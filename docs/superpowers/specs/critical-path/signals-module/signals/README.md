# Signal Specifications Index

Per-signal specifications for all signals in `signals_lib/`.

| File | Source | Signals |
|------|--------|---------|
| [common-signals.md](common-signals.md) | `signals_lib/common.py` | `Less_Signal`, `Greater_Signal`, `Less_Val_Signal`, `Greater_Val_Signal`, `Cross_Up_Signal`, `Cross_Down_Signal`, `Cross_Up_Val_Signal`, `Cross_Down_Val_Signal`, `Rising_Signal`, `Falling_Signal`, `Diff_Greater_Signal`, `Diff_Less_Signal`, `Diff_LessIndi_Signal`, `Diff_GreaterIndi_Signal`, `Near_Level_Signal`, `Near_Price_Level_Signal`, `Over_Level_Signal`, `Under_Level_Signal` |
| [operations-signals.md](operations-signals.md) | `signals_lib/operations.py` | `And_Signal`, `Or_Signal`, `Not_Signal`, `History_Signal`, `Continuous_Signal`, `True_Signal`, `False_Signal`, `BoolValue_Signal`, `PersistentCounter_Signal`, `DataValue_Signal` |
| [complex-signals.md](complex-signals.md) | `signals_lib/complex.py` | `Diver_Bull_signal`, `Diver_Bear_signal`, `Diver_Hidden_Bull_signal`, `Diver_Hidden_Bear_signal`, `Bounce_Long_Signal`, `Bounce_Short_Signal` |
| [candle-signals.md](candle-signals.md) | `signals_lib/candle.py` | `BigCandle_Signal`, `LongTale_Signal`, `ShortTale_Signal`, `CandleUP_Signal`, `CandleDOWN_Signal` |
| [position-signals.md](position-signals.md) | `signals_lib/position_signals.py` | `PositionState_Signal`, `PositionType_Signal` |
| [nn-signals.md](nn-signals.md) | `signals_lib/nn_signals.py` | `NN_Signal`, `NN_Xbigger_Signal`, `NN_ValBigger_Signal`, `NN_ZScore_Signal` |

## Quick Signal Lookup

**"Is X above/below Y?"** → `Greater_Signal`, `Less_Signal`, `Greater_Val_Signal`, `Less_Val_Signal`  
**"Did X cross Y?"** → `Cross_Up_Signal`, `Cross_Down_Signal`, `Cross_Up_Val_Signal`, `Cross_Down_Val_Signal`  
**"Is X rising/falling?"** → `Rising_Signal`, `Falling_Signal`  
**"Is the gap between X and Y > threshold?"** → `Diff_Greater_Signal`, `Diff_Less_Signal`, `Diff_LessIndi_Signal`, `Diff_GreaterIndi_Signal`  
**"Is price near/over/under a level?"** → `Near_Level_Signal`, `Near_Price_Level_Signal`, `Over_Level_Signal`, `Under_Level_Signal`  
**"Combine conditions"** → `And_Signal`, `Or_Signal`, `Not_Signal`  
**"Check N candles ago"** → `History_Signal`  
**"Check N times in M candles"** → `Continuous_Signal`  
**"Read a boolean indicator"** → `BoolValue_Signal` (use for `trend_up`, `trend_down` columns)  
**"Divergence pattern"** → `Diver_Bull_signal`, `Diver_Bear_signal`, `Diver_Hidden_Bull_signal`, `Diver_Hidden_Bear_signal`  
**"Bounce off MA"** → `Bounce_Long_Signal`, `Bounce_Short_Signal`  
**"Candle size/shape"** → `BigCandle_Signal`, `LongTale_Signal`, `ShortTale_Signal`, `CandleUP_Signal`, `CandleDOWN_Signal`  
**"Position state/type"** → `PositionState_Signal`, `PositionType_Signal`  
**"NN confidence"** → `NN_Signal`, `NN_Xbigger_Signal`, `NN_ValBigger_Signal`, `NN_ZScore_Signal`
