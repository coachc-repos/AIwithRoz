"""Brand pictures for any script. Names and colors live here. Logo files do not.

Simple Icons (https://simpleicons.org) is CC0-1.0. A project downloads the SVG
it needs into its own logos folder and keeps it there. Nothing from that set
is stored in this repository. A file Christian uploads for the same brand
replaces the download. If the download fails, the slide uses a monogram we draw.
"""
from __future__ import annotations

import base64
import html
import re
import urllib.request
from pathlib import Path
from typing import Callable, Optional

# Longer phrases first, so "Microsoft Copilot" wins over "Microsoft".
# slug is the Simple Icons file name. color is only a glow and a fallback.
BRANDS = (
    ("microsoft-copilot", "Microsoft Copilot", "microsoftcopilot", "#7b68ee"),
    ("chatgpt", "ChatGPT", "openai", "#10a37f"),
    ("openai", "OpenAI", "openai", "#412991"),
    ("anthropic", "Anthropic", "anthropic", "#d97757"),
    ("claude", "Claude", "anthropic", "#d97757"),
    ("gemini", "Gemini", "googlegemini", "#8ab4f8"),
    ("nvidia", "Nvidia", "nvidia", "#76b900"),
    ("tesla", "Tesla", "tesla", "#cc0000"),
    ("youtube", "YouTube", "youtube", "#ff0000"),
    ("heygen", "HeyGen", "heygen", "#7c5cfc"),
    ("grok", "Grok", "xai", "#f5b83d"),
    ("microsoft", "Microsoft", "microsoft", "#00a4ef"),
    ("x", "X", "x", "#e7e9ea"),
)
_BY_KEY = {row[0]: row for row in BRANDS}
_ICON = "https://cdn.jsdelivr.net/npm/simple-icons@11.14.0/icons/{slug}.svg"
_FETCHED = "simpleicons"


def brands_in_text(text: str) -> list:
    """Brands named in narration, in the order they appear, each once."""
    raw = text or ""
    occupied = []
    hits = []
    for key, name, slug, color in BRANDS:
        for m in re.finditer(r"(?<!\w)" + re.escape(name) + r"(?!\w)", raw, re.I):
            span = (m.start(), m.end())
            if any(span[0] < b and span[1] > a for a, b in occupied):
                continue
            occupied.append(span)
            hits.append((span[0], key, name, slug, color))
    hits.sort(key=lambda row: row[0])
    out, seen = [], set()
    for _at, key, name, slug, color in hits:
        if key in seen:
            continue
        seen.add(key)
        out.append({"key": key, "name": name, "slug": slug, "color": color})
    return out


def monogram_svg(name: str, color: str) -> str:
    """A letter tile we draw ourselves when no logo file is available."""
    letter = html.escape((name or "?").strip()[:1].upper() or "?")
    safe = html.escape(color or "#f5b83d", quote=True)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<rect width="24" height="24" rx="6" fill="{safe}"/>'
        f'<text x="12" y="17" text-anchor="middle" font-family="Inter,sans-serif" '
        f'font-size="14" font-weight="750" fill="#0c1018">{letter}</text></svg>'
    )


def tint_icon(svg: str, color: str) -> str:
    """Simple Icons are black by default. Paint the mark in the brand color."""
    svg = (svg or "").strip()
    if not svg.lower().startswith("<svg") or "<script" in svg.lower():
        return ""
    safe = html.escape(color or "#ffffff", quote=True)
    if re.match(r"<svg\b[^>]*\bfill=", svg, re.I):
        return svg
    return svg.replace("<svg", f'<svg fill="{safe}" fill-rule="evenodd"', 1)


def fetch_icon(slug: str, *, opener: Optional[Callable] = None, timeout: float = 6.0) -> str:
    """The CC0 SVG, or "" when the slug is missing or the network fails."""
    if not slug or not re.fullmatch(r"[a-z0-9]+", slug):
        return ""
    url = _ICON.format(slug=slug)
    try:
        if opener is not None:
            body = opener(url)
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "ScriptCraft"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
        if isinstance(body, str):
            body = body.encode("utf-8")
        text = body.decode("utf-8", "replace")
    except Exception:
        return ""
    if len(text) > 200_000 or not text.lstrip().lower().startswith("<svg"):
        return ""
    return text


def _data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def brand_svg(project, key: str, color: str, name: str, *, opener=None) -> str:
    """A tinted logo SVG: the user's file, then a cached download, then a monogram."""
    logos = (getattr(project, "data", None) or {}).get("logos") or {}
    rec = logos.get(key) or {}
    path = None
    if rec.get("file") and getattr(project, "dir", None):
        candidate = Path(project.dir) / "logos" / rec["file"]
        if candidate.is_file():
            path = candidate
    if path is not None:
        text = path.read_text(encoding="utf-8", errors="replace")
        if text.lstrip().lower().startswith("<svg"):
            return text if rec.get("source") != _FETCHED else (tint_icon(text, color) or text)
    row = _BY_KEY.get(key)
    if row:
        got = fetch_icon(row[2], opener=opener)
        tinted = tint_icon(got, color)
        if tinted:
            return tinted
    return monogram_svg(name, color)


_clip_n = 0


