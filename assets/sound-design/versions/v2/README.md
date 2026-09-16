# 普通话练习 · 声音设计第二轮：庆祝增强

2026-09-12 · **用户已试听并认可 A「奶油木珠」基础风格；本轮四种庆祝声增强，等待试听反馈。正式 APP 尚未接入。**

## 本轮：A 保留，庆祝更有起伏

用户认为 A 整体很好，但奖励结算、单件作品完成、系列集齐偏冷静，希望更能带起情绪。因此新增 `a-lift` 欢庆版：上行节奏与短蓄势 → 明亮大三和弦展开 → 带暖低音的落稳。少量亮音与短空间增加成品感；用柔和波形整形控制瞬态，让和声保持饱满。日常点击、开始、正误、跟读提示、落珠和融合都继续使用原 A 文件，SHA-256 不变。

| 事件 | 原版 | 新版 | 变化 |
|---|---:|---:|---|
| 奖励到账 | 0.65 s | 0.95 s | 四颗珠子轻快跃起，落在明亮和弦上 |
| 今日三练 | 0.94 s | 1.22 s | 多一步上行与轻亮收尾，增加一档庆祝 |
| 单件作品完成 | 1.20 s | 1.80 s | 蓄势后展开，再落回温暖的完成感 |
| 系列集齐 | 1.65 s | 2.25 s | 更完整的上行、两次展开与落稳，最高一档 |

四个文件的样本峰值分别保持原来的 -19 / -18.5 / -18.5 / -18 dBFS。新版节奏、频谱、持续长度和平均能量不同，**这不是感知等响度匹配**；不能把峰值一致理解成听感完全一样响。系列延长到 2.25 秒是本轮“更嗨”方向的试听提案，可随时停止，不改变现有 1.8 秒融合动画。

试听页最上方提供四组“原版／新版”按钮、一键连听四段、流程用原版／新版切换。流程默认日常 A＋新版欢庆；首轮 A/B 区折叠留作回看。B 不再用于当前流程。原版的 25 WAV 全部原位保留，页面／清单／生成器／报告快照在 `versions/v1/`。

新文件：`sources/generate_celebrations.py`、`exports/a-lift-*.wav`（四个单音＋九秒预览）；本轮专项：`sources/check_celebrations.cjs` 与 `qa/celebration-v2/`。用户认可 A 不等于已认可本轮四段新版，耳机／手机的具体设备验收状态也未推断。

## 首轮音色基础

推荐 **A「奶油木珠」**：短木质共鸣、带轻微弹性的圆润落珠、少量温和亮音。当前奶油底、青橙紫小精灵已经活泼，声音以温暖触感与间隙为主。B「软糖气泡」让滑音更明显，适合比较弹性大小；首轮只比较轻点、答对、落珠、单件完成四个关键声音。A/B 使用相同峰值层级，避免单纯因为更响而被偏爱；不是感知响度已匹配的人耳结论。

训练期间不铺音乐，不加入角色口播；前鼻与后鼻选择使用同一种确认音。字词和句子仍然只有跟读计时，不能因计时结束播放“答对”音。连错沿用相同柔和纠错音，不加警报或惩罚旋律。

## 直接试听

- 试听页：<http://127.0.0.1:8772/>。现有训练服务 8769 保持运行。
- 工作目录固定：`/Users/baiyanglin/Desktop/普通话语音系统/普通话语音系统-zcode`。
- 如果试听服务已停止，在工作目录运行：

```bash
PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python scripts/serve_sound_lab.py
```

服务只监听本机回环，使用标准库，无新增运行时依赖。它只提供白名单内的试听页、音效、两张既有角色图及一条既有教学示范；不加载 FastAPI 应用、不调用训练 API、不提供进度写入口。单独的 8772 origin 保持浏览器偏好隔离。不建议使用面向整个仓库的通用 HTTP 文件服务。页面是 ES module，需 HTTP 服务，不能双击 `file://`。

试听顺序：上方四组庆祝“原版／新版” → 连听四段新版 → 完成一件／勾选系列集齐 → 答一小组。下方保留连续拼豆、七种 A 日常音及六个落珠变体、原有拼豆音与教学衔接。总静音／音量只控制音效；“全部停止”或 Escape 结束本次所有试听，包括当前教学演示。切换流程主动结束上一段；“试插入奖励音”专门检验教学占用期间丢弃反馈。

B 仅在折叠的首轮回看区保留四个单音按钮；当前流程采用已确认 A，四种庆祝按独立原版／新版选项切换。模拟网格、预设十题结果、1900 颗临时待拼和作品完成均只存在页面内存，不读取或写入真实记录。

## 交付文件与来源

