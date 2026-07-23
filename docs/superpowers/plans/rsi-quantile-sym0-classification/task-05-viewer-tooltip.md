# Task 05 — Viewer markers + side-aware tooltip

**Layer:** frontend (`frontend/data_viewer.py`, served by `view-full` on 8080)
**Depends on:** task-04 GREEN
**Produces:** new-field markers + long/short win-rate tooltip on the rsi_ma8 subplot

## Interface
```python
# frontend/data_viewer.py
def _draw_class_markers(self, fig, df, tf) -> None: ...   # extend: also draw *_zone_class_q / *_move_class_sym0
def _side_tooltip(self, field: str, tf: int, cls: int) -> str: ...  # NEW: reads rsi_side_stats.json
```

## Integration test → render (RED, Docker/headless)
`test_viewer_draws_new_markers`: given a df with `{tf}_zone_class_q`/`{tf}_move_class_sym0`
and a `rsi_side_stats.json`, the figure gains traces named for the new fields, and a marker's
hovertext contains the class's `long`/`short` win-rate. Skip-if-absent still holds when
columns/json missing.

## Unit tests (RED)
- marker spec added for both new fields (distinct glyph/colormap from legacy).
- `_side_tooltip` formats `long X% / short Y% (lift ±Z)` from `rsi_side_stats.json[tf][field][cls]`.
- absent columns OR absent json → no crash, markers/tooltip skipped.
- legacy markers still drawn unchanged (A/B).

## Implementation
- Extend the existing class-marker drawer to iterate legacy + new fields.
- Load `rsi_side_stats.json` via `stats_folder()` (cache), attach per-point hovertext.

## Constraints
- Read-only; no strategy/signal wiring.
- 8080 = `view-full`; redeploy = merge to experimental_imp_2 + `docker compose up -d view-full`.
