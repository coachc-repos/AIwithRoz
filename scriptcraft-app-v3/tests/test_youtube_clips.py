"""YouTube clips for the explainer: times, checks, save, and assignment.

No network, yt-dlp, or ffmpeg process. Download and cut commands are built
and handed to a fake runner.

    python scriptcraft-app-v3/tests/test_youtube_clips.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPS = ("scriptcraft-app-v3", "scriptcraft-app-v3-container")
URL = "https://www.youtube.com/watch?v=abcdefghijk"


def load(name: str, app: str):
    path = ROOT / app / "explainer_video.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def check_times(xv) -> None:
    assert xv.parse_timecode("90") == 90
    assert xv.parse_timecode("90.5") == 90.5
    assert xv.parse_timecode(" 1:30 ") == 90
    assert xv.parse_timecode("01:05.25") == 65.25
    assert xv.parse_timecode("1:02:03") == 3723
    assert xv.parse_timecode("01:02:03.5") == 3723.5
    assert xv.parse_timecode("90:00") == 5400
    for bad in ("", "abc", "1:60", "1:60:00", "-3", "1:2:3:4"):
        try:
            xv.parse_timecode(bad)
        except xv.YoutubeError:
            pass
        else:
            raise AssertionError(bad)
    assert xv.validate_clip_range(1, 4.5, 30) == (1, 4.5)
    for start, end, dur in ((5, 5, 30), (6, 2, 30), (-1, 3, 30), (0, 0.1, 30), (0, 31, 30)):
        try:
            xv.validate_clip_range(start, end, dur)
        except xv.YoutubeError as e:
            assert str(e)
        else:
            raise AssertionError((start, end, dur))
    assert "past the video" in _raises(xv, lambda: xv.validate_clip_range(0, 31, 30))
    assert "after the start" in _raises(xv, lambda: xv.validate_clip_range(4, 4, 30))

    # A period typed for the colon: "6.41" next to "6:37" is 6:41 (the reported In 6:37 / Out 6.41).
    r = xv.parse_clip_range
    assert r("6:37", "6.41", 840) == (397, 401) and r("6.37", "6:41", 840) == (397, 401)
    assert r("6.37", "6.41", 840) == (397, 401)              # as seconds they make no clip; as m:ss they do
    assert r("10.25", "20.50", 840) == (10.25, 20.5)          # real seconds stay seconds
    assert r("1:05.25", "70.50", 840) == (65.25, 70.5)        # m:ss would pass the video's end
    assert r(None, "6.41", 840, start=397.0, end=400.0) == (397, 401)
    assert r("6:40", None, 840, start=397.0, end=410.0) == (400, 410)
    err = _raises(xv, lambda: r("6.41", "6.37", 840))
    assert "after the start" in err and "In reads as 0:06 (6.41 s)" in err and "colon" in err, err
    err = _raises(xv, lambda: r("6:41", "6:37", 840))
    assert "In reads as 6:41, Out as 6:37." in err and "colon" not in err, err
    assert "past the video" in _raises(xv, lambda: r("13:59", "14.05", 840))


def _raises(xv, fn) -> str:
    try:
        fn()
    except xv.YoutubeError as e:
        return str(e)
    raise AssertionError("expected YoutubeError")


def check_urls_and_errors(xv) -> None:
    assert xv.youtube_url_problem("") == "Paste a YouTube URL."
    assert "youtube.com" in xv.youtube_url_problem("https://example.com/watch?v=abcdefghijk")
    assert xv.youtube_url_problem("https://youtu.be/short")
    assert xv.youtube_url_problem(URL) is None
    assert xv.youtube_url_problem("https://youtu.be/abcdefghijk") is None
    assert xv.youtube_url_problem("https://www.youtube.com/shorts/abcdefghijk") is None
    assert "private" in xv.classify_ytdlp_error("ERROR: Private video. Sign in if you've been granted access").lower()
    assert "age-restricted" in xv.classify_ytdlp_error("ERROR: Sign in to confirm your age. This video may be inappropriate")
    assert "not a bot" in xv.classify_ytdlp_error("ERROR: Sign in to confirm you're not a bot. Use --cookies-from-browser")
    assert "ffmpeg" in xv.classify_ytdlp_error("ERROR: You have requested merging of multiple formats but ffmpeg is not installed").lower()
    assert "YouTube link" in xv.classify_ytdlp_error("ERROR: Unsupported URL: https://example.com/v")
    assert "unavailable" in xv.classify_ytdlp_error("ERROR: Video unavailable").lower()
    real = xv.shutil.which
    xv.shutil.which = lambda name: None if name == "ffmpeg" else real(name)
    try:
        message = _raises(xv, xv.require_ffmpeg)
    finally:
        xv.shutil.which = real
    assert "ffmpeg is not installed" in message
    sw, sh, x, y = xv.fit_contain(1080, 1920, 1920, 1080)
    assert sh == 1080 and sw < 1920 and sw % 2 == 0 and x % 2 == 0 and x > 0
    assert xv.fit_contain(1920, 1080, 1920, 1080) == (1920, 1080, 0, 0)


def _runner(fail: str = ""):
    calls = []

    def runner(cmd, stream=False):
        calls.append(list(cmd))
        if "--dump-single-json" in cmd:
            if fail:
                return subprocess.CompletedProcess(cmd, 1, "", fail)
            body = json.dumps({"id": "abcdefghijk", "title": "CC demo", "duration": 20,
                               "width": 1920, "height": 1080, "availability": "public"})
            return subprocess.CompletedProcess(cmd, 0, body, "")
        dest = Path(cmd[cmd.index("-o") + 1].replace("%(ext)s", "mp4"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-mp4")
        return subprocess.CompletedProcess(cmd, 0, "[download] 100.0% of 1.00MiB\n", "")

    return calls, runner


def check_download_commands(xv) -> None:
    calls, runner = _runner()
    dest = Path(tempfile.mkdtemp()) / "yt_demo.mp4"
    info = xv.yt_download(URL, dest, runner=runner)
    assert info["title"] == "CC demo"
    assert info["seconds"] == 20
    assert dest.is_file()
    download = next(c for c in calls if "--merge-output-format" in c)
    assert "mp4" in download
    assert any("height<=1080" in part for part in download)
    assert "--no-playlist" in download
    joined = " ".join(download)
    assert "-f" in download and "bv*" in joined
    assert _raises(xv, lambda: xv.yt_download("https://example.com/nope", dest, runner=runner))
    _calls, bad = _runner("ERROR: Private video. Sign in if you've been granted access")
    assert "private" in _raises(xv, lambda: xv.yt_download(URL, dest, runner=bad)).lower()
    _calls, age = _runner("ERROR: Sign in to confirm your age")
    assert "age-restricted" in _raises(xv, lambda: xv.yt_download(URL, dest, runner=age))


def _cut_runner(calls):
    def run(cmd):
        calls.append(list(cmd))
        Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[-1]).write_bytes(b"clip")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return run


def _project(xv, seconds=30.0):
    folder = Path(tempfile.mkdtemp())
    (folder / "project.json").write_text(json.dumps({
        "title": "Old explainer", "audio_seconds": seconds, "current": 0}), encoding="utf-8")
    project = xv.Project(folder)
    assert "youtube" not in project.data
    assert xv.yt_public(project)["clips"] == []
    assert "youtube" not in json.loads((folder / "project.json").read_text(encoding="utf-8"))
    media = folder / "working" / "media"
    media.mkdir(parents=True)
    (media / "yt_demo.mp4").write_bytes(b"source")
    project.data["youtube"] = {"videos": [{
        "id": "yt_demo", "url": URL, "title": "CC demo", "file": "working/media/yt_demo.mp4",
        "seconds": seconds, "width": 1280, "height": 720, "has_audio": True, "status": "ready"}],
        "clips": []}
    project.save()
    return project


def check_persist_and_assign(xv) -> None:
    project = _project(xv, seconds=120)
    calls = []
    first = xv.yt_add_clip(project, "yt_demo", "1:00", "1:10.5", label="  opening  ", run=_cut_runner(calls))
    assert first["audio"] == "mute"
    assert first["label"] == "opening"
    assert first["start"] == 60 and first["end"] == 70.5
    assert first["slide"] == ""
    cut = calls[0]
    assert cut.index("-i") < cut.index("-ss")
    assert "libx264" in cut
    assert "-c:a" in cut
    assert _raises(xv, lambda: xv.yt_add_clip(project, "yt_demo", "2:00", "1:00", run=_cut_runner([])))
    assert len(xv.load_youtube(project.data)["clips"]) == 1
    second = xv.yt_add_clip(project, "yt_demo", 12, 18, run=_cut_runner([]))
    xv.yt_assign(project, first["id"], "s01", known={"s01", "s02"})
    xv.yt_assign(project, second["id"], "s01", known={"s01", "s02"})
    saved = xv.load_youtube(project.data)
    by_id = {c["id"]: c for c in saved["clips"]}
    assert by_id[first["id"]]["slide"] == ""
    assert by_id[second["id"]]["slide"] == "s01"
    assert "not in this version" in _raises(xv, lambda: xv.yt_assign(project, first["id"], "missing", known={"s01"}))
    xv.yt_set_audio(project, second["id"], "mix")
    assert _raises(xv, lambda: xv.yt_set_audio(project, second["id"], "loud"))
    # Where it plays: framed on the right by default, left, or full screen.
    assert first["place"] == "right" and second["place"] == "right"
    xv.yt_set_place(project, second["id"], "left")
    assert "in a computer or in a laptop" in _raises(xv, lambda: xv.yt_set_place(project, second["id"], "top"))
    assert xv.yt_set_place(project, first["id"], "laptop")["place"] == "laptop"
    for place in ("left-small", "right-small", "center-large", "center-medium"):
        assert xv.yt_set_place(project, first["id"], place)["place"] == place
    panes = xv.clip_panes()
    assert set(xv.YT_FRAMED) <= set(panes) and set(panes["slide"]) == set(xv.YT_FRAMED)
    for place in xv.YT_FRAMED:                    # every framed pane is 16:9 and on the stage
        x, y, w, h = panes[place]
        assert abs(w / h - 16 / 9) < 0.01 and x >= 0 and y >= 0 and x + w <= 1920 and y + h <= 1080, place
    xv.yt_set_place(project, first["id"], "right")
    assert xv.clip_place({}) == "right" and xv.clip_place({"place": "bogus"}) == "right" and xv.clip_place({"place": "full"}) == "full"
    again = xv.Project(project.dir)
    kept = {c["id"]: c for c in xv.load_youtube(again.data)["clips"]}
    assert kept[second["id"]]["audio"] == "mix"
    assert kept[second["id"]]["slide"] == "s01"
    assert kept[first["id"]]["audio"] == "mute"
    assert kept[second["id"]]["place"] == "left"
    public = xv.yt_public(again)
    assert {c["id"]: c["place"] for c in public["clips"]} == {first["id"]: "right", second["id"]: "left"}
    assert public["timing"] == xv.CLIP_TIMING_NOTE
    assert any(c["id"] == second["id"] and c["slide"] == "s01" for c in public["clips"])
    xv.yt_assign(project, second["id"], "", known={"s01", "s02"})
    assert xv.load_youtube(project.data)["clips"]
    xv.yt_delete_clip(project, first["id"])
    left = xv.load_youtube(xv.Project(project.dir).data)["clips"]
    assert [c["id"] for c in left] == [second["id"]]
    assert not (project.dir / first["file"]).exists()


def check_panes(xv) -> None:
    """Two 16:9 panes side by side, even numbers, inside the stage, mirrored."""
    panes = xv.clip_panes()
    L, R = panes["left"], panes["right"]
    assert L[1:] == R[1:] and all(v % 2 == 0 for v in L + R), panes
    assert L[0] == xv.CLIP_PANE_MARGIN and R[0] + R[2] == xv.STAGE_W - xv.CLIP_PANE_MARGIN
    assert R[0] - (L[0] + L[2]) == xv.CLIP_PANE_GAP and abs(L[2] / L[3] - 16 / 9) < 0.01
    assert L[1] + L[3] / 2 == xv.STAGE_H / 2 and L[2] > 0.45 * xv.STAGE_W
    # Framed on the right at 4K (x2): fitted inside the pane, rounded, laid at the pane.
    framed = {"path": "c.mp4", "seconds": 4, "show": 4, "offset": 2, "src_skip": 0, "w": 1280, "h": 720,
              "place": "right", "pane": R}
    g = xv.build_overlay_cmd(Path("base.mp4"), Path("out.mp4"), [framed], 3840, 2160)
    g = g[g.index("-filter_complex") + 1]
    assert f"pad={R[2] * 2}:{R[3] * 2}:" in g and f"overlay={R[0] * 2}:{R[1] * 2}:" in g, g
    assert "alphamerge" in g and "geq=lum=" in g and "format=yuva420p" in g and f"clip({xv.CLIP_PANE_RADIUS * 2}+0.5-" in g
    # A 4:3 recording is letterboxed inside the pane, not stretched.
    sw, sh, x, y = xv.fit_contain(1024, 768, R[2], R[3])
    assert sh == R[3] and sw < R[2] and x > 0 and y == 0
    # On a device's screen: fitted into the screen, its own corner radius.
    sx, sy, sw, sh = xv.PIP_FRAME_GEOM["laptop"]["screen"]
    dev = dict(framed, place="laptop", pane=[sx, sy, sw, sh], radius=xv.SCREEN_RADIUS)
    g3 = xv.build_overlay_cmd(Path("base.mp4"), Path("out.mp4"), [dev], 3840, 2160)
    g3 = g3[g3.index("-filter_complex") + 1]
    assert f"pad={sw * 2}:{sh * 2}:" in g3 and f"overlay={sx * 2}:{sy * 2}:" in g3 and f"clip({xv.SCREEN_RADIUS * 2}+0.5-" in g3, g3
    full = dict(framed, place="full", pane=None)
    g2 = xv.build_overlay_cmd(Path("base.mp4"), Path("out.mp4"), [full], 1920, 1080)
    g2 = g2[g2.index("-filter_complex") + 1]
    assert "alphamerge" not in g2 and "overlay=0:0:" in g2 and "pad=1920:1080" in g2


def check_graphs(xv) -> None:
    short = {"path": "c.mp4", "seconds": 2, "show": 5, "offset": 1, "src_skip": 0, "w": 1920, "h": 1080}
    cmd = xv.build_overlay_cmd(Path("base.mp4"), Path("out.mp4"), [short], 1920, 1080)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "tpad=stop_mode=clone" in graph
    assert "scale=1920:1080" in graph
    assert "pad=1920:1080" in graph
    long = {"path": "c.mp4", "seconds": 8, "show": 3, "offset": 0, "src_skip": 0, "w": 1920, "h": 1080}
    graph2 = xv.build_overlay_cmd(Path("base.mp4"), Path("out.mp4"), [long], 1920, 1080)
    graph2 = graph2[graph2.index("-filter_complex") + 1]
    assert "tpad=stop_mode=clone" not in graph2
    assert "trim=duration=3.000" in graph2
    plain = xv.build_mux_cmd(Path("v.mp4"), Path("n.wav"), Path("o.mp4"), 0, 10, [])
    assert plain[plain.index("-map") + 1] == "0:v:0"
    assert "1:a:0" in plain
    assert "sidechaincompress" not in " ".join(plain)
    mix = {"path": "c.mp4", "audio": "mix", "offset": 1, "show": 3, "seconds": 3, "src_skip": 0}
    mixed = " ".join(xv.build_mux_cmd(Path("v.mp4"), Path("n.wav"), Path("o.mp4"), 4, 10, [mix]))
    assert "sidechaincompress" in mixed
    only = {"path": "c.mp4", "audio": "clip", "offset": 1, "show": 3, "seconds": 3, "src_skip": 0}
    replaced = " ".join(xv.build_mux_cmd(Path("v.mp4"), Path("n.wav"), Path("o.mp4"), 0, 10, [only]))
    assert "volume=0" in replaced
    assert "sidechaincompress" not in replaced
    muted = {"path": "c.mp4", "audio": "mute", "offset": 1, "show": 3, "seconds": 3, "src_skip": 0}
    same = xv.build_mux_cmd(Path("v.mp4"), Path("n.wav"), Path("o.mp4"), 0, 10, [muted])
    assert "sidechaincompress" not in " ".join(same)
    assert "1:a:0" in same


def check_page(xv) -> None:
    words, t = [], 0.0
    for word in "Markets moved by more than anyone expected today".split():
        words.append({"text": word, "start": round(t, 3), "end": round(t + 0.3, 3)})
        t += 0.4
    timeline = xv.Timeline(words, t + 2)
    raw = ('<section id="s01" data-at="Markets moved" data-kind="slide"><h1 class="h1">Markets</h1></section>')
    comp = xv.compile_composition(raw, timeline, duration=t + 2, plan={}, logos={}, values={}, logo_choices={})
    bare = json.loads(xv.page_html(comp).split("window.__EXPLAINER = ", 1)[1].split(";</script>", 1)[0])
    assert bare["clips"] == []
    html = xv.page_html(comp, clips=[{
        "id": "yc_1", "slide": "s01", "src": "/api/explainer/p/file?path=working/media/yc_1.mp4",
        "audio": "mute", "seconds": 4, "t0": 0, "t1": 5, "label": "Demo"}],
        media_origin="http://127.0.0.1:5000")
    cfg = json.loads(html.split("window.__EXPLAINER = ", 1)[1].split(";</script>", 1)[0])
    assert cfg["clips"][0]["audio"] == "mute"
    assert cfg["clips"][0]["slide"] == "s01"
    assert "media-src 'self' http://127.0.0.1:5000" in html
    assert "holds its last frame" in html
    assert "object-fit:contain" in html


def check_ui(app: str) -> None:
    html = (ROOT / app / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'data-pane="clips"' in html
    assert 'id="xvYtUrl"' in html
    assert "holds the last frame" in html
    assert "xvClipAssign" in html
    assert "window._xv = _xv" in html
    # Sound per clip: mute (narration only), under the narration, or clip sound only.
    assert "['mute', '🔇'" in html and "['mix', '🔉'" in html and "['clip', '🔊'" in html
    # Placement is chosen on the slide row, next to the presenter, not in the Clips tab.
    assert "function _xvClipPlaceSelect(" in html and "['right', '▶ Right half']" in html and "['full', '⛶ Full screen']" in html
    for place in ("left-small", "right-small", "center-large", "center-medium"):
        assert "['" + place + "', " in html, place
    assert "Pick a clip first" in html                       # the spot menu shows beside the Clip menu before a pick
    assert "['monitor', '🖥️ Computer screen']" in html and "['laptop', '💻 Laptop']" in html
    assert 'class="xv-sctl"' in html and "ctlRow(m)" in html
    # Your own video, one group per video with its clips under it, a spinner while a clip is cut.
    assert "function xvVidUpload(" in html and "_xvApi('/video')" in html and "xhr.upload.onprogress" in html
    assert "function _xvVideoGroup(" in html and "✂️ Create clip" in html and "💾 Save clip" in html and "function xvClipTrim(" in html
    assert "'Cutting ' + _xvFmtD(e.a)" in html and 'class="xv-spin"' in html
    assert ">Whole video</button>" not in html and "Set start here" not in html
    assert html.count("<summary>Exact time</summary>") == 1
    assert "_xvStatus('');            // an earlier clip error" in html
    # Clip errors show under the video group that was clicked.
    assert 'id="xvYtMsg"' in html and "'xvYtMsg-' + where" in html and "_xvYtMsg('❌ '" in html and "Clip added below" in html
    # Script video cues show on the slide row and in the Clips tab.
    assert "🎬 Video cue: " in html and "Video cues from the script" in html
    js = (ROOT / app / "static" / "explainer" / "runtime.js").read_text(encoding="utf-8")
    assert "holds its last frame" in js
    assert "object-fit:contain" in js
    assert "shown.audio === 'clip'" in js and "c.audio === 'mute'" in js
    gui = (ROOT / app / "web_gui.py").read_text(encoding="utf-8")
    assert '"/api/explainer/<pid>/youtube"' in gui
    assert '"working"' in gui
    assert "yt_add_clip" in gui
    req = (ROOT / app / "requirements.txt").read_text(encoding="utf-8")
    assert "yt-dlp" in req


def check_video_cues(xv) -> None:
    """A [VIDEO CLIP / RESOLVE] note in the script becomes a Demo video slot on
    the slide where the words after it are spoken. It is never spoken itself."""
    script = (
        "FINAL HOOK:\nHost:\nYour AI tool can write a flyer.\n____\n"
        "Heading: Chapter 1 - Copilot drafts fast\nHost:\n[PRODUCTION BEGIN]\n"
        "[GROK IMAGINE / RESOLVE] a laptop\n"
        "[VIDEO CLIP / RESOLVE] Screen demo: pasting the list into Copilot, about 12 seconds\n"
        "[PRODUCTION END]\nWatch what happens when I paste the list in. It sorts the names.\n"
        "=== SUPPORTING RESEARCH ===\n")
    cues = xv.script_video_cues(script)
    assert cues == [{"note": "Screen demo: pasting the list into Copilot, about 12 seconds",
                     "after": "Watch what happens when I paste the list"}], cues
    project = _project(xv, seconds=20)
    (project.dir / "script.txt").write_text(script, encoding="utf-8")
    spoken = "Your AI tool can write a flyer. Watch what happens when I paste the list in. It sorts the names."
    words = [{"text": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate(spoken.split())]
    (project.dir / "words.json").write_text(json.dumps(words), encoding="utf-8")
    slides = [{"id": "s01", "t0": 0, "t1": 3.0, "spoken": "Your AI tool can write a flyer."},
              {"id": "s02", "t0": 3.0, "t1": 10.0, "spoken": "Watch what happens"}]
    assert xv.video_cue_slides(project, slides) == {"s02": cues[0]["note"]}
    assert xv.sync_demo_placeholders(project, slides) == 1
    ph = [c for c in xv.load_youtube(project.data)["clips"] if c.get("status") == "placeholder"]
    assert len(ph) == 1 and ph[0]["slide"] == "s02" and ph[0]["note"].startswith("Screen demo")
    # A second pass adds nothing.
    assert xv.sync_demo_placeholders(project, slides) == 0


def main() -> None:
    mods = [load("explainer_youtube_" + app.replace("-", "_"), app) for app in APPS]
    for xv in mods:
        check_times(xv)
        check_urls_and_errors(xv)
        check_download_commands(xv)
        check_persist_and_assign(xv)
        check_graphs(xv)
        check_panes(xv)
        check_page(xv)
        check_video_cues(xv)
    check_ui(APPS[0])
    check_ui(APPS[1])
    assert mods[0].CLIP_TIMING_NOTE == mods[1].CLIP_TIMING_NOTE
    assert mods[0].YT_FORMAT == mods[1].YT_FORMAT
    print("PASS  youtube clips: times, download command, save, assignment, mute by default")


if __name__ == "__main__":
    main()
