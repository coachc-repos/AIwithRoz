"""
YouTube Publisher
=================
Automates publishing finished videos to the "AI for Roz" YouTube channel
(account: christian.thilmany@gmail.com) using the YouTube Data API v3.

It parses the YouTube Upload Details markdown produced by the
YouTubeUploadDetailsAgentClient, extracts the best-practice fields
(title, description, tags, category, made-for-kids), and uploads the
selected local video file via a resumable upload.

OAuth setup (one-time):
    1. In Google Cloud Console, create an OAuth 2.0 Client ID of type
       "Desktop app" for a project that has YouTube Data API v3 enabled.
    2. Download the client secret JSON and save it to:
           ~/.scriptcraft/youtube_client_secret.json
    3. The first publish will open a browser window to authorize the
       channel owned by christian.thilmany@gmail.com. The resulting
       refresh token is cached at:
           ~/.scriptcraft/youtube_token.json
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

SCRIPTCRAFT_DIR = Path.home() / ".scriptcraft"
CLIENT_SECRET_PATH = SCRIPTCRAFT_DIR / "youtube_client_secret.json"
TOKEN_PATH = SCRIPTCRAFT_DIR / "youtube_token.json"

# Full upload scope is required to publish videos. The plain ``youtube``
# scope is required to read and modify playlists (add the new video to one
# or more of the channel's playlists).
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube",
          "https://www.googleapis.com/auth/youtube.force-ssl"]

# YouTube category ID lookup (US defaults). We default to Science & Tech (28)
# for the AI for Roz channel if the agent's recommendation is missing.
CATEGORY_NAME_TO_ID = {
    "film & animation": "1",
    "autos & vehicles": "2",
    "music": "10",
    "pets & animals": "15",
    "sports": "17",
    "travel & events": "19",
    "gaming": "20",
    "people & blogs": "22",
    "comedy": "23",
    "entertainment": "24",
    "news & politics": "25",
    "howto & style": "26",
    "education": "27",
    "science & technology": "28",
    "nonprofits & activism": "29",
}
DEFAULT_CATEGORY_ID = "28"  # Science & Technology

VALID_PRIVACY = {"private", "public", "unlisted"}

# YouTube hard limits
MAX_TITLE_LEN = 100
MAX_DESCRIPTION_LEN = 5000
MAX_TAG_LEN = 500       # individual tag
MAX_TAGS_TOTAL = 500    # combined chars across all tags


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

@dataclass
class YouTubeMetadata:
    title: str
    description: str
    tags: List[str] = field(default_factory=list)
    category_id: str = DEFAULT_CATEGORY_ID
    made_for_kids: bool = False
    privacy_status: str = "private"
    hashtags: List[str] = field(default_factory=list)
    # Newer YouTube API fields
    contains_synthetic_media: bool = False  # "Altered content" disclosure
    default_language: str = "en-US"          # snippet metadata language
    default_audio_language: str = "en-US"    # spoken-audio language
    recording_date: Optional[str] = None     # ISO-8601 e.g. 2026-05-14T00:00:00Z
    embeddable: bool = True
    public_stats_viewable: bool = True

    def composed_description(self) -> str:
        """Return the description with hashtags appended on a final line
        (YouTube renders the first 3 hashtags above the title)."""
        desc = (self.description or "").rstrip()
        if not self.hashtags:
            return desc[:MAX_DESCRIPTION_LEN]
        tag_line = " ".join(
            ("#" + h.lstrip("#").strip().replace(" ", ""))
            for h in self.hashtags if h and h.strip()
        )
        if not tag_line:
            return desc[:MAX_DESCRIPTION_LEN]
        if desc:
            combined = f"{desc}\n\n{tag_line}"
        else:
            combined = tag_line
        return combined[:MAX_DESCRIPTION_LEN]

    def to_request_body(self) -> Dict[str, Any]:
        snippet: Dict[str, Any] = {
            "title": self.title[:MAX_TITLE_LEN],
            "description": self.composed_description(),
            "tags": self.tags,
            "categoryId": self.category_id,
        }
        if self.default_language:
            snippet["defaultLanguage"] = self.default_language
        if self.default_audio_language:
            snippet["defaultAudioLanguage"] = self.default_audio_language

        status: Dict[str, Any] = {
            "privacyStatus": self.privacy_status,
            "selfDeclaredMadeForKids": self.made_for_kids,
            "embeddable": bool(self.embeddable),
            "publicStatsViewable": bool(self.public_stats_viewable),
            "license": "youtube",
            # New YouTube field for AI/altered content disclosure.
            "containsSyntheticMedia": bool(self.contains_synthetic_media),
        }

        body: Dict[str, Any] = {"snippet": snippet, "status": status}
        if self.recording_date:
            body["recordingDetails"] = {"recordingDate": self.recording_date}
        return body


_SECTION_RE = re.compile(r"^\s*##\s+", re.MULTILINE)


def _split_sections(md: str) -> Dict[str, str]:
    """Split the YouTube details markdown into a mapping of section
    heading text -> body content. Heading match is case-insensitive
    and emoji is stripped."""
    parts = _SECTION_RE.split(md or "")
    sections: Dict[str, str] = {}
    # The first chunk is anything before the first ## heading.
    for chunk in parts[1:]:
        lines = chunk.splitlines()
        if not lines:
            continue
        heading = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        # Normalize: strip leading emoji + whitespace, lowercase.
        norm = re.sub(r"^[^A-Za-z0-9]+", "", heading).strip().lower()
        sections[norm] = body
    return sections


def _strip_inline_markdown(text: str) -> str:
    text = text.strip()
    # Remove surrounding bold/italic
    text = re.sub(r"^\*+|\*+$", "", text).strip()
    # Drop simple inline code ticks
    text = text.replace("`", "")
    return text


def _extract_first_meaningful_line(body: str) -> str:
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Skip bullet markers and parenthetical "Examples:" lines.
        if line.lower().startswith(("example", "examples:", "- example")):
            continue
        if line.startswith(("- ", "* ", "+ ")):
            line = line[2:].strip()
        if line.startswith(":"):
            line = line.lstrip(":").strip()
        if not line:
            continue
        return _strip_inline_markdown(line)
    return ""


def _parse_tags(body: str) -> List[str]:
    # Take everything after the first colon if present, else the whole body.
    body = body.strip()
    # Some agents emit tags on multiple lines - flatten.
    flat = " ".join(line.strip() for line in body.splitlines() if line.strip()
                    and not line.strip().startswith(("-", "*", "+")) is False
                    or line.strip())
    flat = re.sub(r"\s+", " ", flat)
    # Drop any leading "Tags:" / colon.
    flat = re.sub(r"^[^:]*:\s*", "", flat) if ":" in flat[:40] else flat
    raw_tags = [t.strip().strip("#").strip("`") for t in flat.split(",")]
    tags: List[str] = []
    total = 0
    for t in raw_tags:
        # Sanitize: drop characters YouTube rejects in tags (<, >, quotes,
        # backslashes, control chars). Keep letters, digits, spaces, and
        # a small set of safe punctuation, then collapse internal whitespace
        # into single hyphens ("AI generated video" -> "AI-generated-video").
        t = re.sub(r"[<>\"\\\u0000-\u001f]", "", t)
        # Strip surrounding bold/italic markdown leftovers.
        t = re.sub(r"^[*_`]+|[*_`]+$", "", t).strip()
        # Drop wrapping straight or smart quotes.
        t = t.strip("'\u2018\u2019\u201c\u201d").strip()
        if not t:
            continue
        # Hyphenate multi-word tags.
        t = re.sub(r"\s+", "-", t)
        # Collapse repeat hyphens and trim.
        t = re.sub(r"-{2,}", "-", t).strip("-")
        if not t:
            continue
        # Cap individual tag at YouTube's per-tag practical limit (30 chars).
        if len(t) > 30:
            t = t[:30].rstrip("-")
        if len(t) > MAX_TAG_LEN:
            continue
        # YouTube counts quoted multi-word tags with quotes; keep simple.
        if total + len(t) + 2 > MAX_TAGS_TOTAL:
            break
        tags.append(t)
        total += len(t) + 2
    # De-duplicate (case-insensitive) while preserving order.
    seen: set = set()
    deduped: List[str] = []
    for t in tags:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(t)
    return deduped


_HASHTAG_TOKEN_RE = re.compile(r"#([A-Za-z0-9_]+)")


def _parse_hashtags(sections: Dict[str, str]) -> List[str]:
    """Collect hashtags from a dedicated ``## Hashtags`` section if present,
    otherwise harvest any ``#word`` tokens that appear inside the description
    body. Returns a de-duplicated list (case-insensitive) without the leading
    ``#`` so :meth:`YouTubeMetadata.composed_description` can format them."""
    candidates: List[str] = []
    for key in ("hashtags", "hash tags"):
        block = (sections.get(key) or "").strip()
        if block:
            candidates.extend(_HASHTAG_TOKEN_RE.findall(block))
            # Also accept bare comma/space separated words in the section.
            for tok in re.split(r"[,\s]+", block):
                tok = tok.strip().lstrip("#")
                if tok and re.fullmatch(r"[A-Za-z0-9_]+", tok):
                    candidates.append(tok)
    desc_body = (sections.get("description") or "")
    candidates.extend(_HASHTAG_TOKEN_RE.findall(desc_body))
    out: List[str] = []
    seen: set = set()
    for h in candidates:
        k = h.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(h)
    return out


