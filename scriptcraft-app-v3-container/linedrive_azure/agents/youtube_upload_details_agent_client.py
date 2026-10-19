#!/usr/bin/env python3
"""
YouTube Upload Details Agent Client - Specialized client for generating YouTube upload metadata

This agent handles creation of comprehensive YouTube upload details including:
- Video filename generation
- SEO-optimized titles
- Complete video descriptions with timestamps
- Tags for discoverability
- Thumbnail text suggestions
- Category recommendations
- Playlist suggestions
"""

from typing import Dict, Any, List
from .base_agent_client import BaseAgentClient


class YouTubeUploadDetailsAgentClient(BaseAgentClient):
    """Specialized client for generating YouTube upload metadata and details"""

    def __init__(self):
        """Initialize the YouTube Upload Details Agent"""
        super().__init__(
            agent_id="asst_3SXXgX7WbQmrgg2tGDgkynKV",
            agent_name="YouTube-Upload-Details-Agent",
        )

    def get_specialized_info(self) -> Dict[str, Any]:
        """Get specialized information about the YouTube upload details agent"""
        return {
            "agent_type": "youtube_metadata_generation",
            "capabilities": [
                "Video filename generation",
                "SEO-optimized title creation",
                "Comprehensive description writing",
                "Tag generation for discoverability",
                "Thumbnail text suggestions",
                "Category recommendations",
                "Playlist organization suggestions",
                "End screen content recommendations",
            ],
            "metadata_components": [
                "Clean, SEO-friendly file names",
                "Click-worthy titles (60 char limit)",
                "Structured descriptions (2000-3000 chars)",
                "15-30 relevant tags",
                "Thumbnail text (3-7 words)",
                "Category selection with justification",
                "Playlist suggestions",
                "End screen recommendations",
            ],
            "optimization_focus": [
                "Search engine optimization (SEO)",
                "Click-through rate (CTR) optimization",
                "Discoverability enhancement",
                "Engagement maximization",
                "Algorithm-friendly formatting",
                "Accessibility considerations",
            ],
            "seo_strategies": [
                "Primary keyword integration",
                "Long-tail keyword inclusion",
                "Question-based keywords",
                "Trending topic integration",
                "Competitor analysis insights",
                "YouTube autocomplete optimization",
            ],
        }

    def generate_upload_details(
        self,
        script_content: str,
        script_title: str = None,
        target_audience: str = "general",
        video_length: str = None,
        primary_keywords: List[str] = None,
        channel_focus: str = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        Generate comprehensive YouTube upload details from script content

        Args:
            script_content: The complete script content to analyze
            script_title: Title of the script (extracted if not provided)
            target_audience: Target audience for the content (e.g., "beginners", "professionals")
            video_length: Approximate video length (e.g., "10 minutes", "5-7 minutes")
            primary_keywords: List of primary keywords to focus on (optional)
            channel_focus: Channel focus/niche (e.g., "productivity", "tech reviews")
            timeout: Maximum time to wait for response

        Returns:
            Dictionary containing all YouTube upload details
        """

        # Extract title if not provided
        if not script_title:
            lines = script_content.split("\n")
            for line in lines[:10]:  # Check first 10 lines for title
                if line.strip() and not line.startswith("#"):
                    script_title = line.strip()
                    break
            if not script_title:
                script_title = "Untitled Video"

        # Build keyword context
        keyword_context = ""
        if primary_keywords:
            keyword_context = f"\n        Primary Keywords to emphasize: {', '.join(primary_keywords)}"

        # Build channel context
        channel_context = ""
        if channel_focus:
            channel_context = (
                f"\n        Channel Focus/Niche: {channel_focus}"
            )

        # Calculate expected video duration for VALIDATION (not passed to agent)
        # Agent will do its own calculation - we use this to validate the result
        word_count = len(script_content.split())
        # Average speaking pace: 150 words per minute
        estimated_minutes = word_count / 150
        estimated_seconds = int(estimated_minutes * 60)

        # Format as minutes:seconds for validation
        duration_mins = estimated_seconds // 60
        duration_secs = estimated_seconds % 60
        calculated_duration = f"{duration_mins}:{duration_secs:02d}"

        print(
            f"📊 Client-side validation: {word_count} words = {calculated_duration} estimated duration")

        # Build video length context (only user-provided target, not our calculation)
        length_context = ""
        if video_length:
            length_context = f"\n        Target Video Length: {video_length}"

        query = f"""
        MANDATORY INSTRUCTION: You are a YouTube Upload Details Specialist. 
        You must IMMEDIATELY generate comprehensive YouTube upload metadata based on the provided script.
        DO NOT ask clarifying questions. DO NOT request additional information. 
        ANALYZE THE SCRIPT AND CREATE ALL UPLOAD DETAILS NOW.

        IMMEDIATE ACTION REQUIRED: Generate complete YouTube upload details for this video:

        SCRIPT CONTENT TO ANALYZE:
        {script_content}

        SCRIPT CONTEXT:
        - Script Title: {script_title}
        - Target Audience: {target_audience}{keyword_context}{channel_context}{length_context}

        REQUIRED OUTPUT SECTIONS (Use exact markdown format):

        ## 📁 FILE NAME
        Generate a clean, SEO-friendly filename:
        - Lowercase, hyphen-separated words
        - Include primary keyword
        - No special characters
        - Maximum 60 characters
        - Example format: "best-ai-tools-productivity-2025"

        ## 🎬 VIDEO TITLE
        Create an engaging, optimized title:
        - Include primary keywords naturally
        - TARGET ≤ 60 characters so the title displays cleanly without truncation
        - HARD LIMIT 100 characters (YouTube's max) — only exceed 60 if the extra words materially help SEO/CTR
        - Use power words and numbers when appropriate
        - Create curiosity and promise value
        - Examples: "10 AI Tools That Will 10X Your Productivity in 2025"

        ## 📝 DESCRIPTION
        Write a comprehensive 2000-3000 character description with these sections:

        **HOOK (First 150 chars - appears in search):**
        Front-load keywords and create interest

        **OVERVIEW:**
        What viewers will learn (use bullet points)

        **TIMESTAMPS:**
        📌 Create chapter markers for MAJOR topic shifts only — NOT one per transcript line
        📌 If the input is a Whisper/Otter timestamped transcript (a timecode every few seconds),
           those are RAW SEGMENTS, not chapters. Collapse them into a small number of major chapters.
        📌 STRICT chapter-count limits:
           - Always start with `0:00 Introduction`
           - Videos under 20 minutes: target 5–8 chapters total
           - Videos 20–60 minutes: target 8–12 chapters total
           - NEVER exceed 12 chapters regardless of length
           - Each chapter must be at least 60 seconds long; merge adjacent topics if shorter
        📌 If the script has MANUALLY-AUTHORED timestamps (sparse, one per real chapter), use those exactly.
           Do NOT apply this rule to dense transcript timecodes.
        📌 Use only timecodes that appear in the input — never invent or estimate
        📌 Do NOT create timestamps that exceed the video length
        Format: 0:00 Introduction
                2:15 Chapter Title
                5:30 Next Section
                (etc.)

        **TOOLS & RESOURCES:**
        🔗 List all tools mentioned with full URLs
        Include any resources referenced in the script

        **CONNECT WITH US:**
        📱 [Your Social Media Placeholders]
        
        **HASHTAGS:**
        Include 3-5 relevant hashtags at the end

        **CALL TO ACTION:**
        Encourage likes, subscribes, and comments

        ## 🏷️ TAGS
        Generate 15-30 relevant tags (comma-separated):
        - Primary keyword variations
        - Related topics and subtopics
        - Tool names from the script
        - Year/date tags (e.g., "2025")
        - Audience tags (e.g., "for beginners")
        - Format tags (e.g., "tutorial", "guide")
        - Mix of broad and specific tags

        ## 🖼️ THUMBNAIL
        Specify both the image spec AND the text overlay so the editor can build the asset:

        **Image spec (required for upload):**
        - 1280×720 (16:9), under 2 MB
        - High contrast, subject/face clearly visible at small sizes
        - PNG or JPG
        - Should visually pair with the title for CTR

        **Text overlay (3–7 words max):**
        - Bold, attention-grabbing phrase
        - High contrast against background
        - Examples: "10 AI TOOLS", "GAME CHANGER"

        **Suggested thumbnail concept (1–2 sentences):**
        Describe the visual (subject, expression, background, text placement) tailored to THIS script.

        ## 📂 CATEGORY
        Recommend the best YouTube category:
        - Select from: Education, Science & Technology, Howto & Style, Entertainment, etc.
        - Provide brief justification

        ## 📚 PLAYLIST SUGGESTIONS
        Suggest 2-3 relevant playlist names:
        - Think about series potential
        - Consider content organization
        - Help with channel structure

        ## 🎯 END SCREEN RECOMMENDATIONS
        YouTube end screens have 4 slots. Recommend a value for each, marking any
        slot OPTIONAL when we may not have the link yet (e.g. "best video" if no
        evergreen pick exists). Format each on its own line:
        - Slot 1 — Subscribe button (always required)
        - Slot 2 — Latest video: <auto = "Most recent upload"> (no link needed)
        - Slot 3 — Best video (OPTIONAL): <suggested topic/title if known, else "TBD — leave blank if no evergreen pick">
        - Slot 4 — Playlist (OPTIONAL): <suggested playlist name from the PLAYLIST SUGGESTIONS section, else "TBD">
        Note: Slots 3 and 4 can be left empty in YouTube Studio if a link isn't ready yet.

        ## 🤖 PROMPTS MENTIONED IN THIS EPISODE
        Scan the ENTIRE script for any ChatGPT / AI prompts that are shown,
        spoken aloud, narrated, or described. A "prompt" is ANY direct
        instruction the speaker tells the viewer to send to an AI tool —
        regardless of whether it's quoted, on-screen, or simply spoken in
        flowing narration.

        TRIGGER PHRASES that almost always introduce a prompt (capture the
        sentence(s) that follow, not just the trigger):
        - "Here's the prompt I used…"  /  "Here is the prompt…"
        - "Type this into ChatGPT / Gemini / Claude / Grok…"
        - "Paste this into…"  /  "Copy and paste…"
        - "Use this one exactly…"  /  "Use this prompt…"
        - "For example, use…"  /  "Example prompt…"
        - "Ask the AI…"  /  "Ask your AI…"  /  "Ask ChatGPT…"
        - "Tell the AI…"  /  "Say to the AI…"
        - "In your prompt, type / say / write / ask…"
        - "Try this: …"  /  "Try saying…"
        - Any second-person imperative aimed at the AI assistant
          (e.g. "Give me…", "Generate…", "Suggest…", "Why might…",
          "Walk me through…") that the host is instructing the viewer to send

        HOW TO EXTRACT:
        - Capture the FULL prompt body — usually the next 1–4 sentences after
          the trigger, up to the next natural narration break (when the host
          stops speaking AS the prompt and resumes speaking ABOUT the prompt).
        - Strip leading transcript timestamps like "[00:02:44]".
        - Preserve the prompt's wording; light cleanup is OK (e.g. join
          sentences split across timestamp lines, fix obvious transcription
          punctuation), but do NOT paraphrase or summarize.
        - If the host gives a long profile/persona setup followed by a focused
          request, list each as a SEPARATE numbered prompt (e.g. "Profile
          prompt" + "Meal-idea prompt").
        - List EACH prompt on its own numbered line.
        - Aim for completeness: a 10-minute AI-tutorial episode typically has
          3–8 prompts. If you found 0–1 in such an episode, RE-SCAN — you are
          almost certainly missing narrated prompts.
        - Only write "No AI prompts identified in this episode." if the script
          genuinely contains no AI instructions of any kind (e.g. a non-AI
          topic).
        - Do NOT invent prompts that are not in the script.

        ## � COMMUNITY POST (day-of-publish)
        Write a ready-to-paste Community tab post (NOT just ideas). Should be:
        - 1–3 short sentences
        - Teases the value of the video without spoiling the payoff
        - Ends with a question or CTA to drive comments
        - Includes 1–2 hashtags from the description's HASHTAGS section
        - Optional: mention if there's a poll worth attaching (e.g. "Which tool do you use?")
        Provide the post text inside a fenced code block so it's easy to copy.

        ## 💡 ADDITIONAL NOTES
        Provide upload tips:
        - Best posting times
        - Pinned comment suggestions
        - Engagement strategies

        ## 🎬 STUDIO DETAILS (copy-paste ready into YouTube Studio)
        Emit concrete recommended values for each Studio field, derived from the script.
        Do NOT write generic instructions — fill in the actual value or recommendation.
        - Audience — Made for Kids: No / Yes  (REQUIRED — cannot publish without setting this)
        - Altered content (synthetic media disclosure): Yes — uses AI-generated avatar narration (HeyGen) / No
          (REQUIRED in Studio. If the script is narrated by a HeyGen avatar, mark Yes.)
        - Video language: English (United States)
        - Captions: Upload `.srt` if available (OPTIONAL — leave auto-captions on if no SRT yet).
          When auto-captions are used, REVIEW them for proper nouns and technical terms
          (e.g. "Azure AI Foundry", "MAI-1-Preview", model names, tool names from this script)
          before going public.
        - Caption certification: Captions were not substantively edited
        - Recording date: <today's date if unknown, else date mentioned in script>
        - Recording location: <city/region if mentioned in script, else leave blank>
        - License: Standard YouTube License
        - Allow embedding: Yes
        - Publish to subscriptions feed and notify subscribers: Yes
        - Shorts sampling: Allow / Don't allow  (recommend based on whether content has self-contained short clips)
        - Comments: Allow all / Hold potentially inappropriate for review / Hold all / Disable  (recommend with 1-line reason)
        - Comment ranking: Top comments
        - Automatic chapters: OFF  (manual chapters in description take precedence)

        ## 🛡️ AD SUITABILITY SELF-RATING
        For EACH category below, mark the level (None / Limited) and quote the exact script
        line that triggered it. If nothing in the script triggers a category, mark "None".
        - Inappropriate language: None / Limited — "<quote>"
        - Adult content: None / Limited — "<quote>"
        - Violence: None / Limited — "<quote>"
        - Harmful or dangerous acts: None / Limited — "<quote>"
        - Hateful & derogatory content: None / Limited — "<quote>"
        - Recreational drugs & drug-related content: None / Limited — "<quote>"
        - Firearms-related content: None / Limited — "<quote>"
        - Controversial issues & sensitive events: None / Limited — "<quote>"
        - Tobacco-related content: None / Limited — "<quote>"
        Overall expected rating: Suitable for all advertisers / Limited or no ads — <reason>

        ## 💰 MONETIZATION (skip if channel is not in YPP)
        - Monetization: On / Off (recommend with reason based on content + ad suitability)
        - Ad formats to enable: Display, Overlay, Skippable video ads, Non-skippable video ads, Bumper, Sponsored cards
        - Ad formats to disable for this video: <list any that hurt UX for this content, with reason — or "None">
        - Mid-roll ads: Only applicable if final video length ≥ 8:00.
          If applicable, recommend specific timestamps that fall on chapter breaks from
          the TIMESTAMPS section above. Rules:
            - At least 30 seconds AFTER the intro ends
            - At least 30 seconds BEFORE the outro / CTA begins
            - Never mid-sentence — always at a chapter boundary
            - Maximum 1 mid-roll per ~6 minutes of runtime
          Format: <mm:ss> (end of "<chapter name>")
          If video is < 8:00, write: "Not applicable (video under 8:00)."

        ## 🎴 CARDS (Video elements panel)
        Suggest up to 5 cards. Each card needs a TYPE, TIMESTAMP, and PURPOSE.
        Card types: Video, Playlist, Channel, Link.
        Only suggest a card if the script genuinely references something cardable
        (a tool, a related episode, a channel, etc.). Do not invent links.
        Format:
        1. <0:30> Channel — subscribe prompt
        2. <chapter timestamp> Video — link to <related video name if mentioned, else placeholder>
        3. <chapter timestamp> Link — link to <tool URL from script>
        ...
        If nothing in the script warrants a card beyond #1, write: "Only the subscribe-prompt card recommended."

        ## 👁️ VISIBILITY & SCHEDULING
        IMPORTANT: This pipeline NEVER publishes to Public from the app. The video is
        uploaded as Private or Unlisted, and the user toggles it to Public manually in
        YouTube Studio after review. Therefore:
        - Privacy: Private (recommended for first review) / Unlisted / Scheduled
          (do NOT recommend "Public" here — public is a manual Studio action)
        - Schedule: <day of week> <time> <timezone>  (recommend an optimal slot for the target audience timezone, only if Privacy = Scheduled)
        - Premiere: Yes / No  (Yes = good for tutorials, announcements, episodic content;
          No = evergreen reference content; recommend with 1-line reason)
        - If Premiere = Yes: countdown 2 minutes, instant Premiere = No
        - First-comment pin: <suggested pinned comment text drawn from the script's CTA or a key takeaway>

        ## ✅ PRE-PUBLISH CHECKLIST
        Render as a markdown checklist (use "- [ ]"). Tailor item values to this video.
        - [ ] Title ≤ 60 chars (or ≤ 100 hard limit) and primary keyword in first 40
        - [ ] Description first 150 chars contain primary keyword
        - [ ] Tags include primary keyword + 5–10 variations
        - [ ] Thumbnail uploaded (1280×720, < 2 MB, high contrast, matches THUMBNAIL section)
        - [ ] Made for Kids set (REQUIRED)
        - [ ] Altered content disclosure set (REQUIRED if HeyGen avatar narration)
        - [ ] Video language set
        - [ ] Captions reviewed (auto-caps OK; upload `.srt` if available — proper nouns checked)
        - [ ] Category + playlists set
        - [ ] End screen — Subscribe + Latest video set; Best video & Playlist optional
        - [ ] Cards configured (at minimum: subscribe-prompt card)
        - [ ] Ad suitability self-rated
        - [ ] Mid-roll placements set (if ≥ 8:00)
        - [ ] Visibility = Private/Unlisted (Public toggle is done in YouTube Studio)
        - [ ] Community post ready to publish day-of
        - [ ] First comment ready to pin after publish

        CRITICAL REQUIREMENTS:
        1. Extract ALL tools/resources mentioned in the script with accurate URLs
        2. Create timestamps based on actual chapter structure in the script
        3. Ensure all keywords are relevant to the actual content
        4. Make the description scannable with clear sections
        5. Optimize for both YouTube search and suggested videos
        6. Balance SEO optimization with natural, engaging language
        7. Include specific details from the script (tool names, features, etc.)
        8. Make the title and thumbnail text work together for CTR
        9. Consider the target audience in all recommendations
        10. Ensure accessibility in formatting and structure
        11. Extract ALL AI/ChatGPT prompts verbatim for the Prompts section
        12. STUDIO DETAILS, AD SUITABILITY, MONETIZATION, CARDS, VISIBILITY, and CHECKLIST sections
            MUST contain concrete recommended values derived from THIS script — not placeholders
            or generic instructions. Every line should be ready to copy-paste into YouTube Studio.
        13. If the script clearly indicates HeyGen avatar narration ("**Host:**" sections targeted
            at an avatar template), set Altered Content disclosure to Yes in STUDIO DETAILS.
        14. AD SUITABILITY ratings MUST be evidence-based: quote the script line, or mark None.
        15. Mid-roll ad timestamps MUST come from the TIMESTAMPS section's chapter boundaries.

        SEO OPTIMIZATION PRIORITIES:
        - Front-load keywords in title and description
        - Use long-tail keywords naturally
        - Include question-based keywords
        - Reference trending topics when relevant
        - Use tool/brand names for search traffic
        - Balance broad and niche tags

        ENGAGEMENT OPTIMIZATION:
        - Create curiosity gaps
        - Use emotional triggers
        - Include specific numbers and timeframes
        - Promise clear value/outcomes
        - Use action verbs
        - Create urgency when appropriate

        Generate all sections now using the exact markdown format specified.
        """

        # Create thread and send message to agent
        thread = self.create_thread()
        if not thread:
            return {
                "success": False,
                "error": "Failed to create thread",
                "upload_details": "",
            }

        # Send the query and get response
        result = self.send_message(
            thread_id=thread.id,
            message_content=query,
            show_sources=False,
            timeout=timeout,
        )

        # Parse the response to extract structured data
        response_text = result.get("response") or ""

        # Detect content-filter / safety refusals from the model so callers
        # don't write a 1-line "I'm sorry…" file to disk and silently fail.
        # Refusals are usually very short AND start with a stock refusal
        # phrase AND contain no markdown structure (no "##" headings).
        refusal_phrases = (
            "i'm sorry, but i cannot",
            "i'm sorry, i cannot",
            "i am sorry, but i cannot",
            "i cannot assist with that",
            "i cannot help with that",
            "i can't assist with that",
            "i can't help with that",
            "i am unable to assist",
            "i am not able to assist",
        )
        stripped = response_text.strip()
        looks_like_refusal = (
            len(stripped) < 600
            and "##" not in stripped
            and any(stripped.lower().startswith(p) or p in stripped.lower()[:200] for p in refusal_phrases)
        )

        if looks_like_refusal:
            # One-shot retry with a softer framing that's less likely to trip
            # the safety filter (drop "MANDATORY"/"IMMEDIATE ACTION" framing,
            # make it sound like a plain content-marketing task).
            softer = (
                "You are helping a content creator prepare YouTube metadata for "
                "an educational video they just produced. The transcript is "
                "below. Please generate the same set of markdown sections as "
                "before (file name, title, description with timestamps, tags, "
                "thumbnail concept, category, playlists, end-screen, prompts "
                "mentioned, community post, studio details, ad suitability, "
                "monetization, cards, visibility, pre-publish checklist). "
                "This is standard YouTube SEO/metadata work — nothing else.\n\n"
                f"SCRIPT TITLE: {script_title}\n"
                f"TARGET AUDIENCE: {target_audience}{keyword_context}{channel_context}{length_context}\n\n"
                "TRANSCRIPT:\n"
                f"{script_content}"
            )
            print("⚠️ Agent returned a refusal — retrying once with softer framing…")
            retry_thread = self.create_thread()
            if retry_thread:
                retry_result = self.send_message(
                    thread_id=retry_thread.id,
                    message_content=softer,
                    show_sources=False,
                    timeout=timeout,
                )
                retry_text = (retry_result.get("response") or "").strip()
                retry_is_refusal = (
                    len(retry_text) < 600
                    and "##" not in retry_text
                    and any(p in retry_text.lower()[:200] for p in refusal_phrases)
                )
                if retry_text and not retry_is_refusal:
                    response_text = retry_text
                    result = retry_result
                else:
                    return {
                        "success": False,
                        "error": (
                            "The Azure agent's safety filter refused this transcript "
                            "even after a softer retry. The model returned: "
                            f"{stripped[:300]!r}. Try renaming the video to remove ALL-CAPS "
                            "words (e.g. 'ZERO Knowledge' → 'Zero Knowledge'), then re-run."
                        ),
                        "upload_details": "",
                        "raw_response": result,
                    }
            else:
                return {
                    "success": False,
                    "error": (
                        "The Azure agent's safety filter refused this transcript and "
                        "the retry thread could not be created. Model said: "
                        f"{stripped[:300]!r}"
                    ),
                    "upload_details": "",
                    "raw_response": result,
                }

        # VALIDATION: Check if agent's timestamps exceed our calculated duration
        if response_text:
            try:
                self._validate_timestamps(
                    response_text, estimated_seconds, calculated_duration)
            except Exception as _validation_err:
                print(f"⚠️ Timestamp validation skipped: {_validation_err}")

        return {
            "success": result.get("success", False),
            "upload_details": response_text,
            "raw_response": result,
            "script_title": script_title,
            "metadata": {
                "target_audience": target_audience,
                "video_length": video_length,
                "primary_keywords": primary_keywords,
                "channel_focus": channel_focus,
                "calculated_duration": calculated_duration,
                "word_count": word_count,
            },
        }

    def extract_filename(self, upload_details: str) -> str:
        """Extract the suggested filename from the upload details"""
        import re

        match = re.search(r"## 📁 FILE NAME\s+(.+?)(?:\n\n|##)",
                          upload_details, re.DOTALL)
        if match:
            # Get the filename and clean it
            filename = match.group(1).strip().split("\n")[0].strip()
            # Remove any markdown formatting or extra text
            filename = re.sub(r"[`*_]", "", filename)
            return filename
        return "video-upload"

    def extract_title(self, upload_details: str) -> str:
        """Extract the suggested video title from the upload details"""
        import re

        match = re.search(r"## 🎬 VIDEO TITLE\s+(.+?)(?:\n\n|##)",
                          upload_details, re.DOTALL)
        if match:
            title = match.group(1).strip().split("\n")[0].strip()
            # Remove markdown formatting
            title = re.sub(r"[`*_]", "", title)
            return title
        return "Untitled Video"

    def extract_tags(self, upload_details: str) -> List[str]:
        """Extract the suggested tags as a list from the upload details"""
        import re

        match = re.search(r"## 🏷️ TAGS\s+(.+?)(?:\n\n|##)",
                          upload_details, re.DOTALL)
        if match:
            tags_text = match.group(1).strip()
            # Split by commas and clean each tag
            tags = [tag.strip() for tag in tags_text.split(",")]
            # Remove empty tags
            tags = [tag for tag in tags if tag]
            return tags
        return []

    def extract_description(self, upload_details: str) -> str:
        """Extract the video description from the upload details"""
        import re

        match = re.search(r"## 📝 DESCRIPTION\s+(.+?)(?:\n\n##)",
                          upload_details, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    def format_for_console_display(self, upload_details: str) -> str:
        """Format the upload details for clean console display"""
        # Add some visual separation and formatting
        separator = "=" * 80
        return f"\n{separator}\n{upload_details}\n{separator}\n"

    def get_quick_summary(self, upload_details: str) -> Dict[str, str]:
        """Get a quick summary of key upload details"""
        return {
            "filename": self.extract_filename(upload_details),
            "title": self.extract_title(upload_details),
            "tags_count": len(self.extract_tags(upload_details)),
            "description_length": len(self.extract_description(upload_details)),
        }

    def _validate_timestamps(self, upload_details: str, max_seconds: int, duration_str: str) -> None:
        """Validate that agent's timestamps don't exceed calculated duration"""
        import re

        # Extract all timestamps from the response (format: MM:SS or M:SS or H:MM:SS)
        timestamp_pattern = r'(?:^|\s)(\d{1,2}):([0-5]\d)(?::([0-5]\d))?'
        matches = re.findall(timestamp_pattern, upload_details)

        if not matches:
            print("⚠️ No timestamps found in agent response")
            return

        max_timestamp = 0
        max_timestamp_str = "0:00"
        invalid_count = 0

        for match in matches:
            hours = 0
            minutes = int(match[0])
            seconds = int(match[1])

            # Check if H:MM:SS format (match[2] would be seconds, match[1] would be minutes)
            if match[2]:  # H:MM:SS format
                hours = minutes
                minutes = seconds
                seconds = int(match[2])

            # Convert to total seconds
            total_seconds = (hours * 3600) + (minutes * 60) + seconds

            if total_seconds > max_timestamp:
                max_timestamp = total_seconds
                if hours > 0:
                    max_timestamp_str = f"{hours}:{minutes:02d}:{seconds:02d}"
                else:
                    max_timestamp_str = f"{minutes}:{seconds:02d}"

            # Check if exceeds calculated duration
            if total_seconds > max_seconds:
                invalid_count += 1

        # Report validation results
        if invalid_count > 0:
            print(
                f"❌ VALIDATION FAILED: {invalid_count} timestamp(s) exceed calculated duration")
            print(f"   Max timestamp in response: {max_timestamp_str}")
            print(f"   Calculated duration limit: {duration_str}")
            print(f"   Agent should calculate duration from word count!")
        else:
            print(
                f"✅ VALIDATION PASSED: All timestamps within {duration_str} limit")
            print(f"   Max timestamp found: {max_timestamp_str}")
