from __future__ import annotations

from dataclasses import replace
import webbrowser

from PySide6.QtCore import QEasingCurve, QPoint, QRect, QPropertyAnimation, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.config.config_manager import AppSettings, ConfigManager, WindowSettings
from app.services.market_data import MarketDataService, QuoteResult, StockQuote, StockSearchResult


QUOTE_COLUMNS = (
    ("名称", 76, 2),
    ("代码", 62, 1),
    ("现价", 64, 1),
    ("涨跌额", 66, 1),
    ("涨跌幅", 66, 1),
    ("换手率", 62, 1),
    ("成交量", 72, 1),
    ("成交额", 82, 1),
)


class QuoteWorker(QThread):
    finished = Signal(object)

    def __init__(self, market_data: MarketDataService, stocks: list[str]) -> None:
        super().__init__()
        self._market_data = market_data
        self._stocks = stocks

    def run(self) -> None:
        self.finished.emit(self._market_data.fetch_quotes(self._stocks))


class ConnectionCheckWorker(QThread):
    finished = Signal(object)

    def __init__(self, cookie: str, stocks: list[str]) -> None:
        super().__init__()
        self._cookie = cookie
        self._stocks = stocks

    def run(self) -> None:
        service = MarketDataService()
        service.set_cookie(self._cookie)
        ok, message = service.check_connection(self._stocks)
        self.finished.emit((ok, message))


class StockSearchWorker(QThread):
    finished = Signal(object)

    def __init__(self, keyword: str) -> None:
        super().__init__()
        self._keyword = keyword

    def run(self) -> None:
        try:
            results = MarketDataService().search_stocks(self._keyword)
            self.finished.emit((results, None))
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(([], str(exc)))


