"""Reshape the proportional ASCII into the half-width cell.

Both faces need this, not just the monospace one: ASCII is half-width
throughout, as it is in the original. Squeezing a proportional latin into a
uniform 128-unit cell needs two things: a per-character target width, and stroke
weight compensation.

Narrow characters are *not* stretched. Uniform advances do not mean uniform ink -
in a real monospace font `i` is narrower than `W`. Stretching `|` from 13 units
to 128 just deforms it.
"""
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from build import outline, strokes, vector

HALF_WIDTH = vector.HALF_WIDTH
ASCII_RANGE = range(0x20, 0x7F)

MAX_FIT_ROUNDS = 4
DEFAULT_RATIO = 0.82

# How much of the half-width cell each character's ink should fill, graded by
# character class.
#
# The grading follows GNU Unifont's measured proportions (32-unit half width):
# 62% for the narrow letters, 75% for most letters and digits, 88% for `m` and
# `w`, about 83% for the wide symbols. None of Unifont's glyphs are used - it is
# an unserifed bitmap and the wrong genre - only its *relative* widths.
#
# Two deliberate departures:
#
# 1. Everything runs a little wider than Unifont. Unifont is a simplified bitmap
#    (its `W` is four strokes) whereas serifs need horizontal room. Squeezing
#    capitals to Unifont's 75% crushes them into vertical bars and stands `A`
#    and `V` almost upright - measurably worse than leaving them at 97%.
# 2. Graded by class, not by original width. Same class, same ratio, or the
#    result looks uneven; grading by original width produces oddities like `z`
#    ending up wider than a squeezed `o`.
#
# The values themselves are the reference font's, measured: its ASCII is also
# half width, so the fraction of the cell each of its glyphs inks is exactly
# what this table wants. An earlier set ran one notch narrower throughout
# (0.78/0.82/0.88 against 0.83/0.88/0.97) and spaced running text 35% looser
# than the reference - median gap between letters 27 units against its 20.
#
# Raising a ratio cannot hurt a character that was already narrow enough:
# `_fit_one` only ever compresses, so for `!'|` and `.,:;` the number is a
# ceiling that never binds.
#
# The grading itself is necessary: squeezing only the overwide characters leaves
# mid-width letters like `o e a c` and the digits looking fat next to the narrow
# ones.
#
# A ratio is the *class average*, not the width of every member: `WITHIN_CLASS`
# restores each character's own proportion on top of it.
RATIO: dict[str, float] = {}

# How much of a character's natural proportion survives inside its class.
#
# A flat ratio per class is too blunt. Liberation Serif draws `S` at 0.64 of
# `H`'s ink, and forcing both to 0.82 of the cell widens `S` by 56% against its
# neighbours - it comes out flat and overwide, which is exactly how it reads.
#
# Half width does narrow the range, so the answer is not to keep the proportion
# whole either. Fitted against the reference font, whose own ASCII is half width
# and is what the metrics here follow: sweeping the coefficient and comparing
# every ASCII ink width against it bottoms out at 0.25, cutting the mean error
# from 0.093 to 0.061. It puts `S` at 0.85 of `H` against the reference's 0.86.
#
# Adobe Courier suggests 0.75 by the same measurement, and was tried. It is a
# typewriter face with its own proportions - digits at 0.75 of `H` where the
# reference draws them at 0.83 - and fitting to it moved the whole ASCII set
# away from the design this project follows.
#
# 0.0 is the flat grading this replaced; 1.0 would be the proportional source.
WITHIN_CLASS = 0.25

# No character's ink may pass this much of the cell, whatever its class works
# out to. The glyph is centred in the cell, so the remainder is its bearing on
# both sides; `mwWM@%` already sit at 0.97 and nothing needs to be wider.
CEILING = 0.97

# Ink must keep at least this much cell on either side, in upem 256 units. The
# reference holds its widest letters to exactly this - `W` has 2 - and it is
# what `CEILING` leaves to share between the two sides.
MIN_BEARING = 2.0

# How far optical centring may pull a glyph off its geometric centre.
#
# Unbounded it wrecks the rhythm of a line. `visual_center` reads the ink in the
# x-height band, and for a glyph whose band is offset from its full outline the
# correction runs to nine units: `6` came out with bearings 2 and 20, `7` with
# 21 and 2, so `56` closed to 14 while `67` opened to 41. Likewise `ab` at 27
# against `bc` at 9.
#
# The reference does adjust optically, but barely: its bearings differ by 2
# units at the median and never by more than 8. Half of that 8 is the bound
# here, since a shift of `n` moves both bearings and opens a gap of `2n`.
MAX_OPTICAL_SHIFT = 4.0


