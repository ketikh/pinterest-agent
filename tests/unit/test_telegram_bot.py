"""Unit tests for telegram_bot — all Telegram API calls mocked, no network."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_bag_agent.ai_content.services import telegram_bot as tb


# ---------------------------------------------------------------------------
# _build_keyboard
# ---------------------------------------------------------------------------

class TestBuildKeyboard:
    def test_normal_keyboard_has_five_buttons(self):
        kb = tb._build_keyboard(approval_id=42, regen_count=0)
        flat = [btn for row in kb.inline_keyboard for btn in row]
        assert len(flat) == 5
        assert any(b.callback_data == "approve_42" for b in flat)
        assert any(b.callback_data == "reject_42" for b in flat)
        assert any(b.callback_data == "regen_42" for b in flat)
        assert any(b.callback_data == "promptregen_42" for b in flat)
        assert any(b.callback_data == "editcaption_42" for b in flat)

    def test_max_regen_replaces_regen_button_with_disabled(self):
        kb = tb._build_keyboard(approval_id=42, regen_count=tb.MAX_REGENERATIONS)
        flat = [btn for row in kb.inline_keyboard for btn in row]
        assert any(b.callback_data == "disabled" for b in flat)
        assert not any(b.callback_data == "regen_42" for b in flat)

    def test_regen_button_shows_count(self):
        kb = tb._build_keyboard(approval_id=7, regen_count=2)
        flat = [btn for row in kb.inline_keyboard for btn in row]
        regen = next(b for b in flat if b.callback_data == "regen_7")
        assert "2/3" in regen.text


# ---------------------------------------------------------------------------
# _build_caption
# ---------------------------------------------------------------------------

class TestBuildCaption:
    def test_includes_bag_name_and_count(self):
        snapshot = {
            "bag_name": "Laptop Bag XL",
            "bag_queue_id": 5,
            "generated_image_url": "https://x/y.jpg",
            "reference_url": "https://pinterest.com/pin/123",
            "regeneration_count": 1,
            "telegram_message_id": None,
            "status": "pending",
        }
        caption = tb._build_caption(snapshot)
        assert "Laptop Bag XL" in caption
        assert "#5" in caption
        assert "1/3" in caption
        assert "Reference" in caption

    def test_escapes_markdown_in_bag_name(self):
        snapshot = {
            "bag_name": "Bag_With_Underscores",
            "bag_queue_id": 1,
            "generated_image_url": "https://x.jpg",
            "reference_url": None,
            "regeneration_count": 0,
            "telegram_message_id": None,
            "status": "pending",
        }
        caption = tb._build_caption(snapshot)
        assert "\\_" in caption


# ---------------------------------------------------------------------------
# _append_status
# ---------------------------------------------------------------------------

class TestAppendStatus:
    def test_appends_after_existing_caption(self):
        result = tb._append_status("Hello world", "✅ Approved")
        assert result.startswith("Hello world")
        assert "✅ Approved at" in result

    def test_handles_none_caption(self):
        result = tb._append_status(None, "❌ Rejected")
        assert "❌ Rejected at" in result


# ---------------------------------------------------------------------------
# _with_retry
# ---------------------------------------------------------------------------

class TestWithRetry:
    @pytest.mark.asyncio
    async def test_returns_result_on_success(self):
        factory = AsyncMock(return_value="ok")
        result = await tb._with_retry(factory)
        assert result == "ok"
        assert factory.await_count == 1

    @pytest.mark.asyncio
    async def test_retries_network_error_then_succeeds(self):
        from telegram.error import NetworkError
        calls = {"n": 0}

        async def factory():
            calls["n"] += 1
            if calls["n"] < 2:
                raise NetworkError("transient")
            return "ok"

        with patch.object(tb.asyncio, "sleep", new=AsyncMock()):
            result = await tb._with_retry(factory, retries=3)
        assert result == "ok"
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_returns_none_after_exhausting_retries(self):
        from telegram.error import NetworkError

        async def factory():
            raise NetworkError("always fails")

        with patch.object(tb.asyncio, "sleep", new=AsyncMock()):
            result = await tb._with_retry(factory, retries=2)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_retryable_telegram_error_returns_none_immediately(self):
        from telegram.error import TelegramError

        factory = AsyncMock(side_effect=TelegramError("bad request"))
        result = await tb._with_retry(factory, retries=3)
        assert result is None
        assert factory.await_count == 1


# ---------------------------------------------------------------------------
# Callback routing
# ---------------------------------------------------------------------------

def _make_query(data: str, chat_id: str = "123") -> MagicMock:
    q = MagicMock()
    q.data = data
    q.message = MagicMock()
    q.message.chat_id = int(chat_id)
    q.message.caption = "old caption"
    q.from_user = MagicMock(id=999)
    q.answer = AsyncMock()
    q.edit_message_caption = AsyncMock()
    return q


def _make_update(query: MagicMock) -> SimpleNamespace:
    return SimpleNamespace(callback_query=query)


class TestCallbackRouting:
    @pytest.mark.asyncio
    async def test_unauthorized_chat_is_rejected(self):
        with patch.object(tb, "_TELEGRAM_CHAT_ID", "999999"):
            q = _make_query("approve_5", chat_id="123")
            await tb._handle_callback(_make_update(q), MagicMock())
            q.answer.assert_awaited_once()
            assert "Unauthorized" in q.answer.await_args.args[0]

    @pytest.mark.asyncio
    async def test_disabled_data_shows_alert(self):
        with patch.object(tb, "_TELEGRAM_CHAT_ID", "123"):
            q = _make_query("disabled")
            await tb._handle_callback(_make_update(q), MagicMock())
            q.answer.assert_awaited_once()
            assert q.answer.await_args.kwargs.get("show_alert") is True

    @pytest.mark.asyncio
    async def test_invalid_data_is_handled(self):
        with patch.object(tb, "_TELEGRAM_CHAT_ID", "123"):
            q = _make_query("nonsense")
            await tb._handle_callback(_make_update(q), MagicMock())
            q.answer.assert_awaited_once()
            assert "Invalid" in q.answer.await_args.args[0]

    @pytest.mark.asyncio
    async def test_approve_routes_to_approve_handler(self):
        with patch.object(tb, "_TELEGRAM_CHAT_ID", "123"), \
             patch.object(tb, "_handle_approve", new=AsyncMock()) as mock_h:
            q = _make_query("approve_42")
            await tb._handle_callback(_make_update(q), MagicMock())
            mock_h.assert_awaited_once_with(q, 42)

    @pytest.mark.asyncio
    async def test_reject_routes_to_reject_handler(self):
        with patch.object(tb, "_TELEGRAM_CHAT_ID", "123"), \
             patch.object(tb, "_handle_reject", new=AsyncMock()) as mock_h:
            q = _make_query("reject_7")
            await tb._handle_callback(_make_update(q), MagicMock())
            mock_h.assert_awaited_once_with(q, 7)

    @pytest.mark.asyncio
    async def test_regen_routes_to_regenerate_handler(self):
        with patch.object(tb, "_TELEGRAM_CHAT_ID", "123"), \
             patch.object(tb, "_handle_regenerate", new=AsyncMock()) as mock_h:
            q = _make_query("regen_99")
            await tb._handle_callback(_make_update(q), MagicMock())
            mock_h.assert_awaited_once_with(q, 99)


# ---------------------------------------------------------------------------
# _handle_regenerate — max-count guard
# ---------------------------------------------------------------------------

class TestCaptionReply:
    @pytest.mark.asyncio
    async def test_reply_from_other_chat_is_ignored(self):
        with patch.object(tb, "_TELEGRAM_CHAT_ID", "999"):
            msg = MagicMock()
            msg.chat_id = 123
            msg.reply_to_message = MagicMock(message_id=5)
            msg.text = "new caption"
            update = SimpleNamespace(message=msg)

            # Patch DB helpers to make sure they're NOT called
            with patch.object(tb, "_find_approval_by_message_id") as finder:
                await tb._handle_caption_reply(update, MagicMock())
            finder.assert_not_called()

    @pytest.mark.asyncio
    async def test_reply_to_unknown_message_is_silent(self):
        with patch.object(tb, "_TELEGRAM_CHAT_ID", "123"):
            msg = MagicMock()
            msg.chat_id = 123
            msg.reply_to_message = MagicMock(message_id=999)
            msg.text = "new caption"
            msg.reply_text = AsyncMock()
            update = SimpleNamespace(message=msg)

            ctx = MagicMock()
            ctx.application.chat_data = {123: {}}  # no awaiting_prompt_for

            with patch.object(tb, "_find_approval_by_message_id", return_value=None):
                await tb._handle_caption_reply(update, ctx)
            msg.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_reply_saves_and_confirms(self):
        with patch.object(tb, "_TELEGRAM_CHAT_ID", "123"):
            msg = MagicMock()
            msg.chat_id = 123
            msg.reply_to_message = MagicMock(message_id=42)
            msg.text = "ლამაზი ჩანთა ✨ #TissuGeorgia"
            msg.reply_text = AsyncMock()
            update = SimpleNamespace(message=msg)

            ctx = MagicMock()
            ctx.application.chat_data = {123: {}}

            snapshot = {
                "id": 7, "bag_name": "Bag", "bag_queue_id": 1,
                "generated_image_url": "https://x.jpg", "reference_url": None,
                "regeneration_count": 0, "telegram_message_id": "42",
                "status": "pending", "fb_caption": "ლამაზი ჩანთა ✨ #TissuGeorgia",
                "ig_caption": "ლამაზი ჩანთა ✨ #TissuGeorgia",
            }

            with patch.object(tb, "_find_approval_by_message_id", return_value=7), \
                 patch.object(tb, "_set_captions_for_approval", return_value=True) as setter, \
                 patch.object(tb, "_load_approval_snapshot", return_value=snapshot), \
                 patch.object(tb, "_with_retry", new=AsyncMock()):
                await tb._handle_caption_reply(update, ctx)

            setter.assert_called_once_with(7, "ლამაზი ჩანთა ✨ #TissuGeorgia")

    @pytest.mark.asyncio
    async def test_prompt_state_routes_to_regen(self):
        with patch.object(tb, "_TELEGRAM_CHAT_ID", "123"):
            msg = MagicMock()
            msg.chat_id = 123
            msg.reply_to_message = None
            msg.text = "preserve original dimensions"
            update = SimpleNamespace(message=msg)

            ctx = MagicMock()
            ctx.application.chat_data = {123: {"awaiting_prompt_for": 9}}

            with patch.object(tb, "_kick_off_prompt_regen", new=AsyncMock()) as kick:
                await tb._handle_caption_reply(update, ctx)

            kick.assert_awaited_once()
            args = kick.await_args.args
            assert args[0] == 9
            assert args[1] == "preserve original dimensions"
            # State cleared
            assert "awaiting_prompt_for" not in ctx.application.chat_data[123]


class TestRegenerateGuard:
    @pytest.mark.asyncio
    async def test_max_count_triggers_alert_and_auto_reject(self):
        q = _make_query("regen_50")
        snapshot = {"id": 50, "regeneration_count": tb.MAX_REGENERATIONS,
                    "telegram_message_id": "111"}
        with patch.object(tb, "_load_approval_snapshot", return_value=snapshot), \
             patch.object(tb, "_update_status", return_value=True), \
             patch.object(tb, "_with_retry", new=AsyncMock()):
            await tb._handle_regenerate(q, 50)
        q.answer.assert_awaited()
        # show_alert=True passed
        assert q.answer.await_args.kwargs.get("show_alert") is True

    @pytest.mark.asyncio
    async def test_below_max_acknowledges_immediately_and_schedules_task(self):
        q = _make_query("regen_51")
        snapshot = {"id": 51, "regeneration_count": 0, "telegram_message_id": "222"}
        with patch.object(tb, "_load_approval_snapshot", return_value=snapshot), \
             patch.object(tb, "_with_retry", new=AsyncMock()), \
             patch.object(tb.asyncio, "create_task") as mock_create:
            await tb._handle_regenerate(q, 51)
        # Immediate ack happened
        q.answer.assert_awaited_once()
        assert "Regenerating" in q.answer.await_args.args[0]
        # Pipeline scheduled
        mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_approval_returns_alert(self):
        q = _make_query("regen_404")
        with patch.object(tb, "_load_approval_snapshot", return_value=None):
            await tb._handle_regenerate(q, 404)
        q.answer.assert_awaited_once()
        assert "not found" in q.answer.await_args.args[0].lower()
