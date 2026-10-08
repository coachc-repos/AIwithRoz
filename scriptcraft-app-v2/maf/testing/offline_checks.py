"""Offline parity checks for the MAF code agents (no model calls).

Verifies that every code agent still matches the app it replaces:
  * request messages are byte-identical to the app clients' f-strings
  * ported parsers and helpers behave identically to the app's originals
    (masking, Host-word counter, chapter extraction, reply parsers, extractors)
  * the Shorten content-filter fallback and correction pass work (fake agent)
  * all 15 agents build from the registry, and the hosted zip builds

    maf/.venv/bin/python maf/testing/offline_checks.py

Exit status 0 means every check passed. Run after editing an agent or after
pulling app changes to linedrive_azure/ or web_gui.py.
"""
from __future__ import annotations

import ast
import asyncio
import logging
import os
import re
import sys
import textwrap
import types

MAF = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.dirname(MAF)
sys.path.insert(0, MAF)

from observability import load_env  # noqa: E402

load_env()

from agents import (  # noqa: E402
    hook_summary, pipeline, polisher, quotes_stats, repeat_flow, shorten, youtube_details,
)
from agents import _production_blocks as pb  # noqa: E402
from agents._common import load_reference_script  # noqa: E402
from agents._script_metrics import app_host_words  # noqa: E402
from agents.registry import REGISTRY, build_agent  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str):
    def deco(fn):
        try:
            detail = fn() or ""
            RESULTS.append((name, True, detail))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return deco


def src(rel: str) -> str:
    with open(os.path.join(APP, rel), encoding="utf-8") as f:
        return f.read()


def fstring_block(source: str, start: str, opener: str) -> str:
    """Lines from `start` through the end of the triple-quoted f-string that
    begins at `opener`, runnable inside `if True:`."""
    i = source.index(start)
    i = source.rfind("\n", 0, i) + 1
    j = source.index('"""', source.index(opener) + len(opener)) + 3
    return "if True:\n" + source[i:j]


def grab_defs(rel: str, names: set[str], extra_ns: dict | None = None) -> dict:
    """Exec selected top-level (or class-level) defs/assigns from an app file."""
    source = src(rel)
    ns = {"re": re, "logger": logging.getLogger("offline"), **(extra_ns or {})}
    nodes = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.Assign)):
            name = node.name if isinstance(node, ast.FunctionDef) else getattr(node.targets[0], "id", None)
            if name in names:
                if isinstance(node, ast.FunctionDef):
                    node.decorator_list = []
                nodes.append(node)
    nodes.sort(key=lambda n: n.lineno)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), rel, "exec"), ns)
    return ns


GOLDEN = load_reference_script()
MASKED, BLOCKS = pb.mask_production_blocks(GOLDEN)


@check("Hook-and-Summary request == app client")
def _():
    s = src("linedrive_azure/agents/hook_and_summary_agent_client.py")
    i = s.index('request_message = f"""')
    j = s.index('"""', i + 22) + 3
    ns = dict(script_content="X", script_title="T", target_audience="A", tone="B", video_length="C")
    exec(s[i:j].strip(), {}, ns)
    assert ns["request_message"] == hook_summary.build_request_message("X", "T", "A", "B", "C")


@check("Repeat-and-Flow request + Chapter-1 repair == app client")
def _():
    s = src("linedrive_azure/agents/script_repeat_and_flow_agent_client.py")
    i = s.index('prompt = f"""')
    j = s.index('"""', i + 13) + 3
    for title in ("T", None):
        ns = dict(script_content="BODY", script_title=title, target_audience="pros")
        exec(s[i:j].strip(), {}, ns)
        assert ns["prompt"] == repeat_flow.build_request_message("BODY", title, "pros")
    fix = grab_defs("linedrive_azure/agents/script_repeat_and_flow_agent_client.py",
                    {"_restore_missing_chapter_one"})["_restore_missing_chapter_one"]
    for imp, org in [("## Chapter 2: B\nx", "## Chapter 1: A\ny"), ("intro\nChapter 2 - B\nx", "z"),
                     ("Heading: Chapter 2 - B", "Heading: Chapter 1 - A"), ("", "x")]:
        assert fix(imp, org) == repeat_flow.restore_missing_chapter_one(imp, org)


