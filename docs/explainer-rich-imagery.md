# Richer explainer pictures

Christian's note: the explainer looks too flat and generic. The type, the figures and the motion are fine. This is about the pictures on each slide.

Today every frame is the same particle field (rows of dots on `#090c12`) plus the slide HTML Claude wrote: flat colors, crisp shapes, no gradients. That rule is in the slide prompt on purpose, because soft gradients band after YouTube re-encodes. Logos, YouTube clips and the presenter's footage are the only photographs, and only when the user supplies them. Grok Imagine prompts in the script (`grok_imagine_literals.py`, the literal-subject pass) are briefs for those vector scenes. They are not rendered into the explainer. HeyGen is the presenter. No Pexels key is wired into the explainer. Keys the app already knows by name: `XAI_API_KEY` (also `GROK_API_KEY` on the container), `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `HEYGEN_API_KEY`, `HEYGEN_VOICE_ID`, `GOOGLE_API_KEY`, and the `X_*` set.

## Options, ranked by impact against effort

1. **Per-slide literal stills, one art-style preset.** Highest impact on "generic." Each slide gets a 16:9 picture of the thing the narration is actually about (a data-center hall, a hearing table, a price chart), not a rope or a jar. The prompt builder is the one already in `grok_imagine_literals.py`. Render with Grok Imagine (`grok-imagine-image-2.0`, fallback `grok-imagine-image-pro`) through `xai_sdk`, the same client the thumbnail tool uses. License: xAI's API terms. Cost: one image per distinct prompt the first time that slide is shown; the file cache makes the next preview and the 4K render free. Confirm the current per-image price in the xAI console before a long video. Render time: a few seconds per new still, then nothing per frame beyond drawing the image. **Shipped**, behind `visual_style` `rich` and `cinematic`, when a usable key is present.

2. **Grade: grain, vignette, title veil, practical light, and a light shaft.** High impact for very little machinery, and it does not touch the glyphs. The grade is drawn on the background canvas, so card fills and type stay the slide's own pixels. Libraries: none (the runtime canvas, plus a small noise tile from Pillow). License: Pillow is HPND. Cost: $0. Render time: a few extra fills per frame, lost under the cost of the Chrome screenshot. **Shipped** for `rich` (no shaft) and `cinematic` (shaft on).

3. **2.5D parallax / Ken Burns on layered plates.** This is the direct answer to "too 2D." A far plate (sky, blurred), a mid plate (the subject) and a near plate (a sill and a little foreground bokeh) move at different speeds, with a slow zoom. It is a layered fake, not a depth model. Libraries: none. Cost: $0. Render time: up to three `drawImage`s per frame. **Shipped** as `cinematic`. `rich` is the same still as one layer with the Ken Burns move only.

4. **Pexels photo or video plates, blurred and duotoned.** Real photography, fast to drop in. The Pexels license allows commercial use without attribution. There is no Pexels key in the explainer settings today (the b-roll copy only names Pexels as a source). Video plates cost a decode on every frame and fight the "hold the last frame" clip path. Cost of the media: $0 on the free tier, within their rate limit. Not shipped.

5. **Depth Anything (or V2) depth maps, then the same parallax.** More convincing than the fake layers when the still is a real photo. Depth Anything V2 is Apache-2.0. The weights are a download (the small model is tens of MB, the large one much more) and about a second of inference per still. Not shipped; option 3 is the stand-in that needs no model.

6. **Three.js / WebGL scenes.** Real solids, soft shadows, a reflection. Three.js is MIT. Cost: $0. Effort is high: a second scene graph beside the HTML slides, and headless WebGL is the fragile part of a Chrome screenshot pipeline. Not shipped.

7. **Lottie or Rive illustrated motion.** Good for a character or an icon that animates. `lottie-web` is MIT. Rive's web runtime is MIT; authoring is in their editor. It does not make a hearing room or a data center look like a place, which is the gap here. Not shipped.

8. **Generated isometric icons.** Low impact on realism. Icon sets are a mix of MIT, CC, and commercial licenses and would still read as flat graphics next to the type. Not shipped.

## What shipped

`visual_style` on the project, same precedence as `pip_frame` and `bubble`: an explicit choice, then the saved value, then `classic`.

| Style | Pictures |
| --- | --- |
| `classic` (default) | The particle field. Unchanged. |
| `rich` | One cached still per slide, Ken Burns, grain, a dark title veil, a vignette, a warm practical. |
| `cinematic` | The same still split into far / mid / near, plus a light shaft and a stronger grade. |

Switch it in the explainer setup menu ("pictures: classic / rich / cinematic") or on the Presenter tab after a build. The preview reloads. The 4K render uses the same page, so both match. Stills land in `explainer/<id>/imagery/` and are reused. A missing key, a failed call, or bytes that are not an image keep the painted still of that subject. If the whole picture pass throws, the page falls back to the particle field. `EXPLAINER_IMAGERY=paint` skips Grok even when a key is set.

The painted stills are editorial illustrations of the literal subject (Pillow). They are the pictures you get with no key. They are not a stand-in image pretending to be model output.
