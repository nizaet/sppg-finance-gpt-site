from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected 1 anchor, found {count}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    a = text.find(start)
    if a < 0:
        raise SystemExit(f"{path}: start anchor not found: {start!r}")
    b = text.find(end, a)
    if b < 0:
        raise SystemExit(f"{path}: end anchor not found: {end!r}")
    p.write_text(text[:a] + replacement + text[b:], encoding="utf-8")


# ---------------------------------------------------------------------------
# v4: expose exact item-level PO facts. The engine already matches exact
# distribution date + stock type + unit; we only make those facts explicit.
# ---------------------------------------------------------------------------
replace_once(
    "backend/po_reminder_v4_api.py",
    '''    return {\n        "stage": stage,\n        "action_po": action_po,\n        "contributors": [po for po, _ in rows],\n        "covered_qty": round(total_qty, 4),\n        "remaining_qty": max(0.0, round(recommended - total_qty, 4)),\n    }''',
    '''    latest_completed_po = _latest_po([po for po, _ in done_rows])\n    return {\n        "stage": stage,\n        "action_po": action_po,\n        "contributors": [po for po, _ in rows],\n        "covered_qty": round(total_qty, 4),\n        "completed_qty": round(done_qty, 4),\n        "finalized_qty": round(finalized_qty, 4),\n        "draft_qty": round(draft_qty, 4),\n        "latest_completed_po": latest_completed_po,\n        "remaining_qty": max(0.0, round(recommended - total_qty, 4)),\n    }''',
)

replace_once(
    "backend/po_reminder_v4_api.py",
    '''            requirement_details.append({\n                "distribution_date": req["distribution_date"],''',
    '''            latest_completed_po = coverage.get("latest_completed_po") or {}\n            if coverage["remaining_qty"] <= EPSILON:\n                ordering_state = "COVERED"\n            elif coverage.get("completed_qty", 0.0) > EPSILON:\n                ordering_state = "ORDERED_PARTIAL"\n            elif coverage.get("covered_qty", 0.0) > EPSILON:\n                ordering_state = "IN_APP_PARTIAL"\n            else:\n                ordering_state = "NOT_ORDERED"\n\n            requirement_details.append({\n                "distribution_date": req["distribution_date"],''',
)

replace_once(
    "backend/po_reminder_v4_api.py",
    '''                "covered_po_qty": coverage["covered_qty"],\n                "remaining_po_qty": coverage["remaining_qty"],\n                "coverage_stage": coverage["stage"],''',
    '''                "covered_po_qty": coverage["covered_qty"],\n                "completed_po_qty": coverage.get("completed_qty", 0.0),\n                "finalized_po_qty": coverage.get("finalized_qty", 0.0),\n                "draft_po_qty": coverage.get("draft_qty", 0.0),\n                "remaining_po_qty": coverage["remaining_qty"],\n                "coverage_stage": coverage["stage"],\n                "ordering_state": ordering_state,\n                "completed_purchase_order_id": latest_completed_po.get("id"),\n                "completed_po_code": latest_completed_po.get("po_code"),\n                "completed_po_status": latest_completed_po.get("status"),\n                "completed_po_created_at": latest_completed_po.get("created_at"),\n                "completed_po_sent_at": latest_completed_po.get("sent_at"),''',
)

