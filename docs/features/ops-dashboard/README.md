---
title: Ops Dashboard
status: active
last_updated: 2026-10-12
---

# Ops Dashboard

Optional operational layer for the Web UI. Adds DynamoDB-backed job tracking, SNS email notifications, and a Cognito-authenticated admin dashboard with a per-job agent trace (agents in run order, tool calls with their code and output, generated files). The Web UI works normally without it.

## Where the code lives

- `deep-insight-web/ops/` — admin router, auth, job tracker, trace / files views
- `deep-insight-web/ops/lambda/` — job status Lambda, stale-job sweep
- `managed-agentcore/src/utils/event_log.py` — runtime-side trace recording and S3 upload

## References

- [agent-trace.md](./agent-trace.md) — agent trace recording, job status that always settles, stale-job sweep, trace view
- [admin-authentication.md](./admin-authentication.md) — Cognito JWT, cookies, route protection
- [language-switching.md](./language-switching.md) — Korean/English i18n for admin pages
- [plan/](./plan/) — business requirements, research, technical approach, implementation plan (original 2026-03 scope)
