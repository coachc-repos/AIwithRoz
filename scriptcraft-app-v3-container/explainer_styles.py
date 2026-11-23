"""Board looks for the explainer renderer.

The default look is still the particle waves. A saved board look redraws the
same slides: handwriting that finishes on the spoken word, a camera (or a
wipe, or a peel) between ideas, and the presenter, clips, articles and
manual transitions left in place.

These looks follow the published descriptions of Lemo-Opuscar's Sketch & Board
styles. They are not a copy of that project's code, fonts or media. See
STYLE_LOOKS_NOTICE.txt.
"""
from __future__ import annotations

import math
import re
from typing import Optional

FILM_LOOKS = ("waves", "whiteboard", "chalkboard", "sketchnote", "marker",
               "tilt", "island", "tabletop", "popup")
FILM_LOOK_DEFAULT = "waves"
BOARD_LOOKS = ("whiteboard", "chalkboard", "sketchnote", "marker")
THREE_LOOKS = ("tilt", "island", "tabletop", "popup")
# 6% of the 1920x1080 frame stays clear of type while the camera moves.
FRAME_MARGIN = 0.06
LOOK_TEST_SECONDS = 120.0
# Hidden project that holds a bundled sample when no explainer is open.
# list_projects skips it so it never shows up as one of the user's videos.
LOOK_TEST_ID = "20000101_000000_a11c"

# A cell on the big board, in the same pixel space the camera travels.
CELL_W, CELL_H = 1860.0, 1040.0
CELL_GAP_X, CELL_GAP_Y = 160.0, 180.0
# The approved phone symbol is 82 by 168, about 1:2.05.
PHONE_RATIO = 168 / 82


def film_look_key(choice: Optional[str] = None, saved: Optional[str] = None) -> str:
    """Which look to draw. An explicit choice wins, then a saved look, then waves.

    An unknown value is not a choice, so the current look stays.
    """
    if choice in FILM_LOOKS:
        return choice
    if saved in FILM_LOOKS:
        return saved
    return FILM_LOOK_DEFAULT


def hand_ease(u: float) -> float:
    """Slow, then fast, then slow. Zero at the start of a stroke, one at the end."""
    u = 0.0 if u < 0 else 1.0 if u > 1 else u
    return u - math.sin(2 * math.pi * u) / (2 * math.pi) * 0.8


def stroke_progress(t: float, t0: float, t1: float) -> float:
    """How much of a stroke is on the board at time t. It finishes at t1."""
    if t1 <= t0:
        return 1.0 if t >= t1 else 0.0
    if t <= t0:
        return 0.0
    if t >= t1:
        return 1.0
    return hand_ease((t - t0) / (t1 - t0))


def _glyph(width: float, spec: str) -> dict:
    strokes = []
    for part in spec.split("|"):
        pts = []
        for pair in part.split():
            x, y = pair.split(",")
            pts.append([round(float(x), 3), round(float(y), 3)])
        if len(pts) == 1:
            pts.append([round(pts[0][0] + 0.04, 3), round(pts[0][1] + 0.04, 3)])
        if len(pts) >= 2:
            strokes.append(pts)
    return {"w": width, "s": strokes}