# ---------------------------------------------------------------------------
# Completed shortage compatibility: classify using exact requirement coverage,
# never merely because some PO exists for the same vendor/date.
# ---------------------------------------------------------------------------
new_completed_semantics = r'''def _effective_completed_qty(detail: dict[str, Any]) -> float:
    return max(
        0.0,
        float(detail.get("completed_po_qty") or 0.0),
        float(detail.get("batch_completed_po_qty") or 0.0),
    )


def _detail_ordering_state(detail: dict[str, Any]) -> str:
    remaining = max(0.0, float(detail.get("remaining_po_qty") or 0.0))
    if remaining <= EPSILON:
        return "COVERED"
    completed = _effective_completed_qty(detail)
    if completed > EPSILON:
        return "ORDERED_PARTIAL"
    covered = max(0.0, float(detail.get("covered_po_qty") or 0.0))
    if covered > EPSILON:
        return "IN_APP_PARTIAL"
    return "NOT_ORDERED"


def _detail_names(details: list[dict[str, Any]], state: str) -> list[str]:
    return sorted({
        str(name).strip()
        for detail in details
        if str(detail.get("ordering_state") or "").upper() == state
        for name in (detail.get("item_names") or [])
        if str(name).strip()
    })


def _latest_exact_completed_po(details: list[dict[str, Any]]) -> dict[str, Any] | None:
    rows: list[dict[str, Any]] = []
    for detail in details:
        po_id = detail.get("completed_purchase_order_id")
        if not po_id:
            continue
        rows.append({
            "id": po_id,
            "po_code": detail.get("completed_po_code"),
            "status": detail.get("completed_po_status"),
            "created_at": detail.get("completed_po_created_at"),
            "sent_at": detail.get("completed_po_sent_at"),
            "revision_no": 0,
        })
    return _latest_po(rows)


def apply_completed_po_shortage_semantics(
    payload: dict[str, Any],
    completed_lookup: dict[tuple[str, str, date], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Separate "not ordered" from residual qty after an exact completed PO.

    v4 already knows exact date + item type + unit coverage. We must use those
    item-level facts. A KOPERASI PO containing 12 other lines must never make an
    un-ordered Kecap/Telur/Tepung requirement look like an already-done PO.
    """
    del completed_lookup  # legacy argument retained only for call compatibility
    items = payload.get("items") or []
    changed = False
    shortage_count = 0
    enriched_items: list[dict[str, Any]] = []

    for original in items:
        item = dict(original)
        status = str(item.get("reminder_status") or "").upper()
        details = [dict(detail) for detail in (item.get("requirement_details") or [])]
        open_details: list[dict[str, Any]] = []
        for detail in details:
            detail["ordering_state"] = _detail_ordering_state(detail)
            if float(detail.get("remaining_po_qty") or 0.0) > EPSILON:
                open_details.append(detail)
        item["requirement_details"] = details

        if open_details:
            item["not_ordered_item_names"] = _detail_names(open_details, "NOT_ORDERED")
            item["partial_shortage_item_names"] = _detail_names(open_details, "ORDERED_PARTIAL")
            item["in_app_partial_item_names"] = _detail_names(open_details, "IN_APP_PARTIAL")
            item["not_ordered_count"] = sum(1 for d in open_details if d["ordering_state"] == "NOT_ORDERED")
            item["partial_shortage_count"] = sum(1 for d in open_details if d["ordering_state"] == "ORDERED_PARTIAL")
            item["in_app_partial_count"] = sum(1 for d in open_details if d["ordering_state"] == "IN_APP_PARTIAL")
            changed = True

        if status in SHORTAGE_REMINDER_STATUSES and open_details:
            # Only move the row out of the ordering queue when EVERY remaining
            # requirement has actually appeared in a completed/SENT PO.
            all_completed_partial = all(d["ordering_state"] == "ORDERED_PARTIAL" for d in open_details)
            if all_completed_partial:
                exact_po = _latest_exact_completed_po(open_details)
                # WIKIAN FIFO reconciliation already writes exact parent PO data.
                if exact_po:
                    item.update({
                        "purchase_order_id": exact_po.get("id"),
                        "po_code": exact_po.get("po_code"),
                        "po_status": exact_po.get("status"),
                        "po_created_at": exact_po.get("created_at"),
                        "po_sent_at": exact_po.get("sent_at"),
                    })
                item.update({
                    "po_workflow_status": "DONE",
                    "po_already_done": True,
                    "shortage_only": True,
                    "shortage_reminder_status": status,
                    "reminder_status": "SHORTAGE_REVIEW",
                    "shortage_item_names": sorted({
                        str(name).strip()
                        for detail in open_details
                        for name in (detail.get("item_names") or [])
                        if str(name).strip()
                    }),
                    "shortage_distribution_dates": sorted({
                        value
                        for value in (_as_date(detail.get("distribution_date")) for detail in open_details)
                        if value is not None
                    }),
                    "shortage_qty_total": round(sum(float(d.get("remaining_po_qty") or 0.0) for d in open_details), 4),
                    "ordering_state_summary": "ORDERED_PARTIAL",
                    "reminder_message": (
                        "Item ini sudah pernah masuk PO yang selesai/SENT, tetapi qty masih kurang. "
                        "Pilih Buat PO Tambahan, Konfirmasi stok gudang, atau Sudah dicek / biarkan."
                    ),
                })
                shortage_count += 1
            else:
                item["shortage_only"] = False
                item["ordering_state_summary"] = "NEEDS_ORDERING"
                if item.get("not_ordered_count"):
                    item["reminder_message"] = (
                        "Masih ada item yang belum pernah dipesan pada PO untuk tanggal distribusi ini. "
                        "Pilih Buat PO, PO sudah dilakukan, atau Konfirmasi stok gudang."
                    )

        enriched_items.append(item)

    if not changed:
        return payload
    result = dict(payload)
    result["items"] = enriched_items
    result["shortageAfterCompletedPoCount"] = shortage_count
    return _recount_ordering(result)


'''
replace_between(
    "backend/po_reminder_completed_shortage.py",
    "def apply_completed_po_shortage_semantics(\n",
    "def enrich_completed_po_shortages(",
    new_completed_semantics,
)
replace_between(
    "backend/po_reminder_completed_shortage.py",
    "def enrich_completed_po_shortages(",
    "\n",
    '''def enrich_completed_po_shortages(payload: dict[str, Any], site: str) -> dict[str, Any]:\n    # `site` is retained in the public compatibility signature. Exact coverage\n    # facts are now already present in v4 requirement_details, so no broad\n    # vendor/date PO lookup is needed here.\n    del site\n    return apply_completed_po_shortage_semantics(payload)\n''',
)

