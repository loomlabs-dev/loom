# Dogfood Checklist

Last updated: March 20, 2026

Use this checklist for real Loom sessions in real repositories.

Evaluate the current public alpha honestly:

- Git-native coordination for multi-agent software work
- whether `loom start` gets you moving quickly
- whether claim, intent, and context make real work lighter and safer
- whether `loom clean` and recovery behavior keep the board usable

## Before You Start

- install Loom or run it from a checkout
- pick a real repo and a real task with plausible overlap
- choose stable agent identities for each terminal or runtime
- in stable shells, prefer `loom start --bind <agent-name>`
- in agent-hosted shells without a stable terminal identity, prefer
  `LOOM_AGENT` or `--agent`

Recommended background views:

- `loom inbox --follow`
- `loom log --follow`

## Minimum Habits To Test

- claim before meaningful work
- declare intent when overlap is likely
- publish context when another agent may need it
- acknowledge context if it changed your plan
- resolve conflicts explicitly when coordination is settled

If Loom only works when you remember a much larger ritual, that is a product
problem.

## Questions To Answer

Cold start:

- did `loom start` tell you what to do next without extra docs?
- did identity binding feel obvious?

Core loop:

- did `claim` feel natural or like ceremony?
- did `intent` show up only when it mattered?
- did `context write` feel useful?
- did `inbox` become the place you checked when unsure?

Signal quality:

- were conflicts surfaced early enough to change behavior?
- did `next_steps` help when the session got messy?
- did cleanup and stale-session recovery feel obvious?

## What To Capture Afterward

Write down:

- one thing Loom made easier
- one thing Loom made more confusing
- one command or concept you forgot to use
- one place where the product was too chatty or too silent
- one specific improvement that would make you keep Loom open next time

## Alpha Exit Signal

After 30 to 60 minutes of real multi-agent work, you still want Loom open.
