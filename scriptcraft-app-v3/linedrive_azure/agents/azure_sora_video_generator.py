"""
Azure OpenAI SORA Video Generation Client for Script Visual Cues
Extracts visual cues from scripts and generates professional videos using Azure OpenAI SORA
"""

import requests
import json
import re
import time
import os
from datetime import datetime
from typing import List, Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AzureSoraVideoGenerator:
    def __init__(self):
        # Azure AI Foundry SORA endpoint configuration (based on working curl example)
        self.base_url = os.environ.get("AZURE_AI_SERVICES_ENDPOINT", "https://coach-me1k8xkn-eastus2.cognitiveservices.azure.com")
        self.api_key = os.environ.get("AZURE_AI_SERVICES_KEY", "")

        # Correct endpoint format from AI Foundry curl example
        self.endpoint = (
            f"{self.base_url}/openai/v1/video/generations/jobs?api-version=preview"
        )
        self.status_endpoint_base = f"{self.base_url}/openai/v1/video/generations/jobs"

        self.headers = {
            "Content-Type": "application/json",
            "Api-key": self.api_key,  # Note: "Api-key" not "api-key" as per curl example
        }

    def extract_visual_cues(self, script_content: str) -> List[Dict[str, str]]:
        """Extract visual cues from script content - Enhanced with content analysis"""
        visual_cues = []

        # Pattern to match various visual cue formats (existing functionality)
        patterns = [
            r"\[.*?CUT TO VISUAL AID:\s*(.*?)\]",
            r"\[.*?Cut to.*?:\s*(.*?)\]",
            r"\[.*?Show.*?:\s*(.*?)\]",
            r"\[.*?Transition.*?:\s*(.*?)\]",
            r"\[.*?Scene.*?:\s*(.*?)\]",
            r"\[.*?Opening shot.*?:\s*(.*?)\]",
            r"\[.*?graphic.*?:\s*(.*?)\]",
        ]

        # Extract explicit visual cues first
        for pattern in patterns:
            matches = re.finditer(pattern, script_content, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                visual_desc = match.group(1).strip()
                if (
                    visual_desc and len(visual_desc) > 5
                ):  # Filter out very short descriptions
                    visual_cues.append(
                        {
                            "original_text": match.group(0),
                            "description": visual_desc,
                            "line_context": self._get_line_context(
                                script_content, match.start()
                            ),
                        }
                    )

        # If no explicit cues found, use intelligent content analysis
        if len(visual_cues) == 0:
            print("📍 No explicit visual cues found, analyzing content...")
            intelligent_cues = self._analyze_script_for_video_opportunities(
                script_content
            )
            visual_cues.extend(intelligent_cues)

        # Remove duplicates
        seen = set()
        unique_cues = []
        for cue in visual_cues:
            if cue["description"] not in seen:
                seen.add(cue["description"])
                unique_cues.append(cue)

        return unique_cues

    def _analyze_script_for_video_opportunities(
        self, script_content: str
    ) -> List[Dict[str, str]]:
        """Analyze script content to find intelligent video opportunities"""
        opportunities = []

        # Split into sections
        sections = re.split(r"\n\s*\n", script_content)
        meaningful_sections = [s.strip() for s in sections if len(s.strip()) > 50]

        # If not enough sections, split by sentences
        if len(meaningful_sections) < 2:
            sentences = re.split(r"[.!?]+", script_content)
            current_section = []
            current_length = 0

            for sentence in sentences:
                sentence = sentence.strip()
                if sentence:
                    current_section.append(sentence)
                    current_length += len(sentence)

                    if current_length > 200 and len(current_section) >= 2:
                        meaningful_sections.append(". ".join(current_section) + ".")
                        current_section = []
                        current_length = 0

            if current_section:
                meaningful_sections.append(". ".join(current_section) + ".")

        # Analyze each section
        for i, section in enumerate(meaningful_sections[:4]):  # Limit to 4 videos max
            topics = self._extract_topics_from_section(section)
            concepts = self._extract_concepts_from_section(section)

            if topics or concepts:
                main_topic = topics[0] if topics else "Key Concepts"
                video_prompt = self._create_contextual_prompt(section, topics, concepts)

                opportunities.append(
                    {
                        "original_text": f"[AI GENERATED CUE {i+1}]",
                        "description": video_prompt,
                        "line_context": (
                            section[:100] + "..." if len(section) > 100 else section
                        ),
                        "topic": main_topic,
                        "concepts": concepts[:3],
                    }
                )

        return opportunities

    def _extract_topics_from_section(self, text: str) -> List[str]:
        """Extract main topics from text section"""
        topic_patterns = [
            (
                r"\b(?:AI|artificial intelligence|machine learning|neural networks?|deep learning)\b",
                "AI Technology",
            ),
            (r"\bgpt[- ]?\d*\b", "GPT AI Models"),
            (
                r"\b(?:algorithm|automation|data|analytics|cloud computing)\b",
                "Technology Systems",
            ),
            (
                r"\b(?:blockchain|cryptocurrency|bitcoin|web3)\b",
                "Blockchain Technology",
            ),
            (
                r"\b(?:strategy|growth|revenue|profit|market|business model)\b",
                "Business Strategy",
            ),
            (r"\b(?:innovation|disruption|transformation|evolution)\b", "Innovation"),
            (
                r"\b(?:productivity|efficiency|optimization|performance)\b",
                "Performance",
            ),
            (r"\b(?:learning|education|teaching|training|development)\b", "Education"),
            (r"\b(?:process|workflow|system|framework|methodology)\b", "Processes"),
        ]

        found_topics = []
        text_lower = text.lower()

        for pattern, topic_name in topic_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                found_topics.append(topic_name)
                break  # Take first match to avoid duplicates

        return found_topics[:2]

    def _extract_concepts_from_section(self, text: str) -> List[str]:
        """Extract key concepts for visual representation"""
        concept_patterns = [
            r"\b(?:network|connection|integration|interface)\b",
            r"\b(?:data|information|knowledge|intelligence)\b",
            r"\b(?:growth|progress|development|advancement)\b",
            r"\b(?:innovation|creativity|breakthrough|discovery)\b",
            r"\b(?:efficiency|speed|performance|optimization)\b",
            r"\b(?:collaboration|teamwork|communication|sharing)\b",
            r"\b(?:future|evolution|transformation|change)\b",
        ]

        found_concepts = []
        text_lower = text.lower()

        for pattern in concept_patterns:
            matches = re.findall(pattern, text_lower, re.IGNORECASE)
            found_concepts.extend(matches)

        return list(dict.fromkeys(found_concepts))[:3]  # Remove duplicates, limit to 3

    def _create_contextual_prompt(
        self, text: str, topics: List[str], concepts: List[str]
    ) -> str:
        """Create contextual video prompt based on script content"""

        if topics:
            main_topic = topics[0].lower()

            if "ai" in main_topic or "gpt" in main_topic:
                visual_elements = "neural network connections, data flows, glowing AI nodes and pathways"
            elif "technology" in main_topic:
                visual_elements = (
                    "high-tech interfaces, digital systems, flowing data streams"
                )
            elif "business" in main_topic or "strategy" in main_topic:
                visual_elements = (
                    "corporate graphics, growth charts, professional business diagrams"
                )
            elif "innovation" in main_topic:
                visual_elements = (
                    "creative breakthrough visualizations, transformation animations"
                )
            elif "education" in main_topic or "learning" in main_topic:
                visual_elements = (
                    "knowledge transfer visuals, educational flow diagrams"
                )
            elif "process" in main_topic:
                visual_elements = "workflow animations, step-by-step progressions"
            else:
                visual_elements = (
                    "abstract professional graphics with flowing connections"
                )
        else:
            visual_elements = "sophisticated geometric patterns with smooth motion"

        # Add concept enhancements
        if concepts:
            enhancements = []
            for concept in concepts:
                if concept in ["network", "connection"]:
                    enhancements.append("interconnected network elements")
                elif concept in ["growth", "progress"]:
                    enhancements.append("upward growth animations")
                elif concept in ["data", "information"]:
                    enhancements.append("information visualization flows")

            if enhancements:
                visual_elements += f", {', '.join(enhancements)}"

        prompt = f"""Professional animated visualization representing {topics[0] if topics else 'key concepts'}.
        Visual elements: {visual_elements}.
        
        ABSOLUTELY NO TEXT, WORDS, LETTERS, OR READABLE CONTENT.
        Clean corporate aesthetic with sophisticated motion graphics.
        High-quality cinematic presentation with smooth camera movements.
        Professional color palette suitable for educational/business content."""

        return prompt.strip()

    def _get_line_context(self, content: str, position: int) -> str:
        """Get surrounding context for better video generation"""
        lines = content[:position].split("\n")
        context_lines = lines[-3:] if len(lines) >= 3 else lines
        return " ".join(context_lines).strip()

    def enhance_prompt_for_video_generation(
        self, visual_description: str, context: str = ""
    ) -> str:
        """Enhance visual description for better video generation"""
        # Base enhancement
        enhanced_prompt = f"Professional, high-quality educational video content: {visual_description}"

        # Add context-specific enhancements for video
        if "timeline" in visual_description.lower():
            enhanced_prompt += ". Animated timeline with smooth transitions, modern design elements, technology theme. Camera slowly pans across timeline showing progression. Clean, professional style suitable for educational content."
        elif "diagram" in visual_description.lower():
            enhanced_prompt += ". Technical diagram with animated elements appearing sequentially, clean labels, modern infographic style. Smooth zoom-in to highlight key components. Professional educational presentation style."
        elif "examples" in visual_description.lower():
            enhanced_prompt += ". Multiple example scenarios shown with smooth transitions, clean professional style. Each example appears with subtle animation. Modern, engaging educational content."
        elif "code" in visual_description.lower():
            enhanced_prompt += ". Modern code editor interface with syntax highlighting, clean tech aesthetic. Code appears with typing animation, smooth cursor movement. Professional development environment."
        elif "ethical" in visual_description.lower():
            enhanced_prompt += ". Conceptual video representing ethics and responsibility in technology. Abstract visual metaphors, smooth animations, thoughtful pacing. Professional, contemplative style."
        elif "studio" in visual_description.lower():
            enhanced_prompt += ". Modern tech presentation studio with professional lighting, futuristic elements. Camera moves smoothly through the space. High-tech, professional broadcast quality."

        # Add general video style guidelines
        enhanced_prompt += ". Style: smooth camera movements, professional lighting, modern aesthetic, high production value, educational content appropriate, engaging visual storytelling, 10-15 second duration."

        return enhanced_prompt

    def generate_video(self, prompt: str) -> Optional[Dict]:
        """Generate video using Azure OpenAI SORA with correct AI Foundry endpoint"""
        # Use AI Foundry format from curl example
        payload = {
            "model": "sora",  # Required model parameter
            "prompt": prompt,
            "height": "1080",  # AI Foundry uses height/width, not size
            "width": "1920",  # 16:9 aspect ratio (1920x1080)
            "n_seconds": "10",  # Duration as n_seconds
            "n_variants": "1",  # Number of video variants
        }

        print("🎬 Generating video with SORA...")
        print(f"   Prompt: {prompt[:100]}...")
        logger.info("Starting SORA video generation with prompt: %s...", prompt[:100])

        try:
            logger.info("Using SORA endpoint: %s", self.endpoint)
            print("   🔄 Submitting video generation job...")

            # Submit video generation job
            response = requests.post(
                self.endpoint, headers=self.headers, json=payload, timeout=60
            )

            logger.info("Response status: %d", response.status_code)
            print(f"   📊 Response: {response.status_code}")

            if response.status_code in [200, 201, 202]:
                result = response.json()
                logger.info("Response data: %s", str(result)[:200])

                # Handle different response formats
                job_id = result.get("id") or result.get("job_id")

                # Check if it's a direct response with video URL
                if (
                    "data" in result
                    and isinstance(result["data"], list)
                    and len(result["data"]) > 0
                ):
                    video_data = result["data"][0]
                    if "url" in video_data:
                        print("   🎉 Video generated directly!")
                        return {
                            "success": True,
                            "video_url": video_data["url"],
                            "prompt": prompt,
                            "status": "completed",
                            "endpoint_used": self.endpoint,
                        }
                # Handle job-based response (typical for video generation)
                if job_id:
                    print(f"   ✅ Video generation job submitted: {job_id}")
                    logger.info("Video generation job submitted: %s", job_id)

                    # Poll for completion
                    video_result = self._poll_video_completion(
                        job_id, self.status_endpoint_base
                    )

                    if video_result:
                        return {
                            "success": True,
                            "job_id": job_id,
                            "video_url": video_result.get("video_url"),
                            "prompt": prompt,
                            "status": video_result.get("status"),
                            "endpoint_used": self.endpoint,
                        }
            else:
                logger.warning(
                    "Request failed: %d - %s", response.status_code, response.text[:200]
                )
                print(f"   ❌ Request failed: {response.status_code}")

        except requests.exceptions.Timeout:
            logger.warning("Request timed out")
            print("   ⏰ Request timed out")
        except requests.exceptions.RequestException as e:
            logger.warning("Request failed: %s", str(e))
            print(f"   ❌ Request failed: {str(e)}")
        except Exception as e:
            logger.warning("Unexpected error: %s", str(e))
            print(f"   ❌ Error: {str(e)}")

        # If request failed, provide diagnostic info
        logger.error("❌ SORA video generation failed")
        print("   ❌ Video generation failed")

        # Test basic connectivity
        try:
            test_response = requests.get(
                f"{self.base_url}/openai", headers=self.headers, timeout=10
            )
            logger.info("Base connectivity test: %d", test_response.status_code)
            print(f"   🔍 Base connectivity: {test_response.status_code}")
        except Exception as e:
            logger.error("Base connectivity test failed: %s", str(e))
            print(f"   🔍 Base connectivity failed: {str(e)}")

        return None

    def _poll_video_completion(
        self, job_id: str, base_endpoint: str, max_wait_time: int = 600
    ) -> Optional[Dict]:
        """Poll for video generation completion"""
        # Construct status endpoint using AI Foundry format
        status_endpoint = f"{base_endpoint}/{job_id}?api-version=preview"

        start_time = time.time()
        poll_interval = 10  # Poll every 10 seconds

        print(
            f"   ⏳ Waiting for video generation to complete (max {max_wait_time}s / {max_wait_time//60} minutes)..."
        )

        while time.time() - start_time < max_wait_time:
            try:
                response = requests.get(
                    status_endpoint, headers=self.headers, timeout=30
                )

                if response.status_code == 200:
                    result = response.json()
                    status = result.get("status", "unknown")

                    elapsed = int(time.time() - start_time)
                    print(f"   ⏱️  Status: {status} (elapsed: {elapsed}s)")

                    if status in ["succeeded", "completed"]:
                        # Try different data structures for video URL
                        video_url = None
                        generation_id = None

                        # Look for generation ID in the response
                        if (
                            "generations" in result
                            and isinstance(result["generations"], list)
                            and len(result["generations"]) > 0
                        ):
                            generation_data = result["generations"][0]
                            generation_id = generation_data.get("id")

                            if generation_id:
                                # Construct the correct video download URL from Microsoft docs
                                video_url = f"{self.base_url}/openai/v1/video/generations/{generation_id}/content/video?api-version=preview"
                                print(
                                    f"   🔗 Constructed video URL from generation ID: {generation_id}"
                                )

                        # Legacy URL checks (keep for compatibility)
                        if not video_url:
                            if "result" in result and "data" in result["result"]:
                                data = result["result"]["data"]
                                if isinstance(data, list) and len(data) > 0:
                                    video_url = data[0].get("url")
                            elif "data" in result:
                                data = result["data"]
                                if isinstance(data, list) and len(data) > 0:
                                    video_url = data[0].get("url")
                                elif isinstance(data, dict):
                                    video_url = data.get("url")
                            elif "url" in result:
                                video_url = result["url"]

                        if video_url:
                            print("   🎉 Video generation completed!")
                            return {
                                "status": status,
                                "video_url": video_url,
                                "generation_id": generation_id,
                                "result": result,
                            }
                        else:
                            print("   ⚠️ Status shows complete but no video URL found")
                            logger.warning(
                                "Status complete but no video URL: %s", str(result)
                            )

                    elif status in ["failed", "error"]:
                        error_msg = result.get("error", {}).get(
                            "message", "Unknown error"
                        )
                        print(f"   ❌ Video generation failed: {error_msg}")
                        return None
                    elif status in ["running", "pending", "in-progress"]:
                        # Continue polling
                        time.sleep(poll_interval)
                        continue
                    else:
                        print(f"   ❓ Unknown status: {status}")
                        time.sleep(poll_interval)
                        continue

            except Exception as e:
                logger.error("Error polling video status: %s", str(e))
                print(f"   ⚠️ Error checking status: {str(e)}")
                time.sleep(poll_interval)
                continue

        print(f"   ⏰ Video generation timed out after {max_wait_time}s")
        return None

    def get_default_broll_directory(self) -> str:
        """Get or create the default b-roll video directory"""
        broll_path = os.path.expanduser("~/Desktop/podcast/videos/bRoll")
        os.makedirs(broll_path, exist_ok=True)
        return broll_path

    def download_video(self, video_url: str, filename: str = None) -> bool:
        """Download video from URL to local file in b-roll directory"""
        try:
            print("   📥 Downloading video...")

            # If no filename provided, create one with timestamp
            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"sora_broll_{timestamp}.mp4"

            # If filename doesn't include path, use b-roll directory
            if not os.path.dirname(filename):
                broll_dir = self.get_default_broll_directory()
                filename = os.path.join(broll_dir, filename)
            else:
                # Ensure the directory exists
                os.makedirs(os.path.dirname(filename), exist_ok=True)

            # Use the same headers as the API calls for authentication
            response = requests.get(video_url, headers=self.headers, timeout=120)
            if response.status_code == 200:
                with open(filename, "wb") as f:
                    f.write(response.content)
                file_size = os.path.getsize(filename)
                print(
                    f"   ✅ Video downloaded: {os.path.basename(filename)} ({file_size/1024/1024:.2f} MB)"
                )
                print(f"   📁 Saved to b-roll: {filename}")
                return True
        except Exception as e:
            logger.error("Error downloading video: %s", str(e))
            print(f"   ❌ Download failed: {str(e)}")
        return False

    def generate_videos_for_script(self, script_file_path: str) -> Dict:
        """Generate all videos for visual cues in a script"""
        try:
            # Read script content
            with open(script_file_path, "r", encoding="utf-8") as f:
                script_content = f.read()

            # Extract visual cues
            visual_cues = self.extract_visual_cues(script_content)
            print(f"\n🎬 SORA VIDEO GENERATION")
            print("=" * 60)
            print(f"📍 Script: {os.path.basename(script_file_path)}")
            print(f"🎯 Found {len(visual_cues)} visual cues")

            if len(visual_cues) == 0:
                print("❌ No visual cues found in script")
                return {"error": "No visual cues found"}

            # Create b-roll output directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            broll_base = self.get_default_broll_directory()
            script_name = os.path.splitext(os.path.basename(script_file_path))[0]
            output_dir = os.path.join(broll_base, f"{script_name}_{timestamp}")
            os.makedirs(output_dir, exist_ok=True)
            print(f"📁 B-roll output directory: {output_dir}")

            results = {
                "script_file": script_file_path,
                "total_cues": len(visual_cues),
                "generated_videos": [],
                "failed_videos": [],
                "output_directory": output_dir,
                "timestamp": timestamp,
            }

            # Generate videos for each visual cue
            print(f"\n🚀 Starting video generation...")
            for i, cue in enumerate(visual_cues, 1):
                print(f"\n📽️  Generating Video {i}/{len(visual_cues)}")
                print(f"   Description: {cue['description'][:80]}...")

                # Enhance prompt
                enhanced_prompt = self.enhance_prompt_for_video_generation(
                    cue["description"], cue["line_context"]
                )

                # Generate video
                result = self.generate_video(enhanced_prompt)

                if result and result.get("success"):
                    # Download video
                    filename = f"video_cue_{i:02d}_{cue['description'][:20].replace(' ', '_').replace('/', '_')}.mp4"
                    filename = re.sub(r"[^\w\-_.]", "", filename)  # Clean filename
                    filepath = os.path.join(output_dir, filename)

                    if self.download_video(result["video_url"], filepath):
                        results["generated_videos"].append(
                            {
                                "cue_number": i,
                                "description": cue["description"],
                                "original_text": cue["original_text"],
                                "enhanced_prompt": enhanced_prompt,
                                "video_file": filepath,
                                "video_url": result["video_url"],
                                "job_id": result.get("job_id"),
                            }
                        )
                        print(f"   🎉 Video {i} completed successfully!")
                    else:
                        results["failed_videos"].append(
                            {
                                "cue_number": i,
                                "description": cue["description"],
                                "error": "Failed to download video",
                            }
                        )
                        print(f"   ❌ Failed to download video {i}")
                else:
                    results["failed_videos"].append(
                        {
                            "cue_number": i,
                            "description": cue["description"],
                            "error": "Failed to generate video",
                        }
                    )
                    print(f"   ❌ Failed to generate video {i}")

                # Add delay between requests to avoid overwhelming the service
                if i < len(visual_cues):
                    print(f"   ⏸️  Waiting 5 seconds before next video...")
                    time.sleep(5)

            # Save results summary
            summary_file = os.path.join(output_dir, "video_generation_summary.json")
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)

            print(f"\n🎊 VIDEO GENERATION COMPLETE!")
            print("=" * 60)
            print(f"✅ Generated: {len(results['generated_videos'])} videos")
            print(f"❌ Failed: {len(results['failed_videos'])} videos")
            print(
                f"📊 Success Rate: {(len(results['generated_videos'])/len(visual_cues)*100):.1f}%"
            )
            print(f"📁 All files saved to: {output_dir}")

            return results

        except Exception as e:
            logger.error("Error processing script: %s", str(e))
            print(f"❌ Error processing script: {str(e)}")
            return {"error": str(e)}


def main():
    """Test function"""
    generator = AzureSoraVideoGenerator()

    # Test with latest script
    script_file = "output/script_video_script_20250819_165453.md"
    if os.path.exists(script_file):
        results = generator.generate_videos_for_script(script_file)
        if "error" not in results:
            print(f"\n🎬 Generated {len(results.get('generated_videos', []))} videos")
            print(f"❌ Failed: {len(results.get('failed_videos', []))}")
        else:
            print(f"❌ Error: {results['error']}")
    else:
        print(f"Script file not found: {script_file}")


if __name__ == "__main__":
    main()
