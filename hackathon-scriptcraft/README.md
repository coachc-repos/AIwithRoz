# ScriptCraft hackathon package

Copy this folder into your repo root, then follow setup.

This is the ScriptCraft v3 container app (the same web UI as
`scriptcraft-app-v3-container`) packed so it does not import or build anything
outside this folder. Script generation still uses Microsoft Agent Framework
hosted agents on Azure AI Foundry. DaVinci Resolve, local file pickers, and
channel analytics stay off unless you set `SCRIPTCRAFT_DISABLE_LOCAL_FEATURES=0`
(they need a desktop, not a sandbox).

The UI is on port **8080**.

## What works with no paid keys

| Works offline | Needs credentials |
|---|---|
| Web UI and `/healthz` | Script writing (Foundry hosted agents) |
| Piper narration, paced near 175 wpm, normalized to -14 LUFS, word-timed with faster-whisper | Azure Speech narration (default when the sandbox Speech resource is configured) |
| Explainer page shell. Rendering a finished explainer also needs Chromium, which is in the image, plus a narration file | HeyGen, ElevenLabs, Grok/xAI, Claude, Google thumbnails, YouTube upload, X/LinkedIn |
| | Saved API keys across restarts (storage account + Entra) |

Missing optional keys disable that button's request with an error JSON body. The process keeps running.

## Prerequisites

- Docker with Compose v2
- For Azure setup: Azure CLI (`az`), and optionally `azd`
- Rights in the **sandbox** subscription to create a resource group, an Azure AI Services account, a storage account, and a service principal

## Run the UI

```bash
cp .env.example .env
docker compose up --build
```

Open http://localhost:8080

With no `.env`, the UI still starts. Narration falls back to Piper until Azure Speech is configured (`TTS_PROVIDER=azure` is the default; a missing speech resource uses Piper).

Stop with Ctrl-C. `docker compose down` removes the container.

## Save an image for an offline sandbox

```bash
docker compose build
docker save scriptcraft-hackathon:latest | gzip > scriptcraft-hackathon.tar.gz
# on the offline machine
gunzip -c scriptcraft-hackathon.tar.gz | docker load
docker compose up
```

`make save` writes the same tarball after the image exists.

## Narration

`TTS_PROVIDER` is `azure`, `piper`, or `elevenlabs`.

- **azure** (default): neural voice `en-US-AvaMultilingualNeural` (`TTS_VOICE`). SSML `prosody rate` is computed from `TTS_WPM` (175) and `TTS_BASELINE_WPM` (150), which is `+17%`. Auth is Entra (`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET`) or `AZURE_SPEECH_KEY` plus `AZURE_SPEECH_REGION`. The speech endpoint is the same AI Services account setup creates. No separate Speech resource.
- **piper**: offline. The image includes the Piper binary and the `en_US-lessac-medium` voice. ffmpeg then fits the clip to about 175 wpm.
- **elevenlabs**: used only when `ELEVENLABS_API_KEY` is set and `TTS_PROVIDER=elevenlabs`.

Every provider is passed through `explainer_video.normalize_audio` (-14 LUFS). Azure Speech supplies word boundaries. Piper and ElevenLabs use faster-whisper (`tiny.en`, baked into the image). The explainer reads the `.words.json` sidecar.

Try Piper without Azure:

```bash
docker compose run --rm -e TTS_PROVIDER=piper scriptcraft \
  python narration.py --provider piper \
  --text "This is a short narration test for the hackathon sandbox. It should be paced for clear speech and normalized for broadcast loudness." \
  --out /tmp/piper-check.wav
```

`./smoke-test.sh` builds the image, checks `/healthz` with no Azure credentials, and writes that WAV inside the container.

## Azure setup

Nothing here is tied to an existing subscription. Pick the sandbox tenant, subscription, region, and a short prefix.

```bash
az login --tenant <sandbox tenant>
az account set --subscription <sandbox subscription>
./setup-azure.sh --subscription <sandbox subscription> --location eastus2 --prefix scraft
docker compose up --build
```

`setup-azure.sh` is idempotent. It:

