#!/usr/bin/env python3
"""
Text processing functions for LineDrive Console
Handles script content manipulation and teleprompter text extraction
"""

import re
from pathlib import Path


def extract_teleprompter_text(script_content: str) -> str:
    """Extract only host-readable text from script, removing visual cues,
    production notes, technical directions, and unwanted sections"""
    print("📺 Extracting teleprompter-friendly text from script...")

    lines = script_content.split("\n")
    teleprompter_lines = []

    skip_patterns = [
        # Visual cues
        r"^\s*\[Visual Cue:",
        r"^\s*\[visual cue:",
        r"^\s*\[VISUAL CUE:",
        r"^\s*Visual Cue:",
        r"^\s*\*\*Visual Cue:\*\*",
        r"^\s*\*\*VISUAL CUE:\*\*",
        # Tool demos
        r"^\s*\*\*Tool Demo:\*\*",
        r"^\s*\*\*TOOL DEMO:\*\*",
        r"^\s*Tool Demo:",
        r"^\s*TOOL DEMO:",
        # Production notes
        r"^\s*\[Production Note:",
        r"^\s*\[production note:",
        r"^\s*\[PRODUCTION NOTE:",
        r"^\s*Production Note:",
        # Technical directions
        r"^\s*\[Technical:",
        r"^\s*\[TECHNICAL:",
        r"^\s*Technical:",
        # Camera directions
        r"^\s*\[Camera:",
        r"^\s*\[CAMERA:",
        r"^\s*Camera:",
        # Production timing blocks
        r"^\s*\[\d+:\d+\s*-\s*\d+:\d+\]",
        r"^\s*\[.*STINGER.*\]",
        r"^\s*\[.*LOGO.*STING.*\]",
        r"^\s*\[.*HOST INTRODUCTION.*\]",
        r"^\s*\[.*OUTRO.*\]",
        r"^\s*\[.*TRANSITION.*\]",
        # Production elements
        r"^\s*NOTES FOR PRODUCER:",
        r"^\s*AUDIO:",
        r"^\s*VISUAL:",
        r"^\s*TRANSITION:",
        r"^\s*MUSIC:",
        r"^\s*SFX:",
        r"^\s*GRAPHICS:",
        r"^\s*CUT TO:",
        r"^\s*FADE IN:",
        r"^\s*FADE OUT:",
    ]

    # Sections to completely exclude from teleprompter
    exclude_sections = [
        "## POLISHING ANALYSIS",
        "##POLISHING ANALYSIS",
        "# POLISHING ANALYSIS",
        "#POLISHING ANALYSIS",
        "POLISHING ANALYSIS",
        "## CHAPTER BREAKDOWN",
        "##CHAPTER BREAKDOWN",
        "# CHAPTER BREAKDOWN",
        "#CHAPTER BREAKDOWN",
        "CHAPTER BREAKDOWN",
        "## REVISION SUGGESTIONS",
        "##REVISION SUGGESTIONS",
        "# REVISION SUGGESTIONS",
        "#REVISION SUGGESTIONS",
        "REVISION SUGGESTIONS",
        "## TOOLS TO DEMO",
        "##TOOLS TO DEMO",
        "# TOOLS TO DEMO",
        "#TOOLS TO DEMO",
        "TOOLS TO DEMO",
        "## VISUAL CUES TO ADD",
        "##VISUAL CUES TO ADD",
        "# VISUAL CUES TO ADD",
        "#VISUAL CUES TO ADD",
        "VISUAL CUES TO ADD",
        "## PRODUCTION NOTES",
        "##PRODUCTION NOTES",
        "# PRODUCTION NOTES",
        "#PRODUCTION NOTES",
        "PRODUCTION NOTES",
        "## TOOL SPOTLIGHT",
        "##TOOL SPOTLIGHT",
        "# TOOL SPOTLIGHT",
        "#TOOL SPOTLIGHT",
        "TOOL SPOTLIGHT",
        "## Tool Spotlight",
        "##Tool Spotlight",
        "# Tool Spotlight",
        "#Tool Spotlight",
        "Tool Spotlight",
    ]

    skip_until_next_section = False

    for line in lines:
        # Skip empty lines
        if not line.strip():
            if not skip_until_next_section:
                teleprompter_lines.append(line)
            continue

        line_stripped = line.strip()

        # Check if this line starts a section we want to exclude
        if any(
            line_stripped.upper().startswith(section.upper())
            for section in exclude_sections
        ):
            skip_until_next_section = True
            continue

        # Special check for "Tool Spotlight" which can appear in subsections like "### Tool Spotlight: ChatGPT"
        if "tool spotlight" in line_stripped.lower() and line_stripped.startswith(
            ("#", "##", "###")
        ):
            skip_until_next_section = True
            continue

        # Check if we've reached a new section (starts with # or ##)
        if skip_until_next_section and (
            line.strip().startswith("#") or line.strip().startswith("##")
        ):
            # Check if this new section is also one we want to exclude
            if not any(
                line_stripped.upper().startswith(section.upper())
                for section in exclude_sections
            ):
                # Also check for Tool Spotlight subsections
                if not (
                    "tool spotlight" in line_stripped.lower()
                    and line_stripped.startswith(("#", "##", "###"))
                ):
                    skip_until_next_section = False
                else:
                    continue  # Still excluding this Tool Spotlight section
            else:
                continue  # Still excluding this section

        # If we're in exclusion mode, skip this line
        if skip_until_next_section:
            continue

        # Check if line should be skipped due to other patterns
        should_skip = False
        for pattern in skip_patterns:
            if re.match(pattern, line):
                should_skip = True
                break

        if not should_skip:
            # Remove inline visual cue and tool demo markers
            cleaned_line = line

            # Remove **Visual Cue:** markers and their content
            cleaned_line = re.sub(
                r"\*\*Visual Cue:\*\*[^\n]*(?:\n|$)",
                "",
                cleaned_line,
                flags=re.IGNORECASE,
            )

            # Remove **Tool Demo:** markers and their content
            cleaned_line = re.sub(
                r"\*\*Tool Demo:\*\*[^\n]*(?:\n|$)",
                "",
                cleaned_line,
                flags=re.IGNORECASE,
            )

            # Remove [Visual Cue: ...] style markers
            cleaned_line = re.sub(
                r"\[Visual Cue:[^\]]*\]", "", cleaned_line, flags=re.IGNORECASE
            )

            # Remove [Tool Demo: ...] style markers
            cleaned_line = re.sub(
                r"\[Tool Demo:[^\]]*\]", "", cleaned_line, flags=re.IGNORECASE
            )

            # Only add non-empty lines after cleaning
            if cleaned_line.strip():
                teleprompter_lines.append(cleaned_line)

    return "\n".join(teleprompter_lines)


