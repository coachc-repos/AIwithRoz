"""
MAF migration — Step 3: the script-pipeline agents as code.

Covers the seven portal agents that the app's script pipeline
(linedrive_azure/agents/enhanced_autogen_system.py) calls with messages it
builds itself:

    Topic Assistant  (teaching / list / predictions)   one call per script
    Writer           (teaching / list / predictions)   one call per chapter
    Reviewer         (teaching only)                    one call per chapter

The pipeline assembles these requests inline from a lot of context (the topic
plan, the golden-reference style block, per-chapter targets), so the drop-in
surface is message-level: `send(agent_name, message)` returns the same dict
shape as BaseAgentClient.send_message ({"success", "response", "error"}).

Each code agent runs its captured portal prompt on Claude Opus 5.5 with
Foundry's hosted web search attached (the model policy; the Reviewer uses the
second Opus 5.5 deployment, claude-opus-5-5-2, exactly as the portal does, so
parallel reviews do not compete with the writers for the same capacity).

Validation is replay-based. A capture run records every call the APP makes to
the portal agents during a real pipeline run (calls.jsonl: agent, message,
portal reply). `--replay` sends the same messages to the code agents, one at a
time, and scores both replies with the pipeline's own parsing:
  * Topic: the chapter list the app extracts (its three regexes + fallbacks)
  * Writer: words, Host label, heading, refusal (the app's refusal regex)
  * Reviewer: the "REVISED CHAPTER:" contract and the app's clean-up pass

    maf/.venv/bin/python maf/agents/pipeline.py --replay CAPTURE_DIR [--agent NAME] [--limit N]
    maf/.venv/bin/python maf/agents/pipeline.py --agent Script-Writer-Agent --message-file m.txt

Scoped to maf/, no web_gui.py changes, isolated venv.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import Agent  # noqa: E402

from agents._common import (  # noqa: E402
    CLAUDE_MODEL,
    build_code_agent as _build_agent,
    evidence_line,
    is_truncated,
    load_instructions,
    model_line,
    run_response,
    search_evidence,
)
from observability import load_env, make_credential, setup_tracing  # noqa: E402

REVIEWER_MODEL = os.environ.get("MAF_REVIEWER_MODEL", "claude-opus-5-5-2")


@dataclass(frozen=True)
class AgentSpec:
    kind: str            # "topic" | "writer" | "reviewer"
    model: str
    max_tokens: int = 16000
    web_search: bool = True
    addendum: str = ""   # app rules appended to the captured prompt (code only)


# Writers: the pipeline asks for "around 120 words" (list) or "around 150 words"
# (predictions) per chapter. Replaying the app's recorded list writer calls
# (2026-10-07), the code writers' SPOKEN Host words averaged about 148 per
# chapter with web search and no rule (6 of 10 within 20% of 120) and about 142
# with this rule and no search (8 of 10); the portal averaged about 108 (several
# under). Writers work from the Topic plan, so they get no web search (the
# Topic, Reviewer, and other agents keep it) plus this length rule.
# MAF_WRITER_APP_CONTRACT=0 drops the rule for A/B checks.
WRITER_CONTRACT = """

## App contract (added in code)

Length. When the request says "around N words", keep the chapter's spoken Host words between 0.8 x N and 1.2 x N. Count before you finish, and cut rather than pad. A target written as "N+ words" is a minimum, not a cap.
"""


# Topic assistants: the pipeline takes the chapter list from the reply with a
# regex for "Chapter N: Title (timing)" ANYWHERE in the text and keeps the first
# 8 (teaching) matches. Replaying the app's recorded teaching call (2026-10-07),
# the code agent wrote a callback list ("- **Chapter 3:** Dana's saved context
# note (her role, ...)") above the outline, so the app would have planned two
# bogus chapters and dropped the real final chapter. Either agent can do this.
# MAF_TOPIC_APP_CONTRACT=0 drops the rule for A/B checks.
TOPIC_CONTRACT = """

## App contract (added in code)

