# Integrasi Auto-Stop Pterodactyl

Fitur ini menyambungkan sistem tagihan userbot ke panel Pterodactyl kamu, supaya server
pelanggan otomatis **di-stop** (dimatikan) kalau belum bayar sampai jam tertentu (default
01:00 WIB), dan otomatis **di-start** lagi begitu kamu tandai lunas.

> ⚠️ Fitur ini pakai **Client API**, bukan Application API. Client API cuma bisa kontrol
> server yang **dimiliki akun API key itu sendiri**. Jadi ini cuma cocok kalau semua server
> pelanggan dibuat & dimiliki oleh 1 akun admin/kamu sendiri (pelanggan gak punya login
> panel terpisah). Kalau tiap pelanggan punya akun panel sendiri-sendiri, fitur ini tidak
> akan bisa mengontrol server mereka kecuali akun kamu di-invite jadi subuser di tiap server
> (tidak dibahas di panduan ini).

## 1. Buat Client API Key

Beda dengan Application API Key (yang dibuat Admin), Client API Key dibuat dari **akun
kamu sendiri** (bukan dari halaman Admin):

1. Login ke panel dengan akun yang memiliki semua server pelanggan.
2. Klik ikon profil kamu (pojok kanan atas) → **Account Settings**.
3. Buka tab **API Credentials**.
4. Klik **Create**, kasih deskripsi (mis. "Userbot Auto Stop"), Create.
5. Copy API key yang muncul (formatnya diawali `ptlc_`).

⚠️ **Key ini powerful** — bisa kontrol semua server yang dimiliki akun kamu (start, stop,
restart, kill, akses console). Perlakukan seperti password, jangan taruh di kode langsung,
selalu lewat Environment Variable atau `config.json`.

## 2. Cari Server Identifier tiap pelanggan

Identifier yang dibutuhkan Client API **beda format** dengan Server ID yang dipakai
Application API — ini kode alfanumerik pendek (bukan angka polos). Cara cek:

- Masuk ke server itu di panel (klik dari daftar server kamu).
- Lihat URL di address bar, formatnya `.../server/d3aac351` → `d3aac351` itu identifier-nya.

## 3. Set Environment Variable tambahan

| Variable | Isi |
|---|---|
| `PTERO_PANEL_URL` | URL panel kamu, mis. `https://panel.anonymhost.com` (tanpa trailing slash) |
| `PTERO_CLIENT_API_KEY` | Client API Key dari langkah 1 (diawali `ptlc_`) |
| `SUSPEND_HOUR_WIB` | Jam WIB kapan cek stop dijalankan, default `1` (jam 01:00) |
| `SUSPEND_WINDOW_MINUTES` | Toleransi window pengecekan, default `10` menit |

### Di mana harus diisi?

`main.py` selalu cek `config.json` dulu, baru fallback ke Environment Variable.

**A. Lewat `config.json` (gak perlu update egg)** — buka file `config.json` di server
(lewat File Manager), tambahkan key-key di atas, restart server.

**B. Lewat tab Startup** — kalau pakai egg custom (`pterodactyl-egg.json` versi terbaru),
variable ini sudah otomatis terdaftar, tinggal isi lewat form Startup di panel.

## 4. Cara pakai command

```
.add-tagihan web 0205 150000 d3aac351
```
Artinya: tagihan Rp150.000 label "web", jatuh tempo tiap tanggal 2 Mei/bulan, disambungkan
ke server dengan identifier `d3aac351`.

Kalau identifier belum diketahui saat awal set tagihan, bisa nyusul:
```
.set-server web d3aac351
```

Command lain:
- `.stop [label]` / `.start [label]` — stop/start manual server yang tersambung ke tagihan itu (buat testing atau kondisi darurat).
- `.lunas [label]` — otomatis start lagi kalau sebelumnya sempat di-stop.
- `.list-tagihan` / `.tagihan-sini` — nampilin juga Server Identifier & status stop tiap tagihan.

## 5. Alur otomatisnya

1. Tanggal jatuh tempo tiba → bot kirim reminder + QRIS (seperti biasa).
2. Kalau besoknya masih belum `.lunas` DAN sekarang jam 01:00–01:10 WIB (sesuai
   `SUSPEND_HOUR_WIB`/`SUSPEND_WINDOW_MINUTES`) → bot panggil Client API power signal
   `stop`, kirim notif ke pelanggan bahwa layanan dinonaktifkan sementara.
3. Stop hanya dipanggil **sekali** (ditandai `stopped: true` di database), gak akan
   spam berkali-kali.
4. Begitu kamu jalankan `.lunas`, server otomatis di-start lagi.

Bedanya dengan suspend (metode lama): **stop** cuma mematikan proses server (seperti
tombol Stop di panel), servernya masih kelihatan normal, cuma statusnya offline. Kalau
kamu butuh yang lebih "terkunci" (gak bisa di-start manual sampai di-unsuspend admin),
itu perlu Application API + suspend, yang butuh setup berbeda.

> **Catatan:** di beberapa konfigurasi Wings, server yang berhenti gak sepenuhnya bersih
> (proses gak merespon graceful stop) bisa "nyangkut" — tombol Start di panel gak bisa
> ditekan sampai di-**Kill** dulu. `start_server()` di `main.py` sudah menangani ini
> otomatis: tiap kali `.start` / `.lunas` dipanggil, bot kirim signal `kill` dulu (aman,
> no-op kalau server sudah bersih offline), tunggu 2 detik, baru kirim `start`.

## 6. Testing sebelum dipakai serius

Disarankan test dulu pakai server dummy/testing:
1. `.add-tagihan test <tanggal_kemarin> 10000 <identifier_server_testing>`
2. Coba manual dulu: `.stop test` — pastikan API key & identifier benar sebelum
   mengandalkan yang otomatis.
3. Kalau sukses stop, coba `.lunas test` untuk mastiin auto-start juga jalan.
