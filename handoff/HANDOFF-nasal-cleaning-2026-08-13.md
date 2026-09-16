# 交接：前后鼻音专项错漏清洗（给新对话）

> ✅ **本交接已于 2026-08-14 完成闭环**：人耳听检 1,346 条 / 排除 20 条（累计 919）/ 终验收盲抽两轮达标（0.5%）。
> 完整过程、残余风险与复现命令见 `handoff/MEMORY-2026-08-14-nasal-cleaning.md`；进度总览见 `handoff/STATUS-2026-08-13.md`。
> 本文件保留为过程底稿，供追溯机器侧盘点口径。

生成时间：2026-08-13（Asia/Shanghai）
交接对象：负责「前后鼻音词库再清洗」的新对话
前置背景：本对话已完成 P0+P1 原型、音筛选功能、以及本文件所依赖的**机器侧盘点**。

## 0. 一句话任务

用户实测发现前后鼻音训练里存在「音频读的是别的词」的错漏（历史六轮清洗后仍残存）。请以本文件提供的机器盘点为输入，**对前后鼻音相关的语料条目做一轮专项清洗**：人工听检 + 确认排除（或修复切分），目标是让前鼻音 / 后鼻音 / 前后对比三个训练入口的内容尽量干净。

## 1. 盘子与嫌疑规模（已由机器盘点得出）

- 正式语料 16,156 条中，前后鼻音相关 **9,700 条**（仅前鼻 4,546 / 仅后鼻 3,926 / 前后均有 1,228）。
- 嫌疑集 **2,384 条** = 旧 Qwen3 ASR 低分（score<0.5，2,219 条鼻音相关）∪ Qwen3 错配清单（62 条鼻音相关）。
- 本轮机器盘点用 **faster-whisper base（CPU int8）** 对这 2,384 条全部重新听写，产物已生成在：
  `data/derived/nasal-audit-2026-08-13/`（听写结果保留在 `nasal_asr_results.jsonl`，可直接复用）。

## 2. 机器盘点产物（`data/derived/nasal-audit-2026-08-13/`）

| 文件 | 内容 |
|---|---|
| `NASAL_AUDIT_REPORT.md` | 口径、分级定义、统计、建议流程 |
| `nasal_universe.csv` | 全部 9,700 条前后鼻音条目（含韵母、是否嫌疑） |
| `nasal_suspects_ranked.csv` | 2,384 条嫌疑全表：whisper 文本、旧 Qwen3 文本、`both_asr_agree`（双 ASR 完全一致读成别的文本）、`whisper_text_freq`（同文本出现次数，高频=模型幻觉/短切片噪声）、`clip_duration_ms`、`segment_confidence`、前后邻词、clip_path、级别、理由 |
| `review_batch_*.csv` | 人工听检批次（每批 ≤200，按级别 T1→T4 排序，共 7 批 / 1,216 条可听检） |
| `nasal_audit_stats.json` | 统计快照 |

分级口径（详见报告）：

- `T1_strong`（412 条）：**双 ASR 一致读成别的文本**（372 条）或 Qwen3 错配清单 + 新 whisper 不一致——本轮最强信号，从这批开始听。
- `T2_mismatch`（563 条）：新 whisper 与本词不一致（多音节，疑似音频读错词）。
- `T2_repeat`（153 条）：whisper 高频重复文本（认识×23、噴噴×18、中文字幕×16 等）——多数是短切片/低置信切分问题，看 `clip_duration_ms`/`segment_confidence` 列，优先查切分质量而非当读错词。
- `T3_shift`（13 条）：新 whisper 更像相邻词（疑似切分串位，优先重切而非排除）。
- `T4_homophone`（75 条）：whisper 近音/同音（以人耳为准，多数是听写差异）。
- `T5_*`（586+519 条）：单音节或 ASR 无输出（机器不可靠，量力抽查）。
- `OK`（63 条）：whisper 与本词一致，疑似误报，不必听。

⚠️ whisper 对单音节/近音不可靠；「双 ASR 一致」里仍混有少量两模型共同听错的样本：**所有级别都只是排序线索，最终判定一律人耳**。

