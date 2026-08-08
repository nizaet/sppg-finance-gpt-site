
export const CATEGORIES = {
  IN_SEWA: "Pemasukan: Insentif Sewa",
  IN_OPS: "Pemasukan: Dana Operasional",
  IN_BAHAN: "Pemasukan: Dana Bahan Baku",
  LAUK: "Bahan Baku (Lauk)",
  SAYUR: "Bahan Baku (Sayur/Buah)",
  SEMBAKO: "Bahan Baku (Sembako/Bumbu)",
  PACK: "Packaging",
  OPS_UTIL: "Operasional (Utilitas)",
  OPS_GAJI: "Operasional (Gaji/Admin)",
  OPS_TRANS: "Operasional (Transport)",
  OPS_BERSIH: "Operasional (Kebersihan/APD)",
  OPS_LAIN: "Operasional (Lain-lain)",
  CAPEX: "Belanja Modal (Capex)",
  BEBAN: "Beban Profit (Non-Reimburse)",
  DIVIDEN: "Pembagian Dividen"
};

const norm = (s="") => String(s)
  .toLowerCase()
  .normalize("NFKD")
  .replace(/[^\w\s/-]/g, " ")
  .replace(/\s+/g, " ")
  .trim();

const any = (s, arr) => arr.some(x => s.includes(x));

export function normalizeCategoryForType(tx) {
  const c = String(tx.category || "");
  const d = norm(tx.desc);
  if (tx.type === "income") {
    if (any(d, ["insentif", "sewa", "jasa masak", "jasa layanan"])) return CATEGORIES.IN_SEWA;
    if (any(d, ["operasional", "dana ops", "ops", "reimburse operasional"])) return CATEGORIES.IN_OPS;
    if (any(d, ["bahan baku", "dana bahan", "dana makan", "porsi", "mbg", "makan bergizi"])) return CATEGORIES.IN_BAHAN;
    if (c.startsWith("Pemasukan")) return c;
    return CATEGORIES.IN_BAHAN;
  }
  return c;
}

export function classify(tx, memoryMap) {
  const d = norm(tx.desc);
  const type = tx.type === "income" ? "income" : "expense";
  if (type === "income") {
    return {category: normalizeCategoryForType(tx), confidence: 0.98, reason: "pemasukan dipisahkan dari biaya"};
  }

  const key = d;
  if (memoryMap && memoryMap[key]) {
    const sorted = Object.entries(memoryMap[key]).sort((a,b)=>b[1]-a[1]);
    const total = sorted.reduce((a,b)=>a+b[1],0);
    if (sorted[0][1] >= 2 && sorted[0][1] / total >= 0.82) {
      return {category: sorted[0][0], confidence: 0.94, reason: `histori item ${sorted[0][1]}/${total}`};
    }
  }

  if (any(d, ["dividen", "bagi hasil", "shareholder"])) return {category:CATEGORIES.DIVIDEN, confidence:.99, reason:"kata kunci dividen"};
  if (any(d, ["bonus", "thr", "apron", "tunjangan khusus", "insentif tambahan", "uang apresiasi"])) return {category:CATEGORIES.BEBAN, confidence:.90, reason:"beban profit/non-reimburse"};
  if (any(d, ["kulkas", "freezer", "kompor", "renovasi", "bangunan", "mesin", "aset", "stainless", "tabung gas", "panci besar", "rak"])) return {category:CATEGORIES.CAPEX, confidence:.88, reason:"aset/capex"};

  if (any(d, ["gaji", "upah", "fee", "akuntan", "ahli gizi", "admin", "relawan", "helper", "petty cash", "peety cash", "kas kecil"])) return {category:CATEGORIES.OPS_GAJI, confidence:.88, reason:"gaji/admin/kas kecil"};
  if (any(d, ["listrik", "token", "internet", "wifi", "pulsa", "air", "pdam", "gas isi ulang", "lpg"])) return {category:CATEGORIES.OPS_UTIL, confidence:.89, reason:"utilitas"};
  if (any(d, ["bensin", "parkir", "tol", "ongkir", "driver", "sewa mobil", "grab", "gojek", "lalamove", "transport"])) return {category:CATEGORIES.OPS_TRANS, confidence:.89, reason:"transport"};
  if (any(d, ["tisu", "tisue", "hand towel", "sabun", "mama lemon", "sunlight", "spons", "spon", "sapu", "pel", "karbol", "pembersih", "masker", "sarung tangan", "glove", "hair net", "plastik sampah", "tali rapia", "kebersihan", "latex", "nitril"])) return {category:CATEGORIES.OPS_BERSIH, confidence:.94, reason:"kebersihan/APD"};

  if (any(d, ["box nasi", "dus", "mika", "cup", "sendok plastik", "kertas nasi", "paper bowl", "food tray", "plastik kemasan", "stiker"])) return {category:CATEGORIES.PACK, confidence:.92, reason:"packaging"};
  if (any(d, ["ayam", "daging", "sapi", "ikan", "dori", "udang", "cumi", "telur", "tahu", "tempe", "bebek", "hati ayam", "protein"])) return {category:CATEGORIES.LAUK, confidence:.94, reason:"lauk/protein"};
  if (any(d, ["bawang", "cabe", "cabai", "tomat", "wortel", "buncis", "brokoli", "timun", "selada", "kol", "sawi", "bayam", "kangkung", "jagung", "kentang", "labu", "jahe", "lengkuas", "sereh", "daun bawang", "buah", "jeruk", "apel", "pisang", "nanas", "anggur", "melon", "semangka", "pepaya", "mangga", "sayur"])) return {category:CATEGORIES.SAYUR, confidence:.91, reason:"sayur/buah/bumbu basah"};
  if (any(d, ["beras", "minyak", "tepung", "gula", "garam", "kecap", "saus", "santan", "lada", "merica", "knorr", "totole", "msg", "cuka", "mayonaise", "mentega", "baking powder", "bumbu kering"])) return {category:CATEGORIES.SEMBAKO, confidence:.93, reason:"sembako/bumbu kering"};

  return {category:CATEGORIES.OPS_LAIN, confidence:.42, reason:"belum dikenali; perlu review"};
}

