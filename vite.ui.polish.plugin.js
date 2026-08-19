function replaceOnce(code, needle, replacement, label) {
  if (!code.includes(needle)) {
    throw new Error(`[ui-polish] Missing transform anchor: ${label}`);
  }
  return code.replace(needle, replacement);
}

export default function uiPolishPlugin() {
  return {
    name: "sppg-ui-polish",
    enforce: "pre",
    transform(code, id) {
      if (id.includes("/src/operations/OperationsPoPlanner.jsx")) {
        let next = code;

        next = replaceOnce(
          next,
          `return <tr key={po.id} className={poRowClass(status, isHistory)}>`,
          `return <tr key={po.id} className={poRowClass(status, isHistory)} data-po-receiving-state={status} style={status === "RECEIVED" ? { background: "rgba(34,197,94,.16)" } : status === "PARTIAL_RECEIVED" ? { background: "rgba(245,158,11,.12)" } : undefined}>`,
          "PO list receiving row state",
        );

        const oldStatusCell = `<td><div className="ops-status-stack"><span className={\`ops-badge \${isHistory ? "" : status === "DRAFT" ? "ops-badge-latest" : "ops-badge-active"}\`}>{isHistory ? "HISTORI" : status === "DRAFT" ? "PERLU FINAL" : ["SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"].includes(status) ? "✓ SELESAI" : "SIAP KIRIM"}</span><span className="ops-badge ops-badge-type">{po.status}</span></div></td>`;
        const newStatusCell = `<td><div className="ops-status-stack"><span className={\`ops-badge \${isHistory ? "" : status === "DRAFT" ? "ops-badge-latest" : "ops-badge-active"}\`} style={status === "RECEIVED" ? { background: "#16a34a", color: "#fff" } : status === "PARTIAL_RECEIVED" ? { background: "#f59e0b", color: "#fff" } : undefined}>{isHistory ? "HISTORI" : status === "RECEIVED" ? "✓ DITERIMA" : status === "PARTIAL_RECEIVED" ? "◐ DITERIMA SEBAGIAN" : ["SENT", "ACKNOWLEDGED"].includes(status) ? "✓ TERKIRIM" : status === "DRAFT" ? "PERLU FINAL" : "SIAP KIRIM"}</span><span className="ops-badge ops-badge-type">{po.status}</span></div></td>`;
        next = replaceOnce(next, oldStatusCell, newStatusCell, "PO list receiving status label");

        return next === code ? null : { code: next, map: null };
      }

      if (id.includes("/src/operations/PoOpsEnhancements.jsx")) {
        let next = code;
        const oldCalendarButton = `<button key={\`\${po.id}-\${dateValue}\`} type="button" onClick={() => openCalendarPo(po)} style={{ display: "block", width: "100%", marginTop: 5, textAlign: "left", whiteSpace: "normal" }}>`;
        const newCalendarButton = `<button key={\`\${po.id}-\${dateValue}\`} type="button" data-calendar-receiving-state={String(po.status || "").toUpperCase()} onClick={() => openCalendarPo(po)} style={{ display: "block", width: "100%", marginTop: 5, textAlign: "left", whiteSpace: "normal", background: String(po.status || "").toUpperCase() === "RECEIVED" ? "rgba(34,197,94,.18)" : String(po.status || "").toUpperCase() === "PARTIAL_RECEIVED" ? "rgba(245,158,11,.15)" : undefined, borderColor: String(po.status || "").toUpperCase() === "RECEIVED" ? "#22c55e" : String(po.status || "").toUpperCase() === "PARTIAL_RECEIVED" ? "#f59e0b" : undefined }}>`;
        next = replaceOnce(next, oldCalendarButton, newCalendarButton, "calendar PO receiving color");

        const oldCalendarCreated = `<div className="ops-muted">PO dibuat {compactTimestamp(po.created_at).slice(0, 10)}</div>`;
        const newCalendarCreated = `<div className="ops-muted">PO dibuat {compactTimestamp(po.created_at).slice(0, 10)}</div><div style={{ marginTop: 3, fontWeight: 800, color: String(po.status || "").toUpperCase() === "RECEIVED" ? "#15803d" : String(po.status || "").toUpperCase() === "PARTIAL_RECEIVED" ? "#b45309" : undefined }}>{String(po.status || "").toUpperCase() === "RECEIVED" ? "✓ Barang diterima" : String(po.status || "").toUpperCase() === "PARTIAL_RECEIVED" ? "◐ Diterima sebagian" : ""}</div>`;
        next = replaceOnce(next, oldCalendarCreated, newCalendarCreated, "calendar receiving label");

        return next === code ? null : { code: next, map: null };
      }

      if (id.includes("/src/operations/OperationsAccountantBgn.jsx")) {
        let next = code;
        next = replaceOnce(
          next,
          `  const [excelBusy,setExcelBusy]=useState(false);`,
          `  const [excelBusy,setExcelBusy]=useState(false);\n  const [excelFilename,setExcelFilename]=useState("");`,
          "accountant filename state",
        );

        next = next.replaceAll(
          `calculatorDocumentId: selectedPlanId,\n      }, false);`,
          `calculatorDocumentId: selectedPlanId,\n        customFilename: excelFilename.trim(),\n      }, false);`,
        );
        next = next.replaceAll(
          `calculatorDocumentId: selectedPlanId,\n      }, true);`,
          `calculatorDocumentId: selectedPlanId,\n        customFilename: excelFilename.trim(),\n      }, true);`,
        );

        next = replaceOnce(
          next,
          `      setExcelPreview(data);\n    } catch (e) {\n      setError(e.message || "Gagal preview Excel akuntan");`,
          `      setExcelPreview(data);\n      setExcelFilename((current) => current || data.filename || "");\n    } catch (e) {\n      setError(e.message || "Gagal preview Excel akuntan");`,
          "preview default filename",
        );
        next = replaceOnce(
          next,
          `      setExcelPreview(data);\n      if (data.driveUri) {`,
          `      setExcelPreview(data);\n      setExcelFilename(data.filename || excelFilename);\n      if (data.driveUri) {`,
          "committed filename state",
        );

        next = next.replaceAll(
          `setExcelSite(e.target.value);setExcelPreview(null);setSelectedPlanId("");`,
          `setExcelSite(e.target.value);setExcelPreview(null);setSelectedPlanId("");setExcelFilename("");`,
        );
        next = next.replaceAll(
          `setExcelDate(e.target.value);setExcelPreview(null);setSelectedPlanId("");`,
          `setExcelDate(e.target.value);setExcelPreview(null);setSelectedPlanId("");setExcelFilename("");`,
        );
        next = next.replaceAll(
          `setSelectedPlanId(e.target.value);setExcelPreview(null);`,
          `setSelectedPlanId(e.target.value);setExcelPreview(null);setExcelFilename("");`,
        );

        const actionLabel = `<label>Aksi<div className="ops-row-actions"><button type="button" onClick={loadPlanningOptions} disabled={planBusy}><RefreshCw size={14}/> {planBusy?"Menarik…":"Tarik Perencanaan"}</button><button type="button" onClick={previewExcel} disabled={excelBusy||!selectedPlanId}><FileSpreadsheet size={14}/> {excelBusy?"Memproses...":"Preview Excel"}</button></div></label>`;
        const filenameAndAction = `<label>Nama file Excel<input value={excelFilename} onChange={e=>{setExcelFilename(e.target.value);if(excelPreview)setExcelPreview(null);}} placeholder="contoh: Belanja Maja 19 Agustus 2026.xlsx"/><span className="ops-muted">Boleh tanpa .xlsx; sistem menambahkannya otomatis.</span></label>${actionLabel}`;
        next = replaceOnce(next, actionLabel, filenameAndAction, "accountant filename input");

        next = next.replaceAll(
          `\`Buat file \${excelPreview.filename} dari perencanaan`,
          `\`Buat file \${excelFilename || excelPreview.filename} dari perencanaan`,
        );
        next = next.replaceAll(
          `File: {excelPreview.filename} · Document ID:`,
          `File: {excelFilename || excelPreview.filename} · Document ID:`,
        );

        return next === code ? null : { code: next, map: null };
      }

      return null;
    },
  };
}
