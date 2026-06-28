# Phase 11 NN Module — Implementation Decisions Log

Running log of decisions made while executing the phase-11 rewrite on branch
`phase-11-nn-module` (from `experimental_imp_2`). Each entry: context →
approaches considered → rationale → choice.

---

## D0 — Execution strategy & scope (2026-06-25)

**Context:** 12-task NN-subsystem rewrite + user steps 2-6 (recalc 2w data,
build dataset, small model, train, simulate). Host has **no GPU**, Docker present.

**Decisions (user-confirmed):**
- **Scope:** full phase (all 12 tasks) including agentic loop (ExperimentTracker,
  NNStrategist, TrainingLoop).
- **Method:** subagent-driven TDD — one implementer subagent per task, task review
  (spec + quality) after each, broad review at the end.
- **Workspace:** git worktree `worktrees/phase-11-nn-module` ← `experimental_imp_2`
  (project convention). Merge back into `experimental_imp_2`.

## D1 — nn-train Docker image base (GPU-less host)

**Context:** Task 01 specifies a dedicated CUDA image. This host has no NVIDIA
driver; the verification (steps 2-6) is a small-model smoke, not production GPU
training.

**Approaches:**
1. Literal CUDA runtime base (`nvidia/cuda:*`): multi-GB pull, runs CPU here;
   matches the spec text but heavy + slow on a laptop.
2. Slim Python base + CUDA-enabled torch wheel (`torch==*+cuXXX`) + optuna: the
   cu-wheels bundle CUDA libs and run CPU fine with no GPU, GPU when present.
   Same image runs CPU on laptop / GPU on host — the spec's actual intent.
3. Reuse the always-on `simple_trader` image: violates the image-isolation
   constraint (keeps CUDA/Optuna out of the live image).

**Choice:** **Approach 2.** Honors "GPU optional, one image both ways" + image
isolation, without a multi-GB CUDA-base pull on a GPU-less host. The pure
`nvidia/cuda` base is flagged as a config swap for the GPU host (tech-debt note).

## D2 — Stale verification snippets in task specs (doc-drift)

**Context:** task-06 verification uses old `NNModel(input_size, hidden_size,
num_classes)`; task-07/task-10 use `from nn.model_spec import NNModelSpec` and
`NNModelSpec.default()`.

**Choice:** Authoritative interface sections govern — `nn/nn_model_spec.py` +
spec-driven `NNModel(spec)`. Task-02 implementer also adds a `default()`
classmethod (minimal valid spec) since tasks 07/10 depend on it. Verification
snippets adapted to the real interface by each implementer. Flag upstream
spec-doc fix as tech-debt (do not edit specs from code branch).

## D3 — Per-task local commits authorized (this run)

User confirmed: implementers may commit once per task on the isolated, never-pushed
`phase-11-nn-module` worktree branch (enables SDD per-task review diffs + recovery
ledger). General "confirm before commit" rule still holds for push/PR and for merge
into `experimental_imp_2` — those require explicit sign-off.

## D4 — Main thread performs commits (not subagents)

Implementer subagents inherit the same "only the USER confirms commits; a coordinator
relay is not user authority" memory, so they refuse to commit on the controller's
say-so. Resolution: implementers implement + test (GREEN) + `git add` + report DONE
without committing; the MAIN thread (which the user authorized in D3) runs `git commit`.
Keeps commits under authorized control and unblocks the SDD per-task flow.

## D5 — NNOrchestrator.run_inference signature reconciliation (task 08 vs task 11)

Task 08's Interface specs `run_inference(df, data_attributes, spec=None) -> DataFrame` (pure,
returns nn_res_* indexed by df.index, no write). Task 11's wiring calls
`run_inference(dataset=NN_INFER_DATASET, checkpoint_id=NN_INFER_CHECKPOINT)` and says "the
orchestrator writes {dataset}/df_with_nn.pkl atomically." These conflict on signature.

**Choice:** keep task 08's `run_inference(df, data_attributes, spec=None) -> DataFrame|None`
PURE (testable, reusable, no I/O). The dataset-path + checkpoint_id resolution and the atomic
write of `{dataset}/df_with_nn.pkl` live in a thin orchestrator method added in task 11
(`run_inference_dataset(dataset_dir, checkpoint_id="best")`: loads df_with_indicators.pkl +
DataAttributes, calls run_inference, atomically writes df_with_nn.pkl). The atomic write stays
in the orchestrator layer (honours task 11 constraint) while inference stays pure. Flag the
task-08/11 spec-doc signature mismatch as upstream tech-debt.

## D6 — Inference feature-matrix parity

run_inference must build the SAME closed-candle lookback windows as NNDataset (live/backtest
parity) but normalise with the checkpoint's BUNDLED manifest stats (never recompute — leakage
guard). To avoid duplicating `_build_tf_block`, the orchestrator reuses NNDataset's window
builder (a small public method that applies GIVEN normalization stats rather than recomputing
train-split stats), not a re-implementation in the orchestrator.

