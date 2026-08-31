import { readSessionToken } from "../auth/session.js";

let installed = false;
let observer = null;
let masterCollapsed = true;

function findInventoryRoot() {
  const editor = document.getElementById("inventory-manual-edit");
  if (editor) return editor.closest(".ops-domain-stack");
  const title = Array.from(document.querySelectorAll(".ops-module h3"))
    .find((node) => node.textContent?.trim() === "Stok Gudang Saat Ini");
  return title?.closest(".ops-domain-stack") || null;
}

function applyMasterState(section, button) {
  const hasCollapsed = section.classList.contains("inventory-master-collapsed");
  if (hasCollapsed !== masterCollapsed) {
    section.classList.toggle("inventory-master-collapsed", masterCollapsed);
  }
  const label = masterCollapsed ? "Tampilkan Master Barang" : "Sembunyikan Master Barang";
  const expanded = masterCollapsed ? "false" : "true";
  if (button.textContent !== label) button.textContent = label;
  if (button.getAttribute("aria-expanded") !== expanded) button.setAttribute("aria-expanded", expanded);
}

function ensureMasterCollapse(root) {
  if (!root) return;
  const title = Array.from(root.querySelectorAll(".ops-module h3"))
    .find((node) => node.textContent?.trim() === "Tambah atau Perbarui Klasifikasi");
  const section = title?.closest(".ops-module");
  const header = section?.querySelector(":scope > .ops-module-header");
  if (!section || !header) return;

  if (!section.classList.contains("inventory-master-collapsible")) {
    section.classList.add("inventory-master-collapsible");
  }

  let controls = header.querySelector("[data-inventory-master-toggle-wrap]");
  if (!controls) {
    controls = document.createElement("div");
    controls.className = "ops-inline-controls";
    controls.dataset.inventoryMasterToggleWrap = "true";
    header.appendChild(controls);
  }

  let button = controls.querySelector("[data-inventory-master-toggle]");
  if (!button) {
    button = document.createElement("button");
    button.type = "button";
    button.dataset.inventoryMasterToggle = "true";
    button.addEventListener("click", () => {
      masterCollapsed = !masterCollapsed;
      applyMasterState(section, button);
    });
    controls.appendChild(button);
  }

  applyMasterState(section, button);
}

function normalizeItemName(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function inputByLabel(editor, title) {
  const label = Array.from(editor.querySelectorAll("label"))
    .find((node) => node.textContent?.trim().startsWith(title));
  return label?.querySelector("input") || null;
}

function feedbackNode(editor) {
  let feedback = editor.querySelector("[data-inventory-editor-feedback]");
  if (!feedback) {
    feedback = document.createElement("div");
    feedback.dataset.inventoryEditorFeedback = "true";
    feedback.className = "inventory-editor-feedback";
    const actions = editor.querySelector(".ops-form-grid");
    if (actions) actions.insertAdjacentElement("afterend", feedback);
    else editor.appendChild(feedback);
  }
  return feedback;
}

function setLocalFeedback(editor, message, state = "") {
  editor.dataset.inventoryLocalFeedback = message || "";
  editor.dataset.inventoryLocalFeedbackState = state || "";
  const feedback = feedbackNode(editor);
  feedback.textContent = message || "";
  feedback.classList.toggle("is-error", state === "error");
  feedback.classList.toggle("is-success", state === "success");
  feedback.hidden = !message;
}

async function apiJson(path, options = {}) {
  const token = readSessionToken();
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = "";
    try { detail = await response.text(); } catch {}
    throw new Error(`SPPG Core API ${response.status}: ${detail || response.statusText}`);
  }
  return response.status === 204 ? null : response.json();
}

async function findInventoryMaster(name) {
  const query = new URLSearchParams({ search: name });
  const data = await apiJson(`/v1/inventory/items?${query}`);
  const target = normalizeItemName(name);
  const rows = data?.items || [];
  return rows.find((row) => normalizeItemName(row.canonical_name) === target)
    || rows.find((row) => (row.aliases || []).some((alias) => normalizeItemName(alias) === target))
    || (rows.length === 1 ? rows[0] : null);
}

async function saveItemRename(originalName, newName, unit) {
  const [oldMaster, newMaster] = await Promise.all([
    findInventoryMaster(originalName),
    findInventoryMaster(newName),
  ]);

  if (oldMaster?.code && newMaster?.code && oldMaster.code !== newMaster.code) {
    throw new Error(`Nama ${newName} sudah menjadi Master Barang lain. Buka Master Barang untuk menggabungkan alias agar tidak membuat dua jenis barang.`);
  }

  const master = oldMaster || newMaster;
  const aliases = Array.from(new Set([
    ...(master?.aliases || []),
    originalName,
  ].map((value) => String(value || "").trim()).filter(Boolean)));

  return apiJson("/v1/inventory/items", {
    method: "POST",
    body: JSON.stringify({
      code: master?.code || null,
      canonical_name: newName,
      category_code: master?.category_code || null,
      base_unit: master?.base_unit || unit || null,
      aliases,
      metadata: master?.metadata || {},
      commit: true,
    }),
  });
}

