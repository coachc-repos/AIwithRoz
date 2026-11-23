"""The layout check flags real crowding and leaves deliberate designs alone.

- A lit copy of a row drawn exactly over a dim one is a highlight, not an overlap.
- Punctuation beside its word ("down?") is not crowding.
- Text that runs out of its card, or sits on top of the next line, is flagged.

Run: python tests/test_layout_check.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import explainer_video as xv  # noqa: E402

CARD = ("position:absolute; width:520px; box-sizing:border-box; padding:24px 28px; background:#121824; "
        "border:2px solid #2a3446; border-radius:16px; font-size:40px; font-weight:700; color:#f2f4f8;")


def _slide(sid: str, t0: float, inner: str) -> str:
    return (f'<section class="slide kind-slide" id="{sid}" data-kind="slide" data-t0="{t0}" data-t1="{t0 + 4}" '
            f'data-sidx="0" data-slabel="" data-hud="off" data-transition="cut" data-tracker="">{inner}</section>')


def main() -> None:
    chrome = xv.find_chrome()
    if not chrome:
        print("SKIP  layout check: no Chrome")
        return
    ok = (
        # a dim ladder with a lit copy on top, and a word with its question mark split by the words animation
        f'<div style="{CARD} left:200px; top:200px;"><span>7</span> <span>IDEA</span></div>'
        f'<div style="{CARD} left:200px; top:200px; background:#1b2a4a;"><span>7</span> <span>IDEA</span></div>'
        '<h2 style="position:absolute; left:900px; top:200px; font-size:64px;" data-anim="words">'
        'How far down is <span style="color:#f5b83d">down</span>?</h2>'
        f'<div style="{CARD} left:900px; top:500px;"><div style="font-size:24px; color:#8a94a6;">SOURCE</div>'
        '<div>Elon Musk, public posts</div></div>'
    )
    bad = (
        # text hanging out of the bottom of its card, and a label jammed onto the line under it
        f'<div style="{CARD} left:200px; top:200px; height:90px; padding:0 28px;"><div style="margin-top:70px;">Squeezed</div></div>'
        '<div style="position:absolute; left:900px; top:200px; font-size:40px; line-height:40px;">RELEASED BY</div>'
        '<div style="position:absolute; left:900px; top:226px; font-size:40px; line-height:40px;">Grok Bot 1.0</div>'
    )
    html = _slide("ok", 0, ok) + _slide("bad", 4, bad)
    comp = {"html": html, "slides": [{"id": "ok", "t0": 0, "t1": 4, "kind": "slide"}, {"id": "bad", "t0": 4, "t1": 8, "kind": "slide"}],
            "duration": 8, "start": 0, "end": 8, "sections": [], "host_windows": [], "host_sections": []}
    page = Path("/tmp") / "xv_layout_check.html"
    page.write_text(xv.page_html(comp, mode="render", visual={"style": "classic"}), encoding="utf-8")

    async def run():
        async with xv._Chrome(*chrome) as ch:
            await ch.open(page, 1.0, transparent=False)
            return await ch.evaluate("JSON.stringify(window.__check())")

    import json
    found = {x["id"]: x["issues"] for x in json.loads(asyncio.run(run()))}
    assert "ok" not in found, found.get("ok")
    issues = " | ".join(found.get("bad") or [])
    assert "“Squeezed” runs outside its box" in issues, issues
    assert "almost touches" in issues or "overlaps" in issues, issues
    print("PASS  the layout check flags crowding, not highlights or punctuation")


if __name__ == "__main__":
    main()
