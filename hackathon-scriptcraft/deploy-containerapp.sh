#!/usr/bin/env bash
# Host the ScriptCraft container in the sandbox (no local Docker needed).
# Run after setup-azure.sh. Builds the image in a Basic ACR with `az acr build`,
# then deploys one Azure Container App (consumption plan, scale to zero) that
# signs in with its own managed identity. Never prints .env values.
#
#   ./deploy-containerapp.sh [--tag v1] [--min-replicas 0]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
TAG="v$(date +%Y%m%d%H%M)"
MIN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tag) TAG="$2"; shift 2 ;;
    --min-replicas) MIN="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -f .hackathon-state.json ] && [ -f .env ] || { echo "Run setup-azure.sh first." >&2; exit 1; }
az extension add -n containerapp -y -o none 2>/dev/null || true
az provider register -n Microsoft.App -o none --wait

python3 - "$TAG" "$MIN" << 'PY'
import json, secrets, stat, subprocess, sys
from pathlib import Path
tag, min_replicas = sys.argv[1], sys.argv[2]
st = json.loads(Path(".hackathon-state.json").read_text())
rg, loc, prefix, sub = st["resourceGroup"], st["location"], st["prefix"], st["subscription"]
ai, storage = st["aiAccount"], st["storageAccount"]
acr = (ai[:-2] + "acr")[:50]
env_name, app = f"{prefix}-cae", f"{prefix}-app"
def az(*a, check=True, out=True):
    p = subprocess.run(["az", *a, "--subscription", sub], capture_output=True, text=True)
    if check and p.returncode != 0:
        sys.exit(p.stderr[-800:])
    return p.stdout.strip()
def exists(*a):
    return subprocess.run(["az", *a, "--subscription", sub, "-o", "none"],
                          capture_output=True).returncode == 0
if not exists("acr", "show", "-n", acr, "-g", rg):
    print(f"creating registry {acr} (Basic)")
    az("acr", "create", "-n", acr, "-g", rg, "-l", loc, "--sku", "Basic", "--admin-enabled", "false", "-o", "none")
print(f"building {acr}.azurecr.io/scriptcraft-hackathon:{tag} in Azure")
subprocess.run(["az", "acr", "build", "-r", acr, "-g", rg, "--subscription", sub,
                "-t", f"scriptcraft-hackathon:{tag}", "--platform", "linux/amd64", "."], check=True)
if not exists("containerapp", "env", "show", "-n", env_name, "-g", rg):
    print(f"creating Container Apps environment {env_name}")
    az("containerapp", "env", "create", "-n", env_name, "-g", rg, "-l", loc, "-o", "none")
env = {}
for line in Path(".env").read_text().splitlines():
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); env[k] = v
# The app uses its managed identity, not the service principal or a Speech key.
for k in ("AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID", "AZURE_SPEECH_KEY", "APP_AUTH_TOKEN"):
    env.pop(k, None)
env.update({"SCRIPTCRAFT_DISABLE_LOCAL_FEATURES": "1", "TTS_PROVIDER": env.get("TTS_PROVIDER") or "azure"})
tok_path = Path(".app-token")
if not tok_path.exists():
    tok_path.write_text(secrets.token_urlsafe(24) + "\n")
    tok_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
tok = tok_path.read_text().strip()
pairs = [f"{k}={v}" for k, v in sorted(env.items()) if v] + ["APP_AUTH_TOKEN=secretref:app-auth-token"]
image = f"{acr}.azurecr.io/scriptcraft-hackathon:{tag}"
if exists("containerapp", "show", "-n", app, "-g", rg):
    az("containerapp", "secret", "set", "-n", app, "-g", rg, "--secrets", f"app-auth-token={tok}", "-o", "none")
    az("containerapp", "update", "-n", app, "-g", rg, "--image", image,
       "--min-replicas", min_replicas, "--set-env-vars", *pairs, "-o", "none")
else:
    az("containerapp", "create", "-n", app, "-g", rg, "--environment", env_name, "--image", image,
       "--registry-server", f"{acr}.azurecr.io", "--registry-identity", "system", "--system-assigned",
       "--ingress", "external", "--target-port", "8080", "--cpu", "1.0", "--memory", "2.0Gi",
       "--min-replicas", min_replicas, "--max-replicas", "1",
       "--secrets", f"app-auth-token={tok}", "--env-vars", *pairs, "-o", "none")
principal = az("containerapp", "show", "-n", app, "-g", rg, "--query", "identity.principalId", "-o", "tsv")
ai_id = az("cognitiveservices", "account", "show", "-n", ai, "-g", rg, "--query", "id", "-o", "tsv")
st_id = az("storage", "account", "show", "-n", storage, "-g", rg, "--query", "id", "-o", "tsv")
for role, scope in (("Cognitive Services User", ai_id), ("Storage Blob Data Contributor", st_id)):
    p = subprocess.run(["az", "role", "assignment", "create", "--assignee-object-id", principal,
                        "--assignee-principal-type", "ServicePrincipal", "--role", role,
                        "--scope", scope, "-o", "none"], capture_output=True, text=True)
    print(f"role {role}: {'ok' if p.returncode == 0 or 'exists' in p.stderr else p.stderr.strip()[-300:]}")
fqdn = az("containerapp", "show", "-n", app, "-g", rg, "--query", "properties.configuration.ingress.fqdn", "-o", "tsv")
print(f"app: https://{fqdn}  (sign in with the token in .app-token; not printed)")
print("Role grants can take a few minutes to apply on first deploy.")
PY
