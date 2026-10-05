export const operationalCategories = [
  ["gas", "GAS"],
  ["apd", "APD (masker, sarung tangan, penutup kepala)"],
  ["alat_kebersihan", "Alat kebersihan"],
  ["lain_lain", "Lain-lain"],
  ["air_minum_galon", "Air minum/galon"],
  ["atk", "ATK"],
] as const;

export const operationalCategoryLabels = Object.fromEntries(operationalCategories) as Record<string, string>;

export const defaultOperationalItems = [
  ["Gas lpj 50 kg", "gas", "tabung", 1176000], ["Gas lpj 12 kg", "gas", "tabung", 250000],
  ["Sarung Tangan Plastik @200 pcs", "apd", "pack", 28000], ["Mama Lemon 650 ml", "alat_kebersihan", "pouch", 13900],
  ["Sarung tangan Latex/Nitril (100pcs)", "apd", "box", 75000], ["Tali rapia Hitam", "lain_lain", "roll", 24000],
  ["Tali rapia Warna", "lain_lain", "roll", 30000], ["Plastik sampah 60 x 100", "alat_kebersihan", "pack", 15000],
  ["plastik sampah 90x120", "alat_kebersihan", "pack", 15000], ["Tisu hand towels", "alat_kebersihan", "pack", 10000],
  ["Air Galon isi Ulang", "air_minum_galon", "galon", 5000], ["Masker 3 Play", "apd", "pack", 27500],
  ["Hair Net (50pcs) - Tebal", "apd", "pack", 45000], ["Karbol Larist 4L", "alat_kebersihan", "jerigen", 0],
  ["Clink Pembersih Kaca", "alat_kebersihan", "pouch", 4500], ["Soklin Lantai Lemon 770 ml", "alat_kebersihan", "pcs", 15000],
  ["Lakban Bening Besar", "lain_lain", "pcs", 7500], ["Karbol Laris 650ml", "alat_kebersihan", "pcs", 16000],
  ["Tinta Printer CF400A CF401A CF402A CF403A", "atk", "set", 0],
] as const;

const operationalPrefix = /^\[operasional:([a-z0-9_]+)\]\s*/i;

export function operationalCategoryFromNote(note: unknown, fallback = "lain_lain") {
  const match = String(note || "").match(operationalPrefix);
  return match && operationalCategoryLabels[match[1]] ? match[1] : fallback;
}

export function operationalNote(category: string, note: unknown) {
  const safeCategory = operationalCategoryLabels[category] ? category : "lain_lain";
  const clean = String(note || "").replace(operationalPrefix, "").trim();
  return `[operasional:${safeCategory}]${clean ? ` ${clean}` : ""}`;
}

export function operationalLabelFromNote(note: unknown, fallback = "lain_lain") {
  return operationalCategoryLabels[operationalCategoryFromNote(note, fallback)] || operationalCategoryLabels.lain_lain;
}
