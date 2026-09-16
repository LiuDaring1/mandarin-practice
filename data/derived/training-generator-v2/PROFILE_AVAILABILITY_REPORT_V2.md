# v2 训练 Profile 可用性矩阵 PROFILE_AVAILABILITY_REPORT_V2

- 生成器版本：`v2.0`
- 数据基线：`formal_corpus_2026-08-08_16156`
- 可用条目：16149

## 一、总览

| Profile | 模式 | 候选数 | 核心池 | 10分钟核心 | 20分钟核心 | 缺失组合 | 稀缺组合 |
|---|---|---:|---:|---|---:|---:|---:|
| `bilabial_focus` 双唇音单项 | single_focus | 2894 | 513 | OK | OK | 0 | 1 |
| `h_f_focus` f/h 对比（f 为核心） | single_focus | 1129 | 167 | OK | need_repeat | 0 | 0 |
| `flat_focus` 平舌音单项 | single_focus | 1934 | 264 | OK | need_repeat | 0 | 7 |
| `retroflex_focus` 翘舌音单项 | single_focus | 5203 | 1060 | OK | OK | 0 | 3 |
| `flat_retroflex_contrast` 平翘舌对比（含 r） | contrast | 6738 | 1692 | OK | OK | 0 | 17 |
| `flat_retroflex_contrast_no_r` 平翘舌对比（不含 r） | contrast | 6261 | 1525 | OK | OK | 0 | 9 |
| `n_l_contrast` n/l 对比 | contrast | 2121 | 332 | OK | need_repeat | 0 | 2 |
| `jqx_special` j/q/x 尖音问题 | special_mix | 5132 | 1064 | OK | OK | 0 | 0 |
| `velar_focus` 舌根音单项 | single_focus | 3219 | 535 | OK | OK | 0 | 0 |
| `dt_focus` d/t 舌尖中音强化 | single_focus | 2809 | 410 | OK | OK | 0 | 0 |
| `simple_final_focus` 单韵母综合 | single_focus | 6634 | 1678 | OK | OK | 7 | 19 |
| `compound_all` 复韵母综合 | single_focus | 7070 | 1875 | OK | OK | 14 | 112 |
| `compound_front` 前响复韵母 | single_focus | 3075 | 523 | OK | OK | 0 | 7 |
| `compound_middle` 中响复韵母 | single_focus | 2425 | 373 | OK | OK | 2 | 9 |
| `compound_back` 后响复韵母 | single_focus | 2278 | 339 | OK | OK | 4 | 19 |
| `front_nasal_basic` 前鼻音专项一（基础） | single_focus | 2927 | 469 | OK | OK | 0 | 0 |
| `front_nasal_extended` 前鼻音专项二（扩展） | single_focus | 3147 | 528 | OK | OK | 1 | 19 |
| `front_nasal_all` 前鼻音综合 | single_focus | 5774 | 1279 | OK | OK | 1 | 40 |
| `back_nasal_basic` 后鼻音专项一（基础） | single_focus | 4186 | 747 | OK | OK | 0 | 0 |
| `back_nasal_extended` 后鼻音专项二（扩展） | single_focus | 1175 | 151 | OK | need_repeat | 8 | 8 |
| `back_nasal_all` 后鼻音综合 | single_focus | 5154 | 1095 | OK | OK | 17 | 21 |
| `front_back_nasal_contrast_1` 前后鼻音对比一 | contrast | 3804 | 705 | OK | OK | 0 | 1 |
| `front_back_nasal_contrast_2` 前后鼻音对比二 | contrast | 5121 | 1107 | OK | OK | 0 | 13 |
| `tone_1` 阴平专项 | single_focus | 5935 | 1390 | OK | OK | 0 | 0 |
| `tone_2` 阳平专项 | single_focus | 6156 | 1443 | OK | OK | 0 | 0 |
| `tone_3` 上声专项 | single_focus | 4648 | 912 | OK | OK | 0 | 0 |
| `tone_4` 去声专项 | single_focus | 8761 | 2778 | OK | OK | 0 | 0 |
| `tone_all` 四声综合 | comprehensive | 16149 | 16149 | OK | OK | 0 | 0 |
| `tone_33` 上声变调（3-3 连读） | special_mix | 403 | 403 | OK | OK | 0 | 0 |
| `general` 日常综合练习 | comprehensive | 16149 | 16149 | OK | OK | 0 | 0 |
| `neutral_focus` 轻声专项 | special_mix | 476 | 476 | OK | OK | 0 | 0 |
| `erhua_focus` 儿化专项 | special_mix | 39 | 39 | insufficient | insufficient | 0 | 0 |
| `yi_bu_focus` 一/不变调 | special_mix | 159 | 159 | need_repeat | insufficient | 0 | 0 |
| `front_back_nasal_contrast` 前后鼻音对比（综合） | contrast | 9700 | 3519 | OK | OK | 38 | 123 |

> 核心池 = 核心桶全部 item（含单字核心点）；状态 OK / need_repeat / insufficient。

## 二、各 Profile 明细

### bilabial_focus · 双唇音单项

模式 `single_focus`；候选 2894 条；核心池 513 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 513 | OK |
| 10 分钟 | 150 | 513 | OK |
| 15 分钟 | 225 | 513 | OK |
| 20 分钟 | 300 | 513 | OK |

**桶 core（核心 T×T，目标 80.0%）**

item 513 条：单字 339 / 双字 174 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| b | 139 |
| m | 109 |
| p | 91 |
| m+m | 37 |
| b+b | 28 |
| b+m | 23 |
| m+b | 21 |
| p+b | 21 |
| p+m | 14 |
| b+p | 12 |
| p+p | 11 |
| m+p | 7 |

稀缺（<10，1 个）：m+p(7)

**桶 supplement（补充 T↔O，目标 20.0%）**

item 2381 条：单字 0 / 双字 2231 / 三字+ 150

| pattern | 候选数 |
|---|---:|
| b+ZERO | 76 |
| ZERO+m | 71 |
| b+j | 56 |
| b+zh | 56 |
| m+ZERO | 54 |
| ZERO+b | 53 |
| b+l | 50 |
| b+x | 46 |
| b+d | 45 |
| sh+m | 45 |
| zh+b | 42 |
| j+b | 41 |

稀缺（<10，23 个）：b+n(5)、b+s(8)、p+c(3)、p+g(6)、p+k(6)、p+n(1)、p+r(7)、p+s(8)、m+c(9)、m+k(8)、m+n(9)、c+p(4)、k+p(5)、k+m(7)、l+p(9)、n+b(8)、n+p(4)、r+b(4)、r+p(2)、s+b(9)、s+p(2)、z+b(7)、z+p(3)

### h_f_focus · f/h 对比（f 为核心）

模式 `single_focus`；候选 1129 条；核心池 167 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 167 | OK |
| 10 分钟 | 150 | 167 | OK |
| 15 分钟 | 225 | 167 | need_repeat |
| 20 分钟 | 300 | 167 | need_repeat |

**桶 core（核心 f+f / h+f / f+h，目标 80.0%）**

item 167 条：单字 94 / 双字 73 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| f | 94 |
| f+h | 36 |
| f+f | 21 |
| h+f | 16 |

**桶 supplement（补充 f↔O，目标 20.0%）**

item 962 条：单字 0 / 双字 915 / 三字+ 47

| pattern | 候选数 |
|---|---:|
| f+ZERO | 87 |
| f+sh | 50 |
| ZERO+f | 45 |
| f+x | 43 |
| x+f | 41 |
| f+d | 39 |
| sh+f | 37 |
| f+zh | 35 |
| b+f | 34 |
| ch+f | 33 |
| f+l | 32 |
| f+b | 30 |

稀缺（<10，5 个）：f+n(7)、c+f(7)、n+f(8)、r+f(1)、s+f(2)

### flat_focus · 平舌音单项

模式 `single_focus`；候选 1934 条；核心池 264 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 264 | OK |
| 10 分钟 | 150 | 264 | OK |
| 15 分钟 | 225 | 264 | OK |
| 20 分钟 | 300 | 264 | need_repeat |

**桶 core（核心 T×T，目标 80.0%）**

item 264 条：单字 195 / 双字 69 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| s | 77 |
| z | 60 |
| c | 58 |
| c+c | 11 |
| s+z | 11 |
| c+s | 9 |
| z+s | 9 |
| s+s | 7 |
| z+z | 7 |
| c+z | 6 |
| z+c | 5 |
| s+c | 4 |

稀缺（<10，7 个）：z+z(7)、z+c(5)、z+s(9)、c+z(6)、c+s(9)、s+c(4)、s+s(7)

**桶 supplement（补充 T↔O，目标 20.0%）**

item 1670 条：单字 0 / 双字 1579 / 三字+ 91

| pattern | 候选数 |
|---|---:|
| z+ZERO | 50 |
| ZERO+z | 41 |
| sh+z | 36 |
| s+ZERO | 35 |
| ZERO+s | 34 |
| c+ZERO | 34 |
| j+z | 34 |
| d+z | 33 |
| g+z | 33 |
| z+j | 33 |
| zh+z | 31 |
| s+sh | 30 |

稀缺（<10，37 个）：z+b(7)、z+k(2)、z+n(3)、z+p(3)、z+q(9)、c+ch(9)、c+f(7)、c+g(6)、c+k(9)、c+n(3)、c+p(4)、c+q(9)、c+r(4)、s+b(9)、s+f(2)、s+g(2)、s+k(3)、s+n(3)、s+p(2)、s+q(5)、s+r(7)、s+t(4)、s+zh(6)、b+s(8)、h+c(5)、k+c(4)、k+s(9)、l+c(8)、m+c(9)、n+z(9)、n+c(3)、n+s(5)、p+c(3)、p+s(8)、r+z(7)、r+c(8)、r+s(2)

### retroflex_focus · 翘舌音单项

模式 `single_focus`；候选 5203 条；核心池 1060 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 1060 | OK |
| 10 分钟 | 150 | 1060 | OK |
| 15 分钟 | 225 | 1060 | OK |
| 20 分钟 | 300 | 1060 | OK |

**桶 core（核心 T×T，目标 80.0%）**

item 1060 条：单字 550 / 双字 510 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| zh | 206 |
| sh | 168 |
| ch | 133 |
| sh+sh | 65 |
| zh+sh | 64 |
| zh+zh | 63 |
| ch+sh | 58 |
| sh+zh | 54 |
| r | 43 |
| sh+ch | 33 |
| ch+ch | 29 |
| ch+zh | 28 |

稀缺（<10，3 个）：r+zh(6)、r+ch(7)、r+r(6)

**桶 supplement（补充 T↔O，目标 20.0%）**

item 4143 条：单字 0 / 双字 3950 / 三字+ 193

| pattern | 候选数 |
|---|---:|
| sh+ZERO | 123 |
| zh+ZERO | 116 |
| ZERO+sh | 99 |
| j+sh | 93 |
| sh+j | 80 |
| x+sh | 80 |
| ZERO+zh | 77 |
| j+zh | 71 |
| sh+l | 70 |
| sh+x | 70 |
| zh+j | 68 |
| ch+j | 64 |

稀缺（<10，20 个）：ch+n(8)、r+b(4)、r+c(8)、r+f(1)、r+g(7)、r+k(5)、r+n(3)、r+p(2)、r+s(2)、r+t(5)、r+z(7)、c+ch(9)、c+r(4)、k+r(6)、n+zh(8)、n+ch(5)、n+r(9)、p+r(7)、s+zh(6)、s+r(7)

### flat_retroflex_contrast · 平翘舌对比（含 r）

模式 `contrast`；候选 6738 条；核心池 1692 条；allow_other=False

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 93 | 1692 | OK |
| 10 分钟 | 187 | 1692 | OK |
| 15 分钟 | 281 | 1692 | OK |
| 20 分钟 | 375 | 1692 | OK |

**桶 cross（跨组 A↔B，目标 60.0%）**

item 368 条：单字 0 / 双字 367 / 三字+ 1

| pattern | 候选数 |
|---|---:|
| sh+z | 36 |
| zh+z | 31 |
| s+sh | 29 |
| ch+z | 28 |
| z+zh | 26 |
| z+sh | 25 |
| c+zh | 21 |
| c+sh | 20 |
| sh+s | 19 |
| sh+c | 17 |
| ch+s | 13 |
| z+ch | 13 |

稀缺（<10，7 个）：c+ch(8)、c+r(4)、s+zh(5)、s+r(6)、r+z(6)、r+c(6)、r+s(1)

**桶 same（同组 A+A / B+B，目标 40.0%）**

item 1324 条：单字 745 / 双字 579 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| zh | 206 |
| sh | 168 |
| ch | 133 |
| s | 77 |
| sh+sh | 65 |
| zh+sh | 64 |
| zh+zh | 63 |
| z | 60 |
| c | 58 |
| ch+sh | 58 |
| sh+zh | 54 |
| r | 43 |

稀缺（<10，10 个）：z+z(7)、z+c(5)、z+s(9)、c+z(6)、c+s(9)、s+c(4)、s+s(7)、r+zh(6)、r+ch(7)、r+r(6)

### flat_retroflex_contrast_no_r · 平翘舌对比（不含 r）

模式 `contrast`；候选 6261 条；核心池 1525 条；allow_other=False

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 93 | 1525 | OK |
| 10 分钟 | 187 | 1525 | OK |
| 15 分钟 | 281 | 1525 | OK |
| 20 分钟 | 375 | 1525 | OK |

**桶 cross（跨组 A↔B，目标 60.0%）**

item 335 条：单字 0 / 双字 334 / 三字+ 1

| pattern | 候选数 |
|---|---:|
| sh+z | 36 |
| zh+z | 31 |
| s+sh | 29 |
| ch+z | 28 |
| z+zh | 26 |
| z+sh | 25 |
| c+zh | 21 |
| c+sh | 20 |
| sh+s | 19 |
| sh+c | 17 |
| ch+s | 13 |
| z+ch | 13 |

稀缺（<10，2 个）：c+ch(8)、s+zh(5)

**桶 same（同组 A+A / B+B，目标 40.0%）**

