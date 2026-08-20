import flowConfig from "./vite.flowviews3.config.js";

const legacyMakerExpr = '(x.maker_id?{maker_id:x.maker_id,maker_status:x.maker_status}:(x.invoice_id!=null?makerByInvoice.get(String(x.invoice_id)):null))||(()=>{const same=bgn.filter((m)=>String(m.site||"").toUpperCase()===String(x.site||"").toUpperCase()&&Math.abs(Number(m.maker_amount||0)-Number(x.invoice_amount||0))<0.01);if(same.length===1)return same[0];const ref=String(x.invoice_number||"").trim().toLowerCase();const legacy=String("AKUNTAN-INV-"+(x.invoice_id||"")).toLowerCase();const narrowed=same.filter((m)=>{const mr=String(m.reference_number||"").trim().toLowerCase();return mr===ref||mr===legacy;});return narrowed.length===1?narrowed[0]:null;})()';

function makerStatePrePlugin() {
  return {
    name: "sppg-maker-state-pre-v6",
    enforce: "pre",
    transform(code, id) {
      if (!id.includes("/src/operations/OperationsAccountantBgn.jsx")) return null;
      let out = code;

      out = out.replace(
        'if (makerByInvoice.has(String(row.invoice_id))) return setError("Maker untuk invoice ini sudah ada.");',
        'const legacyMakerMatches=bgn.filter((m)=>String(m.site||"").toUpperCase()===String(row.site||"").toUpperCase()&&Math.abs(Number(m.maker_amount||0)-Number(row.invoice_amount||0))<0.01); if (row.maker_id || makerByInvoice.has(String(row.invoice_id)) || legacyMakerMatches.length===1) return setError("Maker untuk invoice ini sudah ada.");'
      );

      out = out.replace(
        'const existingMaker = x.invoice_id != null ? makerByInvoice.get(String(x.invoice_id)) : null;',
        `const existingMaker = ${legacyMakerExpr};`
      );

      if (!out.includes("const cancelMakerApproval = async")) {
        out = out.replace(
          'const markMakerPaid = async (row) => {',
          'const cancelMakerApproval = async (row) => {\n    if (String(row.approval_status||"").toUpperCase()!=="APPROVED") return;\n    if (Boolean(row.receipt_id)||String(row.maker_status||"").toUpperCase()==="PAID") return setError("Approval tidak bisa dibatalkan karena Maker sudah PAID.");\n    if (!window.confirm(`Batalkan status APPROVED Maker #${row.maker_id}? Maker akan kembali ke PENDING.`)) return;\n    setSaving(`cancel-approve-${row.maker_id}`); setError("");\n    try { await accountantApi.cancelMakerApproval(row.maker_id); setMessage(`Approval Maker #${row.maker_id} dibatalkan dan kembali PENDING.`); await load(); }\n    catch (e) { setError(e.message || "Gagal membatalkan approval Maker"); }\n    finally { setSaving(""); }\n  };\n\n  const markMakerPaid = async (row) => {'
        );
      }

      out = out.replace(
        '{approved&&!paid&&<button type="button" onClick={()=>markMakerPaid(x)} disabled={saving===`paid-${x.maker_id}`||!paymentFiles[x.maker_id]}><WalletCards size={14}/> PAID</button>}',
        '{approved&&!paid&&<><button type="button" className="danger" onClick={()=>cancelMakerApproval(x)} disabled={saving===`cancel-approve-${x.maker_id}`}><Trash2 size={14}/> Batal Approve</button><button type="button" onClick={()=>markMakerPaid(x)} disabled={saving===`paid-${x.maker_id}`||!paymentFiles[x.maker_id]}><WalletCards size={14}/> PAID</button></>}'
      );

      return out === code ? null : { code: out, map: null };
    },
  };
}

function makerStatePostPlugin() {
  return {
    name: "sppg-maker-state-post-v6",
    enforce: "post",
    transform(code, id) {
      let out = code;
      if (id.includes("/src/operations/OperationsAccountantBgn.jsx")) {
        out = out.replace(
          '<td>{existingMaker?`#${existingMaker.maker_id}`:"-"}</td>',
          '<td>{existingMaker?<strong style={{color:"#166534"}}>✓ Maker #{existingMaker.maker_id}</strong>:"-"}</td>'
        );
        out = out.replace(
          'const mk=x.maker_id?{maker_id:x.maker_id,maker_status:x.maker_status}:(x.invoice_id!=null?makerByInvoice.get(String(x.invoice_id)):null);',
          `const mk=${legacyMakerExpr};`
        );
        out = out.replace(
          '{approved&&!paid&&<div style={{marginTop:5}}><input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={e=>setPaymentFiles(current=>({...current,[x.maker_id]:e.target.files?.[0]||null}))}/><button type="button" style={{marginTop:4}} onClick={()=>markMakerPaid(x)} disabled={saving===("paid-"+x.maker_id)||!paymentFiles[x.maker_id]}>PAID</button></div>}',
          '{approved&&!paid&&<div style={{marginTop:5}}><button type="button" style={{marginBottom:4}} onClick={()=>cancelMakerApproval(x)} disabled={saving===("cancel-approve-"+x.maker_id)}>Batal Approve</button><input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={e=>setPaymentFiles(current=>({...current,[x.maker_id]:e.target.files?.[0]||null}))}/><button type="button" style={{marginTop:4}} onClick={()=>markMakerPaid(x)} disabled={saving===("paid-"+x.maker_id)||!paymentFiles[x.maker_id]}>PAID</button></div>}'
        );
      }
      if (id.includes("/src/operations/OperationsPayments.jsx")) {
        const oldJump = 'onClick={()=>{selectPayable(String(item.vendor_invoice_id));window.setTimeout(()=>document.getElementById("vendor-payment-entry")?.scrollIntoView({behavior:"smooth",block:"start"}),0);}}';
        out = out.split(oldJump).join('onClick={()=>setPaymentModalItem(item)}');
      }
      return out === code ? null : { code: out, map: null };
    },
  };
}

export default {
  ...flowConfig,
  plugins: [makerStatePrePlugin(), ...(flowConfig.plugins || []), makerStatePostPlugin()],
};
