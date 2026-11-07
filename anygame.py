"""Any-kind-of-board-game designs for MocPok. Python standard library only.

The local model designs the whole game (type, pieces, setup, turns, winning) as JSON.
This module validates that JSON and draws a printable paper board for it:
a race track, a grid board, or a sheet of cut-out tiles/cards.
Maze adventures are handled by the original, rule-checked Dragon Keys path in server.py.
"""
from __future__ import annotations

from html import escape

import re

KINDS = ("maze_adventure", "race_track", "grid_board", "tiles_or_cards", "property_loop")
PROPERTY_WORDS = re.compile(r"\b(monopoly|property|properties|real estate|landlord|buy (houses|streets|places))\b", re.I)

# Hand-checked real places, so the board never shows invented landmarks for these neighborhoods.
# Ordered cheapest to most expensive; each pair shares a color.
PLACES = {
    "williamsburg": {
        "display": "Williamsburg, Brooklyn",
        "landmarks": [
            "Havemeyer Street", "Grand Street",
            "Kellogg's Diner", "Nitehawk Cinema",
            "McCarren Pool", "McCarren Park",
            "Brooklyn Bowl", "Music Hall of Williamsburg",
            "Smorgasburg", "Brooklyn Brewery",
            "Grand Ferry Park", "Marsha P. Johnson State Park",
            "Bedford Avenue", "Peter Luger Steak House",
            "Domino Park", "Williamsburg Bridge",
        ],
        "transit": ["Bedford Av L Train", "NYC Ferry Landing"],
    },
}
CORNERS = (("START", "Collect $2 each time you pass"), ("Rest Stop", "Just relaxing"),
           ("Lucky Ride", "Move to any space"), ("Traffic Jam", "Skip your next turn"))
PROPERTY_RULES = {
    "players": "2-4 players, ages 6+",
    "goal": "Own the best places and be the richest player when the game ends.",
    "components": ["The printed property board", "One ordinary six-sided die", "Coins or paper money ($15 per player)",
                   "One token per player (a button or coin)", "Blank paper cards for Surprise cards"],
    "setup": "Everyone puts a token on START and takes $15. Write 8 Surprise cards together and stack them in the middle.",
    "turn": "Roll the die and move clockwise. If nobody owns the place you land on, you may buy it for its price. "
            "If another player owns it, pay them its price as rent, or double if they own both places of that color.",
    "winning": "When a player can't pay, the game ends. Everyone counts their money plus the prices of their places, and the richest player wins.",
}
PAIR_COLORS = ("#8d5a3b", "#7cc6e8", "#d0567d", "#e8913a", "#d64545", "#e6c229", "#2f9e5b", "#2b4fa3")


def find_place(prompt: str):
    lowered = prompt.lower()
    for key, place in PLACES.items():
        if key in lowered:
            return place
    return None


def detrademark(text: str) -> str:
    """Keep Hasbro's trademark off the printed board; the mechanics are generic."""
    text = re.sub(r"(?i)\bmonopoly[- ]?(style|like)\b", "property-trading", text)
    return re.sub(r"(?i)\bmonopoly\b", "Property Dash", text)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "title", "game_type", "theme", "players", "goal", "components", "setup", "turn", "winning", "board_labels"],
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "title": {"type": "string", "minLength": 1, "maxLength": 60},
        "game_type": {"type": "string", "minLength": 1, "maxLength": 80},
        "theme": {"type": "string", "minLength": 1, "maxLength": 200},
        "players": {"type": "string", "minLength": 1, "maxLength": 40},
        "goal": {"type": "string", "minLength": 1, "maxLength": 240},
        "components": {"type": "array", "minItems": 2, "maxItems": 7, "items": {"type": "string", "minLength": 1, "maxLength": 80}},
        "setup": {"type": "string", "minLength": 1, "maxLength": 450},
        "turn": {"type": "string", "minLength": 1, "maxLength": 550},
        "winning": {"type": "string", "minLength": 1, "maxLength": 350},
        "board_labels": {"type": "array", "minItems": 4, "maxItems": 16, "items": {"type": "string", "minLength": 1, "maxLength": 30}},
    },
}

