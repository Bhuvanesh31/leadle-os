"""HubSpot ingestion via HubSpot MCP.

This is the only connector that's agent-orchestrated. The reason is tier-related:
Marketing Hub Starter + Sales Hub Pro restricts the breadth of programmatic API
access we need for full-property reads on contacts/companies/deals/engagements.
HubSpot MCP (claude.ai-managed vendor MCP) routes through a different access
path that supplies the coverage we need.

Lands raw payloads into raw_hubspot. Schema design happens in P1 after we
produce docs/data-shape/hubspot.md.
"""