## D7 — nn_train wires to single-shot orchestrator.train (per task-11 brief)

Task 11's `_run_train_nn` calls `NNOrchestrator.from_trainer(pair, self).train(df, data_attributes)`
(single-shot), NOT `TrainingLoop.run`. TrainingLoop (the Optuna+LLM agentic search) is fully
implemented + tested + invocable, but is not the default trainer RUN_TYPE path — it is the
"investigation" entry to be wired to a search RUN_TYPE later. The small-model e2e (step 5) uses
single-shot training, matching the brief. "Ready for training and investigation" = both paths exist.

## D8 — Infer service gets RW on the data volume (spec self-contradiction surfaced at e2e)

The plan is internally inconsistent: task 01 mounts `simple_trader_vol` (`/trader_data`)
READ-ONLY for both nn-train and simulate-nn ("prevent training churn from corrupting live
data"), but tasks 11/12 write `df_with_nn.pkl` BESIDE `df_with_indicators.pkl` (in
`/trader_data`) and the consumer join reads it from `dirname(df_with_indicators)`. With the RO
mount, `infer_nn` cannot write its output → the canonical `simulate-nn` path fails.

**Choice (verification + minimal coherent fix):** mount `simple_trader_vol` RW on the
**simulate-nn (infer)** service only. Inference is additive-only — it writes ONLY the disposable
`df_with_nn.pkl` and provably never mutates `df_with_indicators.pkl` (task 11/12 assert mtime
unchanged). nn-train (training) keeps `/trader_data` RO (it only reads data; weights go to
`_long`). This co-locates `df_with_nn.pkl` with `df_with_indicators.pkl` so the consumer join
finds it trivially.

**Open for the user:** the permanent design could instead keep `/trader_data` RO everywhere and
relocate `df_with_nn.pkl` to `NN_ARTEFACT_ROOT` (`_long`) with a consumer-side path mapping. That
honours "artefacts live on _long" more strictly but adds a path-resolution step to the consumers.
Flagged as a contract-reconciliation follow-up (also a spec-doc edit in the external repo).

## D9 — nn_features config applies_to was silently ignored (perf + latent correctness)

Surfaced at e2e: the 2-week recalc ran >25 min because nn_features computed for ALL 6
timeframes including tf=1 (20k rows) and tf=5, though only 15/60/240 are ever used
(feature_cols + spec). Root cause = the SAME bug the task-03 review caught for align: real
(non-placeholder) IndicatorFields take `applies_to` from the class, not from config, because the
registry factories pass only `**cfg.params` (not `cfg.applies_to`). So setting
`applies_to: [15, 60, 240]` in config had no effect for non-align nn_features.

**Fix:** thread `cfg.applies_to` through every nn_features registry factory + field `__init__`
(generalising the align fix), so config `applies_to` actually governs scheduling. With config
restricting nn_features to `[15, 60, 240]`, the wasteful tf=1/5/1440 nn-feature compute is
eliminated — recalc drops from >25 min toward a few minutes. Guarded by a scheduling test
asserting non-align nn_features do NOT schedule on tf=1.

## D10 — GPU made opt-in (task-01 "GPU optional" hard-failed on driverless host)

Surfaced at e2e: `docker compose run nn-train` aborted with
`nvidia-container-cli: initialization error: nvml error: driver not loaded`. Task 01 added a
hard `deploy.resources.reservations.devices` (driver: nvidia) believing it would "start CPU-only
when no GPU is present" — it does NOT; compose invokes the nvidia prestart hook which hard-fails
on a host with no driver.

**Fix:** removed the device reservation from the base `nn-train`/`simulate-nn` services (so they
run CPU-only and start anywhere) and moved it to a `docker-compose.gpu.yml` override that GPU
hosts layer in (`-f docker-compose.yml -f docker-compose.gpu.yml`). `resolve_device("auto")` then
selects CUDA when present. This is the correct "GPU optional" shape: CPU default everywhere, GPU
opt-in.

## D11 — vol_regime window (200) incompatible with INDICATOR_WINDOW_ROWS (105)

Surfaced at e2e step 3 (`no usable rows`): `DataPreparer` computes each indicator on a slice of
≤ `INDICATOR_WINDOW_ROWS` (=105) closed candles, so `NNVolRegimeField`'s `window=200` (task-03
spec) can never fill a window → `vol_regime` is 100% NaN for every TF, and any spec listing it
drops ALL rows. The field is correct standalone; the bug is window > slice size.

**Fix:** default `vol_regime` window 200→100 (≤105) + a loud `ValueError` guard when
`window > INDICATOR_WINDOW_ROWS` (so the footgun explodes at construction, not silently at
dataset build). The verification spec drops `vol_regime` (uses the 5 other valid features) to
avoid a 42-min re-recalc; a fresh recalc will populate vol_regime correctly with the new window.

