import asyncio
import html
import logging
import re
import warnings
from datetime import time as dtime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ApplicationHandlerStop,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    TypeHandler,
    filters,
)
from telegram.warnings import PTBUserWarning

import config
import db
import report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("fontTools").setLevel(logging.WARNING)  # PDF yaratishda yuzlab keraksiz qator yozadi
log = logging.getLogger("adminbot")
# Suhbatlar foydalanuvchi bo'yicha kuzatiladi (per_message=False) — bu ataylab, ogohlantirish kerak emas
warnings.filterwarnings("ignore", message=".*per_message=False.*", category=PTBUserWarning)

PHOTO_CACHE_DIR = config.REPORTS_DIR / "photo_cache"

# ---- Conversation states ----
CHECKLIST, KINO_KOD, KOD_CONFIRM, CAPTION, POST_LINK = range(5)
PROBLEM_MEDIA, PROBLEM_DESC = range(5, 7)
MONT_KOD, MONT_NOTE = range(7, 9)
NOTE_CATEGORY, NOTE_TEXT = range(9, 11)
PHOTO_WAIT, PHOTO_CAPTION = range(11, 13)
STORY_PLATFORM, STORY_PROOF = range(13, 15)
MONT_CHECKLIST = 15
VIDEO_FILE, TG_CONFIRM = range(16, 18)

# Telegram rasm/video izohi (caption) 1024 belgidan oshmasligi kerak — sarlavha uchun joy qoldiramiz
MAX_DESC_LEN = 800
MAX_KOD_LEN = 50

# ---- Menyu tugmalari ----
BTN_NEW_VIDEO = "🎬 Yangi video"
BTN_STORY = "📖 Story qo'ydim"
BTN_PROBLEM = "⚠️ Muammo haqida xabar"
BTN_REPORT = "📊 Hisobot"
BTN_HELP = "❓ Yordam"

BTN_MONT_VIDEO = "🎬 Video tayyor"

BTN_SCREENSHOT = "📸 Skrinshot qo'shish"
BTN_NOTE = "📝 Eslatma qo'shish"
BTN_OPEN_PROBLEMS = "🗂 Ochiq muammolar"
BTN_SEND_REPORT = "📄 PDF hisobotni yuborish"

MENU_BUTTONS = [
    BTN_NEW_VIDEO, BTN_STORY, BTN_PROBLEM, BTN_REPORT, BTN_HELP, BTN_MONT_VIDEO,
    BTN_SCREENSHOT, BTN_NOTE, BTN_OPEN_PROBLEMS, BTN_SEND_REPORT,
]


def _button(text: str):
    return filters.ChatType.PRIVATE & filters.Regex(f"^{re.escape(text)}$")


MENU_FILTER = filters.Regex("^(" + "|".join(re.escape(b) for b in MENU_BUTTONS) + ")$")
# Suhbat ichida kutilayotgan oddiy matn — menyu tugmalari va buyruqlar bundan chiqarib tashlangan,
# aks holda "📊 Hisobot" kabi tugma matni caption/kino kodi sifatida yozilib qolardi.
TEXT_INPUT = filters.TEXT & ~filters.COMMAND & ~MENU_FILTER
IMAGE_INPUT = filters.PHOTO | filters.Document.IMAGE
# Kutilmagan xabar (masalan, rasm o'rniga matn) — foydalanuvchiga nima kerakligini eslatish uchun
OTHER_INPUT = ~filters.COMMAND & ~MENU_FILTER


# =========================================================
# Rol aniqlash
# =========================================================

def get_role(user_id: int):
    """Rol har doim .env dan olinadi — ro'yxat o'zgarsa, darhol kuchga kiradi."""
    return config.compute_role(user_id)


def is_supervisor_role(role) -> bool:
    return role in ("supervisor", "big_admin")


def supervisor_ids() -> list:
    """Nazoratchi xabarlari kimga boradi. Nazoratchi hali tayinlanmagan bo'lsa — Big Admin'ga."""
    return list(config.SUPERVISOR_IDS or config.BIG_ADMIN_IDS)


def main_menu_keyboard(role):
    if role == "admin":
        rows = [[BTN_NEW_VIDEO], [BTN_STORY, BTN_PROBLEM], [BTN_REPORT, BTN_HELP]]
    elif role == "montajchi":
        rows = [[BTN_MONT_VIDEO], [BTN_PROBLEM], [BTN_REPORT, BTN_HELP]]
    elif role == "supervisor":
        rows = [
            [BTN_SCREENSHOT, BTN_NOTE],
            [BTN_OPEN_PROBLEMS, BTN_SEND_REPORT],
            [BTN_REPORT, BTN_HELP],
        ]
    elif role == "big_admin" and not config.SUPERVISOR_IDS:
        # Nazoratchi tayinlanmaguncha Big Admin uning menyusidan foydalanadi
        rows = [
            [BTN_SCREENSHOT, BTN_NOTE],
            [BTN_OPEN_PROBLEMS, BTN_SEND_REPORT],
            [BTN_REPORT, BTN_HELP],
        ]
    elif role == "big_admin":
        rows = [[BTN_REPORT], [BTN_HELP]]
    else:
        return ReplyKeyboardRemove()
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


ROLE_NAMES = {
    "admin": "Admin",
    "montajchi": "Montajchi",
    "supervisor": "Nazoratchi admin",
    "big_admin": "Big Admin",
}


def esc(value) -> str:
    """Foydalanuvchi kiritgan matnni HTML xabarga xavfsiz qo'yish uchun."""
    return html.escape(str(value) if value is not None else "")


def user_label(user) -> str:
    username = f" (@{user.username})" if user.username else ""
    return esc(user.full_name) + esc(username)


# =========================================================
# Yordamchi funksiyalar
# =========================================================

