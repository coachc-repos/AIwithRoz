"""
MAF migration — Step 3, fourth portal->code conversion: Shorten agent.

Re-creates the Foundry portal agent `Script-Shorten-Agent` as a CODE-DEFINED
Microsoft Agent Framework agent, seeded from its captured instructions
(../agent_instructions/Script-Shorten-Agent.md) and run on the same model
(gpt-6-astra) via FoundryChatClient. It is the first non-Claude conversion.

Like Repeat-and-Flow it is a TRANSFORM agent: when "Shorten script" is checked,
web_gui.py replaces the user's script with the shortened one. The app masks
every [PRODUCTION BEGIN] block first and keeps the original script if any
placeholder is dropped, then reports Host: words before and after against a
target (a percent cut, or the requested minutes at 150 wpm). --compare scores
exactly that, using the app's own word counter.

Drop-in contract: `shorten_to_target()` sends the SAME request as
`linedrive_azure/agents/script_shorten_agent_client.py`, including the
chapter-by-chapter retry when Azure's content filter blocks the whole script,
and returns the same keys (success, response, error, chunked, chunk_failures,
chunk_count). Two differences, both fixes: a reply cut off by max_tokens
returns success=False (without production blocks the app would otherwise save
a truncated script), and the chapter splitter accepts "Heading: Chapter N"
lines, so the content-filter fallback also works on Pro-format scripts (the
client's splitter finds no chapters in them).

The code agent's instructions are the captured prompt PLUS a short APP_CONTRACT
addendum (keep placeholders; never drop items from a counted list). See
APP_CONTRACT for the evidence. MAF_SHORTEN_APP_CONTRACT=0 runs the bare
captured prompt for A/B checks.

Why no web_search tool: the portal agent lists one, but shortening only cuts
the provided script, and its prompt forbids adding new facts.

Validate side-by-side (does NOT delete the portal agent):
    maf/.venv/bin/python maf/agents/shorten.py --compare --dump /tmp/shorten_cmp
    maf/.venv/bin/python maf/agents/shorten.py --compare --percent 30 --script-file s.md
    maf/.venv/bin/python maf/agents/shorten.py --script-file path/to/script.md

Scoped to maf/, no web_gui.py changes, isolated venv.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from typing import Any, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import Agent  # noqa: E402

from agents._common import (  # noqa: E402
    REFERENCE_TITLE,
    build_code_agent as _build_agent,
    is_truncated,
    load_instructions as _load_instructions,
    load_reference_script,
    portal_agent,
    run_response,
)
from agents._production_blocks import mask_production_blocks, restore_or_keep  # noqa: E402
from agents._script_metrics import app_host_words, fmt_chapters, script_stats  # noqa: E402
from observability import PROJECT_ENDPOINT, load_env, make_credential, setup_tracing  # noqa: E402

AGENT_NAME = "Script-Shorten-Agent"   # the portal agent, called by name in --compare
MODEL = os.environ.get("MAF_SHORTEN_MODEL", "gpt-6-astra")
# The reply is the whole shortened script; 32000 leaves room for long scripts.
MAX_TOKENS = int(os.environ.get("MAF_SHORTEN_MAX_TOKENS", "32000"))
WPM = 150  # the app's fixed speaking rate


# App rules the captured portal prompt never states. Appended to the captured
# instructions in code (the .md capture stays verbatim). Evidence, --compare on
# 2026-10-07 (25% cuts on three scripts):
#   1. Both agents kept every [[PRODUCTION_BLOCK_N]] placeholder (85 of 85), but
#      the prompt never names them and one dropped placeholder makes the app
#      silently discard the whole cut. Insurance, as in repeat_flow.py.
#   2. To hit its word target the code agent cut "Ten mistakes, ten seconds."
#      from ten examples to three on the Top-N list script, which breaks the
#      promise; the portal agent kept all ten. (It kept "The five winners" intact
#      on another script, so 1 of 2 counted lists.)
# Set MAF_SHORTEN_APP_CONTRACT=0 to run the bare captured prompt (for A/B checks).
APP_CONTRACT = """

