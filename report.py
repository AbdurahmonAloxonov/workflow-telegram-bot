"""Kunlik hisobotni PDF ko'rinishida yig'ib beruvchi modul."""
import logging
from datetime import date
from pathlib import Path

from fpdf import FPDF

import config
import db

log = logging.getLogger("adminbot")


class ReportPDF(FPDF):
    def header(self):
        pass

    def footer(self):
        self.set_y(-15)
        self.set_font("DejaVu", "", 8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 10, f"Sahifa {self.page_no()}", align="C")


def _new_pdf() -> ReportPDF:
    pdf = ReportPDF()
    pdf.add_font("DejaVu", "", config.FONT_REGULAR)
    pdf.add_font("DejaVu", "B", config.FONT_BOLD)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    return pdf


def _section_title(pdf: ReportPDF, text: str):
    pdf.ln(3)
    pdf.set_font("DejaVu", "B", 13)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 9, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(210, 210, 210)
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(2)
    pdf.set_font("DejaVu", "", 11)
    pdf.set_text_color(30, 30, 30)


def _line(pdf: ReportPDF, text: str, h: float = 7):
    pdf.multi_cell(0, h, text, new_x="LMARGIN", new_y="NEXT")


STATUS_MAP = {"open": "[HAL QILINMAGAN]", "resolved": "[HAL QILINDI]", "escalated": "[BIG ADMINGA YUBORILDI]"}


def _problem_line(p, show_date: bool = False) -> str:
    who = p["full_name"] or f"ID {p['admin_id']}"
    status = STATUS_MAP.get(p["status"], p["status"])
    if p["status"] != "open" and p["resolver_name"]:
        status += f" ({p['resolver_name']})"
    when = f"{p['created_at'][:10]} " if show_date else ""
    return f"• {when}[{who}] {p['description']}  —  holati: {status}"


