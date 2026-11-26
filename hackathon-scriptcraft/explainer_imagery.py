"""Picture treatment for explainer slides.

The background stays the particle waves on every style. Text slides are
otherwise unchanged. classic draws scene objects as flat shapes. cinematic
draws the same objects with volume and motion. `rich` means cinematic.
"""
from __future__ import annotations

VISUAL_STYLES = ("classic", "cinematic")
VISUAL_STYLE_DEFAULT = "classic"
# Old projects may still say rich. That is the detailed scene objects.
_ALIASES = {"rich": "cinematic"}

# The wave field used to be 20 rows at speed 1. Denser, and a little faster.
# Both styles use these. The runtime reads them from the page config.
WAVE_ROWS = 34
WAVE_SPEED = 1.4

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
    return out


def write_imagery_samples(folder) -> list:
    """Same three scenes in classic and cinematic, from headless Chrome.

    A hook street, a data-center yard, and a street of cars. No image model.
    """
    import asyncio
    import shutil
    import subprocess
    from pathlib import Path

    import explainer_video as ev

    folder = Path(folder)
    if folder.exists():
        for old in folder.iterdir():
            keep = old.name.startswith(("edge_", "object_")) or old.name in {
                "demo_filled.png", "objects_sheet_cinematic.png", "objects_fixed.mp4"}
            if old.is_file() and not keep:
                old.unlink()
    folder.mkdir(parents=True, exist_ok=True)
    slides = [
        {"id": "hook", "kind": "scene", "t0": 0.0, "t1": 5.0},
        {"id": "chapter", "kind": "chapter", "t0": 5.0, "t1": 6.4},
        {"id": "grid", "kind": "scene", "t0": 6.4, "t1": 11.4},
        {"id": "street", "kind": "scene", "t0": 11.4, "t1": 16.4},
        {"id": "bots", "kind": "scene", "t0": 16.4, "t1": 21.4, "spoken": "Lots of bots running"},
        {"id": "tracker", "kind": "scene", "t0": 21.4, "t1": 26.4, "spoken": "One rule for every bot"},
        {"id": "demo", "kind": "slide", "t0": 26.4, "t1": 31.0,
         "spoken": "Let me show you how the bot sends the invoice.", "demo": "The invoice bot sending one invoice"},
        {"id": "hero", "kind": "scene", "t0": 31.0, "t1": 36.0, "spoken": "Nvidia builds the chips."},
        {"id": "compare", "kind": "scene", "t0": 36.0, "t1": 41.0, "spoken": "ChatGPT and Nvidia"},
        {"id": "orbit", "kind": "scene", "t0": 41.0, "t1": 46.0, "spoken": "ChatGPT, Claude, Nvidia, Tesla and YouTube"},
    ]
    html = _sample_html()
    compiled = {"html": html, "slides": slides, "duration": 46.0, "start": 0.0, "end": 46.0,
                "sections": ["Hook"], "host_windows": [], "host_sections": []}
    work = folder / "_pages"
    work.mkdir(parents=True, exist_ok=True)
    pages = {}
    for style in ("classic", "cinematic"):
        page = work / f"{style}.html"
        demos = [{"slide": "demo", "t0": 26.4, "t1": 31.0, "label": "Demo video",
                  "note": "The invoice bot sending one invoice"}] if style == "cinematic" else []
        page.write_text(ev.page_html(compiled, mode="render", title="Scene objects",
                                     bubble="off", visual={"style": style}, demos=demos),
                        encoding="utf-8")
        pages[style] = page
    chrome = ev.find_chrome()
    if not chrome:
        note = folder / "SOURCES.txt"
        note.write_text("Chrome was not available, so no stills were captured.\n", encoding="utf-8")
        shutil.rmtree(work, ignore_errors=True)
        return [note]
    shots = [("hook", 2.4), ("datacenter", 8.8), ("street", 13.6),
             ("bots", 19.2), ("tracker", 24.2), ("demo_empty", 28.2),
             ("brand_hero", 33.4), ("brand_compare", 38.4), ("brand_orbit", 43.6)]
    written = []

    async def grab():
        async with ev._Chrome(*chrome) as ch:
            for style, path in pages.items():
                await ch.open(path, 1.0, transparent=False)
                for name, t in shots:
                    if name in ("demo_empty", "brand_hero", "brand_compare", "brand_orbit") and style != "cinematic":
                        continue
                    dest = folder / f"{name}_{style}.png"
                    dest.write_bytes(await ch.frame(t))
                    written.append(dest)

    asyncio.run(grab())
    written.extend(_sample_movie(folder, pages, chrome) or [])
    shutil.rmtree(work, ignore_errors=True)
    note = folder / "SOURCES.txt"
    note.write_text(
        "Real headless-Chrome frames. No mocked pictures.\n"
        "hook, datacenter and street: the same scene in classic (flat) and cinematic (volume).\n"
        "edge_before.png / edge_after.png: zoomed crop of the street car before and after smoothing.\n"
        "edge_4k.png: the same crop from a scale-2 capture, which is how the 4K render draws it.\n"
        "bots_*.png: the grid, eyes centered and solid. bots_idle.mp4 is several seconds of them moving.\n"
        "tracker_*.png: the hub, with dots that travel toward it in the cinematic mp4.\n"
        "brand_hero_cinematic.png, brand_compare_cinematic.png, brand_orbit_cinematic.png:\n"
        "  Nvidia, then ChatGPT beside Nvidia, then five logos on a ring. Logos are fetched\n"
        "  from Simple Icons (CC0) at render time and are not stored in the repository.\n"
        "  brands_motion.mp4 plays those three.\n"
        "demo_empty_cinematic.png: the preview placeholder, to the right of the text card.\n"
        "demo_filled.png: a slide after an uploaded clip is assigned. An empty slot is not drawn in the final render.\n",
        encoding="utf-8")
    written.append(note)
    return written