item 1190 条：单字 702 / 双字 488 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| zh | 206 |
| sh | 168 |
| ch | 133 |
| s | 77 |
| sh+sh | 65 |
| zh+sh | 64 |
| zh+zh | 63 |
| z | 60 |
| c | 58 |
| ch+sh | 58 |
| sh+zh | 54 |
| sh+ch | 33 |

稀缺（<10，7 个）：z+z(7)、z+c(5)、z+s(9)、c+z(6)、c+s(9)、s+c(4)、s+s(7)

### n_l_contrast · n/l 对比

模式 `contrast`；候选 2121 条；核心池 332 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 93 | 332 | OK |
| 10 分钟 | 187 | 332 | OK |
| 15 分钟 | 281 | 332 | OK |
| 20 分钟 | 375 | 332 | need_repeat |

**桶 core（核心 n/l 内部，目标 80.0%）**

item 332 条：单字 253 / 双字 79 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| l | 184 |
| n | 69 |
| l+l | 44 |
| n+l | 20 |
| l+n | 8 |
| n+n | 7 |

稀缺（<10，2 个）：n+n(7)、l+n(8)

**桶 supplement（补充 n/l↔O，目标 20.0%）**

item 1789 条：单字 0 / 双字 1690 / 三字+ 99

| pattern | 候选数 |
|---|---:|
| ZERO+l | 108 |
| l+ZERO | 74 |
| sh+l | 70 |
| j+l | 67 |
| d+l | 62 |
| x+l | 60 |
| h+l | 52 |
| l+j | 52 |
| zh+l | 51 |
| b+l | 50 |
| l+sh | 49 |
| l+x | 48 |

稀缺（<10，27 个）：n+b(8)、n+c(3)、n+ch(5)、n+f(8)、n+p(4)、n+q(6)、n+r(9)、n+s(5)、n+t(8)、n+z(9)、n+zh(8)、l+c(8)、l+p(9)、b+n(5)、c+n(3)、ch+n(8)、d+n(8)、f+n(7)、h+n(6)、k+n(1)、m+n(9)、p+n(1)、q+n(7)、r+n(3)、s+n(3)、t+n(3)、z+n(3)

### jqx_special · j/q/x 尖音问题

模式 `special_mix`；候选 5132 条；核心池 1064 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 65 | 1064 | OK |
| 10 分钟 | 131 | 1064 | OK |
| 15 分钟 | 197 | 1064 | OK |
| 20 分钟 | 262 | 1064 | OK |

**桶 jqx_core（核心 J×J，目标 70.0%）**

item 1064 条：单字 556 / 双字 506 / 三字+ 2

| pattern | 候选数 |
|---|---:|
| j | 244 |
| x | 183 |
| q | 129 |
| j+j | 104 |
| x+j | 68 |
| x+x | 66 |
| j+x | 61 |
| q+j | 53 |
| x+q | 47 |
| q+x | 46 |
| j+q | 41 |
| q+q | 24 |

**桶 flat_relation（平舌关联 J↔Z，目标 20.0%）**

item 297 条：单字 0 / 双字 293 / 三字+ 4

| pattern | 候选数 |
|---|---:|
| j+z | 32 |
| z+j | 32 |
| j+s | 24 |
| x+z | 22 |
| c+j | 20 |
| j+c | 20 |
| q+z | 17 |
| x+s | 17 |
| s+x | 16 |
| z+x | 16 |
| c+x | 14 |
| q+c | 14 |

稀缺（<10，4 个）：x+c(9)、z+q(7)、c+q(9)、s+q(5)

**桶 jqx_other（其他补充 J↔O，目标 10.0%）**

item 3771 条：单字 0 / 双字 3555 / 三字+ 216

| pattern | 候选数 |
|---|---:|
| ZERO+j | 130 |
| j+ZERO | 127 |
| x+ZERO | 119 |
| ZERO+x | 108 |
| j+sh | 93 |
| sh+j | 80 |
| x+sh | 80 |
| ZERO+q | 72 |
| j+zh | 71 |
| q+ZERO | 71 |
| sh+x | 70 |
| j+d | 68 |

稀缺（<10，2 个）：q+n(7)、n+q(6)

### velar_focus · 舌根音单项

模式 `single_focus`；候选 3219 条；核心池 535 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 535 | OK |
| 10 分钟 | 150 | 535 | OK |
| 15 分钟 | 225 | 535 | OK |
| 20 分钟 | 300 | 535 | OK |

**桶 core（核心 T×T，目标 80.0%）**

item 535 条：单字 324 / 双字 210 / 三字+ 1

| pattern | 候选数 |
|---|---:|
| h | 137 |
| g | 114 |
| k | 73 |
| h+h | 44 |
| g+g | 30 |
| g+h | 30 |
| h+g | 25 |
| k+h | 25 |
| g+k | 19 |
| k+g | 14 |
| h+k | 13 |
| k+k | 12 |

**桶 supplement（补充 T↔O，目标 20.0%）**

item 2684 条：单字 0 / 双字 2563 / 三字+ 121

| pattern | 候选数 |
|---|---:|
| ZERO+h | 96 |
| g+ZERO | 89 |
| h+ZERO | 87 |
| g+j | 59 |
| ZERO+g | 58 |
| h+x | 55 |
| j+h | 53 |
| h+l | 52 |
| h+sh | 51 |
| sh+h | 48 |
| x+h | 48 |
| g+d | 47 |

稀缺（<10，18 个）：k+c(4)、k+m(7)、k+n(1)、k+p(5)、k+r(6)、k+s(9)、h+c(5)、h+n(6)、c+g(6)、c+k(9)、m+k(8)、p+g(6)、p+k(6)、r+g(7)、r+k(5)、s+g(2)、s+k(3)、z+k(2)

### dt_focus · d/t 舌尖中音强化

模式 `single_focus`；候选 2809 条；核心池 410 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 410 | OK |
| 10 分钟 | 150 | 410 | OK |
| 15 分钟 | 225 | 410 | OK |
| 20 分钟 | 300 | 410 | OK |

**桶 core（核心 T×T，目标 80.0%）**

item 410 条：单字 259 / 双字 151 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| d | 154 |
| t | 105 |
| d+d | 58 |
| t+t | 33 |
| d+t | 31 |
| t+d | 29 |

**桶 supplement（补充 T↔O，目标 20.0%）**

item 2399 条：单字 0 / 双字 2285 / 三字+ 114

| pattern | 候选数 |
|---|---:|
| d+ZERO | 93 |
| ZERO+d | 85 |
| j+d | 68 |
| t+x | 66 |
| d+j | 63 |
| d+l | 62 |
| t+ZERO | 59 |
| zh+d | 57 |
| d+x | 56 |
| ch+d | 50 |
| ZERO+t | 48 |
| d+sh | 48 |

稀缺（<10，5 个）：d+n(8)、t+n(3)、n+t(8)、r+t(5)、s+t(4)

### simple_final_focus · 单韵母综合

模式 `single_focus`；候选 6634 条；核心池 1678 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 1678 | OK |
| 10 分钟 | 150 | 1678 | OK |
| 15 分钟 | 225 | 1678 | OK |
| 20 分钟 | 300 | 1678 | OK |

**桶 core（核心 T×T，目标 80.0%）**

item 1678 条：单字 748 / 双字 922 / 三字+ 8

| pattern | 候选数 |
|---|---:|
| u | 221 |
| i | 202 |
| u+i | 122 |
| i+i | 101 |
| u+u | 98 |
| ü | 96 |
| a | 95 |
| e | 92 |
| i+u | 89 |
| e+i | 48 |
| i+ü | 45 |
| u+e | 42 |

缺失（0 候选，7 个）：a+er、o+ü、o+er、ü+o、er+a、er+o、er+er

稀缺（<10，19 个）：a+o(3)、o+a(7)、o+o(2)、o+e(4)、o+u(6)、e+a(4)、e+o(4)、e+er(1)、i+o(7)、i+er(1)、u+o(9)、u+er(3)、ü+a(4)、ü+ü(8)、ü+er(1)、er+e(1)、er+i(2)、er+u(2)、er+ü(2)

**桶 supplement（补充 T↔O，目标 20.0%）**

item 4956 条：单字 0 / 双字 4681 / 三字+ 275

| pattern | 候选数 |
|---|---:|
| ian+i | 79 |
| ing+i | 77 |
| i+-i_back | 69 |
| u+-i_back | 61 |
| an+u | 58 |
| ian+u | 58 |
| ong+i | 57 |
| -i_back+i | 56 |
| ao+i | 52 |
| eng+i | 50 |
| in+i | 50 |
| -i_back+u | 49 |

缺失（0 候选，61 个）：a+iong、a+uai、a+ueng、o+en、o+ia、o+in、o+iong、o+ueng、o+üan、o+ün、e+ueng、i+ueng、ü+iong、ü+ueng、ü+ün、er+ai、er+ang、er+ao、er+en、er+eng、er+ia、er+ian、er+iang、er+iong、er+iou、er+ua、er+uai、er+uei、er+ueng、er+üe、er+ün、-i_front+er、ang+er、ei+o、ei+er、eng+er、ia+er、iang+o、iang+er、ie+er、iong+er、ua+o、ua+er、uai+a、uai+er、uan+er、uang+er、uei+er、uen+er、ueng+a、ueng+o、ueng+e、ueng+i、ueng+u、ueng+ü、ueng+er、uo+er、üan+er、üe+o、ün+o、ün+er

稀缺（<10，200 个）：a+-i_front(9)、a+ei(7)、a+eng(6)、a+ia(6)、a+in(5)、a+iou(5)、a+ou(9)、a+ua(8)、a+uan(8)、a+uang(3)、a+uen(6)、a+üan(7)、a+ün(2)、o+-i_back(7)、o+-i_front(2)、o+ai(3)、o+an(9)、o+ang(4)、o+ao(3)、o+ei(1)、o+eng(4)、o+ian(3)、o+iang(1)、o+iao(1)、o+ie(2)、o+ing(2)、o+iou(1)、o+ong(4)、o+ou(2)、o+ua(1)、o+uai(1)、o+uan(2)、o+uang(1)、o+uei(4)、o+uen(2)、o+uo(6)、o+üe(2)、e+-i_front(9)、e+an(7)、e+ao(6)、e+ei(4)、e+ia(1)、e+iang(7)、e+iao(6)、e+in(4)、e+iong(2)、e+iou(8)、e+ong(6)、e+ua(3)、e+uai(4)、e+uang(7)、e+uen(7)、e+uo(9)、e+üan(4)、e+üe(9)、e+ün(2)、i+iong(2)、i+ua(9)、i+uai(5)、i+ün(6)、u+ei(9)、u+iong(8)、u+ua(6)、u+uai(4)、u+ueng(1)、u+ün(5)、ü+-i_front(6)、ü+ai(5)、ü+an(9)、ü+ang(9)、ü+ao(5)、ü+ei(5)、ü+en(6)、ü+eng(5)、ü+ia(2)、ü+iang(6)、ü+ie(5)、ü+in(6)、ü+ing(9)、ü+iou(6)、ü+ou(5)、ü+ua(3)、ü+uai(1)、ü+uan(7)、ü+uang(5)、ü+uei(7)、ü+uen(4)、ü+uo(7)、ü+üan(2)、ü+üe(6)、er+-i_back(1)、er+-i_front(1)、er+an(1)、er+ei(1)、er+iao(1)、er+ie(1)、er+in(1)、er+ing(1)、er+ong(2)、er+ou(3)、er+uan(1)、er+uang(1)、er+uen(1)、er+uo(1)、er+üan(1)、-i_back+a(4)、-i_back+o(3)、-i_back+er(2)、-i_front+a(6)、-i_front+o(1)、-i_front+e(4)、ai+a(5)、ai+o(3)、ai+ü(7)、ai+er(1)、an+o(7)、an+er(1)、ang+a(8)、ang+o(2)、ang+ü(5)、ao+o(6)、ao+er(2)、ei+a(5)、ei+e(7)、ei+ü(8)、en+a(8)、en+o(4)、en+ü(6)、en+er(2)、eng+o(5)、ia+a(8)、ia+o(1)、ia+e(7)、ia+ü(8)、ian+o(6)、ian+er(2)、iang+a(3)、iang+e(6)、iang+ü(3)、iao+a(8)、iao+o(5)、iao+er(1)、ie+a(3)、ie+o(3)、in+a(8)、in+o(4)、in+e(9)、in+er(2)、ing+a(9)、ing+o(3)、ing+er(4)、iong+a(1)、iong+o(1)、iong+e(1)、iong+i(6)、iong+u(8)、iong+ü(2)、iou+a(5)、iou+o(2)、iou+e(4)、iou+ü(9)、iou+er(2)、ong+o(3)、ong+er(2)、ou+o(4)、ou+er(2)、ua+a(1)、ua+e(5)、ua+u(6)、ua+ü(2)、uai+o(2)、uai+e(3)、uai+i(9)、uai+u(8)、uai+ü(2)、uan+a(7)、uan+o(5)、uang+a(3)、uang+o(6)、uang+e(4)、uang+ü(5)、uei+o(3)、uen+a(3)、uen+o(2)、uen+e(9)、uen+ü(7)、uo+a(9)、uo+o(5)、üan+a(2)、üan+o(1)、üan+e(2)、üan+ü(5)、üe+a(4)、üe+e(9)、üe+ü(2)、üe+er(2)、ün+a(2)、ün+e(2)、ün+i(9)、ün+ü(6)

### compound_all · 复韵母综合

模式 `single_focus`；候选 7070 条；核心池 1875 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 1875 | OK |
| 10 分钟 | 150 | 1875 | OK |
| 15 分钟 | 225 | 1875 | OK |
| 20 分钟 | 300 | 1875 | OK |

**桶 core（核心 复韵母×复韵母，目标 80.0%）**

item 1875 条：单字 868 / 双字 1003 / 三字+ 4

| pattern | 候选数 |
|---|---:|
| ao | 128 |
| iao | 100 |
| uei | 96 |
| ie | 87 |
| ai | 83 |
| ou | 82 |
| uo | 71 |
| iou | 63 |
| ei | 53 |
| üe | 34 |
| ia | 30 |
| ao+ao | 28 |

