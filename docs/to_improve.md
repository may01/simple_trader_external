# Specification Gaps — to_improve.md

Each entry: **Improvement** | **Solution Options** | **Human Decision**

---

## 1. `LiveOrderTracker` class — no dedicated spec

**Improvement:** `2026-05-10-position-cross-layer-alignment-design.md §3` introduces `LiveOrderTracker` as a new class that carries live-only order IDs, loan tracking, and crash-recovery state extracted from the Position facade. Multiple specs reference it (`04-execution-layer.md`, `04-execution-layer-impl.md`, `base-position-class.md`) but no dedicated class spec exists. There is no authoritative definition of its constructor signature, attributes (`buy_id`, `sell_id`, `loan`, `repay`), methods (`save()`, `load()`, `clear()`), or lifecycle (when it is created, passed in, and discarded).

**Solution Options:**
- A) Create `external/docs/superpowers/specs/critical-path/position-module/live-order-tracker-class.md` defining: constructor `__init__(pair, thread_num)`, attributes, save/load contract (what file path, what format), and how Robot and TrainRobot interact with it. Include state diagram showing when each attribute is set/cleared.
- B) Expand `04-execution-layer-impl.md §8` (currently marked RESOLVED) into a full `LiveOrderTracker` subsection covering the same content — keep it inside the execution layer doc rather than as a standalone class spec.
- C) Inline the full spec into the existing position alignment design doc as a new §7 addendum.

**Human Decision:** _______________

---

## 2. `position_config.yaml` — referenced but unspecified

**Improvement:** `2026-05-10-position-cross-layer-alignment-design.md §5` says "position parameters (full_position, risk_per_trade, safety_close_time) should be loaded from a yaml config rather than hardcoded or passed as constructor args." `base-position-class.md §2` references this config in its constructor. But no spec defines the yaml schema: which keys exist, their types, defaults, validation rules, or which path the file lives at. Without a schema, implementers cannot write the config or the loader.

**Solution Options:**
- A) Create `external/docs/superpowers/specs/critical-path/position-module/position-config-schema.md` defining the YAML schema with all keys, types, required/optional status, and defaults. Add a cross-reference from `base-position-class.md` and `01-infrastructure-layer.md`.
- B) Add a "Configuration Schema" section to `base-position-class.md §2` (constructor section) that embeds the schema inline.
- C) Add the schema to `candles_config.yaml` / `indicators_config.yaml` design notes in the data layer as a third config file, keeping all runtime config specs co-located.

**Human Decision:** _______________

---

## 3. Production strategies in `strategies/new_simulation/` — completely unspecified

**Improvement:** `strategy-module.md` defines `ExampleStrategyLong` and `ExampleStrategyShort` as reference implementations only, explicitly not production strategies. `training-module.md` mentions `strategies/new_simulation/` as the directory containing actual simulation-ready strategies. But no spec describes how production strategies are structured, what signal chains they use, how they differ from the example strategies, or what the `new_simulation/` naming convention means. Strategy development is the core intellectual property of the system; having no spec for it means new strategies cannot be written consistently.

**Solution Options:**
- A) Create `external/docs/superpowers/specs/critical-path/strategy-module/production-strategy-guide.md` describing: the directory structure of `strategies/new_simulation/`, required override methods, signal composition patterns, testing checklist, and naming conventions.
- B) Add a "Production Strategy Template" section to the existing `strategy-module.md` with a commented skeleton and checklist.
- C) Document one concrete production strategy end-to-end as a worked example spec (redact any proprietary signal logic, just show structure).

**Human Decision:** _______________

---

## 4. `Action` class — used everywhere, specified nowhere

**Improvement:** Every execution spec (`robot-module.md`, `backtesting-module.md`, `04-execution-layer.md`) references an `Action` object created at each tick to record events. `strategy-module.md` and `signals-module.md` both accept `action_msg` parameters. But no spec defines what `Action` is: its constructor, attributes (`timestamp`, `events: list`, `position_state`, etc.), what `action_msg.add_event()` / `action_msg.set_*()` methods exist, how it is serialized, or what schema the per-step pkl files use. Implementers must guess the API from usage context.

