# Security Policy

## Scope

Leadle OS is an internal RevOps tool. It holds read-only credentials to HubSpot,
Instantly, Fathom, Aimfox, Slack, and Supabase. No credentials are committed to git.

## Reporting a vulnerability

If you find a security issue, do not open a public GitHub issue.

Email: **revops@leadle.in** with subject `[SECURITY] Leadle OS — <short description>`

We will acknowledge within 48 hours and patch critical issues within 7 days.

## Credential handling

- All secrets live in `.env` (gitignored)
- `.env.example` contains only placeholder values — never real keys
- The system is read-only against source systems (HubSpot, Lemlist, Aimfox, Instantly, Fathom)
- No write-back to any source tool is implemented or permitted in Phase 1

## Supported versions

| Version | Supported |
|---------|-----------|
| main    | Yes       |
| feature branches | No — use main |
