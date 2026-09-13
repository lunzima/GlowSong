# 星霞宋体 GlowSong

中文宋体的轮廓部分。可以单独安装，也可以与「星霞点阵体」拼合；拼合后在 12–16px
走点阵，字形锐利。

族名就是「星霞宋体」/ `GlowSong`。文件名里的 Base 指这份下载还没有点阵，不是另
一款字体，所以拼合出来的成品不需要改名，也不该与这份同时安装。

## 内容

| 文件 | 说明 |
|---|---|
| `GlowSongBase-Regular.ttf` | GBK 全集 |
| `GlowSongGBBase-Regular.ttf` | GB2312 子集 |
| `GlowSongExtA-Regular.ttf` | CJK 扩展 A 的缺字回退，无需拼合 |
| `src/` | 生成上面三个文件的矢量管线源码 |

## 安装

```sh
mkdir -p ~/.local/share/fonts
cp *.ttf ~/.local/share/fonts/
fc-cache -f
```

要点阵的话先别装，按「星霞点阵体」的说明拼合后再装成品。

## 设计要点

`unitsPerEm` 为 256，与 16×16 的点阵档对齐，坐标均为小整数。

只有两种宽度：ASCII 一律半角 128 单位（0.5 em），全角一律 256。拉丁原为比例宽度，
此处重塑为半角，并施加逐边的笔画粗细补偿——否则横向压缩会使竖笔变细。

单倍行距 1.141 em。不含 hinting 指令、`GSUB`/`GPOS`、`kern`、竖排表。

## 字形来源

汉字、假名、注音、标点和制表符取自思源宋体 SC Regular，拉丁字形取自 Liberation
Serif，两者都是 SIL Open Font License 1.1。

轮廓经过大幅几何简化以压缩体积：曲线降精度、共线点消除、浅弧压平。

## 许可

按 SIL Open Font License 1.1 分发，全文见 `LICENSE`。

`src/` 与字体同属 OFL。它是矢量管线的参考实现，供审阅与修改，不保证开箱即跑：
需自备上述两个源字体，且与本机环境相关的部分已经移除。
