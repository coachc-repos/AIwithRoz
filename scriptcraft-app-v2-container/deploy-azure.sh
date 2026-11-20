#!/bin/bash
# Deploy scriptcraft-app-v2-container (headless cloud variant) to the SAME
# Azure Container App that the v1 deploy-azure.sh script targets.
#
# Differences vs scriptcraft-app/scriptcraft-enhanced-debug-package/deploy-azure.sh:
#   - Builds from this folder's Dockerfile (no docker/ subfolder)
#   - Target port 8080 (not 5007) — explicitly updates ingress
#   - Reuses existing API keys from the current Container App env if no .env
#
# Resource group, registry, environment, and app name are intentionally kept
# identical so this REPLACES the running container.

set -e
cd "$(dirname "$0")"

# --- Config ---------------------------------------------------------------
RESOURCE_GROUP="scriptcraft-rg"
LOCATION="eastus"
CONTAINER_APP_NAME="scriptcraft-app"
CONTAINER_APP_ENV="linedrive-env"
CONTAINER_REGISTRY="scriptcraftregistry"
IMAGE_NAME="scriptcraft"
BUILD_VERSION="v2c.$(date +%Y%m%d%H%M)"
IMAGE_TAG="$BUILD_VERSION"
TARGET_PORT=8080

echo "🚀 ScriptCraft v2 Container Deployment"
echo "======================================"
echo "📋 Build Version: $BUILD_VERSION"
echo "🏷️  Image Tag:     $IMAGE_TAG"
echo "🎯 App:           $CONTAINER_APP_NAME (RG: $RESOURCE_GROUP)"
echo "🔌 Target port:   $TARGET_PORT"

command -v az >/dev/null || { echo "❌ Azure CLI not installed"; exit 1; }
az account show >/dev/null 2>&1 || { echo "❌ Run: az login"; exit 1; }

# --- Resource group -------------------------------------------------------
if ! az group show --name "$RESOURCE_GROUP" >/dev/null 2>&1; then
    echo "📁 Creating resource group $RESOURCE_GROUP ..."
    az group create --name "$RESOURCE_GROUP" --location "$LOCATION" -o table
fi

# --- Container registry ---------------------------------------------------
if ! az acr show --name "$CONTAINER_REGISTRY" >/dev/null 2>&1; then
    echo "🐳 Creating registry $CONTAINER_REGISTRY ..."
    az acr create --resource-group "$RESOURCE_GROUP" --name "$CONTAINER_REGISTRY" \
        --sku Basic --admin-enabled true -o table
fi
REGISTRY_SERVER=$(az acr show --name "$CONTAINER_REGISTRY" --query loginServer -o tsv)
REGISTRY_USERNAME=$(az acr credential show --name "$CONTAINER_REGISTRY" --query username -o tsv)
REGISTRY_PASSWORD=$(az acr credential show --name "$CONTAINER_REGISTRY" --query passwords[0].value -o tsv)
echo "📦 Registry: $REGISTRY_SERVER"

# --- Build image in ACR (no local docker required) -----------------------
echo "🔨 Building image in Azure Container Registry ..."
az acr build \
    --registry "$CONTAINER_REGISTRY" \
    --image "$IMAGE_NAME:$IMAGE_TAG" \
    -f Dockerfile \
    --build-arg BUILD_VERSION="$BUILD_VERSION" \
    .

# --- Container Apps environment ------------------------------------------
if ! az containerapp env show --name "$CONTAINER_APP_ENV" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    echo "🌍 Creating Container Apps environment ..."
    az containerapp env create --name "$CONTAINER_APP_ENV" \
        --resource-group "$RESOURCE_GROUP" --location "$LOCATION" -o table
fi

# --- API keys: prefer .env, otherwise pull from current container -------
if [ -f ".env" ]; then
    echo "🔑 Reading API keys from .env ..."
    AI_PROJECT_API_KEY=$(grep '^AI_PROJECT_API_KEY=' .env | cut -d= -f2-)
    GOOGLE_API_KEY=$(grep '^GOOGLE_API_KEY=' .env | cut -d= -f2-)
fi

