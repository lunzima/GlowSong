/*
 * sbitgraft - move embedded bitmap strikes from one TrueType font to another.
 *
 * Reads an outline font and a bitmap-only font, writes a font with the
 * outlines of the first and the strikes of the second. Optionally renames the
 * result to a monospace family. A second mode packs finished faces into a
 * TrueType collection, sharing the tables they have in common.
 *
 * It works on tables, not on byte offsets: it parses the table directory,
 * copies whole tables across by tag, and rebuilds the directory with fresh
 * checksums. EBDT and EBLC index glyphs by ID, so before writing anything it
 * checks that both fonts map every codepoint to the same glyph ID and refuses
 * the job if they do not.
 *
 * No external dependencies. C99.
 *
 *     cc -O2 -std=c99 -o sbitgraft sbitgraft.c
 *     sbitgraft [--mono] outline.ttf bitmap.otb output.ttf
 *     sbitgraft --pack output.ttc face.ttf [face.ttf ...]
 *
 * Licence: MIT.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#define MAX_TABLES 64
#define MAX_FONTS 16

typedef struct {
    char tag[5];
    u32 checksum;
    u8 *data;
    u32 length;
} Table;

typedef struct {
    u32 version;
    Table tables[MAX_TABLES];
    int count;
} Font;

static void die(const char *msg)
{
    fprintf(stderr, "sbitgraft: %s\n", msg);
    exit(1);
}

static u16 rd16(const u8 *p) { return (u16)((p[0] << 8) | p[1]); }
static u32 rd32(const u8 *p)
{
    return ((u32)p[0] << 24) | ((u32)p[1] << 16) | ((u32)p[2] << 8) | p[3];
}
static void wr16(u8 *p, u16 v) { p[0] = (u8)(v >> 8); p[1] = (u8)v; }
static void wr32(u8 *p, u32 v)
{
    p[0] = (u8)(v >> 24); p[1] = (u8)(v >> 16);
    p[2] = (u8)(v >> 8);  p[3] = (u8)v;
}

/* The checksum every SFNT table carries: the sum of its 32-bit words, with
 * the tail zero-padded, taken modulo 2^32. */
static u32 checksum(const u8 *data, u32 length)
{
    u32 sum = 0, i;
    for (i = 0; i + 4 <= length; i += 4)
        sum += rd32(data + i);
    if (i < length) {
        u8 tail[4] = {0, 0, 0, 0};
        memcpy(tail, data + i, length - i);
        sum += rd32(tail);
    }
    return sum;
}

static u8 *slurp(const char *path, long *size)
{
    FILE *f = fopen(path, "rb");
    u8 *buf;
    if (!f) die("cannot open input");
    fseek(f, 0, SEEK_END);
    *size = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (*size < 0) die("cannot size input");
    buf = malloc((size_t)*size);
    if (!buf || fread(buf, 1, (size_t)*size, f) != (size_t)*size)
        die("cannot read input");
    fclose(f);
    return buf;
}

#define TTCF_TAG 0x74746366u

/* Read one table directory sitting at `dir` within `raw`. Each table is copied
 * out, so faces of a collection that point at the same bytes end up with their
 * own editable copies; `collection_write` finds the sharing again on the way
 * out by comparing what it is given. */
static void font_read_dir(Font *font, const u8 *raw, long size, u32 dir)
{
    int i;

    if ((long)dir + 12 > size) die("table directory is past end of file");
    font->version = rd32(raw + dir);
    font->count = rd16(raw + dir + 4);
    if (font->count > MAX_TABLES) die("too many tables");
    if ((long)dir + 12 + 16 * font->count > size)
        die("table directory is truncated");

    for (i = 0; i < font->count; i++) {
        const u8 *rec = raw + dir + 12 + 16 * i;
        u32 offset = rd32(rec + 8), length = rd32(rec + 12);
        /* Compared this way round because offset + length is u32 arithmetic
         * and a crafted font can make it wrap past the file size. */
        if (offset > (u32)size || length > (u32)size - offset)
            die("table runs past end of file");
        memcpy(font->tables[i].tag, rec, 4);
        font->tables[i].tag[4] = 0;
        font->tables[i].checksum = rd32(rec + 4);
        font->tables[i].length = length;
        font->tables[i].data = malloc(length ? length : 1);
        if (!font->tables[i].data) die("out of memory");
        memcpy(font->tables[i].data, raw + offset, length);
    }
}

