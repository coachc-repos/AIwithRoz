"""OpenAI Demo Agent Client

Simple client to call Azure OpenAI to generate demo packages
from an input script. The client reads the API key from the environment variable
`AZURE_OPENAI_DEMO_KEY` (fallback to `OPENAI_API_KEY`).

Do NOT hardcode keys in source; set AZURE_OPENAI_DEMO_KEY in your shell before running.

Example usage:
    client = OpenAIDemoAgentClient()
    result = client.generate_demo_packages(script_text)

"""

from __future__ import annotations

import os
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from typing import Optional, Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

MASTER_PROMPT = r"""
Master Demo Prompt

I will provide you with a video script. For that script, generate two different demo packages:

CRITICAL REQUIREMENT: You MUST ONLY create demos for tools and services that are EXPLICITLY MENTIONED in the provided script. Do NOT add any additional tools that are not referenced in the original content.

⸻

1. Developer-Focused Demo Package

(For an audience of programmers, technical students, or engineers.)

Each developer demo must include:
	•	Choice of demo(s): Pick 1–2 demos using ONLY tools/services mentioned in the provided script that best illustrate key themes (e.g., summarization, context awareness, recommendation systems).
	•	Tools and libraries: List exactly what to install (with pip or package manager commands).
	•	Setup steps: Assume the audience may start with a blank machine — include Python install note, virtualenv, environment variables, etc.
	•	Code: Provide copy-paste ready example scripts (minimal but functional).
	•	Run instructions: Show exact terminal commands to execute.
	•	Expected output: Show example terminal output.
	•	Transcript commentary: Write out what I (the presenter) should say out loud while typing, waiting for installs, or running code. Commentary should:
	•	Explain what’s happening in simple, clear terms.
	•	Tie back to the script (e.g., “Remember earlier in the script we said AI learns like a pet? This code shows that in practice.”).
	•	Include filler to cover downtime (e.g., while pip installs or model runs).
	•	Anticipate errors and give “if this fails…” recovery lines I can read.
	•	Extra talking points: Give me optional filler blocks to drop in (performance tips, cost considerations, ethics notes) so I can stretch the demo if I need more time.

⸻

2. Everyday-Viewer Demo Package

(For non-technical parents, teachers, or general viewers curious about AI.)

Each user-friendly demo must include:
	•	Choice of tool(s): Pick 1–2 tools using ONLY the tools/services specifically mentioned in the provided script. Do NOT introduce new tools not referenced in the original content.
	•	Full URLs: Include the complete copy-pasteable web address for each tool.
	•	Setup steps: If an account is required, explain quickly how to sign up or preload something.
	•	Walk-through: Step-by-step what to click/do.
	•	Transcript commentary: Write a full teleprompter-style script for me to read out loud. Commentary should:
	•	Tie back to the themes of the provided script (e.g., “This chatbot is a great way to show kids how input/output works, just like we explained earlier about Narrow AI.”).
	•	Use kid-friendly analogies and real-life comparisons.
	•	Explain why this tool demonstrates AI concepts while keeping it fun.
	•	Offer teaching moments (“See how it guessed wrong? That’s bias — a great conversation starter about AI limits.”).
	•	Wrap-up commentary: A closing paragraph I can read to connect the tool back to the bigger message of the script.

⸻

3. Output Formatting

Deliver the results in two clearly separated sections:
	•	Developer Demos
	•	Everyday Viewer Demos

Each section must be fully self-contained so I can copy straight into my teleprompter notes.

IMPORTANT CONSTRAINT: Only create demos for tools, services, websites, or applications that are specifically mentioned by name in the provided script. Do not suggest or demonstrate any additional tools beyond those referenced in the original content.

⸻

4. Tone
	•	Conversational, engaging, and clear.
	•	Assume I am reading this out loud on video while screen-sharing my VS Code or browser.

... (few-shot examples are intentionally omitted here; the model will rely on the instruction and the provided script.)
"""


