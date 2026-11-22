"""Article line matching, emphasis detection, underline timing, and a render smoke test.

    python scriptcraft-app-v3/tests/test_articles_emphasis.py

Set WRITE_ARTICLE_SAMPLES=1 to rebuild the clips in tests/samples/articles/.
"""
from __future__ import annotations

import importlib.util
import math
import os
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPS = ("scriptcraft-app-v3", "scriptcraft-app-v3-container")
SAMPLES = ROOT / "scriptcraft-app-v3" / "tests" / "samples" / "articles"
GOLD = (245, 184, 61)
PAPER = (247, 243, 234)

SCRIPT = """Host: The bench stays **perfectly clear** when you work.
A dull chisel is set aside until it is *honed*.
You MUST put the tools back.
<emphasis>same day</emphasis> is the rule.
THIS WHOLE LINE IS A HEADING IN CAPS
"""

LINES = [
    {"id": "l0", "text": "The bench stays clear when tools go back", "x": 0.08, "y": 0.12, "w": 0.8, "h": 0.05},
    {"id": "l1", "text": "Advertisement", "x": 0.08, "y": 0.22, "w": 0.3, "h": 0.04},
    {"id": "l2", "text": "A dull chisel is set aside until it is honed", "x": 0.08, "y": 0.40, "w": 0.8, "h": 0.05},
    {"id": "l3", "text": "Light from the left makes the edge easy to see", "x": 0.08, "y": 0.55, "w": 0.8, "h": 0.05},
    {"id": "l4", "text": "Copyright nineteen ninety eight unrelated catalog entry", "x": 0.08, "y": 0.86, "w": 0.7, "h": 0.04},
]
NARRATION = (
    "The bench stays clear when tools go back the same day. "
    "A dull chisel is set aside until it is honed. "
    "Light from the left makes the edge easy to see."
)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_articles(tag: str, app: str):
    return load(f"articles_{tag}", ROOT / app / "explainer_articles.py")


def load_video(tag: str, app: str):
    return load(f"video_{tag}", ROOT / app / "explainer_video.py")


def check_lines(mod) -> None:
    picked = mod.suggest_lines(LINES, NARRATION)
    assert picked[:3] == ["l0", "l2", "l3"] or set(picked) == {"l0", "l2", "l3"}
    assert "l1" not in picked and "l4" not in picked
    assert mod.line_score("Advertisement", NARRATION) < mod.LINE_SCORE
    assert mod.url_problem("file:///etc/passwd")
    assert mod.url_problem("http://127.0.0.1/article")
    assert mod.url_problem("https://169.254.169.254/latest")
    assert mod.url_problem("https://example.com/story") is None
    assert mod.paywalled("Subscribe to continue reading this story")
    long_page = ("The workshop keeps a clear bench. " * 80) + " subscribe to continue"
    assert not mod.paywalled(long_page)


