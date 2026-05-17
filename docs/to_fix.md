# Specification Inconsistencies — to_fix.md

Each entry: **Issue** | **Solution Options** | **Human Decision**

---

## 1. Indicator column naming: prefixed vs. unprefixed on live path

**Issue:** `Indicators.compute()` in `indicators-class.md §3.1` writes columns as `data_point.get_df(tf)[f"{tf}_{field.name}"]` (e.g., `"5_rsi_14"` into `ohlc[5]`). But `LiveDataPoint.get()` in `data-class.md §7.1` looks up `self._ohlc[tf][col]` where `col="rsi_14"` (unprefixed). The column written by Indicators is `"5_rsi_14"` but read as `"rsi_14"` — these never match, so live-path indicator reads would always KeyError. The `data-class.md §12` explicitly states live-path DataFrames use unprefixed names. The two halves of the spec directly contradict each other.

**Solution Options:**
- A) `Indicators.compute()` writes UNPREFIXED column names (`field.name`) into `ohlc[tf]` on the live path, and TF-prefixed names (`{tf}_{field.name}`) into the wide df on the simulation path. `Indicators` detects path via `isinstance(data_point, LiveDataPoint)` and applies appropriate naming.
- B) `LiveDataPoint.get(col, tf)` looks up `ohlc[tf][f"{tf}_{col}"]` — live path uses prefixed column names throughout, matching what `Indicators.compute()` writes. `data-class.md §12` is updated to say live path also uses prefixed names.
- C) The two paths use separate `compute()` calls: `Indicators.compute_live(ohlc_df, tf)` writes unprefixed; `Indicators.compute_wide(wide_df, ts, tf)` writes prefixed.

**Human Decision:** Use B

---

## 2. FFill vs. no-ffill in wide DataFrame generation

**Issue:** `data-module.md §8.2` (v2.0) says "No ffill: each row independently holds the indicator value for its own state." `data-class.md §6.4` also says no forward-fill. But `02-data-layer.md §9` (Wide data generation step) says: "Forward-fill all `{tf}_*` indicator columns to 1-min rows within each candle period." Additionally, `dataiterator-class.md §6` (Source Data description for `df_with_indicators.pkl`) says each indicator column is "ffill to all 1-min rows." These are direct contradictions within the same specification family.

**Solution Options:**
- A) Adopt the v2.0 model (no ffill): every 1-min row gets its own independently-computed indicator value (partial-candle mid-period, closed-candle at boundaries). Remove ffill from `02-data-layer.md §9` and `dataiterator-class.md §6`. Document partial-candle semantics clearly in all affected specs.
- B) Adopt the ffill model: indicators are computed only at `{tf}_is_closed=True` rows and forward-filled to all 1-min rows in the same candle period. Revert `data-module.md §8.2` and `data-class.md §6.4` to describe ffill. This simplifies computation but means mid-period rows have stale indicator values.

**Human Decision:** Use A

---

## 3. `add_buy`/`add_sell` vs. `record_entry_fill`/`record_exit_fill` — API mismatch across specs

**Issue:** `position-module.md` and `business-logic-layer.md §2` still use the old direction-named API: `position.add_buy()`, `position.add_sell()`. `base-position-class.md §4.2` uses the new phase-semantic API: `record_entry_fill(coin_amount, price)`, `record_exit_fill(coin_amount, price)`. `2026-05-10-position-cross-layer-alignment-design.md §4` explicitly mandates the rename. `backtesting-module.md §D` still uses old names. The two naming conventions coexist in the spec set creating confusion about which is authoritative.

**Solution Options:**
- A) Adopt the new phase-semantic API (`record_entry_fill`, `record_exit_fill`) everywhere. Update `position-module.md`, `business-logic-layer.md`, `backtesting-module.md`, and `robot-module.md` to use the new names.
- B) Keep old names (`add_buy`/`add_sell`) and update `base-position-class.md` and `2026-05-10-position-cross-layer-alignment-design.md` to match. Revert the rename decision.

