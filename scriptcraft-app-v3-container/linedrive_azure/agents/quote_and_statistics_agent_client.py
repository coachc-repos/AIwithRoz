"""
Script Quotes and Statistics Agent Client for YouTube Script Enhancement

This agent finds recent, authoritative quotes and statistics about AI topics
to enhance script credibility and engagement. Uses the existing Azure AI Foundry
platform (same as all other linedrive agents).

Author: Christian Thilmany
Created: November 21, 2025
"""

from linedrive_azure.agents.base_agent_client import BaseAgentClient


class ScriptQuotesAndStatisticsAgentClient(BaseAgentClient):
    """Client for Script-Quotes-and-Statistics Agent on Azure AI Foundry"""

    def __init__(self):
        super().__init__(
            agent_name="Script-Quotes-and-Statistics-Agent",
            agent_id="asst_bEMK0Y6mdB6yRVnv0WwIZXwd"
        )

    def get_specialized_info(self) -> dict:
        """Get specialized information about this agent"""
        return {
            "purpose": "Find recent quotes and statistics about AI topics",
            "capabilities": [
                "Find 3 authoritative quotes from experts",
                "Find 3 compelling statistics from research",
                "Provide proper attribution and context",
                "Match audience level and tone",
                "Suggest strategic placement in scripts"
            ]
        }

    def generate_quotes_and_statistics(
        self,
        script_content: str,
        script_title: str,
        target_audience: str = "general audience",
        tone: str = "conversational and educational",
        timeout: int = 180
    ) -> dict:
        """
        Generate 3 quotes and 3 statistics for a script topic.

        Args:
            script_content: The completed script content (for context)
            script_title: The video title/topic
            target_audience: Target audience level
            tone: Desired tone
            timeout: Maximum time to wait (default: 180 seconds)

        Returns:
            dict with success status, raw_response, and parsed data
        """
        print(f"\n📊 Generating Quotes & Statistics for: {script_title}")
        print(f"   Audience: {target_audience}")
        print(f"   Tone: {tone}")

        # Extract topic from script title
        topic = script_title

        # Build the request message
        # Note: Using "Generate" instead of "Find" to avoid triggering search loops
        request_message = f"""
QUOTES AND STATISTICS GENERATION REQUEST

SCRIPT DETAILS:
- Title: {script_title}
- Target Audience: {target_audience}
- Tone: {tone}

COMPLETE SCRIPT TO ANALYZE:
{script_content}

TASK:
Generate 3 expert quotes and 3 compelling statistics directly about the SUBJECT
of THIS video: "{topic}". Ground them in the actual topics, claims, people,
companies, studies, and events discussed in the COMPLETE SCRIPT above — not in
generic AI or "AI content creation" material. Every quote and statistic MUST be
relevant to "{topic}"; discard anything that is not.

DELIVERABLE:
- 3 expert quotes with attribution and context
- 3 key statistics with sources and context
- Usage recommendations for strategic placement
- Overall strategy explanation
"""

        # Create thread and send message
        thread = self.create_thread()
        if not thread:
            return {
                "success": False,
                "error": "Failed to create thread",
                "raw_response": ""
            }

        # Send message using base agent client method
        result = self.send_message(
            thread_id=thread.id,
            message_content=request_message,
            show_sources=False,
            timeout=timeout
        )

        if result["success"]:
            response_text = result["response"]
            print(
                f"   ✅ Generated quotes and statistics ({len(response_text)} chars)")

            # Parse the response
            parsed = self._parse_response(response_text)

            return {
                "success": True,
                "raw_response": response_text,
                **parsed
            }
        else:
            print(f"   ❌ Error: {result.get('error', 'Unknown error')}")
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "raw_response": ""
            }

    def _parse_response(self, response_text: str) -> dict:
        """
        Parse the agent's response to extract structured data.

        Args:
            response_text: The full response from the agent

        Returns:
            dict with parsed quotes, statistics, and recommendations
        """
        result = {
            "quotes": [],
            "statistics": [],
            "usage_recommendations": {},
            "overall_strategy": ""
        }

        # Split response into sections
        sections = {
            "quotes": "",
            "statistics": "",
            "recommendations": ""
        }

        # Extract quotes section
        if "## 📊 EXPERT QUOTES" in response_text:
            quotes_start = response_text.find("## 📊 EXPERT QUOTES")
            quotes_end = response_text.find(
                "## 📈 KEY STATISTICS", quotes_start)
            if quotes_end > quotes_start:
                sections["quotes"] = response_text[quotes_start:quotes_end].strip()

        # Extract statistics section
        if "## 📈 KEY STATISTICS" in response_text:
            stats_start = response_text.find("## 📈 KEY STATISTICS")
            stats_end = response_text.find(
                "## 🎯 USAGE RECOMMENDATIONS", stats_start)
            if stats_end > stats_start:
                sections["statistics"] = response_text[stats_start:stats_end].strip()

        # Extract recommendations section
        if "## 🎯 USAGE RECOMMENDATIONS" in response_text:
            rec_start = response_text.find("## 🎯 USAGE RECOMMENDATIONS")
            sections["recommendations"] = response_text[rec_start:].strip()

        # Parse individual quotes (simple extraction - can be enhanced)
        quote_count = sections["quotes"].count("**Quote")
        result["quotes_count"] = quote_count

        # Parse individual statistics (simple extraction - can be enhanced)
        stat_count = sections["statistics"].count("**Statistic")
        result["statistics_count"] = stat_count

        # Extract overall strategy
        if "**Overall Strategy:**" in response_text:
            strategy_start = response_text.find("**Overall Strategy:**")
            strategy_text = response_text[strategy_start:].split("\n\n")[0]
            result["overall_strategy"] = strategy_text.replace(
                "**Overall Strategy:**", "").strip()

        # For now, return the sections as-is for display
        # Can be enhanced to parse into structured list of dicts
        result["quotes_section"] = sections["quotes"]
        result["statistics_section"] = sections["statistics"]
        result["recommendations_section"] = sections["recommendations"]

        return result


# Standalone test function
def main():
    """Test the Script Quotes and Statistics Agent"""
    import sys

    print("=" * 80)
    print("🧪 SCRIPT QUOTES AND STATISTICS AGENT - STANDALONE TEST")
    print("=" * 80)

    try:
        # Initialize the client
        print("\n1️⃣ Initializing Agent Client...")
        client = ScriptQuotesAndStatisticsAgentClient()

        # Get agent info
        print("\n2️⃣ Agent Information:")
        info = client.get_specialized_info()
        for key, value in info.items():
            if isinstance(value, list):
                print(f"   {key}:")
                for item in value:
                    print(f"      - {item}")
            else:
                print(f"   {key}: {value}")

        # Test with a sample topic
        print("\n3️⃣ Testing with Sample Script...")

        sample_script = """
        This is a test script about AI Content Creation Tools.
        It covers various aspects of using AI for content creation,
        including best practices, tools, and workflows.
        """

        result = client.generate_quotes_and_statistics(
            script_content=sample_script,
            script_title="AI Content Creation Tools Guide",
            target_audience="hobbyist",
            tone="conversational and educational",
            timeout=180
        )

        if result["success"]:
            print("\n✅ SUCCESS! Generated quotes and statistics")

            # Display full response
            print("\n" + "=" * 80)
            print("FULL AGENT RESPONSE:")
            print("=" * 80)
            print(result["raw_response"])
            print("=" * 80)

            return 0
        else:
            print(f"\n❌ FAILED: {result.get('error', 'Unknown error')}")
            return 1

    except Exception as e:
        print(f"\n❌ TEST FAILED WITH EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
