
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Utensils, FileSpreadsheet, Upload, Download, RotateCcw, RefreshCcw, CloudUpload,
  LayoutDashboard, Plus, CreditCard, FileText, Users, Package, BrainCircuit, ShieldAlert,
  Wallet, Landmark, TrendingUp, ArrowRightLeft, Eye, Edit2, Trash2, Search, Save,
  ArrowDownCircle, ArrowUpCircle, Sparkles, Loader2, X, CheckCircle2, Printer,
  PieChart as PieChartIcon, History, DollarSign, Eraser, ChefHat, Lightbulb,
  RefreshCw, Database, AlertTriangle, Check, ClipboardPaste
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend,
  ResponsiveContainer, PieChart as RePieChart, Pie, Cell, AreaChart, Area
} from "recharts";
import { initializeApp } from "firebase/app";
import {
  getFirestore, doc, setDoc, getDoc, collection, getDocs, query, orderBy,
  onSnapshot, deleteDoc, writeBatch, serverTimestamp
} from "firebase/firestore";

const CATEGORIES = [
  "Pemasukan: Insentif Sewa",
  "Pemasukan: Dana Operasional",
  "Pemasukan: Dana Bahan Baku",
  "Bahan Baku (Lauk)",
  "Bahan Baku (Sayur)",
  "Bahan Baku (Sayur/Buah)",
  "Bahan Baku (Sembako)",
  "Bahan Baku (Sembako/Bumbu)",
  "Packaging",
  "Operasional (Utilitas)",
  "Operasional (Gaji)",
  "Operasional (Gaji/Admin)",
  "Operasional (Transport)",
  "Operasional (Kebersihan)",
  "Operasional (Kebersihan/APD)",
  "Belanja Modal (Capex)",
  "Beban Profit (Non-Reimburse)",
  "Pembagian Dividen",
  "Lainnya (Ops)"
];

const MONTHS = ["Januari","Februari","Maret","April","Mei","Juni","Juli","Agustus","September","Oktober","November","Desember"];

const defaultFirebaseConfig = {
  apiKey: "AIzaSyB72MVySugfHF_vu11WYv-s9uiQbRpftk4",
  authDomain: "sppg-finance-gpt.firebaseapp.com",
  projectId: "sppg-finance-gpt",
  storageBucket: "sppg-finance-gpt.firebasestorage.app",
  messagingSenderId: "732611890148",
  appId: "1:732611890148:web:5dcfab93d1d351b10315f1",
  measurementId: "G-DZERB61197"
};

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY || defaultFirebaseConfig.apiKey,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || defaultFirebaseConfig.authDomain,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || defaultFirebaseConfig.projectId,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET || defaultFirebaseConfig.storageBucket,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID || defaultFirebaseConfig.messagingSenderId,
  appId: import.meta.env.VITE_FIREBASE_APP_ID || defaultFirebaseConfig.appId,
  measurementId: import.meta.env.VITE_FIREBASE_MEASUREMENT_ID || defaultFirebaseConfig.measurementId
};

// v8.1: routing dapur diputuskan saat browser membuka URL.
// Dua Railway service boleh menyajikan bundle JS yang sama.
const RUNTIME_HOST_SITE_MAP = Object.freeze({
  "sppg-finance-gpt-site-production.up.railway.app": {
    siteId: "sppg-maja-gpt-site",
    databaseId: "(default)",
    siteLabel: "SPPG MAJA BARU",
    siteShortLabel: "Maja"
  },
  "sppg-finance-gpt-site-production-fc7e.up.railway.app": {
    siteId: "sppg-cemplang2-gpt-site",
    databaseId: "cemplang2",
    siteLabel: "SPPG CEMPLANG 2",
    siteShortLabel: "Cemplang 2"
  }
});

const currentHostname =
  typeof window !== "undefined" ? window.location.hostname.toLowerCase() : "";

const runtimeSite = RUNTIME_HOST_SITE_MAP[currentHostname] || null;

const siteId =
  runtimeSite?.siteId ||
  import.meta.env.VITE_SITE_ID ||
  "sppg-maja-gpt-site";

const firestoreDatabaseId =
  runtimeSite?.databaseId ||
  import.meta.env.VITE_FIRESTORE_DATABASE_ID ||
  "(default)";

const siteLabel =
  runtimeSite?.siteLabel ||
  import.meta.env.VITE_SITE_LABEL ||
  "SPPG MAJA BARU";

const siteShortLabel =
  runtimeSite?.siteShortLabel ||
  import.meta.env.VITE_SITE_SHORT_LABEL ||
  "Maja";

// BEGIN RUNTIME BROWSER BRAND V8.3
const browserBrand =
  firestoreDatabaseId === "cemplang2"
    ? {
        title: "Cemplang 2 | SPPG Finance",
        favicon: "/favicon-cemplang.svg?v=83"
      }
    : {
        title: "Maja | SPPG Finance",
        favicon: "/favicon-maja.svg?v=83"
      };

if (typeof document !== "undefined") {
  document.title = browserBrand.title;

  let favicon = document.querySelector("link[rel='icon']");

  if (!favicon) {
    favicon = document.createElement("link");
    favicon.rel = "icon";
    document.head.appendChild(favicon);
  }

  favicon.type = "image/svg+xml";
  favicon.sizes = "any";
  favicon.href = browserBrand.favicon;
}
// END RUNTIME BROWSER BRAND V8.3

const hasFirebaseConfig = Boolean(firebaseConfig.apiKey && firebaseConfig.projectId);
const app = hasFirebaseConfig ? initializeApp(firebaseConfig) : null;

const db = app
  ? (firestoreDatabaseId === "(default)"
      ? getFirestore(app)
      : getFirestore(app, firestoreDatabaseId))
  : null;

const formatIDR = (num) => {
  const n = Number(num) || 0;
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n);
};

const formatAxisIDR = (num) => {
  const n = Number(num) || 0;
  const abs = Math.abs(n);
  if (abs >= 1000000000) return `${(n / 1000000000).toFixed(abs >= 10000000000 ? 0 : 1)}M`; // miliar
  if (abs >= 1000000) return `${(n / 1000000).toFixed(abs >= 10000000 ? 0 : 1)}jt`;
  if (abs >= 1000) return `${(n / 1000).toFixed(abs >= 10000 ? 0 : 1)}rb`;
  return String(Math.round(n));
};

const toMonthKey = (dateStr) => {
  const d = new Date(normalizeDate(dateStr));
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}`;
};
const monthLabelFromKey = (key) => {
  if (!/^\d{4}-\d{2}$/.test(String(key))) return "Semua Bulan";
  const [y,m] = String(key).split("-");
  return `${MONTHS[Number(m)-1]} ${y}`;
};
const escapeHtml = (v) => String(v ?? "").replace(/[&<>"]/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[ch]));
const downloadTextFile = (filename, text, mime) => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: mime }));
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
};

const formatNumberInput = (num) => new Intl.NumberFormat("id-ID").format(Number(num) || 0);
const parseIDRInput = (val) => {
  const clean = String(val ?? "").replace(/\D/g, "");
  return clean ? parseInt(clean, 10) : 0;
};
const safeNumber = (val) => {
  if (val === null || val === undefined || val === "") return 0;
  if (typeof val === "number") return Number.isFinite(val) ? val : 0;
  return Number(String(val).replace(/[^\d.-]/g, "")) || 0;
};
const safeString = (val) => {
  if (val === null || val === undefined) return "";
  if (typeof val === "string") return val;
  if (typeof val === "object") return normalizeDate(val);
  return String(val);
};

const timestampMs = (val) => {
  if (!val) return 0;
  if (typeof val === "number") return val;
  if (typeof val === "string") {
    const ms = Date.parse(val);
    return Number.isNaN(ms) ? 0 : ms;
  }
  if (typeof val === "object") {
    if (typeof val.toDate === "function") return val.toDate().getTime();
    if (val.seconds) return val.seconds * 1000;
  }
  return 0;
};

const txInputMs = (t) => timestampMs(t.updatedAt) || timestampMs(t.createdAt) || timestampMs(t.createdAtClient) || timestampMs(t.date);

const txOutstanding = (t) => {
  const amount = safeNumber(t.amount);
  const paid = safeNumber(t.paidAmount);
  const status = String(t.paymentStatus || "").toLowerCase();
  const rawDebt = Boolean(t.isDebt) || status === "unpaid" || status === "partial";
  const outstanding = Math.max(0, amount - paid);
  if (rawDebt && status !== "paid" && outstanding <= 0) return amount;
  return outstanding;
};

const txIsDebtActive = (t) => {
  const status = String(t.paymentStatus || "").toLowerCase();
  if (status === "paid") return false;
  return Boolean(t.isDebt) || status === "unpaid" || status === "partial" || txOutstanding(t) > 0;
};
const normalizeDate = (dateStr) => {
  if (!dateStr) return new Date().toISOString().split("T")[0];
  if (typeof dateStr === "object") {
    if (dateStr.seconds) return new Date(dateStr.seconds * 1000).toISOString().split("T")[0];
    try { return new Date(dateStr).toISOString().split("T")[0]; } catch { return new Date().toISOString().split("T")[0]; }
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(String(dateStr))) return String(dateStr);
  const d = new Date(dateStr);
  if (!Number.isNaN(d.getTime())) return d.toISOString().split("T")[0];
  return new Date().toISOString().split("T")[0];
};
const generateId = () => {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
};

const parseMoney = (str) => safeNumber(str);

const categorizeByDesc = (desc) => {
  const d = String(desc || "").toLowerCase();
  if (!d) return "Lainnya (Ops)";
  if (d.match(/(dividen|bagi hasil|shareholder)/)) return "Pembagian Dividen";
  if (d.match(/(apron|kursi|bonus|sppi|thr|tunjangan)/)) return "Beban Profit (Non-Reimburse)";
  if (d.match(/(gaji|upah|tip|fee|helper|chef|karyawan|tukang masak|relawan|petty|kas kecil|akuntan|ahli gizi|admin)/)) return "Operasional (Gaji/Admin)";
  if (d.match(/(insentif|sewa gedung|sewa alat|jasa masak|upah masak|6 juta|6jt)/)) return "Pemasukan: Insentif Sewa";
  if (d.match(/(dana operasional|biaya ops|reimburse ops|ganti uang lelah)/)) return "Pemasukan: Dana Operasional";
  if (d.match(/(dana bahan|porsi|paket makan|makan bergizi|mbg|dana makan|pembelian bahan)/)) return "Pemasukan: Dana Bahan Baku";
  if (d.match(/(ayam|sapi|telur|daging|ikan|dori|udang|cumi|bebek|protein|tahu|tempe)/)) return "Bahan Baku (Lauk)";
  if (d.match(/(bawang|cabe|cabai|tomat|wortel|sayur|buah|jeruk|apel|kentang|tauge|bayam|jagung|buncis|sereh|jahe|lengkuas|daun bawang)/)) return "Bahan Baku (Sayur/Buah)";
  if (d.match(/(beras|minyak|tepung|gula|garam|kecap|saus|santan|bumbu|msg|penyedap|kacang|knorr|totole|cuka|lada)/)) return "Bahan Baku (Sembako/Bumbu)";
  if (d.match(/(box nasi|dus|mika|cup|sendok plastik|kertas nasi|plastik wrap|paper)/)) return "Packaging";
  if (d.match(/(listrik|token|air|gas|internet|pulsa|wifi|lpg)/)) return "Operasional (Utilitas)";
  if (d.match(/(sabun|spon|spons|sunlight|mama lemon|sapu|pel|pembersih|plastik sampah|kebersihan|masker|sarung tangan|glove|tisu|tissue|hair net|tali rafia|rapia)/)) return "Operasional (Kebersihan/APD)";
  if (d.match(/(bensin|parkir|tol|sewa mobil|ongkir|grab|gojek|lalamove|driver|transport)/)) return "Operasional (Transport)";
  if (d.match(/(beli alat|beli panci|beli kompor|beli mobil|renovasi|bangunan|tanah|aset|kulkas|freezer|mesin|rak stainless)/)) return "Belanja Modal (Capex)";
  return "Lainnya (Ops)";
};

const normalizeCategory = (cat, desc, type) => {
  const manualCategory = String(cat || "").trim();

  // PENTING:
  // Kategori dari backup/manual/GPT yang sudah dikirim JANGAN ditimpa lagi.
  // Backup lama memang memakai kategori seperti:
  // "Bahan Baku", "Bahan Baku (Lauk/Sayur/Sembako/Packaging)",
  // "Operasional (Gaji/Listrik/Transport)", dll.
  // Itu dianggap kamus/manual truth.
  if (manualCategory) return manualCategory;

  return categorizeByDesc(desc);
};

const normalizeTx = (t) => {
  const date = normalizeDate(t.date);
  const desc = safeString(t.desc || t.description || t.name).trim();
  let type = t.type === "income" ? "income" : "expense";
  let category = normalizeCategory(t.category, desc, type);
  if (category.includes("Pemasukan")) type = "income";

  const qty = safeNumber(t.qty) || 1;
  const unitPrice = safeNumber(t.unitPrice);
  const amount = safeNumber(t.amount) || (qty * unitPrice);

  const statusRaw = String(t.paymentStatus || "").toLowerCase();
  const rawDebt = Boolean(t.isDebt) || statusRaw === "unpaid" || statusRaw === "partial";
  const paymentStatus = statusRaw || (rawDebt ? "unpaid" : "paid");

  let paidAmount;
  if (paymentStatus === "paid") paidAmount = amount;
  else if (paymentStatus === "unpaid") paidAmount = 0;
  else if (paymentStatus === "partial") paidAmount = Math.min(amount, safeNumber(t.paidAmount));
  else paidAmount = rawDebt ? 0 : amount;

  const isDebt = type !== "income" && paymentStatus !== "paid" && (rawDebt || Math.max(0, amount - paidAmount) > 0);

  return {
    id: String(t.id || generateId()).replace(/[/.#[\]]/g, "_"),
    date,
    desc,
    amount,
    qty,
    unit: safeString(t.unit || ""),
    unitPrice,
    type,
    status: t.status || "done",
    category,
    orderBy: safeString(t.orderBy || t.vendor || "-") || "-",
    isDebt,
    paymentStatus: isDebt ? paymentStatus : "paid",
    paidAmount: isDebt ? paidAmount : amount,
    paidDate: safeString(t.paidDate || ""),
    source: safeString(t.source || "legacy"),
    classificationConfidence: safeNumber(t.classificationConfidence),
    classificationReason: safeString(t.classificationReason || ""),
    note: safeString(t.note || ""),

    // AUDIT STATUS PERSISTENCE V8.8
    auditStatus: safeString(t.auditStatus || "").toLowerCase(),
    auditCompletedAt: safeString(t.auditCompletedAt || ""),

    createdAt: t.createdAt || null,
    updatedAt: t.updatedAt || null,
    createdAtClient: safeString(t.createdAtClient || t.inputAt || "")
  };
};

const getTransactionGroup = (t) => {
  const cat = String(t.category || "").toLowerCase();
  const descLower = String(t.desc || "").toLowerCase();
  if (t.type === "income") {
    if (cat.includes("sewa") || cat.includes("insentif")) return "sewa";
    if (cat.includes("operasional") || cat.includes("biaya") || cat.includes("ops")) return "ops";
    return "bahan";
  }
  if (cat.includes("pembagian dividen")) return "dividen";
  if (cat.includes("beban profit") || cat.includes("non-reimburse")) return "beban";
  if (cat.includes("modal") || cat.includes("capex")) return "modal";
  if (cat.includes("bahan") || cat.includes("packaging")) return "bahan";
  if (cat.includes("operasional") || cat.includes("gaji") || cat.includes("transport") || cat.includes("utilitas") || cat.includes("kebersihan")) return "ops";
  if (descLower.includes("dividen")) return "dividen";
  if (descLower.includes("bonus")) return "beban";
  return "ops";
};

const getWeekRange = (dateStr) => {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return "Invalid Range";
  const day = d.getDay();
  const start = new Date(d.getTime() - day * 86400000);
  const end = new Date(start.getTime() + 6 * 86400000);
  const short = ["Jan","Feb","Mar","Apr","Mei","Jun","Jul","Agu","Sep","Okt","Nov","Des"];
  return `${start.getDate()} ${short[start.getMonth()]} - ${end.getDate()} ${short[end.getMonth()]}`;
};

const getPeriodKey = (dateStr, filterType) => {
  if (!dateStr) return "Unknown";
  if (filterType === "daily") return dateStr;
  if (filterType === "monthly") {
    const d = new Date(dateStr);
    if (Number.isNaN(d.getTime())) return "Unknown Month";
    return `${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  }
  return getWeekRange(dateStr);
};

const parseBulkText = (text, defaultType = "expense") => {
  const rows = [];
  for (const raw of String(text || "").split(/\n+/)) {
    let line = raw.trim();
    if (!line) continue;

    const isDebt = /(hutang|bon|belum lunas)/i.test(line);
    const isPaid = /(lunas|paid|terbayar)/i.test(line);
    let type = /(insentif|dana operasional|dana bahan|pemasukan|masuk)/i.test(line) ? "income" : defaultType;

    let date = new Date().toISOString().split("T")[0];
    const dateMatch = line.match(/(\d{4}-\d{2}-\d{2})/);
    if (dateMatch) {
      date = dateMatch[1];
      line = line.replace(dateMatch[1], "").trim();
    }

    let qty = 1, unit = "", unitPrice = 0, amount = 0, desc = line;
    const pattern = line.match(/^(.+?)\s+([\d.,]+)\s*([a-zA-ZÀ-ÿ/]+)?\s*[xX*@]\s*([\d.,]+)/);
    if (pattern) {
      desc = pattern[1].trim();
      qty = safeNumber(pattern[2]);
      unit = pattern[3] || "";
      unitPrice = safeNumber(pattern[4]);
      amount = qty * unitPrice;
    } else {
      const m = line.match(/^(.+?)\s+([\d.,]{4,})(?:\s|$)/);
      if (m) {
        desc = m[1].trim();
        amount = safeNumber(m[2]);
        unitPrice = amount;
      }
    }

    desc = desc.replace(/\b(hutang|bon|belum lunas|lunas|paid|koperasi)\b/gi, "").trim();
    const vendor = /koperasi/i.test(raw) ? "Koperasi" : "-";
    const category = normalizeCategory(categorizeByDesc(desc), desc, type);
    if (category.includes("Pemasukan")) type = "income";
    rows.push(normalizeTx({
      date, desc, qty, unit, unitPrice, amount, type, category, orderBy: vendor,
      isDebt: type === "expense" && isDebt && !isPaid,
      paymentStatus: type === "expense" && isDebt && !isPaid ? "unpaid" : "paid",
      paidAmount: type === "expense" && isDebt && !isPaid ? 0 : amount,
      source: "site_bulk"
    }));
  }
  return rows;
};

