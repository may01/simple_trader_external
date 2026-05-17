# ExampleStrategyLong Class Specification

**Class:** `ExampleStrategyLong` (Concrete — Reference Implementation)
**File:** `strategies/example_strategy_long.py`
**Purpose:** Minimal pipeline-validation reference for long positions — NOT a production strategy
**Scope:** Exercises every Strategy interface method with the simplest possible logic; serves as copy-and-modify starting point for new long strategies

---

## 1. Class Overview

`ExampleStrategyLong` validates the full long-side execution pipeline end-to-end:

```
OPEN_LONG → position.open() → CLOSE_LONG → position.finalize()
```

Signal logic is intentionally trivial (one entry chain, one exit chain). This strategy is **not tuned for profitability** — its only job is to confirm that every layer between signal evaluation and P&L computation wires together correctly.

**When to use this file:**
- Confirming a fresh environment or new data pipeline produces correct action flow
- As a template: copy → rename → replace `register_signals()` with real logic

---

## 2. Inheritance & Constructor

```python
class ExampleStrategyLong(Strategy):
    def __init__(self, data, fee):
        """
        Parameters:
            data (Data): Current market data
            fee (float): Taker fee — injected from stock.item.fee; never hardcoded
        """
        super().__init__(data, fee)
        self.register_signals()
```

**Inherited from Strategy base:**
- `self.signals` (SignalManager) — populated by `register_signals()`
- `self.fee` — injected at construction
- `self.state` — STRATEGY_STATE_WAIT
- Price methods: `get_open_price()`, `get_close_price()`, `get_stop_loss_price()`, `find_level_in_range()`
- Level builder: `get_level_values()`

---

## 3. Signal Registration

### 3.1 Entry Chain: CCI -140 Crossover Up

```
Chain Name: "5m CCI -140 cross up"
Action: STRATEGY_ACTION_OPEN_LONG
Timeframe: 5 minutes
Notify: True

Conditions:
    And_Signal([
        History_Signal(Less_Val_Signal(5, "cci", -140), shift=1),     # CCI was below -140
        History_Signal(Greater_Val_Signal(5, "cci", -140), shift=0),  # CCI now above -140
    ])
```

**Logic:** One-candle crossover of CCI from extreme oversold — the simplest possible reversal signal. No level proximity check, no multi-timeframe confirmation. Fires frequently; that is acceptable for a reference implementation.

### 3.2 Exit Chain: CCI 100 Crossover Down

```
Chain Name: "5m CCI 100 cross down"
Action: STRATEGY_ACTION_CLOSE_LONG
Timeframe: 5 minutes
Notify: True

Conditions:
    And_Signal([
        History_Signal(Greater_Val_Signal(5, "cci", 100), shift=1),   # CCI was above 100
        History_Signal(Less_Val_Signal(5, "cci", 100), shift=0),      # CCI now below 100
    ])
```

**Logic:** CCI falls back below 100 — simplest overbought reversal. Mirrors entry logic in structure (two-candle crossover).

### 3.3 register_signals() implementation

```python
def register_signals(self):
    tf = 5

    entry = SignalChain("5m CCI -140 cross up", STRATEGY_ACTION_OPEN_LONG, tf, True)
    entry.add(And_Signal([
        History_Signal(Less_Val_Signal(tf, "cci", CCI_ENTRY_THRESHOLD), 1),
        History_Signal(Greater_Val_Signal(tf, "cci", CCI_ENTRY_THRESHOLD), 0),
    ]))
    self.signals.add_chain(entry)

    exit_chain = SignalChain("5m CCI 100 cross down", STRATEGY_ACTION_CLOSE_LONG, tf, True)
    exit_chain.add(And_Signal([
        History_Signal(Greater_Val_Signal(tf, "cci", CCI_EXIT_THRESHOLD), 1),
        History_Signal(Less_Val_Signal(tf, "cci", CCI_EXIT_THRESHOLD), 0),
    ]))
    self.signals.add_chain(exit_chain)
```

**Total chains registered:** 2 (1 entry + 1 exit)

---

## 4. Condition Gate

```python
def check_conditions(self, data, position_state, action_msg):
    """
    Skip when already entering a long position.
    Returns True (execute) when NOT in WAIT_SAFETY_BUY or WAIT_BUY states.
    """
    if position_state in (POSITION_STATE_WAIT_SAFETY_BUY, POSITION_STATE_WAIT_BUY):
        return False
    return True
```

---

## 5. Price Methods

All three methods delegate to base class defaults — no overrides:

```python
def get_open_price(self, action, tf, cur_data, action_msg):
    return super().get_open_price(action, tf, cur_data, action_msg)
    # → [current close price]

def get_close_price(self, action, tf, cur_data, action_msg):
    return super().get_close_price(action, tf, cur_data, action_msg)
    # → data-layer tgt_long if available; fallback: close * 1.008

def get_stop_loss_price(self, position_state, action, tf, cur_data, action_msg):
    return super().get_stop_loss_price(position_state, action, tf, cur_data, action_msg)
    # → data-layer sl_long if available; fallback: SAR - 0.3*ATR - level buffer
```

**Rationale:** ExampleStrategyLong exercises base price logic, not custom pricing. Production strategies override these.

---

## 6. Magic Numbers ⚠️ Pending Refactor

| Constant name (proposed) | Current value | Location | What it controls |
|--------------------------|--------------|----------|-----------------|
| `CCI_ENTRY_THRESHOLD` | `-140` | `register_signals` entry chain | CCI level that defines the oversold crossover trigger |
| `CCI_EXIT_THRESHOLD` | `100` | `register_signals` exit chain | CCI level that defines the overbought reversal trigger |
| `SIGNAL_TF` | `5` | `register_signals` | Timeframe (minutes) for both signal chains |

All three should be loaded from `strategy_config.yaml` rather than hardcoded. Until then, treat changes to these values as requiring explicit justification.

---

## 7. Files & Dependencies

**Primary File:**
- `strategies/example_strategy_long.py`

**Imports:**
- `Strategy` (base class)
- `SignalChain`, `SignalManager`
- Signal types: `History_Signal`, `Less_Val_Signal`, `Greater_Val_Signal`, `And_Signal`
- Constants: `STRATEGY_ACTION_OPEN_LONG`, `STRATEGY_ACTION_CLOSE_LONG`, `POSITION_STATE_WAIT_SAFETY_BUY`, `POSITION_STATE_WAIT_BUY`

**Data Flow:**
```
CCI @ 5min crosses up from -140 → OPEN_LONG
CCI @ 5min crosses down from 100 → CLOSE_LONG
    ↓
Strategy.check() → (OPEN_LONG/CLOSE_LONG/NOTHING, open_price, close_price, stop_price, 5)
    ↓
StrategyManager.check() → position.open() / position.close()
```

---

## 8. Summary

`ExampleStrategyLong` is a two-chain pipeline validator. It deliberately avoids level proximity checks, multi-timeframe confirmation, graduated exits, and trend gating — all of which are production concerns. The only goal is to fire OPEN_LONG and CLOSE_LONG through the full stack reliably, confirming that signal evaluation → StrategyManager → Position → Execution wires together without errors. Copy this file as the starting template for any new long strategy and replace `register_signals()` with real signal logic.
