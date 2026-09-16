# 模块：句子练习（sentence-practice）

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
