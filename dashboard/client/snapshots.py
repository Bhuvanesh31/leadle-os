"""Snapshot persistence + delta computation.

v1 uses a local JSON store (no creds). The Supabase table (schemas/0007) is the
v2 home and the corpus for cross-client benchmarks; the row shape matches.
"""

from __future__ import annotations

import json
from pathlib import Path


class LocalJsonStore:
    def __init__(self, path):
        self.path = Path(path)

    def _all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text() or "[]")

    def prior(self, client: str, period_kind: str, before: str | None = None) -> dict | None:
        rows = [r for r in self._all() if r["client"] == client and r["period_kind"] == period_kind]
        if before is not None:
            rows = [r for r in rows if r["period_end"] < before]
        if not rows:
            return None
        rows.sort(key=lambda r: r["period_end"])
        return rows[-1]["metrics"]

    def save(self, client: str, period_kind: str, period_end: str, metrics: dict) -> None:
        rows = [
            r
            for r in self._all()
            if not (
                r["client"] == client
                and r["period_kind"] == period_kind
                and r["period_end"] == period_end
            )
        ]
        rows.append(
            {
                "client": client,
                "period_kind": period_kind,
                "period_end": period_end,
                "metrics": metrics,
            }
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows, indent=2))


_LOWER_IS_BETTER = {"bounce_rate"}


def _dir(field: str, cur, prior):
    if prior is None or not isinstance(cur, (int, float)) or not isinstance(prior, (int, float)):
        return {"value": cur, "delta": None, "dir": "baseline"}
    delta = round(cur - prior, 4)
    if delta == 0:
        return {"value": cur, "delta": 0, "dir": "flat"}
    improved = (delta < 0) if field in _LOWER_IS_BETTER else (delta > 0)
    return {"value": cur, "delta": delta, "dir": "up" if improved else "down"}


def box_deltas(current: dict, prior: dict | None) -> dict:
    out: dict = {}
    pk = (prior or {}).get("kpis", {})
    for k, v in (current.get("kpis") or {}).items():
        out[f"kpis.{k}"] = _dir(k, v, pk.get(k) if prior else None)

    pboxes = (prior or {}).get("boxes", {})
    cboxes = current.get("boxes") or {}
    # Boxes with a stable identity (name) get per-row WoW. Email steps are intentionally
    # excluded: their week-to-week identity is unstable and 'step' is an id, not a metric.
    for box, prefix in (("email_campaigns", "campaign"),
                        ("linkedin_campaigns", "campaign"),
                        ("linkedin_variants", "variant")):
        prior_by_name = {r["name"]: r for r in (pboxes.get(box) or [])}
        for row in cboxes.get(box, []):
            prow = prior_by_name.get(row["name"]) if prior else None
            for field, val in row.items():
                if isinstance(val, (int, float)):
                    out[f"{prefix}.{row['name']}.{field}"] = _dir(
                        field, val, (prow or {}).get(field) if prow else None
                    )
    return out


def deltas(current: dict, prior: dict | None) -> dict:
    out: dict = {}
    for key, value in current.items():
        if not isinstance(value, (int, float)):
            continue
        if prior is None or key not in prior:
            out[key] = {"value": value, "delta": None, "baseline": True}
        else:
            out[key] = {"value": value, "delta": round(value - prior[key], 4), "baseline": False}
    return out
