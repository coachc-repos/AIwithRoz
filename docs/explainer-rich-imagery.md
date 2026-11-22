# Explainer pictures

The wave background stays. It is the same field as before: rows of flat dots on `#090c12`, no gradients. It is denser (`WAVE_ROWS`, default 34, was 20) and a little faster (`WAVE_SPEED`, default 1.4). Both styles use it.

`visual_style` is saved like the corner frame and the guide.

| Style | What changes |
| --- | --- |
| `classic` (default) | The denser, faster waves. Objects animate exactly as before. |
| `cinematic` | The same waves. While a card, icon, chart or figure is entering, it gets a short 3D fly-in (a small rotate, a z move, a scale overshoot), a contact shadow that tightens as it lands, a specular sweep, a faint motion trail, a little blur on the objects that have already landed, and a small camera push. Then it sits in its normal look. |
| `rich` | Old name. It means cinematic. |

The hook is every slide before the first chapter card (or the first slide, when there is no chapter). Its entrance is stronger: more rotation, more travel, a brighter sweep, a slightly bigger camera push. Body slides use the quieter set. Both sets are `POP` in `explainer_imagery.py`.

Type and number animations keep their timing. Headlines, word-by-word lines and counting numbers are not tilted or blurred. Light comes from the upper left, and the rotations stay small so a panel stays thin.

Nothing in this path calls Grok Imagine or paints a still behind the slide.
