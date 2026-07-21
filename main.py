import os
import json
import glob
import asyncio
import calendar
import aiohttp
from datetime import date, datetime, timezone, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ==== KONFIGURASI ====
# Prioritas: file config.json (tidak ada limit panjang karakter) > Environment Variable.
CONFIG_FILE = "config.json"

_cfg = {}
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "r") as f:
        _cfg = json.load(f)


def cfg(key, default=""):
    return _cfg.get(key, os.environ.get(key, default))


API_ID = int(cfg("API_ID", "0"))
API_HASH = cfg("API_HASH", "")
SESSION = cfg("SESSION", "")  # string session, lihat generate_session.py
PREFIX = cfg("PREFIX", ".")   # prefix command, default "."
QRIS_FOLDER = cfg("QRIS_FOLDER", "qris")  # folder tempat gambar qris disimpan
BUSINESS_NAME = cfg("BUSINESS_NAME", "AnonymHost")
DELETE_COMMAND = str(cfg("DELETE_COMMAND", "true")).lower() == "true"
GRACE_DAYS = int(cfg("GRACE_DAYS", "3"))  # berapa hari telat sebelum warning tegas dikirim
TAGIHAN_FILE = cfg("TAGIHAN_FILE", "tagihan.json")
CHECK_INTERVAL_SECONDS = int(cfg("CHECK_INTERVAL_SECONDS", "300"))  # cek tiap 5 menit (dipercepat utk presisi suspend)

# ---- Integrasi Pterodactyl (opsional, buat auto-stop server telat bayar) ----
PTERO_PANEL_URL = cfg("PTERO_PANEL_URL", "").rstrip("/")  # contoh: https://panel.anonymhost.com
PTERO_CLIENT_API_KEY = cfg("PTERO_CLIENT_API_KEY", "")  # Client API Key dari Account Settings -> API Credentials
SUSPEND_HOUR_WIB = int(cfg("SUSPEND_HOUR_WIB", "1"))  # jam WIB kapan cek stop otomatis (default jam 1 pagi)
SUSPEND_WINDOW_MINUTES = int(cfg("SUSPEND_WINDOW_MINUTES", "10"))  # toleransi window cek
WIB = timezone(timedelta(hours=7))

AUTO_STOP_ENABLED = bool(PTERO_PANEL_URL and PTERO_CLIENT_API_KEY)

if not API_ID or not API_HASH or not SESSION:
    raise SystemExit(
        "API_ID / API_HASH / SESSION belum di-set. "
        "Set lewat Environment Variables di Pterodactyl (Startup tab)."
    )

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

_db_lock = asyncio.Lock()


# ==================== UTIL ====================

def format_rupiah(nominal: int) -> str:
    return f"Rp {nominal:,.0f}".replace(",", ".")


def get_qris_file():
    patterns = ["*.jpg", "*.jpeg", "*.png"]
    files = []
    for p in patterns:
        files.extend(glob.glob(os.path.join(QRIS_FOLDER, p)))
    return files[0] if files else None


def _clamp_day(year: int, month: int, day: int) -> int:
    last_day = calendar.monthrange(year, month)[1]
    return min(day, last_day)


def add_one_month(d: date) -> date:
    month = d.month + 1
    year = d.year + (month - 1) // 12
    month = ((month - 1) % 12) + 1
    day = _clamp_day(year, month, d.day)
    return date(year, month, day)


def next_occurrence(day: int, month: int, today: date = None) -> date:
    """Cari tanggal terdekat (hari ini atau masa depan) untuk kombinasi day/month."""
    today = today or date.today()
    year = today.year
    d = date(year, month, _clamp_day(year, month, day))
    if d < today:
        year += 1
        d = date(year, month, _clamp_day(year, month, day))
    return d


# ==================== DATABASE (JSON file) ====================

async def load_db() -> dict:
    async with _db_lock:
        if not os.path.exists(TAGIHAN_FILE):
            return {}
        with open(TAGIHAN_FILE, "r") as f:
            try:
                raw = json.load(f)
            except json.JSONDecodeError:
                return {}

    # ---- Migrasi format lama (key = chat_id polos, 1 tagihan per chat) ----
    # ke format baru (key = "chat_id:label", banyak tagihan per chat).
    migrated = {}
    needs_save = False
    for key, entry in raw.items():
        if ":" in key:
            migrated[key] = entry
        else:
            entry.setdefault("label", "utama")
            new_key = f"{key}:{entry['label']}"
            migrated[new_key] = entry
            needs_save = True

    if needs_save:
        await save_db(migrated)

    return migrated


