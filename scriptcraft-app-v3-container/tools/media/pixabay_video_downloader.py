#!/usr/bin/env python3
"""
Pixabay Video Downloader
A tool to search and download videos from Pixabay API by topic.

Features:
- Searches Pixabay for videos by topic
- Downloads high-quality videos
- Saves to output directory with descriptive filenames
- Logs metadata for tracking
- Shows progress bar during download
"""

import sys
import json
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import re

# Progress bar
try:
    from tqdm import tqdm

    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False


class PixabayConfig:
    """Configuration manager for Pixabay API"""

    def __init__(self):
        # Use the same .env location as other LineDrive agents
        self.config_dir = Path(__file__).parent.parent.parent / "linedrive_azure/agents"
        self.env_file = self.config_dir / ".env"

    def save_api_key(self, api_key: str) -> bool:
        """Save Pixabay API key to LineDrive environment file"""
        try:
            # Create directory if it doesn't exist
            self.config_dir.mkdir(parents=True, exist_ok=True)

            # Load existing environment file if it exists
            existing_lines = []
            if self.env_file.exists():
                with open(self.env_file, "r", encoding="utf-8") as f:
                    existing_lines = f.read().splitlines()

            # Update or add PIXABAY_API_KEY
            found = False
            updated_lines = []
            for line in existing_lines:
                if line.startswith("PIXABAY_API_KEY="):
                    updated_lines.append(f"PIXABAY_API_KEY={api_key}")
                    found = True
                else:
                    updated_lines.append(line)

            if not found:
                updated_lines.append(f"PIXABAY_API_KEY={api_key}")

            # Write back to file
            with open(self.env_file, "w", encoding="utf-8") as f:
                f.write("\n".join(updated_lines) + "\n")

            return True
        except Exception as e:
            print(f"Error saving API key: {e}")
            return False

    def get_api_key(self) -> Optional[str]:
        """Get Pixabay API key from environment file"""
        if not self.env_file.exists():
            return None

        try:
            with open(self.env_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("PIXABAY_API_KEY="):
                        return line.split("=", 1)[1].strip()
        except Exception as e:
            print(f"Error reading API key: {e}")
        return None


class PixabayVideoDownloader:
    """Pixabay video downloader and search tool"""

    def __init__(self, api_key: Optional[str] = None):
        self.config = PixabayConfig()

        # Get API key - use provided key or stored key
        self.api_key = api_key or self.config.get_api_key()

        # If no stored key and no provided key, use the provided key from user
        if not self.api_key and api_key:
            self.api_key = api_key
            # Save it for future use
            self.config.save_api_key(api_key)

        if not self.api_key:
            self._setup_api_key()

        self.base_url = "https://pixabay.com/api/videos/"

        # Setup output directory
        self.output_dir = Path.home() / "Dev/Videos/bRoll"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Setup metadata log file
        metadata_filename = "pixabay_video_metadata_log.json"
        self.metadata_file = self.output_dir / metadata_filename
        self.metadata_log = self._load_metadata_log()

    def _setup_api_key(self):
        """Interactive setup for Pixabay API key"""
        print("🔑 Pixabay API Key Setup")
        print("=" * 40)
        print("To use this tool, you need a free Pixabay API key.")
        print("Get one at: https://pixabay.com/accounts/register/")
        print()

        api_key = input("Enter your Pixabay API key: ").strip()
        if not api_key:
            print("❌ No API key provided. Exiting.")
            sys.exit(1)

        if self.config.save_api_key(api_key):
            self.api_key = api_key
            print("✅ API key configured successfully!")
        else:
            print("❌ Failed to save API key. Exiting.")
            sys.exit(1)

    def _load_metadata_log(self) -> List[Dict[str, Any]]:
        """Load existing metadata log"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ Error loading metadata log: {e}")
        return []

    def _save_metadata_log(self):
        """Save metadata log to file"""
        try:
            with open(self.metadata_file, "w", encoding="utf-8") as f:
                json.dump(self.metadata_log, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Error saving metadata log: {e}")

    def search_videos(self, query: str, per_page: int = 15) -> List[Dict[str, Any]]:
        """Search for videos by topic"""
        print(f"🔍 Searching Pixabay for videos: '{query}'...")

        try:
            response = requests.get(
                self.base_url,
                params={
                    "key": self.api_key,
                    "q": query,
                    "video_type": "film",  # Prefer film quality
                    "per_page": min(per_page, 20),  # Max 20 per request
                    "safesearch": "true",
                    "order": "popular",  # Get popular videos first
                },
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                videos = data.get("hits", [])
                print(f"✅ Found {len(videos)} videos on Pixabay")
                return videos
            elif response.status_code == 429:
                print("⚠️ Rate limit exceeded. Please wait and try again.")
                return []
            else:
                print(f"❌ Pixabay search failed: HTTP {response.status_code}")
                print(f"Response: {response.text}")
                return []

        except requests.exceptions.RequestException as e:
            print(f"❌ Network error during Pixabay search: {e}")
            return []

    def get_best_quality_video_url(self, video: Dict[str, Any]) -> Optional[str]:
        """Get the best quality video URL from available sizes"""
        # Pixabay provides different video sizes - prefer larger/higher quality
        size_priority = ["large", "medium", "small", "tiny"]

        for size in size_priority:
            video_url = video.get("videos", {}).get(size, {}).get("url")
            if video_url:
                return video_url

        return None

    def download_video(
        self, video: Dict[str, Any], filename_base: str
    ) -> Optional[str]:
        """Download a video with progress bar"""
        try:
            # Get best quality video URL
            video_url = self.get_best_quality_video_url(video)
            if not video_url:
                print("❌ No video URL found")
                return None

            # Create safe filename
            safe_filename_base = re.sub(r'[<>:"/\\|?*]', "_", filename_base)
            filename = f"Pixabay_{safe_filename_base}_{video['id']}.mp4"
            filepath = self.output_dir / filename

            # Check if already exists
            if filepath.exists():
                print(f"⚠️ File already exists: {filename}")
                return str(filepath)

            print(f"📥 Downloading from Pixabay: {filename}")

            # Download with progress bar
            response = requests.get(video_url, stream=True, timeout=60)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))

            if TQDM_AVAILABLE and total_size > 0:
                with open(filepath, "wb") as f, tqdm(
                    desc=filename[:30],
                    total=total_size,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                ) as pbar:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))
            else:
                # Simple download without progress bar
                with open(filepath, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

            # Log metadata
            metadata = {
                "filename": filename,
                "pixabay_id": video["id"],
                "tags": video.get("tags", ""),
                "user": video.get("user", "Unknown"),
                "duration": video.get("duration", 0),
                "download_url": video_url,
                "download_timestamp": datetime.now().isoformat(),
                "search_query": filename_base,
                "views": video.get("views", 0),
                "downloads": video.get("downloads", 0),
                "source": "Pixabay",
            }

            self.metadata_log.append(metadata)
            self._save_metadata_log()

            return str(filepath)

        except Exception as e:
            print(f"❌ Error downloading video: {e}")
            return None

    def search_and_download(self, query: str, max_videos: int = 3) -> List[str]:
        """Search for videos and download the best ones"""
        print(f"\n🎬 Pixabay Video Search & Download: '{query}'")
        print("=" * 50)

        videos = self.search_videos(query, per_page=min(max_videos * 2, 20))
        if not videos:
            return []

        downloaded_files = []

        for i, video in enumerate(videos[:max_videos], 1):
            print(f"\n📱 Video {i}/{max_videos}:")
            print(f"   📊 Views: {video.get('views', 0):,}")
            print(f"   ⏱️ Duration: {video.get('duration', 0)}s")
            print(f"   👤 User: {video.get('user', 'Unknown')}")

            # Create descriptive filename
            tags = video.get("tags", query).replace(",", "_").replace(" ", "_")
            filename_base = f"{query.replace(' ', '_')}_{tags[:30]}"

            downloaded_file = self.download_video(video, filename_base)
            if downloaded_file:
                downloaded_files.append(downloaded_file)
                file_size = Path(downloaded_file).stat().st_size / (1024 * 1024)
                filename = Path(downloaded_file).name
                print(f"   ✅ Downloaded: {filename} " f"({file_size:.1f} MB)")
            else:
                print("   ❌ Download failed")

        print("\n🎉 Pixabay download complete!")
        print(f"📊 Downloaded {len(downloaded_files)}/{max_videos} videos")

        return downloaded_files


def main():
    """CLI interface for Pixabay video downloader"""
    print("🎬 Pixabay Video Downloader")
    print("=" * 40)

    # Use the provided API key
    api_key = "52113911-b5f6394f010b214e1f07599f2"
    downloader = PixabayVideoDownloader(api_key=api_key)

    while True:
        try:
            query = input("\n🔍 Enter search query (or 'quit' to exit): ").strip()
            if query.lower() in ["quit", "exit", "q"]:
                break
            if not query:
                print("❌ Please enter a search query")
                continue

            max_videos = input("📊 Max videos to download (default: 3): ").strip()
            try:
                max_videos = int(max_videos) if max_videos else 3
                max_videos = max(1, min(max_videos, 10))  # Limit between 1-10
            except ValueError:
                max_videos = 3

            downloaded_files = downloader.search_and_download(query, max_videos)

            if downloaded_files:
                print(f"\n📁 Files saved to: {downloader.output_dir}")
                for file_path in downloaded_files:
                    print(f"   • {Path(file_path).name}")
            else:
                print("\n⚠️ No videos were downloaded")

        except KeyboardInterrupt:
            print("\n\n👋 Download interrupted by user")
            break
        except EOFError:
            break

    print("\n👋 Goodbye!")


if __name__ == "__main__":
    main()
