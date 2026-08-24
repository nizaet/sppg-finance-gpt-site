import deliveryConfig from "./vite.delivery.config.js";

function mustReplace(code, from, to, label) {
  if (!code.includes(from)) throw new Error("[flowviews2] anchor missing: " + label);
  return code.replace(from, to);
}

function plugin() {
  return {
    name: "sppg-flow-calendar-and-filters-v2",
    enforce: "post",
    transform(code, id) {
      if (id.includes("/src/operations/OperationsAccountantBgn.jsx")) {
        let out = code;
        out = mustReplace(
          out,
          'const money = (v) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(v || 0));',
          'const money = (v) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(v || 0));\nconst dateOnly = (v) => { const s=String(v||""); return /^\\d{4}-\\d{2}-\\d{2}/.test(s) ? s.slice(0,10) : ""; };\nconst groupByDate = (rows,getDate)=>rows.reduce((acc,row)=>{const d=getDate(row)||"Tanpa tanggal";(acc[d] ||= []).push(row);return acc;},{});',
          "accountant helpers"
        );
        out = mustReplace(
          out,
          '  const [customFilename,setCustomFilename]=useState("");',
          '  const [customFilename,setCustomFilename]=useState("");\n  const [accountantDateFilter,setAccountantDateFilter]=useState("");\n  const [accountantView,setAccountantView]=useState("list");\n  const [bgnDateFilter,setBgnDateFilter]=useState("");\n  const [bgnView,setBgnView]=useState("list");',
          "accountant states"
        );
        out = mustReplace(
          out,
          '  const excelArgs = () => ({ site: excelSite, distributionDate: excelDate, calculatorDocumentId: selectedPlanId, customFilename });',
          '  const accountantDateOf = (x) => dateOnly(x.source_distribution_date || x.sent_at || x.submission_updated_at);\n  const bgnDateOf = (x) => dateOnly(x.payment_received_at || x.approved_at || x.maker_created_at);\n  const filteredAccountant = useMemo(() => accountant.filter((x)=>!accountantDateFilter || accountantDateOf(x)===accountantDateFilter), [accountant,accountantDateFilter]);\n  const filteredBgn = useMemo(() => bgn.filter((x)=>!bgnDateFilter || bgnDateOf(x)===bgnDateFilter), [bgn,bgnDateFilter]);\n  const accountantCalendar = useMemo(() => groupByDate(filteredAccountant, accountantDateOf), [filteredAccountant]);\n  const bgnCalendar = useMemo(() => groupByDate(filteredBgn, bgnDateOf), [filteredBgn]);\n  const excelArgs = () => ({ site: excelSite, distributionDate: excelDate, calculatorDocumentId: selectedPlanId, customFilename });',
          "accountant filters"
        );

        out = mustReplace(
          out,
          '<div className="ops-inline-controls"><select value={site}',
          '<div className="ops-inline-controls"><input type="date" value={accountantDateFilter} onChange={e=>setAccountantDateFilter(e.target.value)} title="Filter tanggal"/><button type="button" onClick={()=>setAccountantDateFilter("")}>Semua tanggal</button><button type="button" onClick={()=>setAccountantView(accountantView==="calendar"?"list":"calendar")}>{accountantView==="calendar"?"Mode List":"Mode Kalender"}</button><select value={site}',
          "accountant controls"
        );

        const accTable = '<div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Site</th><th>Perencanaan</th><th>Akuntan</th><th>Excel</th><th>Status</th><th>Invoice</th><th>File Invoice</th><th>Maker</th><th>Aksi</th></tr></thead><tbody>{accountant.map(x=>{';
        const accCalendar = '{accountantView==="calendar"&&<div style={{display:"grid",gap:12,marginBottom:14}}>{Object.entries(accountantCalendar).sort((a,b)=>String(b[0]).localeCompare(String(a[0]))).map(([d,rows])=><div key={d} style={{border:"1px solid #d8e1ec",borderRadius:12,padding:12}}><div style={{fontWeight:800,marginBottom:8}}>{d} · {rows.length} alur</div><div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(260px,1fr))",gap:8}}>{rows.map(x=>{const mk=x.invoice_id!=null?makerByInvoice.get(String(x.invoice_id)):null;return <div key={x.submission_id} style={{padding:10,borderRadius:10,border:"1px solid #d8e1ec",background:mk?"#dcfce7":"#fff"}}><strong>{x.site} · {planningLabel(x)}</strong><div className="ops-muted">{x.accountant_code} · {x.submission_status}</div><div>{x.invoice_number||"Belum invoice"}{x.invoice_amount?(" · "+money(x.invoice_amount)):""}</div><div style={{fontWeight:700,color:mk?"#166534":"#64748b"}}>{mk?("✓ Maker #"+mk.maker_id):"Belum Maker"}</div></div>})}</div></div>)}</div>}<div className="ops-table-wrap" style={{display:accountantView==="calendar"?"none":undefined}}><table className="ops-table"><thead><tr><th>Site</th><th>Perencanaan</th><th>Akuntan</th><th>Excel</th><th>Status</th><th>Invoice</th><th>File Invoice</th><th>Maker</th><th>Aksi</th></tr></thead><tbody>{filteredAccountant.map(x=>{';
        out = mustReplace(out, accTable, accCalendar, "accountant table");
        out = mustReplace(
          out,
          'return <tr key={`${x.submission_id}-${x.invoice_id||0}`}><td>{x.site}</td>',
          'return <tr key={`${x.submission_id}-${x.invoice_id||0}`} style={existingMaker?{background:"#dcfce7"}:undefined}><td>{x.site}</td>',
          "accountant green"
        );

        out = mustReplace(
          out,
          '<div className="ops-module-header"><div><span className="ops-kicker">BGN</span><h3>Maker → Approval → Paid</h3>',
          '<div className="ops-module-header"><div><span className="ops-kicker">BGN</span><h3>Maker → Approval → Paid</h3>',
          "bgn section"
        );
        const bgnActions = '<div className="ops-row-actions"><button type="button" onClick={async()=>{await copyText(pendingApprovalMessage(bgn));';
        out = mustReplace(
          out,
          bgnActions,
          '<div className="ops-row-actions"><input type="date" value={bgnDateFilter} onChange={e=>setBgnDateFilter(e.target.value)} title="Filter tanggal Maker"/><button type="button" onClick={()=>setBgnDateFilter("")}>Semua tanggal</button><button type="button" onClick={()=>setBgnView(bgnView==="calendar"?"list":"calendar")}>{bgnView==="calendar"?"Mode List":"Mode Kalender"}</button><button type="button" onClick={async()=>{await copyText(pendingApprovalMessage(filteredBgn));',
          "bgn controls"
        );
        out = out.replace('encodeURIComponent(pendingApprovalMessage(bgn))', 'encodeURIComponent(pendingApprovalMessage(filteredBgn))');

        const bgnTable = '<div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Site</th><th>Maker</th><th>Invoice</th><th>Referensi</th><th>Nilai</th><th>Maker Status</th><th>Approver</th><th>Approval</th><th>Approved</th><th>Pembayaran</th><th>Bukti</th><th>Aksi</th></tr></thead><tbody>{bgn.map(x=>{';
        const bgnCalendar = '{bgnView==="calendar"&&<div style={{display:"grid",gap:12,marginBottom:14}}>{Object.entries(bgnCalendar).sort((a,b)=>String(b[0]).localeCompare(String(a[0]))).map(([d,rows])=><div key={d} style={{border:"1px solid #d8e1ec",borderRadius:12,padding:12}}><div style={{fontWeight:800,marginBottom:8}}>{d} · {rows.length} maker</div><div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(250px,1fr))",gap:8}}>{rows.map(x=>{const approved=String(x.approval_status||"").toUpperCase()==="APPROVED";const paid=Boolean(x.receipt_id)||String(x.maker_status||"").toUpperCase()==="PAID";return <div key={x.maker_id} style={{padding:10,borderRadius:10,border:"1px solid #d8e1ec",background:paid?"#dcfce7":approved?"#ecfdf5":"#fff7ed"}}><strong>{x.site} · Maker #{x.maker_id}</strong><div>{x.reference_number||"-"}</div><div>{money(x.maker_amount)}</div><div style={{fontWeight:800}}>{paid?"✓ PAID":approved?"✓ APPROVED":"PENDING"}</div></div>})}</div></div>)}</div>}<div className="ops-table-wrap" style={{display:bgnView==="calendar"?"none":undefined}}><table className="ops-table"><thead><tr><th>Site</th><th>Maker</th><th>Invoice</th><th>Referensi</th><th>Nilai</th><th>Maker Status</th><th>Approver</th><th>Approval</th><th>Approved</th><th>Pembayaran</th><th>Bukti</th><th>Aksi</th></tr></thead><tbody>{filteredBgn.map(x=>{';
        out = mustReplace(out, bgnTable, bgnCalendar, "bgn table");
        out = mustReplace(
          out,
          'return <tr key={x.maker_id}><td>{x.site}</td>',
          'return <tr key={x.maker_id} style={paid?{background:"#dcfce7"}:approved?{background:"#ecfdf5"}:undefined}><td>{x.site}</td>',
          "bgn color"
        );
        return { code: out, map: null };
      }

      if (id.includes("/src/operations/OperationsPayments.jsx")) {
        let out = code;
        out = mustReplace(
          out,
          'const VENDORS = ["HOLIL", "WIKIAN", "HAJI_BADRI", "RUMAH_DUTA_PANGAN", "HERU", "DEDE", "KOPERASI"];',
          'const VENDORS = ["HOLIL", "WIKIAN", "HAJI_BADRI", "RUMAH_DUTA_PANGAN", "HERU", "DEDE", "KOPERASI"];\nconst dateOnly = (v) => { const s=String(v||""); return /^\\d{4}-\\d{2}-\\d{2}/.test(s) ? s.slice(0,10) : ""; };\nconst groupByDate = (rows,getDate)=>rows.reduce((acc,row)=>{const d=getDate(row)||"Tanpa tanggal";(acc[d] ||= []).push(row);return acc;},{});',
          "payment helpers"
        );
        out = mustReplace(
          out,
          '  const [savingPayment, setSavingPayment] = useState(false);',
          '  const [savingPayment, setSavingPayment] = useState(false);\n  const [payableDateFilter,setPayableDateFilter]=useState("");\n  const [payableView,setPayableView]=useState("list");',
          "payment state"
        );
        out = mustReplace(
          out,
          '  const outstandingTotal = useMemo(',
          '  const payableDateOf = (x) => dateOnly(x.distribution_date || x.invoice_date || x.created_at);\n  const filteredOutstanding = useMemo(() => outstanding.filter((x)=>!payableDateFilter || payableDateOf(x)===payableDateFilter), [outstanding,payableDateFilter]);\n  const payableCalendar = useMemo(() => groupByDate(filteredOutstanding,payableDateOf), [filteredOutstanding]);\n  const outstandingTotal = useMemo(',
          "payment filters"
        );
        out = out.replace('() => outstanding.reduce((sum, x) => sum + Number(x.net_amount || 0), 0),\n    [outstanding]', '() => filteredOutstanding.reduce((sum, x) => sum + Number(x.net_amount || 0), 0),\n    [filteredOutstanding]');

        out = mustReplace(
          out,
          '<select value={activeSite} disabled={Boolean(fixedSite)} onChange={(e) => setSite(e.target.value)}><option value="">Semua site</option>',
          '<input type="date" value={payableDateFilter} onChange={(e)=>setPayableDateFilter(e.target.value)} title="Filter tanggal invoice/payable"/><button type="button" onClick={()=>setPayableDateFilter("")}>Semua tanggal</button><button type="button" onClick={()=>setPayableView(payableView==="calendar"?"list":"calendar")}>{payableView==="calendar"?"Mode List":"Mode Kalender"}</button><select value={activeSite} disabled={Boolean(fixedSite)} onChange={(e) => setSite(e.target.value)}><option value="">Semua site</option>',
          "payment controls"
        );
        out = mustReplace(out, '<span>Outstanding <strong>{outstanding.length}</strong></span>', '<span>Outstanding <strong>{filteredOutstanding.length}</strong></span>', "payment count");

        const summary = '<span>Total netto <strong>{money(outstandingTotal)}</strong></span>\n        </div>';
        const calendar = '<span>Total netto <strong>{money(outstandingTotal)}</strong></span>\n        </div>\n        {payableView==="calendar"&&<div style={{display:"grid",gap:12,marginBottom:14}}>{Object.entries(payableCalendar).sort((a,b)=>String(b[0]).localeCompare(String(a[0]))).map(([d,rows])=><div key={d} style={{border:"1px solid #d8e1ec",borderRadius:12,padding:12}}><div style={{fontWeight:800,marginBottom:8}}>{d} · {rows.length} tagihan</div><div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(250px,1fr))",gap:8}}>{rows.map(item=><div key={item.vendor_invoice_id} style={{padding:10,borderRadius:10,border:"1px solid #d8e1ec",background:"#fff7ed"}}><strong>{item.vendor_code} · {item.site||"-"}</strong><div>{item.po_code||item.invoice_number||("#"+item.vendor_invoice_id)}</div><div style={{fontWeight:800}}>{money(item.net_amount)}</div><div>{item.payable_status||"UNPAID"}</div></div>)}</div></div>)}</div>}';
        out = mustReplace(out, summary, calendar, "payment calendar");
        out = mustReplace(
          out,
          '<div className="ops-table-wrap">\n          <table className="ops-table">\n            <thead><tr><th>Vendor</th><th>Site</th><th>PO</th><th>Invoice</th><th>Distribusi</th><th>Bruto</th><th>Reject</th><th>Netto</th><th>Jatuh Tempo</th><th>Status</th></tr></thead>',
          '<div className="ops-table-wrap" style={{display:payableView==="calendar"?"none":undefined}}>\n          <table className="ops-table">\n            <thead><tr><th>Vendor</th><th>Site</th><th>PO</th><th>Invoice</th><th>Distribusi</th><th>Bruto</th><th>Reject</th><th>Netto</th><th>Jatuh Tempo</th><th>Status</th></tr></thead>',
          "payment table display"
        );
        const lastOutstandingMap = out.lastIndexOf('{outstanding.map((item) => (');
        if (lastOutstandingMap < 0) throw new Error('[flowviews2] anchor missing: payment list map');
        out = out.slice(0,lastOutstandingMap) + '{filteredOutstanding.map((item) => (' + out.slice(lastOutstandingMap + '{outstanding.map((item) => ('.length);
        out = out.replace('{!loading && outstanding.length === 0 && <tr><td colSpan="10"', '{!loading && filteredOutstanding.length === 0 && <tr><td colSpan="10"');
        return { code: out, map: null };
      }
      return null;
    },
  };
}

export default {
  ...deliveryConfig,
  plugins: [...(deliveryConfig.plugins || []), plugin()],
};
