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

## Step 2 (done) — bring code-side models into MAF

- **`pro_writer_agent.py`** — the single-pass "Pro" script writer as a MAF agent.
  Reuses the exact `SCRIPT_WRITER_PRO_SYSTEM` prompt + golden reference from
  `../linedrive_azure/agents/pro_script_writer.py`, but runs it through
  `FoundryChatClient(model="claude-opus-5-5")` instead of a bespoke Anthropic
  streaming loop. Verified: a full ~28k-char script with the golden-reference
  shape (FINAL HOOK, chapters, PRODUCTION / GROK IMAGINE blocks, VERIFY,
  PROMPT OVERLAY).

  ```bash
  maf/.venv/bin/python maf/pro_writer_agent.py "Top 7 AI Tools, and When NOT to Use Them" \
      --brief "Practical countdown for busy professionals; 2026 examples."
  ```

- **`tools/grok_video.py`** — Grok Imagine video generation as a MAF **function
  tool** (`generate_grok_video`). A media API is a tool, not an agent, so an
  agent decides when to call it. The demo attaches the tool to a small B-Roll
  Director agent that discovers and calls it. Dry-run by default; set
  `MAF_GROK_LIVE=1` + `XAI_API_KEY` (and `pip install xai_sdk certifi requests`
  into the venv) to render for real.

  ```bash
  maf/.venv/bin/python maf/tools/grok_video.py "slow push-in on glowing AI tool icons on a dark desk"
  ```

`observability.py` holds the shared endpoint / credential / tracing helpers used
by all three entry points.

## Step 3 (in progress) — portal agents -> code, one at a time

Convert each portal agent to a code-defined MAF agent seeded from its captured
`../agent_instructions/*.md`; retire the portal copy only after a side-by-side
`--compare` passes.

- **`agents/broll.py`** — `Script-bRoll-Agent` as code (claude-opus-5-5 via
  `FoundryChatClient`, seeded from the captured instructions). `--compare` runs
  the code agent and the portal agent on the same script and prints both tables +
  row/section stats. Validated: both produce well-formed B-Roll tables
  (Timecode | Search Term | Description | Scene Context) with the
  `## Animation Suggestions` section. `web_search` is omitted — B-Roll reads the
  provided script, and the GA Foundry web-search tool is Azure-OpenAI-only.

  ```bash
  maf/.venv/bin/python maf/agents/broll.py --compare
  maf/.venv/bin/python maf/agents/broll.py --script-file path/to/script.md
  ```

- **`agents/hook_summary.py`** — `Script-Hook-and-Summary-Agent` as code (same
  model, same omission of `web_search`). It is a **drop-in** for
  `HookAndSummaryAgentClient.generate_hook_and_summary()`: it sends the app's
  request message verbatim (checked byte-for-byte) and returns the same dict keys
  `web_gui.py` reads. The reply parser is ported from the app client and
  hardened: section headers must start a line (both agents open with a preamble
  that mentions "the opening statement", which the app's regex mis-matched), any
  dash is accepted in "(8‑10 SECONDS)", and standalone length notes such as
  "*(About 122 words…)*" are stripped from spoken text. It also returns
  `opening_statement`, which the app client parses but drops.
  `--compare` defaults to the golden reference script (a full 7-chapter script)
  and scores both replies with that parser against the prompt's targets.
  Validated 2026-10-07: both agents parse into 3 hooks, opening, summary,
  3 thumbnail lines, and flow analysis. The code agent was closer to the word
  targets and followed the no-contractions / no-em-dash voice rules; the portal
  agent's summary ran 184 words against a 90-135 target.

  ```bash
  maf/.venv/bin/python maf/agents/hook_summary.py --compare --dump /tmp/hook_cmp
  maf/.venv/bin/python maf/agents/hook_summary.py --script-file path/to/script.md
  ```

`agents/_common.py` holds the shared recipe (load captured instructions, build
the code agent, retry transient DNS blips, call the portal agent by name, warn
when a reply hits `max_tokens`). Each new conversion is mostly its own prompt,
parser, and `--compare` scoring.

Remaining portal agents to convert: Topic-Assistant, Writer, Repeat-and-Flow,
Reviewer, Polisher, Shorten, Youtube-Upload-Details (gpt-6-astra, and actually
needs web search for tool URLs), Quotes-and-Statistics (grok-4.7),
Demo-Assistant, + the List/Predictions pairs.

## Next steps

4. Optionally host the MAF agents in Foundry (framework-hosted) for managed
   runtime + automatic portal tracing.

## Troubleshooting: `ConnectError: nodename nor servname` (VPN / split-DNS)

If a run fails with `ConnectError: [Errno 8] nodename nor servname provided`
("Connection error") while `nslookup linedrive-ai-foundry.services.ai.azure.com
1.1.1.1` **does** resolve, a zero-trust VPN (e.g. **Microsoft Global Connect** /
Global Secure Access) is intercepting DNS for `*.azure.com` /
`*.cognitive.microsoft.com` and its internal resolver can't resolve this host.
`nslookup` bypasses the OS resolver, so it lies about what the app sees — test
the real path instead:

```bash
maf/.venv/bin/python -c "import socket; print(socket.getaddrinfo('linedrive-ai-foundry.services.ai.azure.com',443)[0][4][0])"
```

Fixes: (a) turn the VPN off; or (b) keep it on and pin just this host in
`/etc/hosts` (it is a public endpoint):

```bash
echo "20.232.91.180 linedrive-ai-foundry.services.ai.azure.com" | sudo tee -a /etc/hosts
```

(The IP is a Traffic Manager front end that can change; remove the line to
revert.) The deployed cloud app is unaffected — it runs inside Azure.

## Notes

- Package set: `agent-framework-foundry` (pulls `agent-framework-core`),
  `azure-identity`, `python-dotenv`, `microsoft-opentelemetry`.
- The venv here resolves `azure-ai-projects` 2.6.x; the main app pins 2.1.0.
  Keeping MAF in its own venv avoids disturbing the running app until we
  reconcile dependencies at cut-over.
