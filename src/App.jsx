
import React, {useEffect, useMemo, useState} from "react";
import {createRoot} from "react-dom/client";
import {
  initializeApp
} from "firebase/app";
import {
  getAuth, signInAnonymously, onAuthStateChanged
} from "firebase/auth";
import {
  getFirestore, collection, doc, getDoc, setDoc, getDocs, writeBatch,
  serverTimestamp, query, orderBy, deleteDoc
} from "firebase/firestore";
import {
  Database, Cloud, CloudOff, Upload, Download, Send, ShieldAlert, Wallet,
  ReceiptText, CreditCard, Package, RefreshCw, Trash2, CheckCircle2, Search,
  FileJson, LayoutDashboard, Bot
} from "lucide-react";
import {ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend} from "recharts";
import {classify, buildMemory, groupOf, parseDailyText} from "./classifier";
import "./styles.css";

const money = n => new Intl.NumberFormat("id-ID",{style:"currency",currency:"IDR",maximumFractionDigits:0}).format(Number(n)||0);
const num = v => Number(v)||0;
const cleanDate = v => {
  if(!v) return new Date().toISOString().slice(0,10);
  if(typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v)) return v;
  if(v?.seconds) return new Date(v.seconds*1000).toISOString().slice(0,10);
  const d = new Date(v);
  return isNaN(d.getTime()) ? new Date().toISOString().slice(0,10) : d.toISOString().slice(0,10);
};
const id = () => crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;

function firebaseConfigFromEnv() {
  if (typeof window !== "undefined" && window.__firebase_config) {
    try { return JSON.parse(window.__firebase_config); } catch {}
  }
  const cfg = {
    apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
    authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
    projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
    storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
    messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
    appId: import.meta.env.VITE_FIREBASE_APP_ID
  };
  return cfg.apiKey && cfg.projectId ? cfg : null;
}

function normalizeTx(t, memory) {
  const base = {
    id: String(t.id ?? id()),
    date: cleanDate(t.date),
    desc: String(t.desc || "").trim(),
    amount: num(t.amount) || (num(t.qty) * num(t.unitPrice)),
    qty: num(t.qty) || 1,
    unit: String(t.unit || ""),
    unitPrice: num(t.unitPrice),
    type: t.type === "income" ? "income" : "expense",
    category: String(t.category || ""),
    orderBy: String(t.orderBy || t.vendor || "-"),
    isDebt: Boolean(t.isDebt),
    status: t.status || "done",
    paymentStatus: t.paymentStatus || (t.isDebt ? "unpaid" : "paid"),
    paidAmount: t.paidAmount !== undefined ? num(t.paidAmount) : (t.isDebt ? 0 : num(t.amount)),
    createdAtClient: t.createdAtClient || new Date().toISOString(),
    source: t.source || "legacy"
  };
  const c = classify(base, memory);
  if (!base.category || base.type === "income" || c.confidence >= .93) {
    base.category = c.category;
  }
  base.classification = c;
  return base;
}

