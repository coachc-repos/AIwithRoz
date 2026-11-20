#!/usr/bin/env python3
"""
Script Polisher Agent Client - Specialized client for final script polishing and refinement

This agent handles final script polish, adds chapter structure, visual cues,
and ensures tool integration for production-ready scripts.
"""

from typing import Dict, Any, List
from .base_agent_client import BaseAgentClient


class ScriptPolisherAgentClient(BaseAgentClient):
    """Specialized client for final script polishing and production preparation"""

    def __init__(self):
        """Initialize the Script Polisher Agent"""
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
                "Video production optimization",
                "Educational content structuring",
                "Tool integration strategies",
                "Visual storytelling techniques",
                "Audience engagement enhancement",
            ],
        }

    def polish_script(
        self,
        raw_script: str,
        script_title: str = None,
        target_audience: str = "general",
        production_type: str = "video",
        special_requirements: str = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        Polish a near-final script for production readiness

        Args:
            raw_script: The script content to polish
            script_title: Title of the script (extracted if not provided)
            target_audience: Target audience for the content
            production_type: Type of production (video, podcast, etc.)
            special_requirements: Any special requirements for the script
            timeout: Maximum time to wait for response

        Returns:
            Polished script with enhanced structure and production elements
        """

        # Extract title if not provided
        if not script_title:
            lines = raw_script.split("\n")
            for line in lines[:10]:  # Check first 10 lines for title
                if line.strip() and not line.startswith("#"):
                    script_title = line.strip()
                    break
            if not script_title:
                script_title = "Untitled Script"

        query = f"""
        MANDATORY INSTRUCTION: You are a script polisher specializing in final production preparation. 
        You must immediately analyze and polish the provided script. DO NOT ask clarifying questions. 
        DO NOT request additional information. USE THE PROVIDED SCRIPT AND CREATE THE POLISHED VERSION NOW.

        IMMEDIATE ACTION REQUIRED: Polish the following script for final production:

        SCRIPT TO POLISH:
        {raw_script}

        POLISHING REQUIREMENTS:
        - Script Title: {script_title}
        - Target Audience: {target_audience}
        - Production Type: {production_type}
        
        CRITICAL POLISHING STANDARDS:
        1. CHAPTER STRUCTURE: Create clear chapter divisions with descriptive titles
           - Each chapter should be 2-4 minutes of content
           - Logical progression and flow between chapters
           - Clear transitions and chapter breaks
        
        2. VISUAL CUE REQUIREMENTS: Add exactly ONE visual cue per chapter
           - Format: [Visual Cue: Description of what should be shown]
           - Place visual cues at strategically important moments
           - Visual cues should enhance understanding and engagement
           - Examples: [Visual Cue: Show screen recording of the tool interface]
           - Examples: [Visual Cue: Display comparison chart of pricing options]
           - Examples: [Visual Cue: Show step-by-step animation of the process]
        
        3. TOOL INTEGRATION: Ensure at least ONE online tool is mentioned per chapter
           - Each tool must be REAL and currently available
           - Include complete URLs where applicable
           - Provide specific instructions on how to access/use each tool
           - Add discovery information (YouTube search terms, etc.)
           - Include pricing information where relevant
           - Examples: ChatGPT (chat.openai.com), Canva (canva.com), Notion (notion.so)
        
        4. FLOW OPTIMIZATION:
           - Smooth transitions between topics and chapters
           - Natural pacing and rhythm
           - Engaging hooks and retention elements
           - Clear narrative progression
        
        5. CONTENT FOCUS:
           - Keep the script focused on the host content
           - Avoid production timing blocks (no [00:00 - 00:05] timestamps)
           - Skip AUDIO/VISUAL/TRANSITION production elements
           - Focus on the actual spoken content and tool demonstrations
        
        EXISTING CONTENT REVIEW:
        - If the script already has visual cues, review them and suggest improvements
        - If chapters already exist, optimize their structure and flow
        - If tools are already mentioned, ensure they meet quality standards
        - Add your analysis and recommendations in a separate section
        
        OUTPUT FORMAT:
        Please structure your response as:

        # POLISHED SCRIPT: {script_title}

        ## REVISION SUGGESTIONS
        [Provide specific suggestions for improving the script, including:]
        - Content enhancement recommendations
        - Flow and pacing suggestions
        - Engagement improvements
        - Technical considerations for {production_type} format

        ## TOOLS TO DEMO
        [List of real online tools that should be demonstrated, with:]
        - Tool name and purpose
        - When to show it in the script (reference line numbers or sections)
        - What specific features to highlight
        - Access information (free/paid, signup required, etc.)

        ## VISUAL CUES TO ADD
        [List of visual cues to add inline with the script, with:]
        - Specific placement instructions (after which line/paragraph)
        - Detailed description of what to show
        - Duration and timing suggestions

        ## ORIGINAL SCRIPT WITH INLINE ADDITIONS
        [The complete original script text with ONLY these additions:]
        - **Visual Cue:** [Description] - added inline at appropriate moments
        - **Tool Demo:** [Tool name and action] - added where tools should be shown
        - Keep ALL original text exactly as provided
        - Do NOT rewrite or change the original content
        - Only INSERT visual cues and tool demo markers

        ## PRODUCTION NOTES
        [Additional technical notes for the production team]

        ABSOLUTE REQUIREMENTS:
        - Preserve the original script text completely unchanged
        - Only add inline **Visual Cue:** and **Tool Demo:** markers
        - Provide clear suggestions in the dedicated sections above
        - Do not rewrite, restructure, or modify the original content
        - Ensure tool demos are practical and accessible
        - Make visual cues specific and actionable
        - Optimize suggestions for {production_type} production format
        - NEVER add production timing blocks like [00:00 - 00:05]
        - NEVER add AUDIO: XXX / VISUAL: XXX / TRANSITION: elements
        - NEVER add NOTES FOR PRODUCER: sections
        - Focus on content the host will actually speak or demonstrate
        """

        if special_requirements:
            query += f"\n- Special Requirements: {special_requirements}"

        query += """
        
        START YOUR RESPONSE IMMEDIATELY WITH THE POLISHED SCRIPT. No preamble, no questions.
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create polishing thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )

    def review_existing_elements(
        self,
        script_content: str,
        element_type: str = "visual_cues",
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """
        Review existing script elements (visual cues, chapters, tools)

        Args:
            script_content: The script to review
            element_type: Type of elements to review (visual_cues, chapters, tools)
            timeout: Maximum time to wait for response

        Returns:
            Analysis and recommendations for existing elements
        """

        query = f"""
        Review the existing {element_type} in this script and provide recommendations:

        SCRIPT CONTENT:
        {script_content}

        REVIEW FOCUS: {element_type}

        Please analyze and provide:
        1. Current state of {element_type} in the script
        2. Quality assessment of existing elements
        3. Specific recommendations for improvement
        4. Suggested additions or modifications
        5. Best practices alignment

        Provide actionable feedback for enhancing the script's {element_type}.
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create review thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )

    def add_chapter_structure(
        self,
        script_content: str,
        chapter_count: int = None,
        timeout: int = 240,
    ) -> Dict[str, Any]:
        """
        Add or enhance chapter structure in a script

        Args:
            script_content: The script to structure
            chapter_count: Desired number of chapters (auto-determined if not provided)
            timeout: Maximum time to wait for response

        Returns:
            Script with enhanced chapter structure
        """

        query = f"""
        Add clear chapter structure to this script:

        SCRIPT CONTENT:
        {script_content}

        CHAPTER STRUCTURE REQUIREMENTS:
        - Create logical chapter divisions based on content flow
        - Each chapter should be 2-4 minutes of speaking content
        - Provide descriptive chapter titles
        - Ensure smooth transitions between chapters
        - Maintain narrative progression
        """

        if chapter_count:
            query += f"\n- Target Chapter Count: {chapter_count}"

        query += """
        
        Please provide:
        1. Recommended chapter breakdown
        2. Chapter titles and descriptions
        3. Timing estimates for each chapter
        4. Enhanced script with clear chapter markers
        5. Transition improvements between chapters
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create chapter thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )

    def enhance_visual_cues(
        self,
        script_content: str,
        production_style: str = "professional",
        timeout: int = 200,
    ) -> Dict[str, Any]:
        """
        Add or enhance visual cues throughout the script

        Args:
            script_content: The script to enhance
            production_style: Style of visual cues (professional, casual, educational)
            timeout: Maximum time to wait for response

        Returns:
            Script with enhanced visual cue integration
        """

        query = f"""
        Enhance the visual cues in this script for {production_style} production:

        SCRIPT CONTENT:
        {script_content}

        VISUAL CUE REQUIREMENTS:
        - At least one visual cue per major section/chapter
        - Format: [Visual Cue: Clear description of what to show]
        - Cues should enhance understanding and engagement
        - Match the {production_style} production style
        - Strategic placement at key moments
        - Support the narrative and teaching points

        VISUAL CUE TYPES:
        - Screen recordings and software demonstrations
        - Comparison charts and infographics
        - Step-by-step process animations
        - Product showcases and interfaces
        - Data visualizations and statistics
        - Before/after comparisons

        Please provide the enhanced script with integrated visual cues.
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create visual cue thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )

    def verify_tool_integration(
        self,
        script_content: str,
        minimum_tools_per_chapter: int = 1,
        timeout: int = 200,
    ) -> Dict[str, Any]:
        """
        Verify and enhance tool integration throughout the script

        Args:
            script_content: The script to verify
            minimum_tools_per_chapter: Minimum tools required per chapter
            timeout: Maximum time to wait for response

        Returns:
            Analysis of tool integration with recommendations
        """

        query = f"""
        Verify and enhance the online tool integration in this script:

        SCRIPT CONTENT:
        {script_content}

        TOOL INTEGRATION REQUIREMENTS:
        - Minimum {minimum_tools_per_chapter} real online tool(s) per chapter
        - Each tool must be currently available and accessible
        - Include complete URLs and access instructions
        - Provide pricing information where relevant
        - Add YouTube search terms for learning more
        - Tools must be relevant to the chapter content

        Please analyze:
        1. Current tool mentions and their quality
        2. Missing tool opportunities in each chapter
        3. Tool accessibility and URL verification needs
        4. Enhanced integration suggestions
        5. Discovery and learning resource additions

        Provide recommendations for improving tool integration.
        """

        thread = self.create_thread()
        if not thread:
            return {
                "success": False,
                "error": "Failed to create tool verification thread",
            }

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )
