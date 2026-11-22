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


def test_bots_pills_and_smooth_edges():
    card = sc.bot_card("drop", "#a07858", "Inbox Triage", 10, 20, 0.4)
    assert "Inbox Triage" in card and "#sc-bot-drop" in card and "sc-pill" in card
    assert "geometricPrecision" in sc.sprite("cinematic")
    assert "crispEdges" not in sc.sprite("cinematic")
    lib = sc.sprite("cinematic")
    assert 'class="sc-eye" cx="68" cy="80" rx="7" ry="12" fill="#ffffff"' in lib
    assert 'class="sc-eye" cx="92" cy="80" rx="7" ry="12" fill="#ffffff"' in lib
    assert "sc-flow" in sc.connector(10, 20, 30, 40)
    line = sc.connector(0, 0, 100, 40, 0.5)
    assert "stroke-dasharray=\"2 8\"" in line and "stroke-linecap=\"round\"" in line


def test_demo_placeholder_and_local_upload(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    project = ev.open_project(folder)
    slides = [{"id": "s01", "t0": 1.0, "t1": 9.0, "spoken": "Let me show you the invoice bot.", "demo": ""}]
    assert ev.demo_note(slides[0]["spoken"])
    assert ev.demo_note("Markets fell today") == ""
    assert ev.sync_demo_placeholders(project, slides) == 1
    assert ev.sync_demo_placeholders(project, slides) == 0
    clips = ev.load_youtube(project.data)["clips"]
    assert clips[0]["status"] == "placeholder" and clips[0]["audio"] == "mute"
    compiled = {"slides": slides}
    assert ev.demo_payloads(compiled, clips, "render") == []
    shown = ev.demo_payloads(compiled, clips, "preview")
    assert shown and "show you" in shown[0]["note"].lower()
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"fake")

    def probe(_path):
        return {"seconds": 4.0, "w": 640, "h": 360, "audio": False}

    def run(cmd):
        Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[-1]).write_bytes(b"cut")

    clip = ev.yt_add_upload(project, src, label="Invoice demo", start=0.5, end=2.5, probe=probe, run=run)
    assert clip["status"] == "ready" and clip["audio"] == "mute"
    assert abs(clip["seconds"] - 2.0) < 0.01
    assert (project.dir / clip["file"]).read_bytes() == b"cut"
    bad = tmp_path / "notes.txt"
    bad.write_text("nope")
    try:
        ev.yt_add_upload(project, bad, probe=probe, run=run)
        raise AssertionError("a text file is not a clip")
    except ev.YoutubeError:
        pass
    ev.yt_assign(project, clip["id"], "s01", known={"s01"})
    left = ev.load_youtube(project.data)["clips"]
    assert any(c["id"] == clip["id"] and c["slide"] == "s01" for c in left)
    assert not any(c.get("status") == "placeholder" and c.get("slide") == "s01" for c in left)
    assert ev.demo_payloads(compiled, left, "preview") == []


def test_runtime_does_not_restyle_text_and_does_move_scene_parts():
    js = (ROOT / "static" / "explainer" / "runtime.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "explainer" / "design.css").read_text(encoding="utf-8")
    assert "WAVE_ROWS" in js and "WAVE_SPEED" in js
    assert "ctx.fillStyle = '#090c12'" in js
    assert "isPopTarget" not in js and "xv-glint" not in js and "depthOfField" not in js
    assert "sc-wheel" in js and "sc-glow" in js and "sc-smoke" in js and "botMotion" in js
    assert "brandMotion" in js and "sc-flow" in js and "left: 1040px" in css
    assert "geometricPrecision" in css and "crispEdges" not in css and "crispEdges" not in js
    assert "look-cinematic" not in css and "xv-glint" not in css
