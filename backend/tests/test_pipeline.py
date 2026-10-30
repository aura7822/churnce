"""End-to-end tests of the whole loop against the real app, scheduler thread included."""
import uuid

from conftest import wait_until

V1 = "/api/v1"


def _simulate(client, api, scenario, sessions=3):
    r = client.post(f"{V1}/demo/simulate", headers=api.as_("administrator"), json={"scenario": scenario, "sessions": sessions})
    assert r.status_code == 200, r.text
    return r.json()


def test_health_and_auth(client, api):
    assert client.get("/healthz").status_code == 200
    assert client.get(f"{V1}/metrics").status_code == 401
    bad = client.post(f"{V1}/auth/login", json={"email": "admin@churnce.demo", "password": "wrong"})
    assert bad.status_code == 401
    me = client.get(f"{V1}/me", headers=api.as_("reviewer")).json()
    assert me["user"]["role"] == "reviewer" and me["environment"] == "demo"


def test_ingest_requires_valid_key_domain_and_consent(client, ingest_headers):
    ev = {"event_id": f"e_{uuid.uuid4().hex}", "session_id": "s_auth", "event_type": "page_view", "page_route": "/", "site_host": "localhost"}
    assert client.post(f"{V1}/events", json={"events": [ev]}).status_code == 401
    assert client.post(f"{V1}/events", headers={"X-Churnce-Key": "nope"}, json={"events": [ev]}).status_code == 401

    wrong_host = {**ev, "event_id": f"e_{uuid.uuid4().hex}", "site_host": "evil.example.org"}
    r = client.post(f"{V1}/events", headers=ingest_headers, json={"events": [wrong_host]}).json()
    assert r["accepted"] == 0 and r["rejected"][0]["reason"] == "domain_not_authorized"

    no_consent = {**ev, "event_id": f"e_{uuid.uuid4().hex}", "consent_state": "denied"}
    r = client.post(f"{V1}/events", headers=ingest_headers, json={"events": [no_consent]}).json()
    assert r["accepted"] == 0 and r["rejected"][0]["reason"] == "consent_not_authorized"

    ok = client.post(f"{V1}/events", headers=ingest_headers, json={"events": [ev]}).json()
    assert ok["accepted"] == 1
    again = client.post(f"{V1}/events", headers=ingest_headers, json={"events": [ev]}).json()
    assert again["accepted"] == 0 and again["duplicates"] == 1  # idempotent


def test_pii_never_reaches_stored_events(client, api, ingest_headers):
    sid = f"s_pii_{uuid.uuid4().hex[:6]}"
    evs = [
        {"event_id": f"e_{uuid.uuid4().hex}", "session_id": sid, "event_type": "search_no_results", "page_route": "/search",
         "site_host": "localhost", "outcome": "no_results", "meta": {"search_query": "boots for jane.doe@example.com", "password": "hunter2"}},
    ]
    assert client.post(f"{V1}/events", headers=ingest_headers, json={"events": evs}).json()["accepted"] == 1
    body = client.get(f"{V1}/events?limit=200", headers=api.as_("reviewer")).text
    assert "jane.doe@example.com" not in body and "hunter2" not in body


