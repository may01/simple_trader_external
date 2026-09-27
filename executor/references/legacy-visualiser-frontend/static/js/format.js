// Shared formatting/parsing helpers for the Overview and Pair pages.
//
// Wire-shape notes this file leans on (see crates/visualizer_server/src/dto.rs
// and specs/2026-09-07-executor-visualiser-design.md -- read those, not this
// comment, if in doubt):
//   - `Decimal` fields (price/qty/size/etc.) serialize as JSON *strings*,
//     never raw numbers -- always go through `num()` before doing math or
//     feeding a value to the chart library.
//   - `Pair`/`Ts`/`OrderId`/`TradeId` are plain newtypes with no
//     `#[serde(transparent)]` needed -- serde's default newtype-struct
//     encoding already makes them a bare string/number on the wire (`Pair`
//     -> string, the rest -> number).
//   - `PositionStatus` is `"Flat"` (a bare string) or `{"Open": {...}}` (an
//     externally-tagged single-field variant) -- never a third shape.
//   - `ReconciliationOutcome` is `"NoDiscrepancy"` (bare string) or one of
//     four `{"VariantName": {...}}` shapes -- only the bare-string case
//     counts as healthy.
//   - `PositionStateEventDto` variants are all externally tagged
//     (`{"Opened": {...}}` etc.) -- there is no bare-string unit variant in
//     this particular enum (every variant carries fields).

/** Parse a wire `Decimal` (a JSON string) into a JS number for math/charting.
 * Returns `null` (never `NaN`) for anything unparseable so callers can
 * decide how to degrade rather than silently propagating `NaN`. */
function num(decimalString) {
  if (decimalString === null || decimalString === undefined) return null;
  const n = Number(decimalString);
  return Number.isFinite(n) ? n : null;
}

/** Escapes text for safe insertion via `innerHTML`. */
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = String(str);
  return div.innerHTML;
}

/** `PositionStatusDto` -> `true` iff it's the bare `"Flat"` string. */
function isPositionFlat(status) {
  return status === "Flat";
}

/** `PositionStatusDto` -> the `OpenPositionDto` payload, or `null` if flat. */
function openPositionOf(status) {
  if (status && typeof status === "object" && Object.prototype.hasOwnProperty.call(status, "Open")) {
    return status.Open;
  }
  return null;
}

/** `PositionStatusDto` -> short human text, e.g. "Flat" / "Open (Buy)". */
function positionStatusText(status) {
  const open = openPositionOf(status);
  if (!open) return "Flat";
  return `Open (${open.side})`;
}

/** `Option<ReconciliationReportDto>` -> `true` (healthy) / `false`
 * (discrepancy) / `null` (never reconciled -- unknown, not a red flag). */
function reconciliationHealthy(reconciliation) {
  if (!reconciliation || !Array.isArray(reconciliation.entries)) return null;
  if (reconciliation.entries.length === 0) return true;
  return reconciliation.entries.every((e) => e.outcome === "NoDiscrepancy");
}

/** Renders a health flag's `{class, text}` pair for a tri-state
 * `reconciliationHealthy()` result. */
function reconciliationFlag(healthy) {
  // A pill like the other two states, not bare grey text: "never
  // reconciled" is a status, and rendering it as washed-out prose made
  // it read like a rendering failure next to the OK/DISCREPANCY badges.
  if (healthy === null) return { cls: "flag flag-unknown", text: "NOT RECONCILED" };
  return healthy ? { cls: "flag flag-ok", text: "OK" } : { cls: "flag flag-bad", text: "DISCREPANCY" };
}

/** One-line human summary of a `PositionStateEventDto` (externally tagged:
 * exactly one own-property key naming the variant). */
function eventSummary(eventDto) {
  const key = Object.keys(eventDto)[0];
  const body = eventDto[key] || {};
  switch (key) {
    case "NotPlaced":
      return `NotPlaced (${body.reason})`;
    case "Opened":
      return `Opened ${body.side} size=${body.size} @ ${body.open_price} (SL ${body.stop_loss_price}, target ${body.close_price})`;
    case "Closed":
      return `Closed @ ${body.close_price}`;
    case "StoppedOut":
      return `StoppedOut @ ${body.stop_price}`;
    case "AlreadyClosed":
      return "AlreadyClosed";
    case "StopLossMoved":
      return `StopLossMoved -> ${body.new_stop_loss_price}`;
    default:
      return key || "(unknown event)";
  }
}