static void font_read(Font *font, const char *path)
{
    long size;
    u8 *raw = slurp(path, &size);

    if (size < 12) die("input is too small to be a font");
    if (rd32(raw) == TTCF_TAG) die("input is a collection, not a font");
    font_read_dir(font, raw, size, 0);
    free(raw);
}

/* Read every face of a collection. Returns the number read through `n`.
 *
 * The header is the tag, a version, a count, and then one offset per face,
 * each pointing at an ordinary table directory. */
static int collection_read(Font *fonts, const char *path)
{
    long size;
    u8 *raw = slurp(path, &size);
    u32 count;
    int i;

    if (size < 16 || rd32(raw) != TTCF_TAG) die("input is not a collection");
    count = rd32(raw + 8);
    if (count == 0) die("collection holds no fonts");
    if (count > MAX_FONTS) die("too many fonts in collection");
    if ((long)(12 + 4 * count) > size) die("collection header is truncated");

    for (i = 0; i < (int)count; i++)
        font_read_dir(&fonts[i], raw, size, rd32(raw + 12 + 4 * i));
    free(raw);
    return (int)count;
}

/* Whether the file begins with the collection tag, read without committing to
 * either reader. */
static int looks_like_collection(const char *path)
{
    u8 head[4];
    size_t got;
    FILE *f = fopen(path, "rb");
    if (!f) die("cannot open input");
    got = fread(head, 1, 4, f);
    fclose(f);
    return got == 4 && rd32(head) == TTCF_TAG;
}

static Table *font_find(Font *font, const char *tag)
{
    int i;
    for (i = 0; i < font->count; i++)
        if (strcmp(font->tables[i].tag, tag) == 0)
            return &font->tables[i];
    return NULL;
}

static int by_tag(const void *a, const void *b)
{
    return strcmp(((const Table *)a)->tag, ((const Table *)b)->tag);
}

static int head_index(Font *font)
{
    int i;
    for (i = 0; i < font->count; i++)
        if (strcmp(font->tables[i].tag, "head") == 0)
            return i;
    return -1;
}

/* Sort the tables into tag order and clear head.checkSumAdjustment.
 *
 * That field holds a checksum of everything including itself, so it has to be
 * zero while the sums are taken and is filled in afterwards. Leaving the
 * input's stale value there would make the directory entry for head describe
 * bytes that are no longer in the file. */
static void font_prepare(Font *font)
{
    Table *head = font_find(font, "head");
    if (head && head->length >= 12)
        wr32(head->data + 8, 0);
    qsort(font->tables, (size_t)font->count, sizeof(Table), by_tag);
}

/* Write one font's table directory at `dir` and copy each table to the offset
 * given in `place`. Returns the value head.checkSumAdjustment must take: the
 * magic number less the sum of the directory and every table, which is what a
 * sum over the whole file would come to if this font stood alone. */
static u32 emit_directory(u8 *out, u32 dir, Font *font, const u32 *place)
{
    u16 entry_selector = 0, search_range, range_shift;
    u32 sum = 0;
    int i;

    while ((1u << (entry_selector + 1)) <= (u32)font->count)
        entry_selector++;
    search_range = (u16)((1u << entry_selector) * 16);
    range_shift = (u16)(font->count * 16 - search_range);

    wr32(out + dir, font->version);
    wr16(out + dir + 4, (u16)font->count);
    wr16(out + dir + 6, search_range);
    wr16(out + dir + 8, entry_selector);
    wr16(out + dir + 10, range_shift);

    for (i = 0; i < font->count; i++) {
        Table *t = &font->tables[i];
        u8 *rec = out + dir + 12 + 16 * i;
        t->checksum = checksum(t->data, t->length);
        memcpy(rec, t->tag, 4);
        wr32(rec + 4, t->checksum);
        wr32(rec + 8, place[i]);
        wr32(rec + 12, t->length);
        memcpy(out + place[i], t->data, t->length);
        sum += t->checksum;
    }
    sum += checksum(out + dir, 12u + 16u * (u32)font->count);
    return 0xB1B0AFBAu - sum;
}

