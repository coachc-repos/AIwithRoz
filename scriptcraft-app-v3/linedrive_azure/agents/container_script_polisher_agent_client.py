#!/usr/bin/env python3
"""
Container Script Polisher Agent Client - Container-specific version

This is a container-specific version for Azure Container Apps deployment
that uses the container base agent client.
"""

from typing import Dict, Any, List
from .container_base_agent_client import ContainerBaseAgentClient


class ContainerScriptPolisherAgentClient(ContainerBaseAgentClient):
    """Container-specific client for final script polishing"""

    def __init__(self):
        """Initialize the Container Script Polisher Agent"""
        super().__init__(
            agent_id="asst_GhmZPA8ktCsrgFTUAgNbA8F6", agent_name="Script-Polisher-Agent"
        )

    def get_specialized_info(self) -> Dict[str, Any]:
        """Get specialized information about the script polisher agent"""
        return {
            "agent_type": "script_polishing",
            "capabilities": [
                "Final script polish and refinement",
                "Chapter structure creation and optimization",
                "Visual cue integration and enhancement",
                "Tool integration and verification",
                "Flow and pacing optimization",
                "Production readiness assessment",
            ],
            "polishing_focus": [
                "Narrative flow optimization",
                "Chapter breaks and structure",
                "Visual storytelling enhancement",
                "Tool integration per chapter",
                "Pacing and timing refinement",
                "Production note enhancement",
            ],
            "output_standards": [
                "One visual cue per chapter minimum",
                "At least one online tool per chapter",
                "Clear chapter divisions and titles",
                "Optimized narrative flow",
                "Production-ready formatting",
                "Enhanced engagement elements",
            ],
            "specializations": [
                "AI tool integration",
                "Educational content structure",
                "Video script optimization",
                "Chapter-based organization",
                "Visual storytelling elements",
                "Production workflow enhancement",
            ],
        }

    def polish_script(
        self,
        content: str,
        audience: str = "general",
        video_type: str = "educational",
        style: str = "conversational",
        max_wait_seconds: int = 180,
    ) -> Dict[str, Any]:
        """
        Polish a script with specific requirements
        
        Args:
            content: Raw script content to polish
            audience: Target audience (general, technical, beginner, etc.)
            video_type: Type of video (educational, tutorial, demo, etc.)
            style: Writing style (conversational, formal, casual, etc.)
            max_wait_seconds: Maximum wait time for response
            
        Returns:
            Dictionary with polished script and metadata
        """
        prompt = f"""Polish this script for a {audience} audience in a {style} style for a {video_type} video.

Requirements:
1. Create clear chapter structure with descriptive titles
2. Add at least one visual cue per chapter
3. Include relevant online tools/resources per chapter
4. Optimize flow and pacing for video format
5. Enhance engagement and educational value
6. Format for production readiness

Original Script:
{content}

Please provide:
- Polished script with chapter structure
- List of visual cues and their placement
- Online tools/resources integrated per chapter
- Production notes and timing suggestions
"""

        try:
            thread = self.create_thread()
            if not thread:
                return {
                    "success": False,
                    "error": "Failed to create conversation thread",
                    "polished_script": None,
                    "metadata": None,
                }

            result = self.send_message(
                thread_id=thread.id,
                message=prompt,
                show_sources=False,
                max_wait_seconds=max_wait_seconds,
            )

            if result["success"]:
                return {
                    "success": True,
                    "polished_script": result["response"],
                    "metadata": {
                        "audience": audience,
                        "video_type": video_type,
                        "style": style,
                        "agent_used": self.agent_name,
                        "processing_time": max_wait_seconds,
                    },
                    "error": None,
                }
            else:
                return {
                    "success": False,
                    "error": result["error"],
                    "polished_script": None,
                    "metadata": None,
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Script polishing failed: {str(e)}",
                "polished_script": None,
                "metadata": None,
            }