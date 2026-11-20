"""Foundry hosted-agent entry point for the ScriptCraft MAF code agents.

One codebase serves any code agent: the hosted agent's MAF_AGENT environment
variable (set per agent by maf/hosted/deploy.py) names the Foundry portal agent
whose code version to serve. The agent is exposed through the Foundry Responses
protocol by agent_framework_foundry_hosting (port 8088), so it shows up in the
Foundry portal and can be called like any other Foundry agent.

Local run (from the zip root, or from maf/ in the repo):
    MAF_AGENT=Script-bRoll-Agent python hosted/main.py
    curl -X POST http://localhost:8088/responses -H "Content-Type: application/json" \
         -d '{"input": "SCRIPT TITLE: x\n\nSCRIPT:\nHost: hello"}'
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# In the deployment zip, main.py sits at the root next to agents/; in the repo
# it lives in maf/hosted/, one level below.
for root in (HERE, os.path.dirname(HERE)):
    if os.path.isdir(os.path.join(root, "agents")):
        sys.path.insert(0, root)
        break

from agent_framework_foundry_hosting import ResponsesHostServer  # noqa: E402

from agents.registry import build_agent  # noqa: E402
from observability import load_env  # noqa: E402


def main() -> None:
    load_env()
    name = os.environ.get("MAF_AGENT", "").strip()
    if not name:
        raise SystemExit("Set MAF_AGENT to a Foundry portal agent name, e.g. Script-bRoll-Agent")
    ResponsesHostServer(build_agent(name)).run()


if __name__ == "__main__":
    main()
