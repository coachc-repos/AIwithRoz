#!/usr/bin/env python3
"""YouTube thumbnails in the channel's own style, rendered by Grok Imagine.

The channel's best thumbnails live in thumbnail_refs/ and are described in
thumbnail_refs/refs.json. Each thumbnail is made in two steps:

1. Claude, as art director, turns the topic, the hook text and the script into
   a concept that follows one of the channel's proven layouts (big number,
   headline text, public figure, mystery scene, comparison).
2. Grok Imagine (grok-imagine-image-2.0, multi-image editing, up to 5 source
   images per request) renders the concept from 2 references that show the
   host's face, matched to the planned expression, and up to 2 references that
   show the planned layout. The host stays recognizable and the result looks
   like the channel's other thumbnails.

The interface matches EmotionalThumbnailGenerator (Gemini), so the GUI can use
either one: generate_all_thumbnails(...) returns
{"script_title", "variations": [...], "output_dir", "total_attempted", "cancelled"}.

Each thumbnail is saved twice: a 1280x720 PNG for YouTube (under its 2 MB
limit) in the output folder, and the full-resolution original in full/, next
to a JSON file with every concept, prompt and reference used.

edit_thumbnail() changes an existing thumbnail (a generated one, one of the
references, or any image) with a plain-language prompt such as "change the 3
to a 9" or "use Elon Musk instead of Roz", keeping everything else, and saves
the result as a new file. An edit that mentions Roz also sends her reference
photos, so she stays recognizable.

    python tools/media/grok_thumbnail_generator.py "Topic" --hook "CHIP WAR" -n 2
    python tools/media/grok_thumbnail_generator.py --edit thumbnail_refs/3_gold_neon.jpg "change the 3! to a 9"
"""
from __future__ import annotations

import base64
import concurrent.futures
import io
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

REFS_DIR = Path(__file__).parent / "thumbnail_refs"
IMAGE_MODEL = os.getenv("GROK_THUMBNAIL_MODEL", "grok-imagine-image-2.0")
FALLBACK_IMAGE_MODEL = os.getenv("GROK_THUMBNAIL_FALLBACK_MODEL", "grok-imagine-image-pro")
CONCEPT_MODEL = os.getenv("THUMBNAIL_CONCEPT_MODEL", "claude-opus-5-5")
MAX_SOURCE_IMAGES = 5       # xAI allows up to 5 source images per request
MAX_REFERENCES = 4          # references per new thumbnail
MAX_INCLUDES = 3            # images (logos etc.) added by one edit
YOUTUBE_SIZE = (1280, 720)
YOUTUBE_MAX_BYTES = 2 * 1024 * 1024 - 64 * 1024   # keep the 1280x720 copy small (YouTube now takes up to 50 MB)
DEFAULT_PER_OPTION = 2      # thumbnails per hook text when the caller doesn't say
MAX_PARALLEL = 3            # concurrent Grok renders

HOST_LOOK = ("jet-black asymmetric undercut pixie haircut with a long side-swept fringe and a "
             "shaved side, green-hazel eyes, defined dark brows, black crew-neck t-shirt, dark "
             "nail polish")

LAYOUTS = {
    "big_number": "a giant number or stat in extra-bold sans-serif (white with a red outer glow, "
                  "or 3D gold with a red neon inlay) fills one side; the host points at it from "
                  "the other side",
    "headline_text": "a short punch phrase of 1 to 3 words in huge white extra-bold letters (one "
                     "key word may be yellow) dominates the frame; the host reacts beside it",
    "public_figure": "a recognizable public figure from the episode, lit by a spotlight from above "
                     "against deep blue, looking up or in profile, on one side; the host on the "
                     "other side against red, pointing or reacting",
    "mystery_scene": "a dramatic dark scene (silhouetted figures in a red-and-blue lit alley, or "
                     "hooded figures with glowing red eyes in a closet) on one side; the host on "
                     "the other side, uneasy, pointing at it or peeking in",
    "comparison": "a split-screen comparison down the middle (real versus AI, before versus "
                  "after) with a short question in huge letters across the top; the host beside "
                  "it with a knowing look",
}
LAYOUT_LABELS = {"big_number": "Big number", "headline_text": "Headline", "public_figure":
                 "Public figure", "mystery_scene": "Mystery scene", "comparison": "Comparison"}

