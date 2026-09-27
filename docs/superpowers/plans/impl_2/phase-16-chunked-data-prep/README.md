# Phase 16 — Chunked, Resumable Data Preparation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement task-by-task. Steps use checkbox tracking.

**Goal:** Make `DataPreparer` resumable and progress-observable for big datasets by splitting preparation into persisted time-portion part files, skipping completed portions on rerun, and merging the parts into the final output — without changing the output (bit-identical to single-pass within float tolerance).

**Spec:** `specs/2026-06-26-chunked-data-preparation-design.md`

**Layer:** 3 — Test data prep (`training/data_preparer.py`). Docker entry is the **existing** `ohlc_gen` compose service; no new service, no new bottom layer. This phase extends one layer.

---

## Why this phase exists

`DataPreparer.prepare()` runs the full pipeline as one silent in-memory pass.
For the 4-year NN dataset (~2.1M 1-min rows) that means no progress/ETA signal
and total loss of work on any crash. This phase adds time-portion chunking with
on-disk part files (resume by skipping existing parts) and per-portion ETA
logging. Small datasets stay on the current single-pass path.

The output is unchanged: the chunked path is a **two-pass + merge-time-globals**
reorganisation that reproduces single-pass results (see spec "Why two-pass is
correct").

---

## Requirements covered

| # | Requirement | Task |
|---|-------------|------|
| 1 | Per-portion progress + ETA logging | 02, 07 |
| 2 | Configurable time-portion split; portions share grabbed data, write separate parts | 01, 03, 05 |
| 3 | Merge parts into one `df_with_indicators.pkl` | 06 |
| 4 | Skip completed portions on rerun; recompute only missing | 03, 05, 07 |
| 5 | Short datasets bypass splitting (single-chunk threshold) | 01, 07 |
| 6 | Chunked output equals single-pass within float tolerance | 04, 05, 08 |

---

## Docker Entry Points (ground truth — defined before any layer)

The existing prepare command is unchanged; chunking is transparent and driven by
env vars in the dataset's `.env` file.

```bash
# Prepare a dataset (chunked automatically when above CHUNK_MIN_ROWS).
TRAIN_ENV=configs/my_dataset.env docker compose up ohlc_gen

# Force chunking on a small dataset (validation):
# add to the env file or pass inline
TRAIN_ENV=configs/train_dataset.env CHUNK_SPAN_DAYS=3 CHUNK_MIN_ROWS=0 \
    docker compose up ohlc_gen
```

These commands are the contract. Implementation must make them work: `ohlc_gen`
runs `trainer.py generate_full_ohlc` → `RUN_TYPE=prepare_data` →
`_run_prepare_data()` → `DataPreparer.prepare_chunked(...)`.

Verified: [ ] `CHUNK_SPAN_DAYS=3 CHUNK_MIN_ROWS=0 ... docker compose up ohlc_gen`
on `train_dataset.env` writes `df_with_indicators.part_*.pkl` then a merged
`df_with_indicators.pkl`, and the result matches a single-chunk run within float
tolerance.

---

## Global Constraints

- **Bit-identical output.** Chunked `df_with_indicators.pkl` must equal the
  single-pass frame within float tolerance (`assert_frame_equal`, `check_exact=False`).
- **Share grabbed data.** All portions read the one `graber_data.pkl`; the graber
  is untouched. Portion lookback comes from earlier rows of the same file.
- **Atomic writes.** Every part + final file writes via temp-file + `os.rename`
  (existing pattern) so a crash never leaves a truncated file that skip logic
  treats as done.
- **No memory goal.** Merge concatenates all parts (same peak frame as today).
  Recovery + observability only.
- **Env config:** `CHUNK_SPAN_DAYS` (default 30), `CHUNK_MIN_ROWS` (default 200000,
  counts 1-min rows in `[DATA_START, DATA_END)`).
- **Sequential portions.** Portions run one at a time (each still uses the existing
  in-portion fork pool); no cross-portion parallelism, so ETA stays meaningful.

---

## Layer interface (what the chunked path adds to `DataPreparer`)

```python
def prepare_chunked(self, raw_data_path: str, data_start_ms: int, data_end_ms: int) -> None: ...
```

Single public entry. Below `CHUNK_MIN_ROWS` it delegates to the unchanged
`prepare(raw_data_path, data_start_ms)`. Internal helpers (tasks 01–06) are
private to `DataPreparer` / `training/data_preparer.py`.

---

## Task list

| Task | Deliverable |
|------|-------------|
| 01 | Chunk config (`chunk_config()`) + `_chunk_boundaries()` + part-path helpers |
| 02 | `_ChunkProgress` ETA logger |
| 03 | Pass-1 base-indicator portion worker (+ skip-if-exists) |
| 04 | Global base-attr stats from base parts |
| 05 | Pass-2 class-indicator portion worker (+ boundary lookback, skip-if-exists) |
| 06 | Merge: concat parts → labels → nn merge → nn-norm → atomic save → cleanup |
| 07 | `prepare_chunked` orchestrator + manifest config-guard + trainer wiring |
| 08 | Docker validation: single-vs-multi equivalence + crash-resume (2-week set) |
| 09 | Intra-chunk 1% progress logging (`_PctProgress` in `_compute_tf_rows`) |

Tasks 01–06 build the private helpers; each is independently unit-testable. Task
07 wires them and is the integration point. Task 08 is the acceptance gate.
