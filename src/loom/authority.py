from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .local_store.records import ClaimRecord, IntentRecord
from .util import overlapping_scopes


AUTHORITY_CONFIG_FILENAME = "loom.yaml"
VALID_AUTHORITY_ROLES = {"root_truth", "policy", "boundary"}


class LoomAuthorityError(ValueError):
    code = "invalid_authority_config"


@dataclass(frozen=True)
class AuthoritySurface:
    id: str
    path: str
    role: str
    kind: str | None = None
    description: str | None = None
    topics: tuple[str, ...] = ()
    scope_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuthorityConfig:
    config_path: Path
    version: int
    surfaces: tuple[AuthoritySurface, ...]


def read_authority_summary(
    repo_root: Path,
    *,
    changed_paths: tuple[str, ...] = (),
    claims: tuple[ClaimRecord, ...] = (),
    intents: tuple[IntentRecord, ...] = (),
) -> dict[str, object]:
    config_path = repo_root / AUTHORITY_CONFIG_FILENAME
    if not config_path.exists():
        return {
            "enabled": False,
            "status": "absent",
            "config_path": AUTHORITY_CONFIG_FILENAME,
            "surface_count": 0,
            "surfaces": (),
            "changed_surfaces": (),
            "changed_scope_hints": (),
            "declaration_changed": False,
            "issues": (),
            "error_code": None,
            "next_steps": (),
            "affected_active_work": (),
        }
    try:
        config = load_authority_config(repo_root)
    except LoomAuthorityError as error:
        return {
            "enabled": True,
            "status": "invalid",
            "config_path": config_path.relative_to(repo_root).as_posix(),
            "surface_count": 0,
            "surfaces": (),
            "changed_surfaces": (),
            "changed_scope_hints": (),
            "declaration_changed": AUTHORITY_CONFIG_FILENAME in set(changed_paths),
            "issues": (
                {
                    "code": error.code,
                    "message": str(error),
                },
            ),
            "error_code": error.code,
            "next_steps": (
                f"Fix {AUTHORITY_CONFIG_FILENAME} and run `loom start` or `loom status` again.",
            ),
            "affected_active_work": (),
        }
    surfaces_payload = tuple(_surface_payload(surface) for surface in config.surfaces)
    changed_set = set(changed_paths)
    declaration_changed = AUTHORITY_CONFIG_FILENAME in changed_set
    changed_surfaces = tuple(
        payload
        for payload in surfaces_payload
        if declaration_changed or str(payload["path"]) in changed_set
    )
    changed_scope_hints = _changed_scope_hints(changed_surfaces)
    summary = {
        "enabled": True,
        "status": "valid",
        "config_path": config.config_path.relative_to(repo_root).as_posix(),
        "surface_count": len(config.surfaces),
        "surfaces": surfaces_payload,
        "changed_surfaces": changed_surfaces,
        "changed_scope_hints": changed_scope_hints,
        "declaration_changed": declaration_changed,
        "issues": (),
        "error_code": None,
        "next_steps": (),
        "affected_active_work": (),
    }
    return _with_affected_active_work(
        summary,
        claims=claims,
        intents=intents,
    )


def authority_has_changed(summary: dict[str, object] | None) -> bool:
    if not isinstance(summary, dict) or summary.get("status") != "valid":
        return False
    changed_surfaces = tuple(summary.get("changed_surfaces", ()))
    return bool(changed_surfaces)


def authority_focus_scope(summary: dict[str, object] | None) -> tuple[str, ...]:
    if not authority_has_changed(summary):
        return ()
    assert isinstance(summary, dict)
    scope_hints = tuple(str(path).strip() for path in summary.get("changed_scope_hints", ()))
    if scope_hints:
        return tuple(path for path in scope_hints if path)
    changed_surfaces = tuple(summary.get("changed_surfaces", ()))
    return tuple(
        str(surface.get("path", "")).strip()
        for surface in changed_surfaces
        if isinstance(surface, dict) and str(surface.get("path", "")).strip()
    )


def authority_focus_summary(summary: dict[str, object] | None) -> str | None:
    if not authority_has_changed(summary):
        return None
    assert isinstance(summary, dict)
    if bool(summary.get("declaration_changed")):
        return "Declared authority changed; coordinate the affected truth surfaces before other work."
    return "Authority surfaces changed; coordinate the affected truth surfaces before other work."


