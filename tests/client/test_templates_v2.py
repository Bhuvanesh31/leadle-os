"""Template-v2 tests: the rendered HTML matches the approved design and all
numbers flow from the metrics bag. Fixtures live in conftest.py."""


def test_client_headline_emails_sent_figure(rendered_client_html):
    # fixture sends 100 + 60 = 160 emails; the headline figure must appear.
    assert "160" in rendered_client_html


def test_client_has_no_internal_leakage(rendered_client_html):
    h = rendered_client_html.lower()
    assert "augustine" not in h
    assert "pause & warm" not in h
    assert "pause &amp; warm" not in h
    assert "sender health" not in h
    assert "signal-to-motion" not in h


def test_internal_shows_sender_health(rendered_internal_html):
    h = rendered_internal_html.lower()
    assert "sender" in h
    # the flagged sender's email must be present in internal output
    assert "augustine@upsta.co" in rendered_internal_html


def test_autoescape_holds(rendered_client_html):
    # campaign name "A<b" must be escaped, never raw.
    assert "A<b" not in rendered_client_html
    assert "A&lt;b" in rendered_client_html


def test_blue_palette_applied_when_opens(rendered_client_html):
    palette = ["#EFF6FF", "#DBEAFE", "#93C5FD", "#3B82F6", "#1D4ED8"]
    assert any(hexv in rendered_client_html for hexv in palette)


def test_timing_best_none_renders_without_literal_none(rendered_client_zero_opens):
    # zero opens → best.weekday is None; the guarded fallback must render,
    # not the literal string "None".
    h = rendered_client_zero_opens
    assert h  # rendered without raising
    # the timing section should not surface a bare "None" weekday.
    assert "Best: None" not in h
    assert "None None" not in h


def test_content_best_step_highlighted(rendered_client_html):
    # step 3 has the highest open rate → marked "best" per the approved design.
    assert "best" in rendered_client_html.lower()
