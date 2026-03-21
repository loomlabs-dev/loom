from __future__ import annotations

from typing import Any

from .mcp_support import prompt_message as _prompt_message


class PromptExecutionError(RuntimeError):
    pass


class PromptArgument:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        required: bool,
    ) -> None:
        self.name = name
        self.description = description
        self.required = required

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required,
        }


class Prompt:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        arguments: tuple[PromptArgument, ...],
        handler: Any,
    ) -> None:
        self.name = name
        self.description = description
        self.arguments = arguments
        self.handler = handler

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": [argument.describe() for argument in self.arguments],
        }


def build_prompts() -> dict[str, Prompt]:
    return {
        "coordinate_before_edit": Prompt(
            name="coordinate_before_edit",
            description="Guide an agent through Loom coordination before editing code.",
            arguments=(
                PromptArgument(
                    name="task",
                    description="The work the agent is about to do.",
                    required=True,
                ),
                PromptArgument(
                    name="scope",
                    description="Optional repo-relative path or scope hint.",
                    required=False,
                ),
                PromptArgument(
                    name="agent_id",
                    description="Optional Loom agent identity to act as.",
                    required=False,
                ),
            ),
            handler=_prompt_coordinate_before_edit,
        ),
        "triage_inbox": Prompt(
            name="triage_inbox",
            description="Guide an agent through checking and reacting to its Loom inbox.",
            arguments=(
                PromptArgument(
                    name="agent_id",
                    description="Optional Loom agent identity to focus the inbox review on.",
                    required=False,
                ),
            ),
            handler=_prompt_triage_inbox,
        ),
        "resolve_conflict": Prompt(
            name="resolve_conflict",
            description="Guide an agent through inspecting and resolving one Loom conflict.",
            arguments=(
                PromptArgument(
                    name="conflict_id",
                    description="The Loom conflict id to inspect and resolve.",
                    required=True,
                ),
            ),
            handler=_prompt_resolve_conflict,
        ),
        "adapt_or_wait": Prompt(
            name="adapt_or_wait",
            description="Guide an agent through deciding whether to adapt, wait, or resolve around a Loom conflict.",
            arguments=(
                PromptArgument(
                    name="conflict_id",
                    description="The Loom conflict id that triggered the decision.",
                    required=True,
                ),
                PromptArgument(
                    name="agent_id",
                    description="Optional Loom agent identity to evaluate the conflict as.",
                    required=False,
                ),
            ),
            handler=_prompt_adapt_or_wait,
        ),
        "finish_and_release": Prompt(
            name="finish_and_release",
            description="Guide an agent through wrapping up Loom work and releasing its claim.",
            arguments=(
                PromptArgument(
                    name="agent_id",
                    description="Optional Loom agent identity to finish work as.",
                    required=False,
                ),
                PromptArgument(
                    name="summary",
                    description="Optional summary of what was completed.",
                    required=False,
                ),
            ),
            handler=_prompt_finish_and_release,
        ),
        "handoff_work": Prompt(
            name="handoff_work",
            description="Guide an agent through handing work or context to another agent with Loom.",
            arguments=(
                PromptArgument(
                    name="task",
                    description="The work being handed off.",
                    required=True,
                ),
                PromptArgument(
                    name="scope",
                    description="Optional repo-relative path or scope hint for the handoff.",
                    required=False,
                ),
                PromptArgument(
                    name="recipient_agent",
                    description="Optional agent expected to pick up the work next.",
                    required=False,
                ),
            ),
            handler=_prompt_handoff_work,
        ),
    }


def _required_string(arguments: dict[str, object], field: str) -> str:
    value = arguments.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PromptExecutionError(f"{field} must be a non-empty string.")
    return value.strip()


def _optional_string(arguments: dict[str, object], field: str) -> str | None:
    value = arguments.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise PromptExecutionError(f"{field} must be a string when provided.")
    stripped = value.strip()
    return stripped or None


def _reject_extra_arguments(arguments: dict[str, object], allowed: tuple[str, ...]) -> None:
    extras = sorted(set(arguments) - set(allowed))
    if extras:
        raise PromptExecutionError(f"Unexpected arguments: {', '.join(extras)}.")


