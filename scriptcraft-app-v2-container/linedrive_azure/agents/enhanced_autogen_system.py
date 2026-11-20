#!/usr/bin/env python3
"""
Enhanced AutoGen Agent Orchestrator - Multi-Agent System for Script Creation and Review

This module provides an enhanced AutoGen framework that orchestrates multiple specialized
agents for script creation and review workflows, including the new Script Writer and
Script Review agents alongside existing tournament and AI tips agents.
"""

import asyncio
import logging
import os
import re
import sys
import time
import concurrent.futures
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Sequence, Union

# Load environment variables from .env file in agents directory
try:
    from dotenv import load_dotenv

    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"🔧 Loaded environment variables from {env_file}")
except ImportError:
    pass  # dotenv not available, continue without it
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_core.models import (
    ChatCompletionClient,
    CreateResult,
    LLMMessage,
    UserMessage,
    AssistantMessage,
    RequestUsage,
    ModelCapabilities,
)
from autogen_agentchat.messages import TextMessage
from autogen_core import CancellationToken

# Import our specialized agent clients
from .tournament_agent_client import TournamentAgentClient
from .ai_tips_agent_client import AITipsAgentClient
from .script_writer_agent_client import ScriptWriterAgentClient
from .script_review_agent_client import ScriptReviewAgentClient
from .script_topic_assistant_agent_client import ScriptTopicAssistantAgentClient
from .hook_and_summary_agent_client import HookAndSummaryAgentClient
# Archetype-specific topic-assistant + writer pairs (predictions / Top-N list).
# The teaching listicle keeps using the two base clients above.
from .script_topic_assistant_predictions_agent_client import (
    ScriptTopicAssistantPredictionsAgentClient,
)
from .script_writer_predictions_agent_client import (
    ScriptWriterPredictionsAgentClient,
)
from .script_topic_assistant_list_agent_client import (
    ScriptTopicAssistantListAgentClient,
)
from .script_writer_list_agent_client import ScriptWriterListAgentClient

# Canonical archetype keys used end-to-end (UI → /create → workflow).
SCRIPT_FORMAT_TEACHING = "teaching"
SCRIPT_FORMAT_PREDICTIONS = "predictions"
SCRIPT_FORMAT_LIST = "list"
# "pro" = single-pass Claude Opus 5.5 (max effort) writer — writes the whole
# script in one call and infers the archetype itself (list / predictions /
# teaching / teardown). Does NOT use the Foundry topic-assistant + writer pair.
SCRIPT_FORMAT_PRO = "pro"
VALID_SCRIPT_FORMATS = (
    SCRIPT_FORMAT_TEACHING,
    SCRIPT_FORMAT_PREDICTIONS,
    SCRIPT_FORMAT_LIST,
    SCRIPT_FORMAT_PRO,
)


# Known acronyms preserved as-is when de-shouting (everything else that is
# ALL-CAPS gets title-cased). Matched case-insensitively per letter run.
_DESHOUT_KEEP = {
    "AI", "API", "APIS", "ML", "LLM", "LLMS", "GPT", "UI", "UX", "SEO", "CSS",
    "HTML", "SQL", "AWS", "GCP", "CPU", "GPU", "SDK", "CLI", "URL", "URI",
    "HTTP", "HTTPS", "JSON", "XML", "IOT", "AR", "VR", "NLP", "RAG", "ROI",
    "KPI", "CRM", "ERP", "SAAS", "PAAS", "IAAS", "IT", "PC", "OS", "DB", "ID",
    "FAQ", "PDF", "CSV", "RAM", "SSD", "USB", "2D", "3D", "4K", "HD", "USA",
    "UK", "EU", "CEO", "CTO", "CFO", "B2B", "B2C", "QA", "ETL", "VPN", "DNS",
}


def _deshout_text(text: str) -> str:
    """Tone down ALL-CAPS 'shouting' so Azure's content filter doesn't reject
    the topic plan / chapter titles as aggressive.

    A whitespace token that is entirely upper-case (no lowercase letter) has
    each of its letter runs title-cased, except runs that are a known acronym
    (kept as-is). Tokens that already contain a lowercase letter are untouched.
    Examples:
        "BUILDING AI APPS WITH PYTHON" -> "Building AI Apps With Python"
        "THE FUTURE OF WORK"           -> "The Future Of Work"
        "AI-POWERED WORKFLOWS"         -> "AI-Powered Workflows"
    """
    if not text:
        return text

    def _fix_run(r: "re.Match") -> str:
        run = r.group(0)
        return run if run.upper() in _DESHOUT_KEEP else run.capitalize()

    def _fix_token(m: "re.Match") -> str:
        w = m.group(0)
        if any(c.islower() for c in w):
            return w  # already mixed/normal case -> not shouting
        return re.sub(r"[A-Za-z]+", _fix_run, w)

    return re.sub(r"\S+", _fix_token, text)


# ---------------------------------------------------------------------------
# Claude (Anthropic) fallback for chapter writing.
#
# The primary Script Writer runs on an Azure AI Foundry deployment whose model
# is configured in the Foundry PORTAL (v2 = Claude Opus 5.5), not in this code.
# A Foundry call can still fail (HTTP 429 "rate_limit_exceeded" under load, a
# content-filter refusal, a timeout) and abort the whole script even though the
# Topic Assistant already produced good chapters. When a chapter write fails for
# ANY reason, we transparently re-write that one chapter here with Claude
# (_CLAUDE_FALLBACK_MODEL) using the exact same request (which carries the full
# format spec). For non-teaching archetypes this same path is the PRIMARY writer.
#
# Returns the chapter text, or None if Claude is unavailable or also fails.
# Requires ANTHROPIC_API_KEY in the environment.
# ---------------------------------------------------------------------------
# Claude model used to write chapters (primary writer for non-teaching
# archetypes; fallback writer for the teaching archetype). Opus 5.5 at MAX
# reasoning effort for the highest-quality draft (user request).
_CLAUDE_FALLBACK_MODEL = "claude-opus-5-5"
# "high", NOT "max": effort="max" on opus-5-5 overthinks and can burn the whole
# token budget on hidden reasoning, returning an empty chapter. "high" reasons
# hard and still writes. (Same finding as the Pro single-pass writer.)
_CLAUDE_WRITER_EFFORT = "high"  # low | medium | high | xhigh | max


def _claude_chapter_fallback(script_request: str) -> Optional[str]:
    """Write a single chapter with Claude when the primary writer fails."""
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        print("   ⚠️ Claude chapter fallback unavailable: ANTHROPIC_API_KEY not set")
        return None
    try:
        import anthropic
    except ImportError:
        print("   ⚠️ Claude chapter fallback unavailable: anthropic SDK not installed")
        return None
    system = (
        "You are a professional video Script Writer. You write a SINGLE chapter "
        "of a longer, continuous video script. Follow the requested FORMAT and "
        "FORMATTING RULES in the user's message EXACTLY — including the heading, "
        "the single '**Host:**' label, and any Visual Cue / Summary sections. "
        "Output ONLY the chapter content in that format: no preamble, no "
        "explanation, no commentary about your process, and no markdown code "
        "fences around the whole thing."
    )
    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=300.0, max_retries=2)
        base_kwargs = dict(
            model=_CLAUDE_FALLBACK_MODEL,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": script_request}],
        )
        # MAX reasoning effort + adaptive thinking for the best draft (user
        # request). effort/output_config and adaptive thinking are GA on recent
        # Opus; if this model alias doesn't accept them, retry once plain so a
        # chapter still comes back rather than erroring the whole run.
        try:
            resp = client.messages.create(
                **base_kwargs,
                output_config={"effort": _CLAUDE_WRITER_EFFORT},
                thinking={"type": "adaptive"},
            )
        except (anthropic.BadRequestError, TypeError) as _be:
            print(f"   ⚠️ Claude writer: effort/thinking rejected "
                  f"({str(_be)[:80]}); retrying without them")
            resp = client.messages.create(**base_kwargs)
        parts = [
            b.text for b in resp.content
            if getattr(b, "type", None) == "text"
        ]
        text = "".join(parts).strip()
        # Peel a markdown fence if the model wrapped the whole chapter in one.
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()
        return text or None
    except Exception as e:
        print(f"   ❌ Claude chapter fallback failed: {e}")
        return None


class LineDriveAgentModelClient(ChatCompletionClient):
    """Custom AutoGen model client for LineDrive agents"""

    def __init__(self, agent_client, agent_name: str, verbose: bool = False):
        """
        Initialize with a specific agent client

        Args:
            agent_client: One of the specialized agent clients
            agent_name: Name of the agent for identification
            verbose: If True, show detailed agent logging
        """
        self.agent_client = agent_client
        self.agent_name = agent_name
        self.verbose = verbose
        self.thread_id = None
        self._total_usage = RequestUsage(prompt_tokens=0, completion_tokens=0)

    def _ensure_thread(self):
        """Ensure we have an active thread"""
        if self.thread_id is None:
            thread = self.agent_client.create_thread()
            if thread:
                self.thread_id = thread.id
            else:
                raise Exception(
                    f"Failed to create thread for {self.agent_name}")

    @property
    def capabilities(self) -> ModelCapabilities:
        """Return model capabilities"""
        return ModelCapabilities(
            completion=True,
            chat_completion=True,
            function_calling=False,
            vision=False,
            json_output=False,
        )

    @property
    def model_info(self) -> Dict[str, Any]:
        """Return model information as dict"""
        return {
            "model_name": f"linedrive-{self.agent_name.lower()}",
            "model_family": "azure-ai-projects",
            "context_length": 8192,
            "max_tokens": 2048,
            "vision": False,
            "function_calling": False,
            "json_output": False,
        }

    def count_tokens(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[Any] = []
    ) -> int:
        """Count tokens in messages"""
        total = 0
        for msg in messages:
            if hasattr(msg, "content"):
                total += len(str(msg.content).split())
            else:
                total += len(str(msg).split())
        return total

    def remaining_tokens(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[Any] = []
    ) -> int:
        """Return remaining tokens"""
        used = self.count_tokens(messages, tools=tools)
        return max(0, self.model_info["context_length"] - used)

    def actual_usage(self) -> RequestUsage:
        """Return actual usage"""
        return self._total_usage

    def total_usage(self) -> RequestUsage:
        """Return total usage"""
        return self._total_usage

    async def create(
        self,
        messages: Sequence[LLMMessage],
        *,
        cancellation_token: CancellationToken = CancellationToken(),
        **kwargs,
    ) -> CreateResult:
        """Create response from the agent"""
        try:
            if self.verbose:
                print(
                    f"🔧 AUTOGEN AGENT CALL TRACE: {self.agent_name} "
                    f"received message"
                )
            self._ensure_thread()

            # Get the latest message content
            latest_message = messages[-1] if messages else None
            if not latest_message:
                raise ValueError("No messages provided")

            content = (
                str(latest_message.content)
                if hasattr(latest_message, "content")
                else str(latest_message)
            )

            if self.verbose:
                print(f"   💬 Message length: {len(content)} characters")
                print(f"   🧵 Thread ID: {self.thread_id}")
                print(
                    f"   🤖 Agent Client Type: " f"{type(self.agent_client).__name__}"
                )

            # Send message to agent
            if self.verbose:
                print(f"   📡 Calling {self.agent_name} agent client...")
            response = self.agent_client.send_message(
                thread_id=self.thread_id,
                message_content=content,
                show_sources=True,
                timeout=300,
            )

            if response["success"]:
                response_content = response["response"]
                if self.verbose:
                    print(
                        f"   ✅ {self.agent_name} responded with "
                        f"{len(response_content)} characters"
                    )

                # Update usage estimates
                prompt_tokens = self.count_tokens(messages)
                completion_tokens = len(response_content.split())

                self._total_usage = RequestUsage(
                    prompt_tokens=self._total_usage.prompt_tokens + prompt_tokens,
                    completion_tokens=self._total_usage.completion_tokens
                    + completion_tokens,
                )

                return CreateResult(
                    content=response_content,
                    usage=RequestUsage(
                        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
                    ),
                    finish_reason="stop",
                    cached=False,
                )
            else:
                error_msg = (
                    f"{self.agent_name} error: "
                    f"{response.get('error', 'Unknown error')}"
                )
                if self.verbose:
                    print(
                        f"   ❌ {self.agent_name} error: "
                        f"{response.get('error', 'Unknown error')}"
                    )
                return CreateResult(
                    content=error_msg,
                    usage=RequestUsage(prompt_tokens=0, completion_tokens=0),
                    finish_reason="error",
                    cached=False,
                )

        except Exception as e:
            error_msg = f"{self.agent_name} processing error: {str(e)}"
            print(f"   💥 {self.agent_name} exception: {str(e)}")
            return CreateResult(
                content=error_msg,
                usage=RequestUsage(prompt_tokens=0, completion_tokens=0),
                finish_reason="error",
                cached=False,
            )

    async def create_stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        cancellation_token: CancellationToken = CancellationToken(),
        **kwargs,
    ):
        """Create a streaming response (simplified implementation)"""
        # For now, just return the regular create response as a single item
        result = await self.create(
            messages, cancellation_token=cancellation_token, **kwargs
        )
        yield result

    async def close(self) -> None:
        """Close the model client connection"""
        # Clean up resources if needed
        self.thread_id = None