## App contract (added in code)

1. Placeholders. The script contains placeholders such as [[PRODUCTION_BLOCK_0]]. Each one stands for a production block that the app restores after you finish. Copy every placeholder exactly as written, on its own line, in the same position relative to the dialogue around it. If any placeholder is missing, the app throws away your entire revision.
2. Counted lists. When the script announces a count and then lists that many items, for example "Ten mistakes, ten seconds." followed by ten examples, keep every item. You may tighten each item's wording, but never drop items, because the count is a promise to the viewer. Take the cuts from elsewhere.
"""


def app_contract_enabled() -> bool:
    return os.environ.get("MAF_SHORTEN_APP_CONTRACT", "1").strip().lower() not in ("0", "false", "no", "off")


def load_instructions() -> str:
    """The captured portal instructions (capture-header comment stripped)."""
    return _load_instructions(AGENT_NAME)


def code_agent_instructions() -> str:
    """Captured instructions, plus the app contract unless MAF_SHORTEN_APP_CONTRACT=0."""
    return load_instructions() + (APP_CONTRACT if app_contract_enabled() else "")


def build_code_agent(credential=None) -> Agent:
    """The Shorten agent defined in code (captured instructions + app contract)."""
    return _build_agent(
        name="Script-Shorten-Agent (code)",
        instructions=code_agent_instructions(),
        model=MODEL,
        max_tokens=MAX_TOKENS,
        credential=credential,
    )


# --------------------------------------------------------------------------- #
# Ports of the app client's helpers (script_shorten_agent_client.py), verbatim
# except the chapter splitter (see split_into_chapter_chunks).
# --------------------------------------------------------------------------- #

def is_content_filter_error(err: Any) -> bool:
    """True when the agent error string looks like an Azure content/prompt-shield block."""
    if not err:
        return False
    s = str(err).lower()
    return (
        "content_filter" in s
        or "content management policy" in s
        or "jailbreak" in s
        or "responsible ai" in s
    )


def split_into_chapter_chunks(script: str) -> List[str]:
    """Split on `Chapter N` headings; the pre-Chapter-1 preamble is the first chunk.

    FIX vs. the app client: also accepts a "Heading:" prefix. The client's
    pattern only matches lines that START with "Chapter N", so a Pro-format
    script ("Heading: Chapter 1 - …") comes back as one chunk and the
    content-filter fallback can never run on it. Scripts without "Heading:"
    lines split exactly as before."""
    pattern = re.compile(r"(?im)^\s*(?:#{1,6}\s*)?\**\s*(?:heading\s*:\s*\**\s*)?chapter\s+\d+\b.*$")
    matches = list(pattern.finditer(script))
    if len(matches) < 2:
        return [script]
    chunks: List[str] = []
    first_start = matches[0].start()
    if first_start > 0:
        preamble = script[:first_start].rstrip()
        if preamble.strip():
            chunks.append(preamble)
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(script)
        chunks.append(script[start:end].rstrip())
    return chunks


def host_words_in(text: str) -> int:
    """The client's per-chunk Host-word count (used only for chunk budgets)."""
    blocks = re.findall(
        r"(?:^|\n)\s*(?:#{1,6}\s*)?\**\s*host\s*\**\s*:\s*([\s\S]*?)"
        r"(?=\n\s*(?:#{1,6}\s+\S|(?:#{1,6}\s*)?(?:\*\*[^*\n]{1,40}\*\*\s*:|host\s*:|"
        r"heading\s*:|chapter\s+\d|visual\s+cue\s*:|b-?roll\s*:)|---+|===+)|$)",
        text,
        flags=re.IGNORECASE,
    )
    return sum(len(re.findall(r"\S+", b)) for b in blocks)