function App() {
  const [firebaseState, setFirebaseState] = useState({ready:false, db:null, user:null, mode:"local", error:null});
  const [ledger, setLedger] = useState({initialCapital:0, actualBalance:0, transactions:[], inventory:[], shareholders:[], paidPeriods:{}});
  const [active, setActive] = useState("dashboard");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("Memuat aplikasi…");
  const [dailyText, setDailyText] = useState("");
  const [dailyDefaults, setDailyDefaults] = useState({date:new Date().toISOString().slice(0,10), vendor:"-", type:"expense"});
  const [search, setSearch] = useState("");

  const siteId = import.meta.env.VITE_SITE_ID || (typeof window !== "undefined" && window.__app_id) || "sppg-maja-gpt-site";

  useEffect(()=> {
    const cfg = firebaseConfigFromEnv();
    if (!cfg) {
      setFirebaseState(s=>({...s,ready:true,mode:"local",error:"Firebase config belum diisi"}));
      loadBaselineLocal();
      return;
    }
    try {
      const app = initializeApp(cfg);
      const auth = getAuth(app);
      const db = getFirestore(app);
      signInAnonymously(auth).catch(err => setFirebaseState({ready:true, db, user:null, mode:"error", error:err.message}));
      return onAuthStateChanged(auth, (u)=>{
        setFirebaseState({ready:true, db, user:u, mode:u?"firebase":"error", error:u?null:"auth gagal"});
      });
    } catch(err) {
      setFirebaseState({ready:true, db:null, user:null, mode:"local", error:err.message});
      loadBaselineLocal();
    }
  }, []);

  useEffect(()=> {
    if (firebaseState.mode === "firebase" && firebaseState.db && firebaseState.user) {
      loadFromFirebase(firebaseState.db);
    }
  }, [firebaseState.mode, firebaseState.user]);

  async function loadBaselineLocal() {
    setBusy(true);
    try {
      const r = await fetch("/data/baseline.json");
      const raw = await r.json();
      const mem = buildMemory(raw.transactions || []);
      const txs = (raw.transactions || []).map(t=>normalizeTx(t, mem));
      setLedger({...raw, transactions: txs, inventory: raw.inventory || [], shareholders: raw.shareholders || [], paidPeriods: raw.paidPeriods || {}});
      setMsg("Mode lokal: baseline JSON aktif");
    } catch(err) {
      setMsg("Gagal load baseline: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  const paths = {
    meta: () => doc(firebaseState.db, "gpt_sites", siteId, "ledger", "meta"),
    transactions: () => collection(firebaseState.db, "gpt_sites", siteId, "ledger", "meta", "transactions"),
    inventory: () => collection(firebaseState.db, "gpt_sites", siteId, "ledger", "meta", "inventory"),
    shareholders: () => collection(firebaseState.db, "gpt_sites", siteId, "ledger", "meta", "shareholders"),
    backups: () => collection(firebaseState.db, "gpt_sites", siteId, "ledger", "meta", "backups")
  };

  async function loadFromFirebase(db) {
    setBusy(true);
    try {
      const metaRef = doc(db, "gpt_sites", siteId, "ledger", "meta");
      const metaSnap = await getDoc(metaRef);
      if (!metaSnap.exists()) {
        await loadBaselineLocal();
        setMsg("Firebase kosong. Klik 'Upload baseline ke Firebase' untuk inisialisasi.");
        return;
      }
      const txSnap = await getDocs(query(collection(db, "gpt_sites", siteId, "ledger", "meta", "transactions"), orderBy("date", "desc")));
      const invSnap = await getDocs(collection(db, "gpt_sites", siteId, "ledger", "meta", "inventory"));
      const shSnap = await getDocs(collection(db, "gpt_sites", siteId, "ledger", "meta", "shareholders"));
      const meta = metaSnap.data();
      const rawTx = txSnap.docs.map(d=>({id:d.id, ...d.data()}));
      const mem = buildMemory(rawTx);
      const txs = rawTx.map(t=>normalizeTx(t, mem));
      setLedger({
        initialCapital: num(meta.initialCapital),
        actualBalance: num(meta.actualBalance),
        paidPeriods: meta.paidPeriods || {},
        lastUpdated: meta.lastUpdated || null,
        transactions: txs,
        inventory: invSnap.docs.map(d=>({id:d.id, ...d.data()})),
        shareholders: shSnap.docs.map(d=>({id:d.id, ...d.data()}))
      });
      setMsg(`Firebase aktif: ${txs.length} transaksi dimuat`);
    } catch(err) {
      setMsg("Gagal load Firebase: " + err.message);
      await loadBaselineLocal();
    } finally {
      setBusy(false);
    }
  }

  async function batchWriteDocs(colRef, items, transform=x=>x) {
    const db = firebaseState.db;
    for (let i=0; i<items.length; i+=450) {
      const batch = writeBatch(db);
      for (const item of items.slice(i,i+450)) {
        const docId = String(item.id || id()).replace(/[/.#\[\]]/g, "_");
        batch.set(doc(colRef, docId), transform({...item, id: docId}), {merge:true});
      }
      await batch.commit();
    }
  }

  async function uploadCurrentToFirebase() {
    if (firebaseState.mode !== "firebase") return alert("Firebase belum aktif.");
    setBusy(true);
    try {
      await setDoc(paths.meta(), {
        initialCapital: num(ledger.initialCapital),
        actualBalance: num(ledger.actualBalance),
        paidPeriods: ledger.paidPeriods || {},
        schemaVersion: 5,
        lastUpdated: new Date().toISOString(),
        updatedAt: serverTimestamp()
      }, {merge:true});
      await batchWriteDocs(paths.transactions(), ledger.transactions, x=>({...x, updatedAt: serverTimestamp()}));
      await batchWriteDocs(paths.inventory(), ledger.inventory || [], x=>({...x, updatedAt: serverTimestamp()}));
      await batchWriteDocs(paths.shareholders(), ledger.shareholders || [], x=>({...x, updatedAt: serverTimestamp()}));
      setMsg(`Baseline/ledger terkirim ke Firebase: ${ledger.transactions.length} transaksi`);
    } catch(err) {
      alert("Gagal upload Firebase: " + err.message);
      setMsg("Gagal upload Firebase");
    } finally {
      setBusy(false);
    }
  }

  async function addTransactions(rows, source="manual") {
    const mem = buildMemory(ledger.transactions);
    const txs = rows.map(r=>normalizeTx({...r, id:r.id || id(), source}, mem));
    setLedger(prev=>({...prev, transactions:[...prev.transactions, ...txs]}));
    if (firebaseState.mode === "firebase") {
      await batchWriteDocs(paths.transactions(), txs, x=>({...x, updatedAt: serverTimestamp()}));
      await setDoc(paths.meta(), {lastUpdated:new Date().toISOString(), updatedAt:serverTimestamp()}, {merge:true});
      setMsg(`${txs.length} transaksi masuk ke Firebase`);
    } else {
      setMsg(`${txs.length} transaksi masuk lokal`);
    }
  }

  async function saveBackupPoint() {
    if (firebaseState.mode !== "firebase") return exportJSON();
    setBusy(true);
    try {
      const payload = {
        createdAt: serverTimestamp(),
        createdAtClient: new Date().toISOString(),
        counts: {transactions: ledger.transactions.length, inventory: ledger.inventory.length},
        initialCapital: ledger.initialCapital,
        actualBalance: ledger.actualBalance
      };
      const b = doc(paths.backups(), new Date().toISOString().replace(/[^\d]/g,"").slice(0,14));
      await setDoc(b, payload);
      setMsg("Titik backup metadata dibuat. Backup penuh tetap lewat Export JSON.");
    } catch(err) {
      alert("Gagal backup: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  function exportJSON() {
    const payload = {...ledger, lastUpdated:new Date().toISOString(), schemaVersion:5};
    const blob = new Blob([JSON.stringify(payload, null, 2)], {type:"application/json"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `SmartCatering_Backup_GPTSite_${new Date().toISOString().slice(0,10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function importJSONFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      const raw = JSON.parse(await file.text());
      const mem = buildMemory(raw.transactions || []);
      const txs = (raw.transactions || []).map(t=>normalizeTx(t, mem));
      setLedger({...raw, transactions:txs, inventory: raw.inventory||[], shareholders: raw.shareholders||[], paidPeriods: raw.paidPeriods||{}});
      setMsg(`JSON dimuat: ${txs.length} transaksi. Klik upload Firebase jika mau sinkron.`);
    } catch(err) {
      alert("JSON gagal dibaca: " + err.message);
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  async function handleDailyProcess() {
    const parsed = parseDailyText(dailyText, dailyDefaults);
    if (!parsed.length) return alert("Tidak ada baris valid.");
    await addTransactions(parsed, "chat_or_daily_text");
    setDailyText("");
  }

  async function payDebt(t) {
    const patch = {paymentStatus:"paid", paidAmount:t.amount, isDebt:false, paidDate:new Date().toISOString().slice(0,10), updatedAtClient:new Date().toISOString()};
    setLedger(prev=>({...prev, transactions:prev.transactions.map(x=>x.id===t.id?{...x,...patch}:x)}));
    if (firebaseState.mode === "firebase") {
      await setDoc(doc(paths.transactions(), String(t.id)), patch, {merge:true});
      setMsg("Hutang ditandai lunas di Firebase");
    }
  }

  async function deleteTx(t) {
    if (!confirm("Hapus transaksi ini?")) return;
    setLedger(prev=>({...prev, transactions:prev.transactions.filter(x=>x.id!==t.id)}));
    if (firebaseState.mode === "firebase") {
      await deleteDoc(doc(paths.transactions(), String(t.id)));
      setMsg("Transaksi dihapus dari Firebase");
    }
  }

  const mem = useMemo(()=>buildMemory(ledger.transactions), [ledger.transactions]);
  const enriched = useMemo(()=>ledger.transactions.map(t=>{
    const s = classify(t, mem);
    return {...t, suggestion:s, needsReview: s.confidence < .80 || (t.category && s.category !== t.category && s.confidence >= .93)};
  }), [ledger.transactions, mem]);

  const stats = useMemo(()=>{
    const s = {income:0,expenseAccrual:0,cashPaid:0,debt:0,incSewa:0,incOps:0,incBahan:0,bahan:0,ops:0,capex:0,bebanProfit:0,dividen:0,review:0,monthly:{}};
    for (const t of enriched) {
      const g = groupOf(t.category, t.type);
      if (t.type === "income") {
        s.income += t.amount; s[g] = (s[g]||0)+t.amount;
      } else {
        s.expenseAccrual += t.amount;
        s.cashPaid += Math.min(t.amount, num(t.paidAmount));
        s.debt += Math.max(0, t.amount - num(t.paidAmount));
        s[g] = (s[g]||0)+t.amount;
      }
      if (t.needsReview) s.review++;
      const m = (t.date||"").slice(0,7) || "unknown";
      s.monthly[m] ||= {month:m, income:0, expense:0, cash:0};
      if (t.type === "income") s.monthly[m].income += t.amount; else {s.monthly[m].expense += t.amount; s.monthly[m].cash += Math.min(t.amount, num(t.paidAmount));}
    }
    s.inventoryValue = (ledger.inventory||[]).reduce((a,b)=>a+num(b.qty)*num(b.valuePerUnit),0);
    s.realBalance = num(ledger.actualBalance) || (num(ledger.initialCapital) + s.income - s.cashPaid);
    s.netWorth = s.realBalance + s.inventoryValue - s.debt;
    s.months = Object.values(s.monthly).sort((a,b)=>a.month.localeCompare(b.month));
    return s;
  }, [enriched, ledger.inventory, ledger.actualBalance, ledger.initialCapital]);

  const filtered = enriched.filter(t => `${t.date} ${t.desc} ${t.category} ${t.orderBy}`.toLowerCase().includes(search.toLowerCase())).sort((a,b)=>String(b.date).localeCompare(String(a.date)));

  const nav = [
    ["dashboard","Dashboard",LayoutDashboard],
    ["transactions","Transaksi",ReceiptText],
    ["debts","Hutang",CreditCard],
    ["inventory","Gudang",Package],
    ["audit","Audit Data",ShieldAlert]
  ];

  return <div className="app">
    <header className="topbar">
      <div>
        <h1>SPPG MAJA — Finance Control</h1>
        <p>Ledger v4 · accrual + cash basis · audit kategori · data terpisah dari aplikasi</p>
      </div>
      <div className="topactions">
        <span className="status"><Database size={14}/>{firebaseState.mode === "firebase" ? `Firebase aktif · ${ledger.transactions.length} transaksi` : msg}</span>
        <button className="btn ghost" onClick={()=>firebaseState.mode==="firebase"?loadFromFirebase(firebaseState.db):loadBaselineLocal()} disabled={busy}><RefreshCw size={15}/> Refresh</button>
        <label className="btn ghost"><Upload size={15}/> Import JSON<input type="file" accept=".json" hidden onChange={importJSONFile}/></label>
        <button className="btn" onClick={exportJSON}><Download size={15}/> Export</button>
      </div>
    </header>

    <nav className="nav">{nav.map(([k,label,Icon])=><button key={k} onClick={()=>setActive(k)} className={active===k?"active":""}><Icon size={16}/>{label}{k==="audit"&&stats.review?<b>{stats.review}</b>:null}</button>)}</nav>

    <main>
      {active==="dashboard" && <section>
        <div className="grid kpis">
          <KPI title="Saldo Real" value={money(stats.realBalance)} note="saldo kas/rekening terhitung" />
          <KPI title="Net Worth" value={money(stats.netWorth)} note="saldo + gudang − hutang" />
          <KPI title="Hutang Outstanding" value={money(stats.debt)} note="belum mengurangi kas" danger={stats.debt>0}/>
          <KPI title="Perlu Audit" value={stats.review} note="kategori/type perlu dicek" danger={stats.review>0}/>
        </div>
        <div className="grid two">
          <Card title="Ringkasan Akuntansi">
            <Rows rows={[
              ["Pemasukan total", money(stats.income)],
              ["Belanja diakui/accrual", money(stats.expenseAccrual)],
              ["Kas sudah keluar", money(stats.cashPaid)],
              ["Nilai stok gudang", money(stats.inventoryValue)],
              ["Pemasukan Insentif", money(stats.incSewa)],
              ["Pemasukan Ops", money(stats.incOps)],
              ["Pemasukan Bahan", money(stats.incBahan)],
            ]}/>
          </Card>
          <Card title="Komposisi Belanja">
            <Rows rows={[
              ["Bahan baku + packaging", money(stats.bahan)],
              ["Operasional", money(stats.ops)],
              ["Capex", money(stats.capex)],
              ["Beban profit", money(stats.bebanProfit)],
              ["Dividen", money(stats.dividen)],
            ]}/>
          </Card>
        </div>
        <Card title="Tren Bulanan">
          <div className="chart">
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={stats.months}>
                <CartesianGrid strokeDasharray="3 3" vertical={false}/>
                <XAxis dataKey="month"/>
                <YAxis tickFormatter={v=>`${Math.round(v/1000000)}jt`}/>
                <Tooltip formatter={v=>money(v)}/>
                <Legend/>
                <Bar dataKey="income" name="Pemasukan"/>
                <Bar dataKey="expense" name="Belanja/Accrual"/>
                <Bar dataKey="cash" name="Kas Keluar"/>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </section>}

      {active==="input" && <section className="grid two">
        <Card title="Input Harian / Paket dari ChatGPT">
          <p className="muted">Format cepat: <code>Nama item qty satuan x harga vendor/status</code>. Bisa juga tab/semicolon: <code>desc;qty;unit;unitPrice;amount;vendor;hutang</code>.</p>
          <div className="formrow">
            <label>Tanggal default<input type="date" value={dailyDefaults.date} onChange={e=>setDailyDefaults({...dailyDefaults,date:e.target.value})}/></label>
            <label>Vendor default<input value={dailyDefaults.vendor} onChange={e=>setDailyDefaults({...dailyDefaults,vendor:e.target.value})}/></label>
            <label>Tipe<select value={dailyDefaults.type} onChange={e=>setDailyDefaults({...dailyDefaults,type:e.target.value})}><option value="expense">Pengeluaran</option><option value="income">Pemasukan</option></select></label>
          </div>
          <textarea value={dailyText} onChange={e=>setDailyText(e.target.value)} placeholder={`Contoh:
Ayam Fillet 185 kg x 45000 Hutang Koperasi
Mama Lemon 60 pouch x 8900 Hutang Koperasi
INSENTIF 1 unit x 6000000`} />
          <button className="btn wide" onClick={handleDailyProcess} disabled={busy}><Send size={16}/> Klasifikasi & Simpan ke Firebase</button>
        </Card>
        <Card title="Preview Cara Saya Akan Input dari Chat">
          <p className="muted">Untuk tes otomatis dari chat, kirim data harian ke percakapan ini. Saya akan balas paket yang bisa langsung dipaste di kotak kiri, atau setelah endpoint tersedia saya bisa dorong ke cloud.</p>
          <Rows rows={[
            ["Ayam/Tahu/Tempe/Telur/Ikan", "Bahan Baku (Lauk)"],
            ["Sayur/Buah/Bumbu basah", "Bahan Baku (Sayur/Buah)"],
            ["Beras/Minyak/Tepung/Bumbu kering", "Bahan Baku (Sembako/Bumbu)"],
            ["Box/Mika/Cup/Sendok", "Packaging"],
            ["Tisu/Mama Lemon/Sarung tangan/Hair net", "Operasional (Kebersihan/APD)"],
            ["Apron/bonus/non-reimburse", "Beban Profit"],
            ["Kompor/Kulkas/Tabung/Renovasi", "Capex"],
          ]}/>
        </Card>
      </section>}

      {active==="transactions" && <Card title={`Transaksi (${filtered.length}/${ledger.transactions.length})`}>
        <div className="toolbar"><label className="search"><Search size={14}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Cari transaksi/vendor/kategori"/></label></div>
        <Table rows={filtered.slice(0,1000)} onDelete={deleteTx}/>
      </Card>}

      {active==="debts" && <Card title="Hutang Belum Lunas">
        <Debt rows={enriched.filter(t=>t.type==="expense" && t.amount > num(t.paidAmount))} onPay={payDebt}/>
      </Card>}

      {active==="inventory" && <Card title={`Gudang (${ledger.inventory.length} item)`}>
        <Inventory ledger={ledger} setLedger={setLedger}/>
      </Card>}

      {active==="audit" && <Card title="Audit Klasifikasi">
        <Audit rows={enriched.filter(t=>t.needsReview)} />
      </Card>}

      {active==="backup" && <section className="grid two">
        <Card title="Backup JSON">
          <p className="muted">Backup penuh tetap paling aman dalam bentuk JSON karena data sudah besar. Firestore dipakai untuk transaksi per dokumen.</p>
          <button className="btn wide" onClick={exportJSON}><Download size={16}/> Download Backup JSON</button>
          <button className="btn wide secondary" onClick={saveBackupPoint}><FileJson size={16}/> Buat Titik Backup Metadata</button>
        </Card>
        <Card title="Restore JSON">
          <p className="muted">Restore membaca JSON ke layar dulu. Setelah benar, klik Upload ke Firebase.</p>
          <label className="btn wide secondary"><Upload size={16}/> Restore dari JSON<input hidden type="file" accept=".json" onChange={importJSONFile}/></label>
        </Card>
      </section>}
    </main>
  </div>
}

function KPI({title,value,note,danger}) { return <div className={`kpi ${danger?"danger":""}`}><span>{title}</span><b>{value}</b><small>{note}</small></div> }
function Card({title,children}) { return <section className="card"><h2>{title}</h2>{children}</section> }
function Rows({rows}) { return <div className="rows">{rows.map(([a,b])=><div key={a}><span>{a}</span><b>{b}</b></div>)}</div> }

function Table({rows,onDelete}) {
  return <div className="tablewrap"><table><thead><tr><th>Tanggal</th><th>Deskripsi</th><th>Tipe</th><th>Kategori</th><th>Vendor</th><th className="right">Nilai</th><th>Bayar</th><th></th></tr></thead>
  <tbody>{rows.map(t=><tr key={t.id}>
    <td>{t.date}</td><td><b>{t.desc}</b><small>{t.qty} {t.unit} × {money(t.unitPrice)}</small></td>
    <td><span className={`pill ${t.type}`}>{t.type==="income"?"MASUK":"KELUAR"}</span></td>
    <td>{t.category}</td><td>{t.orderBy}</td><td className="right"><b>{money(t.amount)}</b></td>
    <td>{t.type==="income"?"-":money(num(t.paidAmount))}</td>
    <td><button className="icon danger" onClick={()=>onDelete(t)}><Trash2 size={14}/></button></td>
  </tr>)}</tbody></table></div>
}

function Debt({rows,onPay}) {
  const total = rows.reduce((a,t)=>a+(t.amount-num(t.paidAmount)),0);
  return <><div className="total">Total hutang: <b>{money(total)}</b></div>
  <div className="tablewrap"><table><thead><tr><th>Tanggal</th><th>Item</th><th>Vendor</th><th className="right">Tagihan</th><th className="right">Sisa</th><th></th></tr></thead>
  <tbody>{rows.map(t=><tr key={t.id}><td>{t.date}</td><td>{t.desc}</td><td>{t.orderBy}</td><td className="right">{money(t.amount)}</td><td className="right"><b>{money(t.amount-num(t.paidAmount))}</b></td><td><button className="btn sm" onClick={()=>onPay(t)}><CheckCircle2 size={14}/> Lunas</button></td></tr>)}</tbody></table></div></>
}

function Inventory({ledger,setLedger}) {
  const patch=(i,k,v)=>setLedger(prev=>({...prev,inventory:prev.inventory.map((x,idx)=>idx===i?{...x,[k]:v}:x)}));
  return <div className="tablewrap"><table><thead><tr><th>Barang</th><th>Qty</th><th>Satuan</th><th>Nilai/Unit</th><th className="right">Total</th></tr></thead>
  <tbody>{(ledger.inventory||[]).map((x,i)=><tr key={x.id||i}><td><input value={x.name||""} onChange={e=>patch(i,"name",e.target.value)}/></td><td><input type="number" value={x.qty||0} onChange={e=>patch(i,"qty",num(e.target.value))}/></td><td><input value={x.unit||""} onChange={e=>patch(i,"unit",e.target.value)}/></td><td><input type="number" value={x.valuePerUnit||0} onChange={e=>patch(i,"valuePerUnit",num(e.target.value))}/></td><td className="right"><b>{money(num(x.qty)*num(x.valuePerUnit))}</b></td></tr>)}</tbody></table></div>
}

function Audit({rows}) {
  return <div className="tablewrap"><table><thead><tr><th>Tanggal</th><th>Deskripsi</th><th>Kategori Sekarang</th><th>Saran</th><th>Confidence</th><th>Alasan</th></tr></thead>
  <tbody>{rows.slice(0,1000).map(t=><tr key={t.id}><td>{t.date}</td><td>{t.desc}<small>{t.type}</small></td><td>{t.category}</td><td>{t.suggestion.category}</td><td>{Math.round(t.suggestion.confidence*100)}%</td><td>{t.suggestion.reason}</td></tr>)}</tbody></table></div>
}

createRoot(document.getElementById("root")).render(<App/>);
