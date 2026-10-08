#!/usr/bin/env python3
"""
Script Review Agent Client - Specialized client for script review and feedback

This agent handles script review, content analysis, feedback generation,
and improvement suggestions for various types of written content.
"""

from typing import Dict, Any, List
from .base_agent_client import BaseAgentClient


class ScriptReviewAgentClient(BaseAgentClient):
    """Specialized client for script review and content analysis"""

    def __init__(self):
        """Initialize the Script Review Agent"""
        super().__init__(
            agent_id="asst_MeeUTGVUBItaslmikiJ1qhd9", agent_name="Script-Review-Agent"
        )

    def get_specialized_info(self) -> Dict[str, Any]:
        """Get specialized information about the script review agent"""
        return {
            "agent_type": "script_review",
            "capabilities": [
                "Script analysis and critique",
                "Content structure evaluation",
                "Dialogue assessment",
                "Pacing and flow analysis",
                "Character development review",
                "Technical accuracy checking",
            ],
            "review_types": [
                "Comprehensive script analysis",
                "Focused content review",
                "Quick feedback sessions",
                "Technical accuracy checks",
                "Audience suitability assessment",
                "Production feasibility review",
            ],
            "content_types": [
                "Video scripts",
                "Podcast scripts",
                "Social media content",
                "Educational materials",
                "Marketing content",
                "Training scripts",
            ],
            "feedback_areas": [
                "Story structure and flow",
                "Character development",
                "Dialogue quality",
                "Technical accuracy",
                "Audience engagement",
                "Production considerations",
            ],
        }

    def review_script(
        self,
        script_content: str,
        script_type: str = "video script",
        review_focus: List[str] = None,
        target_audience: str = "general",
        specific_concerns: str = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        Conduct a comprehensive script review

        Args:
            script_content: The script content to review
            script_type: Type of script being reviewed
            review_focus: Specific areas to focus the review on
            target_audience: Intended audience for the script
            specific_concerns: Any specific concerns to address
            timeout: Maximum time to wait for response

        Returns:
            Detailed script review with feedback and recommendations
        """
        query = f"""
        Please conduct a comprehensive review of this {script_type}:
        
        SCRIPT CONTENT:
        {script_content}
        
        REVIEW PARAMETERS:
        - Script Type: {script_type}
        - Target Audience: {target_audience}
        """

        if review_focus:
            query += f"\n- Focus Areas: {', '.join(review_focus)}"
        if specific_concerns:
            query += f"\n- Specific Concerns: {specific_concerns}"

        # Calculate word count for length analysis
        word_count = len(script_content.split())
        estimated_minutes = word_count / 155  # 155 words per minute

        query += f"""
        
        CRITICAL: LENGTH ANALYSIS REQUIRED
        - Current word count: ~{word_count} words
        - Estimated speaking duration: ~{estimated_minutes:.1f} minutes
        - Target should be 15 minutes (2325 words minimum)
        - Current completion: {(word_count/2325)*100:.1f}% of target length
        
        Please provide a detailed review covering:
        
        1. DURATION AND LENGTH ASSESSMENT (CRITICAL)
           - Does the script actually contain enough content for the claimed duration?
           - Is the word count sufficient for a 15-minute presentation?
           - Are sections properly detailed or just brief outlines?
           - Specific recommendations to expand content to full length
        
        2. OVERALL ASSESSMENT
           - Script strengths and effectiveness
           - Target audience alignment
           - Core message clarity
        
        3. STRUCTURE AND FLOW
           - Opening effectiveness
           - Logical progression
           - Transitions between sections
           - Conclusion impact
        
        4. CONTENT QUALITY
           - Accuracy and credibility
           - Engagement level
           - Clarity and comprehension
           - Supporting details
        
        5. TECHNICAL ELEMENTS
           - Format appropriateness
           - Production considerations
           - Timing and pacing
           - Visual/audio cues
        
        6. SPECIFIC FEEDBACK
           - Line-by-line improvements where needed
           - Suggested revisions
           - Alternative approaches
        
        6. RECOMMENDATIONS
           - Priority improvements
           - Next steps for revision
           - Additional considerations
        
        Provide actionable feedback that helps improve the script's effectiveness.
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create review thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )

    def shorten_to_target(
        self,
        script_content: str,
        target_minutes: float,
        wpm: int = 150,
        timeout: int = 600,
        target_words_override: int | None = None,
        reduction_percent: int | None = None,
        current_host_words: int | None = None,
    ) -> Dict[str, Any]:
        """
        Rewrite a script so the spoken (Host:) portion fits a target duration.

        The agent must preserve the original markdown structure (Heading: lines,
        VISUAL CUE blocks, Host: blocks) and only condense the Host: dialogue
        until the total Host word count is within ~10% of the target.

        Args:
            script_content: The script content to shorten.
            target_minutes: Desired final video length in minutes (e.g. 10).
            wpm: Words-per-minute speaking rate to plan against (default 150).
            timeout: Max time to wait for the agent response.
            target_words_override: If set, overrides the duration-derived target.
            reduction_percent: If set (e.g. 25), informs the agent of the desired
                proportional cut (used in the prompt for context).
            current_host_words: If set, used in the prompt instead of recomputing.

        Returns:
            { success: bool, response: <shortened script text>, ... }
        """
        if target_words_override is not None and target_words_override > 0:
            target_words = int(target_words_override)
        else:
            target_words = int(round(target_minutes * wpm))
        current_words = len(script_content.split())
        cur_host = (
            current_host_words
            if current_host_words is not None
            else "(not provided)"
        )
        pct_note = (
            f"- Requested reduction: ~{reduction_percent}% of current Host: words"
            if reduction_percent
            else "- Reduction implied by target Host: word count below"
        )

        query = f"""
You are condensing a video script so its narrated Host: portion fits a target
duration. Return ONLY the rewritten script content — no preamble, no commentary,
no markdown fences. Preserve the original structure exactly:
- Keep every "Heading:" line and "VISUAL CUE:" block in place.
- Keep every "Host:" speaker label.
- Do NOT add new sections, new chapters, or new visual cues.
- Do NOT remove chapters; keep the same chapter count and order.

TARGET LENGTH:
- Target video length: {target_minutes:.1f} minutes at {wpm} wpm
- Target Host: word count: ~{target_words} words (total across all Host blocks)
- Current Host: word count: {cur_host}
- Current total word count (entire script): ~{current_words} words
{pct_note}

SMART CUTTING RULES (apply in order, stop when target is reached):
1. Remove the OPENING TRANSITION paragraph at the start of chapters 2, 3, 4, 5,
   and 6 — the lines that recap what was just covered before introducing the
   new chapter's topic. Chapter 1 keeps its opening. Each chapter after #1
   should jump straight into its new content with no "Now that we've covered…"
   bridge.
2. Cut REPEATED EXAMPLES of the same concept. If a point is illustrated with
   two or three examples that make the same case, keep the strongest ONE and
   delete the others.
3. Cut REPEATED DEFINITIONS and 101-level framing. Our YouTube channel has
   progressed beyond explaining "AI is a pattern-matching engine" or basic
   what-is-AI definitions — assume the viewer already knows this and remove
   any restatement of those fundamentals.
4. Cut VAGUE / HIGH-LEVEL claims that don't move the argument forward. Keep
   specific, named, numeric, or actionable statements; drop the generic
   "AI is transforming everything" filler.
5. Collapse DUPLICATE LISTS. Keep at most ONE detailed enumerated list per
   chapter (e.g. one full "steps to do X" list). Any later list in the same
   script that covers similar ground should be reduced to a one-line summary
   of considerations rather than a full enumeration. Always preserve at least
   one detailed actionable list overall so the viewer still gets something to
   do or remember.
6. Cut FILLER and TRANSITIONAL HEDGES inside Host: blocks ("As I mentioned",
   "Like we said before", "Basically", "Essentially", "At the end of the day").
7. Only after rules 1–6 are exhausted, lightly tighten remaining Host: prose
   for concision without removing meaning.

DO NOT:
- Summarize a chapter into a paragraph. Keep the chapter shape.
- Remove the hook, the call-to-action, or the final wrap.
- Touch VISUAL CUE, B-Roll, or any production direction lines.
- Strip quotes or statistics that anchor a specific claim — those stay.

The final total Host: word count must land within ±10% of {target_words}.

SCRIPT CONTENT TO SHORTEN:
{script_content}
"""

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create shorten thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )

    def quick_feedback(
        self,
        script_content: str,
        feedback_type: str = "general",
        urgency: str = "standard",
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """
        Provide quick feedback on script content

        Args:
            script_content: The script content to review
            feedback_type: Type of feedback needed (general, technical, creative)
            urgency: Urgency level for feedback
            timeout: Maximum time to wait for response

        Returns:
            Quick feedback with key points and immediate suggestions
        """
        query = f"""
        Provide quick {feedback_type} feedback on this script content (urgency: {urgency}):
        
        SCRIPT CONTENT:
        {script_content}
        
        Please provide:
        1. IMMEDIATE IMPRESSIONS
           - What works well
           - Main areas for improvement
           - Overall effectiveness rating (1-10)
        
        2. TOP 3 PRIORITY IMPROVEMENTS
           - Most important changes needed
           - Quick wins for better impact
           - Critical issues to address
        
        3. QUICK RECOMMENDATIONS
           - Actionable next steps
           - Resources or techniques to consider
           - Timeline for improvements
        
        Keep feedback concise but actionable - focus on the most impactful improvements.
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create feedback thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )

    def compare_versions(
        self,
        original_script: str,
        revised_script: str,
        comparison_focus: List[str] = None,
        timeout: int = 240,
    ) -> Dict[str, Any]:
        """
        Compare two versions of a script and analyze improvements

        Args:
            original_script: The original script version
            revised_script: The revised script version
            comparison_focus: Specific areas to focus comparison on
            timeout: Maximum time to wait for response

        Returns:
            Detailed comparison analysis with improvement assessment
        """
        query = f"""
        Compare these two script versions and analyze the improvements:
        
        ORIGINAL VERSION:
        {original_script}
        
        REVISED VERSION:
        {revised_script}
        """

        if comparison_focus:
            query += f"\n\nFOCUS AREAS: {', '.join(comparison_focus)}"

        query += """
        
        Please provide:
        
        1. CHANGE SUMMARY
           - Major changes identified
           - Overall direction of revisions
           - Scope of improvements
        
        2. IMPROVEMENT ANALYSIS
           - What got better and why
           - Areas that may need more work
           - Effectiveness of changes made
        
        3. SIDE-BY-SIDE COMPARISON
           - Key differences in structure
           - Content additions/removals
           - Style and tone changes
        
        4. RECOMMENDATIONS
           - Further improvements needed
           - Which version works better for different aspects
           - Next revision priorities
        
        5. OVERALL ASSESSMENT
           - Progress made from original to revised
           - Remaining challenges
           - Readiness for production/use
        
        Focus on providing actionable insights about the revision process.
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create comparison thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )

    def check_technical_accuracy(
        self,
        script_content: str,
        subject_domain: str,
        accuracy_level: str = "high",
        fact_check_sources: List[str] = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        Check script content for technical accuracy and factual correctness

        Args:
            script_content: The script content to check
            subject_domain: Domain/field to check accuracy for
            accuracy_level: Required level of accuracy (basic, high, expert)
            fact_check_sources: Preferred sources for fact-checking
            timeout: Maximum time to wait for response

        Returns:
            Technical accuracy assessment with corrections and sources
        """
        query = f"""
        Check the technical accuracy of this script in the {subject_domain} domain:
        
        SCRIPT CONTENT:
        {script_content}
        
        ACCURACY REQUIREMENTS:
        - Subject Domain: {subject_domain}
        - Accuracy Level: {accuracy_level}
        """

        if fact_check_sources:
            query += f"\n- Preferred Sources: {', '.join(fact_check_sources)}"

        query += """
        
        Please provide:
        
        1. ACCURACY ASSESSMENT
           - Overall accuracy rating
           - Areas of strong factual content
           - Sections requiring verification
        
        2. FACTUAL ISSUES IDENTIFIED
           - Incorrect statements or claims
           - Outdated information
           - Misleading representations
           - Missing context or disclaimers
        
        3. CORRECTIONS NEEDED
           - Specific text that needs changing
           - Accurate alternatives
           - Updated information
           - Additional context required
        
        4. SOURCE RECOMMENDATIONS
           - Authoritative sources to reference
           - Expert consultation suggestions
           - Research resources
           - Verification methods
        
        5. CREDIBILITY ENHANCEMENTS
           - Ways to strengthen credibility
           - Disclaimer recommendations
           - Attribution suggestions
           - Professional review needs
        
        Focus on ensuring the script maintains credibility while being accessible to the target audience.
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create accuracy thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )

    def audience_suitability_check(
        self,
        script_content: str,
        target_audience: str,
        content_rating: str = "general",
        cultural_considerations: List[str] = None,
        timeout: int = 240,
    ) -> Dict[str, Any]:
        """
        Evaluate script suitability for target audience

        Args:
            script_content: The script content to evaluate
            target_audience: Target audience description
            content_rating: Desired content rating
            cultural_considerations: Cultural factors to consider
            timeout: Maximum time to wait for response

        Returns:
            Audience suitability assessment with recommendations
        """
        query = f"""
        Evaluate the audience suitability of this script:
        
        SCRIPT CONTENT:
        {script_content}
        
        AUDIENCE PARAMETERS:
        - Target Audience: {target_audience}
        - Content Rating: {content_rating}
        """

        if cultural_considerations:
            query += (
                f"\n- Cultural Considerations: {', '.join(cultural_considerations)}"
            )

        query += """
        
        Please assess:
        
        1. AUDIENCE ALIGNMENT
           - Appropriateness for target audience
           - Age-appropriate content and language
           - Interest level and engagement potential
           - Comprehension level match
        
        2. CONTENT CONCERNS
           - Potentially inappropriate content
           - Complex concepts that may need simplification
           - Cultural sensitivity issues
           - Controversial topics handling
        
        3. ACCESSIBILITY FACTORS
           - Language complexity assessment
           - Technical jargon evaluation
           - Visual/audio description needs
           - Inclusive content considerations
        
        4. ENGAGEMENT OPTIMIZATION
           - Audience interest factors
           - Attention-holding elements
           - Interactive opportunities
           - Call-to-action effectiveness
        
        5. RECOMMENDATIONS
           - Content modifications needed
           - Alternative approaches for better fit
           - Audience-specific improvements
           - Distribution considerations
        
        Ensure recommendations balance audience appropriateness with content goals.
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create suitability thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )

    def production_feasibility_review(
        self,
        script_content: str,
        production_budget: str = "moderate",
        timeline: str = "standard",
        resources_available: List[str] = None,
        timeout: int = 240,
    ) -> Dict[str, Any]:
        """
        Review script for production feasibility and requirements

        Args:
            script_content: The script content to review
            production_budget: Available production budget level
            timeline: Production timeline constraints
            resources_available: Available production resources
            timeout: Maximum time to wait for response

        Returns:
            Production feasibility assessment with recommendations
        """
        query = f"""
        Review the production feasibility of this script:
        
        SCRIPT CONTENT:
        {script_content}
        
        PRODUCTION PARAMETERS:
        - Budget Level: {production_budget}
        - Timeline: {timeline}
        """

        if resources_available:
            query += f"\n- Available Resources: {', '.join(resources_available)}"

        query += """
        
        Please assess:
        
        1. PRODUCTION REQUIREMENTS
           - Personnel needs (cast, crew, specialists)
           - Equipment requirements
           - Location needs
           - Special effects or technical needs
        
        2. BUDGET CONSIDERATIONS
           - Cost factors in the current script
           - High-cost elements to consider
           - Budget-friendly alternatives
           - Potential cost savings
        
        3. TIMELINE FEASIBILITY
           - Production complexity vs. timeline
           - Potential bottlenecks or delays
           - Critical path considerations
           - Schedule optimization opportunities
        
        4. RESOURCE OPTIMIZATION
           - Best use of available resources
           - Areas where resources may be stretched
           - Creative solutions for limitations
           - Outsourcing considerations
        
        5. SCRIPT MODIFICATIONS
           - Changes to improve feasibility
           - Alternative approaches for complex scenes
           - Simplified production options
           - Phased production possibilities
        
        Provide practical recommendations that balance creative vision with production realities.
        """

        thread = self.create_thread()
        if not thread:
            return {"success": False, "error": "Failed to create feasibility thread"}

        return self.send_message(
            thread_id=thread.id, message_content=query, timeout=timeout
        )
