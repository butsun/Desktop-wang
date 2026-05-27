from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_STOCKS = ["000001", "600519", "300750"]


@dataclass(frozen=True)
class WindowSettings:
    x: int = 80
    y: int = 80
    width: int = 460
    height: int = 320


@dataclass(frozen=True)
class AppSettings:
    refresh_interval_seconds: int = 10
    opacity: float = 0.88
    always_on_top: bool = True
    collapse_delay_ms: int = 700
    collapsed_width: int = 220
    collapsed_height: int = 72
    window: WindowSettings = WindowSettings()


class ConfigManager:
    def __init__(self) -> None:
        self.config_dir = self._resolve_config_dir()
        self.stocks_path = self.config_dir / "stocks.json"
        self.settings_path = self.config_dir / "settings.json"
        self.cookie_path = self.config_dir / "cookie.txt"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_defaults()

    def load_stocks(self) -> list[str]:
        payload = self._read_json(self.stocks_path, {"stocks": DEFAULT_STOCKS})
        stocks = payload.get("stocks", DEFAULT_STOCKS)
        return [str(item).strip().zfill(6) for item in stocks if str(item).strip()]

    def save_stocks(self, stocks: list[str]) -> None:
        cleaned = [str(item).strip().zfill(6) for item in stocks if str(item).strip()]
        self._write_json(self.stocks_path, {"stocks": cleaned})

    def load_settings(self) -> AppSettings:
        payload = self._read_json(self.settings_path, self._default_settings_payload())
        window_payload = payload.get("window", {})
        window = WindowSettings(
            x=int(window_payload.get("x", 80)),
            y=int(window_payload.get("y", 80)),
            width=int(window_payload.get("width", 460)),
            height=int(window_payload.get("height", 320)),
        )
        return AppSettings(
            refresh_interval_seconds=max(3, int(payload.get("refresh_interval_seconds", 10))),
            opacity=min(1.0, max(0.35, float(payload.get("opacity", 0.88)))),
            always_on_top=bool(payload.get("always_on_top", True)),
            collapse_delay_ms=min(5000, max(0, int(payload.get("collapse_delay_ms", 700)))),
            collapsed_width=max(160, int(payload.get("collapsed_width", 220))),
            collapsed_height=max(56, int(payload.get("collapsed_height", 72))),
            window=window,
        )

    def save_settings(self, settings: AppSettings) -> None:
        self._write_json(
            self.settings_path,
            {
                "refresh_interval_seconds": settings.refresh_interval_seconds,
                "opacity": settings.opacity,
                "always_on_top": settings.always_on_top,
                "collapse_delay_ms": settings.collapse_delay_ms,
                "collapsed_width": settings.collapsed_width,
                "collapsed_height": settings.collapsed_height,
                "window": {
                    "x": settings.window.x,
                    "y": settings.window.y,
                    "width": settings.window.width,
                    "height": settings.window.height,
                },
            },
        )

    def save_window(self, x: int, y: int, width: int, height: int) -> None:
        payload = self._read_json(self.settings_path, self._default_settings_payload())
        payload["window"] = {"x": x, "y": y, "width": width, "height": height}
        self._write_json(self.settings_path, payload)

    def load_cookie(self) -> str:
        try:
            return self.cookie_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def save_cookie(self, cookie: str) -> None:
        self.cookie_path.write_text(cookie.strip(), encoding="utf-8")

    def _ensure_defaults(self) -> None:
        if not self.stocks_path.exists():
            self._write_json(self.stocks_path, {"stocks": DEFAULT_STOCKS})
        if not self.settings_path.exists():
            self._write_json(self.settings_path, self._default_settings_payload())

    @staticmethod
    def _resolve_config_dir() -> Path:
        system = platform.system()
        if system == "Windows":
            import os

            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
            return base / "StockFloat"
        if system == "Darwin":
            return Path.home() / "Library" / "Application Support" / "StockFloat"
        return Path.home() / ".config" / "StockFloat"

    @staticmethod
    def _default_settings_payload() -> dict[str, Any]:
        return {
            "refresh_interval_seconds": 10,
            "opacity": 0.88,
            "always_on_top": True,
            "collapse_delay_ms": 700,
            "collapsed_width": 220,
            "collapsed_height": 72,
            "window": {"x": 80, "y": 80, "width": 460, "height": 320},
        }

    @staticmethod
    def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
