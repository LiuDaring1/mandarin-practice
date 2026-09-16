# 普通话语音系统 · 前后鼻音专项 + 拼豆成就 节点记录（Memory）

记录时间：2026-08-13（Asia/Shanghai）
状态：**阶段完成** —— 按《前后鼻音专项训练App_产品训练拼豆成就与原型开发总方案 v0.2》在原型 v1 基础上完成 P0，可在本机完整走通“训练 → 拼点 → 作品 → 作品墙”。

## 一、产品策略变化

- 底层保持完整：语料、phonology-v1、Training Session Generator v2、34 个 Profile 全部保留，生成算法未改动。
- 前台极度聚焦：第一版只暴露前鼻音 / 后鼻音 / 前后鼻音对比三个入口，其余 Profile 暂不进入 UI（`PROFILE_MENU` 与 `/api/profiles` 原样保留）。
- 训练是本体，拼豆是“把看不见的练习变成看得见的积累”。

## 二、本轮新增 / 修改

### 独立 Achievement 模块（与生成器解耦）

- 新增 `src/pth_corpus/achievement.py`：`AchievementConfig`、`compute_reward`、`Artwork`（网格校验 + `fill_order`）、`load_artwork_catalog`、`unlocked_artwork_ids`。
- 配置全部外置：
  - `src/pth_corpus/prototype_data/achievement_config_v1.json`：`duration_rewards`（5→6 / 10→12 / 15→20 / 20→28）、`minimum_completion_ratio=0.2`、`completion_bonus=2`、`streak_bonus=0`（P1 预留）。
  - `src/pth_corpus/prototype_data/artwork_catalog_v1.json`：6 张作品（麦克风 58 豆 / 耳机 56 / 声波小怪 58 / 小录音机 104 / 霓虹招牌 90 / 前后鼻音双子 116），含 canvas、palette、grid、size_tier、unlock_rule、fill_sequence_mode。新用户第一次只从麦克风 / 耳机 / 声波小怪三选一；完成 1 件后解锁其余 3 件。
- 奖励口径：完整完成 = 基础 + completion_bonus；中途退出按 `completion_ratio` 四舍五入结算；低于 20% 不奖励。**拼点规则没有进入 training 代码。**

### 对比 Profile（纯数据，不重写算法）

- `training_profiles_v2.json` 新增 `front_back_nasal_contrast`：P=全量前鼻韵母、Q=全量后鼻韵母，65% cross / 35% same，复用 v2 引擎。重跑 `availability-v2`（现 34 Profile），5/10/15/20 分钟全部 OK（cross 池 1145 / same 池 2374）。

### 后端（`prototype_app.py`）

- `GET /api/home`：3 个焦点入口（含 profile_id / 拼音提示 / tone）+ 时长 + 默认时长。
- `GET /api/calibration`：an/ang、en/eng、in/ing、ian/iang、uan/uang 五组真实单字示例（零声母优先，安/昂、恩/争、因/应、烟/秧、弯/汪），音频复用 `/api/clips/{item_id}`。
- `GET /api/achievement`：奖励配置 + 作品目录；`POST /api/achievement/settle`：结算单次训练的拼点。
- `/api/events` 事件模型扩展 `actual_duration_sec / completion_ratio / beads_awarded`。
- `/api/profiles`、`/api/config`、`/api/sessions`、`/api/clips`、播放器闭环全部保持 v1 行为。

### 前端（`prototype_static/`，仍是 FastAPI + 原生 HTML/CSS/JS）

