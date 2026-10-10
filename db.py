import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, date, timedelta

import config

_lock = threading.Lock()


@contextmanager
def _db():
    """Lock ostida ulanish ochadi, oxirida commit qilib YOPADI."""
    with _lock:
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def now() -> datetime:
    """Joriy vaqt — har doim sozlamadagi vaqt zonasida (server vaqtiga bog'liq emas)."""
    return datetime.now(config.TZ)


def today() -> date:
    return now().date()


def _day(day: date = None) -> str:
    return (day or today()).isoformat()


def _ensure_column(c, table: str, column: str, decl: str):
    cols = [r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            role TEXT DEFAULT 'admin',
            registered_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            kino_kod TEXT,
            status TEXT DEFAULT 'checking',
            created_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER,
            admin_id INTEGER,
            platform TEXT,
            caption TEXT,
            posted_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS stories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            platform TEXT,
            posted_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            description TEXT,
            media_file_id TEXT,
            media_type TEXT,
            status TEXT DEFAULT 'open',
            resolved_by INTEGER,
            resolved_at TEXT,
            created_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS montajchi_videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            montajchi_id INTEGER,
            kino_kod TEXT,
            note TEXT,
            created_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS report_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supervisor_id INTEGER,
            category TEXT,
            text TEXT,
            created_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS report_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supervisor_id INTEGER,
            file_id TEXT,
            caption TEXT,
            created_at TEXT
        )""")
        # Eski bazalarni yangi ustunlar bilan moslashtirish (migratsiya)
        _ensure_column(c, "problems", "status", "TEXT DEFAULT 'open'")
        _ensure_column(c, "problems", "resolved_by", "INTEGER")
        _ensure_column(c, "problems", "resolved_at", "TEXT")
        _ensure_column(c, "posts", "url", "TEXT")
        _ensure_column(c, "stories", "file_id", "TEXT")
        _ensure_column(c, "videos", "file_id", "TEXT")


# ---------- Adminlar / rollar ----------

def upsert_admin(user_id: int, full_name: str, username: str, role: str):
    with _db() as c:
        row = c.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,)).fetchone()
        if row:
            c.execute(
                "UPDATE admins SET full_name=?, username=?, role=? WHERE user_id=?",
                (full_name, username, role, user_id),
            )
        else:
            c.execute(
                "INSERT INTO admins (user_id, full_name, username, role, registered_at) VALUES (?,?,?,?,?)",
                (user_id, full_name, username, role, now().isoformat()),
            )


def sync_staff(staff: dict):
    """Bazadagi rollarni .env bilan moslashtiradi.

    .env dagi har bir xodim bazada bo'ladi (hali /start bosmagan bo'lsa ham — hisobotga tushishi uchun),
    .env dan olib tashlanganlar esa 'inactive' bo'lib, hisobot va eslatmalardan chiqadi.
    """
    with _db() as c:
        existing = {r["user_id"] for r in c.execute("SELECT user_id FROM admins").fetchall()}
        for uid in existing:
            c.execute("UPDATE admins SET role=? WHERE user_id=?", (staff.get(uid) or "inactive", uid))
        for uid, role in staff.items():
            if uid not in existing:
                c.execute(
                    "INSERT INTO admins (user_id, full_name, username, role, registered_at) VALUES (?,?,?,?,?)",
                    (uid, None, None, role, now().isoformat()),
                )


def get_admin(user_id: int):
    with _db() as c:
        return c.execute("SELECT * FROM admins WHERE user_id=?", (user_id,)).fetchone()


def all_admins(role: str = None):
    with _db() as c:
        if role:
            return c.execute(
                "SELECT * FROM admins WHERE role=? ORDER BY registered_at", (role,)
            ).fetchall()
        return c.execute("SELECT * FROM admins ORDER BY registered_at").fetchall()


def display_name(row) -> str:
    """Xodim ismi; hali /start bosmagan bo'lsa — ID."""
    if row is None:
        return "Noma'lum"
    return row["full_name"] or f"ID {row['user_id']}"


# ---------- Videolar / postlar (admin) ----------

def create_video(admin_id: int, kino_kod: str) -> int:
    with _db() as c:
        cur = c.execute(
            "INSERT INTO videos (admin_id, kino_kod, status, created_at) VALUES (?,?,?,?)",
            (admin_id, kino_kod, "checking", now().isoformat()),
        )
        return cur.lastrowid


def set_video_file(video_id: int, file_id: str):
    with _db() as c:
        c.execute("UPDATE videos SET file_id=? WHERE id=?", (file_id, video_id))


def set_video_status(video_id: int, status: str):
    with _db() as c:
        c.execute("UPDATE videos SET status=? WHERE id=?", (status, video_id))


def add_post(video_id: int, admin_id: int, platform: str, caption: str, url: str):
    with _db() as c:
        c.execute(
            "INSERT INTO posts (video_id, admin_id, platform, caption, url, posted_at) VALUES (?,?,?,?,?,?)",
            (video_id, admin_id, platform, caption, url, now().isoformat()),
        )


