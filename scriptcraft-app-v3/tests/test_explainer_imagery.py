"""Picture styles for the explainer. Network and Grok Imagine are mocked."""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import explainer_imagery as im  # noqa: E402
import explainer_video as ev  # noqa: E402


def _png(color=(20, 40, 80)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), color).save(buf, "PNG")
    return buf.getvalue()


def _slides():
    return [
        {"id": "s01", "kind": "slide", "t0": 0.0, "t1": 6.0,
         "spoken": "AI stocks lost about two trillion dollars in a single trading session on the nasdaq"},
        {"id": "s02", "kind": "scene", "t0": 6.0, "t1": 12.0,
         "spoken": "The data center power bill is climbing as the grid adds batteries and transformers"},
    ]


def _compiled(slides):
    html = "".join(
        f'<section class="slide" id="{s["id"]}">{s["spoken"]}</section>' for s in slides)
    return {"html": html, "slides": slides, "duration": 12.0, "start": 0.0, "end": 12.0,
            "sections": ["Markets"], "host_windows": [], "host_sections": []}


def test_style_precedence_matches_the_other_look_settings():
    assert im.visual_style_key("rich", "classic") == "rich"
    assert im.visual_style_key(None, "cinematic") == "cinematic"
    assert im.visual_style_key("nope", "rich") == "rich"
    assert im.visual_style_key(None, None) == "classic"
    assert im.visual_style_key("nope", "also-nope") == "classic"
    # The settings Christian already has keep their defaults.
    assert ev.host_share_key(None, None) == "brief"
    assert ev.pip_frame_key(None, None) == "mix"
    assert ev.bubble_mode_key(None, None) == "some"
    assert ev.VISUAL_STYLE_DEFAULT == "classic"


def test_prompt_is_literal_and_not_an_allegory():
    data = im.plate_prompt({
        "spoken": "The data center power bill is climbing as the grid adds batteries and transformers",
        "kind": "scene"})
    assert "data" in data.lower()
    assert "battery" in data.lower() or "transformer" in data.lower()
    allegory = im.plate_prompt({
        "spoken": "the market is a rope of marbles in a jar on a measuring tape",
        "kind": "slide"})
    low = allegory.lower()
    assert "rope" not in low
    assert "marble" not in low
    assert "measuring tape" not in low
    assert "16:9" in allegory


def test_classic_skips_generation_and_keeps_the_particle_page(tmp_path):
    calls = {"n": 0}

    def fetch(prompt):
        calls["n"] += 1
        return _png()

    visual = im.imagery_for_page(tmp_path, _slides(), "classic", fetch=fetch)
    assert visual["style"] == "classic"
    assert visual["plates"] == []
    assert calls["n"] == 0
    page = ev.page_html(_compiled(_slides()), mode="preview", bubble="off", visual=visual)
    assert 'html class="mode-preview"' in page
    assert 'html class="mode-preview look-' not in page
    assert '"style": "classic"' in page


def test_rich_and_cinematic_cache_and_survive_a_failed_generator(tmp_path):
    calls = {"n": 0}

    def fetch(prompt):
        calls["n"] += 1
        if "data center" in prompt.lower() or "data-center" in prompt.lower():
            raise RuntimeError("generator down")
        return _png((30, 60, 90))

    slides = _slides()
    first, stats = im.ensure_plates(tmp_path, slides, "rich", fetch=fetch)
    assert calls["n"] == 2
    assert stats["failed"] == 0
    sources = {p["id"]: p["source"] for p in first}
    assert sources["s01"] == "grok"
    assert sources["s02"] == "painted"
    assert len(first[0]["layers"]) == 1
    assert first[0]["layers"][0]["uri"].startswith("data:image/jpeg;base64,")

    again, stats2 = im.ensure_plates(tmp_path, slides, "rich", fetch=fetch)
    assert calls["n"] == 2
    assert stats2["cache_hits"] == 2
    assert [p["source"] for p in again] == ["grok", "painted"]

    cine, _ = im.ensure_plates(tmp_path, slides, "cinematic", fetch=fetch)
    # Same prompts, so the cached stills are reused. No new generator calls.
    assert calls["n"] == 2
    assert len(cine[0]["layers"]) == 3
    assert all(layer["uri"].startswith("data:image/") for layer in cine[0]["layers"])


def test_bad_image_bytes_fall_back_to_paint_and_the_slide_html_stays(tmp_path):
    def fetch(prompt):
        return b"this is not an image"

    visual = im.imagery_for_page(tmp_path, _slides()[:1], "cinematic", fetch=fetch)
    assert visual["style"] == "cinematic"
    assert visual["plates"][0]["source"] == "painted"
    assert len(visual["plates"][0]["layers"]) == 3
    slides = _slides()[:1]
    compiled = _compiled(slides)
    classic = ev.page_html(compiled, mode="render", bubble="off",
                           visual={"style": "classic", "plates": []})
    rich = ev.page_html(compiled, mode="render", bubble="off", visual=visual)
    def slide_html(page):
        return page.split('<div id="slides">', 1)[1].split('</div><div id="hud">', 1)[0]
    assert slide_html(classic) == slide_html(rich)
    assert "AI stocks" in slide_html(rich)
    assert 'html class="mode-render look-cinematic"' in rich
    # The sidecar keeps the prompt and the source, and never a key.
    meta = next((tmp_path / "imagery").glob("*.json"))
    text = meta.read_text(encoding="utf-8")
    assert "painted" in text
    assert "api_key" not in text.lower()
    assert "xai-" not in text


def test_ken_burns_moves_forward_through_the_slide():
    spec = {"depth": 1.0, "dx": 40, "dy": 10, "zoom": 0.06}
    z0, x0, y0 = im.layer_placement(spec, 0.0)
    z1, x1, y1 = im.layer_placement(spec, 1.0)
    assert z1 > z0
    assert x0 < 0 < x1
    assert y0 < 0 < y1
    # A farther layer travels less.
    far = {"depth": 0.35, "dx": 40, "dy": 10, "zoom": 0.06}
    _, xf, _ = im.layer_placement(far, 1.0)
    assert abs(xf) < abs(x1)


def test_unknown_style_on_the_page_is_classic():
    page = ev.page_html(_compiled(_slides()), bubble="off",
                        visual={"style": "watercolor", "plates": [{"layers": [{"uri": "data:image/png;base64,aa"}]}]})
    assert 'html class="mode-preview"' in page
    assert '"style": "classic"' in page


def test_runtime_keeps_the_particle_field_for_classic():
    js = (ROOT / "static" / "explainer" / "runtime.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "explainer" / "design.css").read_text(encoding="utf-8")
    assert "ctx.fillStyle = '#090c12'" in js
    assert "drawRichBg" in js
    assert "VISUAL.style || 'classic'" in js
    assert "html.look-rich .scene" in css
    assert "html.look-cinematic .scene" in css
