import sqlite3
import os
import sys
from datetime import datetime, timedelta
from contextlib import contextmanager

def _app_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(_app_base_dir(), "data", "usage.db")

def _ensure_dir():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

@contextmanager
def get_connection():
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_usage (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                app_name    TEXT NOT NULL,
                process_name TEXT NOT NULL,
                window_title TEXT NOT NULL DEFAULT '',
                start_time  TEXT NOT NULL,
                end_time    TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                date        TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_app_usage_date
            ON app_usage(date)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_app_usage_app_name
            ON app_usage(app_name, date)
        """)

def insert_usage(app_name: str, process_name: str, window_title: str,
                 start_time: datetime, end_time: datetime):
    duration = (end_time - start_time).total_seconds()
    if duration < 1:
        return
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO app_usage (app_name, process_name, window_title,
                                   start_time, end_time, duration_seconds, date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            app_name,
            process_name,
            window_title,
            start_time.isoformat(),
            end_time.isoformat(),
            duration,
            start_time.strftime("%Y-%m-%d"),
        ))

def query_daily_summary(date_str: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT app_name,
                   SUM(duration_seconds) AS total_seconds,
                   COUNT(*) AS session_count
            FROM app_usage
            WHERE date = ?
            GROUP BY app_name
            ORDER BY total_seconds DESC
        """, (date_str,)).fetchall()
        proc_rows = conn.execute("""
            SELECT app_name, process_name, COUNT(*) AS cnt
            FROM app_usage
            WHERE date = ?
            GROUP BY app_name, process_name
        """, (date_str,)).fetchall()

    proc_map: dict[str, str] = {}
    proc_cnt: dict[str, int] = {}
    for pr in proc_rows:
        an, pn, cnt = pr["app_name"], pr["process_name"], pr["cnt"]
        if an not in proc_map or cnt > proc_cnt[an]:
            proc_map[an] = pn
            proc_cnt[an] = cnt

    result = []
    for r in rows:
        d = dict(r)
        d["process_name"] = proc_map.get(d["app_name"], "")
        result.append(d)
    return result

def query_app_summary_between(start_date: str, end_date: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT app_name,
                   SUM(duration_seconds) AS total_seconds,
                   COUNT(*) AS session_count
            FROM app_usage
            WHERE date BETWEEN ? AND ?
            GROUP BY app_name
            ORDER BY total_seconds DESC
        """, (start_date, end_date)).fetchall()
        proc_rows = conn.execute("""
            SELECT app_name, process_name, COUNT(*) AS cnt
            FROM app_usage
            WHERE date BETWEEN ? AND ?
            GROUP BY app_name, process_name
        """, (start_date, end_date)).fetchall()

    proc_map: dict[str, str] = {}
    proc_cnt: dict[str, int] = {}
    for pr in proc_rows:
        an, pn, cnt = pr["app_name"], pr["process_name"], pr["cnt"]
        if an not in proc_map or cnt > proc_cnt[an]:
            proc_map[an] = pn
            proc_cnt[an] = cnt

    result = []
    for r in rows:
        d = dict(r)
        d["process_name"] = proc_map.get(d["app_name"], "")
        result.append(d)
    return result

def query_daily_totals_between(start_date: str, end_date: str) -> list[dict]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT date,
                   SUM(duration_seconds) AS total_seconds,
                   COUNT(DISTINCT app_name) AS app_count
            FROM app_usage
            WHERE date BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
        """, (start_date, end_date)).fetchall()

    date_map = {r["date"]: dict(r) for r in rows}
    result = []
    days = (end - start).days
    for i in range(days + 1):
        d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        result.append(date_map.get(d, {"date": d, "total_seconds": 0, "app_count": 0}))
    return result

def query_monthly_totals_for_year(year: int) -> list[dict]:
    year_text = str(year)
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT substr(date, 1, 7) AS month,
                   SUM(duration_seconds) AS total_seconds,
                   COUNT(DISTINCT app_name) AS app_count
            FROM app_usage
            WHERE substr(date, 1, 4) = ?
            GROUP BY month
            ORDER BY month
        """, (year_text,)).fetchall()

    month_map = {r["month"]: dict(r) for r in rows}
    result = []
    for month in range(1, 13):
        key = f"{year}-{month:02d}"
        result.append(month_map.get(key, {"month": key, "total_seconds": 0, "app_count": 0}))
    return result

def query_yearly_totals() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT substr(date, 1, 4) AS year,
                   SUM(duration_seconds) AS total_seconds,
                   COUNT(DISTINCT app_name) AS app_count
            FROM app_usage
            GROUP BY year
            ORDER BY year
        """).fetchall()
    return [dict(r) for r in rows]

def query_hourly_distribution(date_str: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT CAST(strftime('%H', start_time) AS INTEGER) AS hour,
                   SUM(duration_seconds) AS total_seconds
            FROM app_usage
            WHERE date = ?
            GROUP BY hour
            ORDER BY hour
        """, (date_str,)).fetchall()
    hour_map = {r["hour"]: r["total_seconds"] for r in rows}
    return [{"hour": h, "total_seconds": hour_map.get(h, 0)} for h in range(24)]

def query_weekly_summary() -> list[dict]:
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT date,
                   SUM(duration_seconds) AS total_seconds,
                   COUNT(DISTINCT app_name) AS app_count
            FROM app_usage
            WHERE date BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
        """, (week_ago, today)).fetchall()
    date_map = {r["date"]: dict(r) for r in rows}
    result = []
    for i in range(7):
        d = (datetime.now() - timedelta(days=6 - i)).strftime("%Y-%m-%d")
        if d in date_map:
            result.append(date_map[d])
        else:
            result.append({"date": d, "total_seconds": 0, "app_count": 0})
    return result

def query_date_range() -> tuple[str, str] | None:
    with get_connection() as conn:
        row = conn.execute("""
            SELECT MIN(date) AS min_date, MAX(date) AS max_date
            FROM app_usage
        """).fetchone()
    if row and row["min_date"]:
        return row["min_date"], row["max_date"]
    return None