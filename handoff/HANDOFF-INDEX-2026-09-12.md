# 交接包索引 · 2026-09-12（路线图定稿 + 标准动画六音交付版归档）

> 包名：`普通话语音系统-交接包-2026-09-12.zip`
> 用途：把「普通话语音系统」原型最新状态 + 中期路线图（9 件事）整体交接给下一个 Agent。
> 制作：2026-09-12 · 快照来源：`/Users/baiyanglin/Desktop/后鼻音训练软件-zcode/普通话语音系统-zcode`（用户当前工作副本）。
> 上一版交接包：`普通话语音系统-交接包-2026-08-26.zip`（在 `/Users/baiyanglin/Desktop/普通话语音系统/`，索引见 `HANDOFF-INDEX-2026-08-26.md`）。

---

## 一、先看什么（阅读顺序，30 秒接上）

| 顺序 | 文件 | 干什么 |
|---|---|---|
| 1 | `README.md` | 项目大门：是什么、怎么跑、节点清单 |
| 2 | `handoff/README.md` | 交接系统规则：看哪、改哪、收工三步 |
| 3 | `handoff/STATUS.md` | **唯一现行状态总览**：模块现状、运行/测试、数据位置、待办 |
| 4 | `handoff/ROADMAP.md` | ⭐ **本次核心：中期路线图 9 件事**（用户 2026-09-12 口述定稿），第 1 件已进行中 |
| 5 | `handoff/CHANGELOG.md` | 每次改动一行（从 2026-08-23 起） |
| 6 | `动画试验/README.md` | 若先做路线图 #1：标准动画三代试验 + 六音交付版说明 |
| 7 | `handoff/modules/<模块>.md` | 按要改的模块下钻 |

## 二、项目一句话

面向校内/本地试用的普通话**前后鼻音专项训练**原型（FastAPI + 原生 JS 前端，单机回环）：
16,156 条正式语料 → 前台三 Tab（**字词 / 句子 / 辨音**）+ 校音页（标准音示范视频卡）→ 训练得**拼点** → 拼豆作品推进。

## 三、本次包相对 08-26 版的关键变化

1. **handoff/ROADMAP.md（新）**：用户口述的 9 件事定稿——①标准示范动画程序化重做（进行中）②示范音频音色替换 ③句子语料加新闻 ④去掉库存数字展示 ⑤辨音答错播词示范音 ⑥整体 UI 换皮 ⑦整体音效设计；远期 ⑧语音评测 ⑨账户与数据管理。含每件的动机/方案/验收/开放问题。
2. **动画试验/（新，178M）**：路线图 #1 的三代试验存档（代码+参数+图层素材+QA 记录），**六音 an/ang/en/eng/in/ing 交付版 MP4 已产出**（`eng_layered/series/交付/`，正常版+半速版）——下一步是用户验收 → 换声（走 #2）→ 替换校音页 `prototype_static/calibration/*.mp4`。
3. **08-27 的应用改动已包含**：拼豆「亲手拼入」交互（placedBeads/pendingBeads + v3 迁移）、fill_order 区域成块浮现、首页「今日三练」状态条与头部微调、校音页真人示范视频卡（详见 `MEMORY-2026-08-27-bead-placement-regional-fill.md` 与 CHANGELOG）。

## 四、目录结构（打了包的，剔噪后）

```
普通话语音系统-zcode/
├── README.md / SOURCE.md / pyproject.toml / uv.lock / .gitignore
├── src/pth_corpus/               # 全部产品代码（prototype_app.py、achievement.py、
│   │                             #   discrimination.py、sentence_reading.py、training/ v2 生成器…）
│   └── prototype_static/         # 前端（app.js / index.html / styles.css / calibration/*.mp4 旧校音视频）
├── scripts/convert_webfem_csv.py # 猫猫 CSV 转换+验收
├── tests/                        # 接口级测试（314 通过 / 6 个既有环境性失败）
├── data/
│   ├── corpus.sqlite3            # 母库（16,156 条）在 data/ 下
│   └── derived/                  # clips-v2 字词示范音 / sentence-practice-v1 句子切片 /
│                                 #   phonology-v1 / training-generator-v1,v2 / prototype/（用户进度+事件日志）
├── handoff/                      # ⭐ 交接体系（STATUS / ROADMAP / CHANGELOG / modules / MEMORY / 索引）
├── 动画试验/                      # ⭐ 本次新增：标准动画三代试验 + 六音交付版（README 先读）
├── 鼻韵母示范/                    # 原真人示范视频 7 个 mp4（an/ang/ang 2/en/eng/in/ing，参考素材）
├── 系统UI建议/                    # 21 张 UI 设计参考图（路线图 #6 的"皮"）
├── assets/cats_v1_preview/       # 猫猫作品预览 PNG
└── 前后鼻音学习软件_奖励系统方案_当前共识版.md   # 设计历史（旧数值已作废）
```

## 五、如何运行 / 测试

```bash
cd <解压目录>
python3 -m venv .venv && ./.venv/bin/pip install -e .          # 新机器先建环境（.venv 未打包）
./.venv/bin/python -m pth_corpus prototype --data-root data --port 8766
# 浏览器 http://127.0.0.1:8766（建议 375/390/430px 手机视口）
./.venv/bin/python -m pytest                                    # 314 通过 / 6 失败（环境，见下）
```

**6 个既有环境性失败（勿当回归）**：`ffmpeg` 不在 PATH → test_audio_analysis ×2；
句子管线数据缺失 → test_sentence_reading ×4（包内 data/derived/sentence-practice-v1 齐全时可通过）。

## 六、打包范围（剔噪表）

| 未打包 | 原因 |
|---|---|
| `.venv/`、`__pycache__/`、`.pytest_cache/`、`.DS_Store` | 环境/缓存，可重建 |
| 原根目录的 `beads29/`、`pdf_work/`、`tools/`、`新大纲…朗读作品音频/`、`data/raw/` | 原始素材/独立工具，运行时不读（切片已在 derived） |
| `eng_layered/` 的可再生产物（output v1-v3 中间帧、compare/dist、series/reference、ang_refine 等） | 由代码+素材+参数可再生；代码、图层、QA 记录、交付视频已保留在 `动画试验/` |
| `普通话语音系统-交接包-2026-08-26.zip` | 旧包，不嵌套 |

## 七、给下一个 Agent 的注意事项

- **用户真实数据勿清空**：`data/derived/prototype/discrim_progress.json`（听辨游标与错题排期）、浏览器 localStorage（`pth-nasal-progress-v1` 等）；走查仪式见 `handoff/README.md`（改状态文件先备份，走查后还原+截断 events.jsonl）。
- 改 `prototype_data/*`、`achievement.py`、`prototype_app.py` 后**必须重启原型服务**。
- 收工三步（硬性）：CHANGELOG 加一行 → STATUS.md 原地更新 → 大改动写 MEMORY。
- 路线图推进规则：一次一件，做完在 `handoff/ROADMAP.md` 总览表更新状态并补指针。
- 旧费率材料（`PRODUCT-REVIEW-…08-23.md`、`前后鼻音学习软件_奖励系统方案_当前共识版.md`）数值已作废，仅作背景；现行奖励权威 = 交接包 `奖励与作品系统_新版规则_100x100基线.md`（08-26 包内，规则未变）。
- 来源合规是本阶段主线：示范音（pthxx.com）、朗读作品（普通话水平测试 50 篇）、示范视频的**音轨**都在去侵权化范围（路线图 #2/#3/#1-换声步骤）。
