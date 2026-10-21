# Replay 2026-10-20 — stop to entry ∓ Y·ATR(1 min) once the entry-side extension is done

Question (user): how does the profit change if, after the 15- or 60-min `extdone` of the entry bound
(the bound opposite to the target) turns on, the stop moves to `entry ∓ Y·ATR(1 min)`, Y ∈ [0, 5]; and how
does it work per position tf.

Script `2026-10-20-extdone-stop-move-replay.py`, raw output `…-output.txt`. Same harness as the
ma-window replay (fires re-derived from the stored `indicators` snapshots + trades; live entry rules,
15-min candle stop, 0.2 % placeholder, trend-flip target exit, sizing `min(100/dist, free·0.5/entry)`,
paper = no fees). Window 2026-10-18 11:41Z → 10-20 21:47Z (58.1 h, 451 k trades).

## 1. Rule and its inputs

- Entry-side state: long → `{trig}_extdone_low`, short → `{trig}_extdone_high` (main/ kernel:
  `extdone_high = ({tf}_high − 1_close)/1_atr_14_ma_5 ≥ d(progress)`, the up-run is done; low mirrored).
  Both names are already in the executor's `indicators` table (30 s cadence, 300 s validity).
- Trigger tf: fixed 15, fixed 60, or the position's own zone tf (`own`).
- ATR1 = `1_atr_14_ma_5` rebuilt from the trades (Wilder ATR-14 on closed 1-min bars, SMA-5): median
  0.0096 (≈ 8 bp of 12.02), p10–p90 0.0061–0.0168. Median 1-min range 0.0080.
- Candidate stop `entry − Y·ATR1` (long) / `entry + Y·ATR1` (short), decided once per position on the
  first reading with the state on; **primary = tighten only** (a looser candidate leaves the candle stop),
  **state** mode (already-on at open counts). Ablations: `trans` (needs a 0 → 1 flip while open),
  `repl` (overwrite the candle stop even when looser).

Reproduction gate (live variant): 146/153 recorded `CbZoneEntry` fires matched (|dt| median 0 s, same
rule 145, same class 145, same zone 146); 7 misses = first fires after executor restarts, 2 extras
(the same restarts); recorded slope reproduced to 2.7e-8 median. Live replay: 136 positions, net +2 447.

## 2. Where the candle stop sits

The live candle stop is a median 2–2.5 ATR1 from the entry, so with tighten-only the rule is a no-op for
Y ≥ 3 (0–4 positions touched, Δ ≤ +33) and the real sweep is Y ∈ [0, 2].

| trigger | positions with the state on while open | median minutes to the move | never on while open |
|---|---|---|---|
| 15 | 88 / 140 (9 already on at open) | 3.5 | 52 |
| 60 | 26 / 136 (7 at open) | 4.3 | 110 |
| own | 66 / 138 (6 at open) | 3.5 | 72 (60-min state rarely turns on inside an 8-min tf-60 hold) |

## 3. Whole system (state, tighten only)

| trig \ Y | 0 | 0.5 | 1 | 1.5 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|---|---|
| 15 | +2532 | +2319 | +2288 | +2390 | +2512 | +2480 | +2459 | +2447 |
| 60 | +2275 | +2230 | +2217 | +2556 | +2498 | +2447 | +2447 | +2447 |
| own | +2615 | +2577 | +2678 | +2695 | +2600 | +2480 | +2459 | +2447 |

live = +2447. Paired Δ vs live (positions matched by side + open time, bootstrap 90 % CI):

| variant | moved | moved → stop-outs / targets | Δ net | Δ 90 % CI | P(Δ<0) |
|---|---|---|---|---|---|
| t15 Y0 | 88 | 42 / 37 | +0 | [−964, +942] | 0.49 |
| t15 Y1 | 88 | 30 / 43 | −141 | [−868, +552] | 0.60 |
| t15 Y1.5 | 79 | 22 / 42 | +182 | [−250, +550] | 0.21 |
| t15 Y2 | 48 | 12 / 26 | +64 | [−209, +299] | 0.30 |
| t60 Y0 | 26 | 10 / 14 | −173 | [−808, +421] | 0.68 |
| t60 Y1 | 25 | 6 / 16 | −230 | [−840, +241] | 0.74 |
| t60 Y1.5 | 19 | 3 / 14 | +108 | [+20, +219] | 0.00 |
| own Y0 | 66 | 27 / 35 | +109 | [−715, +871] | 0.40 |
| own Y1 | 66 | 18 / 41 | +172 | [−380, +668] | 0.28 |
| own Y1.5 | 59 | 13 / 40 | +351 | [+176, +548] | 0.00 |
| own Y2 | 38 | 9 / 24 | +153 | [+57, +280] | 0.00 |

