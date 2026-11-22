"""Wave background and the cinematic object entrance. No network, no image model."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import explainer_imagery as im  # noqa: E402
import explainer_video as ev  # noqa: E402


def _slides():
    return [
        {"id": "s01", "kind": "slide", "t0": 0.0, "t1": 5.0, "spoken": "The opening"},
        {"id": "s02", "kind": "chapter", "t0": 5.0, "t1": 7.0, "spoken": "Chapter one"},
        {"id": "s03", "kind": "slide", "t0": 7.0, "t1": 12.0, "spoken": "The body"},
    ]


def _compiled(slides):
    html = (
        '<section class="slide" id="s01"><div class="card" data-anim="rise">AI stocks</div>'
        '<h1 class="h1" data-anim="words">One day.</h1></section>'
    )
    return {"html": html, "slides": slides, "duration": 12.0, "start": 0.0, "end": 12.0,
            "sections": ["Markets"], "host_windows": [], "host_sections": []}


def _visual(page: str) -> dict:
    raw = page.split("window.__EXPLAINER = ", 1)[1].split(";</script>", 1)[0]
    return json.loads(raw)["visual"]


def test_style_precedence_and_rich_means_cinematic():
    assert im.visual_style_key("cinematic", "classic") == "cinematic"
    assert im.visual_style_key("rich", "classic") == "cinematic"
    assert im.visual_style_key(None, "rich") == "cinematic"
    assert im.visual_style_key(None, None) == "classic"
    assert im.visual_style_key("nope", "cinematic") == "cinematic"
    assert im.visual_style_key("nope", None) == "classic"
    assert im.VISUAL_STYLES == ("classic", "cinematic")
    assert ev.host_share_key(None, None) == "brief"
    assert ev.pip_frame_key(None, None) == "mix"
    assert ev.bubble_mode_key(None, None) == "some"


def test_waves_are_denser_and_shared_by_both_styles():
    assert im.WAVE_ROWS > 20
    assert im.WAVE_SPEED > 1
    slides = _slides()
    classic = im.page_visual("classic", slides)
    cine = im.page_visual("cinematic", slides)
    assert classic["waves"] == cine["waves"] == {"rows": im.WAVE_ROWS, "speed": im.WAVE_SPEED}
    assert "plates" not in classic and "grain" not in classic and "pop" not in classic
    assert cine["pop"]["hook"]["rot"] > cine["pop"]["body"]["rot"]
    assert cine["pop"]["hook"]["z"] > cine["pop"]["body"]["z"]
    assert cine["pop"]["hook"]["glint"] > cine["pop"]["body"]["glint"]


def test_hook_is_everything_before_the_first_chapter():
    assert im.hook_until(_slides()) == 5.0
    assert im.hook_until([{"kind": "slide", "t0": 0}]) is None
    assert im.hook_until([]) is None


def test_pages_keep_the_slide_html_and_do_not_ask_for_pictures():
    slides = _slides()
    compiled = _compiled(slides)
    classic = ev.page_html(compiled, mode="preview", bubble="off", visual={"style": "classic"})
    rich = ev.page_html(compiled, mode="render", bubble="off", visual={"style": "rich"})
    cine = ev.page_html(compiled, mode="render", bubble="off", visual={"style": "cinematic"})

    def slide_html(page):
        return page.split('<div id="slides">', 1)[1].split('</div><div id="hud">', 1)[0]

    assert slide_html(classic) == slide_html(cine)
    assert "AI stocks" in slide_html(cine)
    assert 'html class="mode-preview"' in classic
    assert "look-cinematic" not in classic.split("<style>", 1)[0]
    assert 'html class="mode-render look-cinematic"' in cine
    assert 'html class="mode-render look-cinematic"' in rich
    for page in (classic, cine):
        vis = _visual(page)
        assert vis["waves"]["rows"] == im.WAVE_ROWS
        assert vis["waves"]["speed"] == im.WAVE_SPEED
        assert vis["hookUntil"] == 5.0
        assert "plates" not in vis
    assert _visual(classic)["style"] == "classic"
    assert _visual(cine)["style"] == "cinematic"
    assert "grok" not in cine.lower()
    assert "data:image/jpeg" not in cine


def test_runtime_keeps_the_waves_and_limits_the_pop_to_objects():
    js = (ROOT / "static" / "explainer" / "runtime.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "explainer" / "design.css").read_text(encoding="utf-8")
    assert "WAVE_ROWS" in js and "WAVE_SPEED" in js
    assert "ctx.fillStyle = '#090c12'" in js
    assert "drawRichBg" not in js
    assert "isPopTarget" in js and "xv-glint" in js
    assert "words" in js and "count" in js
    assert "html.look-cinematic section.slide" in css
    assert "look-rich" not in css
