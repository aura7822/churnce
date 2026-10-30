"""The "extend time" control: +30 s on the backend countdown, capped, audited, permission-checked."""
from datetime import datetime

from conftest import wait_until
from test_pipeline import V1, _simulate


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_extend_pushes_backend_deadline_and_respects_manual_mode(client, api):
    admin = api.as_("administrator")
    # A long window so the scheduler cannot approve the chunk while the test is running.
    assert client.patch(f"{V1}/config", headers=admin, json={"review_seconds": 60, "review_policy": "auto_approve_filtered"}).status_code == 200
    try:
        _simulate(client, api, "search_dead_end", sessions=1)
        chunk = wait_until(
            lambda: next((c for c in client.get(f"{V1}/chunks/pending", headers=admin).json()["chunks"] if c["review_mode"] == "auto"), None),
            message="no auto-review chunk pending",
        )
        before = _ts(chunk["review_deadline"])

        assert client.post(f"{V1}/chunks/{chunk['id']}/extend", headers=api.as_("reviewer")).status_code == 403
        assert client.post(f"{V1}/chunks/does_not_exist/extend", headers=admin).status_code == 404

        got = client.post(f"{V1}/chunks/{chunk['id']}/extend", headers=admin)
        assert got.status_code == 200, got.text
        after = _ts(got.json()["review_deadline"])
        assert 29 <= (after - before).total_seconds() <= 31  # +30 s, give or take rounding
        assert got.json()["state"] == "PENDING_REVIEW" and got.json()["version"] == chunk["version"]  # not an edit

        # Repeated extensions stay inside the 10-minute ceiling.
        for _ in range(30):
            last = client.post(f"{V1}/chunks/{chunk['id']}/extend", headers=admin).json()
        assert (_ts(last["review_deadline"]) - datetime.now(after.tzinfo)).total_seconds() <= 601

        audited = client.get(f"{V1}/audit?limit=200", headers=admin).json()["audit"]
        assert any(a["action"] == "chunk_extended" and a["entity_id"] == chunk["id"] for a in audited)

        client.post(f"{V1}/chunks/{chunk['id']}/discard", headers=admin)
        # A discarded chunk has no countdown any more.
        assert client.post(f"{V1}/chunks/{chunk['id']}/extend", headers=admin).status_code == 409
    finally:
        # The API refuses windows under 3 s, so restore the suite's 1 s window straight in the database.
        from app.database import SessionLocal
        from app.models import MonitoringConfig

        with SessionLocal() as db:
            for cfg in db.query(MonitoringConfig).all():
                cfg.review_seconds = 1
            db.commit()
