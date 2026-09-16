"""Tests for the front/back-nasal discrimination practice (听辨练习)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from pth_corpus.db import init_db
from pth_corpus.discrimination import (
    TARGET_FINALS,
    build_discrim_pool,
    build_quiz,
    consecutive_penalty,
    judge_answer,
    load_discrim_syllables,
    summarize_round,
)
from pth_corpus.prototype_app import create_app
from pth_corpus.training.candidates import _make_item as make_corpus_item
from pth_corpus.training.models import GeneratorConfig, Item, SyllableInfo
from pth_corpus.training.v2.schema import V2Profile


# --------------------------------------------------------------------------
# 单元级：直接构造 Item 对象测池子 / 出题 / 判定
# --------------------------------------------------------------------------

def _build_item(
    item_id: str,
    word: str,
    finals: list[str],
    initials: list[str] | None = None,
) -> Item:
    initials = initials or ["b"] * len(finals)
    syllables = [
        SyllableInfo(
            index=i + 1,
            initial=initials[i],
            final_canonical=finals[i],
            final_structure="NASAL",
            nasal_type="FRONT_N" if finals[i] in ("en", "in") else "BACK_NG",
            compound_resonance="NA",
            tone=1,
        )
        for i in range(len(finals))
    ]
    row = {
        "item_id": item_id,
        "table_kind": "table1",
        "word_raw": word,
        "pinyin_nfc": "-".join(finals),
        "global_seq": int(item_id.rsplit("-", 1)[1]),
        "syllable_count": len(finals),
        "length_bucket": str(len(finals)),
        "initial_sequence": "-".join(initials),
        "final_sequence": "-".join(finals),
        "tone_pattern_lexical": "-".join("1" for _ in finals),
        "has_neutral_tone": 0,
        "has_erhua": 0,
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
        "contains_yi": 0,
        "contains_bu": 0,
        "neutral_positions": None,
        "erhua_position": None,
    }
    segment = {
        "clip_path": f"derived/clips-v2/table1/{item_id}.wav",
        "start_ms": 0,
        "end_ms": 1000,
    }
    return make_corpus_item(row, syllables, segment)


def _syllable_rows(word: str, finals: list[str], pinyins: list[str]) -> list[dict[str, str]]:
    return [
        {"char": word[i], "pinyin": pinyins[i], "final": finals[i]}
        for i in range(len(finals))
    ]


def test_pool_keeps_only_target_final_words() -> None:
    items = [
        _build_item("t1-00001", "本领", ["en", "ing"]),
        _build_item("t1-00002", "安放", ["an", "ang"]),
        _build_item("t1-00003", "工人", ["ong", "en"]),
        _build_item("t1-00004", "功夫", ["ong", "u"]),
        _build_item("t1-00005", "妈妈", ["a", "a"]),
    ]
    pool = build_discrim_pool(items)
    assert [entry["item_id"] for entry in pool] == [
        "t1-00001",
        "t1-00003",
    ]
    # 每词判断点 = 目标音节数；其他韵母（ong/an/ang/a/u）不参与判断
    assert len(pool[0]["points"]) == 2
    assert len(pool[1]["points"]) == 1
    assert pool[1]["points"][0].final == "en"
    assert pool[0]["final_sequence"] == ["en", "ing"]


def test_pool_cross_word_has_both_pairs() -> None:
    items = [
        _build_item("t1-00001", "本领", ["en", "ing"]),
        _build_item("t1-00002", "曾经", ["eng", "ing"]),
        _build_item("t1-00003", "神经病", ["en", "ing", "ing"]),
    ]
    pool = build_discrim_pool(items)
    by_id = {entry["item_id"]: entry for entry in pool}
    pairs = [point.pair for point in by_id["t1-00001"]["points"]]
    assert pairs == ["en_eng", "in_ing"]
    assert [point.front for point in by_id["t1-00001"]["points"]] == [True, False]
    # 曾经：eng → en_eng；ing → in_ing
    assert [point.pair for point in by_id["t1-00002"]["points"]] == [
        "en_eng",
        "in_ing",
    ]
    assert len(by_id["t1-00003"]["points"]) == 3
    # 判断点 char_index 与音节位置一致
    assert [p.char_index for p in by_id["t1-00003"]["points"]] == [0, 1, 2]
    assert [p.char_span for p in by_id["t1-00003"]["points"]] == ["神", "经", "病"]


def test_pool_points_carry_pinyin_and_span_from_syllables() -> None:
    items = [_build_item("t1-00001", "本领", ["en", "ing"])]
    syllables = {
        "t1-00001": _syllable_rows("本领", ["en", "ing"], ["běn", "lǐng"]),
    }
    pool = build_discrim_pool(items, syllables)
    point = pool[0]["points"][1]
    assert point.char_index == 1
    assert point.char_span == "领"
    assert point.pinyin == "lǐng"
    assert point.final == "ing"
    assert point.pair == "in_ing"
    # 无拼音库时降级：拼音为空，字串回退到词内字符
    bare = build_discrim_pool(items)[0]["points"][1]
    assert bare.char_span == "领"
    assert bare.pinyin == ""


def test_quiz_payload_contains_no_answers() -> None:
    items = [
        _build_item("t1-00001", "本领", ["en", "ing"]),
        _build_item("t1-00002", "争", ["eng"]),
        _build_item("t1-00003", "病人", ["ing", "en"]),
    ]
    pool = build_discrim_pool(items)
    quiz = build_quiz(pool, count=3, seed=7)
    assert len(quiz) == 3
    for item in quiz:
        assert set(item) == {"item_id", "word", "points"}
        for point in item["points"]:
            # 答案（final / pinyin / front）绝不下发
            assert set(point) == {"char_index", "char_span", "pair"}
            assert point["pair"] in ("en_eng", "in_ing")
    # 同 seed 可复现；count 超池子时全量返回
    again = build_quiz(pool, count=3, seed=7)
    assert [i["item_id"] for i in again] == [i["item_id"] for i in quiz]
    assert len(build_quiz(pool, count=99, seed=1)) == 3


def test_judge_answer_per_point() -> None:
    items = [_build_item("t1-00001", "本领", ["en", "ing"])]
    syllables = {
        "t1-00001": _syllable_rows("本领", ["en", "ing"], ["běn", "lǐng"]),
    }
    points = build_discrim_pool(items, syllables)[0]["points"]
    # en → front；ing → back：全对
    results = judge_answer(points, ["front", "back"])
    assert [r["correct"] for r in results] == [True, True]
    assert [r["final"] for r in results] == ["en", "ing"]
    assert [r["pinyin"] for r in results] == ["běn", "lǐng"]
    assert [r["front"] for r in results] == [True, False]
    # 全错
    results = judge_answer(points, ["back", "front"])
    assert [r["correct"] for r in results] == [False, False]
    # 长度不符 / 非法取值
    try:
        judge_answer(points, ["front"])
    except ValueError as exc:
        assert "expected 2 answers" in str(exc)
    else:
        raise AssertionError("length mismatch must raise")
    try:
        judge_answer(points, ["front", "sideways"])
    except ValueError as exc:
        assert "sideways" in str(exc)
    else:
        raise AssertionError("invalid answer must raise")


def test_consecutive_penalty_and_round_summary() -> None:
    assert consecutive_penalty(0) == 0
    assert consecutive_penalty(1) == 0
    assert consecutive_penalty(2) == 1
    assert consecutive_penalty(5) == 4
    # 模拟一轮：错 / 错 / 对 / 错 / 错 / 错 / 对
    def word(correct: list[bool]) -> list[dict]:
        return [
            {"correct": flag, "char_index": i}
            for i, flag in enumerate(correct)
        ]

    results = [
        word([False]),
        word([False, False]),
        word([True]),
        word([False]),
        word([False]),
        word([False]),
        word([True, True]),
    ]
    summary = summarize_round(results)
    assert summary["correct_points"] == 3
    assert summary["total_points"] == 9
    assert summary["perfect_words"] == 2
    assert summary["consecutive_peak"] == 3
    assert summary["penalty"] == 2
    assert summary["score"] == 1


def test_load_discrim_syllables_missing_db(tmp_path: Path) -> None:
    assert load_discrim_syllables(tmp_path / "nope.sqlite3") == {}


def test_target_finals_exactly_four() -> None:
    assert TARGET_FINALS == ("en", "eng", "in", "ing")


# --------------------------------------------------------------------------
# 端点级：phonology.sqlite3（item_features_available 视图）→ create_app
# --------------------------------------------------------------------------

ITEM_COLUMNS = (
    "item_id, table_kind, word_raw, pinyin_nfc, global_seq, syllable_count, "
    "length_bucket, initial_sequence, final_sequence, tone_pattern_lexical, "
    "has_neutral_tone, has_erhua, has_adjacent_33, has_flat_initial, "
    "has_retroflex_initial, has_n, has_l, has_jqx, has_front_nasal, "
    "has_back_nasal, has_compound_final, has_third_tone, contains_yi, "
    "contains_bu, neutral_positions, erhua_position"
)
SYLLABLE_COLUMNS = (
    "item_id, syllable_index, hanzi, pinyin_original, initial, "
    "final_canonical, final_structure, nasal_type, compound_resonance, "
    "tone_lexical"
)


def _seed_phonology_db(
    path: Path,
    words: list[tuple[str, str, list[str], list[str]]],
    excluded: list[str],
) -> None:
    """words: (item_id, word, finals, pinyins)；excluded: 额外被排除的 item_id。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE item_features (
            item_id TEXT PRIMARY KEY, table_kind TEXT, word_raw TEXT,
            pinyin_nfc TEXT, global_seq INTEGER, syllable_count INTEGER,
            length_bucket TEXT, initial_sequence TEXT, final_sequence TEXT,
            tone_pattern_lexical TEXT, has_neutral_tone INTEGER,
            has_erhua INTEGER, has_adjacent_33 INTEGER, has_flat_initial INTEGER,
            has_retroflex_initial INTEGER, has_n INTEGER, has_l INTEGER,
            has_jqx INTEGER, has_front_nasal INTEGER, has_back_nasal INTEGER,
            has_compound_final INTEGER, has_third_tone INTEGER,
            contains_yi INTEGER, contains_bu INTEGER, neutral_positions TEXT,
            erhua_position TEXT
        );
        CREATE TABLE syllable_features (
            item_id TEXT, syllable_index INTEGER, hanzi TEXT,
            pinyin_original TEXT, initial TEXT, final_canonical TEXT,
            final_structure TEXT, nasal_type TEXT, compound_resonance TEXT,
            tone_lexical INTEGER,
            PRIMARY KEY (item_id, syllable_index)
        );
        CREATE TABLE excluded_items (item_id TEXT PRIMARY KEY);
        CREATE VIEW item_features_available AS
            SELECT i.* FROM item_features i
            WHERE i.item_id NOT IN (SELECT item_id FROM excluded_items);
        CREATE VIEW syllable_features_available AS
            SELECT s.* FROM syllable_features s
            WHERE s.item_id NOT IN (SELECT item_id FROM excluded_items);
        """
    )
    for item_id, word, finals, pinyins in words:
        con.execute(
            f"INSERT INTO item_features ({ITEM_COLUMNS}) VALUES "
            "(?, 'table1', ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, 0, 0, 0, "
            "0, 0, 0, 0, 0, 0, NULL, NULL)",
            (
                item_id,
                word,
                "".join(pinyins),
                int(item_id.rsplit("-", 1)[1]),
                len(finals),
                str(len(finals)),
                "-".join("b" for _ in finals),
                "-".join(finals),
                "-".join("1" for _ in finals),
            ),
        )
        for i, (final, pinyin) in enumerate(zip(finals, pinyins)):
            nasal = "FRONT_N" if final in ("en", "in") else "BACK_NG"
            con.execute(
                f"INSERT INTO syllable_features ({SYLLABLE_COLUMNS}) VALUES "
                "(?, ?, ?, ?, 'b', ?, 'NASAL', ?, 'NA', 1)",
                (item_id, i + 1, word[i], pinyin, final, nasal),
            )
    con.executemany(
        "INSERT INTO excluded_items (item_id) VALUES (?)",
        [(item_id,) for item_id in excluded],
    )
    con.commit()
    con.close()


def _seed_corpus_segments(db_path: Path, item_ids: list[str]) -> None:
    init_db(db_path)
    import pth_corpus.db as db_mod

    with db_mod.connect_db(db_path) as con:
        con.execute(
            "INSERT INTO source_pages (source_key, table_kind, page_no, url, "
            "expected_items, fetch_status) VALUES ('t1-p001', 'table1', 1, "
            "'http://fixture/discrim', 100, 'fetched')"
        )
        page_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        for item_id in item_ids:
            seq = int(item_id.rsplit("-", 1)[1])
            con.execute(
                "INSERT INTO entries (item_id, source_page_id, table_kind, "
                "page_position, global_seq, word_raw, pinyin_raw, pinyin_nfc) "
                "VALUES (?, ?, 'table1', ?, ?, ?, 'x', 'x')",
                (item_id, page_id, seq, seq, item_id),
            )
            con.execute(
                "INSERT INTO segments (item_id, clip_path, clip_sha256, "
                "algorithm_version, confidence, start_ms, end_ms, start_ms_raw, "
                "end_ms_raw) VALUES (?, ?, ?, 'test-v2', 0.9, 0, 1000, 0, 1000)",
                (
                    item_id,
                    f"derived/clips-v2/table1/{item_id}.wav",
                    hashlib.sha256(item_id.encode()).hexdigest(),
                ),
            )


WORDS = [
    ("t1-00001", "本领", ["en", "ing"], ["běn", "lǐng"]),
    ("t1-00002", "病人", ["ing", "en"], ["bìng", "rén"]),
    ("t1-00003", "安放", ["an", "ang"], ["ān", "fàng"]),
    ("t1-00004", "争", ["eng"], ["zhēng"]),
    ("t1-00005", "神经病", ["en", "ing", "ing"], ["shén", "jīng", "bìng"]),
    ("t1-00006", "功夫", ["ong", "u"], ["gōng", "fu"]),
    ("t1-00007", "曾经", ["eng", "ing"], ["céng", "jīng"]),
    ("t1-00098", "认真", ["en", "en"], ["rèn", "zhēn"]),
]


def _make_discrim_fixture(
    tmp_path: Path,
    discrim_config: dict[str, object] | None = None,
) -> tuple[Path, TestClient]:
    data_root = tmp_path / "data"
    data_root.mkdir()
    phonology_db = data_root / "derived" / "phonology-v1" / "phonology.sqlite3"
    _seed_phonology_db(phonology_db, WORDS, excluded=["t1-00098"])
    db_path = data_root / "corpus.sqlite3"
    _seed_corpus_segments(db_path, [item_id for item_id, *_ in WORDS])
    app = create_app(
        data_root,
        generator_dir=data_root / "derived" / "training-generator-v2",
        prototype_dir=data_root / "derived" / "prototype",
        db_path=db_path,
        profiles=[_minimal_profile()],
        config=_minimal_config(),
        discrim_config=discrim_config,
    )
    return data_root, TestClient(app)


def _minimal_profile() -> V2Profile:
    return V2Profile.from_dict(
        {
            "id": "front_nasal_all",
            "name": "front_nasal_all",
            "dimension": "final",
            "mode": "single_focus",
            "target_sets": {},
            "buckets": [],
        }
    )


def _minimal_config() -> GeneratorConfig:
    return GeneratorConfig(
        version="test",
        allowed_duration_minutes=(5, 10),
    )


def test_discrim_home_and_state_endpoints(tmp_path: Path) -> None:
    _, client = _make_discrim_fixture(tmp_path)
    with client:
        home = client.get("/api/discrim/home")
        assert home.status_code == 200
        body = home.json()
        # 8 词 - 无目标音 2 词（安放/功夫）- 已排除 1 词（认真）= 5 候选
        assert body["available"] is True
        assert body["candidates"] == 5
        assert body["judging_points"] == 10
        assert body["cross_words"] == 4
        assert set(body["pair_counts"]) == {"en_eng", "in_ing"}
        # 已排除条目绝不出现
        full = client.get("/api/home").json()
        assert full["discrim"] == body
        # 状态端点：与词库对账后主词库 0/5、无到期复习、默认参数
        state = client.get("/api/discrim/state").json()
        assert state["library"] == {"round": 1, "cursor": 0, "total": 5}
        assert state["review"]["due_today"] == 0
        assert state["review"]["pending"] == 0
        assert state["review"]["intervals"] == [1, 3, 7]
        assert state["practice_sizes"] == [50, 100, 150]
        # 出题结果里没有「认真」（已排除条目）
        session = client.post(
            "/api/discrim/library/session", json={"count": 50, "seed": 3}
        ).json()
        assert {i["item_id"] for i in session["items"]} == {
            "t1-00001",
            "t1-00002",
            "t1-00004",
            "t1-00005",
            "t1-00007",
        }


def test_discrim_library_session_payload_has_no_answers(tmp_path: Path) -> None:
    _, client = _make_discrim_fixture(tmp_path)
    with client:
        resp = client.post("/api/discrim/library/session", json={"count": 3})
    assert resp.status_code == 201
    body = resp.json()
    assert body["session_id"].startswith("disc-")
    assert body["count"] == 3
    for item in body["items"]:
        assert set(item) == {"item_id", "word", "points"}
        assert not any("final" in p or "pinyin" in p for p in item["points"])
    assert body["meta"]["round"] == 1
    assert body["meta"]["total"] == 5
    assert body["meta"]["cursor_before"] == 0
    # count 越界 → 422
    with client:
        assert client.post(
            "/api/discrim/library/session", json={"count": 0}
        ).status_code == 422
        assert client.post(
            "/api/discrim/library/session", json={"count": 151}
        ).status_code == 422


def test_discrim_library_cursor_advances_per_result(tmp_path: Path) -> None:
    data_root, client = _make_discrim_fixture(tmp_path)
    with client:
        session = client.post(
            "/api/discrim/library/session", json={"count": 3}
        ).json()
        sid = session["session_id"]
        items = session["items"]
        # 按出题顺序答前两个词 → 游标前进 2
        for item in items[:2]:
            resp = client.post(
                "/api/discrim/library/result",
                json={"session_id": sid, "item_id": item["item_id"], "correct": True},
            )
            assert resp.status_code == 200
        state = client.get("/api/discrim/state").json()
        assert state["library"]["cursor"] == 2
        assert state["library"]["total"] == 5
        # 答错一个词 → 排进长期复习（明天到期）
        wrong = client.post(
            "/api/discrim/library/result",
            json={"session_id": sid, "item_id": items[2]["item_id"], "correct": False},
        ).json()
        assert wrong["cursor"] == 3
        state = client.get("/api/discrim/state").json()
        assert state["library"]["cursor"] == 3
        assert state["review"]["pending"] == 1
        assert state["review"]["due_today"] == 0  # 明天才到期
        # 下一批从第 4 个词继续（固定乱序 + 游标，不重复）
        session2 = client.post(
            "/api/discrim/library/session", json={"count": 50}
        ).json()
        ids2 = [i["item_id"] for i in session2["items"]]
        assert ids2[0] not in {i["item_id"] for i in items}
        # 结果落在文件里（重载不丢）
        progress_file = (
            data_root / "derived" / "prototype" / "discrim_progress.json"
        )
        assert progress_file.is_file()


def test_discrim_answer_endpoint(tmp_path: Path) -> None:
    _, client = _make_discrim_fixture(tmp_path)
    with client:
        # count=50 → 一次取满 5 候选，保证 t1-00001 在题单里
        session = client.post(
            "/api/discrim/library/session", json={"count": 50}
        ).json()
        sid = session["session_id"]
        # 本领 [en, ing]：front/back 全对
        good = client.post(
            "/api/discrim/answer",
            json={"session_id": sid, "item_id": "t1-00001", "answers": ["front", "back"]},
        )
        assert good.status_code == 200
        body = good.json()
        assert body["all_correct"] is True
        assert [r["final"] for r in body["results"]] == ["en", "ing"]
        assert [r["pinyin"] for r in body["results"]] == ["běn", "lǐng"]
        # 全错
        bad = client.post(
            "/api/discrim/answer",
            json={"session_id": sid, "item_id": "t1-00001", "answers": ["back", "front"]},
        )
        assert bad.json()["all_correct"] is False
        assert [r["correct"] for r in bad.json()["results"]] == [False, False]
        # 长度不符 → 400；非法取值 → 422；未知会话 → 404；会话外词 → 404
        assert client.post(
            "/api/discrim/answer",
            json={"session_id": sid, "item_id": "t1-00001", "answers": ["front"]},
        ).status_code == 400
        assert client.post(
            "/api/discrim/answer",
            json={"session_id": sid, "item_id": "t1-00001", "answers": ["front", "nope"]},
        ).status_code == 422
        assert client.post(
            "/api/discrim/answer",
            json={"session_id": "disc-missing", "item_id": "t1-00001", "answers": ["front", "back"]},
        ).status_code == 404
        assert client.post(
            "/api/discrim/answer",
            json={"session_id": sid, "item_id": "t1-99999", "answers": ["front"]},
        ).status_code == 404


def test_discrim_review_flow_endpoint(tmp_path: Path) -> None:
    """首间隔 0 天：答错当天即到期，走通复习排期 0→3→7→掌握。"""
    config = {"review_intervals_days": [0, 3, 7]}
    _, client = _make_discrim_fixture(tmp_path, discrim_config=config)
    with client:
        # 主词库 5 词全部答错 → 当天即到期
        session = client.post(
            "/api/discrim/library/session", json={"count": 50}
        ).json()
        for item in session["items"]:
            client.post(
                "/api/discrim/library/result",
                json={"session_id": session["session_id"], "item_id": item["item_id"], "correct": False},
            )
        state = client.get("/api/discrim/state").json()
        assert state["review"]["due_today"] == 5
        assert state["review"]["pending"] == 5
        # 复习不改主词库游标
        assert state["library"]["cursor"] == 5
        # 复习一轮：今日到期词全部出现一次
        review = client.post("/api/discrim/review/session", json={}).json()
        ids = [i["item_id"] for i in review["items"]]
        assert len(ids) == 5
        assert len(set(ids)) == 5
        # 两个词一次就对 → 前进到 +3 天
        for item_id in ids[:2]:
            resp = client.post(
                "/api/discrim/review/result",
                json={"session_id": review["session_id"], "item_id": item_id, "correct": True},
            ).json()
            assert resp["correct"] is True
            assert resp["scheduled_in_days"] == 3
            assert resp["mastered"] is False
        # 一个词答错 → 仍到期；复现答对 → 重置回明天（+0）
        target = ids[2]
        wrong = client.post(
            "/api/discrim/review/result",
            json={"session_id": review["session_id"], "item_id": target, "correct": False},
        ).json()
        assert wrong["correct"] is False
        assert wrong["due_remaining"] == 3  # 2 个已排期 + 本词仍到期
        reset = client.post(
            "/api/discrim/review/result",
            json={"session_id": review["session_id"], "item_id": target, "correct": True, "had_wrong_this_round": True},
        ).json()
        assert reset["scheduled_in_days"] == 0
        assert reset["mastered"] is False
        # 剩余两个词也一次就对 → 只剩「答错重置」那个词（首间隔 0 → 仍属今日）
        for item_id in ids[3:]:
            client.post(
                "/api/discrim/review/result",
                json={"session_id": review["session_id"], "item_id": item_id, "correct": True},
            )
        state = client.get("/api/discrim/state").json()
        assert state["review"]["due_today"] == 1
        # 再开会话：只剩那个重置词（复现机制闭环）
        again = client.post("/api/discrim/review/session", json={}).json()
        assert [i["item_id"] for i in again["items"]] == [target]
        # 会话外词 → 404
        assert client.post(
            "/api/discrim/review/result",
            json={"session_id": review["session_id"], "item_id": "t1-99999", "correct": True},
        ).status_code == 404


def test_discrim_review_mastered_endpoint(tmp_path: Path) -> None:
    """同一词连续三次「一次就对」→ 掌握退出活跃复习。"""
    config = {"review_intervals_days": [0, 3, 7]}
    _, client = _make_discrim_fixture(tmp_path, discrim_config=config)
    with client:
        session = client.post(
            "/api/discrim/library/session", json={"count": 50}
        ).json()
        target = session["items"][0]["item_id"]
        client.post(
            "/api/discrim/library/result",
            json={"session_id": session["session_id"], "item_id": target, "correct": False},
        )
        review = client.post("/api/discrim/review/session", json={}).json()
        for expected in (3, 7):
            resp = client.post(
                "/api/discrim/review/result",
                json={"session_id": review["session_id"], "item_id": target, "correct": True},
            ).json()
            assert resp["scheduled_in_days"] == expected
        resp = client.post(
            "/api/discrim/review/result",
            json={"session_id": review["session_id"], "item_id": target, "correct": True},
        ).json()
        assert resp["mastered"] is True
        state = client.get("/api/discrim/state").json()
        assert state["review"]["pending"] == 0


def test_discrim_warmup_session_endpoint(tmp_path: Path) -> None:
    """趁热巩固：按本轮错词建会话，可判题；不写进度。"""
    _, client = _make_discrim_fixture(tmp_path)
    with client:
        warmup = client.post(
            "/api/discrim/warmup/session",
            json={"item_ids": ["t1-00001", "t1-00004", "t1-00001"]},
        )
        assert warmup.status_code == 201
        body = warmup.json()
        # 重复 id 去重
        assert body["count"] == 2
        assert {i["item_id"] for i in body["items"]} == {"t1-00001", "t1-00004"}
        assert body["meta"]["kind"] == "warmup"
        # 判题可用
        judged = client.post(
            "/api/discrim/answer",
            json={"session_id": body["session_id"], "item_id": "t1-00004", "answers": ["back"]},
        ).json()
        assert judged["all_correct"] is True
        # 空列表 → 422（长度校验）；未知词 → 400
        assert client.post(
            "/api/discrim/warmup/session", json={"item_ids": []}
        ).status_code == 422
        assert client.post(
            "/api/discrim/warmup/session", json={"item_ids": ["t1-99999"]}
        ).status_code == 400


def test_discrim_seed_mistakes_endpoint(tmp_path: Path) -> None:
    _, client = _make_discrim_fixture(tmp_path)
    with client:
        resp = client.post(
            "/api/discrim/seed-mistakes",
            json={"item_ids": ["t1-00001", "t1-00004", "t1-00001"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["seeded"] == 3
        assert body["pending"] == 2  # 重复 id 只累计
        assert body["due_today"] == 0  # 明天才到期


def test_discrim_review_session_empty(tmp_path: Path) -> None:
    _, client = _make_discrim_fixture(tmp_path)
    with client:
        assert client.post("/api/discrim/review/session", json={}).status_code == 400


def test_discrim_three_point_word(tmp_path: Path) -> None:
    _, client = _make_discrim_fixture(tmp_path)
    with client:
        session = client.post(
            "/api/discrim/library/session", json={"count": 50}
        ).json()
        resp = client.post(
            "/api/discrim/answer",
            json={
                "session_id": session["session_id"],
                "item_id": "t1-00005",
                "answers": ["front", "back", "back"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["all_correct"] is True
        assert [r["char_span"] for r in body["results"]] == ["神", "经", "病"]
        assert [r["pair"] for r in body["results"]] == ["en_eng", "in_ing", "in_ing"]


def test_discrim_events_recorded(tmp_path: Path) -> None:
    data_root, client = _make_discrim_fixture(tmp_path)
    with client:
        resp = client.post(
            "/api/discrim/events",
            json={
                "session_id": "disc-test-1",
                "source": "library",
                "start_time": "2026-08-16T10:00:00Z",
                "end_time": "2026-08-16T10:01:00Z",
                "exit_early": False,
                "item_count": 10,
                "point_count": 11,
                "correct_points": 9,
                "wrong_points": 2,
                "perfect_words": 8,
                "consecutive_peak": 2,
                "penalty": 1,
                "actual_duration_sec": 60.0,
                "seed": 7,
            },
        )
    assert resp.status_code == 201
    events = (
        data_root / "derived" / "prototype" / "logs" / "events.jsonl"
    ).read_text(encoding="utf-8")
    record = json.loads(events.strip().splitlines()[-1])
    assert record["type"] == "discrim"
    assert record["source"] == "library"
    assert record["consecutive_peak"] == 2
    assert record["penalty"] == 1


def test_discrim_home_empty_pool(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    phonology_db = data_root / "derived" / "phonology-v1" / "phonology.sqlite3"
    _seed_phonology_db(
        phonology_db,
        [("t1-00001", "安放", ["an", "ang"], ["ān", "fàng"])],
        excluded=[],
    )
    db_path = data_root / "corpus.sqlite3"
    _seed_corpus_segments(db_path, ["t1-00001"])
    app = create_app(
        data_root,
        generator_dir=data_root / "derived" / "training-generator-v2",
        prototype_dir=data_root / "derived" / "prototype",
        db_path=db_path,
        profiles=[_minimal_profile()],
        config=_minimal_config(),
    )
    with TestClient(app) as client:
        home = client.get("/api/discrim/home").json()
        assert home["available"] is False
        assert home["candidates"] == 0
        resp = client.post("/api/discrim/library/session", json={"count": 50})
        assert resp.status_code == 404
