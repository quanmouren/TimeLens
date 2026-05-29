import ctypes
import time
import logging
import threading
from datetime import datetime, timedelta
from ctypes import wintypes

import psutil
import win32gui
import win32process

from database import insert_usage

logger = logging.getLogger(__name__)

# 要过滤的进程名
IGNORED_PROCESSES = {
    "explorer.exe",
    "SearchUI.exe",
    "SearchApp.exe",
    "ShellExperienceHost.exe",
    "StartMenuExperienceHost.exe",
    "LockApp.exe",
    "TextInputHost.exe",
    "ctfmon.exe",
}
_IGNORED_LOWER = {p.lower() for p in IGNORED_PROCESSES}

POLL_INTERVAL = 1
IDLE_CHECK_INTERVAL = 60
IDLE_GRACE_SECONDS = 30 * 60


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


def _get_idle_seconds() -> float:
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0
    tick = ctypes.windll.kernel32.GetTickCount()
    idle_ms = (tick - info.dwTime) & 0xFFFFFFFF
    return idle_ms / 1000


def _get_foreground_info() -> tuple[str, str, str] | None:
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None

        if win32gui.IsIconic(hwnd):
            return None

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid == 0:
            return None

        try:
            proc = psutil.Process(pid)
            process_name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

        if process_name.lower() in _IGNORED_LOWER:
            return None

        window_title = win32gui.GetWindowText(hwnd)
        if not window_title:
            return None

        app_name = process_name
        if app_name.lower().endswith(".exe"):
            app_name = app_name[:-4]

        return process_name, app_name, window_title

    except Exception:
        return None


class AppMonitor:
    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._current_process: str | None = None
        self._current_app: str | None = None
        self._current_title: str | None = None
        self._current_start: datetime | None = None

    def _flush_current(self, end_time: datetime | None = None):
        if self._current_start and self._current_app:
            now = end_time or datetime.now()
            if now <= self._current_start:
                now = self._current_start
            try:
                insert_usage(
                    app_name=self._current_app,
                    process_name=self._current_process or "Unknown",
                    window_title=self._current_title or "",
                    start_time=self._current_start,
                    end_time=now,
                )
            except Exception:
                logger.exception("写入使用记录失败")
        self._current_process = None
        self._current_app = None
        self._current_title = None
        self._current_start = None

    def _monitor_loop(self):
        last_idle_check = 0.0
        is_idle = False
        while self._running:
            try:
                monotonic_now = time.monotonic()
                if monotonic_now - last_idle_check >= IDLE_CHECK_INTERVAL:
                    last_idle_check = monotonic_now
                    idle_seconds = _get_idle_seconds()
                    is_idle = idle_seconds >= IDLE_GRACE_SECONDS
                    if is_idle:
                        active_until = datetime.now() - timedelta(
                            seconds=idle_seconds - IDLE_GRACE_SECONDS
                        )
                        self._flush_current(end_time=active_until)

                if is_idle:
                    time.sleep(POLL_INTERVAL)
                    continue

                info = _get_foreground_info()

                if info:
                    process_name, app_name, window_title = info

                    if app_name != self._current_app:
                        self._flush_current()
                        self._current_process = process_name
                        self._current_app = app_name
                        self._current_title = window_title
                        self._current_start = datetime.now()
                    else:
                        self._current_title = window_title
                else:
                    self._flush_current()

            except Exception:
                logger.exception("监控循环异常，继续运行")

            time.sleep(POLL_INTERVAL)

        self._flush_current()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None