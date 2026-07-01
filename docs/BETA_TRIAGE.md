# Beta Triage

How feedback moves from tester to release.

## Priority

- **P0** — Data loss, corruption, crashes
- **P1** — Broken workflow
- **P2** — UX or usability
- **P3** — Nice-to-have

## Areas

- Backup
- Restore
- UI
- Cloud
- Installer
- Documentation

## Workflow

```
Inbox
↓
Needs Reproduction
↓
Confirmed
↓
Planned
↓
In Progress
↓
Ready to Test
↓
Closed
```

## Rules

- One report is an observation.
- Three independent reports indicate a pattern.
- Evidence beats opinion.
- Fix P0/P1 before adding features.
- UX requests go into the UX backlog, not the bug backlog.
