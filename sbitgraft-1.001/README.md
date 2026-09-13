# sbitgraft

把一个 TrueType 字体的内嵌点阵（`EBDT` / `EBLC` / `EBSC`）移植到另一个 TrueType
字体上，并把拼好的字体打包成 TrueType Collection。

## 编译

```sh
make
```

需要一个 C99 编译器，无任何外部依赖。

## 用法

```sh
sbitgraft [--mono] <outline.ttf> <bitmap.otb> <output.ttf>
sbitgraft --pack <output.ttc> <face.ttf> [face.ttf ...]
```

`--mono` 会把结果标记为等宽：置 `post.isFixedPitch` 与 PANOSE 的 proportion
字节，并给族名、全名与 PostScript 名加上 `Mono`。PostScript 名的格式是
`族名-字重`，后缀加在连字符之前，得到 `GlowSongMono-Regular`。本地化的名称记录
拿到的也是 ASCII 的 `Mono`，工具只拿到一个命令行后缀，无从知道对应语言里该怎么
写。

`--pack` 把若干 TTF 装进一个 collection。同一家族的几个 face 只在 `name`、
`post`、`OS/2` 这几张小表上有差别，字节相同的表只存一份，所以 collection 的体积
接近单个 face 而不是它们的总和。`head` 不参与共享：每个 face 需要自己的
`checkSumAdjustment`。

## 前提

内嵌点阵按 glyph ID 索引，因此两个输入必须对同一码点指向同一个 glyph ID。工具
会先逐码点比对两侧的 `cmap`，不一致时打印出前几个冲突的码点并退出，不写任何
文件。

该前提对任意一对满足条件的字体都成立：移植的是表，而非写死的字节偏移。

## 能力边界

会做：解析 SFNT 表目录，按 tag 读写表，重算各表校验和与
`head.checkSumAdjustment`，按 tag 排序重建表目录，改写 `name` 表的变长字符串池，
写出 1.0 版的 collection 头。

不做：解析 `glyf`，重映射 `cmap`，子集化。输入必须是单个字体——工具能写
collection，但读不了 collection。

## 许可

MIT，全文见 `LICENSE`。
