# NNModel Class Specification

**Class:** `NN`  
**File:** `nn.py` (lines 17-530)  
**Purpose:** Build, train, and run inference with Keras/TensorFlow neural networks for price movement classification across multiple timeframe and indicator combinations.

---

## 1. Class Overview

The `NN` class is the core neural network implementation in pybtctr2. It encapsulates model architecture selection, training, inference, and checkpoint management. The class uses Keras/TensorFlow to learn patterns from historical OHLC data and technical indicators, outputting probability distributions for three trading classes: BUY, SELL, NONE.

Rather than hardcoding a single architecture, NN supports multiple configurations (generic, stochastic, MA-only) selected at instantiation via the `nn_tf_type` parameter. This allows different model specializations to be trained independently—e.g., a generic model for all indicators, a simplified stochastic model for fast inference, and a price-action-only model for support/resistance patterns.

The class manages the complete model lifecycle: initialization with hyperparameters, architecture construction, training with Keras callbacks, and inference via batch or single-point prediction. Models are saved to disk with a hierarchical naming scheme that enables multi-class, multi-target, and multi-architecture configurations to coexist.

---

## 2. Key Attributes

### Instance Variables

| Attribute | Type | Description |
|-----------|------|-------------|
| `pair` | `str` | Trading pair (e.g., `link_usdt`). Used for data and model path construction. |
| `model` | `keras.Model` | The compiled Keras model instance. Built by `get_model()`, persisted by `load_model()`/`save_model()`. |
| `all_tf` | `list[int]` | All available timeframes: `[1,3,5,15,30,60,120,240,480,1440]` minutes. Used as reference for skip index calculation. |
| `skip_tf_idx` | `list[int]` | Indices of timeframes to exclude from model input. Varies by `nn_tf_type` (e.g., [0,1,2] for BIG). |
| `skip_indicator_idx` | `list[int]` | Indices of indicators to exclude per timeframe. Used for specialized architectures (MA-only, stochastic). |
| `nn_tf_type` | `int` | Architecture type: NN_TYPE_ALL, NN_TYPE_BIG, NN_TYPE_SMALL, NN_TYPE_REG, NN_TYPE_X_BIG, NN_TYPE_HACK_MA, NN_TYPE_HACK_STOCHASTIC. Determines skip indices and model structure. |
| `nn_type_name` | `str` | Human-readable type name: "all_tf", "big_tf", "small_tf", "regression", "x_big_tf", "x_hack_ma_tf", "x_hack_stoch_tf". Used in model paths and logging. |
| `nn_target_idx` | `int` | Index of target type (0-17). Selects which NN target classification to train on. |
| `class_type` | `int` or `str` | Classification grouping (e.g., NN_POINT_CLASS_BIG). Hierarchical label for model organization. |
| `class_name` | `str` | Subclass identifier (e.g., "0", "1"). Further subdivides class_type into separate training sets. |
| `nn_history` | `int` | Number of historical candles to include in model input. Defines receptive field depth. |
| `cached_result` | `numpy.ndarray` | Last inference output. Cached by `cache_result()`, retrieved by `get_cache_result()`. |

---

## 3. Constructor

### `__init__(pair, class_type, class_name, nn_tf_type, nn_target_idx, nn_history)`

**Purpose:** Initialize an NN instance with configuration parameters.

**Parameters:**
- `pair` (`str`) — Trading pair (e.g., `link_usdt`)
- `class_type` (`int` or `str`) — Classification type for hierarchical model organization
- `class_name` (`str`) — Subclass identifier (further divides training data)
- `nn_tf_type` (`int`) — Architecture type (NN_TYPE_ALL, NN_TYPE_BIG, NN_TYPE_SMALL, NN_TYPE_REG, NN_TYPE_X_BIG, NN_TYPE_HACK_MA, NN_TYPE_HACK_STOCHASTIC)
- `nn_target_idx` (`int`) — Target type index (0-17 for different prediction horizons)
- `nn_history` (`int`) — Number of historical candles for context

**Behavior:**
1. Store all parameters as instance attributes
2. Initialize empty Sequential model instance
3. Set `all_tf` to reference timeframe list
4. Initialize empty `skip_tf_idx` and `skip_indicator_idx` lists
5. Determine `nn_type_name` based on `nn_tf_type`:
   - NN_TYPE_ALL → "all_tf"
   - NN_TYPE_BIG → "big_tf", skip_tf_idx = [0,1,2]
   - NN_TYPE_SMALL → "small_tf", skip_tf_idx = [0,1]
   - NN_TYPE_REG → "regression", skip_tf_idx = [0,1,8]
   - NN_TYPE_X_BIG → "x_big_tf", skip_tf_idx = [0,1,2,3,4]
   - NN_TYPE_HACK_MA → "x_hack_ma_tf", skip_tf_idx = [0,1,2,4,6,8,9], skip_indicator_idx = [1,2,3,4,5,6]
   - NN_TYPE_HACK_STOCHASTIC → "x_hack_stoch_tf", skip_tf_idx = [0,1,2,4,6,8,9], skip_indicator_idx = [0,3,4,5,6]