def authority_focus_reason(summary: dict[str, object] | None) -> str | None:
    scope = authority_focus_scope(summary)
    if not scope:
        return None
    assert isinstance(summary, dict)
    if bool(summary.get("declaration_changed")):
        return (
            "loom.yaml changed, so Loom is treating these declared authority surfaces "
            "and mapped repo areas as the first repository truth to coordinate."
        )
    return (
        "A declared authority surface changed, so Loom is treating its mapped repo "
        "areas as the first repository truth to coordinate."
    )


def load_authority_config(repo_root: Path) -> AuthorityConfig:
    config_path = repo_root / AUTHORITY_CONFIG_FILENAME
    try:
        payload = _parse_minimal_authority_yaml(config_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise LoomAuthorityError(f"Unable to read {AUTHORITY_CONFIG_FILENAME}.") from error
    except LoomAuthorityError:
        raise
    except ValueError as error:
        raise LoomAuthorityError(f"Invalid authority declaration in {AUTHORITY_CONFIG_FILENAME}: {error}") from error

    version = payload["version"]
    if version != 1:
        raise LoomAuthorityError(
            f"Invalid authority declaration in {AUTHORITY_CONFIG_FILENAME}: unsupported version {version}."
        )

    surfaces_payload = payload["authority"]["surfaces"]
    surfaces: list[AuthoritySurface] = []
    seen_ids: set[str] = set()
    for item in surfaces_payload:
        surface_id = _required_string(item, "id")
        if surface_id in seen_ids:
            raise LoomAuthorityError(
                f"Invalid authority declaration in {AUTHORITY_CONFIG_FILENAME}: duplicate surface id '{surface_id}'."
            )
        seen_ids.add(surface_id)
        raw_path = _required_string(item, "path")
        normalized_path = _validated_repo_relative_path(repo_root, raw_path)
        role = _required_string(item, "role")
        if role not in VALID_AUTHORITY_ROLES:
            raise LoomAuthorityError(
                f"Invalid authority declaration in {AUTHORITY_CONFIG_FILENAME}: unsupported role '{role}'."
            )
        absolute_path = (repo_root / normalized_path).resolve()
        if not absolute_path.exists():
            raise LoomAuthorityError(
                f"Invalid authority declaration in {AUTHORITY_CONFIG_FILENAME}: missing file '{normalized_path}'."
            )
        kind = _optional_string(item, "kind")
        description = _optional_string(item, "description")
        topics = _optional_string_tuple(item, "topics")
        scope_hints = _optional_repo_relative_path_tuple(repo_root, item, "scope_hints")
        surfaces.append(
            AuthoritySurface(
                id=surface_id,
                path=normalized_path,
                role=role,
                kind=kind,
                description=description,
                topics=topics,
                scope_hints=scope_hints,
            )
        )
    return AuthorityConfig(
        config_path=config_path,
        version=version,
        surfaces=tuple(surfaces),
    )


def _surface_payload(surface: AuthoritySurface) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": surface.id,
        "path": surface.path,
        "role": surface.role,
    }
    if surface.kind is not None:
        payload["kind"] = surface.kind
    if surface.description is not None:
        payload["description"] = surface.description
    if surface.topics:
        payload["topics"] = surface.topics
    if surface.scope_hints:
        payload["scope_hints"] = surface.scope_hints
    return payload


def _changed_scope_hints(
    surfaces_payload: tuple[dict[str, object], ...],
) -> tuple[str, ...]:
    hints: list[str] = []
    seen: set[str] = set()
    for surface in surfaces_payload:
        if not isinstance(surface, dict):
            continue
        for hint in tuple(surface.get("scope_hints", ())):
            normalized = str(hint).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            hints.append(normalized)
    return tuple(hints)


def _with_affected_active_work(
    summary: dict[str, object],
    *,
    claims: tuple[ClaimRecord, ...],
    intents: tuple[IntentRecord, ...],
) -> dict[str, object]:
    scope = authority_focus_scope(summary)
    if not scope:
        return summary
    affected_work = (
        _affected_claim_payloads(scope, claims=claims)
        + _affected_intent_payloads(scope, intents=intents)
    )
    if not affected_work:
        return summary
    payload = dict(summary)
    payload["affected_active_work"] = affected_work
    return payload


