# MEXC Candles Stock — read-only OHLCV for margin (spot book) and futures

**Date:** 2026-09-26
**Scope:** Stock Abstraction Module (+ touch points in Graber, Trainer, Indicators, base resampler)
**Repo:** `main/` (simple_trader). Trading on MEXC lives in `trade_executor` (see `external/executor/specs/2026-09-25-mexc-trading-connector-design.md`); this spec adds **no** order, account, loan or private-endpoint code to `main/`.
**Status:** design — awaiting review

---

## 1. Goal

Let `main/` use MEXC market data wherever it uses Binance data today:

- **Backfill:** `Graber.ensure_data()` → `graber_data.pkl` (1m base), via `stock.get_candles_range()`.
- **Live:** `trader.py` / `LiveData.build_candles()` → `stock.get_candles_history()` every tick, and `LiveDataCollector` (1m append).

Two markets, selected by `STOCK_TYPE`:

| `STOCK_TYPE` | Market | Symbol (for `PAIR=link_usdt`) | Endpoint |
|---|---|---|---|
| `mexc_margin` | spot order book (MEXC margin trades on the spot book) | `LINKUSDT` | `GET https://api.mexc.com/api/v3/klines` |
| `mexc_futures` | USDT-M perpetual | `LINK_USDT` | `GET https://api.mexc.com/api/v1/contract/kline/{symbol}` |

Success = with either `STOCK_TYPE`, (a) `trainer` grab stage fills a ≤30-day `graber_data.pkl` that `DataPreparer` consumes unchanged, (b) `trader.py` runs live on real MEXC candles with indicators and MQ broadcast working, (c) no call path in `main/` can place, cancel or query orders / account on MEXC.

### Non-goals

- Trading, account, borrow/repay, private endpoints, API keys (executor owns these).
- Order-book depth, websocket feeds, funding/mark/index-price klines.
- Backfill older than MEXC's 1m retention (see §3.2) — no Binance splicing, no coarse-interval fallback. Long history for MEXC comes only from our own archive (§7).
- Multi-resolution raw storage (per-TF native backfill). Considered and rejected for now (§11).

---

## 2. Decisions (from brainstorming 2026-09-26)

| # | Decision |
|---|---|
| D1 | Feed both backfill and live paths (parity with `binance_candles`). |
| D2 | `mexc_margin` = spot-book klines. Evidence: `exchangeInfo` reports `isMarginTradingAllowed=false` for all 1907 symbols (probe 2026-09-26); margin positions on MEXC trade the spot book, so its candles are the spot candles. |
| D3 | Own thin REST client on `requests` (already installed transitively via python-binance, v2.31.0); no ccxt, no keys. Pin `requests` explicitly in `requirements.txt`. |
| D4 | 1m base only. Backfill request older than retention **fails fast** (`MexcHistoryUnavailable`); nothing partial is written. |
| D5 | MEXC has no taker-buy volume → `taker_base_vol = NaN`, stock reports `has_taker_volume = False`; taker-dependent indicators are excluded explicitly (§6), never fed fake data. |
| D6 | Futures OHLC from `realOpen/realHigh/realLow/realClose` (actual trades); volume converted from contracts to base asset (`vol × contractSize`). |
| D7 | Graber writes a venue sidecar and refuses to merge data from a different venue/market into an existing file. |

---

## 3. Exchange facts (live probe, 2026-09-26, LINK)

### 3.1 Endpoints and payloads

**Spot** `GET /api/v3/klines?symbol=LINKUSDT&interval=1m&startTime=<ms>&endTime=<ms>&limit=500`

```
[[1790410620000,"14.05","14.05","14.025","14.025","8.36",1790410680000,"117.273"], ...]
  openTime(ms), open, high, low, close, volume(base), closeTime(ms, = open+60000), quoteVolume
```

- Max 500 rows per call (`limit=5000` returned 500).
- `startTime` without `endTime` is **ignored** (returns latest rows) → always send both.
- Intervals: `1m 5m 15m 30m 60m 4h 1d 1W 1M`. `1h` → `{"code":-1121,"msg":"Invalid interval."}`.
- Rows are start-anchored within `[startTime, endTime]`.

