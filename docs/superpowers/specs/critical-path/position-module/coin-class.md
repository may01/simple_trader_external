# Coin Class Specification

## 1. Class Overview

The `Coin` class tracks the lifecycle of a single currency (coin) amount throughout a trade execution. Its primary purpose is to account for how an initial amount of currency is deployed, used, borrowed (for margin trading), and eventually returned. The Coin class provides granular tracking across multiple dimensions: the total size of the currency available, the portion already committed to trade, loan amounts for margin positions, and returned portions from executed trades.

The Coin class serves as a fundamental building block in the Position subsystem. Positions require two Coin instances—one for the "use" side (typically the base currency like USDT for long trades, or the asset like ETH for short trades) and one for the "get" side (the opposite currency). This dual-coin design enables the Position and BasePosition classes to accurately track both entry and exit legs of a trade, accounting for fees, partial fills, and graduated entry/exit strategies where multiple tranches of a position are opened or closed at different prices.

The class is used internally by Position and BasePosition to manage graduated entry/exit scenarios where a trader might buy (or sell) in multiple price levels, using different amounts at each level. The Coin class ensures that the total deployed amount never exceeds available size, that loans are tracked separately from ownership, and that returned amounts are properly accounted for in final P&L calculations.

## 2. Key Attributes

| Attribute | Type | Description | Initial Value | Constraints |
|-----------|------|-------------|----------------|-------------|
| `name` | str | Human-readable name of the coin (e.g., "BTC", "USDT", "ETH") | "" (empty string) | Optional; used for logging |
| `size` | float | Total amount of the coin available for the trade | 0.0 | Must be ≥ 0; increased by add_size() |
| `loan` | float | Total amount of coin borrowed for margin trading | 0.0 | Must be ≥ 0; set by set_loan() |
| `want_to_use` | float | Desired amount to deploy in the trade (before actual deployment) | 0.0 | 0 ≤ want_to_use ≤ size (validated) |
| `used` | float | Amount of coin already deployed/committed in the trade | 0.0 | 0 ≤ used ≤ size; incremented by use_coin() |
| `returned` | float | Amount of coin received back from trade execution (or repaid on loan) | 0.0 | 0 ≤ returned ≤ used (for long), 0 ≤ returned ≤ loan (for short) |
| `action_amount` | float | Amount targeted for a specific action (entry, exit, or profit-taking level) | 0.0 | Typically set to size for complete exit or partial amounts for profit-taking |

## 3. Constructor

### `__init__()`

**Purpose:** Initialize a new Coin instance with zero values across all tracking attributes.

**Signature:**
```python
def __init__(self):
```

**Parameters:** None

**Return Type:** None

**Initialization:**
- `name`: Set to empty string ""
- `size`: Set to 0.0
- `loan`: Set to 0.0
- `want_to_use`: Set to 0.0
- `used`: Set to 0.0
- `returned`: Set to 0.0
- `action_amount`: Set to 0.0

**Postconditions:**
- Instance is ready to track a coin's lifecycle through a trade
- All counters start at zero, awaiting first calls to add_size(), use_coin(), or set_loan()
- No memory of prior trades (stateless across instances)

**Exceptions:** None

**Usage Example:**
```python
coin = Coin()  # Create new tracking instance
coin.size = 100.0  # Set initial amount (or use external setter)
coin.use_coin(25.0)  # Begin graduated entry: use 25 units
```

## 4. Key Methods & Interfaces

### 4.1 `add_size(amount)`

**Purpose:** Increase the total amount of coin available for trading (used for extending positions or adding funds).

**Signature:**
```python
def add_size(self, amount):
```

**Parameters:**
- `amount` (float): Positive amount to add to total size

**Preconditions:**
- `amount > 0`
- Instance has been initialized

**Return Type:** None

**Postconditions:**
- `self.size` increased by `amount`
- `used` and other tracking attributes remain unchanged
- Available amount (size - used) increases accordingly

