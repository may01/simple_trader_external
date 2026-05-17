# TrainingCoordinator Class Specification

**Class:** `TrainingCoordinator` (Proposed Refactoring)  
**Files:** `trainer.py` (train, group_nn, train_nn methods, lines 700-900)  
**Purpose:** Orchestrate neural network training pipelines: data grouping, model instantiation, training execution, and result management.

---

## 1. Class Overview

The `TrainingCoordinator` class is a proposed refactoring of the current NN training orchestration in trainer.py. It encapsulates the multi-step NN training pipeline: grouping generated data points by classification, instantiating NNModel instances for each class/timeframe/target combination, training models via backpropagation, and managing checkpoints.

TrainingCoordinator serves as the coordination layer between raw data points and trained models, abstracting the complexity of multi-dimensional model configurations.

---

## 2. Key Attributes

### Instance Variables

| Attribute | Type | Description |
|-----------|------|-------------|
| `pair` | `str` | Trading pair (e.g., `link_usdt`) |
| `data_root` | `str` | Root data folder path |
| `class_types` | `list` | NN classification types to train (e.g., [NN_POINT_CLASS_BIG, NN_POINT_CLASS_SMALL]) |
| `target_types` | `list` | NN target indices to train (0-17) |
| `nn_types` | `list` | NN architecture types to train (NN_TYPE_ALL, NN_TYPE_BIG, NN_TYPE_SMALL, NN_TYPE_REG) |
| `nn_history` | `int` | Historical candle window size (default 120) |
| `models_trained` | `dict` | Tracks trained models: {(class_type, class_name, nn_type, target_idx): NN instance} |
| `training_metrics` | `dict` | Per-model training statistics: loss, accuracy, etc. |

---

## 3. Constructor

### `__init__(pair, class_types=None, target_types=None, nn_types=None, nn_history=120)`

**Purpose:** Initialize TrainingCoordinator with configuration.

**Parameters:**
- `pair` (`str`) — Trading pair
- `class_types` (`list[int]`) — Classifications to train. Default: [NN_POINT_CLASS_BIG]
- `target_types` (`list[int]`) — NN target indices (0-17). Default: [0]
- `nn_types` (`list[int]`) — Architectures to train. Default: [NN_TYPE_ALL]
- `nn_history` (`int`) — History window. Default: 120

**Behavior:**
1. Store configuration parameters
2. Extract data_root from environment
3. Initialize tracking dicts: models_trained, training_metrics
4. Validate configuration (non-empty lists, valid indices)

---

## 4. Key Methods & Interfaces

### `group_data(shuffle=False)`

**Purpose:** Load all generated data points, group by classification, save grouped pickles.

**Parameters:**
- `shuffle` (`bool`) — Shuffle within groups. Default: False

**Behavior:**
1. Iterate through all data points in time order
2. For each point:
   - Load NN point data (features, targets, timestamp)
   - Extract classification (e.g., NN_POINT_CLASS_BIG)
   - Append to group list
3. When group reaches size threshold (5000) or iteration ends:
   - Optionally shuffle
   - Save to pickle: `nn_group_{class_type}_{class_name}_{group_num}.pkl`
   - Reset group

**Returns:** `dict` with summary:
- `"total_points"` — Points processed
- `"groups_created"` — Pickle files created
- `"group_sizes"` — Sizes per group

### `train_models(epochs=15, batch_size=32, validation_split=0.30)`

**Purpose:** Train all configured model combinations.

**Parameters:**
- `epochs` (`int`) — Training epochs
- `batch_size` (`int`) — Batch size
- `validation_split` (`float`) — Validation fraction

**Behavior:**
1. For each class_type in self.class_types:
2. For each target_type in self.target_types:
3. For each nn_type in self.nn_types:
   - Instantiate NN: `nn = NN(pair, class_type, class_name, nn_type, target_type, nn_history)`
   - Call `nn.train(data_group_num)` with appropriate grouped data
   - Track metrics: loss, accuracy, training time
   - Save model via checkpoint

**Returns:** `dict` with training summary:
- `"models_trained"` — Count
- `"training_time"` — Total seconds
- `"average_accuracy"` — Mean validation accuracy
- `"failed_models"` — Count of failed training runs

### `validate_models(test_split=0.20)`

**Purpose:** Evaluate trained models on holdout test set.

**Parameters:**
- `test_split` (`float`) — Fraction reserved for testing

**Behavior:**
1. For each trained model:
   - Load test data
   - Call `nn.run_batch(test_data)`
   - Compute accuracy, precision, recall
   - Compare predictions vs. actual targets
2. Aggregate statistics

**Returns:** `dict` with validation results:
- `"model_accuracies"` — Per-model accuracy
- `"average_accuracy"` — Mean across all models
- `"worst_model"` — Lowest-performing model
- `"best_model"` — Highest-performing model

### `get_trained_model(class_type, class_name, nn_type, target_idx)`

**Purpose:** Retrieve trained model for inference.

**Parameters:**
- `class_type` (`int`) — Classification
- `class_name` (`str`) — Subclass
- `nn_type` (`int`) — Architecture type
- `target_idx` (`int`) — Target index

**Return Value:** `NN` instance with loaded weights, or None if not trained

---

## 5. State Management

- **Uninitialized:** Just created
- **Grouped:** Data points grouped into training batches
- **Training:** `train_models()` in progress
- **Trained:** All models persisted; ready for inference

---

## 6. Error Handling

**Missing Grouped Data:**
```python
if not os.path.exists(group_file):
    logger.warning(f"Group not found: {group_file}, skipping model")
    continue
```

**Training Failure:**
```python
try:
    nn.train(group_num)
except Exception as e:
    logger.error(f"Training failed for {model_config}: {e}")
    failed_models.append(model_config)
    continue
```

---

## 7. Existing Approach

Current implementation:
- `group_nn(class_type)` — Standalone method in Trainer
- `train_nn()` — Environment variable-based configuration
- Direct NN instantiation without abstraction

Limitations:
- Hard-coded loop over class types/targets/architectures
- No coordination or progress tracking
- Tight coupling to Trainer
- Difficult to reuse in different contexts

---

## 8. Potential Improvements

1. **Add Parallel Training**
   - Train multiple models simultaneously (different architectures)
   - Would reduce wall-clock time on multi-GPU systems

2. **Implement Early Stopping**
   - Monitor validation loss, stop if no improvement for N epochs
   - Would prevent overfitting

3. **Add Model Versioning**
   - Track model versions with timestamps
   - Allow rollback to previous models
   - Would support experimentation

4. **Implement Hyperparameter Tuning**
   - Grid search or Bayesian optimization over hyperparameters
   - Track best configuration
   - Would improve model performance

5. **Add Cross-Validation**
   - K-fold validation across different time windows
   - Would provide robust performance estimates

6. **Implement Distributed Training**
   - Support training across multiple machines
   - Would enable larger datasets

7. **Add Model Pruning**
   - Remove low-importance weights post-training
   - Would reduce inference latency

8. **Implement Ensemble Methods**
   - Combine predictions from multiple models
   - Would improve robustness

9. **Add Automated Hyperparameter Selection**
   - Suggest learning rate, layers, etc. based on data
   - Would reduce manual tuning

10. **Implement Model Registry**
    - Central tracking of all trained models
    - Would improve model lifecycle management
