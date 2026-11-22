"""Article highlight slides and spoken-emphasis underlines.

An article is a screenshot saved in the project, the same way logos and clips
are. OCR reads lines and boxes. The user keeps the lines that match the
narration. The picture slides in over the wave background and a marker stroke
draws under each chosen line when that sentence is spoken.

Emphasis comes from script markup and, when a narration WAV is on disk, from
words that are louder, higher, or held longer than the rest of the slide.
A stroke is drawn only when that phrase is actually on the slide.

No API key is read from the repo. Azure Document Intelligence is used only
when its endpoint and key are already in the environment.
"""
from __future__ import annotations

import base64
import difflib
import io
import math
import os
import re
import shutil
import subprocess
import uuid
import wave
from pathlib import Path
from typing import Optional

ARTICLE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
ACCENT = "#f5b83d"
ENTRANCE = 0.9          # the sheet has settled by now; strokes start after this
MAX_BYTES = 20 * 1024 * 1024
MAX_MARKS = 4           # markup plus audio, per slide
MAX_AUDIO = 2           # audio-only hits, per slide
LINE_SCORE = 0.62
MAX_SUGGESTED = 4

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")
_STOP = {
    "a", "an", "the", "of", "to", "and", "in", "on", "for", "with", "is", "are",
    "was", "were", "be", "been", "being", "it", "its", "this", "that", "these",
    "those", "as", "by", "from", "or", "at", "if", "so", "but", "not", "no",
    "nor", "you", "your", "we", "our", "they", "their", "he", "she", "i", "me",
    "my", "do", "did", "does", "have", "has", "had", "will", "would", "can",
    "could", "should", "may", "might", "just", "than", "then", "very", "into",
    "over", "about", "up", "out", "off", "when", "what", "which", "who", "how",
}
_FUNCTION = _STOP | {"again", "also", "there", "here", "them", "his", "her"}
_PAYWALL = (
    "subscribe to continue",
    "subscribers only",
    "sign in to read",
    "log in to continue",
    "this article is for subscribers",
    "already a subscriber",
    "create a free account",
    "you've reached your limit",
    "you have reached your limit",
    "to continue reading",
    "register to continue",
    "paid subscribers",
)
_PAYWALL_MSG = (
    "That page looks paywalled or behind a sign-in, so it was not captured. "
    "Upload a PNG, JPEG or WebP screenshot instead."
)
_CAPTURE_MISS = (
    "Could not capture that page. Headless Chrome is not installed and Playwright "
    "is not available. Upload a PNG, JPEG or WebP screenshot instead."
)


class ArticleError(Exception):
    pass


def tokens(text: str) -> list:
    return _TOKEN_RE.findall((text or "").lower().replace("’", "'").replace("‘", "'"))


def norm_phrase(text: str) -> str:
    return " ".join(tokens(text))


def url_problem(url: str) -> Optional[str]:
    """A public http(s) article URL, or a short reason it was refused."""
    import urllib.parse
    raw = (url or "").strip()
    parts = urllib.parse.urlparse(raw)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return "Paste a full http or https article URL."
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return "Paste a full http or https article URL."
    if host in {"localhost", "0.0.0.0", "169.254.169.254"} or host.endswith(".local") or host.endswith(".internal"):
        return "That address is not a public article page. Upload a screenshot instead."
    if host.startswith("127.") or host.startswith("10.") or host.startswith("192.168.") or host.startswith("169.254."):
        return "That address is not a public article page. Upload a screenshot instead."
    if host.startswith("172."):
        bits = host.split(".")
        if len(bits) == 4 and bits[1].isdigit() and 16 <= int(bits[1]) <= 31:
            return "That address is not a public article page. Upload a screenshot instead."
    return None


def paywalled(text: str) -> bool:
    """True when the captured page is a short sign-in or subscription wall."""
    raw = re.sub(r"\s+", " ", (text or "").lower())
    if not any(p in raw[:1800] for p in _PAYWALL):
        return False
    words = re.findall(r"[a-z]{3,}", raw)
    return len(words) < 220 or any(p in raw[:700] for p in _PAYWALL)


def line_score(line: str, narration: str) -> float:
    """How well one OCR line matches a stretch of narration. 0..1."""
    lt = tokens(line)
    nt = tokens(narration)
    content = [t for t in lt if t not in _STOP and len(t) >= 4]
    if len(content) < 2 or not nt:
        return 0.0
    nset = set(nt)
    hit = sum(1 for t in content if t in nset)
    overlap = hit / len(content)
    if hit < 2 or overlap < 0.45:
        return overlap * 0.5
    blob = " ".join(nt)
    pos, ordered = 0, True
    for t in content:
        j = blob.find(t, pos)
        if j < 0:
            ordered = False
            break
        pos = j + len(t)
    if not ordered:
        return overlap * 0.55
    if overlap >= 0.72:
        return 0.55 + 0.45 * overlap
    # A window the same length as the line, so a long narration does not dilute the ratio.
    window = min(len(nt), max(len(lt), len(content) + 2))
    sm = difflib.SequenceMatcher(autojunk=False)
    sm.set_seq2(" ".join(lt))
    best = 0.0
    step = max(1, window // 3)
    for i in range(0, max(1, len(nt) - window + 1), step):
        sm.set_seq1(" ".join(nt[i:i + window]))
        if sm.quick_ratio() < 0.45:
            continue
        best = max(best, sm.ratio())
    return max(overlap, 0.55 + 0.45 * overlap) if best >= 0.45 or overlap >= 0.72 else overlap * 0.7


def suggest_lines(lines: list, narration: str, limit: int = MAX_SUGGESTED) -> list:
    """Ids of the OCR lines that match the narration, best first, few of them."""
    ranked = []
    for line in lines or []:
        score = line_score(line.get("text") or "", narration or "")
        if score >= LINE_SCORE:
            ranked.append((score, line.get("y") or 0, line.get("id")))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    out = []
    for _score, _y, lid in ranked:
        if lid and lid not in out:
            out.append(lid)
        if len(out) >= limit:
            break
    return out


def _word_tokens(words: list, t0: float, t1: float) -> list:
    toks = []
    for w in words or []:
        try:
            start, end = float(w.get("start") or 0), float(w.get("end") or 0)
        except (TypeError, ValueError):
            continue
        if start < t0 - 0.05 or start >= t1 + 0.05:
            continue
        parts = tokens(w.get("text") or "")
        if not parts:
            continue
        span = max(0.01, end - start)
        for i, tok in enumerate(parts):
            a = start + span * i / len(parts)
            b = start + span * (i + 1) / len(parts)
            toks.append((tok, a, b))
    return toks


def phrase_span(phrase: str, words: list, t0: float, t1: float) -> Optional[tuple]:
    """(start, end) of `phrase` inside the slide, from word timestamps. None if it is not spoken there."""
    want = tokens(phrase)
    toks = _word_tokens(words, t0, t1)
    m = len(want)
    if not m or len(toks) < m:
        return None
    for i in range(len(toks) - m + 1):
        if all(toks[i + k][0] == want[k] for k in range(m)):
            return toks[i][1], toks[i + m - 1][2]
    target = " ".join(want)
    sm = difflib.SequenceMatcher(autojunk=False)
    sm.set_seq2(target)
    best, best_i = 0.0, None
    for i in range(len(toks) - m + 1):
        sm.set_seq1(" ".join(toks[i + k][0] for k in range(m)))
        if sm.quick_ratio() < 0.72:
            continue
        ratio = sm.ratio()
        if ratio > best:
            best, best_i = ratio, i
    if best_i is None or best < 0.78:
        return None
    return toks[best_i][1], toks[best_i + m - 1][2]


def line_cues(lines: list, chosen: list, words: list, t0: float, t1: float) -> list:
    """One cue per chosen line, in reading order.

    A line that matches the timed narration starts when that sentence is spoken,
    and not before the sheet has settled. Lines with no match share the slide
    evenly after the entrance.
    """
    want = set(chosen or [])
    picked = [ln for ln in (lines or []) if ln.get("id") in want]
    picked.sort(key=lambda ln: (float(ln.get("y") or 0), str(ln.get("id"))))
    n = len(picked)
    if not n:
        return []
    t0, t1 = float(t0), float(t1)
    floor = t0 + ENTRANCE
    span = max(0.3, (t1 - t0) - ENTRANCE - 0.15)
    step = span / n
    found = []
    for ln in picked:
        hit = phrase_span(ln.get("text") or "", words, t0, t1) if words else None
        found.append(hit[0] if hit else None)
    if any(t is None for t in found):
        times = []
        for i, t in enumerate(found):
            if t is None:
                times.append(floor + step * i)
            else:
                times.append(max(floor, t))
    else:
        times = [max(floor, t) for t in found]
    out = []
    for ln, t in zip(picked, times):
        out.append({
            "id": ln.get("id"),
            "text": ln.get("text") or "",
            "x": float(ln.get("x") or 0),
            "y": float(ln.get("y") or 0),
            "w": float(ln.get("w") or 0),
            "h": float(ln.get("h") or 0),
            "t": round(min(t, max(floor, t1 - 0.05)), 3),
        })
    return out


def _clean_phrase(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip(" *_`")


def markup_phrases(text: str) -> list:
    """Bold, italics, a few CAPS words, and SSML emphasis. A shouted heading is not emphasis."""
    raw = text or ""
    found = []

    def add(phrase: str, kind: str) -> None:
        phrase = _clean_phrase(phrase)
        if not phrase or not tokens(phrase):
            return
        key = (kind, norm_phrase(phrase))
        if any((x["kind"], norm_phrase(x["phrase"])) == key for x in found):
            return
        found.append({"phrase": phrase[:80], "kind": kind})

    for match in re.finditer(r"\*\*([^*\n]{1,80}?)\*\*|__([^_\n]{1,80}?)__", raw):
        add(next(g for g in match.groups() if g), "bold")
    for match in re.finditer(r"<emphasis\b[^>]*>([\s\S]{1,120}?)</emphasis>", raw, re.I):
        add(match.group(1), "ssml")
    without_bold = re.sub(r"\*\*[^*\n]+\*\*|__[^_\n]+__", " ", raw)
    for match in re.finditer(r"(?<!\*)\*([^*\n]{2,80}?)\*(?!\*)|(?<!_)_([^_\n]{2,80}?)_(?!_)", without_bold):
        add(next(g for g in match.groups() if g), "italic")
    for line in raw.splitlines():
        words = re.findall(r"[A-Za-z][A-Za-z0-9']*", line)
        caps = [w for w in words if len(w) >= 4 and w.isupper()]
        if not caps or not words or len(caps) / len(words) > 0.5:
            continue
        for word in caps[:2]:
            add(word, "caps")
    return found


def contains_phrase(text: str, phrase: str) -> bool:
    """True when the phrase's words appear in order in `text`."""
    want = tokens(phrase)
    have = tokens(text)
    if not want or len(have) < len(want):
        return False
    for i in range(len(have) - len(want) + 1):
        if have[i:i + len(want)] == want:
            return True
    return False


def _z(values: list, value: float) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    sd = math.sqrt(var)
    if sd < 1e-6:
        return 0.0
    return (value - mean) / sd


def emphasis_from_audio(wav_path, words: list, t0: float, t1: float, levels: Optional[dict] = None) -> list:
    """At most a couple of words on this slide that stand out in the WAV.

    A word counts when it is clearly louder than the slide and also higher or
    held longer. Function words never count. `levels` maps a word index to
    (rms, zero-crossing rate) when the caller already measured the file.
    """
    indexed = []
    for i, w in enumerate(words or []):
        try:
            start = float(w.get("start") or 0)
            end = float(w.get("end") or 0)
        except (TypeError, ValueError):
            continue
        if start < t0 - 0.02 or start >= t1:
            continue
        parts = tokens(w.get("text") or "")
        if len(parts) != 1 or parts[0] in _FUNCTION or len(parts[0]) < 4:
            continue
        indexed.append((i, w, end - start))
    if len(indexed) < 4:
        return []
    measured = levels if levels is not None else _levels_for(wav_path, words)
    if not measured:
        return []
    rows = []
    for i, w, dur in indexed:
        rms, zcr = measured.get(i, (0.0, 0.0))
        if rms <= 0:
            continue
        rows.append({"i": i, "text": (w.get("text") or "").strip(), "start": float(w["start"]),
                     "end": float(w["end"]), "rms": rms, "zcr": zcr, "dur": max(0.0, dur)})
    if len(rows) < 4:
        return []
    rms_v = [r["rms"] for r in rows]
    zcr_v = [r["zcr"] for r in rows]
    dur_v = [r["dur"] for r in rows]
    ranked = []
    for r in rows:
        zr, zp, zd = _z(rms_v, r["rms"]), _z(zcr_v, r["zcr"]), _z(dur_v, r["dur"])
        loud = zr >= 1.15 and (zp >= 0.55 or zd >= 0.65)
        if not loud and zr < 1.7:
            continue
        score = 0.6 * zr + 0.25 * max(0.0, zp) + 0.15 * max(0.0, zd)
        if score < 1.2:
            continue
        ranked.append((score, r))
    ranked.sort(key=lambda pair: -pair[0])
    if not ranked:
        return []
    picked = [ranked[0][1]]
    if len(ranked) > 1 and ranked[1][0] >= 1.35:
        other = ranked[1][1]
        if abs(other["i"] - picked[0]["i"]) > 1:
            picked.append(other)
    # Adjacent standouts are one phrase, still counting as a single hit.
    if len(ranked) > 1 and abs(ranked[1][1]["i"] - ranked[0][1]["i"]) == 1 and ranked[1][0] >= 1.2:
        a, b = sorted((ranked[0][1], ranked[1][1]), key=lambda r: r["start"])
        return [{"phrase": f"{a['text']} {b['text']}", "t": round(a["start"], 3), "kind": "audio"}]
    return [{"phrase": r["text"], "t": round(r["start"], 3), "kind": "audio"} for r in picked[:MAX_AUDIO]]


def _levels_for(wav_path, words: list) -> dict:
    path = Path(wav_path) if wav_path else None
    if path is None or not path.is_file():
        return {}
    try:
        stat = path.stat()
    except OSError:
        return {}
    key = (str(path), stat.st_mtime, stat.st_size, len(words or []))
    cached = _LEVEL_CACHE.get(key)
    if cached is not None:
        return cached
    out = _read_levels(path, words or [])
    _LEVEL_CACHE[key] = out
    return out


_LEVEL_CACHE: dict = {}


def _read_levels(path: Path, words: list) -> dict:
    """RMS and zero-crossing rate for each word. The file is read once, in order."""
    try:
        handle = wave.open(str(path), "rb")
    except (wave.Error, OSError):
        return {}
    with handle:
        channels, width, rate, nframes = handle.getnchannels(), handle.getsampwidth(), handle.getframerate(), handle.getnframes()
        if width != 2 or rate <= 0 or channels < 1 or nframes < 2:
            return {}
        frame_bytes = width * channels
        out = {}
        for i, w in enumerate(words):
            try:
                start, end = float(w.get("start") or 0), float(w.get("end") or 0)
            except (TypeError, ValueError):
                continue
            a = max(0, min(nframes - 1, int(start * rate)))
            b = max(a + 1, min(nframes, int(end * rate)))
            handle.setpos(a)
            raw = handle.readframes(b - a)
            out[i] = _pcm_stats(raw, channels, frame_bytes)
        return out


def _pcm_stats(raw: bytes, channels: int, frame_bytes: int) -> tuple:
    if not raw:
        return 0.0, 0.0
    usable = raw[:len(raw) - (len(raw) % frame_bytes)]
    if len(usable) < frame_bytes * 8:
        return 0.0, 0.0
    step = frame_bytes * 4
    acc, count, crossings, prev = 0.0, 0, 0, 0
    for offset in range(0, len(usable) - 1, step):
        sample = int.from_bytes(usable[offset:offset + 2], "little", signed=True)
        acc += sample * sample
        if count and (sample >= 0) != (prev >= 0) and abs(sample) > 250:
            crossings += 1
        prev = sample
        count += 1
    if not count:
        return 0.0, 0.0
    return math.sqrt(acc / count) / 32768.0, crossings / count


def _slide_plain(html: str, slide_id: str) -> str:
    if not html or not slide_id:
        return ""
    match = re.search(r'<section\b[^>]*\bid="' + re.escape(slide_id) + r'"[^>]*>([\s\S]*?)</section>', html, re.I)
    if not match:
        return ""
    body = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", match.group(1), flags=re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", body).strip()


def emphasis_prefs(data: Optional[dict]) -> dict:
    raw = (data or {}).get("emphasis") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        raw = {}
    slides = raw.get("slides") if isinstance(raw.get("slides"), dict) else {}
    return {
        "enabled": True if "enabled" not in raw else bool(raw.get("enabled")),
        "slides": {str(k): bool(v) for k, v in slides.items()},
        "removed": [x for x in (raw.get("removed") or []) if isinstance(x, dict)],
        "added": [x for x in (raw.get("added") or []) if isinstance(x, dict)],
    }


def slide_enabled(prefs: dict, slide_id: str) -> bool:
    flags = prefs.get("slides") or {}
    if slide_id in flags:
        return bool(flags[slide_id])
    return bool(prefs.get("enabled", True))


def _removed(prefs: dict) -> set:
    return {(str(x.get("slide") or ""), norm_phrase(x.get("phrase") or "")) for x in prefs.get("removed") or []}


def collect_marks(script: str, slides: list, words: list, wav_path=None, prefs: Optional[dict] = None,
                  html: str = "") -> list:
    """Every detected phrase, including ones that will not be drawn."""
    prefs = prefs or emphasis_prefs({})
    gone = _removed(prefs)
    phrases = markup_phrases(script or "")
    levels = _levels_for(wav_path, words) if wav_path and slides else {}
    marks = []
    for slide in slides or []:
        sid = str(slide.get("id") or "")
        t0, t1 = float(slide.get("t0") or 0), float(slide.get("t1") or 0)
        spoken = slide.get("spoken") or ""
        visible = _slide_plain(html, sid) or slide.get("text") or ""
        on = slide_enabled(prefs, sid)
        count = 0
        for phrase in phrases:
            key = (sid, norm_phrase(phrase["phrase"]))
            in_spoken = contains_phrase(spoken, phrase["phrase"])
            in_visible = contains_phrase(visible, phrase["phrase"])
            if not in_spoken and not in_visible:
                continue
            if key in gone or count >= MAX_MARKS:
                continue
            span = phrase_span(phrase["phrase"], words, t0, t1)
            marks.append({
                "slide": sid, "phrase": phrase["phrase"], "kind": phrase["kind"], "source": phrase["kind"],
                "t": round(span[0], 3) if span else None, "on_slide": in_visible, "enabled": on,
            })
            count += 1
        if on and count < MAX_MARKS and levels:
            for hit in emphasis_from_audio(wav_path, words, t0, t1, levels):
                key = (sid, norm_phrase(hit["phrase"]))
                if key in gone or any(norm_phrase(m["phrase"]) == key[1] and m["slide"] == sid for m in marks):
                    continue
                if count >= MAX_MARKS:
                    break
                visible_hit = contains_phrase(visible, hit["phrase"])
                marks.append({
                    "slide": sid, "phrase": hit["phrase"], "kind": "audio", "source": "audio",
                    "t": hit.get("t"), "on_slide": visible_hit, "enabled": on,
                })
                count += 1
    for extra in prefs.get("added") or []:
        sid = str(extra.get("slide") or "")
        phrase = _clean_phrase(extra.get("phrase") or "")
        if not sid or not phrase or (sid, norm_phrase(phrase)) in gone:
            continue
        slide = next((s for s in slides or [] if str(s.get("id")) == sid), None)
        if slide is None:
            continue
        if any(m["slide"] == sid and norm_phrase(m["phrase"]) == norm_phrase(phrase) for m in marks):
            continue
        t0, t1 = float(slide.get("t0") or 0), float(slide.get("t1") or 0)
        span = phrase_span(phrase, words, t0, t1)
        visible = _slide_plain(html, sid) or slide.get("text") or ""
        marks.append({
            "slide": sid, "phrase": phrase[:80], "kind": "added", "source": "added",
            "t": round(span[0], 3) if span else None,
            "on_slide": contains_phrase(visible, phrase), "enabled": slide_enabled(prefs, sid),
        })
    return marks


def drawable_marks(marks: list, slides: list) -> list:
    """Marks the runtime should stroke: enabled, on the slide, and timed."""
    ends = {str(s.get("id")): float(s.get("t1") or 0) for s in slides or []}
    out = []
    for mark in marks or []:
        if not mark.get("enabled") or not mark.get("on_slide") or mark.get("t") is None:
            continue
        out.append({
            "slide": mark["slide"], "phrase": mark["phrase"],
            "t": float(mark["t"]), "t1": ends.get(mark["slide"], float(mark["t"]) + 1),
        })
    return out


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def _azure_env() -> tuple:
    endpoint = (os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
                or os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT") or "").strip()
    key = (os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")
           or os.getenv("AZURE_DOCUMENT_INTELLIGENCE_API_KEY")
           or os.getenv("AZURE_FORM_RECOGNIZER_KEY") or "").strip()
    return endpoint, key


def _can(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def ocr_status() -> dict:
    endpoint, key = _azure_env()
    return {
        "azure": bool(endpoint and key),
        "tesseract": bool(shutil.which("tesseract")) and _can("pytesseract"),
        "rapidocr": _can("rapidocr_onnxruntime") or _can("rapidocr"),
        "playwright": _can("playwright"),
        "chrome": bool(_chrome_bin()),
    }


def ocr_image(path: Path) -> dict:
    """Lines with normalized boxes. The first configured engine that returns text wins."""
    path = Path(path)
    errors = []
    endpoint, key = _azure_env()
    if endpoint and key:
        try:
            lines = _ocr_azure(path, endpoint, key)
            if lines:
                return {"engine": "azure", "lines": lines, "error": ""}
            errors.append("Azure Document Intelligence returned no text lines.")
        except Exception as exc:
            errors.append("Azure Document Intelligence failed: " + _safe_err(exc))
    if shutil.which("tesseract") and _can("pytesseract"):
        try:
            lines = _ocr_tesseract(path)
            if lines:
                return {"engine": "tesseract", "lines": lines, "error": ""}
            errors.append("Tesseract found no text lines.")
        except Exception as exc:
            errors.append("Tesseract failed: " + _safe_err(exc))
    if _can("rapidocr_onnxruntime") or _can("rapidocr"):
        try:
            lines = _ocr_rapid(path)
            if lines:
                return {"engine": "rapidocr", "lines": lines, "error": ""}
            errors.append("RapidOCR found no text lines.")
        except Exception as exc:
            errors.append("RapidOCR failed: " + _safe_err(exc))
    hint = (
        "No OCR engine is available. Set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and "
        "AZURE_DOCUMENT_INTELLIGENCE_KEY (they are not stored in the repo), or install "
        "Tesseract plus pytesseract, or pip install rapidocr-onnxruntime. "
        "The image is saved either way."
    )
    if not errors and not (endpoint or shutil.which("tesseract") or _can("rapidocr_onnxruntime") or _can("rapidocr")):
        errors = []
    return {"engine": "", "lines": [], "error": (" ".join(errors) + " " + hint).strip()}


def _safe_err(exc: Exception) -> str:
    text = str(exc)
    text = re.sub(r"(?i)(key|token|secret)=[^&\s]+", r"\1=…", text)
    return text[:180]


def _norm_box(x: float, y: float, w: float, h: float, width: float, height: float) -> Optional[dict]:
    if width <= 0 or height <= 0 or w <= 1 or h <= 1:
        return None
    return {
        "x": round(max(0.0, min(1.0, x / width)), 4),
        "y": round(max(0.0, min(1.0, y / height)), 4),
        "w": round(max(0.0, min(1.0, w / width)), 4),
        "h": round(max(0.0, min(1.0, h / height)), 4),
    }


def _number_lines(items: list) -> list:
    out = []
    for i, item in enumerate(items):
        text = re.sub(r"\s+", " ", item.get("text") or "").strip()
        if len(text) < 2:
            continue
        out.append({"id": f"l{i}", "text": text[:240], "x": item["x"], "y": item["y"], "w": item["w"], "h": item["h"]})
    return out


def _ocr_tesseract(path: Path) -> list:
    import pytesseract
    from PIL import Image
    image = Image.open(path).convert("RGB")
    width, height = image.size
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    groups: dict = {}
    n = len(data.get("text") or [])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if not text or conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        left, top = int(data["left"][i]), int(data["top"][i])
        groups.setdefault(key, []).append((left, top, int(data["width"][i]), int(data["height"][i]), text))
    items = []
    for key in sorted(groups):
        parts = groups[key]
        text = " ".join(p[4] for p in parts)
        x0 = min(p[0] for p in parts)
        y0 = min(p[1] for p in parts)
        x1 = max(p[0] + p[2] for p in parts)
        y1 = max(p[1] + p[3] for p in parts)
        box = _norm_box(x0, y0, x1 - x0, y1 - y0, width, height)
        if box:
            items.append({"text": text, **box})
    return _number_lines(items)


def _ocr_rapid(path: Path) -> list:
    from PIL import Image
    with Image.open(path) as image:
        width, height = image.size
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        from rapidocr import RapidOCR
    engine = RapidOCR()
    result, _elapse = engine(str(path))
    items = []
    for row in result or []:
        box, text = row[0], row[1]
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        norm = _norm_box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys), width, height)
        if norm and (text or "").strip():
            items.append({"text": text, **norm})
    return _number_lines(items)


def _ocr_azure(path: Path, endpoint: str, key: str) -> list:
    import time
    import requests
    suffix = path.suffix.lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix, "image/png")
    url = endpoint.rstrip("/") + "/documentintelligence/documentModels/prebuilt-read:analyze?api-version=2024-11-30"
    response = requests.post(url, headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": mime},
                             data=path.read_bytes(), timeout=60)
    if response.status_code not in (200, 202):
        raise ArticleError(f"HTTP {response.status_code}")
    if response.status_code == 200 and response.content:
        body = response.json()
    else:
        op = response.headers.get("Operation-Location") or ""
        if not op:
            raise ArticleError("no operation location")
        body = {}
        for _ in range(30):
            time.sleep(0.6)
            poll = requests.get(op, headers={"Ocp-Apim-Subscription-Key": key}, timeout=30)
            if poll.status_code != 200:
                raise ArticleError(f"HTTP {poll.status_code}")
            body = poll.json()
            if (body.get("status") or "").lower() in {"succeeded", "failed"}:
                break
        if (body.get("status") or "").lower() != "succeeded":
            raise ArticleError(body.get("status") or "did not finish")
    analyze = body.get("analyzeResult") or body
    items = []
    for page in analyze.get("pages") or []:
        width = float(page.get("width") or 0)
        height = float(page.get("height") or 0)
        for line in page.get("lines") or []:
            polygon = line.get("polygon") or []
            if len(polygon) < 8:
                continue
            xs, ys = polygon[0::2], polygon[1::2]
            box = _norm_box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys), width, height)
            if box and (line.get("content") or "").strip():
                items.append({"text": line["content"], **box})
    return _number_lines(items)


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def _chrome_bin() -> str:
    env = os.getenv("SCRIPTCRAFT_CHROME", "").strip()
    if env and Path(env).is_file():
        return env
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def capture_url(url: str, dest: Path) -> dict:
    """Save a screenshot of a public article. On failure, `error` tells the user to upload one."""
    problem = url_problem(url)
    if problem:
        return {"ok": False, "error": problem}
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    playwright_error = ""
    if _can("playwright"):
        try:
            shot = _capture_playwright(url, dest)
            if shot.get("ok") or shot.get("paywalled"):
                return shot
            playwright_error = shot.get("error") or ""
        except Exception as exc:
            playwright_error = _safe_err(exc)
    chrome = _chrome_bin()
    if not chrome:
        return {"ok": False, "error": playwright_error or _CAPTURE_MISS}
    shot = _capture_chrome(chrome, url, dest)
    if not shot.get("ok") and playwright_error and not shot.get("paywalled"):
        shot["error"] = shot.get("error") or playwright_error
    return shot


def _capture_playwright(url: str, dest: Path) -> dict:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1100, "height": 1500})
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(600)
            text = page.inner_text("body")[:8000]
            if paywalled(text):
                return {"ok": False, "error": _PAYWALL_MSG, "paywalled": True}
            page.screenshot(path=str(dest), full_page=False)
        finally:
            browser.close()
    if not dest.is_file() or dest.stat().st_size < 800:
        return {"ok": False, "error": "The capture was empty. Upload a screenshot instead."}
    return {"ok": True}


def _capture_chrome(chrome: str, url: str, dest: Path) -> dict:
    flags = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
             "--hide-scrollbars", "--virtual-time-budget=8000"]
    try:
        dom = subprocess.run(flags + ["--dump-dom", url], capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "The page took too long to load. Upload a screenshot instead."}
    except OSError as exc:
        return {"ok": False, "error": "Headless Chrome could not start. Upload a screenshot instead. " + _safe_err(exc)}
    text = re.sub(r"<[^>]+>", " ", dom.stdout or "")
    if paywalled(text):
        return {"ok": False, "error": _PAYWALL_MSG, "paywalled": True}
    work = dest.parent
    try:
        subprocess.run(flags + ["--window-size=1100,1500", f"--screenshot={dest}", url],
                       capture_output=True, text=True, timeout=25, cwd=str(work))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "The page took too long to capture. Upload a screenshot instead."}
    if not dest.is_file():
        fallback = work / "screenshot.png"
        if fallback.is_file():
            fallback.replace(dest)
    if not dest.is_file() or dest.stat().st_size < 800:
        return {"ok": False, "error": "The capture was empty. The page may have blocked the screenshot. Upload one instead."}
    return {"ok": True}


# ---------------------------------------------------------------------------
# Project storage
# ---------------------------------------------------------------------------

def _items(project) -> list:
    raw = project.data.get("articles")
    if isinstance(raw, dict):
        raw = raw.get("items")
    return raw if isinstance(raw, list) else []


def _save_items(project, items: list) -> None:
    with project.lock:
        project.data["articles"] = items
        project.save()


def _read_image(raw: bytes, filename: str) -> tuple:
    ext = Path(filename or "").suffix.lower()
    if ext not in ARTICLE_EXTS:
        raise ArticleError("Upload a PNG, JPEG or WebP screenshot.")
    if not raw or len(raw) < 32:
        raise ArticleError("That file is empty.")
    if len(raw) > MAX_BYTES:
        raise ArticleError("That image is over 20 MB. Export a smaller screenshot.")
    try:
        from PIL import Image
        image = Image.open(io.BytesIO(raw))
        image.load()
        width, height = image.size
    except ArticleError:
        raise
    except Exception:
        raise ArticleError("That file is not a PNG, JPEG or WebP image.")
    if width < 16 or height < 16:
        raise ArticleError("That image is too small to read.")
    return ext, width, height


def _store(project, raw: bytes, ext: str) -> tuple:
    folder = project.dir / "articles"
    folder.mkdir(parents=True, exist_ok=True)
    aid = uuid.uuid4().hex[:8]
    name = aid + ext
    (folder / name).write_bytes(raw)
    return aid, name


