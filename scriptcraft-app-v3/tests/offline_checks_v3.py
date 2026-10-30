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
os.environ.setdefault("SCRIPTCRAFT_AGENT_BACKEND", "maf")

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str):
    def deco(fn):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                detail = fn() or ""
            RESULTS.append((name, True, detail))
        except Exception as e:  # noqa: BLE001
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
    web_gui._grok_imagine_assets_for_beat = lambda beat, sec="", title="": (calls.append(beat) or "NEW prompt. style", None)
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
    assert "'demo','title'];" in html and 'data-sps-stage="title"' in html
    assert "window._spsTitlePending = wantsTitle && checkedList.length > 0;" in html
    assert html.count("openTitlePicker(processedScript);") == 1 and "function openTitlePicker(script)" in html
    return "Title: line + top heading replaced, a Title: line added when missing, YouTube A/B titles kept; last stage in the dialog"



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



@check("YouTube thumbnails up to 50 MB (thumbnails.set's limit); a size refusal retries with a JPEG under 2 MB")
def _():
    import io as _io
    import tempfile
    import types as _types
    from pathlib import Path
    from PIL import Image
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415
    import youtube_publisher as yp

    assert yp.MAX_THUMBNAIL_BYTES == 50 * 1024 * 1024 and yp.LEGACY_THUMBNAIL_BYTES == 2 * 1024 * 1024
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        # A noisy 2816x1584 PNG (like a 2K Grok original), well over 2 MB.
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
        small = yp._compressed_thumbnail_copy(big)
        assert small and small.name == "thumb_full_youtube.jpg" and small.stat().st_size <= yp.LEGACY_THUMBNAIL_BYTES
    err = lambda status, body: _types.SimpleNamespace(resp=_types.SimpleNamespace(status=status), content=body.encode())
    assert yp._is_size_rejection(err(413, ""))
    assert yp._is_size_rejection(err(400, '{"error": {"message": "The thumbnail image file is too large."}}'))
    assert not yp._is_size_rejection(err(403, '{"error": {"errors": [{"reason": "forbidden"}]}}'))
    src = open(os.path.join(APP, "youtube_publisher.py"), encoding="utf-8").read()
    assert "_is_size_rejection(big)" in src and "small = _compressed_thumbnail_copy(thumb_path)" in src
    web = open(os.path.join(APP, "web_gui.py"), encoding="utf-8").read()
    assert web.count("yp.MAX_THUMBNAIL_BYTES") >= 3 and "2 * 1024 * 1024:" not in web
    return "5.6 MB thumbnail accepted; a noisy 2K PNG compresses under 2 MB for the fallback; size errors told apart from others"


if __name__ == "__main__":
    width = max(len(n) for n, _, _ in RESULTS)
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} checks passed")
    sys.exit(1 if failed else 0)
