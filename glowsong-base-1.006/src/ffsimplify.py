"""Deeper outline simplification through FontForge's simplify().

FontForge's algorithm beats the hand-written pass. choosehv, nearlyhvlines and
mergelines suit Song especially well: its strokes are already axis-aligned, so
snapping near-axis lines exactly onto the axes both removes points and lines
the strokes up with the pixel grid.

**It also misfits glyphs, and the fit is checked per glyph.** Each glyph is
offered a ladder of fits, loosest first, and keeps the first one that stays
within tolerance of the outline it came in with; failing all of them it keeps
that outline unsimplified.

**The check is a rendered comparison, not a bounding box.** An earlier version
compared boxes and asked only whether the ink had moved outward. That check is
blind to the damage that actually happens: a shallow arch flattens towards a
polygon and a hook at the foot of a glyph slides, and through all of it the box
is unchanged, because the stroke still reaches the same extent in every
direction. Measured against a rendered reference at an error bound of 4.0, the
mean glyph sat 1.6% away from its original shape and the worst 15% away, while
the box check rejected almost nothing. So both outlines are rendered unhinted
at one pixel to the unit and compared. The box check is kept as well - a thin spike costs little area but is
worth rejecting.

**The comparison is made at two scales, and the local one is the one that
matters.** Averaging a difference over a whole glyph dilutes anything confined
to one part of it. The sibling project found this the hard way: a glyph whose
foot the eye read as bent came to 0.78% over the glyph, under a 1% check, while
the worst eighth-em window in it had changed by 11.75%. Here the same check
finds 72.4% of glyphs carrying a window over 3% at the loose bound, against a
mean of 1.6% over the glyph. The whole-glyph figure is kept for fits that drift
everywhere at once, and it does still turn down fits the local check passes.

**A ladder beats simply tightening the bound.** The damage is uneven, so a
uniform bound pays everywhere for a fault that is concentrated. Measured over a
1,524-glyph sample, the ladder holds every glyph inside both tolerances while
taking 63% of them at the middle rung and sending only 1% back to their
originals; no single bound does that.

**This is the expensive correction.** Unchecked at 4.0 the pass took glyf to
89.0% of what it was given; checked at both scales it takes it to 95.0%. Six
points of the saving were being bought with damage, and giving that up is the
right trade - but it is worth recording that this step is no longer the 11% win
it was first measured as.

Some damage does not respond to the bound at all: what moves a near-axis
segment is `forcelines` and `choosehv` snapping it onto the axis, which is
independent of the error bound. Those glyphs fall through the whole ladder and
keep their original outlines, which is the right answer for them.

**Dropping flags is not the answer, which is worth recording because it is the
obvious first guess.** Without `forcelines` the worst bulge gets six times worse
- 156 units - and the file is no smaller.

**FontForge's output font is not used.** Only `glyf` is transplanted back, by
codepoint. FontForge inserts `.null` and `nonmarkingreturn`, disturbing the
glyph order; downgrades `post` to format 2, putting glyph names back on disk;
and adds `FFTM` and `GDEF`. Transplanting keeps the table layout ours.

Needs python3-fontforge inside WSL, and freetype-py and Pillow here for the
comparison. Without any of them the step is skipped: a larger font, but a
correct one. It is deliberately not possible to simplify without checking.
"""
import array
import subprocess
import tempfile
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

try:
    import freetype
    from PIL import Image, ImageChops
except ImportError:  # noqa: BLE001
    freetype = Image = ImageChops = None

# Tried loosest first. The first fit a glyph passes is the one it keeps, so the
# rungs below the top are reached only by the glyphs the top one damages.
ERROR_BOUNDS = (4.0, 1.0, 0.25)

# How far a glyph's shape may move over the glyph as a whole, as a percentage
# of its ink area. This is the check that catches a fit which drifts everywhere
# at once; it is not the one that catches local damage, and on its own it let a
# visibly bent foot through in the sibling project.
DEVIATION_TOLERANCE = 1.0

# The local check. The window is an eighth of the em: wide enough to hold a
# component like the foot of a glyph or the shoulder of an `n`, narrow enough
# that damage confined to one does not average away.
CELL_DIVISOR = 8

