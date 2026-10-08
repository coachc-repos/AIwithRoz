"""
Azure OpenAI DALL-E Image Generation Client for Script Visual Cues
Extracts visual cues from scripts and generates professional images using Azure OpenAI DALL-E
"""

import requests
import json
import re
import time
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AzureImageGenerator:
    def __init__(self):
        # Azure OpenAI endpoint configuration
        self.api_key = os.environ.get("AZURE_AI_SERVICES_KEY", "")
        self.base_url = os.environ.get("AZURE_AI_SERVICES_ENDPOINT", "https://coach-me1k8xkn-eastus2.cognitiveservices.azure.com")

        # Try different possible DALL-E endpoints
        self.possible_endpoints = [
            f"{self.base_url}/openai/deployments/dalle-3/images/generations?api-version=2024-02-01",
            f"{self.base_url}/openai/deployments/dall-e-3/images/generations?api-version=2024-02-01",
            f"{self.base_url}/openai/deployments/DALL-E-3/images/generations?api-version=2024-02-01",
            f"{self.base_url}/openai/images/generations?api-version=2024-02-01",
        ]

        self.headers = {"Content-Type": "application/json", "api-key": self.api_key}

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

        # Remove duplicates
        seen = set()
        unique_cues = []
        for cue in visual_cues:
            if cue["description"] not in seen:
                seen.add(cue["description"])
                unique_cues.append(cue)

        return unique_cues

    def _get_line_context(self, content: str, position: int) -> str:
        """Get surrounding context for better image generation"""
        lines = content[:position].split("\n")
        context_lines = lines[-3:] if len(lines) >= 3 else lines
        return " ".join(context_lines).strip()

    def enhance_prompt_for_image_generation(
        self, visual_description: str, context: str = ""
    ) -> str:
        """Enhance visual description for better image generation"""
        # Base enhancement
        enhanced_prompt = f"Professional, high-quality digital illustration for educational video content: {visual_description}"

        # Add context-specific enhancements
        if "timeline" in visual_description.lower():
            enhanced_prompt += (
                ", clean timeline graphic with modern design elements, technology theme"
            )
        elif "diagram" in visual_description.lower():
            enhanced_prompt += (
                ", technical diagram with clear labels, modern infographic style"
            )
        elif "examples" in visual_description.lower():
            enhanced_prompt += ", multiple example scenarios shown in a grid layout, clean professional style"
        elif "code" in visual_description.lower():
            enhanced_prompt += ", modern code editor interface, syntax highlighting, clean tech aesthetic"
        elif "ethical" in visual_description.lower():
            enhanced_prompt += ", conceptual illustration representing ethics and responsibility in technology"
        elif "studio" in visual_description.lower():
            enhanced_prompt += ", modern tech presentation studio, professional lighting, futuristic elements"

        # Add general style guidelines
        enhanced_prompt += ". Style: clean, professional, modern, suitable for tech education content, high contrast, visually appealing for video presentation"

        return enhanced_prompt

    def generate_image(self, prompt: str, size: str = "1024x1024") -> Optional[Dict]:
        """Generate image using Azure OpenAI DALL-E with fallback endpoints"""
        payload = {
            "prompt": prompt,
            "size": size,
            "n": 1,
            "quality": "standard",
            "style": "vivid",
        }

        logger.info("Generating image with prompt: %s...", prompt[:100])

        # Try each possible endpoint
        for i, endpoint in enumerate(self.possible_endpoints):
            try:
                logger.info("Trying endpoint %d: %s", i + 1, endpoint)

                response = requests.post(
                    endpoint, headers=self.headers, json=payload, timeout=60
                )

                logger.info("Response status: %d", response.status_code)

                if response.status_code == 200:
                    result = response.json()
                    if "data" in result and len(result["data"]) > 0:
                        image_url = result["data"][0].get("url")
                        if image_url:
                            logger.info(
                                "✅ Successfully generated image using endpoint %d",
                                i + 1,
                            )
                            return {
                                "success": True,
                                "image_url": image_url,
                                "prompt": prompt,
                                "endpoint_used": endpoint,
                            }

                logger.warning(
                    "Endpoint %d failed: %d - %s",
                    i + 1,
                    response.status_code,
                    response.text[:200],
                )

            except requests.exceptions.Timeout:
                logger.warning("Endpoint %d timed out", i + 1)
                continue
            except requests.exceptions.RequestException as e:
                logger.warning("Endpoint %d request failed: %s", i + 1, str(e))
                continue
            except Exception as e:
                logger.warning("Endpoint %d unexpected error: %s", i + 1, str(e))
                continue

        # If all endpoints failed, try a simple test to see if the service is available
        logger.error("❌ All endpoints failed. Testing basic connectivity...")
        try:
            test_response = requests.get(
                f"{self.base_url}/openai", headers=self.headers, timeout=10
            )
            logger.info("Base connectivity test: %d", test_response.status_code)
        except Exception as e:
            logger.error("Base connectivity test failed: %s", str(e))

        return None

    def download_image(self, image_url: str, filename: str) -> bool:
        """Download image from URL to local file"""
        try:
            response = requests.get(image_url, timeout=30)
            if response.status_code == 200:
                with open(filename, "wb") as f:
                    f.write(response.content)
                return True
        except Exception as e:
            logger.error(f"Error downloading image: {str(e)}")
        return False

    def generate_images_for_script(self, script_file_path: str) -> Dict:
        """Generate all images for visual cues in a script"""
        try:
            # Read script content
            with open(script_file_path, "r", encoding="utf-8") as f:
                script_content = f.read()

            # Extract visual cues
            visual_cues = self.extract_visual_cues(script_content)
            logger.info(f"Found {len(visual_cues)} visual cues in script")

            # Create output directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = f"output/script_images_{timestamp}"
            os.makedirs(output_dir, exist_ok=True)

            results = {
                "script_file": script_file_path,
                "total_cues": len(visual_cues),
                "generated_images": [],
                "failed_images": [],
                "output_directory": output_dir,
                "timestamp": timestamp,
            }

            # Generate images for each visual cue
            for i, cue in enumerate(visual_cues, 1):
                logger.info(
                    f"Processing visual cue {i}/{len(visual_cues)}: {cue['description'][:50]}..."
                )

                # Enhance prompt
                enhanced_prompt = self.enhance_prompt_for_image_generation(
                    cue["description"], cue["line_context"]
                )

                # Generate image
                result = self.generate_image(enhanced_prompt)

                if result and result.get("success"):
                    # Download image
                    filename = f"visual_cue_{i:02d}_{cue['description'][:30].replace(' ', '_').replace('/', '_')}.png"
                    filename = re.sub(r"[^\w\-_.]", "", filename)  # Clean filename
                    filepath = os.path.join(output_dir, filename)

                    if self.download_image(result["image_url"], filepath):
                        results["generated_images"].append(
                            {
                                "cue_number": i,
                                "description": cue["description"],
                                "original_text": cue["original_text"],
                                "enhanced_prompt": enhanced_prompt,
                                "image_file": filepath,
                                "image_url": result["image_url"],
                            }
                        )
                        logger.info(f"✅ Generated and saved: {filename}")
                    else:
                        results["failed_images"].append(
                            {
                                "cue_number": i,
                                "description": cue["description"],
                                "error": "Failed to download image",
                            }
                        )
                        logger.error(f"❌ Failed to download image for cue {i}")
                else:
                    results["failed_images"].append(
                        {
                            "cue_number": i,
                            "description": cue["description"],
                            "error": "Failed to generate image",
                        }
                    )
                    logger.error(f"❌ Failed to generate image for cue {i}")

                # Add delay between requests to avoid rate limiting
                time.sleep(2)

            # Save results summary
            summary_file = os.path.join(output_dir, "image_generation_summary.json")
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)

            logger.info(
                f"✅ Image generation complete! Generated {len(results['generated_images'])} images"
            )
            logger.info(f"📁 Output directory: {output_dir}")

            return results

        except Exception as e:
            logger.error(f"Error processing script: {str(e)}")
            return {"error": str(e)}


def main():
    """Test function"""
    generator = AzureImageGenerator()

    # Test with latest script
    script_file = "output/script_video_script_20250819_165453.md"
    if os.path.exists(script_file):
        results = generator.generate_images_for_script(script_file)
        print(f"Generated {len(results.get('generated_images', []))} images")
        print(f"Failed: {len(results.get('failed_images', []))}")
    else:
        print(f"Script file not found: {script_file}")


if __name__ == "__main__":
    main()
