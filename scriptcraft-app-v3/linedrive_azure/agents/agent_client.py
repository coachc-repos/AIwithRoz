#!/usr/bin/env python3
"""
LinedriveAgentClient - Core AI Agent functionality for tournament search

This module provides the core functionality for interacting with the Azure AI Agent
that has access to tournament data stored in Azure Data Lake.
"""

import time
from typing import Optional, Dict, Any, List
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder


class LinedriveAgentClient:
    """Core client for interacting with the Linedrive AI Agent"""

    def __init__(self):
        """Initialize the AI Agent connection"""
        self.project = AIProjectClient(
            credential=DefaultAzureCredential(),
            endpoint="https://linedrive-ai-foundry.services.ai.azure.com/api/projects/linedriveAgents",
        )

        # Get the agent (tournament planning agent)
        self.agent = self.project.agents.get_agent("asst_zBkNlAu4higVRIVKkNvqsrTC")
        self.agent_name = getattr(self.agent, "name", "LinedriveAgent")

    def create_thread(self) -> Optional[Any]:
        """Create a new conversation thread"""
        try:
            thread = self.project.agents.threads.create()
            return thread
        except Exception as e:
            raise Exception(f"Failed to create thread: {e}")

    def send_message(
        self, thread_id: str, message_content: str, show_sources: bool = False
    ) -> Dict[str, Any]:
        """
        Send a message to the agent and get response

        Args:
            thread_id: The conversation thread ID
            message_content: The user's message
            show_sources: Whether to include source information in response

        Returns:
            Dictionary with 'success', 'response', 'sources', and 'error' keys
        """
        try:
            # Removed automatic delay - only delay on actual rate limit errors
            # time.sleep(8)  # Removed conservative delay for better performance

            # Send user message
            message = self.project.agents.messages.create(
                thread_id=thread_id, role="user", content=message_content
            )

            # Process the run
            run = self.project.agents.runs.create_and_process(
                thread_id=thread_id, agent_id=self.agent.id
            )

            if run.status == "failed":
                return {
                    "success": False,
                    "error": f"Run failed: {run.last_error}",
                    "response": None,
                    "sources": [],
                }

            # Get all messages and return the latest agent response
            messages = self.project.agents.messages.list(
                thread_id=thread_id, order=ListSortOrder.ASCENDING
            )

            # Find the latest assistant message
            for message in reversed(list(messages)):
                if message.role == "assistant" and message.text_messages:
                    response_text = message.text_messages[-1].text.value
                    sources = []

                    # If show_sources is True, look for citation patterns in the response text
                    if show_sources:
                        # Import re module for pattern matching
                        import re

                        # Look for citation patterns like 【3:0†source】 or [Source 1:0] in the response
                        citation_patterns = [
                            r"【(\d+):(\d+)†source】",  # Pattern like 【3:0†source】
                            r"\[Source (\d+):(\d+)\]",  # Pattern like [Source 1:0]
                        ]

                        found_citations = set()  # Use set to avoid duplicates

                        for pattern in citation_patterns:
                            matches = re.findall(pattern, response_text)
                            for match in matches:
                                doc_num = int(match[0])
                                chunk_num = int(match[1])
                                citation_id = f"{doc_num}:{chunk_num}"
                                found_citations.add(citation_id)

                        # Create source objects for inferred citations
                        for citation_id in sorted(found_citations):
                            doc_num = citation_id.split(":")[0]
                            source_info = {
                                "id": citation_id,  # Use id field that frontend expects
                                "title": f"Perfect Game Tournament {doc_num}",
                                "url": f"https://linedrivestorage.blob.core.windows.net/tournament-data/tournament_{doc_num}.pdf",
                                "type": "inferred_citation",
                            }
                            sources.append(source_info)

                    # Also check for file citations from annotations
                    if show_sources and hasattr(
                        message.text_messages[-1], "annotations"
                    ):
                        annotations = message.text_messages[-1].annotations
                        if annotations:
                            for i, annotation in enumerate(annotations):
                                if hasattr(annotation, "file_citation"):
                                    file_id = annotation.file_citation.file_id
                                    citation_id = (
                                        f"{i+1}:0"  # Create consistent ID format
                                    )
                                    source_info = {
                                        "id": citation_id,
                                        "title": f"Source Document {i+1}",
                                        "file_id": file_id,
                                    }

                                    # Try to get file details
                                    try:
                                        file_details = self.project.agents.files.get(
                                            file_id
                                        )
                                        if hasattr(file_details, "filename"):
                                            source_info["title"] = file_details.filename
                                            filename = file_details.filename
                                        else:
                                            filename = f"document_{i+1}.pdf"

                                        # Generate direct blob URL
                                        storage_account = "linedrivestorage"
                                        container = "tournament-data"
                                        source_info["url"] = (
                                            f"https://{storage_account}.blob.core.windows.net/{container}/{filename}"
                                        )
                                    except Exception:
                                        # Fallback URL if file details can't be retrieved
                                        source_info["url"] = (
                                            f"https://linedrivestorage.blob.core.windows.net/tournament-data/document_{i+1}.pdf"
                                        )

                                    sources.append(source_info)

                    return {
                        "success": True,
                        "response": response_text,
                        "sources": sources,
                        "error": None,
                    }

            return {
                "success": False,
                "error": "No response from agent",
                "response": None,
                "sources": [],
            }

        except Exception as e:
            return {"success": False, "error": str(e), "response": None, "sources": []}

    def format_sources_for_display(self, sources: List[Dict[str, Any]]) -> str:
        """Format sources for display in UI"""
        if not sources:
            return ""

        formatted = "\n\n📁 Sources used:"
        for source in sources:
            formatted += (
                f"\n  [{source['citation_number']}] File ID: {source['file_id']}"
            )

            if "filename" in source:
                formatted += f" (Filename: {source['filename']})"

            if "purpose" in source:
                formatted += f" - Purpose: {source['purpose']}"

            # Generate Azure Portal URLs for tournament data
            if "filename" in source and "tournament" in source["filename"].lower():
                formatted += f"\n      🔗 Azure Portal: https://portal.azure.com/#browse/Microsoft.Storage%2FStorageAccounts"
                formatted += f"\n      📁 Storage Account: linedrivestorage"
                formatted += f"\n      📄 Container: tournament-data"
                formatted += f"\n      📋 File: {source['filename']}"
                formatted += f"\n      💡 Navigate to linedrivestorage > tournament-data > {source['filename']}"

        return formatted

    def get_agent_info(self) -> Dict[str, str]:
        """Get basic information about the agent"""
        return {
            "name": self.agent_name,
            "id": self.agent.id,
            "endpoint": "https://linedrive-ai-foundry.services.ai.azure.com/api/projects/linedriveAgents",
        }

    def chat(self, message: str, thread_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Simple chat interface compatible with AutoGen demo

        Args:
            message: The user's message
            thread_id: Optional thread ID (if None, creates new thread)

        Returns:
            Dictionary with 'response', 'sources', and 'thread_id' keys
        """
        try:
            # Create thread if not provided
            if thread_id is None:
                thread = self.create_thread()
                if thread is None:
                    return {
                        "response": "Error: Could not create conversation thread",
                        "sources": [],
                        "thread_id": None,
                    }
                thread_id = thread.id

            # Send message and get response
            result = self.send_message(thread_id, message, show_sources=True)

            if result["success"]:
                return {
                    "response": result["response"],
                    "sources": result["sources"],
                    "thread_id": thread_id,
                }
            else:
                return {
                    "response": f"Error: {result['error']}",
                    "sources": [],
                    "thread_id": thread_id,
                }

        except Exception as e:
            return {
                "response": f"Error in chat: {str(e)}",
                "sources": [],
                "thread_id": thread_id,
            }
