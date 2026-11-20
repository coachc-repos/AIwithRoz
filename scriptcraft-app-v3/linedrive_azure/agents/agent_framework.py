"""
True Microsoft AutoGen Tournament Multi-Agent System
Uses real AutoGen framework components:
- AssistantAgent for each tournament agent
- RoundRobinGroupChat for orchestration
- Custom model clients for LineDrive and Grok backends
"""

import os
import sys
import asyncio
import aiohttp
from datetime import datetime
from typing import Dict, Any, List, Optional, Sequence, Mapping, AsyncGenerator, Union
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

# Add the current directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from agent_client import LinedriveAgentClient
except ImportError as e:
    print(f"Error: Could not import agent_client: {e}")
    sys.exit(1)


class LineDriveModelClient(ChatCompletionClient):
    """Custom AutoGen model client for LineDrive Agent"""

    def __init__(self):
        self.linedrive_client = None  # Initialize lazily
        self.thread_id = None
        self._total_usage = RequestUsage(prompt_tokens=0, completion_tokens=0)

    def _get_client(self):
        """Lazy initialization of LineDrive client"""
        if self.linedrive_client is None:
            self.linedrive_client = LinedriveAgentClient()
        return self.linedrive_client

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
        """Return model information as dict (required by AutoGen)"""
        return {
            "model_name": "linedrive-agent",
            "model_family": "unknown",
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
        return max(0, self.model_info.context_length - used)

    def actual_usage(self) -> RequestUsage:
        """Return actual usage"""
        return self._total_usage

    def total_usage(self) -> RequestUsage:
        """Return total usage"""
        return self._total_usage

    async def close(self) -> None:
        """Close the client"""
        pass

    async def create(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = [],
        tool_choice: Any = "auto",
        json_output: Optional[bool] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: Optional[CancellationToken] = None,
    ) -> CreateResult:
        """Create chat completion using LineDrive Agent"""
        agent_start = datetime.now()
        print(
            f"🔍 LineDrive Agent started at: {agent_start.strftime('%H:%M:%S.%f')[:-3]}"
        )

        try:
            # Initialize thread if needed
            if not self.thread_id:
                client = self._get_client()
                thread = client.create_thread()
                if thread:
                    self.thread_id = thread.id
                else:
                    raise Exception("Could not create LineDrive thread")

            # Get the last message (user input) and enhance for tournament search
            if messages:
                last_message = messages[-1]
                if hasattr(last_message, "content"):
                    original_prompt = last_message.content
                else:
                    original_prompt = str(last_message)
            else:
                original_prompt = "Hello"

            # Enhance prompt to specifically request tournament listings
            enhanced_prompt = f"""
{original_prompt}

IMPORTANT: Please provide specific tournament listings with the following details for each tournament:
- Tournament name and organization
- Dates and times
- Location (field address if available)
- Age group/division
- Registration deadline
- Contact information or website
- Entry fees if available

Format the response as a clear list of tournaments, not just general information.
"""

            # Call LineDrive agent with enhanced prompt
            client = self._get_client()
            result = client.chat(enhanced_prompt, self.thread_id)

            if result.get("response"):
                response = result["response"]

                # Enhance response with tournament data formatting
                if (
                    "tournament" in response.lower()
                    or "perfect game" in response.lower()
                ):
                    # Add clear tournament data header if missing
                    if not response.startswith("🏆"):
                        response = f"🏆 **TOURNAMENT SEARCH RESULTS**\n\n{response}"

                    # Ensure sources are included if available
                    if result.get("sources"):
                        sources_text = "\n\n📋 **TOURNAMENT SOURCES:**\n"
                        for i, source in enumerate(result["sources"], 1):
                            source_title = source.get("title", f"Source {i}")
                            sources_text += f"   {i}. {source_title}\n"
                        response += sources_text
                if result.get("sources"):
                    response += f"\n\n📚 **Data Sources ({len(result['sources'])} references):**"
                    for i, source in enumerate(result["sources"][:3], 1):
                        response += f"\n{i}. {source}"
                    if len(result["sources"]) > 3:
                        response += (
                            f"\n... and {len(result['sources']) - 3} more sources"
                        )

                # Update usage tracking
                prompt_tokens = len(enhanced_prompt.split())
                completion_tokens = len(response.split())
                usage = RequestUsage(
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
                )
                self._total_usage = RequestUsage(
                    prompt_tokens=self._total_usage.prompt_tokens + prompt_tokens,
                    completion_tokens=self._total_usage.completion_tokens
                    + completion_tokens,
                )

                # Return AutoGen-compatible CreateResult
                agent_end = datetime.now()
                duration = (agent_end - agent_start).total_seconds()
                print(
                    f"✅ LineDrive Agent completed at: {agent_end.strftime('%H:%M:%S.%f')[:-3]} (took {duration:.2f}s)"
                )

                return CreateResult(
                    content=response, usage=usage, finish_reason="stop", cached=False
                )
            else:
                raise Exception(
                    f"LineDrive error: {result.get('error', 'Unknown error')}"
                )

        except Exception as e:
            # Return error response in AutoGen format
            agent_end = datetime.now()
            duration = (agent_end - agent_start).total_seconds()
            print(
                f"❌ LineDrive Agent failed at: {agent_end.strftime('%H:%M:%S.%f')[:-3]} (took {duration:.2f}s)"
            )

            error_msg = f"LineDrive Agent Error: {str(e)}"
            return CreateResult(
                content=error_msg,
                usage=RequestUsage(prompt_tokens=0, completion_tokens=0),
                finish_reason="unknown",
                cached=False,
            )

    async def create_stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = [],
        tool_choice: Any = "auto",
        json_output: Optional[bool] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: Optional[CancellationToken] = None,
    ) -> AsyncGenerator[Union[str, CreateResult], None]:
        """Create streaming chat completion - not supported by LineDrive"""
        result = await self.create(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            json_output=json_output,
            extra_create_args=extra_create_args,
            cancellation_token=cancellation_token,
        )
        yield result


