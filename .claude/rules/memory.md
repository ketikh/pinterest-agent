# Memory & Context Rules

## Session Start
1. Check .claude/handoff-*.md for last session notes
2. Run `git log --oneline -5` to see recent commits
3. Tell user: "ბოლოს ვმუშაობდი [X]-ზე. გავაგრძელო?"

## Session End
Create: `.claude/handoff-YYYY-MM-DD.md`
Include:
- Stage completed
- Current app status
- Next steps (numbered by priority)
- Credentials status (which accounts are set up)
- Any unresolved issues

## Architectural Decisions → docs/decisions/
Format: NNN-title.md
Required fields: Date, Status, Context, Decision, Reasoning, Consequences

Create ADR when:
- Choosing integration approach for a service
- Deciding between threading models (Discord bot)
- Changing DB schema
- Deployment strategy decisions

## Stage Progress Tracking
Keep track in PLAN.md — mark stages as DONE:
```
- [x] Stage 0: Skeleton + Auth ✅ (date)
- [ ] Stage 1: kie.ai Generator
```

## Context Window
- Suggest /compact after 20+ exchanges
- Before any large Stage: summarize current state first
