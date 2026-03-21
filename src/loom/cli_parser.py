from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from textwrap import dedent
from pathlib import Path

from . import __version__
from .guidance import DEFAULT_RENEW_LEASE_MINUTES
from .util import DEFAULT_LEASE_POLICY, LEASE_POLICIES

AGENT_HELP = (
    "Stable agent name. Defaults to LOOM_AGENT, any current-terminal Loom binding, "
    "the repo default agent, or the current terminal identity."
)

HELP_EPILOG = dedent(
    """
    Start here:
      loom start
      loom init --no-daemon
      loom start --bind agent-a
      loom claim "Describe the work you're starting" --scope path/to/area
      loom status

    Core loop:
      claim    say what you're working on
      intent   say what you're about to touch
      context  share what another agent should know
      finish   sign off truthfully when you are done for now
      inbox    see what needs a reaction
      conflicts see where coordination is colliding
    """
).strip()

Handler = Callable[[argparse.Namespace], int]


def build_parser(*, handlers: Mapping[str, Handler]) -> argparse.ArgumentParser:
    output_parent = argparse.ArgumentParser(add_help=False)
    output_parent.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON.",
    )

    parser = argparse.ArgumentParser(
        prog="loom",
        description="Git-native coordination for multi-agent software work.",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json",
        dest="json_global",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser(
        "init",
        help="Create the local Loom project state in the current Git repo.",
        parents=[output_parent],
    )
    init_parser.add_argument(
        "--no-daemon",
        action="store_true",
        help="Skip the best-effort local daemon startup step.",
    )
    init_parser.add_argument(
        "--agent",
        help="Persist a repo-local default agent for this checkout.",
    )
    init_parser.set_defaults(handler=handlers["init"])

    start_parser = subparsers.add_parser(
        "start",
        help="Show the best next Loom action for this repository.",
        parents=[output_parent],
    )
    start_parser.add_argument(
        "--bind",
        help="Bind the current terminal session to one agent before showing the next Loom action.",
    )
    start_parser.set_defaults(handler=handlers["start"])

    whoami_parser = subparsers.add_parser(
        "whoami",
        help="Show or set the resolved Loom agent identity.",
        parents=[output_parent],
    )
    whoami_parser.add_argument(
        "--set",
        dest="set_agent",
        help="Persist a repo-local default agent for this checkout.",
    )
    whoami_parser.add_argument(
        "--bind",
        help="Bind the current terminal session to one agent in this checkout.",
    )
    whoami_parser.add_argument(
        "--unbind",
        action="store_true",
        help="Remove any current-terminal agent binding for this checkout.",
    )
    whoami_parser.set_defaults(handler=handlers["whoami"])

    claim_parser = subparsers.add_parser(
        "claim",
        help="Claim a unit of work for one agent.",
        parents=[output_parent],
    )
    claim_parser.add_argument("description", help="What the agent is claiming.")
    claim_parser.add_argument(
        "--scope",
        action="append",
        default=[],
        help="Repo-relative path or namespace this work affects. Repeat to add more. If omitted, Loom tries to infer likely scope from the task description.",
    )
    claim_parser.add_argument(
        "--agent",
        help=AGENT_HELP,
    )
    claim_parser.add_argument(
        "--lease-minutes",
        type=int,
        help="Optional positive lease for this claim. Useful for longer-running or background work.",
    )
    claim_parser.add_argument(
        "--lease-policy",
        choices=LEASE_POLICIES,
        help=(
            "How Loom should treat this work when the lease expires. "
            f"Defaults to {DEFAULT_LEASE_POLICY} when a lease is set."
        ),
    )
    claim_parser.set_defaults(handler=handlers["claim"])

    unclaim_parser = subparsers.add_parser(
        "unclaim",
        help="Release the active claim for one agent.",
        parents=[output_parent],
    )
    unclaim_parser.add_argument(
        "--agent",
        help=AGENT_HELP,
    )
    unclaim_parser.set_defaults(handler=handlers["unclaim"])

    intent_parser = subparsers.add_parser(
        "intent",
        help="Declare planned impact for one agent.",
        parents=[output_parent],
    )
    intent_parser.add_argument("description", help="What the agent plans to do.")
    intent_parser.add_argument(
        "--scope",
        action="append",
        default=[],
        help="Repo-relative path or namespace the intent will affect. Repeat to add more. If omitted, Loom tries to infer likely scope from the intent description.",
    )
    intent_parser.add_argument(
        "--reason",
        help="Why this intent matters. Defaults to the description.",
    )
    intent_parser.add_argument(
        "--agent",
        help=AGENT_HELP,
    )
    intent_parser.add_argument(
        "--lease-minutes",
        type=int,
        help="Optional positive lease for this intent. Useful for longer-running or background work.",
    )
    intent_parser.add_argument(
        "--lease-policy",
        choices=LEASE_POLICIES,
        help=(
            "How Loom should treat this work when the lease expires. "
            f"Defaults to {DEFAULT_LEASE_POLICY} when a lease is set."
        ),
    )
    intent_parser.set_defaults(handler=handlers["intent"])

    finish_parser = subparsers.add_parser(
        "finish",
        help="Publish an optional handoff note and clear active work for one agent.",
        parents=[output_parent],
    )
    finish_parser.add_argument(
        "--note",
        help="Optional session-end handoff note to publish before releasing active work.",
    )
    finish_parser.add_argument(
        "--topic",
        default="session-handoff",
        help="Topic to use if --note publishes a handoff context entry.",
    )
    finish_parser.add_argument(
        "--scope",
        action="append",
        default=[],
        help="Optional override scope for the handoff note. Repeat to add more.",
    )
    finish_parser.add_argument(
        "--agent",
        help=AGENT_HELP,
    )
    finish_parser.add_argument(
        "--keep-idle",
        action="store_true",
        help="Keep the finished agent in idle history instead of pruning it.",
    )
    finish_parser.set_defaults(handler=handlers["finish"])

    clean_parser = subparsers.add_parser(
        "clean",
        help="Close dead pid-based sessions and prune idle agent history.",
        parents=[output_parent],
    )
    clean_parser.add_argument(
        "--keep-idle",
        action="store_true",
        help="Keep idle agent history after closing dead pid-based work.",
    )
    clean_parser.set_defaults(handler=handlers["clean"])

    renew_parser = subparsers.add_parser(
        "renew",
        help="Renew the current coordination lease for one agent's active work.",
        parents=[output_parent],
    )
    renew_parser.add_argument(
        "--lease-minutes",
        type=int,
        default=DEFAULT_RENEW_LEASE_MINUTES,
        help=(
            "Positive lease window to apply to the current active work. "
            f"Defaults to {DEFAULT_RENEW_LEASE_MINUTES} minutes."
        ),
    )
    renew_parser.add_argument(
        "--agent",
        help=AGENT_HELP,
    )
    renew_parser.set_defaults(handler=handlers["renew"])

    status_parser = subparsers.add_parser(
        "status",
        help="Show active coordination state for this repository.",
        parents=[output_parent],
    )
    status_parser.set_defaults(handler=handlers["status"])

    report_parser = subparsers.add_parser(
        "report",
        help="Generate a self-contained Loom coordination report for this repository.",
        parents=[output_parent],
    )
    report_parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Where to write the HTML snapshot. Defaults to "
            ".loom-reports/coordination/latest.html under the repo root."
        ),
    )
    report_parser.add_argument(
        "--agent-limit",
        type=int,
        default=20,
        help="Maximum number of agents to include in the report.",
    )
    report_parser.add_argument(
        "--event-limit",
        type=int,
        default=20,
        help="Maximum number of recent events to include in the report.",
    )
    report_parser.set_defaults(handler=handlers["report"])

    resume_parser = subparsers.add_parser(
        "resume",
        help="Show what changed for one agent since the last Loom resume checkpoint.",
        parents=[output_parent],
    )
    resume_parser.add_argument(
        "--agent",
        help=AGENT_HELP,
    )
    resume_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of relevant events to show since the last resume checkpoint.",
    )
    resume_parser.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Show recovery info without advancing the stored resume checkpoint.",
    )
    resume_parser.set_defaults(handler=handlers["resume"])

    agents_parser = subparsers.add_parser(
        "agents",
        help="Show active Loom agents known in this repository.",
        parents=[output_parent],
    )
    agents_parser.add_argument(
        "--all",
        action="store_true",
        help="Include idle agent history, not just active records.",
    )
    agents_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of agents to show.",
    )
    agents_parser.set_defaults(handler=handlers["agents"])

    agent_parser = subparsers.add_parser(
        "agent",
        help="Show the coordination state for one agent.",
        parents=[output_parent],
    )
    agent_parser.add_argument(
        "--agent",
        help=AGENT_HELP,
    )
    agent_parser.add_argument(
        "--context-limit",
        type=int,
        default=5,
        help="Maximum relevant context notes to show.",
    )
    agent_parser.add_argument(
        "--event-limit",
        type=int,
        default=10,
        help="Maximum recent events to show.",
    )
    agent_parser.set_defaults(handler=handlers["agent"])

    inbox_parser = subparsers.add_parser(
        "inbox",
        help="Show pending coordination work for one agent.",
        parents=[output_parent],
    )
    inbox_parser.add_argument(
        "--agent",
        help=AGENT_HELP,
    )
    inbox_parser.add_argument(
        "--context-limit",
        type=int,
        default=5,
        help="Maximum pending context notes to show.",
    )
    inbox_parser.add_argument(
        "--event-limit",
        type=int,
        default=10,
        help="Maximum recent trigger events to show.",
    )
    inbox_parser.add_argument(
        "--follow",
        action="store_true",
        help="Keep streaming inbox updates for this agent.",
    )
    inbox_parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help=argparse.SUPPRESS,
    )
    inbox_parser.add_argument(
        "--max-follow-updates",
        type=int,
        help=argparse.SUPPRESS,
    )
    inbox_parser.set_defaults(handler=handlers["inbox"])

    conflicts_parser = subparsers.add_parser(
        "conflicts",
        help="Show open coordination conflicts for this repository.",
        parents=[output_parent],
    )
    conflicts_parser.add_argument(
        "--all",
        action="store_true",
        help="Include resolved conflicts in the output.",
    )
    conflicts_parser.set_defaults(handler=handlers["conflicts"])

    resolve_parser = subparsers.add_parser(
        "resolve",
        help="Resolve one coordination conflict.",
        parents=[output_parent],
    )
    resolve_parser.add_argument("conflict_id", help="Conflict id to resolve.")
    resolve_parser.add_argument(
        "--note",
        help="Short note about how the conflict was resolved.",
    )
    resolve_parser.add_argument(
        "--agent",
        help=AGENT_HELP,
    )
    resolve_parser.set_defaults(handler=handlers["resolve"])

    log_parser = subparsers.add_parser(
        "log",
        help="Show recent coordination events for this repository.",
        parents=[output_parent],
    )
    log_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of events to show.",
    )
    log_parser.add_argument(
        "--type",
        dest="event_type",
        help="Only show one event type, for example `context.published`.",
    )
    log_parser.add_argument(
        "--follow",
        action="store_true",
        help="Keep streaming new coordination events.",
    )
    log_parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help=argparse.SUPPRESS,
    )
    log_parser.add_argument(
        "--max-follow-events",
        type=int,
        help=argparse.SUPPRESS,
    )
    log_parser.set_defaults(handler=handlers["log"])

    timeline_parser = subparsers.add_parser(
        "timeline",
        help="Show the coordination timeline for one Loom object.",
        parents=[output_parent],
    )
    timeline_parser.add_argument("object_id", help="Claim, intent, context, or conflict id.")
    timeline_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of related events to show.",
    )
    timeline_parser.set_defaults(handler=handlers["timeline"])

    context_parser = subparsers.add_parser(
        "context",
        help="Publish or read shared context for this repository.",
        parents=[output_parent],
    )
    context_subparsers = context_parser.add_subparsers(
        dest="context_command",
        required=True,
    )

    context_write_parser = context_subparsers.add_parser(
        "write",
        help="Publish a structured context note.",
        parents=[output_parent],
    )
    context_write_parser.add_argument("topic", help="Short topic or namespace for the note.")
    context_write_parser.add_argument("body", help="Shared context body.")
    context_write_parser.add_argument(
        "--scope",
        action="append",
        default=[],
        help="Repo-relative path or namespace this context applies to. Repeat to add more.",
    )
    context_write_parser.add_argument(
        "--agent",
        help=AGENT_HELP,
    )
    context_write_parser.set_defaults(handler=handlers["context_write"])

    context_ack_parser = context_subparsers.add_parser(
        "ack",
        help="Acknowledge one shared context note as read or adapted.",
        parents=[output_parent],
    )
    context_ack_parser.add_argument("context_id", help="Context id to acknowledge.")
    context_ack_parser.add_argument(
        "--status",
        choices=("read", "adapted"),
        default="read",
        help="Whether the agent read the context or adapted because of it.",
    )
    context_ack_parser.add_argument(
        "--note",
        help="Short note about what changed after reading the context.",
    )
    context_ack_parser.add_argument(
        "--agent",
        help=AGENT_HELP,
    )
    context_ack_parser.set_defaults(handler=handlers["context_ack"])

    context_read_parser = context_subparsers.add_parser(
        "read",
        help="Read recent shared context.",
        parents=[output_parent],
    )
    context_read_parser.add_argument("--topic", help="Only show one topic.")
    context_read_parser.add_argument("--agent", help="Only show notes from one agent.")
    context_read_parser.add_argument(
        "--scope",
        action="append",
        default=[],
        help="Only show matching scoped or global notes. Repeat to add more filters.",
    )
    context_read_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of context notes to show.",
    )
    context_read_parser.add_argument(
        "--follow",
        action="store_true",
        help="Keep streaming new matching context.",
    )
    context_read_parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help=argparse.SUPPRESS,
    )
    context_read_parser.add_argument(
        "--max-follow-entries",
        type=int,
        help=argparse.SUPPRESS,
    )
    context_read_parser.set_defaults(handler=handlers["context_read"])

    protocol_parser = subparsers.add_parser(
        "protocol",
        help="Describe the local Loom coordination protocol.",
        parents=[output_parent],
    )
    protocol_parser.set_defaults(handler=handlers["protocol"])

    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Run a stdio MCP server for Loom.",
    )
    mcp_parser.set_defaults(handler=handlers["mcp"])

    daemon_parser = subparsers.add_parser(
        "daemon",
        help="Manage the local Loom daemon.",
        parents=[output_parent],
    )
    daemon_subparsers = daemon_parser.add_subparsers(
        dest="daemon_command",
        required=True,
    )

    daemon_start_parser = daemon_subparsers.add_parser(
        "start",
        help="Start the local Loom daemon in the background.",
        parents=[output_parent],
    )
    daemon_start_parser.set_defaults(handler=handlers["daemon_start"])

    daemon_stop_parser = daemon_subparsers.add_parser(
        "stop",
        help="Stop the local Loom daemon.",
        parents=[output_parent],
    )
    daemon_stop_parser.set_defaults(handler=handlers["daemon_stop"])

    daemon_status_parser = daemon_subparsers.add_parser(
        "status",
        help="Show local Loom daemon status.",
        parents=[output_parent],
    )
    daemon_status_parser.set_defaults(handler=handlers["daemon_status"])

    daemon_run_parser = daemon_subparsers.add_parser(
        "run",
        help=argparse.SUPPRESS,
        parents=[output_parent],
    )
    daemon_run_parser.set_defaults(handler=handlers["daemon_run"])

    daemon_ping_parser = daemon_subparsers.add_parser(
        "ping",
        help=argparse.SUPPRESS,
        parents=[output_parent],
    )
    daemon_ping_parser.set_defaults(handler=handlers["daemon_ping"])

    return parser
