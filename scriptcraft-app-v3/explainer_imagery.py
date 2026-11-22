"""Picture treatment for explainer slides.

The background stays the particle waves on every style. classic is those
waves only. cinematic adds a short 3D entrance on the objects (cards, icons,
charts, figures), stronger on the hook (every slide before the first chapter
card) and quieter after. Nothing here calls an image model, and nothing
replaces the waves with a still, a gradient, or a vignette.

`rich` is an old name for this treatment. It maps to cinematic.
"""
from __future__ import annotations

VISUAL_STYLES = ("classic", "cinematic")
VISUAL_STYLE_DEFAULT = "classic"
# Old projects may still say rich. That is the cinematic object entrance.
_ALIASES = {"rich": "cinematic"}

# The wave field used to be 20 rows at speed 1. Denser, and a little faster.
# Both styles use these. The runtime reads them from the page config.
WAVE_ROWS = 34
WAVE_SPEED = 1.4

# Entrance intensity. Rotations stay small so a card stays a thin panel
# (the same idea as the device frames: light from the upper left, no thick
# extrusion). z is a fly-in from farther away, in stage pixels. push is the
# peak camera scale. dof is the blur, in px, on objects that have already
# landed while another one is still entering.
POP = {
    "body": {"rot": 11, "z": 64, "overshoot": 1.04, "glint": 0.42, "dof": 0.7, "push": 1.022, "shadow": 0.42},
    "hook": {"rot": 20, "z": 128, "overshoot": 1.08, "glint": 0.82, "dof": 1.35, "push": 1.05, "shadow": 0.62},
}


def visual_style_key(choice: str | None = None, saved: str | None = None) -> str:
    """Which picture treatment to draw.

    An explicit choice wins, then a style already saved on the project, then
    classic. `rich` means cinematic. An unknown value is not a choice.
    """
    choice = _ALIASES.get(choice, choice)
    saved = _ALIASES.get(saved, saved)
    if choice in VISUAL_STYLES:
        return choice
    if saved in VISUAL_STYLES:
        return saved
    return VISUAL_STYLE_DEFAULT


def hook_until(slides) -> float | None:
    """Start time of the first chapter card.

    Slides that begin before this are the hook. None when the video has no
    chapter card; the runtime then treats only the first slide as the hook.
    """
    for slide in slides or []:
        if (slide.get("kind") or "") == "chapter":
            try:
                return float(slide.get("t0") or 0)
            except (TypeError, ValueError):
                return 0.0
    return None


def page_visual(style: str | None, slides=None) -> dict:
    """What the runtime needs. No images, no network."""
    style = visual_style_key(style)
    out = {
        "style": style,
        "waves": {"rows": WAVE_ROWS, "speed": WAVE_SPEED},
        "hookUntil": hook_until(slides),
    }
    if style == "cinematic":
        out["pop"] = POP
    return out


def write_imagery_samples(folder) -> list:
    """Hook and body stills, plus a short mp4, from the real page in Chrome.

    Classic and cinematic, same slides. No image model.
    """
    import asyncio
    import shutil
    import subprocess
    from pathlib import Path

    import explainer_video as ev

    folder = Path(folder)
    if folder.exists():
        for old in folder.iterdir():
            if old.is_file():
                old.unlink()
    folder.mkdir(parents=True, exist_ok=True)
    slides = [
        {"id": "hook", "kind": "slide", "t0": 0.0, "t1": 4.6},
        {"id": "chapter", "kind": "chapter", "t0": 4.6, "t1": 6.2},
        {"id": "body", "kind": "slide", "t0": 6.2, "t1": 11.0},
    ]
    html = _sample_html()
    compiled = {"html": html, "slides": slides, "duration": 11.0, "start": 0.0, "end": 11.0,
                "sections": ["Hook"], "host_windows": [], "host_sections": []}
    work = folder / "_pages"
    work.mkdir(parents=True, exist_ok=True)
    pages = {}
    for style in ("classic", "cinematic"):
        page = work / f"{style}.html"
        page.write_text(ev.page_html(compiled, mode="render", title="Object entrance",
                                     bubble="off", visual={"style": style}), encoding="utf-8")
        pages[style] = page
    chrome = ev.find_chrome()
    if not chrome:
        note = folder / "SOURCES.txt"
        note.write_text("Chrome was not available, so no stills were captured.\n", encoding="utf-8")
        shutil.rmtree(work, ignore_errors=True)
        return [note]
    # Mid-entrance, while the first card is still in the air.
    shots = [("hook", 0.72), ("body", 7.05), ("hook_landing", 1.4)]
    written = []

    async def grab():
        async with ev._Chrome(*chrome) as ch:
            for style, path in pages.items():
                await ch.open(path, 1.0, transparent=False)
                for name, t in shots:
                    if style == "classic" and name == "hook_landing":
                        continue
                    dest = folder / f"{name}_{style}.png"
                    dest.write_bytes(await ch.frame(t))
                    written.append(dest)

    asyncio.run(grab())
    movie = _sample_movie(folder, pages, chrome)
    if movie:
        written.append(movie)
    shutil.rmtree(work, ignore_errors=True)
    note = folder / "SOURCES.txt"
    note.write_text(
        "Real headless-Chrome frames of the same two slides.\n"
        "hook_*.png at 0.72s, while the first card is entering.\n"
        "hook_landing_cinematic.png at 1.4s, first card landed, second card still popping.\n"
        "body_*.png at 7.05s, the same card entrance after the chapter card.\n"
        "objects_compare.mp4 plays classic hook, cinematic hook, classic body, cinematic body.\n"
        "The waves are the background in every frame. No still was generated or mocked.\n",
        encoding="utf-8")
    written.append(note)
    return written


