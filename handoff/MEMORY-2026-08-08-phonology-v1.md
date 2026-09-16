# 普通话语音系统 · 语音特征打标 v1 节点记录（Memory）

记录时间：2026-08-08（Asia/Shanghai）
状态：**阶段完成** —— 16,156 条正式语料完成确定性语音特征打标；7 条源拼音异常已隔离；分类验证通过；可进入下一阶段开发。

---

## 一、本次目标与边界

- 依据《普通话语料自动语音特征打标规格 v1.1 全自动版》只建设“语音特征底层”。
- 不做手机页面、播放器、语音评测 API。
- 不修改母库 `data/corpus.sqlite3` 与正式清单；所有产物放在独立目录 `data/derived/phonology-v1/`。

## 二、数据与规则

- 输入：`data/derived/formal_corpus.csv`，16,156 条（字词 + 拼音 + WAV 切片路径）。
- 实现：确定性普通话音节解析器 `src/pth_corpus/phonology.py`（无空格拼音用动态规划按 411 个标准音节切分）。
- 规则版本：`phonology_rules_v1.json`（v1.0.0）：21 个辅音声母 + 零声母、39 韵母体系、四呼、韵头/韵腹/韵尾、前后鼻音、声调/轻声/儿化、“一/不”变调候选。
- 拼音格式实况（已摸清并处理）：
  - 无空格连写 + Unicode 声调符号；
  - 音节分隔符 `•`（129 条）、`*`（129 条）、`’`（119 条）、`‘`（1 条）；
  - 源站特殊字形 `ɡ`（3309 条）、`ɑ`（1 条），已归一化为 g/a；
  - 儿化写成词尾 `r` 或中性 `er` 后缀；
  - 轻声 = 拼音中无声调符号的音节。

## 三、结果

| 指标 | 数值 |
|---|---:|
| 输入条目 | 16,156 |
| 成功解析 | 16,149（覆盖率 99.9567%） |
| 排除异常 | 7 |
| 可用条目 | 16,149 |
| 音节特征行 | 29,894 |
| 机器 QA | PASSED |
| 分类验证 | 13 类 507 条，0 不一致 / 0 分类错误 |

## 四、产出文件（data/derived/phonology-v1/）

| 文件 | 用途 |
|---|---|
| `syllable_features_v1.csv` | 每音节一行：声母/部位/方法/清浊/送气、韵母/四呼/韵头韵腹韵尾/鼻韵、声调/轻声/儿化 |
| `item_features_v1.csv` | 每词一行：长度、序列、计数、目标音位置 |
| `phonology.sqlite3` | SQLite：`syllable_features`、`item_features`、`problem_profiles`、`excluded_items`、`item_features_available` 视图等 |
| `available_item_ids_v1.csv` | 可用 16,149 条 ID 清单（开发默认范围） |
| `phonology_excluded_v1.csv` | 7 条异常清单 |
| `phonology_rules_v1.json` | 版本化规则表 |
| `problem_profiles_v1.json` | 教学问题 Profile（平翘舌、n/l、f/h、前后鼻音、上声等） |
| `phonology_stats_v1.json` / `TAGGING_REPORT_V1.md` | 全量分布统计 + 验收报告 |
| `validation_samples_v1.csv` / `VALIDATION_REPORT_V1.md` | 13 类 507 条抽样 + 机器/人工验证报告 |
| `qa_samples_v1/` | 自动抽样的 QA 样本 CSV |
| `query_samples_v1.json` | 10 组演示查询（每组 20 条） |

## 五、7 条被排除的异常（未猜、未自动改）

| item_id | 字词 | 拼音 | 原因 |
|---|---|---|---|
| t1-00991 | 地下 | dìíxia | 双声调，疑为 dìxià / dìxia |
| t1-05250 | 笑话儿 | xiàohuar | 儿化音节缺声调，疑为 xiàohuàr |
| t2-05821 | 偏 | piān心xīn | 拼音混入汉字，疑为两个词条粘连 |
| t2-09085 | 一目了然 | yīmùlliǎorán | 多一个 l，疑为 yīmùliǎorán |
| t2-09731 | 寨子 | zhaizi | 整条漏标声调，疑为 zhàizi |
| t2-10003 | 指甲 | zhǐjia（zhījia） | 括号注音，建议取主读 zhǐjia |
| t2-10333 | 自给 | zìɡǐ | ɡ 疑为 j，应为 zìjǐ |

若后续要把覆盖率达到 100%，先人工确认这 7 条的源拼音，再升级规则版本重新跑 `phonology`。

## 六、关键口径与已知限制

1. “翘舌音”类别按客观发音部位包含 `r`；纯 zh/ch/sh 训练请用 `zh_ch_sh_positions` 或 `zh_ch_sh_翘舌训练音` 类别。
2. 轻声按“源拼音无声调符号”判定，不参考词典习惯；个别词源站标法与常用词典可能不同。
3. 3-3 上声只标记候选（`has_adjacent_33`、`third_tone_run_max`），不做实际变调值猜测。
4. “一/不”只标记 `contains_yi` / `contains_bu` 候选，`surface_tone_status = NEEDS_CONTEXT`，不覆盖词典调。
5. 儿化只认拼音词尾 `r` / `er` 后缀；“女儿 nǚ’ér”这类完整 `ér` 音节不算儿化。
6. `phonology.sqlite3` 不含音频路径；取音频时用母库 `segments` + `excluded_items` 过滤。

## 七、下一步建议

1. **Training Session Generator（训练课程组合生成器）**：基于 `item_features_available` 按声母、韵母、声调、音变、长度任意组合生成训练材料。
2. 先做几个高频组合查询并做成课程模板（如：双音节 平→翘 3-4 调、前后鼻音对比、n/l 对比、3-3 上声）。
3. 需要播放时：`item_features_available` JOIN 母库 `segments` 拿 `clip_path`，再做音频列表/切片校验。
4. 若要 100% 覆盖：修复 7 条异常后升级 `phonology_rules_v1.json` 重跑。

## 八、复现命令

```bash
python -m pth_corpus phonology --data-root data --out derived/phonology-v1 --seed 20260808
python -m pytest tests/test_phonology.py
```
