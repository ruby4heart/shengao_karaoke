# 声稿 0.12.0 验收范围

按用户要求先导出 0.11.0，再实现本轮六项要求。0.11.0 发行包与源码归档的 SHA256 在最终审计中再次核对。

| 需求 | 实现与行为 | 验收依据 |
| --- | --- | --- |
| Aegisub 三个滑条 | 音频右侧竖向时宽、显示增益、实际试听音量；前两项双击复位，不改工程时间 | `test_v012_editor.py` 控制真实 Timeline 与 QAudioOutput，独立运行验收 |
| 字幕错位易于拖动 | 旧时间不在视野也可抓取整句；移到播放点保持全部相对时间；边缘平移、取消与一步撤销，保护锁定内容 | 整句错位、非 10ms 原起点、边缘拖动、Esc、锁定与 Undo/Redo 测试 |
| 易懂且有顺序的工作流 | 各阶段明确下一步，读音／时间分别确认；主窗口文字按钮均有范围说明 | 新手下一步实际点击测试、所有主按钮说明检查、五阶段离屏图 |
| 五步按钮默认隐藏 | “流程”展开／收起且保存偏好；非校准页默认大视频，小窗口校准优先完整时间轴 | 展开高度变化、偏好往返、960×620／960×680／1280×800／1460×940 实际布局，展开导航时仍不裁切 |
| 分词与注音入口 | 视频上方 ①分词／②注音／③调时间；未匹配句可分词、原文字符切分、词组假名直接修改 | 实际模态窗口、原文保持、应用和一步撤销 |
| 弱尾音辨认与修改 | 默认末音，带前音或当前音慢放、保留音高、循环；可选低频衰减增强；放大频谱、10ms 和单音读音修正 | 实际 PCM／媒体播放、频响和源音频不变、待编辑值保留、取消与一步撤销 |
| 更清楚的日文字体 | Noto Serif CJK JP Black 正文＋BIZ UDPGothic Bold 假名及简洁粗黑模板；保存实际字体与字重 | 字体覆盖、授权和哈希；混合字体库与单 Black 一致；实际 FFmpeg 帧与实时预览对照 |

本轮单元与交互测试主要位于 `desktop/tests/test_v012_editor.py`，已有键位、连续划音、上一句参照、双行排版和 API 模拟回归仍全部执行。原生音频／时间轴绘图函数未改写。

## 发行证据

最终冻结源码完整回归 **258 项通过**；开发实例 **74 项通过**；正常与 150% 缩放的独立运行包验收各 **74 项通过**；**187 个原生依赖**无缺失。两种缩放各 6 个原版时间轴场景均为 **零差异像素**。运行包包含 811 个清单文件。所有证据在归档时核对当前源码快照，最终归档完整性以审计 JSON 为准。

- 全量回归：`build/desktop-tests.xml`；源码快照：`build/desktop-test-sources.json`。
- 开发实例：`tmp/desktop-v012-final/report.json`，包含真实播放、离线分词、工程及 ASS 往返、样片／全片／音频视频压制和本轮控件。
- 独立运行包：`build/desktop-package-test.log`、`build/desktop-package-dpi150-test.log`；各自使用隔离 home 与 PATH，不依赖系统 Python。
- 原版时间轴：`tmp/timeline-full-pixels/report.json`、`tmp/timeline-full-pixels-dpi150/report.json`，正常和 150% 缩放各 6 个场景，要求零差异像素并绑定当前源码快照。
- 原生依赖：`build/desktop-dependencies.json`。
- 最终审计：`build/desktop-final-audit-v012.json`，校验当前源码、测试、运行包清单、便携 ZIP、全部源码归档文件、旧版 SHA256 和原始 Aegisub 绘图文件。

不使用 Computer Use、真实密钥、用户媒体或付费 API。接口依赖模拟 HTTP 与合成音频；这不代表对真实云端服务做了付费联调。自动匹配、词典与 LLM 读音仍需试听确认。尾音增强同时受伴奏影响，不能自动识别“て／す”；修改单音假名会保留原文，原文本身有误应回原文编辑。

## 字体与发音资料

随包字体来源、版本、SHA256 与 OFL 在 `desktop/assets/fonts/SOURCES.json` 及对应授权中。BIZ 来源为 [Morisawa 官方仓库](https://github.com/googlefonts/morisawa-biz-ud-gothic)，Noto 来源为 [Noto CJK 官方仓库](https://github.com/notofonts/noto-cjk)。

句末“す”的元音可能弱化或无声化，实际唱法须结合录音；参考[日本国立国语研究所说明](https://kotoba.ninjal.ac.jp/qa/yokuaru/qa-215/)。该现象不等于所有“て／す”都应缩短或省略。
