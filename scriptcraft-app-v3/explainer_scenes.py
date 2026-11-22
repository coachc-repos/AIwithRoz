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
    "car": (400, 130),
    "tree": (140, 170),
    "factory": (220, 170),
    "server": (80, 160),
    "phone": (82, 168),
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
  <linearGradient id="scg-sedan" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#5c6e84"/><stop offset="0.42" stop-color="#2c3a4c"/><stop offset="1" stop-color="#141a24"/>
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
    # Flat shapes. Each piece overlaps the one it sits on by a few units so a
    # scaled render cannot open a hairline of background between them.
    return {
        "house": """<rect x="36" y="80" width="148" height="70" fill="#6b4630"/>
            <rect x="148" y="44" width="16" height="40" fill="#5a4030"/>
            <polygon points="14,88 110,30 206,88" fill="#8a5a32"/>
            <rect x="144" y="38" width="24" height="8" fill="#6a5040"/>
            <rect x="56" y="96" width="28" height="22" fill="#f5b83d"/>
            <rect x="124" y="96" width="28" height="22" fill="#1a2232"/>
            <rect x="92" y="112" width="28" height="38" fill="#241810"/>""",
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
        "car": """<circle cx="85" cy="96" r="30" fill="#4a5568"/><circle cx="85" cy="96" r="12" fill="#d5dbe3"/>
            <circle cx="315" cy="96" r="30" fill="#4a5568"/><circle cx="315" cy="96" r="12" fill="#d5dbe3"/>
            <path d="M8 96 L8 64 C12 54 22 52 30 52 L95 52 L150 16 L245 16 L300 50 C340 54 370 62 392 78 C396 88 390 96 376 96 L349 96 C349 77 334 62 315 62 C296 62 281 77 281 96 L119 96 C119 77 104 62 85 62 C66 62 51 77 51 96 L8 96 Z" fill="#2a3446"/>
            <path d="M108 52 L155 24 L236 24 L286 52 Z" fill="#3a465c"/>""",
        "tree": """<rect x="52" y="78" width="18" height="64" fill="#6b4630"/>
            <circle cx="60" cy="64" r="40" fill="#2f6a3c"/>""",
        "factory": """<rect x="20" y="74" width="156" height="72" fill="#3a342e"/>
            <polygon points="148,78 196,96 196,146 148,146" fill="#2a2622"/>
            <polygon points="28,78 58,54 88,78" fill="#5c5046"/>
            <polygon points="78,78 112,52 146,78" fill="#4a4038"/>
            <rect x="168" y="36" width="18" height="70" fill="#4a4038"/>
            <rect x="40" y="96" width="22" height="16" fill="#f5b83d"/>
            <rect x="72" y="96" width="22" height="16" fill="#1a2232"/>""",
        "server": """<rect x="18" y="16" width="44" height="120" fill="#1c2432"/>
            <rect x="26" y="28" width="28" height="8" fill="#3cc878"/>
            <rect x="26" y="44" width="28" height="8" fill="#f5b83d"/>
            <rect x="26" y="60" width="28" height="8" fill="#4c8dff"/>""",
        "phone": """<rect x="4" y="4" width="74" height="160" rx="16" fill="#1c2432"/>
            <rect x="10" y="20" width="62" height="132" rx="4" fill="#121820"/>
            <rect x="28" y="24" width="26" height="8" rx="4" fill="#0a0e14"/>""",
        "chart": """<polygon points="156,28 174,40 174,108 156,100" fill="#121820"/>
            <rect x="16" y="20" width="148" height="90" rx="6" fill="#1c2432"/>
            <polyline points="32,86 58,70 80,76 108,48 140,58" fill="none" stroke="#f5b83d" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>""",
        "powerline": """<ellipse cx="110" cy="104" rx="22" ry="4" fill="#000" opacity="0.35"/>
            <polygon points="98,92 122,92 128,104 92,104" fill="#3a465c"/>
            <rect x="104" y="24" width="12" height="72" fill="#2a3446"/>
            <rect x="64" y="20" width="92" height="8" fill="#3a465c"/>
            <rect x="72" y="28" width="6" height="8" fill="#6a5430"/>
            <rect x="142" y="28" width="6" height="8" fill="#6a5430"/>
            <path d="M75 36 Q 30 62 0 52" fill="none" stroke="#8a94a6" stroke-width="3" stroke-linecap="round"/>
            <path d="M145 36 Q 186 58 220 50" fill="none" stroke="#8a94a6" stroke-width="3" stroke-linecap="round"/>""",
    }


