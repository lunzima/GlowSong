"""TrueType hinting, through Chlorophytum.

**Why this exists.** Below 17px the strikes do the drawing and hinting never
runs. At 17px the strikes stop and the outlines take over, and a Song face's
horizontal strokes are about 9 units at upem 256 - half a pixel at 17ppem.
Antialiased, that lands as a mid-grey line where the 16px strike above it drew
solid black.

**Chlorophytum rather than ttfautohint, decided on shape rather than on
contrast.** ttfautohint's `-a sss` makes the strokes far blacker and was
picked for that at first. Measured against the shape the outline actually
describes - the same glyph rendered at eight times the size and box-reduced -
it is the least faithful of the three options and wrecks four times as many
glyphs as leaving the font unhinted: counters fill in, stacked bars swallow the
white between them, strokes shift. Chlorophytum is the most faithful at every
size tried, and more faithful than no hinting at all.

Blur is the price and it is worth paying. A blurred glyph with the right
structure can be read; a crisp glyph with the wrong structure misleads.

**The upstream configuration is used unmodified.** An earlier attempt tuned
`EmBox` to this font's own design and measured better - against the contrast
metric that turned out to be the wrong one. By shape, the stock configuration
wins at 17 and 18px, the two sizes that matter most here, so the tuning is
dropped rather than kept for its own sake.

**Two tools, split by codepoint.** Chlorophytum's passes cover ideographs,
hangul and kana; the letters go to ttfautohint. Neither tool can do both.
Putting Latin through Chlorophytum's ideograph analyser takes a fifth of `g`'s
ink away, because that analyser has an ideograph's em box and no blue zones for
a baseline, an x-height or a descender. Putting ideographs through ttfautohint
is worse still.

**The split is upstream's, and so is the reason it works.** The two cannot
share a font by stacking: run one after the other and the ideographs come out
unrecognisable. What works is hinting each side in its own font and merging -
and the merge needs no renumbering, because a single `instruct` invocation
given several fonts lays out one function and CVT numbering across all of its
outputs. Measured, ideographs hinted that way render identically to a run over
them alone, and the letters identically to plain ttfautohint.

This was nearly abandoned on a false result: an early test appeared to show the
joint invocation breaking the ideographs too. It had a stale configuration
installed beside the toolchain, and was comparing outputs of two different
configurations.

**Runs before the strikes are attached.** Chlorophytum writes the font through
ot-builder, which does not carry EBDT and EBLC across.

Needs ttfautohint, and Node with a set of npm packages, all inside WSL. Without them the step is skipped and the font ships
unhinted, which is correct but softer above 16px.

    python -m build.cli full --no-hinting
"""
import hashlib
import io
import re
import unicodedata
import subprocess
import tempfile
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

from build import ffsimplify

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "build" / "hcfg.json"
WORK = ROOT / "work"

# Where the toolchain lives inside WSL. The configuration has to sit beside its
# node_modules: plugin names in it resolve relative to the configuration's own
# directory, and one kept in this repository gets MODULE_NOT_FOUND.
PROJECT = "$HOME/chlorophytum"
CLI = "node_modules/@chlorophytum/cli/bin/_startup"
JOBS = 8
# The analysis pass is the slow one: an hour and fifty minutes for the GBK
# charset on eight threads, measured. An early estimate of half an hour came
# from extrapolating a sample taken from the start of the Unified Ideographs
# block, where the characters are unusually simple; cost per glyph rises
# steeply with stroke count.
#
# Two and a half hours was not enough: the Base charset is larger again than
# GBK and ran past it. Six leaves room for the largest target on a slower
# machine, and the cache makes a rebuild far cheaper than the first run.
TIMEOUT = 21600

# Names the working directory when the caller does not supply one, so a
# stray one is traceable to the project that left it.
TEMP_PREFIX = "glowsong_hint_"


def wsl_path(path: Path) -> str:
    """Translate a Windows path to its WSL mount point."""
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    rest = resolved.as_posix()[len(resolved.drive):]
    return f"/mnt/{drive}{rest}"