缺失（0 候选，14 个）：ia+ia、ia+uei、ia+üe、ie+ia、iou+uai、ou+uai、ua+iou、uai+ei、uai+ou、uai+ua、uai+uai、uai+üe、üe+uai、üe+üe

稀缺（<10，112 个）：ai+ei(2)、ai+ia(5)、ai+iao(8)、ai+ua(4)、ai+uai(4)、ai+uei(9)、ai+üe(4)、ao+ia(9)、ao+iou(9)、ao+ua(3)、ao+uai(1)、ao+üe(3)、ei+ai(6)、ei+ao(7)、ei+ei(3)、ei+ia(2)、ei+iao(5)、ei+ie(6)、ei+iou(5)、ei+ou(4)、ei+ua(4)、ei+uai(2)、ei+uo(2)、ei+üe(3)、ia+ai(5)、ia+ao(4)、ia+ei(2)、ia+iao(5)、ia+ie(7)、ia+iou(3)、ia+ou(2)、ia+ua(2)、ia+uai(1)、ia+uo(7)、iao+ei(3)、iao+ia(3)、iao+iou(3)、iao+ua(6)、iao+uai(3)、iao+üe(7)、ie+ai(8)、ie+ao(7)、ie+ei(1)、ie+iao(4)、ie+ie(4)、ie+iou(1)、ie+ua(1)、ie+uai(1)、ie+uei(3)、ie+üe(5)、iou+ao(3)、iou+ei(4)、iou+ia(4)、iou+iao(7)、iou+ie(3)、iou+iou(4)、iou+ou(7)、iou+ua(3)、iou+uei(5)、iou+uo(5)、iou+üe(5)、ou+ei(6)、ou+ia(4)、ou+ie(6)、ou+iou(5)、ou+ou(8)、ou+ua(2)、ou+üe(3)、ua+ai(2)、ua+ao(3)、ua+ei(5)、ua+ia(2)、ua+iao(4)、ua+ie(1)、ua+ou(1)、ua+ua(1)、ua+uai(1)、ua+uei(3)、ua+uo(2)、ua+üe(4)、uai+ai(5)、uai+ao(6)、uai+ia(1)、uai+iao(5)、uai+ie(2)、uai+iou(1)、uai+uei(3)、uai+uo(4)、uei+ei(5)、uei+ia(2)、uei+uai(1)、uei+üe(5)、uo+ao(4)、uo+ei(2)、uo+ia(2)、uo+iao(8)、uo+ie(8)、uo+iou(3)、uo+ua(5)、uo+uai(1)、uo+üe(3)、üe+ai(5)、üe+ao(4)、üe+ei(2)、üe+ia(3)、üe+iao(3)、üe+ie(7)、üe+iou(1)、üe+ou(2)、üe+ua(1)、üe+uei(8)、üe+uo(3)

**桶 supplement（补充 复韵母↔其他，目标 20.0%）**

item 5195 条：单字 0 / 双字 4947 / 三字+ 248

| pattern | 候选数 |
|---|---:|
| ao+i | 52 |
| ao+u | 45 |
| uei+i | 44 |
| iou+i | 40 |
| uei+u | 40 |
| ai+u | 37 |
| u+ou | 36 |
| u+iao | 35 |
| i+ai | 33 |
| ao+an | 32 |
| iao+u | 32 |
| uo+i | 32 |

缺失（0 候选，69 个）：ai+ueng、ao+ueng、ei+er、ei+o、ei+ueng、ia+er、ia+ueng、iao+ueng、ie+er、ie+ueng、ie+ün、iou+ueng、iou+ün、ou+ueng、ua+er、ua+iong、ua+o、ua+ueng、ua+ün、uai+a、uai+er、uai+iang、uai+iong、uai+ueng、uai+üan、uei+er、uei+iong、uei+ueng、uo+er、uo+ueng、üe+iong、üe+o、üe+ueng、üe+ün、-i_back+uai、a+uai、eng+uai、er+ai、er+ao、er+ia、er+iou、er+ua、er+uai、er+uei、er+üe、in+ia、iong+ei、iong+ia、iong+iao、iong+ua、iong+uo、o+ia、ueng+ai、ueng+ao、ueng+ei、ueng+ia、ueng+iao、ueng+ie、ueng+iou、ueng+ou、ueng+ua、ueng+uai、ueng+uei、ueng+uo、ueng+üe、ün+ia、ün+ie、ün+uai、ün+üe

稀缺（<10，373 个）：ai+a(5)、ai+en(8)、ai+er(1)、ai+iang(7)、ai+iong(2)、ai+o(3)、ai+uang(8)、ai+uen(5)、ai+ü(7)、ai+ün(3)、ao+en(6)、ao+er(2)、ao+in(8)、ao+iong(1)、ao+o(6)、ao+uang(4)、ao+uen(8)、ao+üan(4)、ao+ün(3)、ei+-i_back(6)、ei+-i_front(4)、ei+a(5)、ei+e(7)、ei+en(7)、ei+eng(4)、ei+iang(5)、ei+in(7)、ei+iong(2)、ei+uan(5)、ei+uang(1)、ei+uen(2)、ei+ü(8)、ei+üan(1)、ei+ün(3)、ia+-i_front(6)、ia+a(8)、ia+an(5)、ia+ang(4)、ia+e(7)、ia+en(4)、ia+eng(3)、ia+ian(5)、ia+iang(8)、ia+in(3)、ia+ing(6)、ia+iong(1)、ia+o(1)、ia+ong(7)、ia+uan(1)、ia+uang(3)、ia+uen(1)、ia+ü(8)、ia+üan(2)、ia+ün(3)、iao+-i_front(9)、iao+a(8)、iao+en(8)、iao+er(1)、iao+in(8)、iao+iong(1)、iao+o(5)、iao+uan(6)、iao+uang(7)、iao+uen(5)、iao+üan(5)、iao+ün(1)、ie+-i_front(6)、ie+a(3)、ie+an(8)、ie+ang(4)、ie+en(4)、ie+eng(7)、ie+iang(3)、ie+in(4)、ie+iong(1)、ie+o(3)、ie+ong(4)、ie+uan(7)、ie+uang(1)、ie+uen(4)、ie+üan(1)、iou+-i_front(6)、iou+a(5)、iou+e(4)、iou+er(2)、iou+iang(7)、iou+in(5)、iou+iong(2)、iou+o(2)、iou+ong(4)、iou+uan(7)、iou+uang(3)、iou+uen(5)、iou+ü(9)、iou+üan(4)、ou+eng(8)、ou+er(2)、ou+iong(1)、ou+o(4)、ou+uan(6)、ou+uang(1)、ou+uen(4)、ou+üan(4)、ou+ün(2)、ua+-i_back(3)、ua+-i_front(5)、ua+a(1)、ua+an(7)、ua+ang(2)、ua+e(5)、ua+en(5)、ua+eng(1)、ua+ian(9)、ua+iang(2)、ua+in(3)、ua+ing(3)、ua+ong(5)、ua+u(6)、ua+uan(1)、ua+uang(3)、ua+uen(4)、ua+ü(2)、ua+üan(4)、uai+-i_back(4)、uai+-i_front(3)、uai+an(4)、uai+ang(4)、uai+e(3)、uai+en(2)、uai+eng(1)、uai+i(9)、uai+ian(9)、uai+in(3)、uai+ing(2)、uai+o(2)、uai+ong(1)、uai+u(8)、uai+uan(2)、uai+uang(1)、uai+uen(2)、uai+ü(2)、uai+ün(1)、uei+-i_front(7)、uei+iang(9)、uei+o(3)、uei+uan(8)、uei+uang(6)、uei+uen(9)、uei+üan(8)、uei+ün(4)、uo+-i_front(6)、uo+a(9)、uo+en(8)、uo+eng(6)、uo+iang(3)、uo+in(4)、uo+iong(2)、uo+o(5)、uo+uan(9)、uo+uang(6)、uo+uen(3)、uo+üan(5)、uo+ün(2)、üe+-i_back(9)、üe+-i_front(2)、üe+a(4)、üe+an(5)、üe+ang(3)、üe+e(9)、üe+en(2)、üe+eng(6)、üe+er(2)、üe+ian(6)、üe+iang(4)、üe+in(4)、üe+ong(3)、üe+uan(4)、üe+uang(2)、üe+uen(2)、üe+ü(2)、üe+üan(6)、-i_back+ei(5)、-i_back+ia(5)、-i_back+iou(8)、-i_back+ua(1)、-i_back+uo(8)、-i_back+üe(8)、-i_front+ai(9)、-i_front+ao(5)、-i_front+ei(5)、-i_front+ia(3)、-i_front+iao(5)、-i_front+ie(1)、-i_front+iou(6)、-i_front+ou(6)、-i_front+ua(2)、-i_front+uai(3)、-i_front+uei(8)、-i_front+uo(3)、-i_front+üe(2)、a+ei(7)、a+ia(6)、a+iou(5)、a+ou(9)、a+ua(8)、an+ei(8)、an+ia(8)、an+ua(8)、an+uai(4)、ang+ei(4)、ang+ia(5)、ang+iao(8)、ang+iou(5)、ang+ou(9)、ang+ua(1)、ang+uai(1)、ang+üe(5)、e+ao(6)、e+ei(4)、e+ia(1)、e+iao(6)、e+iou(8)、e+ua(3)、e+uai(4)、e+uo(9)、e+üe(9)、en+ei(6)、en+ia(7)、en+iao(2)、en+ie(9)、en+iou(6)、en+ua(4)、en+uai(1)、en+uo(8)、en+üe(1)、eng+ei(4)、eng+ia(8)、eng+ie(6)、eng+ua(2)、eng+üe(8)、er+ei(1)、er+iao(1)、er+ie(1)、er+ou(3)、er+uo(1)、i+ua(9)、i+uai(5)、ian+ei(8)、ian+ia(9)、ian+iou(7)、ian+uai(2)、ian+üe(7)、iang+ai(6)、iang+ao(6)、iang+ei(1)、iang+ia(6)、iang+iao(9)、iang+ie(5)、iang+ou(5)、iang+ua(4)、iang+uai(1)、iang+uei(4)、iang+uo(6)、iang+üe(3)、in+ei(4)、in+ie(9)、in+iou(5)、in+ua(4)、in+uai(2)、in+uo(6)、in+üe(9)、ing+ei(7)、ing+ua(7)、ing+uai(5)、ing+uo(6)、ing+üe(6)、iong+ai(1)、iong+ao(3)、iong+ie(1)、iong+iou(3)、iong+ou(3)、iong+uai(1)、iong+uei(2)、iong+üe(1)、o+ai(3)、o+ao(3)、o+ei(1)、o+iao(1)、o+ie(2)、o+iou(1)、o+ou(2)、o+ua(1)、o+uai(1)、o+uei(4)、o+uo(6)、o+üe(2)、ong+ei(7)、ong+ia(5)、ong+uai(4)、ong+üe(9)、u+ei(9)、u+ua(6)、u+uai(4)、uan+ai(5)、uan+ei(3)、uan+ia(8)、uan+iao(9)、uan+ie(8)、uan+iou(8)、uan+ou(9)、uan+ua(4)、uan+uai(2)、uan+uei(7)、uan+uo(9)、uan+üe(4)、uang+ai(6)、uang+ao(7)、uang+ei(3)、uang+ia(3)、uang+iao(1)、uang+ie(8)、uang+iou(3)、uang+ou(4)、uang+ua(4)、uang+uai(2)、uang+uei(4)、uang+uo(7)、uang+üe(2)、uen+ai(5)、uen+ao(8)、uen+ei(3)、uen+ia(1)、uen+iao(3)、uen+ie(2)、uen+iou(3)、uen+ou(5)、uen+ua(3)、uen+uai(1)、uen+uei(4)、uen+üe(2)、ü+ai(5)、ü+ao(5)、ü+ei(5)、ü+ia(2)、ü+ie(5)、ü+iou(6)、ü+ou(5)、ü+ua(3)、ü+uai(1)、ü+uei(7)、ü+uo(7)、ü+üe(6)、üan+ai(3)、üan+ei(1)、üan+ia(2)、üan+iao(5)、üan+ie(3)、üan+iou(4)、üan+ou(6)、üan+ua(2)、üan+uai(1)、üan+uei(7)、üan+uo(6)、üan+üe(2)、ün+ai(2)、ün+ao(4)、ün+ei(4)、ün+iao(3)、ün+iou(2)、ün+ou(1)、ün+ua(2)、ün+uei(4)、ün+uo(5)

### compound_front · 前响复韵母

模式 `single_focus`；候选 3075 条；核心池 523 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 523 | OK |
| 10 分钟 | 150 | 523 | OK |
| 15 分钟 | 225 | 523 | OK |
| 20 分钟 | 300 | 523 | OK |

**桶 core（核心 T×T，目标 80.0%）**

item 523 条：单字 346 / 双字 176 / 三字+ 1

| pattern | 候选数 |
|---|---:|
| ao | 128 |
| ai | 83 |
| ou | 82 |
| ei | 53 |
| ao+ao | 28 |
| ai+ao | 20 |
| ou+ao | 17 |
| ao+ai | 16 |
| ai+ou | 15 |
| ao+ou | 13 |
| ai+ai | 12 |
| ao+ei | 11 |

稀缺（<10，7 个）：ai+ei(2)、ei+ai(6)、ei+ei(3)、ei+ao(7)、ei+ou(4)、ou+ei(6)、ou+ou(8)

**桶 supplement（补充 T↔O，目标 20.0%）**

item 2552 条：单字 0 / 双字 2442 / 三字+ 110

| pattern | 候选数 |
|---|---:|
| ao+i | 52 |
| ao+u | 45 |
| ai+u | 37 |
| u+ou | 36 |
| i+ai | 33 |
| ao+an | 32 |
| an+ao | 30 |
| i+ao | 30 |
| u+ai | 30 |
| ou+u | 29 |
| ian+ai | 28 |
| ou+i | 27 |

缺失（0 候选，16 个）：ai+ueng、ei+er、ei+o、ei+ueng、ao+ueng、ou+uai、ou+ueng、er+ai、er+ao、iong+ei、uai+ei、uai+ou、ueng+ai、ueng+ei、ueng+ao、ueng+ou

