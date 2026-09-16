"""Markdown report builders for candidate-pool stats and benchmark runs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import GENERATOR_VERSION, SOURCE_DATA_VERSION, TrainingProfile


def _fmt_pct(value: float) -> str:
    return f"{value:.1%}"


def _duration_row(d: dict[str, float]) -> str:
    return (
        f"min {d['min']}s / p10 {d['p10']}s / 均值 {d['mean']}s / "
        f"p90 {d['p90']}s / max {d['max']}s"
    )


def build_candidate_pool_report(stats: dict[str, Any],
                                profiles: list[TrainingProfile],
                                config: Any) -> str:
    lines: list[str] = []
    lines.append("# 训练候选池统计报告 CANDIDATE_POOL_REPORT_V1")
    lines.append("")
    lines.append(f"- 生成器版本：`{GENERATOR_VERSION}`")
    lines.append(f"- Profile 配置：`training_profiles_v1.json`")
    lines.append(f"- 生成器配置：`generator_config_v1.json`（{config.version}）")
    lines.append(f"- 数据基线：`{SOURCE_DATA_VERSION}`")
    lines.append(f"- 可用条目：{stats['available_item_count']}")
    lines.append(
        "- 生成时间：" + stats.get("generated_at", datetime.now(timezone.utc).isoformat())
    )
    lines.append("")
    lines.append("> 目的：让参数建立在真实数据分布上，而不是拍脑袋。")
    lines.append("")

    profile_by_id = {p.id: p for p in profiles}
    lines.append("## 一、总览")
    lines.append("")
    lines.append("| Profile | 名称 | 候选数 | 占可用比 | 1音节 | 2音节 | 3音节 | 4音节 | 平均切片 | 平均题长(1遍) |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for p in stats["profiles"]:
        lens = p["word_lengths"]["counts"]
        clip = p["clip_duration_sec"]
        est1 = p["est_item_duration_sec"]["repetitions_1"]
        lines.append(
            f"| `{p['profile_id']}` | {p['profile_name']} | {p['candidate_count']} "
            f"| {_fmt_pct(p['candidate_share_of_available'])} "
            f"| {lens.get('1', 0)} | {lens.get('2', 0)} "
            f"| {lens.get('3', 0)} | {lens.get('4', 0)} "
            f"| {clip['mean']}s | {est1['mean']}s |"
        )
    lines.append("")

    lines.append("## 二、各 Profile 明细")
    lines.append("")
    for p in stats["profiles"]:
        profile = profile_by_id[p["profile_id"]]
        lines.append(f"### {p['profile_id']} · {p['profile_name']}")
        lines.append("")
        lines.append(f"候选 item：**{p['candidate_count']}**（占可用 "
                     f"{_fmt_pct(p['candidate_share_of_available'])}）")
        lines.append("")

        if p["dimensions"]:
            lines.append("**目标子项分布（item 包含数）**")
            lines.append("")
            lines.append("| 子项 | 候选数 | 占比 | 目标占比 | 所属组 |")
            lines.append("|---|---:|---:|---:|---|")
            for dim in profile.balance_dimensions:
                counts = p["dimensions"][dim.id]["counts"]
                shares = p["dimensions"][dim.id]["shares"]
                target_shares = p["dimensions"][dim.id].get("target_shares", {})
                group_of: dict[str, str] = {}
                for gid, gvals in dim.groups.items():
                    for v in gvals:
                        group_of.setdefault(v, gid)
                for v in dim.values:
                    lines.append(
                        f"| {v} | {counts.get(v, 0)} | {_fmt_pct(shares.get(v, 0.0))} "
                        f"| {_fmt_pct(target_shares.get(v, 0.0))} "
                        f"| {group_of.get(v, '-')} |"
                    )
                if dim.groups:
                    lines.append("")
                    lines.append("**分组（组内任一子项即计入）**")
                    lines.append("")
                    lines.append("| 组 | 候选数 | 占比 | 目标占比 |")
                    lines.append("|---|---:|---:|---:|")
                    for gid in dim.groups:
                        gcount = p["dimensions"][dim.id]["group_counts"].get(gid, 0)
                        gshare = p["dimensions"][dim.id]["group_shares"].get(gid, 0.0)
                        gtarget = p["dimensions"][dim.id].get(
                            "group_target_shares", {}
                        ).get(gid)
                        target_txt = _fmt_pct(gtarget) if gtarget is not None else "-"
                        lines.append(
                            f"| {gid} | {gcount} | {_fmt_pct(gshare)} | {target_txt} |"
                        )
                lines.append("")

        if profile.position_dimension:
            pos = p["position"]
            lines.append("**目标音位置**")
            lines.append("")
            lines.append("| 类别 | 候选数 | 占比 |")
            lines.append("|---|---:|---:|")
            for cat in ("1", "2", "3+", "multiple"):
                lines.append(
                    f"| {cat} | {pos['counts'].get(cat, 0)} "
                    f"| {_fmt_pct(pos['shares'].get(cat, 0.0))} |"
                )
            lines.append("")
            lines.append("**目标出现次数分布**")
            lines.append("")
            lines.append("| 次数 | 候选数 | 占比 |")
            lines.append("|---|---:|---:|")
            for occ, count in pos["occurrence_counts"].items():
                lines.append(
                    f"| {occ} | {count} | {_fmt_pct(pos['occurrence_shares'].get(occ, 0.0))} |"
                )
            lines.append("")

        purity = p.get("purity", {})
        if purity.get("counts"):
            lines.append("**目标音纯度（全目标词 / 部分目标词）**")
            lines.append("")
            lines.append("| 纯度 | 候选数 | 占比 | 目标占比 |")
            lines.append("|---|---:|---:|---:|")
            for bucket in ("full", "partial", "none"):
                if bucket not in purity["counts"]:
                    continue
                target = purity["target_shares"].get(bucket)
                target_txt = _fmt_pct(target) if target is not None else "-"
                lines.append(
                    f"| {bucket} | {purity['counts'][bucket]} "
                    f"| {_fmt_pct(purity['shares'].get(bucket, 0.0))} "
                    f"| {target_txt} |"
                )
            lines.append("")

        lens = p["word_lengths"]
        lines.append("**词长分布**")
        lines.append("")
        lines.append("| 音节数 | 候选数 | 占比 |")
        lines.append("|---|---:|---:|")
        for bucket in ("1", "2", "3", "4", "5+"):
            if bucket in lens["counts"]:
                lines.append(
                    f"| {bucket} | {lens['counts'][bucket]} "
                    f"| {_fmt_pct(lens['shares'].get(bucket, 0.0))} |"
                )
        lines.append("")

        tones = p["tone_patterns"]
        lines.append("**tone_pattern Top 10**")
        lines.append("")
        lines.append("| 调型 | 候选数 | 占比 |")
        lines.append("|---|---:|---:|")
        for pattern, count in p["tone_pattern_top15"][:10]:
            lines.append(
                f"| {pattern} | {count} | {_fmt_pct(tones['shares'].get(pattern, 0.0))} |"
            )
        lines.append("")

        lines.append("**时长**")
        lines.append("")
        lines.append(f"- 切片时长：{_duration_row(p['clip_duration_sec'])}")
        lines.append(
            "- 单题预计（1 遍）："
            f"{_duration_row(p['est_item_duration_sec']['repetitions_1'])}"
        )
        lines.append(
            "- 单题预计（2 遍）："
            f"{_duration_row(p['est_item_duration_sec']['repetitions_2'])}"
        )
        lines.append("")

    lines.append("## 三、对生成参数的影响")
    lines.append("")
    lines.append("1. 词长分布与文档建议（1:20% / 2:55% / 3:20% / 4+:5%）差异较大的 Profile，生成器按真实候选池比例作为目标，而不是硬套建议值。")
    lines.append("2. 平翘舌、n/l、前后鼻音等 Profile 的组内子项天然不平衡，动态权重会按候选池占比纠偏，但不会强求 50/50。")
    lines.append("3. 平均单题时长约 3.1–3.3 秒（1 遍），5/10/20 分钟对应的题量约为 90/180/360 条量级，生成时可观察实际数量。")
    lines.append("4. 具体调型数量多且分散，采用“接近候选池占比 + 连续 3 条上限”策略，避免机械均匀。")
    lines.append("")
    return "\n".join(lines)


def _first_items_table(session: dict[str, Any], limit: int = 30) -> list[str]:
    lines = [
        "| # | item_id | 字词 | 拼音 | 目标音 | 位置 | 词长 | 调型 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for entry in session["items"][:limit]:
        tf = entry["target_features"]
        sub = ",".join(tf["target_subfeatures"]) or "-"
        pos = ",".join(str(p) for p in tf["target_positions"]) or "-"
        lines.append(
            f"| {entry['order']} | {entry['item_id']} | {entry['word']} "
            f"| {entry['pinyin']} | {sub} | {pos} | {entry['syllable_count']} "
            f"| {entry['tone_pattern']} |"
        )
    return lines


def _demo_sessions(all_sessions: list[dict[str, Any]],
                   main_ids: list[str]) -> dict[str, dict[str, Any]]:
    demos: dict[str, dict[str, Any]] = {}
    for sid in main_ids:
        for session in all_sessions:
            if (
                session["profile_id"] == sid
                and session["requested_duration_sec"] == 600
            ):
                demos[sid] = session
                break
    return demos


def build_generator_report(stats: dict[str, Any], profiles: list[TrainingProfile],
                           config: Any,
                           all_sessions: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# 平衡随机训练生成器首轮报告 GENERATOR_REPORT_V1")
    lines.append("")
    lines.append(f"- 生成器版本：`{GENERATOR_VERSION}`")
    lines.append(f"- Profile 配置：`training_profiles_v1.json`")
    lines.append(f"- 生成器配置：`generator_config_v1.json`（{config.version}）")
    lines.append(f"- 数据基线：`{SOURCE_DATA_VERSION}`")
    lines.append("- 生成时间：" + stats.get("generated_at", ""))
    lines.append("")

    qa = stats["qa_summary"]
    lines.append("## 一、批量试跑 QA 汇总")
    lines.append("")
    lines.append("| 指标 | 结果 |")
    lines.append("|---|---|")
    lines.append(f"| Session 数 | {qa['sessions']} |")
    lines.append(f"| Profile 候选错误 | {qa['profile_errors']} |")
    lines.append(f"| 候选不匹配错误 | {qa['candidate_mismatch_errors']} |")
    lines.append(f"| 同 Session 重复 item | {qa['duplicate_errors']} |")
    lines.append(f"| 相同 seed 不可复现 | {qa['reproducibility_errors']} |")
    lines.append(f"| 生成失败 | {qa['generation_failures']} |")
    lines.append(
        f"| 最大时长绝对误差 | {qa['max_duration_abs_error_sec']}s "
        f"（相对 {_fmt_pct(qa['max_duration_rel_error'])}） |"
    )
    lines.append("")

    lines.append("## 二、各 Profile 试跑统计")
    lines.append("")
    profile_by_id = {p.id: p for p in profiles}
    by_profile: dict[str, list[dict[str, Any]]] = {}
    for s in stats["session_stats"]:
        by_profile.setdefault(s["profile_id"], []).append(s)
    lines.append("| Profile | Session数 | 候选池 | 题数范围 | 时长误差范围 | 目标音最长连击 | 位置最长连击 | 词长最长连击 | 调型最长连击 | 放宽次数 |")
    lines.append("|---|---:|---:|---:|---|---:|---:|---:|---:|---:|")
    for pid in sorted(by_profile):
        sessions = by_profile[pid]
        profile = profile_by_id[pid]
        counts = [s["item_count"] for s in sessions]
        errs = [s["duration_rel_error"] for s in sessions]
        runs = [s["max_runs"] for s in sessions]
        relax = sum(len(s["relaxed_constraints"]) for s in sessions)
        lines.append(
            f"| `{pid}` {profile.name} | {len(sessions)} "
            f"| {sessions[0]['candidate_count']} "
            f"| {min(counts)}–{max(counts)} "
            f"| {min(errs):+.2%} ~ {max(errs):+.2%} "
            f"| {max(r['max_same_target_run'] for r in runs)} "
            f"| {max(r['max_same_position_run'] for r in runs)} "
            f"| {max(r['max_same_length_run'] for r in runs)} "
            f"| {max(r['max_same_tone_pattern_run'] for r in runs)} "
            f"| {relax} |"
        )
    lines.append("")

    lines.append("## 三、不同 seed 随机性（重叠度）")
    lines.append("")
    lines.append("| 组 | 平均 item 重叠率 | 平均序列重叠率 |")
    lines.append("|---|---:|---:|")
    for key, overlap in stats["overlap_summary"].items():
        mi = overlap.get("mean_item_overlap")
        ms = overlap.get("mean_sequence_overlap")
        lines.append(
            f"| {key} | {'-' if mi is None else f'{mi:.2%}'} "
            f"| {'-' if ms is None else f'{ms:.2%}'} |"
        )
    lines.append("")
    lines.append("> 判断标准：item 重叠率应明显低于 1，且不同 seed 序列位置不应高度重合。")
    lines.append("")

    lines.append("## 三·B、组平衡实测 vs 目标")
    lines.append("")
    group_rows: list[tuple[str, str, str, int, int]] = []
    for s in stats["session_stats"]:
        profile = profile_by_id[s["profile_id"]]
        for dim in profile.balance_dimensions:
            if not dim.target_group_shares:
                continue
            for gid, target in dim.target_group_shares.items():
                group_rows.append(
                    (
                        s["profile_id"],
                        f"{dim.label}/{gid}",
                        f"{target:.0%}",
                        s["target_groups"].get(dim.id, {}).get(gid, 0),
                        s["item_count"],
                    )
                )
    if group_rows:
        by_group: dict[tuple[str, str], list[tuple[int, int]]] = {}
        for pid, gkey, _target, count, item_count in group_rows:
            by_group.setdefault((pid, gkey), []).append((count, item_count))
        lines.append("| Profile | 组 | 目标占比 | 各 Session 出现数 |")
        lines.append("|---|---|---:|---|")
        target_by_key = {(row[0], row[1]): row[2] for row in group_rows}
        for (pid, gkey), counts in sorted(by_group.items()):
            target = target_by_key[(pid, gkey)]
            counts_only = [c for c, _ in counts]
            shares = [c / max(1, n) for c, n in counts]
            lines.append(
                f"| {pid} | {gkey} | {target} | "
                f"{min(counts_only)}–{max(counts_only)}（占比均值 {sum(shares) / len(shares):.1%}） |"
            )
        lines.append("")
    lines.append("> 说明：组内子项仍按候选池自然比例分配；只有组间比例使用 Profile 目标。")
    lines.append("")

    lines.append("## 三·C-2、专项纯度实测（全目标词占比）")
    lines.append("")
    purity_rows: dict[str, dict[str, list[float]]] = {}
    for s in stats["session_stats"]:
        buckets = s.get("purity", {})
        total = sum(buckets.values())
        if not total:
            continue
        row = purity_rows.setdefault(s["profile_id"], {})
        for bucket in ("full", "partial"):
            row.setdefault(bucket, []).append(
                buckets.get(bucket, 0) / total
            )
    if purity_rows:
        lines.append("| Profile | 全目标词均值 | 部分目标词均值 |")
        lines.append("|---|---:|---:|")
        for pid in sorted(purity_rows):
            row = purity_rows[pid]
            full = sum(row.get("full", [])) / max(1, len(row.get("full", [])))
            part = sum(row.get("partial", [])) / max(1, len(row.get("partial", [])))
            lines.append(f"| {pid} | {full:.1%} | {part:.1%} |")
        lines.append("")

    lines.append("## 三·C、位置分布实测（各 Profile Session 均值占比）")
    lines.append("")
    pos_rows: dict[str, dict[str, int]] = {}
    for s in stats["session_stats"]:
        pos_rows.setdefault(s["profile_id"], {})
        for cat, count in s["positions"].items():
            pos_rows[s["profile_id"]][cat] = (
                pos_rows[s["profile_id"]].get(cat, 0) + count
            )
    lines.append("| Profile | 位置1 | 位置2 | 3+ | 多位置 |")
    lines.append("|---|---:|---:|---:|---:|")
    for pid, counts in sorted(pos_rows.items()):
        total = sum(counts.values())
        if not total:
            continue
        cells = []
        for cat in ("1", "2", "3+", "multiple"):
            cells.append(f"{_fmt_pct(counts.get(cat, 0) / total)}")
        lines.append(f"| {pid} | " + " | ".join(cells) + " |")
    lines.append("")

    demos = _demo_sessions(
        all_sessions,
        [
            "initial_flat_retroflex",
            "initial_n_l",
            "final_front_nasal",
            "final_back_nasal",
            "final_front_back_nasal",
            "general",
        ],
    )
    lines.append("## 四、首批 6 个 Profile · 10 分钟 Session 前 30 条")
    lines.append("")
    for pid, session in demos.items():
        profile = profile_by_id[pid]
        lines.append(f"### {pid} · {profile.name}（seed={session['seed']}）")
        lines.append("")
        lines.append(
            f"- 题数：{session['item_count']}；预计时长："
            f"{session['estimated_duration_sec']}s；"
            f"相对误差：{session['duration_rel_error']:+.2%}"
        )
        lines.append("")
        lines.extend(_first_items_table(session))
        lines.append("")

    lines.append("## 五、建议调整项")
    lines.append("")
    lines.append("1. 若某 Profile 目标子项长期失衡，优先调 `weight_coverage` / `weight_group`，而不是改硬约束。")
    lines.append("2. 若序列仍太机械，可扩大 `top_k` 或提高 `random_jitter`。")
    lines.append("3. 若随机性太强导致分布乱，可提高 coverage 相关权重或降低 jitter。")
    lines.append("4. 若总是生成相同词，检查候选池大小与 seed 组合；候选不足的 Profile（如儿化）会自然放宽连续约束。")
    lines.append("5. 时长参数（`extra_follow_sec` / `min_follow_sec` / `transition_sec`）为实验值，等有播放器后按真实试听调整。")
    lines.append("")
    return "\n".join(lines)
