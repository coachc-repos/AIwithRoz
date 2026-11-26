#!/usr/bin/env bash
# Copy hackathon-scriptcraft to a clean folder and zip it.
# Drops secrets, caches, local-only files, and fails if a private pattern remains.
#
#   ./hackathon/export.sh [destination-dir]
# Default destination: /tmp/hackathon-scriptcraft
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO/hackathon-scriptcraft"
DEST="${1:-/tmp/hackathon-scriptcraft}"
ZIP="${DEST}.zip"

if [ ! -d "$SRC" ]; then
  echo "missing $SRC" >&2
  exit 1
fi

rm -rf "$DEST"
mkdir -p "$DEST"
tar -C "$SRC" \
  --exclude='.env' \
  --exclude='.env.*' \
  --exclude='.hackathon-state.json' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.venv' \
  --exclude='.venv-*' \
  --exclude='.azure' \
  --exclude='*.tar' \
  --exclude='*.tar.gz' \
  --exclude='*.mp4' \
  --exclude='*.mov' \
  --exclude='channel_playbook.md' \
  --exclude='youtube_client_secret.json' \
  --exclude='infra/deployed-models.json' \
  -cf - . | tar -C "$DEST" -xf -
# tar --exclude='.env.*' also drops .env.example. Put the template back.
cp "$SRC/.env.example" "$DEST/.env.example"
if [ ! -f "$DEST/.gitignore" ]; then
  echo "export is missing .gitignore" >&2
  exit 1
fi

python3 - "$DEST" << 'PY'
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
patterns = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-ant-[A-Za-z0-9]{10,}"),
    re.compile(r"sk_V2_[A-Za-z0-9]{8,}"),
    re.compile(r"AccountKey="),
    re.compile(r"DefaultEndpointsProtocol="),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"linedrive-ai-foundry"),
    re.compile(r"linedrivestorage"),
    re.compile(r"coach-me[0-9a-z]"),
    re.compile(r"/Users/christhi"),
    re.compile(r"20\.232\.91\.180"),
    re.compile(r"rg-linedrive"),
    re.compile(r"asst_[A-Za-z0-9]{20,}"),
]
bad = []
for path in root.rglob("*"):
    if not path.is_file():
        continue
    name = path.name
    if name in ("channel_playbook.md", "youtube_client_secret.json") or name == ".env":
        bad.append(f"forbidden file {path.relative_to(root)}")
        continue
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ttf", ".woff", ".woff2", ".onnx"}:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for pattern in patterns:
        if pattern.search(text):
            bad.append(f"{path.relative_to(root)}: {pattern.pattern}")
            break
if bad:
    print("secret scan failed:")
    print("\n".join(bad))
    sys.exit(1)
print(f"secret scan ok ({sum(1 for _ in root.rglob('*') if _.is_file())} files)")
PY

rm -f "$ZIP"
(cd "$(dirname "$DEST")" && zip -qr "$ZIP" "$(basename "$DEST")")
echo "exported $DEST"
echo "zip $ZIP"
