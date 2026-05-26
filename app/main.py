from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.config.config_manager import ConfigManager
from app.services.market_data import MarketDataService
from app.ui.floating_window import FloatingWindow
from app.ui.tray import StockTray


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("StockFloat")
    app.setQuitOnLastWindowClosed(False)

    config = ConfigManager()
    market_data = MarketDataService()

    window = FloatingWindow(config=config, market_data=market_data)
    tray = StockTray(window=window)
    tray.show()

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