EXPRESSIONS = {
    "shocked": "shocked: eyes wide, eyebrows raised, mouth open",
    "smirk": "a knowing, confident smirk",
    "smile": "a warm, confident smile",
    "worried": "worried and uneasy: brow furrowed, lips slightly parted",
    "skeptical": "skeptical: one eyebrow raised, lips pressed together",
}

STYLE_GUIDE = f"""The channel's thumbnails share one look:
- 16:9, photographic and cinematic, high contrast, crisp studio light on the host's face. Clean and uncluttered: the host plus ONE hero element, and at most one small supporting element.
- The host appears in every thumbnail: the woman in the references ({HOST_LOOK}). She is framed from the chest or waist up, large in frame (about a third of the width), usually on the right third, sometimes the left.
- Her expressions are exaggerated so they read at small size: shocked, knowing smirk, warm smile, worried, skeptical.
- Her gestures: pointing her index finger at the hero element (most common), pointing up, peeking around a door or through torn paper, holding a small object toward the camera.
- Hero elements: a giant number or stat ("62%", "3!", "$15.9 BILLION!?"); a 1 to 3 word punch phrase ("PAID TO PANIC", "REAL or AI?"); a public figure spotlit against blue; a dramatic dark scene (silhouettes in an alley, hooded figures with glowing red eyes); a symbolic object (silicon wafer, gold bar, money arrow, glowing chip).
- Backgrounds: deep crimson-red gradient (the default), a red-to-blue split when two sides face off, dark navy with torn-paper holes edged in red glow, a dark red-to-teal gradient with faint glitchy code lines (tech going wrong), or a dark scene lit red and blue. Neon green means growth or money.
- Text: at most one text element of 1 to 3 words or one number, huge and perfectly spelled. Nothing else written anywhere: no captions, watermarks or logos.
- What earns the most clicks on this channel: a giant 3D gold number with a red neon inlay on crimson beside a recognizable public figure or the host (the "4" beside Musk for "Musk Will Win the AI Race - Here is Why"), and a public figure under a blue spotlight split against the host on red. The text states the verdict or the conflict, not the topic. Neutral explainer looks ("BROKEN?" over a gadget) draw fewer clicks."""

CONCEPT_SYSTEM = f"""You are the art director for the @AIwithRoz YouTube channel. You plan thumbnails that earn the click and look exactly like the channel's existing ones.

{STYLE_GUIDE}

Layouts you can use:
""" + "\n".join(f"- {k}: {v}" for k, v in LAYOUTS.items()) + """

Rules:
- Use exactly these values: "layout" is one of big_number, headline_text, public_figure, mystery_scene, comparison; "expression" is one of shocked, smirk, smile, worried, skeptical; "host_side" is left or right.
- Every thumbnail features the host.
- "text" is the exact on-image text: the hook text as given when it is 4 words or fewer, otherwise its 1 to 3 most powerful words or its key number, keeping the meaning. Prefer the word or number that carries the verdict or the conflict. Use "" only when the layout works better without text.
- Never invent a statistic: a number in "text" must appear in the hook text, the title or the script.
- Use public_figure only for a real person the topic or title names. Show them as a dignified, recognizable portrait (spotlit, looking up, or in profile). Never show a real person in a demeaning, violent, sexual or criminal-looking scene, or endorsing anything.
- No brand logos.
- Make the thumbnails for one hook text clearly different from each other: vary the layout, the expression and the side.

Reply with JSON only, no prose and no code fences:
{"concepts": [{"option_index": 1, "layout": "big_number", "text": "62%", "host_side": "right", "expression": "shocked", "gesture": "pointing her index finger at the number", "hero": "concrete description of the hero element", "support": "small supporting element, or an empty string", "background": "deep crimson-red gradient, darker toward the left edge", "why": "one line on why this earns the click"}]}
"""


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------
def load_references(refs_dir: Path = REFS_DIR) -> list[dict]:
    """The described references, plus any undescribed image in the folder (layout-only)."""
    refs, listed = [], set()
    manifest = refs_dir / "refs.json"
    if manifest.exists():
        for r in json.loads(manifest.read_text(encoding="utf-8")).get("refs", []):
            if (refs_dir / r.get("file", "")).is_file():
                refs.append({"file": r["file"], "layouts": r.get("layouts", []),
                             "host": bool(r.get("host")), "expression": r.get("expression", ""),
                             "description": r.get("description", "")})
                listed.add(r["file"])
    for p in sorted(refs_dir.glob("*")):
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and p.name not in listed:
            refs.append({"file": p.name, "layouts": [], "host": False, "expression": "",
                         "description": ""})
    return refs