def strip_code_fences(text: str) -> str:
    """What the app does to the reply before restoring production blocks."""
    text = re.sub(r"^```[a-zA-Z]*\n", "", text)
    return re.sub(r"\n```\s*$", "", text)


def target_words_for(target_minutes: float, wpm: int = WPM,
                     target_words_override: Optional[int] = None) -> int:
    if target_words_override is not None and target_words_override > 0:
        return int(target_words_override)
    return int(round(target_minutes * wpm))


def build_request_message(
    script_content: str,
    target_minutes: float,
    wpm: int = WPM,
    target_words_override: Optional[int] = None,
    reduction_percent: Optional[int] = None,
    current_host_words: Optional[int] = None,
) -> str:
    """Verbatim copy of the request the app client sends (keep in sync)."""
    target_words = target_words_for(target_minutes, wpm, target_words_override)
    current_words = len(script_content.split())
    cur_host = (
        current_host_words
        if current_host_words is not None
        else "(not provided)"
    )
    pct_note = (
        f"- Requested reduction: ~{reduction_percent}% of current Host: words"
        if reduction_percent
        else "- Reduction implied by target Host: word count below"
    )
    return f"""TARGET LENGTH:
- Target video length: {target_minutes:.1f} minutes at {wpm} wpm
- Target Host: word count: ~{target_words} words (total across all Host blocks)
- Current Host: word count: {cur_host}
- Current total word count (entire script): ~{current_words} words
{pct_note}

Apply your smart-cut rules and return ONLY the rewritten script text — no
preamble, no commentary, no code fences.

SCRIPT CONTENT TO SHORTEN:
{script_content}
"""


def build_chunk_message(chunk: str, idx: int, chunks: List[str], chunk_target: int,
                        hw: int, target_minutes: float, wpm: int = WPM) -> str:
    """Verbatim copy of the client's per-chapter retry request (keep in sync)."""
    return f"""TARGET LENGTH (this chapter only):
- This is ONE chapter of a longer educational script (chunk {idx} of {len(chunks)}).
- Target Host: word count for THIS chapter: ~{chunk_target} words
- Current Host: word count for THIS chapter: {hw}
- Overall target video length (full script): {target_minutes:.1f} minutes at {wpm} wpm

Apply your smart-cut rules to this chapter only. Preserve chapter heading,
VISUAL CUE, and B-Roll blocks. Return ONLY the rewritten chapter text — no
preamble, no commentary, no code fences.

CHAPTER CONTENT TO SHORTEN:
{chunk}
"""


# --------------------------------------------------------------------------- #
# The app's target rule (web_gui.py, both Shorten call sites).
# --------------------------------------------------------------------------- #

def app_target(before_host_words: int, video_length: str = "10 minutes",
               percent: Optional[int] = None) -> dict:
    """Reproduce how the app picks the target and decides whether to call at all."""
    m = re.search(r"(\d+(?:\.\d+)?)", str(video_length or ""))
    target_minutes = float(m.group(1)) if m else 10.0
    duration_target = int(round(target_minutes * WPM))
    override = None
    if percent and 0 < percent < 100 and before_host_words > 0:
        override = int(round(before_host_words * (1 - percent / 100.0)))
    effective = override if override else duration_target
    return {
        "target_minutes": target_minutes,
        "target_words_override": override,
        "reduction_percent": percent if override else None,
        "effective_target": effective,
        "app_would_call": before_host_words > effective * 1.05,
    }


# --------------------------------------------------------------------------- #
# The agent call, with the client's content-filter fallback.
# --------------------------------------------------------------------------- #

