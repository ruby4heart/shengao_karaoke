# 声稿 0.18.0：本机人声辅助与原声对照

对应完整待办第 3 组第三项。原唱／伴奏视频换源保留；新增的“试听：原声／人声”只控制试听与音频底图，成片仍使用当前视频源。工程格式为 6，可读取 1–6；请用新版保存副本，旧版会拒绝新格式。

| 行为 | 验证 |
| --- | --- |
| 本机真实分离 | CPU PyTorch 2.8.0、Demucs 4.0.1、官方 htdemucs；固定 SHA256 校验后才加载。内置独立引擎、模型与许可证，不依赖用户 Python 或密钥 |
| 时间同步 | FFmpeg 解码 44.1 kHz 双声道；模型输出逐帧数核对；试听视频以原画面流和人声音轨重新封装，单播放器负责慢放、跳转和循环 |
| A/B 和人工校轴 | 人声频谱／波形同时切换；保持播放点、速度、静音、视频缩放、时间轴缩放和视野。歌词、注音、确认及锁定不改动 |
| 源与输出独立 | 即使试听人声，实际导出仍含选定视频源的音轨；合成的 440 Hz 原声与 880 Hz 辅助音轨用于实解码验证 |
| 本地缓存与失败 | 原素材完整指纹、模型与输出指纹绑定，跨实例锁防止同时改写；取消／失败清理临时文件，旧试听和人工修改保留；成功缓存复用不重复推理 |
| 保存与撤销 | 人声资源复制到工程 `.assets/audio` 并校验；重开可复用。添加音轨一步撤销；撤销到没有该音轨时回到原声，源视频切换时也回到原声 |

专项测试为 `desktop/tests/test_vocal_audio.py`，包含真实模型推理及真实媒体 A/B、慢放循环、实际输出音轨、资源保存、取消、迟到人工修改和损坏处理。背景失败使用可控模拟，不能视为真实分离质量验证。正常与 150% 的独立运行包均执行实际内置模型，不在 PATH 中提供 Python。

正式 MV：`E:\media\Emerald ⧸ 楽園【OFFICIAL MUSIC VIDEO】 .webm`。15 秒片段实际 CPU 推理 18.656 秒、661500 帧；整首提取与分离耗时 197.235 秒，输出 11921409 帧，即 270327ms，与原声解码长度一致。视频容器约 270348ms，不将容器片尾当成人声音频采样数。原片 SHA256 前后均为 `1972808f0caddffdc5d447d3204469e8fe23ff94d27d1861d3523c6cd63b4ac8`。整首记录在 `tmp/v018-formal-vocals/report.json`，并提供 45–60 秒原声／人声试听片段。输入仅本地读取，不上传、不改写；片源、歌曲缓存和用户工程不打入公开运行包／源码包。

发行门槛为完整回归、12 组原版绘图逐像素对照、开发版及两种缩放独立包验收、全部 PE 依赖、归档 CRC 与文件哈希、旧发行版和原始 Aegisub 保护。最终计数和哈希以 `build/desktop-final-audit-v018.json`、`build/v018-evidence` 和 `dist/SHA256SUMS-0.18.0.txt` 为准。

模型可能残留伴奏、产生伪影或削弱尾音，必须对照原声；分离不是实际音节边界识别。本版没有把分离音轨自动上传为转录输入，也没有宣称解决特殊唱法、真实摩拉精度、整首字幕制作或真人新手验收。未使用 Computer Use、用户密钥或收费 API。

模型来源与许可：[官方模型列表](https://github.com/facebookresearch/demucs/blob/main/demucs/remote/files.txt)、[默认 htdemucs 配置](https://github.com/facebookresearch/demucs/blob/main/demucs/remote/htdemucs.yaml)、[MIT 许可](https://github.com/facebookresearch/demucs/blob/main/LICENSE)。依赖版本与构建见 `desktop/vocal-requirements.lock` 和 `DESKTOP-BUILD.md`。
