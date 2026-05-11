# PLAN.md — AI Bag Content Agent Build Plan

## Progress

- [x] Phase 1: Infrastructure + setup ✅ (2026-05-01)
- [x] Stage 0: Project skeleton + DB + auth ✅ (2026-05-01)
- [x] Stage 1: kie.ai Generator ✅ (2026-05-01)
- [x] Stage 2: Cloudinary Uploader ✅ (2026-05-06)
- [x] Stage 3: Pinterest Client (API v5) ✅ (2026-05-06)
- [ ] Stage 3.5: Pinterest OAuth flow ⏸️ BLOCKED — awaiting Pinterest Trial approval
- [x] Stage 4: Admin UI — Bag Queue management ✅ (2026-05-06)
- [~] Stage 5: Telegram Bot ✅ partial (send/approve/reject live-tested; regen blocked by Pinterest)
- [ ] Stage 6: Social Poster (FB + IG)
- [ ] Stage 7: Orchestrator — Generate Job
- [ ] Stage 8: Orchestrator — Post Job
- [ ] Stage 9: Regeneration Flow
- [ ] Stage 10: Scheduler (09:00 + 20:00 cron)
- [ ] Stage 11: Settings UI
- [ ] Stage 12: Approvals history + Posts log
- [ ] Stage 13: Production polish
- [ ] Stage 14: Railway deployment

---

## Stage 0: Project Skeleton + DB + Auth ✅

**Goal:** Running Flask app, DB migrations, admin login

**Key files:**
- `ai_bag_agent/__init__.py` — app factory (create_app)
- `ai_bag_agent/config.py` — Config classes (Dev/Test/Prod)
- `ai_bag_agent/extensions.py` — db, login_manager, migrate, csrf
- `ai_bag_agent/auth/` — login/logout blueprint
- `ai_bag_agent/ai_content/models.py` — all 6 DB models
- `ai_bag_agent/ai_content/routes.py` — dashboard (skeleton)
- `wsgi.py`, `Procfile`, `railway.toml`

**DONE test:**
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill FLASK_SECRET_KEY
flask --app wsgi db upgrade
flask --app wsgi auth create-admin  # set username + password
flask --app wsgi run
# Open http://localhost:5000/auth/login
# Login → see dashboard with 0 counts
```

**External accounts needed before Stage 1:** None

---

## Stage 1: kie.ai Generator

**Goal:** Generate promotional image from bag photo + reference + prompt

**File:** `ai_bag_agent/ai_content/services/ai_generator.py`

**Functions:**
- `generate_image(bag_image_url, reference_url, prompt_template, tenant_id) → str`
  - Calls kie.ai Nano Banana Pro API
  - Returns generated image URL
  - Retries 3x with 10s backoff on failure
  - Timeout: 90s (generation can be slow)

**DONE test:** `pytest tests/unit/test_ai_generator.py -v`

**Accounts needed before Stage 2:** kie.ai account → get API key → put in .env as KIEAI_API_KEY

---

## Stage 2: Cloudinary Uploader

**Goal:** Upload images to Cloudinary and get public HTTPS URL

**File:** `ai_bag_agent/ai_content/services/cloudinary_svc.py`

**Functions:**
- `upload_from_url(url, public_id_prefix) → str` — upload from URL
- `upload_file(file_path, public_id_prefix) → str` — upload local file
- Both return public Cloudinary URL
- Organized in folder: `pinterest-agent/{tenant_id}/`

**DONE test:** upload test image → URL accessible in browser

**Accounts needed:** Cloudinary account (free tier) → CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET in .env

---

## Stage 3: Pinterest Client (API v5)

**Goal:** Get random reference photo from Pinterest board (avoiding recent repeats)

**File:** `ai_bag_agent/ai_content/services/pinterest_client.py`

**Functions:**
- `get_random_reference_pin(board_id, tenant_id) → PinData` — FIFO-avoids recent pins
- `PinData` dataclass: pin_id, image_url, title

**Notes:**
- Trial access token expires every 24h — must refresh manually
- `recent_pin_cache` table stores last 7 days of used pins
- Board: https://www.pinterest.com/tissugeorgia/laptop-bags/
- App ID: 1565782

**DONE test:** real API call → returns pin URL → stored in recent_pin_cache

**Accounts:** Pinterest App already set up. Refresh token manually when needed (until app approved).

---

## Stage 3.5: Pinterest OAuth Flow (POST-TRIAL-APPROVAL)

**Status:** ⏸️ BLOCKED — waiting for Pinterest Trial approval (1–3 days typical).

**Why:** The current implementation uses a **"Product Limited" 24h test token** that
must be regenerated manually every day. Once Pinterest approves the Trial, an
**App Secret** becomes available and we can switch to the proper OAuth flow:

- **30-day access_token** — auto-renewable via refresh_token
- **1-year refresh_token** — manual browser login needed only once per year
- Trial Access tier is sufficient (Standard Access not required for our use case)

**File:** `ai_bag_agent/ai_content/services/pinterest_oauth.py` (NEW)

**Functions:**
```python
def generate_authorization_url(tenant_id: str) -> str:
    """OAuth URL → user opens in browser → Pinterest login → 'Allow' → redirect."""

