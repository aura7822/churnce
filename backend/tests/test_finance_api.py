"""Premium plan + 72-hour trial, finance ingestion (consent, plan and capture gated), KES figures, liquidity suite, capture control, sweeps,
Cents AI (deterministic fallback), website identity and website-ID sign-in with scoped data, and the Digest trigger."""
from datetime import datetime, timezone

V1 = "/api/v1"
HOST = "shop.churnce.demo"
CONSENT = {"scopes": ["session", "user_data", "finance"]}


def _event(i, status="success", reason=None, typ="payment", amount=120.5, **extra):
    e = {"event_id": f"ord-{i}", "txn_type": typ, "status": status, "amount": amount, "currency": "KES", "method": "mobile_money", "bank": "Equity Bank",
         "occurred_at": datetime.now(timezone.utc).isoformat(), **extra}
    if reason:
        e["reason"] = reason
    return e


def _hb(client, ingest_headers):
    return client.post(f"{V1}/sites/heartbeat", headers=ingest_headers, json={"site_host": HOST, "monitoring": True, "consent": CONSENT, "rtt_ms": 42}).json()


def test_free_plan_is_gated_everywhere(client, api, ingest_headers):
    admin = api.as_("administrator")
    assert client.get(f"{V1}/finance/summary", headers=admin).status_code == 402
    assert client.get(f"{V1}/finance/liquidity", headers=admin).status_code == 402
    assert client.post(f"{V1}/finance/events", headers=ingest_headers, json={"site_host": HOST, "events": [_event(1)]}).status_code == 402
    assert client.post(f"{V1}/plan", json={"plan": "premium"}, headers=api.as_("developer")).status_code == 403


def test_72_hour_trial_unlocks_premium_for_one_website_only(client, api, ingest_headers):
    admin = api.as_("administrator")
    r = client.post(f"{V1}/sites/register", headers=ingest_headers, json={"site_host": HOST, "name": "Demo Shop", "owner_name": "Amina Otieno", "regenerate_password": True}).json()
    cred = {"website_id": r["website_id"], "password": r["password"]}
    assert client.post(f"{V1}/finance/events", headers=ingest_headers, json={"site_host": HOST, "events": [_event(1)]}).status_code == 402
    t = client.post(f"{V1}/sites/trial", headers=ingest_headers, json={"site_host": HOST})
    assert t.status_code == 200 and t.json()["premium"]["active"] is True and 0 < t.json()["seconds_left"] <= 72 * 3600
    assert client.post(f"{V1}/sites/trial", headers=ingest_headers, json={"site_host": HOST}).status_code == 409  # once per website id
    # trial alone does not bypass owner consent
    assert client.post(f"{V1}/finance/events", headers=ingest_headers, json={"site_host": HOST, "events": [_event(1)]}).status_code == 403
    hb = _hb(client, ingest_headers)
    assert hb["premium"]["active"] is True and hb["premium"]["source"] == "trial" and hb["finance_capture"]["state"] == "running"
    ok = client.post(f"{V1}/finance/events", headers=ingest_headers, json={"site_host": HOST, "events": [_event(i) for i in range(3)]})
    assert ok.status_code == 200 and ok.json()["accepted"] == 3
    # website-ID sign-in: scoped session, trial gives it Premium, server-wide areas answer with the custom 403
    login = client.post(f"{V1}/auth/site-login", json={**cred, "role": "data_analyst"})
    assert login.status_code == 200 and login.json()["scope"]["site_host"] == HOST
    tok = {"Authorization": f"Bearer {login.json()['token']}"}
    assert client.get(f"{V1}/me", headers=tok).json()["scope"]["website_id"] == r["website_id"]
    assert client.get(f"{V1}/plan/access", headers=tok).json()["source"] == "trial"
    assert client.get(f"{V1}/finance/summary", headers=tok).status_code == 200
    for path in ("/logs", "/audit", "/config", "/users", "/demo/scenarios"):
        denied = client.get(f"{V1}{path}", headers=tok)
        assert denied.status_code == 403 and denied.json()["code"] == "site_scope", path
    assert client.post(f"{V1}/rag/search", json={"query": "checkout"}, headers=tok).status_code == 403
    assert client.get(f"{V1}/sites/any/feed", headers=tok).status_code == 403  # the sites area is administrator-only
    sub = client.post(f"{V1}/plan/subscribe", headers=tok)  # Pro keeps access after the trial for this website id only
    assert sub.status_code == 200 and sub.json()["access"]["subscribed"] is True and sub.json()["access"]["source"] == "pro"
    access = client.get(f"{V1}/plan/access", headers=admin).json()
    assert any(x["host"] == HOST for x in access["trial_sites"])