**Preconditions:**
- `pair` must be formatted as `coin_base` (lowercase)
- `nn_tf_type` must be a recognized type constant
- `nn_target_idx` must be in valid range (0-17)

**Postconditions:**
- Instance is configured and ready to build a model via `get_model()`
- No model has been created yet (lazy initialization)

**Example:**
```python
nn = NN("link_usdt", NN_POINT_CLASS_BIG, "0", NN_TYPE_BIG, 0, 120)
# Configures big-timeframe model, class 0, target 0, 120-candle history
```

---

## 4. Key Methods & Interfaces

### 4.1 Model Architecture Construction

#### `get_model()`

**Purpose:** Build and return a Keras model based on `nn_tf_type`.

**Return Value:** `keras.Model` (Functional Model with multiple inputs and softmax output)

**Behavior:**
1. Route to appropriate architecture builder:
   - NN_TYPE_HACK_STOCHASTIC → call `get_hack_stochastic_model()`
   - NN_TYPE_HACK_MA → call `get_hack_ma_model()`
   - Otherwise → call `get_generic_model()`
2. Return compiled model

**Preconditions:**
- Instance attributes (pair, nn_tf_type, nn_history, skip_tf_idx) must be initialized

**Postconditions:**
- `self.model` is updated with new compiled model
- Model is ready for `train()` or `load_model()` + inference

#### `get_generic_model()`

**Purpose:** Build full-feature neural network with per-indicator branches.

**Architecture:**
```
For each non-skipped timeframe:
  ├─ OHLC Branch: Input(9*history) → Dense(9*history*9*history, relu) → Dense(9*9*history, relu)
  ├─ RSI Branch: Input(2*history) → Dense(2*history*2*history, relu) → Dense(2*2*history, relu)
  ├─ CCI Branch: Input(2*history) → Dense(2*history*2*history, relu) → Dense(2*history*2, relu)
  ├─ Volume Branch: Input(1*history) → Dense(1*history*1*history, relu)
  ├─ ATR Branch: Input(1*history) → Dense(1*history*1*history, relu)
  ├─ MACD Branch: Input(3*history) → Dense(3*history*3*history, relu) → Dense(3*3, relu)
  └─ ADX Branch: Input(3*history) → Dense(3*history*3*history, relu) → Dense(3*3, relu)
  
  Concatenate all branches → Dense(sum_size*sum_size, relu) → Dense(sum_size*sum_size, relu)

Concatenate across timeframes
  → Dense(sum_size*sum_size, relu) → Dense(sum_size*sum_size, relu) → Dense(sum_size, relu)
  → Dense(3, softmax)
```

**Compilation:**
- Optimizer: Adam(learning_rate=0.000001)
- Loss: CategoricalCrossentropy
- Metrics: categorical_accuracy, Precision(class_id=1), Precision(class_id=2)

#### `get_hack_stochastic_model()`

**Purpose:** Build simplified stochastic-focused model (RSI + CCI only).

**Architecture:**
```
For each non-skipped timeframe:
  ├─ RSI Branch: Input(2*history) → Dense(2*history*2*history, relu)
  └─ CCI Branch: Input(2*history) → Dense(2*history*2*history, relu)
  
  Concatenate → Dense(sum_size*sum_size, relu) → Dense(sum_size*sum_size, relu)

Concatenate across timeframes
  → Dense(sum_size, relu) → Dense(3, softmax)
```

#### `get_hack_ma_model()`

**Purpose:** Build price-action-only model (OHLC features only).

**Architecture:**
```
For each non-skipped timeframe:
  OHLC Branch: Input(9*history) → Dense(9*history*9*history, relu) → Dense(9*9*history, relu) → Dense(9*9, relu)

Concatenate across timeframes
  → Dense(sum_size*sum_size, relu) → Dense(sum_size*sum_size, relu)
  → Dense(sum_size, relu) → Dense(3, softmax)
```

### 4.2 Training

#### `train(data_group_num)`

**Purpose:** Train the neural network on grouped historical data.

**Parameters:**
- `data_group_num` (`int`) — Group number to load from disk

