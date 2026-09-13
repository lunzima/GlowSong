"""Locate the downloaded source fonts. Does not download anything."""
import re
import tarfile
import zipfile
from functools import lru_cache
from pathlib import Path

SOURCES = Path(__file__).resolve().parent.parent / "sources"

WQY_TAR = SOURCES / "wqy-bitmapsong-bdf.tar.gz"
SHS_ZIP = SOURCES / "SourceHanSerifSC.zip"
LIBERATION_TAR = SOURCES / "liberation.tar.gz"

# X.org bitmap font packages, keyed by short name.
#
# Licences differ and the difference matters for the split distribution:
# misc-fixed and sony are public domain outright, while Schumacher clean is an
# MIT/X11 style licence that requires its copyright notice to travel with any
# redistribution. All three are GPL-compatible.
#
# Only "misc" is used by the build. The other two are the rejected candidates,
# kept so explore/latin_bitmap_style.py can still reproduce the comparison that
# settled the choice. The remaining nine font-*-misc packages were
# surveyed and hold no usable candidate: the CJK ones (isas, jis, daewoo) have
# an empty ASCII range, and mutt and sun are proportional.
XORG_PACKAGES = {
    "misc": SOURCES / "font-misc-misc-1.1.3.tar.xz",
    "sony": SOURCES / "font-sony-misc-1.0.4.tar.xz",
    "clean": SOURCES / "font-schumacher-misc-1.1.3.tar.xz",
}

_SIZE = re.compile(r"^SIZE\s+(\d+)", re.M)


def bdf_pixel_size(text: str) -> int:
    """Pixel size from a BDF's SIZE field.

    Do not parse the filename. WenQuanYi's names do not match the strikes:
    wenquanyi_9pt.bdf is 12px and wenquanyi_13px.bdf is 14px.
    """
    match = _SIZE.search(text)
    if not match:
        raise ValueError("BDF has no SIZE field")
    return int(match.group(1))


def _wqy_members(predicate) -> list[str]:
    with tarfile.open(WQY_TAR) as archive:
        return sorted(n for n in archive.getnames()
                      if n.endswith(".bdf") and predicate(n))


def list_wqy_bdf() -> list[str]:
    """CJK bitmap members, excluding the bundled Liberation Sans latin."""
    return _wqy_members(lambda n: "wenquanyi" in Path(n).name)


def list_liberation_bdf() -> list[str]:
    """The bundled Liberation Sans latin bitmaps (proportional width)."""
    return _wqy_members(lambda n: "Liberation" in Path(n).name)


def read_wqy_bdf(name: str) -> str:
    """BDF is ASCII text; latin-1 decoding keeps every byte intact."""
    with tarfile.open(WQY_TAR) as archive:
        handle = archive.extractfile(name)
        if handle is None:
            raise FileNotFoundError(name)
        return handle.read().decode("latin-1")


@lru_cache(maxsize=None)
def wqy_strikes() -> dict[int, str]:
    """{pixel size: member name}, sizes read from each BDF's SIZE field."""
    out: dict[int, str] = {}
    with tarfile.open(WQY_TAR) as archive:
        for name in list_wqy_bdf():
            head = archive.extractfile(name).read(4096).decode("latin-1")
            size = bdf_pixel_size(head)
            if size in out:
                raise ValueError(f"duplicate {size}px strike: {out[size]} and {name}")
            out[size] = name
    return out


def xorg_available(package: str) -> bool:
    path = XORG_PACKAGES.get(package)
    return path is not None and path.exists()


@lru_cache(maxsize=None)
def read_xorg_bdf(package: str, stem: str) -> str:
    """Read one BDF out of an X.org font package, by font name such as 8x16."""
    path = XORG_PACKAGES[package]
    suffix = f"/{stem}.bdf"
    with tarfile.open(path) as archive:
        for name in archive.getnames():
            if name.endswith(suffix):
                return archive.extractfile(name).read().decode("latin-1")
    raise FileNotFoundError(f"{stem}.bdf not in {path.name}")


def _extract(archive_path: Path, member: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / Path(member).name
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            out.write_bytes(archive.read(member))
    else:
        with tarfile.open(archive_path) as archive:
            out.write_bytes(archive.extractfile(member).read())
    return out


def source_han_serif_regular() -> str:
    with zipfile.ZipFile(SHS_ZIP) as archive:
        found = [n for n in archive.namelist()
                 if n.endswith(".otf") and "Regular" in n]
    if not found:
        raise FileNotFoundError("no Regular weight OTF in the zip")
    return sorted(found, key=len)[0]


def extract_source_han_serif_regular(dest: Path) -> Path:
    return _extract(SHS_ZIP, source_han_serif_regular(), dest)


def liberation_serif_regular() -> str:
    with tarfile.open(LIBERATION_TAR) as archive:
        found = [n for n in archive.getnames()
                 if n.endswith("LiberationSerif-Regular.ttf")]
    if not found:
        raise FileNotFoundError("LiberationSerif-Regular.ttf not in the tarball")
    return found[0]


def extract_liberation_serif_regular(dest: Path) -> Path:
    return _extract(LIBERATION_TAR, liberation_serif_regular(), dest)
