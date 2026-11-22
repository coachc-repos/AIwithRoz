"""Brand detection and logo caching. The network is a stand-in, never a live call."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import explainer_brands as eb
import explainer_video as ev

_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0h24v24H0z"/></svg>'


def test_brands_are_found_in_any_script_and_short_names_stay_whole_words():
    text = "Microsoft Copilot sits next to Microsoft. ChatGPT and Nvidia too, not an extra mark."
    keys = [b["key"] for b in eb.brands_in_text(text)]
    assert keys == ["microsoft-copilot", "microsoft", "chatgpt", "nvidia"]
    assert eb.brands_in_text("nothing about a company here") == []
    assert [b["key"] for b in eb.brands_in_text("On X today")] == ["x"]


def test_a_missing_logo_is_a_monogram_we_draw():
    svg = eb.monogram_svg("Nvidia", "#76b900")
    assert ">N<" in svg and "#76b900" in svg
    assert "simpleicons" not in svg and "cdn." not in svg
    assert eb.tint_icon("<svg viewBox='0 0 24 24'></svg>", "#76b900").startswith('<svg fill="#76b900"')
    assert eb.tint_icon("<script>alert(1)</script>", "#fff") == ""
    assert eb.fetch_icon("not a slug") == ""


def test_download_is_cached_and_an_upload_wins(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    project = ev.open_project(folder)
    calls = {"n": 0}

    def opener(url):
        calls["n"] += 1
        assert url.endswith("/nvidia.svg")
        return _SVG

    found = eb.ensure_brand_logos(project, ["Nvidia ships the chips."], opener=opener)
    assert [b["key"] for b in found] == ["nvidia"]
    assert calls["n"] == 1
    saved = (project.dir / "logos" / "nvidia.svg").read_text(encoding="utf-8")
    assert saved.startswith('<svg fill="#76b900"')
    assert project.data["logos"]["nvidia"]["source"] == "simpleicons"
    eb.ensure_brand_logos(project, ["Nvidia ships the chips."], opener=opener)
    assert calls["n"] == 1

    project.data["logos"]["nvidia"]["source"] = "my-nvidia.svg"
    (project.dir / "logos" / "nvidia.svg").write_text("<svg id='mine'/>", encoding="utf-8")
    eb.ensure_brand_logos(project, ["Nvidia again"], opener=opener)
    assert calls["n"] == 1
    assert "mine" in (project.dir / "logos" / "nvidia.svg").read_text(encoding="utf-8")


def test_a_failed_download_leaves_the_monogram_path(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    project = ev.open_project(folder)

    def opener(_url):
        raise OSError("offline")

    eb.ensure_brand_logos(project, ["Tesla and YouTube"], opener=opener)
    assert project.data["logos"] == {}
    listed = {b["key"]: b["has_file"] for b in project.data["brands"]}
    assert listed == {"tesla": False, "youtube": False}
    assert "T" in eb.monogram_svg("Tesla", "#cc0000")
