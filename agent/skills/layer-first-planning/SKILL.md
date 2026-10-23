---
name: layer-first-planning
description: Use when writing a plan for any feature in simple_trader — extends superpowers:writing-plans by enforcing Docker-first entry point, layer-ordered implementation, interface-before-code at each boundary, and Docker-verified integration tests before each layer starts
---

# Layer-First Planning

## Overview

Plans are organized by the simple_trader pipeline layers, not by module or file.
Docker configuration is defined first — it is the authoritative description of how each layer is invoked.
Each layer boundary is defined as function signatures only before any implementation.
Integration test for each boundary is written RED before either side is implemented.

Extends `superpowers:writing-plans`.

## Layer Order (simple_trader)

Always in this order, top to bottom:

| # | Layer | What it does |
|---|-------|-------------|
| 0 | **Docker** | Compose commands, entry points, how each layer is invoked from outside |
| 1 | **Data acquisition** | Fetch/store market data |
| 2 | **Training pipeline** | Run trainer, produce model artifacts |
| 3 | **Test data prep** | Calculate indicators, prepare inputs for backtesting |
| 4 | **Indicators** | Technical indicator implementations |
| 5 | **Backtesting** | Run backtest, consume indicators + strategy |
| 6 | **Business logic** | Domain rules, risk, portfolio constraints |
| 7 | **Strategy** | Entry/exit logic |
| 8 | **Signals logic** | Signal generation and filtering |
| 9 | **Signal library** | Reusable signal primitives |
| 10 | **Position management** | Position tracking, sizing, lifecycle |

## Plan Structure

Each layer section follows this sequence, strictly:

### Step 0 — Docker (first, before any layer)

Define compose commands and entry points:
```bash
docker compose run --rm trader grab-data --symbol BTC --from 2024-01-01
docker compose run --rm trainer train --config config/default.yaml
docker compose run --rm backtest run --strategy momentum --period 90d
```
These commands are the ground truth. Implementation must make them work.

### Step 1 — Interface (signatures only, no body)

```python
# Layer N public interface — what layer N+1 consumes
def get_ohlcv(symbol: str, start: date, end: date) -> list[OHLCV]: ...
def store_ohlcv(records: list[OHLCV]) -> None: ...
```

Rules:
- No body. No `pass`. Just `...`.
- No `Any`. No untyped `dict`. Concrete types only.
- Only what the next layer actually calls — nothing internal.

### Step 2 — Integration test (RED, runs in Docker)

Write the test for layer N → N+1 connection before implementing either side.
Test must run in Docker and fail (RED) before proceeding.

```python
def test_data_layer_feeds_indicator_layer():
    records = get_ohlcv("BTC", date(2024,1,1), date(2024,3,1))
    result = compute_rsi(records, period=14)
    assert len(result) == len(records) - 14
```

### Step 3 — Unit tests (RED)

Cover all valuable cases per function:
- Happy path
- Key edge cases (empty input, boundary values, missing data)
- Failure modes (invalid args, downstream errors)

All RED before implementation starts.

### Step 4 — Implementation

Code that turns unit tests GREEN, then integration tests GREEN.
All must pass inside Docker before starting next layer.

## Plan Template

```markdown
## Docker Entry Points
[compose commands for each layer]
Verified: [ ] docker compose up succeeds

## Layer 1: Data Acquisition
### Interface
[function signatures]
### Integration test → Layer 2 (RED in Docker)
[test wiring layers 1 and 2]
### Unit tests
[valuable cases: happy path, edge cases, failure modes]
### Constraints / notes
[non-obvious constraints only — no implementation code]

## Layer 2: Training Pipeline
[same structure]

## Layer N: ...
```

## Rules

- Docker config written before any layer. No exceptions.
- Plan organized by layer, not by file or module. Module-first → restart.
- No implementation code in plan. Signatures and test descriptions only.
- Layer N not started until layer N-1 integration test is RED in Docker.
- Layer N not completed until layer N unit + integration tests are GREEN in Docker.
- Integration test written before either connected layer is implemented.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Plan grouped by file / class | Rewrite grouped by layer |
| Plan contains function bodies | Strip to `...` signatures |
| Docker section skipped | Always first — defines the contract |
| Only one unit test per function | Cover happy path + edge cases + failure modes |
| Integration test skipped — "obvious connection" | Write it RED first, always |
| Tests pass locally only | Always verify in Docker before proceeding |
| Layer N+1 started before N is GREEN | Block until Docker green |
