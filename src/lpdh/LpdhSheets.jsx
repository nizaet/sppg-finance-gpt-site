import React from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

export const SHEET_ORDER = [
  "Petunjuk",
  "Identitas",
  "A_PM",
  "B_BahanBaku",
  "C_Operasional",
  "C1_Relawan",
  "D_Insentif",
  "E_Saldo",
  "F_TopUp",
  "G_CekPPK",
  "H_RekapPPK",
  "I_RegisterBukti",
  "J_Pengesahan",
  "Ref",
];

const money = (value) => `Rp ${Number(value || 0).toLocaleString("id-ID", { maximumFractionDigits: 2 })}`;
const num = (value) => Number(value || 0).toLocaleString("id-ID", { maximumFractionDigits: 2 });
const yes = (value) => ["ya","yes","true","1"].includes(String(value || "").toLowerCase()) ? "Ya" : "Tidak";

function Table({ headers, rows, empty = "Belum ada data." }) {
  return <div className="lpdh-table-wrap"><table className="lpdh-data-table preview"><thead><tr>{headers.map((h)=><th key={h}>{h}</th>)}</tr></thead><tbody>
    {rows?.length ? rows.map((row,index)=><tr key={index}>{row.map((cell,i)=><td key={i}>{cell}</td>)}</tr>) : <tr><td colSpan={headers.length} className="lpdh-empty-cell">{empty}</td></tr>}
  </tbody></table></div>;
}

function Status({ ok, children }) {
  return <span className={ok ? "lpdh-check ok" : "lpdh-check bad"}>{ok ? <CheckCircle2 size={14}/> : <AlertTriangle size={14}/>} {children}</span>;
}

function Petunjuk() {
  return <div className="lpdh-sheet-body"><h3>Petunjuk</h3><p>Alur aplikasi mengikuti workbook resmi: isi master → tetapkan Hari Pelayanan Efektif → finalkan Kalkulator → isi realisasi harian → periksa setiap tab → bersihkan G_CekPPK → generate Excel.</p>
    <ol className="lpdh-steps"><li>Nomor bukti harus unik. Satu invoice dengan banyak barang diberi suffix otomatis.</li><li>Biaya bahan baku/porsi dan operasional/PM dipantau terhadap pagu.</li><li>Generate terkunci selama ada status PERIKSA.</li><li>Excel hasil generate tetap memakai rumus pada template resmi.</li></ol>
  </div>;
}

function Identity({ masters, daily, serviceDate }) {
  const i=masters?.identity||{}; const s=masters?.signers||[];
  const rows=[
    ["Nomor LPDH",daily?.lpdhNumber||i.lpdhNumber||""],["ID SPPG",i.sppgId||""],["Nama SPPG",i.sppgName||""],["Desa/Kelurahan",i.village||""],["Kecamatan",i.district||""],["Kab/Kota",i.city||""],["Provinsi",i.province||""],["Yayasan",i.foundation||""],["VA",i.vaNumber||""],["Bank",i.bankName||""],["Tanggal Pelayanan",serviceDate],["Status Hari",daily?.dayStatus||""],["HPE ke",daily?.hpeNumber||""],["Tanggal Upload",daily?.upload?.date||""],["Jam Upload",daily?.upload?.time||""]
  ];
  return <div className="lpdh-sheet-body"><h3>Identitas</h3><Table headers={["Field","Nilai"]} rows={rows}/><h4>Pengesah</h4><Table headers={["Nama","Jenis ID","Nomor","Tanda tangan"]} rows={s.slice(0,3).map(x=>[x.name||"",x.identityType||"",x.identityNumber||"",yes(x.signed)])}/></div>;
}

function APM({ preview }) {
  const p=preview||{}; const pr=p.production||{};
  return <div className="lpdh-sheet-body"><h3>A_PM</h3><Table headers={["Kode","Kelompok","Porsi","Target","Distribusi","Diterima","Tidak diterima","Selisih","BNBA","BAST","Status","PM dihitung"]} rows={(p.pmRows||[]).map(x=>[x.code,x.label,x.portion,num(x.targetPm),num(x.distributed),num(x.received),num(x.notReceived),num(x.difference),x.bnba,x.bastNo,x.bastStatus,num(x.calculatedPm)])}/>
    <div className="lpdh-summary-cards"><div><span>Diproduksi</span><strong>{num(pr.produced)}</strong></div><div><span>Didistribusikan</span><strong>{num(pr.distributed)}</strong></div><div><span>Selisih produksi</span><strong>{num(pr.difference)}</strong></div><div><span>PM Insentif</span><strong>{num(pr.incentivePm)}</strong></div></div></div>;
}

