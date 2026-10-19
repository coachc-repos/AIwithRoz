#!/usr/bin/env python3
"""
YouTube Transcript Index Populator
Populates the Azure Search index with YouTube transcript data
"""

import sys
import os
import json
import requests
import subprocess
from datetime import datetime

sys.path.append("/Users/christhi/Dev/Github/linedrive")
sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from batch_scrapers.common.youtube_transcript_grabber import fetch_youtube_transcript


def populate_youtube_search_index():
    print("📚 YOUTUBE TRANSCRIPT INDEX POPULATOR")
    print("=" * 60)
    print(f"🕐 Started at: {datetime.now().strftime('%H:%M:%S')}")
    print()

    # Azure Search configuration
    service_name = "linedrive-search"
    resource_group = "rg-linedrive-search"
    index_name = "youtube-transcripts-index"

    # Get API key
    print("🔑 Getting Azure Search API key...")
    try:
        result = subprocess.run(
            [
                "az",
                "search",
                "admin-key",
                "show",
                "--service-name",
                service_name,
                "--resource-group",
                resource_group,
                "--query",
                "primaryKey",
                "-o",
                "tsv",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        api_key = result.stdout.strip()
        print("✅ API key retrieved")

    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to get API key: {e}")
        return

    # Setup search client
    endpoint = f"https://{service_name}.search.windows.net"
    headers = {"Content-Type": "application/json", "api-key": api_key}

    # Sample YouTube videos to index (popular tech/AI content)
    sample_videos = [
        {
            "video_id": "dQw4w9WgXcQ",
            "expected_title": "Rick Astley - Never Gonna Give You Up",
            "channel": "Rick Astley",
            "description": "Classic music video",
            "tags": ["music", "classic", "meme"],
        },
        {
            "video_id": "E1rHbyZ03T0",
            "expected_title": "GPT-5 Related Content",
            "channel": "AI Tech Channel",
            "description": "AI and GPT technology discussion",
            "tags": ["ai", "gpt", "technology", "openai"],
        },
    ]

    print(f"🎯 Indexing {len(sample_videos)} YouTube transcripts...")
    print()

    documents_to_index = []

    for i, video_info in enumerate(sample_videos, 1):
        video_id = video_info["video_id"]
        print(f"📹 Processing video {i}: {video_id}")

        try:
            # Fetch transcript
            transcript = fetch_youtube_transcript(video_id)

            if transcript:
                # Prepare document for indexing
                full_transcript = " ".join(
                    [segment.get("text", "") for segment in transcript]
                )

                document = {
                    "@search.action": "upload",
                    "video_id": video_id,
                    "video_title": video_info["expected_title"],
                    "channel_name": video_info["channel"],
                    "host": video_info["channel"],  # Using channel as host for now
                    "video_url": f"https://youtube.com/watch?v={video_id}",
                    "transcript_text": full_transcript,
                    "video_description": video_info["description"],
                    "video_tags": video_info["tags"],
                    "video_duration": f"{max([s.get('start', 0) + s.get('duration', 0) for s in transcript]):.0f}",
                    "publish_date": "2023-01-01T00:00:00Z",  # Default date
                    "created_at": datetime.now().isoformat() + "Z",
                    "language": "en",
                }

                documents_to_index.append(document)
                print(
                    f"   ✅ Prepared for indexing: {len(full_transcript.split())} words"
                )

            else:
                print("   ❌ No transcript available")

        except Exception as e:
            print(f"   ❌ Error processing video: {e}")

    if documents_to_index:
        print(f"\n📤 Uploading {len(documents_to_index)} documents to search index...")

        try:
            # Upload documents to search index
            upload_url = (
                f"{endpoint}/indexes/{index_name}/docs/index?api-version=2023-11-01"
            )
            upload_data = {"value": documents_to_index}

            response = requests.post(
                upload_url, headers=headers, json=upload_data, timeout=30
            )

            if response.status_code in [200, 201]:
                result = response.json()
                successful_uploads = len(
                    [r for r in result.get("value", []) if r.get("status")]
                )
                print(f"✅ Successfully indexed {successful_uploads} documents")

                # Test search immediately
                print("\n🔍 Testing search functionality...")

                search_url = f"{endpoint}/indexes/{index_name}/docs/search?api-version=2023-11-01"
                search_params = {
                    "search": "AI technology",
                    "top": 3,
                    "select": "video_id,video_title,channel_name",
                    "count": True,
                }

                search_response = requests.post(
                    search_url, headers=headers, json=search_params, timeout=15
                )

                if search_response.status_code == 200:
                    search_results = search_response.json()
                    total_results = search_results.get("@odata.count", 0)
                    print(f"✅ Search test successful: {total_results} total documents")

                    if search_results.get("value"):
                        print("📋 Sample search results:")
                        for result in search_results["value"]:
                            print(f"   - {result.get('video_title', 'No title')}")
                            print(
                                f"     Channel: {result.get('channel_name', 'Unknown')}"
                            )
                            print(f"     Video ID: {result.get('video_id', 'Unknown')}")
                    else:
                        print("   No matching results found")
                else:
                    print(f"❌ Search test failed: {search_response.status_code}")

            else:
                print(f"❌ Upload failed: {response.status_code}")
                print(f"   Response: {response.text[:300]}")

        except Exception as e:
            print(f"❌ Upload error: {e}")

    else:
        print("❌ No documents prepared for indexing")

    print(f"\n🏁 Index population completed at: {datetime.now().strftime('%H:%M:%S')}")
    print("\n🎉 YouTube transcript search should now be working!")


if __name__ == "__main__":
    populate_youtube_search_index()
