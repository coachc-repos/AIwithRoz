"""A slide the user took the presenter off fills the frame again.

Claude lays a presenter slide out around the presenter (everything in one
half). When the user picks "No presenter" on that slide, the compiled slide
gets data-refit="1" and the runtime scales what is drawn up, centred in the
safe area. A slide that already fills the frame is left as it is.

Run: python tests/test_slide_refit.py
"""
import asyncio
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import explainer_video as xv  # noqa: E402


def check_mark() -> None:
    raw = ('<section id="s01" data-at="a" data-kind="slide"><p>x</p></section>'
           '<section id="s02" data-at="b" data-kind="slide" data-host="left"><p>y</p></section>'
           '<section id="s03" data-at="c" data-kind="slide"><p>z</p></section>')
    out = xv.mark_refit(raw, {"s01": {"host": "none"}, "s02": {"host": "none"}, "s03": {"host": "pip:monitor"}})
    assert '<section id="s01" data-at="a" data-kind="slide" data-refit="1">' in out
    assert 'data-host="left"><p>y' in out and out.count("data-refit") == 1   # an explicit presenter wins
    assert xv.mark_refit(raw, {}) == raw and xv.mark_refit(raw, None) == raw


def _page(sections: str, slides: list) -> str:
    comp = {"html": sections, "slides": slides, "duration": 8, "start": 0, "end": 8,
            "sections": [], "host_windows": [], "host_sections": []}
    return xv.page_html(comp, mode="render", visual={"style": "classic"})


def _red_box(png: bytes):
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGB")
    xs, ys = [], []
    for y in range(0, im.height, 4):
        for x in range(0, im.width, 4):
            r, g, b = im.getpixel((x, y))
            if r > 200 and g < 60 and b < 60:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def check_render() -> None:
    chrome = xv.find_chrome()
    if not chrome:
        print("SKIP  render check: no Chrome")
        return
    box = ('<div style="position:absolute; left:1000px; top:200px; width:700px; height:300px; '
           'background:#ff0000; border-radius:12px;"></div>')
    secs = (f'<section class="slide kind-slide" id="s1" data-kind="slide" data-t0="0" data-t1="4" data-sidx="0" '
            f'data-slabel="" data-hud="off" data-transition="cut" data-tracker="" data-refit="1">{box}</section>'
            f'<section class="slide kind-slide" id="s2" data-kind="slide" data-t0="4" data-t1="8" data-sidx="0" '
            f'data-slabel="" data-hud="off" data-transition="cut" data-tracker="">{box}</section>')
    slides = [{"id": "s1", "t0": 0, "t1": 4, "kind": "slide"}, {"id": "s2", "t0": 4, "t1": 8, "kind": "slide"}]
    page = Path("/tmp") / "xv_refit_check.html"
    page.write_text(_page(secs, slides), encoding="utf-8")

    async def shoot():
        async with xv._Chrome(*chrome) as ch:
            await ch.open(page, 1.0, transparent=False)
            return await ch.frame(2.0), await ch.frame(6.0)

    fitted, plain = asyncio.run(shoot())
    a, b = _red_box(fitted), _red_box(plain)
    assert a and b, (a, b)
    # Without data-refit the box stays where Claude put it.
    assert abs(b[0] - 1000) <= 8 and abs(b[2] - 1700) <= 8, b
    # With it, the box is larger and centred in the safe area (x 120-1800, y 110-990).
    w, h = a[2] - a[0], a[3] - a[1]
    assert w > 1000 and abs((a[0] + a[2]) / 2 - 960) <= 12, a
    assert abs((a[1] + a[3]) / 2 - 550) <= 12 and a[0] >= 110 and a[2] <= 1810, a
    assert abs(w / h - 700 / 300) < 0.1, (w, h)


def main() -> None:
    check_mark()
    check_render()
    print("PASS  a slide the user took the presenter off is scaled up and centred; others stay as laid out")


if __name__ == "__main__":
    main()
