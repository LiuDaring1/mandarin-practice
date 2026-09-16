import pytest

import pth_corpus.cli as cli
from pth_corpus.cli import main
from pth_corpus.training.models import GeneratorConfig, TrainingProfile


def test_cli_help_lists_all_stages(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    for command in ("discover", "fetch", "parse", "segment", "qa", "review", "training"):
        assert command in output


def test_fetch_cli_prints_machine_readable_summary(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "fetch_pilot_html",
        lambda **kwargs: {"command": "fetch", "status": "succeeded", "fetched": 2},
    )
    assert main(["fetch", "--scope", "pilot", "--asset", "html"]) == 0
    assert '"status": "succeeded"' in capsys.readouterr().out


def test_discover_cli_prints_machine_readable_summary(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        cli,
        "discover_sources",
        lambda **kwargs: {
            "command": "discover",
            "status": "succeeded",
            "source_pages": 171,
            "db": kwargs["db_path"],
        },
    )
    assert main(
        [
            "discover",
            "--db",
            str(tmp_path / "corpus.sqlite3"),
            "--data-root",
            str(tmp_path / "data"),
            "--timeout",
            "3",
            "--retries",
            "1",
        ]
    ) == 0
    assert '"status": "succeeded"' in capsys.readouterr().out


def test_segment_analyze_only_cli_prints_summary(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        cli,
        "analyze_pilot",
        lambda **kwargs: {
            "command": "segment",
            "scope": "pilot",
            "analyze_only": True,
            "status": "succeeded",
            "candidate_count": 4,
        },
    )
    assert main(
        [
            "segment",
            "--scope",
            "pilot",
            "--analyze-only",
            "--db",
            str(tmp_path / "corpus.sqlite3"),
            "--data-root",
            str(tmp_path / "data"),
        ]
    ) == 0
    assert '"candidate_count": 4' in capsys.readouterr().out


def test_qa_cli_returns_gate_status_and_nonzero_when_blocked(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        cli,
        "qa_pilot",
        lambda **kwargs: {
            "command": "qa",
            "scope": "pilot",
            "status": "blocked_on_human_review",
            "review_counts": {"approved": 0},
        },
    )
    assert main(
        [
            "qa",
            "--scope",
            "pilot",
            "--db",
            str(tmp_path / "corpus.sqlite3"),
            "--data-root",
            str(tmp_path / "data"),
        ]
    ) == 1
    assert '"status": "blocked_on_human_review"' in capsys.readouterr().out


def test_review_apply_adjustments_does_not_start_server(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        cli,
        "apply_adjustments",
        lambda **kwargs: {
            "command": "review",
            "operation": "apply-adjustments",
            "status": "succeeded",
            "affected": 0,
        },
    )
    monkeypatch.setattr(cli, "create_app", lambda **kwargs: pytest.fail("server started"))
    assert main(
        [
            "review",
            "--apply-adjustments",
            "--db",
            str(tmp_path / "corpus.sqlite3"),
            "--data-root",
            str(tmp_path / "data"),
        ]
    ) == 0
    assert '"affected": 0' in capsys.readouterr().out


def test_training_generate_prints_summary(monkeypatch, capsys, tmp_path):
    config = GeneratorConfig(version="test", allowed_duration_minutes=(5,))
    profile = TrainingProfile.from_dict(
        {
            "id": "test_profile",
            "name": "Test",
            "aliases": [],
            "candidate_rule": {"field": "item_id", "is_not_null": True},
            "balance_dimensions": [],
            "position_dimension": None,
        }
    )

    def fake_context(args):
        return tmp_path, config, [profile]

    monkeypatch.setattr(cli, "_training_context", fake_context)
    monkeypatch.setattr(cli, "load_items", lambda *args: [])
    monkeypatch.setattr(
        cli,
        "generate_session",
        lambda *args, **kwargs: {
            "profile_id": "test_profile",
            "session_id": "test_profile-5m-seed1-rep1",
            "item_count": 3,
            "estimated_duration_sec": 300.2,
            "duration_rel_error": 0.0007,
            "seed": 1,
            "items": [],
        },
    )
    monkeypatch.setattr(
        cli, "write_session_file", lambda session, out_dir: tmp_path / "session.json"
    )
    assert (
        main(
            [
                "training",
                "generate",
                "--profile",
                "test_profile",
                "--duration",
                "5",
                "--seed",
                "1",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert '"item_count": 3' in output
    assert '"session_id": "test_profile-5m-seed1-rep1"' in output


def test_training_candidate_stats_prints_summary(monkeypatch, capsys, tmp_path):
    config = GeneratorConfig(version="test")
    profile = TrainingProfile.from_dict(
        {
            "id": "test_profile",
            "name": "Test",
            "aliases": [],
            "candidate_rule": {"field": "item_id", "is_not_null": True},
            "balance_dimensions": [],
            "position_dimension": None,
        }
    )
    monkeypatch.setattr(
        cli, "_training_context", lambda args: (tmp_path, config, [profile])
    )
    monkeypatch.setattr(
        cli,
        "run_candidate_stats",
        lambda *args, **kwargs: {
            "command": "candidate-stats",
            "status": "succeeded",
            "available_item_count": 16149,
            "profile_count": 1,
            "report": str(tmp_path / "report.md"),
            "stats": str(tmp_path / "stats.json"),
        },
    )
    assert main(["training", "candidate-stats"]) == 0
    assert '"available_item_count": 16149' in capsys.readouterr().out