def _affected_claim_payloads(
    scope: tuple[str, ...],
    *,
    claims: tuple[ClaimRecord, ...],
) -> tuple[dict[str, object], ...]:
    affected: list[dict[str, object]] = []
    for claim in claims:
        overlaps = overlapping_scopes(scope, claim.scope)
        if not overlaps:
            continue
        affected.append(
            {
                "kind": "claim",
                "id": claim.id,
                "agent_id": claim.agent_id,
                "description": claim.description,
                "scope": claim.scope,
                "overlap_scope": overlaps,
            }
        )
    return tuple(affected)


def _affected_intent_payloads(
    scope: tuple[str, ...],
    *,
    intents: tuple[IntentRecord, ...],
) -> tuple[dict[str, object], ...]:
    affected: list[dict[str, object]] = []
    for intent in intents:
        overlaps = overlapping_scopes(scope, intent.scope)
        if not overlaps:
            continue
        affected.append(
            {
                "kind": "intent",
                "id": intent.id,
                "agent_id": intent.agent_id,
                "description": intent.description,
                "reason": intent.reason,
                "scope": intent.scope,
                "overlap_scope": overlaps,
            }
        )
    return tuple(affected)


def _validated_repo_relative_path(repo_root: Path, raw_path: str) -> str:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise LoomAuthorityError(
            f"Invalid authority declaration in {AUTHORITY_CONFIG_FILENAME}: path '{raw_path}' must stay inside the repo."
        )
    resolved = (repo_root / candidate).resolve()
    try:
        relative = resolved.relative_to(repo_root.resolve())
    except ValueError as error:
        raise LoomAuthorityError(
            f"Invalid authority declaration in {AUTHORITY_CONFIG_FILENAME}: path '{raw_path}' must stay inside the repo."
        ) from error
    return relative.as_posix()


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LoomAuthorityError(
            f"Invalid authority declaration in {AUTHORITY_CONFIG_FILENAME}: surface field '{key}' must be a non-empty string."
        )
    return value.strip()


def _optional_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise LoomAuthorityError(
            f"Invalid authority declaration in {AUTHORITY_CONFIG_FILENAME}: surface field '{key}' must be a string."
        )
    stripped = value.strip()
    return stripped or None


