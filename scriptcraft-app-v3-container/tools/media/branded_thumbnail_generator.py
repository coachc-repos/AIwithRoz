#!/usr/bin/env python3
"""
Branded Thumbnail Generator with Roz's Photo
Creates professional YouTube thumbnails using Roz's headshot as the base
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
from typing import Dict, Tuple, Optional
import textwrap

# Add LineDrive to path for imports
sys.path.append(str(Path(__file__).parent))


class BrandedThumbnailGenerator:
    """Generate branded thumbnails using Roz's professional headshot"""

    def __init__(self, base_photo_path: str = None):
        self.output_dir = Path.home() / "Dev/Videos/Thumbnails/Branded"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Set the base photo path
        self.base_photo_path = base_photo_path
        if not base_photo_path:
            # Look for the photo in common locations
            possible_paths = [
                Path(__file__).parent / "roz_headshot.jpg",
                Path(__file__).parent / "roz_photo.jpg",
                Path(__file__).parent / "headshot.jpg",
                Path.home() / "Dev/Videos/Thumbnails/roz_headshot.jpg",
            ]

            for path in possible_paths:
                if path.exists():
                    self.base_photo_path = str(path)
                    break

        # Thumbnail dimensions (YouTube optimized)
        self.youtube_size = (1280, 720)
        self.social_size = (1200, 628)

        # Brand colors - Simplified for large white text focus
        self.brand_colors = {
            "primary": "#1a1a1a",  # Dark background
            "accent": "#333333",  # Slightly lighter dark
            "highlight": "#555555",  # Medium gray for subtle accents
            "text_white": "#ffffff",  # Large white text (primary)
            "overlay_light": (255, 255, 255, 200),  # Strong white overlay
            "overlay_dark": (0, 0, 0, 150),  # Dark overlay for contrast
        }

    def save_base_photo(self, image_data: bytes) -> str:
        """Save the provided image data as the base photo"""
        base_photo_path = self.output_dir.parent / "roz_headshot.jpg"

        with open(base_photo_path, "wb") as f:
            f.write(image_data)

        self.base_photo_path = str(base_photo_path)
        print(f"✅ Base photo saved: {base_photo_path}")
        return str(base_photo_path)

    def is_photo_available(self) -> bool:
        """Check if the base photo is available"""
        return self.base_photo_path and Path(self.base_photo_path).exists()

    def get_fonts(self) -> Dict[str, ImageFont.FreeTypeFont]:
        """Get fonts for different text elements"""
        fonts = {}

        # Try to load system fonts
        font_paths = [
            "/System/Library/Fonts/Arial Bold.ttf",  # macOS
            "/System/Library/Fonts/Helvetica.ttc",  # macOS
            "/usr/share/fonts/truetype/dejavu/DejaVu-Sans-Bold.ttf",  # Linux
            "C:/Windows/Fonts/ariblk.ttf",  # Windows
        ]

        try:
            for font_path in font_paths:
                if os.path.exists(font_path):
                    fonts["title"] = ImageFont.truetype(font_path, 96)
                    fonts["subtitle"] = ImageFont.truetype(font_path, 56)
                    fonts["brand"] = ImageFont.truetype(font_path, 48)
                    break
            else:
                # Fallback to default fonts
                fonts["title"] = ImageFont.load_default()
                fonts["subtitle"] = ImageFont.load_default()
                fonts["brand"] = ImageFont.load_default()
        except Exception:
            fonts["title"] = ImageFont.load_default()
            fonts["subtitle"] = ImageFont.load_default()
            fonts["brand"] = ImageFont.load_default()

        return fonts

    def add_simple_white_text(
        self,
        draw: ImageDraw.Draw,
        text: str,
        position: Tuple[int, int],
        font: ImageFont.FreeTypeFont,
    ) -> None:
        """Add simple large white text without outlines"""
        draw.text(position, text, font=font, fill="white")

    def create_branded_thumbnail(
        self, title: str, style: str = "professional", thumbnail_type: str = "youtube"
    ) -> Optional[str]:
        """Create a branded thumbnail using Roz's photo"""

        if not self.is_photo_available():
            print("❌ Base photo not available for branded thumbnail")
            return None

        # Choose size based on type
        if thumbnail_type == "social":
            canvas_size = self.social_size
        else:
            canvas_size = self.youtube_size

        try:
            # Load and prepare the base photo
            base_photo = Image.open(self.base_photo_path)

            # Create canvas
            canvas = Image.new("RGB", canvas_size, color="white")

            if style == "professional":
                canvas = self._create_professional_style(
                    canvas, base_photo, title, canvas_size
                )
            elif style == "split":
                canvas = self._create_split_style(
                    canvas, base_photo, title, canvas_size
                )
            elif style == "overlay":
                canvas = self._create_overlay_style(
                    canvas, base_photo, title, canvas_size
                )
            else:
                canvas = self._create_professional_style(
                    canvas, base_photo, title, canvas_size
                )

            # Save thumbnail
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = "".join(
                c for c in title if c.isalnum() or c in (" ", "-", "_")
            ).strip()
            safe_title = safe_title.replace(" ", "_")[:40]
            filename = f"{safe_title}_{style}_{thumbnail_type}_{timestamp}.png"
            filepath = self.output_dir / filename

            canvas.save(filepath, quality=95)
            print(f"📸 Branded thumbnail saved: {filepath}")

            return str(filepath)

        except Exception as e:
            print(f"❌ Error creating branded thumbnail: {e}")
            return None

    def _create_professional_style(
        self,
        canvas: Image.Image,
        photo: Image.Image,
        title: str,
        canvas_size: Tuple[int, int],
    ) -> Image.Image:
        """Create professional style thumbnail with photo on right, text on left"""

        # Make photo more prominent - 50% of canvas width instead of 40%
        photo_width = int(canvas_size[0] * 0.5)
        photo_height = canvas_size[1]

        # Crop photo to square first if needed (focus on face)
        original_width, original_height = photo.size
        min_dimension = min(original_width, original_height)

        # Crop to center square
        left = (original_width - min_dimension) // 2
        top = (original_height - min_dimension) // 2
        right = left + min_dimension
        bottom = top + min_dimension

        photo_square = photo.crop((left, top, right, bottom))

        # Resize to fit thumbnail with sharp focus on face
        photo_resized = photo_square.resize(
            (photo_width, photo_height), Image.Resampling.LANCZOS
        )

        # Create simple dark background for text area for maximum contrast
        text_area_width = canvas_size[0] - photo_width

        # Use solid dark background for maximum text readability
        dark_bg = Image.new(
            "RGB", (text_area_width, canvas_size[1]), color=(26, 26, 26)
        )  # Very dark background

        # Paste dark background and prominent photo onto canvas
        canvas.paste(dark_bg, (0, 0))
        canvas.paste(photo_resized, (text_area_width, 0))

        # Add text
        draw = ImageDraw.Draw(canvas)
        fonts = self.get_fonts()

        # Split title into lines
        max_width = text_area_width - 60  # padding
        words = title.split()
        lines = []
        current_line = []

        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=fonts["title"])
            if bbox[2] - bbox[0] <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)

        if current_line:
            lines.append(" ".join(current_line))

        # Position and draw title with larger spacing for bigger fonts
        total_text_height = len(lines) * 110  # Increased spacing for larger text
        start_y = (canvas_size[1] - total_text_height) // 2 - 40

        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=fonts["title"])
            text_width = bbox[2] - bbox[0]
            x = (text_area_width - text_width) // 2
            y = start_y + (i * 110)  # Increased line spacing

            # Use simple large white text without outlines as requested
            self.add_simple_white_text(draw, line, (x, y), fonts["title"])

        # Add "AI with Roz" branding - also simple white text
        brand_text = "AI with Roz"
        brand_y = start_y + total_text_height + 50
        bbox = draw.textbbox((0, 0), brand_text, font=fonts["brand"])
        brand_width = bbox[2] - bbox[0]
        brand_x = (text_area_width - brand_width) // 2

        # Brand text also simple white
        self.add_simple_white_text(draw, brand_text, (brand_x, brand_y), fonts["brand"])

        return canvas

    def _create_split_style(
        self,
        canvas: Image.Image,
        photo: Image.Image,
        title: str,
        canvas_size: Tuple[int, int],
    ) -> Image.Image:
        """Create split style with photo taking full height on left"""

        # Photo takes left 35% of canvas
        photo_width = int(canvas_size[0] * 0.35)
        photo_height = canvas_size[1]

        # Resize photo to fit left side
        photo_resized = photo.resize(
            (photo_width, photo_height), Image.Resampling.LANCZOS
        )

        # Create background for right side
        right_width = canvas_size[0] - photo_width
        background = Image.new(
            "RGB",
            (right_width, canvas_size[1]),
            color=tuple(
                int(self.brand_colors["primary"][i : i + 2], 16) for i in (1, 3, 5)
            ),
        )

        # Paste photo and background
        canvas.paste(photo_resized, (0, 0))
        canvas.paste(background, (photo_width, 0))

        # Add decorative elements
        draw = ImageDraw.Draw(canvas)

        # Add a diagonal accent
        accent_color = tuple(
            int(self.brand_colors["accent"][i : i + 2], 16) for i in (1, 3, 5)
        )
        for i in range(20):
            draw.line(
                [(photo_width - 10 + i, 0), (photo_width - 10 + i, canvas_size[1])],
                fill=accent_color,
                width=1,
            )

        # Add title text on right side
        fonts = self.get_fonts()
        max_width = right_width - 80

        # Wrap title text
        words = title.split()
        lines = []
        current_line = []

        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=fonts["title"])
            if bbox[2] - bbox[0] <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)

        if current_line:
            lines.append(" ".join(current_line))

        # Center text vertically
        total_height = len(lines) * 85
        start_y = (canvas_size[1] - total_height) // 2

        for i, line in enumerate(lines):
            y = start_y + (i * 85)
            x = photo_width + 40

            # Use simple white text without outlines
            self.add_simple_white_text(draw, line, (x, y), fonts["title"])

        # Add branding at bottom - also simple white text
        brand_text = "AI with Roz"
        brand_x = photo_width + 40
        brand_y = canvas_size[1] - 60

        self.add_simple_white_text(draw, brand_text, (brand_x, brand_y), fonts["brand"])

        return canvas

    def _create_overlay_style(
        self,
        canvas: Image.Image,
        photo: Image.Image,
        title: str,
        canvas_size: Tuple[int, int],
    ) -> Image.Image:
        """Create overlay style with photo as background and text overlaid"""

        # Resize photo to cover entire canvas
        photo_resized = photo.resize(canvas_size, Image.Resampling.LANCZOS)

        # Apply slight blur for text readability
        photo_blurred = photo_resized.filter(ImageFilter.GaussianBlur(radius=1))

        # Create overlay for better text visibility
        overlay = Image.new("RGBA", canvas_size, (0, 0, 0, 140))

        # Composite photo with overlay
        canvas.paste(photo_blurred, (0, 0))
        canvas = canvas.convert("RGBA")
        canvas = Image.alpha_composite(canvas, overlay)
        canvas = canvas.convert("RGB")

        # Add text
        draw = ImageDraw.Draw(canvas)
        fonts = self.get_fonts()

        # Create title with word wrapping
        max_width = canvas_size[0] - 100
        words = title.split()
        lines = []
        current_line = []

        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=fonts["title"])
            if bbox[2] - bbox[0] <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)

        if current_line:
            lines.append(" ".join(current_line))

        # Position title in center
        total_height = len(lines) * 90
        start_y = (canvas_size[1] - total_height) // 2

        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=fonts["title"])
            text_width = bbox[2] - bbox[0]
            x = (canvas_size[0] - text_width) // 2
            y = start_y + (i * 90)

            # Simple white text for clean look
            self.add_simple_white_text(draw, line, (x, y), fonts["title"])

        # Add branding - also simple white text
        brand_text = "AI with Roz"
        bbox = draw.textbbox((0, 0), brand_text, font=fonts["brand"])
        brand_width = bbox[2] - bbox[0]
        brand_x = (canvas_size[0] - brand_width) // 2
        brand_y = start_y + total_height + 50

        self.add_simple_white_text(draw, brand_text, (brand_x, brand_y), fonts["brand"])

        return canvas

    def create_all_branded_thumbnails(self, title: str) -> Dict[str, str]:
        """Create all branded thumbnail variations"""
        print(f"\n🎨 BRANDED THUMBNAIL GENERATION")
        print("=" * 60)
        print(f"📝 Title: {title}")

        if not self.is_photo_available():
            print("❌ Base photo not available!")
            return {}

        results = {}

        styles = [
            ("professional", "Professional split layout"),
            ("split", "Full-height split design"),
            ("overlay", "Photo background with text overlay"),
        ]

        types = [("youtube", "YouTube"), ("social", "Social Media")]

        for style, style_desc in styles:
            print(f"\n🎯 Creating {style_desc}...")

            for thumb_type, type_desc in types:
                try:
                    thumbnail_path = self.create_branded_thumbnail(
                        title, style, thumb_type
                    )
                    if thumbnail_path:
                        key = f"{thumb_type}_{style}"
                        results[key] = thumbnail_path
                        print(f"   ✅ {type_desc} {style} thumbnail created")
                    else:
                        print(f"   ❌ {type_desc} {style} thumbnail failed")

                except Exception as e:
                    print(f"   ❌ Error creating {type_desc} {style}: {e}")

        print(f"\n✅ Generated {len(results)} branded thumbnails")
        return results

    def create_dalle_stylized_thumbnail(
        self, title: str, thumbnail_type: str = "youtube"
    ) -> Optional[str]:
        """Create DALL-E stylized thumbnail with profile photo integration"""

        if not self.is_photo_available():
            print("❌ Base photo not available for DALL-E thumbnail")
            return None

        try:
            from linedrive_azure.agents.azure_image_generator_client import (
                AzureImageGenerator,
            )

            # Create AI image generator
            image_gen = AzureImageGenerator()

            # Create enhanced prompt for stylized background with person
            prompt = f"""Professional YouTube thumbnail with a stylized background for '{title}'. 
            Create a dynamic, eye-catching background with modern design elements, 
            suitable for overlaying with a professional headshot photo and large white text. 
            The background should be:
            - High contrast and visually engaging
            - Professional tech/AI themed
            - Suitable for a YouTube thumbnail (1280x720)
            - Leave space for text overlay and profile photo
            - Modern gradient or geometric patterns
            - Colors that complement white text
            Style: Professional, modern, high-energy, suitable for educational content"""

            print(f"🎨 Generating DALL-E stylized background for: {title}")

            # Generate the background image
            result = image_gen.generate_image(
                prompt=prompt, size="1024x1024"  # DALL-E 3 standard size
            )

            if not result or not result.get("success"):
                print(
                    "❌ DALL-E deployment not available - falling back to gradient background"
                )
                return self._create_fallback_stylized_thumbnail(title, thumbnail_type)

            image_url = result.get("image_url")
            if not image_url:
                print("❌ No image URL in DALL-E response")
                return None

            # Download and process the generated background
            import requests
            from PIL import Image as PILImage
            import io

            response = requests.get(image_url, timeout=30)
            if response.status_code != 200:
                print(f"❌ Failed to download generated image: {response.status_code}")
                return None

            # Load the generated background
            bg_image = PILImage.open(io.BytesIO(response.content))

            # Choose size based on type
            if thumbnail_type == "social":
                canvas_size = self.social_size
            else:
                canvas_size = self.youtube_size

            # Resize background to fit canvas
            bg_resized = bg_image.resize(canvas_size, PILImage.Resampling.LANCZOS)

            # Load and prepare profile photo
            profile_photo = PILImage.open(self.base_photo_path)

            # Create circular mask for profile photo
            profile_size = min(
                canvas_size[0] // 4, canvas_size[1] // 2
            )  # Reasonable size
            profile_resized = profile_photo.resize(
                (profile_size, profile_size), PILImage.Resampling.LANCZOS
            )

            # Create circular mask
            mask = PILImage.new("L", (profile_size, profile_size), 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.ellipse((0, 0, profile_size, profile_size), fill=255)

            # Apply circular mask to profile photo
            profile_circle = PILImage.new(
                "RGBA", (profile_size, profile_size), (0, 0, 0, 0)
            )
            profile_circle.paste(profile_resized, (0, 0))
            profile_circle.putalpha(mask)

            # Paste circular profile photo onto background (top-right corner)
            photo_x = canvas_size[0] - profile_size - 30
            photo_y = 30

            # Convert background to RGBA for blending
            if bg_resized.mode != "RGBA":
                bg_resized = bg_resized.convert("RGBA")

            bg_resized.paste(profile_circle, (photo_x, photo_y), profile_circle)

            # Convert back to RGB for final image
            final_canvas = PILImage.new("RGB", canvas_size, "white")
            final_canvas.paste(bg_resized, (0, 0))

            # Add large white text without outlines
            draw = ImageDraw.Draw(final_canvas)
            fonts = self.get_fonts()

            # Split title into lines for better fit
            words = title.split()
            lines = []
            current_line = []
            max_width = (
                canvas_size[0] - profile_size - 80
            )  # Account for profile photo and padding

            for word in words:
                test_line = " ".join(current_line + [word])
                bbox = draw.textbbox((0, 0), test_line, font=fonts["title"])
                if bbox[2] - bbox[0] <= max_width:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(" ".join(current_line))
                        current_line = [word]
                    else:
                        lines.append(word)

            if current_line:
                lines.append(" ".join(current_line))

            # Position title text (left side, avoiding profile photo area)
            line_height = 110
            total_text_height = len(lines) * line_height
            start_y = (canvas_size[1] - total_text_height) // 2

            for i, line in enumerate(lines):
                y = start_y + (i * line_height)
                # Simple large white text - no outlines as requested
                draw.text((40, y), line, font=fonts["title"], fill="white")

            # Add "AI with Roz" branding - also simple white text
            brand_text = "AI with Roz"
            brand_y = start_y + total_text_height + 30
            draw.text((40, brand_y), brand_text, font=fonts["brand"], fill="white")

            # Save the final thumbnail
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = "".join(
                c for c in title if c.isalnum() or c in (" ", "-", "_")
            ).strip()
            safe_title = safe_title.replace(" ", "_")[:40]
            filename = f"{safe_title}_dalle_stylized_{thumbnail_type}_{timestamp}.png"
            filepath = self.output_dir / filename

            final_canvas.save(filepath, quality=95)
            print(f"📸 DALL-E stylized thumbnail saved: {filepath}")

            return str(filepath)

        except ImportError:
            print("⚠️ Azure Image Generator not available - using gradient fallback")
            return self._create_fallback_stylized_thumbnail(title, thumbnail_type)
        except Exception as e:
            print(f"❌ Error creating DALL-E stylized thumbnail: {e}")
            print("🔄 Falling back to gradient background...")
            return self._create_fallback_stylized_thumbnail(title, thumbnail_type)

    def _create_fallback_stylized_thumbnail(
        self, title: str, thumbnail_type: str = "youtube"
    ) -> Optional[str]:
        """Create stylized thumbnail with gradient background when DALL-E unavailable"""

        try:
            from PIL import Image as PILImage, ImageDraw, ImageFilter
            import colorsys

            # Choose size based on type
            if thumbnail_type == "social":
                canvas_size = self.social_size
            else:
                canvas_size = self.youtube_size

            # Create gradient background
            gradient_bg = self._create_modern_gradient_background(canvas_size)

            # Load and prepare profile photo
            profile_photo = PILImage.open(self.base_photo_path)

            # Create circular mask for profile photo
            profile_size = min(canvas_size[0] // 4, canvas_size[1] // 2)
            profile_resized = profile_photo.resize(
                (profile_size, profile_size), PILImage.Resampling.LANCZOS
            )

            # Create circular mask
            mask = PILImage.new("L", (profile_size, profile_size), 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.ellipse((0, 0, profile_size, profile_size), fill=255)

            # Apply circular mask to profile photo
            profile_circle = PILImage.new(
                "RGBA", (profile_size, profile_size), (0, 0, 0, 0)
            )
            profile_circle.paste(profile_resized, (0, 0))
            profile_circle.putalpha(mask)

            # Add subtle glow effect to profile photo
            glow_size = profile_size + 20
            glow = PILImage.new("RGBA", (glow_size, glow_size), (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(glow)
            glow_draw.ellipse((0, 0, glow_size, glow_size), fill=(255, 255, 255, 30))
            glow = glow.filter(ImageFilter.GaussianBlur(radius=10))

            # Paste glow and profile onto gradient background
            photo_x = canvas_size[0] - profile_size - 40
            photo_y = 30
            glow_x = photo_x - 10
            glow_y = photo_y - 10

            # Convert gradient to RGBA for blending
            if gradient_bg.mode != "RGBA":
                gradient_bg = gradient_bg.convert("RGBA")

            gradient_bg.paste(glow, (glow_x, glow_y), glow)
            gradient_bg.paste(profile_circle, (photo_x, photo_y), profile_circle)

            # Convert back to RGB for final image
            final_canvas = PILImage.new("RGB", canvas_size, "white")
            final_canvas.paste(gradient_bg, (0, 0))

            # Add large white text without outlines
            draw = ImageDraw.Draw(final_canvas)
            fonts = self.get_fonts()

            # Split title into lines for better fit
            words = title.split()
            lines = []
            current_line = []
            max_width = canvas_size[0] - profile_size - 100

            for word in words:
                test_line = " ".join(current_line + [word])
                bbox = draw.textbbox((0, 0), test_line, font=fonts["title"])
                if bbox[2] - bbox[0] <= max_width:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(" ".join(current_line))
                        current_line = [word]
                    else:
                        lines.append(word)

            if current_line:
                lines.append(" ".join(current_line))

            # Position title text with subtle shadow for better readability
            line_height = 110
            total_text_height = len(lines) * line_height
            start_y = (canvas_size[1] - total_text_height) // 2

            for i, line in enumerate(lines):
                y = start_y + (i * line_height)

                # Add subtle shadow for better readability
                shadow_offset = 3
                draw.text(
                    (43, y + shadow_offset),
                    line,
                    font=fonts["title"],
                    fill=(0, 0, 0, 60),
                )  # Semi-transparent shadow

                # Main white text
                draw.text((40, y), line, font=fonts["title"], fill="white")

            # Add "AI with Roz" branding
            brand_text = "AI with Roz"
            brand_y = start_y + total_text_height + 30

            # Brand shadow
            draw.text(
                (43, brand_y + 2), brand_text, font=fonts["brand"], fill=(0, 0, 0, 60)
            )
            # Brand text
            draw.text((40, brand_y), brand_text, font=fonts["brand"], fill="white")

            # Save the final thumbnail
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = "".join(
                c for c in title if c.isalnum() or c in (" ", "-", "_")
            ).strip()
            safe_title = safe_title.replace(" ", "_")[:40]
            filename = (
                f"{safe_title}_stylized_gradient_{thumbnail_type}_{timestamp}.png"
            )
            filepath = self.output_dir / filename

            final_canvas.save(filepath, quality=95)
            print(f"📸 Stylized gradient thumbnail saved: {filepath}")

            return str(filepath)

        except Exception as e:
            print(f"❌ Error creating fallback stylized thumbnail: {e}")
            return None

    def _create_modern_gradient_background(self, size: Tuple[int, int]):
        """Create a modern gradient background with geometric elements"""

        from PIL import Image as PILImage, ImageDraw
        import colorsys
        import math

        width, height = size

        # Create base gradient - modern tech colors
        gradient = PILImage.new("RGB", size, "black")
        draw = ImageDraw.Draw(gradient)

        # Multi-color gradient: deep blue to purple to teal
        colors = [
            (15, 23, 42),  # Dark slate
            (30, 41, 59),  # Slate 700
            (51, 65, 85),  # Slate 600
            (30, 58, 138),  # Blue 800
            (67, 56, 202),  # Indigo 600
            (126, 34, 206),  # Purple 600
            (13, 148, 136),  # Teal 600
        ]

        # Create smooth gradient
        for y in range(height):
            # Calculate position in gradient (0.0 to 1.0)
            pos = y / height

            # Determine which colors to interpolate between
            segment = pos * (len(colors) - 1)
            index1 = int(segment)
            index2 = min(index1 + 1, len(colors) - 1)

            # Calculate interpolation factor
            factor = segment - index1

            # Interpolate between the two colors
            color1 = colors[index1]
            color2 = colors[index2]

            r = int(color1[0] + (color2[0] - color1[0]) * factor)
            g = int(color1[1] + (color2[1] - color1[1]) * factor)
            b = int(color1[2] + (color2[2] - color1[2]) * factor)

            # Add some horizontal variation for more interest
            for x in range(width):
                x_factor = (x / width) * 0.1  # Subtle horizontal shift
                final_r = min(255, max(0, int(r + x_factor * 20)))
                final_g = min(255, max(0, int(g + x_factor * 10)))
                final_b = min(255, max(0, int(b + x_factor * 30)))

                draw.point((x, y), (final_r, final_g, final_b))

        # Add geometric overlay elements
        overlay = PILImage.new("RGBA", size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)

        # Add subtle geometric shapes
        # Large circle in background
        circle_center = (width // 4, height // 2)
        circle_radius = min(width, height) // 3
        overlay_draw.ellipse(
            [
                circle_center[0] - circle_radius,
                circle_center[1] - circle_radius,
                circle_center[0] + circle_radius,
                circle_center[1] + circle_radius,
            ],
            outline=(255, 255, 255, 30),
            width=3,
        )

        # Diagonal lines for tech aesthetic
        for i in range(5):
            start_x = width * 0.2 + i * 50
            overlay_draw.line(
                [(start_x, 0), (start_x + height * 0.3, height)],
                fill=(255, 255, 255, 15),
                width=2,
            )

        # Blend the overlay
        gradient = gradient.convert("RGBA")
        gradient = PILImage.alpha_composite(gradient, overlay)

        return gradient.convert("RGB")

    def interactive_branded_creator(self):
        """Interactive branded thumbnail creator"""
        print("\n🎨 Branded Thumbnail Creator")
        print("=" * 60)
        print("Create professional thumbnails with Roz's photo")

        if not self.is_photo_available():
            print("\n❌ Base photo not found!")
            print("💡 Please provide the headshot photo first")
            return

        while True:
            print(f"\n📸 Using photo: {Path(self.base_photo_path).name}")
            print("\n📋 OPTIONS:")
            print("1. 🎯 Create all thumbnail styles")
            print("2. 🎨 Create specific style")
            print("3. 🤖 DALL-E Stylized (with gradient fallback)")
            print("4. 📁 View generated thumbnails")
            print("5. ❌ Exit")

            try:
                choice = input("\n👆 Select option (1-5): ").strip()

                if choice == "1":
                    title = input("📝 Enter video title: ").strip()
                    if title:
                        results = self.create_all_branded_thumbnails(title)
                        if results:
                            print(f"\n🎉 Created {len(results)} thumbnails:")
                            for key, path in results.items():
                                print(f"   • {key}: {Path(path).name}")

                elif choice == "2":
                    title = input("📝 Enter video title: ").strip()
                    if not title:
                        continue

                    print("\n🎨 Choose style:")
                    print("1. Professional (split layout)")
                    print("2. Split (full-height)")
                    print("3. Overlay (photo background)")

                    style_choice = input("👆 Select style (1-3): ").strip()
                    style_map = {"1": "professional", "2": "split", "3": "overlay"}
                    style = style_map.get(style_choice, "professional")

                    print("\n📐 Choose size:")
                    print("1. YouTube (1280x720)")
                    print("2. Social Media (1200x628)")

                    size_choice = input("👆 Select size (1-2): ").strip()
                    thumb_type = "youtube" if size_choice == "1" else "social"

                    result = self.create_branded_thumbnail(title, style, thumb_type)
                    if result:
                        print(f"✅ Thumbnail created: {Path(result).name}")

                elif choice == "3":
                    title = input("📝 Enter video title: ").strip()
                    if title:
                        print("\n🤖 Creating DALL-E stylized thumbnails...")

                        # Create both YouTube and Social Media versions
                        youtube_path = self.create_dalle_stylized_thumbnail(
                            title, "youtube"
                        )
                        social_path = self.create_dalle_stylized_thumbnail(
                            title, "social"
                        )

                        results = []
                        if youtube_path:
                            results.append(f"YouTube: {Path(youtube_path).name}")
                        if social_path:
                            results.append(f"Social: {Path(social_path).name}")

                        if results:
                            print(f"\n✅ Created {len(results)} DALL-E thumbnails:")
                            for result in results:
                                print(f"   • {result}")
                        else:
                            print("❌ Failed to create DALL-E thumbnails")

                elif choice == "4":
                    thumbnails = list(self.output_dir.glob("*.png"))
                    if thumbnails:
                        print(f"\n📸 Found {len(thumbnails)} branded thumbnails:")
                        for thumb in sorted(thumbnails)[-10:]:  # Show last 10
                            print(f"   • {thumb.name}")
                        print(f"\n📁 Location: {self.output_dir}")
                    else:
                        print("❌ No branded thumbnails found")

                elif choice == "5":
                    print("👋 Goodbye!")
                    break

                else:
                    print("⚠️ Invalid option. Please select 1-5.")

            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")


def main():
    """Main function for standalone use"""
    generator = BrandedThumbnailGenerator()
    generator.interactive_branded_creator()


if __name__ == "__main__":
    main()
