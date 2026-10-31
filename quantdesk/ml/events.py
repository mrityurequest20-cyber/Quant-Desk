"""The prediction-event schema (P0.5 of docs/ML_PHASE0.md; the design is docs/ml/PREDICTION_EVENT.md). **Design only.**

A live model prediction is one journal event in one schema, so the learning bot and the teacher can read every model's predictions the same way. A
prediction is graded later by an outcome event that points back at it. This module defines the two payloads and validates them; `to_journal_args` maps a
validated payload to the arguments of the journal's existing generic `Journal.event(ts, level, category, message, data)`. It does not import or call the
journal: the engine side (a model that predicts live, in shadow) is a later, separately reviewed change, and a model may only tighten, never raise exposure.

The rules the validator enforces are the ones that keep the grading honest: timestamps carry a zone, every number is finite, the features a prediction used
are no newer than the prediction (point in time), a prediction is `shadow` or `applied` (an `offline` model makes no live event), and an outcome comes after
the prediction it grades.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta

SCHEMA_VERSION = 1
PREDICTION = "ml_prediction"
OUTCOME = "ml_outcome"
LIVE_STATUSES = ("shadow", "applied")
HORIZONS = (30, 60, 120, "close")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


class BadEvent(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def _finite(x) -> bool:
    try:
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    except OverflowError:                                                           # an int too large for a float
        return False


def _horizon_ok(h) -> bool:
    return h == "close" or (type(h) is int and h in HORIZONS)                       # not 60.0, not True


def _text(x) -> bool:
    return isinstance(x, str) and bool(x.strip())


def _ts(x):
    try:
        t = datetime.fromisoformat(str(x))
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def check_prediction(ev: dict) -> list[str]:
    p: list[str] = []
    for k in ("schema_version", "model_id", "card_digest", "status", "ts", "symbol", "session", "horizon", "target", "prediction", "features_digest", "feature_ts_max"):
        if k not in ev or ev[k] in (None, ""):
            p.append(f"missing {k}")
    if p:
        return p
    if type(ev["schema_version"]) is not int or ev["schema_version"] != SCHEMA_VERSION:
        p.append(f"schema_version must be the integer {SCHEMA_VERSION}")
    if not (isinstance(ev["model_id"], str) and _ID.fullmatch(ev["model_id"])):
        p.append("model_id is not a valid model id")
    if not _text(ev["symbol"]) or not _text(ev["target"]):
        p.append("symbol and target must be non-blank text")
    if not (isinstance(ev["card_digest"], str) and _HEX64.fullmatch(ev["card_digest"])):
        p.append("card_digest must be the 64-hex digest of the model's card (no card, no prediction)")
    if ev["status"] not in LIVE_STATUSES:
        p.append(f"status must be one of {LIVE_STATUSES}: an offline model makes no live event")
    ts, fts = _ts(ev["ts"]), _ts(ev["feature_ts_max"])
    if ts is None:
        p.append("ts must be an ISO timestamp with a zone")
    if fts is None:
        p.append("feature_ts_max must be an ISO timestamp with a zone")
    if ts is not None and fts is not None and fts > ts:
        p.append("feature_ts_max is later than ts: a feature from the future (point in time)")
    sd = None
    if isinstance(ev["session"], str) and _DAY.fullmatch(ev["session"]):
        try:
            sd = date.fromisoformat(ev["session"])
        except ValueError:
            sd = None
    if sd is None:
        p.append("session must be a real YYYY-MM-DD date (a session is the unit)")
    elif ts is not None and sd != ts.date():
        p.append("session must be the date of ts (in ts's own zone)")
    if not _horizon_ok(ev["horizon"]):
        p.append(f"horizon must be one of {HORIZONS}")
    if not _finite(ev["prediction"]):
        p.append("prediction must be a finite number")
    if "baseline_prediction" in ev and ev["baseline_prediction"] is not None and not _finite(ev["baseline_prediction"]):
        p.append("baseline_prediction must be a finite number or null")
    if not (isinstance(ev["features_digest"], str) and _HEX64.fullmatch(ev["features_digest"])):
        p.append("features_digest must be a 64-hex digest of the inputs")
    return p


def check_outcome(ev: dict) -> list[str]:
    p: list[str] = []
    for k in ("schema_version", "model_id", "ref", "graded_at", "realised", "loss_name", "loss", "baseline_loss"):
        if k not in ev or ev[k] in (None, ""):
            p.append(f"missing {k}")
    if p:
        return p
    if type(ev["schema_version"]) is not int or ev["schema_version"] != SCHEMA_VERSION:
        p.append(f"schema_version must be the integer {SCHEMA_VERSION}")
    if not (isinstance(ev["model_id"], str) and _ID.fullmatch(ev["model_id"])):
        p.append("model_id is not a valid model id")
    if not (_text(ev["loss_name"])):
        p.append("loss_name must name the loss")
    ref = ev["ref"]
    if not (isinstance(ref, dict) and _text(ref.get("ts")) and _text(ref.get("symbol")) and ref.get("horizon") not in (None, "")):
        p.append("ref needs the graded prediction's ts, symbol and horizon")
    else:
        rts, gts = _ts(ref["ts"]), _ts(ev["graded_at"])
        if rts is None or gts is None:
            p.append("ref.ts and graded_at must be ISO timestamps with a zone")
        elif gts <= rts:
            p.append("graded_at must be after the prediction it grades")
        elif type(ref["horizon"]) is int and ref["horizon"] in HORIZONS and gts < rts + timedelta(minutes=ref["horizon"]):
            p.append("graded_at is before the prediction's horizon has elapsed: the outcome cannot be known yet")
        if not _horizon_ok(ref["horizon"]):
            p.append(f"ref.horizon must be one of {HORIZONS}")
    for k in ("realised", "loss", "baseline_loss"):
        if not _finite(ev[k]):
            p.append(f"{k} must be a finite number")
    return p


def validate(ev: dict, kind: str) -> dict:
    """The payload, or `BadEvent` naming every problem. `kind` is PREDICTION or OUTCOME."""
    if kind not in (PREDICTION, OUTCOME):
        raise ValueError(f"kind must be {PREDICTION} or {OUTCOME}")
    problems = check_prediction(ev) if kind == PREDICTION else check_outcome(ev)
    if problems:
        raise BadEvent(problems)
    return ev


def to_journal_args(ev: dict, kind: str) -> tuple[str, str, str, dict]:
    """(level, category, message, data) for `Journal.event(ts, level, category, message, data)`. Pure: it builds the arguments and calls nothing."""
    validate(ev, kind)
    if kind == PREDICTION:
        msg = f"{ev['model_id']} {ev['status']} {ev['symbol']} h={ev['horizon']} -> {ev['prediction']:.6g}"
    else:
        msg = f"{ev['model_id']} graded {ev['ref']['symbol']} h={ev['ref']['horizon']} {ev['loss_name']} {ev['loss']:.6g} vs baseline {ev['baseline_loss']:.6g}"
    return "INFO", kind, msg, dict(ev)
