# 002: Telegram instead of Discord for Approval Workflow

## Date
2026-05-11

## Status
accepted

## Context

Stage 5 originally specified Discord (discord.py) for the human approval workflow
(✅ Approve / ❌ Reject / 🔄 Regenerate). Before any Discord-specific code was
written, the user requested switching to Telegram.

## Decision

Use **Telegram** (`python-telegram-bot` v21.x, async) as the approval channel
instead of Discord.

## Reasoning

- Simpler setup: Telegram bots are created via @BotFather in under a minute;
  no Discord server, intent flags, or application registration ceremony.
- Better mobile notifications: Telegram delivers push notifications faster and
  more reliably to the admin's phone than Discord.
- Lighter client app: Telegram's mobile UX is friendlier for a 1-person admin
  workflow (this project is single-user approval, not a team channel).
- `InlineKeyboardMarkup` provides the exact same UX as Discord buttons —
  feature parity is preserved.

## Consequences

- ✅ Faster onboarding for the admin (one chat with @BotFather)
- ✅ No public webhook URL needed during development (polling mode)
- ✅ Callback timeout is 15 seconds (vs. Discord's 3 seconds) — gives us more
  breathing room before having to background-task the regen pipeline
- ⚠️ `python-telegram-bot` is async-only from v20+; we run its asyncio loop in
  a dedicated background thread inside the Flask process (see ADR 003)
- ⚠️ DB column rename: `pending_approvals.discord_message_id` →
  `telegram_message_id` (clean re-init of initial migration, since no rows exist)
- ⚠️ Webhook signature verification (Discord's Ed25519) is replaced by
  Telegram's `secret_token` header check, deferred to Stage 14

## Migration

This decision was made before any Discord integration code was written.
The refactor scope was: env vars (`DISCORD_*` → `TELEGRAM_*`), the
`pending_approvals` model column, doc references, and the initial Alembic
migration. No production data existed to migrate.
