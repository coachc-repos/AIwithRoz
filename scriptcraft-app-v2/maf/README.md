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

- **`agents/repeat_flow.py`** — `Script-Repeat-and-Flow-Agent` as code, the first
  **transform** agent: when "Flow analysis" is checked, its rewrite replaces the
  user's script. It is a drop-in for
  `ScriptRepeatAndFlowAgentClient.analyze_and_improve_flow()`: same request
  (checked byte-for-byte), same keys, and the Chapter-1 repair is ported. Two
  safety differences: a reply with no revised-script section, or one cut off by
  `max_tokens`, returns `success=False` instead of being pasted in as the script.
  The parser also accepts the markdown-heading marker `### REVISED COMPLETE
  SCRIPT`, which the portal agent used once and the app's exact-text check misses.

  The app masks every `[PRODUCTION BEGIN]…[PRODUCTION END]` block as
  `[[PRODUCTION_BLOCK_N]]` before this agent runs, and **discards the whole
  rewrite if any placeholder is missing**. `agents/_production_blocks.py` ports
  that logic (checked identical to `web_gui.py`), so `--compare` scores what the
  app would actually *save*: placeholders kept, chapters, `Heading:` lines,
  invented timestamps, length, trailing sections, agent notes left in the script,
  dashes, contractions, and no-break spaces. `--code-only` skips the portal call.

  The code agent runs the captured prompt plus a four-rule `APP_CONTRACT`
  addendum: keep every placeholder, keep the heading layout and add no
  timestamps, drop nothing, and put nothing after the script. The portal prompt
  never states these rules, and the request's sample layout
  (`## Chapter 1: [Title] (X:XX)`) and the prompt's "before delivering, verify"
  checklist invite the opposite. `MAF_FLOW_APP_CONTRACT=0` runs the bare captured
  prompt for A/B checks.

  Validated 2026-10-07 on all four script formats: the golden reference and a
  produced Pro script ("Who Actually Wins When AI Doom Goes Viral"), a saved
  Top-N list script ("10 AI Tools, 10 Mistakes", 8 chapters), and a predictions
  script generated by the app's own Predictions topic and writer agents
  (6 predictions, 8 chapters, no production blocks):

  | Agent | Script | Placeholders kept | `Heading:` lines kept | Trailing sections kept | Notes added after script |
  |---|---|---|---|---|---|
  | Portal | golden | 0 of 29 | 0 of 7 | 0 of 4 | yes |
  | Portal | produced | 0 of 21 | 0 of 7, timestamps invented | 0 of 1 | yes |
  | Portal | golden, rerun | 0 of 29 | 0 of 7 | 0 of 4 | yes |
  | Code, no addendum | golden | 29 of 29 | 7 of 7 | 4 of 4 | no |
  | Code, no addendum | produced | 21 of 21 | 0 of 7, timestamps invented | 1 of 1 | no |
  | Code, no addendum | golden without its PARSER RULE line | 28 of 28 | 0 of 7, timestamps invented | 4 of 4 | yes, a "- [x]" checklist |
  | Code + rules 1-3 | golden without its PARSER RULE line | 28 of 28 | 7 of 7 | 4 of 4 | no |
  | Code + rules 1-3 | produced | 21 of 21 | 7 of 7 | 1 of 1 | no |
  | Code + rules 1-3 | golden | 29 of 29 | 7 of 7 | 4 of 4 | no |
  | **Code + final rules 1-4** | golden | 29 of 29 | 7 of 7 | 4 of 4 | no |
  | **Code + final rules 1-4** | produced | 21 of 21 | 7 of 7 | 1 of 1 | no |
  | **Code + final rules 1-4** | Top-N list | 35 of 35 | 8 of 8 | 6 of 6 | no |
  | **Code + final rules 1-4** | predictions | none in this format | 8 of 8 | none in this format | no |

  With the addendum, the code agent's rewrites grew chapter dialogue by 5 to 8%
  on Pro scripts (15% on the shorter predictions script) and added no dashes,
  contractions, or no-break spaces to them. It does not force the 7-chapter
  "5 things" structure from the portal prompt: it treated 10 tools in 8
  chapters and 6 predictions in 8 chapters as variants and kept every chapter.
  On the predictions script it kept the writer's existing heading timestamps,
  added none, and added 4 contractions; only Pro scripts forbid contractions
  (their header line says so). It also normalizes dashes inside an appended
  B-Roll table, with every row intact.

  **Finding: the live app's Flow Analysis step is a silent no-op** on any script
  with production blocks. The portal agent dropped every placeholder in all three
  runs, so `_restore_or_keep` keeps the original script. Both agents report
  `claude-opus-5-5`, so the gap is the prompt and request, not the model. Had the
  portal rewrites been applied, they would also have brought em-dashes, revision
  notes, a "Let me know…" sign-off, and a narrow no-break space inside "Chapter 1"
  that the app's `[ \t]` chapter regexes miss.

  ```bash
  maf/.venv/bin/python maf/agents/repeat_flow.py --compare --dump /tmp/flow_cmp
  maf/.venv/bin/python maf/agents/repeat_flow.py --compare --code-only --script-file s.md
  ```

