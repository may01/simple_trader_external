# Phase 1: Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the project skeleton and infrastructure layer — config, logging, paths, constants.

**Architecture:** Flat dataclass `Config` reads from env vars. `TradeLogger` writes per-pair log files. `paths.py` pure functions derive storage paths from `Config`. `constants.py` holds enums for all domain constants shared across layers.

**Tech Stack:** Python 3.11+, pytest, setuptools src-layout. No external dependencies needed for this phase.

---

## Working Directory

```
⚠️ All relative paths and bash commands below resolve from this directory.
```

| Branch type | Working directory |
|-------------|-------------------|
| `main` branch | `/home/om/projects/simple_trader/main` |
| Worktree branch | `/home/om/projects/simple_trader/worktrees/<branch-name>/` |

For parallel phases (3a+3b, 6a+6b): each agent creates its own worktree under `/home/om/projects/simple_trader/worktrees/` using the `superpowers:using-git-worktrees` skill, then works entirely within that directory.

---

## File Structure

```
src/simple_trader/
  __init__.py
  infrastructure/
    __init__.py
    config.py
    constants.py
    logging.py
    paths.py
tests/
  __init__.py
  conftest.py
  infrastructure/
    __init__.py
    test_config.py
    test_constants.py
    test_logging.py
    test_paths.py
pyproject.toml
requirements.txt
requirements-dev.txt
```

---

## Task 1: Project Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `src/simple_trader/__init__.py`
- Create: `src/simple_trader/infrastructure/__init__.py`
- Create: `tests/__init__.py`, `tests/conftest.py`
- Create: `tests/infrastructure/__init__.py`

- [ ] **Step 1: Create directory tree**

Working directory: `/home/om/projects/simple_trader/main`

```bash
mkdir -p src/simple_trader/infrastructure
mkdir -p tests/infrastructure
touch src/simple_trader/__init__.py
touch src/simple_trader/infrastructure/__init__.py
touch tests/__init__.py
touch tests/infrastructure/__init__.py
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "simple_trader"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pandas>=2.0",
    "numpy>=1.24",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-mock>=3.12",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.mypy]
python_version = "3.11"
strict = true
```

- [ ] **Step 3: Write `requirements.txt`**

```
pandas>=2.0
numpy>=1.24
python-binance>=1.0.19
```

- [ ] **Step 4: Write `requirements-dev.txt`**

```
-r requirements.txt
pytest>=7.4
pytest-mock>=3.12
mypy>=1.5
black>=23.0
```

- [ ] **Step 5: Write `tests/conftest.py`**

```python
import pytest
```

- [ ] **Step 6: Install in editable mode**

```bash
pip install -e ".[dev]"
```

Expected: `Successfully installed simple_trader-0.1.0`

- [ ] **Step 7: Verify import works**

```bash
python -c "import simple_trader; print('ok')"
```

Expected: `ok`

- [ ] **Step 8: Commit skeleton**

```bash
git add pyproject.toml requirements.txt requirements-dev.txt src/ tests/
git commit -m "chore: add project skeleton and pyproject.toml"
```

---

## Task 2: Constants Module

**Files:**
- Create: `src/simple_trader/infrastructure/constants.py`
- Create: `tests/infrastructure/test_constants.py`

- [ ] **Step 1: Write failing test**

`tests/infrastructure/test_constants.py`:

```python
from simple_trader.infrastructure.constants import StrategyAction, PositionState, PositionType

def test_strategy_action_nothing_exists():
    assert StrategyAction.NOTHING is not None

def test_strategy_action_open_long_exists():
    assert StrategyAction.OPEN_LONG is not None

def test_strategy_action_all_distinct():
    actions = [
        StrategyAction.NOTHING,
        StrategyAction.OPEN_LONG,
        StrategyAction.OPEN_SHORT,
        StrategyAction.CLOSE_LONG,
        StrategyAction.CLOSE_SHORT,
        StrategyAction.MOVE_STOP_LOSS_LONG,
        StrategyAction.MOVE_STOP_LOSS_SHORT,
        StrategyAction.DO_STOP_LOSS,
    ]
    assert len(set(actions)) == len(actions)

def test_position_state_wait_is_string_wait():
    assert PositionState.WAIT.value == "WAIT"

def test_position_state_all_states_exist():
    states = [
        PositionState.WAIT,
        PositionState.WAIT_BUY,
        PositionState.WAIT_SELL,
        PositionState.WAIT_SAFETY_BUY,
        PositionState.WAIT_SAFETY_SELL,
    ]
    assert len(states) == 5

def test_position_type_unknown_exists():
    assert PositionType.UNKNOWN is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/infrastructure/test_constants.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.infrastructure.constants'`

- [ ] **Step 3: Write `src/simple_trader/infrastructure/constants.py`**

```python
from enum import Enum, auto


class StrategyAction(Enum):
    NOTHING = auto()
    OPEN_LONG = auto()
    OPEN_SHORT = auto()
    CLOSE_LONG = auto()
    CLOSE_SHORT = auto()
    MOVE_STOP_LOSS_LONG = auto()
    MOVE_STOP_LOSS_SHORT = auto()
    DO_STOP_LOSS = auto()


class PositionState(Enum):
    WAIT = "WAIT"
    WAIT_BUY = "WAIT_BUY"
    WAIT_SELL = "WAIT_SELL"
    WAIT_SAFETY_BUY = "WAIT_SAFETY_BUY"
    WAIT_SAFETY_SELL = "WAIT_SAFETY_SELL"


class PositionType(Enum):
    UNKNOWN = "UNKNOWN"
    LONG = "LONG"
    SHORT = "SHORT"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/infrastructure/test_constants.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/infrastructure/constants.py tests/infrastructure/test_constants.py
git commit -m "feat: add infrastructure constants (StrategyAction, PositionState, PositionType)"
```

---

## Task 3: Config Module

**Files:**
- Create: `src/simple_trader/infrastructure/config.py`
- Create: `tests/infrastructure/test_config.py`

- [ ] **Step 1: Write failing test**

`tests/infrastructure/test_config.py`:

```python
import pytest
from simple_trader.infrastructure.config import Config


def test_config_reads_pair_from_env(monkeypatch):
    monkeypatch.setenv("PAIR", "btc_usdt")
    config = Config()
    assert config.pair == "btc_usdt"


def test_config_defaults_pair_to_link_usdt(monkeypatch):
    monkeypatch.delenv("PAIR", raising=False)
    config = Config()
    assert config.pair == "link_usdt"


def test_config_reads_available_threads_as_int(monkeypatch):
    monkeypatch.setenv("AVAILABLE_THREADS", "4")
    config = Config()
    assert config.available_threads == 4


def test_config_use_nn_simulation_true(monkeypatch):
    monkeypatch.setenv("USE_NN_SIMULATION", "True")
    config = Config()
    assert config.use_nn_simulation is True


def test_config_use_nn_simulation_false_by_default(monkeypatch):
    monkeypatch.delenv("USE_NN_SIMULATION", raising=False)
    config = Config()
    assert config.use_nn_simulation is False


def test_config_is_trader_test_when_env_is_one(monkeypatch):
    monkeypatch.setenv("IS_TRAIDER_TEST", "1")
    config = Config()
    assert config.is_trader_test is True


def test_config_data_start_as_int(monkeypatch):
    monkeypatch.setenv("DATA_START", "1700000000000")
    config = Config()
    assert config.data_start == 1700000000000
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/infrastructure/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.infrastructure.config'`

- [ ] **Step 3: Write `src/simple_trader/infrastructure/config.py`**

