# Strategy Class Specification

**Class:** `Strategy` (Base Abstract)  
**File:** `strategies/strategy.py`  
**Purpose:** Abstract base class defining the interface and common logic for all trading strategies  
**Scope:** Template method pattern for signal registration, condition checking, action selection, and price computation  

---

## 1. Class Overview

The `Strategy` class serves as the foundational template for all strategy implementations (ExampleStrategyLong, ExampleStrategyShort, NN strategies, etc.). It:
- Registers signal chains specific to each strategy type
- Evaluates market conditions to determine if strategy should execute
- Selects a single action from multiple signal results
- Computes entry, exit, and stop-loss prices based on current market state

**Design Pattern:** Template Method  
- Concrete strategies override abstract methods (`register_signals`, `check_conditions`, `process_actions`)
- Common flow (`check()`) calls overridable hooks at key decision points

**Trend filtering:** Trend is a Data layer concern. `trend_up` / `trend_down` boolean columns are pre-computed per timeframe in `data.py` (EMA alignment: `ema_25 > ema_50 > ema_100`). Strategies gate on trend by adding `BoolValue_Signal("trend_up", tf)` as a step inside the relevant signal chain — no separate trend infrastructure in Strategy.

---

## 2. Key Attributes

No class-level `fee` default — a strategy constructed without a fee must fail at construction, not silently use a stale constant.

### Instance Attributes
| Attribute | Type | Initialized | Purpose |
|-----------|------|-------------|---------|
| `name` | str | `__init__` | Strategy identifier (e.g., "ExampleStrategyLong") |
| `fee` | float | `__init__` | Taker fee rate — injected from `stock.item.fee` via StrategyManager; never hardcoded |
| `data` | Data | `__init__` + per-tick update | Current market data reference |
| `signals` | SignalManager | `__init__` | Container for all strategy signal chains |
| `levels` | dict | `__init__` | Support/resistance level dict (deprecated) |
| `state` | int | `__init__` | Internal state (STRATEGY_STATE_WAIT) |

---

## 3. Constructor

```python
def __init__(self, data, fee):
    """
    Initialize strategy with market data and fee structure.
    
    Parameters:
        data (Data): Current market data object
        fee (float): Trading fee (e.g., 0.001 for 0.1%)
    
    Behavior:
        1. Set name = "Base strategy!!!" (overridden in subclasses)
        2. Store fee and data references
        3. Create empty SignalManager for signal chains
        4. Initialize levels dict (deprecated)
        5. Set state to STRATEGY_STATE_WAIT
    """
    self.name = "Base starategy!!!"
    self.fee = fee
    self.data = data
    self.signals = SignalManager()
    self.levels = {}
    self.state = STRATEGY_STATE_WAIT
```

**Note:** Trend signals registered automatically; `register_signals()` not called in base constructor (must be called explicitly by subclasses or StrategyManager).

---

## 4. Abstract Methods (Override in Subclasses)

### 4.1 register_signals()
```python
def register_signals(self):
    """
    Register all signal chains specific to this strategy.
    
    Called once during initialization or explicitly by StrategyManager.
    Subclass must populate self.signals with SignalChain objects.
    
    Behavior:
        - Create signal chains for ENTRY signals (STRATEGY_ACTION_OPEN_LONG/SHORT)
        - Create signal chains for EXIT signals (STRATEGY_ACTION_CLOSE_LONG/SHORT)
        - Add chains to self.signals via self.signals.add_chain(chain)
        - May define signal constants (main_shift, tf) for reuse
    
    Example (from ExampleStrategyLong):
        chain = SignalChain("15 5 CCI -140 Cross UP", STRATEGY_ACTION_OPEN_LONG, 5, True)
        chain.add(And_Signal([...]))
        self.signals.add_chain(chain)
    
    Raises:
        AssertionError if not overridden in subclass (assert False)
    """
    assert(False)
```

