"""
MAF migration — Step 3: Statistics-and-Quotes-Finder-Agent as code, on Grok.

Re-creates the Foundry portal agent `Statistics-and-Quotes-Finder-Agent` as a
CODE-DEFINED Microsoft Agent Framework agent on Grok 4.7 (the model policy:
Quotes-and-Statistics is the one agent that runs Grok). It calls xAI's
OpenAI-compatible Responses API directly so it can use xAI's server-side
**X search** alongside web search; the portal agent's Foundry web search is
Bing-based and returned no X posts when tested (2026-10-07).

Drop-in contract: `generate_quotes_and_statistics()` sends the SAME request as
`linedrive_azure/agents/quote_and_statistics_agent_client.py` and returns the
same keys the pipeline reads (success, raw_response, quotes_count,
statistics_count, quotes_section, statistics_section, recommendations_section,
overall_strategy), parsed with a verbatim port of the client's parser.

The code agent's instructions are the captured portal prompt plus a SOURCING
addendum (search X first and use at least one real X post when one exists;
exact quotes only, never invented; a **Link:** line under every quote and
statistic). The app's parser only counts the
"**Quote N:**" / "**Statistic N:**" labels, so the extra lines are safe.
MAF_QUOTES_SOURCING=0 runs the bare captured prompt for A/B checks.

--compare runs the code agent and the portal agent on the same script and
scores: quotes and statistics the app counts, links, X post links, links that
came from the agent's own search results (grounded), dates inside the prompt's
12-18 month window, and how many web / X searches each agent ran.

    maf/.venv/bin/python maf/agents/quotes_stats.py --compare --dump /tmp/quotes_cmp
    maf/.venv/bin/python maf/agents/quotes_stats.py --script-file s.md --title "..."

Needs XAI_API_KEY (repo-root .env). Scoped to maf/, no web_gui.py changes.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import Agent  # noqa: E402

from agents._common import (  # noqa: E402
    GROK_MODEL,
    REFERENCE_TITLE,
    build_xai_agent,
    evidence_line,
    is_truncated,
    load_instructions as _load_instructions,
    load_reference_script,
    model_line,
    portal_agent,
    run_response,
    search_evidence,
)
from observability import PROJECT_ENDPOINT, load_env, make_credential, setup_tracing  # noqa: E402

AGENT_NAME = "Statistics-and-Quotes-Finder-Agent"   # the portal agent
MODEL = os.environ.get("MAF_QUOTES_MODEL", GROK_MODEL)
MAX_TOKENS = int(os.environ.get("MAF_QUOTES_MAX_TOKENS", "16000"))
# Caps xAI's server-side search loop (see build_xai_agent). Each turn can run
# several X / web searches in parallel, so 8 turns is ample for 3 + 3 sources.
MAX_TURNS = int(os.environ.get("MAF_QUOTES_MAX_TURNS", "8"))

SOURCING = """

## Sourcing rules (added in code)

