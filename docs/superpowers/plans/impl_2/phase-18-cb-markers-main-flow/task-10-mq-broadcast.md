# Task 10: MQ broadcast of the CB columns

**Phase:** 18 — CB Markers Main Flow
**Layer:** MQ
**Depends on:** Task 09
**Produces:** `SharedIndicatorConfig.on_change`, publish-on-change in `Robot._publish_shared_indicators`, new entries in `configs/shared_indicators_config.yaml`
**Gate:** G10

---

## Goal

Put the agreed CB values on the wire to `trade_executor`, and make sure a one-minute marker is not missed by the 30-second heartbeat.

## Context

- `configs/shared_indicators_config.yaml` is an allowlist of `{name, timeframes}`. `config_loader.load_shared_indicators_config` (line ~149) returns `list[SharedIndicatorConfig]`.
- `Robot._publish_shared_indicators` (`robots/robot.py` ~321) runs every tick, returns early unless `indicator_publish_interval_sec` (default 30 s) has elapsed, then reads `data_point.get(cfg.name, tf)` for every entry and publishes finite values as floats under the wire name `{tf}_{name}`. Read failures and non-finite values are skipped and logged once.

Broadcast list, timeframes `[15, 60, 240]` for all:

| Names | `on_change` |
|---|---|
| `cb_high`, `cb_low`, `cb_zone_long`, `cb_zone_short`, `cbnc_high`, `cbnc_low` | false |
| `cb_inzone_long`, `cb_inzone_short`, `extdone_high`, `extdone_low`, `cb_f_extdone_long`, `cb_f_extdone_short`, `cb_f_trend_long`, `cb_f_trend_short` | true |

Not broadcast: `cb_f_mcx_*`, `cbx_inzone_*`, bands (`*_std`, `*_up`, `*_dn`), `cbnc_tgt_*`, `cbnc_zone_*`, `cbnc_inzone_*`, `extdone_*_lvl`.

## Files

- Modify: `config_loader.py` — `SharedIndicatorConfig.on_change: bool = False`; loader reads optional `on_change`
- Modify: `robots/robot.py` — `_publish_shared_indicators`
- Modify: `configs/shared_indicators_config.yaml`
- Test: `tests/test_indicator_publisher.py` (extend) or a new `tests/test_cb_broadcast.py` next to it — follow whichever file already tests `_publish_shared_indicators`; find it with `grep -rn "_publish_shared_indicators" tests/`

## Interface

```python
@dataclass
class SharedIndicatorConfig:
    name: str
    timeframes: list[int]
    on_change: bool = False
```

Behaviour of `_publish_shared_indicators(data_point)`:

1. No publisher → return (unchanged).
2. Read every `on_change` entry's current value (guarded like today's reads). If any finite value differs from the value last **published** for that `(name, tf)`, the interval check is bypassed for this tick.
3. Otherwise the interval check applies as today.
4. When publishing, publish **all** allowlisted readings (not only the changed ones), and remember the published value of each `on_change` reading.

## Key Constraints

- Existing entries (`ema_7/14/25`, `sar_002_02`) keep `on_change` false and their behaviour: one publish per interval.
- A value that is NaN / unreadable never counts as a change and is not published.
- The first publish after start is not a "change" trigger by itself: it happens on the first tick anyway because no publish has happened yet (keep today's behaviour).
- Worst case rate: 8 names × 3 tfs flipping; a publish is still at most once per tick. Do not add a second timer.
- No change to `mq/indicator_publisher.py` or the wire format. Booleans travel as `1.0` / `0.0`.
- No change in `trade_executor`.

## Tests (RED first)

- `test_loader_reads_on_change` — YAML with `on_change: true` on one entry and none on another → `True`, `False`.
- `test_loader_default_file_contains_cb_entries` — the default config contains the 14 names above with timeframes `[15, 60, 240]` and the `on_change` flags in the table; does **not** contain `cb_f_mcx_long`, `cbx_inzone_long`, `cbnc_inzone_long`.
- `test_interval_still_throttles_plain_entries` — only non-`on_change` values change between two ticks 1 s apart → one publish.
- `test_on_change_bypasses_interval` — `15_cb_inzone_long` goes 0.0 → 1.0 between two ticks 1 s apart → second tick publishes; the batch includes `15_cb_high` too.
- `test_no_change_no_extra_publish` — same `on_change` values on 5 ticks within the interval → one publish.
- `test_change_back_publishes_again` — 0 → 1 → 0 across three ticks → three publishes.
- `test_nan_is_not_a_change` — value 1.0 → NaN → no publish on the NaN tick; NaN → 1.0 afterwards → no publish (last published value was 1.0).
- `test_unreadable_on_change_entry_does_not_break_tick` — `data_point.get` raises `KeyError` for one `on_change` name → no exception; other readings still published at the interval.
- `test_bools_published_as_floats` — published value for `15_cb_inzone_long` is `1.0` (float).

Use a fake publisher that records `(wire_name, value)` batches and a fake clock, the way the existing tests of this method do.

## Steps

- [x] Find and read the existing tests of `_publish_shared_indicators`. Write the new tests. Run in Docker: `docker compose -p cbtest run --rm ohlc_gen python -m pytest tests/test_indicator_publisher.py tests/test_cb_broadcast.py -q` → new tests FAIL.
- [x] Implement the loader field, the robot change, the config entries. Re-run → PASS.
- [x] Regression: `... python -m pytest tests -q -k "publish or robot or shared"` → PASS. *(2 collection errors in `tests/nn` (`optuna` missing in the image) are pre-existing, identical on the base branch.)*
- [ ] *(NOT RUN — user-gated; checklist handed over in the task report and the results doc.)* G10, live dry run. **Do not start, restart or recreate the `live` service yourself** — its environment (keys, mode, pair) lives in the user's shell and a recreate from here falls back to defaults. Hand the user this checklist and wait for their output:
  1. Start live as they normally do, on the work branch.
  2. Run `python3 scripts/e2e_indicator_broadcast_probe.py` (read its docstring first for arguments) or tail the executor's indicator log.
  3. Confirm the 14 names × 3 tfs arrive with finite values; `cbnc_*` appear from the second minute on; a `cb_inzone` flip arrives within ~1 s of the tick.
- [x] Record the user's dry-run result in the results doc. If they have not run it, state "G10 not run" — do not mark it passed. *(Results doc states "G10 not run".)*
- [x] Final-review fix wave (2026-10-06). *As executed (final review): an on_change flip publishes ONLY the changed (name, tf) readings (recorded in `_last_published_on_change`) and no longer resets `_last_indicator_publish_at`, so the 30 s heartbeat (whole allowlist) keeps its cadence; wire names, payload and YAML unchanged. `test_on_change_bypasses_interval` now expects a one-reading batch; added `test_flip_publish_does_not_reset_heartbeat`, `test_flapping_value_publishes_one_reading_per_tick`, `test_nan_then_different_finite_publishes`. A read failing with `KeyError` (CB columns absent) logs one plain warning per (name, tf) without traceback; other exceptions keep the traceback.*
- [ ] Stage; describe; wait for confirmation. Suggested message: `feat(mq): broadcast candle-bound levels, marker and filters`. *(As executed: staged by the controller with `git add` after review; no commit — the commit waits for the user's confirmation at handover.)*