**Exceptions:**
- `ValueError` (recommended): If amount ≤ 0, raise error with message: "Cannot add non-positive amount to coin size"

**Implementation Pattern:**
```python
def add_size(self, amount):
    if amount <= 0:
        raise ValueError("Cannot add non-positive amount to coin size")
    self.size += amount
```

---

### 4.2 `use_coin(amount)`

**Purpose:** Mark a portion of the coin as deployed/committed in the trade. This is called during graduated entry when opening positions in tranches.

**Signature:**
```python
def use_coin(self, amount):
```

**Parameters:**
- `amount` (float): Amount of coin to deploy/use in the trade

**Preconditions:**
- `amount > 0`
- `amount ≤ self.get_available()` (cannot use more than available)
- Instance must have size ≥ amount

**Return Type:** bool (True if successful, False if insufficient available)

**Postconditions:**
- `self.used` increased by `amount`
- Available amount decreases by `amount`
- Invariant maintained: `used ≤ size`

**Exceptions:**
- `ValueError` (recommended): If amount ≤ 0, raise error
- Returns False (or raises) if amount > available

**Implementation Pattern:**
```python
def use_coin(self, amount):
    available = self.get_available()
    if amount <= 0:
        raise ValueError("Cannot use non-positive amount")
    if amount > available:
        return False  # or raise InsufficientFundsError
    self.used += amount
    return True
```

**Usage Example (Graduated Entry):**
```python
coin = Coin()
coin.size = 100.0

coin.use_coin(25.0)   # Open 25% at price level 1
coin.use_coin(25.0)   # Open 25% at price level 2
coin.use_coin(50.0)   # Open remaining 50% at price level 3
# Now coin.used = 100.0, all size deployed
```

---

### 4.3 `return_coin(amount)`

**Purpose:** Mark a portion of the deployed coin as returned/received from trade execution. Called during graduated exit when closing positions in tranches or taking profits at multiple levels.

**Signature:**
```python
def return_coin(self, amount):
```

**Parameters:**
- `amount` (float): Amount of coin returned from trade execution

**Preconditions:**
- `amount > 0`
- `amount ≤ (self.used - self.returned)` (cannot return more than already deployed)
- Instance must be in used state (used > 0)

**Return Type:** bool (True if successful, False if invalid)

**Postconditions:**
- `self.returned` increased by `amount`
- Invariant maintained: `returned ≤ used`

**Exceptions:**
- `ValueError` (recommended): If amount ≤ 0
- Returns False if amount exceeds unrepaid used amount

**Implementation Pattern:**
```python
def return_coin(self, amount):
    outstanding = self.used - self.returned
    if amount <= 0:
        raise ValueError("Cannot return non-positive amount")
    if amount > outstanding:
        return False  # Exceeds deployed amount
    self.returned += amount
    return True
```

**Usage Example (Graduated Exit - Profit Taking):**
```python
coin = Coin()
coin.size = 100.0
coin.use_coin(100.0)  # All size deployed

coin.return_coin(30.0)  # Close 30% at profit target 1
coin.return_coin(30.0)  # Close 30% at profit target 2
coin.return_coin(40.0)  # Close final 40% at stop-loss or target 3
# Now coin.returned = 100.0, position fully closed
```

---

### 4.4 `set_loan(amount)`

**Purpose:** Record borrowed amount for margin trading (short positions). Sets the total loan received.

**Signature:**
```python
def set_loan(self, amount):
```

**Parameters:**
- `amount` (float): Total amount of coin borrowed for the position

**Preconditions:**
- `amount ≥ 0`
- Called before or at position setup
- Typically used for short positions where coin is borrowed and sold

**Return Type:** None

**Postconditions:**
- `self.loan` set to `amount`
- Available coin increases (loan is added to accessible funds)
- Loan repayment tracking initialized

**Exceptions:**
- `ValueError` (recommended): If amount < 0

