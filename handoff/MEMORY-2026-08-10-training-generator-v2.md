# 普通话语音系统 · Training Session Generator v2 节点记录（Memory）

记录时间：2026-08-10（Asia/Shanghai）
状态：**阶段完成** —— v2 结构优先生成器 + Availability Matrix + 首批 65 个真实 Session + 自动 QA 报告全部产出。

---

## 一、目标

- 按《普通话训练 Session 组合规则 v2.0 核心补充对比版》把“命中目标后平衡随机”升级为“先定义训练结构，再平衡随机”。
- 每个 Profile 先定义核心/补充/对比桶与配额，再在真实语料内平衡随机；真实语料不足时动态补位，不制造不存在的组合。

## 二、用户确认的口径（v2.1）

1. Profile 允许重叠：`zh/ch/sh/r` 同时属于“纯翘舌组”和“平翘舌对比组”，互不影响；r 归翘舌。
2. 三字词“有多少用多少”：全库三字全核心极少，词长比例只做软目标。
3. 长时长稀缺自动降级：核心桶用足 → pattern 平衡 → 间隔重复（max 2 次、gap ≥20）→ 补充比例提升（仅 allow_other）→ `core_pool_insufficient` 标记。
4. 不可用组合跳过或相关补位：`uen↔ueng` 真实候选 0，默认不启用。

## 三、实现

- 代码：`src/pth_corpus/training/v2/`（`schema.py` 规则 DSL、`engine.py` signature/bucket/组合矩阵、`generator.py` 配额选择器 + 稀缺补位、`report.py`）。
- CLI：`python -m pth_corpus training {availability-v2|generate-v2|benchmark-v2}`。
- v2 规则 DSL：`all_in / any_in / groups_present / adjacent_window / all / any / not`；组合由 `pair_specs` 自动笛卡尔积，不手写几百种。
- 配额选择器：桶配额债务 → 桶内 pattern 缺口 → 加权 Top-K → 顺序约束（可放宽）→ 时间预算；新词用完才允许间隔重复。

## 四、Availability Matrix 要点（29 个 Profile）

输出：`PROFILE_AVAILABILITY_REPORT_V2.md`、`profile_availability_v2.json`。

- 全部 Profile 10 分钟核心配额 OK。
- 20 分钟需要间隔重复补位：平舌（核心池 264）、f/h（167）、n/l（332）、后鼻扩展（151）、前后鼻对比一（cross 桶受限）。
- 缺失/稀缺组合已逐个标注（如单韵母 7 个缺失、后鼻扩展 8 个缺失；`uen↔ueng` 为 0）。

## 五、首批 benchmark（65 个 Session）

矩阵：15 个 Profile × 10 分钟 × 3 seed；4 个时长样例 Profile ×（5 分钟 ×3 + 20 分钟 ×2）。

QA：Profile 候选错误 0、bucket 分类错误 0、重复策略违规 0、相同 seed 不可复现 0、生成失败 0、最大时长相对误差 ≤1%。

配额达成（均值）：

| Profile | 桶占比 |
|---|---|
| 双唇/平舌/翘舌/n/l/单韵母/复韵母/前后鼻专项 | core ≈ 80.0% / supplement ≈ 20.0% |
| 平翘舌对比（含 r） | cross 60.0% / same 40.0% |
| 前后鼻对比一/二 | cross 65.0% / same 35.0% |
| j/q/x | jqx_core 69.8% / flat_relation 20.1% / jqx_other 10.1% |
| 四声综合 | all 100% |

## 六、已知限制与下一步

1. 对比型 Profile 核心桶内同质（双字多位置、调型集中），tone_pattern/length/position 次约束放宽次数偏多（每 Session 几十次），属自动放宽，不影响正确性；后续可调权重或约束。
2. 20 分钟纯专项在候选不足时会出现间隔重复（如平舌、后鼻扩展、前后鼻对比一），报告中已标记。
3. tone_33、轻声、儿化未进首批矩阵（tone_33 已配置，候选 403）。
4. 下一步：按需调 Profile 配额/权重；补 tone_33 等 Profile 试跑；接 UI 前先做真实试听。

## 七、复现命令

```bash
python -m pth_corpus training availability-v2 --data-root data --out derived/training-generator-v2
python -m pth_corpus training generate-v2 --profile flat_retroflex_contrast --duration 10 --seed 20260804 --data-root data --out derived/training-generator-v2
python -m pth_corpus training benchmark-v2 --data-root data --out derived/training-generator-v2
python -m pytest tests/test_training_v2.py
```

产物目录：`data/derived/training-generator-v2/`（配置、Availability 报告、sessions、stats、GENERATOR_REPORT_V2.md）。

## 八、2026-08-10 增补：默认随机 seed + 跨 Session 历史软避让

### 需求

- 用户使用（未来终端 APP/应用）默认随机生成，每次 Session 不同；调试时传固定 `--seed` 复现。
- 跨 Session 减少重复词相撞：按 Profile 记录最近使用历史，软避让（降权），不硬排除；候选不足时正常补位。
- 记忆窗口：7 天 / 最近 7 次 Session（配置项：`history_window_days`、`history_window_sessions`、`history_penalty=0.6`）。

### 实现

- `generate_session_v2` 的 `seed` 改为可选：不传时用当前时间自动生成随机 seed。
- 新增 `src/pth_corpus/training/v2/history.py`：按 Profile 记录 `{item_id, session_no, used_at}`，窗口内条目视为“近期”。
- 评分时近期 item 扣 `history_penalty` 并写 reason；Session summary 输出 `history.recent_items_known / recent_items_selected`。
- CLI `generate-v2` 每次生成后自动追加并保存历史。

### 实测

连续两次不传 seed 生成平翘对比 10 分钟 Session：seed 不同（892389344 / 805835696）；第二次知道 194 个近期词，实际选中 0 个，两个 Session 的 item 重叠 = 0（此前无历史时约 2%–3%）。

### 说明

- 硬排除不做：小词池（n/l、后鼻扩展）长期使用可能凑不满，软避让 + 补位更稳。
- 7 天 / 7 次窗口可随时在 `generator_config_v2.json` 调整。
