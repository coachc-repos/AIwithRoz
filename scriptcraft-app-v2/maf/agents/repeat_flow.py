"""
MAF migration — Step 3, third portal->code conversion: Repeat-and-Flow agent.

Re-creates the Foundry portal agent `Script-Repeat-and-Flow-Agent` as a
CODE-DEFINED Microsoft Agent Framework agent, seeded from its captured
instructions (../agent_instructions/Script-Repeat-and-Flow-Agent.md) and run on
the same model (claude-opus-5-5) via FoundryChatClient.

This is the first TRANSFORM agent: it returns a rewritten script that replaces
the user's script in the app (web_gui.py, "flow_analysis" checkbox). So parity
is judged on what the app would actually save, not just on whether a reply came
back:
  * the app masks every [PRODUCTION BEGIN]…[PRODUCTION END] block as
    [[PRODUCTION_BLOCK_N]] first, and if the agent drops ANY placeholder it
    silently keeps the pre-rewrite script (see _production_blocks.py);
  * chapters, chapter-heading format, length, trailing sections (research,
    packaging, YouTube description), and voice punctuation must survive.

Drop-in contract: `analyze_and_improve_flow()` sends the SAME request message as
`linedrive_azure/agents/script_repeat_and_flow_agent_client.py` and returns the
same keys web_gui.py reads (improved_script, repetition_analysis,
flow_analysis, raw_response). Two deliberate safety differences: a reply with no
"=== REVISED COMPLETE SCRIPT ===" section, or one cut off by max_tokens, returns
success=False (the app client would paste the whole reply, analysis included,
in as the new script).

The code agent's instructions are the captured prompt PLUS a short APP_CONTRACT
addendum (keep placeholders, keep the heading layout, drop nothing, add nothing
after the script). The portal
prompt never states these rules; see APP_CONTRACT for the failures behind each.
MAF_FLOW_APP_CONTRACT=0 runs the bare captured prompt for A/B checks.

Web search: Foundry's hosted web search tool is attached, as on the portal
agent (see broll.py).

Validate side-by-side (does NOT delete the portal agent):
    maf/.venv/bin/python maf/agents/repeat_flow.py --compare --dump /tmp/flow_cmp
    maf/.venv/bin/python maf/agents/repeat_flow.py --compare --code-only --script-file s.md
    maf/.venv/bin/python maf/agents/repeat_flow.py --script-file path/to/script.md

Scoped to maf/, no web_gui.py changes, isolated venv.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import Agent  # noqa: E402

from agents._common import (  # noqa: E402
    CLAUDE_MODEL,
    REFERENCE_TITLE,
    build_code_agent as _build_agent,
    evidence_line,
    model_line,
    is_truncated,
    load_instructions as _load_instructions,
    load_reference_script,
    portal_agent,
    run_response,
)
from agents._production_blocks import (  # noqa: E402
    mask_production_blocks,
    restore_or_keep,
)
from agents._script_metrics import fmt_chapters, script_stats  # noqa: E402
from observability import PROJECT_ENDPOINT, load_env, make_credential, setup_tracing  # noqa: E402

AGENT_NAME = "Script-Repeat-and-Flow-Agent"   # the portal agent, called by name in --compare
MODEL = os.environ.get("MAF_FLOW_MODEL", CLAUDE_MODEL)
# The reply is an analysis PLUS the full rewritten script, so it is the longest
# output of the converted agents so far. 32000 matches the Pro writer.
MAX_TOKENS = int(os.environ.get("MAF_FLOW_MAX_TOKENS", "32000"))


# The app's contract, which the captured portal prompt never states. Appended to
# the captured instructions in code (the .md capture stays verbatim). Each rule
# answers a failure seen in --compare on 2026-10-07:
#   1. The portal agent dropped every [[PRODUCTION_BLOCK_N]] placeholder on both
#      test scripts, so the app discarded its rewrite. The code agent kept them
#      in every run, even with the script's "PARSER RULE" hint removed, so this
#      rule is insurance: the prompt itself never mentions placeholders.
#   2. The request's sample layout "## Chapter 1: [Title] (X:XX)" made the code
#      agent convert "Heading: Chapter N - Title" lines and invent timestamps in
#      2 of 3 runs without this addendum, and 0 of 2 runs with it.
#   3. The portal agent dropped the title block, FINAL HOOK, trailing notes, and
#      the appended HeyGen-ready copy. The code agent never did; insurance.
#   4. 3 of 5 replies without this addendum (both portal runs, one code run)
#      appended revision notes, a "- [x]" checklist, or a "Let me know…" sign-off
#      AFTER the script, which the app would save as part of the script.
# Set MAF_FLOW_APP_CONTRACT=0 to run the bare captured prompt (for A/B checks).
APP_CONTRACT = """

