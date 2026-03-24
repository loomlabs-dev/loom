from __future__ import annotations

import getpass
import os
import socket
import subprocess


_SESSION_ENV_KEYS = (
    ("LOOM_SESSION", "loom"),
    ("TMUX_PANE", "tmux"),
    ("WT_SESSION", "wt"),
    ("TERM_SESSION_ID", "term"),
    ("STY", "screen"),
    ("KITTY_WINDOW_ID", "kitty"),
    ("WINDOWID", "window"),
)
_TRANSIENT_PARENT_COMMANDS = {
    "sh",
    "bash",
    "zsh",
    "dash",
    "fish",
    "ksh",
    "csh",
    "tcsh",
}


def resolve_agent_identity(
    explicit: str | None = None,
    *,
    default_agent: str | None = None,
    terminal_aliases: dict[str, str] | None = None,
) -> tuple[str, str]:
    if explicit and explicit.strip():
        return explicit.strip(), "flag"

    env_agent = os.environ.get("LOOM_AGENT")
    if env_agent and env_agent.strip():
        return env_agent.strip(), "env"

    terminal_identity = current_terminal_identity()
    if terminal_aliases:
        bound_agent = terminal_aliases.get(terminal_identity)
        if bound_agent and bound_agent.strip():
            return bound_agent.strip(), "terminal"

    if default_agent and default_agent.strip():
        return default_agent.strip(), "project"

    return terminal_identity, "tty"


def current_terminal_identity() -> str:
    user = getpass.getuser()
    host = socket.gethostname().split(".", maxsplit=1)[0]
    return f"{user}@{host}:{_terminal_label()}"


def terminal_identity_is_stable(identity: str | None = None) -> bool:
    value = current_terminal_identity() if identity is None else identity
    return not value.rsplit(":", maxsplit=1)[-1].startswith("pid-")


def terminal_identity_pid(identity: str) -> int | None:
    label = identity.rsplit(":", maxsplit=1)[-1]
    for prefix in ("pid-", "host-"):
        if not label.startswith(prefix):
            continue
        pid_text = label.removeprefix(prefix)
        if not pid_text.isdigit():
            return None
        return int(pid_text)
    return None


def terminal_identity_process_is_alive(
    identity: str,
    *,
    kill_fn=os.kill,
) -> bool | None:
    pid = terminal_identity_pid(identity)
    if pid is None:
        return None
    try:
        kill_fn(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _terminal_label() -> str:
    for env_key, label in _SESSION_ENV_KEYS:
        value = os.environ.get(env_key)
        if value and value.strip():
            return f"{label}-{value.strip()}"
    for file_descriptor in (0, 1, 2):
        try:
            return os.path.basename(os.ttyname(file_descriptor))
        except OSError:
            continue
    host_pid = _host_process_pid()
    if host_pid is not None:
        return f"host-{host_pid}"
    return f"pid-{os.getpid()}"


def _host_process_pid(*, max_depth: int = 8) -> int | None:
    current_pid = os.getpid()
    parent_pid = os.getppid()
    visited: set[int] = set()
    depth = 0
    while parent_pid > 1 and parent_pid != current_pid and depth < max_depth:
        if parent_pid in visited:
            break
        visited.add(parent_pid)
        parent_info = _read_process_info(parent_pid)
        if parent_info is None:
            break
        next_parent_pid, command = parent_info
        command_name = os.path.basename(command).strip().lower()
        if command_name and command_name not in _TRANSIENT_PARENT_COMMANDS:
            return parent_pid
        parent_pid = next_parent_pid
        depth += 1
    return None


def _read_process_info(pid: int) -> tuple[int, str] | None:
    try:
        output = subprocess.check_output(
            ["ps", "-o", "ppid=,comm=", "-p", str(pid)],
            text=True,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not output:
        return None
    parts = output.split(None, 1)
    if len(parts) != 2:
        return None
    parent_pid_text, command = parts
    if not parent_pid_text.isdigit():
        return None
    return int(parent_pid_text), command.strip()
