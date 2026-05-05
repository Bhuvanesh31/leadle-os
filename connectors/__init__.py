"""Per-source ingestion.

One subpackage per source: `hubspot/`, `lemlist/`, `aimfox/`, `instantly/`, `fathom/`.

HubSpot is special: agent-orchestrated through HubSpot MCP because Marketing
Hub Starter + Sales Hub Pro tier limits make programmatic API scripts
insufficient for the breadth of read access required.

The other four are scripts using REST APIs.
"""