1. Creates resource group `rg-<prefix>-scriptcraft`.
2. Deploys `infra/main.bicep` (Azure AI Services account, Foundry project, private blob containers `app-settings` and `finished-videos`). `azd provision` is attempted first when `azd` is installed; `azure.yaml` has no app service, so the container is not deployed to Azure. The script always finishes with `az deployment group create`.
3. Deploys the model **names** the agents call (`infra/models.json`). If the region has no quota for the preferred model, it retries smaller capacities and then the next model in the list, still under the deployment name the code expects (`claude-opus-5-5`, `claude-opus-5-5-2`, `gpt-5.4-mini`). Grok for the quotes agent is not a Foundry deployment; set `XAI_API_KEY` or that one agent is skipped.
4. Creates a service principal `<prefix>-scriptcraft` with Cognitive Services User on the AI account and Storage Blob Data Contributor on the storage account. The project identity gets Cognitive Services OpenAI User so hosted agents can call the deployments.
5. Writes `.env` (mode 600) and `.hackathon-state.json`. Secrets stay in `.env` and are not printed. Re-running keeps an existing local secret instead of rotating it.
6. Registers the MAF hosted agents with `maf/hosted/deploy.py` using your `az login` (Foundry Project Manager on the project you just created).

Hosted agents (each named `<portal name>-MAF`):

- Script-Topic-Assistant-Agent, Script-Topic-Assistant-List-Agent, Script-Topic-Assistant-Predictions-Agent
- Script-Writer-Agent, Script-Writer-List-Agent, Script-Writer-Predictions-Agent, Script-Writer-Pro-Agent
- Script-Reviewer-Agent, Script-Demo-Assistant-Agent
- Script-Hook-and-Summary-Agent, Script-Polisher-Agent, Script-Repeat-and-Flow-Agent, Script-Shorten-Agent
- Script-bRoll-Agent, Script-Youtube-Upload-Details-Agent
- Statistics-and-Quotes-Finder-Agent (only if `XAI_API_KEY` is set)

Key Vault is not created. This app stores settings in the private blob and reads keys from the environment.

Speech does not need its own model deployment. Neural voices, including Ava, are part of the AI Services account. Setup writes `AZURE_SPEECH_REGION`, `AZURE_SPEECH_ENDPOINT`, and, when the CLI can list keys, `AZURE_SPEECH_KEY`.

### Host it in Azure instead of local Docker

If the sandbox has no Docker, run this after `setup-azure.sh`:

```bash
./deploy-containerapp.sh            # add --min-replicas 1 to avoid cold starts
```

It creates a Basic container registry, builds the image in Azure
(`az acr build`), and deploys one Azure Container App (consumption plan, 1 vCPU,
2 GiB, scales to zero) in the same resource group. The app signs in with its
own managed identity (Cognitive Services User on the AI account, Storage Blob
Data Contributor on the storage account), so no client secret or Speech key is
copied into it. The public URL asks for a sign-in token, which the script
writes to `.app-token` (mode 600, git-ignored) and does not print.

Notes from the first real sandbox run (2026-11-26):

- Claude models on Foundry ask for Anthropic marketplace details
  (organization name, industry, country) before they deploy. Setup does not
  fill those in for you, so the deployment names fall back to `gpt-5` and
  `gpt-5.4-mini` under the same names the agents call.
- Subscription Owner does not include Foundry data actions. Setup grants the
  signed-in user Foundry Project Manager on the project so it can register the
  hosted agents.
- Optional keys such as `XAI_API_KEY` are read from `.env` only, never from the
  shell that runs setup.

### Tear it down

```bash
./teardown-azure.sh
```

That deletes the resource group, the service principal, `.env`, and the state file. `--keep-sp` leaves the principal.

Validate the template without deploying:

```bash
az bicep build --file infra/main.bicep
```

`az deployment group what-if` needs a real login; do not run it against a production subscription by accident.

## Local-only features

`SCRIPTCRAFT_DISABLE_LOCAL_FEATURES=1` (the image default) returns HTTP 503 `feature_disabled_in_container` for DaVinci Resolve, local Whisper, native file pickers, and YouTube analytics. The page hides those controls. Analytics tells you it runs on a desktop. `channel_playbook.md` and `youtube_client_secret.json` are optional; if they are absent the playbook block is empty and YouTube upload stays disconnected.

## Layout

- `container_app.py`, `web_gui.py`, `explainer_*.py` — the v3 app
- `narration.py` — Azure / Piper / ElevenLabs
- `maf/` — hosted-agent source and `maf/hosted/deploy.py`
- `agent_instructions/` — prompts the hosted agents ship with
- `infra/` — Bicep and model fallbacks
