// Placeholder evidence supports draft estimates only, never authentic FINAL proof.
export function defaultBastRows(rows,serviceDate,historical=false){
 if(historical||!/^\d{4}-\d{2}-\d{2}$/.test(serviceDate||''))return rows;
 return rows.map(row=>{const next={...row},code=String(row.code||row.groupCode||'');
  const no=String(row.bastNo||'').trim(),link=String(row.bastLink||'').trim();
  if(!no||no.startsWith('DRAFT-WAJIB-DIGANTI/'))next.bastNo=`DRAFT-WAJIB-DIGANTI/${serviceDate}/${code}`;
  if(!link||link.startsWith('https://example.invalid/BAST-DRAFT-WAJIB-DIGANTI/'))next.bastLink=`https://example.invalid/BAST-DRAFT-WAJIB-DIGANTI/${serviceDate}/${code}`;
  return next;
 });
}

