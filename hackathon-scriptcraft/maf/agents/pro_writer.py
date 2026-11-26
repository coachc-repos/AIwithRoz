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

Two Foundry endpoints can serve it; MAF_PRO_PATH picks one at build time:

- "responses": Foundry's OpenAI-style Responses endpoint on the
  project, like every other hosted agent. Foundry translates the request into a
  Claude call; the Responses `reasoning` option sets Claude's effort (effort
  low, default, and high gave 170, 257, and 312 output tokens on a short
  prompt, 2026-10-08).
- "anthropic" (default since 2026-10-08): Foundry's Anthropic Messages
  endpoint on the account, through MAF's AnthropicFoundryClient. Claude's
  native request, with effort "high" and adaptive thinking, exactly as the
  classic writer asks Anthropic. The hosted agent's identity holds the custom
  role "ScriptCraft Anthropic Model Caller" (one data action,
  Microsoft.CognitiveServices/accounts/AIServices/providers/action) on the
  account; without it every call fails with 401 and the v3 GUI falls back to
  the classic writer. Access took about 15 minutes to apply after the grant.
"""
from __future__ import annotations

import os

from agent_framework import Agent

from agents._common import CLAUDE_MODEL, FoundryClaudeChatClient, load_instructions
from observability import PROJECT_ENDPOINT, make_credential

AGENT_NAME = "Script-Writer-Pro-Agent"
MAX_TOKENS = int(os.environ.get("MAF_PRO_MAX_TOKENS", "48000"))
EFFORT = os.environ.get("MAF_PRO_EFFORT", "high")
PRO_PATH = os.environ.get("MAF_PRO_PATH", "anthropic").strip().lower()
FOUNDRY_RESOURCE = os.environ.get("MAF_FOUNDRY_RESOURCE", "Linedrive-ai-foundry")
_ANTHROPIC_SCOPE = "https://cognitiveservices.azure.com/.default"


def build_code_agent(credential=None, path: str | None = None) -> Agent:
    credential = credential or make_credential()
    if (path or PRO_PATH) == "anthropic":
        from agent_framework_anthropic import AnthropicFoundryClient  # noqa: PLC0415
        from azure.identity import get_bearer_token_provider  # noqa: PLC0415
        client = AnthropicFoundryClient(
            model=CLAUDE_MODEL,
            resource=FOUNDRY_RESOURCE,
            azure_ad_token_provider=get_bearer_token_provider(credential, _ANTHROPIC_SCOPE),
        )
        options = {"max_tokens": MAX_TOKENS, "thinking": {"type": "adaptive"},
                   "output_config": {"effort": EFFORT}}
    else:
        client = FoundryClaudeChatClient(
            project_endpoint=PROJECT_ENDPOINT, model=CLAUDE_MODEL, credential=credential)
        options = {"max_tokens": MAX_TOKENS, "reasoning": {"effort": EFFORT}}
    return Agent(client=client, name=AGENT_NAME,
                 instructions=load_instructions(AGENT_NAME), default_options=options)


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
