from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from .dependency_graph import IGNORED_DIRS
from .guidance import worktree_signal as guidance_worktree_signal
from .local_store import ClaimRecord, IntentRecord
from .util import normalize_scope, normalize_scopes

MAX_INFERRED_CLAIM_SCOPES = 3
MAX_SCOPE_INFERENCE_FILES = 5000
MAX_SUGGESTED_DRIFT_SCOPES = 5
_SCOPE_INFERENCE_DIRECTORY_BONUS = 2
_SCOPE_INFERENCE_DEPTH_BONUS_CAP = 3
_SCOPE_INFERENCE_MIN_CONFIDENT_SCORE = 5
_SCOPE_INFERENCE_SELECTION_SCORE_DELTA = 2
_SCOPE_INFERENCE_AMBIGUITY_SCORE_DELTA = 1
_SCOPE_INFERENCE_HIGH_CONFIDENCE_SCORE = 12
_SCOPE_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
WORKTREE_IGNORED_PREFIXES = (".loom", ".loom-reports")
_SCOPE_INFERENCE_STOPWORDS = {
    "a",
    "an",
    "and",
    "area",
    "change",
    "changes",
    "code",
    "describe",
    "do",
    "edit",
    "feature",
    "files",
    "flow",
    "for",
    "from",
    "in",
    "into",
    "make",
    "module",
    "on",
    "part",
    "pass",
    "path",
    "project",
    "repo",
    "scope",
    "task",
    "that",
    "the",
    "this",
    "touch",
    "update",
    "work",
}


def worktree_signal(
    *,
    project_root: Path,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
) -> dict[str, object]:
    return guidance_worktree_signal(
        project_root=project_root,
        claim=claim,
        intent=intent,
    )


def active_scope_for_worktree(
    *,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
) -> tuple[str, ...]:
    scopes: list[str] = []
    if claim is not None:
        claim_scope = getattr(claim, "scope", ())
        if isinstance(claim_scope, (list, tuple)):
            scopes.extend(str(item) for item in claim_scope)
    if intent is not None:
        intent_scope = getattr(intent, "scope", ())
        if isinstance(intent_scope, (list, tuple)):
            scopes.extend(str(item) for item in intent_scope)
    if not scopes:
        return ()
    return normalize_scopes(scopes)


def infer_finish_scope(
    *,
    explicit_scope: list[str],
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
) -> tuple[str, ...]:
    if explicit_scope:
        return normalize_scopes(explicit_scope)
    if intent is not None and intent.scope:
        return intent.scope
    if claim is not None and claim.scope:
        return claim.scope
    return (".",)


def resolve_claim_scope(
    *,
    project_root: Path,
    description: str,
    explicit_scope: list[str],
) -> tuple[tuple[str, ...], dict[str, object]]:
    if explicit_scope:
        normalized_scope = normalize_scopes(explicit_scope)
        return normalized_scope, {
            "mode": "explicit",
            "used": True,
            "scopes": normalized_scope,
            "matched_tokens": (),
            "confidence": "explicit",
            "reason": "Scope provided explicitly.",
        }

    inferred_scope, inference = _infer_claim_scope(
        project_root=project_root,
        description=description,
    )
    if inferred_scope:
        return inferred_scope, inference
    return (), inference


def resolve_intent_scope(
    *,
    project_root: Path,
    description: str,
    explicit_scope: list[str],
) -> tuple[tuple[str, ...], dict[str, object]]:
    if explicit_scope:
        normalized_scope = normalize_scopes(explicit_scope)
        return normalized_scope, {
            "mode": "explicit",
            "used": True,
            "scopes": normalized_scope,
            "matched_tokens": (),
            "confidence": "explicit",
            "reason": "Scope provided explicitly.",
        }

    inferred_scope, inference = _infer_claim_scope(
        project_root=project_root,
        description=description,
    )
    if inferred_scope:
        return inferred_scope, inference
    detail = str(inference.get("reason", "")).strip()
    if detail:
        detail = f" {detail}"
    return (), {
        **inference,
        "reason": (
            "Intent scope could not be inferred confidently. "
            f"Provide --scope or use a more path-specific description.{detail}"
        ),
    }


def _should_ignore_worktree_path(path: str) -> bool:
    return path in WORKTREE_IGNORED_PREFIXES or any(
        path.startswith(f"{prefix}/")
        for prefix in WORKTREE_IGNORED_PREFIXES
    )


def _suggest_scope_update(
    *,
    active_scope: tuple[str, ...],
    drift_paths: tuple[str, ...],
) -> tuple[str, ...]:
    if not drift_paths:
        return ()
    candidates = [
        *active_scope,
        *(_worktree_scope_candidate(path) for path in drift_paths),
    ]
    return _compact_scope_suggestion(candidates)


def _worktree_scope_candidate(path: str) -> str:
    normalized = normalize_scope(path)
    pure_path = PurePosixPath(normalized)
    if pure_path.suffix and str(pure_path.parent) not in ("", "."):
        return str(pure_path.parent)
    return normalized


