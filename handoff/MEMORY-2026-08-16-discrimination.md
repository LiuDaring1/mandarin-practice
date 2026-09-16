# MEMORY 节点：听辨练习（前后鼻音逐字判断答题）（2026-08-16）

> 所属任务：「辨音」模块新增听辨练习——从正式字词表提取含 en/eng/in/ing 音节的词，
> 逐字判断前鼻/后鼻，**没有任何示范音**。本轮完成 P1 池子 → P2 后端 →
> P3 前端 → P4 测试/走查/文档。

## 1. 一句话结论

首页「辨音」模块拆成两张卡：**音卡**（原辨音页保留）+ **听辨练习**（点卡直接开题，无模式弹层）。
纯看字判断：词大字无拼音 → 横杠光标落在待判断字下 → 底部【前鼻/后鼻】按钮随当前字的韵母对
自动切换（en/eng 对 ↔ in/ing 对）→ 点选自动填入并跳下一字 → 整词判断点答完后统一反馈
（全对绿闪 + 逐字正确韵母；有错红闪 + 错字标红，1.6s 自动下一词）→ 连错 ≥2 警报条 +
失分 → 轮末结算「判断正确 X/Y 音节 · 全对词 N/10 · 用时 M 秒」。池子实测
**3,796 候选词 / 4,158 判断点 / 177 交叉词**；pytest 新增 14 项全绿
（本机 282 项 = 基线 268 + 14；沙箱环境缺 ffmpeg 有 6 项既有环境失败，与本次改动无关）；
ego-browser 390×844 真实走查两轮（全对轮 + 有错轮）全通过。

## 2. 数据底座（勘察结论，供复核）

- 来源：`data/derived/phonology-v1/phonology.sqlite3` 的 `item_features_available` /
  `syllable_features_available` 视图（自动过滤 `excluded_items`）；**不碰任何音频**。
- 筛选：词内 ≥1 个音节韵母 ∈ {en, eng, in, ing}；其他韵母（an/ang/ong…）随词展示不判断；
  交叉词允许（同词两对都出现）。
- 实测规模：候选 3,796 词；判断点 4,158（每词 1.10 个）；每词判断点数 1 点 3,435 /
  2 点 360 / 3 点 1（神经病）；交叉词 177（本领/病人/风景/技能…）；
  对别判断点 en_eng 1,876 / in_ing 2,282。
- 边界：池内有 7 个儿化词（大婶儿/把门儿/份儿/纳闷儿/嗓门儿/脖颈儿/杏儿，如 shěnr），
  韵母仍标 en/eng/in/ing，保留照考；音节字串逐条拼接恒等于词（0 例外），故判断点用
  「音节首字 0-based 位置 + 字串长度」定位（儿化字串两字）。

## 3. 关键设计（与用户确认过的口径）

1. 判断点 = 词内每个 en/eng/in/ing 音节各算一次；单点词答一次、双点两次、三点三次。
2. 反馈**按词统一给**（整词判断点答完才判定），不做逐字即时对错。
3. 服务端 judge 防作弊：出题载荷只含 `char_index / char_span / pair`；正确韵母与拼音
   只存在于服务端会话（内存 dict，上限 200 条淘汰最旧）与判定响应里。
4. 结算按音节计分；连错罚分初版规则：连续整词答错 ≥2 触发警报条（整轮保持），
   从第 2 个连错词起每词扣 1 分（`discrimination.consecutive_penalty(peak) = max(0, peak-1)`；
   JS 侧同口径 `discrimPenalty`，规则改动需两处同步）。
5. 不接拼豆/streak；事件落 `data/derived/prototype/logs/events.jsonl`（type=discrim：
   题数/音节对错/全对词/连错峰值/罚分/时长/seed）。
6. 模式不拆分：按钮随字自适应后 en/eng 与 in/ing 天然同轮交替（含 177 交叉词），
   只有一个统一入口；「侧重某对」过滤留作后续选项。

## 4. 实现

- P1 `src/pth_corpus/discrimination.py`（新文件，与清洗窗口零冲突）：
  `TARGET_FINALS`、`DiscrimPoint`（char_index/char_span/final/pinyin/pair/front）、
  `load_discrim_syllables(phonology_db)`（逐音节字/拼音/韵母，库缺失降级空拼音）、
  `build_discrim_pool(items, syllables_by_item)`、`build_quiz(pool, count, seed)`
  （无放回随机抽，载荷无答案）、`judge_answer(points, answers)`（长度/取值校验 +
  逐点 correct/final/pinyin/front）、`consecutive_penalty` + `summarize_round`。
- P2 `prototype_app.py` 增量（动手前已 git status 核对）：`PrototypeRuntime` 增
  `phonology_db` 参数（默认 `data_root/derived/phonology-v1/phonology.sqlite3`）、
  惰性缓存 `discrim_pool()`、`discrim_home/session/judge`；路由
  `GET /api/discrim/home`、`POST /api/discrim/session`（count 1–30 默认 10）、
  `POST /api/discrim/answer`（404 未知会话/词、400 长度错、422 非法取值）、
  `POST /api/discrim/events`；`/api/home` 增 `discrim` 字段。
