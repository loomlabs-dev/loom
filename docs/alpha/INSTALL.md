# Public Alpha Install

Last updated: March 19, 2026

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

For the shortest real two-agent walkthrough, continue with
[QUICKSTART.md](QUICKSTART.md).

## Current Packaging Truth

- Python distribution name: `loom-coord`
- installed CLI command: `loom`
- import package: `loom`
- current public alpha path: source checkout / editable install

When PyPI packaging becomes part of the supported public-alpha path, this doc
should be updated in the same change.