## App contract (added in code; overrides the sample layout in the request)

1. Placeholders. The script contains placeholders such as [[PRODUCTION_BLOCK_0]]. Each one stands for a production note that the app restores after your revision. Copy every placeholder exactly as written, on its own line, in the same position relative to the dialogue around it. Never remove, renumber, merge, reword, or move a placeholder, even when you cut or rewrite the dialogue next to it. If any placeholder is missing, the app throws away your entire revision.
2. Layout. Keep the script's existing layout. Keep every heading line exactly as written, for example "Heading: Chapter 3 - Title", and keep the "Host:" labels where they are. The "## Chapter 1: [Title] (X:XX)" layout in the request is only an example. Do not convert headings to it, and do not add timestamps.
3. Completeness. Do not drop any part of the script. Keep the title block and hook before the first chapter, and every section after the last chapter, such as research notes, packaging notes, the video description, and any appended copy of the script.
4. Nothing after the script. The revised script must be the last thing in your reply. Put any notes, checklists, or verification above the "=== REVISED COMPLETE SCRIPT ===" line, and add no sign-off after the script.
"""


def app_contract_enabled() -> bool:
    return os.environ.get("MAF_FLOW_APP_CONTRACT", "1").strip().lower() not in ("0", "false", "no", "off")


def load_instructions() -> str:
    """The captured portal instructions (capture-header comment stripped)."""
    return _load_instructions(AGENT_NAME)


def code_agent_instructions() -> str:
    """Captured instructions, plus the app contract unless MAF_FLOW_APP_CONTRACT=0."""
    return load_instructions() + (APP_CONTRACT if app_contract_enabled() else "")


def build_code_agent(credential=None) -> Agent:
    """The Repeat-and-Flow agent defined in code (captured instructions + app contract)."""
    return _build_agent(
        name="Script-Repeat-and-Flow-Agent (code)",
        instructions=code_agent_instructions(),
        model=MODEL,
        max_tokens=MAX_TOKENS,
        credential=credential,
    )


def build_request_message(
    script_content: str,
    script_title: str | None = None,
    target_audience: str = "general",
) -> str:
    """Verbatim copy of the request the app client sends (keep in sync)."""
    return f"""Analyze this COMPLETE VIDEO SCRIPT for repetitive content and flow issues.

**SCRIPT TITLE:** {script_title or "YouTube Educational Video"}
**TARGET AUDIENCE:** {target_audience}

**COMPLETE SCRIPT TO ANALYZE:**
{script_content}

**YOUR TASK:**

1. **Read the ENTIRE script** and identify ALL repetitive content:
   - Duplicate tips/advice appearing in multiple chapters
   - Redundant examples or analogies
   - Repeated definitions or explanations
   - Overlapping "how it works" sections
   - Rehashed statistics or facts

2. **Analyze flow between ALL chapters**:
   - Chapter-to-chapter transitions (smooth or jarring?)
   - Pacing issues (too dense, dragging, uneven?)
   - Narrative arc problems (weak conclusions, confusing structure?)

3. **Create detailed analysis report** showing:
   - What repetitions were found and where
   - What was removed vs. preserved (and why)
   - What flow issues were identified
   - What improvements were made

4. **Deliver COMPLETE REVISED SCRIPT** with:
   - All problematic repetitions removed
   - All flow issues corrected
   - ALL chapters with FULL dialogue (no summaries or condensing)
   - Smooth transitions between chapters
   - Voice-friendly punctuation (no em-dashes, arrows, en-dashes)

**CRITICAL RULES:**
- Remove ONLY problematic repetition (preserve intentional callbacks)
- **PRESERVE ALL HOOK OPTIONS** - Do NOT remove or consolidate "OPENING HOOK OPTIONS" section (these are intentional creative choices, not repetition)
- Keep ALL chapters at FULL length
- Maintain engaging, conversational tone
- Ensure voice-friendly punctuation throughout
- Make script feel like one cohesive narrative

**OUTPUT FORMAT:**

=== REPETITION ANALYSIS ===

**Duplicate Content Found:**
1. [Description] - Found in Chapters X, Y, Z
   - ACTION: Removed from [locations], kept in [best location]
   - REASON: [why this location is best]

