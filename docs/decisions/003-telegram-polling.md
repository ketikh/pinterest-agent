# 003: Telegram Bot — Polling Mode (Background Thread)

## Date
2026-05-11

## Status
accepted

## Context

Stage 5 integrates a Telegram bot into the Flask app for the approval
workflow. Telegram offers two ways to receive updates:

1. **Long polling** — the bot calls `getUpdates` repeatedly; no public URL
   needed.
2. **Webhook** — Telegram POSTs updates to a public HTTPS endpoint we expose.

The bot also needs to run continuously while the Flask web app is running, so
it must coexist with Gunicorn / `flask run` without blocking them.

## Decision

Run the Telegram bot in **polling mode** during development (Stages 5–13),
inside a dedicated background **daemon thread** that owns its own asyncio
event loop. Postpone the switch to webhook mode until Stage 14 (Railway
deployment), where a public HTTPS URL is naturally available.

Concretely:

- `services/telegram_bot.py` builds a singleton `Application` (via
  `Application.builder().token(...).build()`)
- `start_bot_in_thread()` is called once from `create_app()` (skipped when
  `app.testing` is true)
- The thread function creates a fresh `asyncio.new_event_loop()`, sets it as
  the current loop, then runs `initialize()` → `start()` →
  `updater.start_polling()` → `loop.run_forever()`
- Thread is `daemon=True` so it dies with the Flask process

## Reasoning

- ✅ **Local dev simplicity**: no `ngrok`, no public URL, no TLS cert juggling
- ✅ **One Railway service** is enough — the bot lives in the same process as
  the web app and APScheduler (ADR 001 design choice)
- ✅ **Shared DB session**: bot callbacks can `db.session` directly against
  the same SQLAlchemy engine as the web routes (with a manual app-context
  push inside coroutines)
- ✅ **15-second callback timeout** gives us headroom to acknowledge button
  presses before any heavy work
- ⚠️ Polling has ~1–3 s end-to-end latency for button clicks. Acceptable for
  a manual-approval workflow where the admin reviews on their own schedule.
- ⚠️ Polling uses minimal but constant resources (one open long-poll HTTPS
  connection). Negligible on Railway free tier.
- ⚠️ Only **one** `Application` instance can poll a given bot token at a
  time. If we ever scale to multiple Flask workers, we MUST switch to
  webhooks (only one worker would receive callbacks, others would 409).

## Consequences

### Now (Stages 5–13)
- Develop and test locally with no public infra
- Run Flask with `flask run` or `gunicorn --workers 1` only
- Bot thread starts automatically with `create_app()`

### Later (Stage 14)
- Migrate to webhook mode: `bot.set_webhook(url=..., secret_token=...)`
- Add `/api/telegram/webhook` Flask route that verifies the
  `X-Telegram-Bot-Api-Secret-Token` header and forwards the JSON update to
  `Application.process_update()`
- Drop the background polling thread in production config
- Keep polling available for local development via an env flag
  (`TELEGRAM_MODE=polling|webhook`)

## Alternatives Considered

- **Separate worker process (Celery / RQ / Procfile `worker:`)** — rejected
  for now because it doubles Railway costs and complicates DB session
  management for a single-user approval flow. Will be reconsidered if/when
  Stage 6 (Meta posting) needs heavy background jobs.
- **Webhook from day one** — rejected because it forces ngrok or equivalent
  for local development and adds setup friction for the admin user.
