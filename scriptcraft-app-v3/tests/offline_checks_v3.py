"""Offline checks for the v3 GUI's MAF wiring (no model calls, no network).

Run with the interpreter that runs the GUI, from anywhere:
    python scriptcraft-app-v3/tests/offline_checks_v3.py

Exit status 0 means every check passed.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import sys
import types

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
# Never read the real channel intro / end clip (~/.scriptcraft/channel): a test
# explainer project without its own bookends would pick them up.
import tempfile as _tempfile  # noqa: E402
os.environ["SCRIPTCRAFT_CHANNEL_DIR"] = _tempfile.mkdtemp(prefix="xv-channel-")
os.environ.setdefault("SCRIPTCRAFT_AGENT_BACKEND", "maf")

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str):
    def deco(fn):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                detail = fn() or ""
            RESULTS.append((name, True, detail))
        except Exception as e:  # noqa: BLE001
            if os.environ.get("OFFLINE_TB"):
                import traceback
                traceback.print_exc()
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return deco


from linedrive_azure.agents import base_agent_client as bac  # noqa: E402

USED_CLIENTS = {
    "script_topic_assistant_agent_client": "ScriptTopicAssistantAgentClient",
    "script_topic_assistant_list_agent_client": "ScriptTopicAssistantListAgentClient",
    "script_topic_assistant_predictions_agent_client": "ScriptTopicAssistantPredictionsAgentClient",
    "script_writer_agent_client": "ScriptWriterAgentClient",
    "script_writer_list_agent_client": "ScriptWriterListAgentClient",
    "script_writer_predictions_agent_client": "ScriptWriterPredictionsAgentClient",
    "script_review_agent_client": "ScriptReviewAgentClient",
    "quote_and_statistics_agent_client": "ScriptQuotesAndStatisticsAgentClient",
    "hook_and_summary_agent_client": "HookAndSummaryAgentClient",
    "script_repeat_and_flow_agent_client": "ScriptRepeatAndFlowAgentClient",
    "script_shorten_agent_client": "ScriptShortenAgentClient",
    "youtube_upload_details_agent_client": "YouTubeUploadDetailsAgentClient",
    "script_polisher_agent_client": "ScriptPolisherAgentClient",
    "script_broll_agent_client": "ScriptBRollAgentClient",
}


def _client(module: str, cls: str):
    import importlib
    return getattr(importlib.import_module(f"linedrive_azure.agents.{module}"), cls)()


@check("Golden reference script loads (Pro mode prompt and the pipeline's style block need it)")
def _():
    from linedrive_azure.agents.pro_script_writer import load_golden_reference  # noqa: PLC0415
    text = load_golden_reference(max_chars=100000)
    # load_golden_reference() returns "" when the file is missing, which silently
    # drops the reference from every Pro and pipeline request.
    assert len(text) > 5000, f"golden reference missing or short ({len(text)} chars)"
    return f"{len(text)} chars from agent_instructions/golden_reference_script.md"


@check("Pro prompt requires 7 or 8 balanced chapters; the chapter counter reads 'Heading: Chapter N'")
def _():
    from linedrive_azure.agents import pro_script_writer as pw  # noqa: PLC0415
    assert "CHAPTER COUNT (REQUIRED): write EXACTLY 7 or 8 chapters" in pw.SCRIPT_WRITER_PRO_SYSTEM
    sample = "FINAL HOOK:\n" + "".join(f"Heading: Chapter {i} - X\nHost:\nWords.\n" for i in range(1, 9))
    assert pw.pro_chapter_count(sample) == 8
    return "rule present; counter finds 8 in an 8-chapter sample"


@check("Both Pro writers send the same request; the workflow routes classic vs agent")
def _():
    from linedrive_azure.agents import pro_script_writer as pw  # noqa: PLC0415
    msg = pw.build_pro_user_message("T", "B")
    assert msg.startswith("TODAY: ") and "\n\nTITLE: T\n\n" in msg and "<golden_reference>" in msg
    src = open(os.path.join(APP, "linedrive_azure", "agents", "pro_script_writer.py"), encoding="utf-8").read()
    assert src.count("build_pro_user_message(title, brief)") == 2, "classic and agent must share the builder"
    assert 'PRO_AGENT_NAME = "Script-Writer-Pro-Agent-MAF"' in src
    wf = open(os.path.join(APP, "linedrive_azure", "agents", "enhanced_autogen_system.py"), encoding="utf-8").read()
    assert 'if pro_writer == "agent":' in wf and "write_pro_script_agent(" in wf
    return "shared builder; agent branch present"


@check("Plain speech (ASD-STE100): every writer and the chapter reviewer get the rules; the checker counts what slips")
def _():
    from linedrive_azure.agents import pro_script_writer as pw  # noqa: PLC0415
    rules = pw.PLAIN_SPEECH_RULES
    for rule in ("No sentence has more than 25 words", 'Do not use "should", "would", "may", "might", or "could"',
                 '", making it"', "One name for one thing", "noun chains of three words or fewer",
                 "it is not just X, it is Y", "no contractions"):
        assert rule.lower() in rules.lower(), rule
    assert "PLAIN SPEECH RULES (ASD-STE100" in pw.SCRIPT_WRITER_PRO_SYSTEM and rules in pw.SCRIPT_WRITER_PRO_SYSTEM
    assert "Short sentences mixed with longer ones" not in pw.SCRIPT_WRITER_PRO_SYSTEM
    assert "breaks the PLAIN SPEECH RULES" in pw.build_pro_user_message("T", "B"), "rules beat the golden reference"
    # The hosted Pro agent serves the synced copy (maf/agents/pro_writer.py --sync).
    hosted = open(os.path.join(os.path.dirname(APP), "scriptcraft-app-v2", "agent_instructions",
                               "Script-Writer-Pro-Agent.md"), encoding="utf-8").read()
    assert pw.SCRIPT_WRITER_PRO_SYSTEM.strip() in hosted, "run maf/agents/pro_writer.py --sync"
    wf = open(os.path.join(APP, "linedrive_azure", "agents", "enhanced_autogen_system.py"), encoding="utf-8").read()
    assert "from .pro_script_writer import PLAIN_SPEECH_RULES" in wf
    assert wf.count("script_request += (") == 1 and wf.count("chapter_review_request += (") == 1
    assert wf.index("script_request += (") < wf.index("def _fallback_or_fail"), "hosted writer and fallback share it"
    gui = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    assert "plain_speech_summary(raw_script_content)" in gui

    sloppy = ("Host:\nWe should simply leverage this robust tool, making it seamless. It is not just a tool; "
              "it is a whole new landscape that has been reshaping how teams, partners, vendors, and customers "
              "across every industry and region work together every single day of the week. "
              "The result? Chaos. You don't want that.\n")
    # A writer's raw output: plain "Host:" labels and the metadata block, whose
    # Tone line has a semicolon and runs long. The metadata is not spoken.
    clean = ("FINAL HOOK:\nHost:\nIn May 2026, Google changed the free plan.\n" + "_" * 40 + "\n"
             "Title: Free Plans\nScript Type: Video\nDuration: medium\nAudience: parents\n"
             "Tone: warm. PARSER RULE: skip everything between [PRODUCTION BEGIN] and [PRODUCTION END]; "
             "all Host: text outside the markers is spoken. VISUAL RULE: GROK IMAGINE lines are complete prompts.\n"
             + "_" * 40 + "\nHeading: Chapter 1 - The Free Plan Changed\nHost:\n"
             "If your link is public, make it private. Nobody knows yet what comes next. "
             "The free plan now keeps your files for thirty days.\n")
    s, c = pw.plain_speech_report(sloppy), pw.plain_speech_report(clean)
    for k in ("long sentences", "hedges", "perfect tenses", "-ing clauses", "filler words",
              "not-X-it-is-Y lines", "self-answered questions", "contractions", "semicolons"):
        assert s["counts"][k] >= 1, (k, s["counts"])
    assert c["total"] == 0, c
    assert "no rule breaks" in pw.plain_speech_summary(clean)
    assert "rule breaks (" in pw.plain_speech_summary(sloppy)
    return f"sloppy sample: {s['total']} breaks; clean sample (with 'May 2026'): 0"


@check("Ideas and briefs: today's date + recency rules; Grok searches X and the web; briefs search")
def _():
    gui = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    import web_gui  # noqa: PLC0415
    rules = web_gui._recency_rules(60)
    assert rules.startswith("TODAY is ") and "last 60 days" in rules and "already underway is news" in rules
    assert "+ _recency_rules()" in gui and gui.count("_recency_rules()") >= 2, "idea + brief prompts"
    assert "search_days=IDEA_RECENCY_DAYS" in gui and "_xai_x_search(from_date=since)" in gui
    assert "use_web_search=True, max_searches=4," in gui
    return rules[:60] + "..."


@check("Script Writer control: three options, and the create request carries pro_writer")
def _():
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    for value in ("pro_classic", "pro_agent", "agentic"):
        assert f'name="writerMode" value="{value}"' in html, value
        # The Idea Generator's selected-idea row offers the same choice.
        assert f'name="writerModeIdea" value="{value}" onchange="setWriterMode(this.value)"' in html, value
    assert 'input[name="writerModeIdea"][value="${mode}"]' in html, "the two controls stay in step"
    assert "pro_writer: proWriter," in html
    assert '<option value="pro"' not in html, "Pro is chosen with the control, not the format list"
    gui = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    assert 'pro_writer = (data.get("pro_writer") or "classic").strip().lower()' in gui
    assert gui.count("pro_writer=pro_writer,") == 2
    return "dialog + Idea Generator radios, payload, and server plumbing present"


@check("Every migrated client routes to its hosted '-MAF' agent")
def _():
    names = []
    for module, cls in USED_CLIENTS.items():
        c = _client(module, cls)
        assert c.maf_agent_name == c.v2_agent_name + "-MAF", (cls, c.maf_agent_name)
        assert c.v2_agent_name in bac.MAF_HOSTED_AGENTS, c.v2_agent_name
        names.append(c.maf_agent_name)
    other = _client("tournament_agent_client", "TournamentAgentClient")
    assert other.maf_agent_name is None, "agents without a MAF version stay on the portal"
    return f"{len(names)} clients routed; Tournament-Agent stays on the portal"


# --------------------------------------------------------------------------- #
# A fake hosted-agent endpoint: background create -> queued/in_progress -> done
# --------------------------------------------------------------------------- #
def _ns(**kw):
    return types.SimpleNamespace(**kw)


def _message(text):
    return _ns(type="message", content=[_ns(type="output_text", text=text)])


class _FakeResponses:
    def __init__(self, finals):
        self.finals = list(finals)  # one final response per create()
        self.created = []
        self.polls = 0

    def create(self, **kw):
        self.created.append(kw)
        final = self.finals.pop(0)
        self._pending = [_ns(id="r1", status="in_progress"), final]
        return _ns(id="r1", status="queued")

    def retrieve(self, rid, timeout=None):
        self.polls += 1
        return self._pending.pop(0)

    def cancel(self, rid, timeout=None):
        return None


def _with_fake(client, finals):
    fake = types.SimpleNamespace(responses=_FakeResponses(finals))
    bac._maf_clients[client.maf_agent_name] = fake
    bac._maf_sessions.pop(client.maf_agent_name, None)
    return fake


@check("Hosted call: polls to completion, keeps the last message, logs searches, reuses the session")
def _():
    bac.MAF_POLL_S = 0
    c = _client("script_broll_agent_client", "ScriptBRollAgentClient")
    done = _ns(id="r1", status="completed", agent_session_id="sess-1", error=None, output=[
        _message("Let me search first."),
        _ns(type="function_call", name="web_search", arguments='{"query": "stock footage sites"}'),
        _ns(type="function_call_output", output="results"),
        _message("| Timecode | Search Term |\n|---|---|\n| 0:00 | city |"),
    ])
    fake = _with_fake(c, [done, done])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        t = c.create_thread()
        r = c.send_message(t.id, "make a table", timeout=5)
        r2 = c.send_message(c.create_thread().id, "again", timeout=5)
    log = out.getvalue()
    assert r["success"] and r["response"].startswith("| Timecode"), r
    assert r2["success"]
    assert 'web_search "stock footage sites"' in log and "[maf] Running Script-bRoll-Agent-MAF" in log, log
    assert fake.responses.created[0]["background"] is True
    assert fake.responses.created[0]["extra_body"] is None
    assert fake.responses.created[1]["extra_body"] == {"agent_session_id": "sess-1"}, "warm session reused"
    return f"{fake.responses.polls} status checks for 2 calls; second call reused the session"


@check("Hosted call: MAF's 'Function invocation limit reached' reply is retried, never returned as text")
def _():
    bac.MAF_POLL_S = 0
    c = _client("script_review_agent_client", "ScriptReviewAgentClient")
    gave_up = _ns(id="r1", status="completed", agent_session_id=None, error=None,
                  output=[_message("Function invocation limit reached before a final answer could be produced.")])
    good = _ns(id="r1", status="completed", agent_session_id=None, error=None, output=[_message("Revised chapter")])
    _with_fake(c, [gave_up, good])
    orig_sleep = bac.time.sleep
    bac.time.sleep = lambda s: None
    try:
        r = c.send_message(c.create_thread().id, "review", timeout=5, max_retries=2)
    finally:
        bac.time.sleep = orig_sleep
    assert r["success"] and r["response"] == "Revised chapter", r
    return "second attempt returned the real reply"


@check("Hosted call: a throttled run (429) is retried on its own budget with randomized backoff")
def _():
    bac.MAF_POLL_S = 0
    c = _client("script_review_agent_client", "ScriptReviewAgentClient")
    throttled = _ns(id="r1", status="failed", agent_session_id=None, output=[],
                    error=_ns(code="server_error", message="Model deployment rate limit exceeded"))
    good = _ns(id="r1", status="completed", agent_session_id=None, error=None, output=[_message("Reviewed")])
    _with_fake(c, [throttled, throttled, throttled, throttled, good])
    waits = []
    orig_sleep = bac.time.sleep
    bac.time.sleep = lambda s: waits.append(s)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            r = c.send_message(c.create_thread().id, "review", timeout=5, max_retries=1)
    finally:
        bac.time.sleep = orig_sleep
    assert r["success"] and r["response"] == "Reviewed", r
    assert "rate limited — retry 4/" in out.getvalue(), out.getvalue()
    backoff = [w for w in waits if w > 0]
    assert len(backoff) == 4 and backoff[0] >= 8 and backoff[-1] >= 60, backoff
    return "4 throttled runs, then success; waits " + ", ".join(f"{w:.0f}s" for w in backoff)


@check("Hosted call: a failed run reports its error; hosted runs get at least the minimum timeout")
def _():
    bac.MAF_POLL_S = 0
    c = _client("hook_and_summary_agent_client", "HookAndSummaryAgentClient")
    failed = _ns(id="r1", status="failed", agent_session_id=None, output=[],
                 error=_ns(code="invalid_request", message="bad input"))
    _with_fake(c, [failed])
    r = c.send_message(c.create_thread().id, "x", timeout=120, max_retries=0)
    assert not r["success"] and "bad input" in r["error"], r
    assert bac.MAF_MIN_TIMEOUT_S >= 300
    return f"error surfaced; minimum timeout {bac.MAF_MIN_TIMEOUT_S}s"


@check("Repeat-and-Flow client reads the 'response' field (v2 read only 'messages' and always failed)")
def _():
    c = _client("script_repeat_and_flow_agent_client", "ScriptRepeatAndFlowAgentClient")
    reply = ("=== STRUCTURE CHECK ===\nok\n\n=== REPETITION ANALYSIS ===\n**Repetitions Found:**\n- one\n\n"
             "**Flow Issues Identified:**\n1. a gap\n\n=== REVISED COMPLETE SCRIPT ===\n\n"
             "Heading: Chapter 1 - Start\n\nHost: Hello there.\n")
    c.create_thread = lambda: _ns(id="t")
    c.send_message = lambda **kw: {"success": True, "response": reply, "sources": [], "error": None}
    r = c.analyze_and_improve_flow("Heading: Chapter 1 - Start\n\nHost: Hello hello there.\n")
    assert r["success"] and r["improved_script"].startswith("Heading: Chapter 1"), r
    assert r["flow_analysis"].startswith("**Flow Issues Identified:**"), r["flow_analysis"]
    return "revised script and both analyses extracted"


@check("Hook-and-Summary client returns the opening statement")
def _():
    c = _client("hook_and_summary_agent_client", "HookAndSummaryAgentClient")
    reply = ("HOOK OPTION 1 (0-15 SECONDS):\nHook one.\n\nHOOK OPTION 2 (0-15 SECONDS):\nHook two.\n\n"
             "HOOK OPTION 3 (0-15 SECONDS):\nHook three.\n\nOPENING STATEMENT:\nHere is what you will learn.\n"
             "ANALYSIS: sets the stakes.\n\nSUMMARY/CONCLUSION:\nThat is the list.\n\nFLOW ANALYSIS:\nfine\n")
    c.send_message = lambda **kw: {"success": True, "response": reply, "sources": [], "error": None}
    r = c.generate_hook_and_summary(script_content="Host: hi", script_title="T")
    assert r["opening_statement"] == "Here is what you will learn.", r.get("opening_statement")
    assert r["hook3"] == "Hook three."
    return "opening_statement and opening_analysis present"


@check("Shorten: 'Heading: Chapter N' splitter and the one-time correction pass")
def _():
    from linedrive_azure.agents import script_shorten_agent_client as sh
    script = "Title\n\n" + "".join(f"Heading: Chapter {i} - X\n\nHost: words here.\n\n" for i in range(1, 4))
    assert len(sh._split_into_chapter_chunks(script)) == 4, "preamble + 3 chapters"

    def host(n, placeholders=(1,)):
        ph = " ".join(f"[[PRODUCTION_BLOCK_{p}]]" for p in placeholders)
        return f"Heading: Chapter 1 - X\n\nHost: {' '.join(['w'] * n)}\n\n{ph}\n"

    c = sh.ScriptShortenAgentClient()
    replies = [host(150), host(104)]
    c.create_thread = lambda: _ns(id="t")
    c.send_message = lambda **kw: {"success": True, "response": replies.pop(0), "sources": [], "error": None}
    r = c.shorten_to_target(host(300), target_minutes=1, wpm=100)
    assert r.get("correction_pass") == "150 -> 104", r.get("correction_pass")

    replies = [host(150), host(100, placeholders=())]  # second reply drops a placeholder
    r = c.shorten_to_target(host(300), target_minutes=1, wpm=100)
    assert r.get("correction_pass") == "150 -> 100 (rejected)", r.get("correction_pass")
    assert sh._app_host_words(host(100)) == 100
    return "kept a closer second reply; rejected one that dropped a placeholder"


@check("List/Predictions fix: review results are bound before the review can be skipped")
def _():
    src = open(os.path.join(APP, "linedrive_azure", "agents", "enhanced_autogen_system.py"), encoding="utf-8").read()
    skip = src.index('f"⏭️  STEP 3: Script Review SKIPPED for "')
    for var in ("revision_feedback", "chapter_comparisons"):
        first = re.search(rf"^\s*{var}: List\[Dict\[str, Any\]\] = \[\]", src, flags=re.M)
        assert first and first.start() < skip, f"{var} must be bound before the skip"
    return "both bound before the skip"


@check("List/Predictions chapters go to the hosted MAF writer unless SCRIPTCRAFT_CLAUDE_PRIMARY_WRITER=1")
def _():
    src = open(os.path.join(APP, "linedrive_azure", "agents", "enhanced_autogen_system.py"), encoding="utf-8").read()
    assert "if not is_teaching and _claude_primary:" in src
    assert '"SCRIPTCRAFT_CLAUDE_PRIMARY_WRITER"' in src
    return "direct Claude only when the switch is set; otherwise the fallback"


@check("Progress Log: '[maf]' lines show at the current progress; other unknown lines stay hidden")
def _():
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415  (module import does not start the server)

    sent = []
    streamer = _ns(send_update=lambda msg, prog: sent.append((msg, prog)))
    cap = web_gui.ConsoleCapture(streamer)
    cap.original_stdout = io.StringIO()
    cap.write("⏱️ [maf] Running Script-Topic-Assistant-Agent-MAF (hosted MAF agent, timeout=300s)...\n")
    cap.write('   🔎 [maf] Script-Topic-Assistant-Agent-MAF: web_search "x"\n')
    cap.write("some unrecognized line\n")
    assert [p for _, p in sent] == [14, 14], sent
    assert web_gui.VERSION.startswith("3."), web_gui.VERSION
    return "Running line at 14%, search line at 14%, unknown line dropped"


def _eas():
    from linedrive_azure.agents import enhanced_autogen_system as eas  # noqa: PLC0415
    return eas


@check("Agentic chapters: each chapter keeps exactly one 'Heading: Chapter N - Title' line")
def _():
    eas = _eas()
    norm = eas._normalize_chapter_heading
    body = "[Visual Cue: A cleanroom door slides open.]\n\n**Host:**\nPrediction number one."
    # The Predictions writer's format: a markdown heading with a timing, then a Heading: line.
    both = ("## Chapter 2: Prediction #1 - Intel 14A Becomes Terafab's Production Anchor (1:00)\n\n"
            "Heading: Chapter 2 - Prediction #1 - Intel 14A Becomes Terafab's Production Anchor\n\n" + body)
    want = "Heading: Chapter 2 - Prediction #1 - Intel 14A Becomes Terafab's Production Anchor\n\n" + body
    assert norm(both, 2, "ignored") == want, norm(both, 2, "ignored")
    assert norm(want, 2) == want, "not idempotent"
    # Only the markdown heading: its timing is dropped.
    assert norm("## Chapter 9: The Map, Redrawn (1:00)\n\n" + body, 9).startswith("Heading: Chapter 9 - The Map, Redrawn\n\n")
    # The teaching request's "(3+ minutes)" timing, bold markers, and the reviewer's bare Heading: line.
    assert norm("## Chapter 1: Setup (3+ minutes)\n" + body, 1).startswith("Heading: Chapter 1 - Setup\n")
    assert norm("**Chapter 4: Samsung Steps In**\n" + body, 4).startswith("Heading: Chapter 4 - Samsung Steps In\n")
    assert norm("Heading: The Closing Vision\n" + body, 9).startswith("Heading: Chapter 9 - The Closing Vision\n")
    # No heading at all: the chapter plan's title is used. A wrong number is replaced.
    assert norm(body, 3, "Prediction #2 - X (2:30)").startswith("Heading: Chapter 3 - Prediction #2 - X\n\n")
    assert norm("## Chapter 7: Wrong Number\n" + body, 6).startswith("Heading: Chapter 6 - Wrong Number\n")
    # Text after the heading is untouched, including a later line that mentions a chapter.
    later = body + "\nChapter 3 of the story starts here."
    assert norm("## Chapter 3: T\n\n" + later, 3) == "Heading: Chapter 3 - T\n\n" + later
    return "two headings -> one, timings dropped, idempotent, body unchanged"


@check("Agentic script: one title block when the review is skipped (List/Predictions)")
def _():
    src = open(os.path.join(APP, "linedrive_azure", "agents", "enhanced_autogen_system.py"), encoding="utf-8").read()
    assert "complete_revised_script_content = combined_script" not in src
    assert src.count("complete_revised_script_content = combined_chapters") == 3
    assert 'combined_chapters = "\\n\\n---\\n\\n".join(all_chapter_scripts)' in src
    return "skip and fallback paths use the chapters without the extra title block"


@check("De-shout: shouted lines are toned down, acronyms on normal lines are kept")
def _():
    ds = _eas()._deshout_text
    assert ds("BUILDING AI APPS WITH PYTHON") == "Building AI Apps With Python"
    assert ds("THE FUTURE OF WORK") == "The Future Of Work"
    assert ds("AI-POWERED WORKFLOWS") == "AI-Powered Workflows"
    for keep in ("Chapter 3: Prediction #2 - Terafab Places a Public ASML EUV Order",
                 "Chapter 5: Prediction #4 - TSMC Turns the Snub into a New Playbook",
                 "NVIDIA H100 vs AMD MI300X"):
        assert ds(keep) == keep, ds(keep)
    assert ds("A\nTHE FUTURE OF WORK\nTSMC") == "A\nThe Future Of Work\nTSMC"
    return "'ASML EUV' and 'TSMC' stay; 'THE FUTURE OF WORK' -> 'The Future Of Work'"


@check("Repeat-and-Flow: a dropped 'Heading: Chapter 1' line is restored, like a dropped '## Chapter 1'")
def _():
    cls = _client("script_repeat_and_flow_agent_client", "ScriptRepeatAndFlowAgentClient")
    fix = cls._restore_missing_chapter_one
    original = "Heading: Chapter 1 - The Week Musk Took Back the Keys\n\nHost: a\n\nHeading: Chapter 2 - Intel\n\nHost: b"
    dropped = "Host: a\n\nHeading: Chapter 2 - Intel\n\nHost: b"
    out = fix(dropped, original)
    assert out.split("\n\n")[1] == "Heading: Chapter 1 - The Week Musk Took Back the Keys", out
    assert fix(original, original) == original
    md = fix("Host: a\n\n## Chapter 2: Intel\n\nHost: b", "## Chapter 1: Start\n\nHost: a")
    assert md == "Host: a\n\n## Chapter 1: Start\n\n## Chapter 2: Intel\n\nHost: b", md
    plain = fix("Host: a\n\nChapter 2 - Intel\n\nHost: b", "")
    assert plain == "Host: a\n\nChapter 1 - Introduction\n\nChapter 2 - Intel\n\nHost: b", plain
    return "Heading:, ## and plain forms restored in their own form"


@check("Progress timer: the 2.5-minute hint matches the Script Writer choice; Process Script gets none")
def _():
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    fn = re.search(r"function _writerTimerHint\(writerMode, videoFormat, quickTest\) \{(.*?)\n        \}", html, re.S)
    assert fn, "hint function missing"
    body = fn.group(1)
    assert "if (writerMode === 'pro_classic') return 'Pro writes in one pass" in body
    assert "if (writerMode === 'pro_agent') return 'the Pro writer agent writes in one pass" in body
    assert "agentic writing plans, writes, and reviews each chapter" in body
    assert html.count("Pro writes in one pass") == 1, "the Pro hint must only come from _writerTimerHint"
    assert "startProgressTimer(_writerTimerHint(writerMode, videoFormat, quickTest));" in html
    assert "s >= 150 && _progressTimerHint ? ' · ' + _progressTimerHint : ''" in html
    calls = re.findall(r"startProgressTimer\(([^)]*)\)", html)
    assert "" in calls, "Process Script should start the timer without a hint"
    return "Pro classic, Pro agent, and agentic hints differ; Process Script has none"


@check("Pipeline reference: runs report the stages they completed, and saved versions keep them")
def _():
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415

    st = web_gui._artifact_stages
    assert st({}) == set()
    assert st({"broll_rows": [1], "broll_images": [1], "grok_videos": [1], "curl_commands": "x",
               "youtube_details": "x", "demo_packages": "x", "flow_analysis_report": "x"}) == {
        "broll_table", "broll_images", "grok", "heygen", "youtube", "demo", "flow"}
    src = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    assert '{"script"} | _stages_run | _artifact_stages(streamer.result)' in src, "create result"
    assert '{"load"} | _stages_run | _artifact_stages(streamer.result)' in src, "process result"
    assert '"stages_run": sorted({"load", "hook"} | _stages_run),' in src, "hook-only result"
    assert '"stages_run": result.get("stages_run"),' in src, "version manifest"
    for stage in ("hook", "shorten", "flow", "grok", "heygen", "demo"):
        assert f'_stages_run.add("{stage}")' in src, stage
    eas = open(os.path.join(APP, "linedrive_azure", "agents", "enhanced_autogen_system.py"), encoding="utf-8").read()
    assert eas.count('"hook_generated":') == 2, "Pro and agentic returns both report hook_generated"
    return "artifact stages mapped; create, process, hook-only and saved versions carry stages_run"


@check("Pipeline reference: every diagram step has a stage key, and finished runs record them")
def _():
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    docs = html[html.index('<div id="mobileWorkflowDocs"'):html.index("<!-- Current Output Directory display strip -->")]
    keys = re.findall(r'<div class="mwd-step" data-stage="([a-z_]+)">', docs)
    assert len(keys) == 19 and docs.count('class="mwd-step"') == 19, keys
    assert set(keys) == {"script", "load", "hook", "shorten", "flow", "broll_table", "broll_images",
                         "grok", "heygen", "youtube", "demo"}, set(keys)
    assert "function recordStagesRun(scriptId, stages)" in html
    assert "function renderPipelineHighlights()" in html
    assert html.count("recordStagesRun(window.currentScriptId, message.stages_run);") == 4
    assert "recordStagesRun(window.currentScriptId, ['load'].concat((ver && ver.stages_run) || []));" in html
    return "19 steps keyed; create, process, both hook-only paths, and script load record stages"


@check("LinkedIn drafts never say 'my' (the profile promotes the channel but didn't make it)")
def _():
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415

    f = web_gui._linkedin_without_my
    assert f("Check out my new video") == "Check out the new video"
    assert f("My latest breakdown") == "The latest breakdown"
    assert f('Watch "Why My AI Failed". My take: yes.') == 'Watch "Why My AI Failed". The take: yes.'
    assert f("#MyAI myth Amy") == "#MyAI myth Amy"
    src = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    gen = src[src.index("def _generate_linkedin_post("):src.index("@app.route(\"/api/linkedin/generate\"")]
    assert 'NEVER use the word \\"my\\"' in gen and "text = _linkedin_without_my(text)" in gen
    return "prompt rule present; 'my' -> 'the' outside quoted titles"


@check("Render Audio: a WAV can come from a finished video file (ffmpeg) as well as a Resolve timeline")
def _():
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415

    c = web_gui.app.test_client()
    assert c.post("/api/extract-audio", json={"video_path": ""}).get_json()["error"] == "Choose the finished video first."
    assert "Video not found" in c.post("/api/extract-audio", json={"video_path": "/nonexistent/x.mp4"}).get_json()["error"]
    src = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    worker = src[src.index("def _audio_extract_worker("):src.index('@app.route("/api/extract-audio"')]
    assert '"-map", "0:a:0", "-vn", "-c:a", "pcm_s16le"' in worker and "audio_render_streams" in worker
    assert 'status="done", output_file=output_file' in worker
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert 'name="renderAudioSource" value="video"' in html and 'name="renderAudioSource" value="resolve"' in html
    assert "fetch('/api/youtube/pick-video-path')" in html
    assert "source === 'resolve' ? '/api/resolve/render-audio' : '/api/extract-audio'" in html
    assert "Stage 1 — Render Audio (WAV)" in html
    return "endpoint validates input; worker writes 16-bit PCM WAV on the shared progress stream; dialog offers both sources"


@check("Thumbnails: Grok Imagine generator plans channel-style concepts and picks host + layout references")
def _():
    sys.path.insert(0, os.path.dirname(APP))  # repo root, for tools.media
    from tools.media import grok_thumbnail_generator as g  # noqa: PLC0415

    refs = g.load_references()
    assert len(refs) >= 11 and sum(r["host"] for r in refs) >= 9, len(refs)
    # Claude's loose answers map onto the fixed keys.
    c = g._clean_concept({"layout": "big number", "expression": "knowing smirk", "text": "62%"}, 1, "62%")
    assert (c["layout"], c["expression"], c["host_side"], c["text"]) == ("big_number", "smirk", "right", "62%")
    assert g._clean_concept({}, 1, "THE CHIP WAR IS HERE NOW")["text"] == "THE CHIP WAR IS"
    # References: 2 that show the host (planned expression first), then layout references.
    picked = g.pick_references({"layout": "mystery_scene", "expression": "worried"}, refs)
    assert 3 <= len(picked) <= g.MAX_REFERENCES and picked[0]["host"] and picked[1]["host"]
    assert picked[0]["expression"] == "worried"
    assert any("mystery_scene" in r["layouts"] for r in picked)
    big = g.pick_references({"layout": "big_number", "expression": "shocked"}, refs)
    assert big[0]["expression"] == "shocked" and sum("big_number" in r["layouts"] for r in big) >= 3
    prompt = g.build_render_prompt(c)
    assert '"62%", spelled exactly like that' in prompt and "do not copy their objects" in prompt
    assert "There is no text anywhere" in g.build_render_prompt({**c, "text": ""})
    fb = g.fallback_concepts(["CHIP WAR", "62% UP"], 2)
    assert len(fb) == 4 and fb[2]["layout"] == "big_number" and fb[0]["layout"] == "headline_text"
    src = open(g.__file__, encoding="utf-8").read()
    assert '_full.png' in src and "YOUTUBE_MAX_BYTES" in src, "full-res copies renamed; 2 MB limit kept"
    web = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    assert web.count("_make_thumbnail_generator(") >= 4, "create, process and the Thumbnails tool use the helper"
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert '<select id="thumbEngine"' in html and "engine: engine || 'grok'" in html
    return f"{len(refs)} refs; concepts normalized; host+layout references; engine choice wired"


@check("API Keys dialog: a saved key overrides .env and the shell at startup, as the dialog says")
def _():
    import json as _json
    import tempfile
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415

    keep_path, keep_env = web_gui.SCRIPTCRAFT_SETTINGS_PATH, os.environ.get("ANTHROPIC_API_KEY")
    with tempfile.TemporaryDirectory() as d:
        try:
            f = Path(d) / "settings.json"
            f.write_text(_json.dumps({"anthropic_api_key": "saved-in-dialog"}))
            web_gui.SCRIPTCRAFT_SETTINGS_PATH = f
            os.environ["ANTHROPIC_API_KEY"] = "old-from-dotenv"
            web_gui._hydrate_env_from_settings()
            assert os.environ["ANTHROPIC_API_KEY"] == "saved-in-dialog", os.environ["ANTHROPIC_API_KEY"]
            f.write_text(_json.dumps({}))                       # nothing saved: .env value stays
            os.environ["ANTHROPIC_API_KEY"] = "old-from-dotenv"
            web_gui._hydrate_env_from_settings()
            assert os.environ["ANTHROPIC_API_KEY"] == "old-from-dotenv"
        finally:
            web_gui.SCRIPTCRAFT_SETTINGS_PATH = keep_path
            if keep_env is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = keep_env
    return "saved key wins over the environment; without one, the environment value stays"


_WORD_COUNT_SAMPLE = """**My Title**

FINAL HOOK:
**Host:**

One two three four five.
[PRODUCTION BEGIN]
[GROK IMAGINE / RESOLVE] a garage at night with many words that are not spoken
[PRODUCTION END]

Title: My Title
Script-ID: ld-123
Script-Version: v-456
Script Type: Video
Audience: creators and solo business owners
Tone: energizing and confident

Heading: Chapter 1 - The Setup
**Host:**

Six seven eight.
[PRODUCTION BEGIN]
[VERIFY BEFORE RENDER] Confirm the price before render.
[PRODUCTION END]
Nine ten.

Heading: Chapter 2 - The Payoff
**Host:**

Eleven twelve.
Chapter 3 - A Heading Glued to the Dialogue (4:00-5:00)
Host:
Thirteen fourteen.
Summary: Fifteen sixteen.

=== SUPPORTING RESEARCH AND EXPERT PERSPECTIVES ===
Claims to check on render day: many words here that are not spoken.

=== FINAL PACKAGING (LOCKED PENDING REVIEW) ===
Title: A/B challenger title words

=== YOUTUBE VIDEO DESCRIPTION ===
A description with many more words that the avatar does not speak.

# 🎬 HEYGEN READY SCRIPT

One two three four five. Six seven eight. Nine ten. Eleven twelve. A second copy, not counted.
"""


@check("Word counts: spoken words only (Host content), the same on the server and the page's duration badge")
def _():
    import shutil
    import subprocess
    import tempfile
    from console_ui.text_processing import spoken_text, spoken_word_count

    # Hook 5 + chapter 1 5 + chapter 2 2 + 2 + summary 2 (its label dropped). Not counted: the
    # metadata block, production notes, the glued chapter heading, the trailing sections,
    # and the appended HEYGEN READY SCRIPT copy.
    assert spoken_word_count(_WORD_COUNT_SAMPLE) == 16, (spoken_word_count(_WORD_COUNT_SAMPLE), spoken_text(_WORD_COUNT_SAMPLE))
    assert "Chapter 3" not in spoken_text(_WORD_COUNT_SAMPLE) and "Summary" not in spoken_text(_WORD_COUNT_SAMPLE)
    # A production block still streaming in (no END yet) is not counted either.
    assert spoken_word_count("**Host:**\nOne two.\n[PRODUCTION BEGIN]\nnot spoken yet") == 2
    assert spoken_word_count("**Host:**\nOne [[PRODUCTION_BLOCK_0]] two.") == 2
    web = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    assert '"word_count": _spoken_word_count(final_script_with_tools),' in web
    assert '"word_count": _spoken_word_count(script_text) if script_text else 0,' in web
    assert web.count("return _spoken_word_count(text)") == 2, "both Shorten-step counters"
    sc = open(os.path.join(APP, "linedrive_azure", "agents", "script_shorten_agent_client.py"), encoding="utf-8").read()
    assert "return spoken_word_count(masked_script" in sc
    pw = open(os.path.join(APP, "linedrive_azure", "agents", "pro_script_writer.py"), encoding="utf-8").read()
    assert pw.count("spoken words\",") == 2
    # The page's badge runs a port of the same extraction: same count on the sample.
    node = shutil.which("node")
    if not node:
        return "server count checked; node not installed, so the badge port was not run"
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    js = html[html.index("        const _HG_SKIP_PATTERNS"):html.index("        // Build a small inline badge element from estimateHeyGenDuration().")]
    with tempfile.TemporaryDirectory() as d:
        sample = os.path.join(d, "sample.md")
        open(sample, "w", encoding="utf-8").write(_WORD_COUNT_SAMPLE)
        prog = os.path.join(d, "badge.js")
        open(prog, "w", encoding="utf-8").write(js + "\nconst fs = require('fs');\n"
            "console.log(estimateHeyGenDuration(fs.readFileSync(process.argv[2], 'utf8')).words);\n")
        out = subprocess.run([node, prog, sample], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr[:300]
    assert out.stdout.strip() == "16", out.stdout
    assert "const est = estimateHeyGenDuration(rawTxt, wpm);" in html, "Load Script panel uses the same count"
    return "16 spoken words on the sample from the server and the badge port; metadata, headings, trailing sections and the HeyGen copy excluded"


# The Pro writer's raw layout: the metadata block follows the hook's production
# block and a ____ divider with no blank line, so it used to glue onto the hook.
_PRO_RAW_SAMPLE = """FINAL HOOK:
Host:
One two three four five.
[PRODUCTION BEGIN]
[COLD OPEN / RESOLVE] not spoken
[PRODUCTION END]
________________________________________________________________________________
Title: My Title
Script-ID: ld-123
Script-Version: v-456
Script Type: Video
Duration: medium
**Generated:** 2026-07-21 12:14:06
Audience: creators
Tone: wry. PARSER RULE: skip everything between [PRODUCTION BEGIN] and [PRODUCTION END]; all Host: text is spoken.
________________________________________________________________________________

Heading: Chapter 1 - The Setup
Host:
[PRODUCTION BEGIN]
[ON SCREEN / RESOLVE] not spoken
[PRODUCTION END]
Six seven eight.
________________________________________________________________________________

Heading: Chapter 2 - The End
Host:
Nine ten.
"""


@check("Script duration: the Pro writer's metadata is not counted, and a Shorten run updates the script box")
def _():
    import shutil
    import subprocess
    import tempfile
    from console_ui.text_processing import spoken_text, spoken_word_count

    assert spoken_word_count(_PRO_RAW_SAMPLE) == 10, spoken_text(_PRO_RAW_SAMPLE)
    web = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    assert '"shortened_script": shortened_script,' in web
    assert '"shortened_script": streamer.result.get("shortened_script", ""),' in web
    assert 'f"✅ Shortened: {_before_host_words} → {_after_host_words} spoken words, "' in web
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert "_ta.value = message.shortened_script;" in html
    node = shutil.which("node")
    if not node:
        return "server count checked; node not installed, so the badge port was not run"
    js = html[html.index("        const _HG_SKIP_PATTERNS"):html.index("        // Build a small inline badge element from estimateHeyGenDuration().")]
    with tempfile.TemporaryDirectory() as d:
        sample = os.path.join(d, "sample.md")
        open(sample, "w", encoding="utf-8").write(_PRO_RAW_SAMPLE)
        prog = os.path.join(d, "badge.js")
        open(prog, "w", encoding="utf-8").write(js + "\nconst fs = require('fs');\n"
            "console.log(estimateHeyGenDuration(fs.readFileSync(process.argv[2], 'utf8')).words);\n")
        out = subprocess.run([node, prog, sample], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr[:300]
    assert out.stdout.strip() == "10", out.stdout
    return "10 spoken words on the raw Pro sample from the server and the badge port; the shortened script goes back to the script box"


@check("API Keys dialog: keys are masked, X keys save, and only this machine or a signed-in browser can read or change them")
def _():
    import json
    import tempfile
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415

    env_names = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET", "X_BEARER_TOKEN",
                 "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "HEYGEN_API_KEY", "XAI_API_KEY"]
    saved_env = {e: os.environ.get(e) for e in env_names}
    saved_path, saved_token = web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui.APP_AUTH_TOKEN
    remote = {"REMOTE_ADDR": "192.168.1.50"}
    try:
        with tempfile.TemporaryDirectory() as d:
            web_gui.SCRIPTCRAFT_SETTINGS_PATH = Path(d) / "settings.json"
            web_gui.APP_AUTH_TOKEN = ""
            c = web_gui.app.test_client()
            # Open app (no token): another device on the network can neither read nor change keys.
            for method, path in (("get", "/api/keys"), ("post", "/api/keys"), ("get", "/api/grok/key"), ("post", "/api/grok/key")):
                r = getattr(c, method)(path, json={"x_api_key": "attacker", "api_key": "attacker"}, environ_base=remote)
                assert r.status_code == 403, (path, r.status_code)
            assert not web_gui.SCRIPTCRAFT_SETTINGS_PATH.exists()
            # This machine: save X keys and a Claude key; values never come back, only masked hints.
            r = c.post("/api/keys", json={"x_api_key": " test-x-key-1234 ", "x_access_secret": "secret-9876",
                                          "anthropic_api_key": "sk-ant-test-abcd"})
            assert r.status_code == 200 and r.get_json()["success"], r.get_json()
            assert os.environ["X_API_KEY"] == "test-x-key-1234"
            assert json.loads(web_gui.SCRIPTCRAFT_SETTINGS_PATH.read_text())["x_access_secret"] == "secret-9876"
            got = c.get("/api/keys").get_json()
            body = json.dumps(got)
            assert "test-x-key-1234" not in body and "sk-ant-test-abcd" not in body, "a full key reached the browser"
            assert got["x_keys"]["x_api_key"]["present"] and got["x_keys"]["x_api_key"]["masked"].endswith("1234")
            assert got["keys"]["anthropic_api_key"].endswith("abcd") and got["sources"]["anthropic_api_key"] == "saved"
            # A masked hint posted back is ignored (keeps the current key).
            c.post("/api/keys", json={"anthropic_api_key": got["keys"]["anthropic_api_key"]})
            assert json.loads(web_gui.SCRIPTCRAFT_SETTINGS_PATH.read_text())["anthropic_api_key"] == "sk-ant-test-abcd"
            # Startup hydration sets the X env vars from saved settings.
            os.environ.pop("X_ACCESS_SECRET", None)
            web_gui._hydrate_env_from_settings()
            assert os.environ["X_ACCESS_SECRET"] == "secret-9876"
            # Token set: remote requests need it, and the sign-in form posts it (not in the URL).
            web_gui.APP_AUTH_TOKEN = "offline-check-token"
            assert c.get("/api/keys", environ_base=remote).status_code == 401
            ok = c.get("/api/keys", environ_base=remote, headers={"X-App-Token": "offline-check-token"})
            assert ok.status_code == 200 and "test-x-key-1234" not in json.dumps(ok.get_json())
            assert c.post("/login", data={"token": "wrong"}).status_code == 200
            r = c.post("/login", data={"token": "offline-check-token"}, headers={"X-Forwarded-Proto": "https"})
            cookie = r.headers.get("Set-Cookie", "")
            assert r.status_code == 303 and "app_token=" in cookie and "HttpOnly" in cookie and "Secure" in cookie, cookie
            assert '<form method="post" action="/login">' in c.get("/login").get_data(as_text=True)
    finally:
        web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui.APP_AUTH_TOKEN = saved_path, saved_token
        for e, v in saved_env.items():
            if v is None:
                os.environ.pop(e, None)
            else:
                os.environ[e] = v
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    for input_id in ("modalXApiKey", "modalXApiSecret", "modalXAccessToken", "modalXAccessSecret", "modalXBearerToken"):
        assert html.count(f'id="{input_id}"') == 1, input_id
    return "keys masked (last 4 only), masked hints ignored on save, X keys saved and loaded; remote 403 without a token, 401 with it set"


_GI_REPLACE_SAMPLE = """Title: Sample

**Host:**
Opening line about the news that everyone is talking about this week.
[PRODUCTION BEGIN]
[GROK IMAGINE / RESOLVE] old hook prompt.
[PRODUCTION END]

Heading: Chapter 1 - First
[PRODUCTION BEGIN]
[VERIFY BEFORE RENDER] Check the $40B figure.
[GROK IMAGINE / RESOLVE] old prompt one.
[QUOTE CARD / RESOLVE] "A quote" - Someone
[PRODUCTION END]
**Host:**
First paragraph of chapter one with enough words to count as a spoken beat here.
[PRODUCTION BEGIN]
[GROK IMAGINE / RESOLVE] old prompt two.
[PRODUCTION END]
Second paragraph of chapter one, also spoken by the host on camera today.
[PRODUCTION BEGIN]
[COLD OPEN / RESOLVE] Cut to the montage.
[PRODUCTION END]
Third paragraph of chapter one closes the section with a clear takeaway.

=== SUPPORTING RESEARCH ===
[PRODUCTION BEGIN]
[GROK IMAGINE / RESOLVE] tail prompt stays.
[PRODUCTION END]
"""


@check("Grok Imagine 'Replace existing prompts': old prompts and quote cards out, other cues kept, then a fresh rescan")
def _():
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415
    from console_ui.text_processing import spoken_text

    s = _GI_REPLACE_SAMPLE
    out, removed = web_gui._remove_grok_imagine_prompts(s)
    assert removed == 3, removed                       # body prompts only; the tail's stays
    body, tail = out.split("=== SUPPORTING RESEARCH ===")
    assert "old " not in body and "QUOTE CARD" not in body
    assert "[VERIFY BEFORE RENDER] Check the $40B figure." in body and "[COLD OPEN / RESOLVE] Cut to the montage." in body
    assert body.count("[PRODUCTION BEGIN]") == body.count("[PRODUCTION END]") == 2   # emptied blocks dropped
    assert "tail prompt stays." in tail and spoken_text(out) == spoken_text(s)
    assert web_gui._remove_grok_imagine_prompts(out) == (out, 0)

    calls = []
    real = web_gui._grok_imagine_assets_for_beat
    web_gui._grok_imagine_assets_for_beat = lambda beat, sec="", title="": (calls.append(beat) or "NEW prompt. style", None, None)
    try:
        new, added = web_gui._inject_grok_imagine_prompts(out, video_title="Sample")
    finally:
        web_gui._grok_imagine_assets_for_beat = real
    # Hook + 3 paragraphs: the one after the VERIFY-only block and the one after the cold open count too.
    assert added == 4 and new.count("NEW prompt.") == 4, (added, new)
    assert new.count("[VERIFY BEFORE RENDER]") == 1 and spoken_text(new).split() == spoken_text(s).split()
    src = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    stage = src[src.index('if checkboxes.get("grok_imagine", False):'):src.index("# HOOK-ONLY MODE")]
    assert 'checkboxes.get("grok_imagine_replace", False)' in stage and "cleaned_script = _gi_before" in stage
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert 'id="spsGrokImagineReplace"' in html and 'id="checkGrokImagineReplace"' in html
    assert "grok_imagine_replace: document.getElementById('checkGrokImagineReplace')?.checked || false" in html
    return "3 old prompts + quote card removed, VERIFY/cold open kept, tail untouched; rescan adds hook + 3; falls back if none come back"


@check("Thumbnail edits: a theme, a generated thumbnail, or an upload is edited by prompt (with optional logos) as a new version")
def _():
    import base64
    import io as _io
    import pathlib
    import tempfile
    from PIL import Image
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415
    from tools.media import grok_thumbnail_generator as g

    def png(color, size=(1600, 900)):
        buf = _io.BytesIO()
        Image.new("RGB", size, color).save(buf, "PNG")
        return buf.getvalue()

    sent = []

    def fake_sample(self, prompt, uris):
        sent.append((prompt, len(uris)))
        return png((10, 200, 10)), "fake-model"

    real = (g.GrokThumbnailGenerator._sample, pathlib.Path.home, web_gui._get_output_parent_dir,
            os.environ.get("XAI_API_KEY"))
    with tempfile.TemporaryDirectory() as d:
        home = pathlib.Path(d)
        try:
            g.GrokThumbnailGenerator._sample = fake_sample
            pathlib.Path.home = classmethod(lambda cls: home)
            web_gui._get_output_parent_dir = lambda: home / "Final"
            os.environ["XAI_API_KEY"] = os.environ.get("XAI_API_KEY") or "offline-check"
            c = web_gui.app.test_client()
            themes = c.get("/api/thumbnails/themes").get_json()["themes"]
            files = {t["file"] for t in themes}
            assert {"3_gold_neon.jpg", "9_gold_neon_public_figure.jpg", "broken_cracked_tablet.jpg"} <= files, files
            assert c.get(themes[0]["url"]).status_code == 200
            assert c.get("/api/thumbnails/theme-image/..%2Fgrok_thumbnail_generator.py").status_code == 404
            # Theme -> edit (mentions Roz, so her 2 reference photos go along)
            r = c.post("/api/thumbnails/edit", json={"source_kind": "theme", "source": "3_gold_neon.jpg",
                                                     "instruction": "change the 3! to a 9 and keep Roz pointing"})
            t1 = r.get_json()
            assert r.status_code == 200 and t1["success"], t1
            assert sent[-1][1] == 3 and "Make only this change: change the 3! to a 9" in sent[-1][0]
            p1 = pathlib.Path(t1["thumbnail"]["filepath"])
            assert p1.parent == home / "Dev" / "Thumbnails" / "edits" and p1.is_file()
            assert Image.open(p1).size == (1280, 720) and pathlib.Path(t1["thumbnail"]["full_path"]).is_file()
            # Generated -> edit again (no host mention: only the image itself), saved next to it
            r = c.post("/api/thumbnails/edit", json={"source_kind": "generated", "source": p1.name,
                                                     "instruction": "use Elon Musk instead of her"})
            t2 = r.get_json()["thumbnail"]
            assert sent[-1][1] == 1 and pathlib.Path(t2["filepath"]).parent == p1.parent
            assert re.match(r"^3_gold_neon_edit_\d{8}_\d{6}\.png$", t2["filename"]), t2["filename"]
            assert c.get(f"/thumbnails/{t2['filename']}").status_code == 200
            # Upload -> edit
            up = "data:image/png;base64," + base64.b64encode(png((200, 0, 0), (640, 360))).decode()
            r = c.post("/api/thumbnails/edit", json={"source_kind": "upload", "source": up, "instruction": "add a 9"})
            assert r.status_code == 200 and r.get_json()["success"]
            # Refusals
            assert c.post("/api/thumbnails/edit", json={"source_kind": "theme", "source": "3_gold_neon.jpg"}).status_code == 400
            assert c.post("/api/thumbnails/edit", json={"source_kind": "generated", "source": "*.png", "instruction": "x"}).status_code == 404
            assert c.get("/thumbnails/*.png").status_code == 404
            # Included images (a logo): sent after the thumbnail, transparency kept
            buf = _io.BytesIO()
            Image.new("RGBA", (300, 300), (255, 0, 0, 0)).save(buf, "PNG")
            logo = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
            r = c.post("/api/thumbnails/edit", json={"source_kind": "generated", "source": p1.name,
                                                     "instruction": "add the logo top-right", "include_images": [logo]})
            assert r.status_code == 200 and r.get_json()["thumbnail"]["included_images"] == 1, r.get_json()
            assert sent[-1][1] == 2 and "The 2nd image is supplied to be added" in sent[-1][0]
            assert g._include_data_uri(buf.getvalue()).startswith("data:image/png")
            # 3 logos + Roz named: 1 thumbnail + 3 includes + 1 Roz reference = the 5-image limit
            r = c.post("/api/thumbnails/edit", json={"source_kind": "generated", "source": p1.name,
                                                     "instruction": "have Roz hold the logos", "include_images": [logo] * 3})
            assert r.status_code == 200 and sent[-1][1] == 5 and "The last image shows Roz" in sent[-1][0]
            assert c.post("/api/thumbnails/edit", json={"source_kind": "generated", "source": p1.name,
                                                        "instruction": "x", "include_images": [logo] * 4}).status_code == 400
            assert c.post("/api/thumbnails/edit", json={"source_kind": "generated", "source": p1.name,
                                                        "instruction": "x", "include_images": ["not an image"]}).status_code == 400
        finally:
            (g.GrokThumbnailGenerator._sample, pathlib.Path.home, web_gui._get_output_parent_dir) = real[:3]
            if real[3] is None:
                os.environ.pop("XAI_API_KEY", None)
            else:
                os.environ["XAI_API_KEY"] = real[3]
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert "async function editCurrentThumbnail(el)" in html and "function openThumbnailThemeEditor()" in html
    assert "if (choice.mode === 'theme') {" in html and 'class="thumbnail-gallery" data-gallery="${gid}"' in html
    # Gallery controls are found inside the clicked gallery, never by a page-wide ID.
    gallery = html[html.index("function renderThumbnailGallery("):html.index("async function openThumbnailThemeEditor()")]
    assert "getElementById" not in gallery and 'onclick="editCurrentThumbnail(this)"' in gallery
    assert "include_images: includes.map(i => i.dataUrl)" in gallery
    # Save as… / Save 2K as…: the browser's save-location picker opens before the fetch.
    save = gallery[gallery.index("async function saveCurrentThumbnail(el, full)"):gallery.index("function nextThumbnail(el)")]
    assert save.index("window.showSaveFilePicker({") < save.index("await fetch(url)")
    assert "name = base(thumb.full_path);" in save and "a.download = name;" in save
    css = html[html.index(".tg-edit-input {"):html.index(".tg-include-chips {")]
    assert css.count("height: 40px") == 2 and ".tg-btn:active:not(:disabled) { transform: translateY(3px)" in css
    return ("themes listed and served; theme, generated and uploaded sources edit into new 1280x720 + full files; "
            "included images (logos) sent after the thumbnail, Roz refs fit the 5-image limit; globs refused")



@check("Title Picker: the chosen title replaces the Title: line and top heading; the YouTube section is untouched")
def _():
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415

    f = web_gui._apply_script_title
    out, ch = f("# Old Heading\n\nTitle: Old\nScript-ID: ld-1\n\nHeading: Chapter 1 - A\n"
                "=== YOUTUBE VIDEO DESCRIPTION ===\nTitle: A/B title stays", "New Title")
    assert ch == ["Title: line", "top heading"], ch
    assert out.startswith("# New Title\n") and "\nTitle: New Title\n" in out and "Title: A/B title stays" in out
    assert f("**Title:** Old\nHeading: Chapter 1 - A", "N")[0].startswith("**Title:** N")
    out, ch = f("Heading: Chapter 1 - A\n**Host:**\nHi.", "Fresh")
    assert ch == ["added Title: line"] and out.startswith("Title: Fresh\n\nHeading: Chapter 1")
    assert web_gui._extract_script_title_for_output(out, "") == "Fresh"
    c = web_gui.app.test_client()
    assert c.post("/api/titles/apply", json={"script": "Title: a", "title": ""}).status_code == 400
    assert c.post("/api/titles/apply", json={"script": "Title: a", "title": "x" * 101}).status_code == 400
    assert c.post("/api/titles/suggest", json={"script": " "}).status_code == 400
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert "'demo','title','elevenlabs','explainer'];" in html and 'data-sps-stage="title"' in html
    assert "const _SPS_DIALOGS = ['title', 'elevenlabs', 'explainer'];" in html
    for k in ("elevenlabs", "explainer"):
        assert f'data-sps-stage="{k}"' in html and f"spsOpenDialogStage('{k}')" in html and f"spsDialogClosed('{k}')" in html
    assert "spsDialogClosed('title')" in html and html.count("spsNextDialog(processedScript);") == 1
    assert "if (key === 'title') openTitlePicker(" in html and "function openTitlePicker(script)" in html
    # Both dialogs open a script themselves and follow the script that opens.
    assert "onclick=\"elOpenScript()\"" in html and "class=\"xv-btn\" onclick=\"openScriptChooser()\"" in html
    assert "refreshScriptDialogs();" in html and html.count("z-index:10060; background:rgba(2,6,23,0.72)") == 2
    return ("Title: line + top heading replaced, a Title: line added when missing, YouTube A/B titles kept; "
            "Title Picker, ElevenLabs Audio, Explainer Video are the dialog stages after processing")



@check("X replies: only posts Grok's X search really returned are kept; replies never say 'my'")
def _():
    import json
    import types as _types
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415
    import xai_sdk

    posts = [
        {"url": "https://x.com/real/status/111", "handle": "@real", "text": "Is it safe?", "reply": "Start with my one task."},
        {"url": "https://x.com/madeup/status/999", "handle": "@madeup", "text": "?", "reply": "x"},
        {"url": "https://twitter.com/AIwithRoz/status/222", "handle": "@AIwithRoz", "text": "ours", "reply": "x"},
        {"url": "https://x.com/real/status/111", "handle": "@real", "text": "dup", "reply": "x"},
        {"url": "not a link", "reply": "x"},
    ]
    created = {}

    class FakeChat:
        def append(self, m): pass
        def sample(self):
            return _types.SimpleNamespace(
                content="```json\n" + json.dumps({"posts": posts}) + "\n```",
                citations=["https://x.com/real/status/111", "https://x.com/AIwithRoz/status/222"],
                server_side_tool_usage={"X_SEARCH": 3})

    class FakeClient:
        def __init__(self, api_key=None):
            self.chat = _types.SimpleNamespace(create=lambda **kw: created.update(kw) or FakeChat())

    real_client, real_key = xai_sdk.Client, web_gui._resolve_xai_api_key
    try:
        xai_sdk.Client = FakeClient
        web_gui._resolve_xai_api_key = lambda: "offline-check"
        out = web_gui._find_x_reply_targets("Episode", "desc", "https://youtu.be/x")
        c = web_gui.app.test_client()
        assert c.post("/api/x/related", json={}).status_code == 400
        r = c.post("/api/x/related", json={"title": "Episode"}).get_json()
    finally:
        xai_sdk.Client, web_gui._resolve_xai_api_key = real_client, real_key
    assert [p["handle"] for p in out] == ["@real"] and out[0]["id"] == "111", out
    assert out[0]["reply"] == "Start with the one task." and out[0]["url"] == "https://x.com/real/status/111"
    assert r["success"] and len(r["posts"]) == 1
    assert created["tools"] and created["max_turns"] == 6
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert "async function findXReplyTargets()" in html and "https://x.com/intent/post?in_reply_to=" in html
    return "made-up, own-account, duplicate and malformed posts dropped; 'my' removed; copy + Reply on X wired"



@check("YouTube thumbnails over 2 MB are sent as a JPEG under 2 MB (the Google client refuses bigger media), and a failed thumbnail can be retried without a re-upload")
def _():
    import io as _io
    import tempfile
    from pathlib import Path
    from PIL import Image
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415
    import youtube_publisher as yp
    from googleapiclient.errors import MediaUploadSizeError, HttpError

    class _Svc:
        """thumbnails().set like the real client: media over the discovery
        doc's 2 MB maxSize is refused before anything is sent."""
        def __init__(self):
            self.sent = []
        def thumbnails(self):
            return self
        def set(self, videoId, media_body):
            if media_body.size() > 2097152:
                raise MediaUploadSizeError("Media larger than: 2097152")
            self.sent.append((videoId, media_body.mimetype(), media_body.size()))
            return self
        def execute(self):
            return {"kind": "youtube#thumbnailSetResponse"}

    assert yp.MAX_THUMBNAIL_BYTES == 50 * 1024 * 1024 and yp.LEGACY_THUMBNAIL_BYTES == 2 * 1024 * 1024
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        # A noisy 2816x1584 PNG (like the 6.3 MB split-edit thumbnail), well over 2 MB.
        big = d / "thumb_full.png"
        Image.frombytes("RGB", (2816, 1584), os.urandom(2816 * 1584 * 3)).save(big, "PNG")
        assert big.stat().st_size > 5 * 1024 * 1024
        real_dir = web_gui._yt_uploads_dir
        try:
            web_gui._yt_uploads_dir = lambda: d
            c = web_gui.app.test_client()
            r = c.post("/api/youtube/upload-thumbnail", content_type="multipart/form-data",
                       data={"file": (_io.BytesIO(big.read_bytes()), "big.png")})
            assert r.status_code == 200 and r.get_json()["size_bytes"] > 5 * 1024 * 1024, r.get_json()
        finally:
            web_gui._yt_uploads_dir = real_dir

        svc = _Svc()
        ok, err = yp.set_thumbnail("nZ5MQL-OIUo", big, service=svc)
        assert ok and err is None and svc.sent[0][0] == "nZ5MQL-OIUo", (ok, err)
        assert svc.sent[0][1] == "image/jpeg" and svc.sent[0][2] <= yp.LEGACY_THUMBNAIL_BYTES
        assert (d / "thumb_full_youtube.jpg").is_file()
        small = d / "small.png"
        Image.new("RGB", (1280, 720), (12, 20, 40)).save(small, "PNG")
        ok, _ = yp.set_thumbnail("nZ5MQL-OIUo", small, service=svc)
        assert ok and svc.sent[1][1] == "image/png"                     # small files go as they are

        class _Refuse(_Svc):
            def set(self, videoId, media_body):
                raise HttpError(type("R", (), {"status": 403, "reason": "Forbidden"})(),
                                b'{"error": {"errors": [{"reason": "forbidden"}]}}')
        ok, err = yp.set_thumbnail("nZ5MQL-OIUo", small, service=_Refuse())
        assert not ok and "forbidden" in err

        # Retry route: validates, then calls set_thumbnail for the published video.
        calls = []
        real_set = yp.set_thumbnail
        yp.set_thumbnail = lambda vid, tp: (calls.append((vid, str(tp))) or (True, None))
        try:
            c = web_gui.app.test_client()
            assert c.post("/api/youtube/set-thumbnail", json={"video_id": "x", "thumbnail_path": str(big)}).status_code == 400
            assert c.post("/api/youtube/set-thumbnail", json={"video_id": "nZ5MQL-OIUo", "thumbnail_path": str(d / "nope.png")}).status_code == 400
            r = c.post("/api/youtube/set-thumbnail", json={"video_id": "nZ5MQL-OIUo", "thumbnail_path": str(big)})
            assert r.status_code == 200 and r.get_json()["success"] and calls == [("nZ5MQL-OIUo", str(big))]
        finally:
            yp.set_thumbnail = real_set
    src = open(os.path.join(APP, "youtube_publisher.py"), encoding="utf-8").read()
    assert "thumbnail_set, thumbnail_error = set_thumbnail(" in src and "_is_size_rejection" not in src
    web = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    assert web.count("yp.MAX_THUMBNAIL_BYTES") >= 4 and "2 * 1024 * 1024:" not in web
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert 'onclick="retryYouTubeThumbnail(' in html and "async function retryYouTubeThumbnail(videoId)" in html
    return "6 MB PNG sent as a <2 MB JPEG (client size check passes), small PNG as is, API refusal reported; retry route validates and sets"



