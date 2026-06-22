"""Tests for the client -> spreadsheet_id registry."""
import pytest

from dashboard.client.sources import client_registry


def test_resolves_known_client():
    assert client_registry.spreadsheet_id_for("UPSTA") == \
        "1GgFeDdXpy1ZlDjH8bTWNL_c7m0ihSSO_-iYNyzadCQg"


def test_unknown_client_raises_listing_known():
    with pytest.raises(KeyError) as exc:
        client_registry.spreadsheet_id_for("NOPE")
    assert "UPSTA" in str(exc.value)