**Implementation Pattern:**
```python
def set_loan(self, amount):
    if amount < 0:
        raise ValueError("Loan amount cannot be negative")
    self.loan = amount
```

**Usage Example (Short Position with Margin):**
```python
coin = Coin()  # This is the coin being shorted (e.g., ETH)
coin.size = 0.0  # No owned ETH initially
coin.set_loan(50.0)  # Borrow 50 ETH to sell

coin.use_coin(50.0)  # Sell 50 ETH (from borrowed amount)
# Now position is open: borrowed 50, sold 50
```

---

### 4.5 `set_repay(amount)`

**Purpose:** Record repayment of borrowed coin. Called from position.finalize() or during loan settlement when closing short positions.

**Signature:**
```python
def set_repay(self, amount):
```

**Parameters:**
- `amount` (float): Amount of loan being repaid

**Preconditions:**
- `amount > 0`
- `amount ≤ (self.loan - current_repaid)` (cannot repay more than borrowed)
- `self.loan > 0` (must have active loan)

**Return Type:** bool (True if successful, False if exceeds loan)

**Postconditions:**
- Repayment tracked (implementation may use separate `repaid` counter or reduce `loan`)
- Loan balance decreases, reflecting partial or full settlement
- Invariant maintained: repaid ≤ loan

**Exceptions:**
- `ValueError` (recommended): If amount ≤ 0
- Returns False if repayment exceeds outstanding loan

**Implementation Pattern:**
```python
def set_repay(self, amount):
    # Assuming internal tracking of total repaid
    if amount <= 0:
        raise ValueError("Repay amount must be positive")
    outstanding = self.loan - self.repaid if hasattr(self, 'repaid') else self.loan
    if amount > outstanding:
        return False
    if not hasattr(self, 'repaid'):
        self.repaid = 0
    self.repaid += amount
    return True
```

**Usage Example (Short Position Closure):**
```python
coin = Coin()
coin.set_loan(50.0)  # Borrow 50 ETH
coin.use_coin(50.0)  # Sell 50 ETH at $1000
coin.return_coin(35.0)  # Buy back 35 ETH at $900 (profit on 35)

# Later, closing remainder
coin.return_coin(15.0)  # Buy back remaining 15 ETH at $950
coin.set_repay(50.0)  # Repay the full loan

# P&L calculation: position closed, loan repaid
```

---

### 4.6 `get_loan()`

**Purpose:** Return the remaining loan balance (amount still owed). Useful for P&L calculations and position status checks.

**Signature:**
```python
def get_loan(self):
```

**Parameters:** None

**Preconditions:** Instance initialized

**Return Type:** float

**Returns:** Current outstanding loan amount. If repayments have been made, returns `loan - repaid` (or 0 if fully repaid).

**Postconditions:** No state change; read-only operation.

**Exceptions:** None

**Implementation Pattern:**
```python
def get_loan(self):
    if not hasattr(self, 'repaid'):
        return self.loan
    outstanding = self.loan - self.repaid
    return max(0.0, outstanding)  # Ensure non-negative
```

**Usage Example:**
```python
coin = Coin()
coin.set_loan(100.0)
coin.set_repay(30.0)

remaining = coin.get_loan()  # Returns 70.0
print(f"Still owe: {remaining} units")
```

---

### 4.7 `get_available()`

**Purpose:** Calculate the amount of coin available for next tranche or deployment. Available = size - used (not including fees in base implementation).

**Signature:**
```python
def get_available(self):
```

**Parameters:** None

**Preconditions:** Instance initialized

**Return Type:** float

**Returns:** `self.size - self.used`. For margin positions, may include loan amount.

**Postconditions:** No state change; read-only operation.

**Exceptions:** None

**Implementation Pattern:**
```python
def get_available(self):
    return self.size - self.used
```

**Usage Example:**
```python
coin = Coin()
coin.size = 100.0
coin.use_coin(30.0)

available = coin.get_available()  # Returns 70.0
print(f"Can deploy {available} more units")
```

---

