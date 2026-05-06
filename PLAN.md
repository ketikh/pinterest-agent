# PLAN.md — AI Bag Content Agent Build Plan

## Progress

- [x] Phase 1: Infrastructure + setup ✅ (2026-05-01)
- [x] Stage 0: Project skeleton + DB + auth ✅ (2026-05-01)
- [x] Stage 1: kie.ai Generator ✅ (2026-05-01)
- [x] Stage 2: Cloudinary Uploader ✅ (2026-05-06)
- [x] Stage 3: Pinterest Client (API v5) ✅ (2026-05-06)
- [x] Stage 4: Admin UI — Bag Queue management ✅ (2026-05-06)
- [ ] Stage 5: Discord Bot (approval workflow)
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

## Stage 5: Discord Bot

**Goal:** Send generated image to Discord, handle ✅/❌/🔄 button clicks

**File:** `ai_bag_agent/ai_content/services/discord_svc.py`

**How it works:**
- Runs as background thread (see docs/decisions/002-discord-threading.md)
- Sends embed message with: generated image, bag name, regeneration count
- 3 buttons: Approve (green), Reject (red), Regenerate (grey)
- On button click: updates `pending_approvals.status` in DB

**DONE test:** run bot → call `send_approval_request()` manually → Discord message appears → click ✅ → DB status = "approved"

**Accounts needed:** Discord Developer Portal
1. Create Application → Bot → copy token → DISCORD_BOT_TOKEN
2. Create server → copy channel ID → DISCORD_CHANNEL_ID
3. Enable Message Content Intent

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

**Goal:** Full pipeline: queue → Pinterest → kie.ai → Cloudinary → Discord

**File:** `ai_bag_agent/ai_content/jobs/morning_job.py`

**Function:** `run_morning_generate(app)` — full pipeline
1. Get next `pending` BagQueue item (lowest sort_order + oldest created_at)
2. Get random reference pin (Stage 3, avoids recent)
3. Generate image (Stage 1)
4. Upload generated to Cloudinary (Stage 2)
5. Send to Discord (Stage 5)
6. Create PendingApproval record

**DONE test:** call `run_morning_generate()` directly → Discord message appears, DB record created

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

**Location:** Discord button handler in `discord_svc.py`

**Logic:**
- Check `pending_approval.regeneration_count < MAX_REGENERATIONS (3)`
- If yes: `regeneration_count += 1`, re-run stages 3→1→2→5, edit Discord message
- If no: set status = "rejected", update bag status, edit Discord message to "Max dostignut"

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
- Error notifications: log ERROR to Discord channel (optional)
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
2. Morning job fails gracefully if token expired (logs error, sends Discord notification)
3. Admin can update token via Settings UI

### Discord Interaction Timeout
Discord expects button interaction response within 3 seconds.
Solution: acknowledge immediately (response type 6), process async, edit message after.

### kie.ai Rate Limits
If API is busy, generation can fail. Strategy:
- Retry 3x with exponential backoff (10s, 20s, 40s)
- If all fail: set PendingApproval.status = "failed", send Discord notification

### Awaiting Items
Items that weren't approved by 20:00 get status="awaiting".
Evening job: also process awaiting items where responded_at is not null.
(i.e., approved after 20:00 → post at next 20:00 run)

### Multi-tenancy (future)
All tables have `tenant_id` column (default="default").
When migrating to another admin panel: pass `tenant_id` as context variable in Blueprint.
