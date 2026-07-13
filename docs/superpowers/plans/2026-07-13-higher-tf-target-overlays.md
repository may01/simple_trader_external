# Plan — Higher-TF target/SL overlays on finer charts

**Spec:** `docs/superpowers/specs/2026-07-13-higher-tf-target-overlays-design.md`
**Base branch:** `experimental_imp_2`
**Work branch / worktree:** `viewer-higher-tf-target-overlays`
**Scope:** Presentation layer only (`frontend/`). No pipeline layers touched.

This is a single-layer (Presentation) change, so the layer-first template
collapses to: Docker entry points → the one Presentation boundary
(`DataViewer` → `ChartRenderer`) → unit tests → implementation.

---

## Step 0 — Docker entry points (contract)

**Run the test suite in Docker** (image `simple_trader`, command overridden):

```bash
docker compose run --rm view-full \
  python3 -m pytest \
    tests/test_higher_tf_target_overlays.py \
    tests/test_phase12_task11_target_sl_overlays.py \
    tests/test_phase12_task15_overlay_selection.py -q
```

**Eyeball the viewer:**

```bash
docker compose up view-full        # serves history dashboard on :8080
# browse http://localhost:8080 → select the 1m TF chart
#   expect: 15m tgt/sl step-lines drawn by default (solid, bold)
#   toggle tgtsl_60m / tgtsl_240m / tgtsl_1440m → dashed/thinner lines appear
#   15m/60m/… charts unchanged (native always-on only)
```

- Verified RED before impl: [ ] new test module fails in Docker
- Verified GREEN after impl: [ ] all three suites pass in Docker
- Verified visually: [ ] 1m chart shows toggleable higher-TF step lines

---

## Layer: Presentation (`frontend/data_viewer.py`, `frontend/chart_renderer.py`)

### Step 1 — Interface (signatures only)

```python
# frontend/chart_renderer.py — extended, backward-compatible
class ChartRenderer:
    def draw_line(self, fig, subplot: str, times: list, values: list,
                  label: str, color: str = "blue",
                  dash: str | None = None, width: float | None = None) -> None: ...

# frontend/data_viewer.py — new class constants
class DataViewer:
    _TARGET_TF_GROUPS: dict[str, int]   # {"tgtsl_15m":15,"tgtsl_60m":60,"tgtsl_240m":240,"tgtsl_1440m":1440}
    _TARGET_TF_STYLE: dict[int, tuple[str | None, float]]  # src_tf -> (dash, width)

    # behaviour extended (signatures unchanged):
    def available_overlays(self) -> list[str]: ...          # + present tgtsl_* groups
    def default_overlays(self) -> list[str]: ...            # tgtsl_15m on; 60/240/1440 off
    def _draw_price_overlays(self, fig, df_slice, tf: int,
                             overlays: list[str] | None = None) -> None: ...  # + gated higher-TF block
```

### Step 2 — Integration test → ChartRenderer (RED in Docker)

The boundary is `DataViewer._draw_price_overlays` → `ChartRenderer.draw_line`.
Test the whole `build_window_figure(tf=1)` path with a real `ChartRenderer`
(not mocked) so the Scatter traces are actually produced:

```
test_tf1_draws_higher_tf_target_lines_on_price_axis:
  fixture: 1m OHLC + 15_tgt/sl* + 60_tgt/sl* columns (flat-step values)
  build_window_figure(start, 1, tf=1)  with real ChartRenderer
  assert price-row Scatter trace names include
    tgt_long·15m, sl_long·15m, tgt_short·15m, sl_short·15m,
    tgt_long·60m, ... (60m set)
  assert each trace's line.dash / line.width match _TARGET_TF_STYLE
```

Must fail RED before implementation (columns drawn today are only `1_*`, absent).

### Step 3 — Unit tests (RED)

`tests/test_higher_tf_target_overlays.py`, MagicMock renderer (mirroring
`test_phase12_task11`), asserting on `draw_line` call args:

1. **available_overlays** — includes `tgtsl_15m`/`60m`/`240m`/`1440m` when the
   backing columns exist for that TF; a group is absent when none of its four
   columns exist.
2. **default_overlays** — includes `tgtsl_15m`; excludes `tgtsl_60m`,
   `tgtsl_240m`, `tgtsl_1440m`.
3. **gate at tf ≥ 15** — same multi-TF fixture rendered at `tf=15` draws **no**
   `·{H}m`-suffixed price labels (higher-TF groups no-op).
4. **tf=1 draw-all** (`overlays=None`) — every present-TF group drawn; labels
   TF-suffixed; colours = the four semantic `_OVERLAY_COLORS`.
5. **toggle filter** — `overlays=["tgtsl_15m"]` draws only the 15m set;
   `tgtsl_60m` labels absent. `overlays=[]` draws none of the higher-TF groups.
6. **skip-if-absent** — fixture with only `15_tgt_long` (not the other three,
   not 60m) draws just `tgt_long·15m`.
7. **styling** — `tgt_long·15m` trace solid (`dash is None`) width 2.0;
   `tgt_long·60m` dashed width 1.6 (assert via `draw_line` kwargs).
8. **draw_line back-compat** — omitting `dash`/`width` yields a `line` dict with
   no `dash`/`width` keys; supplying them sets them (direct `ChartRenderer` test).

### Step 4 — Regression (must stay GREEN, unchanged)

- `tests/test_phase12_task11_target_sl_overlays.py` — tf=15 fixture, `15_*`
  only → higher-TF groups skip-if-absent, gate off → bare labels/colours
  identical.
- `tests/test_phase12_task15_overlay_selection.py` — overlay selection contract
  unchanged for existing groups.

### Step 5 — Implementation

Turn unit tests GREEN then the integration test GREEN, then run all three
suites in Docker (Step 0). Edits:

1. `chart_renderer.py::draw_line` — build `line` dict, add `dash`/`width` only
   when non-None.
2. `data_viewer.py` — add `_TARGET_TF_GROUPS`, `_TARGET_TF_STYLE`; extend
   `available_overlays` / `default_overlays`; append the gated higher-TF block
   to `_draw_price_overlays` (draw order descending TF; label `f"{name}·{src_tf}m"`;
   colour `_OVERLAY_COLORS[name]`; skip-if-absent per field; skip group when
   `overlays is not None and group not in overlays`).

### Constraints / notes

- `_dedup_tf_rows(window, 1)` keeps every 1-minute row; `{H}_tgt_*` are already
  flat-per-row → plotly renders horizontal steps, no step mode.
- Gate constant: `min(self._TARGET_TF_GROUPS.values())` == 15, so `tf < 15`
  ⇒ tf ∈ {1,5}. Do not hard-code 15.
- Native always-on `_TARGET_OVERLAYS` block is untouched — higher-TF block is
  strictly additive and lives after it.
- Container writes root-owned files into the mounted worktree; after Docker
  test runs, check `git status` for root-owned artifacts before merge.