def _wsl(script: str, timeout: int = 120,
         log: Path | None = None) -> subprocess.CompletedProcess:
    """Run `script` inside WSL. With `log`, output goes to that file.

    The long steps take a log rather than a pipe. Chlorophytum prints a
    progress line per percent for an hour, and holding all of that in the
    parent's memory buys nothing: nobody reads it unless the step fails, and
    then a file is more use than a truncated repr. It also leaves something to
    look at while the step is still running.
    """
    command = ["wsl", "-e", "bash", "-lc", script]
    if log is None:
        return subprocess.run(command, capture_output=True, timeout=timeout)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as handle:
        return subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT,
                              timeout=timeout)


def _tail(log: Path, limit: int = 800) -> str:
    """The end of a log, for an error message."""
    try:
        return log.read_bytes()[-limit:].decode("utf-8", errors="replace")
    except OSError:
        return "(no log)"


def available() -> bool:
    """Whether Chlorophytum is usable inside WSL."""
    try:
        return _wsl(f"test -f {PROJECT}/{CLI}").returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _place_config() -> None:
    """Copy this repository's configuration next to the toolchain. See PROJECT."""
    result = _wsl(f"cp {wsl_path(CONFIG)} {PROJECT}/hcfg.json")
    if result.returncode != 0:
        raise RuntimeError(f"could not place hcfg.json: {result.stderr[-200:]!r}")


# The alphabets ttfautohint takes, by codepoint. Everything else - ideographs,
# kana, punctuation, box drawing, full-width forms - goes to Chlorophytum's
# side, where its passes hint what they cover and the rest stays plain.
#
# Split by codepoint rather than by which glyphs Chlorophytum would hint: that
# would mean predicting the configuration's ranges here and drifting from them
# silently. This way the division states what each tool is for.
LETTER_RANGES = (
    (0x0020, 0x007E),   # Basic Latin, digits and ASCII punctuation with it
    (0x00A0, 0x024F),   # Latin-1 Supplement, Extended-A, Extended-B
    (0x0250, 0x02AF),   # IPA Extensions
    (0x0370, 0x03FF),   # Greek and Coptic
    (0x0400, 0x04FF),   # Cyrillic
)


def _is_letter(codepoint: int) -> bool:
    return any(lo <= codepoint <= hi for lo, hi in LETTER_RANGES)


UNHINTED_RANGES = (
    (0x2500, 0x25FF),   # box drawing, block elements, geometric shapes
)

# **Two more, and they are classes rather than ranges because that is how they
# fail.** Every inked codepoint outside CJK, kana and Hangul was swept at
# 12/16/22px, hinted against bare; grouped by what the character *is* - read
# off its own Unicode name - rather than by which block it sits in:
#
#   class                            n   fail   rate   worst case
#   horizontal bar / dash / hyphen  29     8   27.6%   U+FE63 240 vs 64 at 16px
#   small isolated mark             67     9   13.4%   U+00B8  88 vs  0 at 16px
#   letter                         222     2    0.9%   U+0448  43 vs 23 at 12px
#   operator / symbol               52     2    3.8%   U+2225  78 vs 48 at 12px
#
# The two controls - 274 letters and operators - put the noise floor at 4%, so
# a class failing at 14% and 28% is not one bad glyph, it is the model failing
# on a shape: a thin isolated bar or mark, exactly what it also failed on in
# the tiling block. Both are held out for now.
#
# **Held out, not ruled out.** This says the one model available *today* is a
# net loss on these two shapes at these three sizes; it does not say they
# cannot be hinted. Anyone bringing a hinter built for them should read this as
# the measurements to beat, not as a decision that they are unhintable.
# **The rule is whole classes, not points.** A codepoint is held out only as a
# member of one of the classes below; `UNHINTED_SYMBOLS` is generated from them
# and a test asserts the two agree in both directions, so nobody can add a
# single codepoint to the list without holding out the class it belongs to.
# That is deliberate: a class held out a member at a time renders one bar
# hinted and the bar beside it bare, which is the inconsistency the whole
# exercise exists to remove.
#
# The members are listed rather than matched at run time because the other half
# of this lives in `hcfg.json` and Chlorophytum's selector understands ranges
# and nothing else. `_members_of_class` re-derives this list from the names; a
# test compares the two.
CLASS_PATTERNS = (
    re.compile(r"HYPHEN|DASH|MACRON|HORIZONTAL BAR|MINUS SIGN|LOW LINE"
               r"|OVERLINE"),
    re.compile(r"FULL STOP|MIDDLE DOT|BULLET|CEDILLA|DIAERESIS|DEGREE SIGN"
               r"|RING ABOVE|APOSTROPHE|QUOTATION MARK|OGONEK|CARON"
               r"|SMALL (FULL STOP|HYPHEN)|COMMA|ACCENT"),
)
# Read the name through this first: a letter named for its accent is a letter.
SCRIPT_PREFIX = re.compile(
    r"^(LATIN|GREEK|CYRILLIC|CJK|HIRAGANA|KATAKANA|HANGUL|BOPOMOFO)")


