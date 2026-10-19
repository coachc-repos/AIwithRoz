#!/bin/bash
# Copy the v3 app (scriptcraft-app-v3/) into this container folder.
# deploy-azure.sh runs this first, so the image always holds the current v3 code.
# The copies are committed, like the v2 container's, so a build is reproducible
# from git. Desktop-only files (DaVinci Resolve, Whisper, native pickers) are
# not copied; container_app.py stubs or disables what depends on them.
set -euo pipefail
cd "$(dirname "$0")"
SRC=../scriptcraft-app-v3
V2C=../scriptcraft-app-v2-container

rm -rf templates static console_ui linedrive_azure agent_instructions tools
cp "$SRC/web_gui.py" .
cp -R "$SRC/templates" "$SRC/static" "$SRC/console_ui" "$SRC/linedrive_azure" "$SRC/agent_instructions" .

# tools/: the subset the v2 container ships (identical to the repo's tools/),
# plus the Grok Imagine thumbnail generator. Its reference thumbnails stay
# local-only; without them it falls back to Gemini.
cp -R "$V2C/tools" .
cp ../tools/media/emotional_thumbnail_generator.py tools/media/
cp ../tools/media/grok_thumbnail_generator.py tools/media/

find . -name __pycache__ -type d -prune -exec rm -rf {} +
echo "✅ Synced from $SRC: web_gui.py, templates/, static/, console_ui/, linedrive_azure/, agent_instructions/, tools/"