function Raw({ preview }) {
  return <div className="lpdh-sheet-body"><h3>B_BahanBaku</h3><Table headers={["No","Tanggal","Bahan","Kategori","Volume","Unit","Harga","Jumlah","Supplier","No Invoice","Bukti"]} rows={(preview?.rawMaterials||[]).map((x,i)=>[i+1,x.date||"",x.name||"",x.category||"",num(x.qty),x.unit||"",money(x.price),money(x.amount),x.supplier||"",x.invoiceNo||"",x.evidenceLink||""])}/>
    <div className="lpdh-summary-cards"><div><span>Total bahan</span><strong>{money(preview?.rawTotal)}</strong></div><div><span>Biaya/porsi</span><strong>{money(preview?.rawPerPortion)}</strong></div><div><span>Pagu/porsi</span><strong>{money(preview?.weightedRawPagu)}</strong></div><div><span>Status</span><strong>{preview?.rawStatus||"-"}</strong></div></div></div>;
}

function Operational({ preview }) {
  const rows=(preview?.operationalGroups||preview?.operations||[]).map((x,i)=>[i+1,x.date||"",x.description||"",num(x.qty),x.unit||"",money(x.price),money(x.amount),x.invoiceNo||"",x.evidenceLink||""]);
  rows.unshift(["","","Relawan","","","",money(preview?.volunteerTotal),"",""]);
  rows.splice(1,0,["","","Insentif guru/kader","","","",money(preview?.incentiveRecipientTotal),"",""]);
  return <div className="lpdh-sheet-body"><h3>C_Operasional</h3><Table headers={["No","Tanggal","Uraian","Volume","Unit","Harga","Jumlah","No Bukti","Link"]} rows={rows}/>
    <div className="lpdh-summary-cards"><div><span>Total operasional</span><strong>{money(preview?.operationalTotal)}</strong></div><div><span>Operasional/PM</span><strong>{money(preview?.operationalPerPm)}</strong></div><div><span>Pagu/PM</span><strong>{money(preview?.operationalPagu)}</strong></div><div><span>Status</span><strong>{preview?.operationalStatus||"-"}</strong></div></div></div>;
}

function Volunteer({ preview }) {
  return <div className="lpdh-sheet-body"><h3>C1_Relawan</h3><Table headers={["No","Nama","Tugas","Tanggal","Hari Kerja","Tarif Harian","Jumlah","Metode","No Kuitansi","Link Bukti"]} rows={(preview?.volunteers||[]).map((x,i)=>[i+1,x.name||"",x.role||"",x.date||"",num(x.workDays),money(x.dailyRate),money(x.amount),x.paymentMethod||"",x.receiptNo||"",x.evidenceLink||""])}/><div className="lpdh-total-line">Total relawan: <strong>{money(preview?.volunteerTotal)}</strong></div></div>;
}

function Incentive({ preview, daily }) {
  const x=daily?.incentive||{}; const e=x.eligibility||{};
  const missing=(preview?.pmRows||[]).filter(r=>Number(r.received)>0&&r.bastStatus!=="Terlampir");
  return <div className="lpdh-sheet-body"><h3>D_Insentif · Mitra/Yayasan</h3>
    <p className="lpdh-sheet-help">Sama dengan rumus Excel: PM dasar = PM diterima yang memenuhi BNBA + BAST + HPE, ditambah organoleptik dan retained sample pada HPE. Insentif dihitung hanya jika seluruh syarat layanan terpenuhi. Nilai pernyataan PPK dan pembayaran tetap diisi sesuai dokumen nyata.</p>
    {missing.length>0&&<div className="lpdh-status-box warn"><strong>{missing.length} kelompok belum dilengkapi BAST</strong><span>{num(missing.reduce((sum,r)=>sum+Number(r.received||0),0))} PM diterima belum masuk perhitungan insentif. Lengkapi nomor dan link BAST di A_PM; angka tidak diubah menjadi 0 pada data distribusi.</span></div>}
    <Table headers={["Syarat","Nilai"]} rows={[
    ["Hari berstatus HPE",preview?.hpeEligible?"Ya":"Tidak"],["Kontaminasi",yes(e.contamination)],["Insiden fatal",yes(e.fatalIncident)],["Suspend",yes(e.suspended)],["Terverifikasi",yes(e.verified)],["PM masuk SIPGN",yes(e.pmInputSipgn)],["PM dasar insentif",num(preview?.production?.incentivePm)],["Tarif",money(preview?.parameters?.incentiveTariff)],["Insentif dihitung",money(preview?.incentiveCalculated)],["No Pernyataan PPK",x.ppkStatementNo||""],["Nilai Pernyataan",money(x.statementAmount)],["Dibayar",money(x.paidAmount)],["Tanggal",x.paymentDate||""],["No Bukti",x.proofNo||""],["No Kuitansi",x.receiptNo||""],["Bukti",x.evidenceLink||""]
    ,["Insentif dapat diberikan",preview?.incentiveEligible?"Ya":"Tidak"],["Kode transaksi (otomatis)",preview?.incentiveTransactionCode||""],["Referensi transaksi VA",x.vaReference||""]
  ]}/></div>;
}

