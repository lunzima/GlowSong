"""Vector pipeline: source outlines -> gutted `glyf`.

Per glyph: scale to upem 256, convert cubics to quadratics, round, simplify.
Scaling *before* conversion is what cuts the point count by 27%:
in a low precision space cu2qu needs fewer segments to stay inside tolerance.

Glyph order ascends by codepoint so that CJK gids are contiguous
and the EBLC CJK run needs only one index subtable.

Two source fonts feed this. Latin comes from Liberation Serif, which is
metric-compatible with Times New Roman; everything else comes from Source Han
Serif, whose own latin is a stylised serif that reads nothing like Times.
Nimbus Roman No. 9 L, the redrawn Nimbus Roman, Noto Serif and Roboto Serif were
all tried and all read worse beside the CJK.
"""
import array
import math
from dataclasses import dataclass
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import ttProgram
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphCoordinates

from build import outline, sources, strokes

UPEM = 256
FULL_WIDTH = UPEM
HALF_WIDTH = UPEM // 2

# Gutting parameters, settled by rendering tests.
# MAX_ERR is the cu2qu tolerance, MAX_DEV the sagitta below which an arc is
# flattened; both in target upem units. ffsimplify runs after these.
MAX_ERR = 2.0
MAX_DEV = 1.5

# Design metrics, matching the reference font.
ASCENT, DESCENT, LINE_GAP = 220, -36, 36

# Non-CJK full-width glyphs narrower than this fraction of the cell get centred.
# CJK ink covers 85-94% of the cell, so 0.84 excludes them automatically.
CENTER_THRESHOLD = 0.84

# Vertical reconciliation between the sources. The cell metrics
# come from the reference font while the glyphs come from elsewhere,
# and the two disagree about where things sit. Measured against it.
#
# CJK: Source Han centres its ideographs at 0.381 em while the design cell
# centres at 0.359, so they ride 5 units high. Shifting down centres them.
HAN_Y_SHIFT = -5.0
# Latin: sits low against the CJK and runs slightly short of the reference font's cap
# height of 171.
LATIN_SCALE = 1.02
LATIN_Y_SHIFT = 5.0
# Greek, Cyrillic, accented pinyin and the squared abbreviations: Source Han
# draws these to latin proportions, 21-45% larger than the reference font's. They are also
# what forces the line height up, reaching -69 and 240 against the CJK's
# -55..221. Scaling them uniformly both matches the reference and lets the win
# metrics close back to the original 1.14 em line.
ALPHABET_SCALE = 0.80
OVERSIZED_BLOCKS = (
    range(0x0100, 0x02B0),      # Latin Extended-A/B, incl. accented pinyin
    range(0x0370, 0x0400),      # Greek
    range(0x0400, 0x0500),      # Cyrillic
    range(0x3380, 0x33E0),      # CJK squared abbreviations
)

WORK = Path(__file__).resolve().parent.parent / "work"