def exchange_code_for_tokens(authorization_code: str) -> dict:
    """Exchange auth code for access_token + refresh_token. Persists to DB.
    Returns: {access_token, refresh_token, expires_in}"""

def refresh_access_token(refresh_token: str) -> dict:
    """Auto-renew access_token using refresh_token. Returns new pair."""

def get_valid_access_token(tenant_id: str = "default") -> str:
    """Main public API used by pinterest_client.py:
    1. Read access_token + expiry from DB
    2. If expires_at > now + 1 day → return current
    3. Else: refresh_access_token() → store new → return"""
```

**DB schema updates** (added to `settings` table — keyed values, not new columns):
- `pinterest_access_token` (TEXT)
- `pinterest_refresh_token` (TEXT)
- `pinterest_token_expires_at` (TIMESTAMP, ISO format)
- `pinterest_oauth_state` (TEXT, temporary during OAuth handshake — CSRF protection)

**CLI helper:** `scripts/pinterest_login.py`
- Opens browser with authorization URL
- Spins up a localhost Flask endpoint for the callback
- Captures `code` from query string, exchanges for tokens, stores in DB
- Run once per year (refresh_token validity)

**Integration:** `pinterest_client.py._get_token()` must call
`pinterest_oauth.get_valid_access_token(tenant_id)` instead of reading the static
`PINTEREST_ACCESS_TOKEN` from environment.

**Env vars needed (after Trial approval):**
- `PINTEREST_APP_ID=1565782` (already have)
- `PINTEREST_APP_SECRET=` (granted by Pinterest after Trial approval)
- `PINTEREST_REDIRECT_URI=http://localhost:5000/auth/pinterest/callback` (dev)
- Production: `https://yourapp.railway.app/auth/pinterest/callback`

**DONE test:**
1. Run `python scripts/pinterest_login.py` → browser opens → log in → "Allow"
2. Script reports "✅ Tokens stored — expires in 30 days, refresh in 1 year"
3. Restart Flask app → `pinterest_client.get_random_pin()` works without
   manually setting `PINTEREST_ACCESS_TOKEN` in `.env`
4. Set `pinterest_token_expires_at` in DB to "yesterday" → call
   `get_valid_access_token()` → verify it auto-refreshed and updated DB

**Accounts needed:** App Secret from Pinterest Developer Portal (post-approval).

---

## Stage 4: Admin UI — Bag Queue Management

**Goal:** Upload bag photos, view FIFO queue, manage statuses