### 4.2 check_conditions(data, position_state, action_msg)
```python
def check_conditions(self, data, position_state, action_msg):
    """
    Gate strategy execution based on market conditions and position state.
    
    Parameters:
        data (Data): Current market snapshot
        position_state (int): Current position state (POSITION_STATE_WAIT, POSITION_STATE_WAIT_SELL, etc.)
        action_msg (ActionMessage): Message object for logging/debugging
    
    Returns:
        bool: True if strategy should execute, False otherwise
    
    Purpose:
        Filter execution based on:
        - Position state (e.g., only execute long strategy if not already holding)
        - Market regime (e.g., only in uptrend)
        - Time-based conditions (e.g., not near market close)
    
    Example (from ExampleStrategyLong):
        if position_state != POSITION_STATE_WAIT_SAFETY_BUY and position_state != POSITION_STATE_WAIT_BUY:
            return True
        return False
    
    Raises:
        AssertionError if not overridden in subclass (assert False)
    
    Note: An earlier version of this signature included a `prediction` parameter
    for passing NN probabilities. That was a transitional experiment — the parameter
    has been removed. NN context belongs in StrategyManager, not check_conditions.
    """
    assert(False)
```

### 4.3 process_actions()
```python
def process_actions(self):
    """
    Process and prioritize actions when multiple signal chains fire.
    
    Returns:
        Reserved for future enhancement; currently deprecated.
    
    Raises:
        AssertionError if not overridden in subclass (assert False)
    """
    assert(False)
```

---

## 5. Key Methods

### 5.1 check(data, position_state, position_target, action_msg)
**Main Entry Point - Called Once Per Tick**

```python
def check(self, data, position_state, position_target, action_msg):
    """
    Evaluate strategy and return action + price levels.
    
    Parameters:
        data (Data): Current market data (OHLC, indicators)
        position_state (int): Current position state
        position_target (float): Position target price (if any)
        action_msg (ActionMessage): Message container for logging
    
    Returns:
        Tuple (action, open_price, close_price, stop_price, timeframe):
            - action (int): STRATEGY_ACTION_* constant (OPEN_LONG, CLOSE_LONG, NOTHING, etc.)
            - open_price (list[float]): Entry price(s) for OPEN actions
            - close_price (list[float]): Exit price(s) for CLOSE actions or targets
            - stop_price (float): Stop-loss price
            - timeframe (int): Recommended timeframe for order placement (minutes)
    
    Flow:
        1. Store data reference (self.data = data)
        2. Call get_level_values() to build price levels dict
        3. Add position_target to levels if provided
        4. Call check_chains() to evaluate SignalManager
        5. Call select_final_action() to prioritize results
        6. Compute open, close, stop-loss prices via get_open/close/stop_loss_price()
        7. Log results
        8. Return (action, open_price, close_price, stop_price, timeframe)
    
    Key Behaviors:
        - Levels include LONG_SUPPORT, LONG_RESISTANCE, SHORT_SUPPORT, SHORT_RESISTANCE
        - Position target added as LEVEL_TYPE_TARGET if provided
        - Signal evaluation done via SignalManager (self.signals.check())
        - Action selection prioritizes CLOSE > MOVE_STOP_LOSS > OPEN
        - If no action or multiple OPEN conflicts: returns NOTHING
    
    Example Return:
        (STRATEGY_ACTION_OPEN_LONG, [16.43], [16.57, 16.71, 16.86], 16.25, 5)
    """
    actions_list = {}
    self.data = data
    
    # Get level values (support, resistance, targets)
    levels = self.get_level_values(data.cur_point, data, action_msg)
    levels[LEVEL_TYPE_TARGET] = []
    if position_target != 0:
        action_msg.add_multiply_action(position_target, "CLOSE TGT")
        levels[LEVEL_TYPE_TARGET].append(position_target)
    
    # Evaluate signal chains
    actions_list = self.check_chains(data, levels, action_msg)
    
    # Select final action from chain results
    action, open_tf, close_tf, stop_loss_tf = self.select_final_action(actions_list, position_state, action_msg)
    
    # Compute prices (pass cur_data so methods use v2.0 DataPoint API, not self.data)
    open_price = self.get_open_price(action, open_tf, data, action_msg)
    close_price = self.get_close_price(action, close_tf, data, action_msg)
    stop_price = self.get_stop_loss_price(position_state, action, stop_loss_tf, data, action_msg)
    time_frame = close_tf

    # Validate risk/reward before surfacing an open action to the caller
    if action in (STRATEGY_ACTION_OPEN_LONG, STRATEGY_ACTION_OPEN_SHORT):
        if not self.validate_trade_risk(open_price, close_price, stop_price, action_msg):
            action = STRATEGY_ACTION_WAIT
    
    # Log and return
    log("strategy:check(): %d, %s, %s, %.4f, %d" % (action, str(open_price), str(close_price), stop_price, time_frame))
    return action, open_price, close_price, stop_price, time_frame
```

