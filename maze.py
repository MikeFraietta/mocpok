"""Deterministic, connected MocPok mazes and portable SVG/binary-STL exports.

Only Python's standard library is required.  Coordinates are [column, row],
with row zero at the bottom.  Seed 18213 reproduces the printed Dragon Keys
board; difficulty changes its clock, not the maze for a given seed.
"""

from __future__ import annotations

import collections
import html
import itertools
import math
import random
import struct
from typing import Any


SIZE = 8
PRINTED_SEED = 18213
STARTS = ((0, 0), (7, 0))
KEYS = ((1, 6), (6, 5))
EXIT = (3, 7)
DIFFICULTIES = {
    "easy": {"rounds_available": 12, "dragon_start": 0},
    "family": {"rounds_available": 10, "dragon_start": 2},
    "hard": {"rounds_available": 9, "dragon_start": 3},
}
DIMENSIONS = {
    "board_width": 216,
    "board_depth": 216,
    "cell_pitch": 25,
    "maze_outer_wall_centerline_span": 200,
    "maze_outer_wall_centerline_origin": [8, 8],
    "wall_thickness": 2,
    "base_thickness": 3,
    "wall_height_above_base": 8,
}


def _new_graph(rng: random.Random) -> dict[tuple[int, int], set]:
    """DFS plus three loops, generated in the original print-map coordinates."""
    graph = {(x, y): set() for y in range(SIZE) for x in range(SIZE)}
    start = (0, SIZE - 1)
    seen, stack = {start}, [start]
    while stack:
        x, y = stack[-1]
        options = [
            p for p in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
            if p in graph and p not in seen
        ]
        if not options:
            stack.pop()
            continue
        other = rng.choice(options)
        graph[x, y].add(other)
        graph[other].add((x, y))
        seen.add(other)
        stack.append(other)
    walls = [
        (p, (p[0] + 1, p[1])) for p in graph
        if (p[0] + 1, p[1]) in graph and (p[0] + 1, p[1]) not in graph[p]
    ] + [
        (p, (p[0], p[1] + 1)) for p in graph
        if (p[0], p[1] + 1) in graph and (p[0], p[1] + 1) not in graph[p]
    ]
    for a, b in rng.sample(walls, min(3, len(walls))):
        graph[a].add(b)
        graph[b].add(a)
    # Convert top-origin print generator into the public bottom-origin grid.
    return {
        (x, SIZE - 1 - y): {(xx, SIZE - 1 - yy) for xx, yy in neighbors}
        for (x, y), neighbors in graph.items()
    }


def _bfs(graph: dict, start: tuple) -> tuple[dict, dict]:
    distances, parents = {start: 0}, {start: None}
    queue = collections.deque([start])
    while queue:
        cell = queue.popleft()
        for other in sorted(graph[cell]):
            if other not in distances:
                distances[other] = distances[cell] + 1
                parents[other] = cell
                queue.append(other)
    return distances, parents


def _route(graph: dict, points: tuple) -> list[list[int]]:
    route = [points[0]]
    for a, b in zip(points, points[1:]):
        parents = _bfs(graph, a)[1]
        leg = [b]
        while leg[-1] != a:
            leg.append(parents[leg[-1]])
        route.extend(reversed(leg[:-1]))
    return [list(p) for p in route]


def _win_probability(threshold: int, rounds: int) -> float:
    counts = {0: 1}
    for _ in range(rounds):
        updated: dict[int, int] = collections.defaultdict(int)
        for total, count in counts.items():
            for roll in range(1, 7):
                updated[total + roll] += count
        counts = updated
    return sum(n for total, n in counts.items() if total >= threshold) / 6 ** rounds


