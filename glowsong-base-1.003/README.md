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
| `GlowSongBaseMono-Regular.ttf` | GBK 全集，等宽 |
| `GlowSongGBBaseMono-Regular.ttf` | GB2312 子集，等宽 |
| `GlowSongExtA-Regular.ttf` | CJK 扩展 A 的缺字回退，无需拼合 |
| `src/` | 生成上面五个文件的矢量管线源码 |

等宽的两份用 `sbitgraft --derive-mono` 从对应的比例版派生：只改族名、
`post.isFixedPitch`、PANOSE 三处，字形与度量逐字节不变。独立成文件而不是指
望应用把点阵拼合后的族名认作等宽变体，是因为字体选择框读的是文件本身列出的
family，不是 fontconfig 事后加的别名——后者 `fc-list` 能看到，但不会出现在
选择框里。

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

单倍行距 1.141 em。不含 `GSUB`/`GPOS`、`kern`、竖排表。

带 Chlorophytum 生成的 TrueType 指令，收益集中在 12px 及以下的密集汉字：横画不粘连、
笔画数可辨。只在大字号用字、或在意体积，可以用另一份下载里的 `sbitgraft --strip`
去掉，轮廓、度量、字符映射与命名都不受影响。

## 字形来源

汉字、假名、注音、标点和制表符取自思源宋体 SC Regular，拉丁字形取自 Liberation
Serif，两者都是 SIL Open Font License 1.1。

轮廓经过大幅几何简化以压缩体积：曲线降精度、共线点消除、浅弧压平。简化是逐字验收
的——每个字形简化前后都渲染比对，形状偏差超过 1% 的拟合退回更保守的一档，全都不合格
就保留未简化的原轮廓。

## 许可

按 SIL Open Font License 1.1 分发，全文见 `LICENSE`。

`src/` 与字体同属 OFL。它是矢量管线的参考实现，供审阅与修改，不保证开箱即跑：
需自备上述两个源字体，且与本机环境相关的部分已经移除。

其中两步依赖外部工具，都是可选的。简化一步需要 FontForge，以及 `freetype-py` 与
`Pillow`——后两者用来渲染比对每个字形简化前后的形状，偏差超过 1% 的拟合一律退回；
这个检查不是可选项，缺了就整步跳过而不是放宽标准。hinting 需要 Chlorophytum。两步
都缺只是产物更大或更软，构建不会中断。
