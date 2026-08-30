# Spike 0.1 — the notification collector

A **throwaway** Android app whose entire job is to answer the question the rest
of the project is currently guessing at: *what does Google Wallet actually post
when you tap to pay?*

It records raw notification text and exports it. It does not parse, match,
queue, sync, or know that Actual Budget exists — see
[`docs/backlog.md` → Spike 0.1 spec](../docs/backlog.md#spike-01-spec--the-notification-collector),
which is the binding scope for everything in this directory. When the corpus
exists, this directory gets deleted.

## No network, by construction

`android.permission.INTERNET` is **absent** from
[`app/src/main/AndroidManifest.xml`](app/src/main/AndroidManifest.xml). This app
reads every notification on the phone, so it should be *provably incapable* of
sending them anywhere — a property you can check by reading one file rather than
by trusting a sentence in a README.

CI re-checks it against the built APK on every run (`aapt2 dump permissions`),
because a library manifest can add a permission during the merge, and the file
you install is the one that matters.

## What it captures

Per notification, verbatim, with no interpretation:

| Field | Source |
| --- | --- |
| `package` | `StatusBarNotification.packageName` |
| `posted_at_utc` | `StatusBarNotification.postTime` |
| `notification_key` | `StatusBarNotification.key` |
| `title` / `text` / `big_text` / `sub_text` | `EXTRA_TITLE`, `EXTRA_TEXT`, `EXTRA_BIG_TEXT`, `EXTRA_SUB_TEXT` |
| `extras_keys` | **every** key present in the extras bundle, not just the four read above |
| `flags`, `flags_decoded`, `group_summary` | `Notification.flags`, including `FLAG_GROUP_SUMMARY` |
| `id`, `captured_at_utc` | assigned on insert |

`extras_keys` is the field that earns its place: if the amount or the card
last-4 lives in a key nobody thought to read, this is how we find out.

Group summaries are captured **with** their flag rather than dropped — dropping
them is Epic 2's job, and doing it here would hide the evidence for how Wallet
groups its notifications.

Export format is JSONL, one record per line, UTF-8. Sample line (invented — the
real shapes are what the spike is for):

```json
{"id":1,"captured_at_utc":1756557600123,"package":"com.example","posted_at_utc":1756557600000,"notification_key":"0|com.example|123|null|10123","title":"…","text":"…","big_text":null,"sub_text":null,"extras_keys":["android.title","android.text"],"flags":16,"flags_decoded":["FLAG_AUTO_CANCEL"],"group_summary":false}
```

## One-time setup: the signing key

**Do this before the first build**, or the workflow will compile and then stop
without publishing anything.

GitHub Actions generates a *fresh* debug keystore on every run, and Android
refuses to install a build signed by a different key over an existing one. That
would mean uninstalling to upgrade — and uninstalling destroys the captured
corpus. So one keystore is held as a repository secret and reused by every run.

1. Take the `debug.keystore` base64 handed to you alongside this branch.
2. Repository → **Settings → Secrets and variables → Actions → New repository
   secret**.
3. Name it `DEBUG_KEYSTORE_B64`, paste the base64 as the value, save.
4. Re-run the workflow.

The keystore is a *debug* keystore with the standard passwords
(`android` / `androiddebugkey`). It carries no security weight — sideloaded, no
Play Store, no network. It matters only because the *signature must not change*.
It is deliberately not committed; keep your copy somewhere you will still have
it in a month.

The build prints the key's SHA-256 on every run. If that fingerprint ever
changes, the next APK will not install over the previous one.

## Getting the APK onto the phone

Push to this branch (or run the workflow manually). When it goes green:

- a **pre-release** is published with the `.apk` attached — open the release page
  in the phone's browser, tap the `.apk`, allow installs from unknown sources;
- the same APK is also attached to the run as an artifact, which downloads as a
  zip and is the less convenient path.

## Using it

1. **Grant notification access** — the button on the main screen opens the right
   settings page. Nothing is captured until this is on.
2. **Grant the battery-optimisation exemption** — the second button. Without it
   Android will eventually stop waking the listener, and you will silently lose
   captures. The screen shows the live state of both.
3. **Find the real Wallet package.** Turn on **capture everything**, tap to pay
   once, and read the per-package counts on screen. The package that appears at
   the moment you tapped is the answer.
4. **Switch capture-everything back off**, add the confirmed package to the
   allowlist, and **purge non-allowlisted** — capture-everything picks up
   WhatsApp, SMS and email previews, and none of that should sit on the phone
   any longer than the minute it takes to identify Wallet.
5. **Collect over several days.** One evening of taps gives one merchant's
   format; variety is the entire point. Aim for the list in the spec: a refund,
   a foreign-currency purchase, something over ₪1,000 (to see the thousands
   separator), a long Hebrew merchant name, and one Gmail "statement ready"
   notification.
6. **Export before you uninstall anything.** App-private storage is destroyed
   with the app. The exported JSONL is the real artefact, not the phone.

## Then what

The exported JSONL is the input to
[backlog 2.5 / 2.6](../docs/backlog.md#epic-2--capture-and-teach-mode-android) —
the bidi normaliser and the pattern engine — and it becomes the committed parser
test fixture. Redact what needs redacting before committing it.

A negative result is also a result: if Wallet turns out not to notify usefully
here, that finding changes the shape of the project, and finding it out now is
exactly why this spike is first.

## Building locally

You do not need to, and the project deliberately assumes you will not. If you
ever want to: JDK 17 and an Android SDK with API 35, then `./gradlew
assembleDebug`.
