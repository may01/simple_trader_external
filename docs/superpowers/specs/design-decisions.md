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

**#29 — `cur_time`/`timer` type: `int` (Unix seconds) or `float`?**
Decision: **`float`** everywhere — `cur_time: float`, `timer: float`. Canonical.
Why: Matches the convention already established in phase-06 task-02 (`open_time: float`), phase-06 task-04/phase-08/phase-10 (`close_by_time(cur_time: float)`), and phase-05's own typed interface + verification script (passes `1000.0`). phase-03 task-08 (`Levels.get_active_levels`, `get_level_value`, `is_price_near_level`, etc. — all typed `cur_time: int`) is the stale outlier; those signatures should be updated to `float` to match.

**#30 — `SignalChain.check()`: log fired signal pre-increment, or next-awaited signal post-increment?**
Decision: Log **before** incrementing `cur_pos` — `action.add_multiply_action(self.signals[self.cur_pos].get_marker_pos(data_point), "SF: C %s S %d" % (self.name, self.cur_pos))`, *then* `self.cur_pos += 1; self.timer = cur_time`. The logged index/marker describes the signal that just fired, not the one now being awaited. `get_marker_pos(data_point)` is part of `BaseSignal`'s surface that `SignalChain` calls (phase-05 task-01 omitted it from its interface list — must be added back).
Why: Matches the underlying SignalChain spec's actual code exactly. phase-05 task-01's prose ("increment, then log") read as post-increment, which would log the wrong signal's marker and a confusing "now waiting on signal N" index instead of "signal N just fired".

**#31 — `completed()`: log "CPLTD: {name}" on completion, or pure stateless bool test?**
Decision: **Log it.** When `notify=True` and `cur_pos == len(signals)`: `action.add_multiply_action(self.signals[-1].get_marker_pos(data_point), "CPLTD: %s" % self.name)`, then return `True`. `notify=False` → no log, just the bool.
Why: Matches underlying spec. Distinct human-visible "whole pattern completed" marker, separate from the per-signal "SF: C..." progress logs added in #30 — needed to visually distinguish "signal N fired" from "entire chain fired" on charts/logs. phase-05 task-01's bare-bool wording was an under-specification, not a deliberate simplification.

**#32 — phase-05 verification scripts crash: `notify=True` default + `action=None`?**
Decision: Pass `notify=False` explicitly when constructing test chains in verification scripts (`SignalChain(..., notify=False)`). `action=None` stays valid input for logging-free test runs.
Why: With #30/#31 confirming `notify=True` triggers `action.add_multiply_action(...)`, the original task-01/task-02 verification scripts construct chains with `notify` defaulting `True` and pass `action=None` → `AttributeError: 'NoneType' object has no attribute 'add_multiply_action'`, crashing on the very first signal fire. `notify=False` is the documented path for "high-frequency test chains" — applying it here is consistent and keeps the scripts runnable as-is. Fixed directly in task-01-signal-chain.md and task-02-signal-manager.md.

**#28 — `levels` param passed into signals: `Levels` instance, raw level dicts, or precomputed shape?**
Decision: A new type alias `SignalLevels = Dict[int, List[float]]` — `{level_type: [interpolated_price, ...]}`. Plain dict, no class, no helper methods. Produced by a new method `Levels.to_signal_levels(data_point) -> SignalLevels`, which internally calls `get_active_levels()` + `get_level_value()` to interpolate every active level of every type once per tick. `Strategy.check()` calls `to_signal_levels()` once per tick and threads the result through `SignalManager.check()` → `SignalChain.check()` → `signal.check()`.
Why: phase-04/phase-05 plan drafts disagreed on the shape — task-01-base-signal.md and the SignalChain verification script type it as plain `dict` (and pass `{}`), while task-03-crossover-level-signals.md line 61 calls `levels.get_level_value(...)`, which only exists on the `Levels` class. Precomputing once per tick keeps signals dumb (plain float comparisons, no interpolation, no `cur_time` needed inside `check()`) and avoids passing the heavyweight `Levels` loader (file I/O, full level list) down into every signal.

`to_signal_levels()` **replaces** `get_levels_dict()` (phase-03 task-08) and `get_level_values()` (phase-04 task-03 — itself a stale alias of the same method). Both names are retired; `to_signal_levels()` is the single canonical conversion from loaded levels to the dict signals consume.

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
