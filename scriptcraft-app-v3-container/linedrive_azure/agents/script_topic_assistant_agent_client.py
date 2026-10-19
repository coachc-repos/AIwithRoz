#!/usr/bin/env python3
"""
Script Topic Assistant Agent Client - Specialized client for topic enhancement and chapter planning

This agent handles topic analysis, enhancement, and chapter breakdown for script creation,
providing structured outlines and enhanced topics for comprehensive script development.
"""

from typing import Dict, Any, List
from .base_agent_client import BaseAgentClient


class ScriptTopicAssistantAgentClient(BaseAgentClient):
    """Specialized client for script topic assistance and chapter planning"""

    def __init__(self, agent_id: str = "asst_vqx6qOfUIEFnuKtb9XEyNtXK",
                 agent_name: str = "Script-Topic-Assistant-Agent"):
        """Initialize the Script Topic Assistant Agent.

        Accepts an optional agent_id/agent_name so archetype-specific
        subclasses (predictions / Top-N list) can point at their own Foundry
        agent while inheriting the topic-planning helpers unchanged.
        """
        super().__init__(agent_id=agent_id, agent_name=agent_name)

    def get_specialized_info(self) -> Dict[str, Any]:
        """Get specialized information about the script topic assistant agent"""
        return {
            "agent_type": "topic_planning",
            "capabilities": [
                "Topic analysis and enhancement",
                "Chapter breakdown and structuring",
                "Content organization and flow",
                "Script outline development",
                "Duration-based planning",
                "Audience-targeted content planning",
            ],
            "content_types": [
                "Video script topics",
                "Podcast episode topics",
                "Educational content topics",
                "Training material topics",
                "Series and multi-part content",
            ],
            "planning_features": [
                "Chapter-based organization",
                "Duration distribution",
                "Content depth analysis",
                "Audience engagement optimization",
                "Topic enhancement and expansion",
            ],
            "specializations": [
                "Educational content planning",
                "Technical topic breakdown",
                "Entertainment content structuring",
                "Corporate training organization",
                "Series development planning",
            ],
        }

    def generate_topic_and_chapters(
        self,
        topic: str,
        duration: str = "15 minutes",
        style: str = "educational",
        audience: str = "general",
        content_type: str = "video",
        chapter_count: int = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        Generate an enhanced topic with detailed chapter breakdown

        Args:
            topic: Original topic to enhance and structure
            duration: Target duration for the complete content
            style: Content style (educational, entertaining, promotional, etc.)
            audience: Target audience
            content_type: Type of content (video, podcast, etc.)
            chapter_count: Preferred number of chapters (optional)
            timeout: Maximum time to wait for response

        Returns:
            Enhanced topic with chapter breakdown and planning details
        """
        query = f"""
        TOPIC ANALYSIS AND ENHANCEMENT REQUEST:
        
        Original Topic: {topic}
        Content Type: {content_type}
        Duration: {duration}
        Style: {style}
        Target Audience: {audience}
        
        Please analyze this topic and provide:
        
        1. ENHANCED TOPIC:
           - Create a more compelling, detailed topic title that captures the full scope
           - Make it engaging and specific to the {audience} audience
           - Ensure it fits the {style} style approach
        
        2. CHAPTER BREAKDOWN:
           - Divide the content into logical chapters/sections
           - Each chapter should be substantial enough for detailed coverage
           - Aim for 3-5 chapters for optimal structure
           - Consider the {duration} total duration for balanced distribution
           
        3. CHAPTER DETAILS:
           For each chapter, provide:
           - Chapter title (engaging and descriptive)
           - Key points to cover
           - Specific examples or case studies to include
           - Estimated importance/depth level
        
        4. CONTENT FLOW:
           - Explain how chapters connect and build upon each other
           - Suggest smooth transitions between sections
           - Identify the narrative arc or learning progression
        
        5. AUDIENCE ENGAGEMENT:
           - Specific hooks and engagement strategies for {audience}
           - Examples that will resonate with this audience
           - Technical depth appropriate for their level
        
        FORMATTING REQUIREMENTS:
        Please format your response as follows:
        
        ENHANCED TOPIC: [Your enhanced topic title]
        
        CHAPTER 1: [Chapter title]
        - Key points: [list key points]
        - Examples: [specific examples to include]
        
        CHAPTER 2: [Chapter title]
        - Key points: [list key points]  
        - Examples: [specific examples to include]
        
        [Continue for all chapters]
        
        CONTENT FLOW: [Explain the progression and connections]
        
        ENGAGEMENT STRATEGY: [Specific approaches for {audience}]
        
        Make this comprehensive and actionable for creating a {duration} {content_type} 
        that will truly engage {audience} with {style} content about {topic}.
        """

        if chapter_count:
            query += f"\n\nPREFERRED CHAPTER COUNT: Please structure the content into approximately {chapter_count} chapters."

        thread = self.create_thread()
        if not thread:
            return {
                "success": False,
                "error": "Failed to create topic assistant thread",
            }

        result = self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )

        # Parse the result to extract structured information
        if result and result.get("success"):
            content = result.get("response", "")
            parsed_result = self._parse_topic_response(content)
            parsed_result["raw_response"] = content
            return parsed_result

        return result

    def _parse_topic_response(self, response: str) -> Dict[str, Any]:
        """Parse the topic assistant response into structured data"""
        try:
            lines = response.split("\n")
            result = {
                "success": True,
                "enhanced_topic": "",
                "chapters": [],
                "content_flow": "",
                "engagement_strategy": "",
                "chapter_details": [],
            }

            current_chapter = None
            current_section = None

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # Extract enhanced topic
                if line.startswith("ENHANCED TOPIC:"):
                    result["enhanced_topic"] = line.replace(
                        "ENHANCED TOPIC:", ""
                    ).strip()
                    current_section = "topic"

                # Extract chapters
                elif line.startswith("CHAPTER "):
                    if current_chapter:
                        result["chapter_details"].append(current_chapter)

                    chapter_title = (
                        line.split(":", 1)[1].strip() if ":" in line else line
                    )
                    chapter_number = line.split(":")[0].strip()
                    result["chapters"].append(chapter_title)

                    current_chapter = {
                        "number": chapter_number,
                        "title": chapter_title,
                        "key_points": [],
                        "examples": [],
                    }
                    current_section = "chapter"

                # Extract content flow
                elif line.startswith("CONTENT FLOW:"):
                    if current_chapter:
                        result["chapter_details"].append(current_chapter)
                        current_chapter = None
                    result["content_flow"] = line.replace("CONTENT FLOW:", "").strip()
                    current_section = "flow"

                # Extract engagement strategy
                elif line.startswith("ENGAGEMENT STRATEGY:"):
                    result["engagement_strategy"] = line.replace(
                        "ENGAGEMENT STRATEGY:", ""
                    ).strip()
                    current_section = "engagement"

                # Extract chapter details
                elif current_chapter and current_section == "chapter":
                    if line.startswith("- Key points:"):
                        current_chapter["key_points"].append(
                            line.replace("- Key points:", "").strip()
                        )
                    elif line.startswith("- Examples:"):
                        current_chapter["examples"].append(
                            line.replace("- Examples:", "").strip()
                        )
                    elif line.startswith("-"):
                        if (
                            "key_points" in line.lower()
                            or not current_chapter["key_points"]
                        ):
                            current_chapter["key_points"].append(line[1:].strip())
                        else:
                            current_chapter["examples"].append(line[1:].strip())

            # Add final chapter if exists
            if current_chapter:
                result["chapter_details"].append(current_chapter)

            return result

        except Exception as e:
            return {
                "success": True,
                "enhanced_topic": "Enhanced Topic Analysis",
                "chapters": ["Introduction", "Main Content", "Conclusion"],
                "content_flow": "Logical progression from introduction to conclusion",
                "engagement_strategy": "Audience-focused approach with relevant examples",
                "chapter_details": [],
                "parse_error": str(e),
            }

    def analyze_topic_depth(
        self,
        topic: str,
        audience: str = "general",
        content_goals: List[str] = None,
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """
        Analyze topic depth and complexity for content planning

        Args:
            topic: Topic to analyze
            audience: Target audience for depth assessment
            content_goals: Specific goals for the content
            timeout: Maximum time to wait for response

        Returns:
            Topic depth analysis with recommendations
        """
        query = f"""
        TOPIC DEPTH ANALYSIS REQUEST:
        
        Topic: {topic}
        Audience: {audience}
        """

        if content_goals:
            query += f"\nContent Goals: {', '.join(content_goals)}"

        query += f"""
        
        Please analyze this topic and provide:
        
        1. COMPLEXITY LEVEL: Rate the topic complexity for {audience} (Beginner/Intermediate/Advanced)
        
        2. KEY CONCEPTS: List the main concepts that need to be covered
        
        3. PREREQUISITE KNOWLEDGE: What should the audience already know?
        
        4. DEPTH RECOMMENDATIONS: How deep should we go for {audience}?
        
        5. POTENTIAL CHALLENGES: What might be difficult to explain or understand?
        
        6. ENGAGEMENT OPPORTUNITIES: Where can we make this more interactive or engaging?
        
        Provide specific, actionable recommendations for content creators.
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create analysis thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )
