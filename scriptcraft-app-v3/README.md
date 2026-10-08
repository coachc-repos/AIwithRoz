# ScriptCraft v3: the web GUI on MAF agents

v3 is a copy of the v2 web GUI (`scriptcraft-app-v2`, build 15.39) in which
every agent that was migrated to the Microsoft Agent Framework (MAF) runs on
its Foundry hosted agent, named `<portal name>-MAF`. The UI, the flows, and
the logs work as in v2. v2 is unchanged and can run alongside v3.

The MAF agents themselves (instructions, models, web search, deployment) live
in `scriptcraft-app-v2/maf/`. See its README for how they were built, tested,
and hosted.

## Run it

```bash
cd scriptcraft-app-v3
PORT=8082 python web_gui.py      # or ./start_web_gui.sh
```

Open http://localhost:8082. The tab title reads "ScriptCraft v3" and the header
badge reads "v3 · MAF agents". The default port is 8082 so v2 can keep 8080.
v3 needs the same Python packages as v2 (`requirements.txt` is unchanged) and
reads the same `.env`, `~/.scriptcraft` settings, and API keys.
`agent_instructions/golden_reference_script.md` is the golden reference that
Pro mode embeds and the pipeline's style block leads with. It is a copy of
v2's; the MAF agents' own prompts stay in `scriptcraft-app-v2/agent_instructions`.

## How the agents are called

`linedrive_azure/agents/base_agent_client.py` sends these agents to their
hosted MAF agent. The app's request text is unchanged, so its parsers are too:

| App client | Hosted agent |
|---|---|
| Topic Assistant, List, Predictions | `Script-Topic-Assistant-*-MAF` |
| Writer, List, Predictions | `Script-Writer-*-MAF` (primary for every format; see below) |
| Reviewer | `Script-Reviewer-Agent-MAF` |
| Quotes and Statistics | `Statistics-and-Quotes-Finder-Agent-MAF` (Grok 4.7 with X search) |
| Hook and Summary | `Script-Hook-and-Summary-Agent-MAF` |
| Repeat and Flow | `Script-Repeat-and-Flow-Agent-MAF` |
| Shorten | `Script-Shorten-Agent-MAF` |
| YouTube Upload Details | `Script-Youtube-Upload-Details-Agent-MAF` |
| B-Roll | `Script-bRoll-Agent-MAF` |
| Polisher (console UI only) | `Script-Polisher-Agent-MAF` |

- **Background mode.** Each call starts the hosted agent in background mode and
  polls until it finishes. Long plain calls can hit the Foundry gateway's
  timeout (HTTP 424 `proxy_timeout`). The app's per-call `timeout` still
  bounds each run, as in v2.
- **Warm sessions.** A hosted session that was used in the last 4 minutes is
  reused. A warm session answered in about 5 seconds and a new one in 11 to 20
  seconds. One session served four parallel calls without trouble.
- **Not migrated.** Tournament-Agent and AI-Tips-Agent have no MAF version and
  still use their portal agents. Demo packages come from a direct gpt-5-mini
  call, as in v2. The portal Script-Demo-Assistant-Agent is a copy of the Topic
  prompt that the app never calls.
- **Switch back.** `SCRIPTCRAFT_AGENT_BACKEND=portal` sends every agent to its
  portal prompt agent, which is the v2 behavior.
- **Throttling and timeouts.** Rate-limited runs get up to six retries with
  randomized backoff, separate from the app's own retry count. Hosted runs get
  at least 300 seconds (`SCRIPTCRAFT_MAF_MIN_TIMEOUT`), and a run that times
  out is retried once.

To test without touching your project folder, cloud script library, or idea
history, point v3 at a separate settings file and idea history, and turn off
the artifact upload:

```bash
echo '{"output_dir": "/tmp/scriptcraft-v3-test"}' > /tmp/v3_settings.json
SCRIPTCRAFT_SETTINGS_FILE=/tmp/v3_settings.json SCRIPT_ARTIFACTS_BLOB_CONTAINER= \
  SCRIPTCRAFT_IDEAS_HISTORY_FILE=/tmp/v3_ideas.json PORT=8083 python web_gui.py
```

## Script Writer control

The Create Script form has a three-way **Script Writer** control. The Idea
Generator shows the same three options once you select an idea, so you can
pick the writer before or after the brief is written; changing either one
changes both. The last choice is remembered in the browser, and Re-run Last
restores it.

| Option | What writes the script |
|---|---|
| ⭐ Pro writer · classic | One Claude Opus 5.5 pass through the Anthropic API, as in v2 |
| 🤖 Pro writer · agent | The same prompt and request, run by the hosted `Script-Writer-Pro-Agent-MAF` on the Foundry Claude deployment, through Foundry's Anthropic endpoint |
| 🧩 Agentic script writing | Topic Assistant, chapter Writers, Reviewer, Quotes and Hook agents; the Video Format list appears for this option |

Both Pro options build their request with `build_pro_user_message` in
`linedrive_azure/agents/pro_script_writer.py`, so a comparison changes only
the serving path. The agent streams its reply, so the Progress Log keeps the
"📝 writing…" word counts. If the agent fails, the run falls back to the
classic writer and says so in the log. The create request carries the choice
as `video_format: "pro"` plus `pro_writer: "classic" | "agent"`.

The Pro prompt requires 7 or 8 chapters of about 250 to 400 spoken words. It
used to let the model pick the chapter count, so a seven-prediction brief came
back as 6 chapters with paired items of about 500 words each, and each
chapter's two HeyGen calls ran long. On the same brief the fixed prompt wrote 8
chapters of 167 to 307 spoken words. The writer logs the chapter count after
every run.