# Single-stroke forms. Coordinates run 0–1 across the glyph, top to bottom.
# Built for this renderer. Not a third-party font.
_GLYPH_SPEC = {
    "A": (0.72, "0.16,1 0.50,0.06 0.84,1|0.30,0.62 0.70,0.62"),
    "B": (0.68, "0.18,0.98 0.18,0.06|0.18,0.06 0.58,0.06 0.74,0.22 0.58,0.48 0.18,0.48|0.20,0.48 0.64,0.48 0.78,0.70 0.62,0.98 0.18,0.98"),
    "C": (0.66, "0.78,0.22 0.55,0.06 0.28,0.16 0.14,0.48 0.28,0.84 0.55,0.96 0.80,0.78"),
    "D": (0.70, "0.18,0.98 0.18,0.06|0.18,0.06 0.52,0.06 0.82,0.28 0.82,0.72 0.52,0.98 0.18,0.98"),
    "E": (0.62, "0.78,0.08 0.20,0.08 0.20,0.96 0.76,0.96|0.20,0.50 0.62,0.50"),
    "F": (0.60, "0.78,0.08 0.22,0.08 0.22,0.98|0.22,0.50 0.64,0.50"),
    "G": (0.70, "0.78,0.24 0.56,0.06 0.26,0.14 0.12,0.48 0.26,0.86 0.58,0.96 0.82,0.72 0.82,0.52 0.52,0.52"),
    "H": (0.72, "0.18,0.04 0.18,0.98|0.18,0.50 0.80,0.50|0.80,0.04 0.80,0.98"),
    "I": (0.36, "0.18,0.08 0.18,0.96"),
    "J": (0.52, "0.62,0.06 0.62,0.72 0.46,0.96 0.22,0.86"),
    "K": (0.70, "0.18,0.04 0.18,0.98|0.74,0.08 0.22,0.52 0.76,0.98"),
    "L": (0.58, "0.20,0.06 0.20,0.96 0.74,0.96"),
    "M": (0.86, "0.12,0.98 0.12,0.12 0.48,0.58 0.84,0.12 0.84,0.98"),
    "N": (0.74, "0.16,0.98 0.16,0.10 0.82,0.92 0.82,0.06"),
    "O": (0.72, "0.50,0.06 0.82,0.22 0.88,0.52 0.78,0.86 0.50,0.98 0.22,0.86 0.12,0.52 0.22,0.18 0.50,0.06 0.62,0.08"),
    "P": (0.64, "0.18,0.98 0.18,0.08|0.18,0.08 0.60,0.08 0.78,0.26 0.60,0.50 0.18,0.50"),
    "Q": (0.74, "0.50,0.06 0.80,0.22 0.86,0.52 0.74,0.84 0.48,0.96 0.22,0.84 0.14,0.50 0.24,0.18 0.50,0.06|0.58,0.70 0.86,0.98"),
    "R": (0.68, "0.18,0.98 0.18,0.08|0.18,0.08 0.60,0.08 0.76,0.26 0.58,0.48 0.18,0.48|0.46,0.48 0.80,0.98"),
    "S": (0.62, "0.74,0.18 0.52,0.06 0.24,0.16 0.20,0.36 0.70,0.62 0.74,0.80 0.50,0.96 0.22,0.84"),
    "T": (0.66, "0.12,0.10 0.88,0.10|0.50,0.10 0.50,0.98"),
    "U": (0.72, "0.16,0.08 0.16,0.70 0.36,0.96 0.64,0.96 0.84,0.70 0.84,0.08"),
    "V": (0.70, "0.12,0.08 0.50,0.98 0.88,0.08"),
    "W": (0.90, "0.08,0.08 0.28,0.98 0.50,0.42 0.72,0.98 0.92,0.08"),
    "X": (0.70, "0.14,0.08 0.86,0.98|0.86,0.08 0.14,0.98"),
    "Y": (0.68, "0.12,0.08 0.50,0.48 0.88,0.08|0.50,0.48 0.50,0.98"),
    "Z": (0.66, "0.16,0.10 0.84,0.10 0.18,0.96 0.84,0.96"),
    "a": (0.62, "0.72,0.46 0.48,0.40 0.24,0.52 0.22,0.74 0.42,0.92 0.70,0.86 0.74,0.48 0.74,0.96"),
    "b": (0.62, "0.22,0.08 0.22,0.96|0.22,0.52 0.48,0.46 0.70,0.64 0.62,0.90 0.36,0.96 0.22,0.82"),
    "c": (0.56, "0.70,0.50 0.48,0.42 0.24,0.56 0.24,0.78 0.48,0.94 0.70,0.84"),
    "d": (0.64, "0.74,0.08 0.74,0.96|0.74,0.56 0.50,0.44 0.26,0.62 0.24,0.86 0.46,0.96 0.74,0.80"),
    "e": (0.60, "0.22,0.66 0.70,0.62 0.68,0.48 0.42,0.42 0.22,0.58 0.24,0.82 0.48,0.96 0.70,0.86"),
    "f": (0.46, "0.62,0.10 0.40,0.04 0.28,0.18 0.30,0.98|0.16,0.42 0.52,0.42"),
    "g": (0.62, "0.70,0.48 0.46,0.42 0.24,0.58 0.26,0.82 0.50,0.94 0.72,0.78|0.70,0.48 0.72,1.12 0.48,1.24 0.26,1.10"),
    "h": (0.62, "0.20,0.06 0.20,0.98|0.20,0.58 0.42,0.46 0.68,0.58 0.68,0.98"),
    "i": (0.32, "0.18,0.22 0.22,0.26|0.20,0.46 0.20,0.96"),
    "j": (0.40, "0.28,0.22 0.32,0.26|0.30,0.46 0.30,1.08 0.14,1.22"),
    "k": (0.60, "0.20,0.08 0.20,0.98|0.62,0.48 0.22,0.70 0.64,0.98"),
    "l": (0.32, "0.18,0.06 0.18,0.86 0.32,0.98"),
    "m": (0.84, "0.12,0.98 0.12,0.50|0.12,0.60 0.28,0.46 0.44,0.58 0.44,0.98|0.44,0.60 0.60,0.46 0.78,0.58 0.78,0.98"),
    "n": (0.64, "0.16,0.98 0.16,0.50|0.16,0.60 0.38,0.46 0.62,0.60 0.62,0.98"),
    "o": (0.62, "0.46,0.42 0.70,0.56 0.68,0.78 0.46,0.96 0.22,0.78 0.20,0.56 0.40,0.42 0.56,0.44"),
    "p": (0.62, "0.20,0.46 0.20,1.22|0.20,0.56 0.46,0.44 0.68,0.60 0.62,0.84 0.40,0.96 0.20,0.82"),
    "q": (0.64, "0.72,0.46 0.72,1.22|0.72,0.58 0.48,0.44 0.24,0.62 0.26,0.86 0.50,0.96 0.72,0.80"),
    "r": (0.46, "0.16,0.98 0.16,0.50|0.16,0.62 0.36,0.46 0.58,0.50"),
    "s": (0.52, "0.62,0.50 0.40,0.42 0.20,0.54 0.48,0.70 0.64,0.80 0.40,0.96 0.18,0.86"),
    "t": (0.42, "0.28,0.16 0.28,0.84 0.46,0.98|0.12,0.42 0.50,0.42"),
    "u": (0.64, "0.16,0.46 0.16,0.78 0.36,0.96 0.58,0.84 0.62,0.46|0.62,0.70 0.62,0.98"),
    "v": (0.60, "0.12,0.46 0.40,0.98 0.70,0.46"),
    "w": (0.80, "0.08,0.48 0.24,0.98 0.44,0.62 0.62,0.98 0.80,0.48"),
    "x": (0.58, "0.14,0.48 0.70,0.98|0.70,0.48 0.14,0.98"),
    "y": (0.60, "0.12,0.46 0.40,0.82|0.70,0.46 0.28,1.16 0.12,1.06"),
    "z": (0.56, "0.16,0.48 0.68,0.48 0.18,0.96 0.70,0.96"),
    "0": (0.64, "0.50,0.06 0.80,0.24 0.84,0.52 0.74,0.84 0.50,0.98 0.24,0.84 0.14,0.52 0.22,0.22 0.50,0.06"),
    "1": (0.42, "0.16,0.28 0.40,0.08 0.40,0.96"),
    "2": (0.64, "0.16,0.28 0.28,0.08 0.58,0.08 0.78,0.26 0.20,0.96 0.80,0.96"),
    "3": (0.62, "0.16,0.16 0.50,0.06 0.74,0.22 0.50,0.48 0.76,0.70 0.52,0.96 0.18,0.84"),
    "4": (0.64, "0.62,0.98 0.62,0.08 0.14,0.62 0.78,0.62"),
    "5": (0.62, "0.74,0.08 0.22,0.08 0.18,0.48 0.52,0.42 0.76,0.60 0.70,0.88 0.40,0.98 0.16,0.84"),
    "6": (0.62, "0.72,0.18 0.46,0.06 0.22,0.36 0.18,0.66 0.36,0.96 0.64,0.90 0.74,0.66 0.52,0.50 0.22,0.58"),
    "7": (0.62, "0.14,0.10 0.80,0.10 0.32,0.98"),
    "8": (0.62, "0.48,0.48 0.22,0.28 0.36,0.06 0.66,0.10 0.74,0.32 0.48,0.48 0.22,0.70 0.36,0.96 0.66,0.94 0.76,0.70 0.48,0.48"),
    "9": (0.62, "0.28,0.84 0.52,0.96 0.76,0.66 0.80,0.36 0.58,0.08 0.30,0.14 0.22,0.36 0.42,0.50 0.74,0.42"),
    ".": (0.28, "0.20,0.90 0.28,0.98"),
    ",": (0.28, "0.24,0.86 0.30,0.96 0.16,1.10"),
    "!": (0.30, "0.18,0.06 0.18,0.68|0.16,0.90 0.22,0.98"),
    "?": (0.52, "0.12,0.22 0.28,0.06 0.58,0.06 0.74,0.24 0.48,0.48 0.40,0.68|0.38,0.90 0.44,0.98"),
    "'": (0.24, "0.16,0.06 0.22,0.22"),
    "-": (0.46, "0.08,0.58 0.84,0.58"),
    ":": (0.28, "0.18,0.32 0.24,0.38|0.18,0.78 0.24,0.86"),
    ";": (0.28, "0.18,0.32 0.24,0.38|0.22,0.74 0.26,0.86 0.12,1.02"),
}


def glyphs() -> dict:
    return {ch: _glyph(w, spec) for ch, (w, spec) in _GLYPH_SPEC.items()}


_GLYPHS = glyphs()


def glyph_of(ch: str) -> dict:
    if ch in _GLYPHS:
        return _GLYPHS[ch]
    up = ch.upper()
    if up in _GLYPHS:
        return _GLYPHS[up]
    return _GLYPHS["?"]


