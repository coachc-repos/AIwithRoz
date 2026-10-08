#!/bin/bash
# Prepare ScriptCraft v2 deployment package
# Stages scriptcraft-app-v2/ sources into the existing
# scriptcraft-app/scriptcraft-enhanced-debug-package staging dir
# (which contains the Dockerfile + deploy-azure.sh used by Azure ACR build).

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

SRC_DIR="$SCRIPT_DIR"                                        # scriptcraft-app-v2
DEST_DIR="$REPO_ROOT/scriptcraft-app/scriptcraft-enhanced-debug-package"

echo "📦 Preparing ScriptCraft v2 deployment package..."
echo "   SRC : $SRC_DIR"
echo "   DEST: $DEST_DIR"

if [ ! -d "$DEST_DIR" ]; then
    echo "❌ Staging dir not found: $DEST_DIR"
    exit 1
fi

if [ ! -f "$SRC_DIR/requirements.txt" ]; then
    echo "❌ $SRC_DIR/requirements.txt missing. Run: pip freeze > requirements.txt"
    exit 1
fi

echo "📄 Copying web_gui.py..."
cp "$SRC_DIR/web_gui.py" "$DEST_DIR/web_gui.py"

echo "📄 Copying requirements.txt..."
cp "$SRC_DIR/requirements.txt" "$DEST_DIR/requirements.txt"

echo "📁 Copying templates/ ..."
rm -rf "$DEST_DIR/templates"
cp -r "$SRC_DIR/templates" "$DEST_DIR/templates"

echo "📁 Copying console_ui/ ..."
rm -rf "$DEST_DIR/console_ui"
cp -r "$SRC_DIR/console_ui" "$DEST_DIR/console_ui"

echo "📁 Copying linedrive_azure/ ..."
rm -rf "$DEST_DIR/linedrive_azure"
cp -r "$SRC_DIR/linedrive_azure" "$DEST_DIR/linedrive_azure"

echo "📁 Copying tools/ (from repo root) ..."
rm -rf "$DEST_DIR/tools"
cp -r "$REPO_ROOT/tools" "$DEST_DIR/tools"

# Optional v2 extras (only if present)
for extra in davinci_resolve_api.py resolve_inspector.py check_agent_config.py verify_section_order.py fusion_presets; do
    if [ -e "$SRC_DIR/$extra" ]; then
        echo "📄 Copying $extra ..."
        rm -rf "$DEST_DIR/$extra"
        cp -r "$SRC_DIR/$extra" "$DEST_DIR/$extra"
    fi
done

# Strip __pycache__ noise from the staged copy
find "$DEST_DIR" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

echo ""
echo "✅ v2 deployment package prepared!"
echo ""
echo "📋 Next steps:"
echo "   1. cd $DEST_DIR"
echo "   2. Verify .env has AI_PROJECT_API_KEY and GOOGLE_API_KEY"
echo "   3. ./deploy-azure.sh"
