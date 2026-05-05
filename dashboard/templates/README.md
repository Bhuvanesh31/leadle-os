# Dashboard templates

Jinja2 templates that render the live dashboard. Layout follows `/home/bhuvanesh/Downloads/leadle-dashboard-v2.html` — the user already designed the presentation; we're producing data into the existing structure.

## Convention

- One template per tab: `tab1_revenue_engine.html.j2`, `tab2_activity_rot.html.j2`, `tab4_outreach.html.j2`. (Tabs 3 and 5 deferred to Extensions.)
- A `base.html.j2` provides shared chrome (header, freshness banner, tab nav).
- A `partials/` subdirectory for repeated section blocks.
- All numeric formatting goes through Jinja filters defined in `dashboard/filters.py`.

## Phase

Templates are added in P7. Earlier phases produce data; nothing renders until P7 — the brief is the Phase 1 deliverable for Sai, the dashboard is the Phase 1 deliverable for Akil/Bhuvanesh, and the latter is the last to land.
