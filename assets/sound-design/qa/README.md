> **当前为第三轮免费音库试听**：90 个作者原音（50 Dustyroom CC0 + 40 R4orce 项目许可），报告见 [library-v3/README.md](library-v3/README.md)。以下 30 个合成样本与历史流程结果不代表第三轮音库的听感验收。

# 声音方案 · 验证边界（第二轮更新）

本轮四种庆祝与原版对比的 9 项新增专项见 [celebration-v2/README.md](celebration-v2/README.md)。共享全套 21 项在本轮重新通过；首轮页面／清单／生成器／报告归档于 `../versions/v1/`。

## 机器与浏览器检查

- `audio-report.json`：30 个 PCM16 单声道 WAV 均可解码，首尾样本均为零，无削波；最高 4 倍插值估计真峰值约 -17.98 dBFS。每个文件记录时长、RMS、峰值、首尾 1 ms 峰值、最大相邻样本差和 SHA-256。
- `browser-report.json`：由 `scripts/qa_sound_lab.cjs` 生成，本轮最终 **21 项检查通过，0 页面脚本错误**。独立 Chrome 浏览器上下文，不放宽自动播放策略；第一次真实点击解锁 AudioContext；27 个运行时样本逐一播放并等待 ended，确认节点释放。输出链分析器测到实际非零 PCM 能量。
- 预设 10 题辨音（7 对 / 3 错，含连续错误）、10 秒加速拼豆（声音限密、六变体）、真实鼠标按住与松开、Space/Enter、1.8 秒融合、单件／系列互斥庆祝均走真实 DOM 控件；所有进度只在独立页面内存。
- 实际播放原教学「安心」：中途尝试奖励音会被丢弃；示范结束不补播。跟读前提示默认关闭，开启后只播一次；2 秒跟读计时结束保持安静。静音不会改变教学音量，停止键结束整个试听。
- 事件去重、默认可选音关闭、音量滑杆键盘输入、静音、真实 AudioContext suspend/resume、销毁、独立 localStorage 偏好及减少动效模式。
- `stress-report.json`：由 `sources/check_runtime_stress.cjs` 可复现，额外独立上下文真实连续点击 16 次，限流后 1 次播放 / 15 次丢弃，结束后 0 活动节点；必要纠错反馈可以打断庆祝，普通点击不能抢占纠错。
- `page-360.png`、`page-390.png`、`page-430.png`、`page-768.png`、`page-1024.png`：响应式截图，页面无横向溢出。已检查手机与桌面布局。

`visibilitychange` 检查**通过覆盖 `document.hidden` 并派发事件模拟后台切换**，核对取消流程、立即断开音源、挂起、不补播及手势恢复。另有真正的 AudioContext suspend/resume 检查；二者不等于 iOS 锁屏或操作系统抢占的真机测试。

ego-browser 独立任务空间首次点击成功，AudioContext 为 running，23 个样本解码成功；其 `Page.captureScreenshot` 在此 Mac 超时，因此截图与完整专项走查改用独立 headless Chrome。未操作用户的 8769 训练页面或浏览器 localStorage。

## 数据保护

`protected-before.json` / `protected-after.json` 与 `protection-report.json` 保存开工、收尾的只读文件哈希。真实 `data/derived/prototype/` 的 68 个文件一致，无增删或变化；8769 首页仍返回 HTTP 200。

同期另一个已授权的标准音动画任务更新了正式前端与 calibration 文件。其变化单独记录于 `concurrent_frontend_changes`，本音效任务没有覆盖、还原或移走它们；不声称全套正式前端哈希不变。音效首轮的产品文件都在 `assets/sound-design/`，两个新辅助脚本在 `scripts/`。校音动画改动的验收归对应任务。

本试听服务本身不加载训练应用、不创建会话、不调用判题或结算接口，所有网络请求为本机 8772 的 GET。页面内只有 `pth-sound-lab-preferences-v1` 一个自身偏好键。QA 另加自己的无关 sentinel，验证它未被改写。母库只读；无数据迁移或恢复。

## 尚未完成的验收

- 用户已试听并认可原 A 基础风格；本轮新庆祝待试听，具体耳机／手机外放设备专项未确认；没有将机器峰值检查表述成“不刺耳”“不疲劳”的听觉验收。
- iOS Safari、安卓真机、锁屏、蓝牙切换与电话抢占后的恢复待正式接入阶段实测。
- 正式 APP 音效接线未开始；本轮所有训练、奖励、拼豆、作品完成流程都是独立模拟。正式接入时须在 8771 临时进度服务再走完整应用流程并运行既有 pytest 基线。
