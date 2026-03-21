# Contributing to Loom

Loom is built around a clear local-first foundation.

If you contribute here, keep two things true:

1. Loom gets stronger at local-first coordination.
2. The repo stays aligned with the current product direction.

## Read First

Start with:

- [README.md](README.md)
- [CHANGELOG.md](CHANGELOG.md)
- [docs/alpha/ALPHA_0_1_CONTRACT.md](docs/alpha/ALPHA_0_1_CONTRACT.md)
- [docs/alpha/BENCHMARKING.md](docs/alpha/BENCHMARKING.md)
- [docs/alpha/DOGFOOD_CHECKLIST.md](docs/alpha/DOGFOOD_CHECKLIST.md)
- [ROADMAP.md](ROADMAP.md)
- [ACP_0_1.md](ACP_0_1.md)
- [docs/adr/](docs/adr/)
- [GOVERNANCE.md](GOVERNANCE.md)
- [SECURITY.md](SECURITY.md)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- [SUPPORT.md](SUPPORT.md)

If you truly need older product context, inspect git history rather than
reviving old assumptions in the active repo.

If you change a supported alpha surface, update:

- [CHANGELOG.md](CHANGELOG.md)
- [docs/alpha/ALPHA_0_1_CONTRACT.md](docs/alpha/ALPHA_0_1_CONTRACT.md)

Read the project trademark policy too:

- [TRADEMARKS.md](TRADEMARKS.md)

## What Belongs On The New Mainline

The mainline is for:

- the local daemon foundation
- the SQLite coordination store
- the minimal CLI
- ACP reference objects
- tests and docs that support the current coordination product

Do not reintroduce server-first or VFS-first complexity by default.

## Verification

For an editable local install:

```bash
make bootstrap
source .venv/bin/activate
```

If you prefer the explicit commands, the equivalent sequence is:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip setuptools wheel
python3 -m pip install -e .
```

The test suite currently uses stdlib `unittest`, so no extra test dependency is
required for the core checks below.

Run the Python checks that match the new scaffold:

```bash
make verify
```

If you are not using `make`, the equivalent commands are:

```bash
python3 -m unittest discover -s tests -q
python3 -m compileall src examples/two-agent-demo tests
```

For a quick local smoke check on the module entrypoint:

```bash
make smoke
```

For local performance work before or during dogfooding:

```bash
make bench-quick
```

## Pull Request Expectations

- Keep changes focused.
- Add or update tests for behavior changes.
- Update docs when product direction, CLI behavior, or public positioning changes.
- Prefer real local-first progress over placeholder surface area.
- Keep changes aligned with the current coordination product and roadmap.
- Do not introduce brand, naming, or positioning changes that conflict with
  [TRADEMARKS.md](TRADEMARKS.md) without explicit approval.

## Contribution Boundary

Maintainers may decline contributions that:

- expand the repo into broader strategy or company material
- reintroduce website, marketing, or unrelated brand bundles
- broaden the product surface faster than the current alpha can support
- create confusion about what is official Loom versus a fork or experiment

## Security

If you discover a security issue, do not open a public bug. Follow
[SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions will be licensed under the
Apache License 2.0 in [LICENSE](LICENSE).

That does not grant trademark rights. The Loom name, logos, and official brand
remain governed by [TRADEMARKS.md](TRADEMARKS.md).
