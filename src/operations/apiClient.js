import { readSessionToken } from "../auth/session.js";

const DEFAULT_BASE_URL = import.meta.env.VITE_SPPG_CORE_API_URL || "https://sppg-finance-gpt-site-production-5b7d.up.railway.app";

const inflightGets = new Map();
const REQUEST_TIMEOUT_MS = 20000;

function requestHeaders(options = {}) {
  const token = readSessionToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };
}

async function doRequest(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`${DEFAULT_BASE_URL}${path}`, {
      ...options,
      signal: controller.signal,
      headers: requestHeaders(options),
    });

    if (!res.ok) {
      let detail = "";
      try { detail = await res.text(); } catch {}
      throw new Error(`SPPG Core API ${res.status}: ${detail || res.statusText}`);
    }

    if (res.status === 204) return null;
    return res.json();
  } catch (err) {
    if (err?.name === "AbortError") throw new Error("SPPG Core API terlalu lama merespons. Coba Refresh.");
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}

function request(path, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  if (method !== "GET") return doRequest(path, options);

  const key = `${DEFAULT_BASE_URL}${path}`;
  const existing = inflightGets.get(key);
  if (existing) return existing;

  const pending = doRequest(path, options).finally(() => inflightGets.delete(key));
  inflightGets.set(key, pending);
  return pending;
}

export const operationsApi = {
  health: () => request("/health"),
  getSchemaStatus: () => request("/v1/schema-status"),
  getControlTower: (date, site = "") => {
    const q = new URLSearchParams({ date });
    if (site) q.set("site", site);
    return request(`/v1/control-tower-v2?${q.toString()}`);
  },
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
  updateVendorLeadTime: (payload) => request("/v1/reference/vendor-rules/lead-time", { method: "POST", body: JSON.stringify(payload) }),
  getPurchaseOrders: ({ site = "", vendor = "", status = "", limit = 100 } = {}) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (site) q.set("site", site);
    if (vendor) q.set("vendor", vendor);
    if (status) q.set("status", status);
    return request(`/v1/purchase-orders?${q.toString()}`);
  },
  getPurchaseOrder: (purchaseOrderId) => request(`/v1/purchase-orders/${encodeURIComponent(purchaseOrderId)}`),
  createPurchaseOrder: (payload) => request("/v1/purchase-orders", { method: "POST", body: JSON.stringify(payload) }),
  previewWhatsAppReceipt: (payload) => request("/v1/receiving/whatsapp", { method: "POST", body: JSON.stringify({ ...payload, commit: false }) }),
  commitWhatsAppReceipt: (payload) => request("/v1/receiving/whatsapp", { method: "POST", body: JSON.stringify({ ...payload, commit: true }) }),
  getReceivingVariance: ({ site = "", limit = 200 } = {}) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (site) q.set("site", site);
    return request(`/v1/receiving/variance?${q.toString()}`);
  },
  parseVendorInvoice: (payload) => request("/v1/vendor-invoices/parse-whatsapp", { method: "POST", body: JSON.stringify(payload) }),
  getVendorPayables: ({ status = "", site = "", vendor = "", limit = 200 } = {}) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (status) q.set("status", status);
    if (site) q.set("site", site);
    if (vendor) q.set("vendor", vendor);
    return request(`/v1/vendor-payables?${q.toString()}`);
  },
  getVendorPayments: ({ status = "", site = "" } = {}) => {
    const q = new URLSearchParams();
    if (status) q.set("status", status);
    if (site) q.set("site", site);
    return request(`/v1/vendor-payments?${q.toString()}`);
  },
  getInventoryBalances: ({ site, search = "", limit = 300 }) => {
    const q = new URLSearchParams({ site, limit: String(limit) });
    if (search) q.set("search", search);
    return request(`/v1/inventory/balances?${q.toString()}`);
  },
  syncCalculatorPlanning: ({ site, distributionDate }) => request("/v1/calculator-planning/sync", {
    method: "POST",
    body: JSON.stringify({ site, distribution_date: distributionDate }),
  }),
  previewCalculatorPlanning: ({ site, distributionDate }) => {
    const q = new URLSearchParams({ site, distributionDate });
    return request(`/v1/calculator-planning/preview?${q.toString()}`);
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
  generateAccountantExcel: (payload, commit = false) => request("/v1/accountant-excel/from-planning", { method: "POST", body: JSON.stringify({ ...payload, commit }) }),
  markAccountantSubmissionSent: (submissionId) => request(`/v1/accountant-submissions/${encodeURIComponent(submissionId)}/mark-sent`, { method: "POST", body: "{}" }),
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
  submitReviewDecision: (eventId, decision, note = "") => request(`/v1/review-queue/${eventId}`, { method: "POST", body: JSON.stringify({ decision, note }) }),
  ingestEvent: (payload) => request("/v1/events", { method: "POST", body: JSON.stringify(payload) }),
};

export const hasOperationsBackend = Boolean(DEFAULT_BASE_URL);
export const operationsBackendUrl = DEFAULT_BASE_URL;
