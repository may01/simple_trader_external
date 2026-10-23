# Operational pitfalls (simple_trader experiments)

## Data and memory

- Wide 2y frame `df_with_indicators.pkl` ≈ 5.7 GB (oos2m ≈ 470 MB, 84,961 × 752). Host has
  ~15 GB. Load inside Docker, one process at a time; ask the user to free RAM for the big
  reads.
- First task of any experiment: extract a **slim** column/row subset once per dataset and
  work from it. Every experiment that skipped this hit OOM.
- 2y data lives on `simple_trader_vol_long` (`ROOT_FOLDER=long` → `/trader_data_long`),
  not `simple_trader_vol`. Host-readable at `/media/om/Alexandria/simple_trader/...`.
- 2y datasets exist as `part_00..24` pickles; labels may not be baked and must be computed
  per part in memory. Per-part boundary tails yield NaN labels — drop and count them.

## Artifacts and files

- Containers write artifacts root-owned into mounted worktrees and block merges. Write to
  the volume via `docker run -v <vol>:/vol`, and `chown 1000:1000` anything a container
  created in the worktree.
- Stats files (`rsi_classification.json`, `diff_stats.pkl`, `indicator_stats.json`) are
  written **only if absent** — a stale copy with an old schema crashes recompute with a
  KeyError. Delete before a schema-changing recompute.
- Artifacts are additive sidecars next to the dataset (`df_with_<experiment>.pkl` +
  `<experiment>_{params,metrics}.json`). Never overwrite the source frame.

## Docker / compose

- Docker entry points are written before any code (see `layer-first-planning`).
- compose v2.34 `run` does not accept `--env-file` — expand the env file into `-e` flags.
- The experiment image (`docker/Dockerfile.experiment`,
  `docker-compose.experiment.yml`: base + jupyterlab, papermill, scikit-learn, scipy,
  matplotlib, plotly) may exist only on another experiment worktree — copy the two files in.
- Tests run in Docker, under `-W error` where the branch already does.
- GPU needs `-f docker-compose.gpu.yml`; the base compose is CPU-only by design.

## Viewer

- Results are shown on the full view as markers/overlays for both the 2y replay and the
  oos2m frame. Wiring touches `data.py`, `view_full.py`, `frontend/data_viewer.py`,
  `chart_renderer.py`.
- The 8080 viewer container mounts one specific worktree. Markers from another worktree are
  invisible until it is restarted against yours. State which worktree the screenshot came
  from.
- Name new overlays after the experiment prefix (`az_`, `cb_`, `cbnc_`, `zp_`) and say in
  the report what each marker means.

## Git

- Worktrees at `/home/om/projects/simple_trader/worktrees/<branch>`, repo at `main/`.
- Branch off `experimental_imp_2` unless the spec names another base; chained experiments
  branch off their predecessor.
- No commits before report approval. Read old commits with `git show`, never stash-hop.
- After approval: success merges into the base branch and the worktree is removed; failure
  is pushed to the remote for history and the local worktree is removed. Nothing lingers.
- Plans, specs and reports live in the external docs repo only.

## Multi-scorer traps

Some pipelines score the same thing twice. In NN training, a new target kind must update
both `_accuracy_counts` (train) and `training_loop._score_predictions` (holdout/promotion);
missing the second silently corrupts promotion. Before adding a variant, grep for every
place the metric is computed.
