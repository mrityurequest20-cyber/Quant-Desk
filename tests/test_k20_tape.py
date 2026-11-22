"""Audit K-20 (E-05, HIGH): nothing recorded Fyers' and Angel One's data: the MCX and currency quotes, books and option chains existed only in the relay's latest
snapshot, so nobody could study, replay or train on what AUTO decided on, and every MCX option series that expired was lost for good. Now each update the feeds
hand the relay is also written to a tape, which the workflow encrypts with the owner's key before it keeps it (licensed data, public repository). Data only."""
from __future__ import annotations

import csv
import gzip
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from quantdesk.data import tape as T

ROOT = Path(__file__).resolve().parents[1]
FEEDS = {"fyers": (ROOT / ".github/workflows/fyers-feed.yml", "data fyers-feed --until"), "angel": (ROOT / ".github/workflows/angel-feed.yml", "data angel-feed --until")}
needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")


class Pusher:
    def __init__(self):
        self.got, self.n, self.started, self.stopped = [], 0, False, False

    def update(self, s, q):
        self.got.append((s, q))
        self.n += 1

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def stats(self):
        return {"pushes_ok": 3}


def rows(d: Path):
    out = []
    for f in sorted(d.glob("tape-*.csv.gz")):
        with gzip.open(f, "rt", newline="", encoding="utf-8") as fh:
            r = list(csv.reader(fh))
        assert r[0] == list(T.HEADER)
        out += r[1:]
    return out


def test_every_update_goes_to_the_relay_unchanged_and_to_the_tape_whole_with_its_book(tmp_path):
    p, clock = Pusher(), iter(range(1_000, 10_000))
    tp = T.TeePusher(p, T.Tape(tmp_path / "tape", "f", flush_rows=2, now=lambda: next(clock)))
    book = {"b": [[5800.0, 3], [5799.0, 7]], "a": [[5801.0, 2]]}
    q1 = {"ltp": 5800.5, "bid": 5800.0, "ask": 5801.0, "bid_qty": 3, "ask_qty": 2, "oi": 1234, "vol": 99, "s": "mcx", "d": book}
    tp.update("CRUDEOIL-MCX", q1)
    tp.update("USDINR-CDS", {"ltp": 93.1, "bid": 93.0975, "ask": 93.1025})
    tp.update("GOLD-MCX", {"ltp": 118000.0})
    tp.update("NONE", None)                                                                # nothing to record, and still handed on as before
    tp.start()
    tp.stop()
    assert [s for s, _ in p.got] == ["CRUDEOIL-MCX", "USDINR-CDS", "GOLD-MCX", "NONE"] and p.got[0][1] is q1 and p.started and p.stopped
    r = rows(tmp_path / "tape")
    assert [x[1] for x in r] == ["CRUDEOIL-MCX", "USDINR-CDS", "GOLD-MCX"] and [int(x[0]) for x in r] == [1_000_000, 1_001_000, 1_002_000]
    assert json.loads(r[0][2]) == q1                                                      # lossless: bid, ask, sizes, OI and the five-level book
    assert len(list((tmp_path / "tape").glob("tape-f-*.csv.gz"))) == 2                    # a chunk of 2, then the rest at stop
    assert tp.stats() == {"pushes_ok": 3, "tape_rows": 3, "tape_files": 2, "tape_errors": 0, "tape_dropped": 0} and tp.n == 4


def test_the_tape_never_costs_the_live_view(tmp_path, monkeypatch):
    p = Pusher()
    tape = T.Tape(tmp_path / "t", "a")
    tp = T.TeePusher(p, tape)
    monkeypatch.setattr(tape, "record", lambda *a: (_ for _ in ()).throw(RuntimeError("disk on fire")))
    tp.update("USDINR-CDS", {"ltp": 93.1})
    assert p.got == [("USDINR-CDS", {"ltp": 93.1})] and tape.errors == 1
    bad = T.Tape(tmp_path / "u", "a")
    bad.record("X", {"ltp": float("nan"), "o": object()})                                 # odd values are written as text, never raised
    assert bad.n == 1 and bad.errors == 0


