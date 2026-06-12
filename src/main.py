import threading
import webbrowser
import sys
import winreg
from pathlib import Path

import pystray
from PIL import Image
from database import init_db
from monitor import AppMonitor
from web_app import run_web_server

WEB_HOST = "127.0.0.1"
WEB_PORT = 6001
WEB_URL = f"http://{WEB_HOST}:{WEB_PORT}"
APP_NAME = "TimeLens"
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
ICON_PATH = BASE_DIR / "ico-64.png"


def create_tray_icon() -> Image.Image:
    return Image.open(ICON_PATH).convert("RGBA")


def open_dashboard(icon=None, item=None):
    webbrowser.open(WEB_URL)


def quit_app(icon, item):
    icon.stop()


def _get_exe_path() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    return str(BASE_DIR / "main.py")


def _is_autostart_enabled() -> bool:
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        )
        try:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except WindowsError:
        return False


def _set_autostart(enabled: bool):
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_WRITE,
        )
        try:
            if enabled:
                exe_path = _get_exe_path()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe_path)
            else:
                winreg.DeleteValue(key, APP_NAME)
        finally:
            winreg.CloseKey(key)
    except WindowsError:
        pass


def _toggle_autostart(icon=None, item=None):
    current = _is_autostart_enabled()
    _set_autostart(not current)
    _refresh_menu(icon)


def _refresh_menu(icon: pystray.Icon):
    if icon:
        icon.menu = _build_menu()


def _build_menu() -> pystray.Menu:
    is_enabled = _is_autostart_enabled()
    return pystray.Menu(
        pystray.MenuItem(f"打开 {APP_NAME}", open_dashboard, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "开机自启",
            _toggle_autostart,
            checked=lambda item: is_enabled,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", quit_app),
    )


def main():
    init_db()

    monitor = AppMonitor()
    monitor.start()
    print("✓ 应用监控已启动")

    web_thread = threading.Thread(
        target=run_web_server,
        kwargs={"host": WEB_HOST, "port": WEB_PORT},
        daemon=True,
    )
    web_thread.start()
    print(f"✓ Web 仪表盘启动中: {WEB_URL}")

    icon = pystray.Icon(
        name=APP_NAME,
        icon=create_tray_icon(),
        title=APP_NAME,
        menu=_build_menu(),
    )

    print("✓ 程序已最小化到系统托盘")
    icon.run()

    monitor.stop()
    print("程序已退出")


if __name__ == "__main__":
    main()