### 5.2 check_chains(data, levels, action_msg)
**Signal Chain Evaluation**

```python
def check_chains(self, data, levels, action_msg):
    """
    Delegate signal chain evaluation to SignalManager.
    
    Returns:
        List[tuple]: Each tuple is (action, timeframe, price, data) from SignalManager.check()
    
    Flow:
        1. Call self.signals.check(data, levels, action_msg)
        2. Return list of [action, tf, price, data] for each fired chain
    """
    actions_list = {}
    actions_list = self.signals.check(data, levels, action_msg)
    return actions_list
```

### 5.3 select_final_action(actions_list, position_state, action_msg)
**Action Prioritization**

```python
def select_final_action(self, actions_list, position_state, action_msg):
    """
    Select single action from multiple signal chain results.
    
    Parameters:
        actions_list (list): List of [action, tf] tuples from check_chains()
        position_state (int): Current position state
        action_msg (ActionMessage): Logging object
    
    Returns:
        Tuple (final_action, open_tf, close_tf, stop_loss_tf):
            - Each timeframe defaults to 15 if no match
    
    Priority Logic:
        1. If empty: return NOTHING, all tfs = 0
        2. If single action: accept it, use its timeframe
        3. If multiple actions:
            a. If POSITION_STATE_WAIT: accept first OPEN_LONG or OPEN_SHORT; skip others
            b. If holding position: prioritize CLOSE > MOVE_STOP_LOSS > others
            c. Skip MOVE_STOP_LOSS if in safety states (WAIT_SAFETY_SELL, WAIT_SAFETY_BUY)
            d. Accept first matching action in priority order
    
    Key Behaviors:
        - Returns NOTHING if multiple OPEN signals in WAIT state (avoid over-trading)
        - CLOSE signals are absolute priority (immediate break)
        - Timeframe extracted from matched action tuple
    
    Example:
        Input: [(STRATEGY_ACTION_OPEN_LONG, 5), (STRATEGY_ACTION_OPEN_SHORT, 15)]
        Position: POSITION_STATE_WAIT
        Output: (STRATEGY_ACTION_OPEN_LONG, 5, 5, 5)  # First match wins
    """
    final_action = STRATEGY_ACTION_NOTHING
    open_tf = 0
    close_tf = 0
    stop_loss_tf = 0
    
    if len(actions_list) == 1:
        final_action = actions_list[0][0]
        open_tf = actions_list[0][1]
    elif len(actions_list) > 1:
        log("multiply actions %s" % (str(actions_list)))
        for al in actions_list:
            select = al[0]
            if position_state == POSITION_STATE_WAIT:
                if select == STRATEGY_ACTION_OPEN_LONG or select == STRATEGY_ACTION_OPEN_SHORT:
                    final_action = select
                    break
            else:
                # Holding: prioritize CLOSE, then MOVE_STOP_LOSS
                if select in [STRATEGY_ACTION_CLOSE_LONG, STRATEGY_ACTION_CLOSE_SHORT, 
                              STRATEGY_ACTION_CLOSE_LONG_PART, STRATEGY_ACTION_CLOSE_SHORT_PART]:
                    final_action = select
                    break
                if select in [STRATEGY_ACTION_MOVE_STOP_LOSS_LONG, STRATEGY_ACTION_MOVE_STOP_LOSS_SHORT]:
                    if position_state not in [POSITION_STATE_WAIT_SAFETY_SELL, POSITION_STATE_WAIT_SAFETY_BUY]:
                        final_action = select
                        break
                final_action = select
    
    open_tf = tf_action_tf  # set in both single and multi-action branches; defaults to 15
    close_tf = open_tf
    stop_loss_tf = open_tf

    return final_action, open_tf, close_tf, stop_loss_tf
```

