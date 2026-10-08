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


if __name__ == "__main__":
    width = max(len(n) for n, _, _ in RESULTS)
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} checks passed")
    sys.exit(1 if failed else 0)
