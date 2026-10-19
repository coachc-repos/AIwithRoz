#!/usr/bin/env python3
"""
Canva API Integration for Text Replacement
=========================================

This module provides functionality to interact with Canva's Connect APIs
to modify text in existing designs/images.

Features:
- OAuth 2.0 authentication with Canva
- Upload images to Canva
- Create designs from images  
- Modify text elements in designs
- Export modified designs

Setup Required:
1. Create a Canva Developer account at https://www.canva.com/developers/
2. Create a new integration in the Developer Portal
3. Configure OAuth redirect URLs and scopes
4. Set environment variables with your credentials

Environment Variables:
- CANVA_CLIENT_ID: Your Canva integration client ID
- CANVA_CLIENT_SECRET: Your Canva integration client secret
- CANVA_REDIRECT_URI: OAuth redirect URI (default: http://localhost:8080/callback)
"""

import os
import json
import base64
import requests
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode, parse_qs
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time
from pathlib import Path


class CanvaAuthHandler(BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback"""
    
    def do_GET(self):
        if self.path.startswith('/callback'):
            query_params = parse_qs(self.path.split('?')[1] if '?' in self.path else '')
            self.server.auth_code = query_params.get('code', [None])[0]
            self.server.auth_error = query_params.get('error', [None])[0]
            
            response = "Authorization successful! You can close this window." if self.server.auth_code else "Authorization failed."
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(f"<html><body><h1>{response}</h1></body></html>".encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Suppress default logging
        pass


class CanvaAPIClient:
    """
    Canva Connect API Client for image text editing
    """
    
    def __init__(self, 
                 client_id: Optional[str] = None,
                 client_secret: Optional[str] = None,
                 redirect_uri: str = "http://localhost:8080/callback"):
        """
        Initialize the Canva API client
        
        Args:
            client_id: Canva integration client ID (from env if not provided)
            client_secret: Canva integration client secret (from env if not provided) 
            redirect_uri: OAuth redirect URI
        """
        self.client_id = client_id or os.getenv('CANVA_CLIENT_ID')
        self.client_secret = client_secret or os.getenv('CANVA_CLIENT_SECRET')
        self.redirect_uri = redirect_uri
        
        if not self.client_id or not self.client_secret:
            raise ValueError("CANVA_CLIENT_ID and CANVA_CLIENT_SECRET must be provided")
        
        self.base_url = "https://api.canva.com/rest/v1"
        self.access_token = None
        self.refresh_token = None
        
        # Create session with default headers
        self.session = requests.Session()
    
    def _update_auth_headers(self):
        """Update session headers with current access token"""
        if self.access_token:
            self.session.headers.update({
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            })
    
    def authenticate(self) -> bool:
        """
        Perform OAuth 2.0 authentication with Canva
        
        Returns:
            bool: True if authentication successful
        """
        print("🔐 Starting Canva OAuth 2.0 authentication...")
        
        # Required scopes for design and asset management
        scopes = [
            'design:content:write',  # Edit design content 
            'design:meta:read',      # Read design metadata
            'asset:read',            # Read assets
            'asset:write',           # Upload assets
            'profile:read'           # Read user profile
        ]
        
        # Build authorization URL
        auth_params = {
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(scopes),
            'state': 'linedrive_canva_auth'  # CSRF protection
        }
        
        auth_url = f"https://www.canva.com/oauth/authorize?{urlencode(auth_params)}"
        
        print(f"📱 Opening browser for Canva authorization...")
        print(f"🔗 If browser doesn't open, go to: {auth_url}")
        
        # Start local HTTP server for OAuth callback
        server = HTTPServer(('localhost', 8080), CanvaAuthHandler)
        server.auth_code = None
        server.auth_error = None
        
        # Start server in background
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()
        
        # Open browser
        webbrowser.open(auth_url)
        
        # Wait for callback
        print("⏳ Waiting for authorization...")
        timeout = 120  # 2 minutes
        start_time = time.time()
        
        while server.auth_code is None and server.auth_error is None:
            if time.time() - start_time > timeout:
                print("❌ Authentication timed out")
                server.shutdown()
                return False
            time.sleep(1)
        
        server.shutdown()
        
        if server.auth_error:
            print(f"❌ Authentication error: {server.auth_error}")
            return False
        
        # Exchange authorization code for access token
        token_data = {
            'grant_type': 'authorization_code',
            'code': server.auth_code,
            'redirect_uri': self.redirect_uri,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        
        try:
            response = requests.post(
                'https://api.canva.com/rest/v1/oauth/token',
                data=token_data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            if response.status_code == 200:
                token_info = response.json()
                self.access_token = token_info.get('access_token')
                self.refresh_token = token_info.get('refresh_token')
                self._update_auth_headers()
                
                print("✅ Successfully authenticated with Canva!")
                return True
            else:
                print(f"❌ Token exchange failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Authentication error: {e}")
            return False
    
    def upload_image(self, image_path: str, name_hint: Optional[str] = None) -> Optional[str]:
        """
        Upload an image to Canva as an asset
        
        Args:
            image_path: Path to the image file
            name_hint: Optional name hint for the asset
            
        Returns:
            str: Asset ID if successful, None otherwise
        """
        if not self.access_token:
            print("❌ Not authenticated. Call authenticate() first.")
            return None
        
        image_path = Path(image_path)
        if not image_path.exists():
            print(f"❌ Image file not found: {image_path}")
            return None
        
        print(f"📤 Uploading image: {image_path.name}")
        
        try:
            # Read and encode image
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            # Create upload job
            upload_data = {
                'name_hint': name_hint or image_path.stem,
                'tags': ['linedrive', 'text-editing']
            }
            
            files = {
                'asset': (image_path.name, image_data, 'image/png')
            }
            
            # Remove Content-Type header for multipart upload
            headers = {'Authorization': f'Bearer {self.access_token}'}
            
            response = requests.post(
                f"{self.base_url}/assets",
                data=upload_data,
                files=files,
                headers=headers
            )
            
            if response.status_code == 201:
                asset_info = response.json()
                asset_id = asset_info.get('asset', {}).get('id')
                print(f"✅ Image uploaded successfully! Asset ID: {asset_id}")
                return asset_id
            else:
                print(f"❌ Upload failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ Upload error: {e}")
            return None
    
    def create_design_from_image(self, asset_id: str, design_type: str = "Presentation") -> Optional[str]:
        """
        Create a design from an uploaded asset
        
        Args:
            asset_id: ID of the uploaded asset
            design_type: Type of design to create
            
        Returns:
            str: Design ID if successful, None otherwise
        """
        if not self.access_token:
            print("❌ Not authenticated. Call authenticate() first.")
            return None
        
        print(f"🎨 Creating design from asset: {asset_id}")
        
        try:
            design_data = {
                'design_type': design_type,
                'asset_id': asset_id
            }
            
            response = self.session.post(
                f"{self.base_url}/designs",
                json=design_data
            )
            
            if response.status_code == 201:
                design_info = response.json()
                design_id = design_info.get('design', {}).get('id')
                print(f"✅ Design created successfully! Design ID: {design_id}")
                return design_id
            else:
                print(f"❌ Design creation failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ Design creation error: {e}")
            return None
    
    def get_design_content(self, design_id: str) -> Optional[Dict[str, Any]]:
        """
        Get design content including text elements
        
        Args:
            design_id: ID of the design
            
        Returns:
            dict: Design content if successful, None otherwise
        """
        if not self.access_token:
            print("❌ Not authenticated. Call authenticate() first.")
            return None
        
        try:
            response = self.session.get(f"{self.base_url}/designs/{design_id}")
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ Failed to get design content: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ Error getting design content: {e}")
            return None
    
    def find_text_elements(self, design_id: str) -> List[Dict[str, Any]]:
        """
        Find all text elements in a design
        
        Args:
            design_id: ID of the design
            
        Returns:
            list: List of text elements found
        """
        print(f"🔍 Finding text elements in design: {design_id}")
        
        design_content = self.get_design_content(design_id)
        if not design_content:
            return []
        
        text_elements = []
        
        # Extract text elements from design content
        # Note: The actual structure depends on Canva's API response format
        pages = design_content.get('design', {}).get('pages', [])
        
        for page in pages:
            elements = page.get('elements', [])
            for element in elements:
                if element.get('type') == 'text':
                    text_elements.append({
                        'id': element.get('id'),
                        'text': element.get('text', ''),
                        'page_id': page.get('id')
                    })
        
        print(f"📝 Found {len(text_elements)} text elements")
        return text_elements
    
    def replace_text(self, design_id: str, replacements: Dict[str, str]) -> bool:
        """
        Replace text in a design
        
        Args:
            design_id: ID of the design
            replacements: Dictionary mapping old text to new text
            
        Returns:
            bool: True if successful
        """
        print(f"✏️ Replacing text in design: {design_id}")
        print(f"📝 Replacements: {replacements}")
        
        try:
            # Get current text elements
            text_elements = self.find_text_elements(design_id)
            
            updates = []
            for element in text_elements:
                current_text = element['text']
                new_text = current_text
                
                # Apply replacements
                for old_text, replacement in replacements.items():
                    if old_text in current_text:
                        new_text = current_text.replace(old_text, replacement)
                        print(f"🔄 Replacing '{old_text}' with '{replacement}' in element {element['id']}")
                
                # If text was changed, add to updates
                if new_text != current_text:
                    updates.append({
                        'id': element['id'],
                        'text': new_text
                    })
            
            if not updates:
                print("ℹ️ No text replacements needed")
                return True
            
            # Apply updates to design
            update_data = {
                'operations': [{
                    'op': 'replace',
                    'path': f"/elements/{update['id']}/text",
                    'value': update['text']
                } for update in updates]
            }
            
            response = self.session.patch(
                f"{self.base_url}/designs/{design_id}",
                json=update_data
            )
            
            if response.status_code == 200:
                print(f"✅ Successfully updated {len(updates)} text elements")
                return True
            else:
                print(f"❌ Text replacement failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Text replacement error: {e}")
            return False
    
    def export_design(self, design_id: str, format: str = "PNG", output_path: Optional[str] = None) -> Optional[str]:
        """
        Export a design to an image file
        
        Args:
            design_id: ID of the design
            format: Export format (PNG, JPG, PDF)
            output_path: Path to save the exported file
            
        Returns:
            str: Path to exported file if successful, None otherwise
        """
        if not self.access_token:
            print("❌ Not authenticated. Call authenticate() first.")
            return None
        
        print(f"📥 Exporting design {design_id} as {format}")
        
        try:
            export_data = {
                'format': format.upper(),
                'quality': 'high'
            }
            
            response = self.session.post(
                f"{self.base_url}/designs/{design_id}/export",
                json=export_data
            )
            
            if response.status_code == 200:
                export_info = response.json()
                download_url = export_info.get('exports', [{}])[0].get('url')
                
                if download_url:
                    # Download the exported file
                    download_response = requests.get(download_url)
                    
                    if not output_path:
                        output_path = f"canva_export_{design_id}.{format.lower()}"
                    
                    with open(output_path, 'wb') as f:
                        f.write(download_response.content)
                    
                    print(f"✅ Design exported to: {output_path}")
                    return output_path
                else:
                    print("❌ No download URL in export response")
                    return None
            else:
                print(f"❌ Export failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ Export error: {e}")
            return None


def modify_image_text(image_path: str, text_replacements: Dict[str, str], 
                     output_path: Optional[str] = None) -> Optional[str]:
    """
    High-level function to modify text in an image using Canva API
    
    Args:
        image_path: Path to the input image
        text_replacements: Dictionary mapping old text to new text
        output_path: Path for the output image
        
    Returns:
        str: Path to modified image if successful, None otherwise
    """
    print("🎨 CANVA IMAGE TEXT MODIFICATION")
    print("=" * 50)
    
    # Initialize client
    try:
        client = CanvaAPIClient()
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("💡 Please set CANVA_CLIENT_ID and CANVA_CLIENT_SECRET environment variables")
        return None
    
    # Authenticate
    if not client.authenticate():
        return None
    
    # Upload image
    asset_id = client.upload_image(image_path)
    if not asset_id:
        return None
    
    # Create design
    design_id = client.create_design_from_image(asset_id)
    if not design_id:
        return None
    
    # Replace text
    if not client.replace_text(design_id, text_replacements):
        return None
    
    # Export modified design
    return client.export_design(design_id, "PNG", output_path)


if __name__ == "__main__":
    # Example usage
    image_path = "/Users/christhi/Dev/Github/linedrive/linedrive_azure/agents/AI in Homeschool.png"
    
    # Example text replacements
    replacements = {
        "Homeschool": "Remote Learning",
        "AI": "Artificial Intelligence", 
        "Heroes": "Champions"
    }
    
    result = modify_image_text(image_path, replacements, "modified_ai_image.png")
    
    if result:
        print(f"🎉 Success! Modified image saved to: {result}")
    else:
        print("❌ Failed to modify image")
