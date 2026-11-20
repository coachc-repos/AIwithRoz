# Azure Deployment Plan

> **Status:** Planning

Generated: 2026-11-07

This plan is not approved and not validated. No Container App, registry, or Foundry call was made. Do not deploy until this plan is approved and azure-validate has completed against the confirmed live target.

---

## 1. Project Overview

**Goal:** Put two already-reviewed code fixes on the existing ScriptCraft Container App: the Idea Generator Grok key fix (PR 6) and the literal Grok Imagine prompt fix (PR 7). Keep the same app, registry, environment, storage, and secrets.

**Path:** Add Components

**Not in scope:** New resources, a redesign, a push to `main`, a Foundry instruction redeploy, or a live image update during this run.

---

## 2. Requirements

| Attribute | Value |
|-----------|-------|
| Classification | Production |
| Scale | Small |
| Budget | Cost-Optimized |
| **Subscription** | UNCONFIRMED. This run did not call Azure. The operator must confirm the subscription that owns `scriptcraft-rg` before any deploy. |
| **Location** | `eastus` is hardcoded in both container deploy scripts. Not verified against the live app. |

---

## 3. Components Detected

| Component | Type | Technology | Path |
|-----------|------|------------|------|
| ScriptCraft v3 web GUI | API | Python 3.12, Flask, Container Apps | `scriptcraft-app-v3/` and `scriptcraft-app-v3-container/` |
| ScriptCraft v2 web GUI | API | Python 3.12, Flask, Container Apps | `scriptcraft-app-v2/` and `scriptcraft-app-v2-container/` |

Both container deploy scripts target the same names: resource group `scriptcraft-rg`, Container Apps environment `linedrive-env`, app `scriptcraft-app`, registry `scriptcraftregistry`, image repository `scriptcraft`, port 8080. v3's script says it replaces whatever is currently on that app, including a v2 image.

---

## 4. Recipe Selection

**Selected:** AZCLI

**Rationale:** The app is already deployed by `scriptcraft-app-v3-container/deploy-azure.sh` and `scriptcraft-app-v2-container/deploy-azure.sh` (`az acr build`, `az containerapp update`). Do not add azd, Bicep, or Terraform. Do not run `azd init`.

---

## 5. Architecture

**Stack:** Containers

### Service Mapping

| Component | Azure Service | SKU |
|-----------|---------------|-----|
| Existing ScriptCraft app | Container App `scriptcraft-app` | Leave the live CPU, memory, replicas, and ingress as they are. The create path in the script (0.5 CPU, 1 Gi, min/max 1 replica) must not be used if the app already exists. |

### Supporting Services

| Service | Purpose |
|---------|---------|
| `scriptcraftregistry` | Build a new image tag. Do not delete old tags. |
| Existing settings blob | `container_app.py` restores `app-settings/web_gui_settings.json`. Do not change the storage account. |
| System-assigned managed identity | Already used for Foundry. Do not recreate or replace it. |

No new Log Analytics, Key Vault, or Application Insights resources.

---

## 6. Configuration and secrets

No secret values belong in this file or in git.

The v3 deploy script, after PR 6, sets these environment **names** when it updates the app: `PYTHONPATH`, `AI_PROJECT_API_KEY`, `GOOGLE_API_KEY`, and, only when a value was resolved, `ANTHROPIC_API_KEY`, `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`, `X_BEARER_TOKEN`, `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_AUTHOR_URN`, `LINKEDIN_API_VERSION`, `XAI_API_KEY`, `GROK_API_KEY`, `HEYGEN_API_KEY`, `AI_PROJECT_ENDPOINT`, plus `FINISHED_VIDEOS_BLOB_ACCOUNT` and `FINISHED_VIDEOS_BLOB_CONTAINER`.

`az containerapp update --set-env-vars` replaces the container env list. Before a deploy, compare live env **names** to that list. If the live app has a name the script does not set, stop. Do not print values.

PR 6 copies a resolved Grok credential into both `XAI_API_KEY` and `GROK_API_KEY`. It does not print the key.

---

## 7. Live target gate (blocking)

The repository cannot prove which image is running. v2 and v3 deploy scripts write different tags into the same app (`v2c.<timestamp>` versus `v3c.<timestamp>`).

Before any build, the operator records, without printing secrets:

1. `az containerapp show -n scriptcraft-app -g scriptcraft-rg --query "{image:properties.template.containers[0].image, rev:properties.latestRevisionName, fqdn:properties.configuration.ingress.fqdn}"`
2. `GET https://<fqdn>/healthz`

