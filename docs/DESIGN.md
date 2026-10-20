# 第一版规划与实现分工

目标是独立的 Windows 日语卡拉 OK 制作软件。用户流程：拖入视频 → 导入／识别歌词 → 音频对齐 → 注音和译文 → 人工校准 → 保存工程及导出成品 ASS。

## 原生编辑主体

在 Aegisub 3.5.0 的开发副本中改造主窗口，保留视频、音频、波形／频谱、逐音节模式、拖动边界、拆分合并、撤销重做和自动保存。这些模块依赖共同的时间、选择和文档模型，第一版保留其稳定联系，逐步在明确边界上替换。

软件有独立名称、启动文件和用户配置目录。左侧歌词，中间视频和音频编辑，右侧自动处理与读音编辑。原始 `E:\transcribe\Aegisub-3.5.0` 保持作为参考，开发副本位于 `vendor/aegisub`。

## 接口分工

| 情况 | 服务 | 输入和输出 |
| --- | --- | --- |
| 没有歌词 | ElevenLabs Scribe v2 | 音轨 → 歌词及字符时间初稿 |
| 有校对过的歌词 | ElevenLabs Forced Alignment | 音轨＋原歌词 → 字词时间 |
| 切换识别提供方 | Microsoft MAI-Transcribe-2 | 音轨 → 歌词及词级时间 |
| 日语语言处理 | DeepSeek | 歌词 → 假名分组、罗马音、中文译文 |

视频在本机提取音轨后上传，DeepSeek 只接收所选歌词文本。付费请求单次提交、后台运行，可取消本地等待；成功的识别／对齐结果缓存复用。错误记录阶段、上传字节数、HTTP 状态和耗时。

接口资料：

- [ElevenLabs Speech to Text](https://elevenlabs.io/docs/overview/capabilities/speech-to-text)
- [ElevenLabs Forced Alignment](https://elevenlabs.io/docs/api-reference/forced-alignment/create/)
- [Microsoft MAI](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe)

## 日语与时间模型

每句保存原文、句起止、原文片段、片段读音、罗马音、译文和人工标记。时间以整数毫秒保存，写入 ASS 时转换为厘秒。一个原文词组可以对应多个演唱音节，例如“今日”对应“きょ／う”。

API 声学时间、词级时间、手动时间和估算时间分别标记。DeepSeek 不生成时间；新增读音拆分的初始均分时间必须标为估算。软件检查时间范围、重叠、原文完整覆盖以及读音合并关系。

自动结果先审核，再通过原生撤销系统提交。处理期间已修改或人工锁定的行受到保护；侧栏未保存的编辑也不会被后台结果覆盖。时间仍以实际试听确认。

## 保存和输出

可编辑 ASS 保存原生音节及扩展注音数据。JSON 保存结构化歌词、媒体引用与 API 结果。成品 ASS 将假名定位为独立字幕事件，包含卡拉 OK 高亮、可选罗马音和译文。另提供 SRT、TXT。

密钥使用 Windows 当前用户 DPAPI 加密，不进入工程文件。发行包包含后台运行时、FFmpeg、所需运行库、授权文件和独立源码包。

## 完成标准

先通过原版基准构建，再通过独立软件编译；验证三个接口契约、取消及错误处理、工程往返和实际字幕渲染。验收结合已完成的窗口实操与真实原生内部集成测试；根据用户“尽量不要使用 Computer Use”的要求，后续视频导入、人工校准、保存恢复和成品预览通过相同的内部服务与渲染器验证。具体证据见 `V1-ACCEPTANCE.md`。
