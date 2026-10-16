# 示范音换音色 · 剪映批处理

2026-10-16 启动。用户已实听认可剪映「口播换音色」的新闻男声、新闻女声；不再做音色筛选，不再以 TTS 重合成为主线。旧火山 API 尚未验证可开通／调用，不作为工程前置条件。

## 2026-10-16 第二轮：首批逐条检查与连续批次验证

**当前结论：可以带质检分批推进，尚不满足整库无人值守条件。** 共实际导出 4 个原始批次、2 个局部修复批次，产生 299 条候选切片；没有接入正式应用，也没有人耳或音素正确性认证。最新本地汇总：`reports/validation-round-2.json`。

| 原始批次 | 切片数 | 检查结果 | 当前候选目录 |
|---|---:|---|---|
| t1-p054 | 100 | 初版 5 个词变静音、1 处边界风险；短段重做覆盖 7 词并加保护余量后，100 条通过机器检查 | staged-edge-safe-v1/t1-p054 |
| t1-p055 | 99 | 无整词静音，99 条通过机器检查 | staged-edge-safe-v1/t1-p055 |
| t1-p056 | 90 | 「养分／养殖」漏音已补回；「摇头」仍有边界风险，邻近「邀请／摇／摇晃」词音映射待复核，4 条 hold，整批不放行 | staged-edge-safe-v1/t1-p056 |
| sentence-01-当今千里眼 | 10 | 初版 3 条强边界风险；原始时间表存在跨句／晚起点疑点，经局部原声及换声 ASR 对照、静音间隔校准候选后，10 条通过机器检查 | staged-edge-safe-v2/sentence-01-当今千里眼 |

这里的“通过”仅指完整性、静音／能量边界筛查，不能理解成全部音素经人耳验收。**原 `staged/t1-p054` 已知包含 5 条静音；句子 `edge-safe-v1` 有 3 条边界问题；均保留作失败证据，不得用于 APP。** 所有实际切片和清单仍在被忽略的本地数据目录。

- p054 原导出丢失 `t1-05366..05370`（凶、兄、兄弟两条、胸）。原声并非静音，源文件哈希匹配数据库。修复原声范围 163.2–180.6 秒，`t1-p054-repair-065-071`，时延中位数 70 ms，7 词均恢复有声。
- p056 原导出丢失 `t1-05531`、`t1-05533`；72.75 秒处 8 秒窗口相关性仅 0.3547，已被门禁拦截。修复原声范围 67.8–89.2 秒，`t1-p056-repair-028-036`，覆盖队列中的 5 词。仅在修复区间完整覆盖失败窗口且其他窗口仍通过时，允许组合暂存；原报告仍记 `stable=false`，不篡改失败事实。
- p056 的 `t1-05549` 起点仍落在发声中。相邻 4 词原始时间映射经 base／medium 局部 ASR 提示可能错位，但 ASR 也会错认孤立词，因此只登记 hold，不自动改字／改标签。`reports/t1-p056__holds.json` 已绑定导出 SHA256，audit 即使能量正常也会阻止有 hold 的整批放行。
- 句子边界改动仅在新候选：0004 的源结束 42.94→41.0 秒，0005 的源开始 42.9→42.20 秒，0007 的源开始 90.91→90.25 秒；局部 ASR 显示“反应”约 40.52 秒结束、“专家”约 42.44 秒开始、“当然”约 90.52 秒开始。相关证据在 `sentence-01-boundary-asr.json`，修正在绑定输出哈希的 `sentence-01-boundary-corrections.json`；未改正式句子清单。
- 字词主时延：p054 +85 ms、p055 +60 ms、p056 +60 ms；句子 +80 ms。候选通常加前 60 ms／后 120 ms 保护，按相邻条目的中点约束，不能靠吞进邻词消除告警。
- 机器检查覆盖全部 299 条，包含 WAV 格式、文件哈希、时长、静音、40 ms 边界相对能量；三份字词原录音哈希均与数据库 `source_pages.audio_sha256` 一致。句子与问题词的局部 ASR只作定位辅助，不是发音判定。
- 剪映异步生成结束后切换时间线，曾需要重新选中音轨／音色才显示最终效果；导出前必须看到正确文件、正确时长和“换音色 新闻女声”标签，不能只凭任务计数消失。
- 原生键入中文导出名曾漏掉中文，句子首批磁盘文件已按已确认的时间线重命名为 `sentence-01__news-female.wav` 并同步队列。新 prepare 为句子生成纯 ASCII 导出名，中文原文件名和 sentence_id 继续保留。

