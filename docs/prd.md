# PRD — Aqueduct

**Status:** Draft v1 · **Owner:** meitalKrin · **Last updated:** 2026-08-23

---

## 1. Problem

I want to know what I am spending, as I spend it, without doing data entry.

Actual Budget is the right ledger — open source, self-hostable, and it has a
real envelope-budgeting engine. But getting *data into it* is the whole problem:

- Actual's automated bank sync (GoCardless / SimpleFIN) has effectively **no
  Israeli bank or credit-card coverage**. That door is closed.
- Manual entry doesn't survive contact with real life. Budgets die from
  friction, not from bad maths.
- Monthly CSV import works, but a budget you only see once a month is a
  *history report*, not a budget. By the time the statement lands, the money is
  already gone.

The gap is **latency**. I need spending to show up in minutes, not weeks — while
still ending up with a ledger that matches my bank statement exactly.

## 2. The insight the design rests on

My phone already knows about a payment the instant it happens: Google Wallet
posts a notification for every tap-to-pay.

But that notification is **a prediction, not a record**:

- It only fires for **NFC taps made with this phone**. Physical card swipes,
  online purchases, standing orders, direct debits and transfers are invisible to it.
- It carries the **authorisation** amount. Tips, currency conversion, partial
  refunds and holds settle differently.
- It can be delayed, edited, duplicated, or never arrive at all.

The **monthly statement is the truth**. So the system runs two tracks that meet:

```
tap  →  instant, provisional, "pending"   ─┐
                                           ├─→  reconcile  →  one clean ledger
statement CSV  →  monthly, authoritative  ─┘
```

Everything else in this document is machinery in service of those two tracks
meeting cleanly instead of producing a pile of duplicates.

## 3. Goals

| # | Goal | How we know it worked |
| --- | --- | --- |
| G1 | A tap-to-pay shows up in Actual without me touching anything | ≥95% of taps land as transactions (measured over a 30-day trial against my statement) |
| G2 | It shows up *fast* | Median tap→visible-in-Actual under 10 minutes while phone has connectivity |
| G3 | The ledger still matches the bank exactly | After reconciliation, account balance in Actual == statement closing balance, to the agora |
| G4 | I never silently lose a payment | Every captured notification is stored durably, including ones the parser failed on; zero silent drops |
| G5 | I can't forget to import a statement | Bank "statement ready" email produces a notification that persists until the CSV is actually ingested |
| G6 | I learn the ops side properly | I build and operate the Pi, Docker, networking and backups myself, including a tested restore |

## 4. Non-goals (v1)

- **Not** replacing the Actual web UI. Budgeting, categorising and reporting all
  happen in Actual. This project only feeds it.
- **Not** a Play Store app. Personal, sideloaded, single user, single phone.
- **Not** scraping bank websites. (`israeli-bank-scrapers` is a real option and is
  noted as a v2 candidate, but it's fragile, needs my banking credentials, and
  is a much bigger security surface. Not now.)
- **Not** multi-user, multi-phone, or multi-household.
- **Not** an on-phone budget UI. The phone captures and nags; it does not report.
- **Not** categorising transactions itself. Actual's own **Rules engine** does
  categorisation from the payee name. The bridge stays dumb on purpose.

## 5. Context and constraints

### C1 — Hardware: Raspberry Pi Zero 2 W
Quad-core Cortex-A53, **512 MB RAM**. RAM is the binding constraint on every
decision in the architecture. Consequences: 64-bit OS Lite only, no desktop, no
building container images on the device, hard memory limits per container, and a
design that keeps the memory-hungry Actual client work **short-lived and batched**
rather than resident.

### C2 — Locale: Israel, ILS (₪), Hebrew
Notification text will be Hebrew, right-to-left, with `₪`, embedded Unicode bidi
control characters, and possibly Western Arabic numerals in an RTL run. Bank and
credit-card CSV exports are commonly `windows-1255` encoded with Hebrew column
headers, and some "`.xls`" exports from Israeli issuers are actually HTML tables.
**The exact strings are unknown to us today** — see R1.

### C3 — Ownership split
Infrastructure is a learning exercise for the owner and is out of scope for
Claude; application code is out of scope for the owner. The two lanes meet at a
written contract (env vars, ports, volumes, healthcheck).

### C4 — Connectivity
The Pi lives on the home LAN and is never exposed to the public internet. Phone
and Pi are joined by **Tailscale**, so the phone can reach the bridge from
anywhere over WireGuard without opening a single router port. The phone still
queues everything locally first — Tailscale reduces latency, it is not a
correctness dependency.

## 6. Scope

### v1 — the thing we are building

