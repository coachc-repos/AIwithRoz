"""Presenter screen-time default for the explainer's first plan.

The plan asks for a share of runtime (screen time), not a share of slides.
No HeyGen, Claude, or network calls.

    python scriptcraft-app-v3/tests/test_host_share_default.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPS = ("scriptcraft-app-v3", "scriptcraft-app-v3-container")


def load(name: str, app: str):
    path = ROOT / app / "explainer_video.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def check_module(xv, app: str) -> None:
    assert xv.HOST_DEFAULT_SHARE == "brief", app
    assert xv.HOST_SHARES == {"mine": 0, "brief": 10, "little": 15, "some": 30, "lots": 50}, app
    assert xv.HOST_SHARES[xv.HOST_DEFAULT_SHARE] == 10, app
    # Saved keys keep the percentages they had before the 10% default.
    assert xv.host_share_pct("little") == 15
    assert xv.host_share_pct("some") == 30
    assert xv.host_share_pct("lots") == 50
    assert xv.host_share_pct("mine") == 0

    # No choice, and no saved share: the default.
    assert xv.host_share_key(None, None) == "brief"
    assert xv.host_share_key("", None) == "brief"
    assert xv.host_share_key("nope", None) == "brief"
    assert xv.host_share_pct(None) == 10

    # An explicit choice beats a saved share. A saved share beats the default.
    assert xv.host_share_key("some", "brief") == "some"
    assert xv.host_share_key("lots", "some") == "lots"
    assert xv.host_share_key(None, "some") == "some"
    assert xv.host_share_key("nope", "little") == "little"
    assert xv.host_share_key("", "lots") == "lots"
    # A planned HeyGen presenter (clips made after the storyboard) gets the same default.
    assert xv.planned_host()["share"] == "brief" and xv.planned_host("lots")["share"] == "lots", app

    unset = xv._host_guide({"parts": [1]})
    assert "about 10% of the runtime" in unset, unset
    assert "opening line" in unset
    assert "screen time" in unset
    assert "drop later items before going much past 10%" in unset
    # The opening is the first place to spend the budget, not extra time on top of it.
    assert unset.index("opening line") < unset.index("sign-off")

    chosen = xv._host_guide({"share": "some", "parts": [1]})
    assert "about 30% of the runtime" in chosen, chosen
    assert "about 10%" not in chosen
    assert "about 50% of the runtime" in xv._host_guide({"share": "lots"})
    assert "about 15% of the runtime" in xv._host_guide({"share": "little"})
    assert "about 10% of the runtime" in xv._host_guide({"share": "brief"})

    # "Only where I put it" stays a user-placement rule, not the 10% budget.
    mine = xv._host_guide({"share": "mine", "parts": [1]})
    assert "user places the presenter themselves" in mine
    assert "about 10%" not in mine
    assert xv._host_guide(None).startswith("- host: none on every slide (no presenter video).")

    # The first plan and the "rest of the video" plan both use this guide.
    task = xv._plan_task(600.0, {}, {"parts": [1]})
    assert "about 10% of the runtime" in task
    assert "opening line" in task
    override = xv._plan_task(600.0, {}, {"share": "some"})
    assert "about 30% of the runtime" in override
    assert "about 10%" not in override
    assert "_host_guide(host)" in Path(xv.__file__).read_text(encoding="utf-8").split("def extend(", 1)[1].split("\ndef ", 1)[0]

    # A section the user placed is composited even though the plan budget is 10%.
    # compile_composition does not take the share; the section is not trimmed to it.
    words = [
        {"text": "Hello there markets", "start": 0.0, "end": 2.0},
        {"text": "are moving today", "start": 2.2, "end": 5.0},
    ]
    timeline = xv.Timeline(words, 20.0)
    raw = '<section id="s01" data-at="Hello there markets" data-kind="slide"><h1>Hello</h1></section>'
    comp = xv.compile_composition(
        raw, timeline, duration=20.0, plan={"slides": [], "sections": []},
        logos={}, values={}, logo_choices={}, host_on=True,
        host_sections=[{"t0": 1.0, "t1": 4.0, "layout": "full"}])
    assert comp["host_sections"] == [{"t0": 1.0, "t1": 4.0, "layout": "full"}], comp["host_sections"]
    assert any(w["layout"] == "full" and w["t0"] <= 1.0 and w["t1"] >= 4.0 for w in comp["host_windows"]), comp["host_windows"]


def check_copies(local, container) -> None:
    assert local.HOST_SHARES == container.HOST_SHARES
    assert local.HOST_DEFAULT_SHARE == container.HOST_DEFAULT_SHARE
    for host in (None, {}, {"share": "mine"}, {"share": "brief"}, {"share": "some"}, {"share": "lots"}):
        assert local._host_guide(host) == container._host_guide(host), host


def check_ui(app: str) -> None:
    html = (ROOT / app / "templates" / "index.html").read_text(encoding="utf-8")
    start = html.split('id="xvHostShare"', 1)[1].split("</select>", 1)[0]
    assert 'value="brief" selected' in start, app
    assert 'value="some" selected' not in start, app
    assert 'on screen briefly (~10%)' in start
    assert 'on screen some (~30%)' in start
    assert "brief|Briefly (~10%)" in html
    assert "some|Some (~30%)" in html
    assert "(h.share || 'brief')" in html
    gui = (ROOT / app / "web_gui.py").read_text(encoding="utf-8")
    assert 'share = _xv.host_share_key(data.get("share"))' in gui
    assert 'share = _xv.host_share_key(data.get("share_new"), (host or {}).get("share"))' in gui
    assert 'in _xv.HOST_SHARES else "some"' not in gui
    assert '.get("share", "some")' not in gui


def main() -> None:
    local = load("explainer_video_v3", APPS[0])
    container = load("explainer_video_v3_container", APPS[1])
    check_module(local, APPS[0])
    check_module(container, APPS[1])
    check_copies(local, container)
    for app in APPS:
        check_ui(app)
    print("PASS  host share default is 10% of runtime; an explicit or saved share still overrides it")


if __name__ == "__main__":
    main()
