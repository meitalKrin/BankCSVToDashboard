# Backlog — Aqueduct

Owner tags: **[OPS]** = you · **[DEV]** = Claude · **[BOTH]** = joint

Rules of the road: epics ship in order, each leaves a working system, and
**nothing in Epic 2+ starts until Epic 0 has retired R1–R3.**

Legend: `→ FR-n` traces to a requirement in [`prd.md`](prd.md#7-functional-requirements).

---

## Epic 0 — Spikes: de-risk before building anything

Four assumptions can sink this project. Kill them cheaply, first. Timebox the
whole epic — if 0.1 fails, the project changes shape and we should find out in
days, not weeks.

- [ ] **0.1 [DEV+OPS] Capture real Wallet notification strings** → retires **R1**
  - Full spec below. This is a **throwaway** — it will be deleted once the corpus exists.
- [ ] **0.2 [DEV] Verify `actualpy` ↔ `actual-server` on arm64** → retires **R2**
  - Stand up `actual-server` in Docker, pin an exact version
  - From Python, authenticate, open the budget, create an uncleared transaction with an `imported_id`, read it back, delete it
  - Confirm the second write with the same `imported_id` does not duplicate
  - **Exit:** a known-good pinned version pair recorded in `decisions.md`, plus a working script
- [ ] **0.3 [OPS] Measure real memory on the Pi** → retires **R3**
  - 64-bit Pi OS Lite, zram enabled, Docker installed
  - Run `actual-server` + Tailscale, use the budget in a browser for 20 minutes
  - Record steady-state and peak RSS per process; compare with [architecture §4](architecture.md#4-resource-budget)
  - **Exit:** a real number, and a go/no-go on keeping everything on the Zero 2 W
- [ ] **0.4 [OPS] Get one real statement export from each issuer** → retires **R5**
  - Download a genuine CSV/XLS export; note encoding, header row, date format, sign convention
  - Redact and commit as a test fixture
  - Capture the "statement ready" email — exact sender address and subject line
  - **Exit:** enough to author a parsing profile and a statement-detection rule
- [ ] **0.5 [BOTH] Answer the open questions** in [prd.md §11](prd.md#11-open-questions) (Q1–Q4)

### Spike 0.1 spec — the notification collector

A separate, disposable app. It exists only to answer questions we are currently
guessing at. **Build exactly this and nothing more** — every feature added here is
a feature thrown away later.

**In scope**

- `NotificationListenerService` recording, per notification: package, post time,
  notification key, `android.title`, `android.text`, `android.bigText`,
  `android.subText`, the **full list of extras keys present**, and the flags
  (including `FLAG_GROUP_SUMMARY`).
- Local append-only storage of those records.
- Export as JSONL through `ACTION_CREATE_DOCUMENT` (Storage Access Framework) —
  the user picks the destination, so **no storage permission is needed**.
- A capture filter: a small allowlist by default (Wallet candidates + Gmail),
  with a temporary **"capture everything"** toggle for discovering the real
  package name.
- Onboarding that links to the notification-access settings screen and to the
  battery-optimisation exemption.
- A live count of captured events on screen, so you can see it's alive.

**Explicitly NOT in scope** — no parsing, no regex, no amounts, no queue, no
Actual, no bridge, no `deploy/` changes.

**No network. At all.**
The `INTERNET` permission must be **absent from the manifest**. This app reads
every notification on the phone; it should be *provably incapable* of sending
them anywhere. That is a property you can verify by reading one file, and it is
worth more than any assurance in a README.

**Two gotchas that will cost you the corpus if missed**

1. **Use a stable signing key across CI runs.** `assembleDebug` is fine — a
   throwaway needs no release keystore — but GitHub Actions generates a *fresh*
   debug keystore per run by default, and Android refuses to install a build
   signed by a different key over an existing one. Store one debug keystore as a
   base64 repository secret and decode it in the workflow.
2. **App-private storage is destroyed on uninstall.** If you ever have to
   uninstall to install a new build, the corpus goes with it. Export before every
   reinstall, and treat the exported file as the real artefact.

**Privacy.** "Capture everything" will pick up WhatsApp, SMS, email previews —
everything. Use it only briefly to identify the Wallet package, then switch back
to the allowlist and purge what you collected in the meantime.

**Exit criteria — the spike is done when we have**

- [ ] ≥5 real tap-to-pay captures, ideally including a **refund**, a
      **foreign-currency** purchase, an amount **over ₪1,000** (to see the
      thousands separator), and a **long Hebrew merchant name**
- [ ] the confirmed Google Wallet package name
- [ ] which extras field actually carries the amount, the merchant, and the card
      last-4 (if it is present at all)
- [ ] an answer to whether a notification fires on **every** tap
- [ ] one captured Gmail "statement ready" notification, with exact sender and
      subject — this feeds 0.4 and Epic 4 for free
- [ ] the corpus committed as the parser test fixture (redact what you need to)
- [ ] **or**: a documented finding that Wallet does not notify usefully here —
      which changes the project, and is exactly why this spike is first

**Collect over several days.** One evening of taps gives one merchant's format.
Variety is the whole point.

---

## Epic 1 — Pi platform  *(yours, end to end)*

Delivers: a working self-hosted Actual you could use today with manual entry.

**Full step-by-step version with verification commands and gotchas:
[`ops-runbook.md`](ops-runbook.md).** The list below is the index; the runbook is
the thing to actually work through.

- [ ] **1.1** Flash Raspberry Pi OS **Lite 64-bit**, headless, SSH keys only, no password auth
- [ ] **1.2** Enable zram swap; disable unneeded services; set `TZ=Asia/Jerusalem`
- [ ] **1.3** Install Docker + compose plugin. **Do not build images on this box**
- [ ] **1.4** Decide volume placement and record the reasoning — on a Zero 2 W, a good A2 card plus tested backups usually beats fighting USB power (**R6**, [runbook B1](ops-runbook.md#b1--decide-where-the-data-lives))
- [ ] **1.5** Run `actual-server` from compose: pinned tag, named volume, `restart: unless-stopped`, `mem_limit`
- [ ] **1.6** Create the budget file in the browser; note the **sync ID** — the bridge needs it
- [ ] **1.7** Set up the accounts you'll actually use, and note exact names for `AQUEDUCT_CARD_MAP`
- [ ] **1.8** Install Tailscale on Pi and phone; verify the phone reaches Actual from mobile data
- [ ] **1.9** `tailscale cert` for a real TLS certificate on the `ts.net` name
- [ ] **1.10** Nightly backup job: both volumes → encrypted archive → off-box
- [ ] **1.11** **Perform a real restore onto a fresh SD card.** An untested backup is not a backup (**NFR-6**)
- [ ] **1.12** Docker log rotation in `/etc/docker/daemon.json` — before it fills the card
- [ ] **1.13** Backup-failure visibility: break it on purpose and confirm you find out
- [ ] **1.14** `deploy/NOTES.md` in your own words — the artefact that proves 1.11 is repeatable

---

## Epic 2 — Capture and teach mode  *(Android)*

Delivers: the parser corpus — the one asset that cannot be reconstructed later.

- [ ] **2.1 [DEV]** Project skeleton: Kotlin, min SDK 26, Room, WorkManager, Compose
- [ ] **2.2 [DEV]** `NotificationListenerService` + onboarding flow that walks through granting notification access → FR-1
- [ ] **2.3 [DEV]** Persist raw event **before** parsing; drop `FLAG_GROUP_SUMMARY`; treat key updates as updates → FR-1, FR-2
- [ ] **2.4 [DEV]** Content-hash dedup within a 120s window → FR-3
- [ ] **2.5 [DEV]** Bidi/Unicode normaliser + unit tests using real strings from 0.1 → FR-5
- [ ] **2.6 [DEV]** Data-driven pattern engine (versioned JSON) + corpus-backed test suite → FR-4, D10
- [ ] **2.7 [DEV]** Amounts as signed minor units throughout; no floats anywhere → FR-6
- [ ] **2.8 [DEV]** Teach-mode export of the raw corpus → FR-7
- [ ] **2.9 [DEV]** Battery-optimisation exemption prompt in onboarding, with a verification step → NFR-8, **R4**
- [ ] **2.10 [DEV]** GitHub Actions APK build + release attachment → F12
- [ ] **2.11 [OPS]** Sideload, run for a week, report anything the parser missed

---

## Epic 3 — The core loop: capture → bridge → Actual

Delivers: **the actual promise.** Taps appear in Actual by themselves.

- [ ] **3.1 [DEV]** Bridge skeleton: FastAPI, config from env per the [ops contract](architecture.md#13-ops-contract--the-seam-between-lanes)
- [ ] **3.2 [DEV]** `inbox.sqlite` schema + migrations → architecture §5.2
- [ ] **3.3 [DEV]** `POST /v1/events`: bearer auth, validation, idempotent insert, fast return → FR-12, FR-13, FR-14
- [ ] **3.4 [DEV]** `GET /healthz` with inbox depth, oldest-pending age, last flush, Actual reachability → FR-28
- [ ] **3.5 [DEV]** Flush worker: batched, short-lived Actual sessions on a schedule → FR-15, D4
- [ ] **3.6 [DEV]** Write taps as uncleared + `imported_id` + `#wallet-auto`, no category → FR-16, FR-17
- [ ] **3.7 [DEV]** Card-last4 → account mapping, with a default fallback
- [ ] **3.8 [DEV]** Android sync worker: batching, backoff, ack-driven state, never-drop → FR-8, FR-9, FR-10
- [ ] **3.9 [DEV]** Token provisioning by QR into `EncryptedSharedPreferences` → FR-11
- [ ] **3.10 [DEV]** Review screen: list events, fix parse failures, re-queue, reject false positives → F4
- [ ] **3.11 [DEV]** Dockerfile + CI cross-build for `linux/arm64`, published to GHCR
- [ ] **3.12 [OPS]** Add the bridge to compose; wire env, volume, healthcheck, memory limit
- [ ] **3.13 [BOTH]** **End-to-end proof:** make a real purchase, watch it appear in Actual unaided
- [ ] **3.14 [BOTH]** Prove resilience: stop `actual-server`, make purchases, restart, confirm nothing was lost → NFR-4

---

## Epic 4 — Statement detection and the nag

Delivers: you stop forgetting to import.

- [ ] **4.1 [DEV]** Statement-ready rules (issuer → sender + subject pattern), authored from 0.4 → FR-18
- [ ] **4.2 [DEV]** Extend the listener to match mail notifications → FR-18
- [ ] **4.3 [DEV]** `statement_watch` state on device; `POST /v1/statements/pending`
- [ ] **4.4 [DEV]** `statement_state` table + `GET /v1/statements/state` on the bridge
- [ ] **4.5 [DEV]** Ongoing, non-dismissable notification naming issuer and period → FR-19, D6
- [ ] **4.6 [DEV]** Periodic state poll; clear the notification only on bridge-confirmed ingest → FR-20
- [ ] **4.7 [DEV]** Explicit dismissal path with a recorded reason → FR-20
- [ ] **4.8 [BOTH]** Verify against a real statement email

---

## Epic 5 — Statement ingest and reconciliation

Delivers: a ledger that matches the bank to the agora.

- [ ] **5.1 [DEV]** Profile schema + loader (encoding, header row, date format, sign convention, column map) → architecture §3.7
- [ ] **5.2 [DEV]** Profiles for each issuer from 0.4, with redacted sample fixtures → **R5**
- [ ] **5.3 [DEV]** Reject-loudly validation: wrong shape → 422, nothing written → FR-21
- [ ] **5.4 [DEV]** `POST /v1/statements/{issuer}/{period}/upload` + a minimal upload page
- [ ] **5.5 [DEV]** Write statement rows as cleared transactions → FR-22
- [x] **5.6 [DEV]** Matching algorithm: amount-equal + date window + same currency → FR-23 ✅ `bridge/aqueduct/reconcile.py`
- [x] **5.7 [DEV]** Merge on unique match; carry over richer payee; delete the placeholder → FR-24 ✅
- [x] **5.8 [DEV]** Flag on ambiguity; **never** auto-merge multiple candidates → FR-25 ✅ strengthened to *mutual* uniqueness
- [x] **5.9 [DEV]** Currency-mismatch path: no amount match, flag for review → FR-26 ✅
- [x] **5.10 [DEV]** Orphan sweep: unmatched taps past the age threshold become exceptions → FR-27 ✅
- [ ] **5.11 [DEV]** `reconciliation_log` append-only audit trail
- [x] **5.12 [DEV]** Reconciler test suite ✅ 35 tests, including two invariants over 400 generated scenarios each
- [ ] **5.13 [BOTH]** **Full-cycle proof:** ingest a real statement, confirm balance matches exactly and zero duplicates → **G3**

---

## Epic 6 — Hardening

Delivers: something you can stop thinking about.

- [ ] **6.1 [DEV]** On-device watchdog: notification access still granted? events seen recently? → FR-29, **R4**
- [ ] **6.2 [DEV]** Warning notification when capture appears to have stopped
- [ ] **6.3 [DEV]** Structured logging with secrets redacted; log rotation inside `/data`
- [ ] **6.4 [DEV]** Rate limiting + payload size caps on ingest → NFR-5
- [ ] **6.5 [DEV]** Raw-corpus retention policy on device (Q4) → privacy
- [ ] **6.6 [OPS]** Monitor `/healthz`; alert on inbox depth or stale last-flush
- [ ] **6.7 [OPS]** **7-day soak:** watch RSS and inbox depth; confirm no drift, no OOM → NFR-1, **R3**
- [ ] **6.8 [OPS]** Second restore drill, now including the bridge `/data` volume
- [ ] **6.9 [OPS]** Document the upgrade procedure for `actual-server` + `actualpy` as a **joint** version bump → **R2**
- [ ] **6.10 [BOTH]** Run the [success criteria](prd.md#10-success-criteria) over one full statement cycle and record the numbers honestly

---

## Deferred to v2

- IMAP statement detection as a fallback for D5
- `israeli-bank-scrapers` as an authoritative auto-pull
- FX rate lookup for foreign-currency auto-matching
- Additional cards and accounts beyond the initial mapping
- Ledger-side spending alerts (budget category over threshold)

---

## Critical path

```
0.1 ──┬─► 2.5 ─► 2.6 ─► 3.8 ─┐
      │                       ├─► 3.13 ─► 4.x ─► 5.13 ─► 6.10
0.2 ──┴─► 3.5 ─► 3.6 ────────┤
0.3 ─────► 1.x ─► 3.12 ──────┘
0.4 ─────► 4.1, 5.2
```

**0.1 is the tightest constraint.** Nothing about parsing, and therefore nothing
about the core loop, is real until we have seen the actual strings.
