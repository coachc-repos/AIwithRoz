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

## Step 3 (done) — all 15 portal agents -> code

Each portal agent is now a code-defined MAF agent seeded from its captured
`../agent_instructions/*.md` (all 15 verified identical to the live portal
prompts on 2026-10-07). Retire a portal copy only after its checks pass.

### Model policy, web search, and how the agents were tested

- **Models.** Every code agent runs Claude Opus 5.5 (`claude-opus-5-5`) on the
  Foundry deployment, except Quotes-and-Statistics, which runs Grok 4.7 through
  xAI so it can search X. The Reviewer uses the second Opus 5.5 deployment,
  `claude-opus-5-5-2`, as the portal does, so parallel reviews do not compete
  with the writers. `--compare` prints the code and portal models and flags a
  mismatch (the portal moved Shorten, YouTube, Demo-Assistant, and the List
  writer to Opus 5.5 on 2026-10-07 03:22 UTC, after their prompts were captured).
- **Web search is a function tool.** Claude agents get a `web_search` function
  (`_common.make_web_search_tool`): `gpt-5.4-mini` runs Foundry's hosted web
  search and returns findings with URLs, and Claude writes its own reply. Do not
  attach Foundry's hosted web search to a Claude agent directly. It runs (the MAF
  docs say Azure-OpenAI-only), but whenever a search fires the returned text
  stops following the agent's formatting rules:

  | Code replies on recorded app calls | Searches | Curly quotes | No-break spaces | Dashes |
  |---|---|---|---|---|
  | Teaching writer | none | 0 | 0 | 0 |
  | List writer | 1 each | 5 | 24 | 11 |
  | Reviewer | 3 of 7 | 42 | 1 | 27 |
  | Reviewer, same calls, function-tool search | 2 of 7 | 0 | 0 | 0 |

  Every portal agent has that hosted tool attached, which explains its format
  failures in the app: `"##  "` double-space headings (the Quotes and YouTube
  parsers match nothing), a B-Roll table without pipes (zero rows parsed), a
  narrow no-break space inside "Chapter 1", and, on one code run, a revised
  script returned twice.
- **Parallel tool calls on Claude.** Foundry's Responses adapter returns only
  the last of several parallel tool calls, so extra parallel searches are
  dropped. When streaming, it also cuts each call's argument deltas against one
  shared buffer, so the joined deltas are invalid JSON. Local runs do not
  stream, but the Foundry hosting server always does. Before the fix, hosted
  Topic, Topic-Predictions, Reviewer, and Demo stopped with "Function invocation
  limit reached" after three "Argument parsing failed" tool results.
  `_common.FoundryClaudeChatClient` builds each streamed call from its final
  `response.output_item.done` event instead, and `testing/offline_checks.py`
  replays the broken event sequence. Each search also has a 120-second limit,
  because one Foundry web search hung for the client's full 600 seconds.
- **Which agents search.** All Claude agents have the function except the three
  Writers, which work from the Topic plan (switch `web_search=True` in
  `pipeline.SPECS` to give them search). The Writers also get a length rule, to
  keep "around N words" chapters within 20% of N. Quotes-and-Statistics uses xAI's own
  X search and web search, capped with `max_turns` (an unbounded full-script
  request ran over ten minutes).
- **Throttling.** `claude-opus-5-5` has 78 capacity units; the app's pipeline
  writes up to eight chapters in parallel and hits HTTP 429. `run_with_retry`
  backs off on 429 and on DNS blips.
- **Testing.** Standalone agents run live `--compare` (code and portal on the
  same input). The pipeline agents (Topic, Writer, Reviewer, Quotes, Hook) are
  tested by replay: `testing/capture_pipeline.py` runs the APP's real pipeline
  with the portal agents and records every message it sends; `--replay` sends
  the same messages to the code agents and scores both replies with the app's
  own parsing. Recorded runs: teaching, Top-N list, and predictions.

