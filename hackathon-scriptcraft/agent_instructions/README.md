# Azure Foundry Agent — System Instruction Reference

Verbatim copies of the system instructions configured in **Azure AI Foundry** for
each agent this app calls. This is the **source of truth for the Microsoft Agent
Framework migration** — when we re-create these agents in code (MAF
`ChatClientAgent`s), the prompt starts from the matching file here.

- One file per agent, named by its Foundry agent name (e.g. `Script-Writer-Agent.md`).
- Content is copied **verbatim** from the Foundry portal. Don't hand-edit except to
  resync from Foundry; note the capture date in each file's header comment.
- Agent IDs below are read from the client code under
  [`linedrive_azure/agents/`](../linedrive_azure/agents/).

## Capture status

All 15 Foundry agents are captured, and every file's instructions match the
live portal agent (verified through the Foundry API on 2026-10-07; headers
resynced to the live version and model that day). Agent names are the v2
Foundry names; the app's clients resolve them by name.

| Foundry agent | Live version | Portal model | Called by | Code agent (maf/agents/) |
|---|---|---|---|---|
| [Script-Topic-Assistant-Agent](Script-Topic-Assistant-Agent.md) | v13 | claude-opus-5-5 | pipeline, teaching | `pipeline.py` |
| [Script-Topic-Assistant-List-Agent](Script-Topic-Assistant-List-Agent.md) | v2 | claude-opus-5-5 | pipeline, list | `pipeline.py` |
| [Script-Topic-Assistant-Predictions-Agent](Script-Topic-Assistant-Predictions-Agent.md) | v3 | claude-opus-5-5 | pipeline, predictions | `pipeline.py` |
| [Script-Writer-Agent](Script-Writer-Agent.md) | v15 | claude-opus-5-5 | pipeline, teaching | `pipeline.py` |
| [Script-Writer-List-Agent](Script-Writer-List-Agent.md) | v3 | claude-opus-5-5 | pipeline, list | `pipeline.py` |
| [Script-Writer-Predictions-Agent](Script-Writer-Predictions-Agent.md) | v2 | gpt-5-mini | pipeline, predictions | `pipeline.py` |
| [Script-Reviewer-Agent](Script-Reviewer-Agent.md) | v8 | claude-opus-5-5-2 | pipeline, teaching | `pipeline.py` |
| [Statistics-and-Quotes-Finder-Agent](Statistics-and-Quotes-Finder-Agent.md) | v13 | grok-4.7 | pipeline, teaching | `quotes_stats.py` |
| [Script-Hook-and-Summary-Agent](Script-Hook-and-Summary-Agent.md) | v10 | claude-opus-5-5 | pipeline + web app | `hook_summary.py` |
| [Script-bRoll-Agent](Script-bRoll-Agent.md) | v11 | claude-opus-5-5 | web app | `broll.py` |
| [Script-Repeat-and-Flow-Agent](Script-Repeat-and-Flow-Agent.md) | v8 | claude-opus-5-5 | web app | `repeat_flow.py` |
| [Script-Shorten-Agent](Script-Shorten-Agent.md) | v8 | claude-opus-5-5 | web app | `shorten.py` |
| [Script-Youtube-Upload-Details-Agent](Script-Youtube-Upload-Details-Agent.md) | v11 | claude-opus-5-5 | web app | `youtube_details.py` |
| [Script-Polisher-Agent](Script-Polisher-Agent.md) | v8 | claude-opus-5-5 | legacy console UI only | `polisher.py` |
| [Script-Demo-Assistant-Agent](Script-Demo-Assistant-Agent.md) | v6 | claude-opus-5-5 | nothing (its prompt is an old Topic Assistant copy) | `pipeline.py` |

The clients for **Tournament-Agent** and **AI-Tips-Agent** reference agents that
no longer exist in the Foundry project, so there is nothing to capture for them.

Code agents follow the model policy (2026-10-07): Claude Opus 5.5 everywhere,
except Quotes-and-Statistics on Grok 4.7 through xAI (for X search). The
Reviewer uses the second Opus 5.5 deployment, `claude-opus-5-5-2`, as the
portal does.

## Three video archetypes (manual picker in Create Script)

The app will offer **three explicit format types**, each routing to its own agent
pair:

1. **Teaching listicle (5 things)** — the original prompts at the top of this file
   (`Script-Topic-Assistant-Agent` + `Script-Writer-Agent`). Distills to exactly 5,
   tutorial/how-to, quick-win framing.
2. **Bold predictions / visionary** — honors the requested count, one prediction
   per chapter, cinematic, no teaching / "already here" framing.
3. **Top-N list / countdown** — honors the requested count, lists ALL N, ranked
   countdown, practical present-day tone, not a tutorial.

### New archetype agents (DRAFT — create these in Foundry)

| Proposed agent | Archetype | Draft prompt | Status |
|---|---|---|---|
| Script-Topic-Assistant-Predictions-Agent | Predictions | [file](Script-Topic-Assistant-Predictions-Agent.md) | ✅ created in Foundry (name confirmed) |
| Script-Writer-Predictions-Agent | Predictions | [file](Script-Writer-Predictions-Agent.md) | ✅ created in Foundry (name confirmed) |
| Script-Topic-Assistant-List-Agent | Top-N list | [file](Script-Topic-Assistant-List-Agent.md) | ✅ created in Foundry (name confirmed) |
| Script-Writer-List-Agent | Top-N list | [file](Script-Writer-List-Agent.md) | ✅ created in Foundry (name confirmed) |

Wiring still needed (one pass once the Top-N agents exist): three-way format
picker in Create Script → `format` param through `/create` → route to the matching
agent pair → raise `max_chapters` (currently 8) to N+2 for the list/predictions
types → skip the teaching-only quotes + review steps for the non-teaching types.

## How to add the next one

Paste the agent's system instructions and I'll drop them into
`<Foundry-Agent-Name>.md` verbatim (with a capture-date header) and flip its row
above to ✅.
