"""Metrics and naming: fill in `name`, `OS/2`, `head`, `post` and `gasp`.

FontBuilder's defaults are not enough for Windows to load the font. It writes
only name IDs 1 and 2, while Windows needs 3 (unique ID), 4 (full name) and 6
(PostScript name) as well. This module fills in every required field and
applies the design metrics and the requirements of legacy GDI applications.
"""
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont, newTable

# Localised family names live in a data file so the source itself stays ASCII.
NAMES_PATH = Path(__file__).resolve().parent / "names.json"


@lru_cache(maxsize=1)
def _names() -> dict:
    return json.loads(NAMES_PATH.read_text(encoding="utf-8"))


VERSION = _names()["version"]
VENDOR_ID = _names()["vendor_id"]

# Design metrics, matching the reference font.
ASCENT, DESCENT, LINE_GAP = 220, -36, 36
WIN_ASCENT, WIN_DESCENT = 220, 36

# OS/2.xAvgCharWidth, which GDI hands applications as tmAveCharWidth. The half
# width, not the mean over the glyph set: applications size a character cell
# from it, and this font is 99% full-width CJK, so the mean would be 255 and
# every cell computed from it would come out twice too wide. The original
# declares 128 for the same reason.
AVG_CHAR_WIDTH = 128

# gasp strategy, following WenQuanYi upstream:
#   <=8px   DOGRAY          too small for anything but greyscale
#   9-16px  GRIDFIT, no AA  this is what keeps the bitmap strikes sharp
#   17px+   GRIDFIT|DOGRAY  outlines with antialiasing
GASP_RANGES = {8: 0x02, 16: 0x01, 0xFFFF: 0x03}

# Smallest strike is 12px; below that there is nothing to show.
LOWEST_REC_PPEM = 8

FSSELECTION_REGULAR = 0x40
CODEPAGE_LATIN1 = 1 << 0        # CP1252
CODEPAGE_GBK = 1 << 18          # CP936


@dataclass(frozen=True)
class FontSpec:
    """One face's identity and characteristics."""

    family_en: str
    ps_name: str
    monospace: bool = False
    gbk_codepage: bool = True
    style: str = "Regular"
    # Which set of notices this face carries. The outline and bitmap sides are
    # distributed separately under incompatible licences and never meet in one
    # file, so neither may claim the other's terms.
    legal: str = "outline"

    @property
    def full_en(self) -> str:
        return f"{self.family_en} {self.style}" if self.style != "Regular" else self.family_en

    @property
    def unique_id(self) -> str:
        return f"{VERSION};{VENDOR_ID};{self.ps_name}"

    @property
    def localised(self) -> dict[str, str]:
        """{language tag: family name} from names.json, keyed by PostScript name."""
        return _names()["faces"].get(self.ps_name, {})

    @property
    def notices(self) -> dict[str, str]:
        """Copyright, licence and licence URL, for name IDs 0, 13 and 14."""
        return _names()["legal"][self.legal]


# The five faces. The full build takes the plain name and the slim
# one carries a GB suffix, so both can be installed side by side.
FULL_PROP = FontSpec("GlowSong", "GlowSong-Regular")
FULL_MONO = FontSpec("GlowSong Mono", "GlowSongMono-Regular",
                     monospace=True)
# The slim build holds only GB2312's 6763 characters, so claiming CP936 does
# overstate it. It claims the codepage anyway: GDI skips any font that does not,
# when an application asks for GB2312_CHARSET, and Chinese Windows applications
# ask for it constantly. Measured - without the bit the font is not merely
# passed over, it is silently replaced by another. Being
# unselectable costs more than tofu on the GBK extensions.
SLIM_PROP = FontSpec("GlowSong GB", "GlowSongGB-Regular")
SLIM_MONO = FontSpec("GlowSong GB Mono", "GlowSongGBMono-Regular",
                     monospace=True)
# Ext A is outside CP936 entirely, and is reached as a fallback rather than
# chosen by charset, so the claim would be both false and useless.
EXT_A = FontSpec("GlowSong ExtA", "GlowSongExtA-Regular",
                 gbk_codepage=False)