新增工具用法：

```bash
# 对已暂存版本逐条检查，并读取任何内容复核 hold。
../.venv/bin/python scripts/voice_conversion_batch.py --batch data/derived/voice-conversion/jianying-v1 audit --job t1-p054 --variant edge-safe-v1

# 首批修复组合的可重现参数；目标目录已存在，重复执行会拒绝覆盖。
../.venv/bin/python scripts/voice_conversion_batch.py --batch data/derived/voice-conversion/jianying-v1 cut --job t1-p054 --variant edge-safe-v1 --timing-reviewed --offset-ms 85 --head-pad-ms 60 --tail-pad-ms 120 --repair t1-p054-repair-065-071

# 句子修正必须绑定当前输出哈希，另存版本，不能覆盖旧证据。
../.venv/bin/python scripts/voice_conversion_batch.py --batch data/derived/voice-conversion/jianying-v1 cut --job sentence-01-当今千里眼 --variant edge-safe-v2 --timing-reviewed --offset-ms 80 --head-pad-ms 60 --tail-pad-ms 120 --bounds-file data/derived/voice-conversion/jianying-v1/reports/sentence-01-boundary-corrections.json
```

当前检查：11 项专项测试通过。接下来优先处理 p056 的 4 条源映射 hold、验证更短输入能否降低漏音，再扩大运行。没有开启后台续跑或全量转换。

## 启动时成果与边界（第一轮历史）

- 本地队列：171 页字词 + 50 篇句子，共 221 批、约 14.62 小时。
- 当前数据库实际过滤 `excluded_items` 后有 16,136 个带切片的字词；句子清单 582 条，共 16,718 条。此处为实际队列数，不用历史 16,156 条覆盖现库。
- 首批 `t1-p054`，使用新闻女声，完整录音导入剪映后整页处理、导出 WAV 成功。输出 44.1 kHz／双声道，260.783311 秒；原记录 260.769 秒，差约 14 毫秒。
- 11 个分布于全页的 8 秒窗口能量包络相关性 0.8191–0.9487，估计延迟 60–100 毫秒，中位数 80 毫秒；另一次错开位置的检查为 60–110 毫秒。本批以 +85 毫秒偏移切回 100 个 16 kHz／单声道 PCM WAV，时长检查通过。
- 以上仅为结构／时间检查；不等于读音正确或逐词边界已由人耳验收。暂存 manifest 的 `pronunciation_reviewed` 为 false。能量相关性不能判定前后鼻音。
- 正式应用仍使用原音库；源录音、母库、真实进度无改写。尚无无人值守剪映 UI 调度器，当前为 agent 操作 UI + 命令行处理。
- 本次专项测试：`tests/test_voice_conversion_batch.py`，7 passed；未运行全量回归，因为未修改应用运行代码。

## 本地目录与续跑

正式仓库中的 `data/derived/voice-conversion/jianying-v1/` 全部被 Git 忽略：

- `queue.json`：唯一批次清单，含绝对源路径、原始 SHA256、音色、导出名和切片映射。重跑 prepare 会拒绝覆盖，可用 status 续看。
- `inputs/`：按需复制的待导入原音。
- `exports/`：剪映导出的完整录音，命名 `<job>__news-female.wav` 或 `<job>__news-male.wav`。
- `reports/`：导出格式、总时长偏差、源／输出的局部时间对比。
- `staged/<job>/`：经偏移补偿的独立切片树和 manifest；不是正式音库。已存在的批次拒绝覆盖。

以下命令在正式仓库根目录执行，维护者现有解释器为 `../.venv/bin/python`：