static void spew(const char *path, const u8 *data, u32 length)
{
    FILE *f = fopen(path, "wb");
    if (!f) die("cannot open output");
    if (fwrite(data, 1, length, f) != length) die("cannot write output");
    fclose(f);
}

static void font_write(Font *font, const char *path)
{
    u32 place[MAX_TABLES];
    u32 cursor = 12u + 16u * (u32)font->count;
    u8 *out;
    int i, h;

    font_prepare(font);
    for (i = 0; i < font->count; i++) {
        place[i] = cursor;
        cursor += (font->tables[i].length + 3) & ~3u;
    }

    out = calloc(cursor, 1);
    if (!out) die("out of memory");
    {
        u32 adjust = emit_directory(out, 0, font, place);
        h = head_index(font);
        if (h >= 0) wr32(out + place[h] + 8, adjust);
    }
    spew(path, out, cursor);
    free(out);
}

/* Pack several fonts into one collection file: a short header of offsets, then
 * one ordinary table directory per font, then the table data.
 *
 * Faces of the same family differ in a handful of small tables and agree on
 * the large ones, so a table whose bytes have already been placed is pointed
 * at again instead of stored twice. That sharing is the whole reason a
 * collection is smaller than the fonts inside it. */
static void collection_write(Font *fonts, int n, const char *path)
{
    u32 place[MAX_FONTS][MAX_TABLES];
    u32 dir_at[MAX_FONTS];
    u32 seen_at[MAX_FONTS * MAX_TABLES];
    Table *seen[MAX_FONTS * MAX_TABLES];
    int found = 0;
    u32 cursor;
    u8 *out;
    int f, i, k;

    for (f = 0; f < n; f++)
        font_prepare(&fonts[f]);

    cursor = 12u + 4u * (u32)n;
    for (f = 0; f < n; f++) {
        dir_at[f] = cursor;
        cursor += 12u + 16u * (u32)fonts[f].count;
    }

    for (f = 0; f < n; f++) {
        for (i = 0; i < fonts[f].count; i++) {
            Table *t = &fonts[f].tables[i];
            u32 at = 0;
            /* head is kept apart from the sharing because each font needs its
             * own checkSumAdjustment written into it, and two fonts pointed at
             * one copy would overwrite each other's. */
            if (strcmp(t->tag, "head") != 0) {
                for (k = 0; k < found; k++)
                    if (seen[k]->length == t->length &&
                        memcmp(seen[k]->data, t->data, t->length) == 0) {
                        at = seen_at[k];
                        break;
                    }
            }
            if (!at) {
                at = cursor;
                cursor += (t->length + 3) & ~3u;
            }
            place[f][i] = at;
            seen[found] = t;
            seen_at[found] = at;
            found++;
        }
    }

    out = calloc(cursor, 1);
    if (!out) die("out of memory");
    memcpy(out, "ttcf", 4);
    wr16(out + 4, 1);
    wr16(out + 6, 0);
    wr32(out + 8, (u32)n);
    for (f = 0; f < n; f++)
        wr32(out + 12 + 4 * f, dir_at[f]);

    for (f = 0; f < n; f++) {
        u32 adjust = emit_directory(out, dir_at[f], &fonts[f], place[f]);
        int h = head_index(&fonts[f]);
        if (h >= 0) wr32(out + place[f][h] + 8, adjust);
    }
    spew(path, out, cursor);
    free(out);
}

/* Decode a format 4 subtable into a codepoint-to-glyph array of 65536 entries.
 * Format 4 is what every font this tool targets uses for the BMP. */
