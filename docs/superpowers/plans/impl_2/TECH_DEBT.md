# Tech Debt

Known unresolved issues, to be picked up as future tasks. One section per item:
what's wrong, why it was deferred, what resolving it looks like.

## 1. Target fields (`tgt_long`, `sl_long`, `tgt_short`, `sl_short`) — semantics unresolved

**Status:** open (flagged 2026-06-12)
**Where:** `indicators/library/targets.py`, group `targets`, TFs [15, 60, 240, 1440]

Target/stop levels are derived from prev-candle `{src}_diff_prc_rm_20` ±
`*_std_above/_std_below` band arithmetic. Two concerns:

- The sided-std fields were redefined in phase-13 task-03 (now: std of the
  window's diff_prc values above/below the window mean, previously an rm ± std
  band). The tgt/sl formulas were patched to follow (`900bcee`), but whether
  "rm − sided-std" / "rm + sided-std" is still the *intended* target geometry
  has not been validated against strategy results.
- These are forward-usage labels computed inside the wide df alongside real
  indicators; nothing structurally prevents a strategy/NN feature set from
  consuming them as if they were ordinary indicators (lookahead risk by
  misuse, not by computation).

**Resolution:** define target semantics explicitly (spec), validate against
backtest/NN-label usage, and consider separating label columns from indicator
columns (naming convention or separate frame).

## 2. `ZB` / `ZS` zone fields — placeholder thresholds, effectively constant

**Status:** open (flagged 2026-06-12)
**Where:** `indicators/library/targets.py` (`ZBField`, `ZSField`), group `targets`

Both read `zb_threshold` / `zs_threshold` from `diff_stats.pkl`, but
`DataAttributes._compute_diff_stats` only writes `mean_diff` / `std_diff` —
the thresholds are never produced. `stats.get(..., 0.0)` then makes:

- `ZB = (close > 0).astype(int)` → always 1
- `ZS = (close < 0).astype(int)` → always 0

i.e. both columns are constants carrying no signal.

**Resolution:** either define and compute real `zb_threshold` / `zs_threshold`
in `_compute_diff_stats` (and document the intended zone semantics), or drop
ZB/ZS from the config until the zone model exists.

## 3. `TargetSpec.kind` dispatch duplicated across 8 call sites

**Status:** open (flagged 2026-09-20)
**Where:** `nn/nn_model_spec.py`, `nn/nn_dataset.py`, `nn/nn_model.py`,
`nn/training_loop.py`

`kind` is a plain `str` on `TargetSpec` (`"direction" | "direction_binary" |
"label" | "regression"`). Every behaviour that varies by kind is re-derived at
the point of use, so the same four-branch `if/elif` chain is written out eight
times:

| Site | Branches on kind to decide |
|------|----------------------------|
| `nn_model_spec.py:115` `__post_init__` | required fields (`side` for `direction_binary`) |
| `nn_model_spec.py:143` `out_columns` | output column names |
| `nn_dataset.py:165-252` `_build_target_block` | y-block encoding, source columns, manifest entry |
| `nn_model.py:43` `_HEAD_WIDTH` | head width (3 / 2 / 1 / 1) |
| `nn_model.py:578` `_class_weights` | balanced-weight scheme (per-class vector vs scalar pos_weight vs none) |
| `nn_model.py:602` `_combined_loss` | loss fn (cross-entropy / BCE-with-logits / smooth L1) |
| `nn_model.py:632` `_accuracy_counts` | train-time accuracy (argmax / sigmoid>0.5 / skip) |
| `nn_model.py:710` `_apply_head_activation` | inference activation (softmax / sigmoid / linear) |
| `training_loop.py:627` `_score_predictions` | holdout/promotion score (argmax acc / >0.5 acc / 1/(1+MSE) / p@k) |

**Why this bites:** adding or changing a kind means finding all eight sites.
Missing one does not raise — it silently produces wrong numbers. This is the
already-recorded "two scorers" failure: `_accuracy_counts` (train) and
`_score_predictions` (holdout/promotion gate) are independent implementations
of the same idea, and a target kind wired into only the first scores
nonsense through the promotion gate. The two have already diverged —
`direction_binary` supports `precision_at_k` in the holdout scorer only.

**Why deferred:** consolidation is invasive across the NN core and touches the
promotion path, and the current sites work for the four kinds in use.

**Resolution:** make kind-varying behaviour a property of the kind itself —
one `TargetKind` object per kind exposing `width`, `validate()`,
`out_columns()`, `build_block()`, `class_weights()`, `loss()`, `activation()`
and `score()` — with the eight call sites reduced to a lookup plus a call.
Constraint to respect: `spec_hash` is a sha256 over the canonical `TargetSpec`
dataclass fields and addresses the checkpoint directories, so keeping `kind` as
a `str` field with a behaviour registry keyed off it leaves the hash and all
existing checkpoints intact. Turning `TargetSpec` into a subclass hierarchy is
the cleaner typing but re-hashes every spec and orphans existing checkpoint
dirs — treat that as a separate, explicitly-costed decision.
