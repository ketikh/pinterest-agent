# Security Rules

## Secrets
- NEVER put API keys, tokens, passwords in source code
- ALL secrets go in .env (dev) or Railway Variables (prod)
- .env is in .gitignore — never commit it
- .env.example has all variable names with placeholder values only

## Input Validation
- All form inputs validated with Flask-WTF (CSRF protection)
- File uploads: check magic bytes, not just extension
- Max upload size: 10MB (configurable in .env)
- Reject filenames with path traversal characters

## Authentication
- Passwords hashed with bcrypt (cost factor 12)
- Session cookies: Secure + HttpOnly + SameSite=Strict
- Session timeout: 8 hours inactivity
- Login rate limit: 5 attempts per minute per IP

## Telegram Security
- TELEGRAM_BOT_TOKEN kept in .env only — never logged, never sent to client
- Polling mode (dev): no public endpoint exposed
- Webhook mode (production): set secret_token in setWebhook and verify
  `X-Telegram-Bot-Api-Secret-Token` header on every incoming request; reject with 401 otherwise
- Restrict bot to a single TELEGRAM_CHAT_ID — ignore callbacks from any other chat

## API Keys in DB
- Settings table stores API credentials encrypted (Fernet)
- Encryption key derived from FLASK_SECRET_KEY
- Never log or display actual credential values — show ✅/❌ only

## SQL Injection
- Use SQLAlchemy ORM exclusively — no raw SQL string concatenation
- If raw SQL is needed: use text() with bound parameters only

## Production
- HTTPS enforced (Railway provides TLS)
- Security headers via Flask-Talisman
- No debug mode in production (FLASK_ENV=production)
- Error responses: never expose internal details or stack traces

## Dependencies
- Pin all versions in requirements.txt
- Run `pip audit` before deploy
- No deprecated or unmaintained packages
