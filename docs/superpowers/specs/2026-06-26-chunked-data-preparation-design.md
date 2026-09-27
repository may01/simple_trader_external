# Chunked Data Preparation — Resumable, Progress-Observable (Design)

**Date:** 2026-06-26
**Status:** Approved
**Plan:** `plans/impl_2/phase-16-chunked-data-prep/` (to be created)

---

## Problem

`DataPreparer.prepare()` runs the full data-preparation pipeline (raw OHLCV →
wide multi-TF frame → indicators → attributes → `df_with_indicators.pkl`) as one
monolithic in-memory pass. For big datasets (e.g. the 4-year NN training set,
~2.1M 1-min rows × 6 TFs × 100+ columns) this has two operational problems:

1. **No progress signal.** The expensive per-row indicator passes are silent —
   there is no way to estimate how long a multi-hour run will take or whether it
   is still making progress.
2. **No recovery.** A crash, OOM, or kill partway through discards *all* work;
   the entire prep restarts from zero.

There is already *in-memory* row chunking (`_split_index_chunks` →
`_compute_parallel`) that fans per-(tf, row-chunk) work out to fork workers, but
it is ephemeral: nothing is persisted, nothing is resumable, nothing is logged.

This design adds **time-portion chunking with persisted part files**: the
simulation window is split into time portions, each portion is computed and
written to its own part file, completed portions are skipped on rerun, and the
parts are merged into the final output. Progress + ETA are logged per portion.
Small datasets bypass chunking entirely and run the existing single-pass path.

**Non-goal:** lowering peak memory. The merge step concatenates all parts into
one frame, exactly as the current single-pass holds the whole frame today. This
change buys *recovery and observability*, not a smaller memory footprint.
Streamed labels / NN-normalisation is a future option, explicitly out of scope.

---

## Requirements

| # | Requirement |
|---|-------------|
| 1 | Log per-portion progress with elapsed + ETA so remaining time is estimable for big datasets |
| 2 | Split prep into configurable time portions; each portion shares the grabbed data but writes a separate part of the output |
| 3 | After all portions are ready, merge the parts into one `df_with_indicators.pkl` |
| 4 | On rerun, skip portions already completed; recompute only missing/failed portions |
| 5 | Short datasets do not require splitting (single-chunk path below a configurable threshold) |
| 6 | Chunked output is equal to single-pass output within float tolerance (bit-identical where exactly reproducible) |

---

## Resolved design decisions

Settled during brainstorming; override any conflicting first-draft task text.

1. **Recovery model = part files + skip-existing.** Each time portion writes
   its own part file. Rerun checks file existence per portion; only
   missing/failed portions recompute. A final merge step concatenates the parts
   into `df_with_indicators.pkl` and deletes the parts on success.
2. **Correctness model = two-pass + merge-time globals.** Three pipeline steps
   are global / order-dependent and are NOT run independently per portion (that
   would desynchronise stats and corrupt boundary labels). Instead:
   - Pass 1 computes **base indicators** per portion (resumable).
   - A **global** step computes base-attribute stats once over all base parts.
   - Pass 2 computes **class indicators** per portion using the persisted stats.
   - The **merge** step computes labels + NN-normalisation over the full
     concatenated frame.
3. **Chunk config = time-span + row threshold.** `CHUNK_SPAN_DAYS` sets portion
   size in calendar days; `CHUNK_MIN_ROWS` is the total-row threshold below which
   the whole dataset runs as one chunk (no part files).
4. **Labels + NN-norm deferred to merge.** Profit labels are lookahead and the
   NN-normalisation is a full-frame reduction; both run after concat so chunk
   boundaries never affect them. This matches single-pass output exactly.
5. **Part files deleted after a successful merge.** The final outputs
   (`df_with_indicators.pkl`, `data_attributes.pkl`) are the durable artifacts;
   parts are scratch.

---

## Why two-pass is correct (and bit-identical)

The pipeline's only genuinely global, order-dependent concerns:

| Concern | Current single-pass | Chunked placement |
|---|---|---|
| base indicators (per-row, expensive) | step 3, over full frame from `start_ts` | **Pass 1**, per portion — each row independent → safe to chunk |
| base-attr stats (`rsi_classification.json`, `diff_stats.pkl`) | step 4, over full frame | **Global**, computed once over all base parts |
| class indicators (`classification`, `targets`) | step 5, consume stats from step 4 | **Pass 2**, per portion using persisted stats |
| profit labels (lookahead `n` candles) | step 7, on trimmed frame | **Merge**, on full concatenated frame |
| NN-norm stats (full-frame reduction) | step 9 | **Merge**, on full concatenated frame |

Two facts verified against the indicator library make this bit-identical:

