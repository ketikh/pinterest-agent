# Testing Rules

## Framework
- pytest + pytest-flask + pytest-mock
- Run: `python -m pytest tests/ -v`
- Coverage: `python -m pytest tests/ --cov=ai_bag_agent --cov-report=term-missing`
- Target: 80%+ coverage on new code, 90%+ on services/

## When to Test (automatic triggers)
- After every new function: write at least 1 test (happy path + 1 error case)
- After every bug fix: write regression test FIRST, then fix
- After every API route: test status code + response shape
- Before every commit: run full suite

## Test Structure
```
tests/
├── unit/           ← fast, no DB, no external APIs (mock everything)
│   ├── test_ai_generator.py
│   ├── test_cloudinary_svc.py
│   ├── test_pinterest_client.py
│   ├── test_telegram_bot.py
│   ├── test_meta_poster.py
│   └── test_models.py
└── integration/    ← uses test DB (SQLite), no real external APIs
    ├── test_morning_job.py
    ├── test_evening_job.py
    └── test_admin_routes.py
```

## Mocking External APIs
- kie.ai: mock HTTP response
- Cloudinary: mock upload method
- Pinterest: mock pin list response
- Telegram: mock Bot.send_photo + Bot.edit_message_reply_markup
- Meta Graph API: mock POST requests

## What to Test Per Stage
- Stage 0: login/logout flow, DB model CRUD
- Stage 1: generate_image() with mocked kie.ai
- Stage 2: upload_image() with mocked cloudinary
- Stage 3: get_random_pin() with mocked Pinterest
- Stage 4: upload bag form validation + queue FIFO order
- Stage 5: Telegram inline-keyboard callback handler
- Stage 6: post_to_facebook() + post_to_instagram() with mocked Meta
- Stage 7: morning_job() end-to-end with all services mocked
- Stage 8: evening_job() with approved records
- Stage 9: regeneration counter limits
- Stage 10: scheduler job registration

## Communication
- Never say "pytest passed" to user
- Say: "დავამოწმე და ყველაფერი მუშაობს სწორად"
- Show screenshots for UI changes
- Only show test output if user specifically asks
