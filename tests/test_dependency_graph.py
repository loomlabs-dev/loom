from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.dependency_graph import DependencyGraph, source_fingerprint  # noqa: E402


class _FakeAnalyzer:
    name = "fake"
    extensions = (".loomtest",)

    def build_state(
        self,
        source_files: tuple[tuple[str, pathlib.Path], ...],
    ) -> set[str]:
        return {relative_path for relative_path, _ in source_files}

    def supports_file(self, relative_path: str) -> bool:
        return relative_path.endswith(".loomtest")

    def imports_for_file(
        self,
        *,
        relative_path: str,
        absolute_path: pathlib.Path,
        state: object,
    ) -> tuple[str, ...]:
        assert isinstance(state, set)
        target = absolute_path.read_text(encoding="utf-8").strip()
        if not target:
            return ()
        return (target,) if target in state else ()


class DependencyGraphTest(unittest.TestCase):
    def test_python_analyzer_resolves_absolute_and_relative_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / "src" / "api").mkdir(parents=True)
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "api" / "helpers.py").write_text(
                "def helper() -> str:\n    return 'ok'\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "auth" / "session.py").write_text(
                "class UserSession:\n    pass\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "api" / "handlers.py").write_text(
                "from .helpers import helper\n"
                "from auth.session import UserSession\n\n"
                "def handle_request() -> UserSession:\n"
                "    helper()\n"
                "    return UserSession()\n",
                encoding="utf-8",
            )

            graph = DependencyGraph.build(repo_root)

        helper_links = graph.direct_links_between(
            ("src/api/handlers.py",),
            ("src/api/helpers.py",),
        )
        auth_links = graph.direct_links_between(
            ("src/api/handlers.py",),
            ("src/auth/session.py",),
        )

        self.assertEqual(len(helper_links), 1)
        self.assertEqual(helper_links[0].source, "src/api/handlers.py")
        self.assertEqual(helper_links[0].target, "src/api/helpers.py")
        self.assertEqual(len(auth_links), 1)
        self.assertEqual(auth_links[0].source, "src/api/handlers.py")
        self.assertEqual(auth_links[0].target, "src/auth/session.py")

    def test_python_analyzer_resolves_package_import_to_init_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "api").mkdir(parents=True)
            (repo_root / "src" / "auth" / "__init__.py").write_text(
                "from .session import UserSession\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "auth" / "session.py").write_text(
                "class UserSession:\n    pass\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "api" / "consumer.py").write_text(
                "import auth\n\n"
                "def load() -> str:\n"
                "    return auth.UserSession.__name__\n",
                encoding="utf-8",
            )

            graph = DependencyGraph.build(repo_root)

        links = graph.direct_links_between(
            ("src/api/consumer.py",),
            ("src/auth/__init__.py",),
        )

        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].source, "src/api/consumer.py")
        self.assertEqual(links[0].target, "src/auth/__init__.py")

    def test_python_analyzer_ignores_syntax_error_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "auth" / "session.py").write_text(
                "class UserSession:\n    pass\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "broken.py").write_text(
                "from auth.session import UserSession\n"
                "def nope(:\n",
                encoding="utf-8",
            )

            graph = DependencyGraph.build(repo_root)

        links = graph.direct_links_between(
            ("src/broken.py",),
            ("src/auth/session.py",),
        )

        self.assertEqual(links, ())

    def test_script_analyzer_resolves_extensionless_and_index_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / "src" / "web" / "widgets").mkdir(parents=True)
            (repo_root / "src" / "web" / "shared.ts").write_text(
                "export const shared = 'ok';\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "web" / "widgets" / "index.ts").write_text(
                "export const widget = 'widget';\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "web" / "types.d.ts").write_text(
                "export type SharedType = string;\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "web" / "index.ts").write_text(
                "import { shared } from './shared';\n"
                "import { widget } from './widgets';\n"
                "import type { SharedType } from './types';\n\n"
                "export const value = `${shared}-${widget}`;\n",
                encoding="utf-8",
            )

            graph = DependencyGraph.build(repo_root)
            fingerprint = source_fingerprint(repo_root)

        shared_links = graph.direct_links_between(
            ("src/web/index.ts",),
            ("src/web/shared.ts",),
        )
        widget_links = graph.direct_links_between(
            ("src/web/index.ts",),
            ("src/web/widgets/index.ts",),
        )
        type_links = graph.direct_links_between(
            ("src/web/index.ts",),
            ("src/web/types.d.ts",),
        )

        self.assertEqual(len(shared_links), 1)
        self.assertEqual(shared_links[0].target, "src/web/shared.ts")
        self.assertEqual(len(widget_links), 1)
        self.assertEqual(widget_links[0].target, "src/web/widgets/index.ts")
        self.assertEqual(type_links, ())
        self.assertEqual(
            sorted(relative_path for relative_path, _, _ in fingerprint),
            [
                "src/web/index.ts",
                "src/web/shared.ts",
                "src/web/widgets/index.ts",
            ],
        )

    def test_build_supports_custom_analyzers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / "notes").mkdir()
            (repo_root / "notes" / "a.loomtest").write_text(
                "notes/b.loomtest\n",
                encoding="utf-8",
            )
            (repo_root / "notes" / "b.loomtest").write_text(
                "",
                encoding="utf-8",
            )

            analyzer = _FakeAnalyzer()
            graph = DependencyGraph.build(repo_root, analyzers=(analyzer,))
            fingerprint = source_fingerprint(repo_root, analyzers=(analyzer,))

        links = graph.direct_links_between(
            ("notes/a.loomtest",),
            ("notes/b.loomtest",),
        )

        self.assertEqual(len(fingerprint), 2)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].source, "notes/a.loomtest")
        self.assertEqual(links[0].target, "notes/b.loomtest")


if __name__ == "__main__":
    unittest.main()