The app reads your chapter plan by looking for lines that start "Chapter N:" followed by a title and a timing in parentheses. Write "Chapter N: Title (start to end)" only in the chapter headings of your outline, one per chapter, in order. Everywhere else (tables, callbacks, transitions, notes) refer to a chapter as "Ch N", never "Chapter N:".
"""


def _topic_addendum() -> str:
    on = os.environ.get("MAF_TOPIC_APP_CONTRACT", "1").strip().lower() not in ("0", "false", "no", "off")
    return TOPIC_CONTRACT if on else ""


def _writer_addendum() -> str:
    on = os.environ.get("MAF_WRITER_APP_CONTRACT", "1").strip().lower() not in ("0", "false", "no", "off")
    return WRITER_CONTRACT if on else ""


TOPIC_MAX_TOKENS = int(os.environ.get("MAF_TOPIC_MAX_TOKENS", "32000"))

SPECS: dict[str, AgentSpec] = {
    # Topic plans used 10,249 output tokens (reasoning included) on a captured
    # request, so they get 32,000. Writers and reviewers write one chapter each
    # and run seven at a time, so they keep the 16,000 default.
    "Script-Topic-Assistant-Agent": AgentSpec("topic", CLAUDE_MODEL, max_tokens=TOPIC_MAX_TOKENS,
                                              addendum=_topic_addendum()),
    "Script-Topic-Assistant-List-Agent": AgentSpec("topic", CLAUDE_MODEL, max_tokens=TOPIC_MAX_TOKENS,
                                                   addendum=_topic_addendum()),
    "Script-Topic-Assistant-Predictions-Agent": AgentSpec("topic", CLAUDE_MODEL, max_tokens=TOPIC_MAX_TOKENS,
                                                          addendum=_topic_addendum()),
    "Script-Writer-Agent": AgentSpec("writer", CLAUDE_MODEL, web_search=False, addendum=_writer_addendum()),
    "Script-Writer-List-Agent": AgentSpec("writer", CLAUDE_MODEL, web_search=False, addendum=_writer_addendum()),
    # The portal agent runs gpt-5-mini; the code agent follows the model policy.
    "Script-Writer-Predictions-Agent": AgentSpec("writer", CLAUDE_MODEL, web_search=False,
                                                 addendum=_writer_addendum()),
    "Script-Reviewer-Agent": AgentSpec("reviewer", REVIEWER_MODEL),
    # Not called by the app (web or console). Its portal prompt is an older copy
    # of a Topic Assistant prompt, so it is tested as a topic planner with the
    # app's real topic-planning message (see --as-agent / --from-agent).
    "Script-Demo-Assistant-Agent": AgentSpec("topic", CLAUDE_MODEL),
}


def build_code_agent(agent_name: str, credential=None) -> Agent:
    spec = SPECS[agent_name]
    return _build_agent(
        name=f"{agent_name} (code)",
        instructions=load_instructions(agent_name) + spec.addendum,
        model=spec.model,
        max_tokens=spec.max_tokens,
        credential=credential,
        web_search=spec.web_search,
    )


async def send(agent_name: str, message: str, credential=None, agent=None) -> dict:
    """Drop-in for BaseAgentClient.send_message(thread_id, message): one turn,
    same result shape. A reply cut off by max_tokens is reported as a failure
    (the pipeline would otherwise keep a truncated chapter)."""
    agent = agent or build_code_agent(agent_name, credential)
    try:
        resp = await run_response(agent, message, agent_name)
    except Exception as e:
        return {"success": False, "error": str(e), "response": ""}
    text = (resp.text or "").strip()
    if is_truncated(resp):
        return {"success": False, "error": "reply hit max_tokens", "response": text, "_resp": resp}
    return {"success": bool(text), "response": text, "_resp": resp,
            **({} if text else {"error": "empty response"})}


# --------------------------------------------------------------------------- #
# The pipeline's own parsing, ported verbatim (enhanced_autogen_system.py).
# --------------------------------------------------------------------------- #

_DESHOUT_KEEP = {
    "AI", "API", "APIS", "ML", "LLM", "LLMS", "GPT", "UI", "UX", "SEO", "CSS",
    "HTML", "SQL", "AWS", "GCP", "CPU", "GPU", "SDK", "CLI", "URL", "URI",
    "HTTP", "HTTPS", "JSON", "XML", "IOT", "AR", "VR", "NLP", "RAG", "ROI",
    "KPI", "CRM", "ERP", "SAAS", "PAAS", "IAAS", "IT", "PC", "OS", "DB", "ID",
    "FAQ", "PDF", "CSV", "RAM", "SSD", "USB", "2D", "3D", "4K", "HD", "USA",
    "UK", "EU", "CEO", "CTO", "CFO", "B2B", "B2C", "QA", "ETL", "VPN", "DNS",
}


def _deshout_text(text: str) -> str:
    if not text:
        return text

    def _fix_run(r: "re.Match") -> str:
        run = r.group(0)
        return run if run.upper() in _DESHOUT_KEEP else run.capitalize()

    def _fix_token(m: "re.Match") -> str:
        w = m.group(0)
        if any(c.islower() for c in w):
            return w
        return re.sub(r"[A-Za-z]+", _fix_run, w)

    return re.sub(r"\S+", _fix_token, text)


def extract_chapters(topic_reply: str, max_chapters: int = 8) -> list[str]:
    """The chapter titles the pipeline takes from a Topic Assistant reply."""
    topic_enhancement = _deshout_text(topic_reply)
    full_pattern_matches = re.findall(
        r"Chapter\s+\d+[:\-]\s*([^\n(]+?)\s*\([^)]+\)", topic_enhancement, re.IGNORECASE)
    emdash_pattern_matches = re.findall(
        r'^([A-Z][^—\n]+)(?:—)\s*["“]([^"”\n]+)', topic_enhancement, re.MULTILINE)
    simple_pattern_matches = re.findall(
        r"Chapter\s+\d+[:\-]\s*([^\n(]+?)(?:\s*\(|\s*$)", topic_enhancement, re.IGNORECASE)
    chapter_matches = []
    if full_pattern_matches:
        chapter_matches = [m.strip() for m in full_pattern_matches]
    elif emdash_pattern_matches:
        chapter_matches = [f"{tool.strip()} - {desc.strip()}" for tool, desc in emdash_pattern_matches]
    elif simple_pattern_matches:
        chapter_matches = [m.strip() for m in simple_pattern_matches]
    chapters, seen = [], set()
    for match in chapter_matches:
        clean_chapter = match.strip()
        is_timestamp = bool(re.match(r'^\d+:\d+[–\-—]\d+:\d+$', clean_chapter))
        if len(clean_chapter) > 10 and clean_chapter not in seen and not is_timestamp:
            chapters.append(clean_chapter)
            seen.add(clean_chapter)
    chapters = chapters[:max_chapters]
    if not chapters:
        numbered_matches = re.findall(r"\d+\.\s*([^\n]+)", topic_enhancement)
        chapters = ([m.strip() for m in numbered_matches[:5]] if numbered_matches
                    else ["Introduction", "Main Content", "Conclusion"])
    return chapters


_REFUSAL_RE = re.compile(
    r"(?:^|\n)\s*I[’']?m sorry,?\s+but I cannot assist with that request\.?\s*$", flags=re.IGNORECASE)


def writer_refused(reply: str) -> bool:
    """The pipeline marks a chapter failed when this refusal dominates it."""
    if not _REFUSAL_RE.search(reply or ""):
        return False
    cleaned = _REFUSAL_RE.sub("", reply).rstrip()
    return len(cleaned) < 400 or len(cleaned) < len(reply) * 0.5


def reviewer_revised_chapter(response: str) -> str:
    """The revised chapter the pipeline keeps from a Reviewer reply."""
    if "=== REVISED SCRIPT ===" in response:
        revised_chapter = response.split("=== REVISED SCRIPT ===", 1)[1].strip()
    elif "REVISED CHAPTER:" in response:
        revised_chapter = response.split("REVISED CHAPTER:", 1)[1].strip()
    else:
        revised_chapter = response
    if "===" in revised_chapter:
        clean_lines, skip_mode = [], False
        for line in revised_chapter.split('\n'):
            if '===' in line or 'REVIEW FEEDBACK' in line:
                skip_mode = True
                continue
            if skip_mode or any(k in line.upper() for k in [
                    'FEEDBACK', 'IMPROVEMENTS', 'CHANGES MADE', 'ASSESSMENT', 'ANALYSIS',
                    'AUDIENCE APPROPRIATENESS', 'TONE & STYLE', 'STRUCTURE & FLOW', 'CONTENT QUALITY']):
                skip_mode = True
                continue
            if skip_mode and (line.startswith('## Chapter') or line.startswith('[Visual Cue:')
                              or line.startswith('**Host:**')):
                skip_mode = False
            if not skip_mode:
                clean_lines.append(line)
        revised_chapter = '\n'.join(clean_lines).strip()
    return revised_chapter


# --------------------------------------------------------------------------- #
# Metrics per agent kind (measurement only).
# --------------------------------------------------------------------------- #

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’]*")
_HOST = re.compile(r"(?im)^[ \t]*\**[ \t]*host[ \t]*\**[ \t]*:")


def _words(s: str) -> int:
    return len(_WORD.findall(s or ""))


def _quirks(s: str) -> int:
    """Curly quotes, no-break/thin spaces, and en/em dashes: the typography that
    appears when Foundry's hosted web search rewrites a Claude reply."""
    return sum((s or "").count(ch) for ch in "\u2018\u2019\u201c\u201d\u00a0\u202f\u2009\u2013\u2014")


