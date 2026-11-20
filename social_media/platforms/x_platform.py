#!/usr/bin/env python3
"""
X (Twitter) Platform Handler
"""

import sys
from datetime import datetime
from typing import Dict, Any
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

try:
    import tweepy
    TWEEPY_AVAILABLE = True
except ImportError:
    TWEEPY_AVAILABLE = False

from config.x_config import XConfig


class XPlatformHandler:
    """Handler for posting to X (Twitter)"""
    
    def __init__(self):
        self.config = XConfig()
        self.client = None
        self.api = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize the X API client"""
        if not TWEEPY_AVAILABLE:
            raise ImportError("tweepy library is required. Install with: pip install tweepy")
        
        credentials = self.config.get_credentials()
        
        # Initialize Twitter API v2 client
        self.client = tweepy.Client(
            bearer_token=credentials.get('bearer_token'),
            consumer_key=credentials['api_key'],
            consumer_secret=credentials['api_key_secret'],
            access_token=credentials['access_token'],
            access_token_secret=credentials['access_token_secret'],
            wait_on_rate_limit=True
        )
        
        # Initialize v1.1 API for media upload
        auth = tweepy.OAuthHandler(
            credentials['api_key'],
            credentials['api_key_secret']
        )
        auth.set_access_token(
            credentials['access_token'],
            credentials['access_token_secret']
        )
        self.api = tweepy.API(auth, wait_on_rate_limit=True)
    
    def test_connection(self) -> bool:
        """Test the X API connection"""
        try:
            if not self.client:
                return False
            
            me = self.client.get_me()
            if me and me.data:
                print(f"✅ Connected to X as: @{me.data.username}")
                return True
            return False
            
        except Exception as e:
            print(f"❌ X API connection test failed: {e}")
            return False
    
    def get_user_info(self) -> Dict[str, Any]:
        """Get information about the authenticated user"""
        try:
            if not self.client:
                raise Exception("X API client not initialized")
            
            me = self.client.get_me(
                user_fields=['created_at', 'description', 'public_metrics', 'verified']
            )
            
            if me and me.data:
                user_data = me.data
                return {
                    'success': True,
                    'username': user_data.username,
                    'name': user_data.name,
                    'id': user_data.id,
                    'description': getattr(user_data, 'description', ''),
                    'followers_count': getattr(user_data, 'public_metrics', {}).get('followers_count', 0),
                    'following_count': getattr(user_data, 'public_metrics', {}).get('following_count', 0),
                    'tweet_count': getattr(user_data, 'public_metrics', {}).get('tweet_count', 0),
                    'verified': getattr(user_data, 'verified', False)
                }
            else:
                raise Exception("Failed to get user information")
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def post_text(self, text: str) -> Dict[str, Any]:
        """Post a text tweet to X"""
        try:
            if not self.client:
                raise Exception("X API client not initialized")
            
            if len(text) > 280:
                raise ValueError(f"Tweet text too long: {len(text)} characters (max 280)")
            
            if not text.strip():
                raise ValueError("Tweet text cannot be empty")
            
            response = self.client.create_tweet(text=text)
            
            if response and response.data:
                result = {
                    'success': True,
                    'tweet_id': response.data['id'],
                    'text': text,
                    'timestamp': datetime.now().isoformat(),
                    'url': f"https://twitter.com/i/web/status/{response.data['id']}"
                }
                print(f"✅ Tweet posted successfully!")
                print(f"   URL: {result['url']}")
                return result
            else:
                raise Exception("Failed to post tweet - no response data")
                
        except Exception as e:
            result = {
                'success': False,
                'error': str(e),
                'text': text,
                'timestamp': datetime.now().isoformat()
            }
            print(f"❌ Failed to post tweet: {e}")
            return result


if __name__ == "__main__":
    print("🧪 Testing X Platform Handler")
    handler = XPlatformHandler()
    if handler.test_connection():
        user_info = handler.get_user_info()
        if user_info.get('success'):
            print(f"User: @{user_info['username']} ({user_info['name']})")
            print(f"Followers: {user_info.get('followers_count', 0)}")
        print("✅ Test completed successfully!")
    else:
        print("❌ Test failed!")