**Solution Options:**
- A) Create `external/docs/superpowers/specs/critical-path/action-class.md` with full constructor, attribute list, method signatures, and the serialization format written to disk per step.
- B) Add an "Action Object" section to `03-business-logic-layer.md §5` since Action is the event record passed through all BL calls.
- C) Add a "Data Structures" appendix to `04-execution-layer.md` covering Action, ActionEvent, and any other shared data-only classes.

**Human Decision:** _______________

---

## 5. `pybtctr.py` main entry point — no spec

**Improvement:** `01-infrastructure-layer-setup.md` describes Docker execution paths A–H for all `RUN_TYPE` values, and `how_to_use.md` shows `docker run` commands. But no spec describes `pybtctr.py` itself: how it reads `RUN_TYPE`, which classes it instantiates, how it wires dependencies (fee, config, strategy list), or how it handles startup errors. This is the system's only entry point for live trading; without a spec, dependency wiring decisions are made ad-hoc and may not match the injection contract described in the infrastructure spec.

**Solution Options:**
- A) Create `external/docs/superpowers/specs/critical-path/entrypoint.md` specifying: argument/env-var reading order, object construction sequence (Stock → Data → StrategyManager → Position → Robot), startup validation checks, and failure modes.
- B) Add a "Startup Sequence" section to `01-infrastructure-layer.md §7` that maps each `RUN_TYPE` to the objects it constructs and the order of construction.
- C) Add startup wiring to each relevant module spec as a "How it is instantiated" subsection.

**Human Decision:** _______________

---

## 6. `nn_signals.py` and `position_signals.py` — listed as TBD

**Improvement:** `signals-module.md §2` lists `nn_signals.py` and `position_signals.py` as files in the `signals_lib/` directory with descriptions marked TBD. NN signals presumably wrap `NNProbabilityField` predictions as `BoolValue_Signal` instances; position signals presumably fire based on position state (price relative to entry, time elapsed, etc.). Neither class set is specified. These files are listed in the module boundary so implementers know they exist — but without specs, their signal types, constructor parameters, and data dependencies are undefined.

**Solution Options:**
- A) Create `external/docs/superpowers/specs/critical-path/signals-module/nn-signals.md` and `position-signals.md` each covering: purpose, signal class list, constructor signatures, and which data columns each signal reads.
- B) Extend `signals-module.md §5` (Signal Types) with subsections for NN signals and position signals, keeping all signal documentation in one file.
- C) Mark these as deferred (Phase 2 scope) in the spec and add a tracked issue to `to_fix.md` when they are implemented.

**Human Decision:** _______________

---

## 7. `PredictorField`, `NNProbabilityField`, `PriceRejectionField` — pending implementation, no spec

**Improvement:** `indicators-class.md §4` mentions `PredictorField`, `NNProbabilityField`, and `PriceRejectionField` as planned `IndicatorField` subtypes marked "pending implementation." These are the data-layer wrappers that expose NN model outputs as indicator columns readable by signals. Without specs: the column naming convention (e.g., `nn_prob_long`, `rejection_score`), the model loading mechanism, inference input shape, caching strategy, and how they integrate with `Indicators.compute()` are all undefined.

**Solution Options:**
- A) Create `external/docs/superpowers/specs/critical-path/data-module/nn-indicator-fields.md` covering all three field types: output column names, model artifact paths, input feature construction, caching (per `data.set_nn_cache()`), and integration with `Indicators.compute()`.
- B) Add a "Pending IndicatorField Types" section to `indicators-class.md` that sketches the spec sufficiently for implementation to begin.
- C) Defer until NN pipeline is more mature; add a `TODO: NNProbabilityField spec` placeholder to `indicators-class.md §4` referencing the neural-network module.

**Human Decision:** _______________

---

## 8. SignalChain timeout/reset mechanism — partially documented

