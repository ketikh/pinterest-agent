# 002: Discord Bot — Background Thread (same process)

## Date
2026-05-01

## Status
accepted

## Context
The Discord bot needs to run continuously to receive button interaction callbacks (✅/❌/🔄). It needs to read and write to the same database as the Flask web app.

## Options Considered
1. **Background thread** — run `discord.py` in a thread within the Flask process
2. **Separate Railway worker** — two services: web + worker

## Decision
Run Discord bot as a background thread within the Flask process.

## Reasoning
- One Railway service = simpler + cheaper
- Shared SQLAlchemy session — no IPC or message queue needed
- The bot has low event volume (only button clicks from one user)
- Implementation: `asyncio.new_event_loop()` in a `threading.Thread`, Flask app context pushed manually

## Consequences
- Need to push Flask app context manually in the Discord coroutines
- If the Flask process crashes, the bot stops too (acceptable — Railway auto-restarts)
- For future scaling (multiple users), consider migrating to Celery + Redis worker