def schedule_word(text: str, t0: float, t1: float) -> list:
    """Stroke times for one spoken word. The last stroke ends at t1.

    Every stroke sits inside [t0, t1], in writing order. A space has no strokes.
    """
    t0, t1 = float(t0), float(t1)
    if t1 < t0:
        t0, t1 = t1, t0
    pieces = []
    for ch in text or "":
        if ch.isspace():
            pieces.append((ch, 0))
            continue
        pieces.append((ch, len(glyph_of(ch)["s"])))
    total = sum(n for _, n in pieces) or 1
    span = max(0.04, t1 - t0)
    cursor = t0
    out = []
    for ch, n in pieces:
        times = []
        for _i in range(n):
            dur = span / total
            times.append([round(cursor, 4), round(min(t1, cursor + dur), 4)])
            cursor += dur
        out.append({"ch": ch, "n": n, "times": times})
    # The word is finished when the narrator finishes it.
    for item in reversed(out):
        if item["times"]:
            item["times"][-1][1] = round(t1, 4)
            break
    return out


def _tokens(text: str) -> list:
    return re.findall(r"[A-Za-z0-9']+", text or "")


def words_in_window(words: list, t0: float, t1: float) -> list:
    out = []
    for w in words or []:
        try:
            start = float(w.get("start"))
        except (TypeError, ValueError):
            continue
        if t0 - 0.02 <= start < t1 - 0.01 and (w.get("text") or "").strip():
            out.append(w)
    return out


def _match_spoken(board_words: list, spoken: list) -> list:
    """Pair each board word with a narration word, in order. Unmatched words
    are returned with no timing so the caller can spread them."""
    pairs = []
    i = 0
    for raw in board_words:
        key = re.sub(r"[^a-z0-9']", "", raw.lower())
        hit = None
        while i < len(spoken):
            have = re.sub(r"[^a-z0-9']", "", str(spoken[i].get("text") or "").lower())
            i += 1
            if have and have == key:
                hit = spoken[i - 1]
                break
        pairs.append((raw, hit))
    return pairs


# Palettes follow the published colour logic for each look. The numbers are
# the ones those descriptions name, used here as a paint recipe, not as assets.
PALETTES = {
    "whiteboard": {
        "board": "#f3f0e8", "board2": "#e4ddd0", "ink": "#23262c", "blue": "#2a5cb3",
        "accent": "#d97757", "ghost": "#8e97a6", "sheen": "#ffffff", "frame": "#d9d3c7",
        "emphasis": "#2a5cb3",
    },
    "chalkboard": {
        "board": "#143328", "board2": "#10281f", "ink": "#f4f1ea", "blue": "#f4f1ea",
        "accent": "#e39b4a", "ghost": "#143328", "sheen": "#000000", "frame": "#6b4528",
        "wall": "#efe6d6", "emphasis": "#e39b4a",
    },
    "sketchnote": {
        "board": "#fbfaf6", "board2": "#f3f1ea", "ink": "#1e1e22", "blue": "#1f8a8a",
        "accent": "#e2b000", "accent2": "#e07a2f", "ghost": "#e4e0d6", "sheen": "#000000",
        "frame": "#fbfaf6", "emphasis": "#e2b000",
    },
    "marker": {
        "board": "#faf9f5", "board2": "#f3f1ea", "ink": "#1b1c20", "blue": "#2456d6",
        "accent": "#e23b2e", "ghost": "#faf9f5", "sheen": "#000000", "frame": "#faf9f5",
        "emphasis": "#e23b2e",
    },
}


def ink_rules(look: str) -> dict:
    look = film_look_key(look)
    return {
        "multiply": look in ("whiteboard", "marker", "sketchnote"),
        "pool": look == "whiteboard",
        "dry": look == "whiteboard",
        "overshoot": 0.08 if look != "chalkboard" else 0.02,
        "pen": look == "whiteboard",
        "magnets": look == "whiteboard",
        "pullback": look in ("whiteboard", "sketchnote"),
        "dots": look == "sketchnote",
        "chalk": look == "chalkboard",
        "peel": look == "marker",
    }


def native_style(look: str, kind: str = "") -> str:
    """What an automatic transition becomes on a board. Manual chips are not passed here."""
    if look == "chalkboard":
        return "wipe"
    if look == "marker":
        return "peel"
    if look == "whiteboard" and kind == "chapter":
        return "wipe"
    return "camera"


def kept_fx(slide: dict, look: str) -> str:
    """The effect the page should still run.

    Waves keep every effect. A board look keeps a hand-picked chip and replaces
    an automatic glitch-style effect with a camera move, an eraser wipe or a peel.
    """
    style = (slide or {}).get("fx") or ""
    if film_look_key(look) == "waves" or not style:
        return style
    if (slide or {}).get("fx_origin") == "manual":
        return style
    return ""


def camera_keys(regions: list, look: str, duration: float) -> list:
    """Pen-led moves between regions, a hold while a region is read, and a
    pull-back on the looks that end on the whole board."""
    look = film_look_key(look)
    duration = max(0.5, float(duration or 0))
    if not regions:
        return [{"t": 0.0, "x": 960.0, "y": 540.0, "z": 1.0}]
    if look in ("chalkboard", "marker"):
        r = regions[0]
        cx, cy = r["x"] + r["w"] / 2, r["y"] + r["h"] / 2
        z = 1780.0 / max(1.0, r["w"])
        keys = [{"t": 0.0, "x": round(cx, 1), "y": round(cy, 1), "z": round(z, 4)}]
        if look == "chalkboard":
            # Once, late, the frame opens enough to show the wood around the slate.
            keys.append({"t": round(max(0.0, duration - 2.4), 3), "x": round(cx, 1),
                         "y": round(cy, 1), "z": round(z, 4)})
            keys.append({"t": round(max(0.2, duration - 0.4), 3), "x": round(cx, 1),
                         "y": round(cy, 1), "z": round(z * 0.78, 4)})
        return keys
    keys = []
    for i, r in enumerate(regions):
        cx, cy = r["x"] + r["w"] / 2, r["y"] + r["h"] / 2
        z = 1780.0 / max(1.0, r["w"])
        arrive = float(r["t0"]) + (0.05 if i == 0 else 0.55)
        depart = float(r["t0"]) - 0.05
        if i == 0:
            keys.append({"t": 0.0, "x": round(cx, 1), "y": round(cy, 1), "z": round(z * 1.08, 4)})
            keys.append({"t": round(min(duration, arrive), 3), "x": round(cx, 1), "y": round(cy, 1), "z": round(z, 4)})
        else:
            keys.append({"t": round(max(0.0, depart), 3), "x": keys[-1]["x"], "y": keys[-1]["y"], "z": keys[-1]["z"]})
            keys.append({"t": round(min(duration, max(depart + 0.05, arrive)), 3),
                         "x": round(cx, 1), "y": round(cy, 1), "z": round(z, 4)})
    if ink_rules(look)["pullback"] and regions:
        xs = [r["x"] for r in regions] + [r["x"] + r["w"] for r in regions]
        ys = [r["y"] for r in regions] + [r["y"] + r["h"] for r in regions]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        z_fit = min(1840.0 / max(1.0, max(xs) - min(xs)), 1000.0 / max(1.0, max(ys) - min(ys)))
        # Do not pull back so far that a 64px label becomes a speck.
        z = max(z_fit, 0.55)
        t_back = max(keys[-1]["t"] + 0.2, duration - 2.2)
        keys.append({"t": round(min(duration, t_back), 3), "x": keys[-1]["x"], "y": keys[-1]["y"], "z": keys[-1]["z"]})
        keys.append({"t": round(duration, 3), "x": round(cx, 1), "y": round(cy, 1), "z": round(z, 4)})
    keys.sort(key=lambda k: k["t"])
    # Two keys at the same time would skip the move. Nudge the later one.
    for i in range(1, len(keys)):
        if keys[i]["t"] <= keys[i - 1]["t"]:
            keys[i]["t"] = round(keys[i - 1]["t"] + 0.05, 3)
    return keys


