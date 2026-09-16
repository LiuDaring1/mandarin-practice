"""Command-line entry points for the corpus workflow."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sqlite3
from typing import Any

from . import __version__
from .audio_fetch import AudioFetchError, fetch_full_audio, fetch_pilot_audio
from .audio_analysis import AudioAnalysisError, analyze_full, analyze_pilot
from .segmentation import SegmentationError, segment_full, segment_pilot
from .discovery import DiscoveryError, discover_sources
from .detail_fetch import DetailFetchError, fetch_full_html, fetch_pilot_html
from .detail_parse import DetailParseError, parse_full, parse_pilot
from .review_app import ReviewAppError, create_app, validate_loopback_host
from .nasal_review import (
    DECISION_LABELS,
    NasalReviewError,
    create_nasal_review_app,
    validate_loopback_host as validate_nasal_host,
)
from .nasal_clean import NasalCleanError, apply_nasal_decisions, undo_nasal_clean
from .qa import QAGateError, qa_full, qa_pilot
from .repair import RepairError, apply_adjustments
from .sentence_reading import (
    SentenceReadingError,
    add_sentence_parser,
    dispatch_sentence,
)
from .sentence_review import (
    SentenceReviewError,
    create_app as create_sentence_review_app,
    validate_loopback_host as validate_sentence_host,
)
from .source_quality import run_source_quality
from .phonology import DEFAULT_SEED, run_pipeline
from .prototype_app import PrototypeAppError, create_app
from .training.candidates import load_items
from .training.generator import (
    generate_session,
    run_benchmark,
    run_candidate_stats,
    write_session_file,
)
from .training.v2.engine import compute_availability
from .training.v2.generator import (
    _universe_from_items,
    generate_session_v2,
    run_availability_v2,
    run_benchmark_v2,
)
from .training.v2.history import HistoryStore
from .training.v2.schema import load_v2_profiles
from .training.models import (
    CONFIG_FILENAME,
    PROFILES_FILENAME,
    load_config,
    load_profiles,
)

COMMANDS = (
    "discover",
    "fetch",
    "parse",
    "segment",
    "qa",
    "sourcecheck",
    "review",
    "nasal-review",
    "nasal-clean",
    "phonology",
    "training",
    "prototype",
    "sentence",
    "sentence-review",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pth-corpus",
        description="Local Mandarin pronunciation corpus workflow (scaffold).",
    )
    parser.add_argument("--version", action="version", version=f"pth-corpus {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    training_subparser = None
    for command in COMMANDS:
        implemented = command in {"discover", "qa"}
        if command in {"fetch", "parse"}:
            implemented = True
        if command == "sentence":
            add_sentence_parser(subparsers)
            continue
        subparser = subparsers.add_parser(
            command,
            help=(
                f"{command} pilot HTML stage"
                if command in {"fetch", "parse"}
                else f"{command} source discovery"
                if command == "discover"
                else "segment pilot audio from the validated analysis report"
                if command == "segment"
                else "run the pilot machine QA gate"
                if command == "qa"
                else "screen word/pinyin/audio consistency and flag source errors"
                if command == "sourcecheck"
                else "run the local review web app"
                if command == "review"
                else "run the local front/back-nasal listening review app"
                if command == "nasal-review"
                else "apply/undo nasal listening decisions (exclude or re-cut)"
                if command == "nasal-clean"
                else "run deterministic phonology tagging and QA"
                if command == "phonology"
                else "generate balanced-random training sessions"
                if command == "training"
                else "run the local Mandarin practice prototype web app"
                if command == "prototype"
                else "run the local sentence-practice listening review app"
                if command == "sentence-review"
                else f"{command} stage (currently a scaffold)"
            ),
            description=(
                "Discover pthxx source detail pages from the seven HTTP indexes."
                if command == "discover"
                else "Fetch pilot detail HTML or direct MP3 assets, or parse HTML."
                if command in {"fetch", "parse"}
                else "Segment pilot audio; use --analyze-only to stop after tail/candidate analysis."
                if command == "segment"
                else "Run read-only machine QA for the pilot corpus and publish a deterministic report."
                if command == "qa"
                else "Run read-only source-quality screening (pinyin lexicon + audio tone contour) and publish a flagged report."
                if command == "sourcecheck"
                else "Run the local-only FastAPI review app."
                if command == "review"
                else "Run the local-only nasal listening review app over one audit batch."
                if command == "nasal-review"
                else "Apply (or undo) nasal listening decisions: exclude wrong-word/tone/quality/shift items, re-cut shift items, atomically and idempotently."
                if command == "nasal-clean"
                else "Run deterministic phonology-v1 tagging (syllable/item features, stats, QA)."
                if command == "phonology"
                else "Run the balanced-random training generator (sessions, stats, reports)."
                if command == "training"
                else "Run the local-only Mandarin practice prototype app."
                if command == "prototype"
                else "Run the local-only sentence-practice listening review app."
                if command == "sentence-review"
                else f"{command} stage; not implemented in the project scaffold."
            ),
        )
        subparser.set_defaults(_command=command)
        if command == "training":
            training_subparser = subparser
        if command in {"discover", "fetch", "parse"}:
            subparser.add_argument(
                "--db",
                default=str(Path("data") / "corpus.sqlite3"),
                help="SQLite database path (default: data/corpus.sqlite3)",
            )
            subparser.add_argument(
                "--data-root",
                default="data",
                help="Data root containing raw/ and derived/ (default: data)",
            )
            subparser.add_argument(
                "--timeout",
                type=float,
                default=10.0,
                help="Per-request timeout in seconds (default: 10)",
            )
            subparser.add_argument(
                "--retries",
                type=int,
                default=2,
                help="Retries after the initial request (default: 2)",
            )
        if command in {"fetch", "parse"}:
            subparser.add_argument(
                "--scope",
                choices=("pilot", "full"),
                default="pilot",
                help="Processing scope: pilot pages or every registered page (default: pilot)",
            )
        if command == "fetch":
            subparser.add_argument(
                "--asset",
                choices=("html", "audio"),
                default="html",
                help="Asset type to fetch for the pilot pages",
            )
        if command == "segment":
            subparser.add_argument(
                "--scope",
                choices=("pilot", "full"),
                default="pilot",
                help="Processing scope: pilot pages or every registered page (default: pilot)",
            )
            subparser.add_argument(
                "--analyze-only",
                action="store_true",
                help="Analyze the shared tail and candidates without writing segments",
            )
            subparser.add_argument(
                "--db",
                default=str(Path("data") / "corpus.sqlite3"),
                help="SQLite database path (default: data/corpus.sqlite3)",
            )
            subparser.add_argument(
                "--data-root",
                default="data",
                help="Data root containing raw/ and derived/ (default: data)",
            )
        if command == "qa":
            subparser.add_argument(
                "--scope",
                choices=("pilot", "full"),
                default="pilot",
                help="QA scope: pilot gate or full-corpus machine gate (default: pilot)",
            )
            subparser.add_argument(
                "--db",
                default=str(Path("data") / "corpus.sqlite3"),
                help="SQLite database path (default: data/corpus.sqlite3)",
            )
            subparser.add_argument(
                "--data-root",
                default="data",
                help="Data root containing raw/ and derived/ (default: data)",
            )
        if command == "sourcecheck":
            subparser.add_argument(
                "--db",
                default=str(Path("data") / "corpus.sqlite3"),
                help="SQLite database path (default: data/corpus.sqlite3)",
            )
            subparser.add_argument(
                "--data-root",
                default="data",
                help="Data root containing raw/ and derived/ (default: data)",
            )
            subparser.add_argument(
                "--out",
                default="derived/source_quality_report.json",
                help="Report path relative to data-root (default: derived/source_quality_report.json)",
            )
        if command == "review":
            subparser.add_argument(
                "--scope",
                choices=("pilot",),
                default="pilot",
                help="Review scope (currently only pilot)",
            )
            subparser.add_argument(
                "--db",
                default=str(Path("data") / "corpus.sqlite3"),
                help="SQLite database path (default: data/corpus.sqlite3)",
            )
            subparser.add_argument(
                "--data-root",
                default="data",
                help="Data root containing raw/ and derived/ (default: data)",
            )
            subparser.add_argument(
                "--host",
                default="127.0.0.1",
                help="Loopback bind host only (default: 127.0.0.1)",
            )
            subparser.add_argument(
                "--port",
                type=int,
                default=8765,
                help="Local review port (default: 8765)",
            )
            subparser.add_argument(
                "--apply-adjustments",
                action="store_true",
                help="Apply only current-hash reviewed boundary adjustments and exit",
            )
        if command == "nasal-review":
            subparser.add_argument(
                "--data-root",
                default="data",
                help="Data root containing corpus.sqlite3 and derived/ (default: data)",
            )
            subparser.add_argument(
                "--db",
                default=str(Path("data") / "corpus.sqlite3"),
                help="SQLite database path (default: data/corpus.sqlite3)",
            )
            subparser.add_argument(
                "--batch",
                default="01",
                help="Audit batch number to review, e.g. 01 (default: 01)",
            )
            subparser.add_argument(
                "--batch-dir",
                default=None,
                help=(
                    "Directory holding review_batch_*.csv "
                    "(default: data/derived/nasal-audit-2026-08-13)"
                ),
            )
            subparser.add_argument(
                "--batch-csv",
                default=None,
                help="Review an arbitrary batch CSV instead of --batch (path)",
            )
            subparser.add_argument(
                "--decisions-dir",
                default=None,
                help=(
                    "Directory for nasal_decisions_*.csv "
                    "(default: data/review)"
                ),
            )
            subparser.add_argument(
                "--host",
                default="127.0.0.1",
                help="Loopback bind host only (default: 127.0.0.1)",
            )
            subparser.add_argument(
                "--port",
                type=int,
                default=8767,
                help="Local nasal review port (default: 8767)",
            )
        if command == "nasal-clean":
            subparser.add_argument(
                "--data-root",
                default="data",
                help="Data root containing corpus.sqlite3 and derived/ (default: data)",
            )
            subparser.add_argument(
                "--db",
                default=str(Path("data") / "corpus.sqlite3"),
                help="SQLite database path (default: data/corpus.sqlite3)",
            )
            subparser.add_argument(
                "--apply",
                action="append",
                default=[],
                metavar="DECISIONS_CSV",
                help=(
                    "Apply one nasal decisions CSV (repeatable); "
                    "use --dry-run to preview"
                ),
            )
            subparser.add_argument(
                "--undo",
                action="append",
                default=[],
                metavar="DECISIONS_CSV",
                help="Undo every applied action recorded from one decisions CSV",
            )
            subparser.add_argument(
                "--undo-item",
                action="append",
                default=[],
                metavar="ITEM_ID",
                help="Undo one item_id (repeatable)",
            )
            subparser.add_argument(
                "--dry-run",
                action="store_true",
                help="Validate and print the plan without changing anything",
            )
        if command == "phonology":
            subparser.add_argument(
                "--data-root",
                default="data",
                help="Data root containing derived/formal_corpus.csv (default: data)",
            )
            subparser.add_argument(
                "--out",
                default="derived/phonology-v1",
                help="Output subdirectory relative to data-root (default: derived/phonology-v1)",
            )
            subparser.add_argument(
                "--seed",
                type=int,
                default=DEFAULT_SEED,
                help="Random seed for QA/query samples (default: 20260808)",
            )
        if command == "prototype":
            subparser.add_argument(
                "--db",
                default=str(Path("data") / "corpus.sqlite3"),
                help="SQLite database path (default: data/corpus.sqlite3)",
            )
            subparser.add_argument(
                "--data-root",
                default="data",
                help="Data root containing derived/ (default: data)",
            )
            subparser.add_argument(
                "--out",
                default="derived/prototype",
                help="Prototype runtime dir relative to data-root (default: derived/prototype)",
            )
            subparser.add_argument(
                "--host",
                default="127.0.0.1",
                help="Loopback bind host only (default: 127.0.0.1)",
            )
            subparser.add_argument(
                "--port",
                type=int,
                default=8766,
                help="Local prototype port (default: 8766)",
            )
        if command == "sentence-review":
            subparser.add_argument(
                "--data-root",
                default="data",
                help="Data root containing derived/sentence-practice-v1 (default: data)",
            )
            subparser.add_argument(
                "--batch",
                choices=("checklist", "alignment"),
                default="checklist",
                help=(
                    "checklist = 36 条抽样+提示项听检清单（默认）；"
                    "alignment = 82 条低置信对齐复核队列"
                ),
            )
            subparser.add_argument(
                "--csv",
                default=None,
                help="自定义批次 CSV（含 sentence_id 列，覆盖 --batch）",
            )
            subparser.add_argument(
                "--decisions-dir",
                default=None,
                help="判定 CSV 目录（默认 data/review）",
            )
            subparser.add_argument(
                "--audio-dir",
                default=None,
                help=(
                    "源朗读音频目录（复核队列生成预览音用；"
                    "默认 新大纲普通话水平测试用朗读作品音频）"
                ),
            )
            subparser.add_argument(
                "--host",
                default="127.0.0.1",
                help="Loopback bind host only (default: 127.0.0.1)",
            )
            subparser.add_argument(
                "--port",
                type=int,
                default=8768,
                help="Local sentence review port (default: 8768)",
            )
    if training_subparser is not None:
        training_commands = training_subparser.add_subparsers(
            dest="training_command", metavar="TRAINING_COMMAND", required=True
        )

        generate_parser = training_commands.add_parser(
            "generate",
            help="Generate one balanced-random training session.",
        )
        generate_parser.add_argument(
            "--profile", required=True, help="Profile id or alias"
        )
        generate_parser.add_argument(
            "--duration", type=int, default=10,
            help="Duration in minutes (5/10/15/20)",
        )
        generate_parser.add_argument(
            "--repetitions", type=int, default=1,
            help="Practice repetitions (1 or 2)",
        )
        generate_parser.add_argument(
            "--auto", dest="auto_advance", action="store_true", default=True,
            help="Auto-advance mode (default)",
        )
        generate_parser.add_argument(
            "--manual", dest="auto_advance", action="store_false",
            help="Manual mode: duration is standard training volume, not wall time",
        )
        generate_parser.add_argument("--seed", type=int, help="Random seed")
        generate_parser.add_argument(
            "--data-root", default="data",
            help="Data root containing corpus.sqlite3 and derived/ (default: data)",
        )
        generate_parser.add_argument(
            "--out", default="derived/training-generator-v1",
            help="Output directory relative to data-root",
        )
        generate_parser.add_argument(
            "--config", default=None,
            help="Generator config JSON path (default: <out>/generator_config_v1.json)",
        )
        generate_parser.add_argument(
            "--profiles-file", default=None,
            help="Training profiles JSON path (default: <out>/training_profiles_v1.json)",
        )

        stats_parser = training_commands.add_parser(
            "candidate-stats",
            help="Compute real candidate-pool statistics for all profiles.",
        )
        stats_parser.add_argument(
            "--data-root", default="data",
            help="Data root containing corpus.sqlite3 and derived/ (default: data)",
        )
        stats_parser.add_argument(
            "--out", default="derived/training-generator-v1",
            help="Output directory relative to data-root",
        )
        stats_parser.add_argument(
            "--config", default=None,
            help="Generator config JSON path (default: <out>/generator_config_v1.json)",
        )
        stats_parser.add_argument(
            "--profiles-file", default=None,
            help="Training profiles JSON path (default: <out>/training_profiles_v1.json)",
        )

        benchmark_parser = training_commands.add_parser(
            "benchmark",
            help="Run the real-data trial matrix and write sessions/report.",
        )
        benchmark_parser.add_argument(
            "--data-root", default="data",
            help="Data root containing corpus.sqlite3 and derived/ (default: data)",
        )
        benchmark_parser.add_argument(
            "--out", default="derived/training-generator-v1",
            help="Output directory relative to data-root",
        )
        benchmark_parser.add_argument(
            "--config", default=None,
            help="Generator config JSON path (default: <out>/generator_config_v1.json)",
        )
        benchmark_parser.add_argument(
            "--profiles-file", default=None,
            help="Training profiles JSON path (default: <out>/training_profiles_v1.json)",
        )
        benchmark_parser.add_argument(
            "--profiles", default=None,
            help="Comma-separated profile ids to run (default: config benchmark matrix)",
        )

        for name, help_text in (
            ("availability-v2", "Build the v2 availability matrix report."),
            ("benchmark-v2", "Run the v2 first-batch session matrix."),
            ("generate-v2", "Generate one v2 session."),
        ):
            sub = training_commands.add_parser(name, help=help_text)
            sub.add_argument(
                "--data-root", default="data",
                help="Data root containing corpus.sqlite3 and derived/",
            )
            sub.add_argument(
                "--out", default="derived/training-generator-v2",
                help="Output directory relative to data-root",
            )
            sub.add_argument(
                "--config", default=None,
                help="Generator config JSON path (default: <out>/generator_config_v2.json)",
            )
            sub.add_argument(
                "--profiles-file", default=None,
                help="v2 profiles JSON path (default: <out>/training_profiles_v2.json)",
            )
            if name == "generate-v2":
                sub.add_argument("--profile", required=True, help="v2 profile id")
                sub.add_argument(
                    "--duration", type=int, default=10,
                    help="Duration in minutes (5/10/15/20)",
                )
                sub.add_argument(
                    "--repetitions", type=int, default=1,
                    help="Practice repetitions (1 or 2)",
                )
                sub.add_argument(
                    "--auto", dest="auto_advance", action="store_true", default=True
                )
                sub.add_argument(
                    "--manual", dest="auto_advance", action="store_false"
                )
                sub.add_argument("--seed", type=int, help="Random seed")
    return parser


def _training_context(args: argparse.Namespace) -> tuple[Path, Any, list[Any]]:
    out_dir = Path(args.data_root) / args.out
    config_path = (
        Path(args.config)
        if getattr(args, "config", None)
        else out_dir / CONFIG_FILENAME
    )
    profiles_path = (
        Path(args.profiles_file)
        if getattr(args, "profiles_file", None)
        else out_dir / PROFILES_FILENAME
    )
    return out_dir, load_config(config_path), load_profiles(profiles_path)


def _resolve_profile(profiles: list[Any], key: str) -> Any:
    for profile in profiles:
        aliases = getattr(profile, "aliases", [])
        if profile.id == key or key in aliases:
            return profile
    raise ValueError(f"unknown training profile: {key}")


def _v2_context(args: argparse.Namespace) -> tuple[Path, Any, list[Any]]:
    out_dir = Path(args.data_root) / args.out
    config_path = (
        Path(args.config)
        if getattr(args, "config", None)
        else out_dir / "generator_config_v2.json"
    )
    profiles_path = (
        Path(args.profiles_file)
        if getattr(args, "profiles_file", None)
        else out_dir / "training_profiles_v2.json"
    )
    return out_dir, load_config(config_path), load_v2_profiles(profiles_path)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = getattr(args, "_command", None)
    if command is None:  # argparse's required subparser normally prevents this.
        return 2
    if command == "discover":
        try:
            summary = discover_sources(
                db_path=args.db,
                data_root=args.data_root,
                timeout=args.timeout,
                retries=args.retries,
            )
        except DiscoveryError as exc:
            print(
                json.dumps(
                    {"command": "discover", "status": "failed", "error": str(exc)},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if summary.get("status") == "succeeded" else 1

    if command == "fetch":
        if args.asset == "audio":
            try:
                fetcher = fetch_full_audio if args.scope == "full" else fetch_pilot_audio
                summary = fetcher(
                    db_path=args.db,
                    data_root=args.data_root,
                    timeout=args.timeout,
                    retries=args.retries,
                )
            except (AudioFetchError, ValueError) as exc:
                print(
                    json.dumps(
                        {
                            "command": "fetch",
                            "scope": args.scope,
                            "asset": "audio",
                            "status": "failed",
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                return 1
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
            return 0 if summary.get("status") == "succeeded" else 1

        try:
            fetcher = fetch_full_html if args.scope == "full" else fetch_pilot_html
            summary = fetcher(
                db_path=args.db,
                data_root=args.data_root,
                timeout=args.timeout,
                retries=args.retries,
            )
        except (DetailFetchError, ValueError) as exc:
            print(
                json.dumps(
                    {"command": "fetch", "scope": args.scope, "status": "failed", "error": str(exc)},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if summary.get("status") == "succeeded" else 1

    if command == "parse":
        try:
            parser = parse_full if args.scope == "full" else parse_pilot
            summary = parser(
                db_path=args.db,
                data_root=args.data_root,
                timeout=args.timeout,
                retries=args.retries,
            )
        except (DetailParseError, ValueError) as exc:
            print(
                json.dumps(
                    {"command": "parse", "scope": args.scope, "status": "failed", "error": str(exc)},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if summary.get("status") == "succeeded" else 1

    if command == "segment" and args.analyze_only:
        try:
            analyzer = analyze_full if args.scope == "full" else analyze_pilot
            summary = analyzer(db_path=args.db, data_root=args.data_root)
        except (AudioAnalysisError, ValueError) as exc:
            print(
                json.dumps(
                    {
                        "command": "segment",
                        "scope": args.scope,
                        "analyze_only": True,
                        "status": "failed",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if summary.get("status") == "succeeded" else 1

    if command == "segment":
        try:
            segmenter = segment_full if args.scope == "full" else segment_pilot
            summary = segmenter(db_path=args.db, data_root=args.data_root)
        except (SegmentationError, AudioAnalysisError, OSError, ValueError) as exc:
            print(
                json.dumps(
                    {
                        "command": "segment",
                        "scope": args.scope,
                        "analyze_only": False,
                        "status": "failed",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if summary.get("status") == "succeeded" else 1

    if command == "qa":
        try:
            runner = qa_full if args.scope == "full" else qa_pilot
            summary = runner(db_path=args.db, data_root=args.data_root)
        except (QAGateError, OSError, ValueError) as exc:
            print(
                json.dumps(
                    {
                        "command": "qa",
                        "scope": args.scope,
                        "status": "failed",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if summary.get("status") == "passed" else 1

    if command == "sourcecheck":
        try:
            summary = run_source_quality(
                db_path=args.db,
                data_root=args.data_root,
                out_path=args.out,
            )
        except (OSError, ValueError, sqlite3.Error) as exc:
            print(
                json.dumps(
                    {
                        "command": "sourcecheck",
                        "status": "failed",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0

    if command == "review":
        if args.apply_adjustments:
            try:
                summary = apply_adjustments(db_path=args.db, data_root=args.data_root)
            except (RepairError, OSError, ValueError) as exc:
                print(
                    json.dumps(
                        {
                            "command": "review",
                            "operation": "apply-adjustments",
                            "scope": "pilot",
                            "status": "failed",
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                return 1
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
            return 0
        try:
            host = validate_loopback_host(args.host)
            if args.port < 1 or args.port > 65535:
                raise ReviewAppError(f"port must be between 1 and 65535, got {args.port}")
            app = create_app(db_path=args.db, data_root=args.data_root)
            import uvicorn

            uvicorn.run(app, host=host, port=args.port)
        except (ReviewAppError, ValueError, OSError) as exc:
            print(
                json.dumps(
                    {
                        "command": "review",
                        "status": "failed",
                        "host": args.host,
                        "port": args.port,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        return 0

    if command == "prototype":
        try:
            host = validate_loopback_host(args.host)
            if args.port < 1 or args.port > 65535:
                raise PrototypeAppError(
                    f"port must be between 1 and 65535, got {args.port}"
                )
            app = create_app(
                data_root=args.data_root,
                prototype_dir=Path(args.data_root) / args.out,
                db_path=args.db,
            )
            import uvicorn

            uvicorn.run(app, host=host, port=args.port)
        except (PrototypeAppError, ValueError, OSError) as exc:
            print(
                json.dumps(
                    {
                        "command": "prototype",
                        "status": "failed",
                        "host": args.host,
                        "port": args.port,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        return 0

    if command == "nasal-review":
        try:
            host = validate_nasal_host(args.host)
            if args.port < 1 or args.port > 65535:
                raise NasalReviewError(
                    f"port must be between 1 and 65535, got {args.port}"
                )
            data_root = Path(args.data_root)
            batch_dir = (
                Path(args.batch_dir)
                if args.batch_dir
                else data_root / "derived" / "nasal-audit-2026-08-13"
            )
            if args.batch_csv:
                batch_csv = Path(args.batch_csv)
                label = batch_csv.stem
            else:
                batch_csv = batch_dir / f"review_batch_{args.batch}.csv"
                label = f"batch_{args.batch}"
            decisions_dir = (
                Path(args.decisions_dir)
                if args.decisions_dir
                else data_root / "review"
            )
            decisions_csv = decisions_dir / f"nasal_decisions_{label}.csv"
            app = create_nasal_review_app(
                data_root=data_root,
                db_path=args.db,
                batch_csv=batch_csv,
                decisions_csv=decisions_csv,
                batch_label=label,
            )
            import uvicorn

            uvicorn.run(app, host=host, port=args.port)
        except (NasalReviewError, FileNotFoundError, ValueError, OSError) as exc:
            print(
                json.dumps(
                    {
                        "command": "nasal-review",
                        "status": "failed",
                        "host": args.host,
                        "port": args.port,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        return 0

    if command == "nasal-clean":
        try:
            if args.apply:
                summary = apply_nasal_decisions(
                    db_path=args.db,
                    data_root=args.data_root,
                    decisions_csvs=args.apply,
                    dry_run=args.dry_run,
                )
            elif args.undo or args.undo_item:
                summary = undo_nasal_clean(
                    db_path=args.db,
                    data_root=args.data_root,
                    decisions_csvs=args.undo,
                    item_ids=args.undo_item,
                    dry_run=args.dry_run,
                )
            else:
                raise NasalCleanError(
                    "nasal-clean requires --apply or --undo/--undo-item"
                )
        except (NasalCleanError, OSError, ValueError, sqlite3.Error) as exc:
            print(
                json.dumps(
                    {
                        "command": "nasal-clean",
                        "status": "failed",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0

    if command == "phonology":
        try:
            summary = run_pipeline(
                data_root=args.data_root,
                out_subdir=args.out,
                seed=args.seed,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(
                json.dumps(
                    {
                        "command": "phonology",
                        "status": "failed",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if summary.get("status") == "succeeded" else 1

    if command == "training":
        try:
            training_command = getattr(args, "training_command", None)
            v2_command = training_command in {
                "availability-v2",
                "benchmark-v2",
                "generate-v2",
            }
            if v2_command:
                out_dir, config, profiles = _v2_context(args)
                if training_command == "availability-v2":
                    summary = run_availability_v2(
                        Path(args.data_root), out_dir, profiles, config
                    )
                elif training_command == "benchmark-v2":
                    summary = run_benchmark_v2(
                        Path(args.data_root), out_dir, profiles, config
                    )
                else:
                    profile = _resolve_profile(profiles, args.profile)
                    seed = args.seed
                    items = load_items(
                        Path(args.data_root) / "derived/phonology-v1/phonology.sqlite3",
                        Path(args.data_root) / "corpus.sqlite3",
                    )
                    universe = _universe_from_items(items)
                    availability = compute_availability(
                        items, [profile], universe
                    )["profiles"][0]
                    history = HistoryStore.load(
                        profile.id,
                        out_dir / "history" / f"{profile.id}.json",
                        window_days=config.history_window_days,
                        window_sessions=config.history_window_sessions,
                    )
                    session = generate_session_v2(
                        profile,
                        config,
                        items,
                        availability,
                        duration_minutes=args.duration,
                        practice_repetitions=args.repetitions,
                        auto_advance=args.auto_advance,
                        seed=seed,
                        history=history,
                    )
                    history.add_session(
                        session["session_id"],
                        [e["item_id"] for e in session["items"]],
                    )
                    history.save()
                    path = (
                        out_dir
                        / "sessions"
                        / profile.id
                        / f"{session['session_id']}.json"
                    )
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with open(path, "w", encoding="utf-8") as fh:
                        json.dump(
                            session, fh, ensure_ascii=False, indent=2, sort_keys=True
                        )
                        fh.write("\n")
                    print(
                        json.dumps(
                            {
                                "command": "training",
                                "operation": "generate-v2",
                                "status": "succeeded",
                                "profile_id": session["profile_id"],
                                "session_id": session["session_id"],
                                "item_count": session["item_count"],
                                "estimated_duration_sec": session["estimated_duration_sec"],
                                "duration_rel_error": session["duration_rel_error"],
                                "seed": session["seed"],
                                "path": str(path),
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    )
                    return 0
            else:
                out_dir, config, profiles = _training_context(args)
                if training_command == "generate":
                    profile = _resolve_profile(profiles, args.profile)
                    seed = args.seed if args.seed is not None else DEFAULT_SEED
                    session = generate_session(
                        profile,
                        config,
                        load_items(
                            Path(args.data_root) / "derived/phonology-v1/phonology.sqlite3",
                            Path(args.data_root) / "corpus.sqlite3",
                        ),
                        duration_minutes=args.duration,
                        practice_repetitions=args.repetitions,
                        auto_advance=args.auto_advance,
                        seed=seed,
                    )
                    path = write_session_file(session, out_dir)
                    print(
                        json.dumps(
                            {
                                "command": "training",
                                "operation": "generate",
                                "status": "succeeded",
                                "profile_id": session["profile_id"],
                                "session_id": session["session_id"],
                                "item_count": session["item_count"],
                                "estimated_duration_sec": session["estimated_duration_sec"],
                                "duration_rel_error": session["duration_rel_error"],
                                "seed": session["seed"],
                                "path": str(path),
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    )
                    return 0
                elif training_command == "candidate-stats":
                    summary = run_candidate_stats(
                        Path(args.data_root), out_dir, profiles, config
                    )
                elif training_command == "benchmark":
                    main_ids = None
                    extra_ids = None
                    if getattr(args, "profiles", None):
                        main_ids = [
                            p.strip()
                            for p in args.profiles.split(",")
                            if p.strip()
                        ]
                        extra_ids = []
                    summary = run_benchmark(
                        Path(args.data_root),
                        out_dir,
                        profiles,
                        config,
                        main_profile_ids=main_ids,
                        extra_profile_ids=extra_ids,
                    )
                else:
                    raise ValueError(
                        f"unknown training command: {training_command}"
                    )
        except (OSError, ValueError, sqlite3.Error) as exc:
            print(
                json.dumps(
                    {
                        "command": "training",
                        "status": "failed",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if summary.get("status") in {"succeeded", "partial"} else 1

    if command == "sentence":
        try:
            return dispatch_sentence(args)
        except (SentenceReadingError, OSError, ValueError) as exc:
            print(
                json.dumps(
                    {"command": "sentence", "status": "failed", "error": str(exc)},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1

    if command == "sentence-review":
        try:
            host = validate_sentence_host(args.host)
            if args.port < 1 or args.port > 65535:
                raise SentenceReviewError(
                    f"port must be between 1 and 65535, got {args.port}"
                )
            data_root = Path(args.data_root)
            sp_root = data_root / "derived" / "sentence-practice-v1"
            if args.csv:
                batch_csv = Path(args.csv)
                label = batch_csv.stem
            elif args.batch == "alignment":
                batch_csv = sp_root / "alignment" / "alignment_review.csv"
                label = "alignment"
            else:
                batch_csv = sp_root / "qa_human_checklist.csv"
                label = "checklist"
            decisions_dir = (
                Path(args.decisions_dir)
                if args.decisions_dir
                else data_root / "review"
            )
            decisions_csv = decisions_dir / f"sentence_decisions_{label}.csv"
            app = create_sentence_review_app(
                data_root=data_root,
                batch_csv=batch_csv,
                decisions_csv=decisions_csv,
                batch_label=label,
                audio_dir=args.audio_dir,
            )
            import uvicorn

            uvicorn.run(app, host=host, port=args.port)
        except (SentenceReviewError, FileNotFoundError, ValueError, OSError) as exc:
            print(
                json.dumps(
                    {
                        "command": "sentence-review",
                        "status": "failed",
                        "host": args.host,
                        "port": args.port,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        return 0

    print(f"{command}: not implemented")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
