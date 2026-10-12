#!/usr/bin/env python3
"""
Script B-Roll Agent Client - Specialized client for generating B-roll search terms

This agent analyzes scripts and generates contextual search terms for B-roll video footage.
"""

from typing import Dict, Any, List
from .base_agent_client import BaseAgentClient


class ScriptBRollAgentClient(BaseAgentClient):
    """Specialized client for B-roll search term generation"""

    def __init__(self):
        """Initialize the Script B-Roll Agent"""
        super().__init__(
            agent_id="asst_ILcqLMcj4zhGbIzUMTrcG73a", 
            agent_name="Script-bRoll-Agent"
        )

    def get_specialized_info(self) -> Dict[str, Any]:
        """Get specialized information about the B-roll agent"""
        return {
            "agent_type": "broll_generation",
            "capabilities": [
                "Script analysis for visual content",
                "B-roll search term generation",
                "Contextual keyword extraction",
                "Visual cue mapping",
                "Multi-source video recommendations",
            ],
            "output_formats": [
                "Search term tables",
                "Prioritized keyword lists",
                "Scene-by-scene breakdowns",
            ],
            "video_sources": [
                "Pexels (free stock videos)",
            ],
        }

    def generate_broll_search_terms(
        self,
        script_content: str,
        script_title: str = None,
        max_terms: int = 30,
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """
        Generate B-roll search terms from a script

        Args:
            script_content: The full script content to analyze
            script_title: Optional title for context
            max_terms: Target number of search terms (default: 30, agent may provide more)
            timeout: Request timeout in seconds (default: 180)

        Returns:
            Dict with success status and search terms or error message
        """
        print(f"\n🎬 Generating B-roll search terms...")
        print(f"   Script length: {len(script_content)} characters")
        if script_title:
            print(f"   Script title: {script_title}")

        # Build the request prompt - Let the AI Foundry system prompt do the heavy lifting
        request = f"""
Analyze this video script and extract comprehensive B-roll search terms.

{'SCRIPT TITLE: ' + script_title if script_title else ''}

SCRIPT CONTENT:
{script_content}

INSTRUCTIONS:
Please provide your analysis using BOTH output formats as specified in your system instructions:

1. First, provide the Quick Reference List organized by category
2. Then, provide a simple list of all unique search terms (one per line) for easy parsing

Focus on extracting:
- ALL product/app names mentioned (Gmail, Netflix, etc.)
- Specific interfaces and UI elements
- Human actions and interactions
- Technology concepts and visualizations
- Objects, devices, and physical items
- Abstract concepts that need visual metaphors

Target approximately {max_terms} core search terms in the final list, but feel free to provide more if the script warrants it.
"""

        # Create thread and send message
        thread = self.project.agents.threads.create()
        thread_id = thread.id

        try:
            result = self.send_message(
                thread_id=thread_id,
                message_content=request,
                show_sources=False,
                timeout=timeout,
            )

            if result.get("success"):
                response_text = result["response"]
                
                # Parse the response - handle both structured and simple list formats
                lines = response_text.strip().split("\n")
                search_terms = []
                seen_terms = set()  # Deduplicate
                
                for line in lines:
                    # Clean up each line
                    term = line.strip()
                    
                    # Skip headers, categories, and section markers
                    if not term or len(term) < 4:
                        continue
                    if term.startswith("#") or term.startswith("**"):
                        continue
                    if "category:" in term.lower() or "priority:" in term.lower():
                        continue
                    if term.startswith("Column") or term.startswith("Section"):
                        continue
                    if term.endswith(":"):  # Category headers like "Technology:"
                        continue
                    
                    # Remove numbering, bullets, dashes, priority markers
                    term = term.lstrip("0123456789.-•*[] ")
                    term = term.replace("[HIGH]", "").replace("[MED]", "").replace("[LOW]", "")
                    term = term.strip('"\'')
                    
                    # Remove "Product names →" style formatting
                    if "→" in term:
                        term = term.split("→")[-1].strip()
                    
                    # Only keep non-empty, unique terms
                    term_lower = term.lower()
                    if term and len(term) > 3 and term_lower not in seen_terms:
                        # Skip obvious non-search-terms
                        if not any(skip in term_lower for skip in [
                            "format", "output", "column", "table", "instruction",
                            "example", "note", "remember", "goal"
                        ]):
                            search_terms.append(term)
                            seen_terms.add(term_lower)
                
                print(f"✅ Generated {len(search_terms)} unique B-roll search terms")
                
                # Show first few terms for verification
                if search_terms:
                    preview = search_terms[:5]
                    print(f"   Preview: {', '.join(preview)}...")
                
                return {
                    "success": True,
                    "search_terms": search_terms,
                    "raw_response": response_text,
                    "term_count": len(search_terms),
                }
            else:
                error_msg = result.get("error", "Unknown error")
                print(f"❌ B-roll generation failed: {error_msg}")
                return {"success": False, "error": error_msg}

        except Exception as e:
            print(f"❌ Exception during B-roll generation: {e}")
            return {"success": False, "error": str(e)}

    def generate_broll_table(
        self,
        script_content: str,
        script_title: str = None,
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """
        Generate a detailed B-roll table with search terms and descriptions

        Args:
            script_content: The full script content to analyze
            script_title: Optional title for context
            timeout: Request timeout in seconds (default: 180 for comprehensive table)

        Returns:
            Dict with success status and formatted table or error message
        """
        print(f"\n📊 Generating detailed B-roll table...")

        request = f"""
Analyze this script and create a detailed B-roll search term table.

{'SCRIPT TITLE: ' + script_title if script_title else ''}

SCRIPT CONTENT:
{script_content}

YOUR TASK:
Create a comprehensive table of B-roll search terms with the following format:

| Search Term | Description | Scene Context |
|-------------|-------------|---------------|
| [term] | [what to look for] | [when to use in script] |

REQUIREMENTS:
1. Generate 25-30 rows (comprehensive coverage)
2. Each search term should be specific and visual
3. Description explains what type of footage to find
4. Scene Context indicates where in the script to use it
5. Use proper Markdown table formatting
6. Focus on actionable, searchable terms
7. Include variety: products/apps, actions, concepts, UI elements, objects

Generate the comprehensive B-roll table:
"""

        # Create thread and send message
        thread = self.project.agents.threads.create()
        thread_id = thread.id

        try:
            result = self.send_message(
                thread_id=thread_id,
                message_content=request,
                show_sources=False,
                timeout=timeout,
            )

            if result.get("success"):
                table_content = result["response"]
                print(f"✅ Generated B-roll table")
                
                return {
                    "success": True,
                    "table": table_content,
                }
            else:
                error_msg = result.get("error", "Unknown error")
                print(f"❌ Table generation failed: {error_msg}")
                return {"success": False, "error": error_msg}

        except Exception as e:
            print(f"❌ Exception during table generation: {e}")
            return {"success": False, "error": str(e)}