async def save_db(db: dict):
    async with _db_lock:
        with open(TAGIHAN_FILE, "w") as f:
            json.dump(db, f, indent=2, default=str)


def chat_entries(db: dict, chat_id) -> list:
    """Semua entry tagihan untuk 1 chat_id tertentu. Return list of (key, entry)."""
    prefix = f"{chat_id}:"
    return [(k, v) for k, v in db.items() if k.startswith(prefix)]


def resolve_entry(db: dict, chat_id, label: str):
    """
    Cari entry tagihan untuk sebuah chat, dengan atau tanpa label eksplisit.
    Return (key, entry, error_message). Kalau error_message tidak None, key/entry adalah None.
    """
    entries = chat_entries(db, chat_id)

    if label:
        key = f"{chat_id}:{label}"
        if key in db:
            return key, db[key], None
        available = ", ".join(f"`{v['label']}`" for _, v in entries) or "(belum ada tagihan)"
        return None, None, f"❌ Label `{label}` tidak ditemukan di chat ini. Tagihan aktif: {available}"

    if len(entries) == 0:
        return None, None, "❌ Belum ada tagihan untuk chat ini."

    if len(entries) == 1:
        return entries[0][0], entries[0][1], None

    labels = ", ".join(f"`{v['label']}`" for _, v in entries)
    example_label = entries[0][1]["label"]
    return None, None, (
        f"⚠️ Chat ini punya {len(entries)} tagihan aktif: {labels}\n"
        f"Sebutkan labelnya, misal `{PREFIX}lunas {example_label}`"
    )


# ==================== PTERODACTYL API (Client API - power actions) ====================

async def _ptero_power(server_identifier: str, signal: str) -> tuple[bool, str]:
    """Kirim power signal (start/stop/restart/kill) lewat Client API. Return (sukses, pesan)."""
    if not AUTO_STOP_ENABLED:
        return False, "Integrasi Pterodactyl belum dikonfigurasi (PTERO_PANEL_URL / PTERO_CLIENT_API_KEY kosong)."

    url = f"{PTERO_PANEL_URL}/api/client/servers/{server_identifier}/power"
    headers = {
        "Authorization": f"Bearer {PTERO_CLIENT_API_KEY}",
        "Accept": "Application/vnd.pterodactyl.v1+json",
        "Content-Type": "application/json",
    }
    payload = {"signal": signal}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status in (200, 202, 204):
                    return True, "OK"
                body = await resp.text()
                return False, f"HTTP {resp.status}: {body[:200]}"
    except Exception as e:
        return False, f"Error koneksi: {e}"


async def stop_server(server_identifier: str) -> tuple[bool, str]:
    return await _ptero_power(server_identifier, "stop")


async def start_server(server_identifier: str) -> tuple[bool, str]:
    """
    Kirim 'kill' dulu sebelum 'start'. Ini buat jaga-jaga kalau server sempat macet di
    state antara stop->offline (proses gak berhenti bersih), yang bikin tombol Start
    terkunci sampai di-kill manual dulu di beberapa konfigurasi Wings. Kalau server
    sudah bersih offline, kill di sini cuma no-op (aman, gak ada efek samping).
    """
    await _ptero_power(server_identifier, "kill")
    await asyncio.sleep(2)
    return await _ptero_power(server_identifier, "start")


def is_in_suspend_window(now_wib: datetime) -> bool:
    """True kalau waktu sekarang (WIB) berada dalam window jam stop otomatis, mis. 01:00-01:10."""
    target_minutes = SUSPEND_HOUR_WIB * 60
    now_minutes = now_wib.hour * 60 + now_wib.minute
    return target_minutes <= now_minutes < (target_minutes + SUSPEND_WINDOW_MINUTES)


# ==================== COMMANDS ====================

