# simple_trader — set up the projects on another machine (human + Claude Code agent)

Bootstraps the three repositories, the Docker runtime state and the agent tooling so that a Claude
Code session on the new machine can build, test and run everything. Repository roles, commands and
conventions are in [REPOS.md](REPOS.md); read that first, then follow this top to bottom.

Target layout is the same as on the source machine, `~/projects/simple_trader/` (keep the path: the
agent's memory directory is keyed by it, see §7).

---

## 1. Host prerequisites

| need | why | check |
|---|---|---|
| git ≥ 2.40 | three repos + worktrees | `git --version` |
| Docker Engine + compose v2 | every service runs in containers | `docker compose version` |
| user in the `docker` group | compose without sudo | `docker ps` |
| NVIDIA driver + nvidia-container-toolkit (optional) | `main/` NN training (`docker-compose.gpu.yml`) | `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi` |
| rustup toolchain 1.94 (optional) | fast executor host test loop; the Docker gate works without it | `cargo --version` |
| node ≥ 20 (optional) | visualiser JS tests (`node --test`) | `node --version` |
| python 3.12 + numpy/pandas (optional) | `external/executor/runs` replay scripts on the host | `python3 --version` |
| GitHub access to `may01/*` | clone / push | `gh auth status` or a credential helper |

Disk: the bind-mounted data volumes hold the 2y / 4y datasets and NN artefacts (hundreds of GB on the
source machine, `du -sh /media/om/Alexandria/simple_trader/*` to size them before copying).

GitHub credentials: `gh auth login` (HTTPS) is the simplest. On the source machine git-credential-manager
+ gpg pinentry intermittently hangs `git fetch/push` in the executor repo; if that setup is copied, run
git non-interactively (`GIT_TERMINAL_PROMPT=0 timeout 120 git …`) and hand hangs to the user.

---

## 2. Clone the repositories

```bash
mkdir -p ~/projects/simple_trader && cd ~/projects/simple_trader

git clone https://github.com/may01/simple_trader.git main
git -C main switch experimental_imp_2                      # base branch for main/ work (= release_001 today)

git clone https://github.com/may01/trade_executor.git trade_executor
git -C trade_executor worktree add .worktrees/layer-implementation layer-implementation   # the code (= release_001)
git -C trade_executor worktree add .worktrees/cb-candle-stop cb-candle-stop               # the running paper executor

git clone https://github.com/may01/simple_trader_external.git external
git -C external switch cross-tf-veto-replay                # current docs branch (ahead of master)
```

Verify: `git -C main log -1 --oneline`, `git -C trade_executor worktree list`, `ls external`.
`main/` worktrees (`~/projects/simple_trader/worktrees/<branch>`) are created per task, not now.

---

## 3. Docker runtime state

```bash
# shared network between the two compose projects (both declare it external)
docker network create trader_mq

# data volumes as bind mounts on a big disk (edit VOL_PATH)
VOL_PATH=/data/simple_trader bash ~/projects/simple_trader/main/scripts/vol_creation.sh
docker volume inspect simple_trader_vol simple_trader_vol_long --format '{{.Name}} {{json .Options}}'
```

Without `VOL_PATH` the script creates plain named volumes under `/var/lib/docker/volumes` — fine for
a test box, not for the 4y datasets.

---

## 4. Data (not in git)

Two sources: copy from the source machine, or regenerate.

**Copy (preferred, keeps every frozen dataset / stats file / checkpoint):**

```bash
# on the new machine, after §3 (same relative layout inside each volume)
rsync -aP --info=progress2 om@<source>:/media/om/Alexandria/simple_trader/simple_trader_vol/      /data/simple_trader/simple_trader_vol/
rsync -aP --info=progress2 om@<source>:/media/om/Alexandria/simple_trader/simple_trader_vol_long/ /data/simple_trader/simple_trader_vol_long/
```

Start with `simple_trader_vol` (the live dataset `train/link_usdt/live` + CB stats files, needed
by the live loop and most replays); `simple_trader_vol_long` (2y / 4y part files, NN datasets at
`train/link_usdt/nn/datasets/<hash>`, checkpoints) only when NN / 2y work is planned.

Executor history (positions, candles, indicators, decisions since 2026-10-16) lives in the postgres
volume of the live compose project, `cbov-check_trader_pgdata`. To carry it over:

```bash
# source machine (dashboard role is read-only, so this is safe to run while the executor is up)
docker exec $(docker ps -qf name=cbov-check-postgres) pg_dump -U executor trader | gzip > trader-$(date +%F).sql.gz
# new machine, after the executor stack has been created once (§6 step 3, run --migrate-only first)
gunzip -c trader-<date>.sql.gz | docker exec -i $(docker ps -qf name=cbov-check-postgres) psql -U executor trader
```

**Regenerate** (no copy): `docker compose run --rm graber` for candles, then `ohlc_gen` per dataset
env (4y ≈ 24 h of indicator computation). Stats files are rebuilt on first use when absent; a stale
schema in an existing stats file crashes the recompute — delete the file.

---

## 5. Secrets

Exchange keys only in the shell that runs `docker compose`, never in a tracked file:

```bash
# ~/.simple_trader.env  (chmod 600; `source` it in the operator shell, never commit)
export BINANCE_API_KEY=…          # read-only keys suffice for paper mode
export BINANCE_API_SECRET=…
export EXCHANGE_API_KEY=…         # executor spelling (falls back to the BINANCE_ pair)
export EXCHANGE_API_SECRET=…
```

`main/.env` is tracked and only points at `configs/*.env`; `main/.env.example` lists the variables.
Executor live-trade-ops env files go to `trade_executor/.worktrees/<branch>/configs/live-trade-ops/*.env`
(gitignored).

---

## 6. Build and smoke-test

```bash
# 1. main/ images + unit tests (33 known failures, see external/docs/releases/2026-10-20-release_001.md §6)
cd ~/projects/simple_trader/main
docker compose build graber
docker compose run --rm graber python -m pytest -m "not docker_e2e" --ignore=tests/nn tests -q

# 2. executor Docker gate in a throw-away project (ports override: see REPOS.md §4)
cd ~/projects/simple_trader/trade_executor/.worktrees/layer-implementation
docker compose -p setup-test -f docker-compose.yml -f <scratch>/ports.yml run --build --rm test cargo test --workspace --no-fail-fast
docker compose -p setup-test -f docker-compose.yml -f <scratch>/ports.yml down -v

# 3. paper stack (only if this machine is to run the system)
cd ~/projects/simple_trader/trade_executor/.worktrees/cb-candle-stop
source ~/.simple_trader.env
export EXECUTION_MODE=paper PAIRS=LINKUSDT EXCHANGE=binance MARKET_KIND=margin
docker compose -p cbov-check build executor visualizer
docker compose -p cbov-check run --rm executor --migrate-only
docker compose -p cbov-check up -d executor visualizer
cd ~/projects/simple_trader/main && docker compose up -d live       # indicators → tcp://executor:5555 over trader_mq
docker compose -p cbov-check logs --tail 50 executor                # "cb stop armed: candle mode …", indicators arriving
# http://127.0.0.1:8090 (visualiser), http://127.0.0.1:8050 (main/ live Dash)
```

Run the paper stack on one machine only: each machine keeps its own postgres history, and two
parallel runs make the replay / incident bookkeeping ambiguous.

---

## 7. Claude Code agent setup

1. **Install Claude Code** and sign in; open it from `~/projects/simple_trader` (the umbrella dir is
   the working directory on the source machine, so the three repos are reachable with relative paths
   and `git -C`).

2. **Plugins** (`/plugin` or `~/.claude/settings.json` → `enabledPlugins`): `superpowers@claude-plugins-official`,
   `ralph-loop@claude-plugins-official`, `github@claude-plugins-official`, and `caveman@caveman` from the
   marketplace `https://github.com/juliusbrussee/caveman.git`. The project-level file
   `~/projects/simple_trader/.claude/settings.json` on the source machine is:
   ```json
   { "enabledPlugins": { "superpowers@claude-plugins-official": true, "ralph-loop@claude-plugins-official": true,
                         "caveman@caveman": true, "github@claude-plugins-official": true } }
   ```

3. **Project skills** (this repo ships them under `agent/skills/`; they are not in any marketplace):
   ```bash
   mkdir -p ~/.claude/skills
   cp -r ~/projects/simple_trader/external/agent/skills/layer-first-planning ~/.claude/skills/
   cp -r ~/projects/simple_trader/external/agent/skills/running-experiments ~/.claude/skills/
   ```
   `layer-first-planning` — how plans for this project are written (Docker-first entry point,
   layer order, interface before code). `running-experiments` — the 7-phase experiment workflow with
   validity gates and the register under `docs/superpowers/experiment/`.
   Third-party skills in `~/projects/simple_trader/.agents/skills` (`skills-lock.json`: caveman,
   grill-me, tdd, prototype, to-issues, …) come from `mattpocock/skills` and are optional.

4. **Agent memory** — the source machine's per-project memory (user preferences, project state,
   decisions that are not in git) lives outside the repos at
   `~/.claude/projects/-home-om-projects-simple-trader/memory/` (directory name = working directory
   with `/` → `-`). Copy it to the same path on the new machine when the working directory is the
   same; otherwise rename the directory to the new encoded path:
   ```bash
   rsync -a om@<source>:~/.claude/projects/-home-om-projects-simple-trader/memory/ \
            ~/.claude/projects/-home-om-projects-simple-trader/memory/
   ```
   `MEMORY.md` in it is the index; each other file is one fact. Without it the agent still has
   REPOS.md §6 (conventions), `executor/UNFINISHED.md`, `executor/TECH_DEBT.md`,
   `docs/superpowers/experiment/REPORT.md` and `docs/releases/` as the written state.

5. **Permissions**: the source machine allows `Bash(git *)`, `Bash(python3 *)`, `Bash(docker compose …)`
   style commands in `.claude/settings.local.json`; recreate what the new machine needs with
   `/permissions`. Keep the "confirm before commit / push" rule (REPOS.md §6) regardless of what the
   permission list allows.

6. **First session checklist for the agent**
   - read `external/REPOS.md`, `external/executor/UNFINISHED.md` (top entry = latest work),
     `external/docs/releases/2026-10-20-release_001.md` §1 and §7;
   - `git -C main status`, `git -C trade_executor worktree list`, `git -C external status` — all clean,
     branches as in §2;
   - `docker network ls | grep trader_mq`, `docker volume ls | grep simple_trader` — present;
   - run §6 step 1 and step 2 once; note the pass/fail counts against the release baseline.

---

## 8. Keeping two machines in sync

- Code: commit on a task branch, push, pull on the other side (`REPOS.md` §3–§5 "Update"). Local-only
  state that does not travel: git stashes, worktree directories, `.claude/settings.local.json`,
  container images (rebuild), postgres history (§4 dump/restore), data volumes (§4 rsync).
- Docs: `external/` is the single place for state; push it with the code so the other machine's agent
  sees the same `UNFINISHED.md` / plans / experiment register.
- The live paper system runs on exactly one machine; a second machine is for development, replays
  and (GPU) training against a copy of the data.