Mechanism at Y = 0 (breakeven stop, trig 15): 42 positions exit at ≈ 0 instead of the candle stop
(−82 mean), but 10 targets (+107 mean) and 9 reversals (+141) are no longer reached → net +85, i.e.
nothing. Y 0.5–1 is the worst spot (stop sits inside the noise, still forfeits the winners). At Y 1.5–2
the moved stop is only ~0.5 ATR nearer than the candle stop, so it changes 10–20 exits for ±100.

The Δ counts ~70 non-moved positions with |Δ| < 2 USDT from balance-dependent sizing; the effect sits
in the moved ones. Fee sensitivity: −10 k at 0.1 %/side for every row (unchanged conclusion).

## 4. Per position tf (paired Δ on matched positions, state / tighten)

| trig \ Y | tf 15 (101 pos, live +1675) | tf 60 (26, live +106) | tf 240 (9, live +667) |
|---|---|---|---|
| 15, Y 0 / 0.5 / 1 / 1.5 / 2 / 3 | +106 / +67 / +168 / +348 / +152 / +32 | −71 / −195 / −220 / −192 / −88 / 0 | −34 / −30 / −88 / +26 / +1 / 0 |
| 60, Y 0 / 0.5 / 1 / 1.5 / 2 | −171 / −216 / −228 / +108 / +51 | 0 / 0 / 0 / 0 / 0 | −2 / −1 / −1 / 0 / 0 |
| own, Y 0 / 0.5 / 1 / 1.5 / 2 / 3 | +107 / +70 / +171 / +350 / +152 / +32 | 0 / 0 / 0 / 0 / 0 / 0 | +1 / 0 / +1 / +1 / 0 / 0 |

- **tf-15 positions, 15-min state**: positive at every Y in 0–3 (+67…+350 on +1 675), peak Y 1.5
  (14 moved stop-outs at −60 instead of candle stop-outs at −80; targets unchanged 49). Consistent sign
  across the grid but a single-digit-percent effect on 101 trades; the halves split +830 / +1 560 vs live
  +797 / +1 650 (first half better, second half worse) — the Y 1.5 CI that excludes zero is one cell of
  eight, picked after the fact.
- **tf-60 positions**: the 15-min state is too early for a 60-min zone trade — every Y ≤ 2 loses
  (−71…−220 on +106; e.g. Y 1.5: 6 moved stop-outs, targets 3 → 2, PF 1.09 → 0.88). The 60-min state
  itself never turns on inside a tf-60 position before it exits (median hold 8 min, ladder 4–10 ATR):
  trigger 60 / own on tf 60 = no-op.
- **tf-240 positions**: 9 trades, the 15-min state moves 2–4 of them for ±30…90; the 240 state never
  fires inside a position. No signal either way.
- Trigger 60 on tf-15 positions: negative at Y ≤ 1 (−170…−230, 20–26 moves), +108 at Y 1.5 from 3 moves.

## 5. Ablations

| variant | net | paired Δ | note |
|---|---|---|---|
| t15 Y0 / Y1 / Y2 `trans` (0→1 flip required) | +2193 / +2135 / +2421 | −339 / −332 / −27 | the few positions where the state is already on at open (5–9) are the ones that earn under `state`; needing a flip removes them and loses |
| t15 Y2 / Y3 / Y5 `repl` (looser stop allowed) | +2790 / +2796 / +2754 | +195 / +263 / +146 | candle stop-outs 63 → 42; this is "loosen the candle stop to 3–5 ATR", not the extdone idea — CIs [−280, +754] … [−780, +1128] |
| t60 Y2 / Y5 `repl` | +2693 / +2763 | +245 / +390 | same loosening effect through 26 moves, CI [−51, +721] / [−0, +907] |

## 6. Verdict