```python
import os
from dataclasses import dataclass, field


@dataclass
class Config:
    pair: str = field(
        default_factory=lambda: os.environ.get("PAIR", "link_usdt")
    )
    data_set_name: str = field(
        default_factory=lambda: os.environ.get("DATA_SET_NAME", "default")
    )
    root_folder: str = field(
        default_factory=lambda: os.environ.get("ROOT_FOLDER", "local")
    )
    data_root: str = field(
        default_factory=lambda: os.environ.get("DATA_ROOT", "trader_data")
    )
    data_start: int = field(
        default_factory=lambda: int(os.environ.get("DATA_START", "0"))
    )
    data_end: int = field(
        default_factory=lambda: int(os.environ.get("DATA_END", "9999999999999"))
    )
    trainer_time_step: int = field(
        default_factory=lambda: int(os.environ.get("TRAINER_TIME_STEP", "1"))
    )
    available_threads: int = field(
        default_factory=lambda: int(os.environ.get("AVAILABLE_THREADS", "1"))
    )
    use_nn_simulation: bool = field(
        default_factory=lambda: os.environ.get("USE_NN_SIMULATION", "False") == "True"
    )
    is_trader_test: bool = field(
        default_factory=lambda: os.environ.get("IS_TRAIDER_TEST", "0") == "1"
    )
    binance_api_key: str = field(
        default_factory=lambda: os.environ.get("BINANCE_API_KEY", "")
    )
    binance_api_secret: str = field(
        default_factory=lambda: os.environ.get("BINANCE_API_SECRET", "")
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/infrastructure/test_config.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/infrastructure/config.py tests/infrastructure/test_config.py
git commit -m "feat: add Config dataclass reading from environment variables"
```

---

## Task 4: Paths Module

**Files:**
- Create: `src/simple_trader/infrastructure/paths.py`
- Create: `tests/infrastructure/test_paths.py`

- [ ] **Step 1: Write failing test**

`tests/infrastructure/test_paths.py`:

```python
from pathlib import Path
import pytest
from simple_trader.infrastructure.config import Config
from simple_trader.infrastructure.paths import (
    root_folder, data_folder, shared_folder,
    nn_folder, action_folder, stats_folder,
)


def make_config(**kwargs):
    import os
    defaults = {
        "PAIR": "link_usdt",
        "DATA_SET_NAME": "train",
        "ROOT_FOLDER": "local",
        "DATA_ROOT": "trader_data",
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        os.environ[k] = v
    return Config()


def test_root_folder_local_uses_trader_data_local():
    config = make_config(ROOT_FOLDER="local", DATA_ROOT="mydata",
                         DATA_SET_NAME="train", PAIR="link_usdt")
    assert root_folder(config) == Path("/trader_data_local/mydata/train_link_usdt")


def test_root_folder_remote_uses_trader_data():
    config = make_config(ROOT_FOLDER="remote", DATA_ROOT="mydata",
                         DATA_SET_NAME="train", PAIR="link_usdt")
    assert root_folder(config) == Path("/trader_data/mydata/train_link_usdt")


def test_data_folder_is_root_slash_data():
    config = make_config()
    assert data_folder(config) == root_folder(config) / "data"


def test_shared_folder_is_root_slash_shared():
    config = make_config()
    assert shared_folder(config) == root_folder(config) / "shared"


def test_nn_folder_is_shared_slash_nn_data():
    config = make_config()
    assert nn_folder(config) == shared_folder(config) / "nn_data"


def test_action_folder_is_shared_slash_actions():
    config = make_config()
    assert action_folder(config) == shared_folder(config) / "actions"


def test_stats_folder_is_repo_local():
    config = make_config(DATA_ROOT="trader_data", PAIR="link_usdt")
    assert stats_folder(config) == Path("stats/trader_data/link_usdt")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/infrastructure/test_paths.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.infrastructure.paths'`

- [ ] **Step 3: Write `src/simple_trader/infrastructure/paths.py`**

