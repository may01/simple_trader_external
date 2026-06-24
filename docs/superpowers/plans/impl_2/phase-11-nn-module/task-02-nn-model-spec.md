# Task 02: NNModelSpec (Declarative Model Definition)

**Phase:** 11 — NN Module  
**Depends on:** Task 01 (device)  
**Produces:** `nn/nn_model_spec.py` (NNModelSpec/LayerSpec/GroupingSpec/TargetSpec, spec_hash, from_yaml), `configs/nn_spec.yaml`

---

## Goal

Implement the declarative model-definition layer for the NN module: four dataclasses (`NNModelSpec`, `LayerSpec`, `GroupingSpec`, `TargetSpec`) plus a content-addressed `spec_hash` and a `NNModelSpec.from_yaml()` loader. The spec is the **single source of truth** consumed by `NNModel.build()`, `NNDataset`, the training loop, and inference. Two models differ only by their specs.

---

## Context

This spec replaces the old hardcoded `nn_tf_type` / `get_generic_model` / `get_hack_*` variants — there are no architecture variants in code anymore. The whole model (input grouping, network depth/layers, history window, which indicators and timeframes feed it, which targets it predicts, and every learning parameter) is now defined declaratively by one `NNModelSpec`. This makes models reproducible (a spec hash identifies a model), searchable (the agentic training loop mutates spec fields), and serialisable (the spec is saved alongside the weights). It is a prerequisite for `NNModel`, `NNDataset`, and `NNOrchestrator`. Direction/label targets are sourced from the profit-labels pipeline (Phase 03 Task 07); regression targets are computed from price.

---

## Files

- Create: `nn/nn_model_spec.py`
- Create: `configs/nn_spec.yaml`

---

## Interface

### `LayerSpec`

| Field | Type | Description |
|-------|------|-------------|
| `kind` | `str` | `"dense"` \| `"lstm"` \| `"gru"` \| `"conv1d"` |
| `units` | `int` | layer width / hidden units |
| `params` | `dict` | kind-specific kwargs (`kernel_size`, `bidirectional`, …) |

```python
@dataclass
class LayerSpec:
    kind: str          # "dense" | "lstm" | "gru" | "conv1d"
    units: int
    params: dict = field(default_factory=dict)
```

### `GroupingSpec`

| Field | Type | Description |
|-------|------|-------------|
| `mode` | `str` | `"single"` (default, one model over all rows) \| `"by_indicator"` (one model per class/regime) |
| `column` | `str \| None` | by_indicator only — timeframe-indicator column, e.g. `"60_vol_regime"` |
| `bins` | `list[float] \| None` | by_indicator only — numeric edges → classes |
| `classes` | `list \| None` | by_indicator only — explicit categorical values → classes |

```python
@dataclass
class GroupingSpec:
    mode: str = "single"               # "single" | "by_indicator"
    column: str | None = None          # e.g. "60_vol_regime"
    bins: list[float] | None = None    # numeric edges → classes, OR
    classes: list | None = None        # explicit categorical values → classes
```

### `TargetSpec`

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | unique label, used in output column names (`nn_res_{name}_*`) |
| `kind` | `str` | `"direction"` \| `"label"` \| `"regression"` |
| `horizons` | `list[int]` | N candles ahead; `>1` entry = multi-horizon (one head per horizon) |
| `label_tf` | `int \| None` | direction/label — tf of the profit-label column to read |
| `label_m` | `float \| None` | direction/label — target size (atr_ma units), selects the label spec |
| `label_x` | `float \| None` | direction/label — stop size (atr_ma units) |
| `strict` | `bool` | direction/label — read `pslong`/`psshort` vs `plong`/`pshort` |
| `transform` | `str` | regression only — `"logret"` |

```python
@dataclass
class TargetSpec:
    name: str          # nn_res_{name}_*
    kind: str          # "direction" | "label" | "regression"
    horizons: list[int] = field(default_factory=lambda: [1])

    # direction / label (sourced from profit-labels pipeline, Phase 03 Task 07):
    label_tf: int | None = None
    label_m: float | None = None
    label_x: float | None = None
    strict: bool = False

    # regression (computed from price):
    transform: str = "logret"
```