static u16 *cmap_format4(const u8 *sub)
{
    u16 length = rd16(sub + 2);
    u16 seg2 = rd16(sub + 6);
    u16 segs = (u16)(seg2 / 2);
    const u8 *end_codes = sub + 14;
    const u8 *start_codes = end_codes + seg2 + 2;
    const u8 *id_deltas = start_codes + seg2;
    const u8 *id_ranges = id_deltas + seg2;
    u16 *map;
    u16 s;

    if (16u + 4u * seg2 > length) die("cmap subtable is truncated");
    map = calloc(65536, sizeof(u16));
    if (!map) die("out of memory");
    for (s = 0; s < segs; s++) {
        u32 first = rd16(start_codes + 2 * s);
        u32 last = rd16(end_codes + 2 * s);
        u16 delta = rd16(id_deltas + 2 * s);
        u16 range = rd16(id_ranges + 2 * s);
        u32 cp;
        if (first > last) continue;
        for (cp = first; cp <= last && cp < 0xFFFF; cp++) {
            u16 gid;
            if (range == 0) {
                gid = (u16)(cp + delta);
            } else {
                const u8 *at = id_ranges + 2 * s + range + 2 * (cp - first);
                gid = rd16(at);
                if (gid) gid = (u16)(gid + delta);
            }
            map[cp] = gid;
        }
    }
    return map;
}

/* The font's best BMP subtable: Windows Unicode (3,1) if present. */
static u16 *cmap_of(Font *font)
{
    Table *t = font_find(font, "cmap");
    u16 n, i;
    if (!t || t->length < 4) die("input has no cmap");
    n = rd16(t->data + 2);
    for (i = 0; i < n; i++) {
        const u8 *rec = t->data + 4 + 8 * i;
        u16 platform, encoding;
        u32 offset;
        if (4u + 8u * (u32)(i + 1) > t->length) break;
        platform = rd16(rec);
        encoding = rd16(rec + 2);
        offset = rd32(rec + 4);
        if (offset + 4 > t->length) continue;
        if (platform == 3 && encoding == 1 && rd16(t->data + offset) == 4)
            return cmap_format4(t->data + offset);
    }
    die("input has no format 4 Windows Unicode cmap");
    return NULL;
}

/* EBDT and EBLC index by glyph ID, so a transplant is only meaningful when
 * both fonts agree on which glyph each codepoint is. This is the check that
 * makes the tool a font tool rather than a patch for two particular files. */
static void require_same_glyph_order(Font *a, Font *b)
{
    u16 *ma = cmap_of(a), *mb = cmap_of(b);
    u32 cp, differ = 0, shown = 0;

    for (cp = 0; cp < 65536; cp++) {
        if (ma[cp] == mb[cp]) continue;
        differ++;
        if (shown < 5) {
            fprintf(stderr, "sbitgraft: U+%04X is glyph %u in the outline font "
                            "but %u in the bitmap font\n",
                    cp, (unsigned)ma[cp], (unsigned)mb[cp]);
            shown++;
        }
    }
    free(ma);
    free(mb);
    if (differ)
        die("the two fonts do not share a glyph order; refusing to graft");
}

/* Tables that carry the bitmaps. EBSC (scaled strikes) is moved when present
 * so that a font relying on it does not lose half its sizes. */
static const char *SBIT_TABLES[] = {"EBDT", "EBLC", "EBSC", NULL};

static void font_put(Font *font, const char *tag, const u8 *data, u32 length)
{
    Table *t = font_find(font, tag);
    if (!t) {
        if (font->count >= MAX_TABLES) die("no room for another table");
        t = &font->tables[font->count++];
        memcpy(t->tag, tag, 4);
        t->tag[4] = 0;
    } else {
        free(t->data);
    }
    t->length = length;
    t->data = malloc(length ? length : 1);
    if (!t->data) die("out of memory");
    memcpy(t->data, data, length);
}

static void font_drop(Font *font, const char *tag)
{
    Table *t = font_find(font, tag);
    int i;
    if (!t) return;
    i = (int)(t - font->tables);
    free(t->data);
    memmove(font->tables + i, font->tables + i + 1,
            sizeof(Table) * (size_t)(font->count - i - 1));
    font->count--;
}

