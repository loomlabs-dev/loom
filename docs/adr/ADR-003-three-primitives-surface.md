# ADR-003: The User-Facing Surface Is Three Primitives

Date: March 14, 2026

Status: Accepted

## Context

Loom accumulated a broad set of nouns and operations:

- assignments
- queue entries
- intents
- locks
- fenced writes
- directives
- plans
- escalations

That breadth made the product difficult to learn and explain.

## Decision

Loom's visible surface is reduced to 3 user-facing primitives:

1. claim work
2. declare intent
3. share context

Other concepts may still exist internally, but they must map cleanly under
those 3 verbs.

## Consequences

- the CLI becomes easier to learn
- the protocol becomes easier to standardize
- server depth remains possible without becoming the first thing users see
- any new feature must declare which primitive it strengthens
