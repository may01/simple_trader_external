# simple_trader — repositories, dependencies, commands

How the three repositories fit together, what each needs, and the commands to build, run,
test and update them. For bootstrapping a fresh machine (human or agent) see
[SETUP_NEW_MACHINE.md](SETUP_NEW_MACHINE.md).

Last verified: 2026-10-23.

---

## 1. Layout on disk

```
~/projects/simple_trader/                 # umbrella dir, NOT a git repo
├── main/                                 # git  github.com/may01/simple_trader          (python)
├── worktrees/<branch>/                   # extra worktrees of main/ (one per task)
├── trade_executor/                       # git  github.com/may01/trade_executor         (rust)
│   └── .worktrees/<branch>/              # extra worktrees of trade_executor (ignored by git)
├── external/                             # git  github.com/may01/simple_trader_external (docs)
├── .claude/settings.json                 # Claude Code plugins for this dir (not in git)
└── .agents/skills/                       # third-party skills (skills-lock.json, not in git)
```

| repo | language | what it is | base branch for work | remote |
|---|---|---|---|---|
| `main/` | Python 3.12, Docker | data grab, indicators, candle-bounds (CB) zones, backtests, NN, Dash viewers, live indicator broadcaster | `experimental_imp_2` (no "l") | `may01/simple_trader` |
| `trade_executor/` | Rust 1.94, Docker, Postgres 17 | live/paper executor: exchange feeds → signals → decisions → orders; visualiser | `layer-implementation` (`main` is an empty stub: README + LICENSE only) | `may01/trade_executor` |
| `external/` | Markdown + replay scripts | specs, plans, experiment register, run reports, tech debt, incidents, releases; **all docs live here, never in the code repos** | `master`; work on short-lived branches merged into master | `may01/simple_trader_external` |

`release_001` exists in `main/` and `trade_executor/` = the paper system that has been running since
2026-10-20 (`docs/releases/2026-10-20-release_001.md`). The executor actually running today is the
`cb-candle-stop` branch (`trade_executor/.worktrees/cb-candle-stop`), one commit on top of `release_001`.

### Worktree convention

One git branch (and usually one worktree) per task. Absolute paths, because `git -C` is used from
the umbrella dir:

```bash
# main/
git -C ~/projects/simple_trader/main worktree add -b <branch> ~/projects/simple_trader/worktrees/<branch> experimental_imp_2
# trade_executor
git -C ~/projects/simple_trader/trade_executor worktree add -b <branch> ~/projects/simple_trader/trade_executor/.worktrees/<branch> layer-implementation
```

Containers mounted on a worktree write root-owned `__pycache__` / output files into it; a merge or
`git worktree remove` can fail on them. Fix: `sudo chown -R $USER:$USER <worktree>` or delete the
root-owned dirs before removing the worktree.

---

## 2. Dependency graph

```
                  Docker volumes (host bind mounts)
    simple_trader_vol      → /trader_data        live dataset  train/link_usdt/live, CB stats files
    simple_trader_vol_long → /trader_data_long   2y / 4y datasets, NN datasets + checkpoints
                       ▲
                       │ read/write
 ┌─────────────────────┴───────────────────┐        docker network `trader_mq`        ┌──────────────────────────────┐
 │ main/  (compose project in main/)        │  ZeroMQ indicators every 30 s           │ trade_executor (compose)      │
 │ graber → 1-min candles                   │ ───────────────────────────────────────▶ │ executor  (tcp://executor:5555│
 │ live    → indicators, CB zones/markers   │  MQ_EXECUTOR_ADDR=tcp://executor:5555    │            and :5556)          │
 │ view-*  → Dash viewers :8080 / :8070     │                                          │ postgres  (127.0.0.1:5436)     │
 │ nn-train / simulate-nn / ohlc_gen        │                                          │ visualizer 127.0.0.1:8090      │
 └──────────────────────────────────────────┘                                          └──────────────────────────────┘
                                                                                             ▲ exchange ws/rest
                                                                                             │ (Binance spot/margin, MEXC)
 external/  — documentation only; its executor/runs/*.py read the executor postgres + the main/ data volumes read-only
```

- `main/` never imports from `trade_executor` and vice versa; the only coupling is the MQ wire format
  (`main/mq/`, `trade_executor/crates/mq_gateway`) and the shared docker network `trader_mq`
  (`docker network create trader_mq`, once per machine; both compose files declare it `external`).
- The executor is the single writer of its postgres; `external/executor/runs` replay scripts and SQL
  clients connect as the read-only `dashboard` role on host port 5436.
- Host runtime deps: Docker + compose v2 (everything runs in containers), optional NVIDIA container
  toolkit (NN training, `docker-compose.gpu.yml`), optional host `cargo` 1.94 for the fast executor
  test loop. No host Python environment is needed; `main/` tests run inside the image.

---

## 3. main/ (python)

### Images and compose

| file | purpose |
|---|---|
| `docker-compose.yml` | services `graber`, `ohlc_gen`, `simulate`, `nn-train`, `simulate-nn`, `live`, `view-sim`, `view-full`, `view-live` |
| `docker-compose.gpu.yml` | overlay: NVIDIA device for `nn-train` / `simulate-nn` (base compose is CPU-only by design) |
| `docker-compose.experiment.yml` | overlay: `experiment` Jupyter image (`docker/Dockerfile.experiment`, port 8899, scipy/joblib) |
| `Dockerfile` | image `simple_trader` (python:3.12-slim + `requirements.txt`); source is bind-mounted at `/code`, not copied |
| `docker/Dockerfile.nn-train` | image `simple_trader_nn` (+ torch/optuna) |
| `.env` (tracked, no secrets) | which `configs/*.env` each service reads: `TRAIN_ENV`, `LONG_ENV`, `NN_TRAIN_ENV`, `LIVE_ENV`, … |
| `configs/*.env` | per-dataset env: `STOCK_TYPE`, `PAIR`, `DATA_SET_NAME`, `ROOT_FOLDER` (`short`→`/trader_data`, `long`→`/trader_data_long`), MQ settings |

Secrets (`BINANCE_API_KEY`, `BINANCE_API_SECRET`) come from the shell environment at `docker compose`
time; see `.env.example`. Never put them in a tracked file.

### Build

```bash
cd ~/projects/simple_trader/main
docker compose build graber            # image simple_trader (all python services share it)
docker compose build nn-train          # image simple_trader_nn (only for NN work / tests/nn)
```

Rebuild only when `requirements.txt` or a Dockerfile changes; code is bind-mounted.

### Test

```bash
cd ~/projects/simple_trader/main
# full suite, excluding docker e2e + NN (needs optuna → nn-train image)
docker compose run --rm graber python -m pytest -m "not docker_e2e" --ignore=tests/nn tests -q
# NN suite
docker compose run --rm nn-train python -m pytest tests/nn -q
# one file
docker compose run --rm graber python -m pytest tests/test_cb_broadcast.py -q
```

Known pre-existing failures on `experimental_imp_2` / `release_001`: 33 (listed in
`docs/releases/2026-10-20-release_001.md` §6, none on the live path). A change is clean when the count
does not grow. `notebooks/action_zones/tests` need the `experiment` image.

### Run

```bash
cd ~/projects/simple_trader/main
# data
docker compose run --rm graber                                  # pull 1-min candles (TRAIN_ENV dataset)
TRAIN_ENV=configs/long_dataset.env docker compose run --rm ohlc_gen   # generate_full_ohlc (4y ≈ 24 h; indicators are the bottleneck)
docker compose run --rm simulate                                # backtest
# NN (GPU host)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml run --rm nn-train
docker compose run --rm simulate-nn                             # inference; CPU for large history_points
# live indicator broadcaster (needs trader_mq + executor up)
BINANCE_API_KEY=… BINANCE_API_SECRET=… docker compose up -d live   # LIVE_ENV=configs/live.env, Dash :8050
# viewers — publish ONLY 8080: 8090 is the executor visualiser on the same host
docker compose run -d --name view-full -p 8080:8080 view-full   # full OOS/2y view over /trader_data_long
docker compose run -d --name view-live -p 8070:8070 view-live   # live view over /trader_data
```

Useful scripts (`main/scripts/`): `export_executor_wide_df.py` (executor DB → wide df for `view_full`
over live data), `cb_zone_run_stats.py`, `cb_live_parity.py`, `e2e_indicator_broadcast.py`,
`vol_creation.sh` (creates both docker volumes as bind mounts).

