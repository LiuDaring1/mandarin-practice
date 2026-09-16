"""Tests for the sentence-practice corpus pipeline (sentence_reading.py)."""

from __future__ import annotations

import csv
import json
import math
import wave
from pathlib import Path

import numpy as np
import pytest

from pth_corpus import cli
from pth_corpus.sentence_reading import (
    BACK_LABEL,
    BENCHMARK_SENTENCE,
    FRONT_LABEL,
    OTHER_LABEL,
    SentenceReadingError,
    align_article,
    apply_filter,
    apply_final_filter,
    build_session,
    cut_clip,
    final_from_pinyin,
    load_sentence_pool,
    machine_qa,
    nasal_label_of_final,
    norm_hanzi,
    parse_page_text,
    run_cut,
    run_extract,
    run_score,
    score_sentence,
    select_reason,
    sentence_weight,
    silence_ratio,
    split_sentences,
)


# ---------------------------------------------------------------------------
# 韵母提取 / 前后鼻音归类
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("py", "expected"),
    [
        ("jiang1", "iang"),
        ("xin1", "in"),
        ("chuang2", "uang"),
        ("yuan2", "üan"),
        ("zhi1", "-i_back"),
        ("si1", "-i_front"),
        ("er2", "er"),
        ("weng1", "ueng"),
        ("yun2", "ün"),
        ("lü4", "ü"),
        ("nü3", "ü"),
        ("hua1r", "ua"),
        ("yong1", "iong"),
        ("xiong2", "iong"),
        ("wen2", "uen"),
        ("liu2", "iou"),
        ("gui1", "uei"),
        ("jun1", "ün"),
        ("quan2", "üan"),
        ("xue2", "üe"),
        ("bu4", "u"),
        ("yu2", "ü"),
        ("ying1", "ing"),
        ("ye4", "ie"),
        ("ong", "ong"),
        ("ang2", "ang"),
        ("ian1", "ian"),
        ("uang", "uang"),
        ("uai4", "uai"),
        ("ei3", "ei"),
    ],
)
def test_final_from_pinyin(py: str, expected: str) -> None:
    assert final_from_pinyin(py) == expected


def test_nasal_labels() -> None:
    assert nasal_label_of_final("an") == FRONT_LABEL
    assert nasal_label_of_final("ün") == FRONT_LABEL
    assert nasal_label_of_final("ang") == BACK_LABEL
    assert nasal_label_of_final("ong") == BACK_LABEL
    assert nasal_label_of_final("a") == OTHER_LABEL
    assert nasal_label_of_final("er") == OTHER_LABEL


# ---------------------------------------------------------------------------
# 断句与页面解析
# ---------------------------------------------------------------------------

def test_split_sentences() -> None:
    text = "第一句。第二句！第三句？第四句；第五句"
    assert split_sentences(text) == [
        "第一句", "第二句", "第三句", "第四句", "第五句",
    ]


def test_split_sentences_handles_wrap_and_empty() -> None:
    text = "甲句。\n乙句！\n\n；\n丙句？，，"
    assert split_sentences(text) == ["甲句", "乙句", "丙句"]


def test_split_sentences_keeps_inner_punctuation() -> None:
    assert split_sentences("他说：“好”，就走了。") == [
        "他说：“好”，就走了",
    ]


def test_parse_page_text() -> None:
    text = (
        "2024 年新大纲普通话免费模拟测评\n"
        "2024 年新大纲普通话免费模拟测评\n"
        "《读书人是幸福人》\n"
        "我常想读书人是世间幸福人。\n"
        "现实的世界是人人都有的。\n"
    )
    title, body = parse_page_text(text)
    assert title == "读书人是幸福人"
    assert body == "我常想读书人是世间幸福人。现实的世界是人人都有的。"


# ---------------------------------------------------------------------------
# 拼音打分与筛选
# ---------------------------------------------------------------------------

