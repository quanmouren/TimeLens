import re
import io
import os
import shutil
import sys
import winreg
from pathlib import Path
from flask import Flask, render_template, jsonify, request, send_file, make_response
from datetime import datetime, timedelta
from calendar import monthrange
from PIL import Image

from database import (
    init_db,
    query_daily_summary,
    query_hourly_distribution,
    query_weekly_summary,
    query_date_range,
    query_app_summary_between,
    query_daily_totals_between,
    query_monthly_totals_for_year,
    query_yearly_totals,
)

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.config["TEMPLATES_AUTO_RELOAD"] = True

_ICON_CACHE: dict[str, bytes] = {}
_EXE_PATH_CACHE: dict[str, str] = {}

def _resolve_exe_path(process_name: str) -> str | None:
    key = process_name.lower()
    if key in _EXE_PATH_CACHE:
        return _EXE_PATH_CACHE[key] or None

    path = shutil.which(process_name)
    if path:
        _EXE_PATH_CACHE[key] = path
        return path

    try:
        import psutil

        for proc in psutil.process_iter(["name", "exe"]):
            if (proc.info.get("name") or "").lower() == key:
                exe = proc.info.get("exe")
                if exe and os.path.exists(exe):
                    _EXE_PATH_CACHE[key] = exe
                    return exe
    except Exception:
        pass

    app_paths = (
        rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{process_name}",
        rf"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\{process_name}",
    )
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for subkey in app_paths:
            try:
                with winreg.OpenKey(root, subkey) as key_handle:
                    exe, _ = winreg.QueryValueEx(key_handle, "")
                    if exe and os.path.exists(exe):
                        _EXE_PATH_CACHE[key] = exe
                        return exe
            except OSError:
                continue

    _EXE_PATH_CACHE[key] = ""
    return None

def _extract_icon_bytes(process_name: str) -> bytes | None:
    if process_name in _ICON_CACHE:
        return _ICON_CACHE[process_name]

    try:
        import win32gui
        import win32ui

        exe_path = _resolve_exe_path(process_name)
        if not exe_path:
            _ICON_CACHE[process_name] = b""
            return None

        large_icons, small_icons = win32gui.ExtractIconEx(exe_path, 0, 1)
        if not large_icons and not small_icons:
            _ICON_CACHE[process_name] = b""
            return None

        hicon = large_icons[0] if large_icons else small_icons[0]
        screen_dc = win32gui.GetDC(0)
        hdc = win32ui.CreateDCFromHandle(screen_dc)
        mem_dc = hdc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(hdc, 32, 32)
        old_bmp = mem_dc.SelectObject(bmp)
        white_brush = win32gui.GetStockObject(0)
        win32gui.FillRect(mem_dc.GetSafeHdc(), (0, 0, 32, 32), white_brush)
        win32gui.DrawIconEx(mem_dc.GetSafeHdc(), 0, 0, hicon, 32, 32, 0, None, 3)

        bmp_info = bmp.GetInfo()
        bmp_bits = bmp.GetBitmapBits(True)
        img = Image.frombuffer(
            "RGB",
            (bmp_info["bmWidth"], bmp_info["bmHeight"]),
            bmp_bits,
            "raw",
            "BGRX",
            0,
            1,
        ).convert("RGBA")

        mem_dc.SelectObject(old_bmp)
        mem_dc.DeleteDC()
        hdc.DeleteDC()
        win32gui.ReleaseDC(0, screen_dc)
        for icon in large_icons + small_icons:
            win32gui.DestroyIcon(icon)

        if img.width != 24 or img.height != 24:
            img = img.resize((24, 24), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        icon_bytes = buf.getvalue()

        _ICON_CACHE[process_name] = icon_bytes
        return icon_bytes

    except Exception:
        _ICON_CACHE[process_name] = b""
        return None

@app.route("/api/icon/<process_name>")
def api_icon(process_name: str):
    icon_bytes = _extract_icon_bytes(process_name)
    if icon_bytes:
        response = make_response(send_file(io.BytesIO(icon_bytes), mimetype="image/png"))
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"
        return response
    response = make_response("", 204)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def _validate_date(date_str: str) -> str:
    if date_str and _DATE_RE.match(date_str):
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return date_str
        except ValueError:
            pass
    return datetime.now().strftime("%Y-%m-%d")

def _format_duration(seconds: float) -> str:
    if seconds <= 0:
        return "0秒"
    if seconds < 60:
        return f"{int(seconds)}秒"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}分钟"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours}小时"
    return f"{hours}小时{mins}分钟"

def _attach_app_meta(summary: list[dict], total_seconds: float) -> list[dict]:
    for item in summary:
        item["percentage"] = round(item["total_seconds"] / total_seconds * 100, 1) if total_seconds > 0 else 0
        item["formatted"] = _format_duration(item["total_seconds"])
    return summary