def _ease_cam(p: float) -> float:
    p = 0.0 if p < 0 else 1.0 if p > 1 else p
    return p * p * (3 - 2 * p)


def camera_at(t: float, keys: list) -> dict:
    if not keys:
        return {"x": 960.0, "y": 540.0, "z": 1.0}
    t = float(t)
    if t <= keys[0]["t"]:
        return {"x": keys[0]["x"], "y": keys[0]["y"], "z": keys[0]["z"]}
    if t >= keys[-1]["t"]:
        return {"x": keys[-1]["x"], "y": keys[-1]["y"], "z": keys[-1]["z"]}
    for a, b in zip(keys, keys[1:]):
        if a["t"] <= t <= b["t"]:
            span = max(1e-6, b["t"] - a["t"])
            p = _ease_cam((t - a["t"]) / span)
            return {"x": a["x"] + (b["x"] - a["x"]) * p, "y": a["y"] + (b["y"] - a["y"]) * p,
                    "z": a["z"] + (b["z"] - a["z"]) * p}
    return {"x": keys[-1]["x"], "y": keys[-1]["y"], "z": keys[-1]["z"]}


_SC_RE = re.compile(
    r'data-sc="([a-z0-9-]+)"[^>]*?\bx="([\d.]+)"\s+y="([\d.]+)"\s+width="([\d.]+)"\s+height="([\d.]+)"')
_PILL_RE = re.compile(r'class="sc-pill"[^>]*>([^<]+)')


def objects_in_section(html: str, sid: str) -> list:
    if not html or not sid:
        return []
    m = re.search(r'id="' + re.escape(sid) + r'"[\s\S]*?</section>', html)
    chunk = m.group(0) if m else ""
    pill = _PILL_RE.search(chunk)
    label = pill.group(1).strip() if pill else ""
    found = []
    for name, x, y, w, h in _SC_RE.findall(chunk):
        found.append({"name": name, "x": float(x), "y": float(y), "w": float(w), "h": float(h),
                      "label": label if name in ("brand", "bot") else ""})
    return found[:8]


def _region_box(index: int, look: str) -> tuple:
    if look in ("chalkboard", "marker"):
        return 160.0, 120.0
    col = index % 3
    row = index // 3
    return 180.0 + col * (CELL_W + CELL_GAP_X), 160.0 + row * (CELL_H + CELL_GAP_Y)


def _color_for(look: str, role: str) -> str:
    pal = PALETTES[look]
    if role == "accent":
        return pal["accent"]
    if role == "given":
        return pal["blue"]
    if role == "answer":
        return pal["accent"]
    return pal["ink"]


def _layout_region(slide: dict, index: int, look: str, spoken: list, html: str) -> dict:
    x, y = _region_box(index, look)
    t0, t1 = float(slide.get("t0") or 0), float(slide.get("t1") or 0)
    if t1 <= t0:
        t1 = t0 + 1.0
    text = (slide.get("spoken") or slide.get("text") or slide.get("idea") or "").strip()
    board_words = _tokens(text)[:14]
    if not board_words:
        board_words = ["…"]
    pairs = _match_spoken(board_words, spoken)
    # Words the narration did not name are spread across the slide so they
    # still get written, after the matched ones.
    unmatched = [(raw, hit) for raw, hit in pairs if hit is None]
    if unmatched:
        span = max(0.4, t1 - t0 - 0.3)
        step = span / len(unmatched)
        cursor = t0 + 0.15
        fixed = []
        for raw, hit in pairs:
            if hit is not None:
                fixed.append((raw, hit))
                continue
            dur = min(0.45, step * 0.8)
            fixed.append((raw, {"text": raw, "start": cursor, "end": cursor + dur}))
            cursor += step
        pairs = fixed
    host = slide.get("host") or ""
    text_w = CELL_W * (0.56 if host == "pip" else 0.86)
    lines = []
    letters = []
    size_title = 120.0 if slide.get("kind") == "chapter" else 108.0
    size_body = 64.0
    cx, cy = x + 90.0, y + 110.0
    # First line is the title (up to four words). The rest wrap underneath.
    title_n = min(4, len(pairs)) if slide.get("kind") == "chapter" else min(3, len(pairs))
    chunks = [pairs[:title_n], pairs[title_n:]]
    sizes = [size_title, size_body]
    for li, (chunk, size) in enumerate(zip(chunks, sizes)):
        if not chunk:
            continue
        cursor_x = cx
        line_y = cy if li == 0 else cy + size_title + 36 + (li - 1) * (size_body + 28)
        max_x = x + 90 + text_w
        words_out = []
        for wi, (raw, hit) in enumerate(chunk):
            start = float(hit.get("start") or t0)
            end = float(hit.get("end") or start + 0.3)
            if end <= start:
                end = start + 0.18
            role = "ink"
            if look == "marker":
                if wi == len(chunk) - 1 and li == len([c for c in chunks if c]) - 1:
                    role = "answer"
                elif wi == 0 and li == 1:
                    role = "given"
            elif wi == len(chunk) - 1 and li == 0:
                role = "accent"
            scheduled = schedule_word(raw, start, end)
            width = 0.0
            for item in scheduled:
                width += glyph_of(item["ch"])["w"] * size * 0.62
                if item["ch"].isspace():
                    width += size * 0.28
            width += size * 0.34
            if cursor_x + width > max_x and cursor_x > cx + 10:
                line_y += size + 22
                cursor_x = cx
            color = _color_for(look, role)
            word_letters = []
            pen_x = cursor_x
            for item in scheduled:
                g = glyph_of(item["ch"])
                if item["ch"].isspace() or not item["times"]:
                    pen_x += size * 0.28
                    continue
                letter = {"ch": item["ch"], "x": round(pen_x, 1), "y": round(line_y, 1),
                          "size": size, "color": color, "region": index,
                          "strokes": [{"i": i, "t0": a, "t1": b} for i, (a, b) in enumerate(item["times"])]}
                letters.append(letter)
                word_letters.append(letter)
                pen_x += g["w"] * size * 0.62
            words_out.append({"text": raw, "t0": round(start, 4), "t1": round(end, 4), "role": role})
            cursor_x = pen_x + size * 0.34
        if words_out:
            lines.append({"y": line_y, "size": size, "banner": look == "sketchnote" and li == 0,
                          "words": words_out})
    objs = []
    for ob in objects_in_section(html, slide.get("id") or ""):
        ox = x + 980
        oy = y + 180
        if ob["name"] == "phone":
            ow, oh = 340.0, round(340.0 * PHONE_RATIO, 1)
        elif ob["name"] == "chart":
            ow, oh = 720.0, 520.0
        else:
            ow = max(280.0, ob["w"] * 1.4)
            oh = max(220.0, ob["h"] * 1.4)
        objs.append({"name": ob["name"], "x": round(ox, 1), "y": round(oy, 1),
                     "w": round(ow, 1), "h": round(oh, 1), "label": ob.get("label") or "",
                     "t0": round(t0 + 0.1, 3), "t1": round(min(t1, t0 + 1.1), 3)})
    if objs and look == "whiteboard":
        objs[0]["magnet"] = True
    return {"id": slide.get("id") or f"r{index}", "i": index, "x": x, "y": y, "w": CELL_W, "h": CELL_H,
            "t0": round(t0, 3), "t1": round(t1, 3), "kind": slide.get("kind") or "slide",
            "host": host, "lines": lines, "letters": letters, "objects": objs}


