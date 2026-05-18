# Phase 6b: Training + NN Implementation Plan (PARALLEL — Agent B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Depends on Phase 5. Runs in parallel with Phase 6a.

**Goal:** Implement `DataPointGenerator` (NN feature vectors), `TrainingCoordinator` (batch training), `ResultAggregator` (thread results), `Trainer` (orchestrator), `NNModel` (PyTorch LSTM), `NNPredictor` (inference), `CheckpointManager` (model persistence).

**Architecture:** `Trainer` orchestrates four modes: `generate_full_ohlc`, `generate_data_points`, `train`, `simulate`. `NNModel` is a single-layer LSTM predicting price direction. `NNPredictor` wraps the model for inference. Tests mock torch where needed to keep CI fast.

**Tech Stack:** torch>=2.0, pandas, numpy. Tests stub torch model to avoid GPU dependency.

---

## Working Directory

```
⚠️ All relative paths and bash commands below resolve from this directory.
```

| Branch type | Working directory |
|-------------|-------------------|
| `main` branch | `/home/om/projects/simple_trader/main` |
| Worktree branch | `/home/om/projects/simple_trader/worktrees/<branch-name>/` |

For parallel phases (3a+3b, 6a+6b): each agent creates its own worktree under `/home/om/projects/simple_trader/worktrees/` using the `superpowers:using-git-worktrees` skill, then works entirely within that directory.

---

## File Structure

```
src/simple_trader/training/
  __init__.py
  data_point_generator.py
  training_coordinator.py
  result_aggregator.py
  trainer.py
src/simple_trader/nn/
  __init__.py
  nn_model.py
  nn_predictor.py
  checkpoint_manager.py
tests/training/
  __init__.py
  test_data_point_generator.py
  test_training_coordinator.py
  test_result_aggregator.py
  test_trainer.py
tests/nn/
  __init__.py
  test_nn_model.py
  test_nn_predictor.py
  test_checkpoint_manager.py
```

---

## Task 0: Directory Setup

- [ ] **Step 1: Create directories**

```bash
mkdir -p src/simple_trader/training src/simple_trader/nn
mkdir -p tests/training tests/nn
touch src/simple_trader/training/__init__.py src/simple_trader/nn/__init__.py
touch tests/training/__init__.py tests/nn/__init__.py
```

---

## Task 1: DataPointGenerator

Converts a `DataPoint` snapshot into a flat feature vector for NN training.

**Files:**
- Create: `src/simple_trader/training/data_point_generator.py`
- Create: `tests/training/test_data_point_generator.py`

- [ ] **Step 1: Write failing test**

`tests/training/test_data_point_generator.py`:

```python
import pytest
import pandas as pd
import numpy as np
from simple_trader.training.data_point_generator import DataPointGenerator
from simple_trader.data.data_point import LiveDataPoint


def _make_point(tfs: list, rows: int = 10) -> LiveDataPoint:
    ohlc = {}
    for tf in tfs:
        ohlc[tf] = pd.DataFrame({
            f"{tf}_close":  np.ones(rows) * 15.0,
            f"{tf}_rsi_14": np.ones(rows) * 50.0,
            f"{tf}_cci_20": np.ones(rows) * 0.0,
            f"{tf}_ema_25": np.ones(rows) * 15.0,
        })
    return LiveDataPoint(ohlc)


def test_generator_returns_list_of_floats():
    gen = DataPointGenerator(tfs=[1, 15], cols=["close", "rsi_14"])
    point = _make_point([1, 15])
    features = gen.generate(point)
    assert isinstance(features, list)
    assert all(isinstance(f, float) for f in features)


def test_generator_feature_count_matches_tfs_times_cols():
    tfs = [1, 15]
    cols = ["close", "rsi_14", "cci_20"]
    gen = DataPointGenerator(tfs=tfs, cols=cols)
    point = _make_point(tfs)
    features = gen.generate(point)
    assert len(features) == len(tfs) * len(cols)


def test_generator_uses_shift_zero_by_default():
    gen = DataPointGenerator(tfs=[1], cols=["close"])
    ohlc = {1: pd.DataFrame({"1_close": [10.0, 20.0, 30.0]})}
    point = LiveDataPoint(ohlc)
    features = gen.generate(point)
    assert features[0] == pytest.approx(30.0)


def test_generator_normalize_scales_to_zero_one():
    gen = DataPointGenerator(tfs=[1], cols=["rsi_14"], normalize=True)
    # RSI is 0-100; value 50 → 0.5
    ohlc = {1: pd.DataFrame({"1_rsi_14": [50.0]})}
    point = LiveDataPoint(ohlc)
    features = gen.generate(point)
    # With min=0, max=100 normalization: 50/100 = 0.5
    assert 0.0 <= features[0] <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/training/test_data_point_generator.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.training.data_point_generator'`

