# Amendment 1 to `docs/prereg/har_oneshot_v1.json`: the precondition on the dataset's status

Committed **alone**: no code, no result, no run. The registered spec `docs/prereg/har_oneshot_v1.json` (sha256 `4b06e3b45dee0b5b58d81c53eb6ca6fb9394995c1903c39a797480def6498700`) is **not edited**; this file amends the precondition on the dataset's status (one rule, and the registered sentences that restate it, listed below) and adds one tightening, and changes nothing else.
It is **post hoc**: it is written after the P0.6 check failed (see `docs/ml/P0_6_result_v2.md`, on `main`; the record itself, `verification.json`, stays beside the dataset outside the repository and the result file gives its sha256), and it loosens a precondition the owner pre-registered. It does so on the owner's explicit instruction of **30 Oct 2026**,
who chose to **amend the precondition** rather than write a post hoc version 3 of the P0.6 criteria to try for the label, or drop the evaluation. (In the conversation this was "option 2"; the options in the result file's closing list are numbered differently.) No limit, gate, loss, test, window or decision rule of the registered spec changes.

## The rule amended, and every registered sentence it overrides

- **Registered (`dataset`, `run_only_after_p06`):** the one-shot evaluation runs only when the dataset is `external_verified`, that is, only when a `verification.json` written by the P0.6 check names this digest and says it **passed**. "The command has no flag that accepts an unverified dataset."
- **Amended:** the evaluation may also run when, and **only when**, the dataset's `verification.json` is **this exact record**: sha256 `f6288b06893d100605cdcb859e1e29e297aafff40c4efda4eaddcda25d646957`, check `p06-v2`, dataset digest `47d28d6376ca63af6f435c7a7fab16dc403cc99a7c49ab954ded2c68ed98e9b8`,
  criteria sha256 `508534f5657190f3ca57ee1cd8dd76cbc81aedabcced056a421f9ad7a019b51b`, `passed: false`, `symbols_verified: []`, and one single reason: `BANKNIFTY C: month 2020-03 has 79% agreeing, at least 80% needed`, with checks A and B passing for both symbols and D passing.
  The command (to be built, separately reviewed) pins that record's sha256 and refuses any other record, any other reason, a record that was edited, and any dataset that is not this digest. It still has **no** flag that accepts an arbitrary unverified dataset.
- **Registered text that this route supersedes, for the pinned record only and for nothing else:**
  - `run_only_after_p06.rule`: "has checked the Mar 2023 to May 2026 stretch of this digest and passed it", and "it refuses a dataset that is not external_verified for the digest named here";
  - `run_only_after_p06.if_p06_rejects_or_changes_the_data`: "the dataset is not used: no look is spent". This was the registered answer to a failed P0.6; for the pinned record it no longer applies, and the look is spent when the run happens, as `looks.rule` says. For any other rejection or change of the data it applies unchanged;
  - `dataset`: "It is run only when the dataset is external_verified";
  - `kill_rule`: "The evaluation is run only after P0.6 has passed the data" (the rest of that sentence, "but the look is spent whatever P0.6 saw", stands);
  - `command.behaviour`: the refusal of a dataset that is "not external_verified";
  - `controls_before_the_run`, first item: "P0.6 has passed this digest and the verification record is present; the loader refuses otherwise".
- **A tightening added here (it loosens nothing):** a later version 3 of the P0.6 criteria does not qualify under this amendment. The registered rule as written does not pin a criteria version, so this closes a route the registration left open; a version 3 would need a new amendment and its own criteria commit.
- **The label.** The registered `label` rule allows "evidence: external_verified (underlying only)" if the verification record is present when the run happens: the test is presence, not a pass. **That rule does not apply to the pinned record.** The result must not carry `external_verified` anywhere, and must say `external_unverified` in its header and in its body.
- The dataset stays `external_unverified`. This file flips no status, licenses no symbol and does not change the loader. The `oneshot` change will have to load the unverified dataset through `build.load_table(reserved_spec=...)` for the pinned record alone, and that change is reviewed on its own.

## What does not change

Everything else in the registered spec: the question, the window (2023-03-01 to 2026-05-14), the symbols, the frozen model and its artifact, the candidates, the loss, the primary and pooled tests, the PASS / MIXED / KILL rules, the kill rule and its finality (below), the one look and its marker file, the registered crash rule, the control on the spent period and its tolerance,
the session and gap rules, the controls before the run (except the first item, as above), and the reporting. The decision rules are **not** changed to account for the unverified status; they are deliberately left exactly as registered.

## What the result must say (mandatory, in the result's header and in every sentence that states the outcome)

"The dataset was `external_unverified` when this was run, and nothing here is verification. Its P0.6 check (version 2) failed one rule: BANKNIFTY, comparison with the aeron7 minute data, month 2020-03 (15 of 19 sessions agree, 80% needed); the four disagreeing sessions have not been examined. Version 2 was written after a void version 1 run, departs from version 1's rule of rerunning with the same rules, is post hoc, and its check C had been rehearsed on 25 Oct, when BANKNIFTY 2020-03 was already seen to fail; the record carries `post_hoc: true` and lists three NSE files with swapped date labels (`date_label_swapped`).
Its P0.6 checks A and B passed for both symbols over the window, under their coverage and agreement thresholds: check A compared the daily high, low and close with Yahoo, and check B compared only the daily close with NSE's official close, which is nearly the same quantity as A's close, so A and B are not two independent confirmations.
Nothing independent checks its minute-by-minute path after Feb 2023, and this evaluation scores 1-minute returns. This evaluation was run under amendment 1 to its registration."

## The risk the registration named is not removed, and no rule is changed to cover it

The registration ran only after a pass because "without this a source defect in that stretch would be scored as model error". This amendment does **not** remove that risk: checks A and B are daily and close checks, and no independent check covers the window's minutes. The only minute-level check, C, compares two vendors up to Feb 2023 (not the window), and it found a disagreement for BANKNIFTY in one month.
So a MIXED or KILL outcome may reflect a data defect, and a PASS rests on minute data that no independent check has covered; the mandatory sentence above is how the result says so.
**No rule other than the precondition above is changed to compensate**, because a rule changed after seeing the data is worse than a stated caveat. **The registered `kill_rule` and `use_if_passed` apply unchanged**: a residual defect P0.6 could not see "is not grounds for a re-run or for voiding a KILL (or a PASS)", and "a failure, a mixed result or a kill is final for this model and this window". The caveat does not make a KILL voidable; it only travels with the result.

## Exposure, said plainly

- The registered spec says its author had "loaded, read, computed on or printed no price, return, variance or loss of any session on or after 2023-03-01". That sentence was true when it was written. (Its `disclosure` also records what the data steward had already seen of the window's variance ranks; that is unchanged.)
  **Since then the P0.6 run loaded the window's data.** It loaded the full minutes through `intake.load(..., allow_unverified=True)`, not through `build.load_table(reserved_spec=...)` as the registered controls require for the evaluation itself. It built daily high, low and close from the window's minutes, and also the mean of the 15:00 to 15:29 closes (`close30`, the official-close rule), and compared them with Yahoo and NSE.
  What was seen: agreement rates and the sessions that disagreed with relative differences (one session in check A: BANKNIFTY 2023-05-11, high 0.23% apart), in the committed result file and the record. **The P0.6 run** computed and showed no variance, forward return, loss or model score of the window. The one-shot has not been run, the `oneshot` command does not exist yet, and no look is spent.
- This amendment is written knowing the P0.6 outcome (checks A and B pass for both symbols; check C fails for BANKNIFTY in 2020-03). That month is outside the window, but it is **inside the registered control period** (2019-01-01 to 2023-02-28), which the control scores on this same table. The control's tolerance is not changed. The amendment was not chosen because of anything about the model's score, which is unknown.

## Order of work after this file merges (each its own reviewed change)

1. Build `python -m quantdesk ml oneshot` per the registered spec with this precondition and the mandatory sentence, rehearsed on a synthetic dataset and on the spent period as the registration's controls require.
2. Only after both reviews and a green CI: the one run. A refusal, a void or a crash before the marker is written spends no look; a run after the marker is the one look, except that a crash after the marker that wrote no number anywhere counts as nothing seen. A rerun is then allowed only under the registered `looks.crash` rule, which governs in full: the crash log saved and committed, a code fix reviewed by the research-reviewer against the unchanged spec, the fix and both attempts stated in the result, only the second run's output published, and any number displayed or written spends the look.