def _cinematic() -> dict:
    # One mass per object. A part that touches another overlaps it by a few
    # units, on integer coordinates, so scaling and the parallax translate
    # cannot open a seam. Highlights sit on top of an opaque fill.
    return {
        "house": """
            <ellipse cx="110" cy="158" rx="78" ry="8" fill="#000" opacity="0.35"/>
            <rect x="32" y="90" width="148" height="62" fill="url(#scg-wall)"/>
            <rect x="32" y="90" width="8" height="62" fill="#c4a078" opacity="0.45"/>
            <rect x="156" y="48" width="16" height="48" fill="#5a4030"/>
            <rect x="164" y="48" width="8" height="48" fill="#3a281c"/>
            <polygon points="16,96 110,24 204,96 188,110 32,110" fill="url(#scg-roof)"/>
            <polygon points="110,24 204,96 188,110" fill="#3a2418"/>
            <rect x="152" y="40" width="24" height="12" fill="#6a5040"/>
            <polygon points="28,144 180,144 188,156 20,156" fill="#5c4634"/>
            <rect x="48" y="106" width="8" height="40" fill="#2c2118"/>
            <rect x="152" y="106" width="8" height="40" fill="#1a140e"/>
            <rect x="84" y="114" width="28" height="42" fill="#2a1c14"/>
            <rect x="88" y="118" width="9" height="14" fill="#4a3424"/>
            <rect x="99" y="118" width="9" height="14" fill="#3a281c"/>
            <circle cx="108" cy="134" r="2" fill="#e8d2a0"/>
            <rect x="46" y="114" width="28" height="22" fill="#1a140e"/>
            <rect class="sc-glow" x="48" y="116" width="24" height="18" fill="#ffc56a"/>
            <rect x="58" y="116" width="3" height="18" fill="#1a140e"/>
            <rect x="48" y="123" width="24" height="3" fill="#1a140e"/>
            <rect x="120" y="114" width="28" height="22" fill="#1a140e"/>
            <rect class="sc-glow" x="122" y="116" width="24" height="18" fill="#9ec8ee"/>
            <rect x="132" y="116" width="3" height="18" fill="#1a140e"/>
            <rect x="122" y="116" width="8" height="4" fill="#fff" opacity="0.4"/>""",
        "building": """
            <ellipse cx="100" cy="228" rx="72" ry="8" fill="#000" opacity="0.4"/>
            <polygon points="132,52 176,68 176,214 132,220" fill="#121820"/>
            <rect x="24" y="46" width="120" height="174" fill="url(#scg-front)"/>
            <rect x="24" y="46" width="8" height="174" fill="#8ea6c8" opacity="0.4"/>
            <polygon points="14,34 170,34 178,48 22,48" fill="#5c7090"/>
            <polygon points="160,34 178,48 178,62 160,50" fill="#3a4a62"/>
            <rect x="14" y="34" width="156" height="4" fill="#d5e2f2"/>
            <rect x="42" y="16" width="34" height="26" fill="#1a2230"/>
            <rect x="50" y="8" width="8" height="14" fill="#2a3548"/>
            <g>
              <rect x="38" y="60" width="20" height="26" fill="#101620"/>
              <rect class="sc-glow" x="40" y="62" width="16" height="22" fill="#ffc56a"/>
              <rect x="38" y="96" width="20" height="26" fill="#101620"/>
              <rect class="sc-glow" x="40" y="98" width="16" height="22" fill="#101820"/>
              <rect x="38" y="132" width="20" height="26" fill="#101620"/>
              <rect class="sc-glow" x="40" y="134" width="16" height="22" fill="#7eb6ff"/>
              <rect x="38" y="168" width="20" height="26" fill="#101620"/>
              <rect class="sc-glow" x="40" y="170" width="16" height="22" fill="#ffc56a"/>
              <rect x="68" y="60" width="20" height="26" fill="#101620"/>
              <rect class="sc-glow" x="70" y="62" width="16" height="22" fill="#1a2434"/>
              <rect x="68" y="96" width="20" height="26" fill="#101620"/>
              <rect class="sc-glow" x="70" y="98" width="16" height="22" fill="#ffc56a"/>
              <rect x="68" y="132" width="20" height="26" fill="#101620"/>
              <rect class="sc-glow" x="70" y="134" width="16" height="22" fill="#ffc56a"/>
              <rect x="68" y="168" width="20" height="26" fill="#101620"/>
              <rect class="sc-glow" x="70" y="170" width="16" height="22" fill="#1a2434"/>
              <rect x="98" y="60" width="20" height="26" fill="#101620"/>
              <rect class="sc-glow" x="100" y="62" width="16" height="22" fill="#7eb6ff"/>
              <rect x="98" y="96" width="20" height="26" fill="#101620"/>
              <rect class="sc-glow" x="100" y="98" width="16" height="22" fill="#1a2434"/>
              <rect x="98" y="132" width="20" height="26" fill="#101620"/>
              <rect class="sc-glow" x="100" y="134" width="16" height="22" fill="#ffc56a"/>
              <rect x="98" y="168" width="20" height="26" fill="#101620"/>
              <rect class="sc-glow" x="100" y="170" width="16" height="22" fill="#7eb6ff"/>
            </g>
            <rect x="62" y="190" width="36" height="30" fill="#0e141e"/>
            <rect x="66" y="194" width="28" height="22" fill="#c9a06a" opacity="0.4"/>
            <rect x="78" y="194" width="3" height="22" fill="#0e141e"/>""",
        "datacenter": """
            <ellipse cx="168" cy="168" rx="130" ry="8" fill="#000" opacity="0.38"/>
            <polygon points="262,80 318,66 318,148 262,156" fill="#121820"/>
            <rect x="24" y="74" width="252" height="82" fill="url(#scg-front)"/>
            <rect x="24" y="74" width="8" height="82" fill="#9eb4d0" opacity="0.4"/>
            <polygon points="12,78 256,50 292,66 36,94" fill="#243044"/>
            <polygon points="256,50 318,66 300,80 262,68" fill="#161c28"/>
            <rect x="20" y="74" width="240" height="4" fill="#e4eef8"/>
            <g>
              <rect x="46" y="96" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="48" y="98" width="14" height="10" fill="#ffc56a"/>
              <rect x="70" y="96" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="72" y="98" width="14" height="10" fill="#7eb6ff"/>
              <rect x="94" y="96" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="96" y="98" width="14" height="10" fill="#1a2434"/>
              <rect x="118" y="96" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="120" y="98" width="14" height="10" fill="#ffc56a"/>
              <rect x="142" y="96" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="144" y="98" width="14" height="10" fill="#ffc56a"/>
              <rect x="166" y="96" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="168" y="98" width="14" height="10" fill="#7eb6ff"/>
              <rect x="190" y="96" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="192" y="98" width="14" height="10" fill="#1a2434"/>
              <rect x="214" y="96" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="216" y="98" width="14" height="10" fill="#ffc56a"/>
              <rect x="46" y="116" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="48" y="118" width="14" height="10" fill="#1a2434"/>
              <rect x="70" y="116" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="72" y="118" width="14" height="10" fill="#ffc56a"/>
              <rect x="94" y="116" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="96" y="118" width="14" height="10" fill="#7eb6ff"/>
              <rect x="118" y="116" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="120" y="118" width="14" height="10" fill="#ffc56a"/>
              <rect x="142" y="116" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="144" y="118" width="14" height="10" fill="#1a2434"/>
              <rect x="166" y="116" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="168" y="118" width="14" height="10" fill="#ffc56a"/>
              <rect x="190" y="116" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="192" y="118" width="14" height="10" fill="#7eb6ff"/>
              <rect x="214" y="116" width="18" height="14" fill="#101620"/>
              <rect class="sc-glow" x="216" y="118" width="14" height="10" fill="#ffc56a"/>
            </g>
            <rect x="44" y="140" width="44" height="28" fill="#1a2e28"/>
            <rect x="46" y="140" width="40" height="4" fill="#3d6a58"/>
            <rect class="sc-glow" x="54" y="152" width="10" height="5" fill="#3cc878"/>
            <rect x="98" y="144" width="44" height="24" fill="#24302c"/>
            <rect class="sc-glow" x="108" y="154" width="10" height="5" fill="#3cc878"/>
            <rect x="228" y="36" width="8" height="28" fill="#3a4452"/>
            <circle cx="232" cy="36" r="3" fill="#c5d0dc"/>
            <line x1="232" y1="36" x2="206" y2="28" stroke="#c5d0dc" stroke-width="3" stroke-linecap="round"/>""",
        "car": """
            <!-- Original sedan on a 400x130 grid, nose to the right. Not copied from a clip-art file. -->
            <ellipse cx="200" cy="124" rx="150" ry="5" fill="#000" opacity="0.35"/>
            <circle cx="85" cy="96" r="34" fill="#0c1016"/>
            <circle cx="315" cy="96" r="34" fill="#0c1016"/>
            <g class="sc-wheel" data-cx="85" data-cy="96">
              <circle cx="85" cy="96" r="30" fill="#1a1f28"/>
              <circle cx="85" cy="96" r="21" fill="#d5dde6"/>
              <rect x="83" y="78" width="4" height="14" rx="1" fill="#f4f7fb" transform="rotate(0 85 96)"/>
              <rect x="83" y="78" width="4" height="14" rx="1" fill="#f4f7fb" transform="rotate(72 85 96)"/>
              <rect x="83" y="78" width="4" height="14" rx="1" fill="#f4f7fb" transform="rotate(144 85 96)"/>
              <rect x="83" y="78" width="4" height="14" rx="1" fill="#f4f7fb" transform="rotate(216 85 96)"/>
              <rect x="83" y="78" width="4" height="14" rx="1" fill="#f4f7fb" transform="rotate(288 85 96)"/>
              <circle cx="85" cy="96" r="7" fill="#2a3138"/>
            </g>
            <g class="sc-wheel" data-cx="315" data-cy="96">
              <circle cx="315" cy="96" r="30" fill="#1a1f28"/>
              <circle cx="315" cy="96" r="21" fill="#d5dde6"/>
              <rect x="313" y="78" width="4" height="14" rx="1" fill="#f4f7fb" transform="rotate(0 315 96)"/>
              <rect x="313" y="78" width="4" height="14" rx="1" fill="#f4f7fb" transform="rotate(72 315 96)"/>
              <rect x="313" y="78" width="4" height="14" rx="1" fill="#f4f7fb" transform="rotate(144 315 96)"/>
              <rect x="313" y="78" width="4" height="14" rx="1" fill="#f4f7fb" transform="rotate(216 315 96)"/>
              <rect x="313" y="78" width="4" height="14" rx="1" fill="#f4f7fb" transform="rotate(288 315 96)"/>
              <circle cx="315" cy="96" r="7" fill="#2a3138"/>
            </g>
            <path d="M8 96 L8 64 C12 54 22 52 30 52 L95 52 L150 16 L245 16 L300 50 C340 54 372 64 392 80 C396 90 390 96 376 96 L349 96 C349 77 334 62 315 62 C296 62 281 77 281 96 L119 96 C119 77 104 62 85 62 C66 62 51 77 51 96 L8 96 Z" fill="url(#scg-sedan)"/>
            <path d="M36 88 L28 88 L8 84 L8 96 L40 96 Z" fill="#6d7c90"/>
            <path d="M366 80 L384 74 L388 88 L368 92 Z" fill="#6d7c90"/>
            <path d="M40 56 L290 54 L290 57 L40 59 Z" fill="#c5d2e0" opacity="0.28"/>
            <path d="M100 52 L155 21 L240 21 L290 52 Z" fill="url(#scg-glass)"/>
            <path d="M150 24 L250 24 L246 32 L146 32 Z" fill="#fff" opacity="0.28"/>
            <path d="M112 52 L118 52 L166 21 L160 21 Z" fill="#243044"/>
            <path d="M196 21 L206 21 L212 52 L202 52 Z" fill="#243044"/>
            <path d="M202 21 L206 21 L212 52 L208 52 Z" fill="#101820"/>
            <path d="M16 58 L30 56 L30 70 L14 68 Z" fill="#e45a5a"/>
            <path d="M358 64 L374 66 L374 78 L356 76 Z" fill="#ffe7a8"/>
            <path d="M262 50 L280 48 L282 58 L260 58 Z" fill="#121820"/>
            <rect x="150" y="68" width="16" height="4" rx="2" fill="#c5ced8"/>
            <rect x="214" y="68" width="16" height="4" rx="2" fill="#c5ced8"/>""",
        "tree": """
            <ellipse cx="70" cy="158" rx="34" ry="6" fill="#000" opacity="0.32"/>
            <polygon points="58,96 50,156 86,156 78,96" fill="#5a3a24"/>
            <polygon points="74,96 86,156 92,154 82,96" fill="#3a2418"/>
            <ellipse cx="48" cy="92" rx="30" ry="24" fill="#16301c"/>
            <ellipse cx="92" cy="88" rx="28" ry="22" fill="#1e4428"/>
            <ellipse cx="70" cy="70" rx="34" ry="28" fill="url(#scg-leaf)"/>
            <ellipse cx="56" cy="58" rx="12" ry="8" fill="#8fd498" opacity="0.55"/>""",
        "factory": """
            <ellipse cx="110" cy="158" rx="88" ry="7" fill="#000" opacity="0.35"/>
            <polygon points="148,86 200,102 200,150 148,150" fill="#2a2622"/>
            <rect x="16" y="84" width="148" height="66" fill="#4a4038"/>
            <rect x="16" y="84" width="8" height="66" fill="#8a7564" opacity="0.45"/>
            <polygon points="16,88 50,60 84,88" fill="#5c5046"/>
            <polygon points="70,88 108,56 146,88" fill="#3e362e"/>
            <polygon points="124,88 156,64 176,96 140,100" fill="#2c2824"/>
            <rect x="168" y="40" width="20" height="72" fill="#5a5048"/>
            <rect x="176" y="40" width="12" height="72" fill="#3a342e"/>
            <rect x="164" y="34" width="28" height="10" fill="#6a6058"/>
            <g class="sc-smoke">
              <ellipse cx="178" cy="40" rx="9" ry="6" fill="#d5dee8" opacity="0.6"/>
            </g>
            <rect x="34" y="102" width="26" height="18" fill="#1a140e"/>
            <rect class="sc-glow" x="36" y="104" width="22" height="14" fill="#ffc56a"/>
            <rect x="70" y="102" width="26" height="18" fill="#1a140e"/>
            <rect class="sc-glow" x="72" y="104" width="22" height="14" fill="#241c16"/>
            <rect x="106" y="102" width="26" height="18" fill="#1a140e"/>
            <rect class="sc-glow" x="108" y="104" width="22" height="14" fill="#ffb45a"/>
            <rect x="36" y="124" width="30" height="26" fill="#241c16"/>""",
        "server": """
            <ellipse cx="40" cy="152" rx="24" ry="5" fill="#000" opacity="0.35"/>
            <rect x="14" y="10" width="52" height="136" rx="4" fill="#121820"/>
            <rect x="20" y="10" width="42" height="136" rx="3" fill="#1e2838"/>
            <rect x="20" y="14" width="6" height="128" fill="#8aa0bc" opacity="0.4"/>
            <rect x="28" y="26" width="28" height="18" rx="2" fill="#10161e"/>
            <rect class="sc-glow" x="32" y="32" width="8" height="6" rx="1" fill="#3cc878"/>
            <rect class="sc-glow" x="44" y="32" width="8" height="6" rx="1" fill="#f5b83d"/>
            <rect x="28" y="54" width="28" height="18" rx="2" fill="#10161e"/>
            <rect class="sc-glow" x="32" y="60" width="8" height="6" rx="1" fill="#4c8dff"/>
            <rect x="28" y="82" width="28" height="18" rx="2" fill="#10161e"/>
            <rect class="sc-glow" x="32" y="88" width="8" height="6" rx="1" fill="#3cc878"/>""",
        "phone": """
            <rect x="2" y="4" width="78" height="160" rx="22" fill="#0e1218"/>
            <rect x="5" y="7" width="72" height="154" rx="20" fill="#1c2432"/>
            <rect x="9" y="18" width="64" height="134" rx="10" fill="#10161e"/>
            <rect x="28" y="22" width="26" height="8" rx="4" fill="#0a0e14"/>
            <polyline points="18,110 32,90 44,100 56,76 68,86" fill="none" stroke="#f5b83d" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>""",
        "chart": """
            <ellipse cx="100" cy="118" rx="64" ry="6" fill="#000" opacity="0.32"/>
            <polygon points="148,30 170,44 170,108 148,100" fill="#10141c"/>
            <rect x="16" y="20" width="140" height="90" rx="6" fill="#243044"/>
            <rect x="16" y="20" width="140" height="6" rx="3" fill="#d5e2f2"/>
            <rect x="26" y="34" width="120" height="64" rx="2" fill="#0c121c"/>
            <polyline points="34,82 54,68 74,74 98,50 122,58 138,44" fill="none" stroke="#f5b83d" stroke-width="8" stroke-linejoin="round" stroke-linecap="round" opacity="0.25"/>
            <polyline points="34,80 54,66 74,72 98,48 122,56 138,42" fill="none" stroke="#f5b83d" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>""",
        "powerline": """
            <ellipse cx="110" cy="104" rx="26" ry="5" fill="#000" opacity="0.35"/>
            <polygon points="96,94 124,94 132,106 88,106" fill="#3a4458"/>
            <rect x="102" y="22" width="16" height="76" fill="#2a3448"/>
            <rect x="102" y="22" width="5" height="76" fill="#8aa0bc" opacity="0.45"/>
            <rect x="58" y="18" width="104" height="10" fill="#4a5c78"/>
            <rect x="68" y="28" width="8" height="12" rx="2" fill="#6a5430"/>
            <rect x="104" y="28" width="8" height="12" rx="2" fill="#6a5430"/>
            <rect x="144" y="28" width="8" height="12" rx="2" fill="#6a5430"/>
            <path d="M72 40 Q 34 62 0 50" fill="none" stroke="#d5dee8" stroke-width="3" stroke-linecap="round"/>
            <path d="M72 40 Q 28 84 0 92" fill="none" stroke="#d5dee8" stroke-width="3" stroke-linecap="round"/>
            <path d="M152 40 Q 188 62 220 50" fill="none" stroke="#d5dee8" stroke-width="3" stroke-linecap="round"/>
            <path d="M152 40 Q 194 84 220 92" fill="none" stroke="#d5dee8" stroke-width="3" stroke-linecap="round"/>""",
    }