static void graft(Font *dst, Font *src)
{
    int i;
    if (!font_find(src, "EBDT") || !font_find(src, "EBLC"))
        die("the bitmap font carries no EBDT and EBLC to graft");
    for (i = 0; SBIT_TABLES[i]; i++) {
        Table *t = font_find(src, SBIT_TABLES[i]);
        /* Drop rather than keep what the source lacks: a leftover EBSC from an
         * earlier graft would index strikes that the new EBLC does not have. */
        if (t)
            font_put(dst, SBIT_TABLES[i], t->data, t->length);
        else
            font_drop(dst, SBIT_TABLES[i]);
    }
}

/* Tables that exist only to hold hinting. `gasp` is not among them: it says how
 * to render, not how to grid-fit, and an unhinted font still wants greyscale. */
static const char *HINT_TABLES[] = {"fpgm", "prep", "cvt ", NULL};

/* Composite component flags, from the glyf table specification. */
#define ARG_1_AND_2_ARE_WORDS    0x0001
#define WE_HAVE_A_SCALE          0x0008
#define MORE_COMPONENTS          0x0020
#define WE_HAVE_AN_X_AND_Y_SCALE 0x0040
#define WE_HAVE_A_TWO_BY_TWO     0x0080
#define WE_HAVE_INSTRUCTIONS     0x0100

/* Locate one glyph's instruction block. `at` comes back as the offset of the
 * first instruction byte and `count` as its length, both zero when the glyph
 * carries none. `len` is the glyph's own length within glyf.
 *
 * A simple glyph states the length right after its contour ends. A composite
 * one states it after the last component, so every component has to be stepped
 * over to reach it - there is no other way to know where it lies. */
static void glyph_instructions(const u8 *g, u32 len, u32 *at, u32 *count)
{
    int contours;
    u32 p;

    *at = *count = 0;
    if (len < 10) return;                    /* an empty glyph has no header */
    contours = (short)rd16(g);

    if (contours >= 0) {
        p = 10 + (u32)contours * 2;
        if (p + 2 > len) return;
        *at = p + 2;
        *count = rd16(g + p);
    } else {
        u16 flags;
        p = 10;
        for (;;) {
            if (p + 4 > len) return;
            flags = rd16(g + p);
            p += 4;
            p += (flags & ARG_1_AND_2_ARE_WORDS) ? 4u : 2u;
            if (flags & WE_HAVE_A_SCALE) p += 2;
            else if (flags & WE_HAVE_AN_X_AND_Y_SCALE) p += 4;
            else if (flags & WE_HAVE_A_TWO_BY_TWO) p += 8;
            if (!(flags & MORE_COMPONENTS)) break;
        }
        if (!(flags & WE_HAVE_INSTRUCTIONS)) return;
        if (p + 2 > len) return;
        *at = p + 2;
        *count = rd16(g + p);
    }
    if (*at + *count > len)                  /* truncated; leave it alone */
        *at = *count = 0;
}

/* Rewrite glyf with every instruction block removed, and loca to match.
 *
 * Offsets in a short loca are stored halved, so there each glyph has to start
 * on an even byte and the padding below is what keeps that true once glyphs
 * shrink. **A long loca gets no padding**, and that is deliberate: glyphs
 * arrive already padded to a four-byte boundary, a reader tolerates up to
 * three bytes of slack past the end of a glyph, and one more pad byte is
 * exactly enough to push a glyph that had three over the line. */
