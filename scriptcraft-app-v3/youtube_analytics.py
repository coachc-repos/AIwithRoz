"""YouTube Analytics for the channel: per-video performance and retention.

Uses its own read-only Google sign-in (youtube_analytics_token.json, scopes
yt-analytics.readonly and youtube.readonly), separate from the publishing
token, so connecting analytics never changes what publishing runs with. The
OAuth client is the same one publishing uses (youtube_client_secret.json); its
Google Cloud project needs the YouTube Analytics API enabled.

The Analytics API has no thumbnail impressions or impressions click-through
rate. Those come from YouTube Studio's own export (Analytics > Advanced mode >
Export current view > CSV), imported with import_studio_export() and merged
into the report by video ID.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import zipfile
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from youtube_publisher import CLIENT_SECRET_PATH, SCRIPTCRAFT_DIR, _import_google_libs

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly",
          "https://www.googleapis.com/auth/youtube.readonly"]
TOKEN_PATH = SCRIPTCRAFT_DIR / "youtube_analytics_token.json"
REACH_PATH = SCRIPTCRAFT_DIR / "youtube_studio_reach.json"   # imported impressions + CTR

# Report windows the dialog offers. "lifetime" starts before YouTube existed.
RANGES = {"7": 7, "28": 28, "90": 90, "365": 365, "lifetime": None}
VIDEO_METRICS = ["views", "estimatedMinutesWatched", "averageViewDuration",
                 "averageViewPercentage", "likes", "comments", "shares",
                 "subscribersGained"]
SUMMARY_METRICS = "views,averageViewDuration,averageViewPercentage"


# ---------------------------------------------------------------------------
# Sign-in
# ---------------------------------------------------------------------------
def is_connected() -> bool:
    return TOKEN_PATH.exists()


def _save(creds) -> None:
    SCRIPTCRAFT_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass


def connect():
    """Run Google's consent flow in the browser on this computer and save the
    token. Blocks until the user finishes (or the flow times out)."""
    if not CLIENT_SECRET_PATH.exists():
        raise FileNotFoundError(
            "No Google OAuth client installed. Upload client_secret.json in "
            "🔑 API Keys > YouTube Publishing first; analytics uses the same one.")
    libs = _import_google_libs()
    flow = libs["InstalledAppFlow"].from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    creds = flow.run_local_server(
        port=0, prompt="consent",
        authorization_prompt_message="Allow read-only access to the channel's YouTube Analytics in the browser window that opened.",
        success_message="YouTube Analytics connected. You can close this tab and return to Podcast Generator.",
        timeout_seconds=300,
    )
    _save(creds)
    return creds


def disconnect() -> bool:
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
        return True
    return False


def _credentials():
    libs = _import_google_libs()
    if not TOKEN_PATH.exists():
        raise PermissionError("YouTube Analytics is not connected yet.")
    creds = libs["Credentials"].from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(libs["Request"]())
        _save(creds)
    return creds


def _services():
    libs = _import_google_libs()
    creds = _credentials()
    build = libs["build"]
    return (build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False),
            build("youtube", "v3", credentials=creds, cache_discovery=False))


def explain_error(e: Exception) -> str:
    """A plain-language message for the common Google API failures."""
    text = str(e)
    if "accessNotConfigured" in text or "has not been used in project" in text or "is disabled" in text:
        return ("The YouTube Analytics API is not enabled for this Google Cloud project. "
                "Enable 'YouTube Analytics API' in the Google Cloud Console for the project "
                "that owns client_secret.json, then try again.")
    if "invalid_grant" in text or "Token has been expired or revoked" in text:
        return "The analytics sign-in expired or was revoked. Connect YouTube Analytics again."
    if "insufficientPermissions" in text or "Insufficient Permission" in text:
        return "The analytics sign-in is missing a permission. Disconnect and connect again."
    return text[:400]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def window(range_key: str, today: Optional[date] = None) -> tuple:
    """(startDate, endDate) as YYYY-MM-DD. Analytics data lags about two days."""
    end = (today or date.today()) - timedelta(days=1)
    days = RANGES.get(str(range_key), 28)
    start = date(2005, 4, 1) if days is None else end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _iso_duration_seconds(iso: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _summary(r: dict) -> dict:
    return {"views": int(r.get("views") or 0),
            "avg_view_duration": int(r.get("averageViewDuration") or 0),
            "avg_view_percentage": round(float(r.get("averageViewPercentage") or 0), 1)}


def _rows(resp: dict) -> List[dict]:
    """Analytics API rows as dicts keyed by column name."""
    names = [c.get("name") for c in resp.get("columnHeaders", [])]
    return [dict(zip(names, row)) for row in resp.get("rows", []) or []]


def video_report(range_key: str = "28", max_results: int = 200, services=None) -> dict:
    """Per-video metrics for the window, newest metadata from the Data API, and
    impressions + CTR merged in from the last Studio import."""
    yta, yt = services or _services()
    start, end = window(range_key)
    resp = yta.reports().query(
        ids="channel==MINE", startDate=start, endDate=end,
        metrics=",".join(VIDEO_METRICS), dimensions="video",
        sort="-views", maxResults=max(1, min(max_results, 200))).execute()
    rows = _rows(resp)
    ids = [r["video"] for r in rows]
    # A short window can hold a handful of views that left within a second, so
    # each video also carries its lifetime average for comparison.
    lifetime: Dict[str, dict] = {}
    if RANGES.get(str(range_key), 28) is not None:
        ls, le = window("lifetime")
        for r in _rows(yta.reports().query(
                ids="channel==MINE", startDate=ls, endDate=le, metrics=SUMMARY_METRICS,
                dimensions="video", sort="-views", maxResults=200).execute()):
            lifetime[r["video"]] = _summary(r)
    meta: Dict[str, dict] = {}
    for i in range(0, len(ids), 50):
        batch = yt.videos().list(part="snippet,contentDetails", id=",".join(ids[i:i + 50]),
                                 maxResults=50).execute()
        for it in batch.get("items", []):
            sn, cd = it.get("snippet", {}), it.get("contentDetails", {})
            thumbs = sn.get("thumbnails", {})
            meta[it["id"]] = {
                "title": sn.get("title", ""),
                "published_at": sn.get("publishedAt", ""),
                "thumbnail": (thumbs.get("medium") or thumbs.get("default") or {}).get("url", ""),
                "duration_seconds": _iso_duration_seconds(cd.get("duration", "")),
            }
    reach = load_reach()
    videos = []
    for r in rows:
        vid = r["video"]
        m = meta.get(vid, {})
        rc = reach.get("videos", {}).get(vid, {})
        videos.append({
            "id": vid, "url": f"https://youtu.be/{vid}",
            "title": m.get("title", vid), "published_at": m.get("published_at", ""),
            "thumbnail": m.get("thumbnail", ""), "duration_seconds": m.get("duration_seconds", 0),
            "views": int(r.get("views") or 0),
            "watch_minutes": float(r.get("estimatedMinutesWatched") or 0),
            "watch_hours": round(float(r.get("estimatedMinutesWatched") or 0) / 60, 1),
            "avg_view_duration": int(r.get("averageViewDuration") or 0),
            "avg_view_percentage": round(float(r.get("averageViewPercentage") or 0), 1),
            "likes": int(r.get("likes") or 0), "comments": int(r.get("comments") or 0),
            "shares": int(r.get("shares") or 0), "subscribers_gained": int(r.get("subscribersGained") or 0),
            "impressions": rc.get("impressions"), "ctr": rc.get("ctr"),
            "lifetime": lifetime.get(vid),
        })
    return {"start": start, "end": end, "range": str(range_key), "videos": videos,
            "totals": totals(videos), "reach_imported_at": reach.get("imported_at"),
            "reach_source": reach.get("source")}


def totals(videos: List[dict]) -> dict:
    views = sum(v["views"] for v in videos)
    # Raw minutes: each video's watch_hours is rounded to 0.1 hours (6 minutes).
    minutes = sum(v.get("watch_minutes", v["watch_hours"] * 60) for v in videos)
    watch_hours = minutes / 60
    with_reach = [v for v in videos if v.get("impressions")]
    impressions = sum(v["impressions"] for v in with_reach)
    clicks = sum(v["impressions"] * (v["ctr"] or 0) / 100 for v in with_reach)
    return {
        "videos": len(videos), "views": views, "watch_hours": round(watch_hours, 1),
        "avg_view_duration": round(minutes * 60 / views) if views else 0,
        "subscribers_gained": sum(v["subscribers_gained"] for v in videos),
        "impressions": impressions or None,
        "ctr": round(clicks / impressions * 100, 1) if impressions else None,
    }


def retention(video_id: str, range_key: str = "lifetime", services=None) -> dict:
    """The audience retention curve: share of viewers still watching at each
    point (audienceWatchRatio) and how that compares with similar-length videos
    (relativeRetentionPerformance, 0 to 1)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id or ""):
        raise ValueError("Invalid video ID")
    yta, _yt = services or _services()
    start, end = window(range_key)
    resp = yta.reports().query(
        ids="channel==MINE", startDate=start, endDate=end,
        metrics="audienceWatchRatio,relativeRetentionPerformance",
        dimensions="elapsedVideoTimeRatio", filters=f"video=={video_id}").execute()
    points = [{"t": float(r["elapsedVideoTimeRatio"]),
               "watch": float(r.get("audienceWatchRatio") or 0),
               "relative": float(r.get("relativeRetentionPerformance") or 0)}
              for r in _rows(resp)]
    points.sort(key=lambda p: p["t"])
    # The video's own average over the same window as the curve.
    rows = _rows(yta.reports().query(
        ids="channel==MINE", startDate=start, endDate=end, metrics=SUMMARY_METRICS,
        filters=f"video=={video_id}").execute())
    return {"video_id": video_id, "points": points, "drops": biggest_drops(points),
            **(_summary(rows[0]) if rows else {})}


