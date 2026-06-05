# Task 03: Config YAML Files

**Phase:** 00 — Infrastructure  
**Depends on:** Task 02 (constants, helpers)  
**Produces:** `candles_config.yaml`, `indicators_config.yaml` — drives timeframe and indicator registry for all modules

---

## Goal

Create the two YAML config files that govern active timeframes and the indicator field registry. Both paths (live and simulation) read the same files at startup.

---

## Context

`candles_config.yaml` defines the canonical TF list consumed by `LiveData`, `DataPreparer`, `SimulationData`, and all signal/strategy code. `indicators_config.yaml` declares every `IndicatorField` — name, group, dependencies, applicable TFs, and parameters. No field names are hardcoded in `Indicators.py`; all come from this config.

---

## Files

- Create: `configs/candles_config.yaml`
- Create: `configs/indicators_config.yaml`
- Create: `config_loader.py` — utility to parse both files, expose `CANDLES` list and field registry

---

## candles_config.yaml Structure

```yaml
candles: [1, 5, 15, 60, 240, 1440]
```

Active TFs: 1-min, 5-min, 15-min, 1-hour, 4-hour, daily. 3-min removed (was unused). 1440 added for macro trend signals.

---

## indicators_config.yaml Structure

Each entry declares one `IndicatorField`:

```yaml
fields:
  - name: rsi_14
    group: momentum
    applies_to: all         # or list: [1, 5, 15]
    depends_on: []
    library: talib
    params:
      length: 14

  - name: rsi_ma8
    group: momentum
    applies_to: all
    depends_on: [rsi_14]
    params:
      source: rsi_14
      length: 8
  ...
```

`library` is optional — omit for computed/derived fields (those with non-empty `depends_on`). `config_loader.py` treats absent `library` as `None` and skips talib dispatch for that field.

### Required Field Groups

| Group | Fields |
|-------|--------|
| momentum | `rsi_14`, `rsi_ma8`, `rsi_ma12`, `rsi_ma24`, `rsi_ma8_diff`, `rsi_ma12_diff`, `rsi_ma24_diff` |
| trend | `ema_7`, `ema_14`, `ema_25`, `ema_50`, `ema_100`, `macd`, `macd_signal`, `macd_hist`, `macd_fast`, `macd_fast_signal` |
| volatility | `atr_14`, `natr_14`, `atr_ma`, `bb_upper`, `bb_middle`, `bb_lower`, `bb_fast_upper`, `bb_fast_lower`, `bb_wide_upper`, `bb_wide_lower` |
| oscillators | `cci_14`, `cci_ma`, `sar` |
| volume | `vol_ma`, `vol_buy_ma`, `vol_sell_ma` |
| price_derivatives | `close_diff_prc`, `close_diff_prc_rm`, `close_diff_prc_rm_mean_above`, `close_diff_prc_rm_mean_below`, `high_diff_prc`, `high_diff_prc_rm`, `high_diff_prc_rm_mean_above`, `high_diff_prc_rm_mean_below`, `low_diff_prc`, `low_diff_prc_rm`, `low_diff_prc_rm_mean_above`, `low_diff_prc_rm_mean_below` |
| classification | `move_class`, `zone_class`, `over_low`, `over_high` (applies_to: [15, 60, 240, 1440]) |
| targets | `tgt_long`, `sl_long`, `tgt_short`, `sl_short`, `ZB`, `ZS` (applies_to: [15, 60, 240, 1440]) |
| trend_flags | `trend_up`, `trend_down` |
| nn_features | `nn_rsi_ma8_norm_mean`, `nn_close_diff_atr_ma` |

---

## Interface — config_loader.py

- `load_candles_config(path: str = "configs/candles_config.yaml") -> list[int]` — returns `[1, 5, 15, 60, 240, 1440]`
- `load_indicators_config(path: str = "configs/indicators_config.yaml") -> list[IndicatorFieldConfig]` — returns list of field descriptors sorted in dependency order
- `CANDLES: list[int]` — module-level constant, loaded once at import

---

## Key Constraints

- `indicators_config.yaml` must declare fields in dependency order OR `config_loader.py` must topologically sort by `depends_on`
- `applies_to: all` expands to full `CANDLES` list at load time
- `classification` and `targets` groups apply ONLY to `[15, 60, 240, 1440]` — NOT to 1-min or 5-min


---

## Verification

```bash
docker compose run --rm simulate python3 -c "
from config_loader import load_candles_config, load_indicators_config
candles = load_candles_config()
assert candles == [1, 5, 15, 60, 240, 1440], f'Got {candles}'
fields = load_indicators_config()
names = [f.name for f in fields]
assert 'rsi_14' in names
# rsi_ma8 must come after rsi_14
assert names.index('rsi_ma8') > names.index('rsi_14')
print('config ok')
"
```

---

## Commit

`feat: add candles_config.yaml and indicators_config.yaml with config loader`
