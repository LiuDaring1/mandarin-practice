# 普通话语音系统 · P1 激励闭环（streak + 训练历史 + 作品详情）节点记录（Memory）

记录时间：2026-08-13（Asia/Shanghai）
状态：**阶段完成** —— 在前后鼻音专项原型 P0 之上完成 P1 激励闭环：连续训练天数（streak）与 streak 拼点奖励、训练历史页、作品详情页。全量 pytest **147 项通过**，ego-browser 390×844 真实走查通过。

## 一、产品策略

- P0 的「训练是本体、拼豆是积累」不动；P1 补上「坚持可见」：连续天数让训练成为每天的小习惯，历史页让每一组都有痕迹，详情页让每件作品有来龙去脉。
- 拼点经济不变（5/10/15/20 分钟 = 6/12/20/28，完整完成 +2），streak 奖励是额外的小增量（第 2 天起每天 +1，封顶 +5），不改变作品所需拼点。
- 奖励口径仍只在 achievement 模块，training 代码零改动；streak 天数由前端按本地日期从 session 历史推导，结算时传给后端。

## 二、本轮新增 / 修改

### streak 连续训练

- 配置 `achievement_config_v1.json` 的 `streak_bonus` 从占位整数 0 升级为结构化：
  `{"start_day": 2, "per_day": 1, "cap": 5}` → 第 N 天（N≥2）当天**第一组完整完成**额外 +min(5, N-1) 拼点，每天只发一次（防刷），中途退出不发。
- `achievement.py` 新增 `StreakBonus`（`from_value` 兼容旧整数直发写法 / `beads(streak_days, first_completion_today)`）；`compute_reward` 增加 `streak_days` / `first_completion_today` 参数，`Reward` 增加 `streak_days` 字段。
- 后端 `/api/achievement/settle` 的 `RewardRequest` 增加 `streak_days`（ge=0, le=36500）与 `first_completion_today`；`SessionEvent` 增加 `streak_days` / `streak_bonus_awarded`（可空，落 events.jsonl）。
- 前端 `app.js`：
  - `computeStreak()` 从 sessions 的 dayKey 集合向后走连续自然日（上限 400 防死循环）；未练今天但昨天有连续时保留天数并标 `trainedToday=false`。
  - `streakAfterToday()`：结算时计算加入今天后的天数（昨天有连续则 +1，否则 1）。
  - `finishSession` 结算前判断 `firstFullToday`（今天是否已有非早退 session），把 `streak_days` / `first_completion_today` 传给 settle；session 记录与事件都带上 `streakDays` / `streakBonus`。
  - 完成页：streak 奖励 > 0 时显示「🔥 连续训练第 N 天 · 额外 +B 拼点」胶囊。
  - 首页统计行第三格「连续训练 N 天」，今天没练时标签变「连续训练 · 今天续上」。

### 训练历史页（新视图）

- 首页顶栏「历史」入口（与「作品墙」并排两个胶囊按钮）。
- 汇总卡：训练组数 / 累计分钟 / 拼点 / 连续天数。
- 记录按 dayKey 倒序分组（日期标题「今天 · 8月13日 周四」+ 当日分钟/拼点合计）；每行：入口色点（青/橙/紫）、「前鼻音 · 10 分钟」、完成度或实际分钟、🔥streak 徽章、右侧拼点数与时间。
- 空态：「还没有训练记录，先练一组吧。」

### 作品详情页（新弹层）

- 作品墙任意卡片（含未解锁）、首页作品卡（非按钮区域）点击打开底部详情弹层。
- 状态覆盖 5 种：正在拼（当前作品）/ 已拼 X%·可继续 / 还没开始 / 已完成（第 N 件 + 完成日期 + 总训练分钟）/ 未解锁（灰色剪影 + 解锁条件）。
- 内容：大拼豆图（未解锁为剪影）、名称、分类胶囊、标语、状态胶囊、进度条（进行中）、前鼻音/后鼻音/对比分钟 + 训练组数四项统计、操作按钮（开始拼这张 / 继续拼这张 / 继续练习 / 知道了）。
- 交互：作品墙卡片点击从「立即开拼」改为「打开详情再决定」，更克制；Escape / 点遮罩 / × 关闭。
- 首页作品卡补「结余 X 拼点」提示（有余额时）。

### 其他修正

- 训练历史分组排序由「插入顺序」改为按日期倒序，避免乱序写入时顺序错乱。
- 首页作品卡百分比旁加「详情 ›」提示可点。

## 三、验证

- 全量 `pytest` **147 项通过**：`test_achievement.py` 新增结构化配置解析、按天递增/封顶、仅当日首次完整完成发放、旧整数直发兼容、非法配置拒绝 5 项；`test_prototype_app.py` 新增 settle streak 字段口径、`/api/achievement` 暴露结构化配置、事件 streak 字段可选 3 项。
- ego-browser 390×844 真实走查：
  - 新用户三选一 → 麦克风；首页三格统计（连续训练 0 天）正常；
  - 前鼻音 10 分钟真实 Session → 调试结算 +14 拼点（第 1 天无 streak），作品 0%→24%；
  - 注入前两天完整记录后重载：首页连续 2 天 +「今天续上」；后鼻音 5 分钟结算 → 当日第二次完整完成不加 streak（规则正确，+8）；
  - 重置后「今天第一组」10 分钟 → **+16 拼点**（14 + streak 2），结算页显示「🔥 连续训练第 3 天 · 额外 +2 拼点」；首页连续 3 天；
  - `data/derived/prototype/logs/events.jsonl` 落盘 `streak_days` / `streak_bonus_awarded`（1/0、3/0、3/2 三组符合口径）；
  - 训练历史页：汇总卡 3 组 / 15 分钟 / 38 拼点 / 连续 3 天；按天倒序分组、streak 徽章、时间显示正确；空态分支逻辑已检查；
  - 作品墙 → 麦克风详情（正在拼 16/58·28% + 四格统计）→ 耳机详情（还没开始）→「开始拼这张」→ 正在拼切到耳机、麦克风转「可选」；锁定件详情剪影 +「完成 1 件作品后解锁」；Escape / × 关闭正常；从麦克风详情「继续拼这张」切回，首页作品卡同步。
- 截图留档 `/tmp/pth-shots/{home,history,wall,detail}.png`（390×844）。本窗口模型无图像输入，未做视觉模型复核；语义快照（snapshotText）逐页核对无缺字/错位，视觉上沿用 P0 已验证的样式体系。

## 四、参数与复现

```bash
python -m pth_corpus prototype --data-root data --port 8766
# 浏览器打开 http://127.0.0.1:8766（建议 375/390/430px 视口）
python -m pytest   # 147 项
```

调试（训练页按 `d`）：「完成训练（测试结算）」会把实际时间记为几秒，影响今日分钟/详情分钟统计（P0 已知口径）；连训练天数可在控制台向 `pth-nasal-progress-v1` 的 sessions 注入带 `dayKey` 的历史记录后刷新验证。

## 五、已知限制 / TODO

- streak 天数存于浏览器本地（localStorage），清缓存即归零；跨设备 / 云同步为 P2。
- 训练历史上限 300 条（P0 设定）；「今天续上」提示不区分时区边缘（按本地时区，符合现有口径）。
- 作品详情未展示「每颗拼豆来自哪次训练」级别的溯源；fill_sequence 仍为 row-major；自由拼豆编辑器不做。
- 录音 / ASR / 评分 / 短句 / 商城 / 排行榜等 P2 全部不做。
- 视觉复核待有图像输入能力的模型/人工执行（截图已备好）。
