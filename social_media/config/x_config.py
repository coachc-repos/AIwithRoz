#!/usr/bin/env python3
"""
X (Twitter) API Configuration
"""

import os
from typing import Dict
from pathlib import Path

# Load the single root .env so X credentials are available even when this
# module is used outside the web app (e.g. the console launcher). Safe no-op
# if python-dotenv isn't installed or the file is absent; never overrides
# variables already present in the real environment.
try:
    from dotenv import load_dotenv
    _ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
    if _ROOT_ENV.exists():
        load_dotenv(_ROOT_ENV)
except ImportError:
    pass


class XConfig:
    """X (Twitter) API configuration manager"""
    
    # Maps internal credential keys to their environment variable names.
    ENV_VAR_MAP = {
        "api_key": "X_API_KEY",
        "api_key_secret": "X_API_SECRET",
        "access_token": "X_ACCESS_TOKEN",
        "access_token_secret": "X_ACCESS_SECRET",
        "bearer_token": "X_BEARER_TOKEN",  # optional, for API v2
    }

    def __init__(self):
        self.config_dir = Path(__file__).parent
        self.credentials_file = self.config_dir / ".x_credentials"

    def _credentials_from_env(self) -> Dict[str, str]:
        """Read whatever X credentials are present in the environment."""
        creds = {}
        for key, env_name in self.ENV_VAR_MAP.items():
            value = os.environ.get(env_name)
            if value:
                creds[key] = value.strip()
        return creds

    def save_credentials(self, credentials: Dict[str, str]) -> bool:
        """Save X API credentials to secure config file"""
        try:
            with open(self.credentials_file, 'w', encoding='utf-8') as f:
                for key, value in credentials.items():
                    f.write(f"{key}={value}\n")
            os.chmod(self.credentials_file, 0o600)
            print(f"✅ Credentials saved to: {self.credentials_file}")
            return True
        except Exception as e:
            print(f"❌ Error saving credentials: {e}")
            return False
    
    def has_credentials(self) -> bool:
        """Check if credentials are available from the config file or environment"""
        try:
            if self.credentials_file.exists() and self.credentials_file.stat().st_size > 0:
                return True
            return bool(self._credentials_from_env())
        except Exception:
            return False

    def get_credentials(self) -> Dict[str, str]:
        """Get X API credentials from environment variables and/or config file.

        Environment variables (X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN,
        X_ACCESS_SECRET, X_BEARER_TOKEN) provide the base values; any keys
        present in the .x_credentials file override them.
        """
        credentials = self._credentials_from_env()

        if self.credentials_file.exists():
            with open(self.credentials_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and '=' in line:
                        key, value = line.split('=', 1)
                        credentials[key.strip()] = value.strip()

        required_keys = ['api_key', 'api_key_secret', 'access_token', 'access_token_secret']
        
        missing_creds = [key for key in required_keys if key not in credentials or not credentials[key]]
        if missing_creds:
            raise ValueError(f"Missing X API credentials: {missing_creds}")
            
        return credentials
    
    def test_credentials(self) -> bool:
        """Test if the stored credentials are valid"""
        try:
            credentials = self.get_credentials()
            required_keys = ['api_key', 'api_key_secret', 'access_token', 'access_token_secret']
            
            return all(
                key in credentials and 
                credentials[key] and 
                len(credentials[key]) > 10  # Basic length check
                for key in required_keys
            )
        except Exception:
            return False
