# Loom Command FAQ

Last updated: March 19, 2026

This page answers the practical question behind every public Loom command:

**when do I use this, and what does it do?**

Most commands also support `--json` for scripts and agent runtimes. The main
read and recovery commands now include a structured `next_action` with a top
recommended command, a short summary, a reason, and a confidence level. When
Loom is yielding leased work because of nearby repo pressure, `next_action`
can also include an `urgency` like `fresh` or `ongoing`.
On the human CLI, `loom start` now also foregrounds that recommendation as a
`Do this first` line before the supporting loop and command guide.
If Loom already saw and resolved the overlap with that nearby work, the reason
text will say the pressure was already acknowledged and is still live.
`loom start` and `loom status` also expose `repo_lanes` so agent hosts can see
when acknowledged migration-style work is already in flight across the repo,
including grouped `lanes` that distinguish one sustained migration lane from
several unrelated ones, plus grouped `programs` that help Loom recognize a
single longer-running migration effort spanning more than one lane.

## Start And Identity

### `loom start`

Use this first when you do not know what Loom wants you to do next in the
current repo.

Typical use:

```bash
loom start
loom start --bind agent-a
```

It tells you whether the repo needs:

- initialization
- a stable identity
- inbox/conflict attention
- a first claim
- attention for changed files that drift outside the current Loom scope
- a likely widened scope when Loom can see the work has moved
- one top recovery action first when you already have active work, using the
  same `Do this first`, `React now`, `Review soon`, and `Scope adoption`
  narrative as `loom resume`
- a clear `loom finish` cue when current work looks settled and there is no
  pending attention or drift
- a clear `loom renew` cue when the current work lease expired but the work is
  still active
- a clear `loom finish` cue when leased background work is configured to
  `yield` and Loom sees directly relevant coordination pressure or sharply
  overlapping nearby work from another agent
- a recent self-handoff from `loom finish --note` when there is no active work
  and Loom thinks resuming that handoff is the best next move

When there is no active work yet, `loom start` also prints the minimal Loom
loop directly: start, follow the returned `next_action`, claim before edits,
intent only when the touched scope is specific, inbox when coordination needs
reaction, and finish when you are done for now.

It also includes a compact command guide so first-run users and agents can see
what `start`, `claim`, `intent`, `inbox`, and `finish` actually mean without
learning the whole system first.

On the plain CLI, `loom start` and `loom whoami --bind` now also say directly
that Loom is already active in the repo and should be used only for
coordination, and explicitly say not to inspect `.loom/`, `.loom-reports/`,
or Loom internals unless the available Loom commands are insufficient for the
task.

If the shell has a stable terminal identity, `loom start --bind <agent-name>`
is now the fastest first-run path: it binds the terminal and immediately
returns the best next coordination action in one command.

The MCP `loom_start` tool and `loom://start` resource now mirror that same
quick loop and command guide, so agent hosts do not have to infer the command
meanings from prompt text alone.

When MCP-hosted agents still resolve to a raw terminal identity, they can now
call `loom_bind` directly instead of depending on a human to run terminal-side
binding commands first.

The MCP `loom_agents` tool and `loom://agents` resource also now mirror the
CLI's active-first posture: idle history is hidden by default unless the host
explicitly asks for it.

If Loom sees dead `pid-*` sessions still holding coordination state, `loom start`
and `loom status` now point directly at `loom clean` instead of leaving that as
generic stale-session cleanup.

### `loom init`

Use this once per repo checkout to create the local Loom project state.

Typical use:

```bash
loom init
```

Useful flags:

- `--no-daemon`: skip best-effort daemon startup
- `--agent <name>`: persist a repo-local default agent

After `loom init`, the usual next move in a stable shell is now:

```bash
loom start --bind agent-a
```

### `loom whoami`

Use this to inspect or set the current Loom identity.

Typical use:

```bash
loom whoami
loom whoami --bind agent-a
```

For first-run work in a stable shell, prefer `loom start --bind agent-a` when
you want Loom to bind the terminal and immediately continue into the action
loop. Use `loom whoami --bind ...` when you want to inspect or set the binding
explicitly before doing anything else.

