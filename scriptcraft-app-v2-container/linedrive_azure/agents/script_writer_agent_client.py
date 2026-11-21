#!/usr/bin/env python3
"""
Script Writer Agent Client - Specialized client for script and content writing

This agent handles script writing, content creation, narrative development,
and creative writing tasks for various media formats.
"""

from typing import Dict, Any, List
from .base_agent_client import BaseAgentClient
from .youtube_transcript_functions import YouTubeTranscriptSearcher


class ScriptWriterAgentClient(BaseAgentClient):
    """Specialized client for script writing and content creation"""

    def __init__(self, agent_id: str = "asst_gUvMkcUOwebEb4YWq0zfNMtb",
                 agent_name: str = "Script-Writer-Agent"):
        """Initialize the Script Writer Agent.

        Accepts an optional agent_id/agent_name so archetype-specific
        subclasses (predictions / Top-N list) can point at their own Foundry
        agent while inheriting every helper (style grounding, write_video_script,
        get_specialized_info, etc.) unchanged.
        """
        super().__init__(agent_id=agent_id, agent_name=agent_name)
        # Initialize YouTube transcript searcher for style grounding
        try:
            self.transcript_searcher = YouTubeTranscriptSearcher()
            self.transcript_available = True
        except Exception as e:
            print(f"Warning: YouTube transcript search not available: {e}")
            self.transcript_searcher = None
            self.transcript_available = False

    def get_specialized_info(self) -> Dict[str, Any]:
        """Get specialized information about the script writer agent"""
        return {
            "agent_type": "script_writing",
            "capabilities": [
                "Script writing and development",
                "Narrative structure creation",
                "Dialogue writing",
                "Content adaptation",
                "Character development",
                "Scene creation and pacing",
            ],
            "script_types": [
                "Video scripts",
                "Podcast scripts",
                "Social media content scripts",
                "Educational content",
                "Promotional scripts",
                "Training materials",
            ],
            "formats": [
                "Short-form content (30s-2min)",
                "Medium-form content (2-10min)",
                "Long-form content (10min+)",
                "Series/episodic content",
                "Interactive content",
            ],
            "specializations": [
                "Sports content writing",
                "Educational script development",
                "Entertainment writing",
                "Corporate content",
                "Training and instructional content",
            ],
        }

    def _calculate_word_count(self, duration: str) -> int:
        """Calculate approximate word count needed for given duration"""
        # Extract numeric value from duration string
        import re

        numbers = re.findall(r"\d+", duration.lower())
        if numbers:
            minutes = int(numbers[0])
            # Assume 150-160 words per minute speaking pace
            return minutes * 155
        return 1550  # Default to 10 minutes worth

    def get_style_references(
        self, topic: str, style: str = None, max_references: int = 3
    ) -> str:
        """
        Get style references from uploaded YouTube transcripts to ground the script writing

        Args:
            topic: The topic to search for relevant transcripts
            style: Specific style to search for (e.g., "educational", "entertaining")
            max_references: Maximum number of transcript references to return

        Returns:
            Formatted string with style references and examples
        """
        if not self.transcript_available:
            return ""

        style_references = ""

        try:
            # Search for transcripts related to the topic
            search_query = topic
            if style:
                search_query += f" {style}"

            results = self.transcript_searcher.search_youtube_transcripts(
                query=search_query, max_results=max_references
            )

            if results.get("videos"):
                style_references += "\n## STYLE REFERENCE MATERIALS\n"
                style_references += "Use these transcript excerpts as style guides for tone, pacing, and approach:\n\n"

                for i, video in enumerate(results["videos"][:max_references], 1):
                    video_title = video.get("video_title", "Unknown Title")
                    channel = video.get("channel_name", "Unknown Channel")
                    excerpt = video.get("transcript_excerpt", "")

                    # Clean and truncate excerpt for style reference
                    if excerpt:
                        # Get first 300 characters for style reference
                        style_excerpt = (
                            excerpt[:300] + "..." if len(excerpt) > 300 else excerpt
                        )
                        style_references += (
                            f"**Reference {i} - {video_title} ({channel}):**\n"
                        )
                        style_references += f'"{style_excerpt}"\n'
                        style_references += f"→ Note the tone, pacing, and structure for style guidance.\n\n"

                style_references += "INSTRUCTION: Analyze the style, tone, pacing, and structure from these references "
                style_references += "and incorporate similar elements into your script while maintaining originality.\n\n"

        except Exception as e:
            print(f"Warning: Could not retrieve style references: {e}")

        return style_references

    def write_video_script(
        self,
        topic: str,
        duration: str = "2-3 minutes",
        style: str = "educational",
        audience: str = "general",
        script_format: str = "standard",
        key_points: List[str] = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        Write a video script based on specifications

        Args:
            topic: Main topic/subject of the script
            duration: Target duration of the video
            style: Style of the script (educational, entertaining, promotional, etc.)
            audience: Target audience
            script_format: Script format (standard, interview, narration, etc.)
            key_points: Specific points to cover
            timeout: Maximum time to wait for response

        Returns:
            Complete video script with timing and direction notes
        """
        # Calculate target word count for the duration
        word_count = self._calculate_word_count(duration)

        # Get style references from uploaded YouTube transcripts
        style_references = self.get_style_references(topic, style, max_references=3)

        query = f"""
        MANDATORY INSTRUCTION: You are a script writer. You must immediately generate a complete, detailed video script. 
        DO NOT ask any clarifying questions. DO NOT request additional information. DO NOT say "Is there anything specific..."
        DO NOT ask what the user wants to adjust. USE THE PROVIDED INFORMATION AND CREATE THE FULL SCRIPT NOW.{style_references}

        IMMEDIATE ACTION REQUIRED: Generate a complete {word_count}+ word video script about "{topic}" right now.

        Write a comprehensive {style} video script about: {topic}
        
        Specifications:
        - Duration: {duration}
        - Style: {style}
        - Audience: {audience}
        - Format: SINGLE HOST PRESENTATION (no dialogue, no interviews)
        
        CRITICAL LENGTH REQUIREMENT: For a {duration} video, you need EXACTLY {word_count} words minimum 
        (assuming 150-160 words per minute speaking pace). Scripts under {word_count} words will be rejected.
        
        FORMAT REQUIREMENTS:
        - Single host speaking directly to camera/audience
        - No dialogue between multiple people
        - Host narrates everything personally
        - Visual cues and scene descriptions for production team
        - Direct, engaging presentation style
        
        ABSOLUTE REQUIREMENT: Generate the complete script immediately. Do not ask for clarification.
        If you need more details about the topic, research and include comprehensive information yourself.
        Start writing the script immediately with an engaging opening hook.
        
        Create a DETAILED, COMPREHENSIVE script with:
        - Extensive, in-depth explanations (not brief summaries)
        - Multiple detailed examples and real-world applications
        - Step-by-step walkthroughs where appropriate
        - Comprehensive comparisons and analysis
        - Rich storytelling with full explanations
        - Detailed technical explanations broken down for the audience
        - Multiple angles and perspectives on each topic
        - Full sentences and paragraphs of actual spoken content
        - Real quotes, statistics, and specific examples
        
        MANDATORY: REAL TOOLS REQUIREMENT
        Your script MUST mention at least 3 REAL, ACTIONABLE TOOLS that users can actually use or download:
        - Each tool mentioned MUST have its exact name and be currently available
        - Include complete, working URLs where applicable (e.g., "You can try ChatGPT at chat.openai.com")
        - Add YouTube search terms for each tool (e.g., "Search 'ChatGPT tutorial' on YouTube for more")
        - Provide installation commands for developer tools (e.g., "pip install openai")
        - Include pricing information where relevant (e.g., "free tier available" or "starts at $20/month")
        - MOST IMPORTANTLY: In the script itself, explain HOW TO GET each tool you mention
          * For web tools: "To get started, visit [URL] and create a free account"
          * For desktop software: "Download it from [URL] - installation takes about 5 minutes"
          * For APIs: "Sign up at [URL] to get your API key - they offer $5 free credit"
          * For browser extensions: "Install the extension from [URL] or search in your browser's extension store"
        - NO hypothetical or generic examples like "SomeAI Tool" or "AI Platform"
        - Examples of real tools: ChatGPT (chat.openai.com), Claude (claude.ai), Perplexity (perplexity.ai), 
          GitHub Copilot (copilot.github.com), OpenAI API (platform.openai.com), Hugging Face (huggingface.co), 
          Midjourney (midjourney.com), DALL-E (openai.com/dall-e), Ollama (ollama.ai), LangChain (langchain.com)
        - Focus on tools that genuinely demonstrate the concepts in your script
        - Provide context on what each tool does and how it relates to your topic
        - Include specific use cases and examples for each tool mentioned
        - Add discovery information: "To learn more, search 'TOOL_NAME tutorial' or 'TOOL_NAME getting started' on YouTube"
        - Detailed case studies and scenarios
        - SCRIPT INTEGRATION: Don't just mention tools - integrate acquisition steps naturally into your narrative
        
        CONTENT DEPTH REQUIREMENTS:
        - MINIMUM {word_count} words required for {duration} duration
        - Each major section must be 2-3 minutes of actual speaking time (350-500 words EACH)
        - Include extensive detailed explanations, not just bullet points
        - Provide 3-5 detailed examples for each concept with full explanations
        - Add comprehensive context, background, and thorough coverage
        - Write complete paragraphs and full explanations that would actually take time to say
        - Include detailed transitions, elaborations, and comprehensive discussions
        - Add step-by-step walkthroughs for technical concepts
        - Include multiple real-world scenarios and case studies
        - Provide detailed comparisons and in-depth analysis
        - Write conversational explanations that naturally extend the content
        - Include specific details, statistics, quotes, and concrete examples
        
        STRUCTURE REQUIREMENTS FOR {duration}:
        - Opening: 1-2 minutes (200-300 words of actual spoken content)
        - Main Section 1: 3 minutes (450+ words with detailed examples)
        - Main Section 2: 3 minutes (450+ words with detailed examples)  
        - Main Section 3: 3 minutes (450+ words with detailed examples)
        - Main Section 4: 3 minutes (450+ words with detailed examples)
        - Conclusion: 2 minutes (300+ words with comprehensive wrap-up)
        
        The host should speak naturally and conversationally, providing extremely thorough explanations
        with multiple examples, detailed walkthroughs, and comprehensive coverage that would 
        genuinely fill the entire {duration} duration when spoken aloud at normal pace.
        
        CRITICAL: Do not just outline or summarize. Write the FULL DETAILED CONTENT with 
        extensive explanations, multiple examples, and comprehensive coverage.
        
        ABSOLUTE PROHIBITIONS:
        - NEVER ask clarifying questions like "Is there anything specific you would like to adjust?"
        - NEVER request additional information
        - NEVER suggest modifications or ask for preferences
        - NEVER provide incomplete scripts or outlines
        - ALWAYS generate the complete, full-length script immediately
        
        START YOUR RESPONSE IMMEDIATELY WITH THE SCRIPT TITLE AND CONTENT. No preamble, no questions."""

        if key_points:
            query += f"\n- Key points to cover in detail: {', '.join(key_points)}"

        query += f"""
        
        Structure your {duration} script with:
        - Opening hook/introduction (1-2 minutes of actual content)
        - Multiple main content sections (each with substantial detail)
        - Detailed explanations, examples, and demonstrations
        - Engaging narrative flow with comprehensive coverage
        - Visual/action cues where appropriate
        - Realistic timing estimates that actually match content length
        - Strong conclusion/call-to-action
        - Technical notes for production
        
        Remember: Write the FULL content that a speaker would actually say to fill {duration}.
        Don't just outline - write the complete, detailed script content.
        
        Format the script professionally with clear scene directions and comprehensive speaker notes.
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create script thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )

    def create_podcast_script(
        self,
        episode_topic: str,
        episode_length: str = "30 minutes",
        hosts: List[str] = None,
        guests: List[str] = None,
        segments: List[str] = None,
        show_format: str = "interview",
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        Create a podcast episode script

        Args:
            episode_topic: Main topic of the episode
            episode_length: Target length of the episode
            hosts: List of host names
            guests: List of guest names (if any)
            segments: Planned segments for the show
            show_format: Format of the show (interview, solo, panel, etc.)
            timeout: Maximum time to wait for response

        Returns:
            Complete podcast script with timing and production notes
        """
        query = f"""
        Create a {show_format} podcast script for an episode about: {episode_topic}
        
        Episode Details:
        - Length: {episode_length}
        - Format: {show_format}
        """

        if hosts:
            query += f"\n- Hosts: {', '.join(hosts)}"
        if guests:
            query += f"\n- Guests: {', '.join(guests)}"
        if segments:
            query += f"\n- Planned segments: {', '.join(segments)}"

        query += """
        
        Please provide a complete podcast script including:
        - Pre-show preparation notes
        - Opening segment with intro music cues
        - Host introductions and guest introductions
        - Structured interview questions or talking points
        - Transition segments between topics
        - Sponsor/ad placement suggestions (if applicable)
        - Closing segment with wrap-up and next episode tease
        - Post-show notes
        - Timing estimates for each segment
        
        Include natural conversation flow and backup questions.
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create podcast thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )

    def write_social_media_script(
        self,
        content_type: str = "promotional",
        platform: str = "Instagram",
        duration: str = "60 seconds",
        message: str = None,
        brand_voice: str = "friendly",
        call_to_action: str = None,
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """
        Write a script for social media video content

        Args:
            content_type: Type of content (promotional, educational, entertainment)
            platform: Target social media platform
            duration: Target video length
            message: Key message to communicate
            brand_voice: Brand voice/tone
            call_to_action: Desired call to action
            timeout: Maximum time to wait for response

        Returns:
            Social media script optimized for the platform
        """
        query = f"""
        Write a {content_type} script for a {duration} {platform} video.
        
        Requirements:
        - Content Type: {content_type}
        - Platform: {platform}
        - Duration: {duration}
        - Brand Voice: {brand_voice}
        """

        if message:
            query += f"\n- Key Message: {message}"
        if call_to_action:
            query += f"\n- Call to Action: {call_to_action}"

        query += f"""
        
        Please create a script optimized for {platform} that includes:
        - Attention-grabbing opening (first 3 seconds)
        - Clear and concise messaging
        - Visual descriptions and shot suggestions
        - On-screen text recommendations
        - Music/sound effect cues
        - Pacing appropriate for the platform
        - Platform-specific engagement elements
        - Hashtag and caption suggestions
        
        Remember to optimize for {platform}'s algorithm and user behavior patterns.
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create social script thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )

    def develop_series_outline(
        self,
        series_concept: str,
        episode_count: int = 6,
        episode_length: str = "5-10 minutes",
        target_audience: str = "general",
        learning_objectives: List[str] = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        Develop an outline for a video/podcast series

        Args:
            series_concept: Overall concept and theme of the series
            episode_count: Number of episodes planned
            episode_length: Target length per episode
            target_audience: Target audience description
            learning_objectives: Key learning objectives (if educational)
            timeout: Maximum time to wait for response

        Returns:
            Detailed series outline with episode breakdowns
        """
        query = f"""
        Develop a comprehensive outline for a {episode_count}-episode series about: {series_concept}
        
        Series Specifications:
        - Episode Count: {episode_count}
        - Episode Length: {episode_length}
        - Target Audience: {target_audience}
        """

        if learning_objectives:
            query += f"\n- Learning Objectives: {', '.join(learning_objectives)}"

        query += """
        
        Please provide:
        1. Series Overview
           - Core concept and value proposition
           - Target audience analysis
           - Unique selling points
        
        2. Episode-by-Episode Breakdown
           - Episode titles and descriptions
           - Key topics and learning outcomes
           - Episode flow and structure
           - Estimated production requirements
        
        3. Series Arc and Progression
           - How episodes build upon each other
           - Narrative or educational progression
           - Recurring themes and elements
        
        4. Production Considerations
           - Consistent formatting elements
           - Resource requirements per episode
           - Potential challenges and solutions
        
        5. Engagement Strategy
           - Audience retention techniques
           - Cross-episode connection points
           - Call-to-actions and next steps
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create series thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )

    def adapt_content_for_format(
        self,
        original_content: str,
        current_format: str,
        target_format: str,
        target_duration: str = None,
        platform_considerations: str = None,
        timeout: int = 240,
    ) -> Dict[str, Any]:
        """
        Adapt existing content from one format to another

        Args:
            original_content: The original content to adapt
            current_format: Current format of the content
            target_format: Desired output format
            target_duration: Target duration for the new format
            platform_considerations: Specific platform requirements
            timeout: Maximum time to wait for response

        Returns:
            Adapted content in the new format
        """
        query = f"""
        Adapt the following content from {current_format} format to {target_format} format:
        
        Original Content:
        {original_content}
        
        Adaptation Requirements:
        - Current Format: {current_format}
        - Target Format: {target_format}
        """

        if target_duration:
            query += f"\n- Target Duration: {target_duration}"
        if platform_considerations:
            query += f"\n- Platform Considerations: {platform_considerations}"

        query += """
        
        Please provide:
        - Adapted content optimized for the new format
        - Key changes made and rationale
        - Format-specific optimization notes
        - Production or delivery recommendations
        - Any content that may have been modified or removed
        - Suggestions for enhancing the adaptation
        
        Ensure the core message and value remain intact while optimizing for the new format's requirements.
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create adaptation thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )
