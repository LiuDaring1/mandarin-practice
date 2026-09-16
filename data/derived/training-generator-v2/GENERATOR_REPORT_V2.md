# 平衡随机训练生成器 v2 首轮报告 GENERATOR_REPORT_V2

- 生成器版本：`v2.0`
- Profile 配置：`training_profiles_v2.json`
- 数据基线：`formal_corpus_2026-08-08_16156`
- 生成时间：2026-08-10T12:30:12.157524+00:00

## 一、QA 汇总

| 指标 | 结果 |
|---|---|
| Session 数 | 65 |
| Profile 候选错误 | 0 |
| bucket 分类错误 | 0 |
| 同 Session 重复 item | 0 |
| 相同 seed 不可复现 | 0 |
| 生成失败 | 0 |
| 最大时长相对误差 | 0.9% |

## 二、各 Profile 试跑统计

| Profile | Session数 | 题数范围 | 时长误差 | 核心占比 | 重复 item | 放宽次数 |
|---|---:|---:|---:|---:|---:|---:|
| `back_nasal_basic` | 3 | 193–195 | +0.06% ~ +0.38% | 79.9% | 0 | 0 |
| `bilabial_focus` | 3 | 202–202 | +0.12% ~ +0.44% | 79.7% | 0 | 5 |
| `compound_front` | 3 | 201–201 | +0.25% ~ +0.46% | 80.1% | 0 | 4 |
| `flat_focus` | 8 | 101–402 | +0.03% ~ +0.50% | 79.9% | 114 | 277 |
| `flat_retroflex_contrast` | 8 | 97–389 | +0.04% ~ +0.90% | 60.0% | 0 | 752 |
| `front_back_nasal_contrast_1` | 8 | 95–381 | +0.08% ~ +0.91% | 65.0% | 183 | 915 |
| `front_back_nasal_contrast_2` | 3 | 188–188 | +0.04% ~ +0.47% | 64.9% | 0 | 358 |
| `front_nasal_basic` | 3 | 199–200 | +0.10% ~ +0.14% | 79.9% | 0 | 13 |
| `jqx_special` | 3 | 193–196 | +0.09% ~ +0.50% | 69.8% | 0 | 30 |
| `n_l_contrast` | 3 | 201–202 | +0.08% ~ +0.11% | 80.0% | 0 | 443 |
| `retroflex_focus` | 3 | 194–195 | +0.12% ~ +0.26% | 80.0% | 0 | 12 |
| `simple_final_focus` | 8 | 96–389 | +0.01% ~ +0.64% | 79.9% | 0 | 42 |
| `tone_1` | 3 | 196–197 | +0.27% ~ +0.33% | 79.8% | 0 | 4 |
| `tone_3` | 3 | 183–184 | +0.36% ~ +0.54% | 79.9% | 0 | 4 |
| `tone_all` | 3 | 186–188 | +0.11% ~ +0.45% | 100.0% | 0 | 361 |

## 三、首批 Session 前 15 条（每个 Profile 取 seed 20260804 的 10 分钟）

### back_nasal_basic（194 题，误差 +0.20%）

| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |
|---|---|---|---|---|---|---|---|
| 1 | 陵 | línɡ | core | ing | ing | 1 | 2 |
| 2 | 中性 | zhōngxìng | core | ong+ing | ing、ong | 2 | 1-4 |
| 3 | 疯 | fēnɡ | core | eng | eng | 1 | 1 |
| 4 | 性病 | xìnɡbìnɡ | core | ing+ing | ing | 2 | 4-4 |
| 5 | 冻 | dòng | core | ong | ong | 1 | 4 |
| 6 | 炎症 | yánzhèng | supplement | ian+eng | eng | 2 | 2-4 |
| 7 | 赏 | shǎng | core | ang | ang | 1 | 3 |
| 8 | 金刚 | jīnɡānɡ | core | ing+ang | ang、ing | 2 | 1-1 |
| 9 | 公公 | gōnggong | core | ong+ong | ong | 2 | 1-0 |
| 10 | 绷 | bēnɡ | core | eng | eng | 1 | 1 |
| 11 | 绫 | línɡ | core | ing | ing | 1 | 2 |
| 12 | 梦境 | mènɡjìnɡ | core | eng+ing | eng、ing | 2 | 4-4 |
| 13 | 趟 | tàng | core | ang | ang | 1 | 4 |
| 14 | 厨房 | chúfáng | supplement | u+ang | ang | 2 | 2-2 |
| 15 | 平整 | pínɡzhěnɡ | core | ing+eng | eng、ing | 2 | 2-3 |

