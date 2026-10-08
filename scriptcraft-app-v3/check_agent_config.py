#!/usr/bin/env python3
"""
Quick check of agent configuration in Azure AI Foundry

This script checks if the Script Quotes and Statistics Agent
has its system instructions configured.
"""

from linedrive_azure.agents.quote_and_statistics_agent_client import (
    ScriptQuotesAndStatisticsAgentClient
)
import sys
import os

# Add scriptcraft-app directory to path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)


def main():
    print("\n" + "="*60)
    print("AGENT CONFIGURATION CHECK")
    print("="*60 + "\n")

    try:
        print("🔄 Connecting to agent...")
        client = ScriptQuotesAndStatisticsAgentClient()

        print(f"✅ Connected to agent")
        print(f"   Agent ID: {client.agent_id}")
        print(f"   Agent Name: {client.agent_name}")
        print()

        # Get agent details
        print("🔍 Checking agent configuration...")
        agent = client.project.agents.get_agent(client.agent_id)

        print(f"   Model: {agent.model}")
        print(
            f"   Instructions length: {len(agent.instructions) if agent.instructions else 0} chars")
        print()

        if agent.instructions:
            print("✅ Agent has system instructions configured")
            print(f"   First 200 chars: {agent.instructions[:200]}...")
        else:
            print("⚠️  WARNING: Agent has NO system instructions!")
            print("   This agent will not produce good results.")
            print()
            print("📋 ACTION REQUIRED:")
            print("   1. Go to: https://linedrive-ai-foundry.services.ai.azure.com")
            print("   2. Find agent: Script-Quotes-and-Statistics-Agent")
            print(f"   3. Agent ID: {client.agent_id}")
            print("   4. Upload contents of QUOTE_AND_STATISTICS_AGENT_PROMPT.md")
            print("   5. Save and test again")

        print()
        print("="*60)

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
