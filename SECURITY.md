# Security Policy

## Supported Scope

Security issues in the following active surfaces are in scope:

- the Python source under `src/`
- tests and local tooling that ship with this repo

Historical refs may exist for continuity, but the active security surface is
the code and tooling shipped on the current default branch.

## Reporting A Vulnerability

Do not open a public issue for a suspected security vulnerability.

Preferred reporting path:

1. use GitHub private vulnerability reporting when it is enabled
2. if private reporting is unavailable, use the current direct Loom maintainer
   contact path and clearly mark the report as a security issue

When reporting, include:

- affected surface
- Loom commit or branch
- impact summary
- reproduction steps
- any proof-of-concept artifacts you can safely share

## What To Expect

Valid reports should receive:

- confirmation of receipt
- triage on scope and severity
- follow-up questions when reproduction detail is missing
- a coordinated fix and disclosure path when appropriate

## Out Of Scope

The following are usually not security vulnerabilities by themselves:

- missing product features
- requests for broader hardening not tied to a concrete issue
- local-only development setups already described as non-production