function ensureRenameCorrection(editor) {
  if (!editor) return;
  const nameInput = inputByLabel(editor, "Barang");
  const targetInput = inputByLabel(editor, "Stok baru");
  const unitInput = inputByLabel(editor, "Unit");
  if (!nameInput || !targetInput) return;

  if (!editor.dataset.inventoryOriginalCaptured) {
    editor.dataset.inventoryOriginalCaptured = "true";
    editor.dataset.inventoryOriginalItemName = nameInput.value || "";
    editor.dataset.inventoryOriginalTargetBalance = targetInput.value || "0";
    delete editor.dataset.inventoryLocalFeedback;
    delete editor.dataset.inventoryLocalFeedbackState;
  }

  if (editor.dataset.inventoryRenameHandlerInstalled === "true") return;
  editor.dataset.inventoryRenameHandlerInstalled = "true";

  editor.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button || !button.textContent?.includes("Simpan Koreksi")) return;

    if (editor.dataset.inventorySkipRenameInterceptor === "true") {
      delete editor.dataset.inventorySkipRenameInterceptor;
      return;
    }

    const originalName = editor.dataset.inventoryOriginalItemName || "";
    const currentName = String(nameInput.value || "").trim();
    const nameChanged = currentName && normalizeItemName(currentName) !== normalizeItemName(originalName);
    if (!nameChanged) return;

    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();

    const originalQty = Number(editor.dataset.inventoryOriginalTargetBalance || 0);
    const targetQty = Number(targetInput.value || 0);
    const qtyChanged = Number.isFinite(targetQty) && Math.abs(targetQty - originalQty) > 0.00005;

    button.disabled = true;
    setLocalFeedback(editor, `Menyimpan nama ${originalName} → ${currentName}…`);
    try {
      await saveItemRename(originalName, currentName, unitInput?.value || "");
      editor.dataset.inventoryOriginalItemName = currentName;
      if (qtyChanged) {
        setLocalFeedback(editor, "Nama barang sudah disimpan. Melanjutkan koreksi jumlah stok…", "success");
        editor.dataset.inventorySkipRenameInterceptor = "true";
        button.disabled = false;
        button.click();
        return;
      }

      setLocalFeedback(editor, `Nama barang berhasil diperbaiki menjadi ${currentName}. Jumlah stok tetap ${targetInput.value}.`, "success");
      window.setTimeout(() => window.location.reload(), 650);
    } catch (error) {
      button.disabled = false;
      setLocalFeedback(editor, error?.message || "Gagal menyimpan perubahan nama barang.", "error");
    }
  }, true);
}

function syncEditorFeedback(root) {
  const editor = root?.querySelector("#inventory-manual-edit");
  if (!editor) return;

  ensureRenameCorrection(editor);
  const feedback = feedbackNode(editor);

  const localMessage = editor.dataset.inventoryLocalFeedback || "";
  const localState = editor.dataset.inventoryLocalFeedbackState || "";
  if (localMessage) {
    if (feedback.textContent !== localMessage) feedback.textContent = localMessage;
    feedback.classList.toggle("is-error", localState === "error");
    feedback.classList.toggle("is-success", localState === "success");
    feedback.hidden = false;
    return;
  }

  const error = Array.from(root.querySelectorAll(":scope > .ops-module .ops-error"))
    .find((node) => !editor.contains(node) && node.textContent?.trim());
  const success = Array.from(root.querySelectorAll(":scope > .ops-module .ops-success"))
    .find((node) => !editor.contains(node) && node.textContent?.trim());

  const message = error?.textContent?.trim() || success?.textContent?.trim() || "";
  const state = error ? "error" : success ? "success" : "";
  if (feedback.textContent !== message) feedback.textContent = message;
  if (feedback.classList.contains("is-error") !== (state === "error")) {
    feedback.classList.toggle("is-error", state === "error");
  }
  if (feedback.classList.contains("is-success") !== (state === "success")) {
    feedback.classList.toggle("is-success", state === "success");
  }
  if (feedback.hidden === Boolean(message)) feedback.hidden = !message;
}

function enhance() {
  const root = findInventoryRoot();
  if (!root) return;
  ensureMasterCollapse(root);
  syncEditorFeedback(root);
}

export function installInventoryUiEnhancements() {
  if (installed || typeof document === "undefined") return;
  installed = true;
  enhance();
  observer = new MutationObserver(enhance);
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
}

export function uninstallInventoryUiEnhancements() {
  observer?.disconnect();
  observer = null;
  installed = false;
}