class GrokModelClient(ChatCompletionClient):
    """Custom AutoGen model client for Azure-hosted Grok 3 Mini"""

    def __init__(self):
        self.api_url = os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT", "https://linedrive-ai-foundry.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview")
        self.api_key = os.environ.get("AZURE_AI_FOUNDRY_KEY", "")
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",  # Use Bearer auth like working version
        }
        self._total_usage = RequestUsage(prompt_tokens=0, completion_tokens=0)

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
        """Return model information as dict (required by AutoGen)"""
        return {
            "model_name": "grok-3-mini",
            "model_family": "unknown",
            "context_length": 16384,
            "max_tokens": 16000,
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

    async def close(self) -> None:
        """Close the client"""
        pass

    async def create(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = [],
        tool_choice: Any = "auto",
        json_output: Optional[bool] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: Optional[CancellationToken] = None,
    ) -> CreateResult:
        """Create chat completion using Grok 3 Mini"""
        agent_start = datetime.now()
        print(f"🚀 Grok Agent started at: {agent_start.strftime('%H:%M:%S.%f')[:-3]}")

        try:
            # Convert AutoGen messages to Grok format
            grok_messages = []
            combined_content = ""

            for msg in messages:
                if hasattr(msg, "content"):
                    content = msg.content
                else:
                    content = str(msg)

                # Combine all messages for Grok (it may not support role separation well)
                combined_content += f"{content}\n"

            payload = {
                "messages": [{"role": "user", "content": combined_content.strip()}],
                "max_completion_tokens": 500,  # Much smaller, reasonable limit
                "temperature": 0.7,
                "top_p": 1,
                "model": "grok-3-mini",
            }

            # Increase timeout for better reliability with Grok API
            timeout = aiohttp.ClientTimeout(total=30)  # Increased to 30 seconds

            try:
                print(f"🌐 Making aiohttp request to: {self.api_url}")
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        self.api_url, headers=self.headers, json=payload
                    ) as response:
                        print(f"📊 Response status: {response.status}")

                        if response.status == 200:
                            print(f"✅ Got 200 response, reading JSON...")
                            try:
                                result = await response.json()
                                print(f"✅ JSON parsed successfully")
                            except Exception as json_error:
                                print(f"❌ JSON parsing error: {json_error}")
                                text_content = await response.text()
                                print(
                                    f"❌ Raw response (first 200 chars): {text_content[:200]}"
                                )
                                raise json_error
                        else:
                            print(f"❌ HTTP Error {response.status}")
                            error_text = await response.text()
                            print(f"❌ Error details: {error_text}")
                            raise aiohttp.ClientResponseError(
                                request_info=response.request_info,
                                history=response.history,
                                status=response.status,
                                message=error_text,
                            )

            except asyncio.TimeoutError:
                agent_end = datetime.now()
                duration = (agent_end - agent_start).total_seconds()
                print(
                    f"⏰ Grok Agent timeout at: {agent_end.strftime('%H:%M:%S.%f')[:-3]} (took {duration:.2f}s)"
                )

                # Return a helpful response instead of error to keep conversation flowing
                error_msg = "I'm having connectivity issues with the Grok model right now. Let me provide some general tournament planning guidance instead.\n\nFor Perfect Game tournaments, I recommend:\n- Register early as spots fill quickly\n- Check Perfect Game website for specific tournament details\n- Plan to arrive 1-2 hours before first game\n- Bring plenty of water and snacks for the team"
                return CreateResult(
                    content=error_msg,
                    usage=RequestUsage(
                        prompt_tokens=len(combined_content.split()),
                        completion_tokens=len(error_msg.split()),
                    ),
                    finish_reason="stop",  # Use "stop" instead of "unknown" to indicate completion
                    cached=False,
                )
            except aiohttp.ClientError as e:
                agent_end = datetime.now()
                duration = (agent_end - agent_start).total_seconds()
                print(
                    f"🔌 Grok Agent connection error at: {agent_end.strftime('%H:%M:%S.%f')[:-3]} (took {duration:.2f}s)"
                )
                print(f"🔍 Error details: {e}")

                # Return a helpful response instead of error
                error_msg = "I'm experiencing connection issues right now. Here's some general tournament advice:\n\nFor 10U Perfect Game tournaments:\n- Focus on fundamentals and having fun\n- Ensure proper equipment and safety gear\n- Emphasize good sportsmanship\n- Stay hydrated and take breaks as needed"
                return CreateResult(
                    content=error_msg,
                    usage=RequestUsage(
                        prompt_tokens=len(combined_content.split()),
                        completion_tokens=len(error_msg.split()),
                    ),
                    finish_reason="stop",  # Use "stop" to indicate completion
                    cached=False,
                )
            except Exception as e:
                agent_end = datetime.now()
                duration = (agent_end - agent_start).total_seconds()
                print(
                    f"❌ Grok Agent unexpected error at: {agent_end.strftime('%H:%M:%S.%f')[:-3]} (took {duration:.2f}s)"
                )
                print(f"🔍 Error details: {e}")

                # Return a helpful response instead of error
                error_msg = f"Unexpected error occurred: {str(e)}"
                return CreateResult(
                    content=error_msg,
                    usage=RequestUsage(
                        prompt_tokens=len(combined_content.split()),
                        completion_tokens=len(error_msg.split()),
                    ),
                    finish_reason="stop",
                    cached=False,
                )

            # Handle Grok response format
            if "choices" in result and len(result["choices"]) > 0:
                response_choice = result["choices"][0]
                content = ""

                # Check different possible response formats for Grok
                if (
                    "message" in response_choice
                    and "content" in response_choice["message"]
                ):
                    content = response_choice["message"]["content"]
                    # If content is empty, check for reasoning_content (new Grok format)
                    if (
                        not content
                        and "reasoning_content" in response_choice["message"]
                    ):
                        content = response_choice["message"]["reasoning_content"]
                elif (
                    "message" in response_choice
                    and "reasoning_content" in response_choice["message"]
                ):
                    content = response_choice["message"]["reasoning_content"]
                elif "text" in response_choice:
                    content = response_choice["text"]
                elif "content" in response_choice:
                    content = response_choice["content"]

                if content:
                    # Add model attribution
                    content += f"\n\n🤖 *Powered by grok-3-mini*"

                    # Update usage tracking
                    prompt_tokens = len(combined_content.split())
                    completion_tokens = len(content.split())
                    usage = RequestUsage(
                        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
                    )
                    self._total_usage = RequestUsage(
                        prompt_tokens=self._total_usage.prompt_tokens + prompt_tokens,
                        completion_tokens=self._total_usage.completion_tokens
                        + completion_tokens,
                    )

                    # Return AutoGen-compatible CreateResult
                    agent_end = datetime.now()
                    duration = (agent_end - agent_start).total_seconds()
                    print(
                        f"✅ Grok Agent completed at: {agent_end.strftime('%H:%M:%S.%f')[:-3]} (took {duration:.2f}s)"
                    )

                    return CreateResult(
                        content=content, usage=usage, finish_reason="stop", cached=False
                    )

            # If we get here, the response format was unexpected
            agent_end = datetime.now()
            duration = (agent_end - agent_start).total_seconds()
            print(
                f"⚠️ Grok Agent unexpected response at: {agent_end.strftime('%H:%M:%S.%f')[:-3]} (took {duration:.2f}s)"
            )

            error_msg = f"Unexpected Grok response format: {result}"
            return CreateResult(
                content=error_msg,
                usage=RequestUsage(prompt_tokens=0, completion_tokens=0),
                finish_reason="unknown",
                cached=False,
            )

        except Exception as e:
            agent_end = datetime.now()
            duration = (agent_end - agent_start).total_seconds()
            print(
                f"❌ Grok Agent failed at: {agent_end.strftime('%H:%M:%S.%f')[:-3]} (took {duration:.2f}s)"
            )

            error_msg = f"Grok Model Error: {str(e)}"
            return CreateResult(
                content=error_msg,
                usage=RequestUsage(prompt_tokens=0, completion_tokens=0),
                finish_reason="unknown",
                cached=False,
            )

    async def create_stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = [],
        tool_choice: Any = "auto",
        json_output: Optional[bool] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: Optional[CancellationToken] = None,
    ) -> AsyncGenerator[Union[str, CreateResult], None]:
        """Create streaming chat completion - not supported by Grok"""
        result = await self.create(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            json_output=json_output,
            extra_create_args=extra_create_args,
            cancellation_token=cancellation_token,
        )
        yield result


