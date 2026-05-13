"""Telegram bot — approval workflow for generated bag photos.

Architecture:
    The bot runs `python-telegram-bot` (async, v21+) inside a dedicated
    background thread that owns its own asyncio event loop. Flask routes,
    APScheduler jobs and test scripts call the sync wrappers below; those
    wrappers schedule coroutines onto the bot loop via
    `asyncio.run_coroutine_threadsafe`.

    See `docs/decisions/003-telegram-polling.md` for rationale.

Lifecycle:
    init_telegram_bot(app)  — call once from create_app()
    send_approval_request_sync(approval_id) — send photo + 3 buttons
    shutdown_bot() — graceful stop (called on Flask teardown)

Security:
    Callbacks from any chat other than TELEGRAM_CHAT_ID are rejected.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)

MAX_REGENERATIONS = int(os.environ.get("MAX_REGENERATIONS", "3"))
_TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Module state (set once at startup)
_application: Optional[Application] = None
_bot_loop: Optional[asyncio.AbstractEventLoop] = None
_flask_app: Any = None
_bot_thread: Optional[threading.Thread] = None
_ready_event = threading.Event()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def init_telegram_bot(flask_app: Any) -> bool:
    """Start the Telegram bot in a background thread.

    Returns False if the token is missing or startup fails within 5 s.
    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _flask_app, _bot_thread

    if not _TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled")
        return False

    if _bot_thread is not None and _bot_thread.is_alive():
        logger.debug("Telegram bot already running")
        return True

    _flask_app = flask_app
    _ready_event.clear()
    _bot_thread = threading.Thread(target=_run_bot, name="telegram-bot", daemon=True)
    _bot_thread.start()

    if not _ready_event.wait(timeout=5):
        logger.error("Telegram bot did not become ready within 5 s")
        return False

    logger.info("Telegram bot started (polling mode)")
    return True


def shutdown_bot() -> None:
    """Gracefully stop the bot. Safe to call even if it was never started."""
    if _bot_loop is None or not _bot_loop.is_running():
        return
    _bot_loop.call_soon_threadsafe(_bot_loop.stop)
    if _bot_thread is not None:
        _bot_thread.join(timeout=5)