def _parse_category(body: str) -> str:
    line = _extract_first_meaningful_line(body)
    # Split on common separators to get just the category name.
    head = re.split(r"[—\-:|(]", line, maxsplit=1)[0].strip().lower()
    return CATEGORY_NAME_TO_ID.get(head, DEFAULT_CATEGORY_ID)


def _parse_made_for_kids(studio_body: str) -> bool:
    # Look for "Made for Kids: Yes" or similar.
    m = re.search(r"made for kids[^\n]*?:\s*(yes|no)", studio_body, re.I)
    if not m:
        return False
    return m.group(1).lower() == "yes"


def _build_description(sections: Dict[str, str]) -> str:
    """Compose the YouTube description body from the agent's
    'description' section. We deliberately only use the description
    section (which already contains hook, overview, timestamps, tools,
    hashtags, CTA). Everything else in the markdown is internal
    production guidance and should not be uploaded."""
    body = sections.get("description", "").strip()
    if not body:
        return ""
    # Section labels we want spaced apart in the final description.
    spaced_labels = (
        "overview", "timestamps", "tools & resources", "tools and resources",
        "call to action", "cta", "hashtags",
        "resources", "links",
    )
    # Labels whose entire body should be dropped from the description.
    # All social-link / follow-me style sections are dropped here and a
    # single canonical X/Twitter line is appended below the description
    # body so we never accidentally publish placeholder handles or stale
    # links to platforms the channel no longer uses.
    dropped_labels = (
        "connect with us", "connect",
        "connect with me", "connect with roz",
        "social links", "social media", "social",
        "follow", "follow me", "follow us",
        "find me", "find us",
        "links", "my links",
    )
    # Match any of these label shapes (the raw label text is captured):
    #   **OVERVIEW:**       **OVERVIEW**:        **OVERVIEW**
    #   ## OVERVIEW         ### OVERVIEW:        OVERVIEW:
    #   __OVERVIEW:__       *OVERVIEW:*
    label_patterns = [
        re.compile(r"^\s*#{1,6}\s+(.+?)\s*:?\s*$"),
        re.compile(r"^\s*\*\*\s*([^*\n]+?)\s*\*\*\s*:?\s*$"),
        re.compile(r"^\s*__\s*([^_\n]+?)\s*__\s*:?\s*$"),
        re.compile(r"^\s*\*\s*([^*\n]+?)\s*\*\s*:?\s*$"),
        re.compile(r"^\s*([A-Z][A-Z0-9 &/\-]{2,40})\s*:\s*$"),
    ]

    def _match_label(line: str) -> Optional[str]:
        for pat in label_patterns:
            m = pat.match(line)
            if m:
                return m.group(1).strip()
        return None

    cleaned_lines: List[str] = []
    skipping = False
    for raw in body.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        label_text = _match_label(stripped)
        if label_text is not None:
            label_norm = re.sub(r"\s*\([^)]*\)\s*", "",
                                label_text).strip().lower().rstrip(":")
            # "Connect with Us" (and similar) is dropped entirely — skip
            # the label and all of its body lines until the next label.
            if any(label_norm.startswith(d) for d in dropped_labels):
                skipping = True
                continue
            # The HOOK label is removed entirely (just the prose stays).
            if label_norm.startswith("hook"):
                skipping = False
                if cleaned_lines and cleaned_lines[-1].strip():
                    cleaned_lines.append("")
                continue
            # For the other major sections, surround the heading with blank
            # lines so they read as distinct paragraphs in YouTube.
            if label_norm in spaced_labels:
                skipping = False
                if cleaned_lines and cleaned_lines[-1].strip():
                    cleaned_lines.append("")
                cleaned_lines.append(label_norm.upper().rstrip(":"))
                cleaned_lines.append("")
                continue
            # Unknown label: keep the text without the bold markers.
            skipping = False
            cleaned_lines.append(label_text.rstrip(":"))
            continue
        if skipping:
            continue
        # Strip inline bold markers but keep the text.
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        # Strip a leading inline "Hook:" / "HOOK -" prefix if the agent
        # emitted the hook label on the same line as the sentence.
        line = re.sub(r"^\s*hook\s*[:\-\u2014]\s*", "", line, flags=re.I)
        # Drop internal production-guidance lines the agent sometimes
        # emits at the end of its description section. These are useful
        # for our own QA but should never be uploaded to YouTube.
        stripped_for_check = line.strip().strip("`").strip()
        if re.match(r"^timestamp\s*source\b", stripped_for_check, re.I):
            continue
        if re.match(r"^(estimated\s+)?video\s+(duration|length)\s*[:=]",
                    stripped_for_check, re.I):
            continue
        # Also drop the bare formula line "~1,790 words ÷ 150 = ~11:56"
        # whether or not it has a leading label.
        if re.search(r"\bwords\s*[÷/]\s*150\b", stripped_for_check, re.I):
            continue
        cleaned_lines.append(line)
    description = "\n".join(cleaned_lines).strip()
    # Collapse 3+ blank lines but keep single blank-line spacing.
    description = re.sub(r"\n{3,}", "\n\n", description)

    # Guarantee exactly one canonical social-link line. Any social-link
    # sections the agent emitted were already dropped above; append the
    # X/Twitter handle here so the description always carries it (and
    # only it) regardless of what the agent produced.
    canonical_social = "- X / Twitter: @AIwithRoz"
    if canonical_social not in description:
        description = (description.rstrip()
                       + "\n\nCONNECT\n\n"
                       + canonical_social).strip()
        description = re.sub(r"\n{3,}", "\n\n", description)

    # Append the "PROMPTS MENTIONED IN THIS EPISODE" section (if the
    # agent produced one) verbatim to the end of the description so
    # viewers can copy the exact prompts shown in the video.
    prompts_body = (sections.get("prompts mentioned in this episode", "")
                    or "").strip()
    if prompts_body:
        # Strip inline bold markers from the prompts block too.
        prompts_clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", prompts_body).strip()
        description = (description.rstrip()
                       + "\n\nPROMPTS MENTIONED IN THIS EPISODE\n\n"
                       + prompts_clean).strip()
        description = re.sub(r"\n{3,}", "\n\n", description)

    return description


def parse_youtube_details_markdown(md: str) -> YouTubeMetadata:
    """Parse the agent-generated YouTube details markdown into a
    :class:`YouTubeMetadata` object ready for upload."""
    sections = _split_sections(md)

    title = _extract_first_meaningful_line(sections.get("video title", "")) \
        or "Untitled Video"
    description = _build_description(sections) or title
    tags = _parse_tags(sections.get("tags", ""))
    hashtags = _parse_hashtags(sections)
    category_id = _parse_category(sections.get("category", ""))
    made_for_kids = _parse_made_for_kids(
        sections.get("studio details (copy-paste ready into youtube studio)",
                     sections.get("studio details", "")))

    return YouTubeMetadata(
        title=title,
        description=description,
        tags=tags,
        hashtags=hashtags,
        category_id=category_id,
        made_for_kids=made_for_kids,
    )


# ---------------------------------------------------------------------------
# OAuth + upload
# ---------------------------------------------------------------------------

def _import_google_libs():
    try:
        from google.oauth2.credentials import Credentials  # noqa: F401
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
        return {
            "Credentials": Credentials,
            "InstalledAppFlow": InstalledAppFlow,
            "Request": Request,
            "build": build,
            "HttpError": HttpError,
            "MediaFileUpload": MediaFileUpload,
        }
    except ImportError as e:  # pragma: no cover - surface friendly error
        raise RuntimeError(
            "Google API client libraries are not installed. Run:\n"
            "    pip install google-api-python-client google-auth-oauthlib "
            "google-auth-httplib2"
        ) from e


