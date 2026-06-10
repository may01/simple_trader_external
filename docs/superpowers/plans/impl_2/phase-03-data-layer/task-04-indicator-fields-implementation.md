# Task 04: Indicator Field Implementations

**Phase:** 03 — Data Layer  
**Depends on:** Task 03 (IndicatorField framework)  
**Produces:** `indicators.py` — all IndicatorField subclasses for momentum, trend, volatility, oscillators, volume, price derivatives, classification, targets, trend flags, NN features

---

## Goal

Implement all `IndicatorField` subclasses covering every field group declared in `indicators_config.yaml`. After this task, `Indicators.compute(data_point, tf)` produces a fully enriched DataFrame for any timeframe.

---

## Context

Each field is a self-contained class reading prior columns from `data_point.get_df(tf)` and returning a `pd.Series`. TA-Lib is used for core technical indicators (RSI, MACD, ATR, Bollinger, CCI, SAR, EMA). pandas-ta or manual computation for derived fields.

---

## Files

- Modify: `indicators.py` (add all IndicatorField subclasses)

---

## Field Groups to Implement

### Momentum Group
- `RSI14Field` — TA-Lib `RSI(close, timeperiod=14)` → `{tf}_rsi_14`
- `RSI_MAField(source, length)` — EMA of RSI source → e.g., `{tf}_rsi_ma8`, `{tf}_rsi_ma12`, `{tf}_rsi_ma24`
- `RSI_MA_DiffField(source_ma)` — `rsi_ma - rsi_ma.shift(1)` → `{tf}_rsi_ma8_diff`, etc.

### Trend Group
- `EMAField(length)` — TA-Lib `EMA(close, length)` → `{tf}_ema_7`, `{tf}_ema_14`, `{tf}_ema_25`, `{tf}_ema_50`, `{tf}_ema_100`
- `MACDField` — TA-Lib `MACD(close, 12, 26, 9)` → `{tf}_macd`, `{tf}_macd_signal`, `{tf}_macd_hist`
- `MACD_FastField` — faster MACD params → `{tf}_macd_fast`, `{tf}_macd_fast_signal`
- `SARField` — TA-Lib `SAR(high, low, acceleration=0.02, maximum=0.2)` → `{tf}_sar`

### Volatility Group
- `ATR14Field` — TA-Lib `ATR(high, low, close, 14)` → `{tf}_atr_14`
- `NATR14Field` — TA-Lib `NATR(high, low, close, 14)` → `{tf}_natr_14`
- `ATR_MAField` — SMA of `atr_14` → `{tf}_atr_ma`
- `BollingerField(length, std_mult)` — TA-Lib `BBANDS` → `{tf}_bb_upper`, `{tf}_bb_middle`, `{tf}_bb_lower`
- `BollingerFastField` / `BollingerWideField` — faster/wider BB variants

### Oscillators Group
- `CCI14Field` — TA-Lib `CCI(high, low, close, 14)` → `{tf}_cci_14`
- `CCI_MAField` — SMA of CCI → `{tf}_cci_ma`

### Volume Group
- `VolMAField` — rolling mean of `volume` → `{tf}_vol_ma`
- `VolBuyMAField` — rolling mean of `buy_volume` → `{tf}_vol_buy_ma`
- `VolSellMAField` — `vol_ma - vol_buy_ma` → `{tf}_vol_sell_ma`

### Price Derivatives Group
- `CloseDiffPrcField` — `(close - close.shift(1)) / close.shift(1) * 100` → `{tf}_close_diff_prc`
- `CloseDiffPrcRMField` — rolling mean of `close_diff_prc` → `{tf}_close_diff_prc_rm`
- `CloseDiffPrcRMMeanAboveField` / `BelowField` — mean of positive/negative values in rolling window

### Classification Group (applies_to: [15, 60, 240, 1440])

All classification fields declare `resource_dependencies = ["rsi_classification.json"]`. If this file is absent, the field is skipped and its output column is NaN.