- 五个视图：首页 / 训练页 / 完成结算页 / 校音页 / 作品墙；另有首次三选一、选择下一张两个底部弹层。
- 首页：品牌标语“听清 · 分清 · 读准”、今日 / 累计训练时长、三个训练入口（青 / 橙 / 紫）、5/10/15/20 分钟、开始按钮、正在拼作品卡（进度 + “再练 X 分钟 预计 +N 拼点”）、校音入口、作品墙入口。
- 训练页保持克制：汉字 / 拼音 / 状态 + 顶部细进度条（拼豆端点）；只有重播、暂停 / 继续、退出；隐藏调试面板新增“完成训练（测试结算）”。
- 完成页：+N 拼点、作品填充动画（逐豆 70ms）、`55% → 76%` 进度变化；作品完成进入庆祝态（第 N 件、训练分钟数）→ 收进作品墙 / 选择下一张。
- 校音页：成对拼豆音卡，每组 A / B / A→B / B→A 播放，播放中卡片高亮。
- 作品墙：正在拼 / 可选 / 已完成 / 未解锁（灰色剪影 + 锁）。
- 本地持久化 `localStorage["pth-nasal-progress-v1"]`：当前作品、各作品进度（前鼻/后鼻/对比分钟、总分钟、session 数）、结余拼点、session 历史；今日 / 累计按本地日期计算。
- 视觉：Modern Perler-Bead 风格——暖纸底色、圆润塑料豆（高光 + 中心孔 + 阴影 + 描边）、拼豆只用于作品 / 进度 / 奖励 / 图标；无玻璃态、无大量渐变、正文用系统无衬线。

## 三、验证

- 全量 `pytest` **139 项通过**（新增 `tests/test_achievement.py` 6 项 + 原型接口新用例：focus home、calibration 解析、achievement/settle、扩展事件字段）。
- ego-browser 390×844 真实走查完整闭环：
  - 首次三选一 → 选麦克风 → 前鼻音 10 分钟 → 真实 Session（词“公案/典/纹…”）→ 自动听读循环、计时、暂停冻结、继续、重播、退出；
  - 调试“完成训练”结算 +14 拼点（10 分钟 = 12 + 完成 bonus 2），作品 0% → 24%；
  - 20 分钟两轮 → 麦克风完成 → 庆祝页 → 选择下一张（5 张可选）→ 小录音机承接结余拼点；
  - 前后对比入口真实生成（首词“商人 shāngrén”跨组词）；后鼻音 5 分钟中途退出练 2 分钟 → +2 拼点（30.2% × 6 四舍五入）；
  - 校音页 5 组音卡 A / A→B 真实音频播放；作品墙“正在拼 / 可选 / 已完成 / 未解锁”分区正确；
  - 事件日志 `data/derived/prototype/logs/events.jsonl` 落盘含 completion_ratio / beads_awarded。
- 首页 / 完成页 / 作品墙截图经视觉模型复核：无文字溢出、层级清晰、现代萌系但非儿童风。

## 四、参数与复现

```bash
python -m pth_corpus prototype --data-root data --port 8766
# 浏览器打开 http://127.0.0.1:8766（建议 375/390/430px 视口）
python -m pytest   # 139 项
```

调试面板（训练页按 `d` 或点右上小圆点）：
- “完成训练（测试结算）”直接走完整结算，方便快速验证拼豆闭环；
- 节奏参数（extra_follow_sec / min_follow_sec / transition_sec）仍可调并存 localStorage。

清空用户进度重走首次三选一：浏览器控制台 `localStorage.removeItem("pth-nasal-progress-v1")` 后刷新。

## 五、已知限制 / TODO（未实现，按文档边界保留）

- 拼豆作品为 6 张代码定义的占位网格（无自由拼豆编辑器）；fill_sequence 目前统一 row-major，后续可换“轮廓优先”等模式。
- 今日 / 累计以本地时区日期结算；连续训练天数（streak）、训练历史页、作品详情为 P1，`streak_bonus` 已在配置中预留。
- 录音 / ASR / 评分 / 短句 / 云同步 / 商城 / 排行榜等 P2 全部不做。
- “实际练了 X 分钟”按真实流逝时间，符合文档口径；调试“完成训练”会把完成的 10/20 分钟 Session 记为实际几秒，仅影响测试数据。
