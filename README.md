# Aqueduct — Google Wallet → Actual Budget

> **Codename `aqueduct` is provisional.** The repo name (`BankCSVToDashboard`) is a
> stand-in from an earlier idea. Rename both when you settle on something.

A self-hosted personal budgeting pipeline running on a **Raspberry Pi Zero 2 W**:

- **Actual Budget** runs 24/7 in Docker on the Pi — the single source of truth.
- An **Android app** listens to Google Wallet notifications and captures every
  tap-to-pay the moment it happens.
- A small **Python bridge** on the Pi receives those events and writes them into
  Actual as *pending* transactions.
- When your bank emails "your monthly statement is ready", the phone raises a
  **nagging notification that will not go away** until you feed the statement CSV in.
- The bridge **reconciles** the CSV against the pending taps, so you get instant
  feedback without duplicate transactions.

## Why this shape

Israeli banks have essentially no coverage in Actual's built-in bank-sync
providers (GoCardless / SimpleFIN). Notification scraping is the only way to get
*instant* spending feedback here. But notifications are a **prediction**, not a
record — they only fire for NFC taps on the phone, and they show the
authorisation amount. The monthly statement is the **truth**. The whole design
follows from holding both of those facts at once.

## Documents

| Document | What it is |
| --- | --- |
| [`docs/prd.md`](docs/prd.md) | What we are building and why — scope, requirements, success criteria |
| [`docs/architecture.md`](docs/architecture.md) | How it works — components, data model, contracts, reconciliation, ops seam |
| [`docs/backlog.md`](docs/backlog.md) | The task list, by epic, with owners and dependencies |
| [`docs/ops-runbook.md`](docs/ops-runbook.md) | **Your lane** — the Pi/Docker/backup checkpoints, with verification commands |
| [`docs/decisions.md`](docs/decisions.md) | Decision log — what was chosen and what was rejected |

## Who does what

This project is deliberately split so you learn the ops side and don't have to
touch Android or Python.

| Lane | Owner | Covers |
| --- | --- | --- |
| **Ops / platform** | **You** | Pi OS, Docker, compose, volumes, Tailscale, backups, restore drills, updates, monitoring |
| **Application code** | **Claude** | Android app (Kotlin), Python bridge, reconciler, CSV profiles, tests, CI APK builds |

The seam between the lanes is a written contract — image names, env vars, ports,
volume paths, healthchecks — in
[`architecture.md` → Ops contract](docs/architecture.md#13-ops-contract--the-seam-between-lanes).
You should never need to read Python to write the compose file.

## Status

Planning. Nothing is built yet. Start at
[`docs/backlog.md` → Epic 0](docs/backlog.md#epic-0--spikes-de-risk-before-building-anything),
which exists to kill the four assumptions that could sink the whole design.
