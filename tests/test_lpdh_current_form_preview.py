"""Read-only current-form previews; synthetic data, never a production database."""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
import test_generated_document_api as fixture
from backend import lpdh_api as api


class CurrentFormPreviewTests(unittest.TestCase):
    def setUp(self):
        self.stored = {"status": "DRAFT", "data": {"pm": {"rows": [{"code": "KS-07", "distributed": 0, "received": 0, "bnba": "Tidak"}], "production": {"produced": 99}}}}
        self.masters = {"posyandu": [{"balitaSmall": 20, "pregnantLarge": 5, "breastfeedingLarge": 7}]}
        self.reads = []
        @contextmanager
        def connection():
            self.reads.append(True)
            yield self
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {"connection": connection, "_load_master": lambda site: {"data": deepcopy(self.masters)},
            "_load_daily": lambda site, day: deepcopy(self.stored), "_load_final_plan": lambda site, day: None,
            "_daily_with_hpe": lambda site, day, daily: (daily, {"effective": True})}.items():
            self.stack.enter_context(patch.object(api, name, value))
        self.stack.enter_context(patch.object(fixture.api, "load_documents", return_value=[]))
        app = FastAPI()
        @app.middleware("http")
        async def authenticated(request, call_next):
            request.state.sppg_role = request.headers.get("x-test-role", "")
            return await call_next(request)
        app.include_router(api.router)
        self.client = TestClient(app)

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, *args):
        raise AssertionError("Preview must never execute a mutation or claim a number")

    def post(self, data, site="MAJA", role="MAJA"):
        return self.client.post("/v1/lpdh/preview", json={"site": site, "service_date": "2026-10-05", "data": data}, headers={"x-test-role": role})

    def test_unsaved_counts_bnba_and_production_without_persistence(self):
        original = deepcopy(self.stored)
        incoming = {"pm": {"rows": [{"code": "KS-07", "distributed": 4, "received": 3, "bnba": "Ya"}], "production": {"produced": 40}}}
        response = self.post(incoming)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        row = next(x for x in result["pmRows"] if x["code"] == "KS-07")
        self.assertEqual((row["targetPm"], row["distributed"], row["received"], row["bnba"]), (5, 4, 3, "Ya"))
        self.assertEqual(result["production"]["produced"], 40)
        self.assertEqual(result["previewSource"], "CURRENT_FORM")
        self.assertEqual(self.stored, original)
        self.assertTrue(self.reads)

    def test_master_changes_and_forged_history_marker(self):
        response = self.post({"_historicalGeneratedSnapshot": True, "pm": {"rows": [{"code": "KS-07", "targetPm": 999}]}})
        row = next(x for x in response.json()["pmRows"] if x["code"] == "KS-07")
        self.assertEqual(row["targetPm"], 5)
        self.masters["posyandu"][0]["pregnantLarge"] = 8
        self.assertEqual(next(x for x in self.post({}).json()["pmRows"] if x["code"] == "KS-07")["targetPm"], 8)

    def test_financial_source_guard_and_canonical_rebuild(self):
        self.assertEqual(self.post({"operations": [{"description": "Injected", "qty": 1, "price": 100}]}).status_code, 409)
        result = self.post({"operations": [{"sourceDocumentId": 999, "qty": 1, "price": 100}]}).json()
        self.assertEqual(result["operationalTotal"], 0)

    def test_site_authorization(self):
        self.assertEqual(self.post({}, site="CEMPLANG").status_code, 403)
        self.assertEqual(self.post({}, role="").status_code, 403)
        self.assertEqual(self.post({}, site="CEMPLANG", role="OWNER").status_code, 200)

    def test_historical_targets_preserved(self):
        self.stored["status"] = "GENERATED"
        self.stored["data"]["pm"]["rows"][0]["targetPm"] = 42
        result = self.post(deepcopy(self.stored["data"])).json()
        self.assertEqual(next(x for x in result["pmRows"] if x["code"] == "KS-07")["targetPm"], 42)


if __name__ == "__main__":
    unittest.main()