**Human Decision:** use A

---

## 4. Fee: hardcoded in Robot vs. injected everywhere else

**Issue:** `robot-module.md §Key Components` says `Robot.fee` is a class variable `= 0.002` (hardcoded). `infrastructure-layer.md §6` says "Fee is a deployment variable, not a code constant" and `EXCHANGE_FEE` is the single source. `business-logic-layer.md §6` says "Fee is injected, never hardcoded." `base-position-class.md §2` says fee is "passed in by caller; never a default constant." `stock-abstraction-module.md` says `Stock_Binance.fee = 0.001` (also hardcoded, different value). These directly contradict each other and each other's values (0.002 vs 0.001).

**Solution Options:**
- A) Robot reads `EXCHANGE_FEE` from environment at startup and passes it to StrategyManager, Strategy, and Position. `Robot.fee` class variable removed. `Stock_Binance.fee` also replaced by env var read. Spec documents updated accordingly.
- B) `Stock_Binance.fee` is set from `EXCHANGE_FEE` env var at init (as the infrastructure spec says). Robot reads fee from `stock.item.fee` and passes it downstream. No class-level constant for fee anywhere.
- C) Allow a class-level default for fee in Stock_Binance only, overrideable by env var. Document that Robot and all BL classes must read fee from `stock.item.fee`.

**Human Decision:** use B

---

## 5. StrategyManager stores `self.data` vs. data passed per-tick

**Issue:** `strategy-module.md §3.4` says StrategyManager has `self.data (Data): Reference to current market data (set per-tick)`. `business-logic-layer.md §5` says "Constructor: `StrategyManager(fee, robot_actions_test)` — registers strategies; **no data stored at construction**; `data` passed in each tick." These directly contradict each other on whether StrategyManager holds a data reference.

**Solution Options:**
- A) Adopt the BL layer v2.0 approach: StrategyManager takes no `data` argument in constructor; `check(data, position_state, position_target, action_msg)` receives `data` (as `DataPoint`) per-tick and passes it to strategies. Remove `self.data` from StrategyManager spec entirely.
- B) Adopt the strategy-module approach: StrategyManager stores `self.data` reference, updated via `set_data()` or `self.data = data_item` each tick before calling check(). Update BL layer spec to match.

**Human Decision:** use A

---

## 6. StrategyManager constructor signature inconsistency

**Issue:** `strategy-module.md §3.4` shows constructor: `def __init__(self, data, fee, robot_actions_test)` — takes `data` as first arg. `business-logic-layer.md §5` shows: `StrategyManager(fee, robot_actions_test)` — no `data`. These are the same class but with incompatible constructors across two specs.

**Solution Options:**
- A) Constructor is `StrategyManager(fee, robot_actions_test)` — no data. Update `strategy-module.md §3.4` to match.
- B) Constructor is `StrategyManager(data, fee, robot_actions_test)` — takes data ref. Update `business-logic-layer.md §5` to match.

**Human Decision:** align with ## 5. StrategyManager stores `self.data` vs. data passed per-tick frmot his file

---

## 7. Position facade still has live-only attributes despite alignment design removing them

**Issue:** `position-module.md §Key Interfaces` still lists `set_action_id()`, `is_action_in_progress()`, `set_loan()`, `set_repay()`, `get_loan()`, `save_position()`, `load_position()`, `restore_position()` as Position facade methods. `2026-05-10-position-cross-layer-alignment-design.md §2` (Status: RESOLVED) says these are extracted to `LiveOrderTracker` in the execution layer. The position-module spec was never updated to reflect this resolved change.

**Solution Options:**
- A) Update `position-module.md` to remove live-only bridge attributes and methods from Position facade. Add `LiveOrderTracker` as a separate class owned by Robot. Note that Position only exposes BL-relevant methods.
- B) Revert the alignment design decision; keep live-only state in Position facade. Mark alignment design as cancelled.

**Human Decision:** use A

---

