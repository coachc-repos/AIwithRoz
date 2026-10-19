#!/usr/bin/env python3
"""
Third-Party Thumbnail API Integrations
Supports Bannerbear, Placid, and HTML/CSS to Image APIs
"""

import requests
import json
import base64
import os
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime


class BannerbearThumbnailGenerator:
    """Generate thumbnails using Bannerbear API"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.bannerbear.com/v2"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def create_youtube_thumbnail(
        self, template_id: str, title: str, profile_image_url: str = None
    ) -> Optional[Dict]:
        """Create YouTube thumbnail using Bannerbear"""

        modifications = [
            {
                "name": "title",  # Text layer name in template
                "text": title,
                "color": "#FFFFFF",  # White text as requested
            }
        ]

        # Add profile image if provided
        if profile_image_url:
            modifications.append(
                {
                    "name": "profile_image",  # Image layer name in template
                    "image_url": profile_image_url,
                }
            )

        payload = {"template": template_id, "modifications": modifications}

        try:
            response = requests.post(
                f"{self.base_url}/images", headers=self.headers, json=payload
            )

            if response.status_code == 201:
                result = response.json()
                print(f"✅ Bannerbear thumbnail created: {result.get('image_url')}")
                return result
            else:
                print(
                    f"❌ Bannerbear API error: {response.status_code} - {response.text}"
                )
                return None

        except Exception as e:
            print(f"❌ Bannerbear request failed: {e}")
            return None


class PlacidThumbnailGenerator:
    """Generate thumbnails using Placid API"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.placid.app/api/rest"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def create_youtube_thumbnail(
        self, template_id: str, title: str, profile_image_url: str = None
    ) -> Optional[Dict]:
        """Create YouTube thumbnail using Placid"""

        data = {"title": title}

        if profile_image_url:
            data["profile_image"] = profile_image_url

        payload = {"template_uuid": template_id, "data": data}

        try:
            response = requests.post(
                f"{self.base_url}/images", headers=self.headers, json=payload
            )

            if response.status_code == 201:
                result = response.json()
                print(f"✅ Placid thumbnail created: {result.get('image_url')}")
                return result
            else:
                print(f"❌ Placid API error: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            print(f"❌ Placid request failed: {e}")
            return None


class HTMLCSSImageGenerator:
    """Generate thumbnails using HTML/CSS to Image API"""

    def __init__(self, user_id: str, api_key: str):
        self.user_id = user_id
        self.api_key = api_key
        self.base_url = "https://hcti.io/v1/image"

        # Create basic auth header
        auth_string = f"{user_id}:{api_key}"
        encoded_auth = base64.b64encode(auth_string.encode()).decode()

        self.headers = {
            "Authorization": f"Basic {encoded_auth}",
            "Content-Type": "application/json",
        }

    def create_youtube_thumbnail(
        self, title: str, profile_image_url: str = None
    ) -> Optional[Dict]:
        """Create YouTube thumbnail using HTML/CSS"""

        # YouTube thumbnail HTML template
        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@700;900&display=swap" rel="stylesheet">
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    width: 1280px;
                    height: 720px;
                    background: linear-gradient(135deg, #0F172A 0%, #1E293B 25%, #334155 50%, #1E40AF 75%, #7C3AED 100%);
                    font-family: 'Inter', sans-serif;
                    display: flex;
                    align-items: center;
                    justify-content: flex-start;
                    padding-left: 40px;
                    position: relative;
                    overflow: hidden;
                }}
                
                /* Geometric background elements */
                body::before {{
                    content: '';
                    position: absolute;
                    top: -200px;
                    left: -200px;
                    width: 600px;
                    height: 600px;
                    border: 3px solid rgba(255, 255, 255, 0.1);
                    border-radius: 50%;
                }}
                
                .content {{
                    max-width: 800px;
                    z-index: 2;
                }}
                
                .title {{
                    color: white;
                    font-size: 96px;
                    font-weight: 900;
                    line-height: 1.1;
                    margin-bottom: 20px;
                    text-shadow: 0 4px 8px rgba(0, 0, 0, 0.3);
                }}
                
                .brand {{
                    color: white;
                    font-size: 48px;
                    font-weight: 700;
                    opacity: 0.9;
                }}
                
                .profile {{
                    position: absolute;
                    top: 30px;
                    right: 40px;
                    width: 180px;
                    height: 180px;
                    border-radius: 50%;
                    border: 6px solid rgba(255, 255, 255, 0.2);
                    box-shadow: 0 0 30px rgba(255, 255, 255, 0.2);
                }}
            </style>
        </head>
        <body>
            <div class="content">
                <div class="title">{title}</div>
                <div class="brand">AI with Roz</div>
            </div>
            {f'<img src="{profile_image_url}" class="profile" alt="Profile">' if profile_image_url else ''}
        </body>
        </html>
        """

        payload = {
            "html": html_template,
            "css": "",  # CSS is inline
            "width": 1280,
            "height": 720,
        }

        try:
            response = requests.post(self.base_url, headers=self.headers, json=payload)

            if response.status_code == 200:
                result = response.json()
                print(f"✅ HTML/CSS thumbnail created: {result.get('url')}")
                return result
            else:
                print(
                    f"❌ HTML/CSS API error: {response.status_code} - {response.text}"
                )
                return None

        except Exception as e:
            print(f"❌ HTML/CSS request failed: {e}")
            return None


class ThirdPartyThumbnailManager:
    """Unified manager for all third-party thumbnail APIs"""

    def __init__(self):
        self.output_dir = Path.home() / "Dev/Videos/Thumbnails/ThirdParty"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Load API keys from environment or config
        self.bannerbear = None
        self.placid = None
        self.htmlcss = None

        self._load_api_credentials()

    def _load_api_credentials(self):
        """Load API credentials from environment variables"""

        # Bannerbear
        bannerbear_key = os.getenv("BANNERBEAR_API_KEY")
        if bannerbear_key:
            self.bannerbear = BannerbearThumbnailGenerator(bannerbear_key)

        # Placid
        placid_key = os.getenv("PLACID_API_KEY")
        if placid_key:
            self.placid = PlacidThumbnailGenerator(placid_key)

        # HTML/CSS to Image
        htmlcss_user = os.getenv("HTMLCSS_USER_ID")
        htmlcss_key = os.getenv("HTMLCSS_API_KEY")
        if htmlcss_user and htmlcss_key:
            self.htmlcss = HTMLCSSImageGenerator(htmlcss_user, htmlcss_key)

    def create_thumbnails_all_services(
        self, title: str, profile_image_url: str = None
    ) -> Dict[str, Optional[str]]:
        """Create thumbnails using all available services"""

        results = {}

        print(f"🎨 Creating thumbnails for: {title}")
        print("=" * 60)

        # Bannerbear (requires template ID)
        if self.bannerbear:
            print("\n🐻 Trying Bannerbear...")
            # You'd need to create templates in Bannerbear dashboard first
            template_id = os.getenv("BANNERBEAR_YOUTUBE_TEMPLATE_ID")
            if template_id:
                result = self.bannerbear.create_youtube_thumbnail(
                    template_id, title, profile_image_url
                )
                results["bannerbear"] = result.get("image_url") if result else None
            else:
                print("⚠️ Bannerbear template ID not configured")
                results["bannerbear"] = None

        # Placid (requires template ID)
        if self.placid:
            print("\n🎯 Trying Placid...")
            template_id = os.getenv("PLACID_YOUTUBE_TEMPLATE_ID")
            if template_id:
                result = self.placid.create_youtube_thumbnail(
                    template_id, title, profile_image_url
                )
                results["placid"] = result.get("image_url") if result else None
            else:
                print("⚠️ Placid template ID not configured")
                results["placid"] = None

        # HTML/CSS to Image (no template needed)
        if self.htmlcss:
            print("\n🔧 Trying HTML/CSS to Image...")
            result = self.htmlcss.create_youtube_thumbnail(title, profile_image_url)
            results["htmlcss"] = result.get("url") if result else None

        return results

    def download_and_save_thumbnail(
        self, image_url: str, service_name: str, title: str
    ) -> Optional[str]:
        """Download thumbnail from URL and save locally"""

        try:
            response = requests.get(image_url, timeout=30)
            if response.status_code == 200:
                # Create filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_title = "".join(
                    c for c in title if c.isalnum() or c in (" ", "-", "_")
                ).strip()
                safe_title = safe_title.replace(" ", "_")[:40]
                filename = f"{safe_title}_{service_name}_youtube_{timestamp}.png"
                filepath = self.output_dir / filename

                # Save file
                with open(filepath, "wb") as f:
                    f.write(response.content)

                print(f"📸 {service_name.title()} thumbnail saved: {filename}")
                return str(filepath)
            else:
                print(
                    f"❌ Failed to download {service_name} thumbnail: {response.status_code}"
                )
                return None

        except Exception as e:
            print(f"❌ Error downloading {service_name} thumbnail: {e}")
            return None

    def interactive_third_party_creator(self):
        """Interactive third-party thumbnail creator"""

        print("\n🌐 Third-Party Thumbnail Creator")
        print("=" * 60)
        print("Generate thumbnails using external APIs")

        # Check available services
        available_services = []
        if self.bannerbear and os.getenv("BANNERBEAR_YOUTUBE_TEMPLATE_ID"):
            available_services.append("Bannerbear")
        if self.placid and os.getenv("PLACID_YOUTUBE_TEMPLATE_ID"):
            available_services.append("Placid")
        if self.htmlcss:
            available_services.append("HTML/CSS to Image")

        if not available_services:
            print("\n❌ No API services configured!")
            print("💡 Configure API keys in environment variables:")
            print("   - BANNERBEAR_API_KEY + BANNERBEAR_YOUTUBE_TEMPLATE_ID")
            print("   - PLACID_API_KEY + PLACID_YOUTUBE_TEMPLATE_ID")
            print("   - HTMLCSS_USER_ID + HTMLCSS_API_KEY")
            return

        print(f"\n✅ Available services: {', '.join(available_services)}")

        while True:
            print(f"\n📋 OPTIONS:")
            print("1. 🎯 Generate thumbnails with all services")
            print("2. 📁 View generated thumbnails")
            print("3. ❌ Exit")

            try:
                choice = input("\n👆 Select option (1-3): ").strip()

                if choice == "1":
                    title = input("📝 Enter video title: ").strip()
                    if title:
                        profile_url = (
                            input("🖼️ Profile image URL (optional): ").strip() or None
                        )

                        # Generate thumbnails
                        results = self.create_thumbnails_all_services(
                            title, profile_url
                        )

                        # Download and save successful results
                        saved_files = []
                        for service, url in results.items():
                            if url:
                                saved_path = self.download_and_save_thumbnail(
                                    url, service, title
                                )
                                if saved_path:
                                    saved_files.append(Path(saved_path).name)

                        if saved_files:
                            print(f"\n🎉 Created {len(saved_files)} thumbnails:")
                            for file in saved_files:
                                print(f"   • {file}")
                        else:
                            print("\n❌ No thumbnails were generated successfully")

                elif choice == "2":
                    thumbnails = list(self.output_dir.glob("*.png"))
                    if thumbnails:
                        print(f"\n📸 Found {len(thumbnails)} third-party thumbnails:")
                        for thumb in sorted(thumbnails)[-10:]:
                            print(f"   • {thumb.name}")
                        print(f"\n📁 Location: {self.output_dir}")
                    else:
                        print("❌ No third-party thumbnails found")

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
    manager = ThirdPartyThumbnailManager()
    manager.interactive_third_party_creator()


if __name__ == "__main__":
    main()