async def _run_one(agent, message: str, label: str) -> dict:
    """One call -> the client's result shape. Never raises."""
    try:
        resp = await run_response(agent, message, label)
    except Exception as e:  # content filter, auth, network after retries…
        return {"success": False, "error": str(e)}
    text = (resp.text or "").strip()
    if is_truncated(resp):
        return {"success": False, "response": text,
                "error": "Shorten reply hit max_tokens; the script is incomplete"}
    return {"success": bool(text), "response": text,
            **({} if text else {"error": "Empty response from Shorten agent"})}


async def _shorten_chunked(agent, chunks: List[str], target_total_host_words: int,
                           target_minutes: float, wpm: int, label: str) -> dict:
    """Port of ScriptShortenAgentClient._shorten_chunked: shorten each chapter on
    its own with a proportional Host-word budget; keep any chunk that fails."""
    host_counts = [host_words_in(c) for c in chunks]
    total_host = sum(host_counts) or 1
    out_parts: List[str] = []
    failures = 0
    for idx, (chunk, hw) in enumerate(zip(chunks, host_counts), start=1):
        if hw == 0:
            out_parts.append(chunk)
            continue
        chunk_target = max(40, int(round(target_total_host_words * (hw / total_host))))
        sub = await _run_one(agent, build_chunk_message(chunk, idx, chunks, chunk_target, hw,
                                                        target_minutes, wpm), f"{label} chunk {idx}")
        if sub.get("success") and sub.get("response"):
            out_parts.append(strip_code_fences(sub["response"].strip()) or chunk)
        else:
            out_parts.append(chunk)
            failures += 1
    joined = "\n\n".join(out_parts).strip() + "\n"
    if failures == len([c for c in host_counts if c > 0]):
        return {"success": False,
                "error": ("Content filter blocked all chapter retries; original script "
                          "kept (Azure prompt shield false-positive on this content).")}
    return {"success": True, "response": joined, "chunked": True,
            "chunk_failures": failures, "chunk_count": len(chunks)}


async def shorten_to_target(
    script_content: str,
    target_minutes: float,
    wpm: int = WPM,
    target_words_override: Optional[int] = None,
    reduction_percent: Optional[int] = None,
    current_host_words: Optional[int] = None,
    credential=None,
    agent=None,
    label: str = "code",
) -> dict:
    """Code-agent equivalent of ScriptShortenAgentClient.shorten_to_target().
    Like the app client, it expects the caller to have masked production blocks.
    Pass `agent` to run the same flow against another agent (e.g. the portal one)."""
    agent = agent or build_code_agent(credential)
    msg = build_request_message(script_content, target_minutes, wpm, target_words_override,
                                reduction_percent, current_host_words)
    result = await _run_one(agent, msg, label)
    if not result.get("success") and is_content_filter_error(result.get("error")):
        chunks = split_into_chapter_chunks(script_content)
        if len(chunks) > 1:
            print(f"   [{label}] content filter blocked the full script; retrying "
                  f"chapter-by-chapter ({len(chunks)} chunks)", file=sys.stderr)
            return await _shorten_chunked(
                agent, chunks, target_words_for(target_minutes, wpm, target_words_override),
                target_minutes, wpm, label)
    return result


# --------------------------------------------------------------------------- #
# --compare: score what the APP would save from each agent's reply
# --------------------------------------------------------------------------- #

