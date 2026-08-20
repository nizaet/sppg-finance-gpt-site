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
        const accMonthly = '{accountantView==="calendar"&&<div style={{marginBottom:14}}><div className="ops-row-actions" style={{justifyContent:"space-between",marginBottom:10}}><button type="button" onClick={()=>setAccountantMonth(shiftMonth(accountantMonth,-1))}>‹ Bulan lalu</button><strong style={{fontSize:18,textTransform:"capitalize"}}>{monthTitle(accountantMonth)}</strong><button type="button" onClick={()=>setAccountantMonth(shiftMonth(accountantMonth,1))}>Bulan berikut ›</button></div><div style={{display:"grid",gridTemplateColumns:"repeat(7,minmax(0,1fr))",gap:6,marginBottom:6}}>{["Sen","Sel","Rab","Kam","Jum","Sab","Min"].map(x=><div key={x} style={{fontWeight:800,textAlign:"center",padding:6}}>{x}</div>)}</div><div style={{display:"grid",gridTemplateColumns:"repeat(7,minmax(0,1fr))",gap:6}}>{monthCells(accountantMonth).map((d,i)=>{const rows=d?accountant.filter(x=>accountantDateOf(x)===d):[];const isToday=d===new Date().toLocaleDateString("en-CA");return <div key={d||("blank-"+i)} style={{minHeight:118,border:"1px solid #d8e1ec",borderRadius:10,padding:7,background:d?(isToday?"#eff6ff":"#fff"):"transparent",opacity:d?1:.35}}>{d&&<><div style={{fontWeight:800,marginBottom:6}}>{Number(d.slice(-2))}</div>{rows.map(x=>{const mk=x.invoice_id!=null?makerByInvoice.get(String(x.invoice_id)):null;return <div key={x.submission_id} style={{padding:6,borderRadius:7,border:"1px solid #d8e1ec",background:mk?"#dcfce7":"#fff7ed",marginBottom:5,fontSize:12}}><strong>{x.site} · {x.accountant_code}</strong><div>{x.invoice_number||"Belum invoice"}</div><div style={{fontWeight:700}}>{mk?("✓ Maker #"+mk.maker_id):"Belum Maker"}</div></div>})}</>}</div>})}</div></div>}';
        out = replaceBlock(out, accStart, accEnd, accMonthly, accEnd);

        const bgnStart = '{bgnView==="calendar"&&<div style={{display:"grid",gap:12,marginBottom:14}}>';
        const bgnEnd = '<div className="ops-table-wrap" style={{display:bgnView==="calendar"?"none":undefined}}>';
        const bgnMonthly = '{bgnView==="calendar"&&<div style={{marginBottom:14}}><div className="ops-row-actions" style={{justifyContent:"space-between",marginBottom:10}}><button type="button" onClick={()=>setBgnMonth(shiftMonth(bgnMonth,-1))}>‹ Bulan lalu</button><strong style={{fontSize:18,textTransform:"capitalize"}}>{monthTitle(bgnMonth)}</strong><button type="button" onClick={()=>setBgnMonth(shiftMonth(bgnMonth,1))}>Bulan berikut ›</button></div><div style={{display:"grid",gridTemplateColumns:"repeat(7,minmax(0,1fr))",gap:6,marginBottom:6}}>{["Sen","Sel","Rab","Kam","Jum","Sab","Min"].map(x=><div key={x} style={{fontWeight:800,textAlign:"center",padding:6}}>{x}</div>)}</div><div style={{display:"grid",gridTemplateColumns:"repeat(7,minmax(0,1fr))",gap:6}}>{monthCells(bgnMonth).map((d,i)=>{const rows=d?bgn.filter(x=>bgnDateOf(x)===d):[];const isToday=d===new Date().toLocaleDateString("en-CA");return <div key={d||("blank-"+i)} style={{minHeight:118,border:"1px solid #d8e1ec",borderRadius:10,padding:7,background:d?(isToday?"#eff6ff":"#fff"):"transparent",opacity:d?1:.35}}>{d&&<><div style={{fontWeight:800,marginBottom:6}}>{Number(d.slice(-2))}</div>{rows.map(x=>{const approved=String(x.approval_status||"").toUpperCase()==="APPROVED";const paid=Boolean(x.receipt_id)||String(x.maker_status||"").toUpperCase()==="PAID";return <div key={x.maker_id} style={{padding:6,borderRadius:7,border:"1px solid #d8e1ec",background:paid?"#dcfce7":approved?"#ecfdf5":"#fff7ed",marginBottom:5,fontSize:12}}><strong>{x.site} · Maker #{x.maker_id}</strong><div>{money(x.maker_amount)}</div><div style={{fontWeight:800}}>{paid?"✓ PAID":approved?"✓ APPROVED":"PENDING"}</div></div>})}</>}</div>})}</div></div>}';
        out = replaceBlock(out, bgnStart, bgnEnd, bgnMonthly, bgnEnd);
      }

      if (id.includes("/src/operations/OperationsPayments.jsx")) {
        if (out.includes('const [payableView,setPayableView]=useState("list");') && !out.includes("payableMonth,setPayableMonth")) {
          out = out.replace(
            'const [payableView,setPayableView]=useState("list");',
            'const [payableView,setPayableView]=useState("list");\n  const initialPayableMonth=()=>{const d=new Date();return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0");};\n  const [payableMonth,setPayableMonth]=useState(initialPayableMonth);\n  const shiftPayableMonth=(value,delta)=>{const p=String(value||initialPayableMonth()).split("-");const d=new Date(Number(p[0]),Number(p[1])-1+delta,1);return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0");};\n  const payableMonthTitle=(value)=>{const p=String(value).split("-");return new Intl.DateTimeFormat("id-ID",{month:"long",year:"numeric"}).format(new Date(Number(p[0]),Number(p[1])-1,1));};\n  const payableMonthCells=(value)=>{const p=String(value).split("-");const y=Number(p[0]),m=Number(p[1])-1;const first=new Date(y,m,1);const days=new Date(y,m+1,0).getDate();const mondayOffset=(first.getDay()+6)%7;const cells=Array(mondayOffset).fill(null);for(let day=1;day<=days;day++){cells.push(y+"-"+String(m+1).padStart(2,"0")+"-"+String(day).padStart(2,"0"));}while(cells.length%7)cells.push(null);return cells;};'
          );
        }
        const payStart = '{payableView==="calendar"&&<div style={{display:"grid",gap:12,marginBottom:14}}>';
        const payEnd = '<div className="ops-table-wrap" style={{display:payableView==="calendar"?"none":undefined}}>';
        const payMonthly = '{payableView==="calendar"&&<div style={{marginBottom:14}}><div className="ops-row-actions" style={{justifyContent:"space-between",marginBottom:10}}><button type="button" onClick={()=>setPayableMonth(shiftPayableMonth(payableMonth,-1))}>‹ Bulan lalu</button><strong style={{fontSize:18,textTransform:"capitalize"}}>{payableMonthTitle(payableMonth)}</strong><button type="button" onClick={()=>setPayableMonth(shiftPayableMonth(payableMonth,1))}>Bulan berikut ›</button></div><div style={{display:"grid",gridTemplateColumns:"repeat(7,minmax(0,1fr))",gap:6,marginBottom:6}}>{["Sen","Sel","Rab","Kam","Jum","Sab","Min"].map(x=><div key={x} style={{fontWeight:800,textAlign:"center",padding:6}}>{x}</div>)}</div><div style={{display:"grid",gridTemplateColumns:"repeat(7,minmax(0,1fr))",gap:6}}>{payableMonthCells(payableMonth).map((d,i)=>{const rows=d?outstanding.filter(x=>payableDateOf(x)===d):[];const isToday=d===new Date().toLocaleDateString("en-CA");return <div key={d||("blank-"+i)} style={{minHeight:118,border:"1px solid #d8e1ec",borderRadius:10,padding:7,background:d?(isToday?"#eff6ff":"#fff"):"transparent",opacity:d?1:.35}}>{d&&<><div style={{fontWeight:800,marginBottom:6}}>{Number(d.slice(-2))}</div>{rows.map(item=><div key={item.vendor_invoice_id} style={{padding:6,borderRadius:7,border:"1px solid #d8e1ec",background:String(item.payable_status||"").toUpperCase()==="PAID"?"#dcfce7":"#fff7ed",marginBottom:5,fontSize:12}}><strong>{item.vendor_code} · {item.site||"-"}</strong><div>{item.invoice_number||item.po_code||("#"+item.vendor_invoice_id)}</div><div style={{fontWeight:800}}>{money(item.net_amount)}</div><div>{item.payable_status||"UNPAID"}</div></div>)}</>}</div>})}</div></div>}';
        out = replaceBlock(out, payStart, payEnd, payMonthly, payEnd);
      }

      return out === code ? null : { code: out, map: null };
    },
  };
}

export default {
  ...flowConfig,
  plugins: [...basePlugins, monthlyCalendarPlugin()],
};
