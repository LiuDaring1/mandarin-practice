# 字词／句子朗读评测

## 2026-10-23 Suntone 独立验证

声通接口已实测，不是 ISE。能输出逐字／韵母分和时间段，但最小对照存在满分漏判，句内 qing/qin 也未区分，正式鼻音门禁及云评测继续关闭。独立脚本、29次成功评测、10项离线测试与证据见 [本轮记录](../MEMORY-2026-10-23-suntone-validation.md)。不把一般低分当成鼻音错误。

## 2026-10-23 试用精简版（当前）

用户确认暂停自动腾讯评测并隐藏朗读回顾。正式 `create_app(..., cloud_assessment=False)`；状态接口返回 `cloud_enabled=false`、`recording_required=true`，无需云凭据即可本地采集。两条音频上传／评测接口在服务端返回 503，不调用供应商、不扣费；前端有持续发声音量就进入下一遍，不上传 WAV。无麦克风仅听示范、静音重读或跳过，均不计有效朗读。音量检查仍不能判断内容或 n/ng 正误。

历史记录／供应商适配／研究验证管线保留，正式 `nasal_review_enabled=False`。回顾入口和结束页回顾均隐藏。研究服务需显式 `cloud_assessment=True`；`serve_reading_qa.py` 使用合成供应商，`serve_ui_qa.py --assessment` 是明确的付费测试选择。新的 `serve_practice_qa.py` 只用临时进度、本地麦克风检查。

零完成的字词记录不再因“未提前退出”误计入三练或有效训练日；仅缺少完成比例的旧记录才兼容原兜底。此前历史记录不重写。下方是旧评测阶段记录。


## 2026-10-23 映射与用户回顾修订（现行）

`nasal_final_evidence()` 匹配连续、完整且唯一的拆分音素序列（如 x + i4 + an 中的 i4 + an 对应 ian），保留组件分数，采用含鼻音的末组件作观察，不平均出新分、不冒充独立鼻尾诊断。后续本地记录保留规范化 `provider_words`，旧历史没有完整返回／音频的部分不凭空补回。

用户页面撤掉计数、诊断门禁、缺少音素、处理队列等开发状态。只有明确待重读条目或经验证启用的薄弱项时才显示回顾和首页入口；未读完整条目后续读完整可移除。无反馈时不显示空回顾，不把无建议解释为发音全对。

真实 API 普通模式／拼音模式各24格对照均不足以用总分阈值可靠判错；离线本地ASR作为另一方法，36份参考音的鼻音类别与标注35份一致，但尚未覆盖真人错误与句子语境，不能上线精度化。讯飞ISE的韵母／调型错误字段已按官方文档核实，尚无该服务凭证实测。正式 `nasal_review_enabled` 继续 false。详细结果、边界及来源见 `../MEMORY-2026-10-23-nasal-mapping-validation.md`。后面的“练后展示状态计数”是上一轮实现，已由本节替代。

## 2026-10-23 试用后连续练习调整（现行）

- `assessment.js.grade()` 只封装当前录音并做本地持续能量检查；有持续能量即提交后台，不等待腾讯、不显示逐句分数。无持续能量须重读或跳过，权限拒绝时仅听示范、不计朗读完成。本地能量不能证明是人声或内容正确；后台没有有效朗读时在回顾说明，不追扣奖励。
- `POST /api/reading/attempts/{kind}/{reference_id}` 返回 202，服务端解析正式条目文本／上下文拼音／目标位置，再在异步任务中评测。内存音频最多 48 个任务，两路排队，复用原服务的串行预算锁。暂停／换题／结束释放麦克风，不取消已提交任务；页面过期回调不推进新练习。
- `GET /api/reading/session/{session_id}` 供结束页轮询：已评／待评／不可用／未识别朗读／可能未读完整计数，不输出总鼻音分。`GET /api/reading/review` 提供本地最近记录。“朗读回顾”在句子首页进入；结果卡保留至用户离开。
- 结果保存在 `prototype_dir/reading/attempts/*.json`（正式在 `data/derived/prototype/`，QA 使用临时目录），原子替换、0600；不存音频、密钥或签名 URL。attempt 与音频摘要持久化去重，重启后中断任务不自动重新收费。排队音频仅在进程内，服务重启标记 interrupted；这是单机后台任务，不是跨关机云队列。API 不可用不伪造零分，上传失败在当前回顾列出。
- 仅解析参考位置可完整对齐的中文单字／短句音素。非目标字、声母、缺失或歧义位置、段落模式不产生鼻韵母建议。韵母分仍可能受声调影响；未找到明确的独立鼻尾分类字段。
- **正式 `ReadingCoach.nasal_review_enabled=False`**。六次真实接口对照显示，输入“星”按“心”评测仍可能近满分；严格度 4 下“林／零”韵母分几乎相同。默认保留音素观察但 `practice=null`，不落错音标签或激活专项复练。不能仅凭现有通用 SOE 分数可靠诊断前后鼻音。
- 若未来独立验证通过，已有复练聚合按条目／位置／上下文拼音／目标韵母，区分练习轮次；同轮两遍不算重复错误，后续有效改善可移除建议。`/api/sentence/session` 的 `review=true` 将原句优先加入同韵母新句，正式门禁关闭时返回 409。只在 `serve_reading_qa.py` 的明确合成评分器里启用测试，不是生产功能已放行。