# How much of any one window's area may change, as a percentage. Calibrated
# against sight rather than chosen: in the sibling project the glyphs that
# looked untouched at the loose bound topped out at 2.0 and the ones with
# damage the eye had already found began at 5.1, so three sits in the gap. The
# same figure is used here - the two fonts share the metric - and this font's
# own distribution agrees, with 72.4% of glyphs over 3% at the loose bound
# against 8.1% over 10%.
#
# It costs 0.8% of glyf over the whole-glyph check alone.
CELL_TOLERANCE = 3.0

# How far a glyph's ink may move outward before its fit is rejected, in upem-256
# units. Two is an eighth of a pixel at 16ppem: under it lies the ordinary noise
# of refitting a curve, over it lies a spike on a stroke.
BULGE_TOLERANCE = 2.0

FLAGS = ("choosehv", "mergelines", "nearlyhvlines", "forcelines")

_SCRIPT = '''
import sys, fontforge
src, dst, eb = sys.argv[1], sys.argv[2], float(sys.argv[3])
flags = tuple(x for x in sys.argv[4].split(",") if x)
f = fontforge.open(src)
for g in f.glyphs():
    if g.foreground.isEmpty():
        continue
    try:
        g.simplify(eb, flags) if flags else g.simplify(eb)
        g.round()
    except Exception as exc:
        print("warn", g.glyphname, exc, file=sys.stderr)
f.generate(dst)
'''


def wsl_path(p: Path) -> str:
    """Translate a Windows path to its WSL mount point."""
    resolved = p.resolve()
    drive = resolved.drive.rstrip(":").lower()
    rest = resolved.as_posix()[len(resolved.drive):]
    return f"/mnt/{drive}{rest}"


def available() -> bool:
    """Whether the step can run: FontForge in WSL, and a rasteriser here.

    The rasteriser is as much a requirement as FontForge. Simplifying without
    checking the result is what damaged the outlines this check exists to
    catch, so its absence skips the step rather than relaxing it.
    """
    if freetype is None:
        return False
    try:
        r = subprocess.run(
            ["wsl", "-e", "python3", "-c", "import fontforge"],
            capture_output=True, timeout=60,
        )
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _bounds(glyph_set, name: str):
    """The drawn outline's box, not the control-point box.

    A quadratic's control points sit outside the curve it draws, so `glyph.yMax`
    reads high - by 65 units on the worst glyph measured. Comparing those would
    reject fits that are perfectly good.
    """
    pen = BoundsPen(glyph_set)
    glyph_set[name].draw(pen)
    return pen.bounds


def _bulge(before, after) -> float:
    """How far the ink moved outward, on its worst side. Negative means it
    shrank, which simplification is allowed to do."""
    if before is None or after is None:
        return 0.0
    return max(after[3] - before[3], before[1] - after[1],
               after[2] - before[2], before[0] - after[0])


_LOAD = None if freetype is None else (
    freetype.FT_LOAD_RENDER | freetype.FT_LOAD_NO_HINTING)


def _probe(path: Path, ppem: int):
    """A face for rendering the comparison, at one pixel to the font unit."""
    face = freetype.Face(str(path))
    face.set_pixel_sizes(0, ppem)
    return face


def _render(face, codepoint: int):
    """One glyph, unhinted. Returns (top, left, image), or None if it is blank.

    `top` counts up from the baseline to the image's first row and `left`
    across to its first column, which is what places two renderings of
    different sizes in a common frame.
    """
    face.load_char(codepoint, _LOAD)
    bitmap, slot = face.glyph.bitmap, face.glyph
    if not (bitmap.width and bitmap.rows):
        return None
    raw = bytes(bitmap.buffer)
    if bitmap.pitch != bitmap.width:
        rows = bytearray()
        for row in range(bitmap.rows):
            start = row * bitmap.pitch
            rows += raw[start:start + bitmap.width]
        raw = bytes(rows)
    image = Image.frombytes("L", (bitmap.width, bitmap.rows), raw)
    return slot.bitmap_top, slot.bitmap_left, image


def _mass(image) -> int:
    """Total coverage, summed in C rather than over 65,000 Python integers."""
    return sum(value * count for value, count in enumerate(image.histogram()))


def _peak(image) -> int:
    """The brightest value present, read off the histogram.

    Through the histogram rather than the pixels: it is a C-level scan either
    way, and it does not depend on which of Pillow's data accessors the
    installed version prefers.
    """
    return max((value for value, count in enumerate(image.histogram()) if count),
               default=0)


