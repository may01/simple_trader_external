# Trend Detection Experiment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `external/docs/superpowers/experiment/trend_detection.md`
**Goal:** Find metrics that split strong-RSI-move points (move_class_sym0 == ±2) into a short-class and a long-class, iterate improvements autonomously until no gain, validate on oos2m.
**Architecture:** Read-only wide-df experiment in the style of zone-selection (`notebooks/action_zones/`): slim column/row subset extracted once per dataset → per-(tf, move-side) point selection → profit_strict ground truth → engineered leak-free features → univariate screen + sklearn classifiers → per-iteration reports → frozen-stats OOS pass. All derived data in memory or sidecar files; source frames never touched.
**Tech stack:** Python, pandas, sklearn (logistic + GradientBoosting), matplotlib (Agg→PNG), Docker service `experiment` (reused from zone-selection branch), pytest.

## Locked decisions (user-confirmed 2026-07-22)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Ground truth | profit_strict n1: long-class = `pslong==1 & psshort==0`, short-class = inverse; both-win / neither-win excluded but counted. Robustness pass: 1-bar and 4-bar forward log-return must agree on split direction |
| 2 | Strong-move source | `move_class_sym0 == ±2`. oos2m: baked column. 2y: digitize `{tf}_rsi_ma8_diff` by `move_cuts` (2y-fit, from rsi-quantile-sym0 stats) |
| 3 | Loop mode | Autonomous: hypothesis → report → improve → repeat; per-iteration report files; stop at no-improvement |

## Global Constraints (verbatim from spec + project rules)

- work in separate branch (`trend-detection-experiment` off `experimental_imp_2`, worktree at `/home/om/projects/simple_trader/worktrees/trend-detection-experiment`)
- **do not commit anything** (overrides default commit-per-step; verify steps replace commit steps)
- do not recalculate existing dataframes; `df_with_indicators.pkl` is read-only, never written back
- if new data required: calculate as separate columns and concatenate to the existing dataframe (batch dict → single `pd.concat`, precedent `data.py:241`)
- perform search for tf 15, 60, 240; strong-up and strong-down points searched **separately**
- 2y dataset for training (fit/select on chronological 70/30 train/test split of 2y)
- 2m oos dataset for validation ONLY (frozen stats + frozen model; never used for selection)
- plans/reports live in external docs repo, never committed to code repo
- experiment PNG/json artifacts → volume `{dataset_folder}/trend_detection/`; report md + key PNGs → `external/docs/superpowers/experiment/trend_detection/`

## Known facts (research, 2026-07-22)

- Wide frame: single df, all tfs as `{tf}_{col}`; 2y merged `/trader_data_long/train/2y_link_usdt/df_with_indicators.pkl` = 5.7 GB (host `/media/om/Alexandria/simple_trader/simple_trader_vol_long/...`), oos2m analog 470 MB, 84,961×752. Host RAM tight (~15 GB total) → heavy load only inside docker, one at a time.
- oos2m frame (Jul 22) already has `{tf}_zone_class_q`/`{tf}_move_class_sym0`; 2y frame (Jul 12) predates them.
- `move_cuts` (2y fit, symmetric, from worktree `rsi-quantile-sym0` `stats/train/link_usdt/rsi_classification.json`): tf15 ±0.40929/±1.36429 · tf60 ±0.42289/±1.40965 · tf240 ±0.43792/±1.45974. Class = np.digitize(diff, cuts, right=False) − 2; NaN → 0; +2 = diff ≥ +1.0·std (strong up), −2 = strong down.
- profit_strict label columns (1.0 = target touched strictly before stop within n·tf minutes, pessimistic entry, clean-entry filter; NaN = warmup/incomplete window):
  - tf15: `15_pslong_n1_m1_x0p3_l15_y0p2` / `15_psshort_n1_m1_x0p3_l15_y0p2` (n2 variant: `n2_`)
  - tf60: `60_pslong_n1_m1_x0p2_l15_y0p1` / `60_psshort_n1_m1_x0p2_l15_y0p1`
  - tf240: `240_pslong_n1_m1_x0p1_l15_y0p1` / `240_psshort_n1_m1_x0p1_l15_y0p1`
