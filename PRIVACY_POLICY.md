# Kebijakan Privasi — SPPG OPERASIONAL

**Terakhir diperbarui: 12 Agustus 2026**

Kebijakan Privasi ini menjelaskan bagaimana layanan **SPPG OPERASIONAL** memproses data ketika pengguna menggunakan GPT dan Action yang terhubung ke sistem operasional SPPG.

## 1. Data yang dapat diproses

Layanan dapat memproses data operasional dan keuangan yang diberikan oleh pengguna, termasuk antara lain:

- nama/lokasi unit SPPG;
- tanggal transaksi atau kegiatan;
- deskripsi transaksi;
- nama vendor, pemasok, penerima, atau pihak terkait;
- kategori transaksi;
- jumlah, kuantitas, satuan, dan harga;
- status hutang dan pembayaran;
- catatan klasifikasi, koreksi, dan audit;
- teks instruksi yang dikirim pengguna kepada GPT apabila diperlukan sebagai bukti operasional.

Pengguna tidak boleh memasukkan password, private key, service-account JSON, API key, token akses, atau kredensial rahasia lainnya ke dalam percakapan.

## 2. Tujuan penggunaan data

Data digunakan untuk menjalankan fungsi operasional SPPG, termasuk:

- mencatat dan mengklasifikasikan transaksi;
- memperbarui data keuangan yang telah diotorisasi pengguna;
- melakukan sinkronisasi dengan sistem aplikasi SPPG;
- melakukan pencarian, koreksi, rekonsiliasi, dan audit transaksi;
- mencegah duplikasi transaksi dan menjaga jejak perubahan;
- mendukung pelaporan dan kontrol operasional.

Data tidak digunakan untuk dijual kepada pihak ketiga atau untuk periklanan pihak ketiga.

## 3. Sistem penyimpanan dan pemrosesan

Untuk menjalankan fungsi layanan, data dapat diproses atau disimpan pada infrastruktur yang digunakan oleh SPPG OPERASIONAL, termasuk database PostgreSQL, Google Cloud/Firebase Firestore, dan layanan hosting backend. Arsip bukti operasional dapat disimpan pada Google Drive apabila fitur tersebut diaktifkan.

Layanan ChatGPT/OpenAI dan penyedia infrastruktur terkait dapat memproses data sesuai kebutuhan teknis untuk menyediakan layanan mereka dan sesuai ketentuan serta kebijakan privasi masing-masing penyedia.

## 4. Akses dan pengendalian

Akses ke fungsi yang dapat mengubah data dibatasi menggunakan autentikasi API dan kredensial server. Pengguna yang tidak memiliki otorisasi tidak diperbolehkan menggunakan Action untuk menambah, mengubah, atau menghapus data operasional.

Kategori atau informasi yang diberikan secara eksplisit oleh pengguna tidak boleh diubah secara otomatis tanpa dasar operasional yang sesuai. Sistem juga menggunakan identifikasi transaksi dan mekanisme idempotensi untuk mengurangi risiko pencatatan ganda.

## 5. Penyimpanan dan penghapusan

Data disimpan selama masih diperlukan untuk kebutuhan operasional, akuntansi, audit, rekonsiliasi, pencadangan, atau kewajiban organisasi yang berlaku. Data yang tidak lagi diperlukan dapat dikoreksi atau dihapus oleh administrator yang berwenang sesuai prosedur internal.

## 6. Keamanan

SPPG OPERASIONAL menerapkan langkah teknis yang wajar untuk melindungi data, termasuk pembatasan akses, autentikasi API, pemisahan kredensial rahasia dari percakapan, serta pencatatan aktivitas pada sistem backend.

Tidak ada sistem elektronik yang dapat dijamin sepenuhnya bebas risiko. Karena itu pengguna harus menghindari memasukkan kredensial atau rahasia sistem ke dalam chat.

## 7. Hak dan koreksi data

Pengguna yang berwenang dapat meminta peninjauan, koreksi, atau penghapusan data yang salah melalui pengelola SPPG OPERASIONAL dan saluran internal yang berlaku.

## 8. Perubahan kebijakan

Kebijakan ini dapat diperbarui apabila fungsi aplikasi, metode penyimpanan, integrasi, atau proses operasional berubah. Tanggal pembaruan terakhir akan dicantumkan pada bagian atas dokumen ini.

## 9. Kontak

Untuk pertanyaan mengenai data yang diproses oleh SPPG OPERASIONAL, hubungi administrator/pengelola SPPG OPERASIONAL melalui saluran internal resmi yang digunakan oleh organisasi.
