# MEMORY 节点：奖励系统 v2（设计师共识版落地）（2026-08-16）

> 所属任务：用户与专业游戏设计师达成共识后，把奖励系统从「统一管道 v1」调整为
> **三层结构**（单项 → 今日三练 → streak）。共识来源：
> `前后鼻音学习软件_奖励系统方案_当前共识版.md`（仓库根，用户提供）；
> 咨询简报见 `handoff/GAME-DESIGN-BRIEF-rewards-2026-08-16.md`。

## 1. 一句话结论

奖励系统升级为三层结构：**单项奖励**（字词 14 不变 / 句子 5→6 开口补偿 / 听辨改
「当日轮次递减」2/1/1/0.5，全对彩蛋 +1 仅首轮）+ **今日三练 +2**（三类各完整完成
一次，每天一次，第三项完成时即时发放）+ **streak**（规则不变，三类打卡打通）。
标准日 = 24–25 拼点，作品节奏不变；「听辨刷分」支配策略被移除（第 4 轮起平均
0.5/轮）。测试 **296 项（290 passed + 6 ffmpeg 环境失败）**；ego-browser 走查
连打 5 轮听辨 + 三练链路全通过（走查后已还原用户 localStorage 快照）。

## 2. 共识要点 → 实现映射

| 共识 | 实现 |
|---|---|
| 字词 10 分钟 = 14（主收入） | 不动（12+完成2） |
| 句子 10 句 = 6（开口补偿） | beads_per_sentence 0.4→**0.5**，完成 +1 |
| 听辨首轮 2、全对 +1 | `round_rates: [2, 1, 1]`，`perfect_bonus: 1` 仅 `discrim_round_today == 1` |
| 第 2/3 轮 1、第 4 轮起 0.5 或更低 | `tail_rate: 0.5`，**累计取整差额发放**（第 4 轮 0、第 5 轮 1、第 6 轮 0…交替，平均 0.5/轮） |
| 否决「越来越长的轮次」 | 轮长保持 10 词不动，只做边际收益递减 ✓ |
| 今日三练 +2，每天一次 | `combo_bonus: 2`；客户端上报三类完成状态 + `combo_awarded_today`，服务端判定，第三项完成时发放并落 `comboAwardedDayKey` |
| streak 保留不动 | 未改；三类完整完成都算打卡（上轮已打通） |
| 每日 100 上限 = 异常保险丝 | 保留；不加模块级硬上限/分时段 |
| 统一「豆子进入作品」表现 | 三类结算页统一 reward-burst（豆子数 = min(拼点,6)）+「正在拼」像素点亮动画（before→after）；听辨 0 拼点轮显示「今日听辨拼点已领完（前 3 轮）」 |
| 先调数字再加规则 | 全部费率在 `achievement_config_v1.json`（v3），日志含 beads/combo/round_today 供 §17 数值验证 |

## 3. 关键实现口径（决策记录）

1. **0.5/轮的取整**：拼点必须整数 → `base_beads_for_round(n)` = `int(累计(n)) − int(累计(n−1))`，
   即 0/1/0/1 交替，长期平均恰好 0.5。想直接砍到第 4 轮起 0：改 `tail_rate=0` 即可。
2. **轮次只计完整完成的轮**：退出轮不占轮次（客户端 `discrimRoundsCompletedToday()` 只数
   `type=discrim && !exitEarly`），防「退出白烧好轮次」；退出轮计价 = 该轮基础 × 正确率
   （int 向下取整，≥20% 门槛）。
3. **全对彩蛋仅首轮**：第 2 轮起全对仍显示 ✦ 视觉标记，无拼点（文档给的三种口径取最简）。
4. **三练发放时点**：第三项完成的那轮结算里即时 +2；此后当天再练显示「今日三练已完成 ·
   +2 拼点已入账」。历史行加「三练 +2」徽章。
5. **退出轮/0 拼点轮的可见性**：结算页新增「完成不足 20%，本次没有拼点」「今日听辨拼点
   已领完」两类说明，避免空白让用户以为没接上（上一轮用户反馈过的坑）。