Useful flags:

- `--set <name>`: persist a repo-local default agent
- `--bind <name>`: bind the current terminal to one agent
- `--unbind`: remove the current terminal binding

When `--bind` is used after this terminal already claimed or intended work
under its raw terminal identity, Loom now adopts that active claim or intent
into the bound agent automatically when it is safe to do so. That keeps the
board from forking into a real agent plus stale `pid-*` work during first-run
or recovery flows.

If you are in an agent-hosted shell without a stable terminal identity, prefer
`LOOM_AGENT` or `--agent` over `--bind`.

On the MCP surface, the equivalent write tool is `loom_bind`.

Example:

```bash
export LOOM_AGENT=agent-a
loom start
```

## Work Ownership

### `loom claim`

Use this when an agent is starting meaningful work and should be visibly
associated with a scope.

Typical use:

```bash
loom claim "Refactor auth flow"
loom claim "Refactor auth flow" --scope src/auth
```

If you omit `--scope`, Loom tries to infer likely scope from the task
description and the repo tree. If several repo areas look equally plausible,
Loom stays unscoped instead of guessing. Repeat `--scope` to add or override
affected paths or namespaces explicitly.

Useful flags:

- `--lease-minutes <n>`: put an explicit lease on the claim for longer-running
  or background work
- `--lease-policy renew|finish|yield`: tell Loom what this leased work should
  default toward when the lease expires; defaults to `renew` when you set a
  lease

### `loom unclaim`

Use this when the active claim is done, abandoned, or no longer truthful.

Typical use:

```bash
loom unclaim
```

Useful flag:

- `--agent <name>`: release another agent's active claim explicitly

### `loom intent`

Use this when an agent is about to touch an area that matters, especially if it
may overlap with another agent's work.

Typical use:

```bash
loom intent "Touch auth middleware"
loom intent "Touch auth middleware" --scope src/auth/middleware
```

Useful flags:

- omit `--scope` to let Loom infer likely scope from the intent description
- `--lease-minutes <n>`: put an explicit lease on the intent for longer-running
  or background work
- `--lease-policy renew|finish|yield`: tell Loom what this leased work should
  default toward when the lease expires; defaults to `renew` when you set a
  lease
- `--reason "<why>"`: explain why the planned impact matters
- `--agent <name>`: declare intent for a specific agent identity

If the inferred match is ambiguous, Loom asks for `--scope` or a more
path-specific description instead of choosing one silently.

Use intent when scope drifts or overlap becomes likely, not as a ritual before
every trivial edit.

### `loom finish`

Use this when an agent is done for now and should sign off truthfully.

Typical use:

```bash
loom finish
loom finish --note "Paused after the auth pass. Middleware follow-up is next."
```

Useful flags:

- `--note "<handoff>"`: publish a session-end context note before Loom clears
  active work
- `--topic <topic>`: override the default handoff topic (`session-handoff`)
- `--scope <path-or-namespace>`: override the inferred handoff scope
- `--agent <name>`: finish another agent explicitly
- `--keep-idle`: keep the finished agent in idle history instead of pruning it

`loom finish` is the clean shutdown path. If there is an active claim or
intent, Loom releases them. If you pass `--note`, Loom records the handoff
before releasing the work. By default it also prunes the finished agent from
idle history so a normal close-out leaves the board cleaner without needing a
follow-up `loom clean`.

### `loom clean`

Use this when Loom's board needs janitorial cleanup rather than a truthful
session handoff.

Typical use:

```bash
loom clean
```

Useful flag:

- `--keep-idle`: keep idle agent history instead of pruning it

`loom clean` closes dead `pid-*` session work without publishing extra handoff
context, then prunes idle agent history by default so the board can return to
zero active and zero idle agents after a messy dogfood or aborted terminal
run.

### `loom renew`

Use this when current work is still active but its claim or intent lease
expired.

Typical use:

```bash
loom renew
loom renew --lease-minutes 120
```

Useful flags:

- `--lease-minutes <n>`: apply a new lease window to the current active work;
  defaults to `60`
- `--agent <name>`: renew another agent explicitly