def _analyze(graph: dict, rounds: int) -> dict[str, Any]:
    points = STARTS + KEYS + (EXIT,)
    distances = {p: _bfs(graph, p)[0] for p in points}
    reachable = len(distances[EXIT])
    if reachable != SIZE * SIZE:
        raise ValueError("The maze must connect all 64 cells.")
    plans = []
    for assignment in itertools.product(range(2), repeat=2):
        lengths, paths = [], []
        for player in range(2):
            owned = [KEYS[k] for k in range(2) if assignment[k] == player]
            candidates = []
            for order in itertools.permutations(owned):
                sequence = (STARTS[player],) + order + (EXIT,)
                length = sum(distances[a][b] for a, b in zip(sequence, sequence[1:]))
                candidates.append((length, sequence))
            length, sequence = min(candidates)
            lengths.append(length)
            paths.append(_route(graph, sequence))
        plans.append({
            "key_assignment_to_players": list(assignment),
            "player_lengths": lengths,
            "team_movement_threshold": max(lengths),
            "paths": paths,
        })
    best = min(plans, key=lambda p: (p["team_movement_threshold"], p["key_assignment_to_players"]))
    edges = sum(len(v) for v in graph.values()) // 2
    threshold = best["team_movement_threshold"]
    return {
        "connected": True,
        "all_cells_reachable": True,
        "reachable_cells": reachable,
        "total_cells": SIZE * SIZE,
        "keys_reachable": True,
        "exit_reachable": True,
        "undirected_passages": edges,
        "independent_cycles": edges - reachable + 1,
        "optimal_team_movement_threshold": threshold,
        "optimal_team_steps": threshold,
        "optimal_plan": best,
        "optimal_routes": best["paths"],
        "optimal_player_steps": best["player_lengths"],
        "winnable_with_max_rolls": threshold <= 6 * rounds,
        "optimal_play_win_probability": _win_probability(threshold, rounds),
        "probability_note": "Exact fair-die model with full map knowledge and optimal routes; not a family playtest result.",
        "checks": ["All 64 cells connected", "Both keys reachable", "Exit reachable", "Two-player key route checked"],
    }


