// Read-only summary of saved invoice lines; never recalculate historical rates.
export function volunteerRecap(documents, period) {
  const groups = new Map(), seen = new Set();
  for (const doc of documents || []) {
    const day = String(doc.serviceDate || '').slice(0, 10);
    if (doc.status !== 'FINAL' || doc.documentType !== 'UPAH_RELAWAN' || day < period.start || day > period.end) continue;
    const identity = doc.id ?? `${doc.documentNumber}:${day}`;
    if (seen.has(identity)) continue;
    seen.add(identity);
    (doc.items || []).forEach((item, index) => {
      const type = String(item.metadata?.recipientType || 'Relawan').trim().toLowerCase();
      if (type !== 'relawan') return; // Combined packages also contain Guru/Kader.
      const name = String(item.itemName || '').trim().replace(/\s+/g, ' ');
      const key = name ? name.toLocaleLowerCase('id-ID') : `unnamed:${identity}:${index}`;
      if (!groups.has(key)) groups.set(key, {key, name: name || 'Nama belum diisi', roles: new Set(), days: new Set(), invoices: new Set(), amount: 0, details: []});
      const group = groups.get(key), amount = Number(item.lineTotal || 0);
      group.amount += amount;
      group.days.add(day);
      group.invoices.add(identity);
      if (item.metadata?.role) group.roles.add(item.metadata.role);
      group.details.push({day, documentNumber: doc.documentNumber, amount, role: item.metadata?.role || '', pdfLink: doc.bgnDriveUri || doc.driveUri || '', documentId: identity, line: index});
    });
  }
  return [...groups.values()].map(g => ({...g, roles: [...g.roles].join(', '), dayCount: g.days.size, invoiceCount: g.invoices.size})).sort((a,b) => a.name.localeCompare(b.name, 'id-ID'));
}