def test_score_sentence_jiangxin() -> None:
    metrics = score_sentence("将心比心")
    assert metrics["label_seq"] == "BFOF"
    assert metrics["pinyin_seq"] == "jiāng xīn bǐ xīn"  # 展示用声调符号
    assert metrics["front_count"] == 2
    assert metrics["back_count"] == 1
    assert metrics["nasal_count"] == 3
    assert metrics["nasal_density"] == pytest.approx(0.75)


def test_score_sentence_benchmark() -> None:
    metrics = score_sentence(BENCHMARK_SENTENCE)
    assert metrics["char_count"] == 42
    assert metrics["nasal_count"] == 16
    assert metrics["nasal_density"] == pytest.approx(16 / 42, abs=1e-3)
    assert select_reason(metrics) == "density"


@pytest.mark.parametrize(
    ("density", "chars", "nasal", "expected"),
    [
        (0.25, 30, 7, "density"),
        (0.249, 30, 7, None),
        (0.10, 25, 4, "short_dense"),
        (0.10, 26, 4, None),
        (0.10, 25, 3, None),
    ],
)
def test_select_reason(density, chars, nasal, expected) -> None:
    metrics = {
        "nasal_density": density,
        "char_count": chars,
        "nasal_count": nasal,
    }
    assert select_reason(metrics) == expected


def test_select_reason_min_chars_gate() -> None:
    # 人耳反馈：<8 字的碎片不收（潮在涨 / 怎么不珍惜呀 之类）
    assert (
        select_reason(
            {"nasal_density": 0.9, "char_count": 7, "nasal_count": 3}
        )
        is None
    )
    assert (
        select_reason(
            {"nasal_density": 0.9, "char_count": 8, "nasal_count": 3}
        )
        == "density"
    )
    assert (
        select_reason(
            {"nasal_density": 0.1, "char_count": 8, "nasal_count": 4},
            min_chars=10,
        )
        is None
    )


def test_norm_hanzi() -> None:
    assert norm_hanzi("他，说：ABC 123“好”。") == "他说好"


# ---------------------------------------------------------------------------
# extract / score 管线（--pages 无 PDF 路径）
# ---------------------------------------------------------------------------

PAGES_FIXTURE = [
    {
        "page": 1,
        "text": (
            "2024 年新大纲普通话免费模拟测评\n"
            "《读书人是幸福人》\n"
            "我常想读书人是世间幸福人。\n"
            + BENCHMARK_SENTENCE
            + "。\n"
            "一个人的一生，只能经历自己拥有的那一份欣悦。\n"
        ),
    },
    {
        "page": 2,
        "text": (
            "2024 年新大纲普通话免费模拟测评\n"
            "《小鸟的天堂》\n"
            "我们的船渐渐地逼近榕树了。\n"
        ),
    },
]


def _fake_audio_dir(tmp_path: Path) -> Path:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "读书人是幸福人.mp3").write_bytes(b"fake")
    (audio_dir / "鸟的天堂.mp3").write_bytes(b"fake")
    (audio_dir / "颐和园.mp4").write_bytes(b"fake")
    return audio_dir


def test_run_extract(tmp_path: Path) -> None:
    out = tmp_path / "sp"
    audio_dir = _fake_audio_dir(tmp_path)
    summary = run_extract(
        pages=PAGES_FIXTURE, audio_dir=audio_dir, out_dir=out
    )
    assert summary["status"] == "succeeded"
    assert summary["articles"] == 2
    assert summary["articles_with_audio"] == 2
    articles = [
        json.loads(line) for line in (out / "articles.jsonl").read_text().splitlines()
    ]
    assert articles[0]["article_id"] == "01-读书人是幸福人"
    assert articles[0]["audio_file"] == "读书人是幸福人.mp3"
    # 标题变体：小鸟的天堂 -> 鸟的天堂
    assert articles[1]["audio_file"] == "鸟的天堂.mp3"
    sentences = [
        json.loads(line)
        for line in (out / "sentences.jsonl").read_text().splitlines()
    ]
    assert sentences[0]["sentence_id"] == "01-读书人是幸福人-0001"
    assert sentences[1]["text"] == BENCHMARK_SENTENCE
    assert all(s["char_count"] > 0 for s in sentences)


