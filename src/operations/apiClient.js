const DEFAULT_BASE_URL = import.meta.env.VITE_SPPG_CORE_API_URL || "https://sppg-finance-gpt-site-production-5b7d.up.railway.app";

const jsonHeaders = { "Content-Type": "application/json" };

async function request(path, options = {}) {
  const res = await fetch(`${DEFAULT_BASE_URL}${path}`, {
    ...options,
    headers: { ...jsonHeaders, ...(options.headers || {}) },
  });

  if (!res.ok) {
    let detail = "";
    try { detail = await res.text(); } catch {}
    throw new Error(`SPPG Core API ${res.status}: ${detail || res.statusText}`);
  }

  if (res.status === 204) return null;
  return res.json();
}

export const operationsApi = {
  health: () => request("/health"),
  getSchemaStatus: () => request("/v1/schema-status"),
  getControlTower: (date) => request(`/v1/control-tower?date=${encodeURIComponent(date)}`),
  getPoCalendar: ({ from, to, site }) => {
    const q = new URLSearchParams({ from, to });
    if (site) q.set("site", site);
    return request(`/v1/po-calendar?${q.toString()}`);
  },
  previewPoSchedule: ({ distributionDate, cookingDate = "", site = "" }) => {
    const q = new URLSearchParams({ distributionDate });
    if (cookingDate) q.set("cookingDate", cookingDate);
    if (site) q.set("site", site);
    return request(`/v1/po-schedule/preview?${q.toString()}`);
  },
  getReferenceSites: () => request("/v1/reference/sites"),
  getReferenceVendors: (site = "") => {
    const q = new URLSearchParams();
    if (site) q.set("site", site);
    return request(`/v1/reference/vendors${q.toString() ? `?${q.toString()}` : ""}`);
  },
  getVendorPayments: ({ status = "", site = "" } = {}) => {
    const q = new URLSearchParams();
    if (status) q.set("status", status);
    if (site) q.set("site", site);
    return request(`/v1/vendor-payments?${q.toString()}`);
  },
  getReviewQueue: () => request("/v1/review-queue"),
  submitReviewDecision: (eventId, decision, note = "") => request(`/v1/review-queue/${eventId}`, {
    method: "POST",
    body: JSON.stringify({ decision, note }),
  }),
  ingestEvent: (payload) => request("/v1/events", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
};

export const hasOperationsBackend = Boolean(DEFAULT_BASE_URL);
export const operationsBackendUrl = DEFAULT_BASE_URL;