def app_max_chapters(script_format: str, script_topic: str, max_chapters: int = 8) -> int:
    """The pipeline's chapter cap: 8, or for list / predictions the first number
    in the title (default 10 / 7, clamped 3..15) plus intro and conclusion."""
    if script_format in ("list", "predictions") and max_chapters > 1:
        m = re.search(r"\b(\d{1,2})\b", script_topic or "")
        n = int(m.group(1)) if m else (7 if script_format == "predictions" else 10)
        return max(3, min(n, 15)) + 2
    return max_chapters


def topic_metrics(reply: str, message: str, ctx: dict) -> dict:
    ch = extract_chapters(reply, ctx.get("max_chapters", 8))
    return {"chars": len(reply), "chapters": f"{len(ch)}/{ctx.get('max_chapters', 8)}",
            "quirks": _quirks(reply), "first": (ch[0][:34] if ch else "-"),
            "last": (ch[-1][:34] if ch else "-")}


def _spoken(reply: str) -> int:
    """Spoken words, the unit of the writers' length targets: the app's Host-word
    count, or words outside production blocks when a chapter has no Host label."""
    from agents._script_metrics import app_host_words
    n = app_host_words(reply)
    if n:
        return n
    return len(re.sub(r"\[PRODUCTION\s+BEGIN\].*?\[PRODUCTION\s+END\]", " ", reply or "",
                      flags=re.S | re.I).split())