# The bitmap-only font is a family of its own: it draws nothing outside 12-16px,
# so an application must be able to tell it apart from a font that does. The
# outline-only base is not - grafting strikes onto it does not make it a
# different typeface, and it ships under the ordinary family names above so the
# merged result needs no renaming.
FULL_BITMAP = FontSpec("GlowSong Bitmap", "GlowSongBitmap-Regular",
                       gbk_codepage=True, legal="bitmap")
SLIM_BITMAP = FontSpec("GlowSong GB Bitmap", "GlowSongGBBitmap-Regular",
                       legal="bitmap")

MAX_FACE_NAME = 31              # LOGFONT.lfFaceName limit


def _set_name(font: TTFont, name_id: int, value: str, *, mac: bool = True) -> None:
    """Write a name record. Windows always; Mac only for ASCII values."""
    table = font["name"]
    table.setName(value, name_id, 3, 1, 0x0409)
    if mac and value.isascii():
        table.setName(value, name_id, 1, 0, 0)


def apply_names(font: TTFont, spec: FontSpec) -> None:
    """Write the full set of name records, including the Chinese family name."""
    if len(spec.family_en) > MAX_FACE_NAME:
        raise ValueError(
            f"family name {spec.family_en!r} exceeds {MAX_FACE_NAME} chars; "
            "Windows truncates it in LOGFONT.lfFaceName"
        )
    font["name"].names = []
    notices = spec.notices
    # Both upstream licences require their notice to travel with the font, so
    # IDs 0, 13 and 14 are an obligation rather than decoration.
    _set_name(font, 0, notices["copyright"], mac=False)
    _set_name(font, 1, spec.family_en)
    _set_name(font, 2, spec.style)
    _set_name(font, 3, spec.unique_id)
    _set_name(font, 4, spec.full_en)
    _set_name(font, 5, f"Version {VERSION}")
    _set_name(font, 6, spec.ps_name)
    _set_name(font, 11, _names()["project_url"])
    _set_name(font, 13, notices["licence"], mac=False)
    _set_name(font, 14, notices["licence_url"])
    # Localised family names, on platform 3 with the language tag from the data
    # file. Style is written alongside so the pair is complete in that language.
    for tag, family in spec.localised.items():
        language = int(tag, 16)
        font["name"].setName(family, 1, 3, 1, language)
        font["name"].setName(spec.style, 2, 3, 1, language)
        font["name"].setName(family, 4, 3, 1, language)


def _measure(font: TTFont, char: str, default: int) -> int:
    """Height of one character's glyph, or the default if it is absent."""
    name = font.getBestCmap().get(ord(char))
    if name is None:
        return default
    g = font["glyf"][name]
    return int(g.yMax) if getattr(g, "numberOfContours", 0) > 0 else default


# The reference font's single line spacing: (220 + 36 + 36) / 256 = 1.14 em.
TARGET_LINE_HEIGHT = ASCENT - DESCENT + LINE_GAP


def ink_extent(font: TTFont) -> tuple[int, int]:
    """(yMax, -yMin) over all ink, the minimum win ascent/descent needed."""
    glyf = font["glyf"]
    ymax, ymin = 0, 0
    for name in font.getGlyphOrder():
        g = glyf[name]
        if getattr(g, "numberOfContours", 0) <= 0:
            continue
        ymax = max(ymax, int(g.yMax))
        ymin = min(ymin, int(g.yMin))
    return ymax, -ymin