- [ ] **Step 3: Write `src/simple_trader/training/data_point_generator.py`**

```python
from typing import Dict, List, Optional, Tuple
from ..data.data_point import DataPoint

# Feature normalization bounds per column name (min, max)
_NORM_BOUNDS: Dict[str, Tuple[float, float]] = {
    "rsi_14": (0.0, 100.0),
    "cci_20": (-200.0, 200.0),
    "close":  (0.0, 1.0),    # relative; callers normalize price separately
}


class DataPointGenerator:
    """
    Converts a DataPoint snapshot into a flat feature vector.

    Features are ordered: for each tf in tfs, for each col in cols: value at shift=0.
    normalize=True scales using known bounds (RSI 0-100, CCI ±200, etc.).
    """

    def __init__(
        self,
        tfs: List[int],
        cols: List[str],
        normalize: bool = False,
    ) -> None:
        self.tfs = tfs
        self.cols = cols
        self.normalize = normalize

    def generate(self, data_point: DataPoint) -> List[float]:
        features: List[float] = []
        for tf in self.tfs:
            for col in self.cols:
                val = data_point.get(col, tf, shift=0)
                if self.normalize:
                    val = self._normalize(col, val)
                features.append(float(val))
        return features

    def _normalize(self, col: str, val: float) -> float:
        bounds = _NORM_BOUNDS.get(col)
        if bounds is None:
            return val
        lo, hi = bounds
        if hi == lo:
            return 0.0
        return (val - lo) / (hi - lo)

    @property
    def feature_count(self) -> int:
        return len(self.tfs) * len(self.cols)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/training/test_data_point_generator.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/training/data_point_generator.py tests/training/test_data_point_generator.py
git commit -m "feat: add DataPointGenerator for NN feature vector construction"
```

---

## Task 2: ResultAggregator

**Files:**
- Create: `src/simple_trader/training/result_aggregator.py`
- Create: `tests/training/test_result_aggregator.py`

- [ ] **Step 1: Write failing test**

`tests/training/test_result_aggregator.py`:

```python
from simple_trader.training.result_aggregator import ResultAggregator


def test_aggregator_starts_empty():
    agg = ResultAggregator()
    assert agg.total_revenue_pct == 0.0


def test_aggregator_add_thread_result():
    agg = ResultAggregator()
    agg.add(thread=0, revenue_pct=0.05)
    assert agg.total_revenue_pct == 0.05


def test_aggregator_sums_across_threads():
    agg = ResultAggregator()
    agg.add(thread=0, revenue_pct=0.05)
    agg.add(thread=1, revenue_pct=0.03)
    assert abs(agg.total_revenue_pct - 0.08) < 1e-9


def test_aggregator_best_thread():
    agg = ResultAggregator()
    agg.add(0, 0.02)
    agg.add(1, 0.08)
    agg.add(2, 0.05)
    assert agg.best_thread() == 1


def test_aggregator_results_per_thread():
    agg = ResultAggregator()
    agg.add(0, 0.02)
    agg.add(0, 0.03)
    assert len(agg.get_thread_results(0)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/training/test_result_aggregator.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write `src/simple_trader/training/result_aggregator.py`**

```python
from collections import defaultdict
from typing import Dict, List


class ResultAggregator:
    """Collects simulation/training results from parallel threads."""

    def __init__(self) -> None:
        self._results: Dict[int, List[float]] = defaultdict(list)

    def add(self, thread: int, revenue_pct: float) -> None:
        self._results[thread].append(revenue_pct)

    def get_thread_results(self, thread: int) -> List[float]:
        return list(self._results[thread])

    @property
    def total_revenue_pct(self) -> float:
        return sum(v for vals in self._results.values() for v in vals)

    def best_thread(self) -> int:
        return max(self._results, key=lambda t: sum(self._results[t]))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/training/test_result_aggregator.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/training/result_aggregator.py tests/training/test_result_aggregator.py
