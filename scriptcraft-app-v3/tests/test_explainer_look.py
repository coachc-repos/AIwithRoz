"""Corner windows on a laptop or a computer screen, picked per slide or
per section, for the explainer. No guide character.

No HeyGen, Claude, or network calls. One optional local Chrome still checks
that the page punches the device screen.

    python scriptcraft-app-v3/tests/test_explainer_look.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

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


def near(px, rgb, tol=12) -> bool:
    return all(abs(int(px[i]) - rgb[i]) <= tol for i in range(3))


def cfg_of(html: str) -> dict:
    return json.loads(html.split("window.__EXPLAINER = ", 1)[1].split(";</script>", 1)[0])


def timeline_of(xv):
    sentence = "Markets moved by more than anyone expected today and the index fund paid for the drop".split()
    words, t = [], 0.0
    for _ in range(6):
        for word in sentence:
            words.append({"text": word, "start": round(t, 3), "end": round(t + 0.28, 3)})
            t += 0.32
    return xv.Timeline(words, t + 2), t + 2


def check_choices(xv) -> None:
    assert xv.PIP_DEVICES == ("laptop", "monitor")
    # No automatic framing and no guide character: nothing left to switch on.
    for gone in ("PIP_FRAME_MODES", "PIP_FRAME_DEFAULT", "pip_frame_key", "pip_device_for", "look_of",
                 "BUBBLE_MODES", "BUBBLE_DEFAULT", "bubble_mode_key", "bubble_png", "bubble_text",
                 "aside_cues", "_aside_payloads", "ASIDE_AT"):
        assert not hasattr(xv, gone), gone

    assert xv.split_layout("pip:laptop") == ("pip", "laptop")
    assert xv.split_layout("pip:monitor") == ("pip", "monitor")
    assert xv.split_layout("PIP:Laptop") == ("pip", "laptop")
    assert xv.split_layout("pip") == ("pip", "")
    assert xv.split_layout("pip:phone") == ("pip", "")
    assert xv.split_layout("full:laptop") == ("full", "")
    assert xv.split_layout("left") == ("left", "")
    assert xv.split_layout("nope") == ("", "")
    assert xv.split_layout("") == xv.split_layout(None) == ("", "")
    assert xv.layout_key("pip", "laptop") == "pip:laptop"
    assert xv.layout_key("pip", "") == "pip"
    assert xv.layout_key("full", "monitor") == "full"
    assert xv.layout_key("", "laptop") == ""

    # A corner window keeps the device picked for it, and only that.
    windows = [{"t0": 0, "t1": 1, "layout": "pip"}, {"t0": 1, "t1": 2, "layout": "pip", "frame": "laptop"},
               {"t0": 2, "t1": 3, "layout": "full", "frame": "monitor"}, {"t0": 3, "t1": 4, "layout": "pip", "frame": "tv"},
               {"t0": 4, "t1": 5, "layout": "pip", "frame": "monitor"}]
    framed = xv.framed_windows(windows)
    assert windows[0].get("frame") is None  # the input is not mutated
    assert [w["frame"] for w in framed] == ["", "laptop", "", "", "monitor"], framed
    assert xv._window_box({"layout": "pip", "frame": "monitor"}, 2) == {
        "x": 1242 * 2, "y": 628 * 2, "w": 576 * 2, "h": 324 * 2}
    assert xv._window_box({"layout": "pip", "frame": ""}, 1) == {"x": 1296, "y": 694, "w": 544, "h": 306}
    assert xv._window_box({"layout": "full", "frame": "monitor"}, 1)["w"] == 1920

    # Sections: "pip:laptop" from the page, or layout + frame as saved; the
    # page's combined key wins. Overlaps merge only on the same device.
    secs = xv.clean_sections([
        {"t0": 1, "t1": 3, "layout": "pip:laptop"},
        {"t0": 2, "t1": 4, "layout": "pip", "frame": "laptop"},
        {"t0": 5, "t1": 7, "layout": "pip", "frame": "monitor"},
        {"t0": 6, "t1": 8, "layout": "pip"},
        {"t0": 9, "t1": 10, "layout": "pip:laptop", "frame": "monitor"},
        {"t0": 11, "t1": 12, "layout": "full", "frame": "laptop"},
        {"t0": 13, "t1": 14, "layout": "pip:tv"},
    ], 60)
    assert secs == [
        {"t0": 1, "t1": 4, "layout": "pip", "frame": "laptop"},
        {"t0": 5, "t1": 7, "layout": "pip", "frame": "monitor"},
        {"t0": 6, "t1": 8, "layout": "pip"},
        {"t0": 9, "t1": 10, "layout": "pip", "frame": "laptop"},
        {"t0": 11, "t1": 12, "layout": "full"},
        {"t0": 13, "t1": 14, "layout": "pip"},
    ], secs


def check_geometry(xv) -> None:
    pip = xv.HOST_LAYOUTS["pip"]
    px, py, pw, ph = pip["x"], pip["y"], pip["w"], pip["h"]
    assert (px, py, pw, ph) == xv._PIP_BOX
    assert set(xv.PIP_FRAME_GEOM) == set(xv.PIP_DEVICES)
    # A device fills a larger corner than the plain window, holding it, inside the frame.
    ox, oy, ow, oh = xv.DEVICE_BOX
    assert ox < px and oy < py and ox + ow >= px + pw and oy + oh >= py + ph
    assert ox + ow <= 1920 - 60 and oy + oh <= 1080 - 56
    before = {"monitor": 432 * 244, "laptop": 400 * 224}   # the screens before they grew
    for name, geom in xv.PIP_FRAME_GEOM.items():
        outer, panel, screen = geom["outer"], geom["panel"], geom["screen"]
        assert outer == xv.DEVICE_BOX, name
        assert all(v % 2 == 0 for v in outer + screen), name
        sx, sy, sw, sh = screen
        x, y, w, h = panel
        assert ox <= x and oy <= y and x + w + xv.PANEL_EDGE <= ox + ow and y + h <= oy + oh, name
        assert x < sx and y < sy and sx + sw < x + w and sy + sh < y + h, name
        assert abs(sw / sh - 16 / 9) < 0.02, name
        assert sw * sh >= 1.7 * before[name], name
    # The monitor's panel (with its side wall) lines up with the plain window's right edge.
    mx, _, mw, _ = xv.PIP_FRAME_GEOM["monitor"]["panel"]
    assert abs(mx + mw + xv.PANEL_EDGE - (px + pw)) <= 2
    # Claude is told the device's larger area, in the rules and in a pick's brief.
    area = f"x {ox}-{ox + ow}, y {oy}-{oy + oh}"
    assert area in xv.SYSTEM_PROMPT
    assert area in xv._pick_note({"host": "pip:monitor"}) and area in xv._pick_note({"host": "pip:laptop"})
    assert area not in xv._pick_note({"host": "pip"})


def check_page(xv) -> None:
    timeline, duration = timeline_of(xv)
    raw = ('<section id="s01" data-at="Markets moved by more" data-kind="slide" data-host="pip" data-frame="laptop">'
           '<h1 class="h1">Markets moved</h1></section>'
           '<section id="s02" data-at="the index fund paid" data-kind="slide">'
           '<h1 class="h1">The fund</h1></section>'
           '<section id="s03" data-at="Markets moved by more" data-kind="slide" data-host="pip">'
           '<h1 class="h1">Plain corner</h1></section>'
           '<section id="s04" data-at="the index fund paid" data-kind="slide" data-host="pip" data-frame="monitor">'
           '<h1 class="h1">On a computer screen</h1></section>'
           '<section id="s05" data-at="Markets moved by more" data-kind="slide" data-host="pip">'
           '<h1 class="h1">Device kept in the plan</h1></section>'
           '<section id="s06" data-at="the index fund paid" data-kind="slide" data-host="full" data-frame="laptop">'
           '<h1 class="h1">Full frame</h1></section>')
    # s05 lost its data-frame (say Claude rewrote it); the plan still has the device.
    plan = {"slides": [{"id": "s05", "host": "pip", "frame": "laptop"}], "sections": []}
    comp = xv.compile_composition(raw, timeline, duration=duration, plan=plan,
                                  logos={}, values={}, logo_choices={}, host_on=True)
    assert [m["frame"] for m in comp["slides"]] == ["laptop", "", "", "monitor", "laptop", ""], comp["slides"]
    got = [(w["layout"], w.get("frame", "")) for w in comp["host_windows"]]
    # The plain corner (s03) and the computer screen (s04) touch, but stay two windows.
    assert got == [("pip", "laptop"), ("pip", ""), ("pip", "monitor"), ("pip", "laptop"), ("full", "")], got

    html = xv.page_html(comp, mode="render", host={"focus": 0.45})
    cfg = cfg_of(html)
    assert [w["frame"] for w in cfg["host"]["windows"]] == ["laptop", "", "monitor", "laptop", ""]
    assert set(cfg["host"]["frames"]) == {"laptop", "monitor"}
    assert cfg["host"]["frames"]["monitor"]["sx"] == 1242 and cfg["host"]["frames"]["monitor"]["w"] == 652
    assert cfg["host"]["frames"]["laptop"]["uri"].startswith("data:image/png;base64,")
    assert "asides" not in cfg
    assert 'data-host="pip" data-frame="laptop"' in html and 'data-host="full" data-frame' not in html

    # Nothing picked: every corner window is the plain corner, and no device image ships.
    plain = xv.compile_composition(raw.replace(' data-frame="laptop"', "").replace(' data-frame="monitor"', ""),
                                   timeline, duration=duration, plan={"slides": [], "sections": []},
                                   logos={}, values={}, logo_choices={}, host_on=True)
    off = cfg_of(xv.page_html(plain, mode="render", host={"focus": 0.45}))
    assert {w["frame"] for w in off["host"]["windows"]} == {""}
    assert off["host"]["frames"] == {}

    # A section on a laptop beats the slide's own plain corner there.
    placed = xv.compile_composition(raw, timeline, duration=duration, plan={"slides": [], "sections": []},
                                    logos={}, values={}, logo_choices={}, host_on=True,
                                    host_sections=[{"t0": 0.5, "t1": 3.0, "layout": "pip", "frame": "monitor"}])
    assert {"t0": 0.5, "t1": 3.0, "layout": "pip", "frame": "monitor"} in placed["host_sections"]
    assert any(w.get("frame") == "monitor" and w["t0"] <= 0.5 and w["t1"] >= 3.0 for w in placed["host_windows"])


def check_slide_choice(xv) -> None:
    """The 🧑‍💼 menu on a slide: a new version with data-host / data-frame, and the plan follows."""
    folder = Path(tempfile.mkdtemp(prefix="xv-look-proj-"))
    project = xv.open_project(folder)
    raw = ('<section id="s01" data-at="Markets moved" data-kind="slide"><h1 class="h1">One</h1></section>'
           '<section id="s02" data-at="index fund" data-kind="slide" data-host="pip"><h1 class="h1">Two</h1></section>')
    project.add_version(xv.split_sections(raw), "build", "First build")
    project.write("plan.json", json.dumps({"slides": [{"id": "s01", "host": "none"}, {"id": "s02", "host": "pip"}]}))

    def tag(sid):
        sec = next(s for s in xv.split_sections(project.composition()) if s["id"] == sid)
        return sec["raw"].split(">", 1)[0]

    def planned(sid):
        return next(s for s in project.plan()["slides"] if s["id"] == sid)

    assert xv.set_slide_host(project, "s01", "pip:laptop") == 2
    assert 'data-host="pip" data-frame="laptop"' in tag("s01")
    assert planned("s01") == {"id": "s01", "host": "pip", "frame": "laptop"}
    assert project.data["versions"][-1]["note"] == "s01: presenter pip:laptop"
    xv.set_slide_host(project, "s01", "pip:monitor")
    assert tag("s01").count("data-frame") == 1 and 'data-frame="monitor"' in tag("s01")
    assert planned("s01")["frame"] == "monitor"
    xv.set_slide_host(project, "s01", "pip")            # back to the plain corner
    assert "data-frame" not in tag("s01") and 'data-host="pip"' in tag("s01")
    assert "frame" not in planned("s01")
    xv.set_slide_host(project, "s02", "full:laptop")    # a device only goes with a corner window
    assert 'data-host="full"' in tag("s02") and "data-frame" not in tag("s02")
    xv.set_slide_host(project, "s02", "")
    assert "data-host" not in tag("s02") and planned("s02")["host"] == "none"

    # Each menu choice is the user's pick; a rewrite that changes it gets it put back.
    xv.set_slide_host(project, "s01", "pip:laptop")
    assert project.data["host_picks"] == {"s01": {"host": "pip:laptop", "at": "Markets moved"},
                                          "s02": {"host": "none", "at": "index fund"}}, project.data["host_picks"]
    claude = xv.split_sections(
        '<section id="s01" data-at="Markets moved" data-kind="slide"><h1 class="h1">One, moved</h1></section>'
        '<section id="s02" data-at="index fund" data-kind="slide" data-host="full"><h1 class="h1">Two</h1></section>'
        '<section id="s03" data-at="new beat" data-kind="slide" data-host="left"><h1 class="h1">Three</h1></section>')
    kept, fixed = xv.keep_host_picks(project, claude)
    assert fixed == ["s01", "s02"], fixed
    assert 'data-host="pip" data-frame="laptop"' in kept[0]["raw"] and "One, moved" in kept[0]["raw"]
    assert kept[0]["attrs"]["data-host"] == "pip" and kept[0]["attrs"]["data-frame"] == "laptop"
    assert "data-host" not in kept[1]["raw"]                       # the user took it off s02
    assert kept[2] is claude[2]                                     # no pick: Claude's choice stands
    assert claude[0]["attrs"].get("data-host") is None              # the input is not changed
    # A new plan: an id may name another moment, so a pick holds only on the same words.
    moved = xv.split_sections('<section id="s01" data-at="A different opening" data-kind="slide"><h1>X</h1></section>'
                              '<section id="s02" data-at="Index fund!" data-kind="slide"><h1>Y</h1></section>')
    _, fixed = xv.keep_host_picks(project, moved, same_slides=False)
    assert fixed == [], fixed                                       # s02 already has no presenter
    moved[1] = xv._host_tag(moved[1], "pip")
    _, fixed = xv.keep_host_picks(project, moved, same_slides=False)
    assert fixed == ["s02"], fixed
    # What Claude's revision brief says about a pick.
    note = xv._pick_note(project.data["host_picks"]["s01"])
    assert "placed the presenter on this slide (corner window on a laptop)" in note
    assert 'Keep data-host="pip" data-frame="laptop"' in note and "Never remove it" in note and 'data-kind="slide"' in note
    assert xv._pick_note({"host": "none"}).startswith("PRESENTER: the user took the presenter off")
    assert xv._pick_note(None) == ""


def _run(im, x, y, dx, dy, pred) -> int:
    n = 0
    while 0 <= x < im.size[0] and 0 <= y < im.size[1] and pred(im.getpixel((x, y))):
        n += 1
        x += dx
        y += dy
    return n


def _local(xv, box):
    ox, oy = xv.DEVICE_BOX[:2]
    return (box[0] - ox, box[1] - oy, box[2], box[3])


def check_depth(xv) -> None:
    """Panel edges stay a few pixels; thickness sits in the laptop base or the
    monitor stand. Light comes from the upper left, so the top edge is
    brighter than the right-hand wall. The glass reflection is faint, smooth
    and off the middle of the screen."""
    devices = {name: Image.open(io.BytesIO(xv.device_png(name))).convert("RGBA") for name in xv.PIP_DEVICES}
    for name, im in devices.items():
        assert im.size == tuple(xv.DEVICE_BOX[2:]), name
        x, y, w, h = _local(xv, xv.PIP_FRAME_GEOM[name]["panel"])
        sx, sy, sw, sh = _local(xv, xv.PIP_FRAME_GEOM[name]["screen"])
        # Cut fully through where the face is and in the lower right; a faint
        # reflection only toward the top left.
        assert im.getpixel((sx + sw // 2, sy + sh // 2))[3] == 0, name
        assert im.getpixel((sx + sw // 2, sy + int(sh * 0.42)))[3] == 0, name
        assert im.getpixel((sx + sw - 6, sy + sh - 6))[3] == 0, name
        corner = im.getpixel((sx + 6, sy + 4))[3]
        assert 0 < corner <= xv.SHEEN_PEAK <= 20, (name, corner)
        # Smooth: no bands. Along the top and down the left, the reflection
        # changes by at most one step of alpha from pixel to pixel.
        row = [im.getpixel((sx + i, sy + 4))[3] for i in range(4, sw - 4)]
        col = [im.getpixel((sx + 4, sy + j))[3] for j in range(4, sh - 4)]
        for line in (row, col):
            assert max(abs(a - b) for a, b in zip(line, line[1:])) <= 1, name
            assert line[0] >= line[-1], name
        # A thin panel: the side wall on the right is PANEL_EDGE pixels.
        assert _run(im, x + w, y + h // 2, 1, 0, lambda p: p[3] > 180) == xv.PANEL_EDGE, name
        assert sum(im.getpixel((x + w // 2, y))[:3]) > sum(im.getpixel((x + w, y + h // 2))[:3]) + 40, name
        # See-through around the device, and no hard edge where a shadow meets the image's edge.
        assert im.getpixel((2, 2))[3] == 0, name
        assert max(im.getpixel((i, im.height - 1))[3] for i in range(im.width)) <= 3, name
        assert max(im.getpixel((im.width - 1, j))[3] for j in range(im.height)) <= 3, name
    lap, mon = devices["laptop"], devices["monitor"]
    # The laptop's thickness is the base under the lid (deck and front edge).
    x, y, w, h = _local(xv, xv.PIP_FRAME_GEOM["laptop"]["panel"])
    base = _run(lap, x + 60, y + h + 2, 0, 1, lambda p: p[3] > 180)
    assert base >= xv.LAPTOP_BASE + 20, base
    assert lap.getpixel((x + w // 2, y + h + base + 6))[3] > 20  # a soft shadow under it
    # The monitor's is its stand; beside the stand, under the panel, is see-through.
    x, y, w, h = _local(xv, xv.PIP_FRAME_GEOM["monitor"]["panel"])
    stand = _run(mon, x + w // 2, y + h, 0, 1, lambda p: p[3] > 180)
    assert stand >= 4 * xv.PANEL_EDGE, stand
    assert mon.getpixel((x + 40, y + h + 4))[3] == 0


def _face(box):
    """Where the drawn stand-in's face is in a window (see _stand_in)."""
    x, y, w, h = box
    return (x + w // 2, y + int(h * 0.42))


def check_stills(xv) -> None:
    stills = {name: Image.open(io.BytesIO(xv.look_still(name))).convert("RGB") for name in ("plain", *xv.PIP_DEVICES)}
    for name in xv.PIP_DEVICES:
        still, geom = stills[name], xv.PIP_FRAME_GEOM[name]
        assert near(still.getpixel(_face(geom["screen"])), GOLD), name
        x, y, w, h = geom["panel"]
        assert sum(still.getpixel((x + w // 2, y))[:3]) > sum(still.getpixel((x + w, y + h // 2))[:3]) + 40, name
    assert near(stills["plain"].getpixel(_face(xv._PIP_BOX)), GOLD)
    monitor = stills["monitor"]
    # The lower left stays the slide: no guide character there.
    assert not near(monitor.getpixel((458, 888)), PAPER)
    # The sample card is raised: its face is lighter than the hard shadow beside it.
    assert sum(monitor.getpixel((400, 400))[:3]) > sum(monitor.getpixel((1008, 400))[:3])
    committed = {p.name for p in SAMPLES.glob("*.png")}
    assert committed == {"plain_corner.png", "frame_laptop.png", "frame_monitor.png", "runtime_monitor.png"}, committed
    # The corner is what these samples show; the headline text depends on the
    # machine's fonts, so only the corner has to match pixel for pixel.
    x, y, w, h = xv.DEVICE_BOX
    for name in ("plain", *xv.PIP_DEVICES):
        file = {"plain": "plain_corner.png"}.get(name, f"frame_{name}.png")
        saved = Image.open(SAMPLES / file).convert("RGB").crop((x, y, x + w, y + h))
        fresh = stills[name].crop((x, y, x + w, y + h))
        assert ImageChops.difference(saved, fresh).getbbox() is None, f"{file}: the corner changed; rerun with --write-samples"
    # before/ keeps the previous, smaller devices for comparison: the new
    # monitor reaches where the old one left the slide showing.
    x, y, w, h = xv.PIP_FRAME_GEOM["monitor"]["panel"]
    old = Image.open(SAMPLES / "before" / "frame_monitor.png").convert("RGB")
    assert near(old.getpixel((x + 2, y + h // 2)), (9, 12, 18), 4)
    assert not near(Image.open(SAMPLES / "frame_monitor.png").convert("RGB").getpixel((x + 2, y + h // 2)), (9, 12, 18), 40)
    shot = Image.open(SAMPLES / "runtime_monitor.png").convert("RGB")
    assert near(shot.getpixel(_face(xv.PIP_FRAME_GEOM["monitor"]["screen"])), GOLD)
    assert not near(shot.getpixel((458, 888)), PAPER)


def runtime_still(xv) -> "Image.Image | None":
    """A Chrome frame of a corner window on a computer screen, or None
    without Chrome. Transparent where the presenter goes."""
    try:
        import websockets  # noqa: F401
    except ImportError:
        print("skip  Chrome still: websockets is not installed")
        return None
    if not xv.find_chrome():
        print("skip  Chrome still: Chrome is not installed")
        return None
    timeline, duration = timeline_of(xv)
    raw = ('<section id="s01" data-at="Markets moved by more" data-kind="slide" data-host="pip" data-frame="monitor">'
           '<h1 class="h1">Markets moved</h1>'
           '<div class="card" style="position:absolute; left:160px; top:280px; width:780px; height:220px;">'
           '<div class="h3">AI stocks</div></div></section>')
    comp = xv.compile_composition(raw, timeline, duration=duration, plan={"slides": [], "sections": []},
                                  logos={}, values={}, logo_choices={}, host_on=True)
    page = Path(tempfile.mkdtemp(prefix="xv-look-")) / "page.html"
    page.write_text(xv.page_html(comp, mode="render", host={"focus": 0.45}), encoding="utf-8")

    async def shoot():
        exe, headless_new = xv.find_chrome()
        async with xv._Chrome(exe, headless_new) as ch:
            await ch.open(page, 1, transparent=True)
            return await ch.frame(comp["slides"][0]["t0"] + 1.5)

    return Image.open(io.BytesIO(asyncio.run(shoot()))).convert("RGBA")


def runtime_sample(xv, im: "Image.Image") -> bytes:
    """The Chrome frame over the drawn stand-in, as the committed sample."""
    sx, sy, sw, sh = xv.PIP_FRAME_GEOM["monitor"]["screen"]
    base = Image.new("RGBA", im.size, (0, 0, 0, 255))
    stand = xv._stand_in(sw, sh)
    base.paste(stand, (sx, sy), stand)
    base.alpha_composite(im)
    buf = io.BytesIO()
    base.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def check_runtime(xv) -> None:
    im = runtime_still(xv)
    if im is None:
        return
    sx, sy, sw, sh = xv.PIP_FRAME_GEOM["monitor"]["screen"]
    assert im.getpixel((sx + sw // 2, sy + sh // 2))[3] == 0
    assert im.getpixel((sx + 30, sy + 6))[3] > 0  # the glass sheen, not a fog over the face
    x, y, w, h = xv.PIP_FRAME_GEOM["monitor"]["panel"]
    lit, wall = im.getpixel((x + w // 2, y)), im.getpixel((x + w, y + h // 2))
    assert lit[3] == 255 and wall[3] == 255 and sum(lit[:3]) > sum(wall[:3]) + 40
    assert not near(im.getpixel((458, 888)), PAPER)  # no guide character lower left
    # The card's hard offset sits just outside its box and is darker than the empty frame.
    assert sum(im.getpixel((700, 400))[:3]) > sum(im.getpixel((946, 400))[:3])


def check_device_zone(xv) -> None:
    """The layout check (Fix flagged slides) treats a device corner's whole
    area as the presenter's: a note just outside the plain corner is fine on a
    plain corner, and flagged on a laptop or a computer screen."""
    try:
        import websockets  # noqa: F401
    except ImportError:
        print("skip  Chrome layout check: websockets is not installed")
        return
    if not xv.find_chrome():
        print("skip  Chrome layout check: Chrome is not installed")
        return
    timeline, duration = timeline_of(xv)
    ox, oy = xv.DEVICE_BOX[:2]
    px, py = xv._PIP_BOX[:2]
    note = (f'<div class="chip" style="position:absolute; left:{ox + 30}px; top:{oy + 14}px;">Source: BLS</div>')
    assert ox + 30 < px and oy + 14 + 60 < py   # inside the device's corner, outside the plain one

    def issues(frame: str) -> list:
        raw = ('<section id="s01" data-at="Markets moved by more" data-kind="slide" data-host="pip"'
               + (f' data-frame="{frame}"' if frame else "") + '><h1 class="h1">Markets moved</h1>' + note + "</section>")
        comp = xv.compile_composition(raw, timeline, duration=duration, plan={"slides": [], "sections": []},
                                      logos={}, values={}, logo_choices={}, host_on=True)
        page = Path(tempfile.mkdtemp(prefix="xv-zone-")) / "page.html"
        page.write_text(xv.page_html(comp, mode="render", host={"focus": 0.45}), encoding="utf-8")

        async def run():
            exe, headless_new = xv.find_chrome()
            async with xv._Chrome(exe, headless_new) as ch:
                await ch.open(page, 1)
                return await ch.evaluate("window.__check()")

        return [i for x in asyncio.run(run()) for i in x["issues"] if "covers the presenter" in i]

    assert issues("") == [], issues("")
    for frame in xv.PIP_DEVICES:
        assert issues(frame) == ["“Source: BLS” covers the presenter"], (frame, issues(frame))


def check_ui(app: str) -> None:
    html = (ROOT / app / "templates" / "index.html").read_text(encoding="utf-8")
    for gone in ('id="xvPipFrame"', 'id="xvBubble"', "pip_frame", "Guide character", "bubbleOpts"):
        assert gone not in html, (app, gone)
    assert "'pip:laptop': 'Corner on a laptop', 'pip:monitor': 'Corner on a computer screen'" in html
    assert "function _xvHostKey(layout, frame)" in html
    assert "_xvHostKey(m.host, m.frame) === k" in html                      # the slide's 🧑‍💼 menu
    assert "_xvLayoutOpts(_xvHostKey(x.layout, x.frame))" in html           # each placed section
    assert "list[i].layout = el.value; delete list[i].frame;" in html
    js = (ROOT / app / "static" / "explainer" / "runtime.js").read_text(encoding="utf-8")
    assert "placeFrame" in js and "name === 'pip' && frame" in js
    assert "presenterIssues(s, s.host, s.frame," in js and "presenterIssues(s, x.layout, x.frame," in js
    assert "aside" not in js.lower()
    css = (ROOT / app / "static" / "explainer" / "design.css").read_text(encoding="utf-8")
    assert "box-shadow: 8px 10px 0 rgba(0, 0, 0, 0.38)" in css
    assert "border-bottom: 6px solid #070b12" in css
    gui = (ROOT / app / "web_gui.py").read_text(encoding="utf-8")
    for gone in ("pip_frame", "bubble", "look_of"):
        assert gone not in gui, (app, gone)
    assert 'if layout and not _xv.split_layout(layout)[0]:' in gui


def check_copies(local, container) -> None:
    assert local.PIP_FRAME_GEOM == container.PIP_FRAME_GEOM
    assert local.PIP_DEVICES == container.PIP_DEVICES
    for key in ("pip:laptop", "pip:monitor", "pip", "full:laptop", "nope"):
        assert local.split_layout(key) == container.split_layout(key), key
    for name in local.PIP_DEVICES:
        assert local.device_png(name) == container.device_png(name), name


def check_clip_split(xv) -> None:
    """A clip framed in one half: the slide plays shrunk in the other half,
    both halves framed (render page: the clip's pane is black inside, for
    ffmpeg to fill). Full screen leaves the slide alone. Saves the frames to
    a temp folder for a look."""
    if not xv.find_chrome():
        print("skip  clip split: Chrome is not installed")
        return
    timeline, duration = timeline_of(xv)
    raw = ('<section id="s01" data-at="Markets moved by more" data-kind="slide">'
           '<h1 class="h1">Markets moved</h1>'
           '<div class="card" style="position:absolute; left:160px; top:280px; width:780px; height:220px;">'
           '<div class="h3">AI stocks</div></div></section>')
    comp = xv.compile_composition(raw, timeline, duration=duration, plan={"slides": [], "sections": []},
                                  logos={}, values={}, logo_choices={}, host_on=False)
    s0 = comp["slides"][0]
    panes = xv.clip_panes()
    out = Path(tempfile.mkdtemp(prefix="xv-split-"))
    got = {}
    for place in ("right", "left", "full", "left-small", "right-small", "center-medium"):
        clips = [{"id": "yc_1", "slide": "s01", "src": "", "audio": "mute", "seconds": 3, "t0": s0["t0"],
                  "t1": s0["t1"], "label": "", "place": place}]
        page = out / f"page_{place}.html"
        page.write_text(xv.page_html(comp, mode="render", clips=clips), encoding="utf-8")

        async def shoot(pg=page):
            exe, headless_new = xv.find_chrome()
            async with xv._Chrome(exe, headless_new) as ch:
                await ch.open(pg, 1)
                png = await ch.frame(s0["t0"] + 1.5)
                rect = await ch.evaluate("(function () { var r = document.querySelector('#s01 h1')"
                                         ".getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; })()")
                return png, rect
        png, rect = asyncio.run(shoot())
        im = Image.open(io.BytesIO(png)).convert("RGB")
        im.save(out / f"split_{place}.png")
        got[place] = (im, rect)

    def inside(rect, box):
        x, y, w, h = box
        return rect[0] >= x - 1 and rect[1] >= y - 1 and rect[2] <= x + w + 1 and rect[3] <= y + h + 1

    black = lambda px: sum(px) <= 6                                  # noqa: E731
    ring = lambda px: all(abs(a - b) <= 12 for a, b in zip(px, (0x3a, 0x48, 0x62)))   # noqa: E731
    for place, other in (("right", "left"), ("left", "right")):
        im, rect = got[place]
        C, S = panes[place], panes[other]
        assert inside(rect, S), (place, rect, S)                      # the slide's heading is in the open half
        assert rect[2] - rect[0] < 0.6 * (got["full"][1][2] - got["full"][1][0]), (place, rect)
        assert black(im.getpixel((C[0] + C[2] // 2, C[1] + C[3] // 2))), place
        edge_x = C[0] - 2 if place == "right" else C[0] + C[2] + 1
        assert ring(im.getpixel((edge_x, C[1] + C[3] // 2))), (place, im.getpixel((edge_x, C[1] + C[3] // 2)))
        assert ring(im.getpixel((S[0] - 2, S[1] + S[3] // 2))), place            # the slide's half is framed too
        assert not black(im.getpixel((S[0] + S[2] - 40, S[1] + S[3] - 40)))       # its backing is the deck's dark, not black
    im, rect = got["full"]
    R = panes["right"]
    assert not inside(rect, panes["left"]) and not black(im.getpixel((R[0] + R[2] // 2, R[1] + R[3] // 2)))
    assert not ring(im.getpixel((R[0] - 2, R[1] + R[3] // 2)))
    # A small window on one side: the slide plays shrunk in the larger pane beside it.
    for place in ("left-small", "right-small"):
        im, rect = got[place]
        C, S = panes[place], panes["slide"][place]
        assert C[2] < S[2] and inside(rect, S), (place, rect, S)
        assert black(im.getpixel((C[0] + C[2] // 2, C[1] + C[3] // 2))), place
        assert ring(im.getpixel((C[0] - 2, C[1] + C[3] // 2))) and ring(im.getpixel((S[0] - 2, S[1] + S[3] // 2))), place
    # In the middle: the slide stays where it was, dimmed around the framed clip.
    im, rect = got["center-medium"]
    C = panes["center-medium"]
    assert panes["slide"]["center-medium"] is None and abs(rect[0] - got["full"][1][0]) < 2, rect
    assert black(im.getpixel((C[0] + C[2] // 2, C[1] + C[3] // 2))) and ring(im.getpixel((C[0] - 2, C[1] + C[3] // 2)))
    def brightest(img, r):                                           # the heading's lit text
        return max(sum(img.getpixel((x, y))) for x in range(int(r[0]) + 1, int(r[2]) - 1, 6)
                   for y in range(int(r[1]) + 1, int(r[3]) - 1, 6))
    assert brightest(im, rect) < 0.5 * brightest(got["full"][0], got["full"][1]), "the slide is dimmed"

    # On a computer or a laptop in the corner: the device shows while the clip plays, the slide
    # stays full size, and the layout check flags a card under the device.
    raw2 = raw.replace("</section>", '<div class="card" style="position:absolute; left:1320px; top:700px; '
                                     'width:420px; height:200px;"><div class="h3">Corner card</div></div></section>')
    comp2 = xv.compile_composition(raw2, timeline, duration=duration, plan={"slides": [], "sections": []},
                                   logos={}, values={}, logo_choices={}, host_on=False)
    for device in ("monitor", "laptop"):
        clips = [{"id": "yc_1", "slide": "s01", "src": "", "audio": "mute", "seconds": 3, "t0": s0["t0"],
                  "t1": s0["t1"], "label": "", "place": device}]
        page = out / f"page_{device}.html"
        page.write_text(xv.page_html(comp2, mode="render", clips=clips), encoding="utf-8")

        async def shoot_dev(pg=page):
            exe, headless_new = xv.find_chrome()
            async with xv._Chrome(exe, headless_new) as ch:
                await ch.open(pg, 1)
                png = await ch.frame(s0["t0"] + 1.5)
                state = await ch.evaluate("(function () { var r = document.querySelector('#s01 h1').getBoundingClientRect();"
                                          " var on = Array.prototype.filter.call(document.querySelectorAll('img'), function (i) {"
                                          " return i.style.zIndex === '798' && i.style.display === 'block'; });"
                                          " return {rect: [r.left, r.top, r.right, r.bottom], shown: on.length,"
                                          " box: on.length ? [on[0].offsetLeft, on[0].offsetTop, on[0].offsetWidth, on[0].offsetHeight] : null,"
                                          " issues: window.__check()}; })()")
                after = await ch.evaluate(f"(function () {{ window.__seek({s0['t1'] + 1}); return Array.prototype.filter.call("
                                          "document.querySelectorAll('img'), function (i) { return i.style.zIndex === '798' && "
                                          "i.style.display === 'block'; }).length; })()")
                return png, state, after
        png, st, after = asyncio.run(shoot_dev())
        Image.open(io.BytesIO(png)).convert("RGB").save(out / f"split_{device}.png")
        assert st["shown"] == 1 and st["box"] == list(xv.DEVICE_BOX), (device, st)
        assert abs((st["rect"][2] - st["rect"][0]) - (got["full"][1][2] - got["full"][1][0])) < 2, (device, st["rect"])
        flags = [i for x in st["issues"] for i in x["issues"]]
        name = "laptop" if device == "laptop" else "computer screen"
        assert any(f"“Corner card” is under the clip’s {name}" in f and "keep x 1204–1856" in f for f in flags), flags
        assert after == 0, device                                    # gone once the clip's slide is over
    print(f"ok    clip split: slide shrunk into the open half, both halves framed; a clip on a computer or laptop shows the device in the corner and flags what is under it ({out})")


def main() -> None:
    local = load("explainer_look_v3", APPS[0])
    container = load("explainer_look_v3_container", APPS[1])
    if "--write-samples" in sys.argv:
        local.write_look_samples(SAMPLES)
        im = runtime_still(local)
        if im is not None:
            (SAMPLES / "runtime_monitor.png").write_bytes(runtime_sample(local, im))
        print(f"wrote samples to {SAMPLES}")
        return
    for xv in (local, container):
        check_choices(xv)
        check_geometry(xv)
        check_page(xv)
        check_slide_choice(xv)
        check_depth(xv)
        check_stills(xv)
    check_copies(local, container)
    for app in APPS:
        check_ui(app)
    check_runtime(local)
    check_device_zone(local)
    check_clip_split(local)
    print("PASS  corner windows go on a laptop or a computer screen only where picked (slide or section); no guide character")


if __name__ == "__main__":
    main()
