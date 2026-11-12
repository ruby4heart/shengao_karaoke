# 联网服务兼容性记录（11.5）

本页记录声稿使用的三家联网服务：ElevenLabs（识别、对齐）、Microsoft AI 转写（识别）、DeepSeek（注音与翻译）。逐项写明接口、限制、超时／限流／取消、返回解析和语言，并把证据按来源分开：

- **真实**：用真实密钥向真实服务发出的请求。
- **模拟**：在本机起一个假服务，按官方文档的请求与返回格式，走完整条后台任务流程。不联网。
- **离线**：不经过网络层的单元测试。

三种证据不能互相替代。模拟只能说明“服务按文档那样回答时，软件处理得对”，不能说明服务今天确实那样回答。

官方文档核对日期：**2026-11-12**。文档以后可能变化，每次发版前应重新核对，并重跑真实检查。

## 证据现状

| 类别 | 内容 | 状态 |
|---|---|---|
| 真实 | `scripts\check-services.py --real`：16 秒 PJS056 公开样例发给 ElevenLabs（识别、对齐）和 Microsoft AI（识别），一句歌词发给 DeepSeek（注音）；每家再用故意写错的密钥发一次 | **待用户在 Windows 上运行**。开发环境没有密钥，从未向真实服务发过请求，这里不填任何真实结果 |
| 模拟 | `scripts\check-services.py`（默认模式），以及 `backend/tests/test_service_compat.py` 中同样的 27 个场景 | 通过（2026-11-12，Linux 开发环境） |
| 离线 | FLAC 时长读取、各家错误体解析、上传上限边界、对齐换行补回；原有的 `test_api.py`、`test_api_stages.py`、`test_paid_requests.py` | 通过（2026-11-12） |

真实检查的报告写在软件数据文件夹的 `service-checks\<时间>-real\report.json`，文件开头标有 `"evidence": "真实"`。模拟报告写在仓库的 `tmp\service-check-mock.json`，标有 `"evidence": "模拟"`。

## 三家共同的处理

- **只发一次，从不自动重试**。任何失败都不会悄悄重发付费请求。
- **超时**：连接必须在 45 秒内建立。之后整次请求最长等 7200 秒（2 小时），单次读取也最长等 7200 秒，够一整首歌的识别。
- **失败阶段与计费判断**（任务记录、诊断报告和提示里都会写）：

| 失败阶段 | 是否可能已计费 | 是否保留“付费未知”登记 |
|---|---|---|
| 本机准备（如超出上限）、连接不上 | 未发出，不计费 | 不保留 |
| 上传中断 | 通常不计费 | 不保留 |
| 服务拒绝（4xx） | 通常不计费 | 不保留 |
| 等待处理时超时或断开、接收结果时中断 | 可能已计费 | 保留 |
| 服务出错（5xx） | 由服务商决定 | 保留 |
| 返回内容无法解析，或结果没有通过校验 | 通常已计费 | 保留 |

- **付费未知不自动重提**：留有登记时，再次提交同一请求会被拦下，并说明上次停在哪个阶段、请求编号是多少。必须在确认对话框里明确选择重发才会再发送。
- **取消**：本地任务立即停止。提示写明“已提交的云端请求可能仍会计费”。如果取消时请求已经发出，会留下标为“已取消”的登记，下次同样需要确认。
- **缓存**：识别和对齐的原始返回存在 `cache\<指纹>.json`。同一音轨、同一设置再次运行时直接读缓存，不重发。
- **请求编号**：读取 `request-id`、`x-request-id`、`apim-request-id` 等响应头，以及错误体里的 `request_id`，写入任务记录，方便向服务商查账。
- **错误代码**：从各家错误体中只取简短代码，写入诊断的 `error_code`。错误消息可能回显请求内容，所以不记录。
- **返回结构异常**：把原始返回保存到任务目录的 `api-response.json`，不应用结果。
- **密钥**：只放在请求头里。任务记录、缓存、诊断报告和检查报告都不含密钥，模拟场景会逐项检查这一点。

## ElevenLabs 识别（Speech to Text）