下文为初次接入说明；逐句成绩与不持久化的描述已由上述流程替代。

2026-10-23 接入腾讯云口语评测 SOE。用户要求现在实施路线图 #8：没有发声不计完成，低分不设门槛、不减少奖励；账户管理另行处理。

## 运行

后端 `assessment.py` 读取本地被忽略的 `data/derived/assessment/config.json`：`appid`、`credential_file`（腾讯导出的 SecretId/SecretKey CSV）、`score_coeff`、`limit_units`。也可用 `TENCENTCLOUD_APP_ID`、`TENCENTCLOUD_SECRET_ID`、`TENCENTCLOUD_SECRET_KEY` 环境变量；凭证不进入静态文件、API 响应、Git 或报错文本。配置示例只包含占位值：

```json
{"appid":"YOUR_APP_ID","credential_file":"/private/path/SecretKey.csv","score_coeff":2.0,"limit_units":1000}
```

`GET /api/assessment/status` 提供可用状态与本地测试剩余额度。`POST /api/assessment/word/{id}`、`sentence/{id}` 接收原始 WAV 和 `attempt_id` 查询参数；参考文本由正式条目 ID 在服务端查询。没有任意文本评测入口。

通过 SOE 新版 WSS 录音模式上传单声道 PCM16 16kHz WAV，0.25–59 秒；单字／词句／段落按参考文本长度选择模式，超过 120 字不截断参考文本而返回不支持提示。发送一份 WAV 与结束帧，保留终帧之前的结果。网络故障不自动重发可能收费的请求。

本地单位预算是额外测试上限，**不是腾讯账户余额**。段落按字数换算单位；请求前在进程锁下预留到 `usage.json`，损坏账本拒绝继续扣费。相同 attempt 与录音哈希在进程内去重，已失败请求也缓存，重启后不能保证跨进程请求去重。录音与评分不持久化，只保存数字计数。

## 前端与完成度

`assessment.js` 在开始按钮手势中创建并恢复 AudioContext，再请求麦克风；只在跟读窗口收集录音，示范音和音效不作为跟读录音。优先 AudioWorklet，嵌入式浏览器有 ScriptProcessor 兼容路径。`reading-pcm.js` 用 FIR 降采样并写真实 WAV，不能把 WebM 当 WAV。

- 开始前明确显示录音发送至腾讯云；首次使用由浏览器请求麦克风。
- 成绩只作建议；低分可继续，弱字提示不冒充前后鼻音音素诊断。
- 静音等待用户重读或跳过，跳过不计完成；拒绝麦克风时可听示范，不发朗读完成奖励。
- 额度／网络不可用时用保守的本地发声音量检查决定是否计完成，不伪造分数。音量检测不能识别人声或判断读对。
- 暂停、重播、离页、后台取消录音／过期评分回调；完成或回首页释放麦克风。
- 字词以实际有效条目数计算完成比例；句子两遍中至少一遍有效才计该句。原奖励档位和低分奖励规则不变。

## 验证与复现

`test_assessment.py` 覆盖签名、模式、WAV、静音、供应商结果／错误、配额与去重；`test_reading_pcm.py` 检查重采样与 WAV。`scripts/qa_news_assessment_ego.mjs` 通过 Ego 原生浏览器和独立 QA 进度目录验证真实录音路径、腾讯返回、静音跳过、拒绝权限与辨音教学音。夹具使用示范 WAV 作虚拟麦克风，没有录制人声。

常规 `scripts/serve_ui_qa.py` 默认禁用评测，只有显式 `--assessment` 才使用本机测试凭证，避免旧 UI 回归无意扣费。页面验收记录见 `handoff/news-assessment-2026-10-22/ui-report.json`；机器测试不替代实体手机麦克风和真人朗读听感验收。

官方协议：[快速入门](https://cloud.tencent.com/document/product/1774/107347)、[WSS 接口](https://cloud.tencent.com/document/product/1774/107497)、[模式](https://cloud.tencent.com/document/product/1774/107373)、[计费](https://cloud.tencent.com/document/product/1774/107342)。
