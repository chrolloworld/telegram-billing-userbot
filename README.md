# Pterodactyl Billing Userbot

**Sistem billing Telegram otomatis untuk reseller hosting.** Kirim kode pembayaran QRIS, kirim pengingat bulanan, dan auto-stop server Pterodactyl untuk pelanggan yang belum bayar — semuanya lewat akun Telegram kamu sendiri.

Dibangun pakai [Telethon](https://github.com/LonamiWebs/Telethon) sebagai userbot (jalan di akun Telegram pribadi kamu, bukan bot BotFather), dirancang khusus untuk reseller hosting/server berbasis Pterodactyl yang selama ini nge-manage billing pelanggan secara manual.

---

## Kenapa project ini dibuat

Kalau kamu jualan jasa hosting berbasis Pterodactyl (game server, bot hosting, panel VPS, dll), kemungkinan besar kamu masih nagih pelanggan manual tiap bulan dan matiin server yang gak bayar satu-satu. Bot ini otomatisin seluruh alur itu:

```
Tanggal jatuh tempo pelanggan tiba
        │
        ▼
Bot otomatis kirim QRIS + pesan pengingat
        │
        ▼
  Sudah bayar? ──Ya──► Kamu jalankan `.lunas` → jatuh tempo maju ke bulan depan
        │
        Belum
        ▼
Reminder harian berlanjut, makin tegas setelah masa tenggang habis
        │
        ▼
Masih belum bayar sampai jam 01:00 WIB sehari setelah jatuh tempo?
        │
        ▼
   Bot otomatis stop server pelanggan lewat Pterodactyl Client API
```

## Fitur

- **Billing QRIS** — `.pay <nominal>` mengirim QRIS yang sudah kamu simpan beserta caption tagihan yang rapi, ke chat manapun, kapan saja.
- **Reminder bulanan berulang** — set tanggal jatuh tempo sekali, bot otomatis ingatkan pelanggan tiap bulan tanpa perlu dicatat manual.
- **Banyak tagihan dalam 1 chat** — satu pelanggan bisa punya beberapa item tagihan terpisah (misal hosting + domain), masing-masing dilacak sendiri lewat label.
- **Pesan telat bayar yang makin tegas** — masa tenggang bisa diatur sebelum nada pesan berubah jadi lebih serius.
- **Auto-stop di Pterodactyl** — sambungkan tagihan ke identifier server pelanggan; kalau belum bayar + sudah lewat jatuh tempo + masuk jam stop → server otomatis di-stop lewat Pterodactyl Client API. Begitu bayar, otomatis di-start lagi.
- **Self-hosted, data tetap punya kamu** — tanpa SaaS billing pihak ketiga, cukup panel Pterodactyl dan akun Telegram kamu sendiri.

## Daftar Command

| Command | Keterangan |
|---|---|
| `.pay <nominal>` | Kirim gambar QRIS tersimpan + caption tagihan |
| `.pay` | Kirim QRIS tanpa nominal spesifik |
| `.add-tagihan <label> <DDMM> <nominal> [server_identifier]` | Buat/update tagihan berulang. Contoh: `.add-tagihan web 0205 150000 d3aac351` |
| `.set-server [label] <server_identifier>` | Sambungkan server Pterodactyl ke tagihan belakangan |
| `.lunas [label]` | Tandai tagihan lunas — jatuh tempo maju ke bulan depan, auto-start kalau server sempat di-stop |
| `.hapus-tagihan [label]` | Hapus satu tagihan |
| `.tagihan-sini` | Lihat semua tagihan di chat ini |
| `.list-tagihan` | Lihat semua tagihan di semua chat |
| `.stop [label]` / `.start [label]` | Stop/start manual server yang tersambung |
| `.ping` | Cek bot masih hidup |
| `.help` | Tampilkan daftar command |

> `[label]` boleh dikosongkan kalau chat itu cuma punya 1 tagihan — bot otomatis pakai yang itu. Kalau ada lebih dari 1 tagihan di chat yang sama, label wajib disebut biar bot tau yang mana yang dimaksud.

## Yang Dibutuhkan

- Akun Telegram (dipakai untuk menjalankan userbot — command cuma bisa dipanggil dari akun ini)
- Kredensial API dari [my.telegram.org](https://my.telegram.org)
- Panel Pterodactyl (cuma dibutuhkan kalau mau pakai auto-stop; fitur billing/reminder tetap jalan tanpa ini)
- Python 3.11, atau server Pterodactyl dengan egg image `Python 3.11`

## Mulai Cepat

### 1. Ambil kredensial API Telegram

Buka [my.telegram.org](https://my.telegram.org) → **API Development Tools** → buat aplikasi baru → catat `api_id` dan `api_hash`.

### 2. Generate session string (sekali saja, di komputer kamu sendiri)

```bash
pip install telethon
python generate_session.py
```

Ikuti instruksinya (nomor HP, kode OTP, 2FA kalau aktif). Ini akan menghasilkan session string Telethon — perlakukan seperti password, karena string ini memberi akses penuh ke akun Telegram kamu.

### 3. Deploy

**Opsi A — Egg custom Pterodactyl (direkomendasikan)**

1. Admin panel → **Nests** → **Import Egg** → upload [`pterodactyl-egg.json`](./pterodactyl-egg.json)
2. Buat server baru menggunakan egg yang baru diimport
3. Isi variable yang muncul (`API_ID`, `API_HASH`, `SESSION`, dll)
4. Upload foto QRIS kamu ke folder `qris/` lewat File Manager
5. Start server

**Opsi B — Environment Python apapun + file config**

1. Clone repo ini / upload semua file ke server kamu
2. `pip install -r requirements.txt`
3. Copy `config.json.example` → `config.json` lalu isi dengan data asli kamu
4. Taruh foto QRIS di folder `qris/`
5. `python main.py`

### 4. Verifikasi

Setelah bot jalan, kirim `.ping` dari akun Telegram kamu sendiri di chat manapun (misal Saved Messages) — harusnya balas `🏓 Pong!`.

## Referensi Konfigurasi

| Variable | Default | Keterangan |
|---|---|---|
| `API_ID` / `API_HASH` | — | Dari my.telegram.org |
| `SESSION` | — | Dihasilkan lewat `generate_session.py` |
| `PREFIX` | `.` | Prefix command |
| `QRIS_FOLDER` | `qris` | Folder tempat gambar QRIS disimpan |
| `BUSINESS_NAME` | `AnonymHost` | Muncul di caption tagihan |
| `DELETE_COMMAND` | `true` | Hapus pesan `.pay` kamu sendiri setelah terkirim |
| `GRACE_DAYS` | `3` | Berapa hari telat sebelum nada pesan makin tegas |
| `TAGIHAN_FILE` | `tagihan.json` | Tempat data tagihan disimpan |
| `CHECK_INTERVAL_SECONDS` | `300` | Seberapa sering loop background cek tagihan |
| `PTERO_PANEL_URL` | *(kosong)* | URL panel Pterodactyl kamu — kosongkan untuk nonaktifkan auto-stop |
| `PTERO_CLIENT_API_KEY` | *(kosong)* | Pterodactyl **Client** API key (bukan Application API), dari Account Settings kamu sendiri |
| `SUSPEND_HOUR_WIB` | `1` | Jam (WIB, 0–23) pengecekan auto-stop dijalankan |
| `SUSPEND_WINDOW_MINUTES` | `10` | Toleransi window di sekitar jam stop |

Panduan lengkap integrasi Pterodactyl (bikin API key, cari Server ID, permission yang dibutuhkan) ada di [`docs/PTERODACTYL-INTEGRATION.md`](./docs/PTERODACTYL-INTEGRATION.md).

## Catatan Keamanan

- **`SESSION` dan `PTERO_API_KEY` setara dengan password.** Jangan pernah di-commit, jangan pernah dishare. Keduanya sudah otomatis dikecualikan lewat `.gitignore` (sebagai bagian dari `config.json`).
- `PTERO_CLIENT_API_KEY` dibuat dari akun kamu sendiri (Account Settings, bukan Admin), dan hanya bisa mengontrol server yang dimiliki akun itu. Cocok untuk setup di mana semua server pelanggan dibuat di 1 akun admin/kamu sendiri.
- Ini adalah userbot, bukan bot Telegram resmi — command dijalankan dari akun kamu sendiri. ToS Telegram secara resmi tidak mengizinkan automasi di akun user biasa, jadi gunakan secara wajar (tool ini dirancang untuk chat billing 1:1 dengan pelanggan, bukan untuk mass messaging).
- QRIS yang dipakai di sini bersifat **statis** — nominal ditulis di caption pesan, bukan ter-embed ke dalam kode QR-nya. QRIS dinamis (nominal ter-embed di kode) membutuhkan integrasi payment gateway berbayar terpisah.

## Disclaimer

Project ini mengotomatisasi penonaktifan infrastruktur milik pelanggan yang membayar. Coba dulu di server percobaan/staging sebelum diarahkan ke server pelanggan asli, dan pastikan pelanggan kamu sudah paham soal ketentuan pembayaran dan kebijakan stop otomatis yang berlaku.

## Lisensi

MIT — bebas dipakai, dimodifikasi, dan dipakai untuk menjual jasa di atasnya.
