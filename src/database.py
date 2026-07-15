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
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_app_usage_process_start
            ON app_usage(LOWER(process_name), start_time, end_time)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_usage_summary (
                process_key    TEXT PRIMARY KEY,
                app_name       TEXT NOT NULL,
                process_name   TEXT NOT NULL,
                exe_path       TEXT NOT NULL DEFAULT '',
                last_used_at   TEXT NOT NULL,
                total_seconds  REAL NOT NULL DEFAULT 0,
                session_count  INTEGER NOT NULL DEFAULT 0,
                latest_usage_id INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_app_usage_summary_recent
            ON app_usage_summary(last_used_at DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_app_usage_summary_total
            ON app_usage_summary(total_seconds DESC, last_used_at DESC)
        """)
        summary_count = conn.execute("SELECT COUNT(*) FROM app_usage_summary").fetchone()[0]
        if summary_count == 0:
            conn.execute("""
                INSERT INTO app_usage_summary(
                    process_key, app_name, process_name, exe_path, last_used_at,
                    total_seconds, session_count, latest_usage_id
                )
                WITH summaries AS (
                    SELECT LOWER(process_name) AS process_key,
                           MAX(id) AS latest_usage_id,
                           MAX(end_time) AS last_used_at,
                           SUM(duration_seconds) AS total_seconds,
                           COUNT(*) AS session_count
                    FROM app_usage
                    GROUP BY LOWER(process_name)
                )
                SELECT summaries.process_key, latest.app_name, latest.process_name,
                       latest.exe_path, summaries.last_used_at, summaries.total_seconds,
                       summaries.session_count, summaries.latest_usage_id
                FROM summaries
                JOIN app_usage AS latest ON latest.id = summaries.latest_usage_id
            """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS key_usage (
                date        TEXT NOT NULL,
                hour        INTEGER NOT NULL,
                key_name    TEXT NOT NULL,
                press_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (date, hour, key_name)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_key_usage_date
            ON key_usage(date)
        """)


def increment_key_usage(key_name: str, pressed_at: datetime | None = None):
    """Store only an aggregate key count; typed text and key order are never saved."""
    pressed_at = pressed_at or datetime.now()
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO key_usage (date, hour, key_name, press_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(date, hour, key_name)
            DO UPDATE SET press_count = press_count + 1
        """, (
            pressed_at.strftime("%Y-%m-%d"),
            pressed_at.hour,
            key_name,
        ))


def increment_key_usage_batch(rows: list[tuple[str, int, str, int]]):
    if not rows:
        return
    with get_connection() as conn:
        conn.executemany("""
            INSERT INTO key_usage (date, hour, key_name, press_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(date, hour, key_name)
            DO UPDATE SET press_count = press_count + excluded.press_count
        """, rows)


def query_key_usage_between(start_date: str | None, end_date: str | None) -> dict:
    with get_connection() as conn:
        params = []
        where = ""
        if start_date and end_date:
            where = "WHERE date BETWEEN ? AND ?"
            params = [start_date, end_date]

        key_rows = conn.execute(f"""
            SELECT key_name, SUM(press_count) AS press_count
            FROM key_usage
            {where}
            GROUP BY key_name
            ORDER BY press_count DESC, key_name ASC
        """, params).fetchall()
        hour_rows = conn.execute(f"""
            SELECT hour, SUM(press_count) AS press_count
            FROM key_usage
            {where}
            GROUP BY hour
            ORDER BY hour
        """, params).fetchall()

    hour_map = {row["hour"]: row["press_count"] for row in hour_rows}
    keys = [dict(row) for row in key_rows]
    return {
        "total_presses": sum(item["press_count"] for item in keys),
        "active_keys": len(keys),
        "keys": keys,
        "hours": [
            {"hour": hour, "press_count": hour_map.get(hour, 0)}
            for hour in range(24)
        ],
    }


def query_key_daily_totals_between(start_date: str, end_date: str) -> list[dict]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT date, SUM(press_count) AS press_count
            FROM key_usage
            WHERE date BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
        """, (start_date, end_date)).fetchall()

    date_map = {row["date"]: row["press_count"] for row in rows}
    return [
        {
            "date": (start + timedelta(days=offset)).strftime("%Y-%m-%d"),
            "press_count": date_map.get(
                (start + timedelta(days=offset)).strftime("%Y-%m-%d"),
                0,
            ),
        }
        for offset in range((end - start).days + 1)
    ]

def insert_usage(app_name: str, process_name: str, exe_path: str, window_title: str,
                 start_time: datetime, end_time: datetime):
    duration = (end_time - start_time).total_seconds()
    if duration < 1:
        return
    with get_connection() as conn:
        cursor = conn.execute("""
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
        usage_id = int(cursor.lastrowid)
        process_key = process_name.casefold()
        end_text = end_time.isoformat()
        conn.execute("""
            INSERT INTO app_usage_summary(
                process_key, app_name, process_name, exe_path, last_used_at,
                total_seconds, session_count, latest_usage_id
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(process_key) DO UPDATE SET
                total_seconds = app_usage_summary.total_seconds + excluded.total_seconds,
                session_count = app_usage_summary.session_count + 1,
                app_name = CASE WHEN excluded.last_used_at >= app_usage_summary.last_used_at
                                THEN excluded.app_name ELSE app_usage_summary.app_name END,
                process_name = CASE WHEN excluded.last_used_at >= app_usage_summary.last_used_at
                                    THEN excluded.process_name ELSE app_usage_summary.process_name END,
                exe_path = CASE WHEN excluded.last_used_at >= app_usage_summary.last_used_at
                                THEN excluded.exe_path ELSE app_usage_summary.exe_path END,
                last_used_at = MAX(app_usage_summary.last_used_at, excluded.last_used_at),
                latest_usage_id = MAX(app_usage_summary.latest_usage_id, excluded.latest_usage_id)
        """, (
            process_key, app_name, process_name, exe_path, end_text,
            duration, usage_id,
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


def query_keytrace_app_catalog(limit: int = 24) -> dict[str, list[dict]]:
    """Return app identities from the incrementally maintained summary table."""
    with get_connection() as conn:
        recent = conn.execute("""
            SELECT app_name, process_name, exe_path, last_used_at,
                   total_seconds, session_count
            FROM app_usage_summary
            ORDER BY last_used_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        most_used = conn.execute("""
            SELECT app_name, process_name, exe_path, last_used_at,
                   total_seconds, session_count
            FROM app_usage_summary
            ORDER BY total_seconds DESC, last_used_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return {
        "recent": [dict(row) for row in recent],
        "most_used": [dict(row) for row in most_used],
    }


def query_keytrace_app_sessions(process_name: str) -> list[dict]:
    """Return foreground intervals for one process without exposing window titles."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT app_name, process_name, exe_path, start_time, end_time
            FROM app_usage
            WHERE LOWER(process_name) = LOWER(?)
            ORDER BY start_time, end_time
        """, (process_name,)).fetchall()
    return [dict(row) for row in rows]

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
