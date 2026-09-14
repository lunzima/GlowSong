# Appendix: how desktop toolkits treat this font

This font is half-width ASCII beside full-width ideographs, and it carries
embedded bitmap strikes from 12 to 16 pixels. Both of those are unusual enough
that toolkits disagree about them. This appendix records what each one actually
does, with file and line references, so that a packager or a bug reporter does
not have to rediscover it.

Everything below was read from source, not inferred from behaviour. Line
numbers are only as stable as the revision they came from, so each is named.

| Component | Revision read |
|---|---|
| fontconfig | 2.15.0 |
| cairo | 1.18.2 |
| Pango | 1.54.0 |
| GNOME Terminal | 3.54.2 |
| MATE Terminal | 1.28.0 |
| MATE Control Center | 1.28.0 |
| Qt Base | 6.8.1 |
| KWidgetsAddons | 6.8.0 |
| libXft | 2.3.8 |
| TQt3 | ALT-Linux-TDE/3-tqt3, branch head |
| tdelibs | Fat-Zer/tdelibs, branch head |

The two TDE revisions are branch heads rather than release tags, because TDE
does not publish per-release source trees at a stable URL. Their line numbers
may drift; the surrounding code has been quoted so the site can be found again.

## 1. Where the monospace verdict is made

fontconfig decides this once, when it scans a font into its cache, and every
toolkit below reads the answer rather than working it out again.

`src/fcfreetype.c:2526`, `FcFreeTypeSpacing()`, called from
`FcFreeTypeQueryFaceInternal()` at `:2113`. It walks the character map,
collects at most three distinct advance widths, and then:

```c
2585    if (num_advances <= 1)
2586        return FC_MONO;
2587    else if (num_advances == 2 &&
2588             fc_approximately_equal (fc_min (advances[0], advances[1]) * 2,
2589                                     fc_max (advances[0], advances[1])))
2590        return FC_DUAL;
2591    else
2592        return FC_PROPORTIONAL;
```

The three constants are 100, 90 and 0 respectively, and those numbers appear
again below wherever a toolkit compares against them.

Two points follow from this, and they are the root of everything else in this
document.

It never reads `post.isFixedPitch`, and it never reads the PANOSE proportion
byte. Those two fields are the ones a font is supposed to use to declare itself
fixed pitch, this font sets both, and fontconfig ignores both.

A CJK monospace font therefore cannot be `FC_MONO`. Half-width ASCII and
full-width ideographs are two advances in exactly a 1:2 ratio, which is the
literal definition of `FC_DUAL` on line 2587. The same is true of every other
CJK monospace family; Sarasa Fixed SC and Source Han Mono report 90 as well.
DejaVu Sans Mono reports 100 because all of its glyphs share one advance.

`fc_approximately_equal` allows about three percent of slack, so there is no
arrangement of advance widths that keeps both a half width and a full width and
still reads as `FC_MONO`.

## 2. Who consumes the verdict

### GNOME (GTK 4, Pango)

Pango treats `FC_DUAL` as monospace. `pango/pangofc-fontmap.c:3609`:

```c
3609  pango_fc_family_is_monospace (PangoFontFamily *family)
3610  {
3611    PangoFcFamily *fcfamily = PANGO_FC_FAMILY (family);
3612
3613    return fcfamily->spacing == FC_MONO ||
3614           fcfamily->spacing == FC_DUAL ||
3615           fcfamily->spacing == FC_CHARCELL;
3616  }
```

registered as the family class method at `:3655`.

GTK's own font chooser has no monospace filter; applications install one.
GNOME Terminal does, and it delegates to Pango. `src/profile-editor.cc:997`:

```c
997   monospace_filter (const PangoFontFamily *family,
998                     const PangoFontFace   *face,
999                     gpointer data)
1000  {
1001    return pango_font_family_is_monospace ((PangoFontFamily *) family);
1002  }
```

