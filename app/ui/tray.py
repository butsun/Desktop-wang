from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from app.ui.floating_window import FloatingWindow


class StockTray(QSystemTrayIcon):
    def __init__(self, window: FloatingWindow) -> None:
        super().__init__()
        self._window = window
        self.setIcon(_default_icon())
        self.setToolTip("StockFloat")
        self.activated.connect(self._handle_activated)
        self.setContextMenu(self._build_menu())

    def _build_menu(self) -> QMenu:
        menu = QMenu()

        toggle_action = QAction("显示/隐藏", menu)
        toggle_action.triggered.connect(self.toggle_window)
        menu.addAction(toggle_action)

        refresh_action = QAction("刷新", menu)
        refresh_action.triggered.connect(self._window.refresh_quotes)
        menu.addAction(refresh_action)

        settings_action = QAction("设置", menu)
        settings_action.triggered.connect(self._window.open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)

        return menu

    def toggle_window(self) -> None:
        if self._window.isVisible():
            self._window.hide()
            return
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _handle_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.toggle_window()


def _default_icon() -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#121826"))
    painter.setPen(QPen(QColor("#4f8cff"), 2))
    painter.drawRoundedRect(3, 3, 26, 26, 7, 7)
    painter.setPen(QPen(QColor("#e5484d"), 2))
    points = [(8, 21), (13, 15), (18, 18), (24, 10)]
    for start, end in zip(points, points[1:]):
        painter.drawLine(start[0], start[1], end[0], end[1])
    painter.end()
    return QIcon(pixmap)
