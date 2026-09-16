# 模块：语料管线（corpus pipeline）

> 给 AI 的 3 行摘要：pthxx.com 表一/表二页面 → 抓取 → 解析 → 音频切片 → 机器 QA → 人工复核 →
> 语音特征打标。全量 16,156 条已收口，919 条异常已排除，产物在 `data/derived/`。

## 职责

从来源页面把词语表与试听音频变成可用的正式语料库：条目、WAV 切片、语音特征打标，
以及逐页/全量机器 QA 门与人工复核流水线。**来源与版权边界**见 `../README.md` 与 `handoff/SOURCE.md`。

## 现状（2026-08-23）

- 全量语料完成：16,156 条正式条目、六轮机器清洗、四批人工验收。
- 异常隔离：`excluded_items` 表 919 条（可恢复清单 `data/derived/excluded_items.csv`），
  切片移入 `derived/clips-excluded/`；正式视图自动过滤。
- 语音打标 v1：16,149 条可用（`derived/phonology-v1/`：CSV + `phonology.sqlite3` + 复核队列）。
- 前后鼻音专项错漏清洗闭环（2026-08-14）：人耳听检 1,346 条、排除 20 条、终验收 0.5% 达标。

## 关键文件

| 内容 | 位置 |
|---|---|
| CLI 主入口 | `python -m pth_corpus`（discover/fetch/parse/segment/qa/sourcecheck/review/phonology/nasal-clean） |
| 清洗工具 | `tools/verify_nasal_clean.py`、`tools/nasal_acceptance_sample.py`、`tools/whisper_batch.py` |
| 判定事实来源 | `data/review/nasal_decisions_*.csv` |
| 数据库 | `data/corpus.sqlite3`（entries/segments/excluded_items…） |

## 数据

- 切片：`data/derived/clips-v2/`；异常切片 `data/derived/clips-excluded/`。
- 报告：`data/derived/{full_qa_report,source_quality_report,segmentation_report}.json` 等。
- 语料分页特殊点：每表第一页音频带标题报幕；各页尾部共享约 7.15s 广告（切分自动排除）。

## 待办

- 无阻塞项。若来源新增词，全量流程重跑顺序见 README「全量流程」段。
- 相关里程碑：`handoff/MEMORY-2026-08-08*.md`、`MEMORY-2026-08-14-nasal-cleaning.md`、`HANDOFF-nasal-cleaning-2026-08-13.md`。