- Baseline side stats (1-bar fwd, `rsi_side_stats.json`): move −2 → long winrate .534/.571/.560 (tf15/60/240), move +2 → short .518/.526/.507. The experiment must beat these unconditional-side base rates *within* strong-move points.
- `levels.txt` (levels.py input) does not exist anywhere → "levels" hypothesis uses proxies: rolling swing high/low distance + BB bands.
- No time-within-higher-tf-candle feature exists; `{tf}_open_index` column enables computing it.
- Experiment docker files (`docker/Dockerfile.experiment`, `docker-compose.experiment.yml`, image = base + jupyterlab papermill scikit-learn scipy matplotlib plotly) exist ONLY on `zone-selection-experiment` worktree → copy into new worktree (uncommitted).
- sklearn models precedent (`azlib/models.py`): LogisticRegression, GradientBoostingClassifier(n_estimators=100, max_depth=3, learning_rate=0.1, random_state=42); no xgboost.

---

## Step 0 — Docker entry points (ground truth)

```bash
W=/home/om/projects/simple_trader/worktrees/trend-detection-experiment
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.experiment.yml"

# build experiment image (once, after copying the 2 docker files)
cd $W && $COMPOSE build experiment

# test gate (every layer ends GREEN here)
cd $W && $COMPOSE run --rm experiment pytest notebooks/trend_detection/tests -v

# L1: slim extraction (heavy: 5.7 GB read — run alone)
cd $W && $COMPOSE run --rm --env-file configs/nn_train_dataset_2y.env experiment \
    python notebooks/trend_detection/run_extract.py
cd $W && $COMPOSE run --rm --env-file configs/oos2m_dataset.env experiment \
    python notebooks/trend_detection/run_extract.py

# L2–L5: autonomous experiment loop on 2y (train/test split internal)
cd $W && $COMPOSE run --rm --env-file configs/nn_train_dataset_2y.env experiment \
    python notebooks/trend_detection/run_loop.py

# L6: final frozen OOS validation on oos2m
cd $W && $COMPOSE run --rm --env-file configs/oos2m_dataset.env experiment \
    python notebooks/trend_detection/run_oos.py
```

Dataset selection is ambient env (`--env-file`), never a script arg (zone-selection convention). Volume paths inside container: `/trader_data_long/train/{2y,oos2m}_link_usdt/`.

Verified: [ ] worktree + branch created · [ ] 2 docker files copied · [ ] image builds · [ ] pytest collects · [ ] both env files exist on branch

## Workspace setup (before L1)

- [ ] `cd /home/om/projects/simple_trader/main && git worktree add ../worktrees/trend-detection-experiment -b trend-detection-experiment experimental_imp_2`
- [ ] Copy from zone-selection worktree (stays uncommitted): `docker/Dockerfile.experiment`, `docker-compose.experiment.yml`
- [ ] `mkdir -p notebooks/trend_detection/{tdlib,tests}` + `touch notebooks/trend_detection/{tdlib/__init__.py,tests/__init__.py}`
- [ ] `conftest.py` in `notebooks/trend_detection/tests/` wires `sys.path` + provides `synthetic_slim_df` fixture (mirror `notebooks/action_zones/tests/conftest.py` pattern from zone worktree; small deterministic frame: ~600 rows × tfs {15,60,240,1440} × cols used below, seeded rng, includes closed flags, rsi diffs crossing cuts, label cols with known outcomes)
- [ ] Verify: `$COMPOSE build experiment` succeeds; `$COMPOSE run --rm experiment pytest notebooks/trend_detection/tests -v` collects 0 tests, exit 5 (no tests yet — acceptable pre-L1)

File map (all under `notebooks/trend_detection/`):

| File | Responsibility |
|------|----------------|
| `tdlib/config.py` | MOVE_CUTS, LABEL_COLS, column whitelist, paths, IterConfig |
| `tdlib/extract.py` | slim frame extraction (read-only source) |
| `tdlib/points.py` | sym0 digitize + strong-point selection |
| `tdlib/truth.py` | ground-truth marking + forward returns |
| `tdlib/features.py` | engineered features + FreezeStats |
| `tdlib/screen.py` | univariate screening + screen charts |
| `tdlib/models.py` | classifiers, metrics, importance |
| `tdlib/loop.py` | iteration runner, improvement loop, reports |
| `tdlib/oos.py` | frozen OOS scoring |
| `run_extract.py`, `run_loop.py`, `run_oos.py` | thin CLI drivers |
| `tests/test_l1_extract.py` … `tests/test_l6_oos.py` | layer test files |

---

## Layer 1 — Slim extraction (data)

