#!/usr/bin/env python3
"""
Script Writer — TOP-N LIST archetype.

Routes to the Foundry agent "Script-Writer-List-Agent", which writes a ranked
countdown: one list item per chapter, present-day practical tone, counts down to
#1 last, not a tutorial. Inherits every helper from the base Script-Writer
client (YouTube style grounding, write_video_script, get_specialized_info, …);
only the Foundry agent it addresses differs.

v2 (Foundry) addresses agents BY NAME, so no asst_ id is required for the call
— the id below is a v2-only sentinel used for logging.
"""

from .script_writer_agent_client import ScriptWriterAgentClient


class ScriptWriterListAgentClient(ScriptWriterAgentClient):
    """Script writer for the Top-N list / countdown archetype."""

    def __init__(self):
        super().__init__(
            agent_id="asst_script_writer_list_v2_only",
            agent_name="Script-Writer-List-Agent",
        )
