#!/usr/bin/env python3
"""Webfem 100×100 CSV → 内部作品 JSON（猫猫系列首个正式资产）。

规则依据（交接包 AGENT_HANDOFF.md §3 / 新版规则基线 §14）：

1. 校验 CSV 为 100×100，每格 HEX 颜色 `#RRGGBB`（无表头）。
2. 收集四条边所有格（100×100 共 396 个唯一边缘格），取出现次数最多的颜色
   作为 background_candidate（并列时按色值字典序取首个，保证确定性）。
3. 从所有边缘上等于该颜色的格子出发，用 **4 邻域** flood-fill。
4. flood-fill 命中的格子写成 `null`（empty 背景）。
5. 其余所有格子保留原 HEX 颜色，包括白色（白色猫毛必须保留）。
6. active_bead_count = 非 null 格数量，并从 grid 重算自校验。

禁止把背景色写死为 #00FF00 / #35E352：当前 6 张资产被 Webfem 映射为
#35E352 只是资产事实，代码必须采用边缘自动识别。

用法::

    python scripts/convert_webfem_csv.py \
        --csv-dir src/pth_corpus/prototype_data/raw_csv/cats_v1 \
        --catalog-v1 src/pth_corpus/prototype_data/artwork_catalog_v1.json \
        --out src/pth_corpus/prototype_data/artwork_catalog_v2.json \
        --expect 4343,4232,3739,3871,4100,4119

脚本可被 tests/test_webfem_cat_assets.py import 复跑核心逻辑。
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import re
import sys
from collections import Counter, deque
from pathlib import Path
from typing import Any

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
EXPECTED_SERIES_TOTAL = 24404

# 猫猫系列元信息（名称/标语为占位文案，可随时编辑 catalog JSON）
CAT_META: dict[str, dict[str, str]] = {
    "cat1": {"name": "棕白猫", "tagline": "棕色的小机灵，第一只猫猫"},
    "cat2": {"name": "三花猫", "tagline": "三花配色，独一份好运"},
    "cat3": {"name": "灰猫", "tagline": "安静的小灰猫"},
    "cat4": {"name": "暹罗猫", "tagline": "蓝眼睛的暹罗"},
    "cat5": {"name": "橘猫", "tagline": "十只橘猫九只胖"},
    "cat6": {"name": "布偶猫", "tagline": "软乎乎的白布偶"},
}


def read_csv_grid(path: Path) -> list[list[str]]:
    """读取 100×100 无表头 HEX CSV，返回大小写归一化后的颜色矩阵。"""
    with open(path, encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    if len(rows) != 100:
        raise ValueError(f"{path.name}: expected 100 rows, got {len(rows)}")
    grid = []
    for idx, row in enumerate(rows):
        if len(row) != 100:
            raise ValueError(
                f"{path.name}: row {idx + 1} has {len(row)} cells, expected 100"
            )
        cells = [cell.strip() for cell in row]
        for cell in cells:
            if not HEX_RE.fullmatch(cell):
                raise ValueError(f"{path.name}: bad cell {cell!r}")
        grid.append([cell.upper() for cell in cells])
    return grid


def detect_background_candidate(grid: list[list[str]]) -> str:
    """边缘（四条边）出现次数最多的颜色；并列取色值字典序最小，保证确定性。"""
    n, m = len(grid), len(grid[0])
    counter: Counter[str] = Counter()
    for r in range(n):
        for c in range(m):
            if r in (0, n - 1) or c in (0, m - 1):
                counter[grid[r][c]] += 1
    if not counter:
        raise ValueError("grid has no edge cells")
    # 第 1 关键字出现次数降序，第 2 关键字色值升序 → 确定性
    return min(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0]


def flood_fill_background_mask(
    grid: list[list[str]], background: str
) -> list[list[bool]]:
    """从所有边缘上等于 background 的格子出发，4 邻域 flood-fill。

    返回同尺寸布尔矩阵：True = 与边缘连通的背景格（将写成 null）。
    """
    n, m = len(grid), len(grid[0])
    mask = [[False] * m for _ in range(n)]
    queue: deque[tuple[int, int]] = deque()
    for r in range(n):
        for c in range(m):
            if (r in (0, n - 1) or c in (0, m - 1)) and grid[r][c] == background:
                mask[r][c] = True
                queue.append((r, c))
    while queue:
        r, c = queue.popleft()
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if (
                0 <= nr < n
                and 0 <= nc < m
                and not mask[nr][nc]
                and grid[nr][nc] == background
            ):
                mask[nr][nc] = True
                queue.append((nr, nc))
    return mask


def same_color_components(
    grid: list[list[str | None]], positions: list[tuple[int, int]]
) -> list[list[tuple[int, int]]]:
    """有效格按同色 4 邻域划分为连通块；每块内坐标升序，块间按起点升序（确定性）。"""
    pos_set = set(positions)
    seen: set[tuple[int, int]] = set()
    components: list[list[tuple[int, int]]] = []
    for start in sorted(positions):
        if start in seen:
            continue
        seen.add(start)
        stack = [start]
        comp: list[tuple[int, int]] = []
        while stack:
            r, c = stack.pop()
            comp.append((r, c))
            for nr, nc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if (
                    (nr, nc) in pos_set
                    and (nr, nc) not in seen
                    and grid[nr][nc] == grid[r][c]
                ):
                    seen.add((nr, nc))
                    stack.append((nr, nc))
        comp.sort()
        components.append(comp)
    return components


def _blob_outward_order(comp: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """块内从左上首格 BFS 外扩：局部从一个种子连续生长成片，而不是行扫描。"""
    comp_set = set(comp)
    start = min(comp)
    seen = {start}
    queue: deque[tuple[int, int]] = deque([start])
    order: list[tuple[int, int]] = []
    while queue:
        r, c = queue.popleft()
        order.append((r, c))
        for nr, nc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if (nr, nc) in comp_set and (nr, nc) not in seen:
                seen.add((nr, nc))
                queue.append((nr, nc))
    return order


def build_fill_order(
    artwork_id: str,
    positions: list[tuple[int, int]],
    grid: list[list[str | None]] | None = None,
) -> list[list[int]]:
    """区域成块浮现 fill_order（2026-08-27 起）。

    目标视觉：局部成块浮现 + 整体逐步扩张——先拼出头顶/耳眼等靠上的完整色块，
    再逐级向下长出身体主体，细碎纹理/高光小块最后收口；每推进一段都能看到
    「这一块真的拼好了」。

    算法（纯几何/颜色排序，无随机数，跨平台确定性）：
    1. 有效格按同色 4 邻域划分为连通块；
    2. 面积 ≥ max(8, 总数×0.4%) 的块视为主体块，按（顶行升序，面积降序，左列升序，
       颜色）排序；块内从左上首格 BFS 外扩；
    3. 其余细碎块统一排在最后（纹理/高光收口），按同规则排序。
    ``artwork_id`` 保留在签名里用于派生扩展（当前算法不依赖随机种子）；
    ``grid`` 缺省时退化为 row-major（仅防御性兜底，正常调用都会传 grid）。
    """
    del artwork_id  # 签名兼容保留；浮现顺序完全由 grid 几何/颜色决定
    items = sorted((int(r), int(c)) for r, c in positions)
    if grid is None:
        return [list(pos) for pos in items]
    total = len(items)
    if total == 0:
        return []
    threshold = max(8, round(total * 0.004))
    main: list[list[tuple[int, int]]] = []
    details: list[list[tuple[int, int]]] = []
    for comp in same_color_components(grid, items):
        (main if len(comp) >= threshold else details).append(comp)

    def comp_key(comp: list[tuple[int, int]]):
        top = min(r for r, _ in comp)
        left = min(c for _, c in comp)
        color = grid[comp[0][0]][comp[0][1]]
        return (top, -len(comp), left, color)

    ordered: list[tuple[int, int]] = []
    for comp in sorted(main, key=comp_key):
        ordered.extend(_blob_outward_order(comp))
    for comp in sorted(details, key=comp_key):
        ordered.extend(comp)
    return [list(pos) for pos in ordered]


def extract_palette(grid: list[list[str]]) -> dict[str, int]:
    """非背景（非 null）颜色 → 颗数，按数量降序、色值升序，确定性。"""
    counts: Counter[str] = Counter()
    for row in grid:
        for cell in row:
            if cell is not None:
                counts[cell] += 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {color: count for color, count in ordered}


def convert_csv(
    path: Path,
    artwork_id: str,
    *,
    series_id: str = "cats_v1",
    name: str = "",
    tagline: str = "",
) -> dict[str, Any]:
    """单张 CSV → 内部作品 dict（grid 为 null/#HEX 矩阵 + fill_order）。"""
    colors = read_csv_grid(path)
    background = detect_background_candidate(colors)
    mask = flood_fill_background_mask(colors, background)
    n, m = len(colors), len(colors[0])

    grid: list[list[str | None]] = [
        [None if mask[r][c] else colors[r][c] for c in range(m)] for r in range(n)
    ]
    positions = [
        (r, c) for r in range(n) for c in range(m) if grid[r][c] is not None
    ]
    active_bead_count = len(positions)
    if active_bead_count != sum(1 for row in grid for cell in row if cell is not None):
        raise ValueError(f"{artwork_id}: active_bead_count recount mismatch")

    return {
        "id": artwork_id,
        "series_id": series_id,
        "kind": "series",
        "name": name or artwork_id,
        "tagline": tagline,
        "width": m,
        "height": n,
        "grid": grid,
        "palette": extract_palette(grid),
        "active_bead_count": active_bead_count,
        "fill_order": build_fill_order(artwork_id, positions, grid),
        "completed": False,
        "_background": background,
        "_background_cells": int(sum(map(sum, mask))),
    }