static void strip_glyf_instructions(Font *font)
{
    Table *head = font_find(font, "head");
    Table *loca = font_find(font, "loca");
    Table *glyf = font_find(font, "glyf");
    u32 *offsets, cursor = 0, n, i;
    u8 *out;
    int longloca;

    if (!head || !loca || !glyf || head->length < 52 || glyf->length == 0)
        return;

    longloca = rd16(head->data + 50) != 0;
    n = longloca ? loca->length / 4 : loca->length / 2;
    if (n < 2) return;
    n -= 1;                                  /* loca holds numGlyphs + 1 */

    offsets = malloc(sizeof(u32) * (n + 1));
    out = malloc(glyf->length);
    if (!offsets || !out) die("out of memory");

    for (i = 0; i < n; i++) {
        u32 start = longloca ? rd32(loca->data + i * 4)
                             : (u32)rd16(loca->data + i * 2) * 2;
        u32 end = longloca ? rd32(loca->data + (i + 1) * 4)
                           : (u32)rd16(loca->data + (i + 1) * 2) * 2;
        u32 at, count, len;

        offsets[i] = cursor;
        if (end <= start || end > glyf->length)
            continue;                        /* empty glyph, or a bad entry */
        len = end - start;
        glyph_instructions(glyf->data + start, len, &at, &count);

        if (count == 0) {
            memcpy(out + cursor, glyf->data + start, len);
            cursor += len;
        } else {
            /* Everything up to and including the length field, then zero that
             * field, then everything after the instructions. */
            memcpy(out + cursor, glyf->data + start, at);
            wr16(out + cursor + at - 2, 0);
            cursor += at;
            memcpy(out + cursor, glyf->data + start + at + count,
                   len - at - count);
            cursor += len - at - count;
        }
        if (!longloca && (cursor & 1)) out[cursor++] = 0;
    }
    offsets[n] = cursor;

    {
        u32 bytes = longloca ? (n + 1) * 4 : (n + 1) * 2;
        u8 *rebuilt = malloc(bytes);
        if (!rebuilt) die("out of memory");
        for (i = 0; i <= n; i++) {
            if (longloca) wr32(rebuilt + i * 4, offsets[i]);
            else wr16(rebuilt + i * 2, (u16)(offsets[i] / 2));
        }
        font_put(font, "loca", rebuilt, bytes);
        free(rebuilt);
    }
    font_put(font, "glyf", out, cursor);
    free(out);
    free(offsets);
}

/* Remove every trace of hinting: the three tables that hold the programs, the
 * per-glyph instructions, and the maxp fields that size the interpreter.
 *
 * maxp matters. A rasteriser allocates its stack and storage from those
 * numbers, and leaving them describing an interpreter that no longer runs is
 * the kind of inconsistency a validator flags. maxZones drops to 1: with no
 * instructions there is no twilight zone to keep. */
static void strip_hints(Font *font)
{
    Table *maxp;
    int i;

    for (i = 0; HINT_TABLES[i]; i++)
        font_drop(font, HINT_TABLES[i]);

    strip_glyf_instructions(font);

    /* Looked up last on purpose. font_drop closes the gap it leaves with a
     * memmove, so any Table pointer taken before it is stale afterwards. */
    maxp = font_find(font, "maxp");
    if (maxp && maxp->length >= 32) {
        wr16(maxp->data + 14, 1);            /* maxZones */
        wr16(maxp->data + 16, 0);            /* maxTwilightPoints */
        wr16(maxp->data + 18, 0);            /* maxStorage */
        wr16(maxp->data + 20, 0);            /* maxFunctionDefs */
        wr16(maxp->data + 22, 0);            /* maxInstructionDefs */
        wr16(maxp->data + 24, 0);            /* maxStackElements */
        wr16(maxp->data + 26, 0);            /* maxSizeOfInstructions */
    }
}

/* Name IDs that carry the family and therefore need the suffix. ID 2 is the
 * style, which stays "Regular"; ID 5 is the version. */
static int name_takes_suffix(u16 id) { return id == 1 || id == 3 || id == 4 || id == 6; }

/* Byte offset of the last `want` in an SFNT name string, or -1. Offsets are in
 * bytes throughout, since a platform 3 string spends two of them per
 * character. */
static int last_ascii(const u8 *s, u16 len, u16 step, char want, u16 from)
{
    int at = -1;
    u16 i;
    for (i = from; i + step <= len; i = (u16)(i + step))
        if (s[i + step - 1] == (u8)want && (step == 1 || s[i] == 0))
            at = (int)i;
    return at;
}

/* Where the suffix goes inside one name string: at the end, except in the two
 * records that hold a PostScript name. ID 6 is one outright, and reads
 * Family-Style, so the suffix belongs on the family half. ID 3, the unique
 * identifier, conventionally reads `version;vendor;PostScriptName`, so the same
 * cut applies to whatever follows the last semicolon. Both shapes come from the
 * OpenType spec's own recommendation, not from any one font.
 *
 * Anything that does not match the shape falls back to appending, which is
 * always safe. */
