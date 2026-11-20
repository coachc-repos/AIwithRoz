#!/usr/bin/env python3
"""
Container-specific BaseAgentClient - For Azure Container Apps deployment only

This is a container-specific version that handles the different environment
in Azure Container Apps without affecting the working local code.
"""

import time
import os
import logging
from typing import Optional, Dict, Any, List
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder
from abc import ABC, abstractmethod


class ContainerBaseAgentClient(ABC):
    """Container-specific base client for Azure AI Agent interactions"""

    def __init__(self, agent_id: str, agent_name: str = None):
        """
        Initialize the AI Agent connection for container environment

        Args:
            agent_id: The Azure AI Agent ID
            agent_name: Optional display name for the agent
        """
        # Container Apps environment - use endpoint approach
        try:
            self.project = AIProjectClient(
                credential=DefaultAzureCredential(),
                endpoint="https://linedrive-ai-foundry.services.ai.azure.com/api/projects/linedriveAgents",
            )
            print("✅ Connected to Azure AI Project via endpoint (container)")
        except Exception as e:
            print(f"❌ Failed to connect to Azure AI Project: {e}")
            raise e

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
        message: str,
        show_sources: bool = False,
        max_wait_seconds: int = 180,
    ) -> Dict[str, Any]:
        """Send a message to the agent and get response"""
        try:
            # Add message to thread
            self.project.agents.threads.messages.create(
                thread_id=thread_id, role="user", content=message
            )

            # Create run
            run = self.project.agents.threads.runs.create(
                thread_id=thread_id, assistant_id=self.agent_id
            )

            # Wait for completion
            start_time = time.time()
            while run.status in ["queued", "in_progress", "requires_action"]:
                if time.time() - start_time > max_wait_seconds:
                    return {
                        "success": False,
                        "error": f"Timeout after {max_wait_seconds} seconds",
                        "response": None,
                        "sources": [],
                    }

                time.sleep(2)
                run = self.project.agents.threads.runs.retrieve(
                    thread_id=thread_id, run_id=run.id
                )

            if run.status == "completed":
                # Get messages
                messages = self.project.agents.threads.messages.list(
                    thread_id=thread_id, order=ListSortOrder.DESC, limit=1
                )

                if messages.data:
                    message = messages.data[0]
                    response_text = ""
                    if message.content:
                        for content in message.content:
                            if hasattr(content, "text") and content.text:
                                response_text += content.text.value

                    sources = self._extract_sources(message) if show_sources else []
                    return {
                        "success": True,
                        "response": response_text,
                        "sources": sources,
                        "error": None,
                    }

            return {
                "success": False,
                "error": f"Run failed with status: {run.status}",
                "response": None,
                "sources": [],
            }

        except Exception as e:
            return {"success": False, "error": str(e), "response": None, "sources": []}

    def _extract_sources(self, message) -> List[Dict[str, str]]:
        """Extract citation sources from message"""
        sources = []
        try:
            if hasattr(message, "content"):
                for content in message.content:
                    if hasattr(content, "text") and hasattr(content.text, "annotations"):
                        for annotation in content.text.annotations:
                            if hasattr(annotation, "file_citation"):
                                sources.append(
                                    {
                                        "type": "file",
                                        "file_id": annotation.file_citation.file_id,
                                        "text": annotation.text,
                                    }
                                )
        except Exception as e:
            pass
        return sources

    def get_agent_info(self) -> Dict[str, Any]:
        """Get basic agent information"""
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "model": getattr(self.agent, "model", "unknown"),
            "endpoint": "https://linedrive-ai-foundry.services.ai.azure.com/api/projects/linedriveAgents",
        }

    @abstractmethod
    def get_specialized_info(self) -> Dict[str, Any]:
        """Get specialized information about this agent type"""
        pass

    def test_connection(self) -> bool:
        """Test the agent connection"""
        try:
            test_thread = self.create_thread()
            return test_thread is not None
        except:
            return False