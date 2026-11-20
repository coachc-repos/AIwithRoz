"""Literal Grok Imagine stills for the spoken paragraph beside each prompt.

The picture has to be recognizable as that paragraph: a named public figure is
an illustrative portrait, a party is its established emblem, a market
definition is a simple chart. Unrelated stand-ins (ropes, jars, marbles,
measuring tapes) are replaced. The image is not documentary footage and does
not prove a quote or an event.

This module is deterministic. It does not call a model. The writer and the
inject stage both run their model output through it, so a symbolic reply
cannot be what gets saved.
"""
from __future__ import annotations

import re

from linedrive_azure.agents.pro_script_writer import GROK_IMAGINE_STYLE_TAG

# Retired house-style ending. It banned faces, so the model invented objects.
OLD_STYLE_SUFFIX = (
    "Landscape 16:9, dark navy background, cinematic soft lighting, clean "
    "modern editorial illustration, minimal or no text, no people, no faces, "
    "no hands."
)

ILLUSTRATIVE_CLAUSE = (
    "Illustrative editorial image only, not documentary footage, not a photograph "
    "of a real event, and not proof of any quote or factual claim."
)

DEFINITION_SHOT = (
    "One simple market chart filling the frame: a single price line that has "
    "moved down, with two horizontal threshold lines and nothing else in the picture"
)

DEFINITION_OVERLAY = (
    '[ON SCREEN / RESOLVE] Editor overlays on the two threshold lines, added in '
    'the edit and not treated as a live market print: "10%" for a correction and '
    '"20%" for a bear market.'
)

_ALLEGORY = re.compile(
    r"\bmeasuring tape\b|\bmarbles?\b|\bjars?\b|\bropes?\b|\bthreads?\b|"
    r"\bthermometers?\b|\bbalance scale\b|\bdominoes?\b|\bdrawbridge\b|\bmoat\b|"
    r"\bweather vane\b|\bdoorways?\b|\bwooden doors?\b|\bglowing doors?\b|"
    r"\bpies? of light\b|\bglowing pie\b|\bcompass\b|\bpadlocks?\b|"
    r"\bcolored liquid\b|\biron chain\b|\bamber flags?\b|\bred flags?\b|"
    r"\bstone bridge\b",
    re.IGNORECASE,
)
_JOURNEY = re.compile(
    r"doorway|spiral staircase|winds across|passes through an open|"
    r"camera follows|from the \w+ .{0,40} to the ",
    re.IGNORECASE,
)
_PRODUCTION_RE = re.compile(
    r"\[PRODUCTION\s+BEGIN\].*?\[PRODUCTION\s+END\]",
    re.IGNORECASE | re.DOTALL,
)
_GI_LINE_RE = re.compile(
    r"(?im)^([ \t]*\[GROK IMAGINE[^\]]*\][ \t]*)(.*)$"
)
_BOUNDARY_RE = re.compile(
    r"^(?:_{5,}|={3,}|#{1,6}\s*)?(?:heading\s*:|chapter\s+\d+\b)",
    re.IGNORECASE,
)
_LABEL_RE = re.compile(
    r"^(?:title|script-?id|script-?version|script\s+type|duration|generated|"
    r"audience|tone|heading|final\s+hook|hook|host|summary|chapter\s+\d+)\b",
    re.IGNORECASE,
)

