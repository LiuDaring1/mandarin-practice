# 普通话训练 Session 组合规则 v2.1 调整说明

> 基于 v2.0《核心/补充/对比/动态补位框架》+ 真实候选池扫描 + 用户决策，对 v2 实现前的规则做最终调整。

## 1. 确认的口径

### 1.1 Profile 允许重叠，互不影响

- 同一个目标音可以同时属于多个 Profile：`zh/ch/sh/r` 同时属于“纯翘舌组”和“平翘舌对比组”。
- Profile 之间独立生成，不互相排斥、不共享配额。
- 翘舌组：`T={zh,ch,sh,r}`（r 归翘舌）。
- 平翘舌对比：`A={z,c,s}`、`B={zh,ch,sh,r}`，100% 在 A/B 体系内部，`O=0`。
- 保留 `flat_retroflex_no_r`（`B={zh,ch,sh}`）作为可选变体；v1 现有 `initial_flat_retroflex` 不变。

### 1.2 三字词：有多少用多少

- 词长比例（单 15% / 双 65% / 三 20%）只是软目标，以真实 Availability 为准。
- 全库“三字及以上全核心”词极少（平翘含 r 仅 1 条，双唇/n/l 为 0），报告如实标注，不硬凑。

### 1.3 长时长稀缺：自动降级补位

优先级（按文档 §27 调整）：

1. 核心桶内先用足（含单字核心点）；
2. 核心内 pattern 平衡；
3. 仍不足 → 允许间隔重复：`max_item_repeat_per_session=2`、`min_repeat_gap_items=20`；
4. 只有 `allow_other=true` 的 Profile 才允许提高补充/关联桶比例；
5. 高纯对比 Profile（平翘、前后鼻）不引入 O，只允许重复；
6. 每一步都在报告中标记 `core_pool_insufficient=true` 与“实际达到的纯度”。

结论：20 分钟纯专项能做到多纯就多纯，不硬撑。

### 1.4 不可用组合：跳过或相关补位

- Availability Matrix 标记 `unavailable`，该 pair 不进 Session 配额。
- 对比 Profile（O=0）：直接跳过该 pair，只在报告中说明“理论存在、语料缺失”。
- 非对比 Profile：可用 `T+O / O+T` 相关组合自然补位。
- `uen↔ueng`：真实候选为 0（ueng 全库仅 4 个音节），默认不启用。

## 2. 真实核心池测算（含单字核心点）

> 估算：单题平均约 3.2s（1 遍）；核心占比按 Profile 配额。

### 2.1 声母（80% 核心，j/q/x 为 70%）

| Profile | 核心池(双字+单字) | 5m | 10m | 15m | 20m |
|---|---:|---|---|---|---|
| 双唇音 b/p/m | 513 | OK | OK | OK | OK |
| 平舌 z/c/s | 264 | OK | OK | OK | **缺36，需间隔重复** |
| 翘舌 zh/ch/sh/r | 1060 | OK | OK | OK | OK |
| n/l | 332 | OK | OK | OK | OK |
| j/q/x（70%） | 1064 | OK | OK | OK | OK |
| 舌根 g/k/h | 535 | OK | OK | OK | OK |
| d/t | 410 | OK | OK | OK | OK |

### 2.2 高纯对比（100% 内部）

| Profile | 核心池 | 5m | 10m | 15m | 20m |
|---|---:|---|---|---|---|
| 平翘含 r | 1692 | OK | OK | OK | OK |
| 平翘不含 r | 1525 | OK | OK | OK | OK |
| 前后鼻对比一 en/eng/in/ing | 705 | OK | OK | OK | OK |
| 前后鼻对比二 an/ang/ian/iang/uan/uang | 1107 | OK | OK | OK | OK |

### 2.3 韵母（80% 核心）

| Profile | 核心池 | 5m | 10m | 15m | 20m |
|---|---:|---|---|---|---|
| 单韵母 | 1678 | OK | OK | OK | OK |
| 前响 | 523 | OK | OK | OK | OK |
| 中响 | 373 | OK | OK | OK | OK |
| 后响 | 339 | OK | OK | OK | OK |
| 前鼻基础 | 469 | OK | OK | OK | OK |
| 前鼻扩展 | 528 | OK | OK | OK | OK |
| 后鼻基础 | 747 | OK | OK | OK | OK |
| 后鼻扩展 | 151 | OK | OK | **缺73，需间隔重复** | **缺149，需间隔重复** |

结论：大多数 Profile 的 20 分钟核心配额真实可满足；只有平舌 20m 与后鼻扩展 15/20m 需要间隔重复补位，其余无压力。

## 3. v2 实现顺序

1. 扩展 v2 Profile schema（`mode / target_sets / buckets / pair_rules / allow_other / scarcity_policy / repeat_policy`）。
2. 实现 signature builder（单/双/三音节 → bucket + matched patterns + credited pattern）。
3. 实现 pair matrix 生成器（理论组合与真实候选分开存）。
4. 先跑 Availability Matrix，输出 `PROFILE_AVAILABILITY_REPORT_V2.md`，不改生成器。
5. 实现 quota-aware selector（桶配额 → pattern 缺口 → 加权 Top-K → 顺序约束 → 时间预算）。
6. 实现 scarcity fallback（间隔重复 + 补充比例提升 + `core_pool_insufficient` 标记）。
7. 接回 v1 的位置/词长/调型/去重约束与时间预算。
8. 输出 v2 Session JSON（`bucket_id / credited_pattern / all_matched_patterns` 等）与 `GENERATOR_REPORT_V2.md`。
9. 按文档 §29 首批试跑矩阵。

## 4. 首批试跑矩阵（沿用 v2.0 §29）

- 声母：双唇音、平舌、翘舌、平翘舌、n/l、j/q/x（各 10 分钟 × 3 seed）
- 韵母：单韵母、前响、前鼻专项一、后鼻专项一、前后鼻对比一、前后鼻对比二（各 10 分钟 × 3 seed）
- 声调：tone_1、tone_3、四声综合（各 10 分钟 × 3 seed）
- 另补 5 分钟和 20 分钟案例，验证配额跨时长稳定。