def test_plan_upgrade_and_ingest_rules(client, api, ingest_headers):
    admin = api.as_("administrator")
    assert client.post(f"{V1}/plan", json={"plan": "premium"}, headers=admin).json()["plan"] == "premium"
    _hb(client, ingest_headers)
    evs = [_event(10 + i) for i in range(10)] + [_event(100 + i, "failed", "timeout") for i in range(3)] + [_event(200, typ="refund", amount=20)]
    r = client.post(f"{V1}/finance/events", headers=ingest_headers, json={"site_host": HOST, "events": evs})
    assert r.status_code == 200 and r.json()["accepted"] == 14
    assert client.post(f"{V1}/finance/events", headers=ingest_headers, json={"site_host": HOST, "events": evs}).json() == {"accepted": 0, "duplicates": 14, "capture": "running"}
    bad = {**_event(300), "card_number": "4242424242424242"}  # anything beyond the allowed fields is refused, never stored
    assert client.post(f"{V1}/finance/events", headers=ingest_headers, json={"site_host": HOST, "events": [bad]}).status_code == 422
    acct = _event(301, bank="0123456789012")  # a bank must be a label, never an account number
    assert client.post(f"{V1}/finance/events", headers=ingest_headers, json={"site_host": HOST, "events": [acct]}).status_code == 422
    s = client.get(f"{V1}/finance/summary?days=30", headers=admin).json()
    assert s["currency"] == "KES" and s["kpis"]["payments_failed"] == 3 and s["kpis"]["refunds"] == 20
    failed = client.get(f"{V1}/finance/transactions?status=failed", headers=api.as_("data_analyst")).json()["transactions"]
    assert len(failed) == 3 and all(t["retryable"] and t["currency"] == "KES" for t in failed)
    body = {"currency": "USD", "opening_balance": 500, "monthly_obligations": 100}
    assert client.put(f"{V1}/finance/settings", json=body, headers=api.as_("developer")).status_code == 403
    assert client.put(f"{V1}/finance/settings", json=body, headers=admin).json()["finance"]["currency"] == "KES"
    assert client.get(f"{V1}/finance/summary", headers=admin).json()["liquidity"]["opening_balance"] == 500
    assert client.get(f"{V1}/plan/access", headers=admin).json()["trial_sites"], "settings must not wipe the trial record"


def test_simulation_feeds_the_liquidity_suite(client, api):
    admin = api.as_("administrator")
    assert client.post(f"{V1}/finance/simulate?days=30", headers=admin).json()["simulated"] is True
    s = client.get(f"{V1}/finance/summary", headers=admin).json()
    assert s["simulated"] is True and s["forecast"]["ready"] is True
    L = client.get(f"{V1}/finance/liquidity", headers=admin).json()
    assert len(L["banks"]) >= 3 and {c["currency"] for c in L["currencies"]} >= {"KES", "USD"}
    assert [h["days"] for h in L["forecast"]["horizons"]] == [7, 14, 30, 60, 90] and len(L["stress"]) == 7
    assert L["working_capital"]["ar"]["balance"] > 0 and L["working_capital"]["ap"]["balance"] > 0 and L["working_capital"]["inventory"]["value"] > 0
    assert set(L["compliance"]) >= {"current_ratio", "quick_ratio", "lcr"}


def test_capture_controls_gate_ingestion_and_log_activity(client, api, ingest_headers):
    admin = api.as_("administrator")
    st = client.post(f"{V1}/finance/capture", json={"action": "start"}, headers=admin).json()
    assert st["state"] == "running" and st["syncing_until"] and st["sites"]
    assert any("started" in x["msg"] for x in st["logs"])
    assert client.post(f"{V1}/finance/capture", json={"action": "pause"}, headers=admin).json()["state"] == "paused"
    assert _hb(client, ingest_headers)["finance_capture"]["state"] == "paused"
    dropped = client.post(f"{V1}/finance/events", headers=ingest_headers, json={"site_host": HOST, "events": [_event(900)]}).json()
    assert dropped == {"accepted": 0, "duplicates": 0, "capture": "paused"}
    assert client.post(f"{V1}/finance/capture", json={"action": "stop"}, headers=admin).json()["state"] == "stopped"
    assert client.post(f"{V1}/finance/capture", json={"action": "restart"}, headers=admin).json()["state"] == "running"
    assert client.post(f"{V1}/finance/capture", json={"action": "start"}, headers=api.as_("developer")).status_code == 403


def test_sweeps_and_cents_ai(client, api):
    admin = api.as_("administrator")
    L = client.get(f"{V1}/finance/liquidity", headers=admin).json()
    src, dst = L["banks"][0]["bank"], L["banks"][-1]["bank"]
    rule = client.post(f"{V1}/finance/sweeps", json={"name": "Pool to main", "kind": "target_balance", "source_bank": src, "dest_bank": dst, "target_kes": 1000}, headers=admin).json()["rule"]
    assert client.get(f"{V1}/finance/sweeps", headers=admin).json()["rules"][0]["id"] == rule["id"]
    done = client.post(f"{V1}/finance/sweeps/run", headers=admin).json()["executed"]
    assert all(x["mode"] == "manual" for x in done)
    L2 = client.get(f"{V1}/finance/liquidity", headers=admin).json()
    assert len(L2["pooling"]["sweep_log"]) == len(done)
    assert client.delete(f"{V1}/finance/sweeps/{rule['id']}", headers=admin).status_code == 200
    summary = client.post(f"{V1}/finance/analyst/summary", headers=admin).json()
    assert summary["analyst"] == "Cents AI" and summary["provider"] == "rules" and summary["advice"] and summary["summary"]
    chat = client.post(f"{V1}/finance/analyst/chat", json={"message": "What is my liquidity coverage ratio?", "history": []}, headers=admin).json()
    assert chat["analyst"] == "Cents AI" and "ratio" in chat["reply"].lower()
    for role in ("developer", "data_analyst", "website_owner"):  # the weekly report is readable by every role
        rep = client.get(f"{V1}/finance/weekly-report", headers=api.as_(role))
        assert rep.status_code == 200 and rep.json()["currency"] == "KES" and rep.json()["required_actions"] and rep.json()["advice"], role