**Improvement:** `signals-module.md §3.2` says `SignalChain.check()` evaluates the current signal and advances `cur_pos` if it fires; `reset()` restores `cur_pos=0` when a signal returns `reset()=True`. But: (1) there is no spec for time-based chain expiry (if signal 1 fires but signal 2 never fires within N candles, should the chain reset?); (2) it is unspecified whether a chain resets on tick if a later signal in the chain fires but an earlier signal has not (out-of-order). Both behaviours are observable in real trading scenarios and their absence creates ambiguous implementation choices.

**Solution Options:**
- A) Add a "Chain Timeout" subsection to `signals-module.md §3.2`: define `timeout_candles` as an optional `SignalChain` constructor parameter; document reset semantics when timeout expires. Add a "Partial Reset" rule: a chain only advances forward, never skips signals; out-of-sequence signals are ignored.
- B) Add the timeout parameter to `SignalChain` constructor in `03-business-logic-layer.md §5` and document the rule there, keeping business logic in the BL spec.
- C) Document current behaviour (no timeout, strict forward-only advancement) as an explicit design decision with a rationale note explaining why timeout was not added.

**Human Decision:** _______________

---

## 9. Position sizing formula — inconsistent documentation

**Improvement:** `business-logic-layer.md §6` says: `size = min(full_position, full_position × risk_per_trade / (risk / avg_price))`. `base-position-class.md §3` describes `LongPosition` / `ShortPosition` computing "graduated position sizing" with the same formula but different variable names (`risk_per_trade=1% of full_position`). `robot-module.md` has no mention of position sizing. `position-module.md` does not describe the formula. The formula is stated in two places with slightly different notation and no worked example, making it unclear whether `risk` here means stop-loss distance in percent, in USD, or in coin units.

**Solution Options:**
- A) Add a "Position Sizing" section to `base-position-class.md §3` with: formula in full, units for each variable, a worked numeric example (e.g., full_position=1000 USDT, risk_per_trade=0.01, stop=1% below entry → size=…), and a reference to this section from `03-business-logic-layer.md`.
- B) Create a standalone `external/docs/superpowers/specs/critical-path/position-module/position-sizing.md` document covering the formula, the risk_per_trade config parameter, and edge cases (minimum order size, max position cap).
- C) Remove the formula from `03-business-logic-layer.md` (it is a BL concern, not a layer-boundary concern) and keep a single authoritative definition only in `base-position-class.md`.

**Human Decision:** _______________

---

## 10. StrategyManager conflict resolution for simultaneous OPEN signals — Robot side undocumented

**Improvement:** `03-business-logic-layer.md §4` says "multiple simultaneous OPENs → conflict → returns NOTHING." `strategy-module.md §5.4` says the same. But the spec stops there: what does Robot/TrainRobot do when it receives NOTHING? Does it hold the previous position state? Does it increment a "missed opportunity" counter? Does it log a conflict warning? The downstream behaviour when StrategyManager returns NOTHING for an OPEN conflict is completely unspecified in the execution layer docs.

**Solution Options:**
- A) Add a "NOTHING action handling" subsection to `robot-module.md §4` (do() flow) and `backtesting-module.md §4.A` describing what happens: position state unchanged, no action taken, optional conflict logged.
- B) Add conflict handling to `04-execution-layer.md §3` (Robot.do() flow) as part of the action routing logic.
- C) Handle at StrategyManager level: add a `last_action` attribute to StrategyManager that Robot can query after NOTHING to understand why no action was returned.

**Human Decision:** _______________

---

## 11. `DataAttributes.TargetsStatsAttribute` computation pipeline — unspecified

**Improvement:** `data-module.md §10.3` lists `TargetsStatsAttribute` as one of the data attributes computed by `DataPreparer`. Its purpose is described as "statistical targets for model training." But neither `data-module.md` nor any other spec defines: what columns it produces, how they are computed (future price thresholds? realized volatility?), what look-ahead window it uses, or how it interacts with the no-look-ahead-in-live-path constraint. Without this, the training pipeline target construction is undocumented.