### Update

```bash
cd ~/projects/simple_trader/main
git fetch --prune
git switch experimental_imp_2 && git pull --ff-only
git diff --stat HEAD@{1} HEAD -- requirements.txt Dockerfile docker/   # non-empty → rebuild images
git worktree list                                                      # worktrees pull on their own branches
```

---

## 4. trade_executor/ (rust)

The code lives in the `layer-implementation` branch (and branches off it). The checkout at
`trade_executor/` is the stub `main`; work from `trade_executor/.worktrees/<branch>/`.

### Workspace

`Cargo.toml` workspace, crates under `crates/`: `exchange_adapter{,_binance,_mexc}`, `market_data`,
`local_analysis` (+ `local_analysis/signals`), `execution`, `state_store`, `mq_gateway`,
`replay_harness`, `cli`, `orchestrator` (the binary), `db_schema`, `migrations/` (SQL, applied with
`--migrate-only`), `visualizer_backend`, `visualizer_server` (SPA at `:8090`), `order_journal`,
`live_trade_ops`, `test_support`, `observability`.

### Compose

| service | role | ports (host) |
|---|---|---|
| `postgres` | postgres:17-alpine, db `trader`, users `executor` (writer) / `dashboard` (read-only) | `127.0.0.1:5436` |
| `test` | `cargo test --workspace` in the image, against the compose postgres | — |
| `executor` | orchestrator; joins `default` + `trader_mq`; the only service with keys / write DB | `127.0.0.1:5555/5556` |
| `visualizer` | read-only dashboard | `127.0.0.1:8090` |

Runtime env is read from the operator shell, defaults are safe: `EXECUTION_MODE=no_trade`,
`EXCHANGE=binance`, `PAIRS=LINKUSDT`, `RISK_PER_TRADE=100`. Paper trading = `EXECUTION_MODE=paper`.
Keys: `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET` (fall back to `BINANCE_API_KEY` / `BINANCE_API_SECRET`),
`EXCHANGE_FUTURES_API_KEY` / `_SECRET` for MEXC futures. Real env files for live-trade-ops tests go in
`configs/live-trade-ops/*.env` (gitignored; `*.env.example` templates are tracked).

### Test — two loops, both isolated from the live stack

The live paper stack runs as compose project `cbov-check` (postgres volume `cbov-check_trader_pgdata`).
**Never run tests, `up`, or `--migrate-only` inside that project** — the test suite truncates tables.
Use a throw-away project name and an override that unpublishes every host port:

```yaml
# <scratch>/ports.yml — never commit
services:
  postgres:   { ports: !override ["127.0.0.1:5437:5432"] }
  executor:   { ports: !override [] }
  visualizer: { ports: !override [] }
```

```bash
cd ~/projects/simple_trader/trade_executor/.worktrees/<branch>
# (a) Docker gate — the merge gate, fresh volume, ~10 min
docker compose -p <task>-test -f docker-compose.yml -f <scratch>/ports.yml run --build --rm test \
    cargo test --workspace --no-fail-fast
docker compose -p <task>-test -f docker-compose.yml -f <scratch>/ports.yml down -v
# (b) host loop — fast, needs rustup toolchain 1.94
cargo test -p local_analysis -p execution -p orchestrator --lib               # no DB
docker compose -p <task>-test -f docker-compose.yml -f <scratch>/ports.yml up -d --wait postgres
TEST_DATABASE_URL=postgres://executor:executor@127.0.0.1:5437/trader \
    cargo test -p signals -p state_store -p visualizer_server -p orchestrator
docker compose -p <task>-test -f docker-compose.yml -f <scratch>/ports.yml down -v
# visualiser JS (node >= 20)
node --test crates/visualizer_server/static/js/
```

Known flaky: `market_data` `write_path` shutdown-timing test. `exchange_adapter_mexc` wiremock tests
can interfere when run in parallel with the workspace; the crate alone passes. Baseline at release_001:
1469 passed.

### Run (paper)