def sprite(style: str) -> str:
    """A hidden symbol library. `cinematic` is the detailed set; anything else is flat."""
    parts = _cinematic() if style == "cinematic" else _classic()
    defs = _DEFS if style == "cinematic" else ""
    symbols = []
    for name in SCENE_OBJECTS:
        bw, bh = SCENE_BOX[name]
        symbols.append(
            f'<symbol id="sc-{name}" viewBox="0 0 {bw} {bh}" '
            f'shape-rendering="geometricPrecision" stroke-linejoin="round" stroke-linecap="round">'
            f'{parts[name]}</symbol>'
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
    # Both eyes are the same solid white, centered as a pair. A blink changes
    # their height together; it never fades one of them.
    eyes = (
        '<g class="sc-eyes">'
        '<ellipse class="sc-eye" cx="68" cy="80" rx="7" ry="12" fill="#ffffff"/>'
        '<ellipse class="sc-eye" cx="92" cy="80" rx="7" ry="12" fill="#ffffff"/>'
        '</g>'
    )
    shadow = '<ellipse cx="80" cy="150" rx="46" ry="8" fill="#000" opacity="0.28"/>' if cinematic else ""
    highlight = '<ellipse cx="50" cy="48" rx="14" ry="9" fill="#fff" opacity="0.28"/>' if cinematic else ""
    out = []
    for shape, body in bodies.items():
        out.append(
            f'<symbol id="sc-bot-{shape}" viewBox="0 0 160 160">{shadow}{body}{highlight}{eyes}</symbol>'
        )
    out.append(
        '<symbol id="sc-check" viewBox="0 0 48 48">'
        '<circle cx="24" cy="24" r="20" fill="#0b0f16" stroke="#f2f4f8" stroke-width="3"/>'
        '<path d="M14 25 L21 32 L35 16" fill="none" stroke="#f2f4f8" stroke-width="4" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '</symbol>'
    )
    return out


def bot(shape: str, fill: str, x: float, y: float, size: float = 140, depth: float = 1,
        hop: float = None, look: str = "") -> str:
    """One character. `fill` is a CSS color. The label sits in HTML, not in the symbol.

    hop is seconds after the slide starts when the character jumps (a check
    badge landing). look="hub" aims the eyes toward the center of a diagram.
    """
    if shape not in BOT_SHAPES:
        shape = "circle"
    extra = ""
    if hop is not None:
        extra += f' data-hop="+{hop:.2f}"'
    if look:
        extra += f' data-look="{look}"'
    return (
        f'<svg class="sc sc-bot" data-sc="bot" data-shape="{shape}" data-depth="{depth:g}"{extra} '
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
    """A dotted line from a character (x1, y1) toward the hub (x2, y2).

    The dots stay dotted and, in cinematic, travel toward the hub.
    """
    return (
        f'<line class="sc-flow" x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" stroke="#8a94a6" '
        f'stroke-width="3" stroke-dasharray="2 8" stroke-linecap="round" data-anim="fade" '
        f'data-t="+{delay:.2f}"/>'
    )


def place(name: str, x: float, y: float, w: float, h: float, depth: float = 1,
         drive: bool = False) -> str:
    """One object in a scene, same markup in either style.

    drive=True is for a car that should roll to the right while its wheels turn.
    """
    if name not in SCENE_OBJECTS:
        raise KeyError(name)
    bw, bh = SCENE_BOX[name]
    flag = ' data-drive="1"' if drive else ""
    return (
        f'<svg class="sc" data-sc="{name}" data-depth="{depth:g}"{flag} x="{x:g}" y="{y:g}" '
        f'width="{w:g}" height="{h:g}" viewBox="0 0 {bw} {bh}"><use href="#sc-{name}"/></svg>'
    )