| ID | Feature | Lane |
| --- | --- | --- |
| F1 | Capture Google Wallet payment notifications on Android | app |
| F2 | "Teach mode" — capture raw notification text so the parser can be built against real strings | app |
| F3 | Durable on-phone queue with retry; nothing is lost if the Pi is unreachable | app |
| F4 | In-app review screen: see captured events, fix parse failures, re-queue, delete false positives | app |
| F5 | Bridge ingest API — idempotent, authenticated, cheap | bridge |
| F6 | Batched writer — flushes the inbox into Actual as **uncleared** transactions | bridge |
| F7 | Statement-ready detection from the bank's email notification, on-phone | app |
| F8 | Persistent (ongoing, non-dismissable) nag notification until the statement is ingested | app + bridge |
| F9 | Statement CSV upload + per-issuer parsing profiles | bridge |
| F10 | Reconciliation: match statement rows against pending taps, merge, never duplicate | bridge |
| F11 | Health, watchdog and observability — know when capture has silently stopped | app + bridge |
| F12 | CI-built APK so the owner never installs Android tooling | ci |
| F13 | Pi platform: Docker, compose, Tailscale, volumes, backups, restore drill | ops |

### v2 — explicitly deferred, designed for

- IMAP statement detection as a fallback when the phone misses the email
- `israeli-bank-scrapers` as an authoritative auto-pull, replacing manual CSV
- Multiple cards / accounts beyond the initial mapping
- Foreign-currency auto-matching with FX rate lookup

### Out of scope

Play Store distribution · iOS · multi-user · budget reporting on the phone ·
anything that requires storing my banking site credentials.

## 7. Functional requirements

Written in EARS form. `SHALL` is binding; each maps to at least one backlog task.

### Capture (Android)

- **FR-1** — When a notification is posted by a package on the configured
  allowlist, the app SHALL persist the event (package, post time, title, text,
  big text, notification key) to local storage **before** any parsing is attempted.
- **FR-2** — The app SHALL discard group-summary notifications
  (`FLAG_GROUP_SUMMARY`) and SHALL treat a notification update to an existing
  key as an update to the same event, not a new one.
- **FR-3** — The app SHALL deduplicate events by content hash within a
  configurable window (default 120s) so that a re-posted or edited notification
  does not create a second transaction.
- **FR-4** — When parsing fails or yields an ambiguous result, the app SHALL
  store the event with status `UNPARSED` and surface it in the review screen.
  It SHALL NOT discard it and SHALL NOT guess.
- **FR-5** — The app SHALL strip Unicode bidi control characters
  (U+200E, U+200F, U+202A–U+202E, U+2066–U+2069) before applying parse patterns.
- **FR-6** — Amounts SHALL be stored as signed integers in minor units (agorot),
  never as floating point.
- **FR-7** — In teach mode, the app SHALL let the owner export the raw captured
  corpus so parse patterns can be authored against real strings.

### Delivery (Android → bridge)

- **FR-8** — Every event SHALL carry a client-generated UUID that is stable
  across retries, so the bridge can be idempotent.
- **FR-9** — The app SHALL retry failed deliveries with exponential backoff and
  SHALL NOT drop an event on repeated failure; it SHALL surface persistent
  failure in the UI after a configurable threshold.
- **FR-10** — The app SHALL only mark an event delivered on an explicit
  acknowledgement from the bridge naming that event's UUID.
- **FR-11** — The auth token SHALL be stored in Android Keystore-backed
  encrypted storage and SHALL NOT be written to logs.

### Bridge

- **FR-12** — The ingest endpoint SHALL authenticate every request with a bearer
  token and SHALL reject unauthenticated requests without touching the payload.
- **FR-13** — Ingest SHALL be idempotent on event UUID: re-delivery returns
  success without creating a second inbox row.
- **FR-14** — Ingest SHALL write to a local durable inbox and return, **without**
  opening a session to Actual, so that a slow or down Actual server never
  causes the phone to lose an event.
- **FR-15** — A separate flush worker SHALL batch pending inbox rows into Actual
  on a schedule (default every 5 minutes) and on demand.
- **FR-16** — Transactions written from taps SHALL be created **uncleared**, with
  `imported_id = "wallet:<uuid>"` and a `#wallet-auto` note tag, so they are
  visually and programmatically distinguishable from statement transactions.
- **FR-17** — The bridge SHALL NOT set categories. Payee is set from the merchant
  string; categorisation is delegated to Actual's Rules engine.

### Statement cycle

- **FR-18** — When a notification from the mail app matches a configured
  statement-ready rule (sender + subject pattern per issuer), the app SHALL
  raise a **statement-pending** state for that issuer and period.
- **FR-19** — While a statement is pending, the app SHALL display an ongoing,
  non-dismissable notification naming the issuer and period.
- **FR-20** — The ongoing notification SHALL be cleared only when the bridge
  confirms a statement for that issuer and period has been successfully ingested,
  or when the owner explicitly dismisses it with a recorded reason.
- **FR-21** — The bridge SHALL accept a statement file upload, parse it using the
  issuer's profile, and reject with a clear error rather than importing a
  partially-understood file.
- **FR-22** — Statement rows SHALL be written as **cleared** transactions and are
  authoritative for balance.

### Reconciliation

- **FR-23** — For each statement row, the bridge SHALL search for a matching
  pending tap in the same account where the amounts are equal in minor units and
  the statement date falls within `[tap_date, tap_date + N days]` (N default 5).
- **FR-24** — On exactly one match, the bridge SHALL keep the statement
  transaction, carry over the tap's payee/notes where richer, delete the tap
  placeholder, and write a reconciliation log entry.
