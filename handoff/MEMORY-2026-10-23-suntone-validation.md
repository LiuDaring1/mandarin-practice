# 2026-10-23 讯飞 Suntone 鼻音评测实测

用户提供声通中文评测凭证并授权调用，要求验证能否解决前后鼻音反馈。基于 `codex/practice-simplification` 的 `4cefc51` 建 `codex/suntone-nasal-validation`；没有改正式 APP 或启用云评测。

## 结论

接口可用，支持字和句子的逐音素分数与时间位置；本轮默认参数下不能直接用于可靠的 n/ng 判错。不是“讯飞全部产品都不能用”：本次只测 Suntone 服务 `s8e098720`，没有测另一个 ISE 产品。

使用原库六对同声母同声调参考音：心／星、林／零、陈／成、真／争、山／商、班／帮。每个录音分别提供正确与相反参考字，共 24 格。输出的 phone／pinyin 是期望读音，不能当成模型听到的实际读音。统计取末个韵母的 pronunciation，不称为纯鼻尾分。

| 项目 | 结果 |
|---|---|
| 正确参考韵母平均分 | 88.33 |
| 相反参考韵母平均分 | 41.08 |
| 同录音正确参考分更高／相同／更低 | 9／2／1（共12） |
| 以70为演示阈值，正确参考过线 | 10／12 |
| 以70为演示阈值，相反参考仍过线 | 3／12 |

70 只是展示阈值，未经校准。“星→心”“零→林”均为100；“真→争”为80。原“林”按林20、按零35，原“心”按心40，说明低分也不能直接归因为鼻音错。样本少、来自已标注示范音，不是人工逐条复核的学习者测试集，不能报告学习者准确率。跨参考分数排序也不是已经验证的诊断算法。

句子选择原散文录音，保持录音不变，仅改变一个目标字的期望发音：

| 目标 | 原期望分 | 相反鼻音期望分 |
|---|---|---|
| 大山的“山”：shan→shang | 100 | 1 |
| 清澈的“清”：qing→qin | 100 | 100 |

两组均有逐字位置和韵母时间段。这个设计验证评分对参考发音的敏感性，不能冒充学生实际错读实验。山的相反参考同时被标成 readType=2，不能据此把所有低分解释为 n/ng 替换。

官方 Python 示例注释出现 `phoneme_diagnosis`，正文未描述其契约。另做1次 `phoneme_diagnosis=1`：星录音按心仍100，未观察到明确 n/ng 替换字段。不能声称已验证开关所有模式，或仅凭请求被接受就断言开关生效。

## 接口与数据

- [官方文档](https://www.xfyun.cn/doc/voiceservice/suntone/API.html)、[官方 Python 示例](https://xfyun-doc.xfyun.cn/static/16564864206416582/suntone_ise_cn_python_demo.zip)。本轮按文档与真实返回核对。
- WSS HMAC-SHA256；16kHz 单声道64kbps MP3；`core=word/sent`、`phoneme_output=1`、`scale=100`、`precision=1`、`slack=0`、`vad=0`、`attachAudioUrl=0`、`getParam=0`、结果 plain 内承载 JSON。
- 最后音频帧必须非空：真实返回10163指出空 audio 长度不满足要求；脚本已修正。短输入也分首尾非空包。
- 原始配置、音频、缓存与请求账本仅在被 Git 忽略的 `data/derived/suntone-validation/`；JSON 0600。不输出签名URL／凭据。截图OCR有两处字符误识别，纠正后通过认证，截图不入仓。
- 共预留32次连接请求：29次成功评测（24字音、4句子、1诊断选项），3次调试失败（1次401、2次空尾帧10163）。第一次成功单字冒烟与矩阵复用同一缓存。该数字是本地记录，不代表账户实际扣费／余额。
- 请求前计数，上限64；相同音频与参数缓存复用，异常也缓存，不自动重试；文件锁避免多进程同时操作账本。
- [字音报告](suntone-validation-2026-10-23/word-report.json)、[句子目标报告](suntone-validation-2026-10-23/sentence-report.json)、[诊断选项](suntone-validation-2026-10-23/diagnosis-option.json)、[核验](suntone-validation-2026-10-23/verification.json)均脱敏。完整句子返回仅留本地。

## 复现与验证

本机运行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts ../.venv/bin/python scripts/validate_suntone_nasal.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts ../.venv/bin/python scripts/validate_suntone_sentences.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts ../.venv/bin/python -m pytest tests/test_suntone_probe.py -q
```

前两条默认只读缓存，未命中拒绝请求。显式 `--allow-paid` 才发请求；本机凭据配置键为 `app_id/api_key/api_secret`，值不提供公开示例。10项离线测试通过，涵盖签名、首尾包／重组、缓存与额度、并发锁、结果脱敏和异常不泄露签名URL。无生产代码变更，未重复运行全套应用测试或浏览器验收；上轮406通过不是本轮结果。198个原有真实进度文件哈希未变。

## 下一步判断

优先验证外部专门评测服务仍合理，无需立即从零训练模型；但本次开通服务不等于已解决核心问题。若继续与供应商沟通，应使用已保存的满分反例，询问中文 n/ng 混淆的专门诊断能力／引擎配置，不靠调低总分阈值制造反馈。若外部服务仍不足，再评估现有声学模型加专项判别器。真实少量朗读的用途是验收误判／漏判，不等于一开始建设大规模训练库。