- **`agents/shorten.py`** — `Script-Shorten-Agent` as code: the first
  non-Claude conversion (`gpt-6-astra` via `FoundryChatClient`) and the second
  transform agent, since the shortened script replaces the user's when "Shorten
  script" is checked. It is a drop-in for
  `ScriptShortenAgentClient.shorten_to_target()`: same request and same
  per-chapter retry request (both checked byte-for-byte), same keys, and the
  content-filter fallback is ported. Two fixes: a reply cut off by `max_tokens`
  fails instead of being saved, and the chapter splitter accepts
  `Heading: Chapter N` lines. **The client's splitter finds no chapters in
  Pro-format scripts, so its content-filter fallback can never run on them.** A
  fake agent that blocks the full script confirmed the fix: 8 chapter calls,
  every placeholder kept.

  `--compare` reproduces the app's target rule (`--percent`, default 25, or
  `--video-length` at 150 wpm) and its own Host-word counter, then scores what
  the app would save: placeholders kept, Host words against the target (the
  prompt promises ±10%), chapters, headings, trailing sections, notes, and
  punctuation. The code agent runs the captured prompt plus a two-rule
  `APP_CONTRACT`: keep every placeholder, and never drop items from a list the
  script counts out. `MAF_SHORTEN_APP_CONTRACT=0` turns it off.

  Validated 2026-10-07 with 25% cuts:

  | Agent | Script | Placeholders kept | Host words vs target | Within ±10% |
  |---|---|---|---|---|
  | Portal | golden | 29 of 29 | 1626 of 1384 (117%) | no |
  | Portal | produced | 21 of 21 | 2176 of 1820 (120%) | no |
  | Portal | Top-N list | 35 of 35 | 1882 of 1694 (111%) | no |
  | Code, no addendum | golden | 29 of 29 | 1394 (101%) | yes |
  | Code, no addendum | produced | 21 of 21 | 1757 (97%) | yes |
  | Code, no addendum | Top-N list | 35 of 35 | 1682 (99%), but cut "Ten mistakes, ten seconds" to 3 items | yes |
  | **Code + addendum** | golden | 29 of 29 | 1398 (101%) | yes |
  | **Code + addendum** | Top-N list | 35 of 35 | 1708 (101%), all 10 items kept | yes |

  Every run kept all chapters, headings, and trailing sections, and added no
  notes, dashes, or contractions. Unlike Repeat-and-Flow, the portal Shorten
  agent keeps the placeholders, so the live Shorten step works; it just cuts
  less than asked.

  ```bash
  maf/.venv/bin/python maf/agents/shorten.py --compare --dump /tmp/shorten_cmp
  maf/.venv/bin/python maf/agents/shorten.py --compare --code-only --percent 30 --script-file s.md
  ```

`agents/_common.py` holds the shared recipe (load captured instructions, build
the code agent, retry transient DNS blips, call the portal agent by name, warn
when a reply hits `max_tokens`). For the agents that rewrite the script,
`agents/_production_blocks.py` ports the app's production-block masking and
`agents/_script_metrics.py` holds the `--compare` scoring, including the app's
own Host-word counter (checked identical to both copies in `web_gui.py`). Each
new conversion is mostly its own prompt, parser, and `--compare` scoring.

Remaining portal agents to convert: Topic-Assistant, Writer, Reviewer, Polisher
(only the legacy console UI calls it), Youtube-Upload-Details (gpt-6-astra, and
actually needs web search for tool URLs), Quotes-and-Statistics (grok-4.7),
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
