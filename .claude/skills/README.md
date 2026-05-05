# Local Leadle OS skills

Skills are Claude-discoverable instruction sets that activate based on context. We use skills here for:

- Multi-step internal procedures (e.g., "explore a new data source" — pull, observe, document, then propose schema).
- Voice/style enforcement (e.g., the AI-pattern sniffer behavior in agent outputs).
- Operational checklists (e.g., the post-phase "done when" verification).

Skills added per phase. Don't pre-build skills speculatively — only when a recurring procedure has emerged in actual use.

## Planned skills

| Skill | Phase | When it fires |
|---|---|---|
| `explore-source` | P3 (after we've done it once for HubSpot) | When a new connector is being added; walks through pull → observe → document → propose-schema |
| `compose-brief` | P1 | Voice + structure rules for Sai's brief |
| `sniff-ai-patterns` | E3 | Before any user-facing draft is published — flags AI-sounding phrases per `LEADLE_CONTEXT.md` tone reference |
| `signal-to-motion-classify` | P5 | Walks through buying-posture and action-type classification for an account |