@dataclass(frozen=True)
class Source:
    """One source font, normalised onto our 256 upem.

    Two container formats are read. OpenType gives a cmap and `hmtx`; Type 1
    gives a 256-entry Encoding array and per-charstring widths, and no cmap at
    all. Both are reduced to the same four things the pipeline needs: a
    codepoint-to-name map, a drawable glyph set, a scale, and advances.
    """

    label: str
    upem: int
    cmap: dict[int, str]
    glyph_set: object
    advances: dict[str, float]
    reverse_contours: bool

    @property
    def scale(self) -> float:
        return UPEM / self.upem

    @staticmethod
    def from_opentype(path: Path, label: str) -> "Source":
        font = TTFont(str(path))
        hmtx = font["hmtx"]
        # TrueType winds outer contours clockwise, CFF counter-clockwise.
        # Everything downstream assumes counter-clockwise outers - see
        # `strokes._thicken_dx`, whose "outward" direction flips with the
        # winding - so TrueType sources are reversed on the way in. Skipping
        # this makes stroke compensation *thin* the latin instead of thickening
        # it: measured stems came out at 13-27% of their original weight.
        return Source(label, font["head"].unitsPerEm, font.getBestCmap(),
                      font.getGlyphSet(),
                      {n: hmtx[n][0] for n in font.getGlyphOrder()},
                      "glyf" in font)

    def has(self, cp: int) -> bool:
        return cp in self.cmap

    def advance(self, cp: int, fit: "Fit" = None) -> int:
        raw = self.advances[self.cmap[cp]] * self.scale
        return round(raw * (fit.scale if fit else 1.0))

    def convert(self, cp: int, fit: "Fit" = None, max_err: float = MAX_ERR,
                max_dev: float = MAX_DEV) -> Glyph:
        """Scale, cu2qu, round, simplify, normalising the winding."""
        fit = fit or Fit()
        pen = TTGlyphPen(None)
        cu2qu = Cu2QuPen(pen, max_err, reverse_direction=self.reverse_contours)
        size = self.scale * fit.scale
        transform = (size, 0, 0, size, 0, fit.y_shift)
        # Recorded through a decomposing pen so that TrueType composites - the
        # accented letters in most latin faces - arrive as plain contours. A
        # bare TTGlyphPen would keep them as components and has no glyph set to
        # resolve them against.
        recorder = DecomposingRecordingPen(self.glyph_set)
        self.glyph_set[self.cmap[cp]].draw(recorder)
        recorder.replay(TransformPen(cu2qu, transform))
        return contours_to_glyph(
            outline.simplify(glyph_to_contours(pen.glyph()), max_dev=max_dev))


# Fullwidth variants map onto ASCII by subtracting this offset.
FULLWIDTH_OFFSET = 0xFEE0
# Only the *alphanumeric* fullwidth variants come from the latin source. The
# punctuation in that block - comma, period, colon, question mark and the rest -
# is Chinese punctuation and belongs to Source Han: it carries Chinese
# letterforms and, more importantly, Chinese positioning (see
# `needs_centering`). Routing it to latin gave a half-width latin comma sitting
# in the middle of a full cell.
FULLWIDTH_ALNUM = (
    range(0xFF10, 0xFF1A),      # digits
    range(0xFF21, 0xFF3B),      # uppercase
    range(0xFF41, 0xFF5B),      # lowercase
)


@dataclass(frozen=True)
class Fit:
    """Uniform scale and vertical shift applied to a glyph on import.

    The scale is uniform on purpose: scaling y alone would squash the
    letterforms. Full-width glyphs keep their 256 advance either way, and
    `fit_in_full_width` re-centres whatever the scale left narrow.
    """

    scale: float = 1.0
    y_shift: float = 0.0


@dataclass(frozen=True)
class SourceSet:
    """Routes each codepoint to the font that should draw it."""

    han: Source
    latin: Source

    def fit(self, cp: int) -> Fit:
        """Vertical reconciliation for one codepoint. See the constants above."""
        if self.resolve(cp)[0] is self.latin:
            return Fit(LATIN_SCALE, LATIN_Y_SHIFT)
        if 0x2500 <= cp <= 0x259F:
            return Fit()                 # box drawing tiles; leave it alone
        if any(cp in block for block in OVERSIZED_BLOCKS):
            return Fit(ALPHABET_SCALE, 0.0)
        return Fit(1.0, HAN_Y_SHIFT)

    def resolve(self, cp: int) -> tuple[Source, int]:
        """Return the source to draw `cp` from, and the codepoint to draw.

        Latin claims two ranges: printable ASCII, which is everything encoding
        to a single CP936 byte, and the fullwidth *alphanumerics*. A fullwidth A
        is the same letter as A, so drawing it from a second source would put two
        designs of one letter in the font. The euro arrives here the same way
        ASCII does - CP936 puts it in a single byte too, 0x80, which is also why
        `is_full_width` leaves it False.

        Everything else stays with Source Han, including the punctuation that
        shares the fullwidth block, Greek, Cyrillic and accented pinyin. They are
        full-width in a CJK context and are not latin in the sense meant here.
        """
        if any(cp in block for block in FULLWIDTH_ALNUM):
            latin_cp = cp - FULLWIDTH_OFFSET
            if self.latin.has(latin_cp):
                return self.latin, latin_cp
        elif not is_full_width(cp) and self.latin.has(cp):
            return self.latin, cp
        return self.han, cp

    def needs_centering(self, cp: int) -> bool:
        """Whether a full-width glyph should be centred in its cell.

        Only glyphs drawn to *latin* proportions need it: they fill about half
        the cell and, left where the source put them, jam against its left edge.

        **CJK punctuation must not be centred.** Chinese sets the comma, period,
        ideographic comma, colon and semicolon in the left half of the cell and
        leaves the right half empty; that is what makes runs of punctuation and
        line breaking come out right. Centring them moved the ideographic full
        stop from x 11..83 to 92..164, against the reference's 35..91.
        """
        if not is_full_width(cp) or is_ideograph(cp):
            return False
        if self.resolve(cp)[0] is self.latin:
            return True
        return any(cp in block for block in OVERSIZED_BLOCKS)

    def missing(self, codepoints) -> list[int]:
        out = []
        for cp in codepoints:
            source, source_cp = self.resolve(cp)
            if not source.has(source_cp):
                out.append(cp)
        return out


