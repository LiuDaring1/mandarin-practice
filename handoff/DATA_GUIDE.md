# 普通话语音语料 · 数据使用指南（给工具开发者的调用手册）

> 适用：任何新的 Codex 会话 / 开发者在做“基于语料的应用”时，先读这份指南即可知道数据在哪、怎么取、怎么用。
> 数据版本：2026-08-08 终版（正式 16,156 条）。完整过程记录见同目录 `MEMORY-2026-08-08.md`。

---

## 1. 数据总览

| 项目 | 数量 |
|---|---:|
| 源详情页（表一 66 + 表二 105） | 171 |
| 源 MP3（每页一个） | 171（约 249MB） |
| 解析出的全部词条 | 17,055 |
| 机器清洗 + 人工验收排除 | 899 |
| **正式可用词条** | **16,156** |

每一条 = 一个字词 + 拼音 + 一个独立 WAV 切片（16kHz 单声道 16-bit，已去报幕/广告/静音头尾）。

## 2. 目录结构

项目根：`/Users/baiyanglin/Desktop/普通话语音系统`

```
data/
├── corpus.sqlite3                  # 主数据库（唯一数据源）
├── raw/
│   ├── html/detail/{table1,table2}/ # 171 个源详情页（{页号:03d}.html）
│   └── audio/{table1,table2}/       # 171 个源 MP3（{页号:03d}.mp3）
└── derived/
    ├── clips-v2/{table1,table2}/    # 正式切片 16,156 个 WAV
    ├── clips-excluded/{table1,table2}/  # 被排除切片 899 个（可恢复，勿删）
    ├── formal_corpus.csv            # ★ 正式清单（工具优先读这个）
    ├── full_entries.jsonl           # 全量 17,055 条文本（含已排除）
    ├── full_segments.jsonl          # 全量切片元数据
    ├── full_qa_report.json          # 全量 QA 报告（passed）
    ├── full_segmentation_report.json
    ├── full_audio_manifest.json
    ├── analysis/full_analysis.json  # 广告尾模板等分析产物
    ├── excluded_items.csv           # 899 条排除清单（含原路径）
    └── source_quality_report_full.json  # 源站质量筛查报告
```

## 3. 正式清单 `formal_corpus.csv`

列：`item_id, table_kind, word_raw, pinyin_nfc, global_seq, clip_path, clip_sha256, confidence`

- `item_id`：`t1-00001` … `t2-10460`（t1=表一，t2=表二；序号即全局序）。
- `clip_path`：相对 `data/` 的 WAV 路径，直接 `data/ + clip_path` 打开。
- `clip_sha256`：切片内容哈希，做校验/缓存键用。
- `confidence`：自动切分置信度（0-1），低置信不代表错误，仅供参考。

```python
import csv
rows = list(csv.DictReader(open("data/derived/formal_corpus.csv", encoding="utf-8")))
clip = f"data/{rows[0]['clip_path']}"   # 第一条音频
```

## 4. 数据库 `data/corpus.sqlite3`

核心表：

- `entries`：`item_id, source_page_id, table_kind, page_position, global_seq, word_raw, pinyin_raw, pinyin_nfc`
- `segments`：`item_id, clip_path, clip_sha256, algorithm_version, confidence, start_ms, end_ms, start_ms_raw, end_ms_raw`
- `source_pages`：页面 URL、音频 URL、哈希、状态
- `reviews`：试点审核记录（197 approved / 3 rejected，仅供追溯）
- `excluded_items`：`item_id, reason, kind, detail, created_at` —— **正式数据 = entries 中不在 excluded_items 的行**

推荐查询（只读）：

```sql
SELECT e.item_id, e.word_raw, e.pinyin_nfc, e.table_kind, e.global_seq,
       s.clip_path, s.clip_sha256, s.confidence
FROM entries e
JOIN segments s ON s.item_id = e.item_id
LEFT JOIN excluded_items x ON x.item_id = e.item_id
WHERE x.item_id IS NULL
ORDER BY e.table_kind, e.global_seq;
```

## 5. 媒体访问（审核服务 API）

本地服务：`python -m pth_corpus review`（127.0.0.1:8765）

- 列表/详情：`GET /api/items?limit=200`、`GET /api/items/{item_id}`
- 音频：`GET /media/items/{item_id}/clip?v={clip_sha256}`（必须带版本号，否则旧缓存可能命中；带错版本返回 409）
- 波形：`GET /api/items/{item_id}/waveform?asset=clip&v={clip_sha256}`
- 抽样核对页：`GET /sample`（读 `data/review/sample_200_*.csv` 最新一批）

注意：服务会自动过滤 `excluded_items`，被排除条目返回 404。正式应用建议直接读 CSV/SQL，不必起服务。

## 6. CLI 命令

```bash
python -m pth_corpus qa --scope full        # 全量机器 QA（当前 passed）
python -m pth_corpus sourcecheck            # 源站质量筛查（字/拼音/声调）
python -m pth_corpus review                 # 本地审核服务
python -m pth_corpus phonology              # 全量语音特征打标（phonology-v1）
```