def _box_hits(a: dict, b: dict, pad: float = 0.0) -> bool:
    return (a["x"] < b["x"] + b["w"] + pad and a["x"] + a["w"] + pad > b["x"]
            and a["y"] < b["y"] + b["h"] + pad and a["y"] + a["h"] + pad > b["y"])


def chart_label_layout(chart: dict) -> list:
    """Bar rects and the label under each one, in world pixels.

    Each label is sized to the slot, with padding, so it stays inside its
    own column and does not touch the bar or the next label.
    """
    x, y = float(chart["x"]), float(chart["y"])
    w, h = float(chart["w"]), float(chart["h"])
    bars = [float(v) for v in (chart.get("bars") or [])]
    labels = [str(s) for s in (chart.get("labels") or [])]
    n = len(bars)
    if n == 0 or h < 40 or w < 40:
        return []
    gap = w / (n + 0.4)
    band = min(72.0, h * 0.22)
    pad = 8.0
    out = []
    for i, frac in enumerate(bars):
        slot_x = x + gap * 0.15 + i * gap
        slot_w = gap * 0.92
        bw = max(10.0, slot_w - 2 * pad)
        bx = slot_x + (slot_w - bw) / 2
        bar_bottom = y + h - band
        bar_top = y + 18.0
        bh = max(10.0, (bar_bottom - bar_top) * max(0.08, min(1.0, frac)))
        by = bar_bottom - bh
        text = labels[i] if i < len(labels) else ""
        size = 30.0
        if text:
            size = min(30.0, (slot_w - 2 * pad) / max(1.0, len(text) * 0.62))
            size = max(14.0, size)
        tw = len(text) * size * 0.62 if text else 0.0
        th = size * 1.1 if text else 0.0
        while text and tw > slot_w - 2 * pad and size > 12:
            size = round(size * 0.9, 2)
            tw = len(text) * size * 0.62
            th = size * 1.1
        lx = slot_x + (slot_w - tw) / 2.0
        ly = bar_bottom + pad
        if ly + th > y + h - 2:
            ly = y + h - 2 - th
        out.append({
            "text": text,
            "size": round(size, 2),
            "bar": {"x": round(bx, 2), "y": round(by, 2), "w": round(bw, 2), "h": round(bh, 2)},
            "slot": {"x": round(slot_x, 2), "y": round(y, 2), "w": round(slot_w, 2), "h": round(h, 2)},
            "label": {"x": round(lx, 2), "y": round(ly, 2), "w": round(tw, 2), "h": round(th, 2)},
        })
    return out


def labels_clear_of_bars(layout: list) -> bool:
    """True when every label is inside its slot and misses every bar and neighbour."""
    for i, item in enumerate(layout):
        lab, slot, bar = item["label"], item["slot"], item["bar"]
        if lab["w"] <= 0:
            continue
        if lab["x"] < slot["x"] + 4 or lab["x"] + lab["w"] > slot["x"] + slot["w"] - 4:
            return False
        if lab["y"] < slot["y"] or lab["y"] + lab["h"] > slot["y"] + slot["h"] + 0.5:
            return False
        if _box_hits(lab, bar, pad=1):
            return False
        for j, other in enumerate(layout):
            if i == j:
                continue
            if _box_hits(lab, other["label"], pad=1) or _box_hits(lab, other["bar"], pad=1):
                return False
    return True


def _text_box(text: str, x: float, y: float, size: float) -> dict:
    width = max(float(size), len(text) * float(size) * 0.62)
    return {"x": float(x), "y": float(y), "w": width, "h": float(size) * 1.2}


def framed_text_boxes(ops: list) -> list:
    """Every string the camera has to keep on screen."""
    boxes = []
    for op in ops or []:
        kind = op.get("op")
        if kind == "text":
            boxes.append(_text_box(op["text"], op["x"], op["y"], op["size"]))
        elif kind == "chip":
            boxes.append(_text_box(op.get("text") or "", op["x"] + 12, op["y"] + 8, 54))
        elif kind == "step" and op.get("label"):
            boxes.append(_text_box(op["label"], op["x"] + 52, op["y"] - 26, 52))
        elif kind == "callout":
            boxes.append(_text_box(op.get("text") or "", op["x"] + 16, op["y"] + 8, 48))
        elif kind == "chart":
            for item in op.get("labelLayout") or chart_label_layout(op):
                lab = item["label"]
                if lab["w"] > 0:
                    boxes.append(dict(lab))
    return boxes


def _project_box(box: dict, cam: dict) -> dict:
    z = float(cam["z"])
    x = 960.0 + (box["x"] - float(cam["x"])) * z
    y = 540.0 + (box["y"] - float(cam["y"])) * z
    return {"x": x, "y": y, "w": box["w"] * z, "h": box["h"] * z}


def texts_to_draw(ops: list, cam: dict, margin: float = FRAME_MARGIN) -> list:
    """Text blocks the renderer may paint. A block that would be sliced is left out."""
    safe = {"x": 1920 * margin, "y": 1080 * margin, "w": 1920 * (1 - 2 * margin), "h": 1080 * (1 - 2 * margin)}
    frame = {"x": -2, "y": -2, "w": 1924, "h": 1084}
    kept = []
    for box in framed_text_boxes(ops):
        screen = _project_box(box, cam)
        if not _box_hits(screen, frame):
            continue
        if (screen["x"] >= safe["x"] - 0.5 and screen["y"] >= safe["y"] - 0.5
                and screen["x"] + screen["w"] <= safe["x"] + safe["w"] + 0.5
                and screen["y"] + screen["h"] <= safe["y"] + safe["h"] + 0.5):
            kept.append(screen)
    return kept


def text_fits_frame(ops: list, cam: dict, margin: float = FRAME_MARGIN) -> bool:
    """Text that meets the frame is fully inside the safe margin.

    A block that is completely off screen is fine. One sliced by the edge is not.
    """
    safe = {"x": 1920 * margin, "y": 1080 * margin, "w": 1920 * (1 - 2 * margin), "h": 1080 * (1 - 2 * margin)}
    frame = {"x": -1, "y": -1, "w": 1922, "h": 1082}
    for box in framed_text_boxes(ops):
        screen = _project_box(box, cam)
        if not _box_hits(screen, frame):
            continue
        if (screen["x"] < safe["x"] or screen["y"] < safe["y"]
                or screen["x"] + screen["w"] > safe["x"] + safe["w"]
                or screen["y"] + screen["h"] > safe["y"] + safe["h"]):
            return False
    return True