**Behavior:**
1. Load grouped training data via `get_group(data_group_num)`
2. If no valid data: log warning and return
3. Extract inputs: `data[NN_POINT_INPUT]`
   - Multi-timeframe OHLC, RSI, CCI, Volume, ATR, MACD, ADX (historical window)
4. Filter inputs via `get_data_with_skip_idx()` to match model architecture
5. Extract targets: `data[NN_POINT_TARGET][nn_target_idx]`
   - Shape: [num_samples, 3] with [P(BUY), P(SELL), P(NONE)]
6. Calculate class weights to balance imbalanced data
   - `class_weight[i] = 1 / column_sum[i]` for each of 3 classes
7. Build model via `get_model()`
8. Create training callbacks:
   - **ModelCheckpoint:** Save best model based on validation accuracy
   - **TensorBoard:** Log metrics for visualization in tensorboard
   - **CSVLogger:** Export per-epoch metrics to CSV
9. Train via `model.fit()`:
   - x = filtered_inputs (list of indicator arrays)
   - y = targets (class probabilities)
   - epochs = 15 (or 20 for NN_TYPE_REG)
   - batch_size = 32
   - validation_split = 0.30
   - class_weight = calculated weights
   - callbacks = [checkpoint, tensorboard, csv_logger]
10. Clear TensorFlow session after training

**Returns:** `None`

**Preconditions:**
- `data_group_num` must be valid and have associated pickle files
- `get_model()` must be callable (nn_tf_type valid)

**Postconditions:**
- Best model saved to disk under `best_model/{class_type}_{class_name}_{nn_type_name}_{nn_target_idx}`
- Training metrics logged to CSV and TensorBoard
- TensorFlow session cleared to free memory

### 4.3 Inference

#### `run(data)`

**Purpose:** Run inference on single data point, return probability output.

**Parameters:**
- `data` (dict with keys `NN_POINT_INPUT`, `NN_POINT_TARGET`) — Single data point with features

**Return Value:** `numpy.ndarray` shape [3] with probabilities [P(BUY), P(SELL), P(NONE)]

**Behavior:**
1. Extract input features from `data[NN_POINT_INPUT]`
2. Filter via `get_data_with_skip_idx()` to match trained input shape
3. Reshape each filtered feature to [1, -1] (single sample)
4. Call `model.predict(data_in)` for single-point inference
5. Extract first (only) result: `result[0]`
6. Cache result via `cache_result(result)`
7. Return probabilities

**Preconditions:**
- Model must be built and trained (or loaded via `load_model()`)
- Input data shape must match model input configuration

**Postconditions:**
- Prediction cached for retrieval via `get_cache_result()`

#### `run_batch(data)`

**Purpose:** Run inference on batch of data points.

**Parameters:**
- `data` (dict with key `NN_POINT_INPUT`) — Batch data with feature lists

**Return Value:** `numpy.ndarray` shape [batch_size, 3] with probabilities

**Behavior:**
1. Extract batch inputs from `data[NN_POINT_INPUT]`
2. Filter via `get_data_with_skip_idx()` (vectorized)
3. Call `model.predict(data_in)` for batch inference
4. Return full output array

**Preconditions:**
- Model must be trained or loaded
- Input batch must be properly formatted

### 4.4 Model Persistence

#### `load_model()`

**Purpose:** Load pre-trained model weights from disk.

**Behavior:**
1. Check local path: `/trader_data_local/{DATA_ROOT}/2020_09_01_3Y_{PAIR}/shared/nn_data/best_model/{class_type}_{class_name}_{nn_type_name}_{nn_target_idx}`
2. If not found, check remote path: `/trader_data/{DATA_ROOT}/2020_09_01_3Y_{PAIR}/shared/nn_data/best_model/...`
3. Load model via `keras.models.load_model(path)`
4. Update `self.model` with loaded instance

**Returns:** `None`

**Preconditions:**
- Model file must exist at one of the two paths
- Environment variables `DATA_ROOT`, `PAIR` must be set

**Postconditions:**
- `self.model` updated with pre-trained weights
- Model ready for inference

#### `save_model()`

**Purpose:** Save current model to disk.

**Behavior:**
1. Construct path: `nn_folder(pair) + '/nn_model'`
2. Call `self.model.save(path)`

**Returns:** `None`

**Preconditions:**
- Model must be built
- Destination directory must exist

### 4.5 Data Processing Utilities

#### `get_data_with_skip_idx(input_data)`

**Purpose:** Filter neural network input data to match model architecture.

**Parameters:**
- `input_data` (list) — Full input feature array with 7 items per timeframe

**Return Value:** `list` — Filtered feature array with skipped items removed

