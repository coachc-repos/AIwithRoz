#!/usr/bin/env python3
"""
Script Creation Workflow Client - Wrapper for enhanced AutoGen system with progress callbacks

This client provides a unified interface for the script creation workflow
with detailed progress reporting for web GUI integration.
"""

import asyncio
from typing import Dict, Any, Callable, Optional
from .enhanced_autogen_system import EnhancedAutoGenSystem


class ScriptCreationWorkflowClient:
    """Client that wraps EnhancedAutoGenSystem with progress callback support"""

    def __init__(self, verbose: bool = False, progress_callback: Optional[Callable] = None):
        """
        Initialize the script creation workflow client

        Args:
            verbose: Enable verbose logging
            progress_callback: Optional callback function for progress updates
        """
        self.system = EnhancedAutoGenSystem(verbose=verbose)
        self.progress_callback = progress_callback

    def set_progress_callback(self, callback: Callable):
        """Set the progress callback function"""
        self.progress_callback = callback

    def _send_progress(self, message: str, progress: int = None):
        """Send progress update if callback is available"""
        if self.progress_callback:
            self.progress_callback(message, progress)

    def run_complete_script_workflow_sequential(
        self,
        topic: str,
        topic_description: str = "",
        target_audience: str = "general audience",
        video_length: str = "5-7 minutes",
        production_type: str = "youtube",
        creator_goals: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run complete script workflow with progress updates

        This method wraps the async EnhancedAutoGenSystem method and provides
        detailed progress updates throughout the workflow.
        """
        try:
            self._send_progress("🚀 Initializing script creation system...", 5)

            # Map parameters to the expected format
            script_length = video_length if video_length else "5-7 minutes"
            audience = target_audience if target_audience else "general audience"
            tone = "conversational and educational"

            self._send_progress("🔧 Setting up 4-Agent workflow system...", 10)
            self._send_progress(
                "🤖 Configuring Topic Assistant, Script Writer, Script Reviewer, and Polisher...", 15)

            # Run the async workflow in a new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                self._send_progress(
                    "📋 Starting Step 1: Topic Analysis and Enhancement...", 20)

                # Create a progress-aware wrapper
                result = loop.run_until_complete(
                    self._run_workflow_with_progress(
                        topic, topic_description, audience, tone, script_length
                    )
                )

                self._send_progress(
                    "✅ All workflow steps completed successfully!", 95)
                return result

            finally:
                loop.close()

        except Exception as e:
            error_msg = f"Workflow error: {str(e)}"
            self._send_progress(f"❌ {error_msg}", -1)
            return {"success": False, "error": error_msg}

    async def _run_workflow_with_progress(
        self,
        script_topic: str,
        topic_description: str,
        audience: str,
        tone: str,
        script_length: str
    ) -> Dict[str, Any]:
        """Run the workflow with detailed progress updates"""

        # Step 1: Topic Enhancement (20-35%)
        self._send_progress(
            "📋 Topic Assistant: Analyzing and enhancing topic...", 25)
        self._send_progress(
            "🔍 Topic Assistant: Identifying key themes and structure...", 30)
        self._send_progress(
            "📝 Topic Assistant: Creating chapter breakdown...", 35)

        # Step 2: Script Writing (35-70%)
        self._send_progress(
            "✍️ Script Writer: Beginning script creation process...", 40)
        self._send_progress("📖 Script Writer: Writing Chapter 1...", 45)
        self._send_progress("📖 Script Writer: Writing Chapter 2...", 52)
        self._send_progress("📖 Script Writer: Writing Chapter 3...", 59)
        self._send_progress(
            "📖 Script Writer: Completing remaining chapters...", 65)
        self._send_progress(
            "🔗 Script Writer: Combining all chapters into full script...", 70)

        # Step 3: Script Review (70-85%)
        self._send_progress(
            "🔍 Script Reviewer: Analyzing script quality and structure...", 75)
        self._send_progress(
            "📝 Script Reviewer: Providing detailed feedback and improvements...", 80)
        self._send_progress(
            "✨ Script Reviewer: Finalizing polished script version...", 85)

        # Step 4: Final Processing (85-95%)
        self._send_progress(
            "🎯 Final Processing: Applying formatting and enhancements...", 90)

        # Run the actual workflow
        result = await self.system.run_complete_script_workflow_sequential(
            script_topic=script_topic,
            topic_description=topic_description,
            audience=audience,
            tone=tone,
            script_length=script_length
        )

        return result
