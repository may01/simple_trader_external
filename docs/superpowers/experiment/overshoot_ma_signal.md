# Overshoot zones: trade on a longer trade-price MA instead of vetoing — spec

**Date:** 2026-10-20 · **Status:** done 2026-10-20 — **negative** (see `results/overshoot_ma_signal_results.md`) · **Base:** read-only replay over the paper executor's stored data (no code-repo branch; precedent `sl_15m_anchor_replay`, REPORT.md 2026-10-20)
**Related:** `specs/2026-10-17-cb-overshoot-main-flow-design.md` (the flag), `executor/specs/2026-10-18-cb-zone-entry-signal-design.md` §5–6 (the check and the 1-min MA class), `executor/specs/2026-10-20-cb-candle-stop-design.md` (the stop now in force), `executor/runs/2026-10-20-sl-15m-anchor-replay.md` (the replay harness this extends).

# Goal

Measure the P&L the running CB-zone paper strategy would have made if, in a zone minute where main/'s
overshoot flag vetoes the side (`{tf}_cb_f_overshoot_{side} == 0`, "the candle broke deep through the
bound"), the entry check did not skip the side but instead took its direction from a **longer** trailing
MA of the executor's own trade prices — 3 min and 5 min (the live check uses 1 min) — and compare it with
the veto as it runs today.

# Rationale and algorithm

The overshoot veto was fitted on "deep breaks precede a larger further move" and removes about half of the
in-zone minutes (phase 19 results). The user's hypothesis: in those minutes the zone is still a valid
level, and a slower MA (less noise than the 1-min one) is enough to tell whether the break is being bought
back; the fast MA is what makes those entries bad, not the zone.

Replay (event-driven, every stored trade, port of `CbZoneEntryCheck` + `signals::trend`):

1. Indicators at trade time `t`: latest stored row with `received_at ≤ t` and `expires_at > t` (the
   store's rule, plus the causal bound the live store gets for free).
2. Trend classes at `t`: the live 1-min class (10 s buckets, 6-bucket trailing mean, ±0.7 σ of the slopes
   over the last 2 h, ≥ 30 buckets, 6 000-trade window) and the same computation with an 18-bucket (3 min)
   and a 30-bucket (5 min) trailing mean.
3. Per (tf, side): rule 1 (`cb_inzone` ∧ class = direction) or rule 2 (previous 1-min candle wick reached
   `cb_zone` and closed back ∧ class ∈ {neutral, direction}); `cb_f_trend` veto always; `cb_f_overshoot`:
   - `current`: veto (as live);
   - `ma3` / `ma5`: the side is evaluated with the 3-/5-min class **in place of** the 1-min class;
   - `ma3_and` / `ma5_and`: 1-min **and** the longer class must both pass (ablation: does the longer MA
     add anything beyond the fast one);
   - `no_veto`: 1-min class as elsewhere (ablation: the veto's own worth).
   Once-per-(tf, side, zone) key, contradiction rule, 60 s deferred gap, highest tf — as live.
4. Position layer as live today: same-side fire while open = skip, opposite = reversal; stop = forming
   15-min extreme ∓ trailing-60 mean 1-min range (bars from trades), placeholder 0.2 % when not adverse;
   target = `{tf}_cbnc_{far}` at fire; close on 1-min trend flip after the extreme passes the target
   (the exit keeps the live 1-min class in every mode — the question is the entry); size
   `min(100 / dist, free × 0.5 / entry)`; paper = no fees (fee sensitivity reported).

# Steps

1. Export `trade`, `indicators` (CB names), `signal_log` CbZoneEntry rows, `position_log`, from the
   `cbov-check` postgres (window: first CB fire 2026-10-18 11:41Z → last stored trade).
2. Reproduction gate: `current` mode must re-fire the recorded CbZoneEntry events (side, tf, zone; ts
   within 60 s) — report matched / missed / extra with reasons (restarts reset the check's state).
3. Run the modes; per mode the standard table plus the **marginal** table: P&L of the positions that
   exist only because an overshoot-vetoed side was taken.
4. Gates: null floor (bootstrap 90 % CI), concentration (top-2 share), ablations (`no_veto`, `_and`),
   fee sensitivity, look-ahead (by construction: every input ≤ t), sample (hours, fires per mode).

# Results

`executor/runs/2026-10-20-overshoot-ma-replay.md` (run report with the per-trade tables), script and raw
outputs beside it; decision summary `experiment/results/overshoot_ma_signal_results.md`; REPORT.md row.

# Constraints

No code change in `main/` or `trade_executor`; no commit; source tables read-only; nothing is fitted —
every parameter is the live one or the user's 3/5 min; no selection on the replay window (the modes are
the user's two values plus named ablations).

# Data

Paper stack `cbov-check` (release_001 + `cb-candle-stop`), Binance LINKUSDT. Stored trades 2026-10-16
22:29Z → 2026-10-20 21:23Z (670 210); overshoot flags on the wire since 2026-10-17 22:00Z; CB check armed
since 2026-10-18 11:41Z (152 CbZoneEntry rows, 108 positions under three successive stop rules). No 2y /
oos2m leg: the trade-price MA has no equivalent on the 1-min frames (a 1-min-close MA is a different
statistic); a 1-min-bar proxy is listed as the next arbiter if this sample cannot decide.

# Locked decisions (author's calls, 2026-10-20 — user not available during the run; flagged for review)

| # | Question | Call |
|---|---|---|
| L1 | What "higher MA of the recent trades" means | The live trend class with the trailing-mean window raised from 6 to 18 (3 min) / 30 (5 min) buckets; bucket, σ span, 0.7 σ, min-buckets unchanged. |
| L2 | Does the longer MA replace or augment the 1-min class in overshoot minutes | Primary = replace (`ma3`, `ma5`); `_and` variants reported as ablation. |
| L3 | Exit trend class | Unchanged (1-min) in every mode. |
| L4 | Stop and placeholder | The rule in force now (candle stop, 0.2 %) applied to every mode over the whole window, so the modes differ by entries only; the live run's earlier stop rules are not reproduced (fires are, P&L is not). |
| L5 | Entry fill | Fire trade's price for every mode (the live book mid is not stored at scale). |
| L6 | Window | 2026-10-18 11:41Z → 2026-10-20 21:23Z (the whole CB-armed history). |