# Place frames: (id, trigger phrases, sentence when this place is the whole
# shot, short noun phrase when it shares the frame with a party emblem).
_PLACES = (
    (
        "data_center",
        ("data center", "power bill", "electricity", "the grid", "power grid",
         "batteries", "battery", "transformer"),
        "One feasible exterior shot of a data-center building with electrical "
        "transformers, grid-scale battery containers, and power lines, with "
        "nearby houses in the same frame. No readable signs",
        "a data-center building, grid-scale batteries, and power lines",
    ),
    (
        "hearing",
        ("hearing", "hearings", "investigation", "testify", "testifying", "gavel"),
        "One feasible shot of a legislative hearing room with a long table, "
        "microphones, and closed folders, and a wall screen showing server racks. "
        "No readable nameplates and no invented testimony",
        "a legislative hearing room, microphones, and closed folders",
    ),
    (
        "election",
        ("midterm", "ballot", "governor", "election"),
        "One feasible shot of an election desk with a ballot box and a blank "
        "results screen. No vote totals and no invented winner",
        "a ballot box and a blank election-results screen",
    ),
    (
        "chips",
        ("semiconductor", "nvidia", "qualcomm", "chip stock", "chipmaker",
         "graphics chip"),
        None,  # built from the beat so only named companies get logos
        "graphics-processor chips on a workbench",
    ),
    (
        "trading",
        ("nasdaq", "s and p", "s&p", "stock", "stocks", "sell-off", "sell off",
         "ticker", "dow", "russell"),
        "One shot of a simple market chart on a screen, the price line moving "
        "in the direction this paragraph describes. No readable tickers and no "
        "invented prices",
        "a simple market chart on a screen",
    ),
    (
        "retirement",
        ("four oh one", "401", "retirement", "fact sheet", "holdings",
         "target-date", "target date", "ira"),
        "One shot of a home desk with an open laptop and a printed fund fact "
        "sheet. The screen is a generic holdings list with no readable account "
        "numbers, names, or dollar amounts",
        "a home desk, a laptop, and a fund fact sheet",
    ),
    (
        "analysts",
        ("do not agree", "strategist", "reuters", "analysts"),
        "One shot of a news desk with two printed market notes side by side and "
        "a monitor showing an unlabeled chart. No readable quotes and no invented "
        "names",
        "two printed market notes and an unlabeled chart",
    ),
    (
        "open_questions",
        ("open question", "has not happened yet", "three open"),
        "An editor-created set of three blank cards on a desk, with no words on "
        "them. Not three symbolic doors",
        "three blank cards on a desk",
    ),
    (
        "ai_labs",
        ("frontier lab", "openai", "anthropic", "deepmind", "xai"),
        None,
        "a modern office beside a glass-walled server room",
    ),
    (
        "forced_selling",
        ("hedge fund", "borrowed", "lenders", "forced to sell", "margin"),
        "One shot of a trading desk with monitors showing generic falling charts "
        "and a phone. No readable firm names or prices",
        "a trading desk with falling charts",
    ),
    (
        "bitcoin",
        ("bitcoin",),
        "One shot of a laptop showing a generic bitcoin price chart moving in "
        "the direction this paragraph describes, with the bitcoin mark and no "
        "readable price",
        "a laptop showing a bitcoin price chart",
    ),
    (
        "community",
        ("county meeting", "county meetings", "community benefit", "state capital",
         "town hall", "local jobs"),
        "One feasible shot inside a county meeting room: a long table, chairs, "
        "microphones, and a paper agenda with no readable text, and a wall "
        "screen showing a data center",
        "a county meeting room with microphones and a paper agenda",
    ),
    (
        "not_law_yet",
        ("not sworn", "no new law", "not one new law"),
        "One shot of an empty legislative chamber with a closed ledger on the "
        "desk. No readable text",
        "an empty legislative chamber and a closed ledger",
    ),
)


def grok_imagine_beat_instruction(beat: str) -> str:
    """User-message line for the still-image model. One paragraph, literal."""
    return (
        "SCRIPT BEAT (one literal shot of THIS paragraph only: the real subject, "
        "action, and place. If it names Elon Musk, show an illustrative portrait "
        "of Elon Musk. If it is about Democrats, show the Democratic donkey. If "
        "it defines a correction and a bear market, show one simple price chart "
        "and leave 10% and 20% for an editor overlay. Do not depict a later topic "
        "this paragraph only previews. Do not use ropes, jars, marbles, threads, "
        "thermometers, measuring tapes, or other unrelated allegories. Add a "
        "quote card only if it cites a quotable source): "
        f"\"{beat}\""
    )


