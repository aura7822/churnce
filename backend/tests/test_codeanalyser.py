import io
import zipfile

import pytest

from app import codeanalyser as ca

FILES = {
    "src/pages/Checkout.tsx": "import { PayButton } from '../components/PayButton';\nexport function Checkout(){ return <PayButton/> }\n",
    "src/components/PayButton.tsx": "import { charge } from '../lib/payments';\nexport function PayButton(){\n  return <button onClick={() => charge()}>Pay now</button>\n}\n",
    "src/lib/payments.ts": "export async function charge(){ const r = await fetch('/api/pay'); return r.json() }\n",
    "src/pages/Home.tsx": "export function Home(){ return <h1>Home</h1> }\n",
    "tests/payments.test.ts": "import { charge } from '../src/lib/payments';\n",
}


def test_locates_origin_and_blast_radius():
    bug = {"title": "Repeated clicks on Pay now button at checkout", "signal": "rage_click", "routes": ["/checkout"], "facts": ["user clicked 'Pay now' 6 times"]}
    r = ca.analyse(FILES, bug)
    top = r["candidates"][0]
    assert top["path"] == "src/components/PayButton.tsx" and top["confidence"] == 100 and r["signals"]["kind"] == "click"
    b = top["blast"]
    assert b["affected"] == 1 and "src/pages/Checkout.tsx" in b["entry_points"]
    pay = ca.blast_radius(ca.build_index(FILES), "src/lib/payments.ts")
    assert pay["affected"] == 3 and pay["tests"] == ["tests/payments.test.ts"]
    assert any(i["rule"] == "click-without-guard" for i in r["related_issues"]) and r["what_if"]


def test_zip_reading_is_safe():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("repo-main/src/a.js", "export const a = 1;")
        z.writestr("repo-main/node_modules/x/index.js", "x")
        z.writestr("repo-main/../evil.js", "bad")
        z.writestr("repo-main/logo.png", "binary")
    files = ca.read_zip(buf.getvalue())
    assert list(files) == ["src/a.js"]
    with pytest.raises(ca.UnsafeArchive):
        ca.read_zip(b"not a zip")