`loom renew` extends the lease on the current active claim and intent together
when they exist. This keeps long-running or background work truthful without
forcing you to release and recreate the same work record.

If leased work was created with `--lease-policy finish` or
`--lease-policy yield`, Loom will prefer `loom finish` instead of `loom renew`
when that lease expires.

If leased work was created with `--lease-policy yield`, Loom may also prefer
`loom finish` before lease expiry when it sees directly relevant coordination
pressure, nearby overlapping intents, or specifically overlapping active
claims from other agents.

Loom ignores stale nearby pressure here. Old quiet agents or expired nearby
leases should not force live background work to yield by themselves.

Loom can also keep `yield` pressure active for live semantically entangled
work, such as another active claim or intent touching an imported or dependent
surface, even after the first direct conflict has already been acknowledged.
When several nearby live surfaces exist, Loom now ranks semantic entanglement
ahead of simple path proximity so the riskiest nearby reason shows up first.
Fresh nearby pressure is treated as more urgent than older nearby active work,
so Loom can distinguish "stop now" pressure from longer-running nearby work
that is still live but no longer as urgent.

## Repo And Agent Views

### `loom status`

Use this to see the repo-wide coordination picture:

- active claims
- active intents
- recent context
- active conflicts
- changed files outside the current agent's claim / intent scope
- Loom's suggested widened scope for those changed files when it has one
- whether the current agent's active work lease expired and should be renewed
  before continuing
- stale active work that either went quiet too long or is still holding an
  expired lease

Typical use:

```bash
loom status
```

### `loom report`

Use this when you want a self-contained visual snapshot of repo coordination:

- active agents
- scope hotspots
- conflicts
- recent context
- recent events

Typical use:

```bash
loom report
loom report --output .loom-reports/coordination/auth-pass.html
```

Useful flags:

- `--output <path>`: choose where the HTML snapshot is written
- `--agent-limit <n>`
- `--event-limit <n>`

This is a local-first report. It writes a static HTML file you can open
directly from disk. It is a snapshot, not a live dashboard.

Expired leased work is classified into the stale-active bucket in the report so
background or long-running tasks do not keep reading as healthy live activity
after their lease lapsed.

### `loom resume`

Use this when you are coming back to an agent and want the shortest honest
answer to:

- what changed since the last Loom resume checkpoint
- what changed since the current claim / intent started
- what is waiting for me now
- what should I do next

Typical use:

```bash
loom resume
loom resume --agent agent-b
loom resume --no-checkpoint
```

Useful flags:

- `--agent <name>`
- `--limit <n>`
- `--no-checkpoint`: inspect recovery state without advancing the stored
  resume cursor

`loom resume` stores a repo-local per-agent checkpoint by default, so the next
resume call can focus on only the newer relevant events while still showing the
recovery history for the current active work, including exact ack / resolve
commands when something needs attention before you continue, plus an exact
widened-scope `claim` / `intent` command when the current worktree has drifted
outside the active Loom scope. When both context and conflicts are present,
Loom now surfaces the highest-priority action first and labels pending context
as `react now` or `review soon`, with a cleaner recovery flow: `Do this first`,
`React now`, `Review soon`, and `Scope adoption` when needed. When current
work looks settled, Loom also tells you plainly that `loom finish` is the
truthful next step. If you finished a prior session with `loom finish --note`,
`loom resume` can also surface that recent self-handoff and suggest the exact
claim command to pick it back up.

### `loom agents`

Use this to see which agents are active in the repo.

Typical use:

```bash
loom agents
loom agents --all
```

Useful flags:

- `--limit <n>`: cap the number of agents shown
- `--all`: include idle agent history instead of only active / stale-active
  records

By default, `loom agents` now focuses on active coordination. Use `--all` when
you want the longer-lived idle/history view too.

If dead `pid-*` sessions are still on the board, `loom agents` also surfaces
them explicitly and points at `loom clean`.

### `loom agent`

Use this to inspect one agent's coordination state in detail.

It now also shows changed files that have drifted outside that agent's active
claim / intent scope, Loom's suggested widened scope when the worktree clearly
points to one, and the relevant coordination changes that happened since that
active work started, including exact ack / resolve commands when there is
something to react to immediately.

