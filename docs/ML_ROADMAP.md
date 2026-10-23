# Machine learning on the Quant-Desk: roadmap (draft for the owner, 17 Oct 2026)

Status: a plan, not a spec. Nothing here is built or registered. Each model below becomes its own pre-registered spec
(docs/prereg/) before any code, as every other study on this desk.

## 1. The idea in one paragraph

One shared learning platform trains every part of the desk: the volatility forecaster, the regime read, the brain
(news and global markets), the entry filter, the exits, sizing, and the execution-cost model. They share one dataset
and one test harness, but each part keeps its **own model and its own gate**. We do not train one end-to-end black box:
we could never validate it, and one failure would take the whole desk with it.

## 2. Rules every model follows (non-negotiable, same as the rest of the desk)

1. **Pre-registered.** Target, features, train / validate / locked-test split in time, baseline to beat, metrics and the
   number of variants tried are written down and committed before any result exists.
2. **Beat the baseline out of sample.** The baseline is what the desk uses today (for volatility: HAR).
3. **Shadow first.** A model predicts live and is graded against what happened. It changes no decision.
4. **Owner flips apply.** Promotion is a registered rule plus your switch (like the earn-in gate). Never automatic.
5. **A model can only tighten.** It may shrink a size, skip a trade or stand aside. It can never raise an exposure
   above the owner's ceilings (risk per trade 0.025, 4 trades a day, 2 open, daily loss 0.05, outlay 0.5, 10% drawdown
   halt), loosen a gate, or touch the paper-mode switch. The ceilings live outside the model's reach.
6. **Automatic demotion.** If a live model's rolling score falls below its baseline, it drops back to shadow by itself
   (tightening needs no approval).
7. **No online learning in the live loop.** Models retrain on a schedule, are versioned with full provenance (data
   digests, code commit, training window, like the committed HAR coefficients), and are loaded read-only by the engine.

## 3. The platform (built once, used by everything)

| Piece | What it does |
|---|---|
| Dataset builder | Point-in-time tables from the journal (decisions, trades, rejections, thoughts, events, plan studies), the chain tape, index minutes (2007 to Feb 2023), stock minutes (from Oct 2026), F&O bhavcopy (2019+), participant OI, chain quotes |
| Labels | Realised vol and moves over 30m / 60m / 120m / close; trade P&L after costs; **counterfactuals** for trades the desk refused or exited early (from plan studies) |
| Harness | Walk-forward splits with purging and an embargo, leakage tests, a baseline comparison, a model card for every run |
| Registry | Model id, version, provenance, status (offline / shadow / applied), rolling grade |
| Prediction events | Every live prediction is a journal event in one schema, so the learning bot and the teacher can read them |
| Retrain job | A scheduled GitHub run on CPU. Small models only, so it costs no Claude usage |

## 4. Models, by component, in order of how much honest evidence we can get

| # | Component | Target | Model family | Baseline | Data we have | Apply-ready when |
|---|---|---|---|---|---|---|
| M1 | **Volatility / move size** | Realised vol at 4 horizons | Gradient boosting, quantile regression | HAR (already beats the old forecaster by 13 to 35%) | 13 years of index minutes | Beats HAR on the locked test, then 20 graded live sessions |
| M2 | **Regime** (trend / range / stress) | Next-hours vol and setup behaviour by regime | Hidden Markov or clustering, then a classifier | Today's hand-set regime rules | Same, plus VIX, breadth, OI | Regime-conditional results differ, out of sample |
| M3 | **Brain** (news and global) | Next-hours index move and vol | Ridge / logistic with heavy shrinkage; text features from news | The hand-weighted links | Journal thoughts and news, global series | Learned weights beat the hand weights, graded live |
| M4 | **Entry filter** | Does this setup fire and pay after costs today? | Meta-labelling on top of the setups | Take every setup | Plan-study counterfactuals plus shadow records | At least about 300 to 500 labelled setups, then forward |
| M5 | **Exits** | Best stop, target, time stop | Offline policy evaluation on replays | Current fixed rules | Same | Beats fixed rules out of sample |
| M6 | **Sizing** | Confidence mapped to size, tighten-only | Calibrated probabilities | Current sizer | Same | After M4 is calibrated |
| M7 | **Option mispricing** | Implied vs forecast vol, skew | Cross-sectional models | Model prices | Chain history is short (since Oct 2026) | Needs months of tape |
| M8 | **Execution costs** | Slippage and spread by time and instrument | Regression on real fills | Flat tick model | Paper fills, tape | Improves cost prediction |
| M9 | **Teacher / LLM** | Hypotheses, news reading | Stays advisory | n/a | n/a | Never gates a trade |

Neural networks are **not** the first move. We test gradient boosting first. A sequence model on minute bars gets its
own spec only if boosting shows real signal that deeper structure might add. Real-time inference is feasible
(CPU, under 50 ms per prediction from bars the engine already holds); real-time *training* is not planned.

## 5. Phases (from the day Monday's session is confirmed clean)

| Phase | Window | Deliverable |
|---|---|---|
| 0 | late Oct to mid Nov | The ML spec template, dataset builder from journal and minutes, leakage tests, model card format, registry |
| 1 | Nov | **M1**: pre-registered ML vs HAR on the locked test, then shadow |
| 2 | Nov to Dec | **M2** (regime) and **M3** (brain weights), offline then shadow |
| 3 | Dec to Jan | **M4** and **M5**, once enough labelled setups exist (shadow records and plan-study counterfactuals) |
| 4 | Jan to Mar | First apply flips for whichever models passed their gates; **M6** sizing (tighten-only), **M8** costs |
| 5 | 2027 | Wider instruments and stocks, more chain history, **M7**, any sequence model that earns a spec |

## 6. Honest expectations

- **ML will not conjure an edge.** Our own direction research found none after costs. Expect the real gains in volatility
  and move-size forecasts, regime reads, cost prediction and tighter sizing, not in predicting direction.
- **Most models will fail promotion.** That is what the gates are for, and a failed gate is a useful result.
- **Trade-level data is thin.** About 14 trades a week is far too few to train an entry filter. The counterfactuals and
  the overnight / sleeve shadow records are what make M4 to M6 possible, and they take months to accumulate.
- **Compute is cheap.** Training small models on GitHub runners costs no Claude usage. Claude is used only for the
  teacher, the news text, and reviews.

## 7. Decisions needed from the owner

1. Approve the rules in section 2 as the standing ML policy (especially "tighten-only" and "owner flips apply").
2. Approve the start order: platform, then M1, then M2 and M3.
3. Confirm neural networks wait until gradient boosting shows signal.
4. Confirm that retraining may run on a schedule as a read-only GitHub job (no write permission, no secrets).