@check("Production-block masking == web_gui.py")
def _():
    web = grab_defs("web_gui.py", {"_PRODUCTION_BLOCK_PATTERN", "_PRODUCTION_BLOCK_RE", "_mask_production_blocks",
                                   "_restore_production_blocks", "_restore_or_keep"})
    assert web["_mask_production_blocks"](GOLDEN) == pb.mask_production_blocks(GOLDEN)
    dropped = MASKED.replace("[[PRODUCTION_BLOCK_5]]", "")
    assert web["_restore_or_keep"](dropped, BLOCKS, GOLDEN) == GOLDEN == pb.restore_or_keep(dropped, BLOCKS, GOLDEN)[0]
    assert pb.restore_or_keep(MASKED, BLOCKS, "x") == (GOLDEN, True)
    return f"{len(BLOCKS)} blocks on the golden script"


@check("Host-word counter == both copies in web_gui.py")
def _():
    s = src("web_gui.py")
    for fname in ("_host_word_count", "_host_word_count_create"):
        i = s.index(f"def {fname}(text: str) -> int:")
        i = s.rfind("\n", 0, i) + 1
        j = s.index("return sum(len(b.split()) for b in blocks)", i) + len("return sum(len(b.split()) for b in blocks)")
        ns = {"re": re, "_re_short": re, "_PRODUCTION_BLOCK_RE": pb._PRODUCTION_BLOCK_RE}
        exec(textwrap.dedent(s[i:j]), ns)
        assert ns[fname](GOLDEN) == app_host_words(GOLDEN)
    return f"{app_host_words(GOLDEN)} Host words on the golden script"


@check("Shorten requests (main + chapter retry) and helpers == app client")
def _():
    s = src("linedrive_azure/agents/script_shorten_agent_client.py")
    main = fstring_block(s, "        if target_words_override is not None and target_words_override > 0:", 'query = f"""')
    for c in [dict(target_minutes=10.0, wpm=150, target_words_override=1384, reduction_percent=25, current_host_words=1845),
              dict(target_minutes=8.0, wpm=150, target_words_override=None, reduction_percent=None, current_host_words=None)]:
        loc = dict(c, script_content=MASKED)
        exec(main, {}, loc)
        assert loc["query"] == shorten.build_request_message(MASKED, **c)
    chunks = shorten.split_into_chapter_chunks(MASKED)
    sub = fstring_block(s, '            sub_query = f"""', 'sub_query = f"""')
    loc = dict(chunk=chunks[2], idx=3, chunks=chunks, chunk_target=180, hw=250, target_minutes=10.0, wpm=150)
    exec(sub, {}, loc)
    assert loc["sub_query"] == shorten.build_chunk_message(chunks[2], 3, chunks, 180, 250, 10.0, 150)
    ns = grab_defs("linedrive_azure/agents/script_shorten_agent_client.py",
                   {"_is_content_filter_error", "_split_into_chapter_chunks", "_host_words_in"},
                   {"Any": object, "List": list})
    for t in ("no chapters", "Chapter 1 x\nHost: a b\nChapter 2 y\nHost: c"):
        assert ns["_split_into_chapter_chunks"](t) == shorten.split_into_chapter_chunks(t)
    for t in (MASKED, GOLDEN):
        assert ns["_host_words_in"](t) == shorten.host_words_in(t)
    for e in ("Error code: 400 content_filter", "Responsible AI", "timeout", None, "jailbreak"):
        assert ns["_is_content_filter_error"](e) == shorten.is_content_filter_error(e)
    assert len(ns["_split_into_chapter_chunks"](MASKED)) == 1 and len(chunks) == 8  # the documented fix
    return "client splitter finds 1 chunk on a Pro script; the fixed splitter finds 8"


@check("Shorten content-filter fallback + correction pass (fake agent)")
def _():
    class Fake:
        async def run(self, message):
            if message.startswith("TARGET LENGTH:\n"):
                raise RuntimeError("Error code: 400 - {'error': {'code': 'content_filter'}}")
            chunk = message.split("CHAPTER CONTENT TO SHORTEN:\n", 1)[1].rstrip("\n")
            return types.SimpleNamespace(text=chunk, finish_reason="stop", messages=[])
    r = asyncio.run(shorten.shorten_to_target(MASKED, 10.0, 150, 1384, 25, 1845, agent=Fake(), label="fake"))
    assert r["success"] and r["chunked"] and r["chunk_failures"] == 0
    assert pb.restore_or_keep(shorten.strip_code_fences(r["response"].strip()), BLOCKS, GOLDEN)[1]
    assert r.get("correction_pass", "").endswith("(rejected)")


