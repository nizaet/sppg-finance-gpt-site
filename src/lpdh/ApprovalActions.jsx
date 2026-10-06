import React, { useEffect, useRef, useState } from 'react';
import { lpdhApi } from './lpdhApi.js';

export default function ApprovalActions({ site, serviceDate, daily, onSaved }) {
  const [printed, setPrinted] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const alive = useRef(true);
  const operationLock = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const preview = async () => {
    if (operationLock.current) return;
    operationLock.current = true;
    const tab = window.open('', '_blank');
    if (!tab) { operationLock.current = false; setMessage('Izinkan tab baru untuk membuka PDF cetak.'); return; }
    tab.document.body.textContent = 'Menyiapkan PDF dari template resmi…';
    setBusy(true); setPrinted(null); setMessage('');
    try {
      const result = await lpdhApi.approvalPreview(site, serviceDate);
      const bytes = Uint8Array.from(atob(result.contentBase64), c => c.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: 'application/pdf' }));
      tab.location.href = url;
      setTimeout(() => URL.revokeObjectURL(url), 300000);
      if (alive.current) { setPrinted(result); setMessage('Cetak PDF pada tab baru, lalu kembali dan klik Finalkan.'); }
    } catch (error) {
      tab.close(); if (alive.current) setMessage(error.message);
    } finally { operationLock.current = false; if (alive.current) setBusy(false); }
  };
  const finalize = async () => {
    if (operationLock.current) return;
    if (!printed || !window.confirm(`Sudah mencetak dan memeriksa J_Pengesahan tanggal ${serviceDate}?${printed.validation?.ready ? '' : ' Masih ada pemeriksaan belum OK.'}\nFinalkan akan menyimpan PDF ke Drive dan mengisi link pengesahan di D_Insentif. Ini bukan konfirmasi transfer bank.`)) return;
    operationLock.current = true; setBusy(true); setMessage('Menyimpan PDF ke Drive…');
    try {
      await lpdhApi.approvalFinalize(site, serviceDate, printed.hash);
      await onSaved?.();
      if (alive.current) setMessage('FINAL: PDF tersimpan di Drive dan link masuk ke D_Insentif.');
    } catch (error) { if (alive.current) setMessage(error.message); }
    finally { operationLock.current = false; if (alive.current) setBusy(false); }
  };
  const approval = daily?._approval;
  return <div className="lpdh-status-box">
    <p>PDF cetak memakai data terakhir yang disimpan dan sheet J_Pengesahan pada template resmi, beserta TTD dan stempel dari Master → Pengesah. Simpan Draft Data Harian serta Simpan Semua Master sebelum mencetak perubahan.</p>
    <div className="lpdh-inline-actions">
      <button type="button" disabled={busy} onClick={preview}>Buka Pratinjau Cetak</button>
      <button type="button" className="primary" disabled={busy || !printed} onClick={finalize}>Finalkan Pengesahan &amp; Simpan ke Drive</button>
      {approval?.pdfLink && <a href={approval.pdfLink} target="_blank" rel="noopener noreferrer">PDF pengesahan di Drive</a>}
    </div>
    {message && <p role="status">{message}</p>}
  </div>;
}