### 4.8 `is_all_used()`

**Purpose:** Check if all available size has been deployed. Boolean predicate for graduated entry completion.

**Signature:**
```python
def is_all_used(self):
```

**Parameters:** None

**Preconditions:** Instance initialized

**Return Type:** bool

**Returns:** True if `self.used >= self.size`, False otherwise.

**Postconditions:** No state change; read-only operation.

**Exceptions:** None

**Implementation Pattern:**
```python
def is_all_used(self):
    return self.used >= self.size
```

**Usage Example:**
```python
coin = Coin()
coin.size = 100.0

coin.use_coin(50.0)
print(coin.is_all_used())  # False

coin.use_coin(50.0)
print(coin.is_all_used())  # True
```

---

### 4.9 `is_loan_repaid()`

**Purpose:** Check if all borrowed coin has been repaid. Boolean predicate for short position closure validation.

**Signature:**
```python
def is_loan_repaid(self):
```

**Parameters:** None

**Preconditions:** Instance initialized (may have active loan)

**Return Type:** bool

**Returns:** True if loan is fully repaid (repaid ≥ loan), False otherwise. Returns True if no loan was taken.

**Postconditions:** No state change; read-only operation.

**Exceptions:** None

**Implementation Pattern:**
```python
def is_loan_repaid(self):
    if self.loan == 0:
        return True  # No loan, so it's "repaid"
    if not hasattr(self, 'repaid'):
        return False  # Loan exists but not tracked as repaid yet
    return self.repaid >= self.loan
```

**Usage Example:**
```python
coin = Coin()
coin.set_loan(50.0)

print(coin.is_loan_repaid())  # False

coin.set_repay(50.0)
print(coin.is_loan_repaid())  # True
```

---

## 5. Loan Management

### Overview

Loan management is a critical subsystem of the Coin class, enabling margin trading for short positions. When a trader initiates a short position, the broker lends cryptocurrency (recorded via `set_loan()`), the trader sells it (recorded via `use_coin()`), and must later repay the loan (recorded via `set_repay()`).

### Loan Lifecycle

1. **Loan Initialization**: `set_loan(amount)` records the borrowed amount at position entry.
2. **Usage**: `use_coin(amount)` tracks the deployed/sold portion of the loan.
3. **Partial Closure**: `return_coin(amount)` records coin repurchased and available for repayment.
4. **Repayment**: `set_repay(amount)` records actual repayment to the broker.
5. **Completion**: `is_loan_repaid()` verifies full repayment before position is closed.

### Invariants

- **Loan Non-Negativity**: `loan ≥ 0` always.
- **Repayment Bound**: `repaid ≤ loan` (cannot repay more than borrowed).
- **Used-to-Loan Alignment**: For short positions, `used ≤ loan` (cannot sell more than borrowed).
- **Outstanding Loan**: `outstanding = loan - repaid ≥ 0`.

### Fee Integration

Fees are typically deducted during repayment or usage calculation, not stored separately in the Coin class. The base implementation hardcodes `fee = 0.002` (0.2%) in BasePosition. Future versions may enhance Coin to forecast or deduct fees.

### Example: Short Position with Graduated Closure

```python
# Setup: short BTC-USD pair
btc_coin = Coin()  # Coin being shorted
usdt_coin = Coin()  # Coin being used (proceeds)

btc_coin.set_loan(0.5)  # Borrow 0.5 BTC at current price
btc_coin.use_coin(0.5)  # Sell 0.5 BTC
usdt_coin.size = 20000  # Receive ~$20,000 in proceeds

# Close position in tranches
btc_coin.return_coin(0.2)  # Buy back 0.2 BTC at lower price (profit)
btc_coin.return_coin(0.3)  # Buy back 0.3 BTC at lower price

# Finalize position
btc_coin.set_repay(0.5)  # Repay full loan to broker
assert btc_coin.is_loan_repaid()  # Verify repayment complete
```

---

## 6. Usage Tracking

### Overview

