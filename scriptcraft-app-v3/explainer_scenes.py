"""Scene objects for the explainer. Original artwork, no third-party assets.

A scene places one with:

    <svg class="sc" data-sc="house" data-depth="1" x="200" y="640"
         width="220" height="170" viewBox="0 0 220 170">
      <use href="#sc-house"/>
    </svg>

classic is the old flat silhouette (a box, a triangle, two circles).
cinematic is the same object with volume: a lit face and a darker side,
light from the upper left, a contact shadow, glass, and the moving parts
the runtime drives (wheels, window glow, smoke). Gradients stay inside
these symbols. They are not the page background.

Names: house, building, datacenter, car, tree, factory, server, phone,
chart, powerline.
"""
from __future__ import annotations

SCENE_OBJECTS = (
    "house", "building", "datacenter", "car", "tree",
    "factory", "server", "phone", "chart", "powerline",
)
# viewBox of each symbol. place() uses the same box so a clone lines up.
SCENE_BOX = {
    "house": (220, 170),
    "building": (190, 240),
    "datacenter": (340, 180),
    "car": (240, 120),
    "tree": (140, 170),
    "factory": (220, 170),
    "server": (80, 160),
    "phone": (90, 170),
    "chart": (200, 130),
    "powerline": (220, 110),
}

_DEFS = """
<defs>
  <linearGradient id="scg-wall" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#8d6b48"/><stop offset="1" stop-color="#4e3826"/>
  </linearGradient>
  <linearGradient id="scg-roof" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#6a4632"/><stop offset="1" stop-color="#3a2418"/>
  </linearGradient>
  <linearGradient id="scg-front" x1="0" y1="0" x2="1" y2="0.4">
    <stop offset="0" stop-color="#3c4e6a"/><stop offset="1" stop-color="#1c2638"/>
  </linearGradient>
  <linearGradient id="scg-glass" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#d7ecff"/><stop offset="0.45" stop-color="#6aa4d4"/><stop offset="1" stop-color="#24384c"/>
  </linearGradient>
  <linearGradient id="scg-body" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#3a4558"/><stop offset="1" stop-color="#141820"/>
  </linearGradient>
  <linearGradient id="scg-leaf" x1="0" y1="0" x2="0.2" y2="1">
    <stop offset="0" stop-color="#3e7a48"/><stop offset="1" stop-color="#16301c"/>
  </linearGradient>
  <filter id="scg-soft" x="-20%" y="-20%" width="140%" height="140%">
    <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" result="n"/>
    <feColorMatrix in="n" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.18 0"/>
  </filter>
</defs>
"""


