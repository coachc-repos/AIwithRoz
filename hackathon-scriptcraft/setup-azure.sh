#!/usr/bin/env bash
# Provision a ScriptCraft sandbox in the Azure subscription you have selected.
# Idempotent. Writes .env and never prints secret values.
#
#   az login --tenant <sandbox-tenant>
#   az account set --subscription <sandbox-subscription>
#   ./setup-azure.sh --location eastus2 --prefix scraft
#
# This does not deploy the web container to Azure. Run docker compose locally.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

LOCATION=""
PREFIX=""
SUBSCRIPTION=""
SKIP_AGENTS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --location) LOCATION="$2"; shift 2 ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --subscription) SUBSCRIPTION="$2"; shift 2 ;;
    --skip-agents) SKIP_AGENTS=1; shift ;;
    -h|--help)
      echo "usage: ./setup-azure.sh --location <region> --prefix <name> [--subscription <id>] [--skip-agents]"
      exit 0
      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if ! command -v az >/dev/null 2>&1; then
  echo "Azure CLI (az) is required." >&2
  exit 1
fi
if [ -z "$LOCATION" ] || [ -z "$PREFIX" ]; then
  echo "Pass --location and --prefix." >&2
  exit 2
fi
if ! [[ "$PREFIX" =~ ^[a-z0-9]{3,12}$ ]]; then
  echo "--prefix must be 3-12 lowercase letters or numbers." >&2
  exit 2
fi

if [ -n "$SUBSCRIPTION" ]; then
  az account set --subscription "$SUBSCRIPTION" >/dev/null
fi
SUBSCRIPTION="$(az account show --query id -o tsv)"
TENANT="$(az account show --query tenantId -o tsv)"
RG="rg-${PREFIX}-scriptcraft"
echo "subscription ${SUBSCRIPTION}"
echo "resource group ${RG} in ${LOCATION}"

az group create --name "$RG" --location "$LOCATION" --subscription "$SUBSCRIPTION" -o none

if command -v azd >/dev/null 2>&1; then
  # azure.yaml has no application service, so this provisions infrastructure only.
  azd env new "$PREFIX" --location "$LOCATION" --subscription "$SUBSCRIPTION" >/dev/null 2>&1 || true
  azd env set AZURE_LOCATION "$LOCATION" >/dev/null || true
  azd env set AZURE_SUBSCRIPTION_ID "$SUBSCRIPTION" >/dev/null || true
  azd provision --no-prompt \
    --parameters "location=${LOCATION}" "namePrefix=${PREFIX}" \
    || echo "azd provision did not complete; continuing with az deployment group create"
fi

DEPLOY_JSON="$(mktemp)"
trap 'rm -f "$DEPLOY_JSON"' EXIT
az deployment group create \
  --name "${PREFIX}-scriptcraft" \
  --resource-group "$RG" \
  --subscription "$SUBSCRIPTION" \
  --template-file infra/main.bicep \
  --parameters "location=${LOCATION}" "namePrefix=${PREFIX}" \
  --query properties.outputs \
  -o json > "$DEPLOY_JSON"

python3 - "$DEPLOY_JSON" "$ROOT" "$SUBSCRIPTION" "$TENANT" "$RG" "$LOCATION" "$PREFIX" << 'PY'
import json, os, stat, subprocess, sys
from pathlib import Path

outputs_path, root, subscription, tenant, group, location, prefix = sys.argv[1:]
root = Path(root)
outputs = json.loads(Path(outputs_path).read_text())

def val(name):
    item = outputs.get(name) or {}
    return item.get("value") if isinstance(item, dict) else item

ai = val("aiAccountName")
ai_id = val("aiAccountId")
subdomain = val("customSubDomain")
project = val("projectName")
project_principal = val("projectPrincipalId")
storage = val("storageAccountName")
storage_id = val("storageAccountId")
settings = val("settingsContainer")
videos = val("videosContainer")
endpoint = f"https://{subdomain}.services.ai.azure.com/api/projects/{project}"

# Model deployments. Failure here is reported; names stay empty if none were created.
model_env = {}
try:
    subprocess.run(
        [sys.executable, str(root / "infra" / "deploy_models.py"),
         ai, group, str(root / "infra" / "models.json")],
        check=True,
    )
    model_env = json.loads((root / "infra" / "deployed-models.json").read_text())
except subprocess.CalledProcessError:
    print("Model deployment did not finish. Re-run setup-azure.sh after quota is available.")

speech_key = ""
keys = subprocess.run(
    ["az", "cognitiveservices", "account", "keys", "list",
     "-n", ai, "-g", group, "-o", "json"],
    capture_output=True, text=True,
)
if keys.returncode == 0:
    speech_key = (json.loads(keys.stdout or "{}").get("key1") or "")
else:
    print("Could not list the Speech key. The container will use Entra ID instead.")

# Service principal. Reuse an existing app. Rotate a secret only when .env
# does not already hold one for this client id.
sp_name = f"{prefix}-scriptcraft"
listed = subprocess.run(
    ["az", "ad", "app", "list", "--display-name", sp_name, "--query", "[0].appId", "-o", "tsv"],
    capture_output=True, text=True, check=True,
)
client_id = (listed.stdout or "").strip()
env_path = root / ".env"
existing = {}
if env_path.is_file():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        existing[k] = v
secret = ""
if client_id and existing.get("AZURE_CLIENT_ID") == client_id and existing.get("AZURE_CLIENT_SECRET"):
    secret = existing["AZURE_CLIENT_SECRET"]
    print(f"service principal {sp_name} already has a local secret; leaving it in place")
