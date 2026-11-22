"""Explainer video: Claude Opus 5.5 (effort high) turns a narrated script and
its ElevenLabs narration into a synced, headless explainer video that blends
presentation slides with illustrated vector scenes.

Pipeline (one project folder per video, under <run dir>/explainer/<id>/):
1. Prepare: normalize the narration to -14 LUFS (two-pass loudnorm), time every
   spoken word (ElevenLabs forced alignment), and process the logo files
   (crop, recolor dark marks for the dark background).
2. Plan: Claude reads the script with its production notes and the timed
   transcript and plans every slide. The plan names what the user must supply:
   logos, figures to confirm ([VERIFY BEFORE RENDER]) and [insert] values.
3. Build: Claude writes the slides as HTML and inline SVG in the composition
   format (SYSTEM_PROMPT), in parallel batches. Each cue is a spoken phrase;
   the compiler turns phrases into times and strips anything unsafe or
   off-style (scripts, external URLs, gradients, shadows, CSS animation).
4. Preview and revise: the dialog plays the slides live against the audio.
   Notes go back to Claude for the slides the user picks, as a new version.
5. Render: headless Chrome draws each frame (the page is a pure function of
   time) and ffmpeg encodes chunks in parallel worker processes: a sample
   clip or 1080p review cut, then after approval the 4K final (3840x2160,
   30 fps, H.264 + AAC at -14 LUFS, faststart), a 720p phone copy and a 4K
   PNG of the copyable asset slide.

A project can start as a test clip (a stretch of the narration, e.g. the first
two minutes) that the user refines; "extend" then plans and writes the rest,
following the test slides and the user's notes.

Presenter video: HeyGen clips made from the same ElevenLabs audio (or one
long video, or upscaled copies of either) are matched to the narration by
their audio. Slides with data-host show the presenter full frame, in a side
panel or in a corner window: the page leaves that area transparent and the
renderer puts the footage under it with ffmpeg. About half of the corner
windows (the default) sit inside a drawn device frame — a monitor, a laptop,
a phone or a TV, in turn — and the rest stay a plain corner. A small guide
character can hold a short line taken from that slide's narration, lower
left, only where it stays clear of the presenter. Both are drawn locally,
and both can be turned off.

YouTube clips: a public video URL is saved with yt-dlp as an mp4 (1080p max;
ffmpeg merges the tracks) under the project's working/media folder. The user
marks one or more ranges and ffmpeg re-encodes each cut. A clip can be
assigned to a slide. The narration keeps the clock: a shorter clip holds its
last frame until the slide ends (it does not loop), and a longer clip stops
when the slide ends, so later slides stay on the spoken words. Per clip, the
audio is muted under the narration (the default), replaces the narration, or
is sidechain-ducked under it.

Pictures: the particle waves stay on every style (denser and a little faster
than the original field). Text slides are otherwise unchanged. visual_style
classic draws scene objects as the old flat shapes. cinematic draws the same
objects with volume, materials and motion (wheels, window glow, smoke,
parallax), stronger on the hook. A saved "rich" means cinematic.
See explainer_scenes.py.

The module has no Flask dependency; web_gui.py wires the routes and passes in
the Anthropic client, the ElevenLabs key and its pause detector.
"""

from __future__ import annotations

import argparse
import array
import asyncio
import base64
import bisect
import difflib
import glob
import html as _html
import io
import json
import math
import operator
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional

MODEL = "claude-opus-5-5"
EFFORT = "high"
MODEL_LABEL = "Claude Opus 5.5 (high effort)"
# Server-side refusal fallback: a declined request is re-run on a fallback
# model inside the same call. Dropped automatically if the account rejects it.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# $ per million tokens (Opus 5.5): input, output, 5-minute cache write, cache read.
PRICES = {"input": 4.0, "output": 20.0, "cache_write": 5.0, "cache_read": 0.20}

