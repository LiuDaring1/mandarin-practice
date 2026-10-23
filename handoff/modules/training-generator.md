# 模块：训练内容生成器（training-generator）

> **2026-10-23 当前档位**：前台字词 3／5 分钟、默认 3。生成器允许 3／5／10 分钟，10 分钟只保留接口兼容；配置仍由原 v2 管线读取。奖励新 3 分钟档为 360，见奖励模块。

> 给 AI 的 3 行摘要：基于 phonology-v1 的 16,149 条可用 item，按 Profile 平衡随机生成训练
> Session（候选过滤 → 覆盖率权重 → Top-K 加权随机 → 顺序约束 → 时间预算）；支持音筛选白名单。

## 职责

把语料库变成「字词 Tab」的一次训练会话：给定训练目标 Profile 与时长，生成题目序列，
保证覆盖率均衡、历史软避让、时间预算可控。

## 现状（2026-08-23）

- v2 生成器可用；66 个真实 Session 自动 QA 通过（v1 节点）。
- `include_finals` 音筛选：`/api/sessions` 支持韵母白名单，前端弹层勾选（前鼻 8 / 后鼻 8 / 对比 5 组 + 2 其他），存 localStorage。

## 关键文件

| 内容 | 位置 |
|---|---|
| 生成器 | `src/pth_corpus/training/v2/`（`generator.py`、`history.py`、`schema.py`、`engine.py`） |
| 配置/Profile | `data/derived/training-generator-v2/training_profiles_v2.json`、`generator_config_v2.json` |
| 产物 | `data/derived/training-generator-v2/sessions/`、`data/derived/prototype/sessions/`（应用实际会话） |
| CLI | `python -m pth_corpus training candidate-stats|generate|benchmark` |
| 历史软避让 | `HistoryStore`（`data/derived/prototype/history/<profile>.json`，窗口 7 天/7 会话） |

## 数据

- 候选统计：`data/derived/training-generator-v1/candidate_pool_stats_v1.json` 等（v1 时代产物，v2 同目录）。
- 生成器只读母库与 `phonology.sqlite3`，不写母库。

## 待办

- 无阻塞项。改 Profile/权重前先跑 `training benchmark` 做 QA 对比。
- 里程碑：`handoff/MEMORY-2026-08-08-training-generator-v1.md`、`MEMORY-2026-08-10-training-generator-v2.md`。
