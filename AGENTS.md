# Agent 协作入口

本仓库是普通话练习 APP 的正式项目。以 `git rev-parse --show-toplevel` 返回目录为根；维护者本机对应 `普通话语音系统-zcode`。父目录是旧项目，不在本仓库内，不要编辑或回退它。

## 开工

1. 读 `README.md`、`handoff/STATUS.md`、`handoff/ROADMAP.md`，再读涉及模块的 `handoff/modules/*.md`。
2. 读 `CONTRIBUTING.md`，检查 `git status --short`、当前分支、`git remote -v`；有网络时 `git fetch origin --prune`。
3. 在干净工作树以最新 `origin/main` 建 `codex/<topic>` 分支；多个 agent 使用各自 clone 或 worktree。不要覆盖别人的未提交修改，不自动 reset、强推或清理文件。共享本机目录时，按任务明确文件范围。
4. `STATUS.md` 是唯一现行状态；`MEMORY-*` 和旧日期快照是历史，不能用它们覆盖新版决定。

## 数据边界

- GitHub 只同步代码、配置、可公开项目资产和交接说明；不包含完整训练语料、教学录音或真实进度。新机器运行条件见 `handoff/LOCAL_DATA.md`。
- 严禁提交 `.env`、令牌、密钥、SQLite 数据库、真实进度／历史／日志和第三方素材原包。不要 `git add -f` 绕过这些排除。
- 真实数据在 `data/derived/prototype/` 与用户浏览器 localStorage；自动验收使用 `scripts/serve_ui_qa.py` 的临时目录和独立浏览器上下文，绝不以测试数据覆盖真实记录。
- 当前 A 音效默认开启、70%，首页无设置入口；11 个插槽保留。跟读计时不是发音评测，不能当作答对播放反馈。

## 收工

- 做与改动相关的验证；记清通过、跳过、未运行及其原因，不把历史测试写成当前结果。
- 更新 `handoff/CHANGELOG.md`、`handoff/STATUS.md` 和相关模块说明；大节点新增不可变 `MEMORY-*`，不改历史快照。
- 提交前检查 `git diff --check`、差异与暂存文件清单；提交相关文件，推送任务分支并发 PR。只有经用户授权的合并才进入 `main`。
- 未完成任务在 PR 说明中写明分支、已完成内容、阻塞点、下一步和数据依赖。其他 agent 以 GitHub 已推送提交为同步依据；本地未推送修改不可见。