def test_full_loop_from_friction_to_verified_reengagement(client, api):
    admin, eng, mkt = api.as_("administrator"), api.as_("engineer"), api.as_("marketing_operator")
    _simulate(client, api, "checkout_failure", sessions=4)

    # 1. Chunks appear, the BACKEND countdown approves them, they get indexed and become retrievable.
    wait_until(lambda: any(c["state"] == "AVAILABLE_FOR_RETRIEVAL" for c in client.get(f"{V1}/chunks", headers=admin).json()["chunks"]), message="no chunk reached AVAILABLE_FOR_RETRIEVAL")

    # 2. An incident is opened and analysed with cited evidence.
    def analysed():
        incs = client.get(f"{V1}/incidents", headers=admin).json()["incidents"]
        return next((i for i in incs if i["journey_stage"] == "checkout" and i["status"] in ("analyzed", "action_pending")), None)

    inc = wait_until(analysed, message="incident not analysed")
    detail = client.get(f"{V1}/incidents/{inc['id']}", headers=admin).json()
    assert detail["recommended_action"]["type"] == "engineering_investigation"
    assert detail["evidence_ids"], "diagnosis must cite evidence"
    assert detail["unresolved_questions"], "must state what is still unknown"
    assert detail["retrieval"]["candidates"], "retrieval must be inspectable"
    assert detail["customer_message_eligible"] is False

    # 3. No outbound marketing exists before a verified resolution; engineering action needs a human.
    acts = detail["actions"]
    assert not [a for a in acts if a["category"] == "marketing" and a["type"] != "suppress_campaign"]
    primary = next(a for a in acts if a["type"] == "engineering_investigation")
    assert primary["status"] == "AWAITING_APPROVAL"
    assert client.post(f"{V1}/actions/{primary['id']}/approve", headers=api.as_("reviewer")).status_code == 403
    assert client.post(f"{V1}/actions/{primary['id']}/approve", headers=mkt).status_code == 403
    done = client.post(f"{V1}/actions/{primary['id']}/approve", headers=eng).json()
    assert done["status"] == "COMPLETED"
    assert client.post(f"{V1}/actions/{primary['id']}/approve", headers=eng).status_code == 409  # not re-executable

    # 4. A fix that is deployed but unproven does NOT unlock customer messaging.
    weak = client.post(f"{V1}/resolutions", headers=eng, json={
        "incident_id": inc["id"], "issue_category": "checkout_responsiveness",
        "sources": [{"type": "release", "ref": "release_000014", "status": "deployed"}],
        "approved_claims": ["The checkout flow has been improved"], "segment_available": True,
    }).json()
    assert weak["resolution_status"] == "pending_verification" and weak["email_eligible"] is False
    assert client.get(f"{V1}/emails", headers=mkt).json()["emails"] == []

    # 5. Adding a passing test run verifies it and proposes (but does not send) a re-engagement email.
    ver = client.post(f"{V1}/resolutions/{weak['resolution_id']}/sources", headers=eng, json={
        "source": {"type": "test_run", "ref": "test_run_000029", "status": "passed"}}).json()
    assert ver["resolution_status"] == "verified" and ver["email_eligible"] is True
    mk = wait_until(lambda: next((a for a in client.get(f"{V1}/recommendations?incident_id={inc['id']}", headers=mkt).json()["recommendations"] if a["type"] == "reengagement_email"), None))
    assert mk["status"] == "AWAITING_APPROVAL"
    assert client.post(f"{V1}/actions/{mk['id']}/approve", headers=mkt).json()["status"] == "COMPLETED"

    # 6. Drafts exist only for customers who pass every policy check; the rest are blocked with reasons.
    emails = client.get(f"{V1}/emails", headers=mkt).json()["emails"]
    assert emails, "expected drafts or blocked records"
    customers = {c["id"]: c for c in client.get(f"{V1}/customers", headers=mkt).json()["customers"]}
    for e in emails:
        c = customers[e["customer_id"]]
        if c["consent"] != "opt_in" or c["suppressed"]:
            assert e["status"] == "blocked", f"{c['ref']} must never be drafted"
        if e["status"] == "draft":
            text = (e["subject"] + e["body"]).lower()
            assert "timeout" not in text and "bug" not in text and "outage" not in text  # benefit-focused, no defect talk
            assert e["claims_used"] == ["The checkout flow has been improved"]
    drafts = [e for e in emails if e["status"] == "draft"]
    if drafts:
        d = drafts[0]
        assert client.post(f"{V1}/emails/{d['id']}/approve", headers=api.as_("reviewer")).status_code == 403
        assert client.post(f"{V1}/emails/{d['id']}/send", headers=mkt).status_code == 409  # not approved yet
        assert client.post(f"{V1}/emails/{d['id']}/approve", headers=mkt).json()["status"] == "approved"
        assert client.post(f"{V1}/emails/{d['id']}/send", headers=mkt).json()["status"] == "sent_simulated"

    # 7. Outcome is measured honestly: simulated data, small sample => no strong claim.
    _simulate(client, api, "checkout_success", sessions=3)
    outs = client.post(f"{V1}/incidents/{inc['id']}/evaluate", headers=mkt).json()["outcomes"]
    assert outs and all(o["simulated"] for o in outs)
    assert all(o["strength"] in ("insufficient", "low") for o in outs)

    # 8. Every state change is audited.
    audit = client.get(f"{V1}/audit?limit=500", headers=admin).json()["audit"]
    assert {"action_executed", "resolution_recorded", "incident_opened"} <= {a["action"] for a in audit}


