# Trade Executor — Main Goal

High-level description of trade_executor's scope and responsibilities. This is
a seed document — each bullet below will be expanded into its own detailed
specification later.

## Relationship to `main/`

- Standalone service, written in Rust, decoupled from `main/`'s Python
  trading system. `main/` keeps owning signal generation, strategy
  selection, and backtesting/simulation — unaffected by this project.
- `main/`'s StrategyManager publishes trade decisions (open/close/modify
  position: side, size, entry, stop-loss, take-profit) to trade_executor
  over a message queue. Transport choice (Redis/NATS/ZeroMQ/etc.) is
  deferred to its own spec.
- `main/` also sends the levels trade_executor should watch for a given
  position — support/resistance, target/SL reference levels from
  `main/`'s existing Levels module — delivered alongside/as part of the
  trade decision.
- Every decision from `main/` carries a unique id; trade_executor
  deduplicates on it, so redelivery of an already-processed decision
  (queue retries, at-least-once delivery) is a no-op.
- The queue also carries force signals (e.g. force-close a position,
  override local risk logic) — same channel and message path as regular
  trade decisions, not a separate side channel. Force actions still go
  through the exchange-native-order-first safety path; no shortcut
  bypasses it.
- backward message passing to main/ should be available to notify fmain about current position state, and  actions that were executed

## Data layer

- Maintains a live order book per pair via exchange websocket
  (incremental updates), and retrieves candlesticks from the exchange.
- Exchange-adapter interface abstracts order placement, market-data
  subscription, and account/balance queries. Binance and MEXC are the first
  concrete implementation; the core is exchange-agnostic from the start.
- The exchange abstraction covers multiple asset/market kinds on the
  same exchange: spot, margin, and futures trading — not spot-only.
- Persists captured market data (order book updates, candles) locally to
  allow replaying specific market conditions/situations and backtesting
  trade_executor's own local simple signals — scoped to the local signal
  layer described below, separate from `main/`'s full backtesting system.
  Any change to the local signal layer must pass through this replay/
  backtest harness before being enabled in live trading — a required
  gate, not just a research tool.

## Local analysis and execution

- **Critical-level analysis**: derives execution-critical levels from its
  own live order book — e.g. detecting a resting-order "wall" likely to
  stop price movement. Feeds directly into local risk/position logic
  (adjusts stop-loss/take-profit/entry placement), no round-trip to
  `main/`.
- **Simplified signals**: a lightweight signal layer over its own live
  feed (order book + candles) — e.g. a sharp volume direction-change
  likely to reverse price. These refine timing only: `main/` decides
  what to trade and the authorized window/conditions; local signals pick
  the exact moment to fire entry/exit within that window.
- Owns position lifecycle and risk logic once a position is handed off:
  reacts locally to stop-loss/take-profit/trailing-stop, wall detection,
  and simplified-signal timing, without round-tripping to `main/` per
  tick. Reports state changes (opened, closed, stopped out, fills) back
  to `main/`.
- For leveraged positions (margin/futures), local risk logic also tracks
  margin/liquidation proximity as a distinct, higher-priority risk than
  price-based stop-loss/take-profit — since exchange-forced liquidation
  happens regardless of whether a stop order manages to fill in time.
- Local safety actions (stop-loss, liquidation avoidance) always take
  priority and execute immediately, never blocked waiting on `main/`. A
  `main/` command arriving for a position already closed locally is a
  no-op, reported back as "already closed," not an error.
- Local risk logic is an enhancement over exchange-native protection,
  never a replacement: a resting stop-loss/liquidation-safe order is
  always placed on the exchange itself for an open position, so
  protection survives even if trade_executor's own feed or process
  dies. On feed loss beyond a short grace period, this exchange-native
  order is the fallback of last resort. At the end two stop loss will be placed and managed on different levels, one in executor and second on exchange itself

## Operational scope

- Multi-pair: one instance handles several trading pairs concurrently.
- Crash recovery required: position/order state is persisted so a
  restart doesn't lose track of open trades or in-flight orders. On
  restart, persisted state is reconciled against the exchange's actual
  account/position/open-orders state — the exchange is always the
  source of truth, since fills or liquidations may have happened while
  trade_executor was down.
- Paper-trading / dry-run mode: simulates fills against the live feed
  without sending real orders — separate from `main/`'s historical
  backtesting.
- Deployed as a Docker container, consistent with `main/`'s existing
  infrastructure (log collection, volume-mounted local data store,
  env-based config).

## Observability

- Emits structured logs/metrics for all state transitions and risk
  events. Alerts (not just logs) on conditions that threaten money
  safety — feed staleness/disconnect, failed order placement,
  approaching liquidation.

## Security

- Exchange API credentials are injected via env/config at process start
  (matching `main/`'s existing convention), never logged, never sent
  over the message queue.

## Interfaces

- **CLI**: command-line interface for inspecting the running process
  (status, positions, logs). Force actions are issued as queue messages
  (see above), not a separate CLI-only command path — the CLI may
  publish them onto the same queue for convenience.
- **Visualizer**: separate front end rendering historical market data
  (from the local data store), switching to live updates while the
  executor is running live trading.