def convert_v1_grid_artwork(data: dict[str, Any]) -> dict[str, Any]:
    """旧 palette-key 网格作品（如新手麦克风）→ 新 schema（null/#HEX grid）。"""
    palette = {str(k): str(v) for k, v in data.get("palette", {}).items()}
    key_rows = list(data["grid"])
    grid: list[list[str | None]] = []
    for row in key_rows:
        cells: list[str | None] = []
        for cell in str(row):
            if cell == ".":
                cells.append(None)
            elif cell in palette:
                cells.append(palette[cell].upper())
            else:
                raise ValueError(
                    f"{data.get('artwork_id')!r}: unknown palette key {cell!r}"
                )
        grid.append(cells)
    height = len(grid)
    width = len(grid[0]) if height else 0
    positions = [
        (r, c) for r in range(height) for c in range(width) if grid[r][c] is not None
    ]
    return {
        "id": str(data["artwork_id"]),
        "series_id": None,
        "kind": "beginner",
        "name": str(data.get("name", data["artwork_id"])),
        "tagline": str(data.get("tagline", "")),
        "width": width,
        "height": height,
        "grid": grid,
        "palette": extract_palette(grid),
        "active_bead_count": len(positions),
        "fill_order": build_fill_order(str(data["artwork_id"]), positions, grid),
        "completed": False,
    }