def is_authorized() -> bool:
    return TOKEN_PATH.exists()


def has_client_secret() -> bool:
    return CLIENT_SECRET_PATH.exists()


def _load_credentials():
    libs = _import_google_libs()
    Credentials = libs["Credentials"]
    Request = libs["Request"]

    creds = None
    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(
                str(TOKEN_PATH), SCOPES)
        except Exception as e:
            logger.warning(f"Could not load cached YouTube token: {e}")
            creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds)
            return creds
        except Exception as e:
            logger.warning(f"YouTube token refresh failed: {e}")

    if not CLIENT_SECRET_PATH.exists():
        raise FileNotFoundError(
            f"Missing OAuth client secret. Place your Google OAuth desktop "
            f"client JSON at: {CLIENT_SECRET_PATH}"
        )

    InstalledAppFlow = libs["InstalledAppFlow"]
    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH), SCOPES)
    # Opens the user's browser. Bind to an ephemeral port on localhost.
    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        authorization_prompt_message=(
            "Authorize the AI for Roz YouTube channel "
            "(christian.thilmany@gmail.com) in the browser window that opened."
        ),
        success_message=(
            "Authorization complete — you can close this tab and return to "
            "ScriptCraft."
        ),
    )
    _save_credentials(creds)
    return creds