### Interface (`tdlib/extract.py`, `tdlib/config.py`)

```python
# config.py
MOVE_CUTS: dict[int, list[float]]      # {15:[-1.36429,-0.40929,0.40929,1.36429], 60:[...], 240:[...]} — 2y fit, hardcoded from rsi_classification.json
LABEL_COLS: dict[int, dict[str, str]]  # tf -> {"pslong_n1":..., "psshort_n1":..., "pslong_n2":..., "psshort_n2":..., "plong_n1":..., "pshort_n1":...}
ANALYSIS_TFS: list[int]                # [15, 60, 240]
CONTEXT_TFS: list[int]                 # [5, 15, 60, 240, 1440]
def slim_columns(available: list[str]) -> list[str]: ...   # whitelist ∩ available; raises if a REQUIRED col missing
def slim_out_path() -> str: ...        # f"{dataset_folder()}trend_detection/slim.pkl"
def artifacts_dir() -> str: ...        # f"{dataset_folder()}trend_detection/"

# extract.py
def extract_slim() -> tuple[int, int]: ...  # loads wide df (env-driven path), filters rows 15_is_closed==True, selects slim_columns, saves slim_out_path(); returns (rows, cols). Never writes source.
```

Column whitelist (per tf in CONTEXT_TFS, where existing): OHLC block (`open_index,open,high,low,close,volume,is_closed`), RSI family (`rsi_14,rsi_ma8,rsi_ma8_diff,rsi_ma8_slope,rsi_ma12,rsi_ma12_diff,rsi_ma24,rsi_ma24_diff,nn_rsi_ma8_norm_mean_20`), classes (`zone_class,move_class,over_low,over_high` + `zone_class_q,move_class_sym0` when present), trend (`ema_{7,14,25,50,100}_minus_close`, ema pair diffs, `ema_{7,14,25,50,100}_slope`, `trend_up_50,trend_down_50`, `adx_14,adx_14_slope`), MACD (`macd_12_26_9,macd_signal_12_26_9,macd_hist_12_26_9,macd_5_13_9,macd_signal_5_13_9` + slopes), oscillators (`cci_14,cci_14_ma_5,cci_diff,sar_002_02`), volatility (`atr_14,natr_14,atr_14_ma_5,natr_14_ma_5,range_atr,vol_regime,bb_upper_20_2,bb_middle_20_2,bb_lower_20_2,bb_upper_10_15,bb_lower_10_15,bb_upper_20_3,bb_lower_20_3`, `bb_*_minus_close` where present), volume (`vol_ma_20,vol_ma_20_minus_volume`), price derivatives (`logret,body_ratio,wick_up,wick_dn,close_diff_prc,close_diff_prc_rm_6,{high,low}_diff_prc_rm_6` + `_std_above/_std_below`), targets (`tgt_long,tgt_short,sl_long,sl_short,ZB,ZS`), align (`align_*`), time (`sin_tod,cos_tod,sin_dow,cos_dow` — tf15 only), labels (LABEL_COLS values, ANALYSIS_TFS only). Row filter `15_is_closed==True` keeps every 15/60/240 candle close (~70k rows / 2y). REQUIRED = OHLC block + rsi_ma8_diff + labels; the rest best-effort (2y vs oos2m differ).

### Integration test → L2 (RED first, in Docker)

`tests/test_l1_extract.py::test_slim_feeds_point_selection` — build synthetic wide df → `extract_slim` (env pointed at tmp dir) → load slim pkl → `points.strong_points(slim, 15, +2)` returns only rows that are closed AND above the +1.0·cut. RED while both sides unimplemented.

### Unit tests

- `slim_columns`: drops unavailable optional cols; raises `KeyError` listing missing REQUIRED cols; no duplicates.
- `extract_slim`: output row count == `15_is_closed` count; source file mtime/bytes unchanged (read-only guarantee); output loadable; label cols preserved with NaN intact; idempotent overwrite of `slim.pkl`.
- Edge: source missing → `FileNotFoundError` with the resolved path in message.

### Constraints / notes

- One heavy pass per dataset; log shape + RSS before/after; `del df; gc.collect()` after save.
- oos2m slim also carries `{tf}_move_class_sym0` (baked) — kept for the L2 cross-check.
- Verify (manual, after GREEN): run both extraction commands from Step 0; expect 2y slim ≈ 70k×~450 (~250 MB), oos2m slim ≈ 5.7k×~460.

---