| healthz `version` | Image tag prefix | Meaning | Allowed update |
|-------------------|------------------|---------|----------------|
| `3.0-maf` | `v3c.` | Current code is the v3 container | Build v3 from the merged `maf-migration` commit |
| `15.39-broll-regenerate` | `v2c.` | Current code is the v2 container | Do **not** run the v3 deploy script. That replaces the whole app with v3 (MAF agents, different GUI). The literal-prompt fix is in v2 source. The Grok idea-key fix is **not** in v2 source. A v2-only key patch, or an explicit decision to switch the app to v3, has to come first. |
| anything else | anything else | Unknown | Stop. Do not deploy. |

This run did not perform those checks.

---

## 8. Image and source, only if the live app is v3

**Source:** `maf-migration` after PRs 6 and 7 are merged. Record that merge SHA. Do not build from a dirty tree.

**Code commits reviewed together:**

- PR 6: `0ad8accba0f1462a4ec2dfce4141372308406e5b`
- PR 7: `f27204ef16a5417e1537a071e345a55f0ad17f1d`

A local merge of those two onto `origin/maf-migration` (`960f622`) produced tree-level commit `49edcb4bd28b939d8efb77f0afa8bb2bad14b7a5` for tests only. That SHA is not the GitHub merge commit.

**Image:** Let `scriptcraft-app-v3-container/deploy-azure.sh` tag `scriptcraft:v3c.<YYYYMMDDHHMM>` as it already does. Also record `git rev-parse HEAD`. Do not move a `:latest` tag. Do not delete the previous `scriptcraft` tag.

`deploy-azure.sh` runs `sync-from-v3.sh` first. After both PRs are on `maf-migration`, that sync copies the v3 files that already contain both fixes. Do not deploy from a checkout that has only one of the two PRs.

**Foundry:** The hosted Pro writer instructions in git changed with PR 7. Redeploying that agent is a separate step and is not part of this Container App update. Until that redeploy, the app still rewrites Imagine lines locally after the model returns.

---

## 9. Deploy sequence (not authorized yet)

Only after approval, azure-validate, and the v3 gate in section 7:

1. From a clean checkout of the merged `maf-migration` SHA, `cd scriptcraft-app-v3-container`.
2. Snapshot the current image name, revision name, and env **names**.
3. Run `./deploy-azure.sh`. It builds in ACR and updates the existing app. It does not create a second app when `scriptcraft-app` already exists.
4. The script then sets single-revision mode and **deactivates older revisions**. The previous image tag remains in the registry unless someone deletes it. Treat deactivation as expected, and keep the previous image name written down.
5. Do not change storage, the settings blob, ingress type, CPU, or memory on an update.

---

## 10. Health check and rollback

**Check:** `GET https://<fqdn>/healthz` returns `{"status":"ok","mode":"container","version":"3.0-maf"}` after a v3 deploy. Then open the app and confirm it loads. Do not run a paid Grok or Claude generation as the health check.

**Rollback:** `az containerapp update -n scriptcraft-app -g scriptcraft-rg --image <previous-image>`. That creates a new revision from the previous image. If single-revision mode deactivated the old revision, updating the image is the rollback. Do not delete the app, registry, storage account, or identity.

The v3 script's own comment says the same rollback: point the app at the previous image tag.

---

## 11. Success criteria

- Live target was identified before the build.
- `/healthz` matches the version that was intentionally deployed.
- Env names that existed before the update still exist, plus `XAI_API_KEY` when a Grok key was already present under either name.
- A new script's Grok Imagine lines describe the adjacent paragraph (portrait or party emblem when that is the subject; a chart plus 10% / 20% editor overlays for a correction definition).
- Existing scripts are unchanged until regenerated.
- No new Azure resources.

---

## 12. Cost

No new resources. The cost stays the existing Container App and one additional ACR image tag. Not measured here.

---

## 13. Validation

**Status:** Not validated.

Checks that did run, locally, with no Azure and no paid generation:

- PR 6 and PR 7 both reported `MERGEABLE` / `CLEAN` against `maf-migration`. GitHub `statusCheckRollup` was empty: no CI checks are configured on these PRs.
- A local merge of both branches onto `origin/maf-migration` completed with no conflicts.
- `python3 scriptcraft-app-v2/maf/testing/grok_imagine_literal_checks.py` — 12 passed.
- `python3 -m pytest -q scriptcraft-app-v3/tests/test_grok_idea_key.py` — 34 passed. Dummy keys only.

azure-validate was not run. The plan status is still Planning, which is what that skill requires before it will start. Do not mark this file Approved, Ready for Validation, Validated, or Deployed in this run.
