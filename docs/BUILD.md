# 从源码构建

源码包保留 Aegisub、Meson 依赖源码和原始授权。构建目标为 Windows x64，使用 Visual Studio C++ Build Tools 与 Windows SDK。

已验证环境：Python 3.12.14、Meson 1.12.1、Ninja 1.13.2、CMake 4.4.4、Visual Studio 2026 MSVC 14.50、Windows SDK 10.0.26100。也需要 Git for Windows 提供 Git 与 sed。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-tested.txt meson==1.12.1 ninja==1.13.2 cmake==4.4.4 pyinstaller==6.22.3 pytest==9.1.1
.\.venv\Scripts\python.exe scripts/apply-studio.py
.\scripts\configure-baseline.cmd
.\scripts\build-native.cmd
.\.venv\Scripts\python.exe scripts/test-native.py
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe scripts/build-worker.py
.\.venv\Scripts\python.exe scripts/prepare-package.py --source
.\.venv\Scripts\python.exe scripts/test-native-integration.py
.\.venv\Scripts\python.exe scripts/test-package.py
```

原生输出为 `build/baseline/shengao-karaoke.exe`；FFmpeg 在 `build/baseline/subprojects/ffmpeg/ffmpeg.exe`。源码快照无 `.git` 时，版本生成脚本始终使用独立发行身份的 `tools/source_version.h`。完整包生成后，运行 `scripts/check-release.py` 检查压缩包、源码和依赖并生成 SHA256。

后台测试的真实渲染需要将构建的 FFmpeg 目录加入 PATH；模拟 HTTP 测试需要本机回环网络权限。测试使用合成音频，不依赖真实 API 密钥。打包前先生成 `demo` 中的合成音频（源码包已包含），必要时运行 `scripts/make-demo.py`。

0.5 增加 Janome 0.5.0，官方源码归档在 `vendor/python/janome-0.5.0.tar.gz`。后台请统一用 `scripts/build-worker.py` 构建：Janome 的内存映射词典需要实际的 Python 数据源文件，脚本通过 `--collect-all janome` 一起打包。运行包包含 Janome / IPADIC 的 LICENSE 与 NOTICE。该库的词典读音只作编辑建议，特殊唱法仍由人工或 DeepSeek 修正。

`scripts/apply-studio.py` 只修改开发副本 `vendor/aegisub`。`native` 中的新增文件以及此脚本中的补丁是改造入口。不要将它指向用户保留的原始 Aegisub 目录。

0.6 的分词条自然字宽与点击映射位于 `native/studio_karaoke.h`、`native/studio_karaoke_display.inc`；拖动手柄位于 `native/studio_timing_drag.inc`，逐词校准位于 `native/studio_calibration.h` / `studio_correction.cpp`，转录辅助读音位于 `backend/studio_backend/analysis.py`。通过适配脚本同步到开发副本；保留底层空白音节、实际停顿及 ASS 样式。适配脚本重复运行不会重复注册 Meson 源文件。

原生集成生成 `karaoke-single-boundaries.png`、`refinement-options.png`、`reading-evidence.png` 和四阶段完整窗口，并验证真实控件和控制器的拖动、撤销、微调、草稿及 ASS 重开。正式验收使用运行包中的后台；可传 `--native build/baseline/shengao-karaoke.exe --package <旧运行包>` 做增量预验收，最终仍需回到完整新包。

0.7 的新手引导、离线示例和停顿窗口在 `native/studio_usability.cpp`，停顿算法在 `native/studio_pauses.h`，原生回归在 `studio_usability_test.inc`。停顿处理修改同一份歌词／音节数据，原生 ASS 与后台导出共用修改后的边界；原词、注音和样式保留。新增 `first-use.png`、`beginner-guide.png`、`pause-options.png`、`pause-merge-preview.png`、`narrow-window.png`。后台接口与模型默认值延续 0.6，未新增云端调用；运行包中的后台仍需通过隔离导出验收。

`build-native.cmd` 会先同步适配文件，避免漏编译 `native` 中的最新修改。原生集成测试创建带标记的独立目录，使用合成音视频运行 `--studio-self-test` 入口，不使用鼠标键盘自动化，也不会调用云端服务。界面渲染阶段只显示软件自己的离屏、不抢焦点、无任务栏测试实例；表格使用 wxGrid 打印接口。测试生成检查报告、自动保存工程、两张原生字幕预览与四阶段侧栏、完整窗口以及六种保存文字状态图片（OpenGL 由同一字幕渲染器合成到实际视频区域）。发行包默认为 `dist/ShengaoKaraoke-0.7.0-final-win64`，重复打包可使用 `--refresh`，只允许清理带打包标记的生成目录。
