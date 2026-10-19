#!/usr/bin/env python3
"""
Emotional Thumbnail Generator for YouTube Videos
Generates 6 variations with different emotional expressions using Google Gemini Flash Image
"""

import os
import re
from io import BytesIO
from pathlib import Path
from datetime import datetime
from PIL import Image

# Lazy import for google.genai (new SDK) - only import when needed
_genai = None
_types = None


def _ensure_genai():
    """Lazy import of google.genai with helpful error message"""
    global _genai, _types
    if _genai is None:
        try:
            from google import genai
            from google.genai import types
            _genai = genai
            _types = types
        except ImportError as e:
            raise ImportError(
                "google-genai package is required for thumbnail generation.\n"
                "Install it with: pip install google-genai\n"
                f"Original error: {e}"
            )
    return _genai, _types


class EmotionalThumbnailGenerator:
    """Generate emotional thumbnail variations using Google Gemini Flash Image"""

    def __init__(self, api_key=None, template_path=None, output_dir=None):
        """
        Initialize the thumbnail generator

        Args:
            api_key: Google API key (defaults to env var GOOGLE_API_KEY)
            template_path: Path to optional template image (if provided, will be used as reference)
            output_dir: Output directory for thumbnails (defaults to ~/Dev/Thumbnails)
        """
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY", "")

        # Template is optional - if provided and exists, use it
        self.template_path = None
        if template_path and Path(template_path).exists():
            self.template_path = template_path
        else:
            # Check default location but don't fail if missing
            current_dir = Path(__file__).parent
            default_template = current_dir / "Thumbnail_Template_Canva.png"
            if default_template.exists():
                self.template_path = str(default_template)

        self.output_dir = Path(
            output_dir or os.path.expanduser("~/Dev/Thumbnails"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Configure Gemini API (lazy import, new SDK)
        genai, types = _ensure_genai()
        self.client = genai.Client(api_key=self.api_key)
        self.model_name = 'gemini-2.5-flash-image'

    def extract_thumbnail_text_from_upload_details(self, upload_details):
        """
        Extract thumbnail text suggestions from YouTube upload details

        Args:
            upload_details: String containing YouTube upload details markdown

        Returns:
            String with primary thumbnail text suggestion, or None
        """
        if not upload_details:
            return None

        # Look for thumbnail text section
        thumbnail_section = re.search(
            r'## 🖼️ THUMBNAIL TEXT\s*\n(.*?)(?=\n##|\Z)',
            upload_details,
            re.DOTALL | re.IGNORECASE
        )

        if thumbnail_section:
            text = thumbnail_section.group(1).strip()
            # Extract first suggestion (usually the most prominent)
            lines = [line.strip() for line in text.split(
                '\n') if line.strip() and not line.strip().startswith('-')]
            if lines:
                # Clean up formatting
                suggestion = lines[0].strip('"').strip("'").strip()
                return suggestion

        return None

    def generate_emotional_variations(self, base_text=None):
        """
        Generate 6 emotional variation configurations

        Args:
            base_text: Optional base text to derive emotions from

        Returns:
            List of dicts with emotion configs
        """
        variations = [
            {
                "emotion": "ANGRY/FRUSTRATED",
                "thumbnail_text": "THIS IS RIDICULOUS!" if not base_text else f"{base_text.upper()}!",
                "expression": "angry and frustrated, furrowed brows, intense stare",
                "mood": "confrontational and challenging",
                "outfit": "black leather jacket with edgy accessories",
                "background": "Dark industrial setting with dramatic red lighting and steam"
            },
            {
                "emotion": "SHOCKED/SURPRISED",
                "thumbnail_text": "WAIT... WHAT?!" if not base_text else f"WAIT... {base_text.upper()}?!",
                "expression": "shocked and surprised, wide eyes, mouth open",
                "mood": "disbelief and amazement",
                "outfit": "trendy oversized blazer with modern streetwear",
                "background": "Bright modern office with holographic displays and bright blue tones"
            },
            {
                "emotion": "SCARED/WORRIED",
                "thumbnail_text": "YOU'RE IN DANGER" if not base_text else f"{base_text.upper()} - DANGER!",
                "expression": "concerned and worried, raised eyebrows, serious look",
                "mood": "warning and urgency",
                "outfit": "tactical vest with streetwear elements",
                "background": "Moody purple-blue cyberpunk cityscape with neon signs"
            },
            {
                "emotion": "EXCITED/ENERGETIC",
                "thumbnail_text": "THIS CHANGES EVERYTHING!" if not base_text else f"{base_text.upper()} IS HERE!",
                "expression": "excited and energetic, wide smile, enthusiastic",
                "mood": "enthusiasm and breakthrough",
                "outfit": "vibrant current fashion with bold colorful patterns",
                "background": "Bright futuristic laboratory with green and yellow lighting"
            },
            {
                "emotion": "SKEPTICAL/DOUBTFUL",
                "thumbnail_text": "I DON'T BELIEVE IT" if not base_text else f"IS {base_text.upper()} REAL?",
                "expression": "skeptical and doubtful, raised eyebrow, smirk",
                "mood": "questioning and analytical",
                "outfit": "chic contemporary designer outfit",
                "background": "Sleek minimalist tech studio with cool teal tones"
            },
            {
                "emotion": "DETERMINED/INTENSE",
                "thumbnail_text": "HERE'S THE TRUTH" if not base_text else f"{base_text.upper()} - THE TRUTH",
                "expression": "determined and intense, direct eye contact, serious",
                "mood": "authoritative and confident",
                "outfit": "dark tactical futuristic gear",
                "background": "Dramatic server room with green matrix-style lighting"
            }
        ]

        return variations

    def _render_text_overlay(self, img, text):
        """Render bold hook text onto the upper-left area of a thumbnail image."""
        from PIL import ImageDraw, ImageFont

        draw = ImageDraw.Draw(img)
        w, h = img.size  # 1280x720

        # Try to load a bold system font
        font_size = 72
        font = None
        candidates = [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        for path in candidates:
            if Path(path).exists():
                try:
                    font = ImageFont.truetype(path, font_size)
                    break
                except Exception:
                    pass
        if font is None:
            # Scale up the default font as a last resort
            font = ImageFont.load_default()

        # Word-wrap to fit left ~55% of frame width
        max_text_w = int(w * 0.55)
        lines = []
        words = text.split()
        current = []
        for word in words:
            test = ' '.join(current + [word])
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] > max_text_w and current:
                lines.append(' '.join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            lines.append(' '.join(current))

        # Draw each line with thick black stroke + white fill
        padding = 50
        y = padding
        for line in lines:
            draw.text(
                (padding, y), line,
                font=font, fill='white',
                stroke_width=5, stroke_fill='black'
            )
            lh = draw.textbbox((0, 0), line, font=font)[3]
            y += lh + 10

        return img

    def generate_thumbnail_variation(self, script_title, emotion_data, variation_num):
        """
        Generate a single thumbnail variation

        Args:
            script_title: Title/topic of the video script
            emotion_data: Dict with emotion, expression, outfit, background info
            variation_num: Variation number (1-6)

        Returns:
            PIL Image object or None on failure
        """
        # Check if we have a template image to use as reference
        has_template = self.template_path and Path(self.template_path).exists()

        hook_text = emotion_data.get('thumbnail_text', '').strip()

        if has_template:
            template_img = Image.open(self.template_path)
            prompt = f"""You are modifying a YouTube thumbnail template image (1280x720 aspect ratio).

TEMPLATE IMAGE PROVIDED: This image shows a person in a specific pose.

WHAT TO TRANSFORM:
1. BACKGROUND: Replace background with: {emotion_data['background']}
2. FACIAL EXPRESSION: {emotion_data['expression']} conveying {emotion_data['mood']}
3. OUTFIT: Change clothing to: {emotion_data['outfit']}

Topic: {script_title}
Emotion: {emotion_data['emotion']}

TEXT REQUIREMENT (MANDATORY):
- Add this exact headline text in the UPPER LEFT area of the image:
  "{hook_text}"
- Style: large bold white letters with thick black drop-shadow/stroke
- Font size: very large (fills roughly the left 55% of the frame width)
- Place text starting at the upper-left corner with padding
- The text must be clearly legible against any background

Keep the person's pose and position. Fill background edge-to-edge (1280x720).
High resolution, photorealistic, YouTube thumbnail optimized."""
        else:
            prompt = f"""Generate a professional YouTube thumbnail image (1280x720 aspect ratio, 16:9).

SCENE DESCRIPTION:
- A person (content creator / YouTuber) positioned on the RIGHT side of the frame
- The person should be from chest up, facing the camera
- Facial expression: {emotion_data['expression']}
- The expression must convey: {emotion_data['mood']}
- Emotion: {emotion_data['emotion']}
- Outfit: {emotion_data['outfit']}

BACKGROUND:
- Topic: {script_title}
- Specific scene: {emotion_data['background']}
- Background fills the ENTIRE frame edge-to-edge
- Vibrant, high-contrast colors for thumbnail visibility

COLOR PALETTE:
- ANGRY: Reds, oranges, dark dramatic
- SHOCKED: Bright blues, whites, high contrast
- SCARED: Dark blues, purples, moody
- EXCITED: Vibrant yellows, greens, energetic
- SKEPTICAL: Cool grays, teals, modern
- DETERMINED: Deep reds, blacks, powerful

TEXT REQUIREMENT (MANDATORY):
- Add this exact headline text in the UPPER LEFT area of the image:
  "{hook_text}"
- Style: large bold white letters with thick black drop-shadow/stroke
- Font size: very large (fills roughly the left 55% of the frame width)
- Place text starting at the upper-left corner with ~50px padding
- Word-wrap to stay within the left 55% of the frame
- The text must be clearly legible against the background

CRITICAL RULES:
- 1280x720 pixels, 16:9 aspect ratio
- Photorealistic, high resolution
- High visual impact, professional YouTube thumbnail quality
- Person takes up roughly 40% of right side of frame
- Background extends to all edges with no gaps or white space"""

        try:
            _, types = _ensure_genai()

            contents = [prompt]
            if has_template:
                template_bytes = BytesIO()
                template_img.save(template_bytes, format='PNG')
                template_bytes.seek(0)
                contents.append(Image.open(BytesIO(template_bytes.getvalue())))

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"]
                )
            )

            # Extract image from response (new SDK format)
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                        img = Image.open(BytesIO(part.inline_data.data))

                        # Ensure correct dimensions
                        if img.size != (1280, 720):
                            img = img.resize(
                                (1280, 720), Image.Resampling.LANCZOS)

                        return img

            print(
                f"⚠️ No image data in response for variation {variation_num}")
            return None

        except Exception as e:
            print(f"❌ Error generating variation {variation_num}: {e}")
            return None

    def generate_all_thumbnails(self, script_title, script_content=None, youtube_upload_details=None,
                                headline_text=None, headline_options=None,
                                progress_callback=None, cancel_check=None,
                                variations_per_option=None):
        """
        Generate all thumbnail variations (6 per headline option).

        Args:
            script_title: Title/topic of the video
            script_content: Optional script content for context
            youtube_upload_details: Optional YouTube upload details with thumbnail text
            headline_text: Override headline text (used as base_text if headline_options not given)
            headline_options: List of headline text strings; generates 6 variations per option
            progress_callback: Optional callable(msg: str) for progress updates
            cancel_check: Optional callable() -> bool; returns True to stop generation

        Returns:
            Dict with variation info, file paths, and optional 'cancelled' / 'error' keys
        """
        def _notify(msg):
            if progress_callback:
                try:
                    progress_callback(msg)
                except Exception:
                    pass

        def _is_cancelled():
            if cancel_check:
                try:
                    return cancel_check()
                except Exception:
                    pass
            return False

        # Determine the list of headline options to iterate over
        if headline_options:
            options_list = headline_options[:3]  # max 3
        elif headline_text:
            options_list = [headline_text]
        elif youtube_upload_details:
            extracted = self.extract_thumbnail_text_from_upload_details(
                youtube_upload_details)
            options_list = [extracted] if extracted else [None]
        else:
            options_list = [None]

        # Create safe filename base
        safe_title = re.sub(
            r'[^\w\s-]', '', script_title).strip().replace(' ', '_')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        results = {
            "script_title": script_title,
            "variations": [],
            "output_dir": str(self.output_dir),
            "total_attempted": 0,
            "cancelled": False,
        }

        per_option = variations_per_option if variations_per_option and variations_per_option > 0 else 6
        total_expected = per_option * len(options_list)
        generated_count = 0

        print(f"\n{'='*70}")
        print(
            f"🎬 Generating {total_expected} Emotional Thumbnails: '{script_title}'")
        print(
            f"📸 Template: {self.template_path or 'None (generating from scratch)'}")
        print(f"{'='*70}\n")

        for opt_idx, base_text in enumerate(options_list, 1):
            if _is_cancelled():
                results["cancelled"] = True
                _notify(
                    f"🛑 Thumbnail generation cancelled after {generated_count}/{total_expected}")
                break

            if base_text:
                print(f"💬 Option {opt_idx}/{len(options_list)}: {base_text}")

            variations = self.generate_emotional_variations(base_text)[
                :per_option]

            for i, emotion_data in enumerate(variations, 1):
                if _is_cancelled():
                    results["cancelled"] = True
                    _notify(
                        f"🛑 Thumbnail generation cancelled after {generated_count}/{total_expected}")
                    break

                global_num = (opt_idx - 1) * per_option + i
                results["total_attempted"] += 1

                _notify(
                    f"🎭 Generating thumbnail {global_num}/{total_expected}: {emotion_data['emotion']}")
                print(f"{'─'*70}")
                print(f"🎭 Variation #{global_num} — {emotion_data['emotion']}")
                print(f"   Text: {emotion_data['thumbnail_text']}")

                img = self.generate_thumbnail_variation(
                    script_title, emotion_data, global_num)

                if img:
                    filename = f"{safe_title}_opt{opt_idx}_v{i}_{timestamp}.png"
                    filepath = self.output_dir / filename
                    img.save(filepath, "PNG", quality=95)
                    generated_count += 1

                    print(f"   ✅ Generated: {img.size}")
                    print(f"   💾 Saved: {filename}\n")

                    results["variations"].append({
                        "number": global_num,
                        "option_index": opt_idx,
                        "headline_text": base_text,
                        "emotion": emotion_data['emotion'],
                        "text": emotion_data['thumbnail_text'],
                        "expression": emotion_data['expression'],
                        "outfit": emotion_data['outfit'],
                        "background": emotion_data['background'],
                        "filename": filename,
                        "filepath": str(filepath),
                        "dimensions": img.size,
                    })
                else:
                    print(f"   ❌ Failed to generate\n")

            if results["cancelled"]:
                break

        return results

    def display_summary(self, results):
        """Display a summary of generated thumbnails"""
        print(f"\n{'='*70}")
        print(f"✅ EMOTIONAL THUMBNAIL GENERATION COMPLETE")
        print(f"{'='*70}\n")
        print(f"📁 Output Directory: {results['output_dir']}\n")

        if results.get('base_text'):
            print(f"💬 Base Text Used: {results['base_text']}\n")

        for var in results['variations']:
            print(f"{'─'*70}")
            print(f"🎭 Variation #{var['number']}: {var['emotion']}")
            print(f"   Text: {var['text']}")
            print(
                f"   Dimensions: {var['dimensions'][0]}x{var['dimensions'][1]}")
            print(f"   File: {var['filename']}")

        print(f"{'─'*70}\n")
        print(f"💡 Next Steps:")
        print(f"   1. Review thumbnails - person should have transformed expressions")
        print(f"   2. Open in Canva to add text overlay on LEFT side")
        print(f"   3. Use the suggested text for each variation")
        print(f"   4. Export final thumbnails")


def main():
    """Test harness for standalone usage"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate emotional thumbnail variations using Google Gemini"
    )
    parser.add_argument(
        "--template",
        default="tools/media/thumbnail_template_canva.png",
        help="Path to template image"
    )
    parser.add_argument(
        "--script",
        help="Path to script markdown file"
    )
    parser.add_argument(
        "--title",
        required=True,
        help="Video title/topic"
    )
    parser.add_argument(
        "--youtube-details",
        help="Path to YouTube upload details file"
    )
    parser.add_argument(
        "--output",
        help="Output directory for thumbnails"
    )

    args = parser.parse_args()

    # Load script content if provided
    script_content = None
    if args.script:
        with open(args.script, 'r', encoding='utf-8') as f:
            script_content = f.read()

    # Load YouTube details if provided
    youtube_details = None
    if args.youtube_details:
        with open(args.youtube_details, 'r', encoding='utf-8') as f:
            youtube_details = f.read()

    # Create generator
    generator = EmotionalThumbnailGenerator(
        template_path=args.template,
        output_dir=args.output
    )

    # Generate thumbnails
    results = generator.generate_all_thumbnails(
        script_title=args.title,
        script_content=script_content,
        youtube_upload_details=youtube_details
    )

    # Display summary
    generator.display_summary(results)


if __name__ == "__main__":
    main()