## 6.5 语音特征底层 phonology-v1

> 2026-08-08 已跑通：16,156 条输入 → 16,149 条解析成功（覆盖率 99.9567%），7 条源数据异常进复核队列，机器 QA `PASSED`。

所有产物在 `data/derived/phonology-v1/`（只读正式清单，不修改母库）：

| 文件 | 内容 |
|---|---|
| `syllable_features_v1.csv` | 每音节一行：声母+部位/方法/清浊/送气、韵母+四呼/韵头/韵腹/韵尾/鼻韵、声调/轻声/儿化 |
| `item_features_v1.csv` | 每词一行：字/音节数、序列（如 `s-sh`、`3-4`）、各类计数与目标音位置 |
| `phonology.sqlite3` | 同构 SQLite（`syllable_features`、`item_features`、`problem_profiles`、`review_needed`、`stats`） |
| `phonology_review_needed_v1.csv` | 7 条无法可靠判断的异常（源拼音打字错误等） |
| `phonology_excluded_v1.csv` / `available_item_ids_v1.csv` | 排除清单 + 可用 16,149 条 ID 清单（开发默认用这个范围） |
| `phonology_rules_v1.json` | 版本化规则：声母表、39 韵母表、411 标准音节表、规范化规则 |
| `problem_profiles_v1.json` | 教学问题 Profile（平翘舌、n/l、f/h、前后鼻音、上声等），后续加检索条件优先改这里 |
| `phonology_stats_v1.json` / `TAGGING_REPORT_V1.md` | 全量分布统计 + 验收报告 |
| `validation_samples_v1.csv` / `VALIDATION_REPORT_V1.md` | 13 类共 507 条抽样 + 机器复核/人工检查报告（0 条分类错误） |

推荐用法：

```python
import sqlite3
con = sqlite3.connect("file:data/derived/phonology-v1/phonology.sqlite3?mode=ro", uri=True)
con.row_factory = sqlite3.Row

# 双音节、第一音节平舌、第二音节翘舌、3-4 调
rows = con.execute("""
    SELECT item_id, word_raw, pinyin_nfc
    FROM item_features_available
    WHERE syllable_count = 2
      AND flat_initial_positions = '1'
      AND zh_ch_sh_positions = '2'
      AND tone_pattern_lexical = '3-4'
""").fetchall()
```

注意：`phonology.sqlite3` 只存语音特征，不含音频路径；取音频时仍按第 4 节用母库 `data/corpus.sqlite3` 的 `segments` + `excluded_items` 过滤（`clip_path` 不在上表，需要时再从母库 JOIN 一次）。开发查询建议直接用 `item_features_available` / `syllable_features_available` 视图，自动排除 7 条异常；如需修复异常请先确认源拼音，再升级规则版本重新跑 `phonology`。

## 7. 常见用法示例

### 7.1 按表/按区间取词条

```python
import sqlite3
con = sqlite3.connect("file:data/corpus.sqlite3?mode=ro", uri=True)
con.row_factory = sqlite3.Row
rows = con.execute("""
    SELECT e.item_id, e.word_raw, e.pinyin_nfc, s.clip_path
    FROM entries e JOIN segments s ON s.item_id=e.item_id
    LEFT JOIN excluded_items x ON x.item_id=e.item_id
    WHERE x.item_id IS NULL AND e.table_kind='table1'
      AND e.global_seq BETWEEN 1 AND 100
    ORDER BY e.global_seq
""").fetchall()
con.close()
```

### 7.2 校验切片是否完整

```python
import hashlib
h = hashlib.sha256(open("data/derived/clips-v2/table1/t1-00001.wav","rb").read()).hexdigest()
assert h == "e1931da471bb53b5147ea40608cab84954d3455e7a5a4889a1e55cc680ed8271"
```

### 7.3 恢复一条被排除的条目

1. 从 `data/derived/excluded_items.csv`（或各批次 `*_excluded.csv`）找到原路径；
2. 把 `data/derived/clips-excluded/{table}/{id}.wav` 移回 `data/derived/clips-v2/{table}/{id}.wav`；
3. `UPDATE segments SET clip_path='derived/clips-v2/{table}/{id}.wav' WHERE item_id=?`；
4. `DELETE FROM excluded_items WHERE item_id=?`；
5. 重跑 `qa --scope full` 确认。

## 8. 注意事项

- **正式数据以 `excluded_items` 之外的 16,156 条为准**；17,055 条全量里含 899 条已知错误，直接全量使用会带错。
- 音频为源站录音，仅限校内/本地试用，不得公开再分发。
- 切片 WAV 均 16kHz 单声道 16-bit；需要更高采样率请用 `data/raw/audio` 源 MP3 重切。
- 源 MP3 含每页开头报幕（仅 t1-p001/t2-p001）和尾部广告，直接截取时注意；正式切片已处理干净。
- 数据库平时以只读方式打开（`?mode=ro`）；需要写库（如恢复条目）先备份。