def _sky() -> str:
    stars = "".join(
        f'<circle cx="{x}" cy="{y}" r="1.6" fill="#8a94a6"/>'
        for x, y in ((140, 90), (420, 140), (880, 70), (1300, 120), (1680, 80), (1100, 180))
    )
    return (
        '<rect width="1920" height="1080" fill="#0c1526"/>'
        '<rect y="690" width="1920" height="390" fill="#101820"/>' + stars
    )


def _scene(sid, kind, t0, t1, label, hud, inner) -> str:
    return (
        f'<section class="slide kind-{kind}" id="{sid}" data-kind="{kind}" data-t0="{t0:.3f}" '
        f'data-t1="{t1:.3f}" data-sidx="0" data-slabel="{label}" data-hud="{hud}" '
        f'data-transition="cut" data-tracker=""><div class="scene">'
        f'<svg class="fill" viewBox="0 0 1920 1080">{_sky()}{inner}</svg></div></section>'
    )


def _sample_html() -> str:
    from explainer_scenes import place
    hook = _scene("hook", "scene", 0, 5, "HOOK", "off", "".join([
        place("building", 70, 500, 150, 190, 0.4),
        place("building", 240, 460, 180, 230, 0.5),
        place("building", 1500, 430, 210, 260, 0.45),
        place("tree", 1240, 560, 120, 150, 0.75),
        place("house", 980, 545, 230, 175, 1.0),
        place("car", 80, 760, 560, 280, 1.8),
        place("car", 760, 820, 300, 150, 1.15),
    ]))
    chapter = (
        '<section class="slide kind-chapter" id="chapter" data-kind="chapter" data-t0="5.000" '
        'data-t1="6.400" data-sidx="0" data-slabel="" data-hud="off" data-transition="cut" data-tracker="">'
        '<div class="pad center"><div class="kicker">CHAPTER</div><h1 class="h2">The grid</h1></div></section>'
    )
    grid = _scene("grid", "scene", 6.4, 11.4, "GRID", "off", "".join([
        place("powerline", 60, 430, 280, 140, 0.35),
        place("tree", 1560, 540, 130, 160, 0.55),
        place("house", 1180, 545, 230, 175, 0.85),
        place("house", 1440, 575, 190, 145, 0.75),
        place("datacenter", 160, 400, 860, 450, 1.15),
    ]))
    street = _scene("street", "scene", 11.4, 16.4, "STREET", "off", "".join([
        place("building", 40, 460, 170, 220, 0.4),
        place("building", 230, 420, 200, 260, 0.5),
        place("factory", 1240, 470, 400, 300, 0.95),
        place("tree", 1080, 540, 140, 170, 0.8),
        place("tree", 1700, 570, 120, 150, 0.7),
        place("car", 80, 780, 460, 230, 1.5),
        place("car", 620, 830, 340, 170, 1.15),
    ]))
    bots = _bots_section()
    tracker = _tracker_section()
    demo = (
        '<section class="slide kind-slide" id="demo" data-kind="slide" data-t0="26.400" data-t1="31.000" '
        'data-sidx="0" data-slabel="DEMO" data-hud="on" data-transition="cut" data-tracker="" '
        'data-demo="The invoice bot sending one invoice">'
        '<div style="position:absolute; left:140px; top:170px; width:720px">'
        '<div class="kicker">DEMO</div>'
        '<h1 class="h2" style="white-space:nowrap">Let me show you.</h1>'
        '<div class="card" style="max-width:560px; margin-top:28px"><div class="h3">The invoice bot</div>'
        '<div class="lead">Narration keeps going.</div></div></div></section>'
    )
    return hook + chapter + grid + street + bots + tracker + demo + _brand_sections()


