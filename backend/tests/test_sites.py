"""Connected sites, role assignment, one-time dashboard access, feeds, series and documentation feedback."""
V1 = "/api/v1"


def _site(client, api):
    admin = api.as_("administrator")
    client.post(f"{V1}/demo/simulate", json={"scenario": "checkout_failure", "sessions": 2}, headers=admin)
    sites = client.get(f"{V1}/sites", headers=admin).json()["sites"]
    return admin, sites


def test_simulated_traffic_registers_sites_and_series(client, api):
    admin, sites = _site(client, api)
    assert sites, "simulated journeys must register a connected site"
    series = client.get(f"{V1}/sites-series?minutes=15", headers=admin).json()
    assert len(series["buckets"]) == 60 and any(s["total"] > 0 for s in series["series"])
    ts = client.get(f"{V1}/timeseries?hours=24", headers=admin).json()
    assert sum(ts["events"]) > 0 and ts["event_types"]


def test_role_assignment_and_one_time_access(client, api):
    admin, sites = _site(client, api)
    s = sites[0]
    r = client.patch(f"{V1}/sites/{s['id']}", json={"role": "developer"}, headers=admin)
    assert r.status_code == 200 and r.json()["role"] == "developer"
    code = client.post(f"{V1}/sites/access", json={"site_host": s["host"]}, headers=admin).json()["code"]
    ok = client.post(f"{V1}/auth/site-access", json={"code": code})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "developer" and ok.json()["scope"]["site_host"] == s["host"]
    assert client.post(f"{V1}/auth/site-access", json={"code": code}).status_code == 401  # single use
    guest = {"Authorization": f"Bearer {ok.json()['token']}"}
    denied = client.get(f"{V1}/logs", headers=guest)  # a website-ID session never sees server logs: custom 403
    assert denied.status_code == 403 and denied.json()["code"] == "site_scope"
    assert client.get(f"{V1}/sites/{s['id']}/feed", headers=guest).status_code in (200, 403)
    assert client.patch(f"{V1}/sites/{s['id']}", json={"role": "administrator"}, headers=guest).status_code == 403
    client.patch(f"{V1}/sites/{s['id']}", json={"access_enabled": False}, headers=admin)
    assert client.get(f"{V1}/me", headers=guest).status_code == 401  # revoked at once


def test_only_admins_assign_roles_and_feed_is_scoped(client, api):
    admin, sites = _site(client, api)
    s = sites[0]
    assert client.patch(f"{V1}/sites/{s['id']}", json={"role": "data_analyst"}, headers=api.as_("developer")).status_code == 403
    feed = client.get(f"{V1}/sites/{s['id']}/feed", headers=api.as_("developer")).json()
    assert any(r["kind"] == "activity" for r in feed["rows"])
    assert client.get(f"{V1}/sites/{s['id']}/feed", headers=api.as_("website_owner")).status_code == 403


def test_doc_feedback_roundtrip(client, api):
    h = api.as_("data_analyst")
    assert client.post(f"{V1}/docs/feedback", json={"rating": 6}, headers=h).status_code == 422
    assert client.post(f"{V1}/docs/feedback", json={"rating": 4, "comment": "Clear"}, headers=h).status_code == 201
    out = client.get(f"{V1}/docs/feedback", headers=h).json()
    assert out["count"] >= 1 and out["distribution"]["4"] >= 1
