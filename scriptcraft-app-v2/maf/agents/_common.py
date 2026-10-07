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
from typing import Annotated, Any, Awaitable, Callable

from agent_framework import Agent, FunctionTool, tool
from agent_framework.foundry import FoundryAgent, FoundryChatClient

from observability import PROJECT_ENDPOINT, make_credential

# Model policy (user decision, 2026-10-07): every code agent runs Claude Opus 5.5
# on the Foundry deployment, except Quotes-and-Statistics, which runs Grok 4.7
# through xAI so it can search X. Portal agents may still run other models;
# compare modes print both so a mismatch is visible (see model_line()).
CLAUDE_MODEL = os.environ.get("MAF_CLAUDE_MODEL", "claude-opus-5-5")
GROK_MODEL = os.environ.get("MAF_GROK_MODEL", "grok-4.7")
XAI_BASE_URL = os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1")
# Model behind the web_search FUNCTION tool (see make_web_search_tool).
SEARCH_MODEL = os.environ.get("MAF_SEARCH_MODEL", "gpt-5.4-mini")

# scriptcraft-app-v2/agent_instructions/ in the repo; <zip root>/agent_instructions/
# in a hosted deployment (maf/hosted/deploy.py packs it next to agents/).
_HERE = os.path.dirname(os.path.abspath(__file__))
INSTRUCTIONS_DIR = next(
    (d for d in (os.environ.get("MAF_INSTRUCTIONS_DIR", ""),
                 os.path.join(os.path.dirname(os.path.dirname(_HERE)), "agent_instructions"),
                 os.path.join(os.path.dirname(_HERE), "agent_instructions"))
     if d and os.path.isdir(d)),
    os.path.join(os.path.dirname(os.path.dirname(_HERE)), "agent_instructions"),
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


_SEARCH_INSTRUCTIONS = (
    "You are a web research tool for a script-writing agent. Search the web and answer the query "
    "with 3 to 8 short bullet points of facts. End each bullet with its source title, URL, and "
    "publication date when known. Plain text. No preamble and no conclusion."
)


def make_web_search_tool(credential=None) -> FunctionTool:
    """Web search as a FUNCTION tool: a small Azure OpenAI model runs Foundry's
    hosted web search and returns findings with URLs; the calling agent (Claude)
    then writes its own answer.

    Why not attach Foundry's hosted web search to Claude directly: it runs on
    claude-opus-5-5 (the MAF docs call it Azure-OpenAI-only), but whenever a
    search actually fires, the returned text stops following the agent's own
    formatting rules: curly quotes and narrow no-break spaces despite explicit
    "straight quotes only" instructions, en/em dashes, "##  " double-space
    headings, plain-text instead of pipe tables, and on Repeat-and-Flow a
    duplicated revised script (measured 2026-10-07; replies with no search were
    clean). The portal agents all have that tool attached, which explains their
    format failures in the app (Quotes and YouTube parsers matched nothing, a
    B-Roll table with no pipes, Flow placeholders dropped)."""
    searcher = Agent(
        client=FoundryChatClient(project_endpoint=PROJECT_ENDPOINT, model=SEARCH_MODEL,
                                 credential=credential or make_credential()),
        name="web-search",
        instructions=_SEARCH_INSTRUCTIONS,
        tools=[FoundryChatClient.get_web_search_tool()],
        default_options={"max_tokens": 2000},
    )

    async def web_search(
        query: Annotated[str, "What to look up: a specific fact, product, statistic, or recent event"],
    ) -> str:
        """Search the public web for current facts, product details, statistics, and recent news. Returns findings with source URLs and dates."""
        resp = await run_response(searcher, query, "web_search")
        return (resp.text or "").strip() or "No results."

    return tool(web_search, name="web_search", approval_mode="never_require")


def build_code_agent(*, name: str, instructions: str, model: str, max_tokens: int,
                     credential=None, web_search: bool = True) -> Agent:
    """A code-defined MAF agent on the Foundry project's model deployment.

    web_search attaches the web_search FUNCTION tool (make_web_search_tool), so
    the agent can look things up like its portal counterpart while still writing
    every word of its reply itself."""
    credential = credential or make_credential()
    return Agent(
        client=FoundryChatClient(
            project_endpoint=PROJECT_ENDPOINT,
            model=model,
            credential=credential,
        ),
        name=name,
        instructions=instructions,
        tools=[make_web_search_tool(credential)] if web_search else None,
        default_options={"max_tokens": max_tokens},
    )


def build_xai_agent(*, name: str, instructions: str, max_tokens: int,
                    model: str = GROK_MODEL, x_search: bool = True,
                    web_search: bool = True, max_turns: int | None = None) -> Agent:
    """A code-defined MAF agent on Grok via xAI's OpenAI-compatible Responses API,
    with xAI's server-side X search and web search. MAF passes the raw tool
    dicts through and treats xAI's x_* tool calls as informational, so the
    search loop runs entirely on xAI. Needs XAI_API_KEY (or GROK_API_KEY).

    max_turns caps xAI's server-side agent loop (sent as an extra body field).
    Without it, a full-script research request ran its search loop for over
    ten minutes; xAI ignores max_tool_calls, but honors max_turns."""
    from agent_framework.openai import OpenAIChatClient

    key = (os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("XAI_API_KEY is not set (repo-root .env or environment)")
    tools = ([{"type": "x_search"}] if x_search else []) + ([{"type": "web_search"}] if web_search else [])
    return Agent(
        client=OpenAIChatClient(model=model, api_key=key, base_url=XAI_BASE_URL),
        name=name,
        instructions=instructions,
        tools=tools or None,
        default_options={"max_tokens": max_tokens,
                         **({"extra_body": {"max_turns": max_turns}} if max_turns else {})},
    )


def search_evidence(resp) -> dict:
    """What a reply's server-side tools actually did: web searches, X searches
    (xAI x_* tools), and the URLs cited in the answer."""
    out = {"web_searches": 0, "x_searches": 0, "citations": []}
    for m in getattr(resp, "messages", None) or []:
        for c in getattr(m, "contents", None) or []:
            ctype = getattr(c, "type", None)
            fname = str(getattr(c, "name", "") or "")
            if ctype == "search_tool_call" or (ctype == "function_call" and fname == "web_search"):
                out["web_searches"] += 1
            elif ctype == "function_call" and fname.startswith("x_"):
                out["x_searches"] += 1
            elif ctype == "function_result":
                # URLs the web_search function returned count as the agent's sources.
                for url in re.findall(r"https?://[^\s)\]>\"'*]+", str(getattr(c, "result", "") or "")):
                    url = url.rstrip(".,;")
                    if url not in out["citations"]:
                        out["citations"].append(url)
            for a in getattr(c, "annotations", None) or []:
                url = a.get("url") if isinstance(a, dict) else getattr(a, "url", None)
                if not url and isinstance(a, dict):
                    url = (a.get("additional_properties") or {}).get("url")
                if url and url not in out["citations"]:
                    out["citations"].append(url)
    return out


def evidence_line(resp) -> str:
    e = search_evidence(resp)
    parts = [f"{e['web_searches']} web searches"]
    if e["x_searches"]:
        parts.append(f"{e['x_searches']} X searches")
    parts.append(f"{len(e['citations'])} cited URLs")
    return ", ".join(parts)


def portal_model(portal_agent_name: str, credential=None) -> str | None:
    """The model the live portal agent runs (its latest Foundry version)."""
    try:
        from azure.ai.projects import AIProjectClient

        pc = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential or make_credential())
        d = pc.agents.get(agent_name=portal_agent_name).as_dict()
        return (((d.get("versions") or {}).get("latest") or {}).get("definition") or {}).get("model")
    except Exception:
        return None


def model_line(portal_agent_name: str, code_model: str, credential=None) -> str:
    """'models: code X | portal Y', flagging a mismatch (e.g. after a portal edit)."""
    pm = portal_model(portal_agent_name, credential)
    note = "" if pm in (None, code_model) else "  <- differs (code follows the model policy)"
    return f"models  : code {code_model} | portal {pm or 'unknown'}{note}"


_TRANSIENT_MARKERS = (
    "connection", "nodename", "servname", "name or service",
    "timed out", "timeout", "temporarily", "reset", "eof",
    "could not resolve", "getaddrinfo",
)
# Model-deployment throttling (HTTP 429). The app's pipeline writes chapters in
# parallel, so these are routine; back off longer than for DNS blips.
_RATE_LIMIT_MARKERS = ("rate_limit", "rate limit", "429", "too many requests")


async def run_with_retry(make_coro: Callable[[], Awaitable[Any]], label: str,
                         attempts: int = 6) -> Any:
    """Retry transient DNS/connection blips (Azure front door / local network).
    The Foundry host DNS occasionally flaps for tens of seconds, so we give it a
    ~40s window (6 attempts with increasing backoff) before giving up."""
    for i in range(1, attempts + 1):
        try:
            return await make_coro()
        except Exception as e:
            msg = str(e).lower()
            throttled = any(k in msg for k in _RATE_LIMIT_MARKERS)
            transient = throttled or any(k in msg for k in _TRANSIENT_MARKERS)
            if not transient or i == attempts:
                raise
            delay = min(60.0, 10.0 * i) if throttled else min(12.0, 2.0 * i)
            kind = "rate limited" if throttled else "transient connection error"
            print(f"   [{label}] {kind} (attempt {i}/{attempts}); retrying in {delay:.0f}s…",
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