def _save_credentials(creds) -> None:
    SCRIPTCRAFT_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass


def _build_service():
    libs = _import_google_libs()
    creds = _load_credentials()
    return libs["build"]("youtube", "v3", credentials=creds,
                         cache_discovery=False)


# ---------------------------------------------------------------------------
# Upload progress tracking (in-memory, keyed by upload_id)
# ---------------------------------------------------------------------------

_UPLOAD_STATE_LOCK = threading.Lock()
_UPLOAD_STATE: Dict[str, Dict[str, Any]] = {}


def _set_state(upload_id: str, **kwargs) -> None:
    with _UPLOAD_STATE_LOCK:
        state = _UPLOAD_STATE.setdefault(upload_id, {})
        state.update(kwargs)


def get_upload_status(upload_id: str) -> Optional[Dict[str, Any]]:
    with _UPLOAD_STATE_LOCK:
        state = _UPLOAD_STATE.get(upload_id)
        return dict(state) if state else None


_SRT_TAG_RE = re.compile(r"</?(?:b|i|u|font)(?:\s[^>]*)?>", re.IGNORECASE)


def _sanitize_srt_for_youtube(src: Path) -> Path:
    """DaVinci Resolve (and some other NLEs) export .srt files whose cue
    text is wrapped in HTML-style tags like ``<b>...</b>``, ``<i>...</i>``,
    or ``<font color="...">...</font>``. YouTube's captions.insert endpoint
    treats SRT as plain SubRip text and preserves those tags literally,
    so viewers see ``<b>`` characters around every caption line.

    Strip those styling tags into a sibling ``*.youtube.srt`` file and
    return the cleaned path. If no tags are present, return the original
    path unchanged."""
    try:
        raw = src.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return src
    if not _SRT_TAG_RE.search(raw):
        return src
    cleaned = _SRT_TAG_RE.sub("", raw)
    # Also collapse any trailing whitespace the tag removal left behind.
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    out = src.with_suffix(".youtube.srt")
    try:
        out.write_text(cleaned, encoding="utf-8")
        logger.info(
            f"🧹 Stripped HTML tags from SRT before upload: "
            f"{src.name} → {out.name}")
        return out
    except Exception as e:
        logger.warning(
            f"Could not write sanitized SRT ({e}); uploading original.")
        return src


def _upload_caption_track(
    service,
    video_id: str,
    srt_path: Path,
    language: str = "en",
    name: str = "English",
) -> Dict[str, Any]:
    """Upload an .srt caption track to ``video_id`` via captions.insert.
    Requires the youtube.force-ssl scope; the broader 'youtube' scope this
    module already requests is sufficient because Google grants captions
    write permission with it for the channel's own videos."""
    libs = _import_google_libs()
    MediaFileUpload = libs["MediaFileUpload"]
    # Strip <b>/<i>/<u>/<font> tags that DaVinci Resolve writes into its
    # SRT export; YouTube would otherwise show them literally.
    clean_srt = _sanitize_srt_for_youtube(srt_path)
    media = MediaFileUpload(str(clean_srt), mimetype="application/octet-stream",
                            resumable=False)
    body = {
        "snippet": {
            "videoId": video_id,
            "language": language,
            "name": name,
            "isDraft": False,
        }
    }
    return service.captions().insert(
        part="snippet", body=body, media_body=media,
    ).execute()