def test_run_extract_missing_audio_flagged(tmp_path: Path) -> None:
    out = tmp_path / "sp"
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "读书人是幸福人.mp3").write_bytes(b"fake")
    summary = run_extract(pages=PAGES_FIXTURE, audio_dir=audio_dir, out_dir=out)
    assert summary["missing_audio"] == ["02-小鸟的天堂（小鸟的天堂）"]


def test_run_extract_requires_source(tmp_path: Path) -> None:
    with pytest.raises(SentenceReadingError):
        run_extract(pages=None, audio_dir=tmp_path, out_dir=tmp_path / "sp")


def test_run_score_flow(tmp_path: Path) -> None:
    out = tmp_path / "sp"
    run_extract(pages=PAGES_FIXTURE, audio_dir=_fake_audio_dir(tmp_path), out_dir=out)
    summary = run_score(out_dir=out)
    assert summary["status"] == "succeeded"
    assert summary["benchmark_sentence"]["found"] is True
    assert summary["benchmark_sentence"]["selected"] is True
    with open(out / "sentences_scored.csv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 4
    by_id = {r["sentence_id"]: r for r in rows}
    bench = by_id["01-读书人是幸福人-0002"]
    assert bench["selected"] == "True"
    assert bench["label_seq"].count("F") == int(bench["front_count"])
    assert int(bench["front_count"]) + int(bench["back_count"]) == int(
        bench["nasal_count"]
    )
    assert (out / "polyphones.csv").is_file()


def test_run_score_empty_requires_extract(tmp_path: Path) -> None:
    with pytest.raises(SentenceReadingError):
        run_score(out_dir=tmp_path / "sp")


# ---------------------------------------------------------------------------
# 对齐算法（合成 whisper 分段）
# ---------------------------------------------------------------------------

def _seg(start: float, end: float, text: str) -> dict:
    return {"start": start, "end": end, "text": text}


def test_align_article_exact() -> None:
    sentences = [
        {"sentence_id": "x-0001", "text": "读书人是幸福人。"},
        {"sentence_id": "x-0002", "text": "我们的船渐渐逼近榕树。"},
    ]
    segments = [
        _seg(0.0, 2.0, "读书人是幸福人"),
        _seg(2.2, 5.0, "我们的船渐渐逼近榕树"),
    ]
    rows = align_article(sentences, segments)
    assert rows[0]["tier"] == "high"
    assert rows[0]["score"] > 0.9
    assert 0.0 <= rows[0]["start"] < rows[0]["end"] <= 2.0
    assert rows[1]["start"] >= 2.2
    assert rows[1]["tier"] == "high"


def test_align_article_splits_across_segments() -> None:
    sentences = [{"sentence_id": "x-0001", "text": "这是一句很长的句子需要跨段对齐。"}]
    segments = [
        _seg(0.0, 1.0, "这是一句很长的句子"),
        _seg(1.1, 2.2, "需要跨段对齐"),
    ]
    rows = align_article(sentences, segments)
    assert rows[0]["tier"] == "high"
    assert rows[0]["window"][1] > 9  # 跨入第二段
    assert 0.0 <= rows[0]["start"] < rows[0]["end"] <= 2.2


def test_align_article_pinyin_channel_rescues_homophones() -> None:
    # whisper 把字听成同音字：字符通道低，拼音通道应拉回高分
    sentences = [{"sentence_id": "x-0001", "text": "读书人是幸福人"}]
    segments = [_seg(0.0, 2.0, "读疏人是性福人")]
    rows = align_article(sentences, segments)
    assert rows[0]["score"] >= 0.8
    assert rows[0]["tier"] == "high"


def test_align_article_low_confidence_on_garbage() -> None:
    sentences = [
        {"sentence_id": "x-0001", "text": "读书人是幸福人"},
        {"sentence_id": "x-0002", "text": "我们的船渐渐逼近榕树"},
    ]
    segments = [
        _seg(0.0, 2.0, "完全不同的内容啊啊啊"),
        _seg(2.2, 5.0, "这也对不上呀"),
    ]
    rows = align_article(sentences, segments)
    assert any(r["tier"] in {"mid", "low"} for r in rows)


def test_align_article_monotonic_repeated() -> None:
    sentences = [
        {"sentence_id": "x-0001", "text": "我们的船渐渐逼近榕树"},
        {"sentence_id": "x-0002", "text": "我们的船渐渐逼近榕树"},
    ]
    segments = [
        _seg(0.0, 2.0, "我们的船渐渐逼近榕树"),
        _seg(2.2, 4.2, "我们的船渐渐逼近榕树"),
    ]
    rows = align_article(sentences, segments)
    assert rows[0]["start"] < rows[1]["start"]
    assert rows[0]["window"] == [0, 10]
    assert rows[1]["window"] == [10, 20]


def test_align_article_no_segments() -> None:
    sentences = [{"sentence_id": "x-0001", "text": "读书人"}]
    rows = align_article(sentences, [])
    assert rows[0]["tier"] == "low"
    assert rows[0]["reason"] == "no_segments"


def test_align_article_gap_goes_to_prev_when_prev_tail_misheard() -> None:
    # 前句句尾被 whisper 听成同音字（参天→餐厅）：缝全归前句，
    # 后句开头干净（不把「厅」带进后句）
    sentences = [
        {"sentence_id": "x-0001", "text": "庭院里繁花似锦古树参天"},
        {"sentence_id": "x-0002", "text": "有一株与古刹同龄的茶花"},
    ]
    segments = [
        _seg(0.0, 4.0, "庭院里繁花似锦古树餐厅有一株与古刹同龄的茶花")
    ]
    rows = align_article(sentences, segments)
    r1, r2 = rows
    assert r1["tier"] == "high" and r2["tier"] == "high"
    assert "餐" in r1["matched_text"]  # 前句拿走自己被听错的句尾
    assert r2["matched_text"].startswith("有一株")  # 后句开头干净
    assert r2["start"] == pytest.approx(r1["end"], abs=1e-6)


def test_align_article_filler_gap_claimed_by_neither() -> None:
    # 两句都完整、缝是 whisper 填充音：两不沾，起止不重叠
    sentences = [
        {"sentence_id": "x-0001", "text": "读书人是幸福人"},
        {"sentence_id": "x-0002", "text": "我们的船渐渐逼近榕树"},
    ]
    segments = [_seg(0.0, 4.0, "读书人是幸福人嗯我们的船渐渐逼近榕树")]
    rows = align_article(sentences, segments)
    assert rows[0]["tier"] == "high" and rows[1]["tier"] == "high"
    assert rows[0]["end"] < rows[1]["start"]
    assert "嗯" not in rows[0]["matched_text"] + rows[1]["matched_text"]


def test_align_article_uses_word_timestamps() -> None:
    # 词级时间戳：边界取词的真实起止，而不是段级均分
    sentences = [
        {"sentence_id": "x-0001", "text": "潮在涨"},
        {"sentence_id": "x-0002", "text": "没有谁能控制住它"},
    ]
    segments = [
        {
            "start": 0.0,
            "end": 4.0,
            "text": "潮在掌没有谁能控制住它",
            "words": [
                {"start": 0.0, "end": 1.0, "word": "潮在掌"},
                {"start": 1.2, "end": 4.0, "word": "没有谁能控制住它"},
            ],
        }
    ]
    rows = align_article(sentences, segments)
    r1, r2 = rows
    # 涨→掌 同音字归前句：r1 结束在 1.0（词边界），r2 从 1.2 开始
    assert r1["end"] == pytest.approx(1.0, abs=0.01)
    assert r2["start"] == pytest.approx(1.2, abs=0.01)


# ---------------------------------------------------------------------------
# 切分与机器 QA
# ---------------------------------------------------------------------------

def _make_wav(path: Path, seconds: float, freq: float = 440.0) -> None:
    rate = 16000
    samples = (
        (np.sin(2 * np.pi * freq * np.arange(int(rate * seconds)) / rate) * 12000)
        .astype(np.int16)
    )
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(samples.tobytes())


def test_cut_clip(tmp_path: Path) -> None:
    src = tmp_path / "src.wav"
    _make_wav(src, 5.0)
    out = tmp_path / "clip.wav"
    info = cut_clip(src, 1.0, 2.0, out)
    assert out.is_file()
    assert 1.3 <= info["clip_duration"] <= 2.0  # 0.3s 缓冲
    assert len(info["sha256"]) == 64
    assert info["src_start"] == pytest.approx(0.7)


def test_silence_ratio(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    _make_wav(wav, 2.0)
    assert silence_ratio(wav) < 0.1


def test_machine_qa(tmp_path: Path) -> None:
    manifest = [
        {
            "sentence_id": "a-0001", "article_id": "a", "wav_rel": "clips/a/a-0001.wav",
            "src_start": 0.5, "src_end": 1.5, "clip_duration": 1.0,
            "sha256": "h1", "tier": "high",
        },
        {
            "sentence_id": "a-0002", "article_id": "a", "wav_rel": "clips/a/a-0002.wav",
            "src_start": 1.0, "src_end": 99.0, "clip_duration": 99.0,
            "sha256": "h2", "tier": "high",
        },
    ]
    root = tmp_path
    (root / "clips/a").mkdir(parents=True)
    _make_wav(root / "clips/a/a-0001.wav", 1.0)
    _make_wav(root / "clips/a/a-0002.wav", 2.0)
    qa = machine_qa(manifest, root)
    assert qa["clips_checked"] == 2
    assert "a-0002" in qa["duration_out_of_range"][0]
    assert qa["status"] == "failed"
    assert qa["duplicate_hashes"] == 0


def test_run_cut_flow(tmp_path: Path) -> None:
    out = tmp_path / "sp"
    audio_dir = _fake_audio_dir(tmp_path)
    # 真实可切音频（覆盖假 mp3 用 wav 名保持一致）
    (audio_dir / "读书人是幸福人.mp3").write_bytes(b"")
    _make_wav(audio_dir / "读书人是幸福人.mp3", 8.0)
    run_extract(pages=PAGES_FIXTURE, audio_dir=audio_dir, out_dir=out)
    run_score(out_dir=out)
    (out / "alignment").mkdir()
    aligned = [
        {
            "sentence_id": "01-读书人是幸福人-0001",
            "text": "我常想读书人是世间幸福人",
            "matched_text": "我常想读书人是世间幸福人",
            "start": 0.5, "end": 2.0, "duration": 1.5,
            "score": 0.95, "tier": "high", "segments": [0, 0],
        },
        {
            "sentence_id": "01-读书人是幸福人-0003",
            "text": "一个人的一生只能经历自己拥有的那一份欣悦",
            "matched_text": "一个人的一生只能经历自己拥有的那一份欣悦",
            "start": 3.0, "end": 5.0, "duration": 2.0,
            "score": 0.5, "tier": "low", "segments": [1, 1],
        },
    ]
    with open(out / "alignment/aligned.jsonl", "w", encoding="utf-8") as fh:
        for row in aligned:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = run_cut(out_dir=out, audio_dir=audio_dir)
    assert summary["status"] == "succeeded"
    assert summary["clips"] == 1  # 仅 high 切
    manifest = json.loads((out / "clip_manifest.json").read_text())
    assert manifest[0]["sentence_id"] == "01-读书人是幸福人-0001"
    assert manifest[0]["tier"] == "high"
    assert (out / "clips/01-读书人是幸福人/01-读书人是幸福人-0001.wav").is_file()
    qa = json.loads((out / "qa_report.json").read_text())
    assert qa["status"] == "passed"


# ---------------------------------------------------------------------------
# 后端句子池
# ---------------------------------------------------------------------------

def _build_pool_fixture(tmp_path: Path) -> Path:
    out = tmp_path / "sp"
    run_extract(pages=PAGES_FIXTURE, audio_dir=_fake_audio_dir(tmp_path), out_dir=out)
    run_score(out_dir=out)
    (out / "alignment").mkdir()
    manifest = []
    aligned = []
    for i, (sid, start, end) in enumerate(
        [
            ("01-读书人是幸福人-0001", 0.5, 2.0),
            ("01-读书人是幸福人-0002", 2.5, 5.0),
            ("02-小鸟的天堂-0001", 0.5, 2.0),
        ]
    ):
        aligned.append(
            {
                "sentence_id": sid, "text": "t", "matched_text": "t",
                "start": start, "end": end, "duration": end - start,
                "score": 0.9, "tier": "high", "segments": [0, 0],
            }
        )
        manifest.append(
            {
                "sentence_id": sid, "article_id": sid.rsplit("-", 1)[0],
                "wav_rel": f"clips/{sid}.wav", "source_file": "x.mp3",
                "src_start": start, "src_end": end,
                "clip_duration": end - start, "sha256": "h", "confidence": 0.9,
                "tier": "high", "whisper_text": "t",
            }
        )
    with open(out / "alignment/aligned.jsonl", "w", encoding="utf-8") as fh:
        for row in aligned:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(out / "clip_manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False)
    return out


def test_load_sentence_pool(tmp_path: Path) -> None:
    out = _build_pool_fixture(tmp_path)
    pool = load_sentence_pool(tmp_path, out_subdir=out)
    assert len(pool) == 3
    first = pool[0]
    assert first["sentence_id"] == "01-读书人是幸福人-0001"
    assert first["article_title"] == "读书人是幸福人"
    assert first["clip_rel"].endswith(".wav")
    assert first["label_seq"]


def test_build_session_filters_and_weights(tmp_path: Path) -> None:
    out = _build_pool_fixture(tmp_path)
    pool = load_sentence_pool(tmp_path, out_subdir=out)
    bench = [r for r in pool if r["text"] == BENCHMARK_SENTENCE][0]
    assert bench["front_count"] + bench["back_count"] == bench["nasal_count"]
    mixed = build_session(pool, count=10, filter_mode="mixed", seed=1)
    for row in mixed:
        assert row["front_count"] > 0 and row["back_count"] > 0
    front = apply_filter(pool, "front")
    assert all(r["front_count"] > r["back_count"] for r in front)
    # 无放回：不超过池子大小
    assert len(build_session(pool, count=100, seed=2)) <= len(pool)


def test_build_session_rejects_bad_filter(tmp_path: Path) -> None:
    out = _build_pool_fixture(tmp_path)
    pool = load_sentence_pool(tmp_path, out_subdir=out)
    with pytest.raises(ValueError):
        build_session(pool, count=3, filter_mode="bogus")


def _pool_row(
    finals: list[str], front: int | None = None, back: int | None = None
) -> dict:
    labels = "".join(
        FRONT_LABEL
        if f in ("an", "en", "ian", "in", "uan", "uen", "üan", "ün")
        else BACK_LABEL
        for f in finals
    )
    return {
        "final_seq": " ".join(finals),
        "label_seq": labels,
        "nasal_density": 0.3,
        "front_count": front if front is not None else labels.count("F"),
        "back_count": back if back is not None else labels.count("B"),
    }


def test_apply_filter_requires_target_finals() -> None:
    # 用户调优：前鼻为主必须含 en/in，后鼻为主必须含 eng/ing
    rows = [
        _pool_row(["an", "ian", "uan"], front=3, back=0),  # 无 en/in → 不中
        _pool_row(["en", "ian", "uan"], front=3, back=0),  # 有 en → 中
        _pool_row(["in", "an"], front=2, back=0),  # 有 in → 中
        _pool_row(["ang", "iang", "eng"], front=0, back=3),  # 有 eng → 中(back)
        _pool_row(["ang", "iang", "ong"], front=0, back=3),  # 无 eng/ing → 不中
    ]
    assert [r["final_seq"] for r in apply_filter(rows, "front")] == [
        "en ian uan", "in an",
    ]
    assert [r["final_seq"] for r in apply_filter(rows, "back")] == [
        "ang iang eng",
    ]


def test_sentence_weight_boost() -> None:
    r1 = _pool_row(["en", "ian"], front=2, back=0)
    r2 = _pool_row(["en", "in", "an", "ian"], front=4, back=0)
    assert sentence_weight(r2, ("en", "in")) > sentence_weight(r1, ("en", "in"))
    assert sentence_weight(r1, ("en", "in")) > sentence_weight(r1)


def test_apply_final_filter_coverage_rule() -> None:
    rows = [
        _pool_row(["an", "ian", "uan"]),  # 0 命中 → 不中
        _pool_row(["en", "in", "ing"]),  # 3 命中 → 中
        _pool_row(["en", "in", "ian", "ang"]),  # 2 命中 → 中
        _pool_row(["en", "ian", "ang", "uang"]),  # 1/4=25% → 中
        _pool_row(["en", "an", "ian", "uan", "ang"]),  # 1/5=20% → 不中
        _pool_row(
            ["en", "an", "ian", "uan", "ang", "iang", "uang", "en", "ong"]
        ),  # 2 命中、22% → 靠 ≥2 命中 → 中
    ]
    picked = apply_final_filter(rows, ["en", "in", "ing"])
    assert len(picked) == 4
    assert picked[0]["final_seq"] == "en in ing"
    assert picked[-1]["final_seq"].count("en") == 2


def test_build_session_include_finals(tmp_path: Path) -> None:
    out = _build_pool_fixture(tmp_path)
    pool = load_sentence_pool(tmp_path, out_subdir=out)
    items = build_session(pool, count=100, include_finals=["ing", "eng"], seed=3)
    assert items
    for r in items:
        nasal = [
            f for f, label in zip(r["final_seq"].split(), r["label_seq"])
            if label in (FRONT_LABEL, BACK_LABEL)
        ]
        hits = sum(1 for f in nasal if f in {"ing", "eng"})
        assert hits >= 2 or (hits >= 1 and hits / len(nasal) >= 0.25)


# ---------------------------------------------------------------------------
# CLI 集成
# ---------------------------------------------------------------------------

def test_cli_sentence_extract_score_status(tmp_path: Path) -> None:
    out = tmp_path / "sp"
    audio_dir = _fake_audio_dir(tmp_path)
    pages_file = tmp_path / "pages.jsonl"
    with open(pages_file, "w", encoding="utf-8") as fh:
        for row in PAGES_FIXTURE:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    assert (
        cli.main(
            [
                "sentence", "extract", "--pages", str(pages_file),
                "--audio-dir", str(audio_dir), "--out", str(out),
            ]
        )
        == 0
    )
    assert cli.main(["sentence", "score", "--out", str(out)]) == 0
    assert cli.main(["sentence", "status", "--out", str(out)]) == 0
    # 未知子命令：argparse 直接 SystemExit(2)
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["sentence", "nope", "--out", str(out)])
    assert exc_info.value.code == 2
