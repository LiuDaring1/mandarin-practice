# 模块：奖励与作品（rewards-achievement）

> 给 AI 的 3 行摘要：拼豆奖励统一管道（字词/句子/辨音/复习四类活动一个 settle 入口），
> 三类平权档位制（标准档 600）+ 今日三练/复习各自 +100；拼点点亮 100×100「拼豆作品」；
> 作品墙 = 新手作品 + 猫猫系列 X/6（6 件全部明牌可选，随时切换，进度永久保留）。

## 职责

把训练活动换算成拼点，并把拼点变成可视化的像素作品进度（拼豆画），形成激励闭环。

## 现状（2026-09-12，100×100 资产版规则延续）

- 统一结算：`/api/achievement/settle` 按 `activity` 分发 word / sentence / discrim / review。
- 定价（`achievement_config_v2.json`，档位制）：字词 5/10 分钟 = 600/1200；句子 10/15 句 = 600/900；
  辨音 50/100/150 词 = 300/600/900；今日三练（三类各完整完成一次）+100/天；今日复习清空 +100/天；
  Streak 不发拼点；无每日硬上限；标准完整训练日 = 1900。
- 统一结算口径：完成不足 20% 不发拼点（不算有效训练、不续 streak、不计三练）；≥20% 按真实完成
  比例结算（浮点余量内部累计，作品推进只取整数颗）；正确率不影响拼点（辨音按「主词库已完成词数/本次词数档位」，趁热巩固和多音节判断不改变档位），无轮次递减、无全对彩蛋、无 streak 加成、无每日上限。
- 作品：`artwork_catalog_v2.json` = mic（新手，58 颗，固定 onboarding）+ cat1..cat6（猫猫系列 6 件
  100×100，4343/4232/3739/3871/4100/4119，合计 24404）；grid 为 null/#HEX 矩阵，fill_order 为
  区域成块浮现顺序（同色连通块，自上而下、块内 BFS）；无解锁规则（全部明牌可选）；
  进度权威在用户 localStorage `pth-nasal-progress-v1`（v2 迁移：sessions/旧记录保留，未知名
  currentArtworkId 回退 mic）。CSV 真值在 `prototype_data/raw_csv/cats_v1/`，转换/验收脚本
  `scripts/convert_webfem_csv.py`（边缘多数色 + 4 邻域 flood-fill，禁止写死背景色）。
- 作品渲染状态（2026-08-27 定稿）：`beadArtworkSvg(art, filledCount)` 只点亮 fill_order 前
  `filledCount` 颗；**未点亮的珠子由 CSS 渲染为毛坯底板小点**（`.bead-art .bead:not(.on)`：灰色
  #ded7c8、0.55 透明度、0.45 缩放），点亮后恢复真实颜色。三种状态：未开始 = 0 颗亮
  （毛坯点阵轮廓，看不到内容——降饱和幽灵预览方案当日试过被用户否决）；进行中 = 已拼颗数亮 +
  剩余毛坯点；完成 = 全亮全彩。作品墙卡片 / 详情弹层 / 选作品弹层 / 结算页四处统一此规则。
- 「亲手拼入」模型（2026-08-27）：作品记录 `placedBeads`（已拼入）+ `pendingBeads`（待拼）；
  结算只把整颗拼点 `earmarkPending()` 预登记给当前作品（上限=剩余空间，浮点余量留口袋），
  **不点亮、不触发完成**；用户在详情「按住拼入」（单击 1 颗 / 长按 320ms 后 rAF 连拼，
  速度随待拼量自适应：8 颗/秒起步、2.5 秒升到 ~52，大堆峰值 ~240、快拼完自动减速 +
  轻音效/震动），`placed+1 / pending-1` 严格 1:1；拼满最后一颗 → 弹层内
  熨烫仪式 → 成品庆祝（系列 6/6 庆祝在弹层内触发一次）。详情页只留作品/进度/待拼/拼入
  （训练分项与「继续练习」已删）；按钮按状态切换：按住拼入 N 颗 / 开始拼这张 / 设为当前作品 /
  去训练赚拼点 / 知道了。loadProgress v3 迁移：旧 `earnedBeads` → `placedBeads`。

09-12 UI 改造同步统一全部结算和作品页面，增加 Space／Enter 拼入支持、按下状态及焦点。浏览器全流程修复了辨音传参误用音节数的问题：旧 API 字段 `completed_points/total_points` 在当前档位制下接收主词库词数，保持既有 300/600/900 定价。详情见 `MEMORY-2026-09-12-ui-refresh.md`。

## 关键文件

| 内容 | 位置 |
|---|---|
| 计价与结算 | `src/pth_corpus/achievement.py`（`AchievementConfig` / `compute_activity_reward` / `compute_review_reward` / `Artwork`） |
| 配置 | `src/pth_corpus/prototype_data/achievement_config_v2.json`（v2：tiers + trio_bonus 100 + review_reward 100） |
| 作品目录 | `src/pth_corpus/prototype_data/artwork_catalog_v2.json`（v1 文件保留为历史，不再加载） |
| 前端 | `prototype_static/app.js`：`applyReward`（浮点余额/整颗入作品）、`beadArtworkSvg`（null/#HEX grid + fill_order，light 模式）、`renderWall`（系列分组）、历史页 `historyRow` 系列 |
| 转换/验收 | `scripts/convert_webfem_csv.py`、`tests/test_webfem_cat_assets.py` |

## 数据

- 用户进度（拼点余额/作品/会话/三练标记）在用户浏览器 localStorage `pth-nasal-progress-v1`；
  agent 使用独立浏览器上下文和临时后端进度，真实进度不需要也不应还原。
- 服务端结算本身无状态；事件落盘 `events.jsonl`（beads / trio_bonus 等）。

## 待办 / 可调口径

- `tiers` / `trio_bonus` / `review_reward` 均在配置里，改 JSON 即可。
- 作品名称/标语为占位文案（棕白猫/三花猫/灰猫/暹罗猫/橘猫/布偶猫），可直接编辑 catalog JSON
  后用转换脚本重新生成（脚本会重算计数，勿手改数字）。
- 新手作品按规则 §19 待真实新手资产后再替换（当前复用「麦克风」58 颗）。
- 里程碑：`handoff/MEMORY-2026-08-16-unified-rewards.md`（旧 v1 费率历史）、
  `handoff/MEMORY-2026-08-16-reward-v2-designer.md`、`handoff/GAME-DESIGN-BRIEF-rewards-2026-08-16.md`；
  当前权威规则 = 交接包 `奖励与作品系统_新版规则_100x100基线.md`。
