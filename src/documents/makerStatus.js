export function documentMakerStatus(doc) {
  if(doc.status!=='FINAL'||!doc.makerId)return {className:'',label:''};
  const maker=String(doc.makerStatus||'').toUpperCase();
  const approval=String(doc.makerApprovalStatus||'').toUpperCase();
  if(doc.makerPaid||maker==='PAID')return {className:'doc-maker-approved',label:'Sudah diapprove · PAID'};
  if(['CANCELLED','REJECTED'].includes(maker))return {className:'',label:maker==='CANCELLED'?'Maker dibatalkan':'Maker ditolak'};
  if(approval==='APPROVED')return {className:'doc-maker-approved',label:'Sudah diapprove'};
  return {className:'doc-maker-pending',label:approval==='REJECTED'?'Sudah di Maker · Approval ditolak':'Sudah di Maker'};
}
