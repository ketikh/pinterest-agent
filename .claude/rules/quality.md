# Code Quality Rules

## Python Standards
- Python 3.11+
- Type hints on ALL function signatures (params + return types)
- PEP 8 compliance via black + flake8 + isort
- Max line length: 88 (black default)
- Docstrings: one-line for simple functions, Google style for complex

## Structure
- Functions: max 50 lines → extract if larger
- Files: max 400 lines → split by responsibility if larger
- Max nesting depth: 4 levels
- One responsibility per function (single responsibility principle)

## Formatting Tools (run before every commit)
```bash
isort src/ tests/
black src/ tests/
flake8 src/ tests/ --max-line-length=88
```

## Naming
- Variables/functions: snake_case, descriptive
- Classes: PascalCase
- Constants: SCREAMING_SNAKE_CASE
- Booleans: is_active, has_permission, can_post
- Functions: verb + noun (get_next_bag, upload_image, post_to_instagram)

## Logging
- Use `python-json-logger` for structured JSON logs (production)
- Log levels: ERROR (broken), WARNING (degraded), INFO (lifecycle), DEBUG (dev)
- NEVER log: passwords, tokens, PII, full API responses with credentials
- Include: timestamp, function name, operation, duration, tenant_id

## Error Handling
- ALWAYS handle errors at every boundary
- Context in messages: "failed to upload to cloudinary: {original_error}"
- Never silently swallow exceptions
- Retry logic for external APIs: exponential backoff, max 3 retries

## Git
- Conventional commits: feat:, fix:, refactor:, docs:, test:, chore:
- No console.log / print() in production code
- No commented-out dead code

## Import Order (isort enforces this)
1. Standard library
2. Third-party (flask, sqlalchemy, telegram, etc.)
3. Local (ai_bag_agent.*)