- `MoveClassField` — classifies `rsi_ma8` vs thresholds loaded from `rsi_classification.json` → `{tf}_move_class`
  - `resource_dependencies: ["rsi_classification.json"]`
  - `dependencies: ["rsi_ma8"]`
  - loads JSON once at construction via `DataAttributes.load_rsi_classification(STATS_DIR)`; raises `RuntimeError` if file exists but is malformed
- `ZoneClassField` — zone classification using same thresholds → `{tf}_zone_class`
  - `resource_dependencies: ["rsi_classification.json"]`
  - `dependencies: ["move_class"]`
- `OverLowField` / `OverHighField` — price above/below rolling thresholds → `{tf}_over_low`, `{tf}_over_high`
  - `resource_dependencies: ["rsi_classification.json"]`
  - `dependencies: ["zone_class"]`

### Targets Group (applies_to: [15, 60, 240, 1440])

All target fields declare `resource_dependencies = ["diff_stats.pkl"]`. If this file is absent, the field is skipped and its output column is NaN.

- `TgtLongField` / `SLLongField` — target and stop-loss levels for long → `{tf}_tgt_long`, `{tf}_sl_long`
  - `resource_dependencies: ["diff_stats.pkl"]`
  - `dependencies: []`
  - loads `diff_stats.pkl` once at construction via `DataAttributes.load_diff_stats(STATS_DIR)`
- `TgtShortField` / `SLShortField` — for short → `{tf}_tgt_short`, `{tf}_sl_short`
  - `resource_dependencies: ["diff_stats.pkl"]`
  - `dependencies: []`
- `ZBField` / `ZSField` — zone buy/sell thresholds → `{tf}_ZB`, `{tf}_ZS`
  - `resource_dependencies: ["diff_stats.pkl"]`
  - `dependencies: ["tgt_long", "tgt_short"]`

### Trend Flags Group
- `TrendUpField` — boolean: price above EMA-50 and EMA-50 rising → `{tf}_trend_up`
- `TrendDownField` — boolean: price below EMA-50 and EMA-50 falling → `{tf}_trend_down`

### NN Features Group (applies_to: [1, 5, 15])
- `NNRSINormField` — normalized RSI for NN input → `{tf}_nn_rsi_ma8_norm_mean`
- `NNCloseDiffATRField` — close diff normalized by ATR → `{tf}_nn_close_diff_atr_ma`

---

## Key Constraints

- All fields read ONLY `{tf}_*` prefixed columns from `data_point.get_df(tf)` — never raw column names like `"close"`
- `classification` and `targets` fields declare `resource_dependencies` (see field specs above); if those files are absent the orchestrator skips them gracefully (NaN output) — see Task 03 dependency resolution semantics
- Stats files loaded at field **construction time** (not per-row) — store as instance attributes; `is_available()` checks `os.path.exists` on each path in `resource_dependencies`
- Groups `["momentum","trend","volatility","oscillators","volume","price_derivatives","trend_flags","nn_features"]` are **base indicators** — `resource_dependencies = []`, computed in pass 1
- Groups `["classification","targets"]` are **class indicators** — `resource_dependencies` non-empty, computed in pass 2 only after `DataPreparer._compute_base_attributes()` writes the stats files
- TA-Lib functions require float64 arrays — cast explicitly before calling
- `SARField` — TA-Lib SAR has issues with very short series; handle `len(df) < 2` edge case
- Forward-looking target fields (`tgt_long`, `tgt_short`) — ONLY valid for offline wide DataFrame generation. These read `df.loc[ts + N]` → must NEVER be computed in the live path

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from indicators import Indicators
from data import WideDataPoint, get_stock_data, build_indicator_input
import os
os.environ['PAIR'] = 'link_usdt'; os.environ['ROOT_FOLDER'] = 'short'
df = get_stock_data('link_usdt')
ts = df[df['5_is_closed']].index[50]
from data import WideDataPoint
pt = WideDataPoint(df, ts)
Indicators.compute(pt, 5)
result_df = pt.get_df(5)
assert '5_rsi_14' in result_df.columns
assert '5_ema_50' in result_df.columns
assert '5_atr_14' in result_df.columns
print('indicator fields ok')
"
```

---

## Commit

`feat: implement all IndicatorField subclasses — momentum, trend, volatility, oscillators, classification, targets`
