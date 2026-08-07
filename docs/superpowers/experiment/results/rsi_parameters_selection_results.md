# RSI Parameters Selection — Results

Source: `rsi_parameters_selection_results.json` (25 parts).

## Analysis

### 0. Reading the ranking tables: the MI floor (why TF240 tops both rankings)

**The top of both mechanical rankings is an artifact and must be discarded.** `mutual_information`
returns MI in bits from a K×2 contingency table. For independent variables the plug-in estimator is
upward-biased by roughly `(K−1)/(2·N·ln2)` bits, so the floor scales with class count and inversely
with sample size. TF240 has 4,386 train / **354 oos** rows; TF15 has 70,170 / 5,664.

I re-estimated that floor per cell by Monte-Carlo (4,000 draws, multivariate hypergeometric with the
cell's own class populations and label base rate held fixed — i.e. the exact permutation null),
averaged over the same 4 label columns the ranking uses:

| cell (strict) | raw oos MI | oos null mean | oos null p95 (per col) | **adj oos** | raw train MI | train null | **adj train** |
|---|---|---|---|---|---|---|---|
| ma8 tf240 zscore 7 (rank 1) | 0.01988 | 0.01277 | 0.02476 | +0.00710 | 0.00069 | 0.00101 | **−0.00032** |
| ma12 tf240 zscore 7 (rank 2) | 0.01782 | 0.01294 | 0.02497 | +0.00489 | 0.00110 | 0.00102 | +0.00008 |
| ma12 tf240 sym0 7 (rank 3) | 0.01772 | 0.01290 | 0.02505 | +0.00482 | 0.00116 | 0.00102 | +0.00013 |
| **ma8 tf15 sym0 7 (rank 4)** | 0.01745 | 0.00077 | 0.00163 | **+0.01668** | 0.01714 | 0.00006 | **+0.01708** |

Every TF240 cell in the strict top-5 sits **below its own oos 95th-percentile null** and has a train
MI at or below the train null — zero signal on the split with 12× the rows. TF15 cells sit ~20× above
their null on both splits. Bias-corrected, the strict ranking becomes ma8/tf15 sym0-7 (+0.01668),
sym0-5 (+0.01647), zscore-7 (+0.01605), zscore-5 (+0.01585), quantile-7 (+0.01526), quantile-5
(+0.01519) — **the first nine raw rows collapse to a single TF15 block and TF240 vanishes.**

**Verification asked for — does MI rank cells highly for non-monotone structure?** Yes, in two
distinct ways, both present here:

1. **TF240 (all 18 cells).** ma8 tf240 zscore 7, train (4,386 rows, the split that can actually
   speak): strict_n1 spread by class = `+0.000 −0.014 −0.016 +0.005 −0.007 +0.007 +0.008`,
   ρ = +0.68; strict_n2 ρ = +0.04. That is noise around zero, not a ladder. The oos MI comes from
   cells of 5–16 rows: the ±3 tails hold 12 (neg) and **5** (pos) rows, and the headline rates are
   single events — `strict_n2_long` rate 0.200 at class +3 is 1/5 rows; `plain_n2_long` rate 0.600
   at class +3 is 3/5 rows. Do not read anything off TF240.
2. **The non-strict (`plain`) kind at every TF.** Its MI is a **|move| / volatility** detector, not a
   direction detector. ma24 tf15 quantile 7, train `plain_n1`: long rate `0.291 0.169 0.117 0.111
   0.129 0.179 0.287`, short rate `0.301 0.184 0.147 0.118 0.119 0.166 0.253` across classes
   −3…+3 — a symmetric U in *both* sides at once. MI is large; long-vs-short spread is ±0.01–0.03.

Everything below is stated on bias-adjusted MI with TF240 excluded, and cites train and oos.

### 1. Best ma window — strict labels

**ma8, unambiguously, and the ordering is monotone in the window.** Mean adjusted MI over the 18
non-TF240 cells per window:

| window | adj oos (strict) | adj train | tf15 adj oos | tf15 adj train | tf60 adj oos | tf60 adj train |
|---|---|---|---|---|---|---|
| **8** | **0.00900** | **0.00895** | **0.01592** | **0.01675** | **0.00208** | **0.00115** |
| 12 | 0.00699 | 0.00697 | 0.01266 | 0.01320 | 0.00132 | 0.00074 |
| 24 | 0.00440 | 0.00477 | 0.00788 | 0.00901 | 0.00091 | 0.00052 |

ma8 wins on both splits, at both usable TFs, and by a wide margin (+26% over ma12, +102% over ma24
on tf15 adj oos). The train/oos agreement per window is near-exact at tf15 (0.01675 / 0.01592,
0.01320 / 0.01266, 0.00901 / 0.00788), so this is not a selection accident. The raw spreads say the
same thing without any MI machinery — `strict_n2` extreme-class dominance on train, ma8 / ma12 / ma24
(7-class sym0): `+0.199 / −0.193`, `+0.187 / −0.182`, `+0.169 / −0.166`. Less smoothing preserves more
of the entry-timing signal; the 24-bar SMA blurs it.

### 2. Best ma window — non-strict labels

**ma24, weakly — and the answer reverses ma8's win, which is itself the tell.** The raw table is
useless here: raw window means are 0.00820 (ma8) / 0.00829 (ma12) / 0.00833 (ma24), a 1.6% spread
entirely composed of TF240 noise. Adjusted, TF240 excluded:

| window | adj oos (plain) | adj train | tf15 adj oos | tf15 adj train | tf60 adj oos | tf60 adj train |
|---|---|---|---|---|---|---|
| 8 | 0.00206 | 0.00383 | 0.00422 | 0.00479 | −0.00010 | 0.00286 |
| 12 | 0.00231 | 0.00361 | 0.00466 | 0.00460 | −0.00004 | 0.00262 |
| **24** | **0.00305** | 0.00340 | **0.00499** | 0.00428 | **0.00112** | 0.00252 |

Note the crossing: on **train** the ordering is ma8 > ma12 > ma24 (0.00383 → 0.00340), on **oos** it
is exactly reversed (0.00206 → 0.00305). At tf60 the ma8/ma12 adjusted oos MI is *negative*
(−0.00010, −0.00004) against a train MI of ~0.0027 — the non-strict signal at tf60 does not survive
out of sample at all. Best individual non-strict cells outside TF240 are ma12 tf15 sym0-7
(adj oos 0.00576 / adj train 0.00544) and ma24 tf15 zscore-7 (0.00573 / 0.00500), i.e. ma12 and ma24
are tied within noise and ma8 trails.

The honest reading: the two kinds are measuring different things. Strict labels carry direction and
want minimal smoothing (ma8); non-strict labels carry volatility and want maximal smoothing (ma24),
because a longer SMA makes `rsi_ma_diff` a cleaner proxy for realised bar range. **The windows differ
because the signals differ — this is not a tuning disagreement to be split.** For anything
direction-driven, ma8 is the answer and the non-strict column should be ignored (see §6).

### 3. 5 vs 7 classes

The mechanical table says 7 > 5 for both kinds (strict 0.01117 vs 0.00865; non-strict 0.01081 vs
0.00574). **Most of that gap is the MI floor**, which is ~1.5× larger for 7 classes than 5 by
construction. Bias-adjusted 5→7 deltas, per TF, on both splits:

| kind | tf | adj 5 (train) | adj 7 (train) | Δ train | adj 5 (oos) | adj 7 (oos) | Δ oos |
|---|---|---|---|---|---|---|---|
| strict | 15 | 0.01274 | 0.01323 | **+0.00048** | 0.01190 | 0.01241 | **+0.00052** |
| strict | 60 | 0.00081 | 0.00080 | −0.00000 | 0.00146 | 0.00141 | −0.00005 |
| strict | 240 | 0.00014 | 0.00015 | +0.00001 | 0.00061 | 0.00281 | **+0.00220** |
| plain | 15 | 0.00372 | 0.00540 | +0.00168 | 0.00379 | 0.00546 | +0.00167 |
| plain | 60 | 0.00233 | 0.00300 | +0.00067 | 0.00004 | 0.00061 | +0.00057 |
| plain | 240 | 0.00105 | 0.00111 | +0.00006 | 0.00174 | 0.00933 | **+0.00759** |

**Overfit tell: it is at TF240, and it is severe.** Strict TF240 gains +0.00001 on train from the
extra split and +0.00220 on oos — a 220× discrepancy in the wrong direction, which is impossible as
signal and is exactly what a 2%-tail-over-354-rows estimator does. Same shape for non-strict
(+0.00006 train vs +0.00759 oos). The 5-vs-7 table's verdict is driven by these rows.

At TF15, by contrast, the extra split adds +0.00048 train / +0.00052 oos for strict — **symmetric
across splits, so it is real, but it is ~4% relative.** At TF60 it adds nothing (−0.00005 oos).
Verdict: **7 classes is marginally better and not overfit at TF15; the split is not worth much, and
5 classes is the safer default** unless the consumer specifically wants the 2% tail broken out.

**Flip pattern — the hypothesis fails at TF15, and in an informative direction.** The spec predicted
the strong class keeps continuation dominance while the extra class shrinks or reverses
(pre-reversal blow-off). At TF15, strict, all 9 seven-class cells, both splits: **0 sign flips in
18/18 rows of the flip table**, and the extra tail does not shrink — it **expands**:

- ma8 tf15 sym0, train: neg strong `+0.0765` → extra `+0.1599` (2.1×); pos strong `−0.0804` → extra
  `−0.1457` (1.8×). n2: `+0.1283 → +0.1986`, `−0.1403 → −0.1932`.
- ma8 tf15 sym0, oos: neg `+0.0772 → +0.1121`; pos `−0.0700 → −0.1229`. n2: `+0.1329 → +0.1207`
  (the *only* shrink at tf15 strict, 1 of 72 side×horizon×split checks), `−0.1331 → −0.2011`.

So the 2% extra tail is the **strongest continuation cell in the grid, not a reversal cell**. A rule
that fades the extra tail expecting a blow-off would be backwards. The non-strict flips at tf15
(2–3 of 4 on train) come from spreads of magnitude 0.003–0.03 sitting either side of zero — sign
noise, not reversal. TF60's oos pos-side flips (1 of 4 in 8 of 9 cells) are the same thing: the
"strong" spread there is `+0.000` to `+0.006` while the extra spread is `−0.037` to `−0.111`, i.e.
the extra tail is still continuation with the inverted sign and it is the *strong* class that is
undefined. TF240's 4-of-4 oos flips are reading 5-row cells (see §0).

### 4. Technique comparison

Raw means put zscore first for both kinds (strict 0.01086 / 0.01032 / 0.00856 for zscore / sym0 /
quantile). Adjusted and with TF240 dropped, the ordering barely holds and reverses for non-strict:

| technique | strict adj oos | strict adj train | plain adj oos | plain adj train |
|---|---|---|---|---|
| **sym0** | **0.00712** | 0.00687 | 0.00248 | 0.00349 |
| zscore | 0.00687 | 0.00684 | 0.00231 | 0.00345 |
| quantile | 0.00639 | 0.00697 | **0.00264** | 0.00389 |

**Technique is close to irrelevant: 11% spread on strict, and quantile has the *best* strict adjusted
train MI (0.00697) while ranking last on oos.** Two structural facts explain the flatness:

- **sym0 and zscore are near-duplicates at 7 classes.** Both use k ∈ {1.0, 2.0} for the outer two
  cuts and `rsi_ma_diff` has mean ≈ 0, so the outer classes are literally the same rows. ma8 tf15:
  sym0 cuts `[−2.729, −1.364, −0.409, +0.409, +1.364, +2.729]` vs zscore
  `[−2.729, −1.364, −0.682, +0.682, +1.364, +2.728]` — only the innermost pair differs (k=0.3 vs
  0.5). Both give train tails of 1,657 / 1,585 and oos 116 / 179, and their strict spreads agree to
  3 dp (`+0.199 / −0.193` on n2 train for both). Their strict oos MI differs by 0.00062. **Treating
  them as two independent techniques over-counts the grid.**
- The difference that does exist is neutral-class width, and it cuts against MI: sym0 puts 23.9% of
  train rows in class 0, zscore 38.9%, quantile 40.0%. sym0's narrower neutral band spends more
  resolution on the near-zero region and buys it the top adjusted strict score, by a hair.

**Population sanity favours quantile.** Its train shares are exact by construction
(2/8/20/40/20/8/2) and hold up oos: 1.8 / 9.0 / 20.1 / 38.9 / 19.5 / 8.1 / 2.6 — max drift 1.0 pp.
sym0/zscore drift more in the tails: train ±3 = 2.4% / 2.3%, oos = 2.0% / **3.2%**, i.e. the positive
extra tail is 39% over-populated out of sample. That is a genuine regime tell (oos2m produced more
sharp RSI up-ticks than the 2y train window) and it is a reason to prefer quantile if downstream
code assumes stable class occupancy. Quantile's tail *lifts* are also the best in the grid
(ma8 tf15 quantile 7, oos strict_n1: long lift 3.02 at class −3, short lift 3.09 at +3, vs sym0's
2.60 / 3.31) — it loses aggregate MI only because 40% of rows sit inert in class 0.

**Monotonicity is the honest discriminator and it agrees with the adjusted MI.** At TF15, strict ρ =
−1.00 on train for all 18 cells and −0.96 to −1.00 on oos, for every technique. At TF60, ρ ∈
[−1.00, −0.60] train and [−0.96, −0.70] oos. At TF240 ρ is a coin flip (+0.68 to −0.15), independently
confirming §0.

### 5. Per-measurement commentary

**TF15 — 70,170 train / 5,664 oos rows. The only TF where anything is real.** ma8 sym0 7 has
adj train 0.01708 vs adj oos 0.01668, a −2% gap; every ma8 cell replicates within 10%. The per-class
lift ladders are monotone on both splits and both sides — `strict_n1` long lift by class
−3…+3: train `3.68 2.01 1.21 0.84 0.59 0.32 0.06`, oos `2.60 1.97 1.13 0.90 0.69 0.38 0.13`; short
lift train `0.12 0.28 0.58 0.89 1.29 1.93 3.02`, oos `0.00 0.20 0.41 0.86 1.33 2.22 3.31`. Seven
classes, two sides, two splits, no crossings anywhere except the oos long ladder's `−3 → −2` step
(2.60 vs 1.97 is ordered correctly; the `strict_n2` oos long ladder does invert at the extreme,
1.55 at −3 vs 1.88 at −2, on 116 rows). **This is the block to build on.**

**TF60 — 17,542 / 1,416. Corroborates direction, does not corroborate magnitude.** Best cell ma8
sym0 7: adj oos 0.00334 against adj train **0.00106** — oos is 3× train, the wrong direction, and the
raw oos MI (0.00660) is only ~2× its own null floor (0.00306 per column). So the oos level is on the
optimistic side of its noise band. What *does* replicate is the sign structure: ρ < 0 in 36/36
train pairs and 36/36 oos pairs, and the extreme-class spreads carry the same signs on both splits
(ma8 sym0 7 `strict_n2`: train `+0.034 / −0.047`, oos `+0.069 / −0.111`). Magnitudes are ~1/4 of
TF15's. Read TF60 as independent confirmation of §6, not as a candidate configuration.

**TF240 — 4,386 / 354. Empty; exclude from every conclusion.** Strict adj train MI is 0.0001–0.0002
across all 18 cells, i.e. indistinguishable from zero on the split with enough rows to test it, and
the train spreads are ±0.017 and non-monotone. The seven-class oos tails hold **4–6 rows on the
positive side and 11–16 on the negative** (ma8 zscore 7: `−3`=12, `+3`=5; the whole TF has 354 oos
rows split 7 ways with a 2–5% label base rate). The entire TF240 presence at the top of both raw
rankings, its apparent 5→7 gain, and its 4-of-4 flip counts are all the same small-sample artifact.
The 7-class TF240 *train* tails (~88–121 rows each) are already too thin to fit cuts against; the
oos tails are not measurable at all.

### 6. Direction — inversion check vs the 2026-07-22 gate finding

**The inversion holds, and it is the single most robust result in this run.** With
`spread = rate_long − rate_short`: falling-RSI-ma classes (negative ids) carry a **long** edge and
rising-RSI-ma classes (positive ids) carry a **short** edge — the opposite of naive momentum, and the
same sign as the 2026-07-22 `rsi_ma8_diff` sym0 gate finding.

Counted over all 54 cells × 2 horizons (`spread(most-negative class) > 0 > spread(most-positive
class)`), strict labels:

| tf | extreme-inverted, train | extreme-inverted, oos | ρ < 0, train | ρ < 0, oos | (of 36 pairs) |
|---|---|---|---|---|---|
| 15 | **36 / 36** | **36 / 36** | 36 / 36 | 36 / 36 | |
| 60 | 36 / 36 | 32 / 36 | 36 / 36 | 36 / 36 | |
| 240 | 4 / 36 | 0 / 36 | 5 / 36 | 12 / 36 | (no structure either way) |

Magnitude at the recommended cell (ma8 tf15 sym0 7, `strict_n1`, base rates train L 4.51% / S 4.90%,
oos L 4.31% / S 3.88%):

- class **−3** (steepest RSI-ma *fall*, 1,657 train / 116 oos rows): long 16.6% vs short 0.6% (train);
  long 11.2% vs short **0.0%** (oos).
- class **+3** (steepest RSI-ma *rise*, 1,585 / 179 rows): long 0.3% vs short 14.8% (train);
  long 0.6% vs short 12.8% (oos).

So the prior finding **reproduces on a different label family (same-TF profit strict, both horizons,
both sides), all three techniques, both class counts, and two independent TFs.** Any production gate
built on `rsi_ma{W}_diff` classes must be wired inverted relative to momentum intuition.

Interpretation caveat: these are same-TF labels measured forward from the same close that anchors the
1-bar RSI-ma diff, so a steep up-tick means price *has already run*. This is a short-horizon
mean-reversion / entry-timing effect, not a claim that RSI momentum is bearish. The strict
(clean-entry) labels isolate it precisely because they require the move to complete without an
adverse excursion first, which mechanically penalises entering after an extended run — which is also
why the effect is 5–10× weaker in the non-strict labels.

**The non-strict labels do not show the inversion — they show no direction at all.** Their ρ is
*positive* at TF15 (ma24 quantile 7: train `plain_n1` ρ = +0.86, oos +0.79), but against long/short
rates of 11–30% the spreads are ±0.01–0.03, and the extreme-class sign does not replicate: train
class −3 spread −0.010, oos −0.113 (n1); train +0.025, oos −0.143 (n2). Across all cells, non-strict
extreme-inversion count is 7/36 train vs 0/36 oos at tf15 and 0/36 train vs 6/36 oos at tf60 — pure
coin-flipping. Non-strict is a |move| detector (§0.2); **do not use it to pick a side.**

### 7. Overall recommendation

**Pick: `rsi_ma8_diff`, technique `sym0`, 7 classes, measured at TF15, against strict labels.**

- adj oos MI **0.01668** (raw 0.01745 against a null floor of 0.00077 — 22× the floor), adj train
  **0.01708**. The only cell in the 54 where a large oos number is matched by an equally large train
  number.
- Monotone in both splits: ρ = −1.00 train, −0.96 oos; long and short lift ladders both monotone
  across all 7 classes on both splits (§5).
- Populations usable: train tails 1,657 (−3) / 1,585 (+3) = 2.4% / 2.3%; oos 116 / 179 = 2.0% / 3.2%.

**Runner-up: same cell at 5 classes** (ma8 tf15 sym0 5) — adj oos 0.01647, adj train 0.01650,
ρ = −1.00 on *both* splits. It costs 1.3% of adjusted oos MI and buys real robustness: the extreme
class becomes 15.3% of train / 16.0% of oos rows (10,725 / 906) instead of 2%, and its oos lifts are
still 2.05 (long at −2) and 2.44 (short at +2). **If the downstream consumer needs per-class
statistics it can actually estimate, take the 5-class version** — §3 shows the extra split is worth
only ~4% relative.

**Technique alternative if population stability matters more than MI: ma8 tf15 quantile 7**
(adj oos 0.01526, adj train 0.01694). Class shares are fixed by construction and drift ≤1.0 pp out of
sample, and its extreme-tail oos lifts are the best in the grid (long 3.02 at −3, short 3.09 at +3).
Given sym0's +39% oos over-population of the `+3` tail (§4), this is a defensible swap.

**Caveats attached to the pick:**

1. **Exclude TF240 from everything downstream from this run.** Its ranking position is an MI
   small-sample artifact; on the split that can measure it, its adjusted MI is zero (§0, §5).
2. **Do not use the non-strict labels for direction** (§6). If non-strict is wanted as a volatility
   feature, the best window is ma24, not ma8 (§2) — a different question with a different answer.
3. **The ±(center) "extra" tail is a continuation cell, not a reversal cell.** The blow-off flip
   hypothesis is refuted at TF15 (0 flips in 18/18 flip-table rows; dominance *expands* 1.8–2.1×
   into the tail). Any rule that fades the extra tail is inverted twice over (§3).
4. **The signal is inverted relative to momentum** — steep RSI-ma fall ⇒ long, steep rise ⇒ short
   (§6). Confirms the 2026-07-22 gate finding.
5. **oos is 2 months of one symbol in one regime.** At TF15 that is 5,664 rows, enough to trust the
   *shape* (monotone ladders, sign, ordering across windows). It is not enough to trust the *level*
   of the lifts as a forward-return estimate, and the oos `+3` tail over-population is direct
   evidence the regime differed from train.

## Ranking — strict

| window | tf | technique | classes | oos MI | train MI | mono ρ (oos) |
|---|---|---|---|---|---|---|
| 8 | 240 | zscore | 7 | 0.01988 | 0.00069 | 0.25 |
| 12 | 240 | zscore | 7 | 0.01782 | 0.00110 | 0.19 |
| 12 | 240 | sym0 | 7 | 0.01772 | 0.00116 | 0.19 |
| 8 | 15 | sym0 | 7 | 0.01745 | 0.01714 | -1.00 |
| 24 | 240 | zscore | 7 | 0.01730 | 0.00161 | 0.07 |
| 8 | 15 | sym0 | 5 | 0.01698 | 0.01654 | -1.00 |
| 8 | 15 | zscore | 7 | 0.01683 | 0.01702 | -1.00 |
| 8 | 15 | zscore | 5 | 0.01636 | 0.01642 | -1.00 |
| 24 | 240 | sym0 | 7 | 0.01620 | 0.00186 | 0.09 |
| 8 | 15 | quantile | 7 | 0.01603 | 0.01701 | -1.00 |
| 8 | 240 | sym0 | 7 | 0.01572 | 0.00069 | 0.18 |
| 8 | 15 | quantile | 5 | 0.01570 | 0.01668 | -1.00 |
| 8 | 240 | zscore | 5 | 0.01490 | 0.00055 | 0.50 |
| 24 | 240 | quantile | 7 | 0.01484 | 0.00152 | -0.15 |
| 12 | 15 | sym0 | 7 | 0.01415 | 0.01351 | -1.00 |

## Ranking — non-strict

| window | tf | technique | classes | oos MI | train MI | mono ρ (oos) |
|---|---|---|---|---|---|---|
| 8 | 240 | zscore | 7 | 0.02685 | 0.00186 | 0.32 |
| 12 | 240 | sym0 | 7 | 0.02675 | 0.00222 | 0.25 |
| 12 | 240 | zscore | 7 | 0.02584 | 0.00189 | 0.25 |
| 24 | 240 | sym0 | 7 | 0.02208 | 0.00234 | -0.11 |
| 8 | 240 | sym0 | 7 | 0.02184 | 0.00187 | 0.25 |
| 8 | 240 | quantile | 7 | 0.02065 | 0.00191 | 0.32 |
| 24 | 240 | quantile | 7 | 0.01977 | 0.00234 | -0.32 |
| 24 | 240 | zscore | 7 | 0.01919 | 0.00243 | 0.11 |
| 12 | 240 | quantile | 7 | 0.01909 | 0.00221 | 0.25 |
| 8 | 240 | zscore | 5 | 0.01497 | 0.00160 | 0.50 |
| 12 | 240 | sym0 | 5 | 0.01156 | 0.00191 | 0.40 |
| 24 | 240 | zscore | 5 | 0.01132 | 0.00197 | 0.87 |
| 24 | 240 | sym0 | 5 | 0.01104 | 0.00190 | 0.90 |
| 12 | 240 | zscore | 5 | 0.01071 | 0.00158 | 0.40 |
| 24 | 240 | quantile | 5 | 0.01048 | 0.00186 | 0.70 |

## 5 vs 7 classes

strict:
| classes | mean oos MI | best cell |
|---|---|---|
| 5 | 0.00865 | ma8 tf15 sym0 (0.01698) |
| 7 | 0.01117 | ma8 tf240 zscore (0.01988) |

non-strict:
| classes | mean oos MI | best cell |
|---|---|---|
| 5 | 0.00574 | ma8 tf240 zscore (0.01497) |
| 7 | 0.01081 | ma8 tf240 zscore (0.02685) |

## Technique comparison

strict:
| technique | mean oos MI | mean train MI |
|---|---|---|
| quantile | 0.00856 | 0.00505 |
| sym0 | 0.01032 | 0.00502 |
| zscore | 0.01086 | 0.00497 |

non-strict:
| technique | mean oos MI | mean train MI |
|---|---|---|
| quantile | 0.00769 | 0.00331 |
| sym0 | 0.00847 | 0.00307 |
| zscore | 0.00866 | 0.00302 |

## Flip test (7-class)

| window | tf | technique | kind | split | flips (of 4) | extra pop − / + |
|---|---|---|---|---|---|---|
| 8 | 15 | quantile | strict | train | 0 | 1404 / 1404 |
| 8 | 15 | quantile | plain | train | 2 | 1404 / 1404 |
| 8 | 15 | quantile | strict | oos | 0 | 100 / 150 |
| 8 | 15 | quantile | plain | oos | 0 | 100 / 150 |
| 8 | 15 | sym0 | strict | train | 0 | 1657 / 1585 |
| 8 | 15 | sym0 | plain | train | 3 | 1657 / 1585 |
| 8 | 15 | sym0 | strict | oos | 0 | 116 / 179 |
| 8 | 15 | sym0 | plain | oos | 1 | 116 / 179 |
| 8 | 15 | zscore | strict | train | 0 | 1657 / 1585 |
| 8 | 15 | zscore | plain | train | 3 | 1657 / 1585 |
| 8 | 15 | zscore | strict | oos | 0 | 116 / 179 |
| 8 | 15 | zscore | plain | oos | 1 | 116 / 179 |
| 12 | 15 | quantile | strict | train | 0 | 1404 / 1404 |
| 12 | 15 | quantile | plain | train | 2 | 1404 / 1404 |
| 12 | 15 | quantile | strict | oos | 0 | 116 / 146 |
| 12 | 15 | quantile | plain | oos | 2 | 116 / 146 |
| 12 | 15 | sym0 | strict | train | 0 | 1605 / 1605 |
| 12 | 15 | sym0 | plain | train | 3 | 1605 / 1605 |
| 12 | 15 | sym0 | strict | oos | 0 | 135 / 160 |
| 12 | 15 | sym0 | plain | oos | 2 | 135 / 160 |
| 12 | 15 | zscore | strict | train | 0 | 1605 / 1605 |
| 12 | 15 | zscore | plain | train | 3 | 1605 / 1605 |
| 12 | 15 | zscore | strict | oos | 0 | 135 / 160 |
| 12 | 15 | zscore | plain | oos | 2 | 135 / 160 |
| 24 | 15 | quantile | strict | train | 0 | 1404 / 1404 |
| 24 | 15 | quantile | plain | train | 1 | 1404 / 1404 |
| 24 | 15 | quantile | strict | oos | 0 | 133 / 129 |
| 24 | 15 | quantile | plain | oos | 0 | 133 / 129 |
| 24 | 15 | sym0 | strict | train | 0 | 1553 / 1662 |
| 24 | 15 | sym0 | plain | train | 2 | 1553 / 1662 |
| 24 | 15 | sym0 | strict | oos | 0 | 150 / 147 |
| 24 | 15 | sym0 | plain | oos | 0 | 150 / 147 |
| 24 | 15 | zscore | strict | train | 0 | 1552 / 1665 |
| 24 | 15 | zscore | plain | train | 2 | 1552 / 1665 |
| 24 | 15 | zscore | strict | oos | 0 | 150 / 147 |
| 24 | 15 | zscore | plain | oos | 0 | 150 / 147 |
| 8 | 60 | quantile | strict | train | 0 | 351 / 351 |
| 8 | 60 | quantile | plain | train | 0 | 351 / 351 |
| 8 | 60 | quantile | strict | oos | 0 | 24 / 33 |
| 8 | 60 | quantile | plain | oos | 2 | 24 / 33 |
| 8 | 60 | sym0 | strict | train | 0 | 417 / 424 |
| 8 | 60 | sym0 | plain | train | 1 | 417 / 424 |
| 8 | 60 | sym0 | strict | oos | 1 | 29 / 36 |
| 8 | 60 | sym0 | plain | oos | 3 | 29 / 36 |
| 8 | 60 | zscore | strict | train | 0 | 416 / 424 |
| 8 | 60 | zscore | plain | train | 1 | 416 / 424 |
| 8 | 60 | zscore | strict | oos | 1 | 29 / 36 |
| 8 | 60 | zscore | plain | oos | 3 | 29 / 36 |
| 12 | 60 | quantile | strict | train | 0 | 351 / 351 |
| 12 | 60 | quantile | plain | train | 0 | 351 / 351 |
| 12 | 60 | quantile | strict | oos | 1 | 27 / 26 |
| 12 | 60 | quantile | plain | oos | 4 | 27 / 26 |
| 12 | 60 | sym0 | strict | train | 0 | 406 / 430 |
| 12 | 60 | sym0 | plain | train | 0 | 406 / 430 |
| 12 | 60 | sym0 | strict | oos | 1 | 29 / 33 |
| 12 | 60 | sym0 | plain | oos | 2 | 29 / 33 |
| 12 | 60 | zscore | strict | train | 0 | 405 / 432 |
| 12 | 60 | zscore | plain | train | 0 | 405 / 432 |
| 12 | 60 | zscore | strict | oos | 1 | 29 / 33 |
| 12 | 60 | zscore | plain | oos | 2 | 29 / 33 |
| 24 | 60 | quantile | strict | train | 0 | 351 / 351 |
| 24 | 60 | quantile | plain | train | 0 | 351 / 351 |
| 24 | 60 | quantile | strict | oos | 1 | 40 / 21 |
| 24 | 60 | quantile | plain | oos | 4 | 40 / 21 |
| 24 | 60 | sym0 | strict | train | 0 | 389 / 422 |
| 24 | 60 | sym0 | plain | train | 0 | 389 / 422 |
| 24 | 60 | sym0 | strict | oos | 1 | 40 / 27 |
| 24 | 60 | sym0 | plain | oos | 3 | 40 / 27 |
| 24 | 60 | zscore | strict | train | 0 | 389 / 422 |
| 24 | 60 | zscore | plain | train | 0 | 389 / 422 |
| 24 | 60 | zscore | strict | oos | 1 | 40 / 27 |
| 24 | 60 | zscore | plain | oos | 3 | 40 / 27 |
| 8 | 240 | quantile | strict | train | 3 | 88 / 88 |
| 8 | 240 | quantile | plain | train | 1 | 88 / 88 |
| 8 | 240 | quantile | strict | oos | 4 | 11 / 4 |
| 8 | 240 | quantile | plain | oos | 4 | 11 / 4 |
| 8 | 240 | sym0 | strict | train | 3 | 90 / 121 |
| 8 | 240 | sym0 | plain | train | 0 | 90 / 121 |
| 8 | 240 | sym0 | strict | oos | 4 | 12 / 5 |
| 8 | 240 | sym0 | plain | oos | 4 | 12 / 5 |
| 8 | 240 | zscore | strict | train | 3 | 90 / 121 |
| 8 | 240 | zscore | plain | train | 0 | 90 / 121 |
| 8 | 240 | zscore | strict | oos | 4 | 12 / 5 |
| 8 | 240 | zscore | plain | oos | 4 | 12 / 5 |
| 12 | 240 | quantile | strict | train | 3 | 88 / 88 |
| 12 | 240 | quantile | plain | train | 3 | 88 / 88 |
| 12 | 240 | quantile | strict | oos | 4 | 15 / 4 |
| 12 | 240 | quantile | plain | oos | 4 | 15 / 4 |
| 12 | 240 | sym0 | strict | train | 4 | 91 / 115 |
| 12 | 240 | sym0 | plain | train | 3 | 91 / 115 |
| 12 | 240 | sym0 | strict | oos | 4 | 15 / 5 |
| 12 | 240 | sym0 | plain | oos | 4 | 15 / 5 |
| 12 | 240 | zscore | strict | train | 4 | 92 / 115 |
| 12 | 240 | zscore | plain | train | 3 | 92 / 115 |
| 12 | 240 | zscore | strict | oos | 4 | 15 / 5 |
| 12 | 240 | zscore | plain | oos | 4 | 15 / 5 |
| 24 | 240 | quantile | strict | train | 0 | 88 / 88 |
| 24 | 240 | quantile | plain | train | 2 | 88 / 88 |
| 24 | 240 | quantile | strict | oos | 4 | 15 / 6 |
| 24 | 240 | quantile | plain | oos | 4 | 15 / 6 |
| 24 | 240 | sym0 | strict | train | 2 | 90 / 111 |
| 24 | 240 | sym0 | plain | train | 2 | 90 / 111 |
| 24 | 240 | sym0 | strict | oos | 4 | 15 / 6 |
| 24 | 240 | sym0 | plain | oos | 4 | 15 / 6 |
| 24 | 240 | zscore | strict | train | 2 | 90 / 110 |
| 24 | 240 | zscore | plain | train | 2 | 90 / 110 |
| 24 | 240 | zscore | strict | oos | 2 | 16 / 6 |
| 24 | 240 | zscore | plain | oos | 4 | 16 / 6 |

## Row counts & drops

| split | tf | closed rows | NaN diffs (8/12/24) |
|---|---|---|---|
| train | 15 | 70170 | 0/0/0 |
| train | 60 | 17542 | 0/0/0 |
| train | 240 | 4386 | 0/0/0 |
| oos | 15 | 5664 | 0/0/0 |
| oos | 60 | 1416 | 0/0/0 |
| oos | 240 | 354 | 0/0/0 |
