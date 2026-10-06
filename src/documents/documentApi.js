import { CORE_API, readSessionToken } from "../auth/session.js";

async function request(path, options = {}) {
  const token = readSessionToken();
  const response = await fetch(`${CORE_API}/v1/accountant-documents${path}`, {
    ...options, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  const result = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = result?.detail;
    const message = Array.isArray(detail) ? detail.map(x => x.msg).join("; ") : typeof detail === "string" ? detail : "Dokumen gagal diproses. Coba lagi.";
    throw new Error(message);
  }
  return result;
}

export const documentApi = {
  previousRoutine: (site, date, sourceDate = "") => request(`/previous-routine?${new URLSearchParams({ site, service_date: date, ...(sourceDate ? { source_date: sourceDate } : {}) })}`),
  suggestNumber: (site, date, type) => request(`/number-suggestion?${new URLSearchParams({ site, service_date: date, document_type: type })}`),
  master: site => request(`/master?${new URLSearchParams({ site })}`),
  get: id => request(`/${id}`),
  uploadAsset: payload => request("/assets", { method: "POST", body: JSON.stringify(payload) }),
  asset: id => request(`/assets/${id}`),
  saveProfile: (site, header) => request("/profile", { method: "PUT", body: JSON.stringify({ site, header_payload: header }) }),
  list: (site, date) => request(`?${new URLSearchParams({ site, service_date: date })}`),
  calendar: (site, month) => request(`/calendar?${new URLSearchParams({ site, month })}`),
  create: payload => request("", { method: "POST", body: JSON.stringify(payload) }),
  edit: (id, payload) => request(`/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  finalizationCheck: id => request(`/${id}/finalization-check`),
  finalize: (id, options = {}) => request(`/${id}/finalize`, { method: "PATCH", body: JSON.stringify(options) }),
  archive: id => request(`/${id}/archive`, { method: "POST" }),
  cancel: (id, reason) => request(`/${id}/cancel`, { method: "PATCH", body: JSON.stringify({ reason }) }),
  pdf: id => request(`/${id}/pdf`),
  excel: id => request(`/${id}/excel`),
  syncDaily: (site, date) => request("/sync-daily", { method: "POST", body: JSON.stringify({ site, service_date: date }) }),
};