def open_sources(latin: Source | None = None) -> SourceSet:
    """Open the source fonts. `latin` overrides the default, for comparisons."""
    han = WORK / "SourceHanSerifSC-Regular.otf"
    if not han.exists():
        han = sources.extract_source_han_serif_regular(WORK)
    if latin is None:
        path = WORK / "LiberationSerif-Regular.ttf"
        if not path.exists():
            path = sources.extract_liberation_serif_regular(WORK)
        latin = Source.from_opentype(path, "LiberationSerif")
    return SourceSet(han=Source.from_opentype(han, "SourceHanSerif"), latin=latin)


def glyph_name(cp: int) -> str:
    """post format 3 drops these; they only index glyphs during the build."""
    return f"uni{cp:04X}"


def plan_glyph_order(codepoints) -> tuple[list[str], dict[int, str]]:
    """order[0] is always .notdef; the rest ascend by codepoint."""
    names = {cp: glyph_name(cp) for cp in sorted(codepoints)}
    return [".notdef"] + list(names.values()), names


def is_full_width(cp: int) -> bool:
    """True when the codepoint occupies a full cell.

    The test is the CP936 encoded byte count: two bytes means full width.
    Enumerating Unicode blocks instead missed 353 characters - the ellipsis,
    em dash, middle dot, multiplication and division signs, plus/minus, circled
    digits, degree Celsius, almost-equal, and every accented pinyin vowel. They
    are all two-byte in CP936 but scattered across many blocks, so any block
    list will leak. The symptom is punctuation that does not line up with CJK.

    Two classes sit outside CP936 yet are still full width:
    CJK Ext A, which is Han and only reached CP936's successor GB18030; and the
    parts of the box drawing and block element ranges CP936 omits, which must
    match the width of their neighbours or TUI frames break apart.

    The euro is the mirror case: CP936 gives it a byte, but Python's cp936 codec
    does not decode that byte, so the test below raises and the character falls
    through as half width - which is the right answer (see `charset`).
    """
    if 0x3400 <= cp <= 0x4DBF:
        return True
    if 0x2500 <= cp <= 0x259F:
        return True
    try:
        return len(chr(cp).encode("cp936")) == 2
    except (UnicodeEncodeError, ValueError):
        return False


def is_ideograph(cp: int) -> bool:
    return (0x3400 <= cp <= 0x4DBF
            or 0x4E00 <= cp <= 0x9FFF
            or 0xF900 <= cp <= 0xFAFF)


def glyph_to_contours(glyph: Glyph) -> list[outline.Contour]:
    if getattr(glyph, "numberOfContours", 0) <= 0:
        return []
    coords, flags = glyph.coordinates, glyph.flags
    out: list[outline.Contour] = []
    start = 0
    for end in glyph.endPtsOfContours:
        out.append([(int(coords[i][0]), int(coords[i][1]), bool(flags[i] & 0x01))
                    for i in range(start, end + 1)])
        start = end + 1
    return out


