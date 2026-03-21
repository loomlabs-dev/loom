# Loom Governance

This document describes how Loom is run on the current foundation.

## Project Posture

Loom is public, Apache-2.0, and open to external feedback.

Loom is also being developed with deliberate product discipline. That means
maintainers will optimize for:

- product clarity
- local-first usefulness
- protocol legibility
- avoiding accidental reintroduction of `v0` complexity

The public code is open. The Loom name, marks, and official product identity
remain governed separately by [TRADEMARKS.md](TRADEMARKS.md).

## Decision Model

The Loom maintainers make final decisions on:

- product direction
- historical boundaries
- protocol and API compatibility
- public positioning
- security handling

External feedback and targeted patches are welcome. Product coherence still
matters more than accepting every possible contribution.

## What We Value In Contributions

The best contributions make Loom:

- faster to adopt in one repo with two or three agents
- clearer around claim, intent, and context
- easier to build on top of ACP
- more honest in docs and public surfaces

## Contribution Posture

The default posture is:

- issues: yes
- feature requests: yes
- documentation fixes: yes
- targeted bug-fix PRs: yes
- broad rewrites that pull Loom back toward server-first or VFS-first
  complexity: no

For larger changes, open an issue first and explain:

- what problem you are solving
- which current Loom surface it affects
- why it belongs now instead of later

## Review Expectations

Changes should come with:

- a clear summary
- a verification path
- updated docs when product behavior or public positioning changes

If a change touches public positioning, keep these in sync:

- [README.md](README.md)
- [ROADMAP.md](ROADMAP.md)

## Security and Conduct

- Security issues follow [SECURITY.md](SECURITY.md)
- Community expectations follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- General support routing follows [SUPPORT.md](SUPPORT.md)
