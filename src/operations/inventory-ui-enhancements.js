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

function ensureMasterCollapse(root) {
  if (!root) return;
  const title = Array.from(root.querySelectorAll(".ops-module h3"))
    .find((node) => node.textContent?.trim() === "Tambah atau Perbarui Klasifikasi");
  const section = title?.closest(".ops-module");
  const header = section?.querySelector(":scope > .ops-module-header");
  if (!section || !header) return;

  section.classList.add("inventory-master-collapsible");
  section.classList.toggle("inventory-master-collapsed", masterCollapsed);

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
      section.classList.toggle("inventory-master-collapsed", masterCollapsed);
      button.textContent = masterCollapsed ? "Tampilkan Master Barang" : "Sembunyikan Master Barang";
      button.setAttribute("aria-expanded", masterCollapsed ? "false" : "true");
    });
    controls.appendChild(button);
  }

  button.textContent = masterCollapsed ? "Tampilkan Master Barang" : "Sembunyikan Master Barang";
  button.setAttribute("aria-expanded", masterCollapsed ? "false" : "true");
}

function syncEditorFeedback(root) {
  const editor = root?.querySelector("#inventory-manual-edit");
  if (!editor) return;

  let feedback = editor.querySelector("[data-inventory-editor-feedback]");
  if (!feedback) {
    feedback = document.createElement("div");
    feedback.dataset.inventoryEditorFeedback = "true";
    feedback.className = "inventory-editor-feedback";
    const actions = editor.querySelector(".ops-form-grid");
    if (actions) actions.insertAdjacentElement("afterend", feedback);
    else editor.appendChild(feedback);
  }

  const error = Array.from(root.querySelectorAll(":scope > .ops-module .ops-error"))
    .find((node) => !editor.contains(node) && node.textContent?.trim());
  const success = Array.from(root.querySelectorAll(":scope > .ops-module .ops-success"))
    .find((node) => !editor.contains(node) && node.textContent?.trim());

  const message = error?.textContent?.trim() || success?.textContent?.trim() || "";
  const state = error ? "error" : success ? "success" : "";
  if (feedback.textContent !== message) feedback.textContent = message;
  feedback.classList.toggle("is-error", state === "error");
  feedback.classList.toggle("is-success", state === "success");
  feedback.hidden = !message;
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
