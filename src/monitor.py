import ctypes
import time
import logging
import threading
from collections import Counter
from datetime import datetime, timedelta
from ctypes import wintypes

import psutil
import win32gui
import win32process
from pynput import keyboard

from database import increment_key_usage_batch, insert_usage

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
ACTIVE_FLUSH_INTERVAL_SECONDS = 10


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


def _get_foreground_info() -> tuple[str, str, str, str] | None:
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
            try:
                exe_path = proc.exe()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                exe_path = ""
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

        return process_name, app_name, exe_path, window_title

    except Exception:
        return None


def list_visible_apps() -> list[dict[str, str]]:
    """Return distinct processes that own a visible, titled top-level window."""
    found: dict[str, dict[str, str]] = {}

    def visit(hwnd, _extra):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            window_title = win32gui.GetWindowText(hwnd).strip()
            if not window_title:
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if not pid:
                return True
            proc = psutil.Process(pid)
            process_name = proc.name()
            if not process_name or process_name.lower() in _IGNORED_LOWER:
                return True
            try:
                exe_path = proc.exe()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                exe_path = ""
            app_name = process_name[:-4] if process_name.lower().endswith(".exe") else process_name
            found.setdefault(process_name.casefold(), {
                "app_name": app_name,
                "process_name": process_name,
                "exe_path": exe_path,
            })
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            pass
        return True

    try:
        win32gui.EnumWindows(visit, None)
    except OSError:
        logger.exception("枚举可见窗口失败")
    return sorted(found.values(), key=lambda item: item["app_name"].casefold())


class AppMonitor:
    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._state_lock = threading.RLock()
        self._current_process: str | None = None
        self._current_exe_path: str | None = None
        self._current_app: str | None = None
        self._current_title: str | None = None
        self._current_start: datetime | None = None

    def _flush_current(self, end_time: datetime | None = None):
        with self._state_lock:
            current = None
            if self._current_start and self._current_app:
                now = end_time or datetime.now()
                if now <= self._current_start:
                    now = self._current_start
                current = (
                    self._current_app,
                    self._current_process or "Unknown",
                    self._current_exe_path or "",
                    self._current_title or "",
                    self._current_start,
                    now,
                )
            self._current_process = None
            self._current_exe_path = None
            self._current_app = None
            self._current_title = None
            self._current_start = None
        if current:
            try:
                insert_usage(
                    app_name=current[0],
                    process_name=current[1],
                    exe_path=current[2],
                    window_title=current[3],
                    start_time=current[4],
                    end_time=current[5],
                )
            except Exception:
                logger.exception("写入使用记录失败")

    def _restart_current(self, process_name: str, app_name: str, exe_path: str, window_title: str):
        with self._state_lock:
            self._current_process = process_name
            self._current_exe_path = exe_path
            self._current_app = app_name
            self._current_title = window_title
            self._current_start = datetime.now()

    def snapshot_current(self) -> dict | None:
        with self._state_lock:
            if not self._current_start or not self._current_app or not self._current_process:
                return None
            return {
                "app_name": self._current_app,
                "process_name": self._current_process,
                "exe_path": self._current_exe_path or "",
                "start_time": self._current_start,
                "end_time": datetime.now(),
            }

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
                    process_name, app_name, exe_path, window_title = info

                    if app_name != self._current_app:
                        self._flush_current()
                        self._restart_current(process_name, app_name, exe_path, window_title)
                    else:
                        if exe_path:
                            self._current_exe_path = exe_path
                        self._current_title = window_title
                        now = datetime.now()
                        if (
                            self._current_start
                            and (now - self._current_start).total_seconds() >= ACTIVE_FLUSH_INTERVAL_SECONDS
                        ):
                            self._flush_current(end_time=now)
                            self._restart_current(process_name, app_name, exe_path, window_title)
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