@check("YouTube request + extract_* == app client")
def _():
    s = src("linedrive_azure/agents/youtube_upload_details_agent_client.py")
    body = fstring_block(s, "        # Extract title if not provided", 'query = f"""')
    for kw in (dict(script_title="T", primary_keywords=None, channel_focus=None, video_length="10 minutes", target_audience="general"),
               dict(script_title=None, primary_keywords=["ai"], channel_focus="tech", video_length=None, target_audience="pros")):
        loc = dict(kw, script_content="Line one\nHost: hello " * 20)
        exec(body, {"print": lambda *a, **k: None}, loc)
        assert loc["query"] == youtube_details.build_request_message(
            loc["script_content"], kw["script_title"], kw["target_audience"], kw["video_length"],
            kw["primary_keywords"], kw["channel_focus"])
    cls = [n for n in ast.parse(s).body if isinstance(n, ast.ClassDef)][0]
    ns = {"re": re, "List": list}
    for fn in cls.body:
        if isinstance(fn, ast.FunctionDef) and fn.name.startswith("extract_"):
            exec(compile(ast.Module(body=[fn], type_ignores=[]), "yt", "exec"), ns)
    sample = ("## 📁 FILE NAME\nai-tools-2026\n\n## 🎬 VIDEO TITLE\nTen Tools\n\n## 📝 DESCRIPTION\nAbout tools.\n\n"
              "## 🏷️ TAGS\nai, tools, 2026\n\n## Other\nx")
    for f in ("extract_filename", "extract_title", "extract_tags", "extract_description"):
        assert ns[f](None, sample) == getattr(youtube_details, f)(sample), f


@check("Polisher request == app client")
def _():
    s = src("linedrive_azure/agents/script_polisher_agent_client.py")
    body = fstring_block(s, "        # Extract title if not provided", 'query = f"""')
    for kw in (dict(script_title="T", target_audience="general", production_type="video", special_requirements=None),
               dict(script_title=None, target_audience="pros", production_type="podcast", special_requirements="x")):
        loc = dict(kw, raw_script="First line\nHost: hello " * 10)
        exec(body, {}, loc)
        assert loc["query"] == polisher.build_request_message(loc["raw_script"], **kw)


@check("Quotes request + parser == app client")
def _():
    s = src("linedrive_azure/agents/quote_and_statistics_agent_client.py")
    i = s.index('request_message = f"""')
    j = s.index('"""', i + 22) + 3
    loc = dict(script_content="BODY", script_title="T", target_audience="A", tone="B", topic="T")
    exec(s[i:j].strip(), {}, loc)
    assert loc["request_message"] == quotes_stats.build_request_message("BODY", "T", "A", "B")
    cls = [n for n in ast.parse(s).body if isinstance(n, ast.ClassDef)][0]
    fn = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_parse_response"][0]
    ns: dict = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "q", "exec"), ns)
    sample = ("## 📊 EXPERT QUOTES\n**Quote 1:**\n\"x\"\n## 📈 KEY STATISTICS\n**Statistic 1:** y\n"
              "## 🎯 USAGE RECOMMENDATIONS\n**Overall Strategy:** z\n\nmore")
    assert ns["_parse_response"](None, sample) == quotes_stats.parse_response(sample)


@check("Pipeline chapter extraction + deshout == the app's pipeline")
def _():
    ns = grab_defs("linedrive_azure/agents/enhanced_autogen_system.py", {"_DESHOUT_KEEP", "_deshout_text"})
    text = "BUILDING AI APPS WITH PYTHON and the AI-POWERED FUTURE"
    assert ns["_deshout_text"](text) == pipeline._deshout_text(text)
    plan = "\n".join(f"Chapter {i}: Title number {i} here (0:{i}0-0:{i}9)" for i in range(1, 12))
    assert len(pipeline.extract_chapters(plan, 8)) == 8
    assert pipeline.app_max_chapters("list", "Top 8 AI tools") == 10
    assert pipeline.app_max_chapters("predictions", "6 bold predictions") == 8
    assert pipeline.app_max_chapters("teaching", "5 habits") == 8


