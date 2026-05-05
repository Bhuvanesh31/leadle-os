"""leadle-os local MCP server (custom, stdio).

Exposes semantic analytics tools to Claude:
    pipeline_health()           phantom_deals()
    signal_to_motion_score()    stuck_deals(stage, days)
    funnel_breakdown(by, period) campaign_performance(tool)
    call_themes(filter)          unmatched_review()
    data_freshness()             tofu_health()

Reads from Supabase. Does not call source APIs directly.

Distinct from HubSpot MCP, which is the *ingestion* path. This server is the
*analytics* path — the surface Claude reasons through during interactive
sessions and scheduled runs.
"""
