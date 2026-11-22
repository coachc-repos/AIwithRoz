"""Stylized explainer transitions: when they fire, and that each style renders.

No Claude, HeyGen, or network. The smoke test drives the same headless Chrome
page the explainer renders, plus the ffmpeg clip overlay for each style.

    python scriptcraft-app-v3/tests/test_transitions.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
APPS = ("scriptcraft-app-v3", "scriptcraft-app-v3-container")
SAMPLES = ROOT / "scriptcraft-app-v3" / "tests" / "samples" / "transitions"
CORE = ("glitch", "paint", "warp", "pixel", "lightleak")


def load(name: str, app: str):
    path = ROOT / app / "explainer_video.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _slide(i, **kw):
    base = {"id": f"s{i:02d}", "kind": "slide", "section": "Body", "section_key": "body",
            "text": "A quiet explanation of the same point", "t0": i * 3.0, "t1": i * 3.0 + 3.0}
    base.update(kw)
    return base


def fired(events):
    return [(e["index"], e["style"], e["reason"]) for e in events if e["style"]]


def check_rules(xv) -> None:
    assert xv.TRANSITION_DEFAULT == "full"
    assert xv.transition_mode_key(None, None) == "full"
    assert xv.transition_mode_key("nope", None) == "full"
    assert xv.transition_mode_key("", "subtle") == "subtle"
    assert xv.transition_mode_key("off", "full") == "off"
    assert xv.slide_fx_key(None) == "auto"
    assert xv.slide_fx_key("GLITCH") == "glitch"
    assert xv.slide_fx_key("sparkle") == "auto"
    assert xv.transition_intensity("full") == 1.0
    assert xv.transition_intensity("subtle") < xv.transition_intensity("full")
    assert xv.transition_intensity("off") == 0.0
    assert 0.4 <= xv.transition_duration("glitch", "full") <= 0.6
    assert xv.transition_duration("glitch", "subtle") < xv.transition_duration("glitch", "full")

    # Numbered steps are spaced: at most one every 3 slides.
    steps = [_slide(i, text=f"Step {i + 1}") for i in range(8)]
    ev = xv.plan_slide_transitions(steps, mode="full")
    assert ev[0]["style"] == "" and ev[0]["blocked"] == "first"
    assert fired(ev) == [(1, "pixel", "step"), (4, "lightleak", "step"), (7, "shatter", "step")]
    assert ev[2]["blocked"] == "spacing" and "step" in ev[2]["reasons"]
    assert ev[3]["blocked"] == "spacing"

    # A presenter entrance is a demand: it plays even one slide after a step.
    present = [_slide(i, text=f"Step {i + 1}") for i in range(6)]
    present[2]["host"] = "full"
    ev = xv.plan_slide_transitions(present, mode="full")
    assert (2, "lightleak", "presenter") in fired(ev)
    assert ev[2]["blocked"] == ""
    assert ev[3]["blocked"] == "spacing"

    # Entering and leaving a clip both play, back to back.
    media = [_slide(0, text="Intro"), _slide(1, media=True, text="Screen recording of the tool"),
             _slide(2, text="Back to the point")]
    ev = xv.plan_slide_transitions(media, mode="full")
    assert fired(ev) == [(1, "glitch", "media-enter"), (2, "pixel", "media-leave")]

    # A demo-video slot and an assigned clip are the same kind of cut.
    demo = [_slide(0), _slide(1, demo="The invoice bot sending one invoice")]
    assert xv.slide_has_media(demo[1])
    assert "media-enter" in xv.detect_transition_reasons(demo[1], demo[0])
    assigned = [_slide(0), _slide(1)]
    assert "media-enter" in xv.detect_transition_reasons(assigned[1], assigned[0], media_ids={"s01"})
    assert xv.demo_note("Let me show you how this works")
    spoken = [_slide(0), _slide(1, spoken="Let me show you how the bot sends it")]
    assert "media-enter" in xv.detect_transition_reasons(spoken[1], spoken[0])

    # Big stat / count, and a #2 marker, are steps. A plain sentence with a
    # number in it is not.
    stat = [_slide(0), _slide(1, has_stat=True, text="The loss")]
    count = [_slide(0), _slide(1, has_count=True, text="It climbed")]
    mark = [_slide(0), _slide(1, text="Point #2 in the list")]
    plain = [_slide(0), _slide(1, text="The fund paid 6 percent too")]
    assert xv.detect_transition_reasons(stat[1], stat[0]) == ["step"]
    assert xv.detect_transition_reasons(count[1], count[0]) == ["step"]
    assert "step" in xv.detect_transition_reasons(mark[1], mark[0])
    assert xv.detect_transition_reasons(plain[1], plain[0]) == []

    # Section change, hook to body, body to outro, and a new scene object.
    body = [_slide(0, section="Hook", section_key="hook", kind="chapter", text="Cold open"),
            _slide(1, section="The drop", section_key="c1", text="Now the story")]
    assert "scene" in xv.detect_transition_reasons(body[1], body[0])
    outro = [_slide(0, section="The drop", section_key="c1"),
             _slide(1, section="Outro", section_key="out", text="The close")]
    assert "scene" in xv.detect_transition_reasons(outro[1], outro[0])
    pictures = [_slide(0, kind="scene", scene_type="house"),
                _slide(1, kind="scene", scene_type="bot", section_key="body")]
    assert xv.detect_transition_reasons(pictures[1], pictures[0]) == ["scene"]
    same = [_slide(0, kind="scene", scene_type="house"), _slide(1, kind="scene", scene_type="house")]
    assert xv.detect_transition_reasons(same[1], same[0]) == []

    # Presenter only on the way in, not on the next presenter slide.
    hosts = [_slide(0), _slide(1, host="full"), _slide(2, host="pip")]
    assert xv.detect_transition_reasons(hosts[1], hosts[0]) == ["presenter"]
    assert "presenter" not in xv.detect_transition_reasons(hosts[2], hosts[1])

    # Overrides and the global switch.
    one = [_slide(0), _slide(1, host="full")]
    assert xv.plan_slide_transitions(one, mode="off")[1]["blocked"] == "off"
    assert xv.plan_slide_transitions(one, mode="full", overrides={"s01": "none"})[1]["blocked"] == "none"
    forced = xv.plan_slide_transitions([_slide(0), _slide(1)], mode="full", overrides={"s01": "warp"})
    assert forced[1]["style"] == "warp" and forced[1]["reason"] == "override"
    subtle = xv.plan_slide_transitions(one, mode="subtle")
    full = xv.plan_slide_transitions(one, mode="full")
    assert subtle[1]["style"] == full[1]["style"]
    assert subtle[1]["dur"] < full[1]["dur"] and subtle[1]["amp"] < full[1]["amp"]

    # Styles rotate by trigger, not by slide index.
    clips = []
    for i in range(6):
        clips.append(_slide(i, media=bool(i % 2), text="A clip" if i % 2 else "A slide"))
    ev = xv.plan_slide_transitions(clips, mode="full")
    enters = [e["style"] for e in ev if e["reason"] == "media-enter"]
    assert enters == ["glitch", "pixel", "warp"]


def check_compile_keeps_text(xv) -> None:
    words = []
    t = 0.2
    for word in "Markets moved by more than anyone expected today and the fund paid".split():
        words.append({"text": word, "start": round(t, 3), "end": round(t + 0.25, 3)})
        t += 0.3
    timeline = xv.Timeline(words, t + 2)
    raw = (
        '<section id="s01" data-at="Markets moved by more" data-kind="slide" data-section="hook">'
        '<h1 class="h1">Markets moved</h1></section>'
        '<section id="s02" data-at="the fund paid" data-kind="slide" data-section="c1" data-host="full">'
        '<h1 class="h1">Step 3</h1><div class="huge">$2.3T</div></section>'
        '<section id="s03" data-at="anyone expected today" data-kind="scene" data-section="c1" data-demo="the bot">'
        '<svg class="sc" data-sc="house"></svg><p>The house stays</p></section>'
    )
    comp = xv.compile_composition(raw, timeline, duration=t + 2, plan={"slides": [], "sections": [
        {"key": "hook", "label": "Hook"}, {"key": "c1", "label": "The drop"}]},
        logos={}, values={}, logo_choices={}, host_on=True)
    assert "Markets moved" in comp["html"] and "Step 3" in comp["html"] and "The house stays" in comp["html"]
    assert comp["slides"][2]["scene_type"] == "house"
    assert comp["slides"][2]["demo"] == "the bot"
    before = comp["html"]
    xv.apply_transition_plan(comp, mode="full", media_ids=set())
    assert "Markets moved" in comp["html"] and "Step 3" in comp["html"] and "The house stays" in comp["html"]
    assert 'data-fx="' in comp["html"]
    # Stamping only adds attributes. The visible words are the same.
    for phrase in ("Markets moved", "Step 3", "$2.3T", "The house stays"):
        assert before.count(phrase) == comp["html"].count(phrase)
    styles = {m["id"]: m["fx"] for m in comp["slides"]}
    assert styles["s01"] == ""
    assert styles["s02"]  # presenter and a step; presenter wins
    assert comp["slides"][1]["fx_reason"] == "presenter"
    assert styles["s03"]  # leaving the presenter is not media; scene type changes, maybe spacing
    page = xv.page_html(comp, mode="render", bubble="off")
    assert "transitions.js" not in page  # the source is inlined
    assert "XVFx" in page and 'id="fx"' in page
    cfg = json.loads(page.split("window.__EXPLAINER = ", 1)[1].split(";</script>", 1)[0])
    assert cfg["fx"] and cfg["fx"][0]["style"] in xv.TRANSITION_STYLES


def check_project_roundtrip(xv) -> None:
    folder = Path(tempfile.mkdtemp(prefix="xv-fx-"))
    words = [{"text": w, "start": i * 0.4, "end": i * 0.4 + 0.3}
             for i, w in enumerate("Markets moved by more than anyone expected today and the fund paid".split())]
    payload = {
        "current": 1, "audio_seconds": 8, "title": "T", "transition_mode": "full",
        "slide_fx": {"s02": "paint"},
        "youtube": {"videos": [], "clips": [{
            "id": "yc_1", "slide": "s03", "status": "placeholder", "file": "", "audio": "mute"}]},
    }
    (folder / "project.json").write_text(json.dumps(payload), encoding="utf-8")
    (folder / "words.json").write_text(json.dumps(words), encoding="utf-8")
    (folder / "plan.json").write_text("{}", encoding="utf-8")
    (folder / "versions").mkdir()
    (folder / "versions" / "v001.html").write_text(
        '<section id="s01" data-at="Markets moved" data-kind="slide"><h1 class="h1">Markets</h1></section>'
        '<section id="s02" data-at="than anyone expected" data-kind="slide"><h1 class="h1">Anyone</h1></section>'
        '<section id="s03" data-at="the fund paid" data-kind="slide"><h1 class="h1">Fund</h1></section>',
        encoding="utf-8")
    project = xv.open_project(folder)
    comp = project.compile()
    by = {m["id"]: m for m in comp["slides"]}
    assert by["s02"]["fx"] == "paint" and by["s02"]["fx_reason"] == "override"
    assert by["s03"]["fx_reason"] == "media-enter"
    assert "Markets" in comp["html"] and 'data-fx="paint"' in comp["html"]
    ids = xv.media_ids_of(project.data)
    assert ids == {"s03"}


def _graph(cmd) -> str:
    return cmd[cmd.index("-filter_complex") + 1]


def check_clip_audio_unchanged(xv) -> None:
    plain = {"path": "c.mp4", "show": 3, "offset": 1, "seconds": 2, "src_skip": 0, "w": 1920, "h": 1080}
    graph = _graph(xv.build_overlay_cmd(Path("base.mp4"), Path("out.mp4"), [plain], 1920, 1080))
    assert "format=yuv420p" in graph and "trim=duration=3.000" in graph
    assert "fade=" not in graph and "rgbashift" not in graph
    short = dict(plain, seconds=1, show=3)
    assert "tpad=stop_mode=clone" in _graph(xv.build_overlay_cmd(Path("b.mp4"), Path("o.mp4"), [short], 1920, 1080))
    styled = dict(plain, show=3, head_fade=0.5, tail=0.4, enter_style="glitch", leave_style="pixel",
                  fx_amp=1, audio="clip")
    graph = _graph(xv.build_overlay_cmd(Path("base.mp4"), Path("out.mp4"), [styled], 1920, 1080))
    assert "rgbashift" in graph and "pixelize" in graph
    assert "fade=t=in" in graph and "fade=t=out" in graph
    assert "trim=duration=3.400" in graph
    # The narration gate stays on the slide window. The 0.4 s tail is picture only.
    mux = " ".join(xv.build_mux_cmd(Path("v.mp4"), Path("n.wav"), Path("o.mp4"), 0, 10, [styled]))
    assert "volume=0" in mux and "between(t,1.000,4.000)" in mux
    assert "sidechaincompress" not in mux
    mix = dict(styled, audio="mix")
    mixed = " ".join(xv.build_mux_cmd(Path("v.mp4"), Path("n.wav"), Path("o.mp4"), 0, 10, [mix]))
    assert "sidechaincompress" in mixed and "volume=0" not in mixed
    muted = dict(styled, audio="mute")
    same = xv.build_mux_cmd(Path("v.mp4"), Path("n.wav"), Path("o.mp4"), 0, 10, [muted])
    assert "1:a:0" in same and "sidechaincompress" not in " ".join(same)


def check_ffmpeg_styles(xv) -> None:
    """Each style's clip filter is a graph ffmpeg will actually run."""
    work = Path(tempfile.mkdtemp(prefix="xv-fx-ff-"))
    base = work / "base.mp4"
    clip = work / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", "color=c=0x102040:s=320x180:d=1.2:r=30", "-pix_fmt", "yuv420p", str(base)],
                   check=True)
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", "color=c=0xf5b83d:s=320x180:d=1.2:r=30", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=1.2", "-shortest", "-pix_fmt", "yuv420p", str(clip)],
                   check=True)
    for style in xv.TRANSITION_STYLES:
        out = work / f"{style}.mp4"
        item = {"path": str(clip), "show": 0.8, "offset": 0.2, "seconds": 1.0, "src_skip": 0,
                "w": 320, "h": 180, "head_fade": 0.4, "tail": 0.0, "enter_style": style,
                "leave_style": "", "fx_amp": 1, "audio": "mute"}
        cmd = xv.build_overlay_cmd(base, out, [item], 320, 180)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode == 0, (style, proc.stderr[-400:])
        assert out.is_file() and out.stat().st_size > 1000
        assert abs(xv.media_seconds(out) - 1.2) < 0.15, style


