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
  "data-delivery-alerts",
  "data-delivery-alert-actions",
  "data-po-archive-search",
  "TAMBAHAN-",
  "planning_item_ids",
  "item_keys",
  "PO sudah dilakukan",
  "Konfirmasi stok gudang",
  "Buat PO Tambahan",
  "Peringatan barang belum datang setelah jam 17.00",
  "PO sudah terkirim",
  "Barang datang sesuai",
  "Datang tidak sesuai",
  "Delivery alert saved but alert refresh failed",
];

const missing = requiredMarkers.filter((marker) => !bundle.includes(marker));
if (missing.length) {
  throw new Error(`PO reminder built bundle missing markers: ${missing.join(", ")}`);
}

console.log("PO reminder/action UI is present in the built bundle:", requiredMarkers.join(", "));