def pick_references(concept: dict, refs: list[dict], max_refs: int = MAX_REFERENCES,
                    min_refs: int = 3) -> list[dict]:
    """2 references that show the host (planned expression first), then layout references,
    topped up to min_refs with more host references so her likeness stays well anchored."""
    expr, layout = concept.get("expression"), concept.get("layout")
    hosts = [r for r in refs if r["host"]]
    hosts.sort(key=lambda r: (r["expression"] != expr, layout not in r["layouts"]))
    chosen = hosts[:2]
    for r in refs:
        if len(chosen) >= max_refs:
            break
        if layout in r["layouts"] and r not in chosen:
            chosen.append(r)
    for r in hosts:
        if len(chosen) >= min(min_refs, max_refs):
            break
        if r not in chosen:
            chosen.append(r)
    return chosen[:max_refs]


def _data_uri(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def _source_data_uri(path: Path, max_width: int = 2048) -> str:
    """An image to edit, as a JPEG data URI no wider than max_width. A 2k PNG
    thumbnail is several MB, too heavy to send as base64."""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)),
                         Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _include_data_uri(data: bytes, max_side: int = 1024) -> str:
    """An image to add to a thumbnail (a logo, a product shot) as a data URI no
    larger than max_side. Transparency is kept (PNG), so a logo doesn't arrive
    on a black or white box."""
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    img.load()
    has_alpha = img.mode in ("RGBA", "LA", "P") and (
        img.mode != "P" or "transparency" in img.info)
    img = img.convert("RGBA" if has_alpha else "RGB")
    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    if has_alpha:
        img.save(buf, "PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    img.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# Concepts
# ---------------------------------------------------------------------------
# Claude sometimes answers "knowing smirk" or "big number" instead of the exact keys.
_EXPRESSION_WORDS = [
    ("smirk", ("smirk", "knowing", "sly", "wry")),
    ("smile", ("smile", "grin", "happy", "warm")),
    ("worried", ("worr", "uneasy", "nervous", "anxious", "afraid", "scared", "fear", "concern")),
    ("skeptical", ("skept", "doubt", "suspicious", "unconvinced", "raised eyebrow")),
    ("shocked", ("shock", "surpris", "stun", "amaz", "astonish", "wide-eyed", "open mouth")),
]
_LAYOUT_WORDS = [
    ("big_number", ("number", "stat", "digit", "percent")),
    ("public_figure", ("figure", "portrait", "person", "celebrity")),
    ("mystery_scene", ("mystery", "scene", "silhouette", "hooded")),
    ("comparison", ("compar", "split", "versus", " vs")),
    ("headline_text", ("headline", "text", "phrase", "word")),
]


def _normalize(value, keys, words, default):
    v = str(value or "").strip().lower()
    if v in keys:
        return v
    v2 = re.sub(r"[\s-]+", "_", v)
    if v2 in keys:
        return v2
    for key, hints in words:
        if any(h in v for h in hints):
            return key
    return default


def _clean_concept(c: dict, option_index: int, hook: str) -> dict:
    layout = _normalize(c.get("layout"), LAYOUTS, _LAYOUT_WORDS, "headline_text")
    expr = _normalize(c.get("expression"), EXPRESSIONS, _EXPRESSION_WORDS, "shocked")
    side = "left" if str(c.get("host_side", "")).lower() == "left" else "right"
    raw = c.get("text")
    text = (" ".join((hook or "").split()[:4]) if raw is None else str(raw)).strip().strip('"')
    return {
        "option_index": option_index,
        "layout": layout,
        "text": text[:40],
        "host_side": side,
        "expression": expr,
        "gesture": str(c.get("gesture") or "pointing her index finger at the hero element"),
        "hero": str(c.get("hero") or LAYOUTS[layout]),
        "support": str(c.get("support") or ""),
        "background": str(c.get("background") or "deep crimson-red gradient"),
        "why": str(c.get("why") or ""),
    }


def fallback_concepts(options: list, per_option: int) -> list[dict]:
    """Concepts without Claude: rotate layouts, expressions and sides for each hook."""
    out = []
    for oi, hook in enumerate(options, 1):
        words = (hook or "").split()
        text = " ".join(words[:4]).upper()
        has_number = any(ch.isdigit() for ch in text)
        plan = [("big_number" if has_number else "headline_text", "shocked", "right"),
                ("headline_text", "smirk", "right"), ("mystery_scene", "worried", "right"),
                ("comparison", "skeptical", "left")]
        for k in range(per_option):
            layout, expr, side = plan[k % len(plan)]
            out.append(_clean_concept({"layout": layout, "text": text, "expression": expr,
                                       "host_side": side}, oi, text))
    return out


def plan_concepts(title: str, options: list, per_option: int, script_excerpt: str = "",
                  log=print) -> list[dict]:
    """Ask Claude for per_option concepts per hook text; fall back to rotation on any failure."""
    try:
        import anthropic
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        hooks = "\n".join(f"{i}. {h or '(no hook text: choose from the title and script)'}"
                          for i, h in enumerate(options, 1))
        user = (f"Video title / topic: {title}\n\nHook texts:\n{hooks}\n\n"
                f"Plan {per_option} thumbnail concept(s) for EACH hook text "
                f"({per_option * len(options)} in all); set option_index to the hook's number.")
        if script_excerpt:
            user += f"\n\nScript excerpt (for context and real numbers only):\n{script_excerpt[:4000]}"
        resp = anthropic.Anthropic(api_key=key, timeout=120).messages.create(
            model=CONCEPT_MODEL, max_tokens=4000, system=CONCEPT_SYSTEM,
            messages=[{"role": "user", "content": user}])
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
        concepts = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])["concepts"]
        out = []
        for oi, hook in enumerate(options, 1):
            mine = [c for c in concepts if int(c.get("option_index") or 0) == oi][:per_option]
            mine += [{}] * (per_option - len(mine))       # pad if Claude came up short
            out += [_clean_concept(c, oi, hook or "") for c in mine]
        return out
    except Exception as e:
        log(f"   ⚠️ Concept planning with Claude failed ({e}); using the built-in layouts")
        return fallback_concepts(options, per_option)