**Behavior:**
1. Build skip index list from `skip_tf_idx` and `skip_indicator_idx`
   - For each timeframe in skip_tf_idx: mark all 7 items for that timeframe
   - For each indicator in skip_indicator_idx: mark across all timeframes
2. Iterate through input_data
3. Skip any index in skip list
4. Convert remaining items to numpy arrays
5. Return filtered list

**Example:**
```python
# Full input has 70 items (10 timeframes * 7 indicators)
# If skip_tf_idx = [0, 1, 2] (skip first 3 timeframes):
# Output has ~49 items (remaining 7 timeframes * 7)
```

#### `get_group(group_num)`

**Purpose:** Load grouped training data from disk.

**Parameters:**
- `group_num` (`int`) — Group number to load

**Return Value:** `(bool, dict)` — (is_valid, data)
- `is_valid` — True if group exists and is loadable
- `data` — Dict with keys `NN_POINT_INPUT`, `NN_POINT_TARGET`, `NN_POINT_TIMESTAMP`

**Behavior:**
1. Start with group_num = 1 (always)
2. Loop through group files with incremental numbers
3. For each group:
   - Construct path: `nn_folder_local(pair) + '/nn_group_{class_type}_{class_name}_{group_num}.pkl'`
   - Check for special 3Y dataset path naming with history variations
   - Attempt to load pickle
   - On success: return (True, loaded_data)
4. If no groups found: return (False, {})

### 4.6 Result Caching

#### `cache_result(result)`

**Purpose:** Store inference output for later retrieval.

**Parameters:**
- `result` (`numpy.ndarray`) — Probability array from `run()`

#### `get_cache_result()`

**Purpose:** Retrieve cached inference result.

**Return Value:** `numpy.ndarray` — Cached probability array

---

## 5. State Management

### Model State
- **Uninitialized:** `self.model = Sequential()` (empty)
- **Built:** Model architecture created via `get_model()`, compiled with optimizer and loss
- **Trained:** Weights updated via `train()`; checkpoint callback saves best
- **Loaded:** Weights restored from disk via `load_model()`

### Data State
- Input features extracted and filtered per request (stateless)
- Predictions cached in `cached_result` (short-lived)
- No persistent training state between method calls

---

## 6. Error Handling

**Missing Training Data:**
```python
if not valid:
    print("There is no valid training data for class: "+self.class_name)
    return
```
Returns early without error if grouped data not found.

**Missing Model File:**
`load_model()` attempts local path first, then remote. If both fail, exception from `keras.models.load_model()` propagates.

**Incompatible Input Shape:**
If input data doesn't match expected shape, `model.predict()` raises TensorFlow shape mismatch error.

---

## 7. Existing Approach

### Timeframe-Based Architecture Selection

The NN class uses `nn_tf_type` to determine which timeframes to include:
- BIG uses larger timeframes (15m+) for trend analysis
- SMALL includes finer granularity for intraday signals
- REG focuses on regression targets with specific timeframe subset

This allows training different models for different market conditions without code duplication.

### Per-Indicator Dense Branches

Rather than flattening all features, the model:
1. Creates separate dense branches per indicator type (OHLC, RSI, CCI, etc.)
2. Allows each branch to learn representations independently
3. Concatenates at the end for interaction modeling

This design improves training stability and feature interpretability.

### Class Weight Balancing

Training uses inverse frequency weighting:
```python
class_weight[i] = 1 / sum(labels[:, i])
```

If BUY examples are rare, they receive higher weight, reducing bias toward majority class.

### Callback-Driven Training

Keras callbacks handle:
- **Checkpoint:** Only saves improving models, avoiding overfitting
- **TensorBoard:** Real-time training visualization
- **CSV Logger:** Metrics export for post-analysis

---

## 8. Potential Improvements

1. **Add Input Normalization**
   - Normalize features to [0, 1] range before model input
   - Would improve training stability and convergence speed

2. **Implement Dropout Regularization**
   - Add Dropout layers between dense layers to prevent overfitting
   - Make regularization configurable per architecture

3. **Add Batch Normalization**
   - Normalize activations between layers
   - Would stabilize training and reduce sensitivity to initialization

4. **Support Model Checkpointing Resume**
   - Save training state (epoch, learning rate) alongside weights
   - Allow resuming interrupted training from last checkpoint

5. **Add Learning Rate Scheduling**
   - Decrease learning rate over epochs
   - Would enable finer convergence in later training phases

6. **Implement Gradient Clipping**
   - Clip gradients to prevent explosive growth
   - Would stabilize training on volatile market data

7. **Add Model Pruning**
   - Remove low-importance weights post-training
   - Would reduce model size for faster inference

8. **Support Quantization**
   - Convert float32 weights to int8
   - Would enable deployment on resource-constrained devices
