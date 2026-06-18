# Task 01: Live Strategy Wiring + Small-Amount Cap

**Phase:** 15 — Live Operation Verification
**Depends on:** Phase 14 merged (`EmaStrategyFactory` in `strategies/test_factory.py`)
**Produces:** `trader.py` that registers the EMA test strategies and sizes orders to a capped USDT notional; corrected plan README references.

---

## Goal

Make the live entry point actually trade with the Phase-14 test EMA strategies, at a small bounded size:

1. `trader.py` reads `STRATEGY_SET`; when `STRATEGY_SET=ema`, it builds the live `StrategyManager` via `EmaStrategyFactory(fee)` instead of an empty `StrategyManager(fee)`.
2. `trader.py` reads `LIVE_POSITION_USDT` and uses it as the live `Position.full_position` (the per-trade notional). Default small (40).
3. Fix the stale references in the plan index (`pybtctr.py` → `trader.py`, `docker-compose-live.yml` → `docker-compose.yml`).

---

## Context

Today `trader.py` does:

```python
strategy_manager = StrategyManager(stock.fee)   # registers NOTHING → robot is inert
robot = Robot(strategy_manager, live_data, stock, stock.fee, persist_path=...)
```

`StrategyManager.__init__` starts with `self.strategies = []`, so with no `register()` calls the robot's `do()` always resolves to NOTHING. Order sizing in `Robot._open_position` is `amount = self.position.full_position / price`, and `Position.full_position` defaults to `10000.0`. For real-money verification this must be overridable down to 30–50 USDT.

`EmaStrategyFactory(fee)` (Phase 14, `strategies/test_factory.py`) is a zero-arg callable returning a `StrategyManager` with `StrategyTest1Long` + `StrategyTest1Short` registered (EMA-7/EMA-14 cross, tf=5).

---

## Files

- Modify: `trader.py`
- Modify: `docs/superpowers/plans/impl_2/README.md` (drift fix — external docs repo)

---

## Interface / behaviour

`trader.py main()`:

- Read `strategy_set = os.environ.get("STRATEGY_SET", "")`.
  - `"ema"` → `from strategies.test_factory import EmaStrategyFactory`; `strategy_manager = EmaStrategyFactory(stock.fee)()`.
  - any other / unset → keep current behaviour (`StrategyManager(stock.fee)`, inert) so existing default runs are unchanged.
- Read `live_usdt = float(os.environ.get("LIVE_POSITION_USDT", "40"))`.
  - Construct the `Robot`, then set the position notional from this value via the position the Robot owns (e.g. `robot.position.full_position = live_usdt`), OR pass it through `Robot` construction if a constructor parameter is cleaner. Pick the path that sets `full_position` for the live position the Robot actually trades with — verify by reading `Robot.__init__` and `Position`.
  - Guard: if `live_usdt > 50`, log a warning and clamp to 50. The cap is a safety rail, not a suggestion.

Leave all other `trader.py` behaviour (stock init, `LiveData`, persist path) unchanged.

---

## Key constraints

- `STRATEGY_SET` unset must not change today's default behaviour (backwards compatible).
- `LIVE_POSITION_USDT` is the **only** knob that sets live notional. Do not hardcode a size anywhere in `trader.py`.
- Clamp to ≤ 50 in code. This is the money-safety guard the phase depends on.
- Do not import Phase-14 strategy classes directly in `trader.py` — go through `EmaStrategyFactory` so the registration set stays defined in one place.

---

## Tests

Add `tests/test_trader_live_wiring.py` (mock stock, no creds, runs in Docker):

```
def test_strategy_set_ema_registers_two_ema_strategies(monkeypatch):
    # STOCK_TYPE=mock_binance, STRATEGY_SET=ema
    # Build the strategy_manager the way main() does (factory path)
    # Assert len(strategy_manager.strategies) == 2

def test_strategy_set_unset_is_inert(monkeypatch):
    # STRATEGY_SET unset → strategy_manager.strategies == []

def test_live_position_usdt_sets_full_position(monkeypatch):
    # LIVE_POSITION_USDT=35 → the robot's position.full_position == 35.0

def test_live_position_usdt_clamped_to_50(monkeypatch):
    # LIVE_POSITION_USDT=1000 → clamped to 50.0, warning logged
```

Refactor `trader.main()` as needed so the strategy-manager build and the size read are unit-testable without launching `robot.run_instantly()` (e.g. a small `build_strategy_manager(stock, strategy_set)` helper and a `resolve_live_usdt()` helper). Keep `main()` thin.

```bash
docker run --rm -v "$PWD":/code -w /code simple_trader \
  python3 -m pytest tests/test_trader_live_wiring.py -q
```

---

## Verification

```bash
# Mock — confirms wiring without touching the exchange.
STRATEGY_SET=ema STOCK_TYPE=mock_binance LIVE_POSITION_USDT=40 \
  docker compose run --rm -e STRATEGY_SET -e STOCK_TYPE -e LIVE_POSITION_USDT \
  trader python3 -c "
import trader
sm = trader.build_strategy_manager(__import__('stocks_holder').stock_holder.item, 'ema') \
     if hasattr(trader,'build_strategy_manager') else None
print('strategies registered:', len(sm.strategies) if sm else 'n/a')
"
```

Verified: [ ] `STRATEGY_SET=ema` registers exactly 2 EMA strategies
Verified: [ ] `LIVE_POSITION_USDT` sets `full_position` and clamps at 50
Verified: [ ] plan `README.md` references `trader.py` / `docker-compose.yml` (no `pybtctr.py` / `docker-compose-live.yml`)

---

## Commit

`feat: wire EMA test strategies and LIVE_POSITION_USDT cap into live trader`
