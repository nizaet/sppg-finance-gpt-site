import flowConfig from "./vite.flowviews2.config.js";

const basePlugins = (flowConfig.plugins || []).map((plugin) => {
  if (plugin?.name === "sppg-flow-calendar-and-filters-v2") {
    return { ...plugin, enforce: "pre" };
  }
  return plugin;
});

function replaceBlock(code, start, end, replacement) {
  const a = code.indexOf(start);
  if (a < 0) return code;
  const b = code.indexOf(end, a + start.length);
  if (b < 0) return code;
  return code.slice(0, a) + replacement + code.slice(b);
}

function replaceAfter(code, marker, from, to) {
  const markerPos = code.indexOf(marker);
  if (markerPos < 0) return code;
  const fromPos = code.indexOf(from, markerPos);
  if (fromPos < 0) return code;
  return code.slice(0, fromPos) + to + code.slice(fromPos + from.length);
}

function monthlyCalendarPlugin() {
  return {
    name: "sppg-monthly-flow-calendars",
    enforce: "pre",
    transform(code, id) {
      let out = code;

      if (id.includes("/src/operations/OperationsAccountantBgn.jsx")) {
        if (out.includes('const [bgnView,setBgnView]=useState("list");') && !out.includes("accountantMonth,setAccountantMonth")) {
          out = out.replace(
            'const [bgnView,setBgnView]=useState("list");',
            'const [bgnView,setBgnView]=useState("list");\n  const initialMonth=()=>{const d=new Date();return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0");};\n  const [accountantMonth,setAccountantMonth]=useState(initialMonth);\n  const [bgnMonth,setBgnMonth]=useState(initialMonth);\n  const shiftMonth=(value,delta)=>{const p=String(value||initialMonth()).split("-");const d=new Date(Number(p[0]),Number(p[1])-1+delta,1);return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0");};\n  const monthTitle=(value)=>{const p=String(value).split("-");return new Intl.DateTimeFormat("id-ID",{month:"long",year:"numeric"}).format(new Date(Number(p[0]),Number(p[1])-1,1));};\n  const monthCells=(value)=>{const p=String(value).split("-");const y=Number(p[0]),m=Number(p[1])-1;const first=new Date(y,m,1);const days=new Date(y,m+1,0).getDate();const mondayOffset=(first.getDay()+6)%7;const cells=Array(mondayOffset).fill(null);for(let day=1;day<=days;day++){cells.push(y+"-"+String(m+1).padStart(2,"0")+"-"+String(day).padStart(2,"0"));}while(cells.length%7)cells.push(null);return cells;};'
          );
        }

        const accStart = '{accountantView==="calendar"&&<div style={{display:"grid",gap:12,marginBottom:14}}>';
        const accEnd = '<div className="ops-table-wrap" style={{display:accountantView==="calendar"?"none":undefined}}>';
        const accMonthly = '{accountantView==="calendar"&&<div style={{marginBottom:14}}><div className="ops-row-actions" style={{justifyContent:"space-between",marginBottom:10}}><button type="button" onClick={()=>setAccountantMonth(shiftMonth(accountantMonth,-1))}>‹ Bulan lalu</button><strong style={{fontSize:18,textTransform:"capitalize"}}>{monthTitle(accountantMonth)}</strong><button type="button" onClick={()=>setAccountantMonth(shiftMonth(accountantMonth,1))}>Bulan berikut ›</button></div><div style={{display:"grid",gridTemplateColumns:"repeat(7,minmax(0,1fr))",gap:6,marginBottom:6}}>{["Sen","Sel","Rab","Kam","Jum","Sab","Min"].map(x=><div key={x} style={{fontWeight:800,textAlign:"center",padding:6}}>{x}</div>)}</div><div style={{display:"grid",gridTemplateColumns:"repeat(7,minmax(0,1fr))",gap:6}}>{monthCells(accountantMonth).map((d,i)=>{const rows=d?accountant.filter(x=>accountantDateOf(x)===d):[];const isToday=d===new Date().toLocaleDateString("en-CA");return <div key={d||("blank-"+i)} style={{minHeight:118,border:"1px solid #d8e1ec",borderRadius:10,padding:7,background:d?(isToday?"#eff6ff":"#fff"):"transparent",opacity:d?1:.35}}>{d&&<><div style={{fontWeight:800,marginBottom:6}}>{Number(d.slice(-2))}</div>{rows.map(x=>{const mk=x.invoice_id!=null?makerByInvoice.get(String(x.invoice_id)):null;const canMaker=Boolean(x.invoice_id)&&!mk&&Number(x.invoice_amount||0)>0;return <div key={x.submission_id} style={{padding:6,borderRadius:7,border:"1px solid #d8e1ec",background:mk?"#dcfce7":"#fff7ed",marginBottom:5,fontSize:12}}><strong>{x.site} · {x.accountant_code}</strong><div>{x.invoice_number||"Belum invoice"}</div><div style={{fontWeight:700,color:mk?"#166534":"#64748b"}}>{mk?("✓ Maker #"+mk.maker_id):"Belum Maker"}</div>{canMaker&&<button type="button" style={{marginTop:5}} onClick={()=>createMakerAndApproval(x)} disabled={saving===("maker-"+x.invoice_id)}>Buat Maker</button>}</div>})}</>}</div>})}</div></div>}';
        out = replaceBlock(out, accStart, accEnd, accMonthly);

        const bgnStart = '{bgnView==="calendar"&&<div style={{display:"grid",gap:12,marginBottom:14}}>';
        const bgnEnd = '<div className="ops-table-wrap" style={{display:bgnView==="calendar"?"none":undefined}}>';
        const bgnMonthly = '{bgnView==="calendar"&&<div style={{marginBottom:14}}><div className="ops-row-actions" style={{justifyContent:"space-between",marginBottom:10}}><button type="button" onClick={()=>setBgnMonth(shiftMonth(bgnMonth,-1))}>‹ Bulan lalu</button><strong style={{fontSize:18,textTransform:"capitalize"}}>{monthTitle(bgnMonth)}</strong><button type="button" onClick={()=>setBgnMonth(shiftMonth(bgnMonth,1))}>Bulan berikut ›</button></div><div style={{display:"grid",gridTemplateColumns:"repeat(7,minmax(0,1fr))",gap:6,marginBottom:6}}>{["Sen","Sel","Rab","Kam","Jum","Sab","Min"].map(x=><div key={x} style={{fontWeight:800,textAlign:"center",padding:6}}>{x}</div>)}</div><div style={{display:"grid",gridTemplateColumns:"repeat(7,minmax(0,1fr))",gap:6}}>{monthCells(bgnMonth).map((d,i)=>{const rows=d?bgn.filter(x=>bgnDateOf(x)===d):[];const isToday=d===new Date().toLocaleDateString("en-CA");return <div key={d||("blank-"+i)} style={{minHeight:118,border:"1px solid #d8e1ec",borderRadius:10,padding:7,background:d?(isToday?"#eff6ff":"#fff"):"transparent",opacity:d?1:.35}}>{d&&<><div style={{fontWeight:800,marginBottom:6}}>{Number(d.slice(-2))}</div>{rows.map(x=>{const approved=String(x.approval_status||"").toUpperCase()==="APPROVED";const paid=Boolean(x.receipt_id)||String(x.maker_status||"").toUpperCase()==="PAID";return <div key={x.maker_id} style={{padding:6,borderRadius:7,border:"1px solid #d8e1ec",background:paid?"#dcfce7":approved?"#ecfdf5":"#fff7ed",marginBottom:5,fontSize:12}}><strong>{x.site} · Maker #{x.maker_id}</strong><div>{money(x.maker_amount)}</div><div style={{fontWeight:800,color:paid?"#166534":undefined}}>{paid?"✓ PAID":approved?"✓ APPROVED":"PENDING"}</div>{!approved&&<button type="button" style={{marginTop:5}} onClick={()=>approveMaker(x)} disabled={saving===("approve-"+x.maker_id)}>Sudah Approve</button>}{approved&&!paid&&<div style={{marginTop:5}}><input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={e=>setPaymentFiles(current=>({...current,[x.maker_id]:e.target.files?.[0]||null}))}/><button type="button" style={{marginTop:4}} onClick={()=>markMakerPaid(x)} disabled={saving===("paid-"+x.maker_id)||!paymentFiles[x.maker_id]}>PAID</button></div>}</div>})}</>}</div>})}</div></div>}';
        out = replaceBlock(out, bgnStart, bgnEnd, bgnMonthly);
      }

      if (id.includes("/src/operations/OperationsPayments.jsx")) {
        if (out.includes('const [payableView,setPayableView]=useState("list");') && !out.includes("payableMonth,setPayableMonth")) {
          out = out.replace(
            'const [payableView,setPayableView]=useState("list");',
            'const [payableView,setPayableView]=useState("list");\n  const initialPayableMonth=()=>{const d=new Date();return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0");};\n  const [payableMonth,setPayableMonth]=useState(initialPayableMonth);\n  const shiftPayableMonth=(value,delta)=>{const p=String(value||initialPayableMonth()).split("-");const d=new Date(Number(p[0]),Number(p[1])-1+delta,1);return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0");};\n  const payableMonthTitle=(value)=>{const p=String(value).split("-");return new Intl.DateTimeFormat("id-ID",{month:"long",year:"numeric"}).format(new Date(Number(p[0]),Number(p[1])-1,1));};\n  const payableMonthCells=(value)=>{const p=String(value).split("-");const y=Number(p[0]),m=Number(p[1])-1;const first=new Date(y,m,1);const days=new Date(y,m+1,0).getDate();const mondayOffset=(first.getDay()+6)%7;const cells=Array(mondayOffset).fill(null);for(let day=1;day<=days;day++){cells.push(y+"-"+String(m+1).padStart(2,"0")+"-"+String(day).padStart(2,"0"));}while(cells.length%7)cells.push(null);return cells;};'
          );
        }

        if (out.includes('const filteredOutstanding = useMemo(() => outstanding.filter((x)=>!payableDateFilter || payableDateOf(x)===payableDateFilter), [outstanding,payableDateFilter]);') && !out.includes("const filteredPayables = useMemo")) {
          out = out.replace(
            'const filteredOutstanding = useMemo(() => outstanding.filter((x)=>!payableDateFilter || payableDateOf(x)===payableDateFilter), [outstanding,payableDateFilter]);',
            'const filteredOutstanding = useMemo(() => outstanding.filter((x)=>!payableDateFilter || payableDateOf(x)===payableDateFilter), [outstanding,payableDateFilter]);\n  const filteredPayables = useMemo(() => payables.filter((x)=>!payableDateFilter || payableDateOf(x)===payableDateFilter), [payables,payableDateFilter]);'
          );
        }

        const paymentSectionMarker = '<span className="ops-kicker">TRANSFER + BUKTI</span>';
        const paymentSectionOpen = '<section className="ops-module">';
        const paymentMarkerPos = out.indexOf(paymentSectionMarker);
        if (paymentMarkerPos >= 0) {
          const paymentOpenPos = out.lastIndexOf(paymentSectionOpen, paymentMarkerPos);
          if (paymentOpenPos >= 0) out = out.slice(0,paymentOpenPos) + '<section className="ops-module" id="vendor-payment-entry">' + out.slice(paymentOpenPos + paymentSectionOpen.length);
        }

        const payStart = '{payableView==="calendar"&&<div style={{display:"grid",gap:12,marginBottom:14}}>';
        const payEnd = '<div className="ops-table-wrap" style={{display:payableView==="calendar"?"none":undefined}}>';
        const payMonthly = '{payableView==="calendar"&&<div style={{marginBottom:14}}><div className="ops-row-actions" style={{justifyContent:"space-between",marginBottom:10}}><button type="button" onClick={()=>setPayableMonth(shiftPayableMonth(payableMonth,-1))}>‹ Bulan lalu</button><strong style={{fontSize:18,textTransform:"capitalize"}}>{payableMonthTitle(payableMonth)}</strong><button type="button" onClick={()=>setPayableMonth(shiftPayableMonth(payableMonth,1))}>Bulan berikut ›</button></div><div style={{display:"grid",gridTemplateColumns:"repeat(7,minmax(0,1fr))",gap:6,marginBottom:6}}>{["Sen","Sel","Rab","Kam","Jum","Sab","Min"].map(x=><div key={x} style={{fontWeight:800,textAlign:"center",padding:6}}>{x}</div>)}</div><div style={{display:"grid",gridTemplateColumns:"repeat(7,minmax(0,1fr))",gap:6}}>{payableMonthCells(payableMonth).map((d,i)=>{const rows=d?payables.filter(x=>payableDateOf(x)===d):[];const isToday=d===new Date().toLocaleDateString("en-CA");return <div key={d||("blank-"+i)} style={{minHeight:118,border:"1px solid #d8e1ec",borderRadius:10,padding:7,background:d?(isToday?"#eff6ff":"#fff"):"transparent",opacity:d?1:.35}}>{d&&<><div style={{fontWeight:800,marginBottom:6}}>{Number(d.slice(-2))}</div>{rows.map(item=>{const paid=CLOSED.has(String(item.payable_status||"UNPAID").toUpperCase());return <div key={item.vendor_invoice_id} style={{padding:6,borderRadius:7,border:"1px solid #d8e1ec",background:paid?"#dcfce7":"#fff7ed",marginBottom:5,fontSize:12}}><strong>{item.vendor_code} · {item.site||"-"}</strong><div>{item.invoice_number||item.po_code||("#"+item.vendor_invoice_id)}</div><div style={{fontWeight:800}}>{money(item.net_amount)}</div><div style={{fontWeight:800,color:paid?"#166534":undefined}}>{paid?"✓ PAID":(item.payable_status||"UNPAID")}</div>{!paid&&<button type="button" style={{marginTop:5}} onClick={()=>{selectPayable(String(item.vendor_invoice_id));window.setTimeout(()=>document.getElementById("vendor-payment-entry")?.scrollIntoView({behavior:"smooth",block:"start"}),0);}}>Bayar</button>}</div>})}</>}</div>})}</div></div>}';
        out = replaceBlock(out, payStart, payEnd, payMonthly);

        const invoiceMarker = '<span className="ops-kicker">INVOICE / PAYABLE</span>';
        out = replaceAfter(out, invoiceMarker, '<thead><tr><th>Vendor</th><th>Site</th><th>PO</th><th>Invoice</th><th>Distribusi</th><th>Bruto</th><th>Reject</th><th>Netto</th><th>Jatuh Tempo</th><th>Status</th></tr></thead>', '<thead><tr><th>Vendor</th><th>Site</th><th>PO</th><th>Invoice</th><th>Distribusi</th><th>Bruto</th><th>Reject</th><th>Netto</th><th>Jatuh Tempo</th><th>Status</th><th>Aksi</th></tr></thead>');
        out = replaceAfter(out, invoiceMarker, '{filteredOutstanding.map((item) => (', '{filteredPayables.map((item) => (');
        out = replaceAfter(out, invoiceMarker, '<tr key={item.vendor_invoice_id}>', '<tr key={item.vendor_invoice_id} style={CLOSED.has(String(item.payable_status||"UNPAID").toUpperCase())?{background:"#dcfce7"}:undefined}>');
        out = replaceAfter(out, invoiceMarker, '<td>{item.payable_status || "UNPAID"}</td>\n                </tr>', '<td><strong>{CLOSED.has(String(item.payable_status||"UNPAID").toUpperCase())?"✓ PAID":(item.payable_status||"UNPAID")}</strong></td><td>{CLOSED.has(String(item.payable_status||"UNPAID").toUpperCase())?<span style={{color:"#166534",fontWeight:800}}>✓ Selesai</span>:<button type="button" onClick={()=>{selectPayable(String(item.vendor_invoice_id));window.setTimeout(()=>document.getElementById("vendor-payment-entry")?.scrollIntoView({behavior:"smooth",block:"start"}),0);}}>Bayar</button>}</td>\n                </tr>');
        out = replaceAfter(out, invoiceMarker, '{!loading && filteredOutstanding.length === 0 && <tr><td colSpan="10"', '{!loading && filteredPayables.length === 0 && <tr><td colSpan="11"');
      }

      return out === code ? null : { code: out, map: null };
    },
  };
}

export default {
  ...flowConfig,
  plugins: [...basePlugins, monthlyCalendarPlugin()],
};
