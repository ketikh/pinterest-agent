# Architecture Overview

## System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Railway (one service)                      │
│                                                               │
│  ┌──────────────────┐   ┌─────────────────────────────────┐  │
│  │   Flask Web App  │   │        Background Threads        │  │
│  │                  │   │                                  │  │
│  │  /auth/*         │   │  APScheduler                     │  │
│  │  /admin/*        │   │  ├── morning_job (09:00 TBS)     │  │
│  │  (no public      │   │  └── evening_job (20:00 TBS)     │  │
│  │   bot endpoint   │   │                                  │  │
│  │   — polling)     │   │  python-telegram-bot             │  │
│  │  SQLAlchemy ORM  │   │  └── callback_query handler      │  │
│           │             └──────────────┬────────────────────┘  │
│           └──────────┬─────────────────┘                      │
│                      ▼                                         │
│              SQLite (dev) / PostgreSQL (prod)                  │
└─────────────────────────────────────────────────────────────┘
                           │
          ┌────────────────┼─────────────────┐
          ▼                ▼                 ▼
    Pinterest API     kie.ai API       Cloudinary
    (reference         (image           (image
     photos)           generation)      hosting)
          
          ┌────────────────┬─────────────────┐
          ▼                ▼                 ▼
      Telegram         Facebook          Instagram
      (approval)        Page             Business
                    (Meta Graph API v21.0)
```

## Daily Workflow

```
09:00 TBS
  │
  ├── Get next pending bag (FIFO from bag_queue)
  ├── Get random reference pin (Pinterest API, avoid recent repeats)
  ├── Generate image (kie.ai: bag + reference + prompt)
  ├── Upload to Cloudinary → public HTTPS URL
  └── Send to Telegram → ✅ / ❌ / 🔄 inline buttons
  
User reviews during the day:
  ✅ Approve  → pending_approvals.status = "approved"
  ❌ Reject   → status = "rejected", bag back in queue
  🔄 Regen   → re-run generation (max 3x, then auto-reject)

20:00 TBS
  │
  ├── Get all "approved" for today
  ├── POST to Facebook Page (Graph API)
  ├── POST to Instagram Business (Graph API)
  └── Log to post_log (fb_post_id, ig_post_id, caption, timestamp)
  
If not reviewed by 20:00 → status = "awaiting"
  Next time user approves → posts at next 20:00
```

## Blueprint Structure

```
ai_bag_agent/
├── __init__.py          # create_app() factory
├── config.py            # Config, DevelopmentConfig, ProductionConfig
├── extensions.py        # db, login_manager, scheduler (initialized here)
│
├── auth/                # Blueprint: /auth
│   ├── __init__.py
│   ├── routes.py        # /login, /logout
│   └── templates/auth/
│       └── login.html
│
└── ai_content/          # Blueprint: /admin  ← migration unit
    ├── __init__.py
    ├── routes.py        # /admin/* routes
    ├── models.py        # All DB models
    ├── services/        # External API clients
    │   ├── ai_generator.py
    │   ├── cloudinary_svc.py
    │   ├── pinterest_client.py
    │   ├── telegram_bot.py
    │   └── meta_poster.py
    ├── jobs/            # APScheduler job functions
    │   ├── morning_job.py
    │   └── evening_job.py
    └── templates/ai_content/
        ├── base.html
        ├── dashboard.html
        ├── queue.html
        ├── approvals.html
        ├── posts.html
        └── settings.html
```

## Database Tables

| Table | Purpose |
|-------|---------|
| users | Admin authentication |
| bag_queue | Uploaded bag photos (FIFO work queue) |
| pending_approvals | Generated images awaiting Telegram review |
| post_log | History of social media posts |
| recent_pin_cache | Recently used Pinterest pins (variety control) |
| settings | Configurable values (prompt template, API creds) |

All tables have `tenant_id` column (default="default") for future multi-tenancy.