class TournamentAutoGenSystem:
    """True AutoGen Tournament Multi-Agent System"""

    def __init__(self):
        self.linedrive_model = LineDriveModelClient()
        self.grok_model = GrokModelClient()
        self.agents = self._create_autogen_agents()
        self.team = self._create_team()

    def _create_autogen_agents(self) -> List[AssistantAgent]:
        """Create real AutoGen AssistantAgent instances - full 3-agent system"""

        # Agent 1: Tournament Finder (uses LineDrive)
        tournament_finder = AssistantAgent(
            name="TournamentFinder",
            model_client=self.linedrive_model,
            system_message="""
            You are a Tournament Finder specializing in helping teams find baseball tournaments.
            
            Your role: Search tournament databases and provide tournament details including dates, locations, competition level, and entry requirements.
            
            You have access to grounded tournament data through the LineDrive system.
            Provide real, current tournament information based on the search criteria.
            
            When you finish, end your response with "TOURNAMENT_FINDER_COMPLETE" on a new line.
            """,
        )

        # Agent 2: Tournament Planner (uses Grok)
        tournament_planner = AssistantAgent(
            name="TournamentPlanner",
            model_client=self.grok_model,
            system_message="""
            You are a Tournament Planner who helps teams prepare for and register for tournaments.
            
            Your expertise includes:
            - Providing registration guidance and links (especially Perfect Game registration)
            - Travel planning and distance calculations from team locations
            - Timeline recommendations for registration deadlines and travel preparation
            - Accommodation and logistics advice
            - Budget planning for tournament participation
            - Schedule coordination and conflict management
            
            When tournaments are found, help teams plan their participation including:
            - Step-by-step registration process
            - Travel time and route planning
            - Recommended departure times
            - Hotel and accommodation suggestions
            - What to prepare before leaving
            
            Wait for the TournamentFinder to complete before starting your work.
            When you finish planning, say "TOURNAMENT_PLANNER_COMPLETE" to signal the next agent.
            """,
        )

        # Agent 3: Tournament Advisor (uses Grok)
        tournament_advisor = AssistantAgent(
            name="TournamentAdvisor",
            model_client=self.grok_model,
            system_message="""
            You are a Tournament Advisor providing expert guidance on tournament rules and preparation.
            
            Your expertise includes:
            - Tournament-specific rules and regulations
            - Required and recommended equipment
            - Typical tournament schedules and formats
            - Training and preparation advice
            - Strategy recommendations for different tournament types
            - Age group and skill level considerations
            
            Based on the tournaments found and planning information, provide detailed advice about:
            - Specific rules for each tournament organization
            - Equipment requirements and recommendations
            - What to expect in terms of scheduling and game formats
            - How teams should prepare and train
            - Common challenges and how to overcome them
            
            Wait for both TournamentFinder and TournamentPlanner to complete before starting your work.
            Provide comprehensive final advice to conclude the tournament consultation.
            """,
        )

        return [tournament_finder, tournament_planner, tournament_advisor]

    def _create_team(self) -> RoundRobinGroupChat:
        """Create AutoGen RoundRobinGroupChat team with 3 agents and better termination"""
        return RoundRobinGroupChat(
            self.agents,
            max_turns=4,  # Reduced to prevent cycling - each agent gets 1 turn + 1 follow-up
        )

    async def process_tournament_request(self, request: str) -> str:
        """Process tournament request using true AutoGen framework"""
        start_time = datetime.now()
        timestamp = start_time.strftime("%H:%M:%S")

        print(f"🏆 True AutoGen Tournament Multi-Agent System")
        print(f"⏰ Started at: {timestamp}")
        print("=" * 60)
        print("Components: AssistantAgent + RoundRobinGroupChat")
        print(
            "Agents: TournamentFinder (LineDrive) → TournamentPlanner (Grok) → TournamentAdvisor (Grok)"
        )
        print("=" * 60)

        try:
            # Create initial message
            initial_message = TextMessage(
                content=f"""
            Tournament Request: {request}
            
            Please help me with this tournament request. I need:
            1. TournamentFinder: Find relevant tournaments using the LineDrive database
            2. TournamentPlanner: Provide planning and registration guidance  
            3. TournamentAdvisor: Give rules, equipment, and preparation advice
            
            Let's start with finding tournaments that match this request.
            """,
                source="User",
            )

            request_timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"\n📝 Processing Request at {request_timestamp}: {request}")
            print("=" * 50)
            print("🔄 AutoGen Agent Execution Flow:")
            print("   1. TournamentFinder (LineDrive) - Search tournaments")
            print("   2. TournamentPlanner (Grok) - Plan and logistics")
            print("   3. TournamentAdvisor (Grok) - Rules and preparation")

            # Run the AutoGen team
            result = await self.team.run(task=initial_message)

            end_time = datetime.now()
            end_timestamp = end_time.strftime("%H:%M:%S")
            duration = (end_time - start_time).total_seconds()

            print("\n" + "=" * 60)
            print(f"✅ AutoGen Tournament Processing Complete!")
            print(f"⏰ Finished at: {end_timestamp}")
            print(f"⏱️  Total Duration: {duration:.2f} seconds")
            print("=" * 60)

            # Collect and format all agent responses
            if result.messages:
                print(f"\n🔍 DEBUG: Found {len(result.messages)} messages")

                # Format comprehensive tournament response
                tournament_response = "🎯 **COMPREHENSIVE TOURNAMENT GUIDE**\n"
                tournament_response += "=" * 50 + "\n\n"

                # Extract responses from each agent - more flexible approach
                agent_responses = []

                # Collect all non-empty messages (excluding initial request)
                for i, msg in enumerate(result.messages):
                    content = msg.content.strip()
                    source = getattr(msg, "source", "Unknown")

                    print(
                        f"🔍 Message {i+1}: Source='{source}', Content length={len(content)}"
                    )

                    if (
                        content
                        and not content.startswith("Tournament Request:")
                        and len(content) > 50
                    ):
                        agent_responses.append(
                            {"content": content, "source": source, "index": i}
                        )
                        print(f"   ✅ Added response from {source}")

                # Display all agent responses in order
                for i, response in enumerate(agent_responses):
                    agent_name = f"Agent {i+1}"
                    if "finder" in response["source"].lower() or i == 0:
                        agent_name = "🔍 TournamentFinder (LineDrive)"
                    elif "planner" in response["source"].lower() or i == 1:
                        agent_name = "� TournamentPlanner (Grok)"
                    elif "advisor" in response["source"].lower() or i == 2:
                        agent_name = "🎯 TournamentAdvisor (Grok)"

                    tournament_response += f"{agent_name}\n"
                    tournament_response += "-" * 50 + "\n"
                    tournament_response += response["content"] + "\n\n"

                # If no responses found, show all messages for debugging
                if not agent_responses:
                    tournament_response += "🔍 **DEBUG: All Messages**\n"
                    tournament_response += "-" * 40 + "\n"
                    for i, msg in enumerate(result.messages):
                        tournament_response += (
                            f"Message {i+1}: {msg.content[:200]}...\n\n"
                        )

                return tournament_response
            else:
                return "No response generated"

        except Exception as e:
            error_time = datetime.now().strftime("%H:%M:%S")
            error_msg = f"AutoGen processing error: {str(e)}"
            print(f"❌ Error at {error_time}: {error_msg}")
            return error_msg

    async def run_tournament_workflow(self, query: str) -> str:
        """Run tournament workflow using AutoGen"""
        return await self.process_tournament_request(query)


