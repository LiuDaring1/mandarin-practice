# handoff/ 交接系统使用说明

> 本文件解释「怎么交接」。任何新对话 / 新 agent（DSH、V4 flash、Cursor 等）**开工前先读本文件**，
> 然后按下面的顺序读文档，30 秒内就能接上项目。

**2026-10-23 最新接手说明**：[Astra 交接](HANDOFF-2026-10-23-astra.md)，含分支／PR 关系、已启用功能、尚未验证的鼻音诊断、数据保护与下一步边界。

## 目录结构与角色

| 文件 | 角色 | 规则 |
|---|---|---|
| `../README.md` | 项目大门 | 是什么、怎么跑、里程碑节点清单（指针） |
| `handoff/README.md` | 本文件：交接系统说明 | 很少改 |
| `handoff/STATUS.md` | **唯一现行状态总览**（各模块现状、运行/测试、数据位置、待办） | **原地更新，永远不换文件名**；头部有「最近更新」 |
| `handoff/CHANGELOG.md` | 每次改动一行 | 每次收工**必须**追加（日期 / 模块 / 改动 / 文件） |
| `handoff/MEMORY-<日期>-<主题>.md` | 不可变里程碑节点（决策过程、验收数据） | 只增不改，像 commit 历史 |
| `handoff/modules/<模块>.md` | 每模块一页：职责 / 现状 / 关键文件 / 数据 / 端点 / 待办 | 每次大改同步更新对应页 |

旧的文件名（如 `STATUS-2026-08-13.md`、`STATUS-2026-08-23.md`）保留为历史快照，**不再是入口**。

## GitHub 同步

正式入口为 https://github.com/LiuDaring1/mandarin-practice 。任何 clone 都以自身仓库根目录为准；下面的绝对路径只表示维护者原电脑位置。开工先阅读根目录 `AGENTS.md` 与 `CONTRIBUTING.md`，fetch 最新提交；用任务分支协作并通过 PR 合入 main，代码与交接文档同时提交。

## 开工三步（任何 agent）

1. 读 `../README.md`（项目是什么、怎么跑）。
2. 读 `handoff/STATUS.md`（现状、数据在哪、怎么测试、怎么走查）。
3. 读 `handoff/CHANGELOG.md` 最新日期段落 + 你要改的 `handoff/modules/<模块>.md`。

## 收工三步（任何 agent，硬性要求）

1. **CHANGELOG 追加一行**：`- 日期 模块：一句话改动（文件）`。小改也要记，哪怕一行。
2. **原地更新 STATUS.md**：改过的模块对应小节 + 头部「最近更新」。
3. 重大节点（新机制、验收达标）才写 `MEMORY-<日期>-<主题>.md`，写完不可再改；并在 README 节点清单加一行。

## 用户话术模板（直接抄）

**维护者当前本机项目根目录（换 agent 时给出；其他机器用自己的 clone 路径）**：`/Volumes/语苗计划/桌面整理2026-10-01/01_语音项目/普通话语音系统/普通话语音系统-zcode`

**开新窗口 / 换 agent 时，开头说**：

> 项目在 /Volumes/语苗计划/桌面整理2026-10-01/01_语音项目/普通话语音系统/普通话语音系统-zcode，先切到这个目录（cd /Volumes/语苗计划/桌面整理2026-10-01/01_语音项目/普通话语音系统/普通话语音系统-zcode）。
> 然后读 README.md 和 handoff/README.md 了解交接规则，再读 handoff/STATUS.md 和
> handoff/CHANGELOG.md。STATUS.md 里有「模块现状一览」表（模块名 → 文档路径索引），
> 按表找到你要改的模块文档（在 handoff/modules/ 下）读它。之后我要做的是：……

（agent 熟悉项目时可简化为：`项目在 /Volumes/语苗计划/桌面整理2026-10-01/01_语音项目/普通话语音系统/普通话语音系统-zcode，先读 handoff/STATUS.md，然后……`）

**为什么这样写**：
1. **位置必须给**——新窗口 agent 不知道项目在哪，相对路径没根，必须先 cd 到项目根。
2. **文件名别让 agent 猜**——模块文档是英文名（如 听辨 → `handoff/modules/discrimination.md`），
   让 STATUS 的表做索引，或直接给全路径：`……然后读 handoff/modules/discrimination.md。之后我要做的是：……`

**过程中**：正常说需求即可，不用特殊话术；agent 犯迷糊时让它「回去读 handoff/STATUS.md」。

**结尾（每次收工前，必说）**：

> 收工前按 handoff/README.md 的收工三步：CHANGELOG 加一行、STATUS.md 原地更新
> 相关模块段落；如果是大改动，写 MEMORY 并在 README 节点清单加一行。然后总结这次改了什么。

（忘了说也没关系，事后补一句「把这次的改动补记到 CHANGELOG 和 STATUS」即可。）

## 其他纪律

- **用户真实数据**（`data/derived/prototype/discrim_progress.json`、用户浏览器 localStorage）自动走查不得修改；使用临时 QA 目录与独立浏览器，绝不通过“还原”覆盖后来新增的真实练习——见 STATUS.md。
- 测试以本次实际结果为准；历史的“6 个环境失败”已失效。缺少本地数据时先查 `LOCAL_DATA.md`，不要直接假定任何失败正常。
- 文档全部用中文、纯 Markdown，不依赖任何工具或账号，保证跨 agent 可读。
