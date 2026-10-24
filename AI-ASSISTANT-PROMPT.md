# 🤖 AI Assistant Context Prompt for LineDrive
**Copy and paste this prompt at the start of a new conversation**

---

## 📚 CRITICAL: Read the Documentation FIRST

Before making ANY suggestions, code changes, or answering questions about LineDrive:

**READ**: [README.md](README.md) and (if present) `DOCUMENTATION.md` in the project root.

---

## 🎯 LineDrive System Overview (current as of May 2026)

LineDrive is a **multi-module platform** with several distinct systems:

### 🎬 **Primary Module: ScriptCraft v2 (YouTube Script + Video Production)**
- **Active app**: [scriptcraft-app-v2/](scriptcraft-app-v2/) — this is the working version. The legacy [scriptcraft-app/](scriptcraft-app/) still exists but is largely superseded.
- **4-agent AI workflow**: Topic enhancement → Script writing → Review → Assembly & Polish
- **Web GUI**: Flask app on port 8080 ([scriptcraft-app-v2/web_gui.py](scriptcraft-app-v2/web_gui.py)) with SSE streaming
- **DaVinci Resolve integration**: Programmatic timeline build, B-roll insertion on V3, marker/EDL export, Fusion comp automation ([scriptcraft-app-v2/davinci_resolve_api.py](scriptcraft-app-v2/davinci_resolve_api.py))
- **HeyGen v2 integration**: Avatar video generation via cURL templates
- **Emotional thumbnails**: 6 AI-powered variations (Gemini Flash Image)
- **B-roll image generation**: Per-chapter image prompts → Shutterstock tab links + AI-generated images

### ⚾ **Secondary Module: Baseball Tournament Management**
- Batch scrapers for Perfect Game, Little League, USA Baseball
- Azure Data Lake storage integration
- Scraper Web GUI at [scraper_web_gui.py](scraper_web_gui.py)

### 📱 **Tertiary Module: Social Media Integration**
- X/Twitter posting under [social_media/](social_media/)

---

## 🚨 CRITICAL RULES - NEVER BREAK THESE

### 1. **Module Isolation**
```
Console UI         = baseline (don't break)
scriptcraft-app    = legacy web GUI (don't break, but prefer v2 for new work)
scriptcraft-app-v2 = ACTIVE web GUI + Resolve/Fusion/HeyGen
```
Each module must remain functional when others are modified.

### 2. **Git Operations - ALWAYS ASK FIRST**
- ❌ Never run `git commit` or `git push` without explicit user approval.
- ✅ Show `git status` / `git diff` and wait for "yes".

### 3. **Working Code - DO NOT MODIFY Without Permission**
Critical files:
- [scriptcraft-app-v2/web_gui.py](scriptcraft-app-v2/web_gui.py) — main Flask + SSE
- [scriptcraft-app-v2/davinci_resolve_api.py](scriptcraft-app-v2/davinci_resolve_api.py) — Resolve/Fusion automation
- [scriptcraft-app-v2/console_ui/workflows.py](scriptcraft-app-v2/console_ui/workflows.py) — 4-agent workflow
- [scriptcraft-app-v2/linedrive_azure/agents/](scriptcraft-app-v2/linedrive_azure/agents/) — agent clients
- [tools/media/emotional_thumbnail_generator.py](tools/media/emotional_thumbnail_generator.py)
- [tools/media/broll_image_generator.py](tools/media/broll_image_generator.py)

### 4. **SSE Streaming Pattern - DO NOT CHANGE**
```python
# ✅ Process queue BEFORE checking done
while True:
    if not streamer.message_queue.empty():
        message = streamer.message_queue.get()
        yield f"data: {json.dumps(message)}\n\n"
    if streamer.done and streamer.message_queue.empty():
        break
```

### 5. **Progress Bar Pattern**
- `send_update()` returns early if `progress is None` (never default to 50%).
- Filter chapter "Writing/Reviewing X/Y" START messages; only emit progress on completion.

### 6. **Azure Agent Thread Cleanup**
Handle "thread already has an active run" by listing + cancelling existing runs, then `time.sleep(5)` before retry.

