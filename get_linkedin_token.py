#!/usr/bin/env python3
"""
One-time helper: mint a LinkedIn OAuth 2.0 member access token for the account
you want to POST from (e.g. the person who admins @AIwithRoz).

LinkedIn removed the one-click token generator from the developer portal, so we
run the real Authorization-Code flow: this opens your browser, you sign in and
approve, LinkedIn redirects back to a tiny local server, and the script exchanges
the code for an access token — then prints LINKEDIN_ACCESS_TOKEN to paste in .env.

Prereqs (in the LinkedIn app → Auth tab):
  • Products added: "Share on LinkedIn" + "Sign In with LinkedIn using OpenID
    Connect"  (scopes: w_member_social openid profile).
  • Authorized redirect URL added EXACTLY:  http://localhost:8000/callback
  • .env has LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET set.

Run:
    venv314/bin/python get_linkedin_token.py
"""

import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

try:
    import requests
except ImportError:
    sys.exit("❌ requests not installed. Run: venv314/bin/pip install requests")

CLIENT_ID = (os.getenv("LINKEDIN_CLIENT_ID") or "").strip()
CLIENT_SECRET = (os.getenv("LINKEDIN_CLIENT_SECRET") or "").strip()
REDIRECT_URI = "http://localhost:8000/callback"
SCOPES = "openid profile w_member_social email"
PORT = 8000

if not CLIENT_ID or not CLIENT_SECRET:
    sys.exit(
        "❌ LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET missing in .env.\n"
        "   Copy them from the app's Auth tab (Application credentials), then re-run."
    )

_result = {}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = urllib.parse.parse_qs(parsed.query)
        _result["code"] = (qs.get("code") or [None])[0]
        _result["error"] = (qs.get("error_description") or qs.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        msg = ("✅ LinkedIn authorization received — you can close this tab and "
               "return to the terminal.") if _result.get("code") else \
              ("❌ Authorization failed: " + str(_result.get("error")))
        self.wfile.write(f"<html><body style='font-family:sans-serif;padding:40px'>"
                         f"<h2>{msg}</h2></body></html>".encode())

    def log_message(self, *a):  # silence server logs
        pass


def main() -> int:
    auth_url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": "linedrive",
    })

    print("\n1) Opening your browser to sign in AS THE ACCOUNT YOU WANT TO POST "
          "FROM and approve access.\n   If it doesn't open, paste this URL:\n")
    print(f"   {auth_url}\n")

    try:
        import webbrowser
        webbrowser.open(auth_url)
    except Exception:
        pass

    print(f"2) Waiting for the redirect to {REDIRECT_URI} …")
    try:
        server = HTTPServer(("localhost", PORT), _Handler)
    except OSError as e:
        sys.exit(f"❌ Could not start local server on port {PORT}: {e}\n"
                 f"   Close whatever is using port {PORT} and re-run.")
    while "code" not in _result and "error" not in _result:
        server.handle_request()
    server.server_close()

    if not _result.get("code"):
        sys.exit(f"❌ Authorization failed: {_result.get('error')}")

    print("3) Exchanging the code for an access token …")
    tok = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": _result["code"],
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if tok.status_code != 200:
        sys.exit(f"❌ Token exchange failed ({tok.status_code}): {tok.text[:300]}")
    access_token = tok.json().get("access_token")
    if not access_token:
        sys.exit(f"❌ No access_token in response: {tok.text[:300]}")

    # Confirm identity + resolve the author URN.
    who, urn = "(unknown)", ""
    try:
        info = requests.get("https://api.linkedin.com/v2/userinfo",
                            headers={"Authorization": f"Bearer {access_token}"},
                            timeout=15)
        if info.status_code == 200:
            j = info.json()
            who = j.get("name") or j.get("email") or "(unknown)"
            if j.get("sub"):
                urn = f"urn:li:person:{j['sub']}"
    except Exception:
        pass

    print(f"\n✅ Success! Authorized as: {who}")
    print("\nPaste this into your root .env (replacing the placeholder):\n")
    print(f"LINKEDIN_ACCESS_TOKEN={access_token}")
    if urn:
        print(f"LINKEDIN_AUTHOR_URN={urn}   # optional — auto-resolves if left blank")
    print("\n(The token lasts ~2 months; re-run this script to refresh it.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