static u16 suffix_cut(u16 id, u16 platform, const u8 *s, u16 len)
{
    u16 step = (u16)(platform == 3 ? 2 : 1);
    int semicolon, hyphen;

    if (id != 3 && id != 6) return len;
    semicolon = id == 3 ? last_ascii(s, len, step, ';', 0) : -1;
    if (id == 3 && semicolon < 0) return len;
    hyphen = last_ascii(s, len, step, '-',
                        (u16)(semicolon < 0 ? 0 : semicolon + step));
    return hyphen < 0 ? len : (u16)hyphen;
}

/* Rebuild the name table with a suffix worked into the family-bearing records.
 * Two suffixes: `spaced` for the human-readable names, `tight` for ID 6, the
 * PostScript name, which may not contain a space. Localised records get the
 * same ASCII suffix - the tool has no way to know the word in their language.
 *
 * The table is a header, an array of fixed-size records, and a string pool the
 * records point into; growing a string means rebuilding all three. */
static void rename_family(Font *font, const char *spaced, const char *tight)
{
    Table *t = font_find(font, "name");
    u16 count, i;
    u32 pool_at, out_pool, out_len;
    u8 *out;

    if (!t || t->length < 6) die("input has no name table");
    count = rd16(t->data + 2);
    pool_at = rd16(t->data + 4);
    out_pool = 6u + 12u * count;
    if (out_pool > t->length) die("name table is truncated");

    out_len = out_pool;
    for (i = 0; i < count; i++) {
        const u8 *rec = t->data + 6 + 12 * i;
        u16 platform = rd16(rec), id = rd16(rec + 6), len = rd16(rec + 8);
        u32 grow = 0;
        if (name_takes_suffix(id)) {
            /* Platform 3 strings are UTF-16BE, so an ASCII suffix costs two
             * bytes a character there and one on the Macintosh records. */
            size_t n = strlen(id == 6 ? tight : spaced);
            grow = (u32)(platform == 3 ? n * 2 : n);
        }
        out_len += len + grow;
    }

    out = calloc(out_len, 1);
    if (!out) die("out of memory");
    wr16(out, 0);
    wr16(out + 2, count);
    wr16(out + 4, (u16)out_pool);

    {
        u32 cursor = out_pool;
        for (i = 0; i < count; i++) {
            const u8 *rec = t->data + 6 + 12 * i;
            u16 platform = rd16(rec), id = rd16(rec + 6);
            u16 len = rd16(rec + 8), off = rd16(rec + 10);
            u8 *orec = out + 6 + 12 * i;
            u32 total = len;

            if (pool_at + off + len > t->length) die("name table is truncated");
            memcpy(orec, rec, 12);
            if (name_takes_suffix(id)) {
                const u8 *src = t->data + pool_at + off;
                u16 cut = suffix_cut(id, platform, src, len);
                /* A suffix landing inside the string is going into a PostScript
                 * name, where a space is not allowed; one appended at the end is
                 * going into a name a person reads. */
                const char *suffix = (id == 6 || cut < len) ? tight : spaced;
                size_t n = strlen(suffix), k;
                u32 grown;

                memcpy(out + cursor, src, cut);
                if (platform == 3) {
                    for (k = 0; k < n; k++) {
                        out[cursor + cut + 2 * k] = 0;
                        out[cursor + cut + 2 * k + 1] = (u8)suffix[k];
                    }
                    grown = (u32)n * 2;
                } else {
                    memcpy(out + cursor + cut, suffix, n);
                    grown = (u32)n;
                }
                memcpy(out + cursor + cut + grown, src + cut, len - cut);
                total = len + grown;
            } else {
                memcpy(out + cursor, t->data + pool_at + off, len);
            }
            /* A name table repeats itself - the family shows up in ID 1, 4 and
             * often 16, and again under every language that spells it the same.
             * Point at a string already in the pool rather than storing it
             * twice. */
            {
                u32 at = out_pool, reuse = 0;
                while (at + total <= cursor) {
                    if (memcmp(out + at, out + cursor, total) == 0) {
                        reuse = at;
                        break;
                    }
                    at++;
                }
                wr16(orec + 8, (u16)total);
                wr16(orec + 10, (u16)((reuse ? reuse : cursor) - out_pool));
                if (!reuse)
                    cursor += total;
            }
        }
        out_len = cursor;
    }

    font_put(font, "name", out, out_len);
    free(out);
}