def generate_game(seed: int, difficulty: str = "family") -> dict[str, Any]:
    """Return an 8x8 game definition. Equal seeds reproduce equal wall layouts.

    Reject mazes requiring more than 40 steps per explorer on the best team
    plan. This bounds long-route outliers and leaves winning die sequences at
    every clock setting. It is not a promise of equal human-play difficulty.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if not isinstance(difficulty, str) or difficulty.lower().strip() not in DIFFICULTIES:
        raise ValueError("difficulty must be easy, family, or hard")
    difficulty = difficulty.lower().strip()
    clock = dict(DIFFICULTIES[difficulty])
    rng = random.Random(seed)
    for attempt in range(100):
        graph = _new_graph(rng)
        validation = _analyze(graph, clock["rounds_available"])
        if validation["optimal_team_movement_threshold"] <= 40:
            break
    else:
        raise ValueError("Could not create a maze with a valid two-player route.")
    east = [
        "".join("1" if (x + 1, y) in graph[x, y] else "0" for x in range(SIZE))
        for y in range(SIZE)
    ]
    north = [
        "".join("1" if (x, y + 1) in graph[x, y] else "0" for x in range(SIZE))
        for y in range(SIZE)
    ]
    return {
        "title": "MocPok: Dragon Keys",
        "subtitle": "Two explorers. Two keys. One dragon.",
        "version": "local-demo-1",
        "seed": seed,
        "generation_attempt": attempt + 1,
        "generator": "Seeded maze algorithm; an AI can choose supported game parameters.",
        "difficulty": difficulty,
        "players": 2,
        "width": SIZE,
        "height": SIZE,
        "east": east,
        "north": north,
        "coordinate_system": {"origin": "bottom-left cell", "coordinates": "[column, row]", "row_index_base": 0},
        "grid": {
            "width": SIZE,
            "height": SIZE,
            "east_open_by_row_bottom_to_top": east,
            "north_open_by_row_bottom_to_top": north,
        },
        "starts": [{"id": "A", "cell": list(STARTS[0])}, {"id": "B", "cell": list(STARTS[1])}],
        "keys": [{"id": "K1", "cell": list(KEYS[0])}, {"id": "K2", "cell": list(KEYS[1])}],
        "exit": {"cell": list(EXIT), "name": "Castle exit"},
        "dimensions_mm": {**DIMENSIONS, "maze_outer_wall_centerline_origin": [8, 8]},
        "round_limit": clock["rounds_available"],
        "dragon_start": clock["dragon_start"],
        "rules": {
            "mode": "cooperative",
            "key_ownership": "Shared by the whole team; either explorer may collect either or both keys.",
            "rounds_available": clock["rounds_available"],
            "dragon_start": clock["dragon_start"],
            "finish_position": 12,
            "difficulties": {name: dict(data) for name, data in DIFFICULTIES.items()},
            "round_sequence": [
                "Roll one d6 for the team. Each explorer gets the full roll, not a split share.",
                "Move each explorer up to that many open passages, in either order. Waiting and backtracking are allowed.",
                "Collect a key immediately when either explorer enters its cell. Pawns may pass or share cells.",
                "Once both keys are collected, explorers at the castle exit escape. Remove escaped pawns.",
                "If both escaped, win immediately, including during the final round before the dragon advances.",
                "Otherwise advance the dragon one space. Reaching 12 while someone is inside means the team loses.",
            ],
            "win_condition": "Collect both keys and get both explorers to the castle exit before the dragon reaches 12.",
        },
        "components": {"board": 1, "explorer_pawns": 2, "key_tokens": 2, "dragon_marker": 1, "dragon_track": 1, "standard_d6": 1},
        "validation": validation,
    }


def _grid_data(game: dict) -> tuple[int, int, list[str], list[str]]:
    grid = game.get("grid", {})
    width, height = int(grid.get("width", SIZE)), int(grid.get("height", SIZE))
    if (width, height) != (SIZE, SIZE):
        raise ValueError("This prototype exports 8x8 boards only.")
    east = grid.get("east_open_by_row_bottom_to_top", game.get("east"))
    north = grid.get("north_open_by_row_bottom_to_top", game.get("north"))
    for rows in (east, north):
        if not isinstance(rows, list) or len(rows) != height:
            raise ValueError("Passages must contain eight binary row strings.")
        if any(not isinstance(row, str) or len(row) != width or set(row) - {"0", "1"} for row in rows):
            raise ValueError("Passages must contain eight binary row strings.")
    if any(row[-1] != "0" for row in east) or "1" in north[-1]:
        raise ValueError("An outer boundary cannot contain an open passage.")
    return width, height, east, north


def _wall_rectangles(game: dict) -> tuple[dict, list[tuple[float, float, float, float]]]:
    width, height, east, north = _grid_data(game)
    dims = {**DIMENSIONS, **game.get("dimensions_mm", {})}
    names = ("board_width", "board_depth", "cell_pitch", "wall_thickness", "base_thickness", "wall_height_above_base")
    for name in names:
        value = float(dims[name])
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Board dimensions must be finite positive numbers.")
        dims[name] = value
    ox, oy = map(float, dims["maze_outer_wall_centerline_origin"])
    if not all(map(math.isfinite, (ox, oy))):
        raise ValueError("The maze origin must be finite.")
    pitch, half = dims["cell_pitch"], dims["wall_thickness"] / 2
    xmax, ymax = ox + width * pitch, oy + height * pitch
    if half >= pitch / 2 or min(ox - half, oy - half) < 0:
        raise ValueError("Wall thickness or origin would close the passages.")
    if xmax + half > dims["board_width"] or ymax + half > dims["board_depth"]:
        raise ValueError("Maze walls extend outside the board.")
    if max(dims["board_width"], dims["board_depth"]) > 256:
        raise ValueError("This export is limited to a 256 mm square print bed.")
    rectangles = [
        (ox - half, oy - half, xmax + half, oy + half),
        (ox - half, ymax - half, xmax + half, ymax + half),
        (ox - half, oy - half, ox + half, ymax + half),
        (xmax - half, oy - half, xmax + half, ymax + half),
    ]
    for y in range(height):
        for x in range(width):
            left, bottom = ox + x * pitch, oy + y * pitch
            if x < width - 1 and east[y][x] == "0":
                center = left + pitch
                rectangles.append((center - half, bottom - half, center + half, bottom + pitch + half))
            if y < height - 1 and north[y][x] == "0":
                center = bottom + pitch
                rectangles.append((left - half, center - half, left + pitch + half, center + half))
    return dims, rectangles


def render_svg(game: dict, title: str = "MocPok: Dragon Keys") -> str:
    """Return an escaped, standalone top-down board and token-placement guide."""
    width, height, _, _ = _grid_data(game)
    dims, rectangles = _wall_rectangles(game)
    bw, bd, pitch = dims["board_width"], dims["board_depth"], dims["cell_pitch"]
    ox, oy = dims["maze_outer_wall_centerline_origin"]
    safe_title = html.escape(" ".join(str(title).split())[:100], quote=True)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -22 {bw:g} {bd + 44:g}" width="{bw:g}mm" height="{bd + 44:g}mm" role="img" aria-label="{safe_title}">',
        f"<title>{safe_title}</title>",
        '<style>text{font-family:Arial,Helvetica,sans-serif} .small{font-size:3px;fill:#68708a}</style>',
        f'<text x="0" y="-10" font-size="8" font-weight="700" fill="#26324b">{safe_title}</text>',
        f'<text x="0" y="-3" class="small">Two explorers. Two keys. One dragon.</text>',
        f'<rect width="{bw:g}" height="{bd:g}" rx="5" fill="#fff9ee"/>',
    ]
    for row in range(height):
        for column in range(width):
            x, y = ox + column * pitch, bd - oy - (row + 1) * pitch
            parts.append(f'<rect x="{x:g}" y="{y:g}" width="{pitch:g}" height="{pitch:g}" fill="none" stroke="#e7e0d2" stroke-width="0.3"/>')
    for x0, y0, x1, y1 in rectangles:
        parts.append(f'<rect x="{x0:g}" y="{bd - y1:g}" width="{x1 - x0:g}" height="{y1 - y0:g}" fill="#26324b"/>')

    def center(cell: list) -> tuple[float, float]:
        return ox + (cell[0] + 0.5) * pitch, bd - oy - (cell[1] + 0.5) * pitch

    for index, start in enumerate(game.get("starts", [])):
        x, y = center(start["cell"])
        color = ("#397ad3", "#249770")[index % 2]
        label = html.escape(str(start.get("id", index + 1)), quote=True)
        parts.append(f'<circle cx="{x:g}" cy="{y:g}" r="6.5" fill="{color}"/><text x="{x:g}" y="{y + 2:g}" text-anchor="middle" font-size="6" font-weight="700" fill="white">{label}</text>')
    for key in game.get("keys", []):
        x, y = center(key["cell"])
        label = html.escape(str(key.get("id", "KEY")), quote=True)
        parts.append(f'<g transform="translate({x - 5:g},{y - 1:g})" fill="none" stroke="#c28b20" stroke-width="1.8" stroke-linecap="round"><circle cx="0" cy="0" r="3"/><path d="M3 0H11M8 0V3M11 0V3"/></g><text x="{x:g}" y="{y + 8:g}" text-anchor="middle" font-size="3.2" fill="#8f6013">{label}</text>')
    x, y = center(game.get("exit", {"cell": list(EXIT)})["cell"])
    parts.append(f'<g transform="translate({x - 6:g},{y - 6:g})" fill="#9a65b5"><path d="M0 0H3V3H5V0H8V3H10V0H13V13H0Z"/><path d="M5 13V8A2 2 0 0 1 9 8V13" fill="#fff9ee"/></g><text x="{x:g}" y="{y + 10:g}" text-anchor="middle" font-size="3" fill="#75458e">EXIT</text>')
    parts.append(f'<text x="0" y="{bd + 10:g}" class="small">Row 0 is at the bottom. A and B start here; collect K1 + K2, then escape.</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def export_stl(game: dict) -> bytes:
    """Return one watertight binary-STL board with no overlapping box interiors.

    All wall rectangle breakpoints partition a shared XY grid.  The base and
    wall layers expose faces only where their neighboring voxel is empty.
    Shared vertex breakpoints prevent T-junctions between adjacent surfaces.
    """
    dims, rectangles = _wall_rectangles(game)
    bw, bd = dims["board_width"], dims["board_depth"]
    base, high = dims["base_thickness"], dims["base_thickness"] + dims["wall_height_above_base"]
    xs = sorted({0.0, bw} | {v for rectangle in rectangles for v in (rectangle[0], rectangle[2])})
    ys = sorted({0.0, bd} | {v for rectangle in rectangles for v in (rectangle[1], rectangle[3])})
    nx, ny = len(xs) - 1, len(ys) - 1
    wall = [[False] * nx for _ in range(ny)]
    for j in range(ny):
        cy = (ys[j] + ys[j + 1]) / 2
        for i in range(nx):
            cx = (xs[i] + xs[i + 1]) / 2
            wall[j][i] = any(x0 < cx < x1 and y0 < cy < y1 for x0, y0, x1, y1 in rectangles)
    records: list[bytes] = []

    def quad(vertices: tuple, normal: tuple) -> None:
        for a, b, c in ((0, 1, 2), (0, 2, 3)):
            values = (*normal, *vertices[a], *vertices[b], *vertices[c])
            records.append(struct.pack("<12fH", *values, 0))

    def vertical(i: int, j: int, low: float, top: float, side: str) -> None:
        x0, x1, y0, y1 = xs[i], xs[i + 1], ys[j], ys[j + 1]
        if side == "west":
            quad(((x0, y0, low), (x0, y0, top), (x0, y1, top), (x0, y1, low)), (-1, 0, 0))
        elif side == "east":
            quad(((x1, y0, low), (x1, y1, low), (x1, y1, top), (x1, y0, top)), (1, 0, 0))
        elif side == "south":
            quad(((x0, y0, low), (x1, y0, low), (x1, y0, top), (x0, y0, top)), (0, -1, 0))
        else:
            quad(((x0, y1, low), (x0, y1, top), (x1, y1, top), (x1, y1, low)), (0, 1, 0))

    for j in range(ny):
        for i in range(nx):
            x0, x1, y0, y1 = xs[i], xs[i + 1], ys[j], ys[j + 1]
            quad(((x0, y1, 0), (x1, y1, 0), (x1, y0, 0), (x0, y0, 0)), (0, 0, -1))
            top = high if wall[j][i] else base
            quad(((x0, y0, top), (x1, y0, top), (x1, y1, top), (x0, y1, top)), (0, 0, 1))
            if i == 0:
                vertical(i, j, 0, base, "west")
            if i == nx - 1:
                vertical(i, j, 0, base, "east")
            if j == 0:
                vertical(i, j, 0, base, "south")
            if j == ny - 1:
                vertical(i, j, 0, base, "north")
            if wall[j][i]:
                for di, dj, side in ((-1, 0, "west"), (1, 0, "east"), (0, -1, "south"), (0, 1, "north")):
                    ii, jj = i + di, j + dj
                    if not (0 <= ii < nx and 0 <= jj < ny) or not wall[jj][ii]:
                        vertical(i, j, base, high, side)
    header = b"MocPok Dragon Keys; units=mm; watertight heightfield board".ljust(80, b"\0")
    return header + struct.pack("<I", len(records)) + b"".join(records)


# Friendly export aliases for callers that use board-oriented names.
board_svg = render_svg
board_stl = export_stl