if [ -z "$AI_PROJECT_API_KEY" ] || [ -z "$GOOGLE_API_KEY" ]; then
    if az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
        echo "🔑 Reusing API keys from existing container app env ..."
        AI_PROJECT_API_KEY=$(az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" \
            --query "properties.template.containers[0].env[?name=='AI_PROJECT_API_KEY'].value | [0]" -o tsv)
        GOOGLE_API_KEY=$(az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" \
            --query "properties.template.containers[0].env[?name=='GOOGLE_API_KEY'].value | [0]" -o tsv)
    fi
fi

if [ -z "$AI_PROJECT_API_KEY" ] || [ -z "$GOOGLE_API_KEY" ]; then
    echo "❌ Missing AI_PROJECT_API_KEY or GOOGLE_API_KEY (no .env, no existing app)"
    exit 1
fi
echo "✅ API keys resolved"

# --- ANTHROPIC_API_KEY: required for the Idea Generator (Claude Opus 4.8) --
# Prefer this dir's .env, then the repo-root .env, then the key already set on
# the running container app. Pass it through so /api/ideas/* works in the cloud
# (unlike the Grok prompts, the Idea Generator has no non-Claude fallback).
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
if [ -z "$ANTHROPIC_API_KEY" ] && [ -f ".env" ]; then
    ANTHROPIC_API_KEY=$(grep '^ANTHROPIC_API_KEY=' .env | cut -d= -f2-)
fi
if [ -z "$ANTHROPIC_API_KEY" ] && [ -f "../.env" ]; then
    ANTHROPIC_API_KEY=$(grep '^ANTHROPIC_API_KEY=' ../.env | cut -d= -f2-)
fi
if [ -z "$ANTHROPIC_API_KEY" ] && az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    ANTHROPIC_API_KEY=$(az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" \
        --query "properties.template.containers[0].env[?name=='ANTHROPIC_API_KEY'].value | [0]" -o tsv)
fi
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "⚠️  ANTHROPIC_API_KEY not found (.env or app) — Idea Generator will be disabled in the cloud."
else
    echo "✅ ANTHROPIC_API_KEY resolved (Idea Generator enabled)"
fi

# --- X (@AIwithRoz) posting keys: needed for /api/x/* to post in the cloud. --
# Resolve each from this dir's .env, then the repo-root .env, then the running
# app. Passed through below so "Post to X" / "Promote on X" work cloud-side.
_resolve_key() {
    # $1 = var name; prints the resolved value (may be empty)
    local name="$1" val=""
    val="$(printenv "$name" 2>/dev/null || true)"
    if [ -z "$val" ] && [ -f ".env" ]; then val=$(grep "^$name=" .env | cut -d= -f2-); fi
    if [ -z "$val" ] && [ -f "../.env" ]; then val=$(grep "^$name=" ../.env | cut -d= -f2-); fi
    if [ -z "$val" ] && az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
        val=$(az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" \
            --query "properties.template.containers[0].env[?name=='$name'].value | [0]" -o tsv)
    fi
    printf '%s' "$val"
}
X_API_KEY=$(_resolve_key X_API_KEY)
X_API_SECRET=$(_resolve_key X_API_SECRET)
X_ACCESS_TOKEN=$(_resolve_key X_ACCESS_TOKEN)
X_ACCESS_SECRET=$(_resolve_key X_ACCESS_SECRET)
X_BEARER_TOKEN=$(_resolve_key X_BEARER_TOKEN)
if [ -n "$X_API_KEY" ] && [ -n "$X_API_SECRET" ] && [ -n "$X_ACCESS_TOKEN" ] && [ -n "$X_ACCESS_SECRET" ]; then
    echo "✅ X (@AIwithRoz) keys resolved (Post to X enabled)"
else
    echo "⚠️  X (@AIwithRoz) keys incomplete — Post to X will be disabled in the cloud until X_* keys are set."
fi

# --- LinkedIn (@AIwithRoz) posting keys: needed for /api/linkedin/* cloud-side.
LINKEDIN_ACCESS_TOKEN=$(_resolve_key LINKEDIN_ACCESS_TOKEN)
LINKEDIN_AUTHOR_URN=$(_resolve_key LINKEDIN_AUTHOR_URN)
LINKEDIN_API_VERSION=$(_resolve_key LINKEDIN_API_VERSION)
if [ -n "$LINKEDIN_ACCESS_TOKEN" ]; then
    echo "✅ LinkedIn (@AIwithRoz) token resolved (Post to LinkedIn enabled)"
else
    echo "⚠️  LinkedIn token not set — Post to LinkedIn will be disabled in the cloud until LINKEDIN_ACCESS_TOKEN is set."
fi

# --- Optional extra keys (passed through if present) ---------------------
GROK_API_KEY="${GROK_API_KEY:-}"
HEYGEN_API_KEY="${HEYGEN_API_KEY:-}"
AI_PROJECT_ENDPOINT="${AI_PROJECT_ENDPOINT:-}"
FINISHED_VIDEOS_BLOB_ACCOUNT="${FINISHED_VIDEOS_BLOB_ACCOUNT:-linedrivestorage}"
FINISHED_VIDEOS_BLOB_CONTAINER="${FINISHED_VIDEOS_BLOB_CONTAINER:-finished-videos}"

ENV_VARS_ARGS=("PYTHONPATH=/app" "AI_PROJECT_API_KEY=$AI_PROJECT_API_KEY" "GOOGLE_API_KEY=$GOOGLE_API_KEY")
[ -n "$ANTHROPIC_API_KEY" ] && ENV_VARS_ARGS+=("ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY")
[ -n "$X_API_KEY" ] && ENV_VARS_ARGS+=("X_API_KEY=$X_API_KEY")
[ -n "$X_API_SECRET" ] && ENV_VARS_ARGS+=("X_API_SECRET=$X_API_SECRET")
[ -n "$X_ACCESS_TOKEN" ] && ENV_VARS_ARGS+=("X_ACCESS_TOKEN=$X_ACCESS_TOKEN")
[ -n "$X_ACCESS_SECRET" ] && ENV_VARS_ARGS+=("X_ACCESS_SECRET=$X_ACCESS_SECRET")
[ -n "$X_BEARER_TOKEN" ] && ENV_VARS_ARGS+=("X_BEARER_TOKEN=$X_BEARER_TOKEN")
[ -n "$LINKEDIN_ACCESS_TOKEN" ] && ENV_VARS_ARGS+=("LINKEDIN_ACCESS_TOKEN=$LINKEDIN_ACCESS_TOKEN")
[ -n "$LINKEDIN_AUTHOR_URN" ] && ENV_VARS_ARGS+=("LINKEDIN_AUTHOR_URN=$LINKEDIN_AUTHOR_URN")
[ -n "$LINKEDIN_API_VERSION" ] && ENV_VARS_ARGS+=("LINKEDIN_API_VERSION=$LINKEDIN_API_VERSION")
[ -n "$GROK_API_KEY" ] && ENV_VARS_ARGS+=("GROK_API_KEY=$GROK_API_KEY")
[ -n "$HEYGEN_API_KEY" ] && ENV_VARS_ARGS+=("HEYGEN_API_KEY=$HEYGEN_API_KEY")
[ -n "$AI_PROJECT_ENDPOINT" ] && ENV_VARS_ARGS+=("AI_PROJECT_ENDPOINT=$AI_PROJECT_ENDPOINT")
ENV_VARS_ARGS+=("FINISHED_VIDEOS_BLOB_ACCOUNT=$FINISHED_VIDEOS_BLOB_ACCOUNT")
ENV_VARS_ARGS+=("FINISHED_VIDEOS_BLOB_CONTAINER=$FINISHED_VIDEOS_BLOB_CONTAINER")

# --- Create or update the container app ----------------------------------
FULL_IMAGE="$REGISTRY_SERVER/$IMAGE_NAME:$IMAGE_TAG"
echo "🚀 Deploying $FULL_IMAGE ..."

if az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    echo "♻️  Updating existing container app ..."
    az containerapp update \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --image "$FULL_IMAGE" \
        --min-replicas 1 \
        --max-replicas 1 \
        --set-env-vars "${ENV_VARS_ARGS[@]}" \
        -o table

    # Ensure ingress targets the new port (was 5007 in v1)
    CURRENT_PORT=$(az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" \
        --query "properties.configuration.ingress.targetPort" -o tsv)
    if [ "$CURRENT_PORT" != "$TARGET_PORT" ]; then
        echo "🔌 Updating ingress port $CURRENT_PORT -> $TARGET_PORT ..."
        az containerapp ingress update \
            --name "$CONTAINER_APP_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --target-port "$TARGET_PORT" \
            --type external \
            -o table
    fi
else
    echo "🆕 Creating container app ..."
    az containerapp create \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --environment "$CONTAINER_APP_ENV" \
        --image "$FULL_IMAGE" \
        --registry-server "$REGISTRY_SERVER" \
        --registry-username "$REGISTRY_USERNAME" \
        --registry-password "$REGISTRY_PASSWORD" \
        --target-port "$TARGET_PORT" \
        --ingress external \
        --min-replicas 1 \
        --max-replicas 1 \
        --cpu 0.5 \
        --memory 1Gi \
        --env-vars "${ENV_VARS_ARGS[@]}" \
        -o table
fi

# --- Single revision mode + clean up old revisions -----------------------
echo "⚙️  Setting single revision mode ..."
az containerapp revision set-mode --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" --mode Single >/dev/null 2>&1 || true

LATEST_REVISION=$(az containerapp revision list \
    --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" \
    --query "max_by([], &properties.createdTime).name" -o tsv)
echo "📌 Latest revision: $LATEST_REVISION"

OLD_REVISIONS=$(az containerapp revision list \
    --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" \
    --query "[?properties.active && name != '$LATEST_REVISION'].name" -o tsv)
if [ -n "$OLD_REVISIONS" ]; then
    echo "🧹 Deactivating old revisions ..."
    for r in $OLD_REVISIONS; do
        echo "   - $r"
        az containerapp revision deactivate --name "$CONTAINER_APP_NAME" \
            --resource-group "$RESOURCE_GROUP" --revision "$r" >/dev/null 2>&1 || true
    done
fi

# --- Managed identity -----------------------------------------------------
echo "🔐 Ensuring system-assigned managed identity ..."
az containerapp identity assign --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" --system-assigned >/dev/null
CURRENT_REVISION=$(az containerapp revision list --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" --query "[0].name" -o tsv)
az containerapp revision restart --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" --revision "$CURRENT_REVISION" >/dev/null

# --- Done -----------------------------------------------------------------
APP_URL=$(az containerapp show --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv)

echo ""
echo "✅ Deployment complete!"
echo "🌍 https://$APP_URL"
echo "💓 https://$APP_URL/healthz"
