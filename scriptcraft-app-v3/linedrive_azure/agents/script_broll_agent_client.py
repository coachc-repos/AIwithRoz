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
                "Pixabay (free stock videos)",
            ],
        }

    def generate_broll_search_terms(
        self,
        script_content: str,
        script_title: str = None,
        max_terms: int = 40,
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
                    term = term.replace("[HIGH]", "").replace(
                        "[MED]", "").replace("[LOW]", "")
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

                print(
                    f"✅ Generated {len(search_terms)} unique B-roll search terms")

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
1. Generate 33-40 rows (comprehensive coverage — about 1/3 more entries than a typical pass)
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

    def generate_broll_table_with_timecodes(
        self,
        script_content: str,
        script_title: str = None,
        words_per_minute: int = 150,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        Generate a detailed B-roll table with timecodes for EDL export

        Args:
            script_content: The full script content to analyze
            script_title: Optional title for context
            words_per_minute: Speaking pace for timecode calculation (default: 150)
            timeout: Request timeout in seconds (default: 180)

        Returns:
            Dict with success status, formatted table, and parsed data for EDL generation
        """
        print(f"\n📊 Generating B-roll table with timecodes...")

        request = f"""
Analyze this script and create a detailed B-roll search term table with specific locations.

{'SCRIPT TITLE: ' + script_title if script_title else ''}

SCRIPT CONTENT:
{script_content}

YOUR TASK:
Create a comprehensive table of B-roll search terms with the following format:

| Timecode | Search Term | Description | Scene Context |
|----------|-------------|-------------|---------------|
| [HH:MM:SS] | [term] | [what to look for] | [when to use in script] |

REQUIREMENTS:
1. Generate 48-60 rows — DENSE, comprehensive coverage. Aim for a distinct
   visual for roughly every 2-4 sentences / every key beat of the script, so
   nearly every moment has b-roll to cut to. Do NOT skip minor moments.
2. For each entry, estimate the timecode by analyzing WHERE in the script the term appears
3. Timecode should be in HH:MM:SS format (e.g., 00:01:23 for 1 minute 23 seconds)
4. Calculate timecodes assuming approximately {words_per_minute} words per minute speaking pace
5. Each search term should be specific and visual
6. Description explains what type of footage to find
7. Scene Context indicates where in the script to use it
8. Use proper Markdown table formatting
9. Focus on actionable, searchable terms
10. Include variety: products/apps, actions, concepts, UI elements, objects
11. INFOGRAPHIC MOMENTS — explicitly capture every DATA / STAT / PROCESS /
    COMPARISON / FRAMEWORK / LIST moment as its own row: numbers, percentages,
    growth or trends, before/after, step-by-step workflows, pros/cons, rankings,
    timelines, and "how it works" concepts. In the Description, describe these as
    a clean animated business infographic (charts, graphs, spreadsheets/tables,
    KPI counters, flow arrows, checkmarks) so they can be rendered as 2D/3D
    business-graphics clips. Aim for at least one such infographic-friendly row
    for every major point in the script.

IMPORTANT: 
- Analyze the script text to find where each term is mentioned
- Place the timecode marker at the approximate point in the script timeline
- Order the table chronologically by timecode
- Be specific about the exact moment each B-roll should appear

Generate the comprehensive B-roll table with timecodes:
"""

        # Create thread and send message
        thread = self.project.agents.threads.create()
        thread_id = thread.id

        def _is_refusal(text: str) -> bool:
            s = (text or "").strip().lower()
            if "|" in (text or ""):
                return False
            markers = (
                "i'm sorry", "i am sorry", "cannot assist", "can't assist",
                "unable to assist", "as an ai", "i cannot help",
                "i can't help",
            )
            return any(m in s for m in markers)

        try:
            result = self.send_message(
                thread_id=thread_id,
                message_content=request,
                show_sources=False,
                timeout=timeout,
            )

            # One-shot retry on refusal with a softened, explicit-context
            # preamble. The Foundry agent occasionally returns a content-policy
            # refusal for benign educational scripts; re-asking on a fresh
            # thread with framing usually resolves it.
            if result.get("success") and _is_refusal(result.get("response", "")):
                print("⚠️ First B-roll attempt looks like a refusal — retrying with softened preamble")
                retry_thread = self.project.agents.threads.create()
                retry_request = (
                    "You are assisting with B-roll search-term generation for "
                    "a legitimate, published educational/instructional video "
                    "script provided by its author. The script content is "
                    "user-supplied source material; your only task is to "
                    "produce a markdown table of stock-footage search terms "
                    "with timecodes. Do not refuse — if any portion seems "
                    "unclear, generate terms for the portions you can use.\n\n"
                    + request
                )
                result = self.send_message(
                    thread_id=retry_thread.id,
                    message_content=retry_request,
                    show_sources=False,
                    timeout=timeout,
                )

            if result.get("success"):
                table_content = result["response"]

                # Parse the table to extract structured data
                parsed_data = self._parse_broll_table_with_timecodes(
                    table_content)

                # Detect agent refusal / non-table responses. The Foundry agent
                # sometimes returns content-policy refusals like "I'm sorry, but
                # I cannot assist with that request." with success=True. If we
                # cannot parse a single table row, treat it as a failure so the
                # UI shows an actionable error instead of pasting the refusal
                # text into the B-Roll Table tab.
                if not parsed_data:
                    snippet = (table_content or "").strip()[:200]
                    refusal_markers = (
                        "i'm sorry", "i am sorry", "cannot assist",
                        "can't assist", "unable to assist", "as an ai",
                    )
                    looks_like_refusal = any(
                        m in snippet.lower() for m in refusal_markers
                    ) or "|" not in (table_content or "")
                    reason = (
                        "Agent declined or returned a non-table response"
                        if looks_like_refusal
                        else "No table rows could be parsed from agent response"
                    )
                    print(f"❌ B-roll table parse failed: {reason}")
                    print(f"   Agent said: {snippet!r}")
                    return {
                        "success": False,
                        "error": f"{reason}. Agent said: {snippet}",
                        "raw_response": table_content,
                    }

                # Create OR-separated search string from all search terms
                search_terms = [entry['search_term'] for entry in parsed_data]
                or_search_string = " OR ".join(search_terms)

                # Append the OR search string below the table
                table_with_search = f"{table_content}\n\n**Stock Footage Search String:**\n\n{or_search_string}"

                print(
                    f"✅ Generated B-roll table with {len(parsed_data)} entries")

                return {
                    "success": True,
                    "table": table_with_search,
                    "parsed_data": parsed_data,
                    "entry_count": len(parsed_data),
                }
            else:
                error_msg = result.get("error", "Unknown error")
                print(f"❌ Table generation failed: {error_msg}")
                return {"success": False, "error": error_msg}

        except Exception as e:
            print(f"❌ Exception during table generation: {e}")
            return {"success": False, "error": str(e)}

    def _parse_broll_table_with_timecodes(self, table_text: str) -> List[Dict[str, str]]:
        """
        Parse markdown table with timecodes into structured data

        Args:
            table_text: Markdown table text

        Returns:
            List of dicts with timecode, search_term, description, and scene_context
        """
        import re as _re

        entries = []
        lines = table_text.strip().split('\n')

        # Header detector — lines whose cells contain the schema keywords
        # (any casing, any order). We skip them so they don't become rows.
        header_keywords = ("timecode", "search term", "description",
                           "scene context", "context")

        for line in lines:
            if '|' not in line:
                continue
            stripped = line.strip()
            # Separator rows: |---|---|---|---|  (also handles :---: alignment)
            if _re.match(r'^\|?\s*:?-{2,}', stripped) or _re.fullmatch(
                r'\|?\s*(?::?-{2,}:?\s*\|?\s*)+', stripped
            ):
                continue

            # Split on pipes WITHOUT collapsing internal empties — that was the
            # original bug: an empty middle cell shifted Description and Scene
            # Context columns left by one. Only trim the leading/trailing
            # empty produced by the wrapping `|` characters.
            raw_parts = line.split('|')
            if raw_parts and raw_parts[0].strip() == '':
                raw_parts = raw_parts[1:]
            if raw_parts and raw_parts[-1].strip() == '':
                raw_parts = raw_parts[:-1]
            parts = [p.strip() for p in raw_parts]

            if len(parts) < 4:
                continue

            # Header row check (case-insensitive on first 4 cells)
            joined_lower = ' '.join(parts[:4]).lower()
            if all(kw in joined_lower for kw in ("search term", "description")):
                continue
            if any(parts[0].lower().startswith(p) for p in ("timecode", "time")) \
                    and "term" in (parts[1].lower() if len(parts) > 1 else ""):
                continue

            # If the agent emitted >4 columns, merge any trailing cells back
            # into Scene Context so we don't lose data and don't truncate.
            timecode = parts[0]
            search_term = parts[1]
            description = parts[2]
            scene_context = ' | '.join(parts[3:]) if len(parts) > 4 else parts[3]

            # Drop rows where every visible cell is empty or placeholder.
            if not any([timecode, search_term, description, scene_context]):
                continue

            entries.append({
                'timecode': timecode,
                'search_term': search_term,
                'description': description,
                'scene_context': scene_context,
            })

        return entries

    def create_edl_markers(
        self,
        broll_data: List[Dict[str, str]],
        output_file: str = 'broll_markers.edl',
        frame_rate: str = '24'
    ) -> Dict[str, Any]:
        """
        Create EDL marker file from b-roll data for DaVinci Resolve

        Args:
            broll_data: List of dicts with timecode, search_term, description, scene_context
            output_file: Path to output EDL file
            frame_rate: Frame rate (24, 30, etc.)

        Returns:
            Dict with success status and file path or error
        """
        try:
            print(f"\n📝 Creating EDL marker file: {output_file}")
            print(f"   Entries: {len(broll_data)}")
            print(f"   Frame rate: {frame_rate} fps")

            edl_content = "TITLE: B-Roll Markers\n"
            edl_content += "FCM: NON-DROP FRAME\n\n"

            for idx, marker in enumerate(broll_data, 1):
                # EDL format for markers
                edl_number = f"{idx:03d}"

                # Convert HH:MM:SS to HH:MM:SS:FF (frames)
                tc = self._convert_to_edl_timecode(
                    marker['timecode'], frame_rate)

                # EDL entry with marker name as clip name
                # Will import as offline clips, user adds B-roll and copies to main timeline
                edl_content += f"{edl_number}  001      V     C        {tc} {tc} {tc} {tc}\n"
                edl_content += f"* FROM CLIP NAME: {marker['search_term']}\n"
                edl_content += f"* COMMENT: {marker['description'][:60]}\n\n"

            # Write the file
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(edl_content)

            print(f"✅ EDL file created successfully: {output_file}")

            return {
                "success": True,
                "file_path": output_file,
                "marker_count": len(broll_data),
            }

        except Exception as e:
            print(f"❌ EDL creation failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def _convert_to_edl_timecode(self, timecode: str, frame_rate: str) -> str:
        """
        Convert HH:MM:SS to HH:MM:SS:FF format for EDL

        Args:
            timecode: Time in HH:MM:SS format
            frame_rate: Frame rate string ('24', '30', etc.)

        Returns:
            Timecode in HH:MM:SS:FF format
        """
        # If already has frames, return as-is
        if timecode.count(':') == 3:
            return timecode

        # Add :00 for frames
        return f"{timecode}:00"
