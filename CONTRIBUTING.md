# 版本与协作

正式仓库：https://github.com/LiuDaring1/mandarin-practice

当前首个公开管理基线是 **v0.2.0（2026-09-16）**。早期 0.1 原型和未提交的本机演进保留在旧目录，本仓库从当前完整代码快照开始，不把未审查的旧 Git 历史公开上传。

## 分支与同步

- `main`：已整合的版本；`codex/<topic>`：每个 agent 的独立任务。
- 开工先 `git fetch origin --prune`。干净 main 可 `git pull --ff-only`；任务分支按需合入最新 main，解决冲突后复测。不得强推共享 main。
- 同机多 agent 推荐 `git worktree add ../mandarin-<topic> -b codex/<topic> origin/main`，或各自 clone。不要在同一工作树同时切分支。
- 完成后推送分支并创建 PR，交代改了什么、如何验证、还有什么限制；获授权后合并。交接文档和代码在同一个提交里更新。
- GitHub 不会自动同步另一个 agent 正在写但尚未推送的内容；开始和结束任务时都要检查同步状态。

## 版本号

采用 `MAJOR.MINOR.PATCH`：破坏兼容的变更升主版本，新增功能升次版本，修复升补丁版本。在 0.x 阶段仍是原型，重大产品调整升次版本。

发版同步更新 `VERSION`、`pyproject.toml`、`uv.lock` 中本项目版本及 `handoff/releases/vX.Y.Z.md`；验证通过后创建带注释 tag `vX.Y.Z`、推送 tag，并建立 GitHub Release。已经发布的 tag 不移动。

## 开发和测试

需要 Python 3.11–3.13；FFmpeg/FFprobe 用于音频相关测试。安装 `uv` 后：

```bash
uv sync --locked --extra dev
uv run pytest
```

没有 uv 时可 `python -m venv .venv`，激活后 `python -m pip install -e '.[dev]'` 再 `python -m pytest`。自动测试模板使用合成夹具，不需要私有训练库；依赖完整库或媒体的手动验收需按 `handoff/LOCAL_DATA.md` 准备本地数据。

当前界面为本地 FastAPI + 静态前端。具备本地数据时：

```bash
uv run pth-corpus prototype --data-root data --port 8769
```

提交前检查 `git diff --check`、`git diff --cached --stat`，不纳入真实数据、秘密或第三方素材原包。公开代码可阅读并协作，不代表获得第三方教学语料的再分发许可，见 `SOURCE.md`。

## 自动测试启用状态

本地干净代码测试已通过。GitHub Actions **尚未启用**：当前 GitHub OAuth 登录具有 repo 权限，但缺少上传 workflow 所需的 workflow 权限。模板保存在 `ci/github-actions-tests.yml.example`。后续具备 workflow 写入权限后，把模板复制到 `.github/workflows/tests.yml` 并提交推送即可。此前不要宣称云端 CI 已运行或显示绿色状态徽章。