稀缺（<10，143 个）：ai+a(5)、ai+en(8)、ai+er(1)、ai+ia(6)、ai+iang(7)、ai+iao(9)、ai+iong(2)、ai+o(3)、ai+ua(7)、ai+uai(4)、ai+uang(8)、ai+uen(5)、ai+ü(7)、ai+üe(4)、ai+ün(3)、ei+-i_back(6)、ei+-i_front(4)、ei+a(5)、ei+e(7)、ei+en(7)、ei+eng(4)、ei+ia(2)、ei+iang(5)、ei+iao(5)、ei+ie(7)、ei+in(7)、ei+iong(2)、ei+iou(5)、ei+ua(4)、ei+uai(2)、ei+uan(5)、ei+uang(1)、ei+uen(2)、ei+uo(3)、ei+ü(8)、ei+üan(1)、ei+üe(3)、ei+ün(3)、ao+en(6)、ao+er(2)、ao+ia(9)、ao+in(8)、ao+iong(1)、ao+o(6)、ao+ua(3)、ao+uai(1)、ao+uang(4)、ao+uen(8)、ao+üan(4)、ao+üe(3)、ao+ün(3)、ou+eng(8)、ou+er(2)、ou+ia(4)、ou+ie(6)、ou+iong(1)、ou+iou(6)、ou+o(4)、ou+ua(2)、ou+uan(6)、ou+uang(1)、ou+uen(4)、ou+üan(4)、ou+üe(3)、ou+ün(2)、-i_back+ei(5)、-i_front+ai(9)、-i_front+ei(5)、-i_front+ao(5)、-i_front+ou(6)、a+ei(7)、a+ou(9)、an+ei(8)、ang+ei(4)、ang+ou(9)、e+ei(4)、e+ao(6)、en+ei(6)、eng+ei(4)、er+ei(1)、er+ou(3)、ia+ai(5)、ia+ei(3)、ia+ao(4)、ia+ou(2)、ian+ei(8)、iang+ai(6)、iang+ei(1)、iang+ao(6)、iang+ou(5)、iao+ei(4)、ie+ai(9)、ie+ei(2)、ie+ao(7)、in+ei(4)、ing+ei(7)、iong+ai(1)、iong+ao(3)、iong+ou(3)、iou+ei(4)、iou+ao(3)、iou+ou(7)、o+ai(3)、o+ei(1)、o+ao(3)、o+ou(2)、ong+ei(7)、u+ei(9)、ua+ai(2)、ua+ei(5)、ua+ao(3)、ua+ou(1)、uai+ai(5)、uai+ao(6)、uan+ai(5)、uan+ei(3)、uan+ou(9)、uang+ai(6)、uang+ei(3)、uang+ao(7)、uang+ou(4)、uei+ei(5)、uen+ai(5)、uen+ei(3)、uen+ao(8)、uen+ou(5)、uo+ei(2)、uo+ao(4)、ü+ai(5)、ü+ei(5)、ü+ao(5)、ü+ou(5)、üan+ai(3)、üan+ei(1)、üan+ou(6)、üe+ai(5)、üe+ei(2)、üe+ao(4)、üe+ou(2)、ün+ai(2)、ün+ei(4)、ün+ao(4)、ün+ou(1)

### compound_middle · 中响复韵母

模式 `single_focus`；候选 2425 条；核心池 373 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 373 | OK |
| 10 分钟 | 150 | 373 | OK |
| 15 分钟 | 225 | 373 | OK |
| 20 分钟 | 300 | 373 | OK |

**桶 core（核心 T×T，目标 80.0%）**

item 373 条：单字 275 / 双字 98 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| iao | 100 |
| uei | 96 |
| iou | 63 |
| uai | 16 |
| iao+uei | 15 |
| uei+uei | 14 |
| iao+iao | 13 |
| uei+iao | 12 |
| uei+iou | 12 |
| iou+iao | 7 |
| iou+uei | 5 |
| uai+iao | 5 |

缺失（0 候选，2 个）：iou+uai、uai+uai

稀缺（<10，9 个）：iao+iou(3)、iao+uai(3)、iou+iao(7)、iou+iou(4)、iou+uei(5)、uai+iao(5)、uai+iou(1)、uai+uei(3)、uei+uai(1)

**桶 supplement（补充 T↔O，目标 20.0%）**

item 2052 条：单字 0 / 双字 1948 / 三字+ 104

| pattern | 候选数 |
|---|---:|
| uei+i | 44 |
| iou+i | 40 |
| uei+u | 40 |
| u+iao | 35 |
| iao+u | 32 |
| iao+i | 31 |
| i+uei | 30 |
| uei+ian | 28 |
| u+uei | 26 |
| i+iao | 25 |
| i+iou | 24 |
| iao+ian | 24 |

缺失（0 候选，31 个）：iao+ueng、iou+ueng、iou+ün、uai+a、uai+ei、uai+er、uai+iang、uai+iong、uai+ou、uai+ua、uai+ueng、uai+üan、uai+üe、uei+er、uei+iong、uei+ueng、-i_back+uai、a+uai、eng+uai、er+iou、er+uai、er+uei、iong+iao、ou+uai、ua+iou、ueng+iao、ueng+iou、ueng+uai、ueng+uei、üe+uai、ün+uai

稀缺（<10，154 个）：iao+-i_front(9)、iao+a(8)、iao+ei(4)、iao+en(8)、iao+er(1)、iao+ia(3)、iao+in(8)、iao+iong(1)、iao+o(5)、iao+ua(6)、iao+uan(6)、iao+uang(7)、iao+uen(5)、iao+üan(5)、iao+üe(8)、iao+ün(1)、iou+-i_front(6)、iou+a(5)、iou+ao(3)、iou+e(4)、iou+ei(4)、iou+er(2)、iou+ia(5)、iou+iang(7)、iou+ie(4)、iou+in(5)、iou+iong(2)、iou+o(2)、iou+ong(4)、iou+ou(7)、iou+ua(3)、iou+uan(7)、iou+uang(3)、iou+uen(5)、iou+uo(5)、iou+ü(9)、iou+üan(4)、iou+üe(5)、uai+-i_back(4)、uai+-i_front(3)、uai+ai(5)、uai+an(4)、uai+ang(4)、uai+ao(6)、uai+e(3)、uai+en(2)、uai+eng(1)、uai+i(9)、uai+ia(1)、uai+ian(9)、uai+ie(2)、uai+in(3)、uai+ing(2)、uai+o(2)、uai+ong(1)、uai+u(8)、uai+uan(2)、uai+uang(1)、uai+uen(2)、uai+uo(4)、uai+ü(2)、uai+ün(1)、uei+-i_front(7)、uei+ei(5)、uei+ia(2)、uei+iang(9)、uei+o(3)、uei+uan(8)、uei+uang(6)、uei+uen(9)、uei+üan(8)、uei+üe(6)、uei+ün(4)、-i_back+iou(8)、-i_front+iao(5)、-i_front+iou(6)、-i_front+uai(3)、-i_front+uei(8)、a+iou(5)、ai+iao(9)、ai+uai(4)、an+uai(4)、ang+iao(8)、ang+iou(5)、ang+uai(1)、ao+uai(1)、e+iao(6)、e+iou(8)、e+uai(4)、ei+iao(5)、ei+iou(5)、ei+uai(2)、en+iao(2)、en+iou(6)、en+uai(1)、er+iao(1)、i+uai(5)、ia+iao(5)、ia+iou(3)、ia+uai(1)、ia+uei(1)、ian+iou(7)、ian+uai(2)、iang+iao(9)、iang+uai(1)、iang+uei(4)、ie+iao(4)、ie+iou(2)、ie+uai(1)、ie+uei(3)、in+iou(5)、in+uai(2)、ing+uai(5)、iong+iou(3)、iong+uai(1)、iong+uei(2)、o+iao(1)、o+iou(1)、o+uai(1)、o+uei(4)、ong+uai(4)、ou+iou(6)、u+uai(4)、ua+iao(4)、ua+uai(2)、ua+uei(3)、uan+iao(9)、uan+iou(8)、uan+uai(2)、uan+uei(7)、uang+iao(1)、uang+iou(3)、uang+uai(2)、uang+uei(4)、uen+iao(3)、uen+iou(3)、uen+uai(1)、uen+uei(4)、uo+iao(8)、uo+iou(4)、uo+uai(1)、ü+iou(6)、ü+uai(1)、ü+uei(7)、üan+iao(5)、üan+iou(4)、üan+uai(1)、üan+uei(7)、üe+iao(3)、üe+iou(1)、üe+uei(8)、ün+iao(3)、ün+iou(2)、ün+uei(4)

### compound_back · 后响复韵母

模式 `single_focus`；候选 2278 条；核心池 339 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 339 | OK |
| 10 分钟 | 150 | 339 | OK |
| 15 分钟 | 225 | 339 | OK |
| 20 分钟 | 300 | 339 | OK |

**桶 core（核心 T×T，目标 80.0%）**

item 339 条：单字 247 / 双字 92 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| ie | 87 |
| uo | 71 |
| üe | 34 |
| ia | 30 |
| ua | 25 |
| ie+uo | 12 |
| uo+uo | 12 |
| uo+ie | 8 |
| ia+ie | 7 |
| ia+uo | 7 |
| üe+ie | 7 |
| ie+üe | 5 |

缺失（0 候选，4 个）：ia+ia、ia+üe、ie+ia、üe+üe

稀缺（<10，19 个）：ia+ie(7)、ia+ua(2)、ia+uo(7)、ie+ie(4)、ie+ua(1)、ie+üe(5)、ua+ia(2)、ua+ie(1)、ua+ua(1)、ua+uo(2)、ua+üe(4)、uo+ia(2)、uo+ie(8)、uo+ua(5)、uo+üe(3)、üe+ia(3)、üe+ie(7)、üe+ua(1)、üe+uo(3)

**桶 supplement（补充 T↔O，目标 20.0%）**

item 1939 条：单字 0 / 双字 1831 / 三字+ 108

| pattern | 候选数 |
|---|---:|
| uo+i | 32 |
| uo+u | 29 |
| u+uo | 26 |
| i+ie | 24 |
| ian+ie | 24 |
| u+ie | 24 |
| i+uo | 23 |
| ie+u | 23 |
| ie+-i_back | 22 |
| ie+i | 21 |
| ao+uo | 19 |
| ie+ian | 19 |

缺失（0 候选，36 个）：ia+er、ia+ueng、ie+er、ie+ueng、ie+ün、ua+er、ua+iong、ua+iou、ua+o、ua+ueng、ua+ün、uo+er、uo+ueng、üe+iong、üe+o、üe+uai、üe+ueng、üe+ün、er+ia、er+ua、er+üe、in+ia、iong+ia、iong+ua、iong+uo、o+ia、uai+ua、uai+üe、ueng+ia、ueng+ie、ueng+ua、ueng+uo、ueng+üe、ün+ia、ün+ie、ün+üe

稀缺（<10，228 个）：ia+-i_front(6)、ia+a(8)、ia+ai(5)、ia+an(5)、ia+ang(4)、ia+ao(4)、ia+e(7)、ia+ei(3)、ia+en(4)、ia+eng(3)、ia+ian(5)、ia+iang(8)、ia+iao(5)、ia+in(3)、ia+ing(6)、ia+iong(1)、ia+iou(3)、ia+o(1)、ia+ong(7)、ia+ou(2)、ia+uai(1)、ia+uan(1)、ia+uang(3)、ia+uei(1)、ia+uen(1)、ia+ü(8)、ia+üan(2)、ia+ün(3)、ie+-i_front(6)、ie+a(3)、ie+ai(9)、ie+an(8)、ie+ang(4)、ie+ao(7)、ie+ei(2)、ie+en(4)、ie+eng(7)、ie+iang(3)、ie+iao(4)、ie+in(4)、ie+iong(1)、ie+iou(2)、ie+o(3)、ie+ong(4)、ie+uai(1)、ie+uan(7)、ie+uang(1)、ie+uei(3)、ie+uen(4)、ie+üan(1)、ua+-i_back(3)、ua+-i_front(5)、ua+a(1)、ua+ai(2)、ua+an(7)、ua+ang(2)、ua+ao(3)、ua+e(5)、ua+ei(5)、ua+en(5)、ua+eng(1)、ua+ian(9)、ua+iang(2)、ua+iao(4)、ua+in(3)、ua+ing(3)、ua+ong(5)、ua+ou(1)、ua+u(6)、ua+uai(2)、ua+uan(1)、ua+uang(3)、ua+uei(3)、ua+uen(4)、ua+ü(2)、ua+üan(4)、uo+-i_front(6)、uo+a(9)、uo+ao(4)、uo+ei(2)、uo+en(8)、uo+eng(6)、uo+iang(3)、uo+iao(8)、uo+in(4)、uo+iong(2)、uo+iou(4)、uo+o(5)、uo+uai(1)、uo+uan(9)、uo+uang(6)、uo+uen(3)、uo+üan(5)、uo+ün(2)、üe+-i_back(9)、üe+-i_front(2)、üe+a(4)、üe+ai(5)、üe+an(5)、üe+ang(3)、üe+ao(4)、üe+e(9)、üe+ei(2)、üe+en(2)、üe+eng(6)、üe+er(2)、üe+ian(6)、üe+iang(4)、üe+iao(3)、üe+in(4)、üe+iou(1)、üe+ong(3)、üe+ou(2)、üe+uan(4)、üe+uang(2)、üe+uei(8)、üe+uen(2)、üe+ü(2)、üe+üan(6)、-i_back+ia(5)、-i_back+ua(1)、-i_back+uo(8)、-i_back+üe(8)、-i_front+ia(3)、-i_front+ie(1)、-i_front+ua(2)、-i_front+uo(3)、-i_front+üe(2)、a+ia(6)、a+ua(8)、ai+ia(6)、ai+ua(7)、ai+üe(4)、an+ia(8)、an+ua(8)、ang+ia(5)、ang+ua(1)、ang+üe(5)、ao+ia(9)、ao+ua(3)、ao+üe(3)、e+ia(1)、e+ua(3)、e+uo(9)、e+üe(9)、ei+ia(2)、ei+ie(7)、ei+ua(4)、ei+uo(3)、ei+üe(3)、en+ia(7)、en+ie(9)、en+ua(4)、en+uo(8)、en+üe(1)、eng+ia(8)、eng+ie(6)、eng+ua(2)、eng+üe(8)、er+ie(1)、er+uo(1)、i+ua(9)、ian+ia(9)、ian+üe(7)、iang+ia(6)、iang+ie(5)、iang+ua(4)、iang+uo(6)、iang+üe(3)、iao+ia(3)、iao+ua(6)、iao+üe(8)、in+ie(9)、in+ua(4)、in+uo(6)、in+üe(9)、ing+ua(7)、ing+uo(6)、ing+üe(6)、iong+ie(1)、iong+üe(1)、iou+ia(5)、iou+ie(4)、iou+ua(3)、iou+uo(5)、iou+üe(5)、o+ie(2)、o+ua(1)、o+uo(6)、o+üe(2)、ong+ia(5)、ong+üe(9)、ou+ia(4)、ou+ie(6)、ou+ua(2)、ou+üe(3)、u+ua(6)、uai+ia(1)、uai+ie(2)、uai+uo(4)、uan+ia(8)、uan+ie(8)、uan+ua(4)、uan+uo(9)、uan+üe(4)、uang+ia(3)、uang+ie(8)、uang+ua(4)、uang+uo(7)、uang+üe(2)、uei+ia(2)、uei+üe(6)、uen+ia(1)、uen+ie(2)、uen+ua(3)、uen+üe(2)、ü+ia(2)、ü+ie(5)、ü+ua(3)、ü+uo(7)、ü+üe(6)、üan+ia(2)、üan+ie(3)、üan+ua(2)、üan+uo(6)、üan+üe(2)、ün+ua(2)、ün+uo(5)