function Button({ children, className = "", variant = "default", size = "md", ...props }) {
  return <button className={`btn ${variant} ${size} ${className}`} {...props}>{children}</button>;
}
function Card({ children, className = "" }) { return <div className={`card ${className}`}>{children}</div>; }
function CardHeader({ children, className = "" }) { return <div className={`card-header ${className}`}>{children}</div>; }
function CardTitle({ children, className = "" }) { return <h3 className={`card-title ${className}`}>{children}</h3>; }
function CardDescription({ children }) { return <p className="card-desc">{children}</p>; }
function CardContent({ children, className = "" }) { return <div className={`card-content ${className}`}>{children}</div>; }
function Badge({ children, className = "", variant = "default" }) { return <span className={`badge ${variant} ${className}`}>{children}</span>; }
function Input(props) { return <input {...props} className={`input ${props.className || ""}`} />; }
function Textarea(props) { return <textarea {...props} className={`textarea ${props.className || ""}`} />; }
function Table({ children, className = "" }) { return <table className={`table ${className}`}>{children}</table>; }
function TableHeader({ children, className = "" }) { return <thead className={className}>{children}</thead>; }
function TableBody({ children }) { return <tbody>{children}</tbody>; }
function TableFooter({ children }) { return <tfoot>{children}</tfoot>; }
function TableRow({ children, className = "" }) { return <tr className={className}>{children}</tr>; }
function TableHead({ children, className = "" }) { return <th className={className}>{children}</th>; }
function TableCell({ children, className = "", colSpan }) { return <td colSpan={colSpan} className={className}>{children}</td>; }


const normalizeDescKey = (desc) => String(desc || "")
  .toLowerCase()
  .replace(/[^a-z0-9\u00c0-\u024f]+/gi, " ")
  .replace(/\b(kg|pcs|pc|box|pack|pouch|rol|roll|liter|ltr|rp|x|dan|di|ke|dari|yang|untuk|hutang|lunas|koperasi)\b/g, " ")
  .replace(/\s+/g, " ")
  .trim();

const descTokens = (desc) => normalizeDescKey(desc)
  .split(" ")
  .filter(w => w.length >= 3)
  .slice(0, 10);