FPS = 30
STAGE_W, STAGE_H = 1920, 1080
LEAD = 0.35            # a slide starts this long before its first word
MIN_SLIDE = 0.8        # shortest slide the compiler allows
TAIL = 1.5             # the picture holds this long after the last word
LONG_SLIDE = 25.0      # slides longer than this are flagged for a split
CUE_FLOOR = 0.6        # a cue is searched from this long before its slide starts
PLAN_MAX_TOKENS = 64000
BUILD_MAX_TOKENS = 64000
BATCH_WEIGHT = 9.0     # slides per build call, weighting scenes heavier
BUILD_WORKERS = 6
CLAUDE_RETRY_WAITS = (20, 60, 150)   # seconds before retrying a rate-limited or dropped call
RENDER_WORKERS = max(1, min(6, (os.cpu_count() or 4) // 4))
ELEVEN_ALIGN_URL = "https://api.elevenlabs.io/v1/forced-alignment"
LOGO_EXTS = {".png", ".svg", ".webp", ".jpg", ".jpeg"}
OFF_WHITE = (236, 239, 244)

# Presenter video: where it shows, in 1920x1080 stage units (the renderer
# scales these for 4K). Side panels crop the 16:9 footage around `focus`.
HOST_LAYOUTS = {
    "full": {"x": 0, "y": 0, "w": 1920, "h": 1080, "r": 0},
    "left": {"x": 0, "y": 0, "w": 800, "h": 1080, "r": 0},
    "right": {"x": 1120, "y": 0, "w": 800, "h": 1080, "r": 0},
    "pip": {"x": 1296, "y": 694, "w": 544, "h": 306, "r": 18},
}
# % of runtime (screen time, not slide count) the plan aims to show the presenter.
# "brief" is the default when the project has no saved share. The other keys
# keep their percentages, so a share the user already saved still wins.
HOST_SHARES = {"mine": 0, "brief": 10, "little": 15, "some": 30, "lots": 50}
HOST_DEFAULT_SHARE = "brief"
HOST_SECTION_FADE = 0.3          # a placed presenter section fades in and out over this long
HOST_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv"}
HOST_MIN_BYTES = 20 * 1048576    # smaller files are not presenter footage
HOST_SEARCH = 3.0                # seconds either side of where a clip should start
HOST_MIN_SCORE = 0.6             # audio match below this: made from a different voiceover
HOST_FOCUS = 0.45                # where the presenter sits across the frame (0 left, 1 right)
# Corner-window dressing. "mix" frames about half of the corner windows
# (the 1st, 3rd, 5th…), cycling a monitor, a laptop, a phone and a TV, and
# leaves the rest as the plain corner. A device name frames every corner
# window that way. "off" is always the plain corner. An explicit choice
# wins, then a value already saved, then this default.
PIP_FRAME_MODES = ("off", "mix", "monitor", "laptop", "phone", "tv")
PIP_FRAME_DEFAULT = "mix"
PIP_DEVICES = ("monitor", "laptop", "phone", "tv")
# The device occupies the reserved corner (the plain pip box). The screen is
# the see-through opening the presenter is scaled into. Every number is even
# so a 4K scale stays on whole pixels.
_PIP_BOX = (1296, 694, 544, 306)
PIP_FRAME_GEOM = {
    "monitor": {"outer": _PIP_BOX, "screen": (1352, 710, 432, 244), "radius": 8},
    "laptop": {"outer": _PIP_BOX, "screen": (1368, 710, 400, 224), "radius": 6},
    "phone": {"outer": _PIP_BOX, "screen": (1344, 720, 448, 252), "radius": 22},
    "tv": {"outer": _PIP_BOX, "screen": (1328, 706, 480, 270), "radius": 4},
}
# Light comes from the upper left, the same way a card's shadow falls (down
# and to the right). A screen panel is only a few pixels thick. A laptop's
# thickness is the base; a monitor's and a TV's is the stand.
PANEL_EDGE = 3
LAPTOP_BASE = 16
# Guide character. "some" shows one on about a third of the slides that have
# room (including the first). "often" shows one on every such slide. "off"
# shows none. The graphic sits lower left, clear of the corner window.
BUBBLE_MODES = ("off", "some", "often")
BUBBLE_DEFAULT = "some"
ASIDE_AT = (48, 848)
ASIDE_SIZE = (440, 176)
BUBBLE_MAX = 46                  # characters in the bubble, so it stays two short lines

HERE = Path(__file__).resolve().parent
ASSET_DIR = HERE / "static" / "explainer"
PROJECT_ID_RE = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{4}$")

# Picture treatment. Re-exported so the dialog can persist it the same way as
# the corner frame and the guide character. classic is the particle field.
# The app directory is on the path even when this file is loaded by path
# (the look tests do that, from the repo root).
import sys as _imagery_sys
_APP_DIR = str(HERE)
if _APP_DIR not in _imagery_sys.path:
    _imagery_sys.path.insert(0, _APP_DIR)
from explainer_imagery import (  # noqa: E402
    VISUAL_STYLE_DEFAULT,
    VISUAL_STYLES,
    page_visual,
    visual_style_key,
)
from explainer_scenes import sprite as scene_sprite  # noqa: E402


class Cancelled(Exception):
    """The user stopped the job."""


# ---------------------------------------------------------------------------
# Claude's instructions. Stable text only, so every call shares the cache.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """ROLE
You are a video production agent for a YouTube channel about AI and markets. You turn a narrated script, the user's logo files and the recorded narration into a finished explainer video. The style blends clean presentation slides with animated, symbolic vector illustrations, all synced word by word to the narration. The video is headless unless the context lists PRESENTER VIDEO: the user's own lip-synced presenter reading this narration, which the app shows on the slides you mark.

HOW THIS APP WORKS
The app has already normalized the narration and timed every spoken word. You plan the video and write every slide as HTML and inline SVG in the COMPOSITION FORMAT below. The app turns each cue phrase you copy from the timed transcript into a time, plays the slides against the audio in a live preview, and renders a 1080p review and, after the user approves, the 4K final (3840x2160, 30 fps). You never write JavaScript: scripts, event handlers and external URLs are removed.

INPUTS
1. The script as written. Spoken lines follow "Host:". Everything between [PRODUCTION BEGIN] and [PRODUCTION END] is not spoken. Inside those blocks:
   - [GROK IMAGINE / RESOLVE]: a description of a symbolic scene. Treat it as a creative brief for an illustrated vector scene, not a literal requirement.
   - [VERIFY BEFORE RENDER]: figures that the user must confirm.
   - [ON SCREEN / RESOLVE]: overlay cards to show without narration.
   - Other RESOLVE notes (for example COLD OPEN): timing and camera directions.
2. The timed transcript: what the narration actually says, with start times in seconds. Build visuals from what is actually spoken.
3. The logo files the user has, by key.

HARD RULES
- Never draw, trace or recreate brand logos. Use only the user's files, through data-logo keys. For a brand with no file, still write data-logo with a short key; the app shows a styled text badge and asks the user for the file.
- Never include a photo or likeness of a real person. Use the name in type plus the person's company logos. If a photo would help, leave a framed photo spot (class photo-spot) the user can fill in their editor. (The user's presenter footage, placed by the app through data-host, is the one exception.)
- Never create mock social posts, receipts, statements or records that could pass as real. Use skeleton UI: gray bars and icons, no names or quote text.
- Show figures exactly as the script states them. Wrap every on-screen figure that a [VERIFY BEFORE RENDER] note covers in a data-ph span keyed to the plan's figures, and every [insert] value in a data-ph span keyed to the plan's inserts. Never invent a number for an [insert].
- No smooth gradients, glows, shadows or blur anywhere: dark gradients band badly after YouTube re-encodes. Flat colors, crisp shapes, clean strokes and small discrete particles only.
- Keep every slide as neutral and factual as the script.

DESIGN SYSTEM
- Layout in 1920x1080 units; the app renders at 2x for 4K, so everything is vectors and live text.
- Colors (CSS variables): --bg #090c12 (background), --panel #121824, --panel-2 #1a2232, --line #2a3446, --text #f2f4f8 (off-white), --muted #8a94a6, --gold #f5b83d (emphasis and "own"), --red #f05252 (losses and "rent"), --green #3cc878 (gains), --blue #4c8dff, --amber #f59e0b, --navy #0c1526 and --navy-2 #13213a (scene skies and ground), --sky-3 #1b2c4a. Use these, plus brand colors where a brand is shown.
- Type: Inter (Inter Display at large sizes, automatic). Classes: kicker (gold caps label), h1 (104px), h2 (72px), h3 (48px), lead (40px, muted), body (34px), small (26px), huge (220px numbers), num (tabular figures); color classes gold, red, green, blue, amber, muted, white.
- The app draws the particle background (rows of small particles riding a slow wave at the bottom, fading out by mid-screen), the HUD (section label top left, chapter tracker top right, thin progress bar at the bottom) and the slide transitions (a 0.4 s push up). Keep content inside x 120-1800 and y 110-990 so it clears the HUD; full-bleed scenes may fill the frame. The app may briefly show a small guide character with a short line from this slide's narration in the lower left (about x 40-520, y 820-1030). Keep essential type, logos and figures out of that pocket.
- The blend: presentation slides for stats, lists, definitions, timelines, comparisons and quotes; illustrated vector scenes for about a third of the runtime, for metaphor and story passages, drawn from the GROK IMAGINE briefs (not every brief needs a scene); a cold-open panorama with camera pans if the script describes one; a chapter card per section; the copyable asset (checklist or cheat sheet) as its own slide of kind asset.
- Any slide where text alone would sit for more than about 8 seconds gets a supporting icon or small illustration (inline SVG).
- Motion: headlines rise word by word, cards slide in, numbers count up, key figures pop or stamp (a ring burst on the biggest), charts draw or wipe on, bars grow from the bottom. Every element appears on the spoken words it illustrates and stays until the slide changes unless it is being swapped.
- Illustrated scenes: flat navy sky (the scene class), a few faint stars (small circles with data-loop="twinkle"), and the ground as one rect. Do not draw a house, building, car, tree, factory, data center, server, phone, chart monitor or power line out of boxes. Place the app's object instead, inside the scene svg:
  <svg class="sc" data-sc="house" data-depth="1" x="200" y="640" width="220" height="170" viewBox="0 0 220 170"><use href="#sc-house"/></svg>
  data-sc is one of: house, building, datacenter, car, tree, factory, server, phone, chart, powerline. Set that symbol's viewBox (house 220x170, building 190x240, datacenter 340x180, car 400x130, tree 140x170, factory 220x170, server 80x160, phone 82x168, chart 200x130, powerline 220x110) and size width/height to match. data-depth is 0.4 for something far, 1 for the middle, 1.6 or more for something close. The hook (before the first chapter card) should put more objects close to the camera. The app draws the flat or the detailed version. Logos inside scenes use <image data-logo>. A few short labels only.
- Topic pictures, not a generic street: if the script is about agents, bots, apps or AI tools, build the scene from bot characters instead of houses and cars. A bot is <svg class="sc sc-bot" data-sc="bot" data-shape="circle|squircle|blob|drop" width="140" height="140" viewBox="0 0 160 160" style="color:#a78bfa"><use href="#sc-bot-circle"/></svg> (the href matches the shape; color is one pastel: #a78bfa purple, #4c8dff blue, #5dbea3 teal, #6bcb77 green, #a07858 brown). Under it, a <div class="sc-pill">Label from the narration</div>. For a grid ("lots of bots"), several of these with data-anim="pop" and data-t="+0.3", "+0.5", "+0.7"... For a hub ("one rule for every bot"), a <div class="sc-message">the rule</div>, one bot, a <div class="sc-hub">Agent Tracker</div>, dotted <line stroke-dasharray="1 10" data-anim="draw"> connectors, and <svg ... data-anim="pop"><use href="#sc-check"/></svg> badges. Labels are the script's own names, not invented ones. Other topics can use the same idea for a product: a phone or chart object plus a sc-pill with the product name.
- Demo video: when the narration says it will show something ("let me show you", "here's how", a walkthrough), put data-demo="what the recording should show" on that section. Do not draw a fake screen recording. The app shows a placeholder the user can fill with their own video. Keep the slide's own text in a left column about 620px wide so the placeholder, which sits on the right, does not cover it.
- Brands, for any script: when the narration names a company or product (Nvidia, Tesla, ChatGPT, Claude, YouTube, and the rest), give that slide a brand picture instead of a generic street. One brand: a large hero, <svg class="sc sc-brand" data-sc="brand" width="520" height="520" viewBox="0 0 520 520"><image data-logo="nvidia" x="150" y="136" width="220" height="220"/></svg> with a <div class="sc-pill">Nvidia</div>, data-anim="pop". Two brands: the same pair, left and right, with a sc-hub that says vs. Several brands: each in a <div class="sc-orb"> around one sc-hub. data-logo is the brand key (nvidia, chatgpt, claude, gemini, tesla, youtube, grok, heygen). The app supplies the logo file, or a monogram if it has none. You still never draw the logo yourself. A bot can wear the brand color (style="color:#76b900") with the brand name in its sc-pill.

COMPOSITION FORMAT
Write each slide as one <section>, in time order, with nothing between sections:

<section id="s07" data-at="your index fund probably paid" data-kind="slide" data-section="c1">
  ... HTML and inline SVG ...
</section>

Section attributes
- id: s01, s02 ... in time order; keep the plan's ids. A split slide adds a letter (s07b).
- data-at: the slide starts on these spoken words, copied exactly from the timed transcript (3 to 8 consecutive words: the first words this slide illustrates). The first slide uses the first words of the narration.
- data-kind: slide | scene | chapter | asset.
- data-section: the section key from the plan (sets the HUD label).
- Optional: data-hud="off" (hide the HUD; chapter cards hide it automatically), data-tracker="text" (replaces the top-right tracker on this slide, e.g. "Own 2 / Rent 3"), data-transition="push|fade|cut", data-host (below).

Presenter (only when the context lists PRESENTER VIDEO)
- data-host="full|left|right|pip" on a section shows the presenter, synced to the narration, in a fixed area; the app draws the footage under your content and that area must stay see-through:
  full: the whole frame. Add at most a kicker, a lower-third or one small card in the empty part of the frame (see the presenter still); never over the face or body.
  left / right: an 800x1080 panel at that side (x 0-800, or 1120-1920). Put all content on the other side (x 880-1800, or 120-1040): one stat, a short list, a logo row or a headline.
  pip: a 544x306 corner window at x 1296-1840, y 694-1000 over a regular slide. Keep that corner clear. The app may draw that window inside a monitor, laptop, phone or TV frame; the corner stays the same either way.
- A presenter slide never has a scene, full-bleed background, panel or camera over the presenter area.

Layout
- A section is a 1920x1080 box. Use the layout classes (fill, pad, center, row, col, gap-s, gap-m, gap-l, grid-2, grid-3, grid-4, wrap, grow) or absolute positioning in px with inline styles (style="position:absolute; left:160px; top:240px; width:720px").
- Components: card (flat panel; add gold-edge, red-edge, green-edge or blue-edge for a colored border), chip (pill label), badge (ticker badge), stat (big number over a label), steps (an <ol> of numbered steps), checklist (a <ul> of checked items), quote, lower-third (caption band near the bottom), overlay-card (ON SCREEN cards), photo-spot, skeleton with sk-bar, sk-line and sk-avatar (placeholder UI), logo-row, bar (a bar for simple bar charts; set its height inline), divider.
- Per-slide CSS: a <style> block inside the section; every selector is scoped to that slide automatically. Allowed: flat colors, borders, border-radius, sizes, positions, transforms, clip-path. Removed: gradients, shadows, filters, blur, CSS animations and transitions, @-rules and external url().
- Inline SVG: for a full-bleed scene use <svg class="fill" viewBox="0 0 1920 1080"> inside a <div class="scene">. Use stroke-linecap="round" and flat fills.

Logos
- In HTML: <img class="logo" data-logo="nvidia" alt="Nvidia" style="height:110px">. In SVG: <image data-logo="nvidia" x="..." y="..." width="..." height="..."/>. Wordmarks (wide logos) replace the company name; icon logos sit beside the name. Never write src or href yourself.

Placeholders
- Verified figure: <span data-ph="nasdaq100_drop">6.36%</span> (the key from the plan's figures; the text is exactly the script's figure). The app swaps in the value the user confirms.
- Insert value: <span data-ph="jobs_report">[insert]</span>; put data-needs="jobs_report" on the card that holds it so the app can drop the card if the user leaves it out.
- data-ph also works on a count-up number (with data-anim="count"; data-to is set from the confirmed value).

Animation (all timing comes from these attributes; the app animates them)
- data-anim on any element: rise | words (word-by-word rise, for headlines) | left | right | up | down (slide in from that side) | pop (scale with overshoot) | stamp (thuds down from 1.7x) | fade | zoom (slow push-in over the slide) | wipe (reveal left to right) | wipe-up (reveal from the bottom; bars) | draw (SVG strokes draw on; on a path, line, polyline, polygon, rect, circle or a <g> of them) | count (counts up to data-to, with optional data-from, data-decimals, data-prefix, data-suffix, data-comma="1"). Add ring to fire a gold ring burst: data-anim="pop ring".
- data-at on an element: the exact spoken words that trigger it, copied from this slide's own transcript; or "+1.5" for seconds after the slide starts. Without data-at it appears with the slide.
- data-delay="0.2" adds seconds after the cue; data-dur="0.8" sets the animation length.
- data-stagger="0.12" on a container animates its direct children one after another, using the container's data-anim.
- data-out-at="spoken words or +seconds" with data-out="fade|down|shrink" removes an element mid-slide (to swap content in place).
- data-loop on any element: float | spin | pulse | blink | drift | twinkle (gentle and continuous); data-speed="2" doubles it.
- Camera (scenes): wrap a large drawing in <div class="camera" data-cam="start: 1920 540 1; on the left: 700 560 1.4; ..."> (e.g. an <svg width="3840" height="1080" viewBox="0 0 3840 1080"> panorama). Each keyframe is "spoken words: x y zoom": the view centers on point (x, y) of the wrapped drawing at that zoom, easing over 1.6 s. "start" is the slide's start.

Timing
- One slide per beat, 4 to 25 seconds each; split anything longer.
- Cue phrases come from the slide's own transcript window, in order. Prefer distinctive words (names, numbers as spoken).
- Cue each element on the first words that name it. Give text time to be read.

EXAMPLE
<section id="s05" data-at="AI stocks lost about two point three trillion" data-kind="slide" data-section="c1">
  <div class="pad col gap-m">
    <div class="kicker" data-anim="fade">Thursday, November 5</div>
    <h1 class="h1" data-anim="words">One day. <span class="red">Trillions</span> erased.</h1>
    <div class="row gap-l" style="margin-top:40px">
      <div class="card red-edge stat" data-anim="pop ring" data-at="two point three trillion dollars">
        <div class="huge red"><span data-ph="lost_value">$2.3T</span></div>
        <div class="lead">wiped off AI stocks</div>
      </div>
      <div class="card" data-anim="left" data-at="your index fund probably paid">
        <div class="h3">Your index fund</div>
        <div class="body muted">probably paid too</div>
      </div>
    </div>
  </div>
</section>
"""

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "sections", "slides", "logos", "figures", "inserts", "questions", "dropped"],
    "properties": {
        "summary": {"type": "string"},
        "sections": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["key", "label"],
            "properties": {"key": {"type": "string"}, "label": {"type": "string"}}}},
        "slides": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "section", "kind", "at", "idea", "logos", "host"],
            "properties": {
                "id": {"type": "string"}, "section": {"type": "string"},
                "kind": {"type": "string", "enum": ["chapter", "slide", "scene", "asset"]},
                "at": {"type": "string"}, "idea": {"type": "string"},
                "logos": {"type": "array", "items": {"type": "string"}},
                "host": {"type": "string", "enum": ["none", "full", "left", "right", "pip"]}}}},
        "logos": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["key", "name"],
            "properties": {"key": {"type": "string"}, "name": {"type": "string"}}}},
        "figures": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["key", "label", "value", "note"],
            "properties": {"key": {"type": "string"}, "label": {"type": "string"},
                           "value": {"type": "string"}, "note": {"type": "string"}}}},
        "inserts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["key", "label", "note"],
            "properties": {"key": {"type": "string"}, "label": {"type": "string"}, "note": {"type": "string"}}}},
        "questions": {"type": "array", "items": {"type": "string"}},
        "dropped": {"type": "array", "items": {"type": "string"}},
    },
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def fmt_secs(s: float) -> str:
    s = max(0, int(round(s or 0)))
    return f"{s // 60}:{s % 60:02d}"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40]


def new_project_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]


def _run(cmd: list, timeout: float = 3600) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} failed: {(r.stderr or '').strip()[-500:]}")
    return r


def media_seconds(path: Path) -> float:
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=nw=1:nk=1", str(path)], timeout=60)
    return float(r.stdout.strip() or 0)


# ---------------------------------------------------------------------------
# YouTube clips. Downloads live in <project>/working/media. Assignments and
# the per-clip audio choice are stored on project.json under "youtube", the
# same save the presenter share, corner frame and guide bubble use. A project
# with no "youtube" key is unchanged.
# ---------------------------------------------------------------------------

# Prefer an mp4 at or under 1080p. ffmpeg merges video+audio when the best
# pair is split, and a non-mp4 result is re-encoded to mp4 afterwards.
YT_FORMAT = (
    "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
    "bv*[height<=1080][ext=mp4]+ba/"
    "bv*[height<=1080]+ba/"
    "b[height<=1080][ext=mp4]/"
    "b[height<=1080]/b"
)
YT_AUDIO_MODES = ("mute", "clip", "mix")
YT_AUDIO_DEFAULT = "mute"
UPLOAD_EXTS = {".mp4", ".mov", ".webm", ".m4v"}
_DEMO_HINT = re.compile(
    r"\b(?:let me show you|here'?s how|i(?:'|’)ll show you|watch this|"
    r"walk you through|step by step|on the screen)\b",
    re.I,
)
# The narration keeps the clock. Documented here and in the clips tab.
CLIP_TIMING_NOTE = (
    "The narration keeps the timing. A clip shorter than its slide plays once and "
    "holds the last frame (it does not loop). A longer clip stops when the slide "
    "ends, so later slides stay on the spoken words."
)
_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}
_YT_ID_RE = re.compile(r"^[\w-]{6,}$")
_YT_CANCELS: dict = {}
_YT_CANCEL_LOCK = threading.Lock()


class YoutubeError(Exception):
    """A download, cut or clip edit the user can act on. `kind` is a short tag."""

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind


class _YtCancel:
    def __init__(self):
        self.event = threading.Event()
        self.proc = None


def parse_timecode(text) -> float:
    """Seconds from '90', '90.5', '1:30', '1:05.25' or '1:02:03.5'."""
    raw = ("" if text is None else str(text)).strip()
    if not raw:
        raise YoutubeError("Enter a time: seconds, m:ss, or h:mm:ss.")
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return round(float(raw), 3)
    m = re.fullmatch(r"(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)", raw)
    if not m:
        raise YoutubeError(f"Can't read “{raw}”. Use seconds (90), m:ss (1:30), or h:mm:ss (1:02:03).")
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2))
    seconds = float(m.group(3))
    if seconds >= 60:
        raise YoutubeError(f"Seconds in “{raw}” must be under 60.")
    if m.group(1) is not None and minutes >= 60:
        raise YoutubeError(f"Minutes in “{raw}” must be under 60.")
    return round(hours * 3600 + minutes * 60 + seconds, 3)


def validate_clip_range(start: float, end: float, duration: float) -> "tuple[float, float]":
    """end must be after start, and both must sit inside the download."""
    start, end = round(float(start), 3), round(float(end), 3)
    if start < 0:
        raise YoutubeError("The start time can't be negative.")
    if end <= start:
        raise YoutubeError("The end time has to be after the start.")
    if end - start < 0.2:
        raise YoutubeError("A clip has to be at least 0.2 seconds.")
    if duration and end > float(duration) + 0.05:
        raise YoutubeError(f"That range goes past the video ({fmt_secs(duration)}).")
    if duration:
        end = min(end, round(float(duration), 3))
    return start, end


def youtube_url_problem(url: str) -> Optional[str]:
    """A reason to refuse `url` before calling yt-dlp, or None when it is a video link."""
    raw = (url or "").strip()
    if not raw:
        return "Paste a YouTube URL."
    try:
        parts = urllib.parse.urlparse(raw)
    except Exception:
        return "That doesn't look like a YouTube link. Paste a youtube.com or youtu.be URL."
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or host not in _YT_HOSTS:
        return "That doesn't look like a YouTube link. Paste a youtube.com or youtu.be URL."
    if host.endswith("youtu.be"):
        vid = parts.path.strip("/").split("/")[0]
    else:
        path = parts.path or ""
        if "/shorts/" in path:
            vid = path.split("/shorts/", 1)[1].split("/")[0]
        elif "/embed/" in path:
            vid = path.split("/embed/", 1)[1].split("/")[0]
        elif "/live/" in path:
            vid = path.split("/live/", 1)[1].split("/")[0]
        else:
            vid = (urllib.parse.parse_qs(parts.query).get("v") or [""])[0]
    if not _YT_ID_RE.match(vid or ""):
        return "That YouTube link is missing the video id."
    return None


def classify_ytdlp_error(text: str) -> str:
    """A short message for a yt-dlp failure (bad URL, private, age-restricted, no ffmpeg)."""
    raw = (text or "").strip()
    t = raw.lower()
    if "no module named" in t and "yt_dlp" in t:
        return "yt-dlp is not installed. From the app folder run: pip install -r requirements.txt"
    if "ffmpeg" in t and any(s in t for s in ("not found", "not installed", "merging")):
        return ("ffmpeg is not installed, so the download can't be merged into an mp4. "
                "Install ffmpeg and try again.")
    if "not a bot" in t or ("sign in to confirm" in t and "bot" in t):
        return ("YouTube blocked the download and asked to confirm this is not a bot. "
                "Public videos usually work from a home network; this one was refused.")
    if "age" in t and any(s in t for s in ("restrict", "confirm your age", "sign in to confirm")):
        return "That video is age-restricted. YouTube won't hand it over without a signed-in account."
    if "private video" in t or "video is private" in t:
        return "That video is private, so it can't be downloaded."
    if "sign in" in t and any(s in t for s in ("private", "bot", "confirm", "age")):
        return "YouTube asked for a sign-in (private or age-restricted). This download only works for public videos."
    if any(s in t for s in ("unsupported url", "incomplete youtube id", "is not a valid url")):
        return "That doesn't look like a YouTube link. Paste a youtube.com or youtu.be URL."
    if any(s in t for s in ("video unavailable", "has been removed", "account associated with this video")):
        return "YouTube says that video is unavailable."
    last = raw.splitlines()[-1] if raw else ""
    return "The download failed. " + last[:300]


def require_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise YoutubeError(
            "ffmpeg is not installed, so the download can't be merged into an mp4 and clips can't be cut. "
            "Install ffmpeg and try again.", "ffmpeg")
    return found


def ytdlp_base_cmd(*, require: bool = True) -> list:
    """How to launch yt-dlp. `require=False` still returns the module command so
    tests can inspect it without the package installed."""
    import importlib.util
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    found = shutil.which("yt-dlp")
    if found:
        return [found]
    if not require:
        return [sys.executable, "-m", "yt_dlp"]
    raise YoutubeError(
        "yt-dlp is not installed. From the app folder run: pip install -r requirements.txt", "ytdlp")


def ytdlp_dump_cmd(url: str) -> list:
    return [*ytdlp_base_cmd(require=False), "--no-playlist", "--no-warnings", "--dump-single-json",
            "--skip-download", url]


def ytdlp_get_cmd(url: str, dest: Path) -> list:
    tmpl = str(Path(dest).with_name(Path(dest).stem + ".download.%(ext)s"))
    return [*ytdlp_base_cmd(require=False), "--no-playlist", "--no-warnings", "--newline",
            "--merge-output-format", "mp4", "-f", YT_FORMAT, "-o", tmpl, url]


def _yt_progress_line(line: str, on_progress: Optional[Callable[[float, str], None]]) -> None:
    if not on_progress:
        return
    m = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line or "")
    if m:
        frac = float(m.group(1)) / 100.0
        on_progress(frac, f"Downloading… {float(m.group(1)):.0f}%")
        return
    low = (line or "").lower()
    if "merger" in low or "merging formats" in low:
        on_progress(0.99, "Merging video and audio into an mp4…")


def _reject_unavailable(info: dict) -> None:
    avail = str(info.get("availability") or "").lower()
    age = int(info.get("age_limit") or 0)
    if avail in ("private", "needs_auth", "premium_only", "subscriber_only"):
        if age >= 18 or "age" in avail:
            raise YoutubeError(
                "That video is age-restricted. YouTube won't hand it over without a signed-in account.", "age")
        if avail == "private":
            raise YoutubeError("That video is private, so it can't be downloaded.", "private")
        raise YoutubeError("That video needs a sign-in, so it can't be downloaded.", "private")
    live = str(info.get("live_status") or "").lower()
    if info.get("is_live") or live in ("is_live", "is_upcoming"):
        raise YoutubeError("Live streams can't be saved as clips. Use a finished video.")
    try:
        duration = float(info.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        raise YoutubeError("YouTube did not report a length for that video, so it can't be cut into clips.")


def _run_ytdlp(cmd: list, *, timeout: float, on_line: Optional[Callable[[str], None]] = None,
               runner=None, cancel: Optional[_YtCancel] = None) -> subprocess.CompletedProcess:
    if runner is not None:
        return runner(cmd, stream=bool(on_line))
    if on_line is None and cancel is None:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    if cancel is not None:
        cancel.proc = proc
    lines: list = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line)
            if on_line:
                on_line(line.rstrip("\n"))
            if cancel is not None and cancel.event.is_set():
                proc.kill()
                break
        try:
            rc = proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = proc.wait(timeout=10)
    finally:
        if cancel is not None:
            cancel.proc = None
    return subprocess.CompletedProcess(cmd, rc, "".join(lines), "")


def _take_download(dest: Path) -> None:
    """Move yt-dlp's file onto `dest` as mp4 (re-encode when the download is not already mp4)."""
    folder, stem = dest.parent, dest.stem
    found = [p for p in folder.glob(stem + ".download.*")
             if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"} and not p.name.endswith(".part")]
    if not found:
        raise YoutubeError("yt-dlp finished without a video file.")
    src = max(found, key=lambda p: p.stat().st_mtime)
    if src.suffix.lower() == ".mp4":
        if dest.exists():
            dest.unlink()
        src.replace(dest)
        return
    require_ffmpeg()
    tmp = dest.with_suffix(".transcode.mp4")
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(tmp)])
    tmp.replace(dest)
    src.unlink(missing_ok=True)


def yt_info_from_dump(info: dict) -> dict:
    _reject_unavailable(info)
    return {"title": str(info.get("title") or "YouTube video")[:180],
            "youtube_id": str(info.get("id") or "")[:32],
            "seconds": round(float(info.get("duration") or 0), 3),
            "width": int(info.get("width") or 0), "height": int(info.get("height") or 0)}


def yt_download(url: str, dest: Path, *, on_progress: Optional[Callable[[float, str], None]] = None,
                runner=None, video_id: str = "") -> dict:
    """Download one public YouTube video to `dest` (mp4, capped at 1080p).

    `runner(cmd, stream=False)` replaces the subprocess in tests. It must
    return a CompletedProcess; for the download command it also creates the
    `*.download.mp4` file yt-dlp would have written.
    """
    problem = youtube_url_problem(url)
    if problem:
        raise YoutubeError(problem, "bad_url")
    if runner is None:
        require_ffmpeg()
        ytdlp_base_cmd()
    cancel = None
    if video_id:
        cancel = _YtCancel()
        with _YT_CANCEL_LOCK:
            _YT_CANCELS[video_id] = cancel
    try:
        if cancel is not None and cancel.event.is_set():
            raise YoutubeError("Download cancelled.")
        dumped = _run_ytdlp(ytdlp_dump_cmd(url), timeout=180, runner=runner)
        if dumped.returncode != 0:
            raise YoutubeError(classify_ytdlp_error((dumped.stderr or "") + "\n" + (dumped.stdout or "")))
        try:
            info = json.loads(dumped.stdout or "{}")
        except json.JSONDecodeError as e:
            raise YoutubeError("yt-dlp did not return video details. " + classify_ytdlp_error(dumped.stdout or "")) from e
        meta = yt_info_from_dump(info)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if on_progress:
            on_progress(0.01, "Starting the download…")

        def line(text, _cb=on_progress):
            _yt_progress_line(text, _cb)

        got = _run_ytdlp(ytdlp_get_cmd(url, dest), timeout=3600, on_line=line, runner=runner, cancel=cancel)
        if cancel is not None and cancel.event.is_set():
            raise YoutubeError("Download cancelled.")
        if got.returncode != 0:
            raise YoutubeError(classify_ytdlp_error(got.stdout or got.stderr or ""))
        _take_download(dest)
        probed = probe_video(dest)
        if probed:
            meta["seconds"] = probed["seconds"]
            meta["width"] = probed["w"]
            meta["height"] = probed["h"]
            meta["has_audio"] = bool(probed["audio"])
        else:
            meta["has_audio"] = True
        if on_progress:
            on_progress(1.0, "Ready")
        return meta
    finally:
        if video_id:
            with _YT_CANCEL_LOCK:
                _YT_CANCELS.pop(video_id, None)


def yt_cancel(video_id: str) -> None:
    with _YT_CANCEL_LOCK:
        job = _YT_CANCELS.get(video_id)
    if not job:
        return
    job.event.set()
    proc = job.proc
    if proc is not None and proc.poll() is None:
        proc.kill()


def load_youtube(data: Optional[dict]) -> dict:
    """The saved videos and clips. Missing or odd data becomes an empty pair."""
    raw = (data or {}).get("youtube") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {"videos": [], "clips": []}
    videos = [dict(v) for v in raw.get("videos") or [] if isinstance(v, dict) and v.get("id")]
    clips = [dict(c) for c in raw.get("clips") or [] if isinstance(c, dict) and c.get("id")]
    return {"videos": videos, "clips": clips}


def _yt_mutate(project: "Project", fn: Callable):
    with project.lock:
        bundle = load_youtube(project.data)
        result = fn(bundle)
        project.data["youtube"] = {"videos": bundle["videos"], "clips": bundle["clips"]}
        project.save()
        return result


def yt_update_video(project: "Project", video_id: str, **fields) -> None:
    def edit(bundle):
        for v in bundle["videos"]:
            if v.get("id") == video_id:
                v.update(fields)
                return v
        return None
    _yt_mutate(project, edit)


def yt_begin_video(project: "Project", url: str) -> "tuple[dict, bool]":
    """A downloading record for `url`. The bool is False when one is already in progress or ready."""
    created = {"ok": False}

    def edit(bundle, _url=url.strip()):
        for v in bundle["videos"]:
            if v.get("url") != _url:
                continue
            if v.get("status") == "error":
                v.update(status="downloading", error="", progress=0, message="Starting the download…")
                created["ok"] = True
                return v
            return v
        vid = "yt_" + uuid.uuid4().hex[:8]
        (project.dir / "working" / "media").mkdir(parents=True, exist_ok=True)
        rec = {"id": vid, "url": _url, "title": "", "youtube_id": "", "file": f"working/media/{vid}.mp4",
               "seconds": 0, "width": 0, "height": 0, "has_audio": True, "status": "downloading",
               "error": "", "progress": 0, "message": "Starting the download…", "created": time.time()}
        bundle["videos"].append(rec)
        created["ok"] = True
        return rec
    rec = _yt_mutate(project, edit)
    return rec, bool(created["ok"])


def yt_finish_video(project: "Project", video_id: str, info: dict) -> None:
    yt_update_video(project, video_id, status="ready", error="", progress=1, message="Ready",
                    title=info.get("title") or "", youtube_id=info.get("youtube_id") or "",
                    seconds=info.get("seconds") or 0, width=info.get("width") or 0,
                    height=info.get("height") or 0, has_audio=bool(info.get("has_audio", True)))


def _clip_label(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:80]


def cut_clip_cmd(src: Path, dest: Path, start: float, end: float, *, audio: bool = True) -> list:
    """Accurate cut: decode from the start of the file, then re-encode the range."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
           "-ss", f"{float(start):.3f}", "-to", f"{float(end):.3f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-b:a", "160k"] if audio else ["-an"]
    cmd += ["-movflags", "+faststart", str(dest)]
    return cmd


def _cut_range(src: Path, dest: Path, start: float, end: float, *, run=None) -> bool:
    """Write the cut. Returns whether the cut has an audio track."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = cut_clip_cmd(src, dest, start, end, audio=True)
    if run is not None:
        got = run(cmd)
        if getattr(got, "returncode", 1) != 0:
            raise YoutubeError("Could not cut that clip. " + ((getattr(got, "stderr", "") or "")[-240:]))
        return True
    require_ffmpeg()
    try:
        _run(cmd)
        return True
    except RuntimeError as first:
        msg = str(first).lower()
        if "audio" not in msg and "matches no streams" not in msg and "stream specifier" not in msg:
            if "ffmpeg" in msg and "not found" in msg:
                raise YoutubeError(
                    "ffmpeg is not installed, so the clip can't be cut. Install ffmpeg and try again.", "ffmpeg") from first
            raise YoutubeError("Could not cut that clip. " + str(first)[-240:]) from first
        try:
            _run(cut_clip_cmd(src, dest, start, end, audio=False))
        except RuntimeError as second:
            raise YoutubeError("Could not cut that clip. " + str(second)[-240:]) from second
        return False


def _video_of(bundle: dict, video_id: str) -> dict:
    video = next((v for v in bundle["videos"] if v.get("id") == video_id), None)
    if video is None or video.get("status") != "ready":
        raise YoutubeError("Download a video before cutting clips from it.")
    return video


def yt_add_clip(project: "Project", video_id: str, start_text, end_text, label: str = "", *, run=None) -> dict:
    with project.lock:
        bundle = load_youtube(project.data)
        video = _video_of(bundle, video_id)
        start, end = validate_clip_range(parse_timecode(start_text), parse_timecode(end_text),
                                         float(video.get("seconds") or 0))
        src = project.dir / (video.get("file") or "")
        if not src.is_file():
            raise YoutubeError("The downloaded video file is missing. Download it again.")
        cid = "yc_" + uuid.uuid4().hex[:8]
        rel = f"working/media/{cid}.mp4"
        width, height = int(video.get("width") or 0), int(video.get("height") or 0)
        has_src_audio = bool(video.get("has_audio", True))
    dest = project.dir / rel
    has_audio = _cut_range(src, dest, start, end, run=run) and has_src_audio
    probed = probe_video(dest)
    if probed:
        width, height = probed["w"], probed["h"]
        has_audio = bool(probed["audio"])
    rec = {"id": cid, "video": video_id, "label": _clip_label(label), "start": start, "end": end,
           "file": rel, "seconds": round(end - start, 3), "width": width, "height": height,
           "has_audio": has_audio, "audio": YT_AUDIO_DEFAULT, "slide": "", "status": "ready",
           "error": "", "created": time.time()}

    def add(bundle, _rec=rec, _vid=video_id):
        if not any(v.get("id") == _vid for v in bundle["videos"]):
            dest.unlink(missing_ok=True)
            raise YoutubeError("That video was removed before the clip was saved.")
        bundle["clips"].append(_rec)
        return _rec
    return _yt_mutate(project, add)


def yt_update_clip(project: "Project", clip_id: str, *, start=None, end=None, label=None, run=None) -> dict:
    with project.lock:
        bundle = load_youtube(project.data)
        clip = next((c for c in bundle["clips"] if c.get("id") == clip_id), None)
        if clip is None:
            raise YoutubeError("That clip is no longer in the list.")
        video = _video_of(bundle, clip.get("video") or "")
        new_start = clip["start"] if start is None else parse_timecode(start)
        new_end = clip["end"] if end is None else parse_timecode(end)
        new_start, new_end = validate_clip_range(new_start, new_end, float(video.get("seconds") or 0))
        src = project.dir / (video.get("file") or "")
        rel = clip.get("file") or f"working/media/{clip_id}.mp4"
        recut = abs(new_start - float(clip["start"])) > 0.001 or abs(new_end - float(clip["end"])) > 0.001
        new_label = clip.get("label") if label is None else _clip_label(label)
        has_src_audio = bool(video.get("has_audio", True))
    has_audio = bool(clip.get("has_audio", True))
    if recut:
        if not src.is_file():
            raise YoutubeError("The downloaded video file is missing. Download it again.")
        has_audio = _cut_range(src, project.dir / rel, new_start, new_end, run=run) and has_src_audio
        probed = probe_video(project.dir / rel)
        if probed:
            has_audio = bool(probed["audio"])

    def edit(bundle, _id=clip_id):
        cur = next((c for c in bundle["clips"] if c.get("id") == _id), None)
        if cur is None:
            raise YoutubeError("That clip is no longer in the list.")
        cur["start"], cur["end"] = new_start, new_end
        cur["seconds"] = round(new_end - new_start, 3)
        cur["label"] = new_label
        cur["file"] = rel
        cur["has_audio"] = has_audio
        cur["status"] = "ready"
        cur["error"] = ""
        if not has_audio:
            cur["audio"] = "mute"
        return cur
    return _yt_mutate(project, edit)


def yt_set_audio(project: "Project", clip_id: str, mode: str) -> dict:
    if mode not in YT_AUDIO_MODES:
        raise YoutubeError("Audio must be mute (keep narration), clip audio only, or mix.")

    def edit(bundle, _id=clip_id, _mode=mode):
        cur = next((c for c in bundle["clips"] if c.get("id") == _id), None)
        if cur is None:
            raise YoutubeError("That clip is no longer in the list.")
        if _mode != "mute" and not cur.get("has_audio", True):
            raise YoutubeError("This clip has no audio track, so it stays muted under the narration.")
        cur["audio"] = _mode
        return cur
    return _yt_mutate(project, edit)


def yt_assign(project: "Project", clip_id: str, slide: str, *, known: Optional[set] = None) -> dict:
    """Put the clip on one slide. Another clip already on that slide is unassigned."""
    slide = (slide or "").strip()
    if slide and (known is None or slide not in known):
        raise YoutubeError("That slide is not in this version." if known else "Build the slides before assigning a clip.")

    def edit(bundle, _id=clip_id, _slide=slide):
        cur = next((c for c in bundle["clips"] if c.get("id") == _id), None)
        if cur is None:
            raise YoutubeError("That clip is no longer in the list.")
        if _slide:
            bundle["clips"] = [c for c in bundle["clips"]
                               if not (c.get("id") != _id and c.get("slide") == _slide and c.get("status") == "placeholder")]
            cur = next((c for c in bundle["clips"] if c.get("id") == _id), None)
            if cur is None:
                raise YoutubeError("That clip is no longer in the list.")
            for other in bundle["clips"]:
                if other.get("id") != _id and other.get("slide") == _slide:
                    other["slide"] = ""
        cur["slide"] = _slide
        return cur
    return _yt_mutate(project, edit)


def _unlink_rel(project: "Project", rel: str) -> None:
    if not rel or ".." in Path(rel).parts:
        return
    path = project.dir / rel
    try:
        if path.is_file() and (project.dir / "working").resolve() in path.resolve().parents:
            path.unlink()
    except OSError:
        pass


def yt_delete_clip(project: "Project", clip_id: str) -> None:
    removed = {}

    def edit(bundle, _id=clip_id):
        keep = []
        for c in bundle["clips"]:
            if c.get("id") == _id:
                removed["file"] = c.get("file") or ""
            else:
                keep.append(c)
        if "file" not in removed:
            raise YoutubeError("That clip is no longer in the list.")
        bundle["clips"] = keep
    _yt_mutate(project, edit)
    _unlink_rel(project, removed.get("file") or "")


def yt_delete_video(project: "Project", video_id: str) -> None:
    removed: list = []

    def edit(bundle, _id=video_id):
        video = next((v for v in bundle["videos"] if v.get("id") == _id), None)
        if video is None:
            raise YoutubeError("That video is no longer in the list.")
        removed.append(video.get("file") or "")
        bundle["videos"] = [v for v in bundle["videos"] if v.get("id") != _id]
        kept = []
        for c in bundle["clips"]:
            if c.get("video") == _id:
                removed.append(c.get("file") or "")
            else:
                kept.append(c)
        bundle["clips"] = kept
    _yt_mutate(project, edit)
    for rel in removed:
        _unlink_rel(project, rel)


def yt_public(project: "Project") -> dict:
    """What the dialog shows. Paths stay relative to the project folder."""
    bundle = load_youtube(project.data)
    videos, clips = [], []
    for v in bundle["videos"]:
        rel = v.get("file") or ""
        videos.append({"id": v.get("id"), "url": v.get("url") or "", "title": v.get("title") or "",
                       "youtube_id": v.get("youtube_id") or "", "seconds": v.get("seconds") or 0,
                       "width": v.get("width") or 0, "height": v.get("height") or 0,
                       "has_audio": bool(v.get("has_audio", True)), "status": v.get("status") or "",
                       "error": v.get("error") or "", "progress": v.get("progress") or 0,
                       "message": v.get("message") or "", "file": rel,
                       "ready": bool(rel) and (project.dir / rel).is_file() and v.get("status") == "ready"})
    for c in bundle["clips"]:
        rel = c.get("file") or ""
        clips.append({"id": c.get("id"), "video": c.get("video") or "", "label": c.get("label") or "",
                      "start": c.get("start") or 0, "end": c.get("end") or 0, "seconds": c.get("seconds") or 0,
                      "audio": c.get("audio") or YT_AUDIO_DEFAULT, "slide": c.get("slide") or "",
                      "has_audio": bool(c.get("has_audio", True)), "status": c.get("status") or "",
                      "error": c.get("error") or "", "file": rel, "note": c.get("note") or "",
                      "source": c.get("source") or "",
                      "ready": bool(rel) and (project.dir / rel).is_file() and c.get("status") == "ready"})
    return {"videos": videos, "clips": clips, "timing": CLIP_TIMING_NOTE}


def demo_note(spoken: str) -> str:
    """A short note when this narration is asking for a screen recording."""
    text = re.sub(r"\s+", " ", spoken or "").strip()
    if not text or not _DEMO_HINT.search(text):
        return ""
    return text[:180]


def demo_payloads(compiled: dict, clips: list, mode: str) -> list:
    """Placeholder frames for the preview. The final render gets none, so an
    empty slot falls back to the slide itself."""
    if mode != "preview":
        return []
    filled = {c.get("slide") for c in clips or [] if c.get("status") == "ready" and c.get("slide")}
    out = []
    for s in (compiled or {}).get("slides") or []:
        sid = s.get("id") or ""
        if not sid or sid in filled:
            continue
        ph = next((c for c in clips or [] if c.get("slide") == sid and c.get("status") == "placeholder"), None)
        note = ((ph or {}).get("note") or s.get("demo") or demo_note(s.get("spoken") or "")).strip()
        if not note and not ph:
            continue
        out.append({"slide": sid, "t0": float(s.get("t0") or 0), "t1": float(s.get("t1") or 0),
                    "label": "Demo video", "note": note[:180]})
    return out


def sync_demo_placeholders(project: "Project", slides: list) -> int:
    """One empty Demo video clip per slide that asks for a recording.

    A slide that already has any clip keeps it. Returns how many were added.
    """
    bundle = load_youtube(project.data)
    taken = {c.get("slide") for c in bundle["clips"] if c.get("slide")}
    new = []
    for s in slides or []:
        sid = s.get("id") or ""
        note = (s.get("demo") or "").strip() or demo_note(s.get("spoken") or "")
        if not sid or not note or sid in taken:
            continue
        new.append({"id": "yc_" + uuid.uuid4().hex[:8], "video": "", "label": "Demo video",
                    "note": note[:180], "start": 0, "end": 0, "file": "", "seconds": 0,
                    "width": 0, "height": 0, "has_audio": False, "audio": "mute",
                    "slide": sid, "status": "placeholder", "error": "", "source": "demo",
                    "created": time.time()})
        taken.add(sid)
    if not new:
        return 0

    def edit(bundle, _new=new):
        have = {c.get("slide") for c in bundle["clips"] if c.get("slide")}
        for rec in _new:
            if rec["slide"] not in have:
                bundle["clips"].append(rec)
                have.add(rec["slide"])
    _yt_mutate(project, edit)
    return len(new)


def yt_add_upload(project: "Project", src: Path, *, label: str = "", start: float = 0.0,
                  end: Optional[float] = None, probe=None, run=None) -> dict:
    """Save a local screen recording as a clip. `probe` and `run` stand in for
    ffprobe and ffmpeg in tests. Audio defaults to mute so narration continues."""
    src = Path(src)
    if src.suffix.lower() not in UPLOAD_EXTS:
        raise YoutubeError("Upload an mp4, mov, webm or m4v screen recording.")
    if not src.is_file():
        raise YoutubeError("That file is missing.")
    info = (probe or probe_video)(src) or {}
    dur = float(info.get("seconds") or 0)
    if dur <= 0:
        raise YoutubeError("Could not read that video.")
    start = max(0.0, float(start or 0))
    stop = dur if end is None else min(dur, float(end))
    if stop - start < 0.2:
        raise YoutubeError("The trim has to be at least 0.2 seconds and inside the video.")
    vid = "up_" + uuid.uuid4().hex[:8]
    vrel = f"working/media/{vid}{src.suffix.lower()}"
    full = project.dir / vrel
    full.parent.mkdir(parents=True, exist_ok=True)
    if full.resolve() != src.resolve():
        shutil.copyfile(src, full)
    cid = "yc_" + uuid.uuid4().hex[:8]
    crel = f"working/media/{cid}.mp4"
    dest = project.dir / crel
    cmd = cut_clip_cmd(full, dest, start, stop, audio=bool(info.get("audio", True)))
    if run is not None:
        run(cmd)
    else:
        _cut_range(full, dest, start, stop)
    width, height = int(info.get("w") or info.get("width") or 0), int(info.get("h") or info.get("height") or 0)
    has_audio = bool(info.get("audio", True))
    video = {"id": vid, "url": "", "title": _clip_label(label) or src.name, "youtube_id": "",
             "seconds": round(dur, 3), "width": width, "height": height, "has_audio": has_audio,
             "status": "ready", "error": "", "progress": 1, "message": "", "file": vrel,
             "source": "upload", "created": time.time()}
    clip = {"id": cid, "video": vid, "label": _clip_label(label) or src.stem[:40],
            "note": "", "start": round(start, 3), "end": round(stop, 3), "file": crel,
            "seconds": round(stop - start, 3), "width": width, "height": height,
            "has_audio": has_audio, "audio": "mute", "slide": "", "status": "ready",
            "error": "", "source": "upload", "created": time.time()}

    def add(bundle, _v=video, _c=clip):
        bundle["videos"].append(_v)
        bundle["clips"].append(_c)
        return _c
    return _yt_mutate(project, add)


def preview_clip_payloads(project: "Project", compiled: dict, url_of: Callable[[str], str]) -> list:
    """Assigned, ready clips with the slide window they play in."""
    slides = {m["id"]: m for m in (compiled or {}).get("slides") or []}
    out = []
    for c in load_youtube(project.data)["clips"]:
        sid = c.get("slide") or ""
        meta = slides.get(sid)
        rel = c.get("file") or ""
        if not meta or c.get("status") != "ready" or not rel or not (project.dir / rel).is_file():
            continue
        out.append({"id": c["id"], "slide": sid, "label": c.get("label") or "", "src": url_of(rel),
                    "audio": c.get("audio") if c.get("audio") in YT_AUDIO_MODES else YT_AUDIO_DEFAULT,
                    "seconds": float(c.get("seconds") or 0), "t0": meta["t0"], "t1": meta["t1"]})
    return out


def fit_contain(src_w: int, src_h: int, box_w: int, box_h: int) -> "tuple[int, int, int, int]":
    """Even width, height and origin that fit the source inside the box (letterboxed)."""
    src_w, src_h = max(1, int(src_w)), max(1, int(src_h))
    box_w, box_h = max(2, int(box_w) // 2 * 2), max(2, int(box_h) // 2 * 2)
    scale = min(box_w / src_w, box_h / src_h)
    sw = min(box_w, max(2, int(round(src_w * scale)) // 2 * 2))
    sh = min(box_h, max(2, int(round(src_h * scale)) // 2 * 2))
    x = (box_w - sw) // 2
    y = (box_h - sh) // 2
    return sw, sh, x - (x % 2), y - (y % 2)


def clip_render_plan(project: "Project", start: float, end: float) -> list:
    """Assigned clips that overlap [start, end), with times relative to the render."""
    try:
        compiled = project.compile()
    except Exception:
        return []
    slides = {m["id"]: m for m in (compiled.get("slides") or [])}
    out = []
    for c in load_youtube(project.data)["clips"]:
        if c.get("status") != "ready":
            continue
        meta = slides.get(c.get("slide") or "")
        rel = c.get("file") or ""
        path = project.dir / rel if rel else None
        if not meta or path is None or not path.is_file():
            continue
        t0, t1 = float(meta["t0"]), float(meta["t1"])
        a, b = max(t0, float(start)), min(t1, float(end))
        if b - a < 1.0 / FPS:
            continue
        src_skip = max(0.0, a - t0)
        full = float(c.get("seconds") or 0)
        remain = max(0.0, full - src_skip) if full else (b - a)
        if full and remain <= 0.05:
            src_skip = max(0.0, full - 0.08)
            remain = 0.08
        audio = c.get("audio") if c.get("audio") in YT_AUDIO_MODES else YT_AUDIO_DEFAULT
        if audio != "mute" and not c.get("has_audio", True):
            audio = "mute"
        out.append({"path": str(path), "audio": audio, "t0": t0, "t1": t1,
                    "offset": round(a - float(start), 3), "show": round(b - a, 3),
                    "src_skip": round(src_skip, 3), "seconds": round(remain, 3),
                    "w": int(c.get("width") or 1920) or 1920, "h": int(c.get("height") or 1080) or 1080})
    return out


def build_overlay_cmd(base: Path, out: Path, clips: list, width: int, height: int, crf: int = 18) -> list:
    """Lay each clip over the rendered frames, fitted inside the frame.

    A clip shorter than its on-screen window is padded by cloning the last
    frame (hold, not loop). A longer clip is trimmed to the window.
    """
    inputs: list = ["-i", str(base)]
    chains = ["[0:v]setpts=PTS-STARTPTS[vin]"]
    last = "vin"
    for i, c in enumerate(clips):
        skip = float(c.get("src_skip") or 0)
        if skip > 0.02:
            inputs += ["-ss", f"{skip:.3f}"]
        inputs += ["-i", str(c["path"])]
        sw, sh, x, y = fit_contain(int(c.get("w") or width), int(c.get("h") or height), width, height)
        show = max(1.0 / FPS, float(c["show"]))
        remain = max(0.0, float(c.get("seconds") or show))
        hold = max(0.0, show - remain)
        pad = f",tpad=stop_mode=clone:stop_duration={hold + 0.08:.3f}" if hold > 0.04 else ""
        lab, nxt = f"c{i}", f"v{i}"
        off = float(c["offset"])
        chains.append(
            f"[{i + 1}:v]setpts=PTS-STARTPTS,fps={FPS},scale={sw}:{sh}:flags=lanczos,setsar=1,"
            f"pad={width}:{height}:{x}:{y}:black,format=yuv420p{pad},"
            f"trim=duration={show:.3f},setpts=PTS-STARTPTS+{off:.3f}/TB[{lab}]")
        chains.append(
            f"[{last}][{lab}]overlay=0:0:eof_action=pass:enable='between(t,{off:.3f},{off + show:.3f})'[{nxt}]")
        last = nxt
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", ";".join(chains),
            "-map", f"[{last}]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(int(crf)),
            "-pix_fmt", "yuv420p", str(out)]


def build_mux_cmd(video: Path, narration: Path, out: Path, start: float, dur: float, clips: list) -> list:
    """Mux the narration. Mute clips leave it alone. 'clip' replaces it on that
    window. 'mix' sidechain-ducks the clip under the narration."""
    audible = [c for c in clips or [] if c.get("audio") in ("clip", "mix")]
    if not audible:
        return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
                "-ss", f"{float(start):.3f}", "-i", str(narration),
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", "apad",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-t", f"{float(dur):.3f}", "-movflags", "+faststart", str(out)]
    inputs = ["-i", str(video), "-ss", f"{float(start):.3f}", "-i", str(narration)]
    for c in audible:
        inputs += ["-i", str(c["path"])]
    enables = []
    for c in audible:
        if c.get("audio") != "clip":
            continue
        a, b = float(c["offset"]), float(c["offset"]) + float(c["show"])
        if b - a > 0.02:
            enables.append(f"between(t,{a:.3f},{b:.3f})")
    if enables:
        narr = (f"[1:a]volume=0:enable='{'+'.join(enables)}',apad=whole_dur={float(dur):.3f},"
                f"aformat=sample_rates=48000:channel_layouts=stereo[narr]")
    else:
        narr = (f"[1:a]apad=whole_dur={float(dur):.3f},aformat=sample_rates=48000:channel_layouts=stereo[narr]")
    chains = [narr]
    mix_labs, only_labs = [], []
    for i, c in enumerate(audible):
        skip = float(c.get("src_skip") or 0)
        play = max(0.05, min(float(c["show"]), float(c.get("seconds") or c["show"])))
        delay = int(round(float(c["offset"]) * 1000))
        lab = f"a{i}"
        chains.append(
            f"[{i + 2}:a]atrim={skip:.3f}:{skip + play:.3f},asetpts=PTS-STARTPTS,adelay={delay}|{delay},"
            f"apad=whole_dur={float(dur):.3f},aformat=sample_rates=48000:channel_layouts=stereo[{lab}]")
        (only_labs if c.get("audio") == "clip" else mix_labs).append(lab)
    tails, n_in = ["[narr]"], 1
    if mix_labs:
        if len(mix_labs) == 1:
            mixbus = mix_labs[0]
        else:
            chains.append("".join(f"[{x}]" for x in mix_labs) +
                          f"amix=inputs={len(mix_labs)}:duration=longest:dropout_transition=0:normalize=0[mixbus]")
            mixbus = "mixbus"
        chains.append(f"[narr]asplit=2[nmain][nsc];[{mixbus}][nsc]sidechaincompress="
                      "threshold=0.02:ratio=8:attack=20:release=250[ducked]")
        tails, n_in = ["[nmain]", "[ducked]"], 2
    if only_labs:
        if len(only_labs) == 1:
            tails.append(f"[{only_labs[0]}]")
        else:
            chains.append("".join(f"[{x}]" for x in only_labs) +
                          f"amix=inputs={len(only_labs)}:duration=longest:dropout_transition=0:normalize=0[onlybus]")
            tails.append("[onlybus]")
        n_in += 1
    if n_in == 1:
        chains.append(f"{tails[0]}anull[aout]")
    else:
        chains.append("".join(tails) + f"amix=inputs={n_in}:duration=first:dropout_transition=0:normalize=0[aout]")
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", ";".join(chains),
            "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-ar", "48000", "-ac", "2", "-t", f"{float(dur):.3f}", "-movflags", "+faststart", str(out)]


def usage_cost(u: dict) -> float:
    return (u.get("input_tokens", 0) * PRICES["input"] + u.get("output_tokens", 0) * PRICES["output"]
            + u.get("cache_creation_input_tokens", 0) * PRICES["cache_write"]
            + u.get("cache_read_input_tokens", 0) * PRICES["cache_read"]) / 1e6


# ---------------------------------------------------------------------------
# Script
# ---------------------------------------------------------------------------

def script_body(script: str) -> str:
    """The script itself, without sections the pipeline appends after it (the
    B-roll table, HeyGen ready script ...): everything before the first
    markdown heading or ==== rule that follows some Host: text."""
    lines = (script or "").replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        if re.match(r"^(#\s|={5,}\s*$)", line):
            head = "\n".join(lines[:i]).strip()
            if "Host:" in head or "[PRODUCTION BEGIN]" in head:
                return head
    return "\n".join(lines).strip()


def production_counts(body: str) -> dict:
    count = lambda pat: len(re.findall(pat, body or "", re.I))
    return {"host": count(r"Host:"), "verify": count(r"\[VERIFY BEFORE RENDER\]"),
            "scenes": count(r"\[GROK IMAGINE"), "on_screen": count(r"\[ON SCREEN"),
            "inserts": count(r"\[insert\]")}


# ---------------------------------------------------------------------------
# Audio and word timing
# ---------------------------------------------------------------------------

def normalize_audio(src: Path, wav: Path, m4a: Path) -> dict:
    """Two-pass loudnorm to -14 LUFS (true peak -1.5 dBTP): a 48 kHz stereo WAV
    for the final mux and an AAC copy for the browser preview."""
    r = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af",
              "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"])
    found = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr)
    if not found:
        raise RuntimeError("ffmpeg loudnorm did not report the loudness")
    m = json.loads(found[-1])
    af = ("loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={input_i}:measured_TP={input_tp}:"
          "measured_LRA={input_lra}:measured_thresh={input_thresh}:offset={target_offset}:"
          "linear=true").format(**m)
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af", af,
          "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(wav)])
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav),
          "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(m4a)])
    return {"input_lufs": float(m["input_i"]), "target_lufs": -14.0}


