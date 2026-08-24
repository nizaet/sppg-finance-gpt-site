import { readSessionToken } from "./auth/session.js";

const BASE_URL = import.meta.env.VITE_SPPG_CORE_API_URL || "https://sppg-finance-gpt-site-production-5b7d.up.railway.app";
const FILENAME_KEY = "sppg.accountant.excelFilename";
const poStateByCode = new Map();
const poStateById = new Map();
let desiredFilename = "";
let decorateQueued = false;
let installed = false;

function loadFilename() {
  try { desiredFilename = sessionStorage.getItem(FILENAME_KEY) || ""; } catch { desiredFilename = ""; }
}

function saveFilename(value) {
  desiredFilename = String(value || "").trim();
  try {
    if (desiredFilename) sessionStorage.setItem(FILENAME_KEY, desiredFilename);
    else sessionStorage.removeItem(FILENAME_KEY);
  } catch {}
}

function apiPath(value) {
  try {
    const raw = typeof value === "string" ? value : value?.url;
    if (!raw) return "";
    return new URL(raw, window.location.origin).pathname;
  } catch {
    return "";
  }
}

function rememberPo(po) {
  if (!po || typeof po !== "object") return;
  const status = String(po.status || "").toUpperCase();
  const code = String(po.po_code || po.poCode || "").trim();
  const id = Number(po.id || po.purchaseOrderId || 0);
  if (code && status) poStateByCode.set(code, status);
  if (id > 0 && status) poStateById.set(id, status);
}

function rememberPoPayload(payload) {
  if (!payload || typeof payload !== "object") return;
  if (Array.isArray(payload.items)) payload.items.forEach(rememberPo);
  rememberPo(payload);
  queueDecorate();
}

function visualForStatus(status) {
  const normalized = String(status || "").toUpperCase();
  if (normalized === "RECEIVED") {
    return {
      background: "rgba(34,197,94,.16)",
      border: "#22c55e",
      text: "#15803d",
      label: "✓ Barang diterima",
    };
  }
  if (normalized === "PARTIAL_RECEIVED") {
    return {
      background: "rgba(245,158,11,.14)",
      border: "#f59e0b",
      text: "#b45309",
      label: "◐ Diterima sebagian",
    };
  }
  return null;
}

function statusForText(text) {
  const content = String(text || "");
  for (const [code, status] of poStateByCode.entries()) {
    if (code && content.includes(code)) return status;
  }
  return "";
}

function clearRuntimeBadge(parent) {
  parent?.querySelectorAll?.("[data-runtime-receiving-badge]").forEach((node) => node.remove());
}

function decoratePurchaseOrderList() {
  document.querySelectorAll("table.ops-table tbody tr").forEach((row) => {
    const status = statusForText(row.textContent);
    if (!status) return;
    const visual = visualForStatus(status);
    row.dataset.runtimeReceivingState = status;
    if (!visual) {
      row.style.removeProperty("background");
      clearRuntimeBadge(row);
      return;
    }
    row.style.background = visual.background;
    const stack = row.querySelector(".ops-status-stack");
    if (stack) {
      clearRuntimeBadge(stack);
      const badge = document.createElement("span");
      badge.dataset.runtimeReceivingBadge = "list";
      badge.textContent = visual.label;
      badge.style.cssText = `display:inline-flex;align-items:center;border-radius:999px;padding:3px 8px;font-size:10px;font-weight:800;background:${visual.border};color:#fff;margin-top:3px;`;
      stack.appendChild(badge);
    }
  });
}

function decorateCalendar() {
  document.querySelectorAll("[data-po-actual-calendar] button").forEach((button) => {
    const status = statusForText(button.textContent);
    if (!status) return;
    const visual = visualForStatus(status);
    button.dataset.runtimeReceivingState = status;
    clearRuntimeBadge(button);
    if (!visual) {
      button.style.removeProperty("background");
      button.style.removeProperty("border-color");
      return;
    }
    button.style.background = visual.background;
    button.style.borderColor = visual.border;
    const marker = document.createElement("div");
    marker.dataset.runtimeReceivingBadge = "calendar";
    marker.textContent = visual.label;
    marker.style.cssText = `margin-top:3px;font-size:11px;font-weight:800;color:${visual.text};`;
    button.appendChild(marker);
  });
}

