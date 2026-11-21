"""A tape of every quote a live feed sends to the relay (audit K-20, E-05): Fyers' MCX and currency quotes, books and option chains, and Angel One's currency
quotes, existed only in the relay's latest snapshot, so nobody could study, replay or train on the data AUTO decided on, and every MCX option series that expired
was lost for good. `TeePusher` wraps the relay's pusher: each update the feed hands it is also written to the tape, then passed on unchanged.

Rows: the time it was handed over (ms since the epoch), the name, and the whole quote as compact JSON (price, bid, ask, sizes, volume, open interest, change,
segment, and the five-level book when the feed sent one): lossless, so nothing has to be decided now about what a study will need. Written as gzip CSV chunks
of FLUSH_ROWS rows. The data is the broker's, licensed to the subscriber, and this repository is public: the workflow encrypts the tape before it keeps it and
never uploads it in the clear. Nothing here can stop or slow the feed: a tape error is counted, never raised."""
from __future__ import annotations

import csv
import gzip
import json
import threading
import time
from pathlib import Path

FLUSH_ROWS = 20_000                    # rows per chunk (about 1-2 MB compressed): a crash loses at most this many
MAX_PENDING = 200_000                  # rows held when the disk keeps failing; past this they are dropped and counted (memory is never unbounded)
HEADER = ("t_ms", "name", "quote")


class Tape:
    def __init__(self, out: Path, src: str, flush_rows: int = FLUSH_ROWS, now=time.time):
        self.out, self.src, self.flush_rows, self.now = Path(out), str(src), int(flush_rows), now
        self.rows: list[list] = []
        self.lock = threading.Lock()
        self.n = self.files = self.errors = self.dropped = 0
        try:
            self.out.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.errors += 1

    def record(self, name: str, quote: dict | None) -> None:
        if not quote:
            return
        try:
            row = [int(self.now() * 1000), str(name), json.dumps(quote, separators=(",", ":"), sort_keys=True, default=str)]
        except (TypeError, ValueError):
            self.errors += 1
            return
        with self.lock:
            if len(self.rows) >= MAX_PENDING:
                self.dropped += 1
                return
            self.rows.append(row)
            self.n += 1
            if len(self.rows) >= self.flush_rows:
                self._flush()

    def flush(self) -> None:
        with self.lock:
            self._flush()

    def _flush(self) -> None:
        if not self.rows:
            return
        path = self.out / f"tape-{self.src}-{self.files:05d}.csv.gz"
        try:
            with gzip.open(path, "wt", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(HEADER)
                w.writerows(self.rows)
            self.files += 1
            self.rows = []
        except OSError:                                                 # kept for the next flush (bounded by MAX_PENDING)
            self.errors += 1

    def stats(self) -> dict:
        return {"tape_rows": self.n, "tape_files": self.files, "tape_errors": self.errors, "tape_dropped": self.dropped}


class TeePusher:
    """The relay's pusher, with every update also written to a Tape. Everything else is the pusher's own."""

    def __init__(self, pusher, tape: Tape):
        self.pusher, self.tape = pusher, tape

    def update(self, symbol: str, quote: dict | None) -> None:
        try:
            self.tape.record(symbol, quote)
        except Exception:                                               # noqa: BLE001 - the tape never costs the live view
            self.tape.errors += 1
        self.pusher.update(symbol, quote)

    def stop(self) -> None:
        try:
            self.pusher.stop()
        finally:
            self.tape.flush()

    def stats(self) -> dict:
        return {**self.pusher.stats(), **self.tape.stats()}

    def __getattr__(self, k):                                           # start, n, push_once, ...: the pusher's
        return getattr(self.pusher, k)


def tee(pusher, env_dir: str | None, src: str):
    """The pusher itself when no tape directory is set (a run by hand, the tests), else the pusher with a tape."""
    return TeePusher(pusher, Tape(Path(env_dir), src)) if env_dir else pusher