- **`agents/broll.py`** — `Script-bRoll-Agent` as code (claude-opus-5-5 via
  `FoundryChatClient`, seeded from the captured instructions). `--compare` runs
  the code agent and the portal agent on the same script and prints both tables +
  row/section stats. Validated: both produce well-formed B-Roll tables
  (Timecode | Search Term | Description | Scene Context) with the
  `## Animation Suggestions` section. Re-validated with the `web_search`
  function: 21 pipe-table rows (2 searches). One portal reply in testing was a
  plain-text table with no pipes, which the app's B-Roll parser reads as zero
  rows (no EDL markers, no per-row Grok prompts).

  ```bash
  maf/.venv/bin/python maf/agents/broll.py --compare
  maf/.venv/bin/python maf/agents/broll.py --script-file path/to/script.md
  ```

- **`agents/hook_summary.py`** — `Script-Hook-and-Summary-Agent` as code (same
  model, `web_search` function attached). It is a **drop-in** for
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
  agent's summary ran 184 words against a 90-135 target. `--replay` on the app's
  recorded calls (teaching, list, predictions): both agents parse into 3 hooks,
  opening, summary, 3 thumbnail lines, and flow analysis every time.

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

  With Foundry's hosted web search attached, one code run returned the revised
  script twice. With the `web_search` function it is clean again: 29 of 29
  placeholders, 7 of 7 headings, 4 of 4 trailing sections, one search. The
  parser also accepts "Flow issues found:" as well as "Flow Issues Identified:".

  ```bash
  maf/.venv/bin/python maf/agents/repeat_flow.py --compare --dump /tmp/flow_cmp
  maf/.venv/bin/python maf/agents/repeat_flow.py --compare --code-only --script-file s.md
  ```

- **`agents/shorten.py`** — `Script-Shorten-Agent` as code on `claude-opus-5-5`
  (the portal agent's model since its v8; this module first ran `gpt-6-astra`
  from a stale capture header, which made the first comparison cross-model). It
  is the second transform agent: the shortened script replaces the user's when
  "Shorten script" is checked. It is a drop-in for
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
  script counts out. `MAF_SHORTEN_APP_CONTRACT=0` turns it off. It also adds a
  **correction pass** the app client lacks: if the reply is still more than 10%
  over the target, the shortened script goes through the same request once more,
  and the second reply is kept only if it is closer and keeps every placeholder.
  On Opus 5.5 the first pass alone landed at 111-114% on the golden script.

  Validated 2026-10-07 with 25% cuts (the first code rows ran `gpt-6-astra`):

  | Agent | Script | Placeholders kept | Host words vs target | Within ±10% |
  |---|---|---|---|---|
  | Portal | golden | 29 of 29 | 1626 of 1384 (117%) | no |
  | Portal | produced | 21 of 21 | 2176 of 1820 (120%) | no |
  | Portal | Top-N list | 35 of 35 | 1882 of 1694 (111%) | no |
  | Code (gpt-6-astra), no addendum | golden | 29 of 29 | 1394 (101%) | yes |
  | Code (gpt-6-astra), no addendum | produced | 21 of 21 | 1757 (97%) | yes |
  | Code (gpt-6-astra), no addendum | Top-N list | 35 of 35 | 1682 (99%), but cut "Ten mistakes, ten seconds" to 3 items | yes |
  | Code (gpt-6-astra) + addendum | golden | 29 of 29 | 1398 (101%) | yes |
  | Code (gpt-6-astra) + addendum | Top-N list | 35 of 35 | 1708 (101%), all 10 items kept | yes |
  | **Code (Opus 5.5), final** | golden | 29 of 29 | 1416 (102%); first pass 1533 (111%), corrected | yes |
  | **Code (Opus 5.5), final** | produced | 21 of 21 | 1991 (109%), no correction needed | yes |
  | **Code (Opus 5.5), final** | Top-N list | 35 of 35 | 1860 (110%), all 10 montage items kept | yes |

  Every run kept all chapters, headings, and trailing sections, and added no
  notes, dashes, or contractions. Unlike Repeat-and-Flow, the portal Shorten
  agent keeps the placeholders, so the live Shorten step works; it just cuts
  less than asked.

  ```bash
  maf/.venv/bin/python maf/agents/shorten.py --compare --dump /tmp/shorten_cmp
  maf/.venv/bin/python maf/agents/shorten.py --compare --code-only --percent 30 --script-file s.md
  ```

