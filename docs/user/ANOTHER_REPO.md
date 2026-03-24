# Using Loom In Another Repo

Last updated: March 24, 2026

You do **not** need to install Loom separately in every repository.

Install the `loom` command once on this machine, then initialize Loom inside
each repo where you want coordination state.

## What Is Per-Machine vs Per-Repo

Installed once per machine or environment:

- the `loom` command

Created per repo checkout:

- `.loom/` project state
- claims, intents, context, conflicts, and timelines for that repo

## Option 1: Shared Editable Install

From the Loom checkout:

```bash
cd /path/to/Loom
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip setuptools wheel
python3 -m pip install -e .
```

Then in another repo:

```bash
cd /path/to/other-repo
loom init
loom start --bind agent-a
```

## Option 2: Shared Alias From Source

If you do not want to install the console script yet:

```bash
alias loom='PYTHONPATH=/path/to/Loom/src python3 -m loom'
```

Then in another repo:

```bash
cd /path/to/other-repo
loom init
loom start --bind agent-a
```

## First Run In Another Repo

```bash
cd /path/to/other-repo
loom init
loom start --bind agent-a
loom claim "Describe the work you're starting" --scope path/to/area
```

Start with `loom start --bind agent-a`. Loom now tries to reuse a terminal
identity first and a parent-shell identity second before falling back.

If Loom prints a `Binding note:`, switch that shell to:

```bash
cd /path/to/other-repo
export LOOM_AGENT=agent-a
loom whoami
loom claim "Describe the work you're starting" --scope path/to/area
loom start
```

Prefer `loom start --bind <agent-name>` for the first run. It binds the shell
and immediately returns the best next coordination action in one command. Use
plain `loom start` when the identity is already bound or when you want a
read-first status check without changing identity.

## What `loom init` Does In Each Repo

`loom init` creates repo-local Loom state.

That includes:

- config
- coordination database
- daemon socket/log locations if the daemon is used

Each repo gets its own coordination history.

## Recommended Background Views

When you start using Loom in another repo, keep one of these open:

```bash
loom inbox --follow
loom log --follow
```

If you are observing a repo from a shell that is not bound to an agent, use
explicit `--agent` reads:

```bash
loom agent --agent agent-a
loom inbox --agent agent-b
```

## Multiple Repos On One Machine

This works well:

- one Loom installation
- many repos
- each repo initialized separately

What does **not** happen automatically:

- claims or conflicts do not cross repo boundaries
- one repo's `.loom/` state does not control another repo

Loom is repo-scoped by design.

## Another Device

Today Loom is still primarily local-first and per-checkout.

That means:

- another device can run Loom in another clone of the repo
- but it does not automatically share coordination state with this device yet

Cross-device shared coordination is a later product layer, not the current
default story.

## Good Next Docs

If you want the next practical step after initialization, use:

- [../alpha/QUICKSTART.md](../alpha/QUICKSTART.md)
- [COMMAND_FAQ.md](COMMAND_FAQ.md)
