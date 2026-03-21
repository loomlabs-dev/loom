# ADR-001: Git Is The Source Of Truth

Date: March 14, 2026

Status: Accepted

## Context

Loom's first architecture assumed the product would eventually own the code
write path and treat Git as a shadow sync target.

That increased complexity, weakened the adoption story, and put Loom in
competition with infrastructure developers already trust.

## Decision

Git is the authoritative source of truth for code content, history, merges, and
review handoff.

Loom owns coordination metadata and coordination history.

## Consequences

- Loom becomes easier to adopt.
- Loom stays composable with existing developer workflows.
- Any advanced transactional write layer must remain optional.
- Product differentiation must come from coordination, not file custody.