def check_timing(mod) -> None:
    words = [
        {"text": "The", "start": 10.2, "end": 10.4},
        {"text": "bench", "start": 10.4, "end": 10.7},
        {"text": "stays", "start": 10.7, "end": 11.0},
        {"text": "clear", "start": 11.0, "end": 11.4},
        {"text": "when", "start": 11.4, "end": 11.6},
        {"text": "tools", "start": 11.6, "end": 11.9},
        {"text": "go", "start": 11.9, "end": 12.1},
        {"text": "back", "start": 12.1, "end": 12.4},
        {"text": "A", "start": 13.0, "end": 13.1},
        {"text": "dull", "start": 13.1, "end": 13.4},
        {"text": "chisel", "start": 13.4, "end": 13.8},
        {"text": "is", "start": 13.8, "end": 13.9},
        {"text": "set", "start": 13.9, "end": 14.1},
        {"text": "aside", "start": 14.1, "end": 14.4},
        {"text": "until", "start": 14.4, "end": 14.6},
        {"text": "it", "start": 14.6, "end": 14.7},
        {"text": "is", "start": 14.7, "end": 14.8},
        {"text": "honed.", "start": 14.8, "end": 15.2},
    ]
    span = mod.phrase_span("until it is honed", words, 10, 16)
    assert span is not None and abs(span[0] - 14.4) < 0.05
    assert mod.phrase_span("not spoken here", words, 10, 16) is None
    cues = mod.line_cues(LINES, ["l0", "l2", "l4"], words, 10, 16)
    by_id = {c["id"]: c["t"] for c in cues}
    assert by_id["l0"] == 10.9  # spoken earlier than the entrance, so it waits
    assert abs(by_id["l2"] - 13.0) < 0.05
    # The catalog line is not in the narration, so it takes an even slot.
    assert by_id["l4"] > by_id["l2"]
    clock = {"intro_dur": 4.0, "hook_end": 2.0}
    assert mod.narration_lag(1.2, clock) == 0.0
    assert mod.to_narration(0.4, 1.8, clock) == (0.4, 1.8, 0.0)
    narr0, narr1, lag = mod.to_narration(6.0, 10.0, clock)
    assert (narr0, narr1, lag) == (2.0, 6.0, 4.0)
    shifted = mod.line_cues(
        [{"id": "l0", "text": "until it is honed", "x": 0.1, "y": 0.2, "w": 0.5, "h": 0.05}],
        ["l0"],
        [{"text": "until", "start": 3.2, "end": 3.5}, {"text": "it", "start": 3.5, "end": 3.6},
         {"text": "is", "start": 3.6, "end": 3.7}, {"text": "honed", "start": 3.7, "end": 4.1}],
        narr0, narr1)
    assert abs(shifted[0]["t"] + lag - 7.2) < 0.05
    even = mod.line_cues(LINES, ["l0", "l2", "l3"], [], 10, 16)
    times = [c["t"] for c in even]
    assert times[0] == 10.9
    assert times[1] > times[0] and times[2] > times[1]
    assert abs((times[1] - times[0]) - (times[2] - times[1])) < 0.02


def _tone(path: Path) -> list:
    rate = 16000
    spec = [
        ("the", 0.00, 0.28, 110, 0.12),
        ("bench", 0.32, 0.62, 120, 0.14),
        ("stays", 0.66, 0.96, 115, 0.13),
        ("clear", 1.00, 1.32, 118, 0.14),
        ("TODAY", 1.40, 1.98, 240, 0.9),
        ("again", 2.08, 2.38, 112, 0.12),
    ]
    n = int(rate * 2.6)
    samples = [0.0] * n
    for _text, a, b, freq, amp in spec:
        i0, i1 = int(a * rate), int(b * rate)
        for i in range(i0, min(i1, n)):
            edge = min(1.0, (i - i0) / 180, (i1 - i) / 180)
            samples[i] += amp * edge * math.sin(2 * math.pi * freq * (i - i0) / rate)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(struct.pack("<h", max(-32767, min(32767, int(s * 32767)))) for s in samples))
    return [{"text": text, "start": a, "end": b} for text, a, b, _f, _amp in spec]


