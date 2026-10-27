# 独立 Qt 工作台构建

本文对应0.30.0开发树，尚未发布，验收进度见 `V030-ACCEPTANCE.md`；当前稳定版为0.29.0。每版合并一个完整工作阶段的多个关联目标；旧包保留，不可把旧包的测试作为新程序通过的证据。原版音频／字幕／时间轴绘图ABI未改动，0.30另增CPython 3.12数据复制模块。

若构建 Python 的 `ssl.py` 引用 `codex-rejected-cas.pem`，两种构建脚本会核对运行时原件与 `vendor/python-tls` 的固定指纹，并打包至 SSL 模块同目录；普通 CPython 不需要该附属文件。不要通过关闭证书验证绕过缺失依赖。构建环境的证书策略变化后，应先核对来源、更新资源和验收。

## 环境

- Windows x64、Visual Studio C++ Build Tools 和 Windows SDK。
- Python 3.12；已验收的桌面及后台版本由 `desktop/requirements-tested.txt` 固定，普通兼容范围见 `desktop/requirements.txt`。
- Meson / Ninja / CMake 及构建工具使用 `.venv`；桌面 Python / PyInstaller 使用 `.venv-desktop`。
- 依赖源码位于 `vendor/aegisub/subprojects/`；这是开发副本，不能修改用户原始 Aegisub 目录。

在 `karaoke-studio` 目录依次执行：

```powershell
.\.venv-desktop\Scripts\python.exe scripts\fetch-json-runtime.py
.\.venv-desktop\Scripts\python.exe -m pip install --no-index vendor\orjson\orjson-3.13.0-cp312-cp312-win_amd64.whl
.\.venv-desktop\Scripts\python.exe scripts\extract-audio-core.py
.\.venv-desktop\Scripts\python.exe scripts\extract-timeline-view.py
cmd /c scripts\build-desktop-engine.cmd
.\.venv-desktop\Scripts\python.exe scripts\build-snapshot-native.py
.\.venv-desktop\Scripts\python.exe -m venv .venv-align
.\.venv-align\Scripts\python.exe -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv-align\Scripts\python.exe -m pip install -r desktop\vocal-requirements.lock --extra-index-url https://download.pytorch.org/whl/cpu
.\.venv-desktop\Scripts\python.exe scripts\fetch-vocal-model.py
.\.venv-align\Scripts\python.exe scripts\build-vocal-engine.py
.\.venv-desktop\Scripts\python.exe scripts\build-desktop.py
```

快照模块使用同一桌面Python的头文件和MSVC生成 `_shengao_snapshot.pyd`，并记录源码、二进制指纹与CPython ABI。修改 `desktop/native/snapshot.c` 后先重建该模块，再运行源码回归和应用构建；`build-desktop.py`拒绝来源不匹配的模块，并将其与记录复制到运行包。实际应用只从自身运行目录加载核验后的模块；缺失或不匹配时保留Python实现，发行自检仍会报告未达到构建要求。两种实现均保留完整工程验证、原文、元数据与撤销语义，不更改原版绘图。

0.30开发树的GPU缩小组件使用已固定PySide6中的Qt Quick／QML／Multimedia，运行包必须收集这些模块、视频QML插件和随附许可，不能沿用以前排除QtQuick／QtQml的配置。纯offscreen软件场景图保留原图像路径；实际GPU验收使用原生Windows隐藏窗口，执行 `shengao-karaoke.exe --gpu-preview-test --output <独立目录>`，记录真实DPR、色彩、源尺寸、字幕和回退。正常GUI自检通过仍不能代替此项，新包须另验依赖与模块完整性。

定时恢复的常见JSON数据使用固定的orjson 3.13.0；原生检查先排除非有限数、自定义类型和非字符串键，不兼容的大整数或特殊文本继续使用原标准库路径。手动工程保存和显式恢复检查点保持原编码。`fetch-json-runtime.py`仅从记录的官方地址取得固定wheel、源码归档及随附许可，校验完整SHA256；完整源码ZIP包含这些文件，已齐全时不再下载。构建还逐文件核对已安装模块与官方wheel，运行包保留许可及来源记录；不要只安装同名版本便跳过来源校验。

