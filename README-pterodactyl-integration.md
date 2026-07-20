# Integrasi Auto-Suspend Pterodactyl

Fitur ini menyambungkan sistem tagihan userbot ke panel Pterodactyl kamu, supaya server
pelanggan otomatis di-suspend kalau belum bayar sampai jam tertentu (default 01:00 WIB).

## 1. Buat Application API Key di Pterodactyl

⚠️ Ini BEDA dengan Client API Key. Yang dibutuhkan adalah **Application API**, yang
hanya bisa dibuat oleh **Admin**.

1. Login ke panel sebagai admin.
2. Ke **Admin → Application API** (biasanya di `/admin/api`).
3. Klik **Create New**, kasih nama (mis. "Userbot Auto Suspend").
4. Centang permission minimal: **Servers: Read & Write** (agar bisa suspend/unsuspend).
5. Save, copy API key yang muncul (formatnya panjang, diawali `ptla_`).

⚠️ **API Key ini sangat powerful** — siapapun yang pegang bisa suspend/unsuspend SEMUA
server di panel kamu, bahkan (tergantung permission) create/delete server. Perlakukan
sama seperti password. Jangan taruh di kode langsung, selalu lewat Environment Variable
atau `config.json`.

## 2. Cari Server ID tiap pelanggan

Server ID yang dibutuhkan adalah **ID internal (angka)**, BUKAN UUID yang muncul di URL
biasa. Cara cek:

- Masuk **Admin → Servers**, klik server pelanggan yang dimaksud.
- Lihat URL di address bar, formatnya `.../admin/servers/view/3` → angka `3` itu Server ID-nya.

## 3. Set Environment Variable tambahan

Selain variable yang sudah ada (`API_ID`, `API_HASH`, `SESSION`, dll), tambahkan:

| Variable | Isi |
|---|---|
| `PTERO_PANEL_URL` | URL panel kamu, mis. `https://panel.anonymhost.com` (tanpa trailing slash) |
| `PTERO_API_KEY` | Application API Key dari langkah 1 |
| `SUSPEND_HOUR_WIB` | Jam WIB kapan cek suspend dijalankan, default `1` (jam 01:00) |
| `SUSPEND_WINDOW_MINUTES` | Toleransi window pengecekan, default `10` menit |
| `CHECK_INTERVAL_SECONDS` | Interval loop cek tagihan, default `300` (5 menit) — **jangan diset kebesaran** kalau pakai auto-suspend, supaya window jam 01:00 gak kelewat |

### Di mana harus diisi? (`config.json` vs tab Startup)

`main.py` selalu cek `config.json` dulu, baru fallback ke Environment Variable. Jadi ada
2 cara, pilih salah satu:

**A. Lewat `config.json` (lebih gampang, TIDAK perlu update egg)**
Buka file `config.json` yang sudah ada di server (lewat File Manager Pterodactyl),
tambahkan key-key baru di atas langsung ke JSON-nya, contoh:
```json
{
  "API_ID": "...",
  "API_HASH": "...",
  "SESSION": "...",
  "PTERO_PANEL_URL": "https://panel.anonymhost.com",
  "PTERO_API_KEY": "ptla_xxxxxxxx",
  "SUSPEND_HOUR_WIB": "1",
  "SUSPEND_WINDOW_MINUTES": "10",
  "CHECK_INTERVAL_SECONDS": "300"
}
```
Save, lalu restart server. Selesai, gak perlu sentuh egg sama sekali.

**B. Lewat tab Startup (env variable), kalau kamu pakai egg custom**
Egg custom (`egg-telegram-userbot-anonymhost.json`) yang dipakai sebelumnya cuma
mendefinisikan 7 variable (`API_ID`, `API_HASH`, `SESSION`, `PREFIX`, `QRIS_FOLDER`,
`BUSINESS_NAME`, `DELETE_COMMAND`) — variable baru di atas **belum terdaftar**, jadi
tidak akan muncul di tab Startup sampai ditambahkan ke egg-nya:
1. Admin panel → **Nests** → pilih egg-nya → tab **Variables**.
2. Klik **New Variable**, isi tiap variable baru satu-satu (nama, `env_variable`, default value, rules).
3. Save. Server yang sudah pakai egg ini otomatis dapat variable baru tsb di tab Startup-nya (tidak perlu reinstall).

Kalau kamu masih pakai egg bawaan (Python-Universal) yang sempat error kemarin, opsi
**A (`config.json`)** jauh lebih disarankan — lebih cepat dan menghindari isu yang sama
seperti sebelumnya (Startup Command box kepotong / bug templating).

Kalau `PTERO_PANEL_URL` atau `PTERO_API_KEY` kosong, fitur auto-suspend otomatis nonaktif
(gak akan error, cuma di-skip).

## 4. Cara pakai command baru

Sekarang satu chat bisa punya **lebih dari 1 tagihan**, dibedakan pakai **label**:

```
.add-tagihan webutama 0205 150000 3
.add-tagihan hostingtambahan 1505 50000 7
```
Artinya: chat itu punya 2 tagihan — "webutama" (Rp150.000, jatuh tempo tgl 2 tiap bulan,
server ID 3) dan "hostingtambahan" (Rp50.000, tgl 15, server ID 7).

Command lain butuh label kalau chat itu punya lebih dari 1 tagihan aktif:
```
.lunas webutama
.set-server hostingtambahan 7
.suspend webutama
```
Kalau chat cuma punya **1 tagihan saja**, label boleh dikosongkan (bot otomatis pakai yang itu):
```
.lunas
```

Lihat semua tagihan di 1 chat tertentu:
```
.tagihan-sini
```

Lihat semua tagihan di semua chat (rekap keseluruhan pelanggan):
```
.list-tagihan
```

Kalau kamu jalankan command tanpa label padahal chat itu punya lebih dari 1 tagihan, bot
akan kasih tau daftar label yang tersedia supaya kamu bisa pilih.

> Data lama (dari sebelum fitur multi-tagihan ini) otomatis di-migrate ke label `utama`
> saat bot pertama kali jalan, jadi data yang sudah ada tidak hilang.

## 5. Alur otomatisnya

1. Tanggal jatuh tempo tiba → bot kirim reminder + QRIS (seperti biasa).
2. Kalau besoknya masih belum `.lunas` DAN sekarang jam 01:00–01:10 WIB (sesuai
   `SUSPEND_HOUR_WIB`/`SUSPEND_WINDOW_MINUTES`) → bot panggil API suspend, kirim notif
   ke pelanggan bahwa layanan dinonaktifkan.
3. Suspend hanya dipanggil **sekali** (ditandai `suspended: true` di database), gak akan
   spam suspend berkali-kali.
4. Begitu kamu jalankan `.lunas`, server otomatis di-unsuspend lagi.

## 6. Testing sebelum dipakai serius

Disarankan test dulu pakai server dummy/testing:
1. `.add-tagihan <tanggal_kemarin> 10000 <server_id_testing>` (pakai server_id server test, bukan pelanggan asli)
2. Tunggu sampai jam window suspend, atau langsung tes manual `.suspend` dulu buat mastiin API key & permission benar.
3. Kalau sukses suspend, coba `.lunas` untuk mastiin auto-unsuspend juga jalan.
