# Tech Debt

Known unresolved issues, to be picked up as future tasks. One section per item:
what's wrong, why it was deferred, what resolving it looks like.

## 1. Target fields (`tgt_long`, `sl_long`, `tgt_short`, `sl_short`) — semantics unresolved

**Status:** open (flagged 2026-06-12)
**Where:** `indicators/library/targets.py`, group `targets`, TFs [15, 60, 240, 1440]

Target/stop levels are derived from prev-candle `{src}_diff_prc_rm_20` ±
`*_std_above/_std_below` band arithmetic. Two concerns:

- The sided-std fields were redefined in phase-13 task-03 (now: std of the
  window's diff_prc values above/below the window mean, previously an rm ± std
  band). The tgt/sl formulas were patched to follow (`900bcee`), but whether
  "rm − sided-std" / "rm + sided-std" is still the *intended* target geometry
  has not been validated against strategy results.
- These are forward-usage labels computed inside the wide df alongside real
  indicators; nothing structurally prevents a strategy/NN feature set from
  consuming them as if they were ordinary indicators (lookahead risk by
  misuse, not by computation).

**Resolution:** define target semantics explicitly (spec), validate against
backtest/NN-label usage, and consider separating label columns from indicator
columns (naming convention or separate frame).

## 2. `ZB` / `ZS` zone fields — placeholder thresholds, effectively constant

**Status:** open (flagged 2026-06-12)
**Where:** `indicators/library/targets.py` (`ZBField`, `ZSField`), group `targets`

Both read `zb_threshold` / `zs_threshold` from `diff_stats.pkl`, but
`DataAttributes._compute_diff_stats` only writes `mean_diff` / `std_diff` —
the thresholds are never produced. `stats.get(..., 0.0)` then makes:

- `ZB = (close > 0).astype(int)` → always 1
- `ZS = (close < 0).astype(int)` → always 0

i.e. both columns are constants carrying no signal.

**Resolution:** either define and compute real `zb_threshold` / `zs_threshold`
in `_compute_diff_stats` (and document the intended zone semantics), or drop
ZB/ZS from the config until the zone model exists.