- 来源：<https://elevenlabs.io/docs/api-reference/speech-to-text/convert>
- **接口**：`POST https://api.elevenlabs.io/v1/speech-to-text`，表单上传，请求头 `xi-api-key`。
- **软件发送的字段**：
  - `model_id=scribe_v2`。文档同时列出 scribe_v3 和 scribe_v2_medical，软件仍用 v2。
  - `language_code`
  - `timestamps_granularity=character`
  - `diarize=false`
  - `tag_audio_events=false`
  - `file`：本机提取的 16 kHz 单声道 FLAC，约 65 MB／小时
- **文档限制**：文件小于 5.0 GB，最短 100 毫秒，未写时长上限。软件在上传前检查 5 GB，达到即在本机拦下。按 FLAC 体积约需 77 小时才会碰到。
- **语言**：文档接受 ISO-639-1 或 639-3 代码。软件原样传入，日语为 `ja`，中文为 `zh`。不选语言时不发送这个字段，由服务自动判断。
- **返回解析**：
  - 读取 `words[]` 中的 `text`、`type`、`start`、`end`、`characters[]`。
  - 逐字时间优先。逐字拼起来与词不一致时退回整词时间。
  - `spacing` 并入前一个字，`audio_event`（如掌声）跳过。
  - 秒换算成毫秒。
  - 遇到倒序时间判为结构异常。
- **报错**：
  - 401 等错误的 `detail` 是对象 `{status, message}`，取 `status` 作为错误代码，例如 `invalid_api_key`。
  - 422 的 `detail` 是列表 `[{loc, msg, type}]`，取第一项的 `type`。
- **限流**：文档未给出具体并发数。收到 429 只提示限流，不重试。
- **未覆盖**：只有配置了 webhook 才会收到 202，软件不使用 webhook。多声道返回的 `transcripts` 软件不使用，因为上传的音频始终是单声道。

## ElevenLabs 对齐（Forced Alignment）

- 来源：<https://elevenlabs.io/docs/api-reference/forced-alignment/create>
- **接口**：`POST https://api.elevenlabs.io/v1/forced-alignment`，表单字段 `text`（逐行歌词，用换行分隔）和 `file`，请求头 `xi-api-key`。
- **文档限制**：文件小于 1 GB。软件在上传前检查，达到即拦下，并提示选取较短范围。
- **返回解析**：
  - 读取 `characters[]`，拼起来必须与上传的歌词完全一致，再按原分行拆回，每行合并成词。
  - `words[].loss` 和整体 `loss` 原样保留在缓存中。
  - 文档没有说明换行是否作为字符返回。软件现在能处理三种情况：服务返回换行、省略换行、把换行换成空格。后两种会按原分行补回一个零长度换行。其他任何不一致仍然拒绝，因为对不上的歌词不能硬套时间。
- **报错**：与识别相同，422 同样是列表。

## Microsoft AI 转写（MAI-Transcribe）

- 来源：
  - <https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe>（页面更新于 2026-11-06）
  - REST 参考 <https://learn.microsoft.com/en-us/rest/api/speechtotext/transcriptions/transcribe?view=rest-speechtotext-2025-10-15>
- **接口**：`POST https://<资源>.cognitiveservices.azure.com/speechtotext/transcriptions:transcribe?api-version=2025-10-15`，请求头 `Ocp-Apim-Subscription-Key`。表单有两个字段：
  - `definition`（JSON）
  - `audio`（FLAC）
- **软件发送的 definition**：
  - `enhancedMode: {enabled: true, model: "MAI-Transcribe-2", modelOptions: {timestamps: "word"}}`
  - `diarization: {enabled: false}`
  - `locales: ["ja"]`：中文为 `["zh"]`；不选语言时不发送，由服务自动判断。
- **模型**：文档列出 MAI-Transcribe-2 和 1.5。MAI-Transcribe-1 已于 2026-08-20 弃用，软件用的是 2。
- **文档限制**：REST 参考写明音频“短于 2 小时且小于 250 MB”。另一页 LLM Speech 写的是 5 小时、500 MB，两页不一致，MAI 页面以 REST 参考为准，软件按更严的 2 小时、250 MB 执行：
  - 大小：上传前检查 250 MB。之前写的是 300 MB，比文档宽松，已改正。
  - 时长：上传前从 FLAC 文件头读出总采样数和采样率，算出时长，达到 2 小时即在本机拦下，并建议改用 ElevenLabs 或截短媒体。之前没有时长检查，超长音轨会先上传再被服务拒绝。读不出时长时不拦，交给服务判断。
