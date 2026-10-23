---
name: running-experiments
description: Use when running a quantitative research experiment in simple_trader — a spec under external/docs/superpowers/experiment/, a hypothesis about labels, zones, indicators, RSI classes or NN targets, or any request to measure
---

# Running Experiments (simple_trader)

## Overview

An experiment is the **mathematical validation of a hypothesis**. It exists to produce
indicators, classes, zones or levels that make trading decisions measurably better —
higher-quality entries, not more code. A hypothesis that survives becomes a candidate
indicator; one that dies is recorded as dead so nobody re-runs it.

The deliverable is a decision-grade report: whether the hypothesis held, on which numbers,
and what it means for trade quality.

**Core principle: a number you have not tried to break is a number you cannot trust.**
Every headline metric gets a null baseline and at least one ablation *before* it enters a
report. Historically, every impressive first result in this project was degenerate,
leaked, or below its own small-sample noise floor.

Extends `superpowers:writing-plans` + `layer-first-planning` (Docker entry points first).

## Phases

Each phase has an exit gate. Do not start phase N+1 before phase N's gate passes.

| # | Phase | Gate |
|---|-------|------|
| 0 | **Read spec + register + clarify** — spec in `external/docs/superpowers/experiment/<name>.md`; check `REPORT.md` for prior attempts | Every ambiguity answered by the user in a **Locked decisions** table (dated); a `running` row appended to `REPORT.md` |
| 1 | **Recon** — real column names, dataset paths/sizes, host RAM, prior artifacts, precedents, missing inputs | A **Known facts** block in the plan; no guessed column name survives |
| 2 | **Isolate** — dedicated worktree + branch off the stated base branch (`experimental_imp_2` unless the spec or a predecessor experiment names another) | Base branch named in the plan; worktree exists; nothing committed |
| 3 | **Plan** — Docker entry points, then tasks; heavy work as its own task | Plan file(s) in the external docs repo, task-by-task, each ending in a test gate |
| 4 | **Build** — read-only over source frames; new data = new columns or sidecar files | Tests GREEN in Docker after every task |
| 5 | **Fit on 2y** — model/cuts/shifts selected on train only, internal chronological split | Frozen artifact (json/pkl) written; selection never touched oos2m |
| 6 | **Validate on oos2m** — score only, zero refit | Validity gates below all executed and reported |
| 7 | **Report + dispose** — results md in the external repo, then user decides | User approval before any commit; then merge into base (success) or push-and-drop the worktree (failure); `REPORT.md` row closed with verdict, disposition and the one-line outcome |

## Validity gates (phase 6 — mandatory, all of them)

| Gate | Question | Failure looks like |
|---|---|---|
| **Null floor** | Is the metric above its small-sample noise floor? | MI at n=354 below `(K−1)/(2N·ln2)` |
| **Base rate** | Does the score beat the unconditional rate for the same rows? | 0.94 "accuracy" on a 6% positive class |
| **Degeneracy** | Where does the objective's argmax sit? | Y pinned at ±2, coverage 1.0, p_reach 0 corner, cell with n=31 |
| **Truth ladder** | strict → plain → forward-return: how much survives dropping label mechanics? | AUC 0.94 → 0.56 → 0.51 |
| **Feature ablation** | Rerun without the suspicious family (candle shape, same-candle geometry) | Signal was the label's fingerprint |
| **Look-ahead** | Does every feature use only closed/past information at its row? | Same-row extreme, unshifted broadcast |
| **Provenance** | Do cuts/params applied to oos2m come from the frozen 2y fit? | Crosscheck fraction < 1.0 |
| **Reproduction** | Refit from stored meta and diff against the stored artifact | Relative diff must be ~1e-15, not "close" |

Report each gate with its number. "Checked" without a number does not count.

Details and the full pitfall list: [validity-gates.md](validity-gates.md),
[operational-pitfalls.md](operational-pitfalls.md).
Spec / plan / results skeletons: [templates.md](templates.md).

## Hard rules

- **The register is `external/docs/superpowers/experiment/REPORT.md`.** Append a row when
  the experiment starts (date, name, the idea in one line, verdict `running`), and fill
  verdict plus disposition when the results report is approved. Rows are never deleted.
  Read it before planning anything — it is the record of what has already been tried.
- **One experiment, one worktree, one branch.** Never run an experiment in a shared
  worktree. The base branch is chosen and stated *before* the run: `experimental_imp_2`
  unless the spec names another, or the predecessor experiment's branch when the work
  chains off it.
- **No commits until the report is approved.** Stage nothing, ask, wait.
- **Disposition after the report, user-confirmed:**
  - Successful → commit, merge the branch into its base branch, then remove the worktree.
  - Unsuccessful → commit, push the branch to the remote so the attempt stays in history,
    remove the local worktree. The branch is the record; the results md says why it died.
- Source frames are read-only. New data is appended as columns or written as a sidecar,
  never written back over `df_with_indicators.pkl`.
- oos2m is scored, never selected on. One touch for selection burns it.
- Docs, plans, specs and reports go to the external docs repo, never the code repo.
- Heavy frames (5.7 GB) load inside Docker, one at a time, column-subset first.
- Every artifact carries its provenance: dataset, git sha, spec, date, params.
- An iteration loop writes a report per iteration and records rejected iterations too.
- Negative results ship. "Did not generalize" is a finished experiment, not a failure.
- Close the loop: a surviving hypothesis is written up as a candidate indicator with its
  frozen parameters; a dead one is recorded as dead, with the number that killed it.

## Red flags — stop and run a gate

- First metric is excellent → truth ladder + ablation before writing a line of report.
- The best cell has the fewest points → add a minimum-points floor, rerun.
- Optimizer chose a boundary value → objective has no counterweight, fix the objective.
- A stats/artifact file already exists → confirm it was regenerated, not silently reused.
- "It matches the old pipeline" → prove it with a numeric reproduction gate.
- About to reuse a column name from memory → grep the real frame first.