def _record(project, *, aid: str, name: str, label: str, source: str, url: str, width: int, height: int) -> dict:
    ocr = ocr_image(project.dir / "articles" / name)
    spoken = ""
    try:
        spoken = project.read("spoken.txt") or project.read("script.txt")
    except Exception:
        spoken = ""
    chosen = suggest_lines(ocr["lines"], spoken)
    item = {
        "id": aid, "file": name, "name": (label or name)[:120], "source": source, "url": (url or "")[:500],
        "width": width, "height": height, "ocr": ocr["engine"], "ocr_error": ocr["error"],
        "lines": ocr["lines"], "chosen": chosen, "slide": "", "touched": False,
    }
    items = _items(project)
    items.append(item)
    _save_items(project, items)
    return item


def add_upload(project, raw: bytes, filename: str, source: str = "upload") -> dict:
    ext, width, height = _read_image(raw, filename)
    if source not in ("upload", "clipboard", "url"):
        source = "upload"
    aid, name = _store(project, raw, ext)
    return _record(project, aid=aid, name=name, label=Path(filename or name).name, source=source,
                   url="", width=width, height=height)


def add_captured(project, url: str) -> dict:
    problem = url_problem(url)
    if problem:
        raise ArticleError(problem)
    dest_name = uuid.uuid4().hex[:8] + ".png"
    dest = project.dir / "articles" / dest_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shot = capture_url(url.strip(), dest)
    if not shot.get("ok"):
        dest.unlink(missing_ok=True)
        raise ArticleError(shot.get("error") or "Could not capture that page. Upload a screenshot instead.")
    raw = dest.read_bytes()
    try:
        _ext, width, height = _read_image(raw, dest.name)
    except ArticleError:
        dest.unlink(missing_ok=True)
        raise
    return _record(project, aid=dest_name[:-4], name=dest_name, label=url.strip()[:120], source="url",
                   url=url.strip(), width=width, height=height)


def _find(project, aid: str) -> tuple:
    items = _items(project)
    for i, item in enumerate(items):
        if item.get("id") == aid:
            return items, i
    raise ArticleError("That article is no longer in this project.")


def set_chosen(project, aid: str, chosen: list) -> dict:
    items, index = _find(project, aid)
    known = {ln.get("id") for ln in items[index].get("lines") or []}
    items[index]["chosen"] = [c for c in chosen if c in known]
    items[index]["touched"] = True
    _save_items(project, items)
    return items[index]


def assign_article(project, aid: str, slide: str, slides: Optional[list] = None) -> dict:
    items, index = _find(project, aid)
    slide = (slide or "").strip()
    if slide and slides is not None and slide not in {s.get("id") for s in slides}:
        raise ArticleError("That slide is not in this version.")
    for item in items:
        if item.get("slide") == slide and slide and item.get("id") != aid:
            item["slide"] = ""
    items[index]["slide"] = slide
    if slide and not items[index].get("touched"):
        spoken = ""
        for s in slides or []:
            if s.get("id") == slide:
                spoken = s.get("spoken") or ""
                break
        items[index]["chosen"] = suggest_lines(items[index].get("lines") or [], spoken)
    _save_items(project, items)
    return items[index]


def remove_article(project, aid: str) -> None:
    items, index = _find(project, aid)
    file_name = items[index].get("file") or ""
    del items[index]
    _save_items(project, items)
    if file_name:
        (project.dir / "articles" / Path(file_name).name).unlink(missing_ok=True)


def reocr(project, aid: str) -> dict:
    items, index = _find(project, aid)
    path = project.dir / "articles" / Path(items[index].get("file") or "").name
    if not path.is_file():
        raise ArticleError("The image file is missing.")
    ocr = ocr_image(path)
    items[index]["lines"] = ocr["lines"]
    items[index]["ocr"] = ocr["engine"]
    items[index]["ocr_error"] = ocr["error"]
    items[index]["touched"] = False
    spoken = ""
    try:
        spoken = project.read("spoken.txt") or ""
    except Exception:
        spoken = ""
    items[index]["chosen"] = suggest_lines(ocr["lines"], spoken)
    _save_items(project, items)
    return items[index]


def _words(project) -> list:
    import json
    try:
        return json.loads(project.read("words.json") or "[]")
    except Exception:
        return []


def _script(project) -> str:
    try:
        return project.read("script.txt") or ""
    except Exception:
        return ""


def public_articles(project, slides: Optional[list] = None) -> list:
    out = []
    by_id = {s.get("id"): s for s in slides or []}
    for item in _items(project):
        slide = item.get("slide") or ""
        narration = (by_id.get(slide) or {}).get("spoken") or ""
        if not narration:
            try:
                narration = project.read("spoken.txt") or ""
            except Exception:
                narration = ""
        out.append({
            "id": item.get("id"), "name": item.get("name") or "", "file": f"articles/{item.get('file')}",
            "source": item.get("source") or "upload", "url": item.get("url") or "",
            "width": item.get("width") or 0, "height": item.get("height") or 0,
            "ocr": item.get("ocr") or "", "ocr_error": item.get("ocr_error") or "",
            "lines": item.get("lines") or [], "chosen": item.get("chosen") or [],
            "suggested": suggest_lines(item.get("lines") or [], narration),
            "slide": slide,
        })
    return out