- **地区**：增强模式只在部分 Azure 地区开放。返回“Enhanced mode is currently not supported yet”说明资源所在地区不对，需要换地区新建资源。
- **返回解析**：
  - 读取 `phrases[]` 的 `offsetMilliseconds`、`durationMilliseconds`、`text`、`words[]`。
  - 有逐词时间时按词切分。没有时保留句首句尾，句内按字均分，并标为估算。
  - `combinedPhrases`、`locale`、`confidence` 不参与时间计算。
- **报错**：
  - 错误体为 `{error: {code, message, innerError: {code}}}`。软件优先取内层代码，如 `AudioLengthLimitExceeded`、`InvalidLocale`、`EmptyAudioFile`，没有内层时取外层。
  - 时长超限、格式无法读取、音频为空、语言不支持这几种会在提示中直接写明。
- **限流**：收到 429（`TooManyRequests`，可能带 `Retry-After`）只提示，不重试。

## DeepSeek（注音与翻译）

- 来源：
  - <https://api-docs.deepseek.com/>
  - 错误码 <https://api-docs.deepseek.com/quick_start/error_codes>
  - 限流 <https://api-docs.deepseek.com/quick_start/rate_limit>
- **接口**：`POST https://api.deepseek.com/chat/completions`，请求头 `Authorization: Bearer <密钥>`。
- **软件发送的内容**：
  - 模型默认 `deepseek-flash`，API 设置里可改为 `deepseek-v4-pro`。旧名 deepseek-v4-flash 仍会指向 Flash。
  - `response_format: {type: "json_object"}`
  - `max_tokens: 12000`
  - `stream: false`
  - `thinking: {type: "disabled"}`
  - 每次最多 30 行、6000 字。只发歌词文字和行号，人工确认或锁定的句子跳过。
- **等待**：非流式请求在等待期间，服务会先发送空行保活。软件读取完整返回后再解析，前面的空行不影响解析，模拟场景按“先空行、后 JSON”的方式验证过。文档说明推理 10 分钟仍未开始时服务会断开，这时任务停在“等待服务处理”阶段，判为可能已计费，保留登记。
- **返回解析**：
  - `finish_reason` 不是 `stop` 时判为输出被截断，并提示减少行数。
  - `message.content` 必须是 JSON，并通过逐项校验：行号不变、原歌词逐字不变、人工分词边界不变、假名只含假名、罗马音合法、整句读音与分词读音一致。
  - 校验失败的结果不会应用。这类失败现在记为“解析结果阶段、通常已计费”。之前误记为“本机准备、未发出”，与付费登记不一致，已改正。
- **报错**：
  - 错误体为 `{error: {message, type, code}}`。软件取 `code`，没有时取 `type`。
  - 402 提示余额不足，401 提示密钥问题。
- **限流**：文档按账户限制并发（Flash 2500，Pro 500），超出返回 429。软件每次只发一个请求，收到 429 只提示，不重试。

## 运行检查

```
cd E:\transcribe\karaoke-studio
.\.venv-desktop\Scripts\python.exe scripts\check-services.py
.\.venv-desktop\Scripts\python.exe scripts\check-services.py --real
```

- 第一条是模拟检查，不联网，几秒钟完成，应显示“共 27 项：通过 27，失败 0”。
- 第二条是真实检查。它先列出要发送的内容，输入 `y` 才发送，会产生少量费用：两段 16 秒音频识别、一段 16 秒对齐、一次短注音。可以用 `--only elevenlabs deepseek` 只查其中几家，用 `--language zh` 改识别语言。
- 真实报告中，对齐一项会与 PJS056 人工标注比较句首、句尾误差，供参考，不设合格线。故意写错密钥的三项应显示 HTTP 401 或 403、阶段“服务拒绝”。
- 超时、限流（429）、服务出错（5xx）、取消这几种情况，只有模拟证据。故意去触发真实服务的这些状态，会浪费额度或违反使用条款，所以不做真实检查。
