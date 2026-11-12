"""Codebase analyser (Pro): zip upload, description-driven analysis, project listing and deletion, role and plan gating."""
import io
import zipfile

V1 = "/api/v1"


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("shop/src/pages/Checkout.tsx", "import { PayButton } from '../components/PayButton';\nexport const Checkout = () => <PayButton />;\n")
        z.writestr("shop/src/components/PayButton.tsx", "export const PayButton = () => <button onClick={() => fetch('/api/pay')}>Pay now</button>;\n")
    return buf.getvalue()


def test_admin_uploads_zip_and_analyses_a_description(client, api):
    admin = api.as_("administrator")
    up = client.post(f"{V1}/analyser/projects/zip?name=Shop", content=_zip(), headers={**admin, "Content-Type": "application/zip"})
    assert up.status_code == 201 and up.json()["files"] == 2
    pid = up.json()["id"]
    assert [x["id"] for x in client.get(f"{V1}/analyser/projects", headers=admin).json()["projects"]] == [pid]
    r = client.post(f"{V1}/analyser/projects/{pid}/analyse", json={"description": "Repeated clicks on the Pay now button at checkout"}, headers=admin)
    assert r.status_code == 200 and r.json()["candidates"][0]["path"].endswith("PayButton.tsx") and r.json()["what_if"]
    assert client.post(f"{V1}/analyser/projects/{pid}/analyse", json={"description": "x"}, headers=admin).status_code == 422
    assert client.post(f"{V1}/analyser/projects/zip", content=b"not a zip", headers={**admin, "Content-Type": "application/zip"}).status_code == 422
    assert client.delete(f"{V1}/analyser/projects/{pid}", headers=admin).status_code == 200

