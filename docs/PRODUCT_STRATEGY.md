# SaveSync Product Strategy

**Last reviewed:** 2026-07-01

---

## Vision

Never lose your game saves again.

---

## Why SaveSync Exists

We believe players should own and protect their progress — regardless of where they bought a game or which cloud service they use.

---

## Mission

- Protect game saves from loss with minimal user effort.
- Support backup to local folders and major cloud providers.
- Make restore as reliable as backup.
- Earn trust through transparency, not marketing.
- Build a polished desktop experience first; expand thoughtfully.

---

## Problem

PC gamers lose hundreds of hours to: failed hard drives, OS reinstalls, corrupted save files, gaps in Steam Cloud (many games don't use it), accidental overwrites, and "I'll back that up later" procrastination. Existing solutions are either too technical (manual file copying), too heavy (full disk imaging), or locked to a single platform.

SaveSync is built for protecting PC game saves first, while remaining flexible enough to back up any important folders users choose.

---

## Target User

| Persona | Description | Priority |
|---------|-------------|----------|
| **PC Gamer** | Plays on Steam, Epic, or GOG. Values saves. Not particularly technical. Willing to configure once. | Primary |
| **Modder** | Manages configs and mods across many installations. Wants cloud-backed saves. | Secondary |
| **Power User** | Uses multiple PCs. Wants saves synced across machines via cloud storage. | Secondary |

**Not targeted:** Enterprise IT, NAS administrators, general-purpose file sync users (unless they also happen to be gamers).

---

## Product Principles

1. **Reliability over features.** A feature that corrupts saves is worse than not having the feature.
2. **Restore is as important as backup.** Backup without verified restore is hope, not backup.
3. **Never silently lose user data.** Every error is logged with a code, a message, and context.
4. **Show progress clearly.** Users should always know what the app is doing and whether it succeeded.
5. **Privacy first.** No telemetry, no analytics, no data collection without explicit consent. Tokens stay on the device.
6. **Local-first.** The app works fully offline with local destinations. Cloud is optional.
7. **Every cloud provider is optional.** Install without any. Add them later.
8. **Thread-safe by design.** The UI never blocks. Background operations are always cancellable.
9. **Simple by default.** Advanced features should never make basic backup confusing.

---

## What Will Never Be Added

- Aggressive telemetry, analytics, or usage tracking
- Ads or bundled third-party software
- Subscription-required core functionality
- Cloud-only features (basic sync always works offline)
- Backdoor access to user files

---

## Commercial Model

A permanent free edition will always exist. Optional paid editions will add advanced capabilities without removing core backup functionality from the free version.

The free edition is the acquisition channel. Paid upgrades serve users who already rely on the app.
