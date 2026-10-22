# 字词／句子朗读评测

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
