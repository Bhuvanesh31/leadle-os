# tests/test_render.py
import json
from pathlib import Path

import pytest

from dashboard.render import render


@pytest.fixture
def sample_raw():
    return json.loads((Path(__file__).parent / "fixtures" / "sample_raw.json").read_text())


def test_render_produces_html_with_skip_agents(sample_raw):
    html = render(sample_raw, skip_agents=True)
    assert "<!DOCTYPE html>" in html
    assert "Leadle Revenue Engine Dashboard" in html
    assert "May 2026" in html


def test_render_includes_all_four_tabs(sample_raw):
    html = render(sample_raw, skip_agents=True)
    for tab_id in ("page1", "page2", "page3", "page4"):
        assert f'id="{tab_id}"' in html


def test_render_shows_fixture_data(sample_raw):
    html = render(sample_raw, skip_agents=True)
    assert "Scalenut" in html
    assert "QuoDeck" in html


def test_render_includes_degraded_badges(sample_raw):
    html = render(sample_raw, skip_agents=True)
    assert "narrative unavailable" in html