## 8. `is_real_stock` still referenced despite alignment design removing it

**Issue:** `position-module.md §Existing Approach` and `base-position-class.md §4.5` (`update_coin_size()`) and `extend()` methods still reference `is_real_stock`. `2026-05-10-position-cross-layer-alignment-design.md §2` says: "Remove `is_real_stock` from Position entirely. Paper-trade mode controlled in Robot via `IS_TRADER_TEST` env var." The alignment design doc says this is already resolved, but the position specs still reference it.

**Solution Options:**
- A) Update `position-module.md` and `base-position-class.md` to remove all references to `is_real_stock`. Document that paper-trade mode is controlled by Robot reading `IS_TRADER_TEST`.
- B) Keep `is_real_stock` in Position; revert the alignment design. Update alignment design to say the extraction was only for order IDs and loans, not the paper-trade flag.

**Human Decision:** use A

---

## 9. Backtesting module still uses old `DataIterator` class and v1 API

**Issue:** `backtesting-module.md §5` still describes `DataIterator` class as: "Iterates through time-ordered data points from disk" with `next()`, `has_next()` methods — this is the v1 API loading per-step `.pkl` files. The v2 architecture replaces `DataIterator` with `SimulationData` (which loads `df_with_indicators.pkl` once). `dataiterator-class.md` is actually the `SimulationData` class spec (class was renamed). `training-module.md §8` explicitly says `DataIterator` is replaced by `SimulationData`.

**Solution Options:**
- A) Rewrite `backtesting-module.md` to use v2 architecture: replace `DataIterator` with `SimulationData`, update `TrainRobot` API references to use `sim.get()` + `sim.next()` pattern. Remove all per-step `.pkl` loading references.
- B) Create a separate `backtesting-module-v2.md` aligned with v2.0 data model, and mark old doc as deprecated.

**Human Decision:** use A

---

## 10. Deprecated RUN_TYPEs (`generate_data_points`, `train`) still in infrastructure setup doc

**Issue:** `01-infrastructure-layer-setup.md` Paths C and D describe `RUN_TYPE=generate_data_points` and `RUN_TYPE=train` as valid execution paths. `training-module.md §2` v2.0 explicitly says "The legacy `generate_data_points`, `generate_data_points_prediction`, `generate_nn_points`, and `train` RUN_TYPEs are removed in v2.0." The infrastructure spec was not updated to reflect v2.0 training module changes.

**Solution Options:**
- A) Remove Paths C and D from `01-infrastructure-layer-setup.md`. Update path dependency diagram to remove these steps. Document that `generate_full_ohlc` now covers what `generate_data_points` used to do.
- B) Keep the infra setup doc as-is (it reflects the v1 system that may still exist in code). Mark Paths C and D as deprecated/v1 with a note pointing to training-module.md v2.0.

**Human Decision:** use A

---

## 11. `data.full_data` singleton in architecture spec vs. FullData instantiated per run

**Issue:** `2026-05-05-pybtctr2-architecture.md §10` says: "Singleton data access: `data.item` and `data.full_data` are module-level singletons accessed directly by all modules; no dependency injection." But `data-class.md §10` says: "`SimulationData` and `FullData` are instantiated per run (not singletons)." There is no `data.full_data` singleton described in the data module specs.

**Solution Options:**
- A) `data.full_data` is removed from the architecture spec. Only `data.item` (`LiveData`) is a module-level singleton. `FullData` is instantiated per run where needed. Update `2026-05-05-pybtctr2-architecture.md §10`.
- B) Establish `data.full_data` as a module-level singleton holding the pre-loaded wide DataFrame. Update `data-class.md §10` and `data-module.md §10` to include this singleton.

**Human Decision:** use A

---

## 12. Level dict key constants located in `helpers.py` vs. `constants.py`