**Solution Options:**
- A) Add a "TargetsStatsAttribute" subsection to `data-module.md §10.3` (or create `data-attributes.md`) covering: output column names, computation method, look-ahead window, and the boundary between training-only columns and live-safe columns.
- B) Create a `neural-network-module.md` spec that covers all ML-pipeline concerns: target construction, feature selection, model architecture, training loop, and inference integration. `TargetsStatsAttribute` is one section of this.
- C) Add a column schema table to `dataiterator-class.md` (which describes `df_with_indicators.pkl`) listing all columns including target columns, their types, and computation logic.

**Human Decision:** _______________

---

## 12. Error handling contract for Binance API failures in live trading loop — absent

**Improvement:** No spec describes what Robot should do when a Binance API call fails: network timeout, rate-limit 429, order rejection, partial fill, or authentication error. `robot-module.md` shows the `do()` loop with exception handling only at the outermost level ("catch any exceptions, log error, continue"). `stock-abstraction-module.md` lists Binance API methods but says nothing about error codes or retry policy. In live trading, silent continuation after a failed order could leave the bot in an inconsistent position state (order sent but not confirmed filled).

**Solution Options:**
- A) Add an "Error Handling Contract" section to `04-execution-layer.md §6` covering: retriable errors (network timeout → retry ≤3 times with backoff), fatal errors (auth failure → halt), partial fill handling (query order status before next tick), and state recovery after unconfirmed fills.
- B) Add error handling to `stock-abstraction-module.md §3` for each API method, listing expected exception types and recommended caller response.
- C) Create a separate `external/docs/superpowers/specs/critical-path/robot-module/error-handling.md` document covering the full error taxonomy and Robot's response to each.

**Human Decision:** _______________

---

## 13. Integration test coverage contract — none documented

**Improvement:** No spec defines what integration tests exist, what they cover, or what the expected test baseline is before deploying changes. `how_to_use.md` mentions `validate_dataset.env` and `validate` RUN_TYPE but only as operational commands. The spec set documents class interfaces and data flows but has no "Testing Strategy" section anywhere. Without a test contract, it is unclear which behaviours are regression-protected and which can break silently.

**Solution Options:**
- A) Create `external/docs/superpowers/specs/testing-strategy.md` covering: unit test scope (per-class), integration test scope (full backtest run on known dataset → known revenue), acceptance criteria for a clean test run, and the `validate_dataset.env` purpose and expected output.
- B) Add a "Test Coverage" subsection to each module spec defining what that module's tests must cover.
- C) Add a minimal "Testing" section to `how_to_use.md §Testing` documenting only the integration/smoke test command and expected output range for the validate dataset.

**Human Decision:** _______________

---

## 14. `do_stock_init()` call site contract — when it must be called

**Improvement:** `robot-module.md §4` shows `do_stock_init()` in the Robot startup sequence and `01-infrastructure-layer-setup.md §Path A` shows it being called. But no spec defines: what `do_stock_init()` does internally (account balance check? fee fetch? symbol info load?), what happens if it is not called before `do()`, whether it is idempotent (can it be called twice?), and whether TrainRobot also calls it. Without this contract, any refactor of the startup sequence risks omitting a required initialization.