def class_of(codepoint: int) -> str | None:
    """Which held-out class this codepoint belongs to, or None."""
    if _claimed(codepoint):
        return None
    name = unicodedata.name(chr(codepoint), "")
    if SCRIPT_PREFIX.search(name):
        return None
    for index, pattern in enumerate(CLASS_PATTERNS):
        if pattern.search(name):
            return ("horizontal bar / dash", "small mark")[index]
    return None


def class_members(codepoints) -> tuple[int, ...]:
    """Every member of every held-out class in `codepoints`."""
    return tuple(sorted(cp for cp in codepoints if class_of(cp)))


def hold_out_faults(codepoints, is_bare=None) -> list[str]:
    """Classes held out a member at a time, as messages.

    **A class is held out whole or not at all.** Holding out the two members
    that measured worst and leaving their neighbours hinted would render one
    bar black and the bar beside it grey - the inconsistency this whole line of
    work exists to remove - and it is what a list built by adding points
    gradually turns into. Both directions are checked: a class member that is
    not held out, and a held-out codepoint that belongs to no class at all.

    `is_bare` defaults to `_is_bare`; the parameter is there so the rule can be
    shown to bite on a list that breaks it.
    """
    is_bare = is_bare or _is_bare
    faults = []
    members = class_members(codepoints)
    by_class = {}
    for cp in members:
        by_class.setdefault(class_of(cp), []).append(cp)
    for name in sorted(by_class):
        held = [cp for cp in by_class[name] if is_bare(cp)]
        if held and len(held) != len(by_class[name]):
            missing = [cp for cp in by_class[name] if not is_bare(cp)]
            faults.append(
                f"class {name!r} is held out for {len(held)} of "
                f"{len(by_class[name])} members; still hinted: "
                + ", ".join(f"U+{cp:04X}" for cp in missing[:6]))
    for cp in sorted(cp for cp in codepoints if is_bare(cp)):
        if class_of(cp) is None and not any(
                lo <= cp <= hi for lo, hi in UNHINTED_RANGES):
            faults.append(f"U+{cp:04X} is held out and belongs to no class")
    return faults
UNHINTED_SYMBOLS = UNHINTED_RANGES + (
    (0x0022, 0x0022),
    (0x0027, 0x0027),
    (0x002C, 0x002E),
    (0x005E, 0x0060),
    (0x00A8, 0x00A8),
    (0x00AB, 0x00AB),
    (0x00AD, 0x00AD),
    (0x00AF, 0x00B1),
    (0x00B4, 0x00B4),
    (0x00B7, 0x00B8),
    (0x00BB, 0x00BB),
    (0x02C6, 0x02C7),
    (0x02C9, 0x02CB),
    (0x2010, 0x2010),
    (0x2013, 0x2015),
    (0x2018, 0x201A),
    (0x201C, 0x201E),
    (0x2022, 0x2022),
    (0x2039, 0x203A),
    (0x2488, 0x249B),
    (0xFE50, 0xFE52),
    (0xFE63, 0xFE63),
)

# What the three upstream passes own. Nothing here is ever held out: they are
# the passes that were measured and chosen for these scripts.
CLAIMED_BY_CHLOROPHYTUM = (
    (0x2E80, 0x2EFF), (0x2F00, 0x2FDF), (0x3000, 0x303F), (0x3040, 0x309F),
    (0x30A0, 0x30FF), (0x3100, 0x312F), (0x3130, 0x318F), (0x31A0, 0x31BF),
    (0x31F0, 0x31FF), (0x3200, 0x32FF), (0x3300, 0x33FF), (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF), (0xA000, 0xA48F), (0xAC00, 0xD7AF), (0xF900, 0xFAFF),
    (0xFE30, 0xFE4F), (0xFF00, 0xFFEF),
)


def _claimed(codepoint: int) -> bool:
    return any(lo <= codepoint <= hi for lo, hi in CLAIMED_BY_CHLOROPHYTUM)