def biggest_drops(points: List[dict], n: int = 3) -> List[dict]:
    """The n steepest falls in retention between neighbouring points, after the
    first 5 percent (the opening always drops)."""
    falls = []
    for a, b in zip(points, points[1:]):
        if a["t"] < 0.05:
            continue
        falls.append({"t": b["t"], "drop": round(a["watch"] - b["watch"], 4)})
    falls = [f for f in falls if f["drop"] > 0]
    falls.sort(key=lambda f: f["drop"], reverse=True)
    return sorted(falls[:n], key=lambda f: f["t"])


# ---------------------------------------------------------------------------
# Impressions and CTR from a YouTube Studio export
# ---------------------------------------------------------------------------
def load_reach() -> dict:
    try:
        return json.loads(REACH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _num(text) -> Optional[float]:
    t = str(text or "").strip().replace(",", "").replace("%", "")
    try:
        return float(t)
    except ValueError:
        return None


def parse_studio_export(data: bytes, filename: str = "") -> Dict[str, dict]:
    """Impressions and CTR per video ID from Studio's export: the .zip it
    downloads (its 'Table data.csv') or that CSV on its own."""
    text = None
    if filename.lower().endswith(".zip") or data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith("table data.csv")), None) \
                or next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
            if not name:
                raise ValueError("No CSV found in the zip.")
            text = z.read(name).decode("utf-8-sig", errors="replace")
    else:
        text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    cols = reader.fieldnames or []
    low = {c: c.lower() for c in cols}
    id_col = next((c for c in cols if low[c] in ("content", "video", "video id")), None)
    imp_col = next((c for c in cols if low[c].startswith("impressions") and "click" not in low[c]), None)
    ctr_col = next((c for c in cols if "click-through" in low[c] or "ctr" in low[c]), None)
    if not (id_col and imp_col and ctr_col):
        raise ValueError("This CSV has no Impressions and Impressions click-through rate columns. "
                         "In Studio, open Analytics > Advanced mode, show those columns, then Export current view > CSV.")
    out = {}
    for row in reader:
        vid = (row.get(id_col) or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            continue          # the Total row and anything that is not a video
        imp, ctr = _num(row.get(imp_col)), _num(row.get(ctr_col))
        if imp is None:
            continue
        out[vid] = {"impressions": int(imp), "ctr": ctr}
    if not out:
        raise ValueError("No video rows with impressions were found in this CSV.")
    return out


def import_studio_export(data: bytes, filename: str = "") -> dict:
    from datetime import datetime
    videos = parse_studio_export(data, filename)
    record = {"imported_at": datetime.now().isoformat(timespec="seconds"),
              "source": filename or "studio export", "videos": videos}
    SCRIPTCRAFT_DIR.mkdir(parents=True, exist_ok=True)
    REACH_PATH.write_text(json.dumps(record), encoding="utf-8")
    return {"videos": len(videos), "imported_at": record["imported_at"]}
