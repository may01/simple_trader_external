# Experiment workflow — analysis and proposed improvements

**Date:** 2026-09-09
**Scope:** all experiments under `external/docs/superpowers/experiment/` (zone selection,
candle bounds, next-candle bounds NC, trend detection, RSI parameters selection,
RSI quantile/sym0 classification, zone profitability, NN zone-filtered training,
asymmetry model, event bars) plus their plans, reports and session history.
**Output:** skill `running-experiments` (`~/.claude/skills/running-experiments/`) and the
proposals below.

## 1. The common template (what every experiment already does)

Seven phases, each with a gate. The sequence is stable across all runs; only the depth of
each phase varies.

| # | Phase | Artifact | Gate |
|---|-------|----------|------|
| 0 | Spec + clarify | `experiment/<name>.md` | Locked-decisions table, user-confirmed |
| 1 | Recon | "Known facts" block | Real column names, dataset sizes, base rates to beat |
| 2 | Isolate | worktree + branch | Nothing committed |
| 3 | Plan | `plans/…` single file or `task-NN` dir | Docker entry points first, task test gates |
| 4 | Build | `notebooks/<name>/` or `experiments/<name>/` | Tests GREEN in Docker |
| 5 | Fit on 2y | frozen params json | Selection never touched OOS |
| 6 | Validate on oos2m | metrics json + OOS report | Score only, zero refit |
| 7 | Report + approve | `experiment/results/<name>_results.md` | User approval before any commit |

The report format has also converged: headline conclusion, progression table (baseline →
variants), degeneracies found, what generalized vs what did not, config and artifacts,
next arbiter. Iterative experiments add `iter_NN.md` per iteration plus a `loop_summary.md`
that records rejected iterations.

## 2. What actually went wrong (the failure record)

Every one of these cost a rerun or produced a wrong conclusion that had to be withdrawn.

| Failure | Case | Generalized lesson |
|---|---|---|
| Objective with no counterweight | zone selection `select_y` → Y pinned at ±2, coverage 1.0 | Boundary argmax means broken objective |
| Optimizer on a rare-positive EV | zone profitability: every EV negative → argmax = fewest points | Use winrate/lift with a min-points floor |
| Metric below its noise floor | MI at TF240, 354 OOS rows | Report the null floor in the same table |
| Score below the base rate | NN promotion gate, 6% positives, 0.94 accuracy | Precision@k / lift / realized R |
| Label mechanics recovered as "signal" | trend detection AUC 0.94 → plain 0.56 → fwd 0.51 | Truth-decomposition ladder is mandatory |
| Same-candle geometry leak | shape-excluded rerun collapsed the remaining edge | Ablate the family that can encode the label |
| Overfit to a 2-month OOS | per-combo level optimization, reverted | Fewer free parameters on short horizons |
| Stale artifact silently reused | stats files written only if absent; stale `diff_std` | Delete or version before recompute |
| Provenance drift 2y vs oos2m | 2y frame predated `move_class` columns | Crosscheck fraction per TF in the OOS report |
| Lost pipeline code | scratchpad scripts of the closed-bounds round | Producers are committed code, not scratchpads |
| Ops friction | root-owned artifacts, compose `--env-file`, viewer mounting another worktree, 5.7 GB frames vs 15 GB host | Encode in the runbook, not in memory |

## 3. Proposed improvements, in priority order

### P1 — Shared experiment harness (`explib`)

`azlib`, `tdlib`, `zplib`, `cbnc` and `experiments/rsi_params_selection` each
reimplement: slim-frame extraction, train/test split, metric tables, plot dumping, report
emission. The bugs repeat with them (OOM on wide loads, metric tables missing `n` and
`base_rate`).

Extract one package with: `slim.extract(dataset, columns) -> frame`,
`metrics.table(...)` that always emits `n`, `base_rate` and `null_floor` alongside any
score, `report.emit(...)` for the standard markdown sections, and
`manifest.write(...)`. Each experiment then owns only its hypothesis code.

### P2 — Gates as code, not discipline

A `gates.py` in that harness producing the gate table from the skill: null floor, base
rate, degeneracy (argmax position within grid, winning-cell n), truth ladder, ablation,
look-ahead audit, provenance crosscheck, reproduction diff. The report emitter refuses to
write a headline section when a gate is missing. Discipline documents get skipped under
time pressure; a failing emitter does not.

### P3 — Artifact manifest and reproducibility

Every artifact gets a sidecar manifest: dataset name and file digest, git sha of the
producing code, spec path and digest, full parameter dict, timestamp, container image tag.
This directly prevents three observed incidents: stale stats reuse, cut-provenance drift,
and the lost producer scripts.

### P4 — Pre-registration block in the plan

Before running: hypothesis in one sentence, the metric, the effect size that would count as
success, the effect size that kills the idea, and which gate the result must survive.
Written into the Locked-decisions section. It converts "the number came out interesting"
into a decision made in advance, and it makes negative results publishable in one line.

### P5 — OOS budget and a third holdout

`oos2m` (2025-01..03) has now been used by at least six experiments. Selection pressure
accumulates across experiments even when each one refits nothing. Two mitigations: log
every OOS touch per hypothesis family in an experiment index, and cut a second validation
period or a second pair that is opened only for final arbitration.

### P6 — Experiment register — DONE 2026-09-09

`experiment/REPORT.md` now exists and is backfilled with all ten executed experiments: date,
idea in one line, verdict, disposition (merged / pushed / branch kept), plus a short entry
per experiment saying what held and what killed it. The skill requires a `running` row at
phase 0 and a closed row at phase 7. Remaining work: reconcile the two experiments whose
worktrees are still alive and uncommitted (`trend-detection-experiment`,
`zone-profitability`) against the new disposition rule.

### P7 — One terminal metric: realized R with fees

Experiments stop at different currencies (AUC, winrate, lift, reach probability, realized
R). Only realized R with fees is decision-grade, and reach-based results have already been
shown to be target-proximity artifacts. Ship a shared realized-R calculator (pessimistic
fill, first-touch race, fee parameter) and require it in the headline of any experiment
that claims profitability.

### P8 — Ops cleanups

Move `docker/Dockerfile.experiment` and `docker-compose.experiment.yml` onto the base
branch so experiment worktrees stop copying them; wrap volume writes in a helper that
chowns to the host user afterwards; add a viewer make target that names the worktree it
mounts.

## 4. Adoption

P4 and P6 are documentation-only and can start with the next experiment. P1–P3 are one
focused build in the experiment image, best sequenced as: manifest → metric table →
gate table → report emitter, each with tests in Docker. P5 and P7 need a decision from the
user, since both change what "validated" means for every future result.
