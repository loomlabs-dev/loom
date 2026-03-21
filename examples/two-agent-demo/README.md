# Two-Agent Demo

This directory now holds Loom's first undeniable proof:

- one developer
- two agents
- one Git repo
- visible claims
- visible intent
- conflict detection before cleanup

## Run It

```bash
python3 examples/two-agent-demo/run_demo.py
```

The script creates a temporary Git repo, seeds a tiny auth/api code layout, and
runs a deterministic local-first regression flow:

1. `loom init --no-daemon`
2. `loom claim`
3. `loom intent`
4. `loom context write`
5. `loom context read`
6. `loom conflicts`
7. `loom unclaim`
8. `loom status`
9. `loom log`

Use `--keep` to preserve the temp repo for inspection, or `--repo /path/to/repo`
to run the walkthrough in a specific directory.