async def notify(context: ContextTypes.DEFAULT_TYPE, chat_ids, text: str,
                 photo_id: str = None, video_id: str = None, document_id: str = None, reply_markup=None):
    for chat_id in chat_ids:
        try:
            if photo_id:
                await context.bot.send_photo(chat_id, photo_id, caption=text,
                                             parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            elif video_id:
                await context.bot.send_video(chat_id, video_id, caption=text,
                                             parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            elif document_id:
                await context.bot.send_document(chat_id, document_id, caption=text,
                                                parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            else:
                await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML,
                                               reply_markup=reply_markup, disable_web_page_preview=True)
        except Exception as e:
            log.warning("Xabar yuborilmadi (%s): %s", chat_id, e)


def _media_kwargs(media_type: str, file_id: str) -> dict:
    if not file_id:
        return {}
    return {
        "photo": {"photo_id": file_id},
        "video": {"video_id": file_id},
        "document": {"document_id": file_id},
    }.get(media_type, {})


async def notify_supervisors_and_group(context, text, reply_markup=None, **media):
    targets = supervisor_ids()
    if config.GROUP_CHAT_ID:
        targets.append(config.GROUP_CHAT_ID)
    await notify(context, targets, text, reply_markup=reply_markup, **media)


def _abort_pending(context: ContextTypes.DEFAULT_TYPE):
    """Yarim qolgan amalni tozalaydi: tugallanmagan video 'cancelled' deb belgilanadi."""
    video_id = context.user_data.get("video_id")
    if video_id:
        db.set_video_status(video_id, "cancelled")
    context.user_data.clear()


# =========================================================
# Kirish nazorati (barcha xabarlardan oldin ishlaydi)
# =========================================================

async def access_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat or chat.type != chat.PRIVATE:
        return  # guruhdagi tugmalar o'z ichida rolni tekshiradi
    role = get_role(user.id)
    if role is None:
        if update.message and update.message.text and update.message.text.startswith("/start"):
            return  # /start foydalanuvchiga ID sini ko'rsatadi
        if update.callback_query:
            await update.callback_query.answer("Sizda ruxsat yo'q.", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text(
                f"⛔ Siz xodimlar ro'yxatida yo'qsiz.\nID raqamingiz: {user.id}\n"
                "Uni rahbaringizga yuboring.",
                reply_markup=ReplyKeyboardRemove(),
            )
        raise ApplicationHandlerStop
    # Hali /start bosmagan xodimning ismini birinchi xabaridayoq saqlab qo'yamiz (hisobot uchun)
    row = db.get_admin(user.id)
    if row is None or row["full_name"] != user.full_name or row["role"] != role:
        db.upsert_admin(user.id, user.full_name, user.username or "", role)


# =========================================================
# /start, /yordam, /bekor_qilish
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    role = get_role(user.id)
    if role is None:
        await update.message.reply_text(
            f"Assalomu alaykum, {esc(user.full_name)}!\n\n"
            f"Siz hali xodimlar ro'yxatiga qo'shilmagansiz.\n"
            f"ID raqamingiz: <code>{user.id}</code>\n"
            "Shu raqamni rahbaringizga yuboring — u sizni ro'yxatga qo'shadi.",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    db.upsert_admin(user.id, user.full_name, user.username or "", role)
    await update.message.reply_text(
        f"Assalomu alaykum, {esc(user.full_name)}!\n"
        f"Sizning rolingiz: <b>{ROLE_NAMES[role]}</b>\n\n"
        "Quyidagi menyudan foydalaning 👇\n"
        "Boshlangan amalni to'xtatish uchun: /bekor_qilish",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(role),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = get_role(update.effective_user.id)
    n = config.MIN_STORIES_PER_PLATFORM
    texts = {
        "admin": (
            "1️⃣ Har bir videoni joylashdan oldin 6 bandli tekshiruvdan o'tkazing.\n"
            "2️⃣ Tekshiruvdan o'tgan video Instagram → TikTok → YouTube → Telegram tartibida joylanadi: "
            "har biri uchun avval opisaniya, so'ng joylangan postning havolasi yuboriladi.\n"
            + ("   Telegram kanalga videoni bot o'zi joylaydi: kino kodidan keyin videoni botga yuborasiz, "
               "Telegram navbatida esa faqat opisaniya yozib, \"✅ Kanalga joylash\" ni bosasiz.\n"
               if _auto_telegram() else "")
            +
            "3️⃣ Muammo topilsa — joylamang, \"⚠️ Muammo haqida xabar\" orqali darhol xabar bering.\n"
            f"4️⃣ Har platformada kuniga kamida {n} ta Story joylang va har birini skrinshoti bilan botga qayd qiling.\n"
            "5️⃣ Boshlangan amalni to'xtatish: /bekor_qilish"
        ),
        "montajchi": (
            "1️⃣ Har bir tayyor bo'lgan videoni \"🎬 Video tayyor\" orqali qayd qiling: avval talablar "
            "ro'yxatini (9:16, 1 daqiqa, HOOK, sifat, musiqa, kod, copyright) tasdiqlaysiz, keyin kino kodini yozasiz.\n"
            f"🎯 Kunlik me'yor: kamida {config.MIN_MONTAJ_VIDEOS} ta video.\n"
            "2️⃣ Ishda muammo yuzaga kelsa (masalan, material yetmasa) \"⚠️ Muammo haqida xabar\" orqali xabar bering.\n"
            "3️⃣ Boshlangan amalni to'xtatish: /bekor_qilish"
        ),
        "supervisor": (
            "1️⃣ Admin va montajchilarning ishini kuzatib boring — muammo xabarlari va Story skrinshotlari avtomatik keladi.\n"
            "2️⃣ Har bir muammoni \"🗂 Ochiq muammolar\" bo'limidan \"✅ Hal qilindi\" yoki "
            "\"🔺 Big Adminga yuborish\" qiling (oldingi kunlarda ochiq qolganlari ham shu yerda).\n"
            "3️⃣ Kun davomida dalil skrinshotlarini \"📸 Skrinshot qo'shish\" orqali yuklang.\n"
            "4️⃣ Aniqlangan xato yoki qo'shimcha ishlarni \"📝 Eslatma qo'shish\" orqali kiriting.\n"
            "5️⃣ Kun oxirida hisobot avtomatik PDF qilib Big Adminga yuboriladi; "
            "istalgan payt \"📄 PDF hisobotni yuborish\" bilan qo'lda ham yuborishingiz mumkin."
        ),
        "big_admin": (
            "Siz Big Admin sifatida har kuni belgilangan vaqtda (yoki nazoratchi qo'lda yuborganda) "
            "PDF hisobotni va jiddiy (eskalatsiya qilingan) muammolarni olib turasiz.\n"
            "\"📊 Hisobot\" orqali joriy kun holatini istalgan payt matn ko'rinishida ham ko'rishingiz mumkin.\n"
            "/hisobot_pdf — PDF hisobotni darhol olish."
        ),
    }
    await update.message.reply_text(
        texts.get(role, "Yordam matni topilmadi."),
        reply_markup=main_menu_keyboard(role),
    )


async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Suhbat ichidagi /bekor_qilish."""
    _abort_pending(context)
    context.user_data["_cancel_handled"] = update.update_id
    role = get_role(update.effective_user.id)
    await update.message.reply_text("Bekor qilindi.", reply_markup=main_menu_keyboard(role))
    return ConversationHandler.END


async def global_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hech qanday amal boshlanmagan paytdagi /bekor_qilish."""
    if context.user_data.pop("_cancel_handled", None) == update.update_id:
        return  # suhbat o'zi javob berdi
    role = get_role(update.effective_user.id)
    await update.message.reply_text("Bekor qilinadigan amal yo'q.", reply_markup=main_menu_keyboard(role))


async def menu_interrupt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Suhbat o'rtasida boshqa menyu tugmasi bosildi: joriy amal bekor qilinadi,
    bosilgan tugma esa o'z handleri orqali odatdagidek ishlaydi."""
    _abort_pending(context)
    await update.message.reply_text("⛔ Oldingi boshlangan amal bekor qilindi.")
    return ConversationHandler.END


async def restart_interrupt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Suhbat o'rtasida /start bosildi — amal jimgina bekor qilinadi, /start o'zi javob beradi."""
    _abort_pending(context)
    return ConversationHandler.END


async def conv_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _abort_pending(context)
    chat = update.effective_chat
    if chat:
        try:
            await context.bot.send_message(
                chat.id,
                f"⌛ {config.CONVERSATION_TIMEOUT_MIN} daqiqa javob bo'lmagani uchun boshlangan amal bekor qilindi.",
                reply_markup=main_menu_keyboard(get_role(update.effective_user.id)),
            )
        except Exception as e:
            log.warning("Timeout xabari yuborilmadi: %s", e)


def make_conv(entry_button: str, entry_callback, states: dict) -> ConversationHandler:
    states = dict(states)
    states[ConversationHandler.TIMEOUT] = [TypeHandler(Update, conv_timeout)]
    return ConversationHandler(
        entry_points=[MessageHandler(_button(entry_button), entry_callback)],
        states=states,
        fallbacks=[
            CommandHandler("bekor_qilish", conv_cancel),
            CommandHandler("start", restart_interrupt),
            MessageHandler(MENU_FILTER, menu_interrupt),
        ],
        allow_reentry=True,
        conversation_timeout=config.CONVERSATION_TIMEOUT_MIN * 60,
    )


async def _require_role(update: Update, allowed_roles) -> bool:
    role = get_role(update.effective_user.id)
    if role not in allowed_roles:
        await update.message.reply_text("Bu funksiya sizning rolingiz uchun mavjud emas.")
        return False
    return True


def _extract_image(msg):
    """(file_id, media_type) — siqilgan rasm yoki fayl ko'rinishidagi rasm."""
    if msg.photo:
        return msg.photo[-1].file_id, "photo"
    if msg.document and (msg.document.mime_type or "").startswith("image/"):
        return msg.document.file_id, "document"
    return None, None


# =========================================================
# ADMIN: Yangi video (tekshiruv → kino kodi → har platformaga caption + havola)
# =========================================================

def checklist_keyboard(checked: list, items=None, prefix: str = "chk") -> InlineKeyboardMarkup:
    """Tekshiruv ro'yxati tugmalari (admin: chk_*, montajchi: mchk_*)."""
    rows = []
    for i, item in enumerate(items or config.CHECKLIST_ITEMS):
        mark = "✅" if checked[i] else "☑️"
        rows.append([InlineKeyboardButton(f"{mark} {item}", callback_data=f"{prefix}_{i}")])
    rows.append([InlineKeyboardButton("➡️ Tasdiqlash va davom etish", callback_data=f"{prefix}_confirm")])
    rows.append([InlineKeyboardButton("❌ Muammo bor — bekor qilish", callback_data=f"{prefix}_cancel")])
    return InlineKeyboardMarkup(rows)


async def new_video_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _abort_pending(context)
    if not await _require_role(update, ("admin",)):
        return ConversationHandler.END
    context.user_data["checklist"] = [False] * len(config.CHECKLIST_ITEMS)
    await update.message.reply_text(
        "🔍 <b>Videoni tekshirish</b>\nHar bir bandni tasdiqlang:",
        parse_mode=ParseMode.HTML,
        reply_markup=checklist_keyboard(context.user_data["checklist"]),
    )
    return CHECKLIST


async def checklist_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    checked = context.user_data.get("checklist", [False] * len(config.CHECKLIST_ITEMS))

    if data == "chk_cancel":
        await query.answer()
        _abort_pending(context)
        await query.edit_message_text(
            "Video bekor qilindi. Muammo bo'lsa, \"⚠️ Muammo haqida xabar\" orqali nazoratchi adminga xabar bering."
        )
        return ConversationHandler.END

    if data == "chk_confirm":
        if not all(checked):
            await query.answer("Avval barcha bandlarni belgilang!", show_alert=True)
            return CHECKLIST
        await query.answer()
        await query.edit_message_text(
            "✅ Tekshiruv yakunlandi.\n\nEndi ushbu video uchun <b>kino kodini</b> kiriting:",
            parse_mode=ParseMode.HTML,
        )
        return KINO_KOD

    await query.answer()
    idx = int(data.split("_")[1])
    checked[idx] = not checked[idx]
    context.user_data["checklist"] = checked
    await query.edit_message_reply_markup(reply_markup=checklist_keyboard(checked))
    return CHECKLIST


def _kod_warnings(kino_kod: str) -> list:
    warnings = []
    dups = db.find_posted_videos_by_kod(kino_kod)
    if dups:
        items = "; ".join(f"{d['full_name'] or 'ID ' + str(d['admin_id'])} — {d['created_at'][:16].replace('T', ' ')}"
                          for d in dups[-3:])
        warnings.append(f"Bu kod bilan video avval {len(dups)} marta joylangan ({items})")
    if config.MONTAJCHI_IDS and not db.montajchi_kod_exists(kino_kod):
        warnings.append("Montajchi bu kodli videoni tayyorlangan deb qayd etmagan")
    return warnings


async def kino_kod_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kino_kod = update.message.text.strip()
    if not kino_kod or len(kino_kod) > MAX_KOD_LEN:
        await update.message.reply_text(f"Kino kodi 1–{MAX_KOD_LEN} belgidan iborat bo'lishi kerak. Qayta kiriting:")
        return KINO_KOD
    context.user_data["kino_kod"] = kino_kod

    warnings = _kod_warnings(kino_kod)
    context.user_data["kod_warnings"] = warnings
    if warnings:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➡️ Baribir davom etish", callback_data="kod_ok")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="kod_cancel")],
        ])
        await update.message.reply_text(
            f"⚠️ <b>Diqqat, kino kodi: {esc(kino_kod)}</b>\n"
            + "\n".join(f"• {esc(w)}" for w in warnings)
            + "\n\nKod to'g'rimi? Davom etsangiz, bu ogohlantirish nazoratchiga ham yuboriladi.\n"
              "Kodni to'g'rilash uchun yangi kodni shunchaki yozib yuboring.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
        return KOD_CONFIRM
    return await _begin_posting(update.message, context)


async def kod_confirm_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "kod_cancel":
        _abort_pending(context)
        await query.edit_message_text("Video bekor qilindi.")
        return ConversationHandler.END
    await query.edit_message_reply_markup(reply_markup=None)
    return await _begin_posting(query.message, context)


TELEGRAM = "Telegram"
MAX_TG_CAPTION = 1024  # Telegram video izohi chegarasi


def _auto_telegram() -> bool:
    """Telegram kanalga bot o'zi joylaydimi (CHANNEL_ID sozlangan bo'lsa)."""
    return bool(config.CHANNEL_ID) and TELEGRAM in config.PLATFORMS


async def _ask_caption(message, context: ContextTypes.DEFAULT_TYPE):
    platform = config.PLATFORMS[context.user_data["platform_idx"]]
    extra = ""
    if platform == TELEGRAM and _auto_telegram():
        extra = "\n(Bu safar kanalga video bilan birga <b>bot o'zi joylaydi</b> — siz faqat opisaniyani yozing.)"
    await message.reply_text(
        f"📲 <b>{platform}</b> uchun opisaniya (caption) matnini yuboring:{extra}",
        parse_mode=ParseMode.HTML,
    )
    return CAPTION


async def _begin_posting(message, context: ContextTypes.DEFAULT_TYPE):
    kino_kod = context.user_data["kino_kod"]
    context.user_data["video_id"] = db.create_video(message.chat_id, kino_kod)
    context.user_data["platform_idx"] = 0
    if _auto_telegram():
        await message.reply_text(
            f"Kino kodi qabul qilindi: <b>{esc(kino_kod)}</b>\n\n"
            "🎞 Endi <b>videoning o'zini</b> yuboring — Telegram kanalga uni bot o'zi joylaydi.",
            parse_mode=ParseMode.HTML,
        )
        return VIDEO_FILE
    await message.reply_text(
        f"Kino kodi qabul qilindi: <b>{esc(kino_kod)}</b>\n\nEndi platformalarga tartib bilan joylaymiz.",
        parse_mode=ParseMode.HTML,
    )
    return await _ask_caption(message, context)


async def video_file_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.video:
        hint = ""
        if msg.document and (msg.document.mime_type or "").startswith("video/"):
            hint = " Siz uni fayl qilib yubordingiz — oddiy video sifatida yuboring."
        await msg.reply_text(f"Iltimos, videoni yuboring (yoki /bekor_qilish).{hint}")
        return VIDEO_FILE
    context.user_data["video_file_id"] = msg.video.file_id
    db.set_video_file(context.user_data["video_id"], msg.video.file_id)
    await msg.reply_text("✅ Video qabul qilindi. Endi platformalarga tartib bilan joylaymiz.")
    return await _ask_caption(msg, context)


async def caption_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    caption = msg.text.strip()
    platform = config.PLATFORMS[context.user_data.get("platform_idx", 0)]
    context.user_data["pending_caption"] = caption

    if platform == TELEGRAM and _auto_telegram() and context.user_data.get("video_file_id"):
        if len(msg.text) > MAX_TG_CAPTION:
            await msg.reply_text(
                f"Telegram'da video izohi {MAX_TG_CAPTION} belgidan oshmasligi kerak "
                f"(sizniki {len(msg.text)}). Qisqartirib qayta yuboring:"
            )
            return CAPTION
        # Admin yozgan formatlash (qalin, havola va h.k.) kanalda ham saqlansin
        context.user_data["pending_entities"] = list(msg.entities or [])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Kanalga joylash", callback_data="tgpost_ok")],
            [InlineKeyboardButton("✏️ Opisaniyani o'zgartirish", callback_data="tgpost_edit")],
        ])
        await msg.reply_text("👇 Kanalda shunday ko'rinadi. Tekshirib, joylashni tasdiqlang:")
        await context.bot.send_video(
            msg.chat_id, context.user_data["video_file_id"],
            caption=msg.text, caption_entities=msg.entities or None, reply_markup=kb,
        )
        return TG_CONFIRM

    await msg.reply_text(
        f"🔗 Endi <b>{platform}</b>ga joylangan postning <b>havolasini</b> (link) yuboring:",
        parse_mode=ParseMode.HTML,
    )
    return POST_LINK


async def tg_confirm_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Tugmalarni darhol olib tashlaymiz — ikki marta bosilib, kanalga ikki marta tushmasin
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    if query.data == "tgpost_edit":
        await query.message.reply_text("✏️ Yangi opisaniyani yuboring:")
        return CAPTION

    user = update.effective_user
    try:
        posted = await context.bot.send_video(
            config.CHANNEL_ID, context.user_data["video_file_id"],
            caption=context.user_data.get("pending_caption", ""),
            caption_entities=context.user_data.get("pending_entities") or None,
        )
    except Exception as e:
        log.warning("Kanalga joylab bo'lmadi (%s): %s", config.CHANNEL_ID, e)
        await query.message.reply_text(
            f"❌ Kanalga avtomatik joylab bo'lmadi: {e}\n\n"
            "Videoni kanalga qo'lda joylang va postning havolasini yuboring. "
            "(Bot egasiga ayting: bot kanalda admin bo'lishi kerak.)"
        )
        return POST_LINK

    url = posted.link or ""
    await query.message.reply_text(f"📢 Kanalga joylandi: {url}", disable_web_page_preview=True)
    return await _record_and_advance(query.message, context, user, url)


def _valid_platform_url(url: str, platform: str) -> bool:
    if not re.match(r"^https?://\S+$", url):
        return False
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in config.PLATFORM_DOMAINS.get(platform, ()))


async def link_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    platform = config.PLATFORMS[context.user_data.get("platform_idx", 0)]
    if not _valid_platform_url(url, platform):
        domains = ", ".join(config.PLATFORM_DOMAINS.get(platform, ()))
        await update.message.reply_text(
            f"❗ Bu {platform} havolasiga o'xshamaydi. Havola https:// bilan boshlanib, "
            f"{domains} manzilida bo'lishi kerak. Qayta yuboring:",
            disable_web_page_preview=True,
        )
        return POST_LINK
    await update.message.reply_text(f"✅ {platform} uchun qayd qilindi.")
    return await _record_and_advance(update.message, context, update.effective_user, url)


async def _record_and_advance(message, context: ContextTypes.DEFAULT_TYPE, user, url: str):
    """Joriy platformadagi postni yozadi va keyingi platformaga o'tadi (yoki videoni yakunlaydi)."""
    idx = context.user_data.get("platform_idx", 0)
    platform = config.PLATFORMS[idx]
    video_id = context.user_data["video_id"]
    db.add_post(video_id, user.id, platform, context.user_data.pop("pending_caption", ""), url)
    context.user_data.pop("pending_entities", None)
    context.user_data.setdefault("links", {})[platform] = url

    idx += 1
    if idx < len(config.PLATFORMS):
        context.user_data["platform_idx"] = idx
        return await _ask_caption(message, context)

    db.set_video_status(video_id, "posted")
    await message.reply_text(
        "🎉 Video barcha platformalarga (Instagram → TikTok → YouTube → Telegram) muvaffaqiyatli joylandi!",
        reply_markup=main_menu_keyboard("admin"),
    )
    links = context.user_data.get("links", {})
    text = (
        f"✅ <b>{esc(user.full_name)}</b> yangi videoni barcha platformalarga joyladi.\n"
        f"🎬 Kino kodi: <code>{esc(context.user_data.get('kino_kod', ''))}</code>\n"
        + "\n".join(f"• <a href=\"{esc(links[p])}\">{p}</a>" for p in config.PLATFORMS if links.get(p))
    )
    warnings = context.user_data.get("kod_warnings") or []
    if warnings:
        text += "\n\n⚠️ <b>Ogohlantirish (admin baribir davom etdi):</b>\n" + "\n".join(f"• {esc(w)}" for w in warnings)
    await notify_supervisors_and_group(context, text)
    context.user_data.clear()  # video tugallandi — _abort_pending chaqirilmaydi
    return ConversationHandler.END


new_video_conv = make_conv(BTN_NEW_VIDEO, new_video_start, {
    CHECKLIST: [CallbackQueryHandler(checklist_toggle, pattern=r"^chk_")],
    KINO_KOD: [MessageHandler(TEXT_INPUT, kino_kod_received)],
    KOD_CONFIRM: [
        CallbackQueryHandler(kod_confirm_chosen, pattern=r"^kod_"),
        MessageHandler(TEXT_INPUT, kino_kod_received),
    ],
    VIDEO_FILE: [MessageHandler(OTHER_INPUT, video_file_received)],
    CAPTION: [MessageHandler(TEXT_INPUT, caption_received)],
    TG_CONFIRM: [
        CallbackQueryHandler(tg_confirm_chosen, pattern=r"^tgpost_"),
        MessageHandler(TEXT_INPUT, caption_received),  # tugma o'rniga yangi matn = yangi opisaniya
    ],
    POST_LINK: [MessageHandler(TEXT_INPUT, link_received)],
})


# =========================================================
# ADMIN: Story (platforma → skrinshot)
# =========================================================

def story_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(p, callback_data=f"storyp_{p}")] for p in config.PLATFORMS]
    return InlineKeyboardMarkup(rows)