export function groupOf(category, type) {
  const c = String(category||"").toLowerCase();
  if (type === "income") {
    if (c.includes("insentif") || c.includes("sewa")) return "incSewa";
    if (c.includes("operasional")) return "incOps";
    return "incBahan";
  }
  if (c.includes("dividen")) return "dividen";
  if (c.includes("beban profit")) return "bebanProfit";
  if (c.includes("modal") || c.includes("capex")) return "capex";
  if (c.includes("bahan") || c.includes("packaging")) return "bahan";
  return "ops";
}

export function buildMemory(transactions) {
  const mem = {};
  for (const tx of transactions || []) {
    if (tx.type !== "expense") continue;
    const k = norm(tx.desc);
    if (!k || !tx.category) continue;
    mem[k] ||= {};
    mem[k][tx.category] = (mem[k][tx.category] || 0) + 1;
  }
  return mem;
}

export function parseDailyText(text, defaults={}) {
  const rows = [];
  const lines = String(text||"").split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
  const today = defaults.date || new Date().toISOString().slice(0,10);
  for (const line of lines) {
    const parts = line.split(/\t|;/).map(x=>x.trim()).filter(Boolean);
    let date = today, desc = line, qty = 1, unit = "", unitPrice = 0, amount = 0, vendor = defaults.vendor || "-", isDebt = false, type = defaults.type || "expense";
    const dateMatch = line.match(/(20\d{2}-\d{2}-\d{2})/);
    if (dateMatch) date = dateMatch[1];

    if (parts.length >= 5) {
      desc = parts[0];
      qty = parseNum(parts[1]) || 1;
      unit = parts[2] || "";
      unitPrice = parseNum(parts[3]);
      amount = parseNum(parts[4]) || qty * unitPrice;
      vendor = parts[5] || vendor;
      isDebt = /hutang|bon|belum/i.test(parts.join(" "));
    } else {
      const m = line.match(/^(.+?)\s+([\d.,/]+)\s*([a-zA-Z]+|kg|pcs|pack|box|pouch|rol|ltr|liter)?\s*(?:x|@)\s*Rp?\s*([\d.,]+)(.*)$/i);
      if (m) {
        desc = m[1].trim();
        qty = parseQty(m[2]);
        unit = m[3] || "";
        unitPrice = parseNum(m[4]);
        amount = qty * unitPrice;
        const tail = m[5] || "";
        isDebt = /hutang|bon|belum/i.test(tail);
        const vend = tail.match(/(?:vendor|supplier|suplier|hutang)\s*[:\-]?\s*([A-Za-z0-9 ._-]+)/i);
        if (vend) vendor = vend[1].trim();
      } else {
        const price = line.match(/([\d.]{4,})\s*$/);
        if (price) amount = parseNum(price[1]);
      }
      if (/pemasukan|masuk|insentif|dana bahan|dana operasional/i.test(line)) type = "income";
    }
    rows.push({date, desc, qty, unit, unitPrice, amount, orderBy: vendor, isDebt, type, status:"done"});
  }
  return rows;
}

function parseNum(v) {
  if (v === null || v === undefined) return 0;
  return Number(String(v).replace(/[^\d,-]/g,"").replace(",", ".")) || 0;
}

function parseQty(v) {
  const s = String(v).trim();
  if (s.includes("/")) {
    const [a,b] = s.split("/").map(parseNum);
    return b ? a / b : a;
  }
  return parseNum(s);
}
