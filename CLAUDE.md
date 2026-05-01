# Project: pinterest-agent

## Overview
**AI Bag Content Agent** — ჩანთების სარეკლამო ფოტოების ავტომატური გენერაცია და სოციალურ ქსელებში დაპოსტვა.

Standalone Flask application with own admin panel.
**Migration-ready**: `ai_content/` blueprint can be moved to another admin panel as a separate tab with minimal code changes.

- **Language:** Python 3.11+
- **Framework:** Flask (Blueprint-based)
- **Database:** SQLite (dev) → PostgreSQL (production)
- **Package Manager:** pip + venv
- **Deployment:** Railway
- **Approach:** CODE

### External Services
| Service | Purpose |
|---------|---------|
| Pinterest API v5 | Reference photos (App ID: 1565782) |
| kie.ai Nano Banana Pro | AI image generation |
| Cloudinary | Image hosting (public HTTPS URL) |
| Discord Bot (discord.py) | Human approval workflow |
| Meta Graph API | Facebook Page + Instagram posting |

## Workflow

### 09:00 (Asia/Tbilisi) — Morning Generate Job
1. FIFO queue-დან შემდეგი `pending` ჩანთის ფოტო
2. Pinterest API v5 → random reference photo from board
3. kie.ai: generate(bag_photo + reference_url + global_prompt_template)
4. Cloudinary → public HTTPS URL
5. Discord notification with ✅ Approve / ❌ Reject / 🔄 Regenerate buttons

### During the Day — Human Review
- ✅ **Approve** → `approved` status
- ❌ **Reject** → `rejected`, bag returns to FIFO queue
- 🔄 **Regenerate** → re-run generation (max 3 attempts, then auto-reject)

### 20:00 (Asia/Tbilisi) — Evening Post Job
- All `approved` photos → Facebook Page + Instagram Business (Meta Graph API)
- If not reviewed by 20:00 → `awaiting` status → posts at next 20:00 after approval

## Project Structure (Blueprint-based, migration-ready)

```
pinterest-agent/
├── ai_bag_agent/               ← main package
│   ├── __init__.py             # app factory
│   ├── config.py               # env-based configuration
│   ├── extensions.py           # Flask extensions (db, login, scheduler)
│   ├── auth/                   ← Blueprint: login/logout/auth
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   └── templates/auth/
│   └── ai_content/             ← ⭐ Main blueprint (migration unit)
│       ├── __init__.py
│       ├── routes.py           # Admin UI routes
│       ├── models.py           # All SQLAlchemy models
│       ├── services/           # External API clients
│       │   ├── __init__.py
│       │   ├── ai_generator.py     # kie.ai
│       │   ├── cloudinary_svc.py   # Cloudinary
│       │   ├── pinterest_client.py # Pinterest API v5
│       │   ├── discord_svc.py      # Discord bot
│       │   └── meta_poster.py      # FB + IG
│       ├── jobs/               # APScheduler job functions
│       │   ├── __init__.py
│       │   ├── morning_job.py  # 09:00 generate
│       │   └── evening_job.py  # 20:00 post
│       └── templates/ai_content/   # Admin panel Jinja2 templates
├── migrations/                 # Alembic migrations
├── tests/
│   ├── unit/
│   └── integration/
├── docs/
│   └── decisions/
├── .env.example
├── requirements.txt
├── PLAN.md                     # Full build plan (Stages 0–14)
├── Procfile                    # Railway: web + worker
├── railway.toml
└── wsgi.py                     # Gunicorn entry point
```

## Database Schema (all tables have tenant_id for future multi-tenancy)

### users
`id, username, password_hash, role, created_at`

### bag_queue
`id, tenant_id (default="default"), bag_name, image_path, custom_prompt, status (pending/processing/done/rejected), created_at, processed_at`

### pending_approvals
`id, tenant_id, bag_queue_id, reference_pin_id, reference_url, generated_image_url, prompt_used, discord_message_id, status (pending/approved/rejected/awaiting), regeneration_count (max 3), caption, scheduled_post_date, created_at, responded_at`

### post_log
`id, tenant_id, approval_id, fb_post_id, ig_post_id, posted_at, caption, error`

### recent_pin_cache
`pin_id, tenant_id, used_at` (variety control — avoids reusing recent reference photos)

### settings
`key, tenant_id, value, updated_at` (prompt template, API tokens, configs)

## Build Stages (see PLAN.md for details)

| Stage | Description |
|-------|-------------|
| 0 | Project skeleton + .env + DB migrations + auth |
| 1 | kie.ai Generator (services/ai_generator.py) |
| 2 | Cloudinary Uploader |
| 3 | Pinterest Client (API v5) |
| 4 | Admin UI — Bag Queue management |
| 5 | Discord Bot (approval workflow) |
| 6 | Social Poster (FB + IG) |
| 7 | Orchestrator — Generate Job |
| 8 | Orchestrator — Post Job |
| 9 | Regeneration Flow |
| 10 | Scheduler (09:00 + 20:00 cron) |
| 11 | Settings UI (prompt template + credentials) |
| 12 | Admin UI — Approvals history + Posts log |
| 13 | Production polish (logging, error handling, retries) |
| 14 | Railway deployment |

## How Claude Should Work With the User

- User writes prompts, not code — explain everything in plain language (Georgian by default)
- Before making changes: say what you'll change and why
- After changes: explain how to verify
- If prompt is vague: interpret charitably, show result, ask for refinement
- Change ONLY what was asked — no uninstructed refactoring
- If changing 4+ files: list them and get confirmation first
- Never show raw error messages without plain-language explanation
- **Stage workflow**: at end of each Stage, tell user: (1) test to run, (2) accounts to create before next Stage

## Data Safety

- Auto-checkpoint before any multi-file change
- Never delete files without asking
- If user says "undo" / "გააუქმე" → git restore

## Security Rules

- Secrets ONLY in .env — never in code
- All user inputs validated (Flask-WTF)
- SQLAlchemy ORM — no raw SQL concatenation
- Discord interactions verified with signature
- Production: HTTPS only, security headers enabled
- (full rules in .claude/rules/security.md)

## Testing

- `pytest tests/ -v` before every commit
- After every visual change: Playwright screenshot
- Each Stage has a DONE test defined in PLAN.md
- New endpoint: minimum 1 test (happy path + 1 error case)
- (full rules in .claude/rules/testing.md)

## Code Quality

- `black` + `flake8` + `isort` — all must pass
- Functions max 50 lines; files max 400 lines
- Type hints on all function signatures
- Structured JSON logging (no print() in production)
- Conventional commits: feat:, fix:, docs:, test:, refactor:, chore:

## Important Rules

1. **Multi-tenant ready:** All models have `tenant_id` (default="default")
2. **Migration-ready:** `ai_content` is a self-contained Blueprint
3. **Secrets:** Never in code — .env or DB encrypted
4. **DRY:** Business logic in service layer, not in routes
5. **Type hints, docstrings, structured logging** everywhere
6. **If unclear → ask** before writing code
7. **Discovery first → PLAN.md → user confirmation → then code**

## Available Resources

Pinterest:
- App ID: 1565782
- Trial Access Token: 24h validity (manually refresh until trial approved)
- Board: https://www.pinterest.com/tissugeorgia/laptop-bags/

Other accounts (kie.ai, Cloudinary, Discord, Meta) → created per Stage as needed.

## Memory & Context

- Session end: create .claude/handoff-YYYY-MM-DD.md
- Architectural decisions: save to docs/decisions/
- (full rules in .claude/rules/memory.md)