- `exports/`：**26 个原创单音 WAV（原 A 16 / B 6 / 欢庆版 4，均包含变体）、3 段预览、1 个旧拼豆音代表参照，共 30 个 WAV**。44.1 kHz / 单声道 / PCM16。短音使用 WAV，浏览器可直接解码，无需为几十毫秒的音效增加有损编码和解码延迟。原 A 16 样本约 648 KiB；若新版庆祝获认可，用四个新文件替换四个旧庆祝文件，仍为 16 个运行时样本，约 801 KiB。
- `manifest.json`：事件 ID、用途、时长、播放 gain、文件峰值、变体、限流、优先级、默认开关、来源及全场景策略。
- `sources/generate.py`：原创模态共鸣／弹性滑音／滤波噪声合成；固定种子 20260912；参数写在源代码中，可重复生成。没有下载第三方音效，没有使用音乐生成服务，也没有提示词来源缺失的问题。
- `sources/check_audio.py`：解码、峰值、边界与 4 倍插值真峰值估计。只负责机器指标，不冒充人耳判断。
- `sound-manager.js`：可复用 Web Audio 样本管理器；`index.html` / `lab.css` / `lab.js`：独立试听界面与流程模拟。
- `qa/`：音频检查 JSON、独立 Chrome 交互报告、五档布局截图、只读保护哈希与边界说明。
- 仓库 `scripts/serve_sound_lab.py`、`scripts/qa_sound_lab.cjs`：本地只读服务与可重复浏览器验收。

原创样音可随本项目修改使用。旧音参照依据本项目当前 `playPlaceTick` 逻辑，以 1600 Hz 固定频率代表其 1350–1850 Hz 随机范围，额外做微淡入淡出；不是逐次随机现场录音。

教学衔接使用既有 **「安心」ānxīn / `t1-00019`**：`data/derived/clips-v2/table1/t1-00019.wav`，服务端仅只读返回，未复制、移动、改写或换声。该示范不是本任务原创，原素材边界见项目 [SOURCE.md](../../SOURCE.md)。角色图只读复用当前 `prototype_static/illustrations/`。

## 原 A 组声音规格（原版对照保留）

以下峰值已经写入 WAV，播放 gain 为 1，总音量默认 70%。低强度落珠与纠错低于奖励声；不对所有文件做同样的响度归一化。

| 声音 ID | 用途 | 导出时长 | 文件样本峰值 | 变体数 |
|---|---|---:|---:|---:|
| `ui.confirm` | 确认 / 切换 | 78 ms | -23 dBFS | 1 |
| `training.start` | 开始训练 | 280 ms | -21 dBFS | 1 |
| `follow.ready` | 轮到你跟读（可选） | 100 ms | -28 dBFS | 1 |
| `answer.correct` | 辨音答对 | 220 ms | -20 dBFS | 1 |
| `answer.retry` | 辨音答错 | 200 ms | -24 dBFS | 1 |
| `reward.arrive` | 结算 / 奖励到账 | 650 ms | -19 dBFS | 1 |
| `day.complete` | 今日三练达成 | 940 ms | -18.5 dBFS | 1 |
| `bead.place` | 拼入一颗 | 66 ms | -25 dBFS | 6 |
| `artwork.fuse` | 熨烫 / 融合 | 1800 ms | -27 dBFS | 1 |
| `artwork.complete` | 单件作品完成 | 1200 ms | -18.5 dBFS | 1 |
| `series.complete` | 系列集齐 | 1650 ms | -18 dBFS | 1 |

共同动机以 C / E / A 一带的温和音程为骨架，声音本体混合阻尼正弦模态，木珠带少量不谐振动；气泡通过短滑音强化弹性。结算、三练、作品、系列逐步展开相同家族的短动机。融合只在仪式内出现，1.8 秒淡入淡出，不循环、不带高频蒸汽嘶声。实际时长、峰值、RMS、哈希以 `qa/audio-report.json` 为准；短瞬态的 LUFS 不宜作为唯一体验判断。

## 全场景统一清单

