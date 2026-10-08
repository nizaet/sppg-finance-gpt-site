import { CORE_API, readSessionToken } from "../auth/session.js";
import { documentApi } from "../documents/documentApi.js";

async function request(path, options = {}) {
  const token = readSessionToken();
  const response = await fetch(`${CORE_API}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  let payload = null;
  try { payload = await response.json(); } catch {}
  if (!response.ok) {
    const detail = payload?.detail;
    const message = Array.isArray(detail) ? detail.map(x => x.msg).join("; ") : typeof detail === "string"
      ? detail
      : detail?.message || payload?.message || response.statusText || "Permintaan LPDH gagal";
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function q(params) {
  const out = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") out.set(key, String(value));
  });
  return out.toString();
}

export const lpdhApi = {
  topupReceipts:(site,date)=>request(`/v1/lpdh/topup/receipts?${new URLSearchParams({site,date})}`),
  topupReceiptDraft:payload=>request('/v1/lpdh/topup/receipts',{method:'POST',body:JSON.stringify(payload)}),
  topupReceiptPdf:id=>request(`/v1/lpdh/topup/receipts/${id}/pdf`),
  topupReceiptFinalize:(id,hash)=>request(`/v1/lpdh/topup/receipts/${id}/finalize`,{method:'POST',body:JSON.stringify({expected_hash:hash})}),
  topupReceiptCancel:(id,hash,reason)=>request(`/v1/lpdh/topup/receipts/${id}/cancel`,{method:'POST',body:JSON.stringify({expected_hash:hash,reason})}),
  uploadTopupEvidence: (site,serviceDate,contentBase64) => request('/v1/lpdh/topup/evidence',{method:'POST',body:JSON.stringify({site,service_date:serviceDate,content_base64:contentBase64})}),
  cancelDailyValidation: (site, serviceDate) => request('/v1/lpdh/daily/validation/cancel', {method:'POST',body:JSON.stringify({site,service_date:serviceDate})}),
  approvalCancel: (site, serviceDate, expectedHash, reason) => request('/v1/lpdh/approval/cancel', { method: 'POST', body: JSON.stringify({ site, service_date: serviceDate, expected_hash: expectedHash, reason }) }),
  approvalPreview: (site, serviceDate) => request('/v1/lpdh/approval/preview', { method: 'POST', body: JSON.stringify({ site, service_date: serviceDate }) }),
  approvalFinalize: (site, serviceDate, expectedHash) => request('/v1/lpdh/approval/finalize', { method: 'POST', body: JSON.stringify({ site, service_date: serviceDate, expected_hash: expectedHash }) }),
  previousRoutine: (site, date, sourceDate) => documentApi.previousRoutine(site, date, sourceDate),
  syncDocuments: (site, date) => documentApi.syncDaily(site, date),
  getMasters: (site) => request(`/v1/lpdh/masters?${q({ site })}`),
  saveMasters: (site, data) => request("/v1/lpdh/masters", {
    method: "PUT",
    body: JSON.stringify({ site, data }),
  }),
  getDaily: (site, date) => request(`/v1/lpdh/daily?${q({ site, date })}`),
  saveDaily: (site, serviceDate, data, status = "DRAFT", options = {}) => request("/v1/lpdh/daily", {
    method: "PUT",
    body: JSON.stringify({ site, service_date: serviceDate, data, status, ...options }),
  }),
  deleteDaily: (site, date) => request(`/v1/lpdh/daily?${q({ site, date })}`, { method: "DELETE" }),
  calendar: (site, month) => request(`/v1/lpdh/calendar?${q({ site, month })}`),
  getEffectiveDays: (site, month) => request(`/v1/lpdh/effective-days?${q({ site, month })}`),
  saveEffectiveDays: (site, month, dates, notes = {}) => request("/v1/lpdh/effective-days", {
    method: "PUT",
    body: JSON.stringify({ site, month, dates, notes }),
  }),
  getFinalPlan: (site, date) => request(`/v1/lpdh/calculator-final?${q({ site, date })}`),
  preview: (site, date) => request(`/v1/lpdh/preview?${q({ site, date })}`),
  previewDraft: (site, serviceDate, data) => request("/v1/lpdh/preview", {
    method: "POST",
    body: JSON.stringify({ site, service_date: serviceDate, data }),
  }),
  generate: (site, serviceDate, draftOnly = false) => request("/v1/lpdh/generate", {
    method: "POST",
    body: JSON.stringify({ site, service_date: serviceDate, draft_only: draftOnly }),
  }),
  history: (site) => request(`/v1/lpdh/history?${q({ site })}`),
  reference: (site) => request(`/v1/lpdh/reference?${q({ site })}`),
  masterTemplate: (site) => request(`/v1/lpdh/master-template?${q({ site })}`, { cache: "no-store" }),
  importMaster: (site, filename, contentBase64) => request("/v1/lpdh/import-master", {
    method: "POST",
    body: JSON.stringify({ site, filename, content_base64: contentBase64 }),
  }),
  officialTemplateStatus: (site) => request(`/v1/lpdh/official-template?${q({ site })}`),
  saveOfficialTemplate: (site, filename, contentBase64) => request("/v1/lpdh/official-template", {
    method: "PUT",
    body: JSON.stringify({ site, filename, content_base64: contentBase64 }),
  }),
};

export function arrayBufferToBase64(buffer) {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  const step = 0x8000;
  for (let i = 0; i < bytes.length; i += step) {
    binary += String.fromCharCode(...bytes.subarray(i, Math.min(i + step, bytes.length)));
  }
  return btoa(binary);
}

export function downloadBase64(filename, mimeType, contentBase64) {
  const binary = atob(contentBase64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const blob = new Blob([bytes], { type: mimeType || "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename || "download";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

