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
Pro mode embeds and the pipeline's style block leads with. Since 2026-10-29 it
is the channel's best-performing script, and `channel_playbook.md` beside it
holds the patterns behind the channel's best analytics (see Changes from v2).
The MAF agents' own prompts stay in `scriptcraft-app-v2/agent_instructions`.

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
- **Warm sessions.** A hosted session that was used in the last 2 minutes is
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
- **One heading per chapter.** The List and Predictions writers' instructions
  ask for two heading lines per chapter, `## Chapter N: Title (X:XX)` and then
  `Heading: Chapter N - Title`. Those formats skip the review that used to
  collapse them, so their scripts showed most chapter titles twice and the
  GUI's chapter splitters saw an extra chapter start. Every agentic chapter now
  keeps exactly one `Heading: Chapter N - Title` line, the form Pro scripts use,
  after writing and again after review. The same runs printed the title block
  twice; a skipped review now passes the chapters on without their own title
  block. Repeat and Flow's check for a dropped Chapter 1 heading also recognizes
  `Heading:` lines now.
- **Acronyms in chapter titles.** The Topic plan's "de-shout" step, which tones
  down ALL-CAPS text that Azure's content filter flagged, also turned acronyms
  such as TSMC and ASML EUV into "Tsmc" and "Asml Euv". It now changes only
  lines that are actually shouting.
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
- **Thumbnails in the channel's style.** The 🖼️ thumbnail tool, and the
  pipelines' thumbnail step, now use Grok Imagine by default
  (`tools/media/grok_thumbnail_generator.py`). Claude plans each thumbnail in
  one of the channel's layouts (big number, headline, public figure, mystery
  scene, comparison), and `grok-imagine-image-2.0` renders it from the
  channel's own thumbnails in `tools/media/thumbnail_refs/`: 2 that show the
  host, matched to the planned expression, plus examples of the layout. Each
  thumbnail is saved at 1280x720 for YouTube (under its 2 MB limit), with the
  full-resolution original and a JSON of every concept and prompt in `full/`.
  The dialog's Engine menu switches back to Gemini, and
  `SCRIPTCRAFT_THUMBNAIL_ENGINE=gemini` makes Gemini the default. To add a
  reference, put the image in `thumbnail_refs/` and describe it in `refs.json`.
- **Keys saved in the API Keys dialog stick.** The dialog says saved keys
  override environment variables, but at startup the app loaded `.env` first
  and used a saved key only where nothing was set, so a key changed in the
  dialog reverted to the `.env` value at the next restart while the dialog
  still showed the new one. Saved keys now win at startup too.
- **Thumbnails up to 50 MB.** Publish to YouTube accepted thumbnails only up
  to 2 MB, YouTube's old limit; `thumbnails.set` now takes up to 50 MB, so the
  2K Grok originals (about 5 MB) upload as they are. If YouTube still refuses
  a large file for its size, the upload retries once with a JPEG copy under
  2 MB (`<name>_youtube.jpg`, full resolution when it fits).
- **Durations use HeyGen's real pace, 175 words per minute.** Hook videos
  from four episodes ran 170 to 177 wpm, so the old 150 wpm made every
  duration on the page (script badge, Load Script panel, hook picker) and the
  reading time about 17% too long. `HEYGEN_WPM` in `web_gui.py` and
  `templates/index.html`. Shorten-to-length targets, B-roll timecodes, YouTube
  timestamps, and the writers' word targets still plan at 150 wpm.
- **Reply to related posts on X.** In the X composer, after picking a
  published episode, "🔎 Find related posts" has Grok search X (last 2
  weeks) for up to 5 posts on the episode's subject and draft a reply to each
  (under 240 characters, no hashtags or links, never "my"). Copy a reply, or
  "↩ Reply on X" opens X's reply box with it filled in; "add video link"
  appends the episode link. A post is shown only if Grok's search actually
  returned it (its link is in the search citations). A search takes about a
  minute.
