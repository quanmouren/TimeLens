import threading
import webbrowser
import sys
from pathlib import Path

import pystray
from PIL import Image
from autostart import is_enabled, set_enabled
from database import init_db
from monitor import AppMonitor, KeyboardMonitor
from settings import load_settings
from web_app import run_web_server

WEB_HOST = "127.0.0.1"
WEB_URL = f"http://{WEB_HOST}:6001"
APP_NAME = "TimeLens"
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
ICON_PATH = BASE_DIR / "ico-64.png"


def dashboard_url(port: int) -> str:
    return f"http://{WEB_HOST}:{port}"


def create_tray_icon() -> Image.Image:
    return Image.open(ICON_PATH).convert("RGBA")


def open_dashboard(icon=None, item=None):
    webbrowser.open(WEB_URL)


def quit_app(icon, item):
    icon.stop()


def _toggle_autostart(icon=None, item=None):
    set_enabled(not is_enabled())
    _refresh_menu(icon)


def _refresh_menu(icon: pystray.Icon):
    if icon:
        icon.menu = _build_menu()


def _build_menu() -> pystray.Menu:
    return pystray.Menu(
        pystray.MenuItem(f"打开 {APP_NAME}", open_dashboard, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "开机自启",
            _toggle_autostart,
            checked=lambda _item: is_enabled(),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", quit_app),
    )


def main():
    global WEB_URL
    settings = load_settings()
    WEB_URL = dashboard_url(settings.port)
    init_db()

    monitor = AppMonitor()
    monitor.start()
    print("[TimeLens] 应用监控已启动")

    keyboard_monitor = KeyboardMonitor()
    keyboard_monitor.start()
    print("[TimeLens] 按键统计已启动（仅记录键位次数）")

    web_thread = threading.Thread(
        target=run_web_server,
        kwargs={"host": WEB_HOST, "port": settings.port, "app_monitor": monitor},
        daemon=True,
    )
    web_thread.start()
    print(f"[TimeLens] Web 仪表盘启动中: {WEB_URL}")

    icon = pystray.Icon(
        name=APP_NAME,
        icon=create_tray_icon(),
        title=APP_NAME,
        menu=_build_menu(),
    )

    print("[TimeLens] 程序已最小化到系统托盘")
    icon.run()

    monitor.stop()
    keyboard_monitor.stop()
    print("程序已退出")


if __name__ == "__main__":
    main()
