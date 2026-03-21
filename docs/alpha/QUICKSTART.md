# 2 Agents, 1 Repo, 5 Minutes

Last updated: March 19, 2026

This is the shortest honest path to a real Loom session.

It is not a polished demo. It is the smallest useful coordination loop:

- initialize a repo
- give two agents stable identities
- claim overlapping work
- see the conflict
- resolve it

## Install

From a fresh checkout:

```bash
make bootstrap
source .venv/bin/activate
loom --version
```

If you prefer the explicit commands:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip setuptools wheel
python3 -m pip install -e .
loom --version
```

If you do not want to install the console script yet, use the fallback in
[INSTALL.md](INSTALL.md).

## Terminal 1

If this is a normal terminal with a stable identity:

```bash
loom init --no-daemon
loom start --bind agent-a
loom claim "Refactor auth flow" --scope src/auth
loom start
```

If this is an agent-hosted shell without a stable terminal identity:

```bash
loom init --no-daemon
export LOOM_AGENT=agent-a
loom claim "Refactor auth flow" --scope src/auth
loom start
```

## Terminal 2

If this is a normal terminal with a stable identity:

```bash
loom start --bind agent-b
loom claim "Add rate limiting hook" --scope src/api
loom intent "Touch auth middleware" --reason "Need auth middleware integration"
loom start
```

If this is an agent-hosted shell without a stable terminal identity:

```bash
export LOOM_AGENT=agent-b
loom claim "Add rate limiting hook" --scope src/api
loom intent "Touch auth middleware" --reason "Need auth middleware integration"
loom start
```

## What You Should See

- `loom conflicts` shows a scope-overlap warning between the auth claim and the
  auth-middleware intent
- `loom inbox` for `agent-b` points to the conflict
- `loom status` shows both claims and the active conflict

## Resolve It

From either terminal:

```bash
loom conflicts
loom resolve <conflict_id> --note "Shifted middleware work to avoid auth overlap."
loom status
```

If one agent learned something the other should know first:

```bash
loom context write auth-interface-change "UserSession now requires refresh_token." --scope src/auth --scope src/api
loom context ack <context_id> --status read --note "Saw this; no impact on current work."
```

## Useful Observer Pane

In a third pane, keep the coordination log open:

```bash
loom log --follow
```

## Clean Sign-Off

When the session is done for now, end it truthfully:

```bash
loom inbox
loom finish --note "What changed, what is still open, and what matters next."
loom status
```

When you come back later, recover with:

```bash
loom resume
```

## Success Criteria

This quickstart succeeded if:

- the agents did not silently overlap
- Loom surfaced the conflict before a merge problem
- `start`, `inbox`, and `conflicts` made the next move obvious
- resolving the conflict felt lighter than coordinating manually

If it felt confusing or ceremonial, that is useful product feedback.