[Continue for all repetitions found]

**Flow Issues Identified:**
1. [Issue description between Chapters X and Y]
   - FIX: [what was done]

[Continue for all flow issues]

=== REVISED COMPLETE SCRIPT ===

[FULL SCRIPT with all chapters, complete dialogue, repetitions removed, flow improved]

## Chapter 1: [Title] (X:XX)

[Visual Cue: Description]

**Host:**
[Complete dialogue with improvements]

[Continue for ALL chapters]
"""


# --------------------------------------------------------------------------- #
# Response parser — same sections and keys as
# ScriptRepeatAndFlowAgentClient.analyze_and_improve_flow, with line-anchored,
# wrapper-tolerant markers: "=== REVISED COMPLETE SCRIPT ===", bold or "#"-
# wrapped variants of it, and the markdown-heading form "### REVISED COMPLETE
# SCRIPT" (the portal agent used that once; the app's exact-text check misses it).
# --------------------------------------------------------------------------- #

def _marker(label: str) -> re.Pattern:
    return re.compile(
        rf"^[ \t]*[#*]*[ \t]*(?:={{2,}}[ \t]*{label}[ \t]*={{2,}}|(?<=#)[ \t]*\**{label}\**:?)[ \t]*\**[ \t]*$",
        flags=re.IGNORECASE | re.MULTILINE,
    )


_REVISED = _marker(r"REVISED\s+COMPLETE\s+SCRIPT")
_REPETITION = _marker(r"REPETITION\s+ANALYSIS")
_STRUCTURE = _marker(r"STRUCTURE\s+CHECK")
# "Flow Issues Identified:" per the request; replies also say "Flow issues found:".
_FLOW_ISSUES = re.compile(r"^[ \t]*#*[ \t]*\**[ \t]*Flow\s+Issues\s+(?:Identified|Found):?\**:?[ \t]*$",
                          flags=re.IGNORECASE | re.MULTILINE)


def parse_flow_response(text: str) -> dict:
    """Split the agent reply into structure check, repetition/flow analysis, and
    the revised script. `marker_found` is False when there is no revised-script
    section (the app client would then use the WHOLE reply as the script)."""
    out = {"marker_found": False, "improved_script": "", "structure_check": "",
           "repetition_analysis": "", "flow_analysis": ""}
    m = _REVISED.search(text or "")
    if not m:
        return out
    out["marker_found"] = True
    out["improved_script"] = text[m.end():].strip()
    analysis = text[:m.start()]

    rep = _REPETITION.search(analysis)
    if rep:
        st = _STRUCTURE.search(analysis[:rep.start()])
        if st:
            out["structure_check"] = analysis[st.end():rep.start()].strip()
        rep_text = analysis[rep.end():]
        fl = _FLOW_ISSUES.search(rep_text)
        if fl:
            out["repetition_analysis"] = rep_text[:fl.start()].strip()
            out["flow_analysis"] = "**Flow Issues Identified:**\n" + rep_text[fl.end():].strip()
        else:
            out["repetition_analysis"] = rep_text.strip()
    return out


def restore_missing_chapter_one(improved_script: str, original_script: str) -> str:
    """Verbatim port of ScriptRepeatAndFlowAgentClient._restore_missing_chapter_one:
    if the first chapter heading in the rewrite is Chapter 2+, put Chapter 1's
    heading back right above it."""
    if not improved_script:
        return improved_script
    chapter_re = re.compile(
        r"(?:^|\n)[ \t]*(?:#+[ \t]*)?\*{0,2}(Chapter\s+(\d+)\b[^\n]*)",
        re.IGNORECASE,
    )
    first_match = chapter_re.search(improved_script)
    if not first_match or int(first_match.group(2)) <= 1:
        return improved_script
    original_match = chapter_re.search(original_script or "")
    if original_match and int(original_match.group(2)) == 1:
        ch1_heading = original_match.group(1).strip()
    else:
        ch1_heading = "Chapter 1 - Introduction"
    insert_at = first_match.start(1)
    prefix = improved_script[:insert_at].rstrip()
    suffix = improved_script[insert_at:]
    return f"{prefix}\n\n{ch1_heading}\n\n{suffix}"


def _result_from_reply(text: str, truncated: bool, script_content: str) -> dict:
    if truncated:
        return {"success": False, "raw_response": text,
                "error": "Flow agent reply hit max_tokens; the revised script is incomplete"}
    p = parse_flow_response(text)
    if not p["marker_found"]:
        return {"success": False, "raw_response": text,
                "error": "Flow agent reply has no '=== REVISED COMPLETE SCRIPT ===' section"}
    return {
        "success": True,
        "improved_script": restore_missing_chapter_one(p["improved_script"], script_content),
        "repetition_analysis": p["repetition_analysis"],
        "flow_analysis": p["flow_analysis"],
        "structure_check": p["structure_check"],
        "raw_response": text,
    }


async def analyze_and_improve_flow(
    script_content: str,
    script_title: str | None = None,
    target_audience: str = "general",
    credential=None,
) -> dict:
    """Code-agent equivalent of ScriptRepeatAndFlowAgentClient.analyze_and_improve_flow().
    Like the app client, it expects the caller to have masked production blocks."""
    msg = build_request_message(script_content, script_title, target_audience)
    try:
        resp = await run_response(build_code_agent(credential), msg, "code")
    except Exception as e:
        return {"success": False, "raw_response": None,
                "error": f"Exception during script flow analysis: {e}"}
    return _result_from_reply((resp.text or "").strip(), is_truncated(resp), script_content)


# --------------------------------------------------------------------------- #
# --compare: score what the APP would save from each agent's reply
# --------------------------------------------------------------------------- #

async def _compare(script_text: str, title: str, dump_dir: str = "", code_only: bool = False) -> None:
    masked, blocks = mask_production_blocks(script_text)
    msg = build_request_message(masked, title, "general")
    print(f"Masked {len(blocks)} production blocks, as the app does. Request: {len(msg)} chars. "
          f"App contract on code agent: {'on' if app_contract_enabled() else 'OFF'}.")
    cred = make_credential()
    print(model_line(AGENT_NAME, MODEL, cred))
    agents = {"CODE": build_code_agent(cred)}
    if not code_only:
        agents["PORTAL"] = portal_agent(AGENT_NAME, cred)
    print(f"Running {' then '.join(agents)} on the same script...\n")
    replies = {}
    for name, agent in agents.items():  # sequential: avoids the concurrent-DNS flake
        replies[name] = await run_response(agent, msg, name.lower())
    print("search  : " + " | ".join(f"{n.lower()} {evidence_line(r)}" for n, r in replies.items()) + "\n")

    orig = script_stats(masked)
    names = list(replies)
    cols, results = {"ORIGINAL": orig}, {}
    for name, resp in replies.items():
        text = (resp.text or "").strip()
        res = _result_from_reply(text, is_truncated(resp), masked)
        results[name] = (text, res, is_truncated(resp))
        cols[name] = script_stats(res.get("improved_script", "")) if res["success"] else None

    n_blocks = len(blocks)
    all_blocks = set(range(n_blocks))

    def agent_only(fn):
        return lambda n: "-" if n == "ORIGINAL" else fn(n)

    def stat(fn):
        return lambda n: "-" if cols[n] is None else fn(cols[n])

    ok = lambda n: results[n][1]["success"]
    rows = [
        ("reply chars", agent_only(lambda n: str(len(results[n][0])))),
        ("truncated", agent_only(lambda n: "YES" if results[n][2] else "no")),
        ("parsed OK", agent_only(lambda n: "yes" if ok(n) else "NO")),
        ("structure check", agent_only(lambda n: "-" if not ok(n) else ("yes" if results[n][1]["structure_check"] else "no"))),
        ("repetition analysis ch", agent_only(lambda n: "-" if not ok(n) else str(len(results[n][1]["repetition_analysis"])))),
        ("flow analysis ch", agent_only(lambda n: "-" if not ok(n) else str(len(results[n][1]["flow_analysis"])))),
        ("chapters", stat(lambda s: fmt_chapters(s["chapter_nums"]))),
        ("'Heading:' lines", stat(lambda s: str(s["heading_prefix"]))),
        ("timestamps in headings", stat(lambda s: str(s["heading_timestamps"]))),
        ("hook/header words", stat(lambda s: str(s["pre_chapter_words"]))),
        ("chapter words", stat(lambda s: str(s["total_chapter_words"]))),
        ("  vs original", stat(lambda s: f"{s['total_chapter_words'] / max(1, orig['total_chapter_words']):.0%}")),
        (f"placeholders kept /{n_blocks}", stat(lambda s: str(len(s["placeholders"] & all_blocks)))),
        ("APP KEEPS REWRITE", agent_only(lambda n: "-" if cols[n] is None else ("yes" if cols[n]["placeholders"] >= all_blocks else "NO (discarded)"))),
        ("em/en dash, arrow", stat(lambda s: str(s["dashes_arrows"]))),
        ("contractions", stat(lambda s: str(s["contractions"]))),
        ("no-break/thin spaces", stat(lambda s: str(s["odd_spaces"]))),
        ("agent notes in script", stat(lambda s: str(s["agent_notes"]))),
        (f"trailing sections /{len(orig['sections'])}", stat(lambda s: str(len(set(s["sections"]) & set(orig["sections"]))))),
    ]
    order = ["ORIGINAL"] + names
    width = 26 + 16 * len(order)
    print("=" * width)
    print(f"{'metric':<26}" + "".join(f"{n:>16}" for n in order))
    for label, fn in rows:
        print(f"{label:<26}" + "".join(f"{fn(n):>16}" for n in order))
    print("=" * width + "\n")
    if orig["sections"]:
        print("trailing sections in original: " + "; ".join(orig["sections"]) + "\n")

    print(f"{'words per chapter':<26}" + "".join(f"{n:>16}" for n in order))
    for ch in sorted(orig["chapter_words"]):
        vals = [str(orig["chapter_words"][ch])] + [
            "-" if cols[n] is None else str(cols[n]["chapter_words"].get(ch, "missing")) for n in names]
        print(f"{'  Chapter ' + str(ch):<26}" + "".join(f"{v:>16}" for v in vals))
    print()

    for name, (text, res, _) in results.items():
        print(f"----- {name} agent: analysis (first 1500 chars) -----")
        if res["success"]:
            print((("STRUCTURE CHECK:\n" + res["structure_check"] + "\n\n") if res["structure_check"] else "")
                  + res["repetition_analysis"][:1500])
        else:
            print(f"FAILED: {res['error']}\n{text[:800]}")
        print()

    if dump_dir:
        os.makedirs(dump_dir, exist_ok=True)
        for name, (text, res, _) in results.items():
            low = name.lower()
            with open(os.path.join(dump_dir, f"flow_{low}_reply.md"), "w", encoding="utf-8") as f:
                f.write(text)
            if res["success"]:
                saved, _applied = restore_or_keep(res["improved_script"], blocks, script_text)
                with open(os.path.join(dump_dir, f"flow_{low}_app_saves.md"), "w", encoding="utf-8") as f:
                    f.write(saved)
        print(f"raw replies + the script the app would save are in {dump_dir}/flow_*.md")


def _read_script(args) -> tuple[str, str]:
    if args.script_file:
        with open(args.script_file, "r", encoding="utf-8") as f:
            text = f.read().strip()
        title = args.title or os.path.splitext(os.path.basename(args.script_file))[0]
        return text, title
    return load_reference_script(), (args.title or REFERENCE_TITLE)


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description="Code-defined Repeat-and-Flow MAF agent (step 3).")
    ap.add_argument("--script-file", help="Path to a .md/.txt script (defaults to the golden reference)")
    ap.add_argument("--title", default="", help="Script title")
    ap.add_argument("--compare", action="store_true",
                    help="Run BOTH the code agent and the portal agent and compare")
    ap.add_argument("--dump", default="", metavar="DIR",
                    help="With --compare: save raw replies and the script the app would save")
    ap.add_argument("--code-only", action="store_true",
                    help="With --compare: score only the code agent (skip the portal call)")
    args = ap.parse_args()

    status = setup_tracing()
    script_text, title = _read_script(args)
    print("ScriptCraft MAF — Repeat-and-Flow agent (portal -> code conversion)")
    print(f"project : {PROJECT_ENDPOINT}")
    print(f"model   : {MODEL} (via FoundryChatClient)  max_tokens={MAX_TOKENS}")
    print(f"contract: {'on' if app_contract_enabled() else 'OFF'} (MAF_FLOW_APP_CONTRACT)")
    print(f"tracing : {status}")
    print(f"title   : {title}  ({len(script_text)} chars)\n")

    if args.compare:
        asyncio.run(_compare(script_text, title, args.dump, args.code_only))
        return
    masked, blocks = mask_production_blocks(script_text)
    result = asyncio.run(analyze_and_improve_flow(masked, title))
    if not result["success"]:
        sys.exit(result["error"])
    saved, applied = restore_or_keep(result["improved_script"], blocks, script_text)
    if not applied:
        print("WARNING: the agent dropped a production-block placeholder, so the app "
              "would keep the original script.", file=sys.stderr)
    print(saved)


if __name__ == "__main__":
    main()
