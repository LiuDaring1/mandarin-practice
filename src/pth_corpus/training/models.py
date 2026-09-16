"""Data models and JSON persistence for the training session generator."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

GENERATOR_VERSION = "v1.0"
DEFAULT_SEED = 20260808

SOURCE_DATA_VERSION = "formal_corpus_2026-08-08_16156"
PHONOLOGY_RULES_VERSION = "v1.0.0"

PROFILES_FILENAME = "training_profiles_v1.json"
CONFIG_FILENAME = "generator_config_v1.json"
CANDIDATE_STATS_FILENAME = "candidate_pool_stats_v1.json"
CANDIDATE_REPORT_FILENAME = "CANDIDATE_POOL_REPORT_V1.md"
GENERATOR_STATS_FILENAME = "generator_stats_v1.json"
GENERATOR_REPORT_FILENAME = "GENERATOR_REPORT_V1.md"


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


@dataclass
class GeneratorConfig:
    """Versioned generator parameters (mirrors generator_config_v1.json)."""

    version: str
    top_k: int = 50
    max_attempts: int = 12
    random_jitter: float = 0.05
    max_same_target_consecutive: int = 2
    max_same_position_consecutive: int = 3
    max_same_length_consecutive: int = 4
    max_same_tone_pattern_consecutive: int = 3
    extra_follow_sec: float = 0.8
    min_follow_sec: float = 1.8
    transition_sec: float = 0.3
    duration_tolerance_ratio: float = 0.05
    weight_coverage: float = 1.0
    weight_pattern: float = 1.0
    weight_group: float = 1.0
    weight_position: float = 0.8
    weight_length: float = 0.5
    weight_tone_pattern: float = 0.4
    weight_purity: float = 0.15
    weight_overshoot_penalty: float = 0.5
    history_window_days: int = 7
    history_window_sessions: int = 7
    history_penalty: float = 0.6
    allowed_duration_minutes: tuple[int, ...] = (5, 10)
    allowed_practice_repetitions: tuple[int, ...] = (1, 2)
    benchmark_seeds_5m: tuple[int, ...] = (20260801, 20260802, 20260803)
    benchmark_seeds_10m: tuple[int, ...] = (20260804, 20260805, 20260806)
    benchmark_seeds_20m: tuple[int, ...] = (20260807, 20260808)
    benchmark_matrix: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GeneratorConfig":
        allowed = data.get("allowed_duration_minutes", (5, 10))
        return cls(
            version=data["version"],
            top_k=int(data.get("top_k", 50)),
            max_attempts=int(data.get("max_attempts", 12)),
            random_jitter=float(data.get("random_jitter", 0.05)),
            max_same_target_consecutive=int(
                data.get("max_same_target_consecutive", 2)
            ),
            max_same_position_consecutive=int(
                data.get("max_same_position_consecutive", 3)
            ),
            max_same_length_consecutive=int(
                data.get("max_same_length_consecutive", 4)
            ),
            max_same_tone_pattern_consecutive=int(
                data.get("max_same_tone_pattern_consecutive", 3)
            ),
            extra_follow_sec=float(data.get("extra_follow_sec", 0.8)),
            min_follow_sec=float(data.get("min_follow_sec", 1.8)),
            transition_sec=float(data.get("transition_sec", 0.3)),
            duration_tolerance_ratio=float(
                data.get("duration_tolerance_ratio", 0.05)
            ),
            weight_coverage=float(data.get("weight_coverage", 1.0)),
            weight_pattern=float(data.get("weight_pattern", 1.0)),
            weight_group=float(data.get("weight_group", 1.0)),
            weight_position=float(data.get("weight_position", 0.8)),
            weight_length=float(data.get("weight_length", 0.5)),
            weight_tone_pattern=float(data.get("weight_tone_pattern", 0.4)),
            weight_purity=float(data.get("weight_purity", 0.15)),
            weight_overshoot_penalty=float(
                data.get("weight_overshoot_penalty", 0.5)
            ),
            history_window_days=int(data.get("history_window_days", 7)),
            history_window_sessions=int(
                data.get("history_window_sessions", 7)
            ),
            history_penalty=float(data.get("history_penalty", 0.6)),
            allowed_duration_minutes=tuple(int(v) for v in allowed),
            allowed_practice_repetitions=tuple(
                int(v)
                for v in data.get("allowed_practice_repetitions", (1, 2))
            ),
            benchmark_seeds_5m=tuple(
                int(v) for v in data.get("benchmark_seeds_5m", (20260801, 20260802, 20260803))
            ),
            benchmark_seeds_10m=tuple(
                int(v) for v in data.get("benchmark_seeds_10m", (20260804, 20260805, 20260806))
            ),
            benchmark_seeds_20m=tuple(
                int(v) for v in data.get("benchmark_seeds_20m", (20260807, 20260808))
            ),
            benchmark_matrix=dict(data.get("benchmark_matrix", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "top_k": self.top_k,
            "max_attempts": self.max_attempts,
            "random_jitter": self.random_jitter,
            "max_same_target_consecutive": self.max_same_target_consecutive,
            "max_same_position_consecutive": self.max_same_position_consecutive,
            "max_same_length_consecutive": self.max_same_length_consecutive,
            "max_same_tone_pattern_consecutive": self.max_same_tone_pattern_consecutive,
            "extra_follow_sec": self.extra_follow_sec,
            "min_follow_sec": self.min_follow_sec,
            "transition_sec": self.transition_sec,
            "duration_tolerance_ratio": self.duration_tolerance_ratio,
            "weight_coverage": self.weight_coverage,
            "weight_pattern": self.weight_pattern,
            "weight_group": self.weight_group,
            "weight_position": self.weight_position,
            "weight_length": self.weight_length,
            "weight_tone_pattern": self.weight_tone_pattern,
            "weight_purity": self.weight_purity,
            "weight_overshoot_penalty": self.weight_overshoot_penalty,
            "history_window_days": self.history_window_days,
            "history_window_sessions": self.history_window_sessions,
            "history_penalty": self.history_penalty,
            "allowed_duration_minutes": list(self.allowed_duration_minutes),
            "allowed_practice_repetitions": list(
                self.allowed_practice_repetitions
            ),
            "benchmark_seeds_5m": list(self.benchmark_seeds_5m),
            "benchmark_seeds_10m": list(self.benchmark_seeds_10m),
            "benchmark_seeds_20m": list(self.benchmark_seeds_20m),
            "benchmark_matrix": self.benchmark_matrix,
        }


@dataclass
class BalanceDimension:
    """One balanced dimension tracked by a training profile."""

    id: str
    label: str
    kind: str  # initials | finals | tones | resonances | structures | nasal_types | flags | lengths
    values: list[str]
    groups: dict[str, list[str]] = field(default_factory=dict)
    target_group_shares: dict[str, float] = field(default_factory=dict)
    primary: bool = False
    final_filter: dict[str, str] = field(default_factory=dict)
    flags: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BalanceDimension":
        return cls(
            id=data["id"],
            label=data.get("label", data["id"]),
            kind=data["kind"],
            values=list(data.get("values", [])),
            groups={k: list(v) for k, v in data.get("groups", {}).items()},
            target_group_shares={
                k: float(v) for k, v in data.get("target_group_shares", {}).items()
            },
            primary=bool(data.get("primary", False)),
            final_filter=dict(data.get("final_filter", {})),
            flags={k: str(v) for k, v in data.get("flags", {}).items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "values": self.values,
            "groups": self.groups,
            "target_group_shares": self.target_group_shares,
            "primary": self.primary,
            "final_filter": self.final_filter,
            "flags": self.flags,
        }


@dataclass
class PositionDimension:
    """How target-syllable positions are derived for a profile."""

    id: str
    label: str
    kind: str
    values: list[str]
    final_filter: dict[str, str] = field(default_factory=dict)
    flags: dict[str, str] = field(default_factory=dict)
    positions_column: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PositionDimension":
        return cls(
            id=data["id"],
            label=data.get("label", data["id"]),
            kind=data["kind"],
            values=list(data.get("values", [])),
            final_filter=dict(data.get("final_filter", {})),
            flags={k: str(v) for k, v in data.get("flags", {}).items()},
            positions_column=data.get("positions_column"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "values": self.values,
            "final_filter": self.final_filter,
            "flags": self.flags,
            "positions_column": self.positions_column,
        }


@dataclass
class TrainingProfile:
    """A training target: hard candidate rule + soft balance dimensions."""

    id: str
    name: str
    aliases: list[str]
    candidate_rule: dict[str, Any]
    balance_dimensions: list[BalanceDimension]
    position_dimension: PositionDimension | None = None
    purity: bool = True
    purity_weight: float | None = None
    purity_target_shares: dict[str, float] = field(default_factory=dict)
    track_tone_pattern: bool = True
    track_word_length: bool = True
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrainingProfile":
        pos = data.get("position_dimension")
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            aliases=list(data.get("aliases", [])),
            candidate_rule=data["candidate_rule"],
            balance_dimensions=[
                BalanceDimension.from_dict(d) for d in data.get("balance_dimensions", [])
            ],
            position_dimension=PositionDimension.from_dict(pos) if pos else None,
            purity=bool(data.get("purity", True)),
            purity_weight=(
                float(data["purity_weight"])
                if data.get("purity_weight") is not None
                else None
            ),
            purity_target_shares={
                k: float(v)
                for k, v in data.get("purity_target_shares", {}).items()
            },
            track_tone_pattern=bool(data.get("track_tone_pattern", True)),
            track_word_length=bool(data.get("track_word_length", True)),
            notes=data.get("notes", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "aliases": self.aliases,
            "candidate_rule": self.candidate_rule,
            "balance_dimensions": [
                d.to_dict() for d in self.balance_dimensions
            ],
            "position_dimension": (
                self.position_dimension.to_dict()
                if self.position_dimension
                else None
            ),
            "purity": self.purity,
            "purity_weight": self.purity_weight,
            "purity_target_shares": self.purity_target_shares,
            "track_tone_pattern": self.track_tone_pattern,
            "track_word_length": self.track_word_length,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class SyllableInfo:
    index: int  # 1-based
    initial: str
    final_canonical: str
    final_structure: str
    nasal_type: str
    compound_resonance: str
    tone: int


@dataclass
class Item:
    """One available corpus item enriched with phonology feature sets."""

    item_id: str
    word_raw: str
    pinyin_nfc: str
    table_kind: str
    global_seq: int
    syllable_count: int
    length_bucket: str
    initial_sequence: str
    final_sequence: str
    tone_pattern_lexical: str
    has_neutral_tone: bool
    has_erhua: bool
    has_adjacent_33: bool
    has_flat_initial: bool
    has_retroflex_initial: bool
    has_n: bool
    has_l: bool
    has_jqx: bool
    has_front_nasal: bool
    has_back_nasal: bool
    has_compound_final: bool
    has_third_tone: bool
    contains_yi: bool
    contains_bu: bool
    neutral_positions: str | None
    erhua_position: str | None
    clip_path: str
    clip_duration_ms: int
    syllables: list[SyllableInfo]
    initials: frozenset[str]
    finals: frozenset[str]
    front_nasal_finals: frozenset[str]
    back_nasal_finals: frozenset[str]
    compound_finals: frozenset[str]
    final_structures: frozenset[str]
    nasal_types: frozenset[str]
    compound_resonances: frozenset[str]
    tone_values: frozenset[str]

    @property
    def clip_duration_sec(self) -> float:
        return self.clip_duration_ms / 1000.0

    def to_session_entry(self, order: int, target_features: dict[str, Any],
                         duration_sec: float, score: float,
                         reason_summary: str) -> dict[str, Any]:
        return {
            "order": order,
            "item_id": self.item_id,
            "word": self.word_raw,
            "pinyin": self.pinyin_nfc,
            "clip_path": self.clip_path,
            "clip_duration_ms": self.clip_duration_ms,
            "estimated_item_duration_sec": round(duration_sec, 3),
            "target_features": target_features,
            "syllable_count": self.syllable_count,
            "tone_pattern": self.tone_pattern_lexical,
            "selection_score": round(score, 6),
            "selection_weight": round(max(score, 1e-9), 6),
            "selection_reason_summary": reason_summary,
        }


def load_profiles(path: Path) -> list[TrainingProfile]:
    data = read_json(path)
    return [TrainingProfile.from_dict(d) for d in data]


def load_config(path: Path) -> GeneratorConfig:
    return GeneratorConfig.from_dict(read_json(path))


def save_profiles(profiles: list[TrainingProfile], path: Path) -> None:
    write_json([p.to_dict() for p in profiles], path)


def save_config(config: GeneratorConfig, path: Path) -> None:
    write_json(config.to_dict(), path)