installed at `:1339` through `gtk_font_chooser_set_filter_func()`.

The font is therefore listed correctly under GNOME with no configuration.

### MATE (GTK 3, Pango)

MATE inherits Pango's definition, and in practice filters less than GNOME does.
`mate-terminal/src/profile-editor.c` has no filter function at all — the file
that carries one in GNOME Terminal has none here — so every installed family is
offered. `mate-control-center/capplets/appearance/appearance-font.c:772` binds a
plain font button to the monospace preference key; the word monospace there
names the setting, not a filter.

The font is listed correctly under MATE, for the simpler reason that nothing
excludes it.

### KDE Plasma (Qt 6)

Qt requires `FC_MONO` exactly. `src/gui/text/unix/qfontconfigdatabase.cpp:411`
reads the property and `:479` reduces it to a boolean:

```c
479      bool fixedPitch = spacing_value >= FC_MONO;
```

which is passed to `QPlatformFontDatabase::registerFont()` at `:495` and
surfaces as `QFontDatabase::isFixedPitch()`. `FC_DUAL` is 90, so the answer is
false.

KDE's font dialog filters on it. `kwidgetsaddons/src/kfontchooser.cpp:862`:

```c
862          if ((fontListCriteria & FixedWidthFonts) > 0 && !QFontDatabase::isFixedPitch(family)) {
863              continue;
864          }
```

reached from `setFamilyBoxItems()` at `:901`, which asks for
`KFontChooser::FixedWidthFonts` whenever the dialog is in fixed-width mode.

Without the fontconfig file shipped beside this font, the monospace face does
not appear in KDE's font dialog when "show fixed width fonts only" is ticked.
It can still be selected by name.

### TDE (TQt3)

TQt3 predates Qt's fontconfig backend and talks to Xft directly, but arrives at
the same rule. `src/kernel/qfontdatabase_x11.cpp:963` defaults the value, `:968`
reads it:

```c
963       spacing_value = XFT_PROPORTIONAL;
...
968       XftPatternGetInteger (font, XFT_SPACING, 0, &spacing_value);
```

and `:1030` applies it:

```c
1030          if (spacing_value < XFT_MONO )
1031              family->fixedPitch = FALSE;
```

`XFT_MONO` is `FC_MONO`, so 90 clears the flag. The same value is mapped back
to an XLFD pitch character at `:1046`, giving `p` rather than `m`.

tdelibs filters on the flag exactly as KDE does.
`tdeui/tdefontdialog.cpp:641`, `TDEFontChooser::getFontList()`:

```c
652          if ((fontListCriteria & FixedWidthFonts) > 0 && !dbase.isFixedPitch(*it)) continue;
```

with a fallback at `:659` for the case where the filter leaves nothing at all.

Xft is a thin layer over fontconfig: `XftListFonts()` is `FcFontList()`, and it
reads the same cache. A `target="scan"` rule in a fontconfig file therefore
reaches TQt3 unchanged, which is why the fix that works for Plasma also works
for Trinity.

### Windows GDI

GDI reads `post.isFixedPitch` and the PANOSE proportion byte, which this font
sets. Classification is correct there without any configuration, and none of
the above applies.

## 3. Embedded bitmaps

The strikes have a separate problem with a similar shape: the default is off,
and it is the toolkit that defaults it, not the distribution.

cairo, `src/cairo-ft-font.c:1779`:

```c
1779      /* Check whether to force use of embedded bitmaps */
1780      if (FcPatternGetBool (pattern,
1781                            FC_EMBEDDED_BITMAP, 0, &bitmap) != FcResultMatch)
1782          bitmap = FcFalse;
```

libXft, `src/xftfreetype.c:549`, reaches the same default by a different route:

```c
549       switch (FcPatternGetBool (pattern, XFT_EMBEDDED_BITMAP, 0, &bitmap)) {
550       case FcResultNoMatch:
551           bitmap = FcFalse;
```

