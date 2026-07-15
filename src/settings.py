from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TimeLensSettings:
    port: int = 6001


def settings_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "config.json"
    return Path(__file__).resolve().parent / "config.json"


def load_settings(path: Path | None = None) -> TimeLensSettings:
    path = path or settings_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"port": 6001}, indent=2) + "\n", encoding="utf-8")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取配置文件：{path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("config.json 必须是 JSON 对象")
    port = payload.get("port", 6001)
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        raise RuntimeError("config.json 中的 port 必须是 1024–65535 的整数")
    return TimeLensSettings(port=port)
