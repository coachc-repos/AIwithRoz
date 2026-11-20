"""
MAF migration — Step 3, second portal->code conversion: Hook-and-Summary agent.

Re-creates the Foundry portal agent `Script-Hook-and-Summary-Agent` as a
CODE-DEFINED Microsoft Agent Framework agent, seeded from its captured
instructions (../agent_instructions/Script-Hook-and-Summary-Agent.md) and run on
the same model (claude-opus-5-5) via FoundryChatClient.

Drop-in contract: `generate_hook_and_summary()` sends the SAME request message as
`linedrive_azure/agents/hook_and_summary_agent_client.py` and parses the reply
with the SAME section parser, returning the same dict keys web_gui.py reads
(hook1..3, summary, flow_analysis, thumbnail_hook_text_options, ...). It also
returns `opening_statement` / `opening_analysis`, which the app client parses
but never returns (web_gui.py's `hook_result.get("opening_statement")` is
always empty today).

Web search: Foundry's hosted web search tool is attached, as on the portal
agent (see broll.py).

Validate side-by-side (does NOT delete the portal agent):
    maf/.venv/bin/python maf/agents/hook_summary.py --compare
    maf/.venv/bin/python maf/agents/hook_summary.py --script-file path/to/script.md

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
    portal_agent,
    run_response,
    load_instructions as _load_instructions,
    load_reference_script,
    run_portal as _run_portal,
    run_text,
)
from observability import PROJECT_ENDPOINT, load_env, make_credential, setup_tracing  # noqa: E402

AGENT_NAME = "Script-Hook-and-Summary-Agent"   # the portal agent, called by name in --compare
MODEL = os.environ.get("MAF_HOOK_MODEL", CLAUDE_MODEL)
# 16000 like B-Roll: on a full script Opus writes long ANALYSIS blocks and an
# 8000 cap truncated the reply before FLOW ANALYSIS.
MAX_TOKENS = int(os.environ.get("MAF_HOOK_MAX_TOKENS", "16000"))

# Default --compare input: the golden reference (a full 7-chapter script, titled
# REFERENCE_TITLE), since this agent analyzes COMPLETED scripts and checks
# chapter-to-chapter flow.


def load_instructions() -> str:
    """The captured portal instructions (capture-header comment stripped)."""
    return _load_instructions(AGENT_NAME)


def build_code_agent(credential=None) -> Agent:
    """The Hook-and-Summary agent defined in code (seeded from the captured instructions)."""
    return _build_agent(
        name="Script-Hook-and-Summary-Agent (code)",
        instructions=load_instructions(),
        model=MODEL,
        max_tokens=MAX_TOKENS,
        credential=credential,
    )


def build_request_message(
    script_content: str,
    script_title: str,
    target_audience: str = "general audience",
    tone: str = "conversational and educational",
    video_length: str = "10 minutes",
) -> str:
    """Verbatim copy of the request the app client sends (keep in sync)."""
    return f"""
HOOK AND SUMMARY GENERATION REQUEST

SCRIPT DETAILS:
- Title: {script_title}
- Target Audience: {target_audience}
- Tone: {tone}
- Video Length: {video_length}

COMPLETE SCRIPT TO ANALYZE:
{script_content}

TASK:
Generate THREE different hook options (8-10 seconds each), ONE opening statement (15-20 seconds), ONE summary/conclusion (30-45 seconds), THREE thumbnail hook text options for image generation, AND analyze the flow between chapters.

HOOK REQUIREMENTS (GENERATE 3 VARIATIONS):
- Create 3 DIFFERENT hooks using DIFFERENT opening patterns (shocking statement, bold question, personal confession, etc.)
- Each hook should be unique but equally effective
- First 3 seconds must stop the scroll using one of the proven patterns
- Include pattern interrupt at 5-7 seconds
- End with commitment statement (7-10 seconds)
- Total: 25-35 words spoken naturally
- Reference specific elements from the script
- Match the video's tone and audience level

SUMMARY REQUIREMENTS:
- Quick recap of key takeaways (10-15 seconds)
- Satisfying wrap-up with closure (10-15 seconds)
- ONE clear call-to-action (10-15 seconds)
- Total: 90-135 words spoken naturally
- Reference specific tools/concepts from the script
- Create emotional closure and encourage engagement

