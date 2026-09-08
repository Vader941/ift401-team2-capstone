# Security Policy

## Educational Scope

This application is a classroom stock trading simulation. It must not process real trades, store brokerage credentials, or be represented as financial advice.

## Reporting a Security Concern

Do not publish exploitable security details, credentials, or private information in a public issue. Notify the repository owner and team privately, then create a sanitized tracking item if appropriate.

## Repository Safety

Never commit:

- Passwords, API keys, access tokens, or private keys
- Local `.env` files
- Production database contents or backups
- Real financial account information
- Private teammate, instructor, or student information
- Instructor-only course content or grading materials

If a secret is committed, deleting it in a later commit is not sufficient. Treat it as exposed, revoke or rotate it immediately, and notify the team.

## Application Practices

- Use Django's authentication, password hashing, CSRF protection, and ORM as intended.
- Validate all user-controlled input.
- Keep dependencies deliberate and documented.
- Do not use production credentials in local development.
- Disable Django debug mode in deployment.
- Store deployment secrets outside the repository.
