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
  "Menyinkronkan revisi Kalkulator",
  "Refresh PO Aktual",
  "Sinkron Semua Blok",
  "4/4 · Kalender PO",
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
  "data-po-site-tabs",
  "data-po-site-panel",
  "PO Vendor per Dapur",
  "Hasil tarikan MAJA dan CEMPLANG disimpan pada tab masing-masing",
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
  throw new Error(`Expected one fresh reminder request plus one empty-state discovery request, found ${reminderRequestCount} source calls`);
}
if (!reminderEnhancementSource.includes("date: today(), horizonDays: 2")) {
  throw new Error("Atomic reminder sync must request overdue + today + tomorrow in one horizonDays=2 snapshot");
}
if (reminderEnhancementSource.includes("date: shiftDate(today(), 1), horizonDays: 1")) {
  throw new Error("Staged tomorrow-only reminder request can expose partial data and must stay retired");
}
if (!reminderEnhancementSource.includes("deactivateMissing: true")) {
  throw new Error("Reminder sync must retire a stale Calculator snapshot when its source plan was deleted");
}
if (!reminderEnhancementSource.includes("refresh: true")) {
  throw new Error("Reminder sync must bypass the short v4 cache after refreshing Calculator planning");
}
if (reminderEnhancementSource.includes("useEffect(() =>")) {
  throw new Error("PO enhancement must not fetch calendar or reminder data automatically on tab mount");
}
if (!/const syncAllBlocks = async \(\) => \{[\s\S]*?await refreshCalendar\(\);[\s\S]*?const refreshCalendar/.test(reminderEnhancementSource)) {
  throw new Error("Sinkron Semua Blok must explicitly populate the selected-month PO calendar");
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

const siteTabsSource = fs.readFileSync(
  path.resolve("src/operations/OperationsPoSiteTabs.jsx"),
  "utf8",
);
if (!siteTabsSource.includes('<OperationsPoPlanner fixedSite={site} />')) {
  throw new Error("MAJA and CEMPLANG PO planners must be mounted as independent site workspaces");
}
if (!siteTabsSource.includes('hidden={activeSite !== site}')) {
  throw new Error("PO site switch must hide, not unmount, the inactive workspace so pulled data is retained");
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