- Whole system: no Y ∈ [0, 5] with a 15- or 60-min trigger is distinguishable from the live rule
  (best own-tf Y 1.5 +248 net on +2 447, every trig-15/60 cell inside its bootstrap noise). Y ≥ 3 is a
  no-op against the 15-min candle stop; Y 0.5–1 is the worst spot.
- By tf: a weak, consistent-sign gain on **tf-15 positions only** with the 15-min state and Y 1–2;
  the same rule **hurts tf-60 positions** (15-min state too early) and the 60-/240-min states do not
  turn on during a position's life. If anything is tried forward, it is "own-tf state, tf 15 only,
  Y ≈ 1.5, tighten only" as a toggle — not a change to the live rule on this evidence.
- The `repl` ablation says the candle stop may be ~0.5–1 ATR too tight; that is a separate hypothesis
  (candle-stop offset sweep), not this one.

## 7. Follow-up 2026-10-21 — profit-side lock-in, and the last 24 h only

User: "does the stop move to the profitable position?" — §1–§6 moved it to the *adverse* side only
(`entry − Y·ATR` for a long; Y = 0 = breakeven). Added `p*` variants: candidate `entry + Y·ATR` (long) /
`entry − Y·ATR` (short), adopted the first time the price is beyond it after the entry-side state has been
on (a stop is never placed ahead of the price; ATR frozen at the first reading with the state on). Data
re-exported (feed ends 10-20 22:03Z, +16 min); window "1 day" = 10-19 22:03Z → 10-20 22:03Z (185 k trades,
reproduction 77/83 recorded fires, live 72 positions net +1 938). Output `…-output-1d.txt`.

Whole system, net:

| window | trigger | side | Y 0 | 0.5 | 1 | 1.5 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|---|---|---|---|
| 58 h (live +2447) | 15 | profit | +2399 | +2394 | +1819 | +1724 | +2495 | +1944 | +2216 | +2143 |
| | 60 | profit | +2229 | +2118 | +2103 | +2136 | +2357 | +2501 | +2533 | +2308 |
| | own | profit | +2482 | +2454 | +2148 | +2118 | +2652 | +2155 | +2349 | +2251 |
| 24 h (live +1938) | 15 | adverse | +1859 | +1967 | +1770 | +1776 | +1837 | +1938 | +1938 | +1938 |
| | 60 | adverse | +2136 | +2045 | +2045 | +2000 | +1959 | +1938 | +1938 | +1938 |
| | own | adverse | +2040 | +2123 | +2030 | +1951 | +1979 | +1938 | +1938 | +1938 |
| | 15 | profit | +1811 | +1762 | +1489 | +1187 | +2056 | +1568 | +1693 | +1722 |
| | 60 | profit | +2140 | +2035 | +1890 | +1805 | +1938 | +1923 | +1963 | +1799 |
| | own | profit | +1992 | +1981 | +1619 | +1603 | +2079 | +1803 | +1914 | +1859 |

Profit side, paired Δ vs live (58 h / 24 h): trig 15 Y 1 −551 / −449, Y 1.5 −723 [−1565, +59] / −751
[−1404, −144], Y 2 +47 / +118, Y 3 −504 / −370, Y 5 −305 / −216 [−484, −11]; own-tf Y 1.5 −330 / −335,
Y 2 +205 [−100, +501] / +141 [+21, +268]. Mechanism: the lock-in turns targets into moved stop-outs —
p15 Y 1.5 on 58 h: 67 moved, 40 stopped at the locked level, only 19 reached the target (adverse Y 0:
42 / 37). The path to the `cbnc` target normally retraces more than 1 ATR after the first excursion, so
a stop 1–1.5 ATR into profit sells the winners early; Y 2 is a single positive cell between two
strongly negative ones (−723 / −504), i.e. a spike, not a plateau. Y ≥ 3 reaches few positions and
still loses.

Adverse side on the 24 h window: trig 15 −139 … 0 (Y 0–2), trig 60 Y 0 +198 [−50, +452], own Y 1.5
+116 [+34, +222] / Y 2 +40 — the same weak tf-15 pattern as the 58 h (tf-15 subset +29 … +116, tf-60
subset −124 … −239 under trig 15). 72 positions; nothing decision-grade.

Verdict addendum: **moving the stop into profit after the entry-side extdone is negative at every
Y ≤ 1.5 and ≥ 3 on both windows; the single Y = 2 cell is noise.** The adverse-side (breakeven-ish)
move stays "not distinguishable from live".
