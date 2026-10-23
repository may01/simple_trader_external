# trend_ma_length — results

**Run date:** 2026-10-21. **Spec:** [`trend_ma_length.md`](../trend_ma_length.md). **Verdict: negative** (the question);
two side findings for follow-up. **Disposition:** no branch (read-only replay over the executor DB + host run over the
stored frames); scripts, raw outputs and the run report in `external/executor/runs/2026-10-21-trend-ma-length-*`.
No code changed in main/ or the executor.

## Question and answer

The CB zone entry's trend filter (`{tf}_cb_f_trend_{side}`) is the forming-candle slope class of the **EMA-25 of
closes** (the user's "ma 21 or 25": there is no 21 in the flow). Asked: how does the profit change if the slope of the
**EMA-7** or the **EMA-14** is used instead?

| tier | e25 (live construction) | **EMA-14**: Δ vs e25 (CI90, P<0) | **EMA-7**: Δ vs e25 |
|---|---|---|---|
| paper executor replay, 84 h, 212 trades | +3 783 USDT (live stored flags: +3 732) | **+168** ([−825, +1 201], 0.40) | **−383** ([−1 821, +1 058], 0.67) |
| 2y frames, set-C entries, hold 60 min, 57 383 entries | +166 435 | −3 825 ([−19 820, +12 368], 0.66) | **−22 822** ([−47 079, +31], 0.95) |
| oos2m frames, 4 414 entries | +15 827 | −1 854 ([−7 813, +4 102], 0.69) | **−10 512** ([−19 237, −1 853], 0.97) |
| 2y / oos2m with the 1-min momentum stand-in gate | −9 714 / −4 079 | +1 918 (0.39) / −1 609 (0.76) | −14 119 (0.93) / −3 894 (0.90) |

**EMA-14: no measurable change** on any tier (every CI straddles zero, the sign flips between tiers).
**EMA-7: worse on every tier**, by −383 on the paper run and by 14 % / 66 % of the e25 net on 2y / oos2m, with the loss
concentrated on the 15-min zones (2y −12.5 k / −12.3 k long / short, P 0.94 / 0.95; oos2m −9.7 k long, P 1.00): the
fast class vetoes bounce entries while its slope still points against the trade, and lets through entries the EMA-25
vetoed. The ranking holds at hold 30 and 240 min and in both halves of the paper window. Per tf swaps (EMA-14 / 7 on
one tf, EMA-25 on the others) are all inside noise (Δ −197 … +209). The EMA length is not the lever.

## Side findings (not the question; candidates for their own experiment)

1. **The veto's strength is the lever, and in the wrong direction.** Weakening the filter beats live on every tier:
   X 0.5 → 1.0 +0.9…+1.1 k (P 0.12–0.18) and no flag at all +968 (P 0.17) on the paper run; no flag +71.6 k on 2y (CI90
   [+39.7 k, +105.6 k]) and +10.6 k on oos2m (P 0.09) under the set-C gate (a wash, +2.3 k / −0.5 k, under the
   momentum stand-in gate). Strengthening it (sign-only, X 0.01) halves the trades and loses 1.9–2.6 k (P 0.94–0.98).
2. **The closed-candle EMA-25 class beats the forming one**: +22.4 k on 2y (P 0.01), +5.3 k on oos2m (P 0.06), +1 on the
   paper run (equal); stable at every hold. The forming definition (the 2026-10-17 memory: all tfs fire together on
   sharp moves, thresholds frozen on closed-candle slopes) vetoes more candidates (pass rate 0.64–0.76 vs 0.76–0.84 on
   2y) without buying quality.

## Gates

| Gate | Number |
|---|---|
| Reproduction, fires | live-flag sim re-fires 177 / 188 recorded CbZoneEntry rows at the same ms / side / tf (+4 within ±120 s; 7 at executor restarts); class 176/177, rule 176/177 |
| Reproduction, flag | recomputed forming EMA-25 flag vs the stored flag at every trade: 99.11–99.92 % agreement per (tf, side), pass rates equal to 3 decimals; e25 vs live net +3 783 vs +3 732 (paired Δ +51, CI90 [−606, +701]) |
| Reproduction, thresholds | the live `EMA_SLOPE_STATS` reproduced from the stored 2y `{tf}_ema_25`: mean rel diff 0 / 2.3e-16 / 0, std 7.1e-6 / 2.9e-5 / 1.1e-4 (= sample vs population std); the 105-window EMA recomputation vs stored: median rel diff 0, max ≤ 4.1e-3 |
| Provenance | N = 7 / 14 thresholds = mean ± 0.5·std of the 2y closed-candle `diff_prc` per tf (table in the run report §2), the live recipe; nothing fitted on the replay window or oos2m |
| Null floor | paper run: 212 trades, net CI90 ≈ ±2.6 k, every length Δ inside its paired CI; 2y: 57 k entries, e7's Δ CI90 [−47 k, +0.03 k]; oos2m: e7's CI90 excludes zero |
| Base rate | n/a (P&L; the no-flag row is the unconditional reference: the flag removes 21 % / 27 % of candidate entries on 2y / oos2m and lowers the net) |
| Degeneracy | none: no optimizer; the variants are fixed constructions |
| Truth ladder | paper flow (all live rules) → 2y / oos2m set-C stand-in (no 1-min class, exit at target) → + momentum gate: EMA-7's sign is the same on all three, EMA-14's is noise on all three |
| Feature ablation | forming vs closed class (c7 / c14 / c25), X 0.01 / 0.5 / 1.0, per-tf swaps, no flag — all reported |
| Look-ahead | prev-closed EMA from fully closed candles, the trade's / minute's own price as the forming close, entry at the minute's close with outcomes from the next minute, mean range over bars before the minute, indicators by `received_at ≤ t` |
| Concentration | paper run top-2 trades +740…+805 in every variant (the same two 240 trades) |
| Stability | paper halves: e14 > e25 in H2 only, e7 < e25 in both; 2y / oos2m: holds 30 / 60 / 240 min give the same ranking |

## Caveats

- The paper tier is 84 h of one pair in one regime (LINK 11.7–12.5, the 4-h EMA-25 sloping down half the time);
  212 trades cannot separate ±400 USDT. The 2y / oos2m tier carries the decision on EMA-7; EMA-14 is undecidable
  everywhere and is therefore not worth a change.
- The 2y / oos2m tier is a stand-in flow: no 1-min trade-MA class (a 1-min momentum gate is the ablation), exit at
  the target price instead of the trend-flip exit, no reversals across (tf, side), fixed max hold, no fees (PF ≈ 1.05
  before fees — the stand-in is for ranking flag variants, not for the system's absolute P&L).
- The forming flag is recomputed from Binance klines + the trade price at minute granularity (klines) / per trade
  (replay); the live value uses the forming 1-min candle between snapshots — hence 99.1–99.9 % and not 100 %.

## Disposition

Negative. No change to the executor or main/. Candidates recorded for later: drop the trend flag, or switch it to the
closed-candle EMA-25 class (both positive on all tiers here, neither decision-grade on the paper run alone).
