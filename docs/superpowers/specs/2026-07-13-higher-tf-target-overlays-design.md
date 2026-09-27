# Higher-TF target/stop-loss overlays on finer charts — design

**Date:** 2026-07-13
**Base branch:** `experimental_imp_2`
**Work branch:** `viewer-higher-tf-target-overlays` (off base; ff-merge back)
**Status:** approved, pre-implementation

## Goal

On charts finer than 15 minutes (tf = 1 and 5), draw the existing
`tgt_long` / `sl_long` / `tgt_short` / `sl_short` target/stop-loss lines that
are computed for the higher timeframes (15, 60, 240, 1440), so a trader
watching 1-minute price action can see where the higher-timeframe targets and
stop-losses sit.

The four target fields have `applies_to: [15, 60, 240, 1440]` — they are never
computed natively for tf 1 or 5. This feature does **not** add native 1m/5m
targets; it overlays the already-materialised higher-TF values onto the finer
chart.

## Non-goals

- **No data re-prep, no new columns, no config change.** The
  `{H}_tgt_long` etc. columns already exist for `H ∈ {15,60,240,1440}` on
  every 1-minute row of the stored wide df (`df_with_indicators.pkl`).
- **No native 1m/5m target compute.** That would require adding `1`/`5` to
  `applies_to` plus a full data re-prep, and would produce a different,
  noisier line. Explicitly rejected in brainstorming.
- **No change to charts at tf ≥ 15.** Their native always-on target/SL
  behaviour is preserved byte-for-byte.

## Verified data facts

Inspected `.../simple_trader_vol/train/2w_link_usdt/df_with_indicators.pkl`:

- Columns present: `15_tgt_long`, `15_sl_long`, `15_tgt_short`, `15_sl_short`
  and the same four for `60_`, `240_`, `1440_`.
- Each is a **flat step**: constant across all N one-minute rows of its
  source-TF candle, changing only at the candle boundary (e.g. `15_tgt_long`
  holds one value across `01:45…01:59`, steps at `02:00`, holds to `02:14`).
- Values are known at candle open (fields use `shift(1)` of the prior *closed*
  candle) — no lookahead introduced by drawing them on the finer chart.

Consequence: plotting `{H}_tgt_long` at 1-minute granularity renders a clean
horizontal step line. No intra-candle wiggle, no step-interpolation mode
needed.

## Design

Single-locus viewer change. Files touched:
`frontend/data_viewer.py`, `frontend/chart_renderer.py`.

### 1. Source-TF-pinned overlay groups

New class constant on `DataViewer`, distinct from `_OVERLAY_GROUPS` (which draw
at the *chart* tf via `f"{tf}_{name}"`):

```python
# base name → same four target fields; value = the FIXED source tf they draw from
_TARGET_TF_GROUPS = {
    "tgtsl_15m": 15,
    "tgtsl_60m": 60,
    "tgtsl_240m": 240,
    "tgtsl_1440m": 1440,
}
```

Each group draws the four `_TARGET_OVERLAYS` fields sourced from its pinned tf.

### 2. Gate: sub-15 charts only

The groups draw **only when the chart tf is finer than the smallest target tf
(15)** — i.e. `tf in {1, 5}`. On charts with tf ≥ 15 the groups are ignored
entirely, so native always-on target/SL (the existing unconditional
`_TARGET_OVERLAYS` draw) is the only target rendering there — unchanged.

The gate lives in `_draw_price_overlays`, keyed on the chart tf argument. The
history dashboard renders one chart per selected TF with a shared overlay
checklist; the gate makes a checked `tgtsl_60m` group appear on the 1m/5m
charts and no-op on the 15m/60m/… charts.

### 3. Toggleable

- `available_overlays()` — extended to append each `tgtsl_*` group whose
  backing columns exist in the wide df (any of the four fields for that source
  tf). In real data all four appear.
- `default_overlays()` — `tgtsl_15m` checked on first load; `tgtsl_60m`,
  `tgtsl_240m`, `tgtsl_1440m` added to the default-off set. So a freshly opened
  1-minute chart shows the 15m target/SL lines out of the box (the original
  ask); the coarser TFs are one click away.
- The existing shared `dcc.Checklist(id="overlays")` in
  `frontend/history_dashboard.py` renders these automatically from
  `available_overlays()` / `default_overlays()` — no dashboard change required.

### 4. Labels and styling

- **Label:** `f"{name}·{H}m"` — e.g. `tgt_long·15m`, `sl_short·240m`. The
  native always-on overlays keep their bare labels (`tgt_long`), so existing
  tf=15 tests that assert exact bare labels are unaffected.
