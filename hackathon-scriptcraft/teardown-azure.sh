#!/usr/bin/env bash
# Delete the sandbox resource group and the service principal recorded by setup.
# Does not print .env. Removes .env afterwards so the secret is not left behind.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
DELETE_SP=1

while [ $# -gt 0 ]; do
  case "$1" in
    --keep-sp) DELETE_SP=0; shift ;;
    -h|--help)
      echo "usage: ./teardown-azure.sh [--keep-sp]"
      exit 0
      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ ! -f .hackathon-state.json ]; then
  echo "No .hackathon-state.json. Pass the resource group to az group delete yourself." >&2
  exit 1
fi

python3 - "$DELETE_SP" << 'PY'
import json, subprocess, sys
from pathlib import Path
delete_sp = sys.argv[1] == "1"
state = json.loads(Path(".hackathon-state.json").read_text(encoding="utf-8"))
group = state["resourceGroup"]
subscription = state["subscription"]
print(f"deleting resource group {group}")
subprocess.run(
    ["az", "group", "delete", "--name", group, "--subscription", subscription,
     "--yes", "--no-wait"],
    check=True,
)
if delete_sp and state.get("clientId"):
    print(f"deleting service principal {state['clientId']}")
    subprocess.run(
        ["az", "ad", "sp", "delete", "--id", state["clientId"]],
        check=False,
    )
for name in (".env", ".hackathon-state.json"):
    path = Path(name)
    if path.exists():
        path.unlink()
        print(f"removed {name}")
print("resource group delete is running; az group delete was started with --no-wait")
PY