- **FR-25** — On multiple candidate matches, the bridge SHALL NOT auto-merge; it
  SHALL flag both for review.
- **FR-26** — Where the tap's currency differs from the account currency, the
  bridge SHALL NOT auto-match on amount and SHALL flag for review.
- **FR-27** — A tap unmatched after a configurable age (default 45 days) SHALL be
  surfaced as an exception, not silently deleted.

### Observability

- **FR-28** — The bridge SHALL expose a healthcheck reporting: inbox depth,
  oldest unflushed event age, last successful Actual write, and Actual
  reachability.
- **FR-29** — The app SHALL run a periodic watchdog that verifies notification
  access is still granted and that events have been seen recently, and SHALL
  warn the owner when capture appears to have stopped.

## 8. Non-functional requirements

| ID | Requirement |
| --- | --- |
| NFR-1 | The whole stack SHALL fit and stay stable in 512 MB RAM, verified under a 7-day soak, with zram enabled and per-container memory limits set |
| NFR-2 | No component SHALL be reachable from the public internet; the bridge binds to loopback and the tailnet interface only |
| NFR-3 | Zero data loss on power cut: every write path is durable before acknowledgement |
| NFR-4 | The bridge SHALL survive Actual being down for 24h without losing events |
| NFR-5 | Merchant strings are untrusted input: length-capped, never interpolated into SQL or shell, never rendered as HTML unescaped |
| NFR-6 | Budget data SHALL be backed up nightly off the SD card, encrypted at rest off-box, with a **restore that has actually been performed** at least once |
| NFR-7 | Median tap→Actual latency under 10 minutes with connectivity; under 30 minutes on next reconnect |
| NFR-8 | The Android app SHALL survive OEM battery optimisation; setup SHALL include the battery-exemption step as a verified checklist item |

## 9. Risks and unknowns

These are the things that can actually kill this project. Epic 0 exists to
resolve them **before** any real building.

| ID | Risk | Impact | How we retire it |
| --- | --- | --- | --- |
| **R1** | We do not know the exact Hebrew text Google Wallet posts, or whether it posts one at all for every tap on this device/issuer | Fatal — no capture, no project | **Spike 0.1**: ship teach-mode first as a throwaway build, tap-to-pay a few times, read the real strings |
| **R2** | `actualpy` ↔ Actual Server version compatibility, and whether both run on arm64 | High — forces a Node bridge, which may not fit in RAM | **Spike 0.2**: pin and verify a working pair on the actual hardware before writing bridge code |
| **R3** | ~~512 MB is not enough for Actual + bridge + Tailscale + Docker~~ **Largely retired 2026-08-30** | Was: forces different hardware | Measured: real ceiling is 463 MiB after `gpu_mem=16`, and OS + Docker + `actual-server` use **233 MiB**, leaving **230 MiB available**. Tailscale + bridge should fit with ~110 MiB spare. **Residual risk:** how `actual-server` grows under a real budget with active sync — that is what the G4 soak measures |
| **R4** | OEM battery management silently kills the notification listener | High — silent data loss, the worst failure mode | Battery exemption at setup + FR-29 watchdog + health surfacing. Treated as *when*, not *if* |
| **R5** | Israeli issuer CSV exports are encoding/format hostile (`windows-1255`, Hebrew headers, fake `.xls`) | Medium — reconciliation blocked | Per-issuer profile files authored from a real sample export; explicit reject over silent misparse (FR-21) |
| **R6** | SD-card wear or corruption takes the budget with it | Medium — total data loss | NFR-6: volumes on USB where possible, nightly encrypted off-box backup, tested restore |
| **R7** | Notification amount ≠ settled amount (tips, FX, holds) | Low by design | This is *why* taps are provisional and the statement is authoritative |

## 10. Success criteria

v1 is done when, over one full statement cycle:

1. ≥95% of my tap-to-pay transactions appeared in Actual automatically (G1).
2. Median tap→visible latency was under 10 minutes (G2).
3. After importing the statement, Actual's account balance matched the
   statement closing balance exactly, with **zero duplicate transactions** (G3).
4. Every notification the parser could not read is sitting in the review
   screen — none were silently dropped (G4).
5. The statement nag fired, persisted, and cleared only on real ingest (G5).
6. I can rebuild the Pi from my own notes and restore the budget from backup (G6).

## 11. Open questions

| # | Question | Blocks | Default if unanswered |
| --- | --- | --- | --- |
| Q1 | Which issuers/cards are in scope, and which Actual account does each map to? | CSV profiles, account mapping | One card, one account; expand later |
| Q2 | Does the statement CSV go to the bridge (reconcile-then-write) or straight into Actual's own importer? | Reconciliation design | **Bridge** — see [D7](decisions.md#d7--statement-csv-is-ingested-by-the-bridge-not-by-actuals-importer) |
| Q3 | Where do volumes live — SD card or USB storage? | Backup design, R6 | USB if available, SD with nightly backup if not |
| Q4 | Retention for the raw notification corpus on the phone | Privacy, storage | 90 days, then raw text purged, parsed record kept |