def writer_metrics(reply: str, message: str, ctx: dict) -> dict:
    target = re.search(r"around (\d+) words", message)
    return {"chars": len(reply), "spoken": _spoken(reply),
            "target": (int(target.group(1)) if target else "-"), "host_labels": len(_HOST.findall(reply)),
            "heading": bool(re.search(r"(?im)^[ \t]*\**[ \t]*heading\s*:", reply)),
            "refused": writer_refused(reply), "quirks": _quirks(reply)}


def reviewer_metrics(reply: str, message: str, ctx: dict) -> dict:
    final = "THIS IS THE FINAL CHAPTER" in message
    orig = message.split("ORIGINAL CHAPTER:", 1)[1].split("INSTRUCTIONS:", 1)[0] if "ORIGINAL CHAPTER:" in message else ""
    kept = reviewer_revised_chapter(reply)
    return {"chars": len(reply), "marker": "REVISED CHAPTER:" in reply,
            "host_labels": len(_HOST.findall(kept)),
            "visual_cue": bool(re.search(r"(?i)visual\s+cue\s*:", kept)),
            "summary": (bool(re.search(r"(?im)^\W*summary\s*:", kept)) if final else None),
            "quirks": _quirks(reply),
            "words_vs_orig": f"{_words(kept) / max(1, _words(orig)):.0%}" if orig else "-"}


METRICS: dict[str, Callable[[str, str, dict], dict]] = {
    "topic": topic_metrics, "writer": writer_metrics, "reviewer": reviewer_metrics}


# --------------------------------------------------------------------------- #
# Replay recorded app -> portal calls against the code agents.
# --------------------------------------------------------------------------- #