OPENING STATEMENT REQUIREMENTS:
- Explain what the video is about
- Tease all major chapter topics to maintain watch time
- Total: 45-60 words spoken naturally

THUMBNAIL HOOK REQUIREMENTS:
- Return THREE thumbnail hook text options that can be used directly in thumbnail generation
- Must be short, emotionally strong, and curiosity-driven
- Use FOMO, warning, contrarian framing, or mistake-avoidance when appropriate
- Keep it to 3-8 words
- Prefer punchy thumbnail language, not descriptive summary language
- Avoid bland benefit-copy such as "save time", "save hours", "learn about", "tips for", or generic explanatory phrases
- Favor stronger patterns like second-person challenge, mistake framing, surprising outcome, or AI-powered transformation
- The line should feel clickable and provocative, not merely helpful
- Use the pattern, not the wording, of examples
- Do not copy example phrasing verbatim; generate a fresh line specific to the script topic
- Example pattern types: direct challenge, bold contrarian claim, painful mistake, dramatic shortcut, unexpected transformation
- Return them using these exact field names:
    - THUMBNAIL_HOOK_TEXT_1:
    - THUMBNAIL_HOOK_TEXT_2:
    - THUMBNAIL_HOOK_TEXT_3:

FLOW ANALYSIS REQUIREMENTS:
- Identify chapter transitions (look for "---" separators or chapter markers)
- Check if each chapter ending flows naturally into the next chapter opening
- Note any jarring transitions or disconnects
- Identify chapters that feel isolated vs well-connected
- Rate overall script flow (1-5, where 5 is seamless)
- Suggest 1-2 specific transition improvements if needed

OUTPUT FORMAT (follow exactly):

HOOK OPTION 1 (8-10 SECONDS)
[Complete hook dialogue for option 1]

ANALYSIS:
- 0-3 sec pattern used: [Pattern name]
- 5-7 sec pattern interrupt: [Interrupt technique]
- Aligns with script tone: [Yes/No + note]
- References script content: [Specific elements]

HOOK OPTION 2 (8-10 SECONDS)
[Complete hook dialogue for option 2]

ANALYSIS:
- 0-3 sec pattern used: [Pattern name]
- 5-7 sec pattern interrupt: [Interrupt technique]
- Aligns with script tone: [Yes/No + note]
- References script content: [Specific elements]

HOOK OPTION 3 (8-10 SECONDS)
[Complete hook dialogue for option 3]

ANALYSIS:
- 0-3 sec pattern used: [Pattern name]
- 5-7 sec pattern interrupt: [Interrupt technique]
- Aligns with script tone: [Yes/No + note]
- References script content: [Specific elements]

OPENING STATEMENT (15-20 SECONDS)
[Complete opening statement dialogue]

ANALYSIS:
- Value proposition: [What the video delivers]
- Chapters teased: [Topics mentioned]
- Anticipation level: [High/Medium + why]

SUMMARY/CONCLUSION (30-45 SECONDS)
[Complete summary dialogue]

ANALYSIS:
- Recap format used: [Format A/B/C]
- Wrap-up approach: [Closure type]
- CTA pattern used: [CTA Pattern number]
- Key elements reinforced: [List 2-3 takeaways]

THUMBNAIL HOOK OPTIONS (FOR IMAGE TEXT)
THUMBNAIL_HOOK_TEXT_1: [3-8 words, strong emotional headline]
THUMBNAIL_HOOK_TEXT_2: [3-8 words, strong emotional headline]
THUMBNAIL_HOOK_TEXT_3: [3-8 words, strong emotional headline]

ANALYSIS:
- Hook angle: [FOMO/Warning/Contrarian/Scare-Mistake/Outcome]
- Based on title: [How title informed this line]
- Promise alignment: [How script content supports this claim]
- Readability: [Why this works on a thumbnail]
- Why it is not bland: [Explain why it avoids generic benefit-copy]