def enhance_script_with_bold_tools(script_content: str) -> str:
    """Enhance script content by making tools, headings, and visual cues bold"""

    # Check if this looks like demo packages content
    if "DEMO PACKAGE" in script_content.upper() and (
        "TOOL 1" in script_content.upper()
        or "EVERYDAY-VIEWER" in script_content.upper()
    ):
        return enhance_demo_packages_formatting(script_content)

    print("✨ Enhancing script with bold tool formatting...")

    lines = script_content.split("\n")
    enhanced_lines = []

    # Common tools and services that should be bold
    tool_names = [
        # AI and productivity tools
        "Notion",
        "ChatGPT",
        "Claude",
        "Gemini",
        "OpenAI",
        "Zapier",
        "Grammarly",
        "Loom",
        "Calendly",
        "Slack",
        "Trello",
        "Asana",
        # Design and creative tools
        "Figma",
        "Canva",
        "Photoshop",
        "Illustrator",
        # Communication tools
        "Zoom",
        "Microsoft Teams",
        "Discord",
        "Telegram",
        # Development tools
        "GitHub",
        "GitLab",
        "VS Code",
        "Visual Studio Code",
        "Copilot",
        # Media and entertainment
        "YouTube",
        "Netflix",
        "TikTok",
        "Instagram",
        "Twitter",
        "LinkedIn",
    ]

    for line in lines:
        enhanced_line = line

        # Handle visual cue sections with special formatting
        if enhanced_line.strip().startswith(
            "**Visual Cue:**"
        ) or enhanced_line.strip().startswith("Visual Cue:"):
            # Make visual cues larger and colorized
            visual_text = (
                enhanced_line.strip()
                .replace("**Visual Cue:**", "")
                .replace("Visual Cue:", "")
                .strip()
            )
            enhanced_line = f"## 🎬 **VISUAL CUE:** {visual_text}"
            enhanced_lines.append(enhanced_line)
            continue

        # Make known tools bold
        for tool in tool_names:
            # Only make it bold if it's not already bold
            if tool in enhanced_line and f"**{tool}**" not in enhanced_line:
                # Use word boundaries to avoid partial matches
                pattern = r"\b" + re.escape(tool) + r"\b"
                enhanced_line = re.sub(pattern, f"**{tool}**", enhanced_line)

        enhanced_lines.append(enhanced_line)

    return "\n".join(enhanced_lines)


def enhance_demo_packages_formatting(demo_content: str) -> str:
    """Enhance demo package content with proper formatting for headings"""
    print("✨ Applying demo-specific formatting enhancements...")

    lines = demo_content.split("\n")
    enhanced_lines = []

    for line in lines:
        enhanced_line = line
        stripped = line.strip()

        # Main demo package headers
        demo_starts = ["EVERYDAY-VIEWER DEMO PACKAGE",
                       "DEVELOPER DEMO PACKAGE"]
        if any(stripped.startswith(start) for start in demo_starts):
            enhanced_line = f"## {stripped}"

        # Tool headers (TOOL 1 — ChatGPT format)
        elif stripped.startswith("TOOL ") and "—" in stripped:
            enhanced_line = f"### {stripped}"

        # Make tool names bold in sentences
        tool_names = ["ChatGPT", "Canva", "Notion", "YouTube", "Google"]
        for tool in tool_names:
            if tool in enhanced_line and f"**{tool}**" not in enhanced_line:
                enhanced_line = enhanced_line.replace(tool, f"**{tool}**")

        enhanced_lines.append(enhanced_line)

    return "\n".join(enhanced_lines)