def align_words(audio: Path, text: str, key: str, timeout: float = 900) -> "tuple[list, Optional[float]]":
    """Word start/end times from ElevenLabs forced alignment of `text` to `audio`."""
    import requests
    with open(audio, "rb") as fh:
        resp = requests.post(ELEVEN_ALIGN_URL, headers={"xi-api-key": key},
                             files={"file": (Path(audio).name, fh, "audio/mpeg")},
                             data={"text": text}, timeout=timeout)
    if resp.status_code != 200:
        detail = ""
        try:
            d = resp.json().get("detail")
            detail = d.get("message") if isinstance(d, dict) else (
                "; ".join(str(x.get("msg") or x) for x in d) if isinstance(d, list) else str(d or ""))
        except Exception:
            detail = (resp.text or "")[:300]
        raise RuntimeError(f"ElevenLabs word timing failed ({resp.status_code}): {detail or 'no details'}")
    body = resp.json() or {}
    words = [{"text": (w.get("text") or "").strip(), "start": float(w.get("start") or 0),
              "end": float(w.get("end") or 0)}
             for w in body.get("words") or [] if (w.get("text") or "").strip()]
    if not words:
        raise RuntimeError("ElevenLabs returned no word timings")
    return words, body.get("loss")


def estimate_words(text: str, duration: float, pauses: list) -> list:
    """Fallback timing: spread the words over the non-silent stretches of the
    audio in proportion to their length. Cues can drift by a second or two."""
    raw = (text or "").split()
    speech, cur = [], 0.0
    for s, e in sorted(pauses or []):
        if s > cur:
            speech.append((cur, s))
        cur = max(cur, e)
    if cur < duration:
        speech.append((cur, duration))
    total = sum(e - s for s, e in speech) or duration or 1.0

    def at(x: float) -> float:
        for s, e in speech:
            if x <= e - s:
                return s + x
            x -= e - s
        return duration

    weights = [len(w) + 1 for w in raw]
    whole = sum(weights) or 1
    out, acc = [], 0.0
    for w, wt in zip(raw, weights):
        a = acc / whole * total
        acc += wt
        b = acc / whole * total
        out.append({"text": w, "start": round(at(a), 3), "end": round(at(max(a, b - 0.02)), 3)})
    return out


_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")


def tokens(text: str) -> list:
    return _TOKEN_RE.findall((text or "").lower().replace("’", "'").replace("‘", "'"))


class Timeline:
    """The timed transcript, searchable by spoken phrase."""

    def __init__(self, words: list, duration: float):
        self.words = words
        self.duration = duration
        self.toks = []          # (token, start, end)
        for w in words:
            ts = tokens(w["text"])
            span = max(0.0, w["end"] - w["start"])
            for k, t in enumerate(ts):
                self.toks.append((t, w["start"] + span * k / len(ts), w["start"] + span * (k + 1) / len(ts)))
        self.starts = [t[1] for t in self.toks]

    def find(self, phrase: str, floor: float = 0.0, limit: Optional[float] = None):
        """(start, end, quality) of the first match at or after `floor`:
        exact token match first, then the closest window (ratio >= 0.78)."""
        p = tokens(phrase)
        if not p or not self.toks:
            return None
        m = len(p)
        i0 = bisect.bisect_left(self.starts, floor)
        i1 = len(self.toks) if limit is None else bisect.bisect_right(self.starts, limit)
        last = min(i1, len(self.toks) - m + 1)
        for i in range(i0, last):
            if self.toks[i][0] == p[0] and all(self.toks[i + k][0] == p[k] for k in range(1, m)):
                return self.toks[i][1], self.toks[i + m - 1][2], "exact"
        target = " ".join(p)
        best, best_i = 0.0, None
        sm = difflib.SequenceMatcher(autojunk=False)
        sm.set_seq2(target)
        for i in range(i0, last):
            sm.set_seq1(" ".join(t[0] for t in self.toks[i:i + m]))
            if sm.real_quick_ratio() < 0.78 or sm.quick_ratio() < 0.78:
                continue
            r = sm.ratio()
            if r > best:
                best, best_i = r, i
        if best_i is not None and best >= 0.78:
            return self.toks[best_i][1], self.toks[best_i + m - 1][2], "approx"
        return None

    def window_text(self, t0: float, t1: float) -> str:
        return " ".join(w["text"] for w in self.words if t0 - 0.01 <= w["start"] < t1)

    def sentences(self) -> list:
        out, cur = [], []
        for k, w in enumerate(self.words):
            cur.append(w)
            nxt = self.words[k + 1] if k + 1 < len(self.words) else None
            if (nxt is None or re.search(r"[.!?…][\"'”’)]*$", w["text"])
                    or nxt["start"] - w["end"] > 0.7 or len(cur) >= 45):
                out.append((cur[0]["start"], cur[-1]["end"], " ".join(x["text"] for x in cur)))
                cur = []
        return out

    def transcript(self) -> str:
        return "\n".join(f"[{s:.1f}] {txt}" for s, _e, txt in self.sentences())


# ---------------------------------------------------------------------------
# Logos
# ---------------------------------------------------------------------------

_LOGO_NOISE = {"logo", "logos", "icon", "icons", "icons8", "png", "svg", "webp", "jpg", "jpeg",
               "seeklogo", "transparent", "background", "backgr", "bg", "blue", "black", "white",
               "dark", "light", "color", "colour", "vector", "official", "full", "horizontal",
               "vertical", "symbol", "mark", "wordmark", "brand", "hd", "large", "small"}


def logo_name_from_file(filename: str) -> str:
    """A brand name guessed from a logo file name: 'icons8-amazon-480.png' ->
    'Amazon', 'google-deepmind-logo-png_seeklogo-284971.png' -> 'Google Deepmind'."""
    stem = Path(filename).name
    while Path(stem).suffix.lower() in LOGO_EXTS:
        stem = Path(stem).stem
    words = [w for w in re.split(r"[^A-Za-z0-9]+", stem) if w]
    keep = [w for w in words
            if w.lower() not in _LOGO_NOISE and not re.fullmatch(r"\d+", w)
            and not (len(w) >= 6 and re.fullmatch(r"[0-9a-f]+", w.lower()) and re.search(r"\d", w))]
    keep = keep or words[:1] or ["Logo"]
    return " ".join(w if w.isupper() and len(w) <= 5 else w.capitalize() for w in keep)[:40]


def logo_info(path: Path) -> dict:
    """Size, aspect and transparency of a logo file (SVG via its viewBox)."""
    if path.suffix.lower() == ".svg":
        txt = path.read_text(encoding="utf-8", errors="ignore")[:4000]
        m = re.search(r"viewBox\s*=\s*[\"']\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)", txt)
        w, h = (float(m.group(1)), float(m.group(2))) if m else (1.0, 1.0)
        return {"width": w, "height": h, "aspect": round(w / h, 2) if h else 1.0, "transparent": True}
    from PIL import Image
    with Image.open(path) as im:
        w, h = im.size
        transparent = False
        if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
            alpha = im.convert("RGBA").getchannel("A")
            transparent = alpha.getextrema()[0] < 250
    return {"width": w, "height": h, "aspect": round(w / h, 2) if h else 1.0, "transparent": transparent}


def process_logo(src: Path, out_dir: Path, key: str, recolor: str = "auto") -> dict:
    """Prepare a logo for the dark background: remove a plain white background
    when the file has no transparency, crop to the content, and recolor dark
    neutral marks to off-white ('auto'), every mark ('white') or none
    ('original'). Wide logos (aspect >= 1.8) are wordmarks; squarer ones icons."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".svg":
        dst = out_dir / f"{key}.svg"
        shutil.copyfile(src, dst)
        info = logo_info(dst)
        return {"file": dst.name, "kind": "wordmark" if info["aspect"] >= 1.8 else "icon",
                "aspect": info["aspect"], "recolored": recolor == "white", "svg": True}
    from PIL import Image, ImageChops
    with Image.open(src) as im0:
        im = im0.convert("RGBA")
    if max(im.size) > 1400:
        im.thumbnail((1400, 1400), Image.LANCZOS)
    r, g, b, a = im.split()
    if a.getextrema()[0] >= 250:
        corners = [im.getpixel(p) for p in ((0, 0), (im.width - 1, 0), (0, im.height - 1),
                                             (im.width - 1, im.height - 1))]
        if all(min(c[:3]) >= 235 for c in corners):
            # Plain white background: fade near-white pixels to transparent.
            lum = im.convert("L")
            a = ImageChops.invert(lum.point(lambda v: 0 if v < 225 else min(255, (v - 225) * 9)))
            im.putalpha(a)
    bbox = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if bbox:
        pad = max(2, int(0.02 * max(bbox[2] - bbox[0], bbox[3] - bbox[1])))
        im = im.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                      min(im.width, bbox[2] + pad), min(im.height, bbox[3] + pad)))
    recolored = False
    if recolor in ("auto", "white"):
        r, g, b, a = im.split()
        opaque = a.point(lambda v: 255 if v > 128 else 0)
        if recolor == "white":
            dark_neutral = Image.new("L", im.size, 255)
        else:
            mx = ImageChops.lighter(ImageChops.lighter(r, g), b)
            mn = ImageChops.darker(ImageChops.darker(r, g), b)
            neutral = ImageChops.subtract(mx, mn).point(lambda v: 255 if v < 35 else 0)
            dark = im.convert("RGB").convert("L").point(lambda v: 255 if v < 150 else 0)
            dark_neutral = ImageChops.multiply(neutral, dark)
        share = ImageChops.multiply(dark_neutral, opaque).histogram()[255] / (opaque.histogram()[255] or 1)
        if recolor == "white" or share >= 0.15:
            white = Image.new("RGBA", im.size, OFF_WHITE + (255,))
            white.putalpha(a)
            # Antialiased (partly transparent) edges of the mark go off-white too.
            im = Image.composite(white, im, dark_neutral)
            recolored = True
    dst = out_dir / f"{key}.png"
    im.save(dst, "PNG", optimize=True)
    aspect = round(im.width / im.height, 2) if im.height else 1.0
    return {"file": dst.name, "kind": "wordmark" if aspect >= 1.8 else "icon", "aspect": aspect,
            "recolored": recolored, "svg": False}


_URI_CACHE: dict = {}


def data_uri(path: Path) -> str:
    st = path.stat()
    k = (str(path), st.st_mtime, st.st_size)
    if k not in _URI_CACHE:
        mime = "image/svg+xml" if path.suffix.lower() == ".svg" else "image/png"
        _URI_CACHE[k] = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    return _URI_CACHE[k]


def badge_uri(name: str, final: bool = False) -> str:
    """A styled text badge standing in for a logo file the user has not added."""
    name = (name or "Logo").strip()[:28]
    w, h = max(180, int(len(name) * 27 + 72)), 96
    dash = "" if final else ' stroke-dasharray="10 8"'
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
           f'<rect x="2" y="2" width="{w - 4}" height="{h - 4}" rx="20" fill="#1a2232" stroke="#8a94a6" '
           f'stroke-width="3"{dash}/><text x="{w / 2}" y="{h / 2 + 14}" text-anchor="middle" '
           f'font-family="Inter, Helvetica, Arial, sans-serif" font-size="40" font-weight="800" '
           f'fill="#f2f4f8">{_html.escape(name)}</text></svg>')
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


# ---------------------------------------------------------------------------
# Presenter video: HeyGen clips (or one long video) matched to the narration
# ---------------------------------------------------------------------------

_PART_RE = re.compile(r"^(?P<stem>.+)_part(?P<i>\d+)of(?P<n>\d+)$")
_PROBES: dict = {}


def probe_video(path: Path) -> Optional[dict]:
    """Duration, size, frame rate and audio of a video file (cached per file version)."""
    try:
        st = Path(path).stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime, st.st_size)
    if key in _PROBES:
        return _PROBES[key]
    info = None
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration:stream=codec_type,width,height,avg_frame_rate",
                            "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
        d = json.loads(r.stdout or "{}")
        streams = d.get("streams") or []
        v = next((s for s in streams if s.get("codec_type") == "video" and s.get("width")), None)
        secs = float((d.get("format") or {}).get("duration") or 0)
        if v and secs > 0:
            num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
            info = {"seconds": round(secs, 3), "w": int(v["width"]), "h": int(v.get("height") or 0),
                    "fps": round(float(num) / float(den), 3) if float(den or 0) else 0.0,
                    "audio": any(s.get("codec_type") == "audio" for s in streams)}
    except (subprocess.SubprocessError, ValueError, TypeError, KeyError):
        info = None
    _PROBES[key] = info
    return info


def local_videos(root: Path, max_depth: int = 3) -> list:
    """Video files in the script folder big enough to be presenter footage,
    with their length, size and audio (ffprobe results are cached)."""
    root = Path(root)
    vids = []
    if not root.is_dir():
        return vids
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "explainer"] if depth < max_depth else []
        for f in filenames:
            p = Path(dirpath) / f
            if f.startswith(".") or p.suffix.lower() not in HOST_VIDEO_EXTS:
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_size < HOST_MIN_BYTES:
                continue
            info = probe_video(p)
            if info and info["seconds"] >= 3 and info["h"]:
                vids.append({"path": p, "rel": p.relative_to(root).as_posix(), "mtime": st.st_mtime, **info})
    return vids


def best_upscale(part: dict, vids: list, skip: set) -> Optional[dict]:
    """A larger copy of about the same length (an upscale); one named after
    the clip wins, then the closest length. Clips of a set can be within a
    few hundredths of a second of each other, so attach_clips checks the
    footage before using it."""
    stem = Path(part["path"]).stem.lower()
    best, best_key = None, None
    for v in vids:
        gap = abs(v["seconds"] - part["seconds"])
        if v["path"] in skip or v["path"] == part["path"] or gap > 0.6 or v["h"] <= part["h"]:
            continue
        key = (stem in v["path"].stem.lower(), -gap, v["h"], v["mtime"])
        if best is None or key > best_key:
            best, best_key = v, key
    return best


def clip_item(path: Path, vids: Optional[list] = None, skip: Optional[set] = None) -> Optional[dict]:
    """A presenter clip ready for attach_clips: the file, its probe and the
    upscale to use in its place (if any)."""
    info = probe_video(Path(path))
    if not info:
        return None
    up = best_upscale({"path": Path(path), **info}, vids or [], skip or set())
    return {"orig": str(Path(path).resolve()), **info,
            "up": ({"file": str(up["path"].resolve()), "seconds": up["seconds"], "w": up["w"], "h": up["h"],
                    "audio": up["audio"]} if up else None)}


def find_host_sources(root: Path, lengths: Optional[list] = None, max_depth: int = 3) -> list:
    """Presenter footage in the script folder: complete HeyGen clip sets
    (…_part1of3.mp4 …) and single videos, as long as one of the narrations
    in `lengths` (seconds; None: any). For each part, a larger copy of the
    same length elsewhere in the folder (an upscale) is picked up."""
    root = Path(root)
    vids = local_videos(root, max_depth)
    sets: dict = {}
    for v in vids:
        m = _PART_RE.match(v["path"].stem)
        if m:
            sets.setdefault((str(v["path"].parent), m.group("stem"), int(m.group("n"))), {})[int(m.group("i"))] = v
    sources, members, upscales = [], set(), set()

    def part_rec(v, skip):
        up = best_upscale(v, vids, skip)
        if up:
            upscales.add(up["path"])
            skip.add(up["path"])            # one clip per upscale within a source
        return {"rel": v["rel"], "seconds": v["seconds"], "w": v["w"], "h": v["h"], "fps": v["fps"],
                "audio": v["audio"], "upscale": ({"rel": up["rel"], "w": up["w"], "h": up["h"],
                                                  "seconds": up["seconds"], "audio": up["audio"]} if up else None)}

    for (folder, stem, n), parts in sets.items():
        if sorted(parts) != list(range(1, n + 1)):
            continue
        skip = {v["path"] for v in parts.values()}
        members |= skip
        recs = [part_rec(parts[i], skip) for i in range(1, n + 1)]
        sources.append({"id": "set:" + (Path(parts[1]["rel"]).parent / stem).as_posix(), "kind": "clips",
                        "label": f"HeyGen clips ({n}) · {stem}", "parts": recs,
                        "seconds": round(sum(r["seconds"] for r in recs), 3),
                        "mtime": max(v["mtime"] for v in parts.values())})
    for v in vids:
        if v["path"] in members:
            continue
        sources.append({"id": "file:" + v["rel"], "kind": "video", "label": v["path"].name,
                        "parts": [part_rec(v, {v["path"]})], "seconds": v["seconds"], "mtime": v["mtime"],
                        "_path": v["path"]})
    sources = [s for s in sources if s.pop("_path", None) not in upscales
               and (lengths is None or any(abs(s["seconds"] - float(n)) <= 2.5 for n in lengths))]
    for s in sources:
        s["height"] = min((p["upscale"] or p)["h"] for p in s["parts"])
        s["upscaled"] = sum(1 for p in s["parts"] if p["upscale"])
    sources.sort(key=lambda s: s["mtime"], reverse=True)
    return sources


def _envelope(path: Path, start: float, seconds: float, rate: int = 100) -> list:
    """The audio's level (mean absolute sample) per 1/rate s from `start`."""
    sr = 8000
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-t", f"{seconds:.3f}",
                        "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                       capture_output=True, timeout=300)
    a = array.array("h")
    a.frombytes(r.stdout[: len(r.stdout) // 2 * 2])
    if sys.byteorder != "little":
        a.byteswap()
    step = sr // rate
    return [sum(map(abs, a[i:i + step])) / step for i in range(0, len(a) - step + 1, step)]


def _best_lag(a: list, b: list) -> "tuple[float, float]":
    """(lag, score): where `a` lines up inside `b` (Pearson correlation of the
    two level curves), with the lag refined between samples."""
    n = len(a)
    if n < 50 or len(b) < n:
        return 0.0, 0.0
    mean = sum(a) / n
    da = [x - mean for x in a]
    sa = math.sqrt(sum(x * x for x in da)) or 1.0
    pb, pb2 = [0.0], [0.0]
    for x in b:
        pb.append(pb[-1] + x)
        pb2.append(pb2[-1] + x * x)
    scores = []
    for lag in range(len(b) - n + 1):
        sb, sb2 = pb[lag + n] - pb[lag], pb2[lag + n] - pb2[lag]
        var = sb2 - sb * sb / n
        scores.append(sum(map(operator.mul, da, b[lag:lag + n])) / (sa * math.sqrt(var)) if var > 1e-9 else 0.0)
    k = max(range(len(scores)), key=scores.__getitem__)
    lag = float(k)
    if 0 < k < len(scores) - 1:
        y0, y1, y2 = scores[k - 1], scores[k], scores[k + 1]
        den = y0 - 2 * y1 + y2
        if den < 0:
            lag += 0.5 * (y0 - y2) / den
    return lag, scores[k]


def align_clip(narration: Path, clip: Path, expected: float, clip_seconds: float,
               at_end: bool = False) -> "tuple[float, float]":
    """(offset, score): the narration time where the clip's own time 0 falls,
    found by matching ~20 s of its audio near `expected`."""
    length = max(4.0, min(20.0, clip_seconds - 4.0))
    s0 = max(0.0, clip_seconds - length - 2.0) if at_end else min(2.0, max(0.0, clip_seconds - length))
    a = _envelope(clip, s0, length)
    w0 = max(0.0, expected + s0 - HOST_SEARCH)
    b = _envelope(narration, w0, length + 2 * HOST_SEARCH)
    lag, score = _best_lag(a, b)
    return round(w0 + lag / 100 - s0, 3), round(score, 3)


def _same_footage(a: Path, b: Path, seconds: float) -> bool:
    """Whether two videos show the same picture (tiny grayscale frames at two
    points), e.g. a clip and its upscale."""
    from PIL import Image, ImageChops, ImageStat
    worst = 0.0
    for f in (0.3, 0.7):
        ims = []
        for path in (a, b):
            r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{seconds * f:.3f}", "-i", str(path), "-frames:v", "1",
                                "-vf", "scale=64:36,format=gray", "-f", "rawvideo", "-"], capture_output=True, timeout=120)
            if len(r.stdout) != 64 * 36:
                return False
            ims.append(Image.frombytes("L", (64, 36), r.stdout))
        worst = max(worst, ImageStat.Stat(ImageChops.difference(*ims)).mean[0])
    return worst < 14