def _data_uri(path: Path) -> str:
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.lower(), "image/png")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def article_runtime(project, slides: list) -> list:
    """What the page draws. The image is embedded so the renderer's file page can show it."""
    by_id = {s.get("id"): s for s in slides or []}
    words = _words(project)
    out = []
    for item in _items(project):
        slide = by_id.get(item.get("slide") or "")
        path = project.dir / "articles" / Path(item.get("file") or "").name
        if not slide or not path.is_file():
            continue
        cues = line_cues(item.get("lines") or [], item.get("chosen") or [], words,
                         float(slide.get("t0") or 0), float(slide.get("t1") or 0))
        out.append({
            "id": item.get("id"), "slide": slide.get("id"), "src": _data_uri(path),
            "w": int(item.get("width") or 0), "h": int(item.get("height") or 0),
            "t0": float(slide.get("t0") or 0), "t1": float(slide.get("t1") or 0),
            "lines": cues, "accent": ACCENT,
        })
    return out


def public_emphasis(project, slides: list, html: str = "") -> dict:
    prefs = emphasis_prefs(project.data)
    wav = project.dir / "narration.wav"
    marks = collect_marks(_script(project), slides, _words(project), wav if wav.is_file() else None, prefs, html)
    return {"enabled": prefs["enabled"], "slides": prefs["slides"], "marks": marks}


def emphasis_runtime(project, slides: list, html: str = "") -> dict:
    prefs = emphasis_prefs(project.data)
    wav = project.dir / "narration.wav"
    marks = collect_marks(_script(project), slides, _words(project), wav if wav.is_file() else None, prefs, html)
    return {"marks": drawable_marks(marks, slides), "accent": ACCENT}


def page_layers(project, compiled: dict) -> tuple:
    slides = compiled.get("slides") or []
    html = compiled.get("html") or ""
    return article_runtime(project, slides), emphasis_runtime(project, slides, html)


def _mutate_prefs(project, fn) -> dict:
    with project.lock:
        prefs = emphasis_prefs(project.data)
        fn(prefs)
        project.data["emphasis"] = prefs
        project.save()
        return prefs


def set_emphasis_global(project, enabled: bool) -> dict:
    return _mutate_prefs(project, lambda prefs: prefs.__setitem__("enabled", bool(enabled)))


def set_emphasis_slide(project, slide: str, enabled: bool) -> dict:
    slide = (slide or "").strip()
    if not slide:
        raise ArticleError("Pick a slide.")

    def apply(prefs, _slide=slide, _enabled=bool(enabled)):
        prefs["slides"][_slide] = _enabled

    return _mutate_prefs(project, apply)


def remove_emphasis(project, slide: str, phrase: str) -> dict:
    slide, phrase = (slide or "").strip(), _clean_phrase(phrase)
    if not slide or not phrase:
        raise ArticleError("Pick the emphasis to remove.")

    def apply(prefs, _slide=slide, _phrase=phrase):
        key = (_slide, norm_phrase(_phrase))
        prefs["removed"] = [x for x in prefs["removed"]
                            if (str(x.get("slide") or ""), norm_phrase(x.get("phrase") or "")) != key]
        prefs["removed"].append({"slide": _slide, "phrase": _phrase[:80]})
        prefs["added"] = [x for x in prefs["added"]
                          if not (str(x.get("slide") or "") == _slide and norm_phrase(x.get("phrase") or "") == key[1])]

    return _mutate_prefs(project, apply)


def add_emphasis(project, slide: str, phrase: str, known: Optional[set] = None) -> dict:
    slide, phrase = (slide or "").strip(), _clean_phrase(phrase)
    if not slide or not tokens(phrase):
        raise ArticleError("Type the word or phrase and pick its slide.")
    if known is not None and slide not in known:
        raise ArticleError("That slide is not in this version.")

    def apply(prefs, _slide=slide, _phrase=phrase[:80]):
        key = (_slide, norm_phrase(_phrase))
        prefs["removed"] = [x for x in prefs["removed"]
                            if (str(x.get("slide") or ""), norm_phrase(x.get("phrase") or "")) != key]
        if not any(str(x.get("slide") or "") == _slide and norm_phrase(x.get("phrase") or "") == key[1]
                   for x in prefs["added"]):
            prefs["added"].append({"slide": _slide, "phrase": _phrase})

    return _mutate_prefs(project, apply)
