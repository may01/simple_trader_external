# LiveDataCollector Class Specification

**Version:** 2.0 — Extracted from `Trainer.collect_live_data()`
**Class:** `LiveDataCollector`
**File:** `live_data_collector.py`
**Purpose:** Continuously ingest live market data from Binance on a 60-second cadence and persist snapshots for the live Robot path.


DO NOT IMPLEMENT THIS CLASS UNTIL SPECIFIC REQUEST
---

## 1. Class Overview

`LiveDataCollector` runs an infinite loop aligned to 60-second boundaries. At each tick it:

1. Updates the `LiveData` singleton from Binance via `stock.item.get_candles_history()`.
2. Triggers `Indicators.compute()` per timeframe (handled inside `LiveData.build_candles()` per Data Module v2.0 §8.1).
3. Optionally fetches depth (bid/ask) data.
4. Persists a snapshot to disk for crash recovery / replay diagnostics.
5. Sleeps until the next 60-second boundary.

In v2.0 it lives in the training module only for **historical / packaging reasons**: in v1.0 the loop was a `Trainer` method. The pipeline coupling is weak — `LiveDataCollector` does not feed `DataPreparer` or `SimulationOrchestrator`. A future revision should move this class into the robot module (see §7).

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `pair` | `str` | Trading pair. |
| `data` | `LiveData` | Reference to the `data.item` singleton from Data Module v2.0. |
| `tick_seconds` | `int` | Tick alignment interval (default 60). |
| `fetch_depth` | `bool` | If `True`, also fetch order-book depth each tick. |
| `depth_limit` | `int` | Depth row count to request (default 1000). |
| `_running` | `bool` | Loop control flag. |

---

## 3. Constructor

### `__init__(pair: str, tick_seconds: int = 60, fetch_depth: bool = True, depth_limit: int = 1000)`

**Behavior:**
1. Store inputs.
2. Resolve the `LiveData` singleton (`from data import item as data; self.data = data`).
3. Set `_running = True`.

**Preconditions:**
- Binance API credentials (`BINANCE_API_KEY`, `BINANCE_API_SECRET`) in environment.
- Network connectivity available.

---

## 4. Methods

### 4.1 `run() -> None`

**Purpose:** Main collection loop. Returns only on `stop()` or fatal error.

**Behavior:**
```python
def run(self):
    while self._running:
        start = time.time()
        cur_ts = (int(start) // self.tick_seconds) * self.tick_seconds
        self.data.cur_point = cur_ts

        self.data.build_candles(time_point=0)   # fetches + runs Indicators.compute()
        if self.fetch_depth:
            self.data.get_depth_data(self.depth_limit)

        self._persist_snapshot(cur_ts)
        elapsed = time.time() - start
        log(f"tick {cur_ts}: {elapsed:.2f}s")

        sleep_for = self.tick_seconds - (time.time() % self.tick_seconds)
        time.sleep(max(0.0, sleep_for))
```

**Notes:**
- `LiveData.build_candles(time_point=0)` triggers per-tf indicator computation via `Indicators.compute()` per Data Module v2.0 §8.1.
- Snapshot persistence is for diagnostics only — the live Robot reads from the in-memory `LiveData` singleton, not from disk.
- The loop catches transient network exceptions internally (see §5) and continues; only fatal errors break out.

---

### 4.2 `stop() -> None`

**Purpose:** Request a graceful loop exit (set `_running = False`). The loop exits at the next iteration boundary.

---

### 4.3 `_persist_snapshot(ts: int) -> None`

**Purpose:** Save candles + depth snapshot to disk.

**Behavior:**
1. Construct path: `{root_folder(pair)}/live_snapshots/{ts}/`.
2. Pickle each `ohlc[tf]` DataFrame to `{path}/{tf}.pkl`.
3. If depth fetched, pickle to `{path}/depth.pkl`.

Snapshots older than a configurable retention window (default 24h) can be pruned by a separate housekeeping process — not part of this class.

---

## 5. Error Handling

| Condition | Behavior |
|-----------|----------|
| Binance API transient error (rate limit, 5xx, timeout) | Caught; logged with backoff; loop retries next tick. |
| Binance API auth failure | Raised; loop terminates. |
| Snapshot persist failure (disk full, permission) | Logged; loop continues (snapshot is non-critical). |
| `Indicators.compute()` failure (typically a bad field config) | Raised; loop terminates so the operator notices. |

Retries are explicitly **not** done with sleep loops — if a tick fails, the next 60s tick is the next retry opportunity.

---

## 6. Lifecycle

```
Trainer.run("collect_live")
   └─ LiveDataCollector(pair).run()
        loop:
          fetch → indicators.compute → depth → persist → sleep
        terminated by:
          - operator kills the process (SIGTERM/SIGINT)
          - stop() called externally
          - fatal exception (auth, indicator config error)
```

This is the only RUN_TYPE that does not terminate on its own.

---

## 7. Constraints and Invariants

- **One collector per pair.** Multiple instances would race on the `LiveData` singleton.
- **No coupling to offline pipeline.** Snapshots written by this class are not consumed by `DataPreparer` or `SimulationData`.
- **Indicator parity.** Both live and simulation paths must use the same indicator implementations (per Data Module v2.0 §11 — config-driven registry). NN forward-looking target fields are excluded from the live `Indicators` instance.
- **Tick alignment is strict.** Snapshot timestamps must be exact multiples of `tick_seconds`. Sleeps target the boundary, not "tick_seconds from now".

---

## 8. Future Refactor

This class is a candidate to move to the robot module (`robot/live_data_collector.py`) along with `LiveData`. Reasons:
- It writes to `LiveData`, not the training pipeline outputs.
- It runs in production, not training.
- The training module would become offline-only, simplifying its scope.

Out of scope for v2.0. Tracked as a follow-up.

---

## 9. Testing Notes

- **Loop alignment:** mock `time.time()` to verify `cur_ts` is always a multiple of `tick_seconds` and sleeps target the next boundary.
- **Error resilience:** mock `LiveData.build_candles()` to raise a transient `ConnectionError` once → assert the loop continues to the next tick.
- **Snapshot layout:** assert `_persist_snapshot(ts)` produces files under the expected path structure with one pickle per active timeframe.