def upload_video(
    video_path: str,
    metadata: YouTubeMetadata,
    upload_id: str,
    notify_subscribers: bool = True,
    thumbnail_path: Optional[str] = None,
    playlist_ids: Optional[List[str]] = None,
    srt_path: Optional[str] = None,
    srt_language: str = "en",
    srt_track_name: str = "English",
) -> Dict[str, Any]:
    """Upload a local video file to YouTube. Updates progress under
    ``upload_id`` so the UI can poll ``get_upload_status``. If
    ``thumbnail_path`` is provided, a custom thumbnail is set after the
    video upload completes."""

    path = Path(video_path).expanduser()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Video file not found: {path}")

    thumb_path: Optional[Path] = None
    if thumbnail_path:
        thumb_path = Path(thumbnail_path).expanduser()
        if not thumb_path.exists() or not thumb_path.is_file():
            raise FileNotFoundError(
                f"Thumbnail file not found: {thumb_path}")
        if thumb_path.suffix.lower() not in THUMBNAIL_EXTS:
            raise ValueError(
                f"Unsupported thumbnail type: {thumb_path.suffix}. "
                f"Allowed: {sorted(THUMBNAIL_EXTS)}")

    srt_file: Optional[Path] = None
    if srt_path:
        srt_file = Path(srt_path).expanduser()
        if not srt_file.exists() or not srt_file.is_file():
            raise FileNotFoundError(f"SRT caption file not found: {srt_file}")
        if srt_file.suffix.lower() != ".srt":
            raise ValueError(
                f"Unsupported caption type: {srt_file.suffix} (only .srt)")

    libs = _import_google_libs()
    HttpError = libs["HttpError"]
    MediaFileUpload = libs["MediaFileUpload"]

    _set_state(upload_id, status="authorizing", progress=0,
               filename=path.name)
    service = _build_service()

    body = metadata.to_request_body()
    body["status"]["notifySubscribers"] = bool(notify_subscribers)

    media = MediaFileUpload(
        str(path), chunksize=8 * 1024 * 1024, resumable=True,
        mimetype="video/*",
    )

    request = service.videos().insert(
        part="snippet,status,recordingDetails",
        body=body,
        media_body=media,
    )

    _set_state(upload_id, status="uploading", progress=0,
               filesize=path.stat().st_size)

    response = None
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                _set_state(upload_id, status="uploading", progress=pct)
        except HttpError as e:
            _set_state(upload_id, status="error", error=str(e))
            raise

    video_id = response.get("id")
    video_url = f"https://youtu.be/{video_id}" if video_id else None

    thumbnail_set = False
    thumbnail_error: Optional[str] = None
    if video_id and thumb_path is not None:
        _set_state(upload_id, status="setting_thumbnail", progress=100)
        # YouTube rejects the wildcard 'image/*' mimetype. Map by extension.
        ext = thumb_path.suffix.lower()
        thumb_mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(ext, "image/jpeg")
        logger.info(
            f"🖼️  Setting thumbnail for video {video_id}: {thumb_path} "
            f"({thumb_path.stat().st_size} bytes, mime={thumb_mime})")
        try:
            thumb_media = MediaFileUpload(
                str(thumb_path), mimetype=thumb_mime, resumable=False)
            resp = service.thumbnails().set(
                videoId=video_id, media_body=thumb_media).execute()
            thumbnail_set = True
            logger.info(f"✅ Thumbnail set OK for {video_id}: {resp}")
        except HttpError as te:
            # The API error body usually contains a useful 'reason' (e.g.
            # 'youtubeSignupRequired' or 'mediaBodyRequired').
            try:
                err_text = te.content.decode("utf-8", errors="replace") \
                    if hasattr(te, "content") and te.content else str(te)
            except Exception:  # pragma: no cover
                err_text = str(te)
            thumbnail_error = err_text
            logger.error(
                f"❌ Thumbnail set FAILED for {video_id} "
                f"(file={thumb_path}): {err_text}")
        except Exception as te:  # network / generic
            thumbnail_error = str(te)
            logger.error(
                f"❌ Thumbnail set FAILED for {video_id} "
                f"(file={thumb_path}): {te}")
    elif video_id and thumb_path is None:
        logger.info(
            f"ℹ️  No thumbnail_path supplied for video {video_id}; "
            f"skipping thumbnail step.")

    playlists_added: List[str] = []
    playlist_errors: List[Dict[str, str]] = []
    if video_id and playlist_ids:
        _set_state(upload_id, status="adding_to_playlists", progress=100)
        for pid in playlist_ids:
            pid = (pid or "").strip()
            if not pid:
                continue
            try:
                service.playlistItems().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": pid,
                            "resourceId": {
                                "kind": "youtube#video",
                                "videoId": video_id,
                            },
                        }
                    },
                ).execute()
                playlists_added.append(pid)
            except Exception as pe:
                msg = str(pe)
                logger.warning(
                    f"Could not add video to playlist {pid}: {pe}")
                playlist_errors.append({"playlist_id": pid, "error": msg})

    caption_id: Optional[str] = None
    caption_error: Optional[str] = None
    if video_id and srt_file is not None:
        _set_state(upload_id, status="uploading_captions", progress=100)
        logger.info(
            f"📝 Uploading caption track for {video_id}: {srt_file} "
            f"({srt_file.stat().st_size} bytes, lang={srt_language})")
        try:
            resp = _upload_caption_track(
                service, video_id, srt_file,
                language=srt_language, name=srt_track_name,
            )
            caption_id = (resp or {}).get("id")
            logger.info(f"✅ Caption track uploaded for {video_id}: id={caption_id}")
        except HttpError as ce:
            try:
                caption_error = ce.content.decode("utf-8", errors="replace") \
                    if hasattr(ce, "content") and ce.content else str(ce)
            except Exception:  # pragma: no cover
                caption_error = str(ce)
            logger.error(
                f"❌ Caption upload FAILED for {video_id} "
                f"(file={srt_file}): {caption_error}")
        except Exception as ce:
            caption_error = str(ce)
            logger.error(
                f"❌ Caption upload FAILED for {video_id} "
                f"(file={srt_file}): {ce}")

    _set_state(
        upload_id,
        status="complete",
        progress=100,
        video_id=video_id,
        video_url=video_url,
        privacy_status=metadata.privacy_status,
        thumbnail_set=thumbnail_set,
        thumbnail_error=thumbnail_error,
        playlists_added=playlists_added,
        playlist_errors=playlist_errors,
        caption_id=caption_id,
        caption_error=caption_error,
    )
    return {
        "video_id": video_id,
        "video_url": video_url,
        "studio_url": (
            f"https://studio.youtube.com/video/{video_id}/edit"
            if video_id else None
        ),
        "thumbnail_set": thumbnail_set,
        "thumbnail_error": thumbnail_error,
        "playlists_added": playlists_added,
        "playlist_errors": playlist_errors,
        "caption_id": caption_id,
        "caption_error": caption_error,
        "metadata": asdict(metadata),
    }


