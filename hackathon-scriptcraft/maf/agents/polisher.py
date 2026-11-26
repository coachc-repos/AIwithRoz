"""
MAF migration — Step 3: Script-Polisher-Agent as code.

Re-creates the Foundry portal agent `Script-Polisher-Agent` as a CODE-DEFINED
Microsoft Agent Framework agent on Claude Opus 5.5 with Foundry's hosted web
search (its prompt asks for real online tools per chapter). Only the legacy
console UI calls it (console_ui/workflows.py: polish_script); the web app does
not.

Drop-in contract: `polish_script()` sends the SAME request as
`linedrive_azure/agents/script_polisher_agent_client.py` polish_script()
(checked byte-for-byte) and returns {"success", "response", "error"} like
send_message.

--compare runs the code agent and the portal agent on the same script and
scores the polished script: chapters, one visual cue per chapter (the
request's rule), Host words against the input, and tool links.

    maf/.venv/bin/python maf/agents/polisher.py --compare --dump /tmp/polish_cmp

Scoped to maf/, no web_gui.py changes, isolated venv.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import Agent  # noqa: E402

from agents._common import (  # noqa: E402
    CLAUDE_MODEL,
    REFERENCE_TITLE,
    build_code_agent as _build_agent,
    evidence_line,
    is_truncated,
    load_instructions as _load_instructions,
    load_reference_script,
    model_line,
    portal_agent,
    run_response,
    search_evidence,
)
from agents._script_metrics import app_host_words  # noqa: E402
from observability import load_env, make_credential, setup_tracing  # noqa: E402

AGENT_NAME = "Script-Polisher-Agent"
MODEL = os.environ.get("MAF_POLISHER_MODEL", CLAUDE_MODEL)
MAX_TOKENS = int(os.environ.get("MAF_POLISHER_MAX_TOKENS", "32000"))


# Markup rules the captured portal prompt never states. On the golden reference
# (2026-10-07) the PORTAL agent rewrote 20 of 29 "[PRODUCTION BEGIN]" markers as
# "[PRODUCTION_BEGIN]" (the app's production-block regex needs the space), and
# the code agent did the same 15 times and prefixed every "Heading:" line with
# an em-dash. MAF_POLISHER_APP_CONTRACT=0 runs the bare captured prompt.
APP_CONTRACT = """

## App contract (added in code)

