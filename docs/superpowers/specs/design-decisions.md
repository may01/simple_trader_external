# Design Decisions

Resolved design Q&A for PyBTCTR2. Each entry: **question** → **decision** → **rationale**.

---

## Data Layer

**#1 — Live-path column naming: prefixed or unprefixed?**
Decision: **Prefixed** (`{tf}_{col}`) in `ohlc[tf]`, matching the wide DataFrame format. `LiveDataPoint.get("rsi_14", tf=5)` looks up `ohlc[5]["5_rsi_14"]`.
Why: Eliminates dual-naming branches in Indicators; live and simulation paths share the same column convention.

**#2 — Wide DataFrame: forward-fill indicator columns between candle boundaries?**
Decision: **No forward-fill.** Indicators are written only at `{tf}_is_closed=True` rows; non-closed rows remain NaN. Consumers filter using `{tf}_is_closed`.
Why: v2.0 model; avoids stale values mid-candle; forces callers to be explicit about which rows are valid.

**#13 — Active timeframes: include 3-min and daily?**
Decision: **Remove 3-min, add 1440.** Canonical list: `[1, 5, 15, 60, 240, 1440]` from `candles_config.yaml`.
Why: 3-min was unused; daily (1440) is required for macro trend signals.

**#18 — `root_folder()`: accept `pair` argument or read from env?**
Decision: **No `pair` argument.** All path functions read `os.environ['PAIR']` internally.
Why: Eliminates dead parameter; one consistent calling convention across all path helpers.

---

## Position Module

**#3 — Fill reporting API: `add_buy`/`add_sell` or phase-semantic names?**
Decision: **`record_entry_fill(coin_amount, price)` / `record_exit_fill(coin_amount, price)`** everywhere.
Why: Direction-neutral; prevents semantic confusion when Long's `add_buy` ≠ Short's `add_buy`.

**#7 — Execution-bridge attributes: in Position facade or separate class?**
Decision: **Extract to `LiveOrderTracker`** in the Execution Layer. Position contains only BL state; order IDs, margin loans, and JSON persistence move to `LiveOrderTracker` owned by Robot.
Why: Enforces BL/Execution boundary; TrainRobot never needs these attributes, giving structural symmetry.

**#8 — `is_real_stock`: keep in Position or use env var?**
Decision: **Remove from Position entirely.** Paper-trade mode controlled by `IS_TRAIDER_TEST` env var read in Robot.
Why: Position should not know whether execution is real; that is an Execution Layer concern.

**#19 — `update_coin_size()`: in BasePosition or delegated to Robot?**
Decision: **Remove from BasePosition.** Robot queries funds from exchange and passes the result into `extend()`. Position never calls `stock.item.funds()` directly.
Why: Position calling stock violates layer boundaries; Robot owns all exchange interactions.

**#25 — Stop-loss checks: inline in TrainRobot or delegated to Position?**
Decision: **Delegate to `Position.is_stop_loss_triggered(cur_price)`.** No inline stop-loss logic in TrainRobot.
Why: Eliminates live/simulation divergence; stop-loss is a BL rule enforced by Position.

---

## Strategy Module

**#5 / #6 — StrategyManager `data` attribute: stored or passed per-tick?**
Decision: **Not stored.** Constructor: `__init__(fee, robot_actions_test)`. `data_point: DataPoint` passed per-tick to `check(data_point, ...)`.
Why: Eliminates stale-reference bugs; stateless between ticks is safer and explicit.

**#15 — Trend signals: `trend_signals`/`trend_modifiers` in Strategy attributes?**
Decision: **Remove.** Use `BoolValue_Signal("trend_up/down", tf)` inside signal chains instead.
Why: Trend filtering is a signal concern, not a Strategy attribute; keeps Strategy attributes minimal.

**#22 — `trend_tf`/`price_check_tf` in StrategyManager?**
Decision: **Remove entirely.** These timeframe constants were unused and confused the interface.
Why: No concrete strategy needed them; removing reduces the constructor surface.

---

## Robot Module

**#4 — Fee: hardcoded class variable or injected from env?**
Decision: **Read from `stock.item.fee`** at Robot init; `stock.item.fee` is set from `EXCHANGE_FEE` env var in `Stock_Binance.__init__`. No class-level fee constant anywhere.
Why: Single source of truth; changing the fee rate requires only an env var update, no code change.

