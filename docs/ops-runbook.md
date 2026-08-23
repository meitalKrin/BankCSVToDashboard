# Ops runbook — your lane

**This is your side of the project, start to finish.** Nothing here needs Android
or Python knowledge. Work top to bottom; each checkpoint has a **Verify** step
with a real command, because "I think it worked" is not a checkpoint.

If you've never done this before: that's what this document is for. The stages
are ordered so you always have a working system, and so the scary parts
(backups, restore) come *before* you have data you'd cry about losing.

**Rough timing:** Stages A–D are one focused evening. E is 30 minutes. F is the
one that takes real effort and is the one that actually matters.

---

## What "up to standard" means here

Six things separate a hobby box from something you can trust with your finances.
Every checkpoint below serves one of them:

1. **Reproducible** — you can rebuild the whole thing from your own notes.
2. **Pinned** — no `latest` tags. You know exactly what version is running.
3. **Durable** — data survives reboots, power cuts, and a dead SD card.
4. **Restorable** — you have *performed* a restore, not merely configured a backup.
5. **Contained** — restart policies, memory limits, log rotation. One failure
   doesn't cascade.
6. **Private** — nothing reachable from the public internet, no secrets in git.

You're done when all six are true and you can demonstrate each.

---

## Stage A — the box exists and you can reach it

### A1 · Flash Raspberry Pi OS Lite, 64-bit

**Goal.** A headless Pi you can SSH into.

**Do.** Raspberry Pi Imager → *Raspberry Pi OS Lite (64-bit)*. Before writing,
open the settings gear and preconfigure: hostname (e.g. `aqueduct`), your SSH
**public key** (not a password), WiFi credentials and country, locale and
timezone `Asia/Jerusalem`.

**Verify.**
```bash
ssh <you>@aqueduct.local
getconf LONG_BIT     # must print 64
uname -m             # must print aarch64
```

**Gotchas.** *Lite* means no desktop — that's deliberate, a desktop would eat
most of your RAM. If `LONG_BIT` says 32 you flashed the wrong image; redo it now
rather than discovering it when a container won't start. The Zero 2 W is 2.4 GHz
WiFi only — a 5 GHz-only network won't appear.

### A2 · Basic hardening and updates

**Goal.** Key-only SSH, patched system.

**Do.** `sudo apt update && sudo apt full-upgrade`. Confirm your key works,
*then* disable password auth in `/etc/ssh/sshd_config`. Install
`unattended-upgrades` for security patches.

**Verify.**
```bash
sudo sshd -T | grep -i passwordauthentication   # → passwordauthentication no
systemctl is-enabled unattended-upgrades        # → enabled
```

**Gotcha.** Test your key login in a *second* terminal before disabling
passwords. Locking yourself out means re-flashing.

### A3 · Timezone

**Goal.** Correct dates on transactions.

**Verify.**
```bash
timedatectl    # Time zone: Asia/Jerusalem, "System clock synchronized: yes"
```

**Why it matters.** A transaction's date comes from a timestamp. A wrong
timezone silently puts late-evening purchases on the wrong day, which shows up
later as reconciliation mismatches you'll waste an hour chasing.

### A4 · zram swap, and kill the SD swapfile

**Goal.** Compressed in-RAM swap. On 512 MB this is the difference between
comfortable and OOM.

**Do.** `sudo apt install zram-tools`, configure it (roughly half of RAM as the
zram device is a sane start), and **disable the default SD-card swapfile**:
`sudo systemctl disable --now dphys-swapfile`.

**Verify.**
```bash
zramctl              # a /dev/zram0 device exists
swapon --show        # shows /dev/zram0 and NOT /var/swap
free -h              # Swap row is non-zero
```

**Gotcha.** Swapping to the SD card is slow *and* burns write cycles on the card
holding your budget. zram lives in RAM — no wear, and compression buys real
capacity. This is the single highest-value tweak on this box.

---

## Stage B — storage

### B1 · Decide where the data lives

**Goal.** A conscious decision, written down.

Two honest options on a Zero 2 W:

| Option | Good | Bad |
| --- | --- | --- |
| **Quality A2 / high-endurance microSD** *(recommended while learning)* | Simple, no adapters, no power issues | SD cards do die; you are fully dependent on Stage F |
| USB SSD or good flash drive | Much better write endurance | The Zero 2 W has one micro-USB data port, needs an OTG adapter, and the power budget is tight — a powered hub is safer |

**Recommendation: a good SD card plus genuinely disciplined backups.** You've
said you plan to upgrade the Pi later — revisit this then, when you have proper
USB ports and headroom. Wear is a *slow* risk; a missing backup is an
*instant* one. Spend your effort on Stage F.

**Verify.** Write your choice and reasoning in your notes file (see G3).

**If you do add USB storage**, mount by UUID in `/etc/fstab`, never by
`/dev/sda1` — device names shuffle between boots.
```bash
lsblk -f            # read the UUID
findmnt /srv/aqueduct
sudo reboot         # then check findmnt again — it must survive
```