### front_nasal_basic · 前鼻音专项一（基础）

模式 `single_focus`；候选 2927 条；核心池 469 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 469 | OK |
| 10 分钟 | 150 | 469 | OK |
| 15 分钟 | 225 | 469 | OK |
| 20 分钟 | 300 | 469 | OK |

**桶 core（核心 T×T，目标 80.0%）**

item 469 条：单字 312 / 双字 157 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| an | 162 |
| en | 77 |
| in | 73 |
| an+an | 38 |
| in+in | 18 |
| en+an | 17 |
| en+en | 17 |
| in+an | 17 |
| en+in | 14 |
| an+en | 13 |
| an+in | 13 |
| in+en | 10 |

**桶 supplement（补充 T↔O，目标 20.0%）**

item 2458 条：单字 0 / 双字 2334 / 三字+ 124

| pattern | 候选数 |
|---|---:|
| an+u | 58 |
| in+i | 50 |
| an+i | 49 |
| u+an | 49 |
| en+i | 48 |
| i+an | 40 |
| en+ing | 39 |
| an+ian | 34 |
| an+ing | 34 |
| u+in | 34 |
| ao+an | 32 |
| u+en | 32 |

缺失（0 候选，9 个）：an+ueng、in+ia、in+ueng、er+en、o+en、o+in、ueng+an、ueng+en、ueng+in

稀缺（<10，105 个）：an+ei(8)、an+er(1)、an+ia(8)、an+iong(3)、an+o(7)、an+ua(8)、an+uai(4)、an+uang(9)、an+üan(7)、an+ün(6)、en+a(8)、en+ang(6)、en+ei(6)、en+er(2)、en+ia(7)、en+iang(7)、en+iao(2)、en+ie(9)、en+iong(2)、en+iou(6)、en+o(4)、en+ua(4)、en+uai(1)、en+uan(4)、en+uang(5)、en+uen(5)、en+ueng(1)、en+uo(8)、en+ü(6)、en+üan(8)、en+üe(1)、en+ün(6)、in+-i_front(8)、in+a(8)、in+e(9)、in+ei(4)、in+er(2)、in+iang(7)、in+ie(9)、in+iong(5)、in+iou(5)、in+o(4)、in+ong(7)、in+ua(4)、in+uai(2)、in+uan(5)、in+uang(4)、in+uen(7)、in+uo(6)、in+üan(6)、in+üe(9)、in+ün(5)、-i_front+en(4)、-i_front+in(6)、a+in(5)、ai+en(8)、ao+en(6)、ao+in(8)、e+an(7)、e+in(4)、ei+en(7)、ei+in(7)、er+an(1)、er+in(1)、ia+an(5)、ia+en(4)、ia+in(3)、iang+en(3)、iao+en(8)、iao+in(8)、ie+an(8)、ie+en(4)、ie+in(4)、iong+an(4)、iong+en(2)、iong+in(8)、iou+in(5)、o+an(9)、ua+an(7)、ua+en(5)、ua+in(3)、uai+an(4)、uai+en(2)、uai+in(3)、uan+en(7)、uan+in(5)、uang+en(2)、uang+in(6)、uen+an(9)、uen+en(6)、uen+in(5)、uo+en(8)、uo+in(4)、ü+an(9)、ü+en(6)、ü+in(6)、üan+an(6)、üan+en(4)、üan+in(7)、üe+an(5)、üe+en(2)、üe+in(4)、ün+an(3)、ün+en(3)、ün+in(1)

### front_nasal_extended · 前鼻音专项二（扩展）

模式 `single_focus`；候选 3147 条；核心池 528 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 528 | OK |
| 10 分钟 | 150 | 528 | OK |
| 15 分钟 | 225 | 528 | OK |
| 20 分钟 | 300 | 528 | OK |

**桶 core（核心 T×T，目标 80.0%）**

item 528 条：单字 352 / 双字 176 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| ian | 163 |
| uan | 66 |
| uen | 52 |
| ian+ian | 45 |
| üan | 40 |
| ün | 31 |
| ian+uan | 19 |
| uan+ian | 16 |
| uen+ian | 11 |
| üan+ian | 11 |
| ian+üan | 9 |
| uan+uan | 8 |

缺失（0 候选，1 个）：üan+ün

稀缺（<10，19 个）：ian+uen(7)、ian+üan(9)、ian+ün(3)、uan+uan(8)、uan+uen(3)、uan+üan(7)、uan+ün(2)、uen+uan(8)、uen+uen(4)、uen+üan(3)、uen+ün(1)、üan+uan(2)、üan+uen(3)、üan+üan(4)、ün+ian(2)、ün+uan(4)、ün+uen(1)、ün+üan(1)、ün+ün(2)

**桶 supplement（补充 T↔O，目标 20.0%）**

item 2619 条：单字 0 / 双字 2509 / 三字+ 110

| pattern | 候选数 |
|---|---:|
| ian+i | 79 |
| ian+u | 58 |
| i+ian | 47 |
| ian+ing | 45 |
| ian+-i_back | 37 |
| u+ian | 37 |
| ing+ian | 36 |
| an+ian | 34 |
| ong+ian | 33 |
| ian+e | 32 |
| -i_back+ian | 30 |
| uan+i | 30 |

缺失（0 候选，34 个）：ian+ueng、uan+er、uan+ueng、uen+er、uen+iang、uen+iong、uen+ueng、üan+er、üan+ueng、ün+er、ün+ia、ün+ie、ün+o、ün+uai、ün+ueng、ün+üe、-i_back+ün、er+ian、er+ün、ie+ün、iong+uan、iong+ün、iou+ün、o+üan、o+ün、ua+ün、uai+üan、ueng+ian、ueng+uan、ueng+uen、ueng+üan、ueng+ün、ü+ün、üe+ün

稀缺（<10，211 个）：ian+ei(8)、ian+er(2)、ian+ia(9)、ian+iong(1)、ian+iou(7)、ian+o(6)、ian+uai(2)、ian+uang(7)、ian+üe(7)、uan+-i_front(6)、uan+a(7)、uan+ai(5)、uan+ei(3)、uan+en(7)、uan+ia(8)、uan+iang(8)、uan+iao(9)、uan+ie(8)、uan+in(5)、uan+iong(3)、uan+iou(8)、uan+o(5)、uan+ou(9)、uan+ua(4)、uan+uai(2)、uan+uang(4)、uan+uei(7)、uan+uo(9)、uan+üe(4)、uen+-i_front(6)、uen+a(3)、uen+ai(5)、uen+an(9)、uen+ang(9)、uen+ao(8)、uen+e(9)、uen+ei(3)、uen+en(6)、uen+eng(8)、uen+ia(1)、uen+iao(3)、uen+ie(2)、uen+in(5)、uen+iou(3)、uen+o(2)、uen+ong(7)、uen+ou(5)、uen+ua(3)、uen+uai(1)、uen+uang(4)、uen+uei(4)、uen+ü(7)、uen+üe(2)、üan+-i_back(5)、üan+-i_front(4)、üan+a(2)、üan+ai(3)、üan+an(6)、üan+ang(4)、üan+e(2)、üan+ei(1)、üan+en(4)、üan+eng(7)、üan+ia(2)、üan+iang(7)、üan+iao(5)、üan+ie(3)、üan+in(7)、üan+ing(6)、üan+iong(1)、üan+iou(4)、üan+o(1)、üan+ong(4)、üan+ou(6)、üan+ua(2)、üan+uai(1)、üan+uang(3)、üan+uei(7)、üan+uo(6)、üan+ü(5)、üan+üe(2)、ün+-i_back(4)、ün+-i_front(2)、ün+a(2)、ün+ai(2)、ün+an(3)、ün+ang(3)、ün+ao(4)、ün+e(2)、ün+ei(4)、ün+en(3)、ün+eng(4)、ün+i(9)、ün+iang(3)、ün+iao(3)、ün+in(1)、ün+ing(3)、ün+iong(3)、ün+iou(2)、ün+ong(6)、ün+ou(1)、ün+ua(2)、ün+uang(1)、ün+uei(4)、ün+uo(5)、ün+ü(6)、-i_back+uen(8)、-i_back+üan(7)、-i_front+ian(9)、-i_front+uan(2)、-i_front+uen(5)、-i_front+üan(3)、-i_front+ün(1)、a+uan(8)、a+uen(6)、a+üan(7)、a+ün(2)、ai+uen(5)、ai+ün(3)、an+üan(7)、an+ün(6)、ang+uen(2)、ang+üan(8)、ang+ün(4)、ao+uen(8)、ao+üan(4)、ao+ün(3)、e+uen(7)、e+üan(4)、e+ün(2)、ei+uan(5)、ei+uen(2)、ei+üan(1)、ei+ün(3)、en+uan(4)、en+uen(5)、en+üan(8)、en+ün(6)、eng+uan(6)、eng+uen(8)、eng+üan(8)、eng+ün(5)、er+uan(1)、er+uen(1)、er+üan(1)、i+ün(6)、ia+ian(5)、ia+uan(1)、ia+uen(1)、ia+üan(2)、ia+ün(3)、iang+uan(2)、iang+uen(3)、iang+üan(2)、iang+ün(1)、iao+uan(6)、iao+uen(5)、iao+üan(5)、iao+ün(1)、ie+uan(7)、ie+uen(4)、ie+üan(1)、in+uan(5)、in+uen(7)、in+üan(6)、in+ün(5)、ing+ün(8)、iong+ian(2)、iong+uen(2)、iong+üan(1)、iou+uan(7)、iou+uen(5)、iou+üan(4)、o+ian(3)、o+uan(2)、o+uen(2)、ong+uen(5)、ong+üan(6)、ong+ün(7)、ou+uan(6)、ou+uen(4)、ou+üan(4)、ou+ün(2)、u+ün(5)、ua+ian(9)、ua+uan(1)、ua+uen(4)、ua+üan(4)、uai+ian(9)、uai+uan(2)、uai+uen(2)、uai+ün(1)、uang+uan(6)、uang+uen(1)、uang+üan(6)、uang+ün(1)、uei+uan(8)、uei+uen(9)、uei+üan(8)、uei+ün(4)、uo+uan(9)、uo+uen(3)、uo+üan(5)、uo+ün(2)、ü+uan(7)、ü+uen(4)、ü+üan(2)、üe+ian(6)、üe+uan(4)、üe+uen(2)、üe+üan(6)

### front_nasal_all · 前鼻音综合

模式 `single_focus`；候选 5774 条；核心池 1279 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 1279 | OK |
| 10 分钟 | 150 | 1279 | OK |
| 15 分钟 | 225 | 1279 | OK |
| 20 分钟 | 300 | 1279 | OK |

**桶 core（核心 T×T，目标 80.0%）**

item 1279 条：单字 664 / 双字 615 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| ian | 163 |
| an | 162 |
| en | 77 |
| in | 73 |
| uan | 66 |
| uen | 52 |
| ian+ian | 45 |
| üan | 40 |
| an+an | 38 |
| an+ian | 33 |
| ün | 31 |
| ian+en | 22 |

缺失（0 候选，1 个）：üan+ün

稀缺（<10，40 个）：an+üan(7)、an+ün(6)、en+uan(4)、en+uen(5)、en+üan(8)、en+ün(6)、ian+uen(7)、ian+üan(9)、ian+ün(3)、in+uan(5)、in+uen(7)、in+üan(6)、in+ün(5)、uan+en(7)、uan+in(5)、uan+uan(8)、uan+uen(3)、uan+üan(7)、uan+ün(2)、uen+an(9)、uen+en(6)、uen+in(5)、uen+uan(8)、uen+uen(4)、uen+üan(3)、uen+ün(1)、üan+an(6)、üan+en(4)、üan+in(7)、üan+uan(2)、üan+uen(3)、üan+üan(4)、ün+an(3)、ün+en(3)、ün+ian(2)、ün+in(1)、ün+uan(4)、ün+uen(1)、ün+üan(1)、ün+ün(2)

**桶 supplement（补充 T↔O，目标 20.0%）**

item 4495 条：单字 0 / 双字 4279 / 三字+ 216

| pattern | 候选数 |
|---|---:|
| ian+i | 79 |
| an+u | 58 |
| ian+u | 58 |
| in+i | 50 |
| an+i | 49 |
| u+an | 49 |
| en+i | 48 |
| i+ian | 47 |
| ian+ing | 45 |
| i+an | 40 |
| en+ing | 39 |
| ian+-i_back | 37 |

