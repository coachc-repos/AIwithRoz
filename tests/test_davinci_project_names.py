"""Smoke tests for Resolve helpers that do not need DaVinci Resolve installed."""

from pathlib import Path

from loadutil import load_module

davinci = load_module(
    "scriptcraft_davinci_resolve_api",
    "scriptcraft-app-v2/davinci_resolve_api.py",
)


def test_sanitize_project_name():
    assert davinci.sanitize_project_name("Hello: World!") == "Hello_World"
    assert davinci.sanitize_project_name("") == "AI_Video_Project"
    assert davinci.sanitize_project_name("a" * 80) == "a" * 50


def test_collect_media_paths_sorts_and_filters(tmp_path):
    folder = tmp_path / "media"
    nested = folder / "sub"
    nested.mkdir(parents=True)
    (folder / "b.mp4").write_bytes(b"b")
    (folder / "a.MP4").write_bytes(b"a")
    (folder / "note.txt").write_text("skip", encoding="utf-8")
    (nested / "c.mov").write_bytes(b"c")

    paths = davinci._collect_media_paths(folder, [".mp4", ".mov"])
    assert [Path(path).name for path in paths] == ["a.MP4", "b.mp4", "c.mov"]
    assert davinci._collect_media_paths(None, [".mp4"]) == []
    assert davinci._collect_media_paths(folder / "missing", [".mp4"]) == []