**Futures** `GET /api/v1/contract/kline/LINK_USDT?interval=Min1&start=<s>&end=<s>`

```json
{"success":true,"code":0,"data":{
  "time":[1790410560,...],            // seconds
  "open":[...],"high":[...],"low":[...],"close":[...],     // open = previous close (continuity)
  "realOpen":[...],"realHigh":[...],"realLow":[...],"realClose":[...],  // actual trades
  "vol":[9260.0,...],                 // contracts
  "amount":[13000.2871,...]}}         // quote volume
```

- Max 2000 rows per call; if the window holds more, the **latest** 2000 are returned (end-anchored) → windows must be ≤ 2000 intervals.
- Intervals: `Min1 Min5 Min15 Min30 Min60 Hour4 Hour8 Day1 Week1 Month1`.
- Same payload from `contract.mexc.com` and `api.mexc.com`; use `api.mexc.com` (matches executor).
- `GET /api/v1/contract/detail?symbol=LINK_USDT` → `contractSize=0.1`, `priceUnit=0.001`, `volUnit=1`.
- Observed: `high` can include the carried previous close (14.028) while `realHigh` is the true trade high (14.025). Hence D6.

### 3.2 Retention (rolling, both markets unless noted)

| Interval | Depth |
|---|---|
| 1m | ~30 days (30d ok, 31d empty) |
| 5m, 15m | ~1 year (360d ok, 370d empty) |
| 30m | spot < 1y; futures deep |
| 60m, 4h, 1d | since listing (spot ≥ 2500d; futures ≥ 2000d, < 2500d) |

Only the 1m row matters for this spec (D4). Retention is a policy of the exchange and may change; it is a constant, not derived at runtime (§5.4).

### 3.3 Rate limits

- Spot: 300 weight / 10 s per IP (executor spec F7); `klines` weight 1.
- Futures public: 20 requests / 2 s.
- Budget at 70 % (same rule as the executor spec §9): spot ≤ 21 req/s, futures ≤ 7 req/s.

---

## 4. Architecture

```
stocks/
  mexc/
    __init__.py
    errors.py            MexcApiError, MexcHistoryUnavailable, MexcDataGap
    rate_limiter.py      TokenBucket
    kline_source.py      KlineSource protocol + SpotKlineSource + FuturesKlineSource
    normalize.py         to_range_frame(), to_history_frame(), fill_minute_gaps()
  mexc_candles_stock.py  Stock_MexcCandles(StockInterface)
stocks_holder.py         + "mexc_margin", "mexc_futures"
```

Layering (each unit testable alone):

1. **`KlineSource`** — HTTP only. Knows URL, symbol, interval codes, paging, ms/s, retries, rate limit. Returns a canonical raw frame; knows nothing about Graber, TFs or the pipeline.
2. **`normalize`** — pure functions on DataFrames: column naming, close-time, gap fill, closed-candle cut. No I/O.
3. **`Stock_MexcCandles`** — implements the `StockInterface` candle contract on top of 1 + 2; refuses every trading/account call.

### 4.1 `KlineSource` interface

```python
class KlineSource(Protocol):
    market: str             # "margin" | "futures"
    symbol: str             # "LINKUSDT" | "LINK_USDT"
    page_rows: int          # 500 | 2000

    def fetch(self, interval_min: int, start_ms: int, end_ms: int) -> pd.DataFrame:
        """Closed-open [start_ms, end_ms). Pages internally.
        Returns canonical raw frame:
          index  open_time  DatetimeIndex[UTC] (from ms)
          cols   open, high, low, close, volume   float64   (volume in BASE asset)
        Sorted, de-duplicated (keep="last"). May be empty. Raises MexcApiError."""
```

Interval maps (`interval_min → code`); any other value raises `ValueError`:

| min | spot | futures |
|---|---|---|
| 1 | `1m` | `Min1` |
| 5 | `5m` | `Min5` |
| 15 | `15m` | `Min15` |
| 30 | `30m` | `Min30` |
| 60 | `60m` | `Min60` |
| 240 | `4h` | `Hour4` |
| 1440 | `1d` | `Day1` |

