"""Waves stay. Scene objects are flat or detailed. Text slides are not restyled."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import explainer_imagery as im  # noqa: E402
import explainer_scenes as sc  # noqa: E402
import explainer_video as ev  # noqa: E402


def _slides():
    return [
        {"id": "s01", "kind": "scene", "t0": 0.0, "t1": 5.0},
        {"id": "s02", "kind": "chapter", "t0": 5.0, "t1": 7.0},
        {"id": "s03", "kind": "slide", "t0": 7.0, "t1": 12.0},
    ]


def _compiled(slides):
    html = (
        '<section class="slide" id="s03"><div class="card" data-anim="rise">AI stocks</div>'
        '<h1 class="h1" data-anim="words">One day.</h1>'
        + sc.place("house", 200, 640, 220, 170, 1)
        + "</section>"
    )
    return {"html": html, "slides": slides, "duration": 12.0, "start": 0.0, "end": 12.0,
            "sections": ["Markets"], "host_windows": [], "host_sections": []}


def _cfg(page: str) -> dict:
    raw = page.split("window.__EXPLAINER = ", 1)[1].split(";</script>", 1)[0]
    return json.loads(raw)


def test_style_precedence_and_rich_means_cinematic():
    assert im.visual_style_key("cinematic", "classic") == "cinematic"
    assert im.visual_style_key("rich", None) == "cinematic"
    assert im.visual_style_key(None, "rich") == "cinematic"
    assert im.visual_style_key(None, None) == "classic"
    assert im.visual_style_key("nope", None) == "classic"
    assert im.VISUAL_STYLES == ("classic", "cinematic")
    assert ev.host_share_key(None, None) == "brief"
    assert ev.pip_frame_key(None, None) == "mix"
    assert ev.bubble_mode_key(None, None) == "some"


def test_waves_are_shared_and_denser_than_the_old_field():
    assert im.WAVE_ROWS == 34 and im.WAVE_ROWS > 20
    assert im.WAVE_SPEED == 1.4 and im.WAVE_SPEED > 1
    slides = _slides()
    assert im.page_visual("classic", slides)["waves"] == im.page_visual("cinematic", slides)["waves"]
    assert im.hook_until(slides) == 5.0
    assert im.hook_until([{"kind": "slide", "t0": 0}]) is None


def test_cinematic_objects_have_volume_and_classic_ones_stay_flat():
    classic = sc.sprite("classic")
    cine = sc.sprite("cinematic")
    for name in ("house", "building", "datacenter", "car", "tree", "factory"):
        assert f'id="sc-{name}"' in classic
        assert f'id="sc-{name}"' in cine
    assert "linearGradient" not in classic
    assert "sc-wheel" not in classic
    assert "linearGradient" in cine
    assert "sc-wheel" in cine and "sc-glow" in cine and "sc-smoke" in cine
    assert sc.place("car", 10, 20, 240, 120, 1.4).count('href="#sc-car"') == 1
    assert 'data-depth="1.4"' in sc.place("car", 10, 20, 240, 120, 1.4)


def test_text_slide_markup_is_unchanged_and_cards_are_not_restyled():
    slides = _slides()
    compiled = _compiled(slides)
    classic = ev.page_html(compiled, mode="preview", bubble="off", visual={"style": "classic"})
    cine = ev.page_html(compiled, mode="render", bubble="off", visual={"style": "cinematic"})

    def slide_html(page):
        return page.split('<div id="slides">', 1)[1].split("</div><div id=\"hud\">", 1)[0]

    assert slide_html(classic) == slide_html(cine)
    assert "AI stocks" in slide_html(cine)
    assert "One day." in slide_html(cine)
    assert 'class="card"' in slide_html(cine)
    assert "look-cinematic" not in classic and "look-cinematic" not in cine
    assert "xv-glint" not in classic and "xv-glint" not in cine
    assert _cfg(classic)["visual"]["style"] == "classic"
    assert _cfg(cine)["visual"]["style"] == "cinematic"
    assert _cfg(classic)["visual"]["waves"]["rows"] == 34
    # The detailed materials live in the symbol library, not in the slide.
    lib_c = classic.split('id="sc-lib"', 1)[1].split("</svg>", 1)[0]
    lib_k = cine.split('id="sc-lib"', 1)[1].split("</svg>", 1)[0]
    assert "linearGradient" not in lib_c
    assert "linearGradient" in lib_k
    assert "data:image/jpeg" not in cine


def test_runtime_does_not_restyle_text_and_does_move_scene_parts():
    js = (ROOT / "static" / "explainer" / "runtime.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "explainer" / "design.css").read_text(encoding="utf-8")
    assert "WAVE_ROWS" in js and "WAVE_SPEED" in js
    assert "ctx.fillStyle = '#090c12'" in js
    assert "isPopTarget" not in js and "xv-glint" not in js and "depthOfField" not in js
    assert "sc-wheel" in js and "sc-glow" in js and "sc-smoke" in js
    assert "look-cinematic" not in css and "xv-glint" not in css