## Logs

Every hosted call prints lines tagged `[maf]`. The Progress Log shows them at
the current progress, so you can see which agent ran, what it searched, and how
long it took:

```
⏱️ [maf] Running Script-Topic-Assistant-Agent-MAF (hosted MAF agent, timeout=300s)...
   🔎 [maf] Script-Topic-Assistant-Agent-MAF: web_search "NotebookLM source limits 2026"
✅ [maf] Script-Topic-Assistant-Agent-MAF completed in 41.2s, 2 tool call(s)
```

Each run also appears in the Foundry portal under its `-MAF` agent (sessions
and traces).

## Changes from v2

- **Agents** run on the hosted MAF agents, as described above.
- **List and Predictions runs finish.** In v2 every List and Predictions run
  ended in "Sequential workflow error": the review step is skipped for those
  formats before `revision_feedback` and `chapter_comparisons` exist, and the
  end of the workflow reads both. v3 binds them before the review step.
- **List and Predictions chapters use the MAF writers.** v2 wrote them with
  Claude Opus 5.5 directly, because the portal writer added dashes and curly
  quotes to countdowns. Those came from Foundry's hosted web search, which the
  MAF writers do not use. In v3 the hosted List and Predictions writers are
  primary (zero em dashes and zero curly quotes in the test chapters), and
  direct Claude is the fallback. `SCRIPTCRAFT_CLAUDE_PRIMARY_WRITER=1` restores
  the v2 order.
- **Flow Analysis works.** The Repeat-and-Flow client read the reply from a
  `messages` field that no backend returns, so in v2 every Flow Analysis ended
  in "No response" and the app kept the original script. v3 reads `response`.
- **The opening statement appears.** The Hook-and-Summary client parsed it but
  never returned it, so the GUI's "📺 OPENING STATEMENT" section stayed empty.
- **Shorten.** Its content-filter fallback now splits on `Heading: Chapter N`
  lines too, so it works on Pro scripts. If the first reply is more than 10%
  over the target, one correction pass runs, as in the MAF Shorten code. The
  second reply is kept only if it is closer to the target and keeps every
  production-block placeholder.
- **Current ideas, briefs, and predictions.** v2's Idea Generator told Claude
  to use "current 2026 events" without giving today's date, so an April 2026
  paper still counted as current, and Grok brainstormed with no search at all.
  Now both models get today's date and a 60-day window (`IDEA_RECENCY_DAYS`),
  and every idea ends with the news it builds on and that news's date. Grok
  searches X, limited to posts from the window, and the web. Claude gets up to
  8 searches and starts with broad "latest AI news" searches. The brief
  creator now searches the web too, and its 2026 TOUCHPOINTS must be current
  and dated. Both Pro writers get today's date and treat anything already
  underway as news, not a prediction. On "5 big AI predictions for 2027",
  every idea and the brief built on news from August to October 2026.
  Idea generation now takes about 3 minutes, mostly Claude's searches.
- **Labels and port.** The tab title, header badge, version (`3.0-maf`), and
  default port (8082) identify v3.

## Test results

Run on 2026-10-07 against the hosted agents (version 3), with v3 on port 8082
driven through the same HTTP endpoints the browser uses.

| Run | Agents exercised | Time | Result |
|---|---|---|---|
| Teaching, 1 chapter, with Hook, flow, 30% shorten | Topic, Writer, Reviewer, Quotes, Hook, Shorten, Flow | 633 s | Complete. Flow's reply was not read (the client bug above, fixed after this run). |
| List, 1 chapter, with Hook | List Topic, Hook (chapter by direct Claude, the v2 order) | 191 s | Complete, no "Sequential workflow error". |
| Predictions, 1 chapter, with Hook | Predictions Topic, Hook (chapter by direct Claude, the v2 order) | 140 s | Complete, no "Sequential workflow error". |
| Process Script on the golden script | Shorten, Hook, YouTube, B-Roll, Flow | 968 s | Complete. Opening statement present, 61 B-Roll rows, flow applied. |
| Teaching, 7 chapters, with Hook, YouTube, B-Roll, flow | All of the above; writers and reviewers in parallel | 1097 s | Complete. Flow report and 71 B-Roll rows; 6 of 7 reviews failed on rate limits (fixed after this run). |
| Teaching, 7 chapters, with Hook | Topic, 7 writers, 7 reviewers, Quotes, Hook | 561 s | Complete. All 7 reviews succeeded after 13 rate-limit retries. |
| List, then Predictions, 1 chapter each, MAF writers primary | List and Predictions Topic and Writer | 65 s, 61 s | Complete. Chapters from the hosted writers, no em dashes or curly quotes. |

The Progress Log showed every hosted call, its web searches, and the Quotes
agent's X searches. `tests/offline_checks_v3.py` covers the routing, the
background polling, rate-limit and timeout handling, the three client fixes,
and the Progress Log lines without calling a model.

Known limits:

- **Rate limits on the reviewer.** `claude-opus-5-5-2` allows 50,000 tokens per
  minute, so seven parallel chapter reviews are throttled and retried. The
  review step took about 3 minutes in the last run. Raising that deployment's
  capacity would shorten it.
- **Hosted calls are slower than portal calls.** A new session costs 10 to 20
  seconds. Topic took 2 minutes and Quotes 2 to 2.5 minutes in these runs.
- **Concurrent runs share log lines.** As in v2, the GUI captures output by
  swapping the process-wide stdout, so two runs started at the same time show
  each other's lines.
