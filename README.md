# 普通话前后鼻音练习 APP

当前版本：**v0.2.0** · [版本说明](handoff/releases/v0.2.0.md) · [GitHub 仓库](https://github.com/LiuDaring1/mandarin-practice)

字词、句子与辨音三类练习，配合猫猫拼豆奖励、六音教学动画和方案 A 音效。此仓库是代码与 agent 交接的正式入口。

**新 agent 先读 [AGENTS.md](AGENTS.md) → [现行状态](handoff/STATUS.md) → [路线图](handoff/ROADMAP.md)。** 协作与发版规则见 [CONTRIBUTING.md](CONTRIBUTING.md)。开始工作先拉取最新已推送提交，任务用独立分支或 worktree。

```bash
git clone https://github.com/LiuDaring1/mandarin-practice.git
cd mandarin-practice
uv sync --locked --extra dev
uv run pytest
```

需要 Python 3.11–3.13，音频测试需要 FFmpeg。公开仓库不包含教学语料、示范录音／视频及个人练习进度；完整 APP 的本地运行准备见 [LOCAL_DATA.md](handoff/LOCAL_DATA.md)。已具备本地数据时运行 `uv run pth-corpus prototype --data-root data --port 8769`。

**2026-10-23 当前试用精简版：** 仅散文原速跟读，字词 3／5 分钟、句子 5／10 句；本地发声检查、暂停云评测与回顾。分支 `codex/practice-simplification`，见 [精简版交接](handoff/MEMORY-2026-10-23-practice-simplification.md)。

**2026-10-23 先前换窗口交接：** 请读 [Astra 接手交接](handoff/HANDOFF-2026-10-23-astra.md)，当前最新工作在 `codex/nasal-mapping-validation`，未合并分支包含新闻／双声／连续朗读成果；鼻音自动诊断仍未启用。

以下保留项目背景与历史节点；其中维护者本机路径不适用于其他机器，克隆后以本仓库根目录为准。


> 2026-09-12：全套 UI 换新，当前工作目录固定为 `普通话语音系统-zcode`，本地预览端口 **8769**。见 [UI 换新交接](handoff/MEMORY-2026-09-12-ui-refresh.md)、[素材说明](assets/ui-refresh/README.md) 和 [现行状态](handoff/STATUS.md)。

这是一个面向校内、本地试用的普通话练习语料库工具。流程按来源发现、pilot 抓取/解析、音频分析与切片、机器 QA、人工复核和选择性修复分阶段运行；机器 QA 不替代人工判断，审核记录保持追加式。

## 来源与使用边界

候选来源是普通话学习网（`pthxx.com`）的普通话词语表一/表二页面及其试听音频。来源、页面命名和本地试用注意事项记录在 [SOURCE.md](SOURCE.md)。本仓库不包含网页、MP3、RAR 或派生音频，也不声称拥有这些内容的再分发权；仅按校内、本地试用范围处理，并应遵守来源方的版权与使用要求。

> 节点：2026-09-12 方案 A 音效已接入 APP：日常保留、四类奖励优化，11 槽／16 WAV，教学优先、默认开启；以后改清单即可替换素材。见 [音效接入交接](handoff/sound-integration-2026-09-12/README.md)，[同文件试听](http://127.0.0.1:8772/)。

> 里程碑：截至 2026-08-08，全量语料已完成下载、解析、切分、六轮机器清洗与四批人工验收，正式语料 16,156 条。完整过程与数据记录见 [handoff/MEMORY-2026-08-08.md](handoff/MEMORY-2026-08-08.md)。
> 节点：2026-09-12 最新六音标准音动画接入，并按手机反馈改为分组单画面、正常／半速均有声，见 [接入交接](handoff/MEMORY-2026-09-12-calibration-refresh.md)、[手机呈现修订](handoff/MEMORY-2026-09-12-calibration-mobile.md)。
> 节点：2026-08-08 语音特征打标 v1 完成（16,149 条可用、7 条异常隔离、验证通过），节点记录见 [handoff/MEMORY-2026-08-08-phonology-v1.md](handoff/MEMORY-2026-08-08-phonology-v1.md)。
> 节点：2026-08-08 平衡随机训练生成器 v1 完成（66 个真实 Session、自动 QA 通过），节点记录见 [handoff/MEMORY-2026-08-08-training-generator-v1.md](handoff/MEMORY-2026-08-08-training-generator-v1.md)。
> 节点：2026-08-10 应用原型第一版完成（选目标 → 选时长 → 自动听读 → 完成），节点记录见 [handoff/MEMORY-2026-08-10-prototype-v1.md](handoff/MEMORY-2026-08-10-prototype-v1.md)。
> 节点：2026-08-13 前后鼻音专项 + 拼豆成就完成（前台聚焦三入口，底层保持完整），节点记录见 [handoff/MEMORY-2026-08-13-front-back-nasal-focus.md](handoff/MEMORY-2026-08-13-front-back-nasal-focus.md)。
> 节点：2026-08-13 P1 激励闭环完成（连续训练 streak 拼点奖励 + 训练历史页 + 作品详情页），节点记录见 [handoff/MEMORY-2026-08-13-p1-streak-history-detail.md](handoff/MEMORY-2026-08-13-p1-streak-history-detail.md)。
> 节点：2026-08-14 前后鼻音专项错漏清洗闭环（人耳听检 1,346 条、排除 20 条、终验收 0.5% 达标），节点记录见 [handoff/MEMORY-2026-08-14-nasal-cleaning.md](handoff/MEMORY-2026-08-14-nasal-cleaning.md)。
> 节点：2026-08-14/15 句子练习（前后鼻音句段朗读）全链路落地并收口（50 篇朗读作品 → 688 句入选 → 582 条示范音切片 → 首页第四入口；人耳四轮迭代 69%→81%→88%→97.1% 达验收线），节点记录见 [handoff/MEMORY-2026-08-14-sentence-practice.md](handoff/MEMORY-2026-08-14-sentence-practice.md)。
> 节点：2026-08-16 听辨练习（前后鼻音逐字判断答题）落地（3,796 候选词 / 4,158 判断点 / 177 交叉词；无示范音纯看字判断、按钮随字切换、整词统一绿闪/红闪反馈、连错警报+失分、轮末结算；事件落盘 type=discrim），节点记录见 [handoff/MEMORY-2026-08-16-discrimination.md](handoff/MEMORY-2026-08-16-discrimination.md)。
> 节点：2026-08-23 听辨模块 v3 重构（主词库「轮次+固定乱序+游标」持续覆盖；词库批末趁热巩固；长期错题复习 1/3/7 天间隔重复 + 复习轮内答错复现；双卡片；0.7s 反馈 + 轻触跳过；今日复习完成 +2 拼点），交接见 [handoff/STATUS-2026-08-23.md](handoff/STATUS-2026-08-23.md)。
> 节点：2026-08-26 猫猫系列 100×100 正式资产 + 新版奖励规则落地（6 件 Webfem CSV 经边缘自动识别 + 4 邻域 flood-fill 导入：4343/4232/3739/3871/4100/4119，系列合计 24,404；奖励基线改为三类平权 600/600/600 + 三练/复习各 +100；废弃 streak 拼点、每日上限、辨音轮次递减、新手三选一；作品墙改为 新手作品 + 猫猫系列 X/6，全部明牌可选），权威规则见 `奖励与作品系统_新版规则_100x100基线.md`（交接包），转换脚本见 `scripts/convert_webfem_csv.py`，节点记录见 [handoff/MEMORY-2026-08-26-cats-v1-rewards-100x100.md](handoff/MEMORY-2026-08-26-cats-v1-rewards-100x100.md)，交接包索引见 [handoff/HANDOFF-INDEX-2026-08-26.md](handoff/HANDOFF-INDEX-2026-08-26.md)。
> 节点：2026-08-27 拼豆作品「亲手拼入」交互（结算拼点只进「待拼」，用户在详情单击/长按主动拼入，placedBeads/pendingBeads 模型 + v3 迁移）+ fill_order 改区域成块浮现（同色连通块自上而下、块内 BFS 外扩，无随机数）+ 作品详情页精简（删训练分项/继续练习）+ 未开始作品毛坯点阵轮廓，节点记录见 [handoff/MEMORY-2026-08-27-bead-placement-regional-fill.md](handoff/MEMORY-2026-08-27-bead-placement-regional-fill.md)。
> 给工具开发者的数据调用手册见 [handoff/DATA_GUIDE.md](handoff/DATA_GUIDE.md)（目录结构、数据库表、CSV 字段、API、常用代码示例）。
> 交接系统与规则见 [handoff/README.md](handoff/README.md)；现行状态总览见 [handoff/STATUS.md](handoff/STATUS.md)（唯一入口，原地更新）；每次改动见 [handoff/CHANGELOG.md](handoff/CHANGELOG.md)；各模块文档见 [handoff/modules/](handoff/modules/)。

## 环境

- Python 3.11–3.13（目标版本为 3.13）
- `uv` 管理依赖和锁文件
- 后续音频处理依赖系统 `ffmpeg`/`ffprobe`

安装依赖并运行测试：

```bash
uv sync --extra dev
uv run pytest
```

若当前环境无法访问包索引，保留 `pyproject.toml`，并在网络可用时生成或更新 `uv.lock`。

## CLI 入口

阶段命令入口如下（默认数据库为 `data/corpus.sqlite3`，数据根目录为 `data/`）：

```bash
python -m pth_corpus --help
python -m pth_corpus discover
python -m pth_corpus fetch
python -m pth_corpus parse
python -m pth_corpus segment
python -m pth_corpus qa --scope pilot
python -m pth_corpus sourcecheck
python -m pth_corpus review
python -m pth_corpus review --apply-adjustments
```

`qa --scope pilot` 只读检查 200 条 entries/segments、切片文件格式与哈希、时序/广告尾边界、低置信度和最新审核哈希状态，并原子写入 `data/derived/pilot_qa_report.json`。机器异常或尚未完成 200 条有效审核时返回非零退出码，报告会明确标记 `blocked_on_machine_qa` 或 `blocked_on_human_review`。

`sourcecheck` 是源数据质量预筛（只读、不修改数据库和音频）：先用 pypinyin 词典核对每个条目的“字-拼音”是否合法，再对单音节条目做基频轮廓分析，核对录音声调与拼音声调是否一致。可疑项写入 `data/derived/source_quality_report.json`（`flags` 为高置信问题，`suspicions` 为低置信待人工复核）。全量推广时应在分段完成后、人工审核前运行，用于集中排查源站的字/拼音/录音错误。

全量流程（表一 66 页 + 表二 105 页，共 17,055 条）：

```bash
python -m pth_corpus fetch --scope full --asset html
python -m pth_corpus parse --scope full
python -m pth_corpus fetch --scope full --asset audio
python -m pth_corpus segment --scope full --analyze-only
python -m pth_corpus segment --scope full
python -m pth_corpus sourcecheck --out derived/source_quality_report_full.json
python -m pth_corpus qa --scope full
python -m pth_corpus phonology
```

全量产物分别写入 `derived/full_entries.jsonl`、`derived/full_segments.jsonl`、`derived/full_segmentation_report.json`、`derived/full_audio_manifest.json`、`derived/full_qa_report.json` 和 `derived/analysis/full_analysis.json`；切片统一写入 `derived/clips-v2/`。只有每表第一页（t1-p001/t2-p001）的音频带页标题报幕，其余页直接读词；各页尾部共享同一段“欢迎光临普通话学习网”广告（约 7.15 秒），切分时自动排除。

`qa --scope full` 是全量机器 QA 门（只读）：核对 171 页抓取/解析/切片数量、17,055 条条目的文件哈希与 WAV 格式、逐页原始边界与分段报告一致、广告尾未混入切片，以及 `excluded_items` 清单文件是否完好。机器异常为 0 时 `status=passed`；人工审核状态只作统计，不阻塞机器门。

`phonology` 是全量语音特征打标（只读正式清单，不写母库）：按版本化普通话规则表把 16,156 条词条解析为音节级/词级特征，输出到 `data/derived/phonology-v1/`（`syllable_features_v1.csv`、`item_features_v1.csv`、`phonology.sqlite3`、`phonology_review_needed_v1.csv`、统计与 QA 报告）。覆盖声母/发音部位/发音方法/送气、39 韵母体系/四呼/韵头韵腹韵尾/前后鼻音、声调/轻声/儿化、“一/不”变调候选，以及全部目标音位置字段；无法可靠判断的异常项进复核队列，不做猜测。

疑似源站错误条目通过 `excluded_items` 表标记排除（`derived/excluded_items.csv` 为可恢复清单），切片移至 `derived/clips-excluded/`；审核页面/API 和 `derived/formal_corpus.csv` 只包含未排除的 16,623 条正式条目。

## 训练内容生成器 training-generator-v1

基于 phonology-v1 的 16,149 条可用 item，实现“平衡随机训练生成器”（Balanced Random Training Generator）：候选过滤 → 覆盖率状态 → 动态权重 → Top-K 加权随机 → 顺序约束 → 时间预算 → Session JSON。全程只读母库与 `phonology.sqlite3`，不重做语音打标。

```bash
# 候选池统计（真实分布 → CANDIDATE_POOL_REPORT_V1.md + candidate_pool_stats_v1.json）
python -m pth_corpus training candidate-stats --data-root data --out derived/training-generator-v1

# 单 Session 生成
python -m pth_corpus training generate \
  --profile initial_flat_retroflex --duration 10 --repetitions 1 --auto --seed 20260804 \
  --data-root data --out derived/training-generator-v1

# 批量试跑（5/10/20 分钟矩阵 + 多 seed + 自动 QA + GENERATOR_REPORT_V1.md）
python -m pth_corpus training benchmark --data-root data --out derived/training-generator-v1
```

配置与产物在 `data/derived/training-generator-v1/`：

- `training_profiles_v1.json`：训练目标 Profile（复用 phonology-v1 的 `initial_flat_retroflex`、`initial_n_l`、`final_front_back_nasal`、`final_compound`、`tone_third_tone` 等命名，新增前/后鼻音、声调、综合等 Profile）。
- `generator_config_v1.json`：Top-K、连续约束、时长参数、权重、试跑矩阵。
- `sessions/<profile_id>/<session_id>.json`：每个 Session 的完整题目、覆盖率汇总与调试信息（selection score / reason）。
- `candidate_pool_stats_v1.json`、`CANDIDATE_POOL_REPORT_V1.md`：候选池真实分布。
- `generator_stats_v1.json`、`GENERATOR_REPORT_V1.md`：批量试跑 QA、随机性重叠度与建议调整项。

Profile 通过 JSON 扩展（候选规则 + 平衡维度 + 位置维度 + 纯度目标 `purity_target_shares`，如平翘舌默认 70% 全目标词 / 30% 单目标词），新增训练目标不需要重写生成算法。第一版明确不做 UI、用户画像、语音评分与课程体系。

### v2：结构优先组合生成器（training-generator-v2）

v2 在 v1 基础上把“命中目标后平衡随机”升级为“先定义训练结构，再平衡随机”：每个 Profile 定义核心/补充/对比桶、组合矩阵与配额（如平翘对比 60% 跨组 / 40% 同组，j/q/x 70/20/10），生成时按桶配额 → pattern 缺口 → 加权 Top-K → 顺序约束 → 时间预算。

```bash
# v2 可用性矩阵（先看真实组合分布，不改生成器）
python -m pth_corpus training availability-v2 --data-root data --out derived/training-generator-v2

# v2 单 Session
python -m pth_corpus training generate-v2 \
  --profile flat_retroflex_contrast --duration 10 \
  --data-root data --out derived/training-generator-v2

# v2 首批 65 个 Session 试跑
python -m pth_corpus training benchmark-v2 --data-root data --out derived/training-generator-v2
```

v2 产物在 `data/derived/training-generator-v2/`：`training_profiles_v2.json`（29 个 Profile）、`generator_config_v2.json`、`profile_availability_v2.json` + `PROFILE_AVAILABILITY_REPORT_V2.md`、`sessions/`、`generator_stats_v2.json` + `GENERATOR_REPORT_V2.md`。调整说明见 [PLAN_V2_1_ADJUSTMENTS.md](data/derived/training-generator-v2/PLAN_V2_1_ADJUSTMENTS.md)。

使用口径：`generate-v2` 不传 `--seed` 时自动随机（每次 Session 不同）；调试可传固定 seed 复现。跨 Session 历史按 Profile 记录最近 7 天 / 最近 7 次用过的 item，生成时软避让（降权，不硬排除，候选不足时补位），历史文件在 `data/derived/training-generator-v2/history/`。

## 本地练习原型（前后鼻音专项版）

原型当前实现《前后鼻音专项训练App 总方案 v0.2》的 P0+P1：**前鼻音 / 后鼻音 / 前后鼻音对比 → 选时长 → 真实听读循环 → 完成 → 结算拼点 → 拼豆作品 → 作品墙**，加上 **连续训练天数（streak）与 streak 拼点奖励、训练历史页、作品详情页**。规则层全部复用 v2 生成器（底层 34 个 Profile 保持完整，前台只暴露 3 个入口），前端不重新实现训练生成算法。

启动（仅本机回环，默认端口 8766）：

```bash
python -m pth_corpus prototype --data-root data --port 8766
```

浏览器打开 `http://127.0.0.1:8766`（建议开发者工具切到 375 / 390 / 430px 手机视口）。

- 首页：前后鼻音专项定位（“听清 · 分清 · 读准”）、**底部三 Tab 标准 App 结构**，三个 Tab 统一为同一套「练什么 → 练多久 → 开始练习」模板——**字词**（前鼻音青 / 后鼻音橙 / 前后对比紫 三入口 + 练多久 5/10 分钟）、**句子**（前鼻为主 / 后鼻为主 / 前后都有 三档 + 练多久 10/15 句，约 4/6 分钟）、**辨音**（词库练习 50/100/150 词/轮 + 错题复习双卡，见「听辨练习」）；顶部一行小统计（今日 X 分钟 · 累计训练 X 天 · 连续 X 天），右上角「作品 / 历史」小图标入口；整页高度 = 手机一屏，不滚动。
- 音筛选：点击任一训练入口即选中并自动弹出「练哪些音」面板——前鼻音 8 个音、后鼻音 8 个音、前后对比仅 5 组天然对应（an↔ang / en↔eng / in↔ing / ian↔iang / uan↔uang；uen/üan/ün 与 ueng/iong/ong 无语料支撑，不强行配对，走单独训练入口）；默认全选，改动立即生效、至少保留一个；收窄后的范围显示在所选入口卡片内（拼音提示行变所选音），再点入口可重新调整；选择存 localStorage，生成 Session 时通过 `include_finals` 白名单传给生成器（只过滤目标音，不改 Profile 定义）。
- 训练页：汉字为主视觉、拼音次之；标准音播放 1 次 → 跟读窗口 → 自动下一条；只有重播、暂停/继续两个控制。
- 完成页：**统一拼豆结算（100×100 资产版基线）**——字词（5/10 分钟 = 600/1200）、句子（10/15 句 = 600/900）、辨音（50/100/150 词 = 300/600/900）；完成不足 20% 不发拼点（不算有效训练），≥20% 按真实完成比例结算（内部允许小数余量，作品推进只取整数颗）；正确率不影响拼点、答错不扣拼点；今日三练（三类各完整完成一次）= +100/天；今日复习清空 = +100/天；Streak 只记录持续回来（连续训练 X 天），不发拼点；无每日硬上限。三类共用同一拼豆管道与「正在拼」作品；作品完成进入「熨烫/融合」仪式 → 收藏 → 选下一张。
- 校音页：an/ang、en/eng、in/ing 三组**新版口腔剖面动画**（`prototype_static/calibration/`），手机端顶部切换三组，单画面跟随当前发音；正常／半速均有声，按 1／0.5 倍同步播放。支持单音、两个方向顺序播放、重播、停止与速度切换；16:9 完整显示，现有示范音轨保留。直达 `http://127.0.0.1:8769/?view=calibration`。
- 作品墙：**新手作品**（固定「麦克风」58 颗，负责 onboarding）+ **猫猫系列 X/6**（6 件 100×100 全部明牌可选：棕白猫 4343 / 三花猫 4232 / 灰猫 3739 / 暹罗猫 3871 / 橘猫 4100 / 布偶猫 4119，系列合计 24404）；随时可切换当前作品、进度永久保留、单一 `currentArtworkId`；点任意卡片打开作品详情（进度 / 分项分钟 / 训练组数 / 开始或继续拼）；6/6 完成后触发一次系列庆祝，系列卡永久进入完成状态。
- 训练历史页：汇总卡（训练组数 / 累计分钟 / 拼点 / 连续天数）+ 按天分组的记录列表（时长、完成度、拼点、时间、三练徽章）。
- 隐藏调试面板：训练页按 `d` 或点右上角小圆点。可调 `extra_follow_sec` / `min_follow_sec` / `transition_sec`（存 localStorage），显示 profile_id / session_id / seed / item_id / 序号 / clip 时长 / 预计题长；另有“跳过当前词”和“完成训练（测试结算）”。
- 本地记录：训练时长 / 拼豆进度 / 训练历史存浏览器 localStorage（`pth-nasal-progress-v1`）；行为事件落 `data/derived/prototype/logs/events.jsonl`（含 completion_ratio / beads_awarded）。
- 跨 Session 软避让：每次生成后按 Profile 写入 `data/derived/prototype/history/`，与规则层 7 天 / 7 次窗口一致。

拼豆成就与生成器解耦：奖励规则在 `src/pth_corpus/prototype_data/achievement_config_v2.json`（档位制 tiers：word/sentence/discrim 各档满额 + 三练/复习固定值，不写死），作品目录在 `artwork_catalog_v2.json`（mic 新手 + cat1..cat6 = 100×100 null/#HEX 网格 + fill_order；CSV 真值在 `prototype_data/raw_csv/cats_v1/`，由 `scripts/convert_webfem_csv.py` 生成并自校验）；生成器只决定“练什么”，成就系统决定“奖励多少、拼什么”。streak 天数由前端按「有效训练日」（三类任一 ≥20%）从训练历史推导，结算时把 `streak_days` 传给 `/api/achievement/settle`（只回显展示，不发拼点），奖励口径仍只存在于 achievement 模块。

实现说明：规格中的 React + Tailwind + shadcn/ui 为建议技术栈；本机为离线环境，原型采用项目已有的 FastAPI + 原生 HTML/CSS/JS（零构建、无 CDN 依赖），P0/P1 功能与视觉纪律等价，后续如需 React 化可按现有 API 直接替换前端。

测试：`python -m pytest tests/test_prototype_app.py tests/test_achievement.py`（接口级，含真实 v2 生成、音频路由、奖励结算、streak 奖励口径、音筛选与作品目录校验）。

## 句子练习（前后鼻音句段朗读）

原型新增第四入口「句子练习」：从 50 篇普通话朗读作品（`新大纲普通话水平测试用朗读作品音频/`，本地材料不入 git，使用边界见 [handoff/SOURCE-sentence-reading.md](handoff/SOURCE-sentence-reading.md)）摘取全部前后鼻音密集句子（密度 ≥0.25，或 ≤25 字含 ≥4 个鼻音节；697 句入选），逐句配一一对应的示范音频切片（589 条，对齐置信度存档）。

训练闭环：句子全文逐字前鼻音青 / 后鼻音橙高亮 + 小字拼音 → 示范音播 1 遍 → 跟读窗口（1.2× 音频时长，最少 2s）→ 自动下一句 → 完成页「练了 N 句 · M 分钟 · +拼点」。练哪种句子只有三档：**前鼻为主**（前鼻音节多，须含 en/in 且按 en/in 加权抽句）、**后鼻为主**（须含 eng/ing 并按之加权）、**前后都有**（同句前后鼻对比，按 en/in/eng/ing 加权）。与 training-generator 完全解耦（不写 Profile；拼点走统一结算，不写 Profile）。

语料管线（`src/pth_corpus/sentence_reading.py` + `sentence` CLI；whisper 转写用 `/opt/miniconda3/bin/python`）：

```bash
# 1) PDF → 句子库（pymupdf 在 conda 环境；无 PDF 时可用 --pages 走纯 venv 路径）
PYTHONPATH=src /opt/miniconda3/bin/python -m pth_corpus.sentence_reading extract \
  --pdf "新大纲普通话水平测试用朗读作品音频/新大纲普通话水平测试朗读作品50套.pdf" \
  --audio-dir "新大纲普通话水平测试用朗读作品音频" --out data/derived/sentence-practice-v1
# 2) 拼音 / 前后鼻音指标 + 筛选（阈值 --min-density 等可调）
python -m pth_corpus sentence score --out data/derived/sentence-practice-v1
# 3) whisper 转写（4 路并行；MP4 自动 ffmpeg 抽音轨，ffmpeg 需在 PATH）
PATH="/opt/homebrew/bin:$PATH" /opt/miniconda3/bin/python tools/whisper_sentence_transcribe.py --data-root data --workers 4
# 4) 字符级滑动窗口 + 双通道相似度 + 句序单调对齐（置信度分级，低置信进复核队列）
python -m pth_corpus sentence align --out data/derived/sentence-practice-v1
# 5) ffmpeg 切分（前后 0.3s 缓冲）+ 机器 QA（时长/静音/哈希/区间单调）+ 30 句抽样
PATH="/opt/homebrew/bin:$PATH" python -m pth_corpus sentence cut \
  --out data/derived/sentence-practice-v1 --audio-dir "新大纲普通话水平测试用朗读作品音频"
python -m pth_corpus sentence status --out data/derived/sentence-practice-v1
```

产物在 `data/derived/sentence-practice-v1/`（不入 git）：`articles.jsonl` / `sentences.jsonl` / `sentences_scored.csv` / `polyphones.csv`（多音字清单）/ `transcripts/` / `alignment/`（aligned.jsonl + alignment_review.csv 复核队列）/ `clips/` + `clip_manifest.json` / `qa_report.json` / `qa_sample_30.csv` + `qa_human_checklist.csv`（人耳听检清单）。

后端：`GET /api/sentence/home`、`POST /api/sentence/session`（加权随机抽句，`filter=all|front|back|mixed`）、`GET /api/sentence/clips/{id}`、`POST /api/sentence/events`（type=sentence 落盘）。测试：`python -m pytest tests/test_sentence_reading.py tests/test_sentence_endpoints.py`。

人耳听检页（待听清单 + 键盘判定 + 断点续判；`--batch alignment` 切低置信复核队列）：

```bash
python -m pth_corpus sentence-review --data-root data --port 8768   # 打开 http://127.0.0.1:8768
```

## 听辨练习（前后鼻音逐字判断）

「辨音」模块第二张卡「听辨练习」：从正式字词表（`item_features_available` 视图，自动过滤已排除条目）提取含 en / eng / in / ing 音节的词，做成**逐字判断答题——没有任何示范音**，纯看字判断。实测池子：3,796 候选词 / 4,158 判断点（每词 1.10 个）/ 177 个交叉词（同词两对都出现，如「本领」en + ing）。

交互闭环：词大字显示、无拼音 → 每个待判断字下方留空位、横杠光标指在当前字 → 底部【前鼻 / 后鼻】双按钮**随当前字的韵母对自动切换**（en/eng 对显示 en/eng，in/ing 对显示 in/ing）→ 点选后所选标签自动填到字下、横杠跳下一个判断点（单点词答一次、双点词答两次、三点词答三次）→ 整词所有判断点答完后**统一给反应**：全对绿闪 + 每个判断字标正确韵母（前鼻青 / 后鼻橙）；有错红闪警报 + 错字标红并显示正确韵母，1.6s 后自动下一词。

游戏规则（v3 持续覆盖版）：词库练习一轮 50/100/150 词（默认 50），按音节计分（每词 1–3 个判断点）；**连续整词答错 ≥2 触发警报条**「连续错了！注意：前鼻收 n、后鼻送 ng」（整轮保持显示），并从第 2 个连错词起每词扣 1 分；轮末结算页「判断正确 X / Y 音节 · 全对词 N/50 · 用时 M 秒」（有连错时追加「⚠ 连错 N 词触发警报 · 扣 P 分」「本轮得分 S / Y」）+ 拼豆结算（按词数档位 300/600/900，见「统一奖励系统」；**正确率不影响拼点，答错不扣拼点**）+ 继续词库练习 / 返回首页。行为事件落 `events.jsonl`（`type=discrim`：题数 / 音节对错 / 连错峰值 / 时长 / 拼点）。

模式不拆分：按钮随字自适应后 en/eng 与 in/ing 天然同轮交替（含 177 个交叉词），故只有一个统一入口；若日后要「侧重某对」的过滤留作后续选项。

后端（`src/pth_corpus/discrimination.py` + `prototype_app.py`）：`GET /api/discrim/home`（候选 / 判断点 / 交叉词规模）、`POST /api/discrim/session`（出题载荷只含 `char_index / char_span / pair`，**答案不下发**，服务端会话保题面）、`POST /api/discrim/answer`（逐点判定 + 正确韵母/拼音）、`POST /api/discrim/events`；`/api/home` 增 `discrim` 字段。测试：`python -m pytest tests/test_discrimination.py`（池子规则、判断点序列、载荷无答案、逐点判定、home 端点、事件落盘）。

## 统一奖励系统（字词 / 句子 / 辨音 三模块一个拼豆管道 · 100×100 资产版）

奖励系统按 2026-08-26 新版规则基线（`奖励与作品系统_新版规则_100x100基线.md`，交接包权威版本）落地：三个正式训练项目**平权**，标准档统一 600；核心原则是「拼点衡量投入，正确率指导学习」，不设防刷性惩罚。全部数值配置可调（`achievement_config_v2.json`）。

| 模块 | 计价（`achievement_config_v2.json`） | 标准档满额 |
|---|---|---|
| 字词 | 5 分钟 = **600**；10 分钟 = **1200** | 600 |
| 句子 | 10 句 = **600**；15 句 = **900** | 600 |
| 辨音 | 50 词 = **300**；100 词 = **600**；150 词 = **900** | 600 |
| 今日三练 | 当天三类各完整完成一次 → **+100**（每天一次） | +100 |
| 今日错题复习 | 清空当天待复习 → **+100**（每天一次） | +100 |
| Streak | 只记录持续回来（连续训练 X 天） | **不发拼点** |

- **≥20% 按比例结算**：完成不足 20% 不发拼点、不算有效训练；达到 20% 后按真实完成比例结算（字词=有效时间/目标时间，句子=完成句数/目标句数，辨音=完成判断数/目标判断数），内部允许小数余量（作品推进只取整数颗，防四舍五入套利）。
- **正确率与拼点解绑**：答对答错都计入真实训练，答错不扣拼点；辨音错误只进错题记录与复习；无辨音当日轮次递减、无首轮全对彩蛋。
- **无每日硬上限**：取消旧版每日 100 上限；用户愿意真实多练，就按真实投入结算。
- 标准完整训练日 = 600 + 600 + 600 + 100 = **1900 拼点**；猫猫系列真实总成本 24,404 ≈ **12.84 个标准训练日**（约两天一件、约两周一套）。
- 结算入口统一：`POST /api/achievement/settle` 带 `activity=word|sentence|discrim|review`（缺省 word 完全向后兼容）；`streak_days` 仅回显展示。
- 前端统一管道：`settleActivity → applyReward` 四类共用；结算页统一「拼豆掉落 + 正在拼作品像素点亮」动画；训练历史页分类型行（字词/句子/辨音/复习 + ✦全对/三练徽章），作品详情含「句子练习 / 听辨练习」分钟分项。
- 测试：`python -m pytest tests/test_unified_rewards.py tests/test_achievement.py tests/test_webfem_cat_assets.py`

## 前后鼻音专项错漏盘点（nasal-audit）用户实测发现前后鼻音训练里仍有“音频读的是别的词”的残存错漏。`nasal_audit` 是为此准备的机器侧盘点（只读母库/音频）：把前后鼻音盘子（9,700 条）与历史清洗信号（旧 Qwen3 ASR 低分、Qwen3 错配清单等）合并，用本地 faster-whisper base 重新听写 2,384 条嫌疑，按“双证据错词 / 错词 / 串位 / 声调 / 不可判定”分级，产出人工听检批次。

```bash
# 重听嫌疑集（需 faster_whisper，本机 /opt/miniconda3/bin/python；可 --limit 试跑）
python tools/whisper_batch.py --input /tmp/nasal_suspects.txt --out /tmp/nasal_asr_0.jsonl

# 生成盘点报告（只写 derived/nasal-audit-2026-08-13/）
python -m pth_corpus.nasal_audit --data-root data --asr /tmp/nasal_asr.jsonl --out derived/nasal-audit-2026-08-13
```

产物与清洗工作流（排除落点、验证方式）见 `handoff/HANDOFF-nasal-cleaning-2026-08-13.md`（已完成，过程记录见 `handoff/MEMORY-2026-08-14-nasal-cleaning.md`）；历史六轮清洗与人工验收见 `handoff/MEMORY-2026-08-08.md`。

清洗闭环命令（2026-08-14 新增）：

```bash
python -m pth_corpus nasal-review --data-root data --batch 01 --port 8767   # 人耳听检页（A/S/D/F/Q/X 判定，判定落 data/review/nasal_decisions_*.csv）
python -m pth_corpus nasal-clean --apply data/review/nasal_decisions_batch_01.csv --dry-run
python -m pth_corpus nasal-clean --apply data/review/nasal_decisions_batch_01.csv   # 幂等排除/重切（可 --undo / --undo-item 撤销）
python tools/verify_nasal_clean.py --data-root data   # 三入口 Session 排除混入检查 + 候选池充足性
```

Pilot 切片使用 `constrained-dp-v2-leading-announcement`：显式排除音频开头的“表一/表二”报幕区间，保留其余全部候选边界（位置 2–102），并将新 WAV 写入 `data/derived/clips-v2/`。原有 `data/derived/clips/`（v1）及源 MP3 保留不变；切片报告、JSONL 和配置会记录排除区间、候选位置、算法版本及低置信度原因。

`review` 默认启动仅绑定 loopback 的本地复核界面；`review --apply-adjustments` 不启动服务，只选择最新审核中仍匹配当前切片哈希、且有边界调整的 `approved`/`rejected`/`needs_review` 记录，严格校验原始范围后原子重切受影响 WAV 并更新 segments。修复报告写入 `data/review/pilot_repair_report.json`；没有可应用调整时为幂等的 0 条。

## 数据与数据库

`data/raw/`、`data/derived/` 和 `data/review/` 用于本地数据，均被 `.gitignore` 排除；目录中的说明文件会保留。SQLite 初始化 API 位于 `pth_corpus.db.init_db`，默认数据库路径是 `data/corpus.sqlite3`，初始迁移位于 `src/pth_corpus/migrations/001_initial.sql`。
