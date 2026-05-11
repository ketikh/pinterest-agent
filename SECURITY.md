# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest  | ✅ Yes    |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it by emailing the project owner directly rather than opening a public issue.

**Do NOT create a public GitHub issue for security vulnerabilities.**

### What to include in your report

1. Description of the vulnerability
2. Steps to reproduce
3. Potential impact
4. Suggested fix (if you have one)

### Response timeline

- Acknowledgment: within 48 hours
- Status update: within 7 days
- Fix: within 30 days for critical issues

## Security Practices

This project follows these security practices:

- All secrets stored in environment variables (never in code)
- Telegram bot token kept server-side only; polling in dev, webhook with secret token in production
- All user inputs validated with Flask-WTF
- SQL injection prevented via SQLAlchemy ORM
- Passwords hashed with bcrypt
- HTTPS enforced in production
- Security headers enabled (via Flask-Talisman in production)
- Dependencies audited regularly with `pip audit`
