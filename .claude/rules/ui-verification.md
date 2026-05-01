# UI Verification Rules

## Trigger
After ANY change to .html, .css, .js files in templates/ — run visual check.

## Sequence
1. Ensure `flask run` is running
2. Navigate to affected page with Playwright
3. Screenshot at desktop (1440x900)
4. Screenshot at mobile (375x812)
5. Show screenshots to user with plain-language description
6. Ask: "ასე გამოიყურება — კარგია?"

## Pages to Check After Each Stage
- Stage 0: /auth/login, /admin/dashboard
- Stage 4: /admin/queue (bag list + upload form)
- Stage 11: /admin/settings
- Stage 12: /admin/approvals, /admin/posts

## Checks
- No broken layout or overlapping elements
- Forms are labeled and functional
- Status badges visible (pending/approved/rejected/awaiting)
- Mobile: no horizontal scroll, buttons are tappable (44px+)
- No console errors

## Admin Panel Style
- Clean, minimal — this is an internal tool, not a public site
- Dark sidebar + light content area (professional)
- Status colors: pending=yellow, approved=green, rejected=red, awaiting=blue
- Bootstrap 5 (CDN) — no custom build step needed
