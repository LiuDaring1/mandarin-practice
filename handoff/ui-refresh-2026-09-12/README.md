# UI 换新验收资料

实现说明见 [交接记录](../MEMORY-2026-09-12-ui-refresh.md)，素材和提示词见 [素材说明](../../assets/ui-refresh/README.md)。

| 证据 | 文件 |
|---|---|
| 前端改造前快照 | `backups/frontend-before.tar.gz` |
| 全流程 12 组检查、84 个截图点 | `qa-results.json` |
| 短屏／异常／奖励边界 6 组检查 | `qa-edges.json` |
| 319 通过、1 预期跳过 | `pytest-results.xml` |
| 真实数据走查前哈希 | `user-data-before-qa.json` |
| 真实数据走查后比对 | `user-data-after-qa.json` |
| 93 张有效截图 | `screenshots/` |

用当前项目目录中的父级 Python 环境启动独立验收服务：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python scripts/serve_ui_qa.py
```

然后用带 Playwright 的随附 Node 运行 `scripts/qa_ui_refresh.cjs` 和 `scripts/qa_ui_refresh_edges.cjs`。每次完整重跑应重启验收服务获得全新临时进度。不要把验收脚本的 8771 地址改为真实预览的 8769。

浏览器测试不需要用户提供麦克风或登录。字词与句子完成时长在测试中加速；没有使用语音评分。单击、键盘和长按拼豆均通过实际输入事件验证。