def build_render_prompt(concept: dict) -> str:
    side = concept["host_side"]
    other = "left" if side == "right" else "right"
    text = concept["text"]
    text_rule = (f'The only text in the image is "{text}", spelled exactly like that, huge, bold and '
                 f'fully visible.' if text else "There is no text anywhere in the image.")
    support = f" Supporting element: {concept['support']}." if concept["support"] else ""
    return (
        "Create a NEW YouTube thumbnail (16:9) in exactly the visual style of the reference "
        "thumbnails. Use the references only for the woman's identity and for the channel's style "
        "(lighting, colors, typography, composition); do not copy their objects, people, scenes "
        "or text. Feature the SAME woman shown in the references, with an identical face and "
        f"features: {HOST_LOOK}. Place her on the {side} third, framed from the chest up, large in "
        f"frame, with {EXPRESSIONS[concept['expression']]}, {concept['gesture']}. "
        f"Layout: {LAYOUTS[concept['layout']]}. On the {other} side: {concept['hero']}.{support} "
        f"{text_rule} Background: {concept['background']}. High contrast, crisp studio lighting "
        "on her face, cinematic and uncluttered. No logos, no watermarks, no other words."
    )


# An edit that names the host gets her reference photos too, so she stays recognizable.
_MENTIONS_HOST_RE = re.compile(r"\b(roz|host)\b", re.IGNORECASE)