@check("Golden reference and channel playbook: the Musk script and the analytics lessons reach the writers, ideas, briefs, and titles; ideas build on the golden episode")
def _():
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415
    from linedrive_azure.agents import pro_script_writer as psw

    golden = psw.load_golden_reference()
    assert golden.startswith("FINAL HOOK:") and "Musk" in golden and "Heading: Chapter 7" in golden
    assert "=== FINAL PACKAGING" in golden and "changes per Roz" not in golden   # revision log left out
    playbook = psw.load_channel_playbook()
    assert "Musk Will Win the AI Race - Here is Why" in playbook and "Provocative, not false" in playbook
    msg = psw.build_pro_user_message("Test title", "Test brief")
    assert "<golden_reference>" in msg and "<channel_playbook>" in msg and golden[-200:] in msg   # whole reference, not cut
    real_recent = web_gui._recent_scripts_for_style_context
    web_gui._recent_scripts_for_style_context = lambda **kw: []      # no cloud lookups offline
    try:
        style = web_gui._build_style_context_block()
    finally:
        web_gui._recent_scripts_for_style_context = real_recent
    assert "CHANNEL PLAYBOOK" in style and "GOLDEN REFERENCE" in style
    assert "Musk Will Win the AI Race" in web_gui._TITLE_SYSTEM and "provocative" in web_gui._TITLE_SYSTEM
    assert web_gui._GOLDEN_CLOUD_VID == "v2" and "Musk Will Win" in web_gui._GOLDEN_CLOUD_TITLE
    src = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    ideas = src[src.index("def api_ideas_generate("):src.index("def _gen_claude():")]
    assert "provocative, opinionated videos" in ideas and "'The Power Play'" in ideas and "+ _channel_playbook_block()" in ideas
    assert "punchy, optimistic" not in ideas
    # The idea generator gets the golden reference as its model episode: Claude and Grok
    # both see its title, hook, chapters, and verdict, and with no topic typed about
    # three ideas continue its story.
    seen = {}
    stubs = {"_anthropic_complete": lambda system, user, **kw: (seen.setdefault("claude", []).append(system) or seen.setdefault("max_tokens", kw["max_tokens"]) and '[{"title": "A", "angle": "B"}]'),
             "_grok_complete": lambda system, user, **kw: (seen.setdefault("grok", []).append(system) or '[{"title": "C", "angle": "D"}]'),
             "_fetch_top_youtube_ai_titles": lambda n: [],
             "_save_idea_batch": lambda req, ideas, **kw: {"id": "test-batch"}}
    real = {k: getattr(web_gui, k) for k in stubs}
    try:
        for k, v in stubs.items():
            setattr(web_gui, k, v)
        c = web_gui.app.test_client()
        assert c.post("/api/ideas/generate", json={}).get_json()["success"]
        assert c.post("/api/ideas/generate", json={"request": "AI in hospitals"}).get_json()["success"]
    finally:
        for k, v in real.items():
            setattr(web_gui, k, v)
    free, topic = seen["claude"]
    assert seen["max_tokens"] >= 16000      # room to write the JSON after the searches
    assert seen["grok"] == seen["claude"]
    for system in (free, topic):
        assert 'MODEL EPISODE' in system and 'Title: "Musk Will Win the AI Race - Here is Why"' in system
        assert "weapon four is already parked in your driveway" in system and "Chapter 5 - Weapon Four" in system and "Yes, he can win." in system
        assert "[PRODUCTION BEGIN]" not in system and "COLD OPEN" not in system
    assert "About three of the ten ideas should continue it" in free and "stance and structure only" not in free
    assert "stance and structure only" in topic and "About three of the ten" not in topic
    brief = src[src.index("You are a creative director writing a production brief"):src.index("logger.info(\"✍️ Brief requested")]
    assert "provocative, opinionated YouTube video" in brief and "_channel_playbook_block()" in brief and "energizing, optimistic" not in brief
    return f"golden reference {len(golden):,} chars embedded whole; playbook in Pro, style context, ideas, briefs, and titles; ideas pitch follow-ups to the golden episode"


@check("Analytics: per-video report, retention drops, impressions/CTR from daily reach reports or a Studio import, routes, and the toolbar dialog")
def _():
    import io as _io
    import json
    import tempfile
    import types as _types
    import zipfile
    from datetime import date
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415
    import youtube_analytics as ya

    assert ya.window("28", date(2026, 10, 29)) == ("2026-10-01", "2026-10-28")
    assert ya.window("lifetime", date(2026, 10, 29))[0] == "2005-04-01"
    assert ya._iso_duration_seconds("PT8M44S") == 524 and ya._iso_duration_seconds("PT1H2M3S") == 3723

    class Exec:
        def __init__(self, v): self.v = v
        def execute(self): return self.v
    calls = {}
    report = {"columnHeaders": [{"name": n} for n in ["video"] + ya.VIDEO_METRICS],
              "rows": [["yHyhG6nHsKs", 903, 2574, 171, 32.6, 40, 5, 3, 12],
                       ["k09qNviJ4oM", 154, 438, 175, 28.2, 9, 1, 0, 2]]}
    retention = {"columnHeaders": [{"name": "elapsedVideoTimeRatio"}, {"name": "audienceWatchRatio"}, {"name": "relativeRetentionPerformance"}],
                 "rows": [[0.01, 1.0, 0.5], [0.03, 0.7, 0.5], [0.1, 0.6, 0.55], [0.2, 0.45, 0.4], [0.3, 0.43, 0.4], [0.5, 0.30, 0.3]]}
    lifetime = {"columnHeaders": [{"name": n} for n in ["video", "views", "averageViewDuration", "averageViewPercentage"]],
                "rows": [["yHyhG6nHsKs", 1200, 165, 31.5], ["k09qNviJ4oM", 300, 180, 29.0]]}
    summary = {"columnHeaders": [{"name": n} for n in ["views", "averageViewDuration", "averageViewPercentage"]],
               "rows": [[1200, 165, 31.5]]}
    def query(**kw):
        calls.setdefault("q", []).append(kw)
        if kw.get("dimensions") == "elapsedVideoTimeRatio":
            return Exec(retention)
        if not kw.get("dimensions"):
            return Exec(summary)
        return Exec(lifetime if kw["startDate"] == "2005-04-01" else report)
    yta = _types.SimpleNamespace(reports=lambda: _types.SimpleNamespace(query=query))
    meta = {"items": [
        {"id": "yHyhG6nHsKs", "snippet": {"title": "Musk Will Win the AI Race - Here is Why", "publishedAt": "2026-08-27T15:00:00Z",
                                          "thumbnails": {"medium": {"url": "https://i.ytimg.com/vi/x/mq.jpg"}}},
         "contentDetails": {"duration": "PT8M44S"}},
        {"id": "k09qNviJ4oM", "snippet": {"title": "Everyone Fears AI Taking Jobs - Nobody Sees the Raise", "publishedAt": "2026-07-20T15:00:00Z", "thumbnails": {}},
         "contentDetails": {"duration": "PT10M22S"}}]}
    yt = _types.SimpleNamespace(videos=lambda: _types.SimpleNamespace(list=lambda **kw: Exec(meta)))

    with tempfile.TemporaryDirectory() as d:
        real = (ya.REACH_PATH, ya.TOKEN_PATH, ya.DAILY_REACH_PATH)
        ya.REACH_PATH, ya.TOKEN_PATH, ya.DAILY_REACH_PATH = Path(d) / "reach.json", Path(d) / "token.json", Path(d) / "daily.json"
        try:
            csv_text = ("Content,Video title,Video publish time,Duration,Impressions,Impressions click-through rate (%),Views\n"
                        "Total,,,,54995,2.5,4060\n"
                        "yHyhG6nHsKs,Musk Will Win the AI Race - Here is Why,\"Aug 27, 2026\",524,\"4,604\",4.7,903\n"
                        "k09qNviJ4oM,Everyone Fears AI Taking Jobs,\"Jul 20, 2026\",622,443,10.6,154\n")
            assert ya.parse_studio_export(csv_text.encode())["yHyhG6nHsKs"] == {"impressions": 4604, "ctr": 4.7}
            buf = _io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("Table data.csv", "﻿" + csv_text)
            assert ya.import_studio_export(buf.getvalue(), "export.zip")["videos"] == 2
            # Studio's current export (2026-10): 'Thumbnail impressions' and 'Thumbnail
            # click-through rate (%)', with Totals.csv giving the days it covers.
            new_csv = ("Content,Video title,Video publish time,Duration,Thumbnail impressions,Thumbnail click-through rate (%),Views,Average view duration,Watch time (hours),Hypes\n"
                       "Total,,,,54995,2.47,4060,0:02:55,132.776,0\n"
                       "yHyhG6nHsKs,Musk Will Win the AI Race - Here is Why,\"Aug 27, 2026\",524,4604,4.69,903,0:02:51,16.5433,0\n"
                       "k09qNviJ4oM,Everyone Fears AI Taking Jobs - Nobody Sees the Raise,\"Jul 20, 2026\",622,443,10.61,154,0:02:55,7.2795,0\n")
            zbuf = _io.BytesIO()
            with zipfile.ZipFile(zbuf, "w") as z:
                z.writestr("Table data.csv", "\ufeff" + new_csv)
                z.writestr("Totals.csv", "Date,Views\n2026-05-28,5\n2026-05-29,18\n2026-10-28,53\n")
            res = ya.import_studio_export(zbuf.getvalue(), "Content 2026-05-28_2026-10-29 AI with Roz.zip")
            assert res["videos"] == 2 and (res["first"], res["last"]) == ("2026-05-28", "2026-10-28"), res
            assert ya.load_reach()["videos"]["yHyhG6nHsKs"] == {"impressions": 4604, "ctr": 4.69}
            assert ya._parse_studio_export(new_csv.encode(), "Content 2026-05-28_2026-10-29 AI with Roz.csv")[1] == ("2026-05-28", "2026-10-29")
            assert ya.import_studio_export(buf.getvalue(), "export.zip")["videos"] == 2
            rep = ya.video_report("28", services=(yta, yt))
            v0 = rep["videos"][0]
            assert v0["title"].startswith("Musk") and v0["duration_seconds"] == 524 and v0["impressions"] == 4604 and v0["ctr"] == 4.7
            assert v0["watch_hours"] == 42.9 and v0["avg_view_duration"] == 171
            assert rep["reach"]["source"] == "studio" and rep["reach"]["daily_job"] is False
            assert calls["q"][0]["dimensions"] == "video" and calls["q"][0]["sort"] == "-views"
            # A windowed report carries each video's lifetime average (a few views can average 0:00).
            assert v0["lifetime"] == {"views": 1200, "avg_view_duration": 165, "avg_view_percentage": 31.5}
            assert ya.video_report("lifetime", services=(yta, yt))["videos"][0]["lifetime"] is None
            t = rep["totals"]
            # Total average view from raw minutes, not the per-video 0.1-hour rounding.
            assert t["avg_view_duration"] == round((2574 + 438) * 60 / 1057), t
            assert t["views"] == 1057 and t["impressions"] == 5047 and abs(t["ctr"] - round((4604 * 4.7 + 443 * 10.6) / 100 / 5047 * 100, 1)) < 0.05
            ret = ya.retention("yHyhG6nHsKs", services=(yta, yt))
            assert calls["q"][-1]["filters"] == "video==yHyhG6nHsKs" and len(ret["points"]) == 6
            assert ret["avg_view_duration"] == 165 and ret["avg_view_percentage"] == 31.5
            # Falls that start in the first 5 percent (0.01 and 0.03) are the opening; skipped.
            assert [round(x["t"], 2) for x in ret["drops"]] == [0.2, 0.3, 0.5], ret["drops"]
            # The end screen's fall is skipped too.
            assert ya.biggest_drops([{"t": 0.5, "watch": 0.3}, {"t": 0.9, "watch": 0.29}, {"t": 0.99, "watch": 0.1}]) == [{"t": 0.9, "drop": 0.01}]
            for bad in ("x", "abc/../../etc"):
                try:
                    ya.retention(bad, services=(yta, yt)); raise AssertionError("bad id accepted")
                except ValueError:
                    pass
            try:
                ya.parse_studio_export(b"Video title,Views\nA,1\n"); raise AssertionError("bad csv accepted")
            except ValueError as e:
                assert "impressions" in str(e)
            # Daily reach reports (Reporting API): the job is made once, reports download
            # once each, a newer report of the same day wins, CTR fractions become percents.
            jobs, made, listed = [], [], []
            def _create(body):
                made.append(body); jobs.append({"id": "job1", "reportTypeId": body["reportTypeId"], "createTime": "2026-10-29T20:00:00Z"})
                return Exec(jobs[-1])
            pages = {None: {"reports": [{"id": "r1", "startTime": "2026-10-20T07:00:00Z", "createTime": "2026-10-29T21:00:00Z", "downloadUrl": "u1"},
                                        {"id": "r2", "startTime": "2026-10-21T07:00:00Z", "createTime": "2026-10-29T21:00:00Z", "downloadUrl": "u2"}],
                             "nextPageToken": "p2"},
                     "p2": {"reports": [{"id": "r3", "startTime": "2026-10-20T07:00:00Z", "createTime": "2026-10-30T09:00:00Z", "downloadUrl": "u3"},
                                        {"id": "r4", "startTime": "2026-10-22T07:00:00Z", "createTime": "2026-10-30T09:00:00Z", "downloadUrl": "u4"}]}}
            def _reports_list(jobId, pageToken=None):
                listed.append(pageToken); assert jobId == "job1"
                return Exec(pages[pageToken])
            yr = _types.SimpleNamespace(jobs=lambda: _types.SimpleNamespace(
                list=lambda: Exec({"jobs": list(jobs)}), create=_create,
                reports=lambda: _types.SimpleNamespace(list=_reports_list)))
            head = "date,channel_id,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n"
            files = {"u1": head + "20261020,UC1,yHyhG6nHsKs,1000,0.01\n",           # superseded by u3
                     "u2": head + "20261021,UC1,yHyhG6nHsKs,500,0.06\n20261021,UC1,k09qNviJ4oM,200,0.1\n",
                     "u3": head + "20261020,UC1,yHyhG6nHsKs,1000,0.04\n",
                     "u4": head + "20261022,UC1,k09qNviJ4oM,0,0\n"}             # a day with no impressions
            assert ya.start_daily_reach(yr)["job_id"] == "job1" and ya.start_daily_reach(yr)["job_id"] == "job1"
            assert len(made) == 1 and made[0]["reportTypeId"] == "channel_reach_basic_a1"
            state = ya.sync_daily_reach(yr, fetch=lambda u: files[u].encode())
            assert listed == [None, "p2"] and sorted(state["days"]) == ["2026-10-20", "2026-10-21", "2026-10-22"]
            assert state["days"]["2026-10-20"]["videos"]["yHyhG6nHsKs"] == [1000, 0.04] and state["days"]["2026-10-22"]["videos"] == {}
            ya.sync_daily_reach(yr, fetch=lambda u: 1 / 0)                       # within 6 hours: no API calls
            assert listed == [None, "p2"]
            agg = ya.daily_reach_for("2026-10-20", "2026-10-22")
            assert agg["videos"]["yHyhG6nHsKs"] == {"impressions": 1500, "ctr": round((40 + 30) / 1500 * 100, 1)}
            assert agg["videos"]["k09qNviJ4oM"] == {"impressions": 200, "ctr": 10.0} and (agg["first"], agg["days"]) == ("2026-10-20", 3)
            assert ya._ctr_scale({"days": {"d": {"videos": {"v": [100, 4.7]}}}}) == 1.0     # already percents
            # A window the daily reports cover uses them; lifetime keeps the Studio import.
            real_window = ya.window
            ya.window = lambda rk, today=None: ("2026-10-20", "2026-10-22") if rk != "lifetime" else ("2005-04-01", "2026-10-22")
            try:
                r7 = ya.video_report("7", services=(yta, yt))
                assert r7["reach"]["source"] == "daily" and r7["reach"]["covers_window"] and r7["videos"][0]["impressions"] == 1500
                assert ya.video_report("lifetime", services=(yta, yt))["reach"]["source"] == "studio"
                ya.REACH_PATH.unlink()
                rl = ya.video_report("lifetime", services=(yta, yt))
                assert rl["reach"]["source"] == "daily" and rl["reach"]["covers_window"] is False
            finally:
                ya.window = real_window
            c = web_gui.app.test_client()
            st = c.get("/api/analytics/status").get_json()
            assert st["success"] and st["connected"] is False and st["reach_videos"] == 0 and st["daily_job"] and st["daily_days"] == 3
            assert c.post("/api/analytics/daily-reach/start").status_code == 401
            assert ya.import_studio_export(buf.getvalue(), "export.zip")["videos"] == 2
            r = c.get("/api/analytics/videos?range=28")
            assert r.status_code == 401 and r.get_json()["connected"] is False
            assert c.get("/api/analytics/videos?range=bogus").status_code == 400
            assert c.post("/api/analytics/import-reach").status_code == 400
            real_ac = web_gui._anthropic_complete
            seen = {}
            web_gui._anthropic_complete = lambda system, user, **kw: (seen.update(user=user, max_tokens=kw["max_tokens"]) or "## What drives clicks\nNamed players.")
            try:
                r = c.post("/api/analytics/insights", json={"videos": rep["videos"], "start": rep["start"], "end": rep["end"]})
            finally:
                web_gui._anthropic_complete = real_ac
            assert r.get_json()["success"] and "Musk Will Win" in seen["user"] and "8:44" in seen["user"] and "| 4.7 |" in seen["user"]
            assert "| 1200 | 2:45 | 31.5" in seen["user"], seen["user"]
            assert seen["max_tokens"] >= 10000      # room for all four sections
            assert c.post("/api/analytics/insights", json={}).status_code == 400
        finally:
            ya.REACH_PATH, ya.TOKEN_PATH, ya.DAILY_REACH_PATH = real
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert 'onclick="openAnalyticsModal()"' in html and "window.openAnalyticsModal = async function" in html
    assert "function drawRetention(box, points, drops, dur, avd)" in html
    assert "range: 'lifetime'" in html and '<option value="lifetime" selected>' in html and "function fewViews(v, text)" in html
    assert "function renderReachHelp(rc)" in html and "fetch('/api/analytics/daily-reach/start'" in html
    cont = open(os.path.join(os.path.dirname(APP), "scriptcraft-app-v3-container", "container_app.py"), encoding="utf-8").read()
    for view in ("status", "connect", "disconnect", "videos", "retention", "import_reach", "insights", "daily_reach_start"):
        assert f'"api_analytics_{view}",' in cont, view
    assert "feature_disabled_in_container" in html
    return "report + metadata + lifetime averages merged; impressions/CTR from daily reach reports (job, sync, newest report per day) or the Studio import; 3 steepest drops; routes guard input"


@check("Grok videos: an xAI credit / spending-limit refusal reads plainly and stops the batch; the script can be hand-edited and saved as a new cloud version")
def _():
    import queue
    import tempfile
    from pathlib import Path
    import grpc
    import xai_sdk
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415

    class _Rpc(grpc.RpcError):
        def __init__(self, code, details):
            self._c, self._d = code, details
        def code(self): return self._c
        def details(self): return self._d
        def __str__(self): return "<_InactiveRpcError of RPC that terminated with: …>"

    credits = _Rpc(grpc.StatusCode.PERMISSION_DENIED, "Your team abc has either used all available "
                   "credits or reached its monthly spending limit. To continue making API requests, …")
    text, fatal = web_gui._grok_error_text(credits)
    assert fatal and "console.x.ai" in text and "_InactiveRpcError" not in text, text
    assert web_gui._grok_error_text(_Rpc(grpc.StatusCode.UNAUTHENTICATED, "bad key"))[1] is True
    text, fatal = web_gui._grok_error_text(ValueError("Video did not respect moderation rules; URL is not available."))
    assert not fatal and "moderation" in text
    assert web_gui._grok_error_text(_Rpc(grpc.StatusCode.DEADLINE_EXCEEDED, "slow")) == ("DEADLINE_EXCEEDED: slow", False)

    calls = []

    class _Video:
        def generate(self, **kw):
            calls.append(kw["prompt"])
            if len(calls) > 1:
                raise credits
            return types.SimpleNamespace(url="https://x.invalid/v.mp4")

    class _Dl:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def raise_for_status(self): pass
        def iter_content(self, chunk_size=0): yield b"mp4"

    real = (xai_sdk.Client, web_gui.requests.get, web_gui._grok_get_output_dir,
            web_gui._upscale_video_to_1080p, web_gui._persist_grok_video)
    with tempfile.TemporaryDirectory() as td:
        xai_sdk.Client = lambda api_key=None: types.SimpleNamespace(video=_Video())
        web_gui.requests.get = lambda *a, **k: _Dl()
        web_gui._grok_get_output_dir = lambda title=None: Path(td)
        web_gui._upscale_video_to_1080p = lambda p: False
        web_gui._persist_grok_video = lambda *a: None
        sid = "offline-credits"
        web_gui.grok_video_streams[sid] = q = queue.Queue()
        try:
            rows = [{"description": f"scene {n}", "search_term": f"t{n}", "grok_prompt": f"cine {n}",
                     "grok_chalk_prompt": f"chalk {n}"} for n in range(3)]
            web_gui._grok_generate_worker(sid, rows, "k", "T", "")
        finally:
            (xai_sdk.Client, web_gui.requests.get, web_gui._grok_get_output_dir,
             web_gui._upscale_video_to_1080p, web_gui._persist_grok_video) = real
            web_gui.grok_video_streams.pop(sid, None)
    events = [q.get_nowait() for _ in range(q.qsize())]
    done = events[-1]
    assert len(calls) == 2, calls       # stopped at the refusal; 4 more clips never sent
    assert done["type"] == "done" and done["generated_count"] == 1 and done["failed_count"] == 1
    assert done["stopped_reason"] and "console.x.ai" in done["message"] and not done["cancelled"]
    failed = [e for e in events if e["type"] == "video_failed"]
    assert len(failed) == 1 and "_InactiveRpcError" not in failed[0]["message"]

    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert "if (payload.stopped_reason) {" in html
    assert 'onclick="startScriptEdit()"' in html and 'onclick="saveScriptEdit(true)"' in html
    assert "function saveScriptEdit(toCloud)" in html and "newCopy: false," in html
    assert "#mainScriptTab.script-editing h3 .script-hdr-btn" in html and "Undo last AI edit" not in html
    assert "_refreshMainScriptBadge();" in html and html.count("_openScriptChanged(") >= 5  # badge after polish/refine/edit/undo
    return "credit refusal → plain text + batch stops after 1 saved / 1 refused; editor saves a new version; badge refreshes after edits"


@check("Grok video delete: the file goes from its recorded broll folder and the blob from its own Script-ID; the gallery never redraws a deleted clip")
def _():
    import tempfile
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415

    class ResourceNotFoundError(Exception):
        pass

    class _CC:
        def __init__(self, fail=None):
            self.fail, self.deleted = fail, []
        def delete_blob(self, name):
            if self.fail:
                raise self.fail
            self.deleted.append(name)

    real = (web_gui._artifacts_enabled, web_gui._artifacts_container, web_gui._get_output_base_dir,
            os.environ.get("HOME"))
    c = web_gui.app.test_client()
    with tempfile.TemporaryDirectory() as home:
        os.environ["HOME"] = home
        old = Path(home) / "iCloud" / "AI Loser" / "broll"     # a previous output folder
        old.mkdir(parents=True)
        clip = old / "grok_20261030_180214_0_cinematic_stadium_scoreboard.mp4"
        stray = Path(home) / "notes" / "grok_x.mp4"
        stray.parent.mkdir()
        try:
            web_gui._get_output_base_dir = lambda: Path(home) / "Final" / "AI Loser"
            web_gui._artifacts_enabled = lambda: True
            cc = _CC()
            web_gui._artifacts_container = lambda: cc
            clip.write_bytes(b"mp4")
            r = c.post("/api/grok-videos/delete", json={"filename": clip.name, "path": str(clip),
                                                        "script_id": "ld-a6d792f14b"}).get_json()
            assert r["success"] and not clip.exists() and r["deleted"] == [str(clip.resolve())], r
            assert cc.deleted == [f"ld-a6d792f14b/videos/{clip.name}", f"ld-a6d792f14b/videos/{clip.name}.json"]
            stray.write_bytes(b"x")                              # not in a broll folder: left alone
            c.post("/api/grok-videos/delete", json={"filename": stray.name, "path": str(stray)})
            assert stray.exists()
            cc.fail = ResourceNotFoundError("The specified blob does not exist.")
            assert c.post("/api/grok-videos/delete", json={"filename": clip.name, "script_id": "ld-1"}).get_json()["success"]
            cc.fail = RuntimeError("AuthorizationFailure")
            r = c.post("/api/grok-videos/delete", json={"filename": clip.name, "script_id": "ld-1"})
            assert r.status_code == 502 and "come back on reload" in r.get_json()["error"]
        finally:
            (web_gui._artifacts_enabled, web_gui._artifacts_container, web_gui._get_output_base_dir) = real[:3]
            os.environ["HOME"] = real[3]

    src = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    assert '"local_path": str(local_path),' in src and '"local_path": meta.get("local_path", ""),' in src
    assert 'video_entry["script_id"] = _safe_blob_id(script_id)' in src
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert "grokVideos = _withoutDeletedGrok(grokVideos);" in html              # gallery
    assert "p.grokVideos = _withoutDeletedGrok(grokVideos);" in html            # live batch redraws
    assert "window.currentGrokVideos = _withoutDeletedGrok(list);" in html      # end-of-batch Azure refresh
    assert "window._deletedGrokVideos.add(filename);" in html and "script_id: entry.script_id ||" in html
    return "recorded path from an old output folder deleted, stray mp4 kept; blob under the clip's Script-ID; real blob errors → 502; deleted clips filtered from every redraw"



@check("B-roll Regenerate in the Process Script dialog + Execution Log; a refined/edited script is what later runs and redraws use (never the old copy)")
def _():
    import logging
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415
    import linedrive_azure.agents as agents  # noqa: PLC0415

    class _Agent:
        def generate_broll_table_with_timecodes(self, **kw):
            assert "Host:" in kw["script_content"] and kw["script_title"] == "AI Loser"
            return {"success": True, "table": "| Time | Term |\n|---|---|\n| 0:00 | stadium |",
                    "parsed_data": [{"term": "stadium"}]}

    seen = []
    class _H(logging.Handler):
        def emit(self, rec):
            seen.append(rec.getMessage())
    h = _H()
    web_gui.logger.addHandler(h)
    real = getattr(agents, "ScriptBRollAgentClient", None)
    agents.ScriptBRollAgentClient = _Agent
    try:
        d = web_gui.app.test_client().post("/api/broll/regenerate", json={
            "script": "Title: AI Loser\n\nHost: The scoreboard says it all.", "title": "AI Loser"}).get_json()
    finally:
        agents.ScriptBRollAgentClient = real
        web_gui.logger.removeHandler(h)
    assert d["success"] and "stadium" in d["broll_table"] and d["broll_rows"], d
    assert any(m.startswith("🔄 Regenerating B-roll table for 'AI Loser'") for m in seen), seen
    assert any(m.startswith("🔄 Regenerated B-roll table") for m in seen), seen

    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert 'id="spsBrollRegenBtn" onclick="regenerateBrollTable(true)"' in html          # dialog button
    assert 'data-sps-current="broll_table"' in html and "spsRefreshBrollInfo();\n      spsRenderStepper();" in html
    fn = html[html.index("async function regenerateBrollTable(fromDialog)"):html.index("function loadBrollTableFromFile()")]
    assert "addToDebugLog(" in fn and "addProgressMessage(" in fn                      # Execution Log / live log
    assert "🔄 Regenerating the B-roll table" in fn and "⏳ Still waiting on the B-roll agent" in fn
    assert "✅ B-roll table regenerated in " in fn and "❌ B-roll table regeneration failed after " in fn
    assert "window.currentResultPayload.brollTable = window._currentBrollTable;" in fn  # survives redraws
    assert "ta.value : (window.currentScript" in fn                                     # dialog's own script
    assert html.count("_openScriptChanged();") == 4                                      # polish, undo, refine, hand edit
    helper = html[html.index("function _openScriptChanged()"):html.index("function _updateScriptEditBadge()")]
    assert "window.currentResultPayload.mainScript = text;" in helper                    # redraws keep the refined script
    assert "ta.value = text;" in helper and "ta.value.trim() ===" not in helper           # Process Script runs on it too
    assert "if (window.currentResultPayload) window.currentResultPayload.mainScript = updated;" in html  # Title Picker
    return "endpoint logs start + result; dialog button, table-state line, Execution Log start/heartbeat/result, payload updated; Refine/Polish/edit/Undo/Title update the Process input + redraw payload"


@check("Refine never returns a cut-off script: long scripts are refined as exact edits; a max_tokens reply is refused (Refine + Polish)")
def _():
    os.environ.setdefault("PORT", "0")
    import json as _json
    import web_gui  # noqa: PLC0415

    blk = "[PRODUCTION BEGIN]\n[GROK IMAGINE / RESOLVE] a dark navy chart\n[PRODUCTION END]"
    body = "".join(f"## Chapter {i}\n\nHost: The Free Agents story keeps moving, part {i}.\n"
                   f"It’s a race for “developer attention” in round {i}.\n\n{blk}\n\n" for i in range(700))
    script = "Title: OpenAI Will Lose\n\n" + body + "Until next time."
    masked, blocks = web_gui._mask_production_blocks(script)
    assert len(masked) > web_gui._REFINE_WHOLE_MAX_CHARS and len(blocks) == 700

    # Edit application: unique, all, curly-quote/whitespace tolerant, ambiguous + placeholder refused.
    t, n, skipped = web_gui._apply_refine_edits(masked, [
        {"find": "Free Agents", "replace": "Developer Mindshare", "all": True},
        {"find": 'It\'s a race for "developer attention" in round 3.', "replace": "It's a race in round 3."},
        {"find": "Host:", "replace": "Narrator:"},                        # ambiguous: skipped
        {"find": "in", "replace": "XX", "all": True},                    # too short for all: skipped
        {"find": "[[PRODUCTION_BLOCK_0]]", "replace": ""},              # would drop a block: skipped
        {"find": "Until next time.", "replace": "See you next week."},
    ])
    assert n == 3 and len(skipped) == 3, (n, skipped)
    assert "Free Agents" not in t and t.count("Developer Mindshare") == 700
    assert "It's a race in round 3." in t and "round 3.\n" in t and "See you next week." in t
    assert web_gui._restore_production_blocks(t, blocks)[1] == []

    calls = []
    def fake(system, user, max_tokens=4000, **kw):
        calls.append((system, max_tokens, kw.get("require_complete")))
        return "Here you go:\n```json\n" + _json.dumps([
            {"find": "Free Agents", "replace": "Developer Mindshare", "all": True},
            {"find": "not in the script at all", "replace": "x"}]) + "\n```"
    real = web_gui._anthropic_complete
    web_gui._anthropic_complete = fake
    try:
        out, used, note = web_gui._refine_script(script, "Rename Free Agents to Developer Mindshare")
        assert out.endswith("Until next time.") and out.count(blk) == 700 and "Free Agents" not in out
        assert len(out) > len(script) - 2000 and "1 of 2 edits could not be matched" in note, note
        assert "JSON array of edits" in calls[0][0] and calls[0][1] == 16000 and calls[0][2] is True

        # A short script goes whole; a cut-off whole reply falls back to edits.
        short = "Title: T\n\nHost: Free Agents rule.\n\nUntil next time."
        seq = []
        def cut_then_edits(system, user, max_tokens=4000, **kw):
            seq.append(max_tokens)
            if max_tokens == 32000:
                raise web_gui.ClaudeReplyCutOff("cut")
            return '[{"find": "Free Agents rule.", "replace": "Developer Mindshare rules."}]'
        web_gui._anthropic_complete = cut_then_edits
        out, _, note = web_gui._refine_script(short, "rename")
        assert seq == [32000, 16000] and out == "Title: T\n\nHost: Developer Mindshare rules.\n\nUntil next time." and not note

        web_gui._anthropic_complete = lambda *a, **k: '[{"find": "nowhere", "replace": "x"}]'
        try:
            web_gui._refine_script(script, "rename"); raise AssertionError("expected refusal")
        except RuntimeError as e:
            assert "nothing was changed" in str(e)
    finally:
        web_gui._anthropic_complete = real

    # The helper refuses a max_tokens reply when asked to.
    class _Resp:
        stop_reason, usage = "max_tokens", None
        content = [type("B", (), {"type": "text", "text": "half a scri"})()]
    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                return _Resp()
    real_c = web_gui._get_anthropic_client
    web_gui._get_anthropic_client = lambda timeout=60.0: _Client()
    try:
        assert web_gui._anthropic_complete("s", "u", use_web_search=False) == "half a scri"
        try:
            web_gui._anthropic_complete("s", "u", use_web_search=False, max_tokens=32000, require_complete=True)
            raise AssertionError("expected ClaudeReplyCutOff")
        except web_gui.ClaudeReplyCutOff as e:
            assert "32,000-token reply limit" in str(e)
    finally:
        web_gui._get_anthropic_client = real_c
    src = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    assert src.count("require_complete=True") >= 2 and "except ClaudeReplyCutOff as e:" in src
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert "(data.note ? '<br>⚠️ '" in html
    return "700-chapter script refined by edits (blocks + ending intact, skipped edit reported); short script cut off → edits; no placeable edit → unchanged; max_tokens reply refused"


