#!/usr/bin/env python3
"""
Script Writer — PREDICTIONS archetype.

Routes to the Foundry agent "Script-Writer-Predictions-Agent", which writes a
single prediction per chapter in a cinematic, visionary voice (no tutorial /
"already here today" framing). Inherits every helper from the base Script-Writer
client (YouTube style grounding, write_video_script, get_specialized_info, …);
only the Foundry agent it addresses differs.

v2 (Foundry) addresses agents BY NAME, so no asst_ id is required for the call
— the id below is a v2-only sentinel used for logging.
"""

from .script_writer_agent_client import ScriptWriterAgentClient


class ScriptWriterPredictionsAgentClient(ScriptWriterAgentClient):
    """Script writer for the bold-predictions / visionary archetype."""

    def __init__(self):
        super().__init__(
            agent_id="asst_script_writer_predictions_v2_only",
            agent_name="Script-Writer-Predictions-Agent",
        )