def build_edit_prompt(instruction: str, host_ref_count: int, include_count: int = 0) -> str:
    """The prompt for one edit of an existing thumbnail. Images are sent in this order:
    the thumbnail, then include_count images to add (logos etc.), then Roz's references."""
    prompt = (
        "Edit the FIRST image, a YouTube thumbnail. Make only this change: "
        f"{instruction.strip()}\n"
        "Keep everything else exactly as it is: the composition and framing, the background, "
        "lighting and colors, the style, size and placement of any text, and every person and "
        "object the change does not mention. Spell any new or changed text exactly as written "
        "in the change. Keep it a 16:9 photographic thumbnail with high contrast."
    )
    if include_count:
        which = ("The 2nd image is" if include_count == 1
                 else f"Images 2 to {include_count + 1} are")
        prompt += (f" {which} supplied to be added to the thumbnail as the change describes "
                   "(for example a logo). Reproduce each one faithfully, with the same shapes, "
                   "colors and lettering, lit to match the scene. If the change doesn't say "
                   "where, place it prominently without covering a face or the main text.")
    if host_ref_count:
        which = ("The last image shows" if host_ref_count == 1
                 else f"The last {host_ref_count} images show")
        prompt += (f" {which} Roz, the channel's host ({HOST_LOOK}). Wherever Roz or the host "
                   "appears in the result, she must look exactly like her.")
    return prompt


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------
class GrokThumbnailGenerator:
    """Thumbnails in the channel's style: Claude concepts, Grok Imagine renders."""

    engine = "grok"

    def __init__(self, api_key=None, output_dir=None, model=None, refs_dir: Path = REFS_DIR):
        self.api_key = (api_key or os.getenv("XAI_API_KEY") or "").strip()
        if not self.api_key:
            raise RuntimeError("XAI_API_KEY is not set")
        self.model = model or IMAGE_MODEL
        self.refs_dir = Path(refs_dir)
        self.refs = load_references(self.refs_dir)
        if not any(r["host"] for r in self.refs):
            raise RuntimeError(f"No host references in {self.refs_dir}")
        self.template_path = str(self.refs_dir)   # logged by the GUI
        self.output_dir = Path(output_dir or os.path.expanduser("~/Dev/Thumbnails"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        from xai_sdk import Client
        self.client = Client(api_key=self.api_key)

    def render(self, prompt: str, refs: list[dict]) -> tuple[bytes, str]:
        """PNG bytes and the model that made them. Tries the fallback model once."""
        return self._sample(prompt, [_data_uri(self.refs_dir / r["file"]) for r in refs])

    def _sample(self, prompt: str, uris: list[str]) -> tuple[bytes, str]:
        last = None
        for model in dict.fromkeys([self.model, FALLBACK_IMAGE_MODEL]):
            try:
                resp = self.client.image.sample(
                    prompt=prompt, model=model, image_urls=uris, image_format="base64",
                    aspect_ratio="16:9", resolution="2k")
                return resp.image, model
            except Exception as e:
                last = e
                if "moderation" in str(e).lower():
                    break                      # the same prompt won't pass on another model
        raise last

    @staticmethod
    def _save(data: bytes, out_dir: Path, stem: str) -> tuple[Path, Path]:
        """Save the full-resolution original in out_dir/full/ and a 1280x720 copy for
        YouTube in out_dir. Returns (youtube_copy, full_resolution)."""
        from PIL import Image, ImageOps
        full_dir = out_dir / "full"
        full_dir.mkdir(parents=True, exist_ok=True)
        # The full-resolution copy gets its own name: the GUI finds thumbnails by
        # file name anywhere under the output folder.
        full_path = full_dir / f"{stem}_full.png"
        full_path.write_bytes(data)
        img = ImageOps.fit(Image.open(io.BytesIO(data)).convert("RGB"), YOUTUBE_SIZE,
                           Image.Resampling.LANCZOS)
        path = out_dir / f"{stem}.png"
        img.save(path, "PNG", optimize=True)
        if path.stat().st_size > YOUTUBE_MAX_BYTES:      # a big PNG: save a JPEG instead
            path.unlink()
            path = out_dir / f"{stem}.jpg"
            img.save(path, "JPEG", quality=92, optimize=True)
        return path, full_path

    def edit_thumbnail(self, source_path, instruction: str, out_dir=None,
                       include_images=None) -> dict:
        """Apply one prompt edit ("change the 3 to a 9", "use Elon Musk instead of Roz") to
        an existing thumbnail and save the result as a new file; the source is untouched.
        include_images: up to MAX_INCLUDES images (bytes, e.g. a logo) to add to it.
        Returns the new thumbnail in the same shape as a generated variation."""
        source = Path(source_path)
        instruction = (instruction or "").strip()
        includes = list(include_images or [])
        if not source.is_file():
            raise FileNotFoundError(f"Thumbnail not found: {source.name}")
        if not instruction:
            raise ValueError("Describe the change to make")
        if len(includes) > MAX_INCLUDES:
            raise ValueError(f"Include at most {MAX_INCLUDES} images per edit")
        # Up to MAX_SOURCE_IMAGES go in: the thumbnail, the includes, then Roz's references.
        room = MAX_SOURCE_IMAGES - 1 - len(includes)
        host_refs = ([r for r in self.refs if r["host"]][:min(2, room)]
                     if _MENTIONS_HOST_RE.search(instruction) else [])
        prompt = build_edit_prompt(instruction, len(host_refs), len(includes))
        uris = ([_source_data_uri(source)] + [_include_data_uri(b) for b in includes]
                + [_data_uri(self.refs_dir / r["file"]) for r in host_refs])
        data, used_model = self._sample(prompt, uris)
        # "X_grok01_20261022_101500" -> "X_grok01_edit_<now>": a chain of edits keeps one stem.
        base = re.sub(r"_full$", "", source.stem)
        base = re.sub(r"(?:_edit)?_\d{8}_\d{6}$", "", base)[:70] or "thumbnail"
        out = Path(out_dir) if out_dir else self.output_dir / "edits"
        path, full_path = self._save(data, out, f"{base}_edit_{datetime.now():%Y%m%d_%H%M%S}")
        return {
            "number": 0, "emotion": "✏️ Edit", "text": instruction, "engine": "grok",
            "model": used_model, "instruction": instruction, "source": source.name,
            "included_images": len(includes),
            "references": [r["file"] for r in host_refs], "prompt": prompt,
            "filename": path.name, "filepath": str(path), "full_path": str(full_path),
            "dimensions": list(YOUTUBE_SIZE),
        }

    def generate_all_thumbnails(self, script_title, script_content=None, youtube_upload_details=None,
                                headline_text=None, headline_options=None,
                                progress_callback=None, cancel_check=None,
                                variations_per_option=None):
        def notify(msg):
            print(msg)
            if progress_callback:
                try:
                    progress_callback(msg)
                except Exception:
                    pass

        def cancelled():
            try:
                return bool(cancel_check and cancel_check())
            except Exception:
                return False

        options = [h for h in (headline_options or []) if str(h or "").strip()][:3]
        if not options:
            options = [headline_text] if headline_text else [None]
        per_option = variations_per_option if variations_per_option and variations_per_option > 0 \
            else DEFAULT_PER_OPTION
        safe_title = re.sub(r"[^\w\s-]", "", script_title or "thumbnail").strip().replace(" ", "_")[:60] \
            or "thumbnail"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        full_dir = self.output_dir / "full"
        full_dir.mkdir(parents=True, exist_ok=True)
        results = {"script_title": script_title, "variations": [], "output_dir": str(self.output_dir),
                   "total_attempted": 0, "cancelled": False, "engine": "grok", "errors": []}

        notify(f"🎨 Planning {per_option * len(options)} thumbnail concept(s) in the channel's style…")
        concepts = plan_concepts(script_title, options, per_option, script_content or "", log=notify)
        total = len(concepts)
        notify(f"🖼️ Rendering {total} thumbnail(s) with Grok Imagine ({self.model}), "
               f"{min(MAX_PARALLEL, total)} at a time…")
        lock = threading.Lock()

        def make(num: int, concept: dict):
            if cancelled():
                return None
            refs = pick_references(concept, self.refs)
            prompt = build_render_prompt(concept)
            label = f"{concept['expression'].upper()} · {LAYOUT_LABELS[concept['layout']]}"
            text_note = f' "{concept["text"]}"' if concept["text"] else ""
            notify(f"   🎬 Thumbnail {num}/{total}: {label}{text_note}")
            with lock:
                results["total_attempted"] += 1
            try:
                data, used_model = self.render(prompt, refs)
            except Exception as e:
                reason = ("blocked by xAI moderation" if "moderation" in str(e).lower()
                          else str(e)[:200])
                notify(f"   ❌ Thumbnail {num}/{total} failed: {reason}")
                with lock:
                    results["errors"].append({"number": num, "error": reason})
                return None
            path, full_path = self._save(data, self.output_dir, f"{safe_title}_grok{num:02d}_{stamp}")
            filename = path.name
            notify(f"   ✅ Thumbnail {num}/{total} saved: {filename}")
            hook = options[concept["option_index"] - 1] if options[0] is not None else None
            return {
                "number": num, "option_index": concept["option_index"], "headline_text": hook,
                "emotion": label, "text": concept["text"],
                "expression": EXPRESSIONS[concept["expression"]],
                "outfit": "black crew-neck t-shirt", "background": concept["background"],
                "layout": concept["layout"], "engine": "grok", "model": used_model,
                "references": [r["file"] for r in refs], "why": concept["why"], "prompt": prompt,
                "filename": filename, "filepath": str(path), "full_path": str(full_path),
                "dimensions": list(YOUTUBE_SIZE),
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
            futures = [pool.submit(make, i, c) for i, c in enumerate(concepts, 1)]
            for f in futures:
                v = f.result()
                if v:
                    results["variations"].append(v)
        results["variations"].sort(key=lambda v: v["number"])
        results["cancelled"] = cancelled()
        if results["cancelled"]:
            notify(f"🛑 Thumbnail generation cancelled after {len(results['variations'])}/{total}")

        try:
            (full_dir / f"{safe_title}_grok_{stamp}_concepts.json").write_text(json.dumps({
                "title": script_title, "hooks": options, "image_model": self.model,
                "concept_model": CONCEPT_MODEL, "concepts": concepts,
                "results": results["variations"], "errors": results["errors"],
            }, indent=2), encoding="utf-8")
        except Exception:
            pass
        notify(f"✅ {len(results['variations'])}/{total} thumbnail(s) ready in {self.output_dir}")
        return results


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Channel-style thumbnails with Grok Imagine")
    ap.add_argument("title", nargs="?")
    ap.add_argument("--hook", action="append", help="hook text (repeat up to 3 times)")
    ap.add_argument("-n", type=int, default=DEFAULT_PER_OPTION, help="thumbnails per hook")
    ap.add_argument("--out", help="output folder (default ~/Dev/Thumbnails)")
    ap.add_argument("--edit", nargs=2, metavar=("IMAGE", "CHANGE"),
                    help="edit an existing thumbnail instead of generating new ones")
    ap.add_argument("--include", action="append", metavar="IMAGE",
                    help="with --edit: an image to add, e.g. a logo (repeat up to 3 times)")
    a = ap.parse_args()
    if not a.title and not a.edit:
        ap.error("give a title, or --edit IMAGE CHANGE")
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    except Exception:
        pass
    gen = GrokThumbnailGenerator(output_dir=a.out)
    if a.edit:
        v = gen.edit_thumbnail(a.edit[0], a.edit[1],
                               include_images=[Path(p).read_bytes() for p in a.include or []])
        print(f"✏️  {v['filepath']}  (full size: {v['full_path']})")
        return
    res = gen.generate_all_thumbnails(a.title, headline_options=a.hook, variations_per_option=a.n)
    for v in res["variations"]:
        print(f"{v['number']:>2}. {v['emotion']:<28} {v['text']!r:<24} {v['filepath']}")


if __name__ == "__main__":
    main()