def _run_bot() -> None:
    """Thread entry point: create event loop, run Application, poll forever."""
    global _application, _bot_loop

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _bot_loop = loop

    # Default httpx timeouts in python-telegram-bot are 5s each — way too
    # tight for multipart upload of a 5-9 MB generated photo. Bump to 60s
    # for write (upload) and 30s for read/connect.
    application = (
        Application.builder()
        .token(_TELEGRAM_BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(60.0)
        .pool_timeout(30.0)
        .build()
    )
    application.add_handler(CallbackQueryHandler(_handle_callback))
    # Reply-to-photo-message → admin is overriding the captions
    application.add_handler(MessageHandler(
        filters.REPLY & filters.TEXT & ~filters.COMMAND,
        _handle_caption_reply,
    ))
    _application = application

    async def _startup() -> None:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(
            drop_pending_updates=False,
            allowed_updates=Update.ALL_TYPES,
        )
        _ready_event.set()

    try:
        loop.run_until_complete(_startup())
        loop.run_forever()
    except Exception:
        logger.exception("Telegram bot crashed")
    finally:
        try:
            loop.run_until_complete(application.updater.stop())
            loop.run_until_complete(application.stop())
            loop.run_until_complete(application.shutdown())
        except Exception:
            logger.debug("Telegram shutdown raised", exc_info=True)
        loop.close()


# ---------------------------------------------------------------------------
# Public sync API (callable from any thread)
# ---------------------------------------------------------------------------

def send_approval_request_sync(
    approval_id: int,
    tenant_id: str = "default",
    timeout: int = 30,
) -> Optional[str]:
    """Send approval request to TELEGRAM_CHAT_ID. Returns message_id or None.

    The DB row's `telegram_message_id` is updated on success.
    """
    if _bot_loop is None:
        logger.error("Telegram bot not initialized — call init_telegram_bot() first")
        return None

    future = asyncio.run_coroutine_threadsafe(
        _send_approval_request(approval_id, tenant_id), _bot_loop
    )
    try:
        return future.result(timeout=timeout)
    except Exception:
        logger.exception("send_approval_request_sync failed for approval_id=%s", approval_id)
        return None


# ---------------------------------------------------------------------------
# Async core — send + callbacks
# ---------------------------------------------------------------------------

async def _send_approval_request(approval_id: int, tenant_id: str) -> Optional[str]:
    """Read approval from DB → send photo + keyboard → save message_id."""
    snapshot = await asyncio.to_thread(_load_approval_snapshot, approval_id)
    if snapshot is None:
        logger.error("Approval %s not found", approval_id)
        return None

    caption = _build_caption(snapshot)
    keyboard = _build_keyboard(approval_id, snapshot["regeneration_count"])

    # Telegram chokes on multi-MB photos (5–9 MB images either time out on
    # multipart upload or get "Wrong type of the web page content" on URL
    # fetch). We ask Cloudinary for a smaller delivery — original full-size
    # PNG stays untouched for FB/IG. ~300 KB is plenty for Telegram preview.
    photo_url = _cloudinary_thumb(snapshot["generated_image_url"])
    photo_arg = await _fetch_image_bytes(photo_url) or photo_url

    message = await _with_retry(lambda: _application.bot.send_photo(
        chat_id=_TELEGRAM_CHAT_ID,
        photo=photo_arg,
        caption=caption,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    ))
    if message is None:
        return None

    await asyncio.to_thread(_save_message_id, approval_id, str(message.message_id))
    return str(message.message_id)


async def _handle_caption_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin replied — either updating the caption, or supplying a prompt
    after clicking the 🎨 Regen + prompt button.

    State for prompt-mode lives in `application.chat_data[chat_id]` so it
    survives between callback and the follow-up message.
    """
    msg = update.message
    if msg is None:
        return

    # Only listen to the authorised chat
    if str(msg.chat_id) != _TELEGRAM_CHAT_ID:
        return

    text = (msg.text or "").strip()
    if not text:
        return

    chat_data = context.application.chat_data[int(_TELEGRAM_CHAT_ID)]
    awaiting_prompt = chat_data.get("awaiting_prompt_for")
    awaiting_caption = chat_data.get("awaiting_caption_for")

    # /cancel — clear any pending state
    if text.lower() == "/cancel":
        cancelled = bool(awaiting_prompt or awaiting_caption)
        chat_data.pop("awaiting_prompt_for", None)
        chat_data.pop("awaiting_caption_for", None)
        if cancelled:
            await _with_retry(lambda: msg.reply_text("OK, cancelled."))
        return

    # Pending prompt → regen with this text
    if awaiting_prompt is not None:
        chat_data.pop("awaiting_prompt_for", None)
        await _kick_off_prompt_regen(awaiting_prompt, text, msg)
        return

    # Pending caption (button-triggered) → save as caption
    approval_id = awaiting_caption
    if approval_id is not None:
        chat_data.pop("awaiting_caption_for", None)
        await _save_caption_and_refresh(approval_id, text, msg)
        return

    # Fallback: reply directly to a photo → save as caption (legacy path)
    if msg.reply_to_message is None:
        return
    replied_msg_id = str(msg.reply_to_message.message_id)
    approval_id = await asyncio.to_thread(_find_approval_by_message_id, replied_msg_id)
    if approval_id is None:
        return
    await _save_caption_and_refresh(approval_id, text, msg)


async def _save_caption_and_refresh(approval_id: int, new_caption: str, ack_msg) -> None:
    """Save caption to DB, re-render the photo message, ack the admin."""
    saved = await asyncio.to_thread(_set_captions_for_approval, approval_id, new_caption)
    if not saved:
        await _with_retry(lambda: ack_msg.reply_text("❌ Caption save failed."))
        return

    snapshot = await asyncio.to_thread(_load_approval_snapshot, approval_id)
    if snapshot is not None and snapshot.get("telegram_message_id"):
        new_full_caption = _build_caption(snapshot)
        keyboard = _build_keyboard(approval_id, snapshot["regeneration_count"])
        await _with_retry(lambda: _application.bot.edit_message_caption(
            chat_id=_TELEGRAM_CHAT_ID,
            message_id=int(snapshot["telegram_message_id"]),
            caption=new_full_caption,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        ))

    await _with_retry(lambda: ack_msg.reply_text(f"✅ Caption updated for #{approval_id}"))


async def _handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    # Security: ignore callbacks from any chat other than the authorized one.
    if str(query.message.chat_id) != _TELEGRAM_CHAT_ID:
        await query.answer("Unauthorized chat.", show_alert=True)
        logger.warning(
            "Unauthorized callback from user=%s chat=%s",
            query.from_user.id if query.from_user else "?",
            query.message.chat_id,
        )
        return

    data = query.data or ""
    if data == "disabled":
        await query.answer("Max regenerations reached", show_alert=True)
        return

    try:
        action, approval_id_str = data.split("_", 1)
        approval_id = int(approval_id_str)
    except (ValueError, AttributeError):
        await query.answer("Invalid action", show_alert=True)
        logger.warning("Unrecognized callback data: %r", data)
        return

    if action == "approve":
        await _handle_approve(query, approval_id)
    elif action == "reject":
        await _handle_reject(query, approval_id)
    elif action == "regen":
        await _handle_regenerate(query, approval_id)
    elif action == "promptregen":
        await _handle_prompt_regen_request(query, approval_id, context)
    elif action == "editcaption":
        await _handle_edit_caption_request(query, approval_id, context)
    elif action == "postnow":
        await _handle_post_now(query, approval_id)
    else:
        await query.answer("Unknown action", show_alert=True)


async def _handle_post_now(query, approval_id: int) -> None:
    """🚀 Post Now — push to FB + IG immediately, in a background task."""
    await query.answer("🚀 Posting…")
    await _with_retry(lambda: query.edit_message_caption(
        caption=_append_status(query.message.caption, "🚀 Posting to FB + IG…"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=None,
    ))
    asyncio.create_task(_run_post_now(approval_id))


async def _run_post_now(approval_id: int) -> None:
    """Background runner: mark approved + post, then report back to chat."""
    try:
        result = await asyncio.to_thread(_blocking_post_now, approval_id)
    except Exception as exc:
        # Bind error text outside the lambda — Python deletes `exc` when the
        # except block exits, and flake8 (F821) is right to flag the capture.
        error_text = _truncate(str(exc), 200)
        logger.exception("Post Now failed for #%s", approval_id)
        await _with_retry(lambda: _application.bot.send_message(
            chat_id=_TELEGRAM_CHAT_ID,
            text=f"❌ Post Now failed for #{approval_id}: {error_text}",
        ))
        return

    lines = []
    if result.get("success"):
        lines.append(f"✅ *Posted #{approval_id}*")
    else:
        lines.append(f"⚠️ *Post Now finished for #{approval_id}*")

    fb = result.get("fb_status")
    ig = result.get("ig_status")
    if fb == "success" and result.get("fb_post_id"):
        lines.append(f"📘 FB: [{result['fb_post_id']}](https://www.facebook.com/{result['fb_post_id']})")
    elif fb == "failed":
        lines.append("📘 FB: ❌ failed")
    if ig == "success" and result.get("ig_post_id"):
        lines.append(f"📷 IG media id: `{result['ig_post_id']}`")
    elif ig == "failed":
        lines.append("📷 IG: ❌ failed")

    err = result.get("error")
    if err and not result.get("success"):
        lines.append(f"\n_Error:_ {_truncate(err, 200)}")

    await _with_retry(lambda: _application.bot.send_message(
        chat_id=_TELEGRAM_CHAT_ID,
        text="\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    ))


def _blocking_post_now(approval_id: int) -> dict:
    """Synchronous: flip status to 'approved' if needed, then post."""
    from ..models import PendingApproval
    from ...extensions import db
    from .social_poster import post_to_both

    with _flask_app.app_context():
        a = db.session.get(PendingApproval, approval_id)
        if a is None:
            return {"success": False, "error": "Approval not found"}
        if a.status != "approved":
            a.status = "approved"
            a.responded_at = datetime.now(timezone.utc)
            db.session.commit()
        tenant_id = a.tenant_id
    return post_to_both(approval_id, tenant_id=tenant_id)


async def _handle_edit_caption_request(query, approval_id: int, context) -> None:
    """✏️ Edit caption button → bot asks for caption text, next reply saves it."""
    snapshot = await asyncio.to_thread(_load_approval_snapshot, approval_id)
    if snapshot is None:
        await query.answer("Approval not found", show_alert=True)
        return

    context.application.chat_data[int(_TELEGRAM_CHAT_ID)]["awaiting_caption_for"] = approval_id
    await query.answer("✏️ Send your caption")
    await _with_retry(lambda: _application.bot.send_message(
        chat_id=_TELEGRAM_CHAT_ID,
        text=(
            f"✏️ *Send the new caption for #{approval_id}*\n\n"
            "შენი ტექსტი იქნება ერთიანად Facebook-ზე და Instagram-ზე.\n\n"
            "_Send /cancel to skip._"
        ),
        parse_mode=ParseMode.MARKDOWN,
    ))


async def _handle_prompt_regen_request(query, approval_id: int, context) -> None:
    """🎨 Custom regen button → ask admin for prompt addition, then regenerate."""
    snapshot = await asyncio.to_thread(_load_approval_snapshot, approval_id)
    if snapshot is None:
        await query.answer("Approval not found", show_alert=True)
        return
    if snapshot["regeneration_count"] >= MAX_REGENERATIONS:
        await query.answer("Max regenerations reached", show_alert=True)
        return

    # Park state on the bot's chat-level data so the next reply knows we're
    # waiting for a prompt and not a caption.
    context.application.chat_data[int(_TELEGRAM_CHAT_ID)]["awaiting_prompt_for"] = approval_id
    await query.answer("🎨 Send your prompt addition")
    await _with_retry(lambda: _application.bot.send_message(
        chat_id=_TELEGRAM_CHAT_ID,
        text=(
            f"✏️ Reply with your prompt for approval #{approval_id}\n\n"
            "მაგ:\n"
            "• Preserve original bag dimensions\n"
            "• Outdoor setting, golden hour\n"
            "• Make the background darker\n\n"
            "Send /cancel to skip."
        ),
    ))


async def _handle_approve(query, approval_id: int) -> None:
    await query.answer("✅ Approved")
    success = await asyncio.to_thread(_update_status, approval_id, "approved")
    new_caption = _append_status(query.message.caption, "✅ Approved" if success else "⚠️ DB error")
    await _with_retry(lambda: query.edit_message_caption(
        caption=new_caption,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=None,
    ))


async def _handle_reject(query, approval_id: int) -> None:
    await query.answer("❌ Rejected")
    success = await asyncio.to_thread(_update_status, approval_id, "rejected")
    new_caption = _append_status(query.message.caption, "❌ Rejected" if success else "⚠️ DB error")
    await _with_retry(lambda: query.edit_message_caption(
        caption=new_caption,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=None,
    ))


async def _handle_regenerate(query, approval_id: int) -> None:
    snapshot = await asyncio.to_thread(_load_approval_snapshot, approval_id)
    if snapshot is None:
        await query.answer("Approval not found", show_alert=True)
        return

    if snapshot["regeneration_count"] >= MAX_REGENERATIONS:
        await query.answer("Max regenerations reached", show_alert=True)
        await asyncio.to_thread(_update_status, approval_id, "rejected")
        await _with_retry(lambda: query.edit_message_caption(
            caption=_append_status(query.message.caption, "❌ Max regens — auto-rejected"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=None,
        ))
        return

    # 1. Immediate acknowledge — 15 s timeout starts ticking
    await query.answer("🔄 Regenerating, please wait...")

    # 2. Remove keyboard + mark message as in-progress so admin can't double-click
    original_caption = query.message.caption or ""
    await _with_retry(lambda: query.edit_message_caption(
        caption=_append_status(original_caption, "🔄 Regenerating..."),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=None,
    ))

    # 3. Run pipeline in background — does NOT block the callback
    asyncio.create_task(_run_regeneration_pipeline(approval_id, original_caption))


async def _kick_off_prompt_regen(approval_id: int, extra_prompt: str, ack_msg) -> None:
    """Admin sent a prompt addition → start a regen with it. Same UX promise
    as the 🔄 button (immediate ack, message edited, background pipeline)."""
    snapshot = await asyncio.to_thread(_load_approval_snapshot, approval_id)
    if snapshot is None:
        await _with_retry(lambda: ack_msg.reply_text("❌ Approval not found."))
        return
    if snapshot["regeneration_count"] >= MAX_REGENERATIONS:
        await _with_retry(lambda: ack_msg.reply_text("❌ Max regenerations reached."))
        return

    # Visible, quoted confirmation — admin sees the prompt back so they know
    # the bot understood it correctly.
    confirmation = (
        f"🎨 *Regeneration started for #{approval_id}*\n\n"
        f"📝 *Your prompt:*\n"
        f"> {_escape_md(_truncate(extra_prompt, 300))}\n\n"
        "⏳ Takes 30–300s. The new photo will arrive in this chat when ready."
    )
    await _with_retry(lambda: _application.bot.send_message(
        chat_id=_TELEGRAM_CHAT_ID,
        text=confirmation,
        parse_mode=ParseMode.MARKDOWN,
        reply_to_message_id=ack_msg.message_id,
    ))

    # Edit original approval photo: mark as regenerating, drop keyboard
    if snapshot.get("telegram_message_id"):
        await _with_retry(lambda: _application.bot.edit_message_caption(
            chat_id=_TELEGRAM_CHAT_ID,
            message_id=int(snapshot["telegram_message_id"]),
            caption=_append_status(
                _build_caption(snapshot),
                f"🎨 Regenerating with prompt: {_truncate(extra_prompt, 80)}",
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=None,
        ))

    old_caption = _build_caption(snapshot)
    asyncio.create_task(_run_regeneration_pipeline(approval_id, old_caption, extra_prompt))


async def _run_regeneration_pipeline(
    old_approval_id: int,
    old_caption: str,
    extra_prompt: str = "",
) -> None:
    """Pinterest → kie.ai → Cloudinary → new approval row → new Telegram message.

    On any failure: restore the old message's keyboard so the admin can retry,
    and append the error to the caption. `regeneration_count` is only
    incremented on success.
    """
    try:
        new_approval_id = await asyncio.to_thread(
            _blocking_regenerate, old_approval_id, extra_prompt,
        )
    except Exception as exc:
        logger.exception("Regeneration pipeline failed for approval %s", old_approval_id)
        await _restore_keyboard_with_error(old_approval_id, old_caption, str(exc))
        return

    if new_approval_id is None:
        await _restore_keyboard_with_error(
            old_approval_id, old_caption, "regeneration returned no result"
        )
        return

    # Send fresh message (not edit, not reply) so admin gets a clean push
    message_id = await _send_approval_request(new_approval_id, "default")
    if message_id is None:
        logger.error("New approval %s created but Telegram send failed", new_approval_id)


def _blocking_regenerate(old_approval_id: int, extra_prompt: str = "") -> Optional[int]:
    """Synchronous pipeline runner — called from a worker thread.

    `extra_prompt` (if non-empty) is appended to the bag's custom_prompt for
    this one regen only — does NOT mutate the BagQueue row.
    """
    from ..models import PendingApproval
    from ...extensions import db
    from .pinterest_client import get_random_pin
    from .ai_generator import generate_image
    from .cloudinary_svc import upload_generated_image

    with _flask_app.app_context():
        old = db.session.get(PendingApproval, old_approval_id)
        if old is None or old.bag is None:
            return None
        bag = old.bag
        new_regen_count = old.regeneration_count + 1
        bag_queue_id = bag.id
        bag_image_path = bag.image_path
        custom_prompt = bag.custom_prompt or ""
        if extra_prompt:
            custom_prompt = (custom_prompt + "\n" + extra_prompt).strip() if custom_prompt else extra_prompt
        tenant_id = bag.tenant_id

    pin_result = get_random_pin(
        board_url=os.environ.get("PINTEREST_BOARD_URL", ""),
        tenant_id=tenant_id,
    )
    if not pin_result["success"]:
        raise RuntimeError(f"Pinterest: {pin_result['error']}")

    gen = generate_image(
        bag_image_path=bag_image_path,
        reference_image_url=pin_result["image_url"],
        custom_prompt=custom_prompt,
        tenant_id=tenant_id,
    )
    if not gen["success"]:
        raise RuntimeError(f"kie.ai: {gen['error']}")

    final_url = gen["generated_url"]
    if gen.get("local_path"):
        up = upload_generated_image(gen, tenant_id=tenant_id)
        if up.get("success"):
            final_url = up["public_url"]

    with _flask_app.app_context():
        new_row = PendingApproval(
            tenant_id=tenant_id,
            bag_queue_id=bag_queue_id,
            reference_pin_id=pin_result.get("pin_id"),
            reference_url=pin_result["image_url"],
            generated_image_url=final_url,
            prompt_used=gen.get("prompt_used", ""),
            regeneration_count=new_regen_count,
            status="pending",
        )
        db.session.add(new_row)
        db.session.commit()
        return new_row.id


async def _restore_keyboard_with_error(
    old_approval_id: int, old_caption: str, error: str
) -> None:
    """After a failed regeneration, restore the keyboard so the admin can retry."""
    snapshot = await asyncio.to_thread(_load_approval_snapshot, old_approval_id)
    if snapshot is None or not snapshot.get("telegram_message_id"):
        logger.error("Can't restore keyboard — no telegram_message_id")
        return

    keyboard = _build_keyboard(old_approval_id, snapshot["regeneration_count"])
    new_caption = (
        (old_caption.strip() + "\n\n" if old_caption else "")
        + f"❌ Regeneration failed: {_truncate(error, 200)}"
    )

    await _with_retry(lambda: _application.bot.edit_message_caption(
        chat_id=_TELEGRAM_CHAT_ID,
        message_id=int(snapshot["telegram_message_id"]),
        caption=new_caption,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    ))


# ---------------------------------------------------------------------------
# DB helpers (sync, run via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _load_approval_snapshot(approval_id: int) -> Optional[dict]:
    from ..models import PendingApproval
    from ...extensions import db

    with _flask_app.app_context():
        a = db.session.get(PendingApproval, approval_id)
        if a is None or a.bag is None:
            return None
        return {
            "id": a.id,
            "bag_name": a.bag.bag_name,
            "bag_queue_id": a.bag.id,
            "generated_image_url": a.generated_image_url,
            "reference_url": a.reference_url,
            "regeneration_count": a.regeneration_count,
            "telegram_message_id": a.telegram_message_id,
            "status": a.status,
            "fb_caption": a.fb_caption,
            "ig_caption": a.ig_caption,
        }


def _find_approval_by_message_id(message_id: str) -> Optional[int]:
    from ..models import PendingApproval
    from ...extensions import db

    with _flask_app.app_context():
        a = (
            db.session.query(PendingApproval)
            .filter_by(telegram_message_id=message_id)
            .first()
        )
        return a.id if a else None


def _set_captions_for_approval(approval_id: int, caption: str) -> bool:
    """Save the same caption text to both FB and IG fields."""
    from ..models import PendingApproval
    from ...extensions import db

    with _flask_app.app_context():
        a = db.session.get(PendingApproval, approval_id)
        if a is None:
            return False
        a.fb_caption = caption
        a.ig_caption = caption
        db.session.commit()
        return True


def _save_message_id(approval_id: int, message_id: str) -> None:
    from ..models import PendingApproval
    from ...extensions import db

    with _flask_app.app_context():
        a = db.session.get(PendingApproval, approval_id)
        if a is not None:
            a.telegram_message_id = message_id
            db.session.commit()


def _update_status(approval_id: int, status: str) -> bool:
    from ..models import PendingApproval
    from ...extensions import db

    with _flask_app.app_context():
        a = db.session.get(PendingApproval, approval_id)
        if a is None:
            return False
        a.status = status
        a.responded_at = datetime.now(timezone.utc)
        db.session.commit()
        return True


# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------

def _build_caption(snapshot: dict) -> str:
    lines = [
        "*🎨 New AI photo ready*",
        "",
        f"📦 *Bag:* {_escape_md(snapshot['bag_name'])}",
        f"🆔 #{snapshot['bag_queue_id']} · 🔄 {snapshot['regeneration_count']}/{MAX_REGENERATIONS}",
    ]

    # Show the active caption (admin's edits override AI-drafted ones; we
    # display whichever has priority — fb_caption first since it's GE).
    active = snapshot.get("fb_caption") or snapshot.get("ig_caption")
    if active:
        # Telegram captions cap at 1024 chars total. Truncate the preview if
        # the active caption is unusually long so the metadata stays visible.
        preview = active if len(active) <= 600 else active[:597] + "..."
        lines.append("")
        lines.append("📝 " + _escape_md(preview))

    if snapshot.get("reference_url"):
        lines.append("")
        lines.append(f"🎯 [Reference]({snapshot['reference_url']})")

    return "\n".join(lines)


def _build_keyboard(approval_id: int, regen_count: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{approval_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{approval_id}"),
        ],
    ]
    if regen_count >= MAX_REGENERATIONS:
        buttons.append([
            InlineKeyboardButton("🔄 Max regens reached", callback_data="disabled"),
        ])
    else:
        buttons.append([
            InlineKeyboardButton(
                f"🔄 Regen ({regen_count}/{MAX_REGENERATIONS})",
                callback_data=f"regen_{approval_id}",
            ),
            InlineKeyboardButton(
                "🎨 Regen + prompt",
                callback_data=f"promptregen_{approval_id}",
            ),
        ])
    buttons.append([
        InlineKeyboardButton(
            "✏️ Edit caption",
            callback_data=f"editcaption_{approval_id}",
        ),
        InlineKeyboardButton(
            "🚀 Post now",
            callback_data=f"postnow_{approval_id}",
        ),
    ])
    return InlineKeyboardMarkup(buttons)


def _append_status(caption: Optional[str], status_line: str) -> str:
    base = (caption or "").strip()
    return f"{base}\n\n{status_line} at {_ts_now()}"


def _ts_now() -> str:
    """Local-time stamp using the scheduler timezone (defaults to Asia/Tbilisi)."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover
        from backports.zoneinfo import ZoneInfo
    tz_name = os.environ.get("SCHEDULER_TIMEZONE", "Asia/Tbilisi")
    return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M %Z")


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len] + "..."


def _escape_md(text: str) -> str:
    # Minimal Markdown v1 escape — only the characters that break captions
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text


# ---------------------------------------------------------------------------
# Cloudinary thumbnail — keep Telegram delivery small
# ---------------------------------------------------------------------------

def _cloudinary_thumb(url: str, width: int = 1600) -> str:
    """Insert a Cloudinary delivery transformation that yields a small file.

    `c_limit,w_N` caps width, `q_auto,f_auto` lets Cloudinary pick the most
    efficient codec/quality for the requesting client. A 6 MB PNG becomes a
    ~250 KB WebP/JPEG that Telegram uploads in well under a second. Other
    URLs are returned unchanged so the helper is safe on third-party hosts.
    """
    if "res.cloudinary.com" not in url or "/upload/" not in url:
        return url
    return url.replace(
        "/upload/",
        f"/upload/c_limit,w_{width},q_auto,f_auto/",
        1,
    )


# ---------------------------------------------------------------------------
# Image fetcher — work around Telegram's URL-fetch quirks
# ---------------------------------------------------------------------------

# Max bytes we will buffer in memory before falling back to URL.
# Telegram's sendPhoto bytes upload limit is 10 MB; we cap slightly lower.
_MAX_PHOTO_BYTES = 9 * 1024 * 1024


