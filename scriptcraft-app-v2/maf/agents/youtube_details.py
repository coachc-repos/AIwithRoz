"""
MAF migration — Step 3: Script-Youtube-Upload-Details-Agent as code.

Re-creates the Foundry portal agent `Script-Youtube-Upload-Details-Agent` as a
CODE-DEFINED Microsoft Agent Framework agent on Claude Opus 5.5 (the model
policy; the portal agent also runs claude-opus-5-5 since its v11), with
Foundry's hosted web search attached. Web search matters here: the description
lists every tool in the script with its URL.

Drop-in contract: `generate_upload_details()` sends the SAME request as
`linedrive_azure/agents/youtube_upload_details_agent_client.py` (checked
byte-for-byte), including the client's one-shot "softer framing" retry when the
model refuses, and returns the same keys web_gui.py reads (success,
upload_details, script_title, metadata). The client's extract_* helpers and its
timestamp check are ported as functions.

--compare runs the code agent and the portal agent on the same script and
scores what the app extracts (title, filename, tags, description), the
timestamps against the script's word-count duration (the client's check), the
tool links in the description, and how many of those links came from the
agent's own web search results.

    maf/.venv/bin/python maf/agents/youtube_details.py --compare --dump /tmp/yt_cmp
    maf/.venv/bin/python maf/agents/youtube_details.py --script-file s.md --title "..."

Scoped to maf/, no web_gui.py changes, isolated venv.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_framework import Agent  # noqa: E402

from agents._common import (  # noqa: E402
    CLAUDE_MODEL,
    REFERENCE_TITLE,
    build_code_agent as _build_agent,
    evidence_line,
    is_truncated,
    load_instructions as _load_instructions,
    load_reference_script,
    model_line,
    portal_agent,
    run_response,
    search_evidence,
)
from observability import load_env, make_credential, setup_tracing  # noqa: E402

AGENT_NAME = "Script-Youtube-Upload-Details-Agent"
MODEL = os.environ.get("MAF_YOUTUBE_MODEL", CLAUDE_MODEL)
MAX_TOKENS = int(os.environ.get("MAF_YOUTUBE_MAX_TOKENS", "16000"))


def load_instructions() -> str:
    return _load_instructions(AGENT_NAME)


def build_code_agent(credential=None) -> Agent:
    return _build_agent(name="Script-Youtube-Upload-Details-Agent (code)", instructions=load_instructions(),
                        model=MODEL, max_tokens=MAX_TOKENS, credential=credential)


def _contexts(script_content: str, script_title: Optional[str], primary_keywords, channel_focus, video_length):
    """The client's derived values, computed exactly as it does."""
    if not script_title:
        for line in script_content.split("\n")[:10]:
            if line.strip() and not line.startswith("#"):
                script_title = line.strip()
                break
        if not script_title:
            script_title = "Untitled Video"
    keyword_context = (f"\n        Primary Keywords to emphasize: {', '.join(primary_keywords)}"
                       if primary_keywords else "")
    channel_context = f"\n        Channel Focus/Niche: {channel_focus}" if channel_focus else ""
    length_context = f"\n        Target Video Length: {video_length}" if video_length else ""
    word_count = len(script_content.split())
    estimated_seconds = int(word_count / 150 * 60)
    calculated_duration = f"{estimated_seconds // 60}:{estimated_seconds % 60:02d}"
    return script_title, keyword_context, channel_context, length_context, word_count, estimated_seconds, calculated_duration