### 5.4 get_level_values(cur_point, data, action_msg)
**Build Support/Resistance Levels**

```python
def get_level_values(self, cur_point, data, action_msg):
    """
    Construct level dict from manual configuration and dynamic indicators.
    
    Returns:
        Dict with keys:
            - LEVEL_TYPE_LONG_SUPPORT: [prices]
            - LEVEL_TYPE_LONG_RESISTANCE: [prices]
            - LEVEL_TYPE_SHORT_SUPPORT: [prices]
            - LEVEL_TYPE_SHORT_RESISTANCE: [prices]
            - LEVEL_TYPE_TARGET: [prices]
            - LEVEL_TYPE_SHORT_1_RESISTANCE: [prices]
            - LEVEL_TYPE_SHORT_2_RESISTANCE: [prices]
    
    Dynamic Levels (Currently Active):
        - SHORT_1_RESISTANCE: EMA_50, EMA_100, BBU (upper band) @ 60, 240 min
        - SHORT_2_RESISTANCE: EMA_50, EMA_100, BBM (middle band) @ 15, 60, 240 min
    
    Note: Long support/resistance levels deprecated (commented out in source).
          Future enhancement: Load from manual configuration or DB.
    
    Returns all levels as price list; Near_Price_Level_Signal checks proximity.
    """
    levels = {
        LEVEL_TYPE_LONG_SUPPORT: [],
        LEVEL_TYPE_LONG_RESISTANCE: [],
        LEVEL_TYPE_SHORT_SUPPORT: [],
        LEVEL_TYPE_SHORT_RESISTANCE: [],
        LEVEL_TYPE_TARGET: [],
        LEVEL_TYPE_AUTO_TARGET_RESISTANCE: [],
        LEVEL_TYPE_AUTO_TARGET_SUPPORT: [],
        LEVEL_TYPE_SHORT_1_RESISTANCE: [],
        LEVEL_TYPE_SHORT_2_RESISTANCE: [],
    }
    
    # Populate SHORT_1_RESISTANCE and SHORT_2_RESISTANCE
    # (Other levels deprecated; to be refactored)
    
    return levels
```

### 5.5 get_open_price(action, tf, cur_data, action_msg)
**Compute Entry Price**

```python
def get_open_price(self, action, tf, cur_data, action_msg):
    """
    Compute entry price for position.
    
    Parameters:
        action (int): Action type (OPEN_LONG, OPEN_SHORT, CLOSE_*, MOVE_STOP_LOSS_*, etc.)
        tf (int): Timeframe (minutes)
        action_msg (ActionMessage): Logging object
    
    Returns:
        List[float]: Entry price(s) in a list (to support multiple entry points)
    
    Base Behavior:
        - For all actions: Return current close price as single-element list
        - Subclasses override for graduated entry or trend-adjusted pricing
    
    Example Override (ExampleStrategyLong):
        if action == STRATEGY_ACTION_OPEN_LONG:
            return [current_close]  # Single entry
    """
    price = [cur_data.get("close", 1)]
    return price
```

### 5.6 get_close_price(action, tf, cur_data, action_msg)
**Compute Exit Prices**