### `NNModelSpec`

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | human label |
| `grouping` | `GroupingSpec` | how to partition rows into classes/regimes |
| `timeframes` | `list[int]` | which TFs feed the model (input), e.g. `[15, 60]` |
| `indicators` | `list[str]` | base + `nn_features` columns to include |
| `history_points` | `int` | lookback window N (candles of context), default `32` |
| `layers` | `list[LayerSpec]` | ordered hidden layers |
| `activation` | `str` | `"relu"` (default) \| `"gelu"` \| `"tanh"` \| … |
| `dropout` | `float` | default `0.0` |
| `targets` | `list[TargetSpec]` | one or more output heads (jointly trained) |
| `loss_fn` | `str` | `"auto"` (per-target default) or override |
| `optimizer` | `str` | default `"adam"` |
| `learning_rate` | `float` | default `1e-3` |
| `weight_decay` | `float` | default `0.0` |
| `batch_size` | `int` | default `32` |
| `epochs` | `int` | default `100` |
| `validation_split` | `float` | default `0.2` |
| `val_strategy` | `str` | `"time_holdout"` (default) \| `"random"` \| `"kfold"` |
| `early_stopping_patience` | `int \| None` | default `10` |
| `class_weight` | `str` | for classification targets, default `"balanced"` |
| `device` | `str` | `"auto"` (default) \| `"cuda"` \| `"cpu"` |
| `seed` | `int` | default `0` |
| `spec_hash` | `str` (derived) | sha256 of normalised fields — not user-set |

```python
@dataclass
class NNModelSpec:
    # --- Identity ---
    name: str
    # spec_hash is derived (sha256 of normalised fields) — see below

    # --- Data grouping ---
    grouping: GroupingSpec = field(default_factory=GroupingSpec)
    timeframes: list[int] = field(default_factory=list)   # e.g. [15, 60]
    indicators: list[str] = field(default_factory=list)
    history_points: int = 32

    # --- Architecture ---
    layers: list[LayerSpec] = field(default_factory=list)
    activation: str = "relu"            # "relu" | "gelu" | "tanh" | ...
    dropout: float = 0.0

    # --- Targets ---
    targets: list[TargetSpec] = field(default_factory=list)

    # --- Learning parameters ---
    loss_fn: str = "auto"
    optimizer: str = "adam"
    learning_rate: float = 1e-3
    weight_decay: float = 0.0
    batch_size: int = 32
    epochs: int = 100
    validation_split: float = 0.2
    val_strategy: str = "time_holdout"  # "time_holdout" | "random" | "kfold"
    early_stopping_patience: int | None = 10
    class_weight: str = "balanced"

    # --- Runtime ---
    device: str = "auto"                # "auto" | "cuda" | "cpu"
    seed: int = 0

    @property
    def spec_hash(self) -> str: ...
        # sha256 hex digest over the canonically-normalised spec fields.
        # device and seed are excluded from the hash (runtime-only, not
        # architecture/data identity). Returned full hex; callers slice
        # [:8] for short labels and use the full digest to key
        # datasets/checkpoints/tracker records.

    @classmethod
    def from_yaml(cls, path: str = "configs/nn_spec.yaml") -> "NNModelSpec": ...
        # Parse the YAML at `path`; build nested GroupingSpec / LayerSpec /
        # TargetSpec from their sub-mappings; coerce types (timeframes →
        # list[int], horizons → list[int]); apply dataclass defaults for
        # absent keys. Returns a fully-populated NNModelSpec.
```

---

## Key Constraints

- `spec_hash` is **content-addressed** (drives `checkpoints/{spec_hash}` and `datasets/` keys); **normalise fields before hashing** — sort/canonicalise nested dataclasses, dicts, and lists so logically-equal specs hash identically. Exclude runtime-only fields (`device`, `seed`) from the hash; they do not change model identity.
- `TargetSpec` out-column naming (timeframe-agnostic): direction → `nn_res_{name}_prob_up` / `nn_res_{name}_prob_neutral` / `nn_res_{name}_prob_down`; label (binary) → `nn_res_{name}_prob`; regression → `nn_res_{name}`. Multi-horizon (`horizons=[h1,h2,…]`) adds `_h{hk}` after `{name}`, e.g. `nn_res_{name}_h{hk}_prob_up`.
- **No `{tf}_` prefix on outputs** — the model always ingests all of `spec.timeframes` as input and emits one timeframe-agnostic `nn_res_*` output set.
- `grouping` partitions **training rows**, not the input: `mode="single"` = one model over all rows; `mode="by_indicator"` splits rows by `column` (via `bins` or `classes`) and the orchestrator trains one model per class. All class models share the same `nn_res_*` schema.
- Head width and loss default follow `kind`: `direction` → softmax / cross-entropy (3-class up/neutral/down from the long+short pair); `label` → sigmoid / BCE (single profit-label column); `regression` → linear / Huber. Multiple `TargetSpec`s = multiple heads trained jointly.
- Dataclasses must round-trip via `from_yaml` and be serialisable (saved alongside weights so a checkpoint rebuilds without external config).

---

## Verification

```bash
docker compose run --rm nn-train python3 -c "from nn.nn_model_spec import NNModelSpec; s=NNModelSpec.from_yaml('configs/nn_spec.yaml'); print(s.spec_hash[:8], s.timeframes, [t.name for t in s.targets])"
```

---

## Commit

`feat(nn): NNModelSpec declarative model definition + nn_spec.yaml`