def extract_tool_links_and_info(script_content: str) -> str:
    """Extract tool links and information for YouTube description"""
    print("🔍 Extracting tool links and information...")

    lines = script_content.split("\n")
    extracted_urls = []

    # Enhanced patterns for tool identification and URLs
    url_pattern = r"(https?://[^\s\)>,]+)"

    for line in lines:
        line = line.strip()
        if "**URL**:" in line or "URL:" in line:
            # Direct URL extraction from **URL**: format
            urls = re.findall(url_pattern, line)
            for url in urls:
                # Clean URL and normalize format
                url = url.rstrip(".,!?;:")
                # Add https:// if it's a domain without protocol
                if not url.startswith("http"):
                    url = f"https://{url}"
                if url not in extracted_urls:
                    extracted_urls.append(url)

    # Map URLs to tool names based on domain
    url_to_tool = {
        "chat.openai.com": "ChatGPT",
        "claude.ai": "Claude",
        "perplexity.ai": "Perplexity",
        "canva.com": "Canva",
        "grammarly.com": "Grammarly",
        "notion.so": "Notion",
        "github.com": "GitHub",
    }

    # Create tool info from extracted URLs
    tool_info = []
    for url in extracted_urls:
        # Try to match domain to known tool
        tool_found = False
        for domain, tool_name in url_to_tool.items():
            if domain in url:
                tool_info.append(f"• {tool_name}: {url}")
                tool_found = True
                break

        if not tool_found:
            # Extract domain name as tool name
            try:
                domain = url.split("//")[1].split("/")[0]
                if domain.startswith("www."):
                    domain = domain[4:]
                tool_name = domain.replace(
                    ".com", "").replace(".ai", "").capitalize()
                tool_info.append(f"• {tool_name}: {url}")
            except Exception:
                tool_info.append(f"• Tool: {url}")

    if tool_info:
        youtube_description = "\n🛠️ TOOLS & RESOURCES MENTIONED:\n"
        youtube_description += "\n".join(tool_info)
        youtube_description += (
            "\n\n📝 This description contains affiliate links where applicable."
        )
        youtube_description += (
            "\nUsing these links helps support the channel at no extra cost to you."
        )
        youtube_description += (
            "\n\n🔗 Want more productivity tips? Check out our other videos!"
        )
        return youtube_description
    else:
        return "\n🛠️ No specific tools or resources were mentioned in this content."