def load_calls(capture_dir: str, agent_name: str | None = None) -> list[dict]:
    calls = []
    with open(os.path.join(capture_dir, "calls.jsonl"), encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("agent") in SPECS and (agent_name is None or rec["agent"] == agent_name):
                calls.append(rec)
    return calls


def _fmt(m: dict) -> str:
    return " ".join(f"{k}={v}" for k, v in m.items() if v is not None)


async def replay(capture_dir: str, agent_name: str | None, limit: int | None, dump_dir: str = "") -> dict:
    calls = load_calls(capture_dir, agent_name)
    by_agent: dict[str, list[dict]] = {}
    for c in calls:
        by_agent.setdefault(c["agent"], []).append(c)
    cred = make_credential()
    ctx = {"max_chapters": 8}
    meta_path = os.path.join(capture_dir, "summary.json")
    if os.path.exists(meta_path):
        meta = json.load(open(meta_path, encoding="utf-8"))
        ctx["max_chapters"] = app_max_chapters(meta.get("format", ""), meta.get("topic", ""))
    summary = {}
    for name, recs in by_agent.items():
        spec = SPECS[name]
        recs = recs[:limit] if limit else recs
        print(f"\n=== {name} [{spec.kind}] — {len(recs)} recorded call(s)")
        print(model_line(name, spec.model, cred))
        agent = build_code_agent(name, cred)
        rows = []
        for i, rec in enumerate(recs, 1):
            t = time.time()
            res = await send(name, rec["message"], agent=agent)
            secs = time.time() - t
            portal_reply = rec.get("response") or ""
            code_reply = res.get("response") or ""
            pm = METRICS[spec.kind](portal_reply, rec["message"], ctx) if portal_reply else None
            cm = METRICS[spec.kind](code_reply, rec["message"], ctx) if res.get("success") else None
            ev = search_evidence(res["_resp"]) if res.get("_resp") else None
            rows.append({"ok": bool(res.get("success")), "code": cm, "portal": pm, "evidence": ev,
                         "error": res.get("error")})
            print(f"  call {i}/{len(recs)} ({len(rec['message'])} chars in, {secs:.0f}s)")
            print(f"    CODE  : {_fmt(cm) if cm else 'FAILED ' + str(res.get('error'))[:160]}"
                  + (f"  [{evidence_line(res['_resp'])}]" if res.get('_resp') else ""))
            print(f"    PORTAL: {_fmt(pm) if pm else 'no reply recorded (' + str(rec.get('error'))[:120] + ')'}")
            if dump_dir:
                os.makedirs(dump_dir, exist_ok=True)
                base = os.path.join(dump_dir, f"{name}_{i}")
                open(base + "_code.md", "w", encoding="utf-8").write(code_reply)
                open(base + "_portal.md", "w", encoding="utf-8").write(portal_reply)
        ok = sum(r["ok"] for r in rows)
        summary[name] = {"calls": len(rows), "code_ok": ok,
                         "web_searches": sum((r["evidence"] or {}).get("web_searches", 0) for r in rows)}
        print(f"  -> code agent succeeded on {ok}/{len(rows)}; "
              f"{summary[name]['web_searches']} web searches in total")
    return summary


async def cross_compare(capture_dir: str, as_agent: str, from_agent: str, limit: int | None) -> None:
    """Send another agent's recorded messages to BOTH versions of `as_agent`
    (code and portal, live). For agents the app never calls."""
    from agents._common import portal_agent
    recs = load_calls(capture_dir, from_agent)[: (limit or None)]
    spec = SPECS[as_agent]
    cred = make_credential()
    ctx = {"max_chapters": 8}
    print(f"\n=== {as_agent} [{spec.kind}] on {len(recs)} recorded {from_agent} message(s)")
    print(model_line(as_agent, spec.model, cred))
    code_agent, portal = build_code_agent(as_agent, cred), portal_agent(as_agent, cred)
    for i, rec in enumerate(recs, 1):
        for label, agent in (("CODE", code_agent), ("PORTAL", portal)):
            res = await send(as_agent, rec["message"], agent=agent)
            m = METRICS[spec.kind](res.get("response") or "", rec["message"], ctx) if res.get("success") else None
            print(f"  {label:<6}: {_fmt(m) if m else 'FAILED ' + str(res.get('error'))[:150]}"
                  + (f"  [{evidence_line(res['_resp'])}]" if res.get('_resp') else ""))


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description="Script-pipeline agents as code (Topic, Writer, Reviewer).")
    ap.add_argument("--replay", metavar="CAPTURE_DIR", help="Replay a capture's recorded calls")
    ap.add_argument("--agent", choices=sorted(SPECS), help="Only this agent")
    ap.add_argument("--limit", type=int, help="At most N calls per agent")
    ap.add_argument("--dump", default="", metavar="DIR", help="Save code and portal replies")
    ap.add_argument("--message-file", help="Send one message from a file to --agent and print the reply")
    ap.add_argument("--as-agent", choices=sorted(SPECS), help="With --replay and --from-agent: run that "
                    "agent's recorded messages on this agent's code AND portal versions (live)")
    ap.add_argument("--from-agent", choices=sorted(SPECS), help="Source agent for --as-agent")
    args = ap.parse_args()
    print(f"tracing : {setup_tracing()}")
    if args.replay and args.as_agent and args.from_agent:
        asyncio.run(cross_compare(args.replay, args.as_agent, args.from_agent, args.limit))
    elif args.replay:
        print(json.dumps(asyncio.run(replay(args.replay, args.agent, args.limit, args.dump)), indent=1))
    elif args.message_file and args.agent:
        msg = open(args.message_file, encoding="utf-8").read()
        res = asyncio.run(send(args.agent, msg))
        print(res.get("response") or res.get("error"))
    else:
        ap.error("use --replay CAPTURE_DIR, or --agent NAME --message-file FILE")


if __name__ == "__main__":
    main()