def _period_payload(view: str, date_str: str) -> dict:
    selected = datetime.strptime(date_str, "%Y-%m-%d")
    today = datetime.now()

    if view == "weekly":
        start = selected - timedelta(days=6)
        end = selected
        apps = query_app_summary_between(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        bars = [
            {"label": datetime.strptime(d["date"], "%Y-%m-%d").strftime("%m/%d"), **d}
            for d in query_daily_totals_between(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        ]
        title = f"{start.month}月{start.day}日 - {end.month}月{end.day}日"
    elif view == "monthly":
        last_day = monthrange(selected.year, selected.month)[1]
        start = selected.replace(day=1)
        end = selected.replace(day=last_day)
        if end.date() > today.date():
            end = today
        apps = query_app_summary_between(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        bars = [
            {"label": str(datetime.strptime(d["date"], "%Y-%m-%d").day), **d}
            for d in query_daily_totals_between(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        ]
        title = f"{selected.year}年{selected.month}月"
    elif view == "yearly":
        start = datetime(selected.year, 1, 1)
        end = datetime(selected.year, 12, 31)
        if end.date() > today.date():
            end = today
        apps = query_app_summary_between(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        bars = [
            {"label": f"{int(m['month'][-2:])}月", **m}
            for m in query_monthly_totals_for_year(selected.year)
        ]
        title = f"{selected.year}年"
    elif view == "total":
        date_range = query_date_range()
        if date_range:
            start_date, end_date = date_range
            apps = query_app_summary_between(start_date, end_date)
        else:
            start_date = end_date = date_str
            apps = []
        bars = [
            {"label": item["year"], **item}
            for item in query_yearly_totals()
        ]
        title = "全部记录"
    else:
        apps = query_daily_summary(date_str)
        bars = []
        title = date_str

    total_seconds = sum(item["total_seconds"] for item in apps)
    return {
        "view": view,
        "date": date_str,
        "title": title,
        "total_seconds": total_seconds,
        "total_formatted": _format_duration(total_seconds),
        "app_count": len(apps),
        "apps": _attach_app_meta(apps, total_seconds),
        "bars": bars,
    }


@app.route("/")
def index():
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("dashboard.html", default_date=today)


@app.route("/ico-64.png")
def favicon():
    response = make_response(send_file(BASE_DIR / "ico-64.png", mimetype="image/png"))
    response.headers["Cache-Control"] = "public, max-age=604800, immutable"
    return response

@app.route("/api/daily")
def api_daily():
    date_str = _validate_date(request.args.get("date", ""))
    summary = query_daily_summary(date_str)
    total_seconds = sum(item["total_seconds"] for item in summary)
    _attach_app_meta(summary, total_seconds)
    return jsonify({
        "date": date_str,
        "total_seconds": total_seconds,
        "total_formatted": _format_duration(total_seconds),
        "app_count": len(summary),
        "apps": summary,
    })

@app.route("/api/hourly")
def api_hourly():
    date_str = _validate_date(request.args.get("date", ""))
    distribution = query_hourly_distribution(date_str)
    return jsonify({
        "date": date_str,
        "hours": distribution,
    })

@app.route("/api/weekly")
def api_weekly():
    weekly = query_weekly_summary()
    for day in weekly:
        day["total_formatted"] = _format_duration(day["total_seconds"])
    total = sum(d["total_seconds"] for d in weekly)
    avg = total / len(weekly) if weekly else 0
    return jsonify({
        "days": weekly,
        "total_seconds": total,
        "total_formatted": _format_duration(total),
        "avg_seconds": avg,
        "avg_formatted": _format_duration(avg),
    })

@app.route("/api/period")
def api_period():
    view = request.args.get("view", "daily")
    if view not in {"daily", "weekly", "monthly", "yearly", "total"}:
        view = "daily"
    date_str = _validate_date(request.args.get("date", ""))
    if view == "daily":
        summary = query_daily_summary(date_str)
        total_seconds = sum(item["total_seconds"] for item in summary)
        return jsonify({
            "view": view,
            "date": date_str,
            "title": date_str,
            "total_seconds": total_seconds,
            "total_formatted": _format_duration(total_seconds),
            "app_count": len(summary),
            "apps": _attach_app_meta(summary, total_seconds),
            "bars": [],
        })
    return jsonify(_period_payload(view, date_str))

@app.route("/api/dates")
def api_dates():
    result = query_date_range()
    if result:
        return jsonify({"min_date": result[0], "max_date": result[1]})
    return jsonify({"min_date": None, "max_date": None})

def run_web_server(host="127.0.0.1", port=5000):
    init_db()
    app.run(host=host, port=port, debug=False, use_reloader=False)