class OpenAIDemoAgentClient:
    """Client for calling Azure OpenAI to generate demo packages.

    Notes:
    - Uses Azure AD authentication (DefaultAzureCredential)
    - Falls back to API key from AZURE_OPENAI_DEMO_KEY or OPENAI_API_KEY
    - Uses Azure OpenAI endpoint based on your provided example
    - Returns structured response from OpenAI chat completion
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        model: str = "gpt-5-mini",
        use_azure_ad: bool = True,
    ) -> None:
        # Azure OpenAI configuration (from your example)
        self.endpoint = endpoint or "https://coach-me1k8xkn-eastus2.openai.azure.com/"
        self.model = model
        self.deployment = self.model  # Use model name as deployment name
        self.api_version = "2024-12-01-preview"
        self.use_azure_ad = use_azure_ad

        if self.use_azure_ad:
            # Try Azure AD authentication first
            try:
                credential = DefaultAzureCredential()
                token_provider = get_bearer_token_provider(
                    credential, "https://cognitiveservices.azure.com/.default"
                )
                self.client = AzureOpenAI(
                    api_version=self.api_version,
                    azure_endpoint=self.endpoint,
                    azure_ad_token_provider=token_provider,
                )
                print("✅ Using Azure AD authentication for OpenAI Demo Agent")
                return
            except Exception as e:
                print(f"⚠️ Azure AD auth failed, falling back to API key: {e}")

        # Fallback to API key authentication
        self.api_key = (
            api_key
            or os.environ.get("AZURE_OPENAI_DEMO_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )

        if not self.api_key:
            raise RuntimeError(
                "Failed Azure AD auth and no API key found. "
                "Set AZURE_OPENAI_DEMO_KEY or ensure Azure CLI login."
            )

        # Initialize Azure OpenAI client with API key
        self.client = AzureOpenAI(
            api_version=self.api_version,
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
        )
        print("✅ Using API key authentication for OpenAI Demo Agent")

    def generate_demo_packages(
        self, script_text: str, max_tokens: int = 8000, audience: str = "general"
    ) -> Dict[str, Any]:
        """Send master prompt + script_text to Azure OpenAI and return parsed text.

        For reasoning models like gpt-5-mini, we need more tokens and specific prompting
        to ensure visible output after internal reasoning.

        Returns: { success: bool, response: str, raw: dict }
        """
        # Enhanced prompt requiring real, actionable tools with detailed descriptions
        # Adapt content based on audience
        is_developer_audience = any(
            term in audience.lower()
            for term in [
                "developer",
                "programmer",
                "engineer",
                "technical",
                "coder",
                "dev",
            ]
        )

        if is_developer_audience:
            # Include both developer and everyday demos for developer audience
            demo_types = """Create TWO demo packages ONLY using tools explicitly mentioned in the provided script:

⚠️ CRITICAL TOOL EXTRACTION RULE ⚠️
You MUST ONLY create demos for tools, services, APIs, or websites that are EXPLICITLY MENTIONED in the provided script content.
- If the script mentions "ChatGPT", create a ChatGPT demo
- If the script mentions "OpenAI API", create an OpenAI API demo
- If NO specific tools are mentioned (other than ChatGPT), look for the "TOOLS & RESOURCES" section in the YouTube upload details
- Create demos for touring those resource websites (e.g., if "Rapsodo: https://rapsodo.com" is listed, create a Rapsodo website tour demo)
- DO NOT add any tools that are not referenced in the original script content
- DO NOT use generic examples or placeholder tools

1. DEVELOPER-FOCUSED DEMO PACKAGE
(For programmers, technical students, engineers)
- Extract tool names from the script content ONLY
- Each tool MUST include:
  * Exact name and complete URL
  * Installation command with version (if applicable)
  * YouTube search terms
  * Pricing info
  * Current version and compatibility notes
- List exact pip install commands with version numbers
- Provide setup steps (assume blank machine) 
- Include copy-paste ready code examples that actually work
- Show exact terminal commands with real API endpoints
- Include presenter commentary for what to say while typing/waiting
- Add optional talking points for extra time

2. EVERYDAY-VIEWER DEMO PACKAGE  
(For parents, general audience, non-technical viewers)
- Extract tool names from the script content ONLY
- If no tools mentioned, use resources from TOOLS & RESOURCES section for website tours
- Each tool/resource MUST include:
  * Exact name and complete copy-pasteable URL
  * Account requirements
  * YouTube search terms
  * Pricing info (if applicable)
  * Mobile app availability
- Provide step-by-step clicking instructions with real button names
- Include presenter commentary with real examples
- Add conversation starters for family discussions

DEMO TRANSITION REQUIREMENT:
Before each tool's step-by-step instructions, add a natural transition using VARIED wording.
Use different phrases for each tool - do NOT use the same wording every time.

