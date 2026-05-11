# Interaction Rules

## Language
- Default: Georgian (ქართული)
- Switch to English only if user writes in English
- Technical terms stay in English (Flask, API, Telegram, etc.)

## Explaining Changes
- Always say WHAT changed and WHY in plain language
- After every change: tell user WHERE to look to verify (URL, file, button)
- Never show raw stack traces — translate to plain language first

## Stage Workflow (specific to this project)
- At the end of each Stage, always report:
  1. "ეს Stage დასრულდა. სატესტო: [plain-language test the user can run]"
  2. "შემდეგ Stage-ამდე გჭირდება: [accounts/credentials to create]"

## Scope Control
- Change ONLY what was asked
- If changing 4+ files: list them and get confirmation first
- No uninstructed refactoring or "cleaning up" nearby code
- If you spot a bug elsewhere: mention it but do NOT fix it without permission

## Vague Requests
- Interpret charitably → show result → ask for refinement
- Do NOT ask 5 questions before doing anything
- Exception: if the request could cause data loss → ask first

## Recovery Commands (respond immediately to these)
- "გააუქმე ბოლო ცვლილება" → git restore
- "რაღაც გაფუჭდა, გაასწორე" → diagnose + fix
- "დააბრუნე ბოლო მომუშავე ვერსია" → show git log, let user pick checkpoint

## Checkpoint Rule
- Before any multi-file change (3+ files): auto-commit checkpoint
- Format: CHECKPOINT: [plain description] — Status: [WORKING/IN-PROGRESS]
