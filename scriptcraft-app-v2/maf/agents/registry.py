"""Every code agent by its Foundry portal name -> a builder.

Used by the hosted entry point (maf/hosted/main.py) to serve one agent per
Foundry hosted agent, and by anything that needs the full list. Builders take
an optional credential and return a ready MAF Agent.
"""
from __future__ import annotations

from typing import Callable

from agent_framework import Agent

from agents import (
    broll, hook_summary, pipeline, polisher, pro_writer, quotes_stats, repeat_flow, shorten,
    youtube_details,
)

REGISTRY: dict[str, Callable[..., Agent]] = {
    "Script-bRoll-Agent": broll.build_code_agent,
    "Script-Hook-and-Summary-Agent": hook_summary.build_code_agent,
    "Script-Repeat-and-Flow-Agent": repeat_flow.build_code_agent,
    "Script-Shorten-Agent": shorten.build_code_agent,
    "Script-Youtube-Upload-Details-Agent": youtube_details.build_code_agent,
    "Script-Polisher-Agent": polisher.build_code_agent,
    "Statistics-and-Quotes-Finder-Agent": lambda credential=None: quotes_stats.build_code_agent(),
    # Not a portal agent: the app's single-pass Pro writer as an agent (2026-10-08).
    "Script-Writer-Pro-Agent": pro_writer.build_code_agent,
    **{name: (lambda credential=None, _n=name: pipeline.build_code_agent(_n, credential))
       for name in pipeline.SPECS},
}


def build_agent(portal_name: str, credential=None) -> Agent:
    try:
        return REGISTRY[portal_name](credential)
    except KeyError:
        raise SystemExit(f"Unknown agent {portal_name!r}; known: {', '.join(sorted(REGISTRY))}")
