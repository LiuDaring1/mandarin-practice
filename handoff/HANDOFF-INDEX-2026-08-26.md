# 交接包索引 · 2026-08-26（猫猫系列 100×100 + 新版奖励规则）

> 包名：`普通话语音系统-交接包-2026-08-26.zip`
> 用途：把「普通话语音系统」原型的最新版（2026-08-26 状态）整体交接给下一个 Agent / 同事。
> 制作：2026-08-26 · 项目根：`/Users/baiyanglin/Desktop/普通话语音系统`（本包即该目录的可运行快照）。

---

## 一、先看什么（阅读顺序，30 秒接上）

| 顺序 | 文件 | 干什么 |
|---|---|---|
| 1 | `README.md` | 项目大门：是什么、怎么跑、节点清单（前因后果） |
| 2 | `handoff/README.md` | 交接系统规则：看哪、改哪、收工三步 |
| 3 | `handoff/STATUS.md` | **唯一现行状态总览**：模块现状、运行/测试、数据位置、待办 |
| 4 | `handoff/CHANGELOG.md` | 每次改动一行（从 2026-08-23 起） |
| 5 | `handoff/modules/rewards-achievement.md` | 本次改动核心模块：奖励与作品 |
| 6 | `handoff/MEMORY-2026-08-26-cats-v1-rewards-100x100.md` | **本次大节点**：决策、验收真值、改动清单、遗留 |
| 7 | 历史脉络 | `handoff/MEMORY-2026-08-08 ~ 08-23/*`（按需下钻）；本次前身 = `PRODUCT-REVIEW-rewards-artworks-2026-08-23.md`（旧费率，**数值已作废**，只当背景） |

## 二、项目一句话

面向校内/本地试用的普通话**前后鼻音专项训练**原型（FastAPI + 原生 JS 前端，单机回环）：
16,156 条正式语料（pthxx.com 来源）→ 前台三 Tab（**字词 / 句子 / 辨音**）→ 训练得**拼点** →
拼豆作品推进 → 完成→熨烫仪式→收藏 → 收齐**猫猫系列**。

## 三、本次包内最关键的 6 个数字

- 猫猫系列 6 件 100×100：**4343 / 4232 / 3739 / 3871 / 4100 / 4119**（合计 **24404**）
- 标准档统一 **600**（字词 5min=600、10min=1200；句子 10 句=600、15 句=900；辨音 50=300、100=600、150=900）
- 今日三练 **+100**/天；今日复习清空 **+100**/天；标准完整训练日 = **1900**
- 奖励与作品规则权威 = `奖励与作品系统_新版规则_100x100基线.md`（仓库根目录留存，与交接包一致）

## 四、目录结构（打了包的，剔噪后）

```
普通话语音系统/
├── README.md                     # 大门 + 节点清单（前因后果）
├── SOURCE.md / pyproject.toml / uv.lock
├── src/pth_corpus/               # 全部产品代码
│   ├── prototype_app.py          # FastAPI 原型（/api/*，静态服务）
│   ├── achievement.py            # 奖励结算 + Artwork（新 schema）
│   ├── discrim_progress.py       # 听辨 v3 状态机（主词库/复习排期）
│   ├── training/                 # v2 生成器（34 Profile）
│   ├── prototype_data/           # ⭐ 本次核心配置与资产
│   │   ├── achievement_config_v2.json   # 新版奖励配置（档位制）
│   │   ├── artwork_catalog_v2.json      # mic + cat1..cat6（100×100 grid+fill_order）
│   │   ├── raw_csv/cats_v1/*.csv        # Webfem CSV 网格真值
│   │   ├── discrim_config_v1.json       # 听辨 50/100/150 词、1/3/7 天
│   │   └── artwork_catalog_v1.json / achievement_config_v1.json  # 历史，不再加载
│   └── prototype_static/         # 前端（app.js / index.html / styles.css）
├── scripts/convert_webfem_csv.py # ⭐ 转换+验收脚本（可复跑）
├── tests/                        # 314 通过（含 test_webfem_cat_assets.py 真值回归锁）
├── data/
│   ├── corpus.sqlite3            # 母库（16,156 条）
│   └── derived/
│       ├── clips-v2/             # 字词示范音（clip_path 指向这里）
│       ├── sentence-practice-v1/ # 句子练习切片 + 清单
│       ├── phonology-v1/         # 语音特征库（辨音词库源）
│       ├── training-generator-v2/# 生成器配置/Profile/历史
│       └── prototype/            # 听辨用户进度（勿清空）+ logs/events.jsonl
├── handoff/                      # ⭐ 交接体系（STATUS/CHANGELOG/modules/MEMORY）
├── 系统UI建议/                    # UI 参考截图（历史材料，27MB）
├── 前后鼻音学习软件_奖励系统方案_当前共识版.md   # 设计历史（旧数值已作废）
└── assets/cats_v1_preview/       # 6 张猫猫 PNG 预览（来自交接包下载目录，非仓库内容）
```