function SmartCateringAccountant() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const fileInputRef = useRef(null);
  const csvInputRef = useRef(null);

  const [initialCapital, setInitialCapital] = useState(50000000);
  const [actualBalance, setActualBalance] = useState(0);
  const [transactions, setTransactions] = useState([]);
  const [inventory, setInventory] = useState([]);
  const [shareholders, setShareholders] = useState([]);
  const [paidPeriods, setPaidPeriods] = useState({});
  const [lastSaved, setLastSaved] = useState("Memeriksa sinkronisasi...");
  const [isDataLoaded, setIsDataLoaded] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [periodFilter, setPeriodFilter] = useState("weekly");
  const [monthFilter, setMonthFilter] = useState("ALL");
  const [customStartDate, setCustomStartDate] = useState("");
  const [customEndDate, setCustomEndDate] = useState("");
  const [globalSearch, setGlobalSearch] = useState("");
  const [trackingStatusFilter, setTrackingStatusFilter] = useState("ALL");
  const [trackingCategoryFilter, setTrackingCategoryFilter] = useState("ALL");
  const [trackingVendorFilter, setTrackingVendorFilter] = useState("ALL");
  const [trackingDateMode, setTrackingDateMode] = useState("ALL");
  const [trackingMonthFilter, setTrackingMonthFilter] = useState("ALL");
  const [trackingStartDate, setTrackingStartDate] = useState("");
  const [trackingEndDate, setTrackingEndDate] = useState("");
  const [trackingSort, setTrackingSort] = useState("LAST_INPUT");
  const [selectedTrackingIds, setSelectedTrackingIds] = useState([]);
  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedDetail, setSelectedDetail] = useState(null);
  const [detailViewType, setDetailViewType] = useState(null);
  const [detailSearch, setDetailSearch] = useState("");
  const [detailSort, setDetailSort] = useState("LAST_INPUT");
  const [editOpen, setEditOpen] = useState(false);
  const [currentEdit, setCurrentEdit] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmData, setConfirmData] = useState({ title: "", msg: "", action: null });
  const [editCapitalOpen, setEditCapitalOpen] = useState(false);
  const [tempCapital, setTempCapital] = useState(0);
  const [backupOpen, setBackupOpen] = useState(false);
  const [backupList, setBackupList] = useState([]);
  const [isLoadingBackups, setIsLoadingBackups] = useState(false);
  const [sheetSyncOpen, setSheetSyncOpen] = useState(false);
  const [googleSheetUrl, setGoogleSheetUrl] = useState(() => typeof window !== "undefined" ? (localStorage.getItem("sppg_google_sheet_webapp_url") || "") : "");
  const [editInventoryOpen, setEditInventoryOpen] = useState(false);
  const [currentEditInventory, setCurrentEditInventory] = useState(null);
  const [aiAnalysisResult, setAiAnalysisResult] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isBulkProcessing, setIsBulkProcessing] = useState(false);
  const [bulkStatus, setBulkStatus] = useState("");
  const [bulkIncomeText, setBulkIncomeText] = useState("");
  const [bulkExpenseText, setBulkExpenseText] = useState("");
  const [bulkInventoryText, setBulkInventoryText] = useState("");
  const [debtVendorFilter, setDebtVendorFilter] = useState("ALL");
  const [debtCategoryFilter, setDebtCategoryFilter] = useState("ALL");
  const [inventorySearch, setInventorySearch] = useState("");
  const [inventoryCategoryFilter, setInventoryCategoryFilter] = useState("ALL");
  const [inventoryPriceFilter, setInventoryPriceFilter] = useState("ALL");
  const [auditFilter, setAuditFilter] = useState("NEED_ACTION");
  const [selectedAuditIds, setSelectedAuditIds] = useState([]);
  const [newItem, setNewItem] = useState({ name: "", qty: "", unit: "", valuePerUnit: "", category: "Bahan Baku (Sembako/Bumbu)" });
  const [newTrans, setNewTrans] = useState({
    date: new Date().toISOString().split("T")[0],
    desc: "", amount: "", unitPrice: "", qty: "", unit: "",
    type: "expense", status: "done", category: "Bahan Baku (Lauk)", orderBy: "-", isDebt: false
  });
  const [divCalcStart, setDivCalcStart] = useState(new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split("T")[0]);
  const [divCalcEnd, setDivCalcEnd] = useState(new Date().toISOString().split("T")[0]);
  const [dividendConfig, setDividendConfig] = useState({
    sourceInsentifPct: 80,
    targetProfitBahanPct: 10,
    distributionDate: new Date().toISOString().split("T")[0],
    periodLabel: new Date().toLocaleString("id-ID", { month: "long", year: "numeric" }),
    customAmount: 0,
    mode: "auto"
  });
  const [manualDistributions, setManualDistributions] = useState({});
  const [menuPlanner, setMenuPlanner] = useState({ pax: 100, budget: 15000 });
  const [menuResult, setMenuResult] = useState(null);

  const paths = useMemo(() => {
    if (!db) return null;
    return {
      meta: () => doc(db, "gpt_sites", siteId, "ledger", "meta"),
      transactions: () => collection(db, "gpt_sites", siteId, "ledger", "meta", "transactions"),
      inventory: () => collection(db, "gpt_sites", siteId, "ledger", "meta", "inventory"),
      shareholders: () => collection(db, "gpt_sites", siteId, "ledger", "meta", "shareholders"),
      backups: () => collection(db, "gpt_sites", siteId, "ledger", "meta", "backups"),
      backupTransactions: (backupId) => collection(db, "gpt_sites", siteId, "ledger", "meta", "backups", String(backupId), "transactions"),
      backupInventory: (backupId) => collection(db, "gpt_sites", siteId, "ledger", "meta", "backups", String(backupId), "inventory"),
      backupShareholders: (backupId) => collection(db, "gpt_sites", siteId, "ledger", "meta", "backups", String(backupId), "shareholders")
    };
  }, []);


  const categoryMemory = useMemo(() => {
    const exact = new Map();
    const examples = [];
    const addCount = (map, key, category) => {
      if (!key || !category || category === "Lainnya (Ops)") return;
      const cur = map.get(key) || {};
      cur[category] = (cur[category] || 0) + 1;
      map.set(key, cur);
    };
    for (const t of transactions) {
      if (!t.desc || !t.category) continue;
      const key = normalizeDescKey(t.desc);
      const tokens = descTokens(t.desc);
      addCount(exact, key, t.category);
      if (tokens.length) examples.push({ tokens, category: t.category, desc: t.desc });
    }
    return { exact, examples };
  }, [transactions]);

  const mostFrequentCategory = (counts) => {
    if (!counts) return null;
    return Object.entries(counts).sort((a,b)=>b[1]-a[1])[0]?.[0] || null;
  };

  const learnCategoryFromHistory = (desc, type = "expense") => {
    const fallback = normalizeCategory(categorizeByDesc(desc), desc, type);
    const key = normalizeDescKey(desc);
    const exact = mostFrequentCategory(categoryMemory.exact.get(key));
    if (exact) return exact;
    const tokens = new Set(descTokens(desc));
    if (!tokens.size) return fallback;
    const scores = {};
    for (const ex of categoryMemory.examples) {
      let overlap = 0;
      for (const t of ex.tokens) if (tokens.has(t)) overlap += 1;
      if (overlap >= 2) scores[ex.category] = (scores[ex.category] || 0) + overlap;
    }
    const learned = Object.entries(scores).sort((a,b)=>b[1]-a[1])[0];
    return learned && learned[1] >= 2 ? learned[0] : fallback;
  };

  useEffect(() => {
    if (!db || !paths) {
      setIsDataLoaded(true);
      setLastSaved("Firebase config belum tersedia");
      return;
    }

    let unsubTx = null, unsubInv = null, unsubSh = null;
    const start = async () => {
      try {
        const metaSnap = await getDoc(paths.meta());
        if (metaSnap.exists()) {
          const meta = metaSnap.data();
          setInitialCapital(safeNumber(meta.initialCapital));
          setActualBalance(safeNumber(meta.actualBalance));
          setPaidPeriods(meta.paidPeriods || {});
        }

        unsubTx = onSnapshot(query(paths.transactions(), orderBy("date", "desc")), snap => {
          const rows = snap.docs.map(d => normalizeTx({ id: d.id, ...d.data() }));
          setTransactions(rows);
          setIsDataLoaded(true);
          setLastSaved(`Firebase ${siteShortLabel} · DB ${firestoreDatabaseId} · ${rows.length} transaksi`);
        }, err => {
          console.error(err);
          setLastSaved("Gagal membaca transaksi: " + err.message);
          setIsDataLoaded(true);
        });

        unsubInv = onSnapshot(paths.inventory(), snap => {
          const rows = snap.docs.map(d => {
            const data = d.data();
            return {
              id: d.id,
              ...data,
              name: safeString(data.name || d.id),
              qty: safeNumber(data.qty),
              unit: safeString(data.unit || ""),
              valuePerUnit: safeNumber(data.valuePerUnit),
              category: safeString(data.category || "Tanpa Kategori"),
              priceSource: safeString(data.priceSource || ""),
              lastStockDate: safeString(data.lastStockDate || "")
            };
          }).sort((a,b)=>String(a.name).localeCompare(String(b.name), "id-ID"));
          setInventory(rows);
          setLastSaved(`Firebase ${siteShortLabel} · DB ${firestoreDatabaseId} · ${rows.length} stok`);
        }, err => {
          console.error(err);
          setLastSaved("Gagal membaca stok Firebase: " + err.message);
        });

        unsubSh = onSnapshot(paths.shareholders(), snap => {
          setShareholders(snap.docs.map(d => ({ id: d.id, ...d.data(), pct: safeNumber(d.data().pct), mgmtFee: safeNumber(d.data().mgmtFee) })));
        });
      } catch (err) {
        console.error(err);
        setLastSaved("Gagal init Firebase: " + err.message);
        setIsDataLoaded(true);
      }
    };
    start();
    return () => {
      if (unsubTx) unsubTx();
      if (unsubInv) unsubInv();
      if (unsubSh) unsubSh();
    };
  }, [paths]);

  const saveMeta = async (patch = {}) => {
    if (!db || !paths) throw new Error("Firebase belum terhubung di aplikasi.");
    await setDoc(paths.meta(), {
      initialCapital,
      actualBalance,
      paidPeriods,
      schemaVersion: 6,
      lastUpdated: new Date().toISOString(),
      updatedAt: serverTimestamp(),
      ...patch
    }, { merge: true });
  };

  const batchWriteDocs = async (colRef, items, transform = x => x) => {
    if (!db) return;
    for (let i = 0; i < items.length; i += 450) {
      const batch = writeBatch(db);
      for (const item of items.slice(i, i + 450)) {
        const docId = String(item.id || generateId()).replace(/[/.#[\]]/g, "_");
        batch.set(doc(colRef, docId), transform({ ...item, id: docId }), { merge: true });
      }
      await batch.commit();
    }
  };

  const clearCollection = async (colRef) => {
    if (!db) return;
    const snap = await getDocs(colRef);
    const docs = snap.docs;
    for (let i = 0; i < docs.length; i += 450) {
      const batch = writeBatch(db);
      for (const d of docs.slice(i, i + 450)) batch.delete(d.ref);
      await batch.commit();
    }
  };

  const addTransactions = async (rows, source = "manual") => {
    const txs = rows.map(r => normalizeTx({ ...r, id: r.id || generateId(), source }));
    setTransactions(prev => [...txs, ...prev]);
    if (db) {
      await batchWriteDocs(paths.transactions(), txs, x => ({ ...x, updatedAt: serverTimestamp() }));
      await saveMeta();
    }
    setLastSaved(`${txs.length} transaksi masuk Firebase`);
  };


  const quickUpdateTransaction = async (id, patch) => {
    const current = transactions.find(t => t.id === id);
    if (!current) return;
    const next = normalizeTx({ ...current, ...patch });
    setTransactions(prev => prev.map(t => t.id === id ? next : t));
    if (db) await setDoc(doc(paths.transactions(), String(id)), { ...next, updatedAt: serverTimestamp() }, { merge: true });
  };

  const applyRecommendedCategory = async (id, category) => {
    await quickUpdateTransaction(id, { category, type: String(category).includes("Pemasukan") ? "income" : "expense", auditStatus: "done", auditCompletedAt: new Date().toISOString() });
  };

  const markAuditDone = async (ids) => {
    const list = Array.isArray(ids) ? ids : [ids];
    if (!list.length) return;
    const updates = transactions.filter(t => list.includes(t.id)).map(t => ({ ...t, auditStatus: "done", auditCompletedAt: new Date().toISOString() }));
    setTransactions(prev => prev.map(t => list.includes(t.id) ? { ...t, auditStatus: "done", auditCompletedAt: new Date().toISOString() } : t));
    if (db && paths) await batchWriteDocs(paths.transactions(), updates, x => ({ ...x, updatedAt: serverTimestamp() }));
    setSelectedAuditIds(prev => prev.filter(id => !list.includes(id)));
  };

  const handleAddTrans = async () => {
    if (!newTrans.desc) return;
    let cat = newTrans.category || learnCategoryFromHistory(newTrans.desc, newTrans.type);
    let type = cat.includes("Pemasukan") ? "income" : newTrans.type;
    let finalAmount = safeNumber(newTrans.amount) || (safeNumber(newTrans.qty) * safeNumber(newTrans.unitPrice));
    if (!finalAmount) return alert("Nilai transaksi belum valid.");
    await addTransactions([{
      ...newTrans,
      category: cat,
      type,
      amount: finalAmount,
      paymentStatus: newTrans.isDebt ? "unpaid" : "paid",
      paidAmount: newTrans.isDebt ? 0 : finalAmount,
      source: "site_manual"
    }], "site_manual");
    setNewTrans({ ...newTrans, desc: "", amount: "", unitPrice: "", qty: "", unit: "", isDebt: false, type: "expense" });
  };

  const handleDeleteTrans = async (id) => {
    setTransactions(prev => prev.filter(t => t.id !== id));
    setSelectedTrackingIds(prev => prev.filter(x => x !== id));
    if (db) await deleteDoc(doc(paths.transactions(), String(id)));
  };

  const openEdit = (t) => {
    const debtActive = txIsDebtActive(t);
    const status = debtActive ? (String(t.paymentStatus || "").toLowerCase() === "partial" ? "partial" : "unpaid") : "paid";
    setCurrentEdit({
      ...t,
      isDebt: debtActive,
      paymentStatus: status,
      paidAmount: status === "paid" ? safeNumber(t.amount) : (status === "partial" ? safeNumber(t.paidAmount) : 0)
    });
    setEditOpen(true);
  };

  const saveEdit = async () => {
    const finalAmount = safeNumber(currentEdit.qty) && safeNumber(currentEdit.unitPrice)
      ? safeNumber(currentEdit.qty) * safeNumber(currentEdit.unitPrice)
      : safeNumber(currentEdit.amount);

    const status = String(currentEdit.paymentStatus || (currentEdit.isDebt ? "unpaid" : "paid")).toLowerCase();
    const finalIsDebt = status !== "paid" || Boolean(currentEdit.isDebt);
    const finalPaidAmount = status === "paid"
      ? finalAmount
      : status === "partial"
        ? Math.min(finalAmount, safeNumber(currentEdit.paidAmount))
        : 0;

    const updated = normalizeTx({
      ...currentEdit,
      amount: finalAmount,
      isDebt: finalIsDebt,
      paymentStatus: finalIsDebt ? status : "paid",
      paidAmount: finalPaidAmount
    });
    setTransactions(prev => prev.map(t => t.id === updated.id ? updated : t));
    if (db) await setDoc(doc(paths.transactions(), updated.id), { ...updated, updatedAt: serverTimestamp() }, { merge: true });
    setEditOpen(false);
  };

  const handlePayDebt = (id) => {
    const t = transactions.find(x => x.id === id);
    if (!t) return;
    confirmAction("Konfirmasi Pelunasan", "Yakin tandai LUNAS?", async () => {
      const patch = {
        isDebt: false,
        paymentStatus: "paid",
        paidAmount: safeNumber(t.amount),
        paidDate: new Date().toISOString().split("T")[0],
        status: "done",
        updatedAt: serverTimestamp()
      };
      setTransactions(prev => prev.map(x => x.id === id ? { ...x, ...patch } : x));
      if (db) await setDoc(doc(paths.transactions(), String(id)), patch, { merge: true });
    });
  };

  const handlePayAllDebts = () => {
    const debtList = transactions.filter(t => t.type === "expense" && txIsDebtActive(t) && txOutstanding(t) > 0);
    if (!debtList.length) return alert("Tidak ada hutang yang perlu dibayar.");
    confirmAction("Lunasi SEMUA Hutang?", `Anda akan melunasi ${debtList.length} transaksi. Total: ${formatIDR(analytics.totalDebt)}.`, async () => {
      const today = new Date().toISOString().split("T")[0];
      const updates = debtList.map(t => ({ ...t, isDebt: false, paymentStatus: "paid", paidAmount: t.amount, paidDate: today }));
      setTransactions(prev => prev.map(t => updates.find(u => u.id === t.id) || t));
      if (db) await batchWriteDocs(paths.transactions(), updates, x => ({ ...x, updatedAt: serverTimestamp() }));
    });
  };

  const handleResetData = () => {
    confirmAction("Reset Data Lokal", "Data di layar akan dikosongkan. Firebase tidak dihapus massal otomatis.", () => {
      setTransactions([]);
      setInventory([]);
    });
  };

  const buildDatabasePayload = () => ({
    initialCapital,
    actualBalance,
    transactions,
    inventory,
    shareholders,
    paidPeriods,
    siteId,
    schemaVersion: 7.5,
    lastUpdated: new Date().toISOString()
  });

  const handleExportJSON = () => {
    const payload = buildDatabasePayload();
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `SmartCatering_Backup_${new Date().toISOString().split("T")[0]}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const applyImportedPayload = async (data, source = "restore_backup") => {
    const txs = (data.transactions || []).map(t => normalizeTx({ ...t, source: t.source || source }));
    const inv = (data.inventory || []).map(i => ({
      ...i,
      id: String(i.id || generateId()).replace(/[/.#[\]]/g, "_"),
      name: safeString(i.name || i.id),
      qty: safeNumber(i.qty),
      unit: safeString(i.unit || ""),
      valuePerUnit: safeNumber(i.valuePerUnit),
      category: safeString(i.category || "Tanpa Kategori")
    }));
    const sh = (data.shareholders || []).map(x => ({ ...x, id: x.id || generateId(), pct: safeNumber(x.pct), mgmtFee: safeNumber(x.mgmtFee) }));
    const nextCapital = safeNumber(data.initialCapital);
    const nextBalance = safeNumber(data.actualBalance);
    const nextPaidPeriods = data.paidPeriods || {};
    setInitialCapital(nextCapital);
    setActualBalance(nextBalance);
    setPaidPeriods(nextPaidPeriods);
    setTransactions(txs);
    setInventory(inv);
    setShareholders(sh);
    if (db && paths) {
      await clearCollection(paths.transactions());
      await clearCollection(paths.inventory());
      await clearCollection(paths.shareholders());
      await saveMeta({ initialCapital: nextCapital, actualBalance: nextBalance, paidPeriods: nextPaidPeriods, restoredAt: new Date().toISOString() });
      await batchWriteDocs(paths.transactions(), txs, x => ({ ...x, updatedAt: serverTimestamp() }));
      await batchWriteDocs(paths.inventory(), inv, x => ({ ...x, updatedAt: serverTimestamp() }));
      await batchWriteDocs(paths.shareholders(), sh, x => ({ ...x, updatedAt: serverTimestamp() }));
    }
    return { txs, inv, sh };
  };

  const handleImportFile = async (e) => {
    const file = e.target.files?.[0]; if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      confirmAction(
        "Restore JSON?",
        `Data aktif akan diganti dari file ${file.name}. Transaksi: ${(data.transactions || []).length}, Stok: ${(data.inventory || []).length}. Lanjutkan?`,
        async () => {
          try {
            const { txs, inv, sh } = await applyImportedPayload(data, "restore_backup_json");
            alert(`✅ Restore JSON sukses.\nTransaksi: ${txs.length}\nStok: ${inv.length}\nShareholder: ${sh.length}`);
          } catch (err) {
            alert("❌ Gagal restore JSON: " + err.message);
          }
        }
      );
    } catch (err) { alert("Gagal membaca file JSON: " + err.message); }
    e.target.value = "";
  };

  const handleImportCSV = (e) => {
    const file = e.target.files?.[0]; if (!file) return;
    const reader = new FileReader();
    reader.onload = async ev => {
      const lines = String(ev.target.result || "").split(/\r?\n/).filter(Boolean);
      const rows = [];
      let start = /tanggal|date/i.test(lines[0] || "") ? 1 : 0;
      for (let i = start; i < lines.length; i++) {
        const cols = lines[i].split(/,(?=(?:(?:[^"]*"){2})*[^"]*$)/).map(x => x.trim().replace(/^"|"$/g, ""));
        if (cols.length < 3) continue;
        const date = normalizeDate(cols[0]);
        const desc = cols[1];
        const amount = parseMoney(cols[4] || cols[2]);
        const category = cols[2] && cols.length >= 10 ? cols[2] : categorizeByDesc(desc);
        const typeStr = cols[3] || "";
        const type = /masuk|income|pemasukan/i.test(typeStr) || category.includes("Pemasukan") ? "income" : "expense";
        rows.push(normalizeTx({
          date, desc, category, type, amount,
          qty: cols[5] || 1, unit: cols[6] || "", unitPrice: cols[7] || amount,
          orderBy: cols[8] || "-", isDebt: /ya|true|1|hutang/i.test(cols[9] || "")
        }));
      }
      await addTransactions(rows, "csv_import");
      alert(`Import CSV berhasil: ${rows.length} transaksi.`);
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  const makeSheetTable = (title, headers, rows) => `
    <h2>${escapeHtml(title)}</h2>
    <table>
      <thead><tr>${headers.map(h => `<th>${escapeHtml(h)}</th>`).join("")}</tr></thead>
      <tbody>${rows.map(r => `<tr>${r.map(c => `<td>${escapeHtml(c)}</td>`).join("")}</tr>`).join("")}</tbody>
    </table>`;

  const handleExportExcelStyled = () => {
    const reportRows = analytics.sortedPeriods.map(p => [p.period, p.incSewa, p.incBahan, p.expBahan, p.incOps, p.expOps, p.expCapex, p.expProfitBurden, p.expDividend, p.netProfit, p.cashFlow]);
    const txRows = transactions.map(t => [t.date, t.desc, t.category, t.type === "income" ? "Pemasukan" : "Pengeluaran", t.amount, t.qty || "", t.unit || "", t.unitPrice || "", t.orderBy || "", t.isDebt ? "YA" : "TIDAK", t.paymentStatus || "", t.paidAmount || 0, t.source || "", t.id]);
    const invRows = inventory.map(i => [i.name, i.category || "Tanpa Kategori", i.qty, i.unit || "", i.valuePerUnit || 0, safeNumber(i.qty) * safeNumber(i.valuePerUnit), i.priceSource || "", i.lastStockDate || ""]);
    const shRows = shareholders.map(s => [s.name, s.pct, s.mgmtFee || 0]);
    const html = `<!doctype html><html><head><meta charset="utf-8" />
      <style>
        body{font-family:Arial,sans-serif;color:#1f2937} h1{background:#0f172a;color:#fff;padding:14px} h2{margin-top:24px;color:#0f172a}
        table{border-collapse:collapse;width:100%;margin-bottom:20px} th{background:#0f766e;color:#fff;font-weight:700} th,td{border:1px solid #cbd5e1;padding:7px;font-size:12px} tr:nth-child(even){background:#f8fafc}.right{text-align:right}.money{mso-number-format:'\\#\\,\\#\\#0'}
      </style></head><body>
      <h1>Database Keuangan SPPG MAJA BARU - ${new Date().toLocaleString("id-ID")}</h1>
      ${makeSheetTable("Ringkasan Laba Rugi", ["Periode","Insentif","Dana Bahan","Belanja Bahan","Dana Ops","Belanja Ops","Capex","Beban Profit","Dividen","Profit Bersih","Arus Kas"], reportRows)}
      ${makeSheetTable("Transaksi", ["Tanggal","Deskripsi","Kategori","Tipe","Jumlah","Qty","Satuan","Harga Satuan","Vendor","Hutang","Payment Status","Paid Amount","Source","ID"], txRows)}
      ${makeSheetTable("Gudang", ["Nama Barang","Kategori","Qty","Satuan","Harga/Unit","Total","Price Source","Last Stock Date"], invRows)}
      ${makeSheetTable("Shareholder", ["Nama","Saham %","Management Fee %"], shRows)}
      </body></html>`;
    downloadTextFile(`SPPG_Keuangan_DB_${new Date().toISOString().split("T")[0]}.xls`, html, "application/vnd.ms-excel;charset=utf-8");
  };

  const handleGoogleSheetExport = async () => {
    if (!googleSheetUrl.trim()) return alert("Isi URL Google Apps Script Web App dulu.");
    localStorage.setItem("sppg_google_sheet_webapp_url", googleSheetUrl.trim());
    const resp = await fetch(googleSheetUrl.trim(), {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=utf-8" },
      body: JSON.stringify({ action: "export", siteId, payload: buildDatabasePayload() })
    });
    const text = await resp.text();
    if (!resp.ok) throw new Error(text);
    alert("✅ Export ke Google Sheet terkirim. Response: " + text.slice(0, 200));
  };

  const handleGoogleSheetImport = async () => {
    if (!googleSheetUrl.trim()) return alert("Isi URL Google Apps Script Web App dulu.");
    localStorage.setItem("sppg_google_sheet_webapp_url", googleSheetUrl.trim());
    const resp = await fetch(googleSheetUrl.trim(), {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=utf-8" },
      body: JSON.stringify({ action: "import", siteId })
    });
    const data = await resp.json();
    const payload = data.payload || data;
    confirmAction("Import dari Google Sheet?", `Data aktif akan diganti dari Google Sheet. Transaksi: ${(payload.transactions || []).length}, Stok: ${(payload.inventory || []).length}. Lanjutkan?`, async () => {
      const { txs, inv, sh } = await applyImportedPayload(payload, "google_sheet_import");
      alert(`✅ Import Google Sheet selesai.\\nTransaksi: ${txs.length}\\nStok: ${inv.length}\\nShareholder: ${sh.length}`);
      setSheetSyncOpen(false);
    });
  };

  const handleExportTransactionsCSV = () => {
    let csv = "\uFEFFTanggal,Deskripsi,Kategori,Tipe,Jumlah_Total,Qty,Satuan,Harga_Satuan,Vendor,Status_Hutang,Payment_Status,Paid_Amount,Source,ID_Sistem\n";
    for (const t of transactions) {
      csv += [
        t.date,
        `"${String(t.desc || "").replace(/"/g, '""')}"`,
        `"${String(t.category || "").replace(/"/g, '""')}"`,
        t.type === "income" ? "Pemasukan" : "Pengeluaran",
        t.amount,
        t.qty || "",
        `"${String(t.unit || "").replace(/"/g, '""')}"`,
        t.unitPrice || "",
        `"${String(t.orderBy || "").replace(/"/g, '""')}"`,
        t.isDebt ? "YA" : "TIDAK",
        t.paymentStatus || "",
        t.paidAmount || 0,
        t.source || "",
        t.id
      ].join(",") + "\n";
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = `Database_Transaksi_SPPG_${new Date().toISOString().split("T")[0]}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const handleExportInventoryCSV = () => {
    let csv = "\uFEFFNama Barang,Kategori,Stok,Satuan,Harga/Unit,Total Nilai,Price Source,Last Stock Date\n";
    csv += inventory.map(i => `"${String(i.name || "").replace(/"/g, '""')}","${String(i.category || "").replace(/"/g, '""')}",${i.qty},"${String(i.unit || "").replace(/"/g, '""')}",${i.valuePerUnit},${safeNumber(i.qty) * safeNumber(i.valuePerUnit)},"${String(i.priceSource || "").replace(/"/g, '""')}","${String(i.lastStockDate || "").replace(/"/g, '""')}"`).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = `Stok_Gudang_SPPG_${new Date().toISOString().split("T")[0]}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const handleSaveToCloud = async () => {
    setIsSaving(true);
    try {
      if (!db || !paths) throw new Error("Firebase belum terhubung. Backup cloud tidak bisa dibuat.");
      const backupId = new Date().toISOString().replace(/[^\d]/g, "").slice(0,14);

      await saveMeta();

      await setDoc(doc(paths.backups(), backupId), {
        createdAt: serverTimestamp(),
        createdAtClient: new Date().toISOString(),
        backupType: "full_snapshot_subcollections",
        schemaVersion: 7.5,
        counts: { transactions: transactions.length, inventory: inventory.length, shareholders: shareholders.length },
        initialCapital,
        actualBalance,
        paidPeriods
      }, { merge: true });

      await batchWriteDocs(paths.backupTransactions(backupId), transactions, x => ({ ...x, backupSavedAt: new Date().toISOString() }));
      await batchWriteDocs(paths.backupInventory(backupId), inventory, x => ({ ...x, backupSavedAt: new Date().toISOString() }));
      await batchWriteDocs(paths.backupShareholders(backupId), shareholders, x => ({ ...x, backupSavedAt: new Date().toISOString() }));

      setLastSaved(`Titik Backup cloud penuh dibuat: ${new Date().toLocaleTimeString("id-ID")}`);
      alert(`✅ Titik backup cloud penuh berhasil dibuat.\nTransaksi: ${transactions.length}\nStok: ${inventory.length}\nShareholder: ${shareholders.length}`);
    } catch (error) {
      alert("❌ Gagal membuat backup cloud: " + error.message);
    } finally { setIsSaving(false); }
  };

  const openBackupDialog = async () => {
    setBackupOpen(true);
    setIsLoadingBackups(true);
    try {
      if (!db || !paths) throw new Error("Firebase belum terhubung.");
      const q = query(paths.backups(), orderBy("createdAtClient", "desc"));
      const snap = await getDocs(q);
      setBackupList(snap.docs.map(d => ({ id: d.id, ...d.data() })));
    } catch (err) {
      console.error(err);
      alert("❌ Gagal membuka backup cloud: " + err.message);
    }
    finally { setIsLoadingBackups(false); }
  };

  const loadBackup = async (backup) => {
    if (!backup?.id) return;
    confirmAction("Restore Cloud Backup", `Restore cloud backup ${backup.id}? Data aktif akan diganti dengan isi snapshot backup.`, async () => {
      setIsSaving(true);
      try {
        if (!db || !paths) throw new Error("Firebase belum terhubung.");

        const [txSnap, invSnap, shSnap] = await Promise.all([
          getDocs(paths.backupTransactions(backup.id)),
          getDocs(paths.backupInventory(backup.id)),
          getDocs(paths.backupShareholders(backup.id))
        ]);

        const txs = txSnap.docs.map(d => normalizeTx({ id: d.id, ...d.data() }));
        const inv = invSnap.docs.map(d => {
          const data = d.data();
          return {
            id: d.id,
            ...data,
            name: safeString(data.name || d.id),
            qty: safeNumber(data.qty),
            unit: safeString(data.unit || ""),
            valuePerUnit: safeNumber(data.valuePerUnit),
            category: safeString(data.category || "Tanpa Kategori")
          };
        });
        const sh = shSnap.docs.map(d => ({ id: d.id, ...d.data(), pct: safeNumber(d.data().pct), mgmtFee: safeNumber(d.data().mgmtFee) }));

        if (!txs.length && !inv.length && backup.backupType !== "full_snapshot_subcollections") {
          throw new Error("Backup ini backup metadata lama. Gunakan backup cloud baru atau Restore JSON.");
        }

        await clearCollection(paths.transactions());
        await clearCollection(paths.inventory());
        await clearCollection(paths.shareholders());

        await batchWriteDocs(paths.transactions(), txs, x => ({ ...x, updatedAt: serverTimestamp(), restoredFromBackupId: backup.id }));
        await batchWriteDocs(paths.inventory(), inv, x => ({ ...x, updatedAt: serverTimestamp(), restoredFromBackupId: backup.id }));
        await batchWriteDocs(paths.shareholders(), sh, x => ({ ...x, updatedAt: serverTimestamp(), restoredFromBackupId: backup.id }));

        const nextCapital = safeNumber(backup.initialCapital);
        const nextBalance = safeNumber(backup.actualBalance);
        const nextPaidPeriods = backup.paidPeriods || {};
        await saveMeta({
          initialCapital: nextCapital,
          actualBalance: nextBalance,
          paidPeriods: nextPaidPeriods,
          restoredFromBackupId: backup.id,
          restoredAt: new Date().toISOString()
        });

        setInitialCapital(nextCapital);
        setActualBalance(nextBalance);
        setPaidPeriods(nextPaidPeriods);
        setTransactions(txs);
        setInventory(inv);
        setShareholders(sh);
        setBackupOpen(false);
        setLastSaved(`Cloud restore selesai: ${new Date().toLocaleTimeString("id-ID")}`);
        alert(`✅ Cloud restore selesai.\nTransaksi: ${txs.length}\nStok: ${inv.length}\nShareholder: ${sh.length}`);
      } catch (err) {
        console.error(err);
        alert("❌ Gagal restore cloud: " + err.message);
      } finally { setIsSaving(false); }
    });
  };

  const deleteBackupPoint = (backup) => {
    if (!backup?.id) return;
    confirmAction("Hapus Titik Backup?", `Backup ${backup.id} akan dihapus dari cloud. Lanjutkan?`, async () => {
      if (!db || !paths) throw new Error("Firebase belum terhubung.");
      await clearCollection(paths.backupTransactions(backup.id));
      await clearCollection(paths.backupInventory(backup.id));
      await clearCollection(paths.backupShareholders(backup.id));
      await deleteDoc(doc(paths.backups(), backup.id));
      setBackupList(prev => prev.filter(b => b.id !== backup.id));
      alert("✅ Titik backup cloud dihapus.");
    });
  };

  const confirmAction = (title, msg, action) => {
    setConfirmData({ title, msg, action });
    setConfirmOpen(true);
  };

  const togglePeriodPaid = async (period) => {
    const next = { ...paidPeriods, [period]: !paidPeriods[period] };
    setPaidPeriods(next);
    if (db) await saveMeta({ paidPeriods: next });
  };

  const openEditInventory = (item) => { setCurrentEditInventory({ ...item }); setEditInventoryOpen(true); };
  const saveEditInventory = async () => {
    const item = { ...currentEditInventory, qty: safeNumber(currentEditInventory.qty), valuePerUnit: safeNumber(currentEditInventory.valuePerUnit) };
    setInventory(prev => prev.map(i => i.id === item.id ? item : i));
    if (db) await setDoc(doc(paths.inventory(), String(item.id)), { ...item, updatedAt: serverTimestamp() }, { merge: true });
    setEditInventoryOpen(false);
  };

  const addInventoryItem = async () => {
    if (!newItem.name) return;
    const item = { ...newItem, id: generateId(), qty: safeNumber(newItem.qty), valuePerUnit: safeNumber(newItem.valuePerUnit), category: newItem.category || "Tanpa Kategori" };
    setInventory(prev => [...prev, item]);
    if (db) await setDoc(doc(paths.inventory(), item.id), { ...item, updatedAt: serverTimestamp() }, { merge: true });
    setNewItem({ name: "", qty: "", unit: "", valuePerUnit: "", category: "Bahan Baku (Sembako/Bumbu)" });
  };

  const removeInventoryItem = async (id) => {
    setInventory(prev => prev.filter(i => i.id !== id));
    if (db) await deleteDoc(doc(paths.inventory(), String(id)));
  };

  const addShareholder = async (name, pct, fee) => {
    if (!name || !pct) return;
    const item = { id: generateId(), name, pct: safeNumber(pct), mgmtFee: safeNumber(fee) };
    setShareholders(prev => [...prev, item]);
    if (db) await setDoc(doc(paths.shareholders(), item.id), item, { merge: true });
  };

  const removeShareholder = async (id) => {
    setShareholders(prev => prev.filter(s => s.id !== id));
    if (db) await deleteDoc(doc(paths.shareholders(), String(id)));
  };

  const processBulkWithLocalParser = async (text, type) => {
    setIsBulkProcessing(true);
    setBulkStatus("Membaca format transaksi...");
    const rows = parseBulkText(text, type).map(row => {
      const learnedCategory = learnCategoryFromHistory(row.desc, row.type);
      return normalizeTx({
        ...row,
        category: learnedCategory,
        type: learnedCategory.includes("Pemasukan") ? "income" : row.type,
        classificationReason: `Kategori dipilih dari memori backup/riwayat: ${learnedCategory}`
      });
    });
    if (!rows.length) {
      setBulkStatus("Tidak ada baris valid.");
      setIsBulkProcessing(false);
      return;
    }
    await addTransactions(rows, `bulk_${type}`);
    setBulkStatus(`Selesai! ${rows.length} transaksi masuk.`);
    if (type === "income") setBulkIncomeText(""); else setBulkExpenseText("");
    setIsBulkProcessing(false);
  };

  const processInventoryBulkLocal = async (text) => {
    setIsBulkProcessing(true);
    const items = String(text || "").split(/\n+/).map(line => {
      const m = line.trim().match(/^(.+?)\s+([\d.,]+)\s*([a-zA-ZÀ-ÿ/]+)?(?:\s*[@xX]\s*([\d.,]+))?/);
      if (!m) return null;
      const nm = m[1].trim();
      return { id: generateId(), name: nm, qty: safeNumber(m[2]), unit: m[3] || "", valuePerUnit: safeNumber(m[4]), category: learnCategoryFromHistory(nm, "expense") };
    }).filter(Boolean);
    setInventory(prev => [...prev, ...items]);
    if (db) await batchWriteDocs(paths.inventory(), items, x => ({ ...x, updatedAt: serverTimestamp() }));
    setBulkInventoryText("");
    setBulkStatus(`Berhasil menambah ${items.length} item stok.`);
    setIsBulkProcessing(false);
  };

  const handleViewDetail = (periodData, type) => {
    setDetailViewType(type);
    const titles = {
      sewa: `Rincian Insentif - ${periodData.period}`,
      bahan: `Rincian Bahan Baku - ${periodData.period}`,
      ops: `Rincian Operasional - ${periodData.period}`,
      modal: `Rincian Modal (Capex) - ${periodData.period}`,
      beban: `Rincian Beban Profit - ${periodData.period}`,
      dividen: `Rincian Dividen - ${periodData.period}`
    };
    const filtered = periodData.transactions.filter(t => getTransactionGroup(t) === type);
    setSelectedDetail({ title: titles[type] || "Rincian", data: filtered });
    setDetailSearch("");
    setDetailSort("LAST_INPUT");
    setDetailOpen(true);
  };

  const handleDistributeDividend = async () => {
    if (!shareholders.length) return alert("Belum ada shareholder.");
    if (calculatedDividendPool.total <= 0) return alert("Tidak ada dana untuk dibagikan pada periode ini.");
    const periodName = `${new Date(divCalcStart).toLocaleDateString("id-ID", { month: "short" })} - ${new Date(divCalcEnd).toLocaleDateString("id-ID", { month: "short", year: "2-digit" })}`;
    confirmAction("Konfirmasi Pembagian Dividen", `Total dividen akan dibagikan ke ${shareholders.length} orang. Lanjutkan?`, async () => {
      const divs = shareholders.map(s => {
        const { net } = getShareData(s);
        return normalizeTx({
          date: dividendConfig.distributionDate,
          desc: `Dividen: ${s.name} (${s.pct}%) - ${periodName}`,
          category: "Pembagian Dividen",
          type: "expense",
          amount: net,
          qty: 1,
          unit: "BagiHasil",
          unitPrice: net,
          isDebt: false,
          paymentStatus: "paid",
          paidAmount: net,
          source: "site_dividend"
        });
      });
      await addTransactions(divs, "site_dividend");
      setManualDistributions({});
      alert("✅ Dividen berhasil dicatat.");
    });
  };

  const handlePrintReport = () => window.print();
  const handlePrintInvestorReport = () => window.print();

  const generateRealAiAnalysis = () => {
    setIsAnalyzing(true);
    setTimeout(() => {
      const result = [];
      if (analytics.totalDebt > 0) result.push({ type: "warn", title: "Hutang aktif", msg: `Outstanding hutang tercatat ${formatIDR(analytics.totalDebt)}. Prioritaskan vendor dengan nilai terbesar.` });
      if (analytics.pendingFunds > 0) result.push({ type: "warn", title: "Dana belum cair", msg: `Ada talangan/pending ${formatIDR(analytics.pendingFunds)} pada periode tertentu.` });
      if (analytics.netWorth > 0) result.push({ type: "good", title: "Net worth positif", msg: `Kekayaan bersih tercatat ${formatIDR(analytics.netWorth)}.` });
      if (!result.length) result.push({ type: "info", title: "Data belum cukup", msg: "Tambahkan transaksi untuk analisis yang lebih tajam." });
      setAiAnalysisResult(result);
      setIsAnalyzing(false);
    }, 500);
  };

  const generateMenuPlan = () => {
    const total = safeNumber(menuPlanner.pax) * safeNumber(menuPlanner.budget);
    setMenuResult({
      menu: ["Menu utama: nasi, lauk protein, sayur, buah", "Distribusi disesuaikan dengan stok gudang"],
      shoppingList: [
        { item: "Protein/lauk", qty: `${Math.ceil(menuPlanner.pax * 0.08)} kg`, estCost: total * 0.45 },
        { item: "Sayur/buah", qty: `${Math.ceil(menuPlanner.pax * 0.12)} kg`, estCost: total * 0.25 },
        { item: "Bumbu/kemasan", qty: "sesuai kebutuhan", estCost: total * 0.15 }
      ],
      totalEstCost: total * 0.85
    });
  };

  const monthOptions = useMemo(() => {
    const keys = Array.from(new Set(transactions.map(t => toMonthKey(t.date)).filter(Boolean))).sort();
    return keys.map(key => ({ key, label: monthLabelFromKey(key) }));
  }, [transactions]);

  const visibleTransactions = useMemo(() => {
    return transactions.filter(t => {
      const date = normalizeDate(t.date);
      if (monthFilter !== "ALL" && toMonthKey(date) !== monthFilter) return false;
      if (periodFilter === "custom" && customStartDate && customEndDate) return date >= customStartDate && date <= customEndDate;
      return true;
    });
  }, [transactions, monthFilter, periodFilter, customStartDate, customEndDate]);

  const analytics = useMemo(() => {
    const groupedData = {};
    const debtByVendor = {};
    let totalDebt = 0, grandTotalRevenue = 0, grandTotalExpense = 0, grandTotalCapex = 0, grandTotalProfitBurden = 0, grandTotalDividend = 0, cashPaid = 0;
    let filteredTransactions = visibleTransactions;

    filteredTransactions.forEach(t => {
      const safeDate = normalizeDate(t.date);
      const timeKey = periodFilter === "custom" ? "Periode Terpilih" : getPeriodKey(safeDate, periodFilter);
      groupedData[timeKey] ||= {
        period: timeKey, incSewa: 0, incOps: 0, incBahan: 0, expBahan: 0, expOps: 0,
        expCapex: 0, expProfitBurden: 0, expDividend: 0, netProfit: 0, transactions: [], firstDate: safeDate
      };
      if (safeDate < groupedData[timeKey].firstDate) groupedData[timeKey].firstDate = safeDate;
      groupedData[timeKey].transactions.push(t);
      const group = getTransactionGroup(t);

      if (t.type === "income") {
        grandTotalRevenue += safeNumber(t.amount);
        if (group === "sewa") groupedData[timeKey].incSewa += t.amount;
        else if (group === "ops") groupedData[timeKey].incOps += t.amount;
        else groupedData[timeKey].incBahan += t.amount;
      } else {
        grandTotalExpense += safeNumber(t.amount);
        const paid = Math.min(safeNumber(t.amount), safeNumber(t.paidAmount));
        cashPaid += paid;
        const outstanding = txOutstanding(t);
        if (txIsDebtActive(t) && outstanding > 0) {
          totalDebt += outstanding;
          const vendor = safeString(t.orderBy || "Lainnya") || "Lainnya";
          debtByVendor[vendor] = (debtByVendor[vendor] || 0) + outstanding;
        }
        if (group === "dividen") { groupedData[timeKey].expDividend += t.amount; grandTotalDividend += t.amount; }
        else if (group === "beban") { groupedData[timeKey].expProfitBurden += t.amount; grandTotalProfitBurden += t.amount; }
        else if (group === "modal") { groupedData[timeKey].expCapex += t.amount; grandTotalCapex += t.amount; }
        else if (group === "bahan") groupedData[timeKey].expBahan += t.amount;
        else groupedData[timeKey].expOps += t.amount;
      }
    });

    Object.values(groupedData).forEach(d => {
      d.surplusBahan = d.incBahan - d.expBahan;
      d.surplusOps = d.incOps - d.expOps;
      d.netProfit = d.incSewa + d.surplusBahan + d.surplusOps - d.expProfitBurden;
      d.totalExpense = d.expBahan + d.expOps + d.expProfitBurden + d.expDividend + d.expCapex;
      d.totalRevenue = d.incSewa + d.incOps + d.incBahan;
      d.cashFlow = d.totalRevenue - d.totalExpense;
      const isEarly = d.firstDate && new Date(d.firstDate) < new Date("2025-11-05");
      const isManuallyPaid = paidPeriods[d.period] === true;
      d.isPending = !isManuallyPaid && !isEarly && ((d.incOps === 0 && d.expOps > 0) || (d.incBahan === 0 && d.expBahan > 0));
    });

    const sortedPeriods = Object.values(groupedData).sort((a,b) => a.firstDate.localeCompare(b.firstDate));
    const systemBalance = initialCapital + grandTotalRevenue - cashPaid;
    const realBalance = actualBalance || systemBalance;
    const discrepancy = systemBalance - realBalance;
    const inventoryValue = inventory.reduce((a,b) => a + safeNumber(b.qty) * safeNumber(b.valuePerUnit), 0);
    const totalAssets = realBalance + inventoryValue;
    const debtRatio = totalAssets > 0 ? (totalDebt / totalAssets) * 100 : 0;
    const pendingFunds = sortedPeriods.filter(p => p.isPending).reduce((a,b) => a + b.expBahan + b.expOps, 0);
    const pieData = [
      { name: "Bahan Baku", value: sortedPeriods.reduce((a,b) => a + b.expBahan, 0), color: "#10b981" },
      { name: "Operasional", value: sortedPeriods.reduce((a,b) => a + b.expOps, 0), color: "#f59e0b" },
      { name: "Capex", value: grandTotalCapex, color: "#6366f1" },
      { name: "Beban Profit", value: grandTotalProfitBurden, color: "#ef4444" }
    ].filter(x => x.value > 0);
    return { totalDebt, systemBalance, realBalance, discrepancy, debtByVendor, sortedPeriods, grandTotalRevenue, grandTotalExpense, grandTotalCapex, grandTotalProfitBurden, grandTotalDividend, debtRatio, totalAssets, inventoryValue, pendingFunds, netWorth: totalAssets - totalDebt, pieData, cashPaid };
  }, [visibleTransactions, inventory, initialCapital, periodFilter, actualBalance, paidPeriods]);

  const calculatedDividendPool = useMemo(() => {
    const rangeTxs = transactions.filter(t => t.date >= divCalcStart && t.date <= divCalcEnd);
    let rangeInsentif = 0, rangeExpenseBahan = 0, rangeCapex = 0, rangeProfitBurden = 0;
    rangeTxs.forEach(t => {
      const group = getTransactionGroup(t);
      if (t.type === "income" && group === "sewa") rangeInsentif += t.amount;
      if (t.type === "expense" && group === "bahan") rangeExpenseBahan += t.amount;
      if (t.type === "expense" && group === "modal") rangeCapex += t.amount;
      if (t.type === "expense" && group === "beban") rangeProfitBurden += t.amount;
    });
    const targetInsentif = rangeInsentif * (dividendConfig.sourceInsentifPct / 100);
    const targetBahan = rangeExpenseBahan * (dividendConfig.targetProfitBahanPct / 100);
    const deductions = rangeCapex + rangeProfitBurden + analytics.totalDebt;
    const bahanNet = Math.max(0, targetBahan - deductions);
    const autoTotal = targetInsentif + bahanNet;
    const finalTotal = dividendConfig.mode === "manual" ? dividendConfig.customAmount : autoTotal;
    const ratio = dividendConfig.mode === "manual" && autoTotal > 0 ? finalTotal / autoTotal : 1;
    return {
      total: finalTotal,
      autoTotal,
      insentifPart: targetInsentif * ratio,
      bahanNet: bahanNet * ratio,
      rangeInsentif,
      rangeExpenseBahan,
      deductions,
      rangeCapex,
      rangeProfitBurden
    };
  }, [transactions, divCalcStart, divCalcEnd, dividendConfig, analytics.totalDebt]);

  const getShareData = (s) => {
    const shareGross = calculatedDividendPool.total * (safeNumber(s.pct) / 100);
    const grossInsentifShare = calculatedDividendPool.insentifPart * (safeNumber(s.pct) / 100);
    const fee = grossInsentifShare * (safeNumber(s.mgmtFee) / 100);
    const calculatedNet = Math.floor(shareGross - fee);
    const manualVal = manualDistributions[s.id];
    const net = manualVal !== undefined && manualVal !== "" ? parseIDRInput(String(manualVal)) : calculatedNet;
    return { gross: shareGross, fee, net, calculatedNet, isManual: manualVal !== undefined && manualVal !== "" };
  };

  const categoryOptions = useMemo(() => {
    const fromTx = transactions.map(t => safeString(t.category).trim()).filter(Boolean);
    const fromInv = inventory.map(i => safeString(i.category).trim()).filter(Boolean);
    return Array.from(new Set([...fromTx, ...fromInv, ...CATEGORIES])).sort((a, b) => a.localeCompare(b, "id-ID"));
  }, [transactions, inventory]);

  const inventoryCategoryOptions = useMemo(() => {
    return Array.from(new Set(inventory.map(i => safeString(i.category || "Tanpa Kategori").trim()).filter(Boolean))).sort((a,b)=>a.localeCompare(b,"id-ID"));
  }, [inventory]);

  const filteredInventory = useMemo(() => {
    const q = inventorySearch.trim().toLowerCase();
    return inventory
      .filter(i => inventoryCategoryFilter === "ALL" || safeString(i.category || "Tanpa Kategori") === inventoryCategoryFilter)
      .filter(i => inventoryPriceFilter === "ALL" || (inventoryPriceFilter === "NO_PRICE" ? safeNumber(i.valuePerUnit) === 0 : safeNumber(i.valuePerUnit) > 0))
      .filter(i => !q || `${i.name} ${i.category} ${i.unit}`.toLowerCase().includes(q))
      .sort((a,b)=>safeString(a.name).localeCompare(safeString(b.name), "id-ID"));
  }, [inventory, inventorySearch, inventoryCategoryFilter, inventoryPriceFilter]);

  const dashboardChartData = useMemo(() => {
    return analytics.sortedPeriods
      .filter(p => safeNumber(p.totalRevenue) || safeNumber(p.totalExpense) || safeNumber(p.netProfit) || safeNumber(p.cashFlow))
      .slice(-16)
      .map((p) => ({
        ...p,
        periodLabel: periodFilter === "daily" ? String(p.period || "").slice(5) : String(p.period || "").replace(/ - /g,"–"),
        incSewa: Number.isFinite(Number(p.incSewa)) ? Number(p.incSewa) : 0,
        surplusBahan: Number.isFinite(Number(p.surplusBahan)) ? Number(p.surplusBahan) : 0,
        surplusOps: Number.isFinite(Number(p.surplusOps)) ? Number(p.surplusOps) : 0,
        totalRevenue: Number.isFinite(Number(p.totalRevenue)) ? Number(p.totalRevenue) : 0,
        totalExpense: Number.isFinite(Number(p.totalExpense)) ? Number(p.totalExpense) : 0,
        netProfit: Number.isFinite(Number(p.netProfit)) ? Number(p.netProfit) : 0,
        cashFlow: Number.isFinite(Number(p.cashFlow)) ? Number(p.cashFlow) : 0
      }));
  }, [analytics.sortedPeriods, periodFilter]);

  const topExpenseCategories = useMemo(() => {
    const m = {};
    visibleTransactions.filter(t => t.type === "expense").forEach(t => { m[t.category || "Tanpa Kategori"] = (m[t.category || "Tanpa Kategori"] || 0) + safeNumber(t.amount); });
    return Object.entries(m).map(([name, value]) => ({ name, value })).sort((a,b)=>b.value-a.value).slice(0,8);
  }, [visibleTransactions]);

  const topVendorDebts = useMemo(() => Object.entries(analytics.debtByVendor || {}).map(([name,value])=>({name,value})).sort((a,b)=>b.value-a.value).slice(0,8), [analytics.debtByVendor]);

  const auditRows = useMemo(() => {
    const rows = transactions.map(t => {
      const currentCategory = safeString(t.category).trim();
      const recommended = learnCategoryFromHistory(t.desc, t.type);
      const isGeneric = !currentCategory || currentCategory === "Lainnya (Ops)" || currentCategory === "Bahan Baku";
      const mismatch = isGeneric && recommended && recommended !== currentCategory;
      const outstanding = txOutstanding(t);
      const severity = txIsDebtActive(t) || outstanding > 0 || mismatch ? "RED" : "INFO";
      return { ...t, recommended, mismatch, outstanding, severity };
    }).filter(t => t.mismatch || t.outstanding > 0 || !t.source || safeNumber(t.classificationConfidence) < 0.75 || t.auditStatus === "done");
    return rows
      .filter(t => auditFilter === "ALL" || (auditFilter === "RED" ? t.severity === "RED" && t.auditStatus !== "done" : auditFilter === "DONE" ? t.auditStatus === "done" : t.auditStatus !== "done"))
      .sort((a,b)=> (b.severity === "RED") - (a.severity === "RED") || String(b.date).localeCompare(String(a.date)) );
  }, [transactions, categoryMemory, auditFilter]);

  const debtRows = useMemo(() => transactions
    .map(t => ({ ...t, outstanding: txOutstanding(t), debtActive: txIsDebtActive(t), inputMs: txInputMs(t) }))
    .filter(t => t.debtActive || t.outstanding > 0)
    .filter(t => debtVendorFilter === "ALL" || t.orderBy === debtVendorFilter)
    .filter(t => debtCategoryFilter === "ALL" || t.category === debtCategoryFilter)
    .sort((a,b)=> b.inputMs - a.inputMs || safeNumber(b.outstanding) - safeNumber(a.outstanding)), [transactions, debtVendorFilter, debtCategoryFilter]);

  const debtVendors = useMemo(() => Array.from(new Set(transactions
    .filter(t => txIsDebtActive(t) || txOutstanding(t) > 0)
    .map(t => t.orderBy || "-")
  )).sort(), [transactions]);

  const debtCategories = useMemo(() => Array.from(new Set(transactions
    .filter(t => txIsDebtActive(t) || txOutstanding(t) > 0)
    .map(t => t.category || "Lainnya (Ops)")
  )).sort(), [transactions]);

  const trackingCategories = useMemo(() => Array.from(new Set(transactions.map(t => t.category || "Tanpa Kategori").filter(Boolean))).sort((a,b)=>a.localeCompare(b,"id-ID")), [transactions]);
  const trackingVendors = useMemo(() => Array.from(new Set(transactions.map(t => t.orderBy || "-").filter(Boolean))).sort((a,b)=>a.localeCompare(b,"id-ID")), [transactions]);
  const trackingMonthOptions = useMemo(() => {
    const monthFmt = new Intl.DateTimeFormat("id-ID", { month: "long", year: "numeric" });
    const keys = Array.from(new Set(transactions.map(t => String(t.date || "").slice(0,7)).filter(k => /^\d{4}-\d{2}$/.test(k)))).sort().reverse();
    return keys.map(key => ({ key, label: monthFmt.format(new Date(`${key}-01T00:00:00`)) }));
  }, [transactions]);

  const trackingRows = useMemo(() => {
    const q = globalSearch.trim().toLowerCase();
    return transactions
      .map(t => ({ ...t, outstanding: txOutstanding(t), debtActive: txIsDebtActive(t), inputMs: txInputMs(t) }))
      .filter(t => !q || `${t.date} ${t.desc} ${t.category} ${t.orderBy} ${t.note} ${t.id} ${t.amount} ${t.unit} ${t.unitPrice}`.toLowerCase().includes(q))
      .filter(t => trackingCategoryFilter === "ALL" || (t.category || "Tanpa Kategori") === trackingCategoryFilter)
      .filter(t => trackingVendorFilter === "ALL" || (t.orderBy || "-") === trackingVendorFilter)
      .filter(t => {
        const d = String(t.date || "");
        if (trackingDateMode === "MONTH") return trackingMonthFilter === "ALL" || d.startsWith(trackingMonthFilter);
        if (trackingDateMode === "CUSTOM") {
          if (trackingStartDate && d < trackingStartDate) return false;
          if (trackingEndDate && d > trackingEndDate) return false;
          return true;
        }
        if (trackingDateMode === "TODAY") return d === new Date().toISOString().split("T")[0];
        return true;
      })
      .filter(t => {
        if (trackingStatusFilter === "ALL") return true;
        if (trackingStatusFilter === "DEBT") return t.debtActive;
        if (trackingStatusFilter === "PAID") return !t.debtActive && String(t.paymentStatus || "").toLowerCase() === "paid";
        if (trackingStatusFilter === "INCOME") return t.type === "income";
        if (trackingStatusFilter === "EXPENSE") return t.type !== "income";
        if (trackingStatusFilter === "PRICE") return safeNumber(t.qty) > 0 || safeNumber(t.unitPrice) > 0;
        if (trackingStatusFilter === "NO_PRICE") return safeNumber(t.qty) > 0 && safeNumber(t.unitPrice) === 0;
        return true;
      })
      .sort((a,b) => {
        if (trackingSort === "DATE_DESC") return String(b.date).localeCompare(String(a.date)) || b.inputMs - a.inputMs;
        if (trackingSort === "DATE_ASC") return String(a.date).localeCompare(String(b.date)) || a.inputMs - b.inputMs;
        if (trackingSort === "AMOUNT_DESC") return safeNumber(b.amount) - safeNumber(a.amount);
        if (trackingSort === "AMOUNT_ASC") return safeNumber(a.amount) - safeNumber(b.amount);
        if (trackingSort === "UNIT_PRICE_DESC") return safeNumber(b.unitPrice) - safeNumber(a.unitPrice);
        if (trackingSort === "OUTSTANDING_DESC") return safeNumber(b.outstanding) - safeNumber(a.outstanding);
        return b.inputMs - a.inputMs || String(b.date).localeCompare(String(a.date));
      });
  }, [transactions, globalSearch, trackingStatusFilter, trackingCategoryFilter, trackingVendorFilter, trackingDateMode, trackingMonthFilter, trackingStartDate, trackingEndDate, trackingSort]);

  // BEGIN TRACKING MULTI SELECT V8.6
  const selectedTrackingSet = useMemo(
    () => new Set(selectedTrackingIds),
    [selectedTrackingIds]
  );

  const selectedTrackingRows = useMemo(
    () => transactions.filter(t => selectedTrackingSet.has(t.id)),
    [transactions, selectedTrackingSet]
  );

  const allTrackingVisibleSelected =
    trackingRows.length > 0 &&
    trackingRows.every(t => selectedTrackingSet.has(t.id));

  const toggleTrackingSelection = (id) => {
    setSelectedTrackingIds(prev =>
      prev.includes(id)
        ? prev.filter(x => x !== id)
        : [...prev, id]
    );
  };

  const toggleAllTrackingVisible = () => {
    const visibleIds = trackingRows.map(t => t.id);

    setSelectedTrackingIds(prev => {
      const next = new Set(prev);

      const allSelected =
        visibleIds.length > 0 &&
        visibleIds.every(id => next.has(id));

      visibleIds.forEach(id => {
        if (allSelected) next.delete(id);
        else next.add(id);
      });

      return Array.from(next);
    });
  };

  const deleteSelectedTracking = () => {
    const rows = selectedTrackingRows;

    if (!rows.length) return;

    const total = rows.reduce(
      (sum, t) => sum + safeNumber(t.amount),
      0
    );

    confirmAction(
      "Hapus Transaksi Terpilih?",
      `Hapus ${rows.length} transaksi yang dicentang dengan total ${formatIDR(total)}? Hanya item yang dicentang yang akan dihapus.`,
      async () => {
        try {
          const ids = rows.map(t => t.id);

          if (db && paths) {
            for (let i = 0; i < ids.length; i += 400) {
              const batch = writeBatch(db);

              ids.slice(i, i + 400).forEach(id => {
                batch.delete(
                  doc(paths.transactions(), String(id))
                );
              });

              await batch.commit();
            }
          }

          const idSet = new Set(ids);

          setTransactions(prev =>
            prev.filter(t => !idSet.has(t.id))
          );

          setSelectedTrackingIds([]);

          alert(
            `✅ ${ids.length} transaksi terpilih berhasil dihapus.`
          );
        } catch (err) {
          console.error(err);
          alert(
            "❌ Gagal menghapus transaksi terpilih: " +
            err.message
          );
        }
      }
    );
  };
  // END TRACKING MULTI SELECT V8.6

  const detailRows = useMemo(() => {
    if (!selectedDetail?.data) return [];
    const q = detailSearch.trim().toLowerCase();
    return selectedDetail.data
      .map(t => ({ ...t, outstanding: txOutstanding(t), debtActive: txIsDebtActive(t), inputMs: txInputMs(t) }))
      .filter(t => !q || `${t.date} ${t.desc} ${t.category} ${t.orderBy} ${t.note} ${t.id} ${t.amount}`.toLowerCase().includes(q))
      .sort((a,b) => {
        if (detailSort === "DATE_DESC") return String(b.date).localeCompare(String(a.date)) || b.inputMs - a.inputMs;
        if (detailSort === "DATE_ASC") return String(a.date).localeCompare(String(b.date)) || a.inputMs - b.inputMs;
        if (detailSort === "AMOUNT_DESC") return safeNumber(b.amount) - safeNumber(a.amount);
        if (detailSort === "AMOUNT_ASC") return safeNumber(a.amount) - safeNumber(b.amount);
        if (detailSort === "VENDOR") return String(a.orderBy || "").localeCompare(String(b.orderBy || ""), "id-ID");
        return b.inputMs - a.inputMs || String(b.date).localeCompare(String(a.date));
      });
  }, [selectedDetail, detailSearch, detailSort]);

  const deleteDetailTransaction = (t) => {
    confirmAction("Hapus Transaksi dari Rincian?", `Hapus ${t.desc} sebesar ${formatIDR(t.amount)}?`, async () => {
      await handleDeleteTrans(t.id);
      setSelectedDetail(prev => prev ? { ...prev, data: prev.data.filter(x => x.id !== t.id) } : prev);
    });
  };

  const payDebtRows = (rows) => {
    if (!rows.length) return alert("Tidak ada hutang pada filter ini.");
    const total = rows.reduce((a,b)=>a+b.outstanding,0);
    confirmAction("Lunasi Hutang Filter", `Lunasi ${rows.length} transaksi dengan total ${formatIDR(total)}?`, async () => {
      const today = new Date().toISOString().split("T")[0];
      const updates = rows.map(t => ({ ...t, isDebt: false, paymentStatus: "paid", paidAmount: t.amount, paidDate: today }));
      setTransactions(prev => prev.map(t => updates.find(u => u.id === t.id) || t));
      if (db) await batchWriteDocs(paths.transactions(), updates, x => ({ ...x, updatedAt: serverTimestamp() }));
    });
  };

  const getTabClass = (id) => activeTab === id ? "active" : "";

  return (
    <div className="app-shell">
      <div className="page">
        <div className="legacy-header">
          <div>
            <h1><Utensils className="orange" /> Laporan Keuangan {siteLabel}</h1>
            <p>Sistem Akuntansi Katering 3 Pintu (Bahan, Ops, Sewa) · {siteShortLabel} · DB {firestoreDatabaseId}</p>
          </div>
          <div className="header-actions">
            <Button variant="green" size="sm" onClick={handleExportExcelStyled}><FileSpreadsheet size={16}/> Export Excel DB</Button>
            <Button variant="outline" size="sm" onClick={()=>setSheetSyncOpen(true)}><Database size={16}/> Google Sheet</Button>
            <Button variant="blue" size="sm" onClick={() => csvInputRef.current?.click()}><Upload size={16}/> Import CSV DB</Button>
            <input type="file" ref={csvInputRef} hidden accept=".csv" onChange={handleImportCSV} />
            <span className="divider" />
            <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}><Upload size={16}/> Restore JSON</Button>
            <input type="file" ref={fileInputRef} hidden accept=".json" onChange={handleImportFile} />
            <Button variant="outline" size="sm" onClick={openBackupDialog}><RotateCcw size={16}/> Cloud Restore</Button>
            <Button variant="outline" size="sm" onClick={handleExportJSON}><Download size={16}/> Backup PC</Button>
            <Button variant="outline" size="sm" className="danger-text" onClick={handleResetData}><RefreshCcw size={16}/> Reset</Button>
            <div className="save-block">
              <span>{lastSaved}</span>
              <Button onClick={handleSaveToCloud} disabled={isSaving || !isDataLoaded} size="sm" className="dark">
                {isSaving ? <Loader2 className="spin" size={14}/> : <CloudUpload size={14}/>} Buat Titik Backup
              </Button>
            </div>
          </div>
        </div>

        <div className="tabs-list">
          <button className={getTabClass("dashboard")} onClick={() => setActiveTab("dashboard")}><LayoutDashboard size={16}/> Dash</button>
          <button className={getTabClass("input")} onClick={() => setActiveTab("input")}><Plus size={16}/> Input</button>
          <button className={getTabClass("debts")} onClick={() => setActiveTab("debts")}><CreditCard size={16}/> Hutang</button>
          <button className={getTabClass("reports")} onClick={() => setActiveTab("reports")}><FileText size={16}/> Laporan</button>
          <button className={getTabClass("dividend")} onClick={() => setActiveTab("dividend")}><Users size={16}/> Dividen</button>
          <button className={getTabClass("inventory")} onClick={() => setActiveTab("inventory")}><Package size={16}/> Gudang</button>
          <button className={getTabClass("audit")} onClick={() => setActiveTab("audit")}><ShieldAlert size={16}/> Audit</button>
        </div>

        {activeTab === "dashboard" && (
          <section className="space">
            <Card>
              <CardContent>
                <div className="dashboard-filterbar">
                  <div className="periods">
                    <Button variant={periodFilter==="daily"?"default":"ghost"} onClick={()=>setPeriodFilter("daily")}>Harian</Button>
                    <Button variant={periodFilter==="weekly"?"default":"ghost"} onClick={()=>setPeriodFilter("weekly")}>Mingguan</Button>
                    <Button variant={periodFilter==="monthly"?"default":"ghost"} onClick={()=>setPeriodFilter("monthly")}>Bulanan</Button>
                    <Button variant={periodFilter==="custom"?"default":"ghost"} onClick={()=>setPeriodFilter("custom")}>Custom</Button>
                  </div>
                  <select className="select month-select" value={monthFilter} onChange={e=>setMonthFilter(e.target.value)}><option value="ALL">Semua bulan</option>{monthOptions.map(m=><option key={m.key} value={m.key}>{m.label}</option>)}</select>
                  {periodFilter==="custom" && <div className="date-range"><Input type="date" value={customStartDate} onChange={e=>setCustomStartDate(e.target.value)}/><span>s/d</span><Input type="date" value={customEndDate} onChange={e=>setCustomEndDate(e.target.value)}/></div>}
                  <Badge variant="soft">{visibleTransactions.length} transaksi</Badge>
                </div>
              </CardContent>
            </Card>
            <Card className="finance-card">
              <CardHeader><CardTitle><Wallet/> POSISI KEUANGAN (REAL TIME)</CardTitle></CardHeader>
              <CardContent>
                <div className="finance-grid">
                  <div>
                    <label>KEKAYAAN BERSIH (NET WORTH)</label>
                    <div className="big green">{formatIDR(analytics.netWorth)}</div>
                    <small>(Saldo Real + Aset Gudang) - Hutang</small>
                  </div>
                  <div>
                    <label className="yellow">SALDO REAL (REKENING)</label>
                    <div className="money-input"><Landmark size={16}/><Input value={formatNumberInput(analytics.realBalance)} onChange={(e) => setActualBalance(parseIDRInput(e.target.value))} /></div>
                  </div>
                  <div>
                    <label className="muted-line">Saldo Buku (System) <button onClick={() => { setTempCapital(initialCapital); setEditCapitalOpen(true); }}>Edit Modal Awal</button></label>
                    <div className="book">{formatIDR(analytics.systemBalance)}</div>
                    <small>(Modal Awal: {formatIDR(initialCapital)})</small>
                    <small className="red">Selisih: {formatIDR(analytics.discrepancy)}</small>
                    {analytics.grandTotalDividend > 0 && <small className="pink">Dividen Dibagikan: -{formatIDR(analytics.grandTotalDividend)}</small>}
                  </div>
                </div>
              </CardContent>
            </Card>

            <div className="kpi-grid">
              <Card><CardContent><span className="label">Uang Masuk</span><div className="kpi green-text">{formatIDR(analytics.grandTotalRevenue)}</div></CardContent></Card>
              <Card><CardContent><span className="label">Uang Keluar</span><div className="kpi red-text">{formatIDR(analytics.grandTotalExpense)}</div></CardContent></Card>
              <Card><CardContent><span className="label">Profit Bersih</span><div className={`kpi ${analytics.sortedPeriods.reduce((a,b)=>a+b.netProfit,0)<0?"red-text":"blue-text"}`}>{formatIDR(analytics.sortedPeriods.reduce((a,b)=>a+b.netProfit,0))}</div></CardContent></Card>
              <Card><CardContent><span className="label">Aset Gudang</span><div className="kpi emerald-text">{formatIDR(analytics.inventoryValue)}</div></CardContent></Card>
            </div>
            <div className="grid-two">
              <Card>
                <CardHeader><CardTitle><TrendingUp className="green-icon"/> Grafik Profitabilitas</CardTitle><CardDescription>Performa mingguan/bulanan</CardDescription></CardHeader>
                <CardContent className="chart">
                  {dashboardChartData.length === 0 ? (
                    <div className="chart-empty">Belum ada data periode untuk grafik.</div>
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={dashboardChartData} margin={{ top: 10, right: 16, left: 0, bottom: 8 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="periodLabel" interval="preserveStartEnd" tick={{ fontSize: 10 }} angle={-12} textAnchor="end" height={46} />
                        <YAxis tickFormatter={formatAxisIDR} width={64} />
                        <RechartsTooltip formatter={(val) => formatIDR(Number(val || 0))} />
                        <Legend />
                        <Bar dataKey="netProfit" name="Profit Bersih" fill="#2563eb" radius={[4, 4, 0, 0]} />
                        <Bar dataKey="cashFlow" name="Arus Kas" fill="#10b981" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  )}
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle><ArrowRightLeft className="blue-icon"/> Tren Arus Kas (Cashflow)</CardTitle><CardDescription>Uang Masuk vs Uang Keluar</CardDescription></CardHeader>
                <CardContent className="chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={dashboardChartData} margin={{ top: 10, right: 16, left: 0, bottom: 8 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="periodLabel" interval="preserveStartEnd" tick={{ fontSize: 10 }} angle={-12} textAnchor="end" height={46} />
                      <YAxis tickFormatter={formatAxisIDR} width={64} />
                      <RechartsTooltip formatter={(val) => formatIDR(Number(val || 0))} />
                      <Legend />
                      <Area type="monotone" dataKey="totalRevenue" name="Uang Masuk" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.12} />
                      <Area type="monotone" dataKey="totalExpense" name="Uang Keluar" stroke="#ef4444" fill="#ef4444" fillOpacity={0.12} />
                    </AreaChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Ringkasan Kategori Operasional</CardTitle></CardHeader>
                <CardContent>
                  <Table>
                    <TableHeader><TableRow><TableHead>Kategori</TableHead><TableHead className="right">Total</TableHead></TableRow></TableHeader>
                    <TableBody>
                      <TableRow><TableCell className="green-text strong">Bahan Baku</TableCell><TableCell className="right">{formatIDR(analytics.sortedPeriods.reduce((a,b)=>a+b.expBahan,0))}</TableCell></TableRow>
                      <TableRow><TableCell className="orange-text strong">Operasional</TableCell><TableCell className="right">{formatIDR(analytics.sortedPeriods.reduce((a,b)=>a+b.expOps,0))}</TableCell></TableRow>
                      <TableRow><TableCell className="indigo-text strong">Capex (Modal)</TableCell><TableCell className="right">{formatIDR(analytics.grandTotalCapex)}</TableCell></TableRow>
                      <TableRow><TableCell className="red-text strong">Beban Profit</TableCell><TableCell className="right">{formatIDR(analytics.grandTotalProfitBurden)}</TableCell></TableRow>
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Komposisi Biaya Operasional</CardTitle></CardHeader>
                <CardContent className="chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <RePieChart>
                      <Pie data={analytics.pieData} cx="50%" cy="50%" innerRadius={60} outerRadius={82} paddingAngle={5} dataKey="value">
                        {analytics.pieData.map((entry, idx) => <Cell key={idx} fill={entry.color} />)}
                      </Pie>
                      <RechartsTooltip formatter={(val) => formatIDR(val)} />
                      <Legend />
                    </RePieChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Top Kategori Pengeluaran</CardTitle></CardHeader>
                <CardContent><Table><TableHeader><TableRow><TableHead>Kategori</TableHead><TableHead className="right">Total</TableHead></TableRow></TableHeader><TableBody>{topExpenseCategories.map(r=><TableRow key={r.name}><TableCell>{r.name}</TableCell><TableCell className="right strong red-text">{formatIDR(r.value)}</TableCell></TableRow>)}{topExpenseCategories.length===0 && <TableRow><TableCell colSpan={2} className="center empty">Tidak ada pengeluaran pada periode ini.</TableCell></TableRow>}</TableBody></Table></CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Top Hutang Vendor</CardTitle></CardHeader>
                <CardContent><Table><TableHeader><TableRow><TableHead>Vendor</TableHead><TableHead className="right">Outstanding</TableHead></TableRow></TableHeader><TableBody>{topVendorDebts.map(r=><TableRow key={r.name}><TableCell>{r.name}</TableCell><TableCell className="right strong orange-text">{formatIDR(r.value)}</TableCell></TableRow>)}{topVendorDebts.length===0 && <TableRow><TableCell colSpan={2} className="center empty">Tidak ada hutang.</TableCell></TableRow>}</TableBody></Table></CardContent>
              </Card>
            </div>
          </section>
        )}

        {activeTab === "input" && (
          <section className="space input-workspace">
            <Card className="tracking tracking-wide">
              <CardHeader>
                <CardTitle className="between">
                  <span>Tracking Harga & Hutang ({trackingRows.length} dari {transactions.length})</span>
                  <span className="searchbox wide-search"><Search size={16}/><Input placeholder="Cari item, vendor, invoice, kategori, note..." value={globalSearch} onChange={e=>setGlobalSearch(e.target.value)} /></span>
                </CardTitle>
                <CardDescription>Tabel penuh untuk audit transaksi, harga satuan, satuan, vendor, status hutang/lunas, dan edit cepat.</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="tracking-toolbar tracking-toolbar-wide">
                  <label>Periode<select className="select" value={trackingDateMode} onChange={e=>setTrackingDateMode(e.target.value)}><option value="ALL">Semua tanggal</option><option value="TODAY">Hari ini</option><option value="MONTH">Bulanan</option><option value="CUSTOM">Custom</option></select></label>
                  {trackingDateMode === "MONTH" && <label>Bulan<select className="select" value={trackingMonthFilter} onChange={e=>setTrackingMonthFilter(e.target.value)}><option value="ALL">Semua bulan</option>{trackingMonthOptions.map(m=><option key={m.key} value={m.key}>{m.label}</option>)}</select></label>}
                  {trackingDateMode === "CUSTOM" && <><label>Dari<Input type="date" value={trackingStartDate} onChange={e=>setTrackingStartDate(e.target.value)}/></label><label>Sampai<Input type="date" value={trackingEndDate} onChange={e=>setTrackingEndDate(e.target.value)}/></label></>}
                  <label>Kategori<select className="select" value={trackingCategoryFilter} onChange={e=>setTrackingCategoryFilter(e.target.value)}><option value="ALL">Semua kategori</option>{trackingCategories.map(c=><option key={c} value={c}>{c}</option>)}</select></label>
                  <label>Vendor<select className="select" value={trackingVendorFilter} onChange={e=>setTrackingVendorFilter(e.target.value)}><option value="ALL">Semua vendor</option>{trackingVendors.map(v=><option key={v} value={v}>{v}</option>)}</select></label>
                  <label>Status<select className="select" value={trackingStatusFilter} onChange={e=>setTrackingStatusFilter(e.target.value)}><option value="ALL">Semua</option><option value="DEBT">Hutang aktif</option><option value="PAID">Lunas</option><option value="INCOME">Pemasukan</option><option value="EXPENSE">Pengeluaran</option><option value="PRICE">Ada qty/harga</option><option value="NO_PRICE">Qty tanpa harga</option></select></label>
                  <label>Urut<select className="select" value={trackingSort} onChange={e=>setTrackingSort(e.target.value)}><option value="LAST_INPUT">Terakhir input/ubah</option><option value="DATE_DESC">Tanggal terbaru</option><option value="DATE_ASC">Tanggal terlama</option><option value="AMOUNT_DESC">Nominal terbesar</option><option value="AMOUNT_ASC">Nominal terkecil</option><option value="UNIT_PRICE_DESC">Harga/unit terbesar</option><option value="OUTSTANDING_DESC">Outstanding terbesar</option></select></label>
                </div>
                <div className="tracking-summary">
                  <span>Total transaksi filter: <b>{trackingRows.length}</b></span>
                  <span>Pemasukan: <b className="green-text">{formatIDR(trackingRows.filter(t=>t.type==="income").reduce((a,b)=>a+safeNumber(b.amount),0))}</b></span>
                  <span>Pengeluaran: <b className="red-text">{formatIDR(trackingRows.filter(t=>t.type!=="income").reduce((a,b)=>a+safeNumber(b.amount),0))}</b></span>
                  <span>Hutang aktif: <b className="orange-text">{formatIDR(trackingRows.reduce((a,b)=>a+safeNumber(b.outstanding),0))}</b></span>
                </div>

                <div className="tracking-selection-actions">
                  <span>
                    Dipilih: <b>{selectedTrackingIds.length}</b> transaksi
                  </span>

                  {selectedTrackingIds.length > 0 && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={()=>setSelectedTrackingIds([])}
                    >
                      Batal Pilih
                    </Button>
                  )}

                  <Button
                    size="sm"
                    variant="red"
                    disabled={selectedTrackingIds.length===0}
                    onClick={deleteSelectedTracking}
                  >
                    <Trash2 size={14}/>
                    Hapus Dipilih ({selectedTrackingIds.length})
                  </Button>
                </div>
                <div className="scroll-table tracking-table tracking-table-wide">
                  <Table>
                    <TableHeader><TableRow><TableHead className="tracking-select-cell"><input type="checkbox" aria-label="Pilih semua transaksi sesuai filter" title="Pilih semua hasil filter" checked={allTrackingVisibleSelected} onChange={toggleAllTrackingVisible} /></TableHead><TableHead>Tgl Transaksi</TableHead><TableHead>Input/Ubah</TableHead><TableHead>Item</TableHead><TableHead>Kategori</TableHead><TableHead>Vendor</TableHead><TableHead>Status</TableHead><TableHead className="right">Qty</TableHead><TableHead>Satuan</TableHead><TableHead className="right">Harga/Unit</TableHead><TableHead className="right">Total</TableHead><TableHead className="right">Outstanding</TableHead><TableHead>Aksi</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {trackingRows.map(t=>(
                        <TableRow key={t.id} className={`${t.debtActive ? "debt-row" : ""} ${selectedTrackingSet.has(t.id) ? "selected-row" : ""}`.trim()}>
                          <TableCell className="tracking-select-cell">
                            <input
                              type="checkbox"
                              aria-label={`Pilih ${t.desc}`}
                              checked={selectedTrackingSet.has(t.id)}
                              onChange={()=>toggleTrackingSelection(t.id)}
                            />
                          </TableCell>
                          <TableCell className="small">{t.date}</TableCell>
                          <TableCell className="small">{t.inputMs ? new Date(t.inputMs).toLocaleString("id-ID", { day:"2-digit", month:"2-digit", year:"2-digit", hour:"2-digit", minute:"2-digit" }) : "-"}</TableCell>
                          <TableCell className="item-cell"><b>{t.desc}</b>{t.note ? <small className="mono">{t.note}</small> : null}<small className="mono">ID: {t.id}</small></TableCell>
                          <TableCell>{t.category}</TableCell>
                          <TableCell>{t.orderBy || "-"}</TableCell>
                          <TableCell>{t.debtActive ? <Badge variant="destructive">Hutang</Badge> : <Badge variant="soft">{t.type==="income" ? "Masuk" : (t.paymentStatus || "paid")}</Badge>}</TableCell>
                          <TableCell className="right">{safeNumber(t.qty) || "-"}</TableCell>
                          <TableCell>{t.unit || "-"}</TableCell>
                          <TableCell className="right">{safeNumber(t.unitPrice) ? formatIDR(t.unitPrice) : "-"}</TableCell>
                          <TableCell className={`right strong ${t.type==="income" ? "green-text" : "red-text"}`}>{formatIDR(t.amount)}</TableCell>
                          <TableCell className="right strong orange-text">{t.debtActive ? formatIDR(t.outstanding) : "-"}</TableCell>
                          <TableCell><div className="row-actions"><button title="Edit" onClick={()=>openEdit(t)}><Edit2 size={13}/></button><button title="Hapus" onClick={()=>confirmAction("Hapus Transaksi?", `Hapus ${t.desc} sebesar ${formatIDR(t.amount)}?`, async()=>handleDeleteTrans(t.id))}><Trash2 size={13}/></button></div></TableCell>
                        </TableRow>
                      ))}
                      {trackingRows.length===0 && <TableRow><TableCell colSpan={13} className="center empty">Tidak ada transaksi sesuai filter. Coba ubah status/filter/search.</TableCell></TableRow>}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>

            <div className="input-panel-grid">
              <Card className="left-form red-border-top input-manual-card">
                <CardHeader><CardTitle>Input Transaksi Manual</CardTitle><CardDescription>Form manual dipindah ke bawah agar tracking penuh lebar.</CardDescription></CardHeader>
                <CardContent className="form-stack">
                  <Input type="date" value={newTrans.date} onChange={(e)=>setNewTrans({...newTrans, date:e.target.value})} />
                  <div className="two-buttons">
                    <Button variant={newTrans.type==="expense" ? "red" : "outline"} onClick={()=>setNewTrans({...newTrans,type:"expense"})}><ArrowDownCircle size={16}/> Keluar</Button>
                    <Button variant={newTrans.type==="income" ? "green" : "outline"} onClick={()=>setNewTrans({...newTrans,type:"income"})}><ArrowUpCircle size={16}/> Masuk</Button>
                  </div>
                  <Input placeholder="Deskripsi (Cth: Beli Ayam)" value={newTrans.desc} onChange={(e)=>{
                    const val=e.target.value; const autoCat=learnCategoryFromHistory(val, newTrans.type); const autoType=autoCat.includes("Pemasukan")?"income":"expense";
                    setNewTrans({...newTrans,desc:val,category:autoCat,type:autoType});
                  }} />
                  <div className="three-cols">
                    <Input type="number" placeholder="Qty" value={newTrans.qty} onChange={(e)=>setNewTrans({...newTrans,qty:e.target.value})} />
                    <Input placeholder="Satuan" value={newTrans.unit} onChange={(e)=>setNewTrans({...newTrans,unit:e.target.value})} />
                    <Input type="number" placeholder="Harga" value={newTrans.unitPrice} onChange={(e)=>setNewTrans({...newTrans,unitPrice:e.target.value})} />
                  </div>
                  <Input type="number" value={newTrans.amount} onChange={(e)=>setNewTrans({...newTrans,amount:e.target.value})} placeholder="Total (Rp)" />
                  <label className="label">Kategori (Auto/Manual)</label>
                  <select className="select" value={newTrans.category} onChange={e=>{
                    const selectedCat=e.target.value; const autoType=selectedCat.includes("Pemasukan")?"income":"expense";
                    setNewTrans({...newTrans,category:selectedCat,type:autoType});
                  }}>
                    {categoryOptions.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                  <label className="checkbox"><input type="checkbox" checked={newTrans.isDebt} onChange={e=>setNewTrans({...newTrans,isDebt:e.target.checked})} /> Tandai sbg Hutang</label>
                  <Button onClick={handleAddTrans} className="full dark"><Save size={16}/> Simpan</Button>
                </CardContent>
              </Card>

              <div className="paste-stack">
                <Card className="red-border-top">
                  <CardHeader><CardTitle className="red-text"><Sparkles size={18}/> Paste Pengeluaran</CardTitle><CardDescription>Parser lokal untuk format chat. AI tetap lewat Custom GPT.</CardDescription></CardHeader>
                  <CardContent>
                    <Textarea placeholder="Mama Lemon 60 pouch x 8900 hutang Koperasi" value={bulkExpenseText} onChange={e=>setBulkExpenseText(e.target.value)} />
                    <Button onClick={()=>processBulkWithLocalParser(bulkExpenseText,"expense")} disabled={isBulkProcessing} className="full red">{isBulkProcessing ? <Loader2 className="spin"/> : "Proses Pengeluaran"}</Button>
                    {bulkStatus && <div className="bulk-status">{bulkStatus}</div>}
                  </CardContent>
                </Card>
                <Card className="green-border-top">
                  <CardHeader><CardTitle className="green-text"><Sparkles size={18}/> Paste Pemasukan</CardTitle><CardDescription>Contoh: INSENTIF 6000000 lunas</CardDescription></CardHeader>
                  <CardContent>
                    <Textarea placeholder="INSENTIF 6000000 lunas" value={bulkIncomeText} onChange={e=>setBulkIncomeText(e.target.value)} />
                    <Button onClick={()=>processBulkWithLocalParser(bulkIncomeText,"income")} disabled={isBulkProcessing} className="full green">{isBulkProcessing ? <Loader2 className="spin"/> : "Proses Pemasukan"}</Button>
                  </CardContent>
                </Card>
              </div>
            </div>
          </section>
        )}

        {activeTab === "debts" && (
          <section className="grid-three">
            <Card className="debt-summary">
              <CardHeader><CardTitle>Rincian Hutang per Vendor</CardTitle></CardHeader>
              <CardContent>
                <ul className="vendor-list">
                  {Object.entries(analytics.debtByVendor).length ? Object.entries(analytics.debtByVendor).map(([vendor, amount]) => <li key={vendor}><span>{vendor}</span><b>{formatIDR(amount)}</b></li>) : <p className="empty">Tidak ada hutang tercatat.</p>}
                </ul>
              </CardContent>
            </Card>
            <Card className="debt-table-card">
              <CardHeader className="orange-bg"><CardTitle><CreditCard size={20}/> Daftar Tagihan Belum Lunas</CardTitle></CardHeader>
              <CardContent className="no-pad">
                <div className="debt-total"><span>Total Hutang: {formatIDR(analytics.totalDebt)}</span>{analytics.totalDebt > 0 && <Button size="sm" variant="red" onClick={handlePayAllDebts}>Lunasi SEMUA Hutang</Button>}</div>
                <div className="debt-filterbar">
                  <label>Vendor<select className="select" value={debtVendorFilter} onChange={e=>setDebtVendorFilter(e.target.value)}><option value="ALL">Semua nama/vendor</option>{debtVendors.map(v=><option key={v} value={v}>{v}</option>)}</select></label>
                  <label>Kategori<select className="select" value={debtCategoryFilter} onChange={e=>setDebtCategoryFilter(e.target.value)}><option value="ALL">Semua kategori</option>{debtCategories.map(c=><option key={c} value={c}>{c}</option>)}</select></label>
                  <div className="filter-paybox"><span>Filter: {debtRows.length} transaksi · {formatIDR(debtRows.reduce((a,b)=>a+b.outstanding,0))}</span><Button size="sm" variant="green" onClick={()=>payDebtRows(debtRows)}>Lunasi Sesuai Filter</Button></div>
                </div>
                <Table>
                  <TableHeader><TableRow><TableHead>Tanggal</TableHead><TableHead>Ket</TableHead><TableHead>Kategori</TableHead><TableHead>Vendor</TableHead><TableHead className="right">Rp</TableHead><TableHead>Aksi</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {debtRows.length ? debtRows.map(t=>(
                      <TableRow key={t.id}><TableCell>{t.date}</TableCell><TableCell>{t.desc}</TableCell><TableCell>{t.category}</TableCell><TableCell>{t.orderBy}</TableCell><TableCell className="right strong orange-text">{formatIDR(t.outstanding)}</TableCell><TableCell><Button size="sm" variant="green" onClick={()=>handlePayDebt(t.id)}>Lunas</Button><button onClick={()=>openEdit(t)}><Edit2 size={13}/></button></TableCell></TableRow>
                    )) : <TableRow><TableCell colSpan={6} className="center empty">Tidak ada hutang pada filter ini.</TableCell></TableRow>}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </section>
        )}

        {activeTab === "reports" && (
          <section className="space">
            <div className="filterbar">
              <div className="periods">
                <Button variant={periodFilter==="daily"?"default":"ghost"} onClick={()=>{setPeriodFilter("daily");setCustomStartDate("");setCustomEndDate("");}}>Harian</Button>
                <Button variant={periodFilter==="weekly"?"default":"ghost"} onClick={()=>{setPeriodFilter("weekly");setCustomStartDate("");setCustomEndDate("");}}>Mingguan</Button>
                <Button variant={periodFilter==="monthly"?"default":"ghost"} onClick={()=>{setPeriodFilter("monthly");setCustomStartDate("");setCustomEndDate("");}}>Bulanan</Button>
                <Button variant={periodFilter==="custom"?"default":"ghost"} onClick={()=>setPeriodFilter("custom")}>Custom Tanggal</Button>
              </div>
              <select className="select month-select" value={monthFilter} onChange={e=>setMonthFilter(e.target.value)}><option value="ALL">Semua bulan</option>{monthOptions.map(m=><option key={m.key} value={m.key}>{m.label}</option>)}</select>
              {periodFilter==="custom" && <div className="date-range"><Input type="date" value={customStartDate} onChange={e=>setCustomStartDate(e.target.value)}/><span>s/d</span><Input type="date" value={customEndDate} onChange={e=>setCustomEndDate(e.target.value)}/></div>}
              <Button variant="outline" onClick={handlePrintReport}><Printer size={16}/> Cetak Laporan (Print/PDF)</Button>
            </div>
            <Card className="report-card">
              <CardHeader><CardTitle><FileText/> Laporan Laba Rugi Komplit</CardTitle><CardDescription>Rincian Insentif, Bahan, dan Operasional dalam satu tabel.</CardDescription></CardHeader>
              <CardContent>
                <div className="wide-table">
                  <Table>
                    <TableHeader><TableRow><TableHead>Periode</TableHead><TableHead className="center blue-soft">INSENTIF (SEWA)</TableHead><TableHead className="center green-soft">BAHAN BAKU</TableHead><TableHead className="center orange-soft">OPERASIONAL</TableHead><TableHead className="center purple-soft">MODAL, BEBAN & DIVIDEN</TableHead><TableHead className="right">PROFIT BERSIH</TableHead><TableHead className="right emerald-soft">ARUS KAS BERSIH</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {analytics.sortedPeriods.map((p,idx)=>(
                        <TableRow key={idx}>
                          <TableCell className="period-cell">{p.period}{p.isPending && <button className="pending" onClick={()=>confirmAction("Tandai Sudah Cair?",`Apakah periode ${p.period} sudah lunas/cair?`,()=>togglePeriodPaid(p.period))}>BELUM CAIR ⚠️</button>}{paidPeriods[p.period] && <button className="paid" onClick={()=>togglePeriodPaid(p.period)}>LUNAS <CheckCircle2 size={9}/></button>}</TableCell>
                          <TableCell className="center blue-text strong bigcell">{p.incSewa ? formatIDR(p.incSewa) : "-"}{p.incSewa>0 && <button className="detail-btn" onClick={()=>handleViewDetail(p,"sewa")}><Eye size={10}/> Rincian</button>}</TableCell>
                          <TableCell className="mini-report"><div><span>Dana:</span><b className="green-text">{formatIDR(p.incBahan)}</b></div><div><span>Blj:</span><b className="red-text">-{formatIDR(p.expBahan)}</b></div><div><span>Sisa:</span><b className={p.surplusBahan<0?"red-text":"green-text"}>{formatIDR(p.surplusBahan)}</b></div><button className="detail-btn" onClick={()=>handleViewDetail(p,"bahan")}><Eye size={10}/> Rincian Belanja</button></TableCell>
                          <TableCell className="mini-report"><div><span>Dana:</span><b className="orange-text">{formatIDR(p.incOps)}</b></div><div><span>Blj:</span><b className="red-text">-{formatIDR(p.expOps)}</b></div><div><span>Sisa:</span><b className={p.surplusOps<0?"red-text":"green-text"}>{formatIDR(p.surplusOps)}</b></div><button className="detail-btn" onClick={()=>handleViewDetail(p,"ops")}><Eye size={10}/> Rincian Ops</button></TableCell>
                          <TableCell className="mini-report"><div><b className="purple-text">Capex</b><span>-{formatIDR(p.expCapex)}</span></div><button className="detail-btn purple-text" onClick={()=>handleViewDetail(p,"modal")}><Eye size={10}/> Rincian</button><div><b className="red-text">Beban Profit</b><span>-{formatIDR(p.expProfitBurden)}</span></div><button className="detail-btn red-text" onClick={()=>handleViewDetail(p,"beban")}><Eye size={10}/> Rincian</button><div><b className="pink-text">Dividen</b><span>-{formatIDR(p.expDividend)}</span></div><button className="detail-btn pink-text" onClick={()=>handleViewDetail(p,"dividen")}><Eye size={10}/> Rincian</button></TableCell>
                          <TableCell className={`right strong xlarge ${p.netProfit<0?"red-text":"blue-text"}`}>{formatIDR(p.netProfit)}</TableCell>
                          <TableCell className={`right strong xlarge emerald-soft ${p.cashFlow<0?"red-text":"emerald-text"}`}>{formatIDR(p.cashFlow)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                    <TableFooter><TableRow className="footer-dark"><TableCell>TOTAL</TableCell><TableCell className="center">{formatIDR(analytics.sortedPeriods.reduce((a,b)=>a+b.incSewa,0))}</TableCell><TableCell className="right">Sisa: {formatIDR(analytics.sortedPeriods.reduce((a,b)=>a+b.surplusBahan,0))}</TableCell><TableCell className="right">Sisa: {formatIDR(analytics.sortedPeriods.reduce((a,b)=>a+b.surplusOps,0))}</TableCell><TableCell className="center"><div>C: {formatIDR(analytics.grandTotalCapex)}</div><div>B: {formatIDR(analytics.grandTotalProfitBurden)}</div><div>D: {formatIDR(analytics.grandTotalDividend)}</div></TableCell><TableCell className="right">{formatIDR(analytics.sortedPeriods.reduce((a,b)=>a+b.netProfit,0))}</TableCell><TableCell className="right">{formatIDR(analytics.sortedPeriods.reduce((a,b)=>a+b.cashFlow,0))}</TableCell></TableRow></TableFooter>
                  </Table>
                </div>
              </CardContent>
            </Card>
          </section>
        )}

        {activeTab === "dividend" && (
          <section className="grid-two">
            <Card className="green-border-top">
              <CardHeader><CardTitle className="green-text"><Users size={20}/> Manajemen Shareholder</CardTitle><CardDescription>Tambah penerima dividen, persentase, dan fee.</CardDescription></CardHeader>
              <CardContent>
                <div className="share-add">
                  <label>Nama Investor<Input id="newShName" placeholder="Contoh: Pak Budi" /></label>
                  <label>Pct (%)<Input id="newShPct" type="number" /></label>
                  <label>Fee (%)<Input id="newShFee" type="number" /></label>
                  <Button onClick={()=>{
                    const n=document.getElementById("newShName").value; const p=document.getElementById("newShPct").value; const f=document.getElementById("newShFee").value;
                    addShareholder(n,p,f); document.getElementById("newShName").value=""; document.getElementById("newShPct").value=""; document.getElementById("newShFee").value="";
                  }}><Plus size={16}/></Button>
                </div>
                <div className="boxed-table">
                  <Table>
                    <TableHeader><TableRow><TableHead>Nama</TableHead><TableHead className="right">Saham</TableHead><TableHead className="right">Fee</TableHead><TableHead></TableHead></TableRow></TableHeader>
                    <TableBody>
                      {shareholders.length ? shareholders.map(s=><TableRow key={s.id}><TableCell className="strong">{s.name}</TableCell><TableCell className="right">{s.pct}%</TableCell><TableCell className="right red-text">{s.mgmtFee||0}%</TableCell><TableCell><button onClick={()=>removeShareholder(s.id)}><Trash2 size={13}/></button></TableCell></TableRow>) : <TableRow><TableCell colSpan={4} className="center empty">Belum ada investor</TableCell></TableRow>}
                      {shareholders.length > 0 && <TableRow className="subtotal"><TableCell>TOTAL</TableCell><TableCell className={shareholders.reduce((a,b)=>a+b.pct,0)!==100?"right red-text":"right green-text"}>{shareholders.reduce((a,b)=>a+b.pct,0)}%</TableCell><TableCell></TableCell><TableCell></TableCell></TableRow>}
                    </TableBody>
                  </Table>
                </div>
                <h4 className="history-title"><History size={16}/> Riwayat Pembagian Dividen</h4>
                <div className="boxed-table dividend-history">
                  <Table><TableHeader><TableRow><TableHead>Tanggal</TableHead><TableHead>Ket</TableHead><TableHead className="right">Jumlah</TableHead><TableHead>Aksi</TableHead></TableRow></TableHeader><TableBody>{transactions.filter(t=>t.category==="Pembagian Dividen").map(t=><TableRow key={t.id}><TableCell>{t.date}</TableCell><TableCell>{t.desc}<small>{t.orderBy || "-"}</small></TableCell><TableCell className="right red-text strong">-{formatIDR(t.amount)}</TableCell><TableCell><button onClick={()=>openEdit(t)}><Edit2 size={13}/></button><button onClick={()=>confirmAction("Hapus Riwayat Dividen?", `Hapus ${t.desc}?`, ()=>handleDeleteTrans(t.id))}><Trash2 size={13}/></button></TableCell></TableRow>)}{transactions.filter(t=>t.category==="Pembagian Dividen").length===0 && <TableRow><TableCell colSpan={4} className="center empty">Belum ada riwayat pembagian</TableCell></TableRow>}</TableBody></Table>
                </div>
              </CardContent>
            </Card>
            <Card className="blue-border-top">
              <CardHeader><CardTitle className="blue-text"><PieChartIcon size={20}/> Kalkulator Dividen (Periode Custom)</CardTitle><CardDescription>Pilih tanggal untuk menghitung profit sesuai periode.</CardDescription></CardHeader>
              <CardContent className="form-stack">
                <div className="blue-panel">
                  <label>Periode Perhitungan Dividen</label>
                  <div className="date-range"><Input type="date" value={divCalcStart} onChange={e=>setDivCalcStart(e.target.value)}/><span>s/d</span><Input type="date" value={divCalcEnd} onChange={e=>setDivCalcEnd(e.target.value)}/></div>
                </div>
                <div className="formula-box">
                  <div className="line-control"><span>Dari Total Insentif ({formatIDR(calculatedDividendPool.rangeInsentif)})</span><Input type="number" value={dividendConfig.sourceInsentifPct} onChange={e=>setDividendConfig({...dividendConfig,sourceInsentifPct:safeNumber(e.target.value)})}/><span>%</span></div>
                  <div className="right small blue-text strong">Subtotal: {formatIDR(calculatedDividendPool.insentifPart)}</div>
                  <hr/>
                  <div className="line-control"><span>Target Profit dari Belanja Bahan</span><Input type="number" value={dividendConfig.targetProfitBahanPct} onChange={e=>setDividendConfig({...dividendConfig,targetProfitBahanPct:safeNumber(e.target.value)})}/><span>%</span></div>
                  <div className="right small muted">Total Belanja: {formatIDR(calculatedDividendPool.rangeExpenseBahan)}</div>
                  <div className="deduct"><div><span>- Capex:</span><b>{formatIDR(calculatedDividendPool.rangeCapex)}</b></div><div><span>- Beban Profit:</span><b>{formatIDR(calculatedDividendPool.rangeProfitBurden)}</b></div><div><span>- Hutang Global:</span><b>{formatIDR(analytics.totalDebt)}</b></div></div>
                  <div className="right small green-text strong">Net Profit Bahan: {formatIDR(calculatedDividendPool.bahanNet)}</div>
                </div>
                <div className="pool">
                  <div>TOTAL POOL DIVIDEN SIAP BAGI</div>
                  {dividendConfig.mode==="auto" ? <b onClick={()=>setDividendConfig({...dividendConfig,customAmount:calculatedDividendPool.autoTotal,mode:"manual"})}>{formatIDR(calculatedDividendPool.total)}</b> : <div><Input value={formatNumberInput(dividendConfig.customAmount)} onChange={e=>setDividendConfig({...dividendConfig,customAmount:parseIDRInput(e.target.value)})}/><Button variant="ghost" size="sm" onClick={()=>setDividendConfig({...dividendConfig,mode:"auto"})}><RefreshCw size={12}/> Reset ke Auto</Button></div>}
                </div>
                <div className="two-cols">
                  <label>Label Periode<Input value={dividendConfig.periodLabel} onChange={e=>setDividendConfig({...dividendConfig,periodLabel:e.target.value})}/></label>
                  <label>Tgl Pembagian<Input type="date" value={dividendConfig.distributionDate} onChange={e=>setDividendConfig({...dividendConfig,distributionDate:e.target.value})}/></label>
                </div>
                <div className="boxed-table">
                  <Table><TableHeader><TableRow><TableHead>Investor</TableHead><TableHead className="right">Gross</TableHead><TableHead className="right red-text">Mgmt Fee</TableHead><TableHead className="right">Net</TableHead></TableRow></TableHeader><TableBody>{shareholders.map(s=>{const d=getShareData(s);return <TableRow key={s.id}><TableCell>{s.name}</TableCell><TableCell className="right">{formatIDR(d.gross)}</TableCell><TableCell className="right red-text">-{formatIDR(d.fee)}</TableCell><TableCell><Input className={d.isManual ? "manual" : ""} value={formatNumberInput(d.net)} onChange={e=>setManualDistributions(prev=>({...prev,[s.id]:parseIDRInput(e.target.value)}))}/></TableCell></TableRow>})}</TableBody></Table>
                </div>
                <div className="two-buttons"><Button variant="outline" onClick={handlePrintInvestorReport}><Printer size={16}/> Cetak Laporan</Button><Button className="green" onClick={handleDistributeDividend}><DollarSign size={16}/> Bayar Dividen</Button></div>
              </CardContent>
            </Card>
          </section>
        )}

        {activeTab === "inventory" && (
          <section className="grid-three">
            <Card className="left-form cyan-border-top">
              <CardHeader><CardTitle><Package size={20}/> Kelola Stok</CardTitle><CardDescription>Tambah atau update stok gudang.</CardDescription></CardHeader>
              <CardContent className="form-stack">
                <Input placeholder="Nama Barang" value={newItem.name} onChange={e=>setNewItem({...newItem,name:e.target.value})}/>
                <div className="two-cols"><Input type="number" placeholder="Qty" value={newItem.qty} onChange={e=>setNewItem({...newItem,qty:e.target.value})}/><Input placeholder="Satuan" value={newItem.unit} onChange={e=>setNewItem({...newItem,unit:e.target.value})}/></div>
                <Input type="number" placeholder="Nilai per Unit (Rp)" value={newItem.valuePerUnit} onChange={e=>setNewItem({...newItem,valuePerUnit:e.target.value})}/>
                <select className="select" value={newItem.category} onChange={e=>setNewItem({...newItem,category:e.target.value})}>{categoryOptions.map(c=><option key={c} value={c}>{c}</option>)}</select>
                <Button className="cyan full" onClick={addInventoryItem}><Plus size={16}/> Tambah Stok</Button>
                <Textarea placeholder="Bulk stok: Beras 50 kg @13000" value={bulkInventoryText} onChange={e=>setBulkInventoryText(e.target.value)}/>
                <Button className="indigo full" onClick={()=>processInventoryBulkLocal(bulkInventoryText)}><Sparkles size={16}/> Proses Bulk</Button>
                <div className="asset-box"><span>Total Nilai Aset Gudang</span><b>{formatIDR(analytics.inventoryValue)}</b></div>
              </CardContent>
            </Card>
            <Card className="tracking">
              <CardHeader><CardTitle className="between"><span>Daftar Barang ({filteredInventory.length} dari {inventory.length} Item)</span><Button variant="outline" size="sm" onClick={handleExportInventoryCSV}><Download size={16}/> CSV</Button></CardTitle></CardHeader>
              <CardContent>
                <div className="inventory-filters">
                  <Input placeholder="Cari barang / kategori..." value={inventorySearch} onChange={e=>setInventorySearch(e.target.value)}/>
                  <select className="select" value={inventoryCategoryFilter} onChange={e=>setInventoryCategoryFilter(e.target.value)}><option value="ALL">Semua kategori</option>{inventoryCategoryOptions.map(c=><option key={c} value={c}>{c}</option>)}</select>
                  <select className="select" value={inventoryPriceFilter} onChange={e=>setInventoryPriceFilter(e.target.value)}><option value="ALL">Semua harga</option><option value="HAS_PRICE">Ada harga</option><option value="NO_PRICE">Harga 0 / perlu cek</option></select>
                  <Button variant="outline" size="sm" onClick={()=>{setInventorySearch("");setInventoryCategoryFilter("ALL");setInventoryPriceFilter("ALL");}}><Eraser size={14}/> Reset</Button>
                </div>
                <div className="scroll-table"><Table><TableHeader><TableRow><TableHead>Barang</TableHead><TableHead>Kategori</TableHead><TableHead className="right">Qty</TableHead><TableHead className="right">Harga/Unit</TableHead><TableHead className="right">Total</TableHead><TableHead></TableHead></TableRow></TableHeader><TableBody>{filteredInventory.length ? filteredInventory.map(item=><TableRow key={item.id}><TableCell className="strong">{item.name}<small>{item.priceSource ? `Harga: ${item.priceSource}` : ''}{item.lastStockDate ? ` · Stok: ${item.lastStockDate}` : ''}</small></TableCell><TableCell><Badge variant="soft">{item.category || "Tanpa Kategori"}</Badge></TableCell><TableCell className="right">{item.qty} {item.unit}</TableCell><TableCell className={`right ${safeNumber(item.valuePerUnit)===0?"orange-text strong":""}`}>{formatIDR(item.valuePerUnit)}</TableCell><TableCell className="right strong">{formatIDR(item.qty*item.valuePerUnit)}</TableCell><TableCell><button onClick={()=>openEditInventory(item)}><Edit2 size={13}/></button><button onClick={()=>removeInventoryItem(item.id)}><Trash2 size={13}/></button></TableCell></TableRow>) : <TableRow><TableCell colSpan={6} className="center empty">Tidak ada barang sesuai filter.</TableCell></TableRow>}</TableBody></Table></div>
              </CardContent>
            </Card>
          </section>
        )}

        {activeTab === "analysis" && (
          <section className="grid-two">
            <Card><CardHeader><CardTitle><BrainCircuit size={20}/> Analisa AI Keuangan</CardTitle><CardDescription>Analisa lokal cepat berdasarkan data Firebase.</CardDescription></CardHeader><CardContent><div className="info-box"><ul><li>Total Hutang: {formatIDR(analytics.totalDebt)}</li><li>Rasio Hutang: {analytics.debtRatio.toFixed(2)}%</li><li>Talangan Pending: {formatIDR(analytics.pendingFunds)}</li></ul></div><Button className="violet full" onClick={generateRealAiAnalysis} disabled={isAnalyzing}>{isAnalyzing ? <Loader2 className="spin"/> : <Sparkles/>} Analisa Sekarang</Button>{aiAnalysisResult && <div className="analysis-list">{aiAnalysisResult.map((res,idx)=><div key={idx} className={`analysis ${res.type}`}><b>{res.title}</b><span>{res.msg}</span></div>)}</div>}</CardContent></Card>
            <Card><CardHeader><CardTitle><ChefHat size={20}/> Menu Planner</CardTitle><CardDescription>Rencanakan menu harian berdasarkan stok.</CardDescription></CardHeader><CardContent className="form-stack"><div className="two-cols"><label>Jumlah Pax<Input type="number" value={menuPlanner.pax} onChange={e=>setMenuPlanner({...menuPlanner,pax:safeNumber(e.target.value)})}/></label><label>Budget/Pax<Input type="number" value={menuPlanner.budget} onChange={e=>setMenuPlanner({...menuPlanner,budget:safeNumber(e.target.value)})}/></label></div><Button variant="outline" className="full" onClick={generateMenuPlan}><Lightbulb/> Generate Menu</Button>{menuResult && <div className="info-box"><b>Rekomendasi Menu:</b><ul>{menuResult.menu.map((m,i)=><li key={i}>{m}</li>)}</ul><b>Estimasi Belanja Tambahan:</b><ul>{menuResult.shoppingList.map((s,i)=><li key={i}>{s.item} ({s.qty}) - {formatIDR(s.estCost)}</li>)}</ul><div className="right strong green-text">Total: {formatIDR(menuResult.totalEstCost)}</div></div>}</CardContent></Card>
          </section>
        )}

        {activeTab === "audit" && (
          <section className="space">
            <Card className="yellow-border-top">
              <CardHeader><CardTitle><ShieldAlert size={20}/> Audit Klasifikasi & Sinkron GPT</CardTitle><CardDescription>Tab baru. Tampilan lama tetap dipertahankan, audit ditambahkan di halaman terpisah.</CardDescription></CardHeader>
              <CardContent>
                <div className="audit-toolbar">
                  <div className="audit-summary"><span><Database size={16}/> Source GPT/Firebase: {transactions.filter(t=>String(t.source).includes("chatgpt")).length} transaksi</span><span><AlertTriangle size={16}/> Tampil: {auditRows.length}</span></div>
                  <div className="periods"><Button variant={auditFilter==="NEED_ACTION"?"default":"ghost"} onClick={()=>setAuditFilter("NEED_ACTION")}>Belum selesai</Button><Button variant={auditFilter==="RED"?"red":"ghost"} onClick={()=>setAuditFilter("RED")}>Merah saja</Button><Button variant={auditFilter==="ALL"?"default":"ghost"} onClick={()=>setAuditFilter("ALL")}>Semua</Button><Button variant={auditFilter==="DONE"?"green":"ghost"} onClick={()=>setAuditFilter("DONE")}>Selesai</Button></div>
                  {selectedAuditIds.length>0 && <Button variant="green" size="sm" onClick={()=>markAuditDone(selectedAuditIds)}><Check size={14}/> Tandai selesai ({selectedAuditIds.length})</Button>}
                </div>
                <div className="scroll-table">
                  <Table><TableHeader><TableRow><TableHead><input type="checkbox" checked={auditRows.length>0 && selectedAuditIds.length===auditRows.length} onChange={e=>setSelectedAuditIds(e.target.checked?auditRows.map(x=>x.id):[])}/></TableHead><TableHead>Status</TableHead><TableHead>Tanggal</TableHead><TableHead>Deskripsi</TableHead><TableHead>Kategori Editable</TableHead><TableHead>Rekomendasi dari Backup</TableHead><TableHead>Vendor</TableHead><TableHead className="right">Outstanding</TableHead><TableHead>Aksi</TableHead></TableRow></TableHeader><TableBody>{auditRows.map(t=><TableRow key={t.id} className={t.severity==="RED"?"audit-red":""}><TableCell><input type="checkbox" checked={selectedAuditIds.includes(t.id)} onChange={e=>setSelectedAuditIds(prev=>e.target.checked?[...prev,t.id]:prev.filter(id=>id!==t.id))}/></TableCell><TableCell>{t.auditStatus==="done"?<Badge variant="soft">Selesai</Badge>:t.severity==="RED"?<Badge variant="destructive">Merah</Badge>:<Badge variant="soft">Info</Badge>}</TableCell><TableCell>{t.date}</TableCell><TableCell>{t.desc}<small>{t.classificationReason || `Source: ${t.source || '-'}`}</small></TableCell><TableCell><select className="select audit-select" value={t.category} onChange={e=>applyRecommendedCategory(t.id, e.target.value)}>{categoryOptions.map(c=><option key={c} value={c}>{c}</option>)}</select></TableCell><TableCell className={t.mismatch?"orange-text strong":"green-text"}>{t.recommended}<button className="detail-btn" onClick={()=>applyRecommendedCategory(t.id, t.recommended)}><Check size={10}/> Pakai ini</button></TableCell><TableCell><Input value={t.orderBy || ''} onChange={e=>quickUpdateTransaction(t.id,{orderBy:e.target.value})}/></TableCell><TableCell className="right strong orange-text">{formatIDR(t.outstanding)}</TableCell><TableCell><button onClick={()=>openEdit(t)}><Edit2 size={13}/></button><button onClick={()=>markAuditDone(t.id)}><Check size={13}/></button></TableCell></TableRow>)}{auditRows.length===0 && <TableRow><TableCell colSpan={9} className="center empty">Tidak ada temuan audit pada filter ini.</TableCell></TableRow>}</TableBody></Table>
                </div>
              </CardContent>
            </Card>
          </section>
        )}

        {editCapitalOpen && <Modal title="Ubah Modal Awal" onClose={()=>setEditCapitalOpen(false)}><p className="muted">Saldo Buku dihitung dari Modal Awal + Masuk - Keluar.</p><Input value={formatNumberInput(tempCapital)} onChange={e=>setTempCapital(parseIDRInput(e.target.value))}/><Button className="full dark" onClick={async()=>{setInitialCapital(tempCapital); setEditCapitalOpen(false); if(db) await saveMeta({initialCapital:tempCapital});}}>Simpan Modal Awal</Button></Modal>}

        {editOpen && currentEdit && <Modal title="Edit Transaksi" wide onClose={()=>setEditOpen(false)}>
          <div className="edit-grid">
            <label>Tanggal<Input type="date" value={currentEdit.date} onChange={e=>setCurrentEdit({...currentEdit,date:e.target.value})}/></label>
            <label>Ket<Input value={currentEdit.desc} onChange={e=>setCurrentEdit({...currentEdit,desc:e.target.value})}/></label>
            <label>Vendor<Input value={currentEdit.orderBy||""} onChange={e=>setCurrentEdit({...currentEdit,orderBy:e.target.value})}/></label>
            <label>Total<Input type="number" value={currentEdit.amount} onChange={e=>setCurrentEdit({...currentEdit,amount:safeNumber(e.target.value)})}/></label>
            <label>Qty<Input type="number" value={currentEdit.qty||""} onChange={e=>setCurrentEdit({...currentEdit,qty:e.target.value})}/></label>
            <label>Satuan<Input value={currentEdit.unit||""} onChange={e=>setCurrentEdit({...currentEdit,unit:e.target.value})}/></label>
            <label>Harga/Unit<Input type="number" value={currentEdit.unitPrice||""} onChange={e=>setCurrentEdit({...currentEdit,unitPrice:e.target.value})}/></label>
            <label>Kategori<select className="select" value={currentEdit.category} onChange={e=>setCurrentEdit({...currentEdit,category:e.target.value})}>{categoryOptions.map(c=><option key={c} value={c}>{c}</option>)}</select></label>
            <label>Status Bayar<select className="select" value={currentEdit.paymentStatus || (currentEdit.isDebt ? "unpaid" : "paid")} onChange={e=>{
              const status=e.target.value;
              setCurrentEdit({
                ...currentEdit,
                paymentStatus: status,
                isDebt: status !== "paid",
                paidAmount: status === "paid" ? safeNumber(currentEdit.amount) : status === "unpaid" ? 0 : safeNumber(currentEdit.paidAmount)
              });
            }}><option value="paid">Lunas</option><option value="unpaid">Hutang / Belum Lunas</option><option value="partial">Sebagian</option></select></label>
            <label>Sudah Dibayar<Input type="number" value={currentEdit.paidAmount ?? ""} onChange={e=>setCurrentEdit({...currentEdit,paidAmount:safeNumber(e.target.value),paymentStatus:"partial",isDebt:true})}/></label>
            <label className="checkbox"><input type="checkbox" checked={Boolean(currentEdit.isDebt) || String(currentEdit.paymentStatus||"").toLowerCase() !== "paid"} onChange={e=>{
              const checked=e.target.checked;
              setCurrentEdit({...currentEdit,isDebt:checked,paymentStatus:checked?"unpaid":"paid",paidAmount:checked?0:safeNumber(currentEdit.amount)});
            }}/> Hutang?</label>
            <div className="edit-debt-preview"><span>Outstanding</span><b>{formatIDR(txOutstanding(currentEdit))}</b></div>
          </div>
          <Button className="full dark" onClick={saveEdit}>Simpan Perubahan</Button>
        </Modal>}

        {detailOpen && selectedDetail && <Modal title={selectedDetail.title} wide onClose={()=>setDetailOpen(false)}>
          <div className="detail-toolbar">
            <Input placeholder="Cari di rincian: item, vendor, invoice, kategori, nominal..." value={detailSearch} onChange={e=>setDetailSearch(e.target.value)} />
            <select className="select" value={detailSort} onChange={e=>setDetailSort(e.target.value)}>
              <option value="LAST_INPUT">Terakhir input/ubah</option>
              <option value="DATE_DESC">Tanggal terbaru</option>
              <option value="DATE_ASC">Tanggal terlama</option>
              <option value="AMOUNT_DESC">Nominal terbesar</option>
              <option value="AMOUNT_ASC">Nominal terkecil</option>
              <option value="VENDOR">Vendor A-Z</option>
            </select>
            <Badge variant="soft">{detailRows.length} dari {selectedDetail.data.length}</Badge>
          </div>
          <div className="detail-summary">
            <span>Total filter: <b>{formatIDR(detailRows.reduce((a,b)=>a+safeNumber(b.amount),0))}</b></span>
            <span>Hutang aktif: <b>{formatIDR(detailRows.reduce((a,b)=>a+safeNumber(b.outstanding),0))}</b></span>
          </div>
          <div className="scroll-table detail-scroll"><Table><TableHeader><TableRow><TableHead>Input</TableHead><TableHead>Tanggal</TableHead><TableHead>Deskripsi</TableHead><TableHead>Vendor</TableHead><TableHead>Status</TableHead><TableHead className="right">Jumlah</TableHead><TableHead>Aksi</TableHead></TableRow></TableHeader><TableBody>{detailRows.map(t=><TableRow key={t.id}><TableCell><small className="mono">{t.updatedAt ? "updated" : t.createdAt ? "created" : "date"}</small></TableCell><TableCell>{t.date}</TableCell><TableCell>{t.desc}<small>{t.category}</small>{t.note ? <small className="mono">{t.note}</small> : null}{safeNumber(t.qty) || safeNumber(t.unitPrice) ? <small className="mono">{t.qty} {t.unit} x {formatIDR(t.unitPrice)}</small> : null}</TableCell><TableCell>{t.orderBy || "-"}</TableCell><TableCell>{t.debtActive ? <Badge variant="destructive">Hutang</Badge> : <Badge variant="soft">Lunas</Badge>}</TableCell><TableCell className={`right strong ${t.type==="income"?"green-text":"red-text"}`}>{formatIDR(t.amount)}</TableCell><TableCell><div className="row-actions"><button title="Edit" onClick={()=>{setDetailOpen(false);openEdit(t);}}><Edit2 size={13}/></button><button title="Hapus" onClick={()=>deleteDetailTransaction(t)}><Trash2 size={13}/></button></div></TableCell></TableRow>)}{detailRows.length===0 && <TableRow><TableCell colSpan={7} className="center empty">Tidak ada transaksi sesuai pencarian.</TableCell></TableRow>}</TableBody></Table></div>
        </Modal>}

        {backupOpen && <Modal title="Riwayat Backup Cloud" onClose={()=>setBackupOpen(false)}>{isLoadingBackups ? <div className="center"><Loader2 className="spin"/> Loading data...</div> : <div className="backup-list">{backupList.map(b=><div key={b.id} className="backup-row"><div><b>{new Date(b.createdAtClient || b.id).toLocaleString("id-ID")}</b><small>Transaksi: {b.counts?.transactions || 0} · Stok: {b.counts?.inventory || 0} · Shareholder: {b.counts?.shareholders || 0}</small><small>{b.backupType || "metadata_lama"}</small></div><div className="row-actions"><Button size="sm" variant="outline" onClick={()=>loadBackup(b)}>Restore</Button><Button size="sm" variant="red" onClick={()=>deleteBackupPoint(b)}><Trash2 size={13}/> Hapus</Button></div></div>)}{backupList.length===0 && <p className="center empty">Belum ada backup tersimpan.</p>}</div>}</Modal>}


        {sheetSyncOpen && <Modal title="Google Sheet Sync" onClose={()=>setSheetSyncOpen(false)} wide>
          <div className="form-stack">
            <p className="muted">Tempel URL Google Apps Script Web App milik Anda. App akan mengirim/mengambil JSON database: transaksi, gudang, shareholder, dan meta.</p>
            <label>URL Web App Google Sheet<Input value={googleSheetUrl} onChange={e=>setGoogleSheetUrl(e.target.value)} placeholder="https://script.google.com/macros/s/.../exec" /></label>
            <div className="two-buttons"><Button variant="green" onClick={handleGoogleSheetExport}><Upload size={16}/> Export ke Google Sheet</Button><Button variant="blue" onClick={handleGoogleSheetImport}><Download size={16}/> Import dari Google Sheet</Button></div>
            <div className="hint">Catatan: koneksi langsung Google Sheet perlu Apps Script Web App. Kalau URL belum diisi, gunakan Export Excel DB atau Backup PC.</div>
          </div>
        </Modal>}
        {editInventoryOpen && currentEditInventory && <Modal title="Edit Stok Barang" onClose={()=>setEditInventoryOpen(false)}><div className="form-stack"><label>Nama Barang<Input value={currentEditInventory.name} onChange={e=>setCurrentEditInventory({...currentEditInventory,name:e.target.value})}/></label><div className="two-cols"><label>Qty<Input type="number" value={currentEditInventory.qty} onChange={e=>setCurrentEditInventory({...currentEditInventory,qty:e.target.value})}/></label><label>Satuan<Input value={currentEditInventory.unit} onChange={e=>setCurrentEditInventory({...currentEditInventory,unit:e.target.value})}/></label></div><label>Nilai per Unit<Input type="number" value={currentEditInventory.valuePerUnit} onChange={e=>setCurrentEditInventory({...currentEditInventory,valuePerUnit:e.target.value})}/></label><label>Kategori<select className="select" value={currentEditInventory.category || "Tanpa Kategori"} onChange={e=>setCurrentEditInventory({...currentEditInventory,category:e.target.value})}>{categoryOptions.map(c=><option key={c} value={c}>{c}</option>)}</select></label><Button className="full cyan" onClick={saveEditInventory}>Simpan Stok</Button></div></Modal>}
        {confirmOpen && <Modal title={confirmData.title} onClose={()=>setConfirmOpen(false)}>
          <p>{confirmData.msg}</p>
          <div className="modal-actions">
            <Button variant="outline" onClick={()=>setConfirmOpen(false)}>Batal</Button>
            <Button onClick={async()=>{const fn=confirmData.action; setConfirmOpen(false); if(fn) await fn();}}>Ya, Lanjutkan</Button>
          </div>
        </Modal>}

      </div>
    </div>
  );
}

function Modal({ title, children, onClose, wide = false }) {
  return (
    <div className="modal-backdrop">
      <div className={`modal ${wide ? "wide" : ""}`}>
        <div className="modal-head"><h3>{title}</h3><button onClick={onClose}><X size={16}/></button></div>
        {children}
      </div>
    </div>
  );
}

export default SmartCateringAccountant;
