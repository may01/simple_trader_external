# extdone_stop_move — move the stop to entry ∓ Y·ATR(1 min) once the entry-side extension is done

Date: 2026-10-20. Status: **done — partial** (see [results](results/extdone_stop_move_results.md)); not a live change, tf-15-only toggle candidate. Base: read-only replay over the paper executor's recorded data
(no code-repo branch; the replay script lives beside the run report, as the sibling replays of 2026-10-20 did).

# Goal

Measure how the paper executor's P&L changes if, while a CB zone position is open, the 15- or 60-min
`extdone` state of the *entry* bound (the bound opposite to the target) moves the stop to
`entry − Y·ATR` (long) / `entry + Y·ATR` (short), Y ∈ [0, 5], and how the effect differs by the
position's own zone tf (15 / 60 / 240).

# Rule under test

`{tf}_extdone_high = 1` ⇔ the forming tf candle's running high has pulled away from the 1-min close by
≥ d(progress) ATRs (the up-extension is done); `_low` mirrored. A long opens at the low bound with the
`cbnc_high` target, so its entry-side state is `{tf}_extdone_low`; a short's is `{tf}_extdone_high`.
The executor already receives both names from main/ (`indicators` table, 30 s cadence, 300 s validity).

While a position is open: if the trigger tf's entry-side extdone is 1, set
`stop = entry ∓ Y·ATR1` where `ATR1 = 1_atr_14_ma_5` (Wilder ATR-14 on closed 1-min bars, SMA-5 — the
column main/'s extdone kernel divides by), rebuilt from the recorded trades. Primary form: the stop only
ever tightens (a looser candidate leaves the candle stop in place); applied once per position.

# Locked decisions (2026-10-20, assumptions — user not available mid-run)

| # | Question | Decision |
|---|---|---|
| 1 | Which extdone side | entry bound = opposite to the target: long → `extdone_low`, short → `extdone_high` |
| 2 | Trigger tf | three variants: fixed 15, fixed 60, the position's own tf (240 positions use 240) |
| 3 | Y grid | 0, 0.5, 1, 1.5, 2, 3, 4, 5 |
| 4 | ATR | `1_atr_14_ma_5` from 1-min bars built from trades, value of the last closed bar |
| 5 | Already-done at open | primary (`state`): apply on the first trade after open; ablation (`transition`): only if the state flips 0 → 1 after open |
| 6 | Loosening | primary: tighten only; ablation (`replace`): overwrite the candle stop regardless |
| 7 | Everything else | today's live rules: entry check, 15-min candle stop, 0.2 % placeholder, trend-flip target exit, sizing `min(100/dist, free·0.5/entry)`, paper = no fees (0.1 %/side sensitivity column) |

# Steps

1. Export `trade`, `indicators` (CB + extdone names), `signal_log`, `position_log` from `cbov-check` postgres.
2. Extend the ma-window replay harness: ATR1 series, stop move in the advisor loop, variant grid.
3. Reproduction gate: live variant fires vs the recorded `CbZoneEntry` rows (expect ~145/152, misses = restarts).
4. Grid: trigger tf × Y × mode; summary, per position tf, paired Δ vs live on matched positions, bootstrap.
5. Report.

# Data

`cbov-check` paper stack postgres: `trade` 2026-10-16 22:29Z → 2026-10-20 21:40Z (671 k trades), `indicators`
extdone names from 10-16 22:34Z, `signal_log` CbZoneEntry 153 rows from 10-18 11:41Z, `position_log` 1 344 rows.
