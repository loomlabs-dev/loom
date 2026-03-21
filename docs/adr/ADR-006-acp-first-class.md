# ADR-006: ACP Is A First-Class Product Output

Date: March 14, 2026

Status: Accepted

## Context

Loom can only become infrastructure if its coordination model is legible beyond
its own implementation.

Without a protocol, Loom risks remaining just one more product surface.

## Decision

Loom will define and publish ACP, the Agent Coordination Protocol, as a
first-class artifact early in the product foundation.

The local daemon, CLI, and later server will be treated as ACP
implementations.

## Consequences

- protocol quality becomes part of product quality
- Loom gains a path to ecosystem adoption
- implementation details are less likely to leak into the public surface
- the project can grow toward standard-setting infrastructure instead of
  remaining a closed control plane concept
