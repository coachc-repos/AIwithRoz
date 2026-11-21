#!/usr/bin/env python3
"""
BaseAgentClient - Generic Azure AI Agent Client

This module provides a base client class for interacting with Azure AI Agents
in the linedrive project. All specific agents inherit from this base class.
"""

import time
from typing import Optional, Dict, Any, List
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder
from abc import ABC, abstractmethod


class BaseAgentClient(ABC):
    """Base client for Azure AI Agent interactions"""

    def __init__(self, agent_id: str, agent_name: str = None):
        """
        Initialize the AI Agent connection

        Args:
            agent_id: The Azure AI Agent ID
            agent_name: Optional display name for the agent
        """
        self.project = AIProjectClient(
            credential=DefaultAzureCredential(),
            endpoint="https://linedrive-ai-foundry.services.ai.azure.com/api/projects/linedriveAgents",
        )

        try:
            # Get the specific agent by ID
            self.agent = self.project.agents.get_agent(agent_id)
            self.agent_id = agent_id
            self.agent_name = agent_name or getattr(
                self.agent, "name", f"Agent-{agent_id}"
            )
        except Exception as e:
            raise Exception(f"Failed to initialize agent {agent_id}: {e}")

    def create_thread(self) -> Optional[Any]:
        """Create a new conversation thread"""
        try:
            thread = self.project.agents.threads.create()
            return thread
        except Exception as e:
            raise Exception(f"Failed to create thread: {e}")

    def send_message(
        self,
        thread_id: str,
        message_content: str,
        show_sources: bool = False,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        Send a message to the agent and get response

        Args:
            thread_id: The conversation thread ID
            message_content: The user's message
            show_sources: Whether to include source information in response
            timeout: Maximum time to wait for response (seconds)

        Returns:
            Dictionary with 'success', 'response', 'sources', and 'error' keys
        """
        try:
            # Send user message
            message = self.project.agents.messages.create(
                thread_id=thread_id, role="user", content=message_content
            )

            # Process the run with timeout
            run = self.project.agents.runs.create_and_process(
                thread_id=thread_id, agent_id=self.agent.id, timeout=timeout
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
                    sources = self._extract_sources(message) if show_sources else []

                    return {
                        "success": True,
                        "response": response_text,
                        "sources": sources,
                        "error": None,
                    }

            return {
                "success": False,
                "error": f"No response from {self.agent_name}",
                "response": None,
                "sources": [],
            }

        except Exception as e:
            return {"success": False, "error": str(e), "response": None, "sources": []}

    def _extract_sources(self, message) -> List[Dict[str, Any]]:
        """Extract source information from message (if available)"""
        sources = []
        try:
            # Extract sources if available in the message
            if hasattr(message, "attachments") and message.attachments:
                for attachment in message.attachments:
                    if hasattr(attachment, "file_citation"):
                        sources.append(
                            {
                                "type": "file_citation",
                                "content": getattr(
                                    attachment.file_citation, "quote", ""
                                ),
                                "file_id": getattr(
                                    attachment.file_citation, "file_id", ""
                                ),
                            }
                        )
        except Exception as e:
            # Sources extraction is optional, don't fail the entire response
            pass
        return sources

    def get_agent_info(self) -> Dict[str, str]:
        """Get basic information about the agent"""
        return {
            "name": self.agent_name,
            "id": self.agent_id,
            "endpoint": "https://linedrive-ai-foundry.services.ai.azure.com/api/projects/linedriveAgents",
        }

    @abstractmethod
    def get_specialized_info(self) -> Dict[str, Any]:
        """Get specialized information about this agent type - must be implemented by subclasses"""
        pass

    def health_check(self) -> Dict[str, Any]:
        """Perform a health check on the agent"""
        try:
            # Try to get agent details
            agent_info = self.get_agent_info()

            # Try to create a test thread
            test_thread = self.create_thread()

            return {
                "success": True,
                "agent_info": agent_info,
                "thread_creation": "OK",
                "status": "Healthy",
            }
        except Exception as e:
            return {"success": False, "error": str(e), "status": "Unhealthy"}
