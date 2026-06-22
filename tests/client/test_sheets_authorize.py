"""authorize.main must fail clearly (before any browser) when env is unset."""

import pytest

from connectors.google_sheets import authorize


def test_main_requires_client_secret_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEETS_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("GOOGLE_SHEETS_TOKEN", "/tmp/token.json")
    with pytest.raises(RuntimeError) as exc:
        authorize.main()
    assert "GOOGLE_SHEETS_CLIENT_SECRET" in str(exc.value)
