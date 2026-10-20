# 声稿 0.11.0 验收

本轮对应用户要求先完成并导出的一组修复：双行显示、Aegisub 音频默认快捷键、波形／频谱切换、未匹配句重新分词、视频放大。

## 行为证据

- `desktop/tests/test_v011_editor.py`：对照随源码保留的 Aegisub 3.5.0 默认 Audio/Always 表；校验精确修饰键、小键盘、提交顺序、已确认句再次提交、Medusa 开关和输入焦点隔离。音节模式不再错误移动整句末界。
- 同一测试文件：远处异常重叠不再挤走正常字幕；三个位置、多行、大字号与密集重叠的实际 libass 帧仍可见。切换双行时暂停在无字幕位置会定位到本句，实际演唱时间不改变。
- 同一测试文件：没有匹配结果、没有词组时仍可打开本句分词窗口，点击原文设置边界、修改范围、预览、应用和撤销；保护锁定与已有人工读音。
- 同一测试文件：波形／频谱即时切换并保存偏好；视频滚轮每格 12.5%、百分比、放大滚动、双击适合窗口、临时收起侧栏。
- `desktop/tests/test_rolling_karaoke.py`：显示时机、逐音高亮、汉字注音、实际 FFmpeg 与 libass 排版对照。
- `desktop/shengao/self_test.py`：独立静音离屏实例，使用合成素材；包含真实播放、后台离线分词、工程/ASS 往返、样片/全片/纯音频字幕视频压制与上述交互。

## 发行检查

237 项完整回归通过；两种缩放的隔离运行包各 63 项通过；187 个原生依赖无缺失。时间轴两种缩放各 6 个场景均为零差异像素。

本轮冻结证据保存于 `build/v011-evidence/`，避免后续版本覆盖全局测试记录。完整回归结果：该目录的 `desktop-tests.xml` 与源码清单 `desktop-test-sources.json`。
开发离屏验收：`tmp/desktop-v011-final/report.json`（63 项）。
运行包验收：正常与 150% 缩放两次独立 home、隔离 PATH，无系统 Python、无 API 环境，记录于冻结目录的 `desktop-package-test.log`、`desktop-package-dpi150-test.log`。
原版时间轴绘图：两种缩放各 6 个场景，本轮源码哈希与冻结目录的 `timeline-full-pixels.json`、`timeline-full-pixels-dpi150.json` 绑定。
依赖：冻结目录的 `desktop-dependencies.json`。
最终源码、便携包、原始 Aegisub 和旧版保留检查：`build/desktop-final-audit-v011.json`。

密集的多句实际重叠会临时缩小字幕并给出排版提示，仍须根据演唱校对；临时缩小不是声学匹配成功的证明。Aegisub 对照范围是音频 Audio/Always 默认键位与原生绘图，不意味着复制了全部 Aegisub 功能。

原始 Aegisub 目录、旧版运行包、用户媒体与密钥未改动。此轮之后继续三个控制滑条、拖轴、工作流、注音入口和弱尾音辅助。