def _assign(chars: str, ratio: float, *, override: bool = True) -> None:
    for ch in chars:
        if override or ch not in RATIO:
            RATIO[ch] = ratio


_assign("!'|", 0.12)
_assign(".,:;", 0.25)
_assign("[]`()", 0.47)
_assign("filjt", 0.66)
_assign("mwWM@%", 0.97)
_assign("ABCDEFGHIJKLMNOPQRSTUVXYZ", 0.88, override=False)
_assign("abcdeghknopqrsuvxyz", 0.83, override=False)
_assign("0123456789", 0.83, override=False)
_assign("#$&*+-=~^_<>?/\\\"{}]", 0.88, override=False)

# Ink is allowed this far past a CJK cell. Source Han draws a few CJK glyphs
# slightly outside their em box (`zha` overhangs by one unit); CJK is never
# repositioned, so that overhang is accepted rather than flagged.
IDEOGRAPH_SLACK = 2.0


def target_ink_width(ch: str, target: int = HALF_WIDTH,
                     shares: dict[str, float] | None = None) -> float:
    """How wide this character's ink should end up.

    `shares` carries each character's proportion within its class, measured
    from the source; without it every member of a class gets the same width,
    which is what made `S` come out as wide as `H`.
    """
    ratio = RATIO.get(ch, DEFAULT_RATIO)
    share = (shares or {}).get(ch, 1.0)
    return min(ratio * share, 1.0) * target


def _natural_widths(glyph_set, lookup) -> dict[str, float]:
    """Ink width of each ASCII glyph as the source draws it."""
    out: dict[str, float] = {}
    for cp in ASCII_RANGE:
        name = lookup.get(cp)
        if name is None:
            continue
        pen = BoundsPen(glyph_set)
        glyph_set[name].draw(pen)
        if pen.bounds:
            out[chr(cp)] = pen.bounds[2] - pen.bounds[0]
    return out


