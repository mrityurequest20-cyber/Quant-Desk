#!/usr/bin/env bash
# Decrypt a private Kite tick artifact on the owner's own machine (docs/ml/KITE_TRIAL.md). The ticks are licensed to the subscriber, so the recorder uploads them encrypted with the
# owner's Kite API secret; this is the reverse. Usage:
#   KITE_DATA_SECRET=<your Kite API secret> deploy/kite-decrypt.sh kite_raw_1.tar.enc ./kite_day [sha256 shown in the run's summary]
# With the sha256 the file is checked first (CBC has no integrity check of its own, so a wrong key or a changed file would otherwise just fail or give junk).
# (download the artifact from the workflow run's page, unzip it, then run this). The secret is read from the environment and never written anywhere.
set -euo pipefail
[ $# -ge 2 ] && [ $# -le 3 ] || { echo "usage: KITE_DATA_SECRET=... $0 <file.tar.enc> <output folder> [sha256]"; exit 2; }
[ -n "${KITE_DATA_SECRET:-}" ] || { echo "set KITE_DATA_SECRET to your Kite API secret"; exit 2; }
if [ -n "${3:-}" ]; then echo "$3  $1" | sha256sum -c - || { echo "the file does not match the digest in the run summary; refusing"; exit 1; }; fi
mkdir -p "$2"
openssl enc -d -aes-256-cbc -pbkdf2 -in "$1" -pass env:KITE_DATA_SECRET | tar -C "$2" -xf -
echo "decrypted into $2"
