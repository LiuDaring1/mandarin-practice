# 普通话语音系统 · 应用原型第一版节点记录（Memory）

记录时间：2026-08-10（Asia/Shanghai）
状态：**阶段完成** —— 按《普通话训练应用原型开发规格 v0.1》完成 P0 最小闭环，可在本机真实试听验证。

---

## 一、目标与边界

- 只验证一条核心体验：打开 → 选训练目标 → 选时长 → 开始 → 听一遍 → 跟读一遍 → 自动下一条 → 一直练到结束。
- 第一版不做：账号/登录、评分、ASR、录音、云同步、上一条/下一条（默认）、每词练 2 次、目标音高亮、发音技巧、复杂设置。
- 前端不重新实现训练生成算法；Session 全部由 `pth_corpus.training.v2.generator.generate_session_v2` 实时生成。

## 二、技术决策

- 规格建议 React + Tailwind + shadcn/ui，但本机为离线环境（npm 需联网）。改用项目已有的 **FastAPI + 原生 HTML/CSS/JS（零构建、无 CDN 依赖）**，P0 功能与视觉纪律等价，后续可据同一套 API 直接 React 化。
- 前端为单页三视图（首页/训练页/完成页），移动优先，仅一个强调色（深朱红 #A6452F），无卡片堆叠、无渐变/毛玻璃/大阴影。
- 播放状态机按规格实现：`idle / loading_session / playing_reference / waiting_follow / paused / completed / error`。
- 跨 Session 历史软避让在服务端生成时落盘到 `data/derived/prototype/history/`（复用 `HistoryStore`）。

## 三、实现内容

### 后端（`src/pth_corpus/prototype_app.py`）

- `GET /api/profiles`：四类菜单（声母 10 / 韵母 13 / 声调 6 / 综合 1 = 30 个目标）+ 时长选项。
- `GET /api/config`：把 `generator_config_v2.json` 的节奏参数暴露给前端。
- `POST /api/sessions`：校验 Profile/时长 → 生成真实 v2 Session → 写历史 → 落盘到 `data/derived/prototype/sessions/`。
- `GET /api/clips/{item_id}`：从母库 segments 取路径（排除 excluded），只读、防穿越。
- `POST /api/events`：把完成/退出行为追加到 `data/derived/prototype/logs/events.jsonl`。
- 启动后后台预热（加载 16,149 items + 30 Profile 可用性矩阵），首页 `/api/health` 显示 `ready`。
- CLI：`python -m pth_corpus prototype --data-root data --port 8766`（仅 loopback）。

### 前端（`src/pth_corpus/prototype_static/`）

- 首页：类别 tabs + 训练目标列表 + 时长分段选择 + 开始练习。
- 训练页：汉字（主视觉，4 字词自动降字号）、拼音、状态文字、剩余时间；仅重播/暂停-继续两个控制；左上角 × 退出（确认对话框）。
- 完成页：目标、时长、完成字词数；再来一组（同 Profile 同时长、新随机 seed）/ 返回首页。
- 隐藏调试面板：按 `d` 或右上角小圆点打开；可调 `extra_follow_sec/min_follow_sec/transition_sec`（localStorage），显示 profile_id/session_id/seed/item_id/index/clip 时长/预计题长；含“跳过当前词”（开发试听用，不计入完成数）。

### 规则层小扩展

- 首页“综合”分类需要“日常综合练习”，但 v2 原本只有 29 个专项 Profile。新增 `general` Profile（全库候选、按声母覆盖平衡），并在 `training/v2/engine.py` 的规则 DSL 增加 `{"op": "always"}`；重跑 `availability-v2`（矩阵现为 30 Profile）。原 65 Session benchmark 报告未重跑，仍为原 29 Profile 批次。

## 四、验证结果

- 全量测试 **127 项通过**（新增 `tests/test_prototype_app.py` 8 项：菜单、配置、真实 Session 生成、历史落盘、输入校验、音频路由、事件记录、always 规则）。
- 真实数据端到端冒烟：10 分钟平翘舌 Session 生成 0.4s（预热后），WAV 可读，两次生成 seed 不同、历史软避让生效。
- ego-browser 在 390×844 视口走查：首页布局无横向溢出；训练页自动下一条（3→5→7 序号推进）、“正在播放/请跟读”状态切换、暂停冻结计时与进度、继续、重播归零、退出对话框、完成页、再来一组均正常；调试面板字段与节奏调整生效。
- 自动化发现的一个“卡住”为浏览器自动播放策略所致（合成 JS click 不算用户手势），真实点击正常；非应用缺陷。