function Balance({ preview, daily }) {
  const b=preview?.balance||{}; const rows=["raw","operational","incentive"].map(k=>[k==="raw"?"Bahan baku":k==="operational"?"Operasional":"Insentif",money(b.opening?.[k]),money(b.topups?.[k]),money(b.expenditure?.[k]),money(b.closing?.[k])]);
  return <div className="lpdh-sheet-body"><h3>E_Saldo</h3><Table headers={["Komponen","Saldo Awal","TopUp","Pengeluaran","Saldo Akhir"]} rows={rows}/><div className="lpdh-summary-cards"><div><span>Total saldo komponen</span><strong>{money(b.closingTotal)}</strong></div><div><span>Saldo VA</span><strong>{money(b.bankBalance)}</strong></div><div><span>Selisih</span><strong>{money(b.bankDifference)}</strong></div></div><h4>Penerimaan TopUp</h4><Table headers={["Tanggal","Referensi","Bahan","Operasional","Insentif","Kuitansi","Bukti"]} rows={(daily?.topups||[]).map(x=>[x.date||"",x.reference||"",money(x.rawAmount),money(x.operationalAmount),money(x.incentiveAmount),x.receiptNo||"",x.evidenceLink||""])}/></div>;
}

function Topup({ preview }) {
  const p=preview?.topup||{};
  return <div className="lpdh-sheet-body"><h3>F_TopUp</h3><Table headers={["Komponen","Usulan SPPG Otomatis"]} rows={[
    ["Biaya Bahan Baku Pangan",money(p.requiredRaw)],
    ["Biaya Operasional",money(p.requiredOperational)],
    ["Insentif Ketersediaan dan Mutu Layanan",money(p.requiredIncentive)],
    ["JUMLAH",money(p.requiredTotal)],
    ["Ruang top up s.d. batas saldo VA",money(p.roomToMax)]
  ]}/><Status ok={p.withinMax}>Usulan {p.withinMax?"dalam":"melebihi"} batas saldo VA</Status><p className="lpdh-sheet-help">Kolom “Disetujui PPK” pada Excel tetap menjadi kewenangan Tim PPK dan tidak diisi otomatis.</p></div>;
}

function Checks({ preview }) {
  return <div className="lpdh-sheet-body"><h3>G_CekPPK</h3><div className="lpdh-check-summary"><Status ok={preview?.ready}>{preview?.ready?"SEMUA VALIDASI OK":"MASIH ADA YANG HARUS DIPERBAIKI"}</Status><strong>{preview?.errorCount||0} PERIKSA</strong></div>
    <Table headers={["No","Pemeriksaan","Status","Detail"]} rows={(preview?.checks||[]).map(x=>[x.no,x.check,<Status key={x.no} ok={x.ok}>{x.status}</Status>,x.detail||""])}/></div>;
}

function Rekap({ preview, masters, daily, serviceDate }) {
  const i=masters?.identity||{}; const p=preview||{}; const b=p.balance||{};
  const rows=[["Tanggal",serviceDate],["SPPG",i.sppgName||""],["Yayasan",i.foundation||""],["PM dihitung",num(p.production?.calculatedPm)],["PM insentif",num(p.production?.incentivePm)],["Total bahan",money(p.rawTotal)],["Bahan/porsi",money(p.rawPerPortion)],["Status bahan",p.rawStatus||""],["Total operasional",money(p.operationalTotal)],["Operasional/PM",money(p.operationalPerPm)],["Status operasional",p.operationalStatus||""],["Insentif dihitung",money(p.incentiveCalculated)],["Saldo akhir",money(b.closingTotal)],["Saldo VA",money(b.bankBalance)],["Selisih VA",money(b.bankDifference)],["Validasi",p.ready?"LENGKAP":"PERLU PERBAIKAN"]];
  return <div className="lpdh-sheet-body"><h3>H_RekapPPK</h3><Table headers={["Ringkasan","Nilai"]} rows={rows}/></div>;
}

