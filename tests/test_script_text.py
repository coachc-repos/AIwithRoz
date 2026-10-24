"""Smoke tests for script text cleanup used by ScriptCraft and HeyGen."""

from loadutil import load_module

text = load_module(
    "scriptcraft_v2_text_processing",
    "scriptcraft-app-v2/console_ui/text_processing.py",
)


def test_teleprompter_drops_cues_and_production_notes():
    script = """Welcome to the show.

[Visual Cue: zoom on host]
This is the spoken line.

**Tool Demo:** click the button

## PRODUCTION NOTES
Do not read this on camera.

# Next Chapter
Read this too.
"""
    spoken = text.extract_teleprompter_text(script)
    assert "Welcome to the show." in spoken
    assert "This is the spoken line." in spoken
    assert "Read this too." in spoken
    assert "zoom on host" not in spoken
    assert "click the button" not in spoken
    assert "Do not read this on camera." not in spoken


def test_heygen_host_script_keeps_only_spoken_lines():
    script = """# Opening

Host:
Hello from the host.

[Visual Cue: cutaway]
Still talking to the camera.

## PRODUCTION NOTES
Secret producer note.

# Later

Host: One more line for the avatar.
"""
    spoken = text.extract_heygen_host_script(script)
    assert "Hello from the host." in spoken
    assert "Still talking to the camera." in spoken
    assert "One more line for the avatar." in spoken
    assert "cutaway" not in spoken
    assert "Secret producer note" not in spoken


def test_scrub_heygen_text_strips_metadata_and_keeps_dialogue():
    raw = """Title: My Video
Heading: Chapter One
Hello there.
Visual Cue: zoom in
**FINAL HOOK:** Don't miss this.
Summary: The real takeaway.
"""
    cleaned = text.scrub_heygen_text(raw)
    assert cleaned == "Hello there."
    assert text.scrub_heygen_text("") == ""
    assert text.scrub_heygen_text("Plain spoken sentence.") == "Plain spoken sentence."


def test_heygen_curl_text_splits_heading_chapters_without_calling_api():
    bar = "=" * 70
    script = (
        "# 🎬 HEYGEN READY SCRIPT\n"
        f"{bar}\n"
        "Heading: Opening Beat\n"
        "The host says hello to the audience. Then the host waves.\n"
        "\n"
        "Visual Cue: wide shot of the field\n"
        "\n"
        "Heading: Closing Beat\n"
        "The host says goodbye. Then the host thanks everyone.\n"
    )
    curls = text.generate_heygen_curl_commands(
        script,
        "Weekend Lineup Tips",
        api_key="ci-placeholder",
        template_id="ci-template",
    )
    assert "ci-placeholder" in curls
    assert "ci-template" in curls
    assert "-Ch1p1" in curls
    assert "-Ch2p1" in curls
    assert "hello to the audience." in curls
    assert "thanks everyone." in curls
    assert "wide shot of the field" not in curls
    assert text.generate_heygen_curl_commands("no heygen section", "Untitled") == ""


def test_heygen_curl_text_splits_chapter_heading_lines():
    bar = "=" * 70
    script = (
        "# 🎬 HEYGEN READY SCRIPT\n"
        f"{bar}\n"
        "Chapter 1 - First Idea\n"
        "This is the first spoken chapter. It stays in chapter one.\n"
        "\n"
        "Chapter 2 - Second Idea\n"
        "This is the second spoken chapter. It stays in chapter two.\n"
    )
    curls = text.generate_heygen_curl_commands(
        script,
        "Practice Plan",
        api_key="ci-placeholder",
        template_id="ci-template",
    )
    assert "-Ch1p1" in curls
    assert "-Ch2p1" in curls
    assert "first spoken chapter." in curls
    assert "second spoken chapter." in curls


def test_tool_links_demo_steps_and_bold_tool_names():
    links = text.extract_tool_links_and_info(
        "See ChatGPT **URL**: https://chat.openai.com/ for the demo"
    )
    assert "https://chat.openai.com/" in links
    assert "ChatGPT" in links
    assert "No specific tools" in text.extract_tool_links_and_info("just words")

    plain = text.format_demo_steps_plain("1. Open the app\n- Click start\n• Save")
    assert plain == "Open the app\nClick start\nSave"

    bold = text.enhance_script_with_bold_tools("Try ChatGPT today.")
    assert "**ChatGPT**" in bold
