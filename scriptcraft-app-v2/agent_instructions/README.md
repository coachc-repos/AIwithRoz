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

| Agent (Foundry name) | Agent ID | Client file | Captured |
|---|---|---|---|
| **Script-Writer-Agent** | `asst_gUvMkcUOwebEb4YWq0zfNMtb` | `script_writer_agent_client.py` | ✅ [Script-Writer-Agent.md](Script-Writer-Agent.md) |
| **Script-Topic-Assistant-Agent** | `asst_vqx6qOfUIEFnuKtb9XEyNtXK` | `script_topic_assistant_agent_client.py` | ✅ [Script-Topic-Assistant-Agent.md](Script-Topic-Assistant-Agent.md) |
| Script-Review-Agent | `asst_MeeUTGVUBItaslmikiJ1qhd9` | `script_review_agent_client.py` | ⬜ pending |
| **Statistics-and-Quotes-Finder-Agent** | `asst_bEMK0Y6mdB6yRVnv0WwIZXwd` | `quote_and_statistics_agent_client.py` | ⚠️ [captured, TAIL MISSING](Statistics-and-Quotes-Finder-Agent.md) |
| Script-Hook-and-Summary-Agent | `asst_IaM5FTf3cVZ33TjIatXwloWE` | `hook_and_summary_agent_client.py` | ⬜ pending |
| Script-bRoll-Agent | `asst_ILcqLMcj4zhGbIzUMTrcG73a` | `script_broll_agent_client.py` | ⬜ pending |
| Script-Shorten-Agent | `asst_script_shorten_v2_only` * | `script_shorten_agent_client.py` | ⬜ pending |
| Script-Repeat-and-Flow-Agent | `asst_pjVIL7vZnKQzK6x7DfEsa2Ai` | `script_repeat_and_flow_agent_client.py` | ⬜ pending |
| Script-Youtube-Upload-Details-Agent | `asst_3SXXgX7WbQmrgg2tGDgkynKV` | `youtube_upload_details_agent_client.py` | ⬜ pending |
| Script-Polisher-Agent | `asst_GhmZPA8ktCsrgFTUAgNbA8F6` | `script_polisher_agent_client.py` | ⬜ pending |
| Tournament-Agent | `asst_zBkNlAu4higVRIVKkNvqsrTC` | `tournament_agent_client.py` | ⬜ pending |
| AI-Tips-Agent | `asst_nkrKxpoA69zYpgs6IK8rdHgu` | `ai_tips_agent_client.py` | ⬜ pending |

\* The Shorten agent ID is referenced in code as a v2-only sentinel
(`asst_script_shorten_v2_only`); confirm the real Foundry ID when capturing it.

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