def contours_to_glyph(contours: list[outline.Contour]) -> Glyph:
    glyph = Glyph()
    glyph.program = ttProgram.Program()
    glyph.program.fromBytecode(b"")
    if not contours:
        glyph.numberOfContours = 0
        glyph.xMin = glyph.yMin = glyph.xMax = glyph.yMax = 0
        return glyph
    coords: list[tuple[int, int]] = []
    flags: list[int] = []
    ends: list[int] = []
    for contour in contours:
        for x, y, on_curve in contour:
            coords.append((x, y))
            flags.append(0x01 if on_curve else 0x00)
        ends.append(len(coords) - 1)
    glyph.numberOfContours = len(contours)
    glyph.coordinates = GlyphCoordinates(coords)
    glyph.flags = array.array("B", flags)
    glyph.endPtsOfContours = ends
    glyph.recalcBounds(None)
    return glyph


def fit_in_full_width(glyph: Glyph, advance: int = FULL_WIDTH,
                      centre: bool = True) -> Glyph:
    """Seat a non-CJK full-width glyph in its cell: centre it, squeeze if wide.

    Source Han's Greek, Cyrillic and accented pinyin are drawn to *latin*
    proportions - ink covers only 46-70% of the cell - yet CP936 encodes them in
    two bytes, so they are full width. Keeping the source position leaves them
    jammed against the left edge: `a-macron` measured 13 units of bearing on the
    left against 116 on the right.

    They overflow at the other end too. Source Han gives Sha and Shcha an
    advance of 1151, wider than a full cell; scaled to upem 256 their ink runs
    268 and 271 wide and collides with the neighbouring glyph. Seven glyphs in
    the full charset do this, at most 5.7% over. Squeezing them needs the same
    per-edge stroke compensation as the monospace latin, or their stems come out
    lighter than everything around them.

    CJK is excluded on purpose: its cell position is deliberate, and recentring
    it would break alignment with the rest of the CJK.
    """
    if getattr(glyph, "numberOfContours", 0) <= 0:
        return glyph
    contours = glyph_to_contours(glyph)
    lo, hi = outline.x_span(contours)
    squeezed = False

    if hi - lo > advance:
        scale = advance / (hi - lo)
        contours = [[(x * scale, y, on) for x, y, on in c] for c in contours]
        contours = strokes.restore_stroke_widths(contours, scale)
        lo, hi = outline.x_span(contours)
        if hi - lo > advance:                    # compensation overshot; rescale
            factor = advance / (hi - lo)
            contours = [[((x - lo) * factor, y, on) for x, y, on in c]
                        for c in contours]
            lo, hi = 0.0, float(advance)
        squeezed = True

    # A glyph can be narrow enough yet still sit outside the cell - Cyrillic Yu
    # measured 4..260 - so the bounds test cannot be skipped.
    in_bounds = lo >= 0 and hi <= advance
    if not centre:
        if in_bounds:
            return contours_to_glyph(outline.simplify(contours)) if squeezed else glyph
        shift = round(max(0.0, -lo) - max(0.0, hi - advance))
    else:
        if not squeezed and in_bounds and hi - lo >= advance * CENTER_THRESHOLD:
            return glyph
        shift = round((advance - (hi - lo)) / 2 - lo)
    if shift == 0 and not squeezed:
        return glyph
    contours = [[(x + shift, y, on) for x, y, on in c] for c in contours]
    return contours_to_glyph(outline.simplify(contours))


def refit_full_width(font: TTFont, src: "SourceSet") -> list[int]:
    """Re-seat non-CJK full-width glyphs that drifted out of their cell.

    Has to run *after* ffsimplify: FontForge's forcelines and nearlyhvlines snap
    near-axis edges into place, which pushes the odd glyph back out of the cell.
    """
    cmap, glyf, hmtx = font.getBestCmap(), font["glyf"], font["hmtx"]
    touched: list[int] = []
    for cp, name in cmap.items():
        if not is_full_width(cp) or is_ideograph(cp):
            continue
        glyph = glyf[name]
        if getattr(glyph, "numberOfContours", 0) <= 0:
            continue
        lo, hi = outline.x_span(glyph_to_contours(glyph))
        if lo >= 0 and hi <= FULL_WIDTH:
            continue
        glyf[name] = fit_in_full_width(glyph, FULL_WIDTH,
                                       src.needs_centering(cp))
        fitted = glyf[name]
        hmtx[name] = (FULL_WIDTH,
                      int(fitted.xMin) if fitted.numberOfContours > 0 else 0)
        touched.append(cp)
    return touched