@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{PREFIX}pay(?:\s+(\d+))?$"))
async def pay_handler(event):
    match = event.pattern_match
    nominal_str = match.group(1)

    qris_file = get_qris_file()
    if not qris_file:
        await event.edit(f"❌ Gambar QRIS tidak ditemukan di folder `{QRIS_FOLDER}/`.")
        return

    header = f"💰 **Tagihan: {format_rupiah(int(nominal_str))}**\n\n" if nominal_str else ""
    caption = (
        f"{header}"
        f"Terimakasih sudah menggunakan jasa **{BUSINESS_NAME}**, "
        f"silahkan bayar sesuai tagihan yang sudah disepakati ya 🙏"
    )

    if DELETE_COMMAND:
        await event.delete()

    await client.send_file(event.chat_id, qris_file, caption=caption)


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{PREFIX}add-tagihan\s+([\w\-]+)\s+(\d{{4}})\s+(\d+)(?:\s+([\w\-]+))?$"))
async def add_tagihan_handler(event):
    label, ddmm, nominal_str, server_identifier = event.pattern_match.groups()
    day, month = int(ddmm[:2]), int(ddmm[2:])
    nominal = int(nominal_str)

    if not (1 <= day <= 31 and 1 <= month <= 12):
        await event.edit("❌ Format tanggal salah. Gunakan DDMM, misal `0205` untuk 2 Mei.")
        return

    due = next_occurrence(day, month)
    chat_id = event.chat_id
    key = f"{chat_id}:{label}"

    db = await load_db()
    is_update = key in db
    db[key] = {
        "chat_id": chat_id,
        "label": label,
        "nominal": nominal,
        "due_day": day,
        "due_month": month,
        "next_due": due.isoformat(),
        "last_reminded": None,
        "active": True,
        "server_identifier": server_identifier,
        "stopped": False,
    }
    await save_db(db)

    server_info = f"\n🖥️ Server: `{server_identifier}`" if server_identifier else f"\n🖥️ Server: (belum diset, pakai `{PREFIX}set-server {label} <identifier>`)"
    action_note = "diperbarui" if is_update else "diset"
    await event.edit(
        f"✅ Tagihan **{label}** {action_note} untuk chat ini:\n"
        f"💰 {format_rupiah(nominal)}\n"
        f"📅 Jatuh tempo: {due.strftime('%d %B %Y')}"
        f"{server_info}\n\n"
        f"Bot akan otomatis mengirim pengingat pada tanggal tersebut."
    )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{PREFIX}set-server\s+(?:([\w\-]+)\s+)?([\w\-]+)$"))
