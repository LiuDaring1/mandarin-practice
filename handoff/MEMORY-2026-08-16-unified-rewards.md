# MEMORY 节点：统一奖励系统（字词 / 句子 / 听辨 三模块一个拼豆管道）（2026-08-16）

> 所属任务：把三个练习模块归到同一套拼豆奖励系统。用户确认的核心口径：
> 难度梯度定价（字词最难最枯燥 > 句子 > 听辨最易）、听辨全对彩蛋 +2、
> streak 三类打卡打通（加成每天只发一次）、历史页与作品详情分类型明细一起做。

## 1. 一句话结论

三类活动现在共用一个拼豆管道（`/api/achievement/settle` + 前端 `settleActivity → applyReward`）：
字词 10 分钟 = 14 拼点（不变）、句子 10 句 = 5 拼点、听辨 11 音节全对 = 5 拼点（有错 3）；
全对彩蛋 +2、连错不二次扣拼点；每日上限 100（服务端钳制）；streak 任一类完整完成都算打卡、
加成每天只发一次；历史页分类型行 + 作品详情新增句子/听辨分钟分项。
测试 287 passed（基线 282 + 11，6 个 ffmpeg 环境失败除外）+ ego-browser 三模块走查全通过
（走查后已还原用户 localStorage 快照，未污染真实进度）。

## 2. 费率定案过程（用户拍板口径）

- 用户给定难度排序：听辨（只点不发声，最易）< 句子（有趣、要开口）< 字词（最枯燥）。
- 倒推指标：**完成一件拼豆要练几天**。现有作品 56/56/58（小）、90/104（中）、116（大）；
  目标「正常练两三天一件小作品」。每天练三类 ≈ 22–24 拼点（方案 A）→ 小件 2.4–2.6 天、
  大件 4.8–5.3 天 ✓；方案 B（25–27/天）也在区间但用户选 A 留 streak 余量。
- 定案数字（`src/pth_corpus/prototype_data/achievement_config_v1.json`，version v1→v2）：
  - sentence_rewards：beads_per_sentence 0.4、completion_bonus 1、minimum_completion_ratio 0.2
  - discrim_rewards：beads_per_correct_point 0.2、completion_bonus 1、perfect_bonus 2、
    minimum_completion_ratio 0.2
  - daily_bead_cap 100（None=关；旧配置缺省为 None，向后兼容）

## 3. 实现

- `achievement.py`：`SentenceRewardRule` / `DiscrimRewardRule`（from_dict 带默认值，旧配置可加载）、
  `ActivityReward`、`compute_sentence_reward`（整轮=round(0.4×句数)+1+streak；退出按完成比例
  ≥20% 给基础分）、`compute_discrim_reward`（整轮=round(0.2×正确)+1(+全对2)+streak；退出按
  正确音节占比 ≥20%）、`_apply_daily_cap`（total, capped）；`compute_reward`（字词）加
  `beads_earned_today` 与 `capped` 字段（关键字参数，签名向后兼容）。
- `prototype_app.py`：`RewardRequest` 扩为 `activity`（默认 word）+ 三类可选字段 +
  `beads_earned_today`；`runtime.settle_activity(request)` 三分支分发（缺字段/未知活动 400）；
  端点不变 `/api/achievement/settle`（旧请求不带 activity 照旧走字词）。
- 前端 `app.js`：
  - `beadsEarnedToday()` + `settleActivity()`；`applyReward` 泛化（meta.type 三分支记分钟，
    sessions 记录带 type + 分类摘要字段：sentenceCount / correctPoints / totalPoints / perfect）。
  - 字词 `finishSession` 补 `activity:"word"` 与 `beads_earned_today`（浏览器走查确认 +15 =
    12+完成2+streak1，与旧口径一致）。
  - 句子 `finishSentenceSession` 结算（整轮 10 句 → +5）→ 结算页奖励区；
    听辨 `settleDiscrim` 结算（全对 10/10 → +5 + ✨全对彩蛋 +2）→ 结算页奖励区。
  - streak/统计：三类 sessions 都写 dayKey/actualMinutes → 今日/累计分钟、连续天数自动含三类。
  - 历史页 `historyRow` 分类型（句子绿色行「N 句 · M 分钟」、听辨紫色行「正确 X/Y 音节 ·
    M 分钟 · ✦全对」、字词保持原样）；作品详情 stats 增「句子练习 / 听辨练习」分钟分项。
  - 顺带加固：句子/听辨入口改为点击时先拉最新数据再判断可用性（首载瞬态失败自愈）。
- 测试 `tests/test_unified_rewards.py`（11 项）：锁定方案 A 配置值、旧配置默认值、三类结算
  全量/部分/门槛/校验、每日上限钳制（三活动+旧配置无上限）、端点三分支+向后兼容+streak。

## 4. 走查结论（ego-browser 390×844，8766 真实数据）

- 字词：调试直结 10 分钟 → +15 拼点（12+2+streak1）、mic 8→23、庆祝页动画正常（向后兼容 ✓）。
- 听辨：真实 10 词全对（天明/冰箱/沉没/政界/喜人/层次/仁慈/光阴/幻灯/纱锭）→ 结算
  「+5 拼点 · ✨ 全对彩蛋 +2 拼点」；session 记录 type=discrim（correctPoints/totalPoints/perfect）；
  mic 23→28、discrimMinutes 0.8 入账；当天 streak 加成已被字词轮取走（只发一次 ✓）。
- 句子：前鼻为主 10 句（调试跳过）→ 结算「+5 拼点」；type=sentence 记录 sentenceCount 10；
  mic 28→33、sentenceMinutes 入账。
- 历史页：三类型行并存（字词/句子/听辨，含 ✦ 全对徽章）；作品详情：前鼻/后鼻/对比/
  句子练习/听辨练习/训练组数 六项明细。
- **数据保护**：走查前快照 localStorage，结束后原样还原（3 sessions / mic 8 点 / 余额 0），
  用户真实进度未污染。

## 5. 踩过的坑（给后来者）

1. 走查用的浏览器任务空间共享用户真实 localStorage —— 走查会写真实进度。必须开头快照、
   结尾还原（本节点已按此执行）。
2. 8766 服务进程重启后，新代码要重载 achievement 配置（内存缓存）——改配置/代码后记得
   重启实例（`curl /api/achievement` 看 version 字段确认）。
3. 页面首载时句子 home 出现过一次瞬态 zeros（服务新起后首个 /api/home），原因未复现；
   已把句子/听辨入口改成「点击时拉最新数据再判断可用性」自愈，勿再依赖 init 缓存做门禁。
4. 短轮（听辨 1-2 分钟）的"每分钟单价"天然偏高，费率评审要按「每轮拿多少 + 几天完成
   一件作品」倒推，不要按分钟单价比（本节点已给用户完整倒推表）。

## 6. 边界（未做）

- 拼点历史不接生成器/Profile；不写数据库，仍走 localStorage + events.jsonl；
  streak 加成不因三类分别发放（每天一次）；未做听辨连错的拼点倒扣（只奖不罚）。
- 作品点数（56–116）与三类费率均已在配置中，日后调节奏改 JSON 即可。