def extract_heygen_host_script(script_content: str) -> str:
    """
    Extract ONLY Host dialogue from script for HeyGen text-to-video.
    Removes all visual cues, tool demos, production notes, and non-host content.
    Only includes the actual spoken words under 'Host:' sections.

    Also extracts and prepends the HOOK text if present.

    Args:
        script_content: Full script content with host dialogue and production notes

    Returns:
        Clean host-only script ready for HeyGen, with paragraphs separated by double newlines
    """
    print("🎬 Extracting HeyGen-ready host script...")

    # First, extract the hook text if present
    hook_text = ""
    hook_pattern = r'HOOK\s*\([\d\-]+\s*seconds?\)\s*["\']([^"\']+)["\']'
    hook_match = re.search(hook_pattern, script_content, re.IGNORECASE)
    if hook_match:
        hook_text = hook_match.group(1).strip()
        print(f"✅ Found hook: {hook_text[:50]}...")

    lines = script_content.split("\n")
    host_paragraphs = []
    current_paragraph = []
    in_host_section = False

    # Patterns that indicate we should skip this line
    skip_patterns = [
        r"^\s*\[Visual Cue:",
        r"^\s*\[visual cue:",
        r"^\s*\[VISUAL CUE:",
        r"^\s*Visual Cue:",
        r"^\s*\*\*Visual Cue:\*\*",
        r"^\s*\*\*VISUAL CUE:\*\*",
        r"^\s*\*\*Tool Demo:\*\*",
        r"^\s*\*\*TOOL DEMO:\*\*",
        r"^\s*Tool Demo:",
        r"^\s*TOOL DEMO:",
        r"^\s*\[Production Note:",
        r"^\s*\[Technical:",
        r"^\s*\[Camera:",
        r"^\s*\[\d+:\d+\s*-\s*\d+:\d+\]",
        r"^\s*\[.*STINGER.*\]",
        r"^\s*\[.*LOGO.*STING.*\]",
        r"^\s*\[.*TRANSITION.*\]",
        r"^\s*NOTES FOR PRODUCER:",
        r"^\s*AUDIO:",
        r"^\s*VISUAL:",
        r"^\s*TRANSITION:",
        r"^\s*MUSIC:",
        r"^\s*SFX:",
        r"^\s*GRAPHICS:",
        r"^\s*CUT TO:",
        r"^\s*FADE IN:",
        r"^\s*FADE OUT:",
        r"^\s*---+\s*$",  # Separator lines (---, ----, etc.)
        r"^\s*===+\s*$",  # Separator lines (===, ====, etc.)
        r"^\s*\*\*\*+\s*$",  # Separator lines (***, ****, etc.)
        # Bold chapter titles (**Chapter 1...**, etc.)
        r"^\s*\*\*Chapter\s+\d+.*\*\*\s*$",
        r"^\s*\*\*CHAPTER\s+\d+.*\*\*\s*$",  # Bold chapter titles uppercase
        r"^\s*Generated by LineDrive",  # Skip "Generated by LineDrive..." footer
        r"^\s*\*\*.*OPENING HOOK.*\*\*\s*$",  # Skip "🎬 OPENING HOOK" heading
        r"^\s*\*\*.*CONCLUSION.*\*\*\s*$",  # Skip "📝 CONCLUSION/SUMMARY" heading
        r"^\s*\*\*.*SUMMARY.*\*\*\s*$",  # Skip summary section headings
        # NOTE: 'Heading:' lines are intentionally KEPT so the curl generator
        # can use them as chapter boundaries (one curl per chapter).
    ]

    # Sections to completely exclude
    exclude_sections = [
        "POLISHING ANALYSIS",
        "CHAPTER BREAKDOWN",
        "REVISION SUGGESTIONS",
        "TOOLS TO DEMO",
        "VISUAL CUES TO ADD",
        "PRODUCTION NOTES",
        "TOOL SPOTLIGHT",
        "YOUTUBE UPLOAD DETAILS",
        "EMOTIONAL THUMBNAIL VARIATIONS",
    ]

    skip_until_next_section = False

    debug = False  # Set to True for debugging

    for line in lines:
        stripped = line.strip()

        if debug and stripped:
            print(
                f"[DEBUG] Line: '{stripped[:50]}...' | in_host: {in_host_section}")

        # Check if we're entering an excluded section
        if any(excluded in stripped.upper() for excluded in exclude_sections):
            skip_until_next_section = True
            in_host_section = False
            if debug:
                print(f"[DEBUG] Entering excluded section")
            continue

        # Check if this is a new major section (reset skip flag)
        if stripped.startswith("#") or stripped.startswith("=="):
            skip_until_next_section = False
            in_host_section = False
            continue

        # If we're in an excluded section, skip this line
        if skip_until_next_section:
            continue

        # Treat a "Heading: ..." line as a chapter boundary: save any
        # in-progress host paragraph, then re-enter host mode so the
        # chapter's prose paragraphs are collected as spoken content.
        # Without this, scripts that use `Heading: Chapter N - ...` as
        # chapter markers (the docx-extracted / processed format) drop
        # all chapter prose because they only have ONE explicit `Host:`
        # (in the FINAL HOOK).
        if re.match(r"^\s*\*{0,2}\s*Heading\s*:", stripped, re.IGNORECASE):
            if current_paragraph:
                paragraph_text = " ".join(current_paragraph)
                if paragraph_text:
                    host_paragraphs.append(paragraph_text)
                current_paragraph = []
            in_host_section = True
            if debug:
                print(f"[DEBUG] Found Heading: chapter boundary")
            continue

        # Check if this line starts with a "Host" speaker label, in any form:
        # Host:, **Host:**, **Host**:, **Host**, *Host* (bold markers anywhere,
        # colon optional).
        if re.match(r"^\s*\*{0,2}\s*Host\s*\*{0,2}\s*:?\s*\*{0,2}\s*$", stripped, re.IGNORECASE):
            # "Host" label on its own line - start collecting from next line
            in_host_section = True
            if debug:
                print(f"[DEBUG] Found Host: marker (standalone)")
            continue
        elif re.match(r"^\s*\*{0,2}\s*Host\s*\*{0,2}\s*:?\s*\*{0,2}", stripped, re.IGNORECASE):
            # "Host" label with text on same line
            in_host_section = True
            if debug:
                print(f"[DEBUG] Found Host: marker (with text)")
            # Extract text after the "Host" label
            host_text = re.sub(
                r"^\s*\*{0,2}\s*Host\s*\*{0,2}\s*:?\s*\*{0,2}\s*",
                "",
                stripped,
                flags=re.IGNORECASE
            )
            if host_text:
                current_paragraph.append(host_text)
                if debug:
                    print(f"[DEBUG] Added text: '{host_text[:50]}...'")
            continue

        # If we're in host section, check if this line should be included
        if in_host_section:
            # Check if we've hit a chapter marker or major section (ends Host section)
            if re.match(r'^#+\s+', stripped):  # Markdown header (# Chapter...)
                # Save current paragraph if exists
                if current_paragraph:
                    paragraph_text = " ".join(current_paragraph)
                    if paragraph_text:
                        host_paragraphs.append(paragraph_text)
                        if debug:
                            print(
                                f"[DEBUG] Saved final paragraph in section: '{paragraph_text[:50]}...'")
                    current_paragraph = []
                in_host_section = False
                if debug:
                    print(f"[DEBUG] Exiting Host section (found chapter marker)")
                continue

            # Skip lines matching skip patterns
            should_skip = any(
                re.match(pattern, line, re.IGNORECASE)
                for pattern in skip_patterns
            )
            if should_skip:
                if debug:
                    print(f"[DEBUG] Skipping line (matches pattern)")
                continue

            # Empty line - ends current paragraph but stays in host section
            if not stripped:
                # If we have paragraph content, save it and start new paragraph
                if current_paragraph:
                    # Join paragraph lines and add to collection
                    paragraph_text = " ".join(current_paragraph)
                    if paragraph_text:
                        host_paragraphs.append(paragraph_text)
                        if debug:
                            print(
                                f"[DEBUG] Saved paragraph: '{paragraph_text[:50]}...'")
                    current_paragraph = []
                    # Stay in host section (don't set in_host_section = False)
                # If no paragraph content yet, skip the blank line (spacing after Host:)
                continue

            # Add line to current paragraph
            current_paragraph.append(stripped)
            if debug:
                print(f"[DEBUG] Added to paragraph: '{stripped[:50]}...'")

    # Don't forget the last paragraph if exists
    if current_paragraph:
        paragraph_text = " ".join(current_paragraph)
        if paragraph_text:
            host_paragraphs.append(paragraph_text)

    # Prepend hook text if found
    if hook_text:
        host_paragraphs.insert(0, hook_text)
        print(f"✅ Added hook to beginning of HeyGen script")

    # Join all paragraphs with double newlines for readability
    heygen_script = "\n\n".join(host_paragraphs)

    # Final scrub: regardless of how we got here, strip every non-spoken
    # artifact (title, chapter headings, hook/summary markers, separators,
    # stage directions, metadata) so the HeyGen text is dialogue ONLY.
    heygen_script = scrub_heygen_text(heygen_script)

    print(f"✅ Extracted {len(host_paragraphs)} host paragraphs for HeyGen")
    return heygen_script


