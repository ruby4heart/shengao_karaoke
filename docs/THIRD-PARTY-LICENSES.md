# 第三方许可与资源清单

核对日期：2026-11-12，对应 0.31.0（开发中）。逐文件的来源、许可和 SHA256 指纹以
[`desktop/assets/licenses/THIRD-PARTY-INVENTORY.json`](../desktop/assets/licenses/THIRD-PARTY-INVENTORY.json)
为准；本页是它的说明。打包时清单随包放在 `licenses/Independent-Qt/`，本页放在 `licenses/THIRD-PARTY-LICENSES.md`。

## 非商业限制

**声稿整体只供个人非商业使用，不宣称可商用。** 原因是软件随附 TIFA-1.0-ST 歌声模型权重，
其许可为 CC BY-NC-SA 4.0（署名—非商业—相同方式共享）。TIFA 原作者说明该许可只约束模型文件本身，
但本软件把权重放进发行包、并用它生成歌声音节时间，所以整个发行包都按非商业对待。
“正式版”“1.0”只表示功能完成度，不代表商用授权。用户已于 2026-10-19 确认为个人非商业用途。

其他组件各有自己的许可条件（见下表），须与上面的限制同时遵守。

ElevenLabs、Microsoft AI 转写、DeepSeek 是用户自备密钥调用的外部服务，不随软件分发，
使用条款与费用以各服务商为准（格式核对见 [联网服务兼容性](SERVICE-COMPATIBILITY.md)）。

## 组件一览

| 组件 | 版本 | 许可 | 来源 | 用途 | 固定指纹（SHA256 前 12 位） |
|---|---|---|---|---|---|
| 声稿应用代码 | 0.31.0（开发中） | MIT | <https://github.com/ruby4heart/shengao_karaoke> | 桌面程序、后台流程、原生适配、脚本与文档 | `Shengao-MIT.txt` c312e7a12e7c |
| Aegisub 相关代码 | 3.5.0（用户提供的源码副本，本地快照 211e7aa） | BSD-3-Clause（个别子目录按各自许可，见 LICENCE） | <https://github.com/TypesettingTools/Aegisub> | 原版音频波形／频谱算法与时间轴绘制，移植进 shengao-audio.dll 与 shengao-view.dll；不构建 Aegisub 主程序 | `audio_display.cpp` 2cdff8e7a4af<br>`provider_convert.cpp` eaba56dca85b |
| wxWidgets | Aegisub 3.5.0 子项目 | wxWindows-exception-3.1（wxWindows Library Licence 3.1） | <https://www.wxwidgets.org/> | 仅在 shengao-view.dll 里离屏执行原版时间轴绘制 | `licence.txt` 5d82dd4900ca<br>`wxWidgets-LICENSE.txt` 5d82dd4900ca |
| 字幕渲染库 libass／FreeType／HarfBuzz／FriBidi | Aegisub 3.5.0 子项目 | ISC；FTL（FreeType License）；MIT（HarfBuzz “Old MIT”）；LGPL-2.1-or-later（FriBidi） | <https://github.com/libass/libass><br><https://freetype.org/> | shengao-render.dll 与 FFmpeg 的 ASS 字幕渲染 | `COPYING` 3dc660f0b5ff<br>`LICENSE.TXT` 84f47dc7f088<br>另 3 个见清单 |
| 内置字体 Noto Sans／Serif CJK JP、BIZ UDPGothic | Noto CJK：Sans/Serif Regular 取自 main 分支，Serif Black 为 Serif2.003；BIZ UDPGothic 固定提交 18934af | OFL-1.1 | <https://github.com/notofonts/noto-cjk><br><https://github.com/googlefonts/morisawa-biz-ud-gothic> | 预览与压制的默认字幕字体 | `NotoSansCJKjp-Regular.otf` 68a3fc98800b<br>`NotoSerifCJKjp-Regular.otf` d9854c7a8ef1<br>另 2 个见清单 |
| FFmpeg | n8.0.1-120033-gff04763ef7（Aegisub 的 Meson 子项目，MSVC 19.50 静态构建，未启用 GPL 与 nonfree） | LGPL-2.1-or-later | <https://ffmpeg.org/><br><https://github.com/TypesettingTools/Aegisub> | 独立 ffmpeg.exe：提取音轨、压制样片与成片 | `ffmpeg.exe` 967f4567a687 |
| Microsoft Visual C++ 运行库 | 随 FFmpeg 构建使用的 Visual Studio 可再发行组件 | Microsoft Visual Studio 可再发行代码条款（应用本地分发，未改动） | <https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files> | ffmpeg.exe 与原生模块的 C++ 运行库 | `concrt140.dll` b2faf3b85b23<br>`msvcp140.dll` def46aa6a8f7<br>另 8 个见清单 |
| Demucs（htdemucs 权重） | demucs 4.0.1；权重 955717e8-8726e21a.th | MIT（代码与权重） | <https://github.com/facebookresearch/demucs><br><https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th> | 本机人声辅助（分离人声） | `955717e8-8726e21a.th` 8726e21a9939 |
| TIFA 源码 | 固定提交 d246be1cc2e202613213ca60a4e5d35e71a2fb6a（未改写） | MIT | <https://github.com/openvpi/TIFA> | 本机歌声音节对齐的推理代码 | `LICENSE` 515ecbf58c3f |
| TIFA-1.0-ST 歌声模型权重 | v1.0.0 | CC-BY-NC-SA-4.0 | <https://github.com/openvpi/TIFA/releases/tag/v1.0.0> | 本机歌声音节对齐（不需要密钥、不上传） | `model.pt` 8d9bf896da18<br>`config.yaml` b4bdfd5c73ca<br>另 2 个见清单 |
| Qt 6 与 PySide6 | 6.12.0 | LGPL-3.0-only（按 LGPL 使用，可替换动态库） | <https://code.qt.io/cgit/pyside/pyside-setup.git/><br><https://doc.qt.io/qt-6/licenses-used-in-qt.html> | 桌面界面、播放与预览 | `LGPL-3.0.txt` e3a994d82e64<br>`SOURCE-CODE.txt` c566936eadd9 |
| CPython 运行时与 Python 依赖包 | Python 3.12；依赖版本见 desktop/requirements-tested.txt 与 desktop/vocal-requirements.lock | PSF-2.0；各依赖包许可逐个收录在 licenses/python 与 vocal-engine/licenses | <https://www.python.org/><br><https://pypi.org/> | 程序运行时 | `Janome-0.5.0.tar.gz` ce4a3ed7a463<br>`codex-rejected-cas.pem` c916ce1b14ed |
| orjson | 3.13.0 | Apache-2.0 OR MIT（部分随附代码为 MPL-2.0） | <https://github.com/ijl/orjson><br><https://pypi.org/project/orjson/3.13.0/> | 自动恢复检查点的快速 JSON 编码 | `orjson-3.13.0-cp312-cp312-win_amd64.whl` b571236d8393<br>`orjson-3.13.0.tar.gz` d1de5eb04485 |
| Intel oneTBB 运行库 | 2023.2.0 | Intel Simplified Software License（未改动二进制再分发） | <https://pypi.org/project/tbb/2023.2.0/> | Numba 可选并行扩展的依赖，放在人声引擎目录 | `tbb-2023.2.0-py3-none-win_amd64.whl` b39121cbdaff |
| PJS 语料 PJS056 演唱片段与人工标注 | 16 秒片段 | CC-BY-SA-4.0 | <https://sites.google.com/site/shinnosuketakamichi/research-topics/pjs_corpus><br><https://github.com/UtaUtaUtau/pjs-manual-labels> | 离线练习、对齐自检与联网服务真实检查的公开样例 | `pjs056_song.wav` 92037425e4b4<br>`sample.json` 29715b8b80e8<br>另 1 个见清单 |