def _letters_for_text(text: str, x: float, y: float, size: float, color: str,
                      t0: float, t1: float, region: int) -> list:
    letters = []
    for item in schedule_word(text, t0, t1):
        strokes = [{"i": i, "t0": a, "t1": b} for i, (a, b) in enumerate(item["times"])]
        if not strokes:
            continue
        letters.append({"ch": item["ch"], "x": x, "y": y, "size": size, "color": color,
                        "region": region, "strokes": strokes})
    return letters


def _narration_word(words: list, text: str):
    key = (text or "").lower()
    for w in words or []:
        if str(w.get("text") or "").lower() == key:
            return w
    return None


def compose_token_board(words: list, look: str, duration: float) -> dict:
    """One dense board about how ChatGPT picks the next token.

    Two idea clusters share the board. The camera frames each one tight,
    rides the arrow between them, then pulls back onto the whole board.
    Type sizes are chosen so a 1280x720 picture of this board still has a
    heading in the 64–90px range and body type in the 36–48px range.
    """
    look = film_look_key(look)
    pal = PALETTES[look]
    ink, accent = pal["ink"], pal["accent"]
    second = pal.get("accent2") or pal.get("blue") or accent
    third = "#1f8a8a" if look == "sketchnote" else (pal.get("blue") or ink)
    if look == "marker":
        second, third = accent, ink
    if look == "chalkboard":
        second, third = accent, ink
    token = _narration_word(words, "token") or {"start": 6.2, "end": 6.8}
    duration = max(8.0, float(duration or 20))

    def text(s, x, y, size, color, t0, t1, region=0):
        return {"op": "text", "text": s, "x": x, "y": y, "size": size, "color": color,
                "t0": round(t0, 3), "t1": round(t1, 3), "region": region}

    phone_w = 320.0
    phone_h = round(phone_w * PHONE_RATIO, 1)
    ops = [
        {"op": "plate", "x": 48, "y": 70, "w": 1080, "h": 940, "t0": 0.15, "t1": 0.55,
         "color": {"whiteboard": "rgba(42,92,179,0.13)", "sketchnote": "rgba(31,138,138,0.12)",
                   "chalkboard": "rgba(244,241,234,0.05)", "marker": "#f0e4d6"}[look], "region": 0},
        {"op": "plate", "x": 1480, "y": 150, "w": 560, "h": 820, "t0": 9.05, "t1": 9.45,
         "color": {"whiteboard": "rgba(217,119,87,0.14)", "sketchnote": "rgba(226,176,0,0.16)",
                   "chalkboard": "rgba(227,155,74,0.10)", "marker": "#f6e1d2"}[look], "region": 1},
        text("Next token", 110, 210, 96, accent if look != "marker" else ink, 0.25, 1.45),
        text("Reads the prompt", 110, 340, 56, ink, 1.45, 3.05),
        {"op": "step", "n": "1", "x": 92, "y": 470, "label": "Read the words", "t0": 2.3, "t1": 3.3,
         "color": ink, "fill": accent, "region": 0},
        {"op": "step", "n": "2", "x": 92, "y": 590, "label": "Cut into tokens", "t0": 3.2, "t1": 4.3,
         "color": ink, "fill": second, "region": 0},
        {"op": "phone", "x": 760, "y": 150, "w": phone_w, "h": phone_h, "t0": 0.45, "t1": 2.5,
         "magnet": look == "whiteboard", "color": ink,
         "fill": {"whiteboard": "rgba(42,92,179,0.82)", "sketchnote": "rgba(31,138,138,0.45)",
                  "chalkboard": "rgba(244,241,234,0.22)", "marker": "rgba(27,28,32,0.10)"}[look],
         "region": 0},
        {"op": "chip", "text": "The", "x": 120, "y": 760, "w": 150, "h": 78, "t0": 3.6, "t1": 4.2, "color": ink, "region": 0},
        {"op": "chip", "text": "cat", "x": 290, "y": 760, "w": 140, "h": 78, "t0": 4.2, "t1": 4.8, "color": ink, "region": 0},
        {"op": "chip", "text": "sat", "x": 450, "y": 760, "w": 140, "h": 78, "t0": 4.8, "t1": 5.4, "color": ink, "region": 0},
        {"op": "chip", "text": "on", "x": 610, "y": 760, "w": 120, "h": 78, "t0": 5.4, "t1": 6.0, "color": ink, "region": 0},
        {"op": "arrow", "x1": 700, "y1": 800, "x2": 860, "y2": 800, "t0": 5.8, "t1": 6.4, "color": second, "region": 0},
        text("token", 470, 860, 56, accent, float(token["start"]), float(token["end"])),
        {"op": "arrow", "x1": 1120, "y1": 520, "x2": 1460, "y2": 460, "t0": 8.3, "t1": 9.3, "color": second, "region": 0},
        text("The scores", 1560, 200, 72, accent if look != "marker" else ink, 9.3, 10.6, 1),
        text("Taller bar wins", 1560, 300, 48, ink, 10.5, 12.0, 1),
        {"op": "chart", "x": 1540, "y": 400, "w": 500, "h": 400, "t0": 10.2, "t1": 13.4,
         "bars": [0.42, 0.62, 0.34, 0.96], "labels": ["a", "the", "on", "mat"],
         "color": ink, "fill": accent, "magnet": look == "whiteboard", "region": 1},
        {"op": "step", "n": "3", "x": 1560, "y": 860, "label": "Score", "t0": 12.2, "t1": 13.2,
         "color": ink, "fill": third, "region": 1},
        {"op": "step", "n": "4", "x": 1780, "y": 860, "label": "Pick", "t0": 13.2, "t1": 14.3,
         "color": ink, "fill": accent, "region": 1},
    ]
    for op in ops:
        if op.get("op") == "chart":
            op["labelLayout"] = chart_label_layout(op)
    letters = []
    for op in ops:
        if op.get("op") == "text":
            letters.extend(_letters_for_text(op["text"], op["x"], op["y"], op["size"], op["color"],
                                             op["t0"], op["t1"], op.get("region") or 0))
        elif op.get("op") == "chip":
            letters.extend(_letters_for_text(op["text"], op["x"] + 16, op["y"] + 12, 42, op["color"],
                                             op["t0"], op["t1"], 0))
    regions = [
        {"id": "prompt", "i": 0, "x": 30, "y": 60, "w": 1100, "h": 960, "t0": 0.0, "t1": 9.0, "kind": "scene", "host": ""},
        {"id": "score", "i": 1, "x": 1160, "y": 60, "w": 920, "h": 960, "t0": 9.0, "t1": duration, "kind": "slide", "host": ""},
    ]
    camera = [
        {"t": 0.0, "x": 640, "y": 530, "z": 1.10},
        {"t": 7.4, "x": 640, "y": 530, "z": 1.10},
        {"t": 9.2, "x": 1058, "y": 560, "z": 0.78},
        {"t": 10.6, "x": 1800, "y": 530, "z": 1.10},
        {"t": 16.0, "x": 1800, "y": 530, "z": 1.10},
        {"t": 18.6, "x": 1058, "y": 560, "z": 0.78},
        {"t": round(duration, 3), "x": 1058, "y": 560, "z": 0.78},
    ]
    return {"ops": ops, "letters": letters, "regions": regions, "camera": camera,
            "board": {"w": 2100, "h": 1080}}


