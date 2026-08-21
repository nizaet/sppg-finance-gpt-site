import fs from "node:fs";
import path from "node:path";

const assetsDir = path.resolve("dist/assets");
if (!fs.existsSync(assetsDir)) {
  throw new Error("dist/assets not found after Vite build");
}

const jsFiles = fs.readdirSync(assetsDir).filter((name) => name.endsWith(".js"));
if (!jsFiles.length) {
  throw new Error("No JavaScript assets found after Vite build");
}

const bundle = jsFiles
  .map((name) => fs.readFileSync(path.join(assetsDir, name), "utf8"))
  .join("\n");

const requiredMarkers = [
  "data-po-actions-version",
  "data-po-reminder-actions",
  "data-editable-stock",
  "data-po-archive-search",
  "data-po-staged-sync",
  "data-po-sync-progress",
  "Tarik / Sinkron Pengingat",
  "Refresh PO Aktual",
  "Sinkron Semua Blok",
  "data-po-actual-calendar",
  "Kalender PO Aktual",
  "data-po-calendar-popup",
  "PO dibuat",
  "Jadwal pesan/kirim",
  "TAMBAHAN-",
  "planning_item_ids",
  "item_keys",
  "PO sudah dilakukan",
  "Konfirmasi stok gudang",
  "Buat PO Tambahan",
  "data-po-receiving-list",
  "data-po-receiving-detail",
  "data-calendar-po-receiving",
  "Konfirmasi Penerimaan",
  "Semua sesuai",
  "Penerimaan",
  "data-po-manual-load",
  "Tarik Kontak Vendor",
  "List PO belum ditarik",
  "Pengingat belum ditarik",
];

const forbiddenMarkers = [
  "data-delivery-alerts",
  "Peringatan barang belum datang setelah jam 17.00",
];

const reminderEnhancementSource = fs.readFileSync(
  path.resolve("src/operations/PoOpsEnhancements.jsx"),
  "utf8",
);
const reminderRequestCount = (reminderEnhancementSource.match(/operationsApi\.getPoReminders\(/g) || []).length;
if (reminderRequestCount !== 2) {
  throw new Error(`Expected one atomic reminder request per sync action, found ${reminderRequestCount} source calls`);
}
if (!reminderEnhancementSource.includes("date: today(), horizonDays: 2")) {
  throw new Error("Atomic reminder sync must request overdue + today + tomorrow in one horizonDays=2 snapshot");
}
if (reminderEnhancementSource.includes("date: shiftDate(today(), 1), horizonDays: 1")) {
  throw new Error("Staged tomorrow-only reminder request can expose partial data and must stay retired");
}
if (reminderEnhancementSource.includes("useEffect(() =>")) {
  throw new Error("PO enhancement must not fetch calendar or reminder data automatically on tab mount");
}

const plannerSource = fs.readFileSync(
  path.resolve("src/operations/OperationsPoPlanner.jsx"),
  "utf8",
);
if (plannerSource.includes("useEffect(() => { loadBase(); }, [activeSite])")) {
  throw new Error("PO Vendor tab must not pull list/vendor/reminder data automatically");
}
if (!plannerSource.includes('data-po-manual-load="v31"')) {
  throw new Error("PO Vendor manual-load notice is missing");
}

const missing = requiredMarkers.filter((marker) => !bundle.includes(marker));
if (missing.length) {
  throw new Error(`PO reminder built bundle missing markers: ${missing.join(", ")}`);
}
const forbidden = forbiddenMarkers.filter((marker) => bundle.includes(marker));
if (forbidden.length) {
  throw new Error(`Retired red delivery alert still present in built bundle: ${forbidden.join(", ")}`);
}

console.log("PO reminder/action + receiving UI is present in the built bundle:", requiredMarkers.join(", "));