async def _compare(script_text: str, title: str, video_length: str, percent: Optional[int],
                   dump_dir: str = "", code_only: bool = False) -> None:
    before = app_host_words(script_text)
    tgt = app_target(before, video_length, percent)
    print(f"Host words now {before}; target {tgt['effective_target']} "
          f"({'-' + str(percent) + '%' if tgt['target_words_override'] else str(tgt['target_minutes']) + ' min at 150 wpm'}).")
    if not tgt["app_would_call"]:
        print("The app would skip Shorten: the script is already within 5% of the target.")
        return
    masked, blocks = mask_production_blocks(script_text)
    kwargs = dict(target_minutes=tgt["target_minutes"], wpm=WPM,
                  target_words_override=tgt["target_words_override"],
                  reduction_percent=tgt["reduction_percent"], current_host_words=before)
    print(f"Masked {len(blocks)} production blocks, as the app does. Request: "
          f"{len(build_request_message(masked, **kwargs))} chars. "
          f"App contract on code agent: {'on' if app_contract_enabled() else 'OFF'}.")
    cred = make_credential()
    agents = {"CODE": build_code_agent(cred)}
    if not code_only:
        agents["PORTAL"] = portal_agent(AGENT_NAME, cred)
    print(f"Running {' then '.join(agents)} on the same script...\n")
    results = {}
    for name, agent in agents.items():  # sequential: avoids the concurrent-DNS flake
        results[name] = await shorten_to_target(masked, agent=agent, label=name.lower(), **kwargs)

    orig = script_stats(masked)
    cols, saved = {"ORIGINAL": orig}, {}
    for name, res in results.items():
        if res.get("success"):
            rewrite = strip_code_fences(res["response"].strip())
            cols[name] = script_stats(rewrite)
            saved[name] = restore_or_keep(rewrite, blocks, script_text)
        else:
            cols[name] = None
    n_blocks, all_blocks, target = len(blocks), set(range(len(blocks))), tgt["effective_target"]
    names = list(results)
    order = ["ORIGINAL"] + names

    def agent_only(fn):
        return lambda n: "-" if n == "ORIGINAL" else fn(n)

    def stat(fn):
        return lambda n: "-" if cols[n] is None else fn(cols[n])

    rows = [
        ("reply chars", agent_only(lambda n: str(len(results[n].get("response") or "")))),
        ("result", agent_only(lambda n: ("ok" + (" (chunked)" if results[n].get("chunked") else ""))
                              if results[n].get("success") else "FAILED")),
        ("code fences in reply", agent_only(lambda n: "yes" if "```" in (results[n].get("response") or "") else "no")),
        (f"placeholders kept /{n_blocks}", stat(lambda s: str(len(s["placeholders"] & all_blocks)))),
        ("APP KEEPS REWRITE", agent_only(lambda n: "-" if cols[n] is None else ("yes" if saved[n][1] else "NO (discarded)"))),
        (f"Host words (target {target})", stat(lambda s: str(s["host_words"]))),
        ("  % of target", stat(lambda s: f"{s['host_words'] / max(1, target):.0%}")),
        ("  within +/-10%", agent_only(lambda n: "-" if cols[n] is None else
                                       ("yes" if abs(cols[n]["host_words"] - target) <= 0.10 * target else "NO"))),
        ("app reports after", agent_only(lambda n: "-" if cols[n] is None else
                                         str(app_host_words(saved[n][0])))),
        ("chapters", stat(lambda s: fmt_chapters(s["chapter_nums"]))),
        ("'Heading:' lines", stat(lambda s: str(s["heading_prefix"]))),
        ("timestamps in headings", stat(lambda s: str(s["heading_timestamps"]))),
        ("hook/header words", stat(lambda s: str(s["pre_chapter_words"]))),
        ("em/en dash, arrow", stat(lambda s: str(s["dashes_arrows"]))),
        ("contractions", stat(lambda s: str(s["contractions"]))),
        ("no-break/thin spaces", stat(lambda s: str(s["odd_spaces"]))),
        ("agent notes in script", stat(lambda s: str(s["agent_notes"]))),
        (f"trailing sections /{len(orig['sections'])}",
         stat(lambda s: str(len(set(s["sections"]) & set(orig["sections"]))))),
    ]
    width = 28 + 16 * len(order)
    print("=" * width)
    print(f"{'metric':<28}" + "".join(f"{n:>16}" for n in order))
    for label, fn in rows:
        print(f"{label:<28}" + "".join(f"{fn(n):>16}" for n in order))
    print("=" * width + "\n")

    print(f"{'Host words per chapter':<28}" + "".join(f"{n:>16}" for n in order))
    for ch in sorted(orig["host_words_by_chapter"]):
        vals = [str(orig["host_words_by_chapter"][ch])] + [
            "-" if cols[n] is None else str(cols[n]["host_words_by_chapter"].get(ch, "missing")) for n in names]
        print(f"{'  Chapter ' + str(ch):<28}" + "".join(f"{v:>16}" for v in vals))
    print()
    for name, res in results.items():
        if not res.get("success"):
            print(f"{name} FAILED: {res.get('error')}\n")

    if dump_dir:
        os.makedirs(dump_dir, exist_ok=True)
        for name, res in results.items():
            low = name.lower()
            with open(os.path.join(dump_dir, f"shorten_{low}_reply.md"), "w", encoding="utf-8") as f:
                f.write(res.get("response") or res.get("error") or "")
            if name in saved:
                with open(os.path.join(dump_dir, f"shorten_{low}_app_saves.md"), "w", encoding="utf-8") as f:
                    f.write(saved[name][0])
        print(f"raw replies + the script the app would save are in {dump_dir}/shorten_*.md")