```python
def get_close_price(self, action, tf, cur_data, action_msg):
    """
    Compute exit price(s) for position (may be multiple tranches).
    
    Parameters:
        action (int): Action type
        tf (int): Timeframe (minutes)
        cur_data (DataPoint): Current tick data snapshot (v2.0 DataPoint API)
        action_msg (ActionMessage): Logging object
    
    Returns:
        List[float]: Exit price(s) (typically 1-3 targets for graduated exits)
    
    Base Behavior (primary: data-layer targets; fallback: fixed %):
        - STRATEGY_ACTION_OPEN_LONG:
            1. Try cur_data.get("tgt_long", tf) — statistically calibrated from diff_stats.pkl
            2. Fallback: entry_price * 1.008
        - STRATEGY_ACTION_OPEN_SHORT:
            1. Try cur_data.get("tgt_short", tf)
            2. Fallback: entry_price * (1.0 - 0.008)
        - STRATEGY_ACTION_NOTHING/CLOSE_*: Current close
    
    Data-layer targets available for tf ∈ {15, 60, 240, 1440}.
    For tf=1 or tf=5, cur_data.get() returns None and fallback is used automatically.
    
    Subclass Overrides (ExampleStrategyLong):
        - OPEN_LONG: Three targets at +0.8%, +1.6%, +2.4% (or data-layer equivalents)
        - CLOSE_LONG: Current close
    
    Note: Price list length determines number of execution tranches in robot.
    """
    price = []
    
    if action == STRATEGY_ACTION_OPEN_LONG:
        tgt = cur_data.get("tgt_long", tf)
        price = [tgt] if tgt is not None else [cur_data.get("close", 1) * 1.008]
    elif action == STRATEGY_ACTION_OPEN_SHORT:
        tgt = cur_data.get("tgt_short", tf)
        price = [tgt] if tgt is not None else [cur_data.get("close", 1) * (1.0 - 0.008)]
    else:
        price = [cur_data.get("close", 1)]
    
    return price
```

### 5.7 get_stop_loss_price(position_state, action, tf, cur_data, action_msg)
**Compute Stop-Loss Price**

```python
def get_stop_loss_price(self, position_state, action, tf, cur_data, action_msg):
    """
    Compute stop-loss price to limit losses on entry or adjust during holding.
    
    Parameters:
        position_state (int): Current position state
        action (int): Action type (determines which stop-loss rule applies)
        tf (int): Timeframe (minutes) for ATR calculation
        cur_data (DataPoint): Current tick data snapshot (v2.0 DataPoint API)
        action_msg (ActionMessage): Logging object
    
    Returns:
        float: Stop-loss price (single value)
    
    Base Logic for Entry (OPEN_LONG, OPEN_SHORT):
        Primary: Use data-layer computed stop (from diff_stats.pkl):
            - OPEN_LONG: cur_data.get("sl_long", tf)
            - OPEN_SHORT: cur_data.get("sl_short", tf)
        Fallback (when primary returns None, e.g. tf ∈ {1, 5}):
            1. Get SAR (Parabolic SAR) @ 5min via cur_data.get("sar", 5)
            2. Get ATR (Average True Range) @ specified timeframe via cur_data.get("atr", tf)
            3. For LONG: SL = SAR - 0.3*ATR; check for level support below; apply -0.2*ATR buffer
            4. For SHORT: SL = SAR + 0.3*ATR; check for level resistance above; apply +0.2*ATR buffer
    
    Logic for Trailing (MOVE_STOP_LOSS_LONG, MOVE_STOP_LOSS_SHORT):
        1. Only execute if not in safety state
        2. For LONG: SL = min(SAR_15, SAR_60) * 0.999 (trailing 0.1%)
        3. For SHORT: SL = max(SAR_15, SAR_60) * 1.001 (trailing 0.1%)
    
    Logic for Close (CLOSE_LONG, CLOSE_SHORT):
        1. Set SL to profit zone to trigger immediate close
        2. For LONG: min(SAR_5, SAR_15)
        3. For SHORT: max(SAR_5, SAR_15)
    
    Helper Method: find_level_in_range(tf, base, delta, direction)
        Searches for nearest EMA/Bollinger Band level within delta range
        Recursively climbs the level ladder (EMA_25 -> EMA_50 -> EMA_100 -> BBU/BBD)
    
    Subclass Overrides:
        ExampleStrategyShort.get_stop_loss_price():
            Custom for SHORT: max of last two 60-min closes + ATR for tighter stop
    """
    if action == STRATEGY_ACTION_OPEN_LONG:
        sl = cur_data.get("sl_long", tf)
        if sl is not None:
            return sl
        # Fallback: SAR ± ATR + level search
    
    if action == STRATEGY_ACTION_OPEN_SHORT:
        sl = cur_data.get("sl_short", tf)
        if sl is not None:
            return sl
        # Fallback: SAR ± ATR + level search
    
    price = cur_data.get("sar", 5)
    atr = cur_data.get("atr", tf)
    bot, top = price, price
    
    if action == STRATEGY_ACTION_OPEN_LONG:
        slp = bot - 0.3 * atr
        price = self.find_level_in_range(tf, slp, 0.3 * atr, TREND_DOWN) - 0.2 * atr
    
    if action == STRATEGY_ACTION_OPEN_SHORT:
        slp = top + 0.3 * atr
        price = self.find_level_in_range(tf, slp, 0.3 * atr, TREND_UP) + 0.2 * atr
    
    # Trailing stops (MOVE_STOP_LOSS)
    sar_5 = cur_data.get("sar", 5)
    sar_15 = cur_data.get("sar", 15)
    sar_60 = cur_data.get("sar", 60)
    
    if action == STRATEGY_ACTION_MOVE_STOP_LOSS_LONG:
        if position_state in [POSITION_STATE_WAIT_SAFETY_SELL, POSITION_STATE_WAIT_SELL]:
            price = min(sar_15, sar_60) * 0.999
    
    if action == STRATEGY_ACTION_MOVE_STOP_LOSS_SHORT:
        if position_state in [POSITION_STATE_WAIT_SAFETY_BUY, POSITION_STATE_WAIT_BUY]:
            price = max(sar_15, sar_60) * 1.001
    
    return price
```