def check_emphasis(mod) -> None:
    found = {item["kind"]: [] for item in mod.markup_phrases(SCRIPT)}
    for item in mod.markup_phrases(SCRIPT):
        found.setdefault(item["kind"], []).append(mod.norm_phrase(item["phrase"]))
    assert "perfectly clear" in found["bold"]
    assert "honed" in found["italic"]
    assert "must" in found["caps"]
    assert "same day" in found["ssml"]
    assert not any(len(p) > 12 for p in found["caps"])
    slides = [
        {"id": "s1", "t0": 0.0, "t1": 4.0, "spoken": "The bench stays perfectly clear when you work.",
         "text": "The bench stays perfectly clear when you work."},
        {"id": "s2", "t0": 4.0, "t1": 9.0, "spoken": "A dull chisel is set aside until it is honed.",
         "text": "A dull chisel is set aside until it is honed."},
        {"id": "s3", "t0": 9.0, "t1": 13.0, "spoken": "You must put the tools back the same day.",
         "text": "Put the tools back."},
    ]
    words = []
    cursor = 0.2
    for slide in slides:
        for word in slide["spoken"].replace(".", "").split():
            words.append({"text": word, "start": cursor, "end": cursor + 0.28})
            cursor += 0.32
        cursor = slide["t1"] + 0.2
    prefs = mod.emphasis_prefs({})
    marks = mod.collect_marks(SCRIPT, slides, words, None, prefs, "")
    phrases = {(m["slide"], mod.norm_phrase(m["phrase"])) for m in marks}
    assert ("s1", "perfectly clear") in phrases
    assert ("s2", "honed") in phrases
    assert ("s3", "must") in phrases
    assert ("s3", "same day") in phrases
    drawn = mod.drawable_marks(marks, slides)
    assert any(m["phrase"].lower().startswith("perfectly") for m in drawn)
    # "same day" is spoken on s3 but the card only says "Put the tools back."
    assert not any(mod.norm_phrase(m["phrase"]) == "same day" for m in drawn)
    off = mod.collect_marks(SCRIPT, slides, words, None, {"enabled": False, "slides": {}, "removed": [], "added": []}, "")
    assert off and not mod.drawable_marks(off, slides)
    gone = mod.collect_marks(SCRIPT, slides, words, None, {
        "enabled": True, "slides": {}, "removed": [{"slide": "s2", "phrase": "honed"}], "added": [],
    }, "")
    assert not any(m["slide"] == "s2" and mod.norm_phrase(m["phrase"]) == "honed" for m in gone)

    folder = Path(tempfile.mkdtemp())
    wav = folder / "tone.wav"
    tone_words = _tone(wav)
    hits = mod.emphasis_from_audio(wav, tone_words, 0.0, 2.6)
    assert hits and hits[0]["phrase"].lower() == "today"
    assert abs(hits[0]["t"] - 1.40) < 0.05
    assert len(hits) == 1


def _compiled(text_html: str, slides: list, duration: float) -> dict:
    return {"html": text_html, "slides": slides, "duration": duration, "start": 0.0, "end": duration,
            "sections": [], "host_windows": [], "host_sections": []}


def _font(size: int):
    from PIL import ImageFont
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_article():
    """An original page, not a capture of someone else's article."""
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (1600, 1000), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1600, 16), fill=(40, 64, 92))
    title_font, body_font, foot_font = _font(54), _font(36), _font(28)
    rows = [
        (90, "The bench stays clear when tools go back", title_font),
        (280, "A dull chisel is set aside until it is honed", body_font),
        (430, "Light from the left makes the edge easy to see", body_font),
        (860, "Shop copy. Written for this sample.", foot_font),
    ]
    lines = []
    for i, (y, text, font) in enumerate(rows):
        draw.text((80, y), text, fill=(28, 32, 38), font=font)
        box = draw.textbbox((80, y), text, font=font)
        lines.append({
            "id": f"l{i}", "text": text,
            "x": box[0] / 1600, "y": box[1] / 1000,
            "w": (box[2] - box[0]) / 1600, "h": (box[3] - box[1]) / 1000,
        })
    return image, lines