def place_clip(narration: Path, clip: Path, seconds: float, expected: Optional[float] = None,
               cache: Optional[dict] = None) -> "tuple[float, float]":
    """(offset, score): where the clip's time 0 falls in the narration. Near
    `expected` when given (the next clip of a set); otherwise anywhere: a
    coarse match on 10 Hz level curves, then the fine one around it."""
    if expected is not None:
        off, score = align_clip(narration, clip, expected, seconds)
        if score >= HOST_MIN_SCORE:
            return off, score
    cache = cache if cache is not None else {}
    if "curve" not in cache:
        cache["curve"] = _envelope(narration, 0.0, 1e5, rate=10)
    length = max(4.0, min(20.0, seconds - 4.0))
    s0 = min(2.0, max(0.0, seconds - length))
    lag, score = _best_lag(_envelope(clip, s0, length, rate=10), cache["curve"])
    if score < HOST_MIN_SCORE * 0.8:
        return round(lag / 10 - s0, 3), round(score, 3)
    return align_clip(narration, clip, lag / 10 - s0, seconds)


def attach_host(project: "Project", source: dict, root: Path, status: Callable, log: Callable,
                share: Optional[str] = None, pip_frame: Optional[str] = None) -> dict:
    """Use a presenter source found by find_host_sources (a HeyGen clip set
    or one video) as the project's presenter footage."""
    items = []
    for i, p in enumerate(source["parts"], 1):
        orig = (Path(root) / p["rel"]).resolve()
        up = p.get("upscale")
        if not orig.is_file() or (up and not (Path(root) / up["rel"]).is_file()):
            raise RuntimeError(f"Presenter clip {i} is missing: {p['rel']}")
        items.append({"orig": str(orig), "seconds": p["seconds"], "w": p["w"], "h": p["h"], "audio": p["audio"],
                      "up": ({"file": str((Path(root) / up["rel"]).resolve()), **{k: up[k] for k in ("seconds", "w", "h", "audio")}}
                             if up else None)})
    return attach_clips(project, items, status, log, share=share, pip_frame=pip_frame, replace=True, ordered=True,
                        source=source["id"], label=source["label"])


def attach_clips(project: "Project", items: list, status: Callable, log: Callable, *, share: Optional[str] = None,
                 pip_frame: Optional[str] = None, replace: bool = False, ordered: bool = False, source: str = "",
                 label: str = "") -> dict:
    """Place presenter clips (clip_item dicts) on the narration by their
    audio and add them to the project's presenter footage (or replace it).
    Clips made from another voiceover are refused. Then remake the preview
    copy and the still. Placed sections and the framing are kept."""
    narration = project.dir / "narration.wav"
    if not narration.is_file():
        raise RuntimeError("The narration is not prepared yet")
    status("presenter", "Matching the presenter clips to the narration\u2026", None)
    old = project.data.get("host") or {}
    parts = [] if replace else [dict(x) for x in old.get("parts") or []]
    have = {x["orig"] for x in parts}
    cache: dict = {}
    refused = []
    expected = 0.0 if ordered else None
    for i, it in enumerate(items, 1):
        orig = Path(it["orig"])
        if str(orig) in have:
            continue
        if not it.get("audio"):
            refused.append(f"{orig.name} has no audio track to match")
            continue
        status(message=f"Matching presenter clip {i} of {len(items)} to the narration\u2026")
        off, score = place_clip(narration, orig, it["seconds"], expected, cache)
        if score < HOST_MIN_SCORE:
            refused.append(f"{orig.name} does not match this narration (audio match {score:.2f}): it was made "
                           "from a different voiceover")
            continue
        end_off, end_score = align_clip(narration, orig, off, it["seconds"], at_end=True)
        drift = round(end_off - off, 3) if end_score >= HOST_MIN_SCORE else None
        up, use, u_off = it.get("up"), orig, None
        if up:
            # Make sure the larger copy is this clip: by its audio when it has
            # some (which also places it, as an upscale can gain or lose a
            # frame), otherwise by comparing frames.
            use = Path(up["file"])
            if up.get("audio"):
                u_off, u_score = align_clip(narration, use, off, up["seconds"])
                same = u_score >= HOST_MIN_SCORE and abs(u_off - off) < 0.5
            else:
                same = _same_footage(orig, use, it["seconds"])
            if not same:
                log(f"\u26a0\ufe0f {use.name} is not an upscale of {orig.name}; using the original", "warning")
                up, use, u_off = None, orig, None
        rec = {"file": str(use), "orig": str(orig), "offset": u_off if u_off is not None else off, "score": score,
               "drift": drift, "seconds": (up or it)["seconds"], "w": (up or it)["w"], "h": (up or it)["h"],
               "upscaled": bool(up)}
        parts.append(rec)
        have.add(str(orig))
        if ordered:
            expected = off + it["seconds"]
        log(f"\U0001f9d1\u200d\U0001f4bc Presenter clip {orig.name}: {fmt_secs(rec['offset'])}\u2013"
            f"{fmt_secs(rec['offset'] + rec['seconds'])} of the narration (audio match {score:.2f}"
            f"{', drift %+.2fs' % drift if drift else ''}, {rec['w']}x{rec['h']}{', upscaled copy' if up else ''})")
    for msg in refused:
        log(f"\u26a0\ufe0f {msg}", "warning")
    if not parts:
        raise RuntimeError("; ".join(refused) or "No presenter clips to use")
    if refused and replace and ordered:
        raise RuntimeError("Presenter " + "; ".join(refused))
    host = {"source": source or old.get("source") or "clips", "label": label or old.get("label") or "Presenter clips",
            "parts": sorted(parts, key=lambda x: x["offset"]), "sections": list(old.get("sections") or []),
            "focus": old.get("focus", HOST_FOCUS),
            "share": host_share_key(share, old.get("share")),
            "pip_frame": pip_frame_key(pip_frame, old.get("pip_frame") or project.data.get("pip_frame")),
            "refused": refused, "created": time.time()}
    _host_preview(project, host, status)
    with project.lock:
        project.data["host"] = host
    project.save()
    return host


def remove_clip(project: "Project", name: str, status: Callable) -> Optional[dict]:
    """Take one clip out of the presenter footage (by file name)."""
    host = project.host()
    if not host:
        return None
    parts = [x for x in host["parts"] if Path(x["orig"]).name != name and Path(x["file"]).name != name]
    if len(parts) == len(host["parts"]):
        raise RuntimeError(f"No presenter clip {name}")
    if not parts:
        with project.lock:
            project.data["host"] = None
        project.save()
        return None
    host = {**host, "parts": parts, "created": time.time()}
    _host_preview(project, host, status)
    with project.lock:
        project.data["host"] = host
    project.save()
    return host


def _host_preview(project: "Project", host: dict, status: Callable) -> None:
    """The 640x360 preview copy on the narration's timeline, and a still."""
    status("presenter", "Making the presenter preview copy\u2026", None)
    folder = project.dir / "host"
    folder.mkdir(exist_ok=True)
    segs = host_segments(host)
    _ffmpeg_host_track(segs, folder / "proxy.mp4", 640, 360, crf=30, preset="veryfast")
    t = min(segs[0]["t1"] - 0.5, segs[0]["t0"] + 20.0)
    still = host_frame(segs, t, 960, 540)
    if still is not None:
        still.convert("RGB").save(folder / "still.jpg", quality=88)
    host["proxy"] = "host/proxy.mp4"


def host_coverage(host: dict) -> list:
    """[(t0, t1)] stretches of the narration the presenter footage covers."""
    spans = []
    for seg in host_segments(host):
        if spans and seg["t0"] - spans[-1][1] < 0.3:
            spans[-1] = (spans[-1][0], seg["t1"])
        else:
            spans.append((seg["t0"], seg["t1"]))
    return [(round(a, 2), round(b, 2)) for a, b in spans]


def host_segments(host: dict) -> list:
    """Pieces of footage on the narration timeline, in time order:
    [{file, src, t0, t1, w, h}] (src = the file time at t0). Where clips
    overlap, the earlier one plays until it ends; a gap of up to a quarter
    second between clips is bridged by the previous clip's last frame."""
    parts = sorted(host.get("parts") or [], key=lambda p: p["offset"])
    out, prev = [], 0.0
    for p in parts:
        t0 = max(p["offset"], prev, 0.0)
        t1 = p["offset"] + p["seconds"]
        if t1 - t0 > 0.02:
            if out and 0 < t0 - out[-1]["t1"] < 0.25:
                out[-1]["t1"] = round(t0, 4)
            out.append({"file": p["file"], "src": round(t0 - p["offset"], 4), "t0": round(t0, 4),
                        "t1": round(t1, 4), "w": p["w"], "h": p["h"]})
        prev = max(prev, t1)
    return out


def clean_sections(sections: list, duration: float) -> list:
    """The user's presenter sections, checked and in time order:
    [{t0, t1, layout}] at least half a second long, inside the video,
    overlapping sections of the same layout merged."""
    out = []
    for x in sections or []:
        try:
            t0, t1 = round(max(0.0, float(x.get("t0"))), 2), round(min(float(duration), float(x.get("t1"))), 2)
        except (TypeError, ValueError, AttributeError):
            continue
        layout = x.get("layout")
        if layout in HOST_LAYOUTS and t1 - t0 >= 0.5:
            out.append({"t0": t0, "t1": t1, "layout": layout})
    out.sort(key=lambda x: (x["t0"], x["t1"]))
    merged = []
    for x in out:
        same = next((m for m in merged if m["layout"] == x["layout"] and x["t0"] <= m["t1"]), None)
        if same:
            same["t1"] = max(same["t1"], x["t1"])
        else:
            merged.append(x)
    return merged


def _cover(src_w: int, src_h: int, w: int, h: int, focus: float = 0.5) -> "tuple[int, int, int, int]":
    """Scale (sw, sh) that covers a w x h box, and the crop (x, y) keeping
    `focus` (0-1 across the frame) in view."""
    s = max(w / max(1, src_w), h / max(1, src_h))
    sw, sh = max(w, int(math.ceil(src_w * s / 2) * 2)), max(h, int(math.ceil(src_h * s / 2) * 2))
    x = int(round(min(max(focus * sw - w / 2, 0), sw - w)))
    return sw, sh, x, (sh - h) // 2


def _host_box(layout: str, k: float) -> dict:
    L = HOST_LAYOUTS[layout]
    even = lambda v: int(round(v * k / 2)) * 2
    return {"x": even(L["x"]), "y": even(L["y"]), "w": even(L["w"]), "h": even(L["h"])}


def _window_box(win: dict, k: float) -> dict:
    """Where the presenter footage goes. A framed corner uses the device's
    screen; everything else uses the layout's own rectangle."""
    frame = (win.get("frame") or "") if win.get("layout") == "pip" else ""
    geom = PIP_FRAME_GEOM.get(frame)
    if not geom:
        return _host_box(win["layout"], k)
    x, y, w, h = geom["screen"]
    even = lambda v: int(round(v * k / 2)) * 2
    return {"x": even(x), "y": even(y), "w": max(2, even(w)), "h": max(2, even(h))}


def _ffmpeg_host_track(segs: list, out: Path, w: int, h: int, crf: int = 30, preset: str = "veryfast") -> None:
    """The footage as one w x h, 30 fps video on the narration's timeline
    (black before the first clip), for the preview player."""
    inputs, chains, labels = [], [], []
    if segs and segs[0]["t0"] > 0.01:
        chains.append(f"color=c=black:s={w}x{h}:r={FPS}:d={segs[0]['t0']:.4f},format=yuv420p[pre]")
        labels.append("pre")
    for k, s in enumerate(segs):
        sw, sh, x, y = _cover(s["w"], s["h"], w, h)
        inputs += ["-ss", f"{s['src']:.4f}", "-t", f"{s['t1'] - s['t0'] + 0.5:.4f}", "-i", s["file"]]
        chains.append(f"[{k}:v]setpts=PTS-STARTPTS,fps={FPS},scale={sw}:{sh}:flags=bicubic,crop={w}:{h}:{x}:{y},"
                      f"setsar=1,format=yuv420p,tpad=stop_mode=clone:stop_duration=0.5,"
                      f"trim=duration={s['t1'] - s['t0']:.4f},setpts=PTS-STARTPTS[s{k}]")
        labels.append(f"s{k}")
    graph = ";".join(chains) + ";" + "".join(f"[{x}]" for x in labels) + f"concat=n={len(labels)}:v=1:a=0[v]"
    tmp = out.with_suffix(".part.mp4")
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", graph, "-map", "[v]",
          "-an", "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-g", str(FPS), "-pix_fmt", "yuv420p",
          "-movflags", "+faststart", str(tmp)])
    tmp.replace(out)


def host_frame(segs: list, t: float, w: int, h: int, layout: str = "full", focus: float = 0.5):
    """The presenter at narration time t, cropped to a w x h box (PIL image), or None."""
    from PIL import Image
    seg = next((s for s in segs if s["t0"] <= t < s["t1"]), None) or (segs[-1] if segs and t >= segs[-1]["t0"] else None)
    if seg is None:
        return None
    sw, sh, x, y = _cover(seg["w"], seg["h"], w, h, focus if layout in ("left", "right") else 0.5)
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{seg['src'] + t - seg['t0']:.4f}", "-i", seg["file"],
                        "-frames:v", "1", "-vf", f"scale={sw}:{sh}:flags=lanczos,crop={w}:{h}:{x}:{y}",
                        "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True, timeout=120)
    if r.returncode != 0 or not r.stdout:
        return None
    return Image.open(io.BytesIO(r.stdout)).convert("RGB")


def composite_host(png: bytes, t: float, windows: list, segs: list, focus: float) -> bytes:
    """Put the presenter under a rendered page frame (PNG with see-through
    presenter areas) at time t. Frames with no presenter come back as is."""
    live = [w for w in windows or [] if w["t0"] <= t < w["t1"]]
    if not live or not segs:
        return png
    from PIL import Image
    page = Image.open(io.BytesIO(png)).convert("RGBA")
    k = page.width / 1920
    base = Image.new("RGBA", page.size, (0, 0, 0, 255))
    for w in live:
        box = _window_box(w, k)
        im = host_frame(segs, t, box["w"], box["h"], w["layout"], focus)
        if im is not None:
            base.paste(im, (box["x"], box["y"]))
    base.alpha_composite(page)
    buf = io.BytesIO()
    base.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def _host_filter(plan: dict, a_t: float, b_t: float) -> "tuple[list, str]":
    """ffmpeg inputs (after the page pipe, input 0) and filter graph that put
    the presenter under the page frames of [a_t, b_t): each presenter window
    decodes only its own stretch of footage, cropped to its layout, and the
    page (RGBA) goes on top with its bt709 colors kept."""
    k, W, H = plan["k"], plan["W"], plan["H"]
    inputs, chains, n = [], [f"color=c=black:s={W}x{H}:r={FPS}:d={b_t - a_t:.4f},format=yuv420p[b0]"], 1
    base, j = "b0", 0
    for win in plan["windows"]:
        a, b = max(win["t0"], a_t), min(win["t1"], b_t)
        if b - a < 0.5 / FPS:
            continue
        box = _window_box(win, k)
        focus = plan["focus"] if win["layout"] in ("left", "right") else 0.5
        pieces = []
        for seg in plan["segments"]:
            s, e = max(a, seg["t0"]), min(b, seg["t1"])
            if e - s < 0.5 / FPS:
                continue
            sw, sh, x, y = _cover(seg["w"], seg["h"], box["w"], box["h"], focus)
            inputs += ["-ss", f"{seg['src'] + s - seg['t0']:.4f}", "-t", f"{e - s + 0.5:.4f}", "-i", seg["file"]]
            lab = f"p{j}_{len(pieces)}"
            chains.append(f"[{n}:v]setpts=PTS-STARTPTS,fps={FPS},scale={sw}:{sh}:flags=lanczos,"
                          f"crop={box['w']}:{box['h']}:{x}:{y},setsar=1,format=yuv420p,"
                          f"tpad=stop_mode=clone:stop_duration=0.5,trim=duration={e - s:.4f},setpts=PTS-STARTPTS[{lab}]")
            pieces.append((lab, s))
            n += 1
        if not pieces:
            continue
        start = pieces[0][1]
        if len(pieces) > 1:
            chains.append("".join(f"[{p}]" for p, _s in pieces) + f"concat=n={len(pieces)}:v=1:a=0[w{j}]")
        else:
            chains.append(f"[{pieces[0][0]}]null[w{j}]")
        chains.append(f"[w{j}]setpts=PTS-STARTPTS+{start - a_t:.4f}/TB[ws{j}]")
        chains.append(f"[{base}][ws{j}]overlay={box['x']}:{box['y']}:eof_action=pass:"
                      f"enable='between(t,{a - a_t - 0.001:.4f},{b - a_t:.4f})'[b{j + 1}]")
        base, j = f"b{j + 1}", j + 1
    chains.append("[0:v]scale=out_color_matrix=bt709:out_range=tv,format=yuva444p[pg]")
    chains.append(f"[{base}]format=yuv444p[bb];[bb][pg]overlay=0:0:format=yuv444:shortest=1,format=yuv420p[v]")
    return inputs, ";".join(chains)


# ---------------------------------------------------------------------------
# Composition: sanitize, cue, compile
# ---------------------------------------------------------------------------

_SKIP = {"script", "iframe", "object", "noscript", "template", "form", "select", "textarea",
         "audio", "video", "canvas", "frameset", "frame", "applet", "title", "head", "button",
         "datalist", "dialog", "portal", "lineargradient", "radialgradient", "filter",
         "animate", "animatemotion", "animatetransform", "set", "discard", "math", "svg:script"}
_VOID_DROP = {"link", "meta", "base", "input", "source", "track", "param", "embed", "keygen"}
_UNWRAP = {"a", "html", "body", "font", "center", "label"}
_HTML_VOID = {"area", "br", "col", "hr", "img", "wbr"}
_SVG_SHAPES = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "image", "use", "stop"}
_URL_ATTRS = {"href", "xlink:href", "src", "srcset", "action", "formaction", "background",
              "poster", "data", "codebase", "cite", "ping", "manifest"}
_CSS_BANNED = ("animation", "transition", "filter", "backdrop-filter", "box-shadow",
               "text-shadow", "-webkit-box-shadow", "-webkit-filter", "mask-image",
               "-webkit-mask-image", "behavior")
ANIMS = {"rise", "words", "left", "right", "up", "down", "pop", "stamp", "fade", "zoom", "wipe",
         "wipe-up", "draw", "count", "ring"}
LOOPS = {"float", "spin", "pulse", "blink", "drift", "twinkle"}
_NUM_RE = re.compile(r"^[+]?\d+(\.\d+)?$")


