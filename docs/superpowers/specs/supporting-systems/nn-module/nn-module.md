# NN Module Specification

**Module:** Neural Network (NN)  
**Files:** `nn.py`, `predictor.py`, `strategies/nn_strategy.py`, `signals_lib/nn_signals.py`  
**Purpose:** Implement neural network models for enhanced price prediction, signal generation, and trading decision support in the pybtctr2 trading bot.

---

## 1. Overview

The NN Module provides deep learning capabilities for the pybtctr2 trading bot. It uses Keras/TensorFlow to build, train, and deploy neural network models that learn trading patterns from historical OHLC data, technical indicators, and signal outputs. The module operates in two main phases:

1. **Training Phase:** NNModel class builds and trains neural networks on grouped historical data, learning to classify future price movements (BUY/SELL/NONE) across multiple timeframes and indicator combinations.

2. **Inference Phase:** Trained models run predictions on live or backtest data, outputting probability distributions that enhance strategy decisions via nn_signals and nn_strategy components.

The NN Module is designed for extensibility—multiple model architectures (generic, stochastic, MA-only) can be trained independently for different market conditions, and their predictions are aggregated in the strategy layer.

---

## 2. Module Boundaries

### Upstream Dependencies
- **Training Module:** `trainer.py` generates grouped training data via `group_nn()` and `train_nn()` pipelines; calls NNModel.train()
- **Data Module:** `data.py` provides OHLC candles and indicators; NN inputs derived from multi-timeframe candle history
- **Signals Module:** Signal values feed into NN inputs; NN outputs feed back to signal pipeline
- **Position Data:** Historical positions and trade outcomes inform target classification (BUY/SELL labels)
- **Environment Configuration:** Model paths, training parameters, NN types specified via `os.environ`

### Downstream Consumers
- **Strategy Manager:** Uses NN predictions to enhance trading signal evaluation
- **NN Signals:** `signals_lib/nn_signals.py` wraps NN predictions as high-level trading signals
- **NN Strategy:** `strategies/nn_strategy.py` makes trading decisions based on NN probabilities
- **Live Robot:** Loads trained models for live trading inference
- **TrainRobot:** Loads trained models for backtesting with NN enhancement

### Key Interfaces Exposed
- **`NNModel.__init__(pair, class_type, class_name, nn_tf_type, nn_target_idx, nn_history)`** — Initialize NN model
- **`NNModel.get_model()`** — Build model architecture (generic, stochastic, MA-only)
- **`NNModel.train(data_group_num)`** — Train model on grouped historical data
- **`NNModel.run(data)`** — Run inference on single data point, return probability [BUY, SELL, NONE]
- **`NNModel.run_batch(data)`** — Run inference on batch of data points
- **`NNModel.load_model()`** — Load pre-trained model weights from disk
- **`NNPredictor.calc(save_data, action, prediction_cache)`** — Compute next price levels via Gaussian prediction
- **`NNPredictor.set_data(data, full_data)`** — Configure predictor with current/historical data

---

## 3. Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│            Historical OHLC Data + Indicators                │
│         (Multi-timeframe candles with RSI, MACD, etc)       │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Generate NN Training Data            │
        │  (generate_data_points w/ predictor) │
        │  ├─ Extract multi-tf candle history │
        │  ├─ Compute technical indicators    │
        │  ├─ Classify future price movement │
        │  │  (BUY/SELL/NONE labels)          │
        │  ├─ Compute NN targets             │
        │  └─ Save grouped pickles           │
        └──────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Group NN Data (group_nn)            │
        │  ├─ Load all generated data points  │
        │  ├─ Classify by type               │
        │  ├─ Group into batches (5000 pts)  │
        │  └─ Save grouped pickles           │
        └──────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Train NN Models                     │
        │  ├─ Load grouped data               │
        │  ├─ Create model (generic/hack)    │
        │  ├─ Train via backpropagation      │
        │  ├─ Save best model weights        │
        │  └─ Emit training logs             │
        └──────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Trained NN Models                   │
        │  ├─ Best model per class/tf/target  │
        │  ├─ Serialized as Keras models      │
        │  └─ Ready for inference             │
        └──────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Inference Phase (simulate_nn)       │
        │  ├─ Load trained models             │
        │  ├─ Run batch predictions           │
        │  ├─ Aggregate probabilities         │
        │  └─ Feed to strategy layer          │
        └──────────────────────────────────────┘
                           │
        ┌──────────────────┴──────────────────┐
        ▼                                      ▼
    ┌──────────────────────┐      ┌──────────────────────┐
    │ NN Signals Pipeline  │      │ NN Strategy Signals  │
    │ (nn_signals.py)      │      │ (nn_strategy.py)     │
    │ ├─ Probability wrap  │      │ ├─ Decision logic    │
    │ └─ Confidence scores │      │ └─ Action generation │
    └──────────────────────┘      └──────────────────────┘
                                           │
                                           ▼
                                   ┌──────────────────────┐
                                   │ Trading Decisions    │
                                   │ (BUY/SELL/WAIT)      │
                                   └──────────────────────┘