def gdi_advance(units: int, ppem: int, upem: int = UPEM) -> int:
    """An advance in font units as GDI rounds it for a given pixel size.

    GDI lays text out from `hmtx`, **not** from the advance stored in
    `EBDT`/`EBLC`, so an embedded bitmap whose advance disagrees with this is
    drawn into a cell of the wrong width: too narrow and the neighbours overlap,
    too wide and they drift apart. Measured through `GetCharWidth32W` (see
    explore/gdi_advances.py), the rounding is half away from zero - 128 units at
    13ppem is exactly 6.5 and becomes 7, not 6.
    """
    return int(math.floor(units * ppem / upem + 0.5))


def glyph_advance(src: SourceSet, cp: int, glyph: Glyph) -> tuple[int, Glyph]:
    """Advance for one codepoint, plus the glyph after any cell fitting.

    Two widths only, full and half, as in the original: the reference font and its monospace
    companion both give every one of their 95 ASCII an advance of 128, and
    differ from each other in nothing but `post.isFixedPitch` and `panose.bProportion`. Latin
    being half-width is what makes English in Song look evenly spaced.

    Keeping latin proportional here was what broke the embedded bitmaps: no
    bitmap latin is drawn to Times' narrow proportions, so the strikes and the
    outlines disagreed on 59-70 of 95 ASCII at every size.
    """
    if is_full_width(cp):
        if not is_ideograph(cp):
            glyph = fit_in_full_width(glyph, FULL_WIDTH, src.needs_centering(cp))
        return FULL_WIDTH, glyph
    return HALF_WIDTH, glyph


def build(src: SourceSet, codepoints, family: str = "GlowSong",
          style: str = "Regular", max_err: float = MAX_ERR,
          max_dev: float = MAX_DEV,
          progress: bool = False) -> TTFont:
    """Build the outline-only TTF. Naming and metrics are metrics.py's job.

    ASCII gets its half-width advance here but keeps its proportional outline;
    reshaping the letterforms to fit is `mono.fit_ascii`, which has to run after
    FontForge and so cannot be folded in.
    """
    order, names = plan_glyph_order(codepoints)
    missing = src.missing(names)
    if missing:
        raise ValueError(f"sources lack {len(missing)} codepoints, "
                         f"first U+{missing[0]:04X}")

    builder = FontBuilder(unitsPerEm=UPEM, isTTF=True)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap(dict(names))

    glyf: dict[str, Glyph] = {".notdef": contours_to_glyph([])}
    hmtx: dict[str, tuple[int, int]] = {".notdef": (FULL_WIDTH, 0)}
    for index, (cp, name) in enumerate(sorted(names.items()), 1):
        source, source_cp = src.resolve(cp)
        glyph = source.convert(source_cp, src.fit(cp), max_err, max_dev)
        advance, glyph = glyph_advance(src, cp, glyph)
        glyf[name] = glyph
        hmtx[name] = (advance, glyph.xMin if glyph.numberOfContours else 0)
        if progress and index % 2000 == 0:
            print(f"  outlines {index}/{len(names)}", flush=True)

    builder.setupGlyf(glyf)
    builder.setupHorizontalMetrics(hmtx)
    builder.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT,
                                  lineGap=LINE_GAP)
    builder.setupNameTable({"familyName": family, "styleName": style})
    builder.setupOS2(version=3, sTypoAscender=ASCENT, sTypoDescender=DESCENT,
                     sTypoLineGap=LINE_GAP, usWinAscent=ASCENT,
                     usWinDescent=-DESCENT)
    builder.setupPost(keepGlyphNames=False)
    return builder.font
