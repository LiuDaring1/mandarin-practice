# 普通话语音系统 · 平衡随机训练生成器 v1 节点记录（Memory）

记录时间：2026-08-08（Asia/Shanghai）
状态：**阶段完成** —— 候选池统计 + 通用生成器 + 首轮 66 个真实 Session + 自动 QA 报告全部产出。

---

## 一、目标与边界

- 依据《普通话平衡随机训练生成器_Training_Session_Generator_v1.0.md》实现第一版生成器。
- 只读复用 phonology-v1 成果（`data/derived/phonology-v1/phonology.sqlite3`，16,149 条可用 item），**未重做语音打标**。
- 母库 `data/corpus.sqlite3` 只读（仅 JOIN `segments` 取 `clip_path` / `start_ms` / `end_ms`）。
- 本阶段不做 UI、用户画像、语音评测、课程体系、难度等级。

## 二、实现

- 代码：`src/pth_corpus/training/`（`models.py`、`candidates.py`、`scoring.py`、`constraints.py`、`timing.py`、`generator.py`、`report.py`）。
- CLI：`python -m pth_corpus training {generate|candidate-stats|benchmark}`。
- 核心流程：Candidate Filter → Coverage State → Dynamic Weighting → Top-K（默认 50）→ 加权随机 → 顺序硬约束（可自动放宽）→ 时间预算 → Session JSON。
- Profile 与生成器分离：`training_profiles_v1.json` 定义候选规则、平衡维度、组目标占比、位置维度；新增训练目标只改 JSON。
- 关键设计决策：
  1. 组目标占比（如平翘 45/55、n/l 50/50、前后鼻 50/50）来自 Profile 配置；组内子项仍按候选池自然比例分配（`group_target × 组内占比`）。
  2. “同一具体目标音连续 ≤2”只对 initials/finals 维度生效；tone/structure/flags 等覆盖维度不做连击约束。
  3. 位置分布加入“偏多惩罚”，避免多位置词被系统性高选。
  4. 顺序约束放宽优先级：tone_pattern → length → position → target，只在实际放宽时记录。
  5. 同 seed 完全可复现（Session JSON 不含时间戳，纯函数生成）。

## 三、候选池统计（真实数据）

输出：`CANDIDATE_POOL_REPORT_V1.md`、`candidate_pool_stats_v1.json`。

| Profile | 候选数 | 说明 |
|---|---:|---|
| 平翘舌 initial_flat_retroflex | 6,261 | flat 1,934 / retroflex 4,684 |
| n/l initial_n_l | 2,121 | n 475 / l 1,674 |
| 前鼻音 final_front_nasal | 5,774 | an/ian 为主 |
| 后鼻音 final_back_nasal | 5,154 | ing/ong/eng 为主 |
| 前后鼻音对比 final_front_back_nasal | 9,700 | front 5,774 / back 5,154 |
| 综合练习 general | 16,149 | 全量 |
| 复韵母 final_compound | 7,070 | 前/中/后响 3264/2531/2375（音节级） |
| 阴平 tone_1 / 阳平 tone_2 / 上声 tone_third_tone / 去声 tone_4 | 5,935 / 6,156 / 4,648 / 8,761 | — |
| 3-3 tone_33 / 轻声 tone_neutral / 儿化 final_erhua | 403 / 476 / 39 | 小候选池 |

全库词长：1 音节 2,931 / 2 音节 12,796 / 3 音节 317 / 4 音节 105。
平均切片约 1.03s；单题预计时长（1 遍）约 3.2–3.4s。

## 四、首轮 benchmark（66 个 Session）

矩阵：
- 6 个主 Profile（平翘舌、n/l、前鼻音、后鼻音、前后鼻音对比、综合练习）：5 分钟 × 3 seed、10 分钟 × 3 seed、20 分钟 × 2 seed。
- 6 个追加 Profile（复韵母、四声、阴平、阳平、上声、去声）：10 分钟 × 3 seed。

QA 汇总（`generator_stats_v1.json` / `GENERATOR_REPORT_V1.md`）：

| 指标 | 结果 |
|---|---|
| Session 数 | 66 |
| Profile 候选错误 | 0 |
| 候选不匹配 | 0 |
| 同 Session 重复 item | 0 |
| 相同 seed 不可复现 | 0 |
| 生成失败 | 0 |
| 最大时长相对误差 | ≤ 1.0%（要求 ≤ 5%） |
| 放宽次数 | 仅 length 122 次、tone_pattern 172 次 |

