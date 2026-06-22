"""Tests for connectors.google_sheets.fetch — injected fake client, no network/auth."""

import pytest

from connectors.google_sheets import fetch


class _FakeWorksheet:
    def __init__(self, title, rows):
        self.title = title
        self._rows = rows

    def get_all_values(self):
        return self._rows


class _FakeSpreadsheet:
    def __init__(self, sheets):
        self._sheets = sheets  # dict[title -> rows]

    def worksheets(self):
        return [_FakeWorksheet(t, r) for t, r in self._sheets.items()]

    def worksheet(self, title):
        return _FakeWorksheet(title, self._sheets[title])


class _FakeClient:
    def __init__(self, sheets):
        self._sheets = sheets

    def open_by_key(self, key):
        assert key == "sheet-123"
        return _FakeSpreadsheet(self._sheets)


def test_fetch_returns_requested_tabs_and_omits_absent():
    fake = _FakeClient(
        {
            "Prospect Data-US": [["Company Name"], ["Acme"]],
            "Webhook - Email": [["Event Type"], ["email_opened"]],
        }
    )
    out = fetch.fetch(
        "sheet-123", ["Prospect Data-US", "Webhook - Email", "Response Tracker"], client=fake
    )
    assert set(out) == {"Prospect Data-US", "Webhook - Email"}  # absent tab omitted
    assert out["Prospect Data-US"] == [["Company Name"], ["Acme"]]


def test_authorized_client_errors_without_token(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEETS_TOKEN", raising=False)
    with pytest.raises(RuntimeError) as exc:
        fetch._authorized_client()
    assert "GOOGLE_SHEETS_TOKEN" in str(exc.value)
    assert "authorize" in str(exc.value)
