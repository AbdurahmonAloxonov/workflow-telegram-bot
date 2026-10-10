import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# .env har doim loyiha papkasidan o'qiladi (bot qaysi papkadan ishga tushirilishidan qat'i nazar)
load_dotenv(BASE_DIR / ".env")

log = logging.getLogger("adminbot")

# --- Asosiy sozlamalar (.env faylidan olinadi) ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")


def _parse_ids(env_name: str) -> list:
    return [int(x.strip()) for x in os.getenv(env_name, "").split(",") if x.strip()]


# Rol xodimlarning Telegram user_id lari orqali belgilanadi (.env da to'ldiriladi).
# Bitta user_id faqat bitta ro'yxatda bo'lishi kerak — ustuvorlik:
# BIG_ADMIN > SUPERVISOR (nazoratchi) > MONTAJCHI > ADMIN.
# Hech qaysi ro'yxatda bo'lmagan foydalanuvchi botdan foydalana olmaydi.
BIG_ADMIN_IDS = _parse_ids("BIG_ADMIN_IDS")
SUPERVISOR_IDS = _parse_ids("SUPERVISOR_IDS")
MONTAJCHI_IDS = _parse_ids("MONTAJCHI_IDS")
ADMIN_IDS = _parse_ids("ADMIN_IDS")

# Videolar avtomatik joylanadigan Telegram kanal: @username yoki -100... ID.
# Bo'sh bo'lsa — Telegram'ga ham admin qo'lda joylab, havolasini yuboradi.
# Bot kanalda "Xabar joylash" huquqi bilan admin bo'lishi shart.
_channel = os.getenv("CHANNEL_ID", "").strip()
CHANNEL_ID = (int(_channel) if _channel.lstrip("-").isdigit() else _channel) or None

# Muammolar, e'lonlar yuboriladigan ish guruhi
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID")) if os.getenv("GROUP_CHAT_ID") else None

# Har bir platformada kuniga majburiy story soni
MIN_STORIES_PER_PLATFORM = int(os.getenv("MIN_STORIES_PER_PLATFORM", "3"))

# Montajchi kuniga kamida nechta video tayyorlashi kerak (Montajchi.txt: "kamida 10 ta")
MIN_MONTAJ_VIDEOS = int(os.getenv("MIN_MONTAJ_VIDEOS", "10"))

# Montajchi tayyorlagan, lekin admin hali joylamagan videolar necha kun orqaga qarab ko'rsatiladi
UNPOSTED_LOOKBACK_DAYS = int(os.getenv("UNPOSTED_LOOKBACK_DAYS", "7"))

# Eslatma yuboriladigan vaqtlar (24 soatlik), vergul bilan: 12:00,18:00,21:30
REMINDER_TIMES = [t.strip() for t in os.getenv("REMINDER_TIMES", "12:00,18:00,21:30").split(",") if t.strip()]

# Kunlik PDF hisobot avtomatik yuboriladigan vaqt (24 soatlik).
# 12:00 dan oldingi vaqt (masalan 00:05) berilsa, hisobot OLDINGI kun uchun tuziladi —
# shunda kechki soatlarda bajarilgan ishlar ham hisobotga to'liq kiradi.
REPORT_TIME = os.getenv("REPORT_TIME", "23:00")

TIMEZONE = os.getenv("TIMEZONE", "Asia/Tashkent")
TZ = ZoneInfo(TIMEZONE)

# Nechta daqiqa javob bo'lmasa, boshlangan amal (video, muammo va h.k.) avtomatik bekor qilinadi
CONVERSATION_TIMEOUT_MIN = int(os.getenv("CONVERSATION_TIMEOUT_MIN", "30"))

# Joylash tartibi — texnik topshiriqda belgilangan ketma-ketlik
PLATFORMS = ["Instagram", "TikTok", "YouTube", "Telegram"]

# Har bir platforma uchun post havolasida bo'lishi kerak bo'lgan domenlar
PLATFORM_DOMAINS = {
    "Instagram": ("instagram.com",),
    "TikTok": ("tiktok.com",),
    "YouTube": ("youtube.com", "youtu.be"),
    "Telegram": ("t.me", "telegram.me"),
}