**`SpotKlineSource(symbol)`** — pages forward in windows of `500 × interval`; sends `startTime`, `endTime`, `limit=500`; `volume` = field 5.

**`FuturesKlineSource(symbol)`** — pages forward in windows of `2000 × interval` (seconds on the wire, `end` inclusive → request `end = window_end_s - 1`); OHLC from `real*`; `volume = vol × contract_size`. `contract_size` fetched once from `contract/detail` at construction and cached; `success=false` or missing symbol → `MexcApiError`. If a `real*` value is null/0 for a row, fall back to the continuity field for that row and count it (logged once per fetch).

**HTTP policy (both):**

- `requests.Session`, timeout 10 s, `User-Agent: simple_trader/mexc-candles`.
- Token bucket per source instance (§3.3 budgets); acquired before every request.
- Retry on network error, timeout, HTTP 429, HTTP 5xx: 5 attempts, backoff 1/2/4/8/16 s, honour `Retry-After` when present. Exhausted → `MexcApiError(kind="transient")`.
- Any other 4xx, spot `{"code": ...}` error body, or futures `success=false` → `MexcApiError(kind="client", code=..., msg=...)` immediately, no retry.
- Base URLs overridable by env `MEXC_SPOT_BASE_URL`, `MEXC_FUTURES_BASE_URL` (tests only; defaults `https://api.mexc.com`).

### 4.2 `normalize`

```python
def cut_unclosed(df: pd.DataFrame, interval_min: int, now_ms: int) -> pd.DataFrame
    # drop rows with open_time + interval > now (forming candle)

def fill_minute_gaps(df: pd.DataFrame, start_ms: int, end_ms: int,
                     max_gap_min: int) -> tuple[pd.DataFrame, int]
    # reindex to the full 1m grid [first_expected, last_row]; a missing minute becomes
    # o=h=l=c=previous close, v=0. Returns (frame, n_filled).
    # Any single run of missing minutes > max_gap_min, or a head gap
    # (first row later than start_ms by > max_gap_min) → MexcDataGap(start, end, minutes).

def to_range_frame(df: pd.DataFrame) -> pd.DataFrame
    # Graber raw format (same as Stock_Binance.get_candles_range):
    #   index open_time (UTC)
    #   o, h, l, c, v            float64
    #   close_time               int64 ms  = open_time_ms + 59_999   (Binance parity)
    #   taker_base_vol           float64   all NaN

def to_history_frame(df: pd.DataFrame) -> pd.DataFrame
    # live format: open, high, low, close, volume, taker_base_vol(NaN)
```

`max_gap_min` default 60, env `MEXC_MAX_GAP_MIN`. Rationale: LINK trades every minute on both books; a short hole is a missing no-trade minute, a long one is an exchange outage that must not be papered over.

---

## 5. `Stock_MexcCandles`

```python
class Stock_MexcCandles(StockInterface):
    stock_name: str          # "mexc_margin" | "mexc_futures"
    exchange = "mexc"
    market: str              # "margin" | "futures"
    has_taker_volume = False

    def __init__(self, market: str): ...
```

### 5.1 Construction

- Reads `PAIR` (e.g. `link_usdt`) → `coin="link"`, `coin_base="usdt"`; `EXCHANGE_FEE` → `self.fee`. Never reads any API key/secret env var.
- `get_pair_name()` → `"LINKUSDT"` (margin) or `"LINK_USDT"` (futures).
- Builds the matching `KlineSource`. Futures construction performs the `contract/detail` call; failure raises (startup must fail loudly, not trade on a stock with unknown contract size).
- `self.was_init = True`.

### 5.2 `get_candles_range(symbol, start_ms, end_ms) -> DataFrame`