## 3. 本地重听能力（本机已有）

- `/opt/miniconda3/bin/python` 装有 `faster_whisper`（CPU int8，每条约 0.5–1.5s）。
- 批量转写脚本：`tools/whisper_batch.py`（分片并行用法见文件头注释）。
- 生成嫌疑清单的方法：`src/pth_corpus/nasal_audit.py` 里 `build_report` 的嫌疑判定逻辑（旧 Qwen3 低分 ∪ Qwen3 错配清单 ∩ 前后鼻音盘子）。

## 4. 复现盘点命令（机器侧，只读）

```bash
# 如需重跑 ASR（已有结果在 data/derived/nasal-audit-2026-08-13/nasal_asr_results.jsonl）：
#   /opt/miniconda3/bin/python tools/whisper_batch.py --input /tmp/nasal_suspects.txt --out /tmp/nasal_asr.jsonl
# 生成报告（读写数据目录，不碰母库/音频）：
.venv/bin/python -m pth_corpus.nasal_audit \
  --data-root data \
  --asr data/derived/nasal-audit-2026-08-13/nasal_asr_results.jsonl \
  --out derived/nasal-audit-2026-08-13
```

## 5. 排除/修复的落点（历史口径）

- 排除判定记录在两张表：`data/corpus.sqlite3` 的 `excluded_items` 表（migration 002）与
  `data/derived/phonology-v1/phonology.sqlite3` 的 `excluded_items` 表（`phonology` 命令重建该库时
  会读取排除信息；训练生成器经 `item_features_available` 视图自动过滤被排除条目）。
- 恢复清单：`data/derived/excluded_items.csv`（可恢复性要求）。
- 历史分类口径（六轮清洗共排除 899 条）：音频串位 380、音频声调错 193、拼音语境错 161、
  音频词错 69、低置信声调 46、拼音非法 35、标准拼音错 13、其他 2。
- 切片移动：被排除条目的 WAV 移至 `data/derived/clips-excluded/`（历史做法，保留原始音频）。
- 串位类（T3）优先尝试 `review --apply-adjustments` 重切边界，而不是直接排除。
- ⚠️ 建议在新对话里先写一个幂等的「排除命令」（CLI 或脚本），把 写表 + 移文件 + 更新 CSV 原子化，
  并补测试；不要手工逐条改数据库。

## 6. 清洗后的验证

- 全量测试：`.venv/bin/python -m pytest`（当前 151 项）。
- 重新生成 Session 抽检三个入口（前鼻/后鼻/对比），确认排除条目不再出现：
  `curl -s -X POST http://127.0.0.1:8766/api/sessions -H 'Content-Type: application/json' -d '{"profile_id":"front_nasal_all","duration_minutes":5}'`
- 重跑 `python -m pth_corpus training availability-v2 --data-root data --out derived/training-generator-v2`
  确认三个入口 Profile 的候选池仍然充足（前端音筛选只选单音时也要够）。

## 7. 与「音筛选」功能的联动

- 原型新增音筛选（本对话完成）：`/api/sessions` 接受 `include_finals`（白名单，只按目标音过滤，
  不重写 Profile）。清洗排除的条目会从候选池消失，天然生效。
- 若某音的候选在清洗后过少（如仅剩几十条），单音筛选 + 10 分钟会话可能出现重复率高/时长不足，
  生成器已有降级逻辑，可在验证时关注。

## 8. 相关文件索引

- 盘点代码：`src/pth_corpus/nasal_audit.py`、`tools/whisper_batch.py`
- 历史清洗产物：`data/derived/{audio_audit_candidates,qwen3_word_mismatch_candidates,qwen3_chain_excluded,qwen3_full_align_excluded,cedict_check,source_quality_report_full,excluded_items}.csv/.json`
- 历史清洗记录：`handoff/MEMORY-2026-08-08.md`（六轮机器清洗 + 四批人工验收详情）
- 数据调用手册：`handoff/DATA_GUIDE.md`