---

## Stage C — Docker

### C1 · Install Docker and the compose plugin

**Do.** `curl -fsSL https://get.docker.com | sh`, then add yourself to the
`docker` group and log out and back in.

**Verify.**
```bash
docker run --rm hello-world                      # works WITHOUT sudo
docker version --format '{{.Server.Arch}}'       # → arm64
docker compose version                           # the plugin, not docker-compose
```

### C2 · Log rotation — do this before you forget

**Goal.** Container logs can't fill the card.

**Do.** Create `/etc/docker/daemon.json`:
```json
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
```
then `sudo systemctl restart docker`.

**Verify.**
```bash
docker info | grep -i "logging driver"
```

**Why.** Unbounded JSON logs quietly filling a full SD card is one of the most
common ways a home server dies. Ten minutes now.

### C3 · Learn the golden rule

**Never build a container image on this Pi.** `docker pull` only. A Gradle or
pip build will exhaust 512 MB and either OOM or thrash the card for an hour.
Images for this project are cross-built in CI for `linux/arm64` and pulled here.

---

## Stage D — Actual Budget running

### D1 · Write your first compose file

**Goal.** `actual-server` running properly — not just running.

Create `deploy/docker-compose.yml`. It must have all five of these:

- a **pinned image tag** — a real version, never `latest`
- a **named volume** for budget data
- `restart: unless-stopped`
- a `mem_limit` (start around `256m` and adjust after you measure)
- a `healthcheck`

**Verify.**
```bash
docker compose up -d
docker compose ps            # State=running, and Status shows (healthy)
docker compose logs --tail=50
```
Then open `http://aqueduct.local:5006` from your laptop.

**Gotchas.** Don't assume the image contains `curl` for your healthcheck —
`docker compose exec actual-server which wget curl` and find out. Checking
rather than assuming is the habit worth building here. And if the container
restarts in a loop, `docker compose logs` is always your first move.

### D2 · Prove the data is actually persistent

**Goal.** Confirm you understand volumes. This is the concept people most often
get wrong, and getting it wrong here means losing your budget.

**Do.** Set a server password, create a budget, add a transaction by hand. Then:
```bash
docker compose down          # NOT "down -v" — that deletes volumes
docker compose up -d
```

**Verify.** Your transaction is still there. If it isn't, your data is inside the
container instead of a volume — fix it now, before there's real data.

**Note down:** the budget's **sync ID** (in Actual's settings). The bridge needs
it later.

### D3 · Create your real accounts

Create the accounts matching your actual cards. **Write the names down exactly**
— they go into `AQUEDUCT_CARD_MAP` later, and a typo there means transactions
landing in the wrong account.

---

## Stage E — network