def _prompt_coordinate_before_edit(
    arguments: dict[str, object],
    context: dict[str, object] | None = None,
) -> dict[str, object]:
    _reject_extra_arguments(arguments, ("task", "scope", "agent_id"))
    task = _required_string(arguments, "task")
    scope = _optional_string(arguments, "scope")
    agent_id = _optional_string(arguments, "agent_id")
    lines = [
        "Do not analyze Loom itself. Use it only for coordination in this repository.",
        "Minimal loop: start, do the returned next_action, edit, finish.",
        "Command meanings:",
        "- `loom://start` or `loom_start`: read the board and follow Loom's best next move first.",
        "- `loom_bind`: pin this MCP session to a stable Loom agent identity when Loom still sees a raw terminal.",
        "- `loom_claim`: reserve the work before edits.",
        "- `loom_intent`: narrow to the exact scope only when the edit gets specific.",
        "- `loom_inbox`: react to context or conflicts before continuing.",
        "- `loom_finish`: release work cleanly when you are done for now.",
        f"Task: {task}",
    ]
    lines.extend(_prompt_authority_lines(context))
    if agent_id:
        lines.append(f"Act as Loom agent: {agent_id}.")
    if scope:
        lines.append(f"Scope hint: {scope}")
    lines.extend(
        [
            "1. Read `loom://start` first when resources are available, or call `loom_start` otherwise.",
            "2. Execute the `next_action` from `loom://start` or `loom_start` before doing anything else.",
            "3. Re-run `loom://start` or `loom_start` after each coordination write until you have claimed work and are ready to edit.",
            "4. If Loom is not initialized yet, call `loom_init`.",
            "5. If Loom still reports a raw terminal identity, call `loom_bind` with your chosen agent name.",
            "6. If you are taking this work, call `loom_claim` for the task.",
            "7. Add `loom_intent` only when you are actually ready to edit a specific scope.",
            "8. If Loom shows conflicts or pending context for your scope, inspect those before editing.",
            "9. When you learn something another agent needs, call `loom_context_write`.",
            "10. If another agent's context changes your plan, call `loom_context_ack` with `read` or `adapted`.",
            "11. Use `loom_finish` when you are done for now. Call `loom_protocol` only if you are blocked on the available operations.",
        ]
    )
    return {"messages": [_prompt_message("\n".join(lines))]}


def _prompt_triage_inbox(
    arguments: dict[str, object],
    context: dict[str, object] | None = None,
) -> dict[str, object]:
    _reject_extra_arguments(arguments, ("agent_id",))
    agent_id = _optional_string(arguments, "agent_id")
    lines = [
        "Use Loom to triage coordination work before you continue coding.",
    ]
    lines.extend(_prompt_authority_lines(context))
    if agent_id:
        lines.append(f"Focus on Loom agent: {agent_id}.")
    lines.extend(
        [
            "1. Read `loom://start` first when resources are available, or call `loom_start` otherwise.",
            "2. Then read `loom://inbox` or call `loom_inbox` to inspect the concrete pending work.",
            "3. For each pending context note, decide whether it is only read or whether it changes your work.",
            "4. Call `loom_context_ack` with `read` or `adapted` for each relevant note.",
            "5. For each active conflict, inspect `loom_timeline` or `loom_conflicts` to understand the dependency.",
            "6. If the conflict is handled, call `loom_resolve` with a concise note.",
            "7. End with a short summary of what changed in your plan.",
        ]
    )
    return {"messages": [_prompt_message("\n".join(lines))]}


def _prompt_resolve_conflict(
    arguments: dict[str, object],
    context: dict[str, object] | None = None,
) -> dict[str, object]:
    _reject_extra_arguments(arguments, ("conflict_id",))
    conflict_id = _required_string(arguments, "conflict_id")
    lines = [
        "Use Loom to inspect and resolve a coordination conflict.",
        f"Conflict id: {conflict_id}",
        *_prompt_authority_lines(context),
        "1. Read `loom://start` first when resources are available, or call `loom_start` otherwise.",
        "2. Call `loom_timeline` for the conflict id to understand the full history.",
        "3. Call `loom_status` or `loom_agents` if you need surrounding repo context.",
        "4. Decide whether you need to adapt your own work, wait, or communicate new context.",
        "5. If the situation is understood and handled, call `loom_resolve` with a concrete note.",
        "6. If the resolution changes another agent's work, publish that with `loom_context_write`.",
    ]
    return {"messages": [_prompt_message("\n".join(lines))]}


