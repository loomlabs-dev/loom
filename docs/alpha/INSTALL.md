# Public Alpha Install

Last updated: March 24, 2026

Loom's current public alpha install path is repo-first.

Today that means:

- clone the repo
- install from the checkout
- verify the CLI locally
- start dogfooding carefully

PyPI packaging can come later. The goal right now is a trustworthy first run,
not broad packaging theater.

## Requirements

- Python 3.11 or newer
- Git
- a writable repo checkout

## Fastest Repo-First Install

If you use `make`, this is the shortest path:

```bash
make bootstrap
source .venv/bin/activate
loom --version
make smoke
```

`make bootstrap` creates `.venv`, upgrades packaging tools, and installs Loom
editable from the current checkout.

## Manual Install

If you prefer the explicit commands:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip setuptools wheel
python3 -m pip install -e .
loom --version
make smoke
```

## No-Install Fallback

If you do not want to install the console script yet, you can still run Loom
directly from the checkout:

```bash
PYTHONPATH=src python3 -m loom --version
PYTHONPATH=src python3 -m loom --help
```

This is slower and less convenient than the editable install, but it is a
useful fallback for quick verification.

## First Commands To Try

Once Loom is installed:

```bash
loom init
loom start --bind agent-a
loom claim "Describe the work you're starting" --scope path/to/area
```

Loom now tries to reuse a terminal identity first and a host-process identity
second before falling back to a raw process id. Start with `loom start --bind`
unless Loom tells you otherwise.

If Loom prints a `Binding note:` after `loom start --bind`, switch that shell
to `LOOM_AGENT` before continuing.

For the shortest real two-agent walkthrough, continue with
[QUICKSTART.md](QUICKSTART.md).

## If `--bind` Prints A Binding Note

Some shell environments still behave like unstable or hosted terminals even on
local machines. Loom now tries a reusable host-process identity before giving
up, and tells you immediately when that still is not enough. If
`loom start --bind <agent-name>` or `loom whoami --bind <agent-name>` prints a
`Binding note:`, switch to `LOOM_AGENT` for that shell right away:

```bash
export LOOM_AGENT=agent-a
loom whoami
```

If `loom whoami` now shows the expected agent id, continue the session with
`LOOM_AGENT` set for that shell.

This is also the right move when a previous `--bind` happened in a different
shell invocation and the current command no longer shares that terminal
identity.

If an older run already left a dead `pid-*` session behind, recover like this:

```bash
loom clean
export LOOM_AGENT=agent-a
loom whoami
```

## Current Packaging Truth

- Python distribution name: `loom-coord`
- installed CLI command: `loom`
- import package: `loom`
- current public alpha path: source checkout / editable install

When PyPI packaging becomes part of the supported public-alpha path, this doc
should be updated in the same change.