async def test_autogen_tournament_system():
    """Test the true AutoGen tournament system"""
    try:
        print("🚀 Initializing True AutoGen Tournament System...")
        system = TournamentAutoGenSystem()

        # Test tournament request
        test_request = "Find baseball tournaments in Houston for 10U teams this month"

        print(f"\n📝 Test Request: {test_request}")
        print("=" * 50)

        result = await system.process_tournament_request(test_request)

        print(f"\n📊 AutoGen Result:")
        print("-" * 30)
        print(result)

        return result

    except Exception as e:
        print(f"Error during AutoGen tournament system test: {e}")
        return None


async def test_grok_connection():
    """Test Grok API connectivity with various timeout settings"""
    print("\n🧪 Testing Grok API Connection...")
    print("=" * 50)

    # Test with different timeout values
    timeout_values = [10, 20, 30, 45]

    for timeout_seconds in timeout_values:
        print(f"\n⏱️  Testing with {timeout_seconds}s timeout...")

        try:
            # Create a simple test payload
            api_url = os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT", "https://linedrive-ai-foundry.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {os.environ.get('AZURE_AI_FOUNDRY_KEY', '')}",
            }

            payload = {
                "messages": [
                    {
                        "role": "user",
                        "content": "Test connection - respond with 'Connection successful'",
                    }
                ],
                "max_completion_tokens": 50,
                "temperature": 0.1,
                "top_p": 1,
                "model": "grok-3-mini",
            }

            timeout = aiohttp.ClientTimeout(total=timeout_seconds)
            start_time = datetime.now()

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    api_url, headers=headers, json=payload
                ) as response:
                    end_time = datetime.now()
                    duration = (end_time - start_time).total_seconds()

                    print(f"   📊 Status: {response.status}")
                    print(f"   ⏰ Response time: {duration:.2f}s")

                    if response.status == 200:
                        result = await response.json()
                        if "choices" in result and len(result["choices"]) > 0:
                            content = result["choices"][0]["message"]["content"]
                            print(f"   ✅ Response: {content[:100]}...")
                            print(f"   🎯 Success with {timeout_seconds}s timeout!")
                            return timeout_seconds
                    else:
                        print(f"   ❌ HTTP Error: {response.status}")

        except asyncio.TimeoutError:
            print(f"   ⏰ Timeout after {timeout_seconds}s")
        except aiohttp.ClientError as e:
            print(f"   🔌 Connection error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")

    print("\n❌ All timeout tests failed")
    return None


