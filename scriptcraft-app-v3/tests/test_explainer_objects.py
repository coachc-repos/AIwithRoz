"""Scene objects stay one piece: shared edges overlap, and a render is not blank."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import explainer_scenes as sc
import explainer_video as ev


def test_every_object_is_in_both_styles_on_whole_pixels():
    for style in ("classic", "cinematic"):
        lib = sc.sprite(style)
        assert 'shape-rendering="geometricPrecision"' in lib
        for name in sc.SCENE_OBJECTS:
            assert f'id="sc-{name}"' in lib
    cine = sc._cinematic()
    # The car is one body, and the wheels are a separate turning part that
    # the body is drawn over, so the sill covers the top of each tire.
    assert cine["car"].count("<path") >= 1
    assert "sc-wheel" in cine["car"]
    assert 'stroke="' not in cine["car"]
    for name, markup in {**sc._classic(), **cine}.items():
        assert ".5\"" not in markup and ".5 " not in markup, name


def test_each_object_paints_in_a_render():
    chrome = ev.find_chrome()
    if not chrome:
        return
    cells = []
    centers = []
    for i, name in enumerate(sc.SCENE_OBJECTS):
        bw, bh = sc.SCENE_BOX[name]
        col, row = i % 5, i // 5
        cell_w, cell_h = 360, 500
        left, top = 40 + col * cell_w, 40 + row * cell_h
        h = 420
        w = max(80, int(round(h * bw / bh)))
        if w > cell_w - 20:
            w = cell_w - 20
            h = int(round(w * bh / bw))
        x = left + (cell_w - w) // 2
        y = top + (cell_h - h) // 2
        cells.append(
            f'<svg class="sc" data-sc="{name}" data-depth="1" x="{x}" y="{y}" '
            f'width="{w}" height="{h}" viewBox="0 0 {bw} {bh}"><use href="#sc-{name}"/></svg>'
        )
        centers.append((x + w // 2, y + h // 2))
    body = (
        '<section class="slide" id="s" data-kind="scene" data-t0="0" data-t1="4" '
        'data-sidx="0" data-slabel="" data-hud="off" data-transition="cut" data-tracker="">'
        '<div class="scene" style="background:#090c12">'
        f'<svg width="1920" height="1080" viewBox="0 0 1920 1080">{"".join(cells)}</svg>'
        '</div></section>'
    )
    comp = {"html": body, "slides": [{"id": "s", "t0": 0, "t1": 4, "kind": "scene"}],
            "duration": 4, "start": 0, "end": 4, "sections": [], "host_windows": [], "host_sections": []}
    page = Path("/tmp/objects_check.html")
    page.write_text(ev.page_html(comp, mode="render", visual={"style": "cinematic"}), encoding="utf-8")

    async def shoot():
        async with ev._Chrome(*chrome) as ch:
            await ch.open(page, 1.0, transparent=False)
            return await ch.frame(1.7)

    from PIL import Image
    import io
    im = Image.open(io.BytesIO(asyncio.run(shoot()))).convert("RGB")
    bg = (9, 12, 18)
    for name, (cx, cy) in zip(sc.SCENE_OBJECTS, centers):
        # A small patch, so a thin object such as the power pole still counts.
        hit = False
        for dx in range(-18, 19, 6):
            for dy in range(-18, 19, 6):
                px = im.getpixel((min(im.width - 1, max(0, cx + dx)), min(im.height - 1, max(0, cy + dy))))
                if abs(px[0] - bg[0]) + abs(px[1] - bg[1]) + abs(px[2] - bg[2]) > 24:
                    hit = True
                    break
            if hit:
                break
        assert hit, name
