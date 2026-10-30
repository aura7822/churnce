import os
import tempfile
import time
from pathlib import Path

import pytest

# Configure BEFORE the app is imported: settings are read once at import time.
_tmp = tempfile.mkdtemp(prefix="churnce-test-")
os.environ.update(
    DATABASE_URL=f"sqlite:///{Path(_tmp) / 'test.db'}",
    SEED_DEMO="true",
    REVIEW_SECONDS="1",
    SCHEDULER_TICK_SECONDS="0.2",
    CHUNK_IDLE_SECONDS="2",
    LLM_PROVIDER="rules",
    EMBEDDING_PROVIDER="local",
    RERANK_PROVIDER="lexical",
    JWT_SECRET="test-secret-test-secret-test-secret-123",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.seed import DEMO_INGEST_KEY, DEMO_PASSWORD  # noqa: E402


class Api:
    def __init__(self, client: TestClient) -> None:
        self.c = client
        self._tokens: dict[str, str] = {}

    def login(self, email: str, password: str = DEMO_PASSWORD) -> dict:
        if email not in self._tokens:
            r = self.c.post("/api/v1/auth/login", json={"email": email, "password": password})
            assert r.status_code == 200, r.text
            self._tokens[email] = r.json()["token"]
        return {"Authorization": f"Bearer {self._tokens[email]}"}

    def as_(self, role: str) -> dict:
        return self.login(f"{role}@churnce.demo")


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:  # runs lifespan: DB init, seeding, scheduler thread
        yield c


@pytest.fixture(scope="session")
def api(client):
    return Api(client)


@pytest.fixture(scope="session")
def ingest_headers():
    return {"X-Churnce-Key": DEMO_INGEST_KEY}


def wait_until(fn, timeout: float = 25.0, interval: float = 0.25, message: str = "condition not met"):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"{message} (last value: {last!r})")
