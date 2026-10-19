#!/usr/bin/env python3
"""
Script Topic Assistant — TOP-N LIST archetype.

Routes to the Foundry agent "Script-Topic-Assistant-List-Agent", which plans a
ranked countdown (e.g. "Top 10 AI Tools"): it honors the requested count, lists
ALL N items, present-day practical tone, NOT a tutorial. Inherits all
topic-planning helpers from the base Script-Topic-Assistant client; only the
Foundry agent it addresses differs.

v2 (Foundry) addresses agents BY NAME, so no asst_ id is required for the call
— the id below is a v2-only sentinel used for logging.
"""

from .script_topic_assistant_agent_client import ScriptTopicAssistantAgentClient


class ScriptTopicAssistantListAgentClient(ScriptTopicAssistantAgentClient):
    """Topic assistant for the Top-N list / countdown archetype."""

    def __init__(self):
        super().__init__(
            agent_id="asst_topic_assistant_list_v2_only",
            agent_name="Script-Topic-Assistant-List-Agent",
        )