def _optional_string_tuple(payload: dict[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise LoomAuthorityError(
            f"Invalid authority declaration in {AUTHORITY_CONFIG_FILENAME}: surface field '{key}' must be a list of non-empty strings."
        )
    return tuple(item.strip() for item in value)


def _optional_repo_relative_path_tuple(
    repo_root: Path,
    payload: dict[str, object],
    key: str,
) -> tuple[str, ...]:
    value = payload.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise LoomAuthorityError(
            f"Invalid authority declaration in {AUTHORITY_CONFIG_FILENAME}: surface field '{key}' must be a list of non-empty repo-relative paths."
        )
    normalized_paths: list[str] = []
    for raw_path in value:
        normalized = _validated_repo_relative_path(repo_root, raw_path)
        if not (repo_root / normalized).exists():
            raise LoomAuthorityError(
                f"Invalid authority declaration in {AUTHORITY_CONFIG_FILENAME}: scope hint '{normalized}' is missing."
            )
        normalized_paths.append(normalized)
    return tuple(normalized_paths)


def _parse_minimal_authority_yaml(text: str) -> dict[str, object]:
    lines = list(_prepared_lines(text))
    if not lines:
        raise ValueError("file is empty")
    index = 0

    version, index = _parse_top_level_scalar(lines, index, key="version")
    authority_value, index = _parse_top_level_mapping_key(lines, index, key="authority")
    if authority_value is not None:
        raise ValueError("authority must be a mapping")
    surfaces, index = _parse_authority_mapping(lines, index)
    if index != len(lines):
        line_number, _, content = lines[index]
        raise ValueError(f"unexpected content on line {line_number}: {content}")
    return {
        "version": version,
        "authority": {
            "surfaces": surfaces,
        },
    }


def _parse_top_level_scalar(
    lines: list[tuple[int, int, str]],
    index: int,
    *,
    key: str,
) -> tuple[int, int]:
    if index >= len(lines):
        raise ValueError(f"missing top-level '{key}'")
    line_number, indent, content = lines[index]
    if indent != 0:
        raise ValueError(f"line {line_number} must start at top level")
    parsed_key, raw_value = _split_key_value(content, line_number)
    if parsed_key != key:
        raise ValueError(f"expected '{key}' on line {line_number}")
    if raw_value is None:
        raise ValueError(f"'{key}' on line {line_number} must have a value")
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"'{key}' on line {line_number} must be an integer") from error
    return value, index + 1


def _parse_top_level_mapping_key(
    lines: list[tuple[int, int, str]],
    index: int,
    *,
    key: str,
) -> tuple[str | None, int]:
    if index >= len(lines):
        raise ValueError(f"missing top-level '{key}'")
    line_number, indent, content = lines[index]
    if indent != 0:
        raise ValueError(f"line {line_number} must start at top level")
    parsed_key, raw_value = _split_key_value(content, line_number)
    if parsed_key != key:
        raise ValueError(f"expected '{key}' on line {line_number}")
    return raw_value, index + 1


def _parse_authority_mapping(
    lines: list[tuple[int, int, str]],
    index: int,
) -> tuple[list[dict[str, object]], int]:
    if index >= len(lines):
        raise ValueError("authority.surfaces is required")
    line_number, indent, content = lines[index]
    if indent != 2:
        raise ValueError(f"authority child on line {line_number} must be indented by two spaces")
    key, raw_value = _split_key_value(content, line_number)
    if key != "surfaces":
        raise ValueError(f"expected 'surfaces' inside authority on line {line_number}")
    if raw_value is not None:
        raise ValueError("authority.surfaces must be a list")
    return _parse_surfaces(lines, index + 1)


def _parse_surfaces(
    lines: list[tuple[int, int, str]],
    index: int,
) -> tuple[list[dict[str, object]], int]:
    surfaces: list[dict[str, object]] = []
    while index < len(lines):
        line_number, indent, content = lines[index]
        if indent < 4:
            break
        if indent != 4:
            raise ValueError(f"surface entry on line {line_number} must be indented by four spaces")
        if not content.startswith("- "):
            raise ValueError(f"expected list item for authority surface on line {line_number}")
        item_content = content[2:].strip()
        if not item_content:
            raise ValueError(f"surface entry on line {line_number} is empty")
        surface: dict[str, object] = {}
        item_key, item_value = _split_key_value(item_content, line_number)
        if item_value is None:
            raise ValueError(f"surface entry on line {line_number} must start with a key/value pair")
        surface[item_key] = _parse_scalar(item_value)
        index += 1
        while index < len(lines):
            child_line_number, child_indent, child_content = lines[index]
            if child_indent <= 4:
                break
            if child_indent != 6:
                raise ValueError(f"surface field on line {child_line_number} must be indented by six spaces")
            child_key, child_value = _split_key_value(child_content, child_line_number)
            if child_value is None:
                if child_key not in {"topics", "scope_hints"}:
                    raise ValueError(f"surface field '{child_key}' on line {child_line_number} must have a value")
                values, index = _parse_string_list(
                    lines,
                    index + 1,
                    expected_indent=8,
                    key=child_key,
                )
                surface[child_key] = values
                continue
            surface[child_key] = _parse_scalar(child_value)
            index += 1
        surfaces.append(surface)
    if not surfaces:
        raise ValueError("authority.surfaces must contain at least one surface")
    return surfaces, index


def _parse_string_list(
    lines: list[tuple[int, int, str]],
    index: int,
    *,
    expected_indent: int,
    key: str,
) -> tuple[list[str], int]:
    values: list[str] = []
    while index < len(lines):
        line_number, indent, content = lines[index]
        if indent < expected_indent:
            break
        if indent != expected_indent or not content.startswith("- "):
            raise ValueError(f"{key} entry on line {line_number} must be a list item indented by {expected_indent} spaces")
        value = content[2:].strip()
        if not value:
            raise ValueError(f"{key} entry on line {line_number} cannot be empty")
        values.append(_parse_scalar(value))
        index += 1
    if not values:
        raise ValueError(f"{key} must contain at least one list item")
    return values, index


def _prepared_lines(text: str):
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if raw_line[:indent].replace(" ", ""):
            raise ValueError(f"tabs are not supported on line {line_number}")
        yield line_number, indent, stripped


def _split_key_value(content: str, line_number: int) -> tuple[str, str | None]:
    if ":" not in content:
        raise ValueError(f"expected key/value content on line {line_number}")
    key, value = content.split(":", 1)
    key = key.strip()
    if not key:
        raise ValueError(f"missing key on line {line_number}")
    value = value.strip()
    return key, value or None


def _parse_scalar(value: str) -> str:
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value