def test_a_failing_disk_keeps_rows_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "MAX_PENDING", 5)
    tape = T.Tape(tmp_path / "t", "f", flush_rows=2)
    monkeypatch.setattr(T.gzip, "open", lambda *a, **k: (_ for _ in ()).throw(OSError("full")))
    for i in range(10):
        tape.record(f"N{i}", {"ltp": i})
    assert len(tape.rows) == 5 and tape.dropped == 5 and tape.errors >= 1 and tape.files == 0


def test_no_tape_without_a_directory():
    p = Pusher()
    assert T.tee(p, None, "f") is p and T.tee(p, "", "f") is p and isinstance(T.tee(p, "/tmp/x-k20-tape", "f"), T.TeePusher)


def test_both_feed_commands_tee_their_pushers():
    src = (ROOT / "quantdesk/data/cli.py").read_text(encoding="utf-8")
    assert 'tee(LivePusher(url, ingest, src="f"), os.environ.get("MARKET_TAPE_DIR"), "f")' in src
    assert 'tee(LivePusher(url, ingest, src="a"), os.environ.get("MARKET_TAPE_DIR"), "a")' in src


@pytest.mark.parametrize("feed", sorted(FEEDS))
def test_every_streaming_job_keeps_its_tape_encrypted_and_only_encrypted(feed):
    path, cmd = FEEDS[feed]
    text = path.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    streaming = [j for j in wf["jobs"].values() if any(cmd in str(s.get("run", "")) for s in j["steps"])]
    assert streaming
    for job in streaming:
        steps = job["steps"]
        i = next(k for k, s in enumerate(steps) if cmd in str(s.get("run", "")))
        assert steps[i]["env"]["MARKET_TAPE_DIR"] == "runtime/tape"
        enc = next(k for k, s in enumerate(steps) if str(s.get("name", "")).startswith("Encrypt the day's"))
        up = next(k for k, s in enumerate(steps) if "upload-artifact" in str(s.get("uses", "")))
        assert i < enc < up and steps[enc]["if"] == "always()" and steps[up]["if"] == "always()"
        assert set(steps[enc]["env"]) == {"MARKET_TAPE_KEY"} and "openssl enc -aes-256-cbc -pbkdf2 -iter 200000" in steps[enc]["run"]
        assert steps[up]["with"]["path"] == f"{feed}_tape.tar.enc" and steps[up]["with"]["retention-days"] == 90
        assert steps[up]["with"]["name"].endswith("-${{ github.run_attempt }}")                      # a re-run never collides with the first attempt's artifact
        tok = "FYERS_DATA_TOKEN" if feed == "fyers" else "ANGEL_DATA_TOKEN"
        blank = next(k for k, s in enumerate(steps) if str(s.get("name", "")).startswith("The day's") and "token ends with the stream" in s["name"])
        assert i < blank < enc and steps[blank]["if"] == "always()" and steps[blank]["run"] == f'echo "{tok}=" >> "$GITHUB_ENV"'     # K-20 review: no later step sees it
        assert all("MARKET_TAPE_KEY" not in str(s.get("env", {})) for k, s in enumerate(steps) if k != enc)      # the key reaches the encrypting step alone
        assert not any("runtime/tape" in str(s.get("with", {})) for s in steps)                                   # the plain tape is never uploaded
    assert re.findall(r"uses:\s*actions/upload-artifact@([0-9a-f]{40})", text)                                   # pinned


def enc_script(feed="fyers"):
    wf = yaml.safe_load(FEEDS[feed][0].read_text(encoding="utf-8"))
    for j in wf["jobs"].values():
        for s in j["steps"]:
            if str(s.get("name", "")).startswith("Encrypt the day's"):
                return s["run"]


