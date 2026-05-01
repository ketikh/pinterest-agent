# 001: Flask Blueprint Architecture (migration-ready)

## Date
2026-05-01

## Status
accepted

## Context
Building an AI Bag Content Agent as a standalone Flask application. The user requires that the core functionality (`ai_content`) be portable to another admin panel as a separate tab in the future, with minimal code changes.

## Decision
Structure the application using Flask Blueprints with two main modules:
- `auth/` — lightweight authentication (login/logout only)
- `ai_content/` — the entire feature module (self-contained, migration unit)

## Reasoning
- Flask Blueprints are designed exactly for this use case: modular, portable, registerable
- `ai_content/` contains all routes, models, services, templates, and jobs for the feature
- Moving to another Flask app requires only: registering the blueprint + copying the templates folder
- Alternative (flat structure) was rejected because it creates tight coupling between auth and business logic

## Consequences
- Slightly more directory depth than a simple flat app
- Clean separation means auth can be swapped (e.g., replaced with another app's auth) without touching ai_content
- All DB models live in `ai_content/models.py` — single source of truth for the feature's data