async def story_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _abort_pending(context)
    if not await _require_role(update, ("admin",)):
        return ConversationHandler.END
    await update.message.reply_text("Qaysi platformaga Story joyladingiz?", reply_markup=story_keyboard())
    return STORY_PLATFORM


async def story_platform_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    platform = query.data.split("_", 1)[1]
    if platform not in config.PLATFORMS:
        return STORY_PLATFORM
    context.user_data["story_platform"] = platform
    await query.edit_message_text(f"📸 {platform}dagi Story'ning skrinshotini yuboring (dalil sifatida):")
    return STORY_PROOF


async def story_proof_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id, media_type = _extract_image(update.message)
    if not file_id:
        await update.message.reply_text("Iltimos, Story skrinshotini rasm ko'rinishida yuboring (yoki /bekor_qilish).")
        return STORY_PROOF

    user = update.effective_user
    platform = context.user_data.get("story_platform")
    db.add_story(user.id, platform, file_id)
    total = db.count_stories_today(user.id, platform)
    target = config.MIN_STORIES_PER_PLATFORM
    status = "✅ bajarildi" if total >= target else f"yana {target - total} ta kerak"
    await update.message.reply_text(
        f"📖 {platform} uchun Story qayd qilindi.\nBugungi hisob: {total}/{target} ({status})",
        reply_markup=main_menu_keyboard("admin"),
    )
    await notify(
        context, supervisor_ids(),
        f"📖 <b>{esc(user.full_name)}</b> — {platform} Story ({total}/{target})",
        **_media_kwargs(media_type, file_id),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def story_wrong_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Iltimos, Story skrinshotini rasm ko'rinishida yuboring (yoki /bekor_qilish).")
    return STORY_PROOF


story_conv = make_conv(BTN_STORY, story_start, {
    STORY_PLATFORM: [CallbackQueryHandler(story_platform_chosen, pattern=r"^storyp_")],
    STORY_PROOF: [
        MessageHandler(IMAGE_INPUT, story_proof_received),
        MessageHandler(OTHER_INPUT, story_wrong_input),
    ],
})


# =========================================================
# ADMIN / MONTAJCHI: Muammo haqida xabar
# =========================================================

async def problem_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _abort_pending(context)
    if not await _require_role(update, ("admin", "montajchi")):
        return ConversationHandler.END
    await update.message.reply_text(
        "⚠️ Muammoni tasvirlovchi <b>skrinshot yoki video</b> yuboring (dalil sifatida):",
        parse_mode=ParseMode.HTML,
    )
    return PROBLEM_MEDIA


async def problem_media_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.photo:
        file_id, media_type = msg.photo[-1].file_id, "photo"
    elif msg.video:
        file_id, media_type = msg.video.file_id, "video"
    elif msg.document and (msg.document.mime_type or "").startswith(("image/", "video/")):
        file_id, media_type = msg.document.file_id, "document"
    else:
        await msg.reply_text("Iltimos, skrinshot (rasm) yoki video yuboring (yoki /bekor_qilish).")
        return PROBLEM_MEDIA
    context.user_data["problem_media"] = file_id
    context.user_data["problem_media_type"] = media_type
    await msg.reply_text("Endi muammoni qisqacha tavsiflab bering (matn):")
    return PROBLEM_DESC


def problem_keyboard(problem_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Hal qilindi", callback_data=f"resolve_{problem_id}"),
        InlineKeyboardButton("🔺 Big Adminga yuborish", callback_data=f"escalate_{problem_id}"),
    ]])


