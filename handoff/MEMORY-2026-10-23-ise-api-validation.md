# 2026-10-23 ISE 实测与 Suntone 使用复核

用户要求先认真核实 API 用法，再比较另外一个 ISE 产品，不把后续研究推给厂商，也不预先否定自研。基于 `f9979da` 建 `codex/ise-api-validation`；正式软件没有改动。现有应用凭据可调用 ISE，无需用户另行开通；凭据仍仅在被忽略的本机配置中。

## 结论与解释

ISE 的返回结构更适合专项反馈：声母／韵母、韵母错误／调型错误、增漏替换、时间位置和部分置信度可以区分。优先继续验证 ISE 有依据，但本轮不能宣称它已达到学生诊断精度，或在所有场景比 Suntone 更准。自研仍是候选，可以基于现有声学模型做窄范围分类，不等于从零训练通用语音模型。

此前表格的含义应表述为“题目要求读心，实际送入星的录音，看接口是否发现不匹配”。改变参考答案是同一音频的对照实验，不是文字识别，也不是要求接口忽略声音强行按文字打分。所用音频来自标注示范库，没有新录制学生错误；原录音自身的口音、边界与标签也需要人工复核。不能把所有正确参考下的低分直接称为供应商误判。

## 文档核对与正确调用

官方来源：[ISE 文档](https://www.xfyun.cn/doc/Ise/IseAPI.html)、[Suntone 文档](https://www.xfyun.cn/doc/voiceservice/suntone/API.html)、[Suntone Python 示例](https://xfyun-doc.xfyun.cn/static/16564864206416582/suntone_ise_cn_python_demo.zip)。本轮重新读取正文与示例，未联系外部人员。

ISE 使用 `wss://ise-api.xfyun.cn/v2/open-ise`：

- `ent=cn_vip`，单字 `category=read_syllable`、句子 `read_sentence`，成人 `group=adult`；UTF-8 BOM 文本、`ttp_skip=true`。
- 错误细节同时开启 `ise_unite="1"`、`rst="entirety"`、`extra_ability="syll_phone_err_msg;multi_dimension"`；不只读取总分。
- 16kHz、单声道 PCM16，去 WAV 头，`aue=raw`；ssb 参数首帧后，auw 音频 aus 依次1／2／4，data.status为1／1／2；1280字节／40ms。
- `is_yun=1` 表示韵母。`perr_msg=0`声韵调型正常，1韵母错，2仅调型错，3两者均错；不能把2误判为鼻音错误。`dp_message=128`是替换，也不是直接返回实际读成哪个鼻尾。0/16/32/64分别为正常／漏／增／回读。
- `perr_level_msg`按官方为1最好、3最差，0不作置信度依据。本轮单字大多0；句中山→商的韵母错误置信度3，不能称为高置信命中。
- 即使报韵母错误，也不自动等于明确 n→ng 或 ng→n；错误可能在元音部分。未上线新的诊断规则。

## ISE 实测：32次成功

12份原声六对最小对照，各按正确和相反参考评测，共24格；冒烟复用矩阵缓存。

| 观察 | 数量 |
|---|---|
| 相反参考下明确报韵母错（perr_msg为1/3） | 9／12 |
| 加上韵母位置报替换（dp_message=128） | 10／12 |
| 相反参考两类信号都没报 | 2／12：零录音／题目林，帮录音／题目班 |
| 正确参考仍报韵母错 | 2／12：心、零，需要人工核验原音，不能直接定性误判 |

“商录音／题目山”为 perr_msg=0 但 dp_message=128，说明不能只看单字段。“星录音／题目心”被标记韵母错误和替换，解决了同一参考对照在 Suntone 下得到100分的问题；但另有漏判，不能用这一个例子代表全面胜出。

两段原散文，各按原文字与只替换一个目标字评测，共4格。录音不变：

| 实际录音目标／题目要求 | ISE目标韵母结果 |
|---|---|
| 山／山 | 正常 |
| 山／商 | 韵母错误；置信度等级3 |
| 清／清 | 正常 |
| 清／亲 | 仍正常，未发现目标不匹配 |

另用 `check_type=hard` 重测4格（心／心、星／心、零／林、零／零），目标错误字段未改变。普通／严格的区别不应仅凭参数提交成功推定有效，也未穷尽其他配置或群体。

## Suntone 补查：14次成功

原先32次请求账本保持，追加至46，没有重置计数：

1. 4格按64kbps MP3的实时速率发送（320字节／40ms），对比之前1280字节／40ms，末韵母分未变。官方通用示例的122字节块针对其Speex说明，不能机械套到MP3。
2. 4格 `slack=-0.5, precision=0.1`，异常韵母分未变；不能声称已经穷尽严度调参。
3. 4格显式 `refPinyin`，并开启 `getParam=1`，服务器回传参考拼音、precision=0.1、phoneme_output=1、coreType=word.eval.cn；上述目标分未变。
4. 2格句子改用实际汉字替换“山→商”“清→亲”，与此前花括号指定拼音结果相同（1／100）。排除了这两例仅因指定拼音写法产生异常的解释。

因此目前没有证据把这些具体反例归因于未开音素输出、发送太快、拼音未明确或仅分数精度设置问题；也不据此宣布 Suntone 所有模式均无效。

## 代码、数据与复现

- `scripts/ise_probe.py`：ISE协议与XML白名单提取，音素保留所属字，实体解析关闭。
- `scripts/validate_ise_nasal.py`：24格字音对照。
- `scripts/validate_ise_followups.py`：句子、4格严格度、Suntone参考格式对照。
- `scripts/audit_suntone_usage.py`：发送速率、松紧度、显式拼音复核。
- 共用原有缓存／配额／文件锁。不同接口／传输方案用独立缓存前缀，避免错误复用；原Suntone默认缓存键保持不变。没有 `--allow-paid` 只读缓存，不发请求。
- 配置与完整返回仅在 `data/derived/{ise-validation,suntone-validation}/`（Git忽略，JSON0600）。新公开报告只含目标字／数值，不提交完整句子、音频或凭据。
- [ISE字音](ise-validation-2026-10-23/ise-words.json)、[ISE句子](ise-validation-2026-10-23/ise-sentences.json)、[严格度](ise-validation-2026-10-23/ise-hard-controls.json)、[Suntone复核](ise-validation-2026-10-23/suntone-usage-audit.json)、[参考格式](ise-validation-2026-10-23/suntone-sentence-parity.json)、[验证记录](ise-validation-2026-10-23/verification.json)。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts ../.venv/bin/python scripts/validate_ise_nasal.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts ../.venv/bin/python scripts/validate_ise_followups.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts ../.venv/bin/python scripts/audit_suntone_usage.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts ../.venv/bin/python -m pytest tests/test_suntone_probe.py tests/test_ise_probe.py -q
```

19项离线测试通过；本轮真实调用46次成功（ISE32＋Suntone14），本地计数不是供应商余额或实际扣费账单；缓存复跑不增加计数。198个原有真实进度文件哈希未改。只改隔离研究脚本，未重复跑全应用／浏览器回归，也没有启用正式云评测或反馈。

下一步重点是核验当前反例的原音并扩大 ISE 的针对性验收，尤其是 in/ing 和句中定位。真实少量朗读的价值是验证系统是否误判，不是预先要求建设训练语料库。若不足再比较现有模型上的专项判别；目前不做“外部API一定行”或“自研不靠谱”的承诺。
