from __future__ import annotations

import getpass
import os
import socket


_SESSION_ENV_KEYS = (
    ("LOOM_SESSION", "loom"),
    ("TMUX_PANE", "tmux"),
    ("WT_SESSION", "wt"),
    ("TERM_SESSION_ID", "term"),
    ("STY", "screen"),
    ("KITTY_WINDOW_ID", "kitty"),
    ("WINDOWID", "window"),
)


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
    if not label.startswith("pid-"):
        return None
    pid_text = label.removeprefix("pid-")
    if not pid_text.isdigit():
        return None
    return int(pid_text)


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
    try:
        return os.path.basename(os.ttyname(0))
    except OSError:
        return f"pid-{os.getpid()}"