SYSTEM = """You are MocPok, a friendly local board-game designer for children and families.
Invent an ORIGINAL board game from the child's idea. It can be any kind of game: a race game, a tile-matching or set-collecting game, a card game, a grid strategy game, a memory game, a cooperative game, or a maze adventure.
You may borrow a classic game's mechanics (for example matching tiles like mah jong), but use your own title and theme.
Choose "kind" for the board our printer can draw:
- "maze_adventure": explorers search a maze, find things, and escape.
- "race_track": players move along a path of spaces with dice; good for racing and journeys.
- "grid_board": players place or move pieces on a square grid; good for strategy, capturing, or connecting.
- "tiles_or_cards": play with a set of printed tiles or cards; good for matching, collecting, memory, or card games.
- "property_loop": players roll a die and travel around a square loop of real or imagined places, buying places and collecting rent; good for property-trading and city games.
Use only simple, cheap components: the printed board or tiles, ordinary dice, coins, buttons, or paper tokens.
Make rules a seven-year-old can follow: setup, turn, and winning are each at most three short sentences. Give a clear way to win.
board_labels are 4 to 12 very short names (1 to 3 words) printed on the board: special spaces for a race track, piece or zone names for a grid, or the tile or card faces for tiles_or_cards.
Return ONLY a JSON object with the required fields.
/no_think"""


class DesignError(ValueError):
    pass


def _clean(value: object, limit: int) -> str:
    if not isinstance(value, str):
        raise DesignError("not text")
    text = " ".join(value.split())
    if not text or len(text) > limit:
        raise DesignError("bad length")
    return text


def validate(draft: object) -> dict:
    if not isinstance(draft, dict) or set(draft) != set(SCHEMA["required"]):
        raise DesignError("incomplete design")
    props = SCHEMA["properties"]
    plan = {}
    if draft["kind"] not in KINDS:
        raise DesignError("unknown kind")
    plan["kind"] = draft["kind"]
    for key in ("title", "game_type", "theme", "players", "goal", "setup", "turn", "winning"):
        plan[key] = _clean(draft[key], props[key]["maxLength"])
    for key in ("components", "board_labels"):
        items = draft[key]
        spec = props[key]
        if not isinstance(items, list) or not spec["minItems"] <= len(items) <= spec["maxItems"]:
            raise DesignError("bad list")
        plan[key] = [_clean(item, spec["items"]["maxLength"]) for item in items]
    return plan


# ---------- printable boards (SVG) ----------

INK = "#23324a"
PAPER = "#fbf8f1"
ACCENTS = ("#e07a5f", "#2f8f83", "#c8962e", "#8a5cc2", "#3d7dd8", "#d0567d")
FONT = "font-family=\"Avenir Next, Helvetica, Arial, sans-serif\""


def _wrap(text: str, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        lines.append(line)
    return lines[:3]


def _label(x: float, y: float, text: str, width: int, size: int, color: str = INK, weight: int = 600) -> str:
    lines = _wrap(text, width)
    top = y - (len(lines) - 1) * size * 0.6
    out = []
    for i, line in enumerate(lines):
        out.append(f'<text x="{x:.1f}" y="{top + i * size * 1.2:.1f}" text-anchor="middle" dominant-baseline="middle" '
                   f'{FONT} font-size="{size}" font-weight="{weight}" fill="{color}">{escape(line)}</text>')
    return "".join(out)


def _frame(plan: dict, body: str, footer: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 900" width="800" height="900">'
            f'<rect width="800" height="900" fill="{PAPER}"/>'
            f'<text x="40" y="62" {FONT} font-size="34" font-weight="700" fill="{INK}">{escape(plan["title"])}</text>'
            f'<text x="40" y="94" {FONT} font-size="16" fill="#5f6b7a">{escape(plan["game_type"])} · {escape(plan["players"])}</text>'
            f'{body}'
            f'<text x="400" y="872" text-anchor="middle" {FONT} font-size="14" fill="#5f6b7a">{escape(footer)}</text>'
            f'</svg>')


def _race_track(plan: dict) -> str:
    cols, rows, size, gap = 6, 5, 104, 14
    x0, y0 = 400 - (cols * size + (cols - 1) * gap) / 2, 130
    centers = []
    for r in range(rows):
        order = range(cols) if r % 2 == 0 else range(cols - 1, -1, -1)
        for c in order:
            centers.append((x0 + c * (size + gap) + size / 2, y0 + r * (size + gap) + size / 2))
    labels = plan["board_labels"]
    path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in centers)
    parts = [f'<path d="{path}" fill="none" stroke="{INK}" stroke-width="10" stroke-linejoin="round" opacity=".18"/>']
    special = 0
    for i, (x, y) in enumerate(centers):
        last = i == len(centers) - 1
        if i == 0 or last:
            fill, text, color = (ACCENTS[1] if i == 0 else ACCENTS[0]), ("START" if i == 0 else "FINISH"), "#ffffff"
        elif i % 4 == 0:
            fill, text, color = ACCENTS[(special % 4) + 2] + "33", labels[special % len(labels)], INK
            special += 1
        else:
            fill, text, color = "#ffffff", str(i), "#8a94a3"
        parts.append(f'<rect x="{x - size / 2:.1f}" y="{y - size / 2:.1f}" width="{size}" height="{size}" rx="16" fill="{fill}" stroke="{INK}" stroke-width="3"/>')
        parts.append(_label(x, y, text, 10, 15 if len(text) > 3 else 20, color))
    return _frame(plan, "".join(parts), "Race board · print at 100% · use a die and one token per player")