def _prompt_finish_and_release(
    arguments: dict[str, object],
    context: dict[str, object] | None = None,
) -> dict[str, object]:
    _reject_extra_arguments(arguments, ("agent_id", "summary"))
    agent_id = _optional_string(arguments, "agent_id")
    summary = _optional_string(arguments, "summary")
    lines = [
        "Use Loom to finish your work cleanly before you step away.",
    ]
    lines.extend(_prompt_authority_lines(context))
    if agent_id:
        lines.append(f"Act as Loom agent: {agent_id}.")
    if summary:
        lines.append(f"Completion summary: {summary}")
    lines.extend(
        [
            "1. Read `loom://start` first when resources are available, or call `loom_start` otherwise.",
            "2. Then read `loom://agent` and `loom://inbox`, or call `loom_agent` and `loom_inbox`, to confirm no coordination work still needs your reaction.",
            "3. If you learned something another agent needs, publish it with `loom_context_write` before you leave.",
            "4. If another agent's context changed your work, acknowledge that with `loom_context_ack` using `read` or `adapted`.",
            "5. If you resolved a conflict during the work, record that with `loom_resolve` and a concise note.",
            "6. When the claimed work is genuinely done or handed off, call `loom_unclaim`.",
            "7. End with a short summary of what was completed, what remains, and any context you published.",
        ]
    )
    return {"messages": [_prompt_message("\n".join(lines))]}


def _prompt_adapt_or_wait(
    arguments: dict[str, object],
    context: dict[str, object] | None = None,
) -> dict[str, object]:
    _reject_extra_arguments(arguments, ("conflict_id", "agent_id"))
    conflict_id = _required_string(arguments, "conflict_id")
    agent_id = _optional_string(arguments, "agent_id")
    lines = [
        "Use Loom to decide whether to adapt your work, wait, or resolve around a conflict.",
        f"Conflict id: {conflict_id}",
    ]
    lines.extend(_prompt_authority_lines(context))
    if agent_id:
        lines.append(f"Evaluate as Loom agent: {agent_id}.")
    lines.extend(
        [
            "1. Read `loom://start` first when resources are available, or call `loom_start` otherwise.",
            "2. Then read `loom://conflicts`, `loom://agent`, and `loom://inbox`, or call `loom_conflicts`, `loom_agent`, and `loom_inbox`.",
            "3. Inspect the specific conflict with `loom_timeline` so you understand the related claims, intents, context, and recent events.",
            "4. Adapt now if your current plan can move to a safer scope or sequence without blocking the broader repo.",
            "5. Wait if another agent owns the prerequisite change and your best move is to stop touching the overlapping area for now.",
            "6. If you adapt, record the change in your behavior with `loom_context_ack` or publish new context with `loom_context_write` when another agent needs to know.",
            "7. If the conflict is now understood and handled, call `loom_resolve` with a concrete note that says why you adapted or decided to wait.",
            "8. End with a short explicit decision: adapt now, wait, or resolve and continue.",
        ]
    )
    return {"messages": [_prompt_message("\n".join(lines))]}