# ---------------------------------------------------------------------------
# UI: overdue/today gets the three operator actions requested. A completed PO
# with residual qty can still create an additional PO and/or confirm stock.
# ---------------------------------------------------------------------------
replace_once(
    "src/operations/OperationsPoPlanner.jsx",
    '''            const actionableShortage = ["OVERDUE", "DUE_TODAY"].includes(String(item.reminder_status || "").toUpperCase()) && remaining > 0;''',
    '''            const reminderStatus = String(item.reminder_status || "").toUpperCase();\n            const orderingAction = ["OVERDUE", "DUE_TODAY"].includes(reminderStatus) && remaining > 0;\n            const residualReview = reminderStatus === "SHORTAGE_REVIEW" && remaining > 0;\n            const canCreatePo = orderingAction || residualReview;\n            const canConfirmStock = ["OVERDUE", "DUE_TODAY", "SHORTAGE_REVIEW"].includes(reminderStatus) && remaining > 0;\n            const canConfirmManualPo = ["OVERDUE", "DUE_TODAY"].includes(reminderStatus) && Boolean(item.reminder_key);''',
)

replace_once(
    "src/operations/OperationsPoPlanner.jsx",
    '''              <td><strong>{names.length || item.item_count || 0}</strong>{names.length > 0 && <div className="ops-muted ops-item-list">{names.join(", ")}</div>}{remaining > 0 && <div className="ops-shortage-qty">Sisa qty: {qty(remaining)} <small>(unit mengikuti item)</small></div>}</td>''',
    '''              <td><strong>{names.length || item.item_count || 0}</strong>\n                {(item.requirement_details || []).filter((detail) => Number(detail.remaining_po_qty || 0) > 0).map((detail, detailIndex) => {\n                  const state = String(detail.ordering_state || "NOT_ORDERED").toUpperCase();\n                  const stateLabel = state === "ORDERED_PARTIAL" ? "SUDAH DIPESAN · SISA" : state === "IN_APP_PARTIAL" ? "PO APLIKASI BELUM CUKUP" : "BELUM DIPESAN";\n                  return <div className="ops-muted ops-item-list" key={`${detail.distribution_date || "date"}-${detail.stock_type_code || detailIndex}-${detailIndex}`}><strong>{(detail.item_names || []).join(", ") || detail.stock_type_code || "Item"}</strong> · <span className={`ops-reminder-pill ${state === "ORDERED_PARTIAL" ? "ops-pill-amber" : "ops-pill-red"}`}>{stateLabel}</span> · sisa {qty(detail.remaining_po_qty)} {detail.unit || ""}</div>;\n                })}\n                {remaining > 0 && <div className="ops-shortage-qty">Total sisa: {qty(remaining)} <small>(unit mengikuti item)</small></div>}\n              </td>''',
)

