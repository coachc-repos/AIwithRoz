#!/usr/bin/env python3
"""
Script Topic Assistant — PREDICTIONS archetype.

Routes to the Foundry agent "Script-Topic-Assistant-Predictions-Agent", which
plans a bold/visionary predictions video: it honors the requested prediction
count (one prediction per chapter), cinematic framing, no teaching / "already
here today" angle. Inherits all topic-planning helpers from the base
Script-Topic-Assistant client; only the Foundry agent it addresses differs.

v2 (Foundry) addresses agents BY NAME, so no asst_ id is required for the call
— the id below is a v2-only sentinel used for logging.
"""

from .script_topic_assistant_agent_client import ScriptTopicAssistantAgentClient


class ScriptTopicAssistantPredictionsAgentClient(ScriptTopicAssistantAgentClient):
    """Topic assistant for the bold-predictions / visionary archetype."""

    def __init__(self):
        super().__init__(
            agent_id="asst_topic_assistant_predictions_v2_only",
            agent_name="Script-Topic-Assistant-Predictions-Agent",
        )
