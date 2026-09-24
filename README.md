# 星霞宋体 GlowSong

![](preview.png)

12–16px 走内嵌点阵的中文宋体，给屏幕用。点阵档位五个：12、13、14、15、16 像素，
这个区间之外走轮廓。字符集到 GBK（CP936）级，另附 CJK 扩展 A 的缺字回退。

每个字符集有比例与等宽两款，字形与度量完全相同，区别只在 `isFixedPitch` 与
PANOSE 两个标志位。ASCII 一律半角（0.5 em），全角一律 1 em，字体只有这两种宽度。

## 这里有什么

轮廓与点阵按各自的许可分开发布，由你在本地拼合。

| 目录 / 文件 | 内容 | 许可 |
|---|---|---|
| `glowsong-base-1.008/` | 轮廓字体、Ext A、矢量管线源码 | SIL OFL 1.1 |
| `glowsong-bitmap-1.008/` | 点阵字体、五档 BDF 源码 | GPL v2 + 字体嵌入例外 |
| `sbitgraft-1.008/` | 拼合工具，单个 C 文件 | MIT |
| `LICENSE-MIT` | 字体 `fpgm` 内含的 hinting 运行时的许可 | MIT |
| `65-glowsong.conf`、`check-fontconfig.sh` | fontconfig 配置与自查脚本 | CC0 1.0 |
| `APPENDIX-toolkits.md` | 各桌面工具包行为的实测记录（英文） | CC0 1.0 |

各目录下的 `README.md` 讲自己那一份怎么用。

`glowsong-base` 里的等宽变体（`GlowSongBaseMono-Regular.ttf`、
`GlowSongGBBaseMono-Regular.ttf`）不需要拼合，装上就能用——它们是从对应的比
例版派生的独立文件，不依赖点阵，也不依赖下面这一节的工具。等宽 fontconfig
分类靠 `65-glowsong.conf`，见该文件内的说明。

## 拼起来

需要一个 C99 编译器，无其他依赖。

```sh
BASE=glowsong-base-1.008
BITS=glowsong-bitmap-1.008
GRAFT=sbitgraft-1.008

make -C "$GRAFT"

"$GRAFT/sbitgraft"        "$BASE/GlowSongBase-Regular.ttf" \
                          "$BITS/GlowSongBitmap.otb"       GlowSong-Regular.ttf
"$GRAFT/sbitgraft" --mono "$BASE/GlowSongBase-Regular.ttf" \
                          "$BITS/GlowSongBitmap.otb"       GlowSongMono-Regular.ttf
"$GRAFT/sbitgraft" --pack GlowSong-GBK.ttc \
                          GlowSong-Regular.ttf GlowSongMono-Regular.ttf
```

把 `GlowSongBase` 换成 `GlowSongGBBase`、`GlowSongBitmap` 换成 `GlowSongGBBitmap`
即得 GB2312 版。两侧字符集必须一致，工具会先比对，不一致就报错退出。

`GlowSongExtA-Regular.ttf` 是纯轮廓，不需要拼合。

## 装上

Linux：

```sh
mkdir -p ~/.local/share/fonts ~/.config/fontconfig/conf.d
cp GlowSong-GBK.ttc glowsong-base-1.008/GlowSongExtA-Regular.ttf \
   ~/.local/share/fonts/
cp 65-glowsong.conf ~/.config/fontconfig/conf.d/
fc-cache -f
```

配置文件与 `fc-cache -f` 都不能省，它们管三件事。

一是内嵌点阵的开关。配置在 12–16px 打开内嵌点阵、关掉抗锯齿，17px 以上反过来。
这两项的默认值本来就对，但桌面环境与发行版常会改动；文件编号 65，排在
`50-user.conf` 与 `51-local.conf` 之后，因此压得住用户配置与发行版的本地配置。

二是等宽分类。fontconfig 扫描字体时按 advance 的种类推断 `spacing`：只有一种是
`FC_MONO`（100），两种且恰好成倍是 `FC_DUAL`（90）。半宽 ASCII 配全宽汉字必然落在
后者，Sarasa、思源等宽黑体同样如此。Pango 把 `FC_DUAL` 视为等宽，GTK 系因此无碍；
Qt 系（含 TDE 的 TQt3）要求 `spacing` 不小于 100，缺了这个文件，等宽那一款就不会
出现在它们的等宽字体列表里，不过按名字仍然选得到。

这一点在字体内部无法修正。fontconfig 计算 `spacing` 时只数 advance，不读
`post.isFixedPitch`，也不读 PANOSE；这两个字段本字体都已按等宽正确填写，Windows
下的分类因此是好的。配置用一条扫描期规则改写该值，而字体列表建自扫描缓存，所以
安装后必须跑 `fc-cache -f`，否则旧判定会留在缓存里。

三是旧族名映射。配置把几个常见的旧宋体族名指向本字体，写死那些名字的老文档因此
也能用。

装完可跑 `sh check-fontconfig.sh` 自查，等宽分类也在检查项里。各桌面工具包的具体
取舍与源码出处记在 `APPENDIX-toolkits.md`，打包者与提 bug 的人用得上。

Windows：右键安装 TTC。点阵只在 GDI 下生效——DirectWrite 不读内嵌点阵，所以 UWP
应用、新版 Office 与浏览器看到的是轮廓。

## 字形来源

汉字、假名、注音、标点与制表符的轮廓取自思源宋体 SC，拉丁轮廓取自 Liberation
Serif，两者皆 SIL OFL 1.1。点阵的全角部分取自文泉驿点阵宋体，ASCII 取自 X.org
misc-fixed。

上游缺失或在这个尺寸下画得不好的字形由本项目按几何生成：23 个制表符与块元素、
省略号与间隔号一类的点状标点、半角的句点逗号冒号分号。

## 项目

源码与问题跟踪：<https://github.com/lunzima/GlowSong>
联系：lunzima@lunzima.net

## 许可

三个目录各自独立，许可见各自的 `LICENSE`；顶层那三个文件（fontconfig 配置、自查
脚本、工具包附录）是 CC0，全文见 `LICENSE-CC0`，抄走改用不必署名。字体文件的 `name` 表里也带着各自的版权与许可
声明（name ID 0、13、14），点阵那侧的 BDF 则写在文件头的注释里。

拼合出来的成品同时衍生自 OFL 与 GPL 两边的材料，而这两个许可对衍生作品的要求
互斥，因此拼合的结果请自用，不要再分发。需要分发时分发这三个目录，让对方自己拼。
