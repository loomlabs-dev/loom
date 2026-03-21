from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .util import utc_now

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix fallback
    fcntl = None


CONFIG_FILENAME = "config.json"
DEFAULT_DB_FILENAME = "coordination.db"
DEFAULT_SOCKET_FILENAME = "daemon.sock"
DEFAULT_RUNTIME_FILENAME = "daemon.json"
DEFAULT_LOG_FILENAME = "daemon.log"
CURRENT_SCHEMA_VERSION = 2


class LoomProjectError(RuntimeError):
    """Raised when the local Loom project state is missing or invalid."""


class ProjectNotInitializedError(LoomProjectError):
    """Raised when Loom has not been initialized in the current repository."""

    code = "project_not_initialized"


@dataclass(frozen=True)
class LoomProject:
    repo_root: Path
    loom_dir: Path
    config_path: Path
    db_path: Path
    socket_path: Path
    runtime_path: Path
    log_path: Path
    schema_version: int
    default_agent: str | None = None
    terminal_aliases: dict[str, str] = field(default_factory=dict)
    resume_sequences: dict[str, int] = field(default_factory=dict)


def initialize_project(start: Path | None = None) -> tuple[LoomProject, bool]:
    repo_root = find_git_root(start)
    if repo_root is None:
        raise LoomProjectError("Loom only works inside a Git repository.")

    loom_dir = repo_root / ".loom"
    loom_dir.mkdir(exist_ok=True)

    config_path = loom_dir / CONFIG_FILENAME
    with _locked_config(config_path):
        created = not config_path.exists()
        if created:
            config = {
                "schema_version": CURRENT_SCHEMA_VERSION,
                "created_at": utc_now(),
                "database": DEFAULT_DB_FILENAME,
                "daemon_socket": DEFAULT_SOCKET_FILENAME,
                "daemon_runtime": DEFAULT_RUNTIME_FILENAME,
                "daemon_log": DEFAULT_LOG_FILENAME,
                "terminal_aliases": {},
                "resume_sequences": {},
            }
            _write_config_unlocked(config_path, config)

    return load_project(repo_root), created


def set_default_agent(
    agent_id: str,
    start: Path | None = None,
) -> LoomProject:
    project = load_project(start)
    value = agent_id.strip()
    if not value:
        raise LoomProjectError("Agent name must not be empty.")
    _update_config(
        project.config_path,
        lambda config: config.__setitem__("default_agent", value),
    )
    return load_project(project.repo_root)


def set_terminal_agent(
    agent_id: str,
    *,
    terminal_identity: str,
    start: Path | None = None,
) -> LoomProject:
    project = load_project(start)
    value = agent_id.strip()
    terminal = terminal_identity.strip()
    if not value:
        raise LoomProjectError("Agent name must not be empty.")
    if not terminal:
        raise LoomProjectError("Terminal identity must not be empty.")
    def _apply(config: dict[str, object]) -> None:
        aliases = _config_string_map(config.get("terminal_aliases"))
        aliases[terminal] = value
        config["terminal_aliases"] = aliases

    _update_config(project.config_path, _apply)
    return load_project(project.repo_root)


def clear_terminal_agent(
    *,
    terminal_identity: str,
    start: Path | None = None,
) -> LoomProject:
    project = load_project(start)
    terminal = terminal_identity.strip()
    if not terminal:
        raise LoomProjectError("Terminal identity must not be empty.")
    def _apply(config: dict[str, object]) -> None:
        aliases = _config_string_map(config.get("terminal_aliases"))
        aliases.pop(terminal, None)
        config["terminal_aliases"] = aliases

    _update_config(project.config_path, _apply)
    return load_project(project.repo_root)


def set_resume_sequence(
    agent_id: str,
    sequence: int,
    *,
    start: Path | None = None,
) -> LoomProject:
    project = load_project(start)
    value = agent_id.strip()
    if not value:
        raise LoomProjectError("Agent name must not be empty.")
    if sequence < 0:
        raise LoomProjectError("Resume sequence must not be negative.")
    def _apply(config: dict[str, object]) -> None:
        resume_sequences = _config_int_map(config.get("resume_sequences"))
        resume_sequences[value] = sequence
        config["resume_sequences"] = resume_sequences

    _update_config(project.config_path, _apply)
    return load_project(project.repo_root)