1. Search X first for quotes. Use X search to find posts from the last 12 months by named experts, researchers, and company leaders about this video's subject, and use at least one of those posts as a quote whenever a relevant one exists, with its post URL as the link. Use web search for the studies, surveys, and reports behind the statistics, and for any remaining quotes.
2. Every quote must be an exact quote you found in a search result. Never invent a quote, paraphrase inside quotation marks, or stitch two quotes together. If you cannot find three real quotes, give fewer and say so.
3. Directly under each quote and each statistic, add one line: **Link:** followed by the URL of the post or page you found it in. For a post on X, use the post URL (https://x.com/<handle>/status/<id>).
4. Keep the required section headings and the **Quote N:** and **Statistic N:** labels exactly as specified.
"""


def sourcing_enabled() -> bool:
    return os.environ.get("MAF_QUOTES_SOURCING", "1").strip().lower() not in ("0", "false", "no", "off")


def load_instructions() -> str:
    return _load_instructions(AGENT_NAME)


def build_code_agent() -> Agent:
    return build_xai_agent(
        name="Statistics-and-Quotes-Finder-Agent (code)",
        instructions=load_instructions() + (SOURCING if sourcing_enabled() else ""),
        model=MODEL,
        max_tokens=MAX_TOKENS,
        max_turns=MAX_TURNS,
    )


def build_request_message(script_content: str, script_title: str,
                          target_audience: str = "general audience",
                          tone: str = "conversational and educational") -> str:
    """Verbatim copy of the request the app client sends (keep in sync)."""
    topic = script_title
    return f"""
QUOTES AND STATISTICS GENERATION REQUEST

SCRIPT DETAILS:
- Title: {script_title}
- Target Audience: {target_audience}
- Tone: {tone}

COMPLETE SCRIPT TO ANALYZE:
{script_content}

TASK:
Generate 3 expert quotes and 3 compelling statistics directly about the SUBJECT
of THIS video: "{topic}". Ground them in the actual topics, claims, people,
companies, studies, and events discussed in the COMPLETE SCRIPT above — not in
generic AI or "AI content creation" material. Every quote and statistic MUST be
relevant to "{topic}"; discard anything that is not.

DELIVERABLE:
- 3 expert quotes with attribution and context
- 3 key statistics with sources and context
- Usage recommendations for strategic placement
- Overall strategy explanation
"""


def parse_response(response_text: str) -> dict:
    """Verbatim port of ScriptQuotesAndStatisticsAgentClient._parse_response."""
    result = {"quotes": [], "statistics": [], "usage_recommendations": {}, "overall_strategy": ""}
    sections = {"quotes": "", "statistics": "", "recommendations": ""}
    if "## 📊 EXPERT QUOTES" in response_text:
        quotes_start = response_text.find("## 📊 EXPERT QUOTES")
        quotes_end = response_text.find("## 📈 KEY STATISTICS", quotes_start)
        if quotes_end > quotes_start:
            sections["quotes"] = response_text[quotes_start:quotes_end].strip()
    if "## 📈 KEY STATISTICS" in response_text:
        stats_start = response_text.find("## 📈 KEY STATISTICS")
        stats_end = response_text.find("## 🎯 USAGE RECOMMENDATIONS", stats_start)
        if stats_end > stats_start:
            sections["statistics"] = response_text[stats_start:stats_end].strip()
    if "## 🎯 USAGE RECOMMENDATIONS" in response_text:
        rec_start = response_text.find("## 🎯 USAGE RECOMMENDATIONS")
        sections["recommendations"] = response_text[rec_start:].strip()
    result["quotes_count"] = sections["quotes"].count("**Quote")
    result["statistics_count"] = sections["statistics"].count("**Statistic")
    if "**Overall Strategy:**" in response_text:
        strategy_start = response_text.find("**Overall Strategy:**")
        strategy_text = response_text[strategy_start:].split("\n\n")[0]
        result["overall_strategy"] = strategy_text.replace("**Overall Strategy:**", "").strip()
    result["quotes_section"] = sections["quotes"]
    result["statistics_section"] = sections["statistics"]
    result["recommendations_section"] = sections["recommendations"]
    return result


async def generate_quotes_and_statistics(script_content: str, script_title: str,
                                         target_audience: str = "general audience",
                                         tone: str = "conversational and educational") -> dict:
    """Code-agent equivalent of the app client's generate_quotes_and_statistics()."""
    msg = build_request_message(script_content, script_title, target_audience, tone)
    try:
        resp = await run_response(build_code_agent(), msg, "code")
    except Exception as e:
        return {"success": False, "error": str(e), "raw_response": ""}
    text = (resp.text or "").strip()
    if is_truncated(resp) or not text:
        return {"success": False, "error": "reply truncated or empty", "raw_response": text}
    return {"success": True, "raw_response": text, **parse_response(text),
            "search": search_evidence(resp)}


# --------------------------------------------------------------------------- #
# --compare scoring
# --------------------------------------------------------------------------- #

_URL = re.compile(r"https?://[^\s)\]>\"'*]+")
_MONTHS = ("january february march april may june july august september october "
           "november december").split()
_DATE = re.compile(r"\b(" + "|".join(m[:3] for m in _MONTHS) + r")[a-z]*\.?\s+(?:\d{1,2},?\s+)?(20\d\d)\b", re.I)


def _status_id(url: str) -> str:
    m = re.search(r"/status(?:es)?/(\d+)", url)
    return m.group(1) if m else url.rstrip("/.").split("?")[0].lower()


def _dates_in_window(text: str, today: dt.date, months: int = 18) -> tuple[int, int]:
    found = [(_MONTHS.index(next(m for m in _MONTHS if m.startswith(mo.lower()))) + 1, int(y))
             for mo, y in _DATE.findall(text)]
    inside = sum((today.year - y) * 12 + (today.month - mth) <= months for mth, y in found)
    return inside, len(found)


def score(reply: str, resp) -> dict:
    p = parse_response(reply)
    body = (p["quotes_section"] + "\n" + p["statistics_section"]) or reply
    urls = list(dict.fromkeys(u.rstrip(".,;") for u in _URL.findall(body)))
    ev = search_evidence(resp) if resp is not None else {"citations": [], "web_searches": 0, "x_searches": 0}
    cited = {_status_id(u) for u in ev["citations"]}
    inside, dated = _dates_in_window(body, dt.date.today())
    return {
        "quotes (app count)": p["quotes_count"],
        "statistics (app count)": p["statistics_count"],
        "links": len(urls),
        "  of them X posts": sum(("x.com/" in u or "twitter.com/" in u) for u in urls),
        "  from own search results": sum(_status_id(u) in cited for u in urls),
        "dates within 18 months": f"{inside}/{dated}",
        "web searches": ev["web_searches"],
        "X searches": ev["x_searches"],
        "chars": len(reply),
    }


async def _compare(script_text: str, title: str, dump_dir: str = "", code_only: bool = False) -> None:
    msg = build_request_message(script_text, title)
    cred = make_credential()
    print(model_line(AGENT_NAME, MODEL, cred) + "  (code agent calls Grok on xAI with X search)")
    print(f"sourcing addendum on code agent: {'on' if sourcing_enabled() else 'OFF'}")
    agents = {"CODE": build_code_agent()}
    if not code_only:
        agents["PORTAL"] = portal_agent(AGENT_NAME, cred)
    print(f"Running {' then '.join(agents)} on the same script...\n")
    replies = {}
    for name, agent in agents.items():
        try:
            replies[name] = await run_response(agent, msg, name.lower())
        except Exception as e:
            replies[name] = e
    scores = {n: (score((r.text or "").strip(), r) if not isinstance(r, Exception) else None)
              for n, r in replies.items()}
    names = list(replies)
    keys = next((list(s.keys()) for s in scores.values() if s), [])
    print("=" * (30 + 16 * len(names)))
    print(f"{'metric':<30}" + "".join(f"{n:>16}" for n in names))
    for k in keys:
        print(f"{k:<30}" + "".join(f"{str(scores[n][k]) if scores[n] else 'ERROR':>16}" for n in names))
    print("=" * (30 + 16 * len(names)) + "\n")
    for n, r in replies.items():
        if isinstance(r, Exception):
            print(f"----- {n}: ERROR {r}\n")
            continue
        p = parse_response((r.text or "").strip())
        print(f"----- {n} agent: quotes section (first 1800 chars) -----")
        print((p["quotes_section"] or (r.text or ""))[:1800] + "\n")
    if dump_dir:
        os.makedirs(dump_dir, exist_ok=True)
        for n, r in replies.items():
            if not isinstance(r, Exception):
                open(os.path.join(dump_dir, f"quotes_{n.lower()}.md"), "w", encoding="utf-8").write(r.text or "")
        print(f"raw replies saved to {dump_dir}/quotes_*.md")


async def _replay(capture_dir: str) -> None:
    """Send the app's recorded Quotes message(s) to the code agent; score both
    replies (the portal reply comes from the capture, so its search counts are n/a)."""
    import json
    recs = [json.loads(line) for line in open(os.path.join(capture_dir, "calls.jsonl"), encoding="utf-8")]
    recs = [r for r in recs if r.get("agent") == AGENT_NAME]
    print(model_line(AGENT_NAME, MODEL, make_credential()) + "  (code agent calls Grok on xAI with X search)")
    for i, rec in enumerate(recs, 1):
        print(f"\n=== recorded call {i}/{len(recs)} ({len(rec['message'])} chars in)")
        resp = await run_response(build_code_agent(), rec["message"], "code")
        cs = score((resp.text or "").strip(), resp)
        ps = score(rec.get("response") or "", None)
        for k in cs:
            pv = ps[k] if k not in ("web searches", "X searches", "  from own search results") else "n/a"
            print(f"  {k:<30}{str(cs[k]):>14}{str(pv):>14}")
        print("\n----- CODE quotes section -----\n" + parse_response((resp.text or "").strip())["quotes_section"][:2000])
        print("\n----- PORTAL quotes section -----\n" + (parse_response(rec.get("response") or "")["quotes_section"]
                                                     or (rec.get("response") or "")[:1500])[:2000])


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description="Code-defined Quotes & Statistics agent on Grok (step 3).")
    ap.add_argument("--script-file", help="Script to research (defaults to the golden reference)")
    ap.add_argument("--title", default="", help="Script title")
    ap.add_argument("--compare", action="store_true", help="Run code and portal agents and compare")
    ap.add_argument("--code-only", action="store_true", help="With --compare: skip the portal call")
    ap.add_argument("--dump", default="", metavar="DIR", help="With --compare: save both replies")
    ap.add_argument("--replay", metavar="CAPTURE_DIR", help="Replay the app's recorded Quotes call(s)")
    args = ap.parse_args()
    print(f"tracing : {setup_tracing()}")
    if args.script_file:
        script = open(args.script_file, encoding="utf-8").read().strip()
        title = args.title or os.path.splitext(os.path.basename(args.script_file))[0]
    else:
        script, title = load_reference_script(), (args.title or REFERENCE_TITLE)
    if args.replay:
        asyncio.run(_replay(args.replay))
    elif args.compare:
        asyncio.run(_compare(script, title, args.dump, args.code_only))
    else:
        r = asyncio.run(generate_quotes_and_statistics(script, title))
        print(r.get("raw_response") or r.get("error"))


if __name__ == "__main__":
    main()