**Solution Options:**
- A) Add a `do_stock_init()` subsection to `robot-module.md §4` covering: what it initializes, preconditions (authenticated Binance connection), postconditions (coin balances set, fee confirmed), idempotency guarantee, and whether TrainRobot calls a no-op stub or skips it entirely.
- B) Add `do_stock_init()` to `stock-abstraction-module.md §3` as a method spec with the same content, since it is a Stock-level operation.
- C) Rename and document it as part of the startup sequence in `pybtctr.py` entrypoint spec (improvement #5 above), treating it as an entrypoint concern rather than a module method concern.

**Human Decision:** _______________

---

## 15. `validate_dataset.env` — intended purpose and time range not documented

**Improvement:** `how_to_use.md` references `validate_dataset.env` as one of the env files used for a smoke-test backtest run. But no spec or comment explains: what time range it covers, what coin/pair it tests, what the expected revenue output is (so a regression can be detected), or why it exists as a separate env file rather than using the standard dataset range. Without documented expected output, the validate step cannot catch regressions.

**Solution Options:**
- A) Add a "Validate Dataset" section to `how_to_use.md §Testing` documenting: the date range, pair, expected revenue range (e.g., "+2% to +8%"), and how to interpret a result outside that range.
- B) Embed the expected output as a comment inside `validate_dataset.env` itself so the context travels with the file.
- C) Add the validate dataset spec to the testing strategy document (improvement #13 above) as the canonical smoke-test definition.

**Human Decision:** _______________

---

## 16. `SimulationData` / `DataIterator` rename — file name does not match class name

**Improvement:** `dataiterator-class.md` documents the class now named `SimulationData` (renamed in `training-module.md v2.0`), but the spec file is still named `dataiterator-class.md`. The class name `DataIterator` appears in the file's own headings and in `backtesting-module.md §5`. This creates confusion when searching for the spec: the file name implies the old class, the content describes the new one, and existing references to `DataIterator` in the backtest spec are stale.

**Solution Options:**
- A) Rename `dataiterator-class.md` to `simulation-data-class.md`, update all cross-references in `backtesting-module.md`, `02-data-layer.md`, and `training-module.md` to point to the new file name.
- B) Keep the file name as `dataiterator-class.md` but add a prominent `> Renamed: DataIterator → SimulationData as of training-module v2.0` banner at the top of the file.
- C) Merge `dataiterator-class.md` content into `data-module.md §SimulationData` since `SimulationData` is the new data-layer class; delete the standalone file.

**Human Decision:** _______________

---

## 17. `TrainerConfig` dataclass — referenced as improvement, never specified

**Improvement:** `training-module.md §7` (Potential Improvements) mentions "introduce a `TrainerConfig` dataclass to replace individual constructor parameters." But no spec defines what fields `TrainerConfig` would contain, what its relationship to `candles_config.yaml` and `indicators_config.yaml` is, or whether the Trainer and SimulationOrchestrator share one config object or have separate configs. The improvement is listed but has no implementation target.

**Solution Options:**
- A) Promote from improvement to spec: add a `TrainerConfig` section to `training-module.md §5` (Key Classes) defining the dataclass fields (start_time, end_time, num_threads, pair, coin, data_path, etc.) and how each class reads from it.
- B) Keep as an improvement note but add acceptance criteria: "TrainerConfig replaces all `os.environ` reads in `Trainer.__init__()` and `SimulationOrchestrator.__init__()`" so implementation is unambiguous when the time comes.
- C) Replace `TrainerConfig` with a unified `AppConfig` that covers both training and live-trading configuration, documented in the infrastructure layer spec.

**Human Decision:** _______________

---

## 18. `DataPreparer` parallelization coordination — shared memory vs. file-based undefined

**Improvement:** `training-module.md §4.B` says `DataPreparer` prepares data for each thread segment. It is unclear whether segments are computed sequentially (one `DataPreparer` per call), in parallel processes (separate `DataPreparer` per segment), or via shared memory. The spec says `SimulationOrchestrator` "divides time range" and "spawns TrainRobot per segment" but does not describe whether `DataPreparer` also runs in parallel or only once before segments are handed to TrainRobots.

**Solution Options:**
- A) Add a "Parallelization Model" subsection to `training-module.md §4.B` specifying: `DataPreparer` runs once sequentially producing `df_with_indicators.pkl`; `SimulationOrchestrator` reads the pkl and partitions it into time segments; each `TrainRobot` process receives its segment's slice. No shared memory.
- B) Add a sequence diagram to `training-module.md §3` (Data Flow section) showing the full multi-process lifecycle: DataPreparer → pkl → SimulationOrchestrator forks → N TrainRobot workers → results aggregated.
- C) Add an explicit "Concurrency Contract" section to `training-module.md §6` (Existing Approach) covering which objects are shared across processes, which are process-local, and how the `df_with_indicators.pkl` is accessed (memory-mapped vs. loaded per process).

