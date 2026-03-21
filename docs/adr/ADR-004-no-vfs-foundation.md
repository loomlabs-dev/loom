# ADR-004: VFS Is Not The Foundation

Date: March 14, 2026

Status: Accepted

## Context

The previous Loom architecture treated file storage, locks, versions, and
transactional writes as foundational product machinery.

That architecture created weight before Loom had secured the adoption wedge.

## Decision

Loom will not rebuild around a VFS-backed write path.

If a transactional write layer ever returns, it will be:

- optional
- off by default
- justified by real high-contention usage

## Consequences

- local mode stays simple
- server mode stays Git-native by default
- Loom must earn advanced write coordination through demand, not theory
- architectural focus returns to coordination instead of storage