## 五、如何运行 / 测试

```bash
cd /Users/baiyanglin/Desktop/普通话语音系统     # 解压后为本包目录
./.venv/bin/python -m pth_corpus prototype --data-root data --port 8766   # 原型
# 浏览器 http://127.0.0.1:8766（建议 375/390/430px 手机视口）

./.venv/bin/python -m pytest                      # 314 通过 / 6 失败（环境，见下）
./.venv/bin/python scripts/convert_webfem_csv.py \
  --csv-dir src/pth_corpus/prototype_data/raw_csv/cats_v1 \
  --catalog-v1 src/pth_corpus/prototype_data/artwork_catalog_v1.json \
  --out src/pth_corpus/prototype_data/artwork_catalog_v2.json             # 重生成+验收
```

> ⚠️ `.venv` 未打进包（机器上已有）。若在新机器：`python3 -m venv .venv && ./.venv/bin/pip install -e .`
> （依赖见 pyproject.toml；听辨/辨音/句子功能不需要 ffmpeg，但旧测试里的音频分析用例需要）。

**6 个既有环境性失败（勿当回归）**：`ffmpeg` 不在 PATH → test_audio_analysis ×2；
句子数据切片缺失 → test_sentence_reading ×4。

## 六、本包与项目根目录的差异（剔噪）

打入包 / 未打入：

| 未打包（机器上都有，按需自取） | 原因 |
|---|---|
| `.venv/`、`.git/`、`beads29/`（995MB，含自己的 venv/output） | 环境/工具，且 beads29 是独立的 56×56 生产工具，未随本次更新 |
| `新大纲普通话水平测试用朗读作品音频/`（334MB）、`pdf_work/`、`data/raw/`（252MB） | 原始素材，运行时不读（切片已在 derived） |
| `cat_beads.png`、`beads29/output/` 等生成物 | 历史产物 |

**包的资产差异**：`assets/cats_v1_preview/`（6 张 PNG）是从交接包下载目录复制的预览图，不属于仓库；
仓库内的网格真值是 `src/pth_corpus/prototype_data/raw_csv/cats_v1/*.csv`。

## 七、这次改了什么（给新 Agent 的重点）

1. **作品**：旧 6 件微型作品（56~116 颗）→ 新手「麦克风」(58) + 猫猫系列 6 件 100×100（全部明牌可选、
   随时切换、进度永久保留、单一当前作品、无解锁规则）。
2. **奖励**：档位制（600/1200、600/900、300/600/900），≥20% 按比例浮点结算，正确率解绑；
   删除 streak 拼点/每日上限 100/辨音轮次递减/首轮全对彩蛋/完成 bonus；三练 +100、复习 +100。
3. **前端**：作品墙「新手作品 + 猫猫系列 X/6」、熨烫完成仪式、6/6 系列庆祝、「今日分钟·累计训练 X 天·连续 X 天」、
   localStorage v2 迁移（sessions/旧记录保留；未知当前作品自动回退 mic）。
4. **档位 UI**：字词 5/10 分钟；句子 10/15 句；辨音 50/100/150 词（300/600/900 明示）。

## 八、给下一个 Agent 的注意事项

- 改 `prototype_data/*` 或 `achievement.py`/`prototype_app.py` 后**必须重启原型服务**（按进程缓存）。
- 用户真实数据勿清空：`data/derived/prototype/discrim_progress.json`（游标 100、66 错词排期）；
  浏览器 localStorage `pth-nasal-progress-v1`；走查仪式见 `handoff/README.md`。
- 收工三步（硬性）：CHANGELOG 加一行 → STATUS.md 原地更新 → 大改动写 MEMORY。
- 旧费率材料（`PRODUCT-REVIEW-…08-23.md`、`前后鼻音学习软件_奖励系统方案_当前共识版.md`）
  数值已作废，仅作背景；现行权威 = `奖励与作品系统_新版规则_100x100基线.md`。
- 可选下一件事：真实新手资产替换（规则 §19）；猫猫作品名/标语定稿；100×100 墙渲染性能再压一压
  （当前 light 模式 1 rect/颗）。
