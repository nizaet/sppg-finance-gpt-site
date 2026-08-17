from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one anchor, found {count}: {old[:90]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# Backend override semantics: CHECKED is a review resolution, and transformed
# SHORTAGE_REVIEW rows must immediately stop contributing to ordering counters.
replace_once(
    "backend/po_reminder_tools_api.py",
    'OVERRIDE_RESOLUTIONS = {"SUFFICIENT", "MANUAL_PO"}',
    'OVERRIDE_RESOLUTIONS = {"SUFFICIENT", "MANUAL_PO", "CHECKED"}',
)
replace_once(
    "backend/po_reminder_tools_api.py",
    '''    actionable = {"OVERDUE", "DUE_TODAY", "DRAFT_NEEDS_FINAL", "READY_TO_SEND"}\n    tomorrow = target + timedelta(days=1)''',
    '''    actionable = {"OVERDUE", "DUE_TODAY", "DRAFT_NEEDS_FINAL", "READY_TO_SEND"}\n    future_actionable = actionable | {"UPCOMING"}\n    tomorrow = target + timedelta(days=1)''',
)
replace_once(
    "backend/po_reminder_tools_api.py",
    '''    result["tomorrowCount"] = sum(\n        1 for item in items\n        if _as_date(item.get("po_date")) == tomorrow\n        and str(item.get("reminder_status") or "").upper() != "DONE"\n    )''',
    '''    result["tomorrowCount"] = sum(\n        1 for item in items\n        if _as_date(item.get("po_date")) == tomorrow\n        and str(item.get("reminder_status") or "").upper() in future_actionable\n    )''',
)
replace_once(
    "backend/po_reminder_tools_api.py",
    '''    result["overdueCount"] = sum(\n        1 for item in items\n        if (_as_date(item.get("po_date")) or date.max) < target\n        and str(item.get("reminder_status") or "").upper() == "OVERDUE"\n    )\n    return result''',
    '''    result["overdueCount"] = sum(\n        1 for item in items\n        if (_as_date(item.get("po_date")) or date.max) < target\n        and str(item.get("reminder_status") or "").upper() == "OVERDUE"\n    )\n    result["shortageReviewCount"] = sum(\n        1 for item in items\n        if str(item.get("reminder_status") or "").upper() == "SHORTAGE_REVIEW"\n    )\n    return result''',
)
replace_once(
    "backend/po_reminder_tools_api.py",
    '''    if not keys or normalized_site not in {"MAJA", "CEMPLANG"} or not database_ready():\n        return decorated''',
    '''    if not keys or normalized_site not in {"MAJA", "CEMPLANG"} or not database_ready():\n        return _recount(decorated, target)''',
)
replace_once(
    "backend/po_reminder_tools_api.py",
    '''        return decorated\n\n    if not overrides:\n        return decorated''',
    '''        return _recount(decorated, target)\n\n    if not overrides:\n        return _recount(decorated, target)''',
)
replace_once(
    "backend/po_reminder_tools_api.py",
    '''        label = "Sudah mencukupi (override)" if resolution == "SUFFICIENT" else "PO manual sudah dilakukan"\n        message = (\n            "Operator mengonfirmasi kebutuhan sudah mencukupi. Reminder ditutup tanpa mengubah stok atau PO."\n            if resolution == "SUFFICIENT"\n            else "Operator mengonfirmasi PO telah dilakukan di luar workflow aplikasi. Reminder ditutup tanpa membuat PO fiktif."\n        )''',
    '''        if resolution == "SUFFICIENT":\n            label = "Sudah mencukupi (override)"\n            message = "Operator mengonfirmasi kebutuhan sudah mencukupi. Reminder ditutup tanpa mengubah stok atau PO."\n        elif resolution == "CHECKED":\n            label = "Sudah dicek / dibiarkan"\n            message = "PO sudah dilakukan dan sisa kebutuhan telah dicek operator. Selisih diterima tanpa membuat PO atau stok fiktif."\n        else:\n            label = "PO manual sudah dilakukan"\n            message = "Operator mengonfirmasi PO telah dilakukan di luar workflow aplikasi. Reminder ditutup tanpa membuat PO fiktif."''',
)
replace_once(
    "backend/po_reminder_tools_api.py",
    '''            "po_workflow_status": "DONE_MANUAL",''',
    '''            "po_workflow_status": "DONE_REVIEWED" if resolution == "CHECKED" else "DONE_MANUAL",''',
)
replace_once(
    "backend/po_reminder_tools_api.py",
    '    resolution: Literal["SUFFICIENT", "MANUAL_PO"]',
    '    resolution: Literal["SUFFICIENT", "MANUAL_PO", "CHECKED"]',
)

# Frontend API for audited physical stock correction.
replace_once(
    "src/operations/apiClient.js",
    '''  clearPoReminderOverride: (reminderKey) => request(`/v1/po-reminders/override/${encodeURIComponent(reminderKey)}`, { method: "DELETE" }),''',
    '''  clearPoReminderOverride: (reminderKey) => request(`/v1/po-reminders/override/${encodeURIComponent(reminderKey)}`, { method: "DELETE" }),\n  confirmPoShortageStock: (payload) => request("/v1/po-reminders/stock-confirmation", { method: "POST", body: JSON.stringify(payload) }),''',
)

# Current PO planner UI. True ordering backlog keeps "Buat PO". A residual after
# an already-SENT PO becomes review-only and offers either accept/check or an
# audited physical stock correction.
replace_once(
    "src/operations/OperationsPoPlanner.jsx",
    '''  UPCOMING: "Akan datang",\n};''',
    '''  UPCOMING: "Akan datang",\n  SHORTAGE_REVIEW: "Perlu cek kekurangan",\n};''',
)
replace_once(
    "src/operations/OperationsPoPlanner.jsx",
    '''  if (item.po_already_done && item.shortage_only) {\n    return { rowClass: "ops-reminder-shortage", pillClass: "ops-pill-amber", label: "PO sudah dilakukan · cek sisa" };\n  }''',
    '''  if (status === "SHORTAGE_REVIEW" || (item.po_already_done && item.shortage_only)) {\n    return { rowClass: "ops-reminder-shortage", pillClass: "ops-pill-amber", label: "Perlu cek kekurangan" };\n  }''',
)
replace_once(
    "src/operations/OperationsPoPlanner.jsx",
    '''  const saveReminderOverride = async (item, resolution) => {\n    if (!item.reminder_key) return;\n    const label = resolution === "SUFFICIENT" ? "SUDAH MENCUKUPI" : "PO SUDAH DILAKUKAN MANUAL";\n    if (!window.confirm(`${label}?\\n\\nReminder ini akan ditutup dan berwarna hijau. Data planning, stok gudang, dan PO yang sudah ada TIDAK diubah.`)) return;\n    const note = window.prompt("Catatan / referensi (opsional):", "") ?? "";''',
    '''  const saveReminderOverride = async (item, resolution) => {\n    if (!item.reminder_key) return;\n    const labels = { SUFFICIENT: "SUDAH MENCUKUPI", MANUAL_PO: "PO SUDAH DILAKUKAN MANUAL", CHECKED: "SUDAH DICEK / BIARKAN" };\n    const label = labels[resolution] || resolution;\n    const explanation = resolution === "CHECKED"\n      ? "PO sudah dilakukan. Sisa qty akan ditandai sudah Anda cek dan tidak lagi dianggap pekerjaan PO. Planning, PO dan stok tidak diubah."\n      : "Reminder ini akan ditutup dan berwarna hijau. Data planning, stok gudang, dan PO yang sudah ada TIDAK diubah.";\n    if (!window.confirm(`${label}?\\n\\n${explanation}`)) return;\n    const note = window.prompt("Catatan / referensi (opsional):", "") ?? "";''',
)
replace_once(
    "src/operations/OperationsPoPlanner.jsx",
    '''      setMessage(resolution === "SUFFICIENT" ? "Reminder ditutup: kebutuhan dikonfirmasi sudah mencukupi." : "Reminder ditutup: PO manual dikonfirmasi sudah dilakukan.");''',
    '''      setMessage(resolution === "SUFFICIENT"\n        ? "Reminder ditutup: kebutuhan dikonfirmasi sudah mencukupi."\n        : resolution === "CHECKED"\n          ? "Kekurangan ditandai sudah dicek / dibiarkan. PO yang sudah selesai tidak lagi masuk antrean terlambat."\n          : "Reminder ditutup: PO manual dikonfirmasi sudah dilakukan.");''',
)

anchor = '''  const clearReminderOverride = async (item) => {'''
insert = '''  const confirmShortageStock = async (item) => {\n    if (!item.reminder_key) return;\n    const details = (item.requirement_details || []).filter((detail) => Number(detail.remaining_po_qty || 0) > 0);\n    if (!details.length) {\n      setError("Tidak ada item kekurangan yang dapat dikoreksi stoknya.");\n      return;\n    }\n    const updates = [];\n    for (const detail of details) {\n      const names = (detail.item_names || []).filter(Boolean);\n      const itemName = names[0] || detail.stock_type_code || "Item";\n      const unit = detail.unit || "";\n      const answer = window.prompt(\n        `Stok fisik AKTUAL dapur untuk ${itemName}${unit ? ` (${unit})` : ""} sekarang berapa?\\n\\nIsi jumlah yang benar-benar ada saat ini, bukan selisih. Kosongkan jika item ini tidak perlu dikoreksi.`,\n        ""\n      );\n      if (answer === null) return;\n      if (!String(answer).trim()) continue;\n      const value = Number(String(answer).replace(",", "."));\n      if (!Number.isFinite(value) || value < 0) {\n        setError(`Stok ${itemName} tidak valid.`);\n        return;\n      }\n      if (!unit) {\n        setError(`Satuan ${itemName} belum tersedia; koreksi stok dibatalkan agar tidak salah unit.`);\n        return;\n      }\n      updates.push({ item_name: itemName, unit, actual_stock_qty: value });\n    }\n    if (!updates.length) {\n      setMessage("Tidak ada stok yang diubah. Gunakan ‘Sudah dicek / biarkan’ jika selisih memang disengaja.");\n      return;\n    }\n    if (!window.confirm(`Catat ${updates.length} stok fisik dapur sebagai koreksi gudang ${activeSite}?\\n\\nSistem hanya mencatat SELISIH terhadap saldo aktual sekarang. SO terakhir tidak diubah.`)) return;\n    setReminderActionKey(item.reminder_key);\n    setError("");\n    setMessage("");\n    try {\n      const result = await operationsApi.confirmPoShortageStock({\n        site: activeSite,\n        reminder_key: item.reminder_key,\n        items: updates,\n        note: `Koreksi dari review kekurangan ${item.po_code || item.vendor_code}`,\n      });\n      await load();\n      setMessage(result?.message || "Stok dapur dikoreksi dan reminder dihitung ulang.");\n    } catch (err) {\n      setError(err.message || "Gagal mencatat koreksi stok dapur");\n    } finally {\n      setReminderActionKey("");\n    }\n  };\n\n  const clearReminderOverride = async (item) => {'''
replace_once("src/operations/OperationsPoPlanner.jsx", anchor, insert)

replace_once(
    "src/operations/OperationsPoPlanner.jsx",
    '''          <span className="ops-summary-green">Selesai <strong>{reminders.filter((item) => item.reminder_status === "DONE").length}</strong></span>\n          <span>Cakupan <strong>21 hari</strong></span>''',
    '''          <span className="ops-summary-green">Selesai <strong>{reminders.filter((item) => item.reminder_status === "DONE").length}</strong></span>\n          <span>Perlu cek kekurangan <strong>{reminders.filter((item) => item.reminder_status === "SHORTAGE_REVIEW").length}</strong></span>\n          <span>Cakupan <strong>21 hari</strong></span>''',
)
replace_once(
    "src/operations/OperationsPoPlanner.jsx",
    '''                  {actionableShortage && <button className="ops-button-primary" type="button" onClick={() => createReminderShortagePo(item)} disabled={reminderActionKey === item.reminder_key}><ShoppingCart size={13} /> {item.po_already_done ? "Buat PO Kekurangan" : "Buat PO"}</button>}\n                  {item.reminder_status === "OVERDUE" && item.reminder_key && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "SUFFICIENT")} disabled={reminderActionKey === item.reminder_key}><CheckCircle2 size={13} /> Sudah mencukupi</button>}\n                  {item.reminder_status === "OVERDUE" && item.reminder_key && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "MANUAL_PO")} disabled={reminderActionKey === item.reminder_key}><Send size={13} /> PO manual sudah dilakukan</button>}''',
    '''                  {actionableShortage && <button className="ops-button-primary" type="button" onClick={() => createReminderShortagePo(item)} disabled={reminderActionKey === item.reminder_key}><ShoppingCart size={13} /> Buat PO</button>}\n                  {item.reminder_status === "SHORTAGE_REVIEW" && item.reminder_key && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "CHECKED")} disabled={reminderActionKey === item.reminder_key}><CheckCircle2 size={13} /> Sudah dicek / biarkan</button>}\n                  {item.reminder_status === "SHORTAGE_REVIEW" && item.reminder_key && <button type="button" onClick={() => confirmShortageStock(item)} disabled={reminderActionKey === item.reminder_key}><Save size={13} /> Isi stok dapur</button>}\n                  {item.reminder_status === "OVERDUE" && item.reminder_key && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "SUFFICIENT")} disabled={reminderActionKey === item.reminder_key}><CheckCircle2 size={13} /> Sudah mencukupi</button>}\n                  {item.reminder_status === "OVERDUE" && item.reminder_key && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "MANUAL_PO")} disabled={reminderActionKey === item.reminder_key}><Send size={13} /> PO manual sudah dilakukan</button>}''',
)

print("PO shortage review patch applied")