## Layer 2 — Point selection + ground truth

### Interface (`tdlib/points.py`, `tdlib/truth.py`)

```python
# points.py
def sym0_class(diff: pd.Series, cuts: list[float]) -> pd.Series: ...      # np.digitize(right=False)−2, NaN→0, int8
def strong_points(slim: pd.DataFrame, tf: int, side: int) -> pd.DataFrame: ...
    # rows where {tf}_is_closed & sym0_class({tf}_rsi_ma8_diff, MOVE_CUTS[tf]) == side; side ∈ {+2,−2}
def crosscheck_baked(slim: pd.DataFrame, tf: int) -> float: ...           # frac of closed rows where computed == baked {tf}_move_class_sym0; only when baked col present

# truth.py
def mark_truth(pts: pd.DataFrame, tf: int, horizon: str = "n1") -> pd.Series: ...
    # categorical: "long" (pslong==1 & psshort==0) | "short" (inverse) | "both" | "neither" | "nan"
def truth_counts(marked: pd.Series) -> dict[str, int]: ...
def fwd_log_return(slim: pd.DataFrame, tf: int, bars: int) -> pd.Series: ...
    # on {tf}_is_closed rows: log(close[k+bars]/close[k]) aligned back to row index; last rows NaN; never leaks into features
def robustness_agreement(pts: pd.DataFrame, marked: pd.Series, fwd1: pd.Series, fwd4: pd.Series) -> dict[str, float]: ...
    # P(fwd>0 | long-class), P(fwd<0 | short-class) for 1-bar and 4-bar
```

### Integration test → L3 (RED)

`tests/test_l2_points_truth.py::test_points_truth_feed_features` — synthetic slim with engineered known outcomes → `strong_points` → `mark_truth` → `features.feature_matrix` returns X aligned to exactly the long/short-marked rows (both/neither/nan dropped), y ∈ {0,1} (1 = long-class).

### Unit tests

- `sym0_class`: values straddling each cut land per `right=False` (boundary → upper tier); NaN→0; matches agent-verified semantics (+2 ≥ +1.0·std).
- `strong_points`: excludes non-closed rows; side filter exact; empty result OK (0 rows, warns).
- `crosscheck_baked`: identical synthetic baked column → 1.0; one flipped row → <1.0.
- `mark_truth`: all four categories + NaN labels → "nan"; horizon "n2" resolves n2 columns.
- `fwd_log_return`: hand-computed 2-row check; final `bars` rows NaN; non-closed rows NaN.
- Failure: unknown tf → KeyError from MOVE_CUTS/LABEL_COLS.

### Constraints / notes

- oos2m gate: `crosscheck_baked` must return ≥ 0.999 for each tf at run time — else abort run with report (cut provenance drift; see memory `spec_hash`-style drift risks).
- Expected 2y strong-point volumes (from side-stats n, order of magnitude): tf15 ~10.7k/side, tf60 ~2.6k/side, tf240 ~670/side. tf240 is small → report CIs (Wilson) everywhere; no sub-splitting beyond train/test.

---

## Layer 3 — Feature engineering (hypothesis metrics)

### Interface (`tdlib/features.py`)

