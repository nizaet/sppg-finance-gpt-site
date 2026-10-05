"""Isolated API contract tests; no production database or session is used."""
import base64
import importlib.util
import json
import sys
import types
import unittest
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("backend")
package.__path__ = [str(ROOT / "backend")]


def session_role(token):
    if token not in {"Bearer MAJA", "Bearer CEMPLANG", "Bearer OWNER"}:
        raise HTTPException(401, "unauthorized")
    return token.split()[1]


auth = types.ModuleType("backend.auth_api")
auth.session_role = session_role
db = types.ModuleType("backend.db")
db.connection = lambda: None
db.database_ready = lambda: True
# Run this test file in its own process: importing backend/__init__ would load
# unrelated services, so install only the package and authentication/DB fixtures.
sys.modules.update({"backend": package, "backend.auth_api": auth, "backend.db": db})
spec = importlib.util.spec_from_file_location("backend.accountant_generated_document_api", ROOT / "backend/accountant_generated_document_api.py")
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)
pdf_spec = importlib.util.spec_from_file_location("backend.generated_document_pdf", ROOT / "backend/generated_document_pdf.py")
pdf_module = importlib.util.module_from_spec(pdf_spec)
sys.modules[pdf_spec.name] = pdf_module
pdf_spec.loader.exec_module(pdf_module)


class FakeConnection:
    def __init__(self):
        self.committed = False
        self.calls = []
        self.row = {"id": 1, "site": "MAJA", "document_type": "OPERASIONAL", "document_number": "INV-OPS-MAJA-20261005-001", "service_date": date(2026, 10, 5), "status": "DRAFT", "header_payload": {"issuerName": "Penerbit", "recipientName": "Dapur", "recipientAddress": "Alamat", "senderSignatory": "Pengirim"}, "total_amount": 1000}
        self.items = [{"item_name": "Gas", "category_code": "Gas", "quantity": 1, "unit": "tabung", "unit_price": 1000, "line_total": 1000, "item_payload": {}}]
        self.result = None

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if sql.startswith("select * from generated_accountant_documents where id"):
            self.result = deepcopy(self.row) if params[0] == 1 else None
        elif sql.startswith("select * from generated_accountant_documents where request_key"):
            self.result = deepcopy(self.row) if self.row.get("request_key") == params[0] else None
        elif sql.startswith("select item_name"):
            self.result = deepcopy(self.items)
        elif sql.startswith("select count(*)"):
            self.result = {"n": 1}
        elif sql.startswith("insert into generated_accountant_documents"):
            self.row.update(site=params[0], document_type=params[1], document_number=params[2], service_date=params[3], header_payload=json.loads(params[4]), total_amount=params[5], request_key=params[6], request_hash=params[7])
            self.items = []
            self.result = deepcopy(self.row)
        elif "insert into generated_accountant_document_items" in sql:
            self.items.append(dict(zip(("document_id", "item_name", "category_code", "quantity", "unit", "unit_price", "line_total", "item_payload"), params)))
            self.items[-1]["item_payload"] = json.loads(params[-1])
        elif sql.startswith("update generated_accountant_documents set status"):
            self.row["status"] = "FINAL"

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result

    def commit(self):
        self.committed = True


class DocumentApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(api.router, prefix="/v1")
        self.client = TestClient(app)
        self.conn = FakeConnection()
        @contextmanager
        def connection():
            original = deepcopy(self.conn.row)
            try:
                yield self.conn
            finally:
                if not self.conn.committed:
                    self.conn.row = original
        self.patcher = patch.object(api, "connection", connection)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.headers = {"Authorization": "Bearer MAJA"}
        self.payload = {"site": "MAJA", "document_type": "OPERASIONAL", "service_date": "2026-10-05", "header_payload": self.conn.row["header_payload"], "request_key": "test-request-001", "items": [{"item_name": "Gas", "category_code": "Gas", "quantity": 1, "unit": "tabung", "unit_price": 1000}]}

    def test_authentication_and_site_scope(self):
        self.assertEqual(self.client.post("/v1/accountant-documents", json=self.payload).status_code, 401)
        for action in ("finalize", "pdf"):
            response = self.client.request("PATCH" if action == "finalize" else "GET", f"/v1/accountant-documents/1/{action}", headers={"Authorization": "Bearer CEMPLANG"})
            self.assertEqual(response.status_code, 403)
        self.assertFalse(self.conn.committed)

    def test_reject_weekly_wages_and_invalid_category(self):
        for change in ({"document_type": "UPAH_RELAWAN", "quantity": 5, "unit": "hari"}, {"category_code": "Upah relawan"}, {"unit_price": 1.001}):
            payload = deepcopy(self.payload)
            if "document_type" in change:
                payload["document_type"] = change.pop("document_type")
            payload["items"][0].update(change)
            self.assertEqual(self.client.post("/v1/accountant-documents", json=payload, headers=self.headers).status_code, 422)
        self.assertEqual(self.conn.calls, [])

    def test_create_is_idempotent_and_conflicting_retry_rejected(self):
        first = self.client.post("/v1/accountant-documents", json=self.payload, headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()["document"]["documentNumber"].endswith("002"))
        second = self.client.post("/v1/accountant-documents", json=self.payload, headers=self.headers)
        self.assertEqual(first.json()["document"], second.json()["document"])
        self.payload["items"][0]["unit_price"] = 2000
        self.assertEqual(self.client.post("/v1/accountant-documents", json=self.payload, headers=self.headers).status_code, 409)

    def test_finalization_import_failure_rolls_back(self):
        with patch.object(api, "_sync_daily", side_effect=HTTPException(409, "duplicate daily payment")):
            response = self.client.patch("/v1/accountant-documents/1/finalize", headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.conn.committed)
        self.assertEqual(self.conn.row["status"], "DRAFT")

    def test_finalization_commits_document_and_daily_together(self):
        with patch.object(api, "_sync_daily", return_value={"data": {"operations": []}, "imported": 1}) as sync:
            response = self.client.patch("/v1/accountant-documents/1/finalize", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["syncedToDaily"])
        self.assertTrue(self.conn.committed)
        sync.assert_called_once_with(self.conn, "MAJA", date(2026, 10, 5), "MAJA")

    def test_final_is_immutable(self):
        self.conn.row["status"] = "FINAL"
        self.assertEqual(self.client.put("/v1/accountant-documents/1", json=self.payload, headers=self.headers).status_code, 409)
        self.assertFalse(self.conn.committed)

    def test_authenticated_download_returns_real_pdf(self):
        with patch.dict(sys.modules, {"backend.generated_document_pdf": pdf_module}):
            response = self.client.get("/v1/accountant-documents/1/pdf", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(base64.b64decode(response.json()["contentBase64"]).startswith(b"%PDF-"))

    def test_generated_daily_rejects_changed_final_documents(self):
        self.conn.result = {"data": {}, "status": "GENERATED"}
        doc = {"id": 1, "site": "MAJA", "documentType": "OPERASIONAL", "documentNumber": "INV-1", "serviceDate": "2026-10-05", "status": "FINAL", "header": {}, "items": [{"itemName": "Gas", "category": "Gas", "quantity": 1, "unit": "tabung", "unitPrice": 1000, "lineTotal": 1000, "metadata": {}}]}
        with patch.object(api, "load_documents", return_value=[doc]):
            with self.assertRaises(HTTPException) as exc:
                api._sync_daily(self.conn, "MAJA", date(2026, 10, 5), "MAJA")
        self.assertEqual(exc.exception.status_code, 409)
        self.assertTrue(any("pg_advisory_xact_lock" in sql for sql, _ in self.conn.calls))


if __name__ == "__main__":
    unittest.main()
