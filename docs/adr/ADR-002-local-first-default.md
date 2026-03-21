# ADR-002: Local-First Is The Default

Date: March 14, 2026

Status: Accepted

## Context

Loom's previous entry path assumed a server-backed control plane and multiple
operational surfaces before a user could experience product value.

That entry path is too heavy for the first real user.

## Decision

Loom's default mode is local-first:

- one Git repo
- one developer
- two or three agents
- no server required

The first Loom experience must happen through a local daemon and SQLite-backed
coordination state.

## Consequences

- setup cost drops dramatically
- the first proof becomes testable and repeatable
- server mode becomes a scale-up layer, not the product foundation
- every future feature must justify itself against the local-first path
