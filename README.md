# pinterest-agent — AI Bag Content Agent

> ჩანთების სარეკლამო ფოტოების ავტომატური გენერაცია და სოციალურ ქსელებში დაპოსტვა

## What it does

Every day at **09:00 (Tbilisi)**:
1. Takes the next bag photo from the queue
2. Gets a reference photo from Pinterest
3. Generates a promotional image with kie.ai
4. Sends to Discord for your approval (✅ / ❌ / 🔄)

Every day at **20:00 (Tbilisi)**:
- Posts all approved photos to Facebook Page + Instagram Business

## Tech Stack

- Python 3.11 + Flask (Blueprint-based)
- SQLite (dev) / PostgreSQL (prod via Railway)
- APScheduler (09:00 + 20:00 cron jobs)
- discord.py (approval workflow)
- Pinterest API v5, kie.ai, Cloudinary, Meta Graph API

## Quick Start

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your credentials
flask db upgrade
flask run
```

Open: http://localhost:5000/auth/login

## Build Stages

See [PLAN.md](PLAN.md) for the full 14-stage build plan.

## Working with Claude

See [docs/how-to-work-with-claude.md](docs/how-to-work-with-claude.md) for prompt examples in Georgian.

## Architecture

See [docs/architecture.md](docs/architecture.md) for system diagram and Blueprint structure.