| 场景 | 策略 | 事件 | 原因 |
|---|---|---|---|
| 按钮确认 / 选项切换 | 独立音效 | ui.confirm | 仅明确确认；前后鼻选项用完全相同的声音 |
| 普通导航 / 浏览历史 / 作品墙 | 保持安静 | — | 高频浏览无须附加声响 |
| 开始字词 / 句子 / 辨音 | 独立音效 | training.start | 一次短起步；示范要开始时立即让路 |
| 示范结束 → 进入跟读 | 独立音效 | follow.ready | 可选，默认关闭；示范 ended 后留 120 ms 空隙 |
| 跟读每秒 / 计时结束 | 保持安静 | — | 只有计时，没有发音评测，不能播放答对音 |
| 辨音整词全对 | 独立音效 | answer.correct | 服务器真实判题结果，每整词一次 |
| 辨音有错 / 连续有错 | 独立音效 | answer.retry | 每整词一次，连错不加重音量或警报 |
| 趁热巩固 / 跨天复习开始 | 复用音效 | training.start | 同为起步，无需新增一种声音 |
| 巩固 / 复习正误 | 复用音效 | answer.correct / answer.retry | 沿用实际判题语义 |
| 训练结算 + 基础奖励 + 复习奖励 | 独立音效 | reward.arrive | 实际到账才响，同一结算合并一次 |
| 今日三练完成 | 独立音效 | day.complete | 当次真的新达成，替代普通到账音 |
| 单颗拼入 | 独立音效 | bead.place | 六个变体轮换，继承现有拼入反馈职责 |
| 按住连续拼入 | 复用音效 | bead.place | 只由实际拼入事件触发，最多 10 次/秒，松手终止 |
| 熨烫 / 融合 | 独立音效 | artwork.fuse | 1.8 秒单次纹理，关闭弹层就结束 |
| 单件作品完成 | 独立音效 | artwork.complete | 只在首次完成后显示成品时触发 |
| 系列集齐 | 独立音效 | series.complete | 替代该次单件完成音，不叠放两段庆祝 |
| 暂停 / 恢复 / 退出 / 取消 | 保持安静 | — | 让用户可以立即安静下来 |
| 加载中 / 网络失败 / 音效不可用 | 保持安静 | — | 文字反馈即可，错误不应制造更多噪声 |
| 示范音频 / 标准视频播放期间 | 保持安静 | — | 教学最高优先，全部音效淡出且丢弃新事件 |

普通点击不得全局绑定 `document.click` 无差别发声。用户点击辨音选项后，如果已经要立即进入判题反馈，就只播最终整词反馈，避免“确认＋答对”叠放。

## 播放与中断规则

1. 教学语音／视频最高优先：`bindMedia()` 绑定 `play/ended/pause/error/abort/emptied`，也可使用成对 `beginTeaching()` / release。教学开始时现有音效约 8 ms 淡出；所有新音效丢弃，结束后保留 120 ms 安静间隙，绝不补播积压。示范音不接入音效 master，不压低教学音量。若调用方要求教学第一个采样前完全清空，可提前占用教学并淡出，约 12 ms 后开始媒体；不要为等待可选装饰音延迟正常示范。
2. 必要反馈（priority 3）> 奖励庆祝（2）> 点击、落珠、融合（1）。高优先事件可淡出低优先事件；低优先遇到正在播放的高优先即丢弃。新同类反馈替代旧反馈，不形成双重旋律。教学优先独立于这套数字。
3. 最多 4 个活动节点，落珠最多 2 个，事件最小间隔在 manifest。`bead.place` 至少间隔 100 ms，所有单击／批量拼入一视同仁；六变体轮换。不随拼入数量叠加音量，不为每颗建一个长声音。真正触发来自 `placeBeads` 的实际 `room > 0`；不从按钮按住时间推断真正拼入量。
4. `stopBus('bead')` 在 pointerup、pointercancel、lostpointercapture、keyup、blur、待拼耗尽与关闭弹层时调用；约 10 ms 内结束。松手后的动画不能继续制造音效事件。
5. `eventKey` 去重使用调用方提供的业务事件标识（如 session ID + settlement），只保留最近 128 个。结算奖励合并一声：三练本次新增则选择 `day.complete`，否则确有到账才 `reward.arrive`。系列集齐选择 `series.complete`，替代同次 `artwork.complete`。不能从“页面上显示已完成”的静态状态反复发声，返回作品墙应安静。
6. 只有用户手势调用 `unlock()`；预取 WAV 不自动建 AudioContext。未解锁、未加载、静音、后台、上下文挂起、语音占用时丢弃事件；状态恢复不重试旧事件。`play()` 本身同步返回 started/reason/done，不持有延后队列。调用方异步预加载后需检查当前意图仍有效，试听页用取消 token 防止松手或切换后补发。
7. 常规停止使用 8 ms 斜坡；后台／页面退出／上下文挂起时立即断开并清理节点，避免 AudioContext 重新运行后播出冻结的残音。再次操作才恢复。调用方同时取消流程计时器和长按 rAF；播放页通过 AbortController 实现，不改变正式训练计时。
8. `setPreferences()` 只写自身 key，支持存储失败时退回内存。当前为 `pth-sound-lab-preferences-v1`；正式接入使用新的 `pth-sound-preferences-v1`，教学设置另管。不修改 `pth-nasal-progress-v1` 等训练结构。`dispose()` 关闭 AudioContext、释放缓存、移除监听。

## 正式接入位置（本轮未执行）

后续在当前 zcode 最新前端上保留快照再接入；不要用旧 Git 内容替换界面。下表以函数名定位，避免同期标准视频更新导致行号漂移。

