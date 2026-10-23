# ML spec: <model id>, <one-line question>

Copy this file, fill every section, and commit it **before any result exists**. A spec is a pre-registration: it cannot be edited after its
first result, only superseded by a new one. Check it is new with `python -m quantdesk experiments --check`.

## 1. Question and decision
- **Question** (one sentence a stranger could judge as right or wrong):
- **What it may change if it ever applies** (it can only tighten: shrink a size, skip a trade, stand aside; never raise an exposure, loosen a gate, or touch the paper-mode switch):
- **Component** (M1 to M8 in [ML_ROADMAP.md](../ML_ROADMAP.md)):

## 2. Target and baseline
- **Target** (exact definition, units, horizon, how it is computed from stored data):
- **Baseline to beat** (what the desk uses today, with its source and version):
- **Metric and decision rule** (the number, the threshold, and what counts as *failing*):

## 3. Data
- **Tiers used** (T1, T1b, T2, T3 from [ML_PHASE0.md](../ML_PHASE0.md)) with manifest digests:
- **Features** (each with how it is known at the decision time and its source):
- **Excluded on purpose** (anything that would leak):

## 4. Split in time (fixed now)
- **Train window:**  **Validation window:**  **Locked test window** (never looked at until the single read):
- **Purge and embargo** (bars or sessions removed between windows):
- **Training cut-off date** (the model is frozen here, then graded forward only):

## 5. Model and variants
- **Model family and settings** (small, CPU):
- **Variants tried, in total** (every one counted, including dropped ones):  **Multiple-testing control:**

## 6. Evidence needed
- **Power:** sessions or labelled setups required, and why that is enough to see the effect size claimed:
- **Costs and capacity assumptions** (the 2x stress):
- **Shadow plan:** how many live sessions, graded how, and the demotion rule:

## 7. What would stop us
- **Kill criterion:** the result that retires the idea, written as a number:
