#!/bin/bash

echo "========================================"
echo "🚀 Starting ScriptCraft v3 Web GUI (MAF hosted agents)"
echo "========================================"
echo ""

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

echo "📁 Script directory: $SCRIPT_DIR"
echo "📁 Repository root: $REPO_ROOT"
echo ""

VENV_PYTHON="python3"
if [ -d "$REPO_ROOT/venv314_v2" ]; then
    echo "🐍 Activating v2 virtual environment (venv314_v2)..."
    source "$REPO_ROOT/venv314_v2/bin/activate"
    VENV_PYTHON="$REPO_ROOT/venv314_v2/bin/python3"
    echo "✅ v2 virtual environment activated"
elif [ -d "$REPO_ROOT/venv314" ]; then
    echo "🐍 Activating fallback virtual environment (venv314)..."
    source "$REPO_ROOT/venv314/bin/activate"
    VENV_PYTHON="$REPO_ROOT/venv314/bin/python3"
    echo "✅ Fallback virtual environment activated"
elif [ -d "$REPO_ROOT/.venv" ]; then
    echo "🐍 Activating fallback virtual environment (.venv)..."
    source "$REPO_ROOT/.venv/bin/activate"
    VENV_PYTHON="$REPO_ROOT/.venv/bin/python3"
    echo "✅ Fallback virtual environment activated"
else
    echo "❌ No supported virtual environment found"
    echo "   Checked: $REPO_ROOT/venv314_v2, $REPO_ROOT/venv314, $REPO_ROOT/.venv"
    exit 1
fi
echo ""

if [ -n "$GOOGLE_API_KEY" ]; then
    echo "🔑 GOOGLE_API_KEY detected in environment"
else
    echo "⚠️ GOOGLE_API_KEY is not set; thumbnail generation will fail"
fi
echo ""

export FOUNDRY_API_MODE="${FOUNDRY_API_MODE:-v2}"
# v3: migrated agents run on their Foundry hosted MAF agents ("<portal name>-MAF").
# SCRIPTCRAFT_AGENT_BACKEND=portal sends them back to the portal prompt agents.
export SCRIPTCRAFT_AGENT_BACKEND="${SCRIPTCRAFT_AGENT_BACKEND:-maf}"
echo "🤖 Agent backend: $SCRIPTCRAFT_AGENT_BACKEND  (maf = hosted MAF agents, portal = v2 prompt agents)"
echo ""

# Point the Video Gallery at Azure Blob Storage so local + cloud serve the same
# (already-transcoded) MP4s via short-lived user-delegation SAS URLs.
export FINISHED_VIDEOS_BLOB_ACCOUNT="${FINISHED_VIDEOS_BLOB_ACCOUNT:-linedrivestorage}"
export FINISHED_VIDEOS_BLOB_CONTAINER="${FINISHED_VIDEOS_BLOB_CONTAINER:-finished-videos}"
echo "🎬 Video Gallery source: blob://$FINISHED_VIDEOS_BLOB_ACCOUNT/$FINISHED_VIDEOS_BLOB_CONTAINER"
echo ""

cd "$SCRIPT_DIR"
echo "📂 Working directory: $(pwd)"
echo ""

if [ ! -f "web_gui.py" ]; then
    echo "❌ Error: web_gui.py not found!"
    exit 1
fi

echo "🐍 Python version:"
$VENV_PYTHON --version
echo ""

echo "📦 Checking key packages..."
$VENV_PYTHON -c "import flask; print('✅ Flask installed')" 2>/dev/null || echo "❌ Flask not installed"
$VENV_PYTHON -c "import azure.ai.projects, azure.ai.agents; print('✅ azure-ai-projects + azure-ai-agents installed')" 2>/dev/null || echo "❌ azure SDKs missing"
$VENV_PYTHON -c "from PIL import Image; print('✅ Pillow installed')" 2>/dev/null || echo "❌ Pillow not installed"
echo ""

TEMPLATE_PATH="$REPO_ROOT/tools/media/Thumbnail_Template_Canva.png"
if [ -f "$TEMPLATE_PATH" ]; then
    echo "✅ Thumbnail template found: $TEMPLATE_PATH"
else
    echo "❌ Thumbnail template NOT found: $TEMPLATE_PATH"
fi
echo ""

# 8082 so the v2 GUI (8080/8081) can run alongside v3.
export PORT="${PORT:-8082}"

echo "========================================"
echo "🌐 Starting Flask server on port $PORT"
echo "========================================"
echo "📍 URL: http://localhost:$PORT"
echo "⏹️  Press Ctrl+C to stop"
echo ""

$VENV_PYTHON web_gui.py