class EnhancedAutoGenSystem:
    """Enhanced AutoGen system with multiple specialized agents"""

    def __init__(self, verbose: bool = False, script_format: str = SCRIPT_FORMAT_TEACHING):
        """Initialize the enhanced multi-agent system

        Args:
            verbose: If True, show detailed logging. If False, minimal output.
            script_format: Which video archetype to generate. Selects the
                topic-assistant + script-writer Foundry agent pair:
                  - "teaching"    → Script-Topic-Assistant-Agent + Script-Writer-Agent
                                     (the original "5 things" tutorial listicle)
                  - "predictions" → ...-Predictions-Agent pair (bold/visionary)
                  - "list"        → ...-List-Agent pair (Top-N ranked countdown)
                Unknown values fall back to "teaching".
        """
        self.verbose = verbose
        self.script_format = (
            script_format if script_format in VALID_SCRIPT_FORMATS
            else SCRIPT_FORMAT_TEACHING
        )
        self._configure_logging()

        if self.script_format == SCRIPT_FORMAT_PRO:
            # Pro mode writes in one Claude pass and uses NO agents — keep the
            # multi-agent initialization chatter out of the progress log.
            print("🅿️ Pro mode — preparing the single-pass Claude Opus 5.5 writer")
        elif self.verbose:
            print("🚀 Initializing Enhanced AutoGen Multi-Agent System...")
            print("🔧 AUTOGEN SYSTEM TRACE: Starting initialization")
        else:
            print("🚀 Initializing AutoGen system...")

        # Initialize agent clients
        if self.verbose:
            print("📡 AUTOGEN SYSTEM TRACE: Initializing agents...")

        self.tournament_client = TournamentAgentClient()
        if self.verbose:
            print("   ✅ TournamentAgentClient initialized")

        self.ai_tips_client = AITipsAgentClient()
        if self.verbose:
            print("   ✅ AITipsAgentClient initialized")

        # Select the topic-assistant + writer pair for the chosen archetype.
        # Every other agent (review, hook-and-summary, …) is archetype-neutral
        # and shared. The two model-client wrappers built below (lines ~413/425)
        # wrap whichever pair we pick here, so the group-chat paths stay
        # consistent with the sequential workflow.
        if self.script_format == SCRIPT_FORMAT_PREDICTIONS:
            self.script_writer_client = ScriptWriterPredictionsAgentClient()
            self.script_topic_assistant_client = (
                ScriptTopicAssistantPredictionsAgentClient()
            )
        elif self.script_format == SCRIPT_FORMAT_LIST:
            self.script_writer_client = ScriptWriterListAgentClient()
            self.script_topic_assistant_client = (
                ScriptTopicAssistantListAgentClient()
            )
        else:
            self.script_writer_client = ScriptWriterAgentClient()
            self.script_topic_assistant_client = ScriptTopicAssistantAgentClient()

        if self.verbose:
            print(f"   🎬 Script format: {self.script_format}")
            print(f"   ✅ Writer agent: {self.script_writer_client.v2_agent_name}")
            print(
                "   ✅ Topic assistant: "
                f"{self.script_topic_assistant_client.v2_agent_name}"
            )

        self.script_review_client = ScriptReviewAgentClient()
        if self.verbose:
            print("   ✅ ScriptReviewAgentClient initialized")

        # NEW: Hook-and-Summary Agent Client
        self.hook_and_summary_client = HookAndSummaryAgentClient()
        if self.verbose:
            print("   ✅ HookAndSummaryAgentClient initialized")

        # Create model clients
        if self.verbose:
            print("🤖 AUTOGEN SYSTEM TRACE: Creating model clients...")

        self.tournament_model = LineDriveAgentModelClient(
            self.tournament_client, "TournamentAgent", verbose=self.verbose
        )
        if self.verbose:
            print("   ✅ TournamentAgent model client created")

        self.ai_tips_model = LineDriveAgentModelClient(
            self.ai_tips_client, "AITipsAgent", verbose=self.verbose
        )
        if self.verbose:
            print("   ✅ AITipsAgent model client created")

        self.script_writer_model = LineDriveAgentModelClient(
            self.script_writer_client, "ScriptWriterAgent", verbose=self.verbose
        )
        if self.verbose:
            print("   ✅ ScriptWriterAgent model client created")

        self.script_review_model = LineDriveAgentModelClient(
            self.script_review_client, "ScriptReviewAgent", verbose=self.verbose
        )
        if self.verbose:
            print("   ✅ ScriptReviewAgent model client created")

        self.script_topic_assistant_model = LineDriveAgentModelClient(
            self.script_topic_assistant_client,
            "ScriptTopicAssistantAgent",
            verbose=self.verbose,
        )
        if self.verbose:
            print("   ✅ ScriptTopicAssistantAgent model client created")

        if self.script_format == SCRIPT_FORMAT_PRO:
            print("🅿️ Pro writer ready")
        elif self.verbose:
            print("🎯 AUTOGEN SYSTEM TRACE: System fully initialized!")
        else:
            print("✅ AutoGen system initialized")

    def _configure_logging(self):
        """Configure Azure SDK logging based on verbose setting"""
        if self.verbose:
            # Verbose: Show detailed Azure SDK logs
            logging.basicConfig(level=logging.INFO)
            azure_logger = logging.getLogger("azure")
            azure_logger.setLevel(logging.INFO)
        else:
            # Minimal: Suppress Azure SDK HTTP logs
            logging.basicConfig(level=logging.WARNING)

            # Specifically suppress the noisy Azure loggers
            azure_loggers = [
                "azure.core.pipeline.policies.http_logging_policy",
                "azure.identity._credentials.environment",
                "azure.identity._credentials.managed_identity",
                "azure.identity._credentials.chained",
                "azure.identity",
                "azure.core",
                "azure",
            ]

            for logger_name in azure_loggers:
                logger = logging.getLogger(logger_name)
                logger.setLevel(logging.ERROR)

    async def run_script_collaboration_workflow(
        self, workflow_prompt: str
    ) -> Dict[str, Any]:
        """Run a collaborative script creation workflow using AutoGen orchestration"""
        try:
            print("🎬 Starting AutoGen Script Collaboration Workflow...")

            # Create specialized AutoGen agents for script collaboration
            script_director = AssistantAgent(
                name="ScriptDirector",
                model_client=self.script_writer_model,
                description="Director that orchestrates script creation workflow",
                system_message="""You are a Script Director. Your role is to:
                1. Analyze script requirements and break them down
                2. Create a clear plan for the Script Writer
                3. Complete your analysis in ONE response
                4. End with "DIRECTOR PLAN COMPLETE"
                
                Be concise, clear, and finish your task in one turn.""",
            )

            script_writer = AssistantAgent(
                name="ScriptWriter",
                model_client=self.script_writer_model,
                description="Creates original scripts based on requirements",
                system_message="""You are a professional Script Writer. Your role is to:
                1. Create original, engaging scripts based on specifications
                2. Follow industry best practices for script formatting
                3. Complete your script in ONE response
                4. End with "SCRIPT COMPLETE" or "REVISED SCRIPT COMPLETE"
                
                Be efficient and complete your task in one turn.""",
            )

            script_reviewer = AssistantAgent(
                name="ScriptReviewer",
                model_client=self.script_review_model,
                description="Reviews scripts and provides comprehensive feedback",
                system_message="""You are a Script Reviewer and Content Expert. Your role is to:
                1. Analyze scripts for quality, structure, and effectiveness
                2. Provide constructive, actionable feedback and suggestions
                3. Complete your review in ONE response
                4. End with "REVIEW COMPLETE"
                
                Be thorough but concise, and complete your task in one turn.""",
            )

            # Create the collaborative team with limited turns to prevent infinite loops
            team = RoundRobinGroupChat(
                [script_director, script_writer, script_reviewer], max_turns=4
            )

            # Enhanced workflow prompt with clear instructions and termination
            enhanced_prompt = f"""
            COLLABORATIVE SCRIPT CREATION WORKFLOW:
            
            Request: {workflow_prompt}
            
            Please execute this 4-step workflow efficiently:
            
            1. ScriptDirector: Analyze the requirements and create a detailed plan (MAX 1 turn)
            2. ScriptWriter: Create the initial script based on the director's plan (MAX 1 turn)
            3. ScriptReviewer: Review the script and provide comprehensive feedback (MAX 1 turn)
            4. ScriptWriter: Create a revised version incorporating the feedback (MAX 1 turn)
            
            IMPORTANT: Each agent should:
            - Clearly identify their role and deliverable
            - Complete their task in ONE turn
            - Use "WORKFLOW COMPLETE" when done
            - NOT continue the conversation after completion
            
            The workflow ends after the revised script is created.
            """

            # Run the collaborative workflow with timeout and termination detection
            result_stream = team.run_stream(
                task=TextMessage(content=enhanced_prompt, source="user")
            )

            # Collect all messages from the workflow with timeout protection
            messages = []
            message_count = 0
            max_messages = 10  # Prevent runaway conversations

            try:
                async for message in result_stream:
                    messages.append(message)
                    message_count += 1

                    source = getattr(message, "source", "Unknown")
                    content = getattr(message, "content", "")
                    print(f"🤖 {source}: Processing... (Message {message_count})")

                    # Check for completion signals
                    completion_signals = [
                        "WORKFLOW COMPLETE",
                        "REVISED SCRIPT COMPLETE",
                        "REVIEW COMPLETE",
                        "DIRECTOR PLAN COMPLETE",
                    ]

                    if any(signal in content for signal in completion_signals):
                        print(f"✅ Completion signal detected: Breaking workflow")
                        break

                    # Safety limit to prevent infinite loops
                    if message_count >= max_messages:
                        print(
                            f"⚠️ Maximum message limit ({max_messages}) reached. Terminating workflow."
                        )
                        break

            except asyncio.TimeoutError:
                print("⏰ Workflow timeout - terminating gracefully")
            except Exception as e:
                print(f"⚠️ Workflow stream error: {e}")

            print(f"📊 Processed {message_count} messages")

            # Extract and organize the workflow results
            workflow_results = self.extract_script_workflow_results(messages)

            print("✅ AutoGen Script Collaboration Workflow Complete!")
            return workflow_results

        except Exception as e:
            print(f"❌ AutoGen workflow error: {e}")
            return {
                "success": False,
                "error": f"AutoGen workflow failed: {str(e)}",
                "original_script": "",
                "review_feedback": "",
                "revised_script": "",
            }

    def extract_script_workflow_results(self, messages) -> Dict[str, Any]:
        """Extract script creation workflow results from AutoGen messages"""
        try:
            director_plan = ""
            original_script = ""
            review_feedback = ""
            revised_script = ""

            # Process messages in order to extract workflow components
            for message in messages:
                if hasattr(message, "source") and hasattr(message, "content"):
                    content = str(message.content)
                    source = getattr(message, "source", "Unknown")

                    if source == "ScriptDirector":
                        director_plan = content
                    elif source == "ScriptWriter":
                        if not original_script:
                            original_script = content  # First script writer response
                        else:
                            revised_script = (
                                # Second script writer response (revision)
                                content
                            )
                    elif source == "ScriptReviewer":
                        review_feedback = content

            # Return organized results
            return {
                "success": True,
                "director_plan": director_plan or "Planning phase...",
                "original_script": original_script or "Script creation in progress...",
                "review_feedback": review_feedback or "Review in progress...",
                "revised_script": revised_script or "Revision in progress...",
                "workflow_complete": bool(original_script and review_feedback),
                "all_messages": [
                    str(msg.content) for msg in messages if hasattr(msg, "content")
                ],
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to extract workflow results: {str(e)}",
                "original_script": "",
                "review_feedback": "",
                "revised_script": "",
            }

    def create_tournament_workflow_agents(self) -> List[AssistantAgent]:
        """Create agents for tournament workflow"""
        return [
            AssistantAgent(
                name="TournamentFinder",
                model_client=self.tournament_model,
                system_message="""
                You are a Tournament Finder specializing in baseball and softball tournament search.
                
                Your expertise includes:
                - Searching tournament databases for specific criteria
                - Filtering by age groups, locations, dates, and tournament types
                - Providing detailed tournament information including registration links
                - Analyzing tournament schedules and formats
                
                When given search criteria, provide comprehensive tournament results with all relevant details.
                Focus on accuracy and completeness of tournament information.
                """,
            ),
            AssistantAgent(
                name="AITipsGenerator",
                model_client=self.ai_tips_model,
                system_message="""
                You are an AI Tips Generator specialized in social media content creation.
                
                Your expertise includes:
                - Creating engaging social media content
                - Generating training tips and advice
                - Developing tournament promotion materials
                - Creating content calendars and engagement strategies
                
                Work with tournament information to create compelling social media content that promotes
                tournaments and engages baseball/softball communities.
                """,
            ),
        ]

    def create_script_workflow_agents(self) -> List[AssistantAgent]:
        """Create agents for script creation and review workflow"""
        return [
            AssistantAgent(
                name="ScriptWriter",
                model_client=self.script_writer_model,
                system_message="""
                You are a Script Writer specializing in creating various types of content scripts.
                
                Your expertise includes:
                - Writing video scripts for different durations and styles
                - Creating podcast episode scripts
                - Developing social media content scripts
                - Adapting content between different formats
                - Creating series outlines and episode structures
                
                Focus on creating engaging, well-structured content that meets specific requirements
                and is optimized for the target platform and audience.
                
                When you complete your script, say "SCRIPT_WRITER_COMPLETE" to signal the reviewer.
                """,
            ),
            AssistantAgent(
                name="ScriptReviewer",
                model_client=self.script_review_model,
                system_message="""
                You are a Script Reviewer specializing in content analysis and improvement.
                
                Your expertise includes:
                - Comprehensive script analysis and critique
                - Technical accuracy verification
                - Audience suitability assessment
                - Production feasibility evaluation
                - Providing actionable feedback and recommendations
                
                Review scripts created by the Script Writer and provide detailed feedback
                to improve quality, accuracy, and effectiveness.
                
                Wait for the Script Writer to complete before starting your review.
                When you finish reviewing, say "SCRIPT_REVIEW_COMPLETE" to signal completion.
                """,
            ),
        ]

    def create_full_content_workflow_agents(self) -> List[AssistantAgent]:
        """Create agents for complete content creation workflow"""
        return [
            AssistantAgent(
                name="TournamentFinder",
                model_client=self.tournament_model,
                system_message="""
                You are a Tournament Finder providing tournament data for content creation.
                Find relevant tournaments and provide detailed information that can be used
                for script writing and social media content creation.
                
                When you complete your search, say "TOURNAMENT_FINDER_COMPLETE".
                """,
            ),
            AssistantAgent(
                name="ScriptWriter",
                model_client=self.script_writer_model,
                system_message="""
                You are a Script Writer creating content based on tournament information.
                Use tournament data from the Tournament Finder to create engaging scripts
                that promote tournaments and engage the baseball/softball community.
                
                Wait for tournament information before starting your script writing.
                When you complete your script, say "SCRIPT_WRITER_COMPLETE".
                """,
            ),
            AssistantAgent(
                name="ScriptReviewer",
                model_client=self.script_review_model,
                system_message="""
                You are a Script Reviewer providing feedback on tournament-related content.
                Review scripts for accuracy, engagement, and effectiveness in promoting
                tournaments and serving the baseball/softball community.
                
                Wait for the Script Writer to complete before starting your review.
                When you finish reviewing, say "SCRIPT_REVIEW_COMPLETE".
                """,
            ),
            AssistantAgent(
                name="SocialMediaOptimizer",
                model_client=self.ai_tips_model,
                system_message="""
                You are a Social Media Optimizer creating final social media content.
                Take the reviewed script and create optimized social media posts, tips,
                and engagement strategies for promoting tournaments.
                
                Wait for the Script Reviewer to complete before creating social media content.
                When you finish, say "SOCIAL_MEDIA_COMPLETE".
                """,
            ),
        ]

    async def run_tournament_workflow(self, query: str) -> str:
        """Run tournament search and social media content creation workflow"""
        agents = self.create_tournament_workflow_agents()
        team = RoundRobinGroupChat(agents, max_turns=6)

        initial_message = TextMessage(
            content=f"""
            Tournament Search Request: {query}
            
            Please help me with this tournament request:
            1. TournamentFinder: Search for relevant tournaments
            2. AITipsGenerator: Create social media content to promote the tournaments
            """,
            source="User",
        )

        print("🔄 Running Tournament + Social Media Workflow...")
        result = await team.run(task=initial_message)
        return self._format_workflow_result(result, "Tournament + Social Media")

    async def run_script_workflow(self, script_request: str) -> str:
        """Run script creation and review workflow"""
        agents = self.create_script_workflow_agents()
        team = RoundRobinGroupChat(agents, max_turns=4)

        initial_message = TextMessage(
            content=f"""
            Script Creation Request: {script_request}
            
            Please help me with this script request:
            1. ScriptWriter: Create the requested script
            2. ScriptReviewer: Review and provide feedback on the script
            """,
            source="User",
        )

        print("🔄 Running Script Creation + Review Workflow...")
        result = await team.run(task=initial_message)
        return self._format_workflow_result(result, "Script Creation + Review")

    async def run_full_content_workflow(self, content_request: str) -> str:
        """Run complete content creation workflow from tournament search to social media"""
        agents = self.create_full_content_workflow_agents()
        team = RoundRobinGroupChat(agents, max_turns=8)

        initial_message = TextMessage(
            content=f"""
            Complete Content Creation Request: {content_request}
            
            Please help me create complete content following this workflow:
            1. TournamentFinder: Find relevant tournament information
            2. ScriptWriter: Create script content based on tournament data
            3. ScriptReviewer: Review and improve the script
            4. SocialMediaOptimizer: Create final social media content and promotion strategy
            """,
            source="User",
        )

        print("🔄 Running Complete Content Creation Workflow...")
        result = await team.run(task=initial_message)
        return self._format_workflow_result(result, "Complete Content Creation")

    def _format_workflow_result(self, result, workflow_name: str) -> str:
        """Format workflow result for display"""
        if not result.messages:
            return f"❌ No results from {workflow_name} workflow"

        formatted_result = f"🎯 **{workflow_name.upper()} RESULTS**\n"
        formatted_result += "=" * 60 + "\n\n"

        # Extract agent responses
        agent_responses = []
        for i, msg in enumerate(result.messages):
            content = msg.content.strip()
            source = getattr(msg, "source", "Unknown")

            if (
                content
                and len(content) > 50
                and not content.startswith(f"{workflow_name} Request:")
            ):
                agent_responses.append(
                    {"content": content, "source": source, "index": i}
                )

        # Display agent responses
        for i, response in enumerate(agent_responses):
            agent_name = response["source"]

            # Map agent names to display names
            display_names = {
                "TournamentFinder": "🔍 Tournament Finder",
                "AITipsGenerator": "📱 AI Tips Generator",
                "ScriptWriter": "✍️ Script Writer",
                "ScriptReviewer": "🔍 Script Reviewer",
                "SocialMediaOptimizer": "📱 Social Media Optimizer",
            }

            display_name = display_names.get(agent_name, f"🤖 {agent_name}")

            formatted_result += f"{display_name}\n"
            formatted_result += "-" * 50 + "\n"
            formatted_result += response["content"] + "\n\n"

        return formatted_result

    def _format_complete_script_result(self, result) -> str:
        """Format complete script workflow result, extracting only the final script content (clean format)"""
        if not result.messages:
            return "❌ No results from Complete Script Creation workflow"

        # Extract the final script content from the ScriptReviewer's response
        final_script_content = ""

        # Look for the final script from ScriptReviewer
        for msg in reversed(result.messages):  # Search from the end
            content = msg.content.strip()
            source = getattr(msg, "source", "Unknown")

            # Substantial content
            if source == "ScriptReviewer" and len(content) > 500:
                final_script_content = content
                break

        # If no ScriptReviewer content found, look for ScriptWriter content
        if not final_script_content:
            for msg in reversed(result.messages):
                content = msg.content.strip()
                source = getattr(msg, "source", "Unknown")

                if source == "ScriptWriter" and len(content) > 500:
                    final_script_content = content
                    break

        # Return the clean script content without agent headers
        return (
            final_script_content
            if final_script_content
            else "❌ No substantial script content found"
        )

    def _format_sequential_workflow_result(
        self,
        script_topic: str,
        audience: str,
        tone: str,
        script_length: str,
        topic_enhancement: str,
        script_content: str,
        script_review: str,
    ) -> str:
        """Format sequential workflow result to match the expected document structure with proper formatting"""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Clean and format the revised script content
        revised_script = script_content.strip()

        # Clean review feedback
        review_feedback = script_review.strip()

        # Create properly formatted markdown document
        # Show only the final revised script (no duplicates)
        formatted_result = f"""Title: {script_topic}
**Script Type:** Video
**Duration:** {script_length}
**Generated:** {timestamp}
**Audience:** {audience}
**Tone:** {tone}

---

{revised_script}

---

*Generated by LineDrive Agent Test Console*
"""

        return formatted_result

    async def run_complete_script_workflow_sequential(
        self,
        script_topic: str,
        topic_description: str = "",
        audience: str = "general audience",
        tone: str = "conversational and educational",
        script_length: str = "5-8 minutes (800-1200 words)",
        max_chapters: int = 8,
        hook_summary: bool = True,
        script_format: str = SCRIPT_FORMAT_TEACHING,
    ) -> Dict[str, Any]:
        """
        Complete 4-Agent Sequential Workflow with Chapter-by-Chapter Script Writing

        1. Topic Assistant → Script Writer (per chapter) → Script Reviewer
        2. Includes timestamps for progress tracking
        3. Creates Word doc output in addition to markdown

        Args:
            max_chapters: Maximum number of chapters to generate (default: 8)
        """
        import re
        from datetime import datetime

        # Normalize the archetype; fall back to whatever the system was built
        # with (its client pair), then to teaching.
        script_format = (
            script_format if script_format in VALID_SCRIPT_FORMATS
            else getattr(self, "script_format", SCRIPT_FORMAT_TEACHING)
        )
        is_teaching = (script_format == SCRIPT_FORMAT_TEACHING)

        # Raised to cleanly bypass teaching-only steps (review, quotes/stats)
        # for the predictions / list archetypes — see STEP 3 and STEP 3.5.
        class _StepSkipped(Exception):
            pass

        def get_timestamp():
            return datetime.now().strftime("%H:%M:%S")

        def extract_duration_minutes(script_length: str) -> int:
            """Extract target minutes from script length string"""
            # Look for patterns like "8-12 minutes" or "20 minutes"
            match = re.search(r"(\d+)(?:-\d+)?\s*minutes?",
                              script_length.lower())
            if match:
                return int(match.group(1))
            # Default fallback
            return 8

        try:
            start_time = get_timestamp()
            if script_format == SCRIPT_FORMAT_PRO:
                print("=" * 60)
                print("🅿️  PRO SINGLE-PASS SCRIPT WRITER")
                print(f"🎬 Title: {script_topic}")
                print(f"👥 Audience: {audience}  |  💬 Tone: {tone}")
                print("🤖 Model: Claude Opus 5.5 (effort high), one cohesive pass")
                print("📐 Writes the hook, every chapter, the inline production "
                      "/ Grok Imagine prompts, the VERIFY notes, the cheat-sheet "
                      "overlay, and the trailing reference sections in ONE call")
                print("⭐ Guided by the saved GOLDEN REFERENCE script")
                print(f"🕐 Started at: {start_time}")
                print("=" * 60)
            else:
                print(f"🚀 COMPLETE 4-AGENT SEQUENTIAL WORKFLOW: {script_topic}")
                print(f"👥 Target Audience: {audience}")
                print(f"💬 Tone: {tone}")
                print(f"⏱️ Length: {script_length}")
                print(f"🕐 Started at: {start_time}")
                print("=" * 60)
                if self.verbose:
                    print("🔧 WORKFLOW TRACE: Starting sequential execution")

            # Initialize result containers
            topic_enhancement = ""
            all_chapter_scripts = []
            script_review = ""

            # ----------------------------------------------------------------
            # PRO single-pass path: write the ENTIRE script in ONE Claude Opus
            # 5.5 (max effort) call and return. Skips the whole topic-assistant
            # / per-chapter / review / quotes / hooks pipeline — the Pro writer
            # produces the hook, chapters, inline production blocks, and the
            # trailing reference sections itself (the way the user's best
            # hand-made script was produced in the Claude app).
            # ----------------------------------------------------------------
            if script_format == SCRIPT_FORMAT_PRO:
                from linedrive_azure.agents.pro_script_writer import (
                    write_pro_script,
                )
                print("📥 Loading the golden reference script as the guide…")
                print("✍️  Claude Opus 5.5 is writing the ENTIRE script in one "
                      "pass. This runs ~3 to 5 minutes with no per-chapter steps "
                      f"— progress prints as it writes. [{get_timestamp()}]")
                print("-" * 50)
                pro_text = write_pro_script(
                    title=script_topic, brief=topic_description)
                if pro_text and len(pro_text) >= 800:
                    _n_ch = len(re.findall(
                        r'(?mi)^\s*Heading:\s*Chapter\b', pro_text))
                    _n_prod = len(re.findall(r'\[PRODUCTION BEGIN\]', pro_text))
                    _n_img = len(re.findall(r'\[GROK IMAGINE', pro_text))
                    _n_verify = len(re.findall(r'\[VERIFY', pro_text))
                    print("-" * 50)
                    print(f"✅ Pro script complete [{get_timestamp()}]")
                    print(f"   📄 {len(pro_text.split())} words, {_n_ch} chapters")
                    print(f"   🎬 {_n_prod} production blocks, {_n_img} Grok "
                          f"Imagine prompts, {_n_verify} verify notes")
                    print("   ⏭️  Skipped: topic planner, per-chapter writers, "
                          "review, quotes, hook agents (all in the one pass)")
                    return {
                        "success": True,
                        "script_content": pro_text,
                        "workflow_type": "single_pass_pro_claude",
                        "topic_enhancement": "",
                        "chapter_scripts": [],
                        "combined_script": pro_text,
                        "script_review": "Single-pass Pro writer (no review)",
                        "thumbnail_hook_text": "",
                        "thumbnail_hook_text_options": [],
                        "chapters_count": _n_ch,
                        "target_minutes_per_chapter": 0,
                        "comparison_file": None,
                        "chapter_comparisons": None,
                    }
                return {
                    "success": False,
                    "error": "Pro single-pass writer returned no/short output "
                             "(check ANTHROPIC_API_KEY and the claude-opus-5-5 "
                             "model alias).",
                }

            # For predictions / Top-N list, honor the item count the user asked
            # for (parsed from the title) and widen the chapter cap to N (+ intro
            # + conclusion). quick_test (max_chapters == 1) is left untouched.
            requested_count = None
            if not is_teaching and max_chapters > 1:
                _m = re.search(r"\b(\d{1,2})\b", script_topic or "")
                requested_count = (
                    int(_m.group(1)) if _m
                    else (7 if script_format == SCRIPT_FORMAT_PREDICTIONS else 10)
                )
                requested_count = max(3, min(requested_count, 15))
                max_chapters = requested_count + 2
                print(
                    f"🔢 {script_format} format: honoring {requested_count} "
                    f"items → max_chapters={max_chapters}"
                )

            # STEP 1: Topic Assistant
            step_start = get_timestamp()
            print(
                f"\n📋 STEP 1: Topic Enhancement & Chapter Planning [{step_start}]")
            print("-" * 50)

            # Create a new thread for the topic assistant
            topic_thread = (
                self.script_topic_assistant_client.project.agents.threads.create()
            )
            topic_thread_id = topic_thread.id

            topic_request = f"""
TOPIC ENHANCEMENT REQUEST:

PRIMARY REQUIREMENTS (MOST IMPORTANT):
{f'''
USER'S DETAILED DESCRIPTION:
{topic_description}

⚠️ CRITICAL: The description above defines EXACTLY what this script should cover.
Follow it closely for tone, scope, specific topics, and approach.
''' if topic_description else "No specific description provided - use topic title as guide."}

Topic Title: {script_topic}
Target Audience: {audience}
Desired Tone: {tone}
Script Length: {script_length}

YOUR TASK:
Create a structured chapter plan that DIRECTLY addresses the user's description above.

Required Output:
1. LOGICAL chapter breakdown (5-8 chapters maximum for {script_length})
2. Each chapter must have a SPECIFIC, DESCRIPTIVE title that reflects 
   the user's description requirements
3. Key points per chapter, drawn from the description (aligned with description)
4. Content flow and timing guidance
5. Specific examples suitable for {audience}
6. Tone guidelines to achieve {tone} style

FIDELITY RULES (these override every other instruction):
- If the description names specific events, products, people, companies,
  quotes, dates or URLs, those are the SUBJECT of the script. Build the
  chapters around THEM. Carry the specific names through into the chapter
  titles and key points — do not abstract them into generic themes.
- Do NOT convert the description into a generic "practical guide", "how-to",
  tutorial, tips listicle, or business-strategy explainer unless the
  description explicitly asks for one. If the description is a set of news
  events, the script is about those events.
- Do NOT introduce statistics, studies, surveys, reports or expert quotes that
  are absent from the description. Never invent a source or a number.
- If the description contains a block of constraints (for example
  "NON-NEGOTIABLE FACTS"), treat every line of it as a hard requirement.

CHAPTER STRUCTURE REQUIREMENTS:
- Chapter 1: Introduction/Overview (hook the audience based on description)
- Chapters 2-6: Specific aspects/subtopics FROM THE DESCRIPTION
- Final Chapter: Conclusion/Future outlook (based on description's goal)
- Each chapter title must be descriptive and specific

FORMAT: List each chapter as:
Chapter 1: [Specific descriptive title based on description]
Chapter 2: [Different specific descriptive title based on description]
etc.

Remember: The USER'S DESCRIPTION is your primary guide. The topic title is
secondary. Ensure every chapter serves the goals outlined in the description.
"""

            # Non-teaching archetypes (predictions / Top-N list) replace the
            # teaching "5-8 chapters" plan request above with a count-honoring
            # one. The archetype's own Foundry system prompt supplies the
            # predictions-vs-countdown framing; this message just carries the
            # brief, the exact item count, and the fidelity rules so it never
            # fights that prompt (no "don't make a listicle", no "Chapters 2-6").
            if not is_teaching:
                _n = requested_count or max(1, max_chapters)
                _kind = (
                    "bold predictions"
                    if script_format == SCRIPT_FORMAT_PREDICTIONS
                    else "ranked list items"
                )
                topic_request = f"""
TOPIC PLANNING REQUEST:

{f'''USER'S DETAILED DESCRIPTION:
{topic_description}

The description above defines what this video must cover — follow it closely.
''' if topic_description else "No detailed description provided — use the title as the guide."}

Video Title: {script_topic}
Target Audience: {audience}
Desired Tone: {tone}
Video Length: {script_length}
Requested item count: {_n}

YOUR TASK:
Plan this video following YOUR system instructions for this format. Produce
EXACTLY {_n} core {_kind}, one per chapter — honor that count, do not collapse
or expand it. You may add a short Introduction chapter at the start and a
Conclusion chapter at the end if it serves the piece.

FIDELITY RULES (these override every other instruction):
- If the description names specific events, products, people, companies,
  quotes, dates or URLs, carry those specifics through into the chapter titles
  and key points — do not abstract them into generic themes.
- Do NOT introduce statistics, studies, surveys, reports or expert quotes that
  are absent from the description. Never invent a source or a number.

OUTPUT FORMAT:
Use YOUR system instructions' output format EXACTLY — in particular, emit the
"CHAPTER BREAKDOWN:" section with one `Chapter N: ...` line for EVERY chapter
(the opening chapter, each of the {_n} items, and the closing chapter). The
downstream script writer and the chapter parser read those `Chapter N:` lines,
so they must be present for every chapter — do not replace them with only a
summary list.
"""

            topic_result = self.script_topic_assistant_client.send_message(
                thread_id=topic_thread_id,
                message_content=topic_request,
                show_sources=False,
                timeout=300,
            )

            step_end = get_timestamp()
            if topic_result["success"]:
                topic_enhancement = topic_result["response"]
                # De-shout ALL-CAPS chapter titles / planning text. Azure's
                # content filter flags shouting as aggressive and rejects the
                # downstream chapter-writer calls, so normalize here — this
                # fixes both the extracted chapter titles AND the full planning
                # text passed to the writer agent.
                topic_enhancement = _deshout_text(topic_enhancement)
                print(
                    f"✅ Topic enhanced ({len(topic_enhancement)} chars) [{step_end}]"
                )

                # Extract chapters from topic enhancement
                # Try multiple patterns to handle different agent output formats

                # Pattern 1: Full format with title and timestamp
                # "Chapter 1: Introduction - Hook (0:00-1:30)"
                # Use non-greedy match and stop at newline to avoid capturing multiple chapters.
                # NOTE: use \s+ (not a literal space) after "Chapter" — the List
                # topic agent emits a NARROW NO-BREAK SPACE (U+202F) there, which a
                # literal " " does not match, silently yielding 0 chapters.
                full_pattern_matches = re.findall(
                    r"Chapter\s+\d+[:\-]\s*([^\n(]+?)\s*\([^)]+\)",
                    topic_enhancement,
                    re.IGNORECASE
                )

                # Pattern 2: Title with em-dash format
                # "Hook + Roadmap — "Stop Guessing: The 5 AI Tools..."
                emdash_pattern_matches = re.findall(
                    r'^([A-Z][^\u2014\n]+)(?:\u2014)\s*["\u201c]([^"\u201d\n]+)',
                    topic_enhancement,
                    re.MULTILINE
                )

                # Pattern 3: Simple chapter format
                # "Chapter 1: Introduction"
                simple_pattern_matches = re.findall(
                    r"Chapter\s+\d+[:\-]\s*([^\n(]+?)(?:\s*\(|\s*$)",
                    topic_enhancement,
                    re.IGNORECASE
                )

                # Combine matches, preferring more specific patterns
                chapter_matches = []
                if full_pattern_matches:
                    chapter_matches = [m.strip() for m in full_pattern_matches]
                elif emdash_pattern_matches:
                    chapter_matches = [
                        f"{tool.strip()} - {desc.strip()}" for tool, desc in emdash_pattern_matches]
                elif simple_pattern_matches:
                    chapter_matches = [m.strip()
                                       for m in simple_pattern_matches]

                # Debug: show all matches found
                print(
                    f"\n🔍 DEBUG: Found {len(chapter_matches)} chapter matches from Topic Agent")
                # Show first 3 only
                for idx, match in enumerate(chapter_matches[:3], 1):
                    print(f"   Raw Match {idx}: '{match[:80]}...'")
                sys.stdout.flush()

                # Remove duplicates while preserving order and limit chapters
                chapters = []
                seen = set()
                if chapter_matches:
                    for match in chapter_matches:
                        clean_chapter = match.strip()
                        # Skip timestamps, very short entries, or duplicates
                        # Filter out entries that are just timestamps (e.g., "0:00–1:30")
                        timestamp_pattern = r'^\d+:\d+[–\-—]\d+:\d+$'
                        is_timestamp = bool(
                            re.match(timestamp_pattern, clean_chapter))
                        if (len(clean_chapter) > 10 and
                            clean_chapter not in seen and
                                not is_timestamp):
                            chapters.append(clean_chapter)
                            seen.add(clean_chapter)
                        else:
                            print(
                                f"   ⚠️ Skipped: '{clean_chapter}' (len={len(clean_chapter)}, duplicate={clean_chapter in seen}, timestamp_only={is_timestamp})")
                    sys.stdout.flush()

                    # Limit to max_chapters parameter
                    if len(chapters) > max_chapters:
                        print(
                            f"   ✂️ Trimming from {len(chapters)} to {max_chapters} chapters")
                        chapters = chapters[:max_chapters]
                        sys.stdout.flush()

                if not chapters:
                    # Fallback: look for numbered sections
                    numbered_matches = re.findall(
                        r"\d+\.\s*([^\n]+)", topic_enhancement
                    )
                    chapters = (
                        [match.strip() for match in numbered_matches[:5]]
                        if numbered_matches
                        else ["Introduction", "Main Content", "Conclusion"]
                    )

                # Display chapter breakdown with progress markers so ConsoleCapture picks it up
                print(
                    f"\n📝 Identified {len(chapters)} chapters - Chapter Planning Complete [21%]")
                print("=" * 80)
                print("📋 CHAPTER BREAKDOWN:")
                print("=" * 80)
                for i, chapter in enumerate(chapters, 1):
                    print(f"   Chapter {i}: {chapter}")
                print("=" * 80)
                print("")
                sys.stdout.flush()

            else:
                return {
                    "success": False,
                    "error": f"Topic Assistant failed: {topic_result.get('error')}",
                }

            # Calculate time per chapter
            total_minutes = extract_duration_minutes(script_length)
            minutes_per_chapter = max(
                total_minutes // len(chapters), 2
            )  # Minimum 2 minutes per chapter
            words_per_minute = 150  # Average speaking rate
            words_per_chapter = minutes_per_chapter * words_per_minute

            print(
                f"⏱️ Target: {minutes_per_chapter}+ minutes per chapter ({words_per_chapter}+ words)"
            )

            # STEP 2: Script Writer - Chapter by Chapter (PARALLEL)
            print(
                f"\n✍️ STEP 2: Chapter-by-Chapter Script Writing [{get_timestamp()}]")
            print("-" * 60)

            def _write_one_chapter(i: int, chapter_topic: str) -> Dict[str, Any]:
                """Write a single chapter. Runs in a worker thread.

                Returns dict: {index, chapter_topic, success, response|error, elapsed}
                Each call uses its OWN agent thread so chapters are fully
                independent and safe to run concurrently.
                """
                _start = time.time()
                _ts = get_timestamp()
                print(
                    f"\n📝 [parallel] Start Chapter {i}/{len(chapters)}: {chapter_topic} [{_ts}]"
                )

                try:
                    script_thread = (
                        self.script_writer_client.project.agents.threads.create()
                    )
                    script_thread_id = script_thread.id
                except Exception as _e:
                    return {
                        "index": i, "chapter_topic": chapter_topic,
                        "success": False,
                        "error": f"thread create failed: {_e}",
                        "elapsed": time.time() - _start,
                    }

                script_request = f"""
CHAPTER SCRIPT WRITING REQUEST:

PRIMARY CONTEXT (FOLLOW CLOSELY):
{f'''
USER'S ORIGINAL DESCRIPTION:
{topic_description}

⚠️ This description defines the TONE, DETAILS, and COVERAGE you must follow.
''' if topic_description else "No specific description - follow topic title and chapter guidance."}

Topic Title: {script_topic}
Chapter {i} of {len(chapters)}: {chapter_topic}
Target Audience: {audience}
Desired Tone: {tone}
Target Length: {minutes_per_chapter}+ minutes ({words_per_chapter}+ words)

ENHANCED PLANNING FROM TOPIC ASSISTANT:
{topic_enhancement}

YOUR TASK:
Write a detailed script for CHAPTER {i} ONLY: "{chapter_topic}"

CRITICAL REQUIREMENTS:
1. Follow the USER'S DESCRIPTION above for tone, depth, and approach
1a. FACTUAL FIDELITY — the description is the source of truth. Use the specific
    events, products, people, companies, quotes, dates and URLs it names, by
    name. Do NOT replace them with generic framing, a "practical guide", a
    how-to, or business-strategy commentary. Do NOT introduce statistics,
    studies, surveys, reports or expert quotes that are absent from the
    description — if you need a number or a quote, it must come from the
    description. Never invent or paraphrase-into-quotes a statement attributed
    to a real person. If the description marks a quote as unavailable, describe
    the event in your own words instead. If the description includes a
    constraints block (e.g. "NON-NEGOTIABLE FACTS"), obey every line of it.
2. Minimum {minutes_per_chapter} minutes of content ({words_per_chapter}+ words)
3. Use {tone} tone appropriate for {audience}
4. Include detailed, specific host dialogue (not summaries)
5. Add ONLY ONE [Visual Cue: ...] at the beginning
6. Make it engaging and comprehensive
7. This is a CONTINUOUS VIDEO - no "Welcome back" phrases
8. For chapters after Chapter 1, use smooth transitions
{"9. **THIS IS THE FINAL CHAPTER** - Include a 'Summary' section that wraps up the entire series. Do NOT end with 'Next up' or suggest future chapters. This should be conclusive and complete." if i == len(chapters) else ""}

FORMAT:
## Chapter {i}: {chapter_topic} ({minutes_per_chapter}+ minutes)

Heading: Chapter {i} - {chapter_topic}

Visual Cue: [Describe what visual/image/video should be shown]

**Host:**
[Complete, detailed host dialogue - the ONLY Host: label in this chapter]

{"Summary: [2-3 paragraph conclusion that ties together all chapters and provides closure]" if i == len(chapters) else ""}

FORMATTING RULES:
- Use only ONE "**Host:**" label per chapter
- No duplicate "Host:" labels in dialogue
- Chapter 1: Assume basic familiarity - don't oversimplify
- Start Chapter 1 conversationally, then build depth
- Maintain {tone} tone throughout
{"- FINAL CHAPTER: Must include Summary section and conclusive ending" if i == len(chapters) else ""}

REMINDER: The USER'S DESCRIPTION is your guide for level of detail,
specific points to cover, and overall approach. Honor their intent.
"""

                # Non-teaching archetypes (predictions / Top-N list) get a punchy,
                # brief-driven message instead of the teaching "detailed /
                # comprehensive" one above (which produced tutorial voice, padding
                # and only-partial coverage). We defer the archetype VOICE to the
                # writer agent's own system prompt and only enforce: follow the
                # brief, cover THIS item fully, stay tight, and (per the user) use
                # NO em-dashes. The teaching 2-min/chapter floor also bloats a
                # 12-item countdown to ~24 min, so target a punchy per-item length.
                if not is_teaching:
                    _is_first = (i == 1)
                    _is_last = (i == len(chapters))
                    _punchy_words = max(
                        90, int((total_minutes * 150) / max(len(chapters), 1)))
                    if script_format == SCRIPT_FORMAT_LIST:
                        _beat = (
                            "This chapter is ONE entry in a ranked countdown. In "
                            "the host's own flowing speech (NOT labeled sections), "
                            "hit three quick beats: what this item is GREAT at (its "
                            "sweet spot), the ONE job where it quietly slips (its "
                            "blind spot), and the ONE-LINE fix or check that makes it "
                            "safe to use. Anchor it in ONE concrete everyday example "
                            "(a flyer, a parent email, a booking sheet, a slide deck, "
                            "a meeting). Frame every slip as a 'good to know', never a "
                            "'gotcha'."
                        )
                    else:  # predictions
                        _beat = (
                            "This chapter is ONE bold prediction. Open on a vivid "
                            "near-future scene, then say what changes and why it is "
                            "plausible, grounded in a real signal happening today. "
                            "Cinematic and visionary, not a how-to, not 'already here "
                            "today' hedging."
                        )
                    if _is_first:
                        _role = (
                            "This is the OPENING chapter. Start with a fast, "
                            "high-energy cold open that matches the brief (e.g. the "
                            "rapid-fire 'ten failures in ten seconds' montage if the "
                            "brief calls for it), state the one-sentence promise of "
                            "the video, then roll STRAIGHT into the first entry. Keep "
                            "the intro SHORT and punchy, no long throat-clearing. "
                            + _beat
                        )
                    elif _is_last:
                        _role = (
                            "This is the FINAL chapter. Land the number-one / final "
                            "entry, then close with a fast recap of the through-line "
                            "and the core payoff from the brief. Be conclusive; do NOT "
                            "tease future chapters. " + _beat
                        )
                    else:
                        _role = _beat

                    script_request = f"""
CHAPTER SCRIPT WRITING REQUEST ({script_format} format):

THE BRIEF IS THE BOSS — follow its tone, structure and language cues exactly:
{topic_description if topic_description else "No brief provided — follow the title and the chapter plan below."}

Video Title: {script_topic}
Chapter {i} of {len(chapters)}: {chapter_topic}
Target Audience: {audience}
Desired Tone: {tone}
Pacing: punchy and tight — around {_punchy_words} words. Prioritize energy and clarity over length. NO padding, NO filler, NO restating.

CHAPTER PLAN FROM THE TOPIC ASSISTANT (ordering/context):
{topic_enhancement}

YOUR TASK:
Write the spoken host narration for CHAPTER {i} ONLY: "{chapter_topic}".
{_role}

HARD RULES:
- Follow YOUR system instructions for this video format. This is NOT a tutorial and NOT a warning label.
- Cover THIS chapter's specific item fully. Do NOT summarize or list the other items here.
- Use the real tools/items/examples named in the brief and the chapter plan, BY NAME. Do not invent items or swap in generic ones.
- NO em-dashes anywhere (no "—", no "–"). Use short sentences, commas, or periods instead.
- Continuous single-host video: no "Welcome back", no "Hey everyone", no per-chapter greeting.
- Output EXACTLY one [Visual Cue: ...] line at the top, then ONE single **Host:** block.

FORMAT:
## Chapter {i}: {chapter_topic}

Visual Cue: [what to show on screen]

**Host:**
[the spoken narration — the ONLY Host: label in this chapter]
"""

                def _fallback_or_fail(primary_error: str) -> Dict[str, Any]:
                    """Re-write this chapter with Claude; only fail if that also fails.

                    Lets a complete script come back even when the Azure writer
                    is rate-limited (429) or refuses — the user's main ask.
                    """
                    print(
                        f"   ⚠️ [parallel] Chapter {i}/{len(chapters)} primary writer "
                        f"failed ({primary_error}). Trying Claude Opus 4.8 fallback…"
                    )
                    _ct = _claude_chapter_fallback(script_request)
                    if _ct and len(_ct) >= 400:
                        print(
                            f"   ✅ [parallel] Chapter {i}/{len(chapters)} written by "
                            f"Claude fallback ({len(_ct)} chars)"
                        )
                        return {
                            "index": i, "chapter_topic": chapter_topic,
                            "success": True, "response": _ct,
                            "elapsed": time.time() - _start, "via": "claude_fallback",
                        }
                    print(
                        f"   ❌ [parallel] Chapter {i}/{len(chapters)} Claude fallback "
                        f"unavailable or too short — failing."
                    )
                    return {
                        "index": i, "chapter_topic": chapter_topic,
                        "success": False, "error": primary_error,
                        "elapsed": time.time() - _start,
                    }

                # Non-teaching archetypes (list / predictions): write with Claude
                # Opus 5.5 at MAX effort as the PRIMARY writer — it follows the
                # brief and the no-em-dash rule far more reliably than the Foundry
                # writer did on countdowns. The Foundry writer stays as the
                # fallback below if Claude is unavailable or returns too little.
                if not is_teaching:
                    _primary = _claude_chapter_fallback(script_request)
                    if _primary and len(_primary) >= 300:
                        print(
                            f"   ✅ [parallel] Chapter {i}/{len(chapters)} written by "
                            f"Claude {_CLAUDE_FALLBACK_MODEL} (primary, {len(_primary)} chars)"
                        )
                        return {
                            "index": i, "chapter_topic": chapter_topic,
                            "success": True, "response": _primary,
                            "elapsed": time.time() - _start, "via": "claude_primary",
                        }
                    print(
                        f"   ⚠️ [parallel] Chapter {i}/{len(chapters)} Claude primary "
                        f"unavailable/too short — falling back to the Foundry writer"
                    )

                try:
                    script_result = self.script_writer_client.send_message(
                        thread_id=script_thread_id,
                        message_content=script_request,
                        show_sources=False,
                        timeout=300,
                    )
                except Exception as _e:
                    return _fallback_or_fail(f"send_message raised: {_e}")

                _elapsed = time.time() - _start
                if script_result.get("success"):
                    _resp = script_result.get("response", "") or ""
                    # Detect Azure content-filter refusal text. The Responses API
                    # sometimes emits partial chapter text followed by a refusal
                    # apology block. If we leave that in, downstream agents (e.g.
                    # Hook & Summary) see the refusal in their input and refuse the
                    # whole job. Strip the refusal tail; if what's left is too
                    # short to be a real chapter, surface as failure.
                    _refusal_re = re.compile(
                        r"(?:^|\n)\s*I[\u2019']?m sorry,?\s+but I cannot assist with that request\.?\s*$",
                        flags=re.IGNORECASE,
                    )
                    if _refusal_re.search(_resp):
                        _cleaned = _refusal_re.sub("", _resp).rstrip()
                        _orig_len = len(_resp)
                        _new_len = len(_cleaned)
                        # If the chapter is now suspiciously short (<400 chars OR
                        # we lost more than 25% of the body), treat as a failed
                        # write so the workflow bails instead of producing a
                        # broken script that later poisons the hook agent.
                        if _new_len < 400 or _new_len < _orig_len * 0.5:
                            print(
                                f"   ⚠️ [parallel] Chapter {i}/{len(chapters)} hit content-filter refusal "
                                f"({_orig_len}→{_new_len} chars). Marking as failed."
                            )
                            return _fallback_or_fail(
                                "Chapter writer hit Azure content-filter refusal "
                                "('I'm sorry, but I cannot assist with that request.')."
                            )
                        # Otherwise just trim the trailing apology and keep the chapter.
                        print(
                            f"   ✂️ [parallel] Chapter {i}/{len(chapters)}: trimmed trailing "
                            f"refusal apology ({_orig_len}→{_new_len} chars)"
                        )
                        _resp = _cleaned
                    print(
                        f"   ✅ [parallel] Chapter {i}/{len(chapters)} done "
                        f"({len(_resp)} chars) in {_elapsed:.1f}s"
                    )
                    return {
                        "index": i, "chapter_topic": chapter_topic,
                        "success": True, "response": _resp, "elapsed": _elapsed,
                    }
                return _fallback_or_fail(script_result.get("error", "unknown"))

            # Run all chapter writes in parallel. Cap concurrency to avoid
            # hammering the agent endpoint; for typical 3-8 chapter videos
            # max_workers=8 means all chapters run truly concurrently.
            _parallel_start = time.time()
            max_workers = min(len(chapters), 8)
            print(
                f"🚀 Launching {len(chapters)} chapter writes in parallel "
                f"(max_workers={max_workers})..."
            )
            chapter_results: List[Dict[str, Any]] = [None] * len(chapters)  # type: ignore
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers, thread_name_prefix="chapter-writer"
            ) as ex:
                future_to_idx = {
                    ex.submit(_write_one_chapter, i, chapter_topic): i - 1
                    for i, chapter_topic in enumerate(chapters, 1)
                }
                for fut in concurrent.futures.as_completed(future_to_idx):
                    idx = future_to_idx[fut]
                    chapter_results[idx] = fut.result()

            _parallel_elapsed = time.time() - _parallel_start
            print(
                f"🏁 Parallel chapter writing finished in {_parallel_elapsed:.1f}s "
                f"(would have been ~{sum(r['elapsed'] for r in chapter_results):.1f}s sequential)"
            )

            # Bail out on first failure (in chapter order) — same behavior as old loop
            for r in chapter_results:
                if not r["success"]:
                    return {
                        "success": False,
                        "error": f"Script Writer failed on Chapter {r['index']}: {r.get('error')}",
                    }

            # Preserve chapter order
            all_chapter_scripts = [r["response"] for r in chapter_results]

            # Combine all chapters into full script
            combined_script = f"""
Title: {script_topic}
**Script Type:** Video
**Duration:** {script_length}  
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

""" + "\n\n---\n\n".join(
                all_chapter_scripts
            )

            print(
                f"\n🔗 Combined all {len(chapters)} chapters into full script ({len(combined_script)} chars)"
            )

            # STEP 3: Script Reviewer (Chapter-by-Chapter)
            review_start = get_timestamp()
            print(f"\n🔍 STEP 3: Script Review & Final Polish [{review_start}]")
            print("-" * 50)
            print("📝 Reviewing each chapter individually for best results...")

            complete_revised_script_content = None
            script_review = "Chapter-by-Chapter Review"
            review_skipped = False

            try:
                # Predictions and Top-N list archetypes skip the review pass
                # entirely — the reviewer agent is tuned for the teaching
                # "5 things" tutorial voice and would flatten the cinematic /
                # countdown styling back toward that archetype.
                if not is_teaching:
                    print(
                        f"⏭️  STEP 3: Script Review SKIPPED for "
                        f"'{script_format}' format")
                    raise _StepSkipped()
                # Skip whole-document review (always times out)
                # Go straight to chapter-by-chapter revision
                print("🔄 Starting chapter-by-chapter revision (parallel)...")

                # Track original vs revised for comparison report
                chapter_comparisons: List[Dict[str, Any]] = []
                revision_feedback: List[Dict[str, Any]] = []

                def _review_one_chapter(i: int, chapter_script: str) -> Dict[str, Any]:
                    """Review and revise a single chapter. Runs in a worker thread.

                    Each chapter gets its OWN agent thread (no cross-chapter
                    state) so the review can be safely parallelized. The
                    review prompt is purely a function of (i, len(chapters),
                    chapter_script, audience, tone) — there is no dependency
                    on previously-revised chapters, so the resulting output
                    is identical to the sequential loop.
                    """
                    _start = time.time()
                    _ts = get_timestamp()
                    print(
                        f"   🔍 [parallel] Reviewing Chapter {i}/{len(chapters)} [{_ts}]")

                    try:
                        chapter_thread = (
                            self.script_review_client.project.agents.threads.create()
                        )
                        chapter_thread_id = chapter_thread.id
                    except Exception as _e:
                        return {
                            "index": i, "success": False,
                            "original": chapter_script,
                            "error": f"thread create failed: {_e}",
                            "elapsed": time.time() - _start,
                        }

                    chapter_review_request = f"""
INDIVIDUAL CHAPTER REVISION REQUEST:

Please review and provide a revised version of this chapter ONLY.

Chapter {i} of {len(chapters)} - Target audience: {audience}, Tone: {tone}
{('**THIS IS THE FINAL CHAPTER** - It MUST include both a Visual Cue AND a ' + chr(39) + 'Summary' + chr(39) + ' section at the end.') if i == len(chapters) else ''}

ORIGINAL CHAPTER:
{chapter_script}

INSTRUCTIONS:
1. Provide a COMPLETE REVISED CHAPTER with full dialogue
2. Use this exact format:
   - Heading: Chapter {i} - [Chapter Title]
   - Visual Cue: [Describe what visual should be shown] (REQUIRED - do not skip!)
   - **Host:** [Complete dialogue]
   {'- Summary: [2-3 paragraph conclusion wrapping up entire series]' if i == len(chapters) else ''}
3. Use ONLY ONE "**Host:**" label per chapter - remove any duplicate Host: labels
4. Include EXACTLY ONE Visual Cue that describes what should be shown visually
5. Ensure content is suitable for {audience} with {tone} tone
6. CONTINUOUS VIDEO FORMAT: Remove "Welcome back", "Thanks for joining", etc.
7. For Chapter {i}: {'Assume audience knows basic concepts - avoid oversimplified explanations' if i == 1 else 'Use smooth transition from previous chapter'}
8. Visual cues should describe actual visuals, not just be chapter titles

CRITICAL - YOUR RESPONSE MUST CONTAIN ONLY:

REVISED CHAPTER:
Heading: [Title]

Visual Cue: [Specific visual description]

**Host:**
[Complete dialogue]
{(chr(10) + 'Summary: [Conclusive wrap-up of entire series]') if i == len(chapters) else ''}

DO NOT INCLUDE:
- "=== REVIEW FEEDBACK ===" sections
- Feedback or meta-commentary
- Multiple format options
- Explanations of changes

Just provide the clean, production-ready revised chapter content above.
"""

                    try:
                        chapter_retry_result = self.script_review_client.send_message(
                            thread_id=chapter_thread_id,
                            message_content=chapter_review_request,
                            show_sources=False,
                            timeout=300,
                        )
                    except Exception as _e:
                        return {
                            "index": i, "success": False,
                            "original": chapter_script,
                            "error": f"send_message raised: {_e}",
                            "elapsed": time.time() - _start,
                        }

                    _elapsed = time.time() - _start
                    if not chapter_retry_result.get("success"):
                        return {
                            "index": i, "success": False,
                            "original": chapter_script,
                            "error": chapter_retry_result.get("error", "unknown"),
                            "elapsed": _elapsed,
                        }

                    response = chapter_retry_result["response"]

                    # Extract feedback/changes made if present
                    feedback_section = ""
                    if "=== REVIEW FEEDBACK ===" in response:
                        parts = response.split("=== REVIEW FEEDBACK ===", 1)
                        if len(parts) > 1:
                            feedback_part = parts[1]
                            if "=== REVISED SCRIPT ===" in feedback_part:
                                feedback_section = feedback_part.split(
                                    "=== REVISED SCRIPT ===")[0].strip()
                            else:
                                feedback_section = feedback_part.strip()

                    # Extract only the revised chapter (ignore feedback)
                    if "=== REVISED SCRIPT ===" in response:
                        revised_chapter = response.split(
                            "=== REVISED SCRIPT ===", 1)[1].strip()
                    elif "REVISED CHAPTER:" in response:
                        revised_chapter = response.split(
                            "REVISED CHAPTER:", 1)[1].strip()
                    else:
                        revised_chapter = response

                    # CRITICAL: Remove any === formatted sections or feedback that leaked through
                    if "===" in revised_chapter:
                        lines = revised_chapter.split('\n')
                        clean_lines = []
                        skip_mode = False
                        for line in lines:
                            if '===' in line or 'REVIEW FEEDBACK' in line:
                                skip_mode = True
                                continue
                            if skip_mode or any(keyword in line.upper() for keyword in [
                                'FEEDBACK', 'IMPROVEMENTS',
                                'CHANGES MADE', 'ASSESSMENT', 'ANALYSIS',
                                'AUDIENCE APPROPRIATENESS', 'TONE & STYLE',
                                'STRUCTURE & FLOW', 'CONTENT QUALITY'
                            ]):
                                skip_mode = True
                                continue
                            if skip_mode and (line.startswith('## Chapter') or
                                              line.startswith('[Visual Cue:') or
                                              line.startswith('**Host:**')):
                                skip_mode = False
                            if not skip_mode:
                                clean_lines.append(line)
                        revised_chapter = '\n'.join(clean_lines).strip()

                    print(
                        f"   ✅ [parallel] Chapter {i} revised "
                        f"({len(revised_chapter)} chars) in {_elapsed:.1f}s")
                    return {
                        "index": i, "success": True,
                        "original": chapter_script,
                        "revised": revised_chapter,
                        "feedback": feedback_section,
                        "elapsed": _elapsed,
                    }

                # Run all chapter reviews in parallel (each has its own
                # agent thread → fully independent). Cap concurrency at 8
                # to match the writer pool and avoid hammering the endpoint.
                _parallel_start = time.time()
                _max_workers = min(len(all_chapter_scripts), 8)
                print(
                    f"🚀 Launching {len(all_chapter_scripts)} chapter reviews in parallel "
                    f"(max_workers={_max_workers})..."
                )
                review_results: List[Dict[str, Any]] = [None] * len(all_chapter_scripts)  # type: ignore
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=_max_workers, thread_name_prefix="chapter-reviewer"
                ) as ex:
                    future_to_idx = {
                        ex.submit(_review_one_chapter, i, chap): i - 1
                        for i, chap in enumerate(all_chapter_scripts, 1)
                    }
                    for fut in concurrent.futures.as_completed(future_to_idx):
                        idx = future_to_idx[fut]
                        review_results[idx] = fut.result()

                _parallel_elapsed = time.time() - _parallel_start
                print(
                    f"🏁 Parallel chapter review finished in {_parallel_elapsed:.1f}s "
                    f"(would have been ~{sum(r['elapsed'] for r in review_results):.1f}s sequential)"
                )

                # Assemble revised chapters in original order. On per-chapter
                # failure, fall back to the original (same behavior as the
                # old sequential loop).
                revised_chapters: List[str] = []
                for r in review_results:
                    i = r["index"]
                    if r["success"]:
                        revised_chapters.append(r["revised"])
                        chapter_comparisons.append({
                            'chapter_num': i,
                            'original': r["original"],
                            'revised': r["revised"],
                            'feedback': r["feedback"] or "No feedback provided"
                        })
                        if r["feedback"]:
                            revision_feedback.append({
                                'chapter': i,
                                'feedback': r["feedback"],
                                'length': len(r["feedback"]),
                            })
                    else:
                        print(
                            f"   ⚠️ Chapter {i} revision failed ({r.get('error')}), using original")
                        revised_chapters.append(r["original"])
                        fallback_msg = f"Used original version (revision failed: {r.get('error')})"
                        revision_feedback.append({
                            'chapter': i,
                            'feedback': fallback_msg,
                            'length': len(fallback_msg),
                        })

                # Assemble all revised chapters into complete script
                print(
                    f"\n🔗 Assembling {len(revised_chapters)} revised chapters..."
                )

                # Assemble all revised chapters into complete script content (without header)
                complete_revised_script_content = "\n\n---\n\n".join(
                    revised_chapters
                )

                # Combine all feedback without embedding the revised script
                all_feedback = "\n".join(
                    f"Chapter {item['chapter']}: {item['feedback']}"
                    if isinstance(item, dict) else str(item)
                    for item in revision_feedback
                )
                script_review = (
                    f"{script_review}\n\n"
                    f"Chapter-by-Chapter Revision Feedback:\n"
                    f"{all_feedback}"
                )

                print(
                    f"✅ All {len(chapters)} chapters revised individually and assembled"
                )

            except _StepSkipped:
                # Intentional skip for non-teaching archetypes — use the
                # combined (unreviewed) chapters directly.
                review_skipped = True
                complete_revised_script_content = combined_script
                script_review = f"Review skipped for '{script_format}' format"
            except Exception as review_error:
                # Script Review failed or timed out - skip and use combined chapters
                review_skipped = True
                error_msg = str(review_error)
                print(
                    f"\n⚠️  Script Review failed or timed out: {error_msg[:100]}")
                print("✅ FALLBACK: Skipping review and using combined chapters directly")
                complete_revised_script_content = combined_script
                script_review = "Script review skipped due to timeout/error"

            # Ensure we have content to proceed
            if not complete_revised_script_content:
                print("⚠️  No revised script content available, using combined chapters")
                complete_revised_script_content = combined_script

            review_end = get_timestamp()
            if review_skipped:
                print(
                    f"⏭️  Script Review skipped [{review_end}] - continuing with original script")
            else:
                print(f"✅ Script Review completed [{review_end}]")

            # STEP 3.5: Quotes & Statistics Generation (NEW - after review, before hooks)
            # Teaching-only step — the predictions / list archetypes do not
            # append a "SUPPORTING RESEARCH" quotes/stats section.
            quotes_and_stats_text = ""
            quotes_stats_start = get_timestamp()
            if is_teaching:
                print(
                    f"\n📊 STEP 3.5: Quotes & Statistics Generation [{quotes_stats_start}]")
                print("-" * 50)
            else:
                print(
                    f"\n⏭️  STEP 3.5: Quotes & Statistics SKIPPED for "
                    f"'{script_format}' format")
            try:
                if not is_teaching:
                    raise _StepSkipped()
                from linedrive_azure.agents.quote_and_statistics_agent_client import (
                    ScriptQuotesAndStatisticsAgentClient
                )

                quotes_agent = ScriptQuotesAndStatisticsAgentClient()
                quotes_result = quotes_agent.generate_quotes_and_statistics(
                    script_content=complete_revised_script_content,
                    script_title=script_topic,
                    target_audience=audience,
                    tone=tone,
                    timeout=180
                )

                quotes_stats_end = get_timestamp()
                if quotes_result["success"]:
                    quotes_and_stats_text = quotes_result.get(
                        "raw_response", "")
                    print(
                        f"✅ Quotes & Statistics generated ({len(quotes_and_stats_text)} chars) [{quotes_stats_end}]")
                else:
                    print(
                        f"⚠️  Quotes/Stats generation failed: {quotes_result.get('error', 'Unknown error')}")
                    print("✅ Continuing workflow without quotes/stats section")

            except _StepSkipped:
                pass  # non-teaching archetype — no quotes/stats section
            except Exception as quotes_error:
                print(
                    f"⚠️  Exception in Quotes/Stats generation: {quotes_error}")
                print("✅ Continuing workflow without quotes/stats section")

            # STEP 4: Hook-and-Summary Generation (runs regardless of review status)
            hook_text = ""
            summary_text = ""
            thumbnail_hook_text = ""
            thumbnail_hook_text_options = []
            hook_summary_result = {"success": False, "error": "hook_summary not requested"}

            if not hook_summary:
                print("\n⏭️  STEP 4: Hook & Summary Generation SKIPPED (hook_summary checkbox not selected)")
            else:
                print("🔍 DEBUG: Reached Hook-and-Summary section!")
                print(
                    f"🔍 DEBUG: complete_revised_script_content length: {len(complete_revised_script_content)}")
                hook_summary_start = get_timestamp()
                print(
                    f"\n🎯 STEP 4: Hook & Summary Generation [{hook_summary_start}]")
                print("-" * 50)

                try:
                    print("🔍 DEBUG: About to call generate_hook_and_summary...")
                    hook_summary_result = self.hook_and_summary_client.generate_hook_and_summary(
                        script_content=complete_revised_script_content,
                        script_title=script_topic,
                        target_audience=audience,
                        tone=tone,
                        video_length=script_length,
                        timeout=120
                    )

                    hook_summary_end = get_timestamp()
                    if hook_summary_result["success"]:
                        # Extract all 3 hooks (with backward compatibility)
                        hook1_text = hook_summary_result.get(
                            "hook1", hook_summary_result.get("hook", ""))
                        hook2_text = hook_summary_result.get("hook2", "")
                        hook3_text = hook_summary_result.get("hook3", "")
                        summary_text = hook_summary_result.get("summary", "")
                        flow_analysis = hook_summary_result.get(
                            "flow_analysis", "")
                        thumbnail_hook_text = (hook_summary_result.get("thumbnail_hook_text") or "").strip()
                        thumbnail_hook_text_options = hook_summary_result.get("thumbnail_hook_text_options") or []

                        # Log each hook generation
                        if hook1_text:
                            print(
                                f"✅ Hook 1 generated ({len(hook1_text)} chars) [{hook_summary_end}]")
                        if hook2_text:
                            print(
                                f"✅ Hook 2 generated ({len(hook2_text)} chars) [{hook_summary_end}]")
                        if hook3_text:
                            print(
                                f"✅ Hook 3 generated ({len(hook3_text)} chars) [{hook_summary_end}]")
                        if summary_text:
                            print(
                                f"✅ Summary generated ({len(summary_text)} chars) [{hook_summary_end}]")
                        if thumbnail_hook_text:
                            print(
                                f"✅ Thumbnail hook text generated: '{thumbnail_hook_text}' [{hook_summary_end}]")
                        if thumbnail_hook_text_options:
                            print(
                                f"✅ Thumbnail hook options generated: {thumbnail_hook_text_options} [{hook_summary_end}]")
                        else:
                            print("⚠️ Thumbnail hook text missing from Hook-and-Summary output")

                        # Display flow analysis if available
                        if flow_analysis:
                            print("\n📊 Flow Analysis Between Chapters:")
                            print("-" * 50)
                            print(flow_analysis)
                            print("-" * 50)

                        # Insert hooks at the beginning and summary at the end
                        if hook1_text:
                            hook_section = "\n" + "=" * 80 + "\n"
                            hook_section += "# 🎬 OPENING HOOK OPTIONS\n"
                            hook_section += "=" * 80 + "\n\n"
                            hook_section += "*Choose one of these three hooks for your video:*\n\n"
                            hook_section += f"**OPTION 1:**\n\n{hook1_text}\n\n---\n\n"
                            if hook2_text:
                                hook_section += f"**OPTION 2:**\n\n{hook2_text}\n\n---\n\n"
                            if hook3_text:
                                hook_section += f"**OPTION 3:**\n\n{hook3_text}\n\n---\n\n"
                            complete_revised_script_content = hook_section + complete_revised_script_content
                            hook_count = 1 + (1 if hook2_text else 0) + \
                                (1 if hook3_text else 0)
                            print(
                                f"✅ {hook_count} hook option(s) prepended to script")

                        # NOTE: Quotes & Statistics insertion moved OUTSIDE this
                        # hook-success branch so it is appended even when Hook-and-Summary
                        # fails. See block after the outer try/except.

                        if summary_text:
                            summary_section = f"""

---

## 📝 SUMMARY/CONCLUSION (30-45 seconds)

{summary_text}
"""
                            complete_revised_script_content = complete_revised_script_content + summary_section
                            print("✅ Summary appended to script")
                    else:
                        print(
                            f"⚠️ Hook-and-Summary generation failed: {hook_summary_result.get('error')}")
                        print("⚠️ Continuing without hook and summary")

                except Exception as hook_error:
                    print(f"⚠️ Hook-and-Summary error: {hook_error}")
                    print("⚠️ Continuing without hook and summary")

            # Insert Quotes & Statistics section (if available) — runs regardless
            # of Hook-and-Summary success/failure so generated quotes are never lost.
            if quotes_and_stats_text:
                quotes_section = "\n" + "=" * 80 + "\n"
                quotes_section += "# 📊 SUPPORTING RESEARCH & EXPERT PERSPECTIVES\n"
                quotes_section += "=" * 80 + "\n\n"
                quotes_section += quotes_and_stats_text + "\n\n"
                complete_revised_script_content = complete_revised_script_content + \
                    "\n\n" + quotes_section
                print("✅ Quotes & Statistics section inserted into script")

            # Format final document
            final_script = self._format_sequential_workflow_result(
                script_topic,
                audience,
                tone,
                script_length,
                topic_enhancement,
                complete_revised_script_content,
                script_review,
            )

            workflow_end = get_timestamp()
            print(f"\n🎉 SEQUENTIAL WORKFLOW COMPLETED! [{workflow_end}]")
            print(
                f"✅ All 5 agents executed successfully - {len(chapters)} chapters with hook & summary"
            )
            print(f"⏱️ Total time: {start_time} → {workflow_end}")

            # Display and save reviewer feedback summary
            if revision_feedback:
                try:
                    print("\n" + "=" * 80)
                    print("📋 REVIEW FEEDBACK SUMMARY")
                    print("=" * 80)
                    print(f"Total chapters reviewed: {len(revision_feedback)}")

                    # Save full feedback to file
                    import datetime
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    feedback_file = f"reviewer_feedback_{timestamp}.txt"

                    with open(feedback_file, 'w') as f:
                        f.write("=" * 80 + "\n")
                        f.write("SCRIPT REVIEW FEEDBACK - COMPLETE LOG\n")
                        f.write("=" * 80 + "\n")
                        f.write(f"Topic: {script_topic}\n")
                        f.write(f"Audience: {audience}\n")
                        f.write(f"Tone: {tone}\n")
                        f.write(f"Timestamp: {timestamp}\n")
                        f.write(f"Total Chapters: {len(revision_feedback)}\n\n")

                        for item in revision_feedback:
                            if isinstance(item, dict):
                                chapter_num = item.get('chapter', '?')
                                feedback = item.get('feedback', '')
                                length = item.get('length', len(str(feedback)))
                            else:
                                chapter_num = '?'
                                feedback = str(item)
                                length = len(feedback)

                            f.write("\n" + "=" * 80 + "\n")
                            f.write(
                                f"CHAPTER {chapter_num} - REVIEW FEEDBACK ({length} chars)\n")
                            f.write("=" * 80 + "\n")
                            f.write(feedback + "\n")

                        f.write("\n" + "=" * 80 + "\n")
                        f.write("END OF REVIEW FEEDBACK LOG\n")
                        f.write("=" * 80 + "\n")

                    print(f"✅ Full review feedback saved to: {feedback_file}")
                    print("=" * 80)
                    sys.stdout.flush()
                except Exception as fb_error:
                    print(f"⚠️ Failed to write review feedback file: {fb_error}")
                    print("✅ Continuing - script content is unaffected")

            # Generate chapter comparison report (Original vs Revised)
            if chapter_comparisons:
                try:
                    print("\n" + "=" * 80)
                    print("📊 GENERATING CHAPTER COMPARISON REPORT")
                    print("=" * 80)

                    import datetime
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    comparison_file = f"chapter_comparison_{timestamp}.md"

                    with open(comparison_file, 'w', encoding='utf-8') as f:
                        # Header
                        f.write(f"# Chapter Comparison Report\n\n")
                        f.write(f"**Topic:** {script_topic}  \n")
                        f.write(f"**Audience:** {audience}  \n")
                        f.write(f"**Tone:** {tone}  \n")
                        f.write(f"**Generated:** {timestamp}  \n")
                        f.write(
                            f"**Total Chapters:** {len(chapter_comparisons)}  \n\n")
                        f.write("---\n\n")

                        # Table of contents
                        f.write("## Table of Contents\n\n")
                        for comp in chapter_comparisons:
                            f.write(
                                f"- [Chapter {comp['chapter_num']}](#chapter-{comp['chapter_num']})\n")
                        f.write("\n---\n\n")

                        # Each chapter comparison
                        for comp in chapter_comparisons:
                            chapter_num = comp['chapter_num']
                            original = comp['original']
                            revised = comp['revised']
                            feedback = comp['feedback']

                            f.write(f"## Chapter {chapter_num}\n\n")

                            # Feedback section
                            f.write(f"### 📝 Reviewer Feedback\n\n")
                            f.write(f"```\n{feedback}\n```\n\n")

                            # Comparison section - use code blocks, not tables
                            f.write("### 📊 Comparison\n\n")

                            f.write("#### 📄 Original Version\n\n")
                            f.write("```\n")
                            f.write(original)
                            f.write("\n```\n\n")

                            f.write("#### ✏️ Revised Version\n\n")
                            f.write("```\n")
                            f.write(revised)
                            f.write("\n```\n\n")

                            f.write("\n---\n\n")

                        # Summary
                        f.write(f"## Summary\n\n")
                        f.write(
                            f"- **Total Chapters Reviewed:** {len(chapter_comparisons)}\n")
                        f.write(f"- **Report Generated:** {timestamp}\n")
                        f.write(
                            f"- **Bold text** indicates changes made by the reviewer\n\n")

                    print(
                        f"✅ Chapter comparison report saved to: {comparison_file}")
                    print("=" * 80)
                    sys.stdout.flush()

                    # Store the file path for UI to display
                    comparison_file_path = comparison_file
                except Exception as comp_error:
                    print(f"⚠️ Failed to write chapter comparison report: {comp_error}")
                    print("✅ Continuing - script content is unaffected")

            return {
                "success": True,
                "script_content": final_script,
                "workflow_type": "sequential_4_agent_chapters",
                "topic_enhancement": topic_enhancement,
                "chapter_scripts": all_chapter_scripts,
                "combined_script": combined_script,
                "script_review": script_review,
                "thumbnail_hook_text": thumbnail_hook_text,
                "thumbnail_hook_text_options": thumbnail_hook_text_options,
                "chapters_count": len(chapters),
                "target_minutes_per_chapter": minutes_per_chapter,
                "comparison_file": comparison_file_path if chapter_comparisons else None,
                "chapter_comparisons": chapter_comparisons if chapter_comparisons else None,
            }

        except Exception as e:
            print(f"❌ Sequential workflow error: {e}")
            return {"success": False, "error": str(e)}

    async def run_complete_script_workflow(
        self,
        script_topic: str,
        audience: str = "general audience",
        tone: str = "conversational and educational",
        script_length: str = "5-8 minutes (800-1200 words)",
    ) -> Dict[str, Any]:
        """
        Complete 4-Agent Workflow: Topic Assistant → Script Writer → Script Reviewer → Demo Generator

        Args:
            script_topic: The topic to develop into a script
            audience: Target audience for the script (e.g., "beginners", "developers", "students")
            tone: Desired tone/style (e.g., "conversational", "professional", "educational")

        1. Topic Assistant: Analyzes and enhances the topic, creates chapter breakdown
        2. Script Writer: Creates comprehensive script based on enhanced topic plan
        3. Script Reviewer: Reviews and provides feedback on the script
        4. Demo Generator: Creates demo packages from the final script
        """
        try:
            print(f"🚀 COMPLETE 4-AGENT WORKFLOW: {script_topic}")
            print(f"👥 Target Audience: {audience}")
            print(f"💬 Tone: {tone}")
            print("=" * 60)

            if self.verbose:
                print(
                    "🔧 AUTOGEN WORKFLOW TRACE: Starting complete 4-agent " "workflow"
                )
                print(
                    "🤖 AUTOGEN WORKFLOW TRACE: This is using FULL AutoGen "
                    "orchestration"
                )
                print(
                    "🎯 AUTOGEN WORKFLOW TRACE: NO fallback systems - "
                    "pure AutoGen RoundRobinGroupChat"
                )

            # Step 1: Topic Enhancement with Topic Assistant
            print("\n📋 STEP 1: Topic Enhancement & Chapter Planning")
            print("-" * 50)

            if self.verbose:
                print(
                    "🔧 AUTOGEN WORKFLOW TRACE: Creating specialized "
                    "AutoGen agents..."
                )

            # Create agents with script length parameter
            agents = [
                AssistantAgent(
                    name="TopicAssistant",
                    model_client=self.script_topic_assistant_model,
                    system_message=f"""
                    You are a Topic Assistant specializing in content planning and topic enhancement.
                    
                    Your role in this workflow:
                    1. Analyze the provided topic and enhance it with detailed structure
                    2. Create a comprehensive chapter breakdown for {script_length}
                    3. Identify key points, learning objectives, and content flow
                    4. Provide timing guidance to achieve target length
                    
                    When you complete your analysis, end with "TOPIC_ANALYSIS_COMPLETE"
                    and provide a detailed topic enhancement plan for the Script Writer to use.
                    """,
                ),
                AssistantAgent(
                    name="ScriptWriter",
                    model_client=self.script_writer_model,
                    system_message=f"""
                    You are a Script Writer specializing in creating comprehensive video scripts.
                    
                    Your role in this workflow:
                    1. Wait for the Topic Assistant to provide the enhanced topic plan
                    2. Create a detailed video script targeting {script_length}
                    3. Use the specified tone and ensure content suits the target audience
                    4. Include chapter headings and visual cues
                    
                    CRITICAL FORMAT REQUIREMENTS:
                    - Start each chapter with: "Heading: Chapter X - [Chapter Title]" (where X is the chapter number)
                    - Follow with: "Visual Cue: [Describe what visual/image/video should be shown]"
                    - Then provide: "**Host:**" followed by the dialogue content
                    - Visual cues should describe actual visuals, not just repeat the chapter title
                    - Example: "Visual Cue: Show a king ruling over his kingdom" not "Visual Cue: Debunking AI Myths"
                    
                    When you complete your script, end with "SCRIPT_WRITER_COMPLETE"
                    """,
                ),
                AssistantAgent(
                    name="ScriptReviewer",
                    model_client=self.script_review_model,
                    system_message=f"""
                    You are a Script Reviewer specializing in content analysis and improvement.
                    
                    Your role:
                    1. Review the script for length targeting {script_length}
                    2. Check tone consistency and audience appropriateness  
                    3. Suggest improvements and provide final polished version
                    4. Ensure the script meets all requirements
                    
                    When you finish your review, end with "SCRIPT_REVIEW_COMPLETE"
                    """,
                ),
            ]

            if self.verbose:
                print(
                    f"✅ AUTOGEN WORKFLOW TRACE: Created {len(agents)} "
                    f"AutoGen AssistantAgent instances"
                )
                for i, agent in enumerate(agents):
                    print(
                        f"   Agent {i+1}: {agent.name} "
                        f"(type: {type(agent).__name__})"
                    )

            if self.verbose:
                print(
                    "🔧 AUTOGEN WORKFLOW TRACE: Creating " "RoundRobinGroupChat team..."
                )
            team = RoundRobinGroupChat(
                agents, max_turns=4
            )  # Exactly 4 turns for 4 agents
            if self.verbose:
                print(
                    "✅ AUTOGEN WORKFLOW TRACE: RoundRobinGroupChat "
                    "created with max_turns=4"
                )
                print(f"   Team type: {type(team).__name__}")
                print(f"   Number of agents in team: {len(agents)}")

            # Create the coordinated task message
            initial_message = TextMessage(
                content=f"""
COMPLETE SCRIPT CREATION WORKFLOW REQUEST: {script_topic}
                
                SCRIPT REQUIREMENTS:
                - Target Audience: {audience}
                - Desired Tone/Style: {tone}
                - Script Length: {script_length}
                - Topic: {script_topic}
                
                Please execute this 4-step workflow with SINGLE responses only:
                
                1. TopicAssistant: Create enhanced topic plan with detailed structure for "{script_topic}" targeting {audience} with {tone} tone. Include timing guidance for {script_length}. End with "TOPIC_ANALYSIS_COMPLETE".
                
                2. ScriptWriter: Write complete script based on the topic plan. Target length: {script_length}. Use {tone} tone for {audience}. End with "SCRIPT_WRITER_COMPLETE".
                
                3. ScriptReviewer: Review and provide final polished version of the script. Ensure it meets {script_length} target and serves {audience} effectively. End with "SCRIPT_REVIEW_COMPLETE".
                
                4. Final result: Completed, reviewed script ready for demo generation
                
                IMPORTANT: Each agent responds ONCE only. No additional responses after completion markers.
                """,
                source="User",
            )

            if self.verbose:
                print(
                    "🔄 AUTOGEN WORKFLOW TRACE: Executing team.run() "
                    "with RoundRobinGroupChat..."
                )
                print(
                    f"🔄 AUTOGEN WORKFLOW TRACE: Initial message length: "
                    f"{len(initial_message.content)} chars"
                )
                print(
                    f"🔄 AUTOGEN WORKFLOW TRACE: Team participants: "
                    f"{[agent.name for agent in agents]}"
                )
                print("🔄 AUTOGEN WORKFLOW TRACE: Max turns: 6")

            result = await team.run(task=initial_message)

            if self.verbose:
                print(
                    "✅ AUTOGEN WORKFLOW TRACE: team.run() completed " "successfully!"
                )
                print(
                    f"✅ AUTOGEN WORKFLOW TRACE: Result type: "
                    f"{type(result).__name__}"
                )
                print(
                    f"✅ AUTOGEN WORKFLOW TRACE: Number of messages "
                    f"in result: {len(result.messages) if hasattr(result, 'messages') else 'N/A'}"
                )

            # Show each message in the result
            if self.verbose and hasattr(result, "messages") and result.messages:
                print("🎭 AUTOGEN WORKFLOW TRACE: Message breakdown:")
                for i, msg in enumerate(result.messages):
                    print(
                        f"   📝 Message {i+1}: {msg.source} → "
                        f"{len(msg.content)} chars"
                    )
                    print(f"      🏷️  Type: {type(msg).__name__}")
            elif self.verbose:
                print("🎭 AUTOGEN WORKFLOW TRACE: No messages array " "found in result")
                print(
                    f"   🔍 Result attributes: "
                    f"{dir(result) if hasattr(result, '__dict__') else 'Not inspectable'}"
                )

            # Extract the final script from the workflow
            if self.verbose:
                print("🔧 AUTOGEN WORKFLOW TRACE: Formatting workflow result...")
            script_content = self._format_complete_script_result(result)
            if self.verbose:
                print(
                    f"✅ AUTOGEN WORKFLOW TRACE: Script content length: "
                    f"{len(script_content)} characters"
                )

            # Step 2: Generate demo packages using the script (optional)
            print(f"\n🎥 STEP 2: Demo Package Generation")
            print("-" * 50)

            demo_packages = ""
            developer_demos = ""
            everyday_demos = ""

            try:
                from .openai_demo_agent_client import OpenAIDemoAgentClient

                demo_client = OpenAIDemoAgentClient()

                demo_result = demo_client.generate_demo_packages(
                    script_content, audience=audience
                )

                if demo_result.get("success"):
                    demo_packages = demo_result["response"]
                    print(
                        f"✅ Demo packages created ({len(demo_packages)} characters)")

                    # Step 3: Split into developer and everyday sections
                    print("\n📁 STEP 3: Splitting Demo Packages")
                    print("-" * 50)

                    split_marker = "2) EVERYDAY-VIEWER DEMO PACKAGE"
                    split_index = demo_packages.find(split_marker)

                    if split_index != -1:
                        developer_demos = demo_packages[:split_index].strip()
                        everyday_demos = demo_packages[split_index:].strip()
                        print(
                            "✅ Successfully split into developer and everyday sections"
                        )
                    else:
                        developer_demos = demo_packages
                        everyday_demos = "No everyday viewer section found."
                        print("⚠️ Could not split demo sections")
                else:
                    print(
                        f"⚠️ Demo generation failed: {demo_result.get('error', 'Unknown error')}"
                    )
                    print("📝 Script content is still available without demos")

            except Exception as demo_error:
                print(f"⚠️ Demo generation skipped: {demo_error}")
                print("📝 Script content is still available without demos")

            # Return results (with or without demos)
            return {
                "success": True,
                "script_content": script_content,
                "demo_packages": demo_packages,
                "developer_demos": developer_demos,
                "everyday_demos": everyday_demos,
                "topic": script_topic,
                "audience": audience,
                "tone": tone,
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                "workflow_type": "complete_4_agent",
                "has_demos": bool(demo_packages),
            }

        except Exception as e:
            print(f"❌ Complete workflow error: {e}")
            return {"success": False, "error": str(e)}

    def create_complete_script_workflow_agents(self) -> List[AssistantAgent]:
        """Create agents for complete 4-agent script workflow: Topic Assistant → Script Writer → Script Reviewer → Demo Generation"""
        if self.verbose:
            print("🔧 AUTOGEN AGENT TRACE: Creating complete script " "workflow agents")

        agents = [
            AssistantAgent(
                name="TopicAssistant",
                model_client=self.script_topic_assistant_model,
                system_message="""
                You are a Topic Assistant specializing in content planning and topic enhancement.
                
                Your role in this workflow:
                1. Analyze the provided topic and enhance it with detailed structure
                2. Create a comprehensive chapter breakdown and content plan
                3. Identify key points, learning objectives, and content flow
                4. Provide detailed guidance for the Script Writer
                
                When you complete your topic analysis and planning, say "TOPIC_ANALYSIS_COMPLETE"
                and provide a detailed topic enhancement plan for the Script Writer to use.
                """,
            ),
            AssistantAgent(
                name="ScriptWriter",
                model_client=self.script_writer_model,
                system_message="""
                You are a Script Writer specializing in creating comprehensive video scripts.
                
                Your role in this workflow:
                1. Wait for the Topic Assistant to provide the enhanced topic plan
                2. Create a detailed, comprehensive video script based on the topic plan
                3. Include all elements from the topic breakdown and structure
                4. Create engaging content that follows the recommended flow and chapters
                
                When you complete your script, say "SCRIPT_WRITER_COMPLETE" to signal the reviewer.
                """,
            ),
            AssistantAgent(
                name="ScriptReviewer",
                model_client=self.script_review_model,
                system_message="""
                You are a Script Reviewer specializing in content analysis and improvement.
                
                Your role in this workflow:
                1. Wait for the Script Writer to complete the script
                2. Review the script for quality, accuracy, and effectiveness
                3. Provide detailed feedback and suggestions for improvement
                4. Ensure the script meets the original topic requirements
                
                When you finish your review, say "SCRIPT_REVIEW_COMPLETE" with your final assessment.
                """,
            ),
        ]

        if self.verbose:
            print("✅ AUTOGEN AGENT TRACE: Agent creation details:")
            for i, agent in enumerate(agents):
                model_client_type = type(agent._model_client).__name__
                print(f"   Agent {i+1}: {agent.name}")
                print(f"      Type: {type(agent).__name__}")
                print(f"      Model Client: {model_client_type}")
                print(
                    f"      Agent Client: "
                    f"{type(agent._model_client.agent_client).__name__}"
                )

            print(
                "🎯 AUTOGEN AGENT TRACE: All agents use AutoGen "
                "AssistantAgent with LineDriveAgentModelClient"
            )
        return agents

    async def run_script_to_demo_workflow(
        self, script_topic: str, audience: str = "general"
    ) -> Dict[str, Any]:
        """
        Complete workflow: Script Creation → Demo Generation

        1. Use AutoGen multi-agent system to create script content
        2. Feed the generated script to the demo creation agent
        3. Return both script and demo packages
        """
        try:
            print(f"🚀 COMPLETE SCRIPT-TO-DEMO WORKFLOW: {script_topic}")
            print("=" * 60)

            # Step 1: Generate script using AutoGen multi-agent system
            print("\n🎬 STEP 1: AutoGen Script Creation")
            print("-" * 40)
            script_content = await self.run_script_workflow(script_topic)
            print(f"✅ Script created ({len(script_content)} characters)")

            # Step 2: Generate demo packages using the script
            print("\n🎥 STEP 2: Demo Package Generation")
            print("-" * 40)

            from .openai_demo_agent_client import OpenAIDemoAgentClient

            demo_client = OpenAIDemoAgentClient()

            demo_result = demo_client.generate_demo_packages(
                script_content, audience=audience
            )

            if demo_result.get("success"):
                demo_packages = demo_result["response"]
                print(
                    f"✅ Demo packages created ({len(demo_packages)} characters)")

                # Step 3: Split into developer and everyday sections
                print("\n📁 STEP 3: Splitting Demo Packages")
                print("-" * 40)

                split_marker = "2) EVERYDAY-VIEWER DEMO PACKAGE"
                split_index = demo_packages.find(split_marker)

                if split_index != -1:
                    dev_demos = demo_packages[:split_index].strip()
                    everyday_demos = demo_packages[split_index:].strip()
                    print("✅ Successfully split into developer and everyday sections")
                else:
                    dev_demos = demo_packages
                    everyday_demos = "No everyday viewer section found."
                    print("⚠️ Could not split demo sections")

                return {
                    "success": True,
                    "script_content": script_content,
                    "demo_packages": demo_packages,
                    "developer_demos": dev_demos,
                    "everyday_demos": everyday_demos,
                    "topic": script_topic,
                    "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                }
            else:
                return {
                    "success": False,
                    "error": demo_result.get("error", "Demo generation failed"),
                    "script_content": script_content,
                }

        except Exception as e:
            print(f"❌ Workflow error: {e}")
            return {"success": False, "error": str(e)}

    def get_available_workflows(self) -> Dict[str, str]:
        """Get information about available workflows"""
        return {
            "tournament": "Tournament search + Social media content creation",
            "script": "Script writing + Review and feedback",
            "complete_script": "Complete 4-Agent: Topic Assistant → Script Writer → Script Reviewer → Demo Generator",
            "script_to_demo": "Complete Script Creation → Demo Package Generation workflow",
            "full_content": "Complete content pipeline: Tournament search → Script writing → Review → Social media optimization",
        }

    def get_agent_info(self) -> Dict[str, Dict[str, Any]]:
        """Get information about all available agents"""
        return {
            "tournament": self.tournament_client.get_specialized_info(),
            "ai_tips": self.ai_tips_client.get_specialized_info(),
            "script_writer": self.script_writer_client.get_specialized_info(),
            "script_review": self.script_review_client.get_specialized_info(),
        }

    async def health_check(self) -> Dict[str, Dict[str, Any]]:
        """Perform health check on all agents"""
        return {
            "tournament": self.tournament_client.health_check(),
            "ai_tips": self.ai_tips_client.health_check(),
            "script_writer": self.script_writer_client.health_check(),
            "script_review": self.script_review_client.health_check(),
        }
