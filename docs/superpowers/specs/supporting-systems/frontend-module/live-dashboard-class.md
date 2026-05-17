# LiveDashboard Class Specification

**Class:** `LiveDashboard` (Refactoring of view_online.py)  
**Files:** `view_online.py`, `view_onlineB.py`  
**Purpose:** Real-time monitoring of live trading: current positions, recent trades, market overview, performance metrics.

---

## 1. Class Overview

The `LiveDashboard` class displays real-time trading status. It connects to the live Robot instance, streaming current positions, execution events, and market data. Designed for active monitoring during live trading sessions.

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `robot` | `Robot` | Live robot instance to monitor |
| `app` | `dash.Dash` | Dash application |
| `refresh_interval` | `int` | Update interval in seconds (default: 5) |
| `data_viewer` | `DataViewer` | Market data loader |
| `position_tracker` | `dict` | Current position states |
| `execution_log` | `list` | Recent trade execution events |

---

## 3. Constructor

### `__init__(robot, pair, refresh_interval=5, enable_alerts=True)`

**Parameters:**
- `robot` (`Robot`) — Live robot instance
- `pair` (`str`) — Trading pair
- `refresh_interval` (`int`) — Update interval seconds. Default: 5
- `enable_alerts` (`bool`) — Enable alerts on signals/fills. Default: True

**Behavior:**
1. Store robot reference
2. Create Dash app
3. Initialize position tracker and execution log
4. Configure auto-refresh interval
5. Set up WebSocket/polling for live updates
6. Build layout

---

## 4. Key Methods & Interfaces

### `display()`

**Purpose:** Start live dashboard (show in browser).

**Behavior:**
1. Start Dash server
2. Enable WebSocket streaming (if available)
3. Run refresh callbacks
4. Display in browser

### `display_positions()`

**Purpose:** Show current open positions.

**Return Value:** `dash.html.Div` with position details table

**Columns:**
- Pair
- Position Type (LONG/SHORT)
- Entry Time
- Entry Price
- Current Price
- Quantity
- Unrealized P&L
- Position Duration
- Status (OPEN/CLOSING/CLOSED)

**Behavior:**
1. Query robot.position for current state
2. Fetch market data (current price)
3. Calculate unrealized PnL
4. Highlight negative PnL in red
5. Return table

### `display_execution_log(limit=50)`

**Purpose:** Show recent trade executions.

**Parameters:**
- `limit` (`int`) — Number of recent events. Default: 50

**Return Value:** `dash.html.Div` with execution log

**Columns:**
- Timestamp
- Action (OPEN_LONG, CLOSE_SHORT, etc.)
- Price
- Quantity
- Message/Reason

### `display_market_overview()`

**Purpose:** Show multi-pair snapshot.

**Return Value:** `dash.html.Div` with overview table

**Columns:**
- Pair
- Current Price
- 24h Change %
- Signal State (BUY/SELL/NEUTRAL)
- Recent Trade (timestamp, price)
- Strategy Action

### `get_performance_metrics()`

**Purpose:** Calculate live performance stats.

**Return Value:** `dict` with:
- `"total_pnl"` — Unrealized PnL
- `"total_pnl_pct"` — Percent
- `"num_open_positions"` — Count
- `"realized_pnl"` — Closed trade profit
- `"win_rate"` — Wins / total closed trades
- `"uptime"` — Minutes since start
- `"trades_today"` — Trades executed today

---

## 5. Live Callbacks

### Auto-Refresh

Every `refresh_interval` seconds:
1. Query robot for position updates
2. Fetch latest market data
3. Calculate unrealized PnL
4. Update display (no page reload, AJAX)

### Alert Triggers

On signal generation:
- Flash notification in dashboard
- Play sound (optional)
- Log event to execution log

On trade fill:
- Update position table
- Update P&L metrics
- Add to execution log
- Play alert sound

### Position Update

On position state change (OPEN → CLOSING):
- Update position status
- Change color (yellow for transitioning)
- Update button states (allow manual close)

---

## 6. Safety Features

### Circuit Breaker

If max drawdown exceeded:
- Flash red alert
- Disable new entries
- Show "RISK LIMIT" warning

### Position Limits

Display warning if:
- Too many open positions
- Position too large relative to capital
- Leverage too high

### Execution Confirmation

On risky actions (large order, market order):
- Show confirmation dialog
- Require explicit click to proceed

---

## 7. Potential Improvements

1. **Add WebSocket Real-Time Updates**
   - Push price ticks to dashboard
   - Eliminate polling latency

2. **Implement Mobile Responsive Design**
   - Optimize for phone/tablet
   - Touch-friendly controls

3. **Add Voice Alerts**
   - Announce signals, fills, alerts
   - Hands-free monitoring

4. **Support Manual Override**
   - Close positions manually
   - Adjust stop losses live

5. **Add Risk Management Controls**
   - Set max drawdown limits
   - Pause trading on threshold
   - Adjust position sizing

6. **Implement News Integration**
   - Show relevant news feed
   - Correlation with price moves

7. **Add Performance Attribution**
   - Show contribution of each signal
   - Identify key decision drivers

8. **Support Multi-Pair Sync**
   - Monitor multiple pairs simultaneously
   - Cross-pair correlation

9. **Add Historical Playback**
   - Replay recent trades
   - Review decision logic

10. **Implement Snapshot Export**
    - Save dashboard state
    - Generate trading records
