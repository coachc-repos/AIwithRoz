"""Script-Writer-Pro-Agent as code: the single-pass Pro script writer.

The app's classic Pro writer (scriptcraft-app-v3/linedrive_azure/agents/
pro_script_writer.py) calls Anthropic's API directly. This agent runs the same
prompt on the Foundry deployment so it can be hosted like the other agents and
compared side by side in the v3 GUI:

- Instructions: SCRIPT_WRITER_PRO_SYSTEM, copied verbatim into
  ../agent_instructions/Script-Writer-Pro-Agent.md (an offline check keeps the
  two identical).
- Request: the app sends the same user message as the classic writer (title,
  brief, and the golden reference), built by pro_script_writer.build_pro_user_message.
- Model settings: claude-opus-5-5, reasoning effort "high", 48,000 max tokens.
  The classic writer asks Anthropic for effort "high" with adaptive thinking.

It uses the same Foundry Responses path as the other agents. The Responses
`reasoning` option sets Claude's effort there: on a short prompt, effort low,
default, and high gave 170, 257, and 312 output tokens (2026-10-08). MAF's
Anthropic connector (AnthropicFoundryClient) also works locally, but the hosted
agent's identity gets 401 on POST /anthropic/v1/* without an extra role
assignment, so this agent does not use it.
"""
from __future__ import annotations

import os

from agent_framework import Agent

from agents._common import CLAUDE_MODEL, FoundryClaudeChatClient, load_instructions
from observability import PROJECT_ENDPOINT, make_credential

AGENT_NAME = "Script-Writer-Pro-Agent"
MAX_TOKENS = int(os.environ.get("MAF_PRO_MAX_TOKENS", "48000"))
EFFORT = os.environ.get("MAF_PRO_EFFORT", "high")


def build_code_agent(credential=None) -> Agent:
    return Agent(
        client=FoundryClaudeChatClient(
            project_endpoint=PROJECT_ENDPOINT,
            model=CLAUDE_MODEL,
            credential=credential or make_credential(),
        ),
        name=AGENT_NAME,
        instructions=load_instructions(AGENT_NAME),
        default_options={"max_tokens": MAX_TOKENS, "reasoning": {"effort": EFFORT}},
    )


# --------------------------------------------------------------------------- #
# Keep the hosted agent's instructions identical to the app's Pro prompt.
#   maf/.venv/bin/python -m agents.pro_writer --sync   (run from maf/)
# --------------------------------------------------------------------------- #
_MAF = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_PRO_WRITER = os.path.join(os.path.dirname(os.path.dirname(_MAF)), "scriptcraft-app-v3",
                              "linedrive_azure", "agents", "pro_script_writer.py")
INSTRUCTIONS_FILE = os.path.join(os.path.dirname(_MAF), "agent_instructions", f"{AGENT_NAME}.md")
_HEADER = """<!--
Script-Writer-Pro-Agent instructions, served by the hosted agent
Script-Writer-Pro-Agent-MAF (maf/agents/pro_writer.py).

Verbatim copy of SCRIPT_WRITER_PRO_SYSTEM in
scriptcraft-app-v3/linedrive_azure/agents/pro_script_writer.py, the prompt the
classic Pro writer sends to Anthropic directly. The app sends the golden
reference in the user message, as the classic writer does, so it is not here.
Do not edit by hand: change the app prompt, then run
    maf/.venv/bin/python -m agents.pro_writer --sync   (from maf/)
and redeploy the agent. maf/testing/offline_checks.py fails if the two differ.
-->

"""


def app_prompt() -> str:
    """SCRIPT_WRITER_PRO_SYSTEM from the v3 app, loaded without importing the app."""
    import importlib.util  # noqa: PLC0415
    spec = importlib.util.spec_from_file_location("_v3_pro_script_writer", APP_PRO_WRITER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SCRIPT_WRITER_PRO_SYSTEM.strip()


def sync_instructions() -> str:
    with open(INSTRUCTIONS_FILE, "w", encoding="utf-8") as f:
        f.write(_HEADER + app_prompt() + "\n")
    return INSTRUCTIONS_FILE


if __name__ == "__main__":
    import sys  # noqa: PLC0415
    if "--sync" in sys.argv:
        print("wrote", sync_instructions())
    else:
        print(__doc__)