/* Declare the font fixed pitch: post.isFixedPitch and the PANOSE proportion
 * byte, which is what fontconfig and the Windows font menus read. */
static void mark_monospace(Font *font)
{
    Table *post = font_find(font, "post");
    Table *os2 = font_find(font, "OS/2");
    if (!post || post->length < 16) die("input has no usable post table");
    if (!os2 || os2->length < 36) die("input has no usable OS/2 table");
    wr32(post->data + 12, 1);
    os2->data[32 + 3] = 9;          /* panose[3] is bProportion */
}

static void usage(void)
{
    fprintf(stderr,
            "usage: sbitgraft [--mono] [--strip] outline.ttf bitmap.otb out.ttf\n"
            "       sbitgraft --pack out.ttc face.ttf [face.ttf ...]\n"
            "       sbitgraft --strip in.ttf out.ttf\n"
            "\n"
            "  --mono   rename the family and set the fixed-pitch flags\n"
            "  --strip  remove hinting: fpgm, prep, cvt, glyph instructions\n");
}

static int pack(int argc, char **argv)
{
    Font faces[MAX_FONTS];
    int n = argc - 3, i;

    if (n < 1) { usage(); return 2; }
    if (n > MAX_FONTS) die("too many fonts for one collection");
    for (i = 0; i < n; i++)
        font_read(&faces[i], argv[3 + i]);
    collection_write(faces, n, argv[2]);
    return 0;
}

/* `--strip in out`, with nothing to graft. Grafting strikes onto a hinted font
 * and stripping it are separate wishes, and a caller that only has the second
 * one should not have to invent a bitmap font to get it.
 *
 * A collection is accepted here and nowhere else, because this is the mode a
 * reader reaches for: what gets installed is the collection, and telling
 * someone to unpack it, strip two faces and pack them again is telling them to
 * do the tool's job. */
static int strip_only(int argc, char **argv)
{
    Font faces[MAX_FONTS];
    int n, i;

    if (argc != 4) { usage(); return 2; }
    if (looks_like_collection(argv[2])) {
        n = collection_read(faces, argv[2]);
        for (i = 0; i < n; i++)
            strip_hints(&faces[i]);
        collection_write(faces, n, argv[3]);
    } else {
        font_read(&faces[0], argv[2]);
        strip_hints(&faces[0]);
        font_write(&faces[0], argv[3]);
    }
    return 0;
}

int main(int argc, char **argv)
{
    Font outline, bitmap;
    int mono = 0, strip = 0, arg = 1;

    if (argc > 1 && strcmp(argv[1], "--pack") == 0)
        return pack(argc, argv);
    /* `--strip` names two different jobs depending on how many paths follow:
     * on its own it is the whole task, and among the graft options it is one
     * more thing to do on the way through. */
    if (argc == 4 && strcmp(argv[1], "--strip") == 0)
        return strip_only(argc, argv);

    while (arg < argc && argv[arg][0] == '-') {
        if (strcmp(argv[arg], "--mono") == 0) mono = 1;
        else if (strcmp(argv[arg], "--strip") == 0) strip = 1;
        else { usage(); return 2; }
        arg++;
    }
    if (argc - arg != 3) {
        usage();
        return 2;
    }
    font_read(&outline, argv[arg]);
    font_read(&bitmap, argv[arg + 1]);
    require_same_glyph_order(&outline, &bitmap);
    graft(&outline, &bitmap);
    if (strip) strip_hints(&outline);
    if (mono) {
        rename_family(&outline, " Mono", "Mono");
        mark_monospace(&outline);
    }
    font_write(&outline, argv[arg + 2]);
    return 0;
}
