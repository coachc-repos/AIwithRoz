#!/usr/bin/env python3
"""
YouTube Transcript Storage and Indexing System
Fetches transcripts, stores them in Data Lake, and indexes them for search
"""

import sys
import os
import json
import subprocess

# Add project root to Python path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.append("/Users/christhi/Dev/Github/linedrive")
import requests
from datetime import datetime, timezone
from azure.storage.filedatalake import DataLakeServiceClient
from azure.identity import DefaultAzureCredential

sys.path.append("/Users/christhi/Dev/Github/linedrive")

from batch_scrapers.common.youtube_transcript_grabber import fetch_youtube_transcript


class YouTubeTranscriptManager:
    def __init__(self):
        # Data Lake configuration
        self.storage_account_name = "linedrivestorage"
        self.container_name = "youtube-transcripts"
        self.account_url = f"https://{self.storage_account_name}.dfs.core.windows.net"

        # Azure Search configuration
        self.search_service_name = "linedrive-search"
        self.search_resource_group = "rg-linedrive-search"
        self.search_index_name = "youtube-transcripts-index"
        self.search_endpoint = f"https://{self.search_service_name}.search.windows.net"

        # Initialize clients
        self.credential = DefaultAzureCredential()
        self.data_lake_client = DataLakeServiceClient(
            account_url=self.account_url, credential=self.credential
        )

        self.container_client = self.data_lake_client.get_file_system_client(
            file_system=self.container_name
        )

        # Get search API key
        self.search_api_key = self._get_search_api_key()
        self.search_headers = {
            "Content-Type": "application/json",
            "api-key": self.search_api_key,
        }

    def _get_search_api_key(self):
        """Get Azure Search API key"""
        try:
            result = subprocess.run(
                [
                    "az",
                    "search",
                    "admin-key",
                    "show",
                    "--service-name",
                    self.search_service_name,
                    "--resource-group",
                    self.search_resource_group,
                    "--query",
                    "primaryKey",
                    "-o",
                    "tsv",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to get search API key: {e}")
            raise

    def fetch_and_store_transcript(
        self,
        video_id: str,
        video_title: str = None,
        channel_name: str = None,
        description: str = None,
        tags: list = None,
    ) -> dict:
        """Fetch transcript and store in both Data Lake and Search Index"""

        print(f"📹 Processing video: {video_id}")

        # Fetch transcript using existing grabber
        try:
            transcript = fetch_youtube_transcript(video_id)
            if not transcript:
                print(f"   ❌ No transcript available for {video_id}")
                return {"success": False, "error": "No transcript available"}

            print(f"   ✅ Transcript fetched: {len(transcript)} segments")

        except Exception as e:
            print(f"   ❌ Error fetching transcript: {e}")
            return {"success": False, "error": str(e)}

        # Process transcript data
        full_transcript = " ".join([segment.get("text", "") for segment in transcript])
        word_count = len(full_transcript.split())
        duration = max(
            [
                segment.get("start", 0) + segment.get("duration", 0)
                for segment in transcript
            ]
        )

        # Create transcript document
        timestamp = datetime.now(timezone.utc)
        document = {
            "video_id": video_id,
            "video_title": video_title or f"Video {video_id}",
            "channel_name": channel_name or "Unknown Channel",
            "host": channel_name or "Unknown Host",
            "video_url": f"https://youtube.com/watch?v={video_id}",
            "transcript_text": full_transcript,
            "transcript_segments": transcript,
            "video_description": description or "No description available",
            "video_tags": tags or [],
            "video_duration": str(int(duration)),
            "word_count": word_count,
            "segment_count": len(transcript),
            "publish_date": timestamp.isoformat(),
            "created_at": timestamp.isoformat(),
            "language": "en",
            "processed_at": timestamp.isoformat(),
        }

        print(f"   📊 Word count: {word_count}, Duration: {duration:.0f}s")

        # Store in Data Lake
        try:
            self._store_in_data_lake(video_id, document)
            print(f"   ✅ Stored in Data Lake")
        except Exception as e:
            print(f"   ❌ Data Lake storage failed: {e}")
            return {"success": False, "error": f"Data Lake storage failed: {e}"}

        # Index in Search
        try:
            self._index_in_search(document)
            print(f"   ✅ Indexed for search")
        except Exception as e:
            print(f"   ❌ Search indexing failed: {e}")
            return {"success": False, "error": f"Search indexing failed: {e}"}

        return {
            "success": True,
            "video_id": video_id,
            "word_count": word_count,
            "duration": duration,
            "segments": len(transcript),
        }

    def process_video_batch(self, video_ids: list, max_workers: int = 3) -> dict:
        """
        Process multiple videos in batch

        Args:
            video_ids: List of YouTube video IDs to process
            max_workers: Maximum number of concurrent workers (default: 3)

        Returns:
            Dict with batch processing results
        """
        import concurrent.futures
        import time

        print(f"🎬 Starting batch processing of {len(video_ids)} videos")
        print(f"📊 Using {max_workers} concurrent workers")
        print("=" * 60)

        batch_start_time = time.time()
        results = {
            "total_videos": len(video_ids),
            "successful": [],
            "failed": [],
            "processing_time": 0,
            "total_words": 0,
            "total_duration": 0,
        }

        def process_single_video(video_id):
            """Process a single video and return result"""
            try:
                print(f"\n🔄 Processing: {video_id}")
                result = self.fetch_and_store_transcript(video_id)
                if result["success"]:
                    print(f"✅ Completed: {video_id}")
                    return {"video_id": video_id, "status": "success", "data": result}
                else:
                    print(
                        f"❌ Failed: {video_id} - {result.get('error', 'Unknown error')}"
                    )
                    return {
                        "video_id": video_id,
                        "status": "failed",
                        "error": result.get("error", "Unknown error"),
                    }
            except Exception as e:
                print(f"💥 Exception for {video_id}: {str(e)}")
                return {"video_id": video_id, "status": "failed", "error": str(e)}

        # Process videos with thread pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all jobs
            future_to_video = {
                executor.submit(process_single_video, video_id): video_id
                for video_id in video_ids
            }

            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_video):
                video_id = future_to_video[future]
                try:
                    result = future.result()
                    if result["status"] == "success":
                        results["successful"].append(result)
                        # Accumulate stats
                        if "data" in result:
                            results["total_words"] += result["data"].get(
                                "word_count", 0
                            )
                            results["total_duration"] += result["data"].get(
                                "duration", 0
                            )
                    else:
                        results["failed"].append(result)

                except Exception as e:
                    print(f"💥 Exception collecting result for {video_id}: {str(e)}")
                    results["failed"].append(
                        {
                            "video_id": video_id,
                            "status": "failed",
                            "error": f"Result collection failed: {str(e)}",
                        }
                    )

        batch_end_time = time.time()
        results["processing_time"] = batch_end_time - batch_start_time

        # Print summary
        print("\n" + "=" * 60)
        print("📊 BATCH PROCESSING COMPLETE")
        print("=" * 60)
        print(f"✅ Successful: {len(results['successful'])}/{results['total_videos']}")
        print(f"❌ Failed: {len(results['failed'])}/{results['total_videos']}")
        print(f"⏱️  Total time: {results['processing_time']:.2f} seconds")
        print(f"📝 Total words processed: {results['total_words']:,}")
        print(
            f"🎥 Total video duration: {results['total_duration']:.0f} seconds ({results['total_duration']/60:.1f} minutes)"
        )

        if results["failed"]:
            print(f"\n❌ Failed videos:")
            for failed in results["failed"]:
                print(f"   • {failed['video_id']}: {failed['error']}")

        return results

    def _store_in_data_lake(self, video_id: str, document: dict):
        """Store transcript document in Data Lake"""

        # Create file path: yyyy/mm/dd/video_id.json
        date_path = datetime.now().strftime("%Y/%m/%d")
        file_path = f"{date_path}/{video_id}.json"

        # Convert document to JSON
        json_data = json.dumps(document, indent=2, ensure_ascii=False)

        # Upload to Data Lake
        file_client = self.container_client.get_file_client(file_path)
        file_client.upload_data(data=json_data.encode("utf-8"), overwrite=True)

        return file_path

    def _index_in_search(self, document: dict):
        """Index document in Azure Search"""

        # Prepare document for search (remove fields not in search schema)
        search_document = {
            "@search.action": "upload",
            "id": document["video_id"],  # Add required key field
            "video_id": document["video_id"],
            "video_title": document["video_title"],
            "channel_name": document["channel_name"],
            "host": document["host"],
            "video_url": document["video_url"],
            "transcript_text": document["transcript_text"],
            "video_description": document["video_description"],
            "video_tags": document["video_tags"],
            "video_duration": document["video_duration"],
            "publish_date": document["publish_date"],
            "created_at": document["created_at"],
            "language": document["language"],
        }

        # Upload to search index
        upload_url = f"{self.search_endpoint}/indexes/{self.search_index_name}/docs/index?api-version=2023-11-01"
        upload_data = {"value": [search_document]}

        response = requests.post(
            upload_url, headers=self.search_headers, json=upload_data, timeout=30
        )

        if response.status_code not in [200, 201]:
            raise Exception(
                f"Search upload failed: {response.status_code} - {response.text}"
            )

        return response.json()


def process_video_list(video_ids: list, max_workers: int = 3) -> dict:
    """
    Process a list of video IDs in batch

    Args:
        video_ids: List of YouTube video IDs (can be URLs or just IDs)
        max_workers: Maximum number of concurrent workers

    Returns:
        Dict with batch processing results
    """
    print("🎬 YOUTUBE TRANSCRIPT BATCH PROCESSOR")
    print("=" * 60)
    print(f"🕐 Started at: {datetime.now().strftime('%H:%M:%S')}")
    print()

    # Initialize manager
    try:
        manager = YouTubeTranscriptManager()
        print("✅ YouTube Transcript Manager initialized")
    except Exception as e:
        print(f"❌ Failed to initialize manager: {e}")
        return {"success": False, "error": str(e)}

    # Clean video IDs (extract from URLs if needed)
    cleaned_ids = []
    for video_id in video_ids:
        # Extract video ID from URL if needed
        if "youtube.com/watch?v=" in video_id:
            video_id = video_id.split("v=")[1].split("&")[0]
        elif "youtu.be/" in video_id:
            video_id = video_id.split("youtu.be/")[1].split("?")[0]

        if video_id and len(video_id) == 11:  # YouTube video IDs are 11 characters
            cleaned_ids.append(video_id)
        else:
            print(f"⚠️  Invalid video ID/URL: {video_id}")

    if not cleaned_ids:
        print("❌ No valid video IDs found")
        return {"success": False, "error": "No valid video IDs"}

    print(f"🎯 Processing {len(cleaned_ids)} valid video IDs...")
    print()

    # Process the batch
    results = manager.process_video_batch(cleaned_ids, max_workers=max_workers)

    print(f"\n🏁 Batch processing completed at: {datetime.now().strftime('%H:%M:%S')}")

    if results["successful"]:
        print("\n🔍 Testing search functionality...")
        try:
            from linedrive_azure.agents.youtube_transcript_functions import (
                YouTubeTranscriptSearcher,
            )

            searcher = YouTubeTranscriptSearcher()
            test_results = searcher.search_youtube_transcripts(
                query="*", max_results=5  # Search for all documents
            )

            print(
                f"   ✅ Search working: {test_results.get('total_results', 0)} total documents indexed"
            )

        except Exception as e:
            print(f"   ❌ Search test failed: {e}")

    return results


def populate_youtube_data():
    """Main function to populate YouTube transcript data"""

    print("🎬 YOUTUBE TRANSCRIPT STORAGE & INDEXING")
    print("=" * 60)
    print(f"🕐 Started at: {datetime.now().strftime('%H:%M:%S')}")
    print()

    # Initialize manager
    try:
        manager = YouTubeTranscriptManager()
        print("✅ YouTube Transcript Manager initialized")
    except Exception as e:
        print(f"❌ Failed to initialize manager: {e}")
        return

    # Sample videos to process
    sample_videos = [
        {
            "video_id": "dQw4w9WgXcQ",
            "title": "Rick Astley - Never Gonna Give You Up (Official Video)",
            "channel": "Rick Astley",
            "description": "The official video for Rick Astley's Never Gonna Give You Up",
            "tags": ["music", "classic", "rick astley", "never gonna give you up"],
        },
        {
            "video_id": "E1rHbyZ03T0",
            "title": "GPT-5 and AI Technology Discussion",
            "channel": "AI Technology Channel",
            "description": "Discussion about GPT-5 and latest AI developments",
            "tags": ["ai", "gpt", "technology", "openai", "machine learning"],
        },
    ]

    print(f"🎯 Processing {len(sample_videos)} videos...")
    print()

    successful_processes = 0

    for video_info in sample_videos:
        result = manager.fetch_and_store_transcript(
            video_id=video_info["video_id"],
            video_title=video_info["title"],
            channel_name=video_info["channel"],
            description=video_info["description"],
            tags=video_info["tags"],
        )

        if result.get("success"):
            successful_processes += 1

        print()

    print(
        f"📊 Results: {successful_processes}/{len(sample_videos)} videos processed successfully"
    )

    # Test the system
    if successful_processes > 0:
        print("\n🔍 Testing the complete system...")

        # Test Data Lake storage
        print("📁 Checking Data Lake storage...")
        try:
            subprocess.run(
                [
                    "az",
                    "storage",
                    "fs",
                    "file",
                    "list",
                    "--file-system",
                    "youtube-transcripts",
                    "--account-name",
                    "linedrivestorage",
                    "--auth-mode",
                    "login",
                    "-o",
                    "table",
                ],
                check=False,
            )  # Don't fail if this doesn't work
        except Exception as e:
            print(f"   Note: Could not list Data Lake files: {e}")

        # Test search functionality
        print("\n🔎 Testing search functionality...")
        try:
            from linedrive_azure.agents.youtube_transcript_functions import (
                YouTubeTranscriptSearcher,
            )

            searcher = YouTubeTranscriptSearcher()
            results = searcher.search_youtube_transcripts(
                query="AI technology", max_results=3
            )

            print(
                f"   ✅ Search working: {results.get('total_results', 0)} total documents"
            )

            if results.get("videos"):
                print("   📋 Sample results:")
                for video in results["videos"][:2]:
                    print(f"   - {video.get('video_title', 'No title')}")
                    print(f"     Channel: {video.get('channel_name', 'Unknown')}")

        except Exception as e:
            print(f"   ❌ Search test failed: {e}")

    print(f"\n🏁 Process completed at: {datetime.now().strftime('%H:%M:%S')}")
    print("\n🎉 YouTube transcript system should now be fully operational!")
    print("📁 Data stored in Data Lake: youtube-transcripts container")
    print("🔍 Data indexed for search in Azure Search")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="YouTube Transcript Batch Processor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Process sample videos:
    python tools/youtube/setup_youtube_system.py
    
    # Process specific video IDs:
    python tools/youtube/setup_youtube_system.py --videos dQw4w9WgXcQ E1rHbyZ03T0 9bZkp7q19f0
    
    # Process from URLs:
    python tools/youtube/setup_youtube_system.py --videos "https://youtube.com/watch?v=dQw4w9WgXcQ" "https://youtu.be/E1rHbyZ03T0"
    
    # Process from JSON file:
    python tools/youtube/setup_youtube_system.py --file config/sample_video_list.json
    
    # Process with more workers:
    python tools/youtube/setup_youtube_system.py --videos dQw4w9WgXcQ E1rHbyZ03T0 --workers 5
    
    # Combine file and command line:
    python tools/youtube/setup_youtube_system.py --file config/sample_video_list.json --videos dQw4w9WgXcQ --workers 4
        """,
    )

    parser.add_argument(
        "--videos", nargs="*", help="List of YouTube video IDs or URLs to process"
    )

    parser.add_argument(
        "--file", type=str, help="JSON file containing list of video IDs or URLs"
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Number of concurrent workers (default: 3)",
    )

    args = parser.parse_args()

    video_list = []

    # Get videos from file if specified
    if args.file:
        try:
            with open(args.file, "r") as f:
                file_data = json.load(f)
                if isinstance(file_data, list):
                    video_list.extend(file_data)
                else:
                    print(
                        f"❌ File {args.file} should contain a JSON array of video IDs"
                    )
                    exit(1)
        except Exception as e:
            print(f"❌ Error reading file {args.file}: {e}")
            exit(1)

    # Add videos from command line
    if args.videos:
        video_list.extend(args.videos)

    if video_list:
        # Process the video list
        results = process_video_list(video_list, max_workers=args.workers)

        # Exit with appropriate code
        if results.get("failed"):
            exit(1)  # Some failures occurred
        elif not results.get("successful"):
            exit(2)  # No successful processing
        else:
            exit(0)  # All good
    else:
        # Run default sample processing
        populate_youtube_data()
