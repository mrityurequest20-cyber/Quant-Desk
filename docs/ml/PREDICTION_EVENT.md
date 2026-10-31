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

`offline -> shadow` is a normal promotion. `shadow -> applied` is refused by the code unless the run record carries an `owner_apply` entry (`by`, `ts`,
`rule`). That entry is free text today (see below), so this is a guard against a slip, not against someone who writes the record. Demotion needs nobody.
Because a card is written once, **a status change is a new version of the card**; nothing yet records the link between the two, and the registry change
that does is a later one.

`rolling_grade` takes the last 60 graded predictions, **oldest first, in the order the caller gives them** (it does not sort), and compares the model's
mean loss with its baseline's. Non-finite losses inside that window are counted (`dropped_non_finite`) and left out of the means, never averaged in or
repaired. `should_demote` returns true when at least 30 predictions are in the window and either (a) 20% or more of them are non-finite (a model that emits
NaN is not working), or (b) the model is **worse** than its baseline. Where the outcomes name their `session`, fewer than 5 distinct sessions is no verdict
at all (a session is the unit: 40 predictions from one busy day are one observation). The demotion rule only ever tightens: it can switch a model down,
never up.

## What a card checks, and what it cannot

`build_card` refuses a run record unless: the model id and the version are file-safe names; the spec has a file and a 64-hex sha256; the code commit is a
full 40-hex commit; every data tier has a name, a manifest, a hex digest and a status from the importer's list; the training window holds real dates with
`start <= end <= cutoff`; the settings hold plain finite JSON and an integer seed; the variants tried is an integer of at least 1; the baseline has a name
and a version; the out-of-sample block has a metric, a model and a baseline score, a difference that **equals model minus baseline**, an interval that
contains it with its level and method, and a session count; and the leakage tests are `{name, passed}` entries that all passed. `ml card` then checks the
record against the repository: the spec file exists inside it and hashes to `spec.sha256`, and the code commit is a commit of it.

It cannot know that a run record was honestly written (for example that the tree was clean), that a leakage test was really run, or that the numbers are the
run's. Those are the job of the harness that writes the record (P0.8). The card's digest is an **unkeyed sha256**: it makes an edit visible, and it does not
stop someone who edits the card and recomputes the digest. Authority comes from where cards are kept and reviewed, not from the digest.

## What is not trusted yet

- **`owner_apply` is free text in the run record.** Today nothing reads a card, so it changes nothing. Before any emitter or engine reader exists, the check for `applied` must be made against a record the owner controls (a committed or signed owner entry), not against a field the author of the run record can write. That belongs to the later, reviewed change that wires cards to the engine.
- **`card_digest` is only checked for shape** (64 hex). The later emitter must also verify that a stored card with that digest exists and says `shadow` or `applied`.
- **Where cards are written:** `ml card` refuses an output folder inside a git working tree unless it is under the gitignored `runtime/` folder (as `ml oi` does). A card that is meant to be committed is placed there by a reviewed change, not written there by the command.

## What is not here

No emitter, no scheduler, no change to the engine, risk, execution or journal. The model card (`python -m quantdesk ml card --run <run.json>`) is
written once per `<id>-<version>`; changing a model is a new version.
