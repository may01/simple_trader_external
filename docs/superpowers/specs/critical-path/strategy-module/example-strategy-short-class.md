# ExampleStrategyShort Class Specification

**Class:** `ExampleStrategyShort` (Concrete — Reference Implementation)
**File:** `strategies/example_strategy_short.py`
**Purpose:** Minimal pipeline-validation reference for short positions — NOT a production strategy
**Scope:** Mirror of ExampleStrategyLong; exercises the short-side execution pipeline with the simplest possible logic

---

## 1. Class Overview

`ExampleStrategyShort` validates the full short-side execution pipeline end-to-end:

```
OPEN_SHORT → position.open() → CLOSE_SHORT → position.finalize()
```

Signal logic is the direct inverse of `ExampleStrategyLong` — CCI directions flipped, position state gates inverted. Same simplicity constraints apply: one entry chain, one exit chain, no production-ready filters.

**When to use this file:**
- Confirming the short-side execution path works end-to-end
- As a template: copy → rename → replace `register_signals()` with real short logic

---

## 2. Inheritance & Constructor

```python
class ExampleStrategyShort(Strategy):
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

### 3.1 Entry Chain: CCI 140 Crossover Down

```
Chain Name: "5m CCI 140 cross down"
Action: STRATEGY_ACTION_OPEN_SHORT
Timeframe: 5 minutes
Notify: True

Conditions:
    And_Signal([
        History_Signal(Greater_Val_Signal(5, "cci", 140), shift=1),   # CCI was above 140
        History_Signal(Less_Val_Signal(5, "cci", 140), shift=0),      # CCI now below 140
    ])
```

**Logic:** One-candle crossover of CCI falling from extreme overbought — direct inverse of the long entry. No level proximity check. Fires frequently; acceptable for a reference implementation.

### 3.2 Exit Chain: CCI -100 Crossover Up

```
Chain Name: "5m CCI -100 cross up"
Action: STRATEGY_ACTION_CLOSE_SHORT
Timeframe: 5 minutes
Notify: True

Conditions:
    And_Signal([
        History_Signal(Less_Val_Signal(5, "cci", -100), shift=1),     # CCI was below -100
        History_Signal(Greater_Val_Signal(5, "cci", -100), shift=0),  # CCI now above -100
    ])
```

**Logic:** CCI recovers above -100 — simplest oversold reversal. Mirrors exit logic of ExampleStrategyLong with inverted direction.

### 3.3 register_signals() implementation

```python
def register_signals(self):
    tf = 5

    entry = SignalChain("5m CCI 140 cross down", STRATEGY_ACTION_OPEN_SHORT, tf, True)
    entry.add(And_Signal([
        History_Signal(Greater_Val_Signal(tf, "cci", CCI_ENTRY_THRESHOLD), 1),
        History_Signal(Less_Val_Signal(tf, "cci", CCI_ENTRY_THRESHOLD), 0),
    ]))
    self.signals.add_chain(entry)

    exit_chain = SignalChain("5m CCI -100 cross up", STRATEGY_ACTION_CLOSE_SHORT, tf, True)
    exit_chain.add(And_Signal([
        History_Signal(Less_Val_Signal(tf, "cci", CCI_EXIT_THRESHOLD), 1),
        History_Signal(Greater_Val_Signal(tf, "cci", CCI_EXIT_THRESHOLD), 0),
    ]))
    self.signals.add_chain(exit_chain)
```

**Total chains registered:** 2 (1 entry + 1 exit)

---

## 4. Condition Gate

```python
def check_conditions(self, data, position_state, action_msg):
    """
    Skip when already entering a short position.
    Returns True (execute) when NOT in WAIT_SAFETY_SELL or WAIT_SELL states.
    """
    if position_state in (POSITION_STATE_WAIT_SAFETY_SELL, POSITION_STATE_WAIT_SELL):
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
    # → data-layer tgt_short if available; fallback: close * (1 - 0.008)

def get_stop_loss_price(self, position_state, action, tf, cur_data, action_msg):
    return super().get_stop_loss_price(position_state, action, tf, cur_data, action_msg)
    # → data-layer sl_short if available; fallback: SAR + 0.3*ATR + level buffer
```

**Rationale:** ExampleStrategyShort exercises base price logic, not custom pricing. Production strategies override these.

---

## 6. Comparison with ExampleStrategyLong

| Aspect | ExampleStrategyLong | ExampleStrategyShort |
|--------|--------------------|--------------------|
| Entry signal | CCI crosses **up** from -140 | CCI crosses **down** from 140 |
| Exit signal | CCI crosses **down** from 100 | CCI crosses **up** from -100 |
| Position gate (skip when) | WAIT_SAFETY_BUY / WAIT_BUY | WAIT_SAFETY_SELL / WAIT_SELL |
| Open price default | current close | current close |
| Close price default | `tgt_long` / `close * 1.008` | `tgt_short` / `close * 0.992` |
| Stop-loss default | SAR − 0.3×ATR | SAR + 0.3×ATR |

---

## 7. Magic Numbers ⚠️ Pending Refactor

| Constant name (proposed) | Current value | Location | What it controls |
|--------------------------|--------------|----------|-----------------|
| `CCI_ENTRY_THRESHOLD` | `140` | `register_signals` entry chain | CCI level that defines the overbought crossover trigger |
| `CCI_EXIT_THRESHOLD` | `-100` | `register_signals` exit chain | CCI level that defines the oversold reversal trigger |
| `SIGNAL_TF` | `5` | `register_signals` | Timeframe (minutes) for both signal chains |

All three should be loaded from `strategy_config.yaml`. Until then, treat changes to these values as requiring explicit justification.

---

## 8. Files & Dependencies

**Primary File:**
- `strategies/example_strategy_short.py`

**Imports:**
- `Strategy` (base class)
- `SignalChain`, `SignalManager`
- Signal types: `History_Signal`, `Less_Val_Signal`, `Greater_Val_Signal`, `And_Signal`
- Constants: `STRATEGY_ACTION_OPEN_SHORT`, `STRATEGY_ACTION_CLOSE_SHORT`, `POSITION_STATE_WAIT_SAFETY_SELL`, `POSITION_STATE_WAIT_SELL`

**Data Flow:**
```
CCI @ 5min crosses down from 140 → OPEN_SHORT
CCI @ 5min crosses up from -100  → CLOSE_SHORT
    ↓
Strategy.check() → (OPEN_SHORT/CLOSE_SHORT/NOTHING, open_price, close_price, stop_price, 5)
    ↓
StrategyManager.check() → position.open() / position.close()
```

---

## 9. Summary

`ExampleStrategyShort` is the short-side mirror of `ExampleStrategyLong` — two chains, no production filters, all price computation delegated to base class defaults. Its sole purpose is to confirm that the short execution path (OPEN_SHORT through finalize) wires correctly. Copy this file as the starting template for any new short strategy and replace `register_signals()` with real signal logic.
