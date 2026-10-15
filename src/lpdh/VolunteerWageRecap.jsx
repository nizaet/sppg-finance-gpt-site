import React from 'react';
import {volunteerRecap} from './volunteerRecap.mjs';
const money = n => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;
export default function VolunteerWageRecap({rows, period}) {
  const people = volunteerRecap(rows, period);
  const total = people.reduce((s,p) => s+p.amount, 0);
  return <section><h3>Rekap Upah Relawan per Nama</h3>
    <p>Hanya upah relawan dari invoice FINAL pada {period.start} sampai {period.end}. Guru dan kader dalam paket gabungan tidak ikut. Hari pelayanan menghitung tanggal berbeda, bukan jumlah baris invoice. Nama sama digabung tanpa membedakan huruf besar/kecil atau spasi.</p>
    <div className="lpdh-summary-cards"><div><span>Nama relawan</span><strong>{people.length}</strong></div><div><span>Total upah relawan</span><strong>{money(total)}</strong></div></div>
    <div className="lpdh-table-wrap"><table className="lpdh-data-table"><thead><tr><th>Nama relawan</th><th>Tugas</th><th>Hari pelayanan</th><th>Jumlah invoice</th><th>Total upah</th><th>Rincian</th></tr></thead><tbody>
      {people.map(person => <tr key={person.key}><td>{person.name}</td><td>{person.roles || '—'}</td><td>{person.dayCount}</td><td>{person.invoiceCount}</td><td>{money(person.amount)}</td><td><details><summary>Rincian invoice · {person.invoiceCount}</summary><table><thead><tr><th>Tanggal HPE</th><th>Invoice</th><th>Upah</th><th>Bukti</th></tr></thead><tbody>{person.details.map(d => <tr key={`${d.documentId}:${d.line}`}><td>{d.day}</td><td>{d.documentNumber}</td><td>{money(d.amount)}</td><td>{d.pdfLink ? <a href={d.pdfLink} target="_blank" rel="noopener noreferrer">PDF invoice</a> : 'Belum ada link PDF'}</td></tr>)}</tbody></table></details></td></tr>)}
      {!people.length && <tr><td colSpan={6}>Belum ada upah relawan dari invoice FINAL pada periode ini.</td></tr>}
    </tbody><tfoot><tr><th colSpan={4}>TOTAL UPAH RELAWAN</th><th>{money(total)}</th><td/></tr></tfoot></table></div>
  </section>;
}

