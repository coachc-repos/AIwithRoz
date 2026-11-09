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

@check("HeyGen clips from an ElevenLabs MP3: cut in pauses into clips under the frame limit counted at the upscaler's fps, each rendered with a template's avatar (engine, background) into heygen/, not aRoll/")
def _():
    import json as _json
    import shutil
    import subprocess
    import tempfile
    import threading as _thr
    from pathlib import Path
    os.environ.setdefault("PORT", "0")
    import web_gui  # noqa: PLC0415

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise AssertionError("ffmpeg/ffprobe are needed for this check (brew install ffmpeg)")
    key = "sk_V2_test_heygen_WXYZ9876"
    TPL, LOOK = "92c09f8e9a1c4f078f7ae53886b7ad80", "5fdf87555a1c4320932077baa2c62c37"
    calls = []
    mode = {"status": {}, "engines": ["avatar_v", "avatar_iv"], "busy": 0, "made": 0}

    class _R:
        def __init__(self, status, body=None, content=b""):
            self.status_code, self._b, self.content = status, body, content
            self.text = _json.dumps(body) if body is not None else ""
        def json(self):
            return self._b
        def raise_for_status(self):
            if self.status_code >= 400:
                raise web_gui.requests.exceptions.HTTPError(response=self)
        def iter_content(self, chunk_size=1):
            yield self.content[:3]
            yield self.content[3:]
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    template = {"data": {"id": TPL, "name": "Roz in Black Template", "aspect_ratio": "16:9", "variables": {},
                         "composition": {"scenes": [{"background": {"color": "#FFFFFF", "type": "color"},
                                                     "elements": [{"type": "avatar", "avatar_id": LOOK, "engine": "avatar_v"}]}]}}}

    def fake_get(url, params=None, headers=None, timeout=None, stream=False):
        calls.append(("GET", url, dict(headers or {}), None))
        if url.endswith("/v3/templates"):
            return _R(200, {"data": [{"id": TPL, "name": "Roz in Black Template"}, {"id": "emptytpl01", "name": "No avatar"}],
                            "has_more": False})
        if url.endswith(f"/v3/templates/{TPL}"):
            return _R(200, template)
        if url.endswith("/v3/templates/emptytpl01"):
            return _R(200, {"data": {"id": "emptytpl01", "name": "No avatar", "composition": {"scenes": [{"elements": []}]}}})
        if url.endswith(f"/v3/avatars/looks/{LOOK}"):
            return _R(200, {"data": {"id": LOOK, "name": "Black Outfit 4K", "avatar_type": "digital_twin",
                                     "supported_api_engines": mode["engines"], "preview_image_url": "https://x/p.jpg"}})
        if "/v3/videos/" in url:
            vid = url.rsplit("/", 1)[1]
            script = mode["status"].setdefault(vid, ["processing", "completed"])
            st = script.pop(0) if script else "completed"
            if st == "failed":
                return _R(200, {"data": {"status": "failed", "failure_message": "Audio too quiet"}})
            return _R(200, {"data": {"status": st, "video_url": f"https://cdn.heygen/{vid}.mp4" if st == "completed" else None}})
        if url.startswith("https://cdn.heygen/"):
            assert stream
            return _R(200, content=b"MP4-" + url.rsplit("/", 1)[1].encode())
        return _R(404, {"error": {"message": "nope"}})

    def fake_post(url, headers=None, json=None, files=None, timeout=None):
        calls.append(("POST", url, dict(headers or {}), json if json is not None else
                      {k: (v[0], v[2]) for k, v in (files or {}).items()}))
        if url.endswith("/v3/assets"):
            return _R(200, {"data": {"asset_id": f"asset{sum(c[1].endswith('/v3/assets') for c in calls)}"}})
        if url.endswith("/v3/videos"):
            if mode["busy"]:
                mode["busy"] -= 1
                return _R(429, {"error": {"message": "Too many concurrent videos"}})
            mode["made"] += 1
            return _R(200, {"data": {"video_id": f"vid{mode['made']}", "status": "waiting"}})
        return _R(404, {"error": {"message": "nope"}})

    def wait_job(c, job_id):
        for _ in range(1000):
            s = c.get(f"/api/heygen/audio-video/{job_id}").get_json()
            if s.get("status") != "running":
                return s
            _thr.Event().wait(0.02)
        raise AssertionError("HeyGen job never finished")

    def tone(path, seconds):
        # 4.4 s of tone, then a 0.6 s pause, every 5 s: the pauses are where cuts may go.
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"aevalsrc='if(lt(mod(t,5),4.4),0.5*sin(2*PI*300*t),0)':s=44100:d={seconds}",
                        "-ac", "1", "-c:a", "libmp3lame", "-b:a", "128k", str(path)], check=True)

    def posts(suffix):
        return [x for x in calls if x[0] == "POST" and x[1].endswith(suffix)]

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        vo = d / "out" / "voiceover"
        vo.mkdir(parents=True)
        (vo / "older.mp3").write_bytes(b"\xff" * 16000)        # unreadable: length estimated at 128 kbps
        short, long_ = vo / "Talk_elevenlabs_Roz_1.mp3", vo / "Talk_elevenlabs_Roz_2.mp3"
        tone(short, 10)
        tone(long_, 30)
        for i, p in enumerate((vo / "older.mp3", short, long_)):
            os.utime(p, (1000 + i, 1000 + i))
        keep = (web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui._get_run_output_dir, web_gui.requests.get,
                web_gui.requests.post, web_gui.time.sleep, os.environ.get("HEYGEN_API_KEY"), web_gui.HEYGEN_AUDIO_MAX_BYTES,
                web_gui._video_frames, web_gui._plan_clip_cuts)
        try:
            settings = d / "settings.json"
            settings.write_text("{}")
            web_gui.SCRIPTCRAFT_SETTINGS_PATH = settings
            web_gui._get_run_output_dir = lambda title, create=True: d / "out"
            web_gui.requests.get, web_gui.requests.post = fake_get, fake_post
            web_gui.time.sleep = lambda s: None
            os.environ.pop("HEYGEN_API_KEY", None)
            c = web_gui.app.test_client()

            o = c.get("/api/heygen/audio-video/options?title=Talk").get_json()
            assert o["needs_key"] and [f["name"] for f in o["voiceovers"]] == [long_.name, short.name, "older.mp3"], o
            settings.write_text(_json.dumps({"heygen_api_key": key}))

            o = c.get("/api/heygen/audio-video/options?title=Talk")
            oj = o.get_json()
            assert oj["success"] and [t["name"] for t in oj["templates"]] == ["Roz in Black Template", "No avatar"]
            secs = {f["name"]: f["seconds"] for f in oj["voiceovers"]}
            assert abs(secs[long_.name] - 30) < 0.1 and abs(secs[short.name] - 10) < 0.1 and secs["older.mp3"] == 1, secs
            assert (oj["heygen_fps"], oj["count_fps"], oj["max_frames"], oj["max_frames_range"]) == (25, 30, 9000, [250, 108000])
            assert 30 in oj["count_fps_choices"] and 25 in oj["count_fps_choices"] and key not in o.get_data(as_text=True)

            a = c.get(f"/api/heygen/template-avatar/{TPL}").get_json()
            assert a["avatar_id"] == LOOK and a["avatar_name"] == "Black Outfit 4K" and a["engine"] == "avatar_v"
            assert a["background"] == {"type": "color", "value": "#FFFFFF"} and a["aspect_ratio"] == "16:9"
            assert "no avatar" in c.get("/api/heygen/template-avatar/emptytpl01").get_json()["error"]
            assert c.get("/api/heygen/template-avatar/..%2Fx").status_code in (400, 404)

            base = {"title": "Talk", "template_id": TPL, "resolution": "1080p"}
            for bad in ("../older.mp3", "older.wav", "missing.mp3", ""):
                assert c.post("/api/heygen/audio-video", json={**base, "voiceover": bad}).status_code == 400, bad
            assert c.post("/api/heygen/audio-video", json={**base, "voiceover": short.name, "resolution": "8k"}).status_code == 400
            for bad in ({"max_frames": 100}, {"max_frames": 200000}, {"max_frames": "abc"}, {"fps": 31}, {"fps": "x"}):
                assert c.post("/api/heygen/audio-video", json={**base, "voiceover": short.name, **bad}).status_code == 400, bad
                q = {"title": "Talk", "voiceover": short.name, **bad}
                assert c.get("/api/heygen/audio-video/plan", query_string=q).status_code == 400, bad
            web_gui.HEYGEN_AUDIO_MAX_BYTES = 1000                  # one whole-file video must fit HeyGen's upload limit
            assert c.post("/api/heygen/audio-video", json={**base, "voiceover": short.name}).status_code == 400
            web_gui.HEYGEN_AUDIO_MAX_BYTES = keep[6]

            # 10 s fits in one 9,000-frame video: the MP3 goes up whole, as one video.
            calls.clear()
            r = c.post("/api/heygen/audio-video", json={**base, "voiceover": short.name}).get_json()
            assert r["success"] and r["avatar"] == "Black Outfit 4K" and r["clips"] == 1 and abs(r["audio_seconds"] - 10) < 0.1, r
            s = wait_job(c, r["job_id"])
            assert s["status"] == "done" and [p["video_id"] for p in s["parts"]] == ["vid1"], s
            up = posts("/v3/assets")
            assert len(up) == 1 and up[0][3] == {"file": (short.name, "audio/mpeg")} and up[0][2]["x-api-key"] == key
            body = posts("/v3/videos")[0][3]
            assert body == {"type": "avatar", "avatar_id": LOOK, "audio_asset_id": "asset1", "title": "Talk (ElevenLabs audio)",
                            "aspect_ratio": "16:9", "resolution": "1080p", "engine": {"type": "avatar_v"},
                            "background": {"type": "color", "value": "#FFFFFF"}}, body
            out = Path(s["parts"][0]["path"])
            assert out.parent == d / "out" / "heygen" and out.name.startswith("Talk_ElevenLabs_") and out.read_bytes() == b"MP4-vid1.mp4"
            assert not (vo / "clips").exists() and not (d / "out" / "aRoll").exists()
            v = c.get(f"/api/heygen/audio-video/{r['job_id']}/file")
            assert v.status_code == 200 and v.mimetype == "video/mp4"
            v.close()

            # The plan: 30 s with a 300-frame limit is 4 clips counted at 30 fps (9.86 s each at most)
            # but 3 counted at 25 fps (11.84 s); every clip's frames are under the limit.
            q = {"title": "Talk", "voiceover": long_.name, "max_frames": 300}
            p30 = c.get("/api/heygen/audio-video/plan", query_string=q).get_json()
            p25 = c.get("/api/heygen/audio-video/plan", query_string={**q, "fps": 25}).get_json()
            assert p30["success"] and p30["fps"] == 30 and len(p30["clips"]) == 4 and p30["in_pauses"], p30
            assert len(p25["clips"]) == 3 and all(x["frames"] <= 300 for x in p25["clips"] + p30["clips"]), (p25, p30)
            assert [x["frames"] for x in p30["clips"]] == [web_gui._hg_frames(x["seconds"], 30) for x in p30["clips"]]

            # 30 s with a 300-frame limit at 25 fps → 3 clips, cut in the pauses, rendered side by side.
            # HeyGen holds one render back once; it starts on the next round.
            calls.clear()
            mode.update(busy=1, made=0, status={})
            web_gui._video_frames = lambda p: (280, 25.0)
            r = c.post("/api/heygen/audio-video", json={**base, "voiceover": long_.name, "max_frames": 300, "fps": 25}).get_json()
            assert r["success"] and r["clips"] == 3 and r["max_frames"] == 300 and r["fps"] == 25, r
            assert [x["end"] for x in r["plan"]] == [x["end"] for x in p25["clips"]], (r["plan"], p25)
            s = wait_job(c, r["job_id"])
            parts = s["parts"]
            assert s["status"] == "done" and [p["status"] for p in parts] == ["done"] * 3, s
            stem = Path(parts[0]["path"]).stem[:-len("_part1of3")]
            assert [Path(p["path"]).name for p in parts] == [f"{stem}_part{i}of3.mp4" for i in (1, 2, 3)]
            assert all(Path(p["path"]).parent == d / "out" / "heygen" for p in parts)
            assert sorted(Path(p["path"]).read_bytes() for p in parts) == [b"MP4-vid1.mp4", b"MP4-vid2.mp4", b"MP4-vid3.mp4"]
            assert [p["audio"] for p in parts] == [f"{stem}_part{i}of3.mp3" for i in (1, 2, 3)]
            assert sorted(x.name for x in (vo / "clips").iterdir()) == [p["audio"] for p in parts]
            for p in parts:
                assert p["frames"] <= 300 and p["seconds"] <= 11.84 and p["video_frames"] == 280 and p["heygen_frames"] == 280, p
            for cut in (parts[0]["end"], parts[1]["end"]):
                assert 4.4 < cut % 5 < 5.0, f"cut at {cut} is not in a pause"
            assert parts[0]["start"] == 0 and parts[0]["end"] == parts[1]["start"] and abs(parts[2]["end"] - 30) < 0.1
            assert abs(sum(p["seconds"] for p in parts) - 30) < 0.15, parts
            assert [x[3]["file"][0] for x in posts("/v3/assets")] == [p["audio"] for p in parts]
            titles = [x[3]["title"] for x in posts("/v3/videos")]
            assert titles == [f"Talk (ElevenLabs audio) part {i} of 3" for i in (1, 2, 3, 1)], titles   # clip 1 retried
            v = c.get(f"/api/heygen/audio-video/{r['job_id']}/file?part=2")
            assert v.status_code == 200 and v.mimetype == "video/mp4"
            v.close()
            assert c.get(f"/api/heygen/audio-video/{r['job_id']}/file?part=9").status_code == 404
            saved = _json.loads(settings.read_text())
            assert (saved["heygen_audio_template_id"], saved["heygen_audio_resolution"], saved["heygen_audio_max_frames"],
                    saved["heygen_audio_count_fps"]) == (TPL, "1080p", 300, 25)

            # One clip fails at HeyGen: the others are still saved and the error names the clip.
            calls.clear()
            mode.update(made=0, status={"vid2": ["processing", "failed"]})
            r = c.post("/api/heygen/audio-video", json={**base, "voiceover": long_.name, "max_frames": 300, "fps": 25}).get_json()
            s = wait_job(c, r["job_id"])
            assert s["status"] == "error" and [p["status"] for p in s["parts"]] == ["done", "failed", "done"], s
            assert "Clip 2 of 3: HeyGen could not render it: Audio too quiet" in s["error"] and "2 of 3 clips were saved" in s["error"]

            # Cuts that would leave a clip over the limit stop the job before anything is uploaded.
            calls.clear()
            web_gui._plan_clip_cuts = lambda duration, pauses, max_seconds, n: [2.0, 4.0][:n - 1]
            r = c.post("/api/heygen/audio-video", json={**base, "voiceover": long_.name, "max_frames": 300, "fps": 25}).get_json()
            s = wait_job(c, r["job_id"])
            assert s["status"] == "error" and "over the 300 limit" in s["error"] and not posts("/v3/assets"), s
            web_gui._plan_clip_cuts = keep[8]

            # A look without the template's engine gets HeyGen's default engine; a failed render reads plainly.
            mode.update(engines=["avatar_iv"], made=0, status={"vid1": ["processing", "failed"]})
            calls.clear()
            r = c.post("/api/heygen/audio-video", json={**base, "voiceover": short.name, "max_frames": 9000, "fps": 30}).get_json()
            s = wait_job(c, r["job_id"])
            body = posts("/v3/videos")[0][3]
            assert "engine" not in body and s["status"] == "error" and "Audio too quiet" in s["error"] and key not in s["error"], s
            assert "Clip 1" not in s["error"]
        finally:
            (web_gui.SCRIPTCRAFT_SETTINGS_PATH, web_gui._get_run_output_dir, web_gui.requests.get,
             web_gui.requests.post, web_gui.time.sleep, env, web_gui.HEYGEN_AUDIO_MAX_BYTES,
             web_gui._video_frames, web_gui._plan_clip_cuts) = keep
            if env is None:
                os.environ.pop("HEYGEN_API_KEY", None)
            else:
                os.environ["HEYGEN_API_KEY"] = env

    # Frames: HeyGen's video is the audio rounded up to a 25 fps frame; the upscaler counts it at its own rate.
    # These are the three clips of 2026-11-07 (7,855 / 7,501 / 7,087 frames from HeyGen; two were over 9,000 at 30 fps).
    hf = web_gui._hg_frames
    assert [hf(x, 25) for x in (314.162708, 300.03, 283.475937)] == [7855, 7501, 7087]
    assert [hf(x, 30) for x in (314.162708, 300.03, 283.475937)] == [9426, 9002, 8505]
    assert hf(web_gui._hg_clip_seconds(9000, 30), 30) <= 9000 and hf(web_gui._hg_clip_seconds(9000, 25), 25) <= 9000
    assert web_gui._hg_clip_count(887.14, 9000, 30) == 3 and web_gui._hg_clip_count(938.43, 9000, 30) == 4
    assert web_gui._hg_clip_count(938.43, 9000, 25) == 3 and web_gui._hg_clip_count(299, 9000, 30) == 1

    # Cut planning: the longest pause near an even split when there's room; inside a pause (not its middle)
    # when the limit is tight; one more clip when no pauses line up; even cuts when there are no pauses.
    plan, cap = web_gui._plan_clip_cuts, web_gui._hg_clip_seconds(9000, 30)
    pauses = [(t - 0.2, t + 0.2) for t in range(3, 900, 3)] + [(293.0, 294.0)]
    cuts = plan(887.14, pauses, cap, 3)
    edges = [0] + cuts + [887.14]
    assert len(cuts) == 2 and cuts[0] == 293.5 and all(b - a <= cap for a, b in zip(edges, edges[1:])), cuts
    tight = [(150.0, 150.4), (290.81, 291.08), (297.92, 298.07), (450.0, 450.4), (597.81, 598.15), (750.0, 750.4)]
    cuts = plan(897.706, tight, cap, 3)                 # 14:58 at 30 fps: only 1.9 s of slack across 3 clips
    assert cuts and 297.97 <= cuts[0] <= 298.02 and 597.86 <= cuts[1] <= 598.10, cuts
    edges = [0] + cuts + [897.706]
    assert all(hf(b - a, 30) <= 9000 for a, b in zip(edges, edges[1:])), [hf(b - a, 30) for a, b in zip(edges, edges[1:])]
    assert plan(897.706, tight[:2] + tight[3:], cap, 3) is None    # no pause near 5:00 → 3 clips can't be clean
    assert plan(300, pauses, 359, 1) == []

    html = open(os.path.join(APP, "templates", "index.html"), encoding="utf-8").read()
    assert 'id="hgaSection"' in html and 'id="hgaMaxFrames"' in html and "async function startHeyGenAudioVideo()" in html
    assert "max_frames: maxFrames, fps: fps" in html and "function _hgaRenderClips(" in html and 'id="hgaCountFps"' in html
    assert "fetch('/api/heygen/audio-video/plan?' + q)" in html
    assert "hgaRefresh((s.path || '').split('/').pop());" in html
    return "frames predicted as HeyGen + upscaler count them (the 2026-11-07 clips: 9,426/9,002/8,505 at 30 fps); 30 s at 300 frames → 4 clips at 30 fps, 3 at 25; cuts in pauses (inside one when tight; extra clip when none line up); rendered side by side (held-back render retried) into heygen/_partNof3.mp4; failed clip named; over-limit stops before upload; bad files/limits/fps refused; key never shown"

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
            for bad in ("alert(1)", "onclick", "evil.example", "box-shadow", "lineargradient", "url(#g)"):
                assert bad not in page.lower(), bad
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
    assert inputs.count("-i") == 2 and "concat=n=2" in graph and "overlay=2240:0" in graph and "between(t,2.9990,7.0000)" in graph, graph
    assert "-reinit_filter" in xv._x264_cmd(Path("x.mp4"), 16)

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
            # Claude's revision of s02 is told about the section.
            r = c.post(f"/api/explainer/{pid}/revise", json={"title": "Talk", "feedback": "", "scope": "slides", "slides": ["s02"],
                                                              "see": False, "warnings": {"s02": ["“Your account” covers the presenter"]}}).get_json()
            s = wait(c, pid)
            task = calls[-1]["messages"][0]["content"][-1]["text"]
            assert s["job"]["status"] == "done" and "PRESENTER SECTIONS the user placed on this slide" in task and "left panel 22.0-27.0 s" in task, task[-600:]
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
            "the one without footage warned, approval cleared; " + rendered + "; Claude's revision brief names the section")


if __name__ == "__main__":
    width = max(len(n) for n, _, _ in RESULTS)
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} checks passed")
    sys.exit(1 if failed else 0)
