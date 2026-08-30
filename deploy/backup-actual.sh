#!/usr/bin/env bash
#
# Nightly backup of the Actual Budget volume.
#
# Stops the container, streams the volume through tar into age, starts it again.
# The plaintext archive is never written to the SD card — tar's output goes
# straight into age over a pipe, so only ciphertext ever lands on disk.
#
# Decryption needs the age PRIVATE key, which deliberately does not live on this
# machine. If you cannot find that key, you do not have backups.
#
set -euo pipefail

DEPLOY=/home/mei/deploy
OUT=/home/mei/backups
VOL=/var/lib/docker/volumes/deploy_actual-data/_data
KEEP=7

# age PUBLIC key. Safe to commit — it can only encrypt.
PUB="age1k2qjf426926w0y6vaslgxxkxqp2dhuears8myaesl8pfvnvd4ufs53l5cu"

STAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE="$OUT/actual-$STAMP.tar.gz.age"

mkdir -p "$OUT"

# Whatever happens below, the service comes back up.
trap 'docker compose -f "$DEPLOY/docker-compose.yml" start >/dev/null 2>&1 || true' EXIT

# A consistent copy beats a clever one. Seconds of downtime at 03:00 is a fine
# price for never having to wonder whether the SQLite file was mid-write.
docker compose -f "$DEPLOY/docker-compose.yml" stop

tar -czf - -C "$VOL" . | age -r "$PUB" -o "$ARCHIVE"

# Rotation. A backup job that fills the disk takes the server down with it.
ls -1t "$OUT"/actual-*.tar.gz.age 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --

# Heartbeat for the dead-man's switch. Absence of a fresh timestamp is the alarm.
date -Is > "$OUT/last-success"

echo "ok: $(basename "$ARCHIVE") ($(du -h "$ARCHIVE" | cut -f1))"