def _page(xv, kind: str):
    import base64
    import io
    if kind == "article":
        image, lines = draw_article()
        buf = io.BytesIO()
        image.save(buf, "PNG")
        src = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        slides = [{"id": "s1", "t0": 0.0, "t1": 4.0, "kind": "slide", "spoken": NARRATION}]
        html = (
            '<section class="slide kind-slide" id="s1" data-kind="slide" data-t0="0.000" data-t1="4.000" '
            'data-sidx="0" data-slabel="" data-hud="off" data-transition="cut" data-tracker="">'
            '<div class="pad"><div class="card"><h2 class="h2">Notes</h2></div></div></section>'
        )
        cues = [
            {**lines[0], "t": 1.05},
            {**lines[1], "t": 1.85},
            {**lines[2], "t": 2.65},
        ]
        articles = [{"id": "a1", "slide": "s1", "src": src, "w": 1600, "h": 1000,
                     "t0": 0.0, "t1": 4.0, "lines": cues, "accent": "#f5b83d"}]
        emphasis = {"marks": [], "accent": "#f5b83d"}
        return xv.page_html(_compiled(html, slides, 4.0), mode="render", title="Article",
                            articles=articles, emphasis=emphasis, bubble="off"), 4.0, image
    slides = [{"id": "s1", "t0": 0.0, "t1": 3.2, "kind": "slide", "spoken": "Keep the edge honed."}]
    html = (
        '<section class="slide kind-slide" id="s1" data-kind="slide" data-t0="0.000" data-t1="3.200" '
        'data-sidx="0" data-slabel="" data-hud="off" data-transition="cut" data-tracker="">'
        '<div class="pad"><div class="card"><h2 class="h2">Keep the edge honed</h2></div></div></section>'
    )
    emphasis = {"marks": [{"slide": "s1", "phrase": "honed", "t": 1.15, "t1": 3.2}], "accent": "#f5b83d"}
    return xv.page_html(_compiled(html, slides, 3.2), mode="render", title="Emphasis",
                        articles=[], emphasis=emphasis, bubble="off"), 3.2, None


def _gold(px) -> bool:
    r, g, b = px[:3]
    return r > 210 and 140 < g < 220 and b < 110 and r > g > b


def _near(px, rgb, tol=18) -> bool:
    return all(abs(int(px[i]) - rgb[i]) <= tol for i in range(3))


def _count(image, pred, box=None) -> int:
    pixels = image.convert("RGB").load()
    w, h = image.size
    x0, y0, x1, y1 = box or (0, 0, w, h)
    n = 0
    for y in range(max(0, y0), min(h, y1)):
        for x in range(max(0, x0), min(w, x1), 2):
            if pred(pixels[x, y]):
                n += 1
    return n


def check_page_config(xv) -> None:
    page, _dur, _image = _page(xv, "emphasis")
    assert "Keep the edge honed" in page
    assert '"phrase": "honed"' in page or '"phrase":"honed"' in page
    assert "placeEmphasis" in (ROOT / "scriptcraft-app-v3" / "static" / "explainer" / "runtime.js").read_text(encoding="utf-8")
    css = (ROOT / "scriptcraft-app-v3" / "static" / "explainer" / "design.css").read_text(encoding="utf-8")
    assert ".card { background: var(--panel);" in css
    assert "#article-layer" in css and "#emphasis-ink" in css
    assert "text-decoration" not in css.split("#article-layer")[-1]


def check_smoke(xv) -> None:
    try:
        import websockets  # noqa: F401
        from PIL import Image
    except Exception as exc:
        print(f"skip  render smoke: {exc}")
        return
    if not xv.find_chrome():
        print("skip  render smoke: Chrome is not installed")
        return
    import asyncio
    page, _dur, _image = _page(xv, "emphasis")
    folder = Path(tempfile.mkdtemp())
    html = folder / "emphasis.html"
    html.write_text(page, encoding="utf-8")

    async def grab(path, times):
        exe = xv.find_chrome()
        async with xv._Chrome(*exe) as chrome:
            await chrome.open(path, 1.0, transparent=False)
            return [await chrome.frame(t) for t in times]

    before, after = asyncio.run(grab(html, [0.4, 1.7]))
    early = Image.open(__import__("io").BytesIO(before))
    late = Image.open(__import__("io").BytesIO(after))
    # The wave dots and the progress bar sit low. The heading underline is above them.
    # The heading sits in the upper band, above the wave field, so gold there is the stroke.
    assert _count(early, _gold, (240, 160, 1680, 460)) < 30
    assert _count(late, _gold, (240, 160, 1680, 460)) > 80
    article_page, _dur, source = _page(xv, "article")
    html.write_text(article_page, encoding="utf-8")
    shot = asyncio.run(grab(html, [2.3]))[0]
    frame = Image.open(__import__("io").BytesIO(shot))
    assert _count(frame, lambda px: _near(px, PAPER, 14), (400, 140, 1520, 860)) > 400
    assert _count(frame, lambda px: 165 < px[0] < 225 and abs(px[0] - px[1]) < 25, (500, 180, 1400, 820)) > 400
    assert _count(frame, _gold, (400, 140, 1520, 860)) > 60
    assert '"articles"' in article_page and "data:image/png" in article_page
    return