1. Keep the script's markup exactly as written: every "Heading: Chapter N - Title" line (add nothing before "Heading:"), every "Host:" label, and the production markers [PRODUCTION BEGIN] and [PRODUCTION END] with a space (never an underscore), together with everything between them.
2. Put your additions, such as visual cues and tool demos, on their own lines. Never edit or reflow an existing line to make room for them.
"""


def app_contract_enabled() -> bool:
    return os.environ.get("MAF_POLISHER_APP_CONTRACT", "1").strip().lower() not in ("0", "false", "no", "off")


def load_instructions() -> str:
    return _load_instructions(AGENT_NAME)


def build_code_agent(credential=None) -> Agent:
    return _build_agent(name="Script-Polisher-Agent (code)",
                        instructions=load_instructions() + (APP_CONTRACT if app_contract_enabled() else ""),
                        model=MODEL, max_tokens=MAX_TOKENS, credential=credential)


def build_request_message(raw_script: str, script_title: Optional[str] = None,
                          target_audience: str = "general", production_type: str = "video",
                          special_requirements: Optional[str] = None) -> str:
    """Verbatim copy of the client's polish_script() request (keep in sync)."""
    if not script_title:
        for line in raw_script.split("\n")[:10]:
            if line.strip() and not line.startswith("#"):
                script_title = line.strip()
                break
        if not script_title:
            script_title = "Untitled Script"
    return f"""
        MANDATORY INSTRUCTION: You are a script polisher specializing in final production preparation. 
        You must immediately analyze and polish the provided script. DO NOT ask clarifying questions. 
        DO NOT request additional information. USE THE PROVIDED SCRIPT AND CREATE THE POLISHED VERSION NOW.

        IMMEDIATE ACTION REQUIRED: Polish the following script for final production:

        SCRIPT TO POLISH:
        {raw_script}

        POLISHING REQUIREMENTS:
        - Script Title: {script_title}
        - Target Audience: {target_audience}
        - Production Type: {production_type}
        
        CRITICAL POLISHING STANDARDS:
        1. CHAPTER STRUCTURE: Create clear chapter divisions with descriptive titles
           - Each chapter should be 2-4 minutes of content
           - Logical progression and flow between chapters
           - Clear transitions and chapter breaks
        
        2. VISUAL CUE REQUIREMENTS: Add exactly ONE visual cue per chapter
           - Format: [Visual Cue: Description of what should be shown]
           - Place visual cues at strategically important moments
           - Visual cues should enhance understanding and engagement
           - Examples: [Visual Cue: Show screen recording of the tool interface]
           - Examples: [Visual Cue: Display comparison chart of pricing options]
           - Examples: [Visual Cue: Show step-by-step animation of the process]
        
        3. TOOL INTEGRATION: Ensure at least ONE online tool is mentioned per chapter
           - Each tool must be REAL and currently available
           - Include complete URLs where applicable
           - Provide specific instructions on how to access/use each tool
           - Add discovery information (YouTube search terms, etc.)
           - Include pricing information where relevant
           - Examples: ChatGPT (chat.openai.com), Canva (canva.com), Notion (notion.so)
        
        4. FLOW OPTIMIZATION:
           - Smooth transitions between topics and chapters
           - Natural pacing and rhythm
           - Engaging hooks and retention elements
           - Clear narrative progression
        
        5. CONTENT FOCUS:
           - Keep the script focused on the host content
           - Avoid production timing blocks (no [00:00 - 00:05] timestamps)
           - Skip AUDIO/VISUAL/TRANSITION production elements
           - Focus on the actual spoken content and tool demonstrations
        
        EXISTING CONTENT REVIEW:
        - If the script already has visual cues, review them and suggest improvements
        - If chapters already exist, optimize their structure and flow
        - If tools are already mentioned, ensure they meet quality standards
        - Add your analysis and recommendations in a separate section
        
        OUTPUT FORMAT:
        Please structure your response as:

        # POLISHED SCRIPT: {script_title}

        ## REVISION SUGGESTIONS
        [Provide specific suggestions for improving the script, including:]
        - Content enhancement recommendations
        - Flow and pacing suggestions
        - Engagement improvements
        - Technical considerations for {production_type} format

        ## TOOLS TO DEMO
        [List of real online tools that should be demonstrated, with:]
        - Tool name and purpose
        - When to show it in the script (reference line numbers or sections)
        - What specific features to highlight
        - Access information (free/paid, signup required, etc.)

        ## VISUAL CUES TO ADD
        [List of visual cues to add inline with the script, with:]
        - Specific placement instructions (after which line/paragraph)
        - Detailed description of what to show
        - Duration and timing suggestions

        ## ORIGINAL SCRIPT WITH INLINE ADDITIONS
        [The complete original script text with ONLY these additions:]
        - **Visual Cue:** [Description] - added inline at appropriate moments
        - **Tool Demo:** [Tool name and action] - added where tools should be shown
        - Keep ALL original text exactly as provided
        - Do NOT rewrite or change the original content
        - Only INSERT visual cues and tool demo markers

        ## PRODUCTION NOTES
        [Additional technical notes for the production team]

        ABSOLUTE REQUIREMENTS:
        - Preserve the original script text completely unchanged
        - Only add inline **Visual Cue:** and **Tool Demo:** markers
        - Provide clear suggestions in the dedicated sections above
        - Do not rewrite, restructure, or modify the original content
        - Ensure tool demos are practical and accessible
        - Make visual cues specific and actionable
        - Optimize suggestions for {production_type} production format
        - NEVER add production timing blocks like [00:00 - 00:05]
        - NEVER add AUDIO: XXX / VISUAL: XXX / TRANSITION: elements
        - NEVER add NOTES FOR PRODUCER: sections
        - Focus on content the host will actually speak or demonstrate
        """