```python
HIGHER_TF: dict[int, list[int]]   # {15:[60,240,1440], 60:[240,1440], 240:[1440]}
LOWER_TF: dict[int, list[int]]    # {15:[5], 60:[5,15], 240:[15,60]}
def engineered_features(slim: pd.DataFrame, tf: int) -> pd.DataFrame: ...
    # NEW columns only (same index; batch-dict → single concat), all leak-free (current/past rows only):
    #   bb_pos_{ctf}            (close−bb_lower_20_2)/(bb_upper_20_2−bb_lower_20_2), ctf ∈ {tf}∪HIGHER_TF[tf]
    #   oob_up_{ctf}, oob_dn_{ctf}      close vs bb_upper/lower_20_2 and _20_3 (out-of-bound flags)
    #   opp_bound_dist_{htf}    (close − bb_lower_20_2[htf])/atr_14[htf] for up-moves; sign-symmetric feature stored raw, side handled at analysis
    #   swing_dist_hi_{ctf}_{w}, swing_dist_lo_{ctf}_{w}   (rolling max(high,w)−close)/atr_14, (close−rolling min(low,w))/atr_14; w ∈ {20,50}; closed-row rolling on ctf series — levels proxy
    #   near_level_{ctf}        min(swing_dist_hi_20, swing_dist_lo_20) < 1.0  (atr-normalized, levels.py convention)
    #   time_in_candle_{htf}    (t − {htf}_open_index)/({htf}·60)  ∈ [0,1)
    #   time_left_{htf}         1 − time_in_candle_{htf}
    #   need_speed_{htf}        opp_bound_dist_{htf} / max(time_left_{htf}, 1/htf-bar)  — required drift to touch opposite bound in remaining candle time
    #   htf_move_{htf}          sym0_class({htf}_rsi_ma8_diff, MOVE_CUTS-nearest)  — higher-tf move state (running)
    #   htf_move_agree_{htf}    sign agreement of htf running rsi_ma8_diff with point-tf side
def feature_matrix(pts: pd.DataFrame, tf: int, feature_cols: list[str] | None = None) -> tuple[pd.DataFrame, pd.Series]: ...
    # X (existing slim cols for tf/context tfs + engineered), y from mark_truth; drops both/neither/nan; median-imputes remaining NaN feature cells, drops all-NaN cols
class FreezeStats:                 # train-frozen robust z-score (mirror azlib.indicators.FreezeStats)
    def fit(self, X: pd.DataFrame) -> "FreezeStats": ...
    def transform(self, X: pd.DataFrame) -> pd.DataFrame: ...
    def to_json(self, path: str) -> None: ...
    @classmethod
    def from_json(cls, path: str) -> "FreezeStats": ...
```

MOVE_CUTS has no tf1440/5 entries → `htf_move_1440` and lower-tf sym0 use nearest-tf cuts (240 for 1440, 15 for 5) — matches `_get_tf_classification` fallback convention; documented in report.

### Integration test → L4 (RED)

`tests/test_l3_features.py::test_features_feed_screen` — synthetic slim where one engineered feature (e.g. `bb_pos_15`) is constructed to separate classes → `feature_matrix` → `screen.univariate_screen` ranks it first with AUC > 0.9; a seeded-noise feature scores ≈ 0.5 (±0.1).

### Unit tests

- `bb_pos`: degenerate band (upper==lower) → NaN not inf; value 0/1 at band edges.
- `oob_*`: exact strict-inequality semantics; both 20_2 and 20_3 variants.
- `swing_dist_*`: rolling window uses only closed rows of ctf ≤ current time (assert no future row enters: construct spike after point, distance unchanged).
- `time_in_candle`/`time_left`: at htf open row → 0/1; last minute row → (htf−1)/htf & 1/htf; open_index in seconds vs minutes resolved against real column semantics (assert against synthetic fixture built from data.py convention).
- `need_speed`: time_left→0 clamps (no inf).
- `htf_move_*`: running (forming) value, not last-closed; NaN warmup → 0 class.
- `FreezeStats`: transform(train).std ≈ 1; to_json→from_json round-trip exact; transform never refits.
- `feature_matrix`: y encoding {short:0, long:1}; both/neither excluded; no label/fwd/target-derived columns in X (explicit leak blocklist: `pslong|psshort|plong|pshort|fwd_` regex assert).

### Constraints / notes

- All engineered features computed on the slim frame (closed 15m grid). For htf running values the slim row already carries the forming htf candle (broadcast) — no recompute of source data.
- Feature count budget: existing slim cols (~350 numeric after excluding labels/OHLC bookkeeping) + ~40 engineered; GBC handles it; logistic gets FreezeStats-normalized matrix.

---

## Layer 4 — Screening + classifiers

### Interface (`tdlib/screen.py`, `tdlib/models.py`)

```python
# screen.py
def univariate_screen(X: pd.DataFrame, y: pd.Series) -> pd.DataFrame: ...
    # per feature: n, auc (Mann-Whitney, oriented), abs_auc_dev, ks_stat, mean_long, mean_short, wilson_low — sorted by abs_auc_dev desc
def screen_charts(scr: pd.DataFrame, X: pd.DataFrame, y: pd.Series, out_dir: str, top_k: int = 15) -> list[str]: ...
    # per top-K feature: class-conditional hist/kde overlay PNG + long-rate-by-decile bar PNG; returns paths

# models.py
def fit_classifiers(X_tr: pd.DataFrame, y_tr: pd.Series) -> dict[str, object]: ...   # {"logistic": pipeline(FreezeStats→LogisticRegression), "gbc": GradientBoostingClassifier(100, 3, 0.1, rs=42)}
def eval_classifier(model: object, X: pd.DataFrame, y: pd.Series) -> dict[str, float]: ...
    # roc_auc, acc, base_rate, prec_at_top_decile(long), prec_at_bottom_decile(short), lift_long, lift_short, n
def importance_table(model: object, X_te: pd.DataFrame, y_te: pd.Series, n_repeats: int = 5) -> pd.DataFrame: ...  # permutation importance on test
```

