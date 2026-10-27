# LATIC完整验证流程与旧录音预检 · 2026-10-27

从 `codex/latic-validation-runner` 的 `2bae8921e255734f9b8fdf83aeb532717ba3d77f` 接续到 `codex/latic-validation-pipeline`。本轮补齐独立语料验证流程，属于工程进展；还没有LATIC音频或新的准确率证据，可靠教学反馈目标仍未完成。

## 流程与数据边界

新增 `scripts/run_latic_validation.py`，串联原严格导入器后的预算、ISE定位、特征提取与五模型评分。57项来源及原模型、权重、层、窗口、VAD、取样方式和评分规则冻结；原72目标／69段／5模型选择保持不变。

位置匹配要求完整汉字序列一致，目标拼音与接口参考一致，再沿用原API有效时间边界。参考拼音一致只证明预期参考被使用，不等于接口识别出了实际读音。没有人工边界回填或按结果修标签。

两编码器依次加载：Xeus第19层、HuBERT第18层；HuBERT仍用CPU，保持已验证的环境。提取Xeus两段、HuBERT两段及四点时间特征，失败按特征块独立记录。某一模型不可用不会让另一模型也丢掉目标；汇总始终保留全部72目标，分开报告双向错误、正常误报和未知。没有新拟合、门槛选择或自动启用。

新增 `scripts/nasal_validation_execution.py` 的请求镜像。发送前将已预留账本持久保存到内置盘，收到返回后镜像原始响应；外置账本相对镜像回退时停止，已有完成结果即使外置盘丢失也拒绝覆盖。仍保留可能发送但无结果的请求，不自动重试。此机制不能保证机器断电时必有响应，更不能把预留数当作供应商计费次数。

## 本轮实际验证

- 在3份原Griffith录音上用现有缓存核对定位，实际重新运行Xeus MPS、HuBERT CPU及VAD。两套特征最大差异均为0，VAD完全相同，五模型共15预测的分数、差值与其他字段完全复现。3目标仅用于协议预检，不能推算准确率。
- 新11项回归包含重复字位置、错误参考拼音、漏读、各模型独立特征缺失、预测漂移及内置镜像防回退。相关11文件共137项通过。
- 合成集成测试以69段／72目标模拟完整批次；2目标导入缺失，67次模拟请求产生另3目标的API／参考／漏读失败，保留67可定位目标。模拟编码器再分别制造3种特征失败，Xeus／HuBERT／分组／时间模型各66可评分，融合65；每个汇总仍有72目标。供应商与编码器为测试替身，没有真实网络调用，不是模型效果验收。
- 本轮新API请求0，账本524逐项未变（历史确认523次＋另1次可能发送）；198个原真实进度文件哈希未改。8769健康：ready=true、34 profile、warm_error=null。本轮未再次重启、未跑真实麦克风或手机端到端。

私有 `data/derived/nasal-acoustic-validation/latic-pipeline-v1/` 保存计划、旧目标特征、预检及保护核验；关键JSON另存内置 `~/.cache/nasal-api-recovery/latic-pipeline-v1/`。公开 [聚合报告](latic-pipeline-2026-10-27/report.json) 不含目标身份、逐人声音、模型权重或原始响应。原导入器的1,680预测重放证据保持不变，本轮未重复运行全部旧评分。

## 接续操作

`prepare` 与 `preflight` 已完成，不重跑或覆盖。下一步实际官方归档下载与导入尚未发生；原导入器仅接受明确ZIP结构，真实格式如不同先只读核查，再另存适配方案。`audio-import/` 当前不存在。

导入完成后按顺序执行 `budget` → `api --allow-paid` → `align` → `features` → `evaluate`。入口为 `scripts/run_latic_validation.py`。预算从执行时实际账本冻结去重请求，最多新增69次；原443→512旧预算不可复用。若中断，检查已有缓存、镜像和账本，不手动清空请求键；失败／缺失目标保留。

普通脚本／测试用 `../.venv/bin/python`、`PYTHONPATH=src:scripts`。模型提取用 `/opt/miniconda3/bin/python`，设置 `HF_HUB_OFFLINE=1`、`OPENBLAS_NUM_THREADS=1`、`OMP_NUM_THREADS=1`、`PYTHONDONTWRITEBYTECODE=1`，通过 `site.addsitedir` 在原搜索路径末尾加入项目 `../.venv/lib/python3.13/site-packages` 以复用已有websockets／pypinyin；不得抢占基础环境的torch／numpy或另行安装。本轮预检已核验模型运行身份。

用户“好了”只回答外置盘重连。IEEE登录尚无完成确认，TaskSpace32继续由用户控制，不接管、不重复提问、不联系作者。后续要用新录音检验真实错音和正常对照，仍须覆盖带噪、漏读／重复和实际设备，并把有效反馈接入字词／句内回听、重试和练后复练。正式诊断及自动云评测保持关闭。
