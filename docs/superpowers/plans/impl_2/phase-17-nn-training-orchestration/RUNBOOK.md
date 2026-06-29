# Phase 17 — NN Training Orchestration: Operator Runbook

The full flow to drive one archetype's lineage with `docker compose` + the
orchestration CLI. Iterate on **2y link_usdt**, confirm on **4y**. Locked values:
`K=2`, `max_versions 6`, `margin 0.01`, `budget 28800s`, `trials_per_round 8`,
`max_rounds 1`.

## 0. One-time setup

```bash
cd /home/om/projects/simple_trader
docker compose build nn-train                 # torch + optuna image
# confirm the data volume is mounted and link_usdt data is present:
docker compose run --rm nn-train ls /trader_data_long/train/link_usdt/nn
```

## 0b. Deploy in-repo skills (after merging branch to experimental_imp_2)

Skills live in-repo at `.claude/skills/` and are deployed on merge by symlinking
into the project-root discovery path:

```bash
cd /home/om/projects/simple_trader
ln -s main/.claude/skills/nn-investigate .agents/skills/nn-investigate
ln -s main/.claude/skills/nn-evolve .agents/skills/nn-evolve
ln -s main/.claude/skills/nn-train-orchestrator .agents/skills/nn-train-orchestrator
```

After the symlinks are in place, Claude Code discovers the skills under
`.agents/skills/` at startup.

## 1. Investigate (Tier 0) — emit the v1 spec

Use the `nn-investigate` skill to produce `v1.yaml` (a valid `NNModelSpec`).
The agent writes it under the archetype's external dir.

## 2. Materialize the version spec onto the artefact volume

```bash
docker compose run --rm nn-train \
  python -m nn.orchestration.cli materialize-spec \
    --spec-yaml /work/<archetype>/v1.yaml --pair link_usdt
# → prints the on-volume path, e.g.
#   /trader_data_long/train/link_usdt/nn/specs/<spec_hash>/spec.yaml
```

## 3. Run one version (multi-hour; drive under ralph-loop / /loop)

```bash
docker compose run --rm nn-train \
  python -m nn.orchestration.cli run-version \
    --spec-path /trader_data_long/train/link_usdt/nn/specs/<spec_hash>/spec.yaml \
    --study <archetype>_v1 --pair link_usdt --timeout 28800
# → prints {"study": "<archetype>_v1", "holdout_score": <f>}
# result also on the volume: tracking/<archetype>_v1/best.json
```

## 4. Evolve — write the report + decide promote/revert/stop

The `nn-evolve` skill writes `{archetype}/v1/report.md` and runs:

```bash
docker compose run --rm nn-train \
  python -m nn.orchestration.cli decide \
    --best none --candidate <holdout_score> --margin 0.01 \
    --strike 0 --k 2 --version-n 1 --max-versions 6 \
    --elapsed <s> --budget 28800
# → {"action": "...", "new_best": ..., "strike_count": ..., "stop": ..., "reason": "..."}
```

If `stop == false`: take the next proposed spec → back to step 2 with
`--version-n 2` (and `--best <running best score>`, `--strike <returned count>`).
Repeat until `stop == true`.

## 5. Confirm the winner on 4y (final lineage step)

Re-run the promoted best ONCE on the 4y dataset with a `_4y` study suffix:

```bash
docker compose run --rm nn-train \
  python -m nn.orchestration.cli run-version \
    --spec-path <winner spec path> --study <archetype>_4y \
    --pair link_usdt --timeout 28800
```

Record the 4y holdout in the winner's report.

## 6. Human gate

Review the lineage (per-version reports + 4y result), then resume the
`nn-train-orchestrator` skill for the NEXT archetype.

## Drive the loop unattended

```bash
# ralph-loop: Stop hook re-feeds the prompt; state persists in files
/ralph-loop "Run nn-train-orchestrator for archetype <name> on link_usdt" \
  --completion-promise "ARCHETYPE_DONE"
# or interval re-invoke:
/loop 30m run the nn-train-orchestrator skill for archetype <name>
```
