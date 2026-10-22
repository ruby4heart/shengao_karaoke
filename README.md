# 声稿 Karaoke Studio

Windows 日语卡拉 OK 字幕制作软件，使用独立 Qt 工作台。当前为 **0.23.0 开发预发布版**，面向个人非商业制作，尚未达到完整 1.0 验收标准。

**0.23.0 整首顺序与重复段检查**：原歌词保持，利用前后文字和人工位置处理重复副歌，列出漏识别／缺唱、错段及未分配转录候选。可直接试听、暂存后手改，或只为这一句限定正确时段重匹配，不重新上传。人工内容默认保留，结果先审核，采用可一步撤销。文字对应不证明实际缺唱、多唱或音节精度。歌声模型继续限个人非商业用途（CC BY-NC-SA 4.0）。

新工程格式为第 9 版，读取第 1–9 版，保存时间来源、变更、声音依据与人声资源。0.21.0 及更旧程序会拒绝第 9 版，请另存副本；旧任务快照和检查点兼容读取。

说明见 [第一次制作](docs/DESKTOP-USER-GUIDE.md)、[0.23.0 验收范围](docs/V023-ACCEPTANCE.md)、[0.22.0 声音空隙](docs/V022-ACCEPTANCE.md)、[完整待办](docs/WORKFLOW-TODO.md)、[构建步骤](docs/DESKTOP-BUILD.md)。每个功能项单独发行；旧包及原始 Aegisub 保留。自动候选仍需试听，整首成品与真人新手验收继续实施。

正式版缺项与完成标准见 [1.0 清单](docs/RELEASE-1.0-CHECKLIST.md)，当前余 **11 组、56 条功能／验收项**，持续交付要求另列。从 0.21.0 起，每个完成的版本同时提交到本仓库，并在 [Releases](https://github.com/ruby4heart/shengao_karaoke/releases) 附 Windows 运行包、完整源码、公开验收和指纹；GitHub 自动生成的源码快照不包含大型第三方资源，构建请使用 Release 中命名的完整源码 ZIP。发布流程见 [GitHub 交付](docs/GITHUB-RELEASE.md)。

## 下载与使用

到 [Releases](https://github.com/ruby4heart/shengao_karaoke/releases) 下载对应版本的 `ShengaoKaraoke-X.Y.Z-final-win64.zip`，完整解压后双击 `shengao-karaoke.exe`。需要 Windows x64，无需另装 Python、FFmpeg 或 Aegisub。软件带不联网的合成练习素材，可先查看 [第一次制作](docs/DESKTOP-USER-GUIDE.md)。

1. 拖入视频，粘贴每行一句的原歌词；没有歌词时可先识别，再确认文字。
2. 配置需要的 ElevenLabs／Microsoft AI 转录及 DeepSeek 文字建议，审核自动初稿。联网动作会使用所配置服务的额度；已有结果可本地复用。
3. 可生成本地人声辅助，使用 TIFA 给原歌词生成待试听的演唱音节候选；在同一编辑区改分词、假名、罗马音与时间。原歌词始终保留。
4. 整体提前／延后、渐进漂移与局部校准均支持预览和撤销；上一句、本句、下一句共用刻度。确认时间与读音分别记录。
5. 选择日式双行注音样式，先压制样片，再导出 ASS 或 MP4，保存 `.sgproj` 以便继续。可给同一作品添加原唱／伴奏视频源并一键切换。

## 已有能力与限制

原版 Aegisub 音频绘图、波形／频谱切换、三个音频滑条和兼容音频键位保留；视频滚轮缩放、音节试听、建议审核、人工修改保护、自动恢复及内置字体和压制工具已接入。软件不启动 Aegisub 的主窗口框架。

自动分词、词典／DeepSeek 假名和歌声边界都可能需要人工复核。文字时间不能证明音素起点，TIFA 按输入读音强制对齐也不能证明该读音唱对。公开单一样本的误差不代表其他歌曲准确率；正式 MV 人工金标准、完整成品和真人新手验收仍在 [待办](docs/WORKFLOW-TODO.md) 中。

API 密钥由当前 Windows 用户的 DPAPI 加密保存在本机，不进入工程或源码发行。TIFA 权重限非商业用途；各第三方代码、字体、模型与运行资源的来源和许可随完整源码及运行包保留，不能把“正式版”理解为商用授权。

## 源码、构建与历史

本仓库包含应用代码、测试、原生适配、文档和演示。请下载 Release 附带的完整源码 ZIP 获取匹配的第三方资源，再按 [构建步骤](docs/DESKTOP-BUILD.md) 操作。依赖说明见 [vendor/GIT-SOURCE-NOTES.md](vendor/GIT-SOURCE-NOTES.md)。

当前变更见 [0.23.0 说明](docs/releases/0.23.0.md) 与 [验收范围](docs/V023-ACCEPTANCE.md)。历史验收资料保留在 `docs/`；[0.7.0 旧 README](docs/README-0.7-HISTORY.md) 仅供追溯，不作为当前操作说明。

## 许可

本项目代码以 [MIT 许可证](LICENSE) 发布。随附的第三方代码、字体、模型与媒体仍使用各自的许可证，不因本文件改为 MIT。

