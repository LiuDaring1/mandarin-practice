# GitHub 与本地运行数据

公开 Git 仓库包含完整应用代码、配置、猫猫作品数据、原创 UI 素材、原创 A 音效及设计／交接说明。不会通过 GitHub 自动分发教学语料或同步用户练习记录。

完整 APP 的本地依赖：

| 路径 | 用途 | 获取方式 |
|---|---|---|
| `data/corpus.sqlite3` | 词语主数据库 | 由维护者提供具备使用权限的本地数据，或按语料管线重新构建 |
| `data/derived/phonology-v1/phonology.sqlite3` | 鼻音特征与筛选 | 从本地语料生成，见训练／语料模块文档 |
| `data/derived/clips-v2/` | 字词示范 WAV | 经来源许可的本地音频切片 |
| `data/derived/sentence-practice-v1/` | 句子清单与音频 | 经来源许可的句子管线输出 |
| `src/pth_corpus/prototype_static/calibration/*.mp4` | 六音正常／半速教学视频 | 维护者现有本地交付；包含示范录音，未作为公共素材发布 |
| `data/derived/prototype/`、浏览器 localStorage | 个人进度、历史、日志 | 每个使用者独立生成，绝不从其他 agent 的测试记录复制 |

旧音库原包 `assets/sound-design/external/`、历史素材备份、完整截图集、`动画试验/`、`鼻韵母示范/` 也仅保存在维护者本地。历史文档指向这些路径时，不代表 GitHub clone 中包含它们。正式运行时 A 音效不依赖第三方原包；历史免费音库试听缺原包时不能重现。

维护者原工作目录：`/Users/baiyanglin/Desktop/普通话语音系统/普通话语音系统-zcode`。其他机器以实际 clone 目录为准，文档中原绝对路径只是来源记录。

没有本地语料的新 agent 仍可读取／修改代码、运行合成夹具单元测试、查看配置和任务说明。不要将缺少教学音频描述为完整应用已正常运行；也不要为了让测试通过而把用户原始数据加入仓库。


## 2026-10-23 新增新闻与评测

新闻私有数据还需要 `data/derived/news-sentence-v1/` 以及 active 指针所引用的 `news-sentences-female-v1/`、`news-sentences-male-v1/` 合并清单和 WAV；不要仅复制新指针而遗漏旧 16,718 条媒体。新新闻发布必须男女覆盖同一批 450 个 ID，缺失或哈希不符时不会当作完整新闻库加载。下载原包在 `data/raw/news-wechat-v1/`，仅续加工时需要，不上传 GitHub。

腾讯录音评测是本机可选配置。按 `modules/assessment.md` 设置被忽略的 `data/derived/assessment/config.json` 或环境变量，在目标机另行准备凭证；Git 不含 CSV 或 SecretKey。`usage.json` 为本地测试单位预留计数，迁移时不能擅自归零。没有配置时沿用旧跟读方式；已配置但云服务不可用时保守检查发声，拒绝麦克风则仅听示范、不计朗读完成。常规 QA 默认禁用云评测与麦克风。


连续评测的本地历史在各自 `prototype_dir/reading/attempts/`，包含参考文本、上下文目标位置和评测观察，不含用户录音；与其他真实进度一样不入 Git，也不从 QA 复制。服务重启不重发中断录音，避免重复收费。正式鼻音自动复练门禁当前关闭，详情见 `modules/assessment.md`。