def _mark(key: str):
    import explainer_brands as eb
    row = next(r for r in eb.BRANDS if r[0] == key)
    tinted = eb.tint_icon(eb.fetch_icon(row[2]), row[3]) or eb.monogram_svg(row[1], row[3])
    return {"name": row[1], "color": row[3], "svg": tinted}


def _brand_sections() -> str:
    import explainer_brands as eb
    nvidia, chatgpt = _mark("nvidia"), _mark("chatgpt")
    ring = [_mark(k) for k in ("chatgpt", "claude", "nvidia", "tesla", "youtube")]
    def section(sid, t0, t1, label, title, inner):
        return (
            f'<section class="slide kind-scene" id="{sid}" data-kind="scene" data-t0="{t0:.3f}" '
            f'data-t1="{t1:.3f}" data-sidx="0" data-slabel="{label}" data-hud="off" '
            f'data-transition="cut" data-tracker=""><div class="scene sc-open">'
            f'<h1 class="h1" data-anim="words" data-t="+0.1" style="position:absolute; left:120px; top:60px; margin:0">{title}</h1>'
            f'{inner}</div></section>'
        )
    return (
        section("hero", 31, 36, "HERO", "Nvidia", eb.hero(nvidia["name"], nvidia["color"], nvidia["svg"], delay=0.25))
        + section("compare", 36, 41, "COMPARE", "ChatGPT and Nvidia", eb.comparison(chatgpt, nvidia))
        + section("orbit", 41, 46, "ORBIT", "One ecosystem", eb.orbit(ring))
    )


