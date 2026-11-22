"""Richer pictures for explainer slides.

The slide HTML (type, figures, cues, motion) stays as Claude wrote it. This
module only builds the pictures behind that HTML:

- classic: nothing here. The runtime keeps the particle field.
- rich: one literal still per slide, a slow Ken Burns move, grain, a title
  veil and a vignette.
- cinematic: the same still split into far / mid / near layers that move at
  different speeds (a cheap depth fake, not a depth model), plus a light shaft.

Stills are cached under the project folder (imagery/) so a re-render does not
generate them again. When a usable xAI key is present, the still is a Grok
Imagine image (grok-imagine-image-2.0, the same model the thumbnail tool uses)
from a literal, scene-tied prompt. If the key is missing, the call fails, or
the bytes are not an image, a painted still of that same subject is used
instead. Set EXPLAINER_IMAGERY=paint to skip Grok even when a key is set.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import random
import threading
from pathlib import Path

VISUAL_STYLES = ("classic", "rich", "cinematic")
VISUAL_STYLE_DEFAULT = "classic"
PAINT_VERSION = "1"
PLATE_W, PLATE_H = 1280, 720

# One look for every slide, whether the still is painted or generated.
ART_STYLE = (
    "Landscape 16:9. Photoreal editorial still, dark navy shadows, one soft "
    "key light from the upper right, fine film grain, shallow depth of field, "
    "a recognizable real-world subject, no readable text, no letters, no "
    "numbers, no logos, no watermark."
)

# Motion is in stage pixels over the slide. depth scales the pan so the far
# layer lags the near one. zoom is added to a 1.08 cover scale.
LAYER_MOTION = {
    "rich": [
        {"file": "flat", "depth": 1.0, "dx": 46, "dy": 14, "zoom": 0.06, "opacity": 1},
    ],
    "cinematic": [
        {"file": "far", "depth": 0.35, "dx": 26, "dy": 8, "zoom": 0.03, "opacity": 1},
        {"file": "mid", "depth": 1.0, "dx": 54, "dy": 16, "zoom": 0.075, "opacity": 1},
        {"file": "near", "depth": 1.8, "dx": 90, "dy": 26, "zoom": 0.02, "opacity": 0.95},
    ],
}

GRADE = {
    "rich": {"vignette": 0.55, "grain": 0.18, "warm": 0.5, "shaft": 0.0, "veil": 0.5},
    "cinematic": {"vignette": 0.82, "grain": 0.3, "warm": 0.75, "shaft": 0.55, "veil": 0.58},
}

_MOTIFS = (
    ("datacenter", ("data-center", "data center", "transformer", "power line", "grid-scale", "battery")),
    ("hearing", ("hearing", "microphone", "gavel", "testify")),
    ("chips", ("chip", "semiconductor", "workbench", "processor")),
    ("election", ("ballot", "election")),
    ("bitcoin", ("bitcoin",)),
    ("meeting", ("county meeting", "meeting room", "agenda")),
    ("chamber", ("legislative chamber", "ledger", "empty legislative")),
    ("chart", ("chart", "nasdaq", "stock", "trading", "price line", "ticker", "s&p", "s and p")),
    ("desk", ("laptop", "desk", "fact sheet", "retirement", "holdings")),
)

_LOCKS: dict = {}
_GRAIN = b""


def visual_style_key(choice: str | None = None, saved: str | None = None) -> str:
    """Which picture treatment to draw.

    An explicit choice wins, then a style already saved on the project, then
    classic (the particle field). An unknown value is not a choice.
    """
    if choice in VISUAL_STYLES:
        return choice
    if saved in VISUAL_STYLES:
        return saved
    return VISUAL_STYLE_DEFAULT


def grok_key_present() -> bool:
    """True when a usable xAI key is in the environment. The value is never returned."""
    return bool(_grok_key())


def _grok_key() -> str:
    if (os.getenv("EXPLAINER_IMAGERY") or "").strip().lower() in ("paint", "painted"):
        return ""
    for name in ("XAI_API_KEY", "GROK_API_KEY"):
        val = (os.getenv(name) or "").strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1].strip()
        if len(val) < 12 or val.startswith("\u2022") or "..." in val:
            continue
        if val == "your-xai-api-key-here":
            continue
        return val
    return ""


def plate_prompt(slide: dict) -> str:
    """A literal still prompt for this slide. The subject comes from the words."""
    beat = " ".join((slide.get("spoken") or "").split())
    idea = " ".join((slide.get("idea") or "").split())
    text = (beat or idea or (slide.get("at") or ""))[:500]
    scene = _literal_scene(text)
    kind = (slide.get("kind") or "slide").lower()
    quiet = "Keep the upper left darker and quieter so a title can sit on it. "
    if kind in ("chapter", "asset"):
        quiet += "Wide and dark, the subject small and toward the lower right. "
    return f"{scene}. {quiet}{ART_STYLE}"


def _literal_scene(beat: str) -> str:
    scene = ""
    try:
        from linedrive_azure.agents.grok_imagine_literals import scene_for_beat
        scene, _overlay = scene_for_beat(beat or "")
    except Exception:
        scene = ""
    scene = " ".join((scene or "").split()).rstrip(".")
    low = scene.lower()
    if (not scene or "blank unlabeled" in low or "no symbolic" in low
            or "editor-created overlay" in low):
        return (
            "A quiet newsroom at night: one wooden desk, one monitor showing an "
            "unlabeled chart, and a window onto a dark city"
        )
    return scene


def motif_for(prompt: str, kind: str = "slide") -> str:
    if (kind or "").lower() in ("chapter", "asset"):
        return "chapter"
    low = (prompt or "").lower()
    for name, keys in _MOTIFS:
        if any(k in low for k in keys):
            return name
    return "newsroom"


def layer_placement(spec: dict, u: float) -> tuple:
    """(scale, pan_x, pan_y) at progress u (0 to 1) through the slide.

    The runtime uses this same formula. Scale is the cover multiplier.
    """
    u = 0.0 if u < 0 else 1.0 if u > 1 else u
    depth = float(spec.get("depth") or 1)
    z = 1.08 + float(spec.get("zoom") or 0) * u
    ox = depth * float(spec.get("dx") or 0) * (u - 0.5)
    oy = depth * float(spec.get("dy") or 0) * (u - 0.5)
    return z, ox, oy


def imagery_for_page(folder: Path, slides: list, style: str, *, fetch="auto") -> dict:
    """Page config for this style. Classic, or any failure, returns no plates
    so the runtime draws the particle field."""
    style = visual_style_key(style)
    if style == "classic" or not slides:
        return {"style": "classic", "plates": [], "grade": {}, "grain": ""}
    try:
        plates, stats = ensure_plates(Path(folder), slides, style, fetch=fetch)
    except Exception:
        return {"style": "classic", "plates": [], "grade": {}, "grain": ""}
    if not plates:
        return {"style": "classic", "plates": [], "grade": {}, "grain": ""}
    return {"style": style, "grade": dict(GRADE[style]), "grain": _data_uri(grain_png(), "image/png"),
            "plates": plates, "stats": stats}


def ensure_plates(folder: Path, slides: list, style: str, *, fetch="auto") -> tuple:
    """Cache a still per slide and return page plate records plus counts."""
    style = visual_style_key(style)
    if style == "classic":
        return [], {"cache_hits": 0, "painted": 0, "grok": 0, "failed": 0}
    fetch_fn = _resolve_fetch(fetch)
    stats = {"cache_hits": 0, "painted": 0, "grok": 0, "failed": 0}
    plates = []
    for slide in slides or []:
        try:
            meta = ensure_one(folder, slide, fetch_fn)
        except Exception:
            stats["failed"] += 1
            continue
        if meta.get("hit"):
            stats["cache_hits"] += 1
        stats[meta.get("source") if meta.get("source") in ("painted", "grok") else "painted"] += 1
        plates.append(_page_plate(folder, slide, meta, style))
    return plates, stats


def ensure_one(folder: Path, slide: dict, fetch) -> dict:
    prompt = plate_prompt(slide)
    provider = "grok" if fetch else "paint"
    key = hashlib.sha256(f"{PAINT_VERSION}|{provider}|{prompt}".encode()).hexdigest()[:20]
    folder = Path(folder)
    meta_path = folder / "imagery" / f"{key}.json"
    with _lock(folder):
        if meta_path.is_file() and _files_ok(folder, key):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["hit"] = True
            return meta
        stack, source = None, "painted"
        if fetch:
            raw = None
            try:
                raw = fetch(prompt)
            except Exception:
                raw = None
            im = _open_rgb(raw) if raw else None
            if im is not None:
                stack = stack_from_photo(im, slide.get("id") or key)
                source = "grok"
        if stack is None:
            stack = paint_stack(prompt, slide.get("kind") or "slide", slide.get("id") or key)
            source = "painted"
        meta = _write_stack(folder, key, stack, prompt, source, slide.get("id") or "")
        meta["hit"] = False
        return meta


def default_grok_fetch(prompt: str):
    """One Grok Imagine still, or None. Never raises and never logs the key."""
    key = _grok_key()
    if not key:
        return None
    try:
        from xai_sdk import Client
        client = Client(api_key=key)
    except Exception:
        return None
    models = []
    for name in (os.getenv("EXPLAINER_IMAGE_MODEL", "grok-imagine-image-2.0"),
                 os.getenv("EXPLAINER_IMAGE_FALLBACK_MODEL", "grok-imagine-image-pro")):
        if name and name not in models:
            models.append(name)
    for model in models:
        try:
            resp = client.image.sample(
                prompt=prompt, model=model, image_format="base64",
                aspect_ratio="16:9", resolution="1k")
            raw = getattr(resp, "image", None)
            if isinstance(raw, str):
                raw = base64.b64decode(raw)
            if isinstance(raw, (bytes, bytearray)) and len(raw) > 32:
                return bytes(raw)
        except Exception:
            continue
    return None


def paint_stack(prompt: str, kind: str, seed: str) -> dict:
    motif = motif_for(prompt, kind)
    far = paint_far(motif, _rng(seed + "|far|" + motif))
    mid = paint_mid(motif, _rng(seed + "|mid|" + motif))
    near = paint_near(_rng(seed + "|near"))
    flat = _finish_flat(_flatten(far, mid, near))
    return {"far": far, "mid": mid, "near": near, "flat": flat}


def stack_from_photo(im, seed: str) -> dict:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    photo = ImageOps.fit(im.convert("RGB"), (PLATE_W, PLATE_H), Image.Resampling.LANCZOS)
    far = ImageEnhance.Color(ImageEnhance.Brightness(photo).enhance(0.7)).enhance(0.65)
    far = far.filter(ImageFilter.GaussianBlur(14))
    mid = photo.convert("RGBA")
    near = paint_near(_rng(str(seed) + "|near"))
    flat = _finish_flat(_flatten(far, mid, near))
    return {"far": far.convert("RGB"), "mid": mid, "near": near, "flat": flat}


# ---------------------------------------------------------------------------
# Painting. Subjects sit lower-right so the title band can stay dark.
# ---------------------------------------------------------------------------

def _rng(seed: str) -> random.Random:
    return random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16))


def _vgrad(size, top, bottom):
    from PIL import Image
    w, h = size
    col = Image.new("RGB", (1, h))
    px = col.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return col.resize(size, Image.Resampling.BILINEAR)


def _grain(im, amount: float = 0.06):
    from PIL import Image
    try:
        noise = Image.effect_noise(im.size, 22).convert("RGB")
    except Exception:
        return im
    return Image.blend(im.convert("RGB"), noise, amount)


def _flatten(far, mid, near):
    base = far.convert("RGBA")
    base.alpha_composite(mid.convert("RGBA"))
    base.alpha_composite(near.convert("RGBA"))
    return base


def _finish_flat(im):
    from PIL import ImageEnhance
    rgb = ImageEnhance.Brightness(im.convert("RGB")).enhance(1.18)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.14)
    rgb = ImageEnhance.Color(rgb).enhance(1.2)
    return _grain(rgb, 0.04)


def paint_far(motif: str, rng: random.Random):
    from PIL import Image, ImageDraw, ImageFilter
    top = (14, 20, 34) if motif == "chapter" else (58, 88, 138)
    im = _vgrad((PLATE_W, PLATE_H), top, (18, 26, 40))
    d = ImageDraw.Draw(im)
    horizon = 460 if motif != "chapter" else 520
    # City glow on the horizon, then the ground.
    glow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-80, horizon - 80, PLATE_W + 80, horizon + 160), fill=(255, 176, 90, 70))
    im = Image.alpha_composite(im.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(18))).convert("RGB")
    d = ImageDraw.Draw(im)
    d.rectangle((0, horizon + 8, PLATE_W, PLATE_H), fill=(16, 22, 32))
    x = -20
    while x < PLATE_W:
        w = rng.randint(36, 120)
        h = rng.randint(40, 180 if motif != "chapter" else 80)
        shade = 28 + (h % 24)
        d.rectangle((x, horizon - h, x + w, horizon + 10), fill=(shade, shade + 8, shade + 22))
        # A few lit windows, so the distance reads as a city and not a bar.
        if h > 70 and rng.random() > 0.4:
            d.rectangle((x + 8, horizon - h + 16, x + 14, horizon - h + 24), fill=(255, 206, 140))
        x += w + rng.randint(8, 26)
    haze = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(haze).rectangle((0, horizon - 24, PLATE_W, horizon + 40), fill=(180, 196, 220, 40))
    im = Image.alpha_composite(im.convert("RGBA"), haze).convert("RGB")
    im = im.filter(ImageFilter.GaussianBlur(4 if motif != "chapter" else 7))
    return _grain(im, 0.04)


def paint_mid(motif: str, rng: random.Random):
    from PIL import Image
    im = Image.new("RGBA", (PLATE_W, PLATE_H), (0, 0, 0, 0))
    if motif == "datacenter":
        _draw_datacenter(im, rng)
    elif motif == "hearing":
        _draw_hearing(im, rng)
    elif motif == "chips":
        _draw_chips(im, rng)
    elif motif == "election":
        _draw_election(im, rng)
    elif motif == "bitcoin":
        _draw_bitcoin(im, rng)
    elif motif == "meeting":
        _draw_meeting(im, rng)
    elif motif == "chamber":
        _draw_chamber(im, rng)
    elif motif == "desk":
        _draw_desk(im, rng)
    elif motif == "chapter":
        _draw_chapter(im, rng)
    elif motif == "chart":
        _draw_chart(im, rng)
    else:
        _draw_newsroom(im, rng)
    return im


def paint_near(rng: random.Random):
    """Out-of-focus foreground: a sill and a few large bokeh discs."""
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.new("RGBA", (PLATE_W, PLATE_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.polygon([(0, 690), (PLATE_W, 660), (PLATE_W, PLATE_H), (0, PLATE_H)], fill=(6, 8, 12, 150))
    d.line((0, 686, PLATE_W, 656), fill=(190, 200, 214, 110), width=2)
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for i in range(6):
        cx = rng.randint(780, 1240)
        cy = rng.randint(520, 700)
        rad = rng.randint(28, 72)
        color = (255, 206, 140, rng.randint(90, 150)) if i % 2 == 0 else (170, 206, 245, rng.randint(80, 130))
        ld.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=color)
    layer = layer.filter(ImageFilter.GaussianBlur(10))
    return Image.alpha_composite(im, layer)


def _lamp(im, cx, cy, rad, color=(255, 196, 130, 120)):
    from PIL import Image, ImageDraw, ImageFilter
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse((cx - rad, cy - rad // 2, cx + rad, cy + rad), fill=color)
    layer = layer.filter(ImageFilter.GaussianBlur(18))
    im.alpha_composite(layer)


def _glow_line(im, points, fill, width=4):
    from PIL import Image, ImageDraw, ImageFilter
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).line(points, fill=fill + (230,), width=width, joint="curve")
    glow = layer.filter(ImageFilter.GaussianBlur(7))
    im.alpha_composite(glow)
    im.alpha_composite(layer)


def _windows(draw, x, y, w, h, rows, cols, rng, lit=0.4):
    if rows < 1 or cols < 1:
        return
    gapx, gapy = w / cols, h / rows
    ww, hh = max(2, gapx * 0.42), max(2, gapy * 0.38)
    for r in range(rows):
        for c in range(cols):
            if rng.random() > lit:
                continue
            wx = x + c * gapx + gapx * 0.2
            wy = y + r * gapy + gapy * 0.22
            color = (255, 206, 150, 230) if rng.random() > 0.3 else (150, 196, 240, 210)
            draw.rectangle((wx, wy, wx + ww, wy + hh), fill=color)


def _draw_chart(im, rng):
    from PIL import ImageDraw
    _lamp(im, 1180, 80, 150, (255, 186, 110, 110))
    d = ImageDraw.Draw(im)
    d.polygon([(520, 545), (1260, 490), (1280, 720), (460, 720)], fill=(62, 46, 32, 255))
    d.line((530, 544, 1255, 490), fill=(196, 156, 104, 255), width=4)
    # A reflection of the screen on the desk.
    d.polygon([(800, 560), (1160, 530), (1140, 575), (820, 600)], fill=(48, 40, 28, 160))
    # Monitor: a dark side wall, then the lit face, then the glass.
    d.rounded_rectangle((770, 176, 1240, 528), radius=16, fill=(8, 10, 16, 255))
    d.rounded_rectangle((748, 156, 1216, 506), radius=16, fill=(46, 58, 80, 255))
    d.line((772, 162, 1188, 162), fill=(214, 224, 238, 255), width=4)
    d.rounded_rectangle((778, 184, 1196, 470), radius=8, fill=(8, 16, 28, 255))
    pts = []
    x0, y0 = 810, 230
    for i in range(16):
        pts.append((x0 + i * 24, y0 + int(rng.randint(-6, 14) + i * 9)))
    _glow_line(im, pts, (255, 196, 70), 5)
    d = ImageDraw.Draw(im)
    d.rectangle((1130, 500, 1176, 556), fill=(28, 34, 48, 255))
    d.polygon([(900, 552), (1200, 540), (1224, 578), (888, 590)], fill=(16, 20, 30, 255))


def _draw_datacenter(im, rng):
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    d.polygon([(400, 545), (1280, 490), (1280, 720), (360, 720)], fill=(28, 36, 32, 255))
    for i, hx in enumerate((540, 630)):
        d.polygon([(hx, 490), (hx + 34, 452), (hx + 68, 490)], fill=(70, 62, 54, 255))
        d.rectangle((hx + 8, 490, hx + 60, 545), fill=(86, 74, 64, 255))
        if i == 0:
            d.rectangle((hx + 26, 508, hx + 40, 524), fill=(255, 210, 140, 255))
    for i in range(3):
        x = 700 + i * 86
        d.rounded_rectangle((x + 6, 508, x + 74, 586), radius=4, fill=(0, 0, 0, 70))
        d.rounded_rectangle((x, 496, x + 68, 574), radius=4, fill=(36, 64, 54, 255))
        d.rectangle((x, 496, x + 68, 508), fill=(150, 196, 160, 255))
        d.rectangle((x + 10, 528, x + 26, 538), fill=(90, 230, 150, 255))
    d.rectangle((868, 262, 1224, 548), fill=(10, 14, 22, 255))
    d.polygon([(860, 248), (1210, 220), (1244, 246), (890, 274)], fill=(64, 82, 112, 255))
    d.rectangle((860, 244, 1216, 258), fill=(214, 224, 236, 255))
    d.rectangle((860, 258, 1216, 545), fill=(24, 34, 52, 255))
    _windows(d, 888, 278, 300, 230, 7, 8, rng, lit=0.72)
    d.rectangle((792, 468, 858, 552), fill=(54, 60, 72, 255))
    d.rectangle((800, 450, 850, 472), fill=(110, 120, 136, 255))
    d.line((1216, 246, 1080, 150, 860, 108, 620, 150), fill=(226, 230, 236, 230), width=3)
    _lamp(im, 1160, 160, 140, (255, 186, 110, 80))


def _draw_hearing(im, rng):
    from PIL import ImageDraw
    _lamp(im, 1180, 80, 150, (220, 228, 245, 100))
    d = ImageDraw.Draw(im)
    d.polygon([(620, 230), (1248, 200), (1260, 470), (640, 510)], fill=(42, 48, 62, 255))
    d.rounded_rectangle((748, 268, 1160, 430), radius=6, fill=(8, 14, 24, 255))
    d.rectangle((748, 268, 1160, 278), fill=(170, 186, 210, 255))
    for i in range(5):
        x = 790 + i * 68
        d.rectangle((x, 300, x + 36, 400), fill=(18, 40, 52, 255))
        d.rectangle((x + 6, 308, x + 14, 392), fill=(80, 190, 220, 255))
    d.polygon([(540, 610), (1270, 490), (1280, 560), (590, 700)], fill=(122, 84, 52, 255))
    d.polygon([(540, 588), (1270, 470), (1270, 494), (560, 614)], fill=(196, 150, 96, 255))
    for i in range(4):
        x = 820 + i * 100
        d.rectangle((x, 400, x + 8, 545), fill=(70, 74, 84, 255))
        d.rounded_rectangle((x - 10, 382, x + 20, 412), radius=8, fill=(28, 30, 36, 255))
        d.rectangle((x - 4, 388, x + 10, 396), fill=(230, 236, 242, 255))
    d.rounded_rectangle((900, 530, 1000, 562), radius=3, fill=(236, 230, 218, 255))
    d.rounded_rectangle((1030, 516, 1136, 552), radius=3, fill=(210, 202, 188, 255))


def _draw_chips(im, rng):
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    d.polygon([(480, 560), (1280, 500), (1280, 720), (440, 720)], fill=(34, 36, 40, 255))
    d.line((500, 558, 1260, 500), fill=(90, 96, 104, 255), width=2)
    _lamp(im, 1000, 160, 280, (255, 214, 160, 60))
    for i in range(3):
        x, y = 760 + i * 150, 340 + (i % 2) * 30
        w, h = 120, 120
        d.rounded_rectangle((x + 8, y + 10, x + w + 8, y + h + 10), radius=6, fill=(0, 0, 0, 80))
        d.rounded_rectangle((x, y, x + w, y + h), radius=6, fill=(18, 48, 40, 255))
        d.rectangle((x, y, x + w, y + 8), fill=(80, 140, 120, 255))
        d.rectangle((x + 28, y + 28, x + w - 28, y + h - 28), fill=(10, 24, 22, 255))
        d.line((x + 36, y + 36, x + w - 40, y + 48), fill=(180, 220, 200, 180), width=2)
        for p in range(8):
            d.rectangle((x + 14 + p * 12, y - 8, x + 20 + p * 12, y + 4), fill=(160, 150, 120, 255))
            d.rectangle((x + 14 + p * 12, y + h - 4, x + 20 + p * 12, y + h + 8), fill=(120, 110, 80, 255))


def _draw_election(im, rng):
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    d.polygon([(500, 580), (1260, 520), (1280, 720), (460, 720)], fill=(28, 26, 24, 255))
    d.rounded_rectangle((860, 300, 1180, 470), radius=8, fill=(8, 12, 20, 255))
    d.rectangle((860, 300, 1180, 308), fill=(140, 156, 180, 255))
    # A ballot box, the recognizable object. No words on it.
    d.rounded_rectangle((760, 430, 980, 620), radius=8, fill=(32, 48, 92, 255))
    d.rectangle((760, 430, 980, 448), fill=(70, 96, 160, 255))
    d.rectangle((820, 400, 920, 436), fill=(20, 28, 48, 255))
    d.polygon([(800, 468), (940, 468), (910, 520), (830, 520)], fill=(230, 224, 210, 255))


def _draw_bitcoin(im, rng):
    from PIL import ImageDraw
    _draw_desk(im, rng)
    d = ImageDraw.Draw(im)
    d.ellipse((1040, 470, 1160, 590), fill=(212, 148, 42, 255))
    d.ellipse((1052, 482, 1148, 578), fill=(255, 196, 90, 230))
    d.ellipse((1074, 504, 1126, 556), fill=(150, 96, 24, 255))


def _draw_meeting(im, rng):
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    d.polygon([(520, 420), (1240, 380), (1240, 500), (540, 540)], fill=(32, 34, 38, 255))
    d.rounded_rectangle((780, 250, 1160, 400), radius=4, fill=(8, 14, 22, 255))
    _windows(d, 820, 270, 300, 100, 3, 6, rng, lit=0.3)
    d.polygon([(600, 560), (1260, 500), (1280, 600), (640, 670)], fill=(70, 58, 46, 255))
    for i in range(4):
        x = 820 + i * 80
        d.rectangle((x, 470, x + 8, 545), fill=(40, 42, 48, 255))
        d.ellipse((x - 10, 456, x + 18, 478), fill=(24, 26, 30, 255))


def _draw_chamber(im, rng):
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    d.polygon([(700, 180), (1220, 160), (1240, 520), (720, 560)], fill=(22, 26, 34, 255))
    for i in range(5):
        x = 780 + i * 80
        d.rectangle((x, 200, x + 28, 470), fill=(30, 36, 48, 255))
        d.rectangle((x, 200, x + 28, 214), fill=(90, 100, 120, 255))
    d.polygon([(640, 560), (1200, 500), (1230, 640), (680, 700)], fill=(48, 40, 34, 255))
    d.rounded_rectangle((900, 530, 1040, 590), radius=4, fill=(24, 28, 26, 255))
    d.rectangle((900, 530, 1040, 540), fill=(80, 90, 80, 255))


def _draw_desk(im, rng):
    from PIL import ImageDraw
    _lamp(im, 1120, 140, 200, (255, 200, 140, 50))
    d = ImageDraw.Draw(im)
    # A window of city lights on the right.
    d.rectangle((1080, 80, 1260, 360), fill=(10, 16, 28, 255))
    _windows(d, 1094, 96, 150, 240, 8, 4, rng, lit=0.45)
    d.polygon([(500, 560), (1280, 500), (1280, 720), (460, 720)], fill=(36, 28, 22, 255))
    d.line((520, 556, 1260, 498), fill=(120, 96, 70, 255), width=3)
    d.rounded_rectangle((760, 300, 1080, 500), radius=8, fill=(16, 20, 28, 255))
    d.rectangle((760, 300, 1080, 312), fill=(70, 78, 92, 255))
    d.rectangle((776, 324, 1064, 484), fill=(4, 8, 14, 255))
    _glow_line(im, [(800, 360), (860, 400), (930, 370), (1000, 430), (1048, 390)], (120, 190, 255), 3)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((1000, 470, 1120, 545), radius=2, fill=(230, 226, 216, 255))


def _draw_newsroom(im, rng):
    _draw_desk(im, rng)


def _draw_chapter(im, rng):
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    _lamp(im, 1080, 420, 180, (245, 184, 61, 35))
    d.rectangle((1040, 220, 1088, 620), fill=(28, 36, 52, 255))
    d.rectangle((1040, 220, 1088, 232), fill=(150, 164, 190, 255))
    d.polygon([(1000, 620), (1140, 600), (1160, 660), (990, 680)], fill=(12, 14, 20, 255))


def grain_png() -> bytes:
    global _GRAIN
    if _GRAIN:
        return _GRAIN
    rng = random.Random(7)
    from PIL import Image
    im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    px = im.load()
    for _ in range(3200):
        x, y = rng.randrange(256), rng.randrange(256)
        v = 255 if rng.random() > 0.45 else 0
        px[x, y] = (v, v, v, rng.randint(60, 150))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    _GRAIN = buf.getvalue()
    return _GRAIN


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _lock(folder: Path):
    return _LOCKS.setdefault(str(Path(folder).resolve()), threading.Lock())


def _resolve_fetch(fetch):
    if fetch == "auto":
        return default_grok_fetch if _grok_key() else None
    return fetch


def _open_rgb(raw):
    if not raw:
        return None
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.load()
        return im.convert("RGB")
    except Exception:
        return None


def _files_ok(folder: Path, key: str) -> bool:
    root = folder / "imagery"
    return all((root / f"{key}{suf}").is_file() for suf in ("-flat.jpg", "-far.jpg", "-mid.png", "-near.png"))


def _write_stack(folder: Path, key: str, stack: dict, prompt: str, source: str, slide_id: str) -> dict:
    root = folder / "imagery"
    root.mkdir(parents=True, exist_ok=True)
    files = {
        "flat": f"imagery/{key}-flat.jpg",
        "far": f"imagery/{key}-far.jpg",
        "mid": f"imagery/{key}-mid.png",
        "near": f"imagery/{key}-near.png",
    }
    _save_jpeg(stack["flat"], folder / files["flat"], 82)
    _save_jpeg(stack["far"], folder / files["far"], 74)
    _save_png(stack["mid"], folder / files["mid"])
    _save_png(stack["near"], folder / files["near"])
    meta = {"key": key, "prompt": prompt, "source": source, "slide": slide_id,
            "files": files, "version": PAINT_VERSION}
    (root / f"{key}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    index_path = root / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {}
    except Exception:
        index = {}
    index[slide_id or key] = {"key": key, "source": source}
    index_path.write_text(json.dumps(index, indent=1), encoding="utf-8")
    return meta


def _save_jpeg(im, path: Path, quality: int) -> None:
    im.convert("RGB").save(path, "JPEG", quality=quality, optimize=True)


def _save_png(im, path: Path) -> None:
    im.save(path, "PNG", optimize=True)


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def _page_plate(folder: Path, slide: dict, meta: dict, style: str) -> dict:
    layers = []
    for spec in LAYER_MOTION[style]:
        rel = meta["files"][spec["file"]]
        path = folder / rel
        mime = "image/png" if path.suffix == ".png" else "image/jpeg"
        layers.append({
            "depth": spec["depth"], "dx": spec["dx"], "dy": spec["dy"],
            "zoom": spec["zoom"], "opacity": spec["opacity"],
            "uri": _data_uri(path.read_bytes(), mime),
        })
    return {"id": slide.get("id") or "", "t0": float(slide.get("t0") or 0),
            "t1": float(slide.get("t1") or 0), "source": meta.get("source") or "",
            "layers": layers}


def write_imagery_samples(folder: Path) -> list:
    """Before/after stills of the same three slides, captured from the real page.

    Painted plates only: this does not call Grok Imagine. Returns the paths
    it wrote. A short comparison mp4 is included when ffmpeg and Chrome run.
    """
    import asyncio
    import explainer_video as ev

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    slides = _sample_slides()
    project = folder / "_project"
    if project.exists():
        import shutil
        shutil.rmtree(project)
    project.mkdir()
    pages = {}
    for style in VISUAL_STYLES:
        visual = imagery_for_page(project, slides, style, fetch=None)
        html = ev.page_html(_sample_compiled(slides), mode="render", title="Imagery samples",
                            bubble="off", visual=visual)
        path = project / f"{style}.html"
        path.write_text(html, encoding="utf-8")
        pages[style] = path
    chrome = ev.find_chrome()
    written = []
    if not chrome:
        import shutil
        shutil.rmtree(project, ignore_errors=True)
        note = folder / "SOURCES.txt"
        note.write_text("Chrome was not available, so no stills were captured.\n", encoding="utf-8")
        return [note]
    out = {}

    async def grab():
        async with ev._Chrome(*chrome) as ch:
            for style, path in pages.items():
                await ch.open(path, 1.0, transparent=False)
                png = await ch.frame(2.4)
                for slide in slides:
                    # One page holds every sample slide in time. Seek to the
                    # middle of each, after the entrance animation has landed.
                    t = (float(slide["t0"]) + float(slide["t1"])) / 2
                    png = await ch.frame(t)
                    dest = folder / f"{style}_{slide['id']}.png"
                    dest.write_bytes(png)
                    out.setdefault(style, []).append(dest)

    asyncio.run(grab())
    for style, paths in out.items():
        written.extend(paths)
    mp4 = _sample_movie(folder, pages, slides, chrome)
    if mp4:
        written.append(mp4)
    import shutil
    shutil.rmtree(project, ignore_errors=True)
    sources = folder / "SOURCES.txt"
    sources.write_text(
        "Same three slides in each style. Type, figures and entrance motion are the slide HTML;\n"
        "only the picture behind them changes.\n"
        "classic_*.png  the current particle field.\n"
        "rich_*.png     painted still, Ken Burns, grain, veil, vignette.\n"
        "cinematic_*.png  the same still as far/mid/near layers, plus a light shaft.\n"
        "chart_compare.mp4  a few seconds of each style on the chart slide.\n"
        "Grok Imagine did not run. No API key was used. These are not mocked model images;\n"
        "they are the painted pictures the app uses when a key is missing or a generation fails.\n",
        encoding="utf-8")
    written.append(sources)
    return written


def _sample_slides() -> list:
    specs = [
        ("chart", "slide",
         "AI stocks lost about two trillion dollars in a single trading session on the nasdaq",
         "MARKETS", "One day. Trillions erased.", "AI stocks", "A slide, with the corner kept clear."),
        ("datacenter", "scene",
         "The data center power bill is climbing as the grid adds batteries and transformers",
         "POWER", "The grid pays the bill.", "Data centers", "Batteries, transformers, power lines."),
        ("hearing", "slide",
         "At the hearing they will testify, with microphones and a gavel on the table",
         "HEARING", "They will testify.", "The hearing", "Microphones, folders, a wall screen."),
    ]
    slides = []
    t = 0.0
    for sid, kind, spoken, kicker, headline, card, body in specs:
        slides.append({
            "id": sid, "kind": kind, "spoken": spoken, "idea": spoken, "t0": t, "t1": t + 6.0,
            "kicker": kicker, "headline": headline, "card": card, "body": body,
        })
        t += 6.0
    return slides


def _sample_compiled(slides: list) -> dict:
    parts = []
    for i, s in enumerate(slides):
        parts.append(
            f'<section class="slide kind-{s["kind"]}" id="{s["id"]}" data-kind="{s["kind"]}" '
            f'data-t0="{s["t0"]:.3f}" data-t1="{s["t1"]:.3f}" data-sidx="0" data-slabel="{s["kicker"]}" '
            f'data-hud="on" data-transition="cut" data-tracker="">'
            f'<div class="pad col gap-m">'
            f'<div class="kicker" data-anim="fade" data-t="{s["t0"] + 0.2:.3f}">{s["kicker"]}</div>'
            f'<h1 class="h1" data-anim="words" data-t="{s["t0"] + 0.35:.3f}">{s["headline"]}</h1>'
            f'<div class="card" data-anim="rise" data-t="{s["t0"] + 0.7:.3f}" style="max-width:860px">'
            f'<div class="h3">{s["card"]}</div><div class="lead">{s["body"]}</div>'
            f'</div></div></section>'
        )
    return {"html": "\n".join(parts), "slides": slides, "duration": slides[-1]["t1"],
            "start": 0.0, "end": slides[-1]["t1"], "sections": ["Markets"],
            "host_windows": [], "host_sections": []}


def _sample_movie(folder: Path, pages: dict, slides: list, chrome) -> Path | None:
    """A short mp4: classic, then rich, then cinematic, on the chart slide."""
    import asyncio
    import shutil
    import subprocess
    import explainer_video as ev
    if not shutil.which("ffmpeg"):
        return None
    frames = folder / "_frames"
    if frames.exists():
        shutil.rmtree(frames)
    frames.mkdir()
    chart = slides[0]
    t0 = float(chart["t0"]) + 0.4
    t1 = float(chart["t1"]) - 1.2
    n = 16  # frames per style, about 1.3s each at 12 fps

    async def grab():
        async with ev._Chrome(*chrome) as ch:
            i = 0
            for style in ("classic", "rich", "cinematic"):
                await ch.open(pages[style], 1.0, transparent=False)
                for k in range(n):
                    u = k / max(1, n - 1)
                    png = await ch.frame(t0 + (t1 - t0) * u)
                    (frames / f"f{i:04d}.png").write_bytes(png)
                    i += 1

    try:
        asyncio.run(grab())
    except Exception:
        shutil.rmtree(frames, ignore_errors=True)
        return None
    dest = folder / "chart_compare.mp4"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-framerate", "12",
           "-i", str(frames / "f%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-crf", "20", "-movflags", "+faststart", str(dest)]
    try:
        subprocess.run(cmd, check=True, timeout=180)
    except Exception:
        shutil.rmtree(frames, ignore_errors=True)
        return None
    shutil.rmtree(frames, ignore_errors=True)
    return dest