def win_metrics(font: TTFont) -> tuple[int, int, int]:
    """Compute (usWinAscent, usWinDescent, lineGap).

    **The win metrics must cover every bit of ink**, because Windows clips to
    them. Measured casualties otherwise: descenders reaching -71, accented
    Cyrillic and box-drawing verticals reaching 240.

    the reference font's own 220/36 cannot be reused. Its latin was drawn for a 256 upem and
    descends only to -34, whereas ours is scaled down from a 1000 or 2048 upem
    design with deeper descenders, so the proportions differ and the ink spills.

    `lineGap` makes up the difference: if the win metrics still fall short of the
    original line height it pads to match, keeping single spacing at 1.14 em in
    legacy GDI applications; if they already exceed it, the gap is zero.
    """
    need_asc, need_desc = ink_extent(font)
    asc = max(ASCENT, need_asc)
    desc = max(-DESCENT, need_desc)
    gap = max(0, TARGET_LINE_HEIGHT - (asc + desc))
    return asc, desc, gap


def apply_os2(font: TTFont, spec: FontSpec) -> None:
    """OS/2: the design metrics plus what legacy GDI applications need."""
    o2 = font["OS/2"]
    o2.version = 3                       # v3: old renderers misread v4 bit 7
    o2.usWeightClass = 400
    o2.usWidthClass = 5
    o2.xAvgCharWidth = AVG_CHAR_WIDTH
    o2.fsType = 0                        # installable embedding, unrestricted
    o2.fsSelection = FSSELECTION_REGULAR
    o2.sFamilyClass = 0
    o2.achVendID = VENDOR_ID
    o2.sTypoAscender = ASCENT
    o2.sTypoDescender = DESCENT
    o2.sTypoLineGap = LINE_GAP
    # These must cover all ink or Windows clips the descenders.
    asc, desc, _ = win_metrics(font)
    o2.usWinAscent = asc
    o2.usWinDescent = desc
    o2.sxHeight = _measure(font, "x", 112)
    o2.sCapHeight = _measure(font, "H", 160)
    o2.usDefaultChar = 0
    o2.usBreakChar = 32
    o2.usMaxContext = 0
    o2.ulCodePageRange1 = CODEPAGE_LATIN1 | (CODEPAGE_GBK if spec.gbk_codepage else 0)
    o2.ulCodePageRange2 = 0
    o2.recalcUnicodeRanges(font, pruneOnly=False)
    cps = sorted(font.getBestCmap())
    o2.usFirstCharIndex = min(cps)
    o2.usLastCharIndex = min(max(cps), 0xFFFF)

    panose = o2.panose
    panose.bFamilyType = 2               # latin text
    panose.bSerifStyle = 2               # cove (serif)
    panose.bWeight = 5
    # 0 (any) proportional, 9 (monospaced) for the mono face, as the reference font does.
    panose.bProportion = 9 if spec.monospace else 0
    for attr in ("bContrast", "bStrokeVariation", "bArmStyle",
                 "bLetterform", "bMidline", "bXHeight"):
        setattr(panose, attr, 0)


def apply_hhea(font: TTFont) -> None:
    """hhea follows the Windows convention and tracks the win metrics.

    Its lineGap pads the line height back towards the original 1.14 em.
    """
    asc, desc, gap = win_metrics(font)
    hhea = font["hhea"]
    hhea.ascender = asc
    hhea.descender = -desc
    hhea.lineGap = gap


def apply_head(font: TTFont, spec: FontSpec) -> None:
    head = font["head"]
    head.macStyle = 0                    # regular; must agree with fsSelection
    head.lowestRecPPEM = LOWEST_REC_PPEM
    head.fontRevision = float(VERSION)
    _ = spec


def apply_post(font: TTFont, spec: FontSpec) -> None:
    post = font["post"]
    post.formatType = 3.0                # drop glyph names, as the reference font does
    post.isFixedPitch = 1 if spec.monospace else 0
    post.italicAngle = 0
    post.underlinePosition = -20
    post.underlineThickness = 12


def apply_gasp(font: TTFont) -> None:
    gasp = newTable("gasp")
    gasp.version = 1
    gasp.gaspRange = dict(GASP_RANGES)
    font["gasp"] = gasp


def apply(font: TTFont, spec: FontSpec) -> None:
    """Fill in every metric and naming table in one go."""
    apply_names(font, spec)
    apply_hhea(font)
    apply_os2(font, spec)
    apply_head(font, spec)
    apply_post(font, spec)
    apply_gasp(font)
