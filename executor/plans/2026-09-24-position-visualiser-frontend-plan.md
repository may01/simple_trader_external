# Position Management 8/9 — Visualiser frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan layer-by-layer. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show an operator what the position is, what it cost, what is resting on the exchange right now, and what the system is allowed to do — as records where the data is records, and as lines only where the data is a live price.

**Spec:** [`2026-09-22-position-management-design.md`](../specs/2026-09-22-position-management-design.md) §8.2, §8.3, audit rows D1, D5–D10.

**Scope:** `crates/visualizer_server/static/` — `pair.js`, `chart.js`, `pair.html`, `css/style.css`, `js/api.js`. **No** Rust.

**Depends on:** plan 7/9 merged, and its committed **route fixtures** — code against those, not against a reading of the spec.

**Branch:** `position-visualiser-frontend`, cut from `position-management`, merged back into it.

## Readiness review

Verified against the code on `layer-implementation` @ `ff2938d` and `live-trade-ops` @ `e45dc05` (2026-09-25).

🟢 **green** — exists in the system, small update · 🟡 **yellow** — in the spec, small code change · 🟠 **orange** — in the spec, large code change · 🔴 **red** — in neither code nor spec

### 🟢 Green

| Item | Where it is today | Change |
|---|---|---|
| `renderPositionSummary`, `openPositionOf`, `positionStatusText` | `static/js/pair.js` | field list extended |
| `setPositionLines` + `series.createPriceLine` | `static/js/chart.js:276` | the exact API `setOpenOrderLines` reuses |
| `setDepthChartWalls` + the `wallLines` chart.js plugin | `static/js/chart.js:586,532` | the exact mechanism the depth-chart order markers reuse |
| `renderPositionEventsPanel`, the Decisions/Signals panels, `refreshTradeActivity`, `tradeActivityRange` | `static/js/pair.js` | the pattern every new panel follows |
| `setTradeMarkers`, `setSignalMarkers`, one-line-series-per-kind | `static/js/chart.js` | **unchanged** — no historical layer is added |
| Vendored `lightweight-charts` and `chart.js` | `static/vendor/` | no new library |

### 🟡 Yellow

Position-panel fields and the unprotected banner · the three record panels and the totals footer · the three operator banners · swapping the position panel's poll for `/ws`.

### 🟠 Orange

| Item | Why it is large |
|---|---|
| `setOpenOrderLines` + the depth-chart channel | two chart mechanisms, a handle map with correct removal, a separate styled channel from walls, and dashed-while-unacked |
| `/ws` for the position panel | the record panels keep polling; only the position panel switches, and it must recover from a dropped socket without a reload |

### 🔴 Red

| Item | Status |
|---|---|
| **There is no test harness for the static frontend in this repository** | **Real gap.** `static/js/` has no test runner, no fixtures, no CI step — verified. Every other plan in this set gates on `docker compose run --build --rm test`; this one cannot. It therefore uses manual checklists, which is honest but weaker than everything around it, and it is the plan whose output an operator stares at during a live run. Decide: accept checklists for this plan, or add a minimal harness (jsdom + the plan-7/9 route fixtures) as a first task. **Not a spec amendment — a scope decision for this plan.** |
| The legend text distinguishing intent lines from resting-order lines | §8.3 requires the distinction be stated rather than inferred, but not its wording; implementation detail |

---

## Global Constraints

- **History goes in panels of records; only currently resting orders are drawn** (§8.2). No qty-scaled fill markers, no per-order history markers, no liquidation line, no equity-curve canvas. The existing position overlay (entry/stop/target lines, position-event markers) is unchanged.
- **Panels follow the existing pattern** — `renderPositionEventsPanel` / Decisions / Signals: a `<table>` in a bordered section, newest first, refreshed on the `refreshTradeActivity` tick, with an explicit empty state. A new panel that invents its own idiom is a defect.
- **New chart series follow `chart.js`'s existing one-line-series-per-kind pattern**, for the reason its own comment gives: lightweight-charts v4 markers cannot be placed at a price.
- **No new vendored library.** `lightweight-charts` and `chart.js` are already there; anything else is out of scope.
- **Commit only after explicit user confirmation.**

---

## Docker Entry Points

```bash
docker compose up -d --build postgres executor visualizer
# then open the pair page and drive a paper position through the executor
docker compose logs -f visualizer
```

Verified: [ ] the pair page loads unchanged against a seeded database before Layer 1 (baseline — a regression here must be attributable).

---

## Layer 1: Position panel (D6)

### Task 1.1: Extend `renderPositionSummary`

**Files:** `static/js/pair.js`, `static/pair.html`, `static/css/style.css`.

**Interface:** a labelled field list (not a table): status, side, net size / target size, avg entry, mark, unrealized P&L (coloured), realized P&L once closing, fees per asset, R-multiple `(mark − avg_entry) / (avg_entry − stop)`, liquidation price and leverage when present, time in position, `settlement_complete`.

**Tests (manual against a seeded database, recorded as a checklist — this is static JS with no harness in this repo):**
- [ ] A flat pair renders the empty state, not zeros. A zero average entry price rendered as `0.00` is indistinguishable from a real one.
- [ ] An `opening` position renders with `avg_entry` blank and `net_size` growing, not `0`.
- [ ] Unrealized P&L is coloured by sign and flips correctly for a short.
- [ ] R-multiple is absent (not `Infinity`, not `NaN`) when `avg_entry == stop`.
- [ ] `settlement_complete: false` is visibly marked — a P&L figure without fees is provisional and must not read as final (§3.5).
- [ ] **Unprotected-position banner**: the `Stop` role's order in `Rejected` renders a red banner above the panel. §8.2 calls this "the one thing on the page an operator must never have to look for" — check it renders before anything else and without scrolling.