def scrub_heygen_text(text: str) -> str:
    """Aggressively remove non-spoken artifacts from a HeyGen-bound script.

    Guarantees the returned string contains ONLY spoken dialogue paragraphs —
    no titles, no chapter headings, no FINAL HOOK / SUMMARY markers, no
    visual cues, no metadata, no separators. Safe to call on already-clean
    text (it becomes a no-op for plain prose).
    """
    if not text:
        return ""

    skip_line_patterns = [
        # Section headers / dividers
        r'^\s*#{1,6}\s',
        r'^\s*={3,}\s*$',
        r'^\s*-{3,}\s*$',
        r'^\s*_{3,}\s*$',
        r'^\s*\*{3,}\s*$',
        # Script metadata (accept both ":" and " -" separators)
        r'^\s*(?:Title|Script\s*Type|Duration|Audience|Tone|Generated|'
        r'Template\s*ID|Voice\s*ID)\s*[:\-]',
        # "Direct Video - <title>" header line
        r'^\s*Direct\s+Video\s*[-:–]',
        # Chapter headings (Heading:, Chapter N - …, **Chapter N…**)
        r'^\s*(?:\*{0,2}\s*)?Heading\s*:',
        r'^\s*(?:#{1,6}\s*)?(?:\*{0,2}\s*)?Chapter\s+\d+\s*[-:–]',
        r'^\s*\*{2}\s*Chapter\s+\d+.*\*{2}\s*$',
        # Hook / Summary markers
        r'^\s*\*{0,2}\s*(?:🎯\s*)?(?:FINAL\s+)?HOOK\s*[:\(]',
        r'^\s*\*{0,2}\s*OPENING\s+HOOK',
        r'^\s*\*{0,2}\s*HOOK\s+OPTION',
        r'^\s*\*{0,2}\s*OPTION\s+\d+',
        r'^\s*\*{0,2}\s*(?:📝\s*)?(?:CONCLUSION|SUMMARY)\s*[:\*]',
        # Speaker / production labels
        r'^\s*\*{0,2}\s*Host\s*:\s*\*{0,2}\s*$',
        r'^\s*(?:🎬\s*)?(?:\*{0,2}\s*)?'
        r'(?:Visual\s*Cue|B-?Roll|On[- ]Screen|Graphic|SFX|Music|Caption|'
        r'Cut\s+to|Transition|Narrator|Voiceover|VO|Camera|Production\s*Note|'
        r'Tool\s*Demo|Notes\s+for\s+Producer|Audio|Visual|Graphics|Fade\s+in|'
        r'Fade\s+out)\s*[:\(]',
        # Footer
        r'^\s*Generated\s+by\s+LineDrive',
    ]
    compiled = [re.compile(p, re.IGNORECASE) for p in skip_line_patterns]

    kept = []
    for raw in text.split('\n'):
        s = raw.strip()
        if not s:
            kept.append('')
            continue
        if any(rx.match(s) for rx in compiled):
            continue
        # Strip leading "Summary:" / "Host:" labels but keep the rest.
        s = re.sub(r'^\s*(?:Summary|Host)\s*:\s*', '', s, flags=re.IGNORECASE)
        if not s:
            continue
        kept.append(s)

    # Collapse runs of blank lines to single blank lines, trim ends.
    out_lines = []
    blank = False
    for ln in kept:
        if not ln:
            if not blank and out_lines:
                out_lines.append('')
            blank = True
        else:
            out_lines.append(ln)
            blank = False
    return '\n'.join(out_lines).strip()