def build_catalog(
    csv_dir: Path,
    catalog_v1: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """组装完整目录：mic（新手，来自 v1）+ cat1..cat6（系列）。"""
    artworks: list[dict[str, Any]] = []
    if catalog_v1 is not None and catalog_v1.is_file():
        v1 = json.loads(catalog_v1.read_text(encoding="utf-8"))
        for item in v1["artworks"]:
            if item.get("kind") == "beginner" or item.get("artwork_id") == "mic":
                artworks.append(convert_v1_grid_artwork(item))
                break
    else:
        raise ValueError(f"catalog v1 not found: {catalog_v1}")

    reports: list[dict[str, str]] = []
    for index in range(1, 7):
        artwork_id = f"cat{index}"
        path = csv_dir / f"{artwork_id}.csv"
        if not path.is_file():
            raise ValueError(f"missing csv: {path}")
        meta = CAT_META.get(artwork_id, {})
        artwork = convert_csv(
            path,
            artwork_id,
            series_id="cats_v1",
            name=meta.get("name", artwork_id),
            tagline=meta.get("tagline", ""),
        )
        reports.append(
            {
                "id": artwork_id,
                "background": artwork.pop("_background"),
                "background_cells": str(artwork.pop("_background_cells")),
                "active_bead_count": str(artwork["active_bead_count"]),
                "color_count": str(len(artwork["palette"])),
            }
        )
        artworks.append(artwork)
    return artworks, reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Webfem 100×100 CSV → 内部作品 JSON（猫猫系列）"
    )
    parser.add_argument("--csv-dir", required=True, type=Path)
    parser.add_argument("--catalog-v1", type=Path, default=None)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--expect",
        default="4343,4232,3739,3871,4100,4119",
        help="六件 active_bead_count 期望值，逗号分隔",
    )
    args = parser.parse_args(argv)

    artworks, reports = build_catalog(args.csv_dir, args.catalog_v1)
    expected = [int(v) for v in args.expect.split(",")]

    ok = True
    for report, want in zip(reports, expected):
        got = int(report["active_bead_count"])
        mark = "OK" if got == want else "MISMATCH"
        if got != want:
            ok = False
        print(
            f"{report['id']}: bg={report['background']} "
            f"bg_cells={report['background_cells']} "
            f"active={got} (want {want}) colors={report['color_count']} {mark}"
        )
    total = sum(int(r["active_bead_count"]) for r in reports)
    print(f"series total = {total} (want {EXPECTED_SERIES_TOTAL})")
    if total != EXPECTED_SERIES_TOTAL:
        ok = False

    catalog = {
        "version": "v2",
        "series": [{"series_id": "cats_v1", "name": "猫猫系列", "count": 6}],
        "artworks": artworks,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(catalog, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes)")

    if not ok:
        print("ERROR: counts do not match acceptance truth; do NOT proceed.")
        return 1
    print("ALL COUNTS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