- **Title Picker.** The last Process Script stage: Claude Opus 5.5 reads the
  script and suggests 5 titles (under 70 characters, five different angles,
  only facts from the script). Pick one, or type your own, and it replaces the
  `Title:` line and a top `# ...` heading (or adds a `Title:` line when there
  is none); the YouTube section's own A/B titles are left alone. With other
  stages selected it opens when their run finishes, on the processed script.
  The thumbnail gallery no longer shows the "Generated Thumbnails (N
  variations)" heading.
- **Edit thumbnails with a prompt.** Under the thumbnail gallery, type a change
  ("change the 3 to a 9", "use Elon Musk instead of Roz") and Grok Imagine
  (XAI_API_KEY, the same key as Grok Imagine video) makes only that change and
  keeps the background, lighting, and style. The result is added as a new
  version you can edit again; earlier versions stay. The Generate Thumbnails
  dialog's "Start from a theme" opens the channel's reference thumbnails
  (`tools/media/thumbnail_refs/`, now 13 with the gold "9" and "BROKEN?"), or
  takes an uploaded image, as the starting point. An edit that names Roz also
  sends her reference photos so she stays recognizable. "📎 Include image"
  adds up to 3 images to an edit (a logo, a product shot; PNG transparency is
  kept), and the edit says where they go ("put the logo top-right"). Edits of
  a theme or upload are saved in `~/Dev/Thumbnails/edits/`; edits of a
  generated thumbnail are saved next to it. From the command line:
  `python tools/media/grok_thumbnail_generator.py --edit IMAGE "change" [--include LOGO]`.
  "💾 Save as…" and "💾 Save 2K as…" (the 2816×1584 original, for Grok
  thumbnails) open the browser's save dialog to pick the folder and name
  (Chrome and Edge; other browsers download to Downloads).
  Each gallery keeps its own state: galleries used to share element IDs, so
  with two on the page Apply edit could read the other gallery's empty box and
  appear to do nothing.
- **Replace existing Grok Imagine prompts.** The Process Script dialog's Grok
  Imagine Prompts stage has a "Replace existing prompts" option. It removes
  every `[GROK IMAGINE / RESOLVE]` prompt and its `[QUOTE CARD / RESOLVE]` line
  from the script body, drops production blocks left empty, and rescans for
  new ones. VERIFY notes, cold opens, overlays, and the trailing sections are
  kept, and if no new prompts come back the old ones stay. A paragraph that
  follows a VERIFY note or other non-Grok block can now get a prompt too, so a
  replaced Pro script ends up with about as many prompts as the writer made.
- **X keys in the API Keys dialog.** The dialog has fields for the five
  @AIwithRoz posting keys (X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN,
  X_ACCESS_SECRET, X_BEARER_TOKEN), saved and loaded like the other keys, so
  Post to X no longer needs `.env`.
- **Key values stay on this computer.** The dialog shows full key values, and
  the GUI listens on every network interface, so any device on the same
  network could read them from `/api/keys` (and `/api/grok/key`). Those
  endpoints now answer only a browser on this machine, or any browser once
  `APP_AUTH_TOKEN` is set and it has signed in. The sign-in form posts the
  token instead of putting it in the URL, where the access log recorded it.
- **Word counts are spoken words.** Every word count the app shows (the
  duration badge, the result's word count and reading time, the cloud script
  list, the Shorten step's Host-word counts, and the Pro writer's progress
  lines) now counts what the HeyGen avatar will speak:
  `console_ui/text_processing.spoken_word_count`, which the page's badge
  ports line for line. Before, the badge also counted the metadata block after
  the hook (Title:, Script-ID:, Audience:, Tone:), the server counted the whole
  file including the trailing research and packaging sections, and the two
  disagreed on 4 of 10 sample scripts. Now they match on all 93 saved scripts.
  The Process Script dialog's "Script loaded" line uses the same count, so a
  script with an appended HEYGEN READY SCRIPT copy is no longer counted twice.
  The HeyGen text also no longer includes the label "Summary:" when a summary
  line follows spoken text directly (12 of 93 scripts), or a chapter title line
  ("Chapter 2: Tell #1 (1:00-2:50)") that sits right under the previous
  paragraph (2 of 93 scripts).
- **Labels and port.** The tab title, header badge, version (`3.0-maf`), and
  default port (8082) identify v3.