def _prompt_handoff_work(
    arguments: dict[str, object],
    context: dict[str, object] | None = None,
) -> dict[str, object]:
    _reject_extra_arguments(arguments, ("task", "scope", "recipient_agent"))
    task = _required_string(arguments, "task")
    scope = _optional_string(arguments, "scope")
    recipient_agent = _optional_string(arguments, "recipient_agent")
    lines = [
        "Use Loom to hand work off cleanly to another agent.",
        f"Task: {task}",
    ]
    lines.extend(_prompt_authority_lines(context))
    if scope:
        lines.append(f"Scope hint: {scope}")
    if recipient_agent:
        lines.append(f"Expected next agent: {recipient_agent}")
    lines.extend(
        [
            "1. Read `loom://start` first when resources are available, or call `loom_start` otherwise.",
            "2. Then read `loom://agent` and `loom://status`, or call `loom_agent` and `loom_status`, for surrounding context.",
            "3. Publish a concise handoff note with `loom_context_write` covering current state, blockers, and the next recommended move.",
            "4. Include the most relevant scope paths in that context note so the right agent sees it in Loom.",
            "5. If the handoff changes another agent's plan, expect them to react through `loom://inbox` or `loom_inbox` and acknowledge with `loom_context_ack`.",
            "6. If you are no longer actively owning the work, call `loom_unclaim` after the context is published.",
            "7. If a conflict is part of the handoff, inspect it with `loom_timeline` or `loom_conflicts` and resolve it if appropriate.",
            "8. End with a short summary of what the next agent should do first.",
        ]
    )
    return {"messages": [_prompt_message("\n".join(lines))]}


def _prompt_authority_lines(context: dict[str, object] | None) -> list[str]:
    if not isinstance(context, dict):
        return []
    start_payload = context.get("start")
    if not isinstance(start_payload, dict):
        return []
    authority = start_payload.get("authority")
    if not isinstance(authority, dict):
        return []

    status = str(authority.get("status", "")).strip()
    lines: list[str] = []
    if status == "invalid":
        lines.append("Declared authority: `loom.yaml` is currently invalid.")
        issues = tuple(authority.get("issues", ()))
        if issues and isinstance(issues[0], dict):
            message = str(issues[0].get("message", "")).strip()
            if message:
                lines.append(f"Authority issue: {message}")
        lines.append(
            "Treat fixing declared repository truth as the first coordination move before other work."
        )
        return lines

    surfaces = tuple(authority.get("surfaces", ()))
    surface_paths = [
        str(surface.get("path", "")).strip()
        for surface in surfaces
        if isinstance(surface, dict) and str(surface.get("path", "")).strip()
    ]
    if surface_paths:
        preview = ", ".join(surface_paths[:4])
        suffix = " ..." if len(surface_paths) > 4 else ""
        lines.append(f"Declared authority surfaces: {preview}{suffix}")

    if status == "valid" and authority.get("declaration_changed"):
        changed_surfaces = tuple(authority.get("changed_surfaces", ()))
        changed_paths = [
            str(surface.get("path", "")).strip()
            for surface in changed_surfaces
            if isinstance(surface, dict) and str(surface.get("path", "")).strip()
        ]
        if changed_paths:
            preview = ", ".join(changed_paths[:4])
            suffix = " ..." if len(changed_paths) > 4 else ""
            lines.append(
                "Declared authority changed recently; treat these surfaces as the first repo truth to coordinate: "
                f"{preview}{suffix}"
            )
    elif status == "valid":
        changed_surfaces = tuple(authority.get("changed_surfaces", ()))
        changed_paths = [
            str(surface.get("path", "")).strip()
            for surface in changed_surfaces
            if isinstance(surface, dict) and str(surface.get("path", "")).strip()
        ]
        if changed_paths:
            preview = ", ".join(changed_paths[:4])
            suffix = " ..." if len(changed_paths) > 4 else ""
            lines.append(
                "Authority surfaces changed recently; treat these surfaces as the first repo truth to coordinate: "
                f"{preview}{suffix}"
            )

    affected_active_work = tuple(authority.get("affected_active_work", ()))
    if affected_active_work:
        previews: list[str] = []
        for item in affected_active_work[:3]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "work")).strip() or "work"
            agent_id = str(item.get("agent_id", "")).strip()
            overlap_scope = [
                str(path).strip()
                for path in item.get("overlap_scope", ())
                if str(path).strip()
            ]
            scope_preview = ", ".join(overlap_scope[:2]) if overlap_scope else ""
            if agent_id and scope_preview:
                previews.append(f"{kind} by {agent_id} on {scope_preview}")
            elif agent_id:
                previews.append(f"{kind} by {agent_id}")
            elif scope_preview:
                previews.append(f"{kind} on {scope_preview}")
        if previews:
            suffix = " ..." if len(affected_active_work) > len(previews) else ""
            lines.append(
                "Active work currently touching authority-affected scope: "
                + "; ".join(previews)
                + suffix
            )
    return lines
