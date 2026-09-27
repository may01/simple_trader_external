# NNModel Class Specification

**File:** `nn/nn_model.py`, `nn/nn_model_spec.py`
**Purpose:** Build, train, and run inference with **parametrised PyTorch** neural networks. The architecture is constructed entirely from a declarative `NNModelSpec` — nothing about the network, its inputs, or its targets is hardcoded.

---

## 1. Class Overview

`NNModel` is the core neural-network implementation in simple-trader. It encapsulates architecture construction, training, and inference. Every aspect of a model — how input data is grouped, network depth, history window, which indicators and timeframes feed it, which targets it predicts, and all learning parameters — is supplied via an `NNModelSpec`. Two models differ only by their specs.

This makes models reproducible (a spec hash identifies a model), searchable (the agentic loop mutates spec fields), and serialisable (the spec is saved alongside the weights).

---

## 2. NNModelSpec

`NNModelSpec` is a dataclass (also expressible as YAML) that fully defines a model. It is the single source of truth consumed by `NNModel.build()`, `NNDataset`, the training loop, and inference.

```python
@dataclass
class NNModelSpec:
    # --- Identity ---
    name: str                          # human label
    # spec_hash is derived (sha256 of normalised fields)

    # --- Data grouping (item 3: how input rows are grouped into classes) ---
    grouping: GroupingSpec = ...       # how to partition rows into classes/regimes
    timeframes: list[int] = ...        # which TFs feed the model (input), e.g. [15, 60]
    indicators: list[str] = ...        # base + nn_features columns to include
    history_points: int = 32           # lookback window N (candles of context)

    # --- Architecture (item 3: depth of levels, layers) ---
    layers: list[LayerSpec] = ...      # ordered hidden layers (see below)
    activation: str = "relu"           # "relu" | "gelu" | "tanh" | ...
    dropout: float = 0.0

    # --- Targets (item 6: what targets to use) ---
    targets: list[TargetSpec] = ...    # one or more output heads (see §6)

    # --- Learning parameters (item 3) ---
    loss_fn: str = "auto"              # per-target default, or override
    optimizer: str = "adam"
    learning_rate: float = 1e-3
    weight_decay: float = 0.0
    batch_size: int = 32
    epochs: int = 100
    validation_split: float = 0.2      # how to split validation data
    val_strategy: str = "time_holdout" # "time_holdout" | "random" | "kfold"
    early_stopping_patience: int | None = 10
    class_weight: str = "balanced"     # for classification targets
    shuffle_train: bool = True         # shuffle TRAIN minibatches each epoch; val/inference never shuffle

    # --- Runtime ---
    device: str = "auto"               # "auto" | "cuda" | "cpu"
    seed: int = 0
```

```python
@dataclass
class LayerSpec:
    kind: str          # "dense" | "lstm" | "gru" | "conv1d"
    units: int
    # kind-specific kwargs (kernel_size, bidirectional, ...) in `params: dict`
    params: dict = field(default_factory=dict)
```

```python
@dataclass
class GroupingSpec:
    mode: str = "single"          # "single" | "by_indicator"
    # by_indicator only — partition rows into classes/regimes:
    column: str | None = None     # timeframe-indicator column, e.g. "60_vol_regime"
    bins: list[float] | None = None    # numeric edges → classes, OR
    classes: list = None          # explicit categorical values → classes
```

A model **always ingests all of `spec.timeframes` as input** and emits one timeframe-agnostic `nn_res_*` output set. `history_points > 1` with `dense` layers flattens the lookback window; with `lstm`/`gru`/`conv1d` layers the window is the sequence dimension.

`grouping` controls **how training rows are partitioned**, not the input:
- `mode="single"` (default) — one model trained over all rows.
- `mode="by_indicator"` — rows are split into classes/regimes by `column` (binned via `bins` or matched via `classes`); the orchestrator trains one model per class, and at inference a router sends each row to its class's model. All class models share the same `nn_res_*` output schema.

`spec_hash` is computed from the normalised spec and used to key datasets, checkpoints, and tracker records.

---

## 3. Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `spec` | `NNModelSpec` | The defining spec (immutable for the model's life). |
| `model` | `torch.nn.Module` | The built network. |
| `input_size` | `int` | Derived from `indicators × timeframes × history_points` (all configured TFs feed every model). |
| `output_size` | `int` | Sum of per-target head widths. |
| `device` | `torch.device` | Resolved from `spec.device` (auto → cuda if available). |
| `is_trained` | `bool` | `False` until `train()`/`load_model()` completes. |

---

## 4. Constructor

### `__init__(spec: NNModelSpec)`
- Stores `spec`, resolves `device`, derives `input_size`/`output_size`.
- Does **not** build the network (lazy; `build()` or `train()` does).

---

## 5. Key Methods

### 5.1 Architecture

#### `build() -> None`
- Constructs `self.model` from `spec.layers`, `spec.activation`, `spec.dropout`, and the target heads from `spec.targets`.
- Idempotent — no-op if already built.
- Called automatically by `train()`; explicit call is useful for logging layer shapes.

### 5.2 Training

