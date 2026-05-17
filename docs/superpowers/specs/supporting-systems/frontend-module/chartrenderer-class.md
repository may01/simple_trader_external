# ChartRenderer Class Specification

**Class:** `ChartRenderer` (Refactoring of view_helpers.py)  
**Files:** `view_helpers.py`, plotly utilities  
**Purpose:** Render OHLC candles, indicators, signals, and trade marks as interactive Plotly figures.

---

## 1. Class Overview

The `ChartRenderer` class encapsulates chart creation logic. It takes raw market data and renders it as interactive Plotly figures, supporting multiple indicator overlays, signal marking, and trade annotation.

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `default_height` | `int` | Default chart height in pixels |
| `default_width` | `int` | Default chart width in pixels |
| `color_scheme` | `dict` | Color palette for indicators and signals |
| `templates` | `dict` | Cached Plotly template configurations |

---

## 3. Constructor

### `__init__(width=1200, height=600, color_scheme=None)`

**Parameters:**
- `width` (`int`) — Figure width. Default: 1200
- `height` (`int`) — Figure height. Default: 600
- `color_scheme` (`dict`) — Custom colors. Default: built-in palette

**Behavior:**
1. Store dimensions
2. Set color scheme (or use default)
3. Initialize template cache

---

## 4. Key Methods & Interfaces

### `render_candlestick(ohlc_data, title="", show_volume=True)`

**Purpose:** Render candlestick chart with volume.

**Parameters:**
- `ohlc_data` (`pandas.DataFrame`) — Columns: open, high, low, close, volume
- `title` (`str`) — Chart title
- `show_volume` (`bool`) — Include volume bars. Default: True

**Return Value:** `plotly.graph_objs.Figure`

**Behavior:**
1. Create candlestick trace from OHLC data
2. Add volume bars as secondary subplot
3. Configure axes, legends, hover templates
4. Return figure

### `add_indicator(figure, indicator_data, name, color=None, yaxis='y')`

**Purpose:** Overlay indicator line on chart.

**Parameters:**
- `figure` — Plotly Figure to modify
- `indicator_data` (`pd.Series`) — Indicator values
- `name` (`str`) — Indicator name (e.g., 'RSI')
- `color` (`str`) — Line color
- `yaxis` (`str`) — Y-axis: 'y' (left) or 'y2' (right)

**Behavior:**
1. Create line trace from indicator data
2. Add to figure
3. Assign to specified y-axis
4. Add to legend
5. Return modified figure

### `add_signals(figure, signals_dict, begin_time, end_time)`

**Purpose:** Mark trading signals on chart.

**Parameters:**
- `figure` — Plotly Figure
- `signals_dict` (`dict`) — Signals: {signal_name: [timestamps, values]}
- `begin_time`, `end_time` — Time range for filtering

**Behavior:**
1. For each signal:
   - Create scatter trace with markers
   - Color by signal type (BUY=green, SELL=red)
   - Add to figure
2. Return modified figure

### `add_trades(figure, trades_list, begin_time, end_time)`

**Purpose:** Mark executed trades on chart.

**Parameters:**
- `figure` — Plotly Figure
- `trades_list` (`list[dict]`) — Trade details
- `begin_time`, `end_time` — Time range

**Behavior:**
1. For each trade:
   - Add entry marker (entry_time, entry_price)
   - Add exit marker (exit_time, exit_price)
   - Color by profitability (green=profit, red=loss)
   - Add annotation showing P&L
2. Return modified figure

### `add_levels(figure, levels_data)`

**Purpose:** Draw support/resistance levels.

**Parameters:**
- `figure` — Plotly Figure
- `levels_data` (`Levels`) — Level objects

**Behavior:**
1. For each level:
   - Draw horizontal line at level price
   - Label with level name/strength
2. Return modified figure

### `add_hover_template(figure, data_dict)`

**Purpose:** Add detailed hover tooltips.

**Parameters:**
- `figure` — Plotly Figure
- `data_dict` (`dict`) — Additional data for tooltips

**Behavior:**
1. Configure hover templates for candlesticks:
   - Show: date, OHLC, volume
   - Add: RSI, MACD, other indicators
2. Configure for indicator lines:
   - Show: value, date
3. Configure for trade marks:
   - Show: entry price, exit price, P&L, duration

---

## 5. Potential Improvements

1. **Add Subplots Support**
   - Stack multiple indicators in separate panels
   - Better visual organization

2. **Implement Dark Mode**
   - Alternative color scheme
   - Eye-friendly for night trading

3. **Add Drawing Tools**
   - User can draw trend lines
   - Annotation layer

4. **Support Heatmaps**
   - Visualize indicator strength over time
   - 2D color-coded matrix

5. **Implement Animation**
   - Replay trades sequentially
   - Time-lapse market evolution

6. **Add Statistical Overlays**
   - Bollinger Bands, standard deviations
   - Distribution plots

7. **Support 3D Visualization**
   - Surface plots for multi-dimensional data
   - Alternative perspectives

8. **Implement Custom Rendering**
   - Pluggable renderer backends
   - Alternative chart libraries

9. **Add Export Options**
   - Save as PNG, PDF, SVG
   - Generate reports

10. **Support Theme Customization**
    - User-defined color schemes
    - Branded layouts