async def set_server_handler(event):
    label, server_identifier = event.pattern_match.groups()
    chat_id = event.chat_id

    db = await load_db()
    key, entry, err = resolve_entry(db, chat_id, label)
    if err:
        await event.edit(err)
        return

    entry["server_identifier"] = server_identifier
    db[key] = entry
    await save_db(db)
    await event.edit(f"✅ Server `{server_identifier}` disambungkan ke tagihan **{entry['label']}**.")


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{PREFIX}stop(?:\s+([\w\-]+))?$"))
async def manual_stop_handler(event):
    label = event.pattern_match.group(1)
    chat_id = event.chat_id
    db = await load_db()
    key, entry, err = resolve_entry(db, chat_id, label)
    if err:
        await event.edit(err)
        return
    if not entry.get("server_identifier"):
        await event.edit(f"❌ Tagihan **{entry['label']}** belum punya Server yang tersambung. Pakai `{PREFIX}set-server {entry['label']} <identifier>` dulu.")
        return
    ok, msg = await stop_server(entry["server_identifier"])
    if ok:
        entry["stopped"] = True
        db[key] = entry
        await save_db(db)
        await event.edit(f"⏹️ Server `{entry['server_identifier']}` ({entry['label']}) berhasil di-stop.")
    else:
        await event.edit(f"❌ Gagal stop: {msg}")


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{PREFIX}start(?:\s+([\w\-]+))?$"))
async def manual_start_handler(event):
    label = event.pattern_match.group(1)
    chat_id = event.chat_id
    db = await load_db()
    key, entry, err = resolve_entry(db, chat_id, label)
    if err:
        await event.edit(err)
        return
    if not entry.get("server_identifier"):
        await event.edit(f"❌ Tagihan **{entry['label']}** belum punya Server yang tersambung. Pakai `{PREFIX}set-server {entry['label']} <identifier>` dulu.")
        return
    ok, msg = await start_server(entry["server_identifier"])
    if ok:
        entry["stopped"] = False
        db[key] = entry
        await save_db(db)
        await event.edit(f"▶️ Server `{entry['server_identifier']}` ({entry['label']}) berhasil di-start.")
    else:
        await event.edit(f"❌ Gagal start: {msg}")


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{PREFIX}lunas(?:\s+([\w\-]+))?$"))
async def lunas_handler(event):
    label = event.pattern_match.group(1)
    chat_id = event.chat_id
    db = await load_db()
    key, entry, err = resolve_entry(db, chat_id, label)
    if err:
        await event.edit(err)
        return

    start_note = ""
    if entry.get("stopped") and entry.get("server_identifier"):
        ok, msg = await start_server(entry["server_identifier"])
        start_note = "\n▶️ Server otomatis di-start kembali." if ok else f"\n⚠️ Gagal auto-start: {msg}"

    new_due = add_one_month(date.fromisoformat(entry["next_due"]))
    entry["next_due"] = new_due.isoformat()
    entry["last_reminded"] = None
    entry["active"] = True
    entry["stopped"] = False
    db[key] = entry
    await save_db(db)

    await event.edit(
        f"✅ Tagihan **{entry['label']}** dicatat lunas.\n"
        f"📅 Tagihan berikutnya: {new_due.strftime('%d %B %Y')} ({format_rupiah(entry['nominal'])})"
        f"{start_note}"
    )


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{PREFIX}hapus-tagihan(?:\s+([\w\-]+))?$"))
async def hapus_tagihan_handler(event):
    label = event.pattern_match.group(1)
    chat_id = event.chat_id
    db = await load_db()
    key, entry, err = resolve_entry(db, chat_id, label)
    if err:
        await event.edit(err)
        return
    del db[key]
    await save_db(db)
    await event.edit(f"🗑️ Tagihan **{entry['label']}** untuk chat ini sudah dihapus.")


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{PREFIX}tagihan-sini$"))
async def tagihan_sini_handler(event):
    db = await load_db()
    entries = chat_entries(db, event.chat_id)
    if not entries:
        await event.edit("📋 Belum ada tagihan untuk chat ini.")
        return

    today = date.today()
    lines = ["📋 **Tagihan Chat Ini**\n"]
    for _, e in sorted(entries, key=lambda kv: kv[1]["next_due"]):
        due = date.fromisoformat(e["next_due"])
        status = "✅ Belum jatuh tempo"
        if due < today:
            status = f"⚠️ Telat {(today - due).days} hari"
        elif due == today:
            status = "🔔 Jatuh tempo hari ini"
        server_note = f" | 🖥️ {e['server_identifier']}" if e.get("server_identifier") else ""
        stopped_note = " | ⏹️ stopped" if e.get("stopped") else ""
        lines.append(f"• **{e['label']}** — {format_rupiah(e['nominal'])} — {due.strftime('%d %b %Y')} ({status}){server_note}{stopped_note}")
    await event.edit("\n".join(lines))


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{PREFIX}list-tagihan$"))
async def list_tagihan_handler(event):
    db = await load_db()
    if not db:
        await event.edit("📋 Belum ada tagihan yang tersimpan.")
        return

    entries = sorted(db.values(), key=lambda e: e["next_due"])
    lines = ["📋 **Daftar Tagihan Aktif**\n"]
    today = date.today()
    for e in entries:
        due = date.fromisoformat(e["next_due"])
        status = "✅ Belum jatuh tempo"
        if due < today:
            status = f"⚠️ Telat {(today - due).days} hari"
        elif due == today:
            status = "🔔 Jatuh tempo hari ini"
        try:
            chat = await client.get_entity(e["chat_id"])
            name = getattr(chat, "first_name", None) or getattr(chat, "title", None) or str(e["chat_id"])
        except Exception:
            name = str(e["chat_id"])
        server_note = f" | 🖥️ {e['server_identifier']}" if e.get("server_identifier") else ""
        stopped_note = " | ⏹️ stopped" if e.get("stopped") else ""
        lines.append(
            f"• **{name}** ({e['label']}) — {format_rupiah(e['nominal'])} — {due.strftime('%d %b %Y')} ({status}){server_note}{stopped_note}"
        )
    await event.edit("\n".join(lines))


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{PREFIX}ping$"))
async def ping_handler(event):
    await event.edit("🏓 Pong! Userbot aktif.")


