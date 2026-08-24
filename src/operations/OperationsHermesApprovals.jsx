import React, { useEffect, useMemo, useState } from "react";
import { Bot, Check, Clock3, FilePlus2, Lock, RefreshCw, ShieldCheck, X } from "lucide-react";
import { operationsApi } from "./apiClient.js";
import "./hermes-approvals.css";

const ACTION_LABELS = {
  CREATE_PO: "Buat draft PO",
  RECORD_RECEIVING: "Catat penerimaan",
  RECORD_VENDOR_PAYABLE: "Catat tagihan vendor",
  RECORD_VENDOR_PAYMENT: "Catat pembayaran vendor",
  RECORD_FINANCE_TRANSACTION: "Catat transaksi keuangan",
  SEND_WHATSAPP: "Kirim WhatsApp",
};

const STATUS_LABELS = {
  PENDING: "Menunggu keputusan",
  VALIDATED: "Disetujui — belum dieksekusi",
  REJECTED: "Ditolak",
  APPLIED: "Diterapkan",
  SUPERSEDED: "Digantikan",
};

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("id-ID", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Jakarta",
  }).format(date);
}

function proposalDetails(item) {
  const candidate = item?.payload && typeof item.payload === "object" ? item.payload : {};
  const proposed = candidate?.proposedAction && typeof candidate.proposedAction === "object"
    ? candidate.proposedAction
    : {};
  const action = item?.action_payload && typeof item.action_payload === "object" ? item.action_payload : {};
  return {
    sourceRef: candidate.sourceRef || "-",
    rationale: candidate.rationale || action.rationale || item.raw_text || "Tidak ada alasan.",
    targetType: proposed.targetType || item.target_type || "-",
    targetId: proposed.targetId || item.target_id || "-",
    payload: proposed.payload || action.payload || {},
  };
}

function formatQty(value) {
  const number = Number(value || 0);
  return Number.isFinite(number)
    ? new Intl.NumberFormat("id-ID", { maximumFractionDigits: 4 }).format(number)
    : String(value || "-");
}

