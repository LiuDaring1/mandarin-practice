"""Local-only FastAPI prototype for the Mandarin listen-and-repeat player.

The prototype deliberately keeps a minimal scope: home -> profile/duration
selection -> a real v2 session -> automatic listen-and-repeat playback ->
completion.  All rules-layer logic comes from ``training.v2.generator``; this
module only wires it to a local web UI.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .achievement import (
    AchievementConfig,
    compute_activity_reward,
    compute_review_reward,
    load_artwork_catalog,
)
from .discrimination import (
    VALID_ANSWERS,
    build_discrim_pool,
    judge_answer,
    load_discrim_syllables,
)
from .discrim_progress import DiscrimPracticeConfig, DiscrimProgress
from .review_app import validate_loopback_host  # noqa: F401  (re-exported for CLI)
from .sentence_reading import (
    ALL_NASAL_FINALS,
    FILTER_MODES,
    apply_filter,
    apply_final_filter,
    final_distribution,
    is_hanzi,
    load_sentence_pool,
    score_sentence,
)
from .training.candidates import load_items
from .training.models import GeneratorConfig, load_config
from .training.v2.engine import compute_availability
from .training.v2.generator import _universe_from_items, generate_session_v2
from .training.v2.history import HistoryStore
from .training.v2.schema import V2Profile, load_v2_profiles
from .voice_library import VoiceLibrary
from .assessment import AssessmentError, AssessmentService
from .reading_coach import NASALS, SAFE_ID, ReadingCoach, plain
from .news_sentences import NEWS_ID, mixed_session


DEFAULT_DURATION_MINUTES = 3
STATIC_DIR = Path(__file__).with_name("prototype_static")
PROTOTYPE_DATA_DIR = Path(__file__).with_name("prototype_data")

# 听辨练习：内存会话上限（本地原型，超出淘汰最旧）；题量与纠错阈值在
# discrim_progress 的 DiscrimPracticeConfig 里配置。
DISCRIM_MAX_SESSIONS = 200


class PrototypeAppError(RuntimeError):
    """Raised when the local prototype app cannot serve its data."""


# Home-screen menu: every v2 profile mapped to short, human-friendly labels
# with the actual initials/finals/tone marks shown where they help.
PROFILE_MENU: list[dict[str, Any]] = [
    {
        "id": "initial",
        "label": "声母",
        "items": [
            {"profile_id": "bilabial_focus", "label": "双唇音（b p m）"},
            {"profile_id": "h_f_focus", "label": "f / h（唇齿音 / 舌根音）"},
            {"profile_id": "flat_focus", "label": "平舌音（z c s）"},
            {"profile_id": "retroflex_focus", "label": "翘舌音（zh ch sh r）"},
            {"profile_id": "flat_retroflex_contrast", "label": "平翘舌音对比"},
            {"profile_id": "n_l_contrast", "label": "鼻边音（n l）"},
            {"profile_id": "jqx_special", "label": "舌面音（j q x）"},
            {"profile_id": "velar_focus", "label": "舌根音（g k h）"},
            {"profile_id": "dt_focus", "label": "舌尖中音（d t）"},
        ],
    },
    {
        "id": "final",
        "label": "韵母",
        "items": [
            {"profile_id": "simple_final_focus", "label": "单韵母（a o e i u ü）"},
            {"profile_id": "compound_front", "label": "前响复韵母（ai ei ao ou）"},
            {"profile_id": "compound_middle", "label": "中响复韵母（iao iou uai uei）"},
            {"profile_id": "compound_back", "label": "后响复韵母（ia ie ua uo üe）"},
            {"profile_id": "compound_all", "label": "复韵母综合"},
            {"profile_id": "front_nasal_basic", "label": "前鼻音 · 基础（an en in）"},
            {"profile_id": "front_nasal_extended", "label": "前鼻音 · 扩展（ian uan uen üan ün）"},
            {"profile_id": "front_nasal_all", "label": "前鼻音综合"},
            {"profile_id": "back_nasal_basic", "label": "后鼻音 · 基础（ang eng ing ong）"},
            {"profile_id": "back_nasal_extended", "label": "后鼻音 · 扩展（iang uang ueng iong）"},
            {"profile_id": "back_nasal_all", "label": "后鼻音综合"},
            {"profile_id": "front_back_nasal_contrast_1", "label": "前后鼻音对比（en/in · eng/ing）"},
            {"profile_id": "front_back_nasal_contrast_2", "label": "前后鼻音对比 · 进阶（an/ian/uan · ang/iang/uang）"},
        ],
    },
    {
        "id": "tone",
        "label": "声调",
        "items": [
            {"profile_id": "tone_1", "label": "阴平（ˉ）"},
            {"profile_id": "tone_2", "label": "阳平（ˊ）"},
            {"profile_id": "tone_3", "label": "上声（ˇ）"},
            {"profile_id": "tone_4", "label": "去声（ˋ）"},
            {"profile_id": "tone_all", "label": "四声综合"},
        ],
    },
    {
        "id": "sandhi",
        "label": "语流音变",
        "items": [
            {"profile_id": "neutral_focus", "label": "轻声"},
            {"profile_id": "erhua_focus", "label": "儿化"},
            {"profile_id": "yi_bu_focus", "label": "一 / 不 变调"},
            {"profile_id": "tone_33", "label": "上声变调（3-3）"},
        ],
    },
    {
        "id": "general",
        "label": "综合",
        "items": [
            {"profile_id": "general", "label": "日常综合练习"},
        ],
    },
]

# The first-version product is deliberately focused: the full 34-profile menu
# stays available underneath (see PROFILE_MENU), but the home screen only
# exposes the three front/back-nasal entries from the product spec.
FOCUS_ENTRIES: list[dict[str, Any]] = [
    {
        "id": "front_nasal",
        "label": "前鼻音训练",
        "short_label": "前鼻音",
        "pinyin_hint": "an · en · in · ian · uan · uen · üan · ün",
        "profile_id": "front_nasal_all",
        "tone": "teal",
        "blurb": "舌尖归位，收住 n 的鼻音",
        "filter_groups": [
            {"id": "an", "label": "an", "example": "安", "finals": ["an"]},
            {"id": "en", "label": "en", "example": "恩", "finals": ["en"]},
            {"id": "in", "label": "in", "example": "因", "finals": ["in"]},
            {"id": "ian", "label": "ian", "example": "烟", "finals": ["ian"]},
            {"id": "uan", "label": "uan", "example": "弯", "finals": ["uan"]},
            {"id": "uen", "label": "uen", "example": "温", "finals": ["uen"]},
            {"id": "yuan", "label": "üan", "example": "冤", "finals": ["üan"]},
            {"id": "yun", "label": "ün", "example": "晕", "finals": ["ün"]},
        ],
    },
    {
        "id": "back_nasal",
        "label": "后鼻音训练",
        "short_label": "后鼻音",
        "pinyin_hint": "ang · eng · ing · ong · iang · uang · ueng · iong",
        "profile_id": "back_nasal_all",
        "tone": "orange",
        "blurb": "舌根抬起，送出 ng 的共鸣",
        "filter_groups": [
            {"id": "ang", "label": "ang", "example": "昂", "finals": ["ang"]},
            {"id": "eng", "label": "eng", "example": "争", "finals": ["eng"]},
            {"id": "ing", "label": "ing", "example": "英", "finals": ["ing"]},
            {"id": "iang", "label": "iang", "example": "秧", "finals": ["iang"]},
            {"id": "ong", "label": "ong", "example": "工", "finals": ["ong"]},
            {"id": "uang", "label": "uang", "example": "汪", "finals": ["uang"]},
            {"id": "ueng", "label": "ueng", "example": "翁", "finals": ["ueng"]},
            {"id": "iong", "label": "iong", "example": "拥", "finals": ["iong"]},
        ],
    },
    {
        "id": "contrast",
        "label": "前后鼻音对比",
        "short_label": "前后对比",
        "pinyin_hint": "an↔ang · en↔eng · in↔ing · ian↔iang · uan↔uang",
        "profile_id": "front_back_nasal_contrast",
        "tone": "violet",
        "blurb": "连续切换，把 n 和 ng 听出区别",
        "filter_groups": [
            {
                "id": "an_ang",
                "label": "an ↔ ang",
                "example": "安·昂",
                "finals": ["an", "ang"],
            },
            {
                "id": "en_eng",
                "label": "en ↔ eng",
                "example": "恩·争",
                "finals": ["en", "eng"],
            },
            {
                "id": "in_ing",
                "label": "in ↔ ing",
                "example": "因·英",
                "finals": ["in", "ing"],
            },
            {
                "id": "ian_iang",
                "label": "ian ↔ iang",
                "example": "烟·秧",
                "finals": ["ian", "iang"],
            },
            {
                "id": "uan_uang",
                "label": "uan ↔ uang",
                "example": "弯·汪",
                "finals": ["uan", "uang"],
            },
        ],
    },
]

# 标准音对比组（2026-08-27 起只保留前三组，示范视频在 prototype_static/assets/calibration/）。
# Each side resolves to a real single-syllable corpus item so the metadata
# (word/pinyin) is authentic; audio now comes from the demo videos themselves.
CALIBRATION_GROUPS: list[dict[str, Any]] = [
    {
        "id": "an_ang",
        "label": "an / ang",
        "a": {"final": "an", "tone": "teal", "prefer": ["安", "氨", "岸", "案"]},
        "b": {"final": "ang", "tone": "orange", "prefer": ["昂", "盎"]},
    },
    {
        "id": "en_eng",
        "label": "en / eng",
        "a": {"final": "en", "tone": "teal", "prefer": ["恩", "真", "身"]},
        "b": {"final": "eng", "tone": "orange", "prefer": ["鞥", "争", "生"]},
    },
    {
        "id": "in_ing",
        "label": "in / ing",
        "a": {"final": "in", "tone": "teal", "prefer": ["因", "音", "心"]},
        "b": {"final": "ing", "tone": "orange", "prefer": ["应", "英", "星"]},
    },
]


ITEM_ID_RE = re.compile(r"^t[12]-\d{5}$")
SENTENCE_ID_RE = re.compile(r"^\d{2}-[^-]+-\d{4}$")


class PrototypeRuntime:
    """Lazy, cached data access for the prototype web app."""

    def __init__(
        self,
        data_root: str | Path,
        generator_dir: str | Path | None = None,
        prototype_dir: str | Path | None = None,
        db_path: str | Path | None = None,
        phonology_db: str | Path | None = None,
        *,
        items: list[Any] | None = None,
        profiles: list[V2Profile] | None = None,
        config: GeneratorConfig | None = None,
        discrim_config: dict[str, Any] | None = None,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.generator_dir = (
            Path(generator_dir).resolve()
            if generator_dir is not None
            else self.data_root / "derived" / "training-generator-v2"
        )
        self.prototype_dir = (
            Path(prototype_dir).resolve()
            if prototype_dir is not None
            else self.data_root / "derived" / "prototype"
        )
        self.db_path = Path(db_path) if db_path is not None else self.data_root / "corpus.sqlite3"
        self.phonology_db = (
            Path(phonology_db).resolve()
            if phonology_db is not None
            else self.data_root / "derived" / "phonology-v1" / "phonology.sqlite3"
        )
        self._injected_items = items
        self._injected_profiles = profiles
        self._injected_config = config
        self._injected_discrim_config = discrim_config
        self._items: list[Any] | None = None
        self._profiles: dict[str, V2Profile] | None = None
        self._config: GeneratorConfig | None = None
        self._achievement_config: AchievementConfig | None = None
        self._artworks: list[Any] | None = None
        self._calibration: list[dict[str, Any]] | None = None
        self._availability: dict[str, dict[str, Any]] = {}
        self._sentence_pool: list[dict[str, Any]] | None = None
        self._sentence_loaded: bool = False
        self._discrim_pool: list[dict[str, Any]] | None = None
        self._discrim_pool_map: dict[str, dict[str, Any]] | None = None
        self._discrim_sessions: dict[str, dict[str, Any]] = {}
        self._discrim_config: DiscrimPracticeConfig | None = None
        self._discrim_progress: DiscrimProgress | None = None
        self._warm_started = False
        self._warm_error: str | None = None
        self._ready = False
        self._warm_lock = threading.Lock()
        self.voice_library = VoiceLibrary(self.data_root)

    # ---- data access -----------------------------------------------------

    def items(self) -> list[Any]:
        if self._items is None:
            if self._injected_items is not None:
                self._items = list(self._injected_items)
            else:
                self._items = load_items(
                    self.data_root / "derived" / "phonology-v1" / "phonology.sqlite3",
                    self.db_path,
                )
        return self._items

    def profiles(self) -> dict[str, V2Profile]:
        if self._profiles is None:
            if self._injected_profiles is not None:
                self._profiles = {p.id: p for p in self._injected_profiles}
            else:
                loaded = load_v2_profiles(
                    self.generator_dir / "training_profiles_v2.json"
                )
                self._profiles = {p.id: p for p in loaded}
        return self._profiles

    def config(self) -> GeneratorConfig:
        if self._config is None:
            if self._injected_config is not None:
                self._config = self._injected_config
            else:
                self._config = load_config(
                    self.generator_dir / "generator_config_v2.json"
                )
        return self._config

    def achievement_config(self) -> AchievementConfig:
        if self._achievement_config is None:
            self._achievement_config = AchievementConfig.from_dict(
                json.loads(
                    (
                        PROTOTYPE_DATA_DIR / "achievement_config_v2.json"
                    ).read_text(encoding="utf-8")
                )
            )
        return self._achievement_config

    def artworks(self) -> list[Any]:
        if self._artworks is None:
            self._artworks = load_artwork_catalog(
                PROTOTYPE_DATA_DIR / "artwork_catalog_v2.json"
            )
        return self._artworks

    def _pick_calibration_item(self, spec: dict[str, Any]) -> Any | None:
        target = spec["final"]
        prefer = list(spec.get("prefer", []))
        matches = [
            item
            for item in self.items()
            if item.syllable_count == 1
            and item.syllables
            and item.syllables[0].final_canonical == target
        ]
        zero_initial = [
            item
            for item in matches
            if item.syllables[0].initial in ("ZERO", "")
        ]
        pool = zero_initial or matches
        for hanzi in prefer:
            for item in pool:
                if item.word_raw == hanzi:
                    return item
        return pool[0] if pool else None

    def calibration_groups(self) -> list[dict[str, Any]]:
        if self._calibration is None:
            groups: list[dict[str, Any]] = []
            for group in CALIBRATION_GROUPS:
                resolved: dict[str, Any] = {
                    "id": group["id"],
                    "label": group["label"],
                }
                for side in ("a", "b"):
                    spec = group[side]
                    item = self._pick_calibration_item(spec)
                    resolved[side] = {
                        "final": spec["final"],
                        "tone": spec["tone"],
                        "item_id": item.item_id if item else None,
                        "word": item.word_raw if item else None,
                        "pinyin": item.pinyin_nfc if item else None,
                    }
                groups.append(resolved)
            self._calibration = groups
        return self._calibration

    def availability(self, profile: V2Profile) -> dict[str, Any]:
        cached = self._availability.get(profile.id)
        if cached is not None:
            return cached
        if not self._warm_started:
            self.start_warmup()
        with self._warm_lock:
            cached = self._availability.get(profile.id)
            if cached is not None:
                return cached
            items = self.items()
            universe = _universe_from_items(items)
            result = compute_availability(items, [profile], universe)["profiles"][0]
            self._availability[profile.id] = result
            return result

    def history(self, profile_id: str) -> HistoryStore:
        config = self.config()
        return HistoryStore.load(
            profile_id,
            self.prototype_dir / "history" / f"{profile_id}.json",
            window_days=config.history_window_days,
            window_sessions=config.history_window_sessions,
        )

    # ---- sentence practice (independent of the training generator) -------

    def sentence_pool(self) -> list[dict[str, Any]]:
        if not self._sentence_loaded:
            self._sentence_loaded = True
            try:
                self._sentence_pool = load_sentence_pool(
                    self.data_root, out_subdir="derived/sentence-practice-v1"
                )
                self._sentence_pool = [{**row, "genre": "literature"} for row in self._sentence_pool]
                # News candidates remain on disk for listening QA; not released for practice.
            except (OSError, ValueError):
                self._sentence_pool = []
        return self._sentence_pool or []

    def sentence_home(self) -> dict[str, Any]:
        pool = self.sentence_pool()
        filters = {
            mode: len(apply_filter(pool, mode))
            for mode in ("all", "front", "back", "mixed")
        }
        densities = [r["nasal_density"] for r in pool]
        return {
            "available": bool(pool),
            "total_clips": len(pool),
            "articles": len({r["article_id"] for r in pool}),
            "source_counts": {genre: sum(r.get("genre") == genre for r in pool) for genre in ("literature", "news")},
            "filter_counts": filters,
            "final_stats": final_distribution(pool),
            "avg_nasal_density": (
                round(sum(densities) / len(densities), 4) if densities else 0.0
            ),
            "total_audio_sec": round(sum(r["clip_duration"] for r in pool), 1),
        }

    def sentence_custom_count(self, include_finals: list[str]) -> dict[str, Any]:
        pool = self.sentence_pool()
        return {
            "count": len(apply_final_filter(pool, include_finals)),
        }

    def sentence_item_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        pys = row["pinyin_seq"].split()
        labels = row["label_seq"]
        units: list[dict[str, str]] = []
        k = 0
        for ch in row["text"]:
            if is_hanzi(ch) and k < len(pys):
                units.append({"ch": ch, "py": pys[k], "label": labels[k]})
                k += 1
            else:
                units.append({"ch": ch, "py": "", "label": ""})
        return {
            "sentence_id": row["sentence_id"],
            "article_title": row["article_title"],
            "genre": row.get("genre", "literature"),
            "source_url": row.get("source_url"),
            "page": row["page"],
            "text": row["text"],
            "units": units,
            "pinyin_seq": row["pinyin_seq"],
            "final_seq": row["final_seq"],
            "label_seq": row["label_seq"],
            "char_count": row["char_count"],
            "nasal_count": row["nasal_count"],
            "nasal_density": row["nasal_density"],
            "front_count": row["front_count"],
            "back_count": row["back_count"],
            "select_reason": row["select_reason"],
            "clip_url": f"/api/sentence/clips/{row['sentence_id']}",
            "clip_duration": row["clip_duration"],
            "confidence": row["confidence"],
            "tier": row["tier"],
        }

    def sentence_session(
        self,
        count: int,
        filter_mode: str,
        seed: int | None = None,
        include_finals: list[str] | None = None,
    ) -> dict[str, Any]:
        pool = self.sentence_pool()
        if not pool:
            raise PrototypeAppError(
                "句子库尚未就绪（data/derived/sentence-practice-v1 无已切片句子）"
            )
        items = mixed_session(
            pool,
            count=count,
            filter_mode=filter_mode,
            seed=seed,
            include_finals=include_finals,
        )
        return {
            "session_id": f"sent-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{len(items)}",
            "filter": filter_mode,
            "include_finals": sorted(include_finals) if include_finals else None,
            "count": len(items),
            "items": [self.sentence_item_payload(row) for row in items],
        }

    def sentence_clip_path(self, sentence_id: str, voice: str | None = None) -> Path | None:
        if NEWS_ID.fullmatch(sentence_id):
            row = next((r for r in self.sentence_pool() if r["sentence_id"] == sentence_id), None)
            if row is None:
                return None
            original = (self.data_root / row["original_relative_path"]).resolve()
            try:
                original.relative_to(self.data_root)
            except ValueError:
                return None
            return self.voice_library.replacement(sentence_id, "sentence", original, voice)
        if not SENTENCE_ID_RE.fullmatch(sentence_id):
            return None
        candidate = (
            self.data_root
            / "derived"
            / "sentence-practice-v1"
            / "clips"
            / sentence_id.rsplit("-", 1)[0]
            / f"{sentence_id}.wav"
        )
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self.data_root)
        except ValueError:
            return None
        replacement = self.voice_library.replacement(sentence_id, "sentence", resolved, voice)
        if voice is not None:
            return replacement
        return replacement or (resolved if resolved.is_file() else None)

    # ---- 听辨练习（前后鼻音逐字判断，无音频，与生成器解耦） ------------

    def discrim_pool(self) -> list[dict[str, Any]]:
        if self._discrim_pool is None:
            syllables = load_discrim_syllables(self.phonology_db)
            self._discrim_pool = build_discrim_pool(self.items(), syllables)
        return self._discrim_pool

    def discrim_pool_map(self) -> dict[str, dict[str, Any]]:
        if self._discrim_pool_map is None:
            self._discrim_pool_map = {
                entry["item_id"]: entry for entry in self.discrim_pool()
            }
        return self._discrim_pool_map

    def discrim_config(self) -> DiscrimPracticeConfig:
        if self._discrim_config is None:
            if self._injected_discrim_config is not None:
                self._discrim_config = DiscrimPracticeConfig.from_dict(
                    self._injected_discrim_config
                )
            else:
                override = self.prototype_dir / "discrim_config_v1.json"
                default = PROTOTYPE_DATA_DIR / "discrim_config_v1.json"
                path = override if override.is_file() else default
                self._discrim_config = DiscrimPracticeConfig.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
        return self._discrim_config

    def discrim_progress(self) -> DiscrimProgress:
        if self._discrim_progress is None:
            progress = DiscrimProgress(
                self.prototype_dir / "discrim_progress.json",
                self.discrim_config(),
            )
            progress.load()
            self._discrim_progress = progress
        return self._discrim_progress

    def discrim_home(self) -> dict[str, Any]:
        pool = self.discrim_pool()
        judging_points = sum(len(entry["points"]) for entry in pool)
        cross_words = sum(
            1 for entry in pool if len({p.pair for p in entry["points"]}) > 1
        )
        pair_counts = {"en_eng": 0, "in_ing": 0}
        for entry in pool:
            for point in entry["points"]:
                pair_counts[point.pair] += 1
        return {
            "available": bool(pool),
            "candidates": len(pool),
            "judging_points": judging_points,
            "cross_words": cross_words,
            "pair_counts": pair_counts,
        }

    @staticmethod
    def _new_discrim_session_id() -> str:
        return (
            f"disc-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )

    def _store_discrim_session(
        self, full_items: list[dict[str, Any]], quiz: list[dict[str, Any]]
    ) -> dict[str, Any]:
        session_id = self._new_discrim_session_id()
        self._discrim_sessions[session_id] = {
            "items": full_items,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        while len(self._discrim_sessions) > DISCRIM_MAX_SESSIONS:
            oldest = next(iter(self._discrim_sessions))
            self._discrim_sessions.pop(oldest)
        return {
            "session_id": session_id,
            "count": len(quiz),
            "items": quiz,
        }

    def discrim_state(self) -> dict[str, Any]:
        progress = self.discrim_progress()
        # 先与当前词库对账（总数/新增/删除），让首页直接看到「本轮 X / 总数」
        progress.reconcile(list(self.discrim_pool_map().values()))
        return progress.state()

    def discrim_library_session(
        self, count: int, seed: int | None = None
    ) -> dict[str, Any]:
        """主词库下一批词：沿固定乱序 + 游标取词（整轮覆盖，不重复随机）。"""
        if not self.discrim_pool():
            raise PrototypeAppError(
                "听辨题库尚未就绪（正式字词表无 en/eng/in/ing 音节词）"
            )
        quiz, full_items, meta = self.discrim_progress().take_library_chunk(
            self.discrim_pool_map(), count, seed=seed
        )
        body = self._store_discrim_session(full_items, quiz)
        body["meta"] = meta
        return body

    def discrim_library_result(
        self, session_id: str, item_id: str, correct: bool
    ) -> dict[str, Any]:
        """主词库单词语结果：统计 + 答错排进复习（明天）+ 游标前进。"""
        session = self._discrim_sessions.get(session_id)
        if session is None:
            raise KeyError(f"unknown discrim session: {session_id}")
        if not any(item["item_id"] == item_id for item in session["items"]):
            raise KeyError(f"item not in discrim session: {item_id}")
        progress = self.discrim_progress()
        result = progress.record_library_result(item_id, correct)
        progress.save()
        return result

    def discrim_warmup_session(self, item_ids: list[str]) -> dict[str, Any]:
        """趁热巩固：把本轮错词建成判题会话（只练习，不写进度）。"""
        if not item_ids:
            raise ValueError("本轮没有错词，无需趁热巩固")
        pool = self.discrim_pool_map()
        missing = [item_id for item_id in item_ids if item_id not in pool]
        if missing:
            raise ValueError(f"unknown item ids: {missing[:3]}")
        quiz: list[dict[str, Any]] = []
        full_items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item_id in item_ids:
            if item_id in seen:
                continue
            seen.add(item_id)
            entry = pool[item_id]
            quiz.append(
                {
                    "item_id": entry["item_id"],
                    "word": entry["word"],
                    "points": [point.question_payload() for point in entry["points"]],
                }
            )
            full_items.append(
                {
                    "item_id": entry["item_id"],
                    "word": entry["word"],
                    "points": entry["points"],
                }
            )
        body = self._store_discrim_session(full_items, quiz)
        body["meta"] = {"count": len(quiz), "kind": "warmup"}
        return body

    def discrim_review_session(
        self, seed: int | None = None
    ) -> dict[str, Any]:
        """错题复习：今日到期词建会话（一次洗牌固定顺序，重进不换序）。"""
        quiz, full_items, meta = self.discrim_progress().take_review_pass(
            self.discrim_pool_map(), seed=seed
        )
        body = self._store_discrim_session(full_items, quiz)
        body["meta"] = meta
        return body

    def discrim_review_result(
        self,
        session_id: str,
        item_id: str,
        correct: bool,
        had_wrong_this_round: bool,
    ) -> dict[str, Any]:
        """复习单词语结果：答错记数等复现；答对按本轮是否答错过前进或重置。"""
        session = self._discrim_sessions.get(session_id)
        if session is None:
            raise KeyError(f"unknown discrim session: {session_id}")
        if not any(item["item_id"] == item_id for item in session["items"]):
            raise KeyError(f"item not in discrim session: {item_id}")
        progress = self.discrim_progress()
        result = progress.record_review_result(
            item_id, correct, had_wrong_this_round=had_wrong_this_round
        )
        progress.save()
        return result

    def discrim_seed_mistakes(self, item_ids: list[str]) -> dict[str, Any]:
        """旧版错题本迁移：把词 id 列表并入复习系统（明天到期）。"""
        progress = self.discrim_progress()
        seeded = progress.seed_mistakes(item_ids)
        progress.save()
        return {
            "seeded": seeded,
            "due_today": len(progress.due_ids()),
            "pending": progress.pending_review_count(),
        }

    def discrim_judge(
        self,
        session_id: str,
        item_id: str,
        answers: list[str],
    ) -> dict[str, Any]:
        session = self._discrim_sessions.get(session_id)
        if session is None:
            raise KeyError(f"unknown discrim session: {session_id}")
        entry = next(
            (item for item in session["items"] if item["item_id"] == item_id),
            None,
        )
        if entry is None:
            raise KeyError(f"item not in discrim session: {item_id}")
        results = judge_answer(entry["points"], answers)
        return {
            "item_id": item_id,
            "results": results,
            "all_correct": all(result["correct"] for result in results),
        }

    # ---- warmup ----------------------------------------------------------

    def start_warmup(self) -> None:
        with self._warm_lock:
            if self._warm_started:
                return
            self._warm_started = True
        thread = threading.Thread(
            target=self._warm,
            name="pth-prototype-warmup",
            daemon=True,
        )
        thread.start()

    def _warm(self) -> None:
        try:
            items = self.items()
            profiles = self.profiles()
            universe = _universe_from_items(items)
            for profile in profiles.values():
                if profile.id in self._availability:
                    continue
                result = compute_availability(items, [profile], universe)["profiles"][0]
                with self._warm_lock:
                    self._availability[profile.id] = result
            self._ready = True
        except Exception as exc:  # noqa: BLE001 - surfaced through /api/health
            self._warm_error = f"{type(exc).__name__}: {exc}"

    # ---- API operations ---------------------------------------------------

    def menu(self) -> dict[str, Any]:
        known = set(self.profiles())
        categories = [
            {
                "id": category["id"],
                "label": category["label"],
                "items": [
                    item
                    for item in category["items"]
                    if item["profile_id"] in known
                ],
            }
            for category in PROFILE_MENU
        ]
        categories = [c for c in categories if c["items"]]
        return {
            "categories": categories,
            "durations": list(self.config().allowed_duration_minutes),
            "default_duration_minutes": DEFAULT_DURATION_MINUTES,
            "profile_count": len(known),
        }

    def focus_home(self) -> dict[str, Any]:
        known = set(self.profiles())
        entries = [
            entry for entry in FOCUS_ENTRIES if entry["profile_id"] in known
        ]
        sentence = self.sentence_home()
        discrim = self.discrim_home()
        return {
            "app_name": "前后鼻音专项训练",
            "tagline": "听清 · 分清 · 读准",
            "entries": entries,
            "sentence": {
                "available": sentence["available"],
                "total_clips": sentence["total_clips"],
                "articles": sentence["articles"],
                "filter_counts": sentence["filter_counts"],
            },
            "discrim": discrim,
            "durations": [n for n in (3, 5) if n in self.config().allowed_duration_minutes],
            "default_duration_minutes": DEFAULT_DURATION_MINUTES,
        }

    def player_config(self) -> dict[str, Any]:
        config = self.config()
        return {
            "extra_follow_sec": config.extra_follow_sec,
            "min_follow_sec": config.min_follow_sec,
            "transition_sec": config.transition_sec,
            "allowed_duration_minutes": list(config.allowed_duration_minutes),
            "default_duration_minutes": DEFAULT_DURATION_MINUTES,
        }

    def generate_session(
        self,
        profile_id: str,
        duration_minutes: int,
        seed: int | None = None,
        include_finals: list[str] | None = None,
    ) -> dict[str, Any]:
        profile = self.profiles().get(profile_id)
        if profile is None:
            raise KeyError(f"unknown profile: {profile_id}")
        config = self.config()
        if duration_minutes not in config.allowed_duration_minutes:
            raise ValueError(
                "duration_minutes must be one of "
                f"{tuple(config.allowed_duration_minutes)}"
            )
        history = self.history(profile_id)
        session = generate_session_v2(
            profile,
            config,
            self.items(),
            self.availability(profile),
            duration_minutes=duration_minutes,
            practice_repetitions=1,
            auto_advance=True,
            seed=seed,
            history=history,
            include_finals=include_finals,
        )
        history.add_session(
            session["session_id"],
            [entry["item_id"] for entry in session["items"]],
        )
        history.save()
        self._write_session(session)
        return session

    def _write_session(self, session: dict[str, Any]) -> Path:
        path = (
            self.prototype_dir
            / "sessions"
            / session["profile_id"]
            / f"{session['session_id']}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(session, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def clip_path(self, item_id: str, voice: str | None = None) -> Path | None:
        if not ITEM_ID_RE.fullmatch(item_id):
            return None
        with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as connection:
            row = connection.execute(
                """
                SELECT s.clip_path
                FROM segments AS s
                LEFT JOIN excluded_items AS x ON x.item_id = s.item_id
                WHERE s.item_id = ? AND x.item_id IS NULL
                """,
                (item_id,),
            ).fetchone()
        if row is None or not row[0]:
            return None
        stored = Path(str(row[0]))
        candidate = stored if stored.is_absolute() else self.data_root / stored
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self.data_root)
        except ValueError:
            return None
        replacement = self.voice_library.replacement(item_id, "word", resolved, voice)
        if voice is not None:
            return replacement
        return replacement or (resolved if resolved.is_file() else None)

    def record_event(self, event: dict[str, Any]) -> Path:
        log_dir = self.prototype_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        line = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        path = log_dir / "events.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
        return path

    def settle_activity(self, request: "RewardRequest") -> dict[str, Any]:
        """统一结算入口：word / sentence / discrim / review 共用拼豆管道。

        新版口径（100×100 资产基线，详见 achievement_config_v2.json）：
        * 三个正式训练项目平权；标准档统一 600，各档见 tiers 表；
        * 完成不足 20% 不发拼点（不算有效训练、不续 streak、不计三练）；
        * ≥20% 按真实完成比例结算（允许浮点余量，作品推进只取整数颗）；
        * 正确率不影响拼点、答错不扣拼点；无辨音轮次递减、无全对彩蛋；
        * Streak 不发拼点；无每日硬上限；
        * 今日三练：本次结算后三类各完整完成 ≥1 次且当天尚未发放时
          +trio_bonus（客户端上报当日状态，单机原型口径）。
        """
        config = self.achievement_config()

        def trio_flags(activity: str, completed: bool) -> tuple[bool, bool]:
            word = request.word_completed_today or (
                activity == "word" and completed
            )
            sentence = request.sentence_completed_today or (
                activity == "sentence" and completed
            )
            discrim = request.discrim_completed_today or (
                activity == "discrim" and completed
            )
            return (word and sentence and discrim), request.trio_awarded_today

        try:
            if request.activity == "word":
                if (
                    request.planned_duration_minutes is None
                    or request.completion_ratio is None
                ):
                    raise ValueError(
                        "planned_duration_minutes and completion_ratio are "
                        "required for word activity"
                    )
                trio = trio_flags("word", request.completion_ratio >= 1.0)
                return compute_activity_reward(
                    config,
                    "word",
                    request.planned_duration_minutes,
                    request.completion_ratio,
                    streak_days=request.streak_days or 0,
                    trio_eligible=trio[0],
                    trio_awarded_today=trio[1],
                ).to_dict()
            if request.activity == "sentence":
                if (
                    request.sentence_count is None
                    or request.completed_sentence_count is None
                ):
                    raise ValueError(
                        "sentence_count and completed_sentence_count are "
                        "required for sentence activity"
                    )
                if request.completed_sentence_count > request.sentence_count:
                    raise ValueError(
                        "completed_sentence_count must not exceed "
                        "sentence_count"
                    )
                completed = (
                    request.completed_sentence_count >= request.sentence_count
                )
                trio = trio_flags("sentence", completed)
                return compute_activity_reward(
                    config,
                    "sentence",
                    request.sentence_count,
                    request.completed_sentence_count / request.sentence_count,
                    streak_days=request.streak_days or 0,
                    trio_eligible=trio[0],
                    trio_awarded_today=trio[1],
                ).to_dict()
            if request.activity == "discrim":
                if (
                    request.completed_points is None
                    or request.total_points is None
                ):
                    raise ValueError(
                        "completed_points and total_points are required for "
                        "discrim activity"
                    )
                if request.completed_points > request.total_points:
                    raise ValueError(
                        "completed_points must not exceed total_points"
                    )
                completed = request.completed_points >= request.total_points
                trio = trio_flags("discrim", completed)
                return compute_activity_reward(
                    config,
                    "discrim",
                    request.total_points,
                    request.completed_points / request.total_points,
                    streak_days=request.streak_days or 0,
                    trio_eligible=trio[0],
                    trio_awarded_today=trio[1],
                ).to_dict()
            if request.activity == "review":
                # 当天完成全部「今日待复习」的一次性固定奖励（防逐题刷分）
                return compute_review_reward(config).to_dict()
            raise ValueError(f"unknown activity: {request.activity}")
        except ValueError as exc:
            raise ValueError(str(exc)) from exc


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(min_length=1, max_length=100)
    duration_minutes: int = Field(default=DEFAULT_DURATION_MINUTES, ge=1, le=60)
    seed: int | None = Field(default=None, ge=0)
    include_finals: list[str] | None = Field(default=None)

    @field_validator("profile_id")
    @classmethod
    def normalize_profile_id(cls, value: str) -> str:
        return value.strip()

    @field_validator("include_finals")
    @classmethod
    def normalize_finals(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = sorted({str(item).strip() for item in value if str(item).strip()})
        if not cleaned:
            raise ValueError("include_finals must not be empty")
        if len(cleaned) > 50:
            raise ValueError("include_finals too long")
        return cleaned


class SessionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=200)
    profile_id: str = Field(min_length=1, max_length=100)
    duration_minutes: int = Field(ge=1, le=60)
    start_time: str
    end_time: str
    completed_item_count: int = Field(ge=0)
    exit_early: bool
    replay_count: int = Field(default=0, ge=0)
    pause_count: int = Field(default=0, ge=0)
    seed: int | None = None
    item_count: int | None = Field(default=None, ge=0)
    actual_duration_sec: float | None = Field(default=None, ge=0)
    completion_ratio: float | None = Field(default=None, ge=0, le=1)
    beads_awarded: int | None = Field(default=None, ge=0)
    streak_days: int | None = Field(default=None, ge=0)
    streak_bonus_awarded: int | None = Field(default=None, ge=0)


class RewardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity: str = Field(default="word", max_length=20)
    # word（字词，向后兼容：缺省 activity 即走此分支）
    planned_duration_minutes: int | None = Field(default=None, ge=1, le=120)
    completion_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    # sentence（句子）
    sentence_count: int | None = Field(default=None, ge=1, le=100)
    completed_sentence_count: int | None = Field(default=None, ge=0, le=100)
    # discrim（辨音）：按「实际完成判断数 / 目标判断数」结算；
    # 正确率只用于错题记录与复习，不影响拼点（答错不扣拼点）
    completed_points: int | None = Field(default=None, ge=0, le=500)
    total_points: int | None = Field(default=None, ge=1, le=500)
    # 今日三练：客户端上报当天三类完整完成状态与是否已发
    word_completed_today: bool = False
    sentence_completed_today: bool = False
    discrim_completed_today: bool = False
    trio_awarded_today: bool = False
    # streak：仅记录展示用（连续训练天数），不发拼点
    streak_days: int | None = Field(default=None, ge=0, le=36500)


class SentenceSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(default=5, ge=1, le=50)
    filter: str = Field(default="all")
    seed: int | None = Field(default=None, ge=0)
    include_finals: list[str] | None = Field(default=None)
    review: bool = False

    @field_validator("filter")
    @classmethod
    def validate_filter(cls, value: str) -> str:
        value = value.strip()
        if value not in FILTER_MODES:
            raise ValueError(
                f"filter must be one of {tuple(FILTER_MODES)}"
            )
        return value

    @field_validator("include_finals")
    @classmethod
    def validate_finals(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = sorted({str(item).strip() for item in value if str(item).strip()})
        if not cleaned:
            return None
        if len(cleaned) > 16:
            raise ValueError("include_finals too long")
        unknown = [f for f in cleaned if f not in ALL_NASAL_FINALS]
        if unknown:
            raise ValueError(
                f"unknown nasal finals: {', '.join(unknown)}; "
                f"must be one of {', '.join(ALL_NASAL_FINALS)}"
            )
        return cleaned


class SentenceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=200)
    filter: str = Field(default="all", max_length=20)
    start_time: str
    end_time: str
    sentence_count: int = Field(ge=0)
    completed_sentence_count: int = Field(default=0, ge=0)
    exit_early: bool
    replay_count: int = Field(default=0, ge=0)
    pause_count: int = Field(default=0, ge=0)
    actual_duration_sec: float | None = Field(default=None, ge=0)
    beads_awarded: int | None = Field(default=None, ge=0)
    trio_bonus: int | None = Field(default=None, ge=0)


class DiscrimLibrarySessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(default=50, ge=1, le=150)
    seed: int | None = Field(default=None, ge=0)


class DiscrimReviewSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int | None = Field(default=None, ge=0)


class DiscrimWarmupSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_ids: list[str] = Field(min_length=1, max_length=150)


class DiscrimResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=200)
    item_id: str = Field(min_length=1, max_length=50)
    correct: bool


class DiscrimReviewResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=200)
    item_id: str = Field(min_length=1, max_length=50)
    correct: bool
    had_wrong_this_round: bool = False


class DiscrimSeedMistakesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_ids: list[str] = Field(min_length=1, max_length=300)


class DiscrimAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=200)
    item_id: str = Field(min_length=1, max_length=50)
    answers: list[str] = Field(min_length=1, max_length=8)

    @field_validator("answers")
    @classmethod
    def validate_answers(cls, value: list[str]) -> list[str]:
        unknown = [answer for answer in value if answer not in VALID_ANSWERS]
        if unknown:
            raise ValueError(
                f"answers must be one of {sorted(VALID_ANSWERS)}, got {unknown}"
            )
        return value


class DiscrimEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=200)
    source: str = Field(default="library", max_length=20)
    start_time: str
    end_time: str
    exit_early: bool
    item_count: int = Field(ge=0)
    point_count: int = Field(ge=0)
    correct_points: int = Field(ge=0)
    wrong_points: int = Field(ge=0)
    perfect_words: int = Field(ge=0)
    consecutive_peak: int = Field(ge=0)
    penalty: int = Field(ge=0)
    actual_duration_sec: float = Field(ge=0)
    seed: int | None = None
    beads_awarded: int | None = Field(default=None, ge=0)
    trio_bonus: int | None = Field(default=None, ge=0)


def create_app(
    data_root: str | Path,
    generator_dir: str | Path | None = None,
    prototype_dir: str | Path | None = None,
    db_path: str | Path | None = None,
    phonology_db: str | Path | None = None,
    *,
    items: list[Any] | None = None,
    profiles: list[V2Profile] | None = None,
    config: GeneratorConfig | None = None,
    discrim_config: dict[str, Any] | None = None,
    cloud_assessment: bool = False,
) -> FastAPI:
    """Create the local prototype app (loopback-only usage)."""

    runtime = PrototypeRuntime(
        data_root,
        generator_dir=generator_dir,
        prototype_dir=prototype_dir,
        db_path=db_path,
        phonology_db=phonology_db,
        items=items,
        profiles=profiles,
        config=config,
        discrim_config=discrim_config,
    )
    static_dir = STATIC_DIR
    if not static_dir.is_dir():
        raise PrototypeAppError(f"prototype static assets missing: {static_dir}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime.start_warmup()
        yield
        await app.state.reading_coach.shutdown()

    app = FastAPI(
        title="pth-corpus Mandarin practice prototype",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.runtime = runtime
    assessment = AssessmentService(runtime.data_root)
    assessment.cloud_enabled = cloud_assessment
    app.state.assessment = assessment
    coach = ReadingCoach(assessment, runtime.prototype_dir)
    app.state.reading_coach = coach
    app.mount("/assets", StaticFiles(directory=str(static_dir)), name="prototype-assets")

    @app.middleware("http")
    async def no_store_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", response_class=FileResponse)
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html", media_type="text/html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "ready": runtime._ready,
            "profile_count": len(runtime.profiles()),
            "warm_error": runtime._warm_error,
        }

    @app.get("/api/profiles")
    def profiles_menu() -> dict[str, Any]:
        return runtime.menu()

    @app.get("/api/home")
    def focus_home() -> dict[str, Any]:
        return runtime.focus_home()

    @app.get("/api/calibration")
    def calibration() -> dict[str, Any]:
        return {"groups": runtime.calibration_groups()}

    @app.get("/api/achievement")
    def achievement() -> dict[str, Any]:
        return {
            "achievement_config": runtime.achievement_config().to_dict(),
            "artworks": [
                artwork.to_dict() for artwork in runtime.artworks()
            ],
        }

    @app.post("/api/achievement/settle")
    def settle_reward(request: RewardRequest) -> dict[str, Any]:
        try:
            return runtime.settle_activity(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/config")
    def player_config() -> dict[str, Any]:
        return runtime.player_config()

    @app.get("/api/voice-library")
    def voice_library_status() -> dict[str, Any]:
        return runtime.voice_library.status()

    @app.get("/api/assessment/status")
    def assessment_status() -> dict[str, Any]:
        return assessment.status()

    @app.get("/api/reading/session/{session_id}")
    def reading_summary(session_id: str) -> dict:
        if not SAFE_ID.fullmatch(session_id):
            raise HTTPException(400, "invalid session")
        return coach.summary(session_id)

    @app.get("/api/reading/review")
    def reading_review() -> dict:
        weak = coach.weak_items()
        sessions = list(dict.fromkeys(r["session_id"] for r in reversed(coach.records())))[:12]
        summaries = [coach.summary(s) for s in sessions]
        return {"weak": weak[:30], "diagnostics_ready": coach.nasal_review_enabled,
                "sessions": summaries, "retry_items": coach.retry_items()[-12:]}

    @app.post("/api/reading/attempts/{kind}/{reference_id}", status_code=202)
    async def submit_reading(kind: str, reference_id: str, request: Request,
                             attempt_id: str, session_id: str, pass_no: int = 1) -> dict:
        if kind not in ("word", "sentence") or not SAFE_ID.fullmatch(attempt_id) or not SAFE_ID.fullmatch(session_id):
            raise HTTPException(400, "invalid reading request")
        if assessment.disabled or not assessment.cloud_enabled:
            raise HTTPException(503, "assessment disabled")
        if kind == "sentence":
            row = next((r for r in runtime.sentence_pool() if r["sentence_id"] == reference_id), None)
            if not row:
                raise HTTPException(404, "reference not found")
            text = row.get("spoken_text", row["text"])
            features = row if plain(text) == plain(row["text"]) else score_sentence(text)
        else:
            item = next((r for r in runtime.items() if r.item_id == reference_id), None)
            if not item:
                raise HTTPException(404, "reference not found")
            text = item.word_raw
            features = score_sentence(text)
            if len(plain(text)) == len(item.syllables):
                features["final_seq"] = " ".join(s.final_canonical for s in item.syllables)
                syllables = re.split(r"[-\s]+", item.pinyin_nfc.strip())
                if len(syllables) == len(item.syllables):
                    features["pinyin_seq"] = " ".join(syllables)
        targets = [{"position": i, "text": ch, "pinyin": py, "final": final}
                   for i, (ch, py, final) in enumerate(zip(plain(text), features["pinyin_seq"].split(), features["final_seq"].split()))
                   if final in NASALS]
        if len(plain(text)) != len(features["final_seq"].split()):
            targets = []  # mixed scripts/numerals need explicit alignment, never zip guesses
        audio = bytearray()
        async for chunk in request.stream():
            audio.extend(chunk)
            if len(audio) > 1_920_100:
                raise HTTPException(413, "recording too large")
        try:
            return coach.submit(attempt_id=attempt_id, session_id=session_id, kind=kind,
                                reference_id=reference_id, text=text, targets=targets,
                                audio=bytes(audio), pass_no=pass_no)
        except AssessmentError as exc:
            return {"status": exc.status, "message": str(exc)}

    @app.post("/api/assessment/{kind}/{reference_id}")
    async def assess_reading(kind: str, reference_id: str, request: Request, attempt_id: str) -> dict:
        if assessment.disabled or not assessment.cloud_enabled:
            raise HTTPException(503, "assessment disabled")
        if kind not in ("word", "sentence") or not re.fullmatch(r"[a-zA-Z0-9-]{8,100}", attempt_id):
            raise HTTPException(400, "invalid assessment request")
        if kind == "sentence":
            row = next((r for r in runtime.sentence_pool() if r["sentence_id"] == reference_id), None)
            text = row.get("spoken_text", row["text"]) if row else None
        else:
            item = next((r for r in runtime.items() if r.item_id == reference_id), None)
            text = item.word_raw if item else None
        if not text:
            raise HTTPException(404, "reference not found")
        audio = bytearray()
        async for chunk in request.stream():
            audio.extend(chunk)
            if len(audio) > 1_920_100:
                raise HTTPException(413, "recording too large")
        try:
            return await assessment.assess(attempt_id, text, bytes(audio))
        except AssessmentError as exc:
            return {"status": exc.status, "message": str(exc)}

    @app.post("/api/sessions", status_code=201)
    def create_session(request: SessionRequest) -> dict[str, Any]:
        try:
            return runtime.generate_session(
                request.profile_id,
                request.duration_minutes,
                seed=request.seed,
                include_finals=request.include_finals,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/clips/{item_id}")
    def clip_media(item_id: str, voice: str | None = None) -> FileResponse:
        path = runtime.clip_path(item_id, voice)
        if path is None:
            raise HTTPException(status_code=404, detail="clip not found")
        return FileResponse(path, media_type="audio/wav")

    @app.post("/api/events", status_code=201)
    def record_event(event: SessionEvent) -> dict[str, Any]:
        path = runtime.record_event(event.model_dump())
        return {"status": "recorded", "log": str(path)}

    @app.get("/api/sentence/home")
    def sentence_home() -> dict[str, Any]:
        return runtime.sentence_home()

    @app.post("/api/sentence/session", status_code=201)
    def sentence_session(request: SentenceSessionRequest) -> dict[str, Any]:
        try:
            weak = coach.weak_items() if request.review else []
            if request.review and not weak:
                raise HTTPException(409, "暂时没有需要复练的朗读记录")
            session = runtime.sentence_session(
                request.count,
                "all" if request.review else request.filter,
                seed=request.seed,
                include_finals=sorted({w["final"] for w in weak}) if request.review else request.include_finals,
            )
            if request.review:
                # Revisit the original sentence before transferring to other contexts.
                references = {w["reference_id"] for w in weak if w["kind"] == "sentence"}
                originals = [runtime.sentence_item_payload(r) for r in runtime.sentence_pool() if r["sentence_id"] in references]
                seen = set()
                items = []
                for item in originals + session["items"]:
                    if item["sentence_id"] not in seen:
                        seen.add(item["sentence_id"])
                        items.append(item)
                session["items"] = items[:request.count]
                session["count"] = len(session["items"])
                session["review"] = True
            return session
        except PrototypeAppError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/sentence/count")
    def sentence_custom_count(
        request: SentenceSessionRequest,
    ) -> dict[str, Any]:
        try:
            return runtime.sentence_custom_count(request.include_finals or [])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/sentence/clips/{sentence_id}")
    def sentence_clip_media(sentence_id: str, voice: str | None = None) -> FileResponse:
        path = runtime.sentence_clip_path(sentence_id, voice)
        if path is None:
            raise HTTPException(status_code=404, detail="clip not found")
        return FileResponse(path, media_type="audio/wav")

    @app.post("/api/sentence/events", status_code=201)
    def record_sentence_event(event: SentenceEvent) -> dict[str, Any]:
        payload = dict(event.model_dump())
        payload["type"] = "sentence"
        path = runtime.record_event(payload)
        return {"status": "recorded", "log": str(path)}

    @app.get("/api/discrim/home")
    def discrim_home() -> dict[str, Any]:
        return runtime.discrim_home()

    @app.get("/api/discrim/state")
    def discrim_state() -> dict[str, Any]:
        return runtime.discrim_state()

    @app.post("/api/discrim/library/session", status_code=201)
    def discrim_library_session(
        request: DiscrimLibrarySessionRequest,
    ) -> dict[str, Any]:
        try:
            return runtime.discrim_library_session(request.count, seed=request.seed)
        except PrototypeAppError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/discrim/library/result")
    def discrim_library_result(request: DiscrimResultRequest) -> dict[str, Any]:
        try:
            return runtime.discrim_library_result(
                request.session_id, request.item_id, request.correct
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/discrim/warmup/session", status_code=201)
    def discrim_warmup_session(
        request: DiscrimWarmupSessionRequest,
    ) -> dict[str, Any]:
        try:
            return runtime.discrim_warmup_session(request.item_ids)
        except PrototypeAppError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/discrim/review/session", status_code=201)
    def discrim_review_session(
        request: DiscrimReviewSessionRequest | None = None,
    ) -> dict[str, Any]:
        seed = request.seed if request is not None else None
        try:
            return runtime.discrim_review_session(seed=seed)
        except PrototypeAppError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/discrim/review/result")
    def discrim_review_result(request: DiscrimReviewResultRequest) -> dict[str, Any]:
        try:
            return runtime.discrim_review_result(
                request.session_id,
                request.item_id,
                request.correct,
                request.had_wrong_this_round,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/discrim/seed-mistakes")
    def discrim_seed_mistakes(request: DiscrimSeedMistakesRequest) -> dict[str, Any]:
        return runtime.discrim_seed_mistakes(request.item_ids)

    @app.post("/api/discrim/answer")
    def discrim_answer(request: DiscrimAnswerRequest) -> dict[str, Any]:
        try:
            return runtime.discrim_judge(
                request.session_id, request.item_id, request.answers
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/discrim/events", status_code=201)
    def record_discrim_event(event: DiscrimEvent) -> dict[str, Any]:
        payload = dict(event.model_dump())
        payload["type"] = "discrim"
        path = runtime.record_event(payload)
        return {"status": "recorded", "log": str(path)}

    return app