def build_daily_report(generated_by_name: str, day: date = None, photo_cache_dir: Path = None) -> str:
    """Berilgan kun (standart — bugun) bo'yicha PDF hisobot yaratadi va fayl yo'lini qaytaradi."""
    day = day or db.today()
    day_str = day.isoformat()
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    pdf = _new_pdf()
    pdf.set_font("DejaVu", "B", 17)
    pdf.cell(0, 12, f"Kunlik hisobot — {day_str}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 7, f"Tayyorladi: {generated_by_name}  |  Yaratilgan vaqt: {db.now().strftime('%Y-%m-%d %H:%M')}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 30, 30)

    # 1. Montajchi natijalari
    _section_title(pdf, "1. Montajchi natijalari")
    montajchilar = db.all_admins(role="montajchi")
    if not montajchilar:
        _line(pdf, "Montajchi ro'yxatdan o'tmagan.")
    else:
        for m in montajchilar:
            videos = db.montajchi_videos_today(m["user_id"], day)
            kodlar = ", ".join(v["kino_kod"] for v in videos if v["kino_kod"]) or "—"
            target = config.MIN_MONTAJ_VIDEOS
            norm = "me'yor bajarildi" if len(videos) >= target else f"ME'YOR BAJARILMADI, {target - len(videos)} ta kam"
            _line(pdf, f"• {db.display_name(m)}: {len(videos)}/{target} ta video tayyorladi ({norm}). "
                       f"Kino kodlari: {kodlar}")

    # 2. Adminlar natijalari
    _section_title(pdf, "2. Adminlar natijalari (video joylash va story)")
    adminlar = db.all_admins(role="admin")
    if not adminlar:
        _line(pdf, "Admin ro'yxatdan o'tmagan.")
    else:
        for a in adminlar:
            videos = db.count_videos_today(a["user_id"], day)
            stories = db.story_counts_today(a["user_id"], day)
            story_line = ", ".join(
                f"{p}: {stories.get(p, 0)}/{config.MIN_STORIES_PER_PLATFORM}" for p in config.PLATFORMS
            )
            problems = db.count_problems_today(a["user_id"], day)
            _line(pdf, f"• {db.display_name(a)}: {videos} ta video joyladi | Story — {story_line} | "
                       f"Muammo bildirgan: {problems} marta")

    # 3. Ijtimoiy tarmoqlardagi bajarilgan ishlar
    _section_title(pdf, "3. Ijtimoiy tarmoqlarda bajarilgan ishlar")
    platform_counts = db.posts_count_by_platform_today(day)
    for p in config.PLATFORMS:
        _line(pdf, f"• {p}: {platform_counts.get(p, 0)} ta video joylandi")

    unposted = db.unposted_montajchi_videos(day)
    pdf.ln(2)
    pdf.set_font("DejaVu", "B", 11)
    if unposted:
        _line(pdf, f"Montajchi tayyorlagan, lekin joylanmagan videolar ({len(unposted)} ta, "
                   f"oxirgi {config.UNPOSTED_LOOKBACK_DAYS} kun):")
        pdf.set_font("DejaVu", "", 10)
        for u in unposted:
            who = u["full_name"] or f"ID {u['montajchi_id']}"
            _line(pdf, f"• Kod {u['kino_kod']} — tayyorlagan: {who}, {u['created_at'][:16].replace('T', ' ')}", h=6)
    elif montajchilar:
        _line(pdf, "Montajchi tayyorlagan barcha videolar joylangan.")
    pdf.set_font("DejaVu", "", 11)

    posted = db.posted_videos_today(day)
    if posted:
        pdf.ln(2)
        pdf.set_font("DejaVu", "B", 11)
        _line(pdf, "Joylangan videolar va havolalar:")
        pdf.set_font("DejaVu", "", 9)
        for v, links in posted:
            who = v["full_name"] or f"ID {v['admin_id']}"
            _line(pdf, f"• Kod {v['kino_kod']} — {who} ({v['created_at'][11:16]})", h=5.5)
            for p in config.PLATFORMS:
                _line(pdf, f"     {p}: {links.get(p) or '—'}", h=5)
        pdf.set_font("DejaVu", "", 11)

    # 4. Muammolar va kamchiliklar
    _section_title(pdf, "4. Muammolar va kamchiliklar")
    problems = db.problems_today(day)
    if not problems:
        _line(pdf, "Shu kuni qayd etilgan muammo bo'lmadi.")
    else:
        for p in problems:
            _line(pdf, _problem_line(p))

    older_open = db.open_problems_before(day)
    if older_open:
        pdf.ln(2)
        pdf.set_font("DejaVu", "B", 11)
        _line(pdf, f"Oldingi kunlardan hal qilinmay qolgan muammolar ({len(older_open)} ta):")
        pdf.set_font("DejaVu", "", 11)
        for p in older_open:
            _line(pdf, _problem_line(p, show_date=True))

    # 5. Aniqlangan xatolar (nazoratchi kiritgan)
    _section_title(pdf, "5. Aniqlangan xatolar")
    xatolar = db.report_notes_today(category="xato", day=day)
    if not xatolar:
        _line(pdf, "Qo'shimcha xato qayd etilmagan.")
    else:
        for x in xatolar:
            _line(pdf, f"• {x['text']}")

    # 6. Kun davomida bajarilgan boshqa ishlar
    _section_title(pdf, "6. Kun davomida bajarilgan boshqa ishlar")
    boshqa = db.report_notes_today(category="boshqa", day=day)
    if not boshqa:
        _line(pdf, "Qo'shimcha yozuv kiritilmagan.")
    else:
        for b in boshqa:
            _line(pdf, f"• {b['text']}")

    # 7. Skrinshotlar (dalil)
    photos = db.report_photos_today(day)
    if photos:
        if pdf.get_y() > pdf.h - 110:  # sarlavha sahifa oxirida yolg'iz qolmasin
            pdf.add_page()
        _section_title(pdf, "7. Skrinshotlar (dalillar)")
        missing = 0
        for ph in photos:
            local_path = photo_cache_dir / f"{ph['file_id']}.jpg" if photo_cache_dir else None
            if not local_path or not local_path.exists():
                missing += 1
                continue
            if pdf.get_y() > pdf.h - 90:
                pdf.add_page()
            pdf.set_font("DejaVu", "", 9)
            if ph["caption"]:
                _line(pdf, ph["caption"], h=6)
            try:
                pdf.image(str(local_path), w=110)
            except Exception as e:
                # Masalan, PDF qo'llab-quvvatlamaydigan format (HEIC) — hisobot baribir yaratilsin
                log.warning("Skrinshot PDF ga qo'shilmadi (%s): %s", local_path.name, e)
                missing += 1
            pdf.ln(4)
        if missing:
            pdf.set_font("DejaVu", "", 9)
            _line(pdf, f"({missing} ta skrinshotni PDF ga qo'shib bo'lmadi — ular Telegramda saqlangan.)", h=6)

    out_path = config.REPORTS_DIR / f"hisobot_{day_str}_{db.now().strftime('%H%M%S')}.pdf"
    pdf.output(str(out_path))
    return str(out_path)