function Register({ preview }) {
  return <div className="lpdh-sheet-body"><h3>I_RegisterBukti</h3><Table headers={["Sumber","Kode","Nomor Bukti","Tanggal","Nilai","Link","Status"]} rows={(preview?.register||[]).map(x=>[x.source,x.code,x.proofNo,x.date||"",money(x.amount),x.link||"",<Status key={x.code} ok={x.proofStatus==="UNIK"}>{x.proofStatus}</Status>])}/></div>;
}

function Approval({ masters, preview, serviceDate }) {
  const i=masters?.identity||{}; const signers=masters?.signers||[];
  return <div className="lpdh-sheet-body"><h3>J_Pengesahan</h3><div className="lpdh-approval"><h2>LEMBAR PENGESAHAN LPDH</h2><p>{i.sppgName||"SPPG"} · {serviceDate}</p><p>Dengan ini menyatakan data realisasi, bukti transaksi, saldo, dan perhitungan pada LPDH telah diperiksa.</p><div className="lpdh-summary-cards"><div><span>Total bahan</span><strong>{money(preview?.rawTotal)}</strong></div><div><span>Total operasional</span><strong>{money(preview?.operationalTotal)}</strong></div><div><span>Insentif</span><strong>{money(preview?.incentiveCalculated)}</strong></div></div><div className="lpdh-signers">{signers.slice(0,3).map((s,i)=><div key={i}><span>{["Pengawas Keuangan SPPG","Kepala SPPG","Perwakilan Mitra/Yayasan"][i]}</span><strong>{s.name||"Belum diisi"}</strong><small>{s.identityType||""} {s.identityNumber||""}</small><Status ok={yes(s.signed)}>{yes(s.signed)?"Ditandatangani":"Belum tanda tangan"}</Status></div>)}</div></div></div>;
}

function Ref({ preview, referenceRows }) {
  const p=preview?.parameters||{};
  const main=[["Tarif Insentif",p.incentiveTariff],["Pagu bahan kecil",p.rawSmall],["Pagu bahan besar",p.rawLarge],["Pagu operasional/PM",p.operationalPerPm],["Maksimum VA",p.maxVa],["Maks HPE",p.maxHpePerWeek],["Jam upload",p.uploadHour],["Toleransi tanggal",p.dateTolerance],["Indeks kemahalan",p.cityIndex],["Sumber indeks",p.cityIndexSource]];
  return <div className="lpdh-sheet-body"><h3>Ref</h3><Table headers={["Parameter","Nilai"]} rows={main}/>{referenceRows?.length>0&&<><h4>Referensi workbook resmi</h4><Table headers={["A","B","C","D"]} rows={referenceRows.slice(0,214).map(r=>r.map(v=>v==null?"":String(v)))}/></>}</div>;
}

export default function LpdhSheets({ activeSheet, masters, daily, preview, serviceDate, referenceRows }) {
  switch(activeSheet){
    case "Petunjuk": return <Petunjuk/>;
    case "Identitas": return <Identity masters={masters} daily={daily} serviceDate={serviceDate}/>;
    case "A_PM": return <APM preview={preview}/>;
    case "B_BahanBaku": return <Raw preview={preview}/>;
    case "C_Operasional": return <Operational preview={preview}/>;
    case "C1_Relawan": return <Volunteer preview={preview}/>;
    case "D_Insentif": return <Incentive preview={preview} daily={daily}/>;
    case "E_Saldo": return <Balance preview={preview} daily={daily}/>;
    case "F_TopUp": return <Topup preview={preview}/>;
    case "G_CekPPK": return <Checks preview={preview}/>;
    case "H_RekapPPK": return <Rekap preview={preview} masters={masters} daily={daily} serviceDate={serviceDate}/>;
    case "I_RegisterBukti": return <Register preview={preview}/>;
    case "J_Pengesahan": return <Approval preview={preview} masters={masters} serviceDate={serviceDate}/>;
    case "Ref": return <Ref preview={preview} referenceRows={referenceRows}/>;
    default: return null;
  }
}
