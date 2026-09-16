# MEMORY 节点：句子练习（前后鼻音句段朗读）全链路落地（2026-08-14）

> 所属任务：「句子练习」功能与语料管线。本轮完成 P0–P5 全部阶段：
> 源材料入轨 → PDF 句子库 → 拼音/前后鼻音打分筛选 → whisper 对齐切分 →
> 应用接入 → 测试/走查/文档。

## 1. 一句话结论

首页新增第四个入口卡「句子练习」：从 50 篇朗读作品（49 MP3 + 《颐和园》MP4，
50/50 全齐）摘出 **697 句**前后鼻音密集句，其中 **589 句**高置信对齐并切成示范音
WAV（前鼻青 / 后鼻橙逐字高亮、示范音 1 遍 → 2.5× 跟读窗口 → 自动下一句 →
「练了 N 句 · M 分钟」结算），pytest **254 项全绿**（基线 184 + 新增 70），
ego-browser 390×844 真实走查通过。

## 2. 数据管线（全部产物在 `data/derived/sentence-practice-v1/`，不入 git）

```bash
# P1/P2 文本底座（PDF 提取需 pymupdf → /opt/miniconda3/bin/python）
PYTHONPATH=src /opt/miniconda3/bin/python -m pth_corpus.sentence_reading extract \
  --pdf "新大纲普通话水平测试用朗读作品音频/新大纲普通话水平测试朗读作品50套.pdf" \
  --audio-dir "新大纲普通话水平测试用朗读作品音频" --out data/derived/sentence-practice-v1
.venv/bin/python -m pth_corpus sentence score --out data/derived/sentence-practice-v1
# P3 转写（faster-whisper base，4 路并行，~8 分钟；MP4 走 ffmpeg 抽音轨）
PATH="/opt/homebrew/bin:$PATH" /opt/miniconda3/bin/python tools/whisper_sentence_transcribe.py \
  --data-root data --workers 4
# P3 对齐（~1.7 分钟）+ 切分 + QA
.venv/bin/python -m pth_corpus sentence align --out data/derived/sentence-practice-v1
PATH="/opt/homebrew/bin:$PATH" .venv/bin/python -m pth_corpus sentence cut \
  --out data/derived/sentence-practice-v1 --audio-dir "新大纲普通话水平测试用朗读作品音频"
```

产物与规模：`articles.jsonl`（50 篇，全部有音频）、`sentences.jsonl`（873 句）、
`sentences_scored.csv`（697 句入选：密度 ≥0.25 或 ≤25 字含 ≥4 鼻音节，阈值可调；
基准句「世间有诸多的不平等…」已入选）、`polyphones.csv`（5,773 条多音字清单）、
`transcripts/`（50 篇 whisper 分段）、`alignment/aligned.jsonl`（741 high / 77 mid / 55 low）、
`alignment/alignment_review.csv`（82 条 mid/low 人工复核队列，含出处/区间/得分）、
`clips/`（589 个 WAV）+ `clip_manifest.json`（时长/哈希/置信度/来源区间）、
`qa_report.json`（passed；4 条高静音仅提示）、`qa_sample_30.csv` + `qa_human_checklist.csv`（36 条人耳听检清单）。

## 3. 对齐算法要点（`src/pth_corpus/sentence_reading.py`）

- 归一化（NFKC + 只留汉字）→ whisper 分段拼成**带时间戳的字符流**。
- 每句做**字符级滑动窗口模糊匹配**：字符相似度（0.35）+ 拼音相似度（0.65）双通道
  × 长度比惩罚；拼音通道吸收 whisper 的繁体/同音字/术语误听（实测拼音通道是主力，
  字符通道只做同音歧义消解）。
- 候选窗口先按「句首 2 字（字符或拼音）锚点」剪枝，锚点全落空时按句首字拼音出现
  位置探测；无候选句跳过（不阻断单调链）。
- 动态规划施加**句序单调性**（后句窗口起点/终点不早于前句）；平局规则推动重复句
  向前移动。
- 窗口确定后用 SequenceMatcher 匹配块把起止细化到**字符边缘时间**（每字按所在
  whisper 段内均分插值）：起点 = 首匹配字前边界（留 1 字余量），终点 = 末匹配字后
  边界（不含下一句粘连字符，0.3s ffmpeg 缓冲兜底）。
- 置信度分级：high ≥0.80 且长度比 ∈[0.70,1.35] 直接切；mid/low 进复核队列。

## 4. 踩过的坑（给后来者）