@check("ElevenLabs Audio: the HeyGen script is read in stitched parts at the chosen similarity and saved as one MP3; the key is saved and masked like the others and never reaches the page")
def _():
    import json as _json
    import shutil
    import subprocess
    import tempfile
    import threading as _thr
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415

    # Parts: paragraph breaks first, sentences inside a long paragraph, never over the limit, nothing dropped.
    long_para = " ".join(f"Sentence number {i} is here." for i in range(400))
    text = "Short opening.\n\n" + long_para + "\n\nClosing line."
    parts = web_gui._eleven_chunks(text, 3000)
    assert len(parts) >= 4 and all(len(p) <= 3000 for p in parts), [len(p) for p in parts]
    assert " ".join(" ".join(parts).split()) == " ".join(text.split()) and parts[0].startswith("Short opening.")
    assert [len(p) for p in web_gui._eleven_chunks("x" * 7000, 3000)] == [3000, 3000, 1000]

    # Text: the page's HeyGen text, else the script's HEYGEN READY section, else extracted like the HeyGen stage.
    assert web_gui._eleven_script_text({"text": " Hi. ", "script": "ignored"}) == ("Hi.", "HeyGen script")
    assembled = "Title: T\n\nHost: Not this.\n\n# 🎬 HEYGEN READY SCRIPT\n" + "=" * 80 + "\n\nHello there.\n\nSecond paragraph."
    assert web_gui._eleven_script_text({"script": assembled}) == ("Hello there.\n\nSecond paragraph.", "HeyGen script")
    t, src = web_gui._eleven_script_text({"script": _WORD_COUNT_SAMPLE})
    assert "One two three" in t and "GROK IMAGINE" not in t and "Confirm the price" not in t, t
    assert src.startswith("HeyGen text extracted")

    have_ff = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        if have_ff:   # a real 1-second MP3 at the format ElevenLabs returns
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                            "-ar", "44100", "-b:a", "128k", str(d / "s.mp3")], check=True)
            mp3 = (d / "s.mp3").read_bytes()
        else:
            mp3 = b"\xff\xfb\x90\x00" + b"\x00" * 400
        key = "sk_test_eleven_ABCD1234"
        posts, gets, mode = [], [], {"fail_once": True, "quota": False}

        class _R:
            def __init__(self, status, content=b"", body=None, headers=None):
                self.status_code, self.content, self._b, self.headers = status, content, body, headers or {}
                self.text = _json.dumps(body) if body is not None else ""
            def json(self):
                return self._b

        def fake_get(url, params=None, headers=None, timeout=None):
            gets.append((url, dict(params or {}), dict(headers or {})))
            if url.endswith("/v2/voices"):
                if not (params or {}).get("next_page_token"):
                    return _R(200, body={"voices": [{"voice_id": "premade0001", "name": "Adam", "category": "premade",
                                                     "labels": {"gender": "male"}, "preview_url": "https://x/a.mp3"}],
                                         "has_more": True, "next_page_token": "p2"})
                return _R(200, body={"voices": [{"voice_id": "voiceABC123", "name": "Roz Clone", "category": "cloned",
                                                 "labels": {"accent": "american"}, "preview_url": ""}],
                                     "has_more": False, "next_page_token": None})
            if url.endswith("/v1/user/subscription"):
                return _R(200, body={"character_limit": 100000, "character_count": 99000, "tier": "creator"})
            if url.endswith("/v1/voices/voiceABC123/settings"):   # the voice's saved settings
                return _R(200, body={"stability": 0.4, "similarity_boost": 0.3, "style": 0.1,
                                     "use_speaker_boost": True, "speed": 1.05, "clone_strength": None})
            return _R(404, body={"detail": "nope"})

        def fake_post(url, params=None, headers=None, json=None, timeout=None):
            posts.append((url, dict(params or {}), dict(headers or {}), dict(json or {})))
            if mode["quota"]:
                return _R(401, body={"detail": {"status": "quota_exceeded", "message": f"You have 5 credits left ({key})."}})
            if mode["fail_once"] and len(posts) == 2:
                mode["fail_once"] = False
                return _R(503, body={"detail": {"status": "system_busy", "message": "busy"}})
            return _R(200, content=mp3, headers={"request-id": f"req{len(posts)}"})

        def wait_job(client, job_id):
            for _ in range(400):
                s = client.get(f"/api/elevenlabs/tts/{job_id}").get_json()
                if s.get("status") != "running":
                    return s
                _thr.Event().wait(0.05)
            raise AssertionError("ElevenLabs job never finished")

        keep = (web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui._get_run_output_dir, web_gui.requests.get,
                web_gui.requests.post, web_gui.time.sleep, os.environ.get("ELEVENLABS_API_KEY"))
        try:
            settings = d / "settings.json"
            settings.write_text("{}")
            web_gui.SCRIPTCRAFT_SETTINGS_PATH = settings
            web_gui._get_run_output_dir = lambda title, create=True: d / "out"
            web_gui.requests.get, web_gui.requests.post = fake_get, fake_post
            web_gui.time.sleep = lambda s: None
            os.environ.pop("ELEVENLABS_API_KEY", None)
            c = web_gui.app.test_client()

            r = c.get("/api/elevenlabs/voices")
            assert r.status_code == 400 and r.get_json()["needs_key"], r.get_json()
            assert c.post("/api/elevenlabs/tts", json={"text": "Hi.", "voice_id": "voiceABC123"}).get_json()["needs_key"]

            # The key: saved in the dialog, masked on the way back, hydrated at startup.
            assert c.post("/api/keys", json={"elevenlabs_api_key": key}).get_json()["updated"] == ["elevenlabs_api_key"]
            k = c.get("/api/keys")
            kj = k.get_json()
            assert kj["keys"]["elevenlabs_api_key"] == "•" * 4 + "1234" and kj["sources"]["elevenlabs_api_key"] == "saved"
            assert key not in k.get_data(as_text=True)
            os.environ.pop("ELEVENLABS_API_KEY", None)
            web_gui._hydrate_env_from_settings()
            assert os.environ.get("ELEVENLABS_API_KEY") == key

            v = c.get("/api/elevenlabs/voices")
            vj = v.get_json()
            assert vj["success"] and [x["name"] for x in vj["voices"]] == ["Roz Clone", "Adam"], vj
            assert vj["balance"]["remaining"] == 1000 and vj["model_id"] == "eleven_v4" and key not in v.get_data(as_text=True)
            assert vj["similarity"] == 0.75                                    # default before any run
            assert all(h.get("xi-api-key") == key for _, _, h in gets) and gets[1][1]["next_page_token"] == "p2"

            p = c.post("/api/elevenlabs/prepare", json={"script": assembled}).get_json()
            assert p["text"] == "Hello there.\n\nSecond paragraph." and p["parts"] == 1 and p["words"] == 4

            assert c.post("/api/elevenlabs/tts", json={"text": "Hi.", "voice_id": "../x"}).status_code == 400
            assert c.post("/api/elevenlabs/tts", json={"text": "Hi.", "voice_id": "voiceABC123", "model_id": "nope"}).status_code == 400
            assert c.post("/api/elevenlabs/tts", json={"text": "Hi.", "voice_id": "voiceABC123", "similarity": 1.5}).status_code == 400

            r = c.post("/api/elevenlabs/tts", json={"text": text, "voice_id": "voiceABC123", "voice_name": "Roz Clone",
                                                    "model_id": "eleven_v4", "similarity": 0.75, "clone_strength": 0.5,
                                                    "title": "My Test Title"}).get_json()
            assert r["success"] and r["parts"] == len(parts), r
            s = wait_job(c, r["job_id"])
            assert s["status"] == "done" and s["done"] == len(parts), s
            tts = [b for u, prm, h, b in posts]
            assert len(posts) == len(parts) + 1                                   # one busy reply retried
            assert all(prm["output_format"] == "mp3_44100_128" and h["xi-api-key"] == key for _, prm, h, _ in posts)
            assert posts[0][0].endswith("/v1/text-to-speech/voiceABC123") and tts[0]["model_id"] == "eleven_v4"
            assert "previous_request_ids" not in tts[0] and tts[-1]["previous_request_ids"] == [f"req{len(posts) - i}" for i in (3, 2, 1)]
            # Similarity 75%; the voice's other saved settings sent unchanged (a null clone_strength left out).
            assert all(b["voice_settings"] == {"stability": 0.4, "similarity_boost": 0.75, "style": 0.1,
                                               "use_speaker_boost": True, "speed": 1.05, "clone_strength": 0.5}
                       for b in tts), tts[0]
            out = Path(s["path"])
            assert out.parent == d / "out" / "voiceover" and out.name.startswith("My_Test_Title_elevenlabs_Roz_Clone_")
            if have_ff:
                dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                            str(out)], capture_output=True, text=True).stdout.strip())
                assert abs(dur - len(parts)) < 0.5, dur                        # one clean file, every part in it
            saved = _json.loads(settings.read_text())
            assert saved["elevenlabs_voice_id"] == "voiceABC123" and saved["elevenlabs_model_id"] == "eleven_v4"
            assert saved["elevenlabs_similarity"] == 0.75 and c.get("/api/elevenlabs/voices").get_json()["similarity"] == 0.75
            assert saved["elevenlabs_clone_strength"] == 0.5 and c.get("/api/elevenlabs/voices").get_json()["clone_strength"] == 0.5
            # Clone Strength is Eleven v4 only: another model keeps the voice's saved settings.
            n0 = len(posts)
            r2 = c.post("/api/elevenlabs/tts", json={"text": "Hi.", "voice_id": "voiceABC123", "model_id": "eleven_multilingual_v2",
                                                     "clone_strength": 0.9}).get_json()
            assert wait_job(c, r2["job_id"])["status"] == "done" and "clone_strength" not in posts[n0][3]["voice_settings"]
            assert c.post("/api/elevenlabs/tts", json={"text": "Hi.", "voice_id": "voiceABC123", "clone_strength": 2}).status_code == 400
            a = c.get(f"/api/elevenlabs/audio/{r['job_id']}?download=1")
            assert a.status_code == 200 and a.mimetype == "audio/mpeg" and "attachment" in a.headers["Content-Disposition"]
            a.close()

            mode["quota"] = True
            r = c.post("/api/elevenlabs/tts", json={"text": "Hi.", "voice_id": "voiceABC123"}).get_json()
            s = wait_job(c, r["job_id"])
            assert s["status"] == "error" and "enough credits" in s["error"] and key not in s["error"], s
        finally:
            (web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui._get_run_output_dir, web_gui.requests.get,
             web_gui.requests.post, web_gui.time.sleep, env) = keep
            if env is None:
                os.environ.pop("ELEVENLABS_API_KEY", None)
            else:
                os.environ["ELEVENLABS_API_KEY"] = env

    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert 'id="modalElevenlabsApiKey"' in html and "setSrc('src_elevenlabs', srcMap.elevenlabs_api_key);" in html
    assert html.count("['modalElevenlabsApiKey','elevenlabs_api_key']") == 2 and html.count('onclick="openElevenLabsModal()"') == 2
    assert 'id="elevenLabsModal"' in html and "async function startElevenLabsAudio()" in html
    assert 'id="elSimilarity"' in html and "similarity: similarity," in html
    assert 'id="elCloneStrength"' in html and "clone_strength: cloneStrength" in html and "function _elToggleClone()" in html
    return (f"{len(parts)} stitched parts (last 3 request IDs passed), similarity 75% + clone strength (v4 only) with the voice's other settings kept, busy reply retried, one MP3"
            + (" checked with ffprobe" if have_ff else "") + "; key masked + hydrated; own voices first; quota error plain, key redacted")

@check("ElevenLabs Audio: the volume is evened out when the parts are joined (a part that fades and a louder next part end at one level), set to -18 LUFS, peak-limited; the parts are still joined if leveling fails")
def _():
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415

    # Gains: each part's speech brought to the voiceover's level; a part never looks into the next.
    g = web_gui._eleven_level_gains([[-30.0] * 300, [-40.0] * 300])
    assert len(g[0]) == len(g[1]) == 300 and abs((g[1][0] - g[0][-1]) - 10.0) < 0.01, (g[0][-1], g[1][0])
    fade = [-30.0 - 8.0 * i / 1200 for i in range(1200)]          # 2 min fading 8 dB
    gf = web_gui._eleven_level_gains([fade])[0]
    assert gf[-1] - gf[0] > 6.0 and all(b >= a - 1e-9 for a, b in zip(gf, gf[1:])), (gf[0], gf[-1])
    assert web_gui._loudness_swing(fade) > 6.0 and web_gui._loudness_swing([m + x for m, x in zip(fade, gf)]) < 1.5
    assert abs(web_gui._loudness_integrated([-23.0] * 100) + 23.0) < 0.01 and web_gui._loudness_integrated([-120.0] * 5) == -70.0

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        return "gain curve only (no ffmpeg here)"
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        parts = []
        # Part 1 fades 8 dB over 60 s, part 2 is steady and as loud as part 1's start (ElevenLabs' pattern).
        for name, vol in (("a", "pow(10,-8*t/60/20)"), ("b", "1")):
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            "anoisesrc=color=pink:amplitude=0.05:duration=" + ("60" if name == "a" else "30"),
                            "-af", f"volume='{vol}':eval=frame", "-ar", "44100", "-ac", "1", "-b:a", "128k",
                            str(d / f"{name}.mp3")], check=True)
            parts.append((d / f"{name}.mp3").read_bytes())
        out = d / "out" / "vo.mp3"
        level = web_gui._eleven_join_mp3(parts, out)
        assert level and level["swing_before"] > 5 and level["swing_after"] < 2, level
        assert abs(level["after"] - web_gui.ELEVEN_TARGET_LUFS) <= 1.0, level
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=channels,sample_rate,bit_rate",
                                "-of", "default=nw=1", str(out)], capture_output=True, text=True).stdout
        dur = float(re.search(r"duration=([\d.]+)", probe).group(1))
        assert abs(dur - 90) < 0.3 and "channels=1" in probe and "sample_rate=44100" in probe and "bit_rate=192000" in probe, probe
        pk = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(out), "-af", "ebur128=peak=true", "-f", "null", "-"],
                            capture_output=True, text=True).stderr
        tp = float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", pk)[-1])
        assert tp <= -1.5, tp

        # Leveling fails: the parts are still joined, nothing lost.
        keep = web_gui._eleven_level
        try:
            web_gui._eleven_level = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
            out2 = d / "out" / "vo2.mp3"
            assert web_gui._eleven_join_mp3(parts, out2) is None and out2.stat().st_size > 0
        finally:
            web_gui._eleven_level = keep

    src = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    assert "level = _eleven_join_mp3(parts, out_path)" in src and "leveled=level," in src
    assert "seconds = int(round(_audio_seconds(out_path)))" in src
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert "const lv = s.leveled;" in html and "'Volume evened out: '" in html
    return (f"fade {level['swing_before']} → {level['swing_after']} dB, {level['before']} → {level['after']} LUFS, "
            f"true peak {tp} dBFS, 192 kbps mono, {dur:.2f}s; plain join when leveling fails")


@check("ElevenLabs Audio → Fix a section: picked sentences are re-read (with the sentences around them as context) and put back at the same length and loudness; keep or try again, undo, and Explainers made from the MP3 get the new narration")
def _():
    import json as _json
    import math
    import shutil
    import struct
    import subprocess
    import tempfile
    import wave
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415
    import explainer_video as xv  # noqa: PLC0415
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        return "skipped: no ffmpeg"
    SR = 44100

    def tones(path, segs, total):
        """A mono WAV of tone bursts [(start, end, freq, amp)] in silence."""
        n = int(total * SR)
        buf = [0.0] * n
        for s, e, f, a in segs:
            i0, i1 = int(s * SR), min(n, int(e * SR))
            ramp = int(0.01 * SR)
            for i in range(i0, i1):
                g = min(1.0, (i - i0) / ramp, (i1 - i) / ramp)
                buf[i] += a * g * math.sin(2 * math.pi * f * (i - i0) / SR)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, v)) * 32767)) for v in buf))

    def to_mp3(wav, mp3, rate="192k"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ar", "44100", "-ac", "1",
                        "-c:a", "libmp3lame", "-b:a", rate, str(mp3)], check=True)

    def pcm(path):
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                           capture_output=True, check=True)
        return struct.unpack(f"<{len(r.stdout) // 2}h", r.stdout)

    def power(x, t, f, win=0.1):
        """Goertzel power of frequency f in a window starting at t."""
        i0 = int(t * SR)
        k = 2 * math.cos(2 * math.pi * f / SR)
        s1 = s2 = 0.0
        for v in x[i0:i0 + int(win * SR)]:
            s1, s2 = v + k * s1 - s2, s1
        return s1 * s1 + s2 * s2 - k * s1 * s2

    # The old reading: 6 sentences of two 0.5 s "words" at 440 Hz.
    words, segs, t = [], [], 0.3
    for k in range(6):
        for j, txt in enumerate((f"Word{k}a", f"word{k}b.")):
            words.append({"text": txt, "start": round(t, 3), "end": round(t + 0.5, 3)})
            segs.append((t, t + 0.5, 440, 0.3))
            t += 0.5 + (0.15 if j == 0 else 0.7)
    total = round(t + 0.5, 3)
    sents = web_gui._eleven_sentences(words)
    assert [s["text"] for s in sents][:2] == ["Word0a word0b.", "Word1a word1b."] and len(sents) == 6, sents
    assert [(s["w0"], s["w1"]) for s in sents][2] == (4, 6)
    title, pid = "Fix Test", "20261122_120000_0abc"
    posts, mode = [], {"long": False, "reject_context": False}

    class _R:
        def __init__(self, status, content=b"", body=None):
            self.status_code, self.content, self._b, self.headers = status, content, body, {}
            self.text = _json.dumps(body) if body is not None else ""

        def json(self):
            return self._b

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        vo = d / "out" / "voiceover"
        vo.mkdir(parents=True)
        tones(d / "old.wav", segs, total)
        name = "Fix_Test_elevenlabs_Roz_20261122_100000.mp3"
        mp3 = vo / name
        to_mp3(d / "old.wav", mp3)
        original = mp3.read_bytes()
        mp3.with_suffix(".txt").write_text(" ".join(w["text"] for w in words), encoding="utf-8")
        mp3.with_name(mp3.stem + ".voice.json").write_text(_json.dumps(
            {"voice_id": "voiceABC123", "model_id": "eleven_v4", "similarity": 0.8, "clone_strength": 0.6}))
        dur = web_gui._audio_seconds(mp3)
        # An Explainer made from this MP3: its word timings, and two presenter clips (one overlaps sentences 2-3).
        pdir = d / "out" / "explainer" / pid
        pdir.mkdir(parents=True)
        # Forced alignment can time a sentence's first word late: the fix must start where the sound starts.
        timed = [dict(w) for w in words]
        timed[4]["start"] = round(timed[4]["start"] + 0.25, 3)
        (pdir / "words.json").write_text(_json.dumps(timed))
        s0, e1 = words[4]["start"], words[7]["end"]
        (pdir / "project.json").write_text(_json.dumps({
            "title": title, "voiceover": name, "audio_seconds": dur, "timing": {"source": "elevenlabs"},
            "host": {"parts": [{"file": "/x/c1.mp4", "orig": "/x/clip_01.mp4", "offset": 0.1, "seconds": 1.0},
                               {"file": "/x/c2.mp4", "orig": "/x/clip_02.mp4", "offset": s0 - 1.0, "seconds": 2.0}]}}))

        def fake_post(url, params=None, headers=None, json=None, timeout=None, **kw):
            body = dict(json or {})
            posts.append((url, body))
            if mode["reject_context"] and "previous_text" in body:
                return _R(422, body={"detail": {"status": "invalid_request",
                                                "message": "previous_text is not supported with this model"}})
            n = len(body["text"].split())
            wl, gap_in, gap_s = (1.0, 0.3, 1.4) if mode["long"] else (0.55, 0.165, 0.77)
            take, tt = [], 0.25
            for i in range(n):
                take.append((tt, tt + wl, 660, 0.3 * 10 ** (-8 / 20)))
                tt += wl + (gap_in if i % 2 == 0 else gap_s)
            tt = tt - gap_s + 0.4
            tones(d / "take.wav", take, tt)
            to_mp3(d / "take.wav", d / "take.mp3", "128k")
            return _R(200, content=(d / "take.mp3").read_bytes())

        keep = (web_gui._get_run_output_dir, web_gui.requests.post, web_gui._eleven_key, web_gui._eleven_voice_settings,
                web_gui.time.sleep)
        try:
            web_gui._get_run_output_dir = lambda title_, create=True: d / "out"
            web_gui.requests.post = fake_post
            web_gui._eleven_key = lambda: "sk_test_fix_9876"
            web_gui._eleven_voice_settings = lambda key, vid, sim, cs=None: {"stability": 0.4, "similarity_boost": sim,
                                                                            **({"clone_strength": cs} if cs is not None else {})}
            web_gui.time.sleep = lambda s: None
            c = web_gui.app.test_client()

            f = c.get("/api/elevenlabs/fix/files?title=" + title).get_json()
            assert f["success"] and [(x["name"], x["has_text"], x["fixes"]) for x in f["files"]] == [(name, True, 0)], f
            for bad in ("../x.mp3", "nope.mp3", "notes.txt", ""):
                assert c.post("/api/elevenlabs/fix/load", json={"title": title, "file": bad}).status_code == 400, bad

            # Load: word times come from the Explainer made from this MP3 (no alignment call), then are kept next to it.
            ld = c.post("/api/elevenlabs/fix/load", json={"title": title, "file": name}).get_json()
            assert ld["success"] and ld["timing"] == "explainer" and len(ld["sentences"]) == 6 and not posts, ld
            assert ld["voice"]["voice_id"] == "voiceABC123" and ld["explainers"] == [pid] and ld["history"] == []
            assert mp3.with_name(mp3.stem + ".words.json").is_file()
            assert c.post("/api/elevenlabs/fix/load", json={"title": title, "file": name}).get_json()["timing"] == "explainer"

            req = {"title": title, "file": name, "first": 2, "last": 3, "voice_id": "voiceABC123", "model_id": "eleven_v4",
                   "similarity": 0.8, "clone_strength": 0.6}
            assert c.post("/api/elevenlabs/fix/take", json={**req, "first": 4, "last": 9}).status_code == 400
            assert c.post("/api/elevenlabs/fix/take", json={**req, "voice_id": "../x"}).status_code == 400

            # A take: only the picked sentences are read, with two sentences each side as context.
            tk = c.post("/api/elevenlabs/fix/take", json=req).get_json()
            assert tk["success"], tk
            url, body = posts[-1]
            assert url.endswith("/v1/text-to-speech/voiceABC123") and body["text"] == "Word2a word2b. Word3a word3b."
            assert body["previous_text"] == "Word0a word0b. Word1a word1b." and body["next_text"] == "Word4a word4b. Word5a word5b."
            assert body["model_id"] == "eleven_v4" and body["voice_settings"]["clone_strength"] == 0.6
            assert "previous_request_ids" not in body and tk["chars"] == len(body["text"])
            assert 1.04 < tk["ratio"] < 1.15 and 6.0 < tk["gain_db"] < 10.0, tk
            assert tk["start"] < s0 and tk["end"] > e1 and tk["start"] > words[3]["end"] and tk["end"] < words[8]["start"], tk
            folder = vo / "fixes" / mp3.stem
            cand = folder / f"take_{tk['take']}.mp3"
            assert mp3.read_bytes() == original and cand.is_file()          # nothing changes until it is kept
            for part in ("before", "after"):
                r = c.get(tk[part])
                assert r.status_code == 200 and r.mimetype == "audio/mpeg" and len(r.data) > 1000, part
            assert c.get(tk["before"].replace("part=before", "part=../x")).status_code == 404

            # Same length; the old reading outside the section; the new one (660 Hz) in its place at the old loudness.
            a, b = pcm(mp3), pcm(cand)
            assert abs(len(a) - len(b)) / SR < 0.03, (len(a), len(b))
            for tw in (words[2]["start"] + 0.2, words[9]["start"] + 0.2, words[10]["start"] + 0.2):
                assert power(b, tw, 440) > 20 * power(b, tw, 660), tw
            for tw in (s0 + 0.05, words[6]["start"] + 0.15):
                assert power(b, tw, 660) > 20 * power(b, tw, 440) and power(a, tw, 440) > 20 * power(a, tw, 660), tw
            assert power(b, (words[5]["end"] + words[6]["start"]) / 2, 660) < power(b, s0 + 0.15, 660) / 50
            old_l = web_gui._eleven_fix_lufs(mp3, s0, e1)
            new_l = web_gui._eleven_fix_lufs(cand, s0, e1)
            assert abs(old_l - new_l) < 1.5, (old_l, new_l)

            # Too long to fit in its place: refused with a plain message; the old take is replaced only by a new one.
            mode["long"] = True
            r = c.post("/api/elevenlabs/fix/take", json=req)
            assert r.status_code == 400 and "too much to fit" in r.get_json()["error"], r.get_json()
            mode["long"] = False
            # A model that takes no surrounding text: read again without it.
            mode["reject_context"] = True
            n0 = len(posts)
            tk = c.post("/api/elevenlabs/fix/take", json=req).get_json()
            assert tk["success"] and len(posts) == n0 + 2 and "previous_text" not in posts[-1][1], tk
            mode["reject_context"] = False
            assert len(list(folder.glob("take_*.mp3"))) == 4             # only the newest take: mix, raw, before, after

            # An Explainer job running on this MP3: the fix waits.
            xv._job_set(pid, status="running")
            try:
                r = c.post("/api/elevenlabs/fix/apply", json={"title": title, "file": name, "take": tk["take"]})
                assert r.status_code == 409 and "Explainer" in r.get_json()["error"]
            finally:
                xv._job_set(pid, status="done")

            # Keep it: the MP3 gets the take, the old one is kept, the Explainer gets the new narration.
            cand_bytes = (folder / f"take_{tk['take']}.mp3").read_bytes()
            ap = c.post("/api/elevenlabs/fix/apply", json={"title": title, "file": name, "take": tk["take"]}).get_json()
            assert ap["success"] and ap["n"] == 1 and ap["explainers"] == [pid], ap
            assert mp3.read_bytes() == cand_bytes and (folder / "before_fix_01.mp3").read_bytes() == original
            assert [c_["n"] for c_ in ap["clips"]] == [2] and ap["clips"][0]["name"] == "clip_02.mp4", ap["clips"]
            assert [h["first"] for h in ap["history"]] == [2] and not list(folder.glob("take_*"))
            assert (pdir / "narration.wav").is_file() and (pdir / "narration.m4a").is_file()
            pj = _json.loads((pdir / "project.json").read_text())
            assert pj["loudness"]["target_lufs"] == -14.0 and abs(xv.media_seconds(pdir / "narration.wav") - dur) < 0.05
            assert c.post("/api/elevenlabs/fix/apply", json={"title": title, "file": name, "take": tk["take"]}).status_code == 404
            f = c.get("/api/elevenlabs/fix/files?title=" + title).get_json()
            assert f["files"][0]["fixes"] == 1
            assert c.post("/api/elevenlabs/fix/load", json={"title": title, "file": name}).get_json()["history"][0]["n"] == 1

            # A take made before the MP3 changed can't be kept.
            tk2 = c.post("/api/elevenlabs/fix/take", json={**req, "first": 0, "last": 0}).get_json()
            assert tk2["success"] and tk2["start"] == 0.0, tk2
            os.utime(mp3, (1_700_000_000, 1_700_000_000))
            assert c.post("/api/elevenlabs/fix/apply", json={"title": title, "file": name, "take": tk2["take"]}).status_code == 409

            # Undo: the MP3 from before the fix, and the Explainer narration made from it again.
            un = c.post("/api/elevenlabs/fix/undo", json={"title": title, "file": name}).get_json()
            assert un["success"] and un["undone"] == 1 and un["history"] == [] and un["explainers"] == [pid], un
            assert mp3.read_bytes() == original and not (folder / "before_fix_01.mp3").exists()
            assert c.post("/api/elevenlabs/fix/undo", json={"title": title, "file": name}).status_code == 400
        finally:
            (web_gui._get_run_output_dir, web_gui.requests.post, web_gui._eleven_key, web_gui._eleven_voice_settings,
             web_gui.time.sleep) = keep
            with xv._PROJECTS_LOCK:
                xv._PROJECTS.pop(str(pdir.resolve()), None)

    import inspect  # noqa: PLC0415
    assert ".voice.json" in inspect.getsource(web_gui._eleven_run)          # new voiceovers record their voice
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    for s_ in ('id="elFixWrap"', "async function elFixTake(", "/api/elevenlabs/fix/apply", "/api/elevenlabs/fix/undo",
               "function _elFixDoneText(", "Make HeyGen clips"):
        assert s_ in html, s_
    return ("sentences from word times; take = picked sentences + context (fallback without), fitted ~x1.09 and +8 dB "
            "to the old loudness at the same length, 660 Hz only in its place; too long refused; kept with a backup, "
            "Explainer narration redone and the overlapping presenter clip named; stale take and running job refused; undo")


@check("Explainer clips: upload your own video (a recorded demo) next to YouTube downloads, use the whole of it or cut a part, and frame a clip in the right or left half (or full screen)")
def _():
    import io as _io
    import json as _json
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        return "skipped: no ffmpeg"
    title, pid = "Demo Talk", "20261122_150000_0d0d"
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        proj = d / "out" / "explainer" / pid
        proj.mkdir(parents=True)
        (proj / "project.json").write_text(_json.dumps({"title": title}))
        demo = d / "demo.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x800:rate=30:duration=2",
                        "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-shortest", str(demo)], check=True)
        keep = web_gui._get_run_output_dir
        try:
            web_gui._get_run_output_dir = lambda t, create=True: d / "out"
            c = web_gui.app.test_client()

            def up(name, data):
                return c.post(f"/api/explainer/{pid}/video", data={"title": title, "file": (_io.BytesIO(data), name)},
                              content_type="multipart/form-data")
            assert up("notes.txt", b"hello").status_code == 400
            r = up("broken.mp4", b"not really a video")
            assert r.status_code == 400 and "Can't read broken.mp4" in r.get_json()["error"], r.get_json()
            r = up("My screen demo.mp4", demo.read_bytes())
            j = r.get_json()
            assert r.status_code == 200 and j["success"], j
            v = next(x for x in j["youtube"]["videos"] if x["id"] == j["video"])
            assert v["source"] == "upload" and v["title"] == "My screen demo.mp4" and abs(v["seconds"] - 2) < 0.1, v
            assert (v["width"], v["height"]) == (1280, 800) and v["has_audio"] and v["ready"], v
            media = proj / "working" / "media"
            assert sorted(p.name for p in media.iterdir()) == [f"{v['id']}.mp4"], list(media.iterdir())   # no .part left over

            # The whole video as one clip; framed on the right by default; left, full screen.
            r = c.post(f"/api/explainer/{pid}/youtube", json={"title": title, "action": "clip", "video": v["id"],
                                                                "start": "0", "end": f"{v['seconds']:.2f}", "label": "demo"}).get_json()
            assert r["success"], r
            clip = r["youtube"]["clips"][0]
            assert clip["place"] == "right" and abs(clip["seconds"] - v["seconds"]) < 0.05 and clip["has_audio"], clip
            r = c.post(f"/api/explainer/{pid}/youtube", json={"title": title, "action": "place", "id": clip["id"], "place": "left"}).get_json()
            assert r["success"] and r["youtube"]["clips"][0]["place"] == "left"
            bad = c.post(f"/api/explainer/{pid}/youtube", json={"title": title, "action": "place", "id": clip["id"], "place": "top"})
            assert bad.status_code == 400
            r = c.post(f"/api/explainer/{pid}/youtube", json={"title": title, "action": "remove_video", "id": v["id"]}).get_json()
            assert r["success"] and not r["youtube"]["videos"] and not r["youtube"]["clips"] and not list(media.iterdir())
        finally:
            web_gui._get_run_output_dir = keep
            import explainer_video as _xvm  # noqa: PLC0415
            with _xvm._PROJECTS_LOCK:
                _xvm._PROJECTS.pop(str(proj.resolve()), None)
    return "upload read by ffprobe (1280x800, 2 s, audio), bad files refused with nothing left behind; whole-video clip framed right, then left; removal deletes the files"