def _is_letter(codepoint: int) -> bool:
    return any(lo <= codepoint <= hi for lo, hi in LETTER_RANGES)


def _goes_to_ttfautohint(codepoint: int) -> bool:
    """The letters. The tiling block is on neither side; see UNHINTED_SYMBOLS."""
    return _is_letter(codepoint)


def _is_bare(codepoint: int) -> bool:
    """Held out of hinting for now, because the model measured a net loss.

    Only shapes the model was measured to fail on: a range it fails on whole
    (box drawing and friends), or a member of one of the two classes the sweep
    found it failing a fifth to a third of the time. Never anything the three
    upstream passes own.
    """
    if _claimed(codepoint):
        return False
    return any(lo <= codepoint <= hi for lo, hi in UNHINTED_SYMBOLS)


def ttfautohint_available() -> bool:
    """Whether ttfautohint is usable inside WSL."""
    try:
        return _wsl("command -v ttfautohint").returncode == 0
    except Exception:  # noqa: BLE001
        return False


def ttfautohint_available() -> bool:
    """Whether ttfautohint is usable inside WSL."""
    try:
        return _wsl("command -v ttfautohint").returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _cut(font: TTFont, codepoints, path: Path) -> None:
    """Write a subset of `font` covering `codepoints`, outlines untouched.

    Through a copy, because subsetting is destructive and the caller's font is
    the one the instructions come back to.
    """
    buffer = io.BytesIO()
    font.save(buffer)
    buffer.seek(0)
    piece = TTFont(buffer)
    options = subset.Options()
    options.hinting = False
    options.notdef_outline = True
    options.layout_features = []
    options.glyph_names = False
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=sorted(codepoints))
    subsetter.subset(piece)
    piece.save(str(path))


def _programs(source: TTFont) -> dict:
    """Every glyph program in `source`, keyed by codepoint."""
    glyf = source["glyf"]
    found = {}
    for codepoint, name in source.getBestCmap().items():
        glyph = glyf[name]
        glyph.expand(glyf)
        program = getattr(glyph, "program", None)
        if program is not None and program.getBytecode():
            found[codepoint] = program
    return found


def _merge(font: TTFont, carrier: TTFont, sources: list) -> TTFont:
    """Put the hinted pieces back on a copy of `font`.

    `carrier` supplies `fpgm`, `prep` and `cvt `; the glyph programs come from
    `sources`, matched by codepoint. This is a straight transplant with no
    renumbering, and it is sound only because one `instruct` produced every
    piece: given several fonts at once, Chlorophytum lays out one function and
    CVT numbering and writes that same one into all of them. Measured, the
    ideographs come back rendering identically to a run over them alone.
    """
    buffer = io.BytesIO()
    font.save(buffer)
    buffer.seek(0)
    merged = TTFont(buffer)

    for tag in ("fpgm", "prep", "cvt "):
        if tag in carrier:
            merged[tag] = carrier[tag]

    glyf, cmap = merged["glyf"], merged.getBestCmap()
    for source in sources:
        for codepoint, program in _programs(source).items():
            name = cmap.get(codepoint)
            if name is None:
                continue
            glyph = glyf[name]
            glyph.expand(glyf)
            glyph.program = program

    limits = merged["maxp"]
    for field in ("maxZones", "maxTwilightPoints", "maxStorage",
                  "maxFunctionDefs", "maxInstructionDefs", "maxStackElements",
                  "maxSizeOfInstructions"):
        highest = max(getattr(source["maxp"], field) for source in sources)
        setattr(limits, field, max(getattr(limits, field), highest))
    return merged


def _cache_for(font: TTFont) -> Path:
    """One cache file per charset. Not one for all of them, and this is why.

    The cache is keyed by a hash of each glyph's geometry, so in principle
    every product could share one: the ideographs the full build analysed
    would come free to the others. Chlorophytum does not keep it that way.
    Its `save` writes back only the entries the run touched - what it hit plus
    what it newly computed - so a build replaces the file rather than adding
    to it. Measured: after the Ext A target the file held 6,580 entries,
    exactly Ext A's glyph count, and the 20,925 from the GBK build before it
    were gone. The next full-charset build then analysed all of them again,
    three hours of work that a cache exists to avoid.

    Splitting by charset means a file is only ever read and written by builds
    that cover the same glyphs, so nothing gets thrown away. Two products over
    one charset - the collection and the hint-free base - share theirs and the
    second is nearly free.

    The name is a digest of the codepoints rather than the product's name:
    what decides whether a cache is usable is the coverage, not what the
    caller chose to call it.
    """
    covered = ",".join(f"{cp:X}" for cp in sorted(font.getBestCmap()))
    digest = hashlib.sha1(covered.encode("ascii")).hexdigest()[:12]
    return WORK / f"chlorophytum-cache-{digest}.gz"