```bash
# 队列已建好，后续直接检查状态；不要重新初始化。
../.venv/bin/python scripts/voice_conversion_batch.py --batch data/derived/voice-conversion/jianying-v1 status

# 为下一页准备有唯一名称的输入，并打印预期导出名。
../.venv/bin/python scripts/voice_conversion_batch.py --batch data/derived/voice-conversion/jianying-v1 stage-input --job t1-p055

# 剪映实际导出之后，检查整页及局部时间位置。
../.venv/bin/python scripts/voice_conversion_batch.py --batch data/derived/voice-conversion/jianying-v1 inspect --job t1-p055

# 本批次仅作示例，首批已完成，重复执行会拒绝覆盖。
# 后续批次必须根据各自检查结果确定 offset，不能一律填 85。
../.venv/bin/python scripts/voice_conversion_batch.py --batch data/derived/voice-conversion/jianying-v1 cut --job t1-p054 --timing-reviewed --offset-ms 85
```

初次建队列命令（已执行，留作新批次目录参考）：

```bash
../.venv/bin/python scripts/voice_conversion_batch.py --batch data/derived/voice-conversion/jianying-v1 prepare --source-data ../data --sentence-sources ../新大纲普通话水平测试用朗读作品音频
```

队列默认新闻女声，仅是本轮执行音色，不要求再做男女声比较；新闻男声亦为用户认可的可用选择。若需改下一批声音，在转换前同步任务的 `voice` 和 `export_name`，不得拿不同音色的导出冒充既有记录。

## 已实际走通的剪映 UI 路径

使用 Computer Use 读当前 UI 后操作；不得把坐标当跨版本稳定接口，不抓私有接口、不写剪映内部缓存／草稿 JSON。

1. 应用完整路径 `/Applications/VideoFusion-macOS.app`。显示名解析失败、bundle ID 有多个 helper 同名时，用完整路径连接。
2. 文件 → 新建草稿 → 确认；原草稿由剪映自动保存。本次独立草稿显示名「10月16日 (3)」，时间线02为完整第54页；原用户试听草稿未编辑。
3. Command+I 导入本批原音；文件选择器 Command+Shift+G → AX `setValue` 填路径 → Return → 导入。路径框曾出现 paste 未更新的情况，必须读回所选文件，避免导入无关资料。
4. 素材右键 →「根据选中素材新建时间线」可可靠放入完整录音。本次 drag／双击／素材 apply 的 AX 点击未成功添加，不盲目重复。
5. 选中音轨 → 换音色 → 口播换音色 → 搜索「新闻女声」→ 点准确名称（不是新闻女主播）。等待音轨「换音色处理中」消失且显示「换音色 新闻女声」。本次完成后自动播放，先暂停。
6. 导出 → 关闭视频导出，开启音频导出，格式 WAV → 标题为队列中不含扩展名的 export_name → 导出至 exports 目录 → 导出。弹窗显示会员权益 1 项，但本次未出现付费／购买步骤，直接成功；后续如出现收费页，不自行购买。
7. 以「音频导出完成」和实际文件验证成功，再调用 inspect；AX 导出路径曾一直显示 .mp4，是旧视频字段，以音频格式和磁盘文件为准。

## 接下来按顺序完成

1. 首批检查和相邻两页／一篇句子验证已做；先复核 p056 的 4 个源映射 hold。保持源母库不变，不因 ASR 提示自动改标签。
2. 针对整页漏音验证更短输入；使用逐条 QA、局部重做、持久化 hold 和版本暂存流程。后续另补人耳／音素质量验收，不能拿机器边界检查冒充。
3. 形成有界的 UI 分批执行循环，每次识别导入文件、当前音色、处理中状态、成功导出再推进；出现付费、登录、错误或用户占用时停止该批并记录，不能静默漏项。
4. 分批完成全量，汇总异常和抽检结果；当前没有后台自动续跑或定时任务。
5. 添加应用新音库映射／版本切换与回退，使用原 item_id／sentence_id；新的路径必须在后端安全 data_root 内。不能把 staged 文件树直接复制覆盖母库，也不能仅靠改文件名宣称已接入。六音动画的音轨替换另列批次，以后续需求为准。

原始录音和目标音色的使用权限需分别确认；本工程不会将教学录音、清单、导出或切片提交到公开 GitHub。