### 5.8 find_level_in_range(tf, base, delta, direction)
**Level Proximity Search**

```python
def find_level_in_range(self, tf, base, delta, direction):
    """
    Recursively search for nearest support/resistance level within range.
    
    Parameters:
        tf (int): Timeframe (minutes)
        base (float): Reference price
        delta (float): Search range (price width)
        direction (int): TREND_UP (find level above) or TREND_DOWN (find level below)
    
    Returns:
        float: Final price after level adjustments
    
    Level Ladder (in order):
        - EMA_25, EMA_50, EMA_100, BBM (middle), BBU (upper), BBD (lower)
    
    Algorithm:
        1. Check each level against (base, base ± delta) range
        2. If level found in range: recursively search above/below it
        3. Return base if no level found
    
    Purpose:
        Move stop-loss to just beyond major technical levels (EMAs, Bollinger Bands)
        to avoid getting stopped out by minor noise while staying risk-aware.
    
    Example:
        find_level_in_range(15, 16.40, 0.10, TREND_DOWN)
        -> Searches for levels between 16.30-16.40 (lower range)
        -> Returns nearest EMA/BB below 16.40 (with recursion for tighter fit)
    """
    lvl_list = ['ema_25', 'ema_50', 'ema_100', BBU, BBM, BBD]
    for l in lvl_list:
        val = self.data.get_cur_price(l, 0, tf)
        if direction == TREND_UP:  # find level higher than base
            if val > base and val < base + delta:
                return self.find_level_in_range(tf, val, delta, direction)
        if direction == TREND_DOWN:  # find level lower than base
            if val < base and val > base - delta:
                return self.find_level_in_range(tf, val, delta, direction)
    
    return base
```

### 5.9 validate_trade_risk(open_price, close_price, stop_price, action_msg)
**Risk/Reward Gate — called by `check()` before surfacing an open action**

```python
def validate_trade_risk(self, open_price, close_price, stop_price, action_msg) -> bool:
    """
    Validate that computed prices form a tradeable risk/reward profile.

    Called in check() after all three prices are computed, only when action is
    OPEN_LONG or OPEN_SHORT. Returns False (and downgrades action to WAIT) if:
      - profit <= 0  (close_price on wrong side of open_price)
      - risk   <= 0  (stop_price on wrong side of open_price)
      - profit / risk < MIN_RISK_REWARD_RATIO

    Parameters:
        open_price (list[float]): Graduated entry prices (average used for ratio)
        close_price (list[float]): Target exit prices (average used for ratio)
        stop_price (float): Stop-loss price
        action_msg: Logging object (⚠ TO REFINE — see action_msg note)

    Returns:
        bool: True if risk/reward is acceptable, False otherwise
    """
    avg_open  = sum(open_price) / len(open_price)
    avg_close = sum(close_price) / len(close_price)

    if action == STRATEGY_ACTION_OPEN_LONG:
        profit = avg_close - avg_open
        risk   = avg_open - stop_price
    else:
        profit = avg_open - avg_close
        risk   = stop_price - avg_open

    if profit <= 0 or risk <= 0:
        return False
    return (profit / risk) >= self.MIN_RISK_REWARD_RATIO
```

