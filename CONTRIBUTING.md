# Contributing

## Setup

```bash
git clone <repo>
cd pinterest-agent
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in .env values
flask db upgrade
flask run
```

## Branch Strategy

- `main` — production-ready only
- `develop` — integration branch
- `feature/stage-N-description` — new stage work
- `fix/description` — bug fixes

## Commit Format

```
feat: add kie.ai image generation service
fix: prevent duplicate Pinterest pin selection
test: add morning_job integration test
docs: update Stage 3 DONE criteria in PLAN.md
```

## Before Submitting a PR

1. `python -m pytest tests/ -v` — all pass
2. `black --check ai_bag_agent/ tests/`
3. `flake8 ai_bag_agent/ tests/ --max-line-length=88`
4. `isort --check-only ai_bag_agent/ tests/`
5. No hardcoded secrets
6. .env.example updated if new vars added