1. **whisper base 输出繁体**且对专业术语错得离谱（大匠无名、人生如下棋），但拼音
   通道基本不失真 → char_weight 从 0.6 降到 0.35，且候选剪枝的锚点必须走「字符或
   拼音」双判定。
2. **段级窗口对短句失效**（whisper 把多句合并进一段时，短句找不到长度合适的整段
   窗口，DP 被迫串链到错误位置）→ 改为字符级滑动窗口后，人生如下棋从全 low 变为
   20 high / 6 mid。
3. **时间边界要用字符边缘而非字符中心**，否则合并段内句尾会被截掉半字（麻雀
   0013「请不要见笑」）。
4. whisper 对 1–2s 短切片复听不可靠（14-看戏-0014「潮在涨」整段音频有语音能量但
   复听输出空/「超」）：人耳听检清单里已标注，勿据 whisper 单点证据判废。
5. 《颐和园》只有 MP4（AAC 音轨）：转写工具自动 ffmpeg 抽音轨；`ffmpeg` 必须在
   PATH（工具侧要 `PATH="/opt/homebrew/bin:$PATH"`）。

## 5. 应用接入（P4）

- 后端（`prototype_app.py`，与清洗窗口同文件、已核对其 16h 无改动后接入）：
  `GET /api/sentence/home`（总量/篇数/四类过滤计数）、`POST /api/sentence/session`
  （加权随机抽句，filter=all|front|back|mixed，无放回）、`GET /api/sentence/clips/{id}`
  （路径正则 + data_root 内解析）、`POST /api/sentence/events`（type=sentence 落
  events.jsonl）；`/api/home` 增 `sentence` 字段供第四入口显示。
- 前端（`prototype_static/`，沿用拼豆视觉）：第四入口卡 tone-green；练哪种句子弹层
  （全部/前鼻多/后鼻多/前后混合，显示各过滤计数）；训练页变体——句子全文逐字
  前鼻 teal / 后鼻 orange 高亮 + 小字拼音 + 出处《篇名》· 密度%；示范音 1 遍 →
  跟读窗口 2.5× 音频时长（≥2.5s）→ 自动下一句；控制仅重播/暂停/退出；
  结算独立完成页「练了 N 句 · M 分钟」+ 再来一组/返回首页。
- 与生成器解耦：不写 Profile、不写拼豆进度，句子库完全独立。

## 6. 测试与走查

- 人耳听检页：`src/pth_corpus/sentence_review.py` + CLI `sentence-review`
  （默认 8768 端口）：卡片列出待听清单（逐字 F/B 高亮 + 拼音 + whisper 匹配
  文本 + 机器提示），键盘 A 正确 / S 边界问题 / D 内容不对 / F 听不清 / X 待定，
  判定服务端原子落盘 `data/review/sentence_decisions_<batch>.csv`，刷新即断点
  续判；`--batch alignment` 切到 82 条低置信复核队列（无切片条目用 ffmpeg 按
  对齐区间生成预览音，缓存 previews/）。259 测试全绿（含 review 5 项）。
- **人耳第一轮（2026-08-15，36 条）**：25 正确 + 11 边界问题（0 内容错/听不清）
  → 69% 未达标。问题两类：①首/尾把邻句一个音节带进来；②短句截太短（~1s）
  掐断话头。据此做了三处修正并全量重切：
  1) `_refine_window` 时间边界改为「匹配块边缘与相邻未匹配字的中点」（不再
     整字含入前字/整字截掉末字）；
  2) 新增 `_couple_adjacent_seams`：相邻两句（置信度均 ≥mid）匹配块之间的
     未匹配字缝（0–6 字）平分给前后句，前句终点=后句起点（潮在涨→涨、麻雀
     「请不要见笑」的「笑」由此保住）；
  3) `run_cut` 切分边界：缓冲 0.3s→0.15s 并被邻句边界钳制（缝边留 0.05s），
     短句保底 1.5s（每侧最多外扩 0.35s）。
  重切后机器复听 34/36（94.4%），两条仍为短切片 whisper 不可靠项；待用户
  第二轮人耳复核（判定旧档备份 `sentence_decisions_checklist_v1_20260815.csv`）。