“另 N 个见清单”指同一组件还有更多固定文件（例如 TIFA 的配置、词表和词典，VC++ 运行库的其余 DLL），
完整列表及运行包里的对应位置都在清单里。每个组件在源码和运行包中都至少带一份许可文本；
Microsoft Visual C++ 运行库按 Visual Studio 可再发行条款以应用本地方式随附，条款随 Visual Studio 授权，不单独附文本。

## 指纹从哪里来、怎样保持一致

- 程序运行时自己会校验的指纹（TIFA 权重与配置、Demucs 权重、orjson、TLS 证书文件、oneTBB、内置字体、
  Original-Audio 源文件）在代码里固定；核对脚本会逐项比较清单与代码，两边不一致就报失败。
- 只在完整源码 ZIP 里才有的大文件（`vendor/` 下的模型、FFmpeg、Aegisub 源码等）不进 Git 仓库；
  清单里的指纹取自已发布的 0.30.0 完整源码 ZIP，并与其中的 `SOURCES.json`、`MODEL.json`、`SHENGAO-SOURCE.json` 交叉核对过。
- 文本类文件（许可文本、说明 JSON 等）在清单里标为 `"text": true`，Git 在 Windows 上把换行改成 CRLF 后仍视为一致；
  模型、程序和音频等二进制文件必须逐字节一致。
- 应用代码每版都会变，不在本清单逐文件固定；它的逐文件指纹由构建时的 `build/desktop-build-sources.json` 与运行包里的
  `package-manifest.json` 记录。

## 怎样核对

```powershell
# 当前源码：清单格式、与代码固定指纹一致、文档写明非商业且没有宣称可商用、本机已有文件的指纹
.venv-desktop\Scripts\python.exe scripts\check-licenses.py

# 解压后的完整源码 ZIP 或放好 vendor 的开发树：清单里的源码文件必须全部存在且一致，并检查 FFmpeg 构建许可
.venv-desktop\Scripts\python.exe scripts\check-licenses.py --full

# 构建好的运行包：随包文件必须全部存在且一致，运行包内 ffmpeg.exe -L 必须是 LGPL 构建（未启用 GPL 和 nonfree）
.venv-desktop\Scripts\python.exe scripts\check-licenses.py --package build\desktop-dist\shengao-karaoke
```

加 `--out 报告.json` 可以另存一份 JSON 报告。退出码 0 表示没有失败项；“跳过”只出现在不带 `--full` 的源码核对里，
表示该文件只在完整源码 ZIP 里。

## 更新组件时

换 FFmpeg、模型、字体或任何第三方文件时，同时更新：代码里的固定指纹（如有）、清单里的版本、来源和指纹、
随附的许可文本，以及本页表格；然后用 `--full` 和 `--package` 各跑一遍。许可从可商用变成非商业
（或反过来）时，清单里的 `noncommercial` 与限制说明、本页“非商业限制”一节和 README、使用说明里的提示要一起改。
