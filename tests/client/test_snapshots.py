from dashboard.client import snapshots


def test_baseline_when_no_prior():
    d = snapshots.deltas({"emails_sent": 200}, None)
    assert d["emails_sent"]["baseline"] is True
    assert d["emails_sent"]["delta"] is None


def test_delta_vs_prior():
    d = snapshots.deltas({"emails_sent": 220}, {"emails_sent": 200})
    assert d["emails_sent"]["delta"] == 20
    assert d["emails_sent"]["baseline"] is False


def test_store_roundtrip(tmp_path):
    store = snapshots.LocalJsonStore(tmp_path / "snaps.json")
    assert store.prior("UPSTA", "monthly") is None
    store.save("UPSTA", "monthly", "2026-05-31", {"kpis": {"emails_sent": 100}})
    store.save("UPSTA", "monthly", "2026-06-30", {"kpis": {"emails_sent": 220}})
    prior = store.prior("UPSTA", "monthly", before="2026-06-30")
    assert prior["kpis"]["emails_sent"] == 100   # most recent before current period