### 7. **DaVinci Resolve / Fusion Automation Rules**
When working in [davinci_resolve_api.py](scriptcraft-app-v2/davinci_resolve_api.py):
- External Python uses `DaVinciResolveScript.scriptapp("Resolve" / "Fusion")`.
- **Per-clip Fusion comps use COMP-LOCAL frames**, not timeline-absolute frames. Read `comp.GetAttrs()['COMPN_GlobalStart' / 'COMPN_GlobalEnd']` for the keyframe range.
- **Modifiers must be added explicitly** — `tool.SetInput(name, value, frame)` does NOT auto-create a BezierSpline on this build. Use:
  ```python
  spline = comp.AddTool("BezierSpline", -32768, -32768)
  blur.ConnectInput("XBlurSize", spline)
  spline.SetKeyFrames({f_start: {1: 0.0}, f_end: {1: max_blur}})
  ```
- **Editor preview cache** must be seeded by evaluating each comp inside the Fusion page: `comp.SetCurrentTime(f)` + `comp.Render({"Tool": tool, "Quality": 1})`, then bounce `OpenPage("fusion")` → scrub timeline → `OpenPage("edit")`.
- B-roll lives on **V3**. Adjustment-clip insertion is currently disabled.
- Script title parsing recognizes `Title:` lines.

### 8. **Console UI Entry Point**
```bash
# ✅ from project root
python console_launcher_module.py
```

### 9. **Bug fixes are test-first**
Follow [AGENTS.md](AGENTS.md). For every bug fix, write a test that reproduces the bug and fails, then make the fix, then confirm that test passes and `python -m pytest` stays green. CI runs that same suite on every push and pull request. Do not call live Azure, HeyGen, Gemini, Grok, Pexels, X, or DaVinci Resolve from tests; those need keys or a local app and are not part of CI.

---

## 🔧 Development Workflow

### Before changes
1. Read README.md.
2. Identify the module (scriptcraft-app-v2 / scriptcraft-app / console / scraper / social).
3. Test the baseline first.
4. ASK before modifying critical working code.

### Running the active web GUI
```bash
cd scriptcraft-app-v2
source ../venv314/bin/activate
python web_gui.py
# http://localhost:8080
```

### After changes
1. Test the modified module.
2. Verify dependent modules still work.
3. Show `git status` / `git diff`.
4. ASK before commit / push.

---

## ✅ DO / ❌ DON'T

### DO
- ✅ Read README.md before suggesting.
- ✅ Prefer `scriptcraft-app-v2` for new work.
- ✅ Ask before modifying working code.
- ✅ Show diff before committing.
- ✅ Wait for explicit "yes" on git operations.
- ✅ For Resolve/Fusion: respect comp-local frame domain and explicit BezierSpline modifiers.

### DON'T
- ❌ Auto-commit or auto-push.
- ❌ Break the SSE streaming pattern.
- ❌ Break console UI baseline.
- ❌ Touch `scriptcraft-app` (legacy) when work is targeted at v2.
- ❌ Assume `tool.SetInput(name, value, frame)` creates keyframes on Fusion.

---

## 📁 Key Files Reference

### Entry Points
- [console_launcher_module.py](console_launcher_module.py) — console UI
- [scriptcraft-app-v2/web_gui.py](scriptcraft-app-v2/web_gui.py) — **active** web GUI (port 8080)
- [scraper_web_gui.py](scraper_web_gui.py) — baseball scraper web UI
- [batch_scrapers/](batch_scrapers/) — tournament scrapers

### ScriptCraft v2 Core
- [scriptcraft-app-v2/davinci_resolve_api.py](scriptcraft-app-v2/davinci_resolve_api.py) — Resolve / Fusion automation, EDL markers, B-roll on V3, blur smoke test
- [scriptcraft-app-v2/console_ui/workflows.py](scriptcraft-app-v2/console_ui/workflows.py) — 4-agent script workflow
- [scriptcraft-app-v2/console_ui/text_processing.py](scriptcraft-app-v2/console_ui/text_processing.py)
- [scriptcraft-app-v2/console_ui/word_processing.py](scriptcraft-app-v2/console_ui/word_processing.py)

