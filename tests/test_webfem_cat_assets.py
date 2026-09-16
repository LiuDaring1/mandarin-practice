"""猫猫系列 100×100 Webfem CSV 资产真值回归锁（验收重点，勿改数值）。

真值（交接包 / 新版规则基线 §14-15）：
- 6 张 CSV 均为 100×100；边缘 396/396 格全部为背景色（当前资产为 #35E352）。
- 背景由「边缘多数色 + 4 邻域 flood-fill」识别，命中格转 null；
  其余格全部保留（包括白色猫毛），不得写死删除颜色。
- active_bead_count：cat1=4343 cat2=4232 cat3=3739 cat4=3871 cat5=4100 cat6=4119，
  系列合计 24404。
- active_bead_count 必须能从 grid 重算校验；fill_order 与 grid 解耦且长度一致。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from pth_corpus.achievement import load_artwork_catalog

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "convert_webfem_csv.py"
RAW_DIR = ROOT / "src" / "pth_corpus" / "prototype_data" / "raw_csv" / "cats_v1"
CATALOG_V1 = ROOT / "src" / "pth_corpus" / "prototype_data" / "artwork_catalog_v1.json"
CATALOG_V2 = ROOT / "src" / "pth_corpus" / "prototype_data" / "artwork_catalog_v2.json"

TRUTH = {
    "cat1": {"active": 4343, "bg_cells": 5657, "colors": 20},
    "cat2": {"active": 4232, "bg_cells": 5768, "colors": 15},
    "cat3": {"active": 3739, "bg_cells": 6261, "colors": 9},
    "cat4": {"active": 3871, "bg_cells": 6129, "colors": 21},
    "cat5": {"active": 4100, "bg_cells": 5900, "colors": 11},
    "cat6": {"active": 4119, "bg_cells": 5881, "colors": 13},
}
SERIES_TOTAL = 24404


def _load_module():
    spec = importlib.util.spec_from_file_location("convert_webfem_csv", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def conv():
    return _load_module()


def test_csvs_are_100x100_with_hex_cells(conv):
    for artwork_id in TRUTH:
        grid = conv.read_csv_grid(RAW_DIR / f"{artwork_id}.csv")
        assert len(grid) == 100
        assert all(len(row) == 100 for row in grid)


def test_edge_background_detection_all_396_cells(conv):
    """四条边 396/396 个唯一边缘格全部为边缘多数背景色（当前资产 #35E352）。"""
    for artwork_id in TRUTH:
        grid = conv.read_csv_grid(RAW_DIR / f"{artwork_id}.csv")
        bg = conv.detect_background_candidate(grid)
        edge_cells = [
            grid[r][c]
            for r in range(100)
            for c in range(100)
            if r in (0, 99) or c in (0, 99)
        ]
        assert len(edge_cells) == 396
        assert edge_cells.count(bg) == 396, f"{artwork_id}: {bg} not on all edges"
        # 不硬编码颜色：背景必须是边缘最多色，且 flood-fill 前背景格数 = 真值
        mask = conv.flood_fill_background_mask(grid, bg)
        flooded = sum(map(sum, mask))
        assert flooded == TRUTH[artwork_id]["bg_cells"], artwork_id


def test_flood_fill_counts_match_acceptance_truth(conv):
    """核心验收：6 件 active_bead_count 必须精确等于真值。"""
    for artwork_id, truth in TRUTH.items():
        artwork = conv.convert_csv(RAW_DIR / f"{artwork_id}.csv", artwork_id)
        # 由 grid 重算校验
        recounted = sum(
            1 for row in artwork["grid"] for cell in row if cell is not None
        )
        assert artwork["active_bead_count"] == truth["active"], artwork_id
        assert recounted == truth["active"], artwork_id
    total = sum(truth["active"] for truth in TRUTH.values())
    assert total == SERIES_TOTAL


def test_all_non_background_colors_are_retained_including_white(conv):
    """flood-fill 只删与边缘连通的背景色；其余所有颜色（含白色猫毛）全部保留。"""
    for artwork_id in TRUTH:
        raw = conv.read_csv_grid(RAW_DIR / f"{artwork_id}.csv")
        bg = conv.detect_background_candidate(raw)
        artwork = conv.convert_csv(RAW_DIR / f"{artwork_id}.csv", artwork_id)
        grid_colors = {
            cell for row in artwork["grid"] for cell in row if cell is not None
        }
        raw_non_bg = {cell for row in raw for cell in row if cell != bg}
        assert grid_colors == raw_non_bg, artwork_id
        assert len(artwork["palette"]) == TRUTH[artwork_id]["colors"], artwork_id
    # 白色猫毛在部分资产中以纯白 #FFFFFF 出现，必须保留
    whites = {
        artwork_id: sum(
            1
            for row in conv.convert_csv(RAW_DIR / f"{artwork_id}.csv", artwork_id)["grid"]
            for cell in row
            if cell == "#FFFFFF"
        )
        for artwork_id in TRUTH
    }
    assert whites["cat2"] > 0 and whites["cat3"] > 0 and whites["cat4"] > 0, whites
    assert whites["cat1"] == 0 and whites["cat5"] == 0 and whites["cat6"] == 0, whites