- **人耳第二轮（2026-08-15，37 条）**：30 正确 + 7 边界 → 81% 仍未达标。
  反馈三点：①仍有几条开头把上一句尾巴剪进来（whisper 把上句句尾听成同音字，
  如「参天→餐厅」，缝平分制把这些字的一半给了下一句）；②有一句句尾被截
  （「响着」的「着」被切掉，听感"剪太快"）；③3/6/7 字的碎片（潮在涨、
  怎么不珍惜呀、请不要见笑）"本来就不是句子"，短了必错。修正：
  1) `select_reason` 新增 `min_chars` 门槛（默认 8 字）：≤7 字碎片不再入选
     （-9 句，池 697→688）；
  2) `_couple_adjacent_seams` 从「缝平分」改为「按真实字数缺字归位」：用
     每句 char_count 与匹配块长度算缺字数，缺字的句子拿走自己缺的字
     （后句不缺→缝全归前句；前句不缺→全归后句；都缺按比例；都不缺视为
     whisper 填充音两不沾），缝上限 6→12 字；
  3) `_cut_bounds` 缓冲从「固定 0.15s + 0.05s 钳制」改为「缓冲最多占邻句
     缝隙的一半」：缝隙大缓冲全量、缝合后相邻边界只留 0.02s 起势，且永不
     越过邻句边界（顺带修掉了缝合后 prev_end+0.05 把起点推到字头之后的 bug）。
  重切后机器复听 34/34（100%）；清单 34 条待用户第三轮人耳（判定旧档备份
  `sentence_decisions_checklist_v2_20260815.csv`，三短句已从应用池剔除）。
- **人耳第三轮（2026-08-15，34 条）**：30 正确 + 4 边界 → 88%，残余误差
  "错得短了一点"——段内按字数均分的时间插值噪声（长段 ±0.2s ≈ 半个音节），
  叠加缝合后缓冲收窄到 0.02s，插值误差直接变成可闻的半截音节。修正：
  1) 转写升级**词级时间戳**（whisper word_timestamps，逐词起止，重转 50 篇
     约 20 分钟），对齐器在 transcripts 有 words 时按词内字数均分字符时间
     （精度高一个量级），无 words 自动退回段级均分；
  2) 修复 `_cut_bounds` 条件 bug：缝合后相邻边界相等（next_start==end）时
     原 `>` 判定失效、缓冲仍全量 0.15s 探进下一句 → 改为 `>=`，相等缝隙只留
     0.02s 起势。
  重切 582 条（静音提示 0 条），机器复听 34/34；清单 34 条待第四轮人耳
  （判定旧档备份 `sentence_decisions_checklist_v3_20260815.csv`）。

## 7. 收尾记录（2026-08-15 用户拍板「先维持这个状态」）

- **用户结论**：第四轮人耳「已经相对比较好了，不是完全好，先维持这个
  状态，往前做」。句子练习本体**到此收口**。- **人耳四轮历程**（同一 36/37/34 条清单，全部判定在
  `data/review/sentence_decisions_checklist_v1/v2/v3.csv` 与当前
  `sentence_decisions_checklist.csv`）：

  | 轮次 | 正确 | 边界问题 | 通过率 | 当时算法状态 |
  |---|---|---|---|---|
  | 第 1 轮 | 25/36 | 11 | 69% | 段级窗口 + 0.3s 缓冲 |
  | 第 2 轮 | 30/37 | 7 | 81% | 字符级窗口 + 缝合(平分) + 0.15s 钳制 |
  | 第 3 轮 | 30/34 | 4 | 88% | 缝合(缺字归位) + 缝隙钳制 + 8 字门槛 |
  | 第 4 轮 | **33/34** | 1 | **97.1% ✅ 达验收线（≥95%）** | + 词级时间戳 + 缝合钳制 bug 修复 |

- **唯一遗留项**：`30-小鸟的天堂-0007`（第 4 轮仍判 boundary）。诊断：
  句尾缺 1 字且下一句句首也缺 1 字（both-missing 歧义），缝合把缝给了
  本句，可能带回下句「船」的半截；句首与上句之间 1.4s 的 whisper 填充
  音缝隙未并入。属单条个案，后续如需修复：对该条手工调
  `alignment/aligned.jsonl` 的 start/end 后 `sentence cut --articles 30-小鸟的天堂`。
- **当前线上状态**：原型 8766 跑第 4 版切片（582 条 / 50 篇）；听检页 8768
  清单 34 条判定已满（33 ok / 1 boundary）。全量 pytest **263 项全绿**。
- **复现与续做**：
  - 重跑管线：`sentence extract → score → whisper_sentence_transcribe
    （默认带词级时间戳）→ align → cut`（命令见 §2，score 默认 `--min-chars 8`）。
  - 补人耳：`python -m pth_corpus sentence-review --data-root data --port 8768`。
  - 82 条 mid/low 对齐复核队列仍未处理（`alignment/alignment_review.csv`，
    听检页 `--batch alignment` 可听），是后续可选工作。
