"""Smoke-test every external service credential. Read-only — no posts, no costs."""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()

OK = "✅"
FAIL = "❌"
WARN = "⚠️"


def _line(label: str, ok: bool, detail: str = "") -> None:
    icon = OK if ok else FAIL
    print(f"{icon} {label:30} {detail}")


def test_kieai() -> bool:
    """Just check the credentials endpoint — no task creation."""
    import requests
    key = os.environ.get("KIE_AI_API_KEY") or os.environ.get("KIEAI_API_KEY")
    if not key:
        _line("kie.ai", False, "KIE_AI_API_KEY missing")
        return False
    try:
        # kie.ai doesn't have a /ping endpoint — use credits endpoint instead.
        r = requests.get(
            "https://api.kie.ai/api/v1/chat/credit",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if r.status_code == 200:
            body = r.json()
            credits = body.get("data") if isinstance(body, dict) else None
            _line("kie.ai", True, f"credits: {credits}")
            return True
        _line("kie.ai", False, f"HTTP {r.status_code}: {r.text[:120]}")
        return False
    except Exception as exc:
        _line("kie.ai", False, str(exc))
        return False


def test_cloudinary() -> bool:
    try:
        import cloudinary
        import cloudinary.api
        cloudinary.config(
            cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
            api_key=os.environ.get("CLOUDINARY_API_KEY"),
            api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
        )
        info = cloudinary.api.ping()
        _line("Cloudinary", info.get("status") == "ok", str(info))
        return info.get("status") == "ok"
    except Exception as exc:
        _line("Cloudinary", False, str(exc))
        return False


def test_pinterest() -> bool:
    import requests
    token = os.environ.get("PINTEREST_ACCESS_TOKEN")
    if not token:
        _line("Pinterest", False, "PINTEREST_ACCESS_TOKEN missing")
        return False
    try:
        r = requests.get(
            "https://api.pinterest.com/v5/user_account",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            _line("Pinterest", True, f"username: @{data.get('username')}")
            return True
        _line("Pinterest", False, f"HTTP {r.status_code}: {r.text[:140]}")
        return False
    except Exception as exc:
        _line("Pinterest", False, str(exc))
        return False


def test_telegram() -> bool:
    import requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token:
        _line("Telegram bot", False, "TELEGRAM_BOT_TOKEN missing")
        return False
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if r.status_code != 200 or not r.json().get("ok"):
            _line("Telegram bot", False, f"HTTP {r.status_code}: {r.text[:140]}")
            return False
        bot_name = r.json()["result"]["username"]
        _line("Telegram bot", True, f"@{bot_name}")
        if not chat_id:
            _line("Telegram chat", False, "TELEGRAM_CHAT_ID missing")
            return False
        # getChat requires the bot to be inside that chat — it's the cleanest
        # way to verify the chat_id is correct AND the bot is added.
        r2 = requests.get(
            f"https://api.telegram.org/bot{token}/getChat",
            params={"chat_id": chat_id},
            timeout=10,
        )
        if r2.status_code == 200 and r2.json().get("ok"):
            chat = r2.json()["result"]
            label = chat.get("title") or chat.get("username") or chat.get("first_name", "?")
            _line("Telegram chat", True, f"id={chat_id} ({label})")
            return True
        _line("Telegram chat", False, f"HTTP {r2.status_code}: {r2.text[:140]}")
        return False
    except Exception as exc:
        _line("Telegram", False, str(exc))
        return False


def test_meta() -> bool:
    import requests
    token = os.environ.get("FB_PAGE_TOKEN")
    page_id = os.environ.get("FB_PAGE_ID")
    ig_id = os.environ.get("IG_BUSINESS_ACCOUNT_ID")
    if not token or not page_id:
        _line("Facebook page", False, "FB_PAGE_TOKEN or FB_PAGE_ID missing")
        return False
    try:
        r = requests.get(
            f"https://graph.facebook.com/v21.0/{page_id}",
            params={"fields": "id,name", "access_token": token},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            _line("Facebook page", True, f"{data.get('name')} (id={data.get('id')})")
        else:
            _line("Facebook page", False, f"HTTP {r.status_code}: {r.text[:140]}")
            return False
        if not ig_id:
            _line("Instagram", False, "IG_BUSINESS_ACCOUNT_ID missing")
            return False
        r2 = requests.get(
            f"https://graph.facebook.com/v21.0/{ig_id}",
            params={"fields": "id,username", "access_token": token},
            timeout=10,
        )
        if r2.status_code == 200:
            data = r2.json()
            _line("Instagram", True, f"@{data.get('username')} (id={data.get('id')})")
            return True
        _line("Instagram", False, f"HTTP {r2.status_code}: {r2.text[:140]}")
        return False
    except Exception as exc:
        _line("Meta", False, str(exc))
        return False


def test_anthropic() -> bool:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        _line("Anthropic (captions)", False, "ANTHROPIC_API_KEY missing — optional")
        return False
    try:
        import requests
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "ping"}],
            },
            timeout=15,
        )
        if r.status_code == 200:
            _line("Anthropic (captions)", True, "ok")
            return True
        _line("Anthropic (captions)", False, f"HTTP {r.status_code}: {r.text[:140]}")
        return False
    except Exception as exc:
        _line("Anthropic", False, str(exc))
        return False


def main() -> int:
    print("=" * 70)
    print("Credential smoke-test — read-only")
    print("=" * 70)
    results = [
        test_kieai(),
        test_cloudinary(),
        test_pinterest(),
        test_telegram(),
        test_meta(),
        test_anthropic(),
    ]
    print("=" * 70)
    failed = sum(1 for r in results if not r)
    print(f"{len(results) - failed} ok / {len(results)} total")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
