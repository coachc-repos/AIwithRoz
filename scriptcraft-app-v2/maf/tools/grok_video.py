"""
MAF migration — Step 2B.

Wraps Grok Imagine video generation as a Microsoft Agent Framework *function
tool*. A video generator is a specialized media API, not a chat agent, so in an
agentic architecture it belongs as a TOOL that an agent decides to call — not as
an agent of its own.

`generate_grok_video(...)` mirrors the app's real call
(web_gui.py:grok_test_video_generate -> xai_sdk .video.generate(
model="grok-imagine-video")). It renders for real when MAF_GROK_LIVE=1 and an
xAI key is present; otherwise it returns a structured dry-run result so the
agentic tool-call loop is testable without spending a render.

Does NOT touch web_gui.py. Runs in the isolated maf/.venv.

Demo (an agent discovers and calls the tool):
    maf/.venv/bin/python maf/tools/grok_video.py "a sleek dark desk with seven glowing AI tool icons"
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
from pathlib import Path

# Put maf/ on the path so we can reuse the shared helpers when run as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import Agent  # noqa: E402
from agent_framework.foundry import FoundryChatClient  # noqa: E402

from observability import PROJECT_ENDPOINT, load_env, make_credential, setup_tracing  # noqa: E402


def generate_grok_video(
    prompt: str,
    aspect_ratio: str = "16:9",
    duration_seconds: int = 6,
    resolution: str = "480p",
) -> dict:
    """Generate one short (~4-6s) SILENT b-roll video clip from a text prompt
    using xAI Grok Imagine (grok-imagine-video), save it locally, and return its
    path and source URL. Use this whenever a script beat needs a b-roll clip.

    Args:
        prompt: A complete, self-contained cinematic visual description of the
            clip (no audio, no on-screen text, no people/faces/hands).
        aspect_ratio: "16:9" (default) or "9:16".
        duration_seconds: Clip length in seconds, 1-15 (default 6).
        resolution: "480p" (default) or "720p".

    Returns:
        A dict describing the result (status "ok" with filename/path/source_url
        when rendered live, or status "dry_run" otherwise).
    """
    duration = max(1, min(15, int(duration_seconds)))
    key = (os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY") or "").strip()
    live = os.getenv("MAF_GROK_LIVE", "").strip().lower() in ("1", "true", "yes")

    print(f"   [tool] generate_grok_video called "
          f"(live={live and bool(key)}, {duration}s, {aspect_ratio}, {resolution})",
          file=sys.stderr)

    if not (live and key):
        return {
            "status": "dry_run",
            "model": "grok-imagine-video",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "duration_seconds": duration,
            "resolution": resolution,
            "note": "Dry run — set MAF_GROK_LIVE=1 and XAI_API_KEY to render for real.",
        }

    try:
        import certifi
        import requests
        import xai_sdk
    except Exception as e:  # pragma: no cover
        return {"status": "error",
                "error": f"xai_sdk/certifi/requests not installed in this venv: {e}"}

    client = xai_sdk.Client(api_key=key)
    resp = client.video.generate(
        prompt=prompt,
        model="grok-imagine-video",
        duration=duration,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
    )
    out_dir = Path.home() / "Dev" / "brollvideos"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() else "_" for c in prompt)[:40].strip("_") or "grok_video"
    path = out_dir / f"grok_{ts}_{safe}.mp4"
    with requests.get(resp.url, stream=True, timeout=180, verify=certifi.where()) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    return {
        "status": "ok",
        "filename": path.name,
        "path": str(path),
        "source_url": resp.url,
        "model": "grok-imagine-video",
        "duration_seconds": getattr(resp, "duration", duration),
    }


def build_broll_director() -> Agent:
    """A tiny MAF agent that has the Grok video tool and decides when to call it."""
    return Agent(
        client=FoundryChatClient(
            project_endpoint=PROJECT_ENDPOINT,
            model="claude-opus-5-5",
            credential=make_credential(),
        ),
        name="B-Roll-Director",
        instructions=(
            "You create b-roll for video scripts. When the user describes a beat, "
            "call generate_grok_video with a single complete cinematic prompt "
            "(silent, no on-screen text, no people/faces/hands). After the tool "
            "returns, confirm in one sentence what was generated."
        ),
        tools=[generate_grok_video],
    )


async def _demo(beat: str) -> str:
    agent = build_broll_director()
    resp = await agent.run(f"Make a short b-roll clip for this beat: {beat}")
    return (resp.text or "").strip()


def main() -> None:
    load_env()
    beat = " ".join(sys.argv[1:]).strip() or "a sleek dark executive desk with glowing AI tool icons"
    status = setup_tracing()
    print("ScriptCraft MAF — Grok video as a function tool (agent decides to call it)")
    print(f"project : {PROJECT_ENDPOINT}")
    print(f"tracing : {status}")
    live = os.getenv("MAF_GROK_LIVE", "").strip().lower() in ("1", "true", "yes")
    print(f"render  : {'LIVE (real Grok render)' if live else 'dry-run (set MAF_GROK_LIVE=1 + XAI_API_KEY to render)'}")
    print(f"beat    : {beat}\n")
    print(asyncio.run(_demo(beat)))


if __name__ == "__main__":
    main()
