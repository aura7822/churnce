"""Backend logs endpoint, redaction, role gating, and Neon URL handling."""
import logging
from pathlib import Path

from app.config import Settings
from app.logbuf import handler, redact

V1 = "/api/v1"


def test_logs_endpoint_returns_lines_and_indicators(client, api):
    logging.getLogger("churnce.test").warning("probe warning for the logs page")
    logging.getLogger("churnce.test").error("probe error for the logs page")
    admin = api.as_("administrator")
    r = client.get(f"{V1}/logs?level=WARNING", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    msgs = [x["message"] for x in body["logs"]]
    assert any("probe warning" in m for m in msgs) and any("probe error" in m for m in msgs)
    ind = body["indicators"]
    assert ind["database"]["ok"] is True and ind["database"]["latency_ms"] >= 0
    assert "scheduler" in ind and ind["errors_5m"] >= 1
    # Incremental polling: nothing newer than the last id except what the poll itself logged.
    last = body["logs"][-1]["id"]
    again = client.get(f"{V1}/logs?after={last}&level=ERROR", headers=admin).json()
    assert all(x["id"] > last for x in again["logs"])


def test_logs_are_restricted(client, api):
    assert client.get(f"{V1}/logs", headers=api.as_("reviewer")).status_code == 403
    assert client.get(f"{V1}/logs", headers=api.as_("marketing_operator")).status_code == 403
    assert client.get(f"{V1}/logs", headers=api.as_("engineer")).status_code == 200


def test_secrets_are_masked_before_storage():
    assert "hunter2" not in redact("connect postgresql://app:hunter2@ep-1.neon.tech/db")
    assert "abc.def" not in redact("Authorization: Bearer abc.def.ghi")
    logging.getLogger("churnce.test").info("password=hunter2 token: sekret")
    stored = " ".join(r["message"] for r in handler.since(0, "INFO", 1000))
    assert "hunter2" not in stored and "sekret" not in stored


def test_neon_urls_are_normalised():
    s = Settings(database_url="postgres://u:p@ep-cool-123-pooler.eu-central-1.aws.neon.tech/neondb", _env_file=None)
    assert s.sqlalchemy_url.startswith("postgresql+psycopg://")
    assert "sslmode=require" in s.sqlalchemy_url
    assert s.is_neon and s.uses_pooler
    direct = Settings(database_url="postgresql://u:p@ep-cool-123.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require", _env_file=None)
    assert not direct.uses_pooler and "channel_binding=require" in direct.sqlalchemy_url
    assert Settings(database_url="sqlite:///./x.db", _env_file=None).sqlalchemy_url == "sqlite:///./x.db"


def test_project_root_env_is_loaded_even_from_backend_dir(monkeypatch):
    project_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(project_root / "backend")
    for key in ["APP_ENV", "DATABASE_URL", "DATABASE_URL_DIRECT", "JWT_SECRET", "SEED_DEMO"]:
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=str(project_root / ".env"))
    assert s.is_neon is True
    assert s.is_sqlite is False
    assert s.db_host.endswith("neon.tech")


def test_remote_postgres_without_tls_is_refused_in_production():
    s = Settings(app_env="production", seed_demo=False, jwt_secret="x" * 48, database_url="postgresql://u:p@db.example.com/app", _env_file=None)
    assert any("TLS" in p for p in s.production_problems())
    ok = Settings(app_env="production", seed_demo=False, jwt_secret="x" * 48, database_url="postgresql://u:p@db.example.com/app?sslmode=require", _env_file=None)
    assert not ok.production_problems()
