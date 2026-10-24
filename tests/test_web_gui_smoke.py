"""Smoke tests for ScriptCraft parsing helpers and the Flask app in-process.

Nothing here calls Azure, HeyGen, Gemini, Grok, or DaVinci Resolve.
"""

from loadutil import load_module

web = load_module("scriptcraft_web_gui", "scriptcraft-app-v2/web_gui.py")


def test_title_line_wins_over_chapter_headings():
    script = """Heading: Chapter 1
# Chapter 1
Title: The Real Title
"""
    assert web._extract_script_title_for_output(script) == "The Real Title"


def test_direct_video_and_skipped_chapter_h1():
    direct = "# Direct Video - Batter Up\nThe body of the script.\n"
    assert web._extract_script_title_for_output(direct) == "Batter Up"

    chapters = "# Chapter 1\n# How Pitchers Think\n"
    assert web._extract_script_title_for_output(chapters) == "How Pitchers Think"
    assert web._extract_script_title_for_output("") == "Untitled Script"


def test_safe_title_for_paths():
    assert web._safe_title_for_paths("Heading: My Big Script") == "My_Big_Script"
    assert web._safe_title_for_paths("Hello/World?") == "HelloWorld"
    assert web._safe_title_for_paths("") == "untitled_script"
    assert web._safe_title_for_paths(None) == "untitled_script"

    long_title = "word " * 40
    safe = web._safe_title_for_paths(long_title)
    assert " " not in safe
    assert len(safe) <= 80


def test_broll_table_and_animation_suggestions():
    script = """
intro line

| Timecode | Search Term | Description | Scene Context |
|----------|-------------|-------------|---------------|
| 00:00:05 | batter swing | slow motion swing | opening |

tail line
"""
    block = web._extract_broll_table_from_script(script)
    assert "batter swing" in block
    assert "intro line" not in block
    assert "tail line" not in block
    assert web._extract_broll_table_from_script("no table here") == ""

    suggestions = """
## Animation Suggestions
- AI hiding in apps: overlay glowing nodes
- A single idea without a colon

## Next
- ignore this bullet
"""
    rows = web._extract_animation_suggestion_rows(suggestions)
    assert len(rows) == 2
    assert rows[0]["search_term"] == "AI hiding in apps"
    assert rows[0]["description"] == "overlay glowing nodes"
    assert rows[0]["scene_context"] == "Animation Suggestion"
    assert rows[1]["search_term"] == "A single idea without a colon"
    assert web._extract_animation_suggestion_rows("no heading") == []

    markdown = web._animation_rows_to_markdown(rows)
    assert "AI hiding in apps" in markdown
    assert "Animation Suggestion" in markdown
    assert web._animation_rows_to_markdown([]) == ""


def test_emotion_label_from_thumbnail_filename():
    assert web._guess_emotion_from_filename("thumb_v2_shot.png") == "SHOCKED/SURPRISED"
    assert web._guess_emotion_from_filename("plain.png") == "EXISTING THUMBNAIL"


def test_home_page_and_agent_mode_api():
    client = web.app.test_client()
    home = client.get("/")
    assert home.status_code == 200
    assert f"ScriptCraft v{web.VERSION}" in home.get_data(as_text=True)

    current = client.get("/api/agent-mode")
    assert current.status_code == 200
    payload = current.get_json()
    assert payload["success"] is True
    assert payload["mode"] in ("v1", "v2")

    rejected = client.post("/api/agent-mode", json={"mode": "nope"})
    assert rejected.status_code == 400
    assert rejected.get_json()["success"] is False


def test_auth_gate_uses_the_configured_token(monkeypatch):
    monkeypatch.setattr(web, "APP_AUTH_TOKEN", "ci-test-token")
    client = web.app.test_client()

    denied = client.get("/api/agent-mode")
    assert denied.status_code == 401

    home = client.get("/")
    assert home.status_code == 302
    assert "/login" in home.headers["Location"]

    login = client.get("/login")
    assert login.status_code == 200

    allowed = client.get("/api/agent-mode", headers={"X-App-Token": "ci-test-token"})
    assert allowed.status_code == 200
    assert allowed.get_json()["success"] is True
