# Decision log — Aqueduct

Each entry: what was decided, why, and **what we gave up**. Settled decisions are
followed, not re-argued — but if the reasoning turns out to be wrong, supersede
the entry rather than quietly drifting.

---

## D1 — Notification scraping is the primary capture mechanism

**Decided.** Capture spending from Google Wallet notifications on Android.

**Why.** Actual's supported bank-sync providers (GoCardless, SimpleFIN) have
effectively no Israeli coverage. The realistic alternatives were monthly CSV
only (too slow to be a budget), website scraping with stored banking credentials
(large security surface), or notifications. Notifications are the only source
that is both *instant* and *credential-free*.

**Given up.** Coverage. Only NFC taps from this phone are captured — not card
swipes, online purchases, standing orders or transfers. This is why D2 exists.

---

## D2 — Taps are provisional; the statement is authoritative

**Decided.** Tap-derived transactions are written **uncleared**, tagged
`#wallet-auto`, with `imported_id = wallet:<uuid>`. Statement-derived
transactions are written **cleared** and win every disagreement.

**Why.** A notification reports an *authorisation*, not a settlement. Tips, FX
conversion, holds and partial refunds all settle differently. Treating the two
sources as equals produces a ledger that is subtly wrong and impossible to
audit. Making provenance explicit costs nothing now and makes reconciliation
possible at all.

**Given up.** Nothing meaningful. This is the cheapest decision in the document
and the one with the largest downside if skipped.

---

## D3 — The phone talks only to the bridge, never to Actual

**Decided.** The Android app has no knowledge of Actual's API or data model.

**Why.** Actual's client library is Node-based, heavy and version-coupled to the
server. Putting it behind the bridge means an Actual upgrade is a bridge concern,
not an app-release-and-sideload concern. It also keeps the Actual password off
the phone.

**Given up.** The bridge becomes a hard dependency — but it already was, since it
owns reconciliation.

---

## D4 — Ingest is decoupled from writing (inbox pattern)

**Decided.** `POST /v1/events` writes to a local SQLite inbox and returns. A
separate worker batches into Actual every 5 minutes.

**Why.** Two reasons, both load-bearing. **Memory:** `actualpy` downloads the
budget file and works on it locally; holding a session open permanently would
cost 100 MB+ on a 512 MB box for a process idle almost all the time. **Robustness:**
the phone gets a fast, reliable ack that doesn't depend on Actual being healthy,
so Actual can be down for a day without a single lost event.

**Given up.** Up to 5 minutes of extra latency. Irrelevant against a budget
horizon of a month.

---

## D5 — "Statement ready" is detected from the phone's mail notification, not IMAP

**Decided.** The same `NotificationListenerService` matches Gmail notifications
against per-issuer sender/subject rules.

**Why.** We are building a notification listener anyway. Reusing it means **zero
new credentials**: no Gmail app password, no OAuth flow, no mailbox access stored
on a Pi that lives in a cupboard. Google has also been progressively restricting
app passwords, so an IMAP design carries ongoing maintenance risk.

**Given up.** Robustness. It requires Gmail notifications enabled for that sender
and the phone to be on and connected. Notification text may be truncated — fine
for detecting *that* a statement exists. If this proves flaky, IMAP on the Pi is
the v2 fallback and slots in behind the same `statement_state` table.

*(This decision came from the owner during design and replaces the "CSV import"
scope option originally offered — it is a better fit: it solves forgetting, which
is the actual failure mode, rather than adding another import path.)*

---

## D6 — The nag notification is ongoing and cleared only by real ingest

**Decided.** While a statement is pending, an ongoing (non-dismissable)
notification names the issuer and period. It clears when the bridge confirms
ingest, or on an explicit dismissal with a recorded reason.

**Why.** The failure mode being designed against is human forgetfulness. A
dismissable notification is a notification you swipe away at a red light and
never think about again. Requiring the *bridge* to confirm ingest means the
notification cannot be cleared by anything except the thing actually getting done.

**Given up.** It will be annoying. That is the entire point.

---

## D7 — Statement CSV is ingested by the bridge, not by Actual's importer

**Decided.** Upload the statement to the bridge, which parses, reconciles, then
writes to Actual.