elif client_id:
    reset = subprocess.run(
        ["az", "ad", "app", "credential", "reset", "--id", client_id, "-o", "json"],
        capture_output=True, text=True, check=True,
    )
    secret = json.loads(reset.stdout).get("password") or ""
    print(f"service principal {sp_name} secret refreshed into .env")
else:
    created = subprocess.run(
        ["az", "ad", "sp", "create-for-rbac", "--name", sp_name, "--skip-assignment", "-o", "json"],
        capture_output=True, text=True, check=True,
    )
    body = json.loads(created.stdout)
    client_id = body.get("appId") or ""
    secret = body.get("password") or ""
    print(f"service principal {sp_name} created")

def role(assignee, role_name, scope):
    if not assignee or not scope:
        return
    proc = subprocess.run(
        ["az", "role", "assignment", "create",
         "--assignee", assignee, "--role", role_name, "--scope", scope, "-o", "none"],
        capture_output=True, text=True,
    )
    if proc.returncode == 0:
        print(f"role {role_name} assigned")
        return
    text = (proc.stderr or "") + (proc.stdout or "")
    if "RoleAssignmentExists" in text or "already exists" in text:
        print(f"role {role_name} already assigned")
        return
    print(text.strip() or f"could not assign {role_name}", file=sys.stderr)
    raise SystemExit(1)

# Container identity: call Foundry and read/write the private blobs. Nothing broader.
role(client_id, "Cognitive Services User", ai_id)
role(client_id, "Storage Blob Data Contributor", storage_id)
# Project identity: hosted agents call the model deployments in this account.
role(project_principal, "Cognitive Services OpenAI User", ai_id)
# The person running setup registers the hosted agents (data-plane write on
# the project). Subscription Owner alone does not include data actions.
me = subprocess.run(["az", "ad", "signed-in-user", "show", "--query", "id", "-o", "tsv"],
                    capture_output=True, text=True)
if me.returncode == 0 and me.stdout.strip():
    role(me.stdout.strip(), "Foundry Project Manager", f"{ai_id}/projects/{project}")
else:
    print("Could not read the signed-in user; grant yourself Foundry Project Manager on the project.")

values = {
    "AZURE_CLIENT_ID": client_id,
    "AZURE_TENANT_ID": tenant,
    "AZURE_CLIENT_SECRET": secret,
    "FOUNDRY_PROJECT_ENDPOINT": endpoint,
    "AZURE_AI_PROJECT_ENDPOINT": endpoint,
    "AI_PROJECT_ENDPOINT": endpoint,
    "FINISHED_VIDEOS_BLOB_ACCOUNT": storage,
    "FINISHED_VIDEOS_BLOB_CONTAINER": videos,
    "SCRIPTCRAFT_SETTINGS_BLOB_CONTAINER": settings,
    "AZURE_SPEECH_REGION": location,
    # Entra (managed identity / service principal) auth for Speech.
    "AZURE_SPEECH_RESOURCE_ID": ai_id,
    "AZURE_SPEECH_ENDPOINT": f"wss://{location}.tts.speech.microsoft.com/cognitiveservices/websocket/v1",
    "TTS_PROVIDER": "azure",
    "TTS_VOICE": "en-US-AvaMultilingualNeural",
    "TTS_WPM": "175",
    "TTS_BASELINE_WPM": "150",
    "SCRIPTCRAFT_DISABLE_LOCAL_FEATURES": "1",
    # The Pro writer's Anthropic path needs a custom role and the account name.
    # The Responses path works with the roles this script grants.
    "MAF_FOUNDRY_RESOURCE": ai,
    "MAF_PRO_PATH": existing.get("MAF_PRO_PATH") or "responses",
}
if speech_key:
    values["AZURE_SPEECH_KEY"] = speech_key
values.update({k: v for k, v in model_env.items() if v})

lines = [
    "# Generated by setup-azure.sh. Do not commit.",
    f"# subscription {subscription}",
    f"# resource group {group}",
]
for key in sorted(values):
    lines.append(f"{key}={values[key]}")
env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
print(f"wrote {env_path.name} (mode 600, values not shown)")

state = {
    "subscription": subscription,
    "tenantId": tenant,
    "resourceGroup": group,
    "location": location,
    "prefix": prefix,
    "aiAccount": ai,
    "project": project,
    "storageAccount": storage,
    "clientId": client_id,
    "foundryEndpoint": endpoint,
}
state_path = root / ".hackathon-state.json"
state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
os.chmod(state_path, stat.S_IRUSR | stat.S_IWUSR)
print("wrote .hackathon-state.json (no secrets)")
PY

if [ "$SKIP_AGENTS" -eq 0 ]; then
  echo "Registering MAF hosted agents (this uses your az login, not the app secret)..."
  if [ ! -d .venv-maf ]; then
    python3 -m venv .venv-maf
    .venv-maf/bin/pip install -r maf/requirements.txt
  fi
  # Load .env in Python so secret values are not expanded by the shell.
  python3 - << 'PY'
import os, subprocess
from pathlib import Path
env = os.environ.copy()
# Optional third-party keys come from .env only, never from the shell that
# runs setup, so a key on the operator's machine is not copied into the
# sandbox's hosted agents by accident.
for name in ("XAI_API_KEY", "GROK_API_KEY", "ANTHROPIC_API_KEY"):
    env.pop(name, None)
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    env[key] = value
subprocess.check_call([".venv-maf/bin/python", "maf/hosted/deploy.py"], env=env)
PY
fi

echo "Done. Next: docker compose up --build"
echo "UI: http://localhost:8080"
