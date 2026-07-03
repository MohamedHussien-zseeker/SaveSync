# Design Principles

These principles guide every decision about SaveSync — what we build, how we build it, and what we say no to. They should change rarely.

---

## 1. Reliability before features

A feature that corrupts saves is worse than not having the feature. Every new capability must prove it handles failure before it ships.

## 2. Restore is as important as backup

Backup without verified restore is hope, not backup. The restore path is tested with the same rigor as the sync path.

## 3. Local-first

The app works fully offline with local destinations. Cloud services are optional additions, never requirements.

## 4. Privacy by default

No telemetry, no analytics, no data collection without explicit user consent. Credentials and tokens remain on the device.

## 5. Never surprise the user

Progress is always visible. Every operation can be cancelled safely. The app communicates what it's doing and whether it succeeded.

## 6. Errors should be understandable

Every error has a code, a human-readable message, and context. Silent failures are never acceptable.

## 7. Simple by default

Advanced features must never make basic backup confusing. The default experience should work for someone who just wants to protect their saves.

## 8. Never silently lose user data

If something goes wrong, the user is told. Errors are logged, surfaced in the UI, and never swallowed.