async def problem_desc_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    description = update.message.text.strip()
    if len(description) > MAX_DESC_LEN:
        await update.message.reply_text(
            f"Tavsif juda uzun ({len(description)} belgi). {MAX_DESC_LEN} belgigacha qisqartirib qayta yuboring:"
        )
        return PROBLEM_DESC

    media_id = context.user_data.get("problem_media")
    media_type = context.user_data.get("problem_media_type")
    problem_id = db.add_problem(user.id, description, media_id, media_type)
    role = get_role(user.id)

    text = (
        f"⚠️ <b>Muammo haqida xabar</b> #{problem_id}\n"
        f"👤 {ROLE_NAMES.get(role, 'Xodim')}: {user_label(user)}\n"
        f"📝 Tavsif: {esc(description)}"
    )
    await notify_supervisors_and_group(
        context, text, reply_markup=problem_keyboard(problem_id), **_media_kwargs(media_type, media_id)
    )
    await update.message.reply_text(
        "Xabaringiz nazoratchi adminga va guruhga yuborildi. Rahmat!",
        reply_markup=main_menu_keyboard(role),
    )
    context.user_data.clear()
    return ConversationHandler.END


problem_conv = make_conv(BTN_PROBLEM, problem_start, {
    PROBLEM_MEDIA: [MessageHandler(OTHER_INPUT, problem_media_received)],
    PROBLEM_DESC: [MessageHandler(TEXT_INPUT, problem_desc_received)],
})