## 五、已知限制与下一步

- 节奏参数（0.8 / 1.8 / 0.3s）仍是实验值，**需要用户真实练完 5/10 分钟校准**；调试面板已支持调整。
- 完成数只统计“跟读窗口走完”的词；调试面板“跳过当前词”不计入，属预期。
- P1 候选：每词练 2 次、上一条/下一条、进度展示、目标音高亮、更多 Profile 菜单优化、本地历史展示。
- 若做正式产品：前端可 React 化，行为记录换数据库，音频与部署边界需重新评估。

## 六、复现命令

```bash
python -m pth_corpus prototype --data-root data --port 8766
# 浏览器打开 http://127.0.0.1:8766

python -m pytest tests/test_prototype_app.py   # 原型接口测试
python -m pytest                               # 全量 127 项
```

---

## 七、2026-08-11 增补：菜单重构 + 语流音变分类

### 用户反馈（真实试听后）

1. 首页列表太长、命名不统一；希望每个菜单项同时写“音名 + 拼音”（如 双唇音（b p m））。
2. “平翘舌（不含 r）”应从菜单删除。
3. 声调里孤零零的“3-3 上声”不合理，应归入“上声变调”并放进新的“语流音变”分类。
4. 缺少“语流音变”分类：应包含轻声、儿化、一/不变调、上声变调。

### 改动

- 菜单重构（`prototype_app.py` 的 `PROFILE_MENU`）：
  - 声母：双唇音（b p m）、f / h（唇齿音 / 舌根音）、平舌音（z c s）、翘舌音（zh ch sh r）、平翘舌音对比、鼻边音（n l）、舌面音（j q x）、舌根音（g k h）、舌尖中音（d t）；移除“不含 r”。
  - 韵母：单韵母（a o e i u ü）→ 前响（ai ei ao ou）→ 中响（iao iou uai uei）→ 后响（ia ie ua uo üe）→ 复韵母综合；前鼻音基础（an en in）/扩展（ian uan uen üan ün）/综合；后鼻音基础（ang eng ing ong）/扩展（iang uang ueng iong）/综合；前后鼻音对比（en/in · eng/ing）与进阶（an/ian/uan · ang/iang/uang）。
  - 声调：阴平（ˉ）、阳平（ˊ）、上声（ˇ）、去声（ˋ）、四声综合（放最后）。
  - 新增“语流音变”：轻声、儿化、一 / 不 变调、上声变调（3-3）。
  - 综合：日常综合练习。
- 新增 3 个 v2 Profile（`training_profiles_v2.json`，现共 33 个）：
  - `neutral_focus` 轻声专项：tone 维度含 0 声调（476 条）。
  - `erhua_focus` 儿化专项：全库仅 39 条，用新 `flag_rule` 按 `has_erhua` 筛选，scarcity 放宽（max_repeat 4 / min_gap 10）。
  - `yi_bu_focus` 一/不变调：用 `flag_rule` 按 `contains_yi` / `contains_bu` 筛选（159 条）。
  - `tone_33` 更名“上声变调（3-3 连读）”，从声调分类移入语流音变。
- 规则层小扩展：`V2Profile` 新增 `flag_rule` 字段，`engine._eval_flag_rule` 支持按词条布尔标记（`has_erhua` / `contains_yi` / `contains_bu`）筛选候选；不重做生成算法。
- 重跑 `availability-v2`（33 Profile）；新增测试：菜单结构与标签、flag_rule 候选匹配。

### 验证

- 全量测试 129 项通过。
- 四个语流音变 Profile 均真实生成 5 分钟 Session：轻声 99 词 / 儿化 93 词 / 一不 90 词 / 上声变调 85 词，时长误差 ≤1%。

### 已知限制 / TODO

- “上声变调”目前只覆盖相邻 3-3（`tone_33` 候选口径），上声+非上（半上）、三上连读等更宽口径需要扩展规则后再做，先按 3-3 标记清楚。
- 儿化词库仅 39 条，10 分钟以上会有明显重复；若未来补充儿化语料可降低重复。
- “平翘舌（不含 r）”Profile 保留在规则配置中但不再进菜单（兼容历史数据）。