def _read_script(args) -> tuple[str, str]:
    if args.script_file:
        with open(args.script_file, "r", encoding="utf-8") as f:
            text = f.read().strip()
        title = args.title or os.path.splitext(os.path.basename(args.script_file))[0]
        return text, title
    return load_reference_script(), (args.title or REFERENCE_TITLE)


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description="Code-defined Shorten MAF agent (step 3).")
    ap.add_argument("--script-file", help="Path to a .md/.txt script (defaults to the golden reference)")
    ap.add_argument("--title", default="", help="Script title (display only)")
    ap.add_argument("--percent", type=int, default=25,
                    help="Cut Host words by this percent, like the app's percent picker "
                         "(0 = use --video-length instead). Default 25.")
    ap.add_argument("--video-length", default="10 minutes",
                    help='Target length when --percent is 0, e.g. "8 minutes" (150 wpm)')
    ap.add_argument("--compare", action="store_true",
                    help="Run BOTH the code agent and the portal agent and compare")
    ap.add_argument("--dump", default="", metavar="DIR",
                    help="With --compare: save raw replies and the script the app would save")
    ap.add_argument("--code-only", action="store_true",
                    help="With --compare: score only the code agent (skip the portal call)")
    args = ap.parse_args()

    status = setup_tracing()
    script_text, title = _read_script(args)
    percent = args.percent or None
    print("ScriptCraft MAF — Shorten agent (portal -> code conversion)")
    print(f"project : {PROJECT_ENDPOINT}")
    print(f"model   : {MODEL} (via FoundryChatClient)  max_tokens={MAX_TOKENS}")
    print(f"tracing : {status}")
    print(f"title   : {title}  ({len(script_text)} chars)\n")

    if args.compare:
        asyncio.run(_compare(script_text, title, args.video_length, percent, args.dump, args.code_only))
        return
    before = app_host_words(script_text)
    tgt = app_target(before, args.video_length, percent)
    if not tgt["app_would_call"]:
        sys.exit(f"Already within 5% of the target ({before} vs {tgt['effective_target']} Host words).")
    masked, blocks = mask_production_blocks(script_text)
    result = asyncio.run(shorten_to_target(
        masked, tgt["target_minutes"], WPM, tgt["target_words_override"],
        tgt["reduction_percent"], before))
    if not result.get("success"):
        sys.exit(result.get("error"))
    saved, applied = restore_or_keep(strip_code_fences(result["response"].strip()), blocks, script_text)
    if not applied:
        print("WARNING: the agent dropped a production-block placeholder, so the app "
              "would keep the original script.", file=sys.stderr)
    print(saved)
    print(f"\nHost words {before} -> {app_host_words(saved)} (target {tgt['effective_target']})",
          file=sys.stderr)


if __name__ == "__main__":
    main()
