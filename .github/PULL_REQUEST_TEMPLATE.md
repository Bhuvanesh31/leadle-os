## What this does

<!-- One sentence. What changed and why. -->

## Spec / task reference

<!-- Link the relevant spec section or task. -->

## Type

- [ ] New analytics process
- [ ] Dashboard / template change
- [ ] Config change (YAML only — no logic)
- [ ] Bug fix
- [ ] Docs / CLAUDE.md update
- [ ] CI / tooling

## Checklist

- [ ] `ruff check .` passes locally
- [ ] `pytest tests/` passes locally
- [ ] No secrets committed (check `.env` is gitignored)
- [ ] New script has a matching `.claude/commands/` slash command
- [ ] CHANGELOG.md updated if this is a user-visible change
- [ ] Follows agent vs. script rule from CLAUDE.md (agent iff judgment/narrative)