Usage tracking enables graduated entry and exit strategies where a position is opened or closed across multiple price levels. Rather than committing all capital at once, traders can deploy tranches at different prices to optimize entry/exit.

### Graduated Entry

During a graduated entry, `use_coin()` is called multiple times with different amounts:

```python
coin = Coin()
coin.size = 1000.0  # Total USDT available

# Graduated buy of ETH across three levels
coin.use_coin(250.0)   # Buy at $1900
coin.use_coin(350.0)   # Buy at $1850
coin.use_coin(400.0)   # Buy at $1800
# Total deployed: $1000, avg entry lower than first price
```

### Graduated Exit (Profit Taking)

During a graduated exit, `return_coin()` is called to lock in profits at multiple levels:

```python
eth_coin = Coin()
eth_coin.size = 0.5  # 0.5 ETH from graduated entry

eth_coin.return_coin(0.15)  # Sell 0.15 ETH at $2100 (profit)
eth_coin.return_coin(0.2)   # Sell 0.2 ETH at $2200 (more profit)
eth_coin.return_coin(0.15)  # Sell 0.15 ETH at $2300 (final profit)
# All 0.5 ETH sold, position closed
```

### Invariants

- **Graduated Entry**: `used ≤ size` (cannot deploy more than available).
- **Graduated Exit**: `returned ≤ used` (cannot return more than deployed).
- **Atomic Integrity**: Each use_coin() and return_coin() call is atomic; partial failures should reject the entire operation.

### State Transitions

```
Initial State:  size=X, used=0, returned=0
    ↓
Entry Tranche 1: size=X, used=A, returned=0
    ↓
Entry Tranche 2: size=X, used=A+B, returned=0
    ↓
Exit Tranche 1: size=X, used=A+B, returned=C
    ↓
Exit Tranche 2: size=X, used=A+B, returned=C+D
    ↓
Final State:    size=X, used=A+B, returned=A+B (fully closed)
```

---

## 7. Fee Handling

### Overview

Fees impact available amounts and must be accounted for in position sizing. The current implementation assumes a fixed fee of 0.002 (0.2%) hardcoded in BasePosition and robot classes. The Coin class itself does not explicitly deduct fees; instead, higher-level Position and BasePosition classes manage fee logic.

### Current Approach

1. **Fee Parameter**: BasePosition.fee = 0.001 (0.2%)
2. **Fee Deduction Points**:
   - During use_coin(): Available amount is typically pre-reduced by expected entry fees.
   - During return_coin(): Exit fees may be pre-deducted from proceeds.
   - During set_repay(): Loan repayment may include interest (not currently implemented).

3. **Available Amount Calculation**: 
   - Simplistic: `available = size - used` (does not pre-reserve for fees).
   - Advanced (potential): `available = (size - fee*size) - used` (pre-reserve fees).

### Fee Tracking

Both entry and exit fees should be tracked for final P&L:

```python
# Example (pseudo-code for future enhancement):
coin.entry_fee = 0.0     # Fees paid on entry
coin.exit_fee = 0.0      # Fees paid on exit
coin.total_fee = 0.0     # Sum of all fees
```

### Example with Fees

```python
coin = Coin()
coin.size = 100.0

# Deploy 100 USD with expected 0.2% entry fee
amount_to_use = 100.0
expected_fee = amount_to_use * 0.002  # $0.20
coin.use_coin(amount_to_use)
# Net deployed: $99.80 (including fee)

# Close at 2% profit
amount_returned = 99.80 * 1.02  # $101.80
exit_fee = amount_returned * 0.002  # $0.20
coin.return_coin(101.60)  # After exit fee
# Net proceeds: $101.40
# Gross P&L: $101.40 - $100 = +$1.40 (+1.4%)
```

### Potential Enhancements

Fee handling can be enhanced with:
- Pre-fee calculation before use_coin() is called.
- Interest accrual on margin loans (set_loan() → interest cost).
- Partial fee tracking per tranche (graduated entry fee breakdown).

