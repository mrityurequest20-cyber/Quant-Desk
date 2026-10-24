# Prediction and outcome events (P0.5, design only)

This is the format a live model's prediction and its later grade take in the journal. It is **design only**: `quantdesk/ml/events.py` validates the
shape and maps it to the journal's existing `event(ts, level, category, message, data)` call, but it does not import the journal, and nothing in the
engine emits these events yet. Wiring an emitter into the engine is a later change, and it needs its own independent review.

## Why events, and why now

A model that is not graded on what it said at the time is graded on what we remember it saying. The shadow period (status `shadow`) is only worth
anything if each prediction is written down before its outcome is known, with enough provenance to rebuild it, and graded afterwards by a separate
event that points back at it.

## Prediction event (`category = "ml_prediction"`, level `INFO`)

| Field | Rule |
|---|---|
| `schema_version` | `1` |
| `model_id` | letters, digits, `_ - .` only |
| `card_digest` | 64-hex digest of the model card of the run that produced the model. No card, no prediction |
| `status` | `shadow` or `applied`. An `offline` model makes no live event |
| `ts` | timezone-aware time the prediction was made |
| `symbol`, `session` (`YYYY-MM-DD`) | what and which trading day |
| `horizon` | one of `30`, `60`, `120` (minutes) or `"close"` |
| `target` | name of the quantity predicted |
| `prediction` | finite number |
| `baseline_prediction` | finite number, or absent: the baseline's forecast for the same thing, so the grade needs nothing else |
| `features_digest` | 64-hex digest of the exact feature vector used |
| `feature_ts_max` | latest timestamp any feature depends on; must not be after `ts` (no feature from the future) |

## Outcome event (`category = "ml_outcome"`, level `INFO`)

| Field | Rule |
|---|---|
| `schema_version`, `model_id` | as above |
| `ref` | `{ts, symbol, horizon}` of the prediction being graded |
| `graded_at` | timezone-aware, strictly after `ref.ts` |
| `realised` | finite number |
| `loss_name`, `loss`, `baseline_loss` | finite losses of the model and of its baseline on that prediction |

## Status and demotion

`offline -> shadow` is a normal promotion. `shadow -> applied` needs the owner's recorded apply switch (`owner_apply` with `by`, `ts`, `rule`) and
nothing else can set it; demotion in the other direction needs nobody. `rolling_grade` compares the model's mean loss with its baseline's over the last
60 graded predictions (non-finite losses are dropped and counted, never averaged in), and `should_demote` fires when at least 30 are graded and the
model is **worse** than its baseline. The demotion rule only ever tightens: it can switch a model down, never up.

## What is not here

No emitter, no scheduler, no change to the engine, risk, execution or journal. The model card (`python -m quantdesk ml card --run <run.json>`) is
written once per `<id>-<version>`; changing a model is a new version.