- **Golden reference and channel playbook.** The golden reference is now the
  channel's best-performing script, "Musk Will Win the AI Race - Here is Why"
  (`agent_instructions/golden_reference_script.md`; Script-ID ld-80b7325091 in
  the cloud library, flagged reference and final). The Pro writers embed up to
  32,000 characters of it instead of 16,000 and are told to match its stance,
  hook and open loop, numbered structure, and verdict.
  `agent_instructions/channel_playbook.md` holds the patterns behind the
  channel's best click-through rate and average view duration: topics, titles,
  thumbnails, hook, and retention. Idea generation, briefs, both Pro writers,
  the agentic pipeline's style context, and the Title Picker all read it. Raw
  metrics stay out of the repo. The idea generator gets the golden reference
  as its model episode (title, spoken hook, chapter headings, and verdict, read
  from the file at each run). With no topic or document, about three of the
  ten ideas continue it: a sequel, the case against its verdict, or the same
  verdict frame applied to another player or race.
- **Provocative by default.** Ideas, briefs, and titles take a side, name who
  wins and who loses, and promise a verdict, while staying true and attributed.
  Ideas gain two formats, The Power Play and Follow the Money. The Grok
  thumbnail style guide favors the verdict or the conflict as on-image text.
- **📊 Analytics.** A toolbar dialog lists the channel's videos for their
  lifetime (the default) or the last 7, 28, 90, or 365 days. It shows views,
  average view duration and percentage, watch hours, likes, and subscribers,
  with sortable columns and total tiles. In a short window a video can have a
  few search views that left within a second, so YouTube reports a 0:00
  average. Averages from fewer than 10 views are greyed out, with the
  lifetime average on hover. Click a video to see its lifetime
  audience-retention curve, with its lifetime average-view mark and the three
  steepest drops (the opening and the end screen are left out). ⬇ CSV exports the table,
  and ✨ Analyze with Claude compares the top and bottom videos against the
  playbook. It uses its own read-only Google sign-in
  (`~/.scriptcraft/youtube_analytics_token.json`, with the same
  `youtube_client_secret.json` as publishing), so publishing is not affected.
  The Google Cloud project needs the YouTube Analytics API enabled. The
  Analytics API does not report thumbnail impressions or click-through rate,
  so they come from two places. **📡 Turn on daily reach reports** creates one
  read-only YouTube Reporting API job (`channel_reach_basic_a1`). YouTube posts
  its first reports within 48 hours, covering the 30 days before the job, then
  one a day. The dialog downloads new ones at most every 6 hours and keeps them
  in `~/.scriptcraft/youtube_reach_daily.json`, since YouTube deletes reports
  after 30 to 60 days. **⬆ Import Studio export** reads a YouTube Studio
  Advanced mode export (the .zip or its Table data.csv) into
  `~/.scriptcraft/youtube_studio_reach.json`. It covers that export's date
  range and is the only source for lifetime numbers. A window the daily reports
  reach back to uses them; otherwise the Studio import is used.
- **🎙️ ElevenLabs Audio.** A toolbar button (also on the HeyGen Script tab)
  reads the HeyGen script with one of your ElevenLabs voices and saves one
  MP3 in the script's output folder under `voiceover/`. It uses the
  HEYGEN READY SCRIPT section when the script has one; otherwise it extracts
  the spoken text the way the HeyGen stage does. The key goes in the API Keys
  dialog (`ELEVENLABS_API_KEY`), masked like the others. The dialog lists
  your own voices first, with ▶ Sample, and offers Eleven v4 (the default),
  Multilingual v2, and Flash v2.5. Similarity (75% by default) and, on
  Eleven v4, Clone Strength (professional voices; higher follows the training
  recordings more closely) are sent with the voice's other saved settings
  unchanged. It remembers the last voice, model, and sliders.
  Long scripts go in requests of about 3,000 characters, each passing the
  previous three request IDs (ElevenLabs request stitching) so the joins
  keep one delivery, and ffmpeg joins the parts. The Execution Log shows the
  start, each finished part, and the saved file. The key needs the Text to
  Speech and Voices (read) permissions; with User (read) the dialog also
  shows the credit balance.
