#!/usr/bin/env python3
"""
Pexels Video Downloader
A tool to search and download videos from Pexels API by topic.

Features:
- Searches Pexels for videos by topic
- Downloads watermark-free videos
- Saves to iCloud directory with descriptive filenames
- Logs metadata for tracking
- Shows progress bar during download
"""

import os
import sys
import json
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

# Progress bar
try:
    from tqdm import tqdm

    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False


class PexelsConfig:
    """Configuration manager for Pexels API"""

    def __init__(self):
        # Use the same .env location as other LineDrive agents
        # Go up to project root and then to linedrive_azure/agents
        project_root = Path(__file__).parent.parent.parent
        self.config_dir = project_root / "linedrive_azure/agents"
        self.env_file = self.config_dir / ".env"

    def save_api_key(self, api_key: str) -> bool:
        """Save Pexels API key to LineDrive environment file"""
        try:
            # Load existing environment file if it exists
            existing_lines = []
            if self.env_file.exists():
                with open(self.env_file, "r", encoding="utf-8") as f:
                    existing_lines = f.read().splitlines()

            # Update or add PEXELS_API_KEY
            found = False
            updated_lines = []

            for line in existing_lines:
                if line.startswith("PEXELS_API_KEY="):
                    updated_lines.append(f"PEXELS_API_KEY={api_key}")
                    found = True
                else:
                    updated_lines.append(line)

            if not found:
                updated_lines.append(f"PEXELS_API_KEY={api_key}")

            # Write back to file
            with open(self.env_file, "w", encoding="utf-8") as f:
                f.write("\n".join(updated_lines) + "\n")

            os.chmod(self.env_file, 0o600)
            print(f"✅ Pexels API key saved to: {self.env_file}")
            return True

        except Exception as e:
            print(f"❌ Error saving API key: {e}")
            return False

    def get_api_key(self) -> Optional[str]:
        """Get Pexels API key from environment or config file"""
        # First try environment variable
        api_key = os.environ.get("PEXELS_API_KEY")
        if api_key:
            return api_key

        # Try LineDrive environment file
        if self.env_file.exists():
            try:
                with open(self.env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("PEXELS_API_KEY="):
                            return line.split("=", 1)[1].strip()
            except Exception as e:
                print(f"⚠️ Error reading environment file: {e}")

        return None

    def has_api_key(self) -> bool:
        """Check if API key is configured"""
        return self.get_api_key() is not None


class PexelsVideoDownloader:
    """Pexels video downloader with progress tracking and metadata logging"""

    def __init__(self, api_key: Optional[str] = None):
        self.config = PexelsConfig()

        # Get API key
        self.api_key = api_key or self.config.get_api_key()

        if not self.api_key:
            self._setup_api_key()

        self.base_url = "https://api.pexels.com/videos"
        self.headers = {"Authorization": self.api_key, "User-Agent": "LineDrive/1.0"}

        # Setup output directory
        self.output_dir = Path.home() / "Dev/Videos/bRoll"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Setup metadata log file
        self.metadata_file = self.output_dir / "video_metadata_log.json"
        self.metadata_log = self._load_metadata_log()

    def _setup_api_key(self):
        """Interactive setup for Pexels API key"""
        print("🔑 Pexels API Key Setup")
        print("=" * 40)
        print("To use this tool, you need a free Pexels API key.")
        print("Get one at: https://www.pexels.com/api/")
        print()

        api_key = input("Enter your Pexels API key: ").strip()
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
        print(f"🔍 Searching Pexels for videos: '{query}'...")

        try:
            response = requests.get(
                f"{self.base_url}/search",
                headers=self.headers,
                params={
                    "query": query,
                    "per_page": per_page,
                    "orientation": "landscape",  # Better for b-roll
                },
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                videos = data.get("videos", [])
                print(f"✅ Found {len(videos)} videos")
                return videos
            elif response.status_code == 429:
                print("⚠️ Rate limit exceeded. Please wait and try again.")
                return []
            else:
                print(f"❌ Search failed: HTTP {response.status_code}")
                print(f"Response: {response.text}")
                return []

        except requests.exceptions.RequestException as e:
            print(f"❌ Network error during search: {e}")
            return []

    def get_best_quality_file(self, video: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get the best quality video file from available files"""
        video_files = video.get("video_files", [])
        if not video_files:
            return None

        # Priority: HD > SD > any other quality
        # Also prefer mp4 format
        quality_priority = ["hd", "sd"]

        for quality in quality_priority:
            for file_info in video_files:
                if (
                    file_info.get("quality") == quality
                    and file_info.get("file_type") == "video/mp4"
                ):
                    return file_info

        # Fallback to first available mp4 file
        for file_info in video_files:
            if file_info.get("file_type") == "video/mp4":
                return file_info

        # Last resort: any file
        return video_files[0] if video_files else None

    def download_video(self, video: Dict[str, Any], topic: str) -> Optional[str]:
        """Download a video with progress bar"""
        try:
            # Get best quality file
            file_info = self.get_best_quality_file(video)
            if not file_info:
                print("❌ No suitable video file found")
                return None

            download_url = file_info["link"]
            quality = file_info.get("quality", "unknown")
            duration = video.get("duration", 0)

            # Create filename
            safe_topic = "".join(
                c for c in topic if c.isalnum() or c in (" ", "-", "_")
            ).strip()
            safe_topic = safe_topic.replace(" ", "_")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{safe_topic}_{quality}_{duration}s_{timestamp}.mp4"

            # Use the current output_dir (which may have been updated)
            filepath = Path(self.output_dir) / filename

            print(f"📥 Downloading: {filename}")
            print(f"   Quality: {quality}")
            print(f"   Duration: {duration}s")
            print(
                f"   Size: {file_info.get('width', 'unknown')}x{file_info.get('height', 'unknown')}"
            )

            # Download with progress bar
            response = requests.get(download_url, stream=True, timeout=60)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))

            if TQDM_AVAILABLE and total_size > 0:
                with open(filepath, "wb") as f:
                    with tqdm(
                        total=total_size, unit="B", unit_scale=True, desc="Downloading"
                    ) as pbar:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                pbar.update(len(chunk))
            else:
                # Simple progress without tqdm
                with open(filepath, "wb") as f:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                percent = (downloaded / total_size) * 100
                                print(
                                    f"\r📥 Progress: {percent:.1f}%", end="", flush=True
                                )
                    print()  # New line after progress

            # Log metadata
            metadata = {
                "timestamp": datetime.now().isoformat(),
                "topic": topic,
                "filename": filename,
                "filepath": str(filepath),
                "source": "Pexels",
                "video_id": video.get("id"),
                "title": safe_topic,
                "url": video.get("url"),
                "photographer": video.get("user", {}).get("name", "Unknown"),
                "photographer_url": video.get("user", {}).get("url"),
                "duration": duration,
                "quality": quality,
                "resolution": f"{file_info.get('width', 'unknown')}x{file_info.get('height', 'unknown')}",
                "file_size_bytes": filepath.stat().st_size,
                "license": "Pexels License (Free to use)",
                "license_url": "https://www.pexels.com/license/",
            }

            self.metadata_log.append(metadata)
            self._save_metadata_log()

            print(f"✅ Downloaded successfully: {filepath}")
            print(f"📄 File size: {filepath.stat().st_size / (1024*1024):.1f} MB")
            return str(filepath)

        except requests.exceptions.RequestException as e:
            print(f"❌ Download failed: {e}")
            return None
        except Exception as e:
            print(f"❌ Unexpected error during download: {e}")
            return None

    def download_video_by_topic(self, topic: str) -> Optional[str]:
        """Main method: search and download one video by topic"""
        print(f"\n🎥 PEXELS VIDEO DOWNLOADER")
        print("=" * 50)
        print(f"Topic: {topic}")
        print(f"Output Directory: {self.output_dir}")
        print()

        # Search for videos
        videos = self.search_videos(topic)
        if not videos:
            print("❌ No videos found for this topic")
            return None

        # Display options
        print(f"\n📋 Available videos ({len(videos)} found):")
        for i, video in enumerate(videos[:10]):  # Show top 10
            photographer = video.get("user", {}).get("name", "Unknown")
            duration = video.get("duration", 0)
            print(f"  {i+1}. By {photographer} - {duration}s")

        # Auto-select first video for now (can be made interactive)
        selected_video = videos[0]
        print(
            f"\n✅ Auto-selected: Video by {selected_video.get('user', {}).get('name', 'Unknown')}"
        )

        # Download the video
        return self.download_video(selected_video, topic)

    def show_metadata_log(self):
        """Display recent downloads"""
        if not self.metadata_log:
            print("📋 No downloads recorded yet")
            return

        print(f"\n📋 DOWNLOAD HISTORY ({len(self.metadata_log)} videos)")
        print("=" * 50)

        for i, entry in enumerate(reversed(self.metadata_log[-10:])):  # Show last 10
            print(f"{i+1}. {entry['filename']}")
            print(f"   Topic: {entry['topic']}")
            print(f"   Date: {entry['timestamp'][:19]}")
            print(f"   Duration: {entry['duration']}s")
            print(f"   Size: {entry['file_size_bytes'] / (1024*1024):.1f} MB")
            print()


def install_requirements():
    """Install required packages"""
    print("📦 Checking/installing required packages...")

    packages_to_install = []

    # Check for requests
    try:
        import requests

        print("✅ requests available")
    except ImportError:
        packages_to_install.append("requests")

    # Check for tqdm (optional)
    try:
        import tqdm

        print("✅ tqdm available")
    except ImportError:
        packages_to_install.append("tqdm")
        print("⚠️ tqdm not available (progress bars will be basic)")

    if packages_to_install:
        print(f"📦 Installing: {', '.join(packages_to_install)}")
        import subprocess

        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", *packages_to_install]
            )
            print("✅ Packages installed successfully!")
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to install packages: {e}")
            print("Please run: pip install requests tqdm")
            return False

    return True


def main():
    """Main interactive interface"""
    print("🎥 PEXELS VIDEO DOWNLOADER")
    print("=" * 40)
    print("Download free, watermark-free videos from Pexels for b-roll content")
    print()

    # Install requirements if needed
    if not install_requirements():
        sys.exit(1)

    try:
        downloader = PexelsVideoDownloader()

        while True:
            print("\n📋 OPTIONS:")
            print("1. 🔍 Download video by topic")
            print("2. 📋 Show download history")
            print("3. 🔧 Reconfigure API key")
            print("4. ❌ Exit")

            choice = input("\n👆 Select option (1-4): ").strip()

            if choice == "1":
                topic = input(
                    "\n🎯 Enter video topic (e.g., 'AI Robot', 'Technology'): "
                ).strip()
                if topic:
                    result = downloader.download_video_by_topic(topic)
                    if result:
                        print(f"\n🎉 Success! Video saved to: {result}")
                    else:
                        print("\n❌ Download failed")
                else:
                    print("❌ Topic cannot be empty")

            elif choice == "2":
                downloader.show_metadata_log()

            elif choice == "3":
                downloader._setup_api_key()

            elif choice == "4":
                print("👋 Goodbye!")
                break

            else:
                print("❌ Invalid choice. Please select 1-4.")

    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
