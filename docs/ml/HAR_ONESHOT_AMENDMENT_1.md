# Amendment 1 to `docs/prereg/har_oneshot_v1.json`: the precondition on the dataset's status

Committed **alone**: no code, no result, no run. The registered spec `docs/prereg/har_oneshot_v1.json` (sha256 `4b06e3b45dee0b5b58d81c53eb6ca6fb9394995c1903c39a797480def6498700`) is **not edited**; this file amends one rule of it and nothing else.
It is **post hoc**: it is written after the P0.6 check failed (see `docs/ml/P0_6_result_v2.md`), and it loosens a precondition the owner pre-registered. It does so on the owner's explicit instruction of **30 Oct 2026** ("Go with option 2", chosen from
three options put to the owner: a post hoc version 3 of the P0.6 criteria to try for the label, this amendment, or dropping the evaluation). No limit, gate, loss, test, window or decision rule of the registered spec changes.

## The one rule amended

- **Registered (`dataset` and `run_only_after_p06`):** the one-shot evaluation runs only when the dataset is `external_verified`, that is, only when a `verification.json` written by the P0.6 check names this digest and says it **passed**. "The command has no flag that accepts an unverified dataset."
- **Amended:** the evaluation may also run when, and **only when**, the dataset's `verification.json` is **this exact record**: sha256 `f6288b06893d100605cdcb859e1e29e297aafff40c4efda4eaddcda25d646957`, check `p06-v2`, dataset digest `47d28d6376ca63af6f435c7a7fab16dc403cc99a7c49ab954ded2c68ed98e9b8`,
  criteria sha256 `508534f5657190f3ca57ee1cd8dd76cbc81aedabcced056a421f9ad7a019b51b`, `passed: false`, `symbols_verified: []`, and one single reason: `BANKNIFTY C: month 2020-03 has 79% agreeing, at least 80% needed`, with checks A and B passing for both symbols and D passing.
  The command (to be built, separately reviewed) pins that record's sha256 and refuses any other record, any other reason, a record that was edited, and any dataset that is not this digest. It still has **no** flag that accepts an arbitrary unverified dataset. If a version 3 of the P0.6 criteria is ever written and passes, the registered rule applies to that record instead and this amendment is not needed.
- The dataset stays `external_unverified`. Nothing here flips a status, licenses a symbol or changes the loader.

## What does not change

Everything else in the registered spec: the question, the window (2023-03-01 to 2026-05-14), the symbols, the frozen model and its artifact, the candidates, the loss, the primary and pooled tests, the PASS / MIXED / KILL rules, the kill rule, the one look and its marker file, the control on the spent period,
the session and gap rules, the controls before the run (except that its first item reads as amended above), and the reporting. The decision rules are **not** changed to account for the unverified status; they are deliberately left exactly as registered.

## What the result must say (mandatory, in the result's header and in every sentence that states the outcome)

"The dataset was `external_unverified` when this was run: its P0.6 check (version 2, post hoc after a void version 1) failed one rule (BANKNIFTY, comparison with the aeron7 minute data, month 2020-03). Its daily high, low and close agreed with Yahoo and NSE for both symbols over the window.
Nothing independent checks its minute-by-minute path after Feb 2023, and this evaluation scores 1-minute returns. This evaluation was run under amendment 1 to its registration."

## Why the risk the registration named is still there, and what is and is not done about it

The registration ran only after a pass because "without this a source defect in that stretch would be scored as model error". That risk is **reduced but not removed** by this amendment: the daily envelope checks (A and B) passed, but the evaluation uses minute returns and no independent check covers them after Feb 2023.
So a MIXED or KILL outcome may reflect a data defect and a PASS may flatter the model's neighbours too; the mandatory sentence above is how the result says so. **No rule is changed to compensate, because a rule changed after seeing the data is worse than a stated caveat.** Whether to act on a KILL of the model, given the caveat, is the owner's decision then.

## Exposure, said plainly

- Nothing in the registered spec's statement that its author "loaded, read, computed on or printed no price, return, variance or loss of any session on or after 2023-03-01" is made false by this amendment's author, but **the P0.6 run did load the window's data**: it built daily high, low and close from the window's minutes and compared them with Yahoo and NSE.
  What was seen: agreement rates and the sessions that disagreed with relative differences (one session in check A: BANKNIFTY 2023-05-11, high 0.23% apart), in the committed result file and the record. No variance, forward return, loss or model score of the window was computed or seen. The one-shot has not been run, the `oneshot` command does not exist yet, and no look is spent.
- This amendment is written knowing the P0.6 outcome (checks A and B pass for both symbols; check C fails for BANKNIFTY in 2020-03, which is outside the window). It was not chosen because of anything about the model's score, which is unknown.

## Order of work after this file merges (each its own reviewed change)

1. Build `python -m quantdesk ml oneshot` per the registered spec with this precondition and the mandatory sentence, rehearsed on a synthetic dataset and on the spent period as the registration's controls require.
2. Only after both reviews and a green CI: the one run. A refusal, a void or a crash before the marker is written spends no look; a run after the marker is the one look.
