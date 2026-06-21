# Contributing to Leadle OS

Leadle OS is an internal tool. Contributions are made by Leadle team members only.

## Ground rules

- All changes go through a feature branch and PR — no direct pushes to `main`
- Every PR must pass CI (ruff lint + pytest) before merge
- Follow the architectural principles in [`CLAUDE.md`](CLAUDE.md)
- New analytics processes: script for deterministic logic, agent for judgment/narrative
- New thresholds or rules belong in `config/*.yaml`, not in code

## Branch naming

```
feat/<short-description>    new capability
fix/<short-description>     bug fix
docs/<short-description>    documentation only
chore/<short-description>   config, deps, CI changes
```

## Making a change

1. Branch from `main`
2. Make your changes; write tests in `tests/` for any new analytics logic
3. Run `ruff check .` and `pytest` locally before pushing
4. Open a PR — use the PR template, link the relevant spec section
5. One approval required before merge

## Adding a new analytics process

1. Write the script in `analytics/<name>.py`
2. Add the slash command in `.claude/commands/<name>.md`
3. Update `docs/` if the data shape is new
4. Add at least one smoke test

## Contact

Questions: ping Bhuvanesh (`revops@leadle.in`) or open an issue.