```bash
cd ~/projects/simple_trader/trade_executor/.worktrees/cb-candle-stop     # the running branch
docker network create trader_mq 2>/dev/null || true
export EXECUTION_MODE=paper PAIRS=LINKUSDT EXCHANGE=binance MARKET_KIND=margin
export BINANCE_API_KEY=… BINANCE_API_SECRET=…                              # read-only keys are enough for paper
docker compose -p cbov-check build executor visualizer
docker compose -p cbov-check run --rm executor --migrate-only              # first boot / after a migration
docker compose -p cbov-check up -d executor visualizer
docker compose -p cbov-check logs -f executor                              # expect "cb stop armed: candle mode …"
# http://127.0.0.1:8090  visualiser;  psql postgres://dashboard:dashboard@127.0.0.1:5436/trader
```

Restart after a code change: `build` then `up -d --no-deps executor` from the same shell env (recreate
while flat; the operator does this, not an agent — the env lives in the operator's shell). Strategy
knobs in force (`CB_ZONE_SIGNAL_TFS`, `CB_STOP_MODE=candle`, `MIN_RR=0`, `TRAILING_FRACTION=0`, …) are
compose defaults on `cb-candle-stop`; the full list is in `docs/releases/2026-10-20-release_001.md` §1.

### Update

```bash
cd ~/projects/simple_trader/trade_executor
git fetch --prune                                   # may hang on a GPG/credential prompt: run with GIT_TERMINAL_PROMPT=0 and a timeout
git -C .worktrees/layer-implementation pull --ff-only
git -C .worktrees/cb-candle-stop pull --ff-only
```

Rebuild the executor image after any pull (`cargo` compiles in the image; nothing is bind-mounted).

---

## 5. external/ (docs)

No build, no tests. Structure:

```
external/
├── REPOS.md, SETUP_NEW_MACHINE.md          this file and the bootstrap guide
├── agent/skills/                           project skills for Claude Code (copy to ~/.claude/skills/)
├── docs/
│   ├── releases/                           what is running (release_001)
│   └── superpowers/
│       ├── specs/                          main/ design specs (dated)
│       ├── plans/                          main/ task plans = the task list (no issue tracker)
│       ├── experiment/                     experiment specs, results/, REPORT.md = the register
│       └── improvements/                   workflow improvements
└── executor/
    ├── specs/, plans/                      trade_executor design specs + plans (specs/layers = layer contracts)
    ├── runs/                               replay scripts (*.py) + outputs + run reports (*.md), executor-DB harnesses
    ├── references/                         frozen external material
    ├── UNFINISHED.md                       open items per landed plan (newest on top)
    ├── TECH_DEBT.md                        numbered debt sections
    └── INCIDENTS_LOG.md                    live-run incidents I-N (Seen / Cause / Fix / Status)
```

Replay scripts under `executor/runs/` are host python 3.12 scripts (numpy / pandas; some import
`main/` modules, so run them with `PYTHONPATH=~/projects/simple_trader/main`). They read a local
`data/` directory of JSON exports from the executor DB (dumped with `psql` as the read-only
`dashboard` role, `postgres://dashboard:dashboard@127.0.0.1:5436/trader`) and, for the 2y / oos2m
stand-ins, the part files on the bind-mounted data volumes. Each script's docstring and its
`*-replay.md` run report say which exports and arguments it takes; outputs sit beside it as
`*-output*.txt`.

Update: `git pull --ff-only` on `master`; experiment work goes on a branch (currently
`cross-tf-veto-replay`, which has diverged from `master`: merge needed, `REPORT.md` will conflict).

---

## 6. Working conventions (apply in every repo)

- A dedicated branch (usually a worktree) per task, from the base branch in §1; merge back into it.
- Docs, specs, plans, experiment results, run reports: **only in `external/`**. Tasks are plan files
  under `external/docs/superpowers/plans/`, not GitHub issues. Every improvement updates its spec + plan.
- Never commit, push or open a PR without the user's explicit confirmation: stage, describe, wait.
- Never `git stash` to hop branches (the stash stack is shared across worktrees); read old commits
  with `git show`.
- Never recreate the live executor stack from an agent shell (its env is in the operator's shell);
  never run tests inside the live compose project.
- Tech debt → `external/executor/TECH_DEBT.md`; live-run bugs → `external/executor/INCIDENTS_LOG.md`.
- Spec or plan "changed on disk" → re-read before building; several sessions edit them in parallel.
- Old name `pybtctr2` = `simple_trader`; replace on sight in docs/code (docker volume names
  `pybtctr_vol*` are historical and exempt).