def _deviation(reference, candidate, cell: int) -> tuple[float, float]:
    """How far the candidate moved: over the whole glyph, and at worst locally.

    The first figure is the symmetric difference as a percentage of the ink.
    The second is the most that any one `cell`-sized window of the image
    changed, as a percentage of that window's own area.

    **The second exists because the first hides exactly the damage that gets
    noticed.** 慧 has fifteen strokes and its foot is a fifth of its ink, so a
    plainly bent foot came to 0.78% over the glyph and passed a 1% check; the
    worst window in it had changed by 11.75%. Averaging over a glyph dilutes
    anything confined to one component by as much as twenty-five times.

    **The window is scored against its area, not against its ink.** Dividing by
    the ink in the window puts a vanishing denominator under a sparse corner:
    tried, it reported a glyph that looked untouched at 12.5% because two grey
    levels of noise sat over almost no ink. Skipping sparse windows instead
    leaves a hole where a thin stroke can move unseen. Area has neither
    problem, and ranks the sample the way sight does.
    """
    if reference is None:
        return (0.0, 0.0) if candidate is None else (100.0, 100.0)
    if candidate is None:
        return 100.0, 100.0
    (r_top, r_left, r_image), (c_top, c_left, c_image) = reference, candidate
    top, left = max(r_top, c_top), min(r_left, c_left)
    width = max(r_left + r_image.width, c_left + c_image.width) - left
    height = top - min(r_top - r_image.height, c_top - c_image.height)

    frames = []
    for glyph_top, glyph_left, image in (reference, candidate):
        frame = Image.new("L", (width, height), 0)
        frame.paste(image, (glyph_left - left, top - glyph_top))
        frames.append(frame)

    difference = ImageChops.difference(*frames)
    ink = _mass(frames[0])
    whole = _mass(difference) / ink * 100.0 if ink else 0.0
    # BOX reduction averages each window, so a pixel of the reduced image is
    # the fraction of that window's area which changed.
    windows = difference.resize((max(1, width // cell), max(1, height // cell)),
                                Image.BOX)
    return whole, _peak(windows) / 255.0 * 100.0


def _run(source: Path, error_bound: float, flags: tuple[str, ...],
         work: Path) -> tuple[TTFont, Path]:
    """One FontForge pass over the whole font. Returns its output and its path.

    The error bound goes into the file name: the passes share a working
    directory, and reusing one name would have a later pass overwrite an
    earlier one before it has been read.
    """
    tag = str(error_bound).replace(".", "_")
    dst_path = work / f"ff_dst_{tag}.ttf"
    script = work / "ff_run.py"
    # newline is explicit: this script runs under python3 inside WSL, and
    # write_text on Windows translates line endings by default.
    # .gitattributes covers files in the repo, not ones made at runtime.
    script.write_text(_SCRIPT, encoding="utf-8", newline="\n")

    cmd = [
        "wsl", "-e", "python3", wsl_path(script),
        wsl_path(source), wsl_path(dst_path),
        str(error_bound), ",".join(flags),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=3600)
    if r.returncode != 0 or not dst_path.exists():
        raise RuntimeError(
            f"FontForge failed (rc={r.returncode}): {r.stderr[-400:]!r}"
        )

    return TTFont(str(dst_path)), dst_path


def simplify(
    font: TTFont,
    error_bounds: tuple[float, ...] = ERROR_BOUNDS,
    flags: tuple[str, ...] = FLAGS,
    workdir: Path | None = None,
    tolerance: float = BULGE_TOLERANCE,
    deviation: float = DEVIATION_TOLERANCE,
    local: float = CELL_TOLERANCE,
) -> int:
    """Replace the font's glyf in place with FontForge's simplified version.

    Returns the number of glyphs replaced. Pairs by cmap codepoint, so it does
    not depend on glyph order or glyph names.

    Each glyph takes the loosest fit that passes all three checks: no window of
    it changed by more than `local`, the glyph as a whole moved less than
    `deviation`, and its ink did not push outward by more than `tolerance`.
    Failing every fit it keeps the outline it came in with, and a glyph
    FontForge simplified away entirely is kept as well.

    The three catch different failures and all three earn their place. Over a
    1,471-glyph sample the whole-glyph check still turned down 128 fits the
    local one passed, and the local one is the only thing that sees damage
    confined to one component.

    `hmtx`'s lsb **must** be resynced afterwards, and this does it. FontForge
    moves contour bounds - `zo` in hiragana had its xMin go from 25 to 13 -
    while the old lsb stays behind. The spec says lsb equals xMin, and when they
    disagree fontTools shifts the whole glyph by the difference on draw: that
    hiragana came out 12 units to the right, ink reaching 260 and bursting out
    of its full-width cell. The offset exists only at draw time, so no check
    that reads `glyph.coordinates` can see it.
    """
    work = workdir or Path(tempfile.mkdtemp(prefix="ffsimp_"))
    work.mkdir(parents=True, exist_ok=True)

    # lsb first, and on the source FontForge reads. FreeType shifts a glyph by
    # lsb - xMin even with hinting off, so a disagreement between the two moves
    # the rendering sideways and the comparison measures the offset instead of
    # the shape: 37 units of skew came out as 37 units of shift. Bounds are
    # refreshed first because `save` recalculates them, and syncing against a
    # stale xMin would write exactly that disagreement into the file.
    glyf = font["glyf"]
    for name in font.getGlyphOrder():
        glyf[name].recalcBounds(glyf)
    sync_lsb(font)
    source = work / "ff_src.ttf"
    font.save(str(source))

    before = font.getGlyphSet()
    original = {cp: _bounds(before, name)
                for cp, name in font.getBestCmap().items()}

    candidates = [_run(source, bound, flags, work) for bound in error_bounds]

    ppem = font["head"].unitsPerEm
    cell = max(1, ppem // CELL_DIVISOR)
    reference_face = _probe(source, ppem)
    probes = [_probe(path, ppem) for _, path in candidates]
    # Hoisted: getGlyphSet builds a new one on every call, and the loop below
    # would ask for one per glyph per rung.
    glyph_sets = [candidate.getGlyphSet() for candidate, _ in candidates]
    charmaps = [candidate.getBestCmap() for candidate, _ in candidates]

    replaced = 0
    for cp, name in font.getBestCmap().items():
        reference = _render(reference_face, cp)
        for (candidate, _), probe, glyph_set, charmap in zip(
                candidates, probes, glyph_sets, charmaps):
            other = charmap.get(cp)
            if other is None:
                continue
            g = candidate["glyf"][other]
            # FontForge can simplify a glyph away entirely; keep the original.
            if (getattr(g, "numberOfContours", 0) <= 0
                    and glyf[name].numberOfContours > 0):
                continue
            if _bulge(original[cp], _bounds(glyph_set, other)) > tolerance:
                continue
            whole, worst = _deviation(reference, _render(probe, cp), cell)
            if whole > deviation or worst > local:
                continue
            glyf[name] = g
            replaced += 1
            break
    clear_overlap_flags(font)
    sync_lsb(font)
    return replaced


# Simple-glyph flag bit 6. Reserved until 2021, OVERLAP_SIMPLE since. Two steps
# here produce it: FontForge leaves a handful behind on the glyphs it rewrites,
# and Chlorophytum's writer, ot-builder, sets it on nearly every glyph it emits
# - 21,914 of 21,917 measured. A handful is already enough for `ots-sanitize`
# 8.2.1 to reject the whole `glyf` table, so it is cleared after both steps.
#
# Nothing renders differently for the want of it: the flag only says that a
# glyph's contours may overlap, and every rasteriser in use handles overlap
# unconditionally.
OVERLAP_SIMPLE = 0x40


def clear_overlap_flags(font: TTFont) -> int:
    """Clear flag bit 6 on every simple glyph. Returns the number changed.

    See OVERLAP_SIMPLE: the writers set it, the validator refuses it, and no
    rasteriser needs it.
    """
    glyf = font["glyf"]
    changed = 0
    for name in font.getGlyphOrder():
        glyph = glyf[name]
        glyph.expand(glyf)
        flags = getattr(glyph, "flags", None)
        if flags is None:
            continue
        if any(flag & OVERLAP_SIMPLE for flag in flags):
            glyph.flags = array.array(
                "B", (flag & ~OVERLAP_SIMPLE for flag in flags))
            changed += 1
    return changed


def sync_lsb(font: TTFont) -> int:
    """Align each hmtx lsb with its glyph's actual xMin. Returns the count."""
    glyf, hmtx = font["glyf"], font["hmtx"]
    fixed = 0
    for name in font.getGlyphOrder():
        g = glyf[name]
        xmin = int(g.xMin) if getattr(g, "numberOfContours", 0) > 0 else 0
        adv, lsb = hmtx[name]
        if lsb != xmin:
            hmtx[name] = (adv, xmin)
            fixed += 1
    return fixed
