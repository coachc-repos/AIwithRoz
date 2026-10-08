"""
Placeholder Image Generator for Visual Cues
Creates placeholder images with descriptions when DALL-E is not available
"""

import os
import json
import re
from datetime import datetime
from typing import List, Dict
from PIL import Image, ImageDraw, ImageFont
import textwrap


class PlaceholderImageGenerator:
    """Generates placeholder images with descriptions for visual cues"""

    def __init__(self):
        self.default_size = (1024, 768)
        self.background_color = "#f0f0f0"
        self.text_color = "#333333"
        self.accent_color = "#4a90e2"

    def extract_visual_cues(self, script_content: str) -> List[Dict[str, str]]:
        """Extract visual cues from script content"""
        visual_cues = []

        # Pattern to match various visual cue formats
        patterns = [
            r"\[.*?CUT TO VISUAL AID:\s*(.*?)\]",
            r"\[.*?Cut to.*?:\s*(.*?)\]",
            r"\[.*?Show.*?:\s*(.*?)\]",
            r"\[.*?Transition.*?:\s*(.*?)\]",
            r"\[.*?Scene.*?:\s*(.*?)\]",
            r"\[.*?Opening shot.*?:\s*(.*?)\]",
            r"\[.*?graphic.*?:\s*(.*?)\]",
        ]

        # Extract all visual cues
        for pattern in patterns:
            matches = re.finditer(pattern, script_content, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                visual_desc = match.group(1).strip()
                if visual_desc and len(visual_desc) > 5:
                    visual_cues.append(
                        {
                            "original_text": match.group(0),
                            "description": visual_desc,
                            "line_context": self._get_line_context(
                                script_content, match.start()
                            ),
                        }
                    )

        # Remove duplicates
        seen = set()
        unique_cues = []
        for cue in visual_cues:
            if cue["description"] not in seen:
                seen.add(cue["description"])
                unique_cues.append(cue)

        return unique_cues

    def _get_line_context(self, content: str, position: int) -> str:
        """Get surrounding context for better understanding"""
        lines = content[:position].split("\n")
        context_lines = lines[-3:] if len(lines) >= 3 else lines
        return " ".join(context_lines).strip()

    def create_placeholder_image(self, description: str, output_path: str) -> bool:
        """Create a placeholder image with the description"""
        try:
            # Create image
            img = Image.new("RGB", self.default_size, color=self.background_color)
            draw = ImageDraw.Draw(img)

            # Try to load a font, fallback to default
            try:
                # Try different font paths for different systems
                font_paths = [
                    "/System/Library/Fonts/Arial.ttf",  # macOS
                    "/usr/share/fonts/truetype/arial.ttf",  # Linux
                    "C:/Windows/Fonts/arial.ttf",  # Windows
                ]

                title_font = None
                body_font = None

                for font_path in font_paths:
                    if os.path.exists(font_path):
                        title_font = ImageFont.truetype(font_path, 40)
                        body_font = ImageFont.truetype(font_path, 20)
                        break

                # Fallback to default font if no TrueType font found
                if not title_font:
                    title_font = ImageFont.load_default()
                    body_font = ImageFont.load_default()

            except Exception:
                title_font = ImageFont.load_default()
                body_font = ImageFont.load_default()

            # Add title
            title = "VISUAL CUE PLACEHOLDER"
            title_bbox = draw.textbbox((0, 0), title, font=title_font)
            title_width = title_bbox[2] - title_bbox[0]
            title_x = (self.default_size[0] - title_width) // 2
            draw.text((title_x, 50), title, fill=self.accent_color, font=title_font)

            # Add description with word wrapping
            wrapped_text = textwrap.fill(description, width=80)
            lines = wrapped_text.split("\n")

            y_offset = 150
            for line in lines:
                line_bbox = draw.textbbox((0, 0), line, font=body_font)
                line_width = line_bbox[2] - line_bbox[0]
                line_x = (self.default_size[0] - line_width) // 2
                draw.text(
                    (line_x, y_offset), line, fill=self.text_color, font=body_font
                )
                y_offset += 35

            # Add decorative elements
            # Draw border
            border_width = 5
            draw.rectangle(
                [
                    border_width,
                    border_width,
                    self.default_size[0] - border_width,
                    self.default_size[1] - border_width,
                ],
                outline=self.accent_color,
                width=border_width,
            )

            # Add footer
            footer_text = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            footer_bbox = draw.textbbox((0, 0), footer_text, font=body_font)
            footer_width = footer_bbox[2] - footer_bbox[0]
            footer_x = (self.default_size[0] - footer_width) // 2
            draw.text(
                (footer_x, self.default_size[1] - 50),
                footer_text,
                fill=self.text_color,
                font=body_font,
            )

            # Save image
            img.save(output_path)
            return True

        except Exception as e:
            print(f"Error creating placeholder image: {e}")
            return False

    def generate_images_for_script(self, script_file_path: str) -> Dict:
        """Generate placeholder images for all visual cues in a script"""
        try:
            # Read script content
            with open(script_file_path, "r", encoding="utf-8") as f:
                script_content = f.read()

            # Extract visual cues
            visual_cues = self.extract_visual_cues(script_content)
            print(f"Found {len(visual_cues)} visual cues in script")

            # Create output directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = f"output/script_placeholder_images_{timestamp}"
            os.makedirs(output_dir, exist_ok=True)

            results = {
                "script_file": script_file_path,
                "total_cues": len(visual_cues),
                "generated_images": [],
                "failed_images": [],
                "output_directory": output_dir,
                "timestamp": timestamp,
                "image_type": "placeholder",
            }

            # Generate placeholder images for each visual cue
            for i, cue in enumerate(visual_cues, 1):
                print(
                    f"Creating placeholder {i}/{len(visual_cues)}: {cue['description'][:50]}..."
                )

                # Create filename
                filename = f"placeholder_{i:02d}_{cue['description'][:30].replace(' ', '_').replace('/', '_')}.png"
                filename = re.sub(r"[^\w\-_.]", "", filename)
                filepath = os.path.join(output_dir, filename)

                # Create placeholder image
                if self.create_placeholder_image(cue["description"], filepath):
                    results["generated_images"].append(
                        {
                            "cue_number": i,
                            "description": cue["description"],
                            "original_text": cue["original_text"],
                            "image_file": filepath,
                            "image_type": "placeholder",
                        }
                    )
                    print(f"✅ Created placeholder: {filename}")
                else:
                    results["failed_images"].append(
                        {
                            "cue_number": i,
                            "description": cue["description"],
                            "error": "Failed to create placeholder image",
                        }
                    )
                    print(f"❌ Failed to create placeholder for cue {i}")

            # Save results summary
            summary_file = os.path.join(
                output_dir, "placeholder_generation_summary.json"
            )
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)

            print(
                f"✅ Placeholder generation complete! Created {len(results['generated_images'])} placeholders"
            )
            print(f"📁 Output directory: {output_dir}")

            return results

        except Exception as e:
            print(f"Error processing script: {e}")
            return {"error": str(e)}


def main():
    """Test function"""
    generator = PlaceholderImageGenerator()

    # Test with latest script
    script_file = "output/script_video_script_20250819_165453.md"
    if os.path.exists(script_file):
        results = generator.generate_images_for_script(script_file)
        print(
            f"Generated {len(results.get('generated_images', []))} placeholder images"
        )
        print(f"Failed: {len(results.get('failed_images', []))}")
    else:
        print(f"Script file not found: {script_file}")


if __name__ == "__main__":
    main()
