# Podcast Generator (ScriptCraft v3) — Container Build

Headless cloud variant of `scriptcraft-app-v3/` for **Azure Container Apps**.
It deploys to the same Container App as `scriptcraft-app-v2-container/`
(`scriptcraft-app` in `scriptcraft-rg`), which stays as it was so v2 can be
redeployed or rolled back to.

## How it differs from the v2 container

* **Code:** `sync-from-v3.sh` copies `web_gui.py`, `templates/`, `static/`,
  `console_ui/`, `linedrive_azure/`, and `agent_instructions/` from
  `scriptcraft-app-v3/`, plus `tools/` (the v2 container's subset and the Grok
  thumbnail generator). `deploy-azure.sh` runs it first. The copies are
  committed so a build is reproducible from git.
* **Agents:** the app calls the hosted Microsoft Agent Framework agents in
  Foundry (`<portal name>-MAF`) through the Container App's system-assigned
  managed identity, which holds Cognitive Services User on the Foundry account.
* **Golden reference:** `agent_instructions/golden_reference_script.md` is in
  the image (the `.dockerignore` excludes other `.md` files), so both Pro
  writers embed it.
* **Requirements:** the API SDKs are pinned to the versions v3 is tested with.
* **Disabled in the cloud** (HTTP 503, see `container_app.py`): everything the
  v2 container disables (DaVinci Resolve, local Whisper, native file pickers,
  local downloads, the thumbnail test tool), plus Render Audio from a local
  video file and 📊 Analytics. Its Google sign-in opens a browser on the
  machine running the app and keeps the token in `~/.scriptcraft`, so the
  image does not ship `youtube_analytics.py`.
* **Channel playbook:** `agent_instructions/channel_playbook.md` ships next to
  the golden reference, and the same `.dockerignore` exception covers it.

## Deploy

```bash
cd scriptcraft-app-v3-container
./deploy-azure.sh          # syncs from scriptcraft-app-v3, builds in ACR, updates the app
```

API keys come from the shell, then the repo-root `.env`, then the running
Container App (with stray spaces, CRs, and quotes trimmed).

Keys saved in the 🔑 API Keys dialog persist in the private blob
`app-settings/web_gui_settings.json` in the `linedrivestorage` account:
`container_app.py` restores it at startup, before `web_gui` reads it, and
uploads it after every save, through the managed identity (Storage Blob Data
Contributor). Saved keys override the deploy-time env vars. The dialog's key
endpoints answer remote browsers only when `APP_AUTH_TOKEN` is set, so the
cloud dialog needs that token (sign in at `/login`).

Roll back with
`az containerapp update -n scriptcraft-app -g scriptcraft-rg --image <previous image>`.