def test_fill_order_is_deterministic_blockwise_and_complete(conv):
    # 6×6：上 2 行 A 色、中 2 行 B 色、下 2 行 C 色，各是一个 12 格连通块
    grid = [
        ["#A" if r < 2 else "#B" if r < 4 else "#C" for _ in range(6)] for r in range(6)
    ]
    positions = [(r, c) for r in range(6) for c in range(6)]
    first = conv.build_fill_order("art", positions, grid)
    second = conv.build_fill_order("art", positions, grid)
    assert first == second  # 同一 grid 永远同序（确定性）
    assert sorted(map(tuple, first)) == positions  # 是同一组坐标的排列
    # 成块浮现：先 A 带整块、再 B 带整块、最后 C 带整块（自上而下）
    colors = [grid[r][c] for r, c in map(tuple, first)]
    assert set(colors[:12]) == {"#A"}
    assert set(colors[12:24]) == {"#B"}
    assert set(colors[24:]) == {"#C"}
    # 块内 BFS 外扩：A 带的第一个格是左上种子 (0,0)
    assert tuple(first[0]) == (0, 0)
    # 顺序由几何+颜色分区决定：不同几何（垂直分割）产出不同顺序；仅换色值不换布局则同序
    grid_vertical = [
        ["#L" if c < 3 else "#R" for c in range(6)] for _ in range(6)
    ]
    other = conv.build_fill_order("art", positions, grid_vertical)
    assert first != other
    grid_recolored = [
        ["#X" if r < 2 else "#Y" if r < 4 else "#Z" for _ in range(6)] for r in range(6)
    ]
    assert conv.build_fill_order("art", positions, grid_recolored) == first


def test_catalog_v2_contains_mic_and_six_cats_with_truth_counts():
    artworks = load_artwork_catalog(CATALOG_V2)
    assert [a.artwork_id for a in artworks] == [
        "mic",
        "cat1",
        "cat2",
        "cat3",
        "cat4",
        "cat5",
        "cat6",
    ]
    assert artworks[0].series_id is None
    assert artworks[0].active_bead_count == 58
    for artwork in artworks[1:]:
        assert artwork.series_id == "cats_v1"
        assert artwork.width == 100 and artwork.height == 100
        assert artwork.active_bead_count == TRUTH[artwork.artwork_id]["active"]
        assert len(artwork.fill_order) == artwork.active_bead_count
        # fill_order 全部指向非 null 格且无重复
        seen = set()
        for row, col in artwork.fill_order:
            assert artwork.grid[row][col] is not None
            assert (row, col) not in seen
            seen.add((row, col))


def test_catalog_v2_series_total_and_metadata():
    data = json.loads(CATALOG_V2.read_text(encoding="utf-8"))
    assert data["version"] == "v2"
    assert data["series"] == [
        {"series_id": "cats_v1", "name": "猫猫系列", "count": 6}
    ]
    cat_artworks = [a for a in data["artworks"] if a["series_id"] == "cats_v1"]
    assert len(cat_artworks) == 6
    total = sum(a["active_bead_count"] for a in cat_artworks)
    assert total == SERIES_TOTAL
    # 背景不写死：grid 中背景格为 null，而非删除颜色
    for artwork in cat_artworks:
        assert all(
            cell is None or (isinstance(cell, str) and cell.startswith("#"))
            for row in artwork["grid"]
            for cell in row
        )


def test_conversion_dry_run_via_build_catalog(conv):
    artworks, reports = conv.build_catalog(RAW_DIR, CATALOG_V1)
    assert [a["id"] for a in artworks] == [
        "mic",
        "cat1",
        "cat2",
        "cat3",
        "cat4",
        "cat5",
        "cat6",
    ]
    for report in reports:
        assert int(report["active_bead_count"]) == TRUTH[report["id"]]["active"]
        assert report["background"] == "#35E352"