| 接入位置（`src/pth_corpus/prototype_static/app.js`） | 接线要求 |
|---|---|
| 首页开始按钮事件 → `startSession` / `startSentenceSession` / `startLibraryPractice` / `startReviewPractice` | 直接在用户手势内 unlock。成功进入训练才播放短开始音，下一条教学开始时立即让路。加载失败不播放成功声。 |
| `els.player` / `els.sentencePlayer`，动态创建的校音 video | 初始化／创建时统一 bindMedia；拆除时调用返回的解绑函数。顺序校音两片之间可用额外 beginTeaching 锁覆盖完整教学序列，确保间隙也无装饰声。|
| `enterFollow` / `enterSentenceFollow` | 可选提示默认关闭；若启用，必须在 media ended 之后并且仍处于跟读阶段。额外提示计时器可取消且不改变现有 follow deadline。|
| `followDone` / `sentenceFollowDone` | 安静，不派发 answer.correct；不得引入任何语音评测、录音或发音判定。|
| `applyDiscrimFeedback(payload)` | 用现有 allCorrect 真值，每整词仅一声；主练、巩固、复习共用。连续有错不新增声音。|
| 三类 finish/结算成功应用结果处；`renderComplete`、`renderSentenceComplete`、`renderLibraryComplete`、`renderReviewComplete` 的上游 | 在实际奖励应用成功处发事件，使用一次性业务 key，避免 render 重绘重响；已有三练替代普通到账逻辑需按当次结果判断。|
| `ensureAudio()` / `playPlaceTick(count)` | 用统一 manager 替换原 oscillator 路径，只保留一个 AudioContext；原震动作为独立触觉处理保留，不因音效静音而丢失。不要同时保留新旧拼豆发声。|
| `placeBeads(count)`、`bindPlacement`、`stopPlacement` | 实際 `room > 0` 才调用 bead.place；所有停止边界取消声音。原有放置速度、数量、fill_order、余额逻辑全不变。|
| `showIronCeremony(art, record)` / `closeDetail` | 仪式启动播 1.8 秒融合；成品显示时按是否首次系列集齐二选一。关闭弹层或切页立即取消仪式音。|
| `setView`、暂停、退出、页面后台 | 主动清理装饰声音和调用方取消句柄；媒体暂停由现有训练逻辑负责，音效模块不更改训练状态。|

建议上线目录 `prototype_static/sounds/`，复制选定 A 的 16 个 WAV、精简 manifest 与 manager；若本轮获认可，将四种庆祝解析到 `a-lift`，其余仍解析到 `a`，或在正式精简 manifest 中统一为所选版本；以 `baseURL` 指向该目录。试听页和 B 组仍放设计目录。正式设置区增加独立音效开关和音量控制，HTML label／键盘操作齐全。

```js
// 接口示意：不是本轮已接入的代码
const sfx = new SoundManager(manifest, {
  baseURL: new URL('/assets/sounds/', location.href),
  storageKey: 'pth-sound-preferences-v1',
});
const unbind = sfx.bindMedia(els.player);
// 用户明确动作的同步调用栈内触发 unlock；实际业务结果仍以当前状态为准。
button.addEventListener('pointerdown', () => { void sfx.unlock(); });
sfx.play('answer.correct', {eventKey: sessionId + ':' + wordId});
sfx.play('bead.place'); // 只放在 room > 0 的真实拼入后
sfx.stopBus('bead');    // 松手或详情关闭
```

## 再生成与专项检查

生成和数值检查使用 Codex 随附 Python/NumPy（仅制作时依赖），不安装到系统 Python：

```bash
/Users/baiyanglin/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 assets/sound-design/sources/generate.py
/Users/baiyanglin/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 assets/sound-design/sources/generate_celebrations.py
/Users/baiyanglin/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 assets/sound-design/sources/check_audio.py
NODE_PATH=/Users/baiyanglin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules /Users/baiyanglin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/qa_sound_lab.cjs
```

浏览器脚本只接受 8772 的只读 `sound-lab` 隔离标记，使用新 Chrome context，无自动播放放宽参数。实际检查与限制详见 `qa/README.md`。独立样音首轮不改应用逻辑，无须把全仓库 pytest 重跑当作音频证据；**正式接入后**必须运行现有 319 通过 / 1 跳过基线命令，并在 `serve_ui_qa.py` 8771 临时进度环境走查三类训练、复习、所有奖励、真实拼豆、校音视频、页面退出及静音。不得在 8769 完成训练造验收数据。

用户已试听并认可原 A 的整体风格；本轮新版庆祝仍待试听确认。耳机、手机外放、iOS Safari 的专项设备听检仍待完成。波形无削波和浏览器有输出不能证明“人听起来不刺耳”或“十秒不会疲劳”；目前风格推荐是设计判断，最终需要用户用平时的音量试听后微调。