- 新增 `tests/test_sentence_reading.py`（62 项：韵母提取/断句/打分筛选/extract-score
  管线/合成对齐 fixture/切分/机器 QA/句子池/CLI）+ `tests/test_sentence_endpoints.py`
  （8 项：3 端点 + 事件 + 空库降级）。
- 全量：`PATH="/opt/homebrew/bin:$PATH" .venv/bin/python -m pytest` → 254 passed。
- ego-browser 390×844 走查通过：第四入口卡 → 筛选弹层（589/288/228/555 计数）→
  前鼻多/后鼻多/前后混合各会话 → 播放→跟读→自动下一句 → 重播/暂停/继续 →
  退出结算「1 句 · 0.9 分钟」→ 返回首页；原三入口训练流回归无碍（连年/请跟读/
  退出结算正常）。截图存 `data/derived/sentence-practice-v1/ego-screenshots/`。
- 机器侧抽查 34 条切片（30 抽样 + 4 高静音提示）whisper 复听：32/34（94.1%）；
  2 条存疑为短切片 whisper 不可靠，已列入人耳清单（`qa_human_checklist.csv` 36 行）。

## 7. 版权边界

源目录 `新大纲普通话水平测试用朗读作品音频/` 已加入 `.gitignore`；全部产物在
`data/derived/sentence-practice-v1/`（本就忽略）；源材料与产物均不入 git。来源与
50 篇清单/名称变体映射见 `handoff/SOURCE-sentence-reading.md`。仅校内本地试用。

## 8. 试用反馈调优（2026-08-15，收口后追加）

用户试用后提出四点，全部落地：

1. **「带 a 的音太多、en/in/ing/ong 少」**——数据核实：鼻音节里 a 族
   （an/ian/uan/üan/ang/iang/uang）占 51%（其中 ian 独占 15.6%、73% 的句
   子都有）；en/in/eng/ing/ong 其实充足（各 8.5–11%）；真正稀缺的是
   ün(0.9%)/ueng(0.02%)/iong(1.2%)/üan/uang/uen(各 ~2.6%)，是普通话本身
   字少。各音出现句数/音节数已随 `/api/sentence/home` 的 `final_stats`
   下发，前端选音 chip 上直接显示「N 句」。
2. **跟读等待太长**：2.5× 音频时长 → **1.2×（最少 2s）**（`enterSentenceFollow`）。
3. **分类迷糊**：预设改名+补说明——全部句子 / 前鼻为主（前鼻音节多于后鼻）/
   后鼻为主 / 前后都有（同句两种都有）；解释「全部 582 ≠ 前后都有 551」是因为
   31 句只有单一类鼻音。
4. **不能选音**：新增「**自选音**」：16 个鼻音韵母 chip（带句数），规则=
   「所选音 ≥2 个音节，或占句中鼻音 ≥1/4」（常用音保浓度、稀缺音保候选），
   选中即显示「已选 N 音 · 可练 M 句」（`POST /api/sentence/count`）；
   `POST /api/sentence/session` 支持 `include_finals`，filter 新增 `custom`。
   eg ün+iong 可练 16 句、en+in 可练 256 句。
- 测试 263→**266 项全绿**；ego-browser 走查自选流程通过（ün+iong → 自选 2 音 →
  训练页 tag「自选 2 音」→ 完成页）。

## 9. 简化与重组（2026-08-15，用户方向性反馈后）

1. **句子筛选只留三档**：前鼻为主 / 后鼻为主 / 前后都有；「全部句子」「自选音」
   从前端移除（后端 `include_finals`/`/api/sentence/count`/`final_stats` 能力保留
   在 API，随时可重新暴露）。
2. **目标音提权**（用户：an/ang 等 a 族多没关系，但 en/in/eng/ing 要多）：
   - `FILTER_TARGET_FINALS`：front→(en,in)、back→(eng,ing)、mixed→(en,in,eng,ing)；
   - `apply_filter` 增硬门槛：对应模式必须含 ≥1 个目标音（前鼻 284→224 句、
     后鼻 226→196、前后都有 551→503，剔掉纯 a 族句）；
   - `sentence_weight` 加权：权重 ×(1+2·min(目标音命中,4))，实测前鼻为主
     30 句抽样的 en/in 均值 3.2 次/句（基线 1.89，+70%）。
3. **首页重组为三大练习模块**（字词 / 句子 / 辨音）：
   - 字词 = 原三入口 + 练多久 + 开始训练（时长/拼点只属于字词模块）；
   - 句子 = 「现代文朗读」卡（新闻筹备中，卡片文案已留位置）；
   - 辨音 = 原校音页升级为模块入口，页面标题「校音」→「辨音」。