**#26 — Indicator calculation in polling loop: separate `calc()` call or via `build_candles()`?**
Decision: **`data_item.build_candles(time_point)`** handles both data fetch and indicator computation. Remove separate `Indicators()` instantiation and `calc()` call from the polling loop.
Why: Encapsulates the data→indicators pipeline in `LiveData`; Robot doesn't need to know about indicator internals.

---

## Backtesting Module

**#9 — Simulation data: `DataIterator` (per-step pkl I/O) or `SimulationData` (load once)?**
Decision: **`SimulationData`**: load `df_with_indicators.pkl` once at init; yield `WideDataPoint` at O(1) cost per step.
Why: Eliminates per-step disk I/O; consistent with v2.0 wide DataFrame model.

**#14 — TrainRobot API: `set_data(cur_data)` + `do()` or `step(data_point, action)`?**
Decision: **`step(data_point: WideDataPoint, action)`**: single call with data and action passed in; replaces the old two-call pattern.
Why: Eliminates the need to store a stale `self.data` reference; matches the per-tick parameter-passing pattern used everywhere else.

---

## Stock Abstraction Module

**#24 — `do_stock_init()` initialization contract: documented?**
Decision: **Document explicitly**: `do_stock_init()` must be called once at process startup before any `stock.item` access. Components that need `fee` receive it as a constructor parameter from the caller that ran `do_stock_init()` — never import `stock.item.fee` at module load time.
Why: Prevents silent no-op from accessing uninitialized StockInterface.

---

## Infrastructure

**#10 — Path C (generate_data_points) and Path D (strategy train): keep or remove?**
Decision: **Remove from active paths.** With v2.0 `SimulationData`, per-timestamp pkl generation is obsolete. The execution path is now: A (collect) → B (generate wide df) → C (simulate).
Why: Eliminates an intermediate step that added disk I/O without benefit.

**#11 — `data.full_data` singleton: keep or remove?**
Decision: **Remove `data.full_data` from singleton constraints.** Only `data.item` (`LiveData`) is a module-level singleton. `FullData` and `SimulationData` are instantiated per run.
Why: `FullData` and `SimulationData` are not live-trading concerns; no reason to keep them as singletons.

**#12 — LI_* level constants: `helpers.py` or `constants.py`?**
Decision: **`constants.py`**. All shared domain constants (`LI_*`, `LEVEL_TYPE_*`, `STRATEGY_ACTION_*`, etc.) live in `constants.py`.
Why: `helpers.py` is for path utilities only; mixing in domain constants violates single responsibility.

**#23 — `validate_dataset.env`: what time range?**
Decision: **Different time range from `train_dataset.env`** to provide out-of-sample validation. Exact range and expected revenue range are documented in testing strategy.
Why: Using the same range as training would not validate generalization.

---

## Levels

**#16 — Level type constants: remove SHORT_1/SHORT_2, rename AUTO_TARGET_*?**
Decision: **Remove** `LEVEL_TYPE_SHORT_1_RESISTANCE=10` and `LEVEL_TYPE_SHORT_2_RESISTANCE=11` (unused). **Rename** `AUTO_TARGET_SUPPORT` → `AUTO_SUPPORT` and `AUTO_TARGET_RESISTANCE` → `AUTO_RESISTANCE`.
Why: Shorter, cleaner names; removing unused types reduces confusion.

---

## Cross-cutting

**#17 — Signal data access: old `data.get_cur_price(col, shift, tf)` or new DataPoint API?**
Decision: **New API**: `data_point.get(col, tf, shift + self.shift)`. Signals never access `data.ohlc[tf]` directly.
Why: DataPoint is the isolation interface; all consumers must go through it.

**#20 — Related-spec links in design docs: relative or root-relative paths?**
Decision: **Root-relative** (e.g., `/layers/02-data-layer.md`).
Why: Portable across renderers; doesn't depend on the file's location in the directory tree.

**#21 — Spec file hierarchy: update §4.1 to match actual created files?**
Decision: **Yes** — `2026-05-04-pybtctr2-specification-design.md §4.1` updated to reflect the actual file tree including all created specs.
Why: The planned file tree diverged significantly from reality during Phase 2/3.

**#27 — Design decisions: scattered in `how_to_use.md` or dedicated file?**
Decision: **This file** (`design-decisions.md`). `how_to_use.md` kept as-is (usage guide, not decisions).
Why: Separates "how to use the system" from "why we designed it this way"; each document has a clear audience.