git commit -m "feat: add ResultAggregator for parallel thread result collection"
```

---

## Task 3: NNModel (PyTorch LSTM)

**Files:**
- Create: `src/simple_trader/nn/nn_model.py`
- Create: `tests/nn/test_nn_model.py`

- [ ] **Step 1: Add torch to requirements**

Add to `requirements.txt`:
```
torch>=2.0
```

- [ ] **Step 2: Write failing test**

`tests/nn/test_nn_model.py`:

```python
import pytest
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

pytestmark = pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch not installed")

from simple_trader.nn.nn_model import NNModel


def test_model_forward_returns_correct_shape():
    model = NNModel(input_size=12, hidden_size=64, output_size=3)
    x = torch.randn(1, 10, 12)   # (batch, seq_len, input_size)
    out = model(x)
    assert out.shape == (1, 3)


def test_model_output_is_probabilities():
    import torch.nn.functional as F
    model = NNModel(input_size=12, hidden_size=64, output_size=3)
    x = torch.randn(1, 10, 12)
    out = model(x)
    probs = F.softmax(out, dim=-1)
    assert abs(probs.sum().item() - 1.0) < 1e-5


def test_model_forward_batch():
    model = NNModel(input_size=8, hidden_size=32, output_size=2)
    x = torch.randn(16, 10, 8)
    out = model(x)
    assert out.shape == (16, 2)
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/nn/test_nn_model.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.nn.nn_model'`

- [ ] **Step 4: Write `src/simple_trader/nn/nn_model.py`**

```python
import torch
import torch.nn as nn


class NNModel(nn.Module):
    """
    Single-layer LSTM predicting market direction.

    Input:  (batch, seq_len, input_size) — sequence of feature vectors
    Output: (batch, output_size) — logits for each class (e.g. UP/DOWN/FLAT)

    Training uses CrossEntropyLoss. Inference: argmax of softmax output.
    """

    def __init__(
        self,
        input_size: int,
        hidden_size: int = 128,
        output_size: int = 3,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=1,
            batch_first=True,
            dropout=0.0,
        )
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, output_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        out = self.dropout(out[:, -1, :])   # take last time step
        return self.fc(out)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/nn/test_nn_model.py -v
```

Expected: `3 passed` (or skip if torch not installed)

- [ ] **Step 6: Commit**

```bash
git add src/simple_trader/nn/nn_model.py tests/nn/test_nn_model.py
git commit -m "feat: add NNModel LSTM for market direction prediction"
```

---

## Task 4: CheckpointManager

**Files:**
- Create: `src/simple_trader/nn/checkpoint_manager.py`
- Create: `tests/nn/test_checkpoint_manager.py`

- [ ] **Step 1: Write failing test**

`tests/nn/test_checkpoint_manager.py`:

```python
import pytest
from pathlib import Path
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

pytestmark = pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch not installed")

from simple_trader.nn.nn_model import NNModel
from simple_trader.nn.checkpoint_manager import CheckpointManager


def test_save_and_load_roundtrip(tmp_path):
    model = NNModel(input_size=8, hidden_size=32, output_size=2)
    ckpt = CheckpointManager(checkpoint_dir=tmp_path)
    ckpt.save(model, epoch=1)

    loaded = NNModel(input_size=8, hidden_size=32, output_size=2)
    ckpt.load(loaded, epoch=1)

    # Parameters should match
    for p1, p2 in zip(model.parameters(), loaded.parameters()):
        assert torch.allclose(p1, p2)


def test_save_creates_file(tmp_path):
    model = NNModel(input_size=4, hidden_size=16, output_size=2)
    ckpt = CheckpointManager(checkpoint_dir=tmp_path)
    ckpt.save(model, epoch=5)
    assert (tmp_path / "checkpoint_epoch_5.pt").exists()


def test_latest_epoch_returns_max(tmp_path):
    model = NNModel(input_size=4, hidden_size=16, output_size=2)
    ckpt = CheckpointManager(checkpoint_dir=tmp_path)
    ckpt.save(model, epoch=1)
    ckpt.save(model, epoch=3)
    ckpt.save(model, epoch=2)
    assert ckpt.latest_epoch() == 3


def test_latest_epoch_none_when_no_checkpoints(tmp_path):
    ckpt = CheckpointManager(checkpoint_dir=tmp_path)
    assert ckpt.latest_epoch() is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/nn/test_checkpoint_manager.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.nn.checkpoint_manager'`

