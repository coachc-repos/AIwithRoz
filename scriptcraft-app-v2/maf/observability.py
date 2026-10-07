"""Shared MAF helpers: env loading, the Foundry project endpoint/credential,
and best-effort OpenTelemetry tracing. Used by every maf/ entry point."""
from __future__ import annotations

import os

# Same project the current app uses
# (linedrive_azure/agents/base_agent_client.py:PROJECT_ENDPOINT).
PROJECT_ENDPOINT = os.environ.get(
    "FOUNDRY_PROJECT_ENDPOINT",
    "https://linedrive-ai-foundry.services.ai.azure.com/api/projects/linedriveAgents",
)


def load_env() -> None:
    """Load maf/.env and the repo-root .env without overriding real env vars."""
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


def make_credential():
    """Local-dev credential (az login). Swap for ManagedIdentityCredential in prod."""
    from azure.identity import AzureCliCredential
    return AzureCliCredential()


def setup_tracing() -> str:
    """Best-effort OpenTelemetry setup. Never raises. Returns a status string.

    Precedence:
      1. APPLICATIONINSIGHTS_CONNECTION_STRING -> Azure Monitor (Foundry portal).
      2. MAF_TRACE_CONSOLE=1 -> verbose local span dump (debugging).
      3. otherwise -> off (clean output; MAF still emits spans, nothing exports).
    """
    conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if conn:
        try:
            from microsoft.opentelemetry import use_microsoft_opentelemetry
            use_microsoft_opentelemetry(
                enable_azure_monitor=True,
                azure_monitor_connection_string=conn,
                enable_sensitive_data=True,
                sampling_ratio=1.0,
                instrumentation_options={
                    "agent-framework": {
                        "enabled": True,
                        "agent_id": "scriptcraft-maf",
                        "agent_name": "ScriptCraft MAF",
                    }
                },
            )
            return "Azure Monitor -> Foundry portal (Observability > Traces)"
        except Exception as e:  # pragma: no cover
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
        except Exception as e:  # pragma: no cover
            return f"console tracing failed ({e!r})"

    return ("off (set APPLICATIONINSIGHTS_CONNECTION_STRING for Foundry portal "
            "traces, or MAF_TRACE_CONSOLE=1 for a local span dump)")