- **`agents/pipeline.py`** — the seven agents the script pipeline calls with
  messages it builds itself: Topic Assistant and Writer for each format
  (teaching, list, predictions) and the Reviewer, plus the Demo-Assistant (not
  called by the app; its portal prompt is an old Topic Assistant copy, so it is
  tested as a topic planner). The drop-in surface is message-level: `send()`
  returns the same dict as `BaseAgentClient.send_message`. Scoring ports the
  pipeline's own parsing: the chapter list it extracts from a Topic reply (with
  its list/predictions cap of N + 2), the writer refusal check, and the
  Reviewer clean-up.

  Two app-contract rules, both from replay evidence. **Topic:** write
  "Chapter N:" only in the outline's chapter headings; one code reply listed
  "- **Chapter 3:** Dana's saved context note (...)" above the outline, so the
  app would have planned two bogus chapters and dropped the real recap.
  **Writers:** no web search, and keep "around N words" chapters within 20% of N.

  Topic Assistants, replayed on the app's recorded planning calls (the chapters
  the app extracts, against its cap):

  | Format | Code, with the chapter-heading rule | Portal |
  |---|---|---|
  | Teaching | 7 of 8, "The 5 AI Habits Quietly Eating…" to "Your Five Habit Fix Cheat Sheet" | 7 of 8 |
  | List | 10 of 10, after 3 searches drawing on 22 sources | 10 of 10 |
  | Predictions | 8 of 8, "Monday Morning, Twenty Thirty" to "A Workday Worth Waking Up For" | 8 of 8 |

  With the rule, "Chapter N:" appeared only in the 7 outline headings (49 other
  references used "Ch N"). Without it, one teaching run would have planned two
  bogus chapters and lost the recap.

  Writers, replayed on every recorded chapter (spoken Host words, the unit of
  the pipeline's length targets):

  | Writer and target | Chapters | Code | Portal | Whole script, code vs portal |
  |---|---|---|---|---|
  | Teaching, "300+ words" | 7 | 416-632, all above 300 | 408-735 | 3,491 vs 3,703 words |
  | List, "around 120 words" | 10 | avg 142, 8 of 10 within 20% | avg 108, 6 of 10 | 9.5 vs 7.2 minutes |
  | Predictions, "around 150 words" | 8 | avg 178, 6 of 8 within 20% | avg 138, 8 of 8 | 9.5 vs 7.4 minutes |

  The capture asked for "8-10 minutes": the code List and Predictions scripts
  land inside it and the portal's fall short. All 25 code chapters succeeded
  with zero formatting quirks and no refusals (the portal's List and Predictions
  chapters had 47 and 9 quirks). The code teaching writer opens chapter 1 with a
  "FINAL HOOK:" block, following the golden reference; the app offers it as the
  "Current FINAL HOOK" hook option and finalize-hook keeps a single FINAL HOOK.

  The Reviewer replied in the required "REVISED CHAPTER:" format on all 7
  recorded chapters with zero formatting quirks (the portal: 14-22 quirks on the
  three chapters where it searched, and the marker missing once). The
  Demo-Assistant, given the app's teaching topic request, planned 7 chapters as
  the portal did.

  ```bash
  maf/.venv/bin/python maf/agents/pipeline.py --replay CAPTURE_DIR [--agent NAME]
  maf/.venv/bin/python maf/agents/pipeline.py --replay CAPTURE_DIR \
      --as-agent Script-Demo-Assistant-Agent --from-agent Script-Topic-Assistant-Agent
  ```

- **`agents/quotes_stats.py`** — `Statistics-and-Quotes-Finder-Agent` on Grok
  4.7 through xAI's Responses API with **X search** and web search (MAF's OpenAI
  client passes xAI's tool definitions through and treats xAI's `x_*` calls as
  informational). Drop-in for `generate_quotes_and_statistics()` (request and
  parser checked identical). A sourcing addendum: search X first and use at
  least one real X post when one exists, exact quotes only, and a **Link:** line
  under every quote and statistic (the app's parser only counts the
  "**Quote N:**" labels, so extra lines are safe). `MAF_QUOTES_SOURCING=0` and
  `MAF_QUOTES_MAX_TURNS` (default 8) control it.

  | Run | Quotes + stats the app counts | Links (X posts) | From own searches | Dates in 18 months | Searches |
  |---|---|---|---|---|---|
  | Portal, golden | 0 + 0 | 0 | n/a | 0 of 0 | 1 web |
  | Code, golden | 3 + 3 | 5 (2) | 4 | 6 of 8 | 10 web, 8 X |
  | Portal, app's recorded teaching call | 0 + 0 | 0 | n/a | 0 of 0 | n/a |
  | Code, same call | 3 + 3 | 6 (1) | 6 | 8 of 8 | 16 web, 6 X |

  The portal's "0 + 0" is real in the app: its headings read `"##  📊"` with two
  spaces, and its "quotes" included "Paraphrased from the script's guidance" and
  a statistic dressed as a quote. The code agent's quotes in testing were real X
  posts (Ethan Mollick, Gary Marcus) and sourced articles (EBU and BBC, KPMG).

  ```bash
  maf/.venv/bin/python maf/agents/quotes_stats.py --compare --dump /tmp/quotes_cmp
  maf/.venv/bin/python maf/agents/quotes_stats.py --replay CAPTURE_DIR
  ```

