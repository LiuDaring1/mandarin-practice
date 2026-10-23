# 2026-10-24 ISE 现有声音与词句验证

用户同意继续试 ISE，希望弄清“更值得验证”究竟指什么、是否能直接用 API 调用。基于 `df12090` 建 `codex/ise-voice-validation`，只做隔离评测，没有启用正式云评测／鼻音诊断。

## 版本和验证目的

当前测试的是 [ISE 语音评测（流式版）](https://www.xfyun.cn/doc/Ise/IseAPI.html)，WSS `/v2/open-ise`，不是官方已下线的 HTTP [普通版](https://www.xfyun.cn/doc/voiceservice/ise/API.html)。流式版已多次真实调用成功；“有错误字段”不等于“判别可靠”。

本轮检查三点：相反鼻音是否报异常、正确参考下是否仍报异常、同一目标放进不同声音／自然词语／句子后结果是否一致。原声、女声和男声是原有参考音与剪映换声版本，不是三个独立说话人。换声可能改变发音，不能把差异全归给评测，也不能当作学生准确率。

## 试验设计

- 针对已有疑点选择心／星、林／零、班／帮六字，每字原声与两种换声，各按正确和相反参考评测，共36格；12格原声复用已有缓存，新增24次。
- 另取原库自然连续录音“零件、林业、班级、帮助”，不用单字拼接。每词只改变一个目标字作为相反参考，共8次。使用 `read_word`。
- 两段原散文，检查“山／商”“清／亲”；原声与两种换声各按正确和相反参考，共12格。4格原声复用缓存，新增8次。使用 `read_sentence`。
- 共56格，40次新调用。已有 ISE 账本从32累计到72，未重置；本轮用户授权后将这份脚本的累计硬上限设为80，不是额外80次，也不是供应商余额。没有重跑全部历史用例收费。
- 设置仍为 `cn_vip/adult/common`，`ise_unite=1/rst=entirety/extra_ability=syll_phone_err_msg;multi_dimension`，PCM16／16kHz／单声道。仅必要时重采样，不改源文件。

## 结果解释与证据

逐格结果、按声别统计以及简表见 [报告目录](ise-stability-2026-10-24/README.md) 和 [report.json](ise-stability-2026-10-24/report.json)。

`flagged` 仅表示目标韵母报错或替换，不能翻译成已确认 n→ng／ng→n；`not_flagged` 仅表示没有这类信号，不能翻译成读对。调型错误 perr_msg=2 不作为鼻音错误。拒识、漏读、目标丢失或重复位置不能当作通过。

词语原音中，“林业”的林和“班级”的班按相反参考均报异常，按正确参考未报；“帮助”的帮也能在相反参考下报异常，而先前单字帮→班没有报。零件中的零按林评测仍没报、按零反而报异常，需要核查原音及模型偏差，不能直接定性为学生错误或评测误判。

单字换声测试中，零的女声版本两类参考能分开，原声／男声没有；星的女声版本出现相反参考未报、正确参考报异常，原声／男声对应结果更符合题目预期。可见输出尚不能视为稳定的鼻音判断。原始读音、切片和换声质量未经本轮人工听音标注，这也是限制。

句中清→亲在原声／女声／男声三种版本都未报异常；山→商在原声／男声报异常、女声未报。正确参考的这两个目标在六个版本均未报异常。详见 report.json。未因接口成功返回就自动向真实学习记录写入任何错误标签。下一步若继续诊断，需要先人工复核这些现成反例音频的实际发音，再确定 API 的错漏边界；不需要把这种验收说成从零训练模型或先建大规模真人训练集。

## 实现与验证

- `scripts/validate_ise_stability.py`：三组最小对照、自然词语及句子声音复核；默认只读缓存，显式 `--allow-paid` 才发请求；遇供应商失败即停止，不自动重试。
- `scripts/report_ise_stability.py`：生成脱敏统计与对照表，不输出学生准确率。
- `scripts/ise_probe.py`：音素补充所属音节，解决多字词只靠上层 word 可能错配目标的问题。
- 新测试覆盖多字词目标归属、声调错误不冒充韵母错、替换字段兼容、拒识／漏读／重复位置弃判；相关29项离线测试通过。研究脚本之外没有产品改动，未重跑全应用／浏览器测试。
- 本机完整结果和音频继续在被忽略的 `data/derived/ise-validation/`；配置不入仓。公开文件不含完整句子音频／凭据／真实进度。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts ../.venv/bin/python scripts/validate_ise_stability.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts ../.venv/bin/python scripts/report_ise_stability.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts ../.venv/bin/python -m pytest tests/test_suntone_probe.py tests/test_ise_probe.py tests/test_ise_stability.py -q
```

数据核验：198个已有真实进度文件SHA未变；缓存重放56格后账本仍为72。正式状态接口 `cloud_enabled=false`。见 [核验记录](ise-stability-2026-10-24/verification.json)。