### Integration test → L5 (RED)

`tests/test_l4_models.py::test_models_feed_loop` — synthetic separable X/y → `loop.run_iteration(cfg, slim)` consumes screen+models output and produces an `IterResult` whose metrics dict contains `gbc.roc_auc > 0.8` and writes `iter_01/metrics.json`.

### Unit tests

- `univariate_screen`: perfect feature auc→1.0 oriented; anti-feature also ranks top by abs_auc_dev; constant feature → dropped with note row; n reflects NaN-imputed rows.
- `eval_classifier`: hand-built probs → exact prec@decile & lift; degenerate one-class y → returns NaNs not crash.
- `fit_classifiers`: logistic pipeline applies FreezeStats fitted on train only (transform stats equality check).
- `screen_charts`: files exist, non-empty, Agg backend, `plt.close` (no figure leak: `plt.get_fignums()==[]`).
- `importance_table`: columns sorted desc, deterministic under fixed rs.

### Constraints / notes

- Train/test = chronological 70/30 split of 2y slim points per (tf, side) — split BEFORE any screening; all selection on train, reported on both.
- tf240 side n≈670 → 70/30 gives ~470/200; keep Wilson CIs and mark metrics with n<300 as low-confidence in reports.

---

## Layer 5 — Iteration loop + reports (autonomous)

### Interface (`tdlib/loop.py`)

```python
@dataclass IterConfig: iter_no: int; tf: int; side: int; horizon: str; feature_set: list[str] | None; notes: str
@dataclass IterResult: cfg: IterConfig; counts: dict; screen_top: pd.DataFrame; metrics: dict[str, dict[str, float]]; robustness: dict[str, float]; chart_paths: list[str]
def run_iteration(cfg: IterConfig, slim: pd.DataFrame) -> IterResult: ...        # L2→L3→L4 for one (tf, side)
def improvement_loop(slim: pd.DataFrame, max_iters: int = 5, eps_auc: float = 0.005) -> list[IterResult]: ...
    # iter 1: full feature set, all (tf∈{15,60,240} × side∈{+2,−2}) = 6 combos
    # iter k>1: apply next improvement from IMPROVEMENTS queue (data-driven feature refinements:
    #   e.g. top-feature interactions with time_left/need_speed, atr-normalization variants, window sweeps
    #   w∈{10,20,50,100} for swing_dist, horizon n2 sensitivity, pruned feature set from permutation importance)
    # keep an improvement iff mean test-AUC over combos rises > eps_auc; stop after 2 consecutive non-improvements or max_iters
def write_iter_report(res_list: list[IterResult], iter_no: int) -> str: ...
    # → external/docs/superpowers/experiment/trend_detection/iter_NN.md (+ copies of top-6 PNGs beside it)
    #   full artifact dump (all PNGs + metrics.json + screen.csv + freeze.json + models via joblib) → {artifacts_dir()}/iter_NN/
def write_final_report(all_iters: list[list[IterResult]]) -> str: ...
    # → external/docs/superpowers/experiment/trend_detection/results.md
```

Report md structure (each iteration): header (date, iter, config, data) → point counts per (tf,side) incl. both/neither/nan excluded → truth robustness (fwd 1/4-bar agreement) → univariate top-15 table → classifier metrics table (train + test, base rates, lifts, CIs) → embedded top charts → hypothesis verdicts (H1–H9 status) → improvement decision for next iter + rationale. Final `results.md` adds: improvement history table, selected best metrics per (tf,side), oos2m table (from L6), spec-mandated "potential hypotheses" list with verdicts, recommendation.

Hypotheses registry (seeded from spec bullets; verdict tracked per iteration):
H1 same-tf indicator state · H2 higher-tf indicators · H3 lower-tf indicators · H4 levels proxy (swing/BB distance) · H5 higher-tf move requires point-tf strong move (htf_move agree) · H6 out-of-bound flags (point + higher tf) · H7 opposite-bound distance of higher tf · H8 time-left / need-speed in higher-tf candle · H9 multivariate classifier over all.

