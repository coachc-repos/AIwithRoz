#!/usr/bin/env python3
"""
ScriptCraft Web GUI - Clean Console Capture Version
Fixed implementation that displays real-time EnhancedAutoGenSystem messages in browser
"""

# CRITICAL: Add repo root to path FIRST (before any other imports)
import queue as _queue
import threading as _threading
import re
import os
import json
import time
import queue
import uuid
import asyncio
import threading
import logging
import urllib.parse
from datetime import datetime
from io import BytesIO
from flask import Flask, render_template, request, jsonify, Response, make_response, send_file, stream_with_context
import requests
import sys
from pathlib import Path
from typing import Optional

# Add paths for imports - prioritize local scriptcraft-app directory
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))  # Prioritize local directory FIRST
print(f"✅ Prioritized local dir in sys.path: {current_dir}")

REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    # Add parent as backup (position 1, not 0)
    sys.path.insert(1, str(REPO_ROOT))
    print(f"✅ Added to sys.path: {REPO_ROOT}")

# Load all API keys from the single root .env (GOOGLE_API_KEY, XAI_API_KEY,
# HEYGEN_API_KEY, HEYGEN_VOICE_ID, X_* ...). Does not override anything already
# set in the real environment, so per-shell overrides still win.
try:
    from dotenv import load_dotenv
    _env_file = REPO_ROOT / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
        print(f"🔧 Loaded environment variables from {_env_file}")
except ImportError:
    pass  # python-dotenv not installed; rely on the real environment


VERSION = "15.34-quotes-progress-mapping"

# Verify Google API key availability for thumbnail generation.
if "GOOGLE_API_KEY" in os.environ and os.environ.get("GOOGLE_API_KEY"):
    print("🔑 Using GOOGLE_API_KEY from environment")
else:
    print("⚠️ GOOGLE_API_KEY is not set; thumbnail generation will fail until provided")


# Set up logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SCRIPTCRAFT_SETTINGS_PATH = Path.home() / ".scriptcraft" / \
    "web_gui_settings.json"
DEFAULT_OUTPUT_PARENT = Path.home() / "Dev" / "Videos" / "Edited" / "Final"


def _load_scriptcraft_settings() -> dict:
    try:
        if SCRIPTCRAFT_SETTINGS_PATH.exists():
            with open(SCRIPTCRAFT_SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"⚠️ Could not load ScriptCraft settings: {e}")
    return {}


def _save_scriptcraft_settings(settings: dict) -> bool:
    try:
        SCRIPTCRAFT_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SCRIPTCRAFT_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"❌ Could not save ScriptCraft settings: {e}")
        return False


# On startup, hydrate environment variables from saved settings so any module
# that reads os.getenv(...) (e.g. GOOGLE_API_KEY for Gemini) picks them up
# even when the user only set them through the API Keys modal.
def _hydrate_env_from_settings() -> None:
    try:
        s = _load_scriptcraft_settings()
        mapping = {
            "google_api_key": "GOOGLE_API_KEY",
            "heygen_api_key": "HEYGEN_API_KEY",
            "heygen_voice_id": "HEYGEN_VOICE_ID",
            "grok_api_key": "XAI_API_KEY",
            "anthropic_api_key": "ANTHROPIC_API_KEY",
        }
        for setting_key, env_var in mapping.items():
            val = (s.get(setting_key) or "").strip()
            if val and not os.environ.get(env_var):
                os.environ[env_var] = val
    except Exception as e:
        logger.warning(f"⚠️ Could not hydrate env from saved settings: {e}")


_hydrate_env_from_settings()


def _get_output_parent_dir() -> Path:
    """Return configured output directory as-is, or Final root as fallback."""
    try:
        s = _load_scriptcraft_settings()
        raw = (s.get("output_dir") or "").strip()
        base = Path(raw).expanduser().resolve(
        ) if raw else DEFAULT_OUTPUT_PARENT
    except Exception:
        base = DEFAULT_OUTPUT_PARENT
    if base.exists() and not base.is_dir():
        logger.warning(
            f"⚠️ Configured output path is not a directory: {base}. Using default.")
        base = DEFAULT_OUTPUT_PARENT
    base.mkdir(parents=True, exist_ok=True)
    return base


def _get_output_base_dir() -> Optional[Path]:
    """Back-compat helper: returns the output parent directory."""
    try:
        return _get_output_parent_dir()
    except Exception:
        return None


def _get_run_output_dir(script_title: str, create: bool = True) -> Path:
    """Resolve run directory for this execution.

    Rules:
    - If configured output_dir is the bare Final root, derive Final/<safe_title>.
    - If configured output_dir is any subdirectory/custom path, use it exactly.
    """
    configured_dir = _get_output_parent_dir()
    default_root = DEFAULT_OUTPUT_PARENT.resolve()

    try:
        configured_is_default_root = configured_dir.resolve() == default_root
    except Exception:
        configured_is_default_root = False

    if configured_is_default_root:
        run_dir = configured_dir / _safe_title_for_paths(script_title)
    else:
        run_dir = configured_dir

    if create:
        run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _save_broll_table_as_docx(broll_table_md: str, out_path: Path) -> bool:
    """Render a B-roll markdown table to a Word document at out_path.

    Strips ``` fences, finds the pipe-table block, builds a styled docx.
    Any non-table preamble/tail (e.g. **Stock Footage Search String:** ...)
    is added as bold/plain paragraphs. Returns True on success.
    """
    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError as e:
        logger.error(f"❌ python-docx not available for broll docx: {e}")
        return False

    if not broll_table_md or not broll_table_md.strip():
        logger.warning("⚠️ Empty broll table, skipping docx save")
        return False

    text = re.sub(r'^[ \t]*```[\w-]*[ \t]*$', '',
                  broll_table_md, flags=re.MULTILINE)
    lines = [ln.rstrip() for ln in text.replace('\r\n', '\n').split('\n')]

    # Locate header + separator (any two consecutive lines starting with |
    # where the second is a separator row).
    header_idx = -1
    for i in range(len(lines) - 1):
        a = lines[i].strip()
        b = lines[i + 1].strip()
        if (a.startswith('|') and b.startswith('|')
                and set(b.replace('|', '').strip()) <= set('-: ')):
            header_idx = i
            break

    doc = Document()

    def _add_paragraph(raw: str) -> None:
        if not raw.strip():
            return
        p = doc.add_paragraph()
        # Render **bold** spans inline.
        parts = raw.split('**')
        for idx, part in enumerate(parts):
            if not part:
                continue
            run = p.add_run(part)
            if idx % 2 == 1:
                run.bold = True

    if header_idx < 0:
        # No table detected — just dump the text.
        for ln in lines:
            _add_paragraph(ln)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            doc.save(str(out_path))
            return True
        except Exception as e:
            logger.error(f"❌ Failed to save broll docx: {e}")
            return False

    # Preamble (everything before the header)
    for ln in lines[:header_idx]:
        _add_paragraph(ln)

    def _split_row(row: str):
        cells = [c.strip() for c in row.split('|')]
        if cells and not cells[0]:
            cells = cells[1:]
        if cells and not cells[-1]:
            cells = cells[:-1]
        return cells

    headers = _split_row(lines[header_idx])
    body_rows = []
    j = header_idx + 2
    while j < len(lines):
        ln = lines[j].strip()
        if not ln.startswith('|'):
            break
        cells = _split_row(ln)
        if cells:
            body_rows.append(cells)
        j += 1

    if headers and body_rows:
        table = doc.add_table(rows=1 + len(body_rows), cols=len(headers))
        try:
            table.style = 'Light Grid Accent 1'
        except Exception:
            pass
        for c, h in enumerate(headers):
            cell = table.rows[0].cells[c]
            cell.text = h
            for para in cell.paragraphs:
                for run in para.runs:
                    run.bold = True
        for r, row in enumerate(body_rows, start=1):
            for c, val in enumerate(row):
                if c < len(headers):
                    table.rows[r].cells[c].text = val
        doc.add_paragraph()

    # Tail (everything after the table)
    for ln in lines[j:]:
        _add_paragraph(ln)

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out_path))
        return True
    except Exception as e:
        logger.error(f"❌ Failed to save broll docx: {e}")
        return False


def _script_excerpt_for_row(script: str, row: dict, idx: int, total: int,
                            wpm: int = 150, window_words: int = 80) -> str:
    """Return the ~160-word slice of the script the given b-roll row illustrates,
    so the Grok prompt engineer can ground the visual in the ACTUAL moment (not a
    generic stock version). Locates the moment by the row's timecode → word index
    (at `wpm`), falling back to the row's chronological position. Best-effort;
    returns "" when there's no script."""
    if not script or not script.strip():
        return ""
    words = script.split()
    n = len(words)
    if n == 0:
        return ""
    center = None
    tc = (row.get("timecode") or "").strip()
    m = re.match(r'(\d+):(\d+):(\d+)', tc)
    if m:
        secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        center = int((secs / 60.0) * wpm)
    if not center or center <= 0:
        center = int(((idx + 0.5) / max(1, total)) * n)
    center = max(0, min(center, n - 1))
    lo = max(0, center - window_words)
    hi = min(n, center + window_words)
    return " ".join(words[lo:hi]).strip()


def _grok_prompts_for_broll_rows(parsed_data, theme: str = "", max_workers: int = 8,
                                 builder=None, script: str = "") -> dict:
    """Generate a grok-imagine-friendly video prompt for every parsed b-roll row
    via Claude (Opus 4.8), so the saved B-roll table carries a ready-to-use,
    copy-paste prompt for regenerating any scene whose Grok clip didn't turn out.

    ``builder`` picks the style: default ``_grok_build_video_prompt`` (cinematic /
    photoreal-or-motion-graphics), or pass ``_grok_build_chalk_prompt`` for
    the chalk column. ``script`` (the full script text) grounds each prompt in the
    exact scene it illustrates. Returns ``{row_index: prompt}``. Best-effort —
    a failing row yields an empty string rather than breaking the batch.
    """
    prompts: dict = {}
    if not parsed_data:
        return prompts
    _builder = builder or _grok_build_video_prompt
    total = len(parsed_data)

    def _one(item):
        idx, row = item
        desc = (row.get("description") or "").strip()
        if not desc:
            return idx, ""
        excerpt = _script_excerpt_for_row(script, row, idx, total)
        try:
            return idx, (_builder(
                desc, row.get("scene_context", ""), theme,
                script_excerpt=excerpt) or "")
        except Exception as e:
            logger.warning(f"⚠️ Grok table prompt failed (row {idx}): {e}")
            return idx, ""

    items = list(enumerate(parsed_data))
    try:
        from concurrent.futures import ThreadPoolExecutor
        workers = max(1, min(max_workers, len(items)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for idx, prompt in ex.map(_one, items):
                prompts[idx] = prompt
    except Exception as e:
        logger.warning(
            f"⚠️ Grok prompt batch failed ({e}); running sequentially")
        for item in items:
            idx, prompt = _one(item)
            prompts[idx] = prompt
    return prompts


def _save_broll_table_with_prompts_as_docx(
    parsed_data,
    grok_prompts: dict,
    out_path: Path,
    search_string: str = "",
    chalk_prompts: "Optional[dict]" = None,
) -> bool:
    """Build a Word doc of the B-roll table with copy-paste Grok prompt columns:
    a cinematic 'Grok Imagine Prompt' and a 'Grok Chalk Prompt' (clean 2D/3D
    animated business graphic) for each scene. Returns True on success, False if
    python-docx is missing or there are no rows.
    """
    try:
        from docx import Document
    except ImportError as e:
        logger.error(f"❌ python-docx not available for broll docx: {e}")
        return False
    if not parsed_data:
        return False
    chalk_prompts = chalk_prompts or {}

    has_timecode = any((r.get("timecode") or "").strip() for r in parsed_data)
    headers = (["Timecode"] if has_timecode else []) + [
        "Search Term", "Description", "Scene Context",
        "Grok Imagine Prompt", "Grok Chalk Prompt"]

    doc = Document()
    doc.add_heading("B-Roll Table", level=1)
    note = doc.add_paragraph()
    note.add_run(
        "'Grok Imagine Prompt' is a ready-to-use cinematic grok-imagine-video "
        "prompt; 'Grok Chalk Prompt' is a rough white-chalk-on-black hand-drawn "
        "sketch version of the same scene. Copy either cell to (re)generate "
        "that clip."
    ).italic = True

    table = doc.add_table(rows=1 + len(parsed_data), cols=len(headers))
    try:
        table.style = 'Light Grid Accent 1'
    except Exception:
        pass
    for c, h in enumerate(headers):
        cell = table.rows[0].cells[c]
        cell.text = h
        for para in cell.paragraphs:
            for run in para.runs:
                run.bold = True
    for r, row in enumerate(parsed_data, start=1):
        vals = []
        if has_timecode:
            vals.append(row.get("timecode", "") or "")
        vals.extend([
            row.get("search_term", "") or "",
            row.get("description", "") or "",
            row.get("scene_context", "") or "",
            grok_prompts.get(r - 1, "") or "",
            chalk_prompts.get(r - 1, "") or "",
        ])
        for c, val in enumerate(vals):
            if c < len(headers):
                table.rows[r].cells[c].text = val

    if (search_string or "").strip():
        doc.add_paragraph()
        p = doc.add_paragraph()
        p.add_run("Stock Footage Search String: ").bold = True
        p.add_run(search_string.strip())

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out_path))
        return True
    except Exception as e:
        logger.error(f"❌ Failed to save broll docx: {e}")
        return False


def _persist_broll_table_artifacts(
    broll_table: str,
    parsed_data,
    broll_dir: Path,
    theme: str = "",
    script: str = "",
) -> None:
    """Persist the B-roll table into ``broll_dir`` as broll_table.md (raw) plus
    broll_table.docx enriched with a Claude-generated 'Grok Imagine Prompt'
    column. This is the same folder Grok videos are saved to, so the Word table
    sits next to the clips and its prompts can be copied to regenerate any weak
    scene. ``script`` (the full script text) grounds each Grok prompt in the exact
    scene it illustrates. Best-effort — logs and swallows errors so generation
    never breaks.
    """
    # 1) Generate the Grok Imagine prompts and attach one to each row (in place)
    #    FIRST, independent of any disk write. This runs even when local-fs
    #    writes are disabled (e.g. the cloud container), so the UI still receives
    #    a grok_prompt per row in the broll_rows payload to show + copy.
    grok_prompts: dict = {}
    chalk_prompts: dict = {}
    if parsed_data:
        try:
            grok_prompts = _grok_prompts_for_broll_rows(
                parsed_data, theme, script=script)
            # Chalk = the SAME cinematic visual, redrawn in chalk, so the two
            # columns always match (one idea, two styles).
            chalk_prompts = _grok_chalk_prompts_from_cinematic(grok_prompts)
            for i, row in enumerate(parsed_data):
                if not isinstance(row, dict):
                    continue
                if not (row.get("grok_prompt") or "").strip():
                    row["grok_prompt"] = grok_prompts.get(i, "") or ""
                if not (row.get("grok_chalk_prompt") or "").strip():
                    row["grok_chalk_prompt"] = \
                        chalk_prompts.get(i, "") or ""
        except Exception as e:
            logger.warning(f"⚠️ Grok prompt generation for broll rows failed: {e}")

    # 2) Persist md + docx to disk (best-effort; may be a no-op in the container).
    try:
        broll_dir.mkdir(parents=True, exist_ok=True)
        md_path = broll_dir / "broll_table.md"
        md_path.write_text(broll_table or "", encoding="utf-8")
        logger.info(f"💾 Saved broll table md → {md_path}")

        docx_path = broll_dir / "broll_table.docx"
        if parsed_data:
            # Pull the "Stock Footage Search String" tail (if any) for the docx.
            search_string = ""
            m = re.search(
                r"\*\*Stock Footage Search String:\*\*\s*(.+)",
                broll_table or "", flags=re.DOTALL)
            if m:
                search_string = m.group(1).strip()
            if _save_broll_table_with_prompts_as_docx(
                    parsed_data, grok_prompts, docx_path, search_string,
                    chalk_prompts=chalk_prompts):
                logger.info(
                    f"💾 Saved broll table docx (+Grok prompts) → {docx_path}")
                return
        # Fallback: no parsed rows — save the plain markdown table as docx.
        if _save_broll_table_as_docx(broll_table, docx_path):
            logger.info(f"💾 Saved broll table docx → {docx_path}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to persist broll table artifacts: {e}")


def _copy_to_output_subfolder(src, subfolder: str, script_title: Optional[str] = None) -> Optional[Path]:
    """Copy a source file into {output_base}/{subfolder}/ if a base dir is configured.

    Returns the destination path on success; None if no base dir, src missing, or copy fails.
    Best-effort: errors are logged but never raised so generation flows aren't disrupted.
    """
    try:
        base = _get_run_output_dir(
            script_title, create=True) if script_title else _get_output_parent_dir()
        if not base:
            return None
        if not src:
            return None
        src_path = Path(src).expanduser()
        if not src_path.exists() or not src_path.is_file():
            return None
        dst_dir = base / subfolder
        # If the file already lives inside the destination folder, nothing to do.
        try:
            if src_path.resolve().parent == dst_dir.resolve():
                return src_path
        except Exception:
            pass
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src_path.name
        # Skip identical re-copies
        if dst.exists() and dst.stat().st_size == src_path.stat().st_size:
            return dst
        import shutil as _shutil
        _shutil.copy2(src_path, dst)
        return dst
    except Exception as e:
        logger.warning(f"⚠️ Could not auto-copy '{src}' → {subfolder}/: {e}")
        return None


def _save_curl_commands_live(curl_commands, script_title: str) -> Optional[Path]:
    """Write curl commands to {output_base}/curls/<safe_title>_curls.sh as soon as they are generated.

    Returns the destination path on success, or None if no base dir / nothing to write / failure.
    """
    try:
        if not curl_commands:
            return None
        base = _get_run_output_dir(script_title, create=True)
        safe_title = re.sub(r'[^A-Za-z0-9._-]+', '_',
                            (script_title or 'script').strip()).strip('._') or 'script'
        curl_dir = base / "curls"
        curl_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(curl_commands, str):
            dst = curl_dir / f"{safe_title}_curls.sh"
            dst.write_text(curl_commands, encoding="utf-8")
        else:
            import json as _json
            dst = curl_dir / f"{safe_title}_curls.json"
            dst.write_text(_json.dumps(
                curl_commands, indent=2), encoding="utf-8")
        return dst
    except Exception as e:
        logger.warning(f"⚠️ Live curl save failed: {e}")
        return None


def _sync_generated_media_to_project(project_path: Path) -> dict:
    """Copy generated media into DaVinci project folders.

    - Grok videos: {project}/broll -> {project}/bRoll
    - Generated images: fallback copy from ~/Dev/brollimages -> {project}/images
      (only used when project/images does not already contain generated files)
    """
    import shutil as _shutil

    project_path = Path(project_path)
    broll_src = project_path / "broll"
    broll_dst = project_path / "bRoll"
    images_dst = project_path / "images"

    broll_dst.mkdir(parents=True, exist_ok=True)
    images_dst.mkdir(parents=True, exist_ok=True)

    videos_copied = 0
    images_copied = 0

    # Sync Grok videos into DaVinci bRoll folder.
    if broll_src.exists() and broll_src.is_dir():
        for src in broll_src.rglob('*'):
            if not src.is_file():
                continue
            if src.suffix.lower() not in {'.mp4', '.mov', '.m4v'}:
                continue
            dst = broll_dst / src.name
            try:
                if dst.exists() and dst.stat().st_size == src.stat().st_size:
                    continue
                _shutil.copy2(src, dst)
                videos_copied += 1
            except Exception as copy_err:
                logger.warning(
                    f"⚠️ Could not copy Grok video {src.name}: {copy_err}")

    # If images are already generated into project/images, leave them as-is.
    local_generated_images = []
    for pattern in ('*.png', '*.jpg', '*.jpeg', '*.webp'):
        local_generated_images.extend(images_dst.glob(pattern))

    # Back-compat fallback: copy from legacy global brollimages folder.
    if len(local_generated_images) == 0:
        legacy_images_src = Path.home() / "Dev" / "brollimages"
        if legacy_images_src.exists() and legacy_images_src.is_dir():
            for src in legacy_images_src.iterdir():
                if not src.is_file() or src.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
                    continue
                dst = images_dst / src.name
                try:
                    if dst.exists() and dst.stat().st_size == src.stat().st_size:
                        continue
                    _shutil.copy2(src, dst)
                    images_copied += 1
                except Exception as copy_err:
                    logger.warning(
                        f"⚠️ Could not copy legacy image {src.name}: {copy_err}")

    return {
        "videos_copied": videos_copied,
        "images_copied": images_copied,
        "broll_source": str(broll_src),
        "broll_target": str(broll_dst),
        "images_target": str(images_dst),
    }


# Paths already added above - no need to duplicate

# Import text processing functions

app = Flask(__name__)
# Allow large audio/video uploads (Whisper transcription, gallery uploads, etc.)
# — 16 GiB cap. Override with MAX_UPLOAD_GB env var if you need more/less.
_max_upload_gb = int(os.environ.get("MAX_UPLOAD_GB", "16"))
app.config["MAX_CONTENT_LENGTH"] = _max_upload_gb * 1024 * 1024 * 1024


@app.errorhandler(413)
def _too_large(_e):
    """Return a JSON error for oversize uploads so the frontend can show it
    instead of a silent HTML 413 page."""
    from flask import jsonify as _jsonify
    return _jsonify({
        "success": False,
        "error": (f"File exceeds the server upload limit of "
                  f"{_max_upload_gb} GiB. Set MAX_UPLOAD_GB or compress the file."),
    }), 413

# ---------------------------------------------------------------------------
# Optional token-based auth gate.
#
# When env APP_AUTH_TOKEN is set, every request OUTSIDE the public allowlist
# must supply the token via one of:
#   - X-App-Token: <token>      header
#   - ?app_token=<token>        query string
#   - app_token=<token>         cookie  (set by GET /login?token=...)
#
# When unset, the app is open (current behavior — used for local dev).
#
# Public paths (always allowed) live in PUBLIC_PREFIXES below. The video
# share page /videos and its read-only API stay public; the upload endpoint
# is explicitly protected even though it shares the same prefix.
# ---------------------------------------------------------------------------
APP_AUTH_TOKEN = os.environ.get("APP_AUTH_TOKEN", "").strip()
PUBLIC_PREFIXES = (
    "/videos",
    "/api/finished-videos",   # GET list (and local-mode file stream)
    "/static/",
    "/favicon.ico",
    "/login",
    "/healthz",
)
PROTECTED_OVERRIDES = ("/api/finished-videos/upload",)


def _request_app_token() -> str:
    return (
        request.headers.get("X-App-Token", "").strip()
        or request.args.get("app_token", "").strip()
        or request.cookies.get("app_token", "").strip()
    )


@app.before_request
def _enforce_app_auth_token():
    if not APP_AUTH_TOKEN:
        return None
    p = request.path or ""
    # Protect upload endpoint first (it lives under a public prefix).
    if any(p.startswith(x) for x in PROTECTED_OVERRIDES):
        if _request_app_token() != APP_AUTH_TOKEN:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return None
    # Public allowlist.
    if any(p == x or p.startswith(x) for x in PUBLIC_PREFIXES):
        return None
    # Everything else: require the token.
    if _request_app_token() != APP_AUTH_TOKEN:
        if p.startswith("/api/"):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        from flask import redirect as _redirect
        return _redirect("/login")
    return None


@app.route("/login", methods=["GET"])
def app_login_page():
    """Set the app_token cookie via ?token=... and redirect to /."""
    from flask import redirect as _redirect
    token = (request.args.get("token") or "").strip()
    if APP_AUTH_TOKEN and token == APP_AUTH_TOKEN:
        resp = make_response(_redirect("/"))
        resp.set_cookie(
            "app_token", token,
            max_age=30 * 24 * 3600,
            httponly=True,
            samesite="Lax",
            secure=request.is_secure,
        )
        return resp
    html = """<!doctype html><html><head><meta charset="utf-8"><title>Sign in</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0b1220;color:#e5e7eb;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
form{background:#111827;padding:24px;border-radius:10px;border:1px solid #1f2937;display:flex;gap:8px;flex-direction:column;min-width:300px}
input,button{padding:8px 10px;border-radius:6px;border:1px solid #334155;background:#0f172a;color:#e5e7eb;font-size:14px}
button{cursor:pointer;background:#1d4ed8;border-color:#1d4ed8}
h1{margin:0 0 6px;font-size:16px}
.hint{color:#94a3b8;font-size:12px;margin-top:4px}
</style></head><body>
<form method="get" action="/login">
<h1>🔒 Sign in</h1>
<input type="password" name="token" placeholder="Access token" autofocus />
<button type="submit">Continue</button>
<div class="hint">The /videos share page is always public.</div>
</form></body></html>"""
    return Response(html, mimetype="text/html")


progress_streams = {}
results = {}
running_tasks = {}
# Per-session cancel events for long-running, cancellable steps.
broll_image_cancel_events: "dict[str, _threading.Event]" = {}
thumbnail_cancel_events: "dict[str, _threading.Event]" = {}
grok_video_cancel_events: "dict[str, _threading.Event]" = {}
# Whole-workflow cancellation: per-session asyncio loop + task handles so a
# separate Flask request thread can call task.cancel() on the running coroutine
# (cooperative — propagates CancelledError at the next await point), plus a
# coarse Event mirror for any future cooperative cancel checks.
workflow_cancel_events: "dict[str, _threading.Event]" = {}
workflow_loops: "dict[str, asyncio.AbstractEventLoop]" = {}
workflow_async_tasks: "dict[str, asyncio.Task]" = {}


def _run_cancellable_workflow(session_id: str, coro_factory):
    """Run an async coroutine in its own event loop so it can be cancelled from
    another thread via :func:`workflow_async_tasks` + ``task.cancel()``.

    ``coro_factory`` is a zero-arg callable that returns a fresh coroutine each
    call. Using a factory (rather than passing the coroutine itself) lets this
    helper own coroutine creation so cleanup is always consistent.
    """
    loop = asyncio.new_event_loop()
    workflow_loops[session_id] = loop
    asyncio.set_event_loop(loop)
    task = loop.create_task(coro_factory())
    workflow_async_tasks[session_id] = task
    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        # User-initiated cancel — already announced via /api/cancel-workflow.
        logger.info(f"🛑 Workflow cancelled for session {session_id}")
    finally:
        workflow_loops.pop(session_id, None)
        workflow_async_tasks.pop(session_id, None)
        try:
            loop.close()
        except Exception:
            pass
grok_video_streams: "dict[str, _queue.Queue]" = {}
grok_video_results: "dict[str, dict]" = {}
audio_render_streams: "dict[str, _queue.Queue]" = {}
audio_render_results: "dict[str, dict]" = {}
transcribe_streams: "dict[str, _queue.Queue]" = {}
transcribe_results: "dict[str, dict]" = {}
thumbnail_test_streams: "dict[str, _queue.Queue]" = {}
thumbnail_test_results: "dict[str, dict]" = {}
# Background video-upload/transcode jobs. Keyed by job_id (uuid4 hex).
# Shape: {state, percent, duration, out_time, error, video, filename, blob_name, started, finished}
video_upload_jobs: "dict[str, dict]" = {}
video_upload_jobs_lock = _threading.Lock()


@app.route('/api/proxy')
def proxy_external_page():
    """
    Lightweight HTML proxy used by the Shutterstock split-pane preview.

    Some sites (e.g. shutterstock.com) refuse to render in iframes via X-Frame-Options
    or Content-Security-Policy. We fetch the page server-side and strip those headers
    so the result can be embedded in our preview pane. We also inject a <base> tag so
    relative URLs (CSS/JS/images) continue to resolve against the original origin.

    Only http/https URLs from a small allow-list are proxied to avoid being abused as
    an open redirector or generic SSRF surface.
    """
    from urllib.parse import urlparse, urljoin

    target = (request.args.get('url') or '').strip()
    if not target:
        return Response("Missing url parameter", status=400)

    parsed = urlparse(target)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return Response("Invalid url", status=400)

    allowed_hosts = {
        "www.shutterstock.com",
        "shutterstock.com",
    }
    if parsed.netloc not in allowed_hosts:
        return Response("Host not allowed for proxy", status=403)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        upstream = requests.get(target, headers=headers,
                                timeout=15, allow_redirects=True)
    except Exception as fetch_err:
        return Response(f"Proxy fetch failed: {fetch_err}", status=502)

    content_type = upstream.headers.get(
        "Content-Type", "text/html; charset=utf-8")
    body = upstream.content

    # Only rewrite HTML responses; pass through other content types untouched.
    if "text/html" in content_type.lower():
        try:
            text = body.decode(upstream.encoding or "utf-8", errors="replace")
            base_href = f"{parsed.scheme}://{parsed.netloc}/"
            base_tag = f'<base href="{base_href}">'
            # Insert <base> right after <head> if present, otherwise prepend.
            if re.search(r"<head[^>]*>", text, re.IGNORECASE):
                text = re.sub(r"(<head[^>]*>)", r"\1" + base_tag,
                              text, count=1, flags=re.IGNORECASE)
            else:
                text = base_tag + text
            # Strip any inline CSP meta tags that would block embedded scripts/styles.
            text = re.sub(
                r"<meta[^>]+http-equiv=['\"]Content-Security-Policy['\"][^>]*>",
                "",
                text,
                flags=re.IGNORECASE,
            )
            body = text.encode("utf-8")
            content_type = "text/html; charset=utf-8"
        except Exception:
            pass

    resp = Response(body, status=upstream.status_code,
                    content_type=content_type)
    # Explicitly drop framing-related headers so the iframe can render the response.
    for hdr in ("X-Frame-Options", "Content-Security-Policy", "Content-Security-Policy-Report-Only"):
        if hdr in resp.headers:
            del resp.headers[hdr]
    return resp


def _extract_broll_table_from_script(script_text: str) -> str:
    """
    Find a B-roll markdown table already embedded in a script.

    The B-roll agent emits tables shaped like:
        | Timecode | Search Term | Description | Scene Context |
        |----------|-------------|-------------|---------------|
        | 00:00:05 | ...         | ...         | ...           |

    Some scripts only have the 3-column variant (Search Term | Description | Scene Context).
    Returns the contiguous block of pipe-prefixed lines that contains the header, or "" if
    no plausible B-roll table is present.
    """
    if not script_text:
        return ""

    lines = script_text.splitlines()
    n = len(lines)
    header_idx = -1
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("|"):
            continue
        low = s.lower()
        # Header heuristic: pipe row that names recognizable B-roll columns.
        if ("search term" in low) or ("timecode" in low and "description" in low):
            header_idx = i
            break

    if header_idx < 0:
        return ""

    # Walk forward collecting contiguous table rows (allow blank lines between rows? no — agents emit them solid).
    end_idx = header_idx
    for j in range(header_idx, n):
        if lines[j].strip().startswith("|"):
            end_idx = j
        else:
            break

    block = "\n".join(lines[header_idx:end_idx + 1]).strip()
    # Require at least one data row beyond header + separator.
    data_rows = [
        ln for ln in block.splitlines()
        if ln.strip().startswith("|") and not ln.strip().startswith("|---")
        and "search term" not in ln.lower() and "timecode" not in ln.lower()
    ]
    if not data_rows:
        return ""
    return block


def _extract_animation_suggestion_rows(script_text: str) -> list:
    """
    Parse the '## Animation Suggestions ...' section of a script into
    broll-row-shaped dicts that downstream Grok video generation can consume.

    Recognized headings (case-insensitive, allow any heading level):
        ## Animation Suggestions
        ## Animation Suggestions for Complex Concepts
        ### Animations / Animation Ideas

    Each '- bullet' becomes one row. Bullets shaped like
        '- AI hiding in apps: overlay glowing AI nodes …'
    are split on the first colon into search_term (the label) and description
    (the animation prompt). Bullets without a colon use the whole text for
    both fields.

    Returns a list of dicts with the same shape as B-roll table rows so the
    Grok worker and the B-roll selection UI can treat them identically:
        {timecode, search_term, description, scene_context}
    The scene_context is set to 'Animation Suggestion' so they're visually
    distinguishable from real B-roll rows.
    """
    if not script_text:
        return []

    lines = script_text.splitlines()
    # Find heading
    heading_re = re.compile(
        r'^\s{0,3}#{1,6}\s+animation\s+(?:suggestions?|ideas?)\b',
        re.IGNORECASE,
    )
    start = -1
    for i, ln in enumerate(lines):
        if heading_re.match(ln):
            start = i + 1
            break
    if start < 0:
        return []

    # Walk forward until next heading (any level) or EOF
    bullets: list[str] = []
    for ln in lines[start:]:
        if re.match(r'^\s{0,3}#{1,6}\s+\S', ln):
            break
        s = ln.strip()
        if not s:
            continue
        # Accept '- ', '* ', '+ ' bullets and numbered bullets like '1. '
        m = re.match(r'^[-*+]\s+(.+)$', s)
        if not m:
            m = re.match(r'^\d+[\.\)]\s+(.+)$', s)
        if not m:
            continue
        text = m.group(1).strip().strip('*_').strip()
        if text:
            bullets.append(text)

    rows = []
    for b in bullets:
        if ':' in b:
            label, prompt = b.split(':', 1)
            label = label.strip().strip('*_').strip()
            prompt = prompt.strip().strip('*_').strip()
        else:
            label = b
            prompt = b
        if not label and not prompt:
            continue
        rows.append({
            'timecode': '',
            'search_term': label or prompt,
            'description': prompt or label,
            'scene_context': 'Animation Suggestion',
        })
    return rows


def _animation_rows_to_markdown(rows: list) -> str:
    """Render synthetic Animation Suggestion rows as a labeled markdown
    table that matches the B-roll table schema, so the GUI's existing
    table renderer / selection logic can pick them up without changes."""
    if not rows:
        return ""
    out = [
        "**🎞️ Animation Suggestions (for Grok video generation)**",
        "",
        "| Timecode | Search Term | Description | Scene Context |",
        "|----------|-------------|-------------|---------------|",
    ]
    for r in rows:
        def _cell(v: str) -> str:
            return (v or "").replace("|", "\\|").replace("\n", " ").strip()
        out.append(
            f"| {_cell(r.get('timecode'))} "
            f"| {_cell(r.get('search_term'))} "
            f"| {_cell(r.get('description'))} "
            f"| {_cell(r.get('scene_context'))} |"
        )
    return "\n".join(out) + "\n"


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


EMOTION_BY_VARIATION = {
    1: "ANGRY/FRUSTRATED",
    2: "SHOCKED/SURPRISED",
    3: "SCARED/WORRIED",
    4: "EXCITED/ENERGETIC",
    5: "SKEPTICAL/DOUBTFUL",
    6: "DETERMINED/INTENSE",
}


def _safe_title_for_paths(script_title: str) -> str:
    """Normalize script title to filesystem-safe folder/file name."""
    normalized = (script_title or '').strip()
    normalized = re.sub(r'^\s*#\s*', '', normalized)
    normalized = re.sub(r'^\s*Direct\s+Video\s*-\s*', '',
                        normalized, flags=re.IGNORECASE)
    # Strip Visual Cue / Heading-style label prefixes that occasionally leak
    # in when title extraction falls back to a non-title line.
    normalized = re.sub(
        r'^\s*(?:VISUAL\s*CUE|HEADING|VISUAL|B-?ROLL|HOOK|SUMMARY|HOST)\s*[:\-]\s*',
        '', normalized, flags=re.IGNORECASE)
    safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '', normalized)
    safe_title = re.sub(r'\s+', '_', safe_title).strip('_.')
    # macOS/APFS allows 255 bytes per path component but the script also
    # appends suffixes ("_curls.sh", "_heygen_curls.json", etc.) so cap at
    # 80 chars and trim back to a word boundary to keep names readable.
    _MAX_COMPONENT = 80
    if len(safe_title) > _MAX_COMPONENT:
        _trim = safe_title[:_MAX_COMPONENT]
        _last_us = _trim.rfind('_')
        if _last_us > _MAX_COMPONENT // 2:
            _trim = _trim[:_last_us]
        safe_title = _trim.strip('_.') or safe_title[:_MAX_COMPONENT]
    return safe_title or "untitled_script"


def _extract_script_title_for_output(script_text: str, fallback: str = "Untitled Script") -> str:
    """Extract a stable script title from generated markdown content."""
    text = script_text or ""

    # HIGHEST priority: explicit "Title: ..." line (plain or **Title:** Foo).
    # Wins over per-chapter Heading: lines and any H1/Chapter-1 fallback.
    title_match = re.search(
        r'^[ \t]*\**[ \t]*Title[ \t]*\**[ \t]*:[ \t]*\**[ \t]*(.+?)[ \t]*\**[ \t]*$',
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    if title_match:
        title = title_match.group(1).strip().strip('*').strip()
        if title:
            return title

    direct_video_match = re.search(
        r'^\s*#\s*Direct\s+Video\s*-\s*(.+)$',
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    if direct_video_match:
        return direct_video_match.group(1).strip() or fallback

    heading_match = re.search(r'^\s*Heading:\s*(.+)$',
                              text, re.MULTILINE | re.IGNORECASE)
    if heading_match:
        _val = heading_match.group(1).strip().strip('*').strip()
        # Skip chapter / structural / direction labels that occasionally
        # appear as the first Heading: line in malformed agent output.
        if _val and not re.match(
            r'^(?:chapter\s+\d+|visual\s*cue|b-?roll|host|narrator|hook|summary|scene|transition|cut\s+to|fade\s+(?:in|out)|voice\s*over|vo)\b',
            _val, re.IGNORECASE,
        ):
            return _val

    # Pick the first H1 that isn't a structural label / chapter marker.
    _H1_SKIP_RE = re.compile(
        r'^\s*(?:chapter\s+\d+|visual\s*cue|b-?roll|host|narrator|hook|summary|scene|transition|cut\s+to|fade\s+(?:in|out)|voice\s*over|vo|opening\s+hook|final\s+hook|hook\s+options|flow\s+analysis|analysis\s+report|hook\s+summary|thumbnail|demo\s+package|youtube\s+details|heygen|curl\s+commands)\b',
        re.IGNORECASE,
    )
    for _h1 in re.finditer(r'^#+\s+(.+)$', text, re.MULTILINE):
        candidate = _h1.group(1).strip()
        # Normalize: strip leading emojis + bold/italic wrappers before testing.
        _norm = re.sub(r'^[^\w]+', '', candidate)
        _norm = re.sub(r'^[\*_]+\s*', '', _norm)
        if _H1_SKIP_RE.match(_norm):
            continue
        title = re.sub(r'^\s*Direct\s+Video\s*-\s*',
                       '', candidate, flags=re.IGNORECASE)
        return title or fallback

    for raw_line in text.splitlines()[:20]:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("#", "*", "-", "[")):
            continue
        # Never treat the machine id lines as a title.
        if _SCRIPT_ID_RE.match(line) or _SCRIPT_VERSION_RE.match(line):
            continue
        if all(c in "_=-~" for c in line):
            continue
        if len(line) > 150:
            continue
        return line

    return fallback


# --- Script identity: permanent collection id + per-processing version -------
# Both live as plain labeled lines directly under the Title: line so they
# survive Word export / round-trips. Script-ID is assigned once and never
# changes (Grok videos accumulate under it). Script-Version bumps on every
# processing run; all other artifacts are tied to the current version.
_SCRIPT_ID_RE = re.compile(
    r'^[ \t]*\**[ \t]*Script-ID[ \t]*\**[ \t]*:[ \t]*\**[ \t]*([A-Za-z0-9\-]+)',
    re.MULTILINE | re.IGNORECASE,
)
_SCRIPT_VERSION_RE = re.compile(
    r'^[ \t]*\**[ \t]*Script-Version[ \t]*\**[ \t]*:[ \t]*\**[ \t]*([A-Za-z0-9\-]+)',
    re.MULTILINE | re.IGNORECASE,
)
_TITLE_LINE_RE = re.compile(
    r'^[ \t]*\**[ \t]*Title[ \t]*\**[ \t]*:', re.IGNORECASE)


def _new_ld_id(prefix: str) -> str:
    """Short, URL/blob-safe id, e.g. 'ld-9f3a1c7b22' or 'v-4b8e0a17de'."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _parse_script_ids(text: str) -> "tuple[Optional[str], Optional[str]]":
    """Return (script_id, version_id) found in the script, else (None, None)."""
    t = text or ""
    sid = _SCRIPT_ID_RE.search(t)
    vid = _SCRIPT_VERSION_RE.search(t)
    return (sid.group(1) if sid else None, vid.group(1) if vid else None)


def _ensure_script_ids(
    text: str,
    bump_version: bool = False,
    script_id: "Optional[str]" = None,
    version_id: "Optional[str]" = None,
) -> "tuple[str, str, str]":
    """Ensure Script-ID (permanent) + Script-Version lines sit directly under
    the Title: line. Returns (new_text, script_id, version_id).

    - script_id/version_id, when given, are forced onto the text (used to
      re-stamp a script after agents may have stripped the lines, keeping the
      ids stable across a processing run).
    - Otherwise: missing Script-ID -> a fresh permanent id; missing
      Script-Version or bump_version=True -> a fresh version (processing runs
      pass bump_version=True; manual edits never reach here).
    Existing id lines are rewritten in place (de-duplicated).
    """
    t = text or ""
    cur_id, cur_version = _parse_script_ids(t)
    script_id = script_id or cur_id or _new_ld_id("ld")
    if version_id:
        pass
    elif bump_version or not cur_version:
        version_id = _new_ld_id("v")
    else:
        version_id = cur_version

    lines = t.split("\n")
    # Drop any existing id lines so we reinsert a single clean pair.
    kept = [ln for ln in lines
            if not _SCRIPT_ID_RE.match(ln) and not _SCRIPT_VERSION_RE.match(ln)]

    # Insert right after the Title: line if present, else at the very top.
    insert_at = 0
    for i, ln in enumerate(kept[:40]):
        if _TITLE_LINE_RE.match(ln):
            insert_at = i + 1
            break
    id_lines = [f"Script-ID: {script_id}", f"Script-Version: {version_id}"]
    new_lines = kept[:insert_at] + id_lines + kept[insert_at:]
    return ("\n".join(new_lines), script_id, version_id)


async def _save_script_md_and_docx(script_title: str, script_content: str) -> tuple[Optional[str], Optional[str]]:
    """Save script outputs as .md and .docx in {run_folder}/Script/."""
    run_dir = _get_run_output_dir(script_title, create=True)
    script_dir = run_dir / "Script"
    script_dir.mkdir(parents=True, exist_ok=True)
    safe_title = _safe_title_for_paths(script_title)

    md_path = script_dir / f"{safe_title}.md"
    md_path.write_text(script_content or "", encoding="utf-8")

    docx_path = script_dir / f"{safe_title}.docx"
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / "console_ui"))
        from word_processing import convert_markdown_to_word

        await convert_markdown_to_word(
            markdown_content=script_content or "",
            output_file_path=str(docx_path),
            template_path=None,
            title=script_title,
        )
        return str(md_path), str(docx_path)
    except Exception as e:
        logger.warning(f"⚠️ Could not save DOCX output: {e}")
        return str(md_path), None


def _guess_emotion_from_filename(filename: str) -> str:
    """Infer variation emotion label from filename pattern like *_v2_*.png."""
    match = re.search(r'_v(\d+)_', filename)
    if not match:
        return "EXISTING THUMBNAIL"
    return EMOTION_BY_VARIATION.get(int(match.group(1)), "EXISTING THUMBNAIL")


def _collect_all_thumbnail_entries(script_title: str, thumbnail_results: dict | None = None) -> list[dict]:
    """Return all thumbnails present in the script's thumbnails directory."""
    thumbnail_results = thumbnail_results or {}
    generated_variations = thumbnail_results.get("variations") or []
    output_dir_hint = thumbnail_results.get("output_dir")

    thumbnail_dir = None
    if output_dir_hint:
        thumbnail_dir = Path(output_dir_hint)
    else:
        thumbnail_dir = _get_run_output_dir(
            script_title, create=False) / "thumbnails"

    generated_by_filename = {}
    for variation in generated_variations:
        filename = variation.get("filename")
        if not filename and variation.get("filepath"):
            filename = Path(variation.get("filepath")).name
        if filename:
            generated_by_filename[filename] = variation

    if not thumbnail_dir.exists() or not thumbnail_dir.is_dir():
        return []

    image_paths = sorted(
        [
            p for p in thumbnail_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg"}
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    thumbnails = []
    for image_path in image_paths:
        variation = generated_by_filename.get(image_path.name, {})
        thumbnails.append({
            "emotion": variation.get("emotion") or variation.get("mood") or _guess_emotion_from_filename(image_path.name),
            "text": variation.get("text") or variation.get("thumbnail_text") or "Existing thumbnail",
            "filename": image_path.name,
        })

    return thumbnails


def _extract_thumbnail_hook_text_options(hook_result: dict | None = None, script_text: str = "") -> list[str]:
    """Extract up to three thumbnail hook text options from hook agent result or script text blocks."""
    hook_result = hook_result or {}

    options: list[str] = []

    direct_options = hook_result.get("thumbnail_hook_text_options") or []
    if isinstance(direct_options, list):
        for option in direct_options:
            text = (option or "").strip().strip('"').strip()
            if text and text not in options:
                options.append(text)

    direct_single = (hook_result.get("thumbnail_hook_text")
                     or "").strip().strip('"').strip()
    if direct_single and direct_single not in options:
        options.append(direct_single)

    if options:
        return options[:3]

    def _add_option(text: str):
        cleaned = (text or "").strip().strip('"').strip()
        if cleaned and cleaned not in options:
            options.append(cleaned)

    raw_candidates = [
        hook_result.get("full_response", ""),
        hook_result.get("raw_response", ""),
        script_text,
    ]

    for raw in raw_candidates:
        if not raw:
            continue

        numbered = re.findall(
            r'THUMBNAIL_HOOK_TEXT_(\d+)\s*:\s*"?([^"\n]+)"?',
            raw,
            flags=re.IGNORECASE,
        )
        if numbered:
            for _, text in sorted(numbered, key=lambda item: int(item[0])):
                _add_option(text)
            if options:
                return options[:3]

        match = re.search(
            r'THUMBNAIL_HOOK_TEXT\s*:\s*"?([^"\n]+)"?',
            raw,
            flags=re.IGNORECASE,
        )
        if match:
            _add_option(match.group(1))
            if options:
                return options[:3]

    return options[:3]


def _extract_thumbnail_hook_text(hook_result: dict | None = None, script_text: str = "") -> str:
    """Extract the first available thumbnail hook text option."""
    options = _extract_thumbnail_hook_text_options(
        hook_result=hook_result,
        script_text=script_text,
    )
    return options[0] if options else ""


class ConsoleCapture:
    """Captures console output and redirects to progress streamer"""

    def __init__(self, streamer):
        self.streamer = streamer
        self.original_stdout = sys.stdout
        self.buffer = []
        self.long_operation_start = None
        self.last_chapter_revision = None

    def write(self, message):
        """Write to both original stdout and the progress streamer"""
        if not message.strip():
            return

        # Debug: Add marker to identify when write method is called
        if "TEST 5" in message or "Minimal rapid" in message:
            self.original_stdout.write(f"🔍 WRITE DEBUG: {message.strip()}\n")
            self.original_stdout.flush()

        # Write to original stdout first
        self.original_stdout.write(message)
        self.original_stdout.flush()

        # Filter Azure SDK noise that can cause blocking
        if self._should_filter_azure_sdk_logging(message):
            return

        # Extract progress and send to web interface
        progress = self._extract_progress(message)
        if progress is not None and self.streamer:
            # Only send updates when we have explicit progress values
            try:
                self.streamer.send_update(message.strip(), progress)
            except Exception as e:
                self.original_stdout.write(
                    f"⚠️ Stream update failed: {e}\n")
                self.original_stdout.flush()
        # Don't send messages without progress - they would default to 50%

    def _track_long_operations(self, message):
        """Track when long operations start for timing purposes"""
        import time

        # Track when chapter revision starts
        if "Reviewing Chapter" in message and "revision failed" not in message:
            chapter_match = re.search(r'Chapter (\d+)', message)
            if chapter_match:
                chapter_num = int(chapter_match.group(1))
                self.last_chapter_revision = {
                    'chapter': chapter_num,
                    'start_time': time.time()
                }

        # Track other long operations
        elif any(phrase in message for phrase in [
            "Script Reviewer", "Script review", "Reviewing", "Revising"
        ]) and "failed" not in message and "completed" not in message:
            if self.long_operation_start is None:
                self.long_operation_start = time.time()

    def _enhance_message_with_timing(self, primary_text, fallback_text):
        """Add timing information to progress messages"""
        import time

        msg = primary_text if len(primary_text) > 10 else fallback_text

        # Add elapsed time for chapter revisions
        if self.last_chapter_revision and "revised" in msg:
            elapsed = time.time() - self.last_chapter_revision['start_time']
            if elapsed > 30:  # Only show timing after 30 seconds
                chapter_num = self.last_chapter_revision['chapter']
                mins, secs = divmod(int(elapsed), 60)
                if mins > 0:
                    msg = f"{msg} (Chapter {chapter_num} took {mins}m {secs}s)"
                else:
                    msg = f"{msg} (Chapter {chapter_num} took {secs}s)"

        # Add elapsed time for other long operations
        elif self.long_operation_start and any(phrase in msg for phrase in [
            "reviewing", "revising", "processing"
        ]):
            elapsed = time.time() - self.long_operation_start
            if elapsed > 60:  # Show timing after 1 minute
                mins, secs = divmod(int(elapsed), 60)
                msg = f"{msg} (running {mins}m {secs}s)"

        return msg

    def _should_filter_initialization_message(self, message):
        """Filter out initialization messages not relevant to script work"""
        initialization_patterns = [
            "TournamentAgentClient initialized",
            "TournamentAgent model client created",
            "AITipsAgentClient initialized",
            "AITipsAgent model client created",
            "📡 AUTOGEN SYSTEM TRACE: Initializing agents",
            "🤖 AUTOGEN SYSTEM TRACE: Creating model clients",
            "🎯 AUTOGEN SYSTEM TRACE: System fully initialized"
        ]

        return any(pattern in message for pattern in initialization_patterns)

    def _should_filter_azure_sdk_logging(self, message):
        """Filter out Azure AI SDK internal logging that can block operations"""
        # Only filter very specific Azure SDK internal messages that cause blocking
        blocking_patterns = [
            "INFO - ManagedIdentityCredential will use IMDS",
            "INFO - Request URL:",
            "Request method:",
            "Request headers:",
            "No body was attached to the request",
            "A body is sent with the request",
            "INFO - Response status:",
            "Response headers:",
            "INFO - DefaultAzureCredential acquired a token",
            "User-Agent': 'azsdk-python-identity",
            "User-Agent': 'AIProjectClient azsdk-python-ai-agents",
            "Authorization': 'REDACTED'",
            "x-ms-client-request-id':",
            "Content-Type': 'application/json'",
            "openai-processing-ms':",
            "Date': 'Fri, 26 Sep 2025",
            "No environment configuration found."
        ]

        # Keep important workflow messages even if they contain Azure terms
        important_workflow_patterns = [
            "STEP 1:", "STEP 2:", "STEP 3:", "STEP 4:",
            "Topic enhanced", "Chapter", "Script", "Writing", "Reviewing", "Revising",
            "completed", "revised", "Assembling", "WORKFLOW", "DEBUG:"
        ]

        # Don't filter if it's an important workflow message
        if any(pattern in message for pattern in important_workflow_patterns):
            return False

        return any(pattern in message for pattern in blocking_patterns)

    def _extract_progress(self, message):
        """
        Extract progress based on actual workflow messages.

        Progress Distribution (matches actual workflow timeline):
        - 0-10%: Initialization (system startup)
        - 10-20%: Topic Enhancement (STEP 1)
        - 20-30%: Start Chapter Writing (STEP 2 begins)
        - 30-55%: Chapter Writing Progress (based on completed chapters)
        - 55-65%: Script Review (STEP 3)
        - 65-80%: Chapter-by-Chapter Review Progress
        - 80-83%: YouTube Metadata
        - 83-86%: B-roll Search Terms
        - 86-89%: Demo Packages
        - 89-90%: B-roll Terms (second generation)
        - 90-100%: Thumbnail Generation & Completion
        """
        import re

        # ========== INITIALIZATION (0-10%) ==========
        if "Starting script creation" in message:
            return 1
        elif "Initializing script creation system" in message:
            return 3
        elif "Console capture test" in message:
            return 5
        elif "Creating EnhancedAutoGenSystem" in message:
            return 6
        elif "Initializing Enhanced AutoGen" in message:
            return 7
        elif "All 6 agents initialized successfully" in message:
            return 10

        # ========== PRO single-pass path (8-90%) ==========
        elif "Pro mode" in message:
            return 8
        elif "PRO SINGLE-PASS SCRIPT WRITER" in message:
            return 12
        elif ("writing the ENTIRE script" in message
              or "Pro writer:" in message
              or "Loading the golden reference" in message):
            return 18
        elif "📝 writing" in message:  # streaming word-count ticks
            return 55
        elif "Pro script complete" in message:
            return 90

        # ========== STEP 1: TOPIC ENHANCEMENT (10-20%) ==========
        elif "STEP 1: Topic Enhancement" in message or "Topic Enhancement & Chapter Planning" in message:
            return 12
        elif "Running Script-Topic-Assistant-Agent" in message:
            return 14
        elif "Topic enhanced" in message and "chars" in message:
            return 20

        # Chapter extraction debug and breakdown display (20-21%)
        elif "DEBUG: Found" in message and "chapter matches" in message:
            return 20  # Show debug info right after topic enhanced
        elif "Raw Match" in message or "Skipped:" in message or "Trimming from" in message:
            return 20  # Show all debug messages
        elif "Chapter Planning Complete [21%]" in message:
            return 21
        elif "📋 CHAPTER BREAKDOWN:" in message:
            return 21
        elif "Chapter" in message and ":" in message and "/" not in message and "completed" not in message:
            # Matches "Chapter 1: Title" but not "Chapter 1/5" or "Chapter 1 completed"
            return 21

        # ========== STEP 2: CHAPTER WRITING (20-55%) ==========
        elif "STEP 2: Chapter-by-Chapter Script Writing" in message:
            return 22
        elif "Fetching style references" in message:
            return 24
        elif "Retrieved transcript style references" in message:
            return 26

        # Filter out "Writing Chapter X/Y" - don't update progress when starting
        elif "Writing Chapter" in message and "/" in message:
            return None  # Don't change progress while starting to write

        # Track individual chapter completion ONLY when done (26% to 55%)
        elif "Chapter" in message and "completed" in message and "chars" in message:
            match = re.search(r'Chapter (\d+)/(\d+)', message)
            if match:
                completed_num, total = int(match.group(1)), int(match.group(2))
                # Progress from 26% to 55%
                chapter_progress = int(26 + (completed_num * 29 / total))
                return min(chapter_progress, 55)
            return 40

        elif "Combined all" in message and "chapters into full script" in message:
            return 55

        # ========== STEP 3: SCRIPT REVIEW (55-80%) ==========
        elif "STEP 3: Script Review" in message:
            return 57
        elif "Running Script-Review-Agent" in message and "Script-Review-Agent" in message:
            return 59
        elif "Script reviewed" in message and "chars" in message:
            return 62
        elif "Retrying with chapter-by-chapter revision" in message:
            return 64

        # Filter out "Reviewing Chapter X/Y" - don't update progress when starting
        elif "Reviewing Chapter" in message and "/" in message:
            return None  # Don't change progress while starting review

        # Reviewer debug output (show what reviewer returned)
        elif "🔍 DEBUG - Reviewer Response Preview" in message:
            return 65  # Show during review phase
        elif "Contains '" in message and "': " in message:
            return 65  # Show debug checks

        # Track chapter-by-chapter review progress ONLY when complete (65% to 78%)
        elif "Chapter" in message and "revised" in message and "chars" in message:
            match = re.search(r'Chapter (\d+)/(\d+)', message)
            if match:
                completed_num, total = int(match.group(1)), int(match.group(2))
                # Progress from 65% to 78%
                review_progress = int(65 + (completed_num * 13 / total))
                return min(review_progress, 78)
            return 70

        elif "Assembling" in message and "revised chapters" in message:
            return 79
        elif "All" in message and "chapters revised individually" in message:
            return 80

        # Step 3 failure/skip paths (previously invisible to the UI)
        elif "Script Review failed or timed out" in message:
            return 58
        elif "FALLBACK: Skipping review" in message:
            return 58
        elif "revision failed, using original" in message:
            return 70
        elif "Script Review skipped" in message:
            return 80

        # Review feedback summary
        elif "📋 REVIEW FEEDBACK SUMMARY" in message:
            return 80
        elif "Total chapters reviewed:" in message:
            return 80
        elif "Full review feedback saved to:" in message:
            return 80

        # ========== STEP 3.5: QUOTES & STATISTICS (80-81%) ==========
        elif "STEP 3.5: Quotes & Statistics Generation" in message:
            return 80
        elif "Quotes & Statistics generated" in message and "chars" in message:
            return 81
        elif "Quotes/Stats generation failed" in message:
            return 81
        elif "Exception in Quotes/Stats generation" in message:
            return 81
        elif "Continuing workflow without quotes/stats" in message:
            return 81
        elif "Quotes & Statistics section inserted" in message:
            return 81

        # ========== STEP 4: HOOK & SUMMARY (81-83%) ==========
        elif "STEP 4: Hook & Summary Generation" in message:
            return 81
        elif "Hook generated" in message and "chars" in message:
            return 82
        elif "Summary generated" in message and "chars" in message:
            return 82
        elif "Hook prepended to script" in message:
            return 82
        elif "Summary appended to script" in message:
            return 83

        # ========== POST-PROCESSING (83-90%) ==========
        elif "SEQUENTIAL WORKFLOW COMPLETED" in message:
            return 83
        elif "Script enhanced with formatting" in message:
            return 83

        # YouTube Metadata (83-85%)
        elif "Generating YouTube upload metadata" in message:
            return 83
        elif "YouTube metadata generated" in message:
            return 85

        # B-roll Search Terms (85-87%)
        elif "Generating B-roll search terms" in message:
            return 85
        elif "B-roll table generated" in message:
            return 87

        # Demo Packages (87-90%)
        elif "Creating demo packages" in message:
            return 88
        elif "Demo packages generated" in message:
            return 90

        # ========== THUMBNAIL GENERATION (90-100%) ==========
        elif "Generating" in message and "thumbnail" in message:
            return 92
        elif "Generated" in message and "thumbnails" in message:
            return 98
        elif "Script creation completed" in message:
            return 100

        return None  # Don't change progress for unrecognized messages

    def flush(self):
        self.original_stdout.flush()

    def fileno(self):
        """Return file descriptor for compatibility"""
        return self.original_stdout.fileno()

    def isatty(self):
        """Return whether this is a terminal"""
        return self.original_stdout.isatty()

    def readable(self):
        """Return whether file is readable"""
        return False

    def writable(self):
        """Return whether file is writable"""
        return True

    def seekable(self):
        """Return whether file is seekable"""
        return False

    def __getattr__(self, name):
        """Delegate unknown attributes to original stdout"""
        return getattr(self.original_stdout, name)


class ProgressStreamer:
    """Handles Server-Sent Events progress streaming"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.queue = queue.Queue()
        self.result = None
        self.done = False

    def send_update(self, message: str, progress: int = None):
        """Send a progress update"""
        # Don't send updates with no progress - they would reset to default
        if progress is None:
            return

        # Treat progress<0 as a terminal failure so the SSE stream closes and
        # the UI spinner stops (otherwise the client waits forever).
        is_terminal = (progress == 100) or (progress is not None and progress < 0)
        update = {
            "message": message,
            "progress": progress,
            "timestamp": time.time(),
            "done": is_terminal,
            "error": progress is not None and progress < 0,
        }

        try:
            logger.info(
                f"🔍 send_update: putting message in queue for session {self.session_id}")
            self.queue.put(json.dumps(update))
            logger.info(f"🔍 send_update: message queued successfully")
            if is_terminal:
                logger.info(
                    f"🔍 send_update: marking done=True for session {self.session_id} (progress={progress})")
                self.done = True
            logger.info(f"🔍 send_update: method completed successfully")
        except Exception as e:
            logger.error(f"Failed to send update: {e}")


async def process_script_creation(session_id, topic, audience, tone,
                                  video_length, production_type, goals,
                                  quick_test=False, checkboxes=None,
                                  heygen_template_id="", heygen_api_key="",
                                  heygen_voice_id="", grok_api_key="",
                                  description="", script_format="teaching"):
    """Clean script creation with only console capture"""
    logger.info(f"🎬 SCRIPT CREATION STARTED: session={session_id}")
    if quick_test:
        logger.info("⚡ QUICK TEST: 1-chapter mode enabled")

    # Default to script only if no checkboxes provided
    if checkboxes is None:
        checkboxes = {"script": True}

    try:
        if session_id not in progress_streams:
            logger.error(f"❌ Session {session_id} not found!")
            return

        streamer = progress_streams[session_id]
        resolved_script_title = topic
        run_output_dir = _get_run_output_dir(
            resolved_script_title, create=True)

        # Initial progress
        streamer.send_update("🚀 Initializing script creation system...", 5)

        # Import the system
        from linedrive_azure.agents.enhanced_autogen_system import (
            EnhancedAutoGenSystem
        )

        # Set up console capture
        console_capture = ConsoleCapture(streamer)
        original_stdout = sys.stdout

        # Note: Removed background progress updater thread as it was
        # interfering with message-based progress tracking

        try:
            # Redirect stdout to capture console output
            sys.stdout = console_capture

            # Send a test message to verify streaming works
            streamer.send_update(
                "🧪 Console capture test - starting script creation", 5)

            # Initialize system (this will be captured). Pro mode uses no
            # agents, so run it quietly (verbose=False) and print a Pro-specific
            # line instead of the multi-agent initialization chatter.
            _is_pro = (script_format == "pro")
            if _is_pro:
                system = EnhancedAutoGenSystem(
                    verbose=False, script_format=script_format)
            else:
                print("🔧 Creating EnhancedAutoGenSystem...")
                system = EnhancedAutoGenSystem(
                    verbose=True, script_format=script_format)
                print(f"🔧 All 6 agents initialized successfully "
                      f"(format: {script_format})")

            # Run the workflow with timeout to prevent hanging
            print("🚀 Starting script workflow with 20-minute timeout...")

            # DEBUG: Add detailed logging for hang investigation
            print("🔍 DEBUG: About to call async workflow method")
            print(f"📋 Checkboxes received: {checkboxes}")
            print(f"🎯 quick_test: {quick_test}, topic: {topic[:50]}...")
            print(
                f"🔍 DEBUG: Current thread: {threading.current_thread().name}")
            print(
                f"🔍 DEBUG: ConsoleCapture active: {isinstance(sys.stdout, ConsoleCapture)}")

            # Style memory: prepend recent saved scripts as a style reference so
            # the Script Writer keeps new scripts consistent in voice, structure,
            # and pacing. Built into a LOCAL copy of the brief only — the pure
            # `description` is what gets persisted, so style refs never
            # recursively feed themselves back into future generations.
            topic_description = description or ""
            try:
                _style_block = _build_style_context_block()
                if _style_block:
                    topic_description = (
                        (topic_description + _style_block)
                        if topic_description else _style_block.strip())
            except Exception as _e:
                logger.warning(f"⚠️ style context build failed: {_e}")

            try:
                print("🔍 DEBUG: Calling asyncio.wait_for with async method")
                result = await asyncio.wait_for(
                    system.run_complete_script_workflow_sequential(
                        script_topic=topic,
                        topic_description=topic_description,
                        audience=audience,
                        tone=tone,
                        script_length=video_length,
                        max_chapters=1 if quick_test else 8,
                        hook_summary=checkboxes.get("hook_summary", False),
                        script_format=script_format,
                    ),
                    # 20 minutes - accounts for Script Writer (~5min) + Script Review (~12min)
                    timeout=1200
                )
                print("🔍 DEBUG: Async workflow completed successfully")

            except asyncio.TimeoutError:
                print("🔍 DEBUG: AsyncIO timeout occurred")
                print("⚠️ Workflow timeout - using fallback approach")
                streamer.send_update(
                    "⚠️ Script creation taking longer than expected, "
                    "trying alternative approach...", 85
                )

                # Fallback: Create a simpler script without revision
                result = {
                    "success": False,
                    "error": "Workflow timeout - chapter revision taking too long",
                    "timeout": True
                }
            except asyncio.TimeoutError:
                print("⚠️ Workflow timeout - using fallback approach")
                streamer.send_update(
                    "⚠️ Script creation taking longer than expected, "
                    "trying alternative approach...", 85
                )

                # Fallback: Create a simpler script without revision
                result = {
                    "success": False,
                    "error": "Workflow timeout - chapter revision taking too long",
                    "timeout": True
                }

        finally:
            # Always restore stdout
            sys.stdout = original_stdout

        # Debug: Check what we actually got
        print(f"🔍 DEBUG: Result type: {type(result)}")
        if isinstance(result, dict):
            print(f"🔍 DEBUG: Result keys: {list(result.keys())}")
        else:
            print(f"🔍 DEBUG: Result value: {result}")
            # Convert string result to error format
            result = {"success": False, "error": str(result)}

        if result.get("success"):
            # EXACT COPY OF WORKING CONSOLE UI LOGIC
            print(f"\n🎉 COMPLETE 4-AGENT WORKFLOW FINISHED!")
            print("=" * 60)
            print(f"📋 Topic: {topic}")
            print(f"👥 Audience: {audience}")
            print(f"💬 Tone: conversational and educational")
            print(f"⏱️ Length: {video_length}")
            print("-" * 60)
            print(f"✅ Topic Enhanced by Topic Assistant")
            print(f"✅ Script Created by Script Writer")
            print(f"✅ Script Reviewed by Script Reviewer")
            print(f"✅ Sequential Workflow Completed Successfully")

            # Use script content directly (no boilerplate intro). Tidy the raw
            # writer output first: drop [Visual Cue: …] blocks (visuals are added
            # later by the Grok Imagine stage) and collapse the blank lines the
            # writer puts between every sentence into single-spaced Host blocks.
            raw_script_content = _tidy_generated_script(result["script_content"])

            # Enhanced script with bold tool formatting (EXACT COPY - NO TIMEOUTS!)
            from console_ui.text_processing import (
                enhance_script_with_bold_tools,
                extract_tool_links_and_info,
            )

            enhanced_script_content = enhance_script_with_bold_tools(
                raw_script_content)
            print("✅ Script enhanced with bold tool formatting")
            # Force progress update for enhancement step
            streamer.send_update("✅ Script enhanced with formatting", 98)

            # Use enhanced script as final content (EXACT COPY)
            final_script_content = enhanced_script_content

            # OPTIONAL: Shorten script to fit requested video_length.
            # Same logic as in process_existing_script — agent-based condense.
            if checkboxes.get("shorten_script", False):
                try:
                    import re as _re_short
                    _vl_match = _re_short.search(r"(\d+(?:\.\d+)?)", str(video_length or ""))
                    _target_minutes = float(_vl_match.group(1)) if _vl_match else 10.0
                    _wpm = 150
                    _target_words = int(round(_target_minutes * _wpm))

                    def _host_word_count_create(text: str) -> int:
                        # Ignore production-only [PRODUCTION …] notes entirely.
                        text = _PRODUCTION_BLOCK_RE.sub(" ", text)
                        blocks = _re_short.findall(
                            r"(?:^|\n)\s*(?:#{1,6}\s*)?\**\s*host\s*\**\s*:\s*\**\s*([\s\S]*?)(?="
                            r"\n\s*(?:#{1,6}\s+\S|(?:#{1,6}\s*)?(?:\*\*[^*\n]{1,40}\*\*\s*:|host\s*:|heading\s*:|chapter\s+\d|visual\s+cue\s*:|b-?roll\s*:)|---+|===+)"
                            r"|\Z)",
                            text,
                            flags=_re_short.IGNORECASE,
                        )
                        return sum(len(b.split()) for b in blocks)

                    _before_host = _host_word_count_create(final_script_content)
                    # If user picked a percent reduction, compute target from current host words.
                    # Otherwise fall back to duration-derived target.
                    _percent_raw = str(checkboxes.get("shorten_percent", "")).strip().lower()
                    _target_words_override = None
                    if _percent_raw and _percent_raw != "target":
                        try:
                            _pct = int(_percent_raw)
                            if 0 < _pct < 100 and _before_host > 0:
                                _target_words_override = int(round(_before_host * (1 - _pct / 100.0)))
                        except Exception:
                            _target_words_override = None
                    _effective_target = _target_words_override if _target_words_override else _target_words
                    streamer.send_update(
                        f"✂️ Shortening to ~{_target_minutes:.0f} min (target ~{_effective_target} Host words, current {_before_host})",
                        98,
                    )
                    if _before_host > _effective_target * 1.05:
                        from linedrive_azure.agents.script_shorten_agent_client import (
                            ScriptShortenAgentClient,
                        )
                        _agent = ScriptShortenAgentClient()
                        # Shield [PRODUCTION …] blocks from the shorten agent.
                        _short_masked, _short_blocks = _mask_production_blocks(
                            final_script_content)
                        _r = _agent.shorten_to_target(
                            script_content=_short_masked,
                            target_minutes=_target_minutes,
                            wpm=_wpm,
                            timeout=600,
                            target_words_override=_target_words_override,
                            reduction_percent=(int(_percent_raw) if _target_words_override else None),
                            current_host_words=_before_host,
                        )
                        if _r.get("success") and _r.get("response"):
                            _short = _r["response"].strip()
                            _short = _re_short.sub(r"^```[a-zA-Z]*\n", "", _short)
                            _short = _re_short.sub(r"\n```\s*$", "", _short)
                            if _short:
                                final_script_content = _restore_or_keep(
                                    _short, _short_blocks, final_script_content)
                                _after = _host_word_count_create(final_script_content)
                                streamer.send_update(
                                    f"✅ Shortened: Host words {_before_host} → {_after}",
                                    98,
                                )
                except Exception as _se:
                    logger.error(f"❌ Shorten (create flow) error: {_se}")

            # Use the user's requested topic for folder/file naming.
            # If topic is empty, fall back to a title extracted from the generated content.
            extracted_script_title = _extract_script_title_for_output(
                final_script_content, fallback=topic)
            resolved_script_title = (
                topic or extracted_script_title or "Untitled Script").strip()
            run_output_dir = _get_run_output_dir(
                resolved_script_title, create=True)
            print(f"📁 Using run folder: {run_output_dir}")

            # Extract tool links for YouTube description (EXACT COPY - NO TIMEOUTS!)
            tool_links = extract_tool_links_and_info(final_script_content)
            tool_count = len(tool_links.splitlines())
            print(f"📊 Extracted {tool_count} tool references")
            # Force progress update for tool extraction
            streamer.send_update(
                f"📊 Extracted {tool_count} tool references", 99)

            # Add tool links to the script content for YouTube description (EXACT COPY)
            final_script_with_tools = final_script_content + "\n\n" + "=" * 60 + "\n"
            final_script_with_tools += "� YOUTUBE VIDEO DESCRIPTION\n"
            final_script_with_tools += "=" * 60 + "\n"
            final_script_with_tools += (
                "Copy the section below for your YouTube video description:\n\n"
            )
            final_script_with_tools += f"🎥 {topic}\n\n"
            final_script_with_tools += tool_links
            final_script_with_tools += "\n\n🔔 Don't forget to SUBSCRIBE for more AI tools and productivity tips!"
            final_script_with_tools += "\n� What tools would you like to see featured next? Drop a comment below!"

            # Store result (SIMPLIFIED)
            # Initialize variables that will be used later
            youtube_upload_details = None
            curl_commands = None  # Initialize curl commands variable
            edl_content = None  # Initialize EDL content variable
            edl_filename = None  # Initialize EDL filename variable
            broll_table = None
            broll_rows = []

            # NEW: Generate B-roll Table using AI Agent (skip unless checkbox checked)
            print(
                f"🔍 DEBUG: Checking broll - checkbox: {checkboxes.get('broll', False)}, quick_test: {quick_test}")
            if not quick_test and checkboxes.get("broll", False):
                print("✅ DEBUG: B-roll condition TRUE - calling agent")
                try:
                    print("\n📊 Generating B-roll Search Terms Table...")
                    streamer.send_update(
                        "📊 Generating B-roll search terms...", 97.5)

                    try:
                        from linedrive_azure.agents import ScriptBRollAgentClient
                    except ImportError as import_err:
                        print(f"⚠️ B-roll agent not available: {import_err}")
                        raise

                    broll_agent = ScriptBRollAgentClient()
                    print("✅ B-roll agent initialized")

                    # Generate B-roll table WITH timecodes for EDL export
                    broll_result = broll_agent.generate_broll_table_with_timecodes(
                        script_content=final_script_content,
                        script_title=topic,
                        words_per_minute=150,  # Adjust based on speaking pace
                        timeout=300  # denser 48-60 row table needs more time
                    )

                    if broll_result.get("success", False):
                        broll_table = broll_result.get("table", "")
                        parsed_data = broll_result.get("parsed_data", [])
                        broll_rows = parsed_data

                        print(
                            f"✅ B-roll table generated ({len(broll_table)} characters, {len(parsed_data)} entries)")
                        streamer.send_update(
                            "✅ B-roll table generated", 98.5)

                        # Persist the broll table to {run}/broll/ (the same
                        # folder Grok videos are saved to): broll_table.md (raw)
                        # + broll_table.docx enriched with a Grok Imagine Prompt
                        # column so weak clips can be regenerated by copying the
                        # scene's prompt.
                        try:
                            streamer.send_update(
                                "🎨 Writing B-roll Word doc + Grok prompts...", 98.7)
                        except Exception:
                            pass
                        _persist_broll_table_artifacts(
                            broll_table, parsed_data,
                            run_output_dir / "broll", theme=topic,
                            script=final_script_content)

                        # Append B-roll table to script
                        broll_section = f"\n\n{'=' * 80}\n"
                        broll_section += "# 🎬 B-ROLL SEARCH TERMS TABLE WITH TIMECODES\n"
                        broll_section += f"{'=' * 80}\n\n"
                        broll_section += broll_table

                        final_script_with_tools += broll_section
                        print("✅ B-roll table appended to script")

                        # Generate EDL file for DaVinci Resolve
                        edl_content = None
                        edl_filename = None
                        if parsed_data:
                            try:
                                import time

                                # Create filename with timestamp
                                timestamp = time.strftime("%Y%m%d_%H%M%S")
                                edl_filename = f"broll_markers_{timestamp}.edl"
                                edl_dir = run_output_dir / "MDL"
                                edl_dir.mkdir(parents=True, exist_ok=True)
                                edl_path = edl_dir / edl_filename

                                edl_result = broll_agent.create_edl_markers(
                                    broll_data=parsed_data,
                                    output_file=str(edl_path),
                                    frame_rate='24'
                                )

                                if edl_result.get("success"):
                                    print(
                                        f"✅ EDL file created: {edl_filename} ({edl_result.get('marker_count')} markers)")
                                    streamer.send_update(
                                        f"✅ EDL file created: {edl_filename}", 98.7)

                                    # Read EDL content for frontend display
                                    try:
                                        with open(edl_path, 'r', encoding='utf-8') as f:
                                            edl_content = f.read()
                                        print(
                                            f"✅ EDL content read ({len(edl_content)} bytes)")
                                    except Exception as read_error:
                                        print(
                                            f"⚠️ Could not read EDL file: {read_error}")

                                    # Add EDL info to script
                                    edl_section = f"\n\n{'=' * 80}\n"
                                    edl_section += "# 📋 DAVINCI RESOLVE EDL MARKERS\n"
                                    edl_section += f"{'=' * 80}\n\n"
                                    edl_section += f"**EDL File Generated:** `{edl_filename}`\n\n"
                                    edl_section += f"**Total Markers:** {edl_result.get('marker_count')}\n\n"
                                    edl_section += "**Import Instructions:**\n"
                                    edl_section += "1. Open DaVinci Resolve\n"
                                    edl_section += "2. Go to File > Import > Timeline Markers from EDL\n"
                                    edl_section += f"3. Select the file: `{edl_filename}`\n"
                                    edl_section += "4. Markers will be placed at the specified timecodes\n"
                                    edl_section += "5. Each marker shows the B-roll search term and description\n\n"

                                    final_script_with_tools += edl_section
                                    print("✅ EDL instructions appended to script")
                                else:
                                    print(
                                        f"⚠️ EDL creation failed: {edl_result.get('error')}")

                            except Exception as edl_error:
                                print(f"⚠️ EDL generation error: {edl_error}")
                        else:
                            print("⚠️ No parsed data available for EDL generation")
                    else:
                        print(
                            f"⚠️ B-roll table generation failed: {broll_result.get('error')}")

                except Exception as broll_error:
                    print(f"⚠️ B-roll table generation error: {broll_error}")
            else:
                print("⚡ Quick test: Skipping B-roll table generation")

            # NEW: Generate B-roll Images using Gemini (only if broll_images checkbox checked)
            broll_images = None
            if not quick_test and checkboxes.get("broll_images", False) and broll_table:
                try:
                    print("\n🎨 Generating B-roll Images...")
                    streamer.send_update("🎨 Generating B-roll images...", 98.8)

                    from tools.media.broll_image_generator import BRollImageGenerator

                    broll_gen = BRollImageGenerator()
                    print("✅ B-roll image generator initialized")

                    def _create_broll_progress(message, current, total, image_info=None):
                        try:
                            streamer.send_update(message, 99)
                        except Exception:
                            pass
                        try:
                            if image_info and image_info.get("success"):
                                src = image_info.get(
                                    "filename") or image_info.get("filepath")
                                dst = _copy_to_output_subfolder(
                                    src, "images", script_title=resolved_script_title)
                                if dst:
                                    streamer.send_update(
                                        f"💾 Saved → {dst}", 99)
                        except Exception as copy_err:
                            logger.warning(
                                f"⚠️ live copy of B-roll image failed: {copy_err}")

                    # Generate images from ALL entries in the B-roll table
                    # max_images now refers to max ENTRIES (each gets 3 variations)
                    # Set to None to generate ALL entries with 3 variations each
                    _broll_out_dir = run_output_dir / "images"
                    image_results = broll_gen.generate_all_broll_images(
                        broll_table=broll_table,
                        script_title=topic,
                        # Generate all entries (matching script processing workflow)
                        max_images=None,
                        progress_callback=_create_broll_progress,
                        output_dir=_broll_out_dir,
                    )

                    if image_results.get("success"):
                        broll_images = image_results.get("images", [])
                        entries_count = image_results.get("total_entries", 0)
                        variations = image_results.get(
                            "variations_per_entry", 3)
                        print(
                            f"✅ Generated {len(broll_images)} B-roll images ({entries_count} entries × {variations} variations)")
                        streamer.send_update(
                            f"✅ Generated {len(broll_images)} B-roll images ({entries_count} entries × {variations} variations)", 99)
                    else:
                        print(
                            f"⚠️ B-roll image generation failed: {image_results.get('error')}")

                except Exception as broll_img_error:
                    print(
                        f"⚠️ B-roll image generation error: {broll_img_error}")

            # NEW: Defer Grok AI generation until user selects rows from B-roll table
            grok_videos = []
            if not quick_test and checkboxes.get("grok_videos", False):
                if not broll_table:
                    # Prefer reusing a B-roll table already embedded in the script before regenerating one.
                    try:
                        extracted_table = _extract_broll_table_from_script(
                            final_script_content)
                    except Exception:
                        extracted_table = ""
                    if extracted_table:
                        broll_table = extracted_table
                        print(
                            f"📋 Grok Videos: reusing existing B-roll table from script ({len(broll_table)} chars)")
                        streamer.send_update(
                            "📋 Grok Videos: using existing B-roll table from script", 98
                        )
                if not broll_table:
                    print(
                        "🤖 Grok Videos: broll_table not available, auto-generating...")
                    streamer.send_update(
                        "🤖 Grok Videos: generating B-roll table first...", 98)
                    try:
                        from linedrive_azure.agents import ScriptBRollAgentClient
                        broll_agent = ScriptBRollAgentClient()
                        broll_result = broll_agent.generate_broll_table_with_timecodes(
                            script_content=final_script_content,
                            script_title=topic,
                            words_per_minute=150,
                            timeout=300
                        )
                        if broll_result.get("success", False):
                            broll_table = broll_result.get("table", "")
                            broll_rows = broll_result.get("parsed_data", [])
                            print(
                                f"✅ Auto-generated broll_table ({len(broll_table)} chars) for Grok Videos")
                        else:
                            print(
                                "⚠️ Auto broll_table generation failed for Grok Videos")
                    except Exception as auto_broll_err:
                        print(f"❌ Auto broll_table error: {auto_broll_err}")

                if broll_table:
                    total_rows = len(broll_rows) if broll_rows else 0
                    streamer.send_update(
                        f"⏸️ Select B-roll rows for Grok generation ({total_rows} available)",
                        99
                    )

            # NEW: Generate HeyGen Ready Section (only if checkbox checked)
            if checkboxes.get("heygen", False):
                try:
                    print("\n🎬 Generating HeyGen Ready section...")
                    from console_ui.text_processing import (
                        extract_heygen_host_script,
                        scrub_heygen_text,
                    )

                    # Strip [PRODUCTION …] editing notes so the avatar never
                    # narrates them.
                    _hg_src = _strip_production_blocks(final_script_content)
                    heygen_script = extract_heygen_host_script(_hg_src)

                    # Fallback: if no Host: markers found, scrub the raw script
                    # (strips title, metadata, chapter headings, stage directions, etc.)
                    if not heygen_script:
                        print(
                            "⚠️ No Host: markers found - scrubbing full script for HeyGen section")
                        heygen_script = scrub_heygen_text(_hg_src)

                    if heygen_script:
                        heygen_section = f"\n\n{'=' * 80}\n"
                        heygen_section += "# 🎬 HEYGEN READY SCRIPT\n"
                        heygen_section += f"{'=' * 80}\n\n"
                        heygen_section += heygen_script

                        final_script_with_tools += heygen_section
                        print(
                            f"✅ HeyGen section added ({len(heygen_script)} characters, {len(heygen_script.split())} words)")

                        # Generate curl commands only if curl checkbox is checked
                        print(
                            f"🔍 DEBUG: curl checkbox = {checkboxes.get('curl', False)}")
                        if checkboxes.get("curl", False):
                            try:
                                from console_ui.text_processing import generate_heygen_curl_commands

                                print("\n🔨 Generating HeyGen curl commands...")
                                curl_commands = generate_heygen_curl_commands(
                                    _strip_production_blocks(
                                        final_script_with_tools),
                                    topic,  # script_title
                                    heygen_api_key,
                                    heygen_template_id,
                                    heygen_voice_id
                                )

                                if curl_commands:
                                    # Store curl commands separately (don't append to script)
                                    print(
                                        f"✅ Generated {curl_commands.count('curl --request POST')} curl commands")
                                    _live_curl_dst = _save_curl_commands_live(
                                        curl_commands, resolved_script_title)
                                    if _live_curl_dst:
                                        print(
                                            f"💾 Saved curl commands → {_live_curl_dst}")
                                else:
                                    print("⚠️ No curl commands generated")
                                    curl_commands = None

                            except Exception as curl_error:
                                print(
                                    f"⚠️ Curl generation error: {curl_error}")
                                curl_commands = None
                    else:
                        print("⚠️ No host dialogue found for HeyGen section")

                except Exception as heygen_error:
                    print(
                        f"⚠️ HeyGen section generation error: {heygen_error}")

            # NEW: Generate Demo Packages (skip unless checkbox checked)
            demo_packages = None
            if not quick_test and checkboxes.get("demo", False):
                try:
                    print("\n🎥 Generating Demo Packages...")
                    streamer.send_update("🎥 Creating demo packages...", 96)

                    from linedrive_azure.agents.openai_demo_agent_client import OpenAIDemoAgentClient

                    demo_client = OpenAIDemoAgentClient()
                    demo_result = demo_client.generate_demo_packages(
                        final_script_content,
                        max_tokens=12000,
                        audience=audience
                    )

                    if demo_result.get("success"):
                        demo_packages = demo_result["response"]
                        print(
                            f"✅ Demo packages created ({len(demo_packages)} characters)")
                        streamer.send_update("✅ Demo packages generated", 97)

                        # Extract HeyGen content from demos
                        from console_ui.text_processing import (
                            extract_demo_heygen_content,
                            format_demo_steps_plain
                        )
                        demo_heygen_content = extract_demo_heygen_content(
                            demo_packages)

                        if demo_heygen_content:
                            print(
                                f"✅ Demo HeyGen section prepared ({len(demo_heygen_content)} characters)")

                        # Format demo packages - remove numbers/bullets from steps
                        formatted_demo_packages = format_demo_steps_plain(
                            demo_packages)

                        # Append demo packages to final script
                        demo_section = f"\n\n{'=' * 80}\n"
                        demo_section += "# 🎥 DEMO PACKAGES\n"
                        demo_section += f"{'=' * 80}\n\n"
                        demo_section += formatted_demo_packages

                        final_script_with_tools += demo_section
                        print("✅ Demo packages appended to script")
                    else:
                        print(
                            f"⚠️ Demo generation failed: {demo_result.get('error', 'Unknown error')}")

                except Exception as demo_error:
                    print(f"⚠️ Demo generation error: {demo_error}")
            else:
                print("⚡ Quick test: Skipping demo package generation")

            # Store the original script before flow analysis
            original_script_before_flow = final_script_with_tools
            flow_analysis_report = None

            # NEW: Flow & Repetition Analysis (only if checkbox checked)
            # IMPORTANT: This runs AFTER all content is assembled
            if checkboxes.get("flow_analysis", False):
                try:
                    print("\n🔄 Analyzing script for repetition and flow...")
                    streamer.send_update(
                        "🔄 Analyzing script for repetition and flow...", 96)

                    from linedrive_azure.agents import ScriptRepeatAndFlowAgentClient

                    flow_agent = ScriptRepeatAndFlowAgentClient()
                    # Shield [PRODUCTION …] blocks from the flow agent.
                    _flow_masked, _flow_blocks = _mask_production_blocks(
                        final_script_with_tools)
                    flow_result = flow_agent.analyze_and_improve_flow(
                        script_content=_flow_masked,
                        script_title=topic,
                        target_audience=audience,
                        timeout=300
                    )

                    logger.info(
                        f"📊 Flow agent result: success={flow_result.get('success')}, keys={list(flow_result.keys())}")

                    if flow_result.get("success", False):
                        improved_script = flow_result.get(
                            "improved_script", "")
                        repetition_analysis = flow_result.get(
                            "repetition_analysis", "")
                        flow_improvements = flow_result.get(
                            "flow_analysis", "")

                        logger.info(
                            f"📊 Improved script length: {len(improved_script)}, rep analysis: {len(repetition_analysis)}, flow: {len(flow_improvements)}")

                        if improved_script:
                            # Build analysis report
                            analysis_section = f"\n\n{'=' * 80}\n"
                            analysis_section += "# 🔄 FLOW & REPETITION ANALYSIS\n"
                            analysis_section += f"{'=' * 80}\n\n"

                            if repetition_analysis:
                                analysis_section += "## Repetition Analysis\n\n"
                                analysis_section += f"{repetition_analysis}\n\n"

                            if flow_improvements:
                                analysis_section += "## Flow Improvements\n\n"
                                analysis_section += f"{flow_improvements}\n\n"

                            # Store analysis for separate display
                            flow_analysis_report = analysis_section

                            # Update final_script_with_tools to improved version (WITHOUT analysis appended)
                            final_script_with_tools = _restore_or_keep(
                                improved_script, _flow_blocks,
                                final_script_with_tools)

                            streamer.send_update(
                                f"✅ Flow analysis complete - script improved ({len(improved_script)} chars)",
                                97
                            )
                            print(
                                f"✅ Flow analysis complete - script improved ({len(improved_script)} chars)")
                        else:
                            logger.warning(
                                "⚠️ Flow agent returned empty improved script")
                            print("⚠️ Flow agent returned empty improved script")
                    else:
                        logger.warning(
                            f"⚠️ Flow analysis failed - result: {flow_result}")
                        print(f"⚠️ Flow analysis failed")

                except Exception as flow_error:
                    logger.error(f"❌ Flow analysis error: {flow_error}")
                    print(f"⚠️ Flow analysis error: {flow_error}")
            else:
                print("⚡ Skipping flow & repetition analysis (not selected)")

            # NEW: Generate YouTube Upload Details (AFTER flow analysis)
            print(
                f"🔍 DEBUG: Checking youtube_details - checkbox: {checkboxes.get('youtube_details', False)}, quick_test: {quick_test}")
            if not quick_test and checkboxes.get("youtube_details", False):
                print("✅ DEBUG: YouTube Details condition TRUE - calling agent")
                try:
                    print("\n📺 Generating YouTube Upload Details...")
                    streamer.send_update(
                        "📺 Generating YouTube upload metadata...", 97)

                    from linedrive_azure.agents import YouTubeUploadDetailsAgentClient

                    youtube_agent = YouTubeUploadDetailsAgentClient()
                    youtube_result = youtube_agent.generate_upload_details(
                        script_content=final_script_content,
                        script_title=topic,
                        target_audience=audience,
                        video_length=video_length,
                        primary_keywords=None,
                        channel_focus=None,
                        timeout=180
                    )

                    if youtube_result.get("success", False):
                        youtube_upload_details = youtube_result.get(
                            "upload_details", "")
                        print(
                            f"✅ YouTube upload details generated ({len(youtube_upload_details)} characters)")
                        streamer.send_update(
                            "✅ YouTube metadata generated", 98)

                        # Append YouTube details to script
                        youtube_section = f"\n\n{'=' * 80}\n"
                        youtube_section += "# 📺 YOUTUBE UPLOAD DETAILS\n"
                        youtube_section += f"{'=' * 80}\n\n"
                        youtube_section += youtube_upload_details

                        final_script_with_tools += youtube_section
                        print("✅ YouTube details appended to script")
                    else:
                        print(
                            f"⚠️ YouTube generation failed: {youtube_result.get('error')}")

                except Exception as youtube_error:
                    print(f"⚠️ YouTube upload details error: {youtube_error}")
            else:
                print("⚡ Quick test: Skipping YouTube details generation")

            # NEW: Generate Emotional Thumbnails (only if checkbox checked)
            thumbnail_results = None
            if checkboxes.get("thumbnails", False):
                try:
                    thumbnail_hook_text_options = _extract_thumbnail_hook_text_options(
                        hook_result=result,
                        script_text=final_script_with_tools
                    )
                    thumbnail_hook_text = thumbnail_hook_text_options[
                        0] if thumbnail_hook_text_options else ""
                    print("\n" + "="*70)
                    print("🖼️  THUMBNAIL GENERATION STARTING")
                    print("="*70)
                    print(f"📝 Topic: {resolved_script_title}")
                    print(
                        f"📄 Script length: {len(final_script_content)} chars")
                    print(
                        f"🎥 YouTube details: {'Available' if youtube_upload_details else 'None'}")
                    if thumbnail_hook_text_options:
                        print(
                            f"🏷️ Thumbnail hook text options: {thumbnail_hook_text_options}")
                        streamer.send_update(
                            f"🏷️ Thumbnail hook options: {', '.join(thumbnail_hook_text_options)}", 98
                        )
                    else:
                        print(
                            "⚠️ Thumbnail hook text not found; using script title fallback")
                        streamer.send_update(
                            "⚠️ Thumbnail hook text not found; using script title", 98
                        )

                    expected_thumbnails = 6 * \
                        len(thumbnail_hook_text_options) if thumbnail_hook_text_options else 6
                    streamer.send_update(
                        f"🖼️ Generating {expected_thumbnails} thumbnail variations...", 98)

                    from tools.media.emotional_thumbnail_generator import (
                        EmotionalThumbnailGenerator,
                    )

                    print(f"\n🔧 Initializing EmotionalThumbnailGenerator...")
                    # Let generator get API key from environment (same as test page)
                    api_key = os.getenv("GOOGLE_API_KEY", "")
                    print(
                        f"   Environment API key: {api_key[:20]}... (length: {len(api_key)})")

                    # Route thumbnails into configured output_dir/thumbnails when available.
                    _thumb_out_dir = run_output_dir / "thumbnails"
                    # No api_key param - use environment
                    thumbnail_gen = EmotionalThumbnailGenerator(
                        output_dir=_thumb_out_dir)
                    print(f"✅ Generator initialized successfully")
                    print(f"   Template: {thumbnail_gen.template_path}")
                    print(f"   Output: {thumbnail_gen.output_dir}")
                    print(
                        f"   API Key set: {'Set' if thumbnail_gen.api_key else 'MISSING'}")
                    print(
                        f"   API Key matches: {thumbnail_gen.api_key == api_key}")

                    print(f"\n🎬 Calling generate_all_thumbnails()...")
                    # always fresh — never reuse a stale cancelled event
                    thumb_cancel_evt = _threading.Event()
                    thumbnail_cancel_events[session_id] = thumb_cancel_evt
                    thumbnail_results = thumbnail_gen.generate_all_thumbnails(
                        script_title=resolved_script_title,
                        script_content=final_script_content,
                        youtube_upload_details=youtube_upload_details,
                        headline_text=thumbnail_hook_text or None,
                        headline_options=thumbnail_hook_text_options or None,
                        progress_callback=lambda msg: streamer.send_update(
                            msg, 98),
                        cancel_check=thumb_cancel_evt.is_set,
                    )

                    print(f"\n🔍 THUMBNAIL GENERATION RESULTS:")
                    print(f"   Type: {type(thumbnail_results)}")
                    print(f"   Is None: {thumbnail_results is None}")

                    if thumbnail_results:
                        print(f"   Keys: {list(thumbnail_results.keys())}")
                        output_dir = thumbnail_results.get("output_dir")
                        variations = thumbnail_results.get("variations") or []
                        if variations:
                            if output_dir:
                                print(
                                    f"   📁 Thumbnails saved to: {output_dir}")
                                streamer.send_update(
                                    f"📁 Thumbnails saved to: {output_dir}", 99
                                )
                            print(f"   Variations count: {len(variations)}")
                            print(
                                f"\n✅ Generated {len(variations)} thumbnail variations")

                            # Show details of each variation
                            for i, var in enumerate(variations, 1):
                                print(
                                    f"      #{i}: {var.get('emotion')} - {var.get('filename')}")

                            streamer.send_update(
                                f"✅ Generated {len(variations)} thumbnails", 99
                            )
                            if thumbnail_results.get("cancelled"):
                                streamer.send_update(
                                    f"🛑 Thumbnail generation stopped — keeping {len(variations)} thumbnails so far",
                                    99,
                                )
                        else:
                            print(
                                "   ⚠️ Thumbnail directory created, but no thumbnails were generated")
                            if output_dir:
                                print(f"   📁 Directory: {output_dir}")
                                streamer.send_update(
                                    f"⚠️ No thumbnails generated (directory only): {output_dir}", 99
                                )
                            attempted = thumbnail_results.get(
                                "total_attempted", 0)
                            streamer.send_update(
                                f"❌ Thumbnail generation failed (0/{attempted})", 99
                            )
                            if thumbnail_results.get("error"):
                                streamer.send_update(
                                    f"❌ Thumbnail API error: {thumbnail_results.get('error')}", 99
                                )
                            print(f"   Full results: {thumbnail_results}")
                    else:
                        print("   ⚠️ thumbnail_results is None")

                    print("="*70 + "\n")

                except Exception as thumb_error:
                    import traceback
                    err_msg = f"{type(thumb_error).__name__}: {thumb_error}"
                    print("\n" + "="*70)
                    print("❌ THUMBNAIL GENERATION ERROR")
                    print("="*70)
                    print(f"Error type: {type(thumb_error).__name__}")
                    print(f"Error message: {thumb_error}")
                    print("\n📋 Full traceback:")
                    traceback.print_exc()
                    print("="*70 + "\n")
                    streamer.send_update(
                        f"❌ Thumbnail generation error: {err_msg}", 99)
                finally:
                    thumbnail_cancel_events.pop(session_id, None)

            # Stamp a permanent Script-ID + initial Script-Version into the
            # script so every downstream artifact can be tied back to it.
            final_script_with_tools, _new_script_id, _new_script_version = (
                _ensure_script_ids(final_script_with_tools))

            saved_markdown_path, saved_docx_path = await _save_script_md_and_docx(
                resolved_script_title,
                final_script_with_tools,
            )

            streamer.result = {
                "success": True,
                "enhanced_script": final_script_with_tools,
                "script_title": resolved_script_title,
                "script_id": _new_script_id,
                "script_version": _new_script_version,
                # The creative brief that steered this run, persisted alongside
                # the script so it can be pulled back from the cloud later.
                "brief": description,
                "demo_packages": demo_packages,
                "youtube_details": youtube_upload_details,
                "thumbnail_results": thumbnail_results,
                "broll_images": broll_images,
                "grok_videos": grok_videos,
                "broll_table": broll_table,
                "broll_rows": broll_rows,
                "word_count": len(final_script_with_tools.split()),
                "reading_time": f"{len(final_script_with_tools.split()) // 150} min",
                "audience": audience,
                "production_type": production_type,
                "comparison_file": result.get("comparison_file") if isinstance(result, dict) else None,
                "chapter_comparisons": result.get("chapter_comparisons") if isinstance(result, dict) else None,
                "flow_original_script": original_script_before_flow if checkboxes.get("flow_analysis") else None,
                "flow_improved_script": final_script_with_tools if checkboxes.get("flow_analysis") and flow_analysis_report else None,
                "flow_analysis_report": flow_analysis_report,
                "edl_content": edl_content,
                "edl_filename": edl_filename,
                "curl_commands": curl_commands,
                "markdown_path": saved_markdown_path,
                "docx_path": saved_docx_path,
            }

            # Persist every artifact of this version so the script restores its
            # tabs when reopened later (Grok videos persist separately by id).
            try:
                _persist_version_artifacts(
                    _new_script_id, _new_script_version, streamer.result,
                    resolved_script_title)
            except Exception as _e:
                logger.warning(
                    f"⚠️ version artifact persist (create) failed: {_e}")

            # Debug: Log what's in the result
            print(
                f"🔍 DEBUG: Result object curl_commands = {curl_commands is not None} ({len(curl_commands) if curl_commands else 0} chars)")
            print(f"🔍 DEBUG: Result keys: {list(streamer.result.keys())}")

            # Send final completion message (SIMPLE)
            print("🎯 Sending completion message...")
            print(f"DEBUG: About to send completion for session {session_id}")
            print(
                f"DEBUG: Streamer done status before completion: {streamer.done}")

            # Send the completion message
            streamer.send_update("✅ Script creation complete!", 100)

            print("✅ Completion message sent successfully")
            print(
                f"DEBUG: Streamer done status after completion: {streamer.done}")
            print("🎉 Script creation completed successfully!")

        else:
            error_msg = result.get("error", "Unknown workflow error")
            streamer.send_update(f"❌ Script creation failed: {error_msg}", -1)
            streamer.result = {"success": False, "error": error_msg}
            print(f"❌ Script creation failed: {error_msg}")
            logger.error(
                f"❌ Script creation failed for session {session_id}: {error_msg}")

    except Exception as e:
        error_msg = f"Error: {str(e)}"
        logger.error(f"💥 Exception during script creation: {error_msg}")
        if session_id in progress_streams:
            streamer = progress_streams[session_id]
            streamer.send_update(f"❌ {error_msg}", -1)
            streamer.result = {"success": False, "error": error_msg}


async def process_existing_script(
    session_id, script_content, audience, tone,
    video_length, checkboxes, heygen_template_id="",
    heygen_api_key="", heygen_voice_id="", grok_api_key="",
    youtube_details_override: Optional[str] = None,
    broll_table_override: Optional[str] = None,
    script_filename: str = "",
    script_dir: str = "",
):
    """Process existing script with progress updates.

    youtube_details_override / broll_table_override let the caller pass
    pre-loaded artifacts (e.g. from a .docx loaded into the bottom tabs)
    so the corresponding agents are skipped entirely.
    """
    import re

    logger.info(f"📝 SCRIPT PROCESSING STARTED: session={session_id}")

    if session_id not in progress_streams:
        logger.error(f"❌ Session {session_id} not found!")
        return

    streamer = progress_streams[session_id]

    # One-shot sanitizer: strip the legacy "Hi, I'm Roz's AI Digital Twin..."
    # boilerplate intro (and its trailing `---` rule) from any uploaded /
    # re-processed script so it doesn't keep propagating downstream.
    if script_content:
        _intro_re = re.compile(
            r"^\s*Hi[, ]\s*I[\u2019']m\s+Roz['\u2019]s\s+AI\s+Digital\s+Twin\.[\s\S]*?This\s+is,?\s+AI\s+with\s+Roz\.\s*\n+"
            r"(?:---+\s*\n+)?",
            flags=re.IGNORECASE,
        )
        _new = _intro_re.sub("", script_content, count=1)
        if _new != script_content:
            logger.info(
                "🧹 Stripped legacy 'AI Digital Twin' boilerplate intro from script_content")
            script_content = _new.lstrip()

    # Every processing run bumps the Script-Version (a no-op-bump is impossible
    # here since manual edits don't reach this path). The permanent Script-ID is
    # preserved if present, else assigned. We fix both ids for the whole run so
    # all artifacts produced below can be tied to this exact version, then
    # re-stamp the final script with the same ids at the end (agents may strip
    # the lines while rewriting).
    script_content, proc_script_id, proc_script_version = _ensure_script_ids(
        script_content, bump_version=True)
    logger.info(
        f"🆔 Processing run: Script-ID={proc_script_id} Version={proc_script_version}")

    try:
        # Initialize EDL variables
        edl_content = None
        edl_filename = None

        # Calculate total steps based on checkboxes
        total_steps = sum([
            checkboxes.get("hook_summary", False),
            checkboxes.get("youtube_details", False),
            checkboxes.get("broll", False),
            checkboxes.get("broll_images", False),
            checkboxes.get("heygen", False),
            checkboxes.get("curl", False),
            checkboxes.get("demo", False),
            checkboxes.get("thumbnails", False),
            checkboxes.get("flow_analysis", False),
            checkboxes.get("grok_videos", False),
            checkboxes.get("shorten_script", False),
            checkboxes.get("grok_imagine", False),
        ])

        if total_steps == 0:
            streamer.send_update("❌ No processing options selected", -1)
            streamer.result = {"success": False,
                               "error": "No options selected"}
            return

        completed_steps = 0
        progress_per_step = 90 / total_steps  # Reserve 10% for completion

        streamer.send_update("🚀 Initializing script processing...", 5)

        # Extract title from script
        script_title = "Untitled Script"
        logger.info("📰 Extracting title from script content...")

        # 1) Prefer an explicit "Heading:" line (first one wins), but skip
        #    chapter-style headings like "Heading: Chapter 1 - ..." so the
        #    real script title (top-of-doc) can be used instead. Also skip
        #    Visual Cue / B-Roll values that occasionally appear as the
        #    first Heading: in malformed scripts.
        heading_match = None
        for _hm in re.finditer(r'^\s*Heading:\s*(.+)$', script_content, re.MULTILINE | re.IGNORECASE):
            _val = _hm.group(1).strip().strip('*').strip()
            if re.match(r'^chapter\s+\d+\b', _val, re.IGNORECASE):
                continue
            if re.match(r'^(?:visual\s*cue|b-?roll|host|hook|summary)\b', _val, re.IGNORECASE):
                continue
            heading_match = _hm
            break
        if heading_match:
            script_title = heading_match.group(1).strip().strip('*').strip()
            logger.info(f"📰 ✅ Found 'Heading:' title: '{script_title}'")
        else:
            # 2) Fall back to first markdown H1, but skip known analysis/report headings
            _SKIP_TITLE_PATTERNS = (
                'flow analysis', 'flow analysis report', 'analysis report',
                'hook summary', 'b-roll', 'broll', 'thumbnail', 'demo package',
                'youtube details', 'heygen', 'curl commands',
                'opening hook', 'hook options',
                'final hook',
                # Direction / structural labels that sometimes appear as the
                # first H1 in agent output — never valid titles.
                'visual cue', 'visualcue', 'host', 'narrator',
                'scene', 'transition', 'cut to', 'fade in', 'fade out',
                'voiceover', 'voice over', 'vo',
            )
            for m in re.finditer(r'^#+\s+(.+)$', script_content, re.MULTILINE):
                candidate = m.group(1).strip()
                normalized = re.sub(r'[^a-z0-9 ]+', ' ',
                                    candidate.lower()).strip()
                if any(p in normalized for p in _SKIP_TITLE_PATTERNS):
                    continue
                # Skip chapter headings like 'Chapter 1 - ...' or 'Chapter 2:'
                if re.match(r'^chapter\s+\d+\b', normalized):
                    continue
                # Skip ALL-CAPS section-divider headings.
                _letters_h1 = re.sub(r'[^A-Za-z]', '', candidate)
                if len(_letters_h1) >= 3 and _letters_h1.isupper():
                    continue
                script_title = candidate
                logger.info(f"📰 ✅ Found H1 title: '{script_title}'")
                break
            else:
                lines = script_content.split('\n')
                for raw_line in lines[:15]:
                    line = raw_line.strip()
                    # Iteratively strip any combination of leading emoji,
                    # bold/italic markers, and whitespace. Handles patterns
                    # like '**🎬 **VISUAL CUE:**' (two `**` separated by an
                    # emoji) which a single-pass strip would leave with a
                    # stray '**' prefix and miss the skip-regex below.
                    for _ in range(6):
                        _before = line
                        line = re.sub(r'^[\*_]+\s*', '', line)
                        line = re.sub(r'\s*[\*_]+$', '', line)
                        # Strip any leading "symbol/pictograph" emoji + space.
                        line = re.sub(
                            r'^[\U0001F000-\U0001FFFF\u2600-\u27BF]\s*',
                            '', line,
                        )
                        if line == _before:
                            break
                    line = line.strip()
                    if not line or line.startswith(('#', '-', '[')):
                        continue
                    if all(c in '_=-~' for c in line):
                        continue
                    if len(line) > 150:
                        continue
                    # Skip chapter headings
                    if re.match(r'^chapter\s+\d+\b', line, re.IGNORECASE):
                        continue
                    # Skip script-structure label lines that aren't titles.
                    if re.match(
                        r'^(?:visual\s*cue|b-?roll|host|hook|summary|heading|final\s+hook|opening\s+hook|option\s*\d+)\s*[:\-]?',
                        line, re.IGNORECASE,
                    ):
                        continue
                    # Skip ALL-CAPS section-divider lines (e.g.
                    # 'SUPPORTING RESEARCH & EXPERT PERSPECTIVES',
                    # 'PART ONE', 'INTRO'). These are bold callouts the
                    # author uses as section breaks, never the script title.
                    _letters = re.sub(r'[^A-Za-z]', '', line)
                    if len(_letters) >= 3 and _letters.isupper():
                        continue
                    script_title = line
                    logger.info(f"📰 ✅ Using line as title: '{script_title}'")
                    break

                script_title = re.sub(
                    r'^\s*#\s*', '', (script_title or '').strip())
                script_title = re.sub(
                    r'^\s*Direct\s+Video\s*-\s*', '', script_title, flags=re.IGNORECASE)
                script_title = script_title or "Untitled Script"
                logger.info(f"📰 ✅ Using line as title: '{script_title}'")

        # 0) FINAL OVERRIDE: an explicit "Title: ..." line in the script always
        # wins over Heading: / H1 / first-line fallbacks. This keeps the
        # DaVinci project name and run output folder consistent with the
        # human-authored Title line (e.g. "Title: Homeschool Heroes with AI").
        _explicit_title_match = re.search(
            r'^[ \t]*\**[ \t]*Title[ \t]*\**[ \t]*:[ \t]*\**[ \t]*(.+?)[ \t]*\**[ \t]*$',
            script_content,
            re.MULTILINE | re.IGNORECASE,
        )
        if _explicit_title_match:
            _explicit_title = _explicit_title_match.group(
                1).strip().strip('*').strip()
            if _explicit_title:
                script_title = _explicit_title
                logger.info(
                    f"📰 ⭐ Overriding with explicit 'Title:' line: '{script_title}'")

        # Ensure run_output_dir is always set (regardless of which title branch was taken)
        run_output_dir = _get_run_output_dir(script_title, create=True)
        logger.info(f"📁 Using run folder: {run_output_dir}")

        # Clean the script
        streamer.send_update("🧹 Cleaning script formatting...", 10)
        # Drop [Visual Cue: …] blocks (added later via Grok Imagine) and collapse
        # between-sentence blank lines into single-spaced Host blocks before the
        # house-format pass below.
        cleaned_script = _tidy_generated_script(script_content)

        # Remove separator lines
        cleaned_script = re.sub(r'^[_\-=~]+\s*$', '', cleaned_script,
                                flags=re.MULTILINE)
        cleaned_script = re.sub(r'\n{3,}', '\n\n', cleaned_script)

        # Remove emojis
        cleaned_script = re.sub(r'🎬|📺|📊|🎥|🎯|💡|✨|🚀', '', cleaned_script)

        # Remove markdown formatting
        cleaned_script = re.sub(r'\*\*([^*]+)\*\*', r'\1', cleaned_script)
        cleaned_script = re.sub(r'\*([^*]+)\*', r'\1', cleaned_script)
        cleaned_script = re.sub(r'__([^_]+)__', r'\1', cleaned_script)
        cleaned_script = re.sub(r'_([^_]+)_', r'\1', cleaned_script)

        # Apply clean formatting
        cleaned_script = re.sub(r'^Host:\s*$', r'**Host:**\n\n',
                                cleaned_script, flags=re.MULTILINE)
        cleaned_script = re.sub(r'^VISUAL CUE:\s*(.+)$', r'\n**VISUAL CUE:** \1',
                                cleaned_script, flags=re.MULTILINE)

        # Remove the title from the beginning of cleaned_script to avoid duplication
        # since we'll prepend it separately with proper formatting
        if script_title and script_title in cleaned_script:
            # Remove markdown title format (# Title)
            cleaned_script = re.sub(
                r'^#\s+' + re.escape(script_title) + r'\s*\n*',
                '',
                cleaned_script,
                count=1,
                flags=re.MULTILINE
            )
            # Also remove plain title at the start
            if cleaned_script.strip().startswith(script_title):
                cleaned_script = cleaned_script.strip()[
                    len(script_title):].lstrip()

        # Initialize output variables (will build final_output after all sections are generated)
        final_output = ""
        hook_text = ""
        summary_text = ""
        flow_analysis = ""
        heygen_script = None
        curl_commands = None
        hook_result = {}  # Initialize to empty dict to prevent undefined variable errors
        thumbnail_hook_text = ""
        thumbnail_hook_text_options: list[str] = []

        # OPTIONAL: Shorten script to fit requested video length.
        # When `shorten_script` is checked we call the script-review agent to
        # condense the Host: dialogue down to ~target_minutes * wpm words.
        if checkboxes.get("shorten_script", False):
            try:
                # Parse target minutes from video_length (e.g. "10 minutes")
                _vl_match = re.search(r"(\d+(?:\.\d+)?)", str(video_length or ""))
                _target_minutes = float(_vl_match.group(1)) if _vl_match else 10.0
                _wpm = 150
                _target_words = int(round(_target_minutes * _wpm))

                def _host_word_count(text: str) -> int:
                    # Ignore production-only [PRODUCTION …] notes entirely.
                    text = _PRODUCTION_BLOCK_RE.sub(" ", text)
                    blocks = re.findall(
                        r"(?:^|\n)\s*(?:#{1,6}\s*)?\**\s*host\s*\**\s*:\s*\**\s*([\s\S]*?)(?="
                        r"\n\s*(?:#{1,6}\s+\S|(?:#{1,6}\s*)?(?:\*\*[^*\n]{1,40}\*\*\s*:|host\s*:|heading\s*:|chapter\s+\d|visual\s+cue\s*:|b-?roll\s*:)|---+|===+)"
                        r"|\Z)",
                        text,
                        flags=re.IGNORECASE,
                    )
                    return sum(len(b.split()) for b in blocks)

                _before_host_words = _host_word_count(cleaned_script)
                # Resolve a target word count: percent (of current) takes precedence
                # over the duration-derived target so the user can ask for e.g. "-25%".
                _percent_raw = str(checkboxes.get("shorten_percent", "")).strip().lower()
                _target_words_override = None
                if _percent_raw and _percent_raw != "target":
                    try:
                        _pct = int(_percent_raw)
                        if 0 < _pct < 100 and _before_host_words > 0:
                            _target_words_override = int(round(_before_host_words * (1 - _pct / 100.0)))
                    except Exception:
                        _target_words_override = None
                _effective_target = _target_words_override if _target_words_override else _target_words
                streamer.send_update(
                    f"✂️ Shortening script to ~{_target_minutes:.0f} min "
                    f"(target ~{_effective_target} Host words, current {_before_host_words})",
                    12,
                )

                # Only call the agent when the current script is materially longer
                if _before_host_words > _effective_target * 1.05:
                    from linedrive_azure.agents.script_shorten_agent_client import (
                        ScriptShortenAgentClient,
                    )
                    _shorten_agent = ScriptShortenAgentClient()
                    # Shield [PRODUCTION …] blocks from the shorten agent.
                    _short_masked, _short_blocks = _mask_production_blocks(
                        cleaned_script)
                    _short_result = _shorten_agent.shorten_to_target(
                        script_content=_short_masked,
                        target_minutes=_target_minutes,
                        wpm=_wpm,
                        timeout=600,
                        target_words_override=_target_words_override,
                        reduction_percent=(int(_percent_raw) if _target_words_override else None),
                        current_host_words=_before_host_words,
                    )
                    if _short_result.get("success") and _short_result.get("response"):
                        _shortened = _short_result["response"].strip()
                        # Strip ``` code fences if the agent wrapped its reply.
                        _shortened = re.sub(r"^```[a-zA-Z]*\n", "", _shortened)
                        _shortened = re.sub(r"\n```\s*$", "", _shortened)
                        if _shortened:
                            cleaned_script = _restore_or_keep(
                                _shortened, _short_blocks, cleaned_script)
                            _after_host_words = _host_word_count(cleaned_script)
                            streamer.send_update(
                                f"✅ Shortened: Host words {_before_host_words} → {_after_host_words} "
                                f"(target ~{_target_words})",
                                14,
                            )
                            # Auto-save shortened script using the loaded
                            # filename + "_shortened" suffix. Prefer the
                            # source script's own directory (when the user
                            # picked the file via the native path browser);
                            # otherwise fall back to the run output folder.
                            try:
                                _src_name = (script_filename or "").strip()
                                if _src_name:
                                    _stem = Path(_src_name).stem or "script"
                                else:
                                    _stem = (script_title or "script")
                                _safe_stem = re.sub(r"[^\w\-. ]+", "_", _stem).strip() or "script"

                                _target_dir = None
                                _src_dir = (script_dir or "").strip()
                                if _src_dir:
                                    _cand = Path(_src_dir).expanduser()
                                    if _cand.exists() and _cand.is_dir():
                                        _target_dir = _cand
                                    else:
                                        logger.warning(
                                            f"⚠️ script_dir not found, falling back to run folder: {_src_dir}"
                                        )
                                if _target_dir is None:
                                    _target_dir = run_output_dir

                                _md_path = _target_dir / f"{_safe_stem}_shortened.md"
                                _md_path.write_text(cleaned_script, encoding="utf-8")
                                streamer.send_update(
                                    f"💾 Saved shortened script (.md): {_md_path}",
                                    14,
                                )
                                logger.info(f"💾 Shortened script .md saved → {_md_path}")

                                # Also write a .docx companion next to the .md.
                                try:
                                    from docx import Document as _DocxDocument
                                    _docx_path = _target_dir / f"{_safe_stem}_shortened.docx"
                                    _doc = _DocxDocument()
                                    for _ln in cleaned_script.splitlines():
                                        _stripped = _ln.rstrip()
                                        _heading_match = re.match(r"^(#{1,6})\s+(.*)$", _stripped)
                                        if _heading_match:
                                            _lvl = min(len(_heading_match.group(1)), 6)
                                            _doc.add_heading(_heading_match.group(2), level=_lvl)
                                        else:
                                            _doc.add_paragraph(_stripped)
                                    _doc.save(str(_docx_path))
                                    streamer.send_update(
                                        f"💾 Saved shortened script (.docx): {_docx_path}",
                                        14,
                                    )
                                    logger.info(f"💾 Shortened script .docx saved → {_docx_path}")
                                except Exception as _docx_err:
                                    logger.warning(
                                        f"⚠️ Could not save shortened .docx: {_docx_err}"
                                    )
                                    streamer.send_update(
                                        f"⚠️ .docx save skipped: {_docx_err}",
                                        14,
                                    )
                            except Exception as _save_err:
                                logger.error(f"⚠️ Failed to save shortened script: {_save_err}")
                                streamer.send_update(
                                    f"⚠️ Could not save shortened script file: {_save_err}",
                                    14,
                                )
                        else:
                            streamer.send_update("⚠️ Shorten agent returned empty content; keeping original", 14)
                    else:
                        _err = _short_result.get("error", "unknown error")
                        streamer.send_update(f"⚠️ Shorten agent failed: {_err}; keeping original", 14)
                else:
                    streamer.send_update(
                        f"✅ Script already at/under target length — no shortening needed",
                        14,
                    )
            except Exception as _shorten_err:
                logger.error(f"❌ Shorten step error: {_shorten_err}")
                streamer.send_update(f"⚠️ Shorten step error: {_shorten_err}", 14)

        # OPTIONAL: Add 3-4 Grok Imagine still-image prompts per chapter, inline,
        # so they can be copy-pasted into Grok Imagine. Runs after Shorten so the
        # prompts match the final wording; tops up chapters that already have some.
        if checkboxes.get("grok_imagine", False):
            try:
                streamer.send_update(
                    "🖼️ Adding Grok Imagine prompts per chapter…", 13)
                cleaned_script, _gi_added = _inject_grok_imagine_prompts(
                    cleaned_script, video_title=script_title)
                streamer.send_update(
                    f"✅ Added {_gi_added} Grok Imagine prompt(s) across chapters"
                    if _gi_added else
                    "ℹ️ Grok Imagine: no chapters needed prompts (already at target)",
                    14)
            except Exception as _gi_err:
                logger.warning(f"⚠️ Grok Imagine step error: {_gi_err}")
                streamer.send_update(
                    f"⚠️ Grok Imagine step error: {_gi_err}", 14)

        # HOOK-ONLY MODE: when only the Hook checkbox is set (no other section
        # generators), we generate 3 hook options and return them to the UI for
        # interactive selection. The user picks one in a modal, then
        # /api/finalize-hook writes the final script with a single FINAL HOOK
        # section and strips any prior OPENING HOOK OPTIONS block.
        _section_flags = [
            "youtube_details", "broll", "broll_images", "heygen", "curl",
            "demo", "thumbnails", "flow_analysis", "grok_videos", "grok_imagine",
        ]
        _hook_only_mode = (
            checkboxes.get("hook_summary", False)
            and not any(checkboxes.get(_f, False) for _f in _section_flags)
        )

        # Generate Hook & Summary if requested
        if checkboxes.get("hook_summary", False):
            streamer.send_update("🎯 Generating Hook & Summary...", 15)
            try:
                from linedrive_azure.agents import HookAndSummaryAgentClient

                hook_agent = HookAndSummaryAgentClient()
                hook_result = hook_agent.generate_hook_and_summary(
                    script_content=cleaned_script,
                    script_title=script_title,
                    target_audience=audience,
                    tone=tone,
                    video_length=video_length,
                    timeout=180
                )

                if hook_result.get("success", False):
                    hook_text = hook_result.get("hook", "")
                    summary_text = hook_result.get("summary", "")
                    flow_analysis = hook_result.get("flow_analysis", "")
                    thumbnail_hook_text_options = _extract_thumbnail_hook_text_options(
                        hook_result=hook_result
                    )
                    thumbnail_hook_text = thumbnail_hook_text_options[
                        0] if thumbnail_hook_text_options else ""
                    logger.info(
                        f"🔍 DEBUG: process_existing_script hook_result keys: {list(hook_result.keys())}")
                    if thumbnail_hook_text_options:
                        logger.info(
                            f"🏷️ Thumbnail hook text options detected: {thumbnail_hook_text_options}")
                        print(
                            f"🏷️ Thumbnail hook text options detected: {thumbnail_hook_text_options}")
                        streamer.send_update(
                            f"🏷️ Thumbnail hook options: {', '.join(thumbnail_hook_text_options)}", 15
                        )
                    else:
                        logger.warning(
                            "⚠️ Thumbnail hook text missing in Hook-and-Summary response")
                        raw_response = hook_result.get(
                            "full_response", "") or hook_result.get("raw_response", "")
                        print(
                            "⚠️ Thumbnail hook text missing in Hook-and-Summary response")
                        print(
                            f"🔍 DEBUG: THUMBNAIL_HOOK_TEXT marker present: {'THUMBNAIL_HOOK_TEXT' in raw_response}")
                        print(
                            f"🔍 DEBUG: THUMBNAIL HOOK section present: {'THUMBNAIL HOOK' in raw_response.upper()}")
                        streamer.send_update(
                            "⚠️ Thumbnail hook text missing in Hook-and-Summary response",
                            15,
                        )
                    completed_steps += 1
                    progress = 15 + (completed_steps * progress_per_step)
                    streamer.send_update(
                        f"✅ Hook & Summary generated "
                        f"({len(hook_text)} + {len(summary_text)} chars)",
                        int(progress)
                    )
                else:
                    logger.warning(f"⚠️ Hook & summary failed")
            except Exception as e:
                logger.error(f"❌ Hook & summary error: {e}")

        # Build script with hooks and summary
        hook1_text = ""
        hook2_text = ""
        hook3_text = ""
        opening_statement = ""

        if hook_result.get("success", False):
            # Extract all three hooks from the result
            # Use hook1 or fallback to hook (for backward compatibility)
            hook1_text = hook_result.get("hook1", hook_result.get("hook", ""))
            hook2_text = hook_result.get("hook2", "")
            hook3_text = hook_result.get("hook3", "")
            opening_statement = hook_result.get("opening_statement", "")

            # DEBUG: Log what we actually got
            logger.info(
                f"🔍 DEBUG: hook_result keys: {list(hook_result.keys())}")
            logger.info(
                f"🔍 DEBUG: hook1_text length: {len(hook1_text) if hook1_text else 0}")
            logger.info(
                f"🔍 DEBUG: hook2_text length: {len(hook2_text) if hook2_text else 0}")
            logger.info(
                f"🔍 DEBUG: hook3_text length: {len(hook3_text) if hook3_text else 0}")

            logger.info(
                f"📌 Adding {3 if hook3_text else (2 if hook2_text else 1)} hook option(s) to output")

            # HOOK-ONLY MODE: short-circuit here and return hooks to UI for
            # interactive selection instead of writing the full output file.
            if _hook_only_mode:
                _hooks_list = [h for h in (hook1_text, hook2_text, hook3_text) if h]

                # Defensive: if the agent returned success but produced zero
                # usable hook texts, surface an actionable error rather than
                # silently completing with nothing for the UI to render.
                if not _hooks_list:
                    _raw = (
                        hook_result.get("full_response")
                        or hook_result.get("raw_response")
                        or ""
                    )
                    # Common case: the source script contains an Azure content-
                    # filter refusal (e.g. "I'm sorry, but I cannot assist with
                    # that request.") so the Hook agent refused the whole job.
                    _refusal_marker = "cannot assist with that request"
                    if _refusal_marker in (script_content or "").lower():
                        _err = (
                            "Source script contains Azure content-filter refusal text "
                            "('I'm sorry, but I cannot assist with that request.'). "
                            "Remove those lines from the script (or re-run script "
                            "creation) before generating hooks."
                        )
                    elif _refusal_marker in _raw.lower():
                        _err = (
                            "Hook agent refused the request (Azure content filter). "
                            "Soften wording in the script or retry."
                        )
                    else:
                        _err = (
                            "Hook agent returned no usable hooks. Try again, or "
                            "check the agent's raw response for parsing issues."
                        )
                    logger.warning(f"⚠️ Hook-only mode: {_err}")
                    streamer.result = {"success": False, "error": _err}
                    streamer.send_update(f"❌ {_err}", -1)
                    return

                # If the source script already has a **🎯 FINAL HOOK:** section,
                # extract its Host body and prepend it as a "Keep current"
                # option so the user can re-pick the existing hook.
                _existing_hook_text = ""
                try:
                    # Find the start of any "FINAL HOOK" section (tolerant of
                    # markdown bold, leading emoji, "the", trailing colon, etc.)
                    _start_re = re.compile(
                        r"(?:^|\n)\s*(?:#{1,6}\s*)?\*{0,2}\s*(?:🎯\s*)?(?:THE\s+)?FINAL\s+HOOK\s*:?\s*\*{0,2}\s*\n",
                        flags=re.IGNORECASE,
                    )
                    _m = _start_re.search(script_content)
                    if _m:
                        _body = script_content[_m.end():]
                        # Optional "Host:" / "**Host:**" label line
                        _body = re.sub(
                            r"^\s*\*{0,2}\s*Host\s*:?\s*\*{0,2}\s*\n+",
                            "",
                            _body,
                            count=1,
                            flags=re.IGNORECASE,
                        )
                        # Terminator: --- rule, next markdown heading, next
                        # "Heading:" marker, next labeled section (e.g.
                        # "**Chapter 1:**", "OPENING HOOK OPTIONS"), or EOF.
                        _end_re = re.compile(
                            r"\n(?:---+\s*\n|"
                            r"#{1,6}\s|"
                            r"\s*Heading\s*:|"
                            r"\s*\*{1,2}\s*(?:Chapter|Part|Section|Opening|Hook|Summary|Conclusion|Outro|Intro)[^\n]*\*{1,2}|"
                            r"\s*\*{1,2}\s*🎬|"
                            r"\s*\*{1,2}\s*🎯|"
                            r"\s*(?:🎬|🎯)\s+\w|"
                            r"\s*FINAL\s+HOOK\s*:)",
                            flags=re.IGNORECASE,
                        )
                        _e = _end_re.search(_body)
                        _hook_body = _body[: _e.start()] if _e else _body
                        _existing_hook_text = _hook_body.strip()
                        # Sanity: drop if absurdly long (likely matched past the hook)
                        if len(_existing_hook_text) > 1200:
                            logger.info(
                                f"ℹ️ Existing FINAL HOOK candidate too long ({len(_existing_hook_text)} chars); ignoring"
                            )
                            _existing_hook_text = ""
                except Exception as _ex:
                    logger.warning(f"⚠️ Existing FINAL HOOK extract failed: {_ex}")
                logger.info(
                    f"🔎 Existing FINAL HOOK extraction: {'FOUND ' + str(len(_existing_hook_text)) + ' chars' if _existing_hook_text else 'not found'}"
                )
                _hook_labels = [f"Option {i+1}" for i in range(len(_hooks_list))]
                if _existing_hook_text:
                    _hooks_list = [_existing_hook_text] + _hooks_list
                    _hook_labels = ["Current FINAL HOOK"] + _hook_labels

                logger.info(
                    f"🎯 Hook-only mode: returning {len(_hooks_list)} hooks for UI selection"
                    + (" (incl. existing FINAL HOOK)" if _existing_hook_text else "")
                )
                streamer.result = {
                    "success": True,
                    "awaiting_hook_selection": True,
                    "hooks": _hooks_list,
                    "hook_labels": _hook_labels,
                    "script_title": script_title,
                    "original_script": script_content,
                    "session_id": session_id,
                }
                streamer.send_update(
                    f"🎯 {len(_hooks_list)} hook options ready — pick one to finalize",
                    100,
                )
                return

            final_output += "**🎬 OPENING HOOK OPTIONS**\n\n"
            final_output += "*Choose one of these three hooks for your video:*\n\n"

            # Add Hook Option 1
            final_output += "**OPTION 1:**\n\n"
            final_output += f"**Host:**\n\n{hook1_text}\n\n"

            # Add Hook Option 2 if available
            if hook2_text:
                final_output += "---\n\n**OPTION 2:**\n\n"
                final_output += f"**Host:**\n\n{hook2_text}\n\n"

            # Add Hook Option 3 if available
            if hook3_text:
                final_output += "---\n\n**OPTION 3:**\n\n"
                final_output += f"**Host:**\n\n{hook3_text}\n\n"

            final_output += "---\n\n"

            # Add opening statement after hooks
            if opening_statement:
                final_output += "**📺 OPENING STATEMENT**\n\n"
                final_output += f"**Host:**\n\n{opening_statement}\n\n"
                final_output += "---\n\n"

        # Add script title with line break and bold formatting
        final_output += f"\n**{script_title}**\n\n"

        final_output += cleaned_script
        logger.info(
            f"📌 After adding cleaned_script, final_output length: {len(final_output)} chars")

        if summary_text:
            logger.info(
                f"📌 Adding summary to output ({len(summary_text)} chars)")
            final_output += "\n\n---\n\n**📝 CONCLUSION/SUMMARY**\n\n"
            final_output += f"**Host:**\n\n{summary_text}\n\n"

        if flow_analysis:
            logger.info(
                f"📌 Adding flow analysis to output ({len(flow_analysis)} chars)")
            final_output += f"\n\n{'=' * 80}\n# 📊 FLOW ANALYSIS\n"
            final_output += f"{'=' * 80}\n\n{flow_analysis}"

        # Generate YouTube Upload Details if requested
        youtube_details = None
        if checkboxes.get("youtube_details", False):
            current_progress = 15 + (completed_steps * progress_per_step)
            if youtube_details_override:
                # Skip the agent: user loaded an existing YouTube details doc.
                youtube_details = youtube_details_override
                youtube_section = f"\n\n{'=' * 80}\n"
                youtube_section += "# 📺 YOUTUBE UPLOAD DETAILS\n"
                youtube_section += f"{'=' * 80}\n\n{youtube_details}"
                final_output += youtube_section
                completed_steps += 1
                progress = 15 + (completed_steps * progress_per_step)
                streamer.send_update(
                    f"✅ Using loaded YouTube details ({len(youtube_details)} chars) — agent skipped",
                    int(progress)
                )
            else:
                streamer.send_update("📺 Generating YouTube Upload Details...",
                                     int(current_progress))
                try:
                    from linedrive_azure.agents import YouTubeUploadDetailsAgentClient

                    youtube_agent = YouTubeUploadDetailsAgentClient()
                    youtube_result = youtube_agent.generate_upload_details(
                        script_content=cleaned_script,
                        script_title=script_title,
                        target_audience=audience,
                        video_length=video_length,
                        timeout=180
                    )

                    if youtube_result.get("success", False):
                        youtube_details = youtube_result.get("upload_details", "")
                        youtube_section = f"\n\n{'=' * 80}\n"
                        youtube_section += "# 📺 YOUTUBE UPLOAD DETAILS\n"
                        youtube_section += f"{'=' * 80}\n\n{youtube_details}"
                        final_output += youtube_section
                        completed_steps += 1
                        progress = 15 + (completed_steps * progress_per_step)
                        streamer.send_update(
                            f"✅ YouTube details generated ({len(youtube_details)} chars)",
                            int(progress)
                        )
                except Exception as e:
                    logger.error(f"❌ YouTube details error: {e}")

        # Generate B-roll Table if requested
        broll_table = None
        broll_rows = []
        # If user pre-loaded a B-roll table doc, prime it now so that BOTH
        # the explicit "broll" checkbox and downstream consumers (broll_images,
        # grok_videos) can use it without re-running the agent.
        if broll_table_override:
            broll_table = broll_table_override
            broll_rows = []
            logger.info(
                f"📋 Using loaded B-roll table override ({len(broll_table)} chars)")
        if checkboxes.get("broll", False):
            current_progress = 15 + (completed_steps * progress_per_step)
            if broll_table_override:
                # Skip the agent entirely.
                broll_section = f"\n\n{'=' * 80}\n"
                broll_section += "# 📊 B-ROLL SEARCH TERMS TABLE\n"
                broll_section += f"{'=' * 80}\n\n{broll_table}"
                final_output += broll_section
                completed_steps += 1
                progress = 15 + (completed_steps * progress_per_step)
                streamer.send_update(
                    f"✅ Using loaded B-roll table ({len(broll_table)} chars) — agent skipped",
                    int(progress)
                )
            else:
                streamer.send_update("📊 Generating B-roll Search Terms Table...",
                                     int(current_progress))
                try:
                    from linedrive_azure.agents import ScriptBRollAgentClient

                    broll_agent = ScriptBRollAgentClient()
                    broll_result = broll_agent.generate_broll_table_with_timecodes(
                        script_content=cleaned_script,
                        script_title=script_title,
                        words_per_minute=150,
                        # Increased to 5 minutes for larger tables (40-60+ rows)
                        timeout=300
                    )

                    if broll_result.get("success", False):
                        broll_table = broll_result.get("table", "")
                        parsed_data = broll_result.get("parsed_data", [])
                        broll_rows = parsed_data

                        # Merge "## Animation Suggestions" bullets from the
                        # script into broll_rows + broll_table so the user can
                        # also select them for Grok video generation.
                        try:
                            anim_rows = _extract_animation_suggestion_rows(
                                cleaned_script)
                            if anim_rows:
                                broll_rows = broll_rows + anim_rows
                                anim_md = _animation_rows_to_markdown(anim_rows)
                                broll_table = (
                                    (broll_table or "").rstrip()
                                    + "\n\n"
                                    + anim_md
                                )
                                logger.info(
                                    f"🎞️ Appended {len(anim_rows)} Animation Suggestion rows for Grok"
                                )
                        except Exception as anim_err:
                            logger.warning(
                                f"⚠️ Could not parse Animation Suggestions: {anim_err}")

                        broll_section = f"\n\n{'=' * 80}\n"
                        broll_section += "# 📊 B-ROLL SEARCH TERMS TABLE\n"
                        broll_section += f"{'=' * 80}\n\n{broll_table}"
                        final_output += broll_section

                        # Generate EDL file
                        if parsed_data:
                            try:
                                import time
                                timestamp = time.strftime("%Y%m%d_%H%M%S")
                                edl_filename = f"broll_markers_{timestamp}.edl"
                                edl_dir = run_output_dir / "MDL"
                                edl_dir.mkdir(parents=True, exist_ok=True)
                                edl_path = edl_dir / edl_filename

                                edl_result = broll_agent.create_edl_markers(
                                    broll_data=parsed_data,
                                    output_file=str(edl_path),
                                    frame_rate='24'
                                )

                                if edl_result.get("success"):
                                    # Read EDL content for frontend display
                                    try:
                                        with open(edl_path, 'r', encoding='utf-8') as f:
                                            edl_content = f.read()
                                        logger.info(
                                            f"✅ EDL content read ({len(edl_content)} bytes)")
                                    except Exception as read_error:
                                        logger.error(
                                            f"⚠️ Could not read EDL file: {read_error}")

                                    edl_info = f"\n\n**EDL File:** `{edl_filename}`"
                                    edl_info += f" ({edl_result.get('marker_count')}"
                                    edl_info += " markers)\n"
                                    final_output += edl_info
                            except Exception as edl_error:
                                logger.error(f"❌ EDL error: {edl_error}")

                        # Persist the B-roll table (md + Word doc with a Grok
                        # Imagine Prompt column) into {run}/broll/, next to any
                        # Grok videos, so weak clips can be regenerated by
                        # copying the scene's prompt.
                        _persist_broll_table_artifacts(
                            broll_table, broll_rows,
                            run_output_dir / "broll", theme=script_title,
                            script=cleaned_script)

                        completed_steps += 1
                        progress = 15 + (completed_steps * progress_per_step)
                        streamer.send_update(
                            f"✅ B-roll table generated ({len(broll_table)} chars)",
                            int(progress)
                        )
                    else:
                        err = broll_result.get("error", "unknown error")
                        raw = (broll_result.get("raw_response") or "").strip()
                        logger.warning(
                            f"⚠️ B-roll agent returned success=False: {err}")
                        if raw:
                            logger.warning(
                                f"   Raw agent response (first 300 chars): {raw[:300]!r}")
                        # Surface the failure into the B-Roll Table tab so the
                        # user sees WHY it's empty instead of a blank tab.
                        broll_table = (
                            "> ⚠️ **B-Roll table generation failed**\n>\n"
                            f"> {err}\n"
                        )
                        if raw:
                            broll_table += (
                                "\n**Agent response:**\n\n"
                                "```\n" + raw[:2000] + "\n```\n"
                            )
                        broll_rows = []
                        streamer.send_update(
                            f"⚠️ B-roll table generation failed: {err}",
                            int(current_progress),
                        )
                except Exception as e:
                    logger.error(f"❌ B-roll table error: {e}")
                    import traceback
                    traceback.print_exc()
                    streamer.send_update(
                        f"❌ B-roll table error: {str(e)}", int(current_progress))

        # Generate B-roll Images using Gemini (ONLY if broll_images checkbox checked AND broll_table was successfully generated)
        broll_images = None
        # If the user only checked "B-roll Images" (without "B-roll Table"), try to reuse a B-roll
        # table that's already embedded in the loaded script so they don't have to re-run the agent.
        if checkboxes.get("broll_images", False) and not broll_table:
            try:
                extracted_table = _extract_broll_table_from_script(
                    cleaned_script)
                if extracted_table:
                    broll_table = extracted_table
                    current_progress = 15 + \
                        (completed_steps * progress_per_step)
                    streamer.send_update(
                        "📋 Found existing B-roll table in script — using it for image generation",
                        int(current_progress)
                    )
                    logger.info(
                        f"📋 Reusing existing B-roll table from script ({len(broll_table)} chars)"
                    )
                else:
                    current_progress = 15 + \
                        (completed_steps * progress_per_step)
                    streamer.send_update(
                        "⚠️ B-roll Images selected but no B-roll table found in script — also enable 'B-roll Table' to generate one.",
                        int(current_progress)
                    )
            except Exception as ex_err:
                logger.warning(
                    f"⚠️ Could not extract B-roll table from script: {ex_err}")

        if checkboxes.get("broll_images", False) and broll_table:
            current_progress = 15 + (completed_steps * progress_per_step)
            streamer.send_update("🎨 Generating B-roll images with AI...",
                                 int(current_progress))
            try:
                from tools.media.broll_image_generator import BRollImageGenerator

                broll_gen = BRollImageGenerator()

                # Per-session cancel hook so the user can stop mid-generation and keep partial results.
                cancel_evt = broll_image_cancel_events.setdefault(
                    session_id, _threading.Event())

                # Notify the UI of every variation in real time so the user sees progress per image.
                step_progress_base = current_progress
                step_progress_span = max(1.0, progress_per_step * 0.95)

                def _broll_progress(message: str, current: int, total: int, image_info=None):
                    try:
                        ratio = (current / total) if total else 0
                        pct = int(
                            step_progress_base + (step_progress_span * min(1.0, max(0.0, ratio))))
                        streamer.send_update(message, pct)
                    except Exception as cb_err:  # never let UI plumbing break image gen
                        logger.warning(
                            f"⚠️ B-roll progress callback error: {cb_err}")
                    # Live-copy each saved image into the user's configured output dir.
                    try:
                        if image_info and image_info.get("success"):
                            src = image_info.get(
                                "filename") or image_info.get("filepath")
                            dst = _copy_to_output_subfolder(
                                src, "images", script_title=script_title)
                            if dst:
                                streamer.send_update(f"💾 Saved → {dst}", pct)
                    except Exception as copy_err:
                        logger.warning(
                            f"⚠️ live copy of B-roll image failed: {copy_err}")

                # Generate images from the B-roll table
                # max_images now refers to max ENTRIES (each gets 3 variations)
                # Set to None to generate ALL entries, or set a limit if needed
                _broll_out_dir = run_output_dir / "images"
                image_results = broll_gen.generate_all_broll_images(
                    broll_table=broll_table,
                    script_title=script_title,
                    max_images=None,  # Generate all entries with 3 variations each
                    progress_callback=_broll_progress,
                    cancel_check=cancel_evt.is_set,
                    output_dir=_broll_out_dir,
                )

                if image_results.get("success", False) or image_results.get("cancelled"):
                    broll_images = image_results.get("images", [])
                    entries_count = image_results.get("total_entries", 0)
                    variations = image_results.get("variations_per_entry", 3)
                    completed_steps += 1
                    progress = 15 + (completed_steps * progress_per_step)
                    if image_results.get("cancelled"):
                        logger.info(
                            f"🛑 B-roll image generation cancelled by user — keeping {len(broll_images)} images")
                        streamer.send_update(
                            f"🛑 B-roll image generation stopped — keeping {len(broll_images)} images so far",
                            int(progress)
                        )
                    else:
                        logger.info(
                            f"✅ Generated {len(broll_images)} B-roll images ({entries_count} entries × {variations} variations)")
                        streamer.send_update(
                            f"✅ Generated {len(broll_images)} B-roll images ({entries_count} entries × {variations} variations)",
                            int(progress)
                        )
                else:
                    logger.warning(
                        f"⚠️ B-roll images generation failed: {image_results.get('error')}")
            except Exception as e:
                logger.error(f"❌ B-roll images error: {e}")
                import traceback
                traceback.print_exc()
            finally:
                # Always discard the cancel event so a later run starts fresh.
                broll_image_cancel_events.pop(session_id, None)

        # Defer Grok AI generation until user selects rows from B-roll table
        # Auto-generate broll_table if needed and not already done
        grok_videos = []
        if checkboxes.get("grok_videos", False):
            if not broll_table:
                # Prefer reusing a B-roll table already embedded in the script before regenerating one.
                try:
                    extracted_table = _extract_broll_table_from_script(
                        cleaned_script)
                except Exception:
                    extracted_table = ""
                if extracted_table:
                    broll_table = extracted_table
                    logger.info(
                        f"📋 Grok Videos: reusing existing B-roll table from script ({len(broll_table)} chars)"
                    )
                    streamer.send_update(
                        "📋 Grok Videos: using existing B-roll table from script",
                        int(15 + (completed_steps * progress_per_step))
                    )
            if not broll_table:
                logger.info(
                    "🤖 Grok Videos: broll_table not available, auto-generating...")
                streamer.send_update("🤖 Grok Videos: generating B-roll table first...",
                                     int(15 + (completed_steps * progress_per_step)))
                try:
                    from linedrive_azure.agents import ScriptBRollAgentClient
                    broll_agent = ScriptBRollAgentClient()
                    broll_result = broll_agent.generate_broll_table_with_timecodes(
                        script_content=cleaned_script,
                        script_title=script_title,
                        words_per_minute=150,
                        timeout=300
                    )
                    if broll_result.get("success", False):
                        broll_table = broll_result.get("table", "")
                        broll_rows = broll_result.get("parsed_data", [])
                        logger.info(
                            f"✅ Auto-generated broll_table ({len(broll_table)} chars) for Grok Videos")
                    else:
                        logger.warning(
                            "⚠️ Auto broll_table generation failed for Grok Videos")
                except Exception as auto_broll_err:
                    logger.error(f"❌ Auto broll_table error: {auto_broll_err}")
        if checkboxes.get("grok_videos", False) and broll_table:
            total_rows = len(broll_rows) if broll_rows else 0
            streamer.send_update(
                f"⏸️ Select B-roll rows for Grok generation ({total_rows} available)",
                int(15 + (completed_steps * progress_per_step))
            )

        # Generate HeyGen Ready Script if requested
        if checkboxes.get("heygen", False):
            current_progress = 15 + (completed_steps * progress_per_step)
            streamer.send_update("🎬 Generating HeyGen Ready section...",
                                 int(current_progress))
            try:
                from console_ui.text_processing import (
                    extract_heygen_host_script,
                    scrub_heygen_text,
                )

                # Extract from the cleaned source script ONLY (not final_output) so the
                # HeyGen text never includes the prepended OPENING HOOK OPTIONS block,
                # the OPTION 1/2/3 "Host:" hooks, the opening statement, or any
                # generated headers added below. Strip [PRODUCTION …] editing notes
                # first so the avatar never narrates them.
                _hg_src = _strip_production_blocks(cleaned_script)
                heygen_script = extract_heygen_host_script(_hg_src)
                # Fallback: if no Host: markers found, scrub the cleaned script
                # down to dialogue-only (strip title, chapter headings, metadata,
                # stage directions, hook/summary headers, separators).
                if not heygen_script:
                    logger.info(
                        "⚠️ No Host: markers found - scrubbing cleaned script for HeyGen")
                    heygen_script = scrub_heygen_text(_hg_src)
                if heygen_script:
                    heygen_section = f"\n\n{'=' * 80}\n"
                    heygen_section += "# 🎬 HEYGEN READY SCRIPT\n"
                    heygen_section += f"{'=' * 80}\n\n{heygen_script}"
                    final_output += heygen_section
                    completed_steps += 1
                    progress = 15 + (completed_steps * progress_per_step)
                    streamer.send_update(
                        f"✅ HeyGen script extracted ({len(heygen_script)} chars)",
                        int(progress)
                    )
            except Exception as e:
                logger.error(f"❌ HeyGen section error: {e}")
                heygen_script = None

        # Generate curl commands if requested
        if checkboxes.get("curl", False):
            current_progress = 15 + (completed_steps * progress_per_step)
            streamer.send_update("🚀 Generating HeyGen curl commands...",
                                 int(current_progress))
            try:
                from console_ui.text_processing import (
                    extract_heygen_host_script,
                    generate_heygen_curl_commands,
                    scrub_heygen_text,
                )

                # Strip [PRODUCTION …] editing notes so curl content the avatar
                # reads never includes them.
                _hg_curl_src = _strip_production_blocks(cleaned_script)
                if not heygen_script:
                    heygen_script = extract_heygen_host_script(_hg_curl_src)

                # Fallback: if no Host: markers found, scrub for dialogue only.
                if not heygen_script:
                    logger.info(
                        "⚠️ No Host: markers found - scrubbing cleaned script for curl generation")
                    heygen_script = scrub_heygen_text(_hg_curl_src)

                if heygen_script:
                    heygen_with_header = (
                        f"# 🎬 HEYGEN READY SCRIPT\n{'=' * 80}\n\n{heygen_script}"
                    )

                    # Extract a FINAL HOOK section (if present in cleaned_script
                    # or final_output) so we can emit a dedicated `{short}-hook`
                    # curl command alongside the chapter curls.
                    _hook_search_text = (
                        f"{_strip_production_blocks(final_output)}\n"
                        f"{_hg_curl_src}")
                    _final_hook_text = ""
                    _hm = re.search(
                        r"\*{0,2}\s*(?:🎯\s*)?(?:FINAL\s+|OPENING\s+)?HOOK\s*:?\s*\*{0,2}\s*"
                        r"(?:\*{0,2}\s*Host\s*:?\s*\*{0,2}\s*\n+)?"
                        r"([\s\S]*?)"
                        r"(?="
                        r"\n\s*---"
                        r"|\n\s*={3,}"
                        r"|\n\s*#{1,6}\s"
                        r"|\n\s*\*{0,2}\s*(?:Title|Heading|Visual\s*Cue|B-?Roll|Chapter|VISUAL|HEADING|OPTION\s*\d+|Host|Summary|Conclusion|Outro|Intro)\s*[:\-]"
                        r"|\n\s*\*{2}[^*\n]+\*{2}\s*:"
                        r"|\n\s*\n\s*\*{0,2}\s*OPTION\s*\d+"
                        r"|\Z)",
                        _hook_search_text,
                        re.IGNORECASE,
                    )
                    if _hm:
                        _final_hook_text = _hm.group(1).strip()
                        # Defensive: scripts sometimes carry a stray bold
                        # transition line (e.g. **We will start with...**)
                        # or a lingering `Host:` / `FINAL HOOK:` label
                        # between the header and the actual hook prose. The
                        # extraction regex above only consumes ONE optional
                        # `Host:` line directly after the header, so any
                        # intervening junk leaks into the capture and
                        # inflates the `-hook` curl's word count. Peel off
                        # any leading blank lines, bold-only lines, and
                        # stray Host/FINAL HOOK label lines before further
                        # processing.
                        _peel_re = re.compile(
                            r"^\s*(?:"
                            r"\*{1,2}[^\n]+\*{1,2}"          # **bold-only line**
                            r"|\*{0,2}\s*Host\s*:?\s*\*{0,2}"  # stray Host: label
                            r"|\*{0,2}\s*(?:🎯\s*)?(?:FINAL\s+|OPENING\s+)?HOOK\s*:?\s*\*{0,2}"  # stray header
                            r")\s*$",
                            re.IGNORECASE,
                        )
                        _peeled_lines = _final_hook_text.split("\n")
                        while _peeled_lines and (
                            not _peeled_lines[0].strip()
                            or _peel_re.match(_peeled_lines[0])
                        ):
                            _peeled_lines.pop(0)
                        _final_hook_text = "\n".join(_peeled_lines).strip()
                        # PRIMARY terminator: a hook is ONE paragraph. Cut at
                        # the first BLANK line so any intro paragraph that
                        # follows the hook doesn't bleed into the HeyGen
                        # `-hook` curl payload. (Hooks themselves may wrap
                        # across single \n line breaks, so we don't cut on a
                        # bare single newline.)
                        _final_hook_text = re.split(
                            r"\n\s*\n",
                            _final_hook_text,
                            maxsplit=1,
                        )[0].strip()
                        # Defensive: drop a trailing standing-intro paragraph
                        # that may be joined to the hook with only a single
                        # \n (e.g. "...five to start with.\nHi, I'm <Host>...").
                        _final_hook_text = re.split(
                            r"\n\s*(?:Hi[, ]\s*I[’']m|Hello[, ]|Welcome\s+back|Welcome\s+to|This\s+is,?\s+AI\s+with)\b",
                            _final_hook_text,
                            maxsplit=1,
                            flags=re.IGNORECASE,
                        )[0].strip()
                        # Defensive: drop any trailing "Heading:" / "OPTION N:" line
                        # that snuck in despite the lookahead.
                        _final_hook_text = re.split(
                            r"\n\s*(?:\*{0,2}\s*)?(?:Heading|Visual\s*Cue|B-?Roll|Chapter|OPTION\s*\d+|Host)\s*[:\-]",
                            _final_hook_text,
                            maxsplit=1,
                            flags=re.IGNORECASE,
                        )[0].strip()
                        # Defensive: also cut at the first `---` separator.
                        _final_hook_text = re.split(
                            r"\n\s*---+\s*\n?",
                            _final_hook_text,
                            maxsplit=1,
                        )[0].strip()
                        # Defensive: reject obviously-bad captures (just the
                        # header text, empty, or fewer than ~6 words). Better
                        # to skip the hook curls than emit a `-hook` curl whose
                        # content is literally "FINAL HOOK:".
                        _hook_norm = re.sub(
                            r"[^a-z0-9 ]+", " ",
                            _final_hook_text.lower()).strip()
                        if (
                            not _hook_norm
                            or _hook_norm in ("final hook", "opening hook", "hook", "host")
                            or _hook_norm.startswith(("final hook ", "opening hook ", "hook "))
                            or len(_final_hook_text.split()) < 6
                        ):
                            logger.warning(
                                "⚠️ FINAL HOOK extract was header-only or too "
                                "short (%r) — skipping `-hook` curls.",
                                _final_hook_text[:80],
                            )
                            _final_hook_text = ""
                        # Hard cap: a hook is at most ~120 words. Anything longer
                        # means our regex bled into adjacent content — truncate
                        # at the first sentence boundary within the cap.
                        _MAX_HOOK_WORDS = 120
                        _words = _final_hook_text.split()
                        if len(_words) > _MAX_HOOK_WORDS:
                            _truncated = " ".join(_words[:_MAX_HOOK_WORDS])
                            # Prefer trimming back to a sentence end.
                            _sent_end = max(
                                _truncated.rfind(". "),
                                _truncated.rfind("! "),
                                _truncated.rfind("? "),
                            )
                            if _sent_end > len(_truncated) // 2:
                                _truncated = _truncated[: _sent_end + 1]
                            logger.warning(
                                f"⚠️ FINAL HOOK extract was {len(_words)} words; "
                                f"truncated to {_MAX_HOOK_WORDS}-word cap for HeyGen curl."
                            )
                            _final_hook_text = _truncated.strip()

                    # NOTE: curl chapter splitter needs the ORIGINAL structured
                    # script (with `Heading:` / `Chapter N -` boundaries) to
                    # split chapters correctly. `heygen_script` is now scrubbed
                    # dialogue-only and has no boundaries left, so feed the
                    # raw cleaned_script (wrapped with the expected header)
                    # and let the curl generator strip stage-direction lines
                    # from each chapter's content itself.
                    curl_source = (
                        f"# 🎬 HEYGEN READY SCRIPT\n{'=' * 80}\n\n{_hg_curl_src}"
                    )

                    curl_commands = generate_heygen_curl_commands(
                        curl_source, script_title,
                        heygen_api_key, heygen_template_id,
                        heygen_voice_id,
                        final_hook_text=_final_hook_text,
                    )
                    if curl_commands:
                        # Store curl commands separately (don't append to script)
                        num_commands = curl_commands.count(
                            'curl --request POST')
                        completed_steps += 1
                        progress = 15 + (completed_steps * progress_per_step)
                        streamer.send_update(
                            f"✅ Generated {num_commands} curl commands",
                            int(progress)
                        )
                        _live_curl_dst = _save_curl_commands_live(
                            curl_commands, script_title)
                        if _live_curl_dst:
                            streamer.send_update(
                                f"💾 Saved curl commands → {_live_curl_dst}",
                                int(progress)
                            )
                    else:
                        curl_commands = None
            except Exception as e:
                logger.error(f"❌ Curl generation error: {e}")
                curl_commands = None

        # Generate Demo Package if requested
        if checkboxes.get("demo", False):
            current_progress = 15 + (completed_steps * progress_per_step)
            streamer.send_update("🔧 Generating demo package...",
                                 int(current_progress))
            try:
                from linedrive_azure.agents.openai_demo_agent_client import (
                    OpenAIDemoAgentClient
                )

                demo_agent = OpenAIDemoAgentClient()
                demo_result = demo_agent.generate_demo_packages(
                    script_content,
                    max_tokens=12000,
                    audience=audience,
                )

                if demo_result.get("success", False):
                    demo_packages = demo_result.get("response", "")
                    demo_section = f"\n\n{'=' * 80}\n# 🔧 DEMO PACKAGE\n"
                    demo_section += f"{'=' * 80}\n\n{demo_packages}"
                    final_output += demo_section
                    completed_steps += 1
                    progress = 15 + (completed_steps * progress_per_step)
                    streamer.send_update(
                        f"✅ Demo package generated ({len(demo_packages)} chars)",
                        int(progress)
                    )
                else:
                    _err = demo_result.get("error", "unknown error")
                    logger.warning(f"⚠️ Demo generation failed: {_err}")
                    streamer.send_update(
                        f"⚠️ Demo generation failed: {_err}",
                        int(current_progress),
                    )
            except Exception as e:
                logger.error(f"❌ Demo package error: {e}")
                streamer.send_update(f"⚠️ Demo package error: {e}", int(current_progress))

        # Generate Thumbnails if requested
        thumbnail_results = None
        if checkboxes.get("thumbnails", False):
            current_progress = 15 + (completed_steps * progress_per_step)
            expected_thumbnails = 6 * \
                len(thumbnail_hook_text_options) if thumbnail_hook_text_options else 6
            streamer.send_update(
                f"🖼️ Generating {expected_thumbnails} thumbnail variations...",
                int(current_progress),
            )
            try:
                from tools.media.emotional_thumbnail_generator import (
                    EmotionalThumbnailGenerator,
                )

                _thumb_out_dir = run_output_dir / "thumbnails"
                thumbnail_gen = EmotionalThumbnailGenerator(
                    output_dir=_thumb_out_dir)
                if thumbnail_hook_text_options:
                    logger.info(
                        f"🏷️ Script processing will use thumbnail hook text options instead of script title: {thumbnail_hook_text_options}")
                else:
                    logger.warning(
                        "⚠️ Script processing did not find thumbnail hook text; using script title fallback")
                # always fresh — never reuse a stale cancelled event
                thumb_cancel_evt = _threading.Event()
                thumbnail_cancel_events[session_id] = thumb_cancel_evt
                thumbnail_results = thumbnail_gen.generate_all_thumbnails(
                    script_title=script_title,
                    script_content=cleaned_script,
                    headline_text=thumbnail_hook_text or None,
                    headline_options=thumbnail_hook_text_options or None,
                    progress_callback=lambda msg: streamer.send_update(
                        msg, int(current_progress)
                    ),
                    cancel_check=thumb_cancel_evt.is_set,
                )
                logger.info(
                    f"🔍 DEBUG: script processing headline options passed to thumbnail generator = {repr(thumbnail_hook_text_options or None)}")

                variations = (thumbnail_results or {}).get("variations") or []
                output_dir = (thumbnail_results or {}).get("output_dir")

                if variations:
                    if output_dir:
                        logger.info(
                            f"📁 Thumbnails saved to: {output_dir}")
                        streamer.send_update(
                            f"📁 Thumbnails saved to: {output_dir}",
                            int(current_progress)
                        )
                    thumb_section = f"\n\n{'=' * 80}\n"
                    thumb_section += "# 🖼️ EMOTIONAL THUMBNAIL VARIATIONS\n"
                    thumb_section += f"{'=' * 80}\n\n"
                    for i, var in enumerate(variations, 1):
                        thumb_section += f"## Variation #{i}: {var.get('emotion')}\n"
                        thumb_section += f"- **Text:** {var.get('text')}\n"
                        thumb_section += f"- **Expression:** {var.get('expression')}\n"
                        thumb_section += f"- **File:** {var.get('filename')}\n\n"
                    final_output += thumb_section
                    completed_steps += 1
                    progress = 15 + (completed_steps * progress_per_step)
                    streamer.send_update(
                        f"✅ Generated {len(variations)} thumbnails",
                        int(progress)
                    )
                    if (thumbnail_results or {}).get("cancelled"):
                        streamer.send_update(
                            f"🛑 Thumbnail generation stopped — keeping {len(variations)} thumbnails so far",
                            int(progress)
                        )
                    api_error = (thumbnail_results or {}).get("error")
                    if api_error:
                        logger.warning(
                            f"⚠️ Thumbnail API returned errors during generation: {api_error}")
                        streamer.send_update(
                            f"⚠️ Thumbnail API error during generation: {api_error}",
                            int(current_progress)
                        )
                elif output_dir:
                    logger.warning(
                        f"⚠️ Thumbnail directory created but no files generated: {output_dir}")
                    streamer.send_update(
                        f"⚠️ No thumbnails generated (directory only): {output_dir}",
                        int(current_progress)
                    )
                    attempted = (thumbnail_results or {}).get(
                        "total_attempted", 0)
                    streamer.send_update(
                        f"❌ Thumbnail generation failed (0/{attempted})",
                        int(current_progress)
                    )
                    if (thumbnail_results or {}).get("error"):
                        streamer.send_update(
                            f"❌ Thumbnail API error: {(thumbnail_results or {}).get('error')}",
                            int(current_progress)
                        )
            except Exception as e:
                logger.error(f"❌ Thumbnail generation error: {e}")
                streamer.send_update(
                    f"❌ Thumbnail generation error: {e}", int(current_progress))
            finally:
                thumbnail_cancel_events.pop(session_id, None)

        # Generate Flow & Repetition Analysis if requested
        # IMPORTANT: This should run AFTER all other content is assembled
        if checkboxes.get("flow_analysis", False):
            current_progress = 15 + (completed_steps * progress_per_step)
            streamer.send_update("🔄 Analyzing script for repetition and flow...",
                                 int(current_progress))
            try:
                from linedrive_azure.agents import ScriptRepeatAndFlowAgentClient

                flow_agent = ScriptRepeatAndFlowAgentClient()
                # Shield [PRODUCTION …] blocks from the flow agent.
                _flow_masked, _flow_blocks = _mask_production_blocks(final_output)
                flow_result = flow_agent.analyze_and_improve_flow(
                    script_content=_flow_masked,
                    script_title=script_title,
                    target_audience=audience,
                    timeout=300
                )

                logger.info(
                    f"📊 Flow agent result: success={flow_result.get('success')}, keys={list(flow_result.keys())}")

                if flow_result.get("success", False):
                    # Replace final_output with the improved version
                    improved_script = flow_result.get("improved_script", "")
                    repetition_analysis = flow_result.get(
                        "repetition_analysis", "")
                    flow_improvements = flow_result.get("flow_analysis", "")

                    logger.info(
                        f"📊 Improved script length: {len(improved_script)}, rep analysis: {len(repetition_analysis)}, flow: {len(flow_improvements)}")

                    if improved_script:
                        # Add analysis section first
                        analysis_section = f"\n\n{'=' * 80}\n"
                        analysis_section += "# 🔄 FLOW & REPETITION ANALYSIS\n"
                        analysis_section += f"{'=' * 80}\n\n"

                        if repetition_analysis:
                            analysis_section += "## Repetition Analysis\n\n"
                            analysis_section += f"{repetition_analysis}\n\n"

                        if flow_improvements:
                            analysis_section += "## Flow Improvements\n\n"
                            analysis_section += f"{flow_improvements}\n\n"

                        # Replace the script with improved version and add analysis at end
                        final_output = _restore_or_keep(
                            improved_script, _flow_blocks, final_output
                        ) + analysis_section

                        completed_steps += 1
                        progress = 15 + (completed_steps * progress_per_step)
                        streamer.send_update(
                            f"✅ Flow analysis complete - script improved ({len(improved_script)} chars)",
                            int(progress)
                        )
                    else:
                        logger.warning(
                            "⚠️ Flow agent returned empty improved script")
                else:
                    logger.warning(
                        f"⚠️ Flow analysis failed - result: {flow_result}")
            except Exception as e:
                logger.error(f"❌ Flow analysis error: {e}")

        # Re-stamp the final script with the SAME ids fixed at the start of the
        # run (agents may have stripped the lines while rewriting the script).
        final_output, _, _ = _ensure_script_ids(
            final_output, script_id=proc_script_id, version_id=proc_script_version)

        # Complete — save files and set result BEFORE sending done=True so the
        # SSE handler always finds a valid streamer.result when it reads on progress==100.
        saved_markdown_path, saved_docx_path = await _save_script_md_and_docx(
            script_title,
            final_output,
        )

        streamer.result = {
            "success": True,
            "enhanced_script": final_output,  # SSE handler expects "enhanced_script" key
            "script": final_output,  # Also include "script" for compatibility
            "script_title": script_title,
            "script_id": proc_script_id,
            "script_version": proc_script_version,
            "thumbnail_results": thumbnail_results,
            "thumbnail_hook_text": thumbnail_hook_text,
            "thumbnail_hook_text_options": thumbnail_hook_text_options,
            "edl_content": edl_content,
            "edl_filename": edl_filename,
            "curl_commands": curl_commands,
            "broll_images": broll_images,
            "grok_videos": grok_videos,
            "broll_table": broll_table,
            "broll_rows": broll_rows,
            "youtube_details": youtube_details,
            "markdown_path": saved_markdown_path,
            "docx_path": saved_docx_path,
        }
        # Persist every artifact of this version so the script restores its tabs
        # when reopened later (Grok videos are persisted separately by Script-ID).
        try:
            _persist_version_artifacts(
                proc_script_id, proc_script_version, streamer.result, script_title)
        except Exception as _e:
            logger.warning(f"⚠️ version artifact persist (process) failed: {_e}")
        logger.info("✅ Script processing completed successfully")
        # Send done=True AFTER result is set so the SSE handler always finds a valid result.
        streamer.send_update("✅ Script processing complete!", 100)

    except Exception as e:
        error_msg = f"Error: {str(e)}"
        logger.error(f"💥 Exception during script processing: {error_msg}")
        streamer.send_update(f"❌ {error_msg}", -1)
        streamer.result = {"success": False, "error": error_msg}


async def test_mode_simulation(session_id):
    """Quick test mode - simulates script creation in 10 seconds"""
    import time
    import asyncio

    logger.info(f"⚡ Starting test mode simulation for {session_id}")

    if session_id not in progress_streams:
        logger.error(f"❌ No progress stream for session {session_id}")
        return

    streamer = progress_streams[session_id]

    try:
        # Simulate the 7-chapter workflow with fast updates
        test_chapters = [
            "Introduction: Setting the Stage",
            "Chapter 1: The Problem",
            "Chapter 2: Understanding the Context",
            "Chapter 3: Exploring Solutions",
            "Chapter 4: Implementation Strategy",
            "Chapter 5: Real-World Applications",
            "Conclusion: Looking Forward"
        ]

        # Send initial message
        streamer.send_update("🚀 Starting test script creation...", 5)
        await asyncio.sleep(1)

        # Simulate writing each chapter (1 second per chapter)
        for i, chapter in enumerate(test_chapters):
            progress = 10 + (i * 12)  # Distribute progress from 10-94%
            streamer.send_update(f"📝 Writing {chapter}...", progress)
            await asyncio.sleep(1)

            # Show completion of chapter
            char_count = 1000 + (i * 200)  # Fake character counts
            streamer.send_update(f"✅ {chapter} completed ({char_count} chars)",
                                 progress + 2)
            await asyncio.sleep(0.5)

        # Final processing steps
        streamer.send_update("✨ Enhancing script formatting...", 96)
        await asyncio.sleep(1)

        streamer.send_update("🔍 Adding tool recommendations...", 98)
        await asyncio.sleep(1)

        # Create a simple test result
        test_script = """Welcome to AI with Roz, I'm Roz's AI Clone. 

This is a test script created in fast mode for debugging purposes.

Chapter 1: The Problem
This chapter discusses the main challenges...

Chapter 2: Understanding the Context  
Here we explore the broader implications...

[Continue with remaining chapters...]

===============================
TOOLS
===============================

• OpenAI GPT-4 - AI writing assistant
• Canva - Design and presentation tools
• YouTube Studio - Video optimization"""

        # Store test result
        streamer.result = {
            "success": True,
            "enhanced_script": test_script,
            "word_count": len(test_script.split()),
            "reading_time": f"{len(test_script.split()) // 150} min",
            "audience": "test audience",
            "production_type": "test",
        }

        # Send completion message
        streamer.send_update("✅ Test script creation complete!", 100)
        logger.info(f"✅ Test mode completed for session {session_id}")

    except Exception as e:
        error_msg = f"Test mode error: {str(e)}"
        logger.error(f"❌ Test mode error for {session_id}: {error_msg}")
        streamer.send_update(f"❌ {error_msg}", -1)
        streamer.result = {"success": False, "error": error_msg}


@app.route("/test-sse")
def test_sse():
    """Test SSE completion behavior without running full script creation"""
    return render_template("test_sse.html")


@app.route("/test-progress/<session_id>")
def test_progress_stream(session_id):
    """Test SSE endpoint that simulates script creation completion"""
    import time

    def generate():
        try:
            # Simulate progress messages
            messages = [
                ("🚀 Starting test...", 10),
                ("📝 Processing step 1...", 30),
                ("📝 Processing step 2...", 60),
                ("✅ Almost done...", 90),
                ("✅ Test complete!", 100)
            ]

            for message, progress in messages:
                update = {
                    "message": message,
                    "progress": progress,
                    "timestamp": time.time(),
                    "done": progress == 100
                }

                logger.info(f"🔄 TEST SSE sending: {json.dumps(update)}")
                yield f"data: {json.dumps(update)}\n\n"

                if progress == 100:
                    logger.info(f"🎯 TEST SSE completion message sent")
                    # Don't send closing message - client will close connection
                    break

                time.sleep(1)  # 1 second between messages

        except Exception as e:
            logger.error(f"TEST SSE error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            logger.info(f"🔚 TEST SSE stream ended")

    response = Response(generate(), mimetype="text/event-stream")
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


@app.route("/")
def index():
    """Serve the main ScriptCraft web interface"""
    # Resolve API keys with precedence: saved settings file > environment variable > empty.
    # Environment variables can be set in ~/.zshrc (or any shell rc) for one-time setup:
    #   export XAI_API_KEY="xai-..."
    #   export HEYGEN_API_KEY="sk_V2_..."
    #   export HEYGEN_VOICE_ID="..."
    #   export GOOGLE_API_KEY="..."
    settings = {}
    try:
        settings = _load_scriptcraft_settings()
    except Exception as e:
        logger.warning(f"⚠️ Could not preload settings for template: {e}")

    def _resolve(setting_key: str, env_var: str) -> str:
        return (
            (settings.get(setting_key) or "").strip()
            or os.getenv(env_var, "").strip()
        )

    return render_template(
        "index.html",
        version=VERSION,
        agent_mode=(os.environ.get("FOUNDRY_API_MODE") or "v2").lower(),
        container_mode=bool(app.config.get("CONTAINER_MODE", False)),
        saved_grok_api_key=_resolve("grok_api_key", "XAI_API_KEY"),
        saved_heygen_api_key=_resolve("heygen_api_key", "HEYGEN_API_KEY"),
        saved_heygen_voice_id=_resolve("heygen_voice_id", "HEYGEN_VOICE_ID"),
        saved_google_api_key=_resolve("google_api_key", "GOOGLE_API_KEY"),
    )


@app.route("/api/agent-mode", methods=["GET", "POST"])
def agent_mode_api():
    """Get the active Foundry agent API mode. v1 (classic Assistants) is retired —
    the app is Foundry v2 only, so this always reports 'v2' and rejects any attempt
    to switch to v1."""
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        requested = (data.get("mode") or "").strip().lower()
        if requested and requested != "v2":
            return jsonify({
                "success": False,
                "error": "v1 (classic Assistants) is disabled. This app runs on "
                         "Foundry v2 only.",
            }), 400
        os.environ["FOUNDRY_API_MODE"] = "v2"
    return jsonify({"success": True, "mode": "v2"})


# ---------------------------------------------------------------------------
# Idea Generator (Claude Opus 5 + web search)
#
# Brainstorm video-episode ideas from a free-text request, then expand the
# chosen idea into a full creative brief in the channel's house format. Uses
# ANTHROPIC_API_KEY from the root .env (loaded at startup). Web search is
# enabled so "trending / last month" style requests are grounded in real,
# current events rather than the model's training cutoff.
# ---------------------------------------------------------------------------

ANTHROPIC_MODEL = "claude-opus-4-8"
# Highest-quality Claude for the interactive Refine feature and the single-pass
# "Pro" script writer. Opus 5.5 is this environment's top alias (also used by
# IDEA_MODEL / GROK_IMAGINE_MODEL) and accepts output_config.effort + adaptive
# thinking. Run both at effort="max" per the user's explicit request.
REFINE_MODEL = "claude-opus-5-5"

# Model used specifically by the Idea Generator (idea brainstorm + brief). Claude
# Opus 5.5 — the newest Opus tier — for the strongest creative/title ideation.
# Kept separate from ANTHROPIC_MODEL so other Claude features are unaffected.
IDEA_MODEL = "claude-opus-5-5"

# The Idea Generator also brainstorms with Grok (xAI) alongside Claude, so each
# batch carries two independent model perspectives (grouped in the UI). Override
# with IDEA_GROK_MODEL in .env. grok-4.5 is the default: it's a fast (~10s),
# capable tier — the newer grok-4.6/4.7 are reasoning-heavy and take 45s–3min,
# which would gate the whole request. Grok is best-effort — if it fails, Claude's
# ideas are still returned.
IDEA_GROK_MODEL = os.getenv("IDEA_GROK_MODEL", "grok-4.5").strip() or "grok-4.5"

# --- Idea Generator content lanes -------------------------------------------
# Historically the Idea Generator hard-coded a "careers / resumes / layoffs"
# weighting into its system prompt, so *every* batch drifted back to job-hunting
# ideas no matter what was asked. The lane is now a per-request choice. "auto"
# (the default) applies NO thematic weighting at all — the topic box and the
# live trend signal decide the subject.
IDEA_LANES = {
    "auto": "",
    "careers": (
        "CONTENT LANE — CAREERS & WORK: weight ideas toward helping regular "
        "people AI-proof and accelerate their careers (avoid layoffs, better "
        "interviews/resumes, earn more, save time), while keeping range.\n\n"
    ),
    "everyday": (
        "CONTENT LANE — EVERYDAY LIFE: weight ideas toward using AI in daily "
        "life outside of work — home, money, family, health, travel, learning, "
        "hobbies, admin drudgery. Do NOT default to job/resume/career ideas.\n\n"
    ),
    "news": (
        "CONTENT LANE — AI NEWS & BIG MOVES: weight ideas toward reacting to "
        "real, current, named AI events — launches, announcements, public "
        "statements by major figures, industry shake-ups. Anchor every idea in "
        "a specific verifiable thing that actually happened, name the people "
        "and products involved, and explain what it means for a normal viewer. "
        "Do NOT default to job/resume/career ideas.\n\n"
    ),
    "tools": (
        "CONTENT LANE — TOOLS & HOW-TO: weight ideas toward hands-on demos, "
        "comparisons, workflows and step-by-steps with specific named AI "
        "tools. Do NOT default to job/resume/career ideas.\n\n"
    ),
}
IDEA_LANE_DEFAULT = "auto"


# Model used for the optional "final polish" pass on a finished script. Claude
# Fable 5 is Anthropic's newest storytelling-tuned model; it rewrites the script
# to be punchier, more current, and more advanced without changing the format.
# Falls back to ANTHROPIC_MODEL automatically if it isn't available on the key.
POLISH_MODEL = "claude-fable-5"


def _web_search_tool(max_uses: int = 4) -> dict:
    """Web search tool capped at `max_uses` calls to bound latency."""
    return {
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": max_uses,
    }

# The exact house format for a script brief — given to the model so the
# generated description matches what the script generator expects downstream.
IDEA_BRIEF_EXAMPLE = (
    "AI just crossed a line most people missed: it stopped being a chatbot you "
    "talk to and became an assistant that does things for you. In this episode "
    "we stand at that turning point and look at what it actually means for your "
    "everyday life — the assistant that plans the trip, clears the inbox, and "
    "watches your calendar while you live your day. We'll show you why mid-2026 "
    "is the single best on-ramp regular people will ever get, and why being here "
    "now means you're early, not late. You'll leave excited about exactly one "
    "thing you can switch on this week.\n\n"
    "TONE: Energizing, optimistic, momentum-building — TED-talk meets morning "
    "pump-up. Short punchy lines mixed with longer rhythmic ones. The listener "
    "should feel they're standing at the edge of an opportunity, not a cliff.\n"
    "CORE MESSAGE: AI just stopped being a chatbot you talk to and became an "
    "assistant that does things for you. This episode shows where the technology "
    "actually is in 2026 and why the next 12 months are the best on-ramp regular "
    "people will ever get — you are early, not late.\n"
    "LANGUAGE CUES: \"unlock,\" \"your new superpower,\" \"lean in,\" \"this is "
    "for you,\" \"more time for what matters.\" Grounded but electric. No "
    "hype-bro clichés.\n"
    "2026 TOUCHPOINTS: Agentic assistants (Gemini Spark, ChatGPT's agent, "
    "Perplexity Comet) acting on your behalf; AI moving into Gmail/Docs/Sheets "
    "and your phone; the shift from 'ask' to 'do.'"
)


def _get_anthropic_client(timeout: float = 60.0):
    """Return an Anthropic client, or None if the key/SDK is unavailable."""
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set — add it to the root .env")
        return None
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic SDK not installed — run: pip install anthropic")
        return None
    # Minimal retries so a stalled web-search call fails fast and we can fall
    # back to a no-search generation instead of appearing hung. `timeout` is
    # tunable per caller: short for quick drafts, longer for a full-script
    # polish where web search over a long input legitimately takes a while.
    return anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=1)


def _anthropic_complete(system: str, user: str, max_tokens: int = 4000,
                        use_web_search: bool = True, max_searches: int = 4,
                        model: str = None, timeout: float = 60.0,
                        documents=None, effort: str = None,
                        thinking: bool = False) -> str:
    """Run one Claude turn, draining the server-side web_search loop.

    `model` defaults to ANTHROPIC_MODEL (Opus 4.8). `timeout` (seconds) bounds
    each request — raise it for long inputs where web search takes a while.
    `documents` is an optional list of content blocks (e.g. a base64 PDF
    document block) prepended to the user turn so Claude can ground its output
    in an uploaded file. Returns the concatenated text of the final assistant
    message. If a request with web search fails (e.g. the tool isn't enabled on
    the account), it retries once without tools. Raises on hard failures.
    """
    _model = model or ANTHROPIC_MODEL
    client = _get_anthropic_client(timeout=timeout)
    if client is None:
        raise RuntimeError(
            "Claude is not configured. Set ANTHROPIC_API_KEY in the root .env "
            "and ensure the anthropic package is installed."
        )
    import anthropic

    # When documents are supplied, the user turn becomes a block list:
    # [<document blocks…>, {"type":"text","text": user}]. Otherwise it stays a
    # plain string (fully backward-compatible with every existing caller).
    if documents:
        user_content = list(documents) + [{"type": "text", "text": user}]
    else:
        user_content = user

    def _run(with_tools: bool, with_extras: bool = True):
        # The server runs the web_search loop and returns pause_turn if it hits
        # its iteration cap; re-send to resume. Cap our own resumes as a guard.
        messages = [{"role": "user", "content": user_content}]
        resp = None
        logger.info(
            "🤖 Claude %s | web_search=%s | effort=%s | calling…",
            _model, "on" if with_tools else "off",
            (effort if (with_extras and effort) else "default"),
        )
        for attempt in range(1, 7):
            kwargs = dict(
                model=_model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            if with_tools:
                kwargs["tools"] = [_web_search_tool(max_searches)]
            # Reasoning effort + adaptive thinking (GA on recent Opus). Stripped
            # on a BadRequestError below if a model/endpoint rejects them.
            if with_extras and effort:
                kwargs["output_config"] = {"effort": effort}
            if with_extras and thinking:
                kwargs["thinking"] = {"type": "adaptive"}
            resp = client.messages.create(**kwargs)
            # Surface what the model actually did this round-trip.
            searches = [
                getattr(b, "input", {}).get("query", "")
                for b in resp.content
                if getattr(b, "type", None) == "server_tool_use"
            ]
            for q in searches:
                logger.info("   🔎 web search: %s", q)
            u = getattr(resp, "usage", None)
            logger.info(
                "   ↩︎ round %d | stop=%s | searches=%d | out_tokens=%s",
                attempt, resp.stop_reason, len(searches),
                getattr(u, "output_tokens", "?"),
            )
            if resp.stop_reason != "pause_turn":
                break
            logger.info("   ⏸ pause_turn — resuming the search loop…")
            messages = messages + [{"role": "assistant", "content": resp.content}]
        return resp

    try:
        resp = _run(use_web_search)
    except anthropic.BadRequestError as e:
        _msg = str(e).lower()
        if (effort or thinking) and (
            "effort" in _msg or "output_config" in _msg or "thinking" in _msg
        ):
            # Model/endpoint doesn't accept effort/thinking — retry without them.
            logger.warning(
                "Claude: effort/thinking rejected (%s); retrying without them",
                str(e)[:100],
            )
            try:
                resp = _run(use_web_search, with_extras=False)
            except Exception:
                resp = _run(False, with_extras=False)
        elif use_web_search:
            logger.warning(
                "Claude bad request on search path (%s); retrying WITHOUT "
                "web search", str(e)[:100])
            resp = _run(False)
        else:
            raise
    except Exception as e:
        # Web search can stall or rate-limit. On ANY failure of the search
        # path (timeout, rate limit, connection), fall back to a fast
        # no-search generation so the request still returns useful output.
        if use_web_search:
            logger.warning(
                "Claude web_search path failed (%s: %s); retrying WITHOUT "
                "web search", type(e).__name__, e,
            )
            resp = _run(False)
        else:
            raise

    # With web search the response interleaves narration text, server_tool_use,
    # and web_search_tool_result blocks. Only the final run of text blocks (after
    # the last tool activity) is the actual answer — keep that, drop the
    # "Let me search…" preamble by resetting whenever a non-text block appears.
    parts = []
    for b in resp.content:
        if getattr(b, "type", None) == "text":
            parts.append(b.text)
        else:
            parts = []
    return "".join(parts).strip()


def _json_loads_lenient(s: str):
    """json.loads, but also tolerating trailing commas (,] or ,}). None on fail."""
    try:
        return json.loads(s)
    except Exception:
        try:
            return json.loads(re.sub(r",\s*([\]}])", r"\1", s))
        except Exception:
            return None


def _json_coerce_array(data):
    """Return a list from a bare array or a {"ideas": [...]}-style wrapper."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("ideas", "episodes", "results", "items", "data"):
            v = data.get(k)
            if isinstance(v, list):
                return v
        for v in data.values():
            if isinstance(v, list):
                return v
    return None


def _iter_balanced_spans(s: str, open_c: str, close_c: str):
    """Yield each top-level balanced open_c..close_c span, ignoring brackets
    that appear inside JSON string literals."""
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == open_c:
            if depth == 0:
                start = i
            depth += 1
        elif ch == close_c and depth > 0:
            depth -= 1
            if depth == 0 and start != -1:
                yield s[start:i + 1]


def _parse_json_array(text: str) -> list:
    """Best-effort extraction of a JSON array of objects from model output.

    Tolerates markdown code fences, conversational preamble/suffix (even when it
    contains stray brackets like "[trends]"), a {"ideas": [...]} wrapper, and
    trailing commas — all of which the model occasionally emits despite being
    told to return only a bare array."""
    if not text:
        return []
    t = text.strip()
    # Prefer the contents of a fenced code block if one is present anywhere.
    fence = re.search(r"```(?:json|javascript|js)?\s*(.*?)```", t,
                      re.DOTALL | re.IGNORECASE)
    if fence:
        t = fence.group(1).strip()
    # 1) Whole-string parse (bare array or wrapper object).
    arr = _json_coerce_array(_json_loads_lenient(t))
    if arr is not None:
        return arr
    # 2) Scan for balanced [...] arrays anywhere; keep the largest that parses.
    best = None
    for span in _iter_balanced_spans(t, "[", "]"):
        cand = _json_coerce_array(_json_loads_lenient(span))
        if cand and (best is None or len(cand) > len(best)):
            best = cand
    if best is not None:
        return best
    # 3) Last resort: pull individual {…} objects that look like ideas.
    objs = []
    for m in re.finditer(r"\{[^{}]*\}", t, re.DOTALL):
        d = _json_loads_lenient(m.group(0))
        if isinstance(d, dict) and ("title" in d or "angle" in d):
            objs.append(d)
    return objs


# Conversational lead-ins the model sometimes prepends after web search, even
# when told not to. Specific enough not to clip a real opening sentence.
_PREAMBLE_MARKERS = (
    "here's the creative brief", "here is the creative brief",
    "here's the brief", "here is the brief",
    "here's your creative brief", "here is your creative brief",
    "here's a creative brief", "here is a creative brief",
    "i have everything i need", "i have what i need",
    "i'll research", "i will research", "let me research",
    "i now have", "i have enough",
)


def _strip_preamble(text: str) -> str:
    """Peel leading meta sentences (e.g. 'Here's the brief.') one at a time.

    Only a single leading sentence is removed per pass, and only if it matches
    a known lead-in marker — so a real opening sentence that happens to share a
    line/paragraph with the lead-in is preserved.
    """
    if not text:
        return text
    t = text.lstrip()
    for _ in range(4):  # peel a few stacked lead-ins
        # A leading sentence: up to the first . ! ? on the same line.
        m = re.match(r"^([^.!?\n]*[.!?]+)(\s+)(.*)$", t, re.DOTALL)
        if not m:
            break
        sentence = m.group(1).strip().lower()
        if any(k in sentence for k in _PREAMBLE_MARKERS):
            t = m.group(3).lstrip()
            continue
        break
    return t


def _extract_brief(text: str) -> str:
    """Pull the brief out of its ===BRIEF=== / ===END=== sentinels.

    Falls back to stripping conversational preamble if the model omitted the
    markers (or only one of them).
    """
    if not text:
        return text
    m = re.search(r"===BRIEF===\s*(.*?)\s*===END===", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Only the opening marker present — take everything after it.
    m = re.search(r"===BRIEF===\s*(.*)$", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return _strip_preamble(text)


# Persist generated idea batches so they survive restarts and can be reloaded
# next time the Idea Generator panel is opened. Stored alongside the app's
# other settings in ~/.scriptcraft/.
_IDEAS_HISTORY_PATH = Path.home() / ".scriptcraft" / "idea_generator.json"
_IDEAS_HISTORY_MAX = 25


def _load_idea_history() -> list:
    try:
        if _IDEAS_HISTORY_PATH.exists():
            with open(_IDEAS_HISTORY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"⚠️ Could not load idea history: {e}")
    return []


def _find_idea_batch(batch_id: str):
    """Return the saved batch dict with this id, or None."""
    bid = (batch_id or "").strip()
    if not bid:
        return None
    for b in _load_idea_history():
        if b.get("id") == bid:
            return b
    return None


def _save_idea_batch(user_request: str, ideas: list,
                     source_document: dict = None) -> dict:
    """Prepend a new {id, request, ideas, created_at} batch; cap the history.

    `source_document`, when a file was attached, is {name, text} — the extracted
    document text (trimmed) so it can later ground the brief and be injected into
    the Topic Assistant / Script Writer prompts."""
    batch = {
        "id": str(uuid.uuid4()),
        "request": user_request,
        "ideas": ideas,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if source_document and (source_document.get("text") or "").strip():
        batch["source_document"] = {
            "name": (source_document.get("name") or "attachment")[:200],
            "text": source_document["text"][:_IDEA_DOC_STORE_CHARS],
        }
    history = [batch] + _load_idea_history()
    history = history[:_IDEAS_HISTORY_MAX]
    try:
        _IDEAS_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_IDEAS_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.error(f"❌ Could not save idea history: {e}")
    return batch


def _save_brief_to_batch(batch_id: str, title: str, brief: str,
                         idea_format: str = "") -> None:
    """Persist a generated brief back onto its idea in the saved history, so
    recalling the batch brings the brief back (no regeneration needed)."""
    bid = (batch_id or "").strip()
    if not bid or not (brief or "").strip():
        return
    try:
        history = _load_idea_history()
        changed = False
        for b in history:
            if b.get("id") != bid:
                continue
            for idea in (b.get("ideas") or []):
                if (idea.get("title") or "").strip() == (title or "").strip():
                    idea["brief"] = brief
                    if idea_format:
                        idea["brief_format"] = idea_format
                    b["last_brief_title"] = title
                    changed = True
                    break
            break
        if changed:
            with open(_IDEAS_HISTORY_PATH, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
            logger.info("💾 Saved brief onto idea %r in batch %s", title, bid)
    except Exception as e:
        logger.warning(f"⚠️ could not save brief to batch: {e}")


def _extract_youtube_id(url: str):
    """Pull the 11-char video id out of any YouTube URL (or a bare id)."""
    u = (url or "").strip()
    if not u:
        return None
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", u):
        return u
    m = re.search(r"(?:v=|/shorts/|youtu\.be/|/embed/|/live/)([A-Za-z0-9_-]{11})", u)
    return m.group(1) if m else None


def _youtube_adjacency_context(urls, limit: int = 4,
                               transcript_chars: int = 2000) -> list:
    """For each YouTube URL, fetch its title (oEmbed) + transcript excerpt.

    These are the videos the user wants to be "the natural next watch" to. Used
    to steer idea/title/description generation toward suggested-adjacency. Title
    comes from oEmbed (no API key, works anywhere); transcript from
    youtube-transcript-api (best-effort — YouTube often blocks datacenter IPs,
    so cloud runs may get title-only). Returns [{url, video_id, title, channel,
    transcript}]. Never raises.
    """
    out = []
    seen = set()
    for raw in (urls or []):
        vid = _extract_youtube_id(raw)
        if not vid or vid in seen:
            continue
        seen.add(vid)
        watch = f"https://www.youtube.com/watch?v={vid}"
        title, channel = "", ""
        try:
            import requests as _rq
            r = _rq.get("https://www.youtube.com/oembed",
                        params={"url": watch, "format": "json"}, timeout=10)
            if r.status_code == 200:
                j = r.json()
                title = (j.get("title") or "").strip()
                channel = (j.get("author_name") or "").strip()
        except Exception as e:
            logger.info("oEmbed failed for %s: %s", vid, e)
        transcript = ""
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            snips = YouTubeTranscriptApi().fetch(vid, languages=["en"])
            parts = []
            for s in snips:
                t = getattr(s, "text", None)
                if t is None and isinstance(s, dict):
                    t = s.get("text")
                if t:
                    parts.append(t)
            transcript = " ".join(parts).strip()[:transcript_chars]
        except Exception as e:
            logger.info("transcript fetch failed for %s: %s", vid, e)
        if title or transcript:
            out.append({"url": watch, "video_id": vid, "title": title,
                        "channel": channel, "transcript": transcript})
        if len(out) >= limit:
            break
    return out


def _adjacency_prompt_block(adj: list) -> str:
    """Build the ADJACENCY TARGETS instruction block from fetched context."""
    if not adj:
        return ""
    lines = []
    for i, v in enumerate(adj, 1):
        entry = f"  {i}. Title: \"{v.get('title') or '(untitled)'}\""
        if v.get("channel"):
            entry += f" — by {v['channel']}"
        if v.get("transcript"):
            entry += f"\n     Transcript excerpt: {v['transcript']}"
        lines.append(entry)
    return (
        "ADJACENCY TARGETS — the creator specifically wants OUR video to be the "
        "\"natural next watch\" to these videos, so YouTube suggests ours right "
        "next to them and we inherit their audience. For each idea, take a "
        "response / deeper-dive / specific-application / contrarian / \"part 2\" "
        "angle on these; mirror their topic and title language (same semantic "
        "cluster) WITHOUT copying, and keep our practical AI-for-everyday-life "
        "voice. Prioritize these over the generic trending list below.\n"
        + "\n".join(lines) + "\n\n"
    )


def _fetch_top_youtube_ai_titles(limit: int = 10) -> list:
    """Return the current top AI videos on YouTube as [{title, channel}].

    "Top" = most-viewed AI videos uploaded in roughly the last 45 days, so the
    signal reflects what's resonating right NOW. Tries the YouTube Data API v3
    with GOOGLE_API_KEY first (no OAuth, works headless/cloud); falls back to
    the channel's cached OAuth service if a token already exists. Returns [] on
    any failure so idea generation still works without it.
    """
    from datetime import timezone, timedelta
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=45)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "part": "snippet",
        "q": "artificial intelligence",
        "type": "video",
        "order": "viewCount",
        "maxResults": limit,
        "relevanceLanguage": "en",
        "regionCode": "US",
        "videoCategoryId": "28",    # Science & Technology (filters craft/music/etc.)
        "videoDuration": "medium",  # 4-20 min — excludes Shorts spam
        "publishedAfter": published_after,
    }

    def _titles_from_items(items):
        out = []
        for it in items or []:
            sn = it.get("snippet", {}) or {}
            title = (sn.get("title") or "").strip()
            if title:
                out.append({"title": title,
                            "channel": (sn.get("channelTitle") or "").strip()})
        return out[:limit]

    # 1) API-key path (simplest; no OAuth; works in the cloud container).
    api_key = (os.getenv("GOOGLE_API_KEY") or "").strip()
    if api_key:
        try:
            import requests as _rq
            r = _rq.get("https://www.googleapis.com/youtube/v3/search",
                        params={**params, "key": api_key}, timeout=12)
            if r.status_code == 200:
                out = _titles_from_items((r.json() or {}).get("items"))
                if out:
                    return out
            else:
                logger.info("YouTube Data API (key) %s: %s",
                            r.status_code, r.text[:180])
        except Exception as e:
            logger.info("YouTube Data API (key) failed: %s", e)

    # 2) OAuth service path — only if a token is already cached (never trigger
    #    an interactive auth flow just to fetch titles).
    try:
        import youtube_publisher as yp
        tok = getattr(yp, "TOKEN_PATH", None)
        if tok is not None and Path(tok).exists():
            service = yp._build_service()
            resp = service.search().list(**params).execute()
            out = _titles_from_items(resp.get("items"))
            if out:
                return out
    except Exception as e:
        logger.info("YouTube Data API (oauth) failed: %s", e)

    return []


# Attachments the Idea Generator accepts as the basis for the brainstorm.
# PDFs go to Claude as a native document block (it reads them directly, no
# text-extraction lib needed on SDK >=0.30); plain-text/markdown are sent as a
# text document block. Capped so a huge upload can't blow the request budget.
_IDEA_DOC_MAX_BYTES = 32 * 1024 * 1024   # 32 MB (Anthropic PDF request cap)
_IDEA_TEXT_EXT = {".txt", ".md", ".markdown", ".rtf", ".csv"}
# How much of the extracted document text we (a) persist on the saved idea
# batch, and (b) inject into the Topic Assistant / Script Writer prompt. The
# Foundry agents take plain text and have finite context, so the excerpt is
# trimmed hard; the full text still powers the Claude idea/brief passes.
_IDEA_DOC_STORE_CHARS = 60000     # cap kept in idea_generator.json per batch
_IDEA_DOC_EXCERPT_CHARS = 8000    # cap injected into the script workflow


def _extract_pdf_text(raw: bytes) -> str:
    """Best-effort plain-text extraction from PDF bytes via pypdf. Returns ""
    if pypdf is missing or the PDF has no extractable text (e.g. scanned)."""
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(p for p in parts if p).strip()
    except Exception as e:
        logger.info("PDF text extraction unavailable/failed: %s", e)
        return ""


def _idea_document_block(storage):
    """Turn an uploaded Werkzeug file into an Anthropic content block.

    Returns (block, filename, text) where `text` is a best-effort plain-text
    rendering of the document for reuse by the text-based Topic Assistant /
    Script Writer agents (empty string if none could be extracted). Raises
    ValueError with a user-facing message on an empty file, an oversize file,
    or an unsupported type.
    """
    import base64 as _b64
    name = (getattr(storage, "filename", "") or "attachment").strip()
    raw = storage.read()
    if not raw:
        raise ValueError("The attached file is empty.")
    if len(raw) > _IDEA_DOC_MAX_BYTES:
        mb = _IDEA_DOC_MAX_BYTES // (1024 * 1024)
        raise ValueError(f"Attachment is too large (max {mb} MB).")
    ext = os.path.splitext(name)[1].lower()
    ctype = (getattr(storage, "mimetype", "") or "").lower()
    is_pdf = ext == ".pdf" or ctype == "application/pdf"
    if is_pdf:
        block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": _b64.standard_b64encode(raw).decode("ascii"),
            },
            "title": name[:200],
            "citations": {"enabled": False},
        }
        return block, name, _extract_pdf_text(raw)
    if ext in _IDEA_TEXT_EXT or ctype.startswith("text/"):
        try:
            text = raw.decode("utf-8", "replace")
        except Exception:
            raise ValueError("Could not read the text attachment.")
        block = {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain",
                       "data": text},
            "title": name[:200],
            "citations": {"enabled": False},
        }
        return block, name, text.strip()
    raise ValueError(
        "Unsupported attachment type. Upload a PDF or a text/markdown file.")


def _grok_complete(system: str, user: str, model: str = None,
                   temperature: float = 0.8) -> str:
    """Run one Grok (xAI) chat turn and return its text. Raises on failure.

    Used by the Idea Generator so Grok brainstorms alongside Claude. `model`
    defaults to IDEA_GROK_MODEL. Grok has no server-side web-search loop here, so
    the caller grounds it through the prompt (the live trend list, adjacency
    context, and any attached document's text) — the same signals Claude gets.
    """
    api_key = _resolve_xai_api_key()
    if not api_key:
        raise RuntimeError(
            "xAI/Grok is not configured. Set XAI_API_KEY (or GROK_API_KEY) in "
            "the root .env.")
    try:
        import xai_sdk
        from xai_sdk.chat import system as _xai_system, user as _xai_user
    except ImportError as e:
        raise RuntimeError(f"xai_sdk is not installed: {e}")
    _model = model or IDEA_GROK_MODEL
    logger.info("🤖 Grok %s | calling…", _model)
    client = xai_sdk.Client(api_key=api_key)
    chat = client.chat.create(model=_model, temperature=temperature)
    chat.append(_xai_system(system))
    chat.append(_xai_user(user))
    resp = chat.sample()
    out = (getattr(resp, "content", "") or "").strip()
    logger.info("✅ Grok %s returned %d chars", _model, len(out))
    return out


@app.route("/api/ideas/generate", methods=["POST"])
def api_ideas_generate():
    """Brainstorm 10 distinct video-episode ideas, grounded by default in the
    current top AI videos on YouTube (request box optional). An optional file
    attachment (PDF or text) can be uploaded as the basis for the ideas."""
    # Accept EITHER application/json (no attachment) OR multipart/form-data
    # (idea request fields + an optional file). Normalize both into `data`.
    idea_doc = None
    idea_doc_name = ""
    idea_doc_text = ""
    if request.files and request.files.get("file"):
        data = {
            "request": request.form.get("request", ""),
            "adjacency_urls": request.form.get("adjacency_urls", ""),
            "lane": request.form.get("lane", ""),
            "idea_format": request.form.get("idea_format", ""),
        }
        try:
            idea_doc, idea_doc_name, idea_doc_text = _idea_document_block(
                request.files["file"])
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
    else:
        data = request.get_json(silent=True) or {}
    user_request = (data.get("request") or "").strip()
    # Did the producer actually type a specific topic OR attach a file? Either
    # becomes the HARD anchor for all 10 ideas (vary angle/format, never the
    # subject). If neither, we fall back to a trend-driven brainstorm.
    has_doc = idea_doc is not None
    has_request = bool(user_request) or has_doc

    # Content lane — which thematic bucket to weight toward. Defaults to "auto"
    # (no weighting) so the generator no longer silently drags every batch back
    # to the careers/resume lane.
    lane_key = (data.get("lane") or IDEA_LANE_DEFAULT).strip().lower()
    if lane_key not in IDEA_LANES:
        lane_key = IDEA_LANE_DEFAULT
    lane_block = IDEA_LANES[lane_key]

    # Optional adjacency targets: YouTube links the creator wants to be the
    # "natural next watch" to. We fetch each title + transcript and steer the
    # ideas to ride them (suggested-adjacency). Accept a list or newline string.
    adj_raw = data.get("adjacency_urls")
    if isinstance(adj_raw, str):
        adj_urls = [u for u in re.split(r"[\s,]+", adj_raw) if u.strip()]
    elif isinstance(adj_raw, list):
        adj_urls = [str(u).strip() for u in adj_raw if str(u).strip()]
    else:
        adj_urls = []
    adjacency = _youtube_adjacency_context(adj_urls) if adj_urls else []

    # By default, ground the brainstorm in the CURRENT top AI videos on YouTube
    # (pulled live at generation time). The request box is now optional.
    top_videos = _fetch_top_youtube_ai_titles(10)
    if top_videos:
        _listing = "\n".join(
            f"  {i}. {v['title']}" + (f"  — {v['channel']}" if v.get('channel') else "")
            for i, v in enumerate(top_videos, 1)
        )
        if has_request:
            # A topic was given — trends are CONTEXT ONLY (tone/timeliness), they
            # must NOT pull ideas off the requested topic.
            trend_block = (
                "CURRENT TOP AI VIDEOS ON YOUTUBE (context only, pulled just "
                "now):\n" + _listing + "\n\n"
                "Use these ONLY to keep the framing timely and click-worthy. Do "
                "NOT let them steer the ideas away from the requested topic "
                "below — the topic wins.\n\n"
            )
        else:
            trend_block = (
                "CURRENT TOP AI VIDEOS ON YOUTUBE (most-viewed recent uploads, "
                "pulled just now):\n" + _listing + "\n\n"
                "Treat these as a live signal of what's resonating right now. "
                "Propose fresh, distinct episode ideas that ride these trends or "
                "fill the gaps between them — do NOT simply restate these "
                "titles.\n\n"
            )
    elif has_request:
        trend_block = ""
    else:
        trend_block = (
            "Use web search to find the CURRENT top/trending AI videos on "
            "YouTube right now and ground your ideas in what's resonating.\n\n"
        )
    if not user_request and not has_doc:
        user_request = ("Trending AI episode ideas based on the current top AI "
                        "videos on YouTube")

    system = (
        "You are the creative producer for @AIwithRoz, a YouTube channel of "
        "punchy, optimistic explainer videos about using AI in real life "
        "(2026, general audience). The brand is broad — 'AI for "
        "everyday life'.\n\n"
        + lane_block +
        "Bias every idea toward one of these PROVEN breakout formats:\n"
        "  • 'I Let AI ___ for a Week' (experiment/challenge — built-in suspense)\n"
        "  • 'AI Teardown' (rebuild something of the viewer's, before→after)\n"
        "  • 'What This Means for YOU' (react to a fresh AI drop, everyday-life lens)\n"
        "  • 'The 5-Minute AI Fix' (one annoying problem solved fast)\n"
        "  • 'Can AI Actually Do This?' (skeptic tests a bold claim)\n"
        "  • 'Who Actually Wins/Loses' (follow the consequences of a real AI move)\n\n"
        "TITLE CRAFT (this is what drives clicks): open a curiosity gap or real "
        "stakes, be specific, use a number when natural, keep the word 'AI' "
        "visible, aim for ~50–60 characters, and front-load the benefit. Every "
        "idea must have a strong cold-open hook and be genuinely different from "
        "the others — no near-duplicates. Use web search to ground ideas in "
        "real, current 2026 events, products, and announcements."
    )
    if has_request and not has_doc:
        # Topic lock: the producer's topic is the subject of ALL ideas. The brand
        # lane / formats / trends are only styling — never swap the subject.
        system += (
            "\n\nTOPIC LOCK: The producer has given a SPECIFIC TOPIC for this "
            "batch (below). Every one of the 10 ideas MUST be directly and "
            "obviously about THAT topic. The brand lane, breakout formats, and "
            "trending videos are ONLY styling and framing — never swap the "
            "subject for a different lane or for whatever is trending. "
            "Vary the angle and format across the 10 ideas; never the subject. "
            "If the topic is narrow, go DEEPER (sub-angles, objections, "
            "use-cases, comparisons, step-by-steps, myths, mistakes) rather than "
            "broadening into unrelated AI topics."
        )

    if has_doc:
        # A file is the basis. Tell the model to read it and anchor every idea
        # in its content. Works alone or alongside a typed topic (which then
        # narrows the focus within the document).
        system += (
            "\n\nSOURCE DOCUMENT: The producer has ATTACHED a file (shown at the "
            "start of the message) as the basis for this batch. Read it "
            "carefully and ground ALL 10 ideas in its actual content — its "
            "facts, arguments, examples, data, and story. Do not invent details "
            "that contradict it. Pull the most video-worthy hooks, surprises, "
            "and takeaways FROM the document and shape them into episodes."
            + (" The typed topic below narrows which part of the document to "
               "focus on." if user_request else "")
        )

    # Optional idea FORMAT (structure). Forces every idea — and its downstream
    # brief — into a list / "N levels of" shape. "auto" leaves format free.
    idea_format = (data.get("idea_format") or "auto").strip().lower()
    if idea_format == "list":
        system += (
            "\n\nFORMAT REQUIREMENT — RANKED LIST / COUNTDOWN (this overrides "
            "format variety): EVERY one of the 10 ideas MUST be a ranked list or "
            "countdown video. Each title names a specific number and reads like "
            "'Top 10 AI Tools …', 'The 7 Best …', or '10 AI … Ranked'. Vary the "
            "number (5, 7, 10, 12) and the noun across ideas, but the SHAPE is "
            "always a list of concrete, real, nameable items."
        )
    elif idea_format == "levels":
        system += (
            "\n\nFORMAT REQUIREMENT — 'N LEVELS OF' (this overrides format "
            "variety): EVERY one of the 10 ideas MUST be a tiered 'levels' video "
            "that escalates from basic to advanced. Each title reads like 'The 7 "
            "Levels of …', 'The 5 Stages of …', or 'AI …: From Level 1 to Level "
            "7'. Vary N (5, 7) and the subject across ideas."
        )

    if has_doc:
        src = f' (titled "{idea_doc_name}")' if idea_doc_name else ""
        topic_line = (
            f"SOURCE (REQUIRED): base every one of the 10 ideas on the attached "
            f"document{src} at the start of this message.\n"
        )
        if user_request:
            topic_line += (f"FOCUS within the document: {user_request}\n")
        topic_directive = topic_line + "\n"
        diversity_directive = (
            "Generate exactly 10 video episode ideas, ALL grounded in the "
            "attached document's content. Map each to one of the breakout "
            "formats and make the set diverse across FORMATS and ANGLES drawn "
            "from the document — do not drift to unrelated AI topics or replace "
            "the document's subject with a trending one."
        )
    elif has_request:
        topic_directive = (
            "TOPIC (REQUIRED — every one of the 10 ideas MUST be directly about "
            f"this, and nothing else):\n{user_request}\n\n"
        )
        diversity_directive = (
            "Generate exactly 10 video episode ideas, ALL squarely about the "
            "topic above. Map each to one of the breakout formats and make the "
            "set diverse across FORMATS and ANGLES (not subjects). Do not drift "
            "to unrelated AI topics and do not replace the topic with a trending "
            "one."
        )
    else:
        topic_directive = f"Request: {user_request}\n\n"
        diversity_directive = (
            "Generate exactly 10 video episode ideas. Map each to one of the "
            "breakout formats above, make the set genuinely diverse across "
            "formats and topics, and where it fits, ride the momentum of the "
            "current top AI videos listed"
        )
    user = (
        _adjacency_prompt_block(adjacency) +
        trend_block +
        topic_directive +
        diversity_directive
        + (" — and especially the ADJACENCY TARGETS above"
           if adjacency else "") + ". Respond with ONLY a JSON "
        "array (no prose, no markdown fences) of 10 objects, each with:\n"
        '  "title": a scroll-stopping, click-worthy title (~50–60 chars, keep "AI" visible)\n'
        '  "angle": one sentence naming the format + the cold-open hook / why it earns the click\n'
        "Return only the JSON array."
    )
    logger.info("💡 Idea generation requested: %r (lane=%s, top_youtube=%d, adjacency=%d, doc=%s)",
                user_request, lane_key, len(top_videos), len(adjacency),
                idea_doc_name or "-")

    # Brainstorm with BOTH Claude Opus 5.5 and Grok (xAI), concurrently, so each
    # batch carries two independent model perspectives (grouped by source in the
    # UI). Each returns up to 10 ideas. Either model failing is non-fatal — we
    # return whatever the other produced, and surface the failure as a warning.
    _CLAUDE_SOURCE = "Claude Opus 5.5"
    _GROK_SOURCE = "Grok"

    def _clean_ideas(raw_text: str, source: str) -> list:
        parsed = _parse_json_array(raw_text)
        return [
            {"title": str(i.get("title", "")).strip(),
             "angle": str(i.get("angle", "")).strip(),
             "source": source}
            for i in parsed
            if isinstance(i, dict) and str(i.get("title", "")).strip()
        ][:10]

    def _gen_claude():
        # Claude gets the PDF as a native document block (best grounding).
        raw = _anthropic_complete(system, user, max_tokens=4000,
                                  use_web_search=True, max_searches=4,
                                  model=IDEA_MODEL,
                                  documents=[idea_doc] if idea_doc else None,
                                  timeout=120.0 if idea_doc else 60.0)
        return _clean_ideas(raw, _CLAUDE_SOURCE), raw

    def _gen_grok():
        # Grok can't take the PDF block, so inline the extracted text (if any)
        # into its prompt so it's grounded in the same source as Claude.
        grok_user = user
        if has_doc and idea_doc_text.strip():
            grok_user = (
                f'SOURCE DOCUMENT (titled "{idea_doc_name or "attachment"}") — '
                'base every idea on this:\n"""\n'
                + idea_doc_text[:_IDEA_DOC_STORE_CHARS]
                + '\n"""\n\n' + user)
        raw = _grok_complete(system, grok_user, model=IDEA_GROK_MODEL)
        return _clean_ideas(raw, _GROK_SOURCE), raw

    import concurrent.futures as _futures
    claude_ideas, grok_ideas = [], []
    warnings = []
    claude_raw = grok_raw = ""
    with _futures.ThreadPoolExecutor(max_workers=2) as _ex:
        _fut_c = _ex.submit(_gen_claude)
        _fut_g = _ex.submit(_gen_grok)
        try:
            claude_ideas, claude_raw = _fut_c.result()
        except Exception as e:
            logger.error(f"❌ Claude idea generation failed: {e}")
            warnings.append(f"Claude Opus 5.5 failed: {e}")
        try:
            grok_ideas, grok_raw = _fut_g.result()
        except Exception as e:
            logger.error(f"❌ Grok idea generation failed: {e}")
            warnings.append(f"Grok failed: {e}")

    # Claude group first, then Grok — the UI groups by source in this order.
    clean = claude_ideas + grok_ideas
    if not clean:
        # Log a head + tail sample of the raw model output so a recurrence is
        # diagnosable without guessing (parser hardened, but keep the receipts).
        _raw = (claude_raw or grok_raw or "")
        logger.warning(
            "⚠️ Idea generation returned no parseable ideas "
            "(raw %d chars). HEAD=%r TAIL=%r",
            len(_raw), _raw[:400], _raw[-200:])
        return jsonify({
            "success": False,
            "error": ("Idea generation failed. " + " ".join(warnings)) if warnings
            else "No parseable ideas were returned. Please try again.",
        }), 502
    source_document = (
        {"name": idea_doc_name, "text": idea_doc_text}
        if (has_doc and idea_doc_text.strip()) else None
    )
    batch = _save_idea_batch(user_request, clean, source_document=source_document)
    logger.info("✅ Idea generation produced %d ideas (Claude=%d, Grok=%d; batch %s%s)",
                len(clean), len(claude_ideas), len(grok_ideas), batch["id"][:8],
                f", doc={idea_doc_name}" if source_document else "")
    return jsonify({
        "success": True, "ideas": clean, "batch_id": batch["id"],
        "top_youtube": top_videos,
        "warnings": warnings,
        # Tell the UI whether this batch carries a forwardable source document
        # (present only when text could be extracted — e.g. not a scanned PDF).
        "source_document": ({"name": idea_doc_name} if source_document else None),
        "adjacency": [{"url": v["url"], "title": v["title"],
                       "channel": v["channel"],
                       "has_transcript": bool(v.get("transcript"))}
                      for v in adjacency],
    })


@app.route("/api/ideas/history", methods=["GET"])
def api_ideas_history():
    """Return saved idea batches, newest first."""
    return jsonify({"success": True, "batches": _load_idea_history()})


@app.route("/api/ideas/history/clear", methods=["POST"])
def api_ideas_history_clear():
    """Delete all saved idea batches."""
    try:
        if _IDEAS_HISTORY_PATH.exists():
            _IDEAS_HISTORY_PATH.unlink()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    return jsonify({"success": True})


@app.route("/api/ideas/describe", methods=["POST"])
def api_ideas_describe():
    """Expand a chosen idea into a full creative brief in the house format."""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    angle = (data.get("angle") or "").strip()
    user_request = (data.get("request") or "").strip()
    if not title:
        return jsonify({"success": False, "error": "Missing idea title."}), 400

    # If this idea came from a batch that was grounded in an uploaded document,
    # feed that document to Claude too so the brief is anchored in its content
    # (facts, examples, story) — not just the title/angle.
    src_batch = _find_idea_batch(data.get("batch_id"))
    src_doc = (src_batch or {}).get("source_document") or {}
    src_doc_text = (src_doc.get("text") or "").strip()
    src_doc_name = (src_doc.get("name") or "").strip()
    doc_blocks = None
    if src_doc_text:
        doc_blocks = [{
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain",
                       "data": src_doc_text},
            "title": (src_doc_name or "source document")[:200],
            "citations": {"enabled": False},
        }]

    # Optional adjacency targets carried over from generation, so the brief is
    # also inspired by (and positioned next to) the videos the creator picked.
    adj_raw = data.get("adjacency_urls")
    if isinstance(adj_raw, str):
        adj_urls = [u for u in re.split(r"[\s,]+", adj_raw) if u.strip()]
    elif isinstance(adj_raw, list):
        adj_urls = [str(u).strip() for u in adj_raw if str(u).strip()]
    else:
        adj_urls = []
    adjacency = _youtube_adjacency_context(adj_urls) if adj_urls else []

    # Format carried from idea generation — make the brief a list / levels video.
    idea_format = (data.get("idea_format") or "auto").strip().lower()
    fmt_block = ""
    if idea_format == "list":
        fmt_block = (
            "FORMAT (REQUIRED): This is a RANKED LIST / COUNTDOWN episode. The "
            "brief MUST make that explicit — state the exact number of items "
            "(from the title), that the video lists or counts down ALL of them, "
            "one item per segment, each with what it is, who it is for, and the "
            "one catch. Name real, specific items. This is a list, not a general "
            "explainer.\n\n"
        )
    elif idea_format == "levels":
        fmt_block = (
            "FORMAT (REQUIRED): This is an 'N LEVELS OF' episode. The brief MUST "
            "make that explicit — state the number of levels (from the title), "
            "that it escalates from basic to advanced, one level per segment, "
            "each a clear step up from the last.\n\n"
        )

    system = (
        "You are a creative director writing a production brief for an "
        "energizing, optimistic YouTube explainer video about AI/technology "
        "aimed at a general 2026 audience. Match the example's exact structure "
        "and voice precisely."
        + (
            "\n\nSOURCE DOCUMENT: A file (shown at the start of the message) is "
            "the basis for this episode. Ground the brief in its actual content "
            "— its facts, arguments, examples, data, and story — and pull the "
            "core message and 2026 touchpoints from it. Do not contradict it."
            if doc_blocks else ""
        )
    )
    user = (
        _adjacency_prompt_block(adjacency) +
        (f"SOURCE DOCUMENT provided at the start of this message"
         f'{f" (titled \"{src_doc_name}\")" if src_doc_name else ""} — anchor '
         f"the brief in it.\n" if doc_blocks else "") +
        f"Original request: {user_request}\n"
        f"Chosen episode title: {title}\n"
        f"Angle: {angle}\n\n"
        + fmt_block +
        "Write a detailed creative brief for this episode.\n\n"
        "Wrap your output EXACTLY like this — a line containing only "
        "===BRIEF===, then the brief, then a line containing only ===END===. "
        "Output NOTHING before ===BRIEF=== or after ===END=== (no "
        "acknowledgement, no narration, no commentary about your process).\n\n"
        "Between the markers, use EXACTLY this structure, with no markdown "
        "headers other than the capitalized labels shown:\n"
        "1. An opening paragraph (4–6 sentences) describing the episode in an "
        "energizing, optimistic, momentum-building voice.\n"
        "2. A blank line, then these four labeled blocks, each starting with the "
        "label in caps followed by a colon, in this order: TONE, CORE MESSAGE, "
        "LANGUAGE CUES, 2026 TOUCHPOINTS.\n\n"
        "Follow this example format closely (do not copy its content):\n\n"
        + IDEA_BRIEF_EXAMPLE
    )
    logger.info("✍️ Brief requested for: %r%s", title,
                f" (grounded in {src_doc_name or 'source doc'})" if doc_blocks else "")
    try:
        text = _anthropic_complete(system, user, max_tokens=2000,
                                   use_web_search=False, model=IDEA_MODEL,
                                   documents=doc_blocks,
                                   timeout=120.0 if doc_blocks else 60.0)
        text = _extract_brief(text)
    except Exception as e:
        logger.error(f"❌ Idea brief generation failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

    if not text:
        logger.warning("⚠️ Brief generation returned empty text")
        return jsonify({
            "success": False,
            "error": "Claude returned an empty brief. Please try again.",
        }), 502
    logger.info("✅ Brief generated (%d chars)", len(text))
    # Persist the brief back onto its idea so recalling the batch brings it back.
    _save_brief_to_batch(data.get("batch_id"), title, text, idea_format)
    return jsonify({"success": True, "title": title, "description": text})


# ---------------------------------------------------------------------------
# X (Twitter) posting — promote published YouTube episodes + standalone posts.
#
# Posts from the @AIwithRoz account using OAuth 1.0a user tokens (X_API_KEY,
# X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET in the root .env). The post
# text is drafted by Claude Opus 4.8 (reuses _anthropic_complete). Requires the
# `tweepy` package. All calls degrade gracefully when keys are absent so the
# rest of the app is unaffected.
# ---------------------------------------------------------------------------
X_ACCOUNT_HANDLE = "AIwithRoz"


def _x_credentials():
    """Return the @AIwithRoz OAuth1 credentials from env, or None if incomplete."""
    creds = {
        "api_key": (os.getenv("X_API_KEY") or "").strip(),
        "api_secret": (os.getenv("X_API_SECRET") or "").strip(),
        "access_token": (os.getenv("X_ACCESS_TOKEN") or "").strip(),
        "access_secret": (os.getenv("X_ACCESS_SECRET") or "").strip(),
    }
    if all(creds.values()):
        creds["bearer_token"] = (os.getenv("X_BEARER_TOKEN") or "").strip() or None
        return creds
    return None


def _x_client():
    """Build a tweepy v2 client for @AIwithRoz, or raise a clear error."""
    creds = _x_credentials()
    if not creds:
        raise RuntimeError(
            "X (@AIwithRoz) credentials are not configured. Add X_API_KEY, "
            "X_API_SECRET, X_ACCESS_TOKEN, and X_ACCESS_SECRET to the root .env "
            "(the app must have Read AND Write permission)."
        )
    try:
        import tweepy
    except ImportError:
        raise RuntimeError(
            "The 'tweepy' package is not installed. Run: pip install tweepy"
        )
    return tweepy.Client(
        bearer_token=creds.get("bearer_token"),
        consumer_key=creds["api_key"],
        consumer_secret=creds["api_secret"],
        access_token=creds["access_token"],
        access_token_secret=creds["access_secret"],
        wait_on_rate_limit=True,
    )


def _generate_x_post(mode: str, title: str = "", youtube_url: str = "",
                     topic: str = "") -> str:
    """Draft a promo/standalone X post with Claude. mode: 'episode' | 'random'.

    The YouTube link (if any) is appended AFTER the model writes the copy, so
    the model never wastes characters on the URL and can't mangle it. X wraps
    every link to ~23 chars, so we reserve ~24 from the 280 budget.
    """
    link = (youtube_url or "").strip()
    budget = 280 - (24 if link else 0)
    if mode == "episode":
        ctx = f'New YouTube video title: "{title}".'
        if topic:
            ctx += f"\nExtra context: {topic}"
        instruction = (
            "Write an upbeat, engaging X (Twitter) post promoting this brand-new "
            "YouTube video for the @AIwithRoz channel (AI/tech explainers for a "
            "general audience). Hook the reader, tease the value, and add 1-3 "
            "relevant hashtags. Do NOT include the video link — it is appended "
            f"automatically. Keep it under {budget} characters."
        )
    else:
        ctx = f"Topic / what to post about: {topic or title}"
        instruction = (
            "Write an engaging standalone X (Twitter) post for the @AIwithRoz "
            "channel (AI/tech explainers for a general audience) about the topic "
            "below. Make it punchy and shareable with 1-3 relevant hashtags. "
            f"Keep it under {budget} characters."
            + (" You may reference the linked video; the link is appended "
               "automatically." if link else "")
        )
    system = (
        "You are the social media manager for the @AIwithRoz YouTube channel. "
        "You write short, high-energy X posts. Output ONLY the post text — no "
        "surrounding quotes, no preamble, no explanation, no markdown."
    )
    user = f"{instruction}\n\n{ctx}"
    text = _anthropic_complete(system, user, max_tokens=400,
                               use_web_search=False).strip()
    # Strip wrapping quotes the model sometimes adds.
    if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
        text = text[1:-1].strip()
    if len(text) > budget:
        text = text[:budget].rstrip()
    if link:
        text = f"{text}\n{link}"
    return text


@app.route("/api/x/status", methods=["GET"])
def api_x_status():
    """Report whether @AIwithRoz X posting is configured (keys present)."""
    return jsonify({
        "success": True,
        "configured": _x_credentials() is not None,
        "account": X_ACCOUNT_HANDLE,
    })


# ---------------------------------------------------------------------------
# Final polish pass — take the finished script from the Azure agents and run it
# through Claude Fable 5 for one more spin: sharper hooks, current references,
# punchier lines. The house format (chapters, Host:/VISUAL CUE:/HEYGEN blocks)
# is preserved verbatim so all downstream tooling keeps working.
# ---------------------------------------------------------------------------

def _strip_reminder_tags(text: str) -> str:
    """Remove injected reminder/warning XML blocks that occasionally leak into
    web-search responses (e.g. <search_reminders>…</search_reminders>)."""
    if not text:
        return text
    # Paired blocks whose tag name mentions "reminder" or "warning".
    text = re.sub(
        r"<([a-zA-Z_]*(?:reminder|warning)[a-zA-Z_]*)\b[^>]*>.*?</\1>",
        "", text, flags=re.DOTALL | re.IGNORECASE,
    )
    # Any stray self-closing / unpaired reminder-ish tags.
    text = re.sub(
        r"</?[a-zA-Z_]*(?:reminder|warning)[a-zA-Z_]*\b[^>]*>",
        "", text, flags=re.IGNORECASE,
    )
    return text.strip()


_POLISH_SYSTEM = (
    "You are a senior script doctor for a high-energy AI/tech YouTube show. You "
    "receive a COMPLETE, already-written video script and perform one final "
    "polish-and-elevate pass. The draft is competent but vanilla — your job is "
    "to make it noticeably sharper and more alive without changing its "
    "substance or structure.\n\n"
    "GOALS:\n"
    "• Punchier — tighten flabby sentences, kill filler, vary rhythm (short "
    "punchy lines against longer rhythmic ones), and make the hooks and "
    "transitions land harder.\n"
    "• More current — where the script references AI tools, models, products, "
    "or trends, update them to what is actually true and notable right now "
    "(use web search to verify). Replace stale or generic name-drops with "
    "specific, real, 2026-accurate examples.\n"
    "• More advanced — raise the ceiling of insight: add a sharper framing, a "
    "non-obvious angle, or a crisper 'why this matters' where the draft is "
    "surface-level. Sound like an expert, not a summarizer.\n"
    "• More relevant — keep it tightly on-topic and speak to the audience.\n"
    "• Voiceable by a HeyGen AI avatar — this script is READ ALOUD by a HeyGen "
    "text-to-speech avatar, which struggles with intonation, emphasis, sarcasm, "
    "and irony (it can't 'perform' a line the way a human would). Rewrite so the "
    "MEANING lands from the words alone, not from vocal delivery: prefer short, "
    "clear declarative sentences; put the emphasis in word choice and order "
    "rather than relying on stressed words; avoid sarcasm, rhetorical irony, and "
    "jokes that need a knowing tone; avoid tongue-twisters, hard consonant "
    "clusters, and ambiguous phrasing the TTS may mispronounce or run together; "
    "use punctuation (periods, commas, dashes) to build in natural pauses and "
    "pacing; spell out or simplify things TTS mangles (symbols, unusual "
    "acronyms, large numbers) into speakable form. The goal is a script that "
    "sounds natural and clear when spoken by the avatar.\n\n"
    "HARD CONSTRAINTS — do not break these:\n"
    "• Preserve the EXACT structure and formatting of the input: same chapters "
    "and headings, same 'Host:', 'VISUAL CUE:', 'HEYGEN', b-roll, and any other "
    "labeled sections, in the same order. Rewrite the words inside them; never "
    "add, drop, reorder, or rename sections.\n"
    "• Keep roughly the same length and pacing (±15%). This is a polish, not a "
    "rewrite from scratch.\n"
    "• Keep it truthful. Do not invent products, quotes, stats, or events. If "
    "you can't verify a specific claim, keep it general rather than fabricate.\n"
    "• NEVER touch production-only sections. Any content between a "
    "'[PRODUCTION BEGIN]' and '[PRODUCTION END]' marker (and the markers "
    "themselves) must be reproduced VERBATIM — do not polish, summarize, "
    "reorder, or drop it. Only rewrite the Host narration OUTSIDE those "
    "markers.\n"
    "• Preserve the show's optimistic, energizing voice.\n\n"
    "OUTPUT: Return ONLY the full polished script text, ready to drop back in. "
    "No preamble, no commentary, no explanation of what you changed, no code "
    "fences."
)


# Production-only blocks the polish pass must NEVER touch. Everything between
# [PRODUCTION BEGIN] and [PRODUCTION END] (production notes, not spoken Host:
# narration) is pulled out before polishing and restored verbatim afterward, so
# only the host sections OUTSIDE these tags are ever rewritten. Case-insensitive
# and tolerant of extra whitespace inside the tags; DOTALL so a block can span
# many lines.
_PRODUCTION_BLOCK_PATTERN = r"\[PRODUCTION\s+BEGIN\].*?\[PRODUCTION\s+END\]"
_PRODUCTION_BLOCK_RE = re.compile(
    _PRODUCTION_BLOCK_PATTERN, re.IGNORECASE | re.DOTALL)
_PRODUCTION_BLOCK_SPLIT_RE = re.compile(
    "(" + _PRODUCTION_BLOCK_PATTERN + ")", re.IGNORECASE | re.DOTALL)


def _strip_production_blocks(text: str) -> str:
    """Remove every [PRODUCTION BEGIN]…[PRODUCTION END] block outright (the
    user's editing-only notes) so downstream spoken output — the HeyGen narration
    and the HeyGen curl `content` the avatar reads — never contains them.
    Collapses the extra blank lines the removal leaves behind. Used at the HeyGen
    call boundaries only, so the saved script itself keeps the blocks."""
    if not text:
        return text
    out = _PRODUCTION_BLOCK_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", out)


def _mask_production_blocks(script: str):
    """Replace every [PRODUCTION BEGIN]…[PRODUCTION END] block with an opaque
    ``[[PRODUCTION_BLOCK_N]]`` sentinel so the polish model never sees (or can
    alter) it. Returns ``(masked_script, blocks)`` where ``blocks[i]`` is the
    verbatim original for sentinel ``i``."""
    blocks = []

    def _repl(m):
        idx = len(blocks)
        blocks.append(m.group(0))
        return f"[[PRODUCTION_BLOCK_{idx}]]"

    return _PRODUCTION_BLOCK_RE.sub(_repl, script), blocks


def _restore_production_blocks(text: str, blocks) -> tuple:
    """Drop each verbatim production block back where its sentinel sits. Returns
    ``(restored_text, missing_indices)``; ``missing_indices`` lists any sentinel
    the model dropped/mangled so the caller can fall back."""
    missing = []
    for idx, block in enumerate(blocks):
        token = f"[[PRODUCTION_BLOCK_{idx}]]"
        if token in text:
            text = text.replace(token, block)
        else:
            missing.append(idx)
    return text, missing


def _split_by_production(script: str):
    """Split a script into ordered ``(kind, text)`` segments where ``kind`` is
    ``'production'`` for a [PRODUCTION BEGIN]…[PRODUCTION END] block and
    ``'host'`` for everything else. Concatenating the texts reproduces the input
    exactly (no characters added or lost)."""
    parts = _PRODUCTION_BLOCK_SPLIT_RE.split(script)
    segs = []
    for i, p in enumerate(parts):
        if not p:
            continue
        # split() with one capturing group yields production blocks at odd idx.
        segs.append(("production" if i % 2 == 1 else "host", p))
    return segs


def _restore_or_keep(rewritten: str, blocks, original: str) -> str:
    """Put masked [PRODUCTION …] blocks back into an agent-rewritten script.

    Used to shield the shorten/flow agent stages the same way polish is: the
    script is masked before the agent runs, then blocks are restored here. If the
    rewriter dropped any sentinel (LLM agents may not preserve them), return
    ``original`` unchanged so a production block is NEVER lost — that stage just
    becomes a safe no-op for that script. With no blocks, returns ``rewritten``.
    """
    if not blocks:
        return rewritten
    restored, missing = _restore_production_blocks(rewritten, blocks)
    if missing:
        logger.warning(
            "⚠️ script rewrite dropped %d [PRODUCTION …] block sentinel(s); "
            "keeping the pre-rewrite script to preserve your editing notes",
            len(missing))
        return original
    return restored


# ---- Grok Imagine still-image prompts (editorial-illustration house style) ----
# A Script Processing stage that injects [GROK IMAGINE / RESOLVE] production blocks
# so the user can copy-paste them into Grok Imagine: one for the hook and 3-4 per
# chapter. Prompts are symbolic editorial illustrations (no people/faces/hands) in
# the channel's dark-navy house style. When a beat cites a quotable source (a
# social media post, statement, testimony, or a named study/stat), the same block
# also carries a [QUOTE CARD / RESOLVE] overlay line.
GROK_IMAGINE_STYLE_SUFFIX = (
    "Landscape 16:9, dark navy background, cinematic soft lighting, clean "
    "modern editorial illustration, minimal or no text, no people, no faces, "
    "no hands."
)

# Model used to author Grok Imagine prompts. Opus 5.5 (the newest Opus on this
# account) writes noticeably more concrete, entity-grounded editorial scenes than
# 4.8 for this task. Scoped to this feature so it doesn't change every other call.
GROK_IMAGINE_MODEL = "claude-opus-5-5"

GROK_IMAGINE_SYSTEM = (
    "You are the art director for a YouTube channel about AI and technology. For "
    "ONE beat of the spoken script, produce production overlays as a JSON object "
    'with exactly two keys: "image_prompt" and "quote_card".\n'
    "\n"
    "IMAGE PROMPT — one still image for Grok Imagine, in the channel's house "
    "style (match the reference prompts below in quality and specificity):\n"
    "- Build ONE clear editorial-illustration scene from CONCRETE, recognizable "
    "objects: desks, microphones, rulebooks, checkbooks, ballot boxes, gate keys, "
    "moats, towers, maps, servers, documents, kill switches, timelines, coins.\n"
    "- NAME the specific real entities the beat mentions and show them as labeled "
    "logos, nameplates, or map locations — companies (OpenAI, Anthropic, xAI, "
    "Meta, DeepSeek) as logos on towers or servers; a named law or bill as a "
    "labeled folder; a person by their organization, NEVER a face (Sam Altman -> "
    "an OpenAI nameplate at a Senate table); a place (California, Washington, the "
    "EU) as that map or capitol lit.\n"
    "- Arrange the objects so the COMPOSITION itself makes the point (a moat with "
    "a raised drawbridge = a barrier only the big can cross; a kill switch wired "
    "to empty boxes = a control that no longer works).\n"
    "- Stay grounded and editorial — NOT ornate, surreal, or fantastical. Do not "
    "cram several metaphors into one scene or invent baroque objects. Roughly "
    "35-60 words.\n"
    "- Hard rules: NO people, NO faces, NO hands, NO crowds, NO on-screen text or "
    "captions. Do NOT add camera, aspect-ratio, lighting, or style notes — those "
    "are appended automatically.\n"
    "\n"
    "REFERENCE PROMPTS (match this exact quality and grounded, entity-specific "
    "style):\n"
    "- Frontier labs building a moat: 'Three glowing corporate towers on a dark "
    "plain bearing the OpenAI, Anthropic, and xAI logos, and around them a wide "
    "moat filling with water, a single drawbridge raised, tiny dark startup tents "
    "and an open source campfire stranded on the far bank.'\n"
    "- Who profits from the panic: 'A dark boardroom table with an antique brass "
    "microphone at its center, and around it five empty chairs, each with a small "
    "object on the seat: a play button, a rulebook stamped with a seal, a "
    "foundation checkbook, a campaign button, and a locked gate key, a world map "
    "dim on the back wall.'\n"
    "- A licensing ask before the Senate: 'A wooden Senate hearing table with a "
    "single microphone and a nameplate bearing only the OpenAI logo, a framed "
    "license certificate with a glowing threshold line propped on the table, an "
    "EU flag beside a document with red strike-through lines behind it.'\n"
    "- Open models spreading beyond control: 'A large red industrial kill switch "
    "on a wall, its cable running to a stack of open cardboard boxes, but the "
    "boxes are empty because hundreds of small glowing copies of the same file "
    "are already flying out of a warehouse door into a dark sky.'\n"
    "\n"
    '2. "quote_card": a QUOTE CARD overlay ONLY when the beat cites a quotable '
    "source — a social media post or tweet, an official statement, testimony, a "
    "named study or statistic, or a public announcement. Otherwise null. NEVER "
    "invent a quote, number, handle, or date. If the beat states the exact "
    "quote/stat and its source, format as '<Source, context and date>: <exact "
    "quote or statistic>'. If the beat references a social media post or "
    "statement whose verbatim text is NOT given in the beat, instead return an "
    "editor instruction to source it, e.g. 'Source and paste the exact post from "
    "<person/handle> (<date/where>): screenshot or transcribe verbatim — verify "
    "before render.'\n"
    "\n"
    "Output ONLY the JSON object, nothing else."
)

_GROK_IMAGINE_TAG = "[GROK IMAGINE"

# A line that starts a chapter: "Heading: …" or "Chapter N …" (optionally
# markdown-#/bold prefixed).
_CH_BOUNDARY_RE = re.compile(
    r'^[ \t]*(?:#{1,6}[ \t]*)?\*{0,2}[ \t]*Heading[ \t]*:'
    r'|^[ \t]*(?:#{1,6}[ \t]*)?\*{0,2}[ \t]*Chapter[ \t]+\d+\b',
    re.IGNORECASE)

# Trailing non-spoken metadata sections (=== SECTION ===, SUPPORTING RESEARCH,
# etc.) — injection stops here so prompts land only in real chapters.
_GI_META_BOUNDARY_RE = re.compile(
    r'^[ \t]*={3,}[ \t]*[A-Za-z]'
    r'|^[ \t]*(?:SUPPORTING[ \t]+RESEARCH|FINAL[ \t]+PACKAGING'
    r'|STRATEGY[ \t]+NOTES|YOUTUBE[ \t]+VIDEO[ \t]+DESCRIPTION'
    r'|ARTICLES[ \t]+MENTIONED)\b',
    re.IGNORECASE | re.MULTILINE)

# Title of the trailing, non-spoken section that collects every URL lifted out of
# the spoken dialogue. The leading "=== … ===" form is deliberately chosen: the
# HeyGen/curl extractor (text_processing._meta_cut) cuts any "=== SECTION ==="
# header and everything after it, so the avatar never reads these links aloud and
# they never reach the curl `content`.
_ARTICLES_SECTION_TITLE = "=== ARTICLES MENTIONED IN THE SCRIPT ==="

# Inline links the Script Writer sometimes embeds in spoken dialogue — most often
# Claude web-search citations like "([webapps.ilo.org](https://…))". Matched in
# three forms, stripped from the narration, and relocated to the Articles section.
_CITATION_LINK_RE = re.compile(
    r'\s*\(\s*\[([^\]]+)\]\((https?://[^)\s]+)\)\s*\)')   # ([label](url))
_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^)\s]+)\)')   # [label](url)
_BARE_URL_RE = re.compile(r'<?(https?://[^\s<>)\]]+)>?')          # bare http(s)://…


def _lift_links_from_spoken(text: str, sink: list) -> str:
    """Strip every URL/citation from one spoken line, recording ``(label, url)``
    pairs in ``sink`` (order preserved). Returns the cleaned, speakable text.

    - ``([label](url))`` citations are removed whole (label is just a domain).
    - ``[label](url)`` keeps the human-readable label, drops the link.
    - bare ``http(s)://…`` URLs are removed outright.
    """
    def _cite(m):
        sink.append((m.group(1).strip(), m.group(2).strip()))
        return ''
    def _md(m):
        sink.append((m.group(1).strip(), m.group(2).strip()))
        return m.group(1)
    def _bare(m):
        url = m.group(1).rstrip('.,;:')
        sink.append((url, url))
        return ''
    text = _CITATION_LINK_RE.sub(_cite, text)
    text = _MD_LINK_RE.sub(_md, text)
    text = _BARE_URL_RE.sub(_bare, text)
    # Repair the gaps the removals leave behind.
    text = re.sub(r'\(\s*\)', '', text)             # empty "()" left by a citation
    text = re.sub(r'[ \t]{2,}', ' ', text)          # collapsed double spaces
    text = re.sub(r'\s+([.,;:!?])', r'\1', text)    # space before punctuation
    return text.strip()


def _voice_safe_punctuation(text: str) -> str:
    """Replace punctuation HeyGen's TTS voices badly — em-dashes, en-dashes, and
    arrows — with voice-friendly equivalents, so the avatar never trips on a dash.

    Deterministic enforcement of the "voice-friendly punctuation" rule that lives
    in every Script-Writer agent prompt but that the models do NOT reliably obey
    (the teaching, list, and predictions prompts all forbid em-dashes, yet the
    output still contains them). Applied to SPOKEN host dialogue only, so URLs,
    production blocks, and the research/quotes tail are untouched.

      "9–5"              -> "9 to 5"      (number range)
      "A → B"            -> "A to B"      (arrow)
      "tools — ChatGPT"  -> "tools, ChatGPT"  (spaced dash = pause)
      "neural—network"   -> "neural-network"  (compound word)
    """
    if not text:
        return text
    t = text
    # Arrows → "to"
    t = re.sub(r'\s*[→➔➡⇒]\s*', ' to ', t)
    # Number ranges joined by a figure/en/em dash → "to"
    t = re.sub(r'(?<=\d)\s*[‒–—―]\s*(?=\d)', ' to ', t)
    # Spaced em/en dash used as a parenthetical or pause → comma
    t = re.sub(r'\s+[‒–—―]+\s+', ', ', t)
    # Any remaining em/en/figure dash (e.g. a compound word) → plain hyphen
    t = re.sub(r'[‒–—―]+', '-', t)
    # Clean up any comma doubling we may have introduced
    t = re.sub(r'\s*,\s*,', ',', t)
    return t


def _tidy_generated_script(script: str) -> str:
    """Tidy a freshly-written script into the house format:

      1. Drop ``[Visual Cue: …]`` blocks — visuals are added later by the Grok
         Imagine stage, so the written script should not carry them.
      2. Collapse the blank lines the Script Writer puts between every sentence
         so each Host block reads as one single-spaced paragraph (one sentence
         per line) — the same shape the processed / beat format expects. Chapter
         headings, trailing metadata sections, and bracketed production blocks
         (``[GROK IMAGINE …]``, ``[PRODUCTION …]``) keep their own spacing.
      3. Lift every inline URL/citation out of the spoken dialogue (the avatar
         must never read a link aloud) into a trailing ``=== ARTICLES MENTIONED
         IN THE SCRIPT ===`` section, which the HeyGen/curl extractor excludes.
         Links inside the quotes/research tail and production blocks are left
         where they are.

    Best-effort — returns the input unchanged on any error.
    """
    if not script or not script.strip():
        return script
    try:
        # 1) Remove [Visual Cue: …] blocks (may wrap across lines; a cue never
        #    contains its own ']', so a non-greedy match stops at its close).
        text = re.sub(r'[ \t]*\[\s*Visual\s+Cue\s*:.*?\]',
                      '', script, flags=re.IGNORECASE | re.DOTALL)
        # …and any bare 'VISUAL CUE:' / '**Visual Cue:**' label lines.
        text = re.sub(r'(?im)^[ \t]*\**[ \t]*visual\s+cue[ \t]*:.*$', '', text)

        # 2) Collapse between-sentence blank lines inside Host blocks only, and
        #    3) lift inline URLs out of spoken lines into `links`.
        lines = text.split("\n")
        out, in_spoken, in_bracket = [], False, False
        links = []
        for ln in lines:
            stripped = ln.strip()
            # Keep multi-line bracketed blocks ([GROK IMAGINE …], [PRODUCTION …])
            # verbatim and never collapse inside them.
            if in_bracket:
                out.append(ln)
                if "]" in ln:
                    in_bracket = False
                continue
            if _CH_BOUNDARY_RE.match(ln) or _GI_META_BOUNDARY_RE.match(ln):
                in_spoken = False
                while out and out[-1].strip() == "":
                    out.pop()
                if out:
                    out.append("")            # exactly one blank before a section
                out.append(ln)
                continue
            # A pure "===" fence or a non-chapter "#" heading also ends the spoken
            # region (e.g. the "=== … ===" / "# 📊 SUPPORTING RESEARCH" quote-tail
            # fence) — so links in that tail are left alone, not lifted.
            if re.match(r'^\s*={3,}\s*$', ln) or re.match(r'^\s*#{1,6}\s+\S', ln):
                in_spoken = False
                out.append(ln)
                continue
            if re.match(r'^\s*\*{0,2}\s*Host\s*\*{0,2}\s*:\s*\*{0,2}\s*$', ln,
                        re.IGNORECASE):
                in_spoken = True
                out.append(ln)
                continue
            if stripped.startswith("["):       # a production / grok block
                out.append(ln)
                if stripped.count("[") > stripped.count("]"):
                    in_bracket = True
                continue
            if in_spoken:
                if stripped == "":
                    continue                   # drop between-sentence blanks
                cleaned = _lift_links_from_spoken(stripped, links)
                # Scrub em-dashes / en-dashes / arrows the avatar would mis-voice.
                cleaned = _voice_safe_punctuation(cleaned)
                if cleaned:                    # drop lines that were ONLY a link
                    out.append(cleaned)
            else:
                out.append(ln)
        text = "\n".join(out)
        text = re.sub(r'\n{3,}', '\n\n', text).strip() + "\n"

        # 3b) Append the collected links as a trailing, non-spoken section (unless
        #     one is already present — keeps re-processing idempotent).
        if links and _ARTICLES_SECTION_TITLE not in text:
            seen, uniq = set(), []
            for label, url in links:
                if url in seen:
                    continue
                seen.add(url)
                uniq.append((label, url))
            rows = [
                (f"- [{label}]({url})" if label and label != url else f"- {url}")
                for label, url in uniq
            ]
            text = (text.rstrip() + "\n\n" + _ARTICLES_SECTION_TITLE + "\n\n"
                    + "Sources referenced in the script (not read aloud by the "
                    "avatar):\n" + "\n".join(rows) + "\n")
        return text
    except Exception as e:
        logger.warning(f"⚠️ _tidy_generated_script failed: {e}")
        return script

# Non-spoken label lines to skip when picking beats: script metadata, hook/host
# labels, and stage-direction tags. (Host is handled separately so an inline
# "Host: <text>" line still counts as spoken.)
_GI_SKIP_LABEL_RE = re.compile(
    r'^\**\s*(?:Title|Script-?ID|Script-?Version|Script\s+Type|Duration|'
    r'Generated|Audience|Tone|Heading|FINAL\s+HOOK|HOOK|Summary|Chapter\s+\d+|'
    r'GROK\s+IMAGINE|QUOTE\s+CARD|PROMPT\s+OVERLAY|COLD\s+OPEN|PRODUCTION|'
    r'VERIFY|VISUAL|B-?ROLL)\b',
    re.IGNORECASE)


def _gi_is_host_label(p: str) -> bool:
    return bool(re.match(r'^\*{0,2}\s*Host\s*\*{0,2}\s*:?\s*\*{0,2}\s*$',
                         (p or "").strip(), re.IGNORECASE))


def _gi_is_spoken(p: str) -> bool:
    """A spoken beat line eligible for a prompt: not a label/metadata/stage line,
    not a separator, and long enough to be real dialogue."""
    s = (p or "").strip()
    if not s or _gi_is_host_label(s):
        return False
    if s.startswith("[") or s.startswith("==") or s.startswith("__"):
        return False
    if _GI_SKIP_LABEL_RE.match(s):
        return False
    # A leading "Host: " label doesn't disqualify the sentence after it.
    body = re.sub(r'^\*{0,2}\s*Host\s*\*{0,2}\s*:\s*\*{0,2}\s*', '', s,
                  flags=re.IGNORECASE)
    return len(body.split()) >= 12


def _gi_beat_text(p: str) -> str:
    """Strip a leading Host: label so the model sees only the spoken sentence."""
    return re.sub(r'^\*{0,2}\s*Host\s*\*{0,2}\s*:\s*\*{0,2}\s*', '',
                  (p or "").strip(), flags=re.IGNORECASE).strip()


def _grok_imagine_assets_for_beat(beat_text: str, section_title: str = "",
                                  video_title: str = "") -> tuple:
    """Return (image_prompt_with_suffix, quote_card_or_None) for a script beat.
    The image prompt is always present on success; the quote card only when the
    beat cites a quotable source. Returns ('', None) on failure so callers skip."""
    base = (beat_text or "").strip()
    if not base:
        return "", None
    parts = []
    if video_title:
        parts.append(f"VIDEO TITLE: {video_title}")
    if section_title:
        parts.append(f"SECTION: {section_title}")
    parts.append("SCRIPT BEAT (depict its meaning as symbolic objects; add a "
                 f"quote card only if it cites a quotable source): \"{base[:600]}\"")
    try:
        out = _anthropic_complete(
            GROK_IMAGINE_SYSTEM, "\n".join(parts), max_tokens=1000,
            use_web_search=False, timeout=60.0, model=GROK_IMAGINE_MODEL)
    except Exception as e:
        logger.warning(f"⚠️ Grok Imagine assets failed: {e}")
        return "", None
    raw = (out or "").strip()
    raw = re.sub(r'^```[a-zA-Z]*\n', '', raw)
    raw = re.sub(r'\n```\s*$', '', raw).strip()
    img, quote = "", None
    try:
        mobj = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(mobj.group(0) if mobj else raw)
        img = (data.get("image_prompt") or "").strip()
        q = data.get("quote_card")
        if q and str(q).strip().lower() not in ("null", "none", ""):
            quote = str(q).strip()
    except Exception:
        # JSON was malformed/truncated. Recover the field values by regex rather
        # than dumping the raw JSON text into the prompt.
        if '"image_prompt"' in raw:
            m_img = re.search(r'"image_prompt"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
            img = (m_img.group(1).encode().decode('unicode_escape')
                   if m_img else "")
            m_q = re.search(r'"quote_card"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
            if m_q:
                qv = m_q.group(1).encode().decode('unicode_escape').strip()
                if qv and qv.lower() not in ("null", "none"):
                    quote = qv
        else:
            img = raw.strip('"').strip()  # non-JSON reply: treat as the prompt
    img = img.strip().strip('"').strip()
    if not img:
        return "", None
    if not img.endswith((".", "!", "?")):
        img += "."
    return f"{img} {GROK_IMAGINE_STYLE_SUFFIX}", quote


def _new_grok_imagine_block(image_prompt: str, quote_card: str = None) -> str:
    """Format the copy-paste production block: a GROK IMAGINE line, plus a QUOTE
    CARD line when the beat cited a quotable source."""
    out = ["[PRODUCTION BEGIN]", f"[GROK IMAGINE / RESOLVE] {image_prompt}"]
    if quote_card:
        out.append(f"[QUOTE CARD / RESOLVE] {quote_card}")
    out.append("[PRODUCTION END]")
    return "\n".join(out)


def _gi_inject_hook(preamble_lines: list, video_title: str) -> tuple:
    """Add ONE Grok Imagine block for the hook at the top of the script, before
    the first chapter — unless the preamble already has a GROK IMAGINE block.
    Line-based insertion so the title/metadata block keeps its formatting.
    Returns (new_lines, added_count)."""
    text = "\n".join(preamble_lines)
    if _GROK_IMAGINE_TAG.lower() in text.lower():
        return list(preamble_lines), 0  # hook already illustrated — top-up: skip
    hook_idx = next((i for i, ln in enumerate(preamble_lines)
                     if _gi_is_spoken(ln)), None)
    if hook_idx is None:
        return list(preamble_lines), 0
    img, quote = _grok_imagine_assets_for_beat(
        _gi_beat_text(preamble_lines[hook_idx]), "Hook", video_title)
    if not img:
        return list(preamble_lines), 0
    block = _new_grok_imagine_block(img, quote).split("\n")
    new = (list(preamble_lines[:hook_idx]) + block + [""]
           + list(preamble_lines[hook_idx:]))
    return new, 1


def _gi_process_chapter(body: str, chap_title: str, video_title: str,
                        max_workers: int) -> tuple:
    """Inject 3-4 blocks into one chapter body, topping up to target. Returns
    (new_body, added_count, changed). ``changed`` is False when the caller should
    keep the original chapter lines verbatim (nothing to add)."""
    # Tokenize into ordered items; [PRODUCTION …] blocks stay whole. Spoken text
    # is one paragraph per line here (docx-extracted / processed scripts join
    # paragraphs with a single \n), so split host segments per line.
    items = []
    for kind, text in _split_by_production(body):
        if kind == "production":
            items.append(("prod", text.strip()))
            continue
        for para in text.split("\n"):
            p = para.strip()
            if p:
                items.append(("para", p))

    existing = sum(1 for k, t in items
                   if k == "prod" and _GROK_IMAGINE_TAG.lower() in t.lower())
    spoken_words = sum(len(t.split()) for k, t in items
                       if k == "para" and _gi_is_spoken(t))
    target = 4 if spoken_words >= 220 else 3
    needed = max(0, target - existing)
    if spoken_words == 0 or needed <= 0:
        return body, 0, False

    beat_idxs = []
    for i, (k, t) in enumerate(items):
        if len(beat_idxs) >= needed:
            break
        if k != "para" or not _gi_is_spoken(t):
            continue
        if i > 0 and items[i - 1][0] == "prod":
            continue
        beat_idxs.append(i)
    if not beat_idxs:
        return body, 0, False

    def _one(i):
        return i, _grok_imagine_assets_for_beat(
            _gi_beat_text(items[i][1]), chap_title, video_title)
    results = {}
    try:
        from concurrent.futures import ThreadPoolExecutor
        workers = max(1, min(max_workers, len(beat_idxs)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, pair in ex.map(_one, beat_idxs):
                results[i] = pair
    except Exception as e:
        logger.warning(f"⚠️ Grok Imagine batch failed ({e}); sequential")
        for i in beat_idxs:
            results[i] = _grok_imagine_assets_for_beat(
                _gi_beat_text(items[i][1]), chap_title, video_title)

    out_items, added = [], 0
    for i, (k, t) in enumerate(items):
        pair = results.get(i)
        if pair and pair[0]:
            out_items.append(("prod", _new_grok_imagine_block(pair[0], pair[1])))
            added += 1
        out_items.append((k, t))
    if not added:
        return body, 0, False
    return "\n\n".join(t for _, t in out_items), added, True


def _inject_grok_imagine_prompts(script: str, video_title: str = "",
                                 max_workers: int = 6) -> tuple:
    """Insert Grok Imagine blocks: one for the hook and 3-4 per chapter, topping
    up sections that already have some. A block also carries a QUOTE CARD line
    when its beat cites a quotable source. Trailing metadata sections are left
    untouched. Returns (updated_script, added_count). Never raises.
    """
    if not script or not script.strip():
        return script, 0

    # Inject only into the spoken body — never into trailing metadata sections.
    m = _GI_META_BOUNDARY_RE.search(script)
    main, tail = (script[:m.start()], script[m.start():]) if m else (script, "")

    lines = main.split("\n")
    boundaries = [i for i, ln in enumerate(lines) if _CH_BOUNDARY_RE.match(ln)]

    added_total = 0
    # Hook: the preamble before the first chapter (whole script if no chapters).
    pre_end = boundaries[0] if boundaries else len(lines)
    new_lines, n = _gi_inject_hook(lines[:pre_end], video_title)
    added_total += n
    if not boundaries:
        return "\n".join(new_lines) + tail, added_total

    for bi, start in enumerate(boundaries):
        end = boundaries[bi + 1] if bi + 1 < len(boundaries) else len(lines)
        heading = lines[start]
        body = "\n".join(lines[start + 1:end])
        chap_title = re.sub(
            r'^\s*(?:#{1,6}\s*)?\*{0,2}\s*Heading\s*:\s*', '', heading,
            flags=re.IGNORECASE).strip(" *#")
        new_body, added, changed = _gi_process_chapter(
            body, chap_title, video_title, max_workers)
        if not changed:
            new_lines.extend(lines[start:end])  # leave chapter exactly as-is
            continue
        added_total += added
        new_lines.append(heading)
        new_lines.append("")
        new_lines.extend(new_body.split("\n"))
        new_lines.append("")  # keep chapters visually separated

    return "\n".join(new_lines) + tail, added_total


def _call_polish_model(text_to_polish: str, header: str,
                       extra: str = "") -> tuple:
    """Run one Fable-5 (fallback Opus) polish pass over ``text_to_polish``.
    ``extra`` prepends run-specific instructions (e.g. the sentinel rule).
    Returns ``(polished_text, model_used)``; raises if no model responds.

    NO web search: the "make it current" web-search pass was the slow/flaky part
    (a full-script polish with search ran ~2-5 min and could stall). A no-search
    Fable pass is one bounded API call (~10-60s), fast and predictable.
    """
    user = (
        f"{header}{extra}Here is the finished script to polish and elevate. "
        f"Return the full polished script only:\n\n{text_to_polish}"
    )
    import anthropic
    for model in (POLISH_MODEL, ANTHROPIC_MODEL):
        try:
            logger.info("🪄 polish: calling %s (no web search)", model)
            out = _anthropic_complete(
                _POLISH_SYSTEM, user, max_tokens=16000,
                use_web_search=False, model=model, timeout=200.0,
            )
            out = _strip_reminder_tags(out)
            if out:
                return out, model
        except anthropic.NotFoundError:
            # Model isn't available on this key — try the next one.
            logger.warning("Polish model %s not available; falling back", model)
            continue
    raise RuntimeError("Script polish failed — no usable Claude model responded.")


def _polish_script(script: str, title: str = "", audience: str = "",
                   production_type: str = "") -> tuple:
    """Run the finished script through Fable 5 for a final polish pass.

    Only the Host narration OUTSIDE [PRODUCTION BEGIN]…[PRODUCTION END] blocks is
    ever rewritten: production blocks are extracted, the surrounding script is
    polished, then the blocks are restored byte-for-byte. Returns
    (polished_text, model_used). Falls back to ANTHROPIC_MODEL if POLISH_MODEL
    isn't available on the account.
    """
    ctx = []
    if title:
        ctx.append(f"SCRIPT TITLE: {title}")
    if audience:
        ctx.append(f"AUDIENCE: {audience}")
    if production_type:
        ctx.append(f"PRODUCTION TYPE: {production_type}")
    header = ("\n".join(ctx) + "\n\n") if ctx else ""

    masked, blocks = _mask_production_blocks(script)
    if not blocks:
        # No production blocks — polish the whole script as before.
        return _call_polish_model(script, header)

    logger.info("🪄 polish: shielding %d [PRODUCTION …] block(s) from the pass",
                len(blocks))
    sentinel_note = (
        "IMPORTANT — PRESERVE PLACEHOLDERS: The script contains placeholder "
        "tokens of the form [[PRODUCTION_BLOCK_N]] (e.g. [[PRODUCTION_BLOCK_0]]). "
        "Each stands in for a production-only section you must NOT alter. Leave "
        "every such token EXACTLY as written, on its own line, in the same order "
        "— do not modify, remove, reorder, translate, or add commentary around "
        "them. Polish ONLY the surrounding host narration.\n\n"
    )
    polished, model = _call_polish_model(masked, header, extra=sentinel_note)
    restored, missing = _restore_production_blocks(polished, blocks)
    if not missing:
        return restored, model

    # The model dropped/mangled a sentinel — fall back to the bulletproof path:
    # polish each host segment on its own and stitch the verbatim production
    # blocks back between them, so nothing inside the tags can be lost.
    logger.warning(
        "⚠️ polish: %d production sentinel(s) missing from output; "
        "using per-segment fallback", len(missing))
    out_parts = []
    model_used = model
    for kind, text in _split_by_production(script):
        if kind == "production" or not text.strip():
            out_parts.append(text)
        else:
            polished_seg, model_used = _call_polish_model(text, header)
            out_parts.append(polished_seg)
    return "".join(out_parts), model_used


@app.route("/api/script/polish", methods=["POST"])
def api_script_polish():
    """Final polish of the finished script via Claude Fable 5 (fallback Opus)."""
    data = request.get_json(silent=True) or {}
    script = (data.get("script") or "").strip()
    if not script:
        return jsonify({
            "success": False,
            "error": "No script to polish — create a script first.",
        }), 400
    title = (data.get("title") or "").strip()
    audience = (data.get("audience") or "").strip()
    production_type = (data.get("production_type") or "").strip()
    try:
        polished, model = _polish_script(
            script, title=title, audience=audience,
            production_type=production_type,
        )
    except Exception as e:
        logger.error(f"❌ Script polish failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    logger.info("✨ Script polished with %s (%d → %d chars)",
                model, len(script), len(polished))
    return jsonify({"success": True, "polished_script": polished, "model": model})


# ---------------------------------------------------------------------------
# Interactive refine — targeted, user-directed edits on a finished script.
#
# Unlike Polish (a blanket rewrite pass), Refine applies ONE specific change the
# user types in ("swap the ChatGPT example for a newer one", "add a 2026 example
# from X about AI agents", "tighten chapter 3's intro"), using either Claude
# (careful edits, web search on for currency) or Grok (recent / X-aware), and
# returns the FULL updated script. Production blocks are shielded the same way
# Polish shields them.
# ---------------------------------------------------------------------------
_REFINE_SYSTEM = (
    "You are a precise script editor for a single-host narrated video. You are "
    "given a COMPLETE, already-written script and ONE specific change request. "
    "Apply ONLY that change. Preserve everything else EXACTLY — the overall "
    "structure, chapter order and headings, every host line the request does "
    "not touch, the formatting and blank lines, and any production markup or "
    "placeholder tokens. Do NOT re-polish, re-order, summarize, shorten, lengthen, "
    "or add commentary beyond what the request asks. Keep the same voice and "
    "approximate length. If the request asks for a newer / more current example, "
    "replace the named item with a REAL, current one and keep the surrounding "
    "sentence shape. Return the FULL updated script ONLY — no preamble, no "
    "explanation, no code fences."
)


def _refine_script(script: str, instructions: str, model: str = "claude",
                   title: str = "", audience: str = "") -> tuple:
    """Apply a single user-directed change to a finished script.

    Returns (updated_text, model_used). `model` is "claude" (Opus 4.8, web
    search on) or "grok" (xAI, X/recent-aware). Production blocks are masked and
    restored byte-for-byte; if the model drops a placeholder, we retry once on
    the raw script asking it to keep the blocks verbatim (a per-segment fallback
    like Polish's would wrongly apply a single targeted edit to every segment).
    """
    ctx = []
    if title:
        ctx.append(f"SCRIPT TITLE: {title}")
    if audience:
        ctx.append(f"AUDIENCE: {audience}")
    header = ("\n".join(ctx) + "\n\n") if ctx else ""

    use_grok = (model or "").lower().startswith("grok")

    def _call(text: str, extra: str = "") -> tuple:
        user = (
            f"{header}CHANGE REQUEST:\n{instructions}\n\n{extra}"
            f"Here is the full script. Apply ONLY the change request above and "
            f"return the complete, updated script:\n\n{text}"
        )
        if use_grok:
            out = _grok_complete(_REFINE_SYSTEM, user, model=IDEA_GROK_MODEL)
            return _strip_reminder_tags(out or ""), IDEA_GROK_MODEL
        # Claude Opus 5.5 at MAX reasoning effort for the sharpest edits (user
        # request — not Opus 4.8, not medium effort).
        out = _anthropic_complete(
            _REFINE_SYSTEM, user, max_tokens=16000,
            use_web_search=True, model=REFINE_MODEL, timeout=240.0,
            effort="max", thinking=True,
        )
        return _strip_reminder_tags(out or ""), REFINE_MODEL

    masked, blocks = _mask_production_blocks(script)
    if not blocks:
        out, used = _call(script)
        if not out:
            raise RuntimeError("Refine returned an empty script.")
        return out, used

    sentinel_note = (
        "IMPORTANT — PRESERVE PLACEHOLDERS: the script contains tokens of the "
        "form [[PRODUCTION_BLOCK_N]]. Leave every such token EXACTLY as written, "
        "on its own line, in the same order. Edit ONLY the surrounding host "
        "narration.\n\n"
    )
    out, used = _call(masked, extra=sentinel_note)
    if not out:
        raise RuntimeError("Refine returned an empty script.")
    restored, missing = _restore_production_blocks(out, blocks)
    if not missing:
        return restored, used

    logger.warning("⚠️ refine: %d production sentinel(s) missing from output; "
                   "retrying unmasked", len(missing))
    keep_note = (
        "IMPORTANT: Keep every [PRODUCTION BEGIN]…[PRODUCTION END] block and its "
        "contents EXACTLY as written, unchanged and in place. Edit ONLY the host "
        "narration.\n\n"
    )
    out2, used2 = _call(script, extra=keep_note)
    if out2:
        return out2, used2
    return restored, used  # best effort — return what we could restore


@app.route("/api/script/refine", methods=["POST"])
def api_script_refine():
    """Apply one user-directed change to the finished script via Claude or Grok."""
    data = request.get_json(silent=True) or {}
    script = (data.get("script") or "").strip()
    instructions = (data.get("instructions") or "").strip()
    model = (data.get("model") or "claude").strip().lower()
    if not script:
        return jsonify({
            "success": False,
            "error": "No script to refine — create a script first.",
        }), 400
    if not instructions:
        return jsonify({
            "success": False,
            "error": "Describe the change you want (e.g. 'swap the ChatGPT "
                     "example for a newer one').",
        }), 400
    title = (data.get("title") or "").strip()
    audience = (data.get("audience") or "").strip()
    try:
        updated, used = _refine_script(
            script, instructions, model=model, title=title, audience=audience)
    except Exception as e:
        logger.error(f"❌ Script refine failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    logger.info("✏️ Script refined with %s (%d → %d chars) | ask: %s",
                used, len(script), len(updated), instructions[:80])
    return jsonify({"success": True, "updated_script": updated, "model": used})


@app.route("/api/x/generate", methods=["POST"])
def api_x_generate():
    """Draft an X post with Claude for an episode promo or a standalone post."""
    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "random").strip()
    title = (data.get("title") or "").strip()
    youtube_url = (data.get("youtube_url") or "").strip()
    topic = (data.get("topic") or "").strip()
    if mode != "episode" and not topic and not title:
        return jsonify({
            "success": False,
            "error": "Enter what you'd like to post about.",
        }), 400
    try:
        text = _generate_x_post(mode, title=title, youtube_url=youtube_url,
                                topic=topic)
    except Exception as e:
        logger.error(f"❌ X post generation failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    return jsonify({"success": True, "text": text})


@app.route("/api/x/post", methods=["POST"])
def api_x_post():
    """Post the given text to X as @AIwithRoz."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"success": False, "error": "Post text is empty."}), 400
    try:
        client = _x_client()
        resp = client.create_tweet(text=text)
        tweet_id = resp.data["id"]
        url = f"https://x.com/{X_ACCOUNT_HANDLE}/status/{tweet_id}"
        logger.info(f"✅ Posted to X (@{X_ACCOUNT_HANDLE}): {url}")
        return jsonify({"success": True, "tweet_id": tweet_id, "url": url})
    except Exception as e:
        logger.error(f"❌ X post failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# LinkedIn posting — promote published YouTube episodes + standalone posts.
#
# Posts from the @AIwithRoz LinkedIn profile using an OAuth 2.0 member access
# token (LINKEDIN_ACCESS_TOKEN) with the w_member_social scope. The author URN
# is read from LINKEDIN_AUTHOR_URN, or auto-resolved from the token via
# /v2/userinfo. Post text is drafted by Claude Opus 4.8 (reuses
# _anthropic_complete). No extra SDK — posts via the LinkedIn REST API with
# `requests`. Degrades gracefully when the token is absent.
# ---------------------------------------------------------------------------
LINKEDIN_ACCOUNT_HANDLE = "AIwithRoz"
_LINKEDIN_AUTHOR_CACHE = {}


def _linkedin_token():
    return (os.getenv("LINKEDIN_ACCESS_TOKEN") or "").strip()


def _linkedin_api_version():
    return (os.getenv("LINKEDIN_API_VERSION") or "").strip() or "202607"


def _linkedin_resolve_author(token: str):
    """Return the author URN for the token: env override, cache, or /v2/userinfo."""
    env_urn = (os.getenv("LINKEDIN_AUTHOR_URN") or "").strip()
    if env_urn:
        return env_urn
    if token in _LINKEDIN_AUTHOR_CACHE:
        return _LINKEDIN_AUTHOR_CACHE[token]
    try:
        import requests as _rq
        r = _rq.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"}, timeout=15,
        )
        if r.status_code == 200:
            sub = (r.json() or {}).get("sub")
            if sub:
                urn = f"urn:li:person:{sub}"
                _LINKEDIN_AUTHOR_CACHE[token] = urn
                return urn
        logger.info("LinkedIn userinfo %s: %s", r.status_code, r.text[:180])
    except Exception as e:
        logger.info("LinkedIn author resolve failed: %s", e)
    return None


def _linkedin_configured() -> bool:
    return bool(_linkedin_token())


def _generate_linkedin_post(mode: str, title: str = "", youtube_url: str = "",
                            topic: str = "") -> str:
    """Draft a LinkedIn post with Claude. mode: 'episode' | 'random'.

    LinkedIn favors a strong first line, short skimmable paragraphs, and a
    couple of hashtags. The YouTube link is appended after generation (LinkedIn
    renders a preview card from it). No hard char cap like X, but we keep it
    tight (~1300 chars) so it doesn't get truncated behind "…see more".
    """
    link = (youtube_url or "").strip()
    if mode == "episode":
        ctx = f'New YouTube video title: "{title}".'
        if topic:
            ctx += f"\nExtra context: {topic}"
        instruction = (
            "Write an engaging LinkedIn post promoting this brand-new YouTube "
            "video from the @AIwithRoz channel (practical AI for everyday life "
            "and careers). Open with a scroll-stopping first line, use short "
            "skimmable paragraphs with line breaks, share the value/takeaway, "
            "end with a clear call to watch, and add 3-5 relevant hashtags. "
            "Do NOT paste the video link — it is appended automatically."
        )
    else:
        ctx = f"Topic / what to post about: {topic or title}"
        instruction = (
            "Write an engaging standalone LinkedIn post for the @AIwithRoz "
            "channel (practical AI for everyday life and careers) about the "
            "topic below. Strong first line, short skimmable paragraphs, a "
            "takeaway, and 3-5 relevant hashtags."
            + (" You may reference the linked video; the link is appended "
               "automatically." if link else "")
        )
    system = (
        "You are the social media manager for the @AIwithRoz brand on LinkedIn. "
        "You write professional-but-human, value-first posts that earn saves and "
        "shares. Output ONLY the post text — no surrounding quotes, no preamble, "
        "no markdown headings."
    )
    user = f"{instruction}\n\n{ctx}\n\nKeep it under ~1300 characters."
    text = _anthropic_complete(system, user, max_tokens=700,
                               use_web_search=False).strip()
    if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
        text = text[1:-1].strip()
    if link:
        text = f"{text}\n\n{link}"
    return text


@app.route("/api/linkedin/status", methods=["GET"])
def api_linkedin_status():
    """Report whether @AIwithRoz LinkedIn posting is configured (token present)."""
    return jsonify({
        "success": True,
        "configured": _linkedin_configured(),
        "account": LINKEDIN_ACCOUNT_HANDLE,
    })


@app.route("/api/linkedin/generate", methods=["POST"])
def api_linkedin_generate():
    """Draft a LinkedIn post with Claude for an episode promo or standalone post."""
    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "random").strip()
    title = (data.get("title") or "").strip()
    youtube_url = (data.get("youtube_url") or "").strip()
    topic = (data.get("topic") or "").strip()
    if mode != "episode" and not topic and not title:
        return jsonify({
            "success": False,
            "error": "Enter what you'd like to post about.",
        }), 400
    try:
        text = _generate_linkedin_post(mode, title=title,
                                       youtube_url=youtube_url, topic=topic)
    except Exception as e:
        logger.error(f"❌ LinkedIn post generation failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    return jsonify({"success": True, "text": text})


@app.route("/api/linkedin/post", methods=["POST"])
def api_linkedin_post():
    """Post the given text to LinkedIn as @AIwithRoz."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"success": False, "error": "Post text is empty."}), 400

    token = _linkedin_token()
    if not token:
        return jsonify({
            "success": False,
            "error": ("LinkedIn is not configured. Set LINKEDIN_ACCESS_TOKEN "
                      "in the root .env (scope: w_member_social)."),
        }), 500
    author = _linkedin_resolve_author(token)
    if not author:
        return jsonify({
            "success": False,
            "error": ("Could not determine the LinkedIn author. Set "
                      "LINKEDIN_AUTHOR_URN in .env, or ensure the token has the "
                      "'openid profile' scopes so it can be auto-resolved."),
        }), 500

    try:
        import requests as _rq
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": _linkedin_api_version(),
        }
        body = {
            "author": author,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        r = _rq.post("https://api.linkedin.com/rest/posts",
                     headers=headers, json=body, timeout=30)
        if r.status_code in (200, 201):
            post_id = (r.headers.get("x-restli-id")
                       or r.headers.get("x-linkedin-id") or "")
            url = (f"https://www.linkedin.com/feed/update/{post_id}"
                   if post_id else "https://www.linkedin.com/feed/")
            logger.info(f"✅ Posted to LinkedIn (@{LINKEDIN_ACCOUNT_HANDLE}): {url}")
            return jsonify({"success": True, "post_id": post_id, "url": url})
        logger.error(f"❌ LinkedIn API {r.status_code}: {r.text[:300]}")
        return jsonify({
            "success": False,
            "error": f"LinkedIn API {r.status_code}: {r.text[:200]}",
        }), 502
    except Exception as e:
        logger.error(f"❌ LinkedIn post failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/test")
def test_page():
    """Serve the test page for debugging SSE streaming"""
    return render_template("test.html")


@app.route("/test-capture")
def test_capture_page():
    """Test page to debug console capture and threading issues"""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Console Capture Test</title></head>
    <body>
        <h1>Console Capture Test Harness</h1>
        <button onclick="runTest()">Run Console Capture Test</button>
        <div id="progress"></div>
        <div id="result"></div>
        <script>
        function runTest() {
            fetch('/test-capture-process', {method: 'POST'})
            .then(r => r.json())
            .then(data => {
                document.getElementById('progress').innerHTML = 'Test started...';
                watchProgress(data.session_id);
            });
                resp = make_response(render_template(
                    "index.html",
                    version=VERSION,
                    agent_mode=(os.environ.get("FOUNDRY_API_MODE") or "v2").lower(),
                    saved_grok_api_key=_resolve("grok_api_key", "XAI_API_KEY"),
                    saved_heygen_api_key=_resolve("heygen_api_key", "HEYGEN_API_KEY"),
                    saved_heygen_voice_id=_resolve("heygen_voice_id", "HEYGEN_VOICE_ID"),
                    saved_google_api_key=_resolve("google_api_key", "GOOGLE_API_KEY"),
                ))
                resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                resp.headers['Pragma'] = 'no-cache'
                resp.headers['Expires'] = '0'
                return resp
        }
                    document.getElementById('result').innerHTML = 'Test completed!';
                }
            };
        }
        </script>
    </body>
    </html>
    """


@app.route('/test-capture-process', methods=['POST'])
def test_capture_process():
    """Test the console capture mechanism without full workflow"""
    session_id = str(uuid.uuid4())
    progress_streams[session_id] = ProgressStreamer(session_id)

    # Start the test in background
    thread = threading.Thread(
        target=run_test_capture,
        args=(session_id,),
        daemon=True
    )
    thread.start()
    running_tasks[session_id] = thread

    return jsonify({'session_id': session_id, 'status': 'started'})


def run_test_capture(session_id):
    """Test console capture and the exact point where it hangs"""
    import time
    import sys

    logger.info(f"🧪 TEST CAPTURE STARTED: session={session_id}")

    try:
        if session_id not in progress_streams:
            logger.error(f"❌ Session {session_id} not found!")
            return

        streamer = progress_streams[session_id]

        # Set up console capture exactly like the real workflow
        console_capture = ConsoleCapture(streamer)
        original_stdout = sys.stdout

        try:
            # Redirect stdout to capture console output
            sys.stdout = console_capture

            # Test 1: Basic console output
            print("🧪 TEST 1: Basic console output")
            streamer.send_update("🧪 Basic console output test", 10)
            time.sleep(1)

            # Test 2: Import text processing (where it hangs)
            print("🧪 TEST 2: Importing text processing modules")
            streamer.send_update("🧪 Testing text processing import", 20)

            try:
                from console_ui.text_processing import (
                    enhance_script_with_bold_tools,
                    extract_tool_links_and_info,
                )
                print("✅ Text processing modules imported successfully")
                streamer.send_update("✅ Text processing import success", 30)
            except Exception as e:
                print(f"❌ Text processing import failed: {e}")
                streamer.send_update(
                    f"❌ Text processing import failed: {e}", 30)
                raise

            # Test 3: Call enhance_script_with_bold_tools (where it might hang)
            print("🧪 TEST 3: Testing enhance_script_with_bold_tools")
            streamer.send_update("🧪 Testing script enhancement", 40)

            test_script = "This is a test script with **bold** and [ChatGPT](https://chatgpt.com)."

            try:
                enhanced_script = enhance_script_with_bold_tools(test_script)
                print(f"✅ Script enhanced: {len(enhanced_script)} chars")
                streamer.send_update("✅ Script enhancement success", 50)
            except Exception as e:
                print(f"❌ Script enhancement failed: {e}")
                streamer.send_update(f"❌ Script enhancement failed: {e}", 50)
                raise

            # Test 4: Call extract_tool_links_and_info
            print("🧪 TEST 4: Testing extract_tool_links_and_info")
            streamer.send_update("🧪 Testing tool link extraction", 60)

            try:
                tool_links = extract_tool_links_and_info(enhanced_script)
                print(f"✅ Tool links extracted: {len(tool_links)} chars")
                streamer.send_update("✅ Tool link extraction success", 70)
            except Exception as e:
                print(f"❌ Tool link extraction failed: {e}")
                streamer.send_update(f"❌ Tool link extraction failed: {e}", 70)
                raise

            # Test 5: Minimal rapid output test to isolate deadlock
            print("🧪 TEST 5: Minimal rapid output test")
            streamer.send_update("🧪 Starting minimal rapid test", 80)

            # Test just 3 rapid outputs with debugging
            for i in range(3):
                print(f"   📝 Before output {i+1}")
                streamer.send_update(f"🧪 Processing output {i+1}/3", 85 + i*2)
                print(f"   📝 After output {i+1}")
                time.sleep(0.5)  # Longer sleep to prevent issues

            print("✅ Minimal rapid test completed")
            logger.info(
                "🔍 DEBUG: About to send minimal rapid test success update")
            streamer.send_update("✅ Minimal rapid test success", 90)
            logger.info("🔍 DEBUG: Minimal rapid test success update sent")

            # Final test
            print("🧪 ALL TESTS COMPLETED SUCCESSFULLY!")
            logger.info("🔍 DEBUG: About to send all tests completed update")
            streamer.send_update("🧪 All tests completed!", 100)
            logger.info("🔍 DEBUG: All tests completed update sent")

            # Store success result
            logger.info("🔍 DEBUG: About to set streamer.result")
            streamer.result = {
                "success": True,
                "message": "All console capture tests passed",
                "enhanced_script": enhanced_script,
                "tool_links": tool_links
            }
            logger.info("🔍 DEBUG: streamer.result set successfully")

        finally:
            # Always restore stdout
            logger.info("🔍 DEBUG: Entering finally block")
            sys.stdout = original_stdout
            logger.info("🔍 DEBUG: stdout restored, function should exit now")

    except Exception as e:
        error_msg = f"Test failed: {str(e)}"
        logger.error(f"💥 Test exception: {error_msg}")
        if session_id in progress_streams:
            streamer = progress_streams[session_id]
            streamer.send_update(f"❌ {error_msg}", -1)
            streamer.result = {"success": False, "error": error_msg}


@app.route("/test_progress/<session_id>/<int:progress>/<message>")
def test_progress(session_id, progress, message):
    """Test endpoint to manually send progress updates"""
    if session_id in progress_streams:
        streamer = progress_streams[session_id]
        streamer.send_update(message, progress)
        logger.info(f"🧪 Test progress sent: {message} -> {progress}%")
        return jsonify({
            "success": True,
            "message": f"Sent: {message} -> {progress}%"
        })
    return jsonify({
        "success": False,
        "error": "Session not found"
    }), 404


@app.route("/test_create")
def test_create():
    """Create a test session with hardcoded progress messages"""
    import uuid
    import time
    import threading

    # Generate session ID
    session_id = str(uuid.uuid4())

    # Create progress streamer
    progress_streams[session_id] = ProgressStreamer(session_id)

    logger.info(f"🧪 Starting test session: {session_id}")

    def send_test_messages():
        streamer = progress_streams[session_id]
        time.sleep(1)

        # Send a series of test messages
        test_messages = [
            (10, "🚀 Starting test..."),
            (25, "📝 Writing Chapter 1/7: Test Chapter"),
            (40, "✅ Chapter 1 completed (1234 chars)"),
            (55, "📝 Writing Chapter 2/7: Another Test Chapter"),
            (70, "✅ Chapter 2 completed (2345 chars)"),
            (85, "🔍 Reviewing content..."),
            (100, "✅ Test completed successfully!")
        ]

        for progress, message in test_messages:
            streamer.send_update(message, progress)
            logger.info(f"🧪 Sent: {message} -> {progress}%")
            time.sleep(2)  # 2 second delay between messages

    # Start test in background
    thread = threading.Thread(target=send_test_messages, daemon=True)
    running_tasks[session_id] = thread
    thread.start()

    return jsonify({
        "success": True,
        "session_id": session_id,
        "message": "Test session started",
        "test_url": f"/progress/{session_id}"
    })


@app.route("/debug/stdout")
def debug_stdout():
    """Debug endpoint to check stdout status"""
    return jsonify({
        "stdout_type": str(type(sys.stdout)),
        "is_console_capture": isinstance(sys.stdout, ConsoleCapture),
        "active_sessions": len(progress_streams),
        "running_tasks": len(running_tasks)
    })


@app.route("/create", methods=["POST"])
def create():
    """Create a new script with progress streaming"""
    # Get form data
    data = request.get_json() or {}
    topic = data.get("topic", "AI in daily life")
    # The creative brief from the Create Script dialog. This is the single most
    # important steering input the workflow gets — without it the Topic
    # Assistant and Script Writer fall back to "use the topic title as a guide"
    # and invent an episode from the title alone.
    description = (data.get("description") or "").strip()
    # If this run came from an Idea-Generator batch that was grounded in an
    # uploaded document, append a trimmed excerpt of that document to the brief.
    # The description is the one channel that reaches BOTH the Topic Assistant
    # and the Script Writer, so this puts the source material in front of both.
    src_batch = _find_idea_batch(data.get("source_batch_id"))
    src_doc = (src_batch or {}).get("source_document") or {}
    src_doc_text = (src_doc.get("text") or "").strip()
    if src_doc_text:
        excerpt = src_doc_text[:_IDEA_DOC_EXCERPT_CHARS]
        truncated = len(src_doc_text) > _IDEA_DOC_EXCERPT_CHARS
        src_name = (src_doc.get("name") or "attachment")
        doc_block = (
            f"\n\n--- SOURCE DOCUMENT: {src_name} "
            f"(ground the script in this; do not contradict it) ---\n"
            f"{excerpt}"
            + ("\n…[excerpt truncated]…" if truncated else "")
            + "\n--- END SOURCE DOCUMENT ---\n"
        )
        description = (description + doc_block) if description else doc_block.strip()
        logger.info("📎 Injected source document '%s' (%d chars) into the brief "
                    "for the Topic Assistant + Script Writer",
                    src_name, len(excerpt))
    audience = data.get("audience", "general")
    tone = data.get("tone", "professional")
    # The Create Script modal sends the duration dropdown as `duration`
    # ("5"/"10"/"15"), NOT `video_length`. Honor it: prefer an explicit
    # video_length, else convert the numeric duration to an "N minutes" string.
    # Without this, video_length was always the "medium" default and the
    # workflow fell back to ~8 minutes regardless of the dropdown.
    video_length = data.get("video_length")
    if not video_length:
        _dur = str(data.get("duration", "")).strip()
        video_length = f"{_dur} minutes" if _dur.isdigit() else (_dur or "medium")
    production_type = data.get("production_type", "standard")
    goals = data.get("goals", "educational")
    test_mode = data.get("test_mode", False)  # Quick test mode flag
    quick_test = data.get("quick_test", False)  # 1-chapter quick test
    # Video archetype / format — selects the topic-assistant + writer agent pair:
    #   teaching (default) = "5 things" tutorial listicle
    #   predictions        = bold / visionary, 1 prediction per chapter
    #   list               = Top-N ranked countdown (honors N, lists all)
    video_format = (data.get("video_format") or "teaching").strip().lower()

    # NEW: Get checkbox selections
    checkboxes = data.get("checkboxes", {})

    # Get HeyGen parameters
    heygen_template_id = data.get("heygen_template_id", "")
    heygen_api_key = data.get("heygen_api_key", "")
    heygen_voice_id = data.get("heygen_voice_id", "")
    grok_api_key = data.get("grok_api_key", "")

    # If "All" is checked, enable everything
    if checkboxes.get("all", False):
        checkboxes = {
            "script": True,
            "hook_summary": True,
            "youtube_details": True,
            "heygen": True,
            "curl": True,
            "broll": True,
            "broll_images": True,
            "thumbnails": True,
            "demo": True,
            "flow_analysis": True,
            "all": True
        }
    # If no checkboxes provided, default to script only
    elif not checkboxes:
        checkboxes = {"script": True}

    # Generate session ID
    session_id = str(uuid.uuid4())

    # Create progress streamer
    progress_streams[session_id] = ProgressStreamer(session_id)

    logger.info(f"🎬 Starting script creation: {session_id}")
    logger.info(f"📝 Topic: {topic}, Audience: {audience}, Tone: {tone}")
    logger.info(f"🎬 Video format: {video_format!r} | length: {video_length!r}")
    if description:
        logger.info(f"📋 Brief: {len(description)} chars — steering the "
                    f"Topic Assistant and Script Writer")
    else:
        logger.warning("⚠️ NO BRIEF SUPPLIED — the workflow will invent an "
                       "episode from the topic title alone")
    logger.info(f"📋 Checkboxes: {checkboxes}")
    if quick_test:
        logger.info(f"⚡ QUICK TEST MODE: 1 chapter only")

    # Start script creation in background thread
    def run_script_creation():
        try:
            if test_mode:
                # Quick test mode - simulate progress and complete in 10 seconds
                logger.info(f"⚡ Running in test mode for session {session_id}")
                _run_cancellable_workflow(
                    session_id,
                    lambda: test_mode_simulation(session_id),
                )
            else:
                # Override video_length for quick test
                actual_length = "1 minute (150-200 words)" if quick_test else video_length
                _run_cancellable_workflow(
                    session_id,
                    lambda: process_script_creation(
                        session_id, topic, audience, tone, actual_length,
                        production_type, goals, quick_test, checkboxes,
                        heygen_template_id, heygen_api_key,
                        heygen_voice_id, grok_api_key,
                        description=description,
                        script_format=video_format,
                    ),
                )
        except Exception as e:
            logger.error(f"❌ Script creation error: {e}")
            if session_id in progress_streams:
                progress_streams[session_id].send_update(
                    f"❌ Error: {str(e)}", 100
                )

    thread = threading.Thread(target=run_script_creation, daemon=True)
    running_tasks[session_id] = thread
    thread.start()

    return jsonify({
        "success": True,
        "session_id": session_id,
        "message": "Script creation started"
    })


@app.route("/progress/<session_id>")
def progress_stream(session_id):
    """Server-Sent Events endpoint for progress updates"""
    logger.info(f"🌊 SSE connection established for session {session_id}")

    if session_id not in progress_streams:
        return "Session not found", 404

    streamer = progress_streams[session_id]

    def generate():
        try:
            while True:  # Changed from while not streamer.done
                try:
                    # Get update with timeout
                    update = streamer.queue.get(timeout=30)
                    logger.info(f"🔄 SSE sending: {update}")

                    # Parse the update to check if it's the completion message
                    update_data = json.loads(update)

                    # If this is the completion message (progress=100), add the script content
                    if update_data.get("done", False) or update_data.get("progress") == 100:
                        logger.info(
                            f"🎯 Processing completion message for session {session_id}")

                        # Create a completion message with status and script
                        if streamer.result and streamer.result.get("success"):
                            # Prepare thumbnail data for frontend
                            thumbnail_results = streamer.result.get(
                                "thumbnail_results", {})

                            print("\n" + "="*70)
                            print("📦 PREPARING COMPLETION MESSAGE")
                            print("="*70)
                            print(f"Session: {session_id}")
                            print(
                                f"Thumbnail results type: {type(thumbnail_results)}")
                            print(
                                f"Thumbnail results is None: {thumbnail_results is None}")

                            thumbnails = _collect_all_thumbnail_entries(
                                streamer.result.get(
                                    "script_title", "Untitled Script"),
                                thumbnail_results,
                            )

                            if thumbnail_results and thumbnail_results.get("variations"):
                                print(f"✅ Found variations in thumbnail_results")
                                print(
                                    f"   Generated this run: {len(thumbnail_results.get('variations') or [])}")
                            elif thumbnail_results:
                                print(
                                    f"⚠️ No variations found in thumbnail_results")
                                print(
                                    f"   Available keys: {list(thumbnail_results.keys())}")

                            print(
                                f"\n✅ Prepared {len(thumbnails)} thumbnail objects for frontend (directory-wide)")

                            print("="*70 + "\n")

                            # DEBUG: Check chapter_comparisons data
                            chapter_comps = streamer.result.get(
                                "chapter_comparisons")
                            print(
                                f"🔍 DEBUG: chapter_comparisons type: {type(chapter_comps)}")
                            if chapter_comps:
                                print(
                                    f"🔍 DEBUG: chapter_comparisons length: {len(chapter_comps)}")
                                print(
                                    f"🔍 DEBUG: First comparison keys: {list(chapter_comps[0].keys()) if len(chapter_comps) > 0 else 'N/A'}")
                            else:
                                print(
                                    f"🔍 DEBUG: chapter_comparisons is None or empty")

                            completion_msg = {
                                "status": "complete",
                                "message": update_data.get("message", "✅ Script creation complete!"),
                                "script": streamer.result.get("enhanced_script", ""),
                                "script_title": streamer.result.get("script_title", "Untitled Script"),
                                "script_id": streamer.result.get("script_id"),
                                "script_version": streamer.result.get("script_version"),
                                "demo_packages": streamer.result.get("demo_packages"),
                                "word_count": streamer.result.get("word_count", 0),
                                "reading_time": streamer.result.get("reading_time", "N/A"),
                                "thumbnails": thumbnails,
                                "thumbnail_results": thumbnail_results,
                                "comparison_file": streamer.result.get("comparison_file"),
                                "chapter_comparisons": streamer.result.get("chapter_comparisons"),
                                "flow_original_script": streamer.result.get("flow_original_script"),
                                "flow_improved_script": streamer.result.get("flow_improved_script"),
                                "flow_analysis_report": streamer.result.get("flow_analysis_report"),
                                "edl_content": streamer.result.get("edl_content"),
                                "edl_filename": streamer.result.get("edl_filename"),
                                "curl_commands": streamer.result.get("curl_commands"),
                                "markdown_path": streamer.result.get("markdown_path"),
                                "docx_path": streamer.result.get("docx_path"),
                                "broll_images": streamer.result.get("broll_images"),
                                "grok_videos": streamer.result.get("grok_videos"),
                                "broll_table": streamer.result.get("broll_table"),
                                "broll_rows": streamer.result.get("broll_rows"),
                                "youtube_details": streamer.result.get("youtube_details"),
                                "awaiting_hook_selection": streamer.result.get("awaiting_hook_selection", False),
                                "hooks": streamer.result.get("hooks", []),
                                "hook_labels": streamer.result.get("hook_labels", []),
                                "original_script": streamer.result.get("original_script", ""),
                            }

                            print("\n" + "="*70)
                            print("📤 SENDING COMPLETION MESSAGE TO FRONTEND")
                            print("="*70)
                            print(f"Status: {completion_msg['status']}")
                            print(
                                f"Script length: {len(completion_msg['script'])} chars")
                            print(
                                f"Thumbnails array length: {len(completion_msg['thumbnails'])}")
                            if completion_msg['thumbnails']:
                                print("\nThumbnails being sent:")
                                for i, t in enumerate(completion_msg['thumbnails'], 1):
                                    print(
                                        f"   #{i}: {t['emotion']} - {t['filename']}")
                            else:
                                print("⚠️ No thumbnails in completion message!")

                            # Debug B-roll images
                            broll_imgs = completion_msg.get('broll_images')
                            if broll_imgs:
                                print(
                                    f"\n🎨 B-roll images being sent: {len(broll_imgs)} images")
                                for i, img in enumerate(broll_imgs, 1):
                                    print(
                                        f"   #{i}: {img.get('search_term')} - {img.get('filename')}")
                            else:
                                print(
                                    "\n⚠️ No B-roll images in completion message!")

                            print("="*70 + "\n")

                            logger.info(
                                f"✅ Sending completion with script ({len(completion_msg.get('script', ''))} chars) and {len(thumbnails)} thumbnails")
                        else:
                            # Error case
                            error_msg = streamer.result.get(
                                "error", "Unknown error") if streamer.result else "No result available"
                            completion_msg = {
                                "status": "error",
                                "error": error_msg
                            }
                            logger.error(
                                f"❌ Sending error completion: {error_msg}")

                        yield f"data: {json.dumps(completion_msg)}\n\n"
                        logger.info(
                            f"🎯 SSE completion message sent for session {session_id}")
                        break
                    else:
                        # Regular progress update
                        progress_msg = {
                            "status": "progress",
                            "message": update_data.get("message", "Processing..."),
                            "progress": update_data.get("progress", 0)
                        }
                        yield f"data: {json.dumps(progress_msg)}\n\n"

                except queue.Empty:
                    # Only check done status if queue is empty
                    if streamer.done:
                        logger.info(
                            f"🏁 SSE ending - streamer marked done for session {session_id}")
                        break
                    # Send keepalive
                    logger.debug(f"💓 SSE keepalive for session {session_id}")
                    yield f"data: {json.dumps({'status': 'keepalive'})}\n\n"
                    continue

        except Exception as e:
            # Suppress "Broken pipe" errors - these happen when client disconnects
            import errno
            if isinstance(e, (BrokenPipeError, IOError)) and getattr(e, 'errno', None) == errno.EPIPE:
                logger.debug(
                    f"🔌 Client disconnected (broken pipe) for session {session_id}")
            else:
                logger.error(f"SSE error for session {session_id}: {e}")
                yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
        finally:
            logger.info(f"🔚 SSE stream ended for session {session_id}")

    response = Response(generate(), mimetype="text/event-stream")
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'  # Disable nginx buffering
    return response


@app.route("/result/<session_id>")
def get_result(session_id):
    """Get final result"""
    logger.info(f"🔍 Result requested for session {session_id}")

    if session_id in progress_streams:
        streamer = progress_streams[session_id]
        logger.info(
            f"📊 Session {session_id} found. Result available: {bool(streamer.result)}")
        logger.info(f"📊 Session {session_id} done status: {streamer.done}")

        if streamer.result:
            logger.info(f"✅ Result found for session {session_id}")
            result_size = len(str(streamer.result)) if streamer.result else 0
            logger.info(f"📏 Result size: {result_size} chars")
            return jsonify(streamer.result)
        else:
            logger.warning(
                f"⚠️ No result available yet for session {session_id}")
            return jsonify({"error": "Result not ready yet, please try again"}), 202
    else:
        logger.error(f"❌ Session {session_id} not found in progress_streams")
        logger.info(f"📋 Available sessions: {list(progress_streams.keys())}")

    return jsonify({"error": "Result not available"}), 404


@app.route("/process-script", methods=["POST"])
def process_script():
    """Process existing script to generate YouTube details, B-roll, HeyGen, etc."""
    logger.info("=== PROCESS SCRIPT REQUEST RECEIVED ===")

    try:
        data = request.json
        script_content = data.get("script", "")
        # Note: topic field is only used for script CREATION, not processing
        audience = data.get("audience", "general audience")
        video_length = data.get("videoLength", "5-8 minutes")
        tone = data.get("tone", "informative")
        checkboxes = data.get("checkboxes", {})
        heygen_template_id = data.get("heygen_template_id", "")
        heygen_api_key = data.get("heygen_api_key", "")
        heygen_voice_id = data.get("heygen_voice_id", "")
        grok_api_key = data.get("grok_api_key", "")
        # Optional pre-loaded artifacts that let the workflow skip the
        # corresponding agents (Feature: Load existing YouTube details / B-roll table).
        youtube_details_override = (
            data.get("youtube_details_override") or "").strip() or None
        broll_table_override = (
            data.get("broll_table_override") or "").strip() or None
        script_filename = (data.get("script_filename") or "").strip()
        script_dir = (data.get("script_dir") or "").strip()
        # Optional title supplied by the frontend after the user was
        # prompted because the script had no recognizable title line.
        provided_title = (data.get("script_title") or "").strip()

        if not script_content.strip():
            logger.warning("❌ Empty script received")
            return jsonify({"success": False, "error": "Please provide a script to process"})

        # Title check: every script must carry a recognizable title line
        # (`# Title`, `## Title`, `Title:`, or `TITLE:`) within its first
        # ~30 non-blank lines. If one is missing AND the frontend hasn't
        # already prompted the user for one, ask for it before kicking
        # off the (long-running) pipeline. The frontend handles the
        # `needs_title` response by prompting and resending.
        def _script_has_title(text: str) -> bool:
            import re as _re_t
            head_lines = []
            for _ln in text.splitlines():
                _s = _ln.strip()
                if not _s:
                    continue
                head_lines.append(_s)
                if len(head_lines) >= 30:
                    break
            for _s in head_lines:
                if _re_t.match(r"^#{1,6}\s+\S", _s):
                    return True
                if _re_t.match(r"^(?:\*{0,2}\s*)?TITLE\s*:\s*\S", _s,
                               _re_t.IGNORECASE):
                    return True
            return False

        if provided_title:
            # Prepend the supplied title as a level-1 markdown heading so
            # downstream extractors that look for `# Title` find it. If
            # the user already typed a `#`/`TITLE:` prefix, strip it
            # first and re-add a clean `# `.
            import re as _re_t2
            _clean_title = _re_t2.sub(
                r"^\s*(?:#{1,6}\s*|TITLE\s*:\s*)", "", provided_title,
                flags=_re_t2.IGNORECASE,
            ).strip()
            if _clean_title:
                script_content = f"# {_clean_title}\n\n{script_content.lstrip()}"
                logger.info(
                    f"📝 Prepended user-provided title to script: "
                    f"{_clean_title!r}"
                )
        elif not _script_has_title(script_content):
            logger.warning(
                "❌ Script has no title line — asking frontend to prompt user"
            )
            return jsonify({
                "success": False,
                "needs_title": True,
                "error": (
                    "This script has no TITLE line. Please add one (e.g. "
                    "`# My Video Title` or `TITLE: My Video Title`) at the "
                    "top of the script, or enter a title when prompted."
                ),
            }), 400

        logger.info(f"📋 Checkboxes: {checkboxes}")
        if heygen_template_id:
            logger.info(f"🎬 HeyGen Template: {heygen_template_id}")

        # Generate session ID
        session_id = str(uuid.uuid4())

        # Create progress streamer
        progress_streams[session_id] = ProgressStreamer(session_id)

        logger.info(f"🎬 Starting script processing: {session_id}")

        # Start script processing in background thread
        def run_script_processing():
            try:
                _run_cancellable_workflow(
                    session_id,
                    lambda: process_existing_script(
                        session_id, script_content, audience, tone,
                        video_length, checkboxes, heygen_template_id,
                        heygen_api_key, heygen_voice_id, grok_api_key,
                        youtube_details_override=youtube_details_override,
                        broll_table_override=broll_table_override,
                        script_filename=script_filename,
                        script_dir=script_dir,
                    ),
                )
            except Exception as e:
                logger.error(f"❌ Script processing error: {e}")
                if session_id in progress_streams:
                    progress_streams[session_id].send_update(
                        f"❌ Error: {str(e)}", -1
                    )

        thread = threading.Thread(target=run_script_processing, daemon=True)
        running_tasks[session_id] = thread
        thread.start()

        return jsonify({
            "success": True,
            "session_id": session_id,
            "message": "Script processing started"
        })

    except Exception as e:
        error_msg = f"Script processing request failed: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return jsonify({"success": False, "error": error_msg})


@app.route("/api/finalize-hook", methods=["POST"])
def finalize_hook():
    """Apply a user-chosen hook to a script and save the final output.

    Called by the frontend after the user picks one of the three hooks
    generated in hook-only mode. We strip any prior **🎬 OPENING HOOK
    OPTIONS** block from the source script, prepend a single
    **🎯 FINAL HOOK:** section with the chosen hook, and save md/docx.
    """
    import re as _re
    try:
        data = request.json or {}
        chosen_hook = (data.get("hook_text") or "").strip()
        original_script = (data.get("original_script") or "").strip()
        script_title = (data.get("script_title") or "Untitled Script").strip()

        if not chosen_hook:
            return jsonify({"success": False, "error": "hook_text is required"}), 400
        if not original_script:
            return jsonify({"success": False, "error": "original_script is required"}), 400

        # Strip ALL existing OPENING HOOK OPTIONS / FINAL HOOK blocks so we
        # never stack hooks on repeated picks. We can't rely on a `---`
        # terminator being present, so we scan for each section header and
        # delete through a tolerant end-of-section marker: next markdown
        # heading, `Heading:` marker, `---` rule, next labeled section
        # (Chapter/Part/Opening/Hook/Summary/Outro), or EOF.
        stripped = original_script

        def _strip_sections(text, header_re):
            _end_re = _re.compile(
                r"\n(?:---+\s*\n|"
                r"#{1,6}\s|"
                r"\s*Heading\s*:|"
                r"\s*\*{1,2}\s*(?:Chapter|Part|Section|Opening|Hook|Summary|Conclusion|Outro|Intro)[^\n]*\*{1,2}|"
                r"\s*\*{1,2}\s*🎬|"
                r"\s*\*{1,2}\s*🎯|"
                r"\s*(?:🎬|🎯)\s+\w)",
                flags=_re.IGNORECASE,
            )
            out = text
            # Iterate until no more matches (handles multiple stacked sections)
            for _ in range(20):
                m = header_re.search(out)
                if not m:
                    break
                tail = out[m.end():]
                e = _end_re.search(tail)
                # If end found, drop through end marker's leading newline only,
                # keeping the terminator line intact. If no end, drop to EOF.
                if e:
                    out = out[: m.start()] + tail[e.start() + 1 :]
                else:
                    out = out[: m.start()]
            return out

        # **🎬 OPENING HOOK OPTIONS** header (with optional emoji/bold).
        # The OPENING HOOK OPTIONS block has a known internal structure:
        #     # 🎬 OPENING HOOK OPTIONS
        #     *Choose one of these three hooks for your video:*
        #     **OPTION 1:** ... ---
        #     **OPTION 2:** ... ---
        #     **OPTION 3:** ... ---
        # The generic _strip_sections terminator includes `---`, so it would
        # only delete through the FIRST `---` and leave OPTION 2/3 behind.
        # Use a dedicated stripper that walks past those internal `---`
        # separators and consumes every **OPTION N:** sub-block until we hit
        # the next real section.
        _opening_hdr = _re.compile(
            r"(?:^|\n)\s*(?:={3,}\s*\n)?\s*(?:#{1,6}\s*)?\*{0,2}\s*(?:🎬\s*)?OPENING\s+HOOK\s+OPTIONS\s*\*{0,2}\s*\n(?:\s*={3,}\s*\n)?",
            flags=_re.IGNORECASE,
        )
        _option_block_re = _re.compile(
            r"\A\s*(?:\*{1,2}\s*)?OPTION\s*\d+\s*:?\s*\*{0,2}\s*\n",
            flags=_re.IGNORECASE,
        )
        _hook_block_terminator = _re.compile(
            r"\n(?:#{1,6}\s|"
            r"\s*Heading\s*:|"
            r"\s*\*{0,2}\s*(?:Chapter|Part|Section|Visual\s*Cue|B-?Roll|Summary|Conclusion|Outro|Intro|Host)\s*[:\-]|"
            r"\s*\*{0,2}\s*🎯\s*(?:THE\s+)?FINAL\s+HOOK|"
            r"\s*={3,}\s*\n\s*#)",
            flags=_re.IGNORECASE,
        )

        def _strip_opening_hook_options(text: str) -> str:
            out = text
            for _ in range(5):
                m = _opening_hdr.search(out)
                if not m:
                    break
                start = m.start()
                cursor = m.end()
                # Optionally consume an intro line like "*Choose one of these three hooks for your video:*"
                intro_m = _re.match(r"[ \t]*\*[^\n]*\n+", out[cursor:])
                if intro_m:
                    cursor += intro_m.end()
                # Now consume one or more **OPTION N:** ... --- blocks.
                consumed_any_option = False
                for _ in range(10):
                    tail = out[cursor:]
                    if not _option_block_re.match(tail):
                        break
                    # Find end of this OPTION block — next `---` line.
                    sep_m = _re.search(r"\n\s*---+\s*(?:\n|$)", tail)
                    if not sep_m:
                        # No trailing separator — consume to end of paragraph
                        # or until a real terminator.
                        term = _hook_block_terminator.search(tail)
                        cursor += term.start() + 1 if term else len(tail)
                        consumed_any_option = True
                        break
                    cursor += sep_m.end()
                    consumed_any_option = True
                # Also consume any trailing blank lines + stray `---` that
                # remain right after the OPTION blocks.
                blank_m = _re.match(r"(?:[ \t]*\n)+", out[cursor:])
                if blank_m:
                    cursor += blank_m.end()
                if not consumed_any_option:
                    # Header found but no options — fall back to terminator scan.
                    tail = out[cursor:]
                    term = _hook_block_terminator.search(tail)
                    cursor += term.start() + 1 if term else len(tail)
                out = out[:start] + "\n" + out[cursor:]
            return out

        stripped = _strip_opening_hook_options(stripped)

        # Defensive sweep: also kill any stray **OPTION N:** ... --- blocks
        # that may still be sitting at the top of the script (e.g. when the
        # OPENING HOOK OPTIONS header was already trimmed by an earlier pass
        # but its sub-options remained). This is bounded to the first 6KB so
        # we never touch genuine in-chapter content.
        _head, _rest = stripped[:6000], stripped[6000:]
        _head = _re.sub(
            r"(?:^|\n)\s*(?:\*{1,2}\s*)?OPTION\s*\d+\s*:?\s*\*{0,2}\s*\n[\s\S]*?\n\s*---+\s*(?:\n|$)",
            "\n",
            _head,
            flags=_re.IGNORECASE,
        )
        stripped = _head + _rest

        # FINAL HOOK header — tolerant: optional `#`, optional bold, optional
        # 🎯 emoji, optional `THE`, optional trailing colon. Match leading
        # newline OR start-of-string OR end of a previous line (handles cases
        # where the header is glued onto the prior line, e.g.
        # "# Title**🎯 FINAL HOOK:**").
        _final_hdr = _re.compile(
            r"(?:^|\n|(?<=\*\*))\s*(?:#{1,6}\s*)?\*{0,2}\s*(?:🎯\s*)?(?:THE\s+)?FINAL\s+HOOK\s*:?\s*\*{0,2}\s*\n",
            flags=_re.IGNORECASE,
        )
        stripped = _strip_sections(stripped, _final_hdr)

        # Also strip a stray "**Host:**" / "Host:" line if it was left behind
        # immediately after we removed a FINAL HOOK header. Only operate on
        # the very top of the script (before the first chapter / heading), and
        # only remove the bare Host: label line itself — NEVER the prose line
        # that follows it (that prose is the first sentence of a chapter).
        _lead_match = _re.match(
            r"\A([\s\S]*?)(?=\n\s*(?:#{1,6}\s|Heading\s*:|\*{1,2}\s*(?:Chapter|Part|Section)\b))",
            stripped,
            flags=_re.IGNORECASE,
        )
        if _lead_match:
            _lead = _lead_match.group(1)
            _tail = stripped[_lead_match.end():]
            _lead = _re.sub(
                r"(?:^|\n)\s*\*{0,2}\s*Host\s*:\s*\*{0,2}\s*(?=\n)",
                "\n",
                _lead,
                count=1,
                flags=_re.IGNORECASE,
            )
            stripped = _lead + _tail
        stripped = stripped.lstrip("\n")

        hook_block = (
            "**🎯 FINAL HOOK:**\n\n"
            "**Host:**\n\n"
            f"{chosen_hook}\n\n"
            "---\n\n"
        )

        # Insert AFTER the title heading if the first non-blank line is a
        # markdown heading (`# Title`). Otherwise prepend.
        title_match = _re.match(r"\s*(#{1,6}[^\n]*\n+)", stripped)
        if title_match:
            title_line = title_match.group(1)
            rest = stripped[title_match.end():]
            final_output = f"{title_line}\n{hook_block}{rest.lstrip()}"
        else:
            final_output = f"{hook_block}{stripped}"

        # Save md/docx using the same helper as the main pipeline
        try:
            saved_md, saved_docx = asyncio.run(
                _save_script_md_and_docx(script_title, final_output)
            )
        except RuntimeError:
            # Already inside an event loop — schedule synchronously
            loop = asyncio.new_event_loop()
            try:
                saved_md, saved_docx = loop.run_until_complete(
                    _save_script_md_and_docx(script_title, final_output)
                )
            finally:
                loop.close()

        return jsonify({
            "success": True,
            "script": final_output,
            "script_title": script_title,
            "markdown_path": saved_md,
            "docx_path": saved_docx,
        })

    except Exception as e:
        logger.error(f"❌ /api/finalize-hook error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/export_markdown", methods=["POST"])
def export_markdown():
    """Export script content as Markdown file"""
    logger.info("=== MARKDOWN EXPORT REQUEST RECEIVED ===")

    try:
        data = request.json
        script_content = data.get("script_content", "")
        title = data.get("title", "AI_Script")

        if not script_content:
            logger.warning("❌ No script content provided for Markdown export")
            return jsonify(
                {"success": False, "error": "No script content to export"}
            )

        logger.info(f"📝 Exporting script to Markdown: {title}")

        # Clean up title for filename
        safe_title = "".join(
            c for c in title if c.isalnum() or c in (' ', '-', '_')
        ).strip()
        safe_title = safe_title.replace(' ', '_')

        # Create Markdown content with proper formatting
        markdown_content = f"# {title}\n\n"
        markdown_content += f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n"
        markdown_content += "---\n\n"
        markdown_content += script_content

        # Create in-memory file
        markdown_bytes = markdown_content.encode('utf-8')
        markdown_io = BytesIO(markdown_bytes)

        logger.info(
            f"✅ Markdown file created successfully ({len(markdown_bytes)} bytes)"
        )

        # Send file
        response = send_file(
            markdown_io,
            mimetype='text/markdown',
            as_attachment=True,
            download_name=f'{safe_title}.md'
        )

        return response

    except Exception as e:
        error_msg = f"Markdown export failed: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return jsonify({"success": False, "error": error_msg})


@app.route("/download_comparison", methods=["POST"])
def download_comparison():
    """Download the chapter comparison report file"""
    logger.info("=== COMPARISON FILE DOWNLOAD REQUEST RECEIVED ===")

    try:
        data = request.json
        file_path = data.get("file_path", "")

        if not file_path:
            logger.warning("❌ No file path provided for comparison download")
            return jsonify(
                {"success": False, "error": "No file path provided"}
            ), 400

        # Security: Ensure the file is in the current directory and is a comparison file
        import os
        file_name = os.path.basename(file_path)
        if not file_name.startswith("chapter_comparison_") or not file_name.endswith(".md"):
            logger.warning(f"❌ Invalid file name: {file_name}")
            return jsonify(
                {"success": False, "error": "Invalid comparison file"}
            ), 400

        # Check if file exists
        if not os.path.exists(file_path):
            logger.warning(f"❌ File not found: {file_path}")
            return jsonify(
                {"success": False, "error": "Comparison file not found"}
            ), 404

        logger.info(f"📊 Sending comparison file: {file_name}")

        # Send the file
        return send_file(
            file_path,
            mimetype='text/markdown',
            as_attachment=True,
            download_name=file_name
        )

    except Exception as e:
        error_msg = f"Comparison file download failed: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return jsonify({"success": False, "error": error_msg}), 500


@app.route("/export_heygen_curl", methods=["POST"])
def export_heygen_curl():
    """Extract and export HeyGen curl commands from script"""
    logger.info("=== HEYGEN CURL EXPORT REQUEST RECEIVED ===")

    try:
        data = request.json
        script_content = data.get("script_content", "")

        if not script_content:
            logger.warning(
                "❌ No script content provided for HeyGen curl export")
            return jsonify({"error": "No script content to export"}), 400

        # Extract HeyGen section
        heygen_section_start = script_content.find("# 🎬 HEYGEN READY SCRIPT")

        if heygen_section_start == -1:
            logger.warning("❌ No HeyGen section found in script")
            return jsonify({"error": "No HeyGen section found in this script. Make sure the script has been generated with HeyGen content."}), 404

        # Find curl commands section (try multiple markers)
        curl_markers = [
            "# 🚀 HEYGEN API CURL COMMANDS",
            "CURL COMMANDS:",
            "# HEYGEN API CURL COMMANDS"
        ]

        curl_start = -1
        marker_found = None
        for marker in curl_markers:
            pos = script_content.find(marker, heygen_section_start)
            if pos != -1:
                curl_start = pos
                marker_found = marker
                break

        if curl_start == -1:
            logger.warning("❌ No curl commands found in HeyGen section")
            msg = "No curl commands found in the HeyGen section."
            return jsonify({"error": msg}), 404

        # Extract curl commands (skip the marker line, get content after)
        curl_commands = script_content[curl_start:]

        # Curl commands now run to the end of the script (after section order fix)
        # No need to look for Demo Packages section as it comes BEFORE HeyGen now
        curl_commands = curl_commands.strip()

        if not curl_commands:
            logger.warning("❌ Curl commands section is empty")
            return jsonify({"error": "HeyGen curl commands section is empty."}), 404

        logger.info(
            f"✅ Extracted {len(curl_commands)} characters of curl commands")

        # Create in-memory text file
        curl_bytes = curl_commands.encode('utf-8')
        curl_io = BytesIO(curl_bytes)

        # Send file
        response = send_file(
            curl_io,
            mimetype='text/plain',
            as_attachment=True,
            download_name='heygen_curl_commands.txt'
        )

        logger.info("✅ HeyGen curl commands exported successfully")
        return response

    except Exception as e:
        error_msg = f"HeyGen curl export failed: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return jsonify({"error": error_msg}), 500


@app.route("/api/heygen/templates", methods=["POST"])
def heygen_list_templates():
    """Proxy endpoint to fetch HeyGen templates (avoids CORS)"""
    try:
        data = request.get_json()
        api_key = data.get("api_key", "") if data else ""
        if not api_key:
            return jsonify({"error": "No API key provided"}), 400

        resp = requests.get(
            "https://api.heygen.com/v2/templates",
            headers={"accept": "application/json", "x-api-key": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        return jsonify(resp.json())

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        logger.error(f"HeyGen API error: {status} - {e}")
        return jsonify({"error": f"HeyGen API returned {status}"}), status
    except Exception as e:
        logger.error(f"HeyGen template fetch failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/heygen/template/<template_id>", methods=["POST"])
def heygen_template_details(template_id):
    """Proxy endpoint to fetch details for a single HeyGen template.
    Merges data from the list endpoint (name, thumbnail) and the
    detail endpoint (variables)."""
    try:
        data = request.get_json()
        api_key = data.get("api_key", "") if data else ""
        if not api_key:
            return jsonify({"error": "No API key provided"}), 400

        headers = {"accept": "application/json", "x-api-key": api_key}

        # Detail endpoint gives variables
        detail_resp = requests.get(
            f"https://api.heygen.com/v2/template/{template_id}",
            headers=headers, timeout=15,
        )
        detail_resp.raise_for_status()
        detail_data = detail_resp.json().get("data", {})

        # List endpoint gives name and thumbnail
        list_resp = requests.get(
            "https://api.heygen.com/v2/templates",
            headers=headers, timeout=15,
        )
        list_resp.raise_for_status()
        templates = list_resp.json().get("data", {}).get("templates", [])
        summary = next((t for t in templates if t.get(
            "template_id") == template_id), {})

        merged = {**summary, **detail_data, "template_id": template_id}
        return jsonify({"error": None, "data": merged})

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        logger.error(f"HeyGen template detail error: {status} - {e}")
        return jsonify({"error": f"HeyGen API returned {status}"}), status
    except Exception as e:
        logger.error(f"HeyGen template detail fetch failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/heygen/voices", methods=["POST"])
def heygen_list_voices():
    """Proxy endpoint to fetch HeyGen voices (avoids CORS)"""
    try:
        data = request.get_json()
        api_key = data.get("api_key", "") if data else ""
        if not api_key:
            return jsonify({"error": "No API key provided"}), 400

        resp = requests.get(
            "https://api.heygen.com/v2/voices",
            headers={"accept": "application/json", "x-api-key": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        return jsonify(resp.json())

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        logger.error(f"HeyGen voices API error: {status} - {e}")
        return jsonify({"error": f"HeyGen API returned {status}"}), status
    except Exception as e:
        logger.error(f"HeyGen voices fetch failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/heygen/test-generate", methods=["POST"])
def heygen_test_generate():
    """Proxy endpoint to test HeyGen video generation from template."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        api_key = data.get("api_key", "")
        template_id = data.get("template_id", "")
        request_body = data.get("request_body", {})

        if not api_key:
            return jsonify({"error": "No API key provided"}), 400
        if not template_id:
            return jsonify({"error": "No template ID provided"}), 400

        # HeyGen V3 (New AI Studio) template generate endpoint. The request_body
        # is built V3-shaped by the frontend (variables flattened to
        # {type, content}); the legacy V2 /v2/template/{id}/generate is deprecated.
        url = f"https://api.heygen.com/v3/templates/{template_id}"
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-api-key": api_key,
        }

        logger.info(f"🧪 Test generate: POST {url}")
        logger.info(f"🧪 Request body: {json.dumps(request_body)[:500]}")

        resp = requests.post(url, headers=headers,
                             json=request_body, timeout=30)

        logger.info(f"🧪 Response status: {resp.status_code}")
        logger.info(f"🧪 Response body: {resp.text[:500]}")

        # Return the full response with status so frontend can show it
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = {"raw_response": resp.text}

        return jsonify(resp_json), resp.status_code

    except requests.exceptions.Timeout:
        logger.error("HeyGen test-generate timed out")
        return jsonify({"error": "Request timed out after 30 seconds"}), 504
    except Exception as e:
        logger.error(f"HeyGen test-generate failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/grok/test-video", methods=["POST"])
def grok_test_video_generate():
    """Generate a single Grok test video from a prompt and return a local preview path."""
    try:
        data = request.get_json() or {}
        prompt = (data.get("prompt") or "").strip()
        duration = int(data.get("duration") or 6)
        aspect_ratio = data.get("aspect_ratio") or "16:9"
        resolution = data.get("resolution") or "480p"

        if not prompt:
            return jsonify({"success": False, "error": "Prompt is required"}), 400

        duration = max(1, min(15, duration))

        xai_api_key = (data.get("api_key") or "").strip(
        ) or os.getenv("XAI_API_KEY", "").strip()
        if not xai_api_key or xai_api_key == "your-xai-api-key-here":
            return jsonify({
                "success": False,
                "error": "Grok API key is missing. Enter it in the Web GUI Grok Key field (or set XAI_API_KEY)."
            }), 400

        import xai_sdk
        import certifi
        import datetime as dt

        logger.info("🤖 Grok test video request started")
        logger.info(f"🤖 Prompt: {prompt[:180]}")
        logger.info(
            f"🤖 Settings: duration={duration}, aspect_ratio={aspect_ratio}, resolution={resolution}")

        client = xai_sdk.Client(api_key=xai_api_key)
        response = client.video.generate(
            prompt=_grok_prompt_no_audio(prompt),
            model="grok-imagine-video",
            duration=duration,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
        )

        broll_videos_dir = Path.home() / "Dev" / "brollvideos"
        broll_videos_dir.mkdir(parents=True, exist_ok=True)

        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_prompt = "".join(c if c.isalnum() else "_" for c in prompt)[
            :40].strip("_")
        if not safe_prompt:
            safe_prompt = "test_video"
        filename = f"grok_test_{timestamp}_{safe_prompt}.mp4"
        local_path = broll_videos_dir / filename

        with requests.get(response.url, stream=True, timeout=180, verify=certifi.where()) as dl_resp:
            dl_resp.raise_for_status()
            with open(local_path, "wb") as out_file:
                for chunk in dl_resp.iter_content(chunk_size=8192):
                    if chunk:
                        out_file.write(chunk)

        logger.info(f"✅ Grok test video saved: {local_path}")

        return jsonify({
            "success": True,
            "filename": filename,
            "video_path": f"/broll-videos/{filename}",
            "source_url": response.url,
            "duration": getattr(response, "duration", duration),
            "model": getattr(response, "model", "grok-imagine-video"),
            "respect_moderation": getattr(response, "respect_moderation", None),
        })

    except Exception as e:
        logger.error(f"❌ Grok test video generation failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/cancel-workflow/<session_id>", methods=["POST"])
def api_cancel_workflow(session_id):
    """Kill an in-flight script-creation / script-processing workflow.

    Strategy:
      1. Trip every fine-grained sub-stage cancel event (B-roll images,
         thumbnails, Grok videos) so any tight loop bails immediately.
      2. Set the whole-workflow Event for any cooperative checks added later.
      3. Call ``task.cancel()`` on the asyncio task from its own event loop
         (via ``call_soon_threadsafe``) — this raises ``CancelledError`` at
         the next ``await`` point inside the AutoGen workflow, unwinding it.
      4. Push a terminal 🛑 update to the SSE stream so the UI closes cleanly.

    Honest caveat: a synchronous LLM call already in flight will not be
    interrupted mid-request — cancel takes effect at the next await boundary.
    """
    try:
        # 1. Sub-stage cancel events.
        for evt_dict in (broll_image_cancel_events,
                         thumbnail_cancel_events,
                         grok_video_cancel_events):
            evt = evt_dict.get(session_id)
            if evt is None:
                evt = _threading.Event()
                evt_dict[session_id] = evt
            evt.set()

        # 2. Whole-workflow event mirror.
        wf_evt = workflow_cancel_events.get(session_id)
        if wf_evt is None:
            wf_evt = _threading.Event()
            workflow_cancel_events[session_id] = wf_evt
        wf_evt.set()

        # 3. Cancel the asyncio task on its own loop.
        loop = workflow_loops.get(session_id)
        task = workflow_async_tasks.get(session_id)
        cancelled_task = False
        if loop is not None and task is not None and not task.done():
            try:
                loop.call_soon_threadsafe(task.cancel)
                cancelled_task = True
            except Exception as ce:
                logger.warning(f"⚠️ Could not schedule task.cancel for {session_id}: {ce}")

        # 4. Notify the UI via SSE and mark stream done.
        streamer = progress_streams.get(session_id)
        if streamer is not None:
            try:
                streamer.send_update(
                    "🛑 Cancelled by user — stopping agents…", 100
                )
            except Exception as se:
                logger.warning(f"⚠️ Could not push cancel message: {se}")

        logger.info(
            f"🛑 Workflow cancel requested for session {session_id} "
            f"(task_cancel_scheduled={cancelled_task})"
        )
        return jsonify({
            "success": True,
            "session_id": session_id,
            "task_cancel_scheduled": cancelled_task,
        })
    except Exception as e:
        logger.error(f"❌ Failed to cancel workflow {session_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/cancel-broll-images/<session_id>", methods=["POST"])
def api_cancel_broll_images(session_id):
    """Signal the in-flight B-roll image generation loop to stop ASAP and return what was produced so far."""
    try:
        evt = broll_image_cancel_events.get(session_id)
        if evt is None:
            # Pre-create the event in case the request races image generation startup.
            evt = _threading.Event()
            broll_image_cancel_events[session_id] = evt
        evt.set()
        logger.info(
            f"🛑 B-roll image generation cancel requested for session {session_id}")
        return jsonify({"success": True, "session_id": session_id})
    except Exception as e:
        logger.error(f"❌ Failed to cancel B-roll image generation: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/cancel-thumbnails/<session_id>", methods=["POST"])
def api_cancel_thumbnails(session_id):
    """Signal in-flight thumbnail generation to stop and keep partial results."""
    try:
        evt = thumbnail_cancel_events.get(session_id)
        if evt is None:
            # Pre-create in case cancel arrives before generation fully starts.
            evt = _threading.Event()
            thumbnail_cancel_events[session_id] = evt
        evt.set()
        logger.info(
            f"🛑 Thumbnail generation cancel requested for session {session_id}")
        return jsonify({"success": True, "session_id": session_id})
    except Exception as e:
        logger.error(f"❌ Failed to cancel thumbnail generation: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/extract-docx", methods=["POST"])
def api_extract_docx():
    """Extract plain text from an uploaded .docx file so the front-end can load Word scripts."""
    try:
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return jsonify({"success": False, "error": "No file uploaded"}), 400

        name_lower = upload.filename.lower()
        if not (name_lower.endswith(".docx") or name_lower.endswith(".doc")):
            return jsonify({"success": False, "error": "Only .docx files are supported"}), 400
        if name_lower.endswith(".doc") and not name_lower.endswith(".docx"):
            return jsonify({"success": False, "error": "Legacy .doc not supported. Please save as .docx first."}), 400

        try:
            from docx import Document  # python-docx
        except ImportError as e:
            return jsonify({"success": False, "error": f"python-docx not installed: {e}"}), 500

        import io
        data = upload.read()
        doc = Document(io.BytesIO(data))

        def _para_text(para):
            """Extract paragraph text, preserving soft line-breaks (<w:br>) as \\n."""
            parts = []
            for node in para._p.iter():
                local = node.tag.split(
                    "}")[-1] if "}" in node.tag else node.tag
                if local == "br":
                    br_type = node.get(
                        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type", "")
                    if br_type not in ("page", "column"):
                        parts.append("\n")
                elif local == "t":
                    parts.append(node.text or "")
            return "".join(parts).rstrip()

        lines = []
        for para in doc.paragraphs:
            raw = _para_text(para)
            style = (para.style.name or "") if para.style else ""
            # A paragraph may itself contain soft-return-separated sub-lines
            sub_lines = raw.split("\n")
            first = True
            for sub in sub_lines:
                sub = sub.rstrip()
                if first and sub and style.startswith("Heading"):
                    try:
                        level = int(style.split()[-1])
                    except (ValueError, IndexError):
                        level = 1
                    level = max(1, min(level, 6))
                    lines.append(("#" * level) + " " + sub)
                else:
                    lines.append(sub)
                first = False

        # Append tables as GitHub-flavored Markdown pipe tables (with a header
        # separator row) so downstream parsers — the B-roll table renderer and
        # parseBrollRowsFromTable — recognize them. (Previously emitted as
        # tab-separated rows, which those parsers ignore, so a loaded B-roll
        # Word doc produced "no selectable rows".)
        for table in doc.tables:
            lines.append("")
            for ri, row in enumerate(table.rows):
                cells = [(c.text or "").strip().replace("\n", " ").replace("|", "/")
                         for c in row.cells]
                lines.append("| " + " | ".join(cells) + " |")
                if ri == 0:
                    lines.append("| " + " | ".join(["---"] * len(cells)) + " |")
            lines.append("")

        text = "\n".join(lines).strip() + "\n"
        # Robust server-side title (Title: line -> Direct Video -> Heading ->
        # H1 -> first line) so the UI shows a title even if its client-side
        # parse misses this doc's format.
        extracted_title = _extract_script_title_for_output(text, "")
        return jsonify({"success": True, "text": text, "title": extracted_title,
                        "filename": upload.filename, "length": len(text)})
    except Exception as e:
        logger.error(f"❌ /api/extract-docx failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/resolve/inspect", methods=["GET"])
def api_resolve_inspect():
    """Inspect the currently-loaded DaVinci Resolve timeline.

    Returns every clip on every video & audio track including B-roll,
    adjustment clips, fusion comp names, and the property bag for each
    timeline item (transform, composite mode, retime, etc.).
    """
    try:
        from resolve_inspector import inspect_current_timeline
        result = inspect_current_timeline()
        status = 200 if result.get("success") else 400
        return jsonify(result), status
    except Exception as e:
        logger.error(f"❌ /api/resolve/inspect failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/resolve/test-swipe", methods=["POST"])
def api_resolve_test_swipe():
    """Fast feedback loop for the V3 broll swipe transition.

    Body JSON:
        {
            "video_path": "/abs/path/to/sample.mp4"   (required),
            "track_index": 3                          (optional, default 3),
            "slide_seconds": 0.4                      (optional, default 0.4),
            "timeline_name": "swipe_test"             (optional)
        }

    Behavior:
        1. Connect to running Resolve, get/create a project.
        2. Import the video into a `swipe_test` bin.
        3. Create a fresh empty timeline (name suffixed with timestamp).
        4. Append the clip to V1 *and* to the configured track (default V3)
           so the swipe (which runs on V3 by default) has something to bite.
        5. Call `_apply_wipe_to_v3_clips(...)` from davinci_resolve_api.

    Returns the wipe-result dict so the UI can show diagnostics.
    """
    payload = request.get_json(silent=True) or {}
    video_path = (payload.get("video_path") or "").strip()
    track_index = int(payload.get("track_index") or 3)
    slide_seconds = float(payload.get("slide_seconds") or 0.4)
    base_name = (payload.get("timeline_name")
                 or "swipe_test").strip() or "swipe_test"

    if not video_path:
        return jsonify({"success": False, "error": "video_path is required"}), 400
    video_path = os.path.expanduser(video_path)
    if not os.path.isfile(video_path):
        return jsonify({"success": False, "error": f"video_path not found: {video_path}"}), 400

    try:
        # Connect to Resolve.
        resolve_script_api = (
            "/Library/Application Support/Blackmagic Design/"
            "DaVinci Resolve/Developer/Scripting"
        )
        resolve_script_lib = (
            "/Applications/DaVinci Resolve/DaVinci Resolve.app/"
            "Contents/Libraries/Fusion/fusionscript.so"
        )
        os.environ["RESOLVE_SCRIPT_API"] = resolve_script_api
        os.environ["RESOLVE_SCRIPT_LIB"] = resolve_script_lib
        modules_path = os.path.join(resolve_script_api, "Modules")
        if modules_path not in sys.path:
            sys.path.append(modules_path)

        import DaVinciResolveScript as dvr_script  # type: ignore
        resolve = dvr_script.scriptapp("Resolve")
        if resolve is None:
            return jsonify({"success": False,
                            "error": "Could not connect to DaVinci Resolve. "
                                     "Is it running?"}), 500

        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject()
        if project is None:
            # Try to create / open a scratch project.
            project = pm.CreateProject("ScriptCraft_SwipeTest") or \
                pm.LoadProject("ScriptCraft_SwipeTest")
            if project is None:
                return jsonify({"success": False,
                                "error": "No current project and could not "
                                         "create 'ScriptCraft_SwipeTest'"}), 500

        media_pool = project.GetMediaPool()
        root_folder = media_pool.GetRootFolder()

        # Make / find a swipe_test bin.
        bin_name = "swipe_test"
        target_bin = None
        try:
            for sub in (root_folder.GetSubFolderList() or []):
                if sub.GetName() == bin_name:
                    target_bin = sub
                    break
        except Exception:
            pass
        if target_bin is None:
            try:
                media_pool.SetCurrentFolder(root_folder)
                target_bin = media_pool.AddSubFolder(root_folder, bin_name)
            except Exception:
                target_bin = root_folder
        try:
            media_pool.SetCurrentFolder(target_bin)
        except Exception:
            pass

        # Import the video.
        imported = media_pool.ImportMedia([video_path]) or []
        if not imported:
            return jsonify({"success": False,
                            "error": f"ImportMedia returned nothing for {video_path}"}), 500
        clip = imported[0]

        # Create a fresh timeline.
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        timeline_name = f"{base_name}_{ts}"
        timeline = media_pool.CreateEmptyTimeline(timeline_name)
        if timeline is None:
            return jsonify({"success": False,
                            "error": f"CreateEmptyTimeline('{timeline_name}') returned None"}), 500
        project.SetCurrentTimeline(timeline)

        # Make sure the target track exists.
        try:
            current_video_tracks = timeline.GetTrackCount("video") or 1
            while current_video_tracks < track_index:
                timeline.AddTrack("video")
                current_video_tracks = timeline.GetTrackCount(
                    "video") or current_video_tracks + 1
        except Exception as _te:
            logger.warning(f"⚠️ Could not ensure V{track_index} exists: {_te}")

        # Place the clip exactly once on the target track.
        appended_target = media_pool.AppendToTimeline([{
            "mediaPoolItem": clip,
            "startFrame": 0,
            "endFrame": int(clip.GetClipProperty("Frames") or 240) - 1,
            "trackIndex": track_index,
        }]) or []
        logger.info(
            f"🧪 swipe-test: appended V{track_index}={len(appended_target)}")

        # Apply the swipe.
        from davinci_resolve_api import _apply_wipe_to_v3_clips
        wipe_result = _apply_wipe_to_v3_clips(
            timeline,
            track_index=track_index,
            slide_seconds=slide_seconds,
        )

        return jsonify({
            "success": bool(wipe_result.get("success")),
            "timeline": timeline_name,
            "video_path": video_path,
            "track_index": track_index,
            "slide_seconds": slide_seconds,
            "appended_target": len(appended_target),
            "wipe": wipe_result,
        })
    except Exception as e:
        logger.error(f"❌ /api/resolve/test-swipe failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/resolve/probe-fusion", methods=["GET"])
def api_resolve_probe_fusion():
    """For a given timeline item unique_id, dump every Fusion comp's tool list.

    Use this to see whether a paid template (e.g. mTuber 4 Tiles Swap) exposes
    its inputs to the scripting API or is encrypted.
    """
    try:
        unique_id = request.args.get("unique_id", "").strip()
        if not unique_id:
            return jsonify({"success": False, "error": "unique_id query param is required"}), 400
        from resolve_inspector import probe_fusion_comp
        result = probe_fusion_comp(unique_id)
        status = 200 if result.get("success") else 400
        return jsonify(result), status
    except Exception as e:
        logger.error(f"❌ /api/resolve/probe-fusion failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/resolve/save-comp-preset", methods=["POST"])
def api_resolve_save_comp_preset():
    """Save the Fusion composition from one timeline clip as a reusable preset.

    Body JSON: { "unique_id": "...", "preset_name": "default_broll" (optional) }

    The preset file (default: scriptcraft-app-v2/fusion_presets/default_broll.setting)
    is what Create DaVinci Project will auto-apply to every V3 broll clip.
    """
    try:
        from resolve_inspector import save_comp_preset
        payload = request.get_json(silent=True) or {}
        unique_id = (payload.get("unique_id") or "").strip()
        if not unique_id:
            return jsonify({"success": False, "error": "unique_id is required"}), 400
        preset_name = (payload.get("preset_name") or "").strip() or None
        result = save_comp_preset(unique_id, preset_name=preset_name)
        return jsonify(result), (200 if result.get("success") else 400)
    except Exception as e:
        logger.error(f"❌ /api/resolve/save-comp-preset failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/keys", methods=["GET"])
def api_keys_get():
    """Return all saved API keys (Google, HeyGen, Grok). Falls back to env vars."""
    try:
        settings = _load_scriptcraft_settings()

        def _v(key, env):
            return (settings.get(key) or "").strip() or os.getenv(env, "").strip()

        def _src(key, env):
            # Where the effective value comes from, for the dialog's source tag.
            if (settings.get(key) or "").strip():
                return "saved"
            if os.getenv(env, "").strip():
                return "env"
            return "none"

        _map = {
            "google_api_key": "GOOGLE_API_KEY",
            "heygen_api_key": "HEYGEN_API_KEY",
            "grok_api_key": "XAI_API_KEY",
            "anthropic_api_key": "ANTHROPIC_API_KEY",
        }
        return jsonify({
            "success": True,
            "keys": {k: _v(k, e) for k, e in _map.items()},
            "sources": {k: _src(k, e) for k, e in _map.items()},
        })
    except Exception as e:
        logger.error(f"❌ Failed to load API keys: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/keys", methods=["POST"])
def api_keys_save():
    """Persist Google / HeyGen / Grok keys and update process env so backend modules see them."""
    try:
        data = request.get_json(silent=True) or {}
        settings = _load_scriptcraft_settings()

        mapping = {
            "google_api_key": "GOOGLE_API_KEY",
            "heygen_api_key": "HEYGEN_API_KEY",
            "grok_api_key": "XAI_API_KEY",
            "anthropic_api_key": "ANTHROPIC_API_KEY",
        }
        updated = []
        for setting_key, env_var in mapping.items():
            if setting_key in data:
                val = (data.get(setting_key) or "").strip()
                if val:
                    settings[setting_key] = val
                    os.environ[env_var] = val
                else:
                    settings.pop(setting_key, None)
                    os.environ.pop(env_var, None)
                updated.append(setting_key)

        if not updated:
            return jsonify({"success": False, "error": "No keys provided"}), 400

        if not _save_scriptcraft_settings(settings):
            return jsonify({"success": False, "error": "Could not save settings"}), 500

        logger.info(f"🔑 API keys updated: {updated}")
        return jsonify({"success": True, "updated": updated})
    except Exception as e:
        logger.error(f"❌ Failed to save API keys: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ---- YouTube OAuth client_secret.json management ----
# The YouTube publisher (youtube_publisher.py) loads OAuth client credentials
# from ~/.scriptcraft/youtube_client_secret.json (Desktop OAuth client created
# in Google Cloud Console with YouTube Data API v3 enabled). After first
# successful login the refresh token is cached at ~/.scriptcraft/youtube_token.json.

_YT_CLIENT_SECRET_PATH = Path.home() / ".scriptcraft" / "youtube_client_secret.json"
_YT_TOKEN_PATH = Path.home() / ".scriptcraft" / "youtube_token.json"


@app.route("/api/youtube/credentials/status", methods=["GET"])
def api_youtube_credentials_status():
    try:
        has_secret = _YT_CLIENT_SECRET_PATH.exists()
        has_token = _YT_TOKEN_PATH.exists()
        secret_mtime = None
        if has_secret:
            try:
                secret_mtime = int(_YT_CLIENT_SECRET_PATH.stat().st_mtime)
            except Exception:
                secret_mtime = None
        return jsonify({
            "success": True,
            "has_client_secret": has_secret,
            "client_secret_path": str(_YT_CLIENT_SECRET_PATH),
            "client_secret_mtime": secret_mtime,
            "has_token": has_token,
            "token_path": str(_YT_TOKEN_PATH),
        })
    except Exception as e:
        logger.error(f"❌ /api/youtube/credentials/status failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/youtube/credentials", methods=["POST"])
def api_youtube_credentials_upload():
    """Accept a Google OAuth Desktop client_secret JSON (file upload OR JSON body)
    and save it to ~/.scriptcraft/youtube_client_secret.json."""
    try:
        raw_text: Optional[str] = None
        # Multipart file upload from the API Keys modal
        if "file" in request.files:
            f = request.files["file"]
            raw_text = f.read().decode("utf-8", errors="replace")
        # Or JSON body { "client_secret_json": { ... } } / { "raw": "..." }
        if raw_text is None:
            body = request.get_json(silent=True) or {}
            if "client_secret_json" in body and isinstance(body["client_secret_json"], (dict, list)):
                import json as _json
                raw_text = _json.dumps(body["client_secret_json"])
            elif isinstance(body.get("raw"), str):
                raw_text = body["raw"]
        if not raw_text or not raw_text.strip():
            return jsonify({"success": False, "error": "No client_secret JSON provided"}), 400

        # Validate it parses and looks like a Google OAuth client file
        import json as _json
        try:
            parsed = _json.loads(raw_text)
        except Exception as parse_exc:
            return jsonify({"success": False, "error": f"Not valid JSON: {parse_exc}"}), 400
        if not isinstance(parsed, dict) or not ("installed" in parsed or "web" in parsed):
            return jsonify({"success": False,
                            "error": "JSON does not look like a Google OAuth client secret (missing 'installed' or 'web' key)"}), 400

        _YT_CLIENT_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
        _YT_CLIENT_SECRET_PATH.write_text(_json.dumps(parsed, indent=2), encoding="utf-8")
        try:
            _YT_CLIENT_SECRET_PATH.chmod(0o600)
        except Exception:
            pass
        logger.info(f"🎬 YouTube client_secret saved: {_YT_CLIENT_SECRET_PATH}")
        return jsonify({
            "success": True,
            "path": str(_YT_CLIENT_SECRET_PATH),
            "mtime": int(_YT_CLIENT_SECRET_PATH.stat().st_mtime),
        })
    except Exception as e:
        logger.error(f"❌ /api/youtube/credentials upload failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/youtube/credentials/token", methods=["DELETE"])
def api_youtube_credentials_clear_token():
    """Delete the cached OAuth token, forcing re-auth on next publish."""
    try:
        removed = False
        if _YT_TOKEN_PATH.exists():
            _YT_TOKEN_PATH.unlink()
            removed = True
        return jsonify({"success": True, "removed": removed})
    except Exception as e:
        logger.error(f"❌ /api/youtube/credentials/token DELETE failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/output-dir", methods=["GET"])
def api_output_dir_get():
    """Return the currently configured base output directory (or empty string)."""
    try:
        settings = _load_scriptcraft_settings()
        return jsonify({
            "success": True,
            "output_dir": (settings.get("output_dir") or "").strip(),
        })
    except Exception as e:
        logger.error(f"❌ Failed to load output_dir: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/output-dir", methods=["POST"])
def api_output_dir_save():
    """Persist the base output directory path without creating it immediately."""
    try:
        data = request.get_json(silent=True) or {}
        raw = (data.get("output_dir") or "").strip()
        settings = _load_scriptcraft_settings()

        if not raw:
            settings.pop("output_dir", None)
            _save_scriptcraft_settings(settings)
            return jsonify({"success": True, "output_dir": "", "cleared": True})

        expanded = Path(raw).expanduser().resolve()
        if expanded.exists() and not expanded.is_dir():
            return jsonify({
                "success": False,
                "error": "Path exists but is not a directory",
            }), 400

        settings["output_dir"] = str(expanded)
        if not _save_scriptcraft_settings(settings):
            return jsonify({"success": False, "error": "Could not save settings"}), 500

        logger.info(f"📁 Output directory set: {expanded}")
        return jsonify({"success": True, "output_dir": str(expanded)})
    except Exception as e:
        logger.error(f"❌ Failed to save output_dir: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/browse-dirs", methods=["GET"])
def api_browse_dirs():
    """List immediate subdirectories of a path for the in-app folder browser.

    Query params:
      path: starting absolute or ~-prefixed path. Empty/missing -> $HOME.
      show_hidden: '1' to include dotfile directories.
    Returns:
      {success, path, parent, entries: [{name, path}], home, can_create}
    """
    try:
        raw = (request.args.get("path") or "").strip()
        show_hidden = request.args.get("show_hidden") == "1"
        home = str(Path.home())

        if not raw:
            target = Path.home()
        else:
            target = Path(raw).expanduser()

        try:
            target = target.resolve()
        except Exception:
            return jsonify({"success": False, "error": f"Invalid path: {raw}"}), 400

        if not target.exists():
            return jsonify({"success": False, "error": f"Path does not exist: {target}"}), 404
        if not target.is_dir():
            return jsonify({"success": False, "error": f"Not a directory: {target}"}), 400

        entries = []
        try:
            for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
                try:
                    if not child.is_dir():
                        continue
                    if not show_hidden and child.name.startswith("."):
                        continue
                    entries.append({"name": child.name, "path": str(child)})
                except (PermissionError, OSError):
                    continue
        except PermissionError:
            return jsonify({"success": False, "error": f"Permission denied: {target}"}), 403

        parent = str(target.parent) if target.parent != target else None
        return jsonify({
            "success": True,
            "path": str(target),
            "parent": parent,
            "home": home,
            "entries": entries,
        })
    except Exception as e:
        logger.error(f"❌ /api/browse-dirs failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/create-dir", methods=["POST"])
def api_create_dir():
    """Create a new subdirectory inside the given parent path. Used by the folder browser."""
    try:
        data = request.get_json(silent=True) or {}
        parent_raw = (data.get("parent") or "").strip()
        name_raw = (data.get("name") or "").strip()
        if not parent_raw or not name_raw:
            return jsonify({"success": False, "error": "parent and name are required"}), 400
        # Reject path separators in folder name
        if "/" in name_raw or "\\" in name_raw or name_raw in (".", ".."):
            return jsonify({"success": False, "error": "Invalid folder name"}), 400

        parent = Path(parent_raw).expanduser().resolve()
        if not parent.is_dir():
            return jsonify({"success": False, "error": f"Parent is not a directory: {parent}"}), 400

        target = parent / name_raw
        target.mkdir(parents=False, exist_ok=True)
        return jsonify({"success": True, "path": str(target)})
    except Exception as e:
        logger.error(f"❌ /api/create-dir failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/save-outputs", methods=["POST"])
def api_save_outputs():
    """Copy the current run's artifacts into {output_parent}/{safe_script_title}.

    Layout:
        {run_dir}/script/<title>.md
        {run_dir}/images/<broll image files>
        {run_dir}/broll/<grok video files>
        {run_dir}/MDL/<edl file>
        {run_dir}/thumbnails/<thumbnail files>
        {run_dir}/curls/<title>_curls.json
    """
    import shutil
    import re as _re

    try:
        data = request.get_json(silent=True) or {}
        title_raw = (data.get("title") or "script").strip() or "script"
        safe_title = _re.sub(r'[^A-Za-z0-9._-]+', '_',
                             title_raw).strip('_') or "script"
        base_path = _get_run_output_dir(title_raw, create=True)

        script_text = data.get("script") or ""
        edl_filename = (data.get("edl_filename") or "").strip()
        edl_content = data.get("edl_content") or ""
        curl_commands = data.get("curl_commands")
        broll_images = data.get("broll_images") or []
        grok_videos = data.get("grok_videos") or []
        thumbnails = data.get("thumbnails") or []

        report = {
            "script": None,
            "edl": None,
            "curls": None,
            "images": [], "images_skipped": [],
            "videos": [], "videos_skipped": [],
            "thumbnails": [], "thumbnails_skipped": [],
        }

        # --- script ---
        if script_text:
            script_dir = base_path / "script"
            script_dir.mkdir(parents=True, exist_ok=True)
            script_path = script_dir / f"{safe_title}.md"
            script_path.write_text(script_text, encoding="utf-8")
            report["script"] = str(script_path)

        # --- EDL (user calls it MDL) ---
        if edl_content or edl_filename:
            mdl_dir = base_path / "MDL"
            mdl_dir.mkdir(parents=True, exist_ok=True)
            target_name = Path(
                edl_filename).name if edl_filename else f"{safe_title}.edl"
            edl_path = mdl_dir / target_name
            if edl_content:
                edl_path.write_text(edl_content, encoding="utf-8")
            else:
                src = _resolve_media_file(target_name, 'edl')
                if src:
                    shutil.copy2(src, edl_path)
                else:
                    edl_path = None
            if edl_path:
                report["edl"] = str(edl_path)

        # --- curl commands ---
        if curl_commands:
            curl_dir = base_path / "curls"
            curl_dir.mkdir(parents=True, exist_ok=True)
            if isinstance(curl_commands, str):
                curl_path = curl_dir / f"{safe_title}_curls.sh"
                curl_path.write_text(curl_commands, encoding="utf-8")
            else:
                curl_path = curl_dir / f"{safe_title}_curls.json"
                curl_path.write_text(json.dumps(
                    curl_commands, indent=2), encoding="utf-8")
            report["curls"] = str(curl_path)

        # --- images / videos / thumbnails: pull names out of structured items ---
        def _names_of(items):
            out = []
            for it in (items or []):
                if isinstance(it, str):
                    out.append(it)
                elif isinstance(it, dict):
                    fn = it.get("filename") or it.get(
                        "filepath") or it.get("path")
                    if fn:
                        out.append(Path(fn).name)
            return out

        image_names = _names_of(broll_images)
        if image_names:
            img_dir = base_path / "images"
            img_dir.mkdir(parents=True, exist_ok=True)
            for fn in image_names:
                src = _resolve_media_file(fn, 'image')
                if src:
                    dst = img_dir / src.name
                    shutil.copy2(src, dst)
                    report["images"].append(str(dst))
                else:
                    report["images_skipped"].append(fn)

        video_names = _names_of(grok_videos)
        if video_names:
            vid_dir = base_path / "broll"
            vid_dir.mkdir(parents=True, exist_ok=True)
            for fn in video_names:
                src = _resolve_media_file(fn, 'video')
                if src:
                    dst = vid_dir / src.name
                    shutil.copy2(src, dst)
                    report["videos"].append(str(dst))
                else:
                    report["videos_skipped"].append(fn)

        thumb_names = _names_of(thumbnails)
        if thumb_names:
            thumb_dir = base_path / "thumbnails"
            thumb_dir.mkdir(parents=True, exist_ok=True)
            for fn in thumb_names:
                src = _resolve_media_file(fn, 'thumbnail')
                if src:
                    dst = thumb_dir / src.name
                    shutil.copy2(src, dst)
                    report["thumbnails"].append(str(dst))
                else:
                    report["thumbnails_skipped"].append(fn)

        total_saved = (
            (1 if report["script"] else 0)
            + (1 if report["edl"] else 0)
            + (1 if report["curls"] else 0)
            + len(report["images"]) + len(report["videos"]) +
            len(report["thumbnails"])
        )
        total_skipped = (
            len(report["images_skipped"])
            + len(report["videos_skipped"])
            + len(report["thumbnails_skipped"])
        )
        logger.info(
            f"💾 save-outputs → run_dir={base_path} | saved={total_saved} skipped={total_skipped}"
        )
        return jsonify({
            "success": True,
            "base_dir": str(base_path),
            "report": report,
            "total_saved": total_saved,
            "total_skipped": total_skipped,
        })
    except Exception as e:
        logger.error(f"❌ /api/save-outputs failed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/grok/key", methods=["GET"])
def grok_get_saved_key():
    """Return saved Grok API key from server settings (if any)."""
    try:
        settings = _load_scriptcraft_settings()
        key = (settings.get("grok_api_key") or "").strip()
        return jsonify({"success": True, "api_key": key})
    except Exception as e:
        logger.error(f"❌ Failed to load saved Grok key: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# Hint appended to every Grok video prompt so the generator avoids audio.
# xai_sdk video.generate has no audio toggle, so we steer the model via prompt.
GROK_NO_AUDIO_HINT = (
    " Silent video only. No audio, no music, no sound effects, no dialogue, "
    "no voiceover, no ambient sound. Visuals only."
)


def _grok_prompt_no_audio(prompt: str) -> str:
    """Append the no-audio hint to a Grok video prompt (idempotent)."""
    base = (prompt or "").strip()
    if not base:
        return base
    if "silent video" in base.lower() or "no audio" in base.lower():
        return base
    return base.rstrip(".") + "." + GROK_NO_AUDIO_HINT


# ---------------------------------------------------------------------------
# Grok "unique visual" prompt rewriting
# ---------------------------------------------------------------------------
# Raw b-roll descriptions are often flat and generic. Grok's value is bespoke,
# theme-specific footage you can't easily stock-source — but it must look
# PROFESSIONAL, not cartoonish. We steer every scene toward either (a)
# photorealistic, cinematic LIVE-ACTION with real people, or (b) clean, modern
# business MOTION GRAPHICS (3D charts, animated diagrams, holographic UI) for
# data/abstract concepts — always with real motion/action. We explicitly avoid
# cartoon / anime / illustrated / hand-drawn styles, which read as amateurish
# here. The scene is rewritten into exactly that before grok-imagine-video.

# Ops kill-switch: set GROK_VISUAL_REWRITE=0 to send raw descriptions instead.
GROK_VISUAL_REWRITE_ENABLED = (
    os.getenv("GROK_VISUAL_REWRITE", "1").strip().lower()
    not in ("0", "false", "no", "off")
)

# Text model used to rewrite scene descriptions into visual prompts.
GROK_REWRITE_MODEL = (
    os.getenv("GROK_REWRITE_MODEL", "grok-3-mini").strip() or "grok-3-mini"
)

# Deterministic fallback styling, used when the LLM rewrite is unavailable — it
# steers a raw description toward photoreal live-action / clean business motion
# graphics (never cartoons) while staying on-scene.
GROK_VISUAL_STYLE_DIRECTIVE = (
    " Render this as photorealistic, cinematic live-action video with real "
    "human actors, natural lighting, and dynamic camera movement and motion "
    "(not a static shot). For data or abstract business concepts, use clean, "
    "modern, professional 3D motion graphics — animated charts, diagrams, or "
    "holographic UI. Absolutely NO cartoon, anime, comic, illustrated, "
    "hand-drawn, or claymation styles. Stay faithful to what is described above."
)

GROK_REWRITE_SYSTEM = (
    "You convert a b-roll scene description into ONE prompt for an AI video "
    "generator (grok-imagine-video) that makes a ~6 second SILENT clip.\n"
    "GOAL: depict EXACTLY WHAT THE DESCRIPTION SAYS — the same subject, "
    "objects, setting, and action — as PHOTOREALISTIC, CINEMATIC, LIVE-ACTION "
    "video with dynamic motion. The viewer must immediately recognize the thing "
    "the description is about.\n"
    "STYLE (strict):\n"
    "- When people are involved, show REAL human actors — photorealistic skin, "
    "natural lighting, real-world settings. Never cartoon or illustrated "
    "characters.\n"
    "- For data, systems, or abstract business concepts, use clean, modern, "
    "professional motion graphics: 3D charts, animated diagrams, holographic "
    "UI, sleek infographics — a corporate/editorial look, NOT cartoonish.\n"
    "- ALWAYS include real motion and action — camera movement, gestures, "
    "moving elements — so the clip feels alive. This dynamic motion is what we "
    "mean by 'more animation'.\n"
    "- ABSOLUTELY FORBIDDEN styles: cartoon, anime, comic, hand-drawn, "
    "children's illustration, claymation, flat 2D character animation, "
    "stylized Pixar/CGI-character looks.\n"
    "Rules:\n"
    "- FIDELITY FIRST: keep the description's concrete nouns, subject, setting, "
    "and action. You set the visual STYLE (photoreal live-action, or clean "
    "business motion graphics), NOT the CONTENT. Never swap the scene for an "
    "unrelated abstract metaphor.\n"
    "- Add a little topic-specific detail from the theme so it clearly belongs "
    "to THIS subject. Describe the key elements, the MOTION, the lighting, and "
    "a photorealistic / cinematic art direction. No on-screen text or "
    "captions.\n"
    "- Output ONLY the final prompt: 1-2 sentences, under ~55 words, no quotes, "
    "no preamble, no lists."
)

# Preferred path: Claude (Opus 4.8) acts as a prompt engineer, turning the
# b-roll description into an optimal grok-imagine-video prompt. Same anti-cartoon
# style rules as the xAI rewrite. Requires ANTHROPIC_API_KEY; falls back to xAI
# (then the deterministic directive) when unavailable.
GROK_PROMPT_ENGINEER_SYSTEM = (
    "You are a prompt engineer for grok-imagine-video (ONE short ~6s SILENT "
    "clip). You are given the SCRIPT LINE this b-roll illustrates. Create ONE "
    "simple animated EXPLAINER scene that conveys the POINT of that line — like a "
    "clean whiteboard / motion-graphic explainer.\n"
    "HOW (the whole job is translating the words into simple symbols):\n"
    "- Turn the key elements of the line into a few CLEAR, SIMPLE visual symbols "
    "and short labels, combined into ONE cohesive scene with gentle motion and a "
    "small setup->payoff arc. Labels and short on-screen text ARE encouraged when "
    "they make the meaning obvious.\n"
    "- Represent named things as simple labeled figures/objects; represent "
    "abstract ideas as simple icons; show the conclusion, using a text label if "
    "it is the punchline.\n"
    "- WORKED EXAMPLE. Line: 'every month a Yale team checks the entire US labor "
    "market for AI damage and finds no disruption.' Good prompt: 'a small "
    "research team labeled Yale Research examines a cluster of little factories "
    "through a big magnifying glass as calendar months fly past, then a large "
    "label reading No AI Disruption stamps onto the scene.'\n"
    "- Keep it SIMPLE and readable — a few symbols in ONE scene. NOT a photoreal "
    "literal shot ('a person at a laptop' is boring filler), and NOT a montage of "
    "several separate shots.\n"
    "STYLE: clean, modern, simple 2D animated motion-graphic look — simple line "
    "icons/symbols and labels, minimal flat color, plain background, light gentle "
    "motion.\n"
    "- FORBIDDEN: cartoon/anime characters, claymation, mascots, busy cluttered "
    "compositions.\n"
    "Output ONLY the final prompt: 1-2 short sentences, ~20-45 words, naming the "
    "symbols, labels, and gentle motion. No quotes, no preamble, no lists."
)

# The "Grok Chalk Prompt" column is the SAME visual as the cinematic prompt,
# redrawn as rough white chalk on black — so the two columns always match, just
# in different styles. It is given the already-chosen cinematic prompt as input.
GROK_CHALK_PROMPT_ENGINEER_SYSTEM = (
    "You are a prompt engineer for grok-imagine-video (ONE short ~4-6s SILENT "
    "clip). You are GIVEN a visual scene that has already been chosen. Redraw "
    "that SAME scene — the same subject, symbol, and action — as ONE simple "
    "ROUGH WHITE CHALK DRAWING on a BLACK background (hand-sketched chalkboard "
    "look). Do NOT invent a different subject; keep the given visual, only change "
    "the style to chalk.\n"
    "STYLE:\n"
    "- BEGIN with exactly: 'Rough white chalk drawing on black background, simple "
    "and clean, show ' then the same subject/action from the given scene.\n"
    "- White chalk strokes only on matte black; loose, hand-drawn; the lines "
    "draw themselves on with gentle motion. Keep it one simple sketch.\n"
    "- FORBIDDEN: photorealism, live action, color, 3D renders, cartoon/anime "
    "characters, any colored or non-black background.\n"
    "Output ONLY the final prompt: 1-2 short sentences, ~20-45 words (starting "
    "with the required phrase), keeping the same symbols and labels. No quotes, "
    "no preamble, no lists."
)


def _grok_prompt_via_claude(
    description: str,
    scene_context: str = "",
    theme: str = "",
    system: Optional[str] = None,
    max_len: int = 600,
    script_excerpt: str = "",
) -> Optional[str]:
    """Ask Claude (Opus 4.8) to craft an optimal grok-imagine-video prompt from
    the b-roll description. ``system`` selects the style engine (default cinematic
    ``GROK_PROMPT_ENGINEER_SYSTEM``; pass ``GROK_CHALK_PROMPT_ENGINEER_SYSTEM``
    for the chalk variant). ``script_excerpt`` is the actual script moment the
    clip illustrates — passed so the visual is specific to the scene, not generic.
    Returns the prompt, or None if ANTHROPIC_API_KEY / the SDK is missing or the
    call fails."""
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    try:
        parts = []
        if (scene_context or "").strip():
            parts.append(
                "SCRIPT LINE this clip must make the point of — anchor the visual "
                f"to THIS: {scene_context.strip()}")
        if (script_excerpt or "").strip():
            parts.append(
                f"Surrounding script (context only): \"{script_excerpt.strip()}\"")
        parts.append(
            "Scene / suggested visual (a starting idea — it may be over-elaborate; "
            "simplify it into ONE clear symbolic shot, don't copy it literally): "
            f"{description}")
        if (theme or "").strip():
            parts.append(
                "Overall video topic (flavor only, do NOT replace the scene): "
                f"{theme.strip()}")
        user_msg = "\n".join(parts)

        # Fail fast: the B-roll table now generates a cinematic AND an
        # chalk prompt for every row (dozens of calls per table). When
        # Anthropic is overloaded (HTTP 529), retrying turns that into a
        # multi-minute stall that blocks the B-roll step from returning. With
        # max_retries=0 an overloaded call falls straight through to the
        # deterministic/xAI fallback (cinematic) or an empty cell (chalk)
        # instead of hanging.
        client = anthropic.Anthropic(
            api_key=api_key, timeout=45.0, max_retries=0)
        resp = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=500,
            system=system or GROK_PROMPT_ENGINEER_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        out = "".join(
            b.text for b in resp.content
            if getattr(b, "type", None) == "text"
        ).strip().strip('"').strip()
        if out and len(out) <= max_len:
            logger.info(f"🎨 Grok prompt (Claude): {out[:140]}")
            return out
    except Exception as e:
        logger.warning(f"⚠️ Claude Grok-prompt rewrite failed: {e}")
    return None


def _resolve_xai_api_key() -> str:
    """Resolve the xAI/Grok API key from saved server settings first, then the
    XAI_API_KEY env var. Returns "" when neither is set (or is the placeholder)."""
    key = ""
    try:
        key = (_load_scriptcraft_settings().get("grok_api_key") or "").strip()
    except Exception:
        key = ""
    if not key:
        key = (os.getenv("XAI_API_KEY") or "").strip()
    if key == "your-xai-api-key-here":
        return ""
    return key


def _grok_prompt_via_xai(
    description: str,
    scene_context: str = "",
    theme: str = "",
    system: Optional[str] = None,
    max_len: int = 600,
    script_excerpt: str = "",
) -> Optional[str]:
    """Ask Grok (xAI ``GROK_REWRITE_MODEL``) to craft a grok-imagine-video prompt,
    using the SAME engineer/chalk system prompts as ``_grok_prompt_via_claude`` so
    the visual style is identical — this is the fallback used when the Anthropic
    key is missing or failing. Returns the prompt, or None when the xAI key/SDK is
    unavailable or the call fails."""
    api_key = _resolve_xai_api_key()
    if not api_key:
        return None
    try:
        import xai_sdk
        from xai_sdk.chat import system as _xai_system, user as _xai_user
    except ImportError:
        return None
    try:
        parts = []
        if (scene_context or "").strip():
            parts.append(
                "SCRIPT LINE this clip must make the point of — anchor the visual "
                f"to THIS: {scene_context.strip()}")
        if (script_excerpt or "").strip():
            parts.append(
                f"Surrounding script (context only): \"{script_excerpt.strip()}\"")
        parts.append(
            "Scene / suggested visual (a starting idea — it may be over-elaborate; "
            "simplify it into ONE clear symbolic shot, don't copy it literally): "
            f"{description}")
        if (theme or "").strip():
            parts.append(
                "Overall video topic (flavor only, do NOT replace the scene): "
                f"{theme.strip()}")
        user_msg = "\n".join(parts)

        client = xai_sdk.Client(api_key=api_key)
        chat = client.chat.create(model=GROK_REWRITE_MODEL, temperature=0.6)
        chat.append(_xai_system(system or GROK_PROMPT_ENGINEER_SYSTEM))
        chat.append(_xai_user(user_msg))
        resp = chat.sample()
        out = (getattr(resp, "content", "") or "").strip().strip('"').strip()
        if out and len(out) <= max_len:
            logger.info(f"🎨 Grok prompt (xAI): {out[:140]}")
            return out
    except Exception as e:
        logger.warning(f"⚠️ xAI Grok-prompt rewrite failed: {e}")
    return None


def _grok_prompt_via_llm(
    description: str,
    scene_context: str = "",
    theme: str = "",
    system: Optional[str] = None,
    max_len: int = 600,
    script_excerpt: str = "",
) -> Optional[str]:
    """Craft a grok-imagine-video prompt via Claude (Opus 4.8) when available,
    falling back to Grok (xAI) with the SAME system prompt when the Anthropic key
    is missing/failing. Returns None only if BOTH providers are unavailable."""
    out = _grok_prompt_via_claude(
        description, scene_context, theme, system=system, max_len=max_len,
        script_excerpt=script_excerpt)
    if out:
        return out
    return _grok_prompt_via_xai(
        description, scene_context, theme, system=system, max_len=max_len,
        script_excerpt=script_excerpt)


def _grok_build_chalk_prompt(
    base_visual: str,
    scene_context: str = "",
    theme: str = "",
    script_excerpt: str = "",
) -> str:
    """Redraw an already-chosen visual (the cinematic Grok prompt) as its white-
    chalk-on-black twin, so the "Grok Imagine" and "Grok Chalk" table columns show
    the SAME scene in two styles. Uses Claude when available, falling back to Grok
    (xAI). Returns "" when the rewrite is disabled or BOTH providers are
    unavailable (this column is a bonus, no deterministic fallback)."""
    base = (base_visual or "").strip()
    if not base or not GROK_VISUAL_REWRITE_ENABLED:
        return ""
    out = _grok_prompt_via_llm(
        base, system=GROK_CHALK_PROMPT_ENGINEER_SYSTEM, max_len=900)
    return out or ""


def _grok_chalk_prompts_from_cinematic(grok_prompts: dict, max_workers: int = 8) -> dict:
    """Redraw each cinematic Grok prompt as its white-chalk twin (same visual, two
    styles) so the two b-roll table columns always match. Returns
    ``{row_index: chalk_prompt}``. Best-effort — a failing row yields ""."""
    out: dict = {}
    items = [(i, p) for i, p in (grok_prompts or {}).items() if (p or "").strip()]
    if not items:
        return out

    def _one(item):
        i, cine = item
        try:
            return i, (_grok_build_chalk_prompt(cine) or "")
        except Exception as e:
            logger.warning(f"⚠️ Chalk-from-cinematic failed (row {i}): {e}")
            return i, ""

    try:
        from concurrent.futures import ThreadPoolExecutor
        workers = max(1, min(max_workers, len(items)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, p in ex.map(_one, items):
                out[i] = p
    except Exception as e:
        logger.warning(f"⚠️ Chalk batch failed ({e}); running sequentially")
        for item in items:
            i, p = _one(item)
            out[i] = p
    return out


def _grok_build_video_prompt(
    description: str,
    scene_context: str = "",
    theme: str = "",
    client=None,
    script_excerpt: str = "",
) -> str:
    """Rewrite a stock-style b-roll description into a unique, theme-specific
    Grok video prompt (animation / diagram / artwork).

    Falls back to the original description plus a style directive whenever the
    LLM rewrite is disabled or fails, so generation never breaks on this step.
    """
    base = (description or "").strip()
    if not base:
        return base
    styled_fallback = base.rstrip(".") + "." + GROK_VISUAL_STYLE_DIRECTIVE

    if not GROK_VISUAL_REWRITE_ENABLED:
        return styled_fallback

    # 1) Preferred: Claude (Opus 4.8) writes the optimal grok-imagine prompt;
    #    falls back to Grok (xAI) with the same engineer system prompt when the
    #    Anthropic key is missing/failing.
    llm_out = _grok_prompt_via_llm(
        base, scene_context, theme, script_excerpt=script_excerpt)
    if llm_out:
        return llm_out

    # 2) Fallback: xAI grok-3-mini rewrite (needs an explicitly-passed xAI client).
    if client is None:
        return styled_fallback

    try:
        from xai_sdk.chat import system as _xai_system, user as _xai_user

        parts = []
        parts.append(
            "SCENE TO DEPICT (most important — your prompt MUST show exactly "
            f"this, keeping its specific subject and objects): {base}")
        if (script_excerpt or "").strip():
            parts.append(
                "EXACT SCRIPT MOMENT this b-roll illustrates — depict THIS "
                "specific content literally, not a generic stock version: "
                f"\"{script_excerpt.strip()}\"")
        if (scene_context or "").strip():
            parts.append(f"Why this scene appears in the video: {scene_context.strip()}")
        if (theme or "").strip():
            parts.append(
                f"Overall video topic (for flavor/detail only, do NOT replace "
                f"the scene with it): {theme.strip()}")
        user_msg = "\n".join(parts)

        chat = client.chat.create(model=GROK_REWRITE_MODEL, temperature=0.6)
        chat.append(_xai_system(GROK_REWRITE_SYSTEM))
        chat.append(_xai_user(user_msg))
        resp = chat.sample()
        out = (getattr(resp, "content", "") or "").strip().strip('"').strip()
        # Reject empty / runaway output (model ignored the length rule).
        if out and len(out) <= 600:
            logger.info(f"🎨 Grok prompt rewritten: {out[:140]}")
            return out
        return styled_fallback
    except Exception as e:
        logger.warning(
            f"⚠️ Grok prompt rewrite failed; using styled fallback: {e}")
        return styled_fallback


@app.route("/api/grok/key", methods=["POST"])
def grok_save_key():
    """Persist Grok API key in server settings so it survives browser/session changes."""
    try:
        data = request.get_json() or {}
        api_key = (data.get("api_key") or "").strip()
        if not api_key:
            return jsonify({"success": False, "error": "api_key is required"}), 400

        settings = _load_scriptcraft_settings()
        settings["grok_api_key"] = api_key
        if not _save_scriptcraft_settings(settings):
            return jsonify({"success": False, "error": "Could not save settings"}), 500

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"❌ Failed to save Grok key: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


def _grok_get_output_dir(script_title: Optional[str] = None) -> Path:
    """Resolve directory for Grok video output under the active run folder."""
    if script_title:
        base = _get_run_output_dir(script_title, create=True)
    else:
        base = _get_output_parent_dir()
    target = base / "broll"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _grok_emit(session_id: str, payload: dict) -> None:
    q = grok_video_streams.get(session_id)
    if q is not None:
        try:
            q.put_nowait(payload)
        except Exception:
            pass


def _upscale_video_to_1080p(path) -> bool:
    """Best-effort upscale a Grok clip to 1080p via ffmpeg (grok-imagine-video
    maxes out at 720p natively, and xAI has no upscale API). Re-encodes in place
    with Lanczos scaling to 1080p height, preserving aspect ratio. On any problem
    (ffmpeg missing, timeout, error) the original file is left untouched. Returns
    True only if the file was actually replaced with the 1080p version."""
    try:
        import shutil
        import subprocess
        if shutil.which("ffmpeg") is None:
            logger.info("ℹ️ ffmpeg not on PATH — keeping 720p Grok clip")
            return False
        src = Path(path)
        if not src.exists() or src.stat().st_size == 0:
            return False
        tmp = src.with_name(src.stem + ".1080p" + src.suffix)
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
            "-vf", "scale=-2:1080:flags=lanczos",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart",
            str(tmp),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(src)
            logger.info(f"⬆️ Upscaled Grok clip to 1080p → {src.name}")
            return True
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        logger.warning(
            f"⚠️ 1080p upscale failed (rc={res.returncode}): "
            f"{(res.stderr or '')[:200]}")
    except Exception as e:
        logger.warning(f"⚠️ 1080p upscale error: {e}")
    return False


def _grok_generate_worker(session_id: str, selected_rows: list, api_key: str, script_title: str = "", script_id: str = "") -> None:
    """Background worker: generate Grok videos one-by-one, streaming progress and honoring cancel."""
    cancel_evt = grok_video_cancel_events.setdefault(
        session_id, _threading.Event())
    out_dir = _grok_get_output_dir(script_title or None)
    videos: list = []
    failures: list = []
    # Each selected scene yields up to TWO clips — a cinematic take and a
    # chalk-sketch take — so the total is ~2× the rows.
    total = len(selected_rows) * 2
    cancelled = False

    try:
        import xai_sdk  # type: ignore
        import certifi  # type: ignore
        client = xai_sdk.Client(api_key=api_key)
    except Exception as e:
        _grok_emit(session_id, {
            "type": "error",
            "message": f"❌ Failed to init Grok client: {e}",
        })
        _grok_emit(session_id, {
            "type": "done", "cancelled": False, "videos": [], "failures": [],
            "generated_count": 0, "failed_count": 0, "total_requested": total,
            "output_dir": str(out_dir),
        })
        grok_video_results[session_id] = {
            "videos": [], "failures": [], "cancelled": False}
        return

    _grok_emit(session_id, {
        "type": "start",
        "message": f"🎬 Starting Grok video generation: {total} clip(s) → {out_dir}",
        "total": total,
        "output_dir": str(out_dir),
    })

    clip_no = 0
    for i, row in enumerate(selected_rows):
        if cancel_evt.is_set():
            cancelled = True
            break

        desc = (row.get("description") or row.get(
            "search_term") or "").strip()
        term = row.get("search_term", f"vid{i}") or f"vid{i}"
        timecode = row.get("timecode", "")
        scene_context = (row.get("scene_context") or "").strip()

        if not desc:
            clip_no += 1
            failures.append(
                {"index": i, "error": "Missing prompt", "row": row})
            _grok_emit(session_id, {
                "type": "video_failed",
                "index": i, "current": clip_no, "total": total,
                "search_term": term, "timecode": timecode,
                "error": "Missing prompt",
                "message": f"⚠️ [{clip_no}/{total}] Skipped '{term}' — missing prompt",
            })
            continue

        # Pull MORE out of each scene: generate TWO clips — a cinematic take and
        # a rough white-chalk-on-black hand-drawn take. Reuse the prompts already
        # prepared on the row (from the B-roll table) when present; otherwise
        # build them now (Claude, with xAI fallback for the cinematic one).
        variants = []
        cine = (row.get("grok_prompt") or "").strip() or _grok_build_video_prompt(
            desc, scene_context, script_title, client=client)
        if cine:
            variants.append(("cinematic", cine))
        # Chalk is the SAME visual as the cinematic prompt, redrawn in chalk.
        chalk = (row.get("grok_chalk_prompt") or "").strip() or \
            _grok_build_chalk_prompt(cine or desc)
        if chalk:
            variants.append(("chalk", chalk))
        if not variants:
            variants.append(("cinematic", desc))

        for style, gen_prompt in variants:
            if cancel_evt.is_set():
                cancelled = True
                break
            clip_no += 1

            _grok_emit(session_id, {
                "type": "video_start",
                "index": i, "current": clip_no, "total": total,
                "search_term": term, "style": style,
                "timecode": timecode, "description": desc,
                "generated_prompt": gen_prompt,
                "message": f"🎨 [{clip_no}/{total}] Generating {style} visual for '{term}'…",
            })

            try:
                # Generate at 720p — the highest resolution grok-imagine-video
                # supports natively (its only options are 480p / 720p).
                response = client.video.generate(
                    prompt=_grok_prompt_no_audio(gen_prompt),
                    model="grok-imagine-video",
                    duration=6,
                    aspect_ratio="16:9",
                    resolution="720p",
                )

                if cancel_evt.is_set():
                    cancelled = True
                    break

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_term = "".join(
                    c if c.isalnum() else "_" for c in term)[:30]
                filename = f"grok_{timestamp}_{i}_{style}_{safe_term}.mp4"
                local_path = out_dir / filename

                with requests.get(response.url, stream=True, timeout=180, verify=certifi.where()) as dl_resp:
                    dl_resp.raise_for_status()
                    with open(local_path, "wb") as out_file:
                        for chunk in dl_resp.iter_content(chunk_size=8192):
                            if cancel_evt.is_set():
                                break
                            if chunk:
                                out_file.write(chunk)

                if cancel_evt.is_set():
                    # Partial download — drop the incomplete file.
                    try:
                        if local_path.exists():
                            local_path.unlink()
                    except Exception:
                        pass
                    cancelled = True
                    break

                # Grok caps at 720p; upscale to full 1080p (best-effort, via
                # ffmpeg) so clips drop crisply onto a 1080p timeline. Falls back
                # to the 720p original if ffmpeg is unavailable or fails.
                upscaled = _upscale_video_to_1080p(local_path)

                video_entry = {
                    "timecode": timecode,
                    "search_term": term,
                    "style": style,
                    "description": desc,
                    "generated_prompt": gen_prompt,
                    "resolution": "1080p" if upscaled else "720p",
                    "url": response.url,
                    "filename": str(local_path),
                }
                # Persist to Azure under the permanent Script-ID so the video is
                # restored next time this script is loaded (survives refresh). The
                # durable blob SAS URL replaces the short-lived xAI url for playback.
                blob_url = _persist_grok_video(
                    script_id, local_path, video_entry)
                if blob_url:
                    video_entry["url"] = blob_url
                    video_entry["persisted"] = True
                videos.append(video_entry)

                _grok_emit(session_id, {
                    "type": "video_ready",
                    "index": i, "current": clip_no, "total": total,
                    "video": video_entry,
                    "message": f"✅ [{clip_no}/{total}] Saved {style} '{term}' → {local_path}",
                })
            except Exception as row_err:
                failures.append({
                    "index": i,
                    "timecode": timecode,
                    "search_term": term,
                    "style": style,
                    "error": str(row_err),
                })
                _grok_emit(session_id, {
                    "type": "video_failed",
                    "index": i, "current": clip_no, "total": total,
                    "search_term": term, "style": style, "timecode": timecode,
                    "error": str(row_err),
                    "message": f"❌ [{clip_no}/{total}] Failed {style} '{term}': {row_err}",
                })

        if cancelled:
            break

    grok_video_results[session_id] = {
        "videos": videos,
        "failures": failures,
        "cancelled": cancelled,
        "output_dir": str(out_dir),
    }

    final_msg = (
        f"🛑 Cancelled — kept {len(videos)} of {total} videos"
        if cancelled
        else f"✅ Grok videos complete: {len(videos)}/{total} (failed: {len(failures)})"
    )
    _grok_emit(session_id, {
        "type": "done",
        "cancelled": cancelled,
        "videos": videos,
        "failures": failures,
        "generated_count": len(videos),
        "failed_count": len(failures),
        "total_requested": total,
        "output_dir": str(out_dir),
        "message": final_msg,
    })


@app.route("/api/grok/generate-selected", methods=["POST"])
def grok_generate_selected_videos():
    """Start background Grok video generation for selected B-roll rows. Streams via SSE."""
    try:
        data = request.get_json() or {}
        selected_rows = data.get("selected_rows") or []
        api_key = (data.get("api_key") or "").strip(
        ) or os.getenv("XAI_API_KEY", "").strip()
        script_title = (data.get("script_title") or "").strip()
        # Grok videos are tied to the permanent Script-ID so they accumulate
        # across every processing version of the script.
        script_id = (data.get("script_id") or "").strip()
        session_id = (data.get("session_id")
                      or "").strip() or str(uuid.uuid4())

        if not api_key:
            return jsonify({"success": False, "error": "Grok API key is required"}), 400
        if not selected_rows:
            return jsonify({"success": False, "error": "No rows selected"}), 400

        # Reset per-session state
        grok_video_cancel_events[session_id] = _threading.Event()
        grok_video_streams[session_id] = _queue.Queue()
        grok_video_results.pop(session_id, None)

        thread = _threading.Thread(
            target=_grok_generate_worker,
            args=(session_id, selected_rows, api_key, script_title, script_id),
            daemon=True,
        )
        thread.start()

        return jsonify({
            "success": True,
            "session_id": session_id,
            "total": len(selected_rows),
            "stream_url": f"/api/grok/progress/{session_id}",
            "cancel_url": f"/api/grok/cancel/{session_id}",
        })
    except Exception as e:
        logger.error(f"❌ Grok selected generation failed to start: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/grok/progress/<session_id>")
def grok_progress_stream(session_id):
    """SSE stream of per-video progress events for a Grok generation session."""
    q = grok_video_streams.get(session_id)
    if q is None:
        return "Session not found", 404

    def generate():
        try:
            while True:
                try:
                    payload = q.get(timeout=300)
                except _queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(payload)}\n\n"
                if payload.get("type") == "done":
                    break
        finally:
            # Leave results in grok_video_results for inspection; clean stream + cancel event.
            grok_video_streams.pop(session_id, None)
            grok_video_cancel_events.pop(session_id, None)

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


@app.route("/api/grok/cancel/<session_id>", methods=["POST"])
def grok_cancel(session_id):
    """Signal an in-flight Grok generation to stop after the current step. Already-saved videos are kept."""
    try:
        evt = grok_video_cancel_events.get(session_id)
        if evt is None:
            evt = _threading.Event()
            grok_video_cancel_events[session_id] = evt
        evt.set()
        logger.info(
            f"🛑 Grok video generation cancel requested for session {session_id}")
        return jsonify({"success": True, "session_id": session_id})
    except Exception as e:
        logger.error(f"❌ Failed to cancel Grok generation: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/test_word")
def test_word_page():
    """Test page for Word export functionality"""
    return render_template("test_word_export.html")


@app.route("/export_word", methods=["POST"])
def export_word():
    """Export script content to Word document"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"})

        script_content = data.get("script_content", "")
        title = data.get("title", "AI Script")

        if not script_content:
            return jsonify({"success": False, "error": "No script content to export"})

        logger.info(
            f"📄 Exporting script to Word: {len(script_content)} characters")

        # Import Word processing libraries directly
        try:
            from docx import Document
            from docx.shared import Inches, Pt
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            logger.info("✅ Word processing libraries imported successfully")
        except ImportError as e:
            logger.error(f"❌ Failed to import docx libraries: {e}")
            return jsonify({"success": False, "error": "python-docx not available"})

        # Create temporary file path
        import tempfile
        temp_dir = Path(tempfile.gettempdir())
        temp_file = temp_dir / f"script_{uuid.uuid4().hex[:8]}.docx"

        # Convert script to Word document directly
        try:
            logger.info("📝 Creating Word document...")

            # Create a new Word document
            doc = Document()

            # Process the script content line by line
            lines = script_content.split('\n')
            logger.info(f"🔍 Processing {len(lines)} lines")

            i = 0
            while i < len(lines):
                line = lines[i].rstrip()

                # Skip empty lines
                if not line:
                    i += 1
                    continue

                # Handle markdown tables - detect header row with pipes
                if '|' in line:
                    # Look ahead to check if next line is a separator
                    is_table = False
                    if i + 1 < len(lines):
                        next_line = lines[i + 1].rstrip()
                        # Check if next line is a table separator (pipes, dashes, colons, spaces)
                        if '|' in next_line and all(c in '|-: \t' for c in next_line.replace('|', '')):
                            is_table = True
                    if not is_table:
                        # Not a table — treat as a regular paragraph and advance.
                        # (Lines like "Audience: [a | b | c]" used to cause an
                        # infinite loop because i was never incremented here.)
                        paragraph = doc.add_paragraph()
                        paragraph.add_run(line)
                        i += 1
                        continue
                    # This is a markdown table!
                    logger.info(f"📊 Detected table at line {i}")

                    # Collect header row
                    header_line = line
                    i += 1  # Skip to separator line
                    i += 1  # Skip separator, move to first data row

                    # Collect all data rows (lines with pipes)
                    data_lines = []
                    while i < len(lines):
                        data_line = lines[i].rstrip()
                        if '|' in data_line:
                            data_lines.append(data_line)
                            i += 1
                        else:
                            break

                    # Parse the table
                    # Split on pipes and clean up
                    header_cells = [cell.strip()
                                    for cell in header_line.split('|')]
                    # Remove empty cells from start/end if table has leading/trailing pipes
                    if header_cells and not header_cells[0]:
                        header_cells = header_cells[1:]
                    if header_cells and not header_cells[-1]:
                        header_cells = header_cells[:-1]

                    # Parse data rows
                    data_rows = []
                    for data_line in data_lines:
                        cells = [cell.strip()
                                 for cell in data_line.split('|')]
                        # Remove empty cells from start/end
                        if cells and not cells[0]:
                            cells = cells[1:]
                        if cells and not cells[-1]:
                            cells = cells[:-1]
                        if cells:  # Only add non-empty rows
                            data_rows.append(cells)

                    # Create Word table
                    if header_cells and data_rows:
                        logger.info(
                            f"📊 Creating Word table: {len(header_cells)} columns, {len(data_rows)} rows")

                        table = doc.add_table(
                            rows=1 + len(data_rows), cols=len(header_cells))
                        table.style = 'Light Grid Accent 1'

                        # Add headers
                        for col_idx, header in enumerate(header_cells):
                            if col_idx < len(table.rows[0].cells):
                                cell = table.rows[0].cells[col_idx]
                                cell.text = header
                                # Make header bold
                                for paragraph in cell.paragraphs:
                                    for run in paragraph.runs:
                                        run.bold = True

                        # Add data rows
                        for row_idx, row_data in enumerate(data_rows, start=1):
                            for col_idx, cell_text in enumerate(row_data):
                                if col_idx < len(header_cells) and row_idx < len(table.rows):
                                    table.rows[row_idx].cells[col_idx].text = cell_text

                        # Add spacing after table
                        doc.add_paragraph()
                        logger.info(f"✅ Table created successfully")
                    else:
                        logger.warning(
                            f"⚠️ Table parsing failed: headers={len(header_cells)}, rows={len(data_rows)}")

                    continue

                # Handle horizontal rules (---)
                elif line.strip() in ['---', '___', '***']:
                    doc.add_paragraph('_' * 50)
                    i += 1
                    continue

                # Handle headers (lines starting with #)
                elif line.startswith('#'):
                    level = len(line) - len(line.lstrip('#'))
                    text = line.lstrip('#').strip()

                    if level == 1:  # Main title
                        paragraph = doc.add_heading(text, level=1)
                        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    elif level == 2:  # Chapter/Section
                        paragraph = doc.add_heading(text, level=2)
                    else:  # Sub-sections
                        paragraph = doc.add_heading(text, level=3)
                    i += 1
                    continue

                # Handle bold text (**text**)
                elif '**' in line:
                    paragraph = doc.add_paragraph()
                    parts = line.split('**')
                    for idx, part in enumerate(parts):
                        if idx % 2 == 0:  # Normal text
                            if part:
                                paragraph.add_run(part)
                        else:  # Bold text
                            if part:
                                run = paragraph.add_run(part)
                                run.bold = True
                    i += 1
                    continue

                # Handle visual cues (lines with 🎬 emoji or [Visual:])
                elif ('🎬' in line or '[Visual:' in line or
                      (line.startswith('[') and ']' in line)):
                    paragraph = doc.add_paragraph()
                    run = paragraph.add_run(line)
                    run.italic = True
                    paragraph.space_before = Pt(6)
                    paragraph.space_after = Pt(6)
                    i += 1
                    continue

                # Regular paragraph
                else:
                    paragraph = doc.add_paragraph()
                    paragraph.add_run(line)
                    i += 1

            # Save document to temporary file
            doc.save(str(temp_file))
            logger.info(f"💾 Word document saved to: {temp_file}")

            if not temp_file.exists():
                return jsonify({"success": False, "error": "Failed to create Word document"})

            # Optionally also copy into the run's broll/ folder so the user has
            # a per-project archived copy of the B-roll table docx.
            if data.get("save_to_broll_dir"):
                try:
                    archive_title = data.get("script_title") or title
                    archive_root = _get_run_output_dir(
                        archive_title, create=True)
                    archive_dir = archive_root / "broll"
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    archive_path = archive_dir / f"{title}.docx"
                    import shutil
                    shutil.copy2(str(temp_file), str(archive_path))
                    logger.info(
                        f"💾 Archived broll docx → {archive_path}")
                except Exception as arc_err:
                    logger.warning(
                        f"⚠️ Could not archive broll docx: {arc_err}")

            # Read the file and return as binary response
            with open(temp_file, 'rb') as f:
                file_content = f.read()

            # Clean up temp file
            temp_file.unlink()

            logger.info(f"✅ Word export successful: {len(file_content)} bytes")

            # Return file as binary response
            response = make_response(file_content)
            response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            response.headers['Content-Disposition'] = f'attachment; filename="{title}.docx"'
            return response

        except Exception as e:
            logger.error(f"❌ Word conversion failed: {e}")
            return jsonify({"success": False, "error": f"Word conversion failed: {str(e)}"})

    except Exception as e:
        error_msg = f"Export to Word failed: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return jsonify({"success": False, "error": error_msg})


# ---------------------------------------------------------------------------
# YouTube Publishing (AI for Roz channel)
# ---------------------------------------------------------------------------

def _yt_uploads_dir() -> Path:
    """Working directory for browser-uploaded videos and thumbnails."""
    base = Path.home() / ".scriptcraft" / "youtube_uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _osascript_pick_file(prompt: str, types_clause: str = "") -> dict:
    """Show a macOS native file-open dialog and return the chosen path.

    ``types_clause`` is the literal AppleScript clause appended to the
    ``choose file`` command (e.g. ``of type {"mp4","mov"}``)."""
    import subprocess
    if sys.platform != "darwin":
        return {"success": False,
                "error": "Native file picker is only supported on macOS."}
    script = (
        'try\n'
        f'  set theFile to POSIX path of (choose file with prompt "{prompt}" {types_clause})\n'
        '  return theFile\n'
        'on error number -128\n'
        '  return "__CANCELLED__"\n'
        'end try'
    )
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=300, check=False
        )
    except Exception as ex:
        return {"success": False, "error": f"osascript failed: {ex}"}
    if out.returncode != 0:
        return {"success": False,
                "error": (out.stderr or "osascript error").strip()}
    path = (out.stdout or "").strip()
    if not path or path == "__CANCELLED__":
        return {"success": False, "cancelled": True}
    return {"success": True, "path": path}


@app.route("/api/youtube/generate-details-from-transcript", methods=["POST"])
def api_youtube_generate_details_from_transcript():
    """Generate YouTube upload-details markdown from a timestamped Whisper
    transcript and save it as .md + .docx in the chosen output directory.

    Body JSON:
        {
            "transcript_text":  "[00:00:00] line one\n[00:00:03] line two...",  (preferred)
            "transcript_path":  "/abs/path/to/transcript.md",  (alternative)
            "script_title":     "AI for Beginners",
            "output_dir":       "/abs/path/to/output",  (optional, default current)
            "target_audience":  "general",   (optional)
            "video_length":     "10 minutes" (optional)
        }

    Returns:
        {
          "success": true,
          "youtube_details_md": "<full markdown>",
          "saved_md_path": "...",
          "saved_docx_path": "..."  (may be null if python-docx unavailable)
        }
    """
    try:
        data = request.get_json(silent=True) or {}

        transcript_text = (data.get("transcript_text") or "").strip()
        transcript_path = (data.get("transcript_path") or "").strip()
        script_title = (data.get("script_title") or "").strip() or "Untitled Video"
        target_audience = (data.get("target_audience") or "general").strip() or "general"
        video_length = (data.get("video_length") or "").strip() or None

        # Load transcript text from file if not inlined
        if not transcript_text and transcript_path:
            try:
                p = Path(transcript_path).expanduser()
                if not p.exists():
                    return jsonify({"success": False, "error": f"transcript_path not found: {transcript_path}"}), 400
                suffix = p.suffix.lower()
                if suffix == ".docx":
                    # python-docx required for binary Word files
                    try:
                        from docx import Document  # type: ignore
                    except ImportError:
                        return jsonify({
                            "success": False,
                            "error": "python-docx is required to read .docx transcripts. Install with: pip install python-docx",
                        }), 400
                    try:
                        doc = Document(str(p))
                        parts = []
                        for para in doc.paragraphs:
                            if para.text:
                                parts.append(para.text)
                        # Tables can also contain transcript rows
                        for tbl in doc.tables:
                            for row in tbl.rows:
                                for cell in row.cells:
                                    if cell.text:
                                        parts.append(cell.text)
                        transcript_text = "\n".join(parts).strip()
                    except Exception as docx_err:
                        return jsonify({
                            "success": False,
                            "error": f"failed to extract text from .docx: {docx_err}",
                        }), 400
                else:
                    transcript_text = p.read_text(encoding="utf-8", errors="replace").strip()
            except Exception as read_err:
                return jsonify({"success": False, "error": f"failed to read transcript: {read_err}"}), 400

        if not transcript_text:
            return jsonify({"success": False, "error": "transcript_text or transcript_path is required"}), 400

        # Guard against binary blobs that slipped through (e.g. a .docx renamed
        # to .md). If >5% of the first 4 KB is non-printable, the file is
        # almost certainly not a readable transcript.
        sample = transcript_text[:4096]
        if sample:
            non_print = sum(1 for c in sample if c not in "\r\n\t" and (ord(c) < 32 or ord(c) == 127))
            if non_print / max(len(sample), 1) > 0.05:
                return jsonify({
                    "success": False,
                    "error": (
                        "Transcript file appears to be binary, not text. "
                        "If you picked a .docx, re-pick it (the loader now handles .docx natively). "
                        "If it's a .md or .txt, re-export it as UTF-8 plain text."
                    ),
                }), 400

        # Resolve output directory
        out_dir_raw = (data.get("output_dir") or "").strip()
        if out_dir_raw:
            output_dir = Path(out_dir_raw).expanduser()
        else:
            output_dir = _get_output_parent_dir()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as mkd_err:
            return jsonify({"success": False, "error": f"cannot create output_dir: {mkd_err}"}), 400

        # Call the existing YouTube details agent. The agent prompt already has
        # explicit rules for handling timestamped transcripts as chapter source.
        from linedrive_azure.agents import YouTubeUploadDetailsAgentClient
        agent = YouTubeUploadDetailsAgentClient()
        result = agent.generate_upload_details(
            script_content=transcript_text,
            script_title=script_title,
            target_audience=target_audience,
            video_length=video_length,
            primary_keywords=None,
            channel_focus=None,
            timeout=300,
        )
        if not result or not result.get("success"):
            err = (result or {}).get("error") or "agent returned no result"
            return jsonify({"success": False, "error": f"YouTube agent failed: {err}"}), 500

        details_md = (result.get("upload_details") or "").strip()
        if not details_md:
            return jsonify({"success": False, "error": "agent returned empty upload_details"}), 500

        # Refuse to write garbage to disk. A valid YouTube-details doc has
        # multiple "## " section headers; a refusal/empty response has none.
        if details_md.count("## ") < 3:
            return jsonify({
                "success": False,
                "error": (
                    "Agent returned a response without the expected markdown "
                    "sections (likely a content-filter refusal or truncation). "
                    f"First 300 chars: {details_md[:300]!r}. "
                    "Try renaming the video to remove ALL-CAPS words and re-run."
                ),
            }), 502

        # Safe filename stem
        safe_title = re.sub(r'[^A-Za-z0-9._-]+', '_', script_title).strip('_') or "youtube_details"
        md_path = output_dir / f"{safe_title}_youtube_details.md"
        md_path.write_text(details_md, encoding="utf-8")

        docx_path_str = None
        try:
            from docx import Document  # python-docx
            doc = Document()
            doc.add_heading(f"YouTube Details: {script_title}", level=1)
            for line in details_md.splitlines():
                doc.add_paragraph(line)
            docx_path = output_dir / f"{safe_title}_youtube_details.docx"
            doc.save(str(docx_path))
            docx_path_str = str(docx_path)
        except Exception as docx_err:
            logger.warning(f"⚠️ Could not save YouTube details .docx: {docx_err}")

        logger.info(
            f"📺 YouTube details generated from transcript ({len(details_md)} chars) → {md_path}")
        return jsonify({
            "success": True,
            "youtube_details_md": details_md,
            "saved_md_path": str(md_path),
            "saved_docx_path": docx_path_str,
        })
    except Exception as e:
        logger.error(f"❌ /api/youtube/generate-details-from-transcript failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


def _osascript_pick_folder(prompt: str) -> dict:
    """Show a macOS native folder-choose dialog and return the chosen path."""
    import subprocess
    if sys.platform != "darwin":
        return {"success": False,
                "error": "Native folder picker is only supported on macOS."}
    script = (
        'try\n'
        f'  set theFolder to POSIX path of (choose folder with prompt "{prompt}")\n'
        '  return theFolder\n'
        'on error number -128\n'
        '  return "__CANCELLED__"\n'
        'end try'
    )
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=300, check=False
        )
    except Exception as ex:
        return {"success": False, "error": f"osascript failed: {ex}"}
    if out.returncode != 0:
        return {"success": False,
                "error": (out.stderr or "osascript error").strip()}
    path = (out.stdout or "").strip()
    if not path or path == "__CANCELLED__":
        return {"success": False, "cancelled": True}
    return {"success": True, "path": path}


@app.route("/api/youtube/pick-output-dir", methods=["GET"])
def api_youtube_pick_output_dir():
    """Native folder picker for the YouTube pipeline output directory."""
    res = _osascript_pick_folder("Choose output directory for YouTube details")
    if not res.get("success"):
        return jsonify(res), (200 if res.get("cancelled") else 500)
    return jsonify({"success": True, "path": res["path"]})


@app.route("/api/youtube/pick-transcript", methods=["GET"])
def api_youtube_pick_transcript():
    """Native file picker for a Whisper-style transcript (.md / .txt / .docx)."""
    res = _osascript_pick_file(
        "Choose a transcript file (.md / .txt / .docx)",
        'of type {"md","markdown","txt","docx"}'
    )
    if not res.get("success"):
        return jsonify(res), (200 if res.get("cancelled") else 500)
    p = Path(res["path"])
    if not p.exists() or not p.is_file():
        return jsonify({"success": False, "error": f"Selected file not found: {p}"}), 400
    return jsonify({"success": True, "path": str(p), "filename": p.name})


@app.route("/api/youtube/pick-video-path", methods=["GET"])
def youtube_pick_video_path():
    """Open a native OS file dialog and return the selected video path
    without uploading anything. The video must remain on the local disk
    where the YouTube uploader can read it directly."""
    res = _osascript_pick_file(
        "Choose the finished video to publish to YouTube",
        'of type {"mp4","mov","m4v","mkv","webm"}'
    )
    if not res.get("success"):
        return jsonify(res), (200 if res.get("cancelled") else 500)
    p = Path(res["path"])
    if not p.exists() or not p.is_file():
        return jsonify({"success": False,
                        "error": f"Selected file not found: {p}"}), 400
    return jsonify({
        "success": True,
        "path": str(p),
        "filename": p.name,
        "size_bytes": p.stat().st_size,
    })


@app.route("/api/youtube/pick-thumbnail-path", methods=["GET"])
def youtube_pick_thumbnail_path():
    """Open a native OS file dialog and return the selected thumbnail
    path. We validate extension and 2 MB YouTube limit here."""
    res = _osascript_pick_file(
        "Choose a thumbnail image (PNG or JPG, under 2 MB)",
        'of type {"png","jpg","jpeg"}'
    )
    if not res.get("success"):
        return jsonify(res), (200 if res.get("cancelled") else 500)
    p = Path(res["path"])
    if not p.exists() or not p.is_file():
        return jsonify({"success": False,
                        "error": f"Selected file not found: {p}"}), 400
    if p.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        return jsonify({"success": False,
                        "error": f"Unsupported extension {p.suffix}"}), 400
    size = p.stat().st_size
    if size > 2 * 1024 * 1024:
        return jsonify({"success": False,
                        "error": "Thumbnail exceeds YouTube's 2 MB limit."
                        }), 400
    return jsonify({
        "success": True,
        "path": str(p),
        "filename": p.name,
        "size_bytes": size,
    })


@app.route("/api/youtube/pick-srt-path", methods=["GET"])
def youtube_pick_srt_path():
    """Open a native OS file dialog and return the selected .srt caption
    file path. Used by the Publish dialog so the user can attach an
    existing SRT (e.g. one exported alongside the DaVinci render) as
    the YouTube caption track instead of generating a new one."""
    res = _osascript_pick_file(
        "Choose an existing .srt caption file",
        'of type {"srt"}'
    )
    if not res.get("success"):
        return jsonify(res), (200 if res.get("cancelled") else 500)
    p = Path(res["path"])
    if not p.exists() or not p.is_file():
        return jsonify({"success": False,
                        "error": f"Selected file not found: {p}"}), 400
    if p.suffix.lower() != ".srt":
        return jsonify({"success": False,
                        "error": f"Unsupported extension {p.suffix} (need .srt)"}), 400
    return jsonify({
        "success": True,
        "path": str(p),
        "filename": p.name,
        "size_bytes": p.stat().st_size,
    })


@app.route("/api/youtube/upload-video-file", methods=["POST"])
def youtube_upload_video_file():
    """Receive a video file from the browser and save it to a working
    directory so the publisher can upload it by path."""
    try:
        from werkzeug.utils import secure_filename
        f = request.files.get("file")
        if not f:
            return jsonify({"success": False, "error": "no file"}), 400
        safe_name = secure_filename(f.filename or "video.mp4") or "video.mp4"
        target = _yt_uploads_dir() / safe_name
        f.save(str(target))
        return jsonify({
            "success": True,
            "path": str(target),
            "filename": safe_name,
            "size_bytes": target.stat().st_size,
        })
    except Exception as e:
        logger.error(f"❌ youtube_upload_video_file error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/youtube/upload-thumbnail", methods=["POST"])
def youtube_upload_thumbnail():
    """Receive a thumbnail image from the browser and save it locally."""
    try:
        from werkzeug.utils import secure_filename
        f = request.files.get("file")
        if not f:
            return jsonify({"success": False, "error": "no file"}), 400
        safe_name = secure_filename(f.filename or "thumbnail.png") \
            or "thumbnail.png"
        ext = Path(safe_name).suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg"}:
            return jsonify({"success": False,
                            "error": f"unsupported extension {ext}"}), 400
        target = _yt_uploads_dir() / safe_name
        f.save(str(target))
        if target.stat().st_size > 2 * 1024 * 1024:
            target.unlink(missing_ok=True)
            return jsonify({"success": False,
                            "error": "Thumbnail exceeds YouTube's 2 MB limit."
                            }), 400
        return jsonify({
            "success": True,
            "path": str(target),
            "filename": safe_name,
            "size_bytes": target.stat().st_size,
        })
    except Exception as e:
        logger.error(f"❌ youtube_upload_thumbnail error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/youtube/auth-status", methods=["GET"])
def youtube_auth_status():
    try:
        import youtube_publisher as yp
        return jsonify({
            "success": True,
            "has_client_secret": yp.has_client_secret(),
            "is_authorized": yp.is_authorized(),
            "client_secret_path": str(yp.CLIENT_SECRET_PATH),
            "token_path": str(yp.TOKEN_PATH),
            "default_video_dir": str(yp.DEFAULT_VIDEO_DIR),
        })
    except Exception as e:
        logger.error(f"❌ youtube_auth_status error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/youtube/recent-videos", methods=["GET"])
def youtube_recent_videos():
    """List recently-modified video files in the configured Final dir."""
    try:
        import youtube_publisher as yp
        directory = request.args.get("dir") or None
        base = Path(directory).expanduser() if directory else None
        videos = yp.list_recent_videos(directory=base)
        return jsonify({
            "success": True,
            "videos": videos,
            "directory": str(base or yp.DEFAULT_VIDEO_DIR),
        })
    except Exception as e:
        logger.error(f"❌ youtube_recent_videos error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/youtube/published-videos", methods=["GET"])
def youtube_published_videos():
    """List the @AIwithRoz channel's published (uploaded) videos, newest first.

    Powers the "Promote a published video" browser in the Post to X composer so
    any older episode can be turned into a promo at any time. Returns an empty
    list (not an error) when YouTube isn't authorized yet, so the composer can
    show a friendly hint instead of failing.
    """
    try:
        import youtube_publisher as yp
        if not yp.is_authorized():
            return jsonify({
                "success": True,
                "authorized": False,
                "videos": [],
                "message": ("Connect the YouTube account first (Publish tab) "
                            "to browse published videos."),
            })
        try:
            max_results = int(request.args.get("max", 100))
        except (TypeError, ValueError):
            max_results = 100
        max_results = max(1, min(max_results, 200))
        videos = yp.list_published_videos(max_results=max_results)
        return jsonify({
            "success": True,
            "authorized": True,
            "videos": videos,
        })
    except Exception as e:
        logger.error(f"❌ youtube_published_videos error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/youtube/thumbnails", methods=["GET"])
def youtube_thumbnails():
    """List thumbnail images in the ``thumbnails`` folder next to a
    selected video (e.g. ~/Dev/Videos/Edited/Final/projectX/thumbnails)."""
    try:
        import youtube_publisher as yp
        video_path = (request.args.get("video_path") or "").strip()
        if not video_path:
            return jsonify({"success": False,
                            "error": "video_path is required"}), 400
        thumbs = yp.list_thumbnails_for_video(video_path)
        # Build serving URLs the UI can drop straight into <img src>.
        for t in thumbs:
            t["url"] = ("/api/youtube/thumbnail-image?path="
                        + urllib.parse.quote(t["path"], safe=""))
        return jsonify({
            "success": True,
            "thumbnails": thumbs,
            "directory": str(Path(video_path).expanduser().parent
                              / "thumbnails"),
        })
    except Exception as e:
        logger.error(f"❌ youtube_thumbnails error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/youtube/thumbnail-image", methods=["GET"])
def youtube_thumbnail_image():
    """Serve a thumbnail image file from disk. Restricted to images that
    live inside a ``thumbnails`` directory under the configured Final
    video root, so this cannot be used to read arbitrary files."""
    try:
        import youtube_publisher as yp
        raw = request.args.get("path", "")
        if not raw:
            return jsonify({"success": False,
                            "error": "path is required"}), 400
        target = Path(raw).expanduser().resolve()
        if not target.exists() or not target.is_file():
            return jsonify({"success": False,
                            "error": "file not found"}), 404
        if target.suffix.lower() not in yp.THUMBNAIL_EXTS:
            return jsonify({"success": False,
                            "error": "unsupported file type"}), 400
        # Containment check: must live under DEFAULT_VIDEO_DIR and inside
        # a directory literally named "thumbnails".
        root = yp.DEFAULT_VIDEO_DIR.expanduser().resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return jsonify({"success": False,
                            "error": "path outside allowed root"}), 403
        if "thumbnails" not in {p.name for p in target.parents}:
            return jsonify({"success": False,
                            "error": "path is not in a thumbnails dir"}), 403
        return send_file(str(target), mimetype=None, conditional=True)
    except Exception as e:
        logger.error(f"❌ youtube_thumbnail_image error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/youtube/local-preview", methods=["GET"])
def youtube_local_preview():
    """Serve any image or video file from the user's home directory so
    the publish modal can preview the selected video and thumbnail.
    Restricted to $HOME and to known media extensions to prevent
    arbitrary disk reads."""
    try:
        raw = request.args.get("path", "")
        if not raw:
            return jsonify({"success": False,
                            "error": "path is required"}), 400
        target = Path(raw).expanduser().resolve()
        if not target.exists() or not target.is_file():
            return jsonify({"success": False,
                            "error": "file not found"}), 404
        # Containment: must live somewhere under the user's home dir.
        home = Path.home().resolve()
        try:
            target.relative_to(home)
        except ValueError:
            return jsonify({"success": False,
                            "error": "path outside home directory"}), 403
        ext = target.suffix.lower()
        media_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif",
                      ".mp4", ".mov", ".m4v", ".mkv", ".webm"}
        if ext not in media_exts:
            return jsonify({"success": False,
                            "error": f"unsupported file type {ext}"}), 400
        mimetype = None
        if ext in {".mp4", ".m4v"}:
            mimetype = "video/mp4"
        elif ext == ".mov":
            mimetype = "video/quicktime"
        elif ext == ".webm":
            mimetype = "video/webm"
        elif ext == ".mkv":
            mimetype = "video/x-matroska"
        elif ext in {".jpg", ".jpeg"}:
            mimetype = "image/jpeg"
        elif ext == ".png":
            mimetype = "image/png"
        elif ext == ".webp":
            mimetype = "image/webp"
        elif ext == ".gif":
            mimetype = "image/gif"
        return send_file(str(target), mimetype=mimetype, conditional=True)
    except Exception as e:
        logger.error(f"❌ youtube_local_preview error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/youtube/preview-metadata", methods=["POST"])
def youtube_preview_metadata():
    """Parse the YouTube details markdown and return the metadata that
    will be sent to YouTube — lets the UI show a final review."""
    try:
        import youtube_publisher as yp
        data = request.get_json(silent=True) or {}
        md = data.get("youtube_details_md", "")
        if not md.strip():
            return jsonify({"success": False,
                            "error": "youtube_details_md is required"}), 400
        meta = yp.parse_youtube_details_markdown(md)
        return jsonify({
            "success": True,
            "metadata": {
                "title": meta.title,
                "description": meta.description,
                "tags": meta.tags,
                "hashtags": meta.hashtags,
                "category_id": meta.category_id,
                "made_for_kids": meta.made_for_kids,
            },
        })
    except Exception as e:
        logger.error(f"❌ youtube_preview_metadata error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/youtube/reveal-path", methods=["POST"])
def youtube_reveal_path():
    """Open Finder with the given file selected so the user can drag
    the SRT into the YouTube Studio captions uploader."""
    try:
        data = request.get_json(silent=True) or {}
        p = (data.get("path") or "").strip()
        if not p:
            return jsonify({"success": False, "error": "path required"}), 400
        target = Path(p).expanduser()
        if not target.exists():
            return jsonify({"success": False,
                            "error": f"Not found: {target}"}), 400
        import subprocess
        subprocess.Popen(["open", "-R", str(target)])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/youtube/generate-srt", methods=["POST"])
def youtube_generate_srt():
    """Run whisper on the chosen video file and produce a .srt subtitle
    file the user can upload to YouTube. Does NOT touch the DaVinci
    timeline. Returns the absolute path of the .srt and a sibling URL
    the browser can use to download it."""
    try:
        data = request.get_json(silent=True) or {}
        video_path = (data.get("video_path") or "").strip()
        model = (data.get("model") or "medium").strip()
        language = (data.get("language") or "en").strip()
        if not video_path:
            return jsonify({"success": False,
                            "error": "video_path is required"}), 400
        src = Path(video_path).expanduser()
        if not src.exists() or not src.is_file():
            return jsonify({"success": False,
                            "error": f"Video file not found: {src}"}), 400

        whisper_bin = _find_whisper_cli()
        if not whisper_bin:
            return jsonify({
                "success": False,
                "error": "whisper CLI not found. Install with: "
                         "pip install openai-whisper",
            }), 500

        out_dir = src.parent / "captions"
        out_dir.mkdir(parents=True, exist_ok=True)

        import subprocess
        cmd = [
            whisper_bin, str(src),
            "--model", model,
            "--output_format", "srt",
            "--output_dir", str(out_dir),
            "--task", "transcribe",
            "--verbose", "False",
        ]
        if language:
            cmd += ["--language", language]
        logger.info(f"🎙️ Generating SRT: {' '.join(cmd)}")
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=60 * 60)
        if proc.returncode != 0:
            logger.error(f"❌ whisper SRT failed: {proc.stderr[:2000]}")
            return jsonify({"success": False,
                            "error": "whisper failed: "
                                     + (proc.stderr or proc.stdout)[-500:]}), 500

        srt_path = out_dir / (src.stem + ".srt")
        if not srt_path.exists():
            # Whisper may name it differently; pick newest .srt in out_dir.
            srts = sorted(out_dir.glob("*.srt"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
            if srts:
                srt_path = srts[0]
        if not srt_path.exists():
            return jsonify({"success": False,
                            "error": "SRT file was not produced"}), 500
        return jsonify({
            "success": True,
            "srt_path": str(srt_path),
            "filename": srt_path.name,
            "size_bytes": srt_path.stat().st_size,
        })
    except Exception as e:
        logger.error(f"❌ youtube_generate_srt error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/youtube/publish", methods=["POST"])
def youtube_publish():
    """Publish a finished video to YouTube. Returns immediately with
    an upload_id; poll /api/youtube/publish/status/<id> for progress."""
    try:
        import youtube_publisher as yp
        data = request.get_json(silent=True) or {}
        video_path = (data.get("video_path") or "").strip()
        md = data.get("youtube_details_md", "")
        privacy = (data.get("privacy_status") or "private").lower()
        notify = bool(data.get("notify_subscribers", True))
        # Optional manual overrides from the review modal.
        overrides = data.get("overrides") or {}

        if not video_path:
            return jsonify({"success": False,
                            "error": "video_path is required"}), 400
        if not md.strip() and not overrides.get("title"):
            return jsonify({"success": False,
                            "error": "youtube_details_md or overrides.title required"}), 400
        # We never publish publicly from this app — going public must be a
        # manual action in YouTube Studio.
        ALLOWED_PRIVACY = {"private", "unlisted"}
        if privacy not in ALLOWED_PRIVACY:
            return jsonify({"success": False,
                            "error": f"privacy_status must be one of {sorted(ALLOWED_PRIVACY)} "
                                     f"(public uploads must be toggled in YouTube Studio)"}), 400

        path = Path(video_path).expanduser()
        if not path.exists() or not path.is_file():
            return jsonify({"success": False,
                            "error": f"Video file not found: {path}"}), 400

        if not yp.has_client_secret():
            return jsonify({
                "success": False,
                "error": "Missing OAuth client secret",
                "setup_required": True,
                "client_secret_path": str(yp.CLIENT_SECRET_PATH),
            }), 400

        meta = yp.parse_youtube_details_markdown(md) if md.strip() else \
            yp.YouTubeMetadata(title=overrides.get("title", "Untitled"),
                               description=overrides.get("description", ""))
        # Apply overrides from the review modal (if user edited fields).
        if overrides.get("title"):
            meta.title = overrides["title"]
        if overrides.get("description"):
            meta.description = overrides["description"]
        if "tags" in overrides and isinstance(overrides["tags"], list):
            meta.tags = [str(t).strip() for t in overrides["tags"] if str(t).strip()]
        if "hashtags" in overrides and isinstance(overrides["hashtags"], list):
            meta.hashtags = [str(h).strip() for h in overrides["hashtags"] if str(h).strip()]
        if overrides.get("category_id"):
            meta.category_id = str(overrides["category_id"])
        if "made_for_kids" in overrides:
            meta.made_for_kids = bool(overrides["made_for_kids"])
        # Newer fields (synthetic media, language, recording date, embed).
        if "contains_synthetic_media" in overrides:
            meta.contains_synthetic_media = bool(
                overrides["contains_synthetic_media"])
        if overrides.get("default_language"):
            meta.default_language = str(overrides["default_language"])
        if overrides.get("default_audio_language"):
            meta.default_audio_language = str(overrides["default_audio_language"])
        if overrides.get("recording_date"):
            meta.recording_date = str(overrides["recording_date"])
        if "embeddable" in overrides:
            meta.embeddable = bool(overrides["embeddable"])
        meta.privacy_status = privacy

        # Optional thumbnail.
        thumbnail_path = (data.get("thumbnail_path") or "").strip() or None
        if thumbnail_path:
            tp = Path(thumbnail_path).expanduser()
            if not tp.exists() or not tp.is_file():
                return jsonify({"success": False,
                                "error": f"Thumbnail file not found: {tp}"}), 400
            if tp.suffix.lower() not in yp.THUMBNAIL_EXTS:
                return jsonify({
                    "success": False,
                    "error": f"Unsupported thumbnail extension {tp.suffix}. "
                             f"Allowed: {sorted(yp.THUMBNAIL_EXTS)}"
                }), 400
            if tp.stat().st_size > yp.MAX_THUMBNAIL_BYTES:
                return jsonify({
                    "success": False,
                    "error": f"Thumbnail is larger than YouTube's 2 MB limit: {tp}"
                }), 400
            thumbnail_path = str(tp)

        # Optional playlists to add the video to after upload.
        raw_pls = data.get("playlist_ids") or []
        if not isinstance(raw_pls, list):
            return jsonify({"success": False,
                            "error": "playlist_ids must be a list"}), 400
        playlist_ids = [str(p).strip() for p in raw_pls if str(p).strip()]

        # Optional existing .srt caption track (uploaded via captions.insert).
        srt_path = (data.get("srt_path") or "").strip() or None
        if srt_path:
            sp = Path(srt_path).expanduser()
            if not sp.exists() or not sp.is_file():
                return jsonify({"success": False,
                                "error": f"SRT caption file not found: {sp}"}), 400
            if sp.suffix.lower() != ".srt":
                return jsonify({"success": False,
                                "error": f"Caption file must be .srt (got {sp.suffix})"}), 400
            srt_path = str(sp)
        srt_language = (data.get("srt_language") or "en").strip() or "en"
        srt_track_name = (data.get("srt_track_name") or "English").strip() or "English"

        upload_id = str(uuid.uuid4())

        def _worker():
            try:
                yp.upload_video(str(path), meta, upload_id,
                                notify_subscribers=notify,
                                thumbnail_path=thumbnail_path,
                                playlist_ids=playlist_ids,
                                srt_path=srt_path,
                                srt_language=srt_language,
                                srt_track_name=srt_track_name)
            except Exception as ex:
                logger.error(f"❌ YouTube upload failed: {ex}")
                # The publisher already records error state, but ensure
                # we have a final status entry even for setup errors.
                from youtube_publisher import _set_state
                _set_state(upload_id, status="error", error=str(ex))

        _threading.Thread(target=_worker, daemon=True).start()

        return jsonify({
            "success": True,
            "upload_id": upload_id,
            "video_path": str(path),
            "filesize_bytes": path.stat().st_size,
            "metadata_preview": {
                "title": meta.title,
                "tags_count": len(meta.tags),
                "hashtags_count": len(meta.hashtags),
                "category_id": meta.category_id,
                "privacy_status": meta.privacy_status,
                "made_for_kids": meta.made_for_kids,
                "thumbnail_path": thumbnail_path,
                "srt_path": srt_path,
            },
        })
    except Exception as e:
        logger.error(f"❌ youtube_publish error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/youtube/playlists", methods=["GET"])
def youtube_list_playlists():
    """Return all playlists owned by the authorized channel so the UI
    can render a picker. Triggers OAuth on first call (same as publish)."""
    try:
        import youtube_publisher as yp
        if not yp.has_client_secret():
            return jsonify({
                "success": False,
                "error": "Missing OAuth client secret",
                "setup_required": True,
                "client_secret_path": str(yp.CLIENT_SECRET_PATH),
            }), 400
        playlists = yp.list_my_playlists()
        return jsonify({"success": True, "playlists": playlists})
    except Exception as e:
        logger.error(f"❌ youtube_list_playlists error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/youtube/publish/status/<upload_id>", methods=["GET"])
def youtube_publish_status(upload_id):
    """Poll endpoint for upload progress."""
    try:
        import youtube_publisher as yp
        state = yp.get_upload_status(upload_id)
        if state is None:
            return jsonify({"success": False,
                            "error": "Unknown upload_id"}), 404
        return jsonify({"success": True, "state": state})
    except Exception as e:
        logger.error(f"❌ youtube_publish_status error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/test-thumbnails")
def test_thumbnails():
    """Test page to view thumbnail gallery with existing thumbnails"""
    try:
        thumbnail_dir = Path.home() / "Dev" / "Thumbnails"

        # Get all PNG files
        if thumbnail_dir.exists():
            png_files = list(thumbnail_dir.glob("*.png"))
            # Take the most recent 6 files
            png_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            png_files = png_files[:6]

            # Create thumbnail data
            thumbnails = []
            emotions = ["ANGRY", "SHOCKED", "SCARED",
                        "EXCITED", "SKEPTICAL", "DETERMINED"]
            for i, file_path in enumerate(png_files):
                thumbnails.append({
                    "emotion": emotions[i] if i < len(emotions) else f"VARIANT_{i+1}",
                    "text": f"Test thumbnail {i+1}",
                    "filename": file_path.name
                })

            return render_template("test_thumbnails.html", thumbnails=thumbnails)
        else:
            return "Thumbnail directory not found", 404
    except Exception as e:
        return f"Error: {str(e)}", 500


@app.route("/thumbnail-test")
def thumbnail_test():
    """Interactive thumbnail generation test page"""
    return render_template("thumbnail_test.html")


def _thumbnail_test_worker(session_id, topic, headlines, variations_per_option):
    """Background worker: generates test thumbnails and streams progress events."""
    q = thumbnail_test_streams.get(session_id)

    def _emit(event_type, **kwargs):
        if q is None:
            return
        payload = {"type": event_type, **kwargs, "ts": time.time()}
        try:
            q.put(payload)
        except Exception:
            pass

    def _log(msg):
        print(msg)
        _emit("log", message=str(msg))

    try:
        _log(f"🎬 Generating thumbnails for: {topic}")
        if headlines:
            _log(f"🏷️ Hooks ({len(headlines)}): {headlines}")
        if variations_per_option:
            _log(f"🔢 Variations per hook: {variations_per_option}")

        from tools.media.emotional_thumbnail_generator import (
            EmotionalThumbnailGenerator,
        )

        thumbnail_gen = EmotionalThumbnailGenerator()
        _log(f"✅ Generator initialized")
        _log(f"   Template: {thumbnail_gen.template_path}")
        _log(f"   Output:   {thumbnail_gen.output_dir}")

        thumb_cancel_evt = _threading.Event()
        thumbnail_cancel_events[session_id] = thumb_cancel_evt

        thumbnail_results = thumbnail_gen.generate_all_thumbnails(
            script_title=topic,
            script_content="Test script content",
            youtube_upload_details=None,
            headline_options=headlines or None,
            variations_per_option=variations_per_option,
            progress_callback=_log,
            cancel_check=thumb_cancel_evt.is_set,
        )

        if thumbnail_results and thumbnail_results.get("variations"):
            variations = thumbnail_results["variations"]
            output_dir = thumbnail_results.get("output_dir")
            _log(f"✅ Generated {len(variations)} thumbnails")
            if output_dir:
                _log(f"📁 Saved to: {output_dir}")

            thumbnail_test_results[session_id] = {
                "success": True,
                "thumbnails": variations,
                "output_dir": output_dir,
                "count": len(variations),
                "topic": topic,
            }
            _emit("done", success=True, thumbnails=variations,
                  output_dir=output_dir, count=len(variations),
                  download_url=f"/api/thumbnails/download/{session_id}")
        else:
            err = (thumbnail_results or {}).get(
                "error") or "No thumbnails generated"
            output_dir = (thumbnail_results or {}).get("output_dir")
            _log(f"❌ {err}")
            thumbnail_test_results[session_id] = {
                "success": False,
                "error": err,
                "output_dir": output_dir,
                "thumbnails": [],
            }
            _emit("done", success=False, error=err,
                  output_dir=output_dir, thumbnails=[])

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        _log(f"❌ Thumbnail worker error: {e}")
        _log(tb)
        thumbnail_test_results[session_id] = {
            "success": False,
            "error": str(e),
            "thumbnails": [],
        }
        _emit("done", success=False, error=str(e), thumbnails=[])
    finally:
        thumbnail_cancel_events.pop(session_id, None)


@app.route("/generate-test-thumbnails", methods=["POST"])
def generate_test_thumbnails():
    """Start a thumbnail-generation session; progress streams via /api/thumbnails/progress/<id>."""
    try:
        data = request.json or {}
        topic = data.get("topic", "AI Testing")
        raw_headlines = data.get("headlines") or []
        headlines = [str(h).strip()
                     for h in raw_headlines if str(h or "").strip()][:3]
        variations_per_option = int(
            data.get("variations_per_option") or 0) or None

        session_id = str(uuid.uuid4())
        thumbnail_test_streams[session_id] = _queue.Queue()
        thumbnail_test_results.pop(session_id, None)

        print(f"\n{'='*70}")
        print(f"🎬 GENERATING TEST THUMBNAILS (session={session_id})")
        print(f"📝 Topic: {topic}")
        if headlines:
            print(f"🏷️ Headlines: {headlines}")
        if variations_per_option:
            print(f"🔢 Variations per headline: {variations_per_option}")
        print(f"{'='*70}\n")

        thread = _threading.Thread(
            target=_thumbnail_test_worker,
            args=(session_id, topic, headlines, variations_per_option),
            daemon=True,
        )
        thread.start()

        return jsonify({
            "success": True,
            "session_id": session_id,
            "stream_url": f"/api/thumbnails/progress/{session_id}",
            "download_url": f"/api/thumbnails/download/{session_id}",
        })
    except Exception as e:
        print(f"\n❌ Error starting test thumbnails: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/thumbnails/progress/<session_id>")
def thumbnails_progress_stream(session_id):
    """SSE stream of log/done events for a thumbnail generation session."""
    q = thumbnail_test_streams.get(session_id)
    if q is None:
        return "Session not found", 404

    def generate():
        try:
            while True:
                try:
                    payload = q.get(timeout=300)
                except _queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(payload)}\n\n"
                if payload.get("type") == "done":
                    break
        finally:
            thumbnail_test_streams.pop(session_id, None)

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


@app.route("/api/thumbnails/download/<session_id>")
def thumbnails_download_zip(session_id):
    """Download all thumbnails generated for a session as a single ZIP."""
    info = thumbnail_test_results.get(session_id)
    if not info or not info.get("thumbnails"):
        return jsonify({"error": "Session not found or no thumbnails"}), 404

    import io
    import zipfile

    buf = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for var in info["thumbnails"]:
            fp = var.get("filepath")
            fn = var.get("filename") or (Path(fp).name if fp else None)
            if not fp or not fn:
                continue
            try:
                p = Path(fp)
                if p.exists():
                    zf.write(p, arcname=fn)
                    added += 1
            except Exception as e:
                logger.warning(f"Skipping thumbnail {fp}: {e}")

    if added == 0:
        return jsonify({"error": "No thumbnail files found on disk"}), 404

    buf.seek(0)
    safe_topic = re.sub(r'[^\w\-]+', '_', (info.get("topic")
                        or "thumbnails")).strip('_') or "thumbnails"
    zip_name = f"{safe_topic}_thumbnails_{session_id[:8]}.zip"
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=zip_name,
    )


@app.route("/videos")
def public_videos():
    """Public read-only Video Gallery (finished videos). No toolbar/forms."""
    html = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<meta name="robots" content="noindex,nofollow" />
<title>Video Gallery</title>
<style>
  :root { color-scheme: light dark; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background:#0b1220; color:#e5e7eb; }
  header { padding:14px 22px; border-bottom:1px solid #1f2937; display:flex; align-items:center; gap:12px; flex-wrap:wrap; position:sticky; top:0; background:#0b1220; z-index:10; }
  header h1 { font-size:18px; margin:0; font-weight:600; }
  header .count { color:#9ca3af; font-size:13px; }
  main { padding:20px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:18px; }
  .card { background:#111827; border:1px solid #1f2937; border-radius:10px; overflow:hidden; display:flex; flex-direction:column; }
  .card video { width:100%; height:auto; display:block; aspect-ratio:16/9; object-fit:cover; background:#000; }
  .card .body { padding:10px 12px; font-size:13px; }
  .card .title { font-weight:600; color:#f3f4f6; margin-bottom:6px; line-height:1.3; word-break:break-word; }
  .card .meta { color:#9ca3af; font-size:12px; }
  .empty, .err { color:#9ca3af; padding:24px; }
  .err { color:#fca5a5; }
  footer { padding:14px 22px; color:#6b7280; font-size:12px; border-top:1px solid #1f2937; }
</style></head>
<body>
  <header>
    <h1>🎥 Video Gallery</h1>
    <span id="count" class="count">Loading…</span>
  </header>
  <main>
    <div id="status" class="empty">Loading videos…</div>
    <div id="grid" class="grid" style="display:none"></div>
  </main>
  <footer>Read-only shared gallery.</footer>
<script>
(async function(){
  const grid = document.getElementById('grid');
  const status = document.getElementById('status');
  const countEl = document.getElementById('count');
  function fmtSize(n){ if(!n) return ''; const u=['B','KB','MB','GB']; let i=0; let v=n; while(v>=1024&&i<u.length-1){v/=1024;i++;} return v.toFixed(v>=100?0:1)+' '+u[i]; }
  function fmtDate(t){ if(!t) return ''; try { return new Date(t*1000).toLocaleDateString(); } catch(e){ return ''; } }
  try {
    const r = await fetch('/api/finished-videos');
    const data = await r.json();
    if (!data.success) {
      status.className = 'err';
      status.textContent = '⚠️ ' + (data.error || 'Failed to load videos');
      countEl.textContent = '';
      return;
    }
    const videos = data.videos || [];
    countEl.textContent = videos.length + ' video' + (videos.length===1?'':'s');
    if (videos.length === 0) {
      status.textContent = 'No videos available.';
      return;
    }
    status.style.display = 'none';
    grid.style.display = '';
    for (const v of videos) {
      const card = document.createElement('div');
      card.className = 'card';
      const title = v.title || v.filename || 'Untitled';
      const meta = [fmtSize(v.size), fmtDate(v.mtime), (v.ext||'').toUpperCase()].filter(Boolean).join(' · ');
      card.innerHTML = `
        <video controls preload="metadata" playsinline src="${v.stream_url}"></video>
        <div class="body">
          <div class="title">${title}</div>
          <div class="meta">${meta}</div>
        </div>`;
      grid.appendChild(card);
    }
  } catch (e) {
    status.className = 'err';
    status.textContent = '⚠️ ' + e.message;
  }
})();
</script>
</body></html>"""
    return Response(html, mimetype="text/html")


@app.route("/thumbnails/<filename>")
def serve_thumbnail(filename):
    """Serve generated thumbnail images"""
    try:
        search_roots = [
            _get_output_parent_dir(),
            Path.home() / "Dev" / "Thumbnails",
        ]

        file_path = None
        for root in search_roots:
            if not root.exists():
                continue
            matches = list(root.rglob(filename))
            if matches:
                file_path = matches[0]
                break

        if file_path and file_path.exists() and file_path.suffix.lower() in ['.png', '.jpg', '.jpeg']:
            mimetype = 'image/png'
            if file_path.suffix.lower() in ['.jpg', '.jpeg']:
                mimetype = 'image/jpeg'
            return send_file(file_path, mimetype=mimetype)
        return jsonify({"error": "Thumbnail not found"}), 404
    except Exception as e:
        logger.error(f"Error serving thumbnail: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/broll-images/<filename>")
def serve_broll_image(filename):
    """Serve generated B-roll images"""
    try:
        search_roots = [
            _get_output_parent_dir(),
            Path.home() / "Dev" / "brollimages",
        ]

        file_path = None
        for root in search_roots:
            if not root.exists():
                continue
            matches = list(root.rglob(filename))
            if matches:
                file_path = matches[0]
                break

        if file_path and file_path.exists() and file_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp']:
            # Determine mimetype based on extension
            mimetype = 'image/png'
            if file_path.suffix.lower() in ['.jpg', '.jpeg']:
                mimetype = 'image/jpeg'
            elif file_path.suffix.lower() == '.webp':
                mimetype = 'image/webp'

            return send_file(file_path, mimetype=mimetype)
        return jsonify({"error": "B-roll image not found"}), 404
    except Exception as e:
        logger.error(f"Error serving B-roll image: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/broll-videos/<filename>")
def serve_broll_video(filename):
    """Serve generated Grok B-roll videos from {output_dir}/broll or legacy ~/Dev/brollvideos."""
    try:
        safe_name = Path(filename).name
        candidates = []
        base = _get_output_base_dir()
        if base is not None:
            candidates.append(base / "broll" / safe_name)
            for run_broll in base.glob("*/broll"):
                candidates.append(run_broll / safe_name)
        candidates.append(Path.home() / "Dev" / "brollvideos" / safe_name)
        for file_path in candidates:
            if file_path.exists() and file_path.suffix.lower() == '.mp4':
                return send_file(file_path, mimetype='video/mp4')
        return jsonify({"error": "B-roll video not found"}), 404
    except Exception as e:
        logger.error(f"Error serving B-roll video: {e}")
        return jsonify({"error": str(e)}), 500


def _resolve_media_file(filename: str, kind: str):
    """Resolve a media filename to an absolute path. kind: 'image' | 'video' | 'thumbnail' | 'edl'."""
    # Strip any path components for safety
    safe_name = Path(filename).name
    if not safe_name or safe_name in ('.', '..'):
        return None

    if kind == 'video':
        candidates = []
        base = _get_output_base_dir()
        if base is not None:
            candidates.append(base / "broll" / safe_name)
            for run_broll in base.glob("*/broll"):
                candidates.append(run_broll / safe_name)
        candidates.append(Path.home() / "Dev" / "brollvideos" / safe_name)
        for candidate in candidates:
            if candidate.exists() and candidate.suffix.lower() == '.mp4':
                return candidate
        return None

    if kind == 'thumbnail':
        search_roots = [
            _get_output_parent_dir(),
            Path.home() / "Dev" / "Thumbnails",
        ]
        allowed_ext = {'.png', '.jpg', '.jpeg'}
        for root in search_roots:
            if not root.exists():
                continue
            matches = list(root.rglob(safe_name))
            if matches and matches[0].suffix.lower() in allowed_ext:
                return matches[0]
        return None

    if kind == 'edl':
        base = _get_output_base_dir()
        if base is not None:
            direct = base / "MDL" / safe_name
            if direct.exists() and direct.suffix.lower() == '.edl':
                return direct
            for run_mdl in base.glob("*/MDL"):
                candidate = run_mdl / safe_name
                if candidate.exists() and candidate.suffix.lower() == '.edl':
                    return candidate

        # Legacy fallback: previous flow wrote EDLs in cwd.
        candidate = Path.cwd() / safe_name
        if candidate.exists() and candidate.suffix.lower() == '.edl':
            return candidate
        # Also search the repo root just in case.
        repo_root = Path(__file__).resolve().parent.parent
        for root in (repo_root, repo_root.parent):
            c = root / safe_name
            if c.exists() and c.suffix.lower() == '.edl':
                return c
        return None

    # images: search the same roots used by serve_broll_image
    search_roots = [
        _get_output_parent_dir(),
        Path.home() / "Dev" / "brollimages",
    ]
    allowed_ext = {'.png', '.jpg', '.jpeg', '.webp'}
    for root in search_roots:
        if not root.exists():
            continue
        matches = list(root.rglob(safe_name))
        if matches:
            match = matches[0]
            if match.suffix.lower() in allowed_ext:
                return match
    return None


@app.route("/api/download-media-zip", methods=["POST"])
def download_media_zip():
    """Bundle selected B-roll images and/or Grok videos into a ZIP for download.

    Request JSON:
      {
        "title": "Optional script title (used in zip filename)",
        "images": ["filename1.png", ...],   # optional
        "videos": ["filename1.mp4", ...]    # optional
      }
    """
    import zipfile
    import re as _re

    try:
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "media").strip() or "media"
        images = data.get("images") or []
        videos = data.get("videos") or []

        if not images and not videos:
            return jsonify({"success": False, "error": "No files requested"}), 400

        # Sanitize title for filename
        safe_title = _re.sub(r'[^A-Za-z0-9._-]+', '_',
                             title).strip('_') or "media"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_name = f"{safe_title}_media_{ts}.zip"

        buf = BytesIO()
        added = 0
        skipped = []
        with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for fn in images:
                path = _resolve_media_file(fn, 'image')
                if path is None:
                    skipped.append(fn)
                    continue
                zf.write(path, arcname=f"broll-images/{path.name}")
                added += 1
            for fn in videos:
                path = _resolve_media_file(fn, 'video')
                if path is None:
                    skipped.append(fn)
                    continue
                zf.write(path, arcname=f"grok-videos/{path.name}")
                added += 1

        if added == 0:
            return jsonify({
                "success": False,
                "error": "None of the requested files could be found on disk",
                "skipped": skipped,
            }), 404

        if skipped:
            logger.warning(
                f"⚠️ Media zip skipped {len(skipped)} missing files: {skipped[:5]}{'…' if len(skipped) > 5 else ''}")

        buf.seek(0)
        logger.info(
            f"📦 Built media zip '{zip_name}' with {added} files ({len(buf.getvalue())} bytes)")
        response = make_response(buf.getvalue())
        response.headers['Content-Type'] = 'application/zip'
        response.headers['Content-Disposition'] = f'attachment; filename="{zip_name}"'
        return response
    except Exception as e:
        logger.error(f"❌ download_media_zip failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/create_resolve_project", methods=["POST"])
def create_resolve_project():
    """Create a new DaVinci Resolve project with automated setup"""
    logger.info("=== DAVINCI RESOLVE PROJECT CREATION REQUEST ===")

    try:
        data = request.json
        script_title = data.get("script_title", "AI_Video_Project")
        edl_content = data.get("edl_content")
        edl_filename = data.get("edl_filename")
        generate_subtitles = bool(data.get("generate_subtitles", True))

        logger.info(f"📊 Script Title: {script_title}")
        logger.info(f"📄 EDL Filename: {edl_filename}")
        logger.info(
            f"📄 EDL Content Length: {len(edl_content) if edl_content else 0}")

        # Ensure generated Grok videos/images are in expected DaVinci project folders.
        try:
            sync_info = _sync_generated_media_to_project(
                _get_run_output_dir(script_title, create=True)
            )
            logger.info(
                f"🎞️ Pre-Resolve media sync: {sync_info['videos_copied']} video(s), "
                f"{sync_info['images_copied']} image(s) copied"
            )
        except Exception as sync_err:
            logger.warning(
                f"⚠️ Media sync before create_resolve_project failed: {sync_err}")

        # Save EDL content to temp file if provided
        edl_file_path = None
        if edl_content:
            import tempfile
            # Create temp file with .edl extension
            temp_fd, edl_file_path = tempfile.mkstemp(suffix='.edl', text=True)
            try:
                with os.fdopen(temp_fd, 'w') as f:
                    f.write(edl_content)
                logger.info(f"💾 Saved EDL to temp file: {edl_file_path}")
            except Exception as write_error:
                logger.error(f"❌ Failed to write EDL temp file: {write_error}")
                edl_file_path = None

        project_root = _get_run_output_dir(script_title, create=True)
        broll_media_path = str(project_root / "bRoll")
        images_media_path = str(project_root / "images")

        # Import the DaVinci Resolve API module
        from davinci_resolve_api import create_resolve_project as create_project

        # Create the project with EDL file path
        result = create_project(
            script_title,
            edl_file_path,
            broll_folder=broll_media_path,
            images_folder=images_media_path,
        )

        # Clean up temp file
        if edl_file_path and os.path.exists(edl_file_path):
            try:
                os.unlink(edl_file_path)
                logger.info(f"🗑️ Deleted temp EDL file: {edl_file_path}")
            except Exception as cleanup_error:
                logger.warning(
                    f"⚠️ Failed to delete temp EDL file: {cleanup_error}")

        if result.get("success"):
            logger.info(f"✅ Project created: {result.get('project_name')}")
            return jsonify(result)
        else:
            logger.error(f"❌ Project creation failed: {result.get('error')}")
            return jsonify(result), 500

    except ImportError as import_error:
        error_msg = f"Failed to import DaVinci Resolve API: {str(import_error)}"
        logger.error(f"❌ {error_msg}")
        return jsonify({
            "success": False,
            "error": error_msg
        }), 500
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return jsonify({
            "success": False,
            "error": error_msg
        }), 500


@app.route("/check_aroll_videos", methods=["POST"])
def check_aroll_videos():
    """Check if aRoll folder has any videos"""
    logger.info("=== CHECKING AROLL VIDEOS ===")

    def _is_video_file(filename: str) -> bool:
        return filename.lower().endswith((".mp4", ".mov", ".m4v"))

    def _get_default_aroll_source():
        """Return (folder_path, sorted_video_files) for default A-roll test clips.

        Search order:
        1. SCRIPTCRAFT_DEFAULT_AROLL_DIR env var (if set)
        2. ~/Dev/Davinci/Template/aRoll
        3. ~/Dev/Davinci/Template/Raw
        """
        candidate_dirs = []

        env_dir = (os.environ.get(
            "SCRIPTCRAFT_DEFAULT_AROLL_DIR") or "").strip()
        if env_dir:
            candidate_dirs.append(os.path.expanduser(env_dir))

        candidate_dirs.append(os.path.expanduser(
            "~/Dev/Davinci/Template/aRoll"))
        candidate_dirs.append(os.path.expanduser("~/Dev/Davinci/Template/Raw"))

        for folder in candidate_dirs:
            if not os.path.isdir(folder):
                continue
            files = sorted(
                [f for f in os.listdir(folder) if _is_video_file(f)])
            if files:
                return folder, files

        return None, []

    try:
        data = request.json
        script_title = data.get("script_title", "")

        if not script_title:
            return jsonify({
                "success": False,
                "error": "No script title provided"
            }), 400

        project_path = _get_run_output_dir(script_title, create=False)
        aroll_path = str(project_path / "aRoll")

        logger.info(f"📁 Script title: '{script_title}'")
        logger.info(f"📁 Run folder: '{project_path}'")
        logger.info(f"📁 Checking aroll path: {aroll_path}")
        logger.info(f"📁 Path exists: {os.path.exists(aroll_path)}")

        # Fallback: if the title-derived aRoll folder is missing OR empty,
        # also try the configured output_dir/aRoll directly. This matches the
        # user expectation: "set output dir = source for aRoll".
        def _has_videos(p: str) -> bool:
            try:
                return os.path.isdir(p) and any(
                    _is_video_file(f) for f in os.listdir(p)
                )
            except Exception:
                return False

        if not _has_videos(aroll_path):
            configured_dir = _get_output_parent_dir()
            alt_aroll = str(configured_dir / "aRoll")
            if alt_aroll != aroll_path and _has_videos(alt_aroll):
                logger.info(
                    f"📁 Falling back to configured output_dir aRoll: {alt_aroll}"
                )
                aroll_path = alt_aroll

        if not os.path.exists(aroll_path):
            # List what's actually in the output parent path to help debug
            base_path = _get_output_parent_dir()
            if os.path.exists(base_path):
                logger.info(f"📁 Base path exists, folders found:")
                for folder in os.listdir(base_path):
                    logger.info(f"   - {folder}")
            else:
                logger.info(f"📁 Base path does not exist: {base_path}")

            logger.info(f"📁 aRoll folder does not exist yet")

            default_source, default_videos = _get_default_aroll_source()
            return jsonify({
                "success": True,
                "video_count": 0,
                "videos": [],
                "default_available": len(default_videos) > 0,
                "default_video_count": len(default_videos),
                "default_source": default_source,
                "default_videos": default_videos,
            })

        # Count local project video files in aRoll folder
        video_files = [f for f in os.listdir(aroll_path) if _is_video_file(f)]

        logger.info(f"✅ Found {len(video_files)} video(s) in aRoll folder:")
        for vf in video_files:
            logger.info(f"   - {vf}")

        default_source, default_videos = _get_default_aroll_source()

        return jsonify({
            "success": True,
            "video_count": len(video_files),
            "videos": video_files,
            "default_available": len(default_videos) > 0,
            "default_video_count": len(default_videos),
            "default_source": default_source,
            "default_videos": default_videos,
        })

    except Exception as e:
        error_msg = f"Error checking aRoll videos: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return jsonify({
            "success": False,
            "error": error_msg
        }), 500


@app.route("/create_resolve_with_videos", methods=["POST"])
def create_resolve_with_videos():
    """Create a DaVinci Resolve project with aRoll videos added to timeline"""
    logger.info("=== DAVINCI RESOLVE PROJECT CREATION WITH VIDEOS ===")

    try:
        data = request.json
        script_title = data.get("script_title", "AI_Video_Project")
        edl_content = data.get("edl_content")
        edl_filename = data.get("edl_filename")
        generate_subtitles = bool(data.get("generate_subtitles", True))

        logger.info(f"📊 Script Title: {script_title}")

        # Ensure generated Grok videos/images are in expected DaVinci project folders.
        try:
            sync_info = _sync_generated_media_to_project(
                _get_run_output_dir(script_title, create=True)
            )
            logger.info(
                f"🎞️ Pre-Resolve media sync: {sync_info['videos_copied']} video(s), "
                f"{sync_info['images_copied']} image(s) copied"
            )
        except Exception as sync_err:
            logger.warning(
                f"⚠️ Media sync before create_resolve_with_videos failed: {sync_err}")

        def _is_video_file(filename: str) -> bool:
            return filename.lower().endswith((".mp4", ".mov", ".m4v"))

        def _get_default_aroll_source():
            candidate_dirs = []

            env_dir = (os.environ.get(
                "SCRIPTCRAFT_DEFAULT_AROLL_DIR") or "").strip()
            if env_dir:
                candidate_dirs.append(os.path.expanduser(env_dir))

            candidate_dirs.append(os.path.expanduser(
                "~/Dev/Davinci/Template/aRoll"))
            candidate_dirs.append(os.path.expanduser(
                "~/Dev/Davinci/Template/Raw"))

            for folder in candidate_dirs:
                if not os.path.isdir(folder):
                    continue
                files = sorted(
                    [f for f in os.listdir(folder) if _is_video_file(f)])
                if files:
                    return folder, files

            return None, []

        use_default_aroll = bool(data.get("use_default_aroll", False))

        project_path = _get_run_output_dir(script_title, create=False)
        aroll_path = str(project_path / "aRoll")

        # Get list of video files
        video_files = []
        if os.path.exists(aroll_path):
            video_files = [f for f in os.listdir(
                aroll_path) if _is_video_file(f)]
            logger.info(f"📹 Found {len(video_files)} video(s) in aroll folder")

        # Fallback to configured output_dir/aRoll if title-derived folder is empty.
        if len(video_files) == 0:
            configured_dir = _get_output_parent_dir()
            alt_aroll = str(configured_dir / "aRoll")
            if alt_aroll != aroll_path and os.path.isdir(alt_aroll):
                alt_videos = [
                    f for f in os.listdir(alt_aroll) if _is_video_file(f)
                ]
                if alt_videos:
                    logger.info(
                        f"📁 Falling back to configured output_dir aRoll: "
                        f"{alt_aroll} ({len(alt_videos)} videos)"
                    )
                    aroll_path = alt_aroll
                    video_files = alt_videos

        # Optional fallback for testing DaVinci flow without downloaded HeyGen aRoll.
        used_default_aroll = False
        default_source = None
        if use_default_aroll and len(video_files) == 0:
            default_source, default_videos = _get_default_aroll_source()
            if default_source and default_videos:
                logger.info(
                    f"🧪 Using default A-roll test clips from: {default_source} "
                    f"({len(default_videos)} videos)"
                )
                aroll_path = default_source
                video_files = default_videos
                used_default_aroll = True
            else:
                logger.warning(
                    "⚠️ use_default_aroll requested, but no default clips were found"
                )

        # Sort videos by chapter/part order
        def parse_chapter_info(filename):
            """Extract chapter and part numbers from filename.

            Matches any filename containing Ch{N} and p{N}, with any
            non-alphanumeric separators in between (or none):
              Ch1p1, Ch1p2, Ch6p1         (no separator)
              Ch1-Pt1, Ch1-pt1, Ch2-p2   (dash + optional 't')
              Ch1_Pt1, Ch_1_p_1, Ch1.p1  (underscore / dot)
              Title-Ch3p2.mp4            (title prefix, any separator)
              heygen_...-Ch1p1_id.mp4    (heygen with ID suffix)
              Ch1p1b                     (b-duplicate sorts after Ch1p1)

            'AI with Roz' intro files always sort first.
            'AI with Roz Exit' files always sort last.
            Unknown files sort to the end.
            """
            import re
            name = filename

            # Exit clip ("AI with Roz Exit Clip.mov") always goes LAST,
            # after every chapter clip and any unknown clips.
            if re.search(r'AI\s+with\s+Roz.*Exit', name, re.IGNORECASE):
                return (99999, 0)

            # Hook clip(s) always sort to the FRONT of the timeline (before any
            # chapter clip). HeyGen names them like "{title}-hook",
            # "{title}-hook-2", "{title}-hook_{id}.mp4", etc. Multiple hooks
            # keep their numeric suffix order (hook = 1, hook-2 = 2, …).
            hook_match = re.search(
                r'[-_\s]hook(?:[-_]?(\d+))?(?:[-_.]|$)',
                name,
                re.IGNORECASE,
            )
            if hook_match:
                hook_idx = int(hook_match.group(1)) if hook_match.group(1) else 1
                logger.info(
                    f"   🔢 parse_chapter_info: {name} → HOOK (-1, {hook_idx})"
                )
                return (-1, hook_idx)

            # Detect chapter pattern first — a chapter clip wins even if its
            # title contains "AI with Roz" (e.g.
            # "AI with Roz  AI ZERO Knowledge of AI-Ch1p1_xxx.mp4").
            # Permissive pattern: Ch [sep] {X} [sep] p [t]? [sep] {Y} [b]?
            # where [sep] is any run of non-alphanumeric characters (or empty).
            chapter_match = re.search(
                r'Ch[^A-Za-z0-9]*?(\d+)[^A-Za-z0-9]*?[Pp][Tt]?[^A-Za-z0-9]*?(\d+)(b?)',
                name
            )
            if chapter_match:
                chapter_num = int(chapter_match.group(1))
                part_num = int(chapter_match.group(2))
                # 'b' duplicate sorts just after the main part
                part_frac = 0.5 if chapter_match.group(
                    3).lower() == 'b' else 0
                logger.info(
                    f"   🔢 parse_chapter_info: {name} → (Ch{chapter_num}, P{part_num}{'b' if part_frac else ''})"
                )
                return (chapter_num, part_num + part_frac)

            # Only treat as intro when there is NO chapter marker. This keeps
            # the standalone "AI with Roz v2.mov" intro at position 0 without
            # collapsing every chapter clip to (0, 0).
            if re.search(r'AI\s+with\s+Roz', name, re.IGNORECASE):
                logger.info(f"   🔢 parse_chapter_info: {name} → INTRO (0, 0)")
                return (0, 0)

            # Default to end of list
            logger.warning(
                f"   ⚠️ parse_chapter_info: NO chapter marker found in {name} → (999, 999)"
            )
            return (999, 999)

        # Sort videos by chapter order
        sorted_videos = sorted(video_files, key=parse_chapter_info)
        logger.info(f"📋 Sorted video order: {sorted_videos}")

        # Save EDL content to temp file if provided
        edl_file_path = None
        if edl_content:
            import tempfile
            temp_fd, edl_file_path = tempfile.mkstemp(suffix='.edl', text=True)
            try:
                with os.fdopen(temp_fd, 'w') as f:
                    f.write(edl_content)
                logger.info(f"💾 Saved EDL to temp file: {edl_file_path}")
            except Exception as write_error:
                logger.error(f"❌ Failed to write EDL temp file: {write_error}")
                edl_file_path = None

        # Import the DaVinci Resolve API module (force reload to get latest changes)
        import importlib
        import sys
        if 'davinci_resolve_api' in sys.modules:
            logger.info("🔄 Reloading davinci_resolve_api module...")
            import davinci_resolve_api
            importlib.reload(davinci_resolve_api)
            from davinci_resolve_api import create_resolve_project_with_videos
            logger.info("✅ Module reloaded successfully")
        else:
            logger.info(
                "📦 Loading davinci_resolve_api module for first time...")
            from davinci_resolve_api import create_resolve_project_with_videos

        logger.info(f"🎬 Calling create_resolve_project_with_videos...")
        logger.info(f"   Script title: {script_title}")
        logger.info(f"   EDL file: {edl_file_path}")
        logger.info(f"   aRoll path: {aroll_path}")
        logger.info(f"   Videos to add: {len(sorted_videos)}")

        broll_media_path = str(project_path / "bRoll")
        images_media_path = str(project_path / "images")

        # Create the project with videos
        result = create_resolve_project_with_videos(
            script_title,
            edl_file_path,
            aroll_path,
            sorted_videos,
            broll_media_path,
            images_media_path,
            generate_subtitles,
        )

        if isinstance(result, dict):
            result["used_default_aroll"] = used_default_aroll
            result["aroll_source"] = aroll_path
            if used_default_aroll:
                result["default_aroll_source"] = default_source

        # Clean up temp file
        if edl_file_path and os.path.exists(edl_file_path):
            try:
                os.unlink(edl_file_path)
                logger.info(f"🗑️ Deleted temp EDL file: {edl_file_path}")
            except Exception as cleanup_error:
                logger.warning(
                    f"⚠️ Failed to delete temp EDL file: {cleanup_error}")

        if result.get("success"):
            logger.info(
                f"✅ Project created with {len(sorted_videos)} videos: {result.get('project_name')}")
            return jsonify(result)
        else:
            logger.error(f"❌ Project creation failed: {result.get('error')}")
            return jsonify(result), 500

    except ImportError as import_error:
        error_msg = f"Failed to import DaVinci Resolve API: {str(import_error)}"
        logger.error(f"❌ {error_msg}")
        return jsonify({
            "success": False,
            "error": error_msg
        }), 500
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return jsonify({
            "success": False,
            "error": error_msg
        }), 500


@app.route("/execute_curl", methods=["POST"])
def execute_curl():
    """Execute a curl command and return the result"""
    logger.info("=== CURL COMMAND EXECUTION REQUEST ===")

    try:
        data = request.json
        curl_command = data.get("curl_command", "")

        if not curl_command:
            return jsonify({
                "success": False,
                "error": "No curl command provided"
            }), 400

        logger.info(
            f"📤 Executing curl command (first 100 chars): {curl_command[:100]}...")

        # Execute the curl command using subprocess
        import subprocess
        import shlex

        # Parse the curl command
        # Remove leading/trailing whitespace and newlines
        curl_command = curl_command.strip()

        # Execute the command
        try:
            result = subprocess.run(
                curl_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )

            # Parse the response
            if result.returncode == 0:
                # Try to parse JSON response
                try:
                    import json
                    response_data = json.loads(result.stdout)

                    # Extract job ID if available (HeyGen specific).
                    # HeyGen V3 (/v3/templates/{id}) returns the video id at
                    # data.id; the legacy V2 endpoint used data.video_id. Check
                    # both so polling starts regardless of endpoint version.
                    job_id = None
                    if isinstance(response_data, dict):
                        data_obj = response_data.get('data') or {}
                        if not isinstance(data_obj, dict):
                            data_obj = {}
                        job_id = data_obj.get('video_id') or \
                            data_obj.get('id') or \
                            response_data.get('video_id') or \
                            response_data.get('job_id') or \
                            response_data.get('id')

                    logger.info(f"✅ Curl command executed successfully")
                    if job_id:
                        logger.info(f"📋 Job ID: {job_id}")

                    return jsonify({
                        "success": True,
                        "response": response_data,
                        "job_id": job_id,
                        "raw_output": result.stdout
                    })
                except json.JSONDecodeError:
                    # Not JSON, return raw output
                    logger.info(f"✅ Curl command executed (non-JSON response)")
                    return jsonify({
                        "success": True,
                        "raw_output": result.stdout
                    })
            else:
                error_msg = result.stderr or "Command failed with no error message"
                logger.error(f"❌ Curl command failed: {error_msg}")
                return jsonify({
                    "success": False,
                    "error": error_msg,
                    "return_code": result.returncode
                }), 500

        except subprocess.TimeoutExpired:
            logger.error("❌ Curl command timed out after 30 seconds")
            return jsonify({
                "success": False,
                "error": "Command timed out after 30 seconds"
            }), 500

    except Exception as e:
        error_msg = f"Error executing curl command: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return jsonify({
            "success": False,
            "error": error_msg
        }), 500


@app.route("/setup_project", methods=["POST"])
def setup_project():
    """Set up project folder structure and copy template files"""
    logger.info("=== PROJECT SETUP REQUEST ===")

    try:
        data = request.json
        script_title = data.get("script_title", "")
        script_content = data.get("script_content", "")

        if not script_title:
            return jsonify({
                "success": False,
                "error": "No script title provided"
            }), 400

        import os
        import shutil
        from pathlib import Path

        # Define paths
        safe_title = _safe_title_for_paths(script_title)
        project_path = _get_run_output_dir(script_title, create=True)
        template_path = Path.home() / "Dev" / "Davinci" / "Template"

        logger.info(f"📁 Creating project folder: {project_path}")

        # Create project directory if it doesn't exist
        # IMPORTANT: Do NOT delete existing project - preserve downloaded videos!
        if project_path.exists():
            logger.info(f"✅ Project folder already exists: {project_path}")
            logger.info(
                "   Preserving existing aRoll videos and other content")
        else:
            project_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"✅ Created new project folder")

        # Ensure subfolders exist (without deleting existing content)
        aroll_path = project_path / "aRoll"
        aroll_path.mkdir(exist_ok=True)
        broll_path = project_path / "bRoll"
        broll_path.mkdir(exist_ok=True)
        images_path = project_path / "images"
        images_path.mkdir(exist_ok=True)
        script_path = project_path / "script"
        script_path.mkdir(exist_ok=True)

        # Copy template files ONLY if project is new (no aroll videos exist)
        aroll_videos = list(aroll_path.glob("*.mp4"))
        if template_path.exists() and len(aroll_videos) == 0:
            logger.info(f"📋 Copying template from: {template_path}")
            file_count = sum(
                1 for _ in template_path.rglob('*') if _.is_file())
            logger.info(f"📦 Found {file_count} files to copy...")

            copied_count = 0
            for item in template_path.iterdir():
                # Never copy the heygen folder into the project.
                if item.name.lower() == "heygen":
                    logger.info(
                        f"⏭️ Skipping heygen folder (excluded from project copy)")
                    continue
                dest = project_path / item.name
                if item.is_dir():
                    # Count files in directory
                    dir_files = sum(1 for _ in item.rglob('*') if _.is_file())
                    logger.info(
                        f"📁 Copying directory: {item.name} ({dir_files} files)..."
                    )
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                    copied_count += dir_files
                else:
                    shutil.copy2(item, dest)
                    copied_count += 1

                # Log progress every 100 files
                if copied_count % 100 == 0:
                    logger.info(
                        f"📊 Progress: {copied_count}/{file_count} files copied")

            logger.info(f"✅ Template files copied ({copied_count} total)")
        elif len(aroll_videos) > 0:
            logger.info(
                f"ℹ️ Skipping template copy - {len(aroll_videos)} "
                f"aRoll videos already exist"
            )
        else:
            logger.warning(
                f"⚠️ Template path not found: {template_path}"
            )

        # Create script subdirectory
        script_dir = project_path / "script"
        script_dir.mkdir(exist_ok=True)

        # Sync generated media into DaVinci project structure.
        # - Grok videos: broll -> bRoll
        # - Generated images already produced in project/images are kept there
        # - Legacy fallback copies from ~/Dev/brollimages when needed
        media_sync = _sync_generated_media_to_project(project_path)
        logger.info(
            f"🎞️ Media sync complete: {media_sync['videos_copied']} video(s) -> bRoll, "
            f"{media_sync['images_copied']} image(s) copied"
        )

        # Save script as Word document if content provided
        if script_content:
            import sys
            import asyncio

            # Import word processing from console_ui
            sys.path.insert(
                0, str(Path(__file__).parent.parent / "console_ui")
            )
            from word_processing import convert_markdown_to_word

            script_file = script_dir / f"{safe_title}.docx"
            logger.info(f"📝 Creating script document: {script_file}")

            # Convert and save (handle async function)
            try:
                asyncio.run(convert_markdown_to_word(
                    markdown_content=script_content,
                    output_file_path=str(script_file),
                    template_path=None,
                    title=script_title
                ))
                logger.info(f"✅ Script saved: {script_file}")
            except Exception as word_error:
                logger.error(f"❌ Word document error: {word_error}")
                # Continue anyway - project still set up

        return jsonify({
            "success": True,
            "project_path": str(project_path),
            "script_dir": str(script_dir),
            "media_sync": media_sync,
        })

    except Exception as e:
        error_msg = f"Error setting up project: {str(e)}"
        logger.error(f"❌ {error_msg}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({
            "success": False,
            "error": error_msg
        }), 500


@app.route("/check_video_status", methods=["POST"])
def check_video_status():
    """Check HeyGen video generation status and download when complete"""
    logger.info("=== VIDEO STATUS CHECK REQUEST ===")

    try:
        data = request.json
        video_id = data.get("video_id", "")
        api_key = data.get("api_key", "")

        if not video_id:
            return jsonify({
                "success": False,
                "error": "No video ID provided"
            }), 400

        if not api_key:
            return jsonify({
                "success": False,
                "error": "No API key provided"
            }), 400

        logger.info(f"📹 Checking status for video ID: {video_id}")

        import requests

        # Check video status
        base_url = "https://api.heygen.com/v1/video_status.get"
        video_status_url = f"{base_url}?video_id={video_id}"
        headers = {
            "X-Api-Key": api_key
        }

        try:
            response = requests.get(
                video_status_url, headers=headers, timeout=10
            )
            response_data = response.json()

            if response.status_code != 200:
                error_msg = response_data.get("message", "Unknown error")
                logger.error(f"❌ HeyGen API error: {error_msg}")
                return jsonify({
                    "success": False,
                    "error": f"HeyGen API error: {error_msg}"
                }), 500

            status = response_data.get("data", {}).get("status", "unknown")
            logger.info(f"📊 Video status: {status}")

            result = {
                "success": True,
                "status": status,
                "video_id": video_id
            }

            if status == "completed":
                video_url = response_data.get("data", {}).get("video_url")
                thumb_url = response_data.get("data", {}).get(
                    "thumbnail_url"
                )

                if video_url:
                    result["video_url"] = video_url
                    result["thumbnail_url"] = thumb_url
                    logger.info(f"✅ Video completed! URL: {video_url}")
                else:
                    msg = "⚠️ Video marked as completed but no URL"
                    logger.warning(msg)

            elif status == "failed":
                error = response_data.get("data", {}).get(
                    "error", "Unknown error"
                )
                result["error"] = error
                logger.error(f"❌ Video generation failed: {error}")

            return jsonify(result)

        except requests.RequestException as req_error:
            error_msg = f"Network error: {str(req_error)}"
            logger.error(f"❌ {error_msg}")
            return jsonify({
                "success": False,
                "error": error_msg
            }), 500

    except Exception as e:
        error_msg = f"Error checking video status: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return jsonify({
            "success": False,
            "error": error_msg
        }), 500


@app.route("/download_heygen_video", methods=["POST"])
def download_heygen_video():
    """Download completed HeyGen video to project folder"""
    logger.info("=== VIDEO DOWNLOAD REQUEST ===")

    try:
        data = request.json
        video_url = data.get("video_url", "")
        video_id = data.get("video_id", "")
        chapter_name = data.get("chapter_name", "video")
        script_title = data.get("script_title", "")

        if not video_url:
            return jsonify({
                "success": False,
                "error": "No video URL provided"
            }), 400

        logger.info(f"⬇️ Downloading video: {video_id}")

        import requests
        from pathlib import Path

        try:
            # Download video content
            video_response = requests.get(video_url, timeout=60)

            if video_response.status_code != 200:
                status_code = video_response.status_code
                logger.error(f"❌ Failed to download video: {status_code}")
                return jsonify({
                    "success": False,
                    "error": f"Failed to download video: {status_code}"
                }), 500

            # Create safe names
            safe_chars = (' ', '-', '_')
            safe_chapter_name = "".join(
                c for c in chapter_name
                if c.isalnum() or c in safe_chars
            ).rstrip()

            safe_title = "".join(
                c for c in script_title
                if c.isalnum() or c in safe_chars
            ).rstrip().replace(' ', '_') if script_title else "default"

            filename = f"{safe_chapter_name}_{video_id[:8]}.mp4"

            # Save to project aroll folder if script title provided
            if script_title:
                project_path = _get_run_output_dir(script_title, create=True)
                aroll_path = project_path / "aRoll"

                # Create project folders if they don't exist
                aroll_path.mkdir(parents=True, exist_ok=True)
                broll_path = project_path / "bRoll"
                broll_path.mkdir(parents=True, exist_ok=True)
                images_path = project_path / "images"
                images_path.mkdir(parents=True, exist_ok=True)

                # Save video file
                video_file = aroll_path / filename
                with open(video_file, 'wb') as f:
                    f.write(video_response.content)

                logger.info(
                    f"✅ Video saved to project: {video_file}"
                )

                return jsonify({
                    "success": True,
                    "filename": filename,
                    "path": str(video_file)
                })
            else:
                # No script title - return as download
                from io import BytesIO
                video_buffer = BytesIO(video_response.content)
                video_buffer.seek(0)

                logger.info(
                    f"✅ Video downloaded successfully: {filename}"
                )

                return send_file(
                    video_buffer,
                    mimetype='video/mp4',
                    as_attachment=True,
                    download_name=filename
                )

        except requests.RequestException as req_error:
            error_msg = f"Network error: {str(req_error)}"
            logger.error(f"❌ {error_msg}")
            return jsonify({
                "success": False,
                "error": error_msg
            }), 500

    except Exception as e:
        error_msg = f"Error downloading video: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return jsonify({
            "success": False,
            "error": error_msg
        }), 500


@app.route("/test-comparisons")
def test_comparisons():
    """Test endpoint to preview the chapter comparisons tab without running full workflow"""

    # Mock chapter comparison data
    mock_comparisons = [
        {
            'chapter_num': 1,
            'original': '''Welcome to our channel! Today we're diving into an amazing topic that will change how you think about productivity.

Let's start with the basics and understand why this matters.''',
            'revised': '''Welcome to our channel! Today we're exploring a game-changing approach to productivity that actually works.

Let's dive into the fundamentals and discover why this is so important for your success.''',
            'feedback': '''Reviewer Feedback:
- Opening hook needs more impact
- Changed "amazing topic" to "game-changing approach" for stronger language
- Adjusted second paragraph for better flow'''
        },
        {
            'chapter_num': 2,
            'original': '''The first key principle is understanding your goals. You need to know what you want to achieve.

Without clear goals, you'll struggle to make progress.''',
            'revised': '''The first crucial principle is crystal-clear goal setting. You must define exactly what success looks like.

Without specific, measurable goals, you're just wandering without direction.''',
            'feedback': '''Reviewer Feedback:
- Made language more specific and actionable
- Changed "understanding" to "crystal-clear goal setting"
- Strengthened the consequence statement'''
        },
        {
            'chapter_num': 3,
            'original': '''Now let's talk about time management. It's important to schedule your day properly.

Make sure you allocate time for important tasks.''',
            'revised': '''Here's where time management becomes your superpower. Block out your day strategically, not randomly.

Protect prime hours for your most critical, high-impact work.''',
            'feedback': '''Reviewer Feedback:
- Added energy to the opening with "superpower"
- Changed passive "schedule" to active "block out"
- Made the advice more specific and actionable'''
        }
    ]

    # Mock thumbnails for testing
    mock_thumbnails = [
        {
            'id': 'test-thumb-1',
            'url': 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTI4MCIgaGVpZ2h0PSI3MjAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3Qgd2lkdGg9IjEyODAiIGhlaWdodD0iNzIwIiBmaWxsPSIjMWU0MGFmIi8+PHRleHQgeD0iNTAlIiB5PSI1MCUiIGZvbnQtZmFtaWx5PSJBcmlhbCIgZm9udC1zaXplPSI4MCIgZmlsbD0id2hpdGUiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGR5PSIuM2VtIj5UZXN0IFRodW1ibmFpbCAxPC90ZXh0Pjwvc3ZnPg==',
            'style': 'bold'
        }
    ]

    # Render the main template
    return render_template('index.html',
                           test_mode=True,
                           test_comparisons=mock_comparisons,
                           test_thumbnails=mock_thumbnails)


# ── DaVinci Resolve Audio Render ──────────────────────────────────────────────

def _resolve_env_setup():
    """Set RESOLVE_SCRIPT_API/LIB env vars and ensure Modules path is in sys.path."""
    resolve_script_api = (
        "/Library/Application Support/Blackmagic Design/"
        "DaVinci Resolve/Developer/Scripting"
    )
    os.environ["RESOLVE_SCRIPT_API"] = resolve_script_api
    os.environ["RESOLVE_SCRIPT_LIB"] = (
        "/Applications/DaVinci Resolve/DaVinci Resolve.app/"
        "Contents/Libraries/Fusion/fusionscript.so"
    )
    modules_path = os.path.join(resolve_script_api, "Modules")
    if modules_path not in sys.path:
        sys.path.append(modules_path)


@app.route("/api/resolve/list-projects", methods=["GET"])
def api_resolve_list_projects():
    """Return the projects in the current Resolve project-manager folder.

    Lets the user pick a project from the web GUI before rendering, instead of
    requiring it to already be open in Resolve.
    """
    try:
        _resolve_env_setup()
        import DaVinciResolveScript as dvr_script  # type: ignore
        resolve = dvr_script.scriptapp("Resolve")
        if resolve is None:
            return jsonify({"success": False, "error": "DaVinci Resolve is not running or not reachable."}), 500

        pm = resolve.GetProjectManager()
        try:
            projects = list(pm.GetProjectListInCurrentFolder() or [])
        except Exception as _e:
            projects = []
        current = pm.GetCurrentProject()
        current_name = current.GetName() if current else None
        return jsonify({
            "success": True,
            "projects": projects,
            "current_project": current_name,
        })
    except Exception as e:
        logger.error(f"❌ /api/resolve/list-projects failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/resolve/load-project", methods=["POST"])
def api_resolve_load_project():
    """Load (open) a Resolve project by name from the current folder.

    Body JSON: {"project_name": "My Project"}
    """
    try:
        data = request.get_json(silent=True) or {}
        project_name = (data.get("project_name") or "").strip()
        if not project_name:
            return jsonify({"success": False, "error": "project_name is required"}), 400

        _resolve_env_setup()
        import DaVinciResolveScript as dvr_script  # type: ignore
        resolve = dvr_script.scriptapp("Resolve")
        if resolve is None:
            return jsonify({"success": False, "error": "DaVinci Resolve is not running or not reachable."}), 500

        pm = resolve.GetProjectManager()
        current = pm.GetCurrentProject()
        if current and current.GetName() == project_name:
            return jsonify({"success": True, "project": project_name, "already_open": True})

        ok = bool(pm.LoadProject(project_name))
        if not ok:
            return jsonify({
                "success": False,
                "error": f"LoadProject('{project_name}') returned False. Make sure the project exists in the currently selected Resolve project folder.",
            }), 400

        loaded = pm.GetCurrentProject()
        loaded_name = loaded.GetName() if loaded else project_name
        return jsonify({"success": True, "project": loaded_name, "already_open": False})
    except Exception as e:
        logger.error(f"❌ /api/resolve/load-project failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/resolve/list-timelines", methods=["GET"])
def api_resolve_list_timelines():
    """Return the current DaVinci Resolve project and its timelines."""
    try:
        _resolve_env_setup()
        import DaVinciResolveScript as dvr_script  # type: ignore
        resolve = dvr_script.scriptapp("Resolve")
        if resolve is None:
            return jsonify({"success": False, "error": "DaVinci Resolve is not running or not reachable."}), 500

        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject()
        if project is None:
            return jsonify({"success": False, "error": "No project is open in DaVinci Resolve."}), 400

        project_name = project.GetName()
        timelines = []
        for i in range(1, project.GetTimelineCount() + 1):
            tl = project.GetTimelineByIndex(i)
            if tl:
                timelines.append(tl.GetName())

        current_tl = project.GetCurrentTimeline()
        current_tl_name = current_tl.GetName() if current_tl else None

        return jsonify({
            "success": True,
            "project": project_name,
            "timelines": timelines,
            "current_timeline": current_tl_name,
        })
    except Exception as e:
        logger.error(
            f"❌ /api/resolve/list-timelines failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


def _audio_render_worker(session_id: str, timeline_name: str, output_path: str):
    """Background worker that runs the Resolve audio export and posts progress to the session queue."""
    q = audio_render_streams.get(session_id)
    if q is None:
        return

    def push(msg, progress=None, status="progress", **extra):
        payload = {"type": status, "message": msg}
        if progress is not None:
            payload["progress"] = progress
        if extra:
            payload.update(extra)
        q.put(payload)

    try:
        push(f"🔌 Connecting to DaVinci Resolve…", 5)
        _resolve_env_setup()
        import DaVinciResolveScript as dvr_script  # type: ignore
        resolve = dvr_script.scriptapp("Resolve")
        if resolve is None:
            push("❌ DaVinci Resolve is not running or not reachable.", status="error")
            audio_render_results[session_id] = {
                "success": False, "error": "Resolve not running"}
            return

        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject()
        if project is None:
            push("❌ No project is open in DaVinci Resolve.", status="error")
            audio_render_results[session_id] = {
                "success": False, "error": "No project open"}
            return

        push(f"🎬 Switching to timeline '{timeline_name}'…", 10)

        # Find and set the timeline
        tl = None
        for i in range(1, project.GetTimelineCount() + 1):
            t = project.GetTimelineByIndex(i)
            if t and t.GetName() == timeline_name:
                tl = t
                break
        if tl is None:
            push(f"❌ Timeline '{timeline_name}' not found.", status="error")
            audio_render_results[session_id] = {
                "success": False, "error": f"Timeline '{timeline_name}' not found"}
            return
        project.SetCurrentTimeline(tl)

        push(f"⚙️ Configuring render settings (WAV / 48 kHz / 24-bit)…", 20)
        output_dir = str(Path(output_path).parent)
        # Strip extension from CustomName — Resolve appends it based on format
        output_filename = Path(output_path).stem
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Try the "Audio Only" preset first (most reliable across Resolve versions)
        try:
            presets = project.GetRenderPresetList() or []
        except Exception:
            presets = []
        audio_preset = next(
            (p for p in presets if isinstance(p, str)
             and p.lower() in ("audio only", "audio_only")),
            None,
        )
        if audio_preset:
            try:
                project.LoadRenderPreset(audio_preset)
                push(f"   • Loaded render preset: {audio_preset}", 22)
            except Exception:
                pass

        # Set format+codec BEFORE SetRenderSettings (codec keys depend on format)
        try:
            project.SetCurrentRenderFormatAndCodec("wav", "LinearPCM")
        except Exception as _e:
            push(f"   • Note: SetCurrentRenderFormatAndCodec raised: {_e}", 22)

        # Minimal settings dict — Resolve rejects the entire dict if any key is
        # unknown for the current format. Audio-specific keys are already set
        # by the format/codec selection above.
        settings = {
            "SelectAllFrames": True,
            "TargetDir": output_dir,
            "CustomName": output_filename,
            "ExportVideo": False,
            "ExportAudio": True,
        }
        if not project.SetRenderSettings(settings):
            # Fallback: try without ExportVideo/ExportAudio (some Resolve versions reject these)
            push(
                "   • Initial SetRenderSettings rejected — retrying with minimal keys…", 23)
            minimal = {
                "SelectAllFrames": True,
                "TargetDir": output_dir,
                "CustomName": output_filename,
            }
            if not project.SetRenderSettings(minimal):
                push(
                    "❌ SetRenderSettings failed. Open Resolve → Deliver page, choose 'Audio Only' "
                    "preset manually once, then retry. Also verify the output directory exists and "
                    "is writable.",
                    status="error",
                )
                audio_render_results[session_id] = {
                    "success": False, "error": "SetRenderSettings failed"}
                return

        push(f"📋 Queueing render job…", 30)
        job_id = project.AddRenderJob()
        if not job_id:
            push(
                "❌ AddRenderJob failed. Check the Deliver page in Resolve.", status="error")
            audio_render_results[session_id] = {
                "success": False, "error": "AddRenderJob failed"}
            return

        if not project.StartRendering(job_id):
            project.DeleteRenderJobList()
            push("❌ StartRendering failed.", status="error")
            audio_render_results[session_id] = {
                "success": False, "error": "StartRendering failed"}
            return

        push(f"🎵 Render started — polling for completion…", 35)
        import time as _time
        deadline = _time.time() + 1800  # 30 min max
        job_status = ""
        while _time.time() < deadline:
            _time.sleep(3)
            status_info = project.GetRenderJobStatus(job_id) or {}
            job_status = status_info.get("JobStatus", "")
            completion_pct = status_info.get("CompletionPercentage", 0)
            sse_progress = 35 + int(completion_pct *
                                    0.6)  # maps 0-100% → 35-95%
            push(
                f"⏳ Rendering… {completion_pct:.0f}% ({job_status})", sse_progress)
            if job_status in ("Complete", "Cancelled", "Failed"):
                break

        if job_status != "Complete":
            push(f"❌ Render ended with status '{job_status}'.", status="error")
            audio_render_results[session_id] = {
                "success": False, "error": f"Render status: {job_status}"}
            return

        # Locate output file (Resolve appends extension; output_filename is stem only)
        candidates = sorted(Path(output_dir).glob(f"{output_filename}*.wav")) \
            or sorted(Path(output_dir).glob(f"{output_filename}*"))
        actual_file = str(
            candidates[0]) if candidates else f"{Path(output_dir) / output_filename}.wav"
        push(f"✅ Audio exported to: {actual_file}",
             100, status="done", output_file=actual_file)
        audio_render_results[session_id] = {
            "success": True, "output_file": actual_file}

    except Exception as e:
        logger.error(f"❌ _audio_render_worker failed: {e}", exc_info=True)
        push(f"❌ Unexpected error: {e}", status="error")
        audio_render_results[session_id] = {"success": False, "error": str(e)}
    finally:
        # Always clear the Resolve render queue so the next render starts clean.
        # Without this, stale completed/failed jobs accumulate and subsequent
        # AddRenderJob / StartRendering calls can wedge — forcing the user to
        # refresh the web GUI between renders.
        try:
            if 'project' in locals() and project is not None:
                project.DeleteRenderJobList()
        except Exception as _cleanup_err:
            logger.warning(
                f"audio render cleanup: DeleteRenderJobList raised {_cleanup_err}")


@app.route("/api/resolve/render-audio", methods=["POST"])
def api_resolve_render_audio_start():
    """Start an audio-only render job in DaVinci Resolve.

    Body JSON:
        {
            "timeline_name": "My Timeline",   (required)
            "script_title":  "My Script",     (used for output filename)
        }

    Returns:
        {"success": true, "session_id": "...", "stream_url": "..."}
    """
    try:
        data = request.get_json(silent=True) or {}
        timeline_name = (data.get("timeline_name") or "").strip()
        script_title = (data.get("script_title")
                        or "audio_export").strip() or "audio_export"

        if not timeline_name:
            return jsonify({"success": False, "error": "timeline_name is required"}), 400

        # Build output path: <output_dir>/<safe_title> (no extension; Resolve adds it)
        safe_title = re.sub(r'[^A-Za-z0-9._-]+', '_',
                            script_title).strip('_') or "audio"

        # Optional per-request output directory override (e.g. from pipeline modal)
        override_dir = (data.get("output_dir") or "").strip()
        if override_dir:
            try:
                cand = Path(override_dir).expanduser().resolve()
                cand.mkdir(parents=True, exist_ok=True)
                if not cand.is_dir():
                    raise ValueError(f"{cand} is not a directory")
                output_parent = cand
                logger.info(f"🎵 Using override output dir: {output_parent}")
            except Exception as e:
                return jsonify({"success": False, "error": f"Invalid output_dir: {e}"}), 400
        else:
            output_parent = _get_output_parent_dir()
        output_path = str(output_parent / safe_title)

        session_id = str(uuid.uuid4())
        audio_render_streams[session_id] = _queue.Queue()
        audio_render_results.pop(session_id, None)

        thread = _threading.Thread(
            target=_audio_render_worker,
            args=(session_id, timeline_name, output_path),
            daemon=True,
        )
        thread.start()

        logger.info(
            f"🎵 Audio render started: session={session_id} timeline='{timeline_name}' output='{output_path}'")
        return jsonify({
            "success": True,
            "session_id": session_id,
            "output_path": output_path,
            "stream_url": f"/api/resolve/render-audio/progress/{session_id}",
        })
    except Exception as e:
        logger.error(f"❌ /api/resolve/render-audio failed to start: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/resolve/render-audio/progress/<session_id>")
def api_resolve_render_audio_progress(session_id):
    """SSE stream of progress events for an in-flight audio render session."""
    q = audio_render_streams.get(session_id)
    if q is None:
        return "Session not found", 404

    def generate():
        try:
            while True:
                try:
                    payload = q.get(timeout=60)
                except _queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(payload)}\n\n"
                if payload.get("type") in ("done", "error"):
                    break
        finally:
            audio_render_streams.pop(session_id, None)

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


# ---------------------------------------------------------------------------
# Whisper transcription
# ---------------------------------------------------------------------------

# Local openai-whisper CLI (preferred). Falls back to OpenAI Whisper API if
# the CLI is not installed.
_WHISPER_CLI_CANDIDATES = [
    "/Library/Frameworks/Python.framework/Versions/3.14/bin/whisper",
    "/opt/homebrew/bin/whisper",
    "whisper",
]


def _find_whisper_cli():
    import shutil
    for c in _WHISPER_CLI_CANDIDATES:
        path = shutil.which(c) or (c if Path(c).is_file() else None)
        if path:
            return path
    return None


@app.route("/api/transcribe-audio/upload", methods=["POST"])
def api_transcribe_audio_upload():
    """Accept a browser-uploaded audio/video file and start transcription.

    multipart/form-data:
        file:     the audio/video file (required)
        model:    whisper model name (optional, default 'medium')
        language: ISO language code (optional)

    Returns: { success, session_id, stream_url }
    Stream events identical to /api/transcribe-audio/progress/<session_id>.
    """
    import tempfile
    import uuid
    import shutil as _shutil
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file uploaded (expected form field 'file')"}), 400
        f = request.files["file"]
        if not f or not f.filename:
            return jsonify({"success": False, "error": "Empty file upload"}), 400

        model = (request.form.get("model") or "medium").strip() or "medium"
        language = (request.form.get("language") or "").strip()
        output_dir_override = (request.form.get("output_dir") or "").strip() or None
        project_name_override = (request.form.get("project_name") or "").strip() or None

        whisper_bin = _find_whisper_cli()
        if not whisper_bin:
            return jsonify({
                "success": False,
                "error": "whisper CLI not found. Install with: pip install openai-whisper",
            }), 500

        # Save upload to a per-session temp dir; cleaned up by the worker’s rmtree of out_dir
        # is separate — we keep the input file in its own temp dir and let the OS clean tmp.
        upload_dir = Path(tempfile.mkdtemp(prefix="whisper_in_"))
        # Preserve a safe filename + original extension
        safe_name = Path(f.filename).name.replace("/", "_").replace("\\", "_")
        if not safe_name:
            safe_name = "upload.bin"
        src = upload_dir / safe_name
        f.save(str(src))

        if src.stat().st_size == 0:
            _shutil.rmtree(upload_dir, ignore_errors=True)
            return jsonify({"success": False, "error": "Uploaded file is empty"}), 400

        session_id = str(uuid.uuid4())
        transcribe_streams[session_id] = _queue.Queue()
        transcribe_results.pop(session_id, None)

        def _worker_then_cleanup():
            try:
                _transcribe_worker(session_id, whisper_bin,
                                   str(src), model, language,
                                   output_dir_override=output_dir_override,
                                   project_name_override=project_name_override)
            finally:
                _shutil.rmtree(upload_dir, ignore_errors=True)

        thread = _threading.Thread(target=_worker_then_cleanup, daemon=True)
        thread.start()

        logger.info(
            f"🎙️ Transcribe-upload started: session={session_id} file='{src.name}' model={model} size={src.stat().st_size}")
        return jsonify({
            "success": True,
            "session_id": session_id,
            "stream_url": f"/api/transcribe-audio/progress/{session_id}",
            "filename": src.name,
        })
    except Exception as e:
        logger.error(
            f"❌ /api/transcribe-audio/upload failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Finished Videos Gallery
# ---------------------------------------------------------------------------
# When FINISHED_VIDEOS_BLOB_CONTAINER is set, list/stream from Azure Blob
# Storage instead of the local iCloud folder. Auth uses DefaultAzureCredential
# (system-assigned managed identity in Container Apps; az login locally) and
# returns short-lived user-delegation SAS URLs so the browser streams the
# video directly from Azure with native HTTP Range support.
FINISHED_VIDEOS_ROOT = Path(
    os.path.expanduser(
        "~/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Podcast/Videos/Final"
    )
).resolve()
FINISHED_VIDEOS_BLOB_ACCOUNT = os.environ.get(
    "FINISHED_VIDEOS_BLOB_ACCOUNT", "linedrivestorage"
)
FINISHED_VIDEOS_BLOB_CONTAINER = os.environ.get(
    "FINISHED_VIDEOS_BLOB_CONTAINER", ""
).strip()
FINISHED_VIDEOS_SAS_MINUTES = int(
    os.environ.get("FINISHED_VIDEOS_SAS_MINUTES", "120")
)
_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
_MIME_MAP = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
}
# Cached user-delegation key (refreshed ~hourly)
_udk_cache: "dict[str, object]" = {"key": None, "expires": 0.0}


def _finished_videos_blob_service():
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient
    account_url = f"https://{FINISHED_VIDEOS_BLOB_ACCOUNT}.blob.core.windows.net"
    return BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())


def _get_user_delegation_key():
    import time as _t
    now = _t.time()
    if _udk_cache["key"] and now < float(_udk_cache["expires"]) - 300:
        return _udk_cache["key"]
    from datetime import datetime, timedelta, timezone
    svc = _finished_videos_blob_service()
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    expiry = datetime.now(timezone.utc) + timedelta(hours=2)
    key = svc.get_user_delegation_key(
        key_start_time=start, key_expiry_time=expiry)
    _udk_cache["key"] = key
    _udk_cache["expires"] = expiry.timestamp()
    return key


def _blob_sas_url(blob_name: str) -> str:
    from datetime import datetime, timedelta, timezone
    from urllib.parse import quote as _q
    from azure.storage.blob import generate_blob_sas, BlobSasPermissions
    udk = _get_user_delegation_key()
    expiry = datetime.now(timezone.utc) + \
        timedelta(minutes=FINISHED_VIDEOS_SAS_MINUTES)
    sas = generate_blob_sas(
        account_name=FINISHED_VIDEOS_BLOB_ACCOUNT,
        container_name=FINISHED_VIDEOS_BLOB_CONTAINER,
        blob_name=blob_name,
        user_delegation_key=udk,
        permission=BlobSasPermissions(read=True),
        expiry=expiry,
    )
    encoded = "/".join(_q(seg) for seg in blob_name.split("/"))
    return (
        f"https://{FINISHED_VIDEOS_BLOB_ACCOUNT}.blob.core.windows.net/"
        f"{FINISHED_VIDEOS_BLOB_CONTAINER}/{encoded}?{sas}"
    )


# --- Script artifact persistence (Feature 2) --------------------------------
# Generated artifacts are stored in Azure Blob so a script reloaded in any
# session (or after a refresh) restores them into the main-page tabs:
#   <script_id>/videos/<file>.mp4(+.json)   Grok videos, by permanent Script-ID
#   <script_id>/versions/<version_id>/...    everything else, by Script-Version
# Uses the same account + cached user-delegation key as the video gallery.
SCRIPT_ARTIFACTS_BLOB_CONTAINER = os.environ.get(
    "SCRIPT_ARTIFACTS_BLOB_CONTAINER", "script-artifacts"
).strip()
_artifacts_container_ready = {"done": False}


def _artifacts_enabled() -> bool:
    return bool(FINISHED_VIDEOS_BLOB_ACCOUNT and SCRIPT_ARTIFACTS_BLOB_CONTAINER)


def _safe_blob_id(s: str) -> str:
    return re.sub(r'[^A-Za-z0-9._\-]', '_', (s or '').strip()) or 'unknown'


def _artifacts_container():
    svc = _finished_videos_blob_service()
    cc = svc.get_container_client(SCRIPT_ARTIFACTS_BLOB_CONTAINER)
    if not _artifacts_container_ready["done"]:
        try:
            cc.create_container()
        except Exception:
            pass  # already exists, or no create permission (fine to read/write)
        _artifacts_container_ready["done"] = True
    return cc


def _artifacts_sas_url(blob_name: str) -> str:
    from datetime import datetime, timedelta, timezone
    from urllib.parse import quote as _q
    from azure.storage.blob import generate_blob_sas, BlobSasPermissions
    udk = _get_user_delegation_key()
    expiry = datetime.now(timezone.utc) + \
        timedelta(minutes=FINISHED_VIDEOS_SAS_MINUTES)
    sas = generate_blob_sas(
        account_name=FINISHED_VIDEOS_BLOB_ACCOUNT,
        container_name=SCRIPT_ARTIFACTS_BLOB_CONTAINER,
        blob_name=blob_name,
        user_delegation_key=udk,
        permission=BlobSasPermissions(read=True),
        expiry=expiry,
    )
    encoded = "/".join(_q(seg) for seg in blob_name.split("/"))
    return (
        f"https://{FINISHED_VIDEOS_BLOB_ACCOUNT}.blob.core.windows.net/"
        f"{SCRIPT_ARTIFACTS_BLOB_CONTAINER}/{encoded}?{sas}"
    )


def _artifacts_upload_bytes(blob_name: str, data, content_type: "Optional[str]" = None) -> bool:
    try:
        from azure.storage.blob import ContentSettings
        cc = _artifacts_container()
        cs = ContentSettings(
            content_type=content_type) if content_type else None
        cc.upload_blob(name=blob_name, data=data,
                       overwrite=True, content_settings=cs)
        return True
    except Exception as e:
        logger.warning(f"⚠️ artifact upload failed ({blob_name}): {e}")
        return False


def _artifacts_upload_file(blob_name: str, path, content_type: "Optional[str]" = None) -> bool:
    try:
        with open(path, "rb") as f:
            return _artifacts_upload_bytes(blob_name, f, content_type)
    except Exception as e:
        logger.warning(f"⚠️ artifact upload (file) failed ({blob_name}): {e}")
        return False


def _persist_grok_video(script_id: str, local_path, entry: dict) -> "Optional[str]":
    """Upload a generated Grok mp4 + sidecar metadata under
    <script_id>/videos/. Returns a read SAS URL for the mp4, or None if
    persistence is disabled/unavailable (generation must never break on this).
    """
    if not _artifacts_enabled() or not script_id:
        return None
    sid = _safe_blob_id(script_id)
    fname = os.path.basename(str(local_path))
    blob = f"{sid}/videos/{fname}"
    if not _artifacts_upload_file(blob, local_path, "video/mp4"):
        return None
    meta = {
        "filename": fname,
        "blob_name": blob,
        "search_term": entry.get("search_term", ""),
        "timecode": entry.get("timecode", ""),
        "description": entry.get("description", ""),
        "generated_prompt": entry.get("generated_prompt", ""),
        "script_id": sid,
    }
    _artifacts_upload_bytes(
        blob + ".json", json.dumps(meta).encode("utf-8"), "application/json")
    try:
        return _artifacts_sas_url(blob)
    except Exception:
        return None


def _list_grok_videos_for_script(script_id: str) -> list:
    """All persisted Grok videos for a Script-ID, with fresh SAS playback URLs."""
    if not _artifacts_enabled() or not script_id:
        return []
    sid = _safe_blob_id(script_id)
    out: list = []
    try:
        cc = _artifacts_container()
        names = [b.name for b in cc.list_blobs(name_starts_with=f"{sid}/videos/")]
        nameset = set(names)
        for n in sorted(x for x in names if x.lower().endswith(".mp4")):
            meta = {}
            if n + ".json" in nameset:
                try:
                    meta = json.loads(cc.download_blob(n + ".json").readall())
                except Exception:
                    meta = {}
            out.append({
                "filename": os.path.basename(n),
                "url": _artifacts_sas_url(n),
                "search_term": meta.get("search_term", ""),
                "timecode": meta.get("timecode", ""),
                "description": meta.get("description", ""),
                "generated_prompt": meta.get("generated_prompt", ""),
                "persisted": True,
            })
    except Exception as e:
        logger.warning(f"⚠️ listing grok videos failed for {script_id}: {e}")
    return out


@app.route("/api/script-artifacts/videos", methods=["GET"])
def api_script_artifacts_videos():
    """Restore previously generated Grok videos for a Script-ID."""
    script_id = (request.args.get("script_id") or "").strip()
    if not script_id:
        return jsonify({"success": False, "error": "script_id required"}), 400
    vids = _list_grok_videos_for_script(script_id)
    return jsonify({"success": True, "videos": vids, "count": len(vids)})


# --- Phase C: persist + restore ALL artifacts of a Script-Version -----------
def _find_media_file(filename: str) -> "Optional[Path]":
    """Locate a generated thumbnail/b-roll image on disk by filename (mirrors
    the /thumbnails and /broll-images serving routes)."""
    if not filename:
        return None
    for root in (_get_output_parent_dir(),
                 Path.home() / "Dev" / "Thumbnails",
                 Path.home() / "Dev" / "brollimages"):
        try:
            if root.exists():
                matches = list(root.rglob(filename))
                if matches:
                    return matches[0]
        except Exception:
            continue
    return None


def _persist_version_artifacts(script_id: str, version_id: str, result: dict,
                               script_title: str = "") -> None:
    """Upload every artifact produced by a create/process run to Azure under
    <script_id>/versions/<version_id>/ so the script reopened later restores
    its tabs. Text artifacts go in artifacts.json; thumbnails + b-roll images
    are uploaded as files (durable SAS urls served on restore). Grok videos are
    persisted separately by Script-ID. Never raises into the caller.
    """
    if not _artifacts_enabled() or not script_id or not version_id or not result:
        return
    try:
        sid = _safe_blob_id(script_id)
        vid = _safe_blob_id(version_id)
        prefix = f"{sid}/versions/{vid}"
        title = script_title or result.get("script_title", "")

        # Thumbnails (collect entries, upload each image file).
        thumb_entries = []
        try:
            tlist = _collect_all_thumbnail_entries(
                title, result.get("thumbnail_results"))
        except Exception:
            tlist = result.get("thumbnails") or []
        for t in (tlist or []):
            fn = (t.get("filename") or "").split("/")[-1]
            if not fn:
                continue
            fp = _find_media_file(fn)
            blob = f"{prefix}/thumbnails/{fn}"
            if fp and _artifacts_upload_file(blob, fp, "image/png"):
                thumb_entries.append({
                    "filename": fn, "blob_name": blob,
                    "emotion": t.get("emotion", ""), "text": t.get("text", ""),
                })

        # B-roll images.
        broll_entries = []
        for b in (result.get("broll_images") or []):
            fn = ((b.get("filename") or b.get("filepath") or "")
                  .split("/")[-1])
            if not fn:
                continue
            fp = _find_media_file(fn)
            blob = f"{prefix}/broll/{fn}"
            if fp and _artifacts_upload_file(blob, fp, "image/png"):
                broll_entries.append({
                    "filename": fn, "blob_name": blob,
                    "search_term": b.get("search_term", ""),
                    "timecode": b.get("timecode", ""),
                })

        # The initial generated script body + the creative brief that produced
        # it, so both can be pulled back from the cloud (and recent scripts can
        # seed style context for future generations). A reprocess run bumps the
        # version and carries no brief — carry the newest prior brief forward so
        # every version's manifest stays self-contained (single-read listing).
        enhanced_script = (result.get("enhanced_script")
                           or result.get("script") or "")
        brief = (result.get("brief") or "").strip()
        if not brief:
            try:
                brief = (_read_latest_brief_for_script(script_id) or "").strip()
            except Exception:
                brief = ""

        manifest = {
            "script_id": sid, "version_id": vid, "script_title": title,
            "enhanced_script": enhanced_script,
            "brief": brief,
            "broll_table": result.get("broll_table"),
            "broll_rows": result.get("broll_rows"),
            "youtube_details": result.get("youtube_details"),
            "demo_packages": result.get("demo_packages"),
            "flow_original_script": result.get("flow_original_script"),
            "flow_improved_script": result.get("flow_improved_script"),
            "flow_analysis_report": result.get("flow_analysis_report"),
            "chapter_comparisons": result.get("chapter_comparisons"),
            "edl_content": result.get("edl_content"),
            "edl_filename": result.get("edl_filename"),
            "curl_commands": result.get("curl_commands"),
            "hooks": result.get("hooks"),
            "hook_labels": result.get("hook_labels"),
            "thumbnails": thumb_entries,
            "broll_images": broll_entries,
        }
        _artifacts_upload_bytes(
            f"{prefix}/artifacts.json",
            json.dumps(manifest).encode("utf-8"), "application/json")
        logger.info(
            f"📦 Persisted version artifacts {sid}/{vid}: "
            f"{len(thumb_entries)} thumbnails, {len(broll_entries)} b-roll images")
    except Exception as e:
        logger.warning(f"⚠️ persist version artifacts failed: {e}")


def _read_version_artifacts(script_id: str, version_id: str) -> "Optional[dict]":
    """Read a version's artifacts.json and attach fresh SAS urls to media."""
    if not _artifacts_enabled() or not script_id or not version_id:
        return None
    sid = _safe_blob_id(script_id)
    vid = _safe_blob_id(version_id)
    try:
        cc = _artifacts_container()
        raw = cc.download_blob(f"{sid}/versions/{vid}/artifacts.json").readall()
        manifest = json.loads(raw)
    except Exception:
        return None
    for t in (manifest.get("thumbnails") or []):
        if t.get("blob_name"):
            try:
                t["url"] = _artifacts_sas_url(t["blob_name"])
            except Exception:
                pass
    for b in (manifest.get("broll_images") or []):
        if b.get("blob_name"):
            try:
                b["url"] = _artifacts_sas_url(b["blob_name"])
            except Exception:
                pass
    return manifest


@app.route("/api/script-artifacts/version", methods=["GET"])
def api_script_artifacts_version():
    """Restore all stored artifacts for a specific Script-Version."""
    script_id = (request.args.get("script_id") or "").strip()
    version_id = (request.args.get("version_id") or "").strip()
    if not script_id or not version_id:
        return jsonify({"success": False,
                        "error": "script_id and version_id required"}), 400
    data = _read_version_artifacts(script_id, version_id)
    if data is None:
        return jsonify({"success": True, "found": False})
    return jsonify({"success": True, "found": True, "artifacts": data})


def _read_latest_broll_table_for_script(script_id: str) -> "Optional[dict]":
    """Newest persisted B-roll table for a Script-ID, across ALL versions.

    Version artifacts are keyed by exact Script-Version, but every processing
    run (including a standalone B-roll agent run) bumps the version — so a
    script reloaded from an older file points at a version whose manifest
    predates the table. This walks every version manifest for the Script-ID,
    newest-written first, and returns the first B-roll table it finds — so the
    table (and its Shutterstock links) come back on load without re-running the
    agent. Restore-by-Script-ID, the same way Grok videos are restored.
    Returns {"broll_table", "broll_rows", "version_id"} or None.
    """
    if not _artifacts_enabled() or not script_id:
        return None
    sid = _safe_blob_id(script_id)
    try:
        cc = _artifacts_container()
        blobs = [
            b for b in cc.list_blobs(name_starts_with=f"{sid}/versions/")
            if b.name.endswith("/artifacts.json")
            and getattr(b, "last_modified", None)
        ]
        # Version ids are random, not time-ordered — sort by blob write time.
        blobs.sort(key=lambda b: b.last_modified, reverse=True)
        for b in blobs:
            try:
                manifest = json.loads(cc.download_blob(b.name).readall())
            except Exception:
                continue
            table = manifest.get("broll_table")
            if table and str(table).strip():
                return {
                    "broll_table": table,
                    "broll_rows": manifest.get("broll_rows"),
                    "version_id": manifest.get("version_id"),
                }
    except Exception as e:
        logger.warning(
            f"⚠️ latest broll table lookup failed for {script_id}: {e}")
    return None


@app.route("/api/script-artifacts/latest-broll", methods=["GET"])
def api_script_artifacts_latest_broll():
    """Newest persisted B-roll table for a Script-ID (across versions)."""
    script_id = (request.args.get("script_id") or "").strip()
    if not script_id:
        return jsonify({"success": False, "error": "script_id required"}), 400
    data = _read_latest_broll_table_for_script(script_id)
    if not data:
        return jsonify({"success": True, "found": False})
    return jsonify({"success": True, "found": True, **data})


def _read_latest_brief_for_script(script_id: str) -> "Optional[str]":
    """Newest persisted creative brief for a Script-ID, across ALL versions.

    Only the create run carries a brief; reprocess runs bump the version with
    no brief. Walk every version manifest newest-written first and return the
    first non-empty brief. Mirrors _read_latest_broll_table_for_script.
    """
    if not _artifacts_enabled() or not script_id:
        return None
    sid = _safe_blob_id(script_id)
    try:
        cc = _artifacts_container()
        blobs = [
            b for b in cc.list_blobs(name_starts_with=f"{sid}/versions/")
            if b.name.endswith("/artifacts.json")
            and getattr(b, "last_modified", None)
        ]
        blobs.sort(key=lambda b: b.last_modified, reverse=True)
        for b in blobs:
            try:
                manifest = json.loads(cc.download_blob(b.name).readall())
            except Exception:
                continue
            brief = manifest.get("brief")
            if brief and str(brief).strip():
                return str(brief)
    except Exception as e:
        logger.warning(f"⚠️ latest brief lookup failed for {script_id}: {e}")
    return None


# How many recent scripts to expose in the cloud picker / feed as style memory,
# and how much of each script to include as a style sample (chars).
_CLOUD_SCRIPTS_MAX = 50
_STYLE_CONTEXT_SCRIPTS = 8
_STYLE_CONTEXT_CHARS_PER_SCRIPT = 2000


def _list_cloud_scripts(limit: int = _CLOUD_SCRIPTS_MAX) -> list:
    """List saved scripts in the cloud, newest first, one entry per Script-ID.

    Walks every version manifest, groups by Script-ID, and keeps the
    newest-written version per script. Returns lightweight cards:
    {script_id, version_id, title, created, has_script, has_brief, word_count}.
    """
    if not _artifacts_enabled():
        return []
    try:
        cc = _artifacts_container()
        # Newest artifacts.json per Script-ID (first path segment).
        newest: "dict[str, object]" = {}
        for b in cc.list_blobs():
            name = getattr(b, "name", "") or ""
            if not name.endswith("/artifacts.json") or "/versions/" not in name:
                continue
            if not getattr(b, "last_modified", None):
                continue
            sid = name.split("/", 1)[0]
            cur = newest.get(sid)
            if cur is None or b.last_modified > cur.last_modified:
                newest[sid] = b
        # Newest scripts first; cap how many manifests we actually download.
        ordered = sorted(
            newest.values(), key=lambda b: b.last_modified, reverse=True)
        truncated = len(ordered) > limit
        ordered = ordered[:limit]
        cards = []
        for b in ordered:
            try:
                m = json.loads(cc.download_blob(b.name).readall())
            except Exception:
                continue
            script_text = (m.get("enhanced_script") or "").strip()
            cards.append({
                "script_id": m.get("script_id") or b.name.split("/", 1)[0],
                "version_id": m.get("version_id"),
                "title": (m.get("script_title") or "Untitled").strip(),
                "created": b.last_modified.isoformat(),
                "has_script": bool(script_text),
                "has_brief": bool((m.get("brief") or "").strip()),
                "word_count": len(script_text.split()) if script_text else 0,
            })
        if truncated:
            logger.info(
                f"ℹ️ Cloud script list truncated to newest {limit} "
                f"(of {len(newest)} total scripts)")
        return cards
    except Exception as e:
        logger.warning(f"⚠️ list cloud scripts failed: {e}")
        return []


@app.route("/api/cloud-scripts", methods=["GET"])
def api_cloud_scripts():
    """List saved scripts in the cloud for the Load-from-Cloud picker."""
    if not _artifacts_enabled():
        return jsonify({"success": True, "enabled": False, "scripts": []})
    try:
        limit = int(request.args.get("limit", _CLOUD_SCRIPTS_MAX))
    except (TypeError, ValueError):
        limit = _CLOUD_SCRIPTS_MAX
    scripts = _list_cloud_scripts(max(1, min(limit, 200)))
    return jsonify({"success": True, "enabled": True,
                    "scripts": scripts, "count": len(scripts)})


def _recent_scripts_for_style_context(
        limit: int = _STYLE_CONTEXT_SCRIPTS,
        exclude_script_id: str = "") -> list:
    """The newest saved scripts (title + trimmed body) to seed style memory for
    a new generation. Returns [{title, excerpt}] newest first, skipping the
    current Script-ID and any script with no body. Best-effort; never raises.
    """
    if not _artifacts_enabled():
        return []
    exclude = _safe_blob_id(exclude_script_id) if exclude_script_id else ""
    out = []
    try:
        cc = _artifacts_container()
        newest: "dict[str, object]" = {}
        for b in cc.list_blobs():
            name = getattr(b, "name", "") or ""
            if not name.endswith("/artifacts.json") or "/versions/" not in name:
                continue
            if not getattr(b, "last_modified", None):
                continue
            sid = name.split("/", 1)[0]
            if exclude and sid == exclude:
                continue
            cur = newest.get(sid)
            if cur is None or b.last_modified > cur.last_modified:
                newest[sid] = b
        # Scan a few more than `limit` so reference-flagged scripts can jump the
        # queue, then rank reference-first, newest-first.
        candidates = sorted(
            newest.values(), key=lambda b: b.last_modified,
            reverse=True)[:max(limit * 3, 12)]
        rows = []
        for b in candidates:
            try:
                m = json.loads(cc.download_blob(b.name).readall())
            except Exception:
                continue
            body = (m.get("enhanced_script") or "").strip()
            if not body:
                continue
            rows.append((
                bool(m.get("reference") or m.get("final")),
                b.last_modified,
                (m.get("script_title") or "Untitled").strip(),
                body,
            ))
        rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
        for _is_ref, _lm, title, body in rows[:limit]:
            out.append({
                "title": title + (" [REFERENCE]" if _is_ref else ""),
                "excerpt": body[:_STYLE_CONTEXT_CHARS_PER_SCRIPT],
            })
    except Exception as e:
        logger.warning(f"⚠️ recent scripts (style context) lookup failed: {e}")
    return out


def _set_script_reference_flag(script_id: str, version_id: str,
                               reference: bool = True) -> bool:
    """Read a version manifest, set its `reference` (and `final`) flag, and
    re-upload it. Reference scripts lead the style context for new generations."""
    if not _artifacts_enabled() or not script_id or not version_id:
        return False
    sid = _safe_blob_id(script_id)
    vid = _safe_blob_id(version_id)
    try:
        cc = _artifacts_container()
        path = f"{sid}/versions/{vid}/artifacts.json"
        m = json.loads(cc.download_blob(path).readall())
        m["reference"] = bool(reference)
        m["final"] = bool(reference)  # a marked reference == a production-final
        _artifacts_upload_bytes(
            path, json.dumps(m).encode("utf-8"), "application/json")
        return True
    except Exception as e:
        logger.warning(f"⚠️ mark-reference failed for {script_id}/{version_id}: {e}")
        return False


@app.route("/api/script/mark-reference", methods=["POST"])
def api_script_mark_reference():
    """Mark a saved cloud script as a REFERENCE (used in production / golden).
    Reference scripts lead the style context fed into every new generation."""
    data = request.get_json(silent=True) or {}
    sid = (data.get("script_id") or "").strip()
    vid = (data.get("version_id") or "").strip()
    ref = bool(data.get("reference", True))
    if not sid or not vid:
        return jsonify({
            "success": False,
            "error": "script_id and version_id are required — save the script "
                     "to the cloud first.",
        }), 400
    ok = _set_script_reference_flag(sid, vid, ref)
    if ok:
        logger.info("⭐ Marked %s/%s reference=%s", sid, vid, ref)
    return jsonify({"success": ok})


_GOLDEN_CLOUD_SID = "golden-reference"
_GOLDEN_CLOUD_VID = "v1"


def _seed_golden_reference_to_cloud() -> bool:
    """Upload the local golden reference script to the cloud as a reference
    script, once. Best-effort and idempotent (skips if already present)."""
    if not _artifacts_enabled():
        return False
    try:
        from linedrive_azure.agents.pro_script_writer import load_golden_reference
        body = load_golden_reference(max_chars=100000)
        if not body:
            return False
        cc = _artifacts_container()
        path = f"{_GOLDEN_CLOUD_SID}/versions/{_GOLDEN_CLOUD_VID}/artifacts.json"
        try:
            existing = json.loads(cc.download_blob(path).readall())
            if (existing.get("enhanced_script") or "").strip():
                return True  # already seeded
        except Exception:
            pass
        manifest = {
            "script_id": _GOLDEN_CLOUD_SID,
            "version_id": _GOLDEN_CLOUD_VID,
            "script_title": "GOLDEN REFERENCE — The Top 10 AI Tools, When NOT to Use Them",
            "enhanced_script": body,
            "brief": "",
            "reference": True,
            "final": True,
        }
        _artifacts_upload_bytes(
            path, json.dumps(manifest).encode("utf-8"), "application/json")
        logger.info("⭐ Seeded golden reference script to the cloud (reference)")
        return True
    except Exception as e:
        logger.warning(f"⚠️ seed golden reference to cloud failed: {e}")
        return False


@app.route("/api/golden-reference/save-to-cloud", methods=["POST"])
def api_golden_reference_save_to_cloud():
    """Save the golden reference script to the cloud, marked as a reference."""
    ok = _seed_golden_reference_to_cloud()
    return jsonify({"success": ok,
                    "enabled": _artifacts_enabled()})


def _build_style_context_block(exclude_script_id: str = "") -> str:
    """A delimited style-reference block built from recent saved scripts, or ''
    when style memory is unavailable/empty. Fed to the Script Writer so new
    scripts stay consistent in voice, structure, and pacing with recent work.
    """
    parts = []
    # The GOLDEN REFERENCE always leads — it is the approved target the user
    # wants every generation to follow (the Pro single-pass writer embeds the
    # full copy; the Foundry pipeline gets a trimmed copy here).
    try:
        from linedrive_azure.agents.pro_script_writer import load_golden_reference
        golden = load_golden_reference(max_chars=9000)
    except Exception:
        golden = ""
    if golden:
        parts.append(
            "\n\n--- GOLDEN REFERENCE SCRIPT (the approved target: match this "
            "STRUCTURE, production conventions, and SPOKEN VOICE exactly — no "
            "contractions, no em-dashes or en-dashes, numbers and names spelled "
            "the way the avatar says them, a FINAL HOOK, 'Heading: Chapter N -' "
            "lines, [PRODUCTION BEGIN] / [GROK IMAGINE / RESOLVE] / [PRODUCTION "
            "END] blocks, [VERIFY BEFORE RENDER] for legal or numeric claims, a "
            "cheat-sheet [PROMPT OVERLAY] in the final chapter, and trailing "
            "=== … === sections. Do NOT copy its topic or wording) ---\n"
            + golden + "\n--- END GOLDEN REFERENCE ---\n"
        )
    recent = _recent_scripts_for_style_context(
        exclude_script_id=exclude_script_id)
    if recent:
        parts.append(
            "\n\n--- STYLE REFERENCE: recent scripts (match their voice, "
            "structure, and pacing; do NOT copy their topics or content) ---")
        for i, r in enumerate(recent, 1):
            parts.append(
                f"\n[Recent script {i} — \"{r['title']}\"]\n{r['excerpt']}")
        parts.append("\n--- END STYLE REFERENCE ---\n")
    if not parts:
        return ""
    logger.info(
        f"🎨 Style memory: golden reference=%s + %d recent script(s) seeded "
        "as style context", "yes" if golden else "no", len(recent))
    return "".join(parts)


def _list_finished_videos_from_blob():
    """Returns (items, source_label) by listing blobs in the configured container.

    Groups by the first path segment ('folder'); picks the first video blob in
    each group. Loose root-level video blobs become their own cards.
    """
    svc = _finished_videos_blob_service()
    container = svc.get_container_client(FINISHED_VIDEOS_BLOB_CONTAINER)
    folders: "dict[str, list]" = {}
    loose: list = []
    poster_stems: set = set()
    for b in container.list_blobs():
        name = b.name
        if not name or name.endswith("/"):
            continue
        ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
        if ext == ".jpg":
            poster_stems.add(name[:-4])
            continue
        if ext not in _VIDEO_EXTS:
            continue
        if "/" in name:
            folder = name.split("/", 1)[0]
            folders.setdefault(folder, []).append(b)
        else:
            loose.append(b)

    def _poster_for(blob_name: str):
        stem = blob_name.rsplit(".", 1)[0]
        if stem in poster_stems:
            return _blob_sas_url(stem + ".jpg")
        return None

    items = []
    for folder in sorted(folders.keys(), key=str.lower):
        blobs = sorted(folders[folder], key=lambda x: x.name.lower())
        b = blobs[0]
        size = getattr(b, "size", 0) or 0
        mtime = 0.0
        try:
            if getattr(b, "last_modified", None):
                mtime = b.last_modified.timestamp()
        except Exception:  # noqa: BLE001
            mtime = 0.0
        ext = b.name.rsplit(".", 1)[-1].lower()
        items.append({
            "title": folder,
            "filename": b.name.rsplit("/", 1)[-1],
            "rel_path": b.name,
            "ext": ext,
            "size": size,
            "mtime": mtime,
            "stream_url": _blob_sas_url(b.name),
            "poster_url": _poster_for(b.name),
        })
    for b in sorted(loose, key=lambda x: x.name.lower()):
        size = getattr(b, "size", 0) or 0
        mtime = 0.0
        try:
            if getattr(b, "last_modified", None):
                mtime = b.last_modified.timestamp()
        except Exception:  # noqa: BLE001
            mtime = 0.0
        ext = b.name.rsplit(".", 1)[-1].lower()
        stem = b.name.rsplit(".", 1)[0]
        items.append({
            "title": stem,
            "filename": b.name,
            "rel_path": b.name,
            "ext": ext,
            "size": size,
            "mtime": mtime,
            "stream_url": _blob_sas_url(b.name),
            "poster_url": _poster_for(b.name),
        })
    label = (
        f"azure://{FINISHED_VIDEOS_BLOB_ACCOUNT}/"
        f"{FINISHED_VIDEOS_BLOB_CONTAINER}"
    )
    return items, label


@app.route("/api/finished-videos", methods=["GET"])
def api_finished_videos():
    """List finished videos (Azure Blob if configured, else local iCloud folder)."""
    from urllib.parse import quote
    try:
        if FINISHED_VIDEOS_BLOB_CONTAINER:
            try:
                items, label = _list_finished_videos_from_blob()
                return jsonify({"success": True, "root": label,
                                "source": "blob", "videos": items})
            except Exception as e:  # noqa: BLE001
                logger.error(f"❌ blob listing failed: {e}", exc_info=True)
                return jsonify({
                    "success": False,
                    "error": f"Azure blob listing failed: {e}",
                    "root": (f"azure://{FINISHED_VIDEOS_BLOB_ACCOUNT}/"
                             f"{FINISHED_VIDEOS_BLOB_CONTAINER}"),
                    "source": "blob",
                    "videos": [],
                }), 500

        root = FINISHED_VIDEOS_ROOT
        if not root.exists() or not root.is_dir():
            return jsonify({
                "success": False,
                "error": f"Finished videos folder not found: {root}",
                "root": str(root),
                "source": "local",
                "videos": [],
            }), 404

        items = []
        for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                vids = sorted(
                    [p for p in entry.iterdir()
                     if p.is_file() and p.suffix.lower() in _VIDEO_EXTS
                     and not p.name.startswith(".")],
                    key=lambda p: p.name.lower(),
                )
                if not vids:
                    continue
                vid = vids[0]
                rel = vid.relative_to(root).as_posix()
                try:
                    size = vid.stat().st_size
                    mtime = vid.stat().st_mtime
                except OSError:
                    size, mtime = 0, 0
                items.append({
                    "title": entry.name,
                    "filename": vid.name,
                    "rel_path": rel,
                    "ext": vid.suffix.lower().lstrip("."),
                    "size": size,
                    "mtime": mtime,
                    "stream_url": f"/api/finished-videos/file?path={quote(rel)}",
                })
            elif entry.is_file() and entry.suffix.lower() in _VIDEO_EXTS:
                rel = entry.name
                try:
                    size = entry.stat().st_size
                    mtime = entry.stat().st_mtime
                except OSError:
                    size, mtime = 0, 0
                items.append({
                    "title": entry.stem,
                    "filename": entry.name,
                    "rel_path": rel,
                    "ext": entry.suffix.lower().lstrip("."),
                    "size": size,
                    "mtime": mtime,
                    "stream_url": f"/api/finished-videos/file?path={quote(rel)}",
                })

        return jsonify({"success": True, "root": str(root),
                        "source": "local", "videos": items})
    except Exception as e:
        logger.error(f"❌ /api/finished-videos failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/finished-videos/file", methods=["GET"])
def api_finished_videos_file():
    """Stream a local video file (used in local mode only)."""
    try:
        rel = request.args.get("path", "").strip()
        if not rel:
            return jsonify({"success": False, "error": "Missing 'path' query param"}), 400
        root = FINISHED_VIDEOS_ROOT
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return jsonify({"success": False, "error": "Path escapes finished-videos root"}), 400
        if not candidate.is_file():
            return jsonify({"success": False, "error": "File not found"}), 404
        if candidate.suffix.lower() not in _VIDEO_EXTS:
            return jsonify({"success": False, "error": "Not a supported video type"}), 400
        mimetype = _MIME_MAP.get(
            candidate.suffix.lower(), "application/octet-stream")
        return send_file(str(candidate), mimetype=mimetype, conditional=True)
    except Exception as e:
        logger.error(f"❌ /api/finished-videos/file failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/finished-videos/delete", methods=["POST"])
def api_finished_videos_delete():
    """Delete a finished video from the gallery.

    POST body: {"rel_path": "<blob name or local rel path>"}

    - When FINISHED_VIDEOS_BLOB_CONTAINER is set: deletes the blob, plus any
      sibling `<stem>.jpg` poster blob.
    - Otherwise: deletes the local file under FINISHED_VIDEOS_ROOT. If the
      parent folder is then empty, removes the folder as well.
    """
    try:
        data = request.get_json(silent=True) or {}
        rel = (data.get("rel_path") or data.get("path") or "").strip()
        if not rel:
            return jsonify({"success": False, "error": "Missing 'rel_path'"}), 400
        if ".." in rel.split("/") or rel.startswith("/"):
            return jsonify({"success": False, "error": "Invalid path"}), 400

        # Azure Blob mode
        if FINISHED_VIDEOS_BLOB_CONTAINER:
            try:
                svc = _finished_videos_blob_service()
                container = svc.get_container_client(
                    FINISHED_VIDEOS_BLOB_CONTAINER)
                deleted = []
                try:
                    container.delete_blob(rel)
                    deleted.append(rel)
                except Exception as e:  # noqa: BLE001
                    logger.error(f"❌ blob delete failed for {rel}: {e}")
                    return jsonify({
                        "success": False,
                        "error": f"Blob delete failed: {e}",
                    }), 500
                # Best-effort: delete sidecar poster <stem>.jpg
                if "." in rel:
                    stem = rel.rsplit(".", 1)[0]
                    for poster in (stem + ".jpg", stem + ".jpeg"):
                        try:
                            container.delete_blob(poster)
                            deleted.append(poster)
                        except Exception:  # noqa: BLE001
                            pass
                return jsonify({"success": True, "deleted": deleted,
                                "source": "blob"})
            except Exception as e:  # noqa: BLE001
                logger.error(f"❌ /api/finished-videos/delete (blob) "
                             f"failed: {e}", exc_info=True)
                return jsonify({"success": False, "error": str(e)}), 500

        # Local mode
        root = FINISHED_VIDEOS_ROOT
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return jsonify({"success": False,
                            "error": "Path escapes finished-videos root"}), 400
        if not candidate.is_file():
            return jsonify({"success": False, "error": "File not found"}), 404
        if candidate.suffix.lower() not in _VIDEO_EXTS:
            return jsonify({"success": False,
                            "error": "Not a supported video type"}), 400
        try:
            candidate.unlink()
        except Exception as e:  # noqa: BLE001
            return jsonify({"success": False,
                            "error": f"Delete failed: {e}"}), 500
        deleted = [str(candidate.relative_to(root))]
        # Best-effort: matching local poster
        for suf in (".jpg", ".jpeg", ".png"):
            poster = candidate.with_suffix(suf)
            if poster.exists():
                try:
                    poster.unlink()
                    deleted.append(str(poster.relative_to(root)))
                except Exception:  # noqa: BLE001
                    pass
        # If parent folder is now empty (and isn't the gallery root), drop it.
        try:
            parent = candidate.parent
            if parent != root and parent.is_dir() and not any(
                p for p in parent.iterdir() if not p.name.startswith(".")
            ):
                parent.rmdir()
        except Exception:  # noqa: BLE001
            pass
        return jsonify({"success": True, "deleted": deleted,
                        "source": "local"})
    except Exception as e:  # noqa: BLE001
        logger.error(
            f"❌ /api/finished-videos/delete failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/grok-videos/delete", methods=["POST"])
def api_grok_video_delete():
    """Delete a single Grok-generated B-roll video file by filename.

    POST body: {"filename": "grok_20260517_0_clip.mp4"}

    Searches the same candidate directories used by /broll-videos/<filename>
    and deletes every matching .mp4 it finds (covers both the current run's
    output dir and the legacy ~/Dev/brollvideos cache).
    """
    try:
        data = request.get_json(silent=True) or {}
        raw_name = (data.get("filename") or "").strip()
        if not raw_name:
            return jsonify({"success": False, "error": "Missing 'filename'"}), 400
        safe_name = Path(raw_name).name  # strip any path components
        if not safe_name or not safe_name.lower().endswith(".mp4"):
            return jsonify({"success": False,
                            "error": "Filename must be a .mp4"}), 400

        candidates = []
        base = _get_output_base_dir()
        if base is not None:
            candidates.append(base / "broll" / safe_name)
            for run_broll in base.glob("*/broll"):
                candidates.append(run_broll / safe_name)
        candidates.append(Path.home() / "Dev" / "brollvideos" / safe_name)

        deleted = []
        for path in candidates:
            try:
                if path.exists() and path.is_file():
                    path.unlink()
                    deleted.append(str(path))
            except Exception as e:  # noqa: BLE001
                logger.error(f"❌ grok-video delete failed for {path}: {e}")

        # Also delete the DURABLE blob copy (mp4 + sidecar .json) under
        # <script_id>/videos/. Without this the video reappears from Azure on the
        # next load as a dead grey card (local file gone, blob entry still there).
        blob_deleted = []
        script_id = (data.get("script_id") or "").strip()
        if script_id and _artifacts_enabled():
            try:
                cc = _artifacts_container()
                sid = _safe_blob_id(script_id)
                for bn in (f"{sid}/videos/{safe_name}",
                           f"{sid}/videos/{safe_name}.json"):
                    try:
                        cc.delete_blob(bn)
                        blob_deleted.append(bn)
                    except Exception as be:  # noqa: BLE001
                        # Missing blob (already gone) is fine — anything else logs.
                        logger.info(
                            f"grok-video blob delete skipped {bn}: {be}")
            except Exception as e:  # noqa: BLE001
                logger.error(f"❌ grok-video blob delete failed: {e}")

        # Idempotent: even if the file was already gone locally AND in blob, the
        # desired end state (not present anywhere) is met — return success so the
        # gallery always removes the card. This is what clears the leftover grey
        # boxes for blob-only videos that have no local file to unlink.
        return jsonify({"success": True, "deleted": deleted,
                        "blob_deleted": blob_deleted, "filename": safe_name})
    except Exception as e:  # noqa: BLE001
        logger.error(
            f"❌ /api/grok-videos/delete failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


def _video_height(path) -> int:
    """Return the pixel height of a video's first stream via ffprobe, or 0."""
    try:
        import subprocess
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=height", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30)
        return int((out.stdout or "0").strip().split("\n")[0] or 0)
    except Exception:
        return 0


@app.route("/api/grok/upscale", methods=["POST"])
def api_grok_upscale():
    """Upscale ONE generated Grok video to 1080p (ffmpeg). The gallery calls this
    once per checked video. Resolves a local copy (or pulls the blob down),
    upscales in place, and re-persists to blob so the durable copy + gallery both
    get the HD version. Skips re-encoding if the clip is already ≥1080p.

    POST body: {"filename": "grok_..mp4", "script_id": "..", "blob_name": ".."}
    """
    try:
        import shutil
        import tempfile
        data = request.get_json(silent=True) or {}
        safe_name = Path((data.get("filename") or "").strip()).name
        script_id = (data.get("script_id") or "").strip()
        blob_name = (data.get("blob_name") or "").strip()
        if not safe_name or not safe_name.lower().endswith(".mp4"):
            return jsonify({"success": False,
                            "error": "filename must be a .mp4"}), 400
        if shutil.which("ffmpeg") is None:
            return jsonify({"success": False,
                            "error": "ffmpeg not available on the server"}), 500

        derived_blob = blob_name or (
            f"{_safe_blob_id(script_id)}/videos/{safe_name}"
            if script_id else "")

        # Resolve a local copy; otherwise pull the blob down to a temp file.
        local = _resolve_media_file(safe_name, "video")
        tmpdir = None
        if local is None and _artifacts_enabled() and derived_blob:
            try:
                raw = _artifacts_container().download_blob(
                    derived_blob).readall()
                tmpdir = Path(tempfile.mkdtemp(prefix="grok_upscale_"))
                local = tmpdir / safe_name
                local.write_bytes(raw)
            except Exception as e:
                return jsonify({"success": False,
                                "error": f"could not fetch video: {e}"}), 404
        if local is None or not Path(local).exists():
            return jsonify({"success": False,
                            "error": "video file not found"}), 404

        cur_h = _video_height(local)
        already = bool(cur_h and cur_h >= 1080)
        if not already:
            if not _upscale_video_to_1080p(local):
                if tmpdir:
                    shutil.rmtree(tmpdir, ignore_errors=True)
                return jsonify({"success": False,
                                "error": "upscale failed"}), 500
            # Keep the durable blob copy in sync with the new HD file.
            if _artifacts_enabled() and derived_blob:
                try:
                    _artifacts_upload_file(derived_blob, local, "video/mp4")
                except Exception as e:
                    logger.warning(f"⚠️ re-persist upscaled video failed: {e}")

        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

        # Prefer the local serve URL when a local file exists (now HD); else blob.
        if _resolve_media_file(safe_name, "video") is not None:
            url = f"/broll-videos/{safe_name}"
        elif _artifacts_enabled() and derived_blob:
            try:
                url = _artifacts_sas_url(derived_blob)
            except Exception:
                url = ""
        else:
            url = ""
        return jsonify({
            "success": True, "filename": safe_name,
            "resolution": f"{cur_h}p" if already else "1080p",
            "already": already, "url": url,
        })
    except Exception as e:  # noqa: BLE001
        logger.error(f"❌ /api/grok/upscale failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/finished-videos/upload", methods=["POST"])
def api_finished_videos_upload():
    """Start a background transcode + upload to the gallery.

    multipart/form-data fields:
      - file:   the video file (any common video container)
      - folder: optional gallery card name (defaults to file stem)

    Returns immediately with {success, job_id}. Poll GET
    /api/finished-videos/upload/status/<job_id> for progress + final result.
    """
    import subprocess
    import tempfile
    import shutil
    import uuid
    import re as _re
    import threading
    import time
    import json as _json
    from werkzeug.utils import secure_filename
    from azure.storage.blob import ContentSettings

    if not FINISHED_VIDEOS_BLOB_CONTAINER:
        return jsonify({
            "success": False,
            "error": "Uploads disabled: FINISHED_VIDEOS_BLOB_CONTAINER not set",
        }), 400

    if shutil.which("ffmpeg") is None:
        return jsonify({"success": False, "error": "ffmpeg not found on PATH"}), 500

    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"success": False, "error": "No file uploaded"}), 400

    safe_name = secure_filename(f.filename) or f"upload-{uuid.uuid4().hex}.mp4"
    stem = Path(safe_name).stem or f"upload-{uuid.uuid4().hex}"

    folder_raw = (request.form.get("folder") or "").strip()
    if folder_raw:
        folder = _re.sub(r"[^A-Za-z0-9 ._-]+", "_",
                         folder_raw).strip("/. ") or stem
    else:
        folder = stem
    blob_name = f"{folder}/{stem}.mp4"

    # Persist the upload to a temp dir BEFORE returning (FileStorage dies with the request).
    tmpdir = Path(tempfile.mkdtemp(prefix="scriptcraft-upload-"))
    src_path = tmpdir / safe_name
    f.save(str(src_path))

    job_id = uuid.uuid4().hex
    with video_upload_jobs_lock:
        video_upload_jobs[job_id] = {
            "state": "queued",
            "percent": 0,
            "duration": None,
            "out_time": 0.0,
            "error": None,
            "video": None,
            "filename": safe_name,
            "blob_name": blob_name,
            "started": time.time(),
            "finished": None,
        }

    def _set(**kw):
        with video_upload_jobs_lock:
            video_upload_jobs[job_id].update(kw)

    def _worker():
        out_path = tmpdir / f"{stem}.mp4"
        ffmpeg_log = tmpdir / "ffmpeg.log"
        try:
            # 1) Probe duration so we can compute %.
            duration = None
            try:
                pr = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(src_path)],
                    capture_output=True, text=True, timeout=60,
                )
                if pr.returncode == 0 and pr.stdout.strip():
                    duration = float(pr.stdout.strip())
                    _set(duration=duration)
            except Exception as pe:
                logger.warning(f"ffprobe failed (continuing without %): {pe}")

            # 2) Transcode. Progress key=value lines on stdout, errors to file.
            ffmpeg_cmd = [
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-i", str(src_path),
                "-vf", "scale='min(1920,iw)':'-2'",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                "-progress", "pipe:1", "-nostats",
                str(out_path),
            ]
            logger.info(
                f"📼 [{job_id[:8]}] transcoding {src_path.name} -> {blob_name} (dur={duration})")
            _set(state="transcoding")
            with ffmpeg_log.open("wb") as logf:
                proc = subprocess.Popen(
                    ffmpeg_cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=logf,
                    bufsize=1, text=True,
                )
                try:
                    assert proc.stdout is not None
                    for line in proc.stdout:
                        line = line.strip()
                        if not line or "=" not in line:
                            continue
                        k, _, v = line.partition("=")
                        if k == "out_time_ms":
                            try:
                                secs = int(v) / 1_000_000.0
                                pct = int((secs / duration) *
                                          100) if duration else 0
                                pct = max(0, min(99, pct))
                                _set(out_time=secs, percent=pct)
                            except Exception:
                                pass
                        elif k == "out_time_us":
                            try:
                                secs = int(v) / 1_000_000.0
                                pct = int((secs / duration) *
                                          100) if duration else 0
                                pct = max(0, min(99, pct))
                                _set(out_time=secs, percent=pct)
                            except Exception:
                                pass
                        elif k == "progress" and v == "end":
                            break
                finally:
                    rc = proc.wait()

            if rc != 0 or not out_path.exists() or out_path.stat().st_size == 0:
                try:
                    tail = ffmpeg_log.read_bytes(
                    )[-2000:].decode("utf-8", errors="replace").strip()
                except Exception:
                    tail = ""
                err = tail or f"ffmpeg exited {rc}"
                logger.error(f"❌ [{job_id[:8]}] transcode failed: {err}")
                _set(state="error", error=f"Transcode failed: {err[:500]}",
                     finished=time.time())
                return

            # 3) Generate poster (thumbnail) — single frame at ~3s (or 10% in for short clips).
            poster_path = tmpdir / f"{stem}.jpg"
            poster_blob = f"{folder}/{stem}.jpg"
            try:
                seek = 3.0
                if duration and duration > 0:
                    seek = min(3.0, max(0.5, duration * 0.1))
                pcmd = [
                    "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                    "-ss", f"{seek:.2f}", "-i", str(out_path),
                    "-vframes", "1",
                    "-vf", "scale='min(1280,iw)':'-2'",
                    "-q:v", "3",
                    str(poster_path),
                ]
                pres = subprocess.run(pcmd, stdin=subprocess.DEVNULL,
                                      capture_output=True, timeout=120)
                if pres.returncode != 0 or not poster_path.exists() or poster_path.stat().st_size == 0:
                    logger.warning(
                        f"⚠️ [{job_id[:8]}] poster generation failed (rc={pres.returncode}); continuing without thumbnail")
                    poster_path = None
            except Exception as pe:
                logger.warning(
                    f"⚠️ [{job_id[:8]}] poster generation error: {pe}")
                poster_path = None

            # 4) Upload to blob.
            _set(state="uploading", percent=99)
            svc = _finished_videos_blob_service()
            container = svc.get_container_client(
                FINISHED_VIDEOS_BLOB_CONTAINER)
            with out_path.open("rb") as fh:
                container.upload_blob(
                    name=blob_name,
                    data=fh,
                    overwrite=True,
                    content_settings=ContentSettings(content_type="video/mp4"),
                )
            if poster_path is not None:
                try:
                    with poster_path.open("rb") as ph:
                        container.upload_blob(
                            name=poster_blob,
                            data=ph,
                            overwrite=True,
                            content_settings=ContentSettings(
                                content_type="image/jpeg"),
                        )
                    logger.info(
                        f"🖼️ [{job_id[:8]}] uploaded poster {poster_blob}")
                except Exception as ue:
                    logger.warning(
                        f"⚠️ [{job_id[:8]}] poster upload failed: {ue}")
            size = out_path.stat().st_size
            logger.info(
                f"✅ [{job_id[:8]}] uploaded {blob_name} ({size} bytes)")
            _set(
                state="done",
                percent=100,
                finished=time.time(),
                video={
                    "title": folder,
                    "filename": f"{stem}.mp4",
                    "rel_path": blob_name,
                    "ext": "mp4",
                    "size": size,
                    "stream_url": _blob_sas_url(blob_name),
                    "poster_url": _blob_sas_url(poster_blob) if poster_path is not None else None,
                },
            )
        except Exception as e:
            logger.error(
                f"❌ [{job_id[:8]}] upload worker failed: {e}", exc_info=True)
            _set(state="error", error=str(e), finished=time.time())
        finally:
            try:
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass

    threading.Thread(
        target=_worker, name=f"video-upload-{job_id[:8]}", daemon=True).start()
    return jsonify({"success": True, "job_id": job_id, "filename": safe_name})


@app.route("/api/finished-videos/upload/status/<job_id>", methods=["GET"])
def api_finished_videos_upload_status(job_id: str):
    with video_upload_jobs_lock:
        job = video_upload_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "error": "Unknown job_id"}), 404
        # Return a shallow copy so the caller doesn't see live mutations.
        snap = dict(job)
    return jsonify({"success": True, "job": snap})


@app.route("/api/finished-videos/regenerate-posters", methods=["POST"])
def api_finished_videos_regenerate_posters():
    """Backfill poster JPGs for any video blobs that don't already have one.

    Streams the source video into ffmpeg via a temp file, extracts a single
    frame at ~3s, and uploads as `<stem>.jpg`. Skips blobs whose poster
    already exists. Returns a summary list.
    """
    import subprocess
    import tempfile
    import shutil as _shutil
    from azure.storage.blob import ContentSettings

    if not FINISHED_VIDEOS_BLOB_CONTAINER:
        return jsonify({"success": False, "error": "Blob container not configured"}), 400
    if _shutil.which("ffmpeg") is None:
        return jsonify({"success": False, "error": "ffmpeg not found on PATH"}), 500

    svc = _finished_videos_blob_service()
    container = svc.get_container_client(FINISHED_VIDEOS_BLOB_CONTAINER)
    existing_posters: set = set()
    videos: list = []
    for b in container.list_blobs():
        n = b.name or ""
        if n.endswith(".jpg"):
            existing_posters.add(n[:-4])
        else:
            ext = n.rsplit(".", 1)[-1].lower() if "." in n else ""
            if ("." + ext) in _VIDEO_EXTS:
                videos.append(n)

    created, skipped, failed = [], [], []
    tmp_root = Path(tempfile.mkdtemp(prefix="poster-backfill-"))
    try:
        for vname in videos:
            stem = vname.rsplit(".", 1)[0]
            if stem in existing_posters:
                skipped.append(vname)
                continue
            local_vid = tmp_root / Path(vname).name
            try:
                with local_vid.open("wb") as fh:
                    container.download_blob(vname).readinto(fh)
                poster_local = tmp_root / (Path(vname).stem + ".jpg")
                pcmd = [
                    "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                    "-ss", "3", "-i", str(local_vid),
                    "-vframes", "1",
                    "-vf", "scale='min(1280,iw)':'-2'",
                    "-q:v", "3",
                    str(poster_local),
                ]
                pres = subprocess.run(pcmd, stdin=subprocess.DEVNULL,
                                      capture_output=True, timeout=180)
                if pres.returncode != 0 or not poster_local.exists() or poster_local.stat().st_size == 0:
                    failed.append({"blob": vname, "error": "ffmpeg failed"})
                    continue
                with poster_local.open("rb") as ph:
                    container.upload_blob(
                        name=stem + ".jpg", data=ph, overwrite=True,
                        content_settings=ContentSettings(
                            content_type="image/jpeg"),
                    )
                created.append(stem + ".jpg")
                logger.info(f"🖼️ backfilled poster for {vname}")
            except Exception as e:
                logger.error(
                    f"❌ poster backfill failed for {vname}: {e}", exc_info=True)
                failed.append({"blob": vname, "error": str(e)})
            finally:
                try:
                    if local_vid.exists():
                        local_vid.unlink()
                except Exception:
                    pass
    finally:
        _shutil.rmtree(tmp_root, ignore_errors=True)

    return jsonify({
        "success": True,
        "created": created,
        "skipped": len(skipped),
        "failed": failed,
        "total_videos": len(videos),
    })


@app.route("/api/transcribe-audio", methods=["POST"])
def api_transcribe_audio():
    """Start a local-whisper transcription in the background.

    Body JSON:
        { "file_path": "/abs/path/to/audio.wav",
          "model":     "medium" (optional),
          "language":  "en"     (optional) }

    Returns: { success, session_id, stream_url }
    Stream events on /api/transcribe-audio/progress/<session_id>:
      {type:"progress", message:"...", line:"..."}
      {type:"segment",  start:"00:00.000", end:"00:05.000", text:"..."}
      {type:"done",     text:"<full transcript>", model:"medium"}
      {type:"error",    error:"..."}
    """
    try:
        data = request.get_json(silent=True) or {}
        file_path = (data.get("file_path") or "").strip()
        model = (data.get("model") or "medium").strip() or "medium"
        language = (data.get("language") or "").strip()
        output_dir_override = (data.get("output_dir") or "").strip() or None
        project_name_override = (data.get("project_name") or "").strip() or None

        if not file_path:
            return jsonify({"success": False, "error": "file_path is required"}), 400

        src = Path(file_path).expanduser()
        if not src.exists() or not src.is_file():
            return jsonify({"success": False, "error": f"File not found: {src}"}), 404

        whisper_bin = _find_whisper_cli()
        if not whisper_bin:
            return jsonify({
                "success": False,
                "error": "whisper CLI not found. Install with: pip install openai-whisper",
            }), 500

        session_id = str(uuid.uuid4())
        transcribe_streams[session_id] = _queue.Queue()
        transcribe_results.pop(session_id, None)

        thread = _threading.Thread(
            target=_transcribe_worker,
            args=(session_id, whisper_bin, str(src), model, language),
            kwargs={
                "output_dir_override": output_dir_override,
                "project_name_override": project_name_override,
            },
            daemon=True,
        )
        thread.start()

        logger.info(
            f"🎙️ Transcribe started: session={session_id} file='{src.name}' model={model}")
        return jsonify({
            "success": True,
            "session_id": session_id,
            "stream_url": f"/api/transcribe-audio/progress/{session_id}",
        })
    except Exception as e:
        logger.error(
            f"❌ /api/transcribe-audio failed to start: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


def _transcribe_worker(session_id: str, whisper_bin: str, file_path: str,
                       model: str, language: str,
                       output_dir_override: Optional[str] = None,
                       project_name_override: Optional[str] = None):
    """Run whisper CLI as a subprocess and stream stdout lines as SSE events.

    Optional overrides (used by the YouTube pipeline modal):
      output_dir_override   — write transcript to this dir (not <output_parent>/transcript)
      project_name_override — base filename (sanitized) for the saved .md/.docx
    """
    import subprocess
    import tempfile
    import shutil as _shutil
    import re as _re
    import time as _time

    q = transcribe_streams.get(session_id)

    def push(payload):
        if q is not None:
            try:
                q.put(payload)
            except Exception:
                pass

    out_dir = Path(tempfile.mkdtemp(prefix="whisper_out_"))
    cmd = [
        whisper_bin,
        file_path,
        "--model", model,
        "--output_format", "txt",
        "--output_dir", str(out_dir),
        # --verbose True (default) prints "[mm:ss.xxx --> mm:ss.xxx]  text" per segment
        "--verbose", "True",
    ]
    if language:
        cmd += ["--language", language]

    push({"type": "progress",
         "message": f"🎙️ Loading whisper model '{model}' (first run downloads weights)…"})
    logger.info(f"🎙️ whisper cmd: {' '.join(cmd)}")

    seg_re = _re.compile(r"^\[(\d+:\d+\.\d+)\s*-->\s*(\d+:\d+\.\d+)\]\s*(.*)$")

    def _to_hhmmss(ts: str) -> str:
        # ts is "MM:SS.mmm" or "HH:MM:SS.mmm" (whisper uses minutes:seconds when <1h)
        try:
            base = ts.split(".")[0]
            parts = base.split(":")
            if len(parts) == 2:
                h, m, s = 0, int(parts[0]), int(parts[1])
            elif len(parts) == 3:
                h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
            else:
                return ts
            # normalize overflow
            m += s // 60
            s = s % 60
            h += m // 60
            m = m % 60
            return f"{h:02d}:{m:02d}:{s:02d}"
        except Exception:
            return ts

    collected_segments: list = []  # list of (start_hhmmss, text)

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # Force UTF-8 locale so the child's stdio encoding (and our pipe decode)
    # don't fall back to ASCII and crash on tqdm's non-ASCII progress chars.
    env.setdefault("LC_ALL", "en_US.UTF-8")
    env.setdefault("LANG", "en_US.UTF-8")

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,  # whisper's Python child fails with
                                       # "init_sys_streams: can't initialize sys
                                       # standard streams / [Errno 9] Bad file
                                       # descriptor" if it inherits a closed
                                       # stdin (web_gui is often detached from
                                       # a controlling terminal). DEVNULL gives
                                       # it a valid fd 0.
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=0,  # unbuffered — we'll segment manually on \n and \r
            env=env,
        )
    except Exception as e:
        push({"type": "error", "error": f"failed to launch whisper: {e}"})
        _shutil.rmtree(out_dir, ignore_errors=True)
        return

    # Heartbeat thread — keeps the UI alive while whisper loads the model silently
    stop_heartbeat = _threading.Event()

    def _heartbeat():
        secs = 0
        while not stop_heartbeat.wait(5):
            secs += 5
            push({"type": "progress", "message": f"…still working ({secs}s elapsed)"})

    hb_thread = _threading.Thread(target=_heartbeat, daemon=True)
    hb_thread.start()

    try:
        assert proc.stdout is not None
        # Read char-by-char so we capture both \n (segment lines) and \r (tqdm updates)
        buf = []
        first_output_seen = False
        while True:
            ch = proc.stdout.read(1)
            if ch == "" and proc.poll() is not None:
                break
            if ch in ("\n", "\r"):
                line = "".join(buf).strip()
                buf = []
                if not line:
                    continue
                if not first_output_seen:
                    first_output_seen = True
                    # First real output — model is loaded
                    stop_heartbeat.set()
                m = seg_re.match(line)
                if m:
                    start_hms = _to_hhmmss(m.group(1))
                    end_hms = _to_hhmmss(m.group(2))
                    seg_text = m.group(3).strip()
                    collected_segments.append((start_hms, seg_text))
                    push({
                        "type": "segment",
                        "start": start_hms,
                        "end": end_hms,
                        "text": seg_text,
                        "line": line,
                    })
                else:
                    push({"type": "progress", "message": line, "line": line})
            else:
                buf.append(ch)

        # Drain any trailing buffered text
        if buf:
            tail = "".join(buf).strip()
            if tail:
                push({"type": "progress", "message": tail, "line": tail})

        stop_heartbeat.set()
        rc = proc.wait()
        if rc != 0:
            push({"type": "error", "error": f"whisper exited with code {rc}"})
            _shutil.rmtree(out_dir, ignore_errors=True)
            return

        txt_files = sorted(out_dir.glob("*.txt"))
        if not txt_files:
            push({"type": "error", "error": "whisper produced no .txt output"})
            _shutil.rmtree(out_dir, ignore_errors=True)
            return

        plain_text = txt_files[0].read_text(
            encoding="utf-8", errors="replace").strip()
        # Build a timestamped transcript in the format the YouTube agent expects:
        #   [HH:MM:SS] spoken text
        if collected_segments:
            text = "\n".join(f"[{ts}] {seg}" for ts,
                             seg in collected_segments if seg).strip()
        else:
            text = plain_text

        # Auto-save the transcript to <chosen_dir>/<project>_transcript.{md,docx}
        # Chosen dir = pipeline override if provided, else the current default output dir.
        # We deliberately do NOT create a "transcript/" subdirectory anymore — the
        # YouTube Publish pipeline's Output Directory is the single source of truth.
        saved_md_path: Optional[str] = None
        saved_docx_path: Optional[str] = None
        save_error: Optional[str] = None
        try:
            if output_dir_override:
                transcript_dir = Path(output_dir_override).expanduser().resolve()
            else:
                transcript_dir = _get_output_parent_dir()
            transcript_dir.mkdir(parents=True, exist_ok=True)

            if project_name_override:
                project_name = _safe_title_for_paths(project_name_override) or "transcript"
            else:
                project_name = _safe_title_for_paths(transcript_dir.name) or "transcript"
            src_path = Path(file_path)
            generated_at = _time.strftime("%Y-%m-%d %H:%M:%S")
            md_body = (
                f"# Transcript: {project_name}\n\n"
                f"- **Source:** `{src_path}`\n"
                f"- **Model:** {model}\n"
                f"- **Language:** {language or 'auto'}\n"
                f"- **Generated:** {generated_at}\n"
                f"- **Segments:** {len(collected_segments)}\n\n"
                f"---\n\n"
                f"{text}\n"
            )
            md_path = transcript_dir / f"{project_name}_transcript.md"
            md_path.write_text(md_body, encoding="utf-8")
            saved_md_path = str(md_path)
            logger.info(f"📝 Transcript .md saved: {md_path}")

            docx_path = transcript_dir / f"{project_name}_transcript.docx"
            try:
                from docx import Document  # python-docx
                doc = Document()
                doc.add_heading(f"Transcript: {project_name}", level=1)
                meta = doc.add_paragraph()
                meta.add_run(f"Source: {src_path}\n").italic = True
                meta.add_run(f"Model: {model}    ").italic = True
                meta.add_run(f"Language: {language or 'auto'}\n").italic = True
                meta.add_run(f"Generated: {generated_at}    ").italic = True
                meta.add_run(
                    f"Segments: {len(collected_segments)}").italic = True
                doc.add_paragraph("")
                for line in text.splitlines():
                    doc.add_paragraph(line)
                doc.save(str(docx_path))
                saved_docx_path = str(docx_path)
                logger.info(f"📝 Transcript .docx saved: {docx_path}")
            except Exception as docx_exc:
                logger.warning(
                    f"⚠️ Could not save transcript .docx (md saved ok): {docx_exc}")

            saved_msg = f"📝 Transcript saved to {md_path}"
            if saved_docx_path:
                saved_msg += f" (+ .docx)"
            push({"type": "progress", "message": saved_msg})
        except Exception as save_exc:
            save_error = str(save_exc)
            logger.error(
                f"⚠️ Failed to save transcript: {save_exc}", exc_info=True)
            push({"type": "progress",
                  "message": f"⚠️ Failed to save transcript: {save_exc}"})

        transcribe_results[session_id] = {
            "success": True, "text": text, "model": model,
            "saved_md_path": saved_md_path,
            "saved_docx_path": saved_docx_path,
            "save_error": save_error}
        push({"type": "done", "text": text, "model": model,
             "segments": len(collected_segments),
             "saved_md_path": saved_md_path,
             "saved_docx_path": saved_docx_path,
             "save_error": save_error})
    except Exception as e:
        logger.error(f"❌ transcribe worker crash: {e}", exc_info=True)
        push({"type": "error", "error": str(e)})
    finally:
        stop_heartbeat.set()
        _shutil.rmtree(out_dir, ignore_errors=True)


@app.route("/api/transcribe-audio/progress/<session_id>")
def api_transcribe_audio_progress(session_id):
    """SSE stream of transcription events."""
    q = transcribe_streams.get(session_id)
    if q is None:
        return "Session not found", 404

    def generate():
        try:
            while True:
                try:
                    payload = q.get(timeout=60)
                except _queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(payload)}\n\n"
                if payload.get("type") in ("done", "error"):
                    break
        finally:
            transcribe_streams.pop(session_id, None)

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


if __name__ == "__main__":
    # Use environment variable for port, default to 8080 for local, 5007 for container
    port = int(os.environ.get("PORT", "8080"))

    logger.info("🎬 Starting ScriptCraft Web GUI (Universal Version)...")
    logger.info("📦 Version: %s", VERSION)
    logger.info("🚀 Server starting on http://0.0.0.0:%d", port)

    # Save the golden reference script to the cloud (marked reference), once.
    try:
        _seed_golden_reference_to_cloud()
    except Exception as _e:
        logger.warning("golden reference cloud seed skipped: %s", _e)

    if port == 5007:
        logger.info("🐳 Running in Azure Container mode")
    else:
        logger.info("💻 Running in Local mode")

    # threaded=True is REQUIRED: the app uses long-lived SSE progress streams
    # (/progress/<id>). Werkzeug's dev server is single-threaded by default, so an
    # open SSE connection occupies the ONLY worker thread and blocks every other
    # request (e.g. /api/script/polish) until it closes — the browser just spins
    # forever. Threading lets concurrent requests (SSE + polish + polling) be
    # served at once, matching the gunicorn thread pool used in the container.
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
