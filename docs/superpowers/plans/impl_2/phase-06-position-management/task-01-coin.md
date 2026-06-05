# Task 01: Coin — Currency Tracker

**Phase:** 06 — Position Management  
**Depends on:** Phase 00 (constants)  
**Produces:** `position/coin.py` — lightweight data structure tracking one currency leg within a position

---

## Goal

Implement `Coin` — tracks available, used, returned, borrowed, and pending amounts for a single currency within an open position. Serializes to/from dict for position persistence.

---

## Files

- Create: `position/coin.py`
- Create: `position/__init__.py` (empty)

---

## Interface

**`Coin(name: str)`**

Attributes:
- `name: str` — currency name (e.g., `"usdt"`, `"link"`)
- `size: float = 0.0` — available amount currently held
- `used: float = 0.0` — amount deployed/committed in current action
- `returned: float = 0.0` — amount recovered from fills
- `loan: float = 0.0` — amount borrowed on margin
- `want_to_use: float = 0.0` — intended allocation for position opening
- `action_amount: float = 0.0` — amount pending in current order (set before placing order)

Methods:
- `log() -> None` — prints current state of all attributes with label
- `to_dict() -> dict` — serializes all attributes to JSON-compatible dict
- `from_dict(data: dict) -> None` — restores all attributes from dict (in-place update)
- `reset() -> None` — sets all amounts to 0.0 (keeps `name`)

---

## Key Constraints

- All amounts are `float` — never `int`
- `to_dict()` / `from_dict()` must be symmetric — `from_dict(to_dict())` restores exact state
- `reset()` sets numeric fields to 0.0 but preserves `name` — called during `position.finalize()`
- `action_amount` is set by `BasePosition` before each order placement; cleared after fill

---

## Verification

```bash
docker compose run --rm trainer python3 -c "
from position.coin import Coin
c = Coin('usdt')
c.size = 1000.0
c.used = 500.0
c.action_amount = 250.0
d = c.to_dict()
c2 = Coin('usdt')
c2.from_dict(d)
assert c2.size == 1000.0
assert c2.used == 500.0
assert c2.action_amount == 250.0
c.reset()
assert c.size == 0.0
assert c.name == 'usdt'
print('Coin ok')
"
```

---

## Commit

`feat: implement Coin currency tracker with serialization`
