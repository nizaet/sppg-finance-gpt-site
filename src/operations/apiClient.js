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
  getPlanningSnapshots: ({ site = "", distributionDate = "", activeOnly = true } = {}) => {
    const q = new URLSearchParams();
    if (site) q.set("site", site);
    if (distributionDate) q.set("distributionDate", distributionDate);
    q.set("activeOnly", activeOnly ? "true" : "false");
    return request(`/v1/planning-snapshots?${q.toString()}`);
  },
  getPlanningSnapshot: (snapshotId) => request(`/v1/planning-snapshots/${snapshotId}`),
  ingestPlanningSnapshot: (payload) => request("/v1/planning-snapshots", { method: "POST", body: JSON.stringify(payload) }),
  parseMessage: (payload) => request("/v1/parse-message", { method: "POST", body: JSON.stringify(payload) }),
  getGoodsReceipts: ({ site = "", limit = 100 } = {}) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (site) q.set("site", site);
    return request(`/v1/goods-receipts?${q.toString()}`);
  },
  createGoodsReceipt: (payload) => request("/v1/goods-receipts", { method: "POST", body: JSON.stringify(payload) }),
  getActualUsage: (productionCycleId) => request(`/v1/actual-usage?productionCycleId=${encodeURIComponent(productionCycleId)}`),
  saveActualUsage: (payload) => request("/v1/actual-usage", { method: "POST", body: JSON.stringify(payload) }),
  getAccountantFlow: (site = "") => {
    const q = new URLSearchParams(); if (site) q.set("site", site);
    return request(`/v1/accountant-flow${q.toString() ? `?${q.toString()}` : ""}`);
  },
  createAccountantSubmission: (payload) => request("/v1/accountant-submissions", { method: "POST", body: JSON.stringify(payload) }),
  createAccountantInvoice: (payload) => request("/v1/accountant-invoices", { method: "POST", body: JSON.stringify(payload) }),
  getBgnFlow: (site = "") => {
    const q = new URLSearchParams(); if (site) q.set("site", site);
    return request(`/v1/bgn-flow${q.toString() ? `?${q.toString()}` : ""}`);
  },
  createBgnMaker: (payload) => request("/v1/bgn-makers", { method: "POST", body: JSON.stringify(payload) }),
  createBgnApproval: (payload) => request("/v1/bgn-approvals", { method: "POST", body: JSON.stringify(payload) }),
  createBgnReceipt: (payload) => request("/v1/bgn-receipts", { method: "POST", body: JSON.stringify(payload) }),
  createSettlement: (payload) => request("/v1/settlements", { method: "POST", body: JSON.stringify(payload) }),
  getAuditLog: (limit = 200) => request(`/v1/audit-log?limit=${encodeURIComponent(limit)}`),
  getReviewQueue: () => request("/v1/review-queue"),
  submitReviewDecision: (eventId, decision, note = "") => request(`/v1/review-queue/${eventId}`, {
    method: "POST",
    body: JSON.stringify({ decision, note }),
  }),
  ingestEvent: (payload) => request("/v1/events", { method: "POST", body: JSON.stringify(payload) }),
};

export const hasOperationsBackend = Boolean(DEFAULT_BASE_URL);
export const operationsBackendUrl = DEFAULT_BASE_URL;
