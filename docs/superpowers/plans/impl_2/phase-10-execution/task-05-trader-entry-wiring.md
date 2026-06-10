# Task 05: trader.py Entry Wiring

**Phase:** 10 — Execution
**Depends on:** Task 02 (Robot polling loop), Phase 07 (StrategyManager), Phase 03 Task 05 (LiveData), Phase 01 (stock abstraction)
**Produces:** root `trader.py` — replaces the phase-00 stub; Docker execution path E

---

## Goal

Wire the root `trader.py` stub to the real live-trading stack: stock init → LiveData → StrategyManager → Robot → `run_instantly()`.

## Context

The phase-00 stub (`print("[stub] trader")`) was never replaced — verification 01 found no plan task specified this wiring; this task closes that gap. The compose `live` service runs `python3 trader.py` with `configs/live.env` and Binance API keys.

**Construction order matters:** `do_stock_init()` must run before anything touches `stock_holder.item` (fee is set there from `EXCHANGE_FEE`); `LiveData()` calls `stock_holder.item.get_candles_history()` in its constructor.

**Paper mode:** the plan README's `IS_TRAIDER_TEST=1` flag does not exist in the implementation. Paper mode is `STOCK_TYPE=mock_binance` (mock order execution via `Stock_MockBinance`). The default MUST be paper — going live requires explicitly setting `STOCK_TYPE=binance` in the env file.

**Known drift (do not silently fix here):** design decision says `StrategyManager.__init__(fee, robot_actions_test)`; the implementation takes only `fee`. Flagged for plan-owner resolution.

## Files

- Modify: `trader.py` (root — currently 1-line stub)
- Test: `tests/test_trader_entry.py`

## Steps

- [ ] **Step 1: Write the failing test** — `tests/test_trader_entry.py`: mock `robots.robot.Robot`, `data.LiveData`, `stocks_holder`, assert construction order and arguments:

```python
def test_trader_main_wires_robot(monkeypatch, tmp_path):
    # env per configs/live.env conventions
    for k, v in {"PAIR": "link_usdt", "ROOT_FOLDER": "short",
                 "DATA_ROOT": "live", "DATA_SET_NAME": "live",
                 "EXCHANGE_FEE": "0.001"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("STOCK_TYPE", raising=False)
    # mock stock_holder / LiveData / StrategyManager / Robot via sys.modules
    # (same pattern as tests/test_phase09_task03_trainer.py)
    ...
    import trader
    trader.main()

    mock_do_stock_init.assert_called_once_with("mock_binance")  # paper by default
    mock_robot_cls.assert_called_once()
    args = mock_robot_cls.call_args
    assert args.args[3] == mock_stock.fee          # fee from stock.fee
    mock_robot_instance.run_instantly.assert_called_once()
```

- [ ] **Step 2: Run test, verify it fails** (stub has no `main`).

- [ ] **Step 3: Implement `trader.py`:**

```python
"""trader.py — live trading entry point (Docker path E).

Paper mode is the DEFAULT (STOCK_TYPE=mock_binance). Real trading
requires STOCK_TYPE=binance set explicitly in the env file.
"""

import os


def main() -> None:
    from stocks_holder import do_stock_init, stock_holder

    stock_type = os.environ.get("STOCK_TYPE", "mock_binance")
    do_stock_init(stock_type)
    stock = stock_holder.item

    from data import LiveData
    from helpers import shared_folder
    from robots.robot import Robot
    from strategies.strategy_manager import StrategyManager

    live_data = LiveData()
    strategy_manager = StrategyManager(stock.fee)

    os.makedirs(shared_folder(), exist_ok=True)
    robot = Robot(
        strategy_manager,
        live_data,
        stock,
        stock.fee,
        persist_path=shared_folder() + "live_tracker.json",
    )
    robot.run_instantly()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test, verify PASS; run full suite.**

- [ ] **Step 5: Docker verification (paper mode only):**

```bash
docker compose run --rm live   # STOCK_TYPE unset → mock_binance
```

Expected: Robot polling loop starts, ticks logged, no stub line. Ctrl-C exits cleanly (`run_instantly` handles KeyboardInterrupt). DO NOT verify with `STOCK_TYPE=binance` and real keys.

- [ ] **Step 6: Commit** — `feat: wire trader.py to Robot live loop, paper mode by default`
