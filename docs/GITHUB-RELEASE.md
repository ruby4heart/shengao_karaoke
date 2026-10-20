# 每个功能版本的 GitHub 交付

指定仓库：https://github.com/ruby4heart/shengao_karaoke 。从 0.21.0 开始，每个完成并验收的功能版本单独提交、打 `vX.Y.Z` 标签并发布 Release，保留既有本地发行与历史标签。

仓库保存可比较的声稿源码、文档、测试和演示。完整第三方源码、字体、运行时、模型及许可随 Release 的完整源码 ZIP 提供，参见 `vendor/GIT-SOURCE-NOTES.md`。GitHub 自动生成的源码快照不包含未跟踪的依赖，应下载明确命名的完整源码 ZIP。

## 发布顺序

1. 冻结版本功能，更新 ToDo、说明及本版本验收；当前源码完成全部回归、离屏实例、正常／150% 独立包与原版像素检查。
2. `prepare-desktop-release.py` 生成新的运行包和完整源码 ZIP；逐文件审计、保留验收记录和 SHA256，已有发行不覆盖。
3. `package-public-evidence.py --version X.Y.Z --tag vXYZ` 提取公开验收子集；不包含用户原片、正式 MV 截图、私人工作工程和任务缓存。完整本地验收保留。
4. 提交源码与说明并推送，创建与该提交一致的版本标签，再运行 `publish-github-release.py --version X.Y.Z --evidence-tag vXYZ --notes-file docs/releases/X.Y.Z.md`（`vXYZ` 使用本次本地验收标签，例如 `v021`）。
5. 发布脚本创建草稿，上传 Windows ZIP、完整源码 ZIP、公开验收 ZIP 和归档 SHA256 清单；核对远端资产大小、SHA256 和标签提交后公开。上传中断保留草稿；重新执行时只复用指纹一致的资产，不覆盖已发布版本。

登录使用已配置的 Git 凭据管理器或显式设置的 `GITHUB_TOKEN`，凭据不进入命令参数、工程、日志或归档。公开验收 ZIP 自身的 SHA256 由 GitHub 资产摘要与发布回执记录，运行包／完整源码 ZIP 的 SHA256 同时保存在附带清单。

`build/github-release-X.Y.Z.json` 是发布回执，记录远端 URL、提交、标签及资产指纹。每次发布后重新读远端核对，不把本地 ZIP 已生成等同 GitHub 已完成。