def hero(name: str, color: str, svg: str, *, size: int = 520, delay: float = 0.2) -> str:
    """One large logo: a disc, a glow, the mark, and a pill. The runtime floats it."""
    global _clip_n
    _clip_n += 1
    clip = f"scclip{_clip_n}"
    safe_name = html.escape(name or "", quote=True)
    safe_color = html.escape(color or "#f5b83d", quote=True)
    uri = _data_uri(svg)
    return (
        f'<div class="sc-hero" data-anim="pop" data-t="+{delay:.2f}" '
        f'style="position:absolute; left:700px; top:220px; width:{size}px; text-align:center;">'
        f'<svg class="sc sc-brand" data-sc="brand" data-color="{safe_color}" '
        f'width="{size}" height="{size}" viewBox="0 0 520 520" shape-rendering="geometricPrecision">'
        f'<defs><clipPath id="{clip}"><circle cx="260" cy="246" r="156"/></clipPath></defs>'
        f'<ellipse class="sc-shadow" cx="260" cy="470" rx="150" ry="16" fill="#000" opacity="0.35"/>'
        f'<circle class="sc-glow" cx="260" cy="246" r="188" fill="{safe_color}" opacity="0.22"/>'
        f'<circle cx="260" cy="246" r="160" fill="#121824" stroke="{safe_color}" stroke-width="4"/>'
        f'<image x="150" y="136" width="220" height="220" href="{uri}" preserveAspectRatio="xMidYMid meet"/>'
        f'<g clip-path="url(#{clip})"><g class="sc-glint" opacity="0">'
        f'<rect x="0" y="70" width="40" height="360" fill="#fff" opacity="0.28"/></g></g>'
        f'</svg><div class="sc-pill">{safe_name}</div></div>'
    )


def comparison(left: dict, right: dict) -> str:
    """Two heroes. Each dict is name, color, svg."""
    a = hero(left["name"], left["color"], left["svg"], size=420, delay=0.2).replace("left:700px; top:220px", "left:160px; top:250px")
    b = hero(right["name"], right["color"], right["svg"], size=420, delay=0.45).replace("left:700px; top:220px", "left:1100px; top:250px")
    return (
        a + b +
        '<div class="sc-hub" data-anim="pop" data-t="+0.3" '
        'style="position:absolute; left:860px; top:470px">vs</div>'
    )


def orbit(items: list) -> str:
    """Logos around a hub. Cinematic moves them on the ring; classic leaves them placed."""
    n = max(1, len(items))
    parts = []
    import math
    for i, item in enumerate(items):
        ang = -math.pi / 2 + i * math.pi * 2 / n
        x = 960 + math.cos(ang) * 420 - 90
        y = 580 + math.sin(ang) * 200 - 90
        uri = _data_uri(item["svg"])
        parts.append(
            f'<div class="sc-orb" data-anim="pop" data-t="+{0.25 + i * 0.15:.2f}" '
            f'style="position:absolute; left:{x:.0f}px; top:{y:.0f}px; width:180px; text-align:center;">'
            f'<svg class="sc sc-brand" data-sc="brand" data-color="{html.escape(item["color"], quote=True)}" '
            f'width="160" height="160" viewBox="0 0 520 520">'
            f'<circle class="sc-glow" cx="260" cy="246" r="188" fill="{html.escape(item["color"], quote=True)}" opacity="0.2"/>'
            f'<circle cx="260" cy="246" r="160" fill="#121824"/>'
            f'<image x="150" y="136" width="220" height="220" href="{uri}" preserveAspectRatio="xMidYMid meet"/>'
            f'</svg><div class="sc-pill">{html.escape(item["name"])}</div></div>'
        )
    return '<div class="sc-orbit">' + "".join(parts) + (
        '<div class="sc-hub" style="position:absolute; left:860px; top:520px">Ecosystem</div></div>'
    )


def ensure_brand_logos(project, texts, *, opener=None) -> list:
    """Cache a CC0 icon per brand named in the texts. Never replaces an upload.

    `opener(url) -> bytes` stands in for the network in tests. Returns the brands found.
    """
    found = brands_in_text("\n".join(texts or []))
    if project is None:
        return found
    logos = project.data.setdefault("logos", {})
    changed = False
    for brand in found:
        key = brand["key"]
        rec = logos.get(key) or {}
        if rec.get("file") and rec.get("source") != _FETCHED:
            continue
        folder = Path(project.dir) / "logos"
        cached = folder / f"{key}.svg"
        if rec.get("source") == _FETCHED and cached.is_file():
            continue
        raw = fetch_icon(brand["slug"], opener=opener)
        tinted = tint_icon(raw, brand["color"])
        if not tinted:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        cached.write_text(tinted, encoding="utf-8")
        logos[key] = {"name": brand["name"], "source": _FETCHED, "file": cached.name,
                      "kind": "icon", "aspect": 1.0, "recolor": "original", "svg": True,
                      "recolored": False}
        changed = True
    listed = [
        {"key": b["key"], "name": b["name"], "color": b["color"], "slug": b["slug"],
         "has_file": bool((logos.get(b["key"]) or {}).get("file"))}
        for b in found
    ]
    if changed or listed != (project.data.get("brands") or []):
        project.data["brands"] = listed
        project.save()
    return found
