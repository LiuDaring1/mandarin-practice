# GitHub 版本基线决策 · 2026-09-16

用户要求给现阶段软件建立版本管理并推送自己的 GitHub，供所有 agent 及时获取同步信息；进一步明确选择公开仓库。

正式代码位于 `普通话语音系统-zcode`，原来它没有独立 `.git`，只作为父目录旧仓库的未跟踪子目录存在。本次以正式目录初始化独立 main，把当前可交付状态作为 v0.2.0 快照。父目录和旧历史不变，另保留本地 Git bundle，避免把旧数据或未审查历史公开上传。

目标公开仓库为 `LiuDaring1/mandarin-practice`。版本号统一到 VERSION、pyproject、uv.lock、Python 包与 CLI；发布带注释 tag 和 GitHub Release。AGENTS / CONTRIBUTING 指定最新状态入口、分支／worktree 协作、PR 交接、数据保护和收工同步规则。

所有待上传文件复制到不含本地语料的干净临时目录，pytest 319 通过、1 旧 pilot 夹具跳过。CLI 版本专项 8 通过。公开内容不含真实练习记录、数据库、原始／派生教学媒体、第三方素材原包或密钥。完整 APP 的数据准备独立说明，不能把“代码可克隆”误解为“完整语料随仓库分发”。

本记录是首次 GitHub 管理节点；后续变更更新 STATUS / CHANGELOG，不覆写此历史决策。

首次推送被 GitHub 拒绝写入 workflow 文件（现有 OAuth token 无 workflow scope）。为完成用户要求的代码与版本同步，自动测试配置改为 `ci/github-actions-tests.yml.example`，待有对应授权后启用；当前没有云端 CI 成功结论。