- **🎬 HeyGen clips from the ElevenLabs audio.** Under the audio in the same
  dialog: pick one of the script's MP3s, one of your HeyGen templates, a
  **Max frames per clip** (default 9,000, the upscaler's limit), and the
  frame rate the limit is **Counted at** (default 30 fps, the upscaler's
  rate). HeyGen renders at 25 fps, as long as the audio rounded up to a
  whole frame, and the upscaler counts that length at its own rate. At
  30 fps, 9,000 frames is 5:00, so a clip HeyGen made with 7,855 frames
  (5:14) counts as 9,426. The app cuts the MP3 into the fewest clips whose
  frames, counted that way, stay under the limit with 3 frames to spare. A
  14:58 voiceover becomes 3 clips; anything over 15:00 needs 4. Every cut
  lands in a silence found with ffmpeg `silencedetect` (−40 dB, 0.12 s or
  longer). When there's room, that's the longest pause within 15 seconds of
  an even split. When the limit is tight, it can be a short gap between
  words, as near the gap's middle as the limit allows. If no silences line
  up, the app adds a clip. The cut clips are measured before anything is
  uploaded. The frames are copied, not re-encoded. Before you start, the
  dialog asks the server for the plan and shows each clip's frames. The app reads the
  template's avatar look, engine (Avatar V), background, and aspect ratio
  from its composition and uploads every clip's audio as a HeyGen asset. It
  then starts one audio-to-video render per clip (`POST /v3/videos` with
  `audio_asset_id`), all at once. If HeyGen holds a render back because too
  many are running, it starts on a later round. The app polls every 20
  seconds and streams each finished clip into the script's output folder
  under `heygen/` as `<title>_ElevenLabs_<time>_part1of3.mp4` and so on, then
  counts its frames with ffprobe at the upscaler's rate and flags any over
  the limit. The audio clips are kept in
  `voiceover/clips/`. The videos stay out of `aRoll/`, which can already hold
  chapter clips that Create DaVinci Project would put on the same timeline.
  If one clip fails, the others are still saved and the error names the
  clip. HeyGen takes up to 32 MB and 30 minutes of audio per video. The
  dialog lists each clip with its span, frames, status, and a ▶ Play button.
  The Execution Log shows the split, each clip's HeyGen video ID, a
  heartbeat every 5 minutes, and each saved file with its frame count.
- **🎞️ Explainer Video.** A toolbar button. Claude Opus 5.5 at high effort
  turns the open script (its Host: lines and production notes) and one of
  its ElevenLabs MP3s into an explainer: presentation slides plus
  illustrated vector scenes drawn from the GROK IMAGINE briefs, synced word
  by word to the narration, with the HeyGen presenter cut in where it
  helps. `explainer_video.py` holds the pipeline; each video is a project
  folder under the script's output folder in `explainer/<id>/`.
  You can start with a **test clip** (from any point, 1 to 5 minutes, ending
  on a sentence). Claude plans and writes only that stretch, and the
  preview and renders stay inside it. Once you like the look, **Build the
  rest of the video** plans and writes everything around it. Claude sees
  the refined test slides as the approved look and your revision notes,
  and the test slides are kept as they are.
  1. *Prepare.* The narration is normalized to -14 LUFS (two-pass
     loudnorm, true peak -1.5 dBTP). Every word is timed with ElevenLabs
     forced alignment against the exact text the MP3 was read from. New MP3s
     save it as a `.txt` next to them; older ones use the page's HeyGen
     text. Without an ElevenLabs key, times are estimated from the pauses.
     The ticked logo files from the folder's `images/` are cropped, and their
     dark neutral marks are recolored off-white for the dark background.
     Files without transparency, often photos, start unticked.
     *Presenter.* HeyGen clips made from the same MP3 (the `_partNofM` set in
     `heygen/`, or one long video) are listed when their length matches the
     narration. A larger copy of the same length anywhere in the script folder
     (a 4K upscale) is used in its place, after a check of its audio, or of
     its frames when it has no audio. Each clip is placed on the narration
     by matching its audio, anywhere in it: a coarse match, then a fine one,
     about 0.3 s a clip. Clips made from another voiceover, or chapter clips
     in HeyGen's own voice, are refused. A 640x360 copy of the footage plays
     in the preview, and Claude gets one still of it.
  2. *Plan.* One call returns the slides, sections, figures to confirm
     ([VERIFY BEFORE RENDER]), [insert] values, the logos used, and any
     questions. With a presenter, it also marks which slides show it, aiming
     for the share you chose (about 15, 30 or 50% of the runtime): full
     frame, an 800 px side panel, or a corner window.
  3. *Build.* The slides are written as HTML and inline SVG in parallel
     batches, 6 at a time, after the first call has cached the shared
     script, transcript and plan. Rate limits and dropped streams are
     retried. If a batch still fails, the other slides are saved as a
     version.
  4. *Compile.* Each slide starts on spoken words and each element appears
     on its cue phrase. The compiler finds those phrases in the timed
     transcript, flags cues it can't find or that fall after their slide,
     and strips scripts, event handlers, external URLs, gradients, shadows,
     filters and CSS animation.

  The dialog plays a live preview: a sandboxed page that draws any moment
  from its time, driven by the audio. It lists every slide with its words,
  checks the layout (overlapping text, text off the frame or under the HUD),
  and sends notes on ticked slides, or the one on screen, back to Claude.
  Claude sees a still of each slide, and every revision is a new version
  with Claude's one-line summary of what changed. "Whole video" rewrites
  every slide, optionally after a new plan. **Needs you** lists what blocks
  the 4K render: logos with no file (upload one, pick one from `images/`,
  or keep the text badge), figures to confirm or correct, and [insert]
  values to fill or leave out. Values are swapped in without another Claude
  call.
  The **Presenter** tab shows the clips, how well each matched and the
  stretches of narration they cover.
  - **Add clips from HeyGen** lists the videos in your HeyGen account,
    searched by title, with thumbnails. Clips already in the script folder
    are marked; the others are downloaded into `heygen/` (recorded in
    `heygen/heygen_videos.json`) and placed by their audio.
  - **Sections you place**: play or scrub, set In and Out at the playhead,
    pick full frame, left or right panel, or corner window, and add. A small
    copy of the presenter follows the playhead. Sections show as gold marks
    under the scrubber (slides with the presenter are blue). They can be
    edited or removed, fade in and out over 0.3 s, and win over a slide's
    own presenter layout. A section with no footage under it gets a warning.
  - It also has a framing slider for the side panels, "rescan for upscales"
    (after your upscaler finishes), and remove.

  Setup's "only where I put it" stops Claude from placing the presenter
  itself. Each slide in the Slides
  tab has a presenter dropdown that makes a new version without a Claude
  call. The layout check flags text, illustrations or backgrounds that
  cover the presenter, on presenter slides and halfway through each
  section. **Fix flagged** sends them to Claude, and the brief names the
  sections on each slide.
  Renders run in headless Chrome over the DevTools protocol, which captures
  each frame. On presenter slides the page leaves the presenter's area
  see-through, and each worker's ffmpeg decodes just that stretch of the
  footage, crops it to the layout and lays the frame on top. ffmpeg encodes
  chunks in 6 parallel worker processes, joins them without re-encoding, and
  adds the normalized narration, padded to the video's length:
  - a sample clip from the playhead;
  - the 1080p review cut;
  - contact sheets of every slide;
  - after you approve the version, the 4K final (3840x2160, 30 fps, H.264
    video and AAC audio, faststart), with a 720p phone copy, a 4K PNG of
    each asset slide, and the audio levels.

  On this Mac, 4K renders at about 60 frames a second (a 15-minute video
  in roughly 8 minutes). A 1:37 excerpt of a real script took 8 minutes
  and $1.39 to plan and build. Budget about $1.50 of Claude usage per
  minute of narration. A one-slide revision with its still took 40 s and
  $0.22. Calls ask for a server-side refusal fallback, and the request
  falls back to a plain call if the account does not accept it.

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
chapter headings, the title block, and the Progress Log lines without
calling a model.

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
