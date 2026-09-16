"""v2 profile schema and JSON loading (structure-first training rules)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models import read_json


@dataclass
class V2Bucket:
    id: str
    label: str
    target_ratio: float
    rule: dict[str, Any]
    role: str = "core"
    pair_specs: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "V2Bucket":
        return cls(
            id=data["id"],
            label=data.get("label", data["id"]),
            target_ratio=float(data["target_ratio"]),
            rule=data.get("rule", {}),
            role=data.get("role", "core"),
            pair_specs=list(data.get("pair_specs", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "target_ratio": self.target_ratio,
            "rule": self.rule,
            "role": self.role,
            "pair_specs": self.pair_specs,
        }


@dataclass
class V2Profile:
    id: str
    name: str
    dimension: str  # initial | final | tone
    mode: str  # single_focus | contrast | special_mix | comprehensive
    target_sets: dict[str, list[str]]
    buckets: list[V2Bucket]
    allow_other: bool = True
    candidate_rule: dict[str, Any] | None = None
    flag_rule: dict[str, Any] | None = None
    scarcity: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    @property
    def target_value_union(self) -> list[str]:
        seen: list[str] = []
        for values in self.target_sets.values():
            for v in values:
                if v not in seen:
                    seen.append(v)
        return seen

    @property
    def target_set_names(self) -> list[str]:
        return list(self.target_sets)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "V2Profile":
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            dimension=data["dimension"],
            mode=data.get("mode", "single_focus"),
            target_sets={
                k: list(v) for k, v in data.get("target_sets", {}).items()
            },
            buckets=[
                V2Bucket.from_dict(b) for b in data.get("buckets", [])
            ],
            allow_other=bool(data.get("allow_other", True)),
            candidate_rule=data.get("candidate_rule"),
            flag_rule=data.get("flag_rule"),
            scarcity=dict(data.get("scarcity", {})),
            notes=data.get("notes", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "dimension": self.dimension,
            "mode": self.mode,
            "target_sets": self.target_sets,
            "buckets": [b.to_dict() for b in self.buckets],
            "allow_other": self.allow_other,
            "candidate_rule": self.candidate_rule,
            "flag_rule": self.flag_rule,
            "scarcity": self.scarcity,
            "notes": self.notes,
        }


def load_v2_profiles(path: Path) -> list[V2Profile]:
    data = read_json(path)
    return [V2Profile.from_dict(d) for d in data]