---

## 8. Error Handling

### Validation Strategy

The Coin class should validate inputs to prevent invalid state transitions. Key error conditions:

### 8.1 Attempting to Use More Than Available

**Condition**: `use_coin(amount)` called with `amount > get_available()`

**Handling**:
```python
def use_coin(self, amount):
    if amount > self.get_available():
        raise ValueError(f"Cannot use {amount}; only {self.get_available()} available")
    self.used += amount
```

**Mitigation**: Check available before calling use_coin(); validate in caller.

---

### 8.2 Negative Amounts

**Condition**: `use_coin(amount)`, `return_coin(amount)`, `add_size(amount)`, `set_loan(amount)`, or `set_repay(amount)` called with `amount < 0`

**Handling**:
```python
def use_coin(self, amount):
    if amount < 0:
        raise ValueError("use_coin() amount must be non-negative")
    if amount == 0:
        return True  # No-op, but allowed
    if amount > self.get_available():
        raise ValueError(f"Insufficient available: {self.get_available()}")
    self.used += amount
```

**Mitigation**: Pre-validate all inputs; use type hints if using modern Python.

---

### 8.3 Loan Repayment Exceeding Loan Amount

**Condition**: `set_repay(amount)` called with `amount > loan - repaid`

**Handling**:
```python
def set_repay(self, amount):
    if amount < 0:
        raise ValueError("Repay amount must be non-negative")
    outstanding = self.loan - getattr(self, 'repaid', 0)
    if amount > outstanding:
        raise ValueError(f"Repay {amount} exceeds outstanding {outstanding}")
    if not hasattr(self, 'repaid'):
        self.repaid = 0
    self.repaid += amount
```

**Mitigation**: Track repaid separately; check before processing repayment.

---

### 8.4 Loan Repayment Sequence (Out-of-Order)

**Condition**: `set_repay()` called multiple times, but repayment order is violated or inconsistent.

**Current Implementation**: Simple additive repayment (no ordering constraint). Future versions may require sequential repayment matching specific tranches.

**Mitigation**: Document that repayment is order-independent (FIFO-like but logical, not temporal). If order matters, implement queue-based tracking.

---

## 9. Existing Approach

### Simple Design Philosophy

The current Coin class follows a minimal, straightforward design:

1. **Counters, Not State Machines**: Attributes are simple numeric counters (size, used, returned, loan). No complex state objects.
2. **Immutable Loan Setup**: Once set_loan(amount) is called, loan amount is fixed. No interest accrual or dynamic loan changes.
3. **Linear Tracking**: used and returned are monotonically increasing (never decrease).
4. **No Fee Forecasting**: Coin does not pre-calculate or reserve fees; higher-level Position classes handle fee logic.
5. **Basic Serialization**: to_dict() and from_dict() enable pickling for backtesting checkpoints.

### Attributes Summary

| Attribute | Purpose | Current Behavior |
|-----------|---------|-------------------|
| `name` | Logging label | Set externally; informational only |
| `size` | Total available | Mutable; set externally or via add_size() |
| `loan` | Borrowed amount | Set once at margin position setup |
| `want_to_use` | Desired deployment (planning) | Set externally; used for validation |
| `used` | Deployed amount (committed) | Incremented by use_coin(); monotonic |
| `returned` | Received/closed amount | Incremented by return_coin(); monotonic |
| `action_amount` | Current action target | Set for specific exit/entry amount |

### No Fee Tracking in Coin

Fees are managed at the BasePosition/Position level:
- BasePosition.fee = 0.001 (0.2%)
- Fee deductions happen during record_entry_fill(), record_exit_fill(), finalize() in Position subclasses.
- Coin class remains agnostic to fee calculations.

### No Interest Calculation on Loans

Margin loans do not accrue interest in the current implementation:
- set_loan(amount) → records static loan amount.
- Loan repayment is simple: repay amount ≤ loan, tracked additively.
- No interest rate, maturity, or time-based cost tracking.

