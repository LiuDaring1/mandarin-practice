# 模块：句子练习（sentence-practice）

## 2026-10-23 试用精简版（当前，替代下方早期行为）

- 正式只抽原 582 句散文；450 条新闻发布音与其原素材保留在磁盘，但不进入 `PrototypeRuntime.sentence_pool()`。这次没有重新切片／换声，不宣称修好了新闻吞音或啸叫。
- 前台只留前鼻为主／后鼻为主；底层 mixed/custom 筛选保留供研究和未来复练。原 mixed 是“同句含两类”，不是对比教学设计；散文 front 224 中 209、back 196 中 185 也属于 mixed（共 503）。
- 5／10 句、默认 5；两遍跟读，每句首遍预览 1.6 秒。所有示范按 1× 播放，忽略旧语速偏好，撤掉变速控件。正文统一颜色、无彩色底块，首遍拼音开、第二遍关。
- 跟读窗口为 `min(59, max(7, clip_duration*1.7+2))` 秒；“读完了”可提前结束。暂停示范后继续播放；暂停朗读会丢弃未提交的这一遍，按钮和状态明确提示“重新跟读”，仍是当前遍，不跳题。
- 5 句不等于 3 分钟。散文按每档 100 个种子估算、等满所有窗口，5 句中位约 5.3–5.7 分钟；主动完成通常更短，但未做人群时长验收。首页仅显示句数／两遍，不写失准分钟数。
- 本地发声检查、不上传录音与无回顾，见评测模块。机器浏览器检查不替代用户真人听感。


> 2026-10-23 回顾清理：撤掉工程状态与无内容回顾，仅显示具体待重读条目；未取得可靠鼻音诊断前不生成自动薄弱项。拆分韵母映射已修，详见最新评测模块。

> 2026-10-23 真人反馈修订：男女示范共用保音高变速，默认 0.85，可切 0.75／1；仅浏览器播放速度变化，原音库和哈希不变。每句先预览 1.6 秒；每遍跟读为 max(7s, 原时长/速度×1.7+2s)，上限 59s，可点“读完了”；暂停后重录整遍，后台已提交结果不取消。两遍、拼音及奖励档位沿用，首页不再显示失准的旧“约4分钟”。逐句评分改为练后汇总；鼻音自动复练仍受验证门禁控制，见 `assessment.md` 和最新 MEMORY。下文的 1.2× 是历史口径。

> 2026-10-23：现行库为原 582 句散文 + 新增 450 句新闻（均有新闻男声／女声），10 句抽 5+5，15 句随机 7+8，音筛选后不足才补位。新闻由 `news_sentences.py` 加载独立双声完整发布，不改旧库；页面标明新闻来源，首页不展示库存数。历史 97.1% 人耳验收只指散文，新增新闻仅完成机器筛选。字词／句子录音评测见 `assessment.md`，本轮记录见 `../MEMORY-2026-10-23-news-assessment.md`。下文为早期语料管线历史，当前奖励档位以奖励模块为准。

> 给 AI 的 3 行摘要：50 篇朗读作品 → 688 句入选 → 582 条示范音切片；首页第二 Tab，
> 三档筛选（前鼻为主/后鼻为主/前后都有），逐字高亮 + 跟读窗口 1.2×，人耳验收 97.1%。

## 职责

前后鼻音句段朗读练习：从朗读作品 PDF 抽取句子 → 按鼻音密度评分入选 → faster-whisper
词级时间戳对齐 → ffmpeg 切示范音 → 应用内整句跟读。

## 现状（2026-08-23）

- 管线已收口：50 篇 → 873 句 → 688 句入选 → 739 条 high 对齐 → 582 条 WAV 切片，机器 QA passed。
- 人耳四轮迭代 69%→81%→88%→97.1% 达验收线；唯一遗留 `30-小鸟的天堂-0007` 已记录。
- 应用：三档筛选 + 目标音硬门槛 + 加权抽句；奖励走统一管道（每句 0.5 拼点 + 整轮完成 +1）。

## 关键文件

| 内容 | 位置 |
|---|---|
| 管线模块 | `src/pth_corpus/sentence_reading.py`（extract/score/align/cut/status） |
| 转写/校验工具 | `tools/whisper_sentence_transcribe.py`、`tools/whisper_verify_sentence_clips.py` |
| 产物 | `data/derived/sentence-practice-v1/`（articles/sentences/alignment/clips/clip_manifest） |
| 服务端 | `prototype_app.py` 的 `/api/sentence/*`（home/session/count/clips/events） |
| 前端 | `prototype_static/app.js` 的 `view-sentence` 流（`startSentenceSession` 等） |

## 数据

- 来源边界：`handoff/SOURCE-sentence-reading.md`。
- 转写依赖 `/opt/miniconda3/bin/python`（词级时间戳）与系统 `ffmpeg`。

## 已知问题（环境，勿当回归）

- 4 个句子管线测试失败：`tests/test_sentence_reading.py::test_cut_clip/test_silence_ratio/test_machine_qa/test_run_cut_flow`
  —— 本机 `data/derived/sentence-practice-v1` 数据缺失/`ffmpeg` 不在 PATH。

## 待办

- 无产品阻塞项；如改句库，重跑 `sentence extract|score|align|cut --out data/derived/sentence-practice-v1`。
- 里程碑：`handoff/MEMORY-2026-08-14-sentence-practice.md`。
