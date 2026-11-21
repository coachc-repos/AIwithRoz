#!/usr/bin/env python3
"""
Tournament Agent Client - Specialized client for tournament search and analysis

This agent handles tournament discovery, search, filtering, and recommendations
using the LineDrive tournament database.
"""

from typing import Dict, Any
from .base_agent_client import BaseAgentClient


class TournamentAgentClient(BaseAgentClient):
    """Specialized client for tournament search and analysis"""

    def __init__(self):
        """Initialize the Tournament Agent"""
        super().__init__(
            agent_id="asst_zBkNlAu4higVRIVKkNvqsrTC", agent_name="Tournament-Agent"
        )

    def get_specialized_info(self) -> Dict[str, Any]:
        """Get specialized information about the tournament agent"""
        return {
            "agent_type": "tournament_search",
            "capabilities": [
                "Tournament search and filtering",
                "Age group recommendations",
                "Location-based search",
                "Date range filtering",
                "Perfect Game tournament data",
                "Tournament details and analysis",
            ],
            "data_sources": [
                "Azure Data Lake tournament data",
                "Perfect Game tournament database",
                "LineDrive tournament index",
            ],
            "search_filters": {
                "age_groups": [
                    "8U",
                    "9U",
                    "10U",
                    "11U",
                    "12U",
                    "13U",
                    "14U",
                    "15U",
                    "16U",
                    "17U",
                    "18U",
                ],
                "sports": ["Baseball", "Softball"],
                "brackets": [
                    "Perfect Game",
                    "USSSA",
                    "Travel Ball",
                    "Recreation",
                    "All Star",
                ],
                "locations": "Cities, states, regions supported",
            },
        }

    def search_tournaments(
        self,
        age_group: str = None,
        location: str = None,
        date_range: str = None,
        sport: str = "Baseball",
        bracket: str = None,
        additional_criteria: str = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        Search for tournaments with specific criteria

        Args:
            age_group: Age group filter (e.g., "10U", "12U")
            location: Location filter (e.g., "Houston, TX")
            date_range: Date range filter (e.g., "This month", "Next weekend")
            sport: Sport type ("Baseball" or "Softball")
            bracket: Tournament bracket type
            additional_criteria: Additional search requirements
            timeout: Maximum time to wait for response

        Returns:
            Tournament search results
        """
        # Build search query
        query_parts = [
            "I need help finding baseball tournaments. Here are my search criteria:"
        ]

        if age_group:
            query_parts.append(f"- Age group: {age_group}")
        if location:
            query_parts.append(f"- Location: {location}")
        if date_range:
            query_parts.append(f"- Time range: {date_range}")
        if sport:
            query_parts.append(f"- Sport: {sport}")
        if bracket:
            query_parts.append(f"- Bracket: {bracket}")
        if additional_criteria:
            query_parts.append(f"- Additional requirements: {additional_criteria}")

        query_parts.append("")
        query_parts.append(
            "Please search for tournaments that match these criteria and provide detailed information including dates, locations, registration links, and any special requirements."
        )

        search_query = "\n".join(query_parts)

        # Create thread and send message
        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create search thread"}

        return self.send_message(
            thread_id=thread.id,
            message_content=search_query,
            show_sources=True,
            timeout=timeout,
        )

    def get_tournament_details(
        self, tournament_info: str, timeout: int = 180
    ) -> Dict[str, Any]:
        """
        Get detailed information about specific tournaments

        Args:
            tournament_info: Tournament name, ID, or description
            timeout: Maximum time to wait for response

        Returns:
            Detailed tournament information
        """
        query = f"""
        Please provide detailed information about this tournament: {tournament_info}
        
        I need details including:
        - Registration dates and deadlines
        - Location and venue information
        - Format and rules
        - Age groups and divisions
        - Entry fees and requirements
        - Contact information
        - Any special notes or requirements
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create details thread"}

        return self.send_message(
            thread_id=thread.id,
            message_content=query,
            show_sources=True,
            timeout=timeout,
        )

    def analyze_tournament_options(
        self, search_criteria: str, timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Analyze and compare multiple tournament options

        Args:
            search_criteria: Detailed search requirements
            timeout: Maximum time to wait for response

        Returns:
            Tournament analysis and recommendations
        """
        query = f"""
        {search_criteria}
        
        Please analyze the available tournament options and provide:
        1. A summary of tournaments that match the criteria
        2. Comparison of key factors (location, dates, fees, competition level)
        3. Recommendations for the best options based on the requirements
        4. Any potential conflicts or considerations
        5. Registration priority suggestions
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create analysis thread"}

        return self.send_message(
            thread_id=thread.id,
            message_content=query,
            show_sources=True,
            timeout=timeout,
        )
