"""Scoring helpers shared by the script-rewriting agents' --compare modes
(Repeat-and-Flow, Shorten). Everything here is measurement only; nothing is
sent to a model. Stats are taken on a MASKED script, i.e. with
[[PRODUCTION_BLOCK_N]] placeholders still in place (see _production_blocks.py).
"""
from __future__ import annotations

import re

from agents._production_blocks import PLACEHOLDER_RE, _PRODUCTION_BLOCK_RE

# The app's own Host-word counter, verbatim from web_gui.py (_host_word_count in
# process_existing_script, _host_word_count_create in the create flow; the two
# are identical). It decides the Shorten target and reports before/after words.
_APP_HOST_BLOCK = re.compile(
    r"(?:^|\n)\s*(?:#{1,6}\s*)?\**\s*host\s*\**\s*:\s*\**\s*([\s\S]*?)(?="
    r"\n\s*(?:#{1,6}\s+\S|(?:#{1,6}\s*)?(?:\*\*[^*\n]{1,40}\*\*\s*:|host\s*:|heading\s*:|chapter\s+\d|visual\s+cue\s*:|b-?roll\s*:)|---+|===+)"
    r"|\Z)",
    flags=re.IGNORECASE,
)


def app_host_words(text: str) -> int:
    """Host: words exactly as the app counts them (production blocks ignored)."""
    text = _PRODUCTION_BLOCK_RE.sub(" ", text or "")
    return sum(len(b.split()) for b in _APP_HOST_BLOCK.findall(text))


# Chapter headings in any layout the agents produce ("Heading: Chapter 1 - …",
# "## Chapter 1: …", "**Chapter 1: …**"), tolerant of no-break spaces.
_CHAPTER_HEADING = re.compile(
    r"^[ \t]*(?:#+[ \t]*)?\*{0,2}(?:Heading:[ \t]*)?\*{0,2}Chapter[^\S\n]+(\d+)\b[^\n]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
_HEADING_PREFIX = re.compile(r"^[ \t]*Heading:[ \t]*Chapter[ \t]+\d+", flags=re.IGNORECASE | re.MULTILINE)
# "(1:15)", "(approx. 1:15)", "(~2:30 to 4:05)", or the literal sample "(X:XX)".
_HEADING_TIMESTAMP = re.compile(r"\([^)\n]*\b(?:\d{1,2}:\d{2}|X:XX)\b[^)\n]*\)", flags=re.IGNORECASE)
# Trailing sections: "=== NAME ===" lines, or the app's "====…" rule followed by a
# "# …" heading (e.g. "# 🎬 HEYGEN READY SCRIPT", "# 🎬 B-ROLL SEARCH TERMS …").
_SECTION_TITLE = re.compile(r"^[ \t]*[#*]*[ \t]*={3}[ \t]*([A-Z][^=\n]*?)[ \t]*={3}[ \t]*\**[ \t]*$",
                            flags=re.MULTILINE)
_RULE_THEN_HEADING = re.compile(r"^[ \t]*={8,}[ \t]*\n(?:[ \t]*\n)*[ \t]*#+[ \t]*(\S[^\n]*)$",
                                flags=re.MULTILINE)
# ...or an all-caps "# …" heading appended without a rule line ("#  HEYGEN READY SCRIPT").
_CAPS_H1 = re.compile(r"^[ \t]*#[ \t]+[^A-Za-z0-9\n]*([A-Z0-9][A-Z0-9 &()\-:/'.,]{3,}?)[ \t]*$",
                      flags=re.MULTILINE)
# Agent commentary that leaked into the script: checklists, notes headings, sign-offs.
_AGENT_NOTES = re.compile(
    r"^[ \t]*(?:[-*][ \t]*\[[ xX\u2713]\]"
    r"|(?:#{1,6}|\*\*)[ \t]*(?:notes?\b|revision notes|summary of (?:changes|revisions)|checklist|voice\W{0,3}synthesis)"
    r"|\**[ \t]*notes on (?:the )?revisions?"
    r"|let me know\b)",
    flags=re.IGNORECASE | re.MULTILINE,
)
# Spaces the app's "[ \t]" chapter regexes do not match (NBSP, figure, thin, narrow NBSP).
_ODD_SPACE = re.compile("[    ]")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’]*")
_CONTRACTION = re.compile(
    r"\b(?:\w+n['’]t|\w+['’](?:re|ve|ll|m|d)|"
    r"(?:it|that|there|here|what|let|he|she|who|where)['’]s)\b",
    flags=re.IGNORECASE,
)


def words(s: str) -> int:
    return len(_WORD.findall(s or ""))


def trailing_sections(text: str, after: int) -> list[tuple[int, str]]:
    found = [(m.start(), m.group(1).strip().upper()) for m in _SECTION_TITLE.finditer(text, after)]
    for m in _RULE_THEN_HEADING.finditer(text, after):
        name = re.sub(r"^[^A-Za-z0-9]+", "", m.group(1)).strip().upper()
        if name:
            found.append((m.start(), name))
    found += [(m.start(), m.group(1).strip()) for m in _CAPS_H1.finditer(text, after)]
    seen, out = set(), []
    for pos, name in sorted(found):
        if name not in seen:
            seen.add(name)
            out.append((pos, name))
    return out


def script_stats(script: str) -> dict:
    """Stats on a MASKED script (placeholders still in place)."""
    kept = {int(n) for n in PLACEHOLDER_RE.findall(script)}
    text = PLACEHOLDER_RE.sub(" ", script)
    heads = list(_CHAPTER_HEADING.finditer(text))
    sections = trailing_sections(text, heads[-1].end() if heads else 0)
    end_of_chapters = sections[0][0] if sections else len(text)
    chapters = {}
    for i, h in enumerate(heads):
        stop = heads[i + 1].start() if i + 1 < len(heads) else end_of_chapters
        chapters[int(h.group(1))] = words(text[h.end():stop])
    spoken = text[:end_of_chapters]
    host_by_chapter = {}
    for i, h in enumerate(heads):
        stop = heads[i + 1].start() if i + 1 < len(heads) else end_of_chapters
        host_by_chapter[int(h.group(1))] = app_host_words(text[h.start():stop])
    return {
        "host_words": app_host_words(text),
        "host_words_by_chapter": host_by_chapter,
        "placeholders": kept,
        "chapter_nums": [int(h.group(1)) for h in heads],
        "heading_prefix": len(_HEADING_PREFIX.findall(text)),
        "heading_timestamps": sum(bool(_HEADING_TIMESTAMP.search(h.group(0))) for h in heads),
        "pre_chapter_words": words(text[:heads[0].start()]) if heads else 0,
        "chapter_words": chapters,
        "total_chapter_words": sum(chapters.values()),
        "dashes_arrows": sum(spoken.count(ch) for ch in ("—", "–", "→")),
        "contractions": len(_CONTRACTION.findall(spoken)),
        "odd_spaces": len(_ODD_SPACE.findall(text)),
        "agent_notes": len(_AGENT_NOTES.findall(text)),
        "sections": [name for _, name in sections],
    }


def fmt_chapters(nums: list[int]) -> str:
    if not nums:
        return "none"
    return f"{nums[0]}-{nums[-1]}" if nums == list(range(nums[0], nums[-1] + 1)) else ",".join(map(str, nums))