本地引擎构建会先逐项核对 `desktop/vocal-requirements.lock` 的全部固定版本。旧 `.venv-vocals` 只有人声分离依赖，不能用于当前歌声对齐引擎；缺少 `g2pflow`、`librosa`、`numba` 或版本不符时必须在 PyInstaller 前失败。成功的引擎附 `engine-environment.json` 与 `engine-sources.json`，依赖校验通过也仍须实际推理与运行包验收，不能仅凭打包工具返回成功交付。

新的根 Meson 工程只构建三个 C ABI 模块：音频底图、libass 字幕、原版离屏时间轴绘图。它不配置 Aegisub 应用，不编译 FrameMain，也不使用 agi::Context。wxWidgets 仅为最后一个模块提供原版 Windows GDI / GDI+ 绘制，整个编辑界面、工程模型和输入由 Qt 管理。`build-desktop-view.cmd` 是复用已有 baseline 静态库的开发快捷方式；正式可重复构建应使用根 Meson 工程。

运行包必须包含 `shengao-view.dll`，不使用“缺少模块时悄悄回退近似绘图”的方式通过验收。Qt 6.12 使用 Windows 系统 ICU，不能混入 Poppler 的同名 `icuuc.dll`；构建脚本会移除这一构建 PATH 冲突。

## 对照与测试

准备音频底图对照库与时间轴原始源码审计：

```powershell
.\.venv-desktop\Scripts\python.exe scripts\build-audio-reference.py
cmd /c scripts\build-audio-reference.cmd
.\.venv-desktop\Scripts\python.exe scripts\build-timeline-reference.py
cmd /c build\desktop-reference\build-view-reference.cmd
.\.venv-desktop\Scripts\python.exe scripts\compare-timeline-scene.py --output tmp\timeline-full-pixels
$env:QT_SCALE_FACTOR='1.5'
.\.venv-desktop\Scripts\python.exe scripts\compare-timeline-scene.py --output tmp\timeline-full-pixels-dpi150
Remove-Item Env:\QT_SCALE_FACTOR
.\.venv-desktop\Scripts\python.exe scripts\test-desktop.py
.\.venv-desktop\Scripts\python.exe scripts\test-desktop-package.py
```

对照库只进入 `build/desktop-reference`，不随运行包分发。`TIMELINE-SOURCES.json` 记录未改写的原版类和绘图函数哈希；用户提供的原始 3.5.0 与开发副本已经核对这些函数一致。音频底图测试要求完整 RGB 逐像素相同。离屏测试使用合成音视频和虚拟 API，不读取用户密钥，不调用收费服务，不操作桌面窗口。

人声引擎与 Qt 环境分离，固定 CPU PyTorch，`build-vocal-engine.py` 收集依赖许可证并绑定源码、依赖锁及官方模型指纹。模型与许可已随源码放在 `vendor/vocal-model`；下载脚本校验官方短指纹，运行时还验证固定的完整 SHA256。主程序不会联网下载模型。重建需要约数 GB 的依赖和构建空间；不要把隔离开发环境打进源码归档。

构建脚本在开始与结束对源码及原生模块求哈希；构建期间文件变化会使包失效。完整回归、完整时间轴图像对照和运行包隔离验收都通过后，执行 `scripts/prepare-desktop-release.py --version 0.30.0` 生成便携 ZIP、对应源码 ZIP 和 SHA256。该脚本拒绝过期证据，并拒绝覆盖已有发行包。全部依赖检查使用 `scripts/check-desktop-dependencies.py`；一小时音频可见区压力测试使用 `scripts/stress-desktop-audio.py --output tmp/desktop-audio-stress`。

0.19.0 的共享 CPU 引擎同时封装 Demucs 与 TIFA，依赖由 `desktop/vocal-requirements.lock` 固定。`vendor/tifa` 保留固定提交的未改写上游源码及 MIT 许可；`vendor/tifa-model` 保留官方配置、日语字典、词表和非商业模型许可、完整指纹。无需重新下载即可从源包构建。构建前会把 TIFA 入口和动态 backbone 纳入模块，构建后复制实际上游源码供 Numba 定位／缓存；缓存仅写入测试／用户数据目录。不要把模型的非商业许可与代码 MIT 混淆。

公开 PJS056 演唱音频和人工标签只用于实际模型回归，位于 `desktop/assets/alignment-demo`，保留作者、上游链接和 CC BY-SA 4.0。独立包自检在隔离 PATH 下调用真正的音频引擎，记录逐摩拉误差；不以合成纯音证明日语演唱准确。