GROK_IMAGINE_SYSTEM = (
    "You are the art director for a YouTube channel about AI and technology. For "
    "ONE beat of the spoken script, produce production overlays as a JSON object "
    'with exactly two keys: "image_prompt" and "quote_card".\n'
    "\n"
    "IMAGE PROMPT — one still image for Grok Imagine. The viewer must recognize "
    "the spoken paragraph from the picture. Depict that paragraph's literal "
    "subject, action, and place. One feasible shot, one coherent scene.\n"
    "- A named public figure is an illustrative photo-style portrait of that "
    "person. Elon Musk, when this paragraph is about him, looks like Elon Musk. "
    "The portrait is not a photograph of a real event and does not show him "
    "saying a quote.\n"
    "- A political party is its established emblem. Democrats: the Democratic "
    "Party donkey. Republicans: the Republican Party elephant. Use the emblem "
    "for the party this paragraph is about, not as a substitute for a different "
    "topic.\n"
    "- A company this paragraph is about may be shown with that company's logo.\n"
    "- A correction and a bear market are one simple price chart: a line that "
    "has moved, plus two horizontal threshold lines. Do not draw the 10% or 20% "
    "labels into the picture. Do not use a measuring tape, flags, or a marble. "
    "Do not also put later topics (a person, a party, a building) into that "
    "chart just because the paragraph previews them.\n"
    "- Do not cram every proper noun into the frame. A route sentence that only "
    "lists what is coming later is not this shot.\n"
    "- Do not use unrelated allegories: ropes, jars, marbles, glowing threads, "
    "thermometers, scales, icon doors, bridges, dominos, or moats.\n"
    "- The image is illustrative. It is not documentary footage and it does not "
    "prove a number, a quote, or an event.\n"
    "- Roughly 40-80 words. Do NOT add camera, aspect-ratio, lighting, or style "
    "notes, and do NOT write \"no people\", \"no faces\", or \"no hands\".\n"
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


def _is_definition_beat(beat: str) -> bool:
    """The paragraph is defining a correction and a bear market, not previewing
    the rest of the episode."""
    b = (beat or "").lower()
    has_correction = "correction" in b
    has_bear = "bear market" in b
    has_ten = ("ten percent" in b) or ("10 percent" in b) or ("10%" in b)
    has_twenty = ("twenty percent" in b) or ("20 percent" in b) or ("20%" in b)
    return bool(has_correction and has_bear and has_ten and has_twenty)


def _is_route_preview(beat: str) -> bool:
    return bool(re.search(r"here is our route|here is the route", beat or "", re.I))


def _focused_figure(beat: str):
    """A public figure who is the subject of this paragraph, not a name in a
    preview list and not a passing mention."""
    if _is_definition_beat(beat) or _is_route_preview(beat):
        return None
    b = (beat or "").lower()
    if re.search(r"\bmusk\b", b) and re.search(
            r"biggest target|one man|line of fire|attacking him|his ai company",
            b):
        return "Elon Musk"
    head = " ".join(b.split()[:30])
    if re.search(r"\belon musk\b", head) and "what can musk" not in head:
        return "Elon Musk"
    return None


def _party_emblem(beat: str):
    if _is_definition_beat(beat) or _is_route_preview(beat):
        return None
    b = (beat or "").lower()
    if re.search(r"\bdemocrats?\b|\bdemocratic\b", b):
        return "Democratic Party donkey"
    if re.search(r"\brepublicans?\b|\bgop\b", b):
        return "Republican Party elephant"
    return None


def _trigger_score(beat_l: str, triggers) -> tuple:
    n = 0
    first = 10 ** 9
    for phrase in triggers:
        i = beat_l.find(phrase)
        if i >= 0:
            n += 1
            if i < first:
                first = i
    return n, first


def _labs_sentence(beat: str) -> str:
    names = []
    low = beat.lower()
    for label, needle in (
            ("OpenAI", "openai"),
            ("Anthropic", "anthropic"),
            ("Google", "google"),
            ("DeepMind", "deepmind"),
            ("xAI", "xai"),
    ):
        if needle in low and label not in names:
            names.append(label)
    logo = ""
    if names:
        logo = " Logos for " + ", ".join(names) + " may appear on the glass."
    return (
        "One shot of a modern office beside a glass-walled server room."
        + logo + " No invented headlines"
    )


def _chips_sentence(beat: str) -> str:
    low = beat.lower()
    extra = ""
    if "nvidia" in low:
        extra += " The Nvidia logo is on the main chip."
    if "qualcomm" in low:
        extra += " A second chip carries the Qualcomm logo."
    return (
        "One feasible shot of graphics-processor chips on a workbench."
        + extra
        + " Through one window, a data-center construction site with idle cranes. "
        "No percentages written in the picture"
    )


def _place_sentence(place_id: str, beat: str, alone: str) -> str:
    if place_id == "ai_labs":
        return _labs_sentence(beat)
    if place_id == "chips":
        return _chips_sentence(beat)
    return alone


def _best_place(beat: str):
    """Return (id, alone_sentence, short_phrase, score) or None."""
    low = (beat or "").lower()
    best = None
    for pid, triggers, alone, short in _PLACES:
        n, first = _trigger_score(low, triggers)
        if n <= 0:
            continue
        # Higher count wins. A tie goes to whichever subject is mentioned first.
        rank = (n, -first)
        if best is None or rank > best[0]:
            best = (rank, pid, _place_sentence(pid, beat, alone), short, n)
    if not best:
        return None
    return best[1], best[2], best[3], best[4]


def _kitchen_chart(beat: str):
    """401(k) plus a market move share one table. Not a journey between them."""
    low = (beat or "").lower()
    r = t = 0
    for pid, triggers, _alone, _short in _PLACES:
        n, _first = _trigger_score(low, triggers)
        if pid == "retirement":
            r = n
        elif pid == "trading":
            t = n
    if r >= 1 and t >= 1 and min(r, t) * 3 >= max(r, t):
        return (
            "One shot at a single kitchen table: a closed retirement-account "
            "envelope beside a laptop showing a generic stock chart moving down. "
            "No readable numbers or account details, and no path from an exchange "
            "floor into the room"
        )
    return None


def scene_for_beat(beat: str) -> tuple:
    """Return (image sentence without the house-style tag, on-screen line or None).

    The on-screen line is only the correction / bear-market threshold labels.
    """
    beat = (beat or "").strip()
    if _is_definition_beat(beat):
        return DEFINITION_SHOT, DEFINITION_OVERLAY
    figure = _focused_figure(beat)
    party = _party_emblem(beat)
    if figure and party:
        return (
            f"One coherent shot: an illustrative photo-style portrait of {figure} "
            f"beside the {party} emblem"
        ), None
    if figure:
        return (
            f"An illustrative photo-style portrait of {figure}"
        ), None
    kitchen = _kitchen_chart(beat)
    place = _best_place(beat)
    if kitchen and (place is None or place[0] in ("retirement", "trading")):
        return kitchen, None
    if party and place:
        return (
            f"One coherent shot: the {party} emblem with {place[2]}"
        ), None
    if party:
        return (
            f"The {party} emblem, shown clearly as the established party symbol "
            f"for this paragraph"
        ), None
    if place:
        return place[1], None
    return (
        "An editor-created overlay of blank unlabeled marks for this paragraph, "
        "with no words and no symbolic stand-in objects. The editor adds any "
        "confirmed words later"
    ), None


def _strip(text: str) -> str:
    t = " ".join((text or "").split())
    for suf in (GROK_IMAGINE_STYLE_TAG, OLD_STYLE_SUFFIX):
        if t.endswith(suf):
            t = t[: -len(suf)].strip()
    t = re.sub(r"\bno people, no faces, no hands\.?", "", t, flags=re.I)
    t = t.replace(ILLUSTRATIVE_CLAUSE, "")
    t = re.sub(r"\s{2,}", " ", t).strip(" .")
    return t


def _finish(scene: str) -> str:
    scene = _strip(scene)
    if not scene.endswith("."):
        scene += "."
    return scene + " " + ILLUSTRATIVE_CLAUSE + " " + GROK_IMAGINE_STYLE_TAG


def _required_tokens(selected: str, beat: str) -> list:
    sel = selected.lower()
    req = []
    if _is_definition_beat(beat):
        req.append("chart")
    if "elon musk" in sel:
        req.append("musk")
    if "donkey" in sel:
        req.append("donkey")
    if "elephant" in sel:
        req.append("elephant")
    if "data-center" in sel or "data center" in sel:
        req.append("data")
    if "battery" in sel:
        req.append("battery")
    if "hearing" in sel:
        req.append("hearing")
    if "ballot" in sel:
        req.append("ballot")
    if "envelope" in sel:
        req.append("envelope")
    if "server room" in sel or "server racks" in sel:
        req.append("server")
    if "county meeting" in sel:
        req.append("meeting")
    if "trading desk" in sel:
        req.append("trading")
    return req


def _model_scene_ok(scene: str, beat: str) -> bool:
    if not scene or not beat:
        return False
    if _ALLEGORY.search(scene) or _JOURNEY.search(scene):
        return False
    if re.search(r"\$\s?\d|\b\d{3,}\b", scene):
        return False
    low = scene.lower()
    if _is_definition_beat(beat) and re.search(r"\bmusk\b|donkey|democrat", low):
        return False
    selected, _overlay = scene_for_beat(beat)
    for token in _required_tokens(selected, beat):
        if token not in low:
            return False
    return True


def ensure_literal_image_prompt(model_prompt: str, beat: str) -> str:
    """A paste-ready Grok Imagine line body for this spoken beat.

    Keeps a model prompt that already shows the literal subject. Replaces
    symbolic or misaligned ones. Always ends with the 16:9 house tag and never
    with a ban on people.
    """
    beat = (beat or "").strip()
    if not beat:
        return ""
    raw = _strip(model_prompt or "")
    if raw and _model_scene_ok(raw, beat):
        scene = raw
    else:
        scene, _overlay = scene_for_beat(beat)
    return _finish(scene)


def _chunks(text: str, stop_on_boundary: bool) -> list:
    chunks = []
    buf = []

    def flush():
        if buf:
            chunks.append(" ".join(buf))
            buf.clear()

    for line in (text or "").splitlines():
        raw = line.strip()
        if stop_on_boundary and raw and (
                _BOUNDARY_RE.match(raw) or raw.startswith("___") or raw.startswith("===")):
            break
        if not raw or raw.startswith("[") or raw.startswith("___") or raw.startswith("==="):
            flush()
            continue
        if _LABEL_RE.match(raw):
            flush()
            continue
        raw = re.sub(r"^Host:\s*", "", raw, flags=re.I)
        if raw:
            buf.append(raw)
    flush()
    return [c for c in chunks if len(c.split()) >= 8]


def _last_spoken_before(text: str) -> str:
    lines = (text or "").splitlines()
    start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if _BOUNDARY_RE.match(stripped) or re.match(r"^heading\s*:", stripped, re.I):
            start = i + 1
    found = _chunks("\n".join(lines[start:]), stop_on_boundary=False)
    return found[-1] if found else ""


def beat_for_production_span(script: str, start: int, end: int) -> str:
    """Spoken paragraph this production block illustrates.

    Chapter blocks sit in front of their paragraph. The hook block sits after
    the hook, so when nothing spoken follows, the previous paragraph is used.
    """
    nxt = _chunks(script[end:], stop_on_boundary=True)
    if nxt:
        return nxt[0]
    return _last_spoken_before(script[:start])


def _overlay_present(block: str) -> bool:
    return bool(re.search(r"\[ON SCREEN[^\]]*\][^\n]*10%", block, re.I))


def rewrite_production_image_prompts(script: str) -> str:
    """Rewrite each [GROK IMAGINE / RESOLVE] line in place.

    Spoken text, VERIFY notes, cold opens, and quote cards stay where they are.
    A definition beat also gains one [ON SCREEN / RESOLVE] line for the 10% and
    20% labels when that line is not already there.
    """
    if not script:
        return script

    def _one(match: re.Match) -> str:
        block = match.group(0)
        gi = _GI_LINE_RE.search(block)
        if not gi:
            return block
        beat = beat_for_production_span(script, match.start(), match.end())
        scene, overlay = scene_for_beat(beat)
        raw = _strip(gi.group(2))
        if raw and _model_scene_ok(raw, beat):
            scene = raw
            if not _is_definition_beat(beat):
                overlay = None
        finished = _finish(scene)
        block = block[:gi.start()] + gi.group(1) + finished + block[gi.end():]
        if overlay and not _overlay_present(block):
            block = re.sub(
                r"\[PRODUCTION\s+END\]",
                overlay + "\n[PRODUCTION END]",
                block,
                count=1,
                flags=re.I,
            )
        return block

    return _PRODUCTION_RE.sub(_one, script)