def ph_key(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", text or "")[:60]


def logo_key(text: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", (text or "").strip().lower())[:40]


def _clean_decls(decls: str, warn: Callable) -> str:
    out = []
    for d in decls.split(";"):
        if ":" not in d:
            continue
        prop, val = d.split(":", 1)
        p, v = prop.strip().lower(), val.strip()
        if not p or not v:
            continue
        lv = v.lower()
        if any(p == b or p.startswith(b + "-") for b in _CSS_BANNED):
            warn(f"removed CSS {p}")
            continue
        if "gradient(" in lv:
            warn("removed a gradient")
            continue
        if "url(" in lv and not re.search(r"url\(\s*['\"]?#", lv):
            warn("removed an external url()")
            continue
        if "expression(" in lv or "javascript:" in lv or "@import" in lv:
            continue
        if p == "position" and lv.startswith("fixed"):
            v = "absolute"
        out.append(f"{p}: {v}")
    return "; ".join(out)


def _clean_style_block(css: str, scope: str, warn: Callable) -> str:
    css = re.sub(r"/\*.*?\*/", "", css or "", flags=re.S)
    kept, i, n = [], 0, len(css)
    while i < n:
        if css[i] == "@":
            brace, semi = css.find("{", i), css.find(";", i)
            if semi != -1 and (brace == -1 or semi < brace):
                warn("removed a CSS @-rule")
                i = semi + 1
                continue
            if brace == -1:
                break
            depth, j = 0, brace
            while j < n:
                if css[j] == "{":
                    depth += 1
                elif css[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            warn("removed a CSS @-rule")
            i = j + 1
            continue
        kept.append(css[i])
        i += 1

    def rule(m):
        sels = [s.strip() for s in m.group(1).split(",") if s.strip()]
        scoped = [s if s.startswith(scope) else f"{scope} {s}" for s in sels]
        return ",".join(scoped) + " { " + _clean_decls(m.group(2), warn) + " }\n"

    return re.sub(r"([^{}]+)\{([^{}]*)\}", rule, "".join(kept))


def _gradient_colors(raw: str) -> dict:
    """id -> first stop color of each SVG gradient, so fills that used a
    gradient get its flat color when the gradient is removed."""
    out = {}
    for m in re.finditer(r"<(linear|radial)gradient\b([^>]*)>([\s\S]*?)</\1gradient>", raw, re.I):
        idm = re.search(r"\bid\s*=\s*[\"']([^\"']+)", m.group(2))
        cm = re.search(r"stop-color\s*[:=]\s*[\"']?\s*([#\w(),.%\s]+?)\s*[\"';/>]", m.group(3))
        if idm:
            out[idm.group(1)] = cm.group(1).strip() if cm else "#2a3446"
    return out


class _Composer(HTMLParser):
    """Re-emits one slide's markup with only safe, on-style content. `hook`
    sees each kept element's tag and attribute dict and may rewrite it; it
    returns (attrs, replacement_text_or_None, drop_bool)."""

    def __init__(self, scope: str, hook: Callable, warn: Callable):
        super().__init__(convert_charrefs=True)
        self.scope, self.hook, self.warn = scope, hook, warn
        self.out: list = []
        self.skip = None        # [tag, depth]
        self.replace = None     # [tag, depth] while an element's text is replaced
        self.capture = None     # [tag, depth, parts, callback]
        self.style = None       # list collecting a <style> block
        self.svg = 0

    @staticmethod
    def _attr_text(attrs: dict) -> str:
        parts = []
        for k, v in attrs.items():
            if v is None:
                parts.append(f" {k}")
            else:
                parts.append(f' {k}="{_html.escape(str(v), quote=True)}"')
        return "".join(parts)

    def _clean_attrs(self, tag: str, attrs: list) -> dict:
        out = {}
        for k, v in attrs:
            k = (k or "").lower()
            if not k or k.startswith("on") or k in ("srcdoc", "formaction"):
                if k.startswith("on"):
                    self.warn("removed an event handler")
                continue
            lv = (v or "").strip().lower()
            if re.match(r"^(javascript|vbscript|data):", lv) or "javascript:" in lv:
                continue
            if k in _URL_ATTRS:
                if k in ("href", "xlink:href") and lv.startswith("#"):
                    out[k] = v
                continue
            if k == "style":
                v = _clean_decls(v or "", self.warn)
                if not v:
                    continue
            if k == "filter":
                self.warn("removed an SVG filter")
                continue
            if k in ("fill", "stroke") and "url(" in lv and not re.search(r"url\(\s*#", lv):
                continue
            out[k] = v
        return out

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, closed=False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, closed=True)

    def _start(self, tag, attrs, closed):
        if self.skip:
            if tag == self.skip[0] and not closed:
                self.skip[1] += 1
            return
        if self.replace:
            if tag == self.replace[0] and not closed:
                self.replace[1] += 1
            return
        if self.capture and tag == self.capture[0] and not closed:
            self.capture[1] += 1
        if tag in _SKIP or (tag in ("img", "image") and not any(k == "data-logo" for k, _ in attrs)):
            if tag in ("script", "iframe", "object"):
                self.warn(f"removed <{tag}>")
            if not closed and tag not in _HTML_VOID:
                self.skip = [tag, 1]
            return
        if tag in _VOID_DROP or tag in _UNWRAP:
            return
        if tag == "style":
            if not closed:
                self.style = []
            return
        clean = self._clean_attrs(tag, attrs)
        clean, text, drop = self.hook(tag, clean)
        if drop:
            if not closed and tag not in _HTML_VOID:
                self.skip = [tag, 1]
            return
        if tag == "svg":
            self.svg += 0 if closed else 1
        self.out.append(f"<{tag}{self._attr_text(clean)}")
        if closed:
            if self.svg or tag == "svg" or tag in _SVG_SHAPES:
                self.out.append("/>")
            elif tag in _HTML_VOID:
                self.out.append(">")
            else:
                self.out.append(f"></{tag}>")
            return
        self.out.append(">")
        if tag in _HTML_VOID:
            return
        if text is not None:
            self.out.append(_html.escape(text, quote=False))
            self.replace = [tag, 1]
        elif "data-ph" in clean:
            self.capture = [tag, 1, [], clean.get("data-ph")]

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[0]:
                self.skip[1] -= 1
                if self.skip[1] <= 0:
                    self.skip = None
            return
        if tag == "style" and self.style is not None:
            self.out.append(f"<style>{_clean_style_block(''.join(self.style), self.scope, self.warn)}</style>")
            self.style = None
            return
        if self.replace:
            if tag == self.replace[0]:
                self.replace[1] -= 1
                if self.replace[1] > 0:
                    return
                self.replace = None
            else:
                return
        if tag in _VOID_DROP or tag in _UNWRAP or tag in _HTML_VOID or tag in _SKIP:
            return
        if self.capture and tag == self.capture[0]:
            self.capture[1] -= 1
            if self.capture[1] <= 0:
                self.hook("#ph-text", {"key": self.capture[3], "text": "".join(self.capture[2]).strip()})
                self.capture = None
        if tag == "svg" and self.svg:
            self.svg -= 1
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self.skip or self.replace:
            return
        if self.style is not None:
            self.style.append(data)
            return
        if self.capture:
            self.capture[2].append(data)
        self.out.append(_html.escape(data, quote=False))

    def result(self) -> str:
        self.close()
        return "".join(self.out)


def _first_tag_attrs(tag_text: str) -> dict:
    found = {}

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if not found:
                found.update({k.lower(): (v if v is not None else "") for k, v in attrs})
                found.setdefault("__tag", tag)

    P().feed(tag_text)
    return found


_SECTION_RE = re.compile(r"<section\b([^>]*)>([\s\S]*?)</section\s*>", re.I)


def split_sections(raw: str) -> list:
    """[{id, attrs, inner, raw}] for each top-level <section> in order."""
    out, seen = [], set()
    for m in _SECTION_RE.finditer(raw or ""):
        attrs = _first_tag_attrs(f"<section{m.group(1)}>")
        sid = re.sub(r"[^A-Za-z0-9_-]", "", attrs.get("id") or "") or f"s{len(out) + 1:02d}"
        while sid in seen:
            sid += "x"
        seen.add(sid)
        out.append({"id": sid, "attrs": attrs, "inner": m.group(2), "raw": m.group(0)})
    return out


def join_sections(sections: list) -> str:
    return "\n\n".join(s["raw"].strip() for s in sections) + "\n"


def merge_sections(current: list, returned: list) -> "tuple[list, list]":
    """Apply a revision: same id replaces in place, data-delete removes, a new
    id goes after its base slide (s07b after s07) or after the previous
    returned section. Returns (sections, changed ids)."""
    out = [dict(s) for s in current]
    ids = [s["id"] for s in out]
    changed, prev = [], None
    for s in returned:
        sid = s["id"]
        if "data-delete" in s["attrs"]:
            if sid in ids:
                k = ids.index(sid)
                out.pop(k)
                ids.pop(k)
                changed.append(sid)
            continue
        if sid in ids:
            out[ids.index(sid)] = s
        else:
            base = re.match(r"^(s\d+)", sid)
            anchor = prev if prev in ids else (base.group(1) if base and base.group(1) in ids else None)
            k = ids.index(anchor) + 1 if anchor else len(out)
            out.insert(k, s)
            ids.insert(k, sid)
        changed.append(sid)
        prev = sid
    return out, changed


def _parse_cam(spec: str) -> list:
    keys = []
    for part in (spec or "").split(";"):
        if ":" not in part:
            continue
        phrase, nums = part.rsplit(":", 1)
        vals = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", nums)]
        if len(vals) >= 2:
            keys.append((phrase.strip(), vals[0], vals[1], vals[2] if len(vals) > 2 else 1.0))
    return keys


def compile_composition(raw: str, timeline: Timeline, *, duration: float, plan: dict,
                        logos: dict, values: dict, logo_choices: dict,
                        span: Optional[tuple] = None, host_on: bool = False,
                        host_sections: Optional[list] = None) -> dict:
    """Resolve every cue phrase to a time, sanitize every slide, and swap in
    logos and confirmed values. Returns the slide markup for the page plus
    per-slide metadata, warnings and the placeholders in use. With `span`
    (a test clip) the slides cover only that stretch of the narration; with
    `host_on`, data-host slides and the user's presenter `host_sections` get
    presenter windows."""
    plan = plan or {}
    sections = split_sections(raw)
    total = round(duration + TAIL, 3)
    first, last = (float(span[0]), float(span[1])) if span else (0.0, total)
    plan_slides = {s.get("id"): s for s in plan.get("slides") or []}
    sec_labels = {s.get("key"): s.get("label") for s in plan.get("sections") or []}
    plan_logos = {logo_key(s.get("key")): s.get("name") for s in plan.get("logos") or []}
    insert_keys = {ph_key(s.get("key")) for s in plan.get("inserts") or []}
    warnings: list = []

    # 1. Slide start times, searched in order.
    starts, floor = [], first
    for k, s in enumerate(sections):
        phrase = s["attrs"].get("data-at") or (plan_slides.get(s["id"]) or {}).get("at") or ""
        hit = timeline.find(phrase, floor=floor, limit=floor + 240) if phrase else None
        if hit is None and phrase:
            hit = timeline.find(phrase, floor=first)
        if hit is None:
            starts.append(None)
            if k:
                warnings.append({"slide": s["id"], "msg": f"start words not found in the narration: “{phrase[:60]}”"})
            continue
        if hit[2] == "approx":
            warnings.append({"slide": s["id"], "msg": f"start words matched loosely: “{phrase[:60]}”", "minor": True})
        starts.append(hit[0])
        floor = hit[0] + 0.01
    t0s, prev = [], -MIN_SLIDE
    for k, st in enumerate(starts):
        if k == 0:
            t = first
        elif st is None:
            nxt = next((x for x in starts[k + 1:] if x is not None), None)
            t = prev + (min(4.0, max(MIN_SLIDE, (nxt - LEAD - prev) / 2)) if nxt else 4.0)
        else:
            t = st - LEAD
        t = max(t, prev + MIN_SLIDE) if k else first
        t0s.append(round(min(t, last - MIN_SLIDE * 0.5), 3))
        prev = t0s[-1]

    # 2. Sections in order of first appearance give the HUD tracker.
    order: list = []
    for s in sections:
        key = s["attrs"].get("data-section") or (plan_slides.get(s["id"]) or {}).get("section") or ""
        if key and key not in order:
            order.append(key)

    used_logos: dict = {}
    used_ph: dict = {}
    slides_meta, out_html = [], []
    windows: list = []
    for k, s in enumerate(sections):
        sid, t0 = s["id"], t0s[k]
        t1 = t0s[k + 1] if k + 1 < len(sections) else last
        a = s["attrs"]
        kind = (a.get("data-kind") or (plan_slides.get(sid) or {}).get("kind") or "slide").lower()
        if kind not in ("slide", "scene", "chapter", "asset"):
            kind = "slide"
        host = (a.get("data-host") or "").strip().lower() if host_on else ""
        host = host if host in HOST_LAYOUTS else ""
        skey = a.get("data-section") or (plan_slides.get(sid) or {}).get("section") or ""
        label = sec_labels.get(skey) or skey
        slide_warn: list = []

        def warn(msg, minor=False, _w=slide_warn):
            if not any(x["msg"] == msg for x in _w):
                _w.append({"slide": sid, "msg": msg, "minor": minor})

        def cue(spec, what):
            spec = (spec or "").strip()
            if not spec:
                return None
            if spec.startswith("+") and _NUM_RE.match(spec):
                return round(min(t0 + float(spec), t1), 3)
            if spec.lower() == "start":
                return t0
            hit = timeline.find(spec, floor=max(0.0, t0 - CUE_FLOOR), limit=t1 + 4.0)
            if hit is None:
                warn(f"{what} words not found in this slide's narration: “{spec[:50]}”")
                return round(t0 + 0.3, 3)
            if hit[2] == "approx":
                warn(f"{what} words matched loosely: “{spec[:50]}”", minor=True)
            t = hit[0]
            if t > t1 - 0.25:
                warn(f"{what} “{spec[:40]}” comes after the slide ends ({fmt_secs(t)} vs {fmt_secs(t1)})")
            return round(t, 3)

        def hook(tag, attrs, _sid=sid):
            if tag == "#ph-text":
                key = attrs["key"]
                if key in used_ph and not used_ph[key].get("default"):
                    used_ph[key]["default"] = attrs["text"]
                return attrs, None, False
            text = None
            if "data-at" in attrs:
                t = cue(attrs.get("data-at"), "cue")
                if t is not None:
                    attrs["data-t"] = f"{t:.3f}"
            if "data-out-at" in attrs:
                t = cue(attrs.get("data-out-at"), "exit")
                if t is not None:
                    attrs["data-tout"] = f"{t:.3f}"
            if "data-cam" in attrs:
                keys = []
                for phrase, x, y, z in _parse_cam(attrs.get("data-cam")):
                    t = t0 if phrase.lower() in ("start", "") else cue(phrase, "camera")
                    keys.append(f"{t:.3f},{x:g},{y:g},{z:g}")
                attrs["data-camt"] = ";".join(keys)
            if "data-anim" in attrs:
                bad = [x for x in (attrs.get("data-anim") or "").split() if x not in ANIMS]
                if bad:
                    warn(f"unknown animation {', '.join(bad)}", minor=True)
            if "data-loop" in attrs and (attrs.get("data-loop") or "") not in LOOPS:
                warn(f"unknown loop {attrs.get('data-loop')}", minor=True)
            logo = logo_key(attrs.get("data-logo"))
            if logo and tag in ("img", "image"):
                attrs["data-logo"] = logo
                info = logos.get(logo)
                name = (info or {}).get("name") or plan_logos.get(logo) or attrs.get("alt") or logo.title()
                rec = used_logos.setdefault(logo, {"name": name, "slides": [], "has_file": bool(info and info.get("path"))})
                if _sid not in rec["slides"]:
                    rec["slides"].append(_sid)
                if info and info.get("path") and Path(info["path"]).is_file():
                    uri = data_uri(Path(info["path"]))
                    if info.get("svg") and info.get("recolor") == "white":
                        attrs["style"] = ("filter: brightness(0) invert(0.94); " + attrs.get("style", "")).strip()
                else:
                    uri = badge_uri(name, final=logo_choices.get(logo) == "badge")
                    attrs["data-logo-missing"] = logo
                if tag == "img":
                    attrs["src"] = uri
                    if "logo" not in attrs.get("class", "").split():
                        attrs["class"] = (attrs.get("class", "") + " logo").strip()
                    attrs.setdefault("alt", name)
                else:
                    attrs["href"] = uri
                    attrs.setdefault("preserveAspectRatio", "xMidYMid meet")
            needs = [ph_key(n) for n in (attrs.get("data-needs") or "").split()]
            if needs and any((values.get(n) or {}).get("status") == "dropped" for n in needs):
                attrs["style"] = ("display: none; " + attrs.get("style", "")).strip()
            key = ph_key(attrs.get("data-ph"))
            if key:
                attrs["data-ph"] = key
                rec = used_ph.setdefault(key, {"slides": [], "default": "", "insert": key in insert_keys})
                if _sid not in rec["slides"]:
                    rec["slides"].append(_sid)
                v = values.get(key) or {}
                if v.get("status") in ("confirmed", "edited", "filled") and (v.get("value") or "").strip():
                    text = v["value"].strip()
                    if "count" in (attrs.get("data-anim") or "").split():
                        num = re.search(r"-?\d[\d,]*(?:\.\d+)?", text)
                        if num:
                            n = num.group(0).replace(",", "")
                            attrs["data-to"] = n
                            attrs.setdefault("data-decimals", str(len(n.split(".")[1]) if "." in n else 0))
                            attrs["data-prefix"] = text[:num.start()]
                            attrs["data-suffix"] = text[num.end():]
                elif v.get("status") == "dropped":
                    text = ""
                else:
                    attrs["class"] = (attrs.get("class", "") + " ph-pending").strip()
            return attrs, text, False

        inner = s["inner"]
        for gid, color in _gradient_colors(inner).items():
            inner = re.sub(r"url\(\s*['\"]?#" + re.escape(gid) + r"['\"]?\s*\)", color, inner)
        comp = _Composer(f"#{sid}", hook, warn)
        comp.feed(inner)
        body = comp.result()
        if t1 - t0 > LONG_SLIDE + 3:
            warn(f"long slide ({t1 - t0:.0f} s): consider splitting it", minor=True)
        if host and kind == "scene":
            warn("an illustrated scene hides the presenter behind it: use a slide, or drop data-host")
        if host and "data-cam" in inner:
            warn("camera moves on a presenter slide drift over the presenter", minor=True)
        sec_idx = order.index(skey) if skey in order else -1
        hud = "off" if (a.get("data-hud") == "off" or kind == "chapter") else "on"
        trans = a.get("data-transition") if a.get("data-transition") in ("push", "fade", "cut") else "push"
        extra = " ".join(c for c in (a.get("class") or "").split() if re.fullmatch(r"[A-Za-z0-9_-]+", c) and c != "slide")
        tracker = (a.get("data-tracker") or "")[:60]
        out_html.append(
            f'<section class="slide kind-{kind}{(" " + extra) if extra else ""}" id="{_html.escape(sid)}" '
            f'data-kind="{kind}" data-t0="{t0:.3f}" data-t1="{t1:.3f}" data-sidx="{sec_idx}" '
            f'data-slabel="{_html.escape(label or "", quote=True)}" data-hud="{hud}" '
            f'data-transition="{trans}" data-tracker="{_html.escape(tracker, quote=True)}"'
            + (f' data-host="{host}"' if host else "") + f">{body}</section>")
        if host:
            # The presenter shows from the slide start until its exit transition ends.
            cut = k + 1 >= len(sections) or sections[k + 1]["attrs"].get("data-transition") == "cut"
            end = t1 + (0.0 if cut else 0.45)
            if windows and windows[-1]["layout"] == host and windows[-1]["t1"] >= t0 - 0.01:
                windows[-1]["t1"] = round(max(windows[-1]["t1"], end), 3)
            else:
                windows.append({"t0": round(max(first, t0 - 0.05), 3), "t1": round(end, 3), "layout": host})
        idea = (plan_slides.get(sid) or {}).get("idea") or ""
        if not idea:
            idea = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()[:140]
        slides_meta.append({"id": sid, "t0": t0, "t1": t1, "kind": kind, "section": label or "",
                            "idea": idea, "at": a.get("data-at") or "", "host": host, "warnings": slide_warn,
                            "spoken": timeline.window_text(t0, t1)[:500],
                            "demo": (a.get("data-demo") or "")[:180]})
        warnings.extend(slide_warn)
    # The user's presenter sections, inside this video's stretch. They win
    # over a slide's own presenter layout: the slide's window keeps only the
    # cross-fades at the section's edges.
    placed = []
    for x in (host_sections or []) if host_on else []:
        a0, a1 = max(first, x["t0"]), min(last, x["t1"])
        if a1 - a0 >= 0.3:
            placed.append({"t0": round(a0, 3), "t1": round(a1, 3), "layout": x["layout"]})
    for x in placed:
        c0, c1 = x["t0"] + HOST_SECTION_FADE, x["t1"] - HOST_SECTION_FADE
        if c1 - c0 > 0.05:
            cut = []
            for w in windows:
                if w["t1"] <= c0 or w["t0"] >= c1:
                    cut.append(w)
                    continue
                if w["t0"] < c0:
                    cut.append({**w, "t1": round(c0, 3)})
                if w["t1"] > c1:
                    cut.append({**w, "t0": round(c1, 3)})
            windows = cut
    windows += [dict(x) for x in placed]
    for m in slides_meta:
        m["sections"] = [x for x in placed if x["t0"] < m["t1"] and x["t1"] > m["t0"]]
    merged_w = []
    for w in sorted(windows, key=lambda w: w["t0"]):
        same = next((m for m in merged_w if m["layout"] == w["layout"] and w["t0"] <= m["t1"] + 0.01), None)
        if same:
            same["t1"] = max(same["t1"], w["t1"])
        else:
            merged_w.append(dict(w))
    windows = merged_w
    for w in warnings:
        if w.get("slide"):
            meta = next((m for m in slides_meta if m["id"] == w["slide"]), None)
            if meta is not None and w not in meta["warnings"]:
                meta["warnings"].append(w)
    for key, rec in used_ph.items():
        if not rec["insert"] and "[insert]" in (rec.get("default") or "").lower():
            rec["insert"] = True
    return {"html": "\n".join(out_html), "slides": slides_meta, "warnings": warnings,
            "logos": used_logos, "ph": used_ph, "duration": total, "start": first, "end": last,
            "host_on": bool(host_on), "host_windows": windows, "host_sections": placed,
            "sections": [sec_labels.get(k) or k for k in order]}


def page_html(compiled: dict, *, mode: str = "preview", title: str = "Explainer",
              host: Optional[dict] = None, pip_frame: Optional[str] = None,
              bubble: Optional[str] = None, clips: Optional[list] = None,
              media_origin: str = "", visual: Optional[dict] = None,
              demos: Optional[list] = None) -> str:
    """A self-contained page: design CSS, the compiled slides, the runtime.
    The runtime exposes __seek(t), __check() and __ready for the renderer;
    in preview mode it answers postMessage seeks from the dialog. With a
    presenter (`host`: focus, and in preview the proxy video's URL) the
    presenter areas are see-through; the preview plays the proxy under them.
    Corner windows carry their device frame, and guide-character cues carry
    a drawn bubble, both as local images. Assigned YouTube clips (`clips`)
    play in preview as each slide's picture; the renderer lays the same
    files on with ffmpeg, holding the last frame when the clip is shorter.
    `visual` picks classic or cinematic. Both keep the wave background.
    Cinematic adds the object entrance. The slide HTML is not changed."""
    css = (ASSET_DIR / "design.css").read_text(encoding="utf-8")
    js = (ASSET_DIR / "runtime.js").read_text(encoding="utf-8")
    host_on = bool(host) and compiled.get("host_on")
    video = (host or {}).get("video") if host_on and mode == "preview" else None
    frame_mode = pip_frame_key(pip_frame, None if pip_frame is not None else (host or {}).get("pip_frame"))
    windows = framed_windows(compiled.get("host_windows") or [], frame_mode) if host_on else []
    clip_cfg = [{k: c.get(k) for k in ("id", "slide", "src", "audio", "seconds", "t0", "t1", "label")}
                for c in (clips or [])]
    style = visual_style_key((visual or {}).get("style"))
    visual_cfg = page_visual(style, compiled.get("slides"))
    cfg = json.dumps({"duration": compiled["duration"], "fps": FPS, "mode": mode,
                      "start": compiled.get("start", 0.0), "end": compiled.get("end", compiled["duration"]),
                      "sections": compiled.get("sections") or [],
                      "asides": _aside_payloads(compiled.get("slides") or [], bubble),
                      "clips": clip_cfg, "visual": visual_cfg,
                      "demos": demos or [],
                      "host": {"on": True, "layouts": HOST_LAYOUTS, "focus": float(host.get("focus", HOST_FOCUS)),
                               "video": video, "sections": compiled.get("host_sections") or [],
                               "fade": HOST_SECTION_FADE, "windows": windows,
                               "frames": _frame_payloads(windows)} if host_on else {"on": False}}).replace("</", "<\\/")
    media = bool(video) or any(c.get("src") for c in clip_cfg)
    origin = media_origin if str(media_origin).startswith(("http://", "https://")) else ""
    csp = ("default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
           "script-src 'unsafe-inline'; font-src data:"
           + (("; media-src 'self'" + (f" {origin}" if origin else "")) if media else ""))
    cls = f"mode-{mode}" + (" host-on" if host_on else "")
    return (f"<!doctype html><html class=\"{cls}\"><head><meta charset=\"utf-8\">"
            f"<meta http-equiv=\"Content-Security-Policy\" content=\"{csp}\">"
            f"<title>{_html.escape(title)}</title><style>{css}</style></head>"
            f"<body class=\"{cls}\"><div id=\"viewport\"><div id=\"stage\">"
            "<canvas id=\"bg\" width=\"1920\" height=\"1080\"></canvas>"
            f"{scene_sprite(style)}"
            f"<div id=\"slides\">{compiled['html']}</div>"
            "<div id=\"hud\"><div id=\"progress-track\"></div><div id=\"progress\"></div>"
            "<div id=\"hud-left\"></div><div id=\"hud-right\"></div></div>"
            "</div></div>"
            f"<script>window.__EXPLAINER = {cfg};</script><script>{js}</script></body></html>")


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

def claude_call(client, blocks: list, *, max_tokens: int, schema: Optional[dict] = None,
                progress: Optional[Callable[[str], None]] = None,
                cancel: Optional[threading.Event] = None,
                on_start: Optional[Callable[[], None]] = None) -> dict:
    """One streamed Claude Opus 5.5 turn at high effort with adaptive thinking.
    Returns {"text", "usage", "stop_reason"}; raises on a refusal or cancel."""
    import anthropic
    output_config: dict = {"effort": EFFORT}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    base = dict(model=MODEL, max_tokens=max_tokens,
                system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": blocks}],
                thinking={"type": "adaptive"}, output_config=output_config)
    extra = dict(betas=[FALLBACK_BETA], extra_body={"fallbacks": "default"})
    waits = list(CLAUDE_RETRY_WAITS)
    while True:
        try:
            return _claude_stream(client, {**base, **extra}, progress, cancel, on_start)
        except anthropic.BadRequestError as e:
            if extra and "fallback" in str(e).lower():
                extra = {}
                continue
            raise
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as e:
            # Rate limits, overload (529) and dropped streams: wait and run the call again.
            if not waits or (cancel is not None and cancel.is_set()):
                raise
            wait = waits.pop(0)
            if progress:
                progress(f"__retry__ {type(e).__name__}; retrying in {wait}s")
            if cancel is not None and cancel.wait(wait):
                raise Cancelled()


def _claude_stream(client, kwargs: dict, progress, cancel, on_start) -> dict:
    parts, last = [], 0.0
    with client.beta.messages.stream(**kwargs) as stream:
        for event in stream:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            kind = getattr(event, "type", "")
            if kind == "message_start":
                # The prompt is read (and cached) by now; thinking comes next.
                if on_start:
                    on_start()
            elif kind == "content_block_delta" and getattr(event.delta, "type", "") == "text_delta":
                parts.append(event.delta.text)
                now = time.time()
                if progress and now - last > 1.5:
                    last = now
                    progress("".join(parts))
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        det = getattr(msg, "stop_details", None)
        raise RuntimeError("Claude declined this request" + (f": {getattr(det, 'explanation', '')}" if det else ""))
    text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
    u = msg.usage
    usage = {k: int(getattr(u, k, 0) or 0) for k in ("input_tokens", "output_tokens",
                                                       "cache_creation_input_tokens", "cache_read_input_tokens")}
    return {"text": text, "usage": usage, "stop_reason": msg.stop_reason}


def _context_blocks(project: "Project", timeline: Timeline) -> list:
    """Script + timed transcript + logo files (+ the presenter still): the
    cached prefix of every call."""
    logos = project.data.get("logos") or {}
    rows = [f"- {k}: {v.get('name')} ({v.get('kind', 'icon')}, aspect {v.get('aspect', 1)}:1)"
            for k, v in sorted(logos.items()) if v.get("path")]
    text = (
        "SCRIPT (as written, production notes included)\n<script>\n" + project.read("script.txt") + "\n</script>\n\n"
        f"TIMED TRANSCRIPT (what the narration says; [seconds] at each sentence start; total {fmt_secs(timeline.duration)})\n"
        "<transcript>\n" + timeline.transcript() + "\n</transcript>\n\n"
        "LOGO FILES THE USER HAS (data-logo key: brand, shape)\n" + ("\n".join(rows) or "- none yet") + "\n")
    blocks = []
    host = project.host()
    if host:
        text += ("\nPRESENTER VIDEO\nThe user's HeyGen presenter, lip-synced to this narration, is available for the "
                 "whole video as 16:9 footage (the still above is a frame of it). Mark the slides that show the "
                 "presenter with data-host, following the Presenter rules.\n")
        still = project.dir / "host" / "still.jpg"
        if still.is_file():
            blocks.append({"type": "text", "text": "Presenter footage, one frame:"})
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                       "data": base64.b64encode(still.read_bytes()).decode("ascii")}})
    blocks.append({"type": "text", "text": text, "cache_control": {"type": "ephemeral"}})
    return blocks


def _plan_block(project: "Project", extra: str = "") -> dict:
    notes = project.data.get("notes") or []
    answers = project.data.get("answers") or {}
    text = "THE PLAN (JSON)\n" + json.dumps(project.plan(), ensure_ascii=False, indent=1) + "\n"
    if notes:
        text += "\nUSER NOTES FOR THE WHOLE VIDEO (apply everywhere)\n" + "\n".join(f"- {n}" for n in notes) + "\n"
    if any(v.strip() for v in answers.values()):
        text += "\nUSER ANSWERS TO YOUR QUESTIONS\n" + "\n".join(f"- {q}: {a}" for q, a in answers.items() if a.strip()) + "\n"
    if extra:
        text += "\n" + extra
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}


def host_share_key(share: Optional[str] = None, saved: Optional[str] = None) -> str:
    """Which HOST_SHARES key to plan with.

    An explicit choice wins, then a share already saved on the project, then
    HOST_DEFAULT_SHARE (about 10% of runtime). An unknown value is not a choice.
    """
    if share in HOST_SHARES:
        return share
    if saved in HOST_SHARES:
        return saved
    return HOST_DEFAULT_SHARE


def host_share_pct(share: Optional[str] = None, saved: Optional[str] = None) -> int:
    """Target presenter screen time, as a percent of runtime."""
    return HOST_SHARES[host_share_key(share, saved)]


def pip_frame_key(choice: Optional[str] = None, saved: Optional[str] = None) -> str:
    """Which corner-frame mode to draw with.

    An explicit choice wins, then a mode already saved on the project, then
    PIP_FRAME_DEFAULT (about half of the corner windows, cycling devices).
    An unknown value is not a choice.
    """
    if choice in PIP_FRAME_MODES:
        return choice
    if saved in PIP_FRAME_MODES:
        return saved
    return PIP_FRAME_DEFAULT


def bubble_mode_key(choice: Optional[str] = None, saved: Optional[str] = None) -> str:
    """Which guide-character mode to draw with. Same precedence as pip_frame_key."""
    if choice in BUBBLE_MODES:
        return choice
    if saved in BUBBLE_MODES:
        return saved
    return BUBBLE_DEFAULT


def look_of(data: Optional[dict], host: Optional[dict] = None) -> "tuple[str, str]":
    """(corner-frame mode, guide mode) saved on a project, with the defaults filled in."""
    data, host = data or {}, host or {}
    return (pip_frame_key(None, host.get("pip_frame") or data.get("pip_frame")),
            bubble_mode_key(None, data.get("bubble")))


