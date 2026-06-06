# Graber Class Specification

**Version:** 2.0 — New class introduced as part of Trainer decomposition
**Class:** `Graber`
**File:** `grabers/graber.py`
**Purpose:** Fetch 1-minute OHLCV candles from Binance for a requested time range and persist them as `graber_data.pkl`.

---

## 1. Class Overview

`Graber` owns the **data retrieval** phase of the training pipeline. It is a class-based reimplementation of `grabers/grab_binance.py`: it connects to the Binance API, downloads 1-minute klines for the configured pair and time range, and writes them to `{root_folder(pair)}/graber_data.pkl` in the schema expected by Data Module v2.0 §10 (raw 1-min OHLCV).

It is the **only** class in the training module that performs network I/O.

**Scope boundary:**
- **Owns:** Binance API auth, pagination, rate-limit handling, retries, schema conversion, persistence of `graber_data.pkl`.
- **Does not own:** building the wide base DataFrame (`{tf}_open/high/low/close/...`). That responsibility belongs to `DataPreparer`. `Graber`'s output is the raw 1-min frame on disk; everything downstream loads it from there.

The existing `grabers/grab_binance.py` entry-point script is preserved as a thin wrapper that instantiates `Graber` and calls `grab()` so existing docker-compose `SCRIPT_TYPE=grabers/grab_binance` invocations continue to work.

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `pair` | `str` | Trading pair (`coin_base` format, e.g. `link_usdt`). |
| `_client` | Binance API client | Constructed at init from `BINANCE_API_KEY` / `BINANCE_API_SECRET`. |
| `_output_path` | `str` | `{root_folder(pair)}/graber_data.pkl`. |
| `_request_limit` | `int` | Max klines per Binance request (default `1000`, Binance's hard cap). |
| `_retry_attempts` | `int` | Number of retry attempts for transient errors (default `5`). |
| `_retry_backoff_seconds` | `float` | Initial backoff between retries (default `1.0`, doubles per attempt). |

---

## 3. Constructor

### `__init__(pair: str)`

**Behavior:**
1. Store `pair`.
2. Read Binance credentials from env (`BINANCE_API_KEY`, `BINANCE_API_SECRET`). Raise `KeyError` if absent.
3. Instantiate the Binance client (`python-binance` or equivalent).
4. Compute `_output_path`.

**Postconditions:**
- Instance is ready to call `grab(...)`.
- Network connection to Binance is verified lazily — auth failures surface on the first request, not at construction.

---

## 4. Methods

### 4.1 `grab(begin_ts: int, end_ts: int, mode: str = "incremental") -> pd.DataFrame`

**Purpose:** Download 1-min OHLCV candles for `[begin_ts, end_ts]` and persist them to `_output_path`.

**Parameters:**
- `begin_ts` — Unix timestamp in **seconds** (inclusive).
- `end_ts` — Unix timestamp in **seconds** (inclusive).
- `mode` — `"incremental"` (default) or `"overwrite"`:
  - **`"incremental"`** — Load existing `graber_data.pkl` if present; fetch only the rows outside its covered range; merge and resave.
  - **`"overwrite"`** — Ignore any existing file; fetch the full range; replace `graber_data.pkl`.

**Behavior:**
1. **Range planning.**
   - If `mode == "incremental"` and `_output_path` exists, load the existing file and compute the missing prefix `[begin_ts, existing.index.min())` and suffix `(existing.index.max(), end_ts]` — fetch only those.
   - Otherwise, plan a single full-range fetch for `[begin_ts, end_ts]`.
2. **Paginated fetch.** Binance returns at most `_request_limit` klines per call (1000 minutes ≈ 16h40m). For each planned chunk:
   - Issue `client.get_klines(symbol=..., interval="1m", startTime=..., endTime=..., limit=...)`.
   - Move the cursor forward by the last returned timestamp + 1 minute.
   - Repeat until the chunk is covered.
3. **Schema conversion.** Each returned kline is `[open_time, open, high, low, close, volume, close_time, quote_asset_volume, n_trades, taker_buy_base, taker_buy_quote, ignore]`. Convert to a DataFrame with:

   | Output column | Source field |
   |---------------|--------------|
   | `open_time` | `open_time` (Timestamp; also becomes the index) |
   | `o` | `open` (float) |
   | `h` | `high` (float) |
   | `l` | `low` (float) |
   | `c` | `close` (float) |
   | `v` | `volume` (float) |
   | `close_time` | `close_time` (Timestamp) |
   | `taker_base_vol` | `taker_buy_base` (float) |

   Index: 1-min `DatetimeIndex` (UTC) built from `open_time`.
4. **Validate.** Reject any chunk that is not strictly 1-min spaced or has duplicate timestamps. Raise `ValueError` with the offending range.
5. **Merge.** If `mode == "incremental"` and an existing file was loaded, concatenate `(prefix, existing, suffix)` and sort by index.
6. **Persist.** Write to `_output_path` via temp-file + atomic rename.
7. **Return** the DataFrame written.

**Return:** `pd.DataFrame` indexed by 1-min `DatetimeIndex`, columns `[open_time, o, h, l, c, v, close_time, taker_base_vol]`.

**Preconditions:**
- `BINANCE_API_KEY` and `BINANCE_API_SECRET` are set.
- Network connectivity to Binance is available.
- `_output_path` directory exists (or is creatable).

**Postconditions:**
- `_output_path` contains a strictly 1-min spaced DataFrame covering at least `[begin_ts, end_ts]`.
- No duplicate timestamps; no gaps within the requested range.

**Exceptions:**
- `KeyError` — env credentials missing.
- `BinanceAPIException` — auth failure, invalid symbol, or non-retryable API error (propagated after retries exhausted).
- `ValueError` — schema validation failed (duplicate or non-contiguous timestamps).
- `IOError` — write to `_output_path` failed.

---

### 4.2 `_fetch_chunk(symbol: str, chunk_begin_ms: int, chunk_end_ms: int) -> list[list]`

**Purpose:** Private helper for one paginated API call, with retry handling.

**Behavior:**
- Call `client.get_klines(...)`.
- On `BinanceAPIException` with retryable code (rate-limit 429, server 5xx, timeout): sleep `_retry_backoff_seconds × 2**attempt` and retry up to `_retry_attempts` times.
- On non-retryable error or retries exhausted: raise.

---

### 4.3 `grab_from_env() -> pd.DataFrame`

**Purpose:** Convenience wrapper that pulls `begin_ts` / `end_ts` from `DATA_START` / `DATA_END` env vars (divided by 1000 since they are milliseconds) and calls `grab()`.

This is the entry point used by the `grab_data` RUN_TYPE (see [trainer-class.md](trainer-class.md) §4.1) and by the legacy `grabers/grab_binance.py` wrapper.

---

## 5. Interaction Contract

```
RUN_TYPE=grab_data
   ↓
Trainer.run("grab_data")
   ↓
Graber(pair).grab_from_env()
   ↓ Binance API (paginated klines)
{root_folder(pair)}/graber_data.pkl   ← raw 1-min OHLCV on disk
   ↓ (later, RUN_TYPE=generate_full_ohlc)
DataPreparer(pair).prepare()          ← reads graber_data.pkl
   ↓
df_with_indicators.pkl
```

`Graber` and `DataPreparer` do not share in-memory data. `graber_data.pkl` on disk is the boundary between them.

---

## 6. Output Schema

`graber_data.pkl` matches the schema documented in Data Module v2.0 §10 (`graber_data.pkl` row).

```
index (DatetimeIndex, 1-min UTC, from open_time)
columns:
  open_time        Timestamp candle open time (also the index)
  o                float64   open price
  h                float64   high price
  l                float64   low price
  c                float64   close price
  v                float64   volume (base asset)
  close_time       Timestamp candle close time
  taker_base_vol   float64   taker buy volume (base asset)
```

Invariants:
- Index is strictly increasing with `freq="1min"`.
- No duplicate timestamps.
- No null values; missing minutes (Binance gap) cause `grab()` to raise `ValueError`.

---

## 7. Error Handling

| Condition | Behavior |
|-----------|----------|
| Missing env credentials | `KeyError` at construction. |
| Auth failure on first request | `BinanceAPIException` propagated immediately, no retries. |
| Rate limit (429) | Backoff and retry up to `_retry_attempts`. |
| Transient server error (5xx, timeout) | Backoff and retry up to `_retry_attempts`. |
| Persistent network failure | After retries exhausted: raise `BinanceAPIException`. Partial data is NOT written. |
| Schema mismatch / missing minute | Raise `ValueError` with offending timestamp range. |
| Disk write failure | `IOError`. Existing `graber_data.pkl` (if any) is left intact thanks to temp-file + atomic rename. |

---

## 8. Testing Notes

- **Mock the Binance client.** Inject a fake client that returns canned kline lists for testable pagination logic.
- **Pagination boundary:** request a range slightly larger than `_request_limit` minutes → assert two API calls were made, second one starts at the correct cursor.
- **Incremental merge:** seed `graber_data.pkl` with rows for `[T₁, T₂]`, call `grab(T₀, T₃, mode="incremental")` → assert two fetches (prefix `[T₀, T₁)` and suffix `(T₂, T₃]`), merged output covers `[T₀, T₃]`.
- **Overwrite mode:** seed `graber_data.pkl`, call `grab(T₀, T₃, mode="overwrite")` → assert one full fetch and the existing file is replaced.
- **Retry on 429:** mock client raises `429` twice then succeeds → assert 3 attempts total, backoff applied.
- **Schema validation:** mock client returns a kline list with a duplicate timestamp → `grab()` raises `ValueError`.

---

## 9. Constraints and Invariants

- **Network is the only source.** `Graber` does not read from a CSV or any other on-disk source.
- **`graber_data.pkl` is the only output.** No side effects on indicators, stats files, or any other artifact.
- **Atomic writes.** The output file is written via temp-file + rename so partial downloads never corrupt a previous valid file.
- **Idempotent in incremental mode.** Calling `grab(begin, end, mode="incremental")` twice with the same range produces the same file content (no duplicate rows).
- **No indicator math.** All field derivation is downstream of `Graber` in `DataPreparer`.
- **Time unit boundary.** Binance API takes timestamps in **milliseconds**; `grab()` accepts **seconds** and converts internally. `DATA_START` / `DATA_END` env vars are milliseconds and are divided by 1000 by `grab_from_env()`.

---

## 10. Relationship to Legacy `grab_binance.py`

`grabers/grab_binance.py` is retained as a thin shim:

```python
# grabers/grab_binance.py
from grabers.graber import Graber
import os

if __name__ == "__main__":
    Graber(os.environ["PAIR"]).grab_from_env()
```

This preserves the `SCRIPT_TYPE=grabers/grab_binance docker-compose up` workflow documented in `CLAUDE.md`. New code should call `Graber` directly or use `RUN_TYPE=grab_data` through the `Trainer`.