Typical use:

```bash
loom agent --agent agent-a
```

Useful flags:

- `--context-limit <n>`
- `--event-limit <n>`

### `loom inbox`

Use this when you want to know what one agent needs to react to right now.

Typical use:

```bash
loom inbox
loom inbox --agent agent-b
loom inbox --follow
```

Useful flags:

- `--agent <name>`
- `--follow`
- `--context-limit <n>`
- `--event-limit <n>`

## Conflicts And Recovery

### `loom conflicts`

Use this to see open coordination conflicts in the repo.

Typical use:

```bash
loom conflicts
```

Useful flag:

- `--all`: include resolved conflicts too

### `loom resolve`

Use this when a specific conflict is settled and should be marked resolved.

Typical use:

```bash
loom resolve conflict_123 --note "Shifted middleware work away from auth."
```

Useful flag:

- `--agent <name>`

## Event History

### `loom log`

Use this for the repo-wide coordination event stream.

Typical use:

```bash
loom log
loom log --follow
```

Useful flags:

- `--limit <n>`
- `--type <event-type>`
- `--follow`

### `loom timeline`

Use this when you want the coordination history for one specific Loom object:

- claim
- intent
- context
- conflict

Typical use:

```bash
loom timeline claim_123
```

Useful flag:

- `--limit <n>`

## Context

### `loom context write`

Use this when another agent should know something you just learned or decided.

Typical use:

```bash
loom context write auth-interface-change "UserSession now requires refresh_token." --scope src/auth --scope src/api
```

Useful flag:

- `--agent <name>`

### `loom context read`

Use this to read recent shared context, optionally filtered by topic, agent, or
scope.

Typical use:

```bash
loom context read --limit 10
loom context read --scope src/auth
loom context read --follow
```

Useful flags:

- `--topic <topic>`
- `--agent <name>`
- `--scope <path-or-namespace>`
- `--limit <n>`
- `--follow`

### `loom context ack`

Use this after reading a context note to say whether you simply saw it or
actually adapted because of it.

Typical use:

```bash
loom context ack context_123 --status read --note "Saw this; no impact on current work."
loom context ack context_456 --status adapted --note "Shifted plan away from auth."
```

Useful flags:

- `--status read|adapted`
- `--note "<what changed>"`
- `--agent <name>`

## Protocol And MCP

### `loom protocol`

Use this when you want the machine-readable local protocol descriptor.

Typical use:

```bash
loom protocol
loom protocol --json
```

### `loom mcp`

Use this to run Loom as a stdio MCP server for agent hosts.

Typical use:

```bash
loom mcp
```

This is the entrypoint for MCP-capable tools that want Loom tools, resources,
prompts, and subscriptions.

## Daemon

### `loom daemon start`

Use this to start the local Loom daemon explicitly.

Typical use:

```bash
loom daemon start
```

### `loom daemon stop`

Use this to stop the local Loom daemon.

Typical use:

```bash
loom daemon stop
```

### `loom daemon status`

Use this to check whether the local daemon is running and where its socket/logs
live.

Typical use:

```bash
loom daemon status
```

### `loom daemon ping`

Use this as a lightweight connectivity check against the local daemon.

Typical use:

```bash
loom daemon ping
```

## What Most Real Sessions Use

Most Loom sessions revolve around:

1. `loom start`
2. `loom claim`
3. `loom intent`
4. `loom context write`
5. `loom inbox`
6. `loom conflicts`
7. `loom resolve`
8. `loom finish`
9. `loom log --follow`

## Session Shutdown

If you are signing off for the session, the clean Loom sequence is:

```bash
loom inbox
loom finish --note "What changed, what is still open, and what matters next."
loom status
```

Use plain `loom finish` when the work is done and there is nothing worth
handing off. Use `loom finish --note ...` when another agent or future-you
needs the context.

If you want the shortest real loop, start with:

- [../alpha/QUICKSTART.md](../alpha/QUICKSTART.md)
- [../alpha/DOGFOOD_CHECKLIST.md](../alpha/DOGFOOD_CHECKLIST.md)