**Issue:** `levels-class.md §3` says level dict keys (`LI_NAME`, `LI_TIME1`, `LI_VAL1`, etc.) are constants from `helpers.py`. `infrastructure-layer.md §5` says level dict keys belong in `constants.py` and `helpers.py` should only contain path functions. The infrastructure spec explicitly lists `LI_NAME/TIME1/VAL1/TIME2/VAL2/ACTIVE/TYPE/HAD_CONTACT` as belonging in `constants.py`. The two specs disagree on where these constants live.

**Solution Options:**
- A) Move LI_* constants to `constants.py`. Update `levels-class.md §3` to say constants come from `constants.py`. This aligns with the infrastructure layer cleanup.
- B) Keep LI_* in `helpers.py` and update `infrastructure-layer.md §5` to reflect that `helpers.py` still holds these level constants alongside its re-exports via `from constants import *`.

**Human Decision:** use A

---

## 13. Timeframe list inconsistencies across specs (includes 3? includes 1440?)

**Issue:** Multiple specs show different active timeframe lists:
- `how_to_use.md` and `robot-module.md` show `[1, 3, 5, 15, 60, 240]` (includes 3-min, no 1440).
- `2026-05-05-pybtctr2-architecture.md` critical path says "resample to `[1,3,5,15,60,240]` min".
- `02-data-layer.md`, `data-module.md`, `data-class.md`, `candles_config.yaml` examples all show `[1, 5, 15, 60, 240, 1440]` (no 3, includes 1440).
- The architecture spec is inconsistent with the data module spec family.

**Solution Options:**
- A) The canonical timeframe list is `[1, 5, 15, 60, 240, 1440]` as defined in `candles_config.yaml` and documented in the data module family. Update all references in `how_to_use.md`, `robot-module.md`, and `2026-05-05-pybtctr2-architecture.md` to remove 3-min and add 1440-min.
- B) The canonical timeframe list is `[1, 3, 5, 15, 60, 240]` (original implementation). Update data module family specs to reflect this.
- C) Both timeframe lists are valid (different config variants). Add explicit documentation that the list is operator-configurable and both examples are valid for different use cases.

**Human Decision:** use A

---

## 14. TrainRobot API: `set_data(cur_data)` + `do()` vs. `step(data_point, action)`

**Issue:** `04-execution-layer.md §4` says: "`train_robot.set_data(cur_data)` must be called before each `train_robot.do()`." `backtesting-module.md §3` exposes `set_data()` + `do()` as key interfaces. But `training-module.md §4.2 (simulation)` and `dataiterator-class.md §10` show: `robot.step(data_point, action)` — a single combined call. These are incompatible API signatures for the same class.

**Solution Options:**
- A) Adopt `step(data_point, action)` as the single combined method. Remove `set_data()` + `do()` from all specs. Update `04-execution-layer.md §4` and `backtesting-module.md` to use the step-based API.
- B) Keep `set_data(cur_data)` + `do()` as the canonical API. Update `training-module.md` and `dataiterator-class.md` to use the two-call pattern.

**Human Decision:** use A

---

## 15. `Strategy.trend_signals` attribute vs. "trend is a Data layer concern"

**Issue:** `strategy-module.md §3.1` says Strategy has `trend_signals` and `trend_modifiers` (dict of SignalManager) as attributes for "Trend detection per timeframe." `business-logic-layer.md §6` says: "Trend filtering is a Data layer concern — use `BoolValue_Signal("trend_up/down", tf)` in signal chains; **no trend detection infrastructure lives in Strategy**." These are mutually exclusive design decisions.

**Solution Options:**
- A) Remove `trend_signals` and `trend_modifiers` from Strategy class. Use `BoolValue_Signal("trend_up", tf)` / `BoolValue_Signal("trend_down", tf)` as gates within signal chains — trend columns (`trend_up`, `trend_down`) are pre-computed by the Data layer. Update `strategy-module.md §3.1`.
- B) Keep `trend_signals` as a Strategy attribute. Update `business-logic-layer.md §6` to say trend detection can live in both Strategy and Data layer (dual approach).

**Human Decision:** use A

---

