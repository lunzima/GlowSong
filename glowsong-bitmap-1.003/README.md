# 星霞点阵体 GlowSong Bitmap

12–16px 的中文点阵字体。可以单独安装，也可以与「星霞宋体 Base」拼合成一个兼有
轮廓与点阵的字体。

## 内容

| 文件 | 说明 |
|---|---|
| `GlowSongBitmap.otb` | GBK 全集，12 / 13 / 14 / 15 / 16px 五档 |
| `GlowSongGBBitmap.otb` | GB2312 子集，体积约三分之一 |
| `src/glowsong-*px.bdf` | 上述两个文件的源码，五档各一个 |

## 单独安装

```sh
mkdir -p ~/.local/share/fonts
cp GlowSongBitmap.otb ~/.local/share/fonts/
fc-cache -f
```

`.otb` 是纯点阵的 OpenType 容器，FreeType 与 fontconfig 直接支持。它只在 12–16px
有字形，其余字号无输出，因此单独使用时通常需要另配一个轮廓字体兜底。

## 与轮廓字体拼合

另取「星霞宋体 Base」与 `sbitgraft`。拼两次得到比例版与等宽版，再打包成一个
TTC：

```sh
sbitgraft        GlowSongBase-Regular.ttf GlowSongBitmap.otb GlowSong-Regular.ttf
sbitgraft --mono GlowSongBase-Regular.ttf GlowSongBitmap.otb GlowSongMono-Regular.ttf
sbitgraft --pack GlowSong-GBK.ttc GlowSong-Regular.ttf GlowSongMono-Regular.ttf
```

装 TTC 而不是那两个 TTF：两款只在几张小表上有差别，TTC 共用其余的表，体积只有
分装的一半。Windows 与 Linux 都能正确处理。

两个输入的字符集必须一致：GBK 配 GBK，GB2312 配 GB2312。拼合工具会先比对两侧的
字符映射，不一致即报错退出，不会写出损坏的文件。

Base 的族名就是「星霞宋体」，拼合不改动它——拼上点阵的是同一款字，不是另一款。
因此 Base 与拼合成品装一个就够，不要两个都装。

## 字形来源

- 汉字、假名、注音、标点与多数符号：文泉驿点阵宋体 1.0.0-RC1
- ASCII：X.org misc-fixed（`font-misc-misc`），`6x13` 与 `7x14` 两个面
- 制表符与块元素中上游缺失的 23 个：本项目按几何生成
- 省略号、间隔号、比号、分音符、折角号：本项目按几何生成。上游在 12–14px 将其
  画作 1 像素高的短横，连排时读作虚线而非一串圆点
- 半角的句点、逗号、冒号、分号：本项目按几何生成。misc-fixed 在 12–14px 把它们
  画成 3×3 的菱形，读起来像脏点；15px 以上本就是 2×2 的方块，统一生成后整条
  尺寸梯级只有一种画法

此外对全部字形做了三项统一处理：把 advance 对齐到渲染器实际使用的值；字面比来源
宽时把多出的列分到两侧，而不是全加在右边；在半宽字格的最右一列留出空白，避免相邻
字粘连。

## 许可

按 GNU 通用公共许可证第 2 版分发，附字体嵌入例外条款，全文见 `LICENSE`。

ASCII 部分来自 X.org 的 misc-fixed，该包声明为 public domain，无附加义务。

`src/` 下的 BDF 即 GPL 第 3 条所要求的对应源码。BDF 是点阵字体通行的编辑格式，
可用任何 BDF 编辑器修改，上游发布采用的也是该格式。
