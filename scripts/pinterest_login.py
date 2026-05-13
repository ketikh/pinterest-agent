#!/usr/bin/env python3
"""One-time (per year) Pinterest OAuth login.

Usage:
    source venv/bin/activate
    python scripts/pinterest_login.py

What it does:
    1. Opens https://www.pinterest.com/oauth/?... in your browser
    2. Spins up a tiny HTTP server on localhost:8080
    3. After you click "Allow", Pinterest redirects to /oauth/callback?code=...
    4. The script exchanges the code for access + refresh tokens
    5. Tokens are stored in the Setting table (per tenant)
    6. The 30-day access token auto-renews from there

Run again only when the refresh token expires (every ~year) or if you
need to switch Pinterest accounts.
"""

from __future__ import annotations

import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass

LISTEN_HOST = "localhost"
LISTEN_PORT = 8080
TENANT_ID = "default"

# Shared state between the request handler and main thread
_captured = {"code": None, "state": None, "error": None}


class _OAuthHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence default access log
        pass

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/oauth/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        if "error" in params:
            _captured["error"] = params["error"][0]
            body = b"<h2>Pinterest returned an error. Check the terminal.</h2>"
        elif "code" in params:
            _captured["code"] = params["code"][0]
            _captured["state"] = params.get("state", [None])[0]
            body = (
                b"<h2 style='font-family: sans-serif'>"
                b"&#9989; Authorized. You can close this tab and return to the terminal."
                b"</h2>"
            )
        else:
            _captured["error"] = "missing_code"
            body = b"<h2>No code returned. Check the terminal.</h2>"

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    print("=" * 60)
    print("Pinterest OAuth Login")
    print("=" * 60)

    from ai_bag_agent import create_app
    from ai_bag_agent.ai_content.services.pinterest_oauth import (
        exchange_code_for_tokens,
        get_authorization_url,
    )

    # Anti-CSRF state — verified after callback
    state = secrets.token_urlsafe(24)
    auth_url = get_authorization_url(state)

    # Start the callback server in a daemon thread
    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), _OAuthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Listening on http://{LISTEN_HOST}:{LISTEN_PORT}/oauth/callback")
    print()
    print("Opening browser…  if it doesn't open, paste this URL manually:")
    print(f"  {auth_url}")
    print()
    webbrowser.open(auth_url)

    # Wait for the callback handler to populate _captured (5 min timeout)
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        if _captured["code"] or _captured["error"]:
            break
        time.sleep(0.25)

    server.shutdown()

    if _captured["error"]:
        print(f"\n❌ OAuth failed: {_captured['error']}")
        sys.exit(1)
    if not _captured["code"]:
        print("\n❌ Timed out waiting for OAuth redirect (5 min).")
        sys.exit(1)
    if _captured["state"] != state:
        print(f"\n❌ State mismatch — possible CSRF. Aborting.")
        sys.exit(1)

    print(f"✅ Code received, exchanging for tokens…")

    # We need a Flask app context to persist into the Setting table
    app = create_app()
    with app.app_context():
        result = exchange_code_for_tokens(_captured["code"], tenant_id=TENANT_ID)

    if not result["success"]:
        print(f"❌ Token exchange failed: {result['error']}")
        sys.exit(1)

    print()
    print("=" * 60)
    print("✅ Tokens saved to DB (Setting table, tenant=default)")
    print("=" * 60)
    days = int(result["expires_in"]) // 86400
    print(f"   access_token  expires in ~{days} day(s)")
    print(f"   refresh_token stored — re-run this script once per year")
    print()
    print("Verify:  python scripts/test_pinterest.py")


if __name__ == "__main__":
    main()
