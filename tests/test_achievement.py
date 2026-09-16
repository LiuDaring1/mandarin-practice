"""Tests for the decoupled achievement / perler-bead reward system (v2 100×100)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pth_corpus.achievement import (
    AchievementConfig,
    Artwork,
    compute_activity_reward,
    load_artwork_catalog,
)


PROTOTYPE_DATA = Path(__file__).resolve().parents[1] / "src" / "pth_corpus" / "prototype_data"


def _config() -> AchievementConfig:
    return AchievementConfig.from_dict(
        json.loads(
            (PROTOTYPE_DATA / "achievement_config_v2.json").read_text(
                encoding="utf-8"
            )
        )
    )


def test_duration_rewards_are_config_driven():
    config = _config()
    assert config.minimum_completion_ratio == 0.2
    assert config.tier_value("word", 5) == 600
    assert config.tier_value("word", 10) == 1200
    assert config.tier_value("sentence", 10) == 600
    assert config.tier_value("sentence", 15) == 900
    assert config.tier_value("discrim", 50) == 300
    assert config.tier_value("discrim", 100) == 600
    assert config.tier_value("discrim", 150) == 900
    assert compute_activity_reward(config, "word", 10, 1.0).total_beads == 1200
    assert compute_activity_reward(config, "word", 5, 1.0).total_beads == 600
    # 旧档位不存在
    assert config.tier_value("word", 15) is None
    assert config.tier_value("sentence", 5) is None


def test_partial_completion_scales_the_base_reward():
    config = _config()
    half = compute_activity_reward(config, "word", 10, 0.5)
    assert half.eligible
    assert half.total_beads == 600
    assert half.trio_bonus == 0


def test_below_threshold_earns_nothing():
    config = _config()
    tiny = compute_activity_reward(config, "word", 10, 0.1)
    assert not tiny.eligible
    assert tiny.total_beads == 0


def test_unknown_tier_is_rejected():
    with pytest.raises(ValueError):
        compute_activity_reward(_config(), "word", 3, 1.0)


def test_artwork_catalog_is_valid_mic_plus_series():
    artworks = load_artwork_catalog(
        PROTOTYPE_DATA / "artwork_catalog_v2.json"
    )
    assert [a.artwork_id for a in artworks] == [
        "mic",
        "cat1",
        "cat2",
        "cat3",
        "cat4",
        "cat5",
        "cat6",
    ]
    mic = artworks[0]
    assert mic.series_id is None and mic.kind == "beginner"
    assert mic.active_bead_count == 58
    cats = artworks[1:]
    assert all(a.series_id == "cats_v1" and a.kind == "series" for a in cats)
    assert [a.active_bead_count for a in cats] == [
        4343, 4232, 3739, 3871, 4100, 4119,
    ]
    assert sum(a.active_bead_count for a in cats) == 24404
    for artwork in artworks:
        assert len(artwork.grid) == artwork.height
        assert all(len(row) == artwork.width for row in artwork.grid)
        assert len(artwork.fill_order) == artwork.active_bead_count
        assert all(
            cell is None or (isinstance(cell, str) and cell.startswith("#"))
            for row in artwork.grid
            for cell in row
        )
    # 无解锁规则字段：全部明牌可选（旧 starter / after_completions 移除）
    for artwork in artworks:
        assert not hasattr(artwork, "unlock_rule")


def test_artwork_validation_rejects_bad_grids():
    base = {
        "id": "x",
        "series_id": "cats_v1",
        "kind": "series",
        "name": "x",
        "tagline": "",
        "width": 2,
        "height": 2,
        "grid": [[None, "#AABBCC"], ["#112233", None]],
        "palette": {"#AABBCC": 1, "#112233": 1},
        "active_bead_count": 2,
        "fill_order": [[0, 1], [1, 0]],
        "completed": False,
    }
    artwork = Artwork.from_dict(base)
    assert artwork.active_bead_count == 2

    bad_count = {**base, "active_bead_count": 3}
    with pytest.raises(ValueError):
        Artwork.from_dict(bad_count)

    bad_cell = {
        **base,
        "grid": [[None, "AABBCC"], ["#112233", None]],  # 缺 #
    }
    with pytest.raises(ValueError):
        Artwork.from_dict(bad_cell)

    bad_order_len = {**base, "fill_order": [[0, 1]]}
    with pytest.raises(ValueError):
        Artwork.from_dict(bad_order_len)

    bad_order_empty = {
        **base,
        "fill_order": [[0, 1], [0, 0]],  # (0,0) 是 null 格
    }
    with pytest.raises(ValueError):
        Artwork.from_dict(bad_order_empty)

    bad_shape = {**base, "width": 3}
    with pytest.raises(ValueError):
        Artwork.from_dict(bad_shape)


def test_catalog_rejects_duplicate_ids():
    import json as _json

    data = _json.loads(
        (PROTOTYPE_DATA / "artwork_catalog_v2.json").read_text(encoding="utf-8")
    )
    duplicate = dict(data)
    duplicate["artworks"] = data["artworks"] + [data["artworks"][1]]
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", encoding="utf-8"
    ) as handle:
        _json.dump(duplicate, handle)
        handle.flush()
        with pytest.raises(ValueError):
            load_artwork_catalog(Path(handle.name))