缺失（0 候选，43 个）：an+ueng、ian+ueng、in+ia、in+ueng、uan+er、uan+ueng、uen+er、uen+iang、uen+iong、uen+ueng、üan+er、üan+ueng、ün+er、ün+ia、ün+ie、ün+o、ün+uai、ün+ueng、ün+üe、-i_back+ün、er+en、er+ian、er+ün、ie+ün、iong+uan、iong+ün、iou+ün、o+en、o+in、o+üan、o+ün、ua+ün、uai+üan、ueng+an、ueng+en、ueng+ian、ueng+in、ueng+uan、ueng+uen、ueng+üan、ueng+ün、ü+ün、üe+ün

稀缺（<10，274 个）：an+ei(8)、an+er(1)、an+ia(8)、an+iong(3)、an+o(7)、an+ua(8)、an+uai(4)、an+uang(9)、en+a(8)、en+ang(6)、en+ei(6)、en+er(2)、en+ia(7)、en+iang(7)、en+iao(2)、en+ie(9)、en+iong(2)、en+iou(6)、en+o(4)、en+ua(4)、en+uai(1)、en+uang(5)、en+ueng(1)、en+uo(8)、en+ü(6)、en+üe(1)、ian+ei(8)、ian+er(2)、ian+ia(9)、ian+iong(1)、ian+iou(7)、ian+o(6)、ian+uai(2)、ian+uang(7)、ian+üe(7)、in+-i_front(8)、in+a(8)、in+e(9)、in+ei(4)、in+er(2)、in+iang(7)、in+ie(9)、in+iong(5)、in+iou(5)、in+o(4)、in+ong(7)、in+ua(4)、in+uai(2)、in+uang(4)、in+uo(6)、in+üe(9)、uan+-i_front(6)、uan+a(7)、uan+ai(5)、uan+ei(3)、uan+ia(8)、uan+iang(8)、uan+iao(9)、uan+ie(8)、uan+iong(3)、uan+iou(8)、uan+o(5)、uan+ou(9)、uan+ua(4)、uan+uai(2)、uan+uang(4)、uan+uei(7)、uan+uo(9)、uan+üe(4)、uen+-i_front(6)、uen+a(3)、uen+ai(5)、uen+ang(9)、uen+ao(8)、uen+e(9)、uen+ei(3)、uen+eng(8)、uen+ia(1)、uen+iao(3)、uen+ie(2)、uen+iou(3)、uen+o(2)、uen+ong(7)、uen+ou(5)、uen+ua(3)、uen+uai(1)、uen+uang(4)、uen+uei(4)、uen+ü(7)、uen+üe(2)、üan+-i_back(5)、üan+-i_front(4)、üan+a(2)、üan+ai(3)、üan+ang(4)、üan+e(2)、üan+ei(1)、üan+eng(7)、üan+ia(2)、üan+iang(7)、üan+iao(5)、üan+ie(3)、üan+ing(6)、üan+iong(1)、üan+iou(4)、üan+o(1)、üan+ong(4)、üan+ou(6)、üan+ua(2)、üan+uai(1)、üan+uang(3)、üan+uei(7)、üan+uo(6)、üan+ü(5)、üan+üe(2)、ün+-i_back(4)、ün+-i_front(2)、ün+a(2)、ün+ai(2)、ün+ang(3)、ün+ao(4)、ün+e(2)、ün+ei(4)、ün+eng(4)、ün+i(9)、ün+iang(3)、ün+iao(3)、ün+ing(3)、ün+iong(3)、ün+iou(2)、ün+ong(6)、ün+ou(1)、ün+ua(2)、ün+uang(1)、ün+uei(4)、ün+uo(5)、ün+ü(6)、-i_back+uen(8)、-i_back+üan(7)、-i_front+en(4)、-i_front+ian(9)、-i_front+in(6)、-i_front+uan(2)、-i_front+uen(5)、-i_front+üan(3)、-i_front+ün(1)、a+in(5)、a+uan(8)、a+uen(6)、a+üan(7)、a+ün(2)、ai+en(8)、ai+uen(5)、ai+ün(3)、ang+uen(2)、ang+üan(8)、ang+ün(4)、ao+en(6)、ao+in(8)、ao+uen(8)、ao+üan(4)、ao+ün(3)、e+an(7)、e+in(4)、e+uen(7)、e+üan(4)、e+ün(2)、ei+en(7)、ei+in(7)、ei+uan(5)、ei+uen(2)、ei+üan(1)、ei+ün(3)、eng+uan(6)、eng+uen(8)、eng+üan(8)、eng+ün(5)、er+an(1)、er+in(1)、er+uan(1)、er+uen(1)、er+üan(1)、i+ün(6)、ia+an(5)、ia+en(4)、ia+ian(5)、ia+in(3)、ia+uan(1)、ia+uen(1)、ia+üan(2)、ia+ün(3)、iang+en(3)、iang+uan(2)、iang+uen(3)、iang+üan(2)、iang+ün(1)、iao+en(8)、iao+in(8)、iao+uan(6)、iao+uen(5)、iao+üan(5)、iao+ün(1)、ie+an(8)、ie+en(4)、ie+in(4)、ie+uan(7)、ie+uen(4)、ie+üan(1)、ing+ün(8)、iong+an(4)、iong+en(2)、iong+ian(2)、iong+in(8)、iong+uen(2)、iong+üan(1)、iou+in(5)、iou+uan(7)、iou+uen(5)、iou+üan(4)、o+an(9)、o+ian(3)、o+uan(2)、o+uen(2)、ong+uen(5)、ong+üan(6)、ong+ün(7)、ou+uan(6)、ou+uen(4)、ou+üan(4)、ou+ün(2)、u+ün(5)、ua+an(7)、ua+en(5)、ua+ian(9)、ua+in(3)、ua+uan(1)、ua+uen(4)、ua+üan(4)、uai+an(4)、uai+en(2)、uai+ian(9)、uai+in(3)、uai+uan(2)、uai+uen(2)、uai+ün(1)、uang+en(2)、uang+in(6)、uang+uan(6)、uang+uen(1)、uang+üan(6)、uang+ün(1)、uei+uan(8)、uei+uen(9)、uei+üan(8)、uei+ün(4)、uo+en(8)、uo+in(4)、uo+uan(9)、uo+uen(3)、uo+üan(5)、uo+ün(2)、ü+an(9)、ü+en(6)、ü+in(6)、ü+uan(7)、ü+uen(4)、ü+üan(2)、üe+an(5)、üe+en(2)、üe+ian(6)、üe+in(4)、üe+uan(4)、üe+uen(2)、üe+üan(6)

### back_nasal_basic · 后鼻音专项一（基础）

模式 `single_focus`；候选 4186 条；核心池 747 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 747 | OK |
| 10 分钟 | 150 | 747 | OK |
| 15 分钟 | 225 | 747 | OK |
| 20 分钟 | 300 | 747 | OK |

**桶 core（核心 T×T，目标 80.0%）**

item 747 条：单字 401 / 双字 345 / 三字+ 1

| pattern | 候选数 |
|---|---:|
| ing | 113 |
| eng | 108 |
| ang | 95 |
| ong | 85 |
| ing+ing | 51 |
| eng+ing | 30 |
| ong+ing | 30 |
| ong+ong | 26 |
| ing+eng | 24 |
| ong+eng | 24 |
| ing+ong | 21 |
| ang+ang | 18 |

**桶 supplement（补充 T↔O，目标 20.0%）**

item 3439 条：单字 0 / 双字 3259 / 三字+ 180

| pattern | 候选数 |
|---|---:|
| ing+i | 77 |
| ong+i | 57 |
| eng+i | 50 |
| u+ong | 49 |
| i+ing | 48 |
| ian+ing | 45 |
| ong+u | 44 |
| i+eng | 43 |
| u+ing | 42 |
| ang+u | 40 |
| en+ing | 39 |
| ing+u | 38 |

缺失（0 候选，14 个）：ang+er、ang+ueng、eng+er、eng+iong、eng+uai、eng+ueng、ing+ueng、ong+ueng、er+ang、er+eng、ueng+ang、ueng+eng、ueng+ing、ueng+ong

稀缺（<10，106 个）：ang+a(8)、ang+ei(4)、ang+ia(5)、ang+iao(8)、ang+iong(1)、ang+iou(5)、ang+o(2)、ang+ou(9)、ang+ua(1)、ang+uai(1)、ang+uang(7)、ang+uen(2)、ang+ü(5)、ang+üan(8)、ang+üe(5)、ang+ün(4)、eng+-i_front(9)、eng+ei(4)、eng+ia(8)、eng+ie(6)、eng+o(5)、eng+ua(2)、eng+uan(6)、eng+uen(8)、eng+üan(8)、eng+üe(8)、eng+ün(5)、ing+a(9)、ing+ei(7)、ing+er(4)、ing+iong(6)、ing+o(3)、ing+ua(7)、ing+uai(5)、ing+uo(6)、ing+üe(6)、ing+ün(8)、ong+ei(7)、ong+er(2)、ong+ia(5)、ong+iong(7)、ong+o(3)、ong+uai(4)、ong+uang(6)、ong+uen(5)、ong+üan(6)、ong+üe(9)、ong+ün(7)、-i_front+ang(4)、-i_front+eng(3)、-i_front+ing(8)、-i_front+ong(7)、a+eng(6)、e+ong(6)、ei+eng(4)、en+ang(6)、er+ing(1)、er+ong(2)、ia+ang(4)、ia+eng(3)、ia+ing(6)、ia+ong(7)、iang+ang(8)、iang+ong(6)、ie+ang(4)、ie+eng(7)、ie+ong(4)、in+ong(7)、iong+ang(2)、iong+eng(4)、iong+ing(1)、iong+ong(3)、iou+ong(4)、o+ang(4)、o+eng(4)、o+ing(2)、o+ong(4)、ou+eng(8)、ua+ang(2)、ua+eng(1)、ua+ing(3)、ua+ong(5)、uai+ang(4)、uai+eng(1)、uai+ing(2)、uai+ong(1)、uang+eng(3)、uang+ing(8)、uen+ang(9)、uen+eng(8)、uen+ong(7)、uo+eng(6)、ü+ang(9)、ü+eng(5)、ü+ing(9)、üan+ang(4)、üan+eng(7)、üan+ing(6)、üan+ong(4)、üe+ang(3)、üe+eng(6)、üe+ong(3)、ün+ang(3)、ün+eng(4)、ün+ing(3)、ün+ong(6)

### back_nasal_extended · 后鼻音专项二（扩展）

模式 `single_focus`；候选 1175 条；核心池 151 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 151 | OK |
| 10 分钟 | 150 | 151 | OK |
| 15 分钟 | 225 | 151 | need_repeat |
| 20 分钟 | 300 | 151 | need_repeat |

**桶 core（核心 T×T，目标 80.0%）**

item 151 条：单字 123 / 双字 28 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| iang | 67 |
| uang | 38 |
| iong | 16 |
| iang+uang | 7 |
| iang+iang | 6 |
| uang+iang | 5 |
| uang+uang | 5 |
| iong+iong | 2 |
| ueng | 2 |
| iang+iong | 1 |
| iong+iang | 1 |
| iong+uang | 1 |

缺失（0 候选，8 个）：iang+ueng、uang+ueng、uang+iong、ueng+iang、ueng+uang、ueng+ueng、ueng+iong、iong+ueng

稀缺（<10，8 个）：iang+iang(6)、iang+uang(7)、iang+iong(1)、uang+iang(5)、uang+uang(5)、iong+iang(1)、iong+uang(1)、iong+iong(2)

**桶 supplement（补充 T↔O，目标 20.0%）**

item 1024 条：单字 0 / 双字 988 / 三字+ 36

| pattern | 候选数 |
|---|---:|
| i+iang | 26 |
| iang+i | 26 |
| u+iang | 25 |
| ing+iang | 20 |
| ing+uang | 19 |
| iang+ian | 18 |
| uang+u | 18 |
| an+iang | 16 |
| ao+iang | 16 |
| iang+ing | 15 |
| ong+iang | 15 |
| ian+iang | 14 |

缺失（0 候选，90 个）：iang+er、iang+o、uang+er、ueng+-i_back、ueng+-i_front、ueng+a、ueng+ai、ueng+an、ueng+ang、ueng+ao、ueng+e、ueng+ei、ueng+en、ueng+eng、ueng+er、ueng+i、ueng+ia、ueng+ian、ueng+iao、ueng+ie、ueng+in、ueng+ing、ueng+iou、ueng+o、ueng+ong、ueng+ou、ueng+u、ueng+ua、ueng+uai、ueng+uan、ueng+uei、ueng+uen、ueng+uo、ueng+ü、ueng+üan、ueng+üe、ueng+ün、iong+ei、iong+er、iong+ia、iong+iao、iong+ua、iong+uan、iong+uo、iong+ün、-i_back+ueng、-i_front+ueng、a+ueng、a+iong、ai+ueng、an+ueng、ang+ueng、ao+ueng、e+ueng、ei+ueng、eng+ueng、eng+iong、er+iang、er+ueng、er+iong、i+ueng、ia+ueng、ian+ueng、iao+ueng、ie+ueng、in+ueng、ing+ueng、iou+ueng、o+ueng、o+iong、ong+ueng、ou+ueng、ua+ueng、ua+iong、uai+iang、uai+ueng、uai+iong、uan+ueng、uei+ueng、uei+iong、uen+iang、uen+ueng、uen+iong、uo+ueng、ü+ueng、ü+iong、üan+ueng、üe+ueng、üe+iong、ün+ueng