4. 测试 266→**268 项全绿**；ego-browser 走查三大模块、三档弹层、辨音页
   10 张音卡、字词训练流回归均通过。

## 10. 句子排版改版 + 辨音方向备忘（2026-08-15 晚）

- **句子排版改版**（用户：逐字方格"不像一句话"）：改为**行内流式排版**——
  整句在一个段落里自然折行，只有前鼻/后鼻字带小字拼音 + 淡色底（前鼻青 /
  后鼻橙），**白字（非鼻音）与标点不标拼音**直接排入句流；字号回到正常
  阅读字号（21–26px，行高 2.1）。
- **标注开关**：训练页图例行加「标注：开/关」按钮（localStorage 持久化，
  key `pth-sentence-highlight-v1`），关闭后整句退回纯文本（无底色无拼音），
  一键可再开。默认开。
- **辨音模块未来方向（待用户细化后实施，本轮不做）**：不只是听音卡，要做成
  判断式练习——给单字/双字词/四字词/句子，让用户判断哪些音是前鼻、哪些是
  后鼻，重点覆盖 n 与 ing 的混淆；素材与判定逻辑待议。
- 268 测试全绿；ego-browser 走查通过（流式段落、仅鼻音字标拼音 18/18、
  开关双向切换、完成页）。

## 11. 句子排版二次改版 + 两遍对比读（2026-08-15 深夜）

- **基线水平**：拼音从「字上方占位」改为**绝对定位悬浮**（bottom:100%+2px，
  不占行高），标注字与白字同基线同行高——开/关标注都是水平一行，不再波浪。
  `.sentence-chars` 加 16px 上留白给首行拼音。
- **两遍对比读**：每句流程改为 示范音 1 遍 → 跟读第 1 遍（**默认标注开**，
  状态提示「看标注」）→ 跟读第 2 遍（**默认自动关标注**，提示「不看标注」）
  → 自动下一句。手动「标注：开/关」按钮仍可随时覆盖。`state.sentencePass`
  控制遍次，跳句/重播不破坏状态。
- ego-browser 走查：标注字基线全等（bottom 全 187）、拼音悬浮不占行、
  状态序列「看标注→不看标注→下一句」连续通过；268 测试全绿。

## 12. 拼音全员上注 + 真声调符号 + 两遍流程定型（2026-08-15 深夜二改）

- **白字也标拼音**（用户反悔后拍板）：所有汉字带悬浮小字拼音，白字不加色
  （`.sc-plain`），前鼻青 / 后鼻橙照旧——整句视觉均衡。
- **真声调符号**：`hanzi_pinyin(tone_marks=True)`（pypinyin Style.TONE），
  `sentences_scored.csv` 的 pinyin_seq 改为 láng 式声调符号（已重跑
  `sentence score`，对齐/切片不受影响）；`final_from_pinyin` 增 NFD 去声调
  附加符逻辑（保留 ü 分音点 U+0308，防止 lǜ→lu）。
- **开关语义改为「拼音」**：按钮「拼音：开/关」只控制拼音显隐，前后鼻颜色
  两遍常驻（localStorage key 换 `pth-sentence-pinyin-v1`）。
- **两遍流程定型**：示范音 → 请跟读（拼音开）→ **再放一遍示范音** → 请跟读
  （拼音自动关，颜色保留）→ 下一句；状态提示统一只写「请跟读」，不再写
  「第 1/2 遍、看/不看标注」。
- 268 测试全绿；ego-browser 实测状态序列「请跟读(拼音开)→示范音(关)→
  请跟读(关)→示范音(开)→…」连续多句正确。

## 13. 细节微调（2026-08-16）

- **字距收紧**：`.sentence-chars` letter-spacing 0.03em→0.015em，`.sc-inline`
  margin/padding 微调（1px→0 / 4px→3px），第一遍读起来更紧凑。
- **第二遍改「加粗不做色分」**（用户回忆早版做法）：pass2 下 `.sc-inline`
  底色全部透明、字色统一（前后鼻与白字同为墨色），仅前后鼻字加粗
  （font-weight 720 vs 白字 400），让学习者自己在脑子里判断前鼻/后鼻；
  拼音照旧自动隐藏，字距与第一遍一致。手动「拼音：开/关」仍可覆盖。
- ego-browser 实测：第一遍鼻字带色/字距收紧；第二遍 pass2 类生效
  （no-pinyin + 统一色 rgb(38,34,27) + 鼻字 720/白字 400）；268 测试全绿。
