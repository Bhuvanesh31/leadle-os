"""Tests for Jinja templates with strict undefined checking."""

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined


@pytest.fixture
def env():
    return Environment(
        loader=FileSystemLoader("dashboard/templates"),
        undefined=StrictUndefined,
        autoescape=True,
    )


@pytest.fixture
def context():
    return {
        "analytics": {
            "page1": {
                "goal_snapshot": {
                    "ytd_revenue": 12000,
                    "goal_amount": 319000,
                    "goal_currency": "USD",
                    "pct_of_goal": 3.76,
                    "revenue_remaining": 307000,
                    "monthly_needed": 61400,
                    "run_rate_status": "critical",
                },
                "monthly_control": {
                    "mtd_revenue": 0,
                    "monthly_target": 61800,
                    "pct_target_achieved": 0,
                    "monthly_gap": 61800,
                    "open_pipeline": 13000,
                    "pipeline_coverage_ratio": 0.21,
                    "pipeline_coverage_status": "critical",
                    "closed_won_count": 0,
                },
                "execution": {
                    "window_label": "May 2026",
                    "new_leads": 2,
                    "qualified_leads": 1,
                    "qualification_rate": 50.0,
                    "meetings_booked": 2,
                    "opportunities": 1,
                    "proposals_sent": 0,
                    "pipeline_added": 0,
                },
                "channel_performance": {
                    "channels": [
                        {
                            "channel": "ORGANIC_SEARCH",
                            "deal_count": 1,
                            "pipeline": 5000,
                            "closed_won_revenue": 0,
                        }
                    ]
                },
                "channel_economics": {"channels": []},
                "funnel": {
                    "stage_counts": {"discovery": 1, "proposal": 1, "closedwon": 1},
                    "conversions": [
                        {
                            "from_stage": "discovery",
                            "to_stage": "proposal",
                            "from_count": 1,
                            "to_count": 1,
                            "conversion_pct": 100.0,
                        }
                    ],
                },
                "accountability": {"owners": []},
                "hygiene": {
                    "missing_source_count": 0,
                    "missing_owner_count": 0,
                    "missing_lifecycle_count": 0,
                    "total_issues": 0,
                    "issues": [],
                },
                "forward_motion_input": {"rotting_deals": [], "rotting_pipeline_at_risk": 0},
            },
            "page2": {
                "rotting_deals": [],
                "pipeline_at_risk": 0,
                "stalled_leads": [],
                "lead_funnel": {
                    "total_leads": 0,
                    "totals": {
                        "call_completed": 0, "meeting_booked_no_call": 0,
                        "responded_no_meeting": 0, "replied_awaiting_us": 0,
                        "no_reply": 0,
                    },
                    "call_completed": [], "meeting_booked_no_call": [],
                    "responded_no_meeting": [], "replied_awaiting_us": [],
                    "no_reply": [], "lead_rotting": [], "rotting_count": 0,
                },
                "kpi": {
                    "rotting_count": 0,
                    "stalled_count": 0,
                    "stalled_30d_plus": 0,
                    "most_critical_deal": None,
                },
            },
            "page3": {"fathom_gap": [], "gap_count": 0},
            "page4": {"lemlist": [], "aimfox": [], "instantly": [], "followup_gap": []},
        },
        "narratives": {
            "forward_motion": {"degraded": True},
            "funnel_leak": {"degraded": True},
            "hygiene": {"degraded": True},
            "fathom_gap": {"degraded": True, "actions": []},
        },
        "window": {"label": "May 2026", "name": "current-month"},
        "rendered_at": "2026-05-09T10:00:00",
        "degraded_sections": ["funnel narrative", "hygiene narrative"],
    }


def test_base_renders_without_error(env, context):
    """Test that base template renders with all required context."""
    html = env.get_template("base.html.j2").render(**context)
    assert "Leadle Revenue Engine Dashboard" in html
    assert "May 2026" in html


def test_all_four_tabs_present(env, context):
    """Test that all four tabs are present in the rendered HTML."""
    html = env.get_template("base.html.j2").render(**context)
    for tab_id in ("page1", "page2", "page3", "page4"):
        assert f'id="{tab_id}"' in html


def test_degraded_narratives_show_fallback_badges(env, context):
    """Test that degraded narratives show 'narrative unavailable' badge."""
    html = env.get_template("base.html.j2").render(**context)
    assert "narrative unavailable" in html


def test_page1_revenue_template_renders(env, context):
    """Test Page 1 Revenue Engine template renders without errors."""
    html = env.get_template("page1_revenue.html.j2").render(**context)
    assert "Revenue Engine Dashboard" in html
    assert "Goal Snapshot" in html
    assert "Monthly Control Panel" in html
    assert "Execution Panel" in html


def test_page2_activity_template_renders(env, context):
    """Test Page 2 Activity & Rot template renders without errors."""
    html = env.get_template("page2_activity.html.j2").render(**context)
    assert "Activity" in html and "Rot Monitor" in html
    assert "Rotting Deals" in html
    assert "Stalled Leads" in html


def test_page3_actions_template_renders(env, context):
    """Test Page 3 Sales Actions template renders without errors."""
    html = env.get_template("page3_actions.html.j2").render(**context)
    assert "Sales Actions" in html
    # Two gap sections (Lead-to-Deal not promoted, Call without CRM record)
    assert "Lead" in html and "Deal" in html
    assert "Call without CRM record" in html
    assert "Inbound" in html
    assert "Outbound" in html


def test_page4_outreach_template_renders(env, context):
    """Test Page 4 Outreach template renders without errors."""
    html = env.get_template("page4_outreach.html.j2").render(**context)
    assert "Outreach" in html
    assert "Lemlist" in html
    assert "Aimfox" in html
    assert "Instantly" in html
    assert "Follow-up Gap" in html


def test_sop_inbound_partial_renders(env, context):
    """Test SOP inbound partial renders."""
    html = env.get_template("_sop_inbound.html.j2").render(**context)
    assert "Web Form" in html
    assert "Inbound" in html


def test_sop_outbound_partial_renders(env, context):
    """Test SOP outbound partial renders."""
    html = env.get_template("_sop_outbound.html.j2").render(**context)
    assert "LinkedIn / Email Sequence" in html
    assert "Outbound" in html


def test_footer_present(env, context):
    """Test that footer is present in rendered output."""
    html = env.get_template("base.html.j2").render(**context)
    assert "Leadle RevOps · Confidential" in html
    assert "Rendered" in html
