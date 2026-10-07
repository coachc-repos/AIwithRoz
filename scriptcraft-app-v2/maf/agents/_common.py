"""Shared plumbing for step-3 portal->code agent conversions.

Every converted agent follows the same recipe:
  1. load the captured portal prompt from ../agent_instructions/<Agent>.md,
  2. build a code-defined MAF `Agent` on `FoundryChatClient` (same model as the portal),
  3. keep a `--compare` mode that runs the portal agent BY NAME on the same input.
This module holds the parts of that recipe that are identical across agents.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from typing import Any, Awaitable, Callable

from agent_framework import Agent
from agent_framework.foundry import FoundryAgent, FoundryChatClient

from observability import PROJECT_ENDPOINT, make_credential

# scriptcraft-app-v2/agent_instructions/
INSTRUCTIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "agent_instructions",
)

_HEADER_COMMENT = re.compile(r"^\s*<!--.*?-->\s*", flags=re.DOTALL)


def load_instructions(portal_agent_name: str) -> str:
    """Captured portal instructions for `portal_agent_name`, minus the capture-header comment."""
    path = os.path.join(INSTRUCTIONS_DIR, f"{portal_agent_name}.md")
    with open(path, "r", encoding="utf-8") as f:
        return _HEADER_COMMENT.sub("", f.read()).strip()


# Title of the golden reference script, the default --compare input for agents
# that work on a complete script.
REFERENCE_TITLE = "10 AI Tools, and When NOT to Use Them"


def load_reference_script() -> str:
    """The golden reference script (a full 7-chapter script) — a realistic --compare input."""
    with open(os.path.join(INSTRUCTIONS_DIR, "golden_reference_script.md"), "r", encoding="utf-8") as f:
        return _HEADER_COMMENT.sub("", f.read()).strip()


def build_code_agent(*, name: str, instructions: str, model: str, max_tokens: int,
                     credential=None) -> Agent:
    """A code-defined MAF agent on the Foundry project's model deployment."""
    return Agent(
        client=FoundryChatClient(
            project_endpoint=PROJECT_ENDPOINT,
            model=model,
            credential=credential or make_credential(),
        ),
        name=name,
        instructions=instructions,
        default_options={"max_tokens": max_tokens},
    )


_TRANSIENT_MARKERS = (
    "connection", "nodename", "servname", "name or service",
    "timed out", "timeout", "temporarily", "reset", "eof",
    "could not resolve", "getaddrinfo",
)


async def run_with_retry(make_coro: Callable[[], Awaitable[Any]], label: str,
                         attempts: int = 6) -> Any:
    """Retry transient DNS/connection blips (Azure front door / local network).
    The Foundry host DNS occasionally flaps for tens of seconds, so we give it a
    ~40s window (6 attempts with increasing backoff) before giving up."""
    for i in range(1, attempts + 1):
        try:
            return await make_coro()
        except Exception as e:
            transient = any(k in str(e).lower() for k in _TRANSIENT_MARKERS)
            if not transient or i == attempts:
                raise
            delay = min(12.0, 2.0 * i)
            print(f"   [{label}] transient connection error "
                  f"(attempt {i}/{attempts}); retrying in {delay:.0f}s…",
                  file=sys.stderr)
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover


def is_truncated(resp) -> bool:
    """True when the reply stopped because it hit max_tokens."""
    return str(getattr(resp, "finish_reason", "") or "").lower().endswith("length")


async def run_response(agent, message: str, label: str):
    """Run any MAF agent (code-defined or FoundryAgent) on one message; return the
    full AgentResponse (text, finish_reason, usage). Warns on truncation."""
    async def _go():
        resp = await agent.run(message)
        if is_truncated(resp):
            print(f"   [{label}] WARNING: reply hit max_tokens and is truncated",
                  file=sys.stderr)
        return resp

    return await run_with_retry(_go, label)


async def run_text(agent, message: str, label: str) -> str:
    """Run any MAF agent on one message; return its text."""
    return ((await run_response(agent, message, label)).text or "").strip()


def portal_agent(portal_agent_name: str, credential=None) -> FoundryAgent:
    """The existing portal agent, addressed by name (the step-1 pattern)."""
    return FoundryAgent(
        project_endpoint=PROJECT_ENDPOINT,
        agent_name=portal_agent_name,
        credential=credential or make_credential(),
    )


async def run_portal(portal_agent_name: str, message: str, credential=None) -> str:
    """The existing portal agent, called by name; return its text."""
    return await run_text(portal_agent(portal_agent_name, credential), message, "portal")
