#!/usr/bin/env python3
"""
B-Roll Image Generator using Google Gemini Flash Image

Generates AI images for each B-roll search term in the table.
Uses Google's Gemini 2.0 Flash image generation model for high-quality, contextual images.
"""

import os
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime


class BRollImageGenerator:
    """Generate AI images for B-roll search terms"""

    def __init__(self, api_key: str = None):
        """
        Initialize the B-roll image generator

        Args:
            api_key: Google API key (defaults to GOOGLE_API_KEY environment variable)
        """
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Google API key not found. Set GOOGLE_API_KEY environment variable "
                "or pass api_key parameter."
            )

        # Output directory
        self.output_dir = Path.home() / "Dev" / "brollimages"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Lazy loading for google.genai
        self._client = None

    def _get_client(self):
        """Get or create the Google GenAI client"""
        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
                print("✅ Google GenAI client initialized")
            except ImportError as e:
                raise ImportError(
                    "google-genai package not installed. "
                    "Install with: pip install google-genai"
                ) from e
        return self._client

    def parse_broll_table(self, table_text: str) -> List[Dict[str, str]]:
        """
        Parse markdown B-roll table into structured data

        Args:
            table_text: Markdown table text

        Returns:
            List of dicts with search_term, description, scene_context
        """
        entries = []
        lines = table_text.strip().split('\n')

        for line in lines:
            # Skip header lines and separator lines
            if '|' not in line or line.strip().startswith('|---'):
                continue

            # Check if this is a header line
            if 'Search Term' in line or 'Timecode' in line:
                continue

            # Split by pipe and clean up
            parts = [p.strip() for p in line.split('|')]
            # Remove empty first/last elements if they exist
            parts = [p for p in parts if p]

            # Handle both timecode and non-timecode tables
            if len(parts) >= 3:
                if len(parts) == 4 and ':' in parts[0]:
                    # Has timecode: timecode | search_term | description | scene_context
                    entry = {
                        'timecode': parts[0],
                        'search_term': parts[1],
                        'description': parts[2],
                        'scene_context': parts[3],
                    }
                elif len(parts) == 3:
                    # No timecode: search_term | description | scene_context
                    entry = {
                        'search_term': parts[0],
                        'description': parts[1],
                        'scene_context': parts[2],
                    }
                else:
                    # Fallback for other formats
                    entry = {
                        'search_term': parts[0],
                        'description': parts[1] if len(parts) > 1 else '',
                        'scene_context': parts[2] if len(parts) > 2 else '',
                    }

                entries.append(entry)

        return entries

    def generate_broll_image(
        self,
        search_term: str,
        description: str,
        scene_context: str,
        index: int,
        script_title: str,
        variation: int = 1
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a single B-roll image

        Args:
            search_term: The B-roll search term
            description: What to look for in the footage
            scene_context: When to use in the script
            index: Image index number
            script_title: Script title for context
            variation: Variation number (1-3)

        Returns:
            Dict with success status and file path, or None on failure
        """
        try:
            client = self._get_client()
            from google.genai import types

            # Create detailed prompt combining search term AND description for specificity
            prompt = f"""Create a professional, high-quality stock photo style image for video B-roll footage.

**Video Topic:** {script_title}

**Image Subject:** {search_term} - {description}

**Scene Context:** {scene_context}

**Style Guidelines:**
- Professional stock photo aesthetic (similar to Pexels/Pixabay)
- Clean, modern, and polished look
- Well-lit and properly exposed
- Sharp focus with good composition
- Suitable for video editing (16:9 aspect ratio preferred)
- No watermarks or text overlays
- Realistic and contextually appropriate
- High production value

**Technical Requirements:**
- Horizontal orientation (landscape)
- Professional lighting
- Clear subject matter
- Appropriate depth of field
- Suitable for video overlay/cutaway shots

Generate an image showing: {search_term} with these specific details: {description}. This will be used as B-roll footage in a professional video about {script_title}."""

            print(
                f"\n🎨 Generating image {index} variation {variation}: {search_term}")
            print(f"   Description: {description[:60]}...")

            # Generate the image using google-genai SDK
            response = client.models.generate_content(
                model="gemini-2.5-flash-image",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                )
            )

            # Check if image was generated
            if not response.candidates or not response.candidates[0].content:
                print(f"❌ No image generated for {search_term}")
                return None

            # Extract image from response parts
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    image_data = part.inline_data.data
                    mime_type = part.inline_data.mime_type or "image/png"

                    # Determine file extension
                    ext = 'png'
                    if 'jpeg' in mime_type or 'jpg' in mime_type:
                        ext = 'jpg'
                    elif 'webp' in mime_type:
                        ext = 'webp'

                    # Create safe filename with variation
                    safe_term = re.sub(r'[^\w\s-]', '', search_term)
                    safe_term = re.sub(r'[-\s]+', '_', safe_term)
                    safe_term = safe_term[:50]  # Limit length

                    filename = f"broll_{index:02d}_{safe_term}.{ext}"
                    filepath = self.output_dir / filename

                    # Save the image
                    with open(filepath, 'wb') as f:
                        f.write(image_data)

                    print(f"✅ Saved: {filename}")

                    return {
                        'success': True,
                        'filename': str(filepath),
                        'search_term': search_term,
                        'description': description,
                        'index': index
                    }

            print(f"❌ No image data found in response for {search_term}")
            return None

        except Exception as e:
            print(f"❌ Error generating image for {search_term}: {e}")
            return None

    def generate_all_broll_images(
        self,
        broll_table: str,
        script_title: str,
        max_images: int = None,
        progress_callback=None,
        cancel_check=None,
        output_dir=None,
    ) -> Dict[str, Any]:
        """
        Generate images for all B-roll entries

        Args:
            broll_table: Markdown table text with B-roll entries
            script_title: Script title for context
            max_images: Optional limit on number of images to generate
            progress_callback: Optional callable(message, current, total, image_info=None)
                invoked after each image attempt so the UI can show live progress.
            cancel_check: Optional callable() -> bool. When it returns True the loop
                exits early and returns partial results with cancelled=True.
            output_dir: Optional Path/str overriding the default output directory.

        Returns:
            Dict with success status, images list, and output directory
        """
        # Allow per-call override of the output directory
        if output_dir is not None:
            self.output_dir = Path(output_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n🎬 B-ROLL IMAGE GENERATION")
        print("=" * 60)
        print(f"📋 Script: {script_title}")
        print(f"📁 Output: {self.output_dir}")
        print("=" * 60)

        # Parse the B-roll table
        entries = self.parse_broll_table(broll_table)

        if not entries:
            return {
                'success': False,
                'error': 'No B-roll entries found in table',
                'images': []
            }

        print(f"📊 Found {len(entries)} B-roll entries")
        print(f"🎯 Generating 1 image per entry")

        # Show first few entries for debugging
        print("\n📋 B-roll entries to process:")
        for i, entry in enumerate(entries[:5], 1):
            print(f"   {i}. {entry['search_term']}")
        if len(entries) > 5:
            print(f"   ... and {len(entries) - 5} more entries")

        # Limit number of entries if specified
        if max_images:
            entries = entries[:max_images]
            print(f"\n🎯 Limited to {len(entries)} images")
        else:
            print(f"\n🎯 Will generate {len(entries)} images")

        # Generate one image per entry
        images = []
        cancelled = False
        total = len(entries)
        import time
        for idx, entry in enumerate(entries, 1):
            if cancel_check is not None:
                try:
                    if cancel_check():
                        cancelled = True
                        print("🛑 B-roll image generation cancelled by user")
                        if progress_callback is not None:
                            try:
                                progress_callback(
                                    "🛑 B-roll image generation cancelled",
                                    idx - 1, total, None,
                                )
                            except Exception:
                                pass
                        break
                except Exception:
                    pass

            if progress_callback is not None:
                try:
                    progress_callback(
                        f"🎨 Generating image {idx}/{total}: {entry['search_term']}",
                        idx - 1, total, None,
                    )
                except Exception:
                    pass

            result = self.generate_broll_image(
                search_term=entry['search_term'],
                description=entry['description'],
                scene_context=entry['scene_context'],
                index=idx,
                script_title=script_title,
                variation=1
            )

            if result and result.get('success'):
                images.append(result)

            if progress_callback is not None:
                try:
                    progress_callback(
                        f"✅ Image {idx}/{total} complete" if (result and result.get('success'))
                        else f"⚠️ Image {idx}/{total} failed",
                        idx, total, result,
                    )
                except Exception:
                    pass

            # Small delay between generations to avoid rate limiting
            time.sleep(1)

        print(f"\n{'=' * 60}")
        print(
            f"✅ Generated {len(images)} B-roll images ({len(entries)} entries × 1)")
        print(f"📁 Saved to: {self.output_dir}")
        print(f"{'=' * 60}")

        return {
            'success': True,
            'cancelled': cancelled,
            'images': images,
            'output_dir': str(self.output_dir),
            'total_generated': len(images),
            'total_entries': len(entries),
            'variations_per_entry': 1
        }


if __name__ == "__main__":
    # Test the generator
    print("🧪 Testing B-Roll Image Generator")

    # Sample B-roll table for testing
    test_table = """
| Search Term | Description | Scene Context |
|-------------|-------------|---------------|
| laptop coding | Person typing on laptop showing code on screen | Opening scene, developer workspace |
| AI neural network | Abstract visualization of neural network connections | Explaining AI concepts |
| team collaboration | Diverse team discussing around whiteboard | Team productivity section |
"""

    generator = BRollImageGenerator()
    results = generator.generate_all_broll_images(
        broll_table=test_table,
        script_title="AI Tools for Developers",
        max_images=3
    )

    if results['success']:
        print(f"\n✅ Test successful!")
        print(f"Generated {len(results['images'])} images")
        for img in results['images']:
            print(f"  - {img['search_term']}: {img['filename']}")
    else:
        print(f"\n❌ Test failed: {results.get('error')}")