def _bots_section() -> str:
    from explainer_scenes import BOT_COLORS, bot_card
    items = [
        ("circle", BOT_COLORS[0], "Invoice Agent", 140, 340, 0.25),
        ("squircle", BOT_COLORS[1], "IG Carousel", 760, 340, 0.45),
        ("blob", BOT_COLORS[2], "Content Bot", 1380, 340, 0.65),
        ("squircle", BOT_COLORS[5], "Brand Partnership", 140, 700, 0.85),
        ("drop", BOT_COLORS[4], "Inbox Triage", 760, 700, 1.05),
        ("circle", BOT_COLORS[3], "Health Agent", 1380, 700, 1.25),
    ]
    cards = "".join(bot_card(*item) for item in items)
    return (
        '<section class="slide kind-scene" id="bots" data-kind="scene" data-t0="16.400" data-t1="21.400" '
        'data-sidx="0" data-slabel="BOTS" data-hud="off" data-transition="cut" data-tracker="">'
        '<div class="scene sc-open"><div class="pad">'
        '<h1 class="h1" data-anim="words" data-t="+0.15">Lots of bots running</h1>'
        + cards + '</div></div></section>'
    )


def _tracker_section() -> str:
    from explainer_scenes import BOT_COLORS, bot, check_badge, connector
    lines = "".join([
        connector(340, 700, 960, 500, 0.7),
        connector(960, 720, 960, 500, 0.85),
        connector(1580, 700, 960, 500, 1.0),
    ])
    figs = "".join([
        bot("blob", BOT_COLORS[2], 890, 300, 120, 1),
        bot("circle", BOT_COLORS[0], 250, 720, 150, 1, hop=1.3, look="hub"),
        bot("squircle", BOT_COLORS[1], 880, 740, 150, 1, hop=1.5, look="hub"),
        bot("squircle", BOT_COLORS[5], 1500, 720, 150, 1, hop=1.7, look="hub"),
    ])
    badges = "".join([
        check_badge(400, 730, 1.3),
        check_badge(1030, 750, 1.5),
        check_badge(1650, 730, 1.7),
    ])
    return (
        '<section class="slide kind-scene" id="tracker" data-kind="scene" data-t0="21.400" data-t1="26.400" '
        'data-sidx="0" data-slabel="TRACKER" data-hud="off" data-transition="cut" data-tracker="">'
        '<div class="scene sc-open">'
        '<h1 class="h1" data-anim="words" data-t="+0.1" style="position:absolute; left:160px; top:70px; margin:0">One rule for every bot</h1>'
        '<div class="sc-message" data-anim="fade" data-t="+0.35" style="position:absolute; left:520px; top:200px">'
        'Ping me when you start, finish or get stuck</div>'
        '<div class="sc-hub" data-anim="pop" data-t="+0.55" style="position:absolute; left:790px; top:450px">Agent Tracker</div>'
        '<svg class="fill" viewBox="0 0 1920 1080" style="position:absolute; inset:0">'
        f'{lines}{figs}{badges}</svg></div></section>'
    )


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
    clips = (
        ("bots_idle.mp4", (("cinematic", 16.8, 20.6),)),
        ("brands_motion.mp4", (("cinematic", 31.2, 33.6), ("cinematic", 36.2, 38.4), ("cinematic", 41.3, 44.2))),
    )
    fps = 10

    made = []

    async def grab():
        async with ev._Chrome(*chrome) as ch:
            open_style = None
            for name, spans in clips:
                i = 0
                for style, t0, t1 in spans:
                    if style != open_style:
                        await ch.open(pages[style], 1.0, transparent=False)
                        open_style = style
                    n = max(2, int(round((t1 - t0) * fps)))
                    for k in range(n):
                        t = t0 + (t1 - t0) * (k / max(1, n - 1))
                        (frames / f"f{i:04d}.png").write_bytes(await ch.frame(t))
                        i += 1
                dest = folder / name
                cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(fps),
                       "-i", str(frames / "f%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                       "-crf", "20", "-movflags", "+faststart", str(dest)]
                subprocess.run(cmd, check=True, timeout=180)
                made.append(dest)
                for old in frames.glob("f*.png"):
                    old.unlink()

    try:
        asyncio.run(grab())
    except Exception:
        shutil.rmtree(frames, ignore_errors=True)
        return made
    shutil.rmtree(frames, ignore_errors=True)
    return made
