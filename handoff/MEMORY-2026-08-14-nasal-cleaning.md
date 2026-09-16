# 普通话语音语料库 · 阶段性节点记录（Memory）

记录时间：2026-08-14（Asia/Shanghai）
状态：**阶段完成** —— 前后鼻音专项错漏清洗闭环（人耳听检 1,346 条 / 排除 20 条 / 终验收达标 0.5%）。

前置：`handoff/HANDOFF-nasal-cleaning-2026-08-13.md`（机器侧盘点 9,700 条盘子 / 2,384 条嫌疑）。

---

## 一、口径修正（阶段 A）

- 复跑 `nasal_audit` 与既有产物**逐字节一致**（9700 盘子 / 2384 嫌疑 / 分级一致），机器盘点可复现。
- 每级抽 10 条核对列与理由自洽，发现 **1 个分类器 bug**：`classify()` 把 `sim_word >= 0.5` 的「近匹配」
  归入 OK 级（如 成人→行人、处分→充分、精光→金光 共 38 条），而报告口径为「whisper 与本词一致、
  疑似误报」——正是用户要抓的「读错词」类被漏掉。修复后：OK 只收完全一致（63→25），近匹配按
  双 ASR 一致→T1_strong（+6），否则→T2_mismatch（+32）；分级变为 T1 418 / T2_mismatch 595 /
  可听检 1,254。新增 4 项测试（tests/test_nasal_audit.py）。

## 二、工具（阶段 B/D，新增代码）

| 模块 | 说明 |
|---|---|
| `src/pth_corpus/nasal_review.py` | 本地听检页（端口 8767，仅 loopback）：词/拼音/tier/reason/whisper/旧 Qwen3/前后邻词/时长/置信度；自动连播；键盘 A=正确 S=读错词 D=串位 F=声调错 Q=音质差 X=待定；串位可附重切边界（限制在原始窗内）；断点续判；判定幂等落 `data/review/nasal_decisions_*.csv`（唯一事实来源）；Backspace 撤销。 |
| `src/pth_corpus/nasal_clean.py` | `python -m pth_corpus nasal-clean --apply <csv> [--dry-run]` / `--undo <csv>` / `--undo-item <id>`：wrong_word→`audio_word_mismatch`、tone→`audio_tone_mismatch`、quality→`audio_quality`、shift（无边界）→`audio_shift`、shift（带边界）→**从源音频重切**（保留条目，更新 segments 边界/hash/algorithm_version=`constrained-dp-v2+nasal-recut-v1`，原切片备份到 `derived/nasal-cleaning/recut-backup/`，事件记 `nasal_repair_report.json`）；排除=写 corpus.sqlite3 `excluded_items` + 移 WAV 到 clips-excluded + 更新 segments.clip_path + 追加 `derived/excluded_items.csv` 恢复清单 + 重生成 `formal_corpus.csv`；全程先校验（文件存在、SHA-256 与库一致、边界包含）→ 文件先行 + DB 单事务 + 派生文件原子替换，异常全回滚；重复应用幂等 no-op，部分状态（有排除行但文件没移）拒绝执行。 |
| `tools/verify_nasal_clean.py` | 清洗后验证：三入口 Profile（front_nasal_all/back_nasal_all/front_back_nasal_contrast）×3 seed + 单音 include_finals 场景生成 Session，断言排除条目 0 混入、候选池 ≥200。 |
| `tools/nasal_acceptance_sample.py` | 终验收抽样：从清洗后鼻音盘子随机抽 200 条生成可听检 CSV（固定 seed 可复现）。 |
| `phonology.py` | 硬编码「formal_corpus 必须 16156 条」改为从 corpus.sqlite3 数据驱动推导（entries−excluded，无母库时回退历史常数）；数据基线标签随条数动态（formal_corpus_n16136）。 |
| `qa.py` | full QA 门允许 `constrained-dp-v2+nasal-recut-v1`（人审重切属机器可验证状态，hash 照查）。 |

测试：新增 `tests/test_nasal_review.py`（8 项）+ `tests/test_nasal_clean.py`（11 项，含撤销/幂等/hash 漂移/部分状态拒绝/重切回滚），全量 **184 项全绿**。

## 三、听检结果（阶段 C，人耳判定 1,346 条）

| 批次 | 范围 | 判定 | 问题 | 命中率 |
|---|---|---:|---:|---:|
| batch_01 | T1_strong 204（含补充 4） | 200 ok | 2 tone + 2 shift（太阳/喷嚏/同时/同学） | 2.0% |
| batch_02 | T1_strong 200 | 195 ok | 3 tone + 2 shift（估量/瞧见/轻巧/毕生/共振） | 2.5% |
| probe | T1 遗留 14 + T2_mismatch 测水 100 | 112 ok | 1 shift（被单，T1） | T1 1/14；**T2 0/100** |
| rt4a | T2_repeat 153 + T3 13 + T4 33 + 程度 1 | 199 ok | 1 shift（钻研，repeat 层） | 0.5% |
| rt4b | T4_homophone 42 | 42 ok | 0 | 0% |
| t5 测水 | T5_single/Unverifiable 200 | 194 ok | 4 shift + 1 wrong_word + 1 tone（防御/绷带/厄运/午餐/圈/挣） | 3.0% |
| 终验收① | 清洗后盘子盲抽 200 | 198 ok | 1 tone + 1 shift（重/笨重） | 1.0% |
| 终验收② | 再抽 200（seed 20260815） | 199 ok | 1 tone（精灵） | **0.5% ✅** |

