"""Tests for the local Mandarin practice prototype web app."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import wave
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from pth_corpus.db import connect_db, init_db
from pth_corpus.prototype_app import PROFILE_MENU, create_app
from pth_corpus.training.candidates import _make_item as make_corpus_item
from pth_corpus.training.models import GeneratorConfig, Item, SyllableInfo
from pth_corpus.training.v2.engine import candidate_matches, classify_item
from pth_corpus.training.v2.schema import V2Profile


def _build_item(
    item_id: str,
    initials: list[str],
    *,
    finals: list[str] | None = None,
    word: str | None = None,
    has_erhua: int = 0,
    contains_yi: int = 0,
    contains_bu: int = 0,
) -> Item:
    syllables = [
        SyllableInfo(
            index=i + 1,
            initial=initial,
            final_canonical=(finals[i] if finals and i < len(finals) else "a"),
            final_structure="SIMPLE",
            nasal_type="NONE",
            compound_resonance="NA",
            tone=1,
        )
        for i, initial in enumerate(initials)
    ]
    finals_list = finals if finals is not None else ["a"] * len(initials)
    row = {
        "item_id": item_id,
        "table_kind": "table1",
        "word_raw": word or item_id,
        "pinyin_nfc": "-".join(initials),
        "global_seq": int(item_id.rsplit("-", 1)[1]),
        "syllable_count": len(initials),
        "length_bucket": str(len(initials)),
        "initial_sequence": "-".join(initials),
        "final_sequence": (
            "a" * len(initials) if finals is None else "-".join(finals_list)
        ),
        "tone_pattern_lexical": "-".join("1" for _ in initials),
        "has_neutral_tone": 0,
        "has_erhua": has_erhua,
        "has_adjacent_33": 0,
        "has_flat_initial": 0,
        "has_retroflex_initial": 0,
        "has_n": 0,
        "has_l": 0,
        "has_jqx": 0,
        "has_front_nasal": 0,
        "has_back_nasal": 0,
        "has_compound_final": 0,
        "has_third_tone": 0,
        "contains_yi": contains_yi,
        "contains_bu": contains_bu,
        "neutral_positions": None,
        "erhua_position": None,
    }
    segment = {
        "clip_path": f"derived/clips-v2/table1/{item_id}.wav",
        "start_ms": 0,
        "end_ms": 1000,
    }
    return make_corpus_item(row, syllables, segment)


def _bilabial_profile() -> V2Profile:
    return V2Profile.from_dict(
        {
            "id": "bilabial_focus",
            "name": "双唇音单项",
            "dimension": "initial",
            "mode": "single_focus",
            "target_sets": {"T": ["b", "p", "m"]},
            "buckets": [
                {
                    "id": "core",
                    "label": "核心 T×T",
                    "target_ratio": 0.8,
                    "role": "core",
                    "rule": {"op": "all_in", "sets": ["T"]},
                    "pair_specs": [{"left": "T", "right": "T"}],
                },
                {
                    "id": "supplement",
                    "label": "补充 T↔O",
                    "target_ratio": 0.2,
                    "role": "supplement",
                    "rule": {
                        "op": "all",
                        "rules": [
                            {"op": "any_in", "sets": ["T"]},
                            {"op": "not", "rule": {"op": "all_in", "sets": ["T"]}},
                        ],
                    },
                    "pair_specs": [
                        {"left": "T", "right": "O"},
                        {"left": "O", "right": "T"},
                    ],
                },
            ],
            "allow_other": True,
            "scarcity": {"repeat_allowed": True, "max_repeat": 2, "min_gap": 20},
        }
    )


def _make_config() -> GeneratorConfig:
    return GeneratorConfig(
        version="test",
        top_k=20,
        max_attempts=8,
        random_jitter=0.05,
        extra_follow_sec=0.8,
        min_follow_sec=1.8,
        transition_sec=0.3,
        allowed_duration_minutes=(5, 10),
        allowed_practice_repetitions=(1, 2),
        benchmark_seeds_5m=(1,),
        benchmark_seeds_10m=(2,),
        benchmark_seeds_20m=(3,),
    )


def _seed_corpus_db(db_path: Path, items: list[Item]) -> None:
    init_db(db_path)
    with connect_db(db_path) as connection:
        connection.execute(
            """
            INSERT INTO source_pages
                (source_key, table_kind, page_no, url, expected_items,
                 fetch_status)
            VALUES ('t1-p001', 'table1', 1, 'http://fixture/t1', 100, 'fetched')
            """
        )
        page_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        connection.executemany(
            """
            INSERT INTO entries
                (item_id, source_page_id, table_kind, page_position,
                 global_seq, word_raw, pinyin_raw, pinyin_nfc)
            VALUES (?, ?, 'table1', ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.item_id,
                    page_id,
                    int(item.item_id.rsplit("-", 1)[1]),
                    int(item.item_id.rsplit("-", 1)[1]),
                    item.word_raw,
                    item.pinyin_nfc,
                    item.pinyin_nfc,
                )
                for item in items
            ],
        )
        connection.executemany(
            """
            INSERT INTO segments
                (item_id, clip_path, clip_sha256, algorithm_version,
                 confidence, start_ms, end_ms, start_ms_raw, end_ms_raw)
            VALUES (?, ?, ?, 'test-v2', ?, 0, 1000, 0, 1000)
            """,
            [
                (
                    item.item_id,
                    item.clip_path,
                    hashlib.sha256(item.item_id.encode()).hexdigest(),
                    0.9,
                )
                for item in items
            ],
        )


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 16_000
    samples = (
        np.sin(2 * np.pi * 440 * np.arange(sample_rate) / sample_rate) * 0.25
    )
    pcm = np.rint(samples * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def _make_fixture(
    tmp_path: Path,
    *,
    extra_profiles: tuple[V2Profile, ...] = (),
    items: list[Item] | None = None,
) -> tuple[Path, TestClient, list[Item]]:
    data_root = tmp_path / "data"
    data_root.mkdir()
    db_path = data_root / "corpus.sqlite3"
    if items is None:
        items = [_build_item(f"t1-{i:05d}", ["b", "b"]) for i in range(1, 121)]
        items += [_build_item(f"t1-{i:05d}", ["b", "k"]) for i in range(121, 151)]
    _seed_corpus_db(db_path, items)
    prototype_dir = data_root / "derived" / "prototype"
    app = create_app(
        data_root,
        generator_dir=data_root / "derived" / "training-generator-v2",
        prototype_dir=prototype_dir,
        db_path=db_path,
        items=items,
        profiles=[_bilabial_profile(), *extra_profiles],
        config=_make_config(),
    )
    return data_root, TestClient(app), items


def _nasal_profile(profile_id: str) -> V2Profile:
    return V2Profile.from_dict(
        {
            "id": profile_id,
            "name": profile_id,
            "dimension": "final",
            "mode": "single_focus",
            "target_sets": {},
            "buckets": [],
        }
    )


def test_always_rule_matches_any_values():
    profile = _bilabial_profile()
    core = _build_item("t1-00001", ["b", "b"])
    assert candidate_matches(core, profile)
    assert classify_item(core, profile) == "core"


def test_index_and_health(tmp_path):
    data_root, client, _ = _make_fixture(tmp_path)
    with client:
        index = client.get("/")
        assert index.status_code == 200
        assert "前后鼻音专项训练" in index.text
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["profile_count"] == 1


def test_focus_home_exposes_three_nasal_entries(tmp_path):
    _, client, _ = _make_fixture(
        tmp_path,
        extra_profiles=(
            _nasal_profile("front_nasal_all"),
            _nasal_profile("back_nasal_all"),
            _nasal_profile("front_back_nasal_contrast"),
        ),
    )
    with client:
        home = client.get("/api/home")
        assert home.status_code == 200
        payload = home.json()
        entries = {entry["id"]: entry for entry in payload["entries"]}
        assert list(entries) == ["front_nasal", "back_nasal", "contrast"]
        assert entries["front_nasal"]["profile_id"] == "front_nasal_all"
        assert entries["back_nasal"]["profile_id"] == "back_nasal_all"
        assert entries["contrast"]["profile_id"] == "front_back_nasal_contrast"
        assert payload["durations"] == [5, 10]
        assert payload["default_duration_minutes"] == 10
        # Contrast entry only offers the 5 natural pairs: the unpaired
        # finals (uen/üan/ün, ueng/iong/ong) are trained solo via the
        # front/back entries, never as forced pairs.
        contrast_groups = entries["contrast"]["filter_groups"]
        assert [group["id"] for group in contrast_groups] == [
            "an_ang",
            "en_eng",
            "in_ing",
            "ian_iang",
            "uan_uang",
        ]
        contrast_finals = {
            final
            for group in contrast_groups
            for final in group["finals"]
        }
        assert contrast_finals == {
            "an", "ang", "en", "eng", "in", "ing",
            "ian", "iang", "uan", "uang",
        }


def test_calibration_groups_resolve_real_items(tmp_path):
    items = [
        _build_item("t1-00001", ["ZERO"], finals=["an"], word="安"),
        _build_item("t1-00002", ["ZERO"], finals=["ang"], word="昂"),
        _build_item("t1-00003", ["ZERO"], finals=["en"], word="恩"),
        _build_item("t1-00004", ["zh"], finals=["eng"], word="争"),
        _build_item("t1-00005", ["ZERO"], finals=["in"], word="因"),
        _build_item("t1-00006", ["ZERO"], finals=["ing"], word="应"),
    ]
    _, client, _ = _make_fixture(tmp_path, items=items)
    with client:
        payload = client.get("/api/calibration")
        assert payload.status_code == 200
        groups = payload.json()["groups"]
        # 2026-08-27 起标准音只保留三组（示范视频覆盖 an/ang、en/eng、in/ing）
        assert [group["id"] for group in groups] == ["an_ang", "en_eng", "in_ing"]
        an_ang = groups[0]
        assert an_ang["a"]["word"] == "安" and an_ang["a"]["final"] == "an"
        assert an_ang["b"]["word"] == "昂" and an_ang["b"]["final"] == "ang"
        en_eng = groups[1]
        assert en_eng["a"]["word"] == "恩"
        assert en_eng["b"]["word"] == "争"


def test_achievement_endpoint_and_settle(tmp_path):
    _, client, _ = _make_fixture(tmp_path)
    with client:
        achievement = client.get("/api/achievement")
        assert achievement.status_code == 200
        payload = achievement.json()
        cfg = payload["achievement_config"]
        assert cfg["tiers"] == {
            "word": {"5": 600.0, "10": 1200.0},
            "sentence": {"10": 600.0, "15": 900.0},
            "discrim": {"50": 300.0, "100": 600.0, "150": 900.0},
        }
        assert cfg["trio_bonus"] == 100
        assert cfg["review_reward"] == 100
        ids = [artwork["artwork_id"] for artwork in payload["artworks"]]
        assert ids == [
            "mic",
            "cat1",
            "cat2",
            "cat3",
            "cat4",
            "cat5",
            "cat6",
        ]
        full = client.post(
            "/api/achievement/settle",
            json={"planned_duration_minutes": 10, "completion_ratio": 1.0},
        )
        assert full.status_code == 200
        assert full.json()["total_beads"] == 1200
        half = client.post(
            "/api/achievement/settle",
            json={"planned_duration_minutes": 10, "completion_ratio": 0.5},
        )
        assert half.json()["total_beads"] == 600
        unknown = client.post(
            "/api/achievement/settle",
            json={"planned_duration_minutes": 15, "completion_ratio": 1.0},
        )
        assert unknown.status_code == 400


def test_settle_streak_is_display_only(tmp_path):
    _, client, _ = _make_fixture(tmp_path)
    with client:
        first = client.post(
            "/api/achievement/settle",
            json={
                "planned_duration_minutes": 10,
                "completion_ratio": 1.0,
                "streak_days": 30,
            },
        )
        assert first.status_code == 200
        payload = first.json()
        assert payload["streak_days"] == 30
        assert payload["streak_bonus"] == 0
        assert payload["total_beads"] == 1200
        # Defaults keep the old behaviour (no streak bonus).
        plain = client.post(
            "/api/achievement/settle",
            json={"planned_duration_minutes": 5, "completion_ratio": 1.0},
        )
        assert plain.json()["streak_bonus"] == 0
        assert plain.json()["total_beads"] == 600


def test_achievement_exposes_new_baseline_config(tmp_path):
    _, client, _ = _make_fixture(tmp_path)
    with client:
        achievement = client.get("/api/achievement")
        payload = achievement.json()
        cfg = payload["achievement_config"]
        assert cfg["version"] == "v2"
        assert cfg["minimum_completion_ratio"] == 0.2
        # 旧规则字段不复存在
        assert "streak_bonus" not in cfg
        assert "daily_bead_cap" not in cfg
        assert "duration_rewards" not in cfg


def test_profiles_menu_filters_unknown_profiles(tmp_path):
    _, client, _ = _make_fixture(tmp_path)
    with client:
        menu = client.get("/api/profiles")
        assert menu.status_code == 200
        payload = menu.json()
        categories = {c["id"]: c for c in payload["categories"]}
        assert categories["initial"]["items"][0]["profile_id"] == "bilabial_focus"
        assert payload["durations"] == [5, 10]
        assert payload["default_duration_minutes"] == 10
        # Unknown profiles are filtered out of the menu.
        assert "general" not in categories


def test_menu_structure_and_labels():
    categories = {c["id"]: c for c in PROFILE_MENU}
    initial_labels = [item["label"] for item in categories["initial"]["items"]]
    assert "双唇音（b p m）" in initial_labels
    assert "平舌音（z c s）" in initial_labels
    assert "平翘舌音对比" in initial_labels
    assert "舌尖中音（d t）" in initial_labels
    assert not any("不含 r" in label for label in initial_labels)

    final_labels = [item["label"] for item in categories["final"]["items"]]
    assert final_labels[0] == "单韵母（a o e i u ü）"
    assert "前响复韵母（ai ei ao ou）" in final_labels
    assert "复韵母综合" in final_labels
    assert "前后鼻音对比 · 进阶（an/ian/uan · ang/iang/uang）" in final_labels

    assert [item["profile_id"] for item in categories["tone"]["items"]] == [
        "tone_1",
        "tone_2",
        "tone_3",
        "tone_4",
        "tone_all",
    ]
    assert [item["label"] for item in categories["tone"]["items"]] == [
        "阴平（ˉ）",
        "阳平（ˊ）",
        "上声（ˇ）",
        "去声（ˋ）",
        "四声综合",
    ]
    assert [item["profile_id"] for item in categories["sandhi"]["items"]] == [
        "neutral_focus",
        "erhua_focus",
        "yi_bu_focus",
        "tone_33",
    ]


def test_flag_rule_candidate_matching():
    erhua = V2Profile.from_dict(
        {
            "id": "erhua_focus",
            "name": "儿化专项",
            "dimension": "final",
            "mode": "special_mix",
            "target_sets": {"T": []},
            "candidate_rule": {"op": "always"},
            "flag_rule": {
                "op": "any",
                "rules": [{"field": "has_erhua", "eq": 1}],
            },
            "buckets": [
                {
                    "id": "all",
                    "label": "儿化词",
                    "target_ratio": 1.0,
                    "role": "all",
                    "rule": {"op": "always"},
                    "pair_specs": [],
                }
            ],
            "allow_other": True,
            "scarcity": {"repeat_allowed": True, "max_repeat": 4, "min_gap": 10},
        }
    )
    yi_bu = V2Profile.from_dict(
        {
            "id": "yi_bu_focus",
            "name": "一/不变调",
            "dimension": "initial",
            "mode": "special_mix",
            "target_sets": {"Y": ["y"], "B": ["b"]},
            "candidate_rule": {"op": "always"},
            "flag_rule": {
                "op": "any",
                "rules": [
                    {"field": "contains_yi", "eq": 1},
                    {"field": "contains_bu", "eq": 1},
                ],
            },
            "buckets": [
                {
                    "id": "all",
                    "label": "一/不词语",
                    "target_ratio": 1.0,
                    "role": "all",
                    "rule": {"op": "always"},
                    "pair_specs": [],
                }
            ],
            "allow_other": True,
            "scarcity": {"repeat_allowed": True, "max_repeat": 2, "min_gap": 20},
        }
    )
    erhua_item = _build_item("t1-00001", ["b", "b"], has_erhua=1)
    plain_item = _build_item("t1-00002", ["b", "b"])
    bu_item = _build_item("t1-00003", ["b", "u"], contains_bu=1)
    assert candidate_matches(erhua_item, erhua)
    assert not candidate_matches(plain_item, erhua)
    assert candidate_matches(bu_item, yi_bu)
    assert not candidate_matches(plain_item, yi_bu)


def test_player_config_endpoint(tmp_path):
    _, client, _ = _make_fixture(tmp_path)
    with client:
        config = client.get("/api/config")
        assert config.status_code == 200
        assert config.json()["extra_follow_sec"] == 0.8
        assert config.json()["min_follow_sec"] == 1.8
        assert config.json()["transition_sec"] == 0.3


def test_create_session_generates_real_items_and_history(tmp_path):
    data_root, client, _ = _make_fixture(tmp_path)
    with client:
        response = client.post(
            "/api/sessions",
            json={"profile_id": "bilabial_focus", "duration_minutes": 5},
        )
        assert response.status_code == 201
        session = response.json()
        assert session["profile_id"] == "bilabial_focus"
        assert session["item_count"] > 50
        assert len(session["items"]) == session["item_count"]
        assert abs(session["estimated_duration_sec"] - 300) < 30
        first = session["items"][0]
        assert first["word"] and first["pinyin"] and first["clip_path"]
        history_path = (
            data_root
            / "derived/prototype/history/bilabial_focus.json"
        )
        assert history_path.exists()
        history = json.loads(history_path.read_text(encoding="utf-8"))
        assert history["session_seq"] == 1
        assert len(history["entries"]) == session["item_count"]


def test_create_session_validates_inputs(tmp_path):
    _, client, _ = _make_fixture(tmp_path)
    with client:
        missing = client.post(
            "/api/sessions",
            json={"profile_id": "nope", "duration_minutes": 5},
        )
        assert missing.status_code == 404
        bad_duration = client.post(
            "/api/sessions",
            json={"profile_id": "bilabial_focus", "duration_minutes": 7},
        )
        assert bad_duration.status_code == 400


def _front_nasal_profile() -> V2Profile:
    return V2Profile.from_dict(
        {
            "id": "front_nasal_all",
            "name": "前鼻音综合",
            "dimension": "final",
            "mode": "single_focus",
            "target_sets": {"T": ["an", "en"]},
            "buckets": [
                {
                    "id": "core",
                    "label": "核心 T×T",
                    "target_ratio": 0.8,
                    "role": "core",
                    "rule": {"op": "all_in", "sets": ["T"]},
                    "pair_specs": [{"left": "T", "right": "T"}],
                },
                {
                    "id": "supplement",
                    "label": "补充 T↔O",
                    "target_ratio": 0.2,
                    "role": "supplement",
                    "rule": {
                        "op": "all",
                        "rules": [
                            {"op": "any_in", "sets": ["T"]},
                            {"op": "not", "rule": {"op": "all_in", "sets": ["T"]}},
                        ],
                    },
                    "pair_specs": [
                        {"left": "T", "right": "O"},
                        {"left": "O", "right": "T"},
                    ],
                },
            ],
            "allow_other": True,
            "scarcity": {"repeat_allowed": True, "max_repeat": 2, "min_gap": 5},
        }
    )


def test_create_session_honours_include_finals(tmp_path):
    items = [
        _build_item(f"t1-{i:05d}", ["b", "b"], finals=["an", "an"])
        for i in range(1, 61)
    ]
    items += [
        _build_item(f"t1-{i:05d}", ["b", "b"], finals=["en", "en"])
        for i in range(61, 121)
    ]
    items += [
        _build_item(f"t1-{i:05d}", ["b", "k"], finals=["an", "a"])
        for i in range(121, 151)
    ]
    _, client, _ = _make_fixture(
        tmp_path,
        extra_profiles=(_front_nasal_profile(),),
        items=items,
    )
    with client:
        response = client.post(
            "/api/sessions",
            json={
                "profile_id": "front_nasal_all",
                "duration_minutes": 5,
                "include_finals": ["an"],
            },
        )
        assert response.status_code == 201
        session = response.json()
        assert session["include_finals"] == ["an"]
        assert session["item_count"] > 0
        for entry in session["items"]:
            item = next(i for i in items if i.item_id == entry["item_id"])
            carried = {s.final_canonical for s in item.syllables}
            assert "en" not in carried
            assert "an" in carried
        # Unknown finals are rejected.
        bad = client.post(
            "/api/sessions",
            json={
                "profile_id": "front_nasal_all",
                "duration_minutes": 5,
                "include_finals": ["ang"],
            },
        )
        assert bad.status_code == 400
        # Empty list is rejected at request validation.
        empty = client.post(
            "/api/sessions",
            json={
                "profile_id": "front_nasal_all",
                "duration_minutes": 5,
                "include_finals": [],
            },
        )
        assert empty.status_code == 422


def test_clip_media_serves_wav_and_rejects_unknown(tmp_path):
    data_root, client, items = _make_fixture(tmp_path)
    item = items[0]
    _write_wav(data_root / item.clip_path)
    with client:
        clip = client.get(f"/api/clips/{item.item_id}")
        assert clip.status_code == 200
        assert clip.headers["content-type"].startswith("audio/wav")
        assert len(clip.content) > 1000
        missing = client.get("/api/clips/t1-99999")
        assert missing.status_code == 404
        malformed = client.get("/api/clips/../../etc/passwd")
        assert malformed.status_code == 404


def test_events_are_appended_locally(tmp_path):
    data_root, client, _ = _make_fixture(tmp_path)
    with client:
        response = client.post(
            "/api/events",
            json={
                "session_id": "bilabial_focus-5m-seed1-rep1",
                "profile_id": "bilabial_focus",
                "duration_minutes": 5,
                "start_time": "2026-08-10T10:00:00+08:00",
                "end_time": "2026-08-10T10:05:00+08:00",
                "completed_item_count": 93,
                "exit_early": False,
                "replay_count": 2,
                "pause_count": 1,
                "seed": 1,
                "item_count": 93,
            },
        )
        assert response.status_code == 201
        log_path = data_root / "derived/prototype/logs/events.jsonl"
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["profile_id"] == "bilabial_focus"
        assert payload["completed_item_count"] == 93
        assert payload["recorded_at"]


def test_events_accept_extended_fields(tmp_path):
    data_root, client, _ = _make_fixture(tmp_path)
    with client:
        response = client.post(
            "/api/events",
            json={
                "session_id": "bilabial_focus-10m-seed9-rep1",
                "profile_id": "bilabial_focus",
                "duration_minutes": 10,
                "start_time": "2026-08-13T10:00:00+08:00",
                "end_time": "2026-08-13T10:10:00+08:00",
                "completed_item_count": 180,
                "exit_early": False,
                "replay_count": 3,
                "pause_count": 2,
                "seed": 9,
                "item_count": 180,
                "actual_duration_sec": 598.4,
                "completion_ratio": 1.0,
                "beads_awarded": 14,
                "streak_days": 4,
                "streak_bonus_awarded": 3,
            },
        )
        assert response.status_code == 201
        log_path = data_root / "derived/prototype/logs/events.jsonl"
        payload = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert payload["actual_duration_sec"] == 598.4
        assert payload["completion_ratio"] == 1.0
        assert payload["beads_awarded"] == 14
        assert payload["streak_days"] == 4
        assert payload["streak_bonus_awarded"] == 3


def test_events_streak_fields_are_optional(tmp_path):
    data_root, client, _ = _make_fixture(tmp_path)
    with client:
        response = client.post(
            "/api/events",
            json={
                "session_id": "bilabial_focus-10m-seed9-rep1",
                "profile_id": "bilabial_focus",
                "duration_minutes": 10,
                "start_time": "2026-08-13T10:00:00+08:00",
                "end_time": "2026-08-13T10:10:00+08:00",
                "completed_item_count": 180,
                "exit_early": True,
            },
        )
        assert response.status_code == 201
        log_path = data_root / "derived/prototype/logs/events.jsonl"
        payload = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert "streak_days" in payload
        assert payload["streak_days"] is None