### bilabial_focus（202 题，误差 +0.12%）

| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |
|---|---|---|---|---|---|---|---|
| 1 | 变 | biàn | core | b | b | 1 | 4 |
| 2 | 配备 | pèibèi | core | p+b | b、p | 2 | 4-4 |
| 3 | 生命 | shēngmìng | supplement | sh+m | m | 2 | 1-4 |
| 4 | 锚 | máo | core | m | m | 1 | 2 |
| 5 | 筹办 | chóubàn | supplement | ch+b | b | 2 | 2-4 |
| 6 | 美育 | měiyù | supplement | m+ZERO | m | 2 | 3-4 |
| 7 | 剖 | pōu | core | p | p | 1 | 1 |
| 8 | 便 | biàn | core | b | b | 1 | 4 |
| 9 | 出苗 | chūmiáo | supplement | ch+m | m | 2 | 1-2 |
| 10 | 买卖 | mǎimai | core | m+m | m | 2 | 3-0 |
| 11 | 品 | pǐn | core | p | p | 1 | 3 |
| 12 | 免 | miǎn | core | m | m | 1 | 3 |
| 13 | 劳模 | láomó | supplement | l+m | m | 2 | 2-2 |
| 14 | 备 | bèi | core | b | b | 1 | 4 |
| 15 | 避免 | bìmiǎn | core | b+m | b、m | 2 | 4-3 |

### compound_front（201 题，误差 +0.25%）

| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |
|---|---|---|---|---|---|---|---|
| 1 | 帽 | mào | core | ao | ao | 1 | 4 |
| 2 | 正道 | zhèngdào | supplement | eng+ao | ao | 2 | 4-4 |
| 3 | 偶 | ǒu | core | ou | ou | 1 | 3 |
| 4 | 茅草 | máocǎo | core | ao+ao | ao | 2 | 2-3 |
| 5 | 拍 | pāi | core | ai | ai | 1 | 1 |
| 6 | 梅 | méi | core | ei | ei | 1 | 2 |
| 7 | 海盗 | hǎidào | core | ai+ao | ai、ao | 2 | 3-4 |
| 8 | 道 | dào | core | ao | ao | 1 | 4 |
| 9 | 太后 | tàihòu | core | ai+ou | ai、ou | 2 | 4-4 |
| 10 | 色 | shǎi | core | ai | ai | 1 | 3 |
| 11 | 钞 | chāo | core | ao | ao | 1 | 1 |
| 12 | 垢 | ɡòu | core | ou | ou | 1 | 4 |
| 13 | 配偶 | pèi’ǒu | core | ei+ou | ei、ou | 2 | 4-3 |
| 14 | 裴 | péi | core | ei | ei | 1 | 2 |
| 15 | 奥 | ào | core | ao | ao | 1 | 4 |

### flat_focus（202 题，误差 +0.36%）

| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |
|---|---|---|---|---|---|---|---|
| 1 | 寺 | sì | core | s | s | 1 | 4 |
| 2 | 随从 | suícónɡ | core | s+c | c、s | 2 | 2-2 |
| 3 | 灾 | zāi | core | z | z | 1 | 1 |
| 4 | 凑 | còu | core | c | c | 1 | 4 |
| 5 | 识字 | shízì | supplement | sh+z | z | 2 | 2-4 |
| 6 | 岁 | suì | core | s | s | 1 | 4 |
| 7 | 崽 | zǎi | core | z | z | 1 | 3 |
| 8 | 猜测 | cāicè | core | c+c | c | 2 | 1-4 |
| 9 | 脆 | cuì | core | c | c | 1 | 4 |
| 10 | 搔 | sāo | core | s | s | 1 | 1 |
| 11 | 丧葬 | sāngzànɡ | core | s+z | s、z | 2 | 1-4 |
| 12 | 慈 | cí | core | c | c | 1 | 2 |
| 13 | 籽 | zǐ | core | z | z | 1 | 3 |
| 14 | 骚 | sāo | core | s | s | 1 | 1 |
| 15 | 著作 | zhùzuò | supplement | zh+z | z | 2 | 4-4 |