@needs_openssl
def test_the_encrypt_step_encrypts_with_the_key_deletes_the_plain_tape_and_without_a_key_keeps_nothing(tmp_path):
    def run(key):
        d = tmp_path / ("k" if key else "nk")
        (d / "runtime" / "tape").mkdir(parents=True)
        tape = T.Tape(d / "runtime" / "tape", "f")
        tape.record("CRUDEOIL-MCX", {"ltp": 5800.5, "bid": 5800.0})
        tape.flush()
        env = {"PATH": "/usr/bin:/bin", "MARKET_TAPE_KEY": key, "GITHUB_STEP_SUMMARY": str(d / "summary")}
        r = subprocess.run(["bash", "-e", "-c", enc_script()], cwd=d, env=env, capture_output=True, text=True)
        return d, r
    d, r = run("k" * 40)
    assert r.returncode == 0, r.stderr
    assert (d / "fyers_tape.tar.enc").exists() and not (d / "runtime" / "tape").exists()
    assert b"CRUDEOIL" not in (d / "fyers_tape.tar.enc").read_bytes()
    out = d / "out"
    out.mkdir()
    dec = subprocess.run(f"openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:MARKET_TAPE_KEY -in fyers_tape.tar.enc | tar -C out -xf -", shell=True, cwd=d,
                         env={"PATH": "/usr/bin:/bin", "MARKET_TAPE_KEY": "k" * 40}, capture_output=True)
    assert dec.returncode == 0 and rows(out)[0][1] == "CRUDEOIL-MCX"                       # the owner can read it back
    d2, r2 = run("")
    assert r2.returncode == 0 and "::warning::MARKET_TAPE_KEY is not set" in r2.stdout
    assert not (d2 / "fyers_tape.tar.enc").exists() and not (d2 / "runtime" / "tape").exists()     # nothing kept in the clear
    tmp_path2 = tmp_path / "short"
    tmp_path2.mkdir()
    (tmp_path2 / "runtime" / "tape").mkdir(parents=True)
    (tmp_path2 / "runtime" / "tape" / "tape-f-00000.csv.gz").write_bytes(b"x")
    r3 = subprocess.run(["bash", "-e", "-c", enc_script()], cwd=tmp_path2, env={"PATH": "/usr/bin:/bin", "MARKET_TAPE_KEY": "k" * 31, "GITHUB_STEP_SUMMARY": str(tmp_path2 / "s")},
                        capture_output=True, text=True)
    assert r3.returncode == 0 and "under 32 characters" in r3.stdout and not (tmp_path2 / "fyers_tape.tar.enc").exists() and not (tmp_path2 / "runtime" / "tape").exists()


def test_a_chunk_is_whole_or_absent_and_a_row_that_cannot_be_written_never_blocks_the_tape(tmp_path):
    tape = T.Tape(tmp_path / "t", "f", flush_rows=3)
    tape.record("GOLD-MCX", {"ltp": 1.0})
    tape.record("BAD\ud800", {"ltp": 2.0})                                                # a lone surrogate: it cannot be encoded
    tape.record("SILVER-MCX", {"ltp": 3.0})                                               # the flush fails, the bad row is dropped and counted
    tape.flush()
    assert not list((tmp_path / "t").glob("*.tmp"))
    assert [r[1] for r in rows(tmp_path / "t")] == ["GOLD-MCX", "SILVER-MCX"] and tape.dropped == 1 and tape.errors == 0    # refused at record(), once
    class P(Pusher):
        def stop(self):
            raise RuntimeError("pusher")
    tp = T.TeePusher(P(), tape)
    tape.flush = lambda: (_ for _ in ()).throw(RuntimeError("flush"))
    with pytest.raises(RuntimeError, match="pusher"):                                      # the pusher's own error is the one reported, never the tape's
        tp.stop()


def test_a_failing_disk_never_costs_more_than_a_row_at_a_time(tmp_path, monkeypatch):
    """Risk review of b09c28b: after a failed write every record() tried the write again and re-scanned every pending row (60 ms a row at 199,000 pending).
    Now a failed write is tried again only after flush_rows more rows, and the partial .tmp is removed."""
    import time
    tape = T.Tape(tmp_path / "t", "f", flush_rows=1000)
    calls = {"n": 0}
    real = T.gzip.open

    def failing(path, *a, **k):
        calls["n"] += 1
        fh = real(path, *a, **k)
        fh.close()
        raise OSError("disk full")
    monkeypatch.setattr(T.gzip, "open", failing)
    t0 = time.perf_counter()
    for i in range(5000):
        tape.record(f"N{i}", {"ltp": i})
    took = time.perf_counter() - t0
    assert calls["n"] == 5 and tape.errors == 5 and len(tape.rows) == 5000                    # one try per 1,000 rows, not one per row after the first failure
    assert took < 2.0 and not list((tmp_path / "t").glob("*.tmp"))
    monkeypatch.setattr(T.gzip, "open", real)
    tape.flush()
    assert len(rows(tmp_path / "t")) == 5000 and tape.files == 1                               # the disk back: nothing kept was lost
