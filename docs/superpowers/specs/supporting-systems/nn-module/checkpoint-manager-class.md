# CheckpointManager Class Specification

**Class:** `CheckpointManager` (Proposed Refactoring)  
**Files:** `trainer.py`, `nn.py` (checkpoint operations)  
**Purpose:** Manage training checkpoints: save/load model state, track progress, enable resume-from-checkpoint capability.

---

## 1. Class Overview

The `CheckpointManager` class is a proposed refactoring to formalize checkpoint management. Currently, checkpointing is handled ad-hoc via Keras ModelCheckpoint callback and pickle serialization. A dedicated class would provide:

- Unified checkpoint save/load interface
- Progress tracking (iteration N of M)
- Resume-from-checkpoint capability
- Multiple checkpoint strategies (best model, latest model, periodic)
- Checkpoint metadata (timestamp, accuracy, training metrics)

---

## 2. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `checkpoint_dir` | `str` | Directory to store checkpoints |
| `pair` | `str` | Trading pair |
| `model_config` | `dict` | Model identifier: {class_type, class_name, nn_type, target_idx} |
| `checkpoints` | `list[dict]` | List of saved checkpoints with metadata |
| `current_checkpoint` | `dict` | Currently active checkpoint |
| `best_checkpoint` | `dict` | Checkpoint with best validation accuracy |

---

## 3. Constructor

### `__init__(checkpoint_dir, pair, model_config)`

**Purpose:** Initialize CheckpointManager.

**Parameters:**
- `checkpoint_dir` (`str`) — Directory for checkpoint storage
- `pair` (`str`) — Trading pair
- `model_config` (`dict`) — Model configuration (class, type, target)

**Behavior:**
1. Store parameters
2. Create checkpoint directory if not exists
3. Load existing checkpoint metadata
4. Initialize current_checkpoint to most recent or None

---

## 4. Key Methods & Interfaces

### `save_checkpoint(model, epoch, metrics, strategy='best')`

**Purpose:** Save model state and training progress.

**Parameters:**
- `model` — Keras model or weights
- `epoch` (`int`) — Epoch number
- `metrics` (`dict`) — Training metrics (loss, accuracy, etc.)
- `strategy` (`str`) — Save strategy: 'best', 'latest', 'periodic'

**Behavior:**
1. Construct checkpoint filename: `checkpoint_e{epoch}_acc{accuracy}.h5`
2. Save model weights via `model.save()`
3. Save metadata to JSON: {epoch, accuracy, loss, timestamp, file_path}
4. If strategy == 'best': check if accuracy > best_checkpoint['accuracy']
   - If yes: mark as best, keep previous best as backup
5. Append checkpoint metadata to checkpoints list
6. Limit total checkpoints to N most recent (cleanup old)

**Returns:** `str` — Path to saved checkpoint

### `load_checkpoint(checkpoint_id='best')`

**Purpose:** Load model state from checkpoint.

**Parameters:**
- `checkpoint_id` (`str`) — 'best', 'latest', or specific filename

**Behavior:**
1. If checkpoint_id == 'best':
   - Load best_checkpoint path
2. If checkpoint_id == 'latest':
   - Load most recent checkpoint
3. Else:
   - Load specific file by name
4. Load model weights via `keras.models.load_model()`
5. Update current_checkpoint
6. Return model and metadata

**Returns:** `(model, metadata_dict)` or `(None, None)` if not found

### `can_resume()`

**Purpose:** Check if training can be resumed from checkpoint.

**Return Value:** `bool` — True if latest checkpoint exists and has training metadata

### `get_resume_state()`

**Purpose:** Get state to resume training from.

**Return Value:** `dict` with:
- `"model"` — Loaded model
- `"epoch"` — Next epoch to start
- `"metrics"` — Last checkpoint metrics
- `"training_steps"` — Iterations completed

### `cleanup_old_checkpoints(keep_count=5)`

**Purpose:** Remove old checkpoints to save disk space.

**Parameters:**
- `keep_count` (`int`) — Number of recent checkpoints to keep

**Behavior:**
1. Sort checkpoints by timestamp (oldest first)
2. Delete all but last keep_count
3. Update checkpoints list

### `export_checkpoint_history()`

**Purpose:** Get historical performance data.

**Return Value:** `dict` with:
- `"checkpoints"` — List of all saved checkpoints
- `"best_accuracy"` — Peak accuracy achieved
- `"training_epochs"` — Total epochs trained
- `"training_duration"` — Total wall-clock time

---

## 5. State Management

- **No Checkpoint:** Just initialized, no training
- **Has Checkpoints:** Training in progress or completed
- **Can Resume:** Recent checkpoint with complete metadata
- **Best Saved:** Peak-performance model identified

---

## 6. Error Handling

**Missing Checkpoint File:**
```python
if not os.path.exists(path):
    logger.warning(f"Checkpoint not found: {path}")
    return None, None
```

**Corrupted Model:**
```python
try:
    model = keras.models.load_model(path)
except Exception as e:
    logger.error(f"Failed to load model: {e}")
    return None, None
```

---

## 7. Existing Approach

Current implementation:
- Keras ModelCheckpoint callback saves best model automatically
- No dedicated resume-from-checkpoint interface
- Manual cleanup of old checkpoint files

Limitations:
- No programmatic access to checkpoint history
- Can't easily resume training mid-epoch
- No unified interface across training types

---

## 8. Potential Improvements

1. **Add Training State Serialization**
   - Save optimizer state, learning rate schedule
   - Enable true resume without losing momentum

2. **Implement Checkpoint Versioning**
   - Track model version separately from checkpoint
   - Support model evolution tracking

3. **Add Checkpoint Comparison**
   - Compare accuracy/loss across checkpoints
   - Visualize training curves

4. **Support Incremental Saving**
   - Save only weights that changed since last checkpoint
   - Reduce disk usage

5. **Add Checkpoint Pruning**
   - Remove weights below threshold
   - Reduce checkpoint size

6. **Implement Remote Checkpoint Storage**
   - Upload checkpoints to cloud storage
   - Enable distributed training

7. **Add Checkpoint Validation**
   - Checksum verification
   - Model architecture validation

8. **Support Multiple Checkpoint Strategies**
   - Time-based: save every N hours
   - Improvement-based: save only on improvement
   - Periodic: save every N epochs

9. **Add Checkpoint Metadata Indexing**
   - Quick lookup by epoch, accuracy, date
   - Enable efficient checkpoint selection

10. **Implement Distributed Checkpointing**
    - Synchronize checkpoints across training nodes
    - Support fault recovery in distributed training
