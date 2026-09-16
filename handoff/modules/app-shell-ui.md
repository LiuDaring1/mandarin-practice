# 模块：应用外壳与 UI

> 当前：2026-09-12 全页 UI 换新。FastAPI＋原生 HTML/CSS/JS，奶油底、青／橙／紫、立体小精灵。手机优先，桌面与 Codex 右侧面板可用。训练与用户进度继续使用既有接口和存储结构。

## 页面与体验

- 三个首页：统一角色页头、作品／历史／标准音入口、今日统计与三练状态。默认选前鼻音；类型卡可调整韵母；只展示本次题量、学习进度和实际奖励，去掉题库规模。390×844 字词首页开始按钮在首屏，短屏自然滚动。
- 字词和句子：文字与拼音是真实 DOM，前鼻青、后鼻橙。播放进度取真实 audio currentTime，跟读条取已有计时 deadline，明确标注“跟读计时”；不是语音评测。保留暂停、重播、两遍句子跟读和拼音开关。
- 辨音与复习：逐字判断，前／后鼻按钮随韵母对切换；正确韵母、错字标记、连错提示同时呈现文字和颜色。词库、趁热巩固、跨天复习沿用原规则。
- 结算与作品：所有结算有统一奖励、三练和待拼反馈，以及去拼入入口。作品继续使用真实 grid 与 fill_order；单击一颗、长按加速、Space／Enter、熨烫和收藏。新手麦克风＋六件猫猫作品不变。
- 标准音：顶部 an↔ang／en↔eng／in↔ing 三组切换，每次只展示当前组的一个完整 16:9 画面，单音或顺序播放时自动跟随当前发音切画面；不再纵向堆六个视频。当前组四个播放操作和正常／半速、停止在主画面下，常见手机尺寸一屏可用。正常与半速都使用权威正常有声视频，原生 playbackRate 为 1／0.5（preservesPitch=true），同步放慢示范音和动作；不再使用静音半速素材。队列令牌隔离过期回调，换组／换速度／离页／隐藏均停止。
- 历史／弹层／异常：统一空状态、音筛选、作品选择、退出确认；弹层焦点循环、Escape 与关闭返回焦点。会话生成失败可通过重播重试。
- 主要点击区域至少 44 px；减少动态效果遵循 `prefers-reduced-motion`。390/360/430 px 及桌面都做页面和弹层横向溢出检查。

## 关键文件

| 文件 | 职责 |
|---|---|
| `prototype_static/index.html` | 8 个主要视图和公共弹层 |
| `prototype_static/styles.css` | 原有结构／真实拼豆样式保留 |
| `prototype_static/ui-theme.css` | 新视觉规范、页面布局、响应式、状态和动效覆盖 |
| `prototype_static/ui.js` | 代码绘制 SVG 图标、角色引用、阶段计时、弹层焦点 |
| `prototype_static/app.js` | 原训练逻辑及新界面连接；API 和存储键不变 |
| `prototype_static/calibration/` | 最新六音正常／半速 MP4 与 6 张新版封面；来源见 `handoff/calibration-refresh-2026-09-12/source-manifest.json` |
| `prototype_static/illustrations/` | 10 张本地透明 WebP，512 px，总约 256 KiB |
| `assets/ui-refresh/` | 原始透明 PNG、完整提示词、素材说明、尺寸与 alpha 清单 |

表中的 `prototype_static/` 位于 `src/pth_corpus/`。

## 运行和验收

真实预览：`http://127.0.0.1:8769/`。工作目录为 `普通话语音系统-zcode`，解释器为父目录 `.venv/bin/python`，运行时设置 `PYTHONPATH=src`。

自动走查先运行 `scripts/serve_ui_qa.py`，它固定使用临时进度目录并监听 8771；再用随附 Node / Playwright 运行 `scripts/qa_ui_refresh.cjs`。脚本检查隔离标记后才执行，使用空白浏览器上下文。不得把脚本改为真实 8769 地址。

现有 pytest：319 通过、1 预期跳过。浏览器检查结果、全页截图和前端改造前快照：`handoff/ui-refresh-2026-09-12/`。ego-browser 在这台 Mac 上截图接口超时，本次改用独立 headless Chrome 生成和审阅截图。

断网验收指阻断外网、本地 FastAPI 保持运行；素材、音频和视频均不依赖第三方网络。没有加入 Service Worker，不缓存或伪造训练 API。

## 后续边界

新版标准示范动画已完成接入。换声、辨音答错播示范音、语音评测和整套音效继续按 ROADMAP 分项推进。后续体验微调在这一套真实界面上继续进行。

标准音直达预览：`http://127.0.0.1:8769/?ui=2026-09-12&view=calibration`。`scripts/qa_calibration_refresh.cjs` 在独立 8771 验收服务中检查正常／半速完整播放矩阵、队列竞态、错误处理、键盘和布局；报告／截图／旧资源快照存于 `handoff/calibration-refresh-2026-09-12/`。

09-12 用户第二轮反馈的最新口径：半速也有声、分组单画面；验收与截图更新至 `handoff/calibration-mobile-2026-09-12/`。上一版 `calibration-refresh-2026-09-12/` 的“半速静音／纵向双卡”记录是初次接入历史，已被本次修订取代。