old_actions = '''                {item.reminder_override ? <button type="button" onClick={() => clearReminderOverride(item)} disabled={reminderActionKey === item.reminder_key}><RotateCcw size={13} /> Batalkan Override</button> : <>\n                  {actionableShortage && <button className="ops-button-primary" type="button" onClick={() => createReminderShortagePo(item)} disabled={reminderActionKey === item.reminder_key}><ShoppingCart size={13} /> Buat PO</button>}\n                  {item.reminder_status === "SHORTAGE_REVIEW" && item.reminder_key && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "CHECKED")} disabled={reminderActionKey === item.reminder_key}><CheckCircle2 size={13} /> Sudah dicek / biarkan</button>}\n                  {item.reminder_status === "SHORTAGE_REVIEW" && item.reminder_key && <button type="button" onClick={() => confirmShortageStock(item)} disabled={reminderActionKey === item.reminder_key}><Save size={13} /> Isi stok dapur</button>}\n                  {item.reminder_status === "OVERDUE" && item.reminder_key && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "SUFFICIENT")} disabled={reminderActionKey === item.reminder_key}><CheckCircle2 size={13} /> Sudah mencukupi</button>}\n                  {item.reminder_status === "OVERDUE" && item.reminder_key && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "MANUAL_PO")} disabled={reminderActionKey === item.reminder_key}><Send size={13} /> PO manual sudah dilakukan</button>}\n                </>}'''
new_actions = '''                {item.reminder_override ? <button type="button" onClick={() => clearReminderOverride(item)} disabled={reminderActionKey === item.reminder_key}><RotateCcw size={13} /> Batalkan Override</button> : <>\n                  {canCreatePo && <button className="ops-button-primary" type="button" onClick={() => createReminderShortagePo(item)} disabled={reminderActionKey === item.reminder_key}><ShoppingCart size={13} /> {residualReview ? "Buat PO Tambahan" : "Buat PO"}</button>}\n                  {canConfirmManualPo && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "MANUAL_PO")} disabled={reminderActionKey === item.reminder_key}><Send size={13} /> PO sudah dilakukan</button>}\n                  {canConfirmStock && item.reminder_key && <button type="button" onClick={() => confirmShortageStock(item)} disabled={reminderActionKey === item.reminder_key}><Save size={13} /> Konfirmasi stok gudang</button>}\n                  {residualReview && item.reminder_key && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "CHECKED")} disabled={reminderActionKey === item.reminder_key}><CheckCircle2 size={13} /> Sudah dicek / biarkan</button>}\n                </>}'''
replace_once("src/operations/OperationsPoPlanner.jsx", old_actions, new_actions)

print("PO item-level action patch applied")