- P3 前端（`prototype_static/`，沿用拼豆视觉）：
  - `index.html`：辨音模块两张卡（音卡 + 听辨练习，副题「en / eng · in / ing 逐字判断 ·
    已备 3,796 词」）；新 `view-discrim`（顶部进度 N/10、词卡、状态行、警报条、双答案按钮）。
  - `app.js`：`startDiscrimSession → renderDiscrimWord（逐字方块 + 判断点空位 + 横杠光标
    .dcursor）→ answerDiscrim（填标签/跳字/按钮随 pair 切换）→ judgeDiscrimWord →
    applyDiscrimFeedback（flash-green/flash-red、slot-final 前鼻 teal/后鼻 orange、
    错字 wrong-char 红标、连错计数/警报条）→ 1.6s 自动下一词 → settleDiscrim →
    renderDiscrimComplete（结算 + 连错扣分 + 再来一轮/返回首页）`；事件 type=discrim；
    提前退出显示实际答题词数。
  - `styles.css`：新增 `--red*` 色板、`.discrim-*` 全套（词卡、光标闪烁动画、
    绿闪/红闪 keyframes、警报条、答案按钮、结算卡）；双卡间距微调。
- P4 测试 `tests/test_discrimination.py`（14 项）：池子规则（目标音过滤/交叉词两对/
  三点词/char_index 序列）、拼音与字串注入与降级、出题载荷无答案 + seed 可复现、
  逐点判定（含长度/取值异常）、连错罚分与轮末汇总、真实视图型端点
  （home 规模字段 + 已排除条目不出现在题目里、session/answer/events、空池 404）。

## 5. 走查结论（ego-browser 390×844，端口 8767 实例）

- 全对轮（真实数据 10 词 12 判断点）：临终/进程/成名/进去/扎根/增加/缝/贫穷/争辩/人马
  ——en/eng/in/ing 四种答案全部出现；交叉词内光标逐字跳（进程 进→程）+ 按钮随字切换
  （in_ing ↔ en_eng）断言通过；每词绿闪 + 正确韵母青/橙标色；结算「判断正确 12/12 音节
  · 全对词 10/10」。
- 有错轮：故意错两连词 → 红闪 + 错字标红（wrong-char）+ 槽位「✗ ing」；第 2 连错后
  警报条出现并整轮保持；交叉词「分兵」半点错整词算错（第 1 点 en 正常标青、第 2 点
  ✗ ing 标红）；提前退出结算「判断正确 6/9 · 全对词 5/8 · ⚠ 连错 2 词触发警报 · 扣 1 分
  · 本轮得分 5/9」；再来一轮 / 返回首页均正常。
- 事件落盘核对：三轮 type=discrim（含连错峰值/罚分字段）正确写入 events.jsonl。
- 截图留档：/tmp/discrim-02-quiz.png、/tmp/discrim-03-settlement.png、
  /tmp/discrim-04-error-settlement.png（临时产物，未入 git）。

## 6. 踩过的坑（给后来者）

1. ego-browser 的 `click(selector)` 对本页偶尔不触发，`js('element.click()')` 稳定；
   跨 heredoc 轮的 `@N` ref 必然失效，每轮都要先 `snapshotText()` 或直接用 id/CSS 选择器。
2. 沙箱 shell 无 ffmpeg（/opt/homebrew/bin 未入 PATH）→ 6 个音频/切句测试失败是环境
   问题，非本次回归；用户环境 268 基线口径不变。
3. 儿化词的音节 `hanzi` 是两字（「婶儿」），判断点定位必须用累计字串偏移而不是
   简单 1 字 = 1 音节。
4. `pytest addopts = "-q"`，命令行再加 `-q` 会变成 `-qq` 吞掉汇总行——查结果用 `-v`
   或只看 exit code。
5. 8766 端口有既有旧代码实例在跑（本窗口不动它）；走查用的 8767 实例走完已停。
   （8-16 晚已按用户反馈重启 8766：旧实例无 /api/discrim/* 路由，新页面 + 旧接口 =
   点卡进去空屏无字，正是用户报的"没有字"。）
6. 词卡汉字用了 `<i>` 标签，浏览器默认斜体 → 中文被合成斜体（用户反馈"字是斜的"）；
   `.dch` / `.dslot` 显式 `font-style: normal` 修正。凡 `<i>` 里放真文字都必须重置。

## 7. 明确不做（边界，与计划一致）

- 无任何音频播放（用户明确：不能出现示范音）；不接拼豆/streak；不动生成器、
  34 个 Profile、音筛选与字词训练、清洗窗口文件；an↔ang 与其他韵母对不做；
  句子练习遗留项（时长选项、奖励接入）仍列后续可选。
