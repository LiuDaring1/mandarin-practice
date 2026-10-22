# 新闻句子来源与处理边界

用户于 2026-10-22 指定微信公众号「播音主持稿件」的「新闻跟读」合集，要求下载配套文字与音频，筛选完整句子、对齐切片，经过剪映新闻女声和新闻男声处理后加入本地 APP。

[公开合集](https://mp.weixin.qq.com/mp/appmsgalbum?__biz=MzA5MTU4NTE3Nw==&action=getalbum&album_id=2407676370572230657)。用户原始长网址中的会话参数不纳入代码和文档。每条候选在私有清单保留原文章 URL、标题、发布日期、音频 URL／哈希、原音时间与对齐证据。

文章通过 Ego Lite 原生页面顺序打开和读取；音频地址来自实际 H5 播放器及页面嵌入的媒体 ID。随后只下载已发现的公开媒体地址，不调用登录态私有接口。新闻稿及示范音来自第三方，原页面的中央广播电视总台等来源标注保留；换音色并不自动取得再分发授权。当前仅用于用户已授权的校内、本地试用，GitHub 不上传原包、正文合集、录音或派生音频。

管线：`collect_news_ego.mjs` → `download_news_audio.py` → `prepare_news_sentences.py` → `release_news_sentences.py prepare` → 剪映双声换音色 → 分组 `split/review/repairs/assemble` → `publish`。收集脚本复用既有 TaskSpace；其他机器须替换本机路径与 TaskSpace ID，不能盲目新建空间恢复失败任务。

候选限定 15–65 个汉字、3–23 秒、句意完整与鼻音密度合适；不选整篇新闻、分号截断、引号不配对或明显依赖前文的句子。含数字／拉丁字母的句子暂缓，不把数字直接删除来凑对齐。用 Qwen3 ForcedAligner 获得字符时间，再由独立 Whisper 转写及拼音对比筛选，保留首尾余量；低置信项留在 holds，不猜测对齐。该流程是机器筛查，不声称每个音素已人工听检。

原始材料在 `data/raw/news-wechat-v1/`，候选、证据、选择快照与发布清单在 `data/derived/news-sentence-v1/`，双声输出在 `data/derived/voice-conversion/news-sentences-{female,male}-v1/`。这些路径全部属于本机私有数据边界。