def _classic() -> dict:
    return {
        "house": """<polygon points="18,78 100,34 182,78" fill="#8a5a32"/>
            <rect x="36" y="76" width="128" height="68" fill="#6b4630"/>
            <rect x="56" y="92" width="24" height="18" fill="#f5b83d"/>
            <rect x="120" y="92" width="24" height="18" fill="#1a2232"/>
            <rect x="88" y="108" width="26" height="36" fill="#241810"/>""",
        "building": """<rect x="28" y="36" width="124" height="176" fill="#2a3448"/>
            <rect x="44" y="52" width="18" height="14" fill="#f5b83d"/>
            <rect x="74" y="52" width="18" height="14" fill="#1a2232"/>
            <rect x="104" y="52" width="18" height="14" fill="#8fb4d8"/>
            <rect x="44" y="80" width="18" height="14" fill="#1a2232"/>
            <rect x="74" y="80" width="18" height="14" fill="#f5b83d"/>
            <rect x="104" y="80" width="18" height="14" fill="#1a2232"/>
            <rect x="44" y="108" width="18" height="14" fill="#8fb4d8"/>
            <rect x="74" y="108" width="18" height="14" fill="#1a2232"/>
            <rect x="104" y="108" width="18" height="14" fill="#f5b83d"/>""",
        "datacenter": """<rect x="24" y="48" width="272" height="100" fill="#243044"/>
            <rect x="40" y="64" width="16" height="12" fill="#f5b83d"/>
            <rect x="70" y="64" width="16" height="12" fill="#8fb4d8"/>
            <rect x="100" y="64" width="16" height="12" fill="#1a2232"/>
            <rect x="130" y="64" width="16" height="12" fill="#f5b83d"/>
            <rect x="48" y="118" width="36" height="28" fill="#2a4038"/>
            <rect x="96" y="118" width="36" height="28" fill="#2a4038"/>""",
        "car": """<rect x="28" y="48" width="180" height="36" rx="8" fill="#2a3446"/>
            <polygon points="70,48 96,24 168,24 188,48" fill="#3a465c"/>
            <circle cx="78" cy="86" r="16" fill="#121418"/>
            <circle cx="176" cy="86" r="16" fill="#121418"/>""",
        "tree": """<rect x="52" y="78" width="16" height="58" fill="#6b4630"/>
            <circle cx="60" cy="62" r="36" fill="#2f6a3c"/>""",
        "factory": """<rect x="20" y="70" width="150" height="74" fill="#3a342e"/>
            <polygon points="150,70 190,40 190,144 150,144" fill="#2a2622"/>
            <rect x="168" y="18" width="16" height="56" fill="#4a4038"/>
            <rect x="40" y="88" width="18" height="14" fill="#f5b83d"/>
            <rect x="70" y="88" width="18" height="14" fill="#1a2232"/>""",
        "server": """<rect x="18" y="16" width="44" height="120" fill="#1c2432"/>
            <rect x="26" y="28" width="28" height="8" fill="#3cc878"/>
            <rect x="26" y="44" width="28" height="8" fill="#f5b83d"/>
            <rect x="26" y="60" width="28" height="8" fill="#4c8dff"/>""",
        "phone": """<rect x="22" y="12" width="46" height="136" rx="8" fill="#1c2432"/>
            <rect x="28" y="24" width="34" height="100" fill="#121820"/>""",
        "chart": """<rect x="16" y="20" width="148" height="90" fill="#1c2432"/>
            <polyline points="32,86 58,70 80,76 108,48 140,58" fill="none" stroke="#f5b83d" stroke-width="4"/>""",
        "powerline": """<line x1="10" y1="70" x2="190" y2="24" stroke="#8a94a6" stroke-width="2"/>
            <rect x="86" y="40" width="10" height="70" fill="#2a3446"/>""",
    }


def _cinematic() -> dict:
    return {
        "house": """
            <ellipse cx="110" cy="156" rx="92" ry="9" fill="#000" opacity="0.38"/>
            <polygon points="148,74 196,96 196,146 148,138" fill="#3a2a1e"/>
            <polygon points="196,96 206,92 206,142 196,146" fill="#2a1e16"/>
            <rect x="30" y="78" width="124" height="66" fill="url(#scg-wall)"/>
            <rect x="30" y="78" width="10" height="66" fill="#c4a078" opacity="0.55"/>
            <polygon points="16,82 108,30 118,36 36,88" fill="url(#scg-roof)"/>
            <polygon points="108,30 200,86 176,98 118,42" fill="#3a2418"/>
            <rect x="150" y="34" width="16" height="32" fill="#5a4030"/>
            <rect x="156" y="34" width="10" height="32" fill="#3a281c"/>
            <rect x="146" y="28" width="24" height="8" fill="#6a5040"/>
            <polygon points="46,128 150,128 158,140 38,140" fill="#5c4634"/>
            <rect x="52" y="112" width="6" height="28" fill="#2c2118"/>
            <rect x="138" y="112" width="6" height="28" fill="#1a140e"/>
            <rect x="78" y="100" width="28" height="44" fill="#2a1c14"/>
            <rect x="82" y="104" width="9" height="16" fill="#4a3424"/>
            <rect x="93" y="104" width="9" height="16" fill="#3a281c"/>
            <circle cx="102" cy="122" r="1.6" fill="#e8d2a0"/>
            <rect x="48" y="90" width="26" height="20" fill="#1a140e"/>
            <rect class="sc-glow" x="51" y="93" width="20" height="14" fill="#ffc56a"/>
            <rect x="60" y="93" width="2" height="14" fill="#1a140e"/>
            <rect x="51" y="99" width="20" height="2" fill="#1a140e"/>
            <rect x="51" y="93" width="8" height="4" fill="#fff" opacity="0.45"/>
            <rect x="112" y="90" width="26" height="20" fill="#1a140e"/>
            <rect class="sc-glow" x="115" y="93" width="20" height="14" fill="#9ec8ee"/>
            <rect x="124" y="93" width="2" height="14" fill="#1a140e"/>
            <rect x="115" y="93" width="7" height="3" fill="#fff" opacity="0.4"/>
            <rect x="34" y="78" width="116" height="3" fill="#e6d2b0" opacity="0.35"/>""",
        "building": """
            <ellipse cx="96" cy="228" rx="78" ry="8" fill="#000" opacity="0.4"/>
            <polygon points="132,40 168,58 168,214 132,206" fill="#141a26"/>
            <polygon points="168,58 178,54 178,210 168,214" fill="#0c1018"/>
            <rect x="22" y="34" width="114" height="180" fill="url(#scg-front)"/>
            <rect x="22" y="34" width="7" height="180" fill="#8ea6c8" opacity="0.35"/>
            <rect x="22" y="30" width="150" height="10" fill="#5c7090"/>
            <rect x="22" y="30" width="150" height="3" fill="#d5e2f2"/>
            <rect x="36" y="18" width="28" height="14" fill="#1a2230"/>
            <rect x="40" y="10" width="8" height="10" fill="#2a3548"/>
            <g>
              <rect x="36" y="52" width="16" height="22" fill="#101620"/>
              <rect class="sc-glow" x="38" y="54" width="12" height="18" fill="#ffc56a"/>
              <rect x="36" y="84" width="16" height="22" fill="#101620"/>
              <rect class="sc-glow" x="38" y="86" width="12" height="18" fill="#101820"/>
              <rect x="36" y="116" width="16" height="22" fill="#101620"/>
              <rect class="sc-glow" x="38" y="118" width="12" height="18" fill="#7eb6ff"/>
              <rect x="36" y="148" width="16" height="22" fill="#101620"/>
              <rect class="sc-glow" x="38" y="150" width="12" height="18" fill="#ffc56a"/>
              <rect x="62" y="52" width="16" height="22" fill="#101620"/>
              <rect class="sc-glow" x="64" y="54" width="12" height="18" fill="#1a2434"/>
              <rect x="62" y="84" width="16" height="22" fill="#101620"/>
              <rect class="sc-glow" x="64" y="86" width="12" height="18" fill="#ffc56a"/>
              <rect x="62" y="116" width="16" height="22" fill="#101620"/>
              <rect class="sc-glow" x="64" y="118" width="12" height="18" fill="#ffc56a"/>
              <rect x="62" y="148" width="16" height="22" fill="#101620"/>
              <rect class="sc-glow" x="64" y="150" width="12" height="18" fill="#1a2434"/>
              <rect x="88" y="52" width="16" height="22" fill="#101620"/>
              <rect class="sc-glow" x="90" y="54" width="12" height="18" fill="#7eb6ff"/>
              <rect x="88" y="84" width="16" height="22" fill="#101620"/>
              <rect class="sc-glow" x="90" y="86" width="12" height="18" fill="#1a2434"/>
              <rect x="88" y="116" width="16" height="22" fill="#101620"/>
              <rect class="sc-glow" x="90" y="118" width="12" height="18" fill="#ffc56a"/>
              <rect x="88" y="148" width="16" height="22" fill="#101620"/>
              <rect class="sc-glow" x="90" y="150" width="12" height="18" fill="#7eb6ff"/>
            </g>
            <rect x="58" y="184" width="34" height="30" fill="#0e141e"/>
            <rect x="62" y="188" width="26" height="22" fill="#c9a06a" opacity="0.35"/>
            <rect x="70" y="188" width="2" height="22" fill="#0e141e"/>""",
        "datacenter": """
            <ellipse cx="170" cy="164" rx="140" ry="10" fill="#000" opacity="0.4"/>
            <polygon points="40,58 300,40 318,56 58,78" fill="#243044"/>
            <polygon points="300,40 318,56 318,132 300,150" fill="#121820"/>
            <rect x="28" y="70" width="250" height="78" fill="url(#scg-front)"/>
            <rect x="28" y="70" width="8" height="78" fill="#9eb4d0" opacity="0.4"/>
            <rect x="28" y="66" width="274" height="8" fill="#6a7e98"/>
            <rect x="28" y="66" width="274" height="2" fill="#e4eef8"/>
            <g>
              <rect class="sc-glow" x="48" y="84" width="14" height="10" fill="#ffc56a"/>
              <rect class="sc-glow" x="70" y="84" width="14" height="10" fill="#7eb6ff"/>
              <rect class="sc-glow" x="92" y="84" width="14" height="10" fill="#1a2434"/>
              <rect class="sc-glow" x="114" y="84" width="14" height="10" fill="#ffc56a"/>
              <rect class="sc-glow" x="136" y="84" width="14" height="10" fill="#ffc56a"/>
              <rect class="sc-glow" x="158" y="84" width="14" height="10" fill="#7eb6ff"/>
              <rect class="sc-glow" x="180" y="84" width="14" height="10" fill="#1a2434"/>
              <rect class="sc-glow" x="202" y="84" width="14" height="10" fill="#ffc56a"/>
              <rect class="sc-glow" x="48" y="102" width="14" height="10" fill="#1a2434"/>
              <rect class="sc-glow" x="70" y="102" width="14" height="10" fill="#ffc56a"/>
              <rect class="sc-glow" x="92" y="102" width="14" height="10" fill="#7eb6ff"/>
              <rect class="sc-glow" x="114" y="102" width="14" height="10" fill="#ffc56a"/>
              <rect class="sc-glow" x="136" y="102" width="14" height="10" fill="#1a2434"/>
              <rect class="sc-glow" x="158" y="102" width="14" height="10" fill="#ffc56a"/>
              <rect class="sc-glow" x="180" y="102" width="14" height="10" fill="#7eb6ff"/>
              <rect class="sc-glow" x="202" y="102" width="14" height="10" fill="#ffc56a"/>
            </g>
            <rect x="44" y="128" width="40" height="30" fill="#1a2e28"/>
            <rect x="46" y="128" width="36" height="4" fill="#3d6a58"/>
            <rect class="sc-glow" x="52" y="140" width="8" height="4" fill="#3cc878"/>
            <rect x="92" y="132" width="40" height="26" fill="#24302c"/>
            <rect class="sc-glow" x="100" y="142" width="8" height="4" fill="#3cc878"/>
            <rect x="230" y="96" width="28" height="36" fill="#2a3038"/>
            <rect x="234" y="88" width="20" height="10" fill="#3a4452"/>
            <rect x="238" y="92" width="4" height="28" fill="#12161c"/>
            <line x1="300" y1="48" x2="200" y2="16" stroke="#c5d0dc" stroke-width="2"/>
            <circle cx="248" cy="32" r="3" fill="#8a94a6"/>""",
        "car": """
            <ellipse cx="120" cy="108" rx="100" ry="8" fill="#000" opacity="0.4"/>
            <path d="M24 78 C24 74 40 70 70 72 L92 50 C100 44 112 44 156 46 L186 72 L214 74 L214 98 C214 104 208 106 200 106 L40 106 C28 106 24 100 24 94 Z" fill="url(#scg-body)" stroke="#1a2230" stroke-width="2" stroke-linejoin="round"/>
            <path d="M24 74 L70 74 L64 100 L24 100 Z" fill="#10151c"/>
            <path d="M96 50 L122 48 L114 72 L78 74 Z" fill="url(#scg-glass)"/>
            <path d="M128 48 L154 46 L168 72 L118 74 Z" fill="#163044"/>
            <path d="M100 52 L112 51 L108 64 L94 66 Z" fill="#fff" opacity="0.5"/>
            <rect x="186" y="72" width="18" height="10" rx="2" fill="#ffe7a8"/>
            <ellipse cx="196" cy="77" rx="12" ry="6" fill="#ffe7a8" opacity="0.35"/>
            <rect x="28" y="78" width="12" height="8" rx="2" fill="#f05252"/>
            <g class="sc-wheel" data-cx="78" data-cy="100">
              <circle cx="78" cy="100" r="16" fill="#101216"/>
              <circle cx="78" cy="100" r="9" fill="#d5dbe3"/>
              <rect x="76" y="88" width="4" height="24" fill="#f4f7fb"/>
              <circle cx="78" cy="100" r="3" fill="#2a3138"/>
            </g>
            <g class="sc-wheel" data-cx="168" data-cy="100">
              <circle cx="168" cy="100" r="16" fill="#101216"/>
              <circle cx="168" cy="100" r="9" fill="#d5dbe3"/>
              <rect x="166" y="88" width="4" height="24" fill="#f4f7fb"/>
              <circle cx="168" cy="100" r="3" fill="#2a3138"/>
            </g>""",
        "tree": """
            <ellipse cx="60" cy="150" rx="36" ry="7" fill="#000" opacity="0.3"/>
            <polygon points="52,86 44,148 68,148 60,86" fill="#5a3a24"/>
            <polygon points="60,86 68,148 74,146 66,86" fill="#3a2418"/>
            <ellipse cx="46" cy="78" rx="28" ry="22" fill="#16301c"/>
            <ellipse cx="74" cy="74" rx="26" ry="20" fill="#1e4428"/>
            <ellipse cx="58" cy="58" rx="30" ry="24" fill="url(#scg-leaf)"/>
            <ellipse cx="48" cy="50" rx="12" ry="8" fill="#8fd498" opacity="0.55"/>""",
        "factory": """
            <ellipse cx="110" cy="152" rx="90" ry="8" fill="#000" opacity="0.35"/>
            <polygon points="150,78 196,96 196,146 150,140" fill="#2a2622"/>
            <rect x="18" y="78" width="140" height="68" fill="#4a4038"/>
            <rect x="18" y="78" width="8" height="68" fill="#8a7564" opacity="0.45"/>
            <polygon points="18,78 48,58 78,78" fill="#5c5046"/>
            <polygon points="70,78 100,56 130,78" fill="#3e362e"/>
            <polygon points="122,78 150,60 168,84 140,90" fill="#2c2824"/>
            <rect x="170" y="28" width="18" height="70" fill="#5a5048"/>
            <rect x="178" y="28" width="10" height="70" fill="#3a342e"/>
            <rect x="166" y="22" width="26" height="8" fill="#6a6058"/>
            <g class="sc-smoke">
              <ellipse cx="180" cy="16" rx="10" ry="6" fill="#d5dee8" opacity="0.45"/>
            </g>
            <rect class="sc-glow" x="36" y="96" width="22" height="16" fill="#ffc56a"/>
            <rect class="sc-glow" x="68" y="96" width="22" height="16" fill="#1a140e"/>
            <rect class="sc-glow" x="100" y="96" width="22" height="16" fill="#ffb45a"/>
            <rect x="40" y="118" width="28" height="28" fill="#241c16"/>""",
        "server": """
            <rect x="14" y="12" width="52" height="128" fill="#121820"/>
            <rect x="18" y="12" width="40" height="128" fill="#1e2838"/>
            <rect x="18" y="12" width="4" height="128" fill="#8aa0bc" opacity="0.45"/>
            <rect x="24" y="24" width="28" height="16" fill="#10161e"/>
            <rect class="sc-glow" x="28" y="28" width="6" height="4" fill="#3cc878"/>
            <rect class="sc-glow" x="38" y="28" width="6" height="4" fill="#f5b83d"/>
            <rect x="24" y="48" width="28" height="16" fill="#10161e"/>
            <rect class="sc-glow" x="28" y="52" width="6" height="4" fill="#4c8dff"/>
            <rect x="24" y="72" width="28" height="16" fill="#10161e"/>
            <rect class="sc-glow" x="28" y="76" width="6" height="4" fill="#3cc878"/>
            <rect x="22" y="16" width="18" height="40" fill="#fff" opacity="0.06"/>""",
        "phone": """
            <rect x="16" y="8" width="58" height="144" rx="10" fill="#0e1218"/>
            <rect x="20" y="8" width="46" height="144" rx="8" fill="#1c2432"/>
            <rect x="20" y="8" width="5" height="144" fill="#8aa0bc" opacity="0.35"/>
            <rect x="26" y="22" width="36" height="108" rx="2" fill="#10161e"/>
            <polyline points="32,96 44,78 52,88 64,60" fill="none" stroke="#f5b83d" stroke-width="2"/>
            <rect x="26" y="22" width="14" height="28" fill="#fff" opacity="0.08"/>
            <circle cx="44" cy="140" r="3" fill="#2a3446"/>""",
        "chart": """
            <ellipse cx="90" cy="112" rx="70" ry="7" fill="#000" opacity="0.3"/>
            <polygon points="150,28 168,40 168,108 150,100" fill="#10141c"/>
            <rect x="14" y="18" width="140" height="86" rx="4" fill="#243044"/>
            <rect x="14" y="18" width="140" height="4" fill="#d5e2f2"/>
            <rect x="22" y="28" width="124" height="68" fill="#0c121c"/>
            <polyline points="30,78 52,64 74,70 98,46 124,54 140,40" fill="none" stroke="#f5b83d" stroke-width="3"/>
            <polyline points="30,80 52,66 74,72 98,48 124,56 140,42" fill="none" stroke="#f5b83d" stroke-width="6" opacity="0.25"/>
            <rect x="22" y="28" width="40" height="16" fill="#fff" opacity="0.06"/>""",
        "powerline": """
            <line x1="8" y1="78" x2="96" y2="28" stroke="#d5dee8" stroke-width="2"/>
            <line x1="96" y1="28" x2="196" y2="70" stroke="#d5dee8" stroke-width="2"/>
            <rect x="88" y="26" width="16" height="78" fill="#2a3448"/>
            <rect x="88" y="26" width="4" height="78" fill="#8aa0bc" opacity="0.5"/>
            <rect x="82" y="24" width="28" height="6" fill="#4a5c78"/>
            <rect x="90" y="46" width="12" height="5" fill="#6a5430"/>
            <rect x="90" y="62" width="12" height="5" fill="#6a5430"/>""",
    }


def sprite(style: str) -> str:
    """A hidden symbol library. `cinematic` is the detailed set; anything else is flat."""
    parts = _cinematic() if style == "cinematic" else _classic()
    defs = _DEFS if style == "cinematic" else ""
    symbols = []
    for name in SCENE_OBJECTS:
        bw, bh = SCENE_BOX[name]
        symbols.append(
            f'<symbol id="sc-{name}" viewBox="0 0 {bw} {bh}">{parts[name]}</symbol>'
        )
    symbols.extend(_bot_symbols(style == "cinematic"))
    return (
        '<svg id="sc-lib" width="0" height="0" shape-rendering="geometricPrecision" '
        'stroke-linejoin="round" stroke-linecap="round" '
        'style="position:absolute;left:0;top:0" aria-hidden="true">'
        + defs + "".join(symbols) + "</svg>"
    )


BOT_SHAPES = ("circle", "squircle", "blob", "drop")
# Pastels from the reference sheet, used when a topic does not name a color.
BOT_COLORS = ("#a78bfa", "#4c8dff", "#5dbea3", "#6bcb77", "#a07858", "#5b8def")


def _bot_symbols(cinematic: bool) -> list:
    """Friendly blob characters. Eyes sit a little to one side, like the reference."""
    bodies = {
        "circle": '<ellipse cx="80" cy="82" rx="54" ry="52" fill="currentColor"/>',
        "squircle": '<rect x="26" y="28" width="108" height="104" rx="32" fill="currentColor"/>',
        "blob": '<path d="M80 28 C118 26 140 52 136 86 C132 122 108 138 78 134 C40 128 22 100 30 70 C38 40 52 30 80 28 Z" fill="currentColor"/>',
        "drop": '<path d="M80 24 C108 24 128 52 124 84 C120 118 100 142 80 142 C60 142 40 118 36 84 C32 52 52 24 80 24 Z" fill="currentColor"/>',
    }
    eyes = (
        '<ellipse class="sc-eye" cx="86" cy="74" rx="6" ry="11" fill="#fff"/>'
        '<ellipse class="sc-eye" cx="106" cy="74" rx="6" ry="11" fill="#fff"/>'
    )
    shade = (
        '<ellipse cx="62" cy="64" rx="22" ry="16" fill="#fff" opacity="0.22"/>'
        '<ellipse cx="98" cy="108" rx="28" ry="16" fill="#000" opacity="0.12"/>'
        '<ellipse cx="80" cy="148" rx="46" ry="8" fill="#000" opacity="0.28"/>'
    ) if cinematic else ""
    out = []
    for shape, body in bodies.items():
        out.append(
            f'<symbol id="sc-bot-{shape}" viewBox="0 0 160 160">{shade}{body}{eyes}</symbol>'
        )
    out.append(
        '<symbol id="sc-check" viewBox="0 0 48 48">'
        '<circle cx="24" cy="24" r="20" fill="#0b0f16" stroke="#f2f4f8" stroke-width="3"/>'
        '<path d="M14 25 L21 32 L35 16" fill="none" stroke="#f2f4f8" stroke-width="4" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '</symbol>'
    )
    return out