**Human Decision:** _______________

---

## 19. `how_to_use.md` "Actions Signals" section — empty placeholder

**Improvement:** `how_to_use.md` contains a section titled "Actions Signals" that is completely empty. Given the central role of signals and actions in the system, this section likely was intended to document how to interpret live action logs, how to read signal chain state, or how to debug a strategy decision. The empty section is a gap that makes the operational runbook incomplete.

**Solution Options:**
- A) Fill the "Actions Signals" section with: how to read the per-step action pkl files, what fields the Action object contains, how to interpret signal chain state from logs, and how to correlate action events with candle data.
- B) Remove the empty section and move its intended content to the relevant module specs (`action-class.md` from improvement #4, `signals-module.md`), keeping `how_to_use.md` as a pure operational runbook.
- C) Replace the empty section with a link to the Action class spec (improvement #4) and signals module spec, documenting only the operational commands to dump action data.

**Human Decision:** _______________

---

## 20. Multi-timeframe candle list — hardcoded `[1, 3, 5, 15, 60, 240]` vs. config-driven

**Improvement:** `robot-module.md §4` shows Robot initializing with timeframe list `[1, 3, 5, 15, 60, 240]` hardcoded. `01-infrastructure-layer.md §5` says "timeframe list defined in `candles_config.yaml`." `data-module.md §4` says `CANDLES` dict is config-driven. But no spec confirms whether Robot reads from `candles_config.yaml` or hardcodes the list. If Robot hardcodes it and config changes, the live and backtest paths would diverge in what timeframes they process.

**Solution Options:**
- A) Update `robot-module.md §4` to show Robot reading `CANDLES` from `candles_config.yaml` via the config loader, not from a hardcoded list. Document this as the single source of truth for timeframe selection.
- B) Add a "Timeframe Configuration" section to `01-infrastructure-layer.md §5` explicitly listing Robot, TrainRobot, DataPreparer, and Indicators as consumers of `candles_config.yaml`, so it is clear that all paths share the same list.
- C) Add an assertion in Robot startup: `assert set(self.timeframes) == set(CANDLES.keys())` to catch any divergence at runtime, and document this guard in `robot-module.md`.

**Human Decision:** _______________

---

## 21. `stock-abstraction-module.md` `depth()` method — live-only call from StrategyManager

**Improvement:** `stock-abstraction-module.md §3` includes a `depth()` method (order book depth query) described as "called from StrategyManager (live-only, pending removal)." No spec documents: what StrategyManager does with depth data, which signal or strategy reads it, or what the removal plan is. This is dead-spec weight: the method is documented but marked for removal, with no timeline, no tracking issue, and no documentation of what replaces the depth-based logic.

**Solution Options:**
- A) Remove `depth()` from `stock-abstraction-module.md` now; add a note: "depth() removed — any depth-based signal logic must be replaced with order-book indicator columns in the Data layer before live deployment."
- B) Add a "Pending Removal" section to `stock-abstraction-module.md` that tracks `depth()` with: current callers, intended replacement (data-layer order-book indicator?), and removal target milestone.
- C) Specify the replacement first: document how order-book depth would be exposed as a data column (e.g., `bid_ask_spread` computed in `LiveData.build_candles()`), then mark `depth()` for removal once the replacement spec exists.

**Human Decision:** _______________

---

## 22. `Graber` class — partial spec in training module

**Improvement:** `training-module.md §4.A` describes `Graber` as the class responsible for live data collection via Binance API. But the spec only lists three methods (`grab_candles()`, `grab_indicators()`, `save()`) with one-line descriptions. No spec defines: the retry/rate-limit policy on Binance candle requests, what happens when a grab fails mid-range, how the grabbed data format relates to `df_with_indicators.pkl`, or whether `Graber` runs concurrently with `DataPreparer` or sequentially before it.