def build_request_message(script_content: str, script_title: Optional[str] = None,
                          target_audience: str = "general", video_length: Optional[str] = None,
                          primary_keywords: Optional[List[str]] = None,
                          channel_focus: Optional[str] = None) -> str:
    """Verbatim copy of the request the app client sends (keep in sync)."""
    script_title, keyword_context, channel_context, length_context, *_ = _contexts(
        script_content, script_title, primary_keywords, channel_focus, video_length)
    return f"""
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


def build_softer_message(script_content: str, script_title: Optional[str] = None,
                         target_audience: str = "general", video_length: Optional[str] = None,
                         primary_keywords: Optional[List[str]] = None,
                         channel_focus: Optional[str] = None) -> str:
    """The client's one-shot retry wording after a refusal (verbatim)."""
    script_title, keyword_context, channel_context, length_context, *_ = _contexts(
        script_content, script_title, primary_keywords, channel_focus, video_length)
    return (
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


_REFUSAL_PHRASES = (
    "i'm sorry, but i cannot", "i'm sorry, i cannot", "i am sorry, but i cannot",
    "i cannot assist with that", "i cannot help with that", "i can't assist with that",
    "i can't help with that", "i am unable to assist", "i am not able to assist",
)


def looks_like_refusal(text: str) -> bool:
    stripped = (text or "").strip()
    return (len(stripped) < 600 and "##" not in stripped
            and any(stripped.lower().startswith(p) or p in stripped.lower()[:200] for p in _REFUSAL_PHRASES))


# Ports of the client's extract_* helpers (verbatim regexes).
def extract_filename(upload_details: str) -> str:
    m = re.search(r"## 📁 FILE NAME\s+(.+?)(?:\n\n|##)", upload_details, re.DOTALL)
    return re.sub(r"[`*_]", "", m.group(1).strip().split("\n")[0].strip()) if m else "video-upload"


def extract_title(upload_details: str) -> str:
    m = re.search(r"## 🎬 VIDEO TITLE\s+(.+?)(?:\n\n|##)", upload_details, re.DOTALL)
    return re.sub(r"[`*_]", "", m.group(1).strip().split("\n")[0].strip()) if m else "Untitled Video"


def extract_tags(upload_details: str) -> List[str]:
    m = re.search(r"## 🏷️ TAGS\s+(.+?)(?:\n\n|##)", upload_details, re.DOTALL)
    return [t for t in (x.strip() for x in m.group(1).strip().split(",")) if t] if m else []


def extract_description(upload_details: str) -> str:
    m = re.search(r"## 📝 DESCRIPTION\s+(.+?)(?:\n\n##)", upload_details, re.DOTALL)
    return m.group(1).strip() if m else ""


def check_timestamps(upload_details: str, max_seconds: int) -> dict:
    """The client's _validate_timestamps, returning its findings instead of printing."""
    found, latest, over = 0, 0, 0
    for mm, ss, extra in re.findall(r'(?:^|\s)(\d{1,2}):([0-5]\d)(?::([0-5]\d))?', upload_details):
        h, m_, s_ = (int(mm), int(ss), int(extra)) if extra else (0, int(mm), int(ss))
        total = h * 3600 + m_ * 60 + s_
        found += 1
        latest = max(latest, total)
        over += total > max_seconds
    return {"timestamps": found, "latest": f"{latest // 60}:{latest % 60:02d}", "past_duration": over}


async def generate_upload_details(script_content: str, script_title: Optional[str] = None,
                                  target_audience: str = "general", video_length: Optional[str] = None,
                                  primary_keywords: Optional[List[str]] = None,
                                  channel_focus: Optional[str] = None, credential=None, agent=None,
                                  label: str = "code") -> dict:
    """Code-agent equivalent of YouTubeUploadDetailsAgentClient.generate_upload_details()."""
    title, *_, word_count, estimated_seconds, calculated_duration = _contexts(
        script_content, script_title, primary_keywords, channel_focus, video_length)
    agent = agent or build_code_agent(credential)
    args = (script_content, script_title, target_audience, video_length, primary_keywords, channel_focus)
    try:
        resp = await run_response(agent, build_request_message(*args), label)
        text = (resp.text or "").strip()
        retried = False
        if looks_like_refusal(text):
            resp = await run_response(agent, build_softer_message(*args), label + " retry")
            text, retried = (resp.text or "").strip(), True
            if looks_like_refusal(text) or not text:
                return {"success": False, "upload_details": "", "error": "refused even after the softer retry"}
    except Exception as e:
        return {"success": False, "upload_details": "", "error": str(e)}
    if is_truncated(resp):
        return {"success": False, "upload_details": text, "error": "reply hit max_tokens"}
    return {"success": bool(text), "upload_details": text, "script_title": title, "retried": retried,
            "search": search_evidence(resp), "_resp": resp,
            "timestamp_check": check_timestamps(text, estimated_seconds),
            "metadata": {"target_audience": target_audience, "video_length": video_length,
                         "primary_keywords": primary_keywords, "channel_focus": channel_focus,
                         "calculated_duration": calculated_duration, "word_count": word_count}}


_URL = re.compile(r"https?://[^\s)\]>\"'*]+")


def score(result: dict) -> dict:
    text = result.get("upload_details") or ""
    desc = extract_description(text)
    urls = list(dict.fromkeys(u.rstrip(".,;") for u in _URL.findall(desc or text)))
    ev = result.get("search") or {"citations": [], "web_searches": 0}
    cited = {u.rstrip("/").split("?")[0].lower() for u in ev["citations"]}
    tc = result.get("timestamp_check") or {}
    title = extract_title(text)
    return {
        "title (app extract)": (title[:34] + "…") if len(title) > 35 else title,
        "title chars": len(title),
        "filename": extract_filename(text)[:30],
        "tags": len(extract_tags(text)),
        "description chars": len(desc),
        "## sections": len(re.findall(r"(?m)^##\s", text)),
        "timestamps": tc.get("timestamps", 0),
        f"past {result.get('metadata', {}).get('calculated_duration', '?')} duration": tc.get("past_duration", 0),
        "links in description": len(urls),
        "  from own search results": sum(u.rstrip("/").split("?")[0].lower() in cited for u in urls),
        "web searches": ev.get("web_searches", 0),
        "refusal retry used": "yes" if result.get("retried") else "no",
    }


async def _compare(script: str, title: str, dump_dir: str = "", code_only: bool = False) -> None:
    cred = make_credential()
    print(model_line(AGENT_NAME, MODEL, cred))
    agents = {"CODE": build_code_agent(cred)}
    if not code_only:
        agents["PORTAL"] = portal_agent(AGENT_NAME, cred)
    print(f"Running {' then '.join(agents)} on the same script...\n")
    results = {n: await generate_upload_details(script, title, "general", "10 minutes", agent=a, label=n.lower())
               for n, a in agents.items()}
    names = list(results)
    scored = {n: (score(r) if r.get("success") else None) for n, r in results.items()}
    keys = next((list(s.keys()) for s in scored.values() if s), [])
    print("=" * (34 + 38 * len(names)))
    print(f"{'metric':<34}" + "".join(f"{n:>38}" for n in names))
    for k in keys:
        print(f"{k:<34}" + "".join(f"{str(scored[n][k]) if scored[n] else 'FAILED':>38}" for n in names))
    print("=" * (34 + 38 * len(names)))
    for n, r in results.items():
        if not r.get("success"):
            print(f"{n} FAILED: {r.get('error')}")
    if dump_dir:
        os.makedirs(dump_dir, exist_ok=True)
        for n, r in results.items():
            open(os.path.join(dump_dir, f"youtube_{n.lower()}.md"), "w", encoding="utf-8").write(r.get("upload_details") or "")
        print(f"replies saved to {dump_dir}/youtube_*.md")


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description="Code-defined YouTube Upload Details agent (step 3).")
    ap.add_argument("--script-file", help="Script (defaults to the golden reference)")
    ap.add_argument("--title", default="", help="Script title")
    ap.add_argument("--compare", action="store_true", help="Run code and portal agents and compare")
    ap.add_argument("--code-only", action="store_true", help="With --compare: skip the portal call")
    ap.add_argument("--dump", default="", metavar="DIR", help="With --compare: save both replies")
    args = ap.parse_args()
    print(f"tracing : {setup_tracing()}")
    if args.script_file:
        script = open(args.script_file, encoding="utf-8").read().strip()
        title = args.title or os.path.splitext(os.path.basename(args.script_file))[0]
    else:
        script, title = load_reference_script(), (args.title or REFERENCE_TITLE)
    if args.compare:
        asyncio.run(_compare(script, title, args.dump, args.code_only))
    else:
        r = asyncio.run(generate_upload_details(script, title))
        print(r.get("upload_details") or r.get("error"))


if __name__ == "__main__":
    main()