def count_videos_today(admin_id: int, day: date = None) -> int:
    with _db() as c:
        row = c.execute(
            "SELECT COUNT(*) c FROM videos WHERE admin_id=? AND status='posted' AND substr(created_at,1,10)=?",
            (admin_id, _day(day)),
        ).fetchone()
        return row["c"] if row else 0


def posts_count_by_platform_today(day: date = None) -> dict:
    """Faqat to'liq joylangan (barcha platformalardan o'tgan) videolar postlari hisoblanadi."""
    with _db() as c:
        rows = c.execute(
            "SELECT p.platform, COUNT(*) c FROM posts p JOIN videos v ON v.id = p.video_id "
            "WHERE v.status='posted' AND substr(p.posted_at,1,10)=? GROUP BY p.platform",
            (_day(day),),
        ).fetchall()
        return {r["platform"]: r["c"] for r in rows}


def posted_videos_today(day: date = None):
    """[(video_row, {platform: url})] — hisobotda havolalar bilan ko'rsatish uchun."""
    with _db() as c:
        videos = c.execute(
            "SELECT v.*, a.full_name, a.user_id FROM videos v LEFT JOIN admins a ON a.user_id = v.admin_id "
            "WHERE v.status='posted' AND substr(v.created_at,1,10)=? ORDER BY v.created_at",
            (_day(day),),
        ).fetchall()
        result = []
        for v in videos:
            posts = c.execute("SELECT platform, url FROM posts WHERE video_id=?", (v["id"],)).fetchall()
            result.append((v, {p["platform"]: p["url"] for p in posts}))
        return result


def find_posted_videos_by_kod(kino_kod: str):
    """Shu kino kodi bilan avval joylangan videolar (dublikat tekshiruvi)."""
    with _db() as c:
        return c.execute(
            "SELECT v.*, a.full_name, a.user_id FROM videos v LEFT JOIN admins a ON a.user_id = v.admin_id "
            "WHERE v.status='posted' AND lower(trim(v.kino_kod)) = lower(trim(?)) ORDER BY v.created_at",
            (kino_kod,),
        ).fetchall()


# ---------- Montajchi ----------

def add_montajchi_video(montajchi_id: int, kino_kod: str, note: str) -> int:
    with _db() as c:
        cur = c.execute(
            "INSERT INTO montajchi_videos (montajchi_id, kino_kod, note, created_at) VALUES (?,?,?,?)",
            (montajchi_id, kino_kod, note, now().isoformat()),
        )
        return cur.lastrowid


def montajchi_kod_exists(kino_kod: str) -> bool:
    with _db() as c:
        row = c.execute(
            "SELECT 1 FROM montajchi_videos WHERE lower(trim(kino_kod)) = lower(trim(?)) LIMIT 1",
            (kino_kod,),
        ).fetchone()
        return row is not None


def unposted_montajchi_videos(day: date = None, lookback_days: int = None):
    """Montajchi tayyorlagan (oxirgi N kun ichida, berilgan kun oxirigacha), lekin hech bir admin
    hali joylamagan kino kodlari. Bitta kod bir necha marta qayd etilgan bo'lsa — bir marta chiqadi."""
    day = day or today()
    lookback = config.UNPOSTED_LOOKBACK_DAYS if lookback_days is None else lookback_days
    since = (day - timedelta(days=lookback - 1)).isoformat()
    with _db() as c:
        return c.execute(
            "SELECT m.kino_kod, MIN(m.created_at) AS created_at, a.full_name, m.montajchi_id "
            "FROM montajchi_videos m LEFT JOIN admins a ON a.user_id = m.montajchi_id "
            "WHERE substr(m.created_at,1,10) BETWEEN ? AND ? "
            "AND NOT EXISTS (SELECT 1 FROM videos v WHERE v.status='posted' "
            "                AND lower(trim(v.kino_kod)) = lower(trim(m.kino_kod))) "
            "GROUP BY lower(trim(m.kino_kod)) ORDER BY MIN(m.created_at)",
            (since, day.isoformat()),
        ).fetchall()


def count_montajchi_videos_today(montajchi_id: int, day: date = None) -> int:
    with _db() as c:
        row = c.execute(
            "SELECT COUNT(*) c FROM montajchi_videos WHERE montajchi_id=? AND substr(created_at,1,10)=?",
            (montajchi_id, _day(day)),
        ).fetchone()
        return row["c"] if row else 0


def montajchi_videos_today(montajchi_id: int, day: date = None):
    with _db() as c:
        return c.execute(
            "SELECT * FROM montajchi_videos WHERE montajchi_id=? AND substr(created_at,1,10)=? ORDER BY created_at",
            (montajchi_id, _day(day)),
        ).fetchall()


