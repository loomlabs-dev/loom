from __future__ import annotations

import ast
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol


IGNORED_DIRS = {
    ".git",
    ".loom",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}

SCRIPT_EXTENSIONS = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
)
SCRIPT_IMPORT_RE = re.compile(
    r"""
    (?:
        \b(?:import|export)\s+(?:type\s+)?(?:[^"'`\n;]+?\s+from\s+)?["']([^"']+)["']
        |
        \brequire\(\s*["']([^"']+)["']\s*\)
        |
        \bimport\(\s*["']([^"']+)["']\s*\)
    )
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class DependencyLink:
    source: str
    target: str


class DependencyAnalyzer(Protocol):
    name: str
    extensions: tuple[str, ...]

    def build_state(self, source_files: tuple[tuple[str, Path], ...]) -> object:
        ...

    def supports_file(self, relative_path: str) -> bool:
        ...

    def imports_for_file(
        self,
        *,
        relative_path: str,
        absolute_path: Path,
        state: object,
    ) -> tuple[str, ...]:
        ...


@dataclass(frozen=True)
class _PythonAnalyzerState:
    module_index: dict[str, str]
    package_index: dict[str, str]
    file_packages: dict[str, str]


@dataclass(frozen=True)
class _ScriptAnalyzerState:
    script_index: set[str]


class PythonDependencyAnalyzer:
    name = "python"
    extensions = (".py",)

    def build_state(self, source_files: tuple[tuple[str, Path], ...]) -> _PythonAnalyzerState:
        python_files = tuple(
            (relative_path, absolute_path)
            for relative_path, absolute_path in source_files
            if self.supports_file(relative_path)
        )
        module_index: dict[str, str] = {}
        package_index: dict[str, str] = {}
        file_packages: dict[str, str] = {}

        for relative_path, _ in python_files:
            candidates = _module_candidates(relative_path)
            if not candidates:
                continue

            canonical_module = candidates[0]
            file_packages[relative_path] = _package_name(relative_path, canonical_module)
            for candidate in candidates:
                module_index.setdefault(candidate, relative_path)
            if relative_path.endswith("/__init__.py") or relative_path == "__init__.py":
                for candidate in candidates:
                    package_index.setdefault(candidate, relative_path)

        return _PythonAnalyzerState(
            module_index=module_index,
            package_index=package_index,
            file_packages=file_packages,
        )

    def supports_file(self, relative_path: str) -> bool:
        return relative_path.endswith(".py")

    def imports_for_file(
        self,
        *,
        relative_path: str,
        absolute_path: Path,
        state: object,
    ) -> tuple[str, ...]:
        if not isinstance(state, _PythonAnalyzerState):
            raise TypeError("invalid_python_analyzer_state")
        return tuple(
            _parse_import_targets(
                absolute_path=absolute_path,
                current_package=state.file_packages.get(relative_path, ""),
                module_index=state.module_index,
                package_index=state.package_index,
            )
        )


class ScriptDependencyAnalyzer:
    name = "script"
    extensions = SCRIPT_EXTENSIONS

    def build_state(self, source_files: tuple[tuple[str, Path], ...]) -> _ScriptAnalyzerState:
        return _ScriptAnalyzerState(
            script_index={
                relative_path
                for relative_path, _ in source_files
                if self.supports_file(relative_path)
            }
        )

    def supports_file(self, relative_path: str) -> bool:
        return _is_script_file(relative_path)

    def imports_for_file(
        self,
        *,
        relative_path: str,
        absolute_path: Path,
        state: object,
    ) -> tuple[str, ...]:
        if not isinstance(state, _ScriptAnalyzerState):
            raise TypeError("invalid_script_analyzer_state")
        return tuple(
            _parse_script_import_targets(
                absolute_path=absolute_path,
                relative_path=relative_path,
                script_index=state.script_index,
            )
        )


DEFAULT_ANALYZERS: tuple[DependencyAnalyzer, ...] = (
    PythonDependencyAnalyzer(),
    ScriptDependencyAnalyzer(),
)
SOURCE_EXTENSIONS = tuple(
    dict.fromkeys(
        extension
        for analyzer in DEFAULT_ANALYZERS
        for extension in analyzer.extensions
    )
)


class DependencyGraph:
    def __init__(
        self,
        *,
        files: tuple[str, ...],
        imports_by_file: dict[str, tuple[str, ...]],
    ) -> None:
        self._files = files
        self._imports_by_file = imports_by_file

    @classmethod
    def build(
        cls,
        repo_root: Path,
        *,
        analyzers: tuple[DependencyAnalyzer, ...] = DEFAULT_ANALYZERS,
    ) -> DependencyGraph:
        source_files = _discover_source_files(
            repo_root,
            extensions=_extensions_for_analyzers(analyzers),
        )
        analyzer_states: dict[str, object] = {
            analyzer.name: analyzer.build_state(source_files)
            for analyzer in analyzers
        }

        imports_by_file: dict[str, tuple[str, ...]] = {}
        for relative_path, absolute_path in source_files:
            for analyzer in analyzers:
                if not analyzer.supports_file(relative_path):
                    continue
                imports_by_file[relative_path] = analyzer.imports_for_file(
                    relative_path=relative_path,
                    absolute_path=absolute_path,
                    state=analyzer_states[analyzer.name],
                )
                break

        return cls(
            files=tuple(relative_path for relative_path, _ in source_files),
            imports_by_file=imports_by_file,
        )

    def direct_links_between(
        self,
        left_scope: tuple[str, ...],
        right_scope: tuple[str, ...],
    ) -> tuple[DependencyLink, ...]:
        left_files = _files_for_scope(self._files, left_scope)
        right_files = _files_for_scope(self._files, right_scope)
        if not left_files or not right_files:
            return ()

        links: list[DependencyLink] = []
        seen: set[tuple[str, str]] = set()
        for source in left_files:
            for target in self._imports_by_file.get(source, ()):
                if target in right_files and (source, target) not in seen:
                    links.append(DependencyLink(source=source, target=target))
                    seen.add((source, target))
        for source in right_files:
            for target in self._imports_by_file.get(source, ()):
                if target in left_files and (source, target) not in seen:
                    links.append(DependencyLink(source=source, target=target))
                    seen.add((source, target))
        return tuple(links)


def source_fingerprint(
    repo_root: Path,
    *,
    analyzers: tuple[DependencyAnalyzer, ...] = DEFAULT_ANALYZERS,
) -> tuple[tuple[str, int, int], ...]:
    fingerprint: list[tuple[str, int, int]] = []
    for relative_path, absolute_path in _discover_source_files(
        repo_root,
        extensions=_extensions_for_analyzers(analyzers),
    ):
        try:
            stat = absolute_path.stat()
        except OSError:
            continue
        fingerprint.append((relative_path, stat.st_mtime_ns, stat.st_size))
    return tuple(fingerprint)


def python_source_fingerprint(repo_root: Path) -> tuple[tuple[str, int, int], ...]:
    return source_fingerprint(repo_root)


def _discover_source_files(
    repo_root: Path,
    *,
    extensions: tuple[str, ...] = SOURCE_EXTENSIONS,
) -> tuple[tuple[str, Path], ...]:
    files: list[tuple[str, Path]] = []
    for extension in extensions:
        pattern = f"*{extension}"
        for absolute_path in repo_root.rglob(pattern):
            relative_path = absolute_path.relative_to(repo_root).as_posix()
            if _should_ignore(relative_path):
                continue
            if relative_path.endswith(".d.ts"):
                continue
            files.append((relative_path, absolute_path))
    files.sort(key=lambda item: item[0])
    return tuple(files)


def _extensions_for_analyzers(analyzers: tuple[DependencyAnalyzer, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            extension
            for analyzer in analyzers
            for extension in analyzer.extensions
        )
    )


def _should_ignore(relative_path: str) -> bool:
    parts = PurePosixPath(relative_path).parts
    return any(part in IGNORED_DIRS for part in parts)


def _module_candidates(relative_path: str) -> tuple[str, ...]:
    path = PurePosixPath(relative_path)
    if path.suffix != ".py":
        return ()

    if path.name == "__init__.py":
        parts = path.parts[:-1]
    else:
        parts = (*path.parts[:-1], path.stem)

    if not parts:
        return ()

    candidates: list[str] = []
    full_module = ".".join(parts)
    candidates.append(full_module)
    if parts[0] == "src" and len(parts) > 1:
        stripped_module = ".".join(parts[1:])
        if stripped_module not in candidates:
            candidates.insert(0, stripped_module)
    return tuple(candidates)


def _package_name(relative_path: str, module_name: str) -> str:
    if relative_path.endswith("/__init__.py") or relative_path == "__init__.py":
        return module_name
    if "." not in module_name:
        return ""
    return module_name.rsplit(".", maxsplit=1)[0]


def _parse_import_targets(
    *,
    absolute_path: Path,
    current_package: str,
    module_index: dict[str, str],
    package_index: dict[str, str],
) -> list[str]:
    try:
        tree = ast.parse(absolute_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []

    targets: list[str] = []
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _resolve_module_path(alias.name, module_index, package_index)
                if target and target not in seen:
                    targets.append(target)
                    seen.add(target)
        elif isinstance(node, ast.ImportFrom):
            candidates = _from_import_candidates(node, current_package)
            for candidate in candidates:
                target = _resolve_module_path(candidate, module_index, package_index)
                if target and target not in seen:
                    targets.append(target)
                    seen.add(target)
                    break
    return targets


def _from_import_candidates(node: ast.ImportFrom, current_package: str) -> tuple[str, ...]:
    base_module = _resolve_from_base_module(node, current_package)
    if base_module is None:
        return ()

    candidates: list[str] = []
    if node.names[0].name == "*":
        if base_module:
            candidates.append(base_module)
        return tuple(candidates)

    for alias in node.names:
        if alias.name == "*":
            continue
        if base_module:
            candidates.append(f"{base_module}.{alias.name}")
            candidates.append(base_module)
        else:
            candidates.append(alias.name)
    return tuple(candidates)


def _resolve_from_base_module(node: ast.ImportFrom, current_package: str) -> str | None:
    if node.level == 0:
        return node.module or ""

    package_parts = [part for part in current_package.split(".") if part]
    if node.level > len(package_parts) + 1:
        return None

    keep = len(package_parts) - (node.level - 1)
    base_parts = package_parts[:keep]
    if node.module:
        base_parts.extend(part for part in node.module.split(".") if part)
    return ".".join(base_parts)


def _resolve_module_path(
    module_name: str,
    module_index: dict[str, str],
    package_index: dict[str, str],
) -> str | None:
    if not module_name:
        return None

    candidate = module_name
    while candidate:
        if candidate in module_index:
            return module_index[candidate]
        if candidate in package_index:
            return package_index[candidate]
        if "." not in candidate:
            break
        candidate = candidate.rsplit(".", maxsplit=1)[0]
    return None


def _files_for_scope(files: tuple[str, ...], scope: tuple[str, ...]) -> set[str]:
    if not scope:
        return set()
    matched = set()
    for file_path in files:
        if any(_scope_matches_file(scope_item, file_path) for scope_item in scope):
            matched.add(file_path)
    return matched


def _scope_matches_file(scope: str, file_path: str) -> bool:
    if scope == ".":
        return True
    if file_path == scope or file_path.startswith(f"{scope}/"):
        return True
    stem_path = _source_stem_path(file_path)
    if stem_path is not None and (stem_path == scope or stem_path.startswith(f"{scope}/")):
        return True
    return False


def _parse_script_import_targets(
    *,
    absolute_path: Path,
    relative_path: str,
    script_index: set[str],
) -> list[str]:
    try:
        source = absolute_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    targets: list[str] = []
    seen: set[str] = set()
    for match in SCRIPT_IMPORT_RE.finditer(source):
        specifier = next(group for group in match.groups() if group is not None)
        target = _resolve_script_import(
            specifier=specifier,
            relative_path=relative_path,
            script_index=script_index,
        )
        if target is None or target in seen:
            continue
        targets.append(target)
        seen.add(target)
    return targets


def _resolve_script_import(
    *,
    specifier: str,
    relative_path: str,
    script_index: set[str],
) -> str | None:
    if not specifier.startswith("."):
        return None

    current_dir = str(PurePosixPath(relative_path).parent)
    candidate = posixpath.normpath(posixpath.join(current_dir, specifier))
    if candidate.startswith("../"):
        return None
    if candidate == ".":
        return None

    direct = _match_script_candidate(
        candidate,
        script_index=script_index,
        extension_order=_script_resolution_extensions(relative_path),
    )
    if direct is not None:
        return direct

    index_candidate = _match_script_candidate(
        posixpath.join(candidate, "index"),
        script_index=script_index,
        extension_order=_script_resolution_extensions(relative_path),
    )
    return index_candidate


def _match_script_candidate(
    candidate: str,
    *,
    script_index: set[str],
    extension_order: tuple[str, ...],
) -> str | None:
    if candidate in script_index:
        return candidate

    candidate_path = PurePosixPath(candidate)
    suffix = candidate_path.suffix
    if suffix in SCRIPT_EXTENSIONS:
        stem = candidate[: -len(suffix)]
        for extension in extension_order:
            alternate = f"{stem}{extension}"
            if alternate in script_index:
                return alternate
        return None

    for extension in extension_order:
        alternate = f"{candidate}{extension}"
        if alternate in script_index:
            return alternate
    return None


def _script_resolution_extensions(relative_path: str) -> tuple[str, ...]:
    suffix = PurePosixPath(relative_path).suffix
    if suffix in {".ts", ".tsx"}:
        return (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        return (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")
    return SCRIPT_EXTENSIONS


def _is_script_file(relative_path: str) -> bool:
    return PurePosixPath(relative_path).suffix in SCRIPT_EXTENSIONS


def _source_stem_path(file_path: str) -> str | None:
    path = PurePosixPath(file_path)
    suffix = path.suffix
    if suffix not in SOURCE_EXTENSIONS:
        return None
    return str(path.with_suffix(""))