def film_payload(compiled: dict, words: Optional[list] = None, look: Optional[str] = None,
                 emphasis: Optional[dict] = None) -> dict:
    """What the board engine draws. Waves return a marker and nothing else,
    so the page stays the current look."""
    look = film_look_key(look)
    if look == "waves":
        return {"look": "waves"}
    if look in THREE_LOOKS:
        duration = float((compiled or {}).get("end") or (compiled or {}).get("duration") or 20)
        return {
            "look": look,
            "mode": "3d",
            "duration": duration,
            "ideas": [
                {"t0": 0.0, "t1": min(9.0, duration * 0.45), "title": "Next token",
                 "body": "ChatGPT reads the prompt"},
                {"t0": min(9.0, duration * 0.45), "t1": duration, "title": "The scores",
                 "body": "A taller bar is a likelier word"},
            ],
        }
    if (compiled or {}).get("packed") == "token":
        duration = float((compiled or {}).get("end") or (compiled or {}).get("duration") or 20)
        packed = compose_token_board(words or [], look, duration)
        return {
            "look": look,
            "palette": PALETTES[look],
            "ink": ink_rules(look),
            "regions": packed["regions"],
            "letters": packed["letters"],
            "ops": packed["ops"],
            "camera": packed["camera"],
            "board": packed["board"],
            "native": [],
            "manual": [],
            "emphasis": (emphasis or {}).get("marks") or [],
        }
    slides = list((compiled or {}).get("slides") or [])
    html = (compiled or {}).get("html") or ""
    regions = []
    letters = []
    for i, slide in enumerate(slides):
        if slide.get("kind") in ("intro", "end"):
            continue
        spoken = words_in_window(words or [], float(slide.get("t0") or 0), float(slide.get("t1") or 0))
        region = _layout_region(slide, len(regions), look, spoken, html)
        letters.extend(region.pop("letters"))
        regions.append(region)
    duration = float((compiled or {}).get("end") or (compiled or {}).get("duration") or 0)
    if regions:
        duration = max(duration, regions[-1]["t1"])
    native = []
    for slide in slides:
        style = slide.get("fx") or ""
        if not style or slide.get("fx_origin") == "manual":
            continue
        if slide.get("kind") in ("intro", "end"):
            continue
        native.append({"id": slide.get("id") or "", "t": float(slide.get("t0") or 0),
                       "dur": max(0.45, float(slide.get("fx_dur") or 0.6)),
                       "style": native_style(look, slide.get("kind") or "")})
    manual = [slide.get("id") for slide in slides
              if slide.get("fx") and slide.get("fx_origin") == "manual"]
    return {
        "look": look,
        "palette": PALETTES[look],
        "ink": ink_rules(look),
        "glyphs": _GLYPHS,
        "regions": regions,
        "letters": letters,
        "camera": camera_keys(regions, look, duration or 1),
        "native": native,
        "manual": manual,
        "emphasis": (emphasis or {}).get("marks") or [],
    }


def page_fx(slides: list, look: Optional[str] = None) -> list:
    """Effects the existing transition canvas should still play."""
    look = film_look_key(look)
    out = []
    for s in slides or []:
        style = kept_fx(s, look)
        if not style:
            continue
        out.append({"id": s.get("id"), "t": s.get("t0"), "dur": s.get("fx_dur"),
                    "style": style, "amp": s.get("fx_amp") or 1, "why": s.get("fx_reason") or "",
                    "manual": s.get("fx_origin") == "manual"})
    return out


def look_test_span(compiled: dict, *, seconds: float = LOOK_TEST_SECONDS,
                   clips: Optional[list] = None, articles: Optional[list] = None) -> dict:
    """The first stretch of the video, about two minutes, from the start.

    A presenter slide, a clip, an article and a transition that begin just
    after that window are pulled in when they are close. Ones far later stay
    in the full video. The hook is the opening. An intro that sits in the
    window is included.
    """
    slides = list((compiled or {}).get("slides") or [])
    start = float((compiled or {}).get("start") or 0)
    video_end = float((compiled or {}).get("end") or (compiled or {}).get("duration") or start)
    if video_end <= start and slides:
        video_end = max(float(s.get("t1") or start) for s in slides)
    seconds = max(5.0, float(seconds or LOOK_TEST_SECONDS))
    end = min(video_end, start + seconds) if video_end > start else start + seconds
    clip_ids = {c.get("slide") for c in (clips or []) if c.get("slide")}
    art_ids = {a.get("slide") for a in (articles or []) if a.get("slide")}
    clock = (compiled or {}).get("clock") or {}
    intro = clock.get("intro") or {}

    def first(pred):
        for s in slides:
            if pred(s):
                try:
                    return float(s.get("t0") or 0)
                except (TypeError, ValueError):
                    return 0.0
        return None

    interests = []
    presenter_t = first(lambda s: s.get("host"))
    clip_t = first(lambda s: s.get("id") in clip_ids)
    article_t = first(lambda s: s.get("id") in art_ids)
    trans_t = first(lambda s: s.get("fx"))
    if presenter_t is not None:
        interests.append(presenter_t)
    if clip_t is not None:
        interests.append(clip_t)
    if article_t is not None:
        interests.append(article_t)
    if trans_t is not None:
        interests.append(trans_t)
    try:
        intro_t = float(intro.get("wall0"))
    except (TypeError, ValueError):
        intro_t = None
    if intro_t is not None:
        interests.append(intro_t)
    limit = start + seconds + 40.0
    for t in interests:
        if start <= t < limit:
            end = max(end, min(video_end or t + 4, t + 6.0))
    if video_end > start:
        end = min(video_end, end)
    end = max(start + min(4.0, max(0.5, (video_end or start + 4) - start)), end)

    def inside(t):
        return t is not None and start - 0.05 <= t < end + 0.05

    chapter = first(lambda s: s.get("kind") == "chapter")
    hook = bool(slides) and (chapter is None or chapter > start + 0.2 or float(slides[0].get("t0") or 0) <= start + 0.05)
    return {
        "start": round(start, 3),
        "end": round(end, 3),
        "seconds": round(max(0.0, end - start), 3),
        "features": {
            "hook": hook and start <= float(slides[0].get("t0") or 0) < end if slides else False,
            "intro": inside(intro_t),
            "presenter": inside(presenter_t),
            "clip": inside(clip_t),
            "article": inside(article_t),
            "transition": inside(trans_t),
        },
    }


