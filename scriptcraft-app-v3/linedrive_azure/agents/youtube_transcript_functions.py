#!/usr/bin/env python3
"""
YouTube Transcript Search Functions
Functions that the AI agent can use to search and retrieve transcript data
"""

import json
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging


class YouTubeTranscriptSearcher:
    def __init__(
        self, search_service_name: str = "linedrive-search", search_api_key: str = None
    ):
        """Initialize the search client"""
        self.search_service_name = search_service_name
        self.search_endpoint = f"https://{search_service_name}.search.windows.net"
        self.index_name = "youtube-transcripts-index"

        if not search_api_key:
            # Get API key from environment or Azure CLI
            import subprocess

            result = subprocess.run(
                [
                    "az",
                    "search",
                    "admin-key",
                    "show",
                    "--service-name",
                    search_service_name,
                    "--resource-group",
                    "rg-linedrive-search",
                    "--query",
                    "primaryKey",
                    "-o",
                    "tsv",
                ],
                capture_output=True,
                text=True,
            )
            self.search_api_key = result.stdout.strip()
        else:
            self.search_api_key = search_api_key

        self.headers = {
            "Content-Type": "application/json",
            "api-key": self.search_api_key,
        }

        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def search_youtube_transcripts(
        self,
        query: str,
        channel_filter: Optional[str] = None,
        host_filter: Optional[str] = None,
        date_range: Optional[Dict] = None,
        video_tags: Optional[List[str]] = None,
        search_type: str = "hybrid",
        max_results: int = 10,
    ) -> Dict[str, Any]:
        """
        Search through YouTube transcripts using Azure Cognitive Search

        Args:
            query: Search query - keywords, phrases, or questions
            channel_filter: Filter by specific channel name
            host_filter: Filter by specific host/speaker name
            date_range: Dict with 'start_date' and 'end_date' in ISO format
            video_tags: List of tags to filter by
            search_type: Type of search ("semantic", "keyword", "hybrid")
            max_results: Maximum number of results to return

        Returns:
            Dict containing search results with video details and transcript excerpts
        """

        # Build search parameters - simplified
        search_params = {
            "search": query,
            "top": max_results,
            "select": "video_id,video_title,channel_name,host,video_url,transcript_text,video_description,video_tags,video_duration,publish_date",
            "count": True,
        }

        # Build filter conditions
        filters = []

        if channel_filter:
            filters.append(f"channel_name eq '{channel_filter}'")

        if host_filter:
            filters.append(f"host eq '{host_filter}'")

        if date_range:
            if date_range.get("start_date"):
                filters.append(f"publish_date ge {date_range['start_date']}")
            if date_range.get("end_date"):
                filters.append(f"publish_date le {date_range['end_date']}")

        if video_tags:
            tag_filters = [f"video_tags/any(t: t eq '{tag}')" for tag in video_tags]
            if tag_filters:
                filters.append(f"({' or '.join(tag_filters)})")

        if filters:
            search_params["$filter"] = " and ".join(filters)

        # Configure search type - simplified for now
        if search_type == "keyword" or search_type == "simple":
            search_params["queryType"] = "simple"
        else:  # default to simple for reliability
            search_params["queryType"] = "simple"

        try:
            # Make the search request
            url = f"{self.search_endpoint}/indexes/{self.index_name}/docs/search"
            response = requests.post(
                f"{url}?api-version=2023-11-01",
                headers=self.headers,
                json=search_params,
            )
            response.raise_for_status()

            search_results = response.json()

            # Format results for the AI agent
            formatted_results = {
                "total_results": search_results.get("@odata.count", 0),
                "search_query": query,
                "search_type": search_type,
                "videos": [],
            }

            for result in search_results.get("value", []):
                video_info = {
                    "video_id": result.get("video_id"),
                    "video_title": result.get("video_title"),
                    "channel_name": result.get("channel_name"),
                    "host": result.get("host"),
                    "video_url": result.get("video_url"),
                    "video_duration": result.get("video_duration"),
                    "publish_date": result.get("publish_date"),
                    "language": result.get("language"),
                    "video_tags": result.get("video_tags", []),
                    "search_score": result.get("@search.score"),
                    "highlights": result.get("@search.highlights", {}),
                    "transcript_excerpt": self._truncate_text(
                        result.get("transcript_text", ""), 500
                    ),
                }

                # Add semantic answers if available
                if "answers" in search_results:
                    video_info["semantic_answers"] = search_results["answers"]

                formatted_results["videos"].append(video_info)

            self.logger.info(
                f"Found {len(formatted_results['videos'])} results for query: {query}"
            )
            return formatted_results

        except Exception as e:
            self.logger.error(f"Search failed: {str(e)}")
            return {"error": str(e), "total_results": 0, "videos": []}

    def get_transcript_details(
        self, video_id: str, include_segments: bool = False
    ) -> Dict[str, Any]:
        """
        Get detailed information about a specific video transcript

        Args:
            video_id: YouTube video ID
            include_segments: Whether to include timestamp segments

        Returns:
            Dict containing full transcript details
        """

        try:
            # Search for the specific video using filter
            search_params = {
                "search": "*",
                "filter": f"video_id eq '{video_id}'",
                "top": 1,
                "select": "*",
            }

            url = f"{self.search_endpoint}/indexes/{self.index_name}/docs/search"
            response = requests.post(
                f"{url}?api-version=2023-11-01",
                headers=self.headers,
                json=search_params,
            )
            response.raise_for_status()

            search_results = response.json()

            if not search_results.get("value"):
                return {
                    "error": f"Video with ID {video_id} not found",
                    "video_id": video_id,
                }

            result = search_results["value"][0]

            transcript_details = {
                "video_id": result.get("video_id"),
                "video_title": result.get("video_title"),
                "channel_name": result.get("channel_name"),
                "channel_url": result.get("channel_url"),
                "host": result.get("host"),
                "video_url": result.get("video_url"),
                "video_description": result.get("video_description"),
                "video_tags": result.get("video_tags", []),
                "video_duration": result.get("video_duration"),
                "publish_date": result.get("publish_date"),
                "created_at": result.get("created_at"),
                "language": result.get("language"),
                "transcript_source": result.get("transcript_source"),
                "full_transcript": result.get("transcript_text", ""),
            }

            # Add transcript segments if requested and available
            if include_segments and "transcript_segments" in result:
                transcript_details["transcript_segments"] = result[
                    "transcript_segments"
                ]

            return transcript_details

        except Exception as e:
            self.logger.error(f"Failed to get details for video {video_id}: {str(e)}")
            return {"error": str(e), "video_id": video_id}

    def _truncate_text(self, text: str, max_length: int) -> str:
        """Truncate text to specified length with ellipsis"""
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."


# Function wrappers for the AI agent
def search_youtube_transcripts(**kwargs) -> str:
    """Function wrapper for AI agent to search transcripts"""
    searcher = YouTubeTranscriptSearcher()
    results = searcher.search_youtube_transcripts(**kwargs)
    return json.dumps(results, indent=2)


def get_transcript_details(**kwargs) -> str:
    """Function wrapper for AI agent to get transcript details"""
    searcher = YouTubeTranscriptSearcher()
    details = searcher.get_transcript_details(**kwargs)
    return json.dumps(details, indent=2)


# Example usage for testing
def main():
    searcher = YouTubeTranscriptSearcher()

    # Test search
    results = searcher.search_youtube_transcripts(
        query="artificial intelligence", max_results=3, search_type="semantic"
    )

    print("Search Results:")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