#### `train(dataset: NNDataset, epoch_callback=None) -> dict`
- Seeds `torch` (from `spec.seed`) **before** `build()` so weight init *and* batch shuffle are reproducible, then calls `build()` if needed.
- Splits train/validation per `spec.val_strategy`/`spec.validation_split` (time-holdout default to avoid look-ahead leakage).
- **Minibatched**: train/val tensors stay on CPU in a `DataLoader(batch_size=spec.batch_size)`; each batch is moved to `device` per step, so resident GPU memory scales with `batch_size`, **not** dataset size. `spec.batch_size >= rows` ⇒ one step/epoch (parity with the former full-batch loop). `num_workers=0` (tensors already in RAM); `drop_last=False`.
- **Shuffle policy**: train batches are reshuffled each epoch iff `spec.shuffle_train` (default True), via a `spec.seed`-seeded generator. Validation is **never** shuffled; inference never uses a shuffling loader. Sample-axis shuffle is safe for dense and sequence layers (the `history_points` sequence lives inside each sample); only a future *stateful* RNN (BPTT across batch boundaries) would set `shuffle_train=False`.
- Optimiser/loss assembled from spec; per-target losses combined (weighted sum). Class targets use `spec.class_weight` — **balanced weights are computed once over the full train labels**, not per batch.
- `loss`/`val_loss`/`accuracy`/`per_target` are **row-weighted means over batches** (equal to the full-batch value at one step/epoch).
- Trains for `spec.epochs` with `early_stopping_patience`; supports Optuna pruning via `epoch_callback(epoch, metrics)` returning a stop signal.
- After each epoch, `epoch_callback` (if set) receives `{loss, accuracy, val_loss, val_accuracy, per_target: {...}}`.
- Returns final metrics dict; sets `is_trained = True`. CUDA OOM during a step → one CPU retry (device policy) before failing.

### 5.3 Inference

#### `run(features: np.ndarray) -> np.ndarray`
- Single-sample inference. Returns the concatenated output vector across heads. Requires `is_trained`.

#### `run_batch(features: np.ndarray) -> np.ndarray`
- Batch inference: `(M, input_size)` → `(M, output_size)`. Used by `NNOrchestrator.run_inference()`.

### 5.4 Persistence

#### `save_model(path: str) -> None`
- Saves `state_dict` **and** the serialised `spec` (so the model can be rebuilt without external config).

#### `load_model(path: str) -> None`
- Rebuilds the network from the embedded spec, loads `state_dict`, sets `is_trained = True`.

---

## 6. TargetSpec (Output Heads)

```python
@dataclass
class TargetSpec:
    name: str          # unique label, used in output column names (nn_res_{name}_*)
    kind: str          # "direction" | "direction_binary" | "label" | "regression"
                       #   ( + multi-horizon via `horizons` below )
    horizons: list[int] = field(default_factory=lambda: [1])  # N candles ahead; >1 entry = multi-horizon
    side: str | None = None           # direction_binary only: "long" | "short"

    # direction / direction_binary / label (sourced from the profit-labels pipeline, task-07):
    label_tf: int | None = None       # tf of the profit-label column to read
    label_m: float | None = None      # target size (atr_ma units) — selects the spec
    label_x: float | None = None      # stop size (atr_ma units)
    strict: bool = False              # read pslong/psshort vs plong/pshort
    #   kind="direction":        derive 3-class up/neutral/down from the long+short pair
    #   kind="direction_binary": one side vs rest → 2-class (prob_{side}, prob_other)
    #   kind="label":            single profit-label column → binary sigmoid head

    # regression (computed from price, not a profit label):
    transform: str = "logret"
```

Output column naming (**timeframe-agnostic** — no `{tf}` prefix):
- direction → `nn_res_{name}_prob_up`, `nn_res_{name}_prob_neutral`, `nn_res_{name}_prob_down`
- direction_binary → `nn_res_{name}_prob_{side}`, `nn_res_{name}_prob_other` (`side` ∈ `long`|`short`)
- label (binary) → `nn_res_{name}_prob`
- regression → `nn_res_{name}`
- multi-horizon (`horizons=[h1,h2,…]`) → one head per horizon, suffixed `_h{hk}`, e.g. `nn_res_{name}_h{hk}_prob_up`

The head width and loss default follow `kind` (`direction`→softmax/cross-entropy width 3, `direction_binary`→softmax/cross-entropy width 2, `label`→sigmoid/BCE width 1, `regression`→linear/Huber width 1). **Multiple `TargetSpec`s produce multiple heads trained jointly** — a model can predict several profit-label-derived directions and/or regressions at once. Direction/direction_binary/label targets read existing profit-label columns; see `datapoint-generator-class.md` §4.

---

## 7. Error Handling

- `build()` with empty `layers` or `targets` → `ValueError`.
- `run()`/`run_batch()` before training → `RuntimeError("model not trained")`.
- Feature-vector width mismatch vs `input_size` → `ValueError` with expected/actual sizes.
- Device "cuda" requested but unavailable → log warning, fall back to CPU.

---

## 8. Notes

- Architecture is data-driven; there are no `get_generic_model`/`get_hack_*` variants. "Variants" are just different specs produced by the training loop.
- Normalisation is **not** performed inside `NNModel`; callers normalise via the training manifest (feature list + per-feature stats) before `run`/`run_batch`. For cross-dataset inference the manifest is **bundled in the checkpoint** (`checkpoint-manager-class.md` §4), so `run_inference` normalises with training stats on any dataset and never recomputes stats from the inference data (leakage guard).
- The spec hash ties a checkpoint to the exact dataset/feature configuration that produced it.