def _grid_board(plan: dict) -> str:
    n, cell = 8, 76
    x0, y0 = 400 - n * cell / 2, 130
    parts = []
    for r in range(n):
        for c in range(n):
            fill = "#efe6d2" if (r + c) % 2 else "#ffffff"
            parts.append(f'<rect x="{x0 + c * cell}" y="{y0 + r * cell}" width="{cell}" height="{cell}" fill="{fill}"/>')
    parts.append(f'<rect x="{x0}" y="{y0}" width="{n * cell}" height="{n * cell}" fill="none" stroke="{INK}" stroke-width="5" rx="6"/>')
    labels = plan["board_labels"]
    legend_y = y0 + n * cell + 40
    per_row = 4
    for i, text in enumerate(labels[:8]):
        cx = 110 + (i % per_row) * 195
        cy = legend_y + (i // per_row) * 46
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="14" fill="{ACCENTS[i % len(ACCENTS)]}"/>')
        parts.append(f'<text x="{cx + 24}" y="{cy}" dominant-baseline="middle" {FONT} font-size="15" font-weight="600" fill="{INK}">{escape(text)}</text>')
    return _frame(plan, "".join(parts), "8 × 8 grid board · print at 100% · use coins or paper tokens as pieces")


def _tiles(plan: dict) -> str:
    cols, rows, w, h, gap = 6, 4, 112, 150, 12
    x0, y0 = 400 - (cols * w + (cols - 1) * gap) / 2, 140
    labels = plan["board_labels"]
    parts = []
    for i in range(cols * rows):
        r, c = divmod(i, cols)
        x, y = x0 + c * (w + gap), y0 + r * (h + gap)
        k = i % len(labels)
        color = ACCENTS[k % len(ACCENTS)]
        text = labels[k]
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="#ffffff" stroke="{INK}" stroke-width="2.5" stroke-dasharray="7 5"/>')
        parts.append(f'<circle cx="{x + w / 2}" cy="{y + 50}" r="28" fill="{color}"/>')
        parts.append(_label(x + w / 2, y + 50, text[0].upper(), 4, 26, "#ffffff", 700))
        parts.append(_label(x + w / 2, y + 112, text, 11, 14))
    body = "".join(parts)
    note_y = y0 + rows * (h + gap) + 30
    body += _label(400, note_y, "Print two sheets for more tiles. Cut along the dashed lines.", 80, 15, "#5f6b7a", 500)
    return _frame(plan, body, "Tile and card sheet · print at 100% · cut out and play")


def _property_loop(plan: dict) -> str:
    """A square loop: 4 corners + 5 spaces per side = 24 spaces, all text upright."""
    x0, y0, size, corner = 40, 120, 720, 120
    side = (size - 2 * corner) / 5
    place = plan.get("place") or {}
    landmarks = list(place.get("landmarks") or plan["board_labels"])
    transit = list(place.get("transit") or ["Train Station", "Bus Stop"])
    while len(landmarks) < 16:
        landmarks.append(plan["board_labels"][len(landmarks) % len(plan["board_labels"])])
    # Clockwise from START (bottom-right): bottom row right-to-left, left column bottom-to-top,
    # top row left-to-right, right column top-to-bottom.
    side_pattern = ("L", "L", "S", "L", "L"), ("L", "L", "T", "L", "L"), ("L", "L", "S", "L", "L"), ("L", "L", "T", "L", "L")
    cells = []
    for s in range(4):
        for j in range(5):
            if s == 0:
                rect = (x0 + size - corner - (j + 1) * side, y0 + size - corner, side, corner)
            elif s == 1:
                rect = (x0, y0 + size - corner - (j + 1) * side, corner, side)
            elif s == 2:
                rect = (x0 + corner + j * side, y0, side, corner)
            else:
                rect = (x0 + size - corner, y0 + corner + j * side, corner, side)
            cells.append((side_pattern[s][j], rect, s))
    corners = [(x0 + size - corner, y0 + size - corner), (x0, y0 + size - corner), (x0, y0), (x0 + size - corner, y0)]
    parts = [f'<rect x="{x0}" y="{y0}" width="{size}" height="{size}" fill="#eef4ea" stroke="{INK}" stroke-width="4"/>']
    for (name, note), (cx, cy) in zip(CORNERS, corners):
        parts.append(f'<rect x="{cx}" y="{cy}" width="{corner}" height="{corner}" fill="#ffffff" stroke="{INK}" stroke-width="2"/>')
        parts.append(_label(cx + corner / 2, cy + 50, name, 10, 17, ACCENTS[0] if name == "START" else INK, 700))
        parts.append(_label(cx + corner / 2, cy + 88, note, 14, 11, "#5f6b7a", 500))
    li = ti = 0
    for kind, (x, y, w, h), s in cells:
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="#ffffff" stroke="{INK}" stroke-width="2"/>')
        mx = x + w / 2
        if kind == "L":
            color, price = PAIR_COLORS[li // 2], li // 2 + 1
            band = 22
            if s == 1:
                parts.append(f'<rect x="{x + w - band:.1f}" y="{y:.1f}" width="{band}" height="{h:.1f}" fill="{color}" stroke="{INK}" stroke-width="2"/>')
                mx = x + (w - band) / 2
                text_y, price_y = y + h / 2 - 8, y + h - 14
            elif s == 3:
                parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{band}" height="{h:.1f}" fill="{color}" stroke="{INK}" stroke-width="2"/>')
                mx = x + band + (w - band) / 2
                text_y, price_y = y + h / 2 - 8, y + h - 14
            elif s == 2:
                parts.append(f'<rect x="{x:.1f}" y="{y + h - band:.1f}" width="{w:.1f}" height="{band}" fill="{color}" stroke="{INK}" stroke-width="2"/>')
                text_y, price_y = y + 44, y + h - band - 14
            else:
                parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{band}" fill="{color}" stroke="{INK}" stroke-width="2"/>')
                text_y, price_y = y + band + 36, y + h - 14
            parts.append(_label(mx, text_y, landmarks[li], 12 if s in (1, 3) else 10, 11))
            parts.append(_label(mx, price_y, f"${price}", 6, 12, "#5f6b7a", 700))
            li += 1
        elif kind == "T":
            parts.append(_label(mx, y + h / 2 - 12, "🚇" if ti == 0 else "⛴", 4, 22))
            parts.append(_label(mx, y + h / 2 + 22, transit[ti % len(transit)], 12, 11))
            ti += 1
        else:
            parts.append(_label(mx, y + h / 2 - 12, "?", 3, 30, ACCENTS[3], 700))
            parts.append(_label(mx, y + h / 2 + 24, "Surprise", 10, 12))
    c = x0 + size / 2
    where = place.get("display", "")
    parts.append(_label(c, y0 + 300, plan["title"], 22, 34, INK, 700))
    if where:
        parts.append(_label(c, y0 + 356, where, 40, 18, ACCENTS[1], 600))
    parts.append(f'<rect x="{c - 190}" y="{y0 + 400}" width="160" height="100" rx="12" fill="#ffffff" stroke="{INK}" stroke-width="2" stroke-dasharray="7 5"/>')
    parts.append(_label(c - 110, y0 + 450, "Surprise cards", 10, 14))
    parts.append(f'<rect x="{c + 30}" y="{y0 + 400}" width="160" height="100" rx="12" fill="#ffffff" stroke="{INK}" stroke-width="2" stroke-dasharray="7 5"/>')
    parts.append(_label(c + 110, y0 + 450, "Bank", 10, 14))
    return _frame(plan, "".join(parts), "Property board · print at 100% · use a die, coins for money, and one token per player")


def render_svg(plan: dict) -> str:
    return {"race_track": _race_track, "grid_board": _grid_board, "tiles_or_cards": _tiles,
            "property_loop": _property_loop}[plan["kind"]](plan)


def make_rules(plan: dict) -> str:
    lines = [f"# {plan['title']}", "", f"*{plan['game_type']} · {plan['players']}*", "",
             "## The world", "", plan["theme"], "", "## Your goal", "", plan["goal"], "", "## What you need", ""]
    lines += [f"- {item}" for item in plan["components"]]
    lines += ["", "## Setup", "", plan["setup"], "", "## On your turn", "", plan["turn"], "",
              "## Winning", "", plan["winning"], ""]
    if plan["kind"] == "property_loop":
        lines += ["## Board spaces", "",
                  "- **START:** collect $2 each time you pass it.",
                  "- **Rest Stop:** nothing happens; take a breather.",
                  "- **Lucky Ride:** move your token to any space you like.",
                  "- **Traffic Jam:** skip your next turn.",
                  "- **Surprise:** draw a Surprise card that you write yourselves (for example: \"Collect $1\" or \"Move back 2\").",
                  "- **Places:** the price is on each space. Two places of the same color are a set: owning both doubles the rent.", ""]
    lines += [
              "## About this game", "",
              "An open-weight model (Qwen3 4B) running locally in Ollama designed these rules from a child's idea, "
              "and MocPok drew the printable board. The rules were written by AI and have not been playtested: "
              "play a round, then change anything that isn't fun or fair.", ""]
    return "\n".join(lines)
