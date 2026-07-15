from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import winreg


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "TimeLens"


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    main = Path(__file__).resolve().parent / "main.py"
    return f'"{Path(sys.executable).resolve()}" "{main}"'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return value == startup_command()
    except FileNotFoundError:
        return False


def set_enabled(enabled: bool) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(key, VALUE_NAME)
