# Stock Module: fetch_fee() and Boundary Corrections

**Date:** 2026-05-12  
**Scope:** Stock Abstraction Module  
**Files affected:** `stocks/base_stock.py`, `stocks/binance_stock.py`, all four stock spec docs

---

## Problem Statement

Two issues identified in the current stock module spec and implementation:

1. **Hardcoded fee** — `Stock_Binance.fee` is set to `0.001` at construction time and never updated from the exchange. If the account's actual taker fee differs (VIP tier, BNB discount, etc.), PnL calculations in Position will be wrong for live trading.

2. **Incorrect Trainer/TrainRobot boundary** — The existing spec states "Trainer and TrainRobot use `stock.item` to fetch historical candles during backtesting." This is false. Trainer and TrainRobot load pre-grabbed candle data from disk (produced by the Grabber). They do read `stock.item.fee` via the Position class for PnL calculations, using a mock stock implementation.

---

## Design

### 1. fetch_fee() — StockInterface (base stub)

**File:** `stocks/base_stock.py`

Add `fetch_fee()` as a non-abstract method that returns `self.fee` unchanged. This preserves correct behavior for all existing mock implementations without requiring any changes to them.

```python
def fetch_fee(self) -> float:
    return self.fee
```

**Contract:**
- Returns the current taker fee as a decimal (e.g. `0.001` = 0.1%)
- No side effects in base class
- Subclasses may override to fetch from exchange and update `self.fee`

---

### 2. fetch_fee() — Stock_Binance (concrete implementation)

**File:** `stocks/binance_stock.py`

Override `fetch_fee()` to call Binance's trade fee endpoint, extract the taker commission for the current symbol, and store it in `self.fee`.

```python
def fetch_fee(self) -> float:
    try:
        fees = self.instance.get_trade_fee(symbol=self.get_pair_name())
        # Response: [{"symbol": "LINKUSDT", "makerCommission": "0.001", "takerCommission": "0.001"}]
        self.fee = float(fees[0]["takerCommission"])
        self.weight += 1
        log_stock("fetch_fee", self.weight)
    except (BinanceRequestException, BinanceAPIException) as e:
        log_error(f"fetch_fee failed, keeping default fee={self.fee}: {e}")
    return self.fee
```

**Behavior:**
- Calls `GET /sapi/v1/asset/tradeFee?symbol={PAIR}` via the python-binance SDK
- Extracts `takerCommission` (taker fee used for all limit order fills on margin)
- Stores result in `self.fee` (the same attribute Position reads for PnL)
- Weight cost: **+1** per call
- On `BinanceRequestException` or `BinanceAPIException`: logs the error, leaves `self.fee` at its current value (default `0.001`), continues normally
- Returns the (possibly unchanged) `self.fee`

**Why taker and not maker:**  
All margin limit orders in this system use GTC time-in-force and are treated as taker fills for fee calculation consistency. Using the taker rate is the conservative choice.

---

### 3. Caller — Robot startup sequence

Robot calls `stock.item.fetch_fee()` once, explicitly, after `do_stock_init("binance")` and before entering the trading loop.

```python
do_stock_init("binance")
stock.item.coin = pair_coin
stock.item.coin_base = pair_base
stock.item.fetch_fee()   # ← new: update fee from exchange
```

**Why explicit call (not in constructor):**  
- Keeps `__init__` free of network calls — faster, more predictable initialization
- Coin/coin_base must be set before the call (needed for `get_pair_name()`)
- Caller controls when the API hit happens (useful for testing startup sequences)

---

### 4. Mock behavior

`Stock_Mock` and `Stock_MockBinance` inherit the base no-op. They keep their hardcoded `fee` value. No changes required.

Trainer and TrainRobot use `do_stock_init("mock")`, so they never hit the Binance endpoint. Position reads `stock.item.fee` from the mock, which remains `0.001`.

---

## Spec Corrections (documentation only)

### Trainer/TrainRobot boundary — all four spec files

**Incorrect (current):**
> Trainer and TrainRobot — use `stock.item` to fetch historical candles during backtesting

**Correct:**
> Trainer and TrainRobot — read `stock.item.fee` for PnL calculations via Position class; use mock stock implementation (`do_stock_init("mock")`); do **not** call `get_candles_history()` — candle data is loaded from pre-grabbed files produced by the Grabber

### stock-abstraction-module.md — Upstream Dependencies table

Add `fetch_fee()` to the Key Interfaces Exposed table:

| Method | Input | Output | Purpose |
|--------|-------|--------|---------|
| `fetch_fee()` | — | float | Fetch taker fee from exchange, store in `self.fee`; no-op fallback on error |

### base-stock-interface-class.md

Add `fetch_fee()` to Key Methods section with the base stub spec above.

### binance-stock-class.md

Add `fetch_fee()` as a numbered method in section 4 with the Binance implementation spec above. Add to the Weight Costs table: `fetch_fee()` → weight +1.

### stock-item-class.md

- Update Trainer & TrainRobot integration section to reflect corrected boundary
- Add `fetch_fee()` under Account Methods as a delegation method

---

## What does NOT change

- `self.fee` attribute name and type — unchanged; all existing callers (Position, Robot) read it the same way
- Mock implementations — no changes required
- `StockInterface` constructor — unchanged
- `Stock_Binance` constructor — unchanged (fetch_fee is called by Robot, not at init)
- All other Stock_Binance methods — unchanged

---

## Summary

| Change | Type | File |
|--------|------|------|
| Add `fetch_fee()` no-op stub | Code + spec | `stocks/base_stock.py`, `base-stock-interface-class.md` |
| Add `fetch_fee()` Binance impl | Code + spec | `stocks/binance_stock.py`, `binance-stock-class.md` |
| Add `fetch_fee()` to interface table | Spec only | `stock-abstraction-module.md` |
| Add `fetch_fee()` delegation method | Spec only | `stock-item-class.md` |
| Call `fetch_fee()` at Robot startup | Code | `robot.py` |
| Fix Trainer/TrainRobot boundary claim | Spec only | All four stock spec files |
