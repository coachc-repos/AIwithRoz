"""Board looks and the two-minute look test.

No Claude and no network. Chrome is used for a short smoke render when it
is installed. The look-test route is exercised with the renderer replaced
by a tiny file, so the suite does not encode two minutes of video.

    python scriptcraft-app-v3/tests/test_explainer_styles.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPS = ("scriptcraft-app-v3", "scriptcraft-app-v3-container")
SAMPLES = ROOT / "scriptcraft-app-v3" / "tests" / "samples" / "styles"


def load(name: str, app: str):
    path = ROOT / app / "explainer_video.py"
    spec = importlib.util.spec_from_file_location(name, path)
    # The app imports explainer_styles from its own directory.
    sys.path.insert(0, str(ROOT / app))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    styles_name = name + "_styles"
    sp = importlib.util.spec_from_file_location(styles_name, ROOT / app / "explainer_styles.py")
    styles = importlib.util.module_from_spec(sp)
    sys.modules[styles_name] = styles
    sp.loader.exec_module(styles)
    mod._styles = styles
    return mod


def test_look_defaults_to_waves_and_unknown_is_ignored():
    for app in APPS:
        xv = load("styles_" + app.replace("-", "_"), app)
        st = xv._styles
        assert st.FILM_LOOK_DEFAULT == "waves"
        assert st.film_look_key(None, None) == "waves"
        assert st.film_look_key("nope", None) == "waves"
        assert st.film_look_key("whiteboard", "waves") == "whiteboard"
        assert st.film_look_key(None, "chalkboard") == "chalkboard"
        assert xv.film_look_key(None, None) == "waves"


def test_word_strokes_finish_on_the_spoken_word():
    xv = load("styles_sync", APPS[0])
    st = xv._styles
    scheduled = st.schedule_word("question", 1.20, 1.70)
    times = [pair for item in scheduled for pair in item["times"]]
    assert times, "a word with letters has strokes"
    assert all(1.20 - 1e-6 <= a <= b <= 1.70 + 1e-6 for a, b in times)
    assert abs(times[-1][1] - 1.70) < 1e-6
    assert st.stroke_progress(1.20, 1.20, 1.70) == 0.0
    assert st.stroke_progress(1.70, 1.20, 1.70) == 1.0
    # Slow at the start: a quarter of the way through the clock is less than a quarter drawn.
    assert st.stroke_progress(1.20 + 0.125, 1.20, 1.70) < 0.25
    lesson = st.demo_lesson()
    film = st.film_payload(lesson["compiled"], lesson["words"], "whiteboard")
    # The narration word "token" is fully drawn when it is spoken.
    spoken = next(w for w in lesson["words"] if w["text"].lower() == "token")
    strokes = []
    for letter in film["letters"]:
        for stroke in letter["strokes"]:
            if spoken["start"] - 0.02 <= stroke["t0"] <= spoken["end"] + 0.02:
                strokes.append(stroke)
    assert strokes
    assert max(s["t1"] for s in strokes) <= spoken["end"] + 0.02
    assert abs(max(s["t1"] for s in strokes) - spoken["end"]) < 0.05
    phone = next(op for op in film["ops"] if op["op"] == "phone")
    assert abs(phone["h"] / phone["w"] - st.PHONE_RATIO) < 0.02


def test_camera_travels_and_pulls_back_and_manual_chips_stay():
    xv = load("styles_cam", APPS[0])
    st = xv._styles
    lesson = st.demo_lesson()
    film = st.film_payload(lesson["compiled"], lesson["words"], "whiteboard")
    early = st.camera_at(2.0, film["camera"])
    mid = st.camera_at(12.0, film["camera"])
    end = st.camera_at(19.8, film["camera"])
    assert abs(early["x"] - mid["x"]) > 50
    assert end["z"] < early["z"]
    chalk = st.film_payload(lesson["compiled"], lesson["words"], "chalkboard")
    assert chalk["ink"]["chalk"] and not chalk["ink"]["pen"]
    marker = st.film_payload(lesson["compiled"], lesson["words"], "marker")
    assert marker["ink"]["peel"] and not marker["ink"]["pullback"]
    note = st.film_payload(lesson["compiled"], lesson["words"], "sketchnote")
    assert note["ink"]["dots"] and note["ink"]["pullback"]
    sample = st.sample_lesson()["compiled"]["slides"]
    fx = st.page_fx(sample, "whiteboard")
    assert any(item["manual"] and item["style"] == "pixel" for item in fx)
    assert all(item["style"] != "glitch" for item in fx)
    waves = st.page_fx(sample, "waves")
    assert any(item["style"] == "glitch" for item in waves)
    page = xv.page_html(lesson["compiled"], mode="render", bubble="off", words=lesson["words"])
    assert "film-board" not in page.split("<body", 1)[1][:120]
    board = xv.page_html(lesson["compiled"], mode="render", bubble="off", film_look="whiteboard",
                         words=lesson["words"])
    assert "film-board" in board and "XVBoard" in board
    assert board.split('<div id="slides">', 1)[1].split("</div><div id=\"hud\">", 1)[0] == \
        page.split('<div id="slides">', 1)[1].split("</div><div id=\"hud\">", 1)[0]


def test_sample_window_includes_hook_intro_and_the_other_pieces():
    xv = load("styles_span", APPS[0])
    st = xv._styles
    lesson = st.sample_lesson()
    span = st.look_test_span(lesson["compiled"], clips=lesson["clips"], articles=lesson["articles"])
    assert 110 <= span["seconds"] <= 130
    for name in ("hook", "intro", "presenter", "clip", "article", "transition"):
        assert span["features"][name], name


def test_chart_labels_stay_inside_their_slots():
    xv = load("styles_labels", APPS[0])
    st = xv._styles
    film = st.film_payload(st.demo_lesson()["compiled"], st.demo_lesson()["words"], "whiteboard")
    chart = next(op for op in film["ops"] if op["op"] == "chart")
    layout = chart["labelLayout"]
    assert st.labels_clear_of_bars(layout)
    assert [item["text"] for item in layout] == ["a", "the", "on", "mat"]
    # The same layout is what the canvas draws.
    assert all(item["label"]["w"] < item["slot"]["w"] for item in layout)


def test_camera_keeps_a_margin_on_the_holds():
    xv = load("styles_margin", APPS[0])
    st = xv._styles
    lesson = st.demo_lesson()
    film = st.film_payload(lesson["compiled"], lesson["words"], "whiteboard")
    for t in (1.0, 4.0, 7.2, 9.0, 12.0, 15.0, 19.6):
        cam = st.camera_at(t, film["camera"])
        assert st.text_fits_frame(film["ops"], cam), t
        drawn = st.texts_to_draw(film["ops"], cam)
        assert len(drawn) >= 2, t
    # Travel can pass a cluster off the edge. Anything still painted stays inside the margin.
    for step in range(0, 81):
        cam = st.camera_at(step * 0.25, film["camera"])
        for box in st.texts_to_draw(film["ops"], cam):
            assert box["x"] >= 1920 * st.FRAME_MARGIN - 1
            assert box["y"] >= 1080 * st.FRAME_MARGIN - 1
            assert box["x"] + box["w"] <= 1920 * (1 - st.FRAME_MARGIN) + 1
            assert box["y"] + box["h"] <= 1080 * (1 - st.FRAME_MARGIN) + 1
    assert xv.film_look_key("clay", "waves") == "waves"
    assert "clay" not in xv.FILM_LOOKS
    for key in ("tilt", "island", "tabletop", "popup"):
        assert key in xv.FILM_LOOKS
        assert xv.film_look_key(key, "waves") == key
    three = st.film_payload(lesson["compiled"], lesson["words"], "island")
    assert three["mode"] == "3d"
    assert three["ideas"] and three["ideas"][0]["title"]


def test_copies_match():
    local = (ROOT / APPS[0] / "static" / "explainer" / "board.js").read_bytes()
    other = (ROOT / APPS[1] / "static" / "explainer" / "board.js").read_bytes()
    assert local == other
    assert (ROOT / APPS[0] / "explainer_styles.py").read_bytes() == (ROOT / APPS[1] / "explainer_styles.py").read_bytes()
    assert (ROOT / APPS[0] / "static" / "explainer" / "scene3d.js").read_bytes() == (
        ROOT / APPS[1] / "static" / "explainer" / "scene3d.js").read_bytes()


def test_committed_samples():
    demo = SAMPLES / "whiteboard_demo.mp4"
    sheet = SAMPLES / "styles_sheet.png"
    picker = SAMPLES / "picker.png"
    player = SAMPLES / "picker_player.png"
    tiles = SAMPLES / "whiteboard_tiles.png"
    three = SAMPLES / "3d_tiles.png"
    compared = SAMPLES / "3d_color_before_after.png"
    demos = [demo] + [SAMPLES / f"{name}_demo.mp4" for name in ("tilt", "island", "tabletop", "popup")]
    for path in (sheet, picker, player, tiles, three, compared, *demos):
        assert path.is_file() and path.stat().st_size > 1000, path
    for path in demos:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, check=True)
        dur = float(json.loads(probe.stdout)["format"]["duration"])
        assert 16 <= dur <= 24, (path.name, dur)


def test_render_smoke_and_presenter_hole():
    xv = load("styles_smoke", APPS[0])
    if not xv.find_chrome():
        print("skip  Chrome smoke: Chrome is not installed")
        return
    try:
        import websockets  # noqa: F401
    except ImportError:
        print("skip  Chrome smoke: websockets is not installed")
        return
    import asyncio
    st = xv._styles
    lesson = st.demo_lesson()

    async def run():
        async with xv._Chrome(*xv.find_chrome()) as ch:
            counts = {}
            varied = {}
            for look in ("tilt", "island", "tabletop", "popup"):
                page = Path(tempfile.mkdtemp()) / f"{look}.html"
                page.write_text(xv.page_html(lesson["compiled"], mode="render", bubble="off",
                                            film_look=look, words=lesson["words"]), encoding="utf-8")
                await ch.open(page, 0.5, transparent=False)
                png = await ch.frame(6.0)
                varied[look] = _kinds(png)
            for look in ("whiteboard", "chalkboard", "sketchnote", "marker"):
                page = Path(tempfile.mkdtemp()) / f"{look}.html"
                page.write_text(xv.page_html(lesson["compiled"], mode="render", bubble="off",
                                            film_look=look, words=lesson["words"]), encoding="utf-8")
                await ch.open(page, 0.5, transparent=False)
                early = await ch.frame(0.25)
                later = await ch.frame(4.0)
                counts[look] = (_ink(early, look), _ink(later, look))
            comp = dict(lesson["compiled"])
            comp["host_on"] = True
            comp["html"] = comp["html"].replace('id="d2"', 'id="d2" data-host="pip"', 1)
            host_page = Path(tempfile.mkdtemp()) / "host.html"
            host_page.write_text(xv.page_html(comp, mode="render", bubble="off", film_look="whiteboard",
                                             words=lesson["words"], host={"focus": 0.45}, pip_frame="off"),
                                 encoding="utf-8")
            await ch.open(host_page, 1.0, transparent=True)
            await ch.frame(12.0)
            hole = await ch.evaluate("""(() => {
                const g = document.getElementById('bg').getContext('2d');
                const pip = [...g.getImageData(1568, 847, 1, 1).data];
                const board = [...g.getImageData(180, 160, 1, 1).data];
                return {pip: pip, board: board};
            })()""")
            return counts, hole, varied

    counts, hole, varied = asyncio.run(run())
    for look, (a, b) in counts.items():
        assert b > a + 20, (look, a, b)
    for look, n in varied.items():
        assert n > 12, (look, n)
    assert hole["pip"][3] == 0
    assert hole["board"][3] == 255


def _kinds(png: bytes) -> int:
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(png)).convert("RGB")
    px = im.load()
    colors = set()
    for y in range(0, im.size[1], 8):
        for x in range(0, im.size[0], 8):
            colors.add(px[x, y])
    return len(colors)


def _ink(png: bytes, look: str) -> int:
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(png)).convert("RGB")
    n = 0
    px = im.load()
    for y in range(0, im.size[1], 3):
        for x in range(0, im.size[0], 3):
            r, g, b = px[x, y]
            if look == "chalkboard":
                if r + g + b > 280:
                    n += 1
            else:
                if r + g + b < 420:
                    n += 1
    return n


def test_look_test_endpoint_does_not_touch_the_full_render(tmp_path=None):
    import web_gui
    xv = web_gui._xv
    folder_root = Path(tempfile.mkdtemp(prefix="xv-look-"))
    title = "Look test script"

    def fake_dir(script_title, create=True):
        path = folder_root / "run"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    written = {}

    def fake_render(project, page, out, start, end, status, cancel, **kwargs):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"look-test")
        written["span"] = (start, end)
        status(message="Drawing the test…", progress=0.5)
        return out

    web_gui._get_run_output_dir = fake_dir
    xv.render_look_clip = fake_render
    client = web_gui.app.test_client()
    res = client.post("/api/explainer/look-test", json={"title": title, "film_look": "not-a-look"})
    assert res.status_code == 400
    res = client.post("/api/explainer/look-test", json={"title": title, "film_look": "chalkboard", "seconds": 30})
    body = res.get_json()
    assert res.status_code == 200 and body["success"] and body["sample"], body
    pid = body["pid"]
    deadline = time.time() + 20
    state = body
    while time.time() < deadline:
        state = client.get(f"/api/explainer/{pid}?title={title}").get_json()
        if (state.get("job") or {}).get("status") in ("done", "error", "cancelled"):
            break
        time.sleep(0.05)
    job = state.get("job") or {}
    assert job.get("status") == "done", job
    assert state.get("approved") in (None, "")
    assert not state.get("renders")
    assert state.get("film_look") == "chalkboard"
    lt = state.get("look_test") or {}
    assert lt.get("path", "").endswith("look_test_chalkboard.mp4")
    assert (folder_root / "run" / "explainer" / pid / lt["path"]).is_file()
    features = (job.get("result") or {}).get("look_test", {}).get("features") or lt.get("features") or {}
    for name in ("hook", "presenter", "clip", "article", "transition"):
        assert features.get(name), features
    # A second look overwrites only its own preview file.
    res = client.post(f"/api/explainer/{pid}/look-test", json={"title": title, "film_look": "marker", "seconds": 20})
    assert res.status_code == 200
    deadline = time.time() + 20
    while time.time() < deadline:
        state = client.get(f"/api/explainer/{pid}?title={title}").get_json()
        if (state.get("job") or {}).get("status") in ("done", "error"):
            break
        time.sleep(0.05)
    assert state["job"]["status"] == "done", state.get("job")
    assert state["film_look"] == "marker"
    assert not state.get("renders")
    assert written["span"][1] - written["span"][0] > 5


def main() -> None:
    test_look_defaults_to_waves_and_unknown_is_ignored()
    test_word_strokes_finish_on_the_spoken_word()
    test_camera_travels_and_pulls_back_and_manual_chips_stay()
    test_sample_window_includes_hook_intro_and_the_other_pieces()
    test_copies_match()
    test_committed_samples()
    test_render_smoke_and_presenter_hole()
    test_look_test_endpoint_does_not_touch_the_full_render()
    print("PASS  board looks keep the wave default, write on the word, and the 2-min test stays off the full render")


if __name__ == "__main__":
    main()
