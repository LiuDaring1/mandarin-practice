# 模块：听辨练习（discrimination）

> 2026-10-23：路线图 #5 已实现。整词所有判断点答完后，若该词答错，自动播放整词示范音一次，继承首页所选新闻男／女声，播放结束再前进；答对仍为 700 ms 反馈且不播示范。轻触跳过、离页和后台会取消声音及旧回调，12 秒看门狗／加载失败不锁死题目。教学音播放时抑制重叠音效；不更改判题、错题排期与奖励。独立 Ego 页面验收覆盖双声、仅错播、等待结束、取消及过期回调，见 `../news-assessment-2026-10-22/ui-report.json`。下文早期奖励数字为历史描述，以现行奖励模块为准。

> 给 AI 的 3 行摘要：前后鼻音逐字判断。v3 = 主词库「轮次+固定乱序+游标」持续覆盖 +
> 词库批末趁热巩固 + 长期错题复习（1/3/7 天间隔、复习轮内答错复现）。3,796 候选词 /
> 4,158 判断点 / 177 交叉词。首页第三 Tab 双卡片。

> 2026-09-12：全页 UI 换新；结算传参按本次词数档位和已完成主词库词数，避免多音节判断／趁热巩固导致档位匹配失败。现有 API、错题结构、1/3/7 天规则不变。见 `../MEMORY-2026-09-12-ui-refresh.md`。

## 职责与设计（v3，2026-08-23 收口）

1. **主词库 = 覆盖**：每轮只洗牌一次成固定乱序，游标持续向后，整轮全覆盖后换轮重新洗牌；
   题量 50/100/150（默认 50）；词库增减只影响待练区。
2. **趁热巩固 = 刚错的马上改对**：一轮做完，本轮错词自动重测（答对出队、答错显示答案后排队尾），
   直到全部过关才结算；不改长期排期，不给额外奖励。
3. **错题复习 = 跨天验证**：主词库答错即入复习系统，每词 `1 天 → 3 天 → 7 天 → 掌握退出`；
   到期滚动累积；复习中答错 → 显示答案 + 排队尾，滚完复现，复现答对 → 重置回明天，
   一次就对 → 前进一格，三次跨天过关 → 掌握（历史保留）。顺序一次洗牌固定。
4. 奖励：当天完成全部「今日待复习」→ 一次性 `review_reward`（当前 +2，当日一次）。
5. 速度：整词反馈 0.7s + 反馈期轻触跳过。

## 关键文件

| 内容 | 位置 |
|---|---|
| 状态机（游标/排期/迁移） | `src/pth_corpus/discrim_progress.py`（`DiscrimProgress`） |
| 池子/判题 | `src/pth_corpus/discrimination.py`（`build_discrim_pool`、`judge_answer`） |
| 端点 | `prototype_app.py` 的 `/api/discrim/*` |
| 前端 | `prototype_static/app.js`：搜 `discrim`（`startLibraryPractice` / `startWarmupPhase` / `startReviewPractice` / `DISCRIM_FEEDBACK_MS`） |
| 配置 | `src/pth_corpus/prototype_data/discrim_config_v1.json`（题量、`review_intervals_days`） |

## 数据（用户真实数据，勿清空）

`data/derived/prototype/discrim_progress.json`（version 3）：

- `library`: `{round, cursor, total, order}` —— 当前游标 100 / 3796。
- `mistakes`: 每词 `{wrongCount, reviewStage(0..3), nextReviewAt(YYYY-MM-DD), lastReviewedAt, masteredAt}`；
  stage 3 = 掌握。当前 66 个错词 stage 0、明天到期。
- `review`: `{order}` 复习固定顺序；`word_stats`: 每词 `{total, correct, wrong, ...}`。
- 旧版状态 load 时自动迁移并落盘。

## 端点

`GET /api/discrim/state`；`POST /api/discrim/library/session|result`、`warmup/session`、
`review/session|result`、`answer`、`seed-mistakes`、`events`。settle 支持 `activity: "review"`。

## 测试与走查

- `tests/test_discrim_progress.py`（状态机单测）+ `tests/test_discrimination.py`（端点）。
- 走查小技巧：在 `data/derived/prototype/` 放 `discrim_config_v1.json` 覆盖配置，设
  `review_intervals_days: [0, 3, 7]`（首间隔 0 = 答错当天到期）即可小样本走通全链路；走完删除并重启。
- ego-browser 坑：页面 fetch 连续约 20 请求后会卡（传输层问题），循环里加看门狗 reload 重进；
  反馈窗口 0.7s 内读 `.dslot .slot-final` 的 class 学正确答案；隐藏元素用 DOM `.click()`。

## 待办 / 可调口径

- `review_reward = 2`、间隔 `[1,3,7]`、反馈 `700ms` 均配置化，随时可调。
- 历史里程碑：`handoff/MEMORY-2026-08-16-discrimination.md`、`MEMORY-2026-08-16-unified-rewards.md`、
  `MEMORY-2026-08-16-reward-v2-designer.md`；本次 v3 详见 `handoff/CHANGELOG.md` 2026-08-23。
