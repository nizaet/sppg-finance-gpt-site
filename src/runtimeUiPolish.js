import { readSessionToken } from "./auth/session.js";

const BASE_URL = import.meta.env.VITE_SPPG_CORE_API_URL || "https://sppg-finance-gpt-site-production-5b7d.up.railway.app";
const poStateByCode = new Map();
const poStateById = new Map();
let decorateQueued = false;
let installed = false;

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

function decorate() {
  decorateQueued = false;
  decoratePurchaseOrderList();
  decorateCalendar();
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

  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const [nextInput, nextInit, path] = modifiedRequest(input, init);
    const response = await nativeFetch(nextInput, nextInit);

    if ((path === "/v1/purchase-orders" || path === "/v1/purchase-orders-active" || /^\/v1\/purchase-orders\/\d+$/.test(path)) && response.ok) {
      response.clone().json().then(rememberPoPayload).catch(() => {});
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