@check("Streamed parallel tool calls parse to valid arguments (Foundry delta bug)")
def _():
    # The exact event shape Foundry's Claude adapter sent on 2026-10-07 when the model made
    # parallel web_search calls: one output item, deltas cut against one shared buffer, and the
    # last call's full arguments only on output_item.done. The hosted server always streams.
    import json  # noqa: PLC0415
    from agent_framework import ChatResponse  # noqa: PLC0415
    from agent_framework.foundry import FoundryChatClient  # noqa: PLC0415
    from openai.types.responses import (  # noqa: PLC0415
        ResponseFunctionCallArgumentsDeltaEvent as Delta,
        ResponseFunctionToolCall as Call,
        ResponseOutputItemAddedEvent as Added,
        ResponseOutputItemDoneEvent as Done,
    )
    from agents._common import CLAUDE_MODEL, FoundryClaudeChatClient  # noqa: PLC0415
    from observability import PROJECT_ENDPOINT, make_credential  # noqa: PLC0415

    first = '{"query": "NotebookLM new features 2025 Audio Overviews Video Overviews Mind Maps Discover sources"}'
    last = ('{"query": "AI search engines accuracy study 2025 Columbia Journalism Review Tow Center '
            'citation errors chatbots news"}')
    cid, fid = "call_toolu_test_agents", "fc_test"
    events = [
        Added(type="response.output_item.added", output_index=0, sequence_number=1,
              item=Call(type="function_call", id=fid, call_id=cid, name="web_search", arguments="")),
        Delta(type="response.function_call_arguments.delta", output_index=0, sequence_number=2,
              item_id=fid, delta=first),
        Delta(type="response.function_call_arguments.delta", output_index=0, sequence_number=3,
              item_id=fid, delta=""),
        Delta(type="response.function_call_arguments.delta", output_index=0, sequence_number=4,
              item_id=fid, delta=last[len(first):]),
        Done(type="response.output_item.done", output_index=0, sequence_number=5,
             item=Call(type="function_call", id=fid, call_id=cid, name="web_search", arguments=last)),
    ]

    def merged_args(cls):
        client = cls(project_endpoint=PROJECT_ENDPOINT, model=CLAUDE_MODEL, credential=make_credential())
        ids: dict = {}
        updates = [client._parse_chunk_from_openai(e, options={}, function_call_ids=ids) for e in events]
        calls = [c for m in ChatResponse.from_updates(updates).messages for c in m.contents
                 if c.type == "function_call"]
        assert len(calls) == 1, f"{cls.__name__}: {len(calls)} function calls"
        return calls[0].arguments

    fixed = merged_args(FoundryClaudeChatClient)
    assert json.loads(fixed) == json.loads(last), fixed
    stock = merged_args(FoundryChatClient)
    try:
        json.loads(stock)
        stock_note = "stock client now parses it too; FoundryClaudeChatClient may be removable"
    except (TypeError, ValueError):
        stock_note = "stock client still yields invalid JSON"
    return f"fixed client: valid JSON; {stock_note}"


@check("Pro writer agent instructions == the v3 app's Pro prompt")
def _():
    from agents._common import load_instructions  # noqa: PLC0415
    from agents.pro_writer import app_prompt  # noqa: PLC0415
    hosted = load_instructions("Script-Writer-Pro-Agent").strip()
    assert hosted == app_prompt(), "run: maf/.venv/bin/python -m agents.pro_writer --sync"
    assert "CHAPTER COUNT (REQUIRED)" in hosted
    return f"{len(hosted)} chars, in sync"


@check("Pro writer agent builds on both Foundry endpoints (MAF_PRO_PATH)")
def _():
    from agents import pro_writer  # noqa: PLC0415
    resp = pro_writer.build_code_agent(path="responses")
    anth = pro_writer.build_code_agent(path="anthropic")
    assert type(resp.client).__name__ == "FoundryClaudeChatClient"
    assert resp.default_options["reasoning"] == {"effort": "high"}
    assert type(anth.client).__name__ == "AnthropicFoundryClient"
    assert anth.default_options["thinking"] == {"type": "adaptive"}
    assert anth.default_options["output_config"] == {"effort": "high"}
    return f"default path: {pro_writer.PRO_PATH}"


@check("All 16 agents build from the registry")
def _():
    names = sorted(REGISTRY)
    for n in names:
        build_agent(n)
    assert len(names) == 16  # 15 portal agents + Script-Writer-Pro-Agent
    return ", ".join(n.replace("Script-", "").replace("-Agent", "") for n in names)


@check("Hosted deployment zip builds")
def _():
    sys.path.insert(0, os.path.join(MAF, "hosted"))
    import deploy  # noqa: PLC0415
    data, sha, files = deploy.build_zip()
    assert "main.py" in files and "agents/registry.py" in files
    assert all(f"agent_instructions/{n}.md" in files for n in REGISTRY)
    return f"{len(files)} files, {len(data) // 1024} KiB"


if __name__ == "__main__":
    width = max(len(n) for n, _, _ in RESULTS)
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} checks passed")
    sys.exit(1 if failed else 0)
