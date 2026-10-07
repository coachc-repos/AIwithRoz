# MAF migration — `maf/`

Incremental migration to **Microsoft Agent Framework (MAF)** as the code-first
orchestration layer, **while keeping the existing Azure AI Foundry agents**.
MAF is the design/orchestration layer; Foundry is the managed runtime — they are
complementary, so we migrate in steps and keep a working app the whole way.

This directory is **self-contained and does not touch `web_gui.py`**. It runs in
its own virtual env (`maf/.venv`, git-ignored) so the running app's dependencies
are untouched.

## Step 1 (done) — orchestrate existing Foundry agents by name

`poc_topic_to_writer.py` stands up MAF and calls two **existing** Foundry agents
**by name** (`FoundryAgent`, the class Microsoft recommends for connecting to a
PromptAgent/HostedAgent), chaining them sequentially:

```
Script-Topic-Assistant-Agent  ->  Script-Writer-Agent
```

No agents are redefined — this proves MAF can drive what already works.

### Run it

```bash
# one-time: create the isolated venv + install
python -m venv maf/.venv
maf/.venv/bin/python -m pip install -r maf/requirements.txt

# run the chain (any episode idea)
maf/.venv/bin/python maf/poc_topic_to_writer.py "The AI tools people are using wrong"
```

Auth uses `AzureCliCredential` — just be signed in with `az login` (same
subscription as the Foundry project).

### Watch the trace

- **Foundry portal (recommended):** set `APPLICATIONINSIGHTS_CONNECTION_STRING`
  (env or repo-root `.env`) to the App Insights resource connected to the
  Foundry project. The run then appears under **Observability > Traces**
  (hosted/MAF-agent tracing is in preview; prompt-agent tracing is GA).
- **Local span dump (debug):** `MAF_TRACE_CONSOLE=1 maf/.venv/bin/python maf/poc_topic_to_writer.py "..."`
- **Default:** tracing off (clean output); MAF still emits OTel spans, nothing exports.

## Next steps (not done yet)

2. Bring code-side models in: make the single-pass **Claude writer** a MAF agent
   (`FoundryChatClient`, model `claude-opus-5-5`); wrap **Grok video** as a
   function tool (it is a media API, not a chat agent).
3. Migrate agents to code one at a time, seeding each from the captured
   `../agent_instructions/*.md`; delete the portal copy only after the code
   version passes.
4. Optionally host the MAF agents in Foundry (framework-hosted) for managed
   runtime + automatic portal tracing.

## Notes

- Package set: `agent-framework-foundry` (pulls `agent-framework-core`),
  `azure-identity`, `python-dotenv`, `microsoft-opentelemetry`.
- The venv here resolves `azure-ai-projects` 2.6.x; the main app pins 2.1.0.
  Keeping MAF in its own venv avoids disturbing the running app until we
  reconcile dependencies at cut-over.
