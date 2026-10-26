# 完整第三方源码和运行资源

Git 仓库保存声稿自身的 desktop、backend、native、scripts、docs 与演示代码。大型第三方开发副本、SDK、字典、字体、运行时和模型不重复放入 Git 历史。

每个版本的 GitHub Release 都附 `ShengaoKaraoke-X.Y.Z-source.zip`，含与该版本匹配的完整 `vendor/`、第三方源码、固定模型、许可与构建资料。下载同版本完整源码 ZIP 后解压至独立目录，按 `docs/DESKTOP-BUILD.md` 构建；不要将另一版本依赖直接覆盖到正在编辑的工作区。

运行软件请选择 `ShengaoKaraoke-X.Y.Z-final-win64.zip`，完整解压后启动，无需构建。GitHub 自动生成的 “Source code (zip)” 只有 Git 跟踪文件，不能代替附带完整依赖的源码包。

旧本地发行版和用户原始 `E:\transcribe\Aegisub-3.5.0` 保持。代码、字体、第三方库与模型分别遵循随附许可，TIFA 权重限非商业用途。

0.30开发树增加 `vendor/orjson/`：官方3.13.0的Windows CPython 3.12 wheel、完整源码归档、METADATA、来源与SHA256，以及wheel随附的Apache、MIT和MPL许可。文件由 `scripts/fetch-json-runtime.py` 按固定来源恢复，完整源码ZIP一并携带；运行包保留许可与来源。构建核对归档、许可和已安装模块，不能以版本号相同代替字节核验。
