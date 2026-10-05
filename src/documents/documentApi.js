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
  master: site => request(`/master?${new URLSearchParams({ site })}`),
  list: (site, date) => request(`?${new URLSearchParams({ site, service_date: date })}`),
  create: payload => request("", { method: "POST", body: JSON.stringify(payload) }),
  edit: (id, payload) => request(`/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  finalize: id => request(`/${id}/finalize`, { method: "PATCH" }),
  pdf: id => request(`/${id}/pdf`),
  syncDaily: (site, date) => request("/sync-daily", { method: "POST", body: JSON.stringify({ site, service_date: date }) }),
};