@client.on(events.NewMessage(outgoing=True, pattern=rf"^\{PREFIX}help$"))
async def help_handler(event):
    text = (
        f"**Userbot {BUSINESS_NAME} - Command List**\n\n"
        f"`{PREFIX}pay <nominal>` - kirim QRIS + tagihan\n"
        f"`{PREFIX}add-tagihan <label> <DDMM> <nominal> [server_identifier]` - set/update tagihan bulanan "
        f"(mis. `{PREFIX}add-tagihan webutama 0205 150000 d3aac351`). Satu chat bisa punya banyak "
        f"tagihan asal label beda.\n"
        f"`{PREFIX}set-server [label] <server_identifier>` - sambungkan tagihan ke server Pterodactyl\n"
        f"`{PREFIX}lunas [label]` - tandai lunas, majukan ke bulan depan, auto-start kalau server sempat di-stop\n"
        f"`{PREFIX}hapus-tagihan [label]` - hapus tagihan\n"
        f"`{PREFIX}tagihan-sini` - lihat semua tagihan di chat ini\n"
        f"`{PREFIX}list-tagihan` - lihat semua tagihan aktif di semua chat\n"
        f"`{PREFIX}stop [label]` / `{PREFIX}start [label]` - stop/start server manual\n"
        f"`{PREFIX}ping` - cek bot hidup\n\n"
        f"ℹ️ `[label]` boleh dikosongkan kalau chat cuma punya 1 tagihan.\n"
        f"Auto-stop: {'✅ aktif' if AUTO_STOP_ENABLED else '❌ nonaktif (isi PTERO_PANEL_URL & PTERO_CLIENT_API_KEY)'}"
    )
    await event.edit(text)


# ==================== BACKGROUND REMINDER LOOP ====================

async def reminder_loop():
    while True:
        try:
            db = await load_db()
            today = date.today()
            today_str = today.isoformat()
            changed = False

            for key, entry in db.items():
                if not entry.get("active", True):
                    continue

                label = entry.get("label", "utama")
                due = date.fromisoformat(entry["next_due"])
                last_reminded = entry.get("last_reminded")
                now_wib = datetime.now(WIB)

                if due == today and last_reminded != today_str:
                    qris_file = get_qris_file()
                    caption = (
                        f"⏰ **Pengingat Tagihan Bulanan ({label})**\n\n"
                        f"💰 Tagihan: {format_rupiah(entry['nominal'])}\n"
                        f"📅 Jatuh tempo: hari ini\n\n"
                        f"Terimakasih sudah menggunakan jasa **{BUSINESS_NAME}**, "
                        f"silahkan lakukan pembayaran ya. Kalau sudah transfer, "
                        f"bisa dikonfirmasi di chat ini 🙏"
                    )
                    if qris_file:
                        await client.send_file(entry["chat_id"], qris_file, caption=caption)
                    else:
                        await client.send_message(entry["chat_id"], caption)
                    entry["last_reminded"] = today_str
                    changed = True

                elif due < today:
                    days_late = (today - due).days

                    # ---- Auto-stop: cek kalau sudah masuk window jam stop WIB ----
                    if (
                        AUTO_STOP_ENABLED
                        and entry.get("server_identifier")
                        and not entry.get("stopped", False)
                        and is_in_suspend_window(now_wib)
                    ):
                        ok, msg = await stop_server(entry["server_identifier"])
                        if ok:
                            entry["stopped"] = True
                            changed = True
                            await client.send_message(
                                entry["chat_id"],
                                f"⏹️ **Layanan Dinonaktifkan Sementara ({label})**\n\n"
                                f"Tagihan sebesar {format_rupiah(entry['nominal'])} belum dibayar "
                                f"hingga jatuh tempo. Server telah di-stop otomatis.\n"
                                f"Silahkan lakukan pembayaran, layanan akan aktif kembali begitu "
                                f"dikonfirmasi lunas 🙏",
                            )
                        else:
                            print(f"[reminder_loop] gagal auto-stop {key}: {msg}")

                    if last_reminded == today_str:
                        continue  # sudah diingatkan hari ini (tapi stop check tetap jalan di atas)

                    if days_late >= GRACE_DAYS:
                        text = (
                            f"⚠️ **Tagihan ({label}) Kamu Sudah Telat {days_late} Hari**\n\n"
                            f"💰 Nominal: {format_rupiah(entry['nominal'])}\n"
                            f"Mohon segera diselesaikan, jika tidak layanan akan "
                            f"segera dinonaktifkan sementara. Terimakasih 🙏"
                        )
                    else:
                        text = (
                            f"🔔 Reminder: tagihan ({label}) kamu sebesar {format_rupiah(entry['nominal'])} "
                            f"sudah lewat jatuh tempo {days_late} hari. Mohon segera dibayar ya 🙏"
                        )
                    await client.send_message(entry["chat_id"], text)
                    entry["last_reminded"] = today_str
                    changed = True

            if changed:
                await save_db(db)

        except Exception as e:
            print(f"[reminder_loop] error: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def main():
    async with client:
        client.loop.create_task(reminder_loop())
        print("Userbot berjalan... (Ctrl+C untuk stop)")
        await client.run_until_disconnected()


if __name__ == "__main__":
    client.loop.run_until_complete(main())