### AI Agents (under [scriptcraft-app-v2/linedrive_azure/agents/](scriptcraft-app-v2/linedrive_azure/agents/))
- `script_writer_agent_client.py`
- `script_review_agent_client.py`
- `script_polisher_agent_client.py`
- `script_repeat_and_flow_agent_client.py`
- `script_broll_agent_client.py`
- `hook_and_summary_agent_client.py`
- `quote_and_statistics_agent_client.py`
- `youtube_upload_details_agent_client.py`
- `ai_tips_agent_client.py`
- `enhanced_autogen_system.py`
- `base_agent_client.py`

### Media Generation
- [tools/media/emotional_thumbnail_generator.py](tools/media/emotional_thumbnail_generator.py) — 6 emotional variations
- [tools/media/broll_image_generator.py](tools/media/broll_image_generator.py) — per-chapter B-roll images

### HeyGen
- [generate_heygen_curls.py](generate_heygen_curls.py)
- [tools/heygen/](tools/heygen/)

### Fusion Presets
- [scriptcraft-app-v2/fusion_presets/](scriptcraft-app-v2/fusion_presets/)

---

## 🆕 What's New (last 3 weeks, ending May 2026)

- **`scriptcraft-app-v2`** introduced as the active web GUI; `scriptcraft-app` is now legacy.
- **DaVinci Resolve API integration**: build timelines, insert B-roll on V3, generate EDL marker exports.
- **Fusion automation**: programmatic Blur (with BezierSpline keyframes) on every V3 broll clip; editor cache refresh via Fusion-page bounce + per-clip `Render` + scrub.
- **HeyGen v2 integration** with template management + curl test features.
- **Grok selection workflow** with API key persistence.
- **Shutterstock tab** opens links in new browser tabs.
- **Thumbnail cancel controls** + aligned stop button UI.
- **`Title:` line recognized** as the script title; **adjustment-clip insertion disabled**.
- **Scraper Web GUI** added.

---

## 🐛 Common Issues & Solutions

### Resolve: Blur visible only after manual Fusion-page scrub
Add per-clip evaluation (`comp.SetCurrentTime` + `comp.Render`) and a Fusion→Edit page bounce that scrubs each V3 clip's mid-timecode. Increase dwell if still flaky.

### Resolve: Keyframes "set" but value stays flat
The `frame` argument to `Tool.SetInput` doesn't create modifiers on this build. Add a `BezierSpline`, `ConnectInput("XBlurSize", spline)`, then `spline.SetKeyFrames({...})`.

### Fusion blur applied only to first 2 clips
Cause: using timeline-absolute frames as keyframe times. Fix: use COMP-LOCAL range from `comp.GetAttrs()`.

### Web GUI hangs at completion
SSE completion bug — use the `while True:` queue-then-done pattern.

### Progress bar jumps to 50% / jumps backward
`send_update()` must return early when `progress is None`; filter chapter START messages.

### "Thread already has an active run"
Cancel existing runs and wait 5s before retry.

### Import error: `google.generativeai`
```bash
venv314/bin/pip install google-generativeai
```

---

## 💡 Your Role as AI Assistant

1. Understand the full system before suggesting.
2. Respect working code — especially `scriptcraft-app-v2` and `davinci_resolve_api.py`.
3. Test the modified module.
4. **Ask permission** for code edits to critical files and ALL git operations.
5. Maintain module isolation.
6. Provide context — explain WHY a change is needed.
7. Offer rollback plans for risky changes.

### Interaction protocol
- Before modifying critical code: state file + reason + impact, ask to proceed.
- Before commit: show diff, ask.
- Before push: confirm.
- After test files: ask if they should be cleaned up.

---

## 🎓 Quick Reference Card

| Situation | Action |
|---|---|
| Before any change | Read README.md |
| Before modifying critical code | Ask user |
| Before `git commit` | Show diff + ASK |
| Before `git push` | ASK |
| Web GUI work | Use `scriptcraft-app-v2/` |
| Resolve/Fusion work | Comp-local frames + explicit BezierSpline + cache refresh |
| Debugging | Isolated test, not full 3–4 min workflow |
