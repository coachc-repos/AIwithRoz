#!/usr/bin/env python3
"""
Thumbnail Generator for LineDrive Scripts
Creates eye-catching thumbnails for video content using multiple approaches
"""

import os
import sys
import requests
import json
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
from typing import Dict, List, Optional, Tuple
import textwrap
import colorsys

# Add LineDrive to path for imports
sys.path.append(str(Path(__file__).parent))


class ThumbnailGenerator:
    """Generate thumbnails                        from .branded_thumbnail_generator import (
        BrandedThumbnailGenerator,
    )r video content using multiple approaches"""

    def __init__(self):
        self.output_dir = Path.home() / "Dev/Videos/Thumbnails"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Thumbnail dimensions (16:9 ratio, YouTube optimized)
        self.thumbnail_size = (1280, 720)  # HD standard
        self.youtube_size = (1280, 720)  # YouTube recommended
        self.social_size = (1200, 628)  # Social media optimized

        # Color schemes for different video types
        self.color_schemes = {
            "tech": {
                "bg": "#1a1a2e",
                "accent": "#16213e",
                "text": "#ffffff",
                "highlight": "#0f3460",
            },
            "ai": {
                "bg": "#0d1421",
                "accent": "#1a2332",
                "text": "#ffffff",
                "highlight": "#00d4ff",
            },
            "business": {
                "bg": "#2c3e50",
                "accent": "#34495e",
                "text": "#ffffff",
                "highlight": "#3498db",
            },
            "education": {
                "bg": "#27ae60",
                "accent": "#2ecc71",
                "text": "#ffffff",
                "highlight": "#f39c12",
            },
            "default": {
                "bg": "#2c3e50",
                "accent": "#34495e",
                "text": "#ffffff",
                "highlight": "#e74c3c",
            },
        }

    def sanitize_filename(self, text: str) -> str:
        """Convert text to safe filename"""
        sanitized = "".join(
            c for c in text if c.isalnum() or c in (" ", "-", "_")
        ).strip()
        sanitized = " ".join(sanitized.split())  # Remove extra spaces
        return sanitized.replace(" ", "_")[:50]

    def get_color_scheme(self, topic: str) -> Dict[str, str]:
        """Get appropriate color scheme based on topic"""
        topic_lower = topic.lower()

        if any(
            word in topic_lower
            for word in ["ai", "artificial intelligence", "machine learning", "neural"]
        ):
            return self.color_schemes["ai"]
        elif any(
            word in topic_lower
            for word in ["tech", "technology", "programming", "coding", "software"]
        ):
            return self.color_schemes["tech"]
        elif any(
            word in topic_lower
            for word in ["business", "marketing", "sales", "leadership"]
        ):
            return self.color_schemes["business"]
        elif any(
            word in topic_lower
            for word in ["learn", "education", "tutorial", "guide", "how to"]
        ):
            return self.color_schemes["education"]
        else:
            return self.color_schemes["default"]

    def create_gradient_background(
        self, size: Tuple[int, int], colors: Dict[str, str]
    ) -> Image.Image:
        """Create a gradient background"""
        img = Image.new("RGB", size)
        draw = ImageDraw.Draw(img)

        # Parse hex colors
        bg_color = tuple(int(colors["bg"][i : i + 2], 16) for i in (1, 3, 5))
        accent_color = tuple(int(colors["accent"][i : i + 2], 16) for i in (1, 3, 5))

        # Create gradient
        for y in range(size[1]):
            # Calculate color blend ratio
            ratio = y / size[1]

            # Blend colors
            r = int(bg_color[0] * (1 - ratio) + accent_color[0] * ratio)
            g = int(bg_color[1] * (1 - ratio) + accent_color[1] * ratio)
            b = int(bg_color[2] * (1 - ratio) + accent_color[2] * ratio)

            draw.line([(0, y), (size[0], y)], fill=(r, g, b))

        return img

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
                    fonts["title"] = ImageFont.truetype(font_path, 80)
                    fonts["subtitle"] = ImageFont.truetype(font_path, 45)
                    fonts["small"] = ImageFont.truetype(font_path, 30)
                    break
            else:
                # Fallback to default fonts
                fonts["title"] = ImageFont.load_default()
                fonts["subtitle"] = ImageFont.load_default()
                fonts["small"] = ImageFont.load_default()
        except Exception:
            fonts["title"] = ImageFont.load_default()
            fonts["subtitle"] = ImageFont.load_default()
            fonts["small"] = ImageFont.load_default()

        return fonts

    def add_text_with_outline(
        self,
        draw: ImageDraw.Draw,
        text: str,
        position: Tuple[int, int],
        font: ImageFont.FreeTypeFont,
        fill: str,
        outline: str = "#000000",
        outline_width: int = 3,
    ) -> None:
        """Add text with outline for better visibility"""
        x, y = position

        # Draw outline
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), text, font=font, fill=outline)

        # Draw main text
        draw.text(position, text, font=font, fill=fill)

    def create_text_thumbnail(
        self, title: str, subtitle: str = "", thumbnail_type: str = "youtube"
    ) -> str:
        """Create a text-based thumbnail"""

        # Choose size based on type
        if thumbnail_type == "social":
            size = self.social_size
        else:
            size = self.youtube_size

        # Get color scheme
        colors = self.get_color_scheme(title)

        # Create gradient background
        img = self.create_gradient_background(size, colors)

        # Add some visual elements
        draw = ImageDraw.Draw(img)

        # Add geometric shapes for visual interest
        highlight_color = tuple(
            int(colors["highlight"][i : i + 2], 16) for i in (1, 3, 5)
        )

        # Add some accent shapes
        draw.ellipse(
            [size[0] - 200, -50, size[0] + 50, 200], fill=highlight_color + (50,)
        )
        draw.rectangle([0, size[1] - 100, 300, size[1]], fill=highlight_color + (30,))

        # Get fonts
        fonts = self.get_fonts()

        # Prepare title text (wrap if too long)
        max_title_width = size[0] - 100
        title_lines = []

        # Split title into lines that fit
        words = title.split()
        current_line = []

        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=fonts["title"])
            if bbox[2] - bbox[0] <= max_title_width:
                current_line.append(word)
            else:
                if current_line:
                    title_lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    title_lines.append(word)

        if current_line:
            title_lines.append(" ".join(current_line))

        # Position title text
        total_text_height = len(title_lines) * 90
        if subtitle:
            total_text_height += 60

        start_y = (size[1] - total_text_height) // 2

        # Draw title lines
        for i, line in enumerate(title_lines):
            bbox = draw.textbbox((0, 0), line, font=fonts["title"])
            text_width = bbox[2] - bbox[0]
            x = (size[0] - text_width) // 2
            y = start_y + (i * 90)

            self.add_text_with_outline(
                draw, line, (x, y), fonts["title"], colors["text"]
            )

        # Draw subtitle if provided
        if subtitle:
            y_subtitle = start_y + (len(title_lines) * 90) + 20
            bbox = draw.textbbox((0, 0), subtitle, font=fonts["subtitle"])
            text_width = bbox[2] - bbox[0]
            x = (size[0] - text_width) // 2

            self.add_text_with_outline(
                draw, subtitle, (x, y_subtitle), fonts["subtitle"], colors["text"]
            )

        # Add branding
        brand_text = "AI with Roz"
        bbox = draw.textbbox((0, 0), brand_text, font=fonts["small"])
        text_width = bbox[2] - bbox[0]
        x = size[0] - text_width - 20
        y = size[1] - 40

        self.add_text_with_outline(
            draw, brand_text, (x, y), fonts["small"], colors["highlight"]
        )

        # Save thumbnail
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.sanitize_filename(title)}_{thumbnail_type}_{timestamp}.png"
        filepath = self.output_dir / filename

        img.save(filepath, quality=95)
        print(f"📸 Thumbnail saved: {filepath}")

        return str(filepath)

    def create_pexels_based_thumbnail(
        self, title: str, description: str = "", thumbnail_type: str = "youtube"
    ) -> Optional[str]:
        """Create thumbnail using Pexels background image with text overlay"""
        try:
            from .pexels_image_downloader import PexelsImageDownloader

            # Download background image
            pexels_downloader = PexelsImageDownloader()

            if not pexels_downloader.is_configured():
                print("⚠️ Pexels not configured. Using text-based thumbnail.")
                return self.create_text_thumbnail(title, description, thumbnail_type)

            # Create search query from title
            search_query = title.lower()
            # Remove common words and focus on key terms
            key_words = [
                word
                for word in search_query.split()
                if word
                not in [
                    "the",
                    "a",
                    "an",
                    "and",
                    "or",
                    "but",
                    "in",
                    "on",
                    "at",
                    "to",
                    "for",
                ]
            ]
            search_query = " ".join(key_words[:3])  # Use first 3 key words

            print(f"🔍 Searching for background image: {search_query}")
            bg_image_path = pexels_downloader.download_thumbnail_image(search_query)

            if not bg_image_path:
                print("⚠️ No background image found. Using text-based thumbnail.")
                return self.create_text_thumbnail(title, description, thumbnail_type)

            # Choose size based on type
            if thumbnail_type == "social":
                size = self.social_size
            else:
                size = self.youtube_size

            # Load and resize background image
            bg_img = Image.open(bg_image_path)
            bg_img = bg_img.resize(size, Image.Resampling.LANCZOS)

            # Add dark overlay for text readability
            overlay = Image.new("RGBA", size, (0, 0, 0, 100))
            bg_img = bg_img.convert("RGBA")
            bg_img = Image.alpha_composite(bg_img, overlay)
            bg_img = bg_img.convert("RGB")

            # Add text overlay (similar to text-based thumbnail)
            draw = ImageDraw.Draw(bg_img)

            # Get fonts
            fonts = self.get_fonts()

            # Prepare title text (wrap if too long)
            max_title_width = size[0] - 100
            title_lines = []

            # Split title into lines that fit
            words = title.split()
            current_line = []

            for word in words:
                test_line = " ".join(current_line + [word])
                bbox = draw.textbbox((0, 0), test_line, font=fonts["title"])
                if bbox[2] - bbox[0] <= max_title_width:
                    current_line.append(word)
                else:
                    if current_line:
                        title_lines.append(" ".join(current_line))
                        current_line = [word]
                    else:
                        title_lines.append(word)

            if current_line:
                title_lines.append(" ".join(current_line))

            # Position title text
            total_text_height = len(title_lines) * 90
            if description:
                total_text_height += 60

            start_y = (size[1] - total_text_height) // 2

            # Draw title lines with strong outline for visibility
            for i, line in enumerate(title_lines):
                bbox = draw.textbbox((0, 0), line, font=fonts["title"])
                text_width = bbox[2] - bbox[0]
                x = (size[0] - text_width) // 2
                y = start_y + (i * 90)

                self.add_text_with_outline(
                    draw, line, (x, y), fonts["title"], "#ffffff", "#000000", 4
                )

            # Draw subtitle if provided
            if description:
                y_subtitle = start_y + (len(title_lines) * 90) + 20
                bbox = draw.textbbox((0, 0), description, font=fonts["subtitle"])
                text_width = bbox[2] - bbox[0]
                x = (size[0] - text_width) // 2

                self.add_text_with_outline(
                    draw,
                    description,
                    (x, y_subtitle),
                    fonts["subtitle"],
                    "#ffffff",
                    "#000000",
                    3,
                )

            # Add branding
            brand_text = "AI with Roz"
            bbox = draw.textbbox((0, 0), brand_text, font=fonts["small"])
            text_width = bbox[2] - bbox[0]
            x = size[0] - text_width - 20
            y = size[1] - 40

            self.add_text_with_outline(
                draw, brand_text, (x, y), fonts["small"], "#00d4ff", "#000000", 2
            )

            # Save thumbnail
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.sanitize_filename(title)}_pexels_{thumbnail_type}_{timestamp}.png"
            filepath = self.output_dir / filename

            bg_img.save(filepath, quality=95)
            print(f"📸 Pexels-based thumbnail saved: {filepath}")

            return str(filepath)

        except ImportError:
            print(
                "⚠️ Pexels Image Downloader not available. Using text-based thumbnail."
            )
            return self.create_text_thumbnail(title, description, thumbnail_type)
        except Exception as e:
            print(f"❌ Error creating Pexels thumbnail: {e}")
            return self.create_text_thumbnail(title, description, thumbnail_type)

    def create_ai_generated_thumbnail(
        self, title: str, description: str = "", thumbnail_type: str = "youtube"
    ) -> Optional[str]:
        """Create AI-generated thumbnail using Azure DALL-E"""
        try:
            from linedrive_azure.agents.azure_image_generator_client import (
                AzureImageGenerator,
            )

            # Create AI image generator
            image_gen = AzureImageGenerator()

            # Create enhanced prompt for thumbnail
            prompt = f"Professional YouTube thumbnail for video titled '{title}'. "
            prompt += (
                "Modern, eye-catching design with bold text overlay, bright colors, "
            )
            prompt += "high contrast, engaging visual elements. "

            if description:
                prompt += f"Content relates to: {description}. "

            prompt += "Style: clean, professional, YouTube thumbnail aesthetic, "
            prompt += "16:9 aspect ratio, optimized for small preview sizes."

            print(f"🎨 Generating AI thumbnail for: {title[:50]}...")
            print(f"   Prompt: {prompt[:100]}...")

            # Generate image
            result = image_gen.generate_image(prompt)

            if result and result.get("success"):
                # Download the generated image
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{self.sanitize_filename(title)}_ai_{thumbnail_type}_{timestamp}.png"
                filepath = self.output_dir / filename

                if image_gen.download_image(result["image_url"], str(filepath)):
                    print(f"✅ AI thumbnail generated: {filepath}")
                    return str(filepath)
                else:
                    print("❌ Failed to download AI-generated image")
                    return None
            else:
                print(
                    f"❌ AI generation failed: {result.get('error', 'Unknown error')}"
                )
                return None

        except ImportError:
            print("⚠️ Azure Image Generator not available. Using text-based thumbnail.")
            return self.create_text_thumbnail(title, description, thumbnail_type)
        except Exception as e:
            print(f"❌ Error generating AI thumbnail: {e}")
            return self.create_text_thumbnail(title, description, thumbnail_type)

    def create_thumbnails_for_script(
        self, script_topic: str, script_content: str = ""
    ) -> Dict[str, str]:
        """Create multiple thumbnail variations for a script"""
        print(f"\n🖼️ THUMBNAIL GENERATION")
        print("=" * 60)
        print(f"📝 Topic: {script_topic}")

        results = {}

        # Extract key points from script for subtitle
        subtitle = ""
        if script_content:
            # Look for key themes or the first chapter
            lines = script_content.split("\n")
            for line in lines:
                if line.startswith("#") and len(line.split()) > 2:
                    subtitle = line.replace("#", "").strip()[:50]
                    break

        # Try branded thumbnails first (if Roz's photo is available)
        print(f"\n🎨 Attempting branded thumbnails...")
        try:
            from .branded_thumbnail_generator import BrandedThumbnailGenerator

            branded_gen = BrandedThumbnailGenerator()
            if branded_gen.is_photo_available():
                print(f"✅ Creating branded thumbnails with Roz's photo...")
                branded_results = branded_gen.create_all_branded_thumbnails(
                    script_topic
                )
                results.update(branded_results)

                if branded_results:
                    print(
                        f"🎉 Successfully created {len(branded_results)} branded thumbnails!"
                    )
                    # If we have branded thumbnails, we might not need as many generic ones
                    print(f"📝 Branded thumbnails complete, adding backup options...")
            else:
                print(f"⚠️ Roz's headshot not found, using generic thumbnails")

        except ImportError as e:
            print(f"⚠️ Branded thumbnail generator not available: {e}")
        except Exception as e:
            print(f"⚠️ Branded thumbnail error: {e}")

        # Generate standard thumbnail types with multiple approaches
        thumbnail_types = [
            ("youtube", "Standard YouTube thumbnail"),
            ("social", "Social media optimized"),
        ]

        for thumb_type, description in thumbnail_types:
            print(f"\n🎯 Creating {description}...")

            # Try all three approaches
            approaches = [
                ("pexels", "Pexels background + text overlay"),
                ("ai", "AI-generated DALL-E"),
                ("text", "Text-based design"),
            ]

            for approach, approach_desc in approaches:
                try:
                    print(f"   🔄 Trying {approach_desc}...")

                    if approach == "pexels":
                        thumbnail = self.create_pexels_based_thumbnail(
                            script_topic, subtitle, thumb_type
                        )
                    elif approach == "ai":
                        thumbnail = self.create_ai_generated_thumbnail(
                            script_topic, subtitle, thumb_type
                        )
                    else:  # text
                        thumbnail = self.create_text_thumbnail(
                            script_topic, subtitle, thumb_type
                        )

                    if thumbnail:
                        results[f"{thumb_type}_{approach}"] = thumbnail
                        print(f"   ✅ {approach_desc} successful")
                        break  # Move to next thumbnail type
                    else:
                        print(f"   ⚠️ {approach_desc} failed, trying next...")

                except Exception as e:
                    print(f"   ❌ {approach_desc} error: {e}")
                    continue

            # Ensure we have at least one thumbnail of each type
            if not any(key.startswith(thumb_type) for key in results.keys()):
                print(f"   🔄 Fallback: Creating basic text thumbnail...")
                fallback = self.create_text_thumbnail(
                    script_topic, subtitle, thumb_type
                )
                if fallback:
                    results[f"{thumb_type}_fallback"] = fallback

        print(f"\n✅ Generated {len(results)} thumbnails in multiple directories")
        return results

    def interactive_thumbnail_creator(self):
        """Interactive thumbnail creation tool"""
        print("\n🖼️ LineDrive Thumbnail Generator")
        print("=" * 60)
        print("Create eye-catching thumbnails for your video content")

        while True:
            print("\n📋 THUMBNAIL OPTIONS:")
            print("1. 🎨 Generate thumbnails for script topic")
            print("2. 📄 Generate from existing script file")
            print("3. 🎯 Quick thumbnail (title only)")
            print("4. � Branded thumbnails (with Roz's photo)")
            print("5. �📊 View generated thumbnails")
            print("6. ❌ Exit")

            try:
                choice = input("\n👆 Select option (1-6): ").strip()

                if choice == "1":
                    title = input("📝 Enter video title/topic: ").strip()
                    if title:
                        subtitle = input("📄 Enter subtitle (optional): ").strip()
                        results = self.create_thumbnails_for_script(title, subtitle)
                        print(f"\n🎉 Created thumbnails: {list(results.keys())}")

                elif choice == "2":
                    script_path = input("📁 Enter script file path: ").strip()
                    if os.path.exists(script_path):
                        # Extract topic from filename
                        filename = Path(script_path).stem
                        topic = filename.replace("_", " ").title()

                        # Read script content
                        with open(script_path, "r", encoding="utf-8") as f:
                            content = f.read()

                        results = self.create_thumbnails_for_script(topic, content)
                        print(f"\n🎉 Created thumbnails: {list(results.keys())}")
                    else:
                        print("❌ Script file not found")

                elif choice == "3":
                    title = input("📝 Enter thumbnail title: ").strip()
                    if title:
                        filepath = self.create_text_thumbnail(title)
                        print(f"✅ Quick thumbnail created: {filepath}")

                elif choice == "4":
                    print("\n👤 Launching Branded Thumbnail Creator...")
                    try:
                        from branded_thumbnail_generator import (
                            BrandedThumbnailGenerator,
                        )

                        branded_gen = BrandedThumbnailGenerator()
                        if not branded_gen.is_photo_available():
                            print("❌ Roz's headshot not found!")
                            print("💡 Please save your headshot as:")
                            print("   ~/Dev/Videos/Thumbnails/" "roz_headshot.jpg")
                        else:
                            branded_gen.interactive_branded_creator()
                    except ImportError:
                        print("❌ Branded thumbnail generator not available")
                    except Exception as e:
                        print(f"❌ Error: {e}")

                elif choice == "5":
                    thumbnails = list(self.output_dir.glob("*.png"))
                    if thumbnails:
                        print(f"\n📸 Found {len(thumbnails)} thumbnails:")
                        for thumb in sorted(thumbnails)[-10:]:  # Show last 10
                            print(f"   • {thumb.name}")
                        print(f"\n📁 Location: {self.output_dir}")
                    else:
                        print("❌ No thumbnails found")

                elif choice == "6":
                    print("👋 Goodbye!")
                    break

                else:
                    print("⚠️ Invalid option. Please select 1-6.")

            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")


def main():
    """Main function for standalone use"""
    generator = ThumbnailGenerator()
    generator.interactive_thumbnail_creator()


if __name__ == "__main__":
    main()
