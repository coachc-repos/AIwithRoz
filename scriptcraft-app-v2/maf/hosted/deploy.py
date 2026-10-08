"""
Deploy the ScriptCraft MAF code agents as Foundry HOSTED agents (step 4).

Builds one source zip (hosted/main.py as the entry point, the agents/ package,
observability.py, and the captured agent_instructions/*.md) and creates one
hosted agent per code agent with Foundry's source-code deployment: no Docker,
no container registry; Foundry installs requirements.txt itself (remote_build).
Each hosted agent is named "<portal name>-MAF" so it sits next to its portal
prompt agent in the Foundry portal, and its MAF_AGENT setting tells the shared
entry point which code agent to serve.

Hosted agents scale to zero: each session gets its own sandbox, billed only
while active, and the sandbox is released after IDLE_TIMEOUT of inactivity.

    maf/.venv/bin/python maf/hosted/deploy.py --dry-run          # build the zip, list the plan
    maf/.venv/bin/python maf/hosted/deploy.py                    # deploy all 15, poll, smoke-test
    maf/.venv/bin/python maf/hosted/deploy.py --only Script-bRoll-Agent
    maf/.venv/bin/python maf/hosted/deploy.py --smoke-only       # re-test what is deployed

Needs the Foundry Project Manager role on the project (az login).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import os
import subprocess
import sys
import time
import zipfile

MAF_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_APP = os.path.dirname(MAF_DIR)
sys.path.insert(0, MAF_DIR)

from observability import PROJECT_ENDPOINT, load_env, make_credential  # noqa: E402
from agents.registry import REGISTRY  # noqa: E402

SUFFIX = "-MAF"
CPU, MEMORY = "0.5", "1Gi"          # smallest sandbox; the agents only make API calls
IDLE_TIMEOUT = dt.timedelta(seconds=300)
RUNTIME = "python_3_13"
SMOKE_INPUT = ("SCRIPT TITLE: Two AI tools\n\nSCRIPT:\nHost: First, Perplexity answers with "
               "sources you can click. Second, NotebookLM only reads the documents you upload.")


def hosted_name(portal_name: str) -> str:
    name = portal_name + SUFFIX
    assert len(name) <= 63, name
    return name


def build_zip() -> tuple[bytes, str, list[str]]:
    """Flat zip: main.py + requirements.txt + observability.py + agents/ + agent_instructions/."""
    entries: list[tuple[str, str]] = [
        (os.path.join(MAF_DIR, "hosted", "main.py"), "main.py"),
        (os.path.join(MAF_DIR, "hosted", "requirements.txt"), "requirements.txt"),
        (os.path.join(MAF_DIR, "observability.py"), "observability.py"),
    ]
    for fn in sorted(os.listdir(os.path.join(MAF_DIR, "agents"))):
        if fn.endswith(".py"):
            entries.append((os.path.join(MAF_DIR, "agents", fn), f"agents/{fn}"))
    instr = os.path.join(REPO_APP, "agent_instructions")
    for name in sorted(REGISTRY):
        entries.append((os.path.join(instr, f"{name}.md"), f"agent_instructions/{name}.md"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for src, arc in entries:
            info = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))  # stable hash across builds
            info.compress_type = zipfile.ZIP_DEFLATED
            # Regular file, rw-r--r--. ZipInfo defaults to 0600, which the hosted
            # build could not read ("No Python dependency manifest found").
            info.external_attr = 0o100644 << 16
            with open(src, "rb") as f:
                z.writestr(info, f.read())
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest(), [arc for _, arc in entries]


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "-C", MAF_DIR, "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def env_for(portal_name: str) -> dict[str, str]:
    env = {"MAF_AGENT": portal_name, "MAF_HOSTED": "1"}
    if portal_name == "Script-Writer-Pro-Agent":
        # v3 streams this agent's reply; send SSE keep-alives through the long
        # reasoning pause (about 100 s) before the first words arrive.
        env["SSE_KEEPALIVE_INTERVAL"] = "15"
    if portal_name == "Statistics-and-Quotes-Finder-Agent":
        # The Grok agent calls xAI directly (X search); it needs the xAI key.
        key = (os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY") or "").strip()
        if not key:
            raise SystemExit("XAI_API_KEY is required to deploy the Quotes agent")
        env["XAI_API_KEY"] = key
    return env


def deploy(names: list[str], dry_run: bool) -> list[str]:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import (
        CodeConfiguration, HostedAgentDefinition, ProtocolVersionRecord, SessionConfiguration,
    )

    data, sha, files = build_zip()
    print(f"zip: {len(files)} files, {len(data) / 1024:.0f} KiB, sha256 {sha[:12]}…")
    for n in names:
        print(f"  {n:<42} -> {hosted_name(n)}")
    if dry_run:
        print("dry run: nothing deployed")
        return []
    project = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=make_credential())
    created = []
    for n in names:
        definition = HostedAgentDefinition(
            cpu=CPU, memory=MEMORY,
            code_configuration=CodeConfiguration(runtime=RUNTIME, entry_point=["python", "main.py"],
                                                 dependency_resolution="remote_build"),
            protocol_versions=[ProtocolVersionRecord(protocol="responses", version="2.0.0")],
            environment_variables=env_for(n),
            session_configuration=SessionConfiguration(idle_timeout_seconds=IDLE_TIMEOUT),
        )
        v = project.agents.create_version_from_code(
            agent_name=hosted_name(n), definition=definition,
            code=(f"{hosted_name(n)}.zip", data, "application/zip"),  # the service needs a .zip filename
            code_zip_sha256=sha,
            description=f"Microsoft Agent Framework code version of the portal agent {n} "
                        f"(ScriptCraft maf/agents, git {git_sha()}).",
            metadata={"source": "maf", "portal_agent": n, "git": git_sha()},
        )
        print(f"  created {hosted_name(n)} v{v.version} ({v.get('status')})")
        created.append((hosted_name(n), v.version))
    # Poll all versions until active / failed.
    pending = dict(created)
    deadline = time.time() + 30 * 60
    while pending and time.time() < deadline:
        time.sleep(15)
        for hn, ver in list(pending.items()):
            st = project.agents.get_version(agent_name=hn, agent_version=ver)
            if st["status"] in ("active", "failed"):
                err = st.get("error") or {}
                print(f"  {hn} v{ver}: {st['status']} {err.get('message', '')[:300]}")
                pending.pop(hn)
    for hn in pending:
        print(f"  {hn}: still not active after 30 minutes")
    return [hn for hn, _ in created if hn not in pending]


def smoke(names: list[str]) -> None:
    from azure.ai.projects import AIProjectClient

    project = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=make_credential())
    for n in names:
        hn = hosted_name(n)
        t = time.time()
        try:
            client = project.get_openai_client(agent_name=hn)
            # Background mode + polling, as the v3 GUI calls these agents: a long
            # plain call can hit the gateway's 424 proxy_timeout.
            r = client.responses.create(input=SMOKE_INPUT, background=True, timeout=120)
            while r.status in ("queued", "in_progress") and time.time() - t < 900:
                time.sleep(3)
                r = client.responses.retrieve(r.id, timeout=60)
            text = (r.output_text or "").strip().replace("\n", " ")
            items = r.output or []
            calls = sum(1 for o in items if getattr(o, "type", "") == "function_call")
            outputs = [str(getattr(o, "output", "") or "") for o in items
                       if getattr(o, "type", "") == "function_call_output"]
            # "Error: ..." is MAF's tool-failure result (e.g. "Argument parsing failed");
            # "web_search is unavailable" is our own graceful fallback (see _common.py).
            errors = sum(1 for out in outputs if out.startswith("Error:"))
            degraded = sum(1 for out in outputs if out.startswith("web_search is unavailable"))
            # MAF returns this text instead of raising when its tool loop gives up.
            bad = not text or "Function invocation limit reached" in text or errors > 0
            print(f"  {'FAIL' if bad else 'OK  '} {hn:<46} {time.time() - t:5.0f}s  "
                  f"{calls} tool call(s), {errors} error(s), {degraded} search fallback(s)  "
                  f"{text[:90]}")
        except Exception as e:
            print(f"  FAIL {hn:<46} {time.time() - t:5.0f}s  {str(e)[:200]}")


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description="Deploy the MAF code agents as Foundry hosted agents.")
    ap.add_argument("--only", nargs="+", choices=sorted(REGISTRY), help="Deploy just these agents")
    ap.add_argument("--dry-run", action="store_true", help="Build the zip and print the plan")
    ap.add_argument("--smoke-only", action="store_true", help="Skip deploy; invoke each hosted agent")
    args = ap.parse_args()
    names = args.only or sorted(REGISTRY)
    if not args.smoke_only:
        deploy(names, args.dry_run)
    if not args.dry_run:
        print("smoke test (one Responses call per hosted agent):")
        smoke(names)


if __name__ == "__main__":
    main()