稀缺（<10，150 个）：iang+-i_back(9)、iang+-i_front(6)、iang+a(3)、iang+ai(6)、iang+ang(8)、iang+ao(6)、iang+e(6)、iang+ei(1)、iang+en(3)、iang+ia(6)、iang+iao(9)、iang+ie(5)、iang+ong(6)、iang+ou(5)、iang+ua(4)、iang+uai(1)、iang+uan(2)、iang+uei(4)、iang+uen(3)、iang+uo(6)、iang+ü(3)、iang+üan(2)、iang+üe(3)、iang+ün(1)、uang+-i_front(5)、uang+a(3)、uang+ai(6)、uang+ao(7)、uang+e(4)、uang+ei(3)、uang+en(2)、uang+eng(3)、uang+ia(3)、uang+iao(1)、uang+ie(8)、uang+in(6)、uang+ing(8)、uang+iou(3)、uang+o(6)、uang+ou(4)、uang+ua(4)、uang+uai(2)、uang+uan(6)、uang+uei(4)、uang+uen(1)、uang+uo(7)、uang+ü(5)、uang+üan(6)、uang+üe(2)、uang+ün(1)、iong+-i_back(1)、iong+-i_front(1)、iong+a(1)、iong+ai(1)、iong+an(4)、iong+ang(2)、iong+ao(3)、iong+e(1)、iong+en(2)、iong+eng(4)、iong+i(6)、iong+ian(2)、iong+ie(1)、iong+in(8)、iong+ing(1)、iong+iou(3)、iong+o(1)、iong+ong(3)、iong+ou(3)、iong+u(8)、iong+uai(1)、iong+uei(2)、iong+uen(2)、iong+ü(2)、iong+üan(1)、iong+üe(1)、-i_back+uang(8)、-i_back+iong(6)、-i_front+iang(7)、-i_front+uang(1)、-i_front+iong(1)、a+uang(3)、ai+iang(7)、ai+uang(8)、ai+iong(2)、an+uang(9)、an+iong(3)、ang+uang(7)、ang+iong(1)、ao+uang(4)、ao+iong(1)、e+iang(7)、e+uang(7)、e+iong(2)、ei+iang(5)、ei+uang(1)、ei+iong(2)、en+iang(7)、en+uang(5)、en+ueng(1)、en+iong(2)、er+uang(1)、i+iong(2)、ia+iang(8)、ia+uang(3)、ia+iong(1)、ian+uang(7)、ian+iong(1)、iao+uang(7)、iao+iong(1)、ie+iang(3)、ie+uang(1)、ie+iong(1)、in+iang(7)、in+uang(4)、in+iong(5)、ing+iong(6)、iou+iang(7)、iou+uang(3)、iou+iong(2)、o+iang(1)、o+uang(1)、ong+uang(6)、ong+iong(7)、ou+uang(1)、ou+iong(1)、u+ueng(1)、u+iong(8)、ua+iang(2)、ua+uang(3)、uai+uang(1)、uan+iang(8)、uan+uang(4)、uan+iong(3)、uei+iang(9)、uei+uang(6)、uen+uang(4)、uo+iang(3)、uo+uang(6)、uo+iong(2)、ü+iang(6)、ü+uang(5)、üan+iang(7)、üan+uang(3)、üan+iong(1)、üe+iang(4)、üe+uang(2)、ün+iang(3)、ün+uang(1)、ün+iong(3)

### back_nasal_all · 后鼻音综合

模式 `single_focus`；候选 5154 条；核心池 1095 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 1095 | OK |
| 10 分钟 | 150 | 1095 | OK |
| 15 分钟 | 225 | 1095 | OK |
| 20 分钟 | 300 | 1095 | OK |

**桶 core（核心 T×T，目标 80.0%）**

item 1095 条：单字 524 / 双字 569 / 三字+ 2

| pattern | 候选数 |
|---|---:|
| ing | 113 |
| eng | 108 |
| ang | 95 |
| ong | 85 |
| iang | 67 |
| ing+ing | 51 |
| uang | 38 |
| eng+ing | 30 |
| ong+ing | 30 |
| ong+ong | 26 |
| ing+eng | 24 |
| ong+eng | 24 |

缺失（0 候选，17 个）：ang+ueng、eng+iong、eng+ueng、iang+ueng、ing+ueng、iong+ueng、ong+ueng、uang+iong、uang+ueng、ueng+ang、ueng+eng、ueng+iang、ueng+ing、ueng+iong、ueng+ong、ueng+uang、ueng+ueng

稀缺（<10，21 个）：ang+iong(1)、ang+uang(7)、iang+ang(8)、iang+iang(6)、iang+iong(1)、iang+ong(6)、iang+uang(7)、ing+iong(6)、iong+ang(2)、iong+eng(4)、iong+iang(1)、iong+ing(1)、iong+iong(2)、iong+ong(3)、iong+uang(1)、ong+iong(7)、ong+uang(6)、uang+eng(3)、uang+iang(5)、uang+ing(8)、uang+uang(5)

**桶 supplement（补充 T↔O，目标 20.0%）**

item 4059 条：单字 0 / 双字 3855 / 三字+ 204

| pattern | 候选数 |
|---|---:|
| ing+i | 77 |
| ong+i | 57 |
| eng+i | 50 |
| u+ong | 49 |
| i+ing | 48 |
| ian+ing | 45 |
| ong+u | 44 |
| i+eng | 43 |
| u+ing | 42 |
| ang+u | 40 |
| en+ing | 39 |
| ing+u | 38 |

缺失（0 候选，86 个）：ang+er、eng+er、eng+uai、iang+er、iang+o、iong+ei、iong+er、iong+ia、iong+iao、iong+ua、iong+uan、iong+uo、iong+ün、uang+er、ueng+-i_back、ueng+-i_front、ueng+a、ueng+ai、ueng+an、ueng+ao、ueng+e、ueng+ei、ueng+en、ueng+er、ueng+i、ueng+ia、ueng+ian、ueng+iao、ueng+ie、ueng+in、ueng+iou、ueng+o、ueng+ou、ueng+u、ueng+ua、ueng+uai、ueng+uan、ueng+uei、ueng+uen、ueng+uo、ueng+ü、ueng+üan、ueng+üe、ueng+ün、-i_back+ueng、-i_front+ueng、a+iong、a+ueng、ai+ueng、an+ueng、ao+ueng、e+ueng、ei+ueng、er+ang、er+eng、er+iang、er+iong、er+ueng、i+ueng、ia+ueng、ian+ueng、iao+ueng、ie+ueng、in+ueng、iou+ueng、o+iong、o+ueng、ou+ueng、ua+iong、ua+ueng、uai+iang、uai+iong、uai+ueng、uan+ueng、uei+iong、uei+ueng、uen+iang、uen+iong、uen+ueng、uo+ueng、ü+iong、ü+ueng、üan+ueng、üe+iong、üe+ueng、ün+ueng

稀缺（<10，230 个）：ang+a(8)、ang+ei(4)、ang+ia(5)、ang+iao(8)、ang+iou(5)、ang+o(2)、ang+ou(9)、ang+ua(1)、ang+uai(1)、ang+uen(2)、ang+ü(5)、ang+üan(8)、ang+üe(5)、ang+ün(4)、eng+-i_front(9)、eng+ei(4)、eng+ia(8)、eng+ie(6)、eng+o(5)、eng+ua(2)、eng+uan(6)、eng+uen(8)、eng+üan(8)、eng+üe(8)、eng+ün(5)、iang+-i_back(9)、iang+-i_front(6)、iang+a(3)、iang+ai(6)、iang+ao(6)、iang+e(6)、iang+ei(1)、iang+en(3)、iang+ia(6)、iang+iao(9)、iang+ie(5)、iang+ou(5)、iang+ua(4)、iang+uai(1)、iang+uan(2)、iang+uei(4)、iang+uen(3)、iang+uo(6)、iang+ü(3)、iang+üan(2)、iang+üe(3)、iang+ün(1)、ing+a(9)、ing+ei(7)、ing+er(4)、ing+o(3)、ing+ua(7)、ing+uai(5)、ing+uo(6)、ing+üe(6)、ing+ün(8)、iong+-i_back(1)、iong+-i_front(1)、iong+a(1)、iong+ai(1)、iong+an(4)、iong+ao(3)、iong+e(1)、iong+en(2)、iong+i(6)、iong+ian(2)、iong+ie(1)、iong+in(8)、iong+iou(3)、iong+o(1)、iong+ou(3)、iong+u(8)、iong+uai(1)、iong+uei(2)、iong+uen(2)、iong+ü(2)、iong+üan(1)、iong+üe(1)、ong+ei(7)、ong+er(2)、ong+ia(5)、ong+o(3)、ong+uai(4)、ong+uen(5)、ong+üan(6)、ong+üe(9)、ong+ün(7)、uang+-i_front(5)、uang+a(3)、uang+ai(6)、uang+ao(7)、uang+e(4)、uang+ei(3)、uang+en(2)、uang+ia(3)、uang+iao(1)、uang+ie(8)、uang+in(6)、uang+iou(3)、uang+o(6)、uang+ou(4)、uang+ua(4)、uang+uai(2)、uang+uan(6)、uang+uei(4)、uang+uen(1)、uang+uo(7)、uang+ü(5)、uang+üan(6)、uang+üe(2)、uang+ün(1)、-i_back+iong(6)、-i_back+uang(8)、-i_front+ang(4)、-i_front+eng(3)、-i_front+iang(7)、-i_front+ing(8)、-i_front+iong(1)、-i_front+ong(7)、-i_front+uang(1)、a+eng(6)、a+uang(3)、ai+iang(7)、ai+iong(2)、ai+uang(8)、an+iong(3)、an+uang(9)、ao+iong(1)、ao+uang(4)、e+iang(7)、e+iong(2)、e+ong(6)、e+uang(7)、ei+eng(4)、ei+iang(5)、ei+iong(2)、ei+uang(1)、en+ang(6)、en+iang(7)、en+iong(2)、en+uang(5)、en+ueng(1)、er+ing(1)、er+ong(2)、er+uang(1)、i+iong(2)、ia+ang(4)、ia+eng(3)、ia+iang(8)、ia+ing(6)、ia+iong(1)、ia+ong(7)、ia+uang(3)、ian+iong(1)、ian+uang(7)、iao+iong(1)、iao+uang(7)、ie+ang(4)、ie+eng(7)、ie+iang(3)、ie+iong(1)、ie+ong(4)、ie+uang(1)、in+iang(7)、in+iong(5)、in+ong(7)、in+uang(4)、iou+iang(7)、iou+iong(2)、iou+ong(4)、iou+uang(3)、o+ang(4)、o+eng(4)、o+iang(1)、o+ing(2)、o+ong(4)、o+uang(1)、ou+eng(8)、ou+iong(1)、ou+uang(1)、u+iong(8)、u+ueng(1)、ua+ang(2)、ua+eng(1)、ua+iang(2)、ua+ing(3)、ua+ong(5)、ua+uang(3)、uai+ang(4)、uai+eng(1)、uai+ing(2)、uai+ong(1)、uai+uang(1)、uan+iang(8)、uan+iong(3)、uan+uang(4)、uei+iang(9)、uei+uang(6)、uen+ang(9)、uen+eng(8)、uen+ong(7)、uen+uang(4)、uo+eng(6)、uo+iang(3)、uo+iong(2)、uo+uang(6)、ü+ang(9)、ü+eng(5)、ü+iang(6)、ü+ing(9)、ü+uang(5)、üan+ang(4)、üan+eng(7)、üan+iang(7)、üan+ing(6)、üan+iong(1)、üan+ong(4)、üan+uang(3)、üe+ang(3)、üe+eng(6)、üe+iang(4)、üe+ong(3)、üe+uang(2)、ün+ang(3)、ün+eng(4)、ün+iang(3)、ün+ing(3)、ün+iong(3)、ün+ong(6)、ün+uang(1)

### front_back_nasal_contrast_1 · 前后鼻音对比一

模式 `contrast`；候选 3804 条；核心池 705 条；allow_other=False

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 93 | 705 | OK |
| 10 分钟 | 187 | 705 | OK |
| 15 分钟 | 281 | 705 | OK |
| 20 分钟 | 375 | 705 | OK |

**桶 cross（跨组 en↔eng / in↔ing，目标 65.0%）**

item 156 条：单字 0 / 双字 155 / 三字+ 1

| pattern | 候选数 |
|---|---:|
| en+ing | 36 |
| in+ing | 24 |
| ing+en | 23 |
| eng+en | 19 |
| in+eng | 18 |
| en+eng | 14 |
| ing+in | 13 |
| eng+in | 9 |
| ing+ing | 1 |

稀缺（<10，1 个）：eng+in(9)

**桶 same（同组 P+P / Q+Q，目标 35.0%）**

item 549 条：单字 371 / 双字 178 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| ing | 113 |
| eng | 108 |
| en | 77 |
| in | 73 |
| ing+ing | 51 |
| eng+ing | 30 |
| ing+eng | 24 |
| in+in | 18 |
| en+en | 17 |
| en+in | 14 |
| eng+eng | 14 |
| in+en | 10 |

### front_back_nasal_contrast_2 · 前后鼻音对比二

模式 `contrast`；候选 5121 条；核心池 1107 条；allow_other=False

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 93 | 1107 | OK |
| 10 分钟 | 187 | 1107 | OK |
| 15 分钟 | 281 | 1107 | OK |
| 20 分钟 | 375 | 1107 | OK |

**桶 cross（跨组 an↔ang 等，目标 65.0%）**

item 229 条：单字 0 / 双字 228 / 三字+ 1

| pattern | 候选数 |
|---|---:|
| ang+ian | 26 |
| ang+an | 25 |
| ian+ang | 20 |
| an+ang | 19 |
| iang+ian | 18 |
| an+iang | 16 |
| ian+iang | 14 |
| uang+ian | 13 |
| ang+uan | 11 |
| iang+an | 11 |
| uan+ang | 11 |
| uang+an | 10 |

稀缺（<10，6 个）：an+uang(9)、ian+uang(7)、uan+iang(7)、uan+uang(4)、iang+uan(2)、uang+uan(6)

**桶 same（同组 P+P / Q+Q，目标 35.0%）**

item 878 条：单字 591 / 双字 287 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| ian | 163 |
| an | 162 |
| ang | 95 |
| iang | 67 |
| uan | 66 |
| ian+ian | 45 |
| an+an | 38 |
| uang | 38 |
| an+ian | 33 |
| ian+uan | 19 |
| ian+an | 18 |
| ang+ang | 17 |