- **Colour:** reuse the four semantic `_OVERLAY_COLORS` entries
  (`tgt_long` darkgreen, `sl_long` darkred, `tgt_short` mediumseagreen,
  `sl_short` indianred) — direction/side reads by colour.
- **Source-TF disambiguation:** by line **dash + width**, e.g.

  ```python
  _TARGET_TF_STYLE = {  # source tf → (dash, width)
      15:   (None,      2.0),   # nearest: solid, bold
      60:   ("dash",    1.6),
      240:  ("dot",     1.3),
      1440: ("dashdot", 1.0),   # farthest: faint, thin
  }
  ```

  On a 1-minute chart the 15m lines read strongest, 1440m faintest.
- **Draw order:** descending source tf (1440 first … 15 last) so the nearest
  TF sits on top.

### 5. Renderer extension

`ChartRenderer.draw_line` currently accepts only `color`. Extend with optional
keyword args, backward-compatible (defaults reproduce current output):

```python
def draw_line(self, fig, subplot, times, values, label, color="blue",
              dash=None, width=None) -> None:
    line = {"color": color}
    if dash is not None:
        line["dash"] = dash
    if width is not None:
        line["width"] = width
    fig.add_trace(go.Scatter(..., line=line), row=row, col=1)
```

### 6. `_draw_price_overlays` changes

After the existing toggleable-group + always-on `_TARGET_OVERLAYS` block
(unchanged), append:

```python
if tf < min(self._TARGET_TF_GROUPS.values()):   # tf in {1, 5}
    for group, src_tf in sorted(
        self._TARGET_TF_GROUPS.items(), key=lambda kv: -kv[1]  # 1440 → 15
    ):
        if overlays is not None and group not in overlays:
            continue
        dash, width = self._TARGET_TF_STYLE[src_tf]
        for name in self._TARGET_OVERLAYS:
            col = f"{src_tf}_{name}"
            if col not in df_slice.columns:
                continue
            self.renderer.draw_line(
                fig, "price", list(df_slice.index), list(df_slice[col]),
                label=f"{name}·{src_tf}m",
                color=self._OVERLAY_COLORS.get(name, "gray"),
                dash=dash, width=width,
            )
```

`overlays is None` (draw-all) includes every target-tf group; `overlays=[]`
draws none of them (native always-on still draws). Same contract as the
existing overlay groups.

## Data flow

Unchanged wide df → `DataViewer.build_window_figure(tf=1, overlays=[...])`
→ `_dedup_tf_rows(window, 1)` keeps every 1-minute row (columns
`{H}_tgt_long` already flat-per-row) → `_draw_price_overlays` draws native
(none exist at tf=1) then the gated higher-TF step lines.

## Testing

New test module (e.g. `tests/test_higher_tf_target_overlays.py`):

- **tf=1 fixture** with `1_*` OHLC plus `15_*` and `60_*` target columns:
  asserts both `tgt_long·15m` and `tgt_long·60m` (and the other three each) are
  drawn on the price axis; `240`/`1440` absent when their columns are absent
  (skip-if-absent).
- **Toggle filter:** `overlays=["tgtsl_15m"]` draws only the 15m set;
  `tgtsl_60m` labels absent.
- **Gate:** same fixture rendered at tf=15 draws no `·{H}m`-suffixed labels
  (higher-TF groups no-op at tf ≥ 15).
- **Styling:** 15m lines solid/bold, 60m dashed/thinner (assert `line.dash` /
  `line.width` on the traces).
- **Availability/defaults:** `available_overlays()` includes the `tgtsl_*`
  groups when columns exist; `default_overlays()` includes `tgtsl_15m`, excludes
  the coarser three.

Existing suites stay green:
`tests/test_phase12_task11_target_sl_overlays.py` and
`tests/test_phase12_task15_overlay_selection.py` use tf=15 fixtures containing
only `15_*` columns → higher-TF groups skip-if-absent and the gate is off, so
labels and colours are byte-identical to today.

## Edge cases

- **5-minute chart:** `tf=5 < 15` → same behaviour as the 1-minute chart.
- **Missing coarser columns** (short datasets without a 1440 candle): skip-if-
  absent per field; the group silently draws nothing.
- **Shared checklist noise:** the `tgtsl_240m` / `tgtsl_1440m` checkboxes appear
  in the shared control even while only a ≥15m chart is displayed; harmless
  (they no-op via the gate). Accepted — keeps the control TF-independent like
  the existing overlay checklist.

## Layers touched

Presentation only (`frontend/`). No data, indicator, NN, or config layer
changes. No Docker/service change beyond redeploying the viewer.