async def polish_script(raw_script: str, script_title: Optional[str] = None, target_audience: str = "general",
                        production_type: str = "video", special_requirements: Optional[str] = None,
                        credential=None, agent=None, label: str = "code") -> dict:
    agent = agent or build_code_agent(credential)
    try:
        resp = await run_response(agent, build_request_message(
            raw_script, script_title, target_audience, production_type, special_requirements), label)
    except Exception as e:
        return {"success": False, "error": str(e), "response": ""}
    text = (resp.text or "").strip()
    if is_truncated(resp):
        return {"success": False, "error": "reply hit max_tokens", "response": text}
    return {"success": bool(text), "response": text, "_resp": resp}


_URL = re.compile(r"https?://[^\s)\]>\"'*]+")


def score(text: str, original: str, resp) -> dict:
    chapters = re.findall(r"(?im)^[ \t#*]*(?:heading:\s*)?chapter\s+\d+", text)
    cues = re.findall(r"(?i)visual cue\W*:", text)
    ev = search_evidence(resp) if resp is not None else {"web_searches": 0, "citations": []}
    head = re.compile(r"(?m)^Heading: Chapter \d+")
    markers = re.compile(r"\[PRODUCTION (?:BEGIN|END)\]")
    return {"chars": len(text),
            "'Heading:' lines kept": f"{len(head.findall(text))}/{len(head.findall(original))}",
            "production markers intact": f"{len(markers.findall(text))}/{len(markers.findall(original))}",
            "markers damaged": len(re.findall(r"\[PRODUCTION_(?:BEGIN|END)\]", text)),
            "chapters": len(chapters), "visual cues": len(cues),
            "Host words vs input": f"{app_host_words(text) / max(1, app_host_words(original)):.0%}",
            "tool links": len(set(_URL.findall(text))), "web searches": ev["web_searches"]}


async def _compare(script: str, title: str, dump_dir: str = "", code_only: bool = False) -> None:
    cred = make_credential()
    print(model_line(AGENT_NAME, MODEL, cred))
    agents = {"CODE": build_code_agent(cred)}
    if not code_only:
        agents["PORTAL"] = portal_agent(AGENT_NAME, cred)
    print(f"Running {' then '.join(agents)} on the same script...\n")
    results = {n: await polish_script(script, title, agent=a, label=n.lower()) for n, a in agents.items()}
    names = list(results)
    scored = {n: (score(r["response"], script, r.get("_resp")) if r.get("success") else None) for n, r in results.items()}
    keys = next((list(s.keys()) for s in scored.values() if s), [])
    print("=" * (26 + 16 * len(names)))
    print(f"{'metric':<26}" + "".join(f"{n:>16}" for n in names))
    for k in keys:
        print(f"{k:<26}" + "".join(f"{str(scored[n][k]) if scored[n] else 'FAILED':>16}" for n in names))
    print("=" * (26 + 16 * len(names)))
    for n, r in results.items():
        if not r.get("success"):
            print(f"{n} FAILED: {r.get('error')}")
    if dump_dir:
        os.makedirs(dump_dir, exist_ok=True)
        for n, r in results.items():
            open(os.path.join(dump_dir, f"polish_{n.lower()}.md"), "w", encoding="utf-8").write(r.get("response") or "")
        print(f"replies saved to {dump_dir}/polish_*.md")


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description="Code-defined Script Polisher agent (step 3).")
    ap.add_argument("--script-file", help="Script (defaults to the golden reference)")
    ap.add_argument("--title", default="", help="Script title")
    ap.add_argument("--compare", action="store_true", help="Run code and portal agents and compare")
    ap.add_argument("--code-only", action="store_true", help="With --compare: skip the portal call")
    ap.add_argument("--dump", default="", metavar="DIR", help="With --compare: save both replies")
    args = ap.parse_args()
    print(f"tracing : {setup_tracing()}")
    if args.script_file:
        script = open(args.script_file, encoding="utf-8").read().strip()
        title = args.title or os.path.splitext(os.path.basename(args.script_file))[0]
    else:
        script, title = load_reference_script(), (args.title or REFERENCE_TITLE)
    if args.compare:
        asyncio.run(_compare(script, title, args.dump, args.code_only))
    else:
        r = asyncio.run(polish_script(script, title))
        print(r.get("response") or r.get("error"))


if __name__ == "__main__":
    main()