- **`agents/youtube_details.py`** — `Script-Youtube-Upload-Details-Agent` as
  code. Drop-in for `generate_upload_details()`: the ~17K-character request
  (checked byte-for-byte), the client's refusal retry, its `extract_*` helpers,
  and its timestamp check. On the golden script the app extracts a title,
  filename, 30 tags, a 3,113-character description with 10 tool links (from 2
  searches), and 19 timestamps, none past the script's duration. From the portal
  reply it extracts nothing: its `"##  📁"` headings miss the client's regexes,
  so the app gets "Untitled Video", no tags, and no description.

  ```bash
  maf/.venv/bin/python maf/agents/youtube_details.py --compare --dump /tmp/yt_cmp
  ```

- **`agents/polisher.py`** — `Script-Polisher-Agent` as code (only the legacy
  console UI calls it). Drop-in for `polish_script()` (request checked
  identical), plus a markup addendum: keep "Heading:" lines, "Host:" labels, and
  `[PRODUCTION BEGIN]` / `[PRODUCTION END]` exactly. The portal agent rewrote 40
  of 58 production markers as `[PRODUCTION_BEGIN]` (the app's regex needs the
  space); the code agent with the addendum kept all 7 headings and damaged no
  markers, with the original text unchanged and 17 visual cues added.

- **`agents/registry.py`** maps every Foundry portal name to its code agent's
  builder (used by the hosted entry point). **`testing/capture_pipeline.py`**
  records the app's real pipeline calls for replay (run it with the app's
  interpreter).

`agents/_common.py` holds the shared recipe (load captured instructions, build
the code agent, retry transient DNS blips, call the portal agent by name, warn
when a reply hits `max_tokens`). For the agents that rewrite the script,
`agents/_production_blocks.py` ports the app's production-block masking and
`agents/_script_metrics.py` holds the `--compare` scoring, including the app's
own Host-word counter (checked identical to both copies in `web_gui.py`). Each
new conversion is mostly its own prompt, parser, and `--compare` scoring.

