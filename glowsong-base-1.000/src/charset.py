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


@lru_cache(maxsize=None)
def slim() -> frozenset[int]:
    """Slim build, GB2312 level, aimed at low-memory Linux use.

    This build must *not* set the CP936 codepage bit in OS/2. It holds only
    GB2312's 6763 characters, so claiming CP936 is a false declaration and lands
    legacy GDI applications on tofu boxes for the GBK extensions.
    """
    return gb2312_codepoints() | _TABULAR


@lru_cache(maxsize=None)
def full() -> frozenset[int]:
    """Full build, GBK/CP936 level. This is the one legacy GDI applications need."""
    return cp936_codepoints() | _TABULAR


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