@check("Explainer: Regenerate test clip makes a new plan and slides in the same project (same or new stretch); logos, values and clips stay, a clip moves to the slide at the same moment")
def _():
    import json as _json
    import tempfile
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415
    import explainer_video as xv  # noqa: PLC0415
    title, pid = "Regen Talk", "20261122_160000_0e0e"
    sentences = [f"Sentence number {i} says something useful here." for i in range(40)]
    words, t = [], 0.0
    for sent in sentences:
        for w in sent.split():
            words.append({"text": w, "start": round(t, 2), "end": round(t + 0.3, 2)})
            t += 0.35
        t += 0.4
    total = round(t, 2)
    sec = lambda i, extra="": (f'<section id="s{i:02d}" data-at="Sentence number {i} says" data-kind="slide"{extra}>'  # noqa: E731
                               f'<h1 class="h1">Slide {i}</h1></section>')
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        proj = d / "out" / "explainer" / pid
        (proj / "versions").mkdir(parents=True)
        (proj / "working" / "media").mkdir(parents=True)
        (proj / "working" / "media" / "yc_a.mp4").write_bytes(b"x")
        (proj / "words.json").write_text(_json.dumps(words))
        (proj / "versions" / "v001.html").write_text("\n\n".join(sec(i) for i in (0, 2, 4)))
        clip = {"id": "yc_a", "video": "yt_v", "file": "working/media/yc_a.mp4", "start": 0, "end": 3, "seconds": 3,
                "status": "ready", "slide": "s02", "place": "right", "audio": "mute"}
        (proj / "project.json").write_text(_json.dumps({
            "title": title, "audio_seconds": total, "current": 1, "span": [0.0, 30.0],
            "versions": [{"n": 1, "kind": "build", "note": "", "slides": 3}],
            "logos": {"acme": {"name": "Acme", "file": "acme.png", "source": "acme.png", "recolor": "auto"}},
            "values": {"peak": {"status": "confirmed", "value": "10%"}},
            "youtube": {"videos": [{"id": "yt_v", "status": "ready", "file": "working/media/v.mp4"}], "clips": [clip]}}))
        p = xv.open_project(proj)
        m2 = {m["id"]: m for m in p.compile()["slides"]}["s02"]
        mid = (m2["t0"] + m2["t1"]) / 2
        calls = []
        keep = (xv.plan_video, xv.build_slides, web_gui._get_run_output_dir, web_gui._get_anthropic_client, xv.regenerate_test)
        try:
            xv.plan_video = lambda proj_, client, cancel, status, log: calls.append(("plan", proj_.span())) or {}
            # The new take: other slide ids, one of which starts just before the clip's moment.
            xv.build_slides = lambda proj_, client, cancel, status, log, feedback="", kind="build": (
                calls.append(("build", feedback)) or [{"id": i, "raw": sec(int(i[1:]))} for i in ("s00", "s01", "s03")])
            r = xv.regenerate_test(p, object(), None, lambda *a, **k: None, lambda *a, **k: None, start=0, minutes=0.6,
                                   notes="More charts")
            assert r["version"] == 2 and p.data["current"] == 2 and calls == [("plan", p.span()), ("build", "More charts")], calls
            assert p.span()[0] == 0 and 30 < p.span()[1] < 42, p.span()
            assert p.data["versions"][-1]["note"].startswith("Test clip regenerated, 0:00–") and "More charts" in p.data["notes"]
            assert p.data["logos"]["acme"]["file"] == "acme.png" and p.data["values"]["peak"]["value"] == "10%"
            new = {m["id"]: m for m in p.compile()["slides"]}
            moved = xv.load_youtube(p.data)["clips"][0]["slide"]
            assert moved in new and new[moved]["t0"] <= mid < new[moved]["t1"] and moved != "s02", (moved, mid, new)
            # A new stretch: the clip's moment falls outside it, so the clip waits unassigned.
            r = xv.regenerate_test(p, object(), None, lambda *a, **k: None, lambda *a, **k: None, start=60, minutes=0.5)
            assert p.span()[0] >= 55 and xv.load_youtube(p.data)["clips"][0]["slide"] == "" and r["version"] == 3
            try:
                xv.regenerate_test(p, object(), None, lambda *a, **k: None, lambda *a, **k: None, start=0, minutes=10)
                raise AssertionError("a test clip as long as the narration was accepted")
            except RuntimeError as e:
                assert "whole narration" in str(e)

            # The route: checks the numbers, starts a job with them.
            got = []
            web_gui._get_run_output_dir = lambda t_, create=True: d / "out"
            web_gui._get_anthropic_client = lambda timeout=60.0: object()
            xv.regenerate_test = lambda proj_, client, cancel, status, log, **kw: got.append(kw) or {"message": "ok"}
            c = web_gui.app.test_client()
            for bad in ({"start": -1}, {"minutes": 0.1}, {"minutes": 11}, {"start": "x"}, {"start": total + 10}):
                assert c.post(f"/api/explainer/{pid}/regenerate", json={"title": title, **bad}).status_code == 400, bad
            r = c.post(f"/api/explainer/{pid}/regenerate", json={"title": title, "start": 12, "minutes": 1.5, "notes": " punchier "}).get_json()
            assert r["success"], r
            for _ in range(100):
                if xv.job_status(pid).get("status") != "running":
                    break
                __import__("time").sleep(0.05)
            assert got == [{"start": 12.0, "minutes": 1.5, "notes": "punchier"}], got
        finally:
            (xv.plan_video, xv.build_slides, web_gui._get_run_output_dir, web_gui._get_anthropic_client, xv.regenerate_test) = keep
            with xv._PROJECTS_LOCK:
                xv._PROJECTS.pop(str(proj.resolve()), None)
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert "🔁 Regenerate test clip" in html and "async function xvRegenerate(" in html and "_xvApi('/regenerate')" in html
    return "new version with a new plan and slides, notes kept; logos and values untouched; the clip moved to the new slide at its moment, unassigned when outside a new stretch; whole-narration refused; route checks start/length"


@check("HeyGen presenter planned on the storyboard first: Claude and sections place it before any clip exists (stand-in in the preview, 4K render gated); then clips are made for only those stretches (cut from the ElevenLabs MP3, padded, merged, rendered side by side into heygen/), placed where they were cut and upscaled with Topaz")
def _():
    import io as _io
    import json as _json
    import shutil
    import subprocess
    import tempfile
    import threading as _thr
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415
    import explainer_video as xv  # noqa: PLC0415
    from PIL import Image

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise AssertionError("ffmpeg/ffprobe are needed for this check (brew install ffmpeg)")
    TPL, LOOK = "92c09f8e9a1c4f078f7ae53886b7ad80", "5fdf87555a1c4320932077baa2c62c37"
    sents = ["AI stocks lost about two point three trillion dollars in one day.",
             "Your index fund probably paid for part of that drop too.",
             "The Nasdaq one hundred fell six point three six percent by the close.",
             "Here is what that means for the money in your retirement account.",
             "First, a correction is a fall of ten percent from a recent peak.",
             "A bear market is a fall of twenty percent or more from that peak.",
             "So far this is a correction and not a bear market at all.",
             "Here is your checklist for the week ahead so you can stay calm."]
    spoken, dur = " ".join(sents), 40.0
    plan = {"summary": "S.", "sections": [{"key": "c1", "label": "One bad day"}],
            "slides": [{"id": "s01", "section": "c1", "kind": "slide", "at": "AI stocks lost about", "idea": "a", "logos": [], "host": "none"},
                       {"id": "s02", "section": "c1", "kind": "slide", "at": "Here is what that means", "idea": "b", "logos": [], "host": "right"},
                       {"id": "s03", "section": "c1", "kind": "slide", "at": "First, a correction is", "idea": "c", "logos": [], "host": "none"}],
            "logos": [], "figures": [], "inserts": [], "questions": [], "dropped": []}
    markup = {
        "s01": '<section id="s01" data-at="AI stocks lost about" data-kind="slide" data-section="c1"><h2 class="h2">Lost</h2></section>',
        "s02": '<section id="s02" data-at="Here is what that means" data-kind="slide" data-section="c1" data-host="right"><h1 class="h1" style="position:absolute;left:160px;top:300px">Your account</h1></section>',
        "s03": '<section id="s03" data-at="First, a correction is" data-kind="slide" data-section="c1"><h2 class="h2">Correction</h2></section>'}
    calls, hg = [], []

    def hg_posts(log):
        return [x for x in log if x[0] == "POST"]

    class _O:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class _Stream:
        def __init__(self, text):
            self.text = text
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def __iter__(self):
            yield _O(type="message_start")
            yield _O(type="content_block_delta", delta=_O(type="text_delta", text=self.text))
        def get_final_message(self):
            return _O(stop_reason="end_turn", content=[_O(type="text", text=self.text)],
                      usage=_O(input_tokens=100, output_tokens=200, cache_creation_input_tokens=0, cache_read_input_tokens=0))

    class _Messages:
        def stream(self, **kw):
            calls.append(kw)
            task = kw["messages"][0]["content"][-1]["text"]
            if "format" in kw["output_config"]:
                return _Stream(_json.dumps(plan))
            if task.startswith("TASK: WRITE SLIDES"):
                return _Stream("\n".join(markup[i] for i in re.findall(r"^(s\d+) \(", task, re.M)))
            raise AssertionError("unexpected Claude call")

    client = _O(beta=_O(messages=_Messages()))
    buf = _io.BytesIO()
    Image.new("RGB", (64, 64), (200, 120, 90)).save(buf, "JPEG")
    avatar_jpg = buf.getvalue()

    class _R:
        def __init__(self, status, body=None, content=b""):
            self.status_code, self._b, self.content = status, body, content
            self.text = _json.dumps(body) if body is not None else ""
        def json(self):
            return self._b
        def raise_for_status(self):
            if self.status_code >= 400:
                raise web_gui.requests.exceptions.HTTPError(response=self)

    assets, videos = {}, {}

    def fake_get(url, params=None, headers=None, timeout=None, stream=False, **kw):
        hg.append(("GET", url, None))
        if url.endswith("/v3/templates"):
            return _R(200, {"data": [{"id": TPL, "name": "Roz in Black Template"}], "has_more": False})
        if url.endswith(f"/v3/templates/{TPL}"):
            return _R(200, {"data": {"id": TPL, "name": "Roz in Black Template", "aspect_ratio": "16:9", "composition": {"scenes": [
                {"background": {"color": "#FFFFFF", "type": "color"}, "elements": [{"type": "avatar", "avatar_id": LOOK, "engine": "avatar_v"}]}]}}})
        if url.endswith(f"/v3/avatars/looks/{LOOK}"):
            return _R(200, {"data": {"id": LOOK, "name": "Black Outfit 4K", "supported_api_engines": ["avatar_v"],
                                     "preview_image_url": "https://img.heygen/look.jpg"}})
        if url == "https://img.heygen/look.jpg":
            return _R(200, content=avatar_jpg)
        if "/v3/videos/" in url:
            vid = url.rsplit("/", 1)[1]
            return _R(200, {"data": {"status": "completed", "video_url": f"https://cdn.heygen/{vid}.mp4"}})
        return _R(404, {"error": {"message": "nope"}})

    def fake_post(url, headers=None, json=None, files=None, timeout=None):
        if url.endswith("/v3/assets"):
            aid = f"asset{len(assets) + 1}"
            assets[aid] = Path(files["file"][1].name)
            hg.append(("POST", url, files["file"][0]))
            return _R(200, {"data": {"asset_id": aid}})
        if url.endswith("/v3/videos"):
            vid = f"vid{len(videos) + 1}"
            videos[vid] = json
            hg.append(("POST", url, json))
            return _R(200, {"data": {"video_id": vid}})
        return _R(404, {"error": {"message": "nope"}})

    def fake_download(url, out_path):
        # HeyGen's video: the avatar (colour bars here) speaking the uploaded MP3, as long as the audio.
        audio = assets[videos[url.rsplit("/", 1)[1][:-4]]["audio_asset_id"]]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "smptebars=s=640x360:r=25", "-i", str(audio),
                        "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                        str(out_path)], check=True)

    def wait(c, pid):
        for _ in range(4000):
            s = c.get(f"/api/explainer/{pid}?title=Talk").get_json()
            if (s.get("job") or {}).get("status") != "running":
                return s
            _thr.Event().wait(0.05)
        raise AssertionError("explainer job never finished")

    topaz = []

    def fake_presenter_topaz(proj, key, root, status, cancel, log, names=None, model=xv.TOPAZ_MODEL):
        topaz.append((key, sorted(names or []), model))
        return {"message": f"{len(names or [])} clip(s) upscaled with Topaz {xv.TOPAZ_MODELS[model]['label']}"}

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        out = d / "out"
        (out / "voiceover").mkdir(parents=True)
        mp3 = out / "voiceover" / "Talk_elevenlabs_Roz_1.mp3"
        expr = "0.5*sin(2*PI*190*t)*gt(sin(2*PI*0.83*t)+sin(2*PI*2.31*t+1.3)+sin(2*PI*0.29*t+0.4),0.2)*lt(mod(t,5),4.6)"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={dur}",
                        "-ac", "1", "-c:a", "libmp3lame", "-b:a", "128k", str(mp3)], check=True)
        mp3.with_suffix(".txt").write_text(spoken, encoding="utf-8")
        keep = (web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui._get_run_output_dir, web_gui._get_anthropic_client, web_gui._eleven_key,
                web_gui._heygen_key, web_gui._topaz_key, web_gui._hg_download, web_gui.requests.get, web_gui.requests.post,
                web_gui._HG_AUDIO_POLL_SECONDS, xv.align_words, xv.presenter_topaz, os.environ.get("ANTHROPIC_API_KEY"))
        try:
            settings = d / "settings.json"
            settings.write_text(_json.dumps({"heygen_audio_template_id": TPL, "heygen_audio_resolution": "1080p"}))
            web_gui.SCRIPTCRAFT_SETTINGS_PATH = settings
            web_gui._get_run_output_dir = lambda title, create=True: out
            web_gui._get_anthropic_client = lambda timeout=60.0: client
            web_gui._eleven_key = lambda: "sk_test_eleven"
            web_gui._heygen_key = lambda: "hg-test-key-123456"
            web_gui._topaz_key = lambda: "tpz-test-key-4321"
            web_gui._hg_download = fake_download
            web_gui.requests.get, web_gui.requests.post = fake_get, fake_post
            web_gui._HG_AUDIO_POLL_SECONDS = 0
            # Timed like real narration: one sentence every 5 s, then a half-second pause.
            xv.align_words = lambda audio, text, key, timeout=900: ([
                {"text": w_, "start": round(5 * i + 4.5 * k / len(sn.split()), 3),
                 "end": round(5 * i + 4.5 * (k + 0.8) / len(sn.split()), 3)}
                for i, sn in enumerate(sents) for k, w_ in enumerate(sn.split())], 0.1)
            xv.presenter_topaz = fake_presenter_topaz
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
            c = web_gui.app.test_client()
            o = c.get("/api/explainer/options?title=Talk").get_json()
            assert o["heygen"] is True, o

            # 1. Plan the presenter: Claude plans with it (seeing the template's avatar) before any clip exists.
            r = c.post("/api/explainer/start", json={"title": "Talk", "voiceover": mp3.name, "script": "**Host:**\n" + spoken,
                                                     "presenter": "heygen", "share": "some"}).get_json()
            pid = r["project"]
            s = wait(c, pid)
            assert s["job"]["status"] == "done", s["job"]
            h = s["host"]
            assert h["planned"] and h["parts"] == [] and h["still"] == "host/still.jpg" and not hg_posts(hg), h
            ctx = " ".join(b.get("text", "") for b in calls[0]["messages"][0]["content"] if b.get("type") == "text")
            assert "is made after this storyboard" in ctx and "The presenter avatar:" in ctx
            assert any(b.get("type") == "image" for b in calls[0]["messages"][0]["content"])
            win = next(w for w in s["host_windows"] if w["layout"] == "right")
            s02 = {m["id"]: m for m in s["slides"]}["s02"]
            assert abs(win["t0"] - s02["t0"]) < 0.06 and win["t1"] > s02["t1"], (win, s02)
            assert h["missing"] == [[round(win["t0"], 2), round(min(win["t1"], s["audio_seconds"]), 2)]], (h["missing"], win)
            need = [x for x in s["outstanding"] if x["type"] == "presenter"]
            assert len(need) == 1 and need[0]["slides"] == ["s02"], s["outstanding"]
            page = c.get(f"/api/explainer/{pid}/preview?title=Talk").get_data(as_text=True)
            assert '"missing": [[0.0, 1000000000.0]]' in page and '"video": null' in page

            # 2. A section placed before any clip: allowed, with a note; it adds a stretch to make.
            r = c.post(f"/api/explainer/{pid}/sections", json={"title": "Talk", "sections": [{"t0": 36.0, "t1": 38.5, "layout": "left"}]}).get_json()
            assert r["success"] and "make the HeyGen clips once the storyboard is set" in r["warning"], r.get("warning")
            gaps = [tuple(x) for x in r["host"]["missing"]]
            assert gaps[-1] == (36.0, 38.5) and len(gaps) == 2, gaps
            spans = r["host"]["clip_spans"]
            tl = xv.open_project(out / "explainer" / pid).timeline()
            assert spans == [list(x) for x in xv.clip_spans(gaps, r["audio_seconds"], timeline=tl)] and len(spans) == 2, spans
            # Whole sentences: s02's window runs into "First, a correction ..." (its exit fade), so the clip
            # takes that sentence to its end; the section's clip starts in the pause before its sentence.
            assert not [x for a_, b_ in spans for x in (a_, b_) for w in tl.words if w["start"] < x < w["end"]], spans
            sen = tl.sentences()
            assert sen[2][1] < spans[0][0] <= sen[3][0] and sen[4][1] <= spans[0][1] < sen[5][0], (spans, sen)
            assert sen[6][1] < spans[1][0] <= sen[7][0] and spans[1][1] >= sen[7][1], (spans, sen)

            # 3. Templates for the clips; the quote names the stretches and the Topaz credits.
            ho = c.get("/api/explainer/heygen-options").get_json()
            assert ho["success"] and ho["template_id"] == TPL and ho["topaz"] and "hg-test-key" not in _json.dumps(ho), ho
            q = c.post(f"/api/explainer/{pid}/heygen-make", json={"title": "Talk", "upscale": True}).get_json()["quote"]
            assert q["spans"] == spans and q["label"] == "Starlight Precise 2.6" and q["credits"] == sum(
                xv.topaz_quote(b - a, 25)["credits"] for a, b in spans), q
            assert not hg_posts(hg)
            bad = c.post(f"/api/explainer/{pid}/heygen-make", json={"title": "Talk", "confirm": True, "template_id": "../x"})
            assert bad.status_code == 400

            # 4. Make them: only those stretches of the MP3 go to HeyGen; each clip lands where it was cut; Topaz follows.
            r = c.post(f"/api/explainer/{pid}/heygen-make", json={"title": "Talk", "confirm": True, "template_id": TPL,
                                                                  "resolution": "1080p", "upscale": True}).get_json()
            assert r["success"], r
            s = wait(c, pid)
            assert s["job"]["status"] == "done" and "2 HeyGen clip(s) made and placed" in s["job"]["message"], s["job"]
            ups = [x[2] for x in hg if x[0] == "POST" and x[1].endswith("/v3/assets")]
            assert len(ups) == 2 and all(re.fullmatch(r"Talk_presenter_\d{8}_\d{6}_0[12]_at0m(14|34)s\.mp3", u) for u in ups), ups
            for (a, b), u in zip(spans, ups):
                secs = web_gui._audio_seconds(out / "voiceover" / "clips" / u)
                assert abs(secs - (b - a)) < 0.1, (u, secs, a, b)
            bodies = [x[2] for x in hg if x[0] == "POST" and x[1].endswith("/v3/videos")]
            assert [b_["title"] for b_ in bodies] == [f"Talk (ElevenLabs audio) presenter {xv.fmt_secs(a)}-{xv.fmt_secs(b)}" for a, b in spans]
            assert all(b_["avatar_id"] == LOOK and b_["engine"] == {"type": "avatar_v"} and b_["resolution"] == "1080p" for b_ in bodies)
            h = s["host"]
            assert h["planned"] and len(h["parts"]) == 2, h
            for part, (a, b) in zip(h["parts"], spans):
                assert abs(part["offset"] - a) < 0.06 and part["score"] > 0.9 and part["name"].endswith(".mp4"), (part, a)
            assert h["missing"] == [] and h["clip_spans"] == [] and not [x for x in s["outstanding"] if x["type"] == "presenter"]
            man = _json.loads((out / "heygen" / "heygen_videos.json").read_text())
            assert set(man) == {"vid1", "vid2"} and all((out / "heygen" / v["file"]).is_file() for v in man.values())
            assert topaz == [("tpz-test-key-4321", sorted(p_["name"] for p_ in h["parts"]), "slp-2.6")], topaz
            assert _json.loads(settings.read_text())["heygen_audio_template_id"] == TPL
            page = c.get(f"/api/explainer/{pid}/preview?title=Talk").get_data(as_text=True)
            assert '"missing": []' in page and "&path=host/proxy.mp4" in page
            # The preview copy keeps each clip at its time: black in the gap, as long as the last clip's end.
            proxy = out / "explainer" / pid / "host" / "proxy.mp4"
            assert abs(xv.probe_video(proxy)["seconds"] - (h["parts"][1]["offset"] + h["parts"][1]["seconds"])) < 0.1, xv.probe_video(proxy)
            assert c.post(f"/api/explainer/{pid}/heygen-make", json={"title": "Talk", "confirm": True, "template_id": TPL}).status_code == 400

            # 5. Taking clips out keeps the planned presenter; its stretch needs a clip again.
            c.post(f"/api/explainer/{pid}/host", json={"title": "Talk", "remove": h["parts"][1]["name"]})
            s = wait(c, pid)
            assert len(s["host"]["parts"]) == 1 and s["host"]["missing"] == [[36.0, 38.5]], s["host"]
            c.post(f"/api/explainer/{pid}/host", json={"title": "Talk", "remove": h["parts"][0]["name"]})
            s = wait(c, pid)
            assert s["host"]["planned"] and s["host"]["parts"] == [] and len(s["host"]["missing"]) == 2, s["host"]
            assert "make them again under Presenter" in s["job"]["message"]
            rendered = "render skipped (no Chrome)"
            if xv.find_chrome():
                # A sample render before the clips exist: the stand-in fills the presenter's area (not a hole).
                r = c.post(f"/api/explainer/{pid}/render", json={"title": "Talk", "kind": "sample", "start": 36.2, "seconds": 2}).get_json()
                s = wait(c, pid)
                assert s["job"]["status"] == "done", s["job"]
                f = out / "explainer" / pid / s["renders"][-1]["files"][0]["path"]
                im = Image.open(_io.BytesIO(subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(f), "-frames:v", "1",
                                                            "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True).stdout)).convert("RGB")
                px = im.getpixel((200, 900))                     # inside the left panel (the 36-38.5 s section)
                assert 15 <= px[0] <= 60 and px[2] > px[0] and max(px) < 90, px
                rendered = "a sample before the clips shows the stand-in in the presenter's panel"
            r = c.post(f"/api/explainer/{pid}/render", json={"title": "Talk", "kind": "final"}).get_json()
            assert not r["success"] and any(x["type"] == "presenter" for x in r["outstanding"]), r
        finally:
            (web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui._get_run_output_dir, web_gui._get_anthropic_client, web_gui._eleven_key,
             web_gui._heygen_key, web_gui._topaz_key, web_gui._hg_download, web_gui.requests.get, web_gui.requests.post,
             web_gui._HG_AUDIO_POLL_SECONDS, xv.align_words, xv.presenter_topaz, k) = keep
            if k is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = k

    # Gaps and clip spans: covered stretches drop out; padding, merging and the narration's end.
    assert xv.presenter_gaps([{"t0": 5, "t1": 12, "layout": "full"}, {"t0": 20, "t1": 30, "layout": "left"}], [(8, 25)]) == [(5, 8), (25, 30)]
    assert xv.presenter_gaps([{"t0": 5, "t1": 12, "layout": "full"}, {"t0": 11, "t1": 14, "layout": "pip"}], []) == [(5, 14)]
    assert xv.clip_spans([(5, 8), (10, 12), (25, 30), (59.8, 60.5)], 60.2) == [(4.5, 12.5), (24.5, 30.5), (59.3, 60.2)]
    assert len(xv.clip_spans([(0, 3600)], 3600)) == 3
    # With the timed words: whole sentences, the pad kept inside the pauses (no tail of the sentence
    # before, no first words of the next); a window ending in a sentence's first word takes in all of it.
    ws, t = [], 0.0
    for sent in ("One two three.", "Four five six seven.", "Eight nine.", "Ten eleven twelve."):
        for wd in sent.split():
            ws.append({"text": wd, "start": round(t, 2), "end": round(t + 0.3, 2)})
            t += 0.4
        t += 0.6
    tl = xv.Timeline(ws, t)
    assert xv.clip_spans([(1.75, 4.1)], t, timeline=tl) == [(1.25, 5.2)], xv.clip_spans([(1.75, 4.1)], t, timeline=tl)
    assert xv.clip_spans([(1.75, 4.1)], t) == [(1.25, 4.6)]                     # without words: ends inside "nine"
    assert xv.clip_spans([(2.3, 3.2)], t, timeline=tl) == [(1.3, 3.8)]          # a window inside one sentence
    src = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    assert src.count("timeline=p.timeline()") == 2
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert 'id="hgaSection"' not in html and "/api/heygen/audio-video" not in html and "function hga" not in html
    assert "async function xvMakeClips(" in html and "function _xvMakePanel(" in html and "async function xvHostPlan(" in html
    assert '<option value="heygen">' in html and "o.type === 'presenter'" in html and "Explainer Video</a> → Presenter" in html
    assert "presenter clips are made later in the Explainer Video" in html
    js = open(os.path.join(APP, "static", "explainer", "runtime.js"), encoding="utf-8").read()
    assert "HeyGen clip not made yet" in js and "placeHost(holes, t, frame)" in js   # the stand-in also sits in a device frame's screen
    return ("planned presenter: Claude plans with the avatar still, a section placed before any clip, stand-in in the preview, "
            "4K render gated; 2 clips made for just the 2 stretches (padded, cut from the MP3, nothing sent before the confirm), "
            "placed at their cut points by audio, then Topaz; preview copy keeps clip times across the gap; removing clips "
            "keeps the plan; " + rendered)



@check("Explainer video: Claude Opus 5.5 (high) plans + writes slides in parallel batches on the timed narration; unsafe/off-style markup stripped; logos, figures and [insert] values gate the 4K render; revise splits a slide into a new version; renders sample, 4K final, phone copy and asset PNG")
def _():
    import json as _json
    import shutil
    import subprocess
    import tempfile
    import threading as _thr
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import anthropic
    import httpx
    import web_gui  # noqa: PLC0415
    import explainer_video as xv  # noqa: PLC0415
    from PIL import Image, ImageDraw

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise AssertionError("ffmpeg/ffprobe are needed for this check (brew install ffmpeg)")
    spoken = ("AI stocks lost about two point three trillion dollars in one day. Your index fund probably paid too. "
              "The Nasdaq one hundred fell six point three six percent. Here is your checklist for the week ahead.")
    script = ("**Talk**\n\n**Host:**\n" + spoken.replace(". ", ".\n") + "\n[PRODUCTION BEGIN]\n[VERIFY BEFORE RENDER] Confirm 6.36%.\n"
              "[GROK IMAGINE / RESOLVE] A night skyline with a falling chart.\n[ON SCREEN / RESOLVE] Overlay: jobs report [insert]\n"
              "[PRODUCTION END]\n\n#  B-ROLL SEARCH TERMS TABLE\n| a | b |\n")
    plan = {"summary": "One scene, one stat slide, one checklist.",
            "sections": [{"key": "c1", "label": "One bad day"}, {"key": "c2", "label": "What to do"}],
            "slides": [{"id": "s01", "section": "c1", "kind": "scene", "at": "AI stocks lost about", "idea": "Skyline, chart falls", "logos": ["acme"]},
                       {"id": "s02", "section": "c1", "kind": "slide", "at": "Your index fund probably", "idea": "6.36% stat", "logos": ["openai"]},
                       {"id": "s03", "section": "c2", "kind": "asset", "at": "Here is your checklist", "idea": "Checklist", "logos": []}],
            "logos": [{"key": "acme", "name": "Acme"}, {"key": "openai", "name": "OpenAI"}],
            "figures": [{"key": "nasdaq_drop", "label": "Nasdaq-100 one-day fall", "value": "6.36%", "note": "Confirm the close"}],
            "inserts": [{"key": "jobs_report", "label": "Friday jobs report", "note": "Overlay only"}],
            "questions": ["Will avatar clips be cut in?"], "dropped": []}
    slides = {
        "s01": ('<section id="s01" data-at="AI stocks lost about" data-kind="scene" data-section="c1" data-hud="off"><div class="scene">'
                '<svg class="fill" viewBox="0 0 1920 1080"><rect x="0" y="700" width="1920" height="380" fill="var(--navy-2)"/>'
                '<polyline points="200,300 600,500 900,800" fill="none" stroke="var(--red)" stroke-width="8" data-anim="draw" data-at="two point three trillion"/>'
                '<image data-logo="acme" x="1400" y="200" width="300" height="120" data-anim="pop" data-at="in one day"/>'
                '<linearGradient id="g"><stop stop-color="#ff0000"/></linearGradient><rect x="10" y="10" width="50" height="50" fill="url(#g)"/></svg></div>'
                '<script>alert(1)</script><div class="lower-third" data-anim="up" data-at="two point three trillion" onclick="steal()">$2.3T erased</div></section>'),
        "s02": ('<section id="s02" data-at="Your index fund probably" data-kind="slide" data-section="c1"><style>.x{box-shadow:0 0 9px red;color:var(--gold)}</style>'
                '<div class="pad col gap-m"><h1 class="h1" data-anim="words">Your fund paid</h1>'
                '<div class="huge red" data-anim="count" data-ph="nasdaq_drop" data-at="six point three six">6.36%</div>'
                '<img class="logo" data-logo="openai" alt="OpenAI"><img src="https://evil.example/x.png">'
                '<div class="overlay-card" data-needs="jobs_report">Jobs: <span data-ph="jobs_report">[insert]</span></div></div></section>'),
        "s03": ('<section id="s03" data-at="Here is your checklist" data-kind="asset" data-section="c2"><div class="pad">'
                '<h2 class="h2" data-anim="rise">Your checklist</h2><ul class="checklist" data-stagger="0.15" data-anim="left" data-at="week ahead">'
                '<li>Check your fund</li><li>Stay the course</li></ul></div></section>'),
    }
    revised = ('CHANGES: Split the stat onto its own slide.\n<section id="s02" data-at="Your index fund probably" data-kind="slide" data-section="c1"><h1 class="h1">Revised</h1></section>'
               '<section id="s02b" data-at="The Nasdaq one hundred" data-kind="slide" data-section="c1">'
               '<div class="huge" data-ph="nasdaq_drop">6.36%</div></section>')
    calls, mode = [], {"build_calls": 0, "fallback_400": True}

    class _O:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class _Stream:
        def __init__(self, text):
            self.text = text
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def __iter__(self):
            yield _O(type="message_start")
            for i in range(0, len(self.text), 300):
                yield _O(type="content_block_delta", delta=_O(type="text_delta", text=self.text[i:i + 300]))
        def get_final_message(self):
            return _O(stop_reason="end_turn", content=[_O(type="text", text=self.text)],
                      usage=_O(input_tokens=1000, output_tokens=4000, cache_creation_input_tokens=2000, cache_read_input_tokens=500))

    class _Messages:
        def stream(self, **kw):
            calls.append(kw)
            if mode["fallback_400"]:
                mode["fallback_400"] = False
                raise anthropic.BadRequestError("fallbacks: not enabled for this organization",
                                                response=httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
                                                body=None)
            task = kw["messages"][0]["content"][-1]["text"]
            if "format" in kw["output_config"]:
                return _Stream(_json.dumps(plan))
            if task.startswith("TASK: WRITE SLIDES"):
                mode["build_calls"] += 1
                ids = re.findall(r"^(s\d+) \(", task, re.M)
                if mode["build_calls"] == 2 and len(ids) > 1:
                    ids = ids[:1]          # one slide "forgotten": the batch is retried for it
                return _Stream("\n".join(slides[i] for i in ids))
            if "TASK: REVISE" in task:
                return _Stream(revised)
            raise AssertionError("unexpected Claude call")

    client = _O(beta=_O(messages=_Messages()))

    def wait(c, pid):
        for _ in range(3000):
            s = c.get(f"/api/explainer/{pid}?title=Talk").get_json()
            if (s.get("job") or {}).get("status") != "running":
                return s
            _thr.Event().wait(0.05)
        raise AssertionError("explainer job never finished")

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        out = d / "out"
        vo = out / "voiceover"
        img = out / "images"
        vo.mkdir(parents=True)
        img.mkdir(parents=True)
        mp3 = vo / "Talk_elevenlabs_Roz_1.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "aevalsrc='if(lt(mod(t,3),2.6),0.4*sin(2*PI*220*t),0)':s=44100:d=9",
                        "-ac", "1", "-c:a", "libmp3lame", "-b:a", "128k", str(mp3)], check=True)
        mp3.with_suffix(".txt").write_text(spoken, encoding="utf-8")
        logo = Image.new("RGBA", (400, 120), (0, 0, 0, 0))
        ImageDraw.Draw(logo).rectangle((20, 20, 380, 100), fill=(20, 20, 24, 255))     # a black wordmark
        logo.save(img / "icons8-acme-480.png")
        Image.new("RGB", (300, 300), (180, 120, 90)).save(img / "person.jpg")         # a photo: no transparency
        keep = (web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui._get_run_output_dir, web_gui._get_anthropic_client,
                web_gui._eleven_key, xv.align_words, xv.BATCH_WEIGHT, os.environ.get("ANTHROPIC_API_KEY"))
        try:
            settings = d / "settings.json"
            settings.write_text("{}")
            web_gui.SCRIPTCRAFT_SETTINGS_PATH = settings
            web_gui._get_run_output_dir = lambda title, create=True: out
            web_gui._get_anthropic_client = lambda timeout=60.0: client
            web_gui._eleven_key = lambda: "sk_test_eleven"
            xv.align_words = lambda audio, text, key, timeout=900: (xv.estimate_words(text, 8.6, [(2.6, 3.0), (5.6, 6.0)]), 0.1)
            xv.BATCH_WEIGHT = 2.0
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
            c = web_gui.app.test_client()

            o = c.get("/api/explainer/options?title=Talk").get_json()
            assert o["success"] and [v["name"] for v in o["voiceovers"]] == [mp3.name], o
            ims = {i["file"]: i for i in o["images"]}
            assert ims["icons8-acme-480.png"]["logo"] and ims["icons8-acme-480.png"]["name"] == "Acme" and not ims["person.jpg"]["logo"], ims
            assert c.get("/api/explainer/image?title=Talk&file=../settings.json").status_code == 404
            assert c.post("/api/explainer/start", json={"title": "Talk", "voiceover": "nope.mp3", "script": script}).status_code == 400

            r = c.post("/api/explainer/start", json={"title": "Talk", "voiceover": mp3.name, "script": script,
                                                    "logos": [{"file": "icons8-acme-480.png", "name": "Acme", "recolor": "auto"}]}).get_json()
            assert r["success"], r
            pid = r["project"]
            s = wait(c, pid)
            assert s["job"]["status"] == "done", s["job"]
            proj = out / "explainer" / pid
            assert "B-ROLL" not in (proj / "script.txt").read_text() and (proj / "narration.wav").is_file() and (proj / "narration.m4a").is_file()
            assert s["timing"]["source"] == "elevenlabs" and s["text_source"].startswith("the exact text")
            assert [m["id"] for m in s["slides"]] == ["s01", "s02", "s03"] and s["current"] == 1, s["slides"]
            assert s["slides"][0]["t0"] == 0 and 1.5 < s["slides"][1]["t0"] < s["slides"][2]["t0"] and s["duration"] == round(s["audio_seconds"] + 1.5, 3), \
                ([(m["id"], m["t0"], m["t1"]) for m in s["slides"]], s["duration"], s["audio_seconds"])
            assert s["logos"]["acme"]["recolored"] and s["logos"]["acme"]["kind"] == "wordmark"
            px = Image.open(proj / "logos" / "acme.png").convert("RGBA").getpixel((100, 40))
            assert px[:3] == xv.OFF_WHITE and px[3] == 255, px                       # black mark → off-white
            need = {(o_["type"], o_["key"]) for o_ in s["outstanding"]}
            assert need == {("logo", "openai"), ("figure", "nasdaq_drop"), ("insert", "jobs_report")}, need
            # Claude calls: plan (structured), 2 batches + 1 retry; Opus 5.5 at high effort, cached prefix, fallback dropped after a 400.
            assert calls[0].get("betas") == [xv.FALLBACK_BETA] and calls[0]["extra_body"] == {"fallbacks": "default"}
            assert "betas" not in calls[1] and "format" in calls[1]["output_config"]
            build = [k for k in calls[2:] if k["messages"][0]["content"][-1]["text"].startswith("TASK: WRITE SLIDES")]
            assert len(build) == 3, len(build)
            for k in calls:
                assert k["model"] == "claude-opus-5-5" and k["output_config"]["effort"] == "high" and k["thinking"] == {"type": "adaptive"}
                assert k["system"][0]["cache_control"] == {"type": "ephemeral"} and "COMPOSITION FORMAT" in k["system"][0]["text"]
                assert k["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
            assert "THE PLAN (JSON)" in build[0]["messages"][0]["content"][1]["text"]
            assert s["usage"]["output_tokens"] > 0 and s["usage"]["cost"] > 0

            page = c.get(f"/api/explainer/{pid}/preview?title=Talk").get_data(as_text=True)
            # design.css has its own box-shadow (the cards' solid offset); Claude's blurred red one is what must go.
            # The app's own transition and board-look scripts draw canvas gradients
            # (createLinearGradient); only Claude's markup has to be free of them, so those files are set aside.
            own = page
            for js in ("transitions.js", "board.js"):
                with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "explainer", js), encoding="utf-8") as fh:
                    fxjs = fh.read()
                assert fxjs in page, js
                own = own.replace(fxjs, "")
            for bad in ("alert(1)", "onclick", "evil.example", "9px red", "lineargradient", "url(#g)"):
                assert bad not in own.lower(), bad
            assert "Content-Security-Policy" in page and 'data-t0="0.000"' in page and "data:image/png;base64," in page
            assert 'data-logo-missing="openai"' in page and re.search(r'class="[^"]*ph-pending', page) and "#s02 .x" in page

            # Fill in what blocks the 4K render; the final stays locked until approved.
            r = c.post(f"/api/explainer/{pid}/values", json={"title": "Talk", "values": {
                "nasdaq_drop": {"status": "confirmed", "value": "6.36%"}, "jobs_report": {"status": "filled", "value": "+12,000 jobs"}},
                "logo_choices": {"openai": "badge"}, "answers": {"Will avatar clips be cut in?": "No, headless"}}).get_json()
            assert r["outstanding"] == [] and r["values"]["jobs_report"]["value"] == "+12,000 jobs", r["outstanding"]
            page = c.get(f"/api/explainer/{pid}/preview?title=Talk").get_data(as_text=True)
            assert "+12,000 jobs" in page and 'data-to="6.36"' in page and not re.search(r'class="[^"]*ph-pending', page), \
                re.findall(r'<[^>]*ph-pending[^>]*>', page)[:3]

            # Change a logo's file: a new upload replaces it on every slide, even under the same file name
            # (the compiled slides are cached by the logo records); a text badge instead, and a file again.
            import io as _io
            uris = lambda html_: set(re.findall(r"data:image/png;base64,[A-Za-z0-9+/=]{40,}", html_))   # noqa: E731

            def png(color, size=(600, 100)):
                im_ = Image.new("RGBA", size, (0, 0, 0, 0))
                ImageDraw.Draw(im_).rectangle((10, 10, size[0] - 10, size[1] - 10), fill=color)
                buf_ = _io.BytesIO()
                im_.save(buf_, "PNG")
                return buf_.getvalue()

            def put_logo(**fields):
                f_ = {"title": "Talk", **{k_: v_ for k_, v_ in fields.items() if k_ != "upload"}}
                if "upload" in fields:
                    f_["file"] = (_io.BytesIO(fields["upload"][1]), fields["upload"][0])
                return c.post(f"/api/explainer/{pid}/logo", data=f_, content_type="multipart/form-data").get_json()

            page0 = c.get(f"/api/explainer/{pid}/preview?title=Talk").get_data(as_text=True)
            was = s["logos"]["acme"]
            r = put_logo(key="acme", name="Acme", recolor="original", upload=("icons8-acme-480.png", png((200, 30, 30, 255))))
            L1 = r["logos"]["acme"]
            assert r["success"] and L1["source"] == "icons8-acme-480.png" and L1["recolor"] == "original" and L1["aspect"] > 5, L1
            assert L1["updated"] > (was.get("updated") or 0) and L1["path"] == "logos/acme.png"
            assert Image.open(img / "icons8-acme-480.png").convert("RGB").getpixel((300, 50)) == (200, 30, 30)
            page1 = c.get(f"/api/explainer/{pid}/preview?title=Talk").get_data(as_text=True)
            assert uris(page1) != uris(page0) and r["outstanding"] == []
            # Same name, same shape, same recolor: only the file's content differs, and the slides still change.
            r = put_logo(key="acme", name="Acme", recolor="original", upload=("icons8-acme-480.png", png((30, 30, 200, 255))))
            assert r["success"] and r["logos"]["acme"]["aspect"] == L1["aspect"] and r["logos"]["acme"]["updated"] > L1["updated"]
            page2 = c.get(f"/api/explainer/{pid}/preview?title=Talk").get_data(as_text=True)
            assert uris(page2) != uris(page1) and Image.open(proj / "logos" / "acme.png").convert("RGB").getpixel((300, 50)) == (30, 30, 200)
            # A text badge instead; nothing new is asked for; then the file again from images/.
            r = put_logo(key="acme", remove="1")
            assert r["success"] and "acme" not in r["logos"] and r["logo_choices"]["acme"] == "badge" and r["outstanding"] == [], r["outstanding"]
            assert 'data-logo-missing="acme"' in c.get(f"/api/explainer/{pid}/preview?title=Talk").get_data(as_text=True)
            r = put_logo(key="acme", name="Acme", image="icons8-acme-480.png")
            assert r["success"] and r["logos"]["acme"]["source"] == "icons8-acme-480.png" and "acme" not in r["logo_choices"]
            assert 'data-logo-missing="acme"' not in c.get(f"/api/explainer/{pid}/preview?title=Talk").get_data(as_text=True)
            # The brand that was a badge gets a file later.
            r = put_logo(key="openai", name="OpenAI", upload=("openai-mark.png", png((240, 240, 240, 255), (300, 300))))
            assert r["success"] and r["logos"]["openai"]["kind"] == "icon" and r["outstanding"] == [], r
            page3 = c.get(f"/api/explainer/{pid}/preview?title=Talk").get_data(as_text=True)
            assert 'data-logo-missing="openai"' not in page3
            assert put_logo(key="acme", upload=("notes.txt", b"x"))["success"] is False
            assert put_logo(key="", remove="1")["success"] is False

            r = c.post(f"/api/explainer/{pid}/render", json={"title": "Talk", "kind": "final"}).get_json()
            assert not r["success"] and "Approve" in r["error"], r
            assert c.post(f"/api/explainer/{pid}/approve", json={"title": "Talk"}).get_json()["approved"] == 1
            for bad in ("renders/../project.json", "project.json", "../x", "logos/../project.json"):
                assert c.get(f"/api/explainer/{pid}/file?title=Talk&path={bad}").status_code == 404, bad
            assert c.get(f"/api/explainer/{pid}?title=Other").status_code == 404
            assert c.get("/api/explainer/..%2F..?title=Talk").status_code == 404

            # A revision of s02 splits it; the approval does not carry over.
            assert c.post(f"/api/explainer/{pid}/revise", json={"title": "Talk", "slides": []}).status_code == 400
            r = c.post(f"/api/explainer/{pid}/revise", json={"title": "Talk", "feedback": "Split the stat out", "scope": "slides",
                                                              "slides": ["s02"], "see": False, "warnings": {"s02": ["“Revised” overlaps “x”"]}}).get_json()
            assert r["success"], r
            s = wait(c, pid)
            assert s["job"]["status"] == "done" and s["current"] == 2 and s["approved"] is None, s["job"]
            assert [m["id"] for m in s["slides"]] == ["s01", "s02", "s02b", "s03"], [m["id"] for m in s["slides"]]
            task = calls[-1]["messages"][0]["content"][-1]["text"]
            assert "Split the stat out" in task and "overlaps" in task and 'data-logo="openai"' in task
            assert [v["n"] for v in s["versions"]] == [1, 2] and s["versions"][1]["kind"] == "revise"
            assert s["versions"][1]["note"] == "Split the stat out \u2192 Split the stat onto its own slide." and "Split the stat onto" in s["job"]["message"], s["versions"][1]
            assert c.post(f"/api/explainer/{pid}/version", json={"title": "Talk", "n": 1}).get_json()["current"] == 1
            assert c.post(f"/api/explainer/{pid}/version", json={"title": "Talk", "n": 2}).get_json()["current"] == 2

            rendered = "renders skipped (no Chrome)"
            if xv.find_chrome():
                r = c.post(f"/api/explainer/{pid}/render", json={"title": "Talk", "kind": "sample", "start": 2.0, "seconds": 5}).get_json()
                assert r["success"], r
                s = wait(c, pid)
                assert s["job"]["status"] == "done", s["job"]
                f = s["renders"][-1]["files"][0]
                probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                                        "-of", "json", str(proj / f["path"])], capture_output=True, text=True).stdout
                info = _json.loads(probe)
                assert {st["codec_type"] for st in info["streams"]} == {"video", "audio"} and info["streams"][0]["width"] == 1920
                assert abs(float(info["format"]["duration"]) - 5.0) < 0.1, info["format"]
                assert c.get(f"/api/explainer/{pid}/file?title=Talk&path={f['path']}").status_code == 200
                c.post(f"/api/explainer/{pid}/approve", json={"title": "Talk"})
                r = c.post(f"/api/explainer/{pid}/render", json={"title": "Talk", "kind": "final"}).get_json()
                assert r["success"], r
                s = wait(c, pid)
                assert s["job"]["status"] == "done", s["job"]
                files = {x["kind"]: x for x in s["renders"][-1]["files"]}
                assert set(files) == {"final", "phone", "asset"}, files
                dims = lambda p: subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                                                 str(proj / p)], capture_output=True, text=True).stdout.split()[0]
                assert dims(files["final"]["path"]) == "3840,2160" and dims(files["phone"]["path"]) == "1280,720"
                assert Image.open(proj / files["asset"]["path"]).size == (3840, 2160)
                assert s["renders"][-1]["levels"]["max_db"] is not None
                rendered = "sample 1080p 5 s with audio, 4K final + 720p phone copy + 4K asset PNG rendered"
        finally:
            (web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui._get_run_output_dir, web_gui._get_anthropic_client,
             web_gui._eleven_key, xv.align_words, xv.BATCH_WEIGHT, k) = keep
            if k is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = k

        # The ElevenLabs job now saves the exact text it read next to the MP3.
        keep = (web_gui._eleven_voice_settings, web_gui._eleven_tts_part)
        try:
            web_gui._eleven_voice_settings = lambda *a, **k: {}
            web_gui._eleven_tts_part = lambda *a, **k: (mp3.read_bytes(), "rid")
            target = d / "vo2" / "x.mp3"
            web_gui._eleven_run("job-xv", "key", "voice", "Roz", "eleven_v4", ["Part one.", "Part two."], target)
            assert target.with_suffix(".txt").read_text() == "Part one.\n\nPart two."
        finally:
            web_gui._eleven_voice_settings, web_gui._eleven_tts_part = keep

    tl = xv.Timeline(xv.estimate_words(spoken, 8.6, []), 8.6)
    assert tl.find("six point three six")[2] == "exact" and tl.find("six point tree six")[2] == "approx" and tl.find("bitcoin rally") is None
    merged, changed = xv.merge_sections(xv.split_sections(slides["s01"] + slides["s02"] + slides["s03"]),
                                        xv.split_sections(revised + '<section id="s03" data-delete="1"></section>'))
    assert [m["id"] for m in merged] == ["s01", "s02", "s02b"] and changed == ["s02", "s02b", "s03"]
    assert xv.logo_name_from_file("google-deepmind-logo-png_seeklogo-284971.png") == "Google Deepmind"
    assert xv.logo_name_from_file("TSM-f70117e2.png") == "TSM" and xv.logo_name_from_file("Nasdaq_blue_black_transparent_backgr.png") == "Nasdaq"
    assert xv.script_body(script).endswith("[PRODUCTION END]")

    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert 'onclick="openExplainerModal()"' in html and 'id="explainerModal"' in html
    assert 'id="xvEpisodeTitle"' in html and "_xvEpisode(src.empty ? '' : src.title);" in html
    assert 'id="xvMuteBtn"' in html and 'onclick="xvMute()"' in html and "function xvMute(on)" in html
    assert "xvMute(muted);" in html and "localStorage.setItem('scriptcraft_xv_muted'" in html, "the episode title shows at the top"
    assert '<iframe id="xvFrame" sandbox="allow-scripts"' in html and "ev.source !== fr.contentWindow" in html
    assert "async function xvRevise(" in html and "async function xvRender(" in html and "function _xvRenderNeeds(" in html
    return ("plan + 2 batches (+1 retry for a dropped slide) at effort high with cached prefix; fallback beta dropped after a 400; "
            "script/onclick/external img/gradient/shadow stripped; black logo recolored; figure + insert + missing logo block the 4K "
            "until filled; approval required and reset by a revision (s02 → s02 + s02b); path traversal refused; " + rendered
            + "; ElevenLabs text sidecar saved")