FLOW ANALYSIS:
- Number of chapters detected: [Count]
- Overall flow rating: [1-5] - [Brief justification]
- Smooth transitions: [List chapter numbers with good flow]
- Jarring transitions: [List chapter numbers with problems, if any]
- Disconnected sections: [Identify isolated chapters, if any]
- Improvement suggestions: [1-2 specific fixes, or "None needed"]

YOUTUBE STRATEGY ALIGNMENT:
- Hook complements thumbnail text: [How they work together]
- Summary encourages [specific engagement action]
- Overall tone: [Match description]
"""


# --------------------------------------------------------------------------- #
# Response parser — ported from HookAndSummaryAgentClient.generate_hook_and_summary
# (same fields, same labels) and hardened: line-anchored headers, any dash.
# --------------------------------------------------------------------------- #

# Any hyphen/dash the models emit inside "(8-10 SECONDS)": ASCII, U+2010..U+2015.
_DASH = r"[-\u2010-\u2015]"


def _section_between(text: str, start_label: str, end_label: str) -> str:
    """Tolerant of bold/heading markers, missing parens, and extra whitespace.

    Hardened vs. the app client's version: section headers must START A LINE.
    Both agents sometimes open with a preamble that mentions "the opening
    statement", which the unanchored app regex matched as the section header.
    """
    start_pat = re.compile(
        rf"^[ \t]*(?:\*{{0,2}}|#{{0,6}})[ \t]*{start_label}"
        rf"(?:\s*\(\s*\d+\s*(?:{_DASH}|to)?\s*\d+\s*SECONDS?\s*\))?\s*[:\-]?\s*\*{{0,2}}",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    end_pat = re.compile(rf"^[ \t]*(?:\*{{0,2}}|#{{0,6}})[ \t]*{end_label}",
                         flags=re.IGNORECASE | re.MULTILINE)
    m = start_pat.search(text)
    if not m:
        return ""
    tail = text[m.end():]
    m2 = end_pat.search(tail)
    return (tail[:m2.start()] if m2 else tail).strip()


def _split_analysis(section: str) -> tuple[str, str]:
    if not section:
        return "", ""
    a_match = re.search(r"\bANALYSIS\s*:", section, flags=re.IGNORECASE)
    if not a_match:
        return section.strip(), ""
    return section[:a_match.start()].strip(), "ANALYSIS:" + section[a_match.end():].strip()


def _thumbnail_options(text: str) -> list[str]:
    opts: list[str] = []
    for idx in range(1, 4):
        m = re.search(rf'THUMBNAIL_HOOK_TEXT_{idx}\s*:\s*"?([^"\n]+)"?', text, flags=re.IGNORECASE)
        if m and (val := m.group(1).strip().strip('"')):
            opts.append(val)
    if not opts:  # backward-compatible single-field fallback
        m = re.search(r'THUMBNAIL_HOOK_TEXT\s*:\s*"?([^"\n]+)"?', text, flags=re.IGNORECASE)
        if m and (val := m.group(1).strip().strip('"')):
            opts.append(val)
    return opts


# A standalone length note the model sometimes appends to a spoken section, e.g.
# "*(About 122 words, roughly 40 seconds.)*". Left in, the avatar would read it.
_META_NOTE = re.compile(
    r"^[ \t]*\*{0,2}\([^)\n]*\b(?:words?|seconds?)\b[^)\n]*\)\*{0,2}[ \t]*$\n?",
    flags=re.IGNORECASE | re.MULTILINE,
)


def _spoken(text: str) -> str:
    return _META_NOTE.sub("", text).strip()


def parse_hook_response(response_text: str) -> dict:
    """Split the agent reply into the fields web_gui.py reads."""
    h1, a1 = _split_analysis(_section_between(response_text, r"HOOK\s+OPTION\s*1", r"HOOK\s+OPTION\s*2"))
    h2, a2 = _split_analysis(_section_between(response_text, r"HOOK\s+OPTION\s*2", r"HOOK\s+OPTION\s*3"))
    h3, a3 = _split_analysis(_section_between(response_text, r"HOOK\s+OPTION\s*3", r"OPENING\s+STATEMENT"))
    opening, opening_a = _split_analysis(
        _section_between(response_text, r"OPENING\s+STATEMENT", r"SUMMARY\s*/\s*CONCLUSION"))
    summary, summary_a = _split_analysis(
        _section_between(response_text, r"SUMMARY\s*/\s*CONCLUSION", r"FLOW\s+ANALYSIS"))
    flow = _section_between(response_text, r"FLOW\s+ANALYSIS", r"YOUTUBE\s+STRATEGY")
    thumbs = _thumbnail_options(response_text)
    h1, h2, h3, opening, summary = map(_spoken, (h1, h2, h3, opening, summary))
    return {
        "hook": h1,  # back-compat alias the app still reads
        "hook1": h1, "hook2": h2, "hook3": h3,
        "hook1_analysis": a1, "hook2_analysis": a2, "hook3_analysis": a3,
        "opening_statement": opening, "opening_analysis": opening_a,
        "summary": summary, "summary_analysis": summary_a,
        "flow_analysis": flow,
        "thumbnail_hook_text": thumbs[0] if thumbs else "",
        "thumbnail_hook_text_options": thumbs,
    }


async def generate_hook_and_summary(
    script_content: str,
    script_title: str,
    target_audience: str = "general audience",
    tone: str = "conversational and educational",
    video_length: str = "10 minutes",
    credential=None,
) -> dict:
    """Code-agent equivalent of HookAndSummaryAgentClient.generate_hook_and_summary()."""
    msg = build_request_message(script_content, script_title, target_audience, tone, video_length)
    try:
        text = await run_text(build_code_agent(credential), msg, "code")
    except Exception as e:
        return {"success": False, "error": f"Hook-and-Summary generation failed: {e}",
                "hook": None, "summary": None}
    return {"success": True, **parse_hook_response(text), "full_response": text,
            "script_title": script_title, "audience": target_audience, "tone": tone}


async def run_code(script_text: str, title: str, credential=None) -> str:
    return await run_text(build_code_agent(credential),
                          build_request_message(script_text, title), "code")


async def run_portal(script_text: str, title: str, credential=None) -> str:
    """The existing portal agent, called by name (the step-1 pattern)."""
    return await _run_portal(AGENT_NAME, build_request_message(script_text, title), credential)


# --------------------------------------------------------------------------- #
# --compare: score both outputs with the app's own parser + the prompt's targets
# --------------------------------------------------------------------------- #

def _words(s: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", s or ""))


def _flow_rating(flow: str) -> str:
    m = re.search(r"flow rating\W*\s*(\d(?:\.\d)?)", flow or "", flags=re.IGNORECASE)
    return m.group(1) if m else "-"


def _stats(text: str) -> dict:
    p = parse_hook_response(text)
    return {
        "chars": len(text),
        "hooks_parsed (3)": sum(bool(p[k]) for k in ("hook1", "hook2", "hook3")),
        "hook1_words (25-35)": _words(p["hook1"]),
        "hook2_words (25-35)": _words(p["hook2"]),
        "hook3_words (25-35)": _words(p["hook3"]),
        "opening_words (45-60)": _words(p["opening_statement"]),
        "summary_words (90-135)": _words(p["summary"]),
        "thumbnail_opts (3)": len(p["thumbnail_hook_text_options"]),
        "flow_analysis": bool(p["flow_analysis"]),
        "flow_rating (1-5)": _flow_rating(p["flow_analysis"]),
    }


def _show(label: str, text: str) -> None:
    p = parse_hook_response(text)
    print(f"----- {label} -----")
    if not any(p[k] for k in ("hook1", "hook2", "hook3")):
        print(f"(no sections parsed) raw reply, first 1500 chars:\n{text[:1500]}\n")
        return
    for i in (1, 2, 3):
        print(f"HOOK {i}: {p[f'hook{i}']}\n")
    print(f"OPENING: {p['opening_statement']}\n")
    print(f"SUMMARY: {p['summary']}\n")
    print("THUMBNAIL: " + " | ".join(p["thumbnail_hook_text_options"]) + "\n")


async def _compare(script_text: str, title: str, dump_dir: str = "") -> None:
    # One shared credential, run sequentially — avoids two concurrent
    # `az` token fetches + connection setups (the transient DNS flake).
    cred = make_credential()
    print(model_line(AGENT_NAME, MODEL, cred))
    print("Running CODE agent, then PORTAL agent, on the same script...\n")
    msg = build_request_message(script_text, title)
    code_resp = await run_response(build_code_agent(cred), msg, "code")
    portal_resp = await run_response(portal_agent(AGENT_NAME, cred), msg, "portal")
    code_out, portal_out = (code_resp.text or "").strip(), (portal_resp.text or "").strip()
    print(f"search  : code {evidence_line(code_resp)} | portal {evidence_line(portal_resp)}")
    if dump_dir:
        os.makedirs(dump_dir, exist_ok=True)
        for name, out in (("code", code_out), ("portal", portal_out)):
            with open(os.path.join(dump_dir, f"hook_summary_{name}.md"), "w", encoding="utf-8") as f:
                f.write(out)
        print(f"raw outputs saved to {dump_dir}/hook_summary_{{code,portal}}.md\n")
    cs, ps = _stats(code_out), _stats(portal_out)
    print("==================== COMPARISON ====================")
    print(f"{'metric':<26}{'CODE':>12}{'PORTAL':>12}")
    for k in cs:
        print(f"{k:<26}{str(cs[k]):>12}{str(ps[k]):>12}")
    print("====================================================\n")
    _show("CODE agent", code_out)
    _show("PORTAL agent", portal_out)


async def _replay(capture_dirs: list[str]) -> None:
    """Send the app's recorded Hook-and-Summary messages to the code agent and
    score both replies with the app's parser (portal replies come from the capture)."""
    import json
    cred = make_credential()
    print(model_line(AGENT_NAME, MODEL, cred))
    for d in capture_dirs:
        recs = [json.loads(line) for line in open(os.path.join(d, "calls.jsonl"), encoding="utf-8")]
        for rec in (r for r in recs if r.get("agent") == AGENT_NAME):
            resp = await run_response(build_code_agent(cred), rec["message"], "code")
            cs, ps = _stats((resp.text or "").strip()), _stats(rec.get("response") or "")
            print(f"\n=== {os.path.basename(d)}: recorded call ({len(rec['message'])} chars in) [{evidence_line(resp)}]")
            for k in cs:
                print(f"  {k:<26}{str(cs[k]):>12}{str(ps[k]):>12}")