- [ ] **Step 3: Write `src/simple_trader/nn/checkpoint_manager.py`**

```python
from pathlib import Path
from typing import Optional
import torch
import torch.nn as nn


class CheckpointManager:
    """Saves and loads PyTorch model checkpoints by epoch number."""

    def __init__(self, checkpoint_dir: Path) -> None:
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, epoch: int) -> Path:
        return self.checkpoint_dir / f"checkpoint_epoch_{epoch}.pt"

    def save(self, model: nn.Module, epoch: int) -> None:
        torch.save(model.state_dict(), self._path(epoch))

    def load(self, model: nn.Module, epoch: int) -> None:
        state = torch.load(self._path(epoch), map_location="cpu")
        model.load_state_dict(state)

    def latest_epoch(self) -> Optional[int]:
        checkpoints = list(self.checkpoint_dir.glob("checkpoint_epoch_*.pt"))
        if not checkpoints:
            return None
        return max(
            int(p.stem.replace("checkpoint_epoch_", ""))
            for p in checkpoints
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/nn/test_checkpoint_manager.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/nn/checkpoint_manager.py tests/nn/test_checkpoint_manager.py
git commit -m "feat: add CheckpointManager for epoch-based model persistence"
```

---

## Task 5: NNPredictor

**Files:**
- Create: `src/simple_trader/nn/nn_predictor.py`
- Create: `tests/nn/test_nn_predictor.py`

- [ ] **Step 1: Write failing test**

`tests/nn/test_nn_predictor.py`:

```python
import pytest
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

pytestmark = pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch not installed")

from simple_trader.nn.nn_model import NNModel
from simple_trader.nn.nn_predictor import NNPredictor


def test_predictor_predict_returns_class_int():
    model = NNModel(input_size=4, hidden_size=16, output_size=3)
    predictor = NNPredictor(model)
    features = [0.5, 0.3, 0.7, 0.2]
    prediction = predictor.predict(features, seq_len=1)
    assert isinstance(prediction, int)
    assert 0 <= prediction < 3


def test_predictor_predict_proba_sums_to_one():
    model = NNModel(input_size=4, hidden_size=16, output_size=3)
    predictor = NNPredictor(model)
    features = [0.5, 0.3, 0.7, 0.2]
    probs = predictor.predict_proba(features, seq_len=1)
    assert abs(sum(probs) - 1.0) < 1e-5


def test_predictor_eval_mode_disables_dropout():
    model = NNModel(input_size=4, hidden_size=16, output_size=3, dropout=0.5)
    predictor = NNPredictor(model)
    # Two predictions of same input should be identical (dropout off in eval)
    features = [0.5, 0.3, 0.7, 0.2]
    p1 = predictor.predict_proba(features, seq_len=1)
    p2 = predictor.predict_proba(features, seq_len=1)
    assert p1 == p2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/nn/test_nn_predictor.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.nn.nn_predictor'`

- [ ] **Step 3: Write `src/simple_trader/nn/nn_predictor.py`**

```python
from typing import List
import torch
import torch.nn.functional as F
from .nn_model import NNModel


class NNPredictor:
    """
    Inference wrapper for NNModel.

    predict() returns the argmax class index.
    predict_proba() returns softmax probabilities for each class.
    Always runs in eval mode — dropout disabled.
    """

    def __init__(self, model: NNModel) -> None:
        self.model = model
        self.model.eval()

    def predict(self, features: List[float], seq_len: int = 1) -> int:
        probs = self.predict_proba(features, seq_len)
        return int(max(range(len(probs)), key=lambda i: probs[i]))

    def predict_proba(self, features: List[float], seq_len: int = 1) -> List[float]:
        input_size = len(features) // seq_len
        x = torch.tensor(features, dtype=torch.float32)
        x = x.view(1, seq_len, input_size)
        with torch.no_grad():
            logits = self.model(x)
            probs = F.softmax(logits, dim=-1)
        return probs.squeeze(0).tolist()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/nn/test_nn_predictor.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Run full Phase 6b suite**

```bash
pytest tests/training/ tests/nn/ -v
```

Expected: `19+ passed, 0 failed`

- [ ] **Step 6: Commit**

```bash
git add src/simple_trader/nn/ src/simple_trader/training/ tests/training/ tests/nn/
git commit -m "feat: add training and NN modules — DataPointGenerator, ResultAggregator, NNModel, NNPredictor, CheckpointManager"
```
