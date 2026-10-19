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

    Args:
        script_content: Full script content with host dialogue and production notes

    Returns:
        Clean host-only script ready for HeyGen, with paragraphs separated by double newlines
    """
    print("🎬 Extracting HeyGen-ready host script...")

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

        # Check if this line starts with "Host:" (case insensitive)
        if re.match(r"^\s*\*?\*?Host:\*?\*?\s*$", stripped, re.IGNORECASE):
            # "Host:" on its own line - start collecting from next line
            in_host_section = True
            if debug:
                print(f"[DEBUG] Found Host: marker (standalone)")
            continue
        elif re.match(r"^\s*\*?\*?Host:\*?\*?", stripped, re.IGNORECASE):
            # "Host:" with text on same line
            in_host_section = True
            if debug:
                print(f"[DEBUG] Found Host: marker (with text)")
            # Extract text after "Host:" marker
            host_text = re.sub(
                r"^\s*\*?\*?Host:\*?\*?\s*",
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

    # Join all paragraphs with double newlines for readability
    heygen_script = "\n\n".join(host_paragraphs)

    print(f"✅ Extracted {len(host_paragraphs)} host paragraphs for HeyGen")
    return heygen_script


def generate_heygen_curl_commands(
    script_content: str,
    script_title: str,
    api_key: str = "",
    template_id: str = "92c09f8e9a1c4f078f7ae53886b7ad80",
    voice_id: str = ""
) -> str:
    """
    Generate HeyGen API curl commands from script content.
    Uses the v2 template generate endpoint per:
    https://docs.heygen.com/reference/generate-from-template-v2

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

    def escape_for_bash(text):
        """Escape text for bash single quotes and JSON double quotes."""
        # First escape backslashes (must be first!)
        text = text.replace('\\', '\\\\')
        # Then escape double quotes for JSON
        text = text.replace('"', '\\"')
        # Finally escape single quotes for bash
        text = text.replace("'", "'\\''")
        return text

    def clean_text(text):
        """Clean up line wrapping and extra whitespace."""
        text = re.sub(r'\s*\n\s*', ' ', text)
        text = re.sub(r'\s{2,}', ' ', text)
        return text.strip()

    # Find the HeyGen section
    heygen_match = re.search(
        r'# 🎬 HEYGEN READY SCRIPT\s*={70,}\s*(.+?)(?:\n\n#+\s|$)',
        script_content,
        re.DOTALL
    )

    if not heygen_match:
        return ""

    heygen_content = heygen_match.group(1).strip()

    # Parse chapters
    chapters = []

    # Helper function to intelligently shorten title
    def shorten_title(title):
        """Extract key words from title, removing common prefixes."""
        # Remove common prefixes like "Direct Video - ", "Video - ", etc.
        title = re.sub(r'^(Direct\s+Video\s*-\s*|Video\s*-\s*|Script\s*-\s*)',
                       '', title, flags=re.IGNORECASE)

        # If still long, try to keep the most meaningful part
        # Look for patterns like "AI for those who have ZERO Knowledge" -> "ZERO Knowledge"
        # Keep words that are ALL CAPS or Title Case as they're usually key words
        words = title.split()

        # If we have a long title, try to extract key words
        if len(words) > 5:
            # Find words that are ALL CAPS or have multiple capital letters
            key_words = []
            for word in words:
                # Keep ALL CAPS words, or words with internal capitals
                if word.isupper() or (len([c for c in word if c.isupper()]) > 1):
                    key_words.append(word)

            # If we found key words, use them plus 2 words of context
            if key_words:
                # Find the position of the first key word
                first_key_idx = next(
                    (i for i, w in enumerate(words) if w in key_words), 0)
                # Take key word plus some context (up to 5 words total)
                result = ' '.join(words[first_key_idx:first_key_idx+5])
                return result

        # Default: take first 5 words
        return ' '.join(words[:5])

    # Try to find structured chapters with "Heading:" markers
    chapter_pattern = r'Heading:\s+(.+?)\n\n(.+?)(?=\nHeading:|$)'
    chapter_matches = list(re.finditer(
        chapter_pattern, heygen_content, re.DOTALL))

    if chapter_matches:
        # Use structured chapters if they exist
        # First chapter (intro before first "Heading:")
        intro_match = re.search(r'^(.+?)(?=\nHeading:)',
                                heygen_content, re.DOTALL)
        if intro_match:
            intro_text = clean_text(intro_match.group(1))
            chapters.append({
                'title': shorten_title(script_title),
                'content': intro_text
            })

        # Add all other chapters
        for match in chapter_matches:
            chapter_title = match.group(1).strip()
            chapter_content = clean_text(match.group(2))

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
        f"# Generated: {len(chapters)} chapters (3 parts each)")
    curl_commands.append(f"# Script: {script_title}")
    curl_commands.append("# Note: Ch1p1 and Ch1p1b are duplicates for backup")
    curl_commands.append("=" * 80)
    curl_commands.append("")

    for i, chapter in enumerate(chapters, 1):
        # Split chapter content into two parts
        part1, part2 = split_content(chapter['content'])

        # Generate Part 1 curl command (original)
        # Use script_title (which is now the 4-digit script number) + chapter number
        escaped_title_part1 = escape_for_bash(f"{script_title}-Ch{i}p1")
        escaped_content_part1 = escape_for_bash(part1)

        # Build variables JSON — template voice is already set, just pass text
        def build_variables_json(escaped_content):
            return f"""    "script": {{
      "type": "text",
      "content": "{escaped_content}"
    }}"""

        def build_curl(escaped_title, escaped_content):
            variables_block = build_variables_json(escaped_content)
            return f"""curl --request POST \\
     --url 'https://api.heygen.com/v3/templates/{template_id}' \\
     --header 'accept: application/json' \\
     --header 'content-type: application/json' \\
     --header 'x-api-key: {api_key}' \\
     --data '{{
  "caption": false,
  "title": "{escaped_title}",
  "variables": {{
{variables_block}
  }}
}}'

"""

        curl_commands.append(build_curl(escaped_title_part1, escaped_content_part1))

        # Generate Part 1b curl command (duplicate with "b" suffix)
        escaped_title_part1b = escape_for_bash(f"{script_title}-Ch{i}p1b")
        curl_commands.append(build_curl(escaped_title_part1b, escaped_content_part1))

        # Generate Part 2 curl command
        escaped_title_part2 = escape_for_bash(f"{script_title}-Ch{i}p2")
        escaped_content_part2 = escape_for_bash(part2)
        curl_commands.append(build_curl(escaped_title_part2, escaped_content_part2))

    curl_commands.append("=" * 80)
    curl_commands.append(f"# ✅ {len(chapters) * 3} curl commands ready")
    curl_commands.append("# (3 per chapter: p1, p1b duplicate, p2)")
    curl_commands.append("# Copy and paste or save to .sh file")
    curl_commands.append("=" * 80)

    return "\n".join(curl_commands)


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