def generate_heygen_curl_commands(
    script_content: str,
    script_title: str,
    api_key: str = "",
    template_id: str = "92c09f8e9a1c4f078f7ae53886b7ad80",
    voice_id: str = "",
    final_hook_text: str = ""
) -> str:
    """
    Generate HeyGen API curl commands from script content.
    Uses the V3 (New AI Studio) template generate endpoint per:
    https://developers.heygen.com/reference/generate-video-from-template
    (the legacy V2 /v2/template/{id}/generate endpoint is being deprecated).

    Args:
        script_content: Full script markdown content
        script_title: Title of the script
        api_key: HeyGen API key
        template_id: HeyGen template ID
        voice_id: Optional HeyGen voice ID for voice override

    Returns:
        Formatted string with all curl commands
    """
    import re
    import json as _json

    def shell_single_quote(text: str) -> str:
        """Escape a string so it can be safely embedded inside bash single quotes.

        Replaces every ' with '\\'' which closes, escapes the quote, and reopens.
        """
        return text.replace("'", "'\\''")

    def clean_text(text):
        """Clean up line wrapping and extra whitespace."""
        text = re.sub(r'\s*\n\s*', ' ', text)
        text = re.sub(r'\s{2,}', ' ', text)
        return text.strip()

    def strip_stage_lines(text: str) -> str:
        """Remove non-spoken lines (visual cues, b-roll, headings, metadata)
        from a chapter body so HeyGen only gets the actual dialogue."""
        out_lines = []
        for ln in text.split('\n'):
            s = ln.strip()
            if not s:
                out_lines.append('')
                continue
            # Stage direction / production label lines.
            if re.match(
                r'^(?:🎬\s*)?(?:\*{0,2}\s*)?'
                r'(?:Visual\s*Cue|B-?Roll|On[- ]Screen|Graphic|SFX|Music|'
                r'Caption|Cut\s+to|Transition|Narrator|Voiceover|VO|Heading)'
                r'\s*:',
                s, re.IGNORECASE,
            ):
                continue
            # Script-metadata bleed lines (Direct Video - ... / Script Type: /
            # Duration: / Generated: / Audience: / Tone:).
            if re.match(
                r'^(?:Direct\s+Video\b|Script\s+Type\s*:|Duration\s*:|'
                r'Generated\s*:|Audience\s*:|Tone\s*:|Title\s*:)',
                s, re.IGNORECASE,
            ):
                continue
            # Drop a standalone "Host" speaker label line entirely, and strip a
            # leading Host label from a spoken line — in every form: Host:,
            # **Host:**, **Host**:, **Host**, *Host* (bold markers anywhere,
            # colon optional). HeyGen must get only the dialogue, never "Host".
            if re.match(r'^\*{0,2}\s*Host\s*\*{0,2}\s*:?\s*\*{0,2}\s*$', s, re.IGNORECASE):
                continue
            s = re.sub(r'^\*{0,2}\s*Host\s*\*{0,2}\s*:?\s*\*{0,2}\s*', '', s, flags=re.IGNORECASE)
            # Strip a leading "Summary:" label (keep the sentence after it).
            s = re.sub(r'^\s*Summary\s*:\s*', '', s, flags=re.IGNORECASE)
            out_lines.append(s)
        return '\n'.join(out_lines).strip()

    # Find the HeyGen section
    heygen_match = re.search(
        r'# 🎬 HEYGEN READY SCRIPT\s*={70,}\s*(.+?)(?:\n\n#+\s|$)',
        script_content,
        re.DOTALL
    )

    if not heygen_match:
        return ""

    heygen_content = heygen_match.group(1).strip()

    # Cut trailing production/metadata sections that follow the LAST chapter
    # (=== SUPPORTING RESEARCH ===, === FINAL PACKAGING ===, === STRATEGY NOTES
    # ===, === YOUTUBE VIDEO DESCRIPTION ===, and any other "=== SECTION ==="
    # header). The primary chapter regex bounds the final chapter with \Z, so
    # without this cut these non-spoken sections get swallowed into the last
    # chapter's curl and split across its parts (the reported Chapter-7 bug).
    _meta_cut = re.search(
        r'^[ \t]*={3,}[ \t]*[A-Za-z]'                 # "=== SECTION ===" header
        r'|^[ \t]*(?:SUPPORTING[ \t]+RESEARCH'        # or a known bare section
        r'|FINAL[ \t]+PACKAGING'
        r'|STRATEGY[ \t]+NOTES'
        r'|YOUTUBE[ \t]+VIDEO[ \t]+DESCRIPTION)\b',
        heygen_content, re.IGNORECASE | re.MULTILINE,
    )
    if _meta_cut:
        heygen_content = heygen_content[:_meta_cut.start()].rstrip()

    # Parse chapters
    chapters = []

    # Helper function to shorten title to 3 words max
    def shorten_title(title):
        words = title.split()
        return ' '.join(words[:3])

    # Try to find structured chapters with "Heading:" markers.
    # IMPORTANT: docx-extracted scripts join paragraphs with a single `\n`
    # (one paragraph per line) so the title and the first body paragraph
    # are separated by just one newline, not a blank line. Use `\n+` so
    # both the docx single-newline and markdown blank-line forms match.
    chapter_pattern = (
        r'Heading:[ \t]+([^\n]+)\n+(.+?)(?=\n+Heading:[ \t]+|\Z)'
    )
    chapter_matches = list(re.finditer(
        chapter_pattern, heygen_content, re.DOTALL))

    # FALLBACK: many manually-authored / processed scripts use bare
    # `Chapter N - Title` or `Chapter N: Title` lines instead of `Heading:`.
    # Detect those and treat each as a chapter boundary so we don't dump the
    # entire script into a single Ch1 curl.
    if not chapter_matches:
        alt_pattern = (
            r'^\s*(?:#{1,6}\s*)?(?:\*{0,2})\s*'
            r'(Chapter\s+\d+\s*[-:–]\s*[^\n]+?)'
            r'(?:\*{0,2})\s*\n+'
            r'(.+?)'
            r'(?=^\s*(?:#{1,6}\s*)?(?:\*{0,2})\s*Chapter\s+\d+\s*[-:–]'
            r'|^\s*SUPPORTING\s+RESEARCH'
            r'|^\s*={3,}\s*$'
            r'|\Z)'
        )
        chapter_matches = list(re.finditer(
            alt_pattern, heygen_content, re.DOTALL | re.MULTILINE))

    if chapter_matches:
        # Use structured chapters if they exist.
        # NOTE: We intentionally SKIP any text that appears before the first
        # "Heading:" marker (the script intro / FINAL HOOK block). The hook
        # already gets its own dedicated `{title}-hook` / `-hook-2` curls via
        # the `final_hook_text` parameter, and standing-intro text like the
        # "Hi, I'm Roz's AI Digital Twin…" preamble shouldn't be turned into
        # a phantom Chapter-0 curl. This keeps N "Heading:" lines → N chapter
        # entries (so 6 chapters yields 6, not 7).

        # Add all chapters as found in the script
        for match in chapter_matches:
            chapter_title = match.group(1).strip()
            chapter_content = clean_text(strip_stage_lines(match.group(2)))

            chapters.append({
                'title': shorten_title(chapter_title),
                'content': chapter_content
            })
    else:
        # No structured chapters - split continuous text into reasonable chunks
        # Split on paragraph breaks (double newlines)
        paragraphs = [clean_text(p)
                      for p in heygen_content.split('\n\n') if p.strip()]

        if not paragraphs:
            return ""

        # Group paragraphs into chapters of ~500-800 words each
        current_chapter_content = []
        current_word_count = 0
        target_words_per_chapter = 650

        for para in paragraphs:
            para_words = len(para.split())

            # If adding this paragraph would exceed target, save current chapter
            if current_word_count > 0 and current_word_count + para_words > target_words_per_chapter:
                chapter_text = ' '.join(current_chapter_content)
                chapters.append({
                    'title': f"{script_title}-Part{len(chapters)+1}",
                    'content': chapter_text
                })
                current_chapter_content = [para]
                current_word_count = para_words
            else:
                current_chapter_content.append(para)
                current_word_count += para_words

        # Add final chapter if any content remains
        if current_chapter_content:
            chapter_text = ' '.join(current_chapter_content)
            chapters.append({
                'title': f"{script_title}-Part{len(chapters)+1}",
                'content': chapter_text
            })

    if not chapters:
        return ""

    # Helper function to split content in half
    def split_content(content):
        """Split content roughly in half at a sentence boundary."""
        mid_point = len(content) // 2
        # Find the nearest sentence end (period + space) around the midpoint
        search_range = 200  # Look 200 chars before/after midpoint
        best_split = mid_point

        # Search for period + space near midpoint
        for offset in range(0, search_range):
            # Check after midpoint
            pos = mid_point + offset
            if pos < len(content) - 1 and content[pos:pos+2] in ['. ', '! ', '? ']:
                best_split = pos + 2
                break
            # Check before midpoint
            pos = mid_point - offset
            if pos > 0 and pos < len(content) - 1 and content[pos:pos+2] in ['. ', '! ', '? ']:
                best_split = pos + 2
                break

        part1 = content[:best_split].strip()
        part2 = content[best_split:].strip()
        return part1, part2

    # Generate curl commands
    curl_commands = []
    curl_commands.append("\n# 🚀 HEYGEN API CURL COMMANDS")
    curl_commands.append("=" * 80)
    curl_commands.append(
        f"# Generated: {len(chapters)} chapters (2 per chapter; +2 hook curls if FINAL HOOK present)")
    curl_commands.append(f"# Script: {script_title}")
    curl_commands.append("=" * 80)
    curl_commands.append("")

    # Helper function to shorten title by extracting key words
    def shorten_title(full_title):
        """Extract key words from title, removing common filler words."""
        import re
        # Strip script-structure label prefixes that occasionally leak in
        # when title extraction falls back to a non-title line.
        title = re.sub(
            r'^(?:VISUAL\s*CUE|HEADING|VISUAL|B-?ROLL|HOOK|SUMMARY|HOST)\s*[:\-]\s*',
            '', full_title, flags=re.IGNORECASE)
        # Remove common prefixes like "Direct Video -", "Video -", etc.
        title = re.sub(r'^(Direct\s+Video\s*-\s*|Video\s*-\s*)',
                       '', title, flags=re.IGNORECASE)
        # Find content before the chapter marker (Ch1p1, Part1, etc.)
        match = re.match(r'^(.+?)(?:-Ch\d+p\d+|-Part\d+)?$', title)
        if match:
            title = match.group(1).strip()
        # Remove common filler phrases
        title = re.sub(r'\bfor those who have\b', '',
                       title, flags=re.IGNORECASE)
        title = re.sub(r'\bAI for\b', '', title, flags=re.IGNORECASE)
        # Clean up extra spaces
        title = re.sub(r'\s+', ' ', title).strip()
        # Remove leading/trailing hyphens or spaces
        title = title.strip(' -')
        # Hard length cap so curl titles stay short and HeyGen-friendly.
        # Truncate at a word boundary; max ~40 chars.
        MAX_LEN = 40
        if len(title) > MAX_LEN:
            truncated = title[:MAX_LEN].rsplit(' ', 1)[0].strip(' -')
            title = truncated or title[:MAX_LEN].strip(' -')
        return title

    # Shorten the script title once for all curl entries
    short_title = shorten_title(script_title)

    # Build the curl with json.dumps for bullet-proof JSON escaping,
    # then shell-escape the resulting payload for bash single quotes.
    # HeyGen template variable name — must match the text variable defined in
    # the Studio template. Keep in sync with the frontend "test generate" form.
    heygen_var_name = "script"

    def build_curl(title_text: str, content_text: str) -> str:
        # HeyGen V3 (New AI Studio) template generate payload. The text variable
        # is flattened to {type, content} — the legacy V2 wrapper
        # ({name, properties:{content}}) is gone. `variables` is keyed by the
        # template's variable name.
        payload = {
            "caption": False,
            "title": title_text,
            "variables": {
                heygen_var_name: {
                    "type": "text",
                    "content": content_text,
                }
            },
        }
        data_json = _json.dumps(payload, indent=2, ensure_ascii=False)
        data_for_bash = shell_single_quote(data_json)
        return (
            "curl --request POST \\\n"
            f"     --url 'https://api.heygen.com/v3/templates/{template_id}' \\\n"
            "     --header 'accept: application/json' \\\n"
            "     --header 'content-type: application/json' \\\n"
            f"     --header 'x-api-key: {api_key}' \\\n"
            f"     --data '{data_for_bash}'\n\n"
        )

    extra_curls = 0
    # If a FINAL HOOK was selected, emit TWO curls for it (hook + hook-2).
    # If the hook is long enough, split it in half at a sentence boundary;
    # otherwise duplicate it so HeyGen always gets two hook variants.
    if final_hook_text and final_hook_text.strip():
        # Defensive: peel off leading blank lines, bold-only transition
        # lines (e.g. **We will start with...**), and stray Host: /
        # FINAL HOOK: label lines that may have leaked into the hook
        # capture upstream. These inflate the hook curl's word count.
        _peel_re = re.compile(
            r"^\s*(?:"
            r"\*{1,2}[^\n]+\*{1,2}"
            r"|\*{0,2}\s*Host\s*\*{0,2}\s*:?\s*\*{0,2}"
            r"|\*{0,2}\s*(?:🎯\s*)?FINAL\s+HOOK\s*:?\s*\*{0,2}"
            r")\s*$",
            re.IGNORECASE,
        )
        _peeled = final_hook_text.split("\n")
        while _peeled and (not _peeled[0].strip()
                           or _peel_re.match(_peeled[0])):
            _peeled.pop(0)
        final_hook_text = "\n".join(_peeled).strip()
        # Defensive: truncate at the first script-structure marker so we never
        # bleed Heading:/Visual Cue:/Chapter lines into the hook curl.
        _hook_raw = re.split(
            r"\n\s*(?:\*{0,2}\s*)?(?:Heading|Visual\s*Cue|B-?Roll|Chapter)\s*[:\-]",
            final_hook_text,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        hook_clean = clean_text(_hook_raw)
        if hook_clean:
            # Both hook curls get the FULL hook text — the user generates the
            # HeyGen video for the hook twice (two takes), so each curl must
            # contain the complete hook, not a split half.
            curl_commands.append(build_curl(f"{short_title}-hook", hook_clean))
            curl_commands.append(build_curl(
                f"{short_title}-hook-2", hook_clean))
            extra_curls += 2

    for i, chapter in enumerate(chapters, 1):
        # Split chapter content into two parts
        part1, part2 = split_content(chapter['content'])

        # Generate Part 1 curl command
        title_part1 = f"{short_title}-Ch{i}p1"
        curl_commands.append(build_curl(title_part1, part1))

        # Generate Part 2 curl command
        curl_commands.append(build_curl(f"{short_title}-Ch{i}p2", part2))

    curl_commands.append("=" * 80)
    total_curls = len(chapters) * 2 + extra_curls
    hook_note = " + 2 FINAL HOOK curls (hook, hook-2)" if extra_curls else ""
    curl_commands.append(
        f"# ✅ {total_curls} curl commands ready (2 per chapter{hook_note})")
    curl_commands.append(
        "# Copy and paste individual commands or save to .sh file")
    curl_commands.append("=" * 80)

    return "\n".join(curl_commands)


def format_demo_steps_plain(demo_packages: str) -> str:
    """
    Format demo package steps to plain text (no numbers, bullets, or dashes).

    Converts:
    1. First step  ->  First step
    2. Second step ->  Second step
    - List item    ->  List item
    • Bullet item  ->  Bullet item

    Args:
        demo_packages: Full demo package markdown content

    Returns:
        Formatted demo packages with plain step lines
    """
    import re

    # Remove numbering from steps (1. 2. 3. etc.)
    demo_packages = re.sub(r'^\s*\d+\.\s+', '',
                           demo_packages, flags=re.MULTILINE)

    # Remove bullet points (•)
    demo_packages = re.sub(r'^\s*•\s+', '', demo_packages, flags=re.MULTILINE)

    # Remove dashes at start of lines (- item)
    demo_packages = re.sub(r'^\s*-\s+', '', demo_packages, flags=re.MULTILINE)

    return demo_packages


def extract_demo_heygen_content(demo_packages: str) -> str:
    """
    Extract HeyGen-ready spoken content from demo packages.

    Extracts:
    - Transition text before steps ("Now let's take a look at...")
    - Numbered steps
    - Presenter commentary

    Args:
        demo_packages: Full demo package markdown content

    Returns:
        String with only the spoken content, ready for HeyGen
    """
    import re

    heygen_sections = []

    # Find all tool sections (marked by ## Tool Name)
    tool_pattern = r'##\s+(.+?)\n(.+?)(?=##|\Z)'

    for match in re.finditer(tool_pattern, demo_packages, re.DOTALL):
        tool_name = match.group(1).strip()
        tool_content = match.group(2).strip()

        heygen_text = []

        # Extract transition text (lines starting with "Now let's take a look at")
        transition_pattern = r'(Now let\'s take a look at .+?)(?=\n|\Z)'
        transition_match = re.search(
            transition_pattern, tool_content, re.IGNORECASE)
        if transition_match:
            heygen_text.append(transition_match.group(1).strip())

        # Extract numbered steps
        # Look for step-by-step instructions section
        steps_pattern = r'(?:Step-by-step Instructions:?\s*\n)?((?:\s*\d+\..+\n?)+)'
        steps_match = re.search(steps_pattern, tool_content, re.MULTILINE)
        if steps_match:
            steps_text = steps_match.group(1).strip()
            # Clean up the steps - just keep the numbers and content
            steps_lines = [line.strip()
                           for line in steps_text.split('\n') if line.strip()]
            heygen_text.extend(steps_lines)

        # Extract presenter commentary
        commentary_pattern = r'Presenter Commentary:?\s*["\']?(.+?)["\']?\s*(?=\n\n|\Z)'
        commentary_match = re.search(
            commentary_pattern, tool_content, re.DOTALL | re.IGNORECASE)
        if commentary_match:
            commentary = commentary_match.group(1).strip()
            # Remove surrounding quotes if present
            commentary = commentary.strip('"\'')
            heygen_text.append(commentary)

        # Add this tool's content to the overall sections
        if heygen_text:
            heygen_sections.append('\n'.join(heygen_text))

    return '\n\n'.join(heygen_sections)