def test_scoped_sessions_only_see_their_own_website(client, api, ingest_headers):
    admin = api.as_("administrator")
    ev = {"event_id": "e_other_site_1", "session_id": "s_other_site", "event_type": "page_view", "page_route": "/", "site_host": "localhost"}
    client.post(f"{V1}/events", headers=ingest_headers, json={"events": [ev]})
    site = next(s for s in client.get(f"{V1}/sites", headers=admin).json()["sites"] if s["host"] == HOST)
    r = client.post(f"{V1}/sites/register", headers=ingest_headers, json={"site_host": HOST, "name": "Demo Shop", "owner_name": "Amina Otieno", "regenerate_password": True}).json()
    login = client.post(f"{V1}/auth/site-login", json={"website_id": r["website_id"], "password": r["password"], "role": "website_owner"}).json()
    tok = {"Authorization": f"Bearer {login['token']}"}
    mine = client.get(f"{V1}/events?limit=200", headers=tok).json()["events"]
    assert not any(e["session_id"] == "s_other_site" for e in mine)  # another website's session never appears
    m = client.get(f"{V1}/metrics", headers=tok).json()
    assert m["scope"]["site_host"] == HOST
    summary = client.get(f"{V1}/emails/summary", headers=tok).json()
    assert set(summary) >= {"sent_count", "draft_count", "auto_send", "recipients"}
    assert client.put(f"{V1}/emails/auto-send", json={"enabled": True, "delay_minutes": 5}, headers=tok).json()["enabled"] is True
    assert client.get(f"{V1}/emails/summary", headers=tok).json()["auto_send"]["enabled"] is True
    assert client.get(f"{V1}/emails/summary", headers=admin).json()["auto_send"]["enabled"] is False  # per-website setting
    assert site["website_id"] == r["website_id"]


def test_website_identity_generate_and_role_login(client, api, ingest_headers):
    admin = api.as_("administrator")
    r = client.post(f"{V1}/sites/register", headers=ingest_headers, json={"site_host": HOST, "name": "Demo Shop", "owner_name": "Amina Otieno", "regenerate_password": True}).json()
    assert r["website_id"].startswith("WS-") and r["password"] and r["name"] == "Demo Shop"
    site = next(s for s in client.get(f"{V1}/sites", headers=admin).json()["sites"] if s["host"] == HOST)
    assert site["website_id"] == r["website_id"] and site["owner_name"] == "Amina Otieno" and site["access_enabled"] is True
    cred = {"website_id": r["website_id"], "password": r["password"]}
    assert client.post(f"{V1}/auth/site-login", json={**cred, "role": "administrator"}).status_code == 403
    assert client.post(f"{V1}/auth/site-login", json={**cred, "role": "engineer"}).status_code == 422  # only the three site roles exist
    for role in ("data_analyst", "developer", "website_owner"):
        ok = client.post(f"{V1}/auth/site-login", json={**cred, "role": role})
        assert ok.status_code == 200 and ok.json()["user"]["role"] == role
    assert client.post(f"{V1}/auth/site-login", json={**cred, "password": "WRONG-WRONG-WRONG", "role": "developer"}).status_code == 401
    client.patch(f"{V1}/sites/{site['id']}", json={"access_enabled": False}, headers=admin)  # revoke: existing tokens die, new sign-ins refused
    tok = {"Authorization": f"Bearer {ok.json()['token']}"}
    assert client.get(f"{V1}/me", headers=tok).status_code == 401
    assert client.post(f"{V1}/auth/site-login", json={**cred, "role": "developer"}).status_code == 403


def test_digest_is_the_only_thing_that_runs_the_model_pass(client, api):
    admin = api.as_("administrator")
    client.post(f"{V1}/demo/simulate", json={"scenario": "checkout_failure", "sessions": 2}, headers=admin)
    hit = client.post(f"{V1}/rag/search", json={"query": "checkout payment timeouts"}, headers=admin).json()
    assert hit["reasoning"] is None  # Retrieve alone never calls the model
    d = client.post(f"{V1}/rag/digest", json={"retrieval_id": hit["id"]}, headers=admin)
    assert d.status_code == 200 and d.json()["reasoning"]["answer"] is not None and d.json()["id"] == hit["id"]
    assert client.post(f"{V1}/rag/digest", json={}, headers=admin).json()["reasoning"] is not None  # default question