> **"Isn't Tailscale too heavy for a Zero 2 W?"** No — **install it.** It costs
> roughly 30–50 MB of 512 MB. That's real but it is not the problem, and it buys
> valid TLS (which removes an entire class of Android networking pain) plus
> SSH-from-anywhere.
>
> I listed "drop Tailscale" first among the fallbacks if the memory measurement
> comes back tight, which made it look like a recommendation. It isn't — it's
> rung 3 of 5 on the ladder in
> [architecture §4](architecture.md#if-spike-03-comes-back-tight), after tuning
> zram and memory limits.
>
> And the reason it must go in **now**: you cannot find out whether it fits by
> leaving it out. Build the real system, measure it in G4, *then* decide whether
> anything needs to come out.

Tailscale is also what lets you SSH into the Pi from anywhere, which you will
appreciate a lot while learning the ops side.

### E1 · Tailscale on Pi and phone

**Verify.** Turn WiFi **off** on your phone, then reach Actual over mobile data
via the Pi's Tailscale name. If that works, the transport is solved.

### E2 · Real TLS

**Do.** `tailscale cert <your-machine>.<tailnet>.ts.net` and configure it.

**Verify.** Your phone browser shows a valid certificate, no warning.

**Why bother.** It isn't cosmetic. Android blocks plaintext HTTP by default and
distrusts self-signed certificates — a real certificate means the app needs zero
special network configuration. This is Tailscale earning its ~30 MB.

### E3 · Prove nothing is exposed

**Verify.**
```bash
ss -tlnp             # check WHICH address each service listens on
```
Services should be on `127.0.0.1` or the tailnet address — **not** `0.0.0.0`
unless you meant it. Then open your router's admin page and confirm there are
**no port forwards** to the Pi.

---

## Stage F — backups · the stage that actually matters

Everything above is recoverable in an evening. The budget data is not. Do this
stage properly and the rest of the project becomes low-stakes.

### F1 · A backup script

**Goal.** A nightly encrypted archive, off this box.

**Approach.** Keep it simple and obviously correct: stop the container, tar the
volume, start it again, encrypt, copy off-box. Seconds of downtime at 3am is a
fine price for a guaranteed-consistent copy — don't get clever with hot copies of
a live SQLite file.

Use `age` for encryption (`sudo apt install age`) — one command, one keyfile,
much less to get wrong than GPG. Encrypt **before** it leaves the Pi, so wherever
it lands only ever sees ciphertext. Then copy off-box via `rclone` to cloud
storage, `scp` to another machine, or both.

Run it from a systemd timer or cron.

**Verify.**
```bash
systemctl list-timers | grep -i backup    # or: crontab -l
# run it manually once:
ls -lh /path/to/backups/                  # non-trivial size
file backup-*.age                         # not readable plaintext
```

**Store the age key somewhere that is not the Pi.** An encrypted backup whose
only key was on the dead SD card is not a backup.

### F2 · Rotation

Keep e.g. 7 daily, 4 weekly. Verify old ones actually get deleted — a backup job
that fills the disk takes the server down with it.

### F3 · 🔴 The restore drill — the real checkpoint

**Nothing above counts until you have done this.**

**Do.** Take a backup. Then simulate the disaster properly: on a spare SD card,
or at minimum in a completely fresh directory with a *new empty volume*, restore
from the encrypted archive and bring Actual up.

**Verify.** You can log in and see the transaction you created in D2.

**Then write down how long it took and what tripped you up.** That's your real
recovery time, and next time you'll be doing this while stressed.

**Gotchas people hit here.** The key wasn't accessible. The archive had wrong
ownership or permissions inside. The restore procedure was never written down and
had to be reinvented. The backup had silently been capturing an empty directory
for weeks. All of these are only ever found by actually restoring.

### F4 · Know when backups fail

A backup that fails silently for three months is worse than no backup, because
you *believed* you had one. Make failure visible: have the script write a
timestamp file on success and check its age, or push a notification on failure.

**Verify.** Break it on purpose — rename the target directory — and confirm you
find out.

---

## Stage G — operating it

### G1 · Watch the health endpoint

Once the bridge exists it exposes `/healthz` with inbox depth and last successful
write. Poll it, alert on stale. Until then, watch `docker compose ps` and get
comfortable with `docker stats` and `journalctl`.

### G2 · A written update procedure

**Goal.** Upgrading doesn't become an adventure.

Write down: how you bump a pinned tag, how you verify afterwards, and **how you
roll back**. Note that `actual-server` and the bridge's `actualpy` are
version-coupled — they get bumped and tested together, never one alone.

### G3 · Your own notes file

**This is what makes the difference between "it works" and "up to standard."**

Keep `deploy/NOTES.md` in the repo, written in your own words: what you did, what
broke, what the fix was, what the restore procedure is. Not copied from here —
*yours*. If you can hand it to yourself in eight months and rebuild the box, your
lane is done.

### G4 · Soak it

Leave it running a week. Watch memory with `docker stats` and `free -h`. Check
nothing was OOM-killed:
```bash
dmesg -T | grep -i -E "oom|killed process"
```
This is also spike 0.3 — the numbers you collect here decide whether the Zero 2 W
holds the full stack.

---

## Definition of done — your lane

- [ ] 64-bit Lite OS, key-only SSH, unattended security updates
- [ ] zram active, SD swapfile disabled
- [ ] Docker + compose working rootless-to-you, log rotation configured
- [ ] `actual-server` on a **pinned tag**, named volume, restart policy, memory limit, healthcheck
- [ ] Data proven to survive `down` / `up`
- [ ] Tailscale working from mobile data with WiFi off, with a valid TLS certificate
- [ ] No public exposure — verified at the router, not assumed
- [ ] Nightly encrypted backup running off-box, with the key stored elsewhere
- [ ] **A restore you have actually performed**, and timed
- [ ] Backup failure is visible to you — tested by breaking it
- [ ] `deploy/NOTES.md` written in your own words
- [ ] A week of soak with no OOM kills, and real memory numbers recorded

---

## Common beginner mistakes

| Mistake | What happens |
| --- | --- |
| `latest` tags | An unattended pull changes your version. Something breaks and you can't tell what changed |
| `docker compose down -v` | The `-v` deletes volumes. This is how people delete their data |
| Data in the container, not a volume | Everything vanishes on the next `docker compose up` after an image change |
| Secrets committed to git | `.env` is gitignored; keep it that way. Commit `.env.example` instead |
| No log rotation | Full disk, dead server, weeks later |
| Configuring a backup and never restoring | You find out it was broken on the worst possible day |
| Backup key stored on the machine being backed up | Encrypted archives you cannot open |
| Building images on the Pi | OOM, or an hour of thrashing the SD card |
| Fixing things by SSH without writing it down | Works today, unreproducible in three months |

---

## When you're stuck

1. `docker compose logs --tail=100 <service>` — nearly always says what's wrong
2. `docker compose ps` — is it running, restarting, or unhealthy?
3. `free -h` and `dmesg -T | grep -i oom` — on this box, suspect memory early
4. `ss -tlnp` — is it listening where you think it is?
5. `systemctl status <unit>` / `journalctl -u <unit> -n 50` for host services

Then bring me the output — I can read it with you. Getting stuck is not a
failure state, it's the actual work.