export default function OperationsHermesApprovals() {
  const [items, setItems] = useState([]);
  const [site, setSite] = useState("");
  const [status, setStatus] = useState("PENDING");
  const [notes, setNotes] = useState({});
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [previewBusyId, setPreviewBusyId] = useState(null);
  const [previews, setPreviews] = useState({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const pendingCount = useMemo(
    () => items.filter((item) => item.candidate_status === "PENDING").length,
    [items],
  );

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await operationsApi.getHermesActionProposals({ site, status, limit: 100 });
      const capabilities = Array.isArray(data?.ownerExecutionCapabilities) ? data.ownerExecutionCapabilities : [];
      if (data?.executionExposed !== false || data?.genericExecutionExposed !== false || capabilities.join(",") !== "CREATE_PO_DRAFT") {
        throw new Error("Batas keamanan Hermes tidak dapat diverifikasi.");
      }
      setItems(Array.isArray(data?.items) ? data.items : []);
    } catch (err) {
      setError(err.message || "Gagal memuat proposal Hermes");
    } finally {
      setLoading(false);
    }
  };

  const previewPoDraft = async (item) => {
    const actionId = item.action_id;
    setPreviewBusyId(actionId);
    setError("");
    setNotice("");
    try {
      const result = await operationsApi.previewHermesPoDraft(actionId);
      const safety = result?.safety || {};
      if (
        safety.createsStatus !== "DRAFT"
        || safety.finalizesPurchaseOrder !== false
        || safety.marksPurchaseOrderSent !== false
        || safety.sendsWhatsApp !== false
        || safety.writesFinance !== false
        || safety.writesReceiving !== false
      ) {
        throw new Error("Preview tidak memenuhi batas CREATE_PO_DRAFT.");
      }
      setPreviews((current) => ({ ...current, [actionId]: result }));
    } catch (err) {
      setError(err.message || "Payload proposal tidak dapat divalidasi sebagai draft PO");
    } finally {
      setPreviewBusyId(null);
    }
  };

  const createPoDraft = async (item) => {
    const actionId = item.action_id;
    const preview = previews[actionId];
    if (!preview?.executable || !preview?.draft) {
      setError("Tinjau dan validasi payload PO terlebih dahulu.");
      return;
    }
    const draft = preview.draft;
    const confirmed = window.confirm(
      `BUAT PO DRAFT DARI HERMES?\n\n`
      + `Site: ${draft.site}\nVendor: ${draft.vendor_code}\nNo. PO: ${draft.po_code}\n`
      + `Distribusi: ${draft.distribution_date}\nItem: ${(draft.items || []).length}\n\n`
      + "Aksi ini MENULIS satu PO berstatus DRAFT. Tidak memfinalkan, tidak menandai terkirim, dan tidak mengirim WhatsApp.",
    );
    if (!confirmed) return;

    setBusyId(actionId);
    setError("");
    setNotice("");
    try {
      const result = await operationsApi.createHermesPoDraft(actionId);
      if (
        result?.purchaseOrderStatus !== "DRAFT"
        || result?.draftOnlyAtCreation !== true
        || result?.finalizedByExecutor !== false
        || result?.markedSentByExecutor !== false
        || result?.whatsAppSentByExecutor !== false
        || result?.otherExecutorsLocked !== true
      ) {
        throw new Error("Respons executor tidak memenuhi batas DRAFT-only.");
      }
      setNotice(`${result.poCode} rev ${result.revisionNo} dibuat sebagai DRAFT. Belum final dan belum dikirim.`);
      setPreviews((current) => {
        const next = { ...current };
        delete next[actionId];
        return next;
      });
      await load();
    } catch (err) {
      setError(err.message || "Gagal membuat PO DRAFT dari proposal Hermes");
    } finally {
      setBusyId(null);
    }
  };

  useEffect(() => { load(); }, [site, status]);

  const decide = async (item, decision) => {
    const actionId = item.action_id;
    const note = String(notes[actionId] || "").trim();
    if (decision === "REJECT" && !note) {
      setError("Alasan penolakan wajib diisi.");
      return;
    }
    if (decision === "APPROVE") {
      const confirmed = window.confirm(
        `Setujui proposal Hermes #${item.proposal_id}?\n\nStatus hanya berubah menjadi READY. Tidak ada PO, pembayaran, receiving, atau WhatsApp yang dieksekusi.`,
      );
      if (!confirmed) return;
    }

    setBusyId(actionId);
    setError("");
    setNotice("");
    try {
      const result = await operationsApi.decideHermesActionProposal(actionId, decision, note);
      if (result?.executed !== false || result?.executionLocked !== true) {
        throw new Error("Respons keputusan tidak memenuhi batas keamanan.");
      }
      setNotice(
        decision === "APPROVE"
          ? `Proposal #${result.proposalId} disetujui sebagai READY, tetapi belum dieksekusi.`
          : `Proposal #${result.proposalId} ditolak dan dibatalkan.`,
      );
      setNotes((current) => ({ ...current, [actionId]: "" }));
      await load();
    } catch (err) {
      setError(err.message || "Gagal menyimpan keputusan proposal");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="ops-module hermes-approval-panel">
      <div className="ops-module-header hermes-approval-header">
        <div>
          <span className="ops-kicker">HERMES ACTION CONTROL</span>
          <h3><ShieldCheck size={23} /> Persetujuan Hermes</h3>
          <p>Tinjau proposal agen. Approval dan pembuatan DRAFT tetap dua tindakan OWNER yang terpisah.</p>
        </div>
        <button type="button" onClick={load} disabled={loading}>
          <RefreshCw size={15} className={loading ? "hermes-spin" : ""} />
          {loading ? "Memuat" : "Refresh"}
        </button>
      </div>

      <div className="hermes-safety-banner">
        <Lock size={18} />
        <div>
          <strong>Hanya executor PO DRAFT yang dibuka</strong>
          <span>Sesudah proposal READY, OWNER wajib meninjau payload lalu konfirmasi lagi. Executor tidak dapat finalisasi PO, menandai terkirim, mengirim WhatsApp, atau menulis receiving/keuangan.</span>
        </div>
      </div>

      <div className="hermes-toolbar">
        <label>
          Site
          <select value={site} onChange={(event) => setSite(event.target.value)}>
            <option value="">Semua site</option>
            <option value="MAJA">MAJA</option>
            <option value="CEMPLANG">CEMPLANG</option>
          </select>
        </label>
        <label>
          Status
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="PENDING">Menunggu keputusan</option>
            <option value="VALIDATED">Sudah disetujui</option>
            <option value="REJECTED">Ditolak</option>
            <option value="APPLIED">Sudah dibuatkan DRAFT</option>
            <option value="">Semua status</option>
          </select>
        </label>
        <div className="hermes-pending-count">
          <Clock3 size={16} /> {pendingCount} pending pada tampilan ini
        </div>
      </div>

      {error && <div className="ops-error">{error}</div>}
      {notice && <div className="ops-success">{notice}</div>}
      {!loading && items.length === 0 && (
        <div className="ops-empty">Tidak ada proposal Hermes untuk filter ini.</div>
      )}

      <div className="hermes-proposal-list">
        {items.map((item) => {
          const details = proposalDetails(item);
          const isPending = item.candidate_status === "PENDING" && item.action_status === "PLANNED";
          const isReadyPo = item.candidate_status === "VALIDATED" && item.action_status === "READY" && item.action_type === "CREATE_PO";
          const preview = previews[item.action_id];
          return (
            <article className="hermes-proposal-card" key={item.action_id}>
              <header>
                <div className="hermes-proposal-title">
                  <Bot size={19} />
                  <div>
                    <strong>{ACTION_LABELS[item.action_type] || item.action_type}</strong>
                    <span>Proposal #{item.proposal_id} · Action #{item.action_id}</span>
                  </div>
                </div>
                <span className={`hermes-status hermes-status-${String(item.candidate_status || "").toLowerCase()}`}>
                  {STATUS_LABELS[item.candidate_status] || item.candidate_status}
                </span>
              </header>

              <div className="hermes-proposal-meta">
                <span><b>Site:</b> {item.site || "-"}</span>
                <span><b>Vendor:</b> {item.vendor_code || "-"}</span>
                <span><b>Confidence:</b> {Math.round(Number(item.confidence || 0) * 100)}%</span>
                <span><b>Dibuat:</b> {formatTime(item.created_at)}</span>
              </div>

              <div className="hermes-proposal-reason">
                <b>Alasan Hermes</b>
                <p>{details.rationale}</p>
              </div>

              <div className="hermes-proposal-grid">
                <div><span>Target</span><strong>{details.targetType}</strong></div>
                <div><span>Target ID</span><strong>{details.targetId}</strong></div>
                <div><span>Source ref</span><strong>{details.sourceRef}</strong></div>
                <div><span>Status workflow</span><strong>{item.action_status}</strong></div>
              </div>

              <details className="hermes-payload">
                <summary>Lihat payload proposal</summary>
                <pre>{JSON.stringify(details.payload, null, 2)}</pre>
              </details>

              {isReadyPo && (
                <div className="hermes-execution-area">
                  <div className="hermes-execution-heading">
                    <div>
                      <strong>Langkah kedua: validasi lalu buat PO DRAFT</strong>
                      <span>Tidak ada aksi otomatis setelah approval. Payload diperiksa kembali terhadap vendor, site, planning, dan PO aktif.</span>
                    </div>
                    <button
                      type="button"
                      className="hermes-preview"
                      disabled={previewBusyId === item.action_id || busyId === item.action_id}
                      onClick={() => previewPoDraft(item)}
                    >
                      <ShieldCheck size={16} /> {previewBusyId === item.action_id ? "Memvalidasi" : "Tinjau draft PO"}
                    </button>
                  </div>

                  {preview && (
                    <div className={`hermes-execution-preview ${preview.executable ? "" : "hermes-execution-blocked"}`}>
                      {preview.executable ? (
                        <>
                          <div className="hermes-preview-grid">
                            <div><span>No. PO</span><strong>{preview.draft.po_code}</strong></div>
                            <div><span>Site / Vendor</span><strong>{preview.draft.site} / {preview.draft.vendor_code}</strong></div>
                            <div><span>Distribusi</span><strong>{preview.draft.distribution_date}</strong></div>
                            <div><span>Status yang dibuat</span><strong>DRAFT</strong></div>
                          </div>
                          <div className="hermes-preview-items">
                            {(preview.draft.items || []).map((line, index) => (
                              <div key={`${line.item_code || line.item_name}-${index}`}>
                                <span>{index + 1}. {line.item_name}</span>
                                <strong>{formatQty(line.po_qty)} {line.unit || ""}</strong>
                              </div>
                            ))}
                          </div>
                          <button
                            type="button"
                            className="hermes-create-draft"
                            disabled={busyId === item.action_id}
                            onClick={() => createPoDraft(item)}
                          >
                            <FilePlus2 size={16} /> {busyId === item.action_id ? "Membuat DRAFT" : "Buat PO DRAFT"}
                          </button>
                        </>
                      ) : (
                        <div>
                          <strong>Eksekusi diblokir karena PO aktif sudah ada.</strong>
                          <span>
                            {preview.existingPurchaseOrder?.poCode || "PO aktif"} · {preview.existingPurchaseOrder?.status || "-"}. Buka PO tersebut; executor tidak membuat duplikat.
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {isPending ? (
                <div className="hermes-decision-area">
                  <label>
                    Catatan keputusan
                    <textarea
                      value={notes[item.action_id] || ""}
                      onChange={(event) => setNotes((current) => ({
                        ...current,
                        [item.action_id]: event.target.value,
                      }))}
                      placeholder="Wajib untuk penolakan; opsional untuk persetujuan"
                      rows={2}
                    />
                  </label>
                  <div>
                    <button
                      type="button"
                      className="hermes-reject"
                      disabled={busyId === item.action_id}
                      onClick={() => decide(item, "REJECT")}
                    >
                      <X size={16} /> Tolak
                    </button>
                    <button
                      type="button"
                      className="hermes-approve"
                      disabled={busyId === item.action_id}
                      onClick={() => decide(item, "APPROVE")}
                    >
                      <Check size={16} /> Setujui sebagai READY
                    </button>
                  </div>
                </div>
              ) : (
                <div className="hermes-decision-readonly">
                  Diputuskan oleh {item.validated_by || "operator"} · {formatTime(item.validated_at)}
                  {item.rejection_reason ? ` · ${item.rejection_reason}` : ""}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
