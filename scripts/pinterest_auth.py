#!/usr/bin/env python3
"""Pinterest OAuth helper — run once to get access + refresh tokens.

Usage:
    source venv/bin/activate
    python scripts/pinterest_auth.py

Requires in .env:
    PINTEREST_APP_ID
    PINTEREST_APP_SECRET

After running, saves to .env:
    PINTEREST_ACCESS_TOKEN
    PINTEREST_REFRESH_TOKEN
"""

from __future__ import annotations

import os
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv, set_key
    load_dotenv(project_root / ".env")
except ImportError:
    print("ERROR: python-dotenv not installed. Run: pip install python-dotenv")
    sys.exit(1)

import requests

REDIRECT_URI = "http://localhost:8765/callback"
AUTH_URL = "https://www.pinterest.com/oauth/"
TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"
SCOPES = "boards:read,pins:read"

_auth_code: str = ""


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [""])[0]
        _auth_code = code

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if code:
            self.wfile.write(b"<h2>Authorization successful!</h2><p>You can close this tab.</p>")
        else:
            self.wfile.write(b"<h2>Authorization failed.</h2>")

    def log_message(self, *args):
        pass  # suppress server logs


def main() -> None:
    app_id = os.environ.get("PINTEREST_APP_ID")
    app_secret = os.environ.get("PINTEREST_APP_SECRET")

    if not app_id or not app_secret:
        print("ERROR: Set PINTEREST_APP_ID and PINTEREST_APP_SECRET in .env first")
        sys.exit(1)

    auth_params = urllib.parse.urlencode({
        "client_id": app_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
    })
    auth_url = f"{AUTH_URL}?{auth_params}"

    print("=" * 60)
    print("Pinterest OAuth — Token Generator")
    print("=" * 60)
    print()
    print("ბრაუზერი გაიხსნება Pinterest-ის authorization გვერდით.")
    print("შეიყვანე Pinterest-ის credentials და დაადასტურე.")
    print()

    server = HTTPServer(("localhost", 8765), _CallbackHandler)
    thread = Thread(target=server.handle_request)
    thread.start()

    webbrowser.open(auth_url)
    print("ლოდინი authorization-ს...")
    thread.join(timeout=120)

    if not _auth_code:
        print("ERROR: Authorization code not received (timeout or cancelled).")
        sys.exit(1)

    # Exchange code for tokens
    resp = requests.post(
        TOKEN_URL,
        auth=(app_id, app_secret),
        data={
            "grant_type": "authorization_code",
            "code": _auth_code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=15,
    )

    if resp.status_code != 200:
        print(f"ERROR: Token exchange failed: {resp.text[:300]}")
        sys.exit(1)

    body = resp.json()
    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")
    expires_in = body.get("expires_in", 86400)

    env_path = project_root / ".env"
    set_key(str(env_path), "PINTEREST_ACCESS_TOKEN", access_token)
    if refresh_token:
        set_key(str(env_path), "PINTEREST_REFRESH_TOKEN", refresh_token)

    print()
    print("=" * 60)
    print("✅ Tokens saved to .env!")
    print(f"   Access token:   {access_token[:30]}...")
    if refresh_token:
        print(f"   Refresh token:  {refresh_token[:30]}...")
        print(f"   Expires in:     {expires_in // 3600} hours")
    print()
    print("ახლა გაუშვი: python scripts/test_pinterest.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
