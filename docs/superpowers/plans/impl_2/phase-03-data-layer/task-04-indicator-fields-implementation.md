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
- `MoveClassField` — classifies `rsi_ma8` vs `rsi_classification.json` thresholds → `{tf}_move_class`
- `ZoneClassField` — zone classification → `{tf}_zone_class`
- `OverLowField` / `OverHighField` — price above/below rolling thresholds → `{tf}_over_low`, `{tf}_over_high`

### Targets Group (applies_to: [15, 60, 240, 1440])
- `TgtLongField` / `SLLongField` — target and stop-loss levels for long → `{tf}_tgt_long`, `{tf}_sl_long`
- `TgtShortField` / `SLShortField` — for short → `{tf}_tgt_short`, `{tf}_sl_short`
- `ZBField` / `ZSField` — zone buy/sell thresholds → `{tf}_ZB`, `{tf}_ZS`

### Trend Flags Group
- `TrendUpField` — boolean: price above EMA-50 and EMA-50 rising → `{tf}_trend_up`
- `TrendDownField` — boolean: price below EMA-50 and EMA-50 falling → `{tf}_trend_down`

### NN Features Group (applies_to: [1, 5, 15])
- `NNRSINormField` — normalized RSI for NN input → `{tf}_nn_rsi_ma8_norm_mean`
- `NNCloseDiffATRField` — close diff normalized by ATR → `{tf}_nn_close_diff_atr_ma`

---

## Key Constraints

- All fields read ONLY `{tf}_*` prefixed columns from `data_point.get_df(tf)` — never raw column names like `"close"`
- `classification` and `targets` fields require `stats/rsi_classification.json` and `stats/diff_stats.pkl` to exist — loaded via `DataAttributes` (Task 07); these stats are produced by `DataPreparer._compute_base_attributes()` before the class-indicator pass runs (see Phase 09 Task 02 two-pass pipeline)
- Groups `["momentum","trend","volatility","oscillators","volume","price_derivatives","trend_flags","nn_features"]` are **base indicators** — no stats dependency, computed in pass 1
- Groups `["classification","targets"]` are **class indicators** — require base attributes, computed in pass 2
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
