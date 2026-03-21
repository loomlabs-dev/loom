from __future__ import annotations


class LoomActionError(ValueError):
    """Raised for actionable Loom command/tool failures with stable semantics."""

    code: str | None = None


class NoActiveClaimError(LoomActionError):
    code = "no_active_claim"

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(f"No active claim for {agent_id}.")


class NoActiveWorkError(LoomActionError):
    code = "no_active_work"

    def __init__(self, agent_id: str, *, detail: str | None = None) -> None:
        self.agent_id = agent_id
        self.detail = detail
        message = f"No active claim or intent for {agent_id}."
        if detail:
            message = f"{message} {detail}"
        super().__init__(message)


class ConflictNotFoundError(LoomActionError):
    code = "conflict_not_found"

    def __init__(self, conflict_id: str) -> None:
        self.conflict_id = conflict_id
        super().__init__(f"Conflict not found: {conflict_id}.")


class ContextNotFoundError(LoomActionError):
    code = "context_not_found"

    def __init__(self, context_id: str) -> None:
        self.context_id = context_id
        super().__init__(f"Context not found: {context_id}.")


class ObjectNotFoundError(LoomActionError):
    code = "object_not_found"

    def __init__(self, object_id: str) -> None:
        self.object_id = object_id
        super().__init__(f"Object not found: {object_id}.")


class WhoamiSelectionError(LoomActionError):
    code = "whoami_selection"

    def __init__(self) -> None:
        super().__init__("Choose only one of --set, --bind, or --unbind.")


_MESSAGE_CODE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("No active claim for ", "no_active_claim"),
    ("No active claim or intent for ", "no_active_work"),
    ("Conflict not found:", "conflict_not_found"),
    ("Context not found:", "context_not_found"),
    ("Object not found:", "object_not_found"),
    ("Unexpected arguments:", "invalid_arguments"),
)


def recoverable_error_code(error: BaseException | str) -> str | None:
    if not isinstance(error, str):
        code = getattr(error, "code", None)
        if isinstance(code, str) and code:
            return code
        message = str(error)
    else:
        message = error

    if "Run `loom init` first" in message or "not initialized" in message:
        return "project_not_initialized"
    if "Choose only one of --set, --bind, or --unbind." in message:
        return "whoami_selection"
    for prefix, code in _MESSAGE_CODE_PATTERNS:
        if message.startswith(prefix):
            return code
    return None
