# Alpha 0.1 Contract

Last updated: March 20, 2026

This document defines the intended support surface for `0.1.0a0`.

The goal is not to promise long-term immutability. The goal is to make the
current alpha honest: outside users, agents, and contributors should know which
surfaces Loom now treats as real enough to dogfood carefully.

This contract covers the current public-alpha product only.
It does not promise broader product layers beyond today's built surface.

## Version

- Python distribution: `loom-coord`
- CLI command: `loom`
- import package: `loom`
- current alpha version: `0.1.0a0`

## Supported Alpha Surfaces

### CLI Commands

These commands are part of the intended alpha product:

- `loom start`
- `loom init`
- `loom whoami`
- `loom claim`
- `loom unclaim`
- `loom intent`
- `loom renew`
- `loom finish`
- `loom clean`
- `loom context write`
- `loom context read`
- `loom context ack`
- `loom status`
- `loom report`
- `loom resume`
- `loom agents`
- `loom agent`
- `loom inbox`
- `loom conflicts`
- `loom resolve`
- `loom log`
- `loom timeline`
- `loom protocol`
- `loom mcp`

### CLI JSON

The JSON surface is part of the alpha contract.

Within `0.1.x` alpha hardening, prefer additive changes over breaking ones.

Intended stable concepts:

- top-level typed records and snapshots
- ids such as `claim_*`, `intent_*`, `context_*`, and `conflict_*`
- `next_steps` guidance arrays
- identity / daemon / MCP diagnostic blocks where already present
- authority-summary and authority-recovery blocks where `loom start` or
  `loom status` already surface committed `loom.yaml` state

Not treated as a compatibility surface:

- exact human-readable CLI text
- the ordering of prose sections in non-JSON output

### MCP

The MCP surface is part of the alpha contract.

Supported tool families:

- repo setup and orientation
- identity binding and agent resolution
- status / agents / inbox / conflicts / log / timeline reads
- claim / finish / cleanup / renew / intent / context / acknowledgment / resolve writes
- protocol introspection
- authority-aware start/status guidance where committed `loom.yaml`
  declarations are already surfaced

Supported MCP capabilities:

- tools
- resources
- prompts
- resource subscriptions

Supported resource families:

- repo views such as `loom://start`, `loom://status`, `loom://log`,
  `loom://context`, `loom://agents`, `loom://conflicts`, and `loom://mcp`
- current-agent views such as `loom://agent`, `loom://inbox`, and
  `loom://activity`
- exact-object and timeline resources for claims, intents, context, conflicts,
  and events
- cursor-style event feeds

Alpha expectation:

- tool and resource names should not churn casually
- response objects should evolve additively whenever possible
- prompts may keep improving, but should continue to point to the same core
  coordination loop

### Declared Authority

The first declared-authority seam is part of the alpha contract where already
surfaced by the product.

Supported alpha behavior:

- committed `loom.yaml` declarations are validated by `loom start`,
  `loom status`, `loom_start`, `loom_status`, `loom://start`, and
  `loom://status`
- invalid declarations surface stable authority-recovery behavior instead of
  being silently ignored
- declaration-only changes can steer focus toward declared authority surfaces
  and mapped `scope_hints` where those are already exposed

Not yet treated as a frozen compatibility promise:

- the full future declaration schema beyond the current minimal model
- broader truth-recomputation consequences beyond today's summary and focus
  steering surfaces

### Local Protocol

The local daemon protocol is part of the alpha contract:

- protocol name: `loom.local`
- protocol version: `v1`
- discoverable through `loom protocol` and MCP/resource introspection

The protocol descriptor is the source of truth for operation names and schemas.

## What Is Still Explicitly Unfrozen

These areas are still expected to evolve during alpha:

- prompt wording and onboarding copy
- exact help text and other human-readable CLI prose
- install/bootstrap instructions
- the minimal `loom.yaml` declaration schema beyond the currently shipped seam
- broader authority-driven consequences beyond today's built surface
- daemon retry tuning and observability detail
- analyzer breadth beyond Python and JavaScript/TypeScript
- future shared-server and cloud layers

## Compatibility Rule For Alpha Work

If a change breaks one of the supported alpha surfaces above:

1. update this contract
2. update [../../CHANGELOG.md](../../CHANGELOG.md)
3. update any affected docs or tests in the same change

Alpha does not mean “no breaking changes.” It does mean “no silent breaking
changes.”