def write_samples(xv) -> None:
    import asyncio
    import io
    from PIL import Image
    SAMPLES.mkdir(parents=True, exist_ok=True)
    _image, _lines = draw_article()
    _image.save(SAMPLES / "sample_article.png")
    note = SAMPLES / "SOURCES.txt"
    note.write_text(
        "Original sample text, written for this test. It is not a screenshot of a published article.\n"
        "article_slide.mp4: the page tilts in over the waves and three lines are underlined in turn.\n"
        "article_frame.png: a frame while the second line is drawing.\n"
        "emphasis_underline.mp4: a text slide; the stroke appears when \"honed\" is spoken.\n"
        "emphasis_frame.png: the stroke under that word.\n",
        encoding="utf-8")
    jobs = [
        ("article", SAMPLES / "article_slide.mp4", SAMPLES / "article_frame.png", 2.3),
        ("emphasis", SAMPLES / "emphasis_underline.mp4", SAMPLES / "emphasis_frame.png", 1.7),
    ]
    exe = xv.find_chrome()

    async def movie(kind, mp4, png, still_at):
        page, duration, _image = _page(xv, kind)
        html = SAMPLES / f"_{kind}.html"
        html.write_text(page, encoding="utf-8")
        proc = subprocess.Popen(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "image2pipe", "-framerate", "30",
             "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(mp4)],
            stdin=subprocess.PIPE)
        async with xv._Chrome(*exe) as chrome:
            await chrome.open(html, 1.0, transparent=False)
            frames = int(round(duration * 30))
            still = None
            for frame in range(frames):
                t = frame / 30
                blob = await chrome.frame(t)
                proc.stdin.write(blob)
                if still is None and t >= still_at:
                    still = blob
            if still:
                png.write_bytes(still)
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed for {mp4.name}")
        html.unlink(missing_ok=True)

    for kind, mp4, png, still_at in jobs:
        asyncio.run(movie(kind, mp4, png, still_at))
        print(f"wrote {mp4.name} ({mp4.stat().st_size} bytes) and {png.name}")


def check_ui(app: str) -> None:
    html = (ROOT / app / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'data-pane="articles"' in html
    assert "xvArticlePaste" in html and "xvEmphasisGlobal" in html
    assert 'id="xvEmphasis"' in html and 'id="xvBookends"' in html and "xv-gap" in html
    js = (ROOT / app / "static" / "explainer" / "runtime.js").read_text(encoding="utf-8")
    assert "placeArticle" in js and "placeEmphasis" in js
    assert "textDecoration" not in js


def main() -> None:
    for app in APPS:
        mod = load_articles(app.replace("-", "_"), app)
        check_lines(mod)
        check_timing(mod)
        check_emphasis(mod)
        print(f"PASS  {app} line matching, emphasis, timing")
    xv = load_video("smoke", APPS[0])
    check_page_config(xv)
    check_smoke(xv)
    for app in APPS:
        check_ui(app)
    if os.environ.get("WRITE_ARTICLE_SAMPLES") == "1" or not (SAMPLES / "article_slide.mp4").is_file():
        try:
            from PIL import Image  # noqa: F401
            if xv.find_chrome():
                write_samples(xv)
        except Exception as exc:
            print(f"samples not written: {exc}")
    print("PASS  article lines, emphasis detection, underline timing, render smoke")


if __name__ == "__main__":
    main()
