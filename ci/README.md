# 自动测试模板（尚未启用）

`github-actions-tests.yml.example` 是待启用 GitHub Actions 配置。当前 OAuth 登录缺少 workflow 写入权限，因此没有向 `.github/workflows/` 安装。

获得相应权限后，复制为 `.github/workflows/tests.yml`、提交并推送。模板执行 Python 3.11 的无私有语料测试和版本一致性检查，需要 Ubuntu FFmpeg。详情见根目录 CONTRIBUTING.md。
