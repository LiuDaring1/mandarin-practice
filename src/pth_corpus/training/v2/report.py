"""Markdown report builders for v2 availability matrix and benchmark."""

from __future__ import annotations

from typing import Any


def _pct(v: float) -> str:
    return f"{v:.1%}"


def build_availability_report(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# v2 训练 Profile 可用性矩阵 PROFILE_AVAILABILITY_REPORT_V2")
    lines.append("")
    lines.append(f"- 生成器版本：`{payload.get('generator_version')}`")
    lines.append(f"- 数据基线：`{payload.get('data_version')}`")
    lines.append(f"- 可用条目：{payload.get('available_item_count')}")
    lines.append("")
    lines.append("## 一、总览")
    lines.append("")
    lines.append("| Profile | 模式 | 候选数 | 核心池 | 10分钟核心 | 20分钟核心 | 缺失组合 | 稀缺组合 |")
    lines.append("|---|---|---:|---:|---|---:|---:|---:|")
    for p in payload["profiles"]:
        core = p.get("core_pool_size", 0)
        d10 = p["duration_sufficiency"]["10"]["status"]
        d20 = p["duration_sufficiency"]["20"]["status"]
        core_roles = {"core", "cross", "same", "all", "adjacent"}
        missing = sum(
            len(b.get("missing_patterns", []))
            for b in p["buckets"].values()
            if b.get("role") in core_roles
        )
        scarce = sum(
            len(b.get("scarce_patterns", []))
            for b in p["buckets"].values()
            if b.get("role") in core_roles
        )
        lines.append(
            f"| `{p['profile_id']}` {p['profile_name']} | {p['mode']} "
            f"| {p['candidate_count']} | {core} | {d10} | {d20} "
            f"| {missing} | {scarce} |"
        )
    lines.append("")
    lines.append("> 核心池 = 核心桶全部 item（含单字核心点）；状态 OK / need_repeat / insufficient。")
    lines.append("")

    lines.append("## 二、各 Profile 明细")
    lines.append("")
    for p in payload["profiles"]:
        lines.append(f"### {p['profile_id']} · {p['profile_name']}")
        lines.append("")
        lines.append(
            f"模式 `{p['mode']}`；候选 {p['candidate_count']} 条；"
            f"核心池 {p.get('core_pool_size', 0)} 条；"
            f"allow_other={p.get('allow_other')}"
        )
        lines.append("")
        lines.append("**时长充足性**")
        lines.append("")
        lines.append("| 时长 | 需核心 | 核心池 | 状态 |")
        lines.append("|---|---:|---:|---|")
        for mins in ("5", "10", "15", "20"):
            d = p["duration_sufficiency"][mins]
            lines.append(
                f"| {mins} 分钟 | {d['core_needed']} | {d['core_unique_pool']} "
                f"| {d['status']} |"
            )
        lines.append("")
        for bucket_id, b in p["buckets"].items():
            lines.append(f"**桶 {bucket_id}（{b['label']}，目标 {_pct(b['target_ratio'])}）**")
            lines.append("")
            lines.append(
                f"item {b['item_count']} 条：单字 {b['single_count']} / "
                f"双字 {b['two_count']} / 三字+ {b['three_plus_count']}"
            )
            patterns = b["patterns"]
            top = sorted(patterns.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
            lines.append("")
            lines.append("| pattern | 候选数 |")
            lines.append("|---|---:|")
            for pat, count in top:
                lines.append(f"| {pat} | {count} |")
            if b.get("missing_patterns"):
                lines.append("")
                lines.append(
                    f"缺失（0 候选，{len(b['missing_patterns'])} 个）："
                    + "、".join(b["missing_patterns"])
                )
            if b.get("scarce_patterns"):
                scarce_txt = "、".join(
                    f"{k}({v})" for k, v in b["scarce_patterns"]
                )
                lines.append("")
                lines.append(f"稀缺（<10，{len(b['scarce_patterns'])} 个）：{scarce_txt}")
            lines.append("")
    return "\n".join(lines)


def build_generator_report_v2(summary: dict[str, Any],
                               profiles: list[Any],
                               config: Any) -> str:
    lines: list[str] = []
    lines.append("# 平衡随机训练生成器 v2 首轮报告 GENERATOR_REPORT_V2")
    lines.append("")
    lines.append(f"- 生成器版本：`{summary.get('generator_version')}`")
    lines.append(f"- Profile 配置：`training_profiles_v2.json`")
    lines.append(f"- 数据基线：`{summary.get('data_version')}`")
    lines.append(f"- 生成时间：{summary.get('generated_at', '')}")
    lines.append("")
    qa = summary["qa_summary"]
    lines.append("## 一、QA 汇总")
    lines.append("")
    lines.append("| 指标 | 结果 |")
    lines.append("|---|---|")
    lines.append(f"| Session 数 | {qa['sessions']} |")
    lines.append(f"| Profile 候选错误 | {qa['profile_errors']} |")
    lines.append(f"| bucket 分类错误 | {qa['bucket_errors']} |")
    lines.append(f"| 同 Session 重复 item | {qa['duplicate_errors']} |")
    lines.append(f"| 相同 seed 不可复现 | {qa['reproducibility_errors']} |")
    lines.append(f"| 生成失败 | {qa['generation_failures']} |")
    lines.append(
        f"| 最大时长相对误差 | {_pct(qa['max_duration_rel_error'])} |"
    )
    lines.append("")

    by_profile: dict[str, list[dict[str, Any]]] = {}
    for s in summary["session_stats"]:
        by_profile.setdefault(s["profile_id"], []).append(s)
    lines.append("## 二、各 Profile 试跑统计")
    lines.append("")
    lines.append("| Profile | Session数 | 题数范围 | 时长误差 | 核心占比 | 重复 item | 放宽次数 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for pid in sorted(by_profile):
        ss = by_profile[pid]
        counts = [s["item_count"] for s in ss]
        errs = [s["duration_rel_error"] for s in ss]
        core = 0.0
        repeats = 0
        relax = 0
        for s in ss:
            core_role = {
                "core",
                "cross",
                "all",
                "adjacent",
                "jqx_core",
            }
            core += sum(
                v["share"]
                for k, v in s["bucket_item_shares"].items()
                if k in core_role
            )
            repeats += s["repeated_items"]["count"]
            relax += len(s["relaxed_constraints"])
        core /= max(1, len(ss))
        lines.append(
            f"| `{pid}` | {len(ss)} | {min(counts)}–{max(counts)} "
            f"| {min(errs):+.2%} ~ {max(errs):+.2%} "
            f"| {core:.1%} | {repeats} | {relax} |"
        )
    lines.append("")

    lines.append("## 三、首批 Session 前 15 条（每个 Profile 取 seed 20260804 的 10 分钟）")
    lines.append("")
    sessions = {
        s["session_id"]: s
        for s in summary["session_stats"]
        if s["seed"] == 20260804 and s["duration_minutes"] == 10
    }
    for pid in sorted(by_profile):
        sid = f"{pid}-10m-seed20260804-rep1"
        if sid not in sessions:
            continue
        stat = sessions[sid]
        path = stat["session_path"]
        import json
        from pathlib import Path

        session = json.loads(Path(path).read_text(encoding="utf-8"))
        lines.append(f"### {pid}（{session['item_count']} 题，"
                     f"误差 {session['duration_rel_error']:+.2%}）")
        lines.append("")
        lines.append("| # | 字词 | 拼音 | bucket | pattern | 目标音 | 词长 | 调型 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for e in session["items"][:15]:
            lines.append(
                f"| {e['order']} | {e['word']} | {e['pinyin']} "
                f"| {e['bucket_id']} | {e['credited_pattern']} "
                f"| {'、'.join(e['target_values']) or '-'} "
                f"| {e['syllable_count']} | {e['tone_pattern']} |"
            )
        lines.append("")
    return "\n".join(lines)