Numba 的可选 TBB 扩展依赖 `tbb12.dll`。主运行包收集时从 `vendor/tbb-runtime` 固定指纹的 Intel 官方 wheel 中加入未改写的 DLL 与完整许可，放在音频子进程的 DLL 根目录；不依赖系统安装 TBB，不混入 Qt 的 DLL 目录。该运行库的来源、版本与二进制指纹另有 `SOURCE.json` 记录，并纳入主包的源码／运行时清单与全 PE 依赖扫描。

0.20.0 音频引擎使用 `audio_contract.py` 的第 2 版事件协议，每个完整推理区间独立返回并立即核验、保存。修改该合同、推理入口、进程管理或依赖后应先重建音频引擎，再构建主程序。后台任务通过私有具名 Windows Job 管理；实际解释器在读取请求或加载模型前自行加入，避免虚拟环境启动器提前派生子进程造成的清理缺口。取消等待音频进程全部退出、句柄释放和检查点保存。独立包自检同时执行单句和多句真实歌声推理、重开复用、审核及人工交接。

0.21.0 的 `studio_backend/provenance.py` 不导入模型库或 Qt，将原始依据、当前范围、后续变更与确认状态分开。第 8 版工程读 1–8，空的新字段在序列化时缺省，避免改变真实 0.18／0.20 检查点的原签名。来源界面只读恢复有原始音素区间可对应的旧 TIFA 资料，不静默迁移旧任务。开发版和独立包自检会从本轮实际歌声候选打开来源页，验证查看、移动、手调、保存及撤销，输出 `timing-provenance-audit.json`。

0.30的私有GPU缩放只使用五个QML模块。`scripts/qt_qml_runtime.py`在构建前运行安装环境的`qmlimportscanner.exe`，实际导入集合与允许集合不一致时停止，先审计再修改集合。应用专用QtQml hook保留PyInstaller的Qt插件依赖扫描，并逐文件按最近的qmldir过滤数据；不能将整个QtQuick父目录复制进去。新包保留`qml-runtime-imports.json`，还须运行实际GPU检查及PE依赖检查。

持续播放的独立入口（源码／冻结包均支持）：

```powershell
.venv-desktop/Scripts/python.exe desktop/main.py --playback-continuity-test --source <本机视频> --output <不存在的本机结果目录> --proxy-cache <本机代理缓存目录>
# 冻结包使用 shengao-karaoke.exe 替代 Python 与 desktop/main.py。
```

入口仅创建自有隐藏Windows Qt窗口，正常启用恢复和回收，不调用外部API。原片与已核验代理各完整播放一遍；五处帧图像和详细报告留在指定目录，私人MV输出不得装进公开验收附件。`progress.json`用于读取阶段；以最终`report.json`为准，不因暂时没有控制台输出推断死锁。受限设备接口可能引发Qt原生异常，须保留旧版对照和异常记录，再在有本机设备访问的环境复核。

同一份完整编辑压力测量也可直接从新冻结程序执行：

```powershell
shengao-karaoke.exe --preview-performance-test --source "本机视频" --output "新的本机目录" --cache-label "实际缓存条件" --with-proxy --native-hidden
.venv-desktop/Scripts/python.exe scripts/measure-desktop-startup.py --package build/desktop-dist/shengao-karaoke --output tmp/startup-new-run --scale 1
```

压力入口与源码脚本共用1000句、50次操作、完整撤销／重做及后台恢复检查；冻结包前后逐文件核验。启动工具运行三个空应用目录和三个复用目录的新进程，记录外部启动至窗口实际绘制和交互就绪，另存完整审计。哈希读取会温热文件，系统缓存未清理；系统冷缓存和干净Windows结果须独立记录。所有窗口属于测试进程并保持隐藏，不使用Computer Use，不调用付费API。两档缩放分别建立新输出目录；同一报告不能被改写后冒充另一档结果。

Windows上固定Qt 6.12时，播放器默认跳过`av1_mf,h264_mf,hevc_mf`三个未使用的Qt内部编码器探测；已有`QT_FFMPEG_EXCLUDE_ENCODERS`配置保持。解码器与独立FFmpeg压制不受此设置控制。该变量属于Qt私有实现，升级Qt小版本须重新审计；实际源码／冻结压力报告记录采用的配置，并继续验证原片解码、GPU颜色与压制输出。