def _compact_scope_suggestion(scopes: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if not scopes:
        return ()
    normalized = normalize_scopes(scopes)
    selected: list[str] = []
    for candidate in sorted(
        normalized,
        key=lambda item: (len(PurePosixPath(item).parts), item),
    ):
        candidate_parts = PurePosixPath(candidate).parts
        if any(
            _scopes_overlap_for_inference(existing, candidate)
            and len(PurePosixPath(existing).parts) <= len(candidate_parts)
            for existing in selected
        ):
            continue
        selected = [
            existing
            for existing in selected
            if not (
                _scopes_overlap_for_inference(existing, candidate)
                and len(candidate_parts) < len(PurePosixPath(existing).parts)
            )
        ]
        selected.append(candidate)
        if len(selected) >= MAX_SUGGESTED_DRIFT_SCOPES:
            break
    return tuple(selected)


def _infer_claim_scope(
    *,
    project_root: Path,
    description: str,
) -> tuple[tuple[str, ...], dict[str, object]]:
    description_tokens = _tokenize_scope_text(description)
    if not description_tokens:
        return (), {
            "mode": "unscoped",
            "used": False,
            "scopes": (),
            "matched_tokens": (),
            "confidence": "none",
            "reason": "No meaningful task keywords were available for scope inference.",
        }

    candidates = _claim_scope_candidates(project_root)
    ranked = []
    for scope, metadata in candidates.items():
        matched_tokens = _matched_scope_tokens(description_tokens, metadata["tokens"])
        if not matched_tokens:
            continue
        score = sum(min(len(token), 8) for token in matched_tokens)
        if metadata["kind"] == "dir":
            score += _SCOPE_INFERENCE_DIRECTORY_BONUS
        score += min(metadata["depth"], _SCOPE_INFERENCE_DEPTH_BONUS_CAP)
        ranked.append(
            {
                "scope": scope,
                "score": score,
                "matched_tokens": matched_tokens,
                "kind": metadata["kind"],
                "depth": metadata["depth"],
            }
        )

    if not ranked:
        return (), {
            "mode": "unscoped",
            "used": False,
            "scopes": (),
            "matched_tokens": (),
            "confidence": "none",
            "reason": "No confident repo path match was found for this task description.",
        }

    ranked.sort(
        key=lambda item: (
            -int(item["score"]),
            -int(item["kind"] == "dir"),
            -int(item["depth"]),
            str(item["scope"]),
        )
    )
    top_score = int(ranked[0]["score"])
    ambiguous_candidates = _ambiguous_scope_candidates(ranked, top_score=top_score)
    if ambiguous_candidates:
        ambiguous_scopes = tuple(str(candidate["scope"]) for candidate in ambiguous_candidates)
        matched_tokens = tuple(
            sorted(
                {
                    str(token)
                    for candidate in ambiguous_candidates
                    for token in tuple(candidate["matched_tokens"])
                }
            )
        )
        return (), {
            "mode": "unscoped",
            "used": False,
            "scopes": (),
            "matched_tokens": matched_tokens,
            "candidate_scopes": ambiguous_scopes,
            "confidence": "ambiguous",
            "reason": (
                "Multiple plausible repo path matches were found "
                f"({', '.join(ambiguous_scopes)}). Provide --scope or use a more path-specific description."
            ),
        }
    if top_score < _SCOPE_INFERENCE_MIN_CONFIDENT_SCORE:
        return (), {
            "mode": "unscoped",
            "used": False,
            "scopes": (),
            "matched_tokens": tuple(ranked[0]["matched_tokens"]),
            "confidence": "low",
            "reason": "Loom found only a weak repo path match, so the claim stayed unscoped.",
        }

    selected: list[dict[str, object]] = []
    for candidate in ranked:
        candidate_score = int(candidate["score"])
        if candidate_score < max(
            _SCOPE_INFERENCE_MIN_CONFIDENT_SCORE,
            top_score - _SCOPE_INFERENCE_SELECTION_SCORE_DELTA,
        ):
            continue
        if any(
            _scopes_overlap_for_inference(str(candidate["scope"]), str(existing["scope"]))
            for existing in selected
        ):
            continue
        selected.append(candidate)
        if len(selected) >= MAX_INFERRED_CLAIM_SCOPES:
            break

    scopes = tuple(str(candidate["scope"]) for candidate in selected)
    matched_tokens = tuple(
        sorted(
            {
                token
                for candidate in selected
                for token in candidate["matched_tokens"]
            }
        )
    )
    confidence = (
        "high"
        if top_score >= _SCOPE_INFERENCE_HIGH_CONFIDENCE_SCORE or len(matched_tokens) >= 2
        else "medium"
    )
    return scopes, {
        "mode": "inferred",
        "used": True,
        "scopes": scopes,
        "matched_tokens": matched_tokens,
        "confidence": confidence,
        "reason": "Loom inferred scope from the task description and repo paths.",
    }


def _ambiguous_scope_candidates(
    ranked: list[dict[str, object]],
    *,
    top_score: int,
) -> tuple[dict[str, object], ...]:
    if len(ranked) < 2 or top_score < _SCOPE_INFERENCE_MIN_CONFIDENT_SCORE:
        return ()
    threshold = max(
        _SCOPE_INFERENCE_MIN_CONFIDENT_SCORE,
        top_score - _SCOPE_INFERENCE_AMBIGUITY_SCORE_DELTA,
    )
    close = [
        candidate
        for candidate in ranked
        if int(candidate["score"]) >= threshold
    ]
    if len(close) < 2:
        return ()

    disjoint: list[dict[str, object]] = []
    for candidate in close:
        scope = str(candidate["scope"])
        if any(_scopes_overlap_for_inference(scope, str(existing["scope"])) for existing in disjoint):
            continue
        disjoint.append(candidate)
    if len(disjoint) < 2:
        return ()

    token_sets = {
        tuple(sorted(str(token) for token in tuple(candidate["matched_tokens"])))
        for candidate in disjoint
    }
    if len(token_sets) != 1:
        return ()
    only_tokens = next(iter(token_sets))
    if len(only_tokens) != 1:
        return ()
    return tuple(disjoint[:MAX_INFERRED_CLAIM_SCOPES])


def _claim_scope_candidates(project_root: Path) -> dict[str, dict[str, object]]:
    candidates: dict[str, dict[str, object]] = {}
    file_count = 0
    for absolute_path in project_root.rglob("*"):
        if not absolute_path.is_file():
            continue
        relative_path = absolute_path.relative_to(project_root).as_posix()
        if _should_ignore_inference_path(relative_path):
            continue
        file_count += 1
        if file_count > MAX_SCOPE_INFERENCE_FILES:
            break

        _remember_scope_candidate(
            candidates,
            scope=relative_path,
            kind="file",
        )

        stem_scope = _inference_stem_scope(relative_path)
        if stem_scope is not None:
            _remember_scope_candidate(
                candidates,
                scope=stem_scope,
                kind="file",
            )

        parent = PurePosixPath(relative_path).parent
        while str(parent) not in ("", "."):
            _remember_scope_candidate(
                candidates,
                scope=str(parent),
                kind="dir",
            )
            parent = parent.parent
    return candidates


def _remember_scope_candidate(
    candidates: dict[str, dict[str, object]],
    *,
    scope: str,
    kind: str,
) -> None:
    normalized = scope.strip()
    if not normalized or normalized == ".":
        return
    existing = candidates.get(normalized)
    metadata = {
        "tokens": _tokenize_scope_text(normalized),
        "kind": kind,
        "depth": len(PurePosixPath(normalized).parts),
    }
    if existing is None:
        candidates[normalized] = metadata
        return
    if kind == "dir" and existing["kind"] != "dir":
        candidates[normalized] = metadata


def _should_ignore_inference_path(relative_path: str) -> bool:
    parts = PurePosixPath(relative_path).parts
    if any(part in IGNORED_DIRS for part in parts):
        return True
    if any(part.startswith(".") and part not in {".github"} for part in parts):
        return True
    suffix = PurePosixPath(relative_path).suffix.lower()
    return suffix in {
        ".db",
        ".jpeg",
        ".jpg",
        ".lock",
        ".log",
        ".png",
        ".pyc",
        ".sock",
        ".sqlite",
        ".svg",
        ".webp",
    }


def _inference_stem_scope(relative_path: str) -> str | None:
    path = PurePosixPath(relative_path)
    if not path.suffix:
        return None
    stem_path = path.with_suffix("")
    stem_scope = stem_path.as_posix()
    if stem_scope == relative_path:
        return None
    return stem_scope


def _matched_scope_tokens(
    description_tokens: tuple[str, ...],
    candidate_tokens: tuple[str, ...],
) -> tuple[str, ...]:
    matched: list[str] = []
    candidate_set = set(candidate_tokens)
    for token in description_tokens:
        if token in candidate_set:
            matched.append(token)
            continue
        for candidate in candidate_set:
            if len(token) >= 4 and len(candidate) >= 4 and (
                token.startswith(candidate) or candidate.startswith(token)
            ):
                matched.append(token)
                break
    return tuple(dict.fromkeys(matched))


def _scopes_overlap_for_inference(left: str, right: str) -> bool:
    if left == right:
        return True
    left_path = PurePosixPath(left)
    right_path = PurePosixPath(right)
    if left_path.with_suffix("") == right_path.with_suffix(""):
        return True
    left_parts = left_path.parts
    right_parts = right_path.parts
    return (
        left_parts == right_parts[: len(left_parts)]
        or right_parts == left_parts[: len(right_parts)]
    )


def _tokenize_scope_text(text: str) -> tuple[str, ...]:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    tokens: list[str] = []
    for raw_token in _SCOPE_TOKEN_RE.findall(normalized.lower()):
        token = raw_token.strip()
        if len(token) < 3 or token in _SCOPE_INFERENCE_STOPWORDS:
            continue
        singular = token[:-1] if len(token) > 4 and token.endswith("s") else token
        if singular not in tokens:
            tokens.append(singular)
    return tuple(tokens)