def list_my_playlists() -> List[Dict[str, Any]]:
    """Return all playlists owned by the authenticated channel.
    Each entry: {id, title, description, item_count, privacy_status}."""
    service = _build_service()
    out: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    while True:
        resp = service.playlists().list(
            part="snippet,contentDetails,status",
            mine=True,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for it in resp.get("items", []):
            sn = it.get("snippet", {})
            cd = it.get("contentDetails", {})
            st = it.get("status", {})
            out.append({
                "id": it.get("id"),
                "title": sn.get("title", ""),
                "description": sn.get("description", ""),
                "item_count": cd.get("itemCount", 0),
                "privacy_status": st.get("privacyStatus", ""),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    out.sort(key=lambda p: p["title"].lower())
    return out


def list_published_videos(max_results: int = 100) -> List[Dict[str, Any]]:
    """Return the authenticated channel's uploaded videos, newest first.

    Reads the channel's "uploads" playlist via the YouTube Data API. Each
    entry: {video_id, title, description, url, published_at, thumbnail,
    privacy_status}. ``privacy_status`` is only populated for the videos the
    extra videos().list lookup covers (batched, 50 at a time). Raises if the
    channel is not yet authorized (callers should check is_authorized first).
    """
    service = _build_service()
    # 1) Find the uploads playlist for the authenticated channel.
    ch = service.channels().list(part="contentDetails", mine=True).execute()
    items = ch.get("items", [])
    if not items:
        return []
    uploads_id = (items[0].get("contentDetails", {})
                  .get("relatedPlaylists", {}).get("uploads"))
    if not uploads_id:
        return []

    # 2) Page through the uploads playlist (newest first) up to max_results.
    out: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    while len(out) < max_results:
        resp = service.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=uploads_id,
            maxResults=min(50, max_results - len(out)),
            pageToken=page_token,
        ).execute()
        for it in resp.get("items", []):
            sn = it.get("snippet", {})
            cd = it.get("contentDetails", {})
            vid = (cd.get("videoId")
                   or sn.get("resourceId", {}).get("videoId") or "")
            if not vid:
                continue
            thumbs = sn.get("thumbnails", {})
            thumb = ((thumbs.get("medium") or thumbs.get("default") or {})
                     .get("url", ""))
            out.append({
                "video_id": vid,
                "title": sn.get("title", ""),
                "description": sn.get("description", ""),
                "url": f"https://youtu.be/{vid}",
                "published_at": (cd.get("videoPublishedAt")
                                 or sn.get("publishedAt") or ""),
                "thumbnail": thumb,
                "privacy_status": "",
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    # 3) Batch-fetch privacy status so drafts/private uploads are flagged.
    try:
        ids = [v["video_id"] for v in out]
        status_by_id: Dict[str, str] = {}
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            vr = service.videos().list(
                part="status", id=",".join(chunk)).execute()
            for v in vr.get("items", []):
                status_by_id[v.get("id", "")] = (
                    v.get("status", {}).get("privacyStatus", ""))
        for v in out:
            v["privacy_status"] = status_by_id.get(v["video_id"], "")
    except Exception as e:  # non-fatal — list still works without status
        logger.warning(f"Could not fetch video privacy status: {e}")

    return out


# ---------------------------------------------------------------------------
# Helpers for the UI
# ---------------------------------------------------------------------------

DEFAULT_VIDEO_DIR = Path.home() / "Dev" / "Videos" / "Edited" / "Final"
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
THUMBNAIL_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
# YouTube custom thumbnail size limit: 2 MB.
MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024


def list_thumbnails_for_video(video_path: str) -> List[Dict[str, Any]]:
    """Return thumbnail image entries from the ``thumbnails`` folder that
    sits next to the selected video, e.g.
    ``~/Dev/Videos/Edited/Final/projectX/thumbnails/*.png``."""
    p = Path(video_path).expanduser()
    thumb_dir = p.parent / "thumbnails"
    if not thumb_dir.exists() or not thumb_dir.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for f in sorted(thumb_dir.iterdir(), key=lambda x: x.name.lower()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in THUMBNAIL_EXTS:
            continue
        st = f.stat()
        out.append({
            "path": str(f),
            "name": f.name,
            "size_bytes": st.st_size,
            "too_large": st.st_size > MAX_THUMBNAIL_BYTES,
            "modified": st.st_mtime,
        })
    return out


def list_recent_videos(limit: int = 25,
                       directory: Optional[Path] = None) -> List[Dict[str, Any]]:
    base = (directory or DEFAULT_VIDEO_DIR).expanduser()
    if not base.exists():
        return []
    files: List[Path] = []
    for p in base.rglob("*"):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            files.append(p)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: List[Dict[str, Any]] = []
    for p in files[:limit]:
        st = p.stat()
        out.append({
            "path": str(p),
            "name": p.name,
            "size_bytes": st.st_size,
            "modified": st.st_mtime,
        })
    return out


__all__ = [
    "YouTubeMetadata",
    "parse_youtube_details_markdown",
    "upload_video",
    "is_authorized",
    "has_client_secret",
    "get_upload_status",
    "list_recent_videos",
    "list_thumbnails_for_video",
    "VALID_PRIVACY",
    "CLIENT_SECRET_PATH",
    "TOKEN_PATH",
    "DEFAULT_VIDEO_DIR",
    "THUMBNAIL_EXTS",
    "MAX_THUMBNAIL_BYTES",
]