Transition examples (pick different ones for each tool):
- "Now let's take a look at [TOOL NAME], the first thing you'll need to do is"
- "Ok, why don't we take a look at [TOOL NAME], you'll get started by"
- "Let me show you [TOOL NAME], to begin you'll want to"
- "Alright, let's explore [TOOL NAME], first you're going to"
- "Next up is [TOOL NAME], the first step is to"
- "Let's dive into [TOOL NAME], you'll start by"
- "Time to check out [TOOL NAME], begin by"

IMPORTANT: Use a DIFFERENT transition phrase for each tool. Vary the wording naturally.
Place this transition text BEFORE the numbered steps."""
        else:
            # Only everyday viewer demos for non-developer audience
            demo_types = """Create ONE comprehensive demo package ONLY using tools from the script:

⚠️ CRITICAL TOOL EXTRACTION RULE ⚠️
You MUST ONLY create demos for tools, services, or websites that are EXPLICITLY MENTIONED in the provided script.
- If the script mentions specific AI tools (e.g., "ChatGPT"), create demos for those tools
- If NO specific tools are mentioned (other than ChatGPT), look for the "TOOLS & RESOURCES" section in the YouTube upload details
- Create demos for touring those resource websites (e.g., if "Rapsodo: https://rapsodo.com" is listed, create a Rapsodo website tour demo)
- DO NOT add any tools that are not referenced in the original script content
- DO NOT use generic examples like Claude, Perplexity, Canva, Character.AI unless explicitly mentioned in the script

EVERYDAY-VIEWER DEMO PACKAGE  
(For parents, general audience, non-technical viewers)
- Extract tool names from the script content ONLY
- If no tools mentioned, use resources from TOOLS & RESOURCES section for website tours
- Each tool/resource MUST include:
  * Exact name and complete copy-pasteable URL
  * Account requirements
  * YouTube search terms
  * Pricing info (if applicable)
  * Mobile app availability
  * Step-by-step getting started instructions
- Provide step-by-step clicking instructions with real button names
- Include presenter commentary with real examples
- Add conversation starters for family discussions
- NO CODE EXAMPLES OR TECHNICAL INSTALLATION STEPS
- Focus on web-based tools that work immediately without setup

DEMO TRANSITION REQUIREMENT:
Before each tool's step-by-step instructions, add a natural transition using VARIED wording.
Use different phrases for each tool - do NOT use the same wording every time.

Transition examples (pick different ones for each tool):
- "Now let's take a look at [TOOL NAME], the first thing you'll need to do is"
- "Ok, why don't we take a look at [TOOL NAME], you'll get started by"
- "Let me show you [TOOL NAME], to begin you'll want to"
- "Alright, let's explore [TOOL NAME], first you're going to"
- "Next up is [TOOL NAME], the first step is to"
- "Let's dive into [TOOL NAME], you'll start by"
- "Time to check out [TOOL NAME], begin by"

IMPORTANT: Use a DIFFERENT transition phrase for each tool. Vary the wording naturally.
Place this transition text BEFORE the numbered steps."""

        reasoning_prompt = f"""You are creating demo packages for a video script about AI education.
Target audience: {audience}

{demo_types}

CRITICAL REQUIREMENTS:
⚠️ ONLY USE TOOLS EXPLICITLY MENTIONED IN THE SCRIPT ⚠️
- You MUST extract tool names from the provided script content ONLY
- If the script mentions "Runway" or "Adobe Photoshop", create demos for those
- If NO tools are mentioned, check the "TOOLS & RESOURCES" section for website URLs
- Create website tour demos for those resources (e.g., Rapsodo, TeamSnap, etc.)
- DO NOT add Claude, Perplexity, Canva, Character.AI, or any other tools not in the script
- NO generic examples like "SomeAI Tool" or "ExampleAPI"
- Every tool must be explicitly referenced in the script or TOOLS & RESOURCES section
- Focus on tools that actually demonstrate the concepts in the script

FORMATTING REQUIREMENTS:
- Use proper markdown formatting throughout
- Replace all dashes "-" with bullet points "•" for lists
- Make text before colons ":" bold using **text**: regular text
- Use proper heading structure: ## Tool Name for each tool demonstration
- Indent numbered steps with proper spacing
- Use clean indentation to separate segments
- Structure like this example:

