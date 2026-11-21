#!/usr/bin/env python3
"""
One-time helper: mint X (Twitter) OAuth 1.0a Access Token + Secret for the
account you want to POST from (e.g. @AIwithRoz).

You already have the app's consumer keys (X_API_KEY / X_API_SECRET). This runs
the PIN-based ("out-of-band") OAuth 1.0a flow: it prints an authorization URL,
you sign in AS THE ACCOUNT YOU WANT TO POST FROM, approve, copy the 7-digit
PIN back here, and it prints the ACCESS TOKEN + SECRET to paste into .env.

Prereqs (do this in the X Developer Portal FIRST):
  • App → User authentication settings → App permissions = READ AND WRITE
    (Type of App: Web App / Native — "Request email" not needed).
  • Any callback URL is fine for PIN flow (e.g. https://localhost); the app
    just needs OAuth 1.0a turned on.

Run:
    venv314_v2/bin/python get_x_tokens.py
"""

import os
import sys
from pathlib import Path

# Load consumer keys from the repo-root .env.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

try:
    import tweepy
except ImportError:
    sys.exit("❌ tweepy not installed. Run: venv314_v2/bin/pip install tweepy")

API_KEY = (os.getenv("X_API_KEY") or "").strip()
API_SECRET = (os.getenv("X_API_SECRET") or "").strip()

if not API_KEY or not API_SECRET:
    sys.exit(
        "❌ X_API_KEY / X_API_SECRET not found in .env.\n"
        "   Add your app's Consumer Key and Secret first, then re-run."
    )

# callback="oob" = PIN-based flow; no web server needed.
handler = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, callback="oob")

try:
    auth_url = handler.get_authorization_url()
except Exception as e:
    sys.exit(
        f"❌ Could not start OAuth flow: {e}\n"
        "   Usually this means the app doesn't have OAuth 1.0a enabled, or the "
        "   consumer keys are wrong."
    )

print("\n1) Open this URL, sign in AS THE ACCOUNT YOU WANT TO POST FROM "
      "(e.g. @AIwithRoz), and click Authorize:\n")
print(f"   {auth_url}\n")
pin = input("2) Paste the 7-digit PIN shown after authorizing: ").strip()

try:
    access_token, access_secret = handler.get_access_token(pin)
except Exception as e:
    sys.exit(f"❌ Failed to exchange PIN for tokens: {e}")

# Confirm who we authenticated as, and that write works.
try:
    client = tweepy.Client(
        consumer_key=API_KEY, consumer_secret=API_SECRET,
        access_token=access_token, access_token_secret=access_secret,
    )
    me = client.get_me()
    who = f"@{me.data.username}" if me and me.data else "(unknown)"
except Exception:
    who = "(could not verify — tokens still printed below)"

print("\n✅ Success! Authorized as:", who)
print("\nPaste these into your root .env (replacing the placeholders):\n")
print(f"X_ACCESS_TOKEN={access_token}")
print(f"X_ACCESS_SECRET={access_secret}")
print("\n(Your existing X_API_KEY, X_API_SECRET, and X_BEARER_TOKEN stay as-is.)")
