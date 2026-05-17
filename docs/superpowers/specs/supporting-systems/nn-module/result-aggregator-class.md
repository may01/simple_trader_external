# ResultAggregator Class Specification

**Class:** `ResultAggregator` (Proposed Refactoring)  
**Files:** `trainer.py` (simulate result aggregation, lines 800-900)  
**Purpose:** Collect and merge results from parallel simulation/training processes into unified summaries.

---

## 1. Class Overview

The `ResultAggregator` class aggregates partial results from parallel TrainRobot instances into unified performance metrics. Rather than inline aggregation in Trainer, extracting into a dedicated class improves reusability and testability.

ResultAggregator handles:
- Loading thread-specific result files
- Merging dictionaries (revenue by strategy ID)
- Summing scalar metrics (total revenue, trades count)
- Computing aggregate statistics
- Exporting results for analysis

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `data_root` | `str` | Root data folder path |
| `pair` | `str` | Trading pair |
| `num_threads` | `int` | Number of threads that produced results |
| `thread_results` | `list[dict]` | Loaded results from each thread |
| `aggregated_result` | `dict` | Merged result summary |

---

## 3. Constructor

### `__init__(data_root, pair, num_threads)`

**Purpose:** Initialize aggregator.

**Parameters:**
- `data_root` (`str`) — Data folder path
- `pair` (`str`) — Trading pair
- `num_threads` (`int`) — Number of parallel threads

**Behavior:**
1. Store parameters
2. Initialize empty thread_results list
3. Initialize empty aggregated_result dict

---

## 4. Key Methods & Interfaces

### `load_thread_results()`

**Purpose:** Load all thread result files from disk.

**Behavior:**
1. For each thread from 0 to num_threads-1:
   - Load file: `{data_root}/pair/results/thread_result_by_id_{thread_num}.pkl`
   - Parse result dict
   - Append to thread_results list

**Returns:** `int` — Count of results loaded

### `aggregate()`

**Purpose:** Merge thread results into unified summary.

**Behavior:**
1. Initialize aggregated totals: total_revenue, total_revenue_abs, revenue_by_id
2. For each thread_result:
   - Add revenue and revenue_abs to totals
   - Merge revenue_by_id dict (per-strategy breakdown)
3. Compute aggregate statistics:
   - Average revenue per thread
   - Min/max revenue
   - Revenue distribution
4. Store in aggregated_result

**Returns:** `dict` — Aggregated results

### `export_results(format='pickle')`

**Purpose:** Export aggregated results to disk.

**Parameters:**
- `format` (`str`) — Output format: 'pickle' or 'json'

**Behavior:**
1. If format == 'pickle':
   - Save aggregated_result to pickle file
2. If format == 'json':
   - Convert to JSON-compatible format
   - Save to JSON file
3. Return file path

### `get_summary()`

**Purpose:** Get human-readable summary of results.

**Return Value:** `dict` with keys:
- `"total_revenue"` — Aggregate revenue
- `"average_revenue_per_thread"` — Mean
- `"revenue_std"` — Standard deviation
- `"best_thread"` — Thread with highest revenue
- `"worst_thread"` — Thread with lowest revenue

---

## 5. Error Handling

**Missing Result Files:**
```python
if not os.path.exists(file):
    logger.warning(f"Result file not found: {file}")
    continue
```

**Corrupted Pickle:**
```python
try:
    data = pickle.load(f)
except pickle.UnpicklingError as e:
    logger.error(f"Failed to load result: {e}")
    continue
```

---

## 6. Existing Approach

Current implementation in Trainer.simulate():
```python
for key in result_by_id_by_thread:
    if key in result_by_id:
        result_by_id[key] += result_by_id_by_thread[key]
```

Inline aggregation at end of simulate method. No dedicated abstraction.

---

## 7. Potential Improvements

1. **Add Incremental Aggregation**
   - Aggregate results as threads complete
   - Provide intermediate summaries
   - Would enable real-time progress reporting

2. **Implement Checksum Validation**
   - Verify result integrity before aggregation
   - Detect corrupted files

3. **Add Statistical Testing**
   - Compare performance across configurations
   - Generate significance tests

4. **Support Different Aggregation Methods**
   - Weighted average by timeframe
   - Median instead of mean (robust to outliers)

5. **Add Outlier Detection**
   - Flag threads with anomalous results
   - Investigate causes

6. **Implement Result Versioning**
   - Track aggregated results with timestamps
   - Enable comparison across versions

7. **Add Export to CSV/Excel**
   - Enable analysis in spreadsheet tools

8. **Implement Result Visualization**
   - Generate charts of revenue distribution
   - Export plots

9. **Add Metadata Tracking**
   - Store configuration alongside results
   - Document reproducibility

10. **Support Custom Metrics**
    - Allow pluggable metric computations
    - Enable domain-specific analysis