```

---

## 4. Execution Flow

### A. Training (NNModel.train)

1. Load grouped training data via `get_group(data_group_num)`
2. Extract input features: `data[NN_POINT_INPUT]`
   - Multi-timeframe OHLC, RSI, CCI, Volume, ATR, MACD, ADX (historical window)
3. Extract target labels: `data[NN_POINT_TARGET][nn_target_idx]`
   - Classification: [P(BUY), P(SELL), P(NONE)]
4. Filter inputs via `get_data_with_skip_idx()` to remove unused timeframes/indicators
5. Calculate class weights to handle imbalanced data
6. Build model via `get_model()`:
   - Per-timeframe branches (OHLC, RSI, CCI, Volume, ATR, MACD, ADX layers)
   - Concatenation and dense layers for aggregation
   - Output: 3-class softmax (BUY, SELL, NONE)
7. Compile with Adam optimizer, categorical crossentropy loss
8. Train via `model.fit()`:
   - Epochs: 15 (REG: 20)
   - Batch size: 32
   - Validation split: 30%
   - Callbacks: ModelCheckpoint (save best), TensorBoard, CSVLogger
9. Save best model to disk under `best_model/` directory
10. Clear TensorFlow session

### B. Inference (NNModel.run_batch)

1. Load pre-trained model via `load_model()` (checks local and remote paths)
2. Prepare input data:
   - Extract historical indicators for each timeframe
   - Filter via skip indices to match trained model input shape
3. Call `model.predict(data_in)` with batch
4. Return prediction output: shape [batch_size, 3] with probabilities

### C. Price Prediction (NNPredictor.calc)

1. Check if data already cached in `prediction_cache`
   - If match (same index), use cached prediction
   - Skip recalculation
2. For each timeframe (15m, 60m, 240m):
   - For each price type (high, low, close):
     - Load or train Gauss predictor model
     - Fit Gaussian distribution to historical price deltas
     - Predict next price delta and confidence score
3. Convert predictions to absolute price levels:
   - `h = h_prev * (1 + predicted_delta_high)`
   - `l = l_prev * (1 + predicted_delta_low)`
   - `c = c_prev * (1 + predicted_delta_close)`
4. Validate prediction (current price within [l, h])
5. If training mode: Load actual future price from full_data; compute actual delta; store for backtesting
6. If save_data=True: Persist predictions to disk

---

## 5. Key Components

### NNModel Class
The core neural network implementation. Builds, trains, and runs predictions using Keras/TensorFlow.

**Key attributes:**
- `model` — Keras Sequential or Model instance
- `nn_tf_type` — Type of timeframe configuration (ALL, BIG, SMALL, REG, X_BIG, HACK_MA, HACK_STOCHASTIC)
- `skip_tf_idx`, `skip_indicator_idx` — Indices to filter inputs per model type
- `nn_history` — Number of historical candles to use as context

### NNPredictor Class
Price prediction via Gaussian models. Estimates future high/low/close based on historical patterns.

**Key attributes:**
- `data`, `full_data` — Current and full historical data references
- `cur_levels` — Cached next-period price predictions
- `next_point`, `cur_point` — Current/predicted price deltas
- `future_fact` — Actual future prices (for training mode)
- `tmp_points`, `tmp_counter` — Temporary caching for de-duplication

### Helper Functions
- **`get_data_with_skip_idx(input_data)`** — Filter NN input to match model architecture
- **`get_group(group_num)`** — Load grouped training pickle files by class/type/group number
- **`get_model()`** — Select architecture based on nn_tf_type (generic, stochastic, MA-only)
- **`run_batch(data)`** — Batch inference wrapper

### NN Type Configurations
- **`NN_TYPE_ALL`** — Uses all 10 timeframes [1,3,5,15,30,60,120,240,480,1440]
- **`NN_TYPE_BIG`** — Large timeframes only [15,30,60,120,240,480,1440]
- **`NN_TYPE_SMALL`** — Small-to-large [5,15,30,60,120,240,480,1440]
- **`NN_TYPE_REG`** — Regression: [1,3,480]
- **`NN_TYPE_X_BIG`** — Extra large: [240,480,1440]
- **`NN_TYPE_HACK_MA`** — MA-only optimization
- **`NN_TYPE_HACK_STOCHASTIC`** — Stochastic-only optimization

---

## 6. Existing Approach

### Multi-Architecture Support

The NN Module supports multiple model architectures:

1. **Generic Model** (`get_generic_model`):
   - Per-timeframe branches: OHLC (9), RSI (2), CCI (2), Volume (1), ATR (1), MACD (3), ADX (3)
   - Dense layers per indicator type
   - Concatenation layer across timeframes
   - Final dense + softmax output

2. **Stochastic Model** (`get_hack_stochastic_model`):
   - Simplified: RSI + CCI only
   - Reduces feature space for faster training
   - Same concatenation and output structure

3. **MA-Only Model** (`get_hack_ma_model`):
   - OHLC features only
   - Filters out momentum indicators
   - Focused on price action patterns

### Class-Based Training Organization

NN models are trained and stored with hierarchical naming:
```
best_model/{class_type}_{class_name}_{nn_type_name}_{nn_target_idx}
```

Example: `NN_POINT_CLASS_BIG_0_big_tf_0` = big class, sub-class 0, big-timeframe type, target 0

This organization allows independent training runs and parallel inference across classes.

### Gaussian Price Prediction (Predictor)

Complementary to NN classification, the Predictor class uses:

1. **Gaussian fitting:** Fit normal distribution to historical price deltas
2. **Score tracking:** Confidence metric alongside price prediction
3. **Caching:** Store predictions per index to avoid redundant computation
4. **Time-based limits:** De-duplicate predictions within time windows (15m→5 calls, 60m→10 calls, 240m→30 calls)

### Callback-Driven Training

Training uses Keras callbacks:
- **ModelCheckpoint** — Saves best model based on validation accuracy
- **TensorBoard** — Logs training metrics for visualization
- **CSVLogger** — Exports epoch-level metrics to CSV

---

## 7. Potential Improvements

1. **Add Early Stopping to Training**
   - Monitor validation loss and stop if no improvement for N epochs
   - Would prevent overfitting and save training time

2. **Implement Model Ensembling**
   - Combine predictions from multiple model architectures
   - Weight ensemble members by validation performance
   - Would improve robustness and accuracy

3. **Add Data Augmentation**
   - Generate synthetic variations of training data (noise injection, resampling)
   - Increases effective training set size
   - Would improve model generalization on unseen data

4. **Introduce Adaptive Learning Rates**
   - Use learning rate schedules that decrease over time
   - Adjust based on training loss plateau detection
   - Would enable finer convergence in later epochs

5. **Add Cross-Validation**
   - Train multiple folds of the same dataset
   - Average predictions across folds for robustness
   - Would provide confidence metrics for inference

6. **Implement Online Learning**
   - Update model weights incrementally as new data arrives
   - Store recent data in rolling buffer
   - Would support continuous model refinement without full retraining

7. **Add Feature Importance Analysis**
   - Use gradient-based methods to rank feature contribution
   - Identify which indicators drive decisions
   - Would support feature engineering improvements

8. **Parallelize Batch Predictions**
   - Use GPU acceleration for batch inference
   - Multi-threaded prediction for multiple model architectures
   - Would accelerate backtest simulation_nn() phase

9. **Add Model Validation & Monitoring**
   - Track prediction performance on holdout test set
   - Alert if validation accuracy drops below threshold
   - Would catch model degradation in live trading

10. **Support Multiple Target Types**
    - Train separate models for different prediction horizons (1h, 4h, 8h)
    - Aggregate predictions across horizons
    - Would improve multi-timeframe strategy coordination