## 16. Level type constants missing from `constants.py` — `LEVEL_TYPE_SHORT_1/2_RESISTANCE`

**Issue:** `infrastructure-layer.md §5` lists level type constants in `constants.py` as: `LEVEL_TYPE_LONG_SUPPORT/RESISTANCE (1/2)`, `LEVEL_TYPE_SHORT_SUPPORT/RESISTANCE (3/4)`, `LEVEL_TYPE_TARGET (5)`, `LEVEL_TYPE_AUTO_SUPPORT/RESISTANCE (6/7)`. But `levels-class.md §4` also has `LEVEL_TYPE_SHORT_1_RESISTANCE = 10`, `LEVEL_TYPE_SHORT_2_RESISTANCE = 11` which are absent from the `constants.py` listing. Also, names differ: `AUTO_TARGET_SUPPORT/RESISTANCE` (levels-class.md) vs `AUTO_SUPPORT/RESISTANCE` (infrastructure-layer.md).

**Solution Options:**
- A) Add `LEVEL_TYPE_SHORT_1_RESISTANCE = 10` and `LEVEL_TYPE_SHORT_2_RESISTANCE = 11` to `constants.py` listing in `infrastructure-layer.md §5`. Standardize the auto-level names to `LEVEL_TYPE_AUTO_SUPPORT/RESISTANCE`.
- B) Update `levels-class.md §4` to match exactly what is in `constants.py`. If SHORT_1/2_RESISTANCE constants don't exist, remove them from the levels spec.

**Human Decision:** use B

---

## 17. `BaseSignal.check()` signature: old `data.get_cur_price()` vs. `DataPoint.get()`

**Issue:** `business-logic-layer.md §6` says: "All signal classes access data exclusively via `data.get_cur_price(col, shift + self.shift, tf)` — they never access `data.ohlc[tf]` directly." But `signals-module.md §1` says signals read via `data_point.get(col, tf, shift)` (DataPoint protocol). These are different method signatures (old vs. v2.0 API). Signal specs use the v2 protocol; BL layer spec still references the old API.

**Solution Options:**
- A) Update `business-logic-layer.md §6` to say all signals access data via `data_point.get(col, tf, shift)` using the DataPoint protocol. Remove all references to `data.get_cur_price()` in the BL spec.
- B) The BL layer spec is describing the current code state (pre-migration). Add a migration note: "planned migration from `data.get_cur_price()` to `data_point.get()`" and document both APIs in transition.

**Human Decision:** use A

---

## 18. `SimulationData` constructor calls `root_folder(pair)` but `root_folder()` should take no args

**Issue:** `data-class.md §9` shows `SimulationData` constructor: `path = root_folder(pair) + "/df_with_indicators.pkl"` — passes `pair` to `root_folder()`. But `infrastructure-layer.md §5` (helpers.py cleanup) says the dead `pair` parameter must be removed: "Target: `def root_folder():` — no pair argument." Both specs describe the "correct" state, but they contradict each other on whether `root_folder()` takes a pair argument.

**Solution Options:**
- A) `root_folder()` takes no `pair` argument (reads env directly). Update `data-class.md §9 SimulationData` constructor to call `root_folder()` without arguments. This aligns with the helpers.py cleanup spec.
- B) Keep `root_folder(pair)` signature. Revert the helpers cleanup spec to say the pair parameter is preserved.

**Human Decision:** use A

---

## 19. `update_coin_size()` in BasePosition reads from `stock.item` directly

**Issue:** `base-position-class.md §4.5` says `update_coin_size()` does: "If `is_real_stock`: query broker for current funds via `stock.item.funds(coin_use)`." This means BasePosition (Business Logic layer) directly imports and calls `stock.item` (Infrastructure/Data layer). This violates layer boundaries: the BL layer should not call the exchange adapter directly. Also, it references `is_real_stock` which the alignment design says to remove.