def load_project(start: Path | None = None) -> LoomProject:
    project_root = find_initialized_project_root(start)
    if project_root is None:
        git_root = find_git_root(start)
        if git_root is None:
            raise LoomProjectError("Loom only works inside a Git repository.")
        raise ProjectNotInitializedError(
            "Loom is not initialized in this repository. Run `loom init` first."
        )

    loom_dir = project_root / ".loom"
    config_path = loom_dir / CONFIG_FILENAME
    try:
        config = _read_config(config_path)
    except FileNotFoundError as error:
        raise ProjectNotInitializedError(
            "Loom is not initialized in this repository. Run `loom init` first."
        ) from error
    try:
        schema_version = int(config.get("schema_version", CURRENT_SCHEMA_VERSION))
        return LoomProject(
            repo_root=project_root,
            loom_dir=loom_dir,
            config_path=config_path,
            db_path=loom_dir / _config_filename(config.get("database"), DEFAULT_DB_FILENAME),
            socket_path=loom_dir / _config_filename(config.get("daemon_socket"), DEFAULT_SOCKET_FILENAME),
            runtime_path=loom_dir / _config_filename(config.get("daemon_runtime"), DEFAULT_RUNTIME_FILENAME),
            log_path=loom_dir / _config_filename(config.get("daemon_log"), DEFAULT_LOG_FILENAME),
            schema_version=schema_version,
            default_agent=_config_string(config.get("default_agent")),
            terminal_aliases=_config_string_map(config.get("terminal_aliases")),
            resume_sequences=_config_int_map(config.get("resume_sequences")),
        )
    except (TypeError, ValueError) as error:
        raise LoomProjectError(f"Invalid Loom config: {config_path}") from error


def find_git_root(start: Path | None = None) -> Path | None:
    origin = (start or Path.cwd()).resolve()
    candidates = [origin, *origin.parents]
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    return None


def find_initialized_project_root(start: Path | None = None) -> Path | None:
    origin = (start or Path.cwd()).resolve()
    candidates = [origin, *origin.parents]
    for candidate in candidates:
        if (candidate / ".loom" / CONFIG_FILENAME).is_file():
            return candidate
    return None


def _read_config(config_path: Path) -> dict[str, object]:
    try:
        return _read_config_unlocked(config_path)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise LoomProjectError(f"Invalid Loom config: {config_path}") from error


def _read_config_unlocked(config_path: Path) -> dict[str, object]:
    loaded = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Loom config must be a JSON object.")
    return {str(key): value for key, value in loaded.items()}


def _write_config(config_path: Path, config: dict[str, object]) -> None:
    with _locked_config(config_path):
        _write_config_unlocked(config_path, config)


def _write_config_unlocked(config_path: Path, config: dict[str, object]) -> None:
    config_path.parent.mkdir(exist_ok=True)
    payload = f"{json.dumps(config, indent=2)}\n"
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=str(config_path.parent),
        prefix=f".{config_path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, config_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _update_config(
    config_path: Path,
    updater,
) -> None:
    with _locked_config(config_path):
        config = _read_config(config_path)
        updater(config)
        _write_config_unlocked(config_path, config)


@contextlib.contextmanager
def _locked_config(config_path: Path):
    lock_path = config_path.with_name(f"{config_path.name}.lock")
    lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _config_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _config_filename(value: object, default: str) -> str:
    if value is None:
        return default
    normalized = _config_string(value)
    if normalized is None:
        raise ValueError("Config filename values must be non-empty strings.")
    return normalized


def _config_string_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, item in value.items():
        normalized_key = _config_string(key)
        normalized_value = _config_string(item)
        if normalized_key and normalized_value:
            normalized[normalized_key] = normalized_value
    return normalized


def _config_int_map(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, item in value.items():
        normalized_key = _config_string(key)
        if normalized_key is None:
            continue
        try:
            normalized_value = int(item)
        except (TypeError, ValueError):
            continue
        if normalized_value >= 0:
            normalized[normalized_key] = normalized_value
    return normalized