```python
from pathlib import Path
from .config import Config


def root_folder(config: Config) -> Path:
    if config.root_folder == "remote":
        base = Path("/trader_data")
    else:
        base = Path("/trader_data_local")
    return base / config.data_root / f"{config.data_set_name}_{config.pair}"


def data_folder(config: Config) -> Path:
    return root_folder(config) / "data"


def shared_folder(config: Config) -> Path:
    return root_folder(config) / "shared"


def nn_folder(config: Config) -> Path:
    return shared_folder(config) / "nn_data"


def action_folder(config: Config) -> Path:
    return shared_folder(config) / "actions"


def stats_folder(config: Config) -> Path:
    return Path("stats") / config.data_root / config.pair
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/infrastructure/test_paths.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/simple_trader/infrastructure/paths.py tests/infrastructure/test_paths.py
git commit -m "feat: add paths module for storage path construction"
```

---

## Task 5: Logging Module

**Files:**
- Create: `src/simple_trader/infrastructure/logging.py`
- Create: `tests/infrastructure/test_logging.py`

- [ ] **Step 1: Write failing test**

`tests/infrastructure/test_logging.py`:

```python
import pytest
from pathlib import Path
from simple_trader.infrastructure.config import Config
from simple_trader.infrastructure.logging import TradeLogger


@pytest.fixture
def tmp_config(monkeypatch, tmp_path):
    monkeypatch.setenv("PAIR", "link_usdt")
    return Config()


def test_log_writes_to_file(tmp_config, tmp_path):
    logger = TradeLogger(tmp_config, log_dir=tmp_path)
    logger.log("hello")
    log_file = tmp_path / "LOG_link_usdt.txt"
    assert log_file.read_text() == "hello\n"


def test_log_appends_multiple_messages(tmp_config, tmp_path):
    logger = TradeLogger(tmp_config, log_dir=tmp_path)
    logger.log("line1")
    logger.log("line2")
    content = (tmp_path / "LOG_link_usdt.txt").read_text()
    assert "line1" in content
    assert "line2" in content


def test_log_revenue_writes_to_per_thread_file(tmp_config, tmp_path):
    logger = TradeLogger(tmp_config, log_dir=tmp_path)
    logger.log_revenue("profit=5%", time_point=12345, thread=0)
    rev_file = tmp_path / "REVENUE_link_usdt_0.txt"
    assert rev_file.exists()
    assert "profit=5%" in rev_file.read_text()


def test_log_error_prefixes_error(tmp_config, tmp_path):
    logger = TradeLogger(tmp_config, log_dir=tmp_path)
    logger.log_error("something failed")
    content = (tmp_path / "LOG_link_usdt.txt").read_text()
    assert "ERROR" in content
    assert "something failed" in content
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/infrastructure/test_logging.py -v
```

Expected: `ModuleNotFoundError: No module named 'simple_trader.infrastructure.logging'`

- [ ] **Step 3: Write `src/simple_trader/infrastructure/logging.py`**

```python
from pathlib import Path
from .config import Config


class TradeLogger:
    def __init__(self, config: Config, log_dir: Path = Path("output")) -> None:
        self._config = config
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._log_dir / f"LOG_{config.pair}.txt"

    def log(self, msg: str, do_print: bool = False) -> None:
        with open(self._log_path, "a") as f:
            f.write(f"{msg}\n")
        if do_print:
            print(msg)

    def log_error(self, msg: str) -> None:
        self.log(f"ERROR: {msg}", do_print=True)

    def log_warn(self, msg: str) -> None:
        self.log(f"WARN: {msg}", do_print=True)

    def log_revenue(self, msg: str, time_point: int, thread: int) -> None:
        line = f"[t={time_point} th={thread}] {msg}"
        print(line)
        rev_path = self._log_dir / f"REVENUE_{self._config.pair}_{thread}.txt"
        with open(rev_path, "a") as f:
            f.write(f"{line}\n")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/infrastructure/test_logging.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Run full Phase 1 test suite**

```bash
pytest tests/infrastructure/ -v
```

Expected: `18+ passed, 0 failed`

- [ ] **Step 6: Commit**

```bash
git add src/simple_trader/infrastructure/logging.py tests/infrastructure/test_logging.py
git commit -m "feat: add TradeLogger for per-pair file logging"
```