**Solution Options:**
- A) Remove `update_coin_size()` from BasePosition entirely. Fund balance queries are an Execution layer concern — Robot queries funds via `stock.item.funds()` before opening a position and passes the result to Position. Remove the method from the spec.
- B) Inject a balance-query callback into Position at construction: `BasePosition(coin_use, coin_get, ..., balance_fn=None)`. Live: `balance_fn = lambda coin: stock.item.funds(coin)`. Simulation: `balance_fn = None` (unlimited funds).

**Human Decision:** use A

---

## 20. `position-cross-layer-alignment-design.md` has broken relative paths in Related specs

**Issue:** `2026-05-10-position-cross-layer-alignment-design.md` is located at `critical-path/position-module/` but its Related specs section links to: `layers/02-data-layer.md`, `critical-path/position-module/position-module.md`, etc. — these paths are relative to the project root, not to the file's actual location. A reader navigating from the file's directory would get broken links.

**Solution Options:**
- A) Fix all relative paths in that document to be correct relative to `critical-path/position-module/`: use `../../layers/02-data-layer.md`, `./position-module.md`, etc.
- B) Use root-relative paths throughout all docs (consistent `/` prefix from the spec root) and document this as the linking convention.

**Human Decision:** use B

---

## 21. Architecture spec vs. Phase 2 plan — planned file names don't match actual files

**Issue:** `2026-05-04-pybtctr2-specification-design.md §4.1` planned file names that differ from what was actually created:
- Planned: `stock-class.md`, `binance-adapter-class.md`, `order-executor-class.md` → Actual: `base-stock-interface-class.md`, `binance-stock-class.md`, `stock-item-class.md`
- Planned: `ohlc-class.md` → Actual: `dataiterator-class.md` (now documents `SimulationData`)
- Planned: `signal-types-class.md` → Actual: multiple signal files in `signals/` subdirectory
- The design spec's file hierarchy is out of date.

**Solution Options:**
- A) Update `2026-05-04-pybtctr2-specification-design.md §4.1` file hierarchy to match the actually created file structure.
- B) Leave the design doc as a historical artifact (original intent); add a note that actual implementation deviated from the plan.

**Human Decision:** use A

---

## 22. StrategyManager — invalid timeframes `trend_tf`/`price_check_tf`

**Issue:** `2026-05-10-position-cross-layer-alignment-design.md §3` (IC-5) says: "`StrategyManager.trend_tf` and `price_check_tf` contain invalid timeframes (3, 30, 45, 120) not present in `CANDLES = [1, 5, 15, 60, 240, 1440]`." The alignment design proposes loading these from `candles_config.yaml`. But no other spec documents this as resolved — `strategy-module.md` and `business-logic-layer.md` don't mention `trend_tf`/`price_check_tf` at all.

**Solution Options:**
- A) Add `trend_tf` and `price_check_tf` keys to `candles_config.yaml` schema (in infrastructure-layer.md). Document in `strategy-module.md §3.4` that StrategyManager validates these against CANDLES at startup. Mark IC-5 as resolved.
- B) Remove `trend_tf` and `price_check_tf` from StrategyManager entirely — strategy evaluation uses all active CANDLES timeframes.

**Human Decision:** use B

---

## 23. `validate_dataset.env` has unresolved TODO