## D8 correction — nn-train also needs RW /trader_data

D8 initially kept nn-train RO. e2e step 5 showed training ALSO writes
`shared/training_state.pkl` under /trader_data (the dashboard progress file), so the RO mount
crashed training (`OSError: Read-only file system`). Both nn-train and simulate-nn now mount
/trader_data RW; neither mutates df_with_indicators.pkl (training reads it; infer writes only the
additive df_with_nn.pkl). A stricter design would relocate training_state.pkl + df_with_nn.pkl to
_long, but that ripples into the dashboard/consumer read paths — deferred as the contract-
reconciliation follow-up already noted in D8.

## Final whole-branch review — READY to merge

All 7 cross-cutting contracts hold at the integration seams; no Critical/Important DEFECT; no
must-fix-before-merge Minors; decisions D1/D5/D6/D8/D9/D10/D11 judged sound. E2E verified on the
2-week dataset (recalc → dataset → train → checkpoint → infer → df_with_nn.pkl → consumer join).

### Recommended follow-up tasks (capability/housekeeping, non-blocking)
1. Wire `TrainingLoop` into `Trainer._run_train_nn` (the Optuna+LLM search loop is implemented +
   tested but dormant; single-shot `orch.train()` is the current path). Highest-value: enables the
   "investigation" half. The promote-gate split (orch.train(promote=False) + loop._maybe_promote)
   already exists for this.
2. Wire `join_nn_results` into the REAL viewer (`view_full.py` → `frontend.data_viewer.FullData`)
   so `nn_res_*` surfaces in the dashboard (consumer join currently only on data.FullData/Sim/Live).
3. Re-recalc the dataset and re-add `vol_regime` to `configs/nn_spec.yaml` (now window≤105).
4. Housekeeping: remove dead `DataPreparer.nn_output_path`; add explicit `image:` tags to
   nn-train/simulate-nn; (compose RO-comment already corrected).
5. Spec-doc edits in the external repo: task-11 run_inference signature (D5); group_nn references.

## Follow-ups implemented (post-review)

1. **TrainingLoop wired into nn_train** (the "investigation" path). `_run_train_nn` now runs the
   agentic Optuna search by default (`NN_TRAIN_MODE=search`); `single` preserves single-shot
   `orch.train`. search_config from `configs/nn_search.yaml`; study_name `NN_STUDY` or
   `{pair}_{spec_hash[:8]}`; strategist opt-in via `NN_STRATEGIST`. VERIFIED on the 2-week data:
   6 Optuna trials (varied lr/depth/units/dropout), holdout-gated best promoted (best.json), tracking
   (index.sqlite + trial JSONs) written.
2. **Viewer NN visualisation** — `view_full.py` left-joins `df_with_nn.pkl`; a toggleable "nn"
   subplot draws the `nn_res_*` direction probabilities (up green / neutral gray / down red).
   Live-verified on the 2-week dataset.
4. **Housekeeping** — removed dead `DataPreparer.nn_output_path`; tagged nn-train/simulate-nn
   `image: simple_trader_nn`; corrected the compose RW comment.
5. **Spec docs** — updated trainer-class.md / training-module.md / nn-orchestrator-class.md
   (group_nn removal, run_inference pure + run_inference_dataset, NN_CLS/NN_TGT/NN_TYPE retired,
   nn_train→TrainingLoop). Broader layer/signals specs still carry stale refs — a remaining sweep.
3. **vol_regime** — field window fixed to 100 (≤105 guard); recalc in progress to populate it, then
   re-added to the verification spec.

## D11 update — vol_regime NOT re-added (deeper prepare-path bug, deferred)

Follow-up attempt: fixed the field window to 100 (≤105 guard), re-recalc'd the 2-week data — but
`vol_regime` is STILL 100% NaN. Root cause is NOT just the window: the field computes correctly
standalone AND via `Indicators.compute_group` on a finished frame (verified: last-row bucket = 0.0,
~19752 valid on the full frame), yet `DataPreparer._compute_tf_rows` (the per-point parallel slice
recompute that materialises features) stores it all-NaN. So a long-rolling-window nn_feature is
incompatible with the per-point ≤105-row slice recompute path in a way the shorter features
(slope w=5, point-in-time diffs/cyclical) are not.

**Decision:** vol_regime stays OUT of the verification spec; the NN flow is fully functional on
the other 5 features (engineered diffs/slopes/logret/range_atr/rsi + cross-TF). The window guard
(loud ValueError on window>105) is kept. Re-adding vol_regime needs a dedicated fix — likely
batch-computing long-window nn_features on the full frame instead of per-point slices (where they
already work), or excluding them from the slice recompute. NOT pursued further here (lowest-value
item, ~43-min recalc per iteration). Logged for a future task.
