"""Identity resolution.

Two paths:
  1. Clay-IDs (script): the 95% case. Reads hubspot_company_id and
     hubspot_contact_id from custom fields injected by Clay into Lemlist /
     Aimfox / Instantly leads during enrichment. Direct join, HIGH confidence.
  2. Edge cases (small Haiku-class agent): records that arrive without Clay
     IDs go to unmatched_review. The agent attempts a waterfall match —
     LinkedIn slug → email-domain root → fuzzy name+country — and either
     resolves them or escalates to Slack for human review.
"""
