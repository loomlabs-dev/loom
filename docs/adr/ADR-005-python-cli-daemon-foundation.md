# ADR-005: Python CLI And Daemon Foundation

Date: March 14, 2026

Status: Accepted

## Context

Loom needs a fast path to a working CLI, daemon, local store, and testable
reference implementation.

The team already has Python implementation experience from `v0`.

## Decision

The foundation will be implemented in Python:

- CLI in Python
- local daemon in Python
- SQLite coordination layer in Python
- protocol reference objects in Python

## Consequences

- the team can ship faster
- contributor overhead stays reasonable
- selected logic from `v0` can be re-imported more easily
- future polyglot clients can still sit on top of ACP
