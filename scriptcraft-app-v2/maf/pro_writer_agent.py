"""
MAF migration — Step 2A.

Brings the code-side single-pass "Pro" script writer into the agentic
architecture as a first-class Microsoft Agent Framework agent.

Today that writer lives in linedrive_azure/agents/pro_script_writer.py and calls
the Anthropic SDK directly. Here we keep the EXACT same proven system prompt and
GOLDEN REFERENCE, but run it as a MAF `Agent` whose model (`claude-opus-5-5`) is
served through the Foundry project via `FoundryChatClient`. That makes it part of
the MAF orchestration graph, versioned in code, and traceable in Foundry — no
separate Anthropic key, no bespoke streaming loop.

Does NOT touch web_gui.py. Runs in the isolated maf/.venv.

Run:
    maf/.venv/bin/python maf/pro_writer_agent.py "Top 10 AI Tools, and When NOT to Use Them" \
        --brief "Practical countdown for busy professionals; punchy, specific, 2026 examples."
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient

from observability import PROJECT_ENDPOINT, load_env, make_credential, setup_tracing

MODEL = os.environ.get("MAF_PRO_WRITER_MODEL", "claude-opus-5-5")
# A full script (hook + chapters + production blocks + cheat sheet) is long;
# give the model plenty of room so it is never truncated.
MAX_TOKENS = int(os.environ.get("MAF_PRO_WRITER_MAX_TOKENS", "32000"))


def _load_pro_writer_prompt():
    """Load SCRIPT_WRITER_PRO_SYSTEM + load_golden_reference from the app's
    pro_script_writer.py as the single source of truth, WITHOUT importing the
    linedrive_azure package (which pulls app-only deps). The module has no
    relative imports, so it loads standalone and its __file__ still resolves the
    golden_reference_script.md path correctly."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "linedrive_azure", "agents", "pro_script_writer.py")
    spec = importlib.util.spec_from_file_location("_pro_script_writer_src", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.SCRIPT_WRITER_PRO_SYSTEM, mod.load_golden_reference


def build_user_message(title: str, brief: str, load_golden_reference) -> str:
    """Mirror pro_script_writer.write_pro_script's prompt composition exactly."""
    _brief = (brief.strip() if brief and brief.strip()
              else "(no brief provided — infer a strong, specific angle "
                   "from the title)")
    golden = load_golden_reference()
    ref_block = ""
    if golden:
        ref_block = (
            "\n\nGOLDEN REFERENCE — the approved example of a great script. "
            "MATCH its shape and spoken voice EXACTLY: the FINAL HOOK, the "
            "'Heading: Chapter N -' lines, the alternating [PRODUCTION BEGIN] / "
            "[GROK IMAGINE / RESOLVE] / [PRODUCTION END] blocks, the VERIFY "
            "block for any legal or numeric claim, the [PROMPT OVERLAY] cheat "
            "sheet in the final chapter, and the trailing '=== …===' reference "
            "sections. Do NOT copy its topic, its tools, or its wording — only "
            "its structure, conventions, and voice.\n\n"
            f"<golden_reference>\n{golden}\n</golden_reference>"
        )
    return (
        f"TITLE: {title}\n\n"
        f"BRIEF:\n{_brief}"
        f"{ref_block}\n\n"
        "Write the complete script now, following your system instructions and "
        "matching the GOLDEN REFERENCE structure and voice exactly."
    )


def build_agent(instructions: str) -> Agent:
    """The single-pass Pro writer as a MAF agent backed by Foundry/Claude."""
    client = FoundryChatClient(
        project_endpoint=PROJECT_ENDPOINT,
        model=MODEL,
        credential=make_credential(),
    )
    return Agent(
        client=client,
        name="Pro-Script-Writer",
        instructions=instructions,
        default_options={"max_tokens": MAX_TOKENS},
    )


async def write_pro_script(title: str, brief: str = "") -> str:
    instructions, load_golden_reference = _load_pro_writer_prompt()
    agent = build_agent(instructions)
    user = build_user_message(title, brief, load_golden_reference)
    resp = await agent.run(user)
    return (resp.text or "").strip()


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description="MAF single-pass Pro script writer (Foundry/Claude).")
    ap.add_argument("title", help="Video title")
    ap.add_argument("--brief", default="", help="Short brief / angle (optional)")
    args = ap.parse_args()

    status = setup_tracing()
    print("ScriptCraft MAF — Pro Script Writer (single pass) via Microsoft Agent Framework")
    print(f"project : {PROJECT_ENDPOINT}")
    print(f"model   : {MODEL} (via FoundryChatClient)  max_tokens={MAX_TOKENS}")
    print(f"tracing : {status}")
    print(f"title   : {args.title}\n")

    script = asyncio.run(write_pro_script(args.title, args.brief))
    print(f"(writer returned {len(script)} chars)\n")
    print(script or "(empty response)")


if __name__ == "__main__":
    main()
