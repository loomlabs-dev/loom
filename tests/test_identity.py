from __future__ import annotations

import os
import pathlib
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.identity import (  # noqa: E402
    _terminal_label,
    current_terminal_identity,
    resolve_agent_identity,
    terminal_identity_pid,
    terminal_identity_process_is_alive,
    terminal_identity_is_stable,
)


class IdentityTest(unittest.TestCase):
    def test_resolve_agent_identity_prefers_explicit_without_resolving_terminal(self) -> None:
        with patch("loom.identity.current_terminal_identity") as current_identity:
            agent_id, source = resolve_agent_identity(
                "agent-flag",
                default_agent="agent-project",
                terminal_aliases={"user@host:tty-1": "agent-terminal"},
            )

        self.assertEqual((agent_id, source), ("agent-flag", "flag"))
        current_identity.assert_not_called()

    def test_resolve_agent_identity_prefers_env_without_resolving_terminal(self) -> None:
        with patch.dict(os.environ, {"LOOM_AGENT": "agent-env"}, clear=False):
            with patch("loom.identity.current_terminal_identity") as current_identity:
                agent_id, source = resolve_agent_identity(
                    None,
                    default_agent="agent-project",
                    terminal_aliases={"user@host:tty-1": "agent-terminal"},
                )

        self.assertEqual((agent_id, source), ("agent-env", "env"))
        current_identity.assert_not_called()

    def test_resolve_agent_identity_prefers_terminal_binding_over_project_default(self) -> None:
        with patch("loom.identity.current_terminal_identity", return_value="user@host:tty-1"):
            agent_id, source = resolve_agent_identity(
                None,
                default_agent="agent-project",
                terminal_aliases={"user@host:tty-1": "agent-terminal"},
            )

        self.assertEqual((agent_id, source), ("agent-terminal", "terminal"))

    def test_resolve_agent_identity_falls_back_to_project_default_before_tty(self) -> None:
        with patch("loom.identity.current_terminal_identity", return_value="user@host:tty-1"):
            agent_id, source = resolve_agent_identity(
                None,
                default_agent="agent-project",
                terminal_aliases={"user@host:other-tty": "agent-terminal"},
            )

        self.assertEqual((agent_id, source), ("agent-project", "project"))

    def test_resolve_agent_identity_falls_back_to_terminal_identity(self) -> None:
        with patch("loom.identity.current_terminal_identity", return_value="user@host:tty-1"):
            agent_id, source = resolve_agent_identity(None)

        self.assertEqual((agent_id, source), ("user@host:tty-1", "tty"))

    def test_current_terminal_identity_formats_user_host_and_label(self) -> None:
        with patch("loom.identity.getpass.getuser", return_value="dev"), patch(
            "loom.identity.socket.gethostname",
            return_value="machine.example.com",
        ), patch("loom.identity._terminal_label", return_value="tmux-7"):
            identity = current_terminal_identity()

        self.assertEqual(identity, "dev@machine:tmux-7")

    def test_terminal_identity_is_stable_distinguishes_pid_labels(self) -> None:
        self.assertFalse(terminal_identity_is_stable("dev@machine:pid-1234"))
        self.assertTrue(terminal_identity_is_stable("dev@machine:host-4321"))
        self.assertTrue(terminal_identity_is_stable("dev@machine:tmux-7"))

    def test_terminal_identity_pid_extracts_process_bound_labels_only(self) -> None:
        self.assertEqual(terminal_identity_pid("dev@machine:pid-1234"), 1234)
        self.assertEqual(terminal_identity_pid("dev@machine:host-4321"), 4321)
        self.assertIsNone(terminal_identity_pid("dev@machine:tmux-7"))
        self.assertIsNone(terminal_identity_pid("dev@machine:pid-nope"))

    def test_terminal_identity_process_is_alive_checks_process_bound_labels(self) -> None:
        self.assertFalse(
            terminal_identity_process_is_alive(
                "dev@machine:pid-1234",
                kill_fn=lambda pid, signal: (_ for _ in ()).throw(ProcessLookupError()),
            )
        )
        self.assertTrue(
            terminal_identity_process_is_alive(
                "dev@machine:pid-1234",
                kill_fn=lambda pid, signal: None,
            )
        )
        self.assertTrue(
            terminal_identity_process_is_alive(
                "dev@machine:host-4321",
                kill_fn=lambda pid, signal: None,
            )
        )
        self.assertIsNone(
            terminal_identity_process_is_alive(
                "dev@machine:tmux-7",
                kill_fn=lambda pid, signal: None,
            )
        )

    def test_terminal_label_prefers_session_env_key_order(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TMUX_PANE": "42",
                "LOOM_SESSION": "alpha",
            },
            clear=False,
        ), patch("loom.identity.os.ttyname") as ttyname:
            label = _terminal_label()

        self.assertEqual(label, "loom-alpha")
        ttyname.assert_not_called()

    def test_terminal_label_falls_back_to_tty_basename_then_host_pid_then_pid(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch(
            "loom.identity.os.ttyname",
            side_effect=lambda fd: "/dev/ttys003" if fd == 1 else (_ for _ in ()).throw(OSError("no tty")),
        ):
            label = _terminal_label()

        self.assertEqual(label, "ttys003")

        with patch.dict(os.environ, {}, clear=True), patch(
            "loom.identity.os.ttyname",
            side_effect=OSError("no tty"),
        ), patch(
            "loom.identity._host_process_pid",
            return_value=3210,
        ):
            label = _terminal_label()

        self.assertEqual(label, "host-3210")

        with patch.dict(os.environ, {}, clear=True), patch(
            "loom.identity.os.ttyname",
            side_effect=OSError("no tty"),
        ), patch("loom.identity._host_process_pid", return_value=None), patch(
            "loom.identity.os.getpid",
            return_value=4321,
        ):
            label = _terminal_label()

        self.assertEqual(label, "pid-4321")

    def test_host_process_pid_skips_shell_ancestors_to_find_stable_host(self) -> None:
        parent_chain = {
            200: (150, "/bin/bash"),
            150: (100, "/bin/zsh"),
            100: (1, "/Applications/Codex.app/Contents/Resources/codex"),
        }

        with patch("loom.identity.os.getpid", return_value=300), patch(
            "loom.identity.os.getppid",
            return_value=200,
        ), patch(
            "loom.identity._read_process_info",
            side_effect=lambda pid: parent_chain.get(pid),
        ):
            from loom.identity import _host_process_pid  # noqa: E402

            self.assertEqual(_host_process_pid(), 100)


if __name__ == "__main__":
    unittest.main()
