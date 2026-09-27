# Step 7 — L5 state_store (plan)

Part of the [layer implementation sequence](2026-09-05-layer-implementation-sequence.md)
(parallel with [06-L4-mq-gateway](06-L4-mq-gateway.md) — both depend
only on L3).
Spec: [L5-state-store](../specs/layers/L5-state-store.md).

## What to implement

- Persistence of every position/order state change execution emits,
  for crash recovery.
- An append-only decision log: every inbound message from main/
  (decisions and force actions alike), including ones that lapsed,
  were rejected, or never resulted in a placed order — a record for
  later inspection, not part of reconciliation.
- Boot-time reconciliation of persisted state against the exchange's
  actual account/position/order state — the exchange always wins
  conflicts, since fills or liquidations may have happened while the
  process was down.

## Acceptance criteria (high level)

**Status:** implemented and committed on branch `layer-implementation`
(`crates/state_store`, commit `adeac3f`). 18 tests, workspace total
174, clippy clean, Docker-verified. `reconcile` actually persists
corrections (exchange wins is an action, not just a report), covering
all four discrepancy kinds against fixtures. `DecisionRecord` reuses
`execution::{TradeDecision, ForceAction}` directly (both still
provisional pending L4).

Not covered: the last high-level bullet ("once L0 is real...") — gated
on L0 testnet credentials, same open item as every other layer's own
docs.

**Update (2026-09-11, branch `postgres-market-data-store`):**
`state_store` moved from sled to PostgreSQL. `persist`, `load_all`,
`reconcile`, `log_decision` and `read_decision_log` are `async fn`,
synchronously durable (commit before returning — no batching, no
queue, the deliberate opposite of L1's batched writer task, since
these fire once per decision and exist to survive a crash).
`last_reconciliation` is unaffected — stays an in-memory,
process-lifetime cache, never persisted, exactly as before the backend
change. See
[L5-state-store.md](../specs/layers/L5-state-store.md)'s amended spec
for the full picture, including an implementation-status note: the
spec's `log_event`/`read_event_log` (`event_log` table additions, dated
2026-09-07) and the `current_levels`/`current_command`/
`analysis_current`/`analysis_log`/`read_wall_log` additions (dated
2026-09-08/09) are **not** implemented on this branch — only
`position_state` and `decision_log` exist in code
(`crates/state_store/src/{lib,pg}.rs`). The `event_log` table itself is
already present in `migrations/0001_init.sql` — created but unused —
so the eventual merge of the unmerged `state-store-expansion` branch
needs no new migration for that one table, only the Rust methods.

- [ ] Reconciliation logic is proven against fixture mismatches:
      missing position, extra position, quantity drift, and a
      locally-open order that actually filled or was cancelled on
      the exchange — exchange wins every case.
- [ ] Every decision and force-action variant is logged and read back
      unchanged, including ones that resulted in nothing happening —
      the log never silently drops an entry just because no order
      was placed.
- [ ] Corrupt or missing local state on boot is never trusted alone —
      reconciliation always runs before execution starts accepting
      new decisions.
- [ ] Once L0 is real: reconciliation against L0's actual
      `get_account_state`/`get_order` output (not a stub) recovers
      correctly from a simulated real-world mismatch.