---

## 10. Potential Improvements

The following enhancements could extend Coin functionality without breaking existing code:

1. **Fee Forecasting Before Usage**
   - Add method `get_cost_with_fees(amount)` to calculate total cost including entry and exit fees.
   - Enables accurate position sizing before use_coin() is called.
   - Example: `usdt_coin.get_cost_with_fees(1000.0)` → returns 1004.0 (1000 + 0.4% fees).

2. **Interest Rate on Margin Loans**
   - Add attribute `interest_rate` and method `accrue_interest(time_elapsed)` to track interest cost.
   - Useful for realistic margin trading backtesting.
   - Example: Loan of 100 BTC at 5% annual → 100 * 0.05 / 365 per day.

3. **Partial Fee Calculation Per Tranche**
   - Track fees separately for each use_coin() or return_coin() tranche.
   - Enables per-tranche P&L reporting and fee analysis.
   - Example: `coin.use_coin_with_fee(100.0, fee=0.2)` → tracks 100 used, 0.2 fee.

4. **Loan Tier Management**
   - Support different interest rates for different loan amounts (tiered pricing).
   - Example: First 50 BTC at 3%, next 50 BTC at 4%, beyond 100 BTC at 5%.
   - Enables realistic cost modeling for large trades.

5. **Automated Repayment Scheduling**
   - Add method `schedule_repayment(tranches)` to plan multi-step repayment matching exit prices.
   - Synchronizes loan repayment with position closure across multiple levels.
   - Ensures P&L accuracy when loan repayment is spread across exit tranches.

6. **Minimum Amount Validation**
   - Add pre-check for exchange minimums (e.g., Binance minimum order 10 USDT).
   - Method `validate_against_exchange_minimums()` ensures use_coin() doesn't request below minimums.

7. **Transaction History Audit Trail**
   - Maintain log of all use_coin(), return_coin(), set_repay() operations.
   - Enables debugging, transaction replay, and audit compliance.
   - Example: `coin.get_history()` → returns list of (timestamp, operation, amount).

8. **Loan Early Repayment Penalties**
   - Track early repayment penalties or bonuses.
   - Some exchanges incentivize early loan repayment; others charge penalties.

9. **Multi-Currency Coin Swaps**
   - Support swapping between different coin instances without explicit return/repay.
   - Useful for complex strategies involving multiple assets.

10. **Fractional Share Support**
    - Enhanced rounding and precision for fractional coins (e.g., satoshis for BTC).
    - Ensures no precision loss in calculations.

---

## 11. Serialization

The Coin class provides two methods for persistence (used in backtesting checkpoints and trade replay):

### `to_dict()`

**Purpose:** Convert Coin instance to dictionary for JSON serialization or pickling.

**Signature:**
```python
def to_dict(self):
```

**Returns:** Dictionary with keys: `name`, `size`, `loan`, `want_to_use`, `used`, `returned`, `action_amount`.

**Usage:**
```python
coin = Coin()
coin.size = 100.0
coin.used = 50.0

dict_repr = coin.to_dict()
# {'name': '', 'size': 100.0, 'loan': 0.0, 'want_to_use': 0.0, 'used': 50.0, 'returned': 0.0, 'action_amount': 0.0}
```

---

### `from_dict(dict)`

**Purpose:** Restore Coin instance from dictionary (inverse of to_dict()).

**Signature:**
```python
def from_dict(self, dict):
```

**Parameters:**
- `dict` (dict): Dictionary with keys matching to_dict() output.

**Returns:** self (for method chaining)

**Postconditions:** All attributes restored from dictionary.

**Usage:**
```python
coin = Coin()
dict_repr = {'name': 'BTC', 'size': 1.0, 'loan': 0.5, ...}
coin.from_dict(dict_repr)

assert coin.name == 'BTC'
assert coin.size == 1.0
```

---

## 12. Integration with Position System

The Coin class is used within the Position subsystem as follows:

### In BasePosition

```python
def do_init(self):
    self.coinUse = Coin()   # Tracks usage side (e.g., USDT for long)
    self.coinGet = Coin()   # Tracks receipt side (e.g., ETH for long)
```

### Graduated Entry (Long Position)

1. Strategy signals buy → Position.open() called.
2. First tranche: `self.coinUse.use_coin(amount_1)` → marks USDT deployed.
3. Second tranche: `self.coinUse.use_coin(amount_2)` → marks more USDT deployed.
4. When all deployed: `self.coinUse.is_all_used() == True`.

### Graduated Exit (Long Position Closing)

1. Strategy signals sell → Position.close() called.
2. Profit-taking level 1: `self.coinGet.return_coin(amount_1)` → marks ETH closed.
3. Profit-taking level 2: `self.coinGet.return_coin(amount_2)` → marks more ETH closed.
4. When all closed: `self.coinGet.returned == self.coinGet.used`.

### Short Position with Loan

1. Strategy signals short → BasePosition.open() called with margin.
2. Loan setup: `self.coinUse.set_loan(amount)` → borrows ETH.
3. Sell tranches: `self.coinUse.use_coin(amount_i)` → sells borrowed ETH.
4. Buy-back tranches: `self.coinUse.return_coin(amount_i)` → repurchases ETH.
5. Loan closure: `self.coinUse.set_repay(total_borrowed)` → repays loan to broker.
6. Verification: `self.coinUse.is_loan_repaid()` → confirms all debt settled.

### P&L Calculation in finalize()

```python
def finalize(self):
    if self.state == POSITION_STATE_WAIT_SELL:  # Long
        revenue_abs = self.coinGet.returned - self.coinGet.used
        # P&L = coins returned - coins used (before fees)
    
    if self.state == POSITION_STATE_WAIT_BUY:  # Short
        revenue_abs = avg_price_open * (self.coinUse.returned - self.coinUse.used)
        # P&L = price change * quantity (short logic)
```

---

## Appendix: Reference Implementation

Below is the complete source code of the Coin class as of this specification:

```python
class Coin:

  def __init__(self):
    self.name = ""
    self.size = 0.0
    self.loan = 0.0    
    self.want_to_use = 0.0
    self.used = 0.0
    self.returned = 0.0 
    self.action_amount = 0.0

  def log(self):
    log("______________:")
    log("coin_name     : %s"%(self.name     ))
    log("coin_size     : %f"%(self.size     ))
    log("coin_loan     : %f"%(self.loan     ))
    log("coin_want_to_use     : %f"%(self.want_to_use     ))
    log("coin_used     : %f"%(self.used     ))
    log("coin_returned : %f"%(self.returned ))
    log("coin_action_amount : %f"%(self.action_amount ))
    log("______________:")

  def to_dict(self):
    return {
      "name" : self.name,
      "size" : self.size,
      "loan" : self.loan,
      "want_to_use" : self.want_to_use,
      "used" : self.used,
      "returned" : self.returned,
      "action_amount" : self.action_amount,
    }

  def from_dict(self, dict):
    self.name = dict["name"]
    self.size = dict["size"]
    self.loan = dict["loan"]
    self.want_to_use = dict["want_to_use"]
    self.used = dict["used"]
    self.returned = dict["returned"]
    self.action_amount = dict["action_amount"]
    return self
```

---

## Conclusion

The Coin class provides a minimal yet effective abstraction for tracking currency amounts through a trade lifecycle. Its simple counter-based design integrates seamlessly with the Position subsystem, enabling graduated entry/exit strategies and margin trading support. While the current implementation is deliberately simple—avoiding fee forecasting, interest calculation, and complex state management—the architecture supports future enhancements without requiring breaking changes to existing code. By maintaining clear invariants (used ≤ size, returned ≤ used, repaid ≤ loan) and providing atomic operations, Coin ensures data integrity across multi-tranche trades and loan management scenarios.
