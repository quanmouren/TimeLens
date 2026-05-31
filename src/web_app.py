import ctypes
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
_EXE_PATH_CACHE: dict[str, tuple[str, int] | None] = {}
_ICON_SIZE = 32


class _SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", ctypes.c_void_p),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", ctypes.c_ulong),
        ("szDisplayName", ctypes.c_wchar * 260),
        ("szTypeName", ctypes.c_wchar * 80),
    ]


def _clean_icon_path(path: str) -> str:
    path = os.path.expandvars((path or "").strip().strip('"'))
    if path.startswith("@"):
        path = path[1:]
    return path


def _parse_icon_location(value: str) -> tuple[str, int]:
    value = (value or "").strip()
    if value.startswith('"') and '"' in value[1:]:
        end_quote = value.find('"', 1)
        path = _clean_icon_path(value[1:end_quote])
        rest = value[end_quote + 1:].strip()
        if rest.startswith(","):
            try:
                return path, int(rest[1:].strip())
            except ValueError:
                return path, 0
        return path, 0

    if "," in value:
        path, index = value.rsplit(",", 1)
        try:
            return _clean_icon_path(path), int(index.strip())
        except ValueError:
            pass
    return value, 0


def _existing_icon_location(value: str) -> tuple[str, int] | None:
    path, index = _parse_icon_location(value)
    if path and os.path.exists(path):
        return path, index
    return None


def _matches_app_key(text: str, process_name: str, app_name: str = "") -> bool:
    text = (text or "").lower()
    process = (process_name or "").lower()
    process_stem = process[:-4] if process.endswith(".exe") else process
    app = (app_name or "").lower()
    return bool(
        (process and process in text)
        or (process_stem and process_stem in text)
        or (app and app in text)
    )

def _resolve_exe_path(process_name: str, app_name: str = "", exe_path: str = "") -> tuple[str, int] | None:
    explicit = _existing_icon_location(exe_path)
    if explicit:
        return explicit

    key = f"{process_name.lower()}|{app_name.lower()}"
    if key in _EXE_PATH_CACHE:
        return _EXE_PATH_CACHE[key]

    path = shutil.which(process_name)
    if path:
        _EXE_PATH_CACHE[key] = (path, 0)
        return path, 0

    try:
        import psutil

        for proc in psutil.process_iter(["name", "exe"]):
            if (proc.info.get("name") or "").lower() == process_name.lower():
                exe = proc.info.get("exe")
                if exe and os.path.exists(exe):
                    _EXE_PATH_CACHE[key] = (exe, 0)
                    return exe, 0
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
                        _EXE_PATH_CACHE[key] = (exe, 0)
                        return exe, 0
            except OSError:
                continue

    uninstall_roots = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for subkey in uninstall_roots:
            try:
                with winreg.OpenKey(root, subkey) as uninstall_key:
                    for i in range(winreg.QueryInfoKey(uninstall_key)[0]):
                        try:
                            child_name = winreg.EnumKey(uninstall_key, i)
                            with winreg.OpenKey(uninstall_key, child_name) as child_key:
                                display_name = ""
                                display_icon = ""
                                try:
                                    display_name, _ = winreg.QueryValueEx(child_key, "DisplayName")
                                except OSError:
                                    pass
                                try:
                                    display_icon, _ = winreg.QueryValueEx(child_key, "DisplayIcon")
                                except OSError:
                                    pass

                                if not display_icon:
                                    continue
                                if not _matches_app_key(display_name, process_name, app_name):
                                    continue

                                icon_location = _existing_icon_location(display_icon)
                                if icon_location:
                                    _EXE_PATH_CACHE[key] = icon_location
                                    return icon_location
                        except OSError:
                            continue
            except OSError:
                continue

    _EXE_PATH_CACHE[key] = None
    return None


def _icon_handle_from_shell(path: str):
    shinfo = _SHFILEINFOW()
    flags = 0x000000100 | 0x000000000
    result = ctypes.windll.shell32.SHGetFileInfoW(
        path,
        0,
        ctypes.byref(shinfo),
        ctypes.sizeof(shinfo),
        flags,
    )
    return shinfo.hIcon if result else None


def _draw_icon_to_png(hicon) -> bytes | None:
    import win32gui
    import win32ui

    screen_dc = win32gui.GetDC(0)
    hdc = win32ui.CreateDCFromHandle(screen_dc)
    mem_dc = hdc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(hdc, _ICON_SIZE, _ICON_SIZE)
    old_bmp = mem_dc.SelectObject(bmp)
    brush = win32gui.GetStockObject(0)
    win32gui.FillRect(mem_dc.GetSafeHdc(), (0, 0, _ICON_SIZE, _ICON_SIZE), brush)
    win32gui.DrawIconEx(
        mem_dc.GetSafeHdc(),
        0,
        0,
        hicon,
        _ICON_SIZE,
        _ICON_SIZE,
        0,
        None,
        3,
    )

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

    img = img.resize((24, 24), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _extract_icon_bytes(process_name: str, app_name: str = "", exe_path: str = "") -> bytes | None:
    cache_key = "|".join([process_name or "", app_name or "", exe_path or ""])
    if cache_key in _ICON_CACHE:
        return _ICON_CACHE[cache_key]

    try:
        import win32gui

        icon_location = _resolve_exe_path(process_name, app_name, exe_path)
        if not icon_location:
            _ICON_CACHE[cache_key] = b""
            return None
        resolved_path, icon_index = icon_location

        large_icons, small_icons = win32gui.ExtractIconEx(resolved_path, icon_index, 1)
        hicon = large_icons[0] if large_icons else small_icons[0] if small_icons else None
        destroy_icons = large_icons + small_icons
        if not hicon:
            hicon = _icon_handle_from_shell(resolved_path)
            destroy_icons = [hicon] if hicon else []

        if not hicon:
            _ICON_CACHE[cache_key] = b""
            return None

        icon_bytes = _draw_icon_to_png(hicon)
        for icon in destroy_icons:
            if icon:
                win32gui.DestroyIcon(icon)

        _ICON_CACHE[cache_key] = icon_bytes or b""
        return icon_bytes

    except Exception:
        _ICON_CACHE[cache_key] = b""
        return None

@app.route("/api/icon/<process_name>")
def api_icon(process_name: str):
    app_name = request.args.get("app", "")
    exe_path = request.args.get("path", "")
    icon_bytes = _extract_icon_bytes(process_name, app_name, exe_path)
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