async def _fetch_image_bytes(url: str) -> Optional[bytes]:
    """Download an image to bytes (best-effort).

    Returning bytes lets us upload via multipart, which avoids Telegram's
    server-side URL fetcher that often chokes on >5 MB Cloudinary images
    with "Wrong type of the web page content". On failure (oversize,
    network error, non-image content) we return None and the caller falls
    back to passing the raw URL string.
    """
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning("Image download HTTP %d for %s", resp.status_code, url[:80])
                return None
            data = resp.content
            if len(data) > _MAX_PHOTO_BYTES:
                logger.warning("Image too large for bytes upload (%d B) — falling back to URL",
                               len(data))
                return None
            return data
    except Exception as exc:
        logger.warning("Image download failed for %s: %s", url[:80], exc)
        return None


# ---------------------------------------------------------------------------
# Telegram API retry wrapper
# ---------------------------------------------------------------------------

async def _with_retry(
    coro_factory: Callable[[], Awaitable[Any]],
    retries: int = 3,
) -> Any:
    """Run a Telegram coroutine with exponential backoff on transient errors.

    Returns None on permanent failure (caller treats None as failure).
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            return await coro_factory()
        except RetryAfter as exc:
            wait = float(getattr(exc, "retry_after", 1)) + 1
            logger.warning("Telegram rate-limited — waiting %.1fs", wait)
            await asyncio.sleep(wait)
            last_exc = exc
        except BadRequest as exc:
            # 4xx — Telegram rejected the request shape (bad URL, photo too
            # large, bad chat id…). Retrying won't help.
            logger.error("Telegram BadRequest (non-retryable): %s", exc)
            return None
        except (NetworkError, TimedOut) as exc:
            wait = 2 ** attempt
            logger.warning(
                "Telegram network error (attempt %d/%d): %s — retry in %ds",
                attempt, retries, exc, wait,
            )
            await asyncio.sleep(wait)
            last_exc = exc
        except TelegramError as exc:
            logger.error("Telegram error (non-retryable): %s", exc)
            return None
    logger.error("Telegram retry exhausted after %d attempts: %s", retries, last_exc)
    return None