In both, absence means off. A font that carries strikes and says nothing else
is rendered from its outlines.

What rescues it in both is that the suppression is conditional on
antialiasing. cairo, `:1873`, sits inside `if (antialias)` opened at `:1789`:

```c
1873          if (!bitmap)
1874              ft_options.load_flags |= FT_LOAD_NO_BITMAP;
```

libXft, `:559`, states the same condition inline:

```c
559       /* disable bitmaps when anti-aliasing or transforming glyphs */
560       if ((!bitmap && fi->antialias) || fi->transform)
561           fi->load_flags |= FT_LOAD_NO_BITMAP;
```

Qt reaches it a third way. `qfontconfigdatabase.cpp:1116` selects a monochrome
glyph format when antialiasing is off, and
`src/gui/text/freetype/qfontengine_ft.cpp:1145` allows bitmaps only for that
format:

```c
1145      if (transform || obliquen || (format != Format_Mono && !isScalableBitmap()))
1146          load_flags |= FT_LOAD_NO_BITMAP;
```

So on all three stacks, turning antialiasing off at the strike sizes is what
lets the strikes through, and setting `embeddedbitmap` is the belt to that
braces. The configuration shipped with this font sets both.

One interaction is worth knowing about because it is easy to walk into. In
cairo, `hinting=false` becomes `FC_HINT_NONE` at `:1850`, and a hint style of
none forces bitmaps off at `:1868`:

```c
1850      if (!hinting)
1851          hintstyle = FC_HINT_NONE;
...
1868      /* Force embedded bitmaps off if no hinting requested */
1869      if (ft_options.base.hint_style == CAIRO_HINT_STYLE_NONE)
1870        bitmap = FcFalse;
```

A configuration that asks for embedded bitmaps and no hinting, but leaves
antialiasing on, gets neither the hinting nor the bitmaps. The file shipped
here escapes this only because it also turns antialiasing off at those sizes,
which takes the whole block out of the path.

## 4. Hint style

Relevant to any build of this font that carries TrueType instructions.

cairo maps `hintslight` to FreeType's light target at
`src/cairo-ft-font.c:1957`:

```c
1957      case CAIRO_HINT_STYLE_SLIGHT:
1958          load_target = FT_LOAD_TARGET_LIGHT;
1959          break;
```

`FT_LOAD_TARGET_LIGHT` runs FreeType's own autohinter and ignores the
instructions in the font. A hinted build asking for `hintslight` pays for its
instructions and throws them away; it wants `hintfull` or `hintmedium`.

Qt reads `FC_HINT_STYLE` at
`src/gui/text/unix/qfontconfigdatabase.cpp:669`, inside
`defaultHintStyleFromMatch()` at `:645`, and applies it at `:1067`.

## 5. Summary

| Stack | Monospace listing | Embedded bitmaps |
|---|---|---|
| GNOME, GTK 4, Pango | works, `FC_DUAL` accepted | off unless configured |
| MATE, GTK 3, Pango | works, nothing filters | off unless configured |
| KDE Plasma, Qt 6 | needs the scan rule | off unless configured |
| TDE, TQt3, Xft | needs the scan rule | off unless configured |
| Windows GDI | works from the font's own fields | on |

The scan rule referred to is the one in `65-glowsong.conf`:

```xml
<match target="scan">
  <test name="family"><string>GlowSong Mono</string></test>
  <edit name="spacing" mode="assign"><const>mono</const></edit>
</match>
```

It has to be `target="scan"` and not `target="font"`, because every list above
is built from what the scan put in the cache rather than from a match. Run
`fc-cache -f` after installing it, or the old verdict stays in place.

---

To the extent possible under law, The GlowSong Authors have waived all
copyright and related or neighbouring rights to this document. The full text of
the waiver is in `LICENSE-CC0`.

SPDX-License-Identifier: CC0-1.0
