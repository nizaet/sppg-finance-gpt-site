import { readSessionToken } from "../auth/session.js";

const BASE_URL = import.meta.env.VITE_SPPG_CORE_API_URL || "https://sppg-finance-gpt-site-production-5b7d.up.railway.app";
const TIMEOUT_MS = 60000;

async function request(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
  const token = readSessionToken();
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };
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
  } finally {
    clearTimeout(timeout);
  }
}

export function absoluteAccountantUrl(path) {
  if (!path) return "";
  if (/^https?:\/\//i.test(path)) return path;
  return `${BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Gagal membaca file invoice"));
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

  generateSelectedPlanExcel: ({ site, distributionDate, calculatorDocumentId }, commit = false) => request(
    "/v1/accountant-excel/from-selected-plan",
    {
      method: "POST",
      body: JSON.stringify({
        site,
        distribution_date: distributionDate,
        calculator_document_id: calculatorDocumentId,
        commit,
      }),
    },
  ),

  uploadInvoice: async ({ submissionId, file, invoiceNumber, invoiceAmount }) => {
    const contentBase64 = await fileToBase64(file);
    return request(`/v1/accountant-submissions/${encodeURIComponent(submissionId)}/invoice-upload`, {
      method: "POST",
      body: JSON.stringify({
        file_name: file.name,
        mime_type: file.type || "application/octet-stream",
        content_base64: contentBase64,
        invoice_number: invoiceNumber || null,
        invoice_amount: invoiceAmount == null ? null : Number(invoiceAmount),
        received_at: null,
      }),
    });
  },

  createMakerFromInvoice: (invoiceId) => request(`/v1/accountant-invoices/${encodeURIComponent(invoiceId)}/create-maker`, {
    method: "POST",
    body: "{}",
  }),
};