function accountantSection() {
  return Array.from(document.querySelectorAll("section.ops-module")).find((section) => {
    const heading = section.querySelector("h3");
    return String(heading?.textContent || "").includes("Excel Belanja per Perencanaan");
  }) || null;
}

function syncFilenameInput() {
  const input = document.querySelector("input[data-runtime-excel-filename]");
  if (input && input.value !== desiredFilename) input.value = desiredFilename;
}

function ensureFilenameControl() {
  const section = accountantSection();
  if (!section) return;
  const form = section.querySelector(".ops-form-grid");
  if (!form || form.querySelector("[data-runtime-excel-filename-wrap]")) {
    syncFilenameInput();
    return;
  }

  const label = document.createElement("label");
  label.dataset.runtimeExcelFilenameWrap = "v1";
  label.append(document.createTextNode("Nama file Excel"));
  const input = document.createElement("input");
  input.dataset.runtimeExcelFilename = "v1";
  input.placeholder = "contoh: Belanja Maja 19 Agustus 2026.xlsx";
  input.value = desiredFilename;
  input.addEventListener("input", () => saveFilename(input.value));
  label.appendChild(input);
  const note = document.createElement("span");
  note.className = "ops-muted";
  note.textContent = "Boleh tanpa .xlsx. Nama ini dipakai saat Preview, Download, dan arsip Drive.";
  label.appendChild(note);

  const actionLabel = Array.from(form.children).find((node) => String(node.textContent || "").trim().startsWith("Aksi"));
  if (actionLabel) form.insertBefore(label, actionLabel);
  else form.appendChild(label);

  section.addEventListener("change", (event) => {
    const target = event.target;
    if (target === input) return;
    if (target?.matches?.("select,input[type='date']")) {
      saveFilename("");
      input.value = "";
    }
  }, { capture: true });
}

function decorate() {
  decorateQueued = false;
  decoratePurchaseOrderList();
  decorateCalendar();
  ensureFilenameControl();
}

function queueDecorate() {
  if (decorateQueued) return;
  decorateQueued = true;
  window.requestAnimationFrame(decorate);
}

function modifiedRequest(input, init = {}) {
  let nextInput = input;
  let nextInit = init;
  const path = apiPath(input);

  if (path === "/v1/accountant-excel/from-selected-plan" && String(init?.method || "GET").toUpperCase() === "POST" && desiredFilename) {
    try {
      const body = JSON.parse(String(init.body || "{}"));
      body.custom_filename = desiredFilename;
      nextInit = { ...init, body: JSON.stringify(body) };
    } catch {}
  }

  if (path === "/v1/accountant-excel/download-selected-plan" && desiredFilename && (typeof input === "string" || input instanceof URL)) {
    try {
      const url = new URL(String(input), window.location.origin);
      url.searchParams.set("customFilename", desiredFilename);
      nextInput = url.toString();
    } catch {}
  }
  return [nextInput, nextInit, path];
}

async function refreshPoState(site = "") {
  const q = new URLSearchParams({ limit: "100", includeArchived: "true" });
  if (site) q.set("site", String(site).toUpperCase());
  const token = readSessionToken();
  try {
    const response = await window.fetch(`${BASE_URL}/v1/purchase-orders-active?${q}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) return;
    rememberPoPayload(await response.json());
  } catch {}
}

export function installRuntimeUiPolish() {
  if (installed || typeof window === "undefined") return;
  installed = true;
  loadFilename();

  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const [nextInput, nextInit, path] = modifiedRequest(input, init);
    const response = await nativeFetch(nextInput, nextInit);

    if ((path === "/v1/purchase-orders" || path === "/v1/purchase-orders-active" || /^\/v1\/purchase-orders\/\d+$/.test(path)) && response.ok) {
      response.clone().json().then(rememberPoPayload).catch(() => {});
    }

    if (path === "/v1/accountant-excel/from-selected-plan" && response.ok) {
      response.clone().json().then((data) => {
        if (!desiredFilename && data?.filename) {
          saveFilename(data.filename);
          syncFilenameInput();
        }
      }).catch(() => {});
    }
    return response;
  };

  const observer = new MutationObserver(queueDecorate);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("sppg:goods-receipt-saved", (event) => {
    refreshPoState(event?.detail?.site || "");
    window.setTimeout(queueDecorate, 50);
  });

  queueDecorate();
}
