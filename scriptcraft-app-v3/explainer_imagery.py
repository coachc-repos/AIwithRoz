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
            if old.is_file():
                old.unlink()
    folder.mkdir(parents=True, exist_ok=True)
    slides = [
        {"id": "hook", "kind": "scene", "t0": 0.0, "t1": 5.0},
        {"id": "chapter", "kind": "chapter", "t0": 5.0, "t1": 6.4},
        {"id": "grid", "kind": "scene", "t0": 6.4, "t1": 11.4},
        {"id": "street", "kind": "scene", "t0": 11.4, "t1": 16.4},
    ]
    html = _sample_html()
    compiled = {"html": html, "slides": slides, "duration": 16.4, "start": 0.0, "end": 16.4,
                "sections": ["Hook"], "host_windows": [], "host_sections": []}
    work = folder / "_pages"
    work.mkdir(parents=True, exist_ok=True)
    pages = {}
    for style in ("classic", "cinematic"):
        page = work / f"{style}.html"
        page.write_text(ev.page_html(compiled, mode="render", title="Scene objects",
                                     bubble="off", visual={"style": style}), encoding="utf-8")
        pages[style] = page
    chrome = ev.find_chrome()
    if not chrome:
        note = folder / "SOURCES.txt"
        note.write_text("Chrome was not available, so no stills were captured.\n", encoding="utf-8")
        shutil.rmtree(work, ignore_errors=True)
        return [note]
    shots = [("hook", 2.4), ("datacenter", 8.8), ("street", 13.6)]
    written = []

    async def grab():
        async with ev._Chrome(*chrome) as ch:
            for style, path in pages.items():
                await ch.open(path, 1.0, transparent=False)
                for name, t in shots:
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
        "Real headless-Chrome frames of the same three scenes.\n"
        "hook_*.png at 2.4s, a close car and buildings, before the chapter card.\n"
        "datacenter_*.png at 8.8s, the hall, houses, batteries and a power line.\n"
        "street_*.png at 13.6s, cars, a factory and trees.\n"
        "objects_compare.mp4 plays classic then cinematic for each scene, so the motion shows.\n"
        "classic is the flat object. cinematic is the same placement with volume and motion.\n"
        "No image was generated or mocked. Text cards are not in these frames.\n",
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
    return hook + chapter + grid + street


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
    spans = (("classic", 1.6, 3.3), ("cinematic", 1.6, 3.3),
             ("classic", 8.0, 9.6), ("cinematic", 8.0, 9.6),
             ("classic", 12.8, 14.4), ("cinematic", 12.8, 14.4))
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
