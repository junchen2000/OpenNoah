"""Buddy/Companion system - virtual pet for Noah Code."""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import get_config_dir

# ── Types ────────────────────────────────────────────────────

RARITIES = ("common", "uncommon", "rare", "epic", "legendary")
RARITY_WEIGHTS = {"common": 60, "uncommon": 25, "rare": 10, "epic": 4, "legendary": 1}
RARITY_STARS = {"common": "★", "uncommon": "★★", "rare": "★★★", "epic": "★★★★", "legendary": "★★★★★"}
RARITY_FLOOR = {"common": 5, "uncommon": 15, "rare": 25, "epic": 35, "legendary": 50}

SPECIES = [
    "duck", "goose", "blob", "cat", "dragon", "octopus", "owl", "penguin",
    "turtle", "snail", "ghost", "axolotl", "capybara", "cactus", "robot",
    "rabbit", "mushroom", "chonk",
]
EYES = ["·", "✦", "×", "◉", "@", "°"]
HATS = ["none", "crown", "tophat", "propeller", "halo", "wizard", "beanie", "tinyduck"]
STAT_NAMES = ["DEBUGGING", "PATIENCE", "CHAOS", "WISDOM", "SNARK"]

SALT = "noah-legend-1140"


@dataclass
class Companion:
    rarity: str
    species: str
    eye: str
    hat: str
    shiny: bool
    stats: dict[str, int]
    name: str = ""
    personality: str = ""
    hatched_at: float = 0.0


# ── Seeded PRNG (Mulberry32) ────────────────────────────────

