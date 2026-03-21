# Loom Roadmap

Last updated: March 20, 2026

This roadmap describes the build order for the current public alpha:

- core coordination primitives
- local-first CLI / daemon / MCP operation
- lower-friction startup and cleanup
- repeated dogfooding and release hardening

## Current Public Slice

The public alpha is centered on a small, durable loop:

1. start from the right identity
2. claim work
3. declare intent when overlap is likely
4. share context when coordination matters
5. resolve or adapt explicitly
6. finish cleanly

The current product work is about making that loop feel obvious, reliable, and
worth keeping open during real multi-agent repo work.

## Phase 0: Foundation

Status:

- complete

Scope:

- Git-native coordination stance
- local-first default
- three-primitives surface
- Python CLI + daemon base
- ACP draft

Gate:

- the repo tells one coherent story about Loom's coordination product

## Phase 1: Core Local Coordination

Status:

- complete

Scope:

- `loom init`
- `loom start`
- `loom claim`
- `loom intent`
- `loom status`
- `loom conflicts`
- `loom log`
- local daemon
- SQLite coordination store

Gate:

- two agents can coordinate in one repo in under 60 seconds

## Phase 2: Shared Context And Recovery

Status:

- complete

Scope:

- `loom context write|read|ack`
- inbox and agent-centric views
- cleanup and stale-session recovery
- better next-step guidance

Gate:

- one agent can change another agent's behavior without a separate transcript

## Phase 3: Public Alpha Hardening

Status:

- active

Scope:

- `loom start --bind <agent>` as the standard first move
- `loom clean` as the standard board reset path
- CLI / daemon / MCP parity for the core coordination loop
- clearer repo-first installation
- tighter docs and release truth
- benchmark visibility
- real dogfood in real repositories

Gate:

- outside users can install Loom, understand it quickly, and complete a real
  local coordination session without private coaching

## Next Public Work

The next public work is:

1. reduce startup ambiguity even further
2. keep cleanup and dead-session recovery reliable
3. harden daemon and MCP behavior under messier real sessions
4. improve conflict, inbox, and status signal quality
5. pressure-test Loom in outside repos and keep trimming ceremony