**Issue:** `infrastructure-layer.md §5` (configs/*.env files table) lists `validate_dataset.env` with note: "Validation (TODO marker in file)." This is acknowledged but unresolved: the file is presumably identical to `train_dataset.env` but the distinction is never clarified.

**Solution Options:**
- A) Document the intended purpose of `validate_dataset.env` — should cover a different time range from `train_dataset.env` to prevent overfitting evaluation. Specify what the time range should be.
- B) Remove `validate_dataset.env` from the env file listing if it is currently just a copy of `train_dataset.env` with no meaningful difference.

**Human Decision:** use A

---

## 24. `StockHolder.item` initialized with empty `StockInterface` vs. `do_stock_init()` pattern

**Issue:** `stock-abstraction-module.md §StockHolder` says the singleton is "initialized to a default `StockInterface("","","")` at module level." But it also shows `do_stock_init(stock_name)` as the proper initialization function that replaces `stock_holder.item`. This creates a fragile state: any module that imports before `do_stock_init()` is called gets a no-op interface. The spec doesn't document when `do_stock_init()` must be called or what happens if it isn't.

**Solution Options:**
- A) Document the initialization contract clearly: `do_stock_init()` must be called at process startup before any other module accesses `stock.item`. Specify the call site (e.g., `pybtctr.py` and `trainer.py` entry points). Add a guard that raises if `stock.item.was_init` is False when any API method is called.
- B) Remove the default `StockInterface("")` initialization. `stock_holder.item` starts as `None`. Any access to `stock.item` before `do_stock_init()` raises `RuntimeError("Stock not initialized")`.

**Human Decision:** use A

---

## 25. `backtesting-module.md` stop-loss checks in `buy()`/`sell()` violate position ownership

**Issue:** `backtesting-module.md §B` (buy execution) and `§C` (sell execution) both have internal stop-loss checks flagged with `⚠️ [REFACTOR: stop-loss check should move to Position side]`. These methods directly check price against `stop_loss` and execute if triggered — bypassing the Position state machine. `business-logic-layer.md §6` says: "Position state machine is the source of truth for trade state; Robot/TrainRobot must never bypass `position.open()`/`close()`/`finalize()` to modify state directly."

**Solution Options:**
- A) Move stop-loss trigger detection into `Position.is_stop_loss_triggered(cur_data, cur_time)`. `TrainRobot.do()` calls this and, if True, calls `position.setup_stop_loss()` before executing the fill. Remove the in-line stop-loss checks from `buy()` and `sell()`.
- B) Keep stop-loss checks in `TrainRobot.buy()`/`sell()` but call position methods properly (`position.close(DO_STOP_LOSS, ...)`) rather than modifying state directly. The fill execution stays in TrainRobot.

**Human Decision:** use A

---

## 26. Robot module still describes calling `indi.Indicators()` instance with `calc()` method

**Issue:** `robot-module.md §Execution Flow — Polling Loop` step 7 says: "Create `indi.Indicators()` instance and call `calc()` on OHLC data for each timeframe (1, 3, 5, 15, 60, 240 minutes)." But `indicators-class.md §3` says the v2.0 Indicators is not instantiated — it is a class-level registry with `Indicators.compute(data_point, tf)` as a static method (no instance creation). The old `calc(df)` monolith method was removed in v2.0.

**Solution Options:**
- A) Update `robot-module.md §Execution Flow` step 7: data enrichment happens via `data_item.build_candles()` (which calls `Indicators.compute()` internally). Robot does not call Indicators directly. Remove the `indi.Indicators()` instantiation from the Robot flow.
- B) Keep the robot module description as reflecting current v1 code; add a note that v2.0 changes this call to go through `LiveData.build_candles()`.

**Human Decision:** use A

---

## 27. `how_to_use.md` Main flow has unresolved questions and TODOs

**Issue:** `how_to_use.md` contains multiple unresolved design questions and TODOs directly in the spec content:
- `## Q: Who is responsible for position action price -> strategy+market` — answered inline but never formalized
- `## Q: Who is responsible for position action amount` — not answered
- `Q: how to use ATR`, `Q: how to use volume` — unanswered
- `TODO: consider position extension` — untracked
- `TODO: potentially price MA can be used as well` — untracked
- `### Actions Signals — TODO:` — entirely empty section

This document is a design scratch pad, not a clean spec, but it's stored alongside specifications.

**Solution Options:**
- A) Migrate resolved design decisions from `how_to_use.md` into the appropriate layer/module specs. Archive `how_to_use.md` as an operational runbook (Docker commands, AWS notes) and move its design content to proper specs.
- B) Create a `design-decisions.md` doc that captures all answered Qs and TODOs. Keep `how_to_use.md` as-is for operational reference.

**Human Decision:** use B

---