STATUS_TEXT = {"resolved": "✅ hal qilingan", "escalated": "🔺 Big Adminga yuborilgan"}


async def resolve_or_escalate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if not is_supervisor_role(get_role(user.id)):
        await query.answer("Bu amal faqat nazoratchi admin uchun.", show_alert=True)
        return

    action, pid = query.data.split("_", 1)
    pid = int(pid)
    problem = db.get_problem(pid)
    if not problem:
        await query.answer("Muammo topilmadi.", show_alert=True)
        return

    new_status = "resolved" if action == "resolve" else "escalated"
    if not db.close_problem(pid, new_status, user.id):
        # Boshqa nazoratchi (yoki boshqa xabar nusxasi orqali) allaqachon yopilgan
        problem = db.get_problem(pid)
        resolver = db.display_name(db.get_admin(problem["resolved_by"])) if problem["resolved_by"] else "—"
        await query.answer(
            f"Bu muammo allaqachon {STATUS_TEXT.get(problem['status'], problem['status'])} ({resolver}).",
            show_alert=True,
        )
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return
    await query.answer()

    if new_status == "resolved":
        suffix = f"\n\n✅ <b>{esc(user.full_name)}</b> tomonidan hal qilindi."
    else:
        suffix = f"\n\n🔺 <b>{esc(user.full_name)}</b> tomonidan Big Adminga yuborildi."
        reporter_name = db.display_name(db.get_admin(problem["admin_id"]))
        escalate_text = (
            f"🔺 <b>Eskalatsiya qilingan muammo</b> #{pid}\n"
            f"👤 Xodim: {esc(reporter_name)}\n"
            f"📝 Tavsif: {esc(problem['description'])}\n"
            f"Yubordi: {esc(user.full_name)} (nazoratchi admin)"
        )
        await notify(context, config.BIG_ADMIN_IDS, escalate_text,
                     **_media_kwargs(problem["media_type"], problem["media_file_id"]))

    # Asl formatlash (qalin matn va h.k.) saqlanishi uchun *_html dan foydalanamiz
    try:
        msg = query.message
        if msg.caption is not None:
            await query.edit_message_caption(caption=(msg.caption_html or "") + suffix, parse_mode=ParseMode.HTML)
        else:
            await query.edit_message_text((msg.text_html or "") + suffix, parse_mode=ParseMode.HTML)
    except Exception as e:
        log.warning("Muammo xabari tahrirlanmadi (#%s): %s", pid, e)


# =========================================================
# MONTAJCHI: Video tayyor
# =========================================================

async def mont_video_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _abort_pending(context)
    if not await _require_role(update, ("montajchi",)):
        return ConversationHandler.END
    context.user_data["mont_checklist"] = [False] * len(config.MONTAJ_CHECKLIST_ITEMS)
    await update.message.reply_text(
        "🔍 <b>Videoni yuborishdan oldin tekshiring</b>\nHar bir bandni tasdiqlang:",
        parse_mode=ParseMode.HTML,
        reply_markup=checklist_keyboard(context.user_data["mont_checklist"],
                                        config.MONTAJ_CHECKLIST_ITEMS, "mchk"),
    )
    return MONT_CHECKLIST


