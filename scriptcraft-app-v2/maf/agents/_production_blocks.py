"""[PRODUCTION BEGIN]…[PRODUCTION END] masking, ported from web_gui.py.

The app hides every production block (Grok prompts, Resolve cues, overlays)
behind an opaque ``[[PRODUCTION_BLOCK_N]]`` placeholder before a rewriting agent
(Repeat-and-Flow, Shorten) sees the script, then puts the blocks back. If the
agent drops ANY placeholder, the app keeps the pre-rewrite script, so the whole
rewrite is silently discarded. Keep these functions in sync with
web_gui.py: _mask_production_blocks / _restore_production_blocks / _restore_or_keep.
"""
from __future__ import annotations

import re

_PRODUCTION_BLOCK_PATTERN = r"\[PRODUCTION\s+BEGIN\].*?\[PRODUCTION\s+END\]"
_PRODUCTION_BLOCK_RE = re.compile(_PRODUCTION_BLOCK_PATTERN, re.IGNORECASE | re.DOTALL)
PLACEHOLDER_RE = re.compile(r"\[\[PRODUCTION_BLOCK_(\d+)\]\]")


def mask_production_blocks(script: str) -> tuple[str, list[str]]:
    """Replace each block with ``[[PRODUCTION_BLOCK_N]]``; return (masked, blocks)."""
    blocks: list[str] = []

    def _repl(m):
        blocks.append(m.group(0))
        return f"[[PRODUCTION_BLOCK_{len(blocks) - 1}]]"

    return _PRODUCTION_BLOCK_RE.sub(_repl, script), blocks


def restore_production_blocks(text: str, blocks: list[str]) -> tuple[str, list[int]]:
    """Put blocks back; return (restored, indices of placeholders the agent dropped)."""
    missing: list[int] = []
    for idx, block in enumerate(blocks):
        token = f"[[PRODUCTION_BLOCK_{idx}]]"
        if token in text:
            text = text.replace(token, block)
        else:
            missing.append(idx)
    return text, missing


def restore_or_keep(rewritten: str, blocks: list[str], original: str) -> tuple[str, bool]:
    """The app's rule. Returns (script, rewrite_applied).
    Any dropped placeholder means the original is kept and the rewrite is lost."""
    if not blocks:
        return rewritten, True
    restored, missing = restore_production_blocks(rewritten, blocks)
    if missing:
        return original, False
    return restored, True