`MIN_RISK_REWARD_RATIO` is a strategy-level constant (default `1.5`), loadable from `strategy_config.yaml`. Position never sees this check — by the time `open()` is called, prices are already validated.

---

### 5.10 Trend Gating Pattern
**How strategies use trend — via BoolValue_Signal**

Trend detection is a Data layer responsibility. `data.py` computes `trend_up` and `trend_down` as boolean columns per timeframe:

```python
# In data.py (Data layer — not Strategy):
ohlc[t]['trend_up']   = (ema_25 > ema_50) & (ema_50 > ema_100)
ohlc[t]['trend_down'] = (ema_25 < ema_50) & (ema_50 < ema_100)
```

Strategies add trend confirmation by including `BoolValue_Signal` as a gate in any signal chain:

```python
# In register_signals() — require uptrend before opening long:
chain = SignalChain("60m uptrend + CCI cross", STRATEGY_ACTION_OPEN_LONG, 5, True)
chain.add(And_Signal([
    BoolValue_Signal("trend_up", 60),          # Data layer trend gate
    History_Signal(Less_Val_Signal(5, "cci", -100), 1),
    History_Signal(Greater_Val_Signal(5, "cci", -100), 0),
]))
self.signals.add_chain(chain)
```

`BoolValue_Signal(col, tf)` reads `data.get_cur_price(col, shift, tf)` — the same accessor all other signals use. No separate trend infrastructure in Strategy is needed.

### 5.10 Helper Methods (Supporting Functions)

```python
def is_same_class_action(self, action1, action2):
    """Equality check for actions."""
    return action1 == action2
```

---

## 6. Price Defaults & Computation

### Entry Price (Open)
- **Default:** Current close price
- **ExampleStrategy:** Delegates to base class default (no override)

### Exit Price (Close)
- **Default:** +0.8% for LONG, -0.8% for SHORT
- **ExampleStrategy:** Delegates to base class default (no override) — single target, no tranches

### Stop-Loss Price
- **Default Computation:**
  - Base: SAR ± 0.3*ATR
  - Adjusted: Find nearest EMA/BB in range
  - Final: Apply -/+ 0.2*ATR buffer
- **Trailing:** SAR @ 15/60min with 0.1% safety shift
- **Close SL:** Set to profit zone (SAR 5/15) for immediate exit

---

## 7. State Machine

| State | Meaning | Behavior |
|-------|---------|----------|
| STRATEGY_STATE_WAIT | No position held | Evaluate OPEN signals; skip MOVE_STOP_LOSS |

---

## 8. Existing Code Patterns

### Signal Chain Construction
```python
chain = SignalChain("Name", STRATEGY_ACTION_OPEN_LONG, 5, True)
chain.add(And_Signal([
    History_Signal(Less_Val_Signal(tf, "cci", -140), 1),
    History_Signal(Greater_Val_Signal(tf, "cci", -140), 0),
    Near_Price_Level_Signal(15, "close", LEVEL_TYPE_LONG_SUPPORT, 0.2)
]))
self.signals.add_chain(chain)
```

### Trend Gating Pattern
```python
# Add BoolValue_Signal as a gate to require trend alignment before firing:
chain = SignalChain("uptrend + CCI cross", STRATEGY_ACTION_OPEN_LONG, 5, True)
chain.add(And_Signal([
    BoolValue_Signal("trend_up", 60),   # pre-computed in Data layer
    History_Signal(Less_Val_Signal(5, "cci", -100), 1),
    History_Signal(Greater_Val_Signal(5, "cci", -100), 0),
]))
self.signals.add_chain(chain)
```

