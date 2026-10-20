# Task 03: 2y run, memory retry path, results doc

**Phase:** 20 — CB zone run stats
**Depends on:** 02
**Produces:** `cb_zone_run_stats.{json,md}` on 2y + oos2m; `external/docs/superpowers/experiment/results/cb_zone_run_stats_results.md`; the six frozen numbers
**Gates:** G3, G4, G5

---

## Goal

Produce the numbers the executor freezes. The user's decision: wait for 2y, retry on error, never freeze oos2m-only.

## Files

- Modify: `scripts/cb_zone_run_stats.py` only if the run exposes a bug
- Create: `external/docs/superpowers/experiment/results/cb_zone_run_stats_results.md`
- Modify: `external/docs/superpowers/specs/2026-10-19-cb-zone-run-stats-design.md` (status line), `external/docs/superpowers/experiment/REPORT.md` (one row)

## Steps

- [ ] **Step 1: Host budget** — `free -g` and `df -h /media/om/Alexandria` before the run; record both.

- [ ] **Step 2: Full run (G3)** — README "Full run" entry point, wrapped in `/usr/bin/time -v` inside the container (`docker compose -p cbrun run --rm ohlc_gen /usr/bin/time -v python3 scripts/cb_zone_run_stats.py …`). Record `Maximum resident set size` and wall time. On `MemoryError` / OOM kill (exit 137): run `--make-subset` (README retry path), then rerun with `--train-ind` pointing at the subset. If the subset write itself dies, retry once with every other container stopped; if it still dies, stop and report — do not substitute oos2m numbers.

- [ ] **Step 3: G4 — 2y vs oos2m** — for every `(tf, side)` set C: `|p50_oos − p50_2y| / p50_2y`; cells above 0.5 listed. Also list cells where set A and set C p50 differ by more than 1 minute (spec §4 call).

- [ ] **Step 4: G5 — results doc** `cb_zone_run_stats_results.md`: run date, branch + commit, exact commands, host budget, peak RSS / wall time, the ATR choice printed by the script, the G2 parity pairs from Task 02, the full per-set tables (2y and oos2m), the `remaining_given_streak` table for set C, the G4 lists, and the **freeze table** ending with the literal line `CB_STOP_EXPECTED_POINTS=15:L/S;60:L/S;240:L/S` (2y, set C, p50, one decimal). State plainly that set C is the entry *filter* set, not the executor's firing set.

- [ ] **Step 5: Docs** — spec status → "measured 2026-MM-DD, frozen values in results doc"; `REPORT.md` row (date, link, one-line verdict); memory `project_cb_book_stop` gains the six numbers.

- [ ] **Step 6: Stage and describe** — `notebooks/zone_profitability/out/` is git-ignored? Check; the json/md go to the results doc, not the code repo. Message `docs: cb zone run stats results` (external repo is not a git repo of ours — just write). Wait for the user before any commit.

- [ ] **Step 7: Hand-over line** to the executor plan: "run-stats results doc exists; copy the `CB_STOP_EXPECTED_POINTS` line into `docker-compose.yml` (executor plan Task 6)".
