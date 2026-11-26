#!/usr/bin/env python3
"""
Pexels Image Downloader for Thumbnail Generation
Extends the existing Pexels video downloader to support images for thumbnails
"""

import os
import sys
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import json

# Add LineDrive to path for imports
sys.path.append(str(Path(__file__).parent))


class PexelsImageDownloader:
    """Download images from Pexels for thumbnail generation"""

    def __init__(self):
        # Use the same config as the video downloader
        try:
            from .pexels_video_downloader import PexelsConfig

            self.config = PexelsConfig()
            self.api_key = self.config.get_api_key()
        except ImportError:
            print("⚠️ PexelsConfig not available. Please set PEXELS_API_KEY manually.")
            self.api_key = os.environ.get("PEXELS_API_KEY")

        self.base_url = "https://api.pexels.com/v1"
        self.headers = {
            "Authorization": f"{self.api_key}",
            "User-Agent": "LineDrive-ThumbnailGen/1.0",
        }

        # Output directory for images
        self.output_dir = Path.home() / "Dev/Videos/Thumbnails/PexelsImages"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def is_configured(self) -> bool:
        """Check if Pexels API is properly configured"""
        return bool(self.api_key and len(self.api_key.strip()) > 10)

    def search_images(self, query: str, per_page: int = 15) -> Optional[Dict]:
        """Search for images on Pexels"""
        if not self.is_configured():
            print("❌ Pexels API key not configured")
            return None

        url = f"{self.base_url}/search"
        params = {
            "query": query,
            "per_page": per_page,
            "orientation": "landscape",  # Better for thumbnails
        }

        try:
            print(f"🔍 Searching Pexels for images: '{query}'...")
            response = requests.get(
                url, headers=self.headers, params=params, timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                print(f"✅ Found {data.get('total_results', 0)} total results")
                return data
            else:
                print(f"❌ Search failed: {response.status_code}")
                print(f"Response: {response.text}")
                return None

        except Exception as e:
            print(f"❌ Search error: {e}")
            return None

    def download_image(
        self, image_url: str, filename: str, metadata: Dict = None
    ) -> bool:
        """Download an image from URL"""
        try:
            filepath = self.output_dir / filename

            print(f"📥 Downloading: {filename}")
            response = requests.get(image_url, timeout=30)

            if response.status_code == 200:
                with open(filepath, "wb") as f:
                    f.write(response.content)

                # Log metadata
                if metadata:
                    self._log_image_metadata(metadata)

                file_size = filepath.stat().st_size / (1024 * 1024)  # MB
                print(f"✅ Downloaded: {filename} ({file_size:.1f} MB)")
                return True
            else:
                print(f"❌ Download failed: {response.status_code}")
                return False

        except Exception as e:
            print(f"❌ Download error: {e}")
            return False

    def _log_image_metadata(self, metadata: Dict):
        """Log image download metadata"""
        log_file = self.output_dir / "image_metadata_log.json"

        try:
            # Read existing log
            if log_file.exists():
                with open(log_file, "r") as f:
                    log_data = json.load(f)
            else:
                log_data = []

            # Add new entry
            log_data.append(metadata)

            # Write updated log
            with open(log_file, "w") as f:
                json.dump(log_data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            print(f"⚠️ Failed to log metadata: {e}")

    def download_thumbnail_image(
        self, query: str, size: str = "large"
    ) -> Optional[str]:
        """Download a single image for thumbnail use"""
        search_results = self.search_images(query, per_page=10)

        if not search_results or not search_results.get("photos"):
            print(f"❌ No images found for: {query}")
            return None

        # Get the first good image
        photo = search_results["photos"][0]

        # Choose image size (large = 1280x853 typically, good for thumbnails)
        image_url = photo["src"].get(size, photo["src"]["large"])

        # Create filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        query_safe = "".join(
            c for c in query if c.isalnum() or c in (" ", "-", "_")
        ).strip()
        query_safe = query_safe.replace(" ", "_")[:30]
        filename = f"pexels_{query_safe}_{size}_{timestamp}.jpg"

        # Create metadata
        metadata = {
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "filename": filename,
            "filepath": str(self.output_dir / filename),
            "source": "Pexels",
            "photo_id": photo.get("id"),
            "photographer": photo.get("photographer"),
            "photographer_url": photo.get("photographer_url"),
            "photo_url": photo.get("url"),
            "size": size,
            "width": photo.get("width"),
            "height": photo.get("height"),
            "license": "Pexels License (Free to use)",
            "license_url": "https://www.pexels.com/license/",
        }

        # Download the image
        if self.download_image(image_url, filename, metadata):
            return str(self.output_dir / filename)
        else:
            return None

    def interactive_image_downloader(self):
        """Interactive image download tool"""
        print("\n📸 Pexels Image Downloader for Thumbnails")
        print("=" * 60)

        if not self.is_configured():
            print("❌ Pexels API key not found!")
            print("💡 Add PEXELS_API_KEY to linedrive_azure/agents/.env")
            return

        while True:
            print("\n📋 OPTIONS:")
            print("1. 🔍 Download image by topic")
            print("2. 📁 Show downloaded images")
            print("3. ❌ Exit")

            try:
                choice = input("\n👆 Select option (1-3): ").strip()

                if choice == "1":
                    query = input(
                        "🎯 Enter image topic (e.g., 'technology', 'business'): "
                    ).strip()
                    if query:
                        print(f"\n📸 Searching for: {query}")

                        # Size options
                        print("\n📐 Choose image size:")
                        print("1. Large (best for thumbnails)")
                        print("2. Medium")
                        print("3. Small")

                        size_choice = input("👆 Select size (1-3, default=1): ").strip()
                        size_map = {"1": "large", "2": "medium", "3": "small"}
                        size = size_map.get(size_choice, "large")

                        filepath = self.download_thumbnail_image(query, size)

                        if filepath:
                            print(f"\n🎉 Success! Image saved: {Path(filepath).name}")
                        else:
                            print(f"\n❌ Failed to download image for: {query}")

                elif choice == "2":
                    images = list(self.output_dir.glob("*.jpg")) + list(
                        self.output_dir.glob("*.png")
                    )
                    if images:
                        print(f"\n📸 Found {len(images)} downloaded images:")
                        for img in sorted(images)[-10:]:  # Show last 10
                            size_mb = img.stat().st_size / (1024 * 1024)
                            print(f"   • {img.name} ({size_mb:.1f} MB)")
                        print(f"\n📁 Location: {self.output_dir}")
                    else:
                        print("❌ No images found")

                elif choice == "3":
                    print("👋 Goodbye!")
                    break

                else:
                    print("⚠️ Invalid option. Please select 1-3.")

            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")


def main():
    """Main function for standalone use"""
    downloader = PexelsImageDownloader()
    downloader.interactive_image_downloader()


if __name__ == "__main__":
    main()