# ---------- Storylar ----------

def add_story(admin_id: int, platform: str, file_id: str):
    with _db() as c:
        c.execute(
            "INSERT INTO stories (admin_id, platform, file_id, posted_at) VALUES (?,?,?,?)",
            (admin_id, platform, file_id, now().isoformat()),
        )


def count_stories_today(admin_id: int, platform: str, day: date = None) -> int:
    with _db() as c:
        row = c.execute(
            "SELECT COUNT(*) c FROM stories WHERE admin_id=? AND platform=? AND substr(posted_at,1,10)=?",
            (admin_id, platform, _day(day)),
        ).fetchone()
        return row["c"] if row else 0


def story_counts_today(admin_id: int, day: date = None) -> dict:
    with _db() as c:
        rows = c.execute(
            "SELECT platform, COUNT(*) c FROM stories WHERE admin_id=? AND substr(posted_at,1,10)=? GROUP BY platform",
            (admin_id, _day(day)),
        ).fetchall()
        return {r["platform"]: r["c"] for r in rows}


# ---------- Muammolar ----------

def add_problem(admin_id: int, description: str, media_file_id: str, media_type: str) -> int:
    with _db() as c:
        cur = c.execute(
            "INSERT INTO problems (admin_id, description, media_file_id, media_type, status, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (admin_id, description, media_file_id, media_type, "open", now().isoformat()),
        )
        return cur.lastrowid


def get_problem(problem_id: int):
    with _db() as c:
        return c.execute("SELECT * FROM problems WHERE id=?", (problem_id,)).fetchone()


def close_problem(problem_id: int, status: str, resolved_by: int) -> bool:
    """Muammoni faqat u hali OCHIQ bo'lsa yopadi. Kimdir oldinroq yopgan bo'lsa False qaytaradi."""
    with _db() as c:
        cur = c.execute(
            "UPDATE problems SET status=?, resolved_by=?, resolved_at=? WHERE id=? AND status='open'",
            (status, resolved_by, now().isoformat(), problem_id),
        )
        return cur.rowcount == 1


def count_problems_today(admin_id: int, day: date = None) -> int:
    with _db() as c:
        row = c.execute(
            "SELECT COUNT(*) c FROM problems WHERE admin_id=? AND substr(created_at,1,10)=?",
            (admin_id, _day(day)),
        ).fetchone()
        return row["c"] if row else 0


_PROBLEM_SELECT = (
    "SELECT p.*, a.full_name, r.full_name AS resolver_name FROM problems p "
    "LEFT JOIN admins a ON a.user_id = p.admin_id "
    "LEFT JOIN admins r ON r.user_id = p.resolved_by "
)


def problems_today(day: date = None):
    with _db() as c:
        return c.execute(
            _PROBLEM_SELECT + "WHERE substr(p.created_at,1,10)=? ORDER BY p.created_at",
            (_day(day),),
        ).fetchall()


def open_problems():
    """Barcha ochiq muammolar — qaysi kuni yuborilganidan qat'i nazar."""
    with _db() as c:
        return c.execute(
            _PROBLEM_SELECT + "WHERE p.status='open' ORDER BY p.created_at"
        ).fetchall()


def open_problems_before(day: date = None):
    """Berilgan kundan OLDIN yuborilgan va hali ham ochiq turgan muammolar."""
    with _db() as c:
        return c.execute(
            _PROBLEM_SELECT + "WHERE p.status='open' AND substr(p.created_at,1,10) < ? ORDER BY p.created_at",
            (_day(day),),
        ).fetchall()


# ---------- Hisobot uchun eslatma/skrinshotlar (nazoratchi kiritadi) ----------

def add_report_note(supervisor_id: int, category: str, text: str):
    with _db() as c:
        c.execute(
            "INSERT INTO report_notes (supervisor_id, category, text, created_at) VALUES (?,?,?,?)",
            (supervisor_id, category, text, now().isoformat()),
        )


def report_notes_today(category: str = None, day: date = None):
    with _db() as c:
        if category:
            return c.execute(
                "SELECT * FROM report_notes WHERE category=? AND substr(created_at,1,10)=? ORDER BY created_at",
                (category, _day(day)),
            ).fetchall()
        return c.execute(
            "SELECT * FROM report_notes WHERE substr(created_at,1,10)=? ORDER BY created_at",
            (_day(day),),
        ).fetchall()


def add_report_photo(supervisor_id: int, file_id: str, caption: str):
    with _db() as c:
        c.execute(
            "INSERT INTO report_photos (supervisor_id, file_id, caption, created_at) VALUES (?,?,?,?)",
            (supervisor_id, file_id, caption, now().isoformat()),
        )


def report_photos_today(day: date = None):
    with _db() as c:
        return c.execute(
            "SELECT * FROM report_photos WHERE substr(created_at,1,10)=? ORDER BY created_at",
            (_day(day),),
        ).fetchall()