@check("Explainer video: a test clip on sentence boundaries, then 'build the rest' around it; HeyGen presenter clips matched to the narration by audio (wrong voiceover refused, upscales verified), shown per slide and composited under the page in renders and stills")
def _():
    import json as _json
    import shutil
    import subprocess
    import tempfile
    import threading as _thr
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415
    import explainer_video as xv  # noqa: PLC0415
    from PIL import Image

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise AssertionError("ffmpeg/ffprobe are needed for this check (brew install ffmpeg)")
    sents = ["AI stocks lost about two point three trillion dollars in one day.",
             "Your index fund probably paid for part of that drop too.",
             "The Nasdaq one hundred fell six point three six percent by the close.",
             "Here is what that means for the money in your retirement account.",
             "First, a correction is a fall of ten percent from a recent peak.",
             "A bear market is a fall of twenty percent or more from that peak.",
             "So far this is a correction and not a bear market at all.",
             "Here is your checklist for the week ahead so you can stay calm."]
    spoken, dur = " ".join(sents), 40.0
    script = "**Talk**\n\n**Host:**\n" + "\n".join(sents) + "\n"
    host_plan = {"summary": "Test.", "sections": [{"key": "c1", "label": "One bad day"}],
                 "slides": [{"id": "s01", "section": "c1", "kind": "scene", "at": "AI stocks lost about", "idea": "Skyline", "logos": [], "host": "left"},
                            {"id": "s02", "section": "c1", "kind": "slide", "at": "Your index fund probably", "idea": "Left panel", "logos": [], "host": "left"},
                            {"id": "s03", "section": "c1", "kind": "slide", "at": "Here is what that means", "idea": "Full", "logos": [], "host": "full"}],
                 "logos": [], "figures": [], "inserts": [], "questions": [], "dropped": []}
    rest_plan = {"summary": "Rest.", "sections": [{"key": "c1", "label": "Renamed?"}, {"key": "c2", "label": "What to do"}],
                 "slides": [{"id": "s04", "section": "c1", "kind": "slide", "at": "Your index fund probably", "idea": "Inside the test: dropped", "logos": [], "host": "none"},
                            {"id": "s05", "section": "c2", "kind": "slide", "at": "So far this is", "idea": "Corner", "logos": [], "host": "pip"},
                            {"id": "s06", "section": "c2", "kind": "asset", "at": "Here is your checklist", "idea": "Checklist", "logos": [], "host": "bogus"}],
                 "logos": [], "figures": [{"key": "peak", "label": "Peak", "value": "10%", "note": "n"}], "inserts": [], "questions": [], "dropped": []}
    markup = {
        "s01": '<section id="s01" data-at="AI stocks lost about" data-kind="scene" data-section="c1"><div class="scene"><svg class="fill" viewBox="0 0 1920 1080"><rect width="1920" height="1080" fill="var(--navy)"/></svg></div></section>',
        "s02": '<section id="s02" data-at="Your index fund probably" data-kind="slide" data-section="c1" data-host="left"><h1 class="h1" style="position:absolute;left:900px;top:300px">Your fund paid</h1></section>',
        "s03": '<section id="s03" data-at="Here is what that means" data-kind="slide" data-section="c1" data-host="full"><div class="lower-third">Retirement</div></section>',
        "s05": '<section id="s05" data-at="So far this is" data-kind="slide" data-section="c2" data-host="pip"><h2 class="h2" style="position:absolute;left:160px;top:200px">Correction</h2></section>',
        "s06": '<section id="s06" data-at="Here is your checklist" data-kind="asset" data-section="c2"><h2 class="h2">Checklist</h2></section>'}
    calls = []

    class _O:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class _Stream:
        def __init__(self, text):
            self.text = text
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def __iter__(self):
            yield _O(type="message_start")
            yield _O(type="content_block_delta", delta=_O(type="text_delta", text=self.text))
        def get_final_message(self):
            return _O(stop_reason="end_turn", content=[_O(type="text", text=self.text)],
                      usage=_O(input_tokens=1000, output_tokens=2000, cache_creation_input_tokens=0, cache_read_input_tokens=0))

    class _Messages:
        def stream(self, **kw):
            calls.append(kw)
            task = kw["messages"][0]["content"][-1]["text"]
            if "format" in kw["output_config"]:
                return _Stream(_json.dumps(rest_plan if "PLAN THE REST" in task else host_plan))
            if task.startswith("TASK: WRITE SLIDES"):
                return _Stream("\n".join(markup[i] for i in re.findall(r"^(s\d+) \(", task, re.M) if i in markup))
            raise AssertionError("unexpected Claude call")

    client = _O(beta=_O(messages=_Messages()))

    def wait(c, pid):
        for _ in range(4000):
            s = c.get(f"/api/explainer/{pid}?title=Talk").get_json()
            if (s.get("job") or {}).get("status") != "running":
                return s
            _thr.Event().wait(0.05)
        raise AssertionError("explainer job never finished")

    def ff(*args):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True)

    # Unit pieces: the level-curve match, the crop maths, segments and the ffmpeg graph.
    a = [abs(((i * 7919) % 97) - 48) for i in range(400)]
    lag, score = xv._best_lag(a, [0.0] * 37 + a + [0.0] * 50)
    assert abs(lag - 37) < 0.01 and score > 0.99, (lag, score)
    assert xv._cover(1920, 1080, 800, 1080, 0.45) == (1920, 1080, 464, 0) and xv._cover(1920, 1080, 544, 306, 0.5)[:2] == (544, 306)
    segs = xv.host_segments({"parts": [{"file": "b", "offset": 20.03, "seconds": 20.0, "w": 1, "h": 1},
                                       {"file": "a", "offset": 0.01, "seconds": 20.04, "w": 1, "h": 1}]})
    assert [(x["file"], x["src"], x["t0"], x["t1"]) for x in segs] == [("a", 0.0, 0.01, 20.05), ("b", 0.02, 20.05, 40.03)], segs
    inputs, graph = xv._host_filter({"k": 2, "W": 3840, "H": 2160, "focus": 0.5, "segments": segs,
                                     "windows": [{"t0": 18.0, "t1": 22.0, "layout": "right"}]}, 15.0, 25.0)
    # Each clip's piece is laid at its own time (a gap between clips would stay black, not shift the next one).
    assert inputs.count("-i") == 2 and "concat" not in graph and graph.count("overlay=2240:0") == 2, graph
    assert "between(t,2.9990,5.0500)" in graph and "between(t,5.0490,7.0000)" in graph and "PTS-STARTPTS+5.0500/TB" in graph, graph
    assert "-reinit_filter" in xv._x264_cmd(Path("x.mp4"), 16)
    with tempfile.TemporaryDirectory() as d:                   # Topaz's H.265 copies are full range: white must stay at TV white
        full = Path(d) / "full.mp4"
        ff("-f", "lavfi", "-i", "color=c=white:s=64x36:r=25:d=1", "-vf", "scale=out_range=pc,format=yuv420p",
           "-color_range", "pc", "-c:v", "libx264", full)
        inputs, graph = xv._host_filter({"k": 0.05, "W": 96, "H": 54, "focus": 0.5, "windows": [{"t0": 0, "t1": 1, "layout": "full"}],
                                         "segments": [{"t0": 0, "t1": 1, "src": 0, "w": 64, "h": 36, "file": str(full)}]}, 0, 1)
        r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=16x16:d=1", *inputs, "-filter_complex",
                            graph.split(";[0:v]")[0] + ";[b1]signalstats,metadata=print:file=-[v]", "-map", "[v]",
                            "-frames:v", "1", "-f", "null", "-"], capture_output=True, text=True)
        ymax = [float(l.split("=")[-1]) for l in r.stdout.splitlines() if "signalstats.YMAX=" in l]
        assert ymax and ymax[0] <= 236, (ymax, r.stderr[-300:])

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        out = d / "out"
        for sub in ("voiceover", "heygen", "aroll", "other"):
            (out / sub).mkdir(parents=True)
        mp3 = out / "voiceover" / "Talk_elevenlabs_Roz_1.mp3"
        expr = "0.5*sin(2*PI*190*t)*gt(sin(2*PI*0.83*t)+sin(2*PI*2.31*t+1.3)+sin(2*PI*0.29*t+0.4),0.2)*lt(mod(t,5),4.6)"
        ff("-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={dur}", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "128k", mp3)
        mp3.with_suffix(".txt").write_text(spoken, encoding="utf-8")
        stem = "Talk_ElevenLabs_20261109_090000"
        for i, (t0, t1, src) in enumerate(((0, 20.0, "testsrc2"), (20.0, dur, "smptebars")), 1):
            ff("-f", "lavfi", "-i", f"{src}=s=640x360:r=25:d={t1 - t0}", "-ss", t0, "-t", t1 - t0, "-i", mp3,
               "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
               out / "heygen" / f"{stem}_part{i}of2.mp4")
        ff("-i", out / "heygen" / f"{stem}_part1of2.mp4", "-vf", "scale=1280:720", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "copy", out / "aroll" / f"{stem}_part1of2_upscaled.mp4")
        ff("-f", "lavfi", "-i", "color=c=red:s=1280x720:r=25:d=20", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           out / "aroll" / "decoy_same_length.mp4")                                  # same length as part 2, not its footage, no audio
        other = out / "other" / "other.mp3"                                           # a different voiceover take, same length
        ff("-f", "lavfi", "-i", f"aevalsrc='0.5*sin(2*PI*240*t)*gt(sin(2*PI*1.7*t+2),0)':s=44100:d={dur}", "-ac", "1", other)
        ff("-f", "lavfi", "-i", f"testsrc=s=640x360:r=25:d={dur}", "-i", other, "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out / "other" / "wrong_take.mp4")
        keep = (web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui._get_run_output_dir, web_gui._get_anthropic_client,
                web_gui._eleven_key, xv.align_words, xv.HOST_MIN_BYTES, os.environ.get("ANTHROPIC_API_KEY"))
        try:
            settings = d / "settings.json"
            settings.write_text("{}")
            web_gui.SCRIPTCRAFT_SETTINGS_PATH = settings
            web_gui._get_run_output_dir = lambda title, create=True: out
            web_gui._get_anthropic_client = lambda timeout=60.0: client
            web_gui._eleven_key = lambda: "sk_test_eleven"
            xv.align_words = lambda audio, text, key, timeout=900: (
                xv.estimate_words(text, dur - 0.4, [(4.6 + 5 * k, 5.0 + 5 * k) for k in range(7)]), 0.1)
            xv.HOST_MIN_BYTES = 0
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
            c = web_gui.app.test_client()

            o = c.get("/api/explainer/options?title=Talk").get_json()
            src = {x["id"]: x for x in o["presenters"]}
            sid = f"set:heygen/{stem}"
            assert sid in src and "file:other/wrong_take.mp4" in src, list(src)
            parts = src[sid]["parts"]
            assert parts[0]["upscale"]["rel"] == f"aroll/{stem}_part1of2_upscaled.mp4", parts[0]
            assert parts[1]["upscale"]["rel"] == "aroll/decoy_same_length.mp4", parts[1]         # found by length, checked on attach
            assert "file:aroll/decoy_same_length.mp4" not in src and abs(src[sid]["seconds"] - dur) < 0.2
            r = c.post("/api/explainer/start", json={"title": "Talk", "voiceover": mp3.name, "script": script, "presenter": "set:nope"}).get_json()
            assert not r["success"] and "no longer" in r["error"], r

            # A presenter from a different voiceover is refused before any Claude call.
            r = c.post("/api/explainer/start", json={"title": "Talk", "voiceover": mp3.name, "script": script,
                                                    "test": {"start": 0, "minutes": 0.5}, "presenter": "file:other/wrong_take.mp4"}).get_json()
            s = wait(c, r["project"])
            assert s["job"]["status"] == "error" and "different voiceover" in s["job"]["error"] and not calls, s["job"]

            # A 30-second test clip with the HeyGen clips.
            r = c.post("/api/explainer/start", json={"title": "Talk", "voiceover": mp3.name, "script": script,
                                                    "test": {"start": 0, "minutes": 0.5}, "presenter": sid, "share": "lots"}).get_json()
            pid = r["project"]
            s = wait(c, pid)
            assert s["job"]["status"] == "done", s["job"]
            proj = out / "explainer" / pid
            span = s["span"]
            assert span[0] == 0 and 27 < span[1] < 34 and s["start"] == 0 and s["end"] == span[1], span
            h = s["host"]
            assert [x["upscaled"] for x in h["parts"]] == [True, False] and h["parts"][0]["w"] == 1280, h["parts"]
            assert abs(h["parts"][0]["offset"]) < 0.06 and abs(h["parts"][1]["offset"] - 20.0) < 0.06 and min(x["score"] for x in h["parts"]) > 0.9, h["parts"]
            assert h["share"] == "lots" and (proj / "host" / "proxy.mp4").is_file() and (proj / "host" / "still.jpg").is_file()
            assert abs(xv.probe_video(proj / "host" / "proxy.mp4")["seconds"] - dur) < 0.2
            plan_call = calls[0]["messages"][0]["content"]
            assert plan_call[1]["type"] == "image" and "PRESENTER VIDEO" in plan_call[2]["text"] and plan_call[2]["cache_control"]
            assert "TASK: PLAN A TEST CLIP" in plan_call[-1]["text"] and "about 50% of the runtime" in plan_call[-1]["text"]
            builds = [k["messages"][0]["content"][-1]["text"] for k in calls if k["messages"][0]["content"][-1]["text"].startswith("TASK: WRITE")]
            assert any('presenter left panel: data-host="left"' in b for b in builds), builds
            meta = {m["id"]: m for m in s["slides"]}
            assert [m["id"] for m in s["slides"]] == ["s01", "s02", "s03"] and meta["s02"]["host"] == "left" and meta["s03"]["host"] == "full"
            assert meta["s01"]["host"] == "" and [w["layout"] for w in s["host_windows"]] == ["left", "full"], s["host_windows"]
            comp = xv.compile_composition('<section id="s01" data-at="AI stocks lost about" data-kind="scene" data-host="full"></section>',
                                          xv.open_project(proj).timeline(), duration=dur, plan={}, logos={}, values={},
                                          logo_choices={}, host_on=True)
            assert any("scene hides the presenter" in w["msg"] for w in comp["slides"][0]["warnings"]), comp["slides"]
            page = c.get(f"/api/explainer/{pid}/preview?title=Talk").get_data(as_text=True)
            assert "media-src 'self'" in page and "host/proxy.mp4" in page and 'class="mode-preview host-on"' in page
            assert c.get(f"/api/explainer/{pid}/file?title=Talk&path=host/proxy.mp4").status_code == 200

            # Per-slide presenter, framing; no Claude call.
            n_calls = len(calls)
            s = c.post(f"/api/explainer/{pid}/layout", json={"title": "Talk", "slide": "s02", "host": "right"}).get_json()
            assert s["current"] == 2 and {m["id"]: m["host"] for m in s["slides"]}["s02"] == "right" and len(calls) == n_calls
            assert c.post(f"/api/explainer/{pid}/layout", json={"title": "Talk", "slide": "s02", "host": "sideways"}).status_code == 400
            s = c.post(f"/api/explainer/{pid}/layout", json={"title": "Talk", "slide": "s02", "host": "left"}).get_json()
            assert 'data-host="left"' in (proj / "versions" / "v003.html").read_text() and (proj / "versions" / "v003.html").read_text().count("data-host") == 2
            s = c.post(f"/api/explainer/{pid}/host", json={"title": "Talk", "focus": 0.3}).get_json()
            assert s["host"]["focus"] == 0.3

            rendered = "renders skipped (no Chrome)"
            if xv.find_chrome():
                # Sample across s02 (left panel): the footage shows in the panel, the page on the right.
                m2 = {m["id"]: m for m in s["slides"]}["s02"]
                r = c.post(f"/api/explainer/{pid}/render", json={"title": "Talk", "kind": "sample", "start": m2["t0"] + 0.6, "seconds": 5}).get_json()
                assert r["success"], r
                s = wait(c, pid)
                assert s["job"]["status"] == "done", s["job"]
                f = proj / s["renders"][-1]["files"][0]["path"]
                assert abs(xv.media_seconds(f) - 5.0) < 0.1
                fr = subprocess.run(["ffmpeg", "-v", "error", "-ss", "2", "-i", str(f), "-frames:v", "1", "-f", "image2pipe",
                                     "-c:v", "png", "-"], capture_output=True).stdout
                im = Image.open(__import__("io").BytesIO(fr)).convert("RGB")
                panel = [im.getpixel((x, 540)) for x in range(40, 760, 60)]
                right = [im.getpixel((x, 900)) for x in range(1000, 1880, 80)]
                assert max(max(p_) - min(p_) for p_ in panel) > 120, panel                 # saturated test pattern = footage
                assert all(max(p_) < 60 for p_ in right), right                           # dark page background
                stills = xv.slide_stills(xv.open_project(proj), ["s02"])
                sim = Image.open(__import__("io").BytesIO(stills["s02"])).convert("RGB")
                assert sim.size == (1280, 720) and max(max(p_) - min(p_) for p_ in (sim.getpixel((x, 360)) for x in range(30, 500, 40))) > 120
                rendered = "sample with the presenter in the left panel; Claude's stills include the presenter"

            # Build the rest: plans around the test clip, keeps its slides, drops a planned slide inside it.
            n_calls = len(calls)
            r = c.post(f"/api/explainer/{pid}/extend", json={"title": "Talk"}).get_json()
            assert r["success"], r
            s = wait(c, pid)
            assert s["job"]["status"] == "done", s["job"]
            assert s["span"] is None and [m["id"] for m in s["slides"]] == ["s01", "s02", "s03", "s05", "s06"], [m["id"] for m in s["slides"]]
            assert s["end"] == round(s["audio_seconds"] + xv.TAIL, 3) and s["versions"][-1]["kind"] == "extend"
            rest_call = calls[n_calls]["messages"][0]["content"]
            assert "TASK: PLAN THE REST" in rest_call[-1]["text"] and "<test_slides>" in rest_call[-2]["text"] and 'id="s02"' in rest_call[-2]["text"]
            plan_now = _json.loads((proj / "plan.json").read_text())
            assert [x["id"] for x in plan_now["slides"]] == ["s01", "s02", "s03", "s05", "s06"] and plan_now["slides"][-1]["host"] == "none"
            assert {x["key"]: x["label"] for x in plan_now["sections"]}["c1"] == "One bad day" and plan_now["figures"][0]["key"] == "peak"
            assert {m["id"]: m["host"] for m in s["slides"]}["s05"] == "pip"
            assert c.post(f"/api/explainer/{pid}/extend", json={"title": "Talk"}).status_code == 400

            # Remove the presenter: data-host stays in the markup but nothing shows.
            s = c.post(f"/api/explainer/{pid}/host", json={"title": "Talk", "source": ""}).get_json()
            assert s["host"] is None and all(not m["host"] for m in s["slides"]) and not s["host_windows"]
            page = c.get(f"/api/explainer/{pid}/preview?title=Talk").get_data(as_text=True)
            assert 'class="mode-preview"' in page and "host/proxy.mp4" not in page
        finally:
            (web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui._get_run_output_dir, web_gui._get_anthropic_client,
             web_gui._eleven_key, xv.align_words, xv.HOST_MIN_BYTES, k) = keep
            if k is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = k
    tl = xv.Timeline(xv.estimate_words(spoken, 39.6, []), 39.6)
    assert xv.pick_span(tl, 0, 600) is None
    a_, b_ = xv.pick_span(tl, 12.0, 10)
    assert 0 < a_ < 12.5 < b_ and b_ - a_ < 25, (a_, b_)
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert 'id="xvHostSel"' in html and 'name="xvBuild"' in html and "async function xvExtend(" in html and "function xvSlideHost(" in html
    return ("30 s test clip ends on a sentence; wrong-voiceover clips refused before Claude; clips placed by audio (upscale of clip 1 "
            "used, same-length decoy rejected); Claude sees the presenter still; per-slide layout without Claude; " + rendered
            + "; the rest planned around the test (slide inside it dropped) and merged; presenter removable")


@check("Explainer video: a phrase spoken twice (an intro that names the chapters) never moves a slide: 'build the rest' searches each slide after the one before it; slides out of order are flagged (and gate the 4K render) and 'Put slides in narration order' fixes them free as a new version")
def _():
    import json as _json
    import tempfile
    from pathlib import Path
    import explainer_video as xv  # noqa: PLC0415

    sents = ["The meter moved and nobody touched it.",                      # 0  s01 c1
             "I am counting three signs of rationing.",                     # 1
             "Sign one. The shrinking plan.",                               # 2  the intro names the chapters
             "Sign two. The admission.",                                    # 3
             "At the end you get a cheat sheet you can copy.",              # 4  s02 c1
             "The menu still says all you can eat.",                        # 5  s03 c1
             "Sign one. The shrinking plan. OpenAI cut the Pro plan in half.",  # 6  s04 c2
             "At two hundred dollars a month the plan got smaller.",        # 7  s05 c2
             "Sign two. The admission. The owner wrote it down.",           # 8  s06 c3
             "On November first the cost problem was in writing."]         # 9  s07 c3
    words, t, starts = [], 0.0, []
    for sent in sents:
        starts.append(round(t, 3))
        for w in sent.split():
            words.append({"text": w, "start": round(t, 3), "end": round(t + 0.3, 3)})
            t += 0.35
        t += 0.6
    dur = round(t + 0.5, 3)
    tl = xv.Timeline(words, dur)
    at = {"s01": "The meter moved and", "s02": "At the end you get", "s03": "The menu still says",
          "s04": "Sign one. The shrinking plan.", "s05": "At two hundred dollars", "s06": "Sign two. The admission.",
          "s07": "On November first the"}
    sec = {"s01": "c1", "s02": "c1", "s03": "c1", "s04": "c2", "s05": "c2", "s06": "c3", "s07": "c3"}
    real = {"s01": 0, "s02": 4, "s03": 5, "s04": 6, "s05": 7, "s06": 8, "s07": 9}
    slides = [{"id": i, "section": sec[i], "kind": "slide", "at": at[i], "idea": i, "logos": [], "host": "none"} for i in at]
    by = {s["id"]: s for s in slides}
    assert tl.find(at["s04"])[0] == starts[2], "the check needs the chapter name spoken first in the intro"

    # 1. Build the rest: Claude's list is in time order; each slide is searched after the one before it.
    a, b = 0.0, starts[1]                                            # test clip = s01 only
    before, after, skipped = xv.place_around([by[i] for i in ("s02", "s03", "s04", "s05", "s06", "s07")], tl, a, b)
    assert not before and not skipped, (before, skipped)
    assert [(s["id"], round(x, 3)) for x, s in after] == [(i, starts[real[i]]) for i in ("s02", "s03", "s04", "s05", "s06", "s07")], after
    a, b = starts[7], starts[8] - 0.05                               # test clip = s05, in the middle
    before, after, skipped = xv.place_around([by[i] for i in ("s01", "s02", "s03", "s04", "s06", "s07")], tl, a, b)
    assert [(s["id"], round(x, 3)) for x, s in before] == [(i, starts[real[i]]) for i in ("s01", "s02", "s03", "s04")], before
    assert [(s["id"], round(x, 3)) for x, s in after] == [("s06", starts[8]), ("s07", starts[9])] and not skipped, after
    before, after, skipped = xv.place_around([by["s05"], by["s03"]], tl, 0.0, starts[1])   # a list out of order still sorts
    assert [s["id"] for _x, s in after] == ["s03", "s05"] and not skipped, after
    _b, _a, skipped = xv.place_around([{"id": "s09", "at": "nothing like this is said"}], tl, 0.0, starts[1])
    assert skipped == ["s09"]

    # 2. Slides out of order (as the old merge left them): flagged on the first squeezed slide, and gating the 4K.
    data_at = dict(at, s04="Sign one. The shrinking plan. OpenAI cut", s06="Sign two. The admission. The owner")

    def markup(order, cues=data_at):
        return "\n".join(f'<section id="{i}" data-at="{cues[i]}" data-kind="slide" data-section="{sec[i]}">'
                         f'<h2 class="h2" data-at="{cues[i]}">{i}</h2></section>' for i in order)

    broken = ["s01", "s04", "s06", "s02", "s03", "s05", "s07"]
    plan = {"summary": "", "sections": [{"key": k, "label": k} for k in ("c1", "c2", "c3")],
            "slides": [by[i] for i in broken], "logos": [], "figures": [], "inserts": [], "questions": [], "dropped": []}
    c = xv.compile_composition(markup(broken), tl, duration=dur, plan=plan, logos={}, values={}, logo_choices={})
    order_w = [w for w in c["warnings"] if w.get("order")]
    assert [w["slide"] for w in order_w] == ["s02"] and "out of order" in order_w[0]["msg"], c["warnings"]
    meta = {m["id"]: m for m in c["slides"]}
    assert meta["s02"]["t0"] > meta["s06"]["t0"] and any(w.get("order") for w in meta["s02"]["warnings"])
    # The narration order: sections in plan order first, so the repeated name lands on the chapter.
    for cues in (data_at, at):
        got = [s["id"] for s in xv.narration_order(xv.split_sections(markup(broken, cues)), tl, plan)]
        assert got == ["s01", "s02", "s03", "s04", "s05", "s06", "s07"], (cues is at, got)
    c = xv.compile_composition(markup(sorted(at)), tl, duration=dur, plan=plan, logos={}, values={}, logo_choices={})
    assert not c["warnings"], c["warnings"]
    assert [round(m["t0"] + xv.LEAD, 2) for m in c["slides"]][1:] == [round(starts[real[i]], 2) for i in sorted(at)][1:], c["slides"]

    # 3. The project: an 'order' item in Needs you, then one free click makes a new version in narration order.
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "versions").mkdir()
        (d / "versions" / "v001.html").write_text(markup(broken), encoding="utf-8")
        (d / "words.json").write_text(_json.dumps(words), encoding="utf-8")
        (d / "plan.json").write_text(_json.dumps(plan), encoding="utf-8")
        (d / "project.json").write_text(_json.dumps({"title": "T", "audio_seconds": dur, "current": 1, "approved": 1,
                                                     "versions": [{"n": 1, "kind": "extend", "note": "", "created": 1, "slides": 7}]}))
        p = xv.Project(d)
        need = [o for o in p.outstanding(p.compile()) if o["type"] == "order"]
        assert need and need[0]["slides"] == ["s02"], need
        n = xv.order_slides(p)
        assert n == 2 and p.data["current"] == 2 and p.data["approved"] is None, (n, p.data)
        assert [s["id"] for s in xv.split_sections(p.composition())] == sorted(at)
        assert [s["id"] for s in p.plan()["slides"]] == sorted(at)
        assert (d / "versions" / "v001.html").read_text(encoding="utf-8") == markup(broken), "the old version is kept"
        v = p.data["versions"][-1]
        assert v["kind"] == "order" and "narration order" in v["note"] and v["slides"] == 7, v
        c = p.compile()
        assert not [w for w in c["warnings"] if w.get("order")] and not [o for o in p.outstanding(c) if o["type"] == "order"]
        assert xv.order_slides(p) is None and p.data["current"] == 2, "already in order: no new version"
        assert v["kind"] not in ("revise", "rebuild") and not xv._test_notes(p), "an order fix is not a note for Claude"

    # 4. Wiring: build the rest uses it, the route and the button exist, and Claude never gets the order warning.
    src = Path(xv.__file__).read_text(encoding="utf-8")
    assert "place_around(new_plan.get(\"slides\") or [], timeline, a, b)" in src
    assert 'not w.get("minor") and not w.get("order")' in src
    gui = (Path(APP) / "web_gui.py").read_text(encoding="utf-8")
    assert '@app.route("/api/explainer/<pid>/order", methods=["POST"])' in gui and "_xv.order_slides(p)" in gui
    html = (Path(APP) / "templates" / "index.html").read_text(encoding="utf-8")
    assert "o.type === 'order'" in html and "async function xvOrder()" in html and "_xvApi('/order')" in html
    assert "!w.minor && !w.order &&" in html, "Fix flagged slides must not send order warnings to Claude"
    return ("chapter names spoken twice land on the chapter (test clip first or in the middle); the squeezed slide is "
            "flagged and gates the 4K; one free click puts 7 slides back in order as v2, the plan follows, v1 kept")


