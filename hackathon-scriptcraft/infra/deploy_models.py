#!/usr/bin/env python3
"""Create the Foundry model deployments this app calls.

Reads infra/models.json. Lists the account catalog and deploys the first
preferred model the region actually offers, walking SKU and capacity fallbacks
when quota is refused. Prints deployment names only, never keys.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _az(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["az", *args],
        check=check, capture_output=True, text=True,
    )


def list_catalog(account: str, group: str) -> list[dict]:
    proc = _az([
        "cognitiveservices", "account", "list-models",
        "-n", account, "-g", group, "-o", "json",
    ])
    data = json.loads(proc.stdout or "[]")
    if isinstance(data, dict):
        data = data.get("value") or data.get("models") or []
    return data if isinstance(data, list) else []


def _model_fields(entry: dict) -> tuple[str, str, str, str]:
    model = entry.get("model") if isinstance(entry.get("model"), dict) else entry
    name = str((model or {}).get("name") or entry.get("name") or "")
    version = str((model or {}).get("version") or entry.get("version") or "")
    fmt = str((model or {}).get("format") or entry.get("format") or "OpenAI")
    sku = str(entry.get("skuName") or entry.get("sku") or "")
    return name, version, fmt, sku


def _quota_error(text: str) -> bool:
    low = text.lower()
    return any(token in low for token in (
        "quota", "insufficient", "specialfeatureorquota", "capacity",
    ))


def _create(account: str, group: str, deployment: str, name: str,
            version: str, fmt: str, sku: str, capacity: int) -> tuple[bool, str]:
    proc = _az([
        "cognitiveservices", "account", "deployment", "create",
        "-n", account, "-g", group,
        "--deployment-name", deployment,
        "--model-name", name,
        "--model-version", version,
        "--model-format", fmt,
        "--sku-name", sku,
        "--sku-capacity", str(capacity),
    ], check=False)
    if proc.returncode == 0:
        return True, ""
    detail = (proc.stderr or proc.stdout or "")[-500:]
    return False, detail


def deploy(account: str, group: str, manifest: Path) -> dict[str, str]:
    spec = json.loads(manifest.read_text(encoding="utf-8"))
    catalog = list_catalog(account, group)
    if not catalog:
        print("No models returned for this account. Check the region and that the provider is registered.")
    chosen: dict[str, str] = {}
    for item in spec["deployments"]:
        deployment = item["deploymentName"]
        env_var = item["envVar"]
        existing = _az([
            "cognitiveservices", "account", "deployment", "show",
            "-n", account, "-g", group, "--deployment-name", deployment,
            "-o", "json",
        ], check=False)
        if existing.returncode == 0:
            print(f"deployment {deployment} already exists")
            chosen[env_var] = deployment
            continue
        match = None
        for preferred in item["modelNamePreference"]:
            for entry in catalog:
                name, version, fmt, sku = _model_fields(entry)
                if name == preferred and version:
                    match = (name, version, fmt, sku)
                    break
            if match:
                break
        if not match:
            print(f"WARNING: no catalog model for {deployment} "
                  f"(wanted {', '.join(item['modelNamePreference'])})")
            if item.get("required"):
                raise SystemExit(f"required deployment {deployment} has no matching model")
            continue
        name, version, fmt, catalog_sku = match
        skus = []
        for sku in item.get("skuCandidates") or []:
            if sku not in skus:
                skus.append(sku)
        if catalog_sku and catalog_sku not in skus:
            skus.insert(0, catalog_sku)
        ok = False
        last = ""
        for sku in skus:
            for capacity in item.get("capacityFallback") or [1]:
                print(f"creating {deployment} from {fmt}/{name}/{version} "
                      f"sku={sku} capacity={capacity}")
                ok, last = _create(
                    account, group, deployment, name, version, fmt, sku, int(capacity))
                if ok:
                    break
                if not _quota_error(last):
                    print(f"WARNING: {deployment} rejected ({sku}/{capacity}): {last.strip()}")
                    break
                print(f"quota refused for {deployment} at {sku}/{capacity}; trying a smaller size")
            if ok:
                break
        if not ok:
            print(f"WARNING: could not create {deployment}: {last.strip()}")
            if item.get("required"):
                raise SystemExit(f"required deployment {deployment} was not created")
            continue
        chosen[env_var] = deployment
        print(f"ready {deployment} ({env_var})")
    return chosen


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: deploy_models.py <account> <resource-group> <models.json>")
    chosen = deploy(sys.argv[1], sys.argv[2], Path(sys.argv[3]))
    Path(sys.argv[3]).with_name("deployed-models.json").write_text(
        json.dumps(chosen, indent=2) + "\n", encoding="utf-8")
    print("wrote deployment name map (no secrets)")


if __name__ == "__main__":
    main()
