from __future__ import annotations

import subprocess
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4


ACTIVE_RECORD_STALE_AFTER_HOURS = 8
LEASE_POLICIES = ("renew", "finish", "yield")
DEFAULT_LEASE_POLICY = "renew"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def utc_after_minutes(minutes: int, *, from_timestamp: str | None = None) -> str:
    if minutes <= 0:
        raise ValueError("Lease minutes must be positive.")
    reference = (
        datetime.now(timezone.utc)
        if from_timestamp is None
        else parse_utc_timestamp(from_timestamp)
    )
    return (reference + timedelta(minutes=minutes)).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def parse_utc_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_stale_utc_timestamp(
    value: str,
    *,
    now: datetime | None = None,
    stale_after_hours: int = ACTIVE_RECORD_STALE_AFTER_HOURS,
) -> bool:
    reference = now or datetime.now(timezone.utc)
    age = reference - parse_utc_timestamp(value)
    return age >= timedelta(hours=max(0, stale_after_hours))


def is_past_utc_timestamp(
    value: str,
    *,
    now: datetime | None = None,
) -> bool:
    reference = now or datetime.now(timezone.utc)
    return parse_utc_timestamp(value) <= reference


def normalize_lease_policy(
    value: str | None,
    *,
    allow_none: bool = False,
) -> str | None:
    if value is None:
        if allow_none:
            return None
        raise ValueError("Lease policy must not be empty.")
    normalized = value.strip().lower()
    if not normalized:
        if allow_none:
            return None
        raise ValueError("Lease policy must not be empty.")
    if normalized not in LEASE_POLICIES:
        allowed = ", ".join(LEASE_POLICIES)
        raise ValueError(f"Lease policy must be one of: {allowed}.")
    return normalized


def make_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def normalize_scopes(scope: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in scope:
        value = normalize_scope(item)
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    return tuple(normalized)


def normalize_scope(scope: str) -> str:
    value = scope.strip().replace("\\", "/")
    if not value:
        raise ValueError("Scope entries must not be empty.")

    if value.endswith("/**"):
        value = value[:-3]
    elif value.endswith("/*"):
        value = value[:-2]

    path = PurePosixPath(value)
    parts = [part for part in path.parts if part not in ("", ".")]
    return str(PurePosixPath(*parts)) if parts else "."


def current_git_branch(repo_root: Path) -> str | None:
    git_dir = _git_dir(repo_root)
    if git_dir is None:
        return None

    head_path = git_dir / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not head.startswith("ref: "):
        return None

    ref = head[5:].strip()
    prefix = "refs/heads/"
    if ref.startswith(prefix):
        return ref[len(prefix) :]
    return ref or None


def current_worktree_paths(repo_root: Path) -> tuple[str, ...]:
    commands = (
        (
            "git",
            "-C",
            str(repo_root),
            "ls-files",
            "--modified",
            "--deleted",
            "--others",
            "--exclude-standard",
        ),
        (
            "git",
            "-C",
            str(repo_root),
            "diff",
            "--cached",
            "--name-only",
            "--relative",
        ),
    )
    paths: list[str] = []
    seen: set[str] = set()
    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                check=False,
                text=True,
            )
        except OSError:
            return ()
        if result.returncode != 0:
            return ()
        for raw_line in result.stdout.splitlines():
            value = raw_line.strip()
            if not value:
                continue
            normalized = normalize_scope(value)
            if normalized not in seen:
                paths.append(normalized)
                seen.add(normalized)
    return tuple(paths)


def _git_dir(repo_root: Path) -> Path | None:
    git_path = repo_root / ".git"
    if git_path.is_dir():
        return git_path
    if not git_path.is_file():
        return None

    try:
        content = git_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not content.lower().startswith("gitdir:"):
        return None

    location = content.split(":", maxsplit=1)[1].strip()
    if not location:
        return None
    git_dir = Path(location)
    if not git_dir.is_absolute():
        git_dir = (repo_root / git_dir).resolve()
    return git_dir


def json_ready(value: object) -> object:
    if is_dataclass(value):
        return {
            field.name: json_ready(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return value


def infer_object_type(object_id: str) -> str:
    if object_id.startswith("claim_"):
        return "claim"
    if object_id.startswith("intent_"):
        return "intent"
    if object_id.startswith("context_"):
        return "context"
    if object_id.startswith("conflict_"):
        return "conflict"
    raise ValueError(f"Unsupported Loom object id: {object_id}.")


def overlapping_scopes(
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> tuple[str, ...]:
    overlaps: list[str] = []
    for left_scope in left:
        for right_scope in right:
            overlap = _overlap_pair(left_scope, right_scope)
            if overlap and overlap not in overlaps:
                overlaps.append(overlap)
    return tuple(overlaps)


def _overlap_pair(left: str, right: str) -> str | None:
    if left == "." or right == ".":
        return "."

    left_parts = PurePosixPath(left).parts
    right_parts = PurePosixPath(right).parts

    if len(left_parts) <= len(right_parts) and left_parts == right_parts[: len(left_parts)]:
        return right
    if len(right_parts) <= len(left_parts) and right_parts == left_parts[: len(right_parts)]:
        return left
    return None