**Layer 1 gate:** the panel renders every field correctly against the plan-7/9 fixtures. Commit: `feat(spa): position panel with size, average entry, P&L, fees and risk`.

---

## Layer 2: Record panels (D7, D8)

### Task 2.1: Orders panel

**Interface:** columns — time, role (entry/exit/stop), side, kind, price, stop price, qty, filled qty, status, reject reason, `client_order_id`. One row per `exchange_order`.

**Checklist:**
- [ ] A refused order is visible **as itself**, with its reject reason, rather than inferred from a gap.
- [ ] An orphaned order (no live position) appears.
- [ ] Empty state when the window holds no orders.

### Task 2.2: Fills panel

**Interface:** time, side, price, qty, quote qty, fee, fee asset, maker/taker, realized P&L, trade id. Expandable under its order, or filtered by the selected position.

**Checklist:**
- [ ] Multi-fill orders show every fill; the panel's own total matches the order's `filled_qty`.
- [ ] A fee in a third asset (BNB) renders its own asset rather than being coerced to quote — §4.5 of the live-trade-ops design has `fee_in_quote: None` for exactly this case.

### Task 2.3: Closed positions panel

**Interface:** opened, closed, duration, side, size, avg entry, avg exit, realized P&L, fees, close reason, `decision_id` / `signal_id` linking to the existing Decisions and Signals panels. **Footer row totals realized P&L and fees over the window.**

**Checklist:**
- [ ] The footer total is what replaced the equity curve — confirm it reads clearly and is not lost at the bottom of a long table.
- [ ] `decision_id` / `signal_id` links resolve to rows the other panels already render.
- [ ] A position closed by each `close_reason` renders that reason legibly.

**Layer 2 gate:** all three panels render against fixtures. Commit: `feat(spa): orders, fills and closed-positions panels`.

---

## Layer 3: Open-order lines (§8.3)

The one chart change in the whole spec.

### Task 3.1: Candle chart

**Files:** `static/js/chart.js`.

**Interface:** `setOpenOrderLines(state, orders)` using `state.series.createPriceLine` — the same API `setPositionLines` (`chart.js:276`) already uses — keeping its own handle map so lines are removed when an order fills or cancels.

**Checklist:**
- [ ] A resting stop draws a line at its trigger price; a resting limit at its limit price; a market order draws nothing.
- [ ] The line disappears within one refresh of the order filling or cancelling. A stale line claiming protection that no longer exists is worse than no line.
- [ ] `intent` / `submitted_unknown` draws **dashed** — believed sent, not confirmed resting (§8.3).
- [ ] Title reads `{role} {side} {qty}`, one colour per role.
- [ ] Against the existing intent lines: a target line with no order under it is expected (D7 — the target never rests); a stop line with no order under it is an unprotected position. The **legend states which is which** rather than leaving it to be inferred.

### Task 3.2: Order book chart

**Interface:** the existing `wallLines` chart.js plugin and `setDepthChartWalls` (`chart.js:586`) mechanism — a price drawn onto the depth axis, not a chart.js dataset.

**Checklist:**
- [ ] An open order appears at its price on the depth chart.
- [ ] It is on a **separate styled channel** from walls — "my order" and "somebody's wall" are never the same colour.
- [ ] Removing the last open order leaves the wall rendering untouched.

**Layer 3 gate:** both charts show a live resting order against a running executor. Commit: `feat(spa): draw resting orders on the candle and depth charts`.

---

## Layer 4: Live updates and operator context

### Task 4.1: `/ws` replaces the position poll (D9)

**Checklist:**
- [ ] The position panel updates from `/ws` without the poll.
- [ ] The record panels keep their existing polled refresh — they are history and do not need push.
- [ ] `pair.js`'s header comment declaring `/ws` candle/trade/book-only is **updated**, not worked around.
- [ ] A dropped socket reconnects and the panel recovers without a page reload.

### Task 4.2: Operator banners (D10)

**Checklist:**
- [ ] `EXECUTION_MODE=no_trade` renders a persistent banner. "Why did nothing trade" must be answerable from the page (§8.2).
- [ ] `MAIN_ORDER_PLACEMENT=enabled` renders a **warning** banner — two processes able to place orders is the hazard plan 5/9 exists to remove.
- [ ] An unresolved `reconciliation_log` discrepancy renders a banner.

**Layer 4 gate:** all banners render from `/api/status` and the position panel updates live. Commit: `feat(spa): live position over /ws, operator banners`.

---

## Done when

- [ ] Every layer gate green, in order, against a running stack.
- [ ] Spec acceptance criteria satisfied here: "the visualiser's Position panel shows size, avg entry, unrealized and realized P&L, fees, R-multiple, liquidation price and the unprotected-position banner; the Orders, Fills and Closed-positions panels render … and the Closed-positions footer totals P&L and fees"; "open orders are drawn on both charts … dashed while `intent`/`submitted_unknown`"; "an orphaned order … is still drawn"; "no *historical* chart layer was added".
- [ ] `position-visualiser-frontend` merged into `position-management` (after user confirmation).
