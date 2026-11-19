"""Corner frames and the guide character for the explainer.

No HeyGen, Claude, or network calls. One optional local Chrome still checks
that the page punches the device screen and draws the bubble.

    python scriptcraft-app-v3/tests/test_explainer_look.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import re
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
APPS = ("scriptcraft-app-v3", "scriptcraft-app-v3-container")
SAMPLES = ROOT / "scriptcraft-app-v3" / "tests" / "samples" / "explainer_look"
GOLD = (245, 184, 61)
PAPER = (242, 244, 248)


def load(name: str, app: str):
    path = ROOT / app / "explainer_video.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def hits(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def near(px, rgb, tol=12) -> bool:
    return all(abs(int(px[i]) - rgb[i]) <= tol for i in range(3))


def words_in(line: str, *sources: str) -> bool:
    blob = " ".join(sources).lower()
    at = 0
    for word in re.findall(r"[A-Za-z0-9']+", line.replace("…", "")):
        found = blob.find(word.lower(), at)
        if found < 0:
            return False
        at = found + len(word)
    return True


def check_modes(xv) -> None:
    assert xv.PIP_FRAME_DEFAULT == "mix"
    assert xv.BUBBLE_DEFAULT == "some"
    assert xv.pip_frame_key(None, None) == "mix"
    assert xv.pip_frame_key("nope", None) == "mix"
    assert xv.pip_frame_key("", "tv") == "tv"
    assert xv.pip_frame_key("off", "monitor") == "off"
    assert xv.pip_frame_key(None, "laptop") == "laptop"
    assert xv.bubble_mode_key(None, None) == "some"
    assert xv.bubble_mode_key("often", "off") == "often"
    assert xv.bubble_mode_key(None, "off") == "off"
    assert xv.bubble_mode_key("nope", "often") == "often"
    assert xv.look_of({}, None) == ("mix", "some")
    assert xv.look_of({"pip_frame": "off", "bubble": "often"}, {"pip_frame": "tv"}) == ("tv", "often")

    devices = [xv.pip_device_for("mix", i) for i in range(8)]
    assert devices == ["monitor", "", "laptop", "", "phone", "", "tv", ""]
    assert all(xv.pip_device_for("off", i) == "" for i in range(4))
    assert [xv.pip_device_for("phone", i) for i in range(3)] == ["phone", "phone", "phone"]

    windows = [{"t0": i, "t1": i + 1, "layout": "pip" if i != 1 else "full"} for i in range(4)]
    framed = xv.framed_windows(windows, "mix")
    assert windows[0].get("frame") is None  # the input is not mutated
    assert [w["frame"] for w in framed] == ["monitor", "", "", "laptop"]
    assert framed[1]["layout"] == "full"
    assert xv._window_box({"layout": "pip", "frame": "monitor"}, 2) == {
        "x": 1352 * 2, "y": 710 * 2, "w": 432 * 2, "h": 244 * 2}
    assert xv._window_box({"layout": "pip", "frame": ""}, 1) == {"x": 1296, "y": 694, "w": 544, "h": 306}
    assert xv._window_box({"layout": "full", "frame": "monitor"}, 1)["w"] == 1920


def check_geometry(xv) -> None:
    aside = (xv.ASIDE_AT[0], xv.ASIDE_AT[1], xv.ASIDE_SIZE[0], xv.ASIDE_SIZE[1])
    assert aside[0] >= 0 and aside[1] >= 0
    assert aside[0] + aside[2] <= 1920 and aside[1] + aside[3] <= 1060
    pip = xv.HOST_LAYOUTS["pip"]
    pip_box = (pip["x"], pip["y"], pip["w"], pip["h"])
    assert not hits(aside, pip_box)
    assert not hits(aside, (xv.HOST_LAYOUTS["right"]["x"], xv.HOST_LAYOUTS["right"]["y"],
                            xv.HOST_LAYOUTS["right"]["w"], xv.HOST_LAYOUTS["right"]["h"]))
    for name, geom in xv.PIP_FRAME_GEOM.items():
        outer, screen = geom["outer"], geom["screen"]
        assert outer == pip_box, name
        assert all(v % 2 == 0 for v in outer + screen), name
        sx, sy, sw, sh = screen
        ox, oy, ow, oh = outer
        assert ox <= sx and oy <= sy and sx + sw <= ox + ow and sy + sh <= oy + oh, name
        assert abs(sw / sh - 16 / 9) < 0.12, name
        assert not hits(aside, screen)


def check_bubble_text(xv) -> None:
    spoken = "So the index fund paid for it too and then some."
    idea = "Cards slide in while the host names the drop."
    line = xv.bubble_text(spoken, idea)
    assert line == "the index fund paid for it too and then some"
    assert words_in(line, spoken)
    assert "Cards" not in line
    long = xv.bubble_text("Markets moved by more than anyone expected today and the index fund paid.", "")
    assert long.endswith("…") and len(long) <= xv.BUBBLE_MAX
    assert words_in(long, "Markets moved by more than anyone expected today and the index fund paid.")
    assert xv.bubble_text("So yes.", "") == ""
    assert xv.bubble_text("", idea).startswith("Cards slide in")
    assert xv.bubble_text("", "") == ""

    slides = []
    for i in range(6):
        slides.append({"id": f"s{i:02d}", "kind": "slide", "host": "", "sections": [],
                       "t0": i * 10, "t1": i * 10 + 9,
                       "spoken": f"Markets moved by more than anyone expected on day {i} of the selloff.",
                       "idea": ""})
    slides.append({"id": "ch", "kind": "chapter", "host": "", "t0": 70, "t1": 80,
                   "spoken": "This chapter opens the next section of the story today.", "idea": ""})
    slides.append({"id": "full", "kind": "slide", "host": "full", "t0": 80, "t1": 90,
                   "spoken": "The presenter fills the frame while talking to the viewer now.", "idea": ""})
    slides.append({"id": "left", "kind": "slide", "host": "left", "t0": 90, "t1": 100,
                   "spoken": "A side panel would cover the lower left of this slide entirely.", "idea": ""})
    slides.append({"id": "short", "kind": "slide", "host": "", "t0": 100, "t1": 104,
                   "spoken": "Too short a beat to hold a readable line on screen.", "idea": ""})
    some = xv.aside_cues(slides, "some")
    often = xv.aside_cues(slides, "often")
    assert xv.aside_cues(slides, "off") == []
    assert [c["slide"] for c in some] == ["s00", "s03"]
    assert [c["slide"] for c in often] == [f"s{i:02d}" for i in range(6)]
    for cue in often:
        assert 2.0 <= cue["t1"] - cue["t0"] <= 3.41
        assert words_in(cue["text"], slides[int(cue["slide"][1:])]["spoken"])
        assert not hits((xv.ASIDE_AT[0], xv.ASIDE_AT[1], xv.ASIDE_SIZE[0], xv.ASIDE_SIZE[1]),
                        (xv.HOST_LAYOUTS["pip"]["x"], xv.HOST_LAYOUTS["pip"]["y"],
                         xv.HOST_LAYOUTS["pip"]["w"], xv.HOST_LAYOUTS["pip"]["h"]))


def check_page(xv) -> None:
    sentence = "Markets moved by more than anyone expected today and the index fund paid for the drop".split()
    words, t = [], 0.0
    for _ in range(6):
        for word in sentence:
            words.append({"text": word, "start": round(t, 3), "end": round(t + 0.28, 3)})
            t += 0.32
    timeline = xv.Timeline(words, t + 2)
    raw = ('<section id="s01" data-at="Markets moved by more" data-kind="slide" data-host="pip">'
           '<h1 class="h1">Markets moved</h1></section>'
           '<section id="s02" data-at="the index fund paid" data-kind="slide">'
           '<h1 class="h1">The fund</h1></section>'
           '<section id="s03" data-at="Markets moved by more" data-kind="slide" data-host="pip">'
           '<h1 class="h1">Again</h1></section>')
    comp = xv.compile_composition(raw, timeline, duration=t + 2, plan={"slides": [], "sections": []},
                                  logos={}, values={}, logo_choices={}, host_on=True)
    assert comp["slides"][0]["spoken"].startswith("Markets moved")
    assert [w["layout"] for w in comp["host_windows"]] == ["pip", "pip"], comp["host_windows"]
    html = xv.page_html(comp, mode="render", host={"focus": 0.45, "pip_frame": "off"},
                        pip_frame="monitor", bubble="often")
    cfg = json.loads(html.split("window.__EXPLAINER = ", 1)[1].split(";</script>", 1)[0])
    assert [w["frame"] for w in cfg["host"]["windows"]] == ["monitor", "monitor"]
    assert cfg["host"]["frames"]["monitor"]["sx"] == 1352
    assert cfg["host"]["frames"]["monitor"]["uri"].startswith("data:image/png;base64,")
    assert cfg["asides"]
    narration = " ".join(w["text"] for w in words)
    assert all(words_in(a["text"], narration) for a in cfg["asides"])
    assert "data-host=\"pip\"" in html
    off = json.loads(xv.page_html(comp, mode="render", host={"focus": 0.45}, pip_frame="off", bubble="off")
                     .split("window.__EXPLAINER = ", 1)[1].split(";</script>", 1)[0])
    assert [w["frame"] for w in off["host"]["windows"]] == ["", ""]
    assert off["host"]["frames"] == {}
    assert off["asides"] == []
    saved = json.loads(xv.page_html(comp, mode="render", host={"focus": 0.45, "pip_frame": "tv"})
                       .split("window.__EXPLAINER = ", 1)[1].split(";</script>", 1)[0])
    assert saved["host"]["windows"][0]["frame"] == "tv"


def check_depth(xv) -> None:
    """The frames are shaded, the screen hole stays clear, and the bubble has a shadow."""
    for name in xv.PIP_DEVICES:
        im = Image.open(io.BytesIO(xv.device_png(name))).convert("RGBA")
        ox, oy, ow, oh = xv.PIP_FRAME_GEOM[name]["outer"]
        sx, sy, sw, sh = xv.PIP_FRAME_GEOM[name]["screen"]
        cx, cy = sx - ox + sw // 2, sy - oy + sh // 2
        assert im.getpixel((cx, cy))[3] == 0, name
        assert im.getpixel((cx, sy - oy + 4))[3] > 0, name  # glass sheen at the top of the screen
    monitor = Image.open(io.BytesIO(xv.device_png("monitor"))).convert("RGBA")
    lit, side = monitor.getpixel((272, 8)), monitor.getpixel((530, 40))
    assert lit[3] == 255 and side[3] == 255
    assert sum(lit[:3]) > sum(side[:3]) + 40
    tv = Image.open(io.BytesIO(xv.device_png("tv"))).convert("RGBA")
    foot_top, foot_front = tv.getpixel((160, 290)), tv.getpixel((160, 302))
    assert sum(foot_top[:3]) > sum(foot_front[:3]) + 40
    bubble = Image.open(io.BytesIO(xv.bubble_png("AI stocks lost about two trillion")[0])).convert("RGBA")
    assert near(bubble.getpixel((410, 40)), PAPER)
    assert bubble.getpixel((430, 165))[3] > 20  # contact shadow, off the paper
    assert sum(bubble.getpixel((200, 168))[:3]) < sum(PAPER) - 30  # the bubble's thicker underside


def check_stills(xv) -> None:
    monitor = Image.open(io.BytesIO(xv.look_still("monitor"))).convert("RGB")
    assert near(monitor.getpixel((1568, 832)), GOLD)
    assert sum(monitor.getpixel((1568, 702))[:3]) > sum(monitor.getpixel((1826, 734))[:3]) + 40
    plain = Image.open(io.BytesIO(xv.look_still("plain"))).convert("RGB")
    assert near(plain.getpixel((1568, 822)), GOLD)
    both = Image.open(io.BytesIO(xv.look_still("both"))).convert("RGB")
    assert near(both.getpixel((1568, 832)), GOLD)
    assert near(both.getpixel((458, 888)), PAPER)
    # The sample card is raised: its face is lighter than the hard shadow beside it.
    assert sum(both.getpixel((400, 400))[:3]) > sum(both.getpixel((1008, 400))[:3])
    committed = SAMPLES / "frame_monitor.png"
    before = SAMPLES / "before" / "frame_monitor.png"
    assert committed.is_file() and before.is_file()
    assert committed.read_bytes() != before.read_bytes()
    saved = Image.open(committed).convert("RGB")
    assert sum(saved.getpixel((1568, 702))[:3]) > sum(Image.open(before).convert("RGB").getpixel((1568, 702))[:3]) + 20
    runtime = SAMPLES / "runtime_monitor_and_bubble.png"
    assert runtime.is_file()
    shot = Image.open(runtime).convert("RGB")
    assert near(shot.getpixel((1568, 832)), GOLD)
    assert near(shot.getpixel((458, 888)), PAPER)


def check_runtime(xv) -> None:
    try:
        import websockets  # noqa: F401
    except ImportError:
        print("skip  Chrome still: websockets is not installed")
        return
    if not xv.find_chrome():
        print("skip  Chrome still: Chrome is not installed")
        return
    sentence = "Markets moved by more than anyone expected today and the index fund paid for the drop".split()
    words, t = [], 0.0
    for _ in range(6):
        for word in sentence:
            words.append({"text": word, "start": round(t, 3), "end": round(t + 0.28, 3)})
            t += 0.32
    timeline = xv.Timeline(words, t + 2)
    raw = ('<section id="s01" data-at="Markets moved by more" data-kind="slide" data-host="pip">'
           '<h1 class="h1">Markets moved</h1>'
           '<div class="card" style="position:absolute; left:160px; top:280px; width:780px; height:220px;">'
           '<div class="h3">AI stocks</div></div></section>')
    comp = xv.compile_composition(raw, timeline, duration=t + 2, plan={"slides": [], "sections": []},
                                  logos={}, values={}, logo_choices={}, host_on=True)
    html = xv.page_html(comp, mode="render", host={"focus": 0.45}, pip_frame="monitor", bubble="often")
    page = Path(tempfile.mkdtemp(prefix="xv-look-")) / "page.html"
    page.write_text(html, encoding="utf-8")

    async def shoot():
        exe, headless_new = xv.find_chrome()
        async with xv._Chrome(exe, headless_new) as ch:
            await ch.open(page, 1, transparent=True)
            return await ch.frame(comp["slides"][0]["t0"] + 1.5)

    im = Image.open(io.BytesIO(asyncio.run(shoot()))).convert("RGBA")
    sx, sy, sw, sh = xv.PIP_FRAME_GEOM["monitor"]["screen"]
    assert im.getpixel((sx + sw // 2, sy + sh // 2))[3] == 0
    assert im.getpixel((sx + 30, sy + 6))[3] > 0  # the glass sheen, not a fog over the face
    lit, wall = im.getpixel((1568, 702)), im.getpixel((1826, 734))
    assert lit[3] == 255 and wall[3] == 255 and sum(lit[:3]) > sum(wall[:3]) + 40
    assert near(im.getpixel((458, 888)), PAPER) and im.getpixel((458, 888))[3] == 255
    # The card's hard offset sits just outside its box and is darker than the empty frame.
    assert sum(im.getpixel((700, 400))[:3]) > sum(im.getpixel((946, 400))[:3])


def check_ui(app: str) -> None:
    html = (ROOT / app / "templates" / "index.html").read_text(encoding="utf-8")
    frame = html.split('id="xvPipFrame"', 1)[1].split("</select>", 1)[0]
    bubble = html.split('id="xvBubble"', 1)[1].split("</select>", 1)[0]
    assert 'value="mix" selected' in frame, app
    assert 'value="off"' in frame and 'value="tv"' in frame
    assert 'value="some" selected' in bubble, app
    assert 'value="often"' in bubble and 'value="off"' in bubble
    assert "pip_frame: pipFrame" in html
    assert "bubble: bubble" in html
    assert "xvLook(\\'pip_frame\\'" in html and "xvLook(\\'bubble\\'" in html
    assert "s.pip_frame, s.bubble" in html
    js = (ROOT / app / "static" / "explainer" / "runtime.js").read_text(encoding="utf-8")
    assert "placeFrame" in js and "placeAside" in js
    assert "name === 'pip' && frame" in js
    css = (ROOT / app / "static" / "explainer" / "design.css").read_text(encoding="utf-8")
    assert "box-shadow: 8px 10px 0 rgba(0, 0, 0, 0.38)" in css
    assert "border-bottom: 6px solid #070b12" in css
    gui = (ROOT / app / "web_gui.py").read_text(encoding="utf-8")
    assert 'pip_frame = _xv.pip_frame_key(data.get("pip_frame"))' in gui
    assert 'bubble = _xv.bubble_mode_key(data.get("bubble"))' in gui
    assert 'data.get("pip_frame") not in _xv.PIP_FRAME_MODES' in gui
    assert 'data.get("bubble") not in _xv.BUBBLE_MODES' in gui
    assert "pip_frame=frame, bubble=bubble" in gui


def check_copies(local, container) -> None:
    assert local.PIP_FRAME_GEOM == container.PIP_FRAME_GEOM
    assert local.PIP_FRAME_DEFAULT == container.PIP_FRAME_DEFAULT
    assert local.BUBBLE_DEFAULT == container.BUBBLE_DEFAULT
    assert local.ASIDE_AT == container.ASIDE_AT
    slides = [{"id": "s01", "kind": "slide", "host": "pip", "sections": [], "t0": 0, "t1": 12,
               "spoken": "Markets moved by more than anyone expected today.", "idea": "A chart of the drop."}]
    assert local.aside_cues(slides, "some") == container.aside_cues(slides, "some")
    windows = [{"t0": i, "t1": i + 1, "layout": "pip"} for i in range(4)]
    assert local.framed_windows(windows, "mix") == container.framed_windows(windows, "mix")
    assert local.device_png("monitor") == container.device_png("monitor")
    assert local.bubble_png("Markets moved today")[0] == container.bubble_png("Markets moved today")[0]


def main() -> None:
    local = load("explainer_look_v3", APPS[0])
    container = load("explainer_look_v3_container", APPS[1])
    for xv in (local, container):
        check_modes(xv)
        check_geometry(xv)
        check_bubble_text(xv)
        check_page(xv)
        check_depth(xv)
        check_stills(xv)
    check_copies(local, container)
    for app in APPS:
        check_ui(app)
    check_runtime(local)
    print("PASS  corner frames cycle on about half of pip windows; the guide bubble is optional and stays clear")


if __name__ == "__main__":
    main()