def class_shares(natural: dict[str, float]) -> dict[str, float]:
    """Each character's width as a multiple of its class ratio.

    Measured against the class **median**, not its mean: a class is not a tidy
    group of letters - the 0.82 one holds the capitals together with `& - I / ?`
    and a mean would follow those outliers rather than the letters.

    A whole class is then scaled down together if its widest member would
    otherwise pass `CEILING`. Scaling the class keeps the proportion the blend
    just restored; clamping the offender alone would flatten the top of the
    class back into a single width, which is the defect being fixed.
    """
    classes: dict[float, list[str]] = {}
    for ch in natural:
        classes.setdefault(RATIO.get(ch, DEFAULT_RATIO), []).append(ch)

    shares: dict[str, float] = {}
    for ratio, members in classes.items():
        widths = sorted(natural[ch] for ch in members)
        middle = widths[len(widths) // 2] if len(widths) % 2 else (
            (widths[len(widths) // 2 - 1] + widths[len(widths) // 2]) / 2)
        if middle <= 0:
            continue
        group = {ch: 1.0 + WITHIN_CLASS * (natural[ch] / middle - 1.0)
                 for ch in members}
        widest = ratio * max(group.values())
        if widest > CEILING:
            group = {ch: v * CEILING / widest for ch, v in group.items()}
        shares.update(group)
    return shares


def _squeeze(glyph_set, name: str, scale: float, compensate: bool):
    """Compress horizontally, then restore stroke weight. Returns contours.

    Compensation is per edge, driven by each edge's local thickness and angle.
    A single amount for the whole glyph cannot work: stroke weights inside one
    glyph differ by a factor of two (Song's `N` has 9-unit stems against a
    26-unit diagonal). Computing from the stems leaves diagonals thin; scaling
    the amount up for diagonal-heavy characters also scales up that glyph's own
    stems, which is how `N` ended up with stems heavier than its diagonal.
    """
    pen = TTGlyphPen(None)
    glyph_set[name].draw(TransformPen(pen, (scale, 0, 0, 1, 0, 0)))
    contours = vector.glyph_to_contours(pen.glyph())
    if compensate and scale < 1.0:
        contours = strokes.restore_stroke_widths(contours, scale)
    return contours


def _fit_one(glyph_set, name: str, limit: float, target: int,
             compensate: bool):
    """Squeeze one glyph to `limit` of ink, centre it, return the glyf glyph.

    The compensation amount is dynamic per edge, so the scale factor cannot be
    solved for up front the way a single amount could. Iterate instead: squeeze,
    compensate, measure, correct. Converges within two rounds in practice.
    """
    scale = 1.0
    contours = _squeeze(glyph_set, name, scale, compensate)
    for _ in range(MAX_FIT_ROUNDS):
        lo, hi = outline.x_span(contours)
        width = hi - lo
        if width <= limit + 0.5 or width <= 0:
            break
        scale *= limit / width
        contours = _squeeze(glyph_set, name, scale, compensate)

    lo, hi = outline.x_span(contours)
    centre = strokes.visual_center(contours)
    if centre is None:
        centre = (lo + hi) / 2

    # Optical centring is a nudge, not a relocation. Unbounded it both wrecks
    # the rhythm of a line and drives lopsided glyphs into the cell wall - `F`
    # ended up with no right bearing at all. Bound the correction first, then
    # hold the result inside the room the glyph leaves.
    geometric = target / 2 - (lo + hi) / 2
    optical = target / 2 - centre
    shift = geometric + max(-MAX_OPTICAL_SHIFT,
                            min(optical - geometric, MAX_OPTICAL_SHIFT))
    room = target - (hi - lo)
    margin = min(MIN_BEARING, max(room, 0) / 2)
    shift = max(margin - lo, min(shift, target - margin - hi))
    contours = [[(x + shift, y, on) for x, y, on in c] for c in contours]
    return vector.contours_to_glyph(outline.simplify(contours))


def fit_ascii(font: TTFont, target: int = HALF_WIDTH,
              compensate_stems: bool = True) -> int:
    """Reshape the ASCII glyphs in place to a uniform advance. Returns the count.

    FontForge's condenseExtend, which should do this job, does nothing here: it
    needs hinting to identify stems and this project writes none. changeWeight
    thickens uniformly and throws spline errors.
    """
    lookup = font.getBestCmap()
    glyf, hmtx = font["glyf"], font["hmtx"]
    glyph_set = font.getGlyphSet()
    shares = class_shares(_natural_widths(glyph_set, lookup))
    changed = 0

    for cp in ASCII_RANGE:
        name = lookup.get(cp)
        if name is None:
            continue
        if getattr(glyf[name], "numberOfContours", 0) <= 0:
            hmtx[name] = (target, 0)
            continue
        limit = target_ink_width(chr(cp), target, shares)
        glyf[name] = _fit_one(glyph_set, name, limit, target, compensate_stems)
        fitted = glyf[name]
        hmtx[name] = (target,
                      int(fitted.xMin) if fitted.numberOfContours > 0 else 0)
        changed += 1

    return changed


def build_mono(src: vector.SourceSet, codepoints,
               family: str = "GlowSong Mono", **kwargs) -> TTFont:
    """A single face with ASCII reshaped to half width.

    Both faces are built this way; the name is kept because the monospace face
    is what the reshaping exists for.
    """
    font = vector.build(src, codepoints, family=family, **kwargs)
    fit_ascii(font)
    return font


def check(font: TTFont) -> list[str]:
    """Validate monospace correctness. Empty list means it passes.

    Ink overflow is measured with BoundsPen, on the *drawn curve*, not from
    `glyph.xMax`. That field is the control point box, and a quadratic's control
    points always sit outside the curve, so using it flags 700-odd CJK glyphs
    that are in fact fine (the largest phantom overhang measured 12 units).
    """
    problems: list[str] = []
    cmap, glyf, hmtx = font.getBestCmap(), font["glyf"], font["hmtx"]
    glyph_set = font.getGlyphSet()
    for cp, name in cmap.items():
        advance = hmtx[name][0]
        if vector.is_full_width(cp):
            if advance != vector.FULL_WIDTH:
                problems.append(f"U+{cp:04X} full-width advance={advance}, "
                                f"expected {vector.FULL_WIDTH}")
        elif advance != HALF_WIDTH:
            problems.append(f"U+{cp:04X} half-width advance={advance}, "
                            f"expected {HALF_WIDTH}")
        if getattr(glyf[name], "numberOfContours", 0) <= 0:
            continue
        slack = IDEOGRAPH_SLACK if vector.is_ideograph(cp) else 0.5
        pen = BoundsPen(glyph_set)
        glyph_set[name].draw(pen)
        if pen.bounds and pen.bounds[2] > advance + slack:
            problems.append(f"U+{cp:04X} ink right edge {pen.bounds[2]:.0f} "
                            f"exceeds advance {advance}")
    return problems