稀缺（<10，7 个）：uan+uan(8)、ang+uang(7)、iang+ang(8)、iang+iang(6)、iang+uang(7)、uang+iang(5)、uang+uang(5)

### tone_1 · 阴平专项

模式 `single_focus`；候选 5935 条；核心池 1390 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 1390 | OK |
| 10 分钟 | 150 | 1390 | OK |
| 15 分钟 | 225 | 1390 | OK |
| 20 分钟 | 300 | 1390 | OK |

**桶 core（核心 1-1 / 单字 1，目标 80.0%）**

item 1390 条：单字 715 / 双字 669 / 三字+ 6

| pattern | 候选数 |
|---|---:|
| 1 | 715 |
| 1+1 | 681 |

**桶 supplement（补充 1-x / x-1，目标 20.0%）**

item 4545 条：单字 0 / 双字 4320 / 三字+ 225

| pattern | 候选数 |
|---|---:|
| 1+4 | 1394 |
| 1+2 | 913 |
| 1+3 | 630 |
| 4+1 | 629 |
| 2+1 | 577 |
| 3+1 | 359 |
| 1+0 | 127 |
| 4+4 | 51 |
| 1+1 | 44 |
| 3+4 | 25 |
| 2+4 | 23 |
| 4+2 | 23 |

缺失（0 候选，1 个）：0+1

### tone_2 · 阳平专项

模式 `single_focus`；候选 6156 条；核心池 1443 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 1443 | OK |
| 10 分钟 | 150 | 1443 | OK |
| 15 分钟 | 225 | 1443 | OK |
| 20 分钟 | 300 | 1443 | OK |

**桶 core（核心 2-2 / 单字 2，目标 80.0%）**

item 1443 条：单字 667 / 双字 772 / 三字+ 4

| pattern | 候选数 |
|---|---:|
| 2+2 | 780 |
| 2 | 667 |

**桶 supplement（补充 2-x / x-2，目标 20.0%）**

item 4713 条：单字 0 / 双字 4472 / 三字+ 241

| pattern | 候选数 |
|---|---:|
| 2+4 | 1318 |
| 1+2 | 913 |
| 4+2 | 890 |
| 2+1 | 577 |
| 3+2 | 517 |
| 2+3 | 489 |
| 2+0 | 118 |
| 4+4 | 48 |
| 2+2 | 33 |
| 3+4 | 26 |
| 1+4 | 25 |
| 4+3 | 21 |

稀缺（<10，1 个）：0+2(1)

### tone_3 · 上声专项

模式 `single_focus`；候选 4648 条；核心池 912 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 912 | OK |
| 10 分钟 | 150 | 912 | OK |
| 15 分钟 | 225 | 912 | OK |
| 20 分钟 | 300 | 912 | OK |

**桶 core（核心 3-3 / 单字 3，目标 80.0%）**

item 912 条：单字 527 / 双字 383 / 三字+ 2

| pattern | 候选数 |
|---|---:|
| 3 | 527 |
| 3+3 | 388 |

**桶 supplement（补充 3-x / x-3，目标 20.0%）**

item 3736 条：单字 0 / 双字 3548 / 三字+ 188

| pattern | 候选数 |
|---|---:|
| 3+4 | 1045 |
| 4+3 | 679 |
| 1+3 | 630 |
| 3+2 | 517 |
| 2+3 | 489 |
| 3+1 | 359 |
| 3+0 | 93 |
| 4+4 | 26 |
| 4+2 | 23 |
| 3+3 | 18 |
| 1+4 | 17 |
| 2+1 | 17 |

缺失（0 候选，1 个）：0+3

### tone_4 · 去声专项

模式 `single_focus`；候选 8761 条；核心池 2778 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 74 | 2778 | OK |
| 10 分钟 | 150 | 2778 | OK |
| 15 分钟 | 225 | 2778 | OK |
| 20 分钟 | 300 | 2778 | OK |

**桶 core（核心 4-4 / 单字 4，目标 80.0%）**

item 2778 条：单字 1022 / 双字 1735 / 三字+ 21

| pattern | 候选数 |
|---|---:|
| 4+4 | 1777 |
| 4 | 1022 |

**桶 supplement（补充 4-x / x-4，目标 20.0%）**

item 5983 条：单字 0 / 双字 5667 / 三字+ 316

| pattern | 候选数 |
|---|---:|
| 1+4 | 1394 |
| 2+4 | 1318 |
| 3+4 | 1045 |
| 4+2 | 890 |
| 4+3 | 679 |
| 4+1 | 629 |
| 4+0 | 136 |
| 4+4 | 107 |
| 1+2 | 31 |
| 1+1 | 30 |
| 2+1 | 29 |
| 2+2 | 24 |

稀缺（<10，1 个）：0+4(2)

### tone_all · 四声综合

模式 `comprehensive`；候选 16149 条；核心池 16149 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 93 | 16149 | OK |
| 10 分钟 | 187 | 16149 | OK |
| 15 分钟 | 281 | 16149 | OK |
| 20 分钟 | 375 | 16149 | OK |

**桶 all（全部，目标 100.0%）**

item 16149 条：单字 2931 / 双字 12796 / 三字+ 422

| pattern | 候选数 |
|---|---:|
| 4+4 | 1884 |
| 1+4 | 1394 |
| 2+4 | 1318 |
| 3+4 | 1045 |
| 4 | 1022 |
| 1+2 | 913 |
| 4+2 | 890 |
| 2+2 | 813 |
| 1+1 | 725 |
| 1 | 715 |
| 4+3 | 679 |
| 2 | 667 |

### tone_33 · 上声变调（3-3 连读）

模式 `special_mix`；候选 403 条；核心池 403 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 93 | 403 | OK |
| 10 分钟 | 187 | 403 | OK |
| 15 分钟 | 281 | 403 | OK |
| 20 分钟 | 375 | 403 | OK |

**桶 adjacent（相邻 3-3，目标 100.0%）**

item 403 条：单字 0 / 双字 383 / 三字+ 20

| pattern | 候选数 |
|---|---:|
| 3+3 | 406 |
| 2+3 | 4 |
| 1+3 | 3 |
| 3+4 | 3 |
| 4+3 | 3 |
| 3+0 | 2 |
| 3+1 | 2 |
| 3+2 | 2 |
| 1+2 | 1 |

### general · 日常综合练习

模式 `comprehensive`；候选 16149 条；核心池 16149 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 93 | 16149 | OK |
| 10 分钟 | 187 | 16149 | OK |
| 15 分钟 | 281 | 16149 | OK |
| 20 分钟 | 375 | 16149 | OK |

**桶 all（综合全库，目标 100.0%）**

item 16149 条：单字 2931 / 双字 12796 / 三字+ 422

| pattern | 候选数 |
|---|---:|
| ZERO | 361 |
| ZERO+ZERO | 254 |
| j | 244 |
| zh | 206 |
| l | 184 |
| x | 183 |
| sh | 168 |
| d | 154 |
| b | 139 |
| h | 137 |
| ch | 133 |
| ZERO+j | 130 |

### neutral_focus · 轻声专项

模式 `special_mix`；候选 476 条；核心池 476 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 93 | 476 | OK |
| 10 分钟 | 187 | 476 | OK |
| 15 分钟 | 281 | 476 | OK |
| 20 分钟 | 375 | 476 | OK |

**桶 all（轻声词，目标 100.0%）**

item 476 条：单字 0 / 双字 467 / 三字+ 9

| pattern | 候选数 |
|---|---:|
| 4+0 | 136 |
| 1+0 | 127 |
| 2+0 | 118 |
| 3+0 | 93 |
| 0+4 | 2 |
| 3+3 | 2 |
| 0+2 | 1 |
| 1+4 | 1 |
| 2+1 | 1 |
| 2+2 | 1 |
| 3+2 | 1 |
| 4+2 | 1 |

### erhua_focus · 儿化专项

模式 `special_mix`；候选 39 条；核心池 39 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 93 | 39 | insufficient |
| 10 分钟 | 187 | 39 | insufficient |
| 15 分钟 | 281 | 39 | insufficient |
| 20 分钟 | 375 | 39 | insufficient |

**桶 all（儿化词，目标 100.0%）**

item 39 条：单字 7 / 双字 32 / 三字+ 0

| pattern | 候选数 |
|---|---:|
| a+en | 3 |
| a | 2 |
| -i_back+-i_front | 1 |
| a+ian | 1 |
| a+uan | 1 |
| a+uen | 1 |
| a+uo | 1 |
| an+uan | 1 |
| an+üe | 1 |
| ang+en | 1 |
| ao+an | 1 |
| ao+ou | 1 |

### yi_bu_focus · 一/不变调

模式 `special_mix`；候选 159 条；核心池 159 条；allow_other=True

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 93 | 159 | OK |
| 10 分钟 | 187 | 159 | need_repeat |
| 15 分钟 | 281 | 159 | need_repeat |
| 20 分钟 | 375 | 159 | insufficient |

**桶 all（一/不词语，目标 100.0%）**

item 159 条：单字 2 / 双字 110 / 三字+ 47

| pattern | 候选数 |
|---|---:|
| b+x | 16 |
| b+ZERO | 12 |
| b+d | 11 |
| b+j | 10 |
| b+g | 9 |
| ZERO+d | 7 |
| b+f | 7 |
| ZERO+ZERO | 6 |
| b+l | 6 |
| b+k | 5 |
| b+q | 5 |
| b+r | 5 |

### front_back_nasal_contrast · 前后鼻音对比（综合）

模式 `contrast`；候选 9700 条；核心池 3519 条；allow_other=False

**时长充足性**

| 时长 | 需核心 | 核心池 | 状态 |
|---|---:|---:|---|
| 5 分钟 | 93 | 3519 | OK |
| 10 分钟 | 187 | 3519 | OK |
| 15 分钟 | 281 | 3519 | OK |
| 20 分钟 | 375 | 3519 | OK |

**桶 cross（跨组 前鼻↔后鼻，目标 65.0%）**

item 1145 条：单字 0 / 双字 1136 / 三字+ 9

| pattern | 候选数 |
|---|---:|
| ian+ing | 42 |
| en+ing | 36 |
| ing+ian | 34 |
| ong+ian | 32 |
| an+ing | 30 |
| ing+an | 30 |
| ian+ong | 27 |
| ang+ian | 26 |
| ang+an | 25 |
| ian+eng | 25 |
| in+ing | 24 |
| ing+en | 23 |

缺失（0 候选，20 个）：an+ueng、en+ueng、in+ueng、ian+ueng、uan+ueng、uen+iang、uen+ueng、uen+iong、üan+ueng、ün+ueng、ueng+an、ueng+en、ueng+in、ueng+ian、ueng+uan、ueng+uen、ueng+üan、ueng+ün、iong+uan、iong+ün

稀缺（<10，62 个）：an+uang(9)、an+iong(3)、en+ang(6)、en+iang(7)、en+uang(5)、en+iong(2)、in+ong(7)、in+iang(7)、in+uang(3)、in+iong(5)、ian+uang(7)、ian+iong(1)、uan+iang(7)、uan+uang(4)、uan+iong(3)、uen+ang(9)、uen+eng(8)、uen+ong(7)、uen+uang(4)、üan+ang(4)、üan+eng(7)、üan+ing(6)、üan+ong(4)、üan+iang(6)、üan+uang(3)、üan+iong(1)、ün+ang(3)、ün+eng(4)、ün+ing(3)、ün+ong(6)、ün+iang(3)、ün+uang(1)、ün+iong(2)、ang+uen(2)、ang+üan(8)、ang+ün(3)、eng+in(9)、eng+uan(6)、eng+uen(7)、eng+üan(7)、eng+ün(5)、ing+ün(8)、ong+uen(5)、ong+üan(5)、ong+ün(7)、iang+en(3)、iang+uan(2)、iang+uen(2)、iang+üan(1)、iang+ün(1)、uang+en(1)、uang+in(5)、uang+uan(6)、uang+uen(1)、uang+üan(6)、uang+ün(1)、iong+an(3)、iong+en(2)、iong+in(7)、iong+ian(2)、iong+uen(2)、iong+üan(1)

**桶 same（同组 前鼻+前鼻 / 后鼻+后鼻，目标 35.0%）**

item 2374 条：单字 1188 / 双字 1184 / 三字+ 2

| pattern | 候选数 |
|---|---:|
| ian | 163 |
| an | 162 |
| ing | 113 |
| eng | 108 |
| ang | 95 |
| ong | 85 |
| en | 77 |
| in | 73 |
| iang | 67 |
| uan | 66 |
| uen | 52 |
| ing+ing | 51 |

缺失（0 候选，18 个）：üan+ün、ang+ueng、eng+ueng、eng+iong、ing+ueng、ong+ueng、iang+ueng、uang+ueng、uang+iong、ueng+ang、ueng+eng、ueng+ing、ueng+ong、ueng+iang、ueng+uang、ueng+ueng、ueng+iong、iong+ueng

稀缺（<10，61 个）：an+üan(7)、an+ün(6)、en+uan(4)、en+uen(5)、en+üan(8)、en+ün(6)、in+uan(5)、in+uen(7)、in+üan(6)、in+ün(5)、ian+uen(7)、ian+üan(9)、ian+ün(3)、uan+en(7)、uan+in(5)、uan+uan(8)、uan+uen(3)、uan+üan(7)、uan+ün(2)、uen+an(9)、uen+en(6)、uen+in(5)、uen+uan(8)、uen+uen(4)、uen+üan(3)、uen+ün(1)、üan+an(6)、üan+en(4)、üan+in(7)、üan+uan(2)、üan+uen(3)、üan+üan(4)、ün+an(3)、ün+en(3)、ün+in(1)、ün+ian(2)、ün+uan(4)、ün+uen(1)、ün+üan(1)、ün+ün(2)、ang+uang(7)、ang+iong(1)、ing+iong(6)、ong+uang(6)、ong+iong(7)、iang+ang(8)、iang+ong(6)、iang+iang(6)、iang+uang(7)、iang+iong(1)、uang+eng(3)、uang+ing(8)、uang+iang(5)、uang+uang(5)、iong+ang(2)、iong+eng(4)、iong+ing(1)、iong+ong(3)、iong+iang(1)、iong+uang(1)、iong+iong(2)
