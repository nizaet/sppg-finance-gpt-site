from datetime import date

from backend.menu_planning_advisor_api import _preview_response, router


def test_menu_advisor_exposes_only_read_only_preview_route():
    methods = {
        method
        for route in router.routes
        for method in getattr(route, "methods", set())
        if method not in {"HEAD", "OPTIONS"}
    }

    assert methods == {"GET"}


def test_preview_keeps_draft_boundary_and_reports_missing_evidence():
    response = _preview_response(
        site="MAJA",
        requested_date=date(2026, 8, 24),
        target_snapshot={"id": 91, "site": "MAJA", "status": "ACTIVE"},
        target_items=[{"item_name": "Ayam", "planned_qty": None, "planning_price": None}],
        history=[],
        confirmed_knowledge=[],
        database_ready=True,
    )

    assert response["readOnly"] is True
    assert response["draftOnly"] is True
    assert response["automationBoundary"]["canCreateOrEditCalculator"] is False
    assert response["automationBoundary"]["canCreateOrEditPurchaseOrder"] is False
    assert {gap["code"] for gap in response["dataGaps"]} == {
        "PLANNED_QTY_MISSING",
        "PLANNING_PRICE_MISSING",
        "CONFIRMED_MENU_KNOWLEDGE_EMPTY",
    }


def test_preview_reports_missing_target_snapshot_without_inventing_a_menu():
    response = _preview_response(
        site="CEMPLANG",
        requested_date=date(2026, 8, 25),
        target_snapshot=None,
        target_items=[],
        history=[],
        confirmed_knowledge=[],
        database_ready=True,
    )

    assert response["targetPlanning"] is None
    assert response["dataGaps"][0]["code"] == "PLANNING_NOT_FOUND"
    assert "menu" not in response["targetPlanning"] if response["targetPlanning"] else True
