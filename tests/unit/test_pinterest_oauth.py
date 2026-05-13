"""Unit tests for pinterest_oauth — HTTP + DB mocked, no live calls."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from ai_bag_agent.ai_content.services import pinterest_oauth as po


FAKE_ENV = {
    "PINTEREST_APP_ID": "1565782",
    "PINTEREST_APP_SECRET": "secret-xyz",
    "PINTEREST_REDIRECT_URI": "http://localhost:8080/oauth/callback",
}


def _resp(json_body=None, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body or {}
    r.text = str(json_body or {})
    return r


# ---------------------------------------------------------------------------
# get_authorization_url
# ---------------------------------------------------------------------------

class TestAuthorizationUrl:
    def test_includes_app_id_and_state(self):
        with patch.dict("os.environ", FAKE_ENV):
            url = po.get_authorization_url(state="abc123")
        assert url.startswith("https://www.pinterest.com/oauth/")
        assert "client_id=1565782" in url
        assert "state=abc123" in url
        assert "boards%3Aread" in url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Foauth%2Fcallback" in url

    def test_missing_app_id_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError):
                po.get_authorization_url(state="x")


# ---------------------------------------------------------------------------
# exchange_code_for_tokens
# ---------------------------------------------------------------------------

class TestExchangeCode:
    def test_success_saves_tokens(self):
        body = {
            "access_token": "pina_new_access",
            "refresh_token": "pina_new_refresh",
            "expires_in": 2592000,
        }
        with patch.dict("os.environ", FAKE_ENV), \
             patch.object(po.requests, "post", return_value=_resp(body)), \
             patch.object(po, "_save_tokens") as save:
            result = po.exchange_code_for_tokens("code_123")
        assert result["success"] is True
        assert result["access_token"] == "pina_new_access"
        save.assert_called_once_with("pina_new_access", "pina_new_refresh", 2592000,
                                     tenant_id="default")

    def test_missing_app_secret_fails(self):
        with patch.dict("os.environ", {}, clear=True):
            result = po.exchange_code_for_tokens("code_123")
        assert result["success"] is False
        assert "APP_ID" in result["error"] or "APP_SECRET" in result["error"]

    def test_http_error_fails(self):
        with patch.dict("os.environ", FAKE_ENV), \
             patch.object(po.requests, "post", return_value=_resp({}, status=400)):
            result = po.exchange_code_for_tokens("bad_code")
        assert result["success"] is False
        assert "400" in result["error"]


# ---------------------------------------------------------------------------
# refresh_access_token
# ---------------------------------------------------------------------------

class TestRefreshAccessToken:
    def test_uses_stored_refresh_token(self):
        body = {"access_token": "pina_refreshed", "refresh_token": "pina_new_rt",
                "expires_in": 2592000}
        with patch.dict("os.environ", FAKE_ENV), \
             patch.object(po, "_setting_get", return_value="pina_existing_rt"), \
             patch.object(po.requests, "post", return_value=_resp(body)) as mock_post, \
             patch.object(po, "_save_tokens") as save:
            result = po.refresh_access_token()
        assert result["success"] is True
        # Confirm we sent grant_type=refresh_token with the stored token
        sent = mock_post.call_args.kwargs["data"]
        assert sent["grant_type"] == "refresh_token"
        assert sent["refresh_token"] == "pina_existing_rt"
        save.assert_called_once()

    def test_no_refresh_token_fails(self):
        with patch.dict("os.environ", {}, clear=True), \
             patch.object(po, "_setting_get", return_value=None):
            result = po.refresh_access_token()
        assert result["success"] is False


# ---------------------------------------------------------------------------
# refresh_if_needed
# ---------------------------------------------------------------------------

class TestRefreshIfNeeded:
    def test_no_stored_token_returns_false(self):
        with patch.object(po, "_stored_expiry", return_value=None):
            assert po.refresh_if_needed() is False

    def test_fresh_token_no_refresh(self):
        future = datetime.now(timezone.utc) + timedelta(days=10)
        with patch.object(po, "_stored_expiry", return_value=future), \
             patch.object(po, "refresh_access_token") as refresh:
            assert po.refresh_if_needed() is True
            refresh.assert_not_called()

    def test_near_expiry_triggers_refresh(self):
        soon = datetime.now(timezone.utc) + timedelta(hours=1)
        with patch.object(po, "_stored_expiry", return_value=soon), \
             patch.object(po, "refresh_access_token",
                          return_value={"success": True, "access_token": "x"}) as refresh:
            assert po.refresh_if_needed() is True
            refresh.assert_called_once()

    def test_refresh_failure_returns_false(self):
        soon = datetime.now(timezone.utc) + timedelta(hours=1)
        with patch.object(po, "_stored_expiry", return_value=soon), \
             patch.object(po, "refresh_access_token",
                          return_value={"success": False, "error": "boom"}):
            assert po.refresh_if_needed() is False


# ---------------------------------------------------------------------------
# get_valid_access_token
# ---------------------------------------------------------------------------

class TestGetValidAccessToken:
    def test_returns_stored_token(self):
        with patch.object(po, "refresh_if_needed", return_value=True), \
             patch.object(po, "_setting_get", return_value="pina_stored"):
            assert po.get_valid_access_token() == "pina_stored"

    def test_falls_back_to_env(self):
        with patch.dict("os.environ", {"PINTEREST_ACCESS_TOKEN": "pina_env"}, clear=True), \
             patch.object(po, "refresh_if_needed", return_value=False), \
             patch.object(po, "_setting_get", return_value=None):
            assert po.get_valid_access_token() == "pina_env"

    def test_returns_none_when_nothing_configured(self):
        with patch.dict("os.environ", {}, clear=True), \
             patch.object(po, "refresh_if_needed", return_value=False), \
             patch.object(po, "_setting_get", return_value=None):
            assert po.get_valid_access_token() is None
