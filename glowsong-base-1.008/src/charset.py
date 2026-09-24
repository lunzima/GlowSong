"""Charset definitions.

The character lists are enumerated from Python's own codecs rather than
maintained by hand. A hand-written table leaks characters and cannot be checked
against anything; the codec *is* the reference implementation of CP936.
"""
from functools import lru_cache

EXT_A = range(0x3400, 0x4DB6)            # CJK Ext A, 6582 characters
BOX_DRAWING = range(0x2500, 0x2580)      # box drawing, 128
BLOCK_ELEMENTS = range(0x2580, 0x25A0)   # block elements, 32


def _decode_table(codec: str, hi_range, lo_range) -> set[int]:
    """Every valid two-byte sequence, decoded to the codepoints it covers."""
    # Single-byte range contributes printable ASCII only: 0x00-0x1F are control
    # codes and 0x7F is DEL, none of which need a glyph.
    cps = set(range(0x20, 0x7F))
    for hi in hi_range:
        for lo in lo_range:
            try:
                s = bytes((hi, lo)).decode(codec)
            except UnicodeDecodeError:
                continue
            if len(s) == 1:
                cps.add(ord(s))
    return cps


@lru_cache(maxsize=None)
def gb2312_codepoints() -> frozenset[int]:
    """GB2312-80's byte ranges, decoded through the CP936 mapping.

    Python's own gb2312 codec is deliberately not used. It follows the Unicode
    Consortium's table and maps 0xA1A4 to U+30FB, the katakana middle dot, where
    Microsoft's CP936 maps it to U+00B7. The target is Windows and legacy GDI applications,
    and the slim charset must stay a strict subset of the full one, so both go
    through CP936.
    """
    return frozenset(_decode_table("cp936", range(0xA1, 0xFF), range(0xA1, 0xFF)))


@lru_cache(maxsize=None)
def cp936_codepoints() -> frozenset[int]:
    """Codepoints CP936 (GBK) covers. Low byte spans 0x40-0xFE, skipping 0x7F."""
    lo = [b for b in range(0x40, 0xFF) if b != 0x7F]
    return frozenset(_decode_table("cp936", range(0x81, 0xFF), lo))


_TABULAR = frozenset(BOX_DRAWING) | frozenset(BLOCK_ELEMENTS)

# Characters the two enumerations above do not both reach, named by hand.
#
# Every constant below is here because a byte range cannot reach the character,
# and each says which range.
#
# The euro is the first. CP936 carries it in a single byte, 0x80, but
# Python's cp936 codec rejects that byte instead of decoding it, so enumerating
# the codec never reaches the character and nothing about it is implied by the
# tables above. It has to be added to both builds explicitly.
#
# It is half width: one byte is the test this project decides a width by, and it is the test that wins when the reference font disagrees -
# that font gives the euro 256, but it also gives the thirty accented pinyin
# vowels 128 where the byte count says full, and there the byte count is what
# was followed. Every latin source the pipeline draws from also draws the euro
# to a half cell already.
EURO = 0x20AC

# Windows-1252's non-ASCII letters and punctuation. CP936 has no code point
# for any of them: the code page spent its one non-ASCII single byte on the
# euro and carried nothing else there, and the twenty Latin-1 characters it does
# carry - U+00A4, U+00A7, U+00A8, U+00B0, U+00B1, U+00B7, U+00D7, U+00F7 and the
# twelve accented pinyin vowels - arrive through the tables above already. So
# this is neither a slim-only gap nor a full-only one: the enumeration misses
# all 92, and both builds need the whole list.
#
# Half width on the same byte-count test as the euro, and drawn to a half cell
# by every latin source the pipeline draws from, which is why `latinbitmap` is
# where their strikes come from.
NON_ASCII_LATIN = frozenset({
    0x00A0, 0x00A1, 0x00A2, 0x00A3, 0x00A5, 0x00A6,
    0x00A9, 0x00AA, 0x00AB, 0x00AC, 0x00AD, 0x00AE,
    0x00AF, 0x00B2, 0x00B3, 0x00B4, 0x00B5, 0x00B6,
    0x00B8, 0x00B9, 0x00BA, 0x00BB, 0x00BC, 0x00BD,
    0x00BE, 0x00BF, 0x00C0, 0x00C1, 0x00C2, 0x00C3,
    0x00C4, 0x00C5, 0x00C6, 0x00C7, 0x00C8, 0x00C9,
    0x00CA, 0x00CB, 0x00CC, 0x00CD, 0x00CE, 0x00CF,
    0x00D0, 0x00D1, 0x00D2, 0x00D3, 0x00D4, 0x00D5,
    0x00D6, 0x00D8, 0x00D9, 0x00DA, 0x00DB, 0x00DC,
    0x00DD, 0x00DE, 0x00DF, 0x00E2, 0x00E3, 0x00E4,
    0x00E5, 0x00E6, 0x00E7, 0x00EB, 0x00EE, 0x00EF,
    0x00F0, 0x00F1, 0x00F4, 0x00F5, 0x00F6, 0x00F8,
    0x00FB, 0x00FD, 0x00FE, 0x00FF, 0x0152, 0x0153,
    0x0160, 0x0161, 0x0178, 0x0192, 0x02C6, 0x02DC,
    0x201A, 0x201E, 0x2020, 0x2021, 0x2022, 0x2039,
    0x203A, 0x2122,
})