def pip_device_for(mode: str, index: int) -> str:
    """The device for the `index`th corner window (0-based), or "" for a plain corner.

    "mix" frames the 1st, 3rd, 5th… window — about half — and cycles monitor,
    laptop, phone, TV. A device name frames every window. "off" frames none.
    """
    mode = pip_frame_key(mode)
    if mode == "off":
        return ""
    if mode in PIP_DEVICES:
        return mode
    if index % 2 == 1:
        return ""
    return PIP_DEVICES[(index // 2) % len(PIP_DEVICES)]


def framed_windows(windows: list, mode: Optional[str] = None) -> list:
    """Copy presenter windows, tagging each corner window with its device (or "")."""
    out, i = [], 0
    for w in windows or []:
        w = dict(w)
        if w.get("layout") == "pip":
            w["frame"] = pip_device_for(mode or PIP_FRAME_DEFAULT, i)
            i += 1
        else:
            w["frame"] = ""
        out.append(w)
    return out


_BUBBLE_FILLER = re.compile(r"^(?:and|but|so|well|now|then|okay|ok|yeah|right)\b[, ]*", re.I)


def bubble_text(spoken: str, idea: str = "") -> str:
    """A short bubble line from the narration, or from the slide idea if the
    narration has nothing readable. The words are the source's own words."""
    for src in (spoken, idea):
        line = _bubble_clip(src)
        if line:
            return line
    return ""


def _bubble_clip(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip(" \"'`")
    sentence = _BUBBLE_FILLER.sub("", sentence).strip()
    sentence = sentence.rstrip(".!?…").strip(" \"'`")
    if len(sentence) <= BUBBLE_MAX and len(sentence) >= 12:
        return sentence
    if len(sentence) < 12:
        return ""
    cut = sentence[:BUBBLE_MAX - 1].rsplit(" ", 1)[0].rstrip(",;:")
    if len(cut) < 12:
        return ""
    return cut + "…"


def aside_cues(slides: list, mode: Optional[str] = None) -> list:
    """Where the guide character shows: a few seconds on a slide that has room.

    Skips chapter cards, the asset slide, short slides, and any slide whose
    presenter is full frame or a side panel (those cover the lower left, or
    the whole frame). "some" keeps about one in three of the slides that
    qualify, including the first. "often" keeps all of them. "off" keeps none.
    """
    mode = bubble_mode_key(mode)
    if mode == "off":
        return []
    eligible = []
    for s in slides or []:
        if s.get("kind") not in ("slide", "scene"):
            continue
        if s.get("host") in ("full", "left", "right"):
            continue
        if any(x.get("layout") in ("full", "left", "right") for x in s.get("sections") or []):
            continue
        if float(s.get("t1") or 0) - float(s.get("t0") or 0) < 6.5:
            continue
        text = bubble_text(s.get("spoken") or "", s.get("idea") or "")
        if not text:
            continue
        eligible.append((s, text))
    step = 1 if mode == "often" else 3
    cues = []
    for i, (s, text) in enumerate(eligible):
        if i % step:
            continue
        t0 = round(float(s["t0"]) + 1.0, 3)
        t1 = round(min(float(s["t1"]) - 0.35, t0 + 3.4), 3)
        if t1 - t0 < 2.0:
            continue
        cues.append({"t0": t0, "t1": t1, "text": text, "slide": s.get("id") or ""})
    return cues


def _font(size: int, bold: bool = False):
    """Inter when the machine has it, otherwise another installed sans."""
    from PIL import ImageFont
    names = ("Inter-Bold.ttf", "Inter-SemiBold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf") if bold \
        else ("Inter-Medium.ttf", "Inter-Regular.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf")
    roots = (Path("/usr/share/fonts/truetype/macos"), Path("/usr/share/fonts/truetype/dejavu"),
             Path("/usr/share/fonts/truetype/liberation"), Path("/usr/share/fonts/truetype/liberation2"))
    for root in roots:
        for name in names:
            p = root / name
            if p.is_file():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def _punch_round(im, box: "tuple[int, int, int, int]", radius: int):
    """Clear a rounded rectangle (box is x0, y0, x1, y1) out of an RGBA image."""
    from PIL import Image, ImageChops, ImageDraw
    mask = Image.new("L", im.size, 255)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=0)
    r, g, b, a = im.split()
    return Image.merge("RGBA", (r, g, b, ImageChops.multiply(a, mask)))


def _soft_shadow(size, box, radius: int, blur: int = 7, alpha: int = 120, dx: int = 0, dy: int = 8):
    """A blurred contact shadow. Drawn once per device, then cached with the PNG."""
    from PIL import Image, ImageDraw, ImageFilter
    x0, y0, x1, y1 = box
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((x0 + dx, y0 + dy, x1 + dx, y1 + dy), radius=radius, fill=(0, 0, 0, alpha))
    return layer.filter(ImageFilter.GaussianBlur(blur))


def _glass_sheen(im, screen, radius: int):
    """A short reflection across the top of the screen. The middle stays clear
    so the presenter footage is not fogged."""
    from PIL import Image, ImageChops, ImageDraw
    x0, y0, x1, y1 = screen
    h = max(1, y1 - y0)
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for start, end, alpha in ((0.0, 0.07, 58), (0.07, 0.14, 30), (0.14, 0.22, 12)):
        d.rectangle((x0, y0 + int(h * start), x1, y0 + int(h * end)), fill=(236, 244, 255, alpha))
    streak = x0 + int((x1 - x0) * 0.34)
    d.polygon([(x0 + 16, y0 + 8), (streak, y0 + 6), (streak - 18, y0 + 20), (x0 + 10, y0 + 22)],
              fill=(255, 255, 255, 46))
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(screen, radius=radius, fill=255)
    r, g, b, a = overlay.split()
    return Image.alpha_composite(im, Image.merge("RGBA", (r, g, b, ImageChops.multiply(a, mask))))


def _local_box(outer, box) -> "tuple[int, int, int, int]":
    ox, oy = outer[0], outer[1]
    x, y, w, h = box
    return (x - ox, y - oy, x - ox + w, y - oy + h)


def device_png(name: str) -> bytes:
    """The device frame for a corner window.

    Light comes from the upper left. A lid, a phone and a TV are a thin panel:
    the side wall is only PANEL_EDGE pixels. The laptop's thickness is the
    keyboard base, and a monitor's is the neck and the foot. The screen stays
    an axis-aligned rounded rectangle so the presenter footage sits in that
    hole. The middle of the screen is fully clear.
    """
    cache = device_png.__dict__.setdefault("cache", {})
    if name in cache:
        return cache[name]
    from PIL import Image, ImageDraw
    import io as _io
    g = PIP_FRAME_GEOM[name]
    _, _, ow, oh = g["outer"]
    screen = _local_box(g["outer"], g["screen"])
    navy, deep, side, top = (12, 21, 38, 255), (5, 8, 16, 255), (8, 13, 24, 255), (62, 80, 110, 255)
    gold, gold_lit, gold_dim = (245, 184, 61, 255), (255, 220, 140, 255), (150, 96, 24, 255)
    rim = (150, 168, 196, 255)
    im = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))
    sx0, sy0, sx1, sy1 = screen
    e = PANEL_EDGE

    def chassis(front, radius):
        """Thin panel: lit top and left, a PANEL_EDGE wall on the right."""
        x0, y0, x1, y1 = front
        d.polygon([(x1 + 1, y0 + 2), (x1 + e, y0), (x1 + e, y1 - 1), (x1 + 1, y1)], fill=side)
        d.polygon([(x1 + 1, y0 + 2), (x1 + e, y0), (x1 + e, y0 + 2), (x1 + 1, y0 + 3)], fill=top)
        d.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=navy)
        d.rectangle((x0 + 10, y0, x1 - 8, y0 + 2), fill=top)
        d.line((x0 + 2, y0 + 4, x0 + 2, y1 - 6), fill=rim, width=2)

    if name == "monitor":
        front = (48, 6, 496, 268)
        im = Image.alpha_composite(im, _soft_shadow((ow, oh), (ow // 2 - 100, 286, ow // 2 + 90, 302), 8, blur=6, alpha=110, dx=6, dy=6))
        d = ImageDraw.Draw(im)
        cx = ow // 2
        # The foot is the thick part: a lit top plane and a dark front face.
        d.polygon([(cx - 96, 292), (cx + 70, 286), (cx + 86, 300), (cx - 84, 304)], fill=(32, 44, 64, 255))
        d.line((cx - 90, 294, cx + 64, 288), fill=top, width=2)
        d.polygon([(cx - 78, 300), (cx + 88, 296), (cx + 96, oh - 1), (cx - 70, oh - 1)], fill=deep)
        # Neck, with its own narrow side, under the thin panel.
        d.polygon([(cx + 8, 270), (cx + 16, 266), (cx + 18, 296), (cx + 8, 300)], fill=side)
        d.polygon([(cx - 22, 268), (cx + 8, 266), (cx + 8, 300), (cx - 22, 302)], fill=(34, 46, 68, 255))
        chassis(front, 12)
        d.rectangle((cx - 16, 262, cx + 4, 265), fill=gold_dim)
        d.rectangle((cx - 16, 260, cx + 4, 263), fill=gold)
        d.rounded_rectangle((sx0 - 3, sy0 - 2, sx1 + 3, sy1 + 3), radius=g["radius"] + 2, fill=deep)
        d.line((sx0, sy0 - 1, sx1, sy0 - 1), fill=rim, width=1)
    elif name == "laptop":
        im = Image.alpha_composite(im, _soft_shadow((ow, oh), (16, 286, 528, 304), 6, blur=5, alpha=120, dx=6, dy=4))
        d = ImageDraw.Draw(im)
        # The base is the thick part. Its top plane recedes; the near face is LAPTOP_BASE tall.
        d.polygon([(18, 288), (526, 280), (534, 304), (10, 304)], fill=deep)
        d.polygon([(36, 254), (492, 250), (520, 286), (22, 292)], fill=(22, 32, 48, 255))
        d.line((42, 256, 486, 252), fill=top, width=2)
        for row in range(3):
            for col in range(12):
                x, y = 54 + col * 36, 258 + row * 9
                d.rectangle((x, y + 4, x + 28, y + 7), fill=side)
                d.rectangle((x, y, x + 28, y + 4), fill=(52, 66, 90, 255))
        d.polygon([(214, 276), (330, 274), (334, 286), (210, 288)], fill=deep)
        d.line((218, 277, 326, 275), fill=top, width=1)
        # Lid: a thin panel, only PANEL_EDGE of side wall. No thick extrusion.
        chassis((64, 10, 480, 246), 8)
        d.rectangle((ow // 2 - 22, 246, ow // 2 + 22, 250), fill=(28, 38, 54, 255))
        d.rounded_rectangle((sx0 - 3, sy0 - 2, sx1 + 3, sy1 + 3), radius=g["radius"] + 2, fill=deep)
        d.line((sx0, sy0 - 1, sx1, sy0 - 1), fill=rim, width=1)
    elif name == "phone":
        front = (10, 16, 504, 288)
        im = Image.alpha_composite(im, _soft_shadow((ow, oh), front, 30, blur=6, alpha=110, dx=6, dy=8))
        d = ImageDraw.Draw(im)
        chassis(front, 34)
        # A slim side button, a couple of pixels proud of the body.
        d.rounded_rectangle((6, oh // 2 - 6, 12, oh // 2 + 28), radius=2, fill=gold_dim)
        d.rounded_rectangle((6, oh // 2 - 16, 12, oh // 2 + 16), radius=2, fill=gold)
        d.line((8, oh // 2 - 12, 8, oh // 2 + 10), fill=gold_lit, width=1)
        # Camera island on the left bezel, only a few pixels proud of the glass.
        d.rounded_rectangle((18, oh // 2 - 22, 36, oh // 2 + 28), radius=6, fill=deep)
        d.rounded_rectangle((18, oh // 2 - 26, 34, oh // 2 + 22), radius=6, fill=(24, 32, 48, 255))
        d.ellipse((21, oh // 2 - 16, 31, oh // 2 - 6), fill=(4, 6, 12, 255))
        d.ellipse((23, oh // 2 - 14, 27, oh // 2 - 10), fill=(180, 200, 230, 180))
        d.rounded_rectangle((sx0 - 3, sy0 - 2, sx1 + 3, sy1 + 3), radius=g["radius"] + 2, fill=deep)
        d.line((sx0 + 6, sy0 - 1, sx1 - 6, sy0 - 1), fill=rim, width=1)
    else:
        front = (20, 8, 520, 284)
        im = Image.alpha_composite(im, _soft_shadow((ow, oh), (140, 286, 400, 304), 4, blur=4, alpha=100, dx=6, dy=4))
        d = ImageDraw.Draw(im)
        for cx in (150, 330):
            d.polygon([(cx - 8, 298), (cx + 52, 296), (cx + 58, 305), (cx, 305)], fill=deep)
            d.polygon([(cx - 36, 286), (cx + 28, 282), (cx + 48, 298), (cx - 16, 302)], fill=(78, 98, 128, 255))
            d.line((cx - 30, 288, cx + 24, 284), fill=top, width=2)
        chassis(front, 6)
        d.rounded_rectangle((sx0 - 2, sy0 - 1, sx1 + 2, sy1 + 2), radius=g["radius"] + 2, fill=deep)
        d.line((sx0, sy0 - 1, sx1, sy0 - 1), fill=rim, width=1)
        d.ellipse((514, 148, 520, 154), fill=gold_dim)
        d.ellipse((514, 146, 520, 152), fill=gold)
    im = _punch_round(im, screen, g["radius"])
    im = _glass_sheen(im, screen, g["radius"])
    buf = _io.BytesIO()
    im.save(buf, "PNG")
    cache[name] = buf.getvalue()
    return cache[name]


def bubble_png(text: str) -> "tuple[bytes, int, int]":
    """The guide character and a speech bubble, with a shaded face and a
    contact shadow. Returns PNG bytes and its size. The words stay on the
    light face of the bubble."""
    from PIL import Image, ImageDraw, ImageFilter
    import io as _io
    w, h = ASIDE_SIZE
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse((24, 150, 108, 172), fill=(0, 0, 0, 90))
    sd.rounded_rectangle((136, 28, w - 2, h - 4), radius=20, fill=(0, 0, 0, 80))
    im = Image.alpha_composite(im, shadow.filter(ImageFilter.GaussianBlur(4)))
    d = ImageDraw.Draw(im)
    navy, navy_lit, gold, gold_lit, gold_dim = (12, 21, 38, 255), (36, 52, 78, 255), (245, 184, 61, 255), (255, 224, 150, 255), (176, 112, 28, 255)
    ink, paper, paper_shade = (12, 21, 38, 255), (242, 244, 248, 255), (214, 220, 230, 255)
    # Body, darker on the right where it turns away from the light.
    d.rounded_rectangle((34, 90, 102, 166), radius=28, fill=gold_dim)
    d.rounded_rectangle((30, 84, 94, 160), radius=28, fill=navy)
    d.rounded_rectangle((32, 86, 70, 156), radius=22, fill=navy_lit)
    # Head: a lit cap over a warmer underside.
    d.ellipse((28, 26, 100, 98), fill=gold_dim)
    d.ellipse((26, 18, 98, 90), fill=gold)
    d.ellipse((32, 20, 78, 58), fill=gold_lit)
    d.ellipse((48, 48, 58, 58), fill=navy)
    d.ellipse((70, 48, 80, 58), fill=navy)
    d.ellipse((50, 49, 55, 54), fill=paper)
    d.arc((50, 56, 78, 80), 20, 160, fill=navy, width=3)
    d.rounded_rectangle((10, 112, 36, 132), radius=8, fill=gold_dim)
    d.rounded_rectangle((8, 106, 32, 124), radius=8, fill=gold)
    # Bubble: a thicker underside, then the paper face, then a top highlight.
    d.polygon([(132, 84), (108, 102), (132, 120)], fill=(150, 158, 172, 255))
    d.rounded_rectangle((126, 22, w - 6, h - 8), radius=20, fill=(176, 184, 196, 255))
    d.polygon([(130, 78), (110, 94), (130, 110)], fill=paper)
    d.rounded_rectangle((124, 16, w - 12, h - 16), radius=18, fill=paper)
    d.rounded_rectangle((136, 22, w - 24, 34), radius=6, fill=(255, 255, 255, 255))
    d.polygon([(128, 24), (168, 20), (160, 32), (126, 34)], fill=paper_shade)
    font = _font(22, bold=True)
    lines = _bubble_lines(text, font, w - 128 - 40)
    gap, block = 28, 28 * len(lines)
    y = 28 + max(6, ((h - 52) - block) // 2)
    for line in lines:
        d.text((148, y), line, font=font, fill=ink)
        y += gap
    buf = _io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue(), w, h


def _bubble_lines(text: str, font, width: int) -> list:
    def width_of(s: str) -> float:
        return font.getlength(s) if hasattr(font, "getlength") else len(s) * 12
    words = (text or "").split()
    if not words:
        return []
    lines, cur = [], ""
    overflow = False
    for word in words:
        trial = (cur + " " + word).strip()
        if not cur or width_of(trial) <= width:
            cur = trial
            continue
        lines.append(cur)
        cur = word
        if len(lines) == 2:
            overflow = True
            break
    if len(lines) < 2 and cur:
        lines.append(cur)
    if overflow and len(lines) == 2:
        last = lines[1]
        while last and width_of(last + "…") > width:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lines[1] = (last or lines[1][:1]).rstrip(",;:") + "…"
    return lines[:2]


def _aside_payloads(slides: list, mode: Optional[str]) -> list:
    """Cues plus the drawn graphic, for the page config."""
    out = []
    for cue in aside_cues(slides, mode):
        png, w, h = bubble_png(cue["text"])
        out.append({**cue, "x": ASIDE_AT[0], "y": ASIDE_AT[1], "w": w, "h": h,
                    "uri": "data:image/png;base64," + base64.b64encode(png).decode()})
    return out


def _frame_payloads(windows: list) -> dict:
    """Device graphics the page shows around corner windows that use one."""
    used = [w["frame"] for w in windows if w.get("frame")]
    out = {}
    for name in PIP_DEVICES:
        if name not in used:
            continue
        g = PIP_FRAME_GEOM[name]
        ox, oy, ow, oh = g["outer"]
        sx, sy, sw, sh = g["screen"]
        out[name] = {"x": ox, "y": oy, "w": ow, "h": oh, "sx": sx, "sy": sy, "sw": sw, "sh": sh,
                     "sr": g["radius"], "uri": "data:image/png;base64," + base64.b64encode(device_png(name)).decode()}
    return out


def _stand_in(w: int, h: int):
    """A drawn stand-in for the presenter, for sample stills. Not footage."""
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (w, h), (19, 33, 58, 255))
    d = ImageDraw.Draw(im)
    cx, rad = w // 2, int(min(w, h) * 0.18)
    cy = int(h * 0.42)
    d.rounded_rectangle((cx - int(w * 0.30), int(h * 0.70), cx + int(w * 0.30), h + 30), radius=rad, fill=(26, 34, 50, 255))
    d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=(245, 184, 61, 255))
    d.ellipse((cx - rad // 3, cy - rad // 5, cx - rad // 8, cy + rad // 8), fill=(12, 21, 38, 255))
    d.ellipse((cx + rad // 8, cy - rad // 5, cx + rad // 3, cy + rad // 8), fill=(12, 21, 38, 255))
    return im


def look_still(kind: str) -> bytes:
    """One 1920x1080 still of the corner treatment and the guide character.

    `kind` is plain, monitor, laptop, phone, tv, bubble, or both (a monitor
    plus the guide). The presenter is the drawn stand-in, so this needs no
    footage and no network.
    """
    from PIL import Image, ImageDraw
    import io as _io
    im = Image.new("RGBA", (STAGE_W, STAGE_H), (9, 12, 18, 255))
    d = ImageDraw.Draw(im)
    d.text((160, 130), "MARKETS", font=_font(28, bold=True), fill=(245, 184, 61, 255))
    d.text((160, 176), "One day. Trillions erased.", font=_font(60, bold=True), fill=(242, 244, 248, 255))
    # The same hard depth the slide cards use: a contact shadow, a dark
    # underside, then the lit face.
    d.rounded_rectangle((172, 334, 1016, 616), radius=24, fill=(0, 0, 0, 80))
    d.rounded_rectangle((160, 328, 1000, 608), radius=24, fill=(7, 11, 18, 255))
    d.rounded_rectangle((160, 320, 1000, 596), radius=24, fill=(18, 24, 36, 255), outline=(74, 92, 120, 255), width=2)
    d.line((184, 322, 976, 322), fill=(120, 142, 176, 255), width=3)
    d.text((200, 360), "AI stocks", font=_font(40, bold=True), fill=(242, 244, 248, 255))
    d.text((200, 430), "A slide, with the corner kept clear.", font=_font(28), fill=(138, 148, 166, 255))
    show_frame = kind if kind in PIP_FRAME_GEOM else ("monitor" if kind == "both" else "")
    if kind == "plain" or show_frame:
        if show_frame:
            box = PIP_FRAME_GEOM[show_frame]["screen"]
            outer = PIP_FRAME_GEOM[show_frame]["outer"]
        else:
            box = _PIP_BOX
            outer = None
        x, y, w, h = box
        stand = _stand_in(w, h)
        if kind == "plain":
            mask = Image.new("L", (w, h), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=18, fill=255)
            im.paste(stand, (x, y), mask)
        else:
            im.paste(stand, (x, y), stand)
            frame = Image.open(_io.BytesIO(device_png(show_frame))).convert("RGBA")
            im.alpha_composite(frame, (outer[0], outer[1]))
    if kind in ("bubble", "both"):
        png, bw, bh = bubble_png("AI stocks lost about two trillion")
        im.alpha_composite(Image.open(_io.BytesIO(png)).convert("RGBA"), ASIDE_AT)
    buf = _io.BytesIO()
    im.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def write_look_samples(folder: Path) -> list:
    """Write the sample stills (plain corner, each device, the guide, both)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    names = {"plain": "plain_corner.png", "monitor": "frame_monitor.png", "laptop": "frame_laptop.png",
             "phone": "frame_phone.png", "tv": "frame_tv.png", "bubble": "guide_bubble.png",
             "both": "monitor_and_bubble.png"}
    out = []
    for kind, name in names.items():
        p = folder / name
        p.write_bytes(look_still(kind))
        out.append(p)
    return out


def _host_guide(host: Optional[dict]) -> str:
    if not host:
        return "- host: none on every slide (no presenter video)."
    pct = host_share_pct(host.get("share"))
    if not pct:
        return ("- host: none on every slide. The user places the presenter themselves (PRESENTER SECTIONS in a "
                "slide's brief); keep those areas clear.")
    return (f"- host: the presenter is on screen for about {pct}% of the runtime. "
            "That figure is screen time, and it is the budget. Spend it where the host talks "
            "to the viewer, in this order, and drop later items before going much past "
            f"{pct}%: the opening line, a chapter's first beat after its chapter card, opinions and asides, "
            "direct \"you\" moments, the call to action and the sign-off. full for short direct-address beats "
            "(4 to 10 s); left or right when one simple graphic supports what the host says; pip only now and then "
            "over a regular slide. Never on scenes, chapter cards or the asset slide. none for every other slide.")


def _plan_task(duration: float, counts: dict, host: Optional[dict] = None,
               span: Optional[tuple] = None) -> str:
    seconds = (span[1] - span[0]) if span else duration
    target = max(3 if span else 6, round(seconds / 11))
    if span:
        scope = (f"TASK: PLAN A TEST CLIP\nThe user wants to judge the look on a short test before the whole video is "
                 f"made. Plan only the narration from {span[0]:.1f} s to {span[1]:.1f} s ({fmt_secs(seconds)}), "
                 "as it would appear in the finished video (sections and chapter cards included where they fall). "
                 f"The first slide starts at the first spoken words at or after {span[0]:.1f} s. "
                 "Return JSON matching the schema.")
        first = f"the first slide starts at the first spoken words at or after {span[0]:.1f} s"
    else:
        scope = "TASK: PLAN THE VIDEO\nPlan every slide before any slide is written. Return JSON matching the schema."
        first = "s01 starts at the first spoken words"
    return f"""{scope}
- summary: 2 to 4 sentences on the approach: which passages become illustrated scenes, the recurring metaphors, the asset slide.
- sections: one per chapter or section of the script, in order, keys c1, c2 ...; label = a short HUD label of 2 to 4 words.
- slides: every slide in time order, ids s01, s02 ... at = the exact spoken words (3 to 8, copied from the timed transcript) where the slide starts; {first}. Each slide lasts 4 to 25 seconds: about {target} slides for {fmt_secs(seconds)} of narration. kind: chapter (one short card per section), scene (illustrated; about a third of the runtime, drawn from the GROK IMAGINE briefs and RESOLVE notes), slide, or asset (the copyable checklist or cheat sheet; one). idea: one or two sentences on what is on screen and how it moves, naming figures, logos and the spoken words that trigger the key beats. logos: the logo keys it shows.
{_host_guide(host)}
- logos: every brand logo the video shows. Use the user's file key when the brand has a file; otherwise a short lowercase key (openai, xai) and the brand name.
- figures: every [VERIFY BEFORE RENDER] figure that will appear on screen: key (snake_case), label, value exactly as the script states it, note (what to confirm, from the script).
- inserts: every [insert] value an ON SCREEN card needs: key, label, note.
- questions: only what blocks you. Usually empty.
- dropped: production notes you chose not to use, and why, in a few words each.
The script has {counts.get('scenes', 0)} GROK IMAGINE briefs, {counts.get('verify', 0)} VERIFY notes, {counts.get('on_screen', 0)} ON SCREEN notes and {counts.get('inserts', 0)} [insert] slots{' in all (plan only those in the test clip)' if span else ''}."""


_WHERE = {"full": "full frame", "left": "left panel", "right": "right panel", "pip": "corner window"}


def _sections_note(sections: list) -> str:
    """The user's presenter sections on a slide, for Claude."""
    if not sections:
        return ""
    return ("\n  PRESENTER SECTIONS the user placed on this slide (the presenter shows there; keep that area clear, "
            "following the Presenter rules for that layout): "
            + "; ".join(f"{_WHERE[x['layout']]} {x['t0']:.1f}-{x['t1']:.1f} s" for x in sections))


def _slide_brief(timeline: Timeline, entry: dict, t0: float, t1: float, sections: Optional[list] = None) -> str:
    host = entry.get("host") if entry.get("host") in HOST_LAYOUTS else ""
    on = [x for x in sections or [] if x["t0"] < t1 and x["t1"] > t0]
    return (f"{entry['id']} ({entry.get('kind', 'slide')}, section {entry.get('section', '')}"
            + (f", presenter {_WHERE[host]}: data-host=\"{host}\"" if host else "") + ") "
            f"{t0:.1f}-{t1:.1f} s ({t1 - t0:.1f} s). Idea: {entry.get('idea', '')}\n"
            f"  Spoken: {timeline.window_text(t0, t1)}" + _sections_note(on))


# ---------------------------------------------------------------------------
# Project folder
# ---------------------------------------------------------------------------

class Project:
    """One explainer video: <run dir>/explainer/<id>/ with project.json."""

    def __init__(self, folder: Path):
        self.dir = Path(folder)
        self.lock = threading.RLock()
        self._compiled = None
        p = self.dir / "project.json"
        self.data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}

    @property
    def id(self) -> str:
        return self.dir.name

    def save(self) -> None:
        with self.lock:
            self.data["updated"] = time.time()
            tmp = self.dir / "project.json.tmp"
            tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.dir / "project.json")

    def read(self, name: str) -> str:
        p = self.dir / name
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    def write(self, name: str, text: str) -> None:
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def plan(self) -> dict:
        t = self.read("plan.json")
        return json.loads(t) if t else {}

    def timeline(self) -> Timeline:
        words = json.loads(self.read("words.json") or "[]")
        return Timeline(words, float(self.data.get("audio_seconds") or 0))

    def span(self) -> Optional[tuple]:
        """(start, end) of a test clip, or None for the whole narration."""
        s = self.data.get("span")
        return (float(s[0]), float(s[1])) if s else None

    def host(self) -> Optional[dict]:
        h = self.data.get("host")
        return h if h and h.get("parts") else None

    def host_plan(self, compiled: dict, scale: float) -> Optional[dict]:
        """What a render worker needs to put the presenter under the page."""
        host = self.host()
        if not host or not compiled.get("host_windows"):
            return None
        return {"k": scale, "W": int(round(1920 * scale)), "H": int(round(1080 * scale)),
                "focus": float(host.get("focus", HOST_FOCUS)), "segments": host_segments(host),
                "windows": framed_windows(compiled["host_windows"], look_of(self.data, host)[0])}

    def version_name(self, n: int) -> str:
        return f"versions/v{int(n):03d}.html"

    def composition(self, n: Optional[int] = None) -> str:
        n = n or self.data.get("current") or 0
        return self.read(self.version_name(n)) if n else ""

    def add_usage(self, usage: dict) -> None:
        with self.lock:
            tot = self.data.setdefault("usage", {})
            for k, v in usage.items():
                tot[k] = tot.get(k, 0) + v
            tot["cost"] = round(usage_cost(tot), 4)

    def add_version(self, sections: list, kind: str, note: str = "") -> int:
        with self.lock:
            versions = self.data.setdefault("versions", [])
            n = max([v["n"] for v in versions] or [0]) + 1
            self.write(self.version_name(n), join_sections(sections))
            versions.append({"n": n, "kind": kind, "note": note[:300], "created": time.time(),
                             "slides": len(sections)})
            self.data["current"] = n
            self.data["approved"] = None
            self.save()
            return n

    def compile(self, n: Optional[int] = None) -> dict:
        """The compiled current (or given) version, cached until the version,
        values, logos or timing change."""
        n = n or self.data.get("current") or 0
        host = self.host()
        key = json.dumps([n, self.data.get("values"), self.data.get("logo_choices"),
                          self.data.get("logos"), self.data.get("timing"), self.data.get("span"),
                          bool(host), (host or {}).get("sections")], sort_keys=True, default=str)
        with self.lock:
            if self._compiled and self._compiled[0] == key:
                return self._compiled[1]
        logos = {}
        for k, v in (self.data.get("logos") or {}).items():
            path = self.dir / "logos" / v["file"] if v.get("file") else None
            logos[k] = {**v, "path": str(path) if path and path.is_file() else ""}
        out = compile_composition(
            self.composition(n), self.timeline(), duration=float(self.data.get("audio_seconds") or 0),
            plan=self.plan(), logos=logos, values=self.data.get("values") or {},
            logo_choices=self.data.get("logo_choices") or {}, span=self.span(), host_on=bool(host),
            host_sections=(host or {}).get("sections") or [])
        with self.lock:
            self._compiled = (key, out)
        return out

    def outstanding(self, compiled: dict) -> list:
        """What the user must supply before the 4K render."""
        plan = self.plan()
        figures = {ph_key(f.get("key")): f for f in plan.get("figures") or []}
        inserts = {ph_key(f.get("key")): f for f in plan.get("inserts") or []}
        values = self.data.get("values") or {}
        choices = self.data.get("logo_choices") or {}
        items = []
        for key, rec in sorted(compiled["logos"].items()):
            if not rec["has_file"] and choices.get(key) != "badge":
                items.append({"type": "logo", "key": key, "label": rec["name"], "slides": rec["slides"]})
        for key, rec in compiled["ph"].items():
            st = (values.get(key) or {}).get("status")
            if rec["insert"]:
                if st not in ("filled", "dropped"):
                    f = inserts.get(key) or {}
                    items.append({"type": "insert", "key": key, "label": f.get("label") or key,
                                  "note": f.get("note", ""), "slides": rec["slides"]})
            elif st not in ("confirmed", "edited"):
                f = figures.get(key) or {}
                items.append({"type": "figure", "key": key, "label": f.get("label") or key,
                              "value": f.get("value") or rec.get("default", ""), "note": f.get("note", ""),
                              "slides": rec["slides"]})
        return items


_PROJECTS: dict = {}
_PROJECTS_LOCK = threading.Lock()


def open_project(folder: Path) -> Project:
    """One shared Project per folder, so a running job and the dialog's
    requests see (and save) the same data."""
    key = str(Path(folder).resolve())
    with _PROJECTS_LOCK:
        if key not in _PROJECTS:
            _PROJECTS[key] = Project(Path(folder))
        return _PROJECTS[key]


def list_projects(root: Path, title: str) -> list:
    out = []
    base = Path(root) / "explainer"
    if not base.is_dir():
        return out
    for p in base.iterdir():
        f = p / "project.json"
        if p.is_dir() and PROJECT_ID_RE.match(p.name) and f.is_file():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if (d.get("title") or "") != title:
                continue
            out.append({"id": p.name, "created": d.get("created"), "updated": d.get("updated"),
                        "voiceover": d.get("voiceover"), "current": d.get("current"),
                        "slides": next((v["slides"] for v in d.get("versions") or [] if v["n"] == d.get("current")), 0),
                        "status": d.get("status") or "", "test": bool(d.get("span")),
                        "presenter": bool((d.get("host") or {}).get("parts"))})
    out.sort(key=lambda x: x.get("created") or 0, reverse=True)
    return out


# ---------------------------------------------------------------------------
# Jobs: prepare -> plan -> build, revise, render. One at a time per project.
# ---------------------------------------------------------------------------

_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()


def job_status(pid: str) -> dict:
    with _JOBS_LOCK:
        j = dict(_JOBS.get(pid) or {})
    j.pop("cancel", None)
    j.pop("procs", None)
    return j


def _job_set(pid: str, **kw) -> None:
    with _JOBS_LOCK:
        _JOBS.setdefault(pid, {}).update(kw)


def job_running(pid: str) -> bool:
    with _JOBS_LOCK:
        return (_JOBS.get(pid) or {}).get("status") == "running"


def cancel_job(pid: str) -> bool:
    with _JOBS_LOCK:
        j = _JOBS.get(pid)
        if not j or j.get("status") != "running":
            return False
        j["cancel"].set()
        for p in j.get("procs") or []:
            try:
                p.terminate()
            except Exception:
                pass
        return True


def start_job(project: Project, kind: str, fn: Callable, log: Callable) -> bool:
    """Run fn(project, cancel, status) on a thread; False if one is running."""
    pid = project.id
    cancel = threading.Event()
    with _JOBS_LOCK:
        if (_JOBS.get(pid) or {}).get("status") == "running":
            return False
        _JOBS[pid] = {"status": "running", "kind": kind, "stage": "", "message": "Starting…",
                      "progress": 0.0, "started": time.time(), "cancel": cancel, "procs": []}

    def status(stage=None, message=None, progress=None):
        kw = {}
        if stage is not None:
            kw["stage"] = stage
        if message is not None:
            kw["message"] = message
        if progress is not None:
            kw["progress"] = max(0.0, min(1.0, progress))
        _job_set(pid, **kw)

    def run():
        try:
            result = fn(project, cancel, status) or {}
            _job_set(pid, status="done", progress=1.0, result=result,
                     message=result.get("message") or "Done", elapsed=round(time.time() - _JOBS[pid]["started"]))
        except Cancelled:
            log(f"⏹️ Explainer {kind} stopped")
            _job_set(pid, status="cancelled", message="Stopped")
        except Exception as e:  # noqa: BLE001 - shown to the user
            log(f"❌ Explainer {kind} failed: {e}", "error")
            _job_set(pid, status="error", error=str(e), message=str(e))
        finally:
            project.data["status"] = job_status(pid).get("status", "")
            try:
                project.save()
            except Exception:
                pass

    threading.Thread(target=run, daemon=True, name=f"explainer-{kind}-{pid}").start()
    return True


def _register_proc(pid: str, proc) -> None:
    with _JOBS_LOCK:
        (_JOBS.get(pid) or {}).setdefault("procs", []).append(proc)


def pick_span(timeline: Timeline, start: float, seconds: float) -> Optional[tuple]:
    """A test clip of about `seconds` from `start`, on sentence boundaries:
    it opens just before a sentence and closes just after one, without
    catching the neighbouring words. None when that is the whole narration."""
    sents = timeline.sentences()
    words = timeline.words
    if not sents:
        return None
    i0 = next((i for i, s in enumerate(sents) if s[1] > start + 0.01), len(sents) - 1)
    first_word = sents[i0][0]
    target = first_word + max(15.0, seconds)
    best = i0
    for i in range(i0, len(sents)):
        if abs(sents[i][1] - target) < abs(sents[best][1] - target):
            best = i
        if sents[i][1] > target + 20:
            break
    if i0 == 0 and best == len(sents) - 1:
        return None
    before = [w["end"] for w in words if w["end"] <= first_word + 1e-6]
    a = 0.0 if i0 == 0 else round(max(max(before or [0.0]) + 0.05, first_word - 0.5), 3)
    last_word = sents[best][1]
    after = [w["start"] for w in words if w["start"] > last_word + 1e-6]
    b = (round(timeline.duration + TAIL, 3) if best == len(sents) - 1
         else round(min(last_word + 1.0, min(after or [last_word + 1.0]) - 0.05), 3))
    return a, b


def prepare(project: Project, *, audio_src: Path, spoken_text: str, eleven_key: str,
            pauses: Callable[[Path], list], logos: list, images_dir: Path,
            status: Callable, log: Callable, test: Optional[dict] = None) -> None:
    """Normalize the narration, time the words, pick the test clip (if any)
    and process the logos."""
    status("audio", "Normalizing the narration to -14 LUFS…", 0.02)
    loud = normalize_audio(audio_src, project.dir / "narration.wav", project.dir / "narration.m4a")
    seconds = media_seconds(project.dir / "narration.wav")
    project.data.update(audio_seconds=round(seconds, 3), loudness=loud)
    log(f"\U0001f39a️ Narration normalized: {loud['input_lufs']:.1f} → -14 LUFS, {fmt_secs(seconds)}")
    status("timing", "Timing every spoken word (ElevenLabs)…", 0.05)
    words, source, loss = None, "estimated", None
    if eleven_key and spoken_text.strip():
        try:
            words, loss = align_words(audio_src, spoken_text, eleven_key)
            source = "elevenlabs"
        except Exception as e:
            log(f"⚠️ Word timing fell back to an estimate: {e}", "warning")
    if words is None:
        words = estimate_words(spoken_text, seconds, pauses(audio_src))
    project.write("words.json", json.dumps(words))
    project.data["timing"] = {"source": source, "words": len(words),
                              "loss": round(float(loss), 3) if isinstance(loss, (int, float)) else None}
    log(f"⏱️ {len(words):,} words timed ({'ElevenLabs forced alignment' if source == 'elevenlabs' else 'estimated from pauses'})")
    project.data["span"] = None
    if test:
        span = pick_span(Timeline(words, seconds), float(test.get("start") or 0),
                         float(test.get("minutes") or 2) * 60)
        project.data["span"] = list(span) if span else None
        if span:
            log(f"\U0001f9ea Test clip: {fmt_secs(span[0])}–{fmt_secs(span[1])} of {fmt_secs(seconds)}")
    status("logos", "Preparing logos…", 0.08)
    project.data["logos"] = {}
    for item in logos:
        add_logo(project, images_dir / item["file"], item.get("name") or logo_name_from_file(item["file"]),
                 item.get("recolor") or "auto", source_name=item["file"])
    project.save()


def add_logo(project: Project, src: Path, name: str, recolor: str = "auto",
             key: Optional[str] = None, source_name: str = "") -> dict:
    key = key or slug(name) or slug(src.stem) or "logo"
    info = process_logo(src, project.dir / "logos", key, recolor)
    rec = {"name": name.strip()[:40] or key, "source": source_name or src.name, "recolor": recolor, **info}
    with project.lock:
        project.data.setdefault("logos", {})[key] = rec
        project.data.setdefault("logo_choices", {}).pop(key, None)
    return {"key": key, **rec}


def _clean_plan(plan: dict, host_on: bool, taken: Optional[set] = None) -> dict:
    """Unique slide ids, safe placeholder and logo keys, valid presenter layouts."""
    seen = set(taken or ())
    for i, s in enumerate(plan.get("slides") or []):
        sid = re.sub(r"[^A-Za-z0-9_-]", "", s.get("id") or "") or f"s{i + 1:02d}"
        while sid in seen:
            sid += "x"
        seen.add(sid)
        s["id"] = sid
        s["host"] = s.get("host") if host_on and s.get("host") in HOST_LAYOUTS else "none"
    for f in (plan.get("figures") or []) + (plan.get("inserts") or []):
        f["key"] = ph_key(f.get("key")) or "value"
    for lg in plan.get("logos") or []:
        lg["key"] = logo_key(lg.get("key")) or "logo"
    return plan


def _plan_call(project: Project, client, cancel, status, blocks: list, what: str) -> "tuple[dict, dict]":
    def prog(text):
        if text.startswith("__retry__"):
            status(message=f"{MODEL_LABEL}: {text[10:]}")
            return
        n = len(re.findall(r'"id"\s*:', text))
        status(message=f"{MODEL_LABEL} is {what}\u2026 {n} planned", progress=0.1 + min(0.1, n / 900))

    status("plan", f"{MODEL_LABEL} is {what}\u2026", 0.1)
    res = claude_call(client, blocks, max_tokens=PLAN_MAX_TOKENS, schema=PLAN_SCHEMA, progress=prog, cancel=cancel)
    project.add_usage(res["usage"])
    if res["stop_reason"] == "max_tokens":
        raise RuntimeError("Claude's plan was cut off at the token limit. Try again.")
    return json.loads(res["text"]), res["usage"]


def plan_video(project: Project, client, cancel, status, log) -> dict:
    timeline = project.timeline()
    counts = production_counts(project.read("script.txt"))
    t0 = time.time()
    span = project.span()
    plan, usage = _plan_call(project, client, cancel, status, _context_blocks(project, timeline) + [
        {"type": "text", "text": _plan_task(timeline.duration, counts, project.host(), span)}],
        "planning the test clip" if span else "planning the slides")
    if not plan.get("slides"):
        raise RuntimeError("Claude's plan has no slides")
    _clean_plan(plan, bool(project.host()))
    project.write("plan.json", json.dumps(plan, indent=1, ensure_ascii=False))
    hosted = sum(1 for s in plan["slides"] if s.get("host") in HOST_LAYOUTS)
    log(f"\U0001f5fa\ufe0f Plan ready in {time.time() - t0:.0f}s: {len(plan['slides'])} slides, "
        f"{sum(1 for s in plan['slides'] if s.get('kind') == 'scene')} scenes, "
        + (f"{hosted} with the presenter, " if project.host() else "")
        + f"{len(plan.get('figures') or [])} figures to confirm, {len(plan.get('inserts') or [])} inserts "
        f"(${usage_cost(usage):.2f})")
    return plan


def _plan_windows(project: Project, plan: dict) -> list:
    """(entry, t0, t1) for each planned slide, from its start words."""
    timeline = project.timeline()
    stub = "\n".join(f'<section id="{_html.escape(s["id"])}" data-at="{_html.escape(s.get("at") or "", quote=True)}"></section>'
                     for s in plan.get("slides") or [])
    comp = compile_composition(stub, timeline, duration=timeline.duration, plan=plan, logos={},
                               values={}, logo_choices={}, span=project.span())
    by_id = {m["id"]: m for m in comp["slides"]}
    return [(s, by_id[s["id"]]["t0"], by_id[s["id"]]["t1"]) for s in plan.get("slides") or [] if s["id"] in by_id]


def _batches(windows: list) -> list:
    weight = {"scene": 2.5, "asset": 2.0, "slide": 1.0, "chapter": 0.5}
    out, cur, w = [], [], 0.0
    for item in windows:
        cur.append(item)
        w += weight.get(item[0].get("kind"), 1.0)
        if w >= BATCH_WEIGHT:
            out.append(cur)
            cur, w = [], 0.0
    if cur:
        out.append(cur)
    return out


def _build_task(timeline: Timeline, batch: list, windows: list, feedback: str = "",
                host_on: bool = False, notes_label: str = "THE USER'S NOTES FOR THIS REBUILD",
                sections: Optional[list] = None) -> str:
    ids = [e["id"] for e, _a, _b in batch]
    pos = {e["id"]: i for i, (e, _a, _b) in enumerate(windows)}
    before = windows[pos[ids[0]] - 1][0] if pos[ids[0]] > 0 else None
    after = windows[pos[ids[-1]] + 1][0] if pos[ids[-1]] + 1 < len(windows) else None
    lines = [f"TASK: WRITE SLIDES {ids[0]} TO {ids[-1]}",
             "Write these slides following the plan, the design system and the composition format. "
             "Return only the <section> elements, in order, with nothing before, between or after them. "
             "Copy every data-at phrase exactly from that slide's spoken words below.", ""]
    if feedback:
        lines += [notes_label, feedback.strip(), ""]
    if before:
        lines.append(f"(Previous slide {before['id']}: {before.get('idea', '')})")
    for e, t0, t1 in batch:
        lines.append(_slide_brief(timeline, e if host_on else {**e, "host": "none"}, t0, t1,
                                  sections if host_on else None))
    if after:
        lines.append(f"(Next slide {after['id']}: {after.get('idea', '')})")
    return "\n".join(lines)


def build_slides(project: Project, client, cancel, status, log, feedback: str = "",
                 progress_span=(0.2, 0.95), kind: str = "build", only: Optional[set] = None,
                 extra: str = "", notes_label: str = "THE USER'S NOTES FOR THIS REBUILD",
                 combine: Callable[[list], list] = lambda new: new) -> list:
    """Write every planned slide (or the `only` ones), in parallel batches.
    Returns the sections; `combine` places them in the whole composition when
    a failed batch forces a partial save."""
    plan = project.plan()
    timeline = project.timeline()
    windows = _plan_windows(project, plan)
    batches = _batches([w for w in windows if only is None or w[0]["id"] in only])
    if not batches:
        raise RuntimeError("There are no slides to write")
    ctx = _context_blocks(project, timeline)
    plan_blk = _plan_block(project, extra)
    host_on = bool(project.host())
    sections = (project.host() or {}).get("sections") or []
    total = sum(len(b) for b in batches)
    done = {"n": 0}
    lock = threading.Lock()
    results: dict = {}
    first_started = threading.Event()
    lo, hi = progress_span
    t_start = time.time()

    def report():
        with lock:
            n = min(done["n"], total)
        status("build", f"{MODEL_LABEL} is writing slides… {n} of {total} done "
                        f"({len(batches)} batches, {BUILD_WORKERS} at a time)",
               lo + (hi - lo) * n / max(1, total))

    def run_batch(k: int, batch: list, retry: bool = False):
        ids = [e["id"] for e, _a, _b in batch]
        seen_in_stream = {"n": 0}

        def prog(text):
            if text.startswith("__retry__"):
                log(f"\u23f3 Slides {ids[0]}\u2013{ids[-1]}: {text[10:]}", "warning")
                return
            n = text.count("</section>")
            if n > seen_in_stream["n"]:
                with lock:
                    done["n"] += n - seen_in_stream["n"]
                seen_in_stream["n"] = n
                report()

        task = _build_task(timeline, batch, windows, feedback, host_on, notes_label, sections)
        res = claude_call(client, ctx + [plan_blk, {"type": "text", "text": task}],
                          max_tokens=BUILD_MAX_TOKENS, progress=prog, cancel=cancel,
                          on_start=first_started.set)
        first_started.set()
        project.add_usage(res["usage"])
        got = {s["id"]: s for s in split_sections(res["text"])}
        with lock:
            done["n"] += max(0, len([i for i in ids if i in got]) - seen_in_stream["n"])
        report()
        missing = [e for e in batch if e[0]["id"] not in got]
        log(f"✍️ Slides {ids[0]}–{ids[-1]} written ({len(got)} sections, "
            f"{res['usage']['output_tokens']:,} tokens, ${usage_cost(res['usage']):.2f})")
        if missing and not retry and not cancel.is_set():
            log(f"↻ Rewriting {len(missing)} slide(s) Claude did not return: {', '.join(e[0]['id'] for e in missing)}")
            got.update(run_batch(k, missing, retry=True))
        return got

    report()
    failed: list = []
    with ThreadPoolExecutor(max_workers=BUILD_WORKERS) as pool:
        futs = [pool.submit(run_batch, 0, batches[0])]
        # Let the first call write the shared prefix to the cache before the rest start.
        first_started.wait(timeout=60)
        futs += [pool.submit(run_batch, k, b) for k, b in enumerate(batches[1:], 1)]
        for k, f in enumerate(futs):
            try:
                results.update(f.result())
            except Cancelled:
                pass
            except Exception as e:  # noqa: BLE001 - keep the batches that worked
                ids = [x["id"] for x, _a, _b in batches[k]]
                failed.append((ids, e))
                log(f"\u274c Slides {ids[0]}\u2013{ids[-1]} failed: {e}", "error")
    if cancel.is_set():
        raise Cancelled()
    sections = []
    for e, _a, _b in windows:
        if e["id"] in results:
            sections.append(results.pop(e["id"]))
            for split_id in [k for k in list(results) if k.startswith(e["id"]) and k != e["id"]]:
                sections.append(results.pop(split_id))
    sections += list(results.values())
    if not sections:
        raise RuntimeError(f"Claude returned no slides: {failed[0][1] if failed else 'empty reply'}")
    log(f"\U0001f3ac {len(sections)} slides written in {time.time() - t_start:.0f}s")
    if failed:
        missing = [i for ids, _e in failed for i in ids]
        n = project.add_version(combine(sections), kind, f"Saved without {len(missing)} slide(s) that failed")
        raise RuntimeError(f"{len(missing)} slide(s) could not be written ({missing[0]}\u2013{missing[-1]}: "
                           f"{failed[0][1]}). Version {n} was saved with the other {len(sections)} slides so "
                           "nothing is lost; rebuild with notes, or revise the slide before the gap.")
    return sections


def revise(project: Project, client, cancel, status, log, *, feedback: str, slide_ids: list,
           warnings: dict, stills: Optional[dict] = None) -> "tuple[int, list]":
    """Rewrite the chosen slides from the user's notes. Returns (version, changed ids)."""
    current = split_sections(project.composition())
    compiled = project.compile()
    meta = {m["id"]: m for m in compiled["slides"]}
    timeline = project.timeline()
    targets = [s for s in current if s["id"] in slide_ids]
    if not targets:
        raise RuntimeError("Pick at least one slide to revise")
    index = "\n".join(f"- {m['id']} {m['t0']:.1f}-{m['t1']:.1f}s {m['kind']} [{m['section']}]: {m['idea'][:160]}"
                      for m in compiled["slides"])
    blocks = _context_blocks(project, timeline) + [_plan_block(project, "CURRENT SLIDES\n" + index)]
    parts = ["TASK: REVISE SLIDES",
             "The user reviewed the preview. Rewrite the slides below to address the notes, keeping "
             "everything that already works. Return only the <section> elements that change, in "
             "time order. To split a slide, return both parts (s12 and s12b) with their own data-at. "
             "To remove a slide, return <section id=\"s12\" data-delete=\"1\"></section>. "
             "Copy every data-at phrase exactly from the spoken words. Start your reply with one line: "
             "CHANGES: one or two sentences on what you changed and anything that still needs the user's input.", "",
             "THE USER'S NOTES", feedback.strip() or "(none: fix the layout problems below)", ""]
    for s in targets:
        m = meta.get(s["id"]) or {}
        t0, t1 = m.get("t0", 0), m.get("t1", 0)
        parts.append(f"=== {s['id']} {t0:.1f}-{t1:.1f} s ({t1 - t0:.1f} s), {m.get('kind', '')}")
        parts.append(f"Spoken: {timeline.window_text(t0, t1)}" + _sections_note(m.get("sections") or []))
        found = [w["msg"] for w in m.get("warnings") or [] if not w.get("minor")] + list(warnings.get(s["id"]) or [])
        if found:
            parts.append("Problems found: " + "; ".join(found))
        parts.append("Current markup:\n" + s["raw"])
        parts.append("")
    content = []
    for sid, png in (stills or {}).items():
        content.append({"type": "text", "text": f"Still of {sid} near its end:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                    "data": base64.b64encode(png).decode("ascii")}})
    content.append({"type": "text", "text": "\n".join(parts)})
    status("revise", f"{MODEL_LABEL} is revising {len(targets)} slide(s)…", 0.2)

    def prog(text):
        if text.startswith("__retry__"):
            status(message=f"{MODEL_LABEL}: {text[10:]}")
            return
        status(message=f"{MODEL_LABEL} is revising… {text.count('</section>')} slide(s) rewritten")

    res = claude_call(client, blocks + content, max_tokens=BUILD_MAX_TOKENS, progress=prog, cancel=cancel)
    project.add_usage(res["usage"])
    returned = split_sections(res["text"])
    if not returned:
        raise RuntimeError("Claude returned no slides for this revision")
    merged, changed = merge_sections(current, returned)
    m = re.search(r"CHANGES:\s*(.+)", res["text"].split("<section", 1)[0])
    summary = m.group(1).strip()[:400] if m else ""
    n = project.add_version(merged, "revise", (feedback or "Layout fixes") + (f" → {summary}" if summary else ""))
    log(f"✏️ Version {n}: {len(changed)} slide(s) changed ({', '.join(changed[:12])}) "
        f"(${usage_cost(res['usage']):.2f})" + (f": {summary}" if summary else ""))
    return n, changed, summary


def run_create(project: Project, client, *, audio_src: Path, spoken_text: str, eleven_key: str,
               pauses: Callable, logos: list, images_dir: Path, cancel, status, log,
               test: Optional[dict] = None, presenter: Optional[dict] = None,
               root: Optional[Path] = None, share: Optional[str] = None,
               pip_frame: Optional[str] = None, bubble: Optional[str] = None,
               visual_style: Optional[str] = None) -> dict:
    """The whole first pass: prepare, (match the presenter clips,) plan,
    build. Returns the job result."""
    prepare(project, audio_src=audio_src, spoken_text=spoken_text, eleven_key=eleven_key, pauses=pauses,
            logos=logos, images_dir=images_dir, status=status, log=log, test=test)
    with project.lock:
        project.data["pip_frame"] = pip_frame_key(pip_frame, project.data.get("pip_frame"))
        project.data["bubble"] = bubble_mode_key(bubble, project.data.get("bubble"))
        project.data["visual_style"] = visual_style_key(visual_style, project.data.get("visual_style"))
    project.save()
    if cancel.is_set():
        raise Cancelled()
    if presenter:
        attach_host(project, presenter, root or project.dir, status, log, share, project.data.get("pip_frame"))
    plan_video(project, client, cancel, status, log)
    sections = build_slides(project, client, cancel, status, log)
    n = project.add_version(sections, "build", "Test clip" if project.span() else "First build")
    compiled = project.compile()
    left = project.outstanding(compiled)
    log(f"\u2705 Explainer version {n} ready: {len(sections)} slides for "
        f"{fmt_secs(compiled['end'] - compiled['start'])}{' (test clip)' if project.span() else ''}; "
        f"{len(left)} item(s) need your input before the 4K render; Claude so far "
        f"${(project.data.get('usage') or {}).get('cost', 0):.2f}")
    return {"message": f"Version {n} ready: {len(sections)} slides", "version": n}


def _base_id(sid: str) -> str:
    m = re.match(r"^(s\d+)", sid or "")
    return m.group(1) if m else sid


def _test_notes(project: Project) -> list:
    """What the user asked for while refining (revision notes and whole-video notes)."""
    out = []
    for v in project.data.get("versions") or []:
        if v.get("kind") in ("revise", "rebuild"):
            note = (v.get("note") or "").split(" \u2192 ")[0].strip()
            if note and note not in ("Layout fixes", "Rebuilt") and note not in out:
                out.append(note)
    for n in project.data.get("notes") or []:
        if n not in out:
            out.append(n)
    return out


def extend(project: Project, client, cancel, status, log) -> dict:
    """Plan and write the rest of the video around the refined test clip,
    following its slides (as the approved look) and the user's notes."""
    span = project.span()
    if not span:
        raise RuntimeError("This video already covers the whole narration")
    current = split_sections(project.composition())
    if not current:
        raise RuntimeError("Build the test clip first")
    a, b = span
    timeline = project.timeline()
    plan = project.plan()
    counts = production_counts(project.read("script.txt"))
    host = project.host()
    taken = {s["id"] for s in current} | {s["id"] for s in plan.get("slides") or []}
    next_n = max([int(m.group(1)) for m in (re.match(r"^s(\d+)", i) for i in taken) if m] or [0]) + 1
    rest = max(0.0, a) + max(0.0, timeline.duration - b)
    reference = join_sections(current)
    if len(reference) > 60000:
        reference = reference[:60000] + "\n<!-- (more test slides) -->\n"
    notes = _test_notes(project)
    extra = (f"THE TEST CLIP ({a:.1f}-{b:.1f} s), REFINED AND APPROVED BY THE USER: keep these slides as they "
             "are and match their look (layouts, type sizes, colors, motion, how scenes are drawn).\n"
             "<test_slides>\n" + reference + "</test_slides>\n")
    if notes:
        extra += "\nTHE USER'S NOTES WHILE REFINING THE TEST CLIP\n" + "\n".join(f"- {x}" for x in notes) + "\n"
    where = " and ".join(x for x in (f"before it (0-{a:.1f} s)" if a > 1 else "",
                                     f"after it ({b:.1f} s to the end)" if b < timeline.duration else "") if x)
    task = f"""TASK: PLAN THE REST OF THE VIDEO
The test clip is finished: its slides are in THE PLAN and in the test slides above. Plan the rest of the narration, {where or 'around it'}, in the same style. Return JSON matching the schema.
- summary: how the rest continues the test clip's approach.
- sections: every section of the whole video in order, keeping the keys and labels the plan already has.
- slides: only the new slides, in time order, ids s{next_n:02d}, s{next_n + 1:02d} ... and none inside {a:.1f}-{b:.1f} s. at = the exact spoken words (3 to 8, copied from the timed transcript) where each starts{'; the first new slide starts at the first spoken words of the narration' if a > 1 else ''}. Each slide lasts 4 to 25 seconds: about {max(1, round(rest / 11))} slides for {fmt_secs(rest)} of narration. kind, idea and logos as in THE PLAN; the asset slide only if the plan has none.
{_host_guide(host)}
- logos, figures, inserts: only ones THE PLAN does not have yet.
- questions: only what blocks you. Usually empty.
- dropped: production notes in the new part you chose not to use, and why.
The script has {counts.get('scenes', 0)} GROK IMAGINE briefs, {counts.get('verify', 0)} VERIFY notes, {counts.get('on_screen', 0)} ON SCREEN notes and {counts.get('inserts', 0)} [insert] slots in all."""
    t0 = time.time()
    new_plan, usage = _plan_call(project, client, cancel, status, _context_blocks(project, timeline) + [
        _plan_block(project, extra), {"type": "text", "text": task}], "planning the rest of the video")
    _clean_plan(new_plan, bool(host), taken)
    before, after, skipped = [], [], []
    for s in new_plan.get("slides") or []:
        hit = timeline.find(s.get("at") or "", floor=0.0, limit=a) if a > 1 else None
        if hit and hit[0] < a:
            before.append((hit[0], s))
            continue
        hit = timeline.find(s.get("at") or "", floor=max(0.0, b - 1.0))
        if hit and hit[0] >= b - 0.5:
            after.append((hit[0], s))
        else:
            skipped.append(s["id"])
    if not before and not after:
        raise RuntimeError("Claude's plan for the rest had no slides outside the test clip. Try again.")
    if skipped:
        log(f"\u26a0\ufe0f Left out {len(skipped)} planned slide(s) whose start words fall inside the test clip "
            f"or were not found: {', '.join(skipped)}", "warning")
    before.sort(key=lambda x: x[0])
    after.sort(key=lambda x: x[0])
    merged = dict(plan)
    merged["slides"] = [s for _t, s in before] + list(plan.get("slides") or []) + [s for _t, s in after]
    labels = {x.get("key"): x for x in plan.get("sections") or []}
    secs = [labels.get(x.get("key"), x) for x in new_plan.get("sections") or []]
    secs += [x for x in plan.get("sections") or [] if x.get("key") not in {y.get("key") for y in secs}]
    merged["sections"] = secs
    for k in ("logos", "figures", "inserts"):
        have = {x.get("key") for x in plan.get(k) or []}
        merged[k] = list(plan.get(k) or []) + [x for x in new_plan.get(k) or [] if x.get("key") not in have]
    for k in ("questions", "dropped"):
        merged[k] = list(plan.get(k) or []) + [x for x in new_plan.get(k) or [] if x not in (plan.get(k) or [])]
    merged["summary"] = ((plan.get("summary") or "") + " " + (new_plan.get("summary") or "")).strip()
    log(f"\U0001f5fa\ufe0f Plan for the rest ready in {time.time() - t0:.0f}s: {len(before)} slide(s) before and "
        f"{len(after)} after the test clip (${usage_cost(usage):.2f})")
    old_plan, old_current = project.read("plan.json"), project.data.get("current")
    project.write("plan.json", json.dumps(merged, indent=1, ensure_ascii=False))
    project.data["span"] = None
    project.save()
    pre_ids = {s["id"] for _t, s in before}

    def combine(new):
        return ([s for s in new if _base_id(s["id"]) in pre_ids] + current
                + [s for s in new if _base_id(s["id"]) not in pre_ids])

    try:
        new = build_slides(project, client, cancel, status, log, feedback="\n".join(f"- {x}" for x in notes),
                           only=pre_ids | {s["id"] for _t, s in after}, extra=extra, combine=combine,
                           notes_label="THE USER'S NOTES WHILE REFINING THE TEST CLIP (apply them here where they fit)",
                           kind="extend")
    except BaseException:
        if project.data.get("current") == old_current:
            # Nothing was saved: put the test clip back the way it was.
            project.write("plan.json", old_plan)
            project.data["span"] = [a, b]
            project.save()
        raise
    n = project.add_version(combine(new), "extend", f"Built the rest of the video: {len(new)} new slides "
                                                    f"around the test clip")
    log(f"\U0001f9e9 Explainer version {n}: the whole video ({len(new)} new + {len(current)} test slides); "
        f"Claude so far ${(project.data.get('usage') or {}).get('cost', 0):.2f}")
    return {"message": f"Version {n} ready: the whole video ({len(new) + len(current)} slides)", "version": n}


def set_slide_host(project: Project, sid: str, layout: str) -> int:
    """Show the presenter on a slide (or not) without asking Claude: a new
    version with that slide's data-host changed."""
    layout = layout if layout in HOST_LAYOUTS else ""
    sections = split_sections(project.composition())
    target = next((s for s in sections if s["id"] == sid), None)
    if target is None:
        raise RuntimeError(f"No slide {sid}")
    tag = re.match(r"<section\b[^>]*>", target["raw"], re.I).group(0)
    new_tag = re.sub(r"\sdata-host\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", tag, flags=re.I)
    if layout:
        new_tag = new_tag[:-1].rstrip() + f' data-host="{layout}">'
    target["raw"] = new_tag + target["raw"][len(tag):]
    target["attrs"] = _first_tag_attrs(new_tag)
    plan = project.plan()
    for s in plan.get("slides") or []:
        if s.get("id") == sid:
            s["host"] = layout or "none"
            project.write("plan.json", json.dumps(plan, indent=1, ensure_ascii=False))
    return project.add_version(sections, "layout", f"{sid}: presenter {layout or 'off'}")


def rebuild(project: Project, client, cancel, status, log, *, feedback: str, replan: bool) -> dict:
    """Whole-video revision: optionally re-plan, then rewrite every slide."""
    if replan:
        notes = project.data.setdefault("notes", [])
        if feedback and feedback not in notes:
            notes.append(feedback)
        plan_video(project, client, cancel, status, log)
    sections = build_slides(project, client, cancel, status, log, feedback=feedback, kind="rebuild")
    n = project.add_version(sections, "rebuild", feedback or "Rebuilt")
    log(f"\u267b\ufe0f Explainer version {n}: every slide rewritten ({len(sections)} slides)")
    return {"message": f"Version {n} ready: {len(sections)} slides", "version": n}


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text or "Explainer").strip("_")[:60] or "Explainer"


def end_times(compiled: dict) -> dict:
    """slide id -> a time when the slide is fully built and alone on screen."""
    return {m["id"]: round(max(m["t0"] + 0.45, m["t1"] - 0.05), 3) for m in compiled["slides"]}


def render(project: Project, kind: str, cancel, status, log, start: float = 0.0,
           seconds: float = 30.0) -> dict:
    """sample: a 1080p clip from `start`; review: the whole 1080p cut; final:
    the approved 4K video + 720p phone copy + 4K PNG of each asset slide."""
    n = project.data.get("current")
    if not n:
        raise RuntimeError("There are no slides yet")
    compiled = project.compile()
    first, last = compiled["start"], compiled["end"]
    total = last - first
    test = project.span() is not None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = _safe_name(project.data.get("title")) + ("_test" if test else "")
    page = write_page(project, compiled, "render", f"render_v{n:03d}.html")
    files, levels = [], None
    t_start = time.time()
    if kind == "sample":
        a = max(first, min(float(start), last - 1.0))
        b = min(last, a + max(5.0, float(seconds)))
        out = project.dir / "renders" / f"sample_v{n:03d}_{int(a) // 60:02d}m{int(a) % 60:02d}s_{stamp}.mp4"
        log(f"\U0001f39e\ufe0f Sample clip {fmt_secs(a)}\u2013{fmt_secs(b)} of version {n} (1080p)\u2026")
        render_video(project, page, start=a, end=b, scale=1, crf=18, out=out, status=status,
                     cancel=cancel, label="Sample clip", host=project.host_plan(compiled, 1))
        files.append({"kind": "sample", "path": str(out.relative_to(project.dir)), "seconds": round(b - a, 2)})
    elif kind == "review":
        out = project.dir / "renders" / f"{safe}_review_1080p_v{n:03d}_{stamp}.mp4"
        log(f"\U0001f4fc 1080p review cut of version {n} ({fmt_secs(total)}{', test clip' if test else ''})\u2026")
        render_video(project, page, start=first, end=last, scale=1, crf=17, out=out, status=status,
                     cancel=cancel, label="1080p review", host=project.host_plan(compiled, 1))
        files.append({"kind": "review", "path": str(out.relative_to(project.dir)), "seconds": total})
    elif kind == "final":
        left = project.outstanding(compiled)
        if left:
            raise RuntimeError(f"{len(left)} item(s) still need your input before the 4K render")
        if project.data.get("approved") != n:
            raise RuntimeError("Approve this version first")
        final_dir = project.dir / "final"
        out = final_dir / f"{safe}_explainer_4K_v{n:03d}_{stamp}.mp4"
        log(f"\U0001f3ac 4K {'test' if test else 'final'} of version {n} ({fmt_secs(total)}, 3840x2160, 30 fps)\u2026")
        render_video(project, page, start=first, end=last, scale=2, crf=16, out=out, status=status,
                     cancel=cancel, label="4K test" if test else "4K final", progress_span=(0.0, 0.86),
                     host=project.host_plan(compiled, 2))
        files.append({"kind": "final", "path": str(out.relative_to(project.dir)), "seconds": total})
        status("phone", "Making the 720p phone copy\u2026", 0.88)
        phone = phone_copy(out, final_dir / f"{safe}_explainer_720p_phone_v{n:03d}_{stamp}.mp4")
        files.append({"kind": "phone", "path": str(phone.relative_to(project.dir)), "seconds": total})
        assets = [m for m in compiled["slides"] if m["kind"] == "asset"]
        if assets:
            status("asset", "Saving the asset slide as a 4K PNG\u2026", 0.95)
            ends = end_times(compiled)
            for m, png in zip(assets, project_stills(project, compiled, page, [ends[m["id"]] for m in assets], 2.0)):
                p = final_dir / f"{safe}_asset_4K_{m['id']}_v{n:03d}.png"
                p.write_bytes(png)
                files.append({"kind": "asset", "path": str(p.relative_to(project.dir))})
        levels = audio_levels(out)
        log(f"\U0001f50a Final audio: mean {levels['mean_db']} dB, peak {levels['max_db']} dB "
            "(target about -18 dB mean, peaks under -1 dB)")
    else:
        raise RuntimeError(f"Unknown render: {kind}")
    for f in files:
        p = project.dir / f["path"]
        f["size"] = p.stat().st_size if p.is_file() else 0
    rec = {"kind": kind, "version": n, "created": time.time(), "elapsed": round(time.time() - t_start),
           "files": files, "levels": levels}
    with project.lock:
        project.data.setdefault("renders", []).append(rec)
    project.save()
    main = project.dir / files[0]["path"]
    log(f"\u2705 {kind.title()} render saved: {main} ({main.stat().st_size / 1048576:.0f} MB, "
        f"{time.time() - t_start:.0f}s)")
    return {"message": f"Saved {main.name}", "render": rec}


def contact_sheets(project: Project, status, cancel, per_sheet: int = 24) -> list:
    """Stills of every slide, fully built, as contact sheets (4 across)."""
    n = project.data.get("current")
    compiled = project.compile()
    page = write_page(project, compiled, "render", f"render_v{n:03d}.html")
    ends = end_times(compiled)
    slides = compiled["slides"]
    status("stills", f"Rendering {len(slides)} stills\u2026", 0.1)
    pngs = project_stills(project, compiled, page, [ends[m["id"]] for m in slides], 0.5)
    if cancel.is_set():
        raise Cancelled()
    out = []
    folder = project.dir / "stills"
    folder.mkdir(exist_ok=True)
    for old in folder.glob(f"sheet_v{n:03d}_*.png"):
        old.unlink()
    for k in range(0, len(slides), per_sheet):
        chunk = slides[k:k + per_sheet]
        sheet = contact_sheet(pngs[k:k + per_sheet],
                              [f"{m['id']}  {fmt_secs(m['t0'])}  {m['kind']}" for m in chunk])
        p = folder / f"sheet_v{n:03d}_{k // per_sheet + 1}.png"
        p.write_bytes(sheet)
        out.append(str(p.relative_to(project.dir)))
    return out


def slide_stills(project: Project, ids: list, limit: int = 12) -> dict:
    """1280x720 stills of the given slides near their end, for Claude to see."""
    if not find_chrome():
        return {}
    n = project.data.get("current")
    compiled = project.compile()
    ends = end_times(compiled)
    ids = [i for i in ids if i in ends][:limit]
    if not ids:
        return {}
    page = write_page(project, compiled, "render", f"render_v{n:03d}.html")
    return dict(zip(ids, project_stills(project, compiled, page, [ends[i] for i in ids], 2 / 3)))


def project_stills(project: Project, compiled: dict, page: Path, times: list, scale: float) -> list:
    """Stills of the page at these times, with the presenter put in where it shows."""
    pngs = render_stills(page, times, scale)
    plan = project.host_plan(compiled, scale)
    if not plan:
        return pngs
    return [composite_host(png, t, plan["windows"], plan["segments"], plan["focus"]) for png, t in zip(pngs, times)]


# ---------------------------------------------------------------------------
# Rendering: headless Chrome over the DevTools protocol, ffmpeg in chunks
# ---------------------------------------------------------------------------

def find_chrome() -> "tuple[str, bool] | None":
    """(executable, needs --headless=new). Prefers Playwright's headless shell."""
    env = os.getenv("SCRIPTCRAFT_CHROME", "").strip()
    if env and Path(env).is_file():
        return env, "headless" not in Path(env).name.lower()
    pats = ["~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell",
            "~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell"]
    for pat in pats:
        found = sorted(glob.glob(os.path.expanduser(pat)),
                       key=lambda p: int(re.search(r"shell-(\d+)", p).group(1)) if re.search(r"shell-(\d+)", p) else 0,
                       reverse=True)
        if found:
            return found[0], False
    for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Chromium.app/Contents/MacOS/Chromium"):
        if Path(p).is_file():
            return p, True
    for name in ("chrome-headless-shell", "chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        w = shutil.which(name)
        if w:
            return w, "headless-shell" not in name
    return None


class _Chrome:
    """A headless Chrome page driven over the DevTools protocol."""

    def __init__(self, exe: str, headless_new: bool):
        self.exe, self.headless_new = exe, headless_new
        self.n = 0

    async def __aenter__(self):
        import websockets
        self.ud = tempfile.mkdtemp(prefix="xv-chrome-")
        args = [self.exe, "--remote-debugging-port=0", f"--user-data-dir={self.ud}", "--hide-scrollbars",
                "--force-color-profile=srgb", "--mute-audio", "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", "--disable-background-networking", "--disable-gpu",
                "--allow-file-access-from-files", "about:blank"]
        if self.headless_new:
            args.insert(1, "--headless=new")
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = Path(self.ud) / "DevToolsActivePort"
        for _ in range(300):
            if port_file.is_file() and len(port_file.read_text().split()) >= 2:
                break
            if self.proc.poll() is not None:
                raise RuntimeError("Chrome exited at startup")
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("Chrome did not start")
        port, path = port_file.read_text().split()[:2]
        self.ws = await websockets.connect(f"ws://127.0.0.1:{port}{path}", max_size=None, ping_interval=None)
        target = await self.call("Target.createTarget", {"url": "about:blank"})
        self.session = (await self.call("Target.attachToTarget",
                                        {"targetId": target["targetId"], "flatten": True}))["sessionId"]
        return self

    async def __aexit__(self, *exc):
        try:
            await self.ws.close()
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        shutil.rmtree(self.ud, ignore_errors=True)

    async def call(self, method: str, params: Optional[dict] = None, page: bool = False):
        self.n += 1
        msg = {"id": self.n, "method": method, "params": params or {}}
        if page:
            msg["sessionId"] = self.session
        await self.ws.send(json.dumps(msg))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get("id") == self.n:
                if "error" in r:
                    raise RuntimeError(f"Chrome {method}: {r['error'].get('message')}")
                return r.get("result") or {}

    async def evaluate(self, expr: str, await_promise: bool = False):
        r = await self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                                 "awaitPromise": await_promise}, page=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(f"page error: {r['exceptionDetails'].get('text')}")
        return (r.get("result") or {}).get("value")

    async def open(self, page_path: Path, scale: float, transparent: bool = False):
        await self.call("Emulation.setDeviceMetricsOverride",
                        {"width": STAGE_W, "height": STAGE_H, "deviceScaleFactor": scale, "mobile": False}, page=True)
        if transparent:
            await self.call("Emulation.setDefaultBackgroundColorOverride",
                            {"color": {"r": 0, "g": 0, "b": 0, "a": 0}}, page=True)
        await self.call("Page.enable", {}, page=True)
        await self.call("Page.navigate", {"url": Path(page_path).resolve().as_uri()}, page=True)
        for _ in range(400):
            if await self.evaluate("document.readyState") == "complete" and await self.evaluate("!!window.__ready"):
                break
            await asyncio.sleep(0.05)
        await self.evaluate("window.__ready", await_promise=True)

    async def frame(self, t: float) -> bytes:
        await self.evaluate(f"window.__seek({t:.4f})")
        r = await self.call("Page.captureScreenshot", {"format": "png", "optimizeForSpeed": True,
                                                        "fromSurface": True, "captureBeyondViewport": False}, page=True)
        return base64.b64decode(r["data"])


def _x264_cmd(out: Path, crf: int, host: Optional[dict] = None, a_t: float = 0.0, b_t: float = 0.0) -> list:
    """ffmpeg reading PNG frames on stdin; with a presenter plan, the footage
    goes under the frames (see _host_filter)."""
    # Chrome writes RGB PNGs for opaque frames and RGBA where the presenter
    # shows through. Rebuilding the filter graph on that switch would restart
    # the footage's timing (or wait forever once its stretch has ended), so the
    # graph stays as it is and the scale filter converts each frame.
    head = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
            "-c:v", "png", "-reinit_filter", "0", "-i", "-"]
    tail = ["-c:v", "libx264", "-preset", "faster", "-crf", str(crf),
            "-x264-params", "aq-mode=3:rc-lookahead=12", "-threads", "3",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", str(out)]
    if host and any(w["t1"] > a_t and w["t0"] < b_t for w in host["windows"]):
        inputs, graph = _host_filter(host, a_t, b_t)
        return head + inputs + ["-filter_complex", graph, "-map", "[v]"] + tail
    return head + ["-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"] + tail


async def _render_chunk_async(page: Path, f0: int, f1: int, scale: float, out: Path, crf: int,
                              exe: str, headless_new: bool, host: Optional[dict] = None) -> None:
    import queue as _queue
    part = out.with_suffix(".part.mp4")
    # ffmpeg's messages go to a file: an unread pipe that fills up would stall it.
    errlog = open(out.with_suffix(".log"), "w+b")
    ff = subprocess.Popen(_x264_cmd(part, crf, host, f0 / FPS, f1 / FPS), stdin=subprocess.PIPE, stderr=errlog)
    q: "_queue.Queue" = _queue.Queue(maxsize=12)
    err: list = []

    def writer():
        while True:
            b = q.get()
            if b is None:
                break
            try:
                ff.stdin.write(b)
            except Exception as e:  # ffmpeg died
                err.append(e)
                break

    th = threading.Thread(target=writer, daemon=True)
    th.start()
    loop = asyncio.get_running_loop()
    try:
        async with _Chrome(exe, headless_new) as ch:
            await ch.open(page, scale, transparent=bool(host))
            for f in range(f0, f1):
                png = await ch.frame(f / FPS)
                await loop.run_in_executor(None, q.put, png)
                if err:
                    break
                if (f - f0) % 5 == 4 or f == f1 - 1:
                    print(f"F {f - f0 + 1}", flush=True)
    except BaseException:
        ff.kill()
        try:
            q.put_nowait(None)
        except _queue.Full:
            pass
        raise
    q.put(None)
    th.join()
    ff.stdin.close()
    rc = ff.wait()
    errlog.seek(0)
    msg = errlog.read().decode(errors="ignore")
    errlog.close()
    if rc != 0 or err:
        raise RuntimeError(f"ffmpeg failed: {msg.strip()[-300:]}")
    part.replace(out)


def render_video(project: Project, page: Path, *, start: float, end: float, scale: float, crf: int,
                 out: Path, status: Callable, cancel: threading.Event, label: str,
                 progress_span=(0.0, 1.0), host: Optional[dict] = None) -> Path:
    """Render [start, end) of the page in parallel chunk workers (with the
    presenter under it when `host` is a presenter plan), join them and mux
    the normalized narration."""
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("Rendering needs Chrome or Chromium. Install Google Chrome, or run "
                           "`npx playwright install chromium-headless-shell`.")
    exe, headless_new = chrome
    f_a, f_b = int(round(start * FPS)), int(round(end * FPS))
    frames = max(1, f_b - f_a)
    workers = max(1, min(RENDER_WORKERS, frames // 60 or 1))
    bounds = [f_a + round(frames * k / workers) for k in range(workers + 1)]
    work = Path(tempfile.mkdtemp(prefix="xv-render-", dir=str(project.dir)))
    procs, done = [], [0] * workers
    lo, hi = progress_span
    t0 = time.time()
    try:
        host_file = None
        if host:
            host_file = work / "host.json"
            host_file.write_text(json.dumps(host), encoding="utf-8")
        for k in range(workers):
            cmd = [sys.executable, str(Path(__file__).resolve()), "render-chunk", "--page", str(page),
                   "--from", str(bounds[k]), "--to", str(bounds[k + 1]), "--scale", str(scale),
                   "--crf", str(crf), "--out", str(work / f"chunk_{k:02d}.mp4"), "--chrome", exe]
            if headless_new:
                cmd.append("--headless-new")
            if host_file:
                cmd += ["--host", str(host_file)]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            procs.append(p)
            _register_proc(project.id, p)

        def read(k, p):
            for line in p.stdout:
                if line.startswith("F "):
                    done[k] = int(line.split()[1])

        readers = [threading.Thread(target=read, args=(k, p), daemon=True) for k, p in enumerate(procs)]
        for r in readers:
            r.start()
        while any(p.poll() is None for p in procs):
            if cancel.is_set():
                for p in procs:
                    p.terminate()
                raise Cancelled()
            n = sum(done)
            el = time.time() - t0
            eta = (el / n * (frames - n)) if n > 30 else None
            status(message=f"{label}: frame {n:,} of {frames:,} ({workers} workers"
                           + (f", ~{fmt_secs(eta)} left)" if eta else ")"),
                   progress=lo + (hi - lo) * 0.92 * n / frames)
            time.sleep(0.5)
        for r in readers:
            r.join(timeout=2)
        for k, p in enumerate(procs):
            if p.returncode != 0:
                if cancel.is_set():
                    raise Cancelled()
                raise RuntimeError(f"render worker {k + 1} failed: {(p.stderr.read() or '').strip()[-400:]}")
        chunks = [work / f"chunk_{k:02d}.mp4" for k in range(workers)]
        missing = [c.name for c in chunks if not c.is_file()]
        if missing:
            raise RuntimeError(f"render chunks missing: {', '.join(missing)}")
        status(message=f"{label}: joining {workers} chunks and adding the narration…",
               progress=lo + (hi - lo) * 0.95)
        lst = work / "chunks.txt"
        lst.write_text("".join(f"file '{c}'\n" for c in chunks), encoding="utf-8")
        video = work / "video.mp4"
        _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
              "-i", str(lst), "-c", "copy", str(video)])
        dur = frames / FPS
        yclips = clip_render_plan(project, start, start + dur)
        if yclips:
            # The narration keeps the clock: a short clip holds its last frame,
            # a long one is trimmed to the slide. This re-encodes the joined picture.
            status(message=f"{label}: fitting YouTube clips into the frame…",
                   progress=lo + (hi - lo) * 0.97)
            laid = work / "with_clips.mp4"
            _run(build_overlay_cmd(video, laid, yclips, int(round(STAGE_W * scale)),
                                   int(round(STAGE_H * scale)), crf=crf))
            video = laid
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".part.mp4")
        _run(build_mux_cmd(video, project.dir / "narration.wav", tmp, start, dur, yclips))
        tmp.replace(out)
        return out
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
        shutil.rmtree(work, ignore_errors=True)


async def _stills_async(page: Path, times: list, scale: float) -> list:
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("Stills need Chrome or Chromium installed.")
    async with _Chrome(*chrome) as ch:
        await ch.open(page, scale, transparent=True)
        return [await ch.frame(t) for t in times]


def render_stills(page: Path, times: list, scale: float = 1.0) -> list:
    return asyncio.run(_stills_async(page, times, scale))


def contact_sheet(pngs: list, labels: list, cols: int = 4, width: int = 480) -> bytes:
    from PIL import Image, ImageDraw
    h = width * 9 // 16
    rows = (len(pngs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (width + 12) + 12, rows * (h + 44) + 12), (15, 18, 26))
    draw = ImageDraw.Draw(sheet)
    for i, (png, lab) in enumerate(zip(pngs, labels)):
        im = Image.open(io.BytesIO(png)).convert("RGB")
        im.thumbnail((width, h), Image.LANCZOS)
        x, y = 12 + (i % cols) * (width + 12), 12 + (i // cols) * (h + 44)
        sheet.paste(im, (x, y))
        draw.text((x + 2, y + h + 8), lab[:70], fill=(200, 206, 216))
    buf = io.BytesIO()
    sheet.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def audio_levels(path: Path) -> dict:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True, timeout=600)
    mean = re.search(r"mean_volume:\s*(-?[\d.]+)", r.stderr)
    peak = re.search(r"max_volume:\s*(-?[\d.]+)", r.stderr)
    return {"mean_db": float(mean.group(1)) if mean else None, "max_db": float(peak.group(1)) if peak else None}


def phone_copy(src: Path, out: Path) -> Path:
    tmp = out.with_suffix(".part.mp4")
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
          "-vf", "scale=1280:720:flags=lanczos", "-c:v", "libx264", "-profile:v", "main", "-preset", "medium",
          "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(tmp)])
    tmp.replace(out)
    return out


def write_page(project: Project, compiled: dict, mode: str, name: str) -> Path:
    page = project.dir / "pages" / name
    page.parent.mkdir(parents=True, exist_ok=True)
    host = project.host()
    frame, bubble = look_of(project.data, host)
    style = visual_style_key(None, project.data.get("visual_style"))
    page.write_text(page_html(compiled, mode=mode, title=project.data.get("title") or "Explainer",
                              host=host, pip_frame=frame, bubble=bubble,
                              visual={"style": style},
                              demos=demo_payloads(compiled, load_youtube(project.data)["clips"], mode)),
                    encoding="utf-8")
    return page


def _cli(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="explainer_video")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rc = sub.add_parser("render-chunk")
    rc.add_argument("--page", required=True)
    rc.add_argument("--from", dest="f0", type=int, required=True)
    rc.add_argument("--to", dest="f1", type=int, required=True)
    rc.add_argument("--scale", type=float, default=1.0)
    rc.add_argument("--crf", type=int, default=17)
    rc.add_argument("--out", required=True)
    rc.add_argument("--chrome", required=True)
    rc.add_argument("--headless-new", action="store_true")
    rc.add_argument("--host", default="")
    a = ap.parse_args(argv)
    host = json.loads(Path(a.host).read_text(encoding="utf-8")) if a.host else None
    asyncio.run(_render_chunk_async(Path(a.page), a.f0, a.f1, a.scale, Path(a.out), a.crf,
                                    a.chrome, a.headless_new, host))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