def main():
    """Main entry point for true AutoGen system"""
    print("🏆 True Microsoft AutoGen Tournament Multi-Agent System")
    print("=" * 60)

    # Test connections
    try:
        system = TournamentAutoGenSystem()
        client = system.linedrive_model._get_client()
        agent_info = client.get_agent_info()
        print(f"✅ Connected to LineDrive Agent: {agent_info['name']}")
        print(f"   Agent ID: {agent_info['id']}")
    except Exception as e:
        print(f"❌ Could not connect to LineDrive Agent: {e}")
        return

    print("✅ AutoGen components loaded successfully")
    print("   - AssistantAgent")
    print("   - RoundRobinGroupChat")
    print("   - Custom model clients for LineDrive and Grok")

    # Handle command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "demo":
            print("\n🎯 Running AutoGen tournament demo...")
            test_request = "Find Perfect Game tournaments in California for 16U teams"
            asyncio.run(test_autogen_tournament_system())
        elif sys.argv[1] == "test":
            print("\n🧪 Testing AutoGen tournament system...")
            asyncio.run(test_autogen_tournament_system())
        elif sys.argv[1] == "test-grok":
            print("\n🧪 Testing Grok connection...")
            asyncio.run(test_grok_connection())
        else:
            print(f"Unknown command: {sys.argv[1]}")
            print("Usage: python agent_framework.py [demo|test|test-grok]")
    else:
        print("\nChoose an option:")
        print("1. Run AutoGen tournament demo")
        print("2. Test AutoGen system")
        print("3. Test Grok connection")

        choice = input("\nEnter choice (1-3): ").strip()

        if choice == "1":
            test_request = "Find Perfect Game tournaments in Texas for 14U teams"
            print(f"\n🎯 Running demo with request: {test_request}")
            asyncio.run(test_autogen_tournament_system())
        elif choice == "2":
            print("\n🧪 Running AutoGen system test...")
            asyncio.run(test_autogen_tournament_system())
        elif choice == "3":
            print("\n🧪 Testing Grok connection...")
            asyncio.run(test_grok_connection())
        else:
            print("Invalid choice. Running default test...")
            asyncio.run(test_autogen_tournament_system())


if __name__ == "__main__":
    main()
