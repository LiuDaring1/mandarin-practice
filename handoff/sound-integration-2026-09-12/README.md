# 方案 A 音效接入 · 2026-09-12

用户听过免费音库后认为音效与场景不合，选回原方案 A：保留大部分，优化奖励后安装 APP，预留以后直接替换素材的插槽。本轮已按此授权完成，正式前端刷新生效；训练端口 8769 未重启。

## 交付

- [APP](http://127.0.0.1:8769/) 使用七种原 A 日常声音与四种优化奖励：到账 0.72 秒、三练 0.96 秒、作品 1.25 秒、集齐 1.65 秒。12 个日常样本与原文件完全相同；四种奖励沿用 A 动机、上行音粒与短亮泛音、干净收尾。
- 11 个插槽、16 个 44.1 kHz / PCM16 无损 WAV，全是项目原创合成，无付费素材。运行时映射与替换说明：[sounds/README.md](../../src/pth_corpus/prototype_static/sounds/README.md)。只改 `variants` 与 `gain`，保留事件 ID 即可替换，无需改训练逻辑。
- `sfx.js` 适配原 APP。教学优先、正误反馈只在辨音判定后、三练替代到账、集齐替代单件、结算去重、长按 100 ms 限流、松手取消。单击保留 66 ms 完整短音。
- 首页新增音效开关与音量，默认开、70%；独立偏好 key，不改示范媒体音量。音库加载失败时练习仍可用，丢失音效不补播。
- 修复接入时发现的开关回写竞争、融合旧回调覆盖新弹层。只增加音效和取消控制，未改训练计时、判题、奖励额度或作品数据规则。应用改动见 `app.diff`。
- [同文件试听](http://127.0.0.1:8772/) 直接读 APP 运行清单与 WAV，四类奖励可与原 A 对比。`/index.html`、`/library.html` 保留历史页，第三轮 90 个免费原音未进入 APP。

## 验收证据

- `sound-contract-report.json`：14 项通过，覆盖手势解锁、16 样本解码、静音／音量持久化、示范优先、跟读不判对、标准音顺序保护、结算去重／互斥、真实最后一颗到单件／集齐、关闭融合取消、轻点不截断、真实长按限流／停止、四档布局、仅替换映射、清单失败仍可练习。
- `full-flow/qa-results.json`：12 项通过，84 张截图、360/390/430/1024 宽度无横向溢出、无 JS 运行错误。实际 UI 操作验证字词／句子示范与跟读、600 拼点、真实长按完成麦克风、50 词辨音＋2 错词巩固的 300＋三练 100、到期复习 100、标准音视频、外网断开仍可加载、错误恢复与不足 20% 无奖励。
- 全流程为节约等待使用原有 debug 提前结算字词与句子；辨音通过实际按钮和 API 判题。QA 在反馈函数末端取消自动 700 ms 下一词计时，防止截图等待或工具延迟跳词，随后显式切下一词。正式 APP 的 700 ms 时序未改。跨天到期接口仅存在于临时 QA 服务。
- `settings-*.png`：四档音效设置截图，390px 已目检；完整流程截图在 `full-flow/screenshots/`。
- `preview-report.json` / `preview-390.png`：同文件试听页的真实手势播放、0.72 秒文件时长、停止、15 个按钮及手机布局通过；ego-browser 也验证了手势播放与停止，验收任务空间已关闭。临时 8773 QA 服务已结束，8769 与 8772 保持运行。
- `assets/sound-design/qa/integration-v4/audio-report.json`：16 WAV 数值检查通过，首尾归零，4 倍插值真峰值估计低于 −15 dBFS。机器指标不等于好听，尚未替用户宣称手机／耳机主观验收通过。
- pytest：319 通过、1 预期跳过（本轮运行）。
- `protection-report.json`：98 个受保护文件哈希不变，包括真实进度／日志／历史与原 30 WAV，无新增真实进度文件；正式与试听服务各 16 样本逐字节匹配交付文件。浏览器验收使用新建上下文，没有操作用户浏览器 localStorage。

## 重跑

在项目工作目录启动**新的临时进度**服务；重复完整流程前应结束自己那次 QA 服务并重启，以免读到上次 QA 的辨音游标。不要指向 8769：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python scripts/serve_ui_qa.py --port 8773
```

另开终端执行（Node 与 Playwright 使用 Codex 已捆绑依赖）：

```bash
NODE_PATH=/Users/baiyanglin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules /Users/baiyanglin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/qa_sound_integration.cjs
NODE_PATH=/Users/baiyanglin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules /Users/baiyanglin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/qa_sound_contract.cjs
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -m pytest -q
```

试听服务：`PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python scripts/serve_sound_lab.py`（只读白名单，8772）。

## 回退与后续

`backups/frontend-before.tar.gz` 保留接入前完整静态前端。回退时先在临时目录解包、比较并只还原本轮修改的 `app.js`、`index.html`、`ui-theme.css`，移除新增 `sfx.js` 引用；不要整包覆盖之后的 UI 工作。奖励微调优先仅回退清单中的四个文件映射，原 A 对照在实验室 `exports/`。

不改真实进度文件，不用备份覆盖用户后来练习的数据。旧 MEMORY 文档是历史快照，现行状态以 `handoff/STATUS.md` 为准。未来找到更合适的素材可通过插槽替换；音色主观调整不需要重做训练功能。