@check("Explainer video: pick clips from your HeyGen account (download the ones not in the folder, refuse other voiceovers), place each on the narration by its audio, and place presenter sections (In/Out + layout) that render, get checked and reach Claude")
def _():
    import io as _io
    import json as _json
    import shutil
    import subprocess
    import tempfile
    import threading as _thr
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415
    import explainer_video as xv  # noqa: PLC0415
    from PIL import Image

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise AssertionError("ffmpeg/ffprobe are needed for this check (brew install ffmpeg)")
    sents = ["AI stocks lost about two point three trillion dollars in one day.",
             "Your index fund probably paid for part of that drop too.",
             "The Nasdaq one hundred fell six point three six percent by the close.",
             "Here is what that means for the money in your retirement account.",
             "First, a correction is a fall of ten percent from a recent peak.",
             "A bear market is a fall of twenty percent or more from that peak.",
             "So far this is a correction and not a bear market at all.",
             "Here is your checklist for the week ahead so you can stay calm."]
    spoken, dur = " ".join(sents), 40.0
    plan = {"summary": "S.", "sections": [{"key": "c1", "label": "One bad day"}],
            "slides": [{"id": "s01", "section": "c1", "kind": "slide", "at": "AI stocks lost about", "idea": "a", "logos": [], "host": "none"},
                       {"id": "s02", "section": "c1", "kind": "slide", "at": "Here is what that means", "idea": "b", "logos": [], "host": "none"},
                       {"id": "s03", "section": "c1", "kind": "slide", "at": "So far this is", "idea": "c", "logos": [], "host": "none"}],
            "logos": [], "figures": [], "inserts": [], "questions": [], "dropped": []}
    markup = {
        "s01": '<section id="s01" data-at="AI stocks lost about" data-kind="slide" data-section="c1"><h1 class="h1" style="position:absolute;left:1000px;top:300px">Lost</h1></section>',
        "s02": '<section id="s02" data-at="Here is what that means" data-kind="slide" data-section="c1"><h1 class="h1" style="position:absolute;left:160px;top:300px">Your account</h1></section>',
        "s03": '<section id="s03" data-at="So far this is" data-kind="slide" data-section="c1"><h2 class="h2">Correction</h2></section>'}
    calls = []

    class _O:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class _Stream:
        def __init__(self, text):
            self.text = text
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def __iter__(self):
            yield _O(type="message_start")
            yield _O(type="content_block_delta", delta=_O(type="text_delta", text=self.text))
        def get_final_message(self):
            return _O(stop_reason="end_turn", content=[_O(type="text", text=self.text)],
                      usage=_O(input_tokens=100, output_tokens=200, cache_creation_input_tokens=0, cache_read_input_tokens=0))

    class _Messages:
        def stream(self, **kw):
            calls.append(kw)
            task = kw["messages"][0]["content"][-1]["text"]
            if "format" in kw["output_config"]:
                return _Stream(_json.dumps(plan))
            if task.startswith("TASK: WRITE SLIDES"):
                return _Stream("\n".join(markup[i] for i in re.findall(r"^(s\d+) \(", task, re.M)))
            if "TASK: REVISE" in task:
                return _Stream('CHANGES: moved right.\n' + markup["s02"].replace("left:160px", "left:900px"))
            raise AssertionError("unexpected Claude call")

    client = _O(beta=_O(messages=_Messages()))

    def wait(c, pid):
        for _ in range(4000):
            s = c.get(f"/api/explainer/{pid}?title=Talk").get_json()
            if (s.get("job") or {}).get("status") != "running":
                return s
            _thr.Event().wait(0.05)
        raise AssertionError("explainer job never finished")

    def ff(*args):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True)

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        out, stage = d / "out", d / "heygen_cloud"
        for sub in ("voiceover", "heygen"):
            (out / sub).mkdir(parents=True)
        stage.mkdir()
        mp3 = out / "voiceover" / "Talk_elevenlabs_Roz_1.mp3"
        expr = "0.5*sin(2*PI*190*t)*gt(sin(2*PI*0.83*t)+sin(2*PI*2.31*t+1.3)+sin(2*PI*0.29*t+0.4),0.2)*lt(mod(t,5),4.6)"
        ff("-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={dur}", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "128k", mp3)
        mp3.with_suffix(".txt").write_text(spoken, encoding="utf-8")
        # In the folder already (made by this app): part 1. In the HeyGen "cloud": part 2 and a chapter clip in another voice.
        for i, (t0, t1, src, dest) in enumerate(((0, 20.0, "testsrc2", out / "heygen" / "Talk_ElevenLabs_20261109_090000_part1of2.mp4"),
                                                 (20.0, dur, "smptebars", stage / "part2.mp4")), 1):
            ff("-f", "lavfi", "-i", f"{src}=s=640x360:r=25:d={t1 - t0}", "-ss", t0, "-t", t1 - t0, "-i", mp3,
               "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", dest)
        ff("-f", "lavfi", "-i", "testsrc=s=640x360:r=25:d=12", "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*300*t)*gt(sin(2*PI*1.3*t),0)':s=44100:d=12",
           "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", stage / "chapter.mp4")
        cloud = [{"id": "vidPart2xyz", "title": "Talk (ElevenLabs audio) part 2 of 2", "duration": 20.0, "status": "completed",
                  "created_at": 1794300000, "thumbnail_url": "https://cdn.example/t2.jpg", "video_url": "https://cdn.example/part2.mp4"},
                 {"id": "vidPart1abc", "title": "Talk (ElevenLabs audio) part 1 of 2", "duration": 20.0, "status": "completed",
                  "created_at": 1794300000, "thumbnail_url": "", "video_url": "https://cdn.example/part1.mp4"},
                 {"id": "vidChapter1", "title": "Talk-Ch1p1", "duration": 12.0, "status": "completed",
                  "created_at": 1794200000, "thumbnail_url": "", "video_url": "https://cdn.example/chapter.mp4"},
                 {"id": "vidRendering", "title": "Talk-Ch2p1", "duration": 0, "status": "processing", "created_at": 1794400000}]
        seen = []

        class _Resp:
            def __init__(self, data, code=200):
                self.status_code, self._d = code, data
            def json(self):
                return self._d

        def fake_get(url, headers=None, params=None, timeout=None, **kw):
            seen.append((url, dict(params or {}), (headers or {}).get("x-api-key")))
            if url.endswith("/v3/videos"):
                q = (params or {}).get("title", "")
                return _Resp({"data": [v for v in cloud if q.lower() in v["title"].lower()], "has_more": False, "next_token": None})
            vid = url.rsplit("/", 1)[-1]
            v = next((x for x in cloud if x["id"] == vid), None)
            return _Resp({"data": v} if v else {"error": {"message": "not found"}}, 200 if v else 404)

        downloads = []

        def fake_download(url, out_path):
            downloads.append(url)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(stage / url.rsplit("/", 1)[-1], out_path)

        keep = (web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui._get_run_output_dir, web_gui._get_anthropic_client,
                web_gui._eleven_key, web_gui._heygen_key, web_gui._hg_download, web_gui.requests.get,
                xv.align_words, xv.HOST_MIN_BYTES, os.environ.get("ANTHROPIC_API_KEY"))
        try:
            settings = d / "settings.json"
            settings.write_text("{}")
            web_gui.SCRIPTCRAFT_SETTINGS_PATH = settings
            web_gui._get_run_output_dir = lambda title, create=True: out
            web_gui._get_anthropic_client = lambda timeout=60.0: client
            web_gui._eleven_key = lambda: "sk_test_eleven"
            web_gui._heygen_key = lambda: "hg-test-key-123456"
            web_gui._hg_download = fake_download
            web_gui.requests.get = fake_get
            xv.align_words = lambda audio, text, key, timeout=900: (
                xv.estimate_words(text, dur - 0.4, [(4.6 + 5 * k, 5.0 + 5 * k) for k in range(7)]), 0.1)
            xv.HOST_MIN_BYTES = 0
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
            c = web_gui.app.test_client()
            r = c.post("/api/explainer/start", json={"title": "Talk", "voiceover": mp3.name, "script": "**Host:**\n" + spoken}).get_json()
            pid = r["project"]
            s = wait(c, pid)
            assert s["job"]["status"] == "done" and s["host"] is None, s["job"]
            assert c.post(f"/api/explainer/{pid}/sections", json={"title": "Talk", "sections": []}).status_code == 400

            # Browse: the part already in the folder is marked; nothing leaks the key.
            g = c.get(f"/api/explainer/heygen-videos?title=Talk&pid={pid}&q=Talk").get_json()
            assert g["success"] and seen[-1][1] == {"limit": 50, "title": "Talk"} and seen[-1][2] == "hg-test-key-123456"
            vids = {v["id"]: v for v in g["videos"]}
            assert vids["vidPart1abc"]["local"] == "heygen/Talk_ElevenLabs_20261109_090000_part1of2.mp4" and vids["vidPart2xyz"]["local"] == ""
            assert vids["vidRendering"]["status"] == "processing" and "hg-test-key" not in _json.dumps(g)
            assert c.post(f"/api/explainer/{pid}/heygen-add", json={"title": "Talk", "ids": ["../etc"]}).status_code == 400

            # Add part 2 (downloaded) and the chapter clip (another voice: refused), placed anywhere in the narration.
            r = c.post(f"/api/explainer/{pid}/heygen-add", json={"title": "Talk", "ids": ["vidPart2xyz", "vidChapter1"]}).get_json()
            assert r["success"], r
            s = wait(c, pid)
            assert (s.get("job") or {}).get("status") == "done", s
            assert downloads == ["https://cdn.example/part2.mp4", "https://cdn.example/chapter.mp4"], downloads
            man = _json.loads((out / "heygen" / "heygen_videos.json").read_text())
            assert set(man) == {"vidPart2xyz", "vidChapter1"} and (out / "heygen" / man["vidPart2xyz"]["file"]).is_file()
            h = s["host"]
            assert len(h["parts"]) == 1 and abs(h["parts"][0]["offset"] - 20.0) < 0.06 and h["parts"][0]["score"] > 0.9, h["parts"]
            assert len(h["refused"]) == 1 and "different voiceover" in h["refused"][0] and "added" in s["job"]["message"], (h["refused"], s["job"])
            assert h["coverage"] == [[20.0, 40.0]] or [list(x) for x in h["coverage"]] == [[20.0, 40.0]], h["coverage"]
            g = c.get(f"/api/explainer/heygen-videos?title=Talk&pid={pid}&q=part").get_json()
            assert {v["id"]: v["in_video"] for v in g["videos"]} == {"vidPart2xyz": True, "vidPart1abc": False}
            # Adding part 1 uses the copy in the folder: no download.
            r = c.post(f"/api/explainer/{pid}/heygen-add", json={"title": "Talk", "ids": ["vidPart1abc"]}).get_json()
            s = wait(c, pid)
            assert len(downloads) == 2 and len(s["host"]["parts"]) == 2 and abs(s["host"]["parts"][0]["offset"]) < 0.06, s["host"]["parts"]
            r = c.post(f"/api/explainer/{pid}/host", json={"title": "Talk", "remove": "Talk_ElevenLabs_20261109_090000_part1of2.mp4"}).get_json()
            s = wait(c, pid)
            assert [p_["orig"] for p_ in s["host"]["parts"]] == [man["vidPart2xyz"]["file"]], s["host"]["parts"]

            # Sections: In/Out + layout; one with no footage gets a warning; approval cleared.
            c.post(f"/api/explainer/{pid}/approve", json={"title": "Talk"})
            r = c.post(f"/api/explainer/{pid}/sections", json={"title": "Talk", "sections": [
                {"t0": 22.0, "t1": 27.0, "layout": "left"}, {"t0": 5, "t1": 8, "layout": "full"},
                {"t0": 30, "t1": 30.2, "layout": "pip"}, {"t0": 1, "t1": 3, "layout": "sideways"}]}).get_json()
            assert r["success"] and r["approved"] is None and "0:05" in r.get("warning", ""), r.get("warning")
            assert r["host"]["sections"] == [{"t0": 5.0, "t1": 8.0, "layout": "full"}, {"t0": 22.0, "t1": 27.0, "layout": "left"}]
            m2 = {m["id"]: m for m in r["slides"]}["s02"]
            assert m2["sections"] == [{"t0": 22.0, "t1": 27.0, "layout": "left"}] and m2["t0"] < 22 < 27 < m2["t1"], m2
            assert {"t0": 22.0, "t1": 27.0, "layout": "left"} in r["host_windows"]
            page = c.get(f"/api/explainer/{pid}/preview?title=Talk").get_data(as_text=True)
            assert '"sections": [{"t0": 5.0' in page and '"fade": 0.3' in page
            assert "user places the presenter themselves" in xv._host_guide({"share": "mine", "parts": [1]})

            rendered = "renders skipped (no Chrome)"
            proj = xv.open_project(out / "explainer" / pid)
            if xv.find_chrome():
                r = c.post(f"/api/explainer/{pid}/render", json={"title": "Talk", "kind": "sample", "start": 22.5, "seconds": 5}).get_json()
                s = wait(c, pid)
                assert s["job"]["status"] == "done", s["job"]
                f = proj.dir / s["renders"][-1]["files"][0]["path"]
                im = Image.open(_io.BytesIO(subprocess.run(["ffmpeg", "-v", "error", "-ss", "2", "-i", str(f), "-frames:v", "1",
                                                            "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True).stdout)).convert("RGB")
                panel = [im.getpixel((x, 800)) for x in range(40, 760, 60)]
                assert max(max(p_) - min(p_) for p_ in panel) > 100, panel          # colour bars: the presenter clip
                assert max(im.getpixel((1500, 800))) < 60                            # the page on the right
                # The layout check sees the section over s02's headline.
                comp = proj.compile()
                page_f = xv.write_page(proj, comp, "render", "check.html")

                async def _chk():
                    exe, hn = xv.find_chrome()
                    async with xv._Chrome(exe, hn) as ch:
                        await ch.open(page_f, 1, transparent=True)
                        return await ch.evaluate("JSON.stringify(window.__check())")
                import asyncio as _asyncio
                issues = {x["id"]: x["issues"] for x in _json.loads(_asyncio.run(_chk()))}
                assert any("covers the presenter" in i for i in issues.get("s02", [])), issues           # left section 22-27 s
                assert any("covers the presenter" in i for i in issues.get("s01", [])), issues           # full section 5-8 s
                assert not any("presenter" in i for i in issues.get("s03", [])), issues                  # no section
                rendered = "sample shows the clip in the section's left panel; the layout check flags the headlines under both sections"
            # The user puts the presenter on s02, on a laptop (the slide's 🧑‍💼 menu).
            assert c.post(f"/api/explainer/{pid}/layout", json={"title": "Talk", "slide": "s02", "host": "nope"}).status_code == 400
            r = c.post(f"/api/explainer/{pid}/layout", json={"title": "Talk", "slide": "s02", "host": "pip:laptop"}).get_json()
            assert r["success"] and [(m["host"], m["frame"]) for m in r["slides"] if m["id"] == "s02"] == [("pip", "laptop")], r
            assert proj.data["host_picks"]["s02"]["host"] == "pip:laptop"
            # Claude's revision of s02 is told about the section and about the user's presenter. The
            # fake Claude drops the presenter (as the real one did, citing "no avatar" in the script's
            # notes); the app puts it back.
            r = c.post(f"/api/explainer/{pid}/revise", json={"title": "Talk", "feedback": "", "scope": "slides", "slides": ["s02"],
                                                              "see": False, "warnings": {"s02": ["“Your account” covers the presenter"]}}).get_json()
            s = wait(c, pid)
            task = calls[-1]["messages"][0]["content"][-1]["text"]
            assert s["job"]["status"] == "done" and "PRESENTER SECTIONS the user placed on this slide" in task and "left panel 22.0-27.0 s" in task, task[-600:]
            assert "the user placed the presenter on this slide (corner window on a laptop)" in task, task[-900:]
            assert 'Keep data-host="pip" data-frame="laptop"' in task and "Never remove it" in task
            assert "never remove or change its data-host" in calls[-1]["system"][0]["text"]
            assert "left:900px" in proj.composition()                                   # Claude's change is kept
            assert [(m["host"], m["frame"]) for m in s["slides"] if m["id"] == "s02"] == [("pip", "laptop")], s["slides"]
            assert "Presenter kept where you placed it: s02" in proj.data["versions"][-1]["note"], proj.data["versions"][-1]
            r = c.post(f"/api/explainer/{pid}/host", json={"title": "Talk", "remove": man["vidPart2xyz"]["file"]}).get_json()
            s = wait(c, pid)
            assert s["host"] is None and not s["host_windows"]
        finally:
            (web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui._get_run_output_dir, web_gui._get_anthropic_client,
             web_gui._eleven_key, web_gui._heygen_key, web_gui._hg_download, web_gui.requests.get,
             xv.align_words, xv.HOST_MIN_BYTES, k) = keep
            if k is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = k
    segs = xv.host_segments({"parts": [{"file": "a", "offset": 0.0, "seconds": 10.0, "w": 1, "h": 1},
                                       {"file": "b", "offset": 8.0, "seconds": 10.0, "w": 1, "h": 1},
                                       {"file": "c", "offset": 18.1, "seconds": 5.0, "w": 1, "h": 1},
                                       {"file": "d", "offset": 30.0, "seconds": 5.0, "w": 1, "h": 1}]})
    assert [(x["file"], x["src"], x["t0"], x["t1"]) for x in segs] == [("a", 0.0, 0.0, 10.0), ("b", 2.0, 10.0, 18.1),
                                                                      ("c", 0.0, 18.1, 23.1), ("d", 0.0, 30.0, 35.0)], segs
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert "function xvHgOpen(" in html and "async function xvSecAdd(" in html and 'id="xvMarks"' in html and 'value="mine"' in html
    return ("HeyGen list marks the copy in the folder; part 2 downloaded and placed at 20 s by its audio, the chapter clip "
            "(another voice) refused, part 1 added from the folder without a download, a clip removed; sections cleaned, "
            "the one without footage warned, approval cleared; " + rendered + "; Claude's revision brief names the section "
            "and the presenter the user put on a slide (on a laptop), which stays when Claude's rewrite drops it")


@check("Explainer video: upscaled presenter clips under any file name are found by length and checked by audio or frames, even when clips of a set are the same length; Rescan works for any presenter footage; adding an upscale as a clip replaces the original")
def _():
    import json as _json
    import shutil
    import subprocess
    import tempfile
    import threading as _thr
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415
    import explainer_video as xv  # noqa: PLC0415

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise AssertionError("ffmpeg/ffprobe are needed for this check (brew install ffmpeg)")

    def ff(*args):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True)

    logs = []
    log = lambda msg, level="info": logs.append(msg)
    status = lambda stage=None, message=None, progress=None: None
    keep_min = xv.HOST_MIN_BYTES
    try:
        xv.HOST_MIN_BYTES = 0
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for sub in ("voiceover", "heygen", "aroll"):
                (root / sub).mkdir()
            mp3 = root / "voiceover" / "Talk_elevenlabs_Roz_1.mp3"
            expr = "0.5*sin(2*PI*190*t)*gt(sin(2*PI*0.83*t)+sin(2*PI*2.31*t+1.3)+sin(2*PI*0.29*t+0.4),0.2)*lt(mod(t,5),4.6)"
            ff("-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d=30", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "128k", mp3)
            stem = "Talk_ElevenLabs_20261109_100000"
            # Three clips of exactly the same length (10 s), each a different picture.
            for i, src in enumerate(("testsrc2", "smptebars", "rgbtestsrc"), 1):
                ff("-f", "lavfi", "-i", f"{src}=s=640x360:r=25:d=10", "-ss", 10 * (i - 1), "-t", 10, "-i", mp3, "-map", "0:v",
                   "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", root / "heygen" / f"{stem}_part{i}of3.mp4")
            woman = root / "aroll" / "Woman speaking into microphone.mp4"       # upscale of clip 3, renamed, with audio
            ff("-i", root / "heygen" / f"{stem}_part3of3.mp4", "-vf", "scale=1280:720", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", woman)
            man = root / "aroll" / "Man at a desk.mp4"                           # upscale of clip 2, renamed, no audio
            ff("-i", root / "heygen" / f"{stem}_part2of3.mp4", "-vf", "scale=1280:720", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", man)

            def project(name):
                folder = root / "explainer" / name
                folder.mkdir(parents=True)
                proj = xv.Project(folder)
                xv.normalize_audio(mp3, folder / "narration.wav", folder / "narration.m4a")
                proj.data.update(title="Talk", audio_seconds=30.0)
                proj.save()
                return proj

            names = lambda h: [Path(x["file"]).name for x in h["parts"]]
            # 1. The set from setup: both upscales end up on the right clips (a wrong guess is checked and passed on).
            src = next(x for x in xv.find_host_sources(root, [30.0]) if x["id"].startswith("set:"))
            assert all(len(p_["upscales"]) == 2 for p_ in src["parts"][1:]), src["parts"]
            h = xv.attach_host(project("p1"), src, root, status, log)
            assert names(h) == [f"{stem}_part1of3.mp4", man.name, woman.name], names(h)
            assert [x["upscaled"] for x in h["parts"]] == [False, True, True] and h["parts"][2]["h"] == 720
            assert abs(h["parts"][2]["offset"] - 20.0) < 0.06 and abs(h["parts"][1]["offset"] - 10.0) < 0.06, h["parts"]
            # 2. Clips added one by one (as from HeyGen), then Rescan.
            p2 = project("p2")
            items = [xv.clip_item(root / "heygen" / f"{stem}_part{i}of3.mp4", []) for i in (1, 2, 3)]
            h = xv.attach_clips(p2, items, status, log)
            assert names(h) == [f"{stem}_part{i}of3.mp4" for i in (1, 2, 3)] and not any(x["upscaled"] for x in h["parts"])
            r = xv.rescan_upscales(p2, root, status, log)
            assert r == {"changed": 2, "upscaled": 2, "clips": 3}, r
            assert names(p2.host()) == [f"{stem}_part1of3.mp4", man.name, woman.name], names(p2.host())
            assert xv.rescan_upscales(p2, root, status, log)["changed"] == 0
            proxy = xv.host_segments(p2.host(), originals=True)
            assert [Path(x["file"]).name for x in proxy] == [f"{stem}_part{i}of3.mp4" for i in (1, 2, 3)]
            # An upscale that is deleted falls back to the original on the next Rescan.
            man.rename(root / "Man at a desk (moved).mov.bak")
            r = xv.rescan_upscales(p2, root, status, log)
            assert r["changed"] == 1 and names(p2.host())[1] == f"{stem}_part2of3.mp4", (r, names(p2.host()))
            # 3. Adding the upscale itself as a clip (e.g. downloaded under its new name) replaces clip 3.
            p3 = project("p3")
            xv.attach_clips(p3, items, status, log)
            h = xv.attach_clips(p3, [xv.clip_item(woman, [])], status, log)
            assert len(h["parts"]) == 3 and names(h)[2] == woman.name and h["parts"][2]["upscaled"], names(h)
            assert any("used in its place" in n for n in h["notes"]), h["notes"]
            # The rescan route on a project whose clips came one by one.
            keep = (web_gui._get_run_output_dir, web_gui.SCRIPTCRAFT_SETTINGS_PATH)
            try:
                web_gui._get_run_output_dir = lambda title, create=True: root
                settings = root / "settings.json"
                settings.write_text("{}")
                web_gui.SCRIPTCRAFT_SETTINGS_PATH = settings
                c = web_gui.app.test_client()
                p4 = project("20261109_100000_abcd")
                xv.attach_clips(p4, items, status, log)
                r = c.post("/api/explainer/20261109_100000_abcd/host", json={"title": "Talk", "rescan": True}).get_json()
                assert r["success"], r
                for _ in range(2000):
                    st = c.get("/api/explainer/20261109_100000_abcd?title=Talk").get_json()
                    if (st.get("job") or {}).get("status") != "running":
                        break
                    _thr.Event().wait(0.05)
                assert st["job"]["status"] == "done" and "1 clip(s) switched" in st["job"]["message"], st["job"]
                assert [x["upscaled"] for x in st["host"]["parts"]] == [False, False, True]
            finally:
                web_gui._get_run_output_dir, web_gui.SCRIPTCRAFT_SETTINGS_PATH = keep
    finally:
        xv.HOST_MIN_BYTES = keep_min
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert "async function xvHostRescan(" in html and "any name; it must be the same length" in html
    return ("three same-length clips: the renamed upscales land on clips 2 and 3 (one by audio, one by frames); Rescan "
            "upgrades clips added one by one and reverts a deleted upscale; an upscale added as a clip replaces the original; "
            "the preview copy keeps using the originals")


@check("Topaz 4K upscales over HTTP: create (estimate) → accept → multipart upload → complete → poll → download; the Explainer quotes then upscales presenter clips and swaps the 4K copies in by audio; the key lives in API Keys")
def _():
    import json as _json
    import shutil
    import subprocess
    import tempfile
    import threading as _thr
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import requests as _rq
    import web_gui  # noqa: PLC0415
    import explainer_video as xv  # noqa: PLC0415

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise AssertionError("ffmpeg/ffprobe are needed for this check (brew install ffmpeg)")

    def ff(*args):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True)

    logs = []
    log = lambda msg, level="info": logs.append(msg)
    status = lambda stage=None, message=None, progress=None: None
    with tempfile.TemporaryDirectory() as d:
        root, cloud = Path(d) / "script", Path(d) / "cloud"      # what "Topaz" sends back lives outside the script folder
        for sub in ("voiceover", "heygen"):
            (root / sub).mkdir(parents=True)
        cloud.mkdir()
        mp3 = root / "voiceover" / "Talk_elevenlabs_Roz_1.mp3"
        expr = "0.5*sin(2*PI*190*t)*gt(sin(2*PI*0.83*t)+sin(2*PI*2.31*t+1.3)+sin(2*PI*0.29*t+0.4),0.2)*lt(mod(t,5),4.6)"
        ff("-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d=20", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "128k", mp3)
        stem = "Talk_ElevenLabs_20261109_110000"
        for i, src in enumerate(("testsrc2", "smptebars"), 1):
            ff("-f", "lavfi", "-i", f"{src}=s=640x360:r=25:d=10", "-ss", 10 * (i - 1), "-t", 10, "-i", mp3, "-map", "0:v",
               "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", root / "heygen" / f"{stem}_part{i}of2.mp4")
            ff("-i", root / "heygen" / f"{stem}_part{i}of2.mp4", "-vf", "scale=1280:720", "-c:v", "libx264", "-pix_fmt",
               "yuv420p", "-c:a", "copy", cloud / f"up{i}.mp4")         # what "Topaz" sends back
        calls, polls = [], {}

        class _R:
            def __init__(self, code=200, data=None, headers=None, body=b""):
                self.status_code, self._d, self.headers, self._b, self.text = code, data, headers or {}, body, ""
            def json(self):
                return self._d
            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(self.status_code)
            def iter_content(self, chunk_size=1):
                yield self._b
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        state = {"n": 0, "urls": 1, "key": "tpz-test-key-0001"}

        def fake_post(url, headers=None, json=None, timeout=None, **kw):
            calls.append(("POST", url, json, (headers or {}).get("X-API-Key")))
            if (headers or {}).get("X-API-Key") != state["key"]:
                return _R(401, {"message": "invalid key"})
            state["n"] += 1
            # Remember which clip this request is for (by its size), to send back its own upscale.
            size = (json or {}).get("source", {}).get("size")
            state.setdefault("src", {})[f"rq{state['n']}"] = next(
                (i for i in (1, 2) if (root / "heygen" / f"{stem}_part{i}of2.mp4").stat().st_size == size), 1)
            return _R(200, {"requestId": f"rq{state['n']}", "estimates": {"cost": [7, 9], "time": [60, 90]}})

        def fake_patch(url, headers=None, json=None, timeout=None, **kw):
            calls.append(("PATCH", url, json, None))
            if url.endswith("/accept") and state.get("accept_fails"):     # e.g. 425 "Credit refill in progress"
                code = state["accept_fails"].pop(0)
                return _R(code, {"message": "Insufficient credits" if code == 402 else "Credit refill in progress"})
            if url.endswith("/accept"):      # the real API answers 202 Accepted, with an uploadId
                return _R(202, {"uploadId": "MTc5", "urls": [f"https://upload.example/{url.split('/')[-2]}/{k}" for k in range(1, state["urls"] + 1)]})
            if state.get("unquoted") and any(u["eTag"].startswith('"') for u in (json or {}).get("uploadResults", [])):
                return _R(400, {"message": "bad eTag https://upload.example/secret?X-Amz-Signature=abc"})
            return _R(202, {"message": "queued"})

        def fake_put(url, data=None, headers=None, timeout=None, **kw):
            calls.append(("PUT", url, len(data or b""), (headers or {}).get("Content-Type")))
            if state.get("put_fail"):
                return _R(500)
            return _R(200, headers={"ETag": f'"etag-{url.rsplit("/", 1)[-1]}"'})

        def fake_delete(url, headers=None, timeout=None, **kw):
            calls.append(("DELETE", url, None, None))
            return _R(204)

        def fake_get(url, headers=None, timeout=None, stream=False, **kw):
            if url == xv.TOPAZ_BALANCE:
                return _R(200, {"available_credits": state.get("balance", 300), "reserved_credits": 0, "total_credits": 300})
            if url.startswith("https://dl.example/"):
                if state.get("dl_fails"):
                    state["dl_fails"] -= 1
                    raise _rq.exceptions.ConnectionError(f"Max retries exceeded with url: {url}?X-Amz-Signature=abc")
                return _R(200, body=(cloud / url.rsplit("/", 1)[-1]).read_bytes())
            if state.get("status_fails"):
                state["status_fails"] -= 1
                raise _rq.exceptions.ReadTimeout("HTTPSConnectionPool(host='api.topazlabs.com', port=443): Read timed out. (read timeout=60)")
            rid = url.split("/")[-2]
            polls[rid] = polls.get(rid, 0) + 1
            if polls[rid] == 1:
                return _R(200, {"status": "processing", "progress": 40})
            return _R(200, {"status": "complete", "download": {"url": f"https://dl.example/up{state['src'][rid]}.mp4", "expiresIn": 604800}})

        keep = (_rq.post, _rq.patch, _rq.put, _rq.get, _rq.delete, xv.TOPAZ_POLL_SECONDS, xv.HOST_MIN_BYTES, xv.TOPAZ_PART_BYTES,
                xv.TOPAZ_RETRY_WAITS, xv.TOPAZ_DOWNLOAD_WAITS, xv.TOPAZ_OFFLINE_MAX)
        try:
            _rq.post, _rq.patch, _rq.put, _rq.get, _rq.delete = fake_post, fake_patch, fake_put, fake_get, fake_delete
            xv.TOPAZ_POLL_SECONDS, xv.HOST_MIN_BYTES = 0.01, 0
            xv.TOPAZ_RETRY_WAITS, xv.TOPAZ_DOWNLOAD_WAITS = (0.01, 0.01, 0.01), (0.01, 0.01)
            # 1. One upscale, multipart: three upload URLs → three parts that add up to the file.
            src = root / "heygen" / f"{stem}_part1of2.mp4"
            state["urls"] = 3
            xv.TOPAZ_PART_BYTES = 1 << 30
            r = xv.topaz_upscale(state["key"], src, xv.topaz_out_path(src), status, None, log)
            post = next(c for c in calls if c[0] == "POST")
            body = post[2]
            assert post[1] == "https://api.topazlabs.com/video/" and body["filters"] == [{"model": "slp-2.6"}]
            assert body["output"]["videoEncoder"] == "H265" and body["output"]["videoProfile"] == "Main10"
            assert body["source"]["resolution"] == {"width": 640, "height": 360} and body["source"]["frameCount"] == 250
            assert body["source"]["size"] == src.stat().st_size and body["source"]["frameRate"] == 25
            assert body["output"]["resolution"] == {"width": 3840, "height": 2160} and body["output"]["audioTransfer"] == "Copy"
            puts = [c for c in calls if c[0] == "PUT"]
            assert len(puts) == 3 and sum(c[2] for c in puts) == src.stat().st_size and puts[0][3] == "video/mp4", puts
            done = next(c for c in calls if c[0] == "PATCH" and "complete-upload" in c[1])
            assert done[1].endswith("/rq1/complete-upload/") and [u["partNum"] for u in done[2]["uploadResults"]] == [1, 2, 3]
            assert done[2]["uploadResults"][0]["eTag"] == '"etag-1"'
            assert r["estimate"] == {"estimates.cost": [7, 9]} and Path(r["out"]).name == f"{stem}_part1of2_starlight4k.mp4"
            assert xv.probe_video(Path(r["out"]))["h"] == 720 and polls["rq1"] == 2
            Path(r["out"]).unlink()
            # A bad key is reported plainly.
            try:
                xv.topaz_upscale("wrong", src, xv.topaz_out_path(src), status, None, log)
                raise AssertionError("bad key accepted")
            except RuntimeError as e:
                assert "Topaz rejected the API key (401)" in str(e), e
            assert xv.topaz_quote(300, 25) == {"credits": 630, "dollars": 41.79}        # Starlight Precise 2.6
            assert xv.topaz_quote(300, 25, "iris-2") == {"credits": 121, "dollars": 8.03}
            # Iris still sends its "auto" setting and keeps the old file name.
            r = xv.topaz_upscale(state["key"], src, xv.topaz_out_path(src, "iris-2"), status, None, log, model="iris-2")
            assert [c for c in calls if c[0] == "POST"][-1][2]["filters"] == [{"model": "iris-2", "auto": "Auto"}]
            assert Path(r["out"]).name == f"{stem}_part1of2_topaz4k.mp4"
            Path(r["out"]).unlink()
            # Which clips a model would upscale: not 4K yet, or a copy from a lesser Topaz model;
            # an upscale made elsewhere (HeyGen) is kept.
            hz = {"parts": [{"file": "/f/a_topaz4k.mp4", "orig": "/f/a.mp4", "h": 2160},
                            {"file": "/f/b_starlight4k.mp4", "orig": "/f/b.mp4", "h": 2160},
                            {"file": "/f/Woman hosting a podcast.mp4", "orig": "/f/c.mp4", "h": 2160},
                            {"file": "/f/d.mp4", "orig": "/f/d.mp4", "h": 1080}]}
            assert [Path(x["orig"]).name for x in xv.topaz_todo(hz)] == ["a.mp4", "d.mp4"]
            assert [Path(x["orig"]).name for x in xv.topaz_todo(hz, "slf-3")] == ["a.mp4", "d.mp4"]
            assert [Path(x["orig"]).name for x in xv.topaz_todo(hz, "iris-2")] == ["d.mp4"]
            assert [xv.topaz_model_of(x["file"]) for x in hz["parts"]] == ["iris-2", "slp-2.6", None, None]
            # Two same-length 4K copies named after the clip: the newer one (the redo) wins.
            vids = [{"path": Path("/f/a_topaz4k.mp4"), "seconds": 10.0, "h": 2160, "mtime": 1},
                    {"path": Path("/f/a_starlight4k.mp4"), "seconds": 10.0, "h": 2160, "mtime": 2}]
            assert xv.best_upscale({"path": "/f/a.mp4", "seconds": 10.0, "h": 1080}, vids, set())["path"].name == "a_starlight4k.mp4"
            # Storage that wants the ETag without quotes: one retry, unquoted; links never reach the message.
            state["unquoted"], state["urls"] = True, 1
            r = xv.topaz_upscale(state["key"], src, xv.topaz_out_path(src), status, None, log)
            last = [c for c in calls if c[0] == "PATCH" and "complete-upload" in c[1]][-1]
            assert last[2]["uploadResults"][0]["eTag"] == "etag-1" and any("unquoted" in m for m in logs)
            Path(r["out"]).unlink()
            state["unquoted"] = False
            e400 = xv._topaz_error(_R(400, {"message": "bad https://x.example/a?X-Amz-Signature=abc"}))
            assert "X-Amz" not in e400 and "<link>" in e400, e400
            # A failed upload cancels the request so its reserved credits are released.
            state["put_fail"] = True
            try:
                xv.topaz_upscale(state["key"], src, xv.topaz_out_path(src), status, None, log)
                raise AssertionError("upload failure not reported")
            except RuntimeError as e:
                assert "upload failed (500)" in str(e), e
            rid = [c for c in calls if c[0] == "PATCH" and c[1].endswith("/accept")][-1][1].split("/")[-2]
            assert calls[-1] == ("DELETE", f"https://api.topazlabs.com/video/{rid}", None, None), calls[-1]
            state["put_fail"] = False
            assert xv.topaz_balance(state["key"])["available_credits"] == 300
            # Retries. "Credit refill in progress" (425) on accept: canceled (nothing spent), a new request
            # after a wait, upscaled.
            out = xv.topaz_out_path(src)
            n_posts, logs[:] = sum(1 for c_ in calls if c_[0] == "POST"), []
            state["accept_fails"] = [425]
            r = xv._topaz_tries(state["key"], src, out, status, None, log, xv.TOPAZ_MODEL)
            assert Path(r["out"]).is_file() and sum(1 for c_ in calls if c_[0] == "POST") == n_posts + 2
            assert any("trying again" in m and "425" in m for m in logs), logs
            out.unlink()
            # "Not enough credits" (402): one more try (an automatic top-up may be under way), then reported;
            # none when an earlier clip already ran out.
            for credit_retry, tries in ((True, 2), (False, 1)):
                n_posts, state["accept_fails"] = sum(1 for c_ in calls if c_[0] == "POST"), [402] * 5
                try:
                    xv._topaz_tries(state["key"], src, out, status, None, log, xv.TOPAZ_MODEL, credit_retry=credit_retry)
                    raise AssertionError("402 not reported")
                except xv.TopazRetry as e:
                    assert e.credits and "not enough credits" in str(e), e
                assert sum(1 for c_ in calls if c_[0] == "POST") == n_posts + tries
            # A status check that times out (what canceled a clip 8 minutes into processing) is waited out:
            # same request, no cancel, logged once.
            state["accept_fails"], state["status_fails"], logs[:] = [], 2, []
            n_posts, n_dels = (sum(1 for c_ in calls if c_[0] == m) for m in ("POST", "DELETE"))
            r = xv._topaz_tries(state["key"], src, out, status, None, log, xv.TOPAZ_MODEL)
            assert Path(r["out"]).is_file() and sum(1 for c_ in calls if c_[0] == "POST") == n_posts + 1
            assert sum(1 for c_ in calls if c_[0] == "DELETE") == n_dels
            assert sum("still waiting" in m for m in logs) == 1 and any("answering again" in m for m in logs), logs
            out.unlink()
            # ... but not forever: then the request is canceled and the error says Topaz stopped answering.
            xv.TOPAZ_OFFLINE_MAX, state["status_fails"] = -1, 1
            try:
                xv._topaz_tries(state["key"], src, out, status, None, log, xv.TOPAZ_MODEL)
                raise AssertionError("an unanswered status check was not reported")
            except RuntimeError as e:
                assert "did not answer" in str(e) and not isinstance(e, xv.TopazRetry), e
            assert calls[-1][0] == "DELETE" and not out.exists()
            xv.TOPAZ_OFFLINE_MAX, state["status_fails"] = keep[-1], 0
            # A dropped download of a finished (paid) upscale is downloaded again; its link stays out of the log.
            state["dl_fails"], logs[:] = 2, []
            r = xv._topaz_tries(state["key"], src, out, status, None, log, xv.TOPAZ_MODEL)
            assert Path(r["out"]).is_file() and sum("Download" in m and "trying again" in m for m in logs) == 2, logs
            assert not any("X-Amz" in m for m in logs), logs
            out.unlink()
            # Topaz can't be reached at all: retried, then reported (still a TopazRetry: nothing was spent).
            fp, _rq.post = _rq.post, lambda *a, **k: (_ for _ in ()).throw(_rq.exceptions.ConnectionError("no network"))
            try:
                xv._topaz_tries(state["key"], src, out, status, None, log, xv.TOPAZ_MODEL)
                raise AssertionError("no network not reported")
            except xv.TopazRetry as e:
                assert "Could not reach Topaz" in str(e), e
            finally:
                _rq.post = fp
            assert xv._no_links("Max retries exceeded with url: /b/k?X-Amz-Signature=abc") == "Max retries exceeded with url: <link>"

            # 2. The Explainer: quote, then upscale + swap in (checked by audio).
            state["urls"], state["n"] = 1, 0
            folder = root / "explainer" / "20261109_110000_abcd"
            folder.mkdir(parents=True)
            proj = xv.Project(folder)
            xv.normalize_audio(mp3, folder / "narration.wav", folder / "narration.m4a")
            proj.data.update(title="Talk", audio_seconds=20.0)
            proj.save()
            xv.attach_clips(proj, [xv.clip_item(root / "heygen" / f"{stem}_part{i}of2.mp4", []) for i in (1, 2)], status, log)
            kkeep = (web_gui._get_run_output_dir, web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui._topaz_key)
            try:
                web_gui._get_run_output_dir = lambda title, create=True: root
                settings = root / "settings.json"
                settings.write_text("{}")
                web_gui.SCRIPTCRAFT_SETTINGS_PATH = settings
                web_gui._topaz_key = lambda: ""
                c = web_gui.app.test_client()
                q = c.post("/api/explainer/20261109_110000_abcd/topaz", json={"title": "Talk"}).get_json()
                assert q["success"] and not q["quote"]["has_key"] and [x["name"] for x in q["quote"]["clips"]] == [f"{stem}_part1of2.mp4", f"{stem}_part2of2.mp4"]
                assert q["quote"]["credits"] == 2 * 21 and q["quote"]["label"] == "Starlight Precise 2.6", q["quote"]
                assert c.post("/api/explainer/20261109_110000_abcd/topaz", json={"title": "Talk", "model": "iris-2"}).get_json()["quote"]["credits"] == 2 * 5
                assert c.post("/api/explainer/20261109_110000_abcd/topaz", json={"title": "Talk", "confirm": True}).status_code == 400
                web_gui._topaz_key = lambda: state["key"]

                def run(body):
                    r = c.post("/api/explainer/20261109_110000_abcd/topaz", json={"title": "Talk", "confirm": True, **body}).get_json()
                    assert r["success"], r
                    for _ in range(3000):
                        st = c.get("/api/explainer/20261109_110000_abcd?title=Talk").get_json()
                        if (st.get("job") or {}).get("status") != "running":
                            return st
                        _thr.Event().wait(0.05)
                    raise AssertionError("topaz job never finished")

                # Out of credits: the first clip gets one more try, the next clip none (no waiting on each).
                n_posts, state["accept_fails"] = sum(1 for c_ in calls if c_[0] == "POST"), [402] * 5
                st = run({})
                assert st["job"]["status"] == "error" and "not enough credits" in st["job"]["error"], st["job"]
                assert sum(1 for c_ in calls if c_[0] == "POST") == n_posts + 3
                state["accept_fails"] = []
                # The balance covers one clip: the quote says which; that one is upscaled.
                state["balance"] = 30
                q = c.post("/api/explainer/20261109_110000_abcd/topaz", json={"title": "Talk"}).get_json()["quote"]
                assert q["available"] == 30 and q["fits"] == [f"{stem}_part1of2.mp4"], q
                # Every upscale failing shows as a failed job, not a ✅.
                state["put_fail"] = True
                st = run({"names": [f"{stem}_part1of2.mp4"]})
                assert st["job"]["status"] == "error" and "Topaz upscale failed for 1 clip(s)" in st["job"]["error"], st["job"]
                state["put_fail"] = False
                st = run({"names": q["fits"]})
                assert st["job"]["status"] == "done" and "1 clip(s) upscaled with Topaz Starlight Precise 2.6; 1 of 2 clip(s) now 4K" in st["job"]["message"], st["job"]
                state["balance"] = 300
                n_posts = sum(1 for c_ in calls if c_[0] == "POST")
                st = run({})                    # the test "4K" copies are 720p, so clip 1 counts again: its copy is reused
                assert st["job"]["status"] == "done" and "2 of 2 clip(s) now 4K" in st["job"]["message"], st["job"]
                assert sum(1 for c_ in calls if c_[0] == "POST") == n_posts + 1      # only clip 2 went to Topaz
                assert [x["name"] for x in st["host"]["parts"]] == [f"{stem}_part1of2_starlight4k.mp4", f"{stem}_part2of2_starlight4k.mp4"], st["host"]["parts"]
                assert [x["topaz"] for x in st["host"]["parts"]] == ["slp-2.6", "slp-2.6"]
                assert all(x["upscaled"] and x["h"] == 720 for x in st["host"]["parts"])
                # 3. The API Keys dialog stores the Topaz key like the others (masked when read back).
                assert c.post("/api/keys", json={"topaz_api_key": "tpz-dialog-key-9876"}).get_json()["updated"] == ["topaz_api_key"]
                kj = c.get("/api/keys").get_json()
                assert kj["keys"]["topaz_api_key"] == "•" * 4 + "9876" and kj["sources"]["topaz_api_key"] == "saved"
                c.post("/api/keys", json={"clear": ["topaz_api_key"]})
            finally:
                web_gui._get_run_output_dir, web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui._topaz_key = kkeep
                os.environ.pop("TOPAZ_API_KEY", None)
        finally:
            (_rq.post, _rq.patch, _rq.put, _rq.get, _rq.delete, xv.TOPAZ_POLL_SECONDS, xv.HOST_MIN_BYTES, xv.TOPAZ_PART_BYTES,
             xv.TOPAZ_RETRY_WAITS, xv.TOPAZ_DOWNLOAD_WAITS, xv.TOPAZ_OFFLINE_MAX) = keep
    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert 'id="modalTopazApiKey"' in html and "setSrc('src_topaz', srcMap.topaz_api_key);" in html
    assert html.count("['modalTopazApiKey','topaz_api_key']") == 2 and "function _xvTopazModelSel(" in html and "async function xvTopaz(" in html
    return ("request body (Starlight Precise 2.6 by default, Iris on request; 3840x2160 10-bit H.265, audio copied, source "
            "frames/size), Iris copies redone by Starlight and the newer copy used, 3-part upload with ETags, polling to the "
            "download; bad key reported; retries (425 refill, 402 once, status timeouts waited out, download again, no "
            "network); Explainer quote without a key, then 2 clips upscaled and swapped in by audio; "
            "Topaz key saved and masked in API Keys")


@check("Topaz 4K copies open in QuickTime and Finder: an H.265 'hev1' download is marked 'hvc1' (streams copied, file time kept)")
def _():
    import inspect  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    import explainer_video as xv  # noqa: PLC0415
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        return "skipped: no ffmpeg"

    def tag(p):
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=codec_tag_string", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
        return r.stdout.strip()

    with tempfile.TemporaryDirectory() as d:
        hev1, h264, junk = Path(d, "up.mp4.part"), Path(d, "plain.mp4"), Path(d, "junk.mp4")
        base = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=1",
                "-f", "lavfi", "-i", "sine=duration=1"]
        subprocess.run(base + ["-c:v", "libx265", "-x265-params", "log-level=none", "-pix_fmt", "yuv420p10le",
                               "-tag:v", "hev1", "-c:a", "aac", "-f", "mp4", str(hev1)], check=True)
        subprocess.run(base + ["-c:v", "libx264", "-c:a", "aac", str(h264)], check=True)
        junk.write_bytes(b"not a video")
        assert tag(hev1) == "hev1", tag(hev1)
        os.utime(hev1, (1_700_000_000, 1_700_000_000))
        seconds, logged = xv.media_seconds(hev1), []
        assert xv.apple_hevc_tag(hev1, lambda *a: logged.append(a)) is True
        assert tag(hev1) == "hvc1" and hev1.stat().st_mtime == 1_700_000_000, (tag(hev1), hev1.stat().st_mtime)
        assert abs(xv.media_seconds(hev1) - seconds) < 0.05 and not logged, logged
        assert xv.apple_hevc_tag(hev1) is False                      # already hvc1: left alone
        size = h264.stat().st_size
        assert xv.apple_hevc_tag(h264) is False and h264.stat().st_size == size and tag(h264) == "avc1"
        assert xv.apple_hevc_tag(junk) is False and junk.read_bytes() == b"not a video"
        assert sorted(p.name for p in Path(d).iterdir()) == ["junk.mp4", "plain.mp4", "up.mp4.part"]
    dl = inspect.getsource(xv._topaz_download)
    assert dl.index("apple_hevc_tag(tmp, log)") < dl.index("tmp.replace(out)"), "retag before the copy is saved"
    return "hev1 → hvc1 with the same length and file time; hvc1, H.264 and unreadable files untouched; the Topaz download retags before saving"


if __name__ == "__main__":
    width = max(len(n) for n, _, _ in RESULTS)
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} checks passed")
    sys.exit(1 if failed else 0)