def bot(shape: str, fill: str, x: float, y: float, size: float = 140, depth: float = 1) -> str:
    """One character. `fill` is a CSS color. The label sits in HTML, not in the symbol."""
    if shape not in BOT_SHAPES:
        shape = "circle"
    return (
        f'<svg class="sc sc-bot" data-sc="bot" data-shape="{shape}" data-depth="{depth:g}" '
        f'x="{x:g}" y="{y:g}" width="{size:g}" height="{size:g}" viewBox="0 0 160 160" '
        f'shape-rendering="geometricPrecision" style="color:{fill}">'
        f'<use href="#sc-bot-{shape}"/></svg>'
    )


def bot_card(shape: str, fill: str, label: str, left: float, top: float, delay: float) -> str:
    """A character plus a dark pill, popping in at `delay` seconds after the slide starts."""
    import html as _html
    safe = _html.escape(label or "", quote=True)
    return (
        f'<div class="sc-fig" data-anim="pop" data-t="+{delay:.2f}" '
        f'style="position:absolute; left:{left:g}px; top:{top:g}px; width:300px; text-align:center;">'
        f'{bot(shape, fill, 80, 0, 140)}'
        f'<div class="sc-pill">{safe}</div></div>'
    )


def check_badge(x: float, y: float, delay: float) -> str:
    return (
        f'<svg class="sc" data-sc="check" x="{x:g}" y="{y:g}" width="52" height="52" viewBox="0 0 48 48" '
        f'data-anim="pop" data-t="+{delay:.2f}" shape-rendering="geometricPrecision">'
        f'<use href="#sc-check"/></svg>'
    )


def connector(x1: float, y1: float, x2: float, y2: float, delay: float = 0.6) -> str:
    """A dotted line that fades on. Coordinates are in the scene svg.

    It stays dotted. The draw animation would replace the dots with a solid stroke.
    """
    return (
        f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" stroke="#8a94a6" stroke-width="3" '
        f'stroke-dasharray="2 8" stroke-linecap="round" data-anim="fade" data-t="+{delay:.2f}"/>'
    )


def place(name: str, x: float, y: float, w: float, h: float, depth: float = 1) -> str:
    """One object in a scene, same markup in either style."""
    if name not in SCENE_OBJECTS:
        raise KeyError(name)
    bw, bh = SCENE_BOX[name]
    return (
        f'<svg class="sc" data-sc="{name}" data-depth="{depth:g}" x="{x:g}" y="{y:g}" '
        f'width="{w:g}" height="{h:g}" viewBox="0 0 {bw} {bh}"><use href="#sc-{name}"/></svg>'
    )