# Video joylashdan oldingi tekshiruv ro'yxati
CHECKLIST_ITEMS = [
    "Video 1 daqiqadan oshmagan",
    "O'g'irlangan kontent emas",
    "Sifat yaxshi (xira/sifatsiz emas)",
    "18+ yoki nomaqbul kontent emas",
    "Kino kodi to'g'ri",
    "Video/musiqa bilan bog'liq mualliflik huquqi muammosi yo'q",
]

# Montajchi videoni "tayyor" deb yuborishdan oldingi tekshiruv (Montajchi.txt talablari)
MONTAJ_CHECKLIST_ITEMS = [
    "9:16 formatda",
    "1 daqiqadan oshmagan",
    "Kinoning eng qiziqarli joyidan (HOOK) olingan",
    "Tiniq, sifatli (4K va yuqori)",
    "Mos musiqa yoki ovoz qo'shilgan",
    "Kino Telegram manzili va kino kodi ko'rsatilgan",
    "Original kino manbasidan olingan (o'g'irlanmagan)",
    "Video va musiqa mualliflik huquqi tekshirilgan",
]

# PDF hisobot uchun shrift fayllari (o'zbekcha belgilarni qo'llab-quvvatlaydi)
FONT_REGULAR = str(BASE_DIR / "assets" / "fonts" / "DejaVuSans.ttf")
FONT_BOLD = str(BASE_DIR / "assets" / "fonts" / "DejaVuSans-Bold.ttf")
# Baza va hisobotlar saqlanadigan papka. Serverda doimiy (persistent) diskka yo'naltiriladi,
# aks holda har qayta joylashda ma'lumotlar o'chib ketadi.
DATA_DIR = Path(os.getenv("DATA_DIR") or BASE_DIR)
REPORTS_DIR = DATA_DIR / "reports"
DB_PATH = str(DATA_DIR / "bot.db")


def compute_role(user_id: int):
    """Rolni .env ro'yxatlaridan aniqlaydi; ro'yxatda bo'lmasa None qaytaradi."""
    if user_id in BIG_ADMIN_IDS:
        return "big_admin"
    if user_id in SUPERVISOR_IDS:
        return "supervisor"
    if user_id in MONTAJCHI_IDS:
        return "montajchi"
    if user_id in ADMIN_IDS:
        return "admin"
    return None


def all_staff_ids() -> dict:
    """{user_id: role} — .env dagi barcha xodimlar."""
    result = {}
    for uid in ADMIN_IDS + MONTAJCHI_IDS + SUPERVISOR_IDS + BIG_ADMIN_IDS:
        result[uid] = compute_role(uid)
    return result


def validate():
    """Ishga tushirishda sozlamalardagi xatolarni logga chiqaradi."""
    problems = []
    lists = {
        "BIG_ADMIN_IDS": BIG_ADMIN_IDS, "SUPERVISOR_IDS": SUPERVISOR_IDS,
        "MONTAJCHI_IDS": MONTAJCHI_IDS, "ADMIN_IDS": ADMIN_IDS,
    }
    seen = {}
    for name, ids in lists.items():
        for uid in ids:
            if uid in seen:
                problems.append(f"{uid} ham {seen[uid]}, ham {name} ro'yxatida — faqat bittasida bo'lishi kerak")
            seen.setdefault(uid, name)
    if not ADMIN_IDS:
        problems.append("ADMIN_IDS bo'sh — adminlar botdan foydalana olmaydi")
    if not BIG_ADMIN_IDS:
        problems.append("BIG_ADMIN_IDS bo'sh — PDF hisobot hech kimga yuborilmaydi")
    if not SUPERVISOR_IDS:
        problems.append("SUPERVISOR_IDS bo'sh — nazoratchi vazifalari vaqtincha Big Admin'ga o'tkazildi")
    if not MONTAJCHI_IDS:
        problems.append("MONTAJCHI_IDS bo'sh — kino kodini montajchi ro'yxati bilan solishtirish o'chirildi")
    for f in (FONT_REGULAR, FONT_BOLD):
        if not Path(f).exists():
            problems.append(f"Shrift fayli topilmadi: {f} — PDF hisobot yaratilmaydi")
    for p in problems:
        log.warning("SOZLAMA: %s", p)
    return problems