### Integration test → L6 (RED)

`tests/test_l5_loop.py::test_loop_freezes_for_oos` — mini improvement_loop (max_iters=1) on synthetic slim → artifacts dir contains per-combo `freeze.json`, `model_gbc.joblib`, `selected_features.json`, `metrics.json`; `oos.run_oos` consumes them without refit (FreezeStats.from_json equality).

### Unit tests

- `improvement_loop`: improvement below eps → rejected, loop stops after 2 consecutive rejects; above eps → config carried forward; deterministic under fixed seed.
- `run_iteration`: crosscheck_baked gate wired (abort path raises with report line when <0.999 on frames carrying baked col).
- `write_iter_report`: md exists, contains counts table + metrics table; PNG copies exist; volume dump complete.
- Failure: empty point set for a combo → combo skipped with WARN row in report, loop continues.

### Constraints / notes

- Autonomous per locked decision 3; every iteration leaves a permanent report file (spec: "on each loop iteration create corresponding report").
- oos2m NEVER loaded here — loop code has no oos path import (test asserts `oos` not imported by `loop`).

---

## Layer 6 — OOS validation + final report

### Interface (`tdlib/oos.py`)

```python
def run_oos() -> pd.DataFrame: ...
    # env = oos2m; loads oos slim + frozen artifacts of BEST iteration only;
    # crosscheck_baked gate (≥0.999); strong_points → mark_truth → engineered features
    # → FreezeStats.from_json transform → stored models predict → eval_classifier
    # returns per-(tf,side) table: n, base_rate, auc, prec@deciles, lifts, robustness fwd-agreement
```

### Integration test (RED)

`tests/test_l6_oos.py::test_oos_no_refit` — run_oos on synthetic oos slim with planted frozen artifacts → metrics computed; FreezeStats file bytes unchanged after run; models not refitted (predict-only mock assert); output table has all 6 combos or explicit skip rows.

### Unit tests

- Missing frozen artifacts → actionable error naming expected path.
- oos slim lacking a baked sym0 col → crosscheck skipped with WARN (not crash); lacking label col → combo skipped.
- Final `results.md` gains OOS section; train/test/oos triple shown side by side per combo.

### Constraints / notes

- Selection is closed before this layer runs (frozen best iteration); oos numbers land only in `results.md`.
- Success yardstick (spec "how good this metric splits the classes"): test+oos AUC materially > 0.5 with consistent sign, and per-side lift over the unconditional side-stats base rates (tf60 −2 long .571 etc.).

---

## Execution order & verification gates

1. Workspace setup → docker build + pytest collect gate.
2. L1 RED → GREEN in docker → run both extractions (manual verify shapes/RAM).
3. L2 RED → GREEN → 2y point counts sanity vs side-stats n (~10.7k/2.6k/670 per side).
4. L3 RED → GREEN (leak blocklist test mandatory).
5. L4 RED → GREEN.
6. L5 RED → GREEN → run `run_loop.py` (the real autonomous experiment; hours-scale, GBC on ≤10.7k×~400 is minutes per combo — budget ~1–2 h total incl. charts).
7. L6 RED → GREEN → `run_oos.py` → `results.md`.
8. Cleanup check: `git status` in worktree shows only new untracked experiment files + 2 copied docker files; NOTHING committed; source pkl mtimes unchanged.

## Self-review (done at write time)

- Spec coverage: strong up/down separately (L2 side param, 6 combos) ✓ · mark short/long class (truth.py) ✓ · indicators same/higher/lower tf (L3 HIGHER_TF/LOWER_TF) ✓ · levels (H4 proxy — levels.txt absent, documented) ✓ · higher-tf-requires-move (H5) ✓ · out of bounds + higher tf (H6) ✓ · opposite bound higher tf (H7) ✓ · time left for bound touch (H8 need_speed) ✓ · classification algorithms (L4) ✓ · hypothesis list + reports + charts + best performers + improvement loop + per-iteration reports (L5) ✓ · select best metrics (results.md) ✓ · branch/no-commit/no-recalc/concat/tf-set/2y-train/oos-validate (Global Constraints) ✓
- Placeholder scan: signatures-only per layer-first-planning (project skill overrides full-code steps); no TBDs; all cuts/col names/paths concrete ✓
- Type consistency: `strong_points→mark_truth→feature_matrix→screen/models→loop→oos` chain signatures align ✓