def _read_script(args) -> tuple[str, str]:
    if args.script_file:
        with open(args.script_file, "r", encoding="utf-8") as f:
            text = f.read().strip()
        title = args.title or os.path.splitext(os.path.basename(args.script_file))[0]
        return text, title
    return load_reference_script(), (args.title or REFERENCE_TITLE)


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description="Code-defined Hook-and-Summary MAF agent (step 3).")
    ap.add_argument("--script-file", help="Path to a .md/.txt script (defaults to the golden reference)")
    ap.add_argument("--title", default="", help="Script title")
    ap.add_argument("--compare", action="store_true",
                    help="Run BOTH the code agent and the portal agent and compare")
    ap.add_argument("--dump", default="", metavar="DIR",
                    help="With --compare: also save both raw replies to DIR")
    ap.add_argument("--replay", nargs="+", metavar="CAPTURE_DIR",
                    help="Replay the app's recorded Hook-and-Summary calls from capture dirs")
    args = ap.parse_args()

    status = setup_tracing()
    if args.replay:
        asyncio.run(_replay(args.replay))
        return
    script_text, title = _read_script(args)
    print("ScriptCraft MAF — Hook-and-Summary agent (portal -> code conversion)")
    print(f"project : {PROJECT_ENDPOINT}")
    print(f"model   : {MODEL} (via FoundryChatClient)  max_tokens={MAX_TOKENS}")
    print(f"tracing : {status}")
    print(f"title   : {title}  ({len(script_text)} chars)\n")

    if args.compare:
        asyncio.run(_compare(script_text, title, args.dump))
    else:
        result = asyncio.run(generate_hook_and_summary(script_text, title))
        if not result["success"]:
            sys.exit(result["error"])
        print(result["full_response"])


if __name__ == "__main__":
    main()
