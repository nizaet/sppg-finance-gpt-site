import flowConfig from "./vite.flowviews3.config.js";

function workflowStateHardeningPlugin() {
  return {
    name: "sppg-workflow-state-hardening-v4",
    enforce: "post",
    transform(code, id) {
      let out = code;

      if (id.includes("/src/operations/OperationsAccountantBgn.jsx")) {
        out = out.replace(
          'if (makerByInvoice.has(String(row.invoice_id))) return setError("Maker untuk invoice ini sudah ada.");',
          'if (row.maker_id || makerByInvoice.has(String(row.invoice_id))) return setError("Maker untuk invoice ini sudah ada.");'
        );
        out = out.replace(
          '<tr key={`${x.submission_id}-${x.invoice_id||0}`}>',
          '<tr key={`${x.submission_id}-${x.invoice_id||0}`} style={existingMaker?{background:"#dcfce7"}:undefined}>'
        );
        out = out.replace(
          '<td>{existingMaker?`#${existingMaker.maker_id}`:"-"}</td>',
          '<td>{existingMaker?<strong style={{color:"#166534"}}>✓ Maker #{existingMaker.maker_id}</strong>:"-"}</td>'
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
  plugins: [...(flowConfig.plugins || []), workflowStateHardeningPlugin()],
};