**Solution Options:**
- A) Create `external/docs/superpowers/specs/critical-path/training-module/graber-class.md` with: full method signatures, Binance API call sequence, error handling for rate limits and network failures, output format (which pkl or csv files are written), and sequencing relative to DataPreparer.
- B) Expand the `Graber` subsection in `training-module.md §4.A` to include the same content, keeping all training docs in one file.
- C) Merge Graber responsibilities into `LiveDataCollector` spec since both deal with live-data acquisition; document as one class if the distinction is implementation-only.

**Human Decision:** _______________

---

## 23. Neural network training pipeline — no dedicated spec

**Improvement:** The system includes NN-based signals and a `NNOrchestrator` class in the training module. `training-module.md §4.D` describes `NNOrchestrator` as responsible for "training NN models, saving artifacts, running inference." But no spec covers: model architecture (what type of NN, input shape, output shape), feature engineering (which indicator columns go in), training/validation split strategy, artifact storage format and path, model versioning, or how the saved model is loaded during live inference. Without this, the NN pipeline cannot be re-implemented or debugged from specs alone.

**Solution Options:**
- A) Create `external/docs/superpowers/specs/critical-path/neural-network-module.md` covering: model type, input feature set, target construction (linking to TargetsStatsAttribute from improvement #11), training split, artifact paths, versioning scheme, and live inference integration.
- B) Expand `training-module.md §4.D` (NNOrchestrator) into a full subsection with architecture, training, and inference details; keep all ML concerns in the training module.
- C) Split into two specs: `nn-training.md` (offline training pipeline) and `nn-inference.md` (live inference and `NNProbabilityField` integration), since training and inference have different owners/lifecycles.

**Human Decision:** _______________

---

## 24. `how_to_use.md` design scratch-pad content — should be archived or promoted

**Improvement:** `how_to_use.md` mixes operational runbook content (Docker commands, AWS setup) with design scratch-pad content (unresolved questions marked "Q:", "TODO:" notes, ad-hoc architecture notes that predate the formal specs). The design questions were never resolved in the formal specs. This means there are design decisions documented only in the runbook as informal TODOs with no resolution, creating a parallel informal spec layer that may contradict the formal one.

**Solution Options:**
- A) Audit all `Q:` and `TODO:` items in `how_to_use.md`: resolve each in the appropriate spec, then remove them from the runbook. Keep `how_to_use.md` as a pure operational document.
- B) Move all design-question content from `how_to_use.md` into `to_fix.md` or a new `open-questions.md` tracking document, so nothing is lost but the runbook stays clean.
- C) Add a `## Design Notes (Archive)` section at the bottom of `how_to_use.md` and move all non-operational content there, clearly labelled as informal/historic.

**Human Decision:** _______________

---

## 25. `Levels` update mechanism — `update()` method marked non-functional

**Improvement:** `levels-class.md §4` documents a `Levels.update()` method with a comment saying "non-functional / commented out." This method is responsible for dynamically updating support/resistance levels as new candles arrive. Without it, levels are only computed once at startup and never refreshed during a live session. The spec does not say when `update()` will be implemented, what algorithm it should use, or how stale levels affect trading decisions. Callers of `get_levels()` in strategies may rely on fresh levels and silently get stale ones.

**Solution Options:**
- A) Specify the `update()` algorithm fully in `levels-class.md §4`: what triggers an update (every N candles? new level detected?), the detection algorithm (swing high/low? volume cluster?), and how levels are evicted when stale. Mark this as required before live deployment.
- B) Remove `update()` from the spec (matching current non-functional status) and document that levels are computed once at `__init__` and treated as static for the session. Add a note: "dynamic level refresh is a future improvement."
- C) Replace the commented-out `update()` with a `rebuild()` that fully recomputes levels from the current `ohlc` window, called periodically by Robot. Spec the rebuild trigger and cost in `robot-module.md`.

**Human Decision:** _______________

