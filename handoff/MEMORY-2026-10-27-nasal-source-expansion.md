# 新来源核查与独立发声方式对照 · 2026-10-27

从 `codex/latic-validation-pipeline` 的 `5bb9e7bdd0ea5407a23e9ba45a3297dd210ad8ec` 接续到 `codex/nasal-source-expansion`。上一轮完成验证入口，本轮取得并核对新对照录音，均有实质进展；没有解决可靠鼻音纠错，没有启用正式反馈。

## 来源核查的结论

- [兰银官话偏误研究](https://www.mdpi.com/2076-3417/16/8/3675)涉及双向鼻音混淆，但数据声明要求联系作者，附录说明为刺激材料与汇总表。未联系作者、未取得录音。
- [SAIT-EMA官方归档](https://zenodo.org/records/17506802)开放声音／舌部运动资料，已取得官方元数据和校验一致的README。[论文](https://www.nature.com/articles/s41597-026-07237-9)说明TextGrid由MFA自动对齐；不能把它当学习者实际错音的人工转写。本轮没有下载数GB的说话人原包。论文PDF请求实际返回HTML，已保留失败证据，未伪称下载到PDF。
- [语音属性诊断论文](https://arxiv.org/html/2606.22022v1)链接的[作者仓库](https://github.com/Evanchan1923/MDD_SpeechAttribute)提供训练代码，但所查README／配置仍把微调权重设为本地占位路径，评估部分注明未完成。没有取得可直接运行的训练权重，论文成绩不是本系统成绩。
- [X-MDD论文](https://arxiv.org/html/2610.23079v1)使用额外人工转写的LATIC／MagicHub实际音素；所查文章未给出可用权重／标注下载。不能从“原始语料公开”推断额外标注已取得。未联系作者。

这轮仍新增0处可信鼻音错误标签。LATIC仍无音频，IEEE登录未明确完成；用户“好了”仍仅指磁盘重连，TaskSpace32继续由用户控制。

## 新取得的录音与核对

[CMNmatrix官方数据](https://zenodo.org/records/7063030)为同一人正常／Lombard两种发声方式的录音，采用CC BY 4.0。官方说明录音经过发音人员监听、重录与最终选择，适合补充来源质检的正常对照。其整句质检不是逐目标实际音素标注；耳机噪声诱发的发声变化也不能当作手机混噪验收。

归档620,571,090字节，MD5 `66ddcd4e46debc44ce4f331cbb7220f5` 与官方元数据一致，另记录SHA256。外置盘约剩2.4 GiB，归档保存在内置 `~/.cache/nasal-validation-sources/matrix-7063030/wavfiles.rar`，没有把完整解压副本写入项目。

新增 `scripts/audit_matrix_corpus.py` 以实际目录核对：11说话人、100句编号、2方式，应有2,200段，实有2,198，缺2处保留；另40辅助WAV与33目录，不混入句子。没有重复或未知路径。归档5个SF／6个SM前缀，与2022页面的6女／5男表述不一致，与[2025关联论文](https://journals.sagepub.com/doi/10.1177/23312165251324266)的数量一致；保留这个差异，不替参与者猜测人口信息。

根据[原论文表1的作者公开全文](https://www.researchgate.net/publication/327433174_Construction_and_evaluation_of_the_Mandarin_Chinese_matrix_CMNmatrix_sentence_test_for_the_assessment_of_speech_recognition_in_noise)建立50词候选矩阵。数字文件名映射先只列为假设；元数据顺序选第一个说话人、前两个句号、两种方式，共4段，读取为44.1kHz／单声道／PCM16。无参考文字输入的本地Qwen3-ASR识别，4段汉字及逐字拼音都与候选内容一致。该检查仅支持这4段的内容映射，不提供n/ng实际发音标签，不证明所有文件均已核对。

首次本地检查在导入共享工具时因基础Python缺websockets而停止，尚未加载模型或调用网络；随后按既有做法将项目venv加入基础解释器搜索路径末尾，未安装软件，四段检查完成。错误与环境处理另存私有记录。

## 下一批已固定，尚未执行评分

`matrix-control-plan.json` 固定11位说话人×两种方式×同两句话=44段，154鼻音目标（前66、后88），原5模型及原门槛不变。这是来源质检控制，不是新的实际音素人工标签；下一轮报告纠错／匹配／未知及说话人内方式差异，不据此宣称真实错音检出率或自然人群误报率。选定44段均存在，整库缺2仍留在库存审计中。

下一步核对并转换选定录音，按执行时账本另行冻结最多44次新请求，再进行定位、两编码器特征、五模型评分。当前没有新API预算键、没有任何鼻音诊断输出，没有按结果选模型／门槛或重新训练。原LATIC72目标／5模型及完整入口不变；不要覆盖已完成计划或复用过期预算。

私有证据在 `data/derived/nasal-acoustic-validation/source-expansion-v1/`；关键JSON另存内置 `~/.cache/nasal-api-recovery/source-expansion-v1/`。公开 [聚合报告](nasal-source-expansion-2026-10-27/report.json)不含参与者逐条音频、实际识别文本或原包。

## 本轮验证与边界

8项新测试通过：缺失配对仍进预期分母、缺整组、辅助音频分离、重复／危险／未知路径拒绝、前导零与矩阵列顺序。实际官方归档完整扫描与校验通过。未重跑整套应用测试，未做真人麦克风或手机端到端。

新付费请求0；524预留账本逐项不变，仍包含历史确认523次＋另1次可能发送。198份原真实进度哈希未变，8769健康（ready=true、34 profile、warm_error=null）。正式云评测与鼻音反馈保持关闭；完整目标仍包括有效字词／句内纠错、回听、重试、练后复练和设备验收。