async def mont_checklist_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    checked = context.user_data.get("mont_checklist", [False] * len(config.MONTAJ_CHECKLIST_ITEMS))

    if data == "mchk_cancel":
        await query.answer()
        _abort_pending(context)
        await query.edit_message_text(
            "Bekor qilindi. Talablarga javob bermaydigan video \"tayyor\" deb yuborilmaydi — "
            "avval kamchilikni tuzating. Yordam kerak bo'lsa, \"⚠️ Muammo haqida xabar\" orqali yozing."
        )
        return ConversationHandler.END

    if data == "mchk_confirm":
        if not all(checked):
            await query.answer("Avval barcha bandlarni belgilang!", show_alert=True)
            return MONT_CHECKLIST
        await query.answer()
        await query.edit_message_text(
            "✅ Tekshiruv yakunlandi.\n\n🎬 Endi videoning <b>kino kodini</b> yuboring:",
            parse_mode=ParseMode.HTML,
        )
        return MONT_KOD

    await query.answer()
    idx = int(data.split("_")[1])
    checked[idx] = not checked[idx]
    context.user_data["mont_checklist"] = checked
    await query.edit_message_reply_markup(
        reply_markup=checklist_keyboard(checked, config.MONTAJ_CHECKLIST_ITEMS, "mchk"))
    return MONT_CHECKLIST


async def mont_kod_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kod = update.message.text.strip()
    if not kod or len(kod) > MAX_KOD_LEN:
        await update.message.reply_text(f"Kino kodi 1–{MAX_KOD_LEN} belgidan iborat bo'lishi kerak. Qayta kiriting:")
        return MONT_KOD
    context.user_data["mont_kod"] = kod
    extra = "\n⚠️ Diqqat: bu kod avval ham qayd etilgan." if db.montajchi_kod_exists(kod) else ""
    await update.message.reply_text(f"Izoh bo'lsa yozing (bo'lmasa \"-\" yuboring):{extra}")
    return MONT_NOTE


async def mont_note_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = update.message.text.strip()
    note = "" if note == "-" else note
    user = update.effective_user
    kod = context.user_data.get("mont_kod", "")
    db.add_montajchi_video(user.id, kod, note)
    total = db.count_montajchi_videos_today(user.id)
    target = config.MIN_MONTAJ_VIDEOS
    status = "🎉 kunlik me'yor bajarildi!" if total >= target else f"me'yorgacha yana {target - total} ta"
    await update.message.reply_text(
        f"✅ Qayd etildi. Bugun: <b>{total}/{target}</b> ta video ({status})",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard("montajchi"),
    )
    context.user_data.clear()
    return ConversationHandler.END


mont_video_conv = make_conv(BTN_MONT_VIDEO, mont_video_start, {
    MONT_CHECKLIST: [CallbackQueryHandler(mont_checklist_toggle, pattern=r"^mchk_")],
    MONT_KOD: [MessageHandler(TEXT_INPUT, mont_kod_received)],
    MONT_NOTE: [MessageHandler(TEXT_INPUT, mont_note_received)],
})


# =========================================================
# NAZORATCHI: Skrinshot qo'shish, Eslatma qo'shish, Ochiq muammolar
# =========================================================

async def screenshot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _abort_pending(context)
    if not await _require_role(update, ("supervisor", "big_admin")):
        return ConversationHandler.END
    await update.message.reply_text("📸 Hisobot uchun skrinshot (rasm) yuboring:")
    return PHOTO_WAIT


async def screenshot_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id, _ = _extract_image(update.message)
    if not file_id:
        await update.message.reply_text("Iltimos, skrinshotni rasm ko'rinishida yuboring (yoki /bekor_qilish).")
        return PHOTO_WAIT
    context.user_data["shot_file_id"] = file_id
    await update.message.reply_text("Izoh yozing (bo'lmasa \"-\" yuboring):")
    return PHOTO_CAPTION


async def screenshot_caption_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = update.message.text.strip()
    caption = "" if caption == "-" else caption
    user = update.effective_user
    db.add_report_photo(user.id, context.user_data.get("shot_file_id"), caption)
    await update.message.reply_text(
        "✅ Skrinshot kunlik hisobotga qo'shildi.",
        reply_markup=main_menu_keyboard(get_role(user.id)),
    )
    context.user_data.clear()
    return ConversationHandler.END


screenshot_conv = make_conv(BTN_SCREENSHOT, screenshot_start, {
    PHOTO_WAIT: [MessageHandler(OTHER_INPUT, screenshot_photo_received)],
    PHOTO_CAPTION: [MessageHandler(TEXT_INPUT, screenshot_caption_received)],
})


async def note_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _abort_pending(context)
    if not await _require_role(update, ("supervisor", "big_admin")):
        return ConversationHandler.END
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Aniqlangan xato", callback_data="note_xato")],
        [InlineKeyboardButton("📌 Boshqa bajarilgan ish", callback_data="note_boshqa")],
    ])
    await update.message.reply_text("Yozuv turini tanlang:", reply_markup=kb)
    return NOTE_CATEGORY


async def note_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.split("_", 1)[1]
    context.user_data["note_category"] = category
    label = "aniqlangan xato" if category == "xato" else "bajarilgan boshqa ish"
    await query.edit_message_text(f"Matn kiriting ({label}):")
    return NOTE_TEXT


async def note_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    category = context.user_data.get("note_category", "boshqa")
    db.add_report_note(user.id, category, update.message.text.strip())
    await update.message.reply_text(
        "✅ Kunlik hisobotga qo'shildi.",
        reply_markup=main_menu_keyboard(get_role(user.id)),
    )
    context.user_data.clear()
    return ConversationHandler.END


note_conv = make_conv(BTN_NOTE, note_start, {
    NOTE_CATEGORY: [CallbackQueryHandler(note_category_chosen, pattern=r"^note_")],
    NOTE_TEXT: [MessageHandler(TEXT_INPUT, note_text_received)],
})