class FloatingWindow(QWidget):
    RESIZE_MARGIN = 16
    MIN_EXPANDED_WIDTH = 700
    MIN_EXPANDED_HEIGHT = 220

    def __init__(self, config: ConfigManager, market_data: MarketDataService) -> None:
        super().__init__()
        self._config = config
        self._market_data = market_data
        self._settings = config.load_settings()
        saved_cookie = config.load_cookie()
        if saved_cookie:
            self._market_data.set_cookie(saved_cookie)
        self._drag_offset: QPoint | None = None
        self._resize_origin: QPoint | None = None
        self._resize_start_geometry: QRect | None = None
        self._worker: QuoteWorker | None = None
        self._expanded = False
        self._settings_dialog: SettingsDialog | None = None
        self._search_dialog: StockSearchDialog | None = None
        self._last_result: QuoteResult | None = None

        self._rows_layout = QVBoxLayout()
        self._status_label = QLabel("准备刷新")
        self._time_label = QLabel("--:--:--")
        self._summary_title = QLabel("StockFloat")
        self._summary_text = QLabel("等待刷新")
        self._summary_time = QLabel("--:--")
        self._expanded_panel = QFrame()
        self._collapsed_panel = QFrame()
        self._pin_button: QToolButton | None = None
        self._collapse_timer = QTimer(self)
        self._resize_animation = QPropertyAnimation(self, b"geometry", self)

        self._setup_window()
        self._build_ui()
        self._apply_mode(expanded=False, animated=False)

        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.timeout.connect(self._collapse_if_allowed)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_quotes)
        self._timer.start(self._settings.refresh_interval_seconds * 1000)
        self.refresh_quotes()

    def refresh_quotes(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        stocks = self._config.load_stocks()
        self._status_label.setText("刷新中...")
        self._summary_text.setText("刷新中...")
        self._worker = QuoteWorker(self._market_data, stocks)
        self._worker.finished.connect(self._handle_quotes)
        self._worker.finished.connect(self._clear_worker)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def open_settings(self) -> None:
        self._apply_mode(expanded=True, animated=True)
        if self._settings_dialog is not None:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dialog = SettingsDialog(self._config, self._settings, self)
        self._settings_dialog = dialog
        dialog.settings_saved.connect(self._apply_settings)
        dialog.finished.connect(self._settings_closed)
        dialog.show()

    def open_search(self) -> None:
        self._apply_mode(expanded=True, animated=True)
        if self._search_dialog is not None:
            self._search_dialog.raise_()
            self._search_dialog.activateWindow()
            return
        dialog = StockSearchDialog(self)
        self._search_dialog = dialog
        dialog.stock_selected.connect(self.add_stock)
        dialog.finished.connect(self._search_closed)
        dialog.show()

    def add_stock(self, code: str) -> None:
        normalized = code.strip().zfill(6)
        if not normalized:
            return
        stocks = self._config.load_stocks()
        if normalized not in stocks:
            stocks.append(normalized)
            self._config.save_stocks(stocks)
        self._status_label.setText(f"已加入自选: {normalized}")
        self.refresh_quotes()

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._collapse_timer.stop()
        self._apply_mode(expanded=True, animated=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._collapse_timer.start(self._settings.collapse_delay_ms)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton and self._can_resize_at(event.position().toPoint()):
            self._resize_origin = event.globalPosition().toPoint()
            self._resize_start_geometry = self.geometry()
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._resize_origin is not None and self._resize_start_geometry is not None:
            delta = event.globalPosition().toPoint() - self._resize_origin
            geometry = QRect(self._resize_start_geometry)
            geometry.setWidth(max(self.MIN_EXPANDED_WIDTH, geometry.width() + delta.x()))
            geometry.setHeight(max(self.MIN_EXPANDED_HEIGHT, geometry.height() + delta.y()))
            self.setGeometry(geometry)
            event.accept()
            return
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        self._update_resize_cursor(event.position().toPoint())

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._resize_origin = None
        self._resize_start_geometry = None
        self._drag_offset = None
        self._save_window_geometry()
        self._update_resize_cursor(event.position().toPoint())
        event.accept()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(1500)
        super().closeEvent(event)

    def _setup_window(self) -> None:
        self._apply_window_flags()
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowOpacity(self._settings.opacity)
        self.setGeometry(
            self._settings.window.x,
            self._settings.window.y,
            self._settings.collapsed_width,
            self._settings.collapsed_height,
        )
        self.setMinimumSize(160, 56)

    def _apply_window_flags(self) -> None:
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self._settings.always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._collapsed_panel)
        root.addWidget(self._expanded_panel)
        self._build_collapsed_panel()
        self._build_expanded_panel()
        self.setStyleSheet(_stylesheet())

    def _build_collapsed_panel(self) -> None:
        self._collapsed_panel.setObjectName("panel")
        layout = QHBoxLayout(self._collapsed_panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        pulse = QLabel()
        pulse.setObjectName("pulse")
        pulse.setFixedSize(10, 10)
        layout.addWidget(pulse)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        self._summary_title.setObjectName("compactTitle")
        self._summary_text.setObjectName("compactText")
        text_box.addWidget(self._summary_title)
        text_box.addWidget(self._summary_text)
        layout.addLayout(text_box, 1)

        self._summary_time.setObjectName("muted")
        layout.addWidget(self._summary_time)

    def _build_expanded_panel(self) -> None:
        self._expanded_panel.setObjectName("panel")
        panel_layout = QVBoxLayout(self._expanded_panel)
        panel_layout.setContentsMargins(14, 12, 14, 12)
        panel_layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("StockFloat")
        title.setObjectName("title")
        self._time_label.setObjectName("muted")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._time_label)
        header.addWidget(_tool_button("搜索添加自选", "🔎", self.open_search))
        header.addWidget(_tool_button("刷新", "R", self.refresh_quotes))
        self._pin_button = _tool_button("钉在顶层", "", self._toggle_always_on_top)
        self._pin_button.setCheckable(True)
        self._sync_pin_button()
        header.addWidget(self._pin_button)
        header.addWidget(_tool_button("设置", "S", self.open_settings))
        header.addWidget(_tool_button("隐藏", "H", self.hide))
        header.addWidget(_tool_button("退出", "X", QApplication.quit))
        panel_layout.addLayout(header)

        column_header = QGridLayout()
        column_header.setHorizontalSpacing(8)
        column_header.setContentsMargins(10, 0, 10, 0)
        _apply_quote_column_widths(column_header)
        for col, (text, _, _) in enumerate(QUOTE_COLUMNS):
            label = QLabel(text)
            label.setObjectName("header")
            if col >= 2:
                label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            column_header.addWidget(label, 0, col)
        panel_layout.addLayout(column_header)

        self._rows_layout.setSpacing(6)
        panel_layout.addLayout(self._rows_layout)
        panel_layout.addStretch(1)

        footer = QHBoxLayout()
        self._status_label.setObjectName("status")
        footer.addWidget(self._status_label, 1)
        opacity_label = QLabel("透明度")
        opacity_label.setObjectName("header")
        footer.addWidget(opacity_label)
        slider = QSlider(Qt.Horizontal)
        slider.setObjectName("opacitySlider")
        slider.setRange(35, 100)
        slider.setValue(int(self._settings.opacity * 100))
        slider.setFixedWidth(110)
        slider.valueChanged.connect(self._change_opacity)
        footer.addWidget(slider)
        resize_hint = QLabel("◢")
        resize_hint.setObjectName("resizeHint")
        resize_hint.setToolTip("拖拽调整看板大小")
        footer.addWidget(resize_hint)
        panel_layout.addLayout(footer)

    def _apply_mode(self, expanded: bool, animated: bool) -> None:
        if self._expanded == expanded and self._expanded_panel.isVisible() == expanded:
            return
        self._expanded = expanded
        self._collapsed_panel.setVisible(not expanded)
        self._expanded_panel.setVisible(expanded)

        target_width = (
            max(self.MIN_EXPANDED_WIDTH, self._settings.window.width)
            if expanded
            else self._settings.collapsed_width
        )
        target_height = self._settings.window.height if expanded else self._settings.collapsed_height
        target = self.geometry()
        target.setWidth(target_width)
        target.setHeight(target_height)

        if animated:
            self._resize_animation.stop()
            self._resize_animation.setDuration(170)
            self._resize_animation.setEasingCurve(QEasingCurve.OutCubic)
            self._resize_animation.setStartValue(self.geometry())
            self._resize_animation.setEndValue(target)
            self._resize_animation.start()
        else:
            self.setGeometry(target)

    def _collapse_if_allowed(self) -> None:
        if self._settings_dialog is not None or self._search_dialog is not None or self.underMouse():
            return
        self._apply_mode(expanded=False, animated=True)

    def _handle_quotes(self, result: QuoteResult) -> None:
        self._last_result = result
        self._clear_rows()
        for quote in result.quotes:
            self._rows_layout.addWidget(_QuoteRow(quote))

        self._time_label.setText(result.updated_at.strftime("%H:%M:%S"))
        self._summary_time.setText(result.updated_at.strftime("%H:%M"))
        self._summary_text.setText(_summary_text(result.quotes, result.error))
        if result.error:
            prefix = "使用缓存" if result.stale else "刷新失败"
            self._status_label.setText(f"{prefix}: {result.error[:80]}")
        else:
            self._status_label.setText("已更新")

    def _clear_worker(self) -> None:
        self._worker = None

    def _can_resize_at(self, position: QPoint) -> bool:
        return self._expanded and position.x() >= self.width() - self.RESIZE_MARGIN and position.y() >= self.height() - self.RESIZE_MARGIN

    def _update_resize_cursor(self, position: QPoint) -> None:
        if self._resize_origin is not None or self._can_resize_at(position):
            self.setCursor(QCursor(Qt.SizeFDiagCursor))
        else:
            self.unsetCursor()

    def _settings_closed(self) -> None:
        self._settings_dialog = None
        self._collapse_timer.start(self._settings.collapse_delay_ms)

    def _search_closed(self) -> None:
        self._search_dialog = None
        self._collapse_timer.start(self._settings.collapse_delay_ms)

    def _apply_settings(self, settings: AppSettings, stocks: list[str], cookie: str) -> None:
        old_top = self._settings.always_on_top
        self._settings = settings
        self._config.save_settings(settings)
        self._config.save_stocks(stocks)
        self._config.save_cookie(cookie)
        self._market_data.set_cookie(cookie)
        self.setWindowOpacity(settings.opacity)
        self._timer.start(settings.refresh_interval_seconds * 1000)
        if old_top != settings.always_on_top:
            self._apply_window_flags()
            self.show()
        self._sync_pin_button()
        self.refresh_quotes()

    def _toggle_always_on_top(self) -> None:
        was_visible = self.isVisible()
        self._settings = replace(self._settings, always_on_top=not self._settings.always_on_top)
        self._config.save_settings(self._settings)
        self._apply_window_flags()
        if was_visible:
            self.show()
            self.raise_()
            self.activateWindow()
        self._sync_pin_button()

    def _sync_pin_button(self) -> None:
        if self._pin_button is None:
            return
        self._pin_button.setChecked(self._settings.always_on_top)
        self._pin_button.setText("📌" if self._settings.always_on_top else "📍")
        self._pin_button.setToolTip("取消置顶" if self._settings.always_on_top else "钉在顶层")

    def _change_opacity(self, value: int) -> None:
        opacity = value / 100
        self._settings = replace(self._settings, opacity=opacity)
        self.setWindowOpacity(opacity)
        self._config.save_settings(self._settings)

    def _save_window_geometry(self) -> None:
        if self._expanded:
            self._settings = replace(
                self._settings,
                window=WindowSettings(self.x(), self.y(), self.width(), self.height()),
            )
        else:
            self._settings = replace(
                self._settings,
                window=WindowSettings(
                    self.x(),
                    self.y(),
                    self._settings.window.width,
                    self._settings.window.height,
                ),
            )
        self._config.save_settings(self._settings)

    def _clear_rows(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


class SettingsDialog(QDialog):
    settings_saved = Signal(object, object, str)

    def __init__(self, config: ConfigManager, settings: AppSettings, parent: QWidget) -> None:
        super().__init__(parent)
        self._config = config
        self._settings = settings
        self._check_worker: ConnectionCheckWorker | None = None
        self.setWindowTitle("StockFloat 设置")
        self.setModal(False)
        self.resize(440, 520)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        stock_box = QFrame()
        stock_box.setObjectName("settingsBox")
        stock_layout = QVBoxLayout(stock_box)
        stock_layout.addWidget(QLabel("自选股"))
        self._stock_list = QListWidget()
        self._stock_list.setSelectionMode(QAbstractItemView.SingleSelection)
        for stock in self._config.load_stocks():
            self._stock_list.addItem(stock)
        stock_layout.addWidget(self._stock_list)

        add_row = QHBoxLayout()
        self._stock_input = QLineEdit()
        self._stock_input.setPlaceholderText("输入股票代码，例如 000001")
        add_button = QPushButton("添加")
        remove_button = QPushButton("删除")
        up_button = QPushButton("上移")
        down_button = QPushButton("下移")
        add_button.clicked.connect(self._add_stock)
        remove_button.clicked.connect(self._remove_stock)
        up_button.clicked.connect(lambda: self._move_stock(-1))
        down_button.clicked.connect(lambda: self._move_stock(1))
        add_row.addWidget(self._stock_input, 1)
        add_row.addWidget(add_button)
        add_row.addWidget(remove_button)
        add_row.addWidget(up_button)
        add_row.addWidget(down_button)
        stock_layout.addLayout(add_row)
        root.addWidget(stock_box)

        settings_box = QFrame()
        settings_box.setObjectName("settingsBox")
        settings_layout = QGridLayout(settings_box)
        self._top_check = QCheckBox("窗口置顶")
        self._top_check.setChecked(self._settings.always_on_top)
        self._opacity_slider = QSlider(Qt.Horizontal)
        self._opacity_slider.setRange(35, 100)
        self._opacity_slider.setValue(int(self._settings.opacity * 100))
        self._refresh_spin = QSpinBox()
        self._refresh_spin.setRange(3, 3600)
        self._refresh_spin.setValue(self._settings.refresh_interval_seconds)
        self._collapse_delay_spin = QSpinBox()
        self._collapse_delay_spin.setRange(0, 5000)
        self._collapse_delay_spin.setSingleStep(100)
        self._collapse_delay_spin.setSuffix(" ms")
        self._collapse_delay_spin.setValue(self._settings.collapse_delay_ms)
        settings_layout.addWidget(self._top_check, 0, 0, 1, 2)
        settings_layout.addWidget(QLabel("透明度"), 1, 0)
        settings_layout.addWidget(self._opacity_slider, 1, 1)
        settings_layout.addWidget(QLabel("刷新间隔/秒"), 2, 0)
        settings_layout.addWidget(self._refresh_spin, 2, 1)
        settings_layout.addWidget(QLabel("移出收起延迟"), 3, 0)
        settings_layout.addWidget(self._collapse_delay_spin, 3, 1)
        root.addWidget(settings_box)

        cookie_box = QFrame()
        cookie_box.setObjectName("settingsBox")
        cookie_layout = QVBoxLayout(cookie_box)
        cookie_layout.addWidget(QLabel("东方财富 Cookie"))
        self._cookie_edit = QTextEdit()
        self._cookie_edit.setPlaceholderText("可选。接口不可用时，从 Chrome Network 复制 Cookie 头内容。")
        self._cookie_edit.setPlainText(self._config.load_cookie())
        self._cookie_edit.setFixedHeight(96)
        cookie_layout.addWidget(self._cookie_edit)

        cookie_actions = QHBoxLayout()
        open_button = QPushButton("打开东方财富")
        check_button = QPushButton("检测接口")
        open_button.clicked.connect(self._open_eastmoney)
        check_button.clicked.connect(self._check_connection)
        cookie_actions.addWidget(open_button)
        cookie_actions.addWidget(check_button)
        cookie_actions.addStretch(1)
        cookie_layout.addLayout(cookie_actions)

        self._connection_label = QLabel("接口不可用时，先在本机浏览器打开东方财富行情页完成验证。")
        self._connection_label.setObjectName("status")
        self._connection_label.setWordWrap(True)
        cookie_layout.addWidget(self._connection_label)
        root.addWidget(cookie_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.setStyleSheet(_stylesheet())

    def _add_stock(self) -> None:
        code = self._stock_input.text().strip()
        if not code:
            return
        normalized = code.zfill(6)
        existing = {self._stock_list.item(i).text() for i in range(self._stock_list.count())}
        if normalized not in existing:
            self._stock_list.addItem(normalized)
        self._stock_input.clear()

    def _remove_stock(self) -> None:
        row = self._stock_list.currentRow()
        if row >= 0:
            self._stock_list.takeItem(row)

    def _move_stock(self, delta: int) -> None:
        row = self._stock_list.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= self._stock_list.count():
            return
        item = self._stock_list.takeItem(row)
        self._stock_list.insertItem(target, item)
        self._stock_list.setCurrentRow(target)

    def _save(self) -> None:
        stocks = [self._stock_list.item(i).text() for i in range(self._stock_list.count())]
        settings = replace(
            self._settings,
            refresh_interval_seconds=self._refresh_spin.value(),
            opacity=self._opacity_slider.value() / 100,
            always_on_top=self._top_check.isChecked(),
            collapse_delay_ms=self._collapse_delay_spin.value(),
        )
        self.settings_saved.emit(settings, stocks, self._cookie_edit.toPlainText().strip())
        self.accept()

    def _open_eastmoney(self) -> None:
        webbrowser.open("https://quote.eastmoney.com/center/gridlist.html#hs_a_board")
        self._connection_label.setText("已打开东方财富。页面加载后如有验证，请在浏览器里手动完成。")

    def _check_connection(self) -> None:
        if self._check_worker is not None and self._check_worker.isRunning():
            return
        self._connection_label.setText("正在检测接口...")
        self._check_worker = ConnectionCheckWorker(
            self._cookie_edit.toPlainText().strip(),
            [self._stock_list.item(i).text() for i in range(self._stock_list.count())],
        )
        self._check_worker.finished.connect(self._handle_connection_result)
        self._check_worker.finished.connect(self._clear_check_worker)
        self._check_worker.finished.connect(self._check_worker.deleteLater)
        self._check_worker.start()

    def _handle_connection_result(self, result: tuple[bool, str]) -> None:
        ok, message = result
        prefix = "检测成功" if ok else "检测失败"
        self._connection_label.setText(f"{prefix}: {message[:160]}")

    def _clear_check_worker(self) -> None:
        self._check_worker = None


class StockSearchDialog(QDialog):
    stock_selected = Signal(str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._search_worker: StockSearchWorker | None = None
        self.setWindowTitle("搜索股票")
        self.setModal(False)
        self.resize(380, 360)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        search_row = QHBoxLayout()
        self._keyword_input = QLineEdit()
        self._keyword_input.setPlaceholderText("输入股票代码或名称")
        self._keyword_input.returnPressed.connect(self._search)
        search_button = QPushButton("搜索")
        search_button.clicked.connect(self._search)
        search_row.addWidget(self._keyword_input, 1)
        search_row.addWidget(search_button)
        root.addLayout(search_row)

        self._result_list = QListWidget()
        self._result_list.itemDoubleClicked.connect(lambda _: self._add_selected())
        root.addWidget(self._result_list, 1)

        self._status_label = QLabel("输入关键词后搜索，双击结果可加入自选。")
        self._status_label.setObjectName("status")
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        actions = QHBoxLayout()
        add_button = QPushButton("加入自选")
        close_button = QPushButton("关闭")
        add_button.clicked.connect(self._add_selected)
        close_button.clicked.connect(self.close)
        actions.addStretch(1)
        actions.addWidget(add_button)
        actions.addWidget(close_button)
        root.addLayout(actions)
        self.setStyleSheet(_stylesheet())

    def _search(self) -> None:
        keyword = self._keyword_input.text().strip()
        if not keyword or (self._search_worker is not None and self._search_worker.isRunning()):
            return
        self._status_label.setText("搜索中...")
        self._result_list.clear()
        self._search_worker = StockSearchWorker(keyword)
        self._search_worker.finished.connect(self._handle_results)
        self._search_worker.finished.connect(self._clear_search_worker)
        self._search_worker.finished.connect(self._search_worker.deleteLater)
        self._search_worker.start()

    def _handle_results(self, payload: tuple[list[StockSearchResult], str | None]) -> None:
        results, error = payload
        if error:
            self._status_label.setText(f"搜索失败: {error[:160]}")
            return
        for result in results:
            item_text = f"{result.code}  {result.name}  {result.market}"
            self._result_list.addItem(item_text)
            item = self._result_list.item(self._result_list.count() - 1)
            item.setData(Qt.UserRole, result.code)
        self._status_label.setText(f"找到 {len(results)} 条结果" if results else "未找到匹配股票")

    def _add_selected(self) -> None:
        item = self._result_list.currentItem()
        if item is None:
            self._status_label.setText("请先选择一个搜索结果")
            return
        code = item.data(Qt.UserRole)
        self.stock_selected.emit(str(code))
        self._status_label.setText(f"已加入自选: {code}")

    def _clear_search_worker(self) -> None:
        self._search_worker = None


class _QuoteRow(QFrame):
    def __init__(self, quote: StockQuote) -> None:
        super().__init__()
        self.setObjectName("quoteRow")
        layout = QGridLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setHorizontalSpacing(8)
        _apply_quote_column_widths(layout)

        values = [
            quote.name,
            quote.code,
            _fmt_price(quote.price),
            _fmt_amount(quote.change_amount),
            _fmt_percent(quote.change_percent),
            _fmt_unsigned_percent(quote.turnover_rate),
            _fmt_compact_number(quote.volume),
            _fmt_compact_number(quote.turnover_amount),
        ]
        for col, value in enumerate(values):
            label = QLabel(value)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            if col in (2, 3, 4):
                label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                label.setStyleSheet(f"color: {_quote_color(quote.change_percent).name()};")
            elif col >= 5:
                label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                label.setObjectName("muted")
            layout.addWidget(label, 0, col)


def _apply_quote_column_widths(layout: QGridLayout) -> None:
    for col, (_, minimum_width, stretch) in enumerate(QUOTE_COLUMNS):
        layout.setColumnMinimumWidth(col, minimum_width)
        layout.setColumnStretch(col, stretch)


def _tool_button(tooltip: str, text: str, callback) -> QToolButton:
    button = QToolButton()
    button.setText(text)
    button.setToolTip(tooltip)
    button.clicked.connect(callback)
    return button


def _summary_text(quotes: list[StockQuote], error: str | None) -> str:
    if error:
        return "接口待验证"
    changed = [quote.change_percent for quote in quotes if quote.change_percent is not None]
    if not changed:
        return "暂无行情"
    up = sum(1 for value in changed if value > 0)
    down = sum(1 for value in changed if value < 0)
    return f"{len(changed)} 只  涨 {up} / 跌 {down}"


def _fmt_price(value: float | None) -> str:
    return "--" if value is None else f"{value:.2f}"


def _fmt_amount(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:+.2f}"


def _fmt_percent(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:+.2f}%"


def _fmt_unsigned_percent(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:.2f}%"


def _fmt_compact_number(value: float | None) -> str:
    if value is None:
        return "--"
    abs_value = abs(value)
    if abs_value >= 100000000:
        return f"{value / 100000000:.2f}亿"
    if abs_value >= 10000:
        return f"{value / 10000:.2f}万"
    return f"{value:.0f}"


def _quote_color(change_percent: float | None) -> QColor:
    if change_percent is None:
        return QColor("#9aa4b2")
    if change_percent > 0:
        return QColor("#e5484d")
    if change_percent < 0:
        return QColor("#2fb344")
    return QColor("#9aa4b2")


def _stylesheet() -> str:
    return """
    QWidget {
        color: #f5f7fb;
        font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
        font-size: 13px;
    }
    QDialog {
        background-color: #141926;
    }
    #panel {
        background-color: rgba(18, 24, 38, 225);
        border: 1px solid rgba(255, 255, 255, 34);
        border-radius: 8px;
    }
    #settingsBox {
        background-color: rgba(255, 255, 255, 14);
        border: 1px solid rgba(255, 255, 255, 22);
        border-radius: 8px;
    }
    #title {
        font-size: 16px;
        font-weight: 700;
    }
    #compactTitle {
        font-size: 14px;
        font-weight: 700;
    }
    #compactText {
        color: #cbd5e1;
        font-size: 12px;
    }
    #muted, #header, #status {
        color: #9aa4b2;
    }
    #header {
        font-size: 12px;
    }
    #status {
        font-size: 12px;
    }
    #pulse {
        background-color: #2fb344;
        border-radius: 5px;
    }
    #quoteRow {
        background-color: rgba(255, 255, 255, 18);
        border-radius: 6px;
    }
    #resizeHint {
        color: #687386;
        font-size: 14px;
        padding-left: 4px;
    }
    QToolButton, QPushButton {
        background-color: rgba(255, 255, 255, 20);
        border: 1px solid rgba(255, 255, 255, 30);
        border-radius: 6px;
        padding: 5px 8px;
    }
    QToolButton:hover, QPushButton:hover {
        background-color: rgba(255, 255, 255, 34);
    }
    QLineEdit, QTextEdit, QListWidget, QSpinBox {
        background-color: rgba(6, 10, 18, 190);
        border: 1px solid rgba(255, 255, 255, 28);
        border-radius: 6px;
        padding: 6px;
        selection-background-color: #2f6feb;
    }
    QSlider::groove:horizontal {
        height: 4px;
        background: rgba(255, 255, 255, 28);
        border-radius: 2px;
    }
    QSlider::handle:horizontal {
        width: 14px;
        margin: -5px 0;
        background: #d7e3f4;
        border-radius: 7px;
    }
    """