def _run(script: str, what: str, log: Path) -> None:
    result = _wsl(script, timeout=TIMEOUT, log=log)
    if result.returncode != 0:
        raise RuntimeError(f"{what} failed (rc={result.returncode}), "
                           f"log at {log}:\n{_tail(log)}")


def apply(font: TTFont, workdir: Path | None = None,
          cache: Path | None = None, jobs: int = JOBS) -> TTFont:
    """Return a hinted copy of `font`. The input is left alone.

    The font is split by codepoint, hinted by two tools and put back together.
    `LETTER_RANGES` states the division; the module docstring says why there
    has to be one.

    **The two `instruct` runs must be one invocation.** That is what makes the
    pieces mergeable: it lays out a single function and CVT numbering across
    every output, so an ideograph's program reads the same CVT entries in the
    merged font that it read on its own. Run separately, each piece numbers
    from zero and the merge is nonsense.

    Without ttfautohint the split is skipped and the whole font goes to
    Chlorophytum, which is what the font shipped as before: correct, with the
    letters carrying no instructions.
    """
    work = Path(workdir or tempfile.mkdtemp(prefix=TEMP_PREFIX))
    work.mkdir(parents=True, exist_ok=True)
    cache = Path(cache) if cache else _cache_for(font)
    cache.parent.mkdir(parents=True, exist_ok=True)
    _place_config()

    covered = set(font.getBestCmap())
    # The held-out set wins over both sides: `LETTER_RANGES` is a range, and a
    # range cannot express "these two letters are fine and these two marks are
    # not", so the classes have to be able to take a codepoint out of it.
    letters = {cp for cp in covered
               if _goes_to_ttfautohint(cp) and not _is_bare(cp)}
    rest = {cp for cp in covered if not _is_bare(cp)} - letters
    if not letters or not rest or not ttfautohint_available():
        letters, rest = set(), covered

    pieces = []
    if letters:
        plain = work / "hint_letters_plain.ttf"
        _cut(font, letters, plain)
        tuned = work / "hint_letters.ttf"
        _run(f"ttfautohint {wsl_path(plain)} {wsl_path(tuned)}",
             "ttfautohint", work / "ttfautohint.log")
        pieces.append((tuned, work / "hint_letters.gz",
                       work / "hint_letters_out.ttf"))

    body = work / "hint_body.ttf"
    _cut(font, rest, body)
    pieces.append((body, work / "hint_body.gz", work / "hint_body_out.ttf"))

    pairs = " ".join(f"{wsl_path(i)} {wsl_path(h)}" for i, h, _ in pieces)
    triples = " ".join(f"{wsl_path(i)} {wsl_path(h)} {wsl_path(o)}"
                       for i, h, o in pieces)
    _run(
        f"cd {PROJECT} && "
        f"node {CLI} hint -c hcfg.json -h {wsl_path(cache)} -j {jobs} {pairs} && "
        f"node {CLI} instruct -c hcfg.json {triples}",
        "Chlorophytum",
        work / "chlorophytum.log",
    )
    missing = [str(o) for _, _, o in pieces if not o.exists()]
    if missing:
        raise RuntimeError(f"Chlorophytum wrote no output for {missing}")

    outputs = [TTFont(str(o)) for _, _, o in pieces]
    # The letters' piece carries both tools' tables, so it is the one to take
    # `fpgm`, `prep` and `cvt ` from; without it there is only the one piece.
    hinted = _merge(font, outputs[0], outputs)
    # ot-builder sets OVERLAP_SIMPLE on nearly every glyph it writes, and
    # ots-sanitize rejects the whole `glyf` table over it. The same cleanup
    # runs after the simplify pass, for whatever FontForge leaves behind.
    ffsimplify.clear_overlap_flags(hinted)
    return hinted


def is_hinted(font: TTFont) -> bool:
    """Whether a font carries hinting, which decides its gasp ladder."""
    return "fpgm" in font