### flat_retroflex_contrast（194 题，误差 +0.48%）

| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |
|---|---|---|---|---|---|---|---|
| 1 | 村镇 | cūnzhèn | cross | c+zh | c、zh | 2 | 1-4 |
| 2 | 之 | zhī | same | zh | zh | 1 | 1 |
| 3 | 赛事 | sàishì | cross | s+sh | s、sh | 2 | 4-4 |
| 4 | 傻子 | shǎzi | cross | sh+z | sh、z | 2 | 3-0 |
| 5 | 种族 | zhǒngzú | cross | zh+z | z、zh | 2 | 3-2 |
| 6 | 慈善 | císhàn | cross | c+sh | c、sh | 2 | 2-4 |
| 7 | 增殖 | zēngzhí | cross | z+zh | z、zh | 2 | 1-2 |
| 8 | 胜 | shèng | same | sh | sh | 1 | 4 |
| 9 | 出资 | chūzī | cross | ch+z | ch、z | 2 | 1-1 |
| 10 | 纵使 | zòngshǐ | cross | z+sh | sh、z | 2 | 4-3 |
| 11 | 手册 | shǒucè | cross | sh+c | c、sh | 2 | 3-4 |
| 12 | 自称 | zìchēng | cross | z+ch | ch、z | 2 | 4-1 |
| 13 | 输送 | shūsòng | cross | sh+s | s、sh | 2 | 1-4 |
| 14 | 疮 | chuānɡ | same | ch | ch | 1 | 1 |
| 15 | 塞 | sè | same | s | s | 1 | 4 |

### front_back_nasal_contrast_1（191 题，误差 +0.40%）

| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |
|---|---|---|---|---|---|---|---|
| 1 | 本领 | běnlǐng | cross | en+ing | en、ing | 2 | 3-3 |
| 2 | 能人 | nénɡrén | cross | eng+en | en、eng | 2 | 2-2 |
| 3 | 丁 | dīng | same | ing | ing | 1 | 1 |
| 4 | 讽 | fěnɡ | same | eng | eng | 1 | 3 |
| 5 | 听任 | tīnɡrèn | cross | ing+en | en、ing | 2 | 1-4 |
| 6 | 新型 | xīnxíng | cross | in+ing | in、ing | 2 | 1-2 |
| 7 | 禁 | jìn | same | in | in | 1 | 4 |
| 8 | 诊 | zhěn | same | en | en | 1 | 3 |
| 9 | 音程 | yīnchénɡ | cross | in+eng | eng、in | 2 | 1-2 |
| 10 | 任命 | rènmìng | cross | en+ing | en、ing | 2 | 4-4 |
| 11 | 核能 | hénénɡ | cross | en+eng | en、eng | 2 | 2-2 |
| 12 | 蝇 | yínɡ | same | ing | ing | 1 | 2 |
| 13 | 民警 | mínjǐnɡ | cross | in+ing | in、ing | 2 | 2-3 |
| 14 | 引证 | yǐnzhènɡ | cross | in+eng | eng、in | 2 | 3-4 |
| 15 | 盆 | pén | same | en | en | 1 | 2 |

### front_back_nasal_contrast_2（188 题，误差 +0.40%）

| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |
|---|---|---|---|---|---|---|---|
| 1 | 昂然 | ánɡrán | cross | ang+an | an、ang | 2 | 2-2 |
| 2 | 反常 | fǎnchánɡ | cross | an+ang | an、ang | 2 | 3-2 |
| 3 | 砚 | yàn | same | ian | ian | 1 | 4 |
| 4 | 篮 | lán | same | an | an | 1 | 2 |
| 5 | 天堂 | tiāntánɡ | cross | ian+ang | ang、ian | 2 | 1-2 |
| 6 | 仿 | fǎnɡ | same | ang | ang | 1 | 3 |
| 7 | 双 | shuāng | same | uang | uang | 1 | 1 |
| 8 | 防线 | fánɡxiàn | cross | ang+ian | ang、ian | 2 | 2-4 |
| 9 | 向 | xiàng | same | iang | iang | 1 | 4 |
| 10 | 唤 | huàn | same | uan | uan | 1 | 4 |
| 11 | 掩 | yǎn | same | ian | ian | 1 | 3 |
| 12 | 占 | zhān | same | an | an | 1 | 1 |
| 13 | 偏向 | piānxiàng | cross | ian+iang | ian、iang | 2 | 1-4 |
| 14 | 沿 | yán | same | ian | ian | 1 | 2 |
| 15 | 碳 | tàn | same | an | an | 1 | 4 |

### front_nasal_basic（200 题，误差 +0.10%）

| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |
|---|---|---|---|---|---|---|---|
| 1 | 刊 | kān | core | an | an | 1 | 1 |
| 2 | 坦然 | tǎnrán | core | an+an | an | 2 | 3-2 |
| 3 | 自信 | zìxìn | supplement | -i_front+in | in | 2 | 4-4 |
| 4 | 安静 | ānjìng | supplement | an+ing | an | 2 | 1-4 |
| 5 | 近 | jìn | core | in | in | 1 | 4 |
| 6 | 陈 | chén | core | en | en | 1 | 2 |
| 7 | 殷勤 | yīnqín | core | in+in | in | 2 | 1-2 |
| 8 | 惨 | cǎn | core | an | an | 1 | 3 |
| 9 | 憾 | hàn | core | an | an | 1 | 4 |
| 10 | 主任 | zhǔrèn | supplement | u+en | en | 2 | 3-4 |
| 11 | 晨 | chén | core | en | en | 1 | 2 |
| 12 | 实战 | shízhàn | supplement | -i_back+an | an | 2 | 2-4 |
| 13 | 深 | shēn | core | en | en | 1 | 1 |
| 14 | 分散 | fēnsàn | core | en+an | an、en | 2 | 1-4 |
| 15 | 隐 | yǐn | core | in | in | 1 | 3 |

### jqx_special（194 题，误差 +0.11%）

| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |
|---|---|---|---|---|---|---|---|
| 1 | 溅 | jiàn | jqx_core | j | j | 1 | 4 |
| 2 | 案件 | ànjiàn | jqx_other | ZERO+j | j | 2 | 4-4 |
| 3 | 接近 | jiējìn | jqx_core | j+j | j | 2 | 1-4 |
| 4 | 悉 | xī | jqx_core | x | x | 1 | 1 |
| 5 | 契机 | qìjī | jqx_core | q+j | j、q | 2 | 4-1 |
| 6 | 长线 | chánɡxiàn | jqx_other | ch+x | x | 2 | 2-4 |
| 7 | 增加 | zēngjiā | flat_relation | z+j | j、z | 2 | 1-1 |
| 8 | 奇 | qí | jqx_core | q | q | 1 | 2 |
| 9 | 井 | jǐng | jqx_core | j | j | 1 | 3 |
| 10 | 席卷 | xíjuǎn | jqx_core | x+j | j、x | 2 | 2-3 |
| 11 | 项 | xiàng | jqx_core | x | x | 1 | 4 |
| 12 | 建造 | jiànzào | flat_relation | j+z | j、z | 2 | 4-4 |
| 13 | 锹 | qiāo | jqx_core | q | q | 1 | 1 |
| 14 | 减轻 | jiǎnqīng | jqx_core | j+q | j、q | 2 | 3-1 |
| 15 | 猜想 | cāixiǎnɡ | flat_relation | c+x | c、x | 2 | 1-3 |

### n_l_contrast（201 题，误差 +0.10%）

| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |
|---|---|---|---|---|---|---|---|
| 1 | 廉 | lián | core | l | l | 1 | 2 |
| 2 | 琉璃 | liú*lí | core | l+l | l | 2 | 2-2 |
| 3 | 尿 | niào | core | n | n | 1 | 4 |
| 4 | 动力 | dònglì | supplement | d+l | l | 2 | 4-4 |
| 5 | 卤 | lǔ | core | l | l | 1 | 3 |
| 6 | 露 | lù | core | l | l | 1 | 4 |
| 7 | 挠 | náo | core | n | n | 1 | 2 |
| 8 | 协力 | xiélì | supplement | x+l | l | 2 | 2-4 |
| 9 | 烙 | lào | core | l | l | 1 | 4 |
| 10 | 捻 | niǎn | core | n | n | 1 | 3 |
| 11 | 聋 | lónɡ | core | l | l | 1 | 2 |
| 12 | 凌乱 | línɡluàn | core | l+l | l | 2 | 2-4 |
| 13 | 拢 | lǒng | core | l | l | 1 | 3 |
| 14 | 嫩 | nèn | core | n | n | 1 | 4 |
| 15 | 上路 | shànɡlù | supplement | sh+l | l | 2 | 4-4 |

### retroflex_focus（195 题，误差 +0.12%）

| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |
|---|---|---|---|---|---|---|---|
| 1 | 祝 | zhù | core | zh | zh | 1 | 4 |
| 2 | 闪烁 | shǎnshuò | core | sh+sh | sh | 2 | 3-4 |
| 3 | 蜀 | shǔ | core | sh | sh | 1 | 3 |
| 4 | 支柱 | zhīzhù | core | zh+zh | zh | 2 | 1-4 |
| 5 | 超 | chāo | core | ch | ch | 1 | 1 |
| 6 | 正视 | zhèngshì | core | zh+sh | sh、zh | 2 | 4-4 |
| 7 | 溶 | róng | core | r | r | 1 | 2 |
| 8 | 真诚 | zhēnchéng | core | zh+ch | ch、zh | 2 | 1-2 |
| 9 | 朕 | zhèn | core | zh | zh | 1 | 4 |
| 10 | 差事 | chāishi | core | ch+sh | ch、sh | 2 | 1-0 |
| 11 | 升 | shēng | core | sh | sh | 1 | 1 |
| 12 | 成长 | chéngzhǎng | core | ch+zh | ch、zh | 2 | 2-3 |
| 13 | 铲 | chǎn | core | ch | ch | 1 | 3 |
| 14 | 来势 | láishì | supplement | l+sh | sh | 2 | 2-4 |
| 15 | 正 | zhèng | core | zh | zh | 1 | 4 |

### simple_final_focus（195 题，误差 +0.01%）

| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |
|---|---|---|---|---|---|---|---|
| 1 | 地力 | dìlì | core | i+i | i | 2 | 4-4 |
| 2 | 幂 | mì | core | i | i | 1 | 4 |
| 3 | 收入 | shōurù | supplement | ou+u | u | 2 | 1-4 |
| 4 | 舒 | shū | core | u | u | 1 | 1 |
| 5 | 逃避 | táobì | supplement | ao+i | i | 2 | 2-4 |
| 6 | 掩蔽 | yǎnbì | supplement | ian+i | i | 2 | 3-4 |
| 7 | 固然 | gùrán | supplement | u+an | u | 2 | 4-2 |
| 8 | 不必 | bùbì | core | u+i | i、u | 2 | 4-4 |
| 9 | 夫妇 | fūfù | core | u+u | u | 2 | 1-4 |
| 10 | 砸 | zá | core | a | a | 1 | 2 |
| 11 | 贫瘠 | pínjí | supplement | in+i | i | 2 | 2-2 |
| 12 | 异物 | yìwù | core | i+u | i、u | 2 | 4-4 |
| 13 | 滤 | lǜ | core | ü | ü | 1 | 4 |
| 14 | 利于 | lìyú | core | i+ü | i、ü | 2 | 4-2 |
| 15 | 荷 | hé | core | e | e | 1 | 2 |

### tone_1（197 题，误差 +0.30%）

| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |
|---|---|---|---|---|---|---|---|
| 1 | 结 | jiē | core | 1 | 1 | 1 | 1 |
| 2 | 收工 | shōuɡōnɡ | core | 1+1 | 1 | 2 | 1-1 |
| 3 | 轰 | hōng | core | 1 | 1 | 1 | 1 |
| 4 | 经商 | jīnɡshānɡ | core | 1+1 | 1 | 2 | 1-1 |
| 5 | 筐 | kuāng | core | 1 | 1 | 1 | 1 |
| 6 | 生疏 | shēnɡshū | core | 1+1 | 1 | 2 | 1-1 |
| 7 | 诛 | zhū | core | 1 | 1 | 1 | 1 |
| 8 | 今天 | jīntiān | core | 1+1 | 1 | 2 | 1-1 |
| 9 | 曰 | yuē | core | 1 | 1 | 1 | 1 |
| 10 | 方针 | fāngzhēn | core | 1+1 | 1 | 2 | 1-1 |
| 11 | 剜 | wān | core | 1 | 1 | 1 | 1 |
| 12 | 高温 | gāowēn | core | 1+1 | 1 | 2 | 1-1 |
| 13 | 漆 | qī | core | 1 | 1 | 1 | 1 |
| 14 | 唏嘘 | xīxū | core | 1+1 | 1 | 2 | 1-1 |
| 15 | 音量 | yīnliàng | supplement | 1+4 | 1 | 2 | 1-4 |

### tone_3（184 题，误差 +0.54%）

| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |
|---|---|---|---|---|---|---|---|
| 1 | 缓 | huǎn | core | 3 | 3 | 1 | 3 |
| 2 | 起草 | qǐcǎo | core | 3+3 | 3 | 2 | 3-3 |
| 3 | 假 | jiǎ | core | 3 | 3 | 1 | 3 |
| 4 | 处女 | chǔnǚ | core | 3+3 | 3 | 2 | 3-3 |
| 5 | 咧 | liě | core | 3 | 3 | 1 | 3 |
| 6 | 辅导 | fǔdǎo | core | 3+3 | 3 | 2 | 3-3 |
| 7 | 老 | lǎo | core | 3 | 3 | 1 | 3 |
| 8 | 累 | lěi | core | 3 | 3 | 1 | 3 |
| 9 | 政体 | zhènɡtǐ | supplement | 4+3 | 3 | 2 | 4-3 |
| 10 | 发抖 | fādǒu | supplement | 1+3 | 3 | 2 | 1-3 |
| 11 | 改善 | gǎishàn | supplement | 3+4 | 3 | 2 | 3-4 |
| 12 | 脑海 | nǎohǎi | core | 3+3 | 3 | 2 | 3-3 |
| 13 | 停止 | tíngzhǐ | supplement | 2+3 | 3 | 2 | 2-3 |
| 14 | 髓 | suǐ | core | 3 | 3 | 1 | 3 |
| 15 | 晚 | wǎn | core | 3 | 3 | 1 | 3 |

### tone_all（187 题，误差 +0.11%）

| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |
|---|---|---|---|---|---|---|---|
| 1 | 变色 | biànsè | all | 4+4 | 4 | 2 | 4-4 |
| 2 | 仲 | zhònɡ | all | 4 | 4 | 1 | 4 |
| 3 | 工事 | ɡōnɡshì | all | 1+4 | 1、4 | 2 | 1-4 |
| 4 | 夺目 | duómù | all | 2+4 | 2、4 | 2 | 2-4 |
| 5 | 板凳 | bǎndèng | all | 3+4 | 3、4 | 2 | 3-4 |
| 6 | 光能 | ɡuānɡnénɡ | all | 1+2 | 1、2 | 2 | 1-2 |
| 7 | 呆 | dāi | all | 1 | 1 | 1 | 1 |
| 8 | 意识 | yì•shí | all | 4+2 | 2、4 | 2 | 4-2 |
| 9 | 核能 | hénénɡ | all | 2+2 | 2 | 2 | 2-2 |
| 10 | 哥哥 | gēgē | all | 1+1 | 1 | 2 | 1-1 |
| 11 | 怜 | lián | all | 2 | 2 | 1 | 2 |
| 12 | 号码 | hàomǎ | all | 4+3 | 3、4 | 2 | 4-3 |
| 13 | 纲领 | gānglǐng | all | 1+3 | 1、3 | 2 | 1-3 |
| 14 | 下跌 | xiàdiē | all | 4+1 | 1、4 | 2 | 4-1 |
| 15 | 氯气 | lǜqì | all | 4+4 | 4 | 2 | 4-4 |