1. `symbol` must equal `get_pair_name()`, else `ValueError` (catches the Trainer `LINKUSDT` vs `LINK_USDT` mix-up, §8.2).
2. Retention guard: `oldest = now_ms - MEXC_1M_RETENTION_DAYS*86_400_000 + RETENTION_MARGIN_MS` (30 d, margin 1 h). `start_ms < oldest` → `MexcHistoryUnavailable(start_ms, oldest)`; message names `DATA_START`, the oldest reachable UTC time, and the remedy (move `DATA_START`, or use the collector archive).
3. `source.fetch(1, start_ms, end_ms)` → `cut_unclosed` → `fill_minute_gaps` → `to_range_frame`.
4. Empty result for a non-empty in-retention range → `MexcDataGap` (Graber's own empty-result `ValueError` stays as a second line of defence).
5. Logs `n_filled` when > 0.

### 5.3 `get_candles_history(time_list, coin, time_point=0) -> {tf: DataFrame}`

Same shape and semantics as `Stock_Binance.get_candles_history` (≤ 120 rows per TF, forming candle **kept** as the last row, missing base rows forward-filled). Base plan:

| base interval | lookback | TFs served | rows ≈ | calls spot / futures |
|---|---|---|---|---|
| 1m | 10 h | 1, 5 | 600 | 2 / 1 |
| 15m | 4 d | 15 | 384 | 1 / 1 |
| 60m | 43 d | 60, 240 | 1032 | 3 / 1 |
| 1d | 121 d | 1440 | 121 | 1 / 1 |

(Binance uses 12h for 1440; MEXC has no 12h, and 1d is native.) Only groups with a requested TF are fetched. Resampling uses the shared `StockInterface._resample_to_tf` (§8.1 fix). `taker_base_vol` column is present and NaN on every TF.

Per tick cost ≤ 7 spot / 4 futures requests — well inside the §3.3 budgets at the 1 s tick; the token bucket enforces it regardless.

### 5.4 Constants (`stocks/mexc/__init__.py`)

```python
MEXC_1M_RETENTION_DAYS = 30
RETENTION_MARGIN_MS = 3_600_000
SPOT_PAGE_ROWS = 500
FUTURES_PAGE_ROWS = 2000
SPOT_REQ_PER_SEC = 21
FUTURES_REQ_PER_SEC = 7
```

### 5.5 Refused / unsupported surface

- `trade`, `order_info`, `cancel_order`, `funds`, `get_aviable_loan`, `borrow`, `repay` → log WARNING `"<method> refused: STOCK_TYPE=<name> is read-only"` and return `(STATUS_FAIL, <empty>)` — identical contract to `Stock_BinanceCandles._refuse`.
- `depth`, `info` → `NotImplementedError("MEXC candles stock provides OHLCV only")`. Verified 2026-09-26: the only live caller of `depth` is `LiveData.get_depth_data`, which has no callers outside tests.
- `fetch_fee` → returns `self.fee` (base behaviour; no private endpoint).

---

## 6. Taker-volume handling (D5)

MEXC klines carry no taker-buy volume. Current pipeline behaviour that must change:

| Where | Today | Required |
|---|---|---|
| `StockInterface._resample_to_tf` (`base_stock.py:285`) | `'taker_base_vol': 'sum'` → NaN sums to **0** | sum with `min_count=1` → NaN stays NaN |
| `IndicatorField` | no notion | class attr `requires_taker_volume: bool = False`; `VolBuyMAField` sets `True` |
| Indicator config load (`config_loader.load_indicators_config`) | loads all | new `filter_for_taker_volume(configs, has_taker_volume) -> (kept, dropped)`: when `False`, drops every indicator whose field class `requires_taker_volume`, **and transitively** every indicator whose `depends_on` hits a dropped one (today: `vol_buy_ma_20`, `vol_sell_ma_20`). Logs one WARNING listing dropped names. |
| Live (`trader.py` / `Indicators` init) | — | applies the filter with `stock_holder.item.has_taker_volume`. Startup **raises** if any dropped name is in `shared_indicators_config.yaml` (executor expects it) or in the active NN spec's feature list. |
| Training (`DataPreparer`) | fills `taker_base_vol=0.0` if column absent (`data_preparer.py:643`) | reads `has_taker_volume` from the graber sidecar (§7) and applies the same filter; the `0.0` placeholder stays only for legacy files without a sidecar. |

`data.py:217` (`groupby().cumsum()`) and `data.py:298` need no change: NaN propagates as NaN.

Binance and mock stocks keep `has_taker_volume = True`, so their behaviour is byte-identical.

---

## 7. Venue sidecar and archive (D7)

`Graber` writes `graber_data.meta.json` next to `graber_data.pkl` (atomic, same tmp+rename as `save_atomic`):

```json
{"exchange": "mexc", "market": "futures", "symbol": "LINK_USDT",
 "has_taker_volume": false, "schema": 1}
```

- New `StockInterface` attributes used to build it: `exchange` (`"binance"` default), `market` (`"margin"` default), `has_taker_volume` (`True` default). `Stock_Binance*` and mocks inherit the defaults.
- `ensure_data`: if the pkl exists and the sidecar exists and any of `exchange/market/symbol` differs from the current stock → `GraberSourceMismatch` (subclass of `ValueError`), nothing fetched or written.
- Pkl exists, sidecar missing (legacy file): Binance stock → write sidecar as Binance and continue; MEXC stock → `GraberSourceMismatch` (a legacy file is Binance data by construction).
- New configs `configs/mexc_margin_dataset.env` and `configs/mexc_futures_dataset.env`: `STOCK_TYPE`, `PAIR=link_usdt`, distinct `DATA_SET_NAME` (`mexc_margin`, `mexc_futures`), `DATA_START` within the last 30 days, `EXCHANGE_FEE` (margin 0.001 spot taker placeholder, futures 0.0002 — operator to confirm).

**Archive recipe (documentation only, no new code):** run `LiveDataCollector` with `STOCK_TYPE=mexc_*` continuously against the MEXC dataset folder; it appends closed 1m rows to the same `graber_data.pkl`, so history beyond 30 days accumulates forward. The collector must go through `Graber`'s sidecar check on start (it writes to the same file) — `LiveDataCollector.__init__` reads the sidecar and applies the same mismatch rule.

---

## 8. Other touch points

### 8.1 `StockInterface` (`stocks/base_stock.py`)

- Add class attrs `exchange = "binance"`, `market = "margin"`, `has_taker_volume = True`.
- `_resample_to_tf`: `taker_base_vol` aggregated with `sum(min_count=1)`.

### 8.2 Trainer (`training/trainer.py:126`)

`symbol = pair.replace("_", "").upper()` → `symbol = stock_holder.item.get_pair_name()` after `do_stock_init`. Binance output unchanged (`LINKUSDT`); futures gets `LINK_USDT`.

### 8.3 `stocks_holder.do_stock_init`

```python
elif stock_name == "mexc_margin":
    from stocks.mexc_candles_stock import Stock_MexcCandles
    stock_holder.item = Stock_MexcCandles("margin")
elif stock_name == "mexc_futures":
    from stocks.mexc_candles_stock import Stock_MexcCandles
    stock_holder.item = Stock_MexcCandles("futures")
```

No other `STOCK_TYPE` gains MEXC behaviour; `binance` remains the only stock in `main/` with an order path.

---

## 9. Error model

| Error | Raised when | Caller effect |
|---|---|---|
| `MexcApiError(kind="client")` | 4xx / error body / `success=false` | propagates; grab stage / trader startup fails |
| `MexcApiError(kind="transient")` | retries exhausted | grab stage fails; live tick: exception propagates out of `build_candles()` → `Robot.run_instantly` logs `do() raised an exception; continuing loop` (`robots/robot.py:176`) and the tick is skipped — same as a Binance exception today, no new handling |
| `MexcHistoryUnavailable` | `start_ms` older than 1m retention | grab stage fails before any request |
| `MexcDataGap` | gap > `MEXC_MAX_GAP_MIN` or empty in-retention range | grab stage fails; nothing written |
| `GraberSourceMismatch` | venue sidecar mismatch / MEXC on legacy file | grab / collector fails; nothing written |

All are defined in `stocks/mexc/errors.py` except `GraberSourceMismatch` (`training/graber.py`).

---

## 10. Testing

**Unit (`tests/unit/stock_abstraction/mexc/`, `unittest.mock` patching `requests.Session.get` — repo convention, no vcr):**

- Fixtures `tests/fixtures/mexc/{spot_klines_1m.json, futures_kline_min1.json, futures_contract_detail.json, spot_error_invalid_interval.json}` — payloads captured by the 2026-09-26 probe (§3.1), trimmed.
- Spot/futures sources: interval maps; paging windows (500 / 2000 rows; futures seconds + inclusive end); spot always sends `endTime`; `real*` selection and fallback; `vol × contractSize`; retry on 429/5xx with backoff (patched sleep), no retry on 4xx; token bucket never exceeds budget over a burst.
- `normalize`: unclosed cut; gap fill values; gap > max raises; head gap raises; range frame columns/dtypes identical to `Stock_Binance.get_candles_range` output (compare against `_parse_klines` result schema); `close_time = open + 59_999`.
- Stock: symbol mismatch raises; retention guard raises with oldest time in message; history dict shape (≤120 rows, keys = requested TFs, `taker_base_vol` NaN on resampled TFs); every refused method returns `STATUS_FAIL` and never touches the session; `depth/info` raise; no env key read (patch `os.environ` with fake `MEXC_API_KEY` and assert unused).
- `_resample_to_tf`: NaN taker stays NaN; Binance numeric taker unchanged.
- Indicator filter: drops `vol_buy_ma_20` + dependent `vol_sell_ma_20`; no-op when `has_taker_volume=True`; raises when a dropped name is in shared indicators / NN features.
- Graber sidecar: write on new file; mismatch raises; legacy + Binance writes sidecar; legacy + MEXC raises.
- `do_stock_init("mexc_margin"|"mexc_futures")` returns the right class/market.

**Live smoke (`@pytest.mark.mexc_live`, new marker in `pytest.ini`, skipped by default, run in Docker):**

- For both markets: `get_candles_range` over the last 3 h → 1m grid complete, 0 < price, `v ≥ 0`, `taker_base_vol` all NaN; retention probe `now-31d` raises `MexcHistoryUnavailable`.
- `get_candles_history([1,5,15,60,240,1440], "link")` → all six TFs, ≤ 120 rows each.

**End-to-end (Docker, manual gate):** `mexc_futures_dataset.env` grab + prepare over 7 days produces `df_with_indicators` without `vol_buy_ma_20`/`vol_sell_ma_20` columns; `trader.py` with `STOCK_TYPE=mexc_futures` runs ≥ 5 min, publishes shared indicators to the executor MQ, and logs no refused-call warnings.

---

## 11. Alternatives considered

- **ccxt** — adds a heavy dependency, hides the contract-size and `real*` choices, does not help retention. Rejected.
- **Subclass `Stock_Binance`** — coupled to python-binance and margin trading. Rejected.
- **Binance splice for old history / coarse-interval fallback** — mixed-venue or degraded series in one file. Rejected (D4).
- **Per-TF native backfill** (5/15m ≈ 1 y, 60/240/1440 since listing) — needs a multi-resolution raw format and a new `DataPreparer` path; out of scope. Revisit as its own spec if MEXC-only long training becomes a goal.

---

## 12. Spec/doc updates on landing

When implemented, update in the same change (per external-repo rule):

- `critical-path/stock-abstraction-module/stock-abstraction-module.md` — add MEXC candles stock to components and candle-fetch flow.
- `critical-path/stock-abstraction-module/base-stock-interface-class.md` — new attrs, resample `min_count`.
- `critical-path/stock-abstraction-module/stock-item-class.md` — new `do_stock_init` names.
- New `critical-path/stock-abstraction-module/mexc-candles-stock-class.md` — class spec derived from §5.
- `supporting-systems/training-module/graber-class.md`, `livedatacollector-class.md`, `datapreparer-class.md` — sidecar, mismatch rule, taker filter.
- `critical-path/data-module/indicators-class.md` and `layers/02-data-layer.md` — `IndicatorField.requires_taker_volume` and the config filter.
