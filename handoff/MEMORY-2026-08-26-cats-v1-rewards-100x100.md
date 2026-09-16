# MEMORY · 2026-08-26 猫猫系列 100×100 资产 + 新版奖励规则落地

> 本文件是不可变更的里程碑节点（决策过程 + 验收数据）。后续改动请写 STATUS/CHANGELOG。

## 1. 背景

- 旧系统：奖励 v3（2026-08-16 设计师共识版）使用 56×56 时代的小型拼豆作品（14×11 ~ 22×12，
  56~116 颗）与旧费率（字词 6/12/20/28、句子 0.5/句、听辨当日轮次递减 + 首轮全对彩蛋、
  每日上限 100、streak 拼点加成、新手三选一、完成 1 件解锁其余）。
- 产品侧提供「首个正式系列」：猫猫系列 6 件 100×100 Webfem CSV 真值资产，并定稿
  `奖励与作品系统_新版规则_100x100基线.md`（本文实现依据，权威版本以交接包为准，
  仓库根目录同步留存）。
- 验收要求（交接包 AGENT_HANDOFF.md §7）：6 件 CSV 全部导入；背景不参与推进；白色猫毛保留；
  六件 active_bead_count = 4343/4232/3739/3871/4100/4119（合计 24404）；
  奖励基线 600/600/600 + 三练 100；旧规则（streak 拼点/日上限/辨音递减/三选一）不再出现。

## 2. 资产导入算法（写入代码的要求，勿改）

1. 校验 CSV 为 100×100、每格 `#RRGGBB`（无表头）。
2. 收集四边 396 个唯一边缘格，取出现次数最多的颜色为 background_candidate
   （并列取色值字典序最小，确定性）。
3. 从所有边缘等于该色的格子出发，**4 邻域** flood-fill → 命中格写 `null`。
4. 其余格子全部保留（含白色）；`active_bead_count = 非 null 格数`，从 grid 重算自校验。
5. **禁止写死 `#00FF00` / `#35E352`**：当前 6 张资产被 Webfem 映射为 `#35E352` 只是资产事实。

实现：`scripts/convert_webfem_csv.py`（纯标准库；CLI `--csv-dir --catalog-v1 --out --expect`；
计数不符非零退出）。CSV 真值随仓库：`src/pth_corpus/prototype_data/raw_csv/cats_v1/`。

## 3. 验收真值（导入后实测，全部吻合）

| 作品 | 背景格（flood） | active_bead_count | 颜色数（含白） |
|---|---|---|---|
| cat1 | 5657 | **4343** | 20 |
| cat2 | 5768 | **4232** | 15 |
| cat3 | 6261 | **3739** | 9 |
| cat4 | 6129 | **3871** | 21 |
| cat5 | 5900 | **4100** | 11 |
| cat6 | 5881 | **4119** | 13 |
| 合计 | — | **24404** | — |

背景色当前全部为 `#35E352`（边缘 396/396）。白色猫毛保留：cat2 #FFFFFF×60、cat3 ×3、cat4 ×6。

## 4. 新版奖励基线（achievement_config_v2.json）

- 字词 5/10 分钟 = 600/1200；句子 10/15 句 = 600/900；辨音 50/100/150 词 = 300/600/900。
- 最低有效门槛 20%：不足 20% 不发拼点、不算有效训练、不续 streak、不计三练；
  ≥20% 按真实完成比例结算（浮点，内部累计；作品推进只取整数颗）。
- 正确率与拼点彻底解绑；无辨音轮次递减、无首轮全对彩蛋。
- 今日三练（三类各完整完成一次）+100/天；今日复习清空 +100/天。
- Streak 不发拼点（只记录「连续训练 X 天」）；无每日硬上限。
- 标准完整训练日 = 1900；系列总成本 24404 ≈ 12.84 个标准训练日（约两天一件/两周一套）。

## 5. 关键决策（与用户确认）

1. 新手作品 = 保留旧「麦克风」（58 颗）固定作 onboarding（三选一废弃）；其余 5 件旧作品
   从目录移除（记录不删）。真实新手资产做好后按规则 §19 替换。
2. 本次只改 App 本体（src/pth_corpus）；beads29 生产工具（→56×56）不动，仍为历史工具。
3. 辨音「完整完成」= 该批全部判断点答完（含答错）；完成比例 = 已答判断数/目标判断数。
4. 三练与 streak 只认字词/句子/辨音三类正式训练；错题复习不计入。
5. 猫猫中文名/标语为占位（棕白/三花/灰/暹罗/橘/布偶）。
6. fill_order：确定性占位（id 派生 seed 的 Fisher–Yates 洗牌），与 grid 解耦，
   后续可替换为设计过的浮现顺序；不得被 row-major 当成最终视觉规则。

## 6. 改动清单

- 新增：`scripts/convert_webfem_csv.py`；`prototype_data/`（achievement_config_v2.json、
  artwork_catalog_v2.json、raw_csv/cats_v1/）；`tests/test_webfem_cat_assets.py`。
- 服务端：`achievement.py`（重写：AchievementConfig tiers / compute_activity_reward /
  compute_review_reward / Artwork 新 schema；删除 StreakBonus、_apply_daily_cap、
  round_rates、perfect_bonus 等旧逻辑）；`prototype_app.py`（加载 v2；RewardRequest
  discrim 改 completed_points/total_points、trio_awarded_today；旧字段 422）。
- 前端：`app.js`（档位提示、结算载荷、浮点余额+整颗入作品、100×100 SVG light 模式与动画上限、
  作品墙 = 新手作品 + 猫猫系列 X/6、熨烫完成仪式、6/6 系列庆祝、统计行、localStorage v2 迁移、
  ensureCurrentArtwork 首次固定 mic）；`index.html`（累计训练 X 天）；`styles.css`（系列头/熨烫动画）。
- 档位：`data/derived/training-generator-v2/generator_config_v2.json` allowed_duration_minutes=[5,10]；
  `training/models.py` 默认 (5,10)；前端句子档 10/15 句。
- 文档：README.md、handoff/STATUS.md、handoff/modules/rewards-achievement.md、CHANGELOG.md。

## 7. 验证结果

- `./.venv/bin/python scripts/convert_webfem_csv.py ...` → 六件真值全 OK，400 万格重生成字节一致。
- 全量 pytest：**314 通过 / 6 失败**；6 个失败均为既有环境问题
  （ffmpeg 不在 PATH：test_audio_analysis ×2；句子数据缺失：test_sentence_reading ×4），勿当回归。
- 接口抽查（新进程）：10 分钟整 = 1200、5 分钟 60% = 360、句子 10 句+三练 = 700、辨音 100 词 50% = 300、
  复习 = 100；旧辨音字段 422；word 15 分钟 400；/api/home durations=[5,10]。

## 8. 遗留 / 注意

- 改 `prototype_data/` 或 achievement/prototype_app 后**必须重启服务**（配置与目录按进程缓存）。
- 用户真实数据：localStorage `pth-nasal-progress-v1`（v2 迁移保留 sessions/旧记录）+ 服务端
  `data/derived/prototype/discrim_progress.json`；勿清空。
- 历史 session 的拼点为旧单位（未换算），历史页仅作记录展示。
- 旧 `achievement_config_v1.json` / `artwork_catalog_v1.json` 保留为历史文件，不再加载。