async def open_problems(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_role(update, ("supervisor", "big_admin")):
        return
    problems = db.open_problems()
    if not problems:
        await update.message.reply_text("Ochiq (hal qilinmagan) muammolar yo'q. 👍")
        return
    await update.message.reply_text(f"🗂 Ochiq muammolar: {len(problems)} ta")
    today = db.today().isoformat()
    for p in problems:
        who = p["full_name"] or f"ID {p['admin_id']}"
        day = p["created_at"][:10]
        when = p["created_at"][11:16] if day == today else f"{day} {p['created_at'][11:16]}"
        text = f"#{p['id']} · 🕒 {when}\n👤 {who}\n📝 {p['description']}"
        kb = problem_keyboard(p["id"])
        try:
            if p["media_type"] == "photo" and p["media_file_id"]:
                await update.message.reply_photo(p["media_file_id"], caption=text, reply_markup=kb)
            elif p["media_type"] == "video" and p["media_file_id"]:
                await update.message.reply_video(p["media_file_id"], caption=text, reply_markup=kb)
            elif p["media_type"] == "document" and p["media_file_id"]:
                await update.message.reply_document(p["media_file_id"], caption=text, reply_markup=kb)
            else:
                await update.message.reply_text(text, reply_markup=kb)
        except Exception as e:
            log.warning("Muammo #%s ko'rsatilmadi: %s", p["id"], e)
            await update.message.reply_text(text + "\n(dalil faylini yuklab bo'lmadi)", reply_markup=kb)


# =========================================================
# Hisobot (matnli, tezkor ko'rinish)
# =========================================================

def _unposted_lines(limit: int = 15) -> list:
    """Montajchi tayyorlagan, lekin hali joylanmagan kodlar (matnli hisobot uchun)."""
    rows = db.unposted_montajchi_videos()
    if not rows:
        return []
    today = db.today().isoformat()
    items = []
    for r in rows[:limit]:
        day = r["created_at"][:10]
        items.append(esc(r["kino_kod"]) + ("" if day == today else f" ({day[5:]})"))
    more = f" … va yana {len(rows) - limit} ta" if len(rows) > limit else ""
    return [f"⏳ <b>Tayyor, lekin joylanmagan: {len(rows)} ta</b>", "   " + ", ".join(items) + more, ""]


async def report_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    role = get_role(user.id)
    lines = ["📊 <b>Bugungi hisobot</b>\n"]

    if is_supervisor_role(role):
        montajchilar = db.all_admins(role="montajchi")
        if montajchilar:
            lines.append("🎬 <b>Montajchi</b>")
            for m in montajchilar:
                n = db.count_montajchi_videos_today(m["user_id"])
                flag = "✅" if n >= config.MIN_MONTAJ_VIDEOS else "⚠️"
                lines.append(f"   {flag} {esc(db.display_name(m))}: {n}/{config.MIN_MONTAJ_VIDEOS} ta video")
            lines.append("")

        adminlar = db.all_admins(role="admin")
        if adminlar:
            lines.append("📲 <b>Adminlar</b>")
            for a in adminlar:
                videos = db.count_videos_today(a["user_id"])
                stories = db.story_counts_today(a["user_id"])
                story_line = ", ".join(
                    f"{p}: {stories.get(p, 0)}/{config.MIN_STORIES_PER_PLATFORM}" for p in config.PLATFORMS
                )
                under = any(stories.get(p, 0) < config.MIN_STORIES_PER_PLATFORM for p in config.PLATFORMS)
                flag = "⚠️" if under else "✅"
                lines.append(f"   {flag} {esc(db.display_name(a))}: {videos} video | {story_line}")
            lines.append("")

        lines.extend(_unposted_lines())
        total_count = len(db.problems_today())
        open_all = len(db.open_problems())
        older_open = len(db.open_problems_before())
        line = f"⚠️ Bugungi muammolar: {total_count} ta | Jami ochiq: {open_all} ta"
        if older_open:
            line += f" (shundan {older_open} tasi oldingi kunlardan)"
        lines.append(line)

    elif role == "montajchi":
        total = db.count_montajchi_videos_today(user.id)
        lines.append(f"🎬 Bugun tayyorlagan videolaringiz: <b>{total}/{config.MIN_MONTAJ_VIDEOS}</b> ta")

    else:  # admin
        videos = db.count_videos_today(user.id)
        stories = db.story_counts_today(user.id)
        story_line = ", ".join(
            f"{p}: {stories.get(p, 0)}/{config.MIN_STORIES_PER_PLATFORM}" for p in config.PLATFORMS
        )
        problems = db.count_problems_today(user.id)
        lines.append(f"🎬 Joylangan videolar: {videos}")
        lines.append(f"📖 Storylar: {story_line}")
        lines.append(f"⚠️ Muammolar: {problems}")
        lines.append("")
        lines.extend(_unposted_lines())

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# =========================================================
# PDF hisobotni yig'ish va yuborish
# =========================================================

async def _download_photos(context: ContextTypes.DEFAULT_TYPE, day):
    PHOTO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for ph in db.report_photos_today(day):
        local_path = PHOTO_CACHE_DIR / f"{ph['file_id']}.jpg"
        if local_path.exists():
            continue
        try:
            file = await context.bot.get_file(ph["file_id"])
            await file.download_to_drive(str(local_path))
        except Exception as e:
            log.warning("Skrinshot yuklab olinmadi: %s", e)


async def generate_and_send_report(context: ContextTypes.DEFAULT_TYPE, generated_by_name: str, day=None):
    """PDF yaratadi va Big Adminlarga yuboradi. (pdf_path, yetkazilganlar soni) qaytaradi."""
    day = day or db.today()
    await _download_photos(context, day)
    # PDF yaratish sekin bo'lishi mumkin — botni to'xtatib qo'ymasligi uchun alohida oqimda
    pdf_path = await asyncio.to_thread(report.build_daily_report, generated_by_name, day, PHOTO_CACHE_DIR)

    sent = 0
    for chat_id in config.BIG_ADMIN_IDS:
        try:
            with open(pdf_path, "rb") as f:
                await context.bot.send_document(
                    chat_id, f, filename=f"hisobot_{day.isoformat()}.pdf",
                    caption=f"📄 Kunlik hisobot ({day.isoformat()}) — tayyorladi: {generated_by_name}",
                )
            sent += 1
        except Exception as e:
            log.warning("PDF yuborilmadi (%s): %s", chat_id, e)
    if not config.BIG_ADMIN_IDS:
        log.warning("BIG_ADMIN_IDS sozlanmagan — PDF hech kimga yuborilmadi.")
    return pdf_path, sent


async def send_report_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_role(update, ("supervisor", "big_admin")):
        return
    await update.message.reply_text("⏳ Hisobot tayyorlanmoqda...")
    try:
        pdf_path, sent = await generate_and_send_report(context, update.effective_user.full_name)
    except Exception:
        log.exception("PDF hisobot yaratilmadi")
        await update.message.reply_text("❌ PDF hisobotni yaratishda xatolik yuz berdi. Bot logini tekshiring.")
        return

    total = len(config.BIG_ADMIN_IDS)
    if total and sent == total:
        await update.message.reply_text("✅ PDF hisobot Big Adminga yuborildi.")
    else:
        await update.message.reply_text(
            f"⚠️ PDF yaratildi, lekin {total} ta Big Admindan faqat {sent} tasiga yetkazildi "
            "(Big Admin botga /start bosmagan bo'lishi mumkin). Fayl sizga yuborilmoqda:"
        )
        with open(pdf_path, "rb") as f:
            await update.message.reply_document(f, filename=Path(pdf_path).name)


async def auto_report_job(context: ContextTypes.DEFAULT_TYPE):
    # 12:00 dan oldin ishlasa (masalan REPORT_TIME=00:05) — kechagi kun hisoboti
    now = db.now()
    day = now.date() if now.hour >= 12 else now.date() - timedelta(days=1)
    try:
        await generate_and_send_report(context, "Avtomatik (bot)", day)
    except Exception:
        log.exception("Avtomatik PDF hisobot yaratilmadi")
        await notify(context, supervisor_ids(),
                     "❌ Avtomatik PDF hisobotni yaratib bo'lmadi. \"📄 PDF hisobotni yuborish\" orqali qayta urinib ko'ring.")


# =========================================================
# Eslatmalar (JobQueue) — story me'yori va ochiq muammolar
# =========================================================

async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    unposted_count = len(db.unposted_montajchi_videos())
    for admin in db.all_admins(role="admin"):
        stories = db.story_counts_today(admin["user_id"])
        missing = [p for p in config.PLATFORMS if stories.get(p, 0) < config.MIN_STORIES_PER_PLATFORM]
        parts = []
        if missing:
            parts.append(
                "Quyidagi platformalarda kunlik Story me'yori hali to'liq bajarilmagan:\n"
                + "\n".join(f"• {p} ({stories.get(p, 0)}/{config.MIN_STORIES_PER_PLATFORM})" for p in missing)
            )
        if unposted_count:
            parts.append(f"Montajchi tayyorlagan {unposted_count} ta video hali joylanmagan "
                         "(ro'yxat — \"📊 Hisobot\" bo'limida).")
        if parts:
            try:
                await context.bot.send_message(admin["user_id"], "⏰ Eslatma:\n\n" + "\n\n".join(parts))
            except Exception as e:
                log.warning("Eslatma yuborilmadi (%s): %s", admin["user_id"], e)

    behind = []  # me'yordan orqada qolgan montajchilar
    for m in db.all_admins(role="montajchi"):
        n = db.count_montajchi_videos_today(m["user_id"])
        if n >= config.MIN_MONTAJ_VIDEOS:
            continue
        behind.append(f"• {esc(db.display_name(m))}: {n}/{config.MIN_MONTAJ_VIDEOS}")
        try:
            await context.bot.send_message(
                m["user_id"],
                f"⏰ Eslatma: bugun {n} ta video tayyorladingiz, kunlik me'yor — "
                f"{config.MIN_MONTAJ_VIDEOS} ta (yana {config.MIN_MONTAJ_VIDEOS - n} ta kerak).",
            )
        except Exception as e:
            log.warning("Eslatma yuborilmadi (%s): %s", m["user_id"], e)

    # Nazoratchiga bitta umumiy xabar: ochiq muammolar, joylanmagan videolar, montajchi me'yori
    parts = []
    problems = db.open_problems()
    if problems:
        shown = problems[:10]
        parts.append(
            f"⚠️ <b>Ochiq muammolar: {len(problems)} ta</b>\n"
            + "\n".join(
                f"• #{p['id']} {esc(p['created_at'][:16].replace('T', ' '))} — "
                f"{esc(p['full_name'] or p['admin_id'])}: {esc(p['description'][:80])}"
                for p in shown
            )
            + (f"\n… va yana {len(problems) - len(shown)} ta" if len(problems) > len(shown) else "")
            + "\n\"🗂 Ochiq muammolar\" bo'limida hal qiling."
        )
    unposted = _unposted_lines()
    if unposted:
        parts.append("\n".join(unposted).strip())
    if behind:
        parts.append("🎬 <b>Montajchi me'yordan orqada:</b>\n" + "\n".join(behind))
    if parts:
        await notify(context, supervisor_ids(), "⏰ <b>Nazorat eslatmasi</b>\n\n" + "\n\n".join(parts))


def _parse_hhmm(t: str):
    hh, mm = [int(x) for x in t.split(":")]
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise ValueError("soat 00:00–23:59 oralig'ida bo'lishi kerak")
    return hh, mm


def schedule_jobs(app: Application):
    for t in config.REMINDER_TIMES:
        try:
            hh, mm = _parse_hhmm(t)
            app.job_queue.run_daily(reminder_job, time=dtime(hour=hh, minute=mm, tzinfo=config.TZ))
        except Exception as e:
            log.warning("Noto'g'ri eslatma vaqti '%s': %s", t, e)
    try:
        hh, mm = _parse_hhmm(config.REPORT_TIME)
        app.job_queue.run_daily(auto_report_job, time=dtime(hour=hh, minute=mm, tzinfo=config.TZ))
    except Exception as e:
        log.warning("Noto'g'ri hisobot vaqti '%s': %s", config.REPORT_TIME, e)


async def check_channel(app: Application):
    """Ishga tushishda: bot kanalda xabar joylay oladimi — oldindan ogohlantirish uchun."""
    if not config.CHANNEL_ID:
        return
    try:
        member = await app.bot.get_chat_member(config.CHANNEL_ID, app.bot.id)
        if member.status != "administrator" or not getattr(member, "can_post_messages", False):
            log.warning("SOZLAMA: bot %s kanalida xabar joylash huquqiga ega admin emas — "
                        "avto-joylash ishlamaydi", config.CHANNEL_ID)
        else:
            log.info("Kanal tayyor: %s", config.CHANNEL_ID)
    except Exception as e:
        log.warning("SOZLAMA: %s kanalini tekshirib bo'lmadi (bot kanalga qo'shilmaganmi?): %s",
                    config.CHANNEL_ID, e)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Kutilmagan xatolik", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message and update.effective_chat \
            and update.effective_chat.type == "private":
        try:
            await update.effective_message.reply_text("❌ Kutilmagan xatolik yuz berdi. Qayta urinib ko'ring.")
        except Exception:
            pass


# =========================================================
# Botni ishga tushirish
# =========================================================

def build_app(builder=None) -> Application:
    config.validate()
    db.init_db()
    db.sync_staff(config.all_staff_ids())
    if builder is None:
        # Standart 5 soniya sekin internetda yetmaydi — bot ishga tushishda yiqilib qolardi
        builder = (
            ApplicationBuilder().token(config.BOT_TOKEN)
            .connect_timeout(20).read_timeout(30).write_timeout(60).pool_timeout(20)
            .get_updates_connect_timeout(20).get_updates_read_timeout(30)
        )
    app = builder.post_init(check_channel).build()

    # -1: kirish nazorati — ro'yxatda yo'q foydalanuvchi shu yerda to'xtatiladi
    app.add_handler(TypeHandler(Update, access_guard), group=-1)

    # Har bir suhbat alohida guruhda: suhbat o'rtasida boshqa menyu tugmasi bosilsa,
    # joriy suhbat bekor qilinadi VA bosilgan tugma o'z guruhida odatdagidek ishlaydi.
    for i, conv in enumerate([new_video_conv, story_conv, problem_conv, mont_video_conv,
                              screenshot_conv, note_conv], start=1):
        app.add_handler(conv, group=i)

    g = 10  # oddiy (suhbatsiz) handlerlar
    app.add_handler(CommandHandler("start", start), group=g)
    app.add_handler(CommandHandler("yordam", help_cmd), group=g)
    app.add_handler(MessageHandler(_button(BTN_HELP), help_cmd), group=g)
    app.add_handler(CommandHandler("bekor_qilish", global_cancel), group=g)
    app.add_handler(CallbackQueryHandler(resolve_or_escalate, pattern=r"^(resolve|escalate)_\d+$"), group=g)
    app.add_handler(MessageHandler(_button(BTN_OPEN_PROBLEMS), open_problems), group=g)
    app.add_handler(MessageHandler(_button(BTN_SEND_REPORT), send_report_manual), group=g)
    app.add_handler(CommandHandler("hisobot_pdf", send_report_manual, filters=filters.ChatType.PRIVATE), group=g)
    app.add_handler(MessageHandler(_button(BTN_REPORT), report_text), group=g)
    app.add_handler(CommandHandler("hisobot", report_text, filters=filters.ChatType.PRIVATE), group=g)

    app.add_error_handler(error_handler)

    if app.job_queue:
        schedule_jobs(app)
    else:
        log.warning("JobQueue mavjud emas — eslatmalar va avtomatik hisobot ishlamaydi. "
                    "'pip install \"python-telegram-bot[job-queue]\"' ni bajaring.")
    return app


def main():
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN topilmadi. .env faylida BOT_TOKEN ni to'ldiring.")
    app = build_app()
    # Python 3.14+ da event loop avtomatik yaratilmaydi, PTB 21.x esa uni kutadi
    asyncio.set_event_loop(asyncio.new_event_loop())
    log.info("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
