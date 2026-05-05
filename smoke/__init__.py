"""Smoke tests for end-to-end plumbing.

`python -m smoke.test` is the P0 milestone — verifies Supabase connection,
HubSpot MCP reachability, Slack workspace integration. Inserts a dummy row
into raw_hubspot, posts 'hello' to the configured ops channel, and reads
data_freshness() from the leadle-os MCP skeleton.

If smoke passes, the foundation is alive. Phase 1 work begins.
"""
