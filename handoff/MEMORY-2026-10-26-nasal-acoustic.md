# 2026-10-26晚至27日凌晨：声学判别与公开真人错音验证

用户授权继续想办法解决 n/ng 反馈，可用外部 API，也可自研，不以时间或额度限制研究。本轮从 `89b0296` 的 ISE 研究成果继续到 `codex/nasal-acoustic-prototype`。**目标仍未完成**：正式应用仍只有发声检查，尚未启用可靠鼻音反馈。不能把下面的研究数据当作上线准确率。

## 新增证据

1. 运行两个固定版本的本地模型，不给推理器标准答案：Meta 多语言音素 CTC，以及 HanziFlow 声母／韵母／声调模型的韵母头。后者用库内 Wav2Vec2 和 safetensors 重建结构，未执行下载的自定义 Python。模型不加入 APP 默认依赖。
2. 36 份原有单字／换声参考音：音素模型类别与标签一致31、未判断3、不一致2；韵母模型一致31、未判断4、不一致1。这仍不是学生准确率，三个声音不是三个独立人。
3. 韵母模型对句中“山”的3个版本均更支持 an，对“清”的3个版本均更支持 ing；此前 ISE 未报清／亲差别。自然词“林业”仍更支持 ing，显示不能直接启用。10项上下文的精确声学差值见 [汇总](nasal-acoustic-2026-10-26/report.json)。CTC 差值不等于校准后的置信度。
4. 找到 [香港教育大学公开语料](https://lml-elearning.eduhk.hk/about_g.aspx)，有明确的前后鼻音替换标注与研究用途录音下载。40个说话人页面中提取92处纯 n/ng 字母替换标注，下载对应50段录音；未将录音、完整网页或个人背景信息提交到 Git，也未把它们当 APP 示范音。
5. 网页词表可能不同于实际朗读顺序。最初直接按词表对齐的尝试不能作为结果；最终采用**无答案提示转写→对该转写定位→唯一拼音近邻匹配**。重复、冲突或异常时长排除。得到610个词候选；480个匹配不明确、24个时间边界异常的词候选排除。对齐仍未经人耳逐条复核。

## 真人错音筛查

92处显式鼻音替换中，本轮完成自动定位及韵母评分的为51处，另41处未评分，不能算成功。51处里：

- 39处相反鼻音的 CTC 声学似然高于原韵母；把漏读候选也加入比较后，37处仍以相反鼻音为最高。
- 自由解码明确支持相反鼻音类别的为30处。
- 475个没有韵母偏差标注的位置中，64处同样更支持相反鼻音，提示可能存在误报、标注遗漏或定位问题；“未标错”不等于确证正确，因此不计算伪精确率。
- 独立音素模型对可用单字中的33个标注错音，14个类别吻合、15个弃判、4个不吻合。不能仅因模型直接输出 n/ŋ 就认为它更可靠。

这批公开录音已用于方法筛选；按说话人1–20／21–40分别汇总只是描述性分组，不冒充从未查看的最终保留集。尚未拟合判错阈值。

## ISE 必须保留为候选

用同一批真人录音追加6次 ISE 调用：in/ing、en/eng、an/ang 两个方向各1例，包含本地韵母差值漏掉的2例。**6例均返回目标韵母异常或替换**，而本地差值支持相反鼻音4例。接口与之前的流式 ISE、参数、XML提取相同，累计账本由72到78；脚本硬上限仍80，未重置账本。

这些是有意选取的已知错音，且定位仍需审计；不能把6/6写成接口准确率。`perr_msg`／替换仅说明一般韵母异常，不直接给出真实 n/ng 方向。本轮没有配套的确证正确真人对照，必须继续测误报。新证据不支持放弃 ISE 或认定纯自研优于 API。

## 实现与复现

- `scripts/nasal_acoustics.py`：音频独立推理、按模型版本／波形缓存 logits、自由 CTC 解码、精确候选路径概率求和。
- `probe_nasal_acoustics.py`、`prepare_nasal_context.py`、`probe_nasal_context.py`：旧参考音和自然词句对照；修正模型特有的舌尖元音标签（卷舌 ii，平舌 iii）。
- `collect_eduhk_nasal.py`、`download_eduhk_audio.py`：缓存公开页面标注及直接下载链接。保持研究归属与用途，二路下载，已下载不重取。
- `prepare_eduhk_crops.py`：无提示 Qwen ASR＋Qwen ForcedAligner，仅作音频定位；拒绝多条词表记录占同一音段，不把对齐当发音评测。
- `probe_eduhk_nasal.py`、`probe_eduhk_phoneme.py`、`probe_ise_eduhk.py`、`report_nasal_acoustics.py`：本地模型对照、小批 ISE 复查和脱敏统计。付费仍须显式 `--allow-paid`；不自动重试供应商失败。

研究目录：`data/derived/nasal-acoustic-validation/`，全部私有媒体、logits、逐条输出留在忽略目录。ISE凭据和原返回仍在 `data/derived/ise-validation/`，不打印。

模型及来源：

- [Meta 音素模型](https://huggingface.co/facebook/wav2vec2-xlsr-53-espeak-cv-ft)，revision `2c733782da5604684829819a5eb744c193fe9398`。
- [HanziFlow V2.1](https://huggingface.co/thin-nwe-soe/hanziflow-v2-1-multihead-wav2vec2)，revision `93c4b3f185f67b2f82135b34ca0397ddf8254de1`。模型作者也明确尚未验证为学习者打分工具。
- 既有 Qwen3-ASR／ForcedAligner 缓存继续使用，版本固定在脚本；没有重新训练大模型。
- [OMPAL](https://github.com/phantomhsieh/OMPAL-corpus) 已调查并缓存评分元数据，尚未评测；其韵母正误标签不能直接当作 n/ng 方向标签。

在正式仓库目录运行（模型已在维护者机器缓存，其他机器须按代码固定版本准备）：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts ../.venv/bin/python scripts/prepare_nasal_context.py
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 /opt/miniconda3/bin/python scripts/probe_nasal_acoustics.py --kind final
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 /opt/miniconda3/bin/python scripts/probe_nasal_acoustics.py --kind phoneme
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 /opt/miniconda3/bin/python scripts/probe_nasal_context.py
PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python scripts/collect_eduhk_nasal.py
PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python scripts/download_eduhk_audio.py
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 /opt/miniconda3/bin/python scripts/prepare_eduhk_crops.py
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 /opt/miniconda3/bin/python scripts/probe_eduhk_nasal.py
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 /opt/miniconda3/bin/python scripts/probe_eduhk_phoneme.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts ../.venv/bin/python scripts/probe_ise_eduhk.py
PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python scripts/report_nasal_acoustics.py
```

## 验证与仍须完成的工作

44项相关离线测试通过（15项新增，29项既有供应商测试），包括枚举 CTC 路径核验、相邻重复音、漏读／无鼻尾不判对、标准答案交换只翻转比较符号、不同音标体系映射、标注解析、网页顺序不同／重复定位拒绝、不完整批次不发布为完整结果。未改正式产品代码，未重跑全 APP 或浏览器测试。198个已有真实进度文件SHA未变；8769健康检查 ready=true，cloud_enabled=false。详见本轮 verification.json。

接下来按 [持续目标与验收要求](NASAL-FEEDBACK-GOAL.md) 继续：先取得确证正常发音对照、审计切片并扩展 ISE 比较；再校准 API＋本地声学的判别／弃判，解决句内定位，最终接入可操作的字词及句子反馈。不要把本次脚本、模型下载或筛查统计当作用户目标已经完成。