def _beat(sid, kind, t0, t1, spoken, *, host="", objects="", fx="", origin="", section=""):
    return {"id": sid, "kind": kind, "t0": t0, "t1": t1, "spoken": spoken, "text": spoken,
            "host": host, "fx": fx, "fx_origin": origin, "fx_dur": 0.6 if fx else 0,
            "fx_amp": 1, "fx_reason": origin, "section": section, "idea": spoken,
            "_objects": objects}


def sample_lesson() -> dict:
    """A bundled two-minute lesson used when no explainer project is open.

    It has a hook, an intro after the hook, a presenter slide, a clip, an
    article line, and a transition, so the test clip has each of those when
    the open project does not.
    """
    beats = [
        _beat("s01", "scene", 0.0, 8.0,
              "A question lands on your phone and the chatbot starts to think.",
              objects="phone"),
        _beat("s02", "chapter", 8.0, 12.0, "The path inside the model.", section="Path"),
        _beat("s03", "slide", 12.0, 28.0,
              "Here is the short version of how an answer gets made.",
              host="pip"),
        _beat("s04", "slide", 28.0, 46.0,
              "The model breaks the words into tokens and scores the next one.",
              objects="chart"),
        _beat("s05", "slide", 46.0, 64.0,
              "A short clip shows the same steps on a real screen.",
              fx="glitch", origin="auto"),
        _beat("s06", "slide", 64.0, 82.0,
              "The article says the model predicts one token at a time."),
        _beat("s07", "scene", 82.0, 100.0,
              "Nvidia builds the chips that run these models.",
              objects="brand"),
        _beat("s08", "slide", 100.0, 120.0,
              "That is the whole loop from question to reply.",
              fx="pixel", origin="manual"),
    ]
    words = []
    parts = []
    for b in beats:
        words.extend(_time_words(b["spoken"], b["t0"], b["t1"]))
        extra = ""
        if b["_objects"] == "phone":
            extra = '<svg class="sc" data-sc="phone" data-depth="1.2" x="1280" y="560" width="200" height="360" viewBox="0 0 82 168"></svg>'
        elif b["_objects"] == "chart":
            extra = '<svg class="sc" data-sc="chart" data-depth="1" x="1180" y="420" width="520" height="340" viewBox="0 0 200 130"></svg>'
        elif b["_objects"] == "brand":
            extra = ('<svg class="sc sc-brand" data-sc="brand" data-depth="1" x="700" y="280" width="460" height="460" '
                     'viewBox="0 0 520 520"></svg><div class="sc-pill">Nvidia</div>')
        host = f' data-host="{b["host"]}"' if b["host"] else ""
        parts.append(
            f'<section class="slide kind-{b["kind"]}" id="{b["id"]}" data-kind="{b["kind"]}" '
            f'data-t0="{b["t0"]:.3f}" data-t1="{b["t1"]:.3f}" data-hud="off" data-transition="cut"{host}>'
            f'<h1 class="h2">{b["spoken"]}</h1>{extra}</section>')
    slides = []
    for b in beats:
        slides.append({k: v for k, v in b.items() if k != "_objects"})
    return {
        "compiled": {"html": "\n".join(parts), "slides": slides, "duration": 120.0,
                     "start": 0.0, "end": 120.0, "sections": ["Path"], "host_windows": [],
                     "host_sections": [], "host_on": True,
                     "clock": {"intro": {"wall0": 8.0, "wall1": 12.0}, "intro_dur": 4.0}},
        "words": words,
        "clips": [{"id": "clip1", "slide": "s05", "t0": 46.0, "t1": 64.0, "audio": "mute"}],
        "articles": [{"id": "art1", "slide": "s06"}],
        "title": "How a chatbot answers",
    }


def demo_lesson() -> dict:
    """About twenty seconds on how ChatGPT predicts the next token."""
    beats = [
        _beat("d1", "scene", 0.0, 9.0,
              "ChatGPT reads your prompt and cuts it into a token.", objects="phone"),
        _beat("d2", "slide", 9.0, 20.0,
              "Then it scores the next word and the tallest bar wins.", objects="chart",
              fx="glitch", origin="auto"),
    ]
    words = []
    parts = []
    for b in beats:
        words.extend(_time_words(b["spoken"], b["t0"], b["t1"]))
        extra = ""
        if b["_objects"] == "phone":
            extra = '<svg class="sc" data-sc="phone" data-depth="1.2" x="1240" y="520" width="220" height="380" viewBox="0 0 82 168"></svg>'
        elif b["_objects"] == "chart":
            extra = '<svg class="sc" data-sc="chart" data-depth="1" x="1100" y="400" width="560" height="360" viewBox="0 0 200 130"></svg>'
        host = f' data-host="{b["host"]}"' if b["host"] else ""
        parts.append(
            f'<section class="slide kind-{b["kind"]}" id="{b["id"]}" data-kind="{b["kind"]}" '
            f'data-t0="{b["t0"]:.3f}" data-t1="{b["t1"]:.3f}" data-hud="off" data-transition="cut"{host}>'
            f'<h1 class="h2">{b["spoken"]}</h1>{extra}</section>')
    slides = [{k: v for k, v in b.items() if k != "_objects"} for b in beats]
    return {"compiled": {"html": "\n".join(parts), "slides": slides, "duration": 20.0,
                         "start": 0.0, "end": 20.0, "sections": ["Next token"],
                         "host_windows": [], "host_sections": [], "host_on": False,
                         "packed": "token"},
            "words": words}


def _time_words(text: str, t0: float, t1: float) -> list:
    raw = _tokens(text)
    if not raw:
        return []
    span = max(0.3, (t1 - t0) - 0.35)
    step = span / len(raw)
    t = t0 + 0.2
    out = []
    for w in raw:
        dur = min(0.48, max(0.12, step * 0.82))
        end = min(t1 - 0.05, t + dur)
        if end <= t:
            end = t + 0.08
        out.append({"text": w, "start": round(t, 3), "end": round(end, 3)})
        t += step
    return out


def sample_raw(lesson: Optional[dict] = None) -> str:
    """Sections the compiler can time from the bundled lesson's narration."""
    lesson = lesson or sample_lesson()
    parts = []
    html = lesson["compiled"]["html"]
    for slide in lesson["compiled"]["slides"]:
        words = _tokens(slide.get("spoken") or "")
        at = " ".join(words[:3])
        host = f' data-host="{slide["host"]}"' if slide.get("host") else ""
        extra = ""
        m = re.search(r'id="' + re.escape(slide["id"]) + r'"[\s\S]*?</section>', html)
        if m:
            objs = _SC_RE.findall(m.group(0))
            pills = _PILL_RE.findall(m.group(0))
            for name, x, y, w, h in objs:
                extra += (f'<svg class="sc" data-sc="{name}" data-depth="1" x="{x}" y="{y}" '
                          f'width="{w}" height="{h}" viewBox="0 0 200 160"></svg>')
            if pills:
                extra += f'<div class="sc-pill">{pills[0]}</div>'
        parts.append(
            f'<section id="{slide["id"]}" data-at="{at}" data-kind="{slide.get("kind") or "slide"}"{host}>'
            f'<h1 class="h2">{slide.get("spoken") or ""}</h1>{extra}</section>')
    return "\n".join(parts)