- **`classification` needs 0 lookback / 0 lookahead.** Each field is a per-row
  comparison of the current row's `rsi_ma8` / `rsi_ma8_diff` against global stats
  (`indicators/library/classification.py`).
- **`targets` needs at most 1 prior row** (`.shift(1)` on already-computed
  columns) and 0 future rows (`indicators/library/targets.py`).

Consequences:

- Base-attr stats computed over the concatenated base parts equal stats computed
  over the single-pass frame: warmup rows carry NaN base indicators (base is
  filled only from `start_ts`), so they are already excluded from the
  closed-candle reductions today.
- A portion's class indicators are reproducible from its own base part plus a
  small **lookback margin** (`INDICATOR_WINDOW_ROWS × largest_tf` rows) prepended
  from the previous base part. Interior boundaries are bit-identical because the
  prepended prior row carries real base values; the portion-0 first row resolves
  to NaN for `targets` — exactly as single-pass does today (its `shift(1)` points
  at a warmup row whose base indicators are NaN).
- Labels at the final portion's tail reference rows beyond `DATA_END` → NaN, the
  same as single-pass.

---

## Flow

```
                         shared graber_data.pkl  (incl. warmup history)
                                    │
  PASS 1  base indicators           ▼      per portion 0..N
          build wide_df over [warmup_start(portion_start), portion_end)
          compute base indicators with start_ts = portion_start
          save owned rows [portion_start, portion_end)  → df_base.part_NN.pkl
          (skip portion if its base part already exists)
                                    │
  GLOBAL  base-attr stats           ▼
          stream/concat base parts → rsi_classification.json + diff_stats.pkl
          (skip if stats files already exist — current idempotent behaviour)
                                    │
  PASS 2  class indicators          ▼      per portion 0..N
          load base part NN + lookback margin from base part NN-1
          inject persisted stats, compute classification + targets
          drop lookback margin → df_with_indicators.part_NN.pkl
          (skip portion if its final part already exists)
                                    │
  MERGE                             ▼
          concat final parts in order → full frame [DATA_START, DATA_END)
          compute profit labels (full frame)
          compute NN-normalisation stats (full frame)
          atomic save df_with_indicators.pkl + data_attributes.pkl
          delete part files on success
```

### Portion boundaries

For portion `k`, with `span = CHUNK_SPAN_DAYS` days:

- `window_k = [DATA_START + k·span, min(DATA_START + (k+1)·span, DATA_END))` — the
  rows the portion *owns* and saves.
- `input_k = [warmup_start(window_k.start), window_k.end)` — the rows it *loads*;
  the leading lookback margin feeds `build_indicator_input` slices and is dropped
  before save.

Boundaries are a pure function of `(DATA_START, DATA_END, CHUNK_SPAN_DAYS)`, so a
part file's existence unambiguously means "this portion is done" — no separate
progress ledger required for skip logic.

---

## Configuration

New env vars (set per-dataset in `configs/*.env`, like the existing
`DATA_START` / `AVAIABLE_THREADS`); defaults live in `config_loader.py`.

| Var | Default | Meaning |
|---|---|---|
| `CHUNK_SPAN_DAYS` | `30` | Portion size in calendar days |
| `CHUNK_MIN_ROWS` | `200000` | Row threshold below which the dataset runs as ONE chunk (≈140 days @ 1-min). No part files, current single-pass path. Counts 1-min rows in the simulation window `[DATA_START, DATA_END)`, i.e. `(DATA_END − DATA_START) / 60000` — derived from timestamps, so the decision is made *before* any frame is built. |

- A 2-week dataset (~20k rows) is below `CHUNK_MIN_ROWS` → single chunk by
  default (current behaviour + progress logs).
- To force chunking for validation: `CHUNK_SPAN_DAYS=3 CHUNK_MIN_ROWS=0` →
  ~5 portions over a 2-week window.

---

## Progress logging / ETA

Per portion completion, per pass, to stdout (captured by docker logs) through the
existing `logs.py` logger:

```
[prepare] pass1 base-ind  portion 12/49  24%  elapsed 8m12s  ETA 25m40s  rows=518400
[prepare] pass2 class-ind portion  3/49   6%  elapsed 1m05s  ETA 16m50s  rows=129600
```

- ETA = `elapsed / portions_done × portions_remaining`, computed independently
  per pass.
- Pass-level start/finish banners; global-stats and merge steps log start/finish.
- Single-chunk path logs the same pass banners (without per-portion lines) so a
  small run is still observable.

### Intra-chunk 1% progress

Portion-boundary logging alone leaves a *long silent gap inside each portion* —
the per-row indicator pass (`_compute_tf_rows`, the expensive loop) emits nothing
until the whole portion finishes. With the default 30-day span that is a
multi-hour blackout. To fix it, the per-row loop logs a line **each time it
completes 1% of its rows**:

```
[prepare] indic tf=15 n=43200 1% (432/43200)
[prepare] indic tf=15 n=43200 2% (864/43200)
...
```

- A `_PctProgress(total, label)` helper owns the "log once per integer percent
  reached" rule; `_compute_tf_rows` ticks it once per row.
- Granularity is **per work unit** — one `(tf, row-slice)` unit, tagged with `tf`
  and the slice row count `n`. In serial mode that is one `0→100%` stream per
  timeframe; in parallel mode each fork worker reports its own slice's 1% (their
  stdout is the parent's, so the lines reach docker logs). Streams interleave but
  each is self-identifying.
- Logging only — no effect on output, so the bit-identical guarantee is preserved.
- For `total < 100` rows each row crosses more than 1%; the helper still logs at
  most once per integer percent, in order.

---

## Code shape (interface-first)

- **`DataPreparer.prepare(raw_data_path, data_start_ms)`** stays the
  single-chunk worker — semantics unchanged; it is the body the chunked path
  delegates to when below threshold.
- **`DataPreparer.prepare_chunked(raw_data_path, data_start_ms, data_end_ms)`** —
  new orchestrator: reads `CHUNK_MIN_ROWS` / `CHUNK_SPAN_DAYS`, decides
  single-vs-chunked, computes portion boundaries, drives Pass 1 → global stats →
  Pass 2 → merge, owns part-file skip logic and progress logging. Below the
  threshold it calls `prepare()` and returns.
- New internal helpers, each independently testable:
  - `_chunk_boundaries(start_ms, end_ms, span_days) -> list[(start, end)]`
  - `_pass1_base(portion) -> writes df_base.part_NN.pkl` (skips if present)
  - `_global_base_stats(base_parts)` (skips if stats present)
  - `_pass2_class(portion) -> writes df_with_indicators.part_NN.pkl` (skips if present)
  - `_merge_parts(parts) -> labels + nn-norm + atomic save + cleanup`
    (mirrors `prepare()` exactly; the `df_with_nn.pkl` left-join lives in
    *consumers*, not `prepare()`, so the merge step does not perform it)
- **`chunk_manifest.json`** in the dataset `data/` folder records a config hash
  (`DATA_START`, `DATA_END`, `CHUNK_SPAN_DAYS`). On rerun, a hash mismatch
  invalidates stale parts (config changed between runs) rather than silently
  merging incompatible portions. Skip logic itself relies on file existence;
  the manifest is a safety guard against config drift.
- **`training/trainer.py::_run_prepare_data()`** calls `prepare_chunked(...)`,
  passing `DATA_END` alongside the existing `DATA_START`.

Part-file paths derive from the existing `wide_df_path()` helper (e.g.
`df_with_indicators.part_07.pkl`, `df_base.part_07.pkl` beside it); atomic writes
reuse the temp-file + `os.rename` pattern already in `prepare()`.

---

## Error handling

- Each per-portion pass writes via temp-file + atomic rename, so a crash mid-write
  never leaves a truncated part that skip logic would mistake for "done".
- A failed portion raises; the run aborts with the portion index logged.
  Re-running resumes — completed parts are skipped, the failed portion recomputes.
- The merge step runs only when every expected final part exists; a missing part
  aborts merge with the missing index named.
- Stale parts (manifest config-hash mismatch) are deleted before Pass 1 starts.

---

## Testing

Unit / integration (pytest, mirrors existing `tests/` style):

1. `_chunk_boundaries` — exact boundaries, last-portion clamp to `DATA_END`,
   single-portion when below threshold.
2. **Equivalence** — small synthetic dataset prepared single-pass vs forced
   multi-chunk (`CHUNK_MIN_ROWS=0`, small span): assert frames equal within float
   tolerance (`pd.testing.assert_frame_equal`, `check_exact=False`).
3. **Resume** — run chunked, delete one middle part, rerun: assert only that
   portion recomputes (others untouched by mtime) and final output matches a
   clean run.
4. **Config drift** — change `CHUNK_SPAN_DAYS` between runs: assert stale parts
   are discarded, not merged.
5. **Threshold** — dataset below `CHUNK_MIN_ROWS` takes the single-chunk path
   (no part files written).

Docker-level validation (the acceptance gate):

- Prepare the 2-week `train_dataset.env` twice — default (single chunk) and
  forced multi-chunk — and diff the two `df_with_indicators.pkl` frames within
  float tolerance.
- Crash-resume on the forced multi-chunk run.

---

## Out of scope

- Lower peak memory (streamed merge / labels / nn-norm).
- Parallelism *across* portions (each portion still uses the existing in-portion
  fork pool; portions run sequentially so progress + ETA stay meaningful and
  fork memory stays bounded).
- Changing indicator semantics, config schema, or the graber.