All 15 portal agents now have code versions. The clients for Tournament-Agent
and AI-Tips-Agent point at agents that no longer exist in the Foundry project.

### Findings in the live app (v2 unchanged; "fixed in v3" = `scriptcraft-app-v3`)

- **Flow Analysis never runs.** The Repeat-and-Flow client reads the reply from
  a `messages` field that only the retired classic Assistants API returned, so
  every call ends in "No response" and the app keeps the original script.
  Even with that fixed, the portal agent drops the production-block
  placeholders, which also makes the app keep the original. Fixed in v3, which
  reads the reply and uses the code agent that keeps placeholders.
- **List and Predictions scripts always end in "Sequential workflow error".**
  `enhanced_autogen_system.py` skips the review step for those formats before it
  creates `revision_feedback`, then reads it at the end (UnboundLocalError).
  Fixed in v3 by binding it, and `chapter_comparisons`, before the review step.
- **The portal agents' hosted web search breaks the app's parsers** (see Web
  search above): Quotes and YouTube extraction return nothing, B-Roll tables can
  come back without pipes.
- **The portal Quotes agent invents quotes** ("Paraphrased from the script's
  guidance") and adds no links.
- **`claude-opus-5-5` capacity (78) throttles the pipeline.** Parallel chapter
  writes hit HTTP 429; the app's Claude fallback then needs `ANTHROPIC_API_KEY`.
- **The Shorten client's content-filter fallback never runs on Pro scripts**:
  its splitter ignores "Heading: Chapter N" lines. Fixed in v3.
- **Hook-and-Summary drops the parsed opening statement**, so the Process
  Script flow's "📺 OPENING STATEMENT" section is always empty. Fixed in v3. Its
  header regex can also match preamble text; the code agent's replies parse
  correctly, so v3 leaves the regex alone.
- The saved "10 AI Tools, 10 Mistakes" script ends with a B-Roll table from a
  different video (a 2030 grocery bill).

## Step 4 (done) — host the code agents in Foundry

Every code agent runs as a Foundry **hosted agent**, so it appears in the
Foundry portal's Agents list (Build > Agents) next to its prompt agent, named
`<portal name>-MAF` (for example `Script-bRoll-Agent-MAF`). You can open each in
the Playground, see its versions and status, and view runs under Agents >
Traces. Instructions and models live in this code, not in the portal; change
them here and redeploy.

- **`hosted/main.py`** serves one code agent through the Foundry Responses
  protocol (`agent_framework_foundry_hosting.ResponsesHostServer`, port 8088).
  The hosted agent's `MAF_AGENT` setting picks which one, so all 15 share one
  codebase. `MAF_HOSTED=1` switches the credential to the agent's own managed
  identity.
- **`hosted/deploy.py`** packs one zip (main.py, `agents/`, `observability.py`,
  and the captured prompts) and creates each hosted agent with Foundry's
  source-code deployment: no Docker and no container registry, because Foundry
  installs `hosted/requirements.txt` itself. Then it waits for each version to
  turn active and calls each agent once.
- **Cost:** hosted agents scale to zero. Each session gets its own sandbox
  (0.5 vCPU, 1 GiB here), billed only while active and released after 5 idle
  minutes.
- **Secrets:** the Quotes agent needs the xAI key, which deploy.py sets as an
  environment variable on that one hosted agent. Move it to Key Vault for
  production.

```bash
maf/.venv/bin/python maf/hosted/deploy.py --dry-run      # build the zip, list the plan
maf/.venv/bin/python maf/hosted/deploy.py                # deploy all 15, wait, smoke-test
maf/.venv/bin/python maf/hosted/deploy.py --only Script-bRoll-Agent
maf/.venv/bin/python maf/hosted/deploy.py --smoke-only   # re-test what is deployed

# local run of one hosted agent
MAF_AGENT=Script-bRoll-Agent maf/.venv/bin/python maf/hosted/main.py
curl -X POST http://localhost:8088/responses -H "Content-Type: application/json" \
     -d '{"input": "SCRIPT TITLE: x\n\nSCRIPT:\nHost: hello"}'
```

### Deployment results (2026-10-07)

All 15 hosted agents are active and pass `deploy.py`'s smoke test: one
Responses call each with a two-line script. A pass means a non-empty reply, no
"Function invocation limit reached", and no tool result that is an error. No
search fell back to the "web_search is unavailable" message.

| Hosted agent | Version | Time | Tool calls |
|---|---|---|---|
| Script-Demo-Assistant-Agent-MAF | 3 | 61 s | 2 |
| Script-Hook-and-Summary-Agent-MAF | 3 | 52 s | 1 |
| Script-Polisher-Agent-MAF | 3 | 68 s | 2 |
| Script-Repeat-and-Flow-Agent-MAF | 3 | 25 s | 0 |
| Script-Reviewer-Agent-MAF | 3 | 145 s | 5 |
| Script-Shorten-Agent-MAF | 3 | 15 s | 0 |
| Script-Topic-Assistant-Agent-MAF | 3 | 116 s | 5 |
| Script-Topic-Assistant-List-Agent-MAF | 3 | 50 s | 2 |
| Script-Topic-Assistant-Predictions-Agent-MAF | 3 | 58 s | 2 |
| Script-Writer-Agent-MAF | 3 | 104 s | 0 |
| Script-Writer-List-Agent-MAF | 3 | 35 s | 0 |
| Script-Writer-Predictions-Agent-MAF | 3 | 39 s | 0 |
| Script-Youtube-Upload-Details-Agent-MAF | 3 | 37 s | 0 |
| Script-bRoll-Agent-MAF | 4 | 28 s | 0 |
| Statistics-and-Quotes-Finder-Agent-MAF | 3 | 113 s | 8 (xAI X and web searches) |

The hosted Quotes agent on the golden script, with the app's verbatim request:

| Call | Time | Quotes / statistics (app parser) | Links | X posts |
|---|---|---|---|---|
| Plain | 117 s | 3 / 3 | 6 | 1 |
| Streaming | 122 s | 3 / 3 | 5 | 1 |
| Background | 117 s | 3 / 3 | 6 | 2 |

The X posts are real posts by Gary Marcus (April 2026) and Ethan Mollick
(2025), each quoted with a **Link:** line.

What it took to host:

- **Zip upload.** Pass the code to `create_version_from_code` as a
  `(filename, bytes, content type)` tuple. Bare bytes fail with "Code part
  filename must end with .zip".
- **File modes.** Zip entries need mode 0644. With 0600 the remote build cannot
  read `requirements.txt` and fails with "No Python dependency manifest found".
- **Streamed tool calls.** The hosting server always streams, which exposed the
  Foundry parallel tool-call bug (see "Parallel tool calls on Claude" in step 3).
  Topic, Topic-Predictions, Reviewer, and Demo failed until
  `FoundryClaudeChatClient` was in place.
- **Long calls.** One plain call to Quotes, sent right after deployment,
  returned HTTP 424 `proxy_timeout` ("agent container did not respond within
  ..."). Three repeats, plain, streaming, and background, each finished in
  about two minutes. For long runs from code, prefer `stream=True`, or
  `background=True` and poll `responses.retrieve`. The hosting server supports
  both.

**Where to see them:** Foundry portal > Build > Agents. Each hosted agent is
listed (type Hosted) next to its prompt agent, 30 agents in all. Open one for
its versions, Playground, and logs. Runs appear under Traces, because App
Insights is connected.

## Step 5 (done) — the v3 web GUI on the hosted agents

`scriptcraft-app-v3/` is a copy of the v2 GUI in which every migrated agent
runs on its hosted `-MAF` agent; v2 is unchanged. The switch lives in v3's
`linedrive_azure/agents/base_agent_client.py`: the app sends the same request
text, each call runs in background mode with polling, warm sessions are reused,
and every call prints `[maf]` lines that the Progress Log shows. List and
Predictions chapters, which v2 wrote with direct Claude calls, now go to the
hosted MAF writers first. v3 also fixes the app bugs marked "fixed in v3" above. See `scriptcraft-app-v3/README.md` for
how to run it and the end-to-end test results, and
`scriptcraft-app-v3/tests/offline_checks_v3.py` for the offline checks.

## Step 6 (done) — the Pro writer as a hosted agent

`agents/pro_writer.py` is the app's single-pass Pro writer as a code agent,
hosted as `Script-Writer-Pro-Agent-MAF`. It is not a portal agent. Its
instructions are a verbatim copy of `SCRIPT_WRITER_PRO_SYSTEM` from the v3 app
in `../agent_instructions/Script-Writer-Pro-Agent.md`. Regenerate the copy with
`maf/.venv/bin/python -m agents.pro_writer --sync` (run from `maf/`); an
offline check fails when the two differ. The app sends the same user message
as the classic writer, golden reference included. The agent runs
`claude-opus-5-5` through the Foundry Responses path with reasoning effort
"high" and 48,000 max tokens.

- **Reasoning effort works on the Responses path.** On a short prompt, effort
  low, default, and high gave 170, 257, and 312 output tokens.
- **Two Foundry endpoints can serve it.** By default it uses Foundry's
  OpenAI-style Responses endpoint on the project, like the other agents.
  Deploying with `MAF_PRO_PATH=anthropic` serves it from Foundry's Anthropic
  Messages endpoint on the account instead, through MAF's
  `AnthropicFoundryClient`. That is Claude's native request, with effort
  "high" and adaptive thinking, exactly as the classic writer asks Anthropic.
- **The Anthropic endpoint needs a role first.** The agent's own identity
  (`instance_identity.principal_id` on the agent, `0e026a6a-…` for
  `Script-Writer-Pro-Agent-MAF`) gets 401 on `POST /anthropic/v1/*` until it
  has a role with the data action
  `Microsoft.CognitiveServices/accounts/AIServices/providers/action` on the
  Foundry account. The built-in Cognitive Services User and Foundry User roles
  include it, but both also let the holder list account keys and connection
  secrets. A custom role with only that data action is the narrow option.
  After the grant, redeploy with
  `MAF_PRO_PATH=anthropic maf/.venv/bin/python maf/hosted/deploy.py --only Script-Writer-Pro-Agent`.
- **Output caps include hidden reasoning.** A hosted B-Roll run stopped
  mid-row at its 16,000-token cap with only about 4,000 tokens of visible
  table, and the app parsed the rows it got. B-Roll, YouTube, and the three
  Topic agents now allow 32,000. Writers and reviewers keep 16,000, since they
  write one chapter each and run seven at a time.
- **Why hosted agents are slower than portal agents.** The same model writes
  at the same speed on both paths, about 90 output tokens per second. On one
  captured Topic request the hosted agent produced 22% more output tokens
  for nearly the same visible text, and took 25% longer: 115 s against 92 s.
  The extra tokens are hidden reasoning. A new hosted session adds 10 to 20
  seconds, and the container itself adds under a second.

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
  `agent-framework-openai` (Grok via xAI), `agent-framework-foundry-hosting`
  (prerelease; `hosted/main.py`), `azure-identity`, `python-dotenv`,
  `microsoft-opentelemetry`. `hosted/requirements.txt` pins what Foundry
  installs for the hosted agents.
- The venv here resolves `azure-ai-projects` 2.6.x; the main app pins 2.1.0.
  Keeping MAF in its own venv avoids disturbing the running app until we
  reconcile dependencies at cut-over.