**Why.** Reconciliation has to happen *between* parsing and writing. If the CSV
goes straight into Actual's own importer, the pending taps are already
duplicated by the time anything could match them, and we'd be reduced to a
delete-duplicates-afterwards cleanup pass — which is exactly the fragile,
trust-destroying behaviour the whole design is trying to avoid. Owning the parse
step also lets us handle Israeli issuer encoding quirks in Python, where they can
be unit-tested against real sample files.

**Given up.** A second place to upload things, and we take on CSV parsing
ourselves. Worth it — and the repo was named `BankCSVToDashboard` for a reason.

**Alternative if this proves annoying:** import via Actual's UI and run the
reconciler as a post-pass. Strictly worse, but it is a real fallback.

---

## D8 — Categorisation is delegated to Actual's Rules engine

**Decided.** The bridge sets payee and never sets a category.

**Why.** Actual already has a good rules engine that the owner will be using
interactively anyway. Building a second categorisation system that competes with
it would produce two sources of truth and endless "why did it pick that".

**Given up.** Nothing. This is strictly less code and a better result.

---

## D9 — Tailscale for transport; the Pi is never internet-exposed

**Decided.** WireGuard mesh between phone and Pi. Bridge binds to loopback and
the tailnet interface only. `tailscale cert` provides real TLS for the `ts.net`
name.

**Why.** Cloudflare Tunnel or port-forwarding would put a complete record of
personal finances on the public internet behind a single static token. Tailscale
gives near-realtime reachability with no public attack surface and no
certificate-pinning workarounds.

**Given up.** One extra daemon (~25–40 MB, which matters at 512 MB) and a
dependency on a third-party coordination service. The durable phone-side queue
means a Tailscale outage delays events rather than losing them.

---

## D10 — Parse patterns are versioned data, not code

**Decided.** Notification patterns live in a versioned JSON resource with a
committed corpus of real captured strings as the test fixture.

**Why.** We cannot know today what Google Wallet posts in Hebrew, and it will
change without warning. Data-driven patterns mean a fix is an edit plus a test
case, and `parser_version` on every stored event lets us reprocess the raw corpus
when a pattern improves.

**Given up.** Slightly more indirection than a hard-coded regex.

---

## D11 — Teach mode ships first, as a throwaway

**Decided.** Before any real capture pipeline, ship a build that only records raw
notification text and lets it be exported.

**Why.** R1 — not knowing the real notification strings — is the single risk that
can kill the project outright, and it is unresolvable by reasoning. It's also
possible that Wallet posts no useful notification at all on this device/issuer
combination, in which case we need to know *now*, before building a bridge, a
reconciler and a CSV parser for a data source that doesn't exist.

**Given up.** A few days before the "real" work starts. Cheap insurance.

---

## D12 — Ops is the owner's lane, bounded by a written contract

**Decided.** The owner builds and runs the Pi, Docker, networking and backups.
Claude writes the Android app and the Python bridge. The seam is the ops contract
in [`architecture.md` §13](architecture.md#13-ops-contract--the-seam-between-lanes).

**Why.** The owner wants to learn infrastructure and has no interest in Android
or Python. A written contract — image, ports, env vars, volumes, healthcheck —
means neither side has to read the other's code.

**Given up.** Some integration friction at the boundary. Mitigated by keeping the
contract explicit and treating a gap in it as a documentation bug rather than
something to work around.

---

## Rejected

| Option | Why not |
| --- | --- |
| GoCardless / SimpleFIN bank sync | No meaningful Israeli coverage |
| `israeli-bank-scrapers` in v1 | Requires storing credentials that can move money — a categorically larger blast radius. Strong v2 candidate once the core works |
| Google Sheets as an intermediary | An extra cloud hop, an OAuth flow, and a second source of truth, in exchange for nothing |
| `actual-http-api` (Node REST wrapper) | Adds a whole Node runtime to a 512 MB box just to avoid using a Python library |
| Cloudflare Tunnel / port-forwarding | Public exposure of complete personal financial data |
| Firebase Cloud Messaging for the nag | A Google Cloud project and push infrastructure to replace a periodic poll over an already-existing private network |
| Categorising in the bridge | Competes with Actual's rules engine; two sources of truth |
| Play Store distribution | Play policy is hostile to notification-access apps, and this is a single-user personal tool |