def test_review_gate_manual_edit_conflict_and_never_auto_ingest(client, api):
    admin = api.as_("administrator")
    assert client.patch(f"{V1}/config", headers=admin, json={"review_policy": "manual"}).status_code == 200
    try:
        _simulate(client, api, "search_dead_end", sessions=1)
        chunk = wait_until(lambda: next((c for c in client.get(f"{V1}/chunks/pending", headers=admin).json()["chunks"] if c["issue_signature"] == "search:no_results"), None), message="no pending chunk")
        assert chunk["review_mode"] == "manual" and chunk["seconds_remaining"] is None

        import time as _t
        _t.sleep(3)  # well past the 1s review window: the timer must NOT approve a manual-review chunk
        again = client.get(f"{V1}/chunks/{chunk['id']}", headers=admin).json()
        assert again["state"] == "PENDING_REVIEW"

        stale = client.patch(f"{V1}/chunks/{chunk['id']}", headers=admin, json={"version": 99, "summary": "x" * 10})
        assert stale.status_code == 409
        edited = client.patch(f"{V1}/chunks/{chunk['id']}", headers=admin, json={"version": chunk["version"], "summary": "Customer searched for wide-fit boots and found nothing"})
        assert edited.status_code == 200 and edited.json()["version"] == chunk["version"] + 1 and edited.json()["edited"] is True

        assert client.post(f"{V1}/chunks/{chunk['id']}/approve", headers=api.as_("reviewer")).status_code == 403
        ok = client.post(f"{V1}/chunks/{chunk['id']}/approve", headers=admin).json()
        assert ok["state"] in ("QUEUED_FOR_INGESTION", "EMBEDDING", "INDEXED", "AVAILABLE_FOR_RETRIEVAL", "VALIDATING")
        wait_until(lambda: client.get(f"{V1}/chunks/{chunk['id']}", headers=admin).json()["state"] == "AVAILABLE_FOR_RETRIEVAL")
        assert client.post(f"{V1}/chunks/{chunk['id']}/discard", headers=admin).status_code == 409  # too late to discard
    finally:
        client.patch(f"{V1}/config", headers=admin, json={"review_policy": "auto_approve_filtered"})


def test_discarded_chunk_never_enters_index(client, api):
    admin = api.as_("administrator")
    client.patch(f"{V1}/config", headers=admin, json={"review_policy": "manual"})
    try:
        _simulate(client, api, "onboarding_stall", sessions=1)
        chunk = wait_until(lambda: next((c for c in client.get(f"{V1}/chunks/pending", headers=admin).json()["chunks"] if c["journey_stage"] == "onboarding"), None))
        assert client.post(f"{V1}/chunks/{chunk['id']}/discard", headers=admin).json()["state"] == "DISCARDED"
        hits = client.post(f"{V1}/rag/search", headers=admin, json={"query": "onboarding profile save failures", "collections": ["customer_journey"]}).json()
        assert chunk["id"] not in str(hits["candidates"])
    finally:
        client.patch(f"{V1}/config", headers=admin, json={"review_policy": "auto_approve_filtered"})


def test_rbac_and_tenant_isolation(client, api):
    reviewer, admin = api.as_("reviewer"), api.as_("administrator")
    assert client.patch(f"{V1}/config", headers=reviewer, json={"monitoring_enabled": False}).status_code == 403
    assert client.get(f"{V1}/users", headers=reviewer).status_code == 403
    assert client.post(f"{V1}/demo/simulate", headers=reviewer, json={"scenario": "checkout_failure"}).status_code == 403

    # Second tenant, created directly in the DB.
    from app.database import SessionLocal
    from app.models import Organization, User, MonitoringConfig
    from app.security import hash_ingest_key, hash_password

    db = SessionLocal()
    try:
        org = Organization(name="Other Co")
        db.add(org); db.flush()
        db.add(MonitoringConfig(org_id=org.id, ingest_key_hash=hash_ingest_key("other-key"), authorized_domains=["other.test"]))
        db.add(User(org_id=org.id, email="x@other.test", name="X", role="administrator", password_hash=hash_password("Another-Pass-1")))
        db.commit()
    finally:
        db.close()
    other = api.login("x@other.test", "Another-Pass-1")
    mine = client.get(f"{V1}/chunks", headers=admin).json()["chunks"]
    assert mine
    assert client.get(f"{V1}/chunks/{mine[0]['id']}", headers=other).status_code == 404  # indistinguishable from "missing"
    assert client.get(f"{V1}/chunks", headers=other).json()["chunks"] == []
    assert client.get(f"{V1}/incidents", headers=other).json()["incidents"] == []
    # Retrieval is tenant-scoped: the other tenant sees none of the seeded knowledge.
    rag = client.post(f"{V1}/rag/search", headers=other, json={"query": "checkout payment timeouts"}).json()
    assert not any(c["kept"] for c in rag["candidates"])


def test_websocket_requires_auth_and_streams_events(client, api, ingest_headers):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"{V1}/stream") as ws:
            ws.send_json({"type": "auth", "token": "garbage"})
            ws.receive_json()

    token = api.as_("reviewer")["Authorization"].split()[1]
    with client.websocket_connect(f"{V1}/stream") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "hello"
        ev = {"event_id": f"e_{uuid.uuid4().hex}", "session_id": "s_ws", "event_type": "page_view", "page_route": "/", "site_host": "localhost"}
        client.post(f"{V1}/events", headers=ingest_headers, json={"events": [ev]})
        msg = ws.receive_json()
        assert msg["type"] == "event_ingested"