def _mulberry32(seed: int):
    """Tiny seeded PRNG matching the TS implementation."""
    a = seed & 0xFFFFFFFF
    def _next() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((a ^ (a >> 15)) * (1 | a)) & 0xFFFFFFFF
        t = (t + ((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF) ^ t
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return _next


def _hash_string(s: str) -> int:
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _pick(rng, arr):
    return arr[int(rng() * len(arr))]


def _roll_rarity(rng) -> str:
    total = sum(RARITY_WEIGHTS.values())
    roll = rng() * total
    for r in RARITIES:
        roll -= RARITY_WEIGHTS[r]
        if roll < 0:
            return r
    return "common"


def _roll_stats(rng, rarity: str) -> dict[str, int]:
    floor = RARITY_FLOOR[rarity]
    peak = _pick(rng, STAT_NAMES)
    dump = _pick(rng, STAT_NAMES)
    while dump == peak:
        dump = _pick(rng, STAT_NAMES)

    stats = {}
    for name in STAT_NAMES:
        if name == peak:
            stats[name] = min(100, floor + 50 + int(rng() * 30))
        elif name == dump:
            stats[name] = max(1, floor - 10 + int(rng() * 15))
        else:
            stats[name] = floor + int(rng() * 40)
    return stats


def roll_companion(user_id: str) -> dict[str, Any]:
    """Deterministically generate companion bones from user ID."""
    key = user_id + SALT
    rng = _mulberry32(_hash_string(key))
    rarity = _roll_rarity(rng)
    return {
        "rarity": rarity,
        "species": _pick(rng, SPECIES),
        "eye": _pick(rng, EYES),
        "hat": "none" if rarity == "common" else _pick(rng, HATS),
        "shiny": rng() < 0.01,
        "stats": _roll_stats(rng, rarity),
    }


# ── Persistence ──────────────────────────────────────────────

def _companion_file() -> Path:
    return get_config_dir() / "companion.json"


def save_companion(companion: Companion) -> None:
    """Persist companion soul (name + personality) to config."""
    data = {"name": companion.name, "personality": companion.personality, "hatched_at": companion.hatched_at}
    path = _companion_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_companion(user_id: str | None = None) -> Companion | None:
    """Load companion: regenerate bones from user_id, merge with stored soul."""
    uid = user_id or os.environ.get("USER", os.environ.get("USERNAME", "anon"))
    path = _companion_file()

    bones = roll_companion(uid)

    if not path.exists():
        return None

    try:
        stored = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    return Companion(
        **bones,
        name=stored.get("name", ""),
        personality=stored.get("personality", ""),
        hatched_at=stored.get("hatched_at", 0),
    )


def hatch_companion(user_id: str | None = None, name: str = "", personality: str = "") -> Companion:
    """Hatch a new companion."""
    uid = user_id or os.environ.get("USER", os.environ.get("USERNAME", "anon"))
    bones = roll_companion(uid)
    companion = Companion(
        **bones,
        name=name or bones["species"].capitalize(),
        personality=personality or "curious and friendly",
        hatched_at=time.time(),
    )
    save_companion(companion)
    return companion


# ── ASCII Sprites ────────────────────────────────────────────

SPRITES: dict[str, list[list[str]]] = {
    "duck": [
        ["            ", "    __      ", "  <({E} )___  ", "   (  ._>   ", "    `--´    "],
        ["            ", "    __      ", "  <({E} )___  ", "   (  ._>   ", "    `--´~   "],
        ["            ", "    __      ", "  <({E} )___  ", "   (  .__>  ", "    `--´    "],
    ],
    "cat": [
        ["            ", "   /\\_/\\    ", "  ( {E}   {E})  ", "  (  ω  )   ", '  (")_(")   '],
        ["            ", "   /\\_/\\    ", "  ( {E}   {E})  ", "  (  ω  )   ", '  (")_(")~  '],
        ["            ", "   /\\-/\\    ", "  ( {E}   {E})  ", "  (  ω  )   ", '  (")_(")   '],
    ],
    "blob": [
        ["            ", "   .----.   ", "  ( {E}  {E} )  ", "  (      )  ", "   `----´   "],
        ["            ", "   .----.   ", "  ( {E}  {E} )  ", "   (    )   ", "    `--´    "],
        ["            ", "  .------.  ", " (  {E}  {E}  ) ", " (        ) ", "  `------´  "],
    ],
    "dragon": [
        ["            ", "  /^\\  /^\\  ", " <  {E}  {E}  > ", " (   ~~   ) ", "  `-vvvv-´  "],
        ["            ", "  /^\\  /^\\  ", " <  {E}  {E}  > ", " (        ) ", "  `-vvvv-´  "],
        ["   ~    ~   ", "  /^\\  /^\\  ", " <  {E}  {E}  > ", " (   ~~   ) ", "  `-vvvv-´  "],
    ],
    "octopus": [
        ["            ", "   .----.   ", "  ( {E}  {E} )  ", "  (______)  ", "  /\\/\\/\\/\\  "],
        ["            ", "   .----.   ", "  ( {E}  {E} )  ", "  (______)  ", "  \\/\\/\\/\\/  "],
        ["     o      ", "   .----.   ", "  ( {E}  {E} )  ", "  (______)  ", "  /\\/\\/\\/\\  "],
    ],
    "owl": [
        ["            ", "   /\\  /\\   ", "  (({E})({E}))  ", "  (  ><  )  ", "   `----´   "],
        ["            ", "   /\\  /\\   ", "  (({E})({E}))  ", "  (  ><  )  ", "   .----.   "],
        ["            ", "   /\\  /\\   ", "  (({E})(-))  ", "  (  ><  )  ", "   `----´   "],
    ],
    "penguin": [
        ["            ", "  .---.     ", "  ({E}>{E})     ", " /(   )\\    ", "  `---´     "],
        ["            ", "  .---.     ", "  ({E}>{E})     ", " |(   )|    ", "  `---´     "],
        ["  .---.     ", "  ({E}>{E})     ", " /(   )\\    ", "  `---´     ", "   ~ ~      "],
    ],
    "ghost": [
        ["            ", "   .---.    ", "  ( {E} {E} )   ", "  (  o  )   ", "  /\\/\\/\\    "],
        ["            ", "    .---.   ", "   ( {E} {E} )  ", "   (  o  )  ", "   /\\/\\/\\   "],
        ["     ~      ", "   .---.    ", "  ( {E} {E} )   ", "  (  o  )   ", "  /\\/\\/\\    "],
    ],
    "turtle": [
        ["            ", "   _,--._   ", "  ( {E}  {E} )  ", " /[______]\\ ", "  ``    ``  "],
        ["            ", "   _,--._   ", "  ( {E}  {E} )  ", " /[______]\\ ", "   ``  ``   "],
        ["            ", "   _,--._   ", "  ( {E}  {E} )  ", " /[======]\\ ", "  ``    ``  "],
    ],
    "goose": [
        ["            ", "     ({E}>    ", "     ||     ", "   _(__)_   ", "    ^^^^    "],
        ["            ", "    ({E}>     ", "     ||     ", "   _(__)_   ", "    ^^^^    "],
        ["            ", "     ({E}>>   ", "     ||     ", "   _(__)_   ", "    ^^^^    "],
    ],
    "snail": [
        ["            ", " {E}    .--.  ", "  \\  ( @ )  ", "   \\_`--´   ", "  ~~~~~~~   "],
        ["            ", "  {E}   .--.  ", "  |  ( @ )  ", "   \\_`--´   ", "  ~~~~~~~   "],
        ["            ", " {E}    .--.  ", "  \\  ( @ )  ", "   \\_`--´   ", "   ~~~~~~   "],
    ],
    "axolotl": [
        ["            ", " \\\\  /\\  // ", "  ( {E}  {E} )  ", "  (  vv  )  ", "  ~~~~~~~~  "],
        ["            ", " \\\\  /\\  // ", "  ( {E}  {E} )  ", "  (  vv  )  ", "   ~~~~~~~  "],
        ["            ", "  \\\\ /\\ //  ", "  ( {E}  {E} )  ", "  (  vv  )  ", "  ~~~~~~~~  "],
    ],
    "capybara": [
        ["            ", "   .----.   ", "  ({E}    {E})  ", "  (  UU  )  ", "   `----´   "],
        ["            ", "   .----.   ", "  ({E}    {E})  ", "  (  UU  )  ", "   .----.   "],
        ["    ~       ", "   .----.   ", "  ({E}    {E})  ", "  (  UU  )  ", "   `----´   "],
    ],
    "cactus": [
        ["            ", "   .|.      ", "  ({E}{E})--   ", "   |.|      ", "  ~~~~~     "],
        ["            ", "   .|.      ", "  ({E}{E}) --  ", "   |.|      ", "  ~~~~~     "],
        ["    *       ", "   .|.      ", "  ({E}{E})--   ", "   |.|      ", "  ~~~~~     "],
    ],
    "robot": [
        ["   [===]    ", "  [  {E}{E}  ]  ", "  [______]  ", "   ||  ||   ", "   d´  `b   "],
        ["   [===]    ", "  [  {E}{E}  ]  ", "  [______]  ", "   ||  ||   ", "   d´  `b   "],
        ["   [=!=]    ", "  [  {E}{E}  ]  ", "  [______]  ", "   ||  ||   ", "   d´  `b   "],
    ],
    "rabbit": [
        ["   ()  ()   ", "   (\\  /)   ", "  ( {E}  {E} )  ", "  ( _vv_ )  ", "   `----´   "],
        ["   ()  ()   ", "   (\\  /)   ", "  ( {E}  {E} )  ", "  ( _vv_ )  ", "   .----.   "],
        ["    () ()   ", "    (\\ /)   ", "  ( {E}  {E} )  ", "  ( _vv_ )  ", "   `----´   "],
    ],
    "mushroom": [
        ["   .::::.   ", "  (::::::)  ", "   `{E}{E}´    ", "    ||      ", "   ~~~~     "],
        ["   .::::.   ", "  (::::::)  ", "   `{E}{E}´    ", "    ||      ", "    ~~~     "],
        ["   .:!!:.   ", "  (::::::)  ", "   `{E}{E}´    ", "    ||      ", "   ~~~~     "],
    ],
    "chonk": [
        ["            ", "  .------.  ", " ({E}        {E})", " (          )", "  `------´  "],
        ["            ", "  .------.  ", " ({E}        {E})", "  (        ) ", "   `----´   "],
        ["     z      ", "  .------.  ", " ({E}        {E})", " (          )", "  `------´  "],
    ],
}

HAT_SPRITES = {
    "none":      "            ",
    "crown":     "    ♔       ",
    "tophat":    "   ┌─┐      ",
    "propeller": "    ⌘       ",
    "halo":      "    ◯       ",
    "wizard":    "   /\\       ",
    "beanie":    "   ≈≈       ",
    "tinyduck":  "    🦆      ",
}

RARITY_COLORS = {
    "common": "dim",
    "uncommon": "green",
    "rare": "blue",
    "epic": "magenta",
    "legendary": "yellow",
}


def render_sprite(companion: Companion, frame: int = 0) -> str:
    """Render a companion as ASCII art."""
    species = companion.species
    if species not in SPRITES:
        species = "blob"  # fallback

    frames = SPRITES[species]
    f = frame % len(frames)
    lines = list(frames[f])

    # Replace eye placeholder
    for i, line in enumerate(lines):
        lines[i] = line.replace("{E}", companion.eye)

    # Add hat on first line
    if companion.hat != "none" and companion.hat in HAT_SPRITES:
        lines[0] = HAT_SPRITES[companion.hat]

    # Add shiny sparkle
    if companion.shiny:
        lines[0] = "  ✧ " + lines[0][4:]

    return "\n".join(lines)


def render_stat_card(companion: Companion) -> str:
    """Render a companion stat card."""
    lines = []
    stars = RARITY_STARS.get(companion.rarity, "★")
    lines.append(f"  {companion.name} ({companion.species})")
    lines.append(f"  {stars} {companion.rarity}")
    if companion.shiny:
        lines.append("  ✧ SHINY ✧")
    lines.append("")
    for stat_name in STAT_NAMES:
        val = companion.stats.get(stat_name, 0)
        bar = "█" * (val // 10) + "░" * (10 - val // 10)
        lines.append(f"  {stat_name:<10} {bar} {val}")
    return "\n".join(lines)