def _sample_html() -> str:
    icon = ('<svg data-anim="pop" data-t="0.95" data-dur="0.55" width="150" height="150" '
            'viewBox="0 0 150 150" style="position:absolute; left:1480px; top:180px">'
            '<rect x="18" y="18" width="114" height="114" rx="18" fill="#1a2232" stroke="#f5b83d" stroke-width="6"/>'
            '<circle cx="75" cy="75" r="28" fill="#4c8dff"/></svg>')
    hook = (
        '<section class="slide kind-slide" id="hook" data-kind="slide" data-t0="0.000" data-t1="4.600" '
        'data-sidx="0" data-slabel="HOOK" data-hud="on" data-transition="cut" data-tracker="">'
        '<div class="pad col gap-m">'
        '<div class="kicker" data-anim="fade" data-t="0.200">HOOK</div>'
        '<h1 class="h1" data-anim="words" data-t="0.320" data-dur="0.500">The opening lands.</h1>'
        '<div class="row gap-l" style="margin-top:24px">'
        '<div class="card gold-edge" data-anim="rise" data-t="0.520" data-dur="0.800" style="width:640px">'
        '<div class="h3">AI stocks</div><div class="lead">The card flies in, then sits.</div></div>'
        '<div class="card" data-anim="pop" data-t="1.200" data-dur="0.550" style="width:420px">'
        '<div class="h2 gold">2.3T</div><div class="lead">wiped in a day</div></div>'
        '</div></div>' + icon + '</section>'
    )
    chapter = (
        '<section class="slide kind-chapter" id="chapter" data-kind="chapter" data-t0="4.600" data-t1="6.200" '
        'data-sidx="0" data-slabel="" data-hud="off" data-transition="cut" data-tracker="">'
        '<div class="pad center"><div class="kicker" data-anim="fade" data-t="4.800">CHAPTER</div>'
        '<h1 class="h2" data-anim="words" data-t="5.000">The body</h1></div></section>'
    )
    body = (
        '<section class="slide kind-slide" id="body" data-kind="slide" data-t0="6.200" data-t1="11.000" '
        'data-sidx="0" data-slabel="BODY" data-hud="on" data-transition="cut" data-tracker="">'
        '<div class="pad col gap-m">'
        '<div class="kicker" data-anim="fade" data-t="6.400">BODY</div>'
        '<h1 class="h1" data-anim="words" data-t="6.500" data-dur="0.500">After the chapter.</h1>'
        '<div class="row gap-l" style="margin-top:24px; align-items:flex-end">'
        '<div class="card" data-anim="rise" data-t="6.850" data-dur="0.800" style="width:640px">'
        '<div class="h3">The same card</div><div class="lead">Quieter than the hook.</div></div>'
        '<div style="display:flex; align-items:flex-end; gap:18px; height:220px">'
        '<div class="bar" data-anim="wipe-up" data-t="7.300" data-dur="0.600" style="height:90px"></div>'
        '<div class="bar" data-anim="wipe-up" data-t="7.450" data-dur="0.600" style="height:160px; background:#4c8dff"></div>'
        '<div class="bar" data-anim="wipe-up" data-t="7.600" data-dur="0.600" style="height:120px; background:#f05252"></div>'
        '</div></div></div></section>'
    )
    return hook + chapter + body


def _sample_movie(folder, pages, chrome):
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
    # (style, start, end) so the clip shows the entrance, then the settle.
    spans = (("classic", 0.40, 1.90), ("cinematic", 0.40, 1.90),
             ("classic", 6.70, 8.15), ("cinematic", 6.70, 8.15))
    fps = 10

    async def grab():
        async with ev._Chrome(*chrome) as ch:
            i = 0
            open_style = None
            for style, t0, t1 in spans:
                if style != open_style:
                    await ch.open(pages[style], 1.0, transparent=False)
                    open_style = style
                n = max(2, int(round((t1 - t0) * fps)))
                for k in range(n):
                    t = t0 + (t1 - t0) * (k / max(1, n - 1))
                    (frames / f"f{i:04d}.png").write_bytes(await ch.frame(t))
                    i += 1

    try:
        asyncio.run(grab())
    except Exception:
        shutil.rmtree(frames, ignore_errors=True)
        return None
    dest = folder / "objects_compare.mp4"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(fps),
           "-i", str(frames / "f%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-crf", "20", "-movflags", "+faststart", str(dest)]
    try:
        subprocess.run(cmd, check=True, timeout=180)
    except Exception:
        shutil.rmtree(frames, ignore_errors=True)
        return None
    shutil.rmtree(frames, ignore_errors=True)
    return dest