### Price Computation Override Pattern
```python
def get_close_price(self, action, tf, action_msg):
    cur_price = self.data.get_cur_price("close", 0, 1)
    if action == STRATEGY_ACTION_OPEN_LONG:
        shift = 0.008
        return [cur_price * (1 + 1*shift), cur_price * (1 + 2*shift), cur_price * (1 + 3*shift)]
    return super().get_close_price(action, tf, action_msg)
```

---

## 9. Magic Numbers ⚠️ Pending Refactor

All values below are currently hardcoded in `strategy.py`. Each should be extracted to a named constant in a config file (e.g. `strategy_defaults.yaml` or `strategy_config.py`) so they can be tuned per-pair and per-regime without code changes.

| Constant name (proposed) | Current value | Location | What it controls |
|--------------------------|--------------|----------|-----------------|
| `SL_ATR_INITIAL_MULT` | `0.3` | `get_stop_loss_price` | ATR multiplier for initial SL placement: `SAR ± 0.3 × ATR` |
| `SL_ATR_LEVEL_BUFFER` | `0.2` | `get_stop_loss_price` | ATR buffer added beyond nearest level after `find_level_in_range`: `± 0.2 × ATR` |
| `SL_TRAIL_LONG_MULT` | `0.999` | `get_stop_loss_price` (MOVE_STOP_LOSS_LONG) | Trailing long stop safety shift: `min(SAR_15, SAR_60) × 0.999` (0.1% below SAR) |
| `SL_TRAIL_SHORT_MULT` | `1.001` | `get_stop_loss_price` (MOVE_STOP_LOSS_SHORT) | Trailing short stop safety shift: `max(SAR_15, SAR_60) × 1.001` (0.1% above SAR) |
| `SL_SAR_FALLBACK_TF` | `5` | `get_stop_loss_price` fallback | Fixed timeframe used to read SAR when the primary data-layer SL is unavailable |
| `SL_TRAIL_SAR_TF_FAST` | `15` | `get_stop_loss_price` trailing | Faster SAR timeframe used in trailing and close-SL logic |
| `SL_TRAIL_SAR_TF_SLOW` | `60` | `get_stop_loss_price` trailing | Slower SAR timeframe used in trailing and close-SL logic |
| `EXIT_PCT_FALLBACK` | `0.008` | `get_close_price` | Fallback exit offset (+0.8% long / -0.8% short) when data-layer `tgt_long/short` unavailable |
| `EXIT_TRANCHE_STEP` | `0.008` | `get_close_price` tranche example | Step between graduated exit tranches (+0.8%, +1.6%, +2.4%) |
| `DEFAULT_TF` | `15` | `select_final_action` | Default timeframe returned when no action fires (fallback for `open_tf`, `close_tf`, `stop_loss_tf`) |
| `LEVEL_SHORT1_TF` | `[60, 240]` | `get_level_values` | Timeframes used to build `SHORT_1_RESISTANCE` levels (EMA_50, EMA_100, BBU) |
| `LEVEL_SHORT2_TF` | `[15, 60, 240]` | `get_level_values` | Timeframes used to build `SHORT_2_RESISTANCE` levels (EMA_50, EMA_100, BBM) |
| `LEVEL_PROXIMITY_BUFFER` | `0.2` | `Near_Price_Level_Signal` in signal chain examples | Proximity tolerance (% or ATR units) for level-nearness signals |

**Refactor path:** Move all the above to `strategy_config.yaml` (or a per-strategy config block loaded at `__init__`). Each strategy subclass should be able to override individual values for its own risk profile. Until then, treat any change to these numbers as a breaking change requiring explicit justification.

---

## 10. Summary

The `Strategy` base class provides a robust template for signal-based trading decisions. Subclasses override three abstract methods (signal registration, condition checking, action processing) and optionally override price computation methods. The main `check()` flow is deterministic and repeatable: given identical market data and position state, it produces identical action recommendations. Trend detection is pre-built; multi-timeframe confirmation is reserved for future enhancement. All price levels integrate fee awareness, ATR-based risk buffers, and level proximity logic.