_SPECIAL_KEYS = {
    keyboard.Key.space: "Space",
    keyboard.Key.enter: "Enter",
    keyboard.Key.tab: "Tab",
    keyboard.Key.backspace: "Backspace",
    keyboard.Key.delete: "Del",
    keyboard.Key.insert: "Ins",
    keyboard.Key.home: "Home",
    keyboard.Key.end: "End",
    keyboard.Key.page_up: "PgUp",
    keyboard.Key.page_down: "PgDn",
    keyboard.Key.esc: "Esc",
    keyboard.Key.caps_lock: "Caps Lock",
    keyboard.Key.shift_l: "ShiftLeft",
    keyboard.Key.shift_r: "ShiftRight",
    keyboard.Key.ctrl: "CtrlLeft",
    keyboard.Key.ctrl_l: "CtrlLeft",
    keyboard.Key.ctrl_r: "CtrlRight",
    keyboard.Key.alt: "Alt",
    keyboard.Key.alt_l: "Alt",
    keyboard.Key.alt_r: "Alt",
    keyboard.Key.cmd: "Win",
    keyboard.Key.cmd_l: "Win",
    keyboard.Key.cmd_r: "Win",
    keyboard.Key.menu: "Menu",
    keyboard.Key.up: "Up",
    keyboard.Key.down: "Down",
    keyboard.Key.left: "Left",
    keyboard.Key.right: "Right",
    keyboard.Key.print_screen: "PrtSc",
    keyboard.Key.scroll_lock: "ScrLk",
    keyboard.Key.pause: "Pause",
    keyboard.Key.num_lock: "Num",
}


def _key_name(key) -> str | None:
    if key in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[key]
    if isinstance(key, keyboard.KeyCode):
        vk = getattr(key, "vk", None)
        if isinstance(vk, int):
            if 96 <= vk <= 105:
                return f"Num{vk - 96}"
            numpad_symbols = {
                106: "Num*",
                107: "Num+",
                109: "Num-",
                110: "Num.",
                111: "Num/",
            }
            if vk in numpad_symbols:
                return numpad_symbols[vk]
        char = key.char
        if not char or char.isspace():
            return None
        return char.upper() if char.isalpha() else char
    text = str(key)
    if text.startswith("Key.f") and text[5:].isdigit():
        return text[4:].upper()
    return None


class KeyboardMonitor:
    """Privacy-preserving key counter: stores key totals, never typed text or order."""

    def __init__(self):
        self._listener: keyboard.Listener | None = None
        self._running = False
        self._flush_thread: threading.Thread | None = None
        self._pending: Counter[tuple[str, int, str]] = Counter()
        self._pressed: set[str] = set()
        self._lock = threading.Lock()

    def _on_press(self, key):
        name = _key_name(key)
        if not name:
            return
        now = datetime.now()
        with self._lock:
            if name in self._pressed:
                return
            self._pressed.add(name)
            self._pending[(now.strftime("%Y-%m-%d"), now.hour, name)] += 1

    def _on_release(self, key):
        name = _key_name(key)
        if not name:
            return
        with self._lock:
            self._pressed.discard(name)

    def _flush(self):
        with self._lock:
            pending = self._pending
            self._pending = Counter()
        if not pending:
            return
        rows = [
            (date, hour, name, count)
            for (date, hour, name), count in pending.items()
        ]
        try:
            increment_key_usage_batch(rows)
        except Exception:
            with self._lock:
                self._pending.update(pending)
            logger.exception("写入按键统计失败")

    def _flush_loop(self):
        while self._running:
            time.sleep(1)
            self._flush()

    def start(self):
        if self._listener:
            return
        self._running = True
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def stop(self):
        if not self._listener:
            return
        self._running = False
        self._listener.stop()
        self._listener.join(timeout=3)
        self._listener = None
        with self._lock:
            self._pressed.clear()
        if self._flush_thread:
            self._flush_thread.join(timeout=2)
            self._flush_thread = None
        self._flush()
