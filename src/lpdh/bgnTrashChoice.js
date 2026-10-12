// Preserve BGN files by default. Closing the warning aborts cancellation.
export function chooseBgnTrash(hasFile=true) {
  if (!hasFile) return false;
  const choice=window.prompt('File di Drive BGN:\nSIMPAN = batalkan dokumen, file BGN tetap ada (default).\nSAMPAH = batalkan dan pindahkan file BGN ke Sampah; bukan hapus permanen.\nSalinan internal dan riwayat tetap disimpan. Ketik SIMPAN atau SAMPAH:', 'SIMPAN');
  if (choice===null) return null;
  const answer=choice.trim().toUpperCase();
  if (answer==='SIMPAN') return false;
  if (answer==='SAMPAH') return true;
  window.alert('Pilihan tidak valid. Pembatalan tidak dijalankan.');
  return null;
}
