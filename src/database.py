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
                exe_path    TEXT NOT NULL DEFAULT '',
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
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(app_usage)").fetchall()
        }
        if "exe_path" not in columns:
            conn.execute(
                "ALTER TABLE app_usage ADD COLUMN exe_path TEXT NOT NULL DEFAULT ''"
            )

def insert_usage(app_name: str, process_name: str, exe_path: str, window_title: str,
                 start_time: datetime, end_time: datetime):
    duration = (end_time - start_time).total_seconds()
    if duration < 1:
        return
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO app_usage (app_name, process_name, exe_path, window_title,
                                   start_time, end_time, duration_seconds, date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            app_name,
            process_name,
            exe_path,
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
            SELECT app_name, process_name, exe_path, COUNT(*) AS cnt
            FROM app_usage
            WHERE date = ?
            GROUP BY app_name, process_name, exe_path
        """, (date_str,)).fetchall()

    proc_map: dict[str, str] = {}
    exe_map: dict[str, str] = {}
    proc_cnt: dict[str, int] = {}
    for pr in proc_rows:
        an, pn, ep, cnt = pr["app_name"], pr["process_name"], pr["exe_path"], pr["cnt"]
        if an not in proc_map or cnt > proc_cnt[an]:
            proc_map[an] = pn
            exe_map[an] = ep
            proc_cnt[an] = cnt

    result = []
    for r in rows:
        d = dict(r)
        d["process_name"] = proc_map.get(d["app_name"], "")
        d["exe_path"] = exe_map.get(d["app_name"], "")
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
            SELECT app_name, process_name, exe_path, COUNT(*) AS cnt
            FROM app_usage
            WHERE date BETWEEN ? AND ?
            GROUP BY app_name, process_name, exe_path
        """, (start_date, end_date)).fetchall()

    proc_map: dict[str, str] = {}
    exe_map: dict[str, str] = {}
    proc_cnt: dict[str, int] = {}
    for pr in proc_rows:
        an, pn, ep, cnt = pr["app_name"], pr["process_name"], pr["exe_path"], pr["cnt"]
        if an not in proc_map or cnt > proc_cnt[an]:
            proc_map[an] = pn
            exe_map[an] = ep
            proc_cnt[an] = cnt

    result = []
    for r in rows:
        d = dict(r)
        d["process_name"] = proc_map.get(d["app_name"], "")
        d["exe_path"] = exe_map.get(d["app_name"], "")
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

def query_hourly_app_distribution(start_date: str | None = None, end_date: str | None = None) -> list[dict]:
    period_start = datetime.fromisoformat(f"{start_date}T00:00:00") if start_date else None
    period_end = datetime.fromisoformat(f"{end_date}T00:00:00") + timedelta(days=1) if end_date else None
    if period_start and not period_end:
        period_end = period_start + timedelta(days=1)

    with get_connection() as conn:
        params = []
        where = []
        if period_end:
            where.append("start_time < ?")
            params.append(period_end.isoformat())
        if period_start:
            where.append("end_time > ?")
            params.append(period_start.isoformat())
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = conn.execute("""
            SELECT app_name,
                   process_name,
                   exe_path,
                   start_time,
                   end_time
            FROM app_usage
            {where_sql}
        """.format(where_sql=where_sql), params).fetchall()

    hours = [
        {"hour": h, "total_seconds": 0, "apps": []}
        for h in range(24)
    ]
    app_totals: list[dict[str, float | str]] = [
        {}
        for _ in range(24)
    ]

    for row in rows:
        try:
            start = datetime.fromisoformat(row["start_time"])
            end = datetime.fromisoformat(row["end_time"])
        except ValueError:
            continue

        if period_start:
            start = max(start, period_start)
        if period_end:
            end = min(end, period_end)
        if end <= start:
            continue

        cursor = start
        while cursor < end:
            next_hour = (cursor.replace(minute=0, second=0, microsecond=0)
                         + timedelta(hours=1))
            segment_end = min(end, next_hour)
            seconds = (segment_end - cursor).total_seconds()
            hour = cursor.hour
            key = f"{row['app_name']}|{row['process_name']}|{row['exe_path']}"

            hour_bucket = hours[hour]
            hour_bucket["total_seconds"] += seconds
            if key not in app_totals[hour]:
                app_totals[hour][key] = {
                    "app_name": row["app_name"],
                    "process_name": row["process_name"],
                    "exe_path": row["exe_path"],
                    "total_seconds": 0,
                }
            app_totals[hour][key]["total_seconds"] += seconds
            cursor = segment_end

    for hour, apps in enumerate(app_totals):
        hours[hour]["apps"] = sorted(
            apps.values(),
            key=lambda app: app["total_seconds"],
            reverse=True,
        )
    return hours

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
