"""
MAF migration — Step 1 proof of concept.

Stands up a Microsoft Agent Framework (MAF) orchestration layer that calls the
EXISTING Azure AI Foundry agents BY NAME (no agent rewrites) and chains two of
them sequentially:

    Script-Topic-Assistant-Agent  ->  Script-Writer-Agent

Goal of step 1: prove MAF can orchestrate the agents that already work in the
Foundry portal, end to end, with tracing — before we change anything else.
This file intentionally does NOT touch web_gui.py and runs in an isolated venv
(maf/.venv) so the working Foundry app's dependencies stay untouched.

Run:
    maf/.venv/bin/python maf/poc_topic_to_writer.py "AI tools people use wrong"

Tracing:
    If APPLICATIONINSIGHTS_CONNECTION_STRING is set (env or the repo-root .env),
    spans export to Azure Monitor and show in the Foundry portal
    (Observability > Traces). Otherwise spans print to the console so you can
    watch the run locally.
"""
from __future__ import annotations

import asyncio
import os
import sys

from azure.identity import AzureCliCredential
from agent_framework.foundry import FoundryAgent

# The live Foundry project — same endpoint the current app uses
# (linedrive_azure/agents/base_agent_client.py:PROJECT_ENDPOINT).
PROJECT_ENDPOINT = os.environ.get(
    "FOUNDRY_PROJECT_ENDPOINT",
    "https://linedrive-ai-foundry.services.ai.azure.com/api/projects/linedriveAgents",
)

# Existing v2 agents, called BY NAME — nothing is redefined here.
TOPIC_AGENT_NAME = os.environ.get("MAF_TOPIC_AGENT", "Script-Topic-Assistant-Agent")
WRITER_AGENT_NAME = os.environ.get("MAF_WRITER_AGENT", "Script-Writer-Agent")


def _load_env() -> None:
    """Load the repo-root .env (and a maf/.env if present) for connection
    strings, without overriding anything already in the environment."""
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    here = os.path.dirname(os.path.abspath(__file__))
    for env_path in (
        os.path.join(here, ".env"),
        os.path.join(here, "..", "..", ".env"),  # repo root
    ):
        if os.path.exists(env_path):
            load_dotenv(env_path, override=False)


def setup_tracing() -> str:
    """Best-effort OpenTelemetry setup. Never raises — tracing is additive.
    Returns a short status string for the banner.

    Precedence:
      1. APPLICATIONINSIGHTS_CONNECTION_STRING set -> Azure Monitor export; the
         run shows in the Foundry portal (Observability > Traces). This is the
         recommended way to "watch the trace".
      2. MAF_TRACE_CONSOLE=1 -> verbose local span dump (debugging only; noisy).
      3. otherwise -> off (clean output; MAF still emits spans, nothing exports).
    """
    conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()

    if conn:
        try:
            from microsoft.opentelemetry import use_microsoft_opentelemetry
            use_microsoft_opentelemetry(
                enable_azure_monitor=True,
                azure_monitor_connection_string=conn,
                enable_sensitive_data=True,  # dev: capture prompt/response content
                sampling_ratio=1.0,
                instrumentation_options={
                    "agent-framework": {
                        "enabled": True,
                        "agent_id": "scriptcraft-maf-poc",
                        "agent_name": "ScriptCraft MAF POC",
                    }
                },
            )
            return "Azure Monitor -> Foundry portal (Observability > Traces)"
        except Exception as e:  # pragma: no cover - diagnostics only
            return f"Azure Monitor setup failed ({e!r}); continuing without tracing"

    if os.environ.get("MAF_TRACE_CONSOLE", "").strip().lower() in ("1", "true", "yes"):
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import (
                BatchSpanProcessor,
                ConsoleSpanExporter,
            )
            provider = TracerProvider()
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
            trace.set_tracer_provider(provider)
            try:
                from microsoft.opentelemetry import use_microsoft_opentelemetry
                use_microsoft_opentelemetry(
                    enable_azure_monitor=False,
                    enable_sensitive_data=True,
                    instrumentation_options={"agent-framework": {"enabled": True}},
                )
            except Exception:
                pass
            return "console (verbose span dump; MAF_TRACE_CONSOLE=1)"
        except Exception as e:  # pragma: no cover - diagnostics only
            return f"console tracing failed ({e!r})"

    return ("off (set APPLICATIONINSIGHTS_CONNECTION_STRING for Foundry portal "
            "traces, or MAF_TRACE_CONSOLE=1 for a local span dump)")


async def run_pipeline(idea: str) -> str:
    """Topic Assistant -> Writer, both existing Foundry agents called by name."""
    credential = AzureCliCredential()

    topic_agent = FoundryAgent(
        project_endpoint=PROJECT_ENDPOINT,
        agent_name=TOPIC_AGENT_NAME,
        credential=credential,
    )
    writer_agent = FoundryAgent(
        project_endpoint=PROJECT_ENDPOINT,
        agent_name=WRITER_AGENT_NAME,
        credential=credential,
    )

    print(f"\n=== STEP 1/2 — {TOPIC_AGENT_NAME} ===")
    print(f"input: {idea}\n")
    topic_resp = await topic_agent.run(idea)
    topic_text = (topic_resp.text or "").strip()
    print(topic_text or "(empty response)")

    print(f"\n=== STEP 2/2 — {WRITER_AGENT_NAME} ===")
    writer_input = (
        "Here is the approved topic and outline from the Topic Assistant. "
        "Write the full script based on it:\n\n" + topic_text
    )
    writer_resp = await writer_agent.run(writer_input)
    script_text = (writer_resp.text or "").strip()
    print(f"(writer returned {len(script_text)} chars)\n")
    print(script_text or "(empty response)")
    return script_text


def main() -> None:
    _load_env()
    idea = " ".join(sys.argv[1:]).strip() or "The AI tools people are using wrong"
    status = setup_tracing()
    print("ScriptCraft MAF POC — Topic -> Writer by name (Microsoft Agent Framework)")
    print(f"project : {PROJECT_ENDPOINT}")
    print(f"agents  : {TOPIC_AGENT_NAME} -> {WRITER_AGENT_NAME}")
    print(f"tracing : {status}")
    asyncio.run(run_pipeline(idea))


if __name__ == "__main__":
    main()
