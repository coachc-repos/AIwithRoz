#!/usr/bin/env bash
# Build the image and confirm it serves /healthz with no Azure credentials,
# then synthesize a short Piper WAV inside the container.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
IMAGE="${IMAGE:-scriptcraft-hackathon:smoke}"
PORT="${PORT:-18080}"
NAME="scriptcraft-smoke-$$"

docker build -t "$IMAGE" "$ROOT"
cid="$(docker run -d --name "$NAME" -p "${PORT}:8080" \
  -e TTS_PROVIDER=piper \
  -e SCRIPTCRAFT_SETTINGS_BLOB_CONTAINER= \
  -e FINISHED_VIDEOS_BLOB_ACCOUNT= \
  -e SCRIPTCRAFT_DISABLE_LOCAL_FEATURES=1 \
  "$IMAGE")"
cleanup() { docker rm -f "$cid" >/dev/null 2>&1 || true; }
trap cleanup EXIT

ok=0
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:${PORT}/healthz" > /tmp/scriptcraft-health.json; then
    ok=1
    break
  fi
  sleep 2
done
if [ "$ok" -ne 1 ]; then
  echo "health check failed" >&2
  docker logs "$cid" >&2 || true
  exit 1
fi
python3 - << 'PY'
import json
data = json.load(open("/tmp/scriptcraft-health.json"))
assert data.get("status") == "ok", data
print("health", data.get("status"), "tts", (data.get("tts") or {}).get("provider"))
PY
ui_code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/")"
echo "ui_http ${ui_code}"
test "$ui_code" = "200"

docker exec "$cid" python narration.py --provider piper \
  --text "This is a short narration test for the hackathon sandbox. It should be paced for clear speech and normalized for broadcast loudness." \
  --out /tmp/piper-check.wav
docker exec -i "$cid" python - << 'PY'
import json, wave
from pathlib import Path
with wave.open("/tmp/piper-check.wav") as handle:
    frames = handle.getnframes()
    rate = handle.getframerate()
assert frames > 0 and rate > 0
seconds = frames / float(rate)
words = json.loads(Path("/tmp/piper-check.words.json").read_text(encoding="utf-8"))
assert words, "no word timings"
assert seconds > 0.4, seconds
print(f"piper_wav_seconds={seconds:.2f} timed_words={len(words)} rate={rate}")
PY

docker image inspect "$IMAGE" --format 'image_bytes={{.Size}}'
echo "smoke ok"