**T1 实锤率只有 ~2.2%**：whisper base 双 ASR 一致仍大量共听错，机器信号仅排序线索，人耳是唯一判决——与「准确优先」预期一致。
滚动决策：T2_mismatch 测水 0%（<5%）→ 剩余暂缓；T5 测水 3.0%（<5%）→ 剩余暂缓；
两类判定文件与机器证据均在 `data/review/nasal_decisions_*.csv` / `nasal_suspects_ranked.csv`，随时可回来补听。

## 四、排除明细（本轮共 20 条，累计 899→919）

| 分类 | 条数 | 条目 |
|---|---:|---|
| audio_shift 串位 | 11 | 同时 同学 毕生 共振 被单 钻研 防御 绷带 厄运 午餐 笨重（用户三度确认串位类直接排除口径；重切通道已就绪但未被采用） |
| audio_tone_mismatch 声调错 | 8 | 太阳 喷嚏 估量 瞧见 轻巧 挣 重 精灵 |
| audio_word_mismatch 读错词 | 1 | 圈（t1-02630） |

其中两条根因是**源站拼音错**（已在恢复清单 detail 注明）：`重` 源拼音 `zhóng` 非法（标准 zhòng/chóng）；`精灵` 源拼音 `jīngling` 缺声调符号（标准 jīnglíng）。

- 所有排除可撤销：`nasal-clean --undo data/review/nasal_decisions_<batch>.csv`（恢复 excluded_items 行、移回 WAV、回写 formal_corpus/excluded_items.csv）。
- WAV 全部移 `data/derived/clips-excluded/`（899+20=919 个），segments.clip_path 同步更新。

## 五、验证（阶段 D/E）

- 全量 pytest **184 项全绿**（每次应用后跑）。
- `qa --scope full` → **passed，0 异常**（17055 entries/segments，919 excluded，clip hash 全一致）。
- phonology 重建 → PASSED，16136 输入 / 16129 可用（7 条历史解析异常不变）。
- `tools/verify_nasal_clean.py` → passed：三入口 9 个 Session + 单音筛选 Session **排除条目 0 混入**；候选池 front 5773 / back 5151 / contrast 9696（充足）。
- 终验收两轮盲抽 400 条：第一轮 1.0% 暴露 2 条 → 补排后第二轮 **0.5% 达标**。

## 六、残余风险（知情备忘）

1. 嫌疑集仍有 **1,352 条暂缓未人耳**（截至 2026-08-14 收盘，用户确认暂缓、保留记录）：T2_mismatch 477、T5_single 462、T5_unverifiable 413（测水命中率 <5% 按滚动规则暂缓）。未判清单已固化在 `data/derived/nasal-audit-2026-08-13/resume_undecided.csv`（1352 行），补听入口见「七、复现命令」，听检页会自动跳过已判条目，**不会重复**。OK 级 23 条机器文本与本词完全一致，按口径不必听。
2. 前后鼻音盘子 9,680 条中另有 **7,314 条非嫌疑条目从未入机器嫌疑、也从未人耳**（与历史四批验收口径一致：抽样验收而非全听）。
3. 本窗口模型不支持音频输入，未做 AI 预判列；全部判定为纯人耳（更强，只是慢）。
4. whisper 对单音节/近音不可靠、双 ASR 一致亦有共错——未来若再清，T1 类机器证据的实锤率预期仅 ~2%。
5. 串位类本次全部走排除；重切通道（shift+边界 → 源音频重切）已实现并有测试，但未被实际使用，真实数据上未验证过重切效果。

## 七、复现命令

```bash
# 机器盘点（只读，产物已与交接一致）：
python -m pth_corpus.nasal_audit --data-root data \
  --asr data/derived/nasal-audit-2026-08-13/nasal_asr_results.jsonl \
  --out derived/nasal-audit-2026-08-13
# 听检页（任意批次或自定义 CSV）：
python -m pth_corpus nasal-review --data-root data --batch 01 --port 8767
python -m pth_corpus nasal-review --data-root data --batch-csv data/derived/nasal-audit-2026-08-13/t5_sample_200.csv --port 8767
# 落地/撤销：
python -m pth_corpus nasal-clean --apply data/review/nasal_decisions_batch_01.csv --dry-run
python -m pth_corpus nasal-clean --apply data/review/nasal_decisions_batch_01.csv
python -m pth_corpus nasal-clean --undo-item t1-04566
# 补听暂缓条目（不重复：听检页自动跳过已判条目，判定并入 nasal_decisions_*.csv）：
python -m pth_corpus nasal-review --data-root data \
  --batch-csv data/derived/nasal-audit-2026-08-13/resume_undecided.csv --port 8767
# （若清洗后又排除了条目，先重跑 nasal_audit，再用 tools/nasal_resume_undecided.py 重生成未判清单）
# 清洗后重建 + 验证：
python -m pth_corpus phonology --data-root data
python tools/verify_nasal_clean.py --data-root data
python -m pth_corpus qa --scope full
```

## 八、关键文件

- 判定事实来源：`data/review/nasal_decisions_*.csv`（8 个批次/轮次）
- 暂缓未判清单（补听入口）：`data/derived/nasal-audit-2026-08-13/resume_undecided.csv`（1,352 行）
- 恢复清单：`data/derived/excluded_items.csv`（919 行明细）
- 重切备份/报告：`data/derived/nasal-cleaning/`（本轮无重切实例）
- 验证报告：`data/derived/nasal-cleaning/verify_nasal_clean.json`
- 终验收抽样：`data/review/nasal_acceptance_200.csv`、`nasal_acceptance_200b.csv`
- 新增代码：`src/pth_corpus/{nasal_review,nasal_clean}.py`、`tools/{verify_nasal_clean,nasal_acceptance_sample,nasal_resume_undecided}.py`
