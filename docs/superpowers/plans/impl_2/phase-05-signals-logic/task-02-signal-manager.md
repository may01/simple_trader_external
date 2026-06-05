# Task 02: SignalManager — Chain Container and Evaluator

**Phase:** 05 — Signals Logic  
**Depends on:** Task 01 (SignalChain)  
**Produces:** `signals_lib/signal_manager.py` — `SignalManager` class

---

## Goal

Implement `SignalManager` — container for multiple `SignalChain` objects. `check()` evaluates all chains per tick, returns list of completed action tuples, resets each completed chain.

---

## Files

- Modify: `signals_lib/signal_manager.py`

---

## Interface

**`SignalManager()`**

Attributes:
- `chains: list[SignalChain]` — all registered chains

Methods:
- `add_chain(chain: SignalChain) -> None` — appends chain to `self.chains`
- `check(data_point, levels, cur_time: float, action) -> list` — evaluates ALL chains; for each completed chain: appends `chain.get_action(data_point.get("close", 1, 0), action)` to results list and calls `chain.reset(action)`; returns accumulated results list

---

## Return Value Format

Each element of the returned list is a 4-element list:
```
[result_action: int, tf: int, price: float, data_dict: dict]
```

Where `data_dict` contains `{"position_time": tf, ...signal_data...}`.

---

## Evaluation Loop Logic

```
actions = []
for chain in self.chains:
    chain.check(data_point, levels, cur_time, action)
    if chain.completed(data_point, action):
        actions.append(chain.get_action(current_close_price, action))
        chain.reset(action)
return actions
```

`current_close_price` = `data_point.get("close", 1, 0)` — 1-min close at current tick.

---

## Key Constraints

- ALL chains are evaluated every tick — even chains with `cur_pos=0`
- After completion, chain is IMMEDIATELY reset via `chain.reset(action)` — it can start again next tick
- Multiple chains can complete in the same tick — all their actions are returned
- `data_point.get("close", 1, 0)` for the price in `get_action()` — always 1-min current close
- Returns empty list `[]` when no chains complete — normal case for most ticks
- Chains with `notify=False` still complete and return actions — just without logging

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from signals_lib.signal_manager import SignalChain, SignalManager
from signals_lib.common import Greater_Val_Signal
from constants import STRATEGY_ACTION_OPEN_LONG, STRATEGY_ACTION_OPEN_SHORT
from data import LiveDataPoint
import pandas as pd

mgr = SignalManager()
chain1 = SignalChain('long', STRATEGY_ACTION_OPEN_LONG, tf=15)
chain1.add(Greater_Val_Signal(15, 'rsi_14', 50))
chain2 = SignalChain('short', STRATEGY_ACTION_OPEN_SHORT, tf=15)
chain2.add(Greater_Val_Signal(15, 'rsi_14', 70))
mgr.add_chain(chain1)
mgr.add_chain(chain2)

df = pd.DataFrame({'15_rsi_14': [60.0], '1_close': [20.0]})
pt = LiveDataPoint({15: df, 1: df})
results = mgr.check(pt, {}, 1000.0, None)

# chain1 fires (60 > 50), chain2 does not (60 < 70)
assert len(results) == 1
assert results[0][0] == STRATEGY_ACTION_OPEN_LONG
print('signal manager ok')
"
```

---

## Commit

`feat: implement SignalManager — multi-chain evaluation and completion handling`