## 4. 实现清单

- 配置：`prototype_data/achievement_config_v1.json` v2→**v3**（sentence 0.5；discrim
  round_rates/tail_rate/perfect_bonus；combo_bonus 2）。
- `achievement.py`：`DiscrimRewardRule` 重写（round_rates/tail_rate/perfect_bonus +
  `base_beads_for_round` 累计取整）；`AchievementConfig.combo_bonus`（缺省 0，旧配置可加载）；
  `Reward`/`ActivityReward` 增 `combo_bonus`；三个 compute 函数增 `combo_eligible /
  combo_awarded_today` kwarg；`compute_discrim_reward` 增 `discrim_round_today`（必传，
  <1 报错）；退出轮改「基础×正确率 int」。
- `prototype_app.py`：`RewardRequest` 增 `discrim_round_today`、三类完成状态、
  `combo_awarded_today`；`settle_activity` 用 `combo_flags()`（本次结算并入判定）；
  `SentenceEvent`/`DiscrimEvent` 增 beads_awarded/combo_bonus（听辨另加 round_today）。
- 前端 `app.js`：`completedToday(type)` / `comboAwardedToday()` / `discrimRoundsCompletedToday()`
  助手；`progress.comboAwardedDayKey`（emptyProgress 默认 null）；三类 settle 载荷带三练
  状态（听辨带轮次）；`applyReward` 记 comboBonus 并落 comboAwardedDayKey；共享
  `rewardBurstHtml`（豆子数=min(beads,6)）/`comboLineHtml`/`comboProgressHtml`/
  `artProgressHtml`；听辨结算加「已领完」提示；历史行加「三练 +2」徽章；事件带拼点字段。
- 测试 `tests/test_unified_rewards.py`（11→14 项）：配置锁定 v3 数值、轮次递减逐轮断言
  （[2,1,1,0,1,0,1,0]）、首轮彩蛋唯一性、退出轮计价、combo 触发/不重复/缺项、上限钳制
  含 combo、旧配置默认值、端点级向后兼容。

## 5. 走查结论（ego-browser 390×844，8766 v3 真实数据）

- 听辨连打 5 轮（全点前鼻乱答）：+4（首轮 2+全对1+streak1）→ +1 → +1 → **+0**
  （「今日听辨拼点已领完（前 3 轮）」）→ +1 ✓ 递减与取整口径精确。
- 字词 dbg 直结 +14；句子 skip 10 句 +8（6+三练2）并显示「✨ 今日三练达成 · +2 拼点」；
  第二组句子 +6 不再 +2（comboAwardedDayKey 生效）✓。
- 结算页三练进度（字词 ✓ / 句子 ○ / 听辨 ✓ → 已完成）、作品「正在拼」像素推进
  （14%→21%→…→74%）、历史页「三练 +2」徽章与听辨 0 拼点行「—」均正确。
- 走查前快照 localStorage、结束后精确还原（3 sessions / mic 8 点 / 余额 0）。

## 6. 数值验证与后续调优（设计师文档 §17/§18）

- 数据已就绪：`events.jsonl` 三类事件带时长/完成度/对错 + `beads_awarded/combo_bonus/
  round_today`；观察「每人每天听辨轮数、第 1/2/3/4+ 轮占比、听辨拼点占总收入比例」。
- 第二轮调优顺序：**先调数字再加规则**——听辨重复衰减 → 句子基础奖励 → 今日三练奖励 →
  作品价格；最后才考虑硬上限/分时段/模块封顶。
- 长期方向（本轮不做）：streak 后期转荣誉/收藏（边框/特效/徽章）而非印钞；作品分层
  小/中/大/特殊 + 系列/图鉴/用户自定义作品；语音质量评分接入后「完成度≠掌握度」原则。

## 7. 边界（未做）

不动作品库与价格、不加语音质量评分、不改 streak 数值、不加模块级硬上限、不做长期
收藏结构、听辨轮长保持 10 词（设计师明确否决累进轮次）。
