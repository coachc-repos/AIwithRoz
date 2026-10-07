"""Record every agent call the APP's real script pipeline makes (for replay tests).

Runs linedrive_azure/agents/enhanced_autogen_system.py's
run_complete_script_workflow_sequential() exactly as web_gui.py does, with the
portal agents, and records each BaseAgentClient.send_message() call (agent
name, the exact message the app built, the portal agent's reply) to
OUTDIR/calls.jsonl, plus OUTDIR/summary.json (format, title) and the final
script. maf/agents/pipeline.py --replay OUTDIR (and the --replay modes of
quotes_stats.py and hook_summary.py) then send the same messages to the code
agents and score both replies with the app's own parsing.

Run it with the APP's interpreter (it imports the app), not maf/.venv:

    /opt/homebrew/opt/python@3.12/bin/python3.12 maf/testing/capture_pipeline.py \
        teaching /tmp/cap_teaching "5 AI habits that quietly waste your time at work" \
        "Practical teaching video: five habits, why each wastes time, the fix for each."

FORMAT is teaching | list | predictions. Like web_gui, the topic description
gets the golden-reference style block (the "recent scripts" half needs web_gui
internals and is left out). Review-feedback files the pipeline writes land in
OUTDIR. The repo-root .env is loaded so the app's Claude chapter fallback works
when a Foundry call is throttled.
"""
import asyncio, json, os, sys, threading, time
APP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # scriptcraft-app-v2
fmt, out, topic, desc = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
os.makedirs(out, exist_ok=True)
sys.path.insert(0, APP)
os.chdir(APP)  # import-time relative paths (env, instruction files)
from dotenv import load_dotenv  # same as web_gui: keys from the repo-root .env
load_dotenv(os.path.join(os.path.dirname(APP), ".env"), override=False)
from linedrive_azure.agents import base_agent_client as bac
from linedrive_azure.agents.enhanced_autogen_system import EnhancedAutoGenSystem
from linedrive_azure.agents.pro_script_writer import load_golden_reference
os.chdir(out)  # review feedback files land here, not in the repo

lock = threading.Lock()
_orig = bac.BaseAgentClient.send_message
def _recording_send(self, thread_id, message_content, show_sources=False, timeout=300, max_retries=3):
    t = time.time()
    res = _orig(self, thread_id, message_content, show_sources=show_sources, timeout=timeout, max_retries=max_retries)
    rec = {"agent": getattr(self, "v2_agent_name", None) or getattr(self, "agent_name", None),
           "client": type(self).__name__, "message": message_content, "success": res.get("success"),
           "response": res.get("response"), "error": res.get("error"), "seconds": round(time.time() - t, 1)}
    with lock:
        with open(os.path.join(out, "calls.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    print(f"   [recorded] {rec['agent']} ({rec['client']}) {len(message_content)} -> {len(rec['response'] or '')} chars, {rec['seconds']}s", flush=True)
    return res
bac.BaseAgentClient.send_message = _recording_send

golden = load_golden_reference(max_chars=9000)
style = ("\n\n--- GOLDEN REFERENCE SCRIPT (the approved target: match this "
         "STRUCTURE, production conventions, and SPOKEN VOICE exactly — no "
         "contractions, no em-dashes or en-dashes, numbers and names spelled "
         "the way the avatar says them, a FINAL HOOK, 'Heading: Chapter N -' "
         "lines, [PRODUCTION BEGIN] / [GROK IMAGINE / RESOLVE] / [PRODUCTION "
         "END] blocks, [VERIFY BEFORE RENDER] for legal or numeric claims, a "
         "cheat-sheet [PROMPT OVERLAY] in the final chapter, and trailing "
         "=== … === sections. Do NOT copy its topic or wording) ---\n"
         + golden + "\n--- END GOLDEN REFERENCE ---\n") if golden else ""
topic_description = (desc + style) if desc else style.strip()

t0 = time.time()
system = EnhancedAutoGenSystem(verbose=False, script_format=fmt)
result = asyncio.run(system.run_complete_script_workflow_sequential(
    script_topic=topic, topic_description=topic_description, audience="general audience",
    tone="conversational and educational", script_length="8-10 minutes", max_chapters=8,
    hook_summary=True, script_format=fmt))
summary = {k: (v if isinstance(v, (int, float, bool)) or v is None else (len(v) if hasattr(v, "__len__") else str(v)))
           for k, v in (result or {}).items()}
json.dump({"format": fmt, "topic": topic, "seconds": round(time.time() - t0), "result_keys": summary},
          open(os.path.join(out, "summary.json"), "w"), indent=1, default=str)
for key in ("final_script", "complete_script", "script", "enhanced_script"):
    if isinstance((result or {}).get(key), str) and result[key].strip():
        open(os.path.join(out, "final_script.md"), "w", encoding="utf-8").write(result[key]); break
print("DONE", fmt, round(time.time() - t0), "s")
