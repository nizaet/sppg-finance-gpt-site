import React, { useEffect, useState } from "react";
import { Check, RefreshCw, X } from "lucide-react";
import { operationsApi } from "./apiClient";

export default function OperationsReviewQueue() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await operationsApi.getReviewQueue();
      setItems(data?.items || []);
    } catch (err) {
      setError(err.message || "Gagal mengambil review queue");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const decide = async (item, decision) => {
    setBusyId(item.id);
    setError("");
    try {
      await operationsApi.submitReviewDecision(item.id, decision, "Reviewed from Pusat Operasional");
      setItems((prev) => prev.filter((x) => x.id !== item.id));
    } catch (err) {
      setError(err.message || "Gagal menyimpan keputusan");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="ops-review-panel">
      <div className="ops-review-header">
        <div>
          <span className="ops-kicker">AI / WHATSAPP REVIEW</span>
          <h3>Review Queue</h3>
          <p>Event berisiko tidak mengubah transaksi sampai disetujui.</p>
        </div>
        <button type="button" onClick={load} disabled={loading}>
          <RefreshCw size={15} /> {loading ? "Memuat" : "Refresh"}
        </button>
      </div>

      {error && <div className="ops-error">{error}</div>}
      {!loading && items.length === 0 && <div className="ops-empty">Tidak ada event yang menunggu review.</div>}

      <div className="ops-review-list">
        {items.map((item) => (
          <article className="ops-review-card" key={item.id}>
            <div className="ops-review-meta">
              <strong>{item.event_type}</strong>
              <span>{item.site || "-"} · {item.vendor_code || item.entity_code || "-"}</span>
              <span>Confidence {Math.round(Number(item.confidence || 0) * 100)}%</span>
            </div>
            <div className="ops-review-text">{item.raw_text || "Tidak ada raw text."}</div>
            <div className="ops-review-actions">
              <button type="button" className="ops-btn-reject" onClick={() => decide(item, "REJECT")} disabled={busyId === item.id}>
                <X size={15} /> Tolak
              </button>
              <button type="button" className="ops-btn-approve" onClick={() => decide(item, "APPROVE")} disabled={busyId === item.id}>
                <Check size={15} /> Setujui
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