def check_ui(app: str) -> None:
    html = (ROOT / app / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="xvTransition"' in html and 'value="full" selected' in html.split('id="xvTransition"', 1)[1].split("</select>", 1)[0]
    assert 'id="xvFxMode"' in html
    assert "xvTransitionMode" in html and "xvSlideFx" in html
    assert "transition_mode: transitionMode" in html
    assert "s.transition_mode, s.slide_fx" in html
    for style in ("glitch", "paint", "warp", "pixel", "lightleak", "burn", "shatter"):
        assert style in html, style
    js = (ROOT / app / "static" / "explainer" / "runtime.js").read_text(encoding="utf-8")
    assert "XVFx" in js and "clipTail" in js
    assert "shown.audio === 'clip'" in js
    fx = (ROOT / app / "static" / "explainer" / "transitions.js").read_text(encoding="utf-8")
    for style in ("glitch", "paint", "warp", "pixel", "lightleak", "burn", "shatter"):
        assert f"'{style}'" in fx or f'"{style}"' in fx
    assert "clearRect" in fx
    gui = (ROOT / app / "web_gui.py").read_text(encoding="utf-8")
    assert '"/api/explainer/<pid>/transitions"' in gui
    assert "transition_mode" in gui and "slide_fx_key" in gui


def _card(sid, t0, t1, kind, kicker, title, color, bg) -> str:
    return (
        f'<section class="slide kind-{kind}" id="{sid}" data-kind="{kind}" data-t0="{t0:.3f}" data-t1="{t1:.3f}" '
        f'data-sidx="0" data-slabel="" data-hud="on" data-transition="push" data-tracker="">'
        f'<div style="position:absolute;left:140px;top:220px;width:1640px;height:560px;background:{bg};'
        f'border-radius:28px"></div>'
        f'<div class="kicker" style="position:absolute;left:200px;top:280px">{kicker}</div>'
        f'<h1 class="h1" style="position:absolute;left:200px;top:360px;color:{color}">{title}</h1>'
        f'</section>'
    )


def _compiled(xv, slides, html, overrides=None):
    comp = {"html": "\n".join(html), "slides": slides, "duration": slides[-1]["t1"],
            "start": 0.0, "end": slides[-1]["t1"], "sections": ["Hook", "Body", "Outro"],
            "host_windows": [], "host_sections": []}
    xv.apply_transition_plan(comp, mode="full", overrides=overrides or {})
    return comp


def _render(xv, page: Path, out: Path, start: float, end: float, grabs: dict) -> None:
    exe, headless = xv.find_chrome()
    f0, f1 = int(round(start * xv.FPS)), int(round(end * xv.FPS))
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(xv.FPS),
           "-c:v", "png", "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    async def frames():
        async with xv._Chrome(exe, headless) as ch:
            await ch.open(page, 1.0, transparent=False)
            for f in range(f0, f1):
                png = await ch.frame(f / xv.FPS)
                if f in grabs:
                    grabs[f] = png
                ff.stdin.write(png)

    try:
        asyncio.run(frames())
    except BaseException:
        ff.kill()
        raise
    ff.stdin.close()
    err = ff.stderr.read().decode(errors="ignore")
    rc = ff.wait()
    if rc != 0:
        raise RuntimeError(err[-400:])


def _mean_diff(a: Image.Image, b: Image.Image) -> float:
    a = a.resize((160, 90)).convert("RGB")
    b = b.resize((160, 90)).convert("RGB")
    da, db = a.tobytes(), b.tobytes()
    return sum(abs(x - y) for x, y in zip(da, db)) / len(da)


def _has_dark(im: Image.Image) -> bool:
    small = im.resize((80, 45)).convert("RGB")
    raw = small.tobytes()
    dark = 0
    for i in range(0, len(raw), 3):
        if raw[i] + raw[i + 1] + raw[i + 2] < 90:
            dark += 1
    return dark > 40


def check_renders(xv) -> None:
    try:
        import websockets  # noqa: F401
    except ImportError:
        print("skip  Chrome render: websockets is not installed")
        return
    if not xv.find_chrome() or not xv.shutil.which("ffmpeg"):
        print("skip  Chrome render: Chrome or ffmpeg is missing")
        return
    SAMPLES.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="xv-fx-pages-"))
    shots, labels = [], []
    for style in CORE:
        slides = [
            {"id": "a", "t0": 0.0, "t1": 1.05, "kind": "slide", "section": "A", "section_key": "a", "text": "Before"},
            {"id": "b", "t0": 1.05, "t1": 2.3, "kind": "slide", "section": "A", "section_key": "a", "text": "After"},
        ]
        html = [
            _card("a", 0.0, 1.05, "slide", "OUTGOING", "BEFORE", "#090c12", "#f5b83d"),
            _card("b", 1.05, 2.3, "slide", "INCOMING", "AFTER", "#f2f4f8", "#4c8dff"),
        ]
        comp = _compiled(xv, slides, html, {"b": style})
        assert comp["slides"][1]["fx"] == style, comp["slides"][1]
        assert "BEFORE" in comp["html"] and "AFTER" in comp["html"]
        page = work / f"{style}.html"
        page.write_text(xv.page_html(comp, mode="render", title=style, bubble="off",
                                     visual={"style": "classic"}), encoding="utf-8")
        dur = comp["slides"][1]["fx_dur"]
        t_mid = 1.05 + dur * 0.5
        grabs = {int(round(t * xv.FPS)): None for t in (0.4, t_mid, 1.05 + dur + 0.25)}
        out = SAMPLES / f"transition_{style}.mp4"
        print(f"render {style} ({dur:.2f}s effect)", flush=True)
        _render(xv, page, out, 0.0, 2.3, grabs)
        assert abs(xv.media_seconds(out) - 2.3) < 0.12, (style, xv.media_seconds(out))
        frames = [Image.open(io.BytesIO(grabs[k])).convert("RGB") for k in sorted(grabs)]
        before, mid, after = frames
        assert _mean_diff(before, mid) > 8, style
        assert _mean_diff(after, mid) > 8, style
        assert _mean_diff(before, after) > 8, style
        assert _has_dark(mid), style
        shots.append(xv.render_stills and None)
        labels.append(f"{style}  mid")
        buf = io.BytesIO()
        mid.save(buf, "PNG")
        shots[-1] = buf.getvalue()
    # Early / late of the glitch, so the sheet shows the move and not one freeze.
    sheet = xv.contact_sheet(shots, labels, cols=5, width=360)
    (SAMPLES / "transitions_sheet.png").write_bytes(sheet)

    # ~30s demo: hook, plain cuts, a spaced step, a held step, a scene, presenter, clip, leave.
    demo_specs = [
        ("s01", 0.0, "chapter", "hook", "Hook", "HOOK", "Wait.", False, "", ""),
        ("s02", 2.5, "slide", "body", "The drop", "BODY", "The drop", False, "", ""),
        ("s03", 5.0, "slide", "body", "The drop", "NO CUT", "Still here", False, "", ""),
        ("s04", 7.5, "slide", "body", "The drop", "NO CUT", "And here", False, "", ""),
        ("s05", 10.0, "slide", "body", "The drop", "STEP", "Step 1", True, "", ""),
        ("s06", 12.5, "slide", "body", "The drop", "HELD", "Step 2", True, "", ""),
        ("s07", 15.0, "slide", "body", "The drop", "NO CUT", "Keep going", False, "", ""),
        ("s08", 17.5, "scene", "body", "The drop", "SCENE", "New picture", False, "house", ""),
        ("s09", 20.0, "slide", "body", "The drop", "PRESENTER", "Roz", False, "", "full"),
        ("s10", 22.5, "slide", "body", "The drop", "CLIP", "Demo", False, "", ""),
        ("s11", 25.0, "slide", "outro", "Outro", "LEAVE", "That's it", False, "", ""),
        ("s12", 27.5, "slide", "outro", "Outro", "NO CUT", "Hold", False, "", ""),
    ]
    slides, html = [], []
    colors = [("#f5b83d", "#121824"), ("#f2f4f8", "#1a2232"), ("#8a94a6", "#121824"),
              ("#f2f4f8", "#13213a"), ("#090c12", "#f5b83d"), ("#090c12", "#4c8dff"),
              ("#f2f4f8", "#121824"), ("#f5b83d", "#0c1526"), ("#f2f4f8", "#1a2232"),
              ("#090c12", "#3cc878"), ("#f2f4f8", "#121824"), ("#8a94a6", "#0c1526")]
    for i, (sid, t0, kind, key, section, kicker, title, step, scene, host) in enumerate(demo_specs):
        slides.append({"id": sid, "t0": t0, "t1": t0 + 2.5, "kind": kind, "section": section,
                       "section_key": key, "text": title, "has_stat": step, "scene_type": scene,
                       "host": host, "media": sid == "s10", "demo": "screen recording" if sid == "s10" else ""})
        bg, fg = colors[i][1], colors[i][0]
        html.append(_card(sid, t0, t0 + 2.5, kind, kicker, title, fg, bg))
    comp = _compiled(xv, slides, html)
    by = {m["id"]: m for m in comp["slides"]}
    assert by["s01"]["fx"] == "" and by["s01"]["fx_blocked"] == "first"
    assert by["s02"]["fx_reason"] == "scene"
    assert by["s03"]["fx"] == "" and by["s04"]["fx"] == ""
    assert by["s05"]["fx_reason"] == "step"
    assert by["s06"]["fx_blocked"] == "spacing"
    assert by["s07"]["fx"] == ""
    assert by["s08"]["fx_reason"] == "scene"
    assert by["s09"]["fx_reason"] == "presenter"
    assert by["s10"]["fx_reason"] == "media-enter"
    assert by["s11"]["fx_reason"] == "media-leave"
    assert by["s12"]["fx"] == ""
    # The five core styles all show up across the demo.
    used = {m["fx"] for m in comp["slides"] if m["fx"]}
    assert set(CORE) <= used, used
    page = work / "demo.html"
    page.write_text(xv.page_html(comp, mode="render", title="Transitions demo", bubble="off",
                                 visual={"style": "classic"}), encoding="utf-8")
    demo = SAMPLES / "transitions_demo.mp4"
    print("render demo 30s", flush=True)
    _render(xv, page, demo, 0.0, 30.0, {})
    got = xv.media_seconds(demo)
    assert abs(got - 30.0) < 0.15, got
    print(f"samples in {SAMPLES}", flush=True)


def check_copies(local, container) -> None:
    slides = [_slide(0), _slide(1, host="full"), _slide(2, text="Step 3", has_stat=True),
              _slide(3, media=True)]
    assert local.plan_slide_transitions(slides, mode="full") == container.plan_slide_transitions(slides, mode="full")
    assert local.TRANSITION_DURS == container.TRANSITION_DURS
    assert local.transition_mode_key("subtle") == container.transition_mode_key("subtle")


def main() -> None:
    local = load("explainer_fx_v3", APPS[0])
    container = load("explainer_fx_container", APPS[1])
    for xv in (local, container):
        check_rules(xv)
        check_compile_keeps_text(xv)
        check_project_roundtrip(xv)
        check_clip_audio_unchanged(xv)
        check_ffmpeg_styles(xv)
    check_copies(local, container)
    for app in APPS:
        check_ui(app)
    check_renders(local)
    print("PASS  stylized transitions fire on presenter, clips, steps and scene changes; the rest stay cuts")


if __name__ == "__main__":
    main()
