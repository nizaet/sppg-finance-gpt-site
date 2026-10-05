const LISTS = ['rawMaterials', 'operations', 'volunteerPayments', 'incentiveRecipients'];
const LABELS = {rawMaterials:'Invoice bahan baku',operations:'Invoice operasional',volunteerPayments:'Kuitansi relawan',incentiveRecipients:'Kuitansi guru/kader'};

export function evidenceGroups(data) {
  return LISTS.flatMap(list => {
    const groups = new Map();
    (data[list] || []).forEach((row,index) => {
      // Legacy individual receipts must not be conflated with aggregate packages.
      const batch = row.sourceDocumentId && (list === 'rawMaterials' || list === 'operations' || row.aggregatePayment);
      const key = batch ? `doc:${row.sourceDocumentId}` : `legacy:${index}`;
      if (!groups.has(key)) groups.set(key,{key:`${list}:${key}`,list,indexes:[],label:LABELS[list],number:row.invoiceNo || row.receiptNo || 'Historis',name:batch?'':row.name || row.description || '',conflictingFields:[]});
      groups.get(key).indexes.push(index);
    });
    return [...groups.values()].map(group => {
      for (const field of ['evidenceLink','paymentReference']) {
        const values = [...new Set(group.indexes.map(i => String(data[list][i][field] ?? '')))];
        group[field] = values.length === 1 ? values[0] : '';
        if (values.length > 1) group.conflictingFields.push(field);
      }
      return group;
    });
  });
}

export function applyEvidence(data, group, field, value) {
  if (!['evidenceLink','paymentReference'].includes(field)) throw new Error('Hanya bukti dan referensi yang dapat diubah');
  const selected = new Set(group.indexes);
  return {...data,[group.list]:(data[group.list] || []).map((row,i)=>selected.has(i)?{...row,[field]:value}:row)};
}
