# Agent Coordination Protocol v0.1

Last updated: March 14, 2026

Status: Draft

ACP is Loom's proposed open protocol for coordinating live multi-agent software
work.

ACP is intentionally small.
It should be simple enough for a small client or tool to implement quickly.

## Goals

ACP exists to standardize 5 things:

1. claim work
2. declare intent
3. publish context
4. surface conflicts
5. stream coordination events

## Non-Goals

ACP v0.1 does not standardize:

- file storage
- code review
- Git hosting
- CI execution
- model inference
- editor UX
- agent runtime internals

## Design Principles

### Git-native

ACP coordinates work around a Git repository.
It does not replace Git history or merge semantics.

### Local-first

ACP must work for a local daemon and for a shared server.

### Transport-light

ACP objects should work over:

- local sockets
- stdin/stdout adapters
- HTTP
- WebSocket
- MCP wrappers

### Explainable

Conflict outputs must be inspectable by humans.

## Core Objects

### Agent

Represents a participating actor.

Required fields:

- `id`
- `name`
- `mode`

Example:

```json
{
  "id": "agent-codex-a",
  "name": "Codex A",
  "mode": "local"
}
```

### Claim

Represents ownership of a unit of work.

Required fields:

- `id`
- `agent_id`
- `description`
- `scope`
- `status`
- `created_at`

Example:

```json
{
  "id": "claim_01",
  "agent_id": "agent-codex-a",
  "description": "Refactor auth flow",
  "scope": ["src/auth/**"],
  "status": "active",
  "created_at": "2026-03-14T14:00:00Z"
}
```

### Intent

Represents planned impact.

Required fields:

- `id`
- `agent_id`
- `description`
- `scope`
- `reason`
- `created_at`

Optional fields:

- `related_claim_id`

Example:

```json
{
  "id": "intent_01",
  "agent_id": "agent-codex-a",
  "related_claim_id": "claim_01",
  "description": "Touch auth middleware and token validation",
  "scope": ["src/auth/**", "src/middleware/**"],
  "reason": "Refresh token refactor",
  "created_at": "2026-03-14T14:01:12Z"
}
```

### Context

Represents shared knowledge.

Required fields:

- `id`
- `agent_id`
- `topic`
- `body`
- `created_at`

Optional fields:

- `scope`
- `related_claim_id`
- `related_intent_id`

Example:

```json
{
  "id": "context_01",
  "agent_id": "agent-codex-a",
  "topic": "auth-interface-change",
  "body": "UserSession now requires refresh_token.",
  "scope": ["src/auth/**", "src/api/**"],
  "created_at": "2026-03-14T14:05:30Z"
}
```

### Conflict

Represents a coordination problem Loom detected.

Required fields:

- `id`
- `kind`
- `severity`
- `summary`
- `objects`
- `created_at`

Example:

```json
{
  "id": "conflict_01",
  "kind": "semantic_overlap",
  "severity": "warning",
  "summary": "Auth middleware changes likely intersect active token refactor.",
  "objects": ["claim_01", "intent_02"],
  "created_at": "2026-03-14T14:06:10Z"
}
```

### Event

Represents a protocol-level coordination event.

Required fields:

- `id`
- `type`
- `timestamp`
- `actor_id`
- `payload`

Example:

```json
{
  "id": "event_01",
  "type": "intent.declared",
  "timestamp": "2026-03-14T14:01:12Z",
  "actor_id": "agent-codex-a",
  "payload": {
    "intent_id": "intent_01"
  }
}
```

## Core Operations

ACP v0.1 defines these operations:

### `claim.create`

Input:

- agent
- description
- scope

Output:

- claim
- overlapping claims, if any

### `claim.release`

Input:

- claim id

Output:

- released claim

### `intent.declare`

Input:

- agent
- description
- scope
- reason

Output:

- intent
- detected conflicts

### `context.publish`

Input:

- agent
- topic
- body
- optional scope

Output:

- stored context object

### `status.read`

Output:

- active claims
- active intents
- recent context
- open conflicts

### `events.subscribe`

Output stream:

- claim events
- intent events
- context events
- conflict events

### `protocol.describe`

Output:

- protocol name
- protocol version
- transport/framing details
- supported operations
- supported stream types

## Local Implementation Model

For local mode, ACP runs over a local daemon:

- transport: Unix domain socket or platform equivalent
- store: SQLite
- event stream: daemon fanout

The current Loom reference daemon exposes a concrete local transport:

- protocol name: `loom.local`
- protocol version: `1`
- message encoding: JSON
- framing: one message per newline
- introspection: `ping` and `protocol.describe`

Each request and response carries:

- `protocol`
- `protocol_version`

That makes the local reference transport self-describing enough for another
tool to implement without reading Loom internals.

## Server Implementation Model

For shared mode, ACP runs over a server:

- transport: HTTP + WebSocket
- store: server database
- event stream: WebSocket or server-sent alternative

## Conflict Semantics

ACP v0.1 recognizes 3 conflict classes:

1. `scope_overlap`
2. `semantic_overlap`
3. `contextual_dependency`

The protocol does not require every implementation to detect all 3 perfectly.
It requires the conflict shape to be representable and explainable.

## Minimal Flow

Example:

1. Agent A creates a claim.
2. Agent A declares intent.
3. Agent B creates a claim.
4. Agent B declares intent.
5. Implementation emits a conflict.
6. Agent A publishes context.
7. Agent B reads context and adapts.

That is the smallest useful coordination loop ACP should standardize.

## Why ACP Matters

If Loom wants to become infrastructure, it needs a protocol other tools can
adopt.

ACP is how Loom stops being only a product and starts becoming the coordination
standard for multi-agent software work.
