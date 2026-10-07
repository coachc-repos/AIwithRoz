"""
MAF migration — Step 3 (first portal->code conversion): B-Roll agent.

Re-creates the Foundry portal agent `Script-bRoll-Agent` as a CODE-DEFINED
Microsoft Agent Framework agent, seeded from its captured instructions
(../agent_instructions/Script-bRoll-Agent.md) and run on the same model
(claude-opus-5-5) via FoundryChatClient.

Why no web_search tool: the portal agent lists a `web_search` tool, but the GA
Foundry web-search tool is Azure-OpenAI-only (not Claude), and B-Roll generation
reads the PROVIDED script rather than the live web. So the code version omits it;
the `--compare` mode below confirms the output still matches the portal agent.

Validate side-by-side (does NOT delete the portal agent — retire that only after
you're satisfied):
    maf/.venv/bin/python maf/agents/broll.py --compare
    maf/.venv/bin/python maf/agents/broll.py --script-file path/to/script.md

Scoped to maf/, no web_gui.py changes, isolated venv.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import Agent  # noqa: E402

from agents._common import (  # noqa: E402
    build_code_agent as _build_agent,
    load_instructions as _load_instructions,
    run_portal as _run_portal,
    run_text,
)
from observability import PROJECT_ENDPOINT, load_env, make_credential, setup_tracing  # noqa: E402

AGENT_NAME = "Script-bRoll-Agent"   # the portal agent, called by name in --compare
MODEL = os.environ.get("MAF_BROLL_MODEL", "claude-opus-5-5")
MAX_TOKENS = int(os.environ.get("MAF_BROLL_MAX_TOKENS", "16000"))

# Short, self-contained sample used by --compare so the two tables are easy to
# diff. Replace with --script-file for a full-length check.
SAMPLE_TITLE = "Three AI Tools That Save You an Hour a Day"
SAMPLE_SCRIPT = """**Host:** Let us look at three AI tools that give you back an hour every day.

First, Superhuman. It triages your inbox, drafts replies in your voice, and lets you clear a hundred emails in ten minutes with keyboard shortcuts.

Second, Fathom. It joins your Zoom calls, records them, and writes the summary and action items before you have even left the meeting.

Third, Grammarly. It rewrites a clumsy paragraph into something clear and professional while you keep typing, right inside your email and your docs.

Use these three together and you reclaim a full hour, every single day."""


def load_instructions() -> str:
    """The captured portal instructions (capture-header comment stripped)."""
    return _load_instructions(AGENT_NAME)


def build_code_agent(credential=None) -> Agent:
    """The B-Roll agent defined in code (seeded from the captured instructions)."""
    return _build_agent(
        name="Script-bRoll-Agent (code)",
        instructions=load_instructions(),
        model=MODEL,
        max_tokens=MAX_TOKENS,
        credential=credential,
    )


def _user_message(script_text: str, title: str) -> str:
    return f"SCRIPT TITLE: {title}\n\nSCRIPT:\n{script_text}"


async def run_code(script_text: str, title: str, credential=None) -> str:
    return await run_text(build_code_agent(credential), _user_message(script_text, title), "code")


async def run_portal(script_text: str, title: str, credential=None) -> str:
    """The existing portal agent, called by name (the step-1 pattern)."""
    return await _run_portal(AGENT_NAME, _user_message(script_text, title), credential)


def _table_stats(md: str) -> dict:
    rows = [ln for ln in md.splitlines()
            if ln.strip().startswith("|") and "---" not in ln]
    # subtract a header row if present
    body = max(0, len(rows) - 1) if rows else 0
    return {
        "chars": len(md),
        "table_rows": body,
        "has_animation_section": "## Animation Suggestions" in md,
    }


async def _compare(script_text: str, title: str) -> None:
    # One shared credential, run sequentially — avoids two concurrent
    # `az` token fetches + connection setups (the transient DNS flake).
    cred = make_credential()
    print("Running CODE agent, then PORTAL agent, on the same script...\n")
    code_out = await run_code(script_text, title, cred)
    portal_out = await run_portal(script_text, title, cred)
    cs, ps = _table_stats(code_out), _table_stats(portal_out)
    print("================ COMPARISON ================")
    print(f"{'metric':<22}{'CODE':>12}{'PORTAL':>12}")
    for k in ("chars", "table_rows", "has_animation_section"):
        print(f"{k:<22}{str(cs[k]):>12}{str(ps[k]):>12}")
    print("============================================\n")
    print("----- CODE agent output (first 1600 chars) -----")
    print(code_out[:1600])
    print("\n----- PORTAL agent output (first 1600 chars) -----")
    print(portal_out[:1600])


def _read_script(args) -> tuple[str, str]:
    if args.script_file:
        with open(args.script_file, "r", encoding="utf-8") as f:
            text = f.read().strip()
        title = args.title or os.path.splitext(os.path.basename(args.script_file))[0]
        return text, title
    return SAMPLE_SCRIPT, (args.title or SAMPLE_TITLE)


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description="Code-defined B-Roll MAF agent (step 3).")
    ap.add_argument("--script-file", help="Path to a .md/.txt script (defaults to a built-in sample)")
    ap.add_argument("--title", default="", help="Script title")
    ap.add_argument("--compare", action="store_true",
                    help="Run BOTH the code agent and the portal agent and compare")
    args = ap.parse_args()

    status = setup_tracing()
    script_text, title = _read_script(args)
    print("ScriptCraft MAF — B-Roll agent (portal -> code conversion)")
    print(f"project : {PROJECT_ENDPOINT}")
    print(f"model   : {MODEL} (via FoundryChatClient)  max_tokens={MAX_TOKENS}")
    print(f"tracing : {status}")
    print(f"title   : {title}\n")

    if args.compare:
        asyncio.run(_compare(script_text, title))
    else:
        print(asyncio.run(run_code(script_text, title)))


if __name__ == "__main__":
    main()
