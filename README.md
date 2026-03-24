# Loom

**Git-native coordination for multi-agent software work.**

Loom is a local-first coordination layer for agents working in the same
repository.

The public alpha focuses on a small, durable coordination loop:

- Git owns code.
- Loom owns live coordination.
- The core product surface is claim, intent, and context.
- The first job is helping two or three agents work safely in one repo.

## What The Public Alpha Includes

- a local CLI for starting, coordinating, and finishing work
- a SQLite-backed coordination store
- a local daemon for faster repo reads and subscriptions
- a stdio MCP bridge for agent runtimes
- machine-readable `--json` output across the CLI surface
- local protocol introspection through `loom protocol`
- a repo-first install path

The public alpha does not try to present Loom as a finished platform. It is a
focused coordination product that is being hardened under real use.

## Fast Start

Install from a checkout:

```bash
make bootstrap
source .venv/bin/activate
loom --help
```

Shortest honest loop:

```bash
loom init
loom start --bind agent-a
loom claim "Describe the work you're starting"
```

`loom start --bind` now tries to reuse a terminal identity first and a
parent-shell identity second before falling back to a raw process id. If Loom
still prints a `Binding note:`, switch that shell to `LOOM_AGENT` and keep
going.

If you are coordinating with multiple agents, the smallest useful habits are:

- claim before meaningful work
- declare intent when overlap looks likely
- publish context when another agent may need it
- acknowledge context if it changed your plan
- clean up stale session state with `loom clean`

## Commands Worth Knowing Early

- `loom start --bind <agent>`: start from the right identity and get the next move
- `loom claim`: declare active work
- `loom intent`: declare likely overlap before edits
- `loom context write|read|ack`: share and react to coordination context
- `loom status`: read repo coordination state
- `loom inbox`: read the current agent's incoming coordination
- `loom agents` / `loom agent`: inspect active work lanes
- `loom clean`: clear dead-session clutter and stale board noise
- `loom mcp`: expose Loom to MCP-capable agent runtimes

## Read Next

- [ROADMAP.md](ROADMAP.md)
- [docs/alpha/INSTALL.md](docs/alpha/INSTALL.md)
- [docs/alpha/QUICKSTART.md](docs/alpha/QUICKSTART.md)
- [docs/alpha/ALPHA_0_1_CONTRACT.md](docs/alpha/ALPHA_0_1_CONTRACT.md)
- [docs/user/COMMAND_FAQ.md](docs/user/COMMAND_FAQ.md)
- [docs/user/ANOTHER_REPO.md](docs/user/ANOTHER_REPO.md)
- [ACP_0_1.md](ACP_0_1.md)
- [docs/adr/](docs/adr/)

## Public Repo Scope

This public repo covers:

- the core coordination product
- the local-first CLI / daemon / MCP path
- the current alpha contract
- the near-term roadmap for hardening the coordination loop

## License And Marks

- code in this repo is licensed under [LICENSE](LICENSE)
- the Loom name, logos, and brand are governed separately by
  [TRADEMARKS.md](TRADEMARKS.md)

## Verification

For the standard local verification path:

```bash
make alpha-check
```

If you do not want to install the console script yet, run Loom directly from
the checkout:

```bash
PYTHONPATH=src python3 -m loom --help
```

The Python distribution name in [pyproject.toml](pyproject.toml) is
`loom-coord`. The installed CLI command remains `loom`, and the import package
remains `loom`.
