import { readSessionToken } from "../auth/session.js";

const BASE_URL = import.meta.env.VITE_SPPG_CORE_API_URL || "https://sppg-finance-gpt-site-production-5b7d.up.railway.app";
const TIMEOUT_MS = 60000;

function headersFor(options = {}) {
  const token = readSessionToken();
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };
}

async function request(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
  const headers = { "Content-Type": "application/json", ...headersFor(options) };
  try {
    const response = await fetch(`${BASE_URL}${path}`, { ...options, headers, signal: controller.signal });
    if (!response.ok) {
      let detail = "";
      try { detail = await response.text(); } catch {}
      throw new Error(`SPPG Core API ${response.status}: ${detail || response.statusText}`);
    }
    return response.status === 204 ? null : response.json();
  } catch (error) {
    if (error?.name === "AbortError") throw new Error(`SPPG Core API terlalu lama merespons: ${path}`);
    throw error;
  } finally { clearTimeout(timeout); }
}

async function download(path, fallbackFilename) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(`${BASE_URL}${path}`, { method: "GET", headers: headersFor(), signal: controller.signal });
    if (!response.ok) {
      let detail = "";
      try { detail = await response.text(); } catch {}
      throw new Error(`SPPG Core API ${response.status}: ${detail || response.statusText}`);
    }
    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    return { blob: await response.blob(), filename: fallbackFilename || match?.[1] || "daftar_belanja.xlsx" };
  } catch (error) {
    if (error?.name === "AbortError") throw new Error(`SPPG Core API terlalu lama merespons: ${path}`);
    throw error;
  } finally { clearTimeout(timeout); }
}

export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Gagal membaca file"));
    reader.onload = () => {
      const raw = String(reader.result || "");
      resolve(raw.includes(",") ? raw.split(",", 2)[1] : raw);
    };
    reader.readAsDataURL(file);
  });
}

export const accountantApi = {
  getPlanningOptions: ({ site, distributionDate }) => {
    const q = new URLSearchParams({ site, distributionDate });
    return request(`/v1/accountant-excel/planning-options?${q}`);
  },
  generateSelectedPlanExcel: ({ site, distributionDate, calculatorDocumentId, customFilename = "" }, commit = false) => request(
    "/v1/accountant-excel/from-selected-plan-fresh",
    { method: "POST", body: JSON.stringify({ site, distribution_date: distributionDate, calculator_document_id: calculatorDocumentId, custom_filename: customFilename || null, commit }) },
  ),
  downloadSelectedPlanExcel: ({ downloadUrl, filename }) => download(downloadUrl, filename),
  uploadInvoice: async ({ submissionId, file, invoiceNumber, invoiceAmount }) => {
    const contentBase64 = await fileToBase64(file);
    return request(`/v1/accountant-submissions/${encodeURIComponent(submissionId)}/invoice-upload`, {
      method: "POST",
      body: JSON.stringify({ file_name: file.name, mime_type: file.type || "application/octet-stream", content_base64: contentBase64, invoice_number: invoiceNumber || null, invoice_amount: invoiceAmount == null ? null : Number(invoiceAmount), received_at: null }),
    });
  },
  previewInvoiceDocument: async ({ file, site = null, category = null, submissionId = null }) => {
    const contentBase64 = await fileToBase64(file);
    return request("/v1/accountant-invoices/document-preview", {
      method: "POST",
      body: JSON.stringify({
        file_name: file.name, mime_type: file.type || "application/octet-stream", content_base64: contentBase64,
        site: site || null, category: category || null, accountant_submission_id: submissionId || null,
      }),
    });
  },
  commitInvoiceDocument: async ({ file, preview, site, category, submissionId = null }) => {
    const contentBase64 = await fileToBase64(file);
    return request("/v1/accountant-invoices/direct-upload", {
      method: "POST",
      body: JSON.stringify({
        file_name: file.name, mime_type: file.type || "application/octet-stream", content_base64: contentBase64,
        site, category, accountant_submission_id: submissionId || null,
        invoice_number: preview.invoiceNumber, invoice_date: preview.invoiceDate,
        period_start: preview.periodStart || null, period_end: preview.periodEnd || null,
        invoice_amount: Number(preview.invoiceAmount), lines: preview.lines || [],
        parsed_payload: preview.raw || {}, parse_confidence: preview.confidence == null ? null : Number(preview.confidence),
        create_maker: false, commit: true,
      }),
    });
  },
  getDirectInvoices: (site = "") => request(`/v1/accountant-invoices/direct?site=${encodeURIComponent(site || "")}`),
  getAllInvoices: (site = "") => request(`/v1/accountant-invoices/all?site=${encodeURIComponent(site || "")}`),
  previewApprovalEvidence: async ({ file, site = null }) => {
    const contentBase64 = await fileToBase64(file);
    return request("/v1/approval-evidence/document-preview", {
      method: "POST",
      body: JSON.stringify({ file_name: file.name, mime_type: file.type || "application/octet-stream", content_base64: contentBase64, site: site || null, commit: false }),
    });
  },
  commitApprovalEvidence: async ({ file, site = null, parsedPayload }) => {
    const contentBase64 = await fileToBase64(file);
    return request("/v1/approval-evidence/upload", {
      method: "POST",
      body: JSON.stringify({ file_name: file.name, mime_type: file.type || "application/octet-stream", content_base64: contentBase64, site: site || null, parsed_payload: parsedPayload || null, commit: true }),
    });
  },
  createMakerFromInvoice: (invoiceId) => request(`/v1/accountant-invoices/${encodeURIComponent(invoiceId)}/create-maker`, { method: "POST", body: "{}" }),
  deleteSubmissionCascade: (submissionId) => request(`/v1/accountant-submissions/${encodeURIComponent(submissionId)}/cascade`, { method: "DELETE" }),
  confirmMakerApproved: (makerId) => request(`/v1/bgn-makers/${encodeURIComponent(makerId)}/approve-now`, {
    method: "POST",
    body: "{}",
  }),
  cancelMakerApproval: (makerId) => request(`/v1/bgn-makers/${encodeURIComponent(makerId)}/cancel-approval`, {
    method: "POST",
    body: "{}",
  }),
  confirmMakerPaid: async ({ makerId, file = null, evidenceUri = null, commit = true }) => {
    const payload = { commit, paid_at: null, evidence_uri: evidenceUri || null, actor: "web-owner" };
    if (file) {
      payload.file_name = file.name;
      payload.mime_type = file.type || "application/octet-stream";
      payload.content_base64 = await fileToBase64(file);
    }
    return request(`/v1/bgn-makers/${encodeURIComponent(makerId)}/confirm-paid`, { method: "POST", body: JSON.stringify(payload) });
  },
};