**Routes added to** `ai_bag_agent/ai_content/routes.py`:
- `GET /admin/queue` — view queue with status badges
- `POST /admin/queue/upload` — upload bag photo + optional custom_prompt
- `POST /admin/queue/<id>/delete` — remove from queue

**Templates:**
- `ai_content/queue.html` — table with status colors, upload form

**DONE test:** upload 2 photos → see them in queue in order → status shows "pending"

**Accounts:** None (uses Cloudinary from Stage 2 for image storage)

---

## Stage 5: Telegram Bot

**Goal:** Send generated image to Telegram, handle ✅/❌/🔄 inline-keyboard button clicks

**File:** `ai_bag_agent/ai_content/services/telegram_bot.py`

**Library:** `python-telegram-bot` v21+ (async API)

**How it works:**
- Runs as background asyncio task in a dedicated thread (started at Flask app startup)
- Strategy: **polling** (long polling, no public URL needed)
- Sends `send_photo` message with: generated image, bag info caption, `InlineKeyboardMarkup` (3 buttons)
- Buttons: ✅ Approve / ❌ Reject / 🔄 Regenerate (count/3)
- On button click (`CallbackQueryHandler`): updates `pending_approvals.status` in DB, edits message

**DONE test:** run bot → call `send_approval_request()` manually → Telegram message appears in chat → click ✅ → DB status = "approved", message keyboard removed

**Accounts needed:** Telegram (via @BotFather)
1. Chat with @BotFather → `/newbot` → copy token → `TELEGRAM_BOT_TOKEN`
2. Start chat with your bot → run helper to get your chat ID → `TELEGRAM_CHAT_ID`
3. (Optional) `/setcommands` for `/start`, `/help`

---

## Stage 6: Social Poster (Meta Graph API)

**Goal:** Post approved images to Facebook Page + Instagram Business

**File:** `ai_bag_agent/ai_content/services/meta_poster.py`

**Functions:**
- `post_to_facebook(image_url, caption, page_id) → str` — returns fb_post_id
- `post_to_instagram(image_url, caption, ig_account_id) → str` — returns ig_post_id
- Uses Meta Graph API v21.0

**DONE test:** post test image to sandbox FB page + IG

**Accounts needed:** Meta Developer account
1. Create App → add Facebook Login + Instagram Basic Display
2. Get Page Access Token (long-lived)
3. Get Instagram Business Account ID
→ META_ACCESS_TOKEN, META_PAGE_ID, META_INSTAGRAM_ACCOUNT_ID in .env

---

## Stage 7: Orchestrator — Morning Generate Job

**Goal:** Full pipeline: queue → Pinterest → kie.ai → Cloudinary → Telegram

**File:** `ai_bag_agent/ai_content/jobs/morning_job.py`

**Function:** `run_morning_generate(app)` — full pipeline
1. Get next `pending` BagQueue item (lowest sort_order + oldest created_at)
2. Get random reference pin (Stage 3, avoids recent)
3. Generate image (Stage 1)
4. Upload generated to Cloudinary (Stage 2)
5. Send to Telegram (Stage 5)
6. Create PendingApproval record

**DONE test:** call `run_morning_generate()` directly → Telegram message appears, DB record created

---

## Stage 8: Orchestrator — Evening Post Job

**Goal:** Post all approved images at 20:00

**File:** `ai_bag_agent/ai_content/jobs/evening_job.py`

**Function:** `run_evening_post(app)` — posts approved items
1. Query all `approved` PendingApprovals not yet in PostLog
2. For each: post to FB + IG (Stage 6)
3. Create PostLog entry
4. Update PendingApproval.status = "posted"
5. Items with `awaiting` status that got approved: also posts them

**DONE test:** create PendingApproval(status="approved") → run job → PostLog entry created

---

## Stage 9: Regeneration Flow

**Goal:** Handle 🔄 button with max 3 attempts

**Location:** Telegram callback handler in `telegram_bot.py`

