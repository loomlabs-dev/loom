# Loom Agent Guide

This file is for agent runtimes working inside the Loom repo itself.

## Repo Purpose

Loom is a local-first, Git-native coordination layer for multi-agent software
work.

The public repo is centered on the smallest useful product:

- claim work
- declare intent
- share context

Supporting surfaces exist to make that loop usable:

- `start`
- `status`
- `agents` / `agent`
- `inbox`
- `conflicts` / `resolve`
- `log` / `timeline`
- `clean`
- MCP and daemon support

## Read First

- [README.md](README.md)
- [ROADMAP.md](ROADMAP.md)
- [CHANGELOG.md](CHANGELOG.md)
- [docs/alpha/ALPHA_0_1_CONTRACT.md](docs/alpha/ALPHA_0_1_CONTRACT.md)
- [docs/alpha/QUICKSTART.md](docs/alpha/QUICKSTART.md)
- [docs/user/COMMAND_FAQ.md](docs/user/COMMAND_FAQ.md)
- [ACP_0_1.md](ACP_0_1.md)
- [docs/adr/](docs/adr/)

## Working Rules

- Git owns code.
- Loom owns coordination.
- Prefer small, durable Python decisions.
- Keep the public alpha legible.
- Do not inspect `.loom/` unless Loom's commands are insufficient.

If a change does not strengthen the current coordination product, it is probably
not a public-repo priority.

## Useful Local Commands

```bash
PYTHONPATH=src python3 -m loom start --bind agent-a
PYTHONPATH=src python3 -m loom claim "Tighten MCP alpha surface"
PYTHONPATH=src python3 -m loom inbox --follow
PYTHONPATH=src python3 -m loom status
PYTHONPATH=src python3 -m loom clean
```

## Verification

Run the core verification commands after behavior changes:

```bash
python3 -m unittest discover -s tests -q
python3 -m compileall src examples/two-agent-demo tests
```
