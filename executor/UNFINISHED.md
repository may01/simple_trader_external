# Unfinished — executor

What is left open across the plans that have landed but are not closed out. Newest work on top. A line here means "known and deliberate", not "forgotten"; when a line is done, tick it in its own plan and delete it here.

---

## SAR flip test signal (plan [2026-09-23](plans/2026-09-23-sar-flip-test-signal-plan.md), spec [2026-09-22](specs/2026-09-22-sar-flip-test-signal-design.md))

Layers 1–6 are implemented, merged and green: Docker gate **1037 passed / 0 failed** (baseline was 1007). Layer 7 is where it stops.

- [ ] **The last hop of the `no_trade` run is unproven.** Two flips were observed live on LINKUSDT — `Buy` (sar 13.28632 vs price 13.28700) and `Sell` on the way back — and each produced a `signal_log` row, a `decision_log` row, a `signal_firing` metric and reached `execution`. Both then died at **sizing**: `NotPlaced { "computed size exceeds account limits" }`, before `NoTradeAccount`'s refusal — which is the one thing `no_trade` exists to demonstrate. `within_account_limits` needs `free_quote × MAX_NOTIONAL_FRACTION ≥ notional`, so at `RISK_PER_TRADE=0.5` (notional $50, `MAX_NOTIONAL_FRACTION=0.5`) it needs **≥ $100 free USDT on cross margin**. Unblock by funding the sub-account, or accept the hop as covered by unit tests only.
- [ ] **Spec §11.4's acceptance criterion is not met.** It asks for one full `Open → flip → Close → Open(reverse)` cycle with position-state rows and the visualiser rendering it. No position ever opened, so close-then-reverse has only ever run against `FakeExecutorSpy`, never against a real fill.
- [ ] **Layer 7.2, the live run, has not started (HUMAN GATE).** Decide `RISK_PER_TRADE` deliberately first: `compute_size` is `RISK_PER_TRADE / |entry − stop|` against a flat 1% stop, so **notional = 100 × RISK_PER_TRADE** regardless of price. The committed default of `100` therefore asks for a $10,000 position from a signal whose exits are two placeholder constants.
- [ ] **`MIN_RR=0` is deployment-wide.** Committed to `docker-compose.yml` for this test (spec §9): it disables the R:R gate for *every* decision path in that deployment, including the depletion signals and anything `main/` sends over MQ. Any deployment doing more than this test needs its own value.
- [ ] **`main/`'s full suite has not been run against this change.** Its config tests pass on the host (7/7, RED before the YAML entry), but 21 modules cannot be collected there — no `optuna`, `plotly`, `zmq`. The `simple_trader` image now exists locally, so `docker compose run --rm live python3 -m pytest tests/ -q` is runnable.
- [ ] **Paper mode is still not wired** (spec §13). `EXECUTION_MODE` parses `no_trade|live` only, and `PaperMarketAccount` needs the market-data feed that `boot` constructs *after* receiving the account — so paper needs `boot` to take a real account for ingestion and a simulated one for execution. It is the only way to watch a full position lifecycle without money.
- [ ] **Replay of an indicator-driven signal is unsupported** (spec §13). Expiry is judged against wall-clock time, so `replay_harness` passes `NoIndicators` permanently: no reading, no flip. A replayable source (`as_of` driven by the replayed event's own time) is its own change.
- [ ] **Statuses.** Spec header still says `draft — awaiting user review`; the plan's layer checkboxes are unticked.

---

## Live trade-ops (plan [2026-09-22](plans/2026-09-22-live-trade-ops-plan.md), spec [2026-09-22](specs/2026-09-22-live-trade-ops-l0-test-design.md))

Carried over verbatim from that plan's Task 7.6. The branch itself is merged into `layer-implementation` (`125a7f3`); which of its Tasks 7.2–7.5 human-gated runs completed is not recorded — their boxes are unticked.

- [ ] Tick L0 Stage 1 checkboxes named in the spec header in [specs/layers/L0-exchange-adapter.md](specs/layers/L0-exchange-adapter.md), with run dates.
- [ ] Spec status → `implemented 2026-…`; that plan's status line.
- [ ] `TECH_DEBT.md` §7 (`order_event.order_id` bigint) stays open — not fixed there.