## ChatGPT Demo
**URL**: chat.openai.com  
**Account Required**: Free account recommended  
**Mobile App**: Available on iOS and Android  

**Step-by-step Instructions**:
   1. Navigate to chat.openai.com
   2. Click "Sign Up" or "Log In"  
   3. Start typing your question

**Presenter Commentary**: "Let me show you how easy this is..."

Script to create demos for:
{script_text}

IMPORTANT: You must provide complete, detailed responses with ONLY real tools that users can immediately access and use. Verify each tool/URL is real before including it. Use the formatting requirements above consistently throughout your response."""

        messages = [
            {
                "role": "user",
                "content": reasoning_prompt,
            }
        ]

        try:
            response = self.client.chat.completions.create(
                messages=messages,
                max_completion_tokens=max_tokens,
                model=self.deployment,
            )

            # Extract the content from the response
            content = response.choices[0].message.content or ""

            # Remove all double asterisks - Word formatting will handle bolding
            content = content.replace("**", "")

            # For reasoning models, if we get empty content but used reasoning tokens,
            # that means the model did internal reasoning but didn't provide output
            if (
                not content
                and response.usage
                and response.usage.completion_tokens_details
            ):
                reasoning_tokens = getattr(
                    response.usage.completion_tokens_details, "reasoning_tokens", 0
                )
                if reasoning_tokens > 0:
                    logger.warning(
                        f"Reasoning model used {reasoning_tokens} tokens for internal reasoning but provided no visible output. Consider increasing max_tokens or adjusting the prompt."
                    )
                    return {
                        "success": False,
                        "error": f"Reasoning model completed internal reasoning ({reasoning_tokens} tokens) but provided no visible output. This may indicate the task was too complex for the token limit or the prompt needs adjustment for reasoning models.",
                        "raw": {
                            "model": response.model,
                            "usage": (
                                response.usage.model_dump() if response.usage else None
                            ),
                            "finish_reason": response.choices[0].finish_reason,
                        },
                    }

            return {
                "success": True,
                "response": content,
                "raw": {
                    "model": response.model,
                    "usage": response.usage.model_dump() if response.usage else None,
                    "finish_reason": response.choices[0].finish_reason,
                    "full_response": response.model_dump(),
                },
            }

        except Exception as e:
            logger.error(f"Error calling Azure OpenAI: {e}")
            return {"success": False, "error": str(e)}

    def save_api_key(self, api_key: str, env_file: Optional[str] = None) -> bool:
        """Persist the provided API key to a .env file inside the agents folder.

        This will update or create `linedrive_azure/agents/.env` by default and add
        AZURE_OPENAI_DEMO_KEY and OPENAI_API_KEY entries. File permissions will be
        set to 0o600 when possible.
        """
        try:
            env_path = Path(env_file) if env_file else Path(__file__).parent / ".env"
            env_path.parent.mkdir(parents=True, exist_ok=True)

            existing = []
            if env_path.exists():
                existing = env_path.read_text(encoding="utf-8").splitlines()

            # Parse existing key-values to preserve other settings
            kv = {}
            for line in existing:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    kv[k.strip()] = v.strip()

            kv["AZURE_OPENAI_DEMO_KEY"] = api_key
            if "OPENAI_API_KEY" not in kv:
                kv["OPENAI_API_KEY"] = api_key

            # Rebuild file content while preserving comments/other lines
            out_lines = []
            seen = set()
            for line in existing:
                if "=" in line and not line.strip().startswith("#"):
                    k = line.split("=", 1)[0].strip()
                    if k in ("AZURE_OPENAI_DEMO_KEY", "OPENAI_API_KEY"):
                        if k in kv:
                            out_lines.append(f"{k}={kv[k]}")
                            seen.add(k)
                    else:
                        out_lines.append(line)
                else:
                    out_lines.append(line)

            if "AZURE_OPENAI_DEMO_KEY" not in seen:
                out_lines.append(f"AZURE_OPENAI_DEMO_KEY={kv['AZURE_OPENAI_DEMO_KEY']}")
            if "OPENAI_API_KEY" not in seen:
                out_lines.append(f"OPENAI_API_KEY={kv['OPENAI_API_KEY']}")

            env_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
            try:
                os.chmod(env_path, 0o600)
            except Exception:
                # ignore chmod failures on platforms that don't support it
                pass

            return True
        except Exception:
            return False
