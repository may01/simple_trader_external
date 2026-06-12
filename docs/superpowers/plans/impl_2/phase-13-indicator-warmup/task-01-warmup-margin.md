# Task 01: Indicator Warmup Margin

**Phase:** 13 — Indicator Warmup
**Depends on:** Phase 02 (grab_binance script), Phase 09 (Graber, DataPreparer, Trainer)
**Produces:** `constants.INDICATOR_WINDOW_ROWS`, `config_loader.warmup_minutes/warmup_start_ms`, head-extension in `Graber.ensure_data`, warmup-extended grab range in `grab_binance.main()` and `Trainer._run_grab_data`
**Branch:** `indicator-warmup` (off `experimental_imp_2`), worktree `worktrees/indicator-warmup`.

## Problem

Offline pipeline (grab → prepare → simulate) has zero warmup: grabber downloads exactly
`DATA_START → DATA_END`, and simulation begins at `DATA_START`. Every indicator is NaN at
the simulation start date; on tf=1440 the slowest field (`ema_100`) needs ~100 closed daily
candles, so short datasets never produce valid daily indicators at all.

`build_indicator_input()` feeds at most **105 closed candles** per TF — that is the
authoritative warmup requirement: `105 × max(CANDLES)` minutes (= 105 days with tf 1440).

Live path is unaffected (`get_candles_history` already fetches ≥120 candles per TF).

## Design decisions

- Single source of truth: `INDICATOR_WINDOW_ROWS = 105` in `constants.py`
  (no project imports, safe everywhere). `indicators/framework.py` replaces its
  hardcoded `105`/`104` literals with it; the warmup helper derives from it.
- Warmup helper lives in `helpers.py` (imports `CANDLES` from `config_loader`,
  never from `indicators` — avoids talib at import time).
- Warmup clamps at 0 (live.env has `DATA_START=0`).
- Simulation window is **unchanged**: `begin_ts = DATA_START`. `SimulationData`
  intersects the requested range with the df index, so extra leading history is harmless.
- `DataPreparer` is unchanged: it computes indicators over whatever range
  `graber_data.pkl` covers.
- `Graber.ensure_data` currently extends only the tail; it must also fetch a missing
  **head** (warmup range earlier than existing file start).

## Docker Entry Points (existing — must keep working)

```bash
docker compose run --rm graber                              # python3 grabers/grab_binance.py
docker compose run --rm <svc> python3 trainer.py generate_full_ohlc
docker compose run --rm <svc> python3 trainer.py simulate
docker compose run --rm graber python3 -m pytest tests/     # verification
```

No compose changes. Same env vars (`DATA_START`, `DATA_END`, `PAIR`); both grab entry
points now extend the fetch start back by the warmup margin internally.

## Layer 1: Data acquisition

### Interface

```python
# constants.py
INDICATOR_WINDOW_ROWS: int  # = 105, mirrors build_indicator_input window

# helpers.py
def warmup_minutes() -> int: ...                      # INDICATOR_WINDOW_ROWS * max(CANDLES)
def warmup_start_ms(data_start_ms: int) -> int: ...   # data_start - warmup, clamped to >= 0

# training/graber.py — signature unchanged, behavior extended
class Graber:
    def ensure_data(self, symbol: str, start_ms: int, end_ms: int) -> None: ...
    # now fetches missing head when existing data starts after start_ms
```

### Integration test → data prep layer (RED in Docker)

`trainer._run_grab_data` calls `Graber.ensure_data` with
`warmup_start_ms(DATA_START)` instead of raw `DATA_START`; resulting
`graber_data.pkl` covers `[warmup_start, DATA_END)` (mock stock).

### Unit tests

- `warmup_minutes`: equals `105 * max(CANDLES)`.
- `warmup_start_ms`: happy path subtraction; clamps to 0 when result negative; 0 input → 0.
- `Graber.ensure_data` head extension: existing file starting at T, request start T−X →
  fetches `[T−X, T)`, merges, saves; no fetch when range already covered;
  tail-only and head+tail combinations; empty head fetch raises ValueError.
- `grab_binance.__main__` range: grab start extended by warmup (test via extracted
  range computation or env-driven invocation).

### Constraints / notes

- `validate_1min_spacing` runs on the merged frame — head merge must keep 1-min continuity
  (Binance listing date later than warmup start would create a gap; out of scope, existing
  validator already rejects it loudly).

## Layer 3: Test data prep — no code change

Note only: `DataPreparer.prepare` computes over the full (warmup-extended) range.
Integration test (RED first): with `CANDLES` patched small (e.g. `[1, 5]`) and a fixture
covering `105 × 5` minutes of warmup before `DATA_START`, base indicators
(momentum/trend incl. `ema_100`) are non-NaN at the first simulation timestamp.

## Layer 5: Backtesting — no code change

Note only: `trainer._run_simulate` keeps `begin_ts = DATA_START // 1000`.
Unit test asserts simulate window is NOT warmup-extended (guards against
accidentally shifting the sim start back along with the grab start).

## Execution order

1. RED: all tests above (unit + integration).
2. GREEN: `constants.INDICATOR_WINDOW_ROWS` + framework literal replacement.
3. GREEN: `helpers.warmup_minutes` / `warmup_start_ms`.
4. GREEN: `Graber.ensure_data` head extension.
5. GREEN: `trainer._run_grab_data` + `grab_binance.__main__` use `warmup_start_ms`.
6. Full suite GREEN in Docker; merge back into `experimental_imp_2`.
