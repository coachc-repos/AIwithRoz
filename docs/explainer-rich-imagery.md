# Explainer pictures

Text slides are unchanged, apart from the wave background. That field is the same flat dots as before, denser (`WAVE_ROWS` 34, was 20) and a little faster (`WAVE_SPEED` 1.4). Both styles use it.

Scene illustrations use a small original library (`explainer_scenes.py`, no third-party art). A scene places an object with `<use href="#sc-house"/>` and `data-sc`. The names are house, building, datacenter, car, tree, factory, server, phone, chart, and powerline.

| Style | Scene objects |
| --- | --- |
| `classic` (default) | The flat silhouette: a box, a roof triangle, two circles. |
| `cinematic` | The same object with a lit face and a darker side (light from the upper left), a contact shadow, glass, and motion: wheels turn, a few windows flicker, smoke rises, near objects drift more than far ones. |
| `rich` | Old name. It means cinematic. |

The hook is every scene before the first chapter card. Those objects drift a little more and the wheels turn a little faster. Headlines, cards, and numbers are not part of this.

Gradients and a light noise filter live only inside the cinematic symbols, not on the page background. Edges use geometric precision and round joins. The 4K render draws the page at scale 2, which is the smooth capture in `edge_4k.png`.

If the script is about agents, bots, apps or tools, the scene uses characters instead of houses and cars: `sc-bot` (circle, squircle, blob or drop), a dark `sc-pill` label taken from the narration, a dotted connector, an `sc-check` badge and an `sc-message`. A grid and a hub-and-spoke tracker are the two layouts. Other topics can use a phone or chart object plus a pill with the product name.

A slide whose narration says it will show something ("let me show you", "here's how", a walkthrough) gets a Demo video slot. In the preview that is a dashed frame on the right, clear of the text card. Upload an mp4, mov or webm in Clips, optionally trimmed, and assign it. The narration keeps playing and the clip starts muted. An empty slot is not drawn in the final render, so the slide underneath is what gets encoded.

In cinematic, bot characters keep moving the whole time they are on screen: a small float, a little squash, a shared blink, a glance, and a hop when a check badge lands. Dots on a connector travel toward the hub. Classic leaves them still.

Brands named in the narration (Nvidia, ChatGPT, Claude, and the others in explainer_brands.py) get a large logo. The file comes from Simple Icons, which is CC0-1.0, downloaded into that project's logos folder and not stored in this repository. Upload a PNG, SVG, WebP or JPEG on the Needs tab to replace it. If nothing is found, the slide draws a monogram. Layouts are one hero, two brands side by side, or several logos on a ring.