分布效果：
- 平翘舌：flat 均值 49.4%（目标 45%），retroflex 59.1%（目标 55%）。
- n/l：n 52.0%、l 52.6%（目标各 50%）。
- 前后鼻：front 58.1%、back 57.5%（目标各 50%；因多位置词同时计入两组，均值略高于 50% 属正常）。
- 位置分布：多位置占比已从纯池化时的 31–44% 压到 12–35%，位置 1 / 2 为主。
- 不同 seed 重叠：一般 ≤ 6%（n/l 20 分钟因 n 候选仅 475 条，item 重叠 22.9%）；序列位置重叠基本为 0。

## 五、已知限制与下一步

1. “多位置”占比仍高于候选池自然比例（混合目标词被组平衡略微偏爱），下一轮可调 `weight_position` / `weight_purity`。
2. n/l 20 分钟长 Session 重叠率偏高（n 候选池小），属数据限制；可接受，或后续补充 n 声母语料。
3. 时长参数（`extra_follow_sec=0.8`、`min_follow_sec=1.8`、`transition_sec=0.3`）为文档实验值，等有播放器后按真实试听调整。
4. 3-3、轻声、儿化 Profile 已配置但未进首轮矩阵；儿化候选仅 39 条，连续约束会自动放宽。
5. 下一步建议：试听 2–3 个 10 分钟 Session 校准节奏；按需要新增 j/q/x、单韵母、f/h 等 Profile（只改 JSON）。

## 六、复现命令

```bash
python -m pth_corpus training candidate-stats --data-root data --out derived/training-generator-v1
python -m pth_corpus training generate --profile initial_flat_retroflex --duration 10 --seed 20260804 --data-root data --out derived/training-generator-v1
python -m pth_corpus training benchmark --data-root data --out derived/training-generator-v1
python -m pytest tests/test_training.py tests/test_cli.py
```

产物目录：`data/derived/training-generator-v1/`（配置、候选池统计、`sessions/<profile>/`、`generator_stats_v1.json`、`GENERATOR_REPORT_V1.md`）。

## 七、2026-08-10 增补：专项纯度聚焦（v1.1 配置）

### 需求

用户反馈：平翘舌等专项练习里单目标词（如“试用 shìyònɡ”只有 sh）密度不够。期望：

- 双字词尽量两个音节都在目标范围内（平+翘、翘+平、平+平、翘+翘）；
- 三字词尽量整词都在目标范围内（如“出租车”）；
- 单字词只要含目标音即可；
- 单目标词少量掺杂，保持练习聚焦。

### 实现

- `TrainingProfile` 新增 `purity_weight` 与 `purity_target_shares`（配置化，不写死在代码里）。
- 有 `purity_target_shares` 时，按“全目标 full / 部分目标 partial”做桶平衡（目标占比 + 偏多惩罚）；无该配置时保留原来的轻量连续纯度权重。
- `full` 定义：目标音出现数 ≥ 音节数（即每个音节都含目标音）。
- 配置：
  - 平翘舌 / n/l：full 70%、partial 30%（权重 2.0 / 1.2）；
  - 前鼻音 / 后鼻音 / 前后鼻对比 / 复韵母：full 60%、partial 40%（权重 0.9）。

### 效果（66 个 Session 全量重跑后）

| Profile | 全目标词占比 | 部分目标词占比 |
|---|---:|---:|
| 平翘舌 | 65.8% | 34.2% |
| n/l | 61.4% | 38.6% |
| 前后鼻音对比 | 56.6% | 43.4% |
| 前鼻音 | 53.7% | 46.3% |
| 后鼻音 | 53.5% | 46.5% |
| 复韵母综合 | 54.5% | 45.5% |

候选池天然比例只有 16%–36% 全目标词，重跑后各专项全目标词占比明显提升；QA 仍为 0 错误、最大时长误差 ≤1%。实际比例略低于目标值，是因为位置平衡会拉回一部分单目标词（全目标词多为“多位置”词），属正常折中；如需更密可提高 `purity_weight` 或调整 `purity_target_shares`。