**Logic:**
- Check `pending_approval.regeneration_count < MAX_REGENERATIONS (3)`
- If yes: `regeneration_count += 1`, re-run stages 3→1→2→5, edit old Telegram message + send new one
- If no: answer callback with `show_alert=True` "Max regenerations reached", disable the button

**DONE test:** click 🔄 3 times → 4th shows "Max regenerations reached"

---

## Stage 10: Scheduler (APScheduler)

**Goal:** Auto-run morning and evening jobs at correct times

**Location:** `ai_bag_agent/extensions.py` (scheduler setup) + `ai_bag_agent/__init__.py` (start)

**Implementation:**
```python
scheduler = BackgroundScheduler(timezone="Asia/Tbilisi")
scheduler.add_job(morning_job, CronTrigger(hour=9, minute=0))
scheduler.add_job(evening_job, CronTrigger(hour=20, minute=0))
```

**DONE test:** set local clock to 08:59 → wait 2 minutes → morning_job runs

---

## Stage 11: Settings UI

**Goal:** Edit prompt template, view API credential status

**Routes:**
- `GET/POST /admin/settings` — prompt template editor + connection status

**Template:** `ai_content/settings.html`
- Global prompt template textarea
- Per-service connection status (✅/❌ — calls test function, never shows actual key)
- Manual "Test Connection" buttons

**DONE test:** edit prompt → save → check DB Setting('prompt_template') updated

---

## Stage 12: Approvals History + Posts Log

**Goal:** Full audit trail in admin panel

**Routes:**
- `GET /admin/approvals` — paginated list (filter by status, date, bag)
- `GET /admin/posts` — paginated list with FB/IG links

**DONE test:** create 25 records → paginate → filter works

---

## Stage 13: Production Polish

**Goal:** Reliable, observable production system

**Tasks:**
- Replace `logging.basicConfig` with `python-json-logger` (structured JSON)
- Add `@retry(stop=stop_after_attempt(3), wait=wait_exponential())` to all API calls
- `GET /health` already done — add DB ping check
- Error notifications: send to Telegram chat (optional)
- Rate limit awareness: Pinterest (10 req/s), Meta (200 calls/hr)

**DONE test:** intentionally break one service → error logged → app continues

---

## Stage 14: Railway Deployment

**Goal:** Live on Railway with PostgreSQL

**Steps:**
1. `railway login`
2. `railway init` → new project
3. Add PostgreSQL plugin → DATABASE_URL auto-set
4. Set all env vars in Railway Variables panel
5. `railway up` → deploy
6. Run DB migrations: `railway run flask --app wsgi db upgrade`
7. Create admin: `railway run flask --app wsgi auth create-admin`
8. Verify `/health` returns 200

**DONE test:** open Railway URL → login → dashboard loads → manually trigger morning job

---

## Edge Cases & Notes

### Pinterest Token Expiry
Trial tokens expire every 24h. System should:
1. Log WARNING when token is about to expire (check at startup)
2. Morning job fails gracefully if token expired (logs error, sends Telegram notification)
3. Admin can update token via Settings UI

### Telegram Callback Timeout
Telegram expects `callback_query.answer()` within 15 seconds, otherwise the
loading spinner stays on the user's button. Strategy: call `answer()` immediately
(empty or short text), then perform DB/IO work, then `edit_message_*` afterwards.

### kie.ai Rate Limits
If API is busy, generation can fail. Strategy:
- Retry 3x with exponential backoff (10s, 20s, 40s)
- If all fail: set PendingApproval.status = "failed", send Telegram notification

### Awaiting Items
Items that weren't approved by 20:00 get status="awaiting".
Evening job: also process awaiting items where responded_at is not null.
(i.e., approved after 20:00 → post at next 20:00 run)

### Multi-tenancy (future)
All tables have `tenant_id` column (default="default").
When migrating to another admin panel: pass `tenant_id` as context variable in Blueprint.