# CP936's double-byte symbols that GB2312-80 does not have. Every one of them
# *is* in CP936, so `full()` reaches all thirty through the codec and this list
# changes nothing there; naming them is what puts them into `slim()`, which
# walks GB2312's byte ranges and so misses the lot. Full width, by the same
# byte-count test as the euro - and the slim build is the one installed by
# default, so without this list the symbols would be missing from exactly the
# build most users have.
CP936_SYMBOLS = frozenset({
    0x02CA, 0x02CB, 0x02D9, 0x2010, 0x2013, 0x2015,
    0x2025, 0x2035, 0x2105, 0x2109, 0x2121, 0x2196,
    0x2197, 0x2198, 0x2199, 0x2215, 0x221F, 0x2223,
    0x2252, 0x2266, 0x2267, 0x2295, 0x22BF, 0x25BC,
    0x25BD, 0x25E2, 0x25E3, 0x25E4, 0x25E5, 0x2609,
})

# The same GB2312 gap, one block over: the ideographic zero and the squared
# metric, company and abbreviation signs. Two CP936 bytes each and none of them
# inside GB2312's ranges, so again `full()` has them and `slim()` lacks them.
# Full width. `U+3007` is the one that shows up in ordinary text - a date
# written 二〇二六 needs it.
CJK_SYMBOLS = frozenset({
    0x3007, 0x338E, 0x338F, 0x339C, 0x339D, 0x339E,
    0x33A1, 0x33C4, 0x33CE, 0x33D1, 0x33D2, 0x33D5,
})

CP936_EXTRA = frozenset({EURO}) | NON_ASCII_LATIN | CP936_SYMBOLS | CJK_SYMBOLS


@lru_cache(maxsize=None)
def slim() -> frozenset[int]:
    """Slim build, GB2312 level, aimed at low-memory Linux use.

    It holds only GB2312's 6763 characters, so the CP936 codepage bit it sets in
    OS/2 does overstate it. It sets the bit anyway, and `metrics.py` records why:
    a font without it is not merely passed over when an application asks for
    GB2312_CHARSET, it is silently replaced. Tofu on the GBK extensions costs
    less than being unselectable.

    GB2312-80 predates the euro and this build is a strict subset of the full
    one, so `CP936_EXTRA` is added here too and the relation still holds.
    """
    return gb2312_codepoints() | _TABULAR | CP936_EXTRA


@lru_cache(maxsize=None)
def full() -> frozenset[int]:
    """Full build, GBK/CP936 level. This is the one legacy GDI applications need."""
    return cp936_codepoints() | _TABULAR | CP936_EXTRA


@lru_cache(maxsize=None)
def ext_a() -> frozenset[int]:
    """Ext A supplement, shipped as a separate fallback, disjoint from full()."""
    return frozenset(EXT_A) - full()


def _is_hanzi(cp: int) -> bool:
    return 0x4E00 <= cp <= 0x9FA5 or 0x3400 <= cp <= 0x4DB5


def summary() -> dict[str, dict[str, int]]:
    """Glyph composition per build, for verification and size accounting."""
    out = {}
    for name, cps in (("slim", slim()), ("full", full()), ("ext_a", ext_a())):
        han = sum(1 for c in cps if _is_hanzi(c))
        out[name] = {"total": len(cps), "hanzi": han, "non_hanzi": len(cps) - han}
    return out
