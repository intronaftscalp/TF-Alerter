import sys
import datetime
import threading
import time
import ctypes
import os
import json
import re
import subprocess
from collections import deque

# Отключаем Qt warnings и debug сообщения для чистого вывода
os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.qpa.*=false;qt.multimedia.*=false"


def _try_relaunch_with_project_venv():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    current_exe = os.path.abspath(sys.executable)
    script_path = os.path.abspath(__file__)

    candidates = [
        os.path.join(base_dir, ".venv", "Scripts", "python.exe"),
        os.path.join(base_dir, ".venv-1", "Scripts", "python.exe"),
    ]

    for candidate in candidates:
        if not os.path.exists(candidate):
            continue
        if os.path.abspath(candidate).lower() == current_exe.lower():
            continue
        try:
            print(f"[LAUNCH] Перезапуск через {candidate}")
            try:
                subprocess.call(
                    [candidate, script_path, *sys.argv[1:]],
                    cwd=base_dir,
                )
            except KeyboardInterrupt:
                pass
            return True
        except Exception:
            continue

    return False

try:
    from PyQt6.QtWidgets import (
        QApplication,
        QMainWindow,
        QVBoxLayout,
        QWidget,
        QAbstractItemView,
        QPushButton,
        QHBoxLayout,
        QCheckBox,
        QListWidgetItem,
        QToolTip,
        QMessageBox,
        QTableWidgetItem,
    )
    from PyQt6.QtGui import QColor, QIcon, QFont, QGuiApplication, QCursor
    from PyQt6.QtCore import Qt, QSettings, QTimer, QEvent, QLockFile, QStandardPaths
except ModuleNotFoundError as exc:
    if getattr(exc, "name", "") == "PyQt6":
        try:
            if _try_relaunch_with_project_venv():
                raise SystemExit(0)
        except KeyboardInterrupt:
            raise SystemExit(0)
    if getattr(exc, "name", "") == "PyQt6":
        print("[ERROR] Не найден PyQt6 в текущем Python. Запустите: .\\run.bat")
        raise SystemExit(1)
    raise
import config
import gui
import logic
from hotkey_manager import HotkeyManager
from color_picker_dialog import ColorPickerDialog
from font_picker_dialog import FontPickerDialog
from funding_alerts import FundingMonitor
from listing_alerts import ListingMonitor
from sessions_alerts import SessionMonitor
from donate_dialog import DonateDialog

# Установка App User Model ID для иконки на панели задач (Windows)
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        "MyTradeTools.TF-Alerter"
    )
except Exception:
    pass

# Логирование
# Логирование - отключено для экономии памяти и ресурсов
LOG_ENABLED = False
LOG_FILE = "debug.log"
_APP_INSTANCE_LOCK = None


def log_write(msg):
    if not LOG_ENABLED:
        return
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except:
        pass


def _acquire_instance_lock():
    app_data_dir = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if not app_data_dir:
        app_data_dir = config.BASE_DIR

    os.makedirs(app_data_dir, exist_ok=True)
    lock_path = os.path.join(app_data_dir, "tf-alerter.lock")

    lock = QLockFile(lock_path)
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        return None
    return lock


class MainWindow(QMainWindow):
    def __init__(self):
        # Чтобы иконка отображалась в панели задач Windows
        myappid = "mytrader.tfalerter.v1"
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

        super().__init__()

        # Установка иконки для окна
        self.setWindowIcon(QIcon(config.LOGO_PATH))

        # Настройки окна (безрамочное + всегда поверх)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(*config.WINDOW_SIZE)
        self.setWindowTitle("TF-Alerter")

        # Центральный виджет
        self.central_widget = QWidget()
        self.central_widget.setObjectName("mainContainer")  # Имя для точечного стиля
        self.setCentralWidget(self.central_widget)

        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # 1. Создаем заголовок
        self.title_bar = gui.CustomTitleBar(self)
        self.main_layout.addWidget(self.title_bar)

        # 2. Создаем основной интерфейс
        self.ui = gui.UI_Widget(parent=self)
        self.main_layout.addWidget(self.ui)

        # 3. Инициализация логики
        self.logic = logic.AlerterLogic(self.ui)
        self.logic.time_signal.connect(self.ui.time_label.setText)

        # Funding alerts
        self.funding_monitor = FundingMonitor(self.ui)
        self.funding_monitor.alert_signal.connect(self.on_funding_alert)
        self.funding_monitor.log_signal.connect(self.append_funding_log_text)
        self.funding_monitor.status_signal.connect(self.on_funding_status_update)

        # Listing alerts
        self.listing_monitor = ListingMonitor(self.ui)
        self.listing_monitor.listing_signal.connect(self.append_listing_log_text)
        self.listing_monitor.status_signal.connect(self.on_listing_status_update)

        # Session alerts
        self.session_monitor = SessionMonitor(self.ui)
        self.session_monitor.alert_signal.connect(self.on_session_alert)
        self.session_monitor.status_signal.connect(self.on_session_status_update)
        # Передаем ссылку на main_window в overlay для автосохранения
        self.logic.overlay.main_window = self

        # Переменная для перетаскивания окна
        self.old_pos = None

        # Флаг для отслеживания авторизованного сворачивания (через горячую клавишу)
        self._is_closing = False

        # Флаг для блокировки автосохранения во время загрузки
        self.loading_settings = True
        self.current_overlay_font = "Arial"
        self.overlay_bg_enabled = False
        self.overlay_bg_color = "#000000"
        self.overlay_move_locked = False
        self.funding_alert_counter = 0
        self.funding_alert_entries = []
        self.triggered_alerts = []  # Список завершённых алертов
        self.max_triggered_alerts = 10  # Максимум зачеркнутых алертов
        self._funding_log_view_mode = "upcoming"
        self._funding_exchange_status = {}
        self._edge_tts_queue = []
        self._edge_tts_busy = False
        self._edge_tts_started = False
        self._system_tts_queue = deque()
        self._system_tts_busy = False
        self._system_tts_lock = threading.Lock()
        self._last_funding_sound_duration_ms = 1700
        self._edge_ready_paths = deque()
        self._edge_ready_lock = threading.Lock()
        self._edge_ready_timer = QTimer()
        self._edge_ready_timer.setInterval(50)
        self._edge_ready_timer.timeout.connect(self._drain_edge_ready_paths)
        self._edge_ready_timer.start()
        self._pending_tts_entries = []
        self._pending_tts_seq = 0
        self._seen_funding_keys = set()
        self._funding_tts_sound_pending = False
        self._funding_tts_batch_active = False
        self._funding_paused = False
        self.funding_triggered_history = []
        self._funding_triggered_history_keys = set()
        self.listing_alert_entries = []
        self._listing_seen_keys = set()
        self._listing_alerted_keys = set()
        self._listing_tts_queue = deque()
        self._listing_tts_busy = False
        self._listing_edge_tts_busy = False
        self._listing_edge_tts_started = False
        self._listing_edge_ready_paths = deque()
        self._listing_edge_ready_lock = threading.Lock()
        self._listing_edge_ready_timer = QTimer()
        self._listing_edge_ready_timer.setInterval(50)
        self._listing_edge_ready_timer.timeout.connect(self._drain_listing_edge_ready)
        self._listing_edge_ready_timer.start()
        self._last_listing_sound_duration_ms = 1700
        self._listing_sound_cooldown_ms = 60000
        self._last_listing_sound_played_ms = 0
        self._listing_sound_pending_file = ""
        self._listing_sound_pending = False
        self._listing_sound_delay_timer = QTimer()
        self._listing_sound_delay_timer.setSingleShot(True)
        self._listing_sound_delay_timer.timeout.connect(
            self._play_delayed_listing_sound
        )
        self._listing_exchange_status = {}
        self._listing_log_view_mode = "upcoming"
        self.listing_alert_history = []
        self._listing_alert_history_keys = set()
        self._session_status = {}
        self._session_tts_busy = False
        self._pending_session_warning = None
        self._session_warning_retry_timer = QTimer()
        self._session_warning_retry_timer.setSingleShot(True)
        self._session_warning_retry_timer.timeout.connect(
            self._process_pending_session_warning
        )
        self._compact_window_size = tuple(config.WINDOW_SIZE)
        self._source_error_last = {}
        self._allow_minimize = False
        self._font_dialog_open = False
        self._donate_dialog = None
        self._donate_dialog_cache_key = None
        self._funding_tts_timer = QTimer()
        self._funding_tts_timer.setSingleShot(True)
        self._funding_tts_timer.timeout.connect(self._flush_funding_tts_queue)
        self._funding_clear_resume_timer = QTimer()
        self._funding_clear_resume_timer.setSingleShot(True)
        self._funding_clear_resume_timer.timeout.connect(
            self._resume_funding_after_clear
        )
        # --- ПОДКЛЮЧЕНИЕ СИГНАЛОВ ---
        self.ui.color_btn.clicked.connect(self.change_color)
        self.ui.clock_font_btn.clicked.connect(self.open_font_dialog)
        self.ui.lang_sel.currentTextChanged.connect(self.ui.change_language)

        # Подключаем переключатель отображения часов
        self.ui.cb_overlay.toggled.connect(self.toggle_overlay)
        self.ui.cb_lock_overlay_move.toggled.connect(self.toggle_overlay_move_lock)

        # --- ПОДКЛЮЧЕНИЕ СИГНАЛОВ ДЛЯ УПРАВЛЕНИЯ OVERLAY ОКНАМИ ---
        self.ui.overlay_mode_combo.currentIndexChanged.connect(self.update_overlay_mode)
        self.ui.select_app_btn.clicked.connect(self.select_overlay_app)

        # Инициализация менеджера горячих клавиш
        self.hotkey_manager = HotkeyManager(self)
        self.hotkey_manager.hotkey_pressed.connect(self.toggle_minimize)
        self.hotkey_manager.start()

        # Загружаем настройки (это вызовет apply_interface_scale автоматически)
        self.load_settings()

        # Миграция звуков (только если еще не выполнена)
        settings = QSettings("MyTradeTools", "TF-Alerter")
        if not settings.value("sounds_migrated", False, type=bool):
            try:
                config.migrate_sounds_to_subdirs()
                settings.setValue("sounds_migrated", True)
            except Exception:
                pass

        # Re-apply accent-based styles to already-created widgets
        try:
            fixed_blue = "#1e90ff"
            # Title label
            if hasattr(self, "title_bar") and hasattr(self.title_bar, "title_label"):
                self.title_bar.title_label.setStyleSheet(
                    f"color: {fixed_blue}; font-family: 'Segoe UI Semibold'; font-size: 12px; letter-spacing: 2px; background: transparent; border: none;"
                )
            # Main UI buttons
            if hasattr(self, "ui"):
                try:
                    if hasattr(self.ui, "select_app_btn"):
                        self.ui.select_app_btn.setStyleSheet(
                            self.ui._select_app_style()
                        )
                except Exception:
                    pass
        except Exception:
            pass

        # Теперь подключаем автосохранение ПОСЛЕ загрузки
        self.ui.volume_slider.valueChanged.connect(self.save_settings)
        self.ui.ov_size_slider.valueChanged.connect(self.save_settings)
        self.ui.lang_sel.currentTextChanged.connect(self.save_settings)
        self.ui.cb_overlay.toggled.connect(self.save_settings)
        self.ui.cb_lock_overlay_move.toggled.connect(self.save_settings)
        self.ui.funding_binance_check.toggled.connect(self.on_funding_exchanges_changed)
        self.ui.funding_bybit_check.toggled.connect(self.on_funding_exchanges_changed)
        self.ui.funding_okx_check.toggled.connect(self.on_funding_exchanges_changed)
        self.ui.funding_gate_check.toggled.connect(self.on_funding_exchanges_changed)
        self.ui.funding_bitget_check.toggled.connect(self.on_funding_exchanges_changed)
        self.ui.funding_enable_check.toggled.connect(self.on_funding_enable_toggled)
        self.ui.funding_minutes_edit.textChanged.connect(self.save_settings)
        self.ui.funding_threshold_pos_edit.textChanged.connect(self.save_settings)
        self.ui.funding_threshold_neg_edit.textChanged.connect(self.save_settings)
        self.ui.funding_threshold_pos_edit.textChanged.connect(
            self.on_funding_thresholds_changed
        )
        self.ui.funding_threshold_neg_edit.textChanged.connect(
            self.on_funding_thresholds_changed
        )
        self.ui.funding_volume_slider.valueChanged.connect(self.save_settings)
        self.ui.funding_clear_btn.clicked.connect(self.clear_funding_log)
        self.ui.funding_refresh_btn.clicked.connect(self.refresh_funding_data)
        self.ui.funding_log_upcoming_btn.clicked.connect(
            lambda: self.set_funding_log_view_mode("upcoming")
        )
        self.ui.funding_log_triggered_btn.clicked.connect(
            lambda: self.set_funding_log_view_mode("triggered")
        )
        self.ui.funding_log_list.itemClicked.connect(self.copy_funding_symbol)
        self.ui.funding_log_list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.ui.funding_log_list.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.ui.funding_log_list.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        funding_scrollbar = self.ui.funding_log_list.verticalScrollBar()
        funding_scrollbar.setSingleStep(12)
        funding_scrollbar.setPageStep(90)

        # Listing UI signals
        self.ui.listing_enable_check.toggled.connect(self.on_listing_enable_toggled)
        self.ui.listing_binance_check.toggled.connect(self.on_listing_exchanges_changed)
        self.ui.listing_bybit_check.toggled.connect(self.on_listing_exchanges_changed)
        self.ui.listing_okx_check.toggled.connect(self.on_listing_exchanges_changed)
        self.ui.listing_gate_check.toggled.connect(self.on_listing_exchanges_changed)
        self.ui.listing_bitget_check.toggled.connect(self.on_listing_exchanges_changed)
        self.ui.listing_binance_spot_check.toggled.connect(
            self.on_listing_exchanges_changed
        )
        self.ui.listing_binance_futures_check.toggled.connect(
            self.on_listing_exchanges_changed
        )
        self.ui.listing_bybit_spot_check.toggled.connect(
            self.on_listing_exchanges_changed
        )
        self.ui.listing_bybit_futures_check.toggled.connect(
            self.on_listing_exchanges_changed
        )
        self.ui.listing_okx_spot_check.toggled.connect(
            self.on_listing_exchanges_changed
        )
        self.ui.listing_okx_futures_check.toggled.connect(
            self.on_listing_exchanges_changed
        )
        self.ui.listing_gate_spot_check.toggled.connect(
            self.on_listing_exchanges_changed
        )
        self.ui.listing_gate_futures_check.toggled.connect(
            self.on_listing_exchanges_changed
        )
        self.ui.listing_bitget_spot_check.toggled.connect(
            self.on_listing_exchanges_changed
        )
        self.ui.listing_bitget_futures_check.toggled.connect(
            self.on_listing_exchanges_changed
        )
        self.ui.listing_minutes_edit.textChanged.connect(self.save_settings)
        self.ui.listing_minutes_edit.textChanged.connect(
            self._render_listing_exchange_status
        )
        self.ui.listing_volume_slider.valueChanged.connect(self.save_settings)
        self.ui.listing_refresh_btn.clicked.connect(self.refresh_listing_data)
        self.ui.listing_clear_btn.clicked.connect(self.clear_listing_log)
        # Подключаем кнопки режима просмотра листингов
        if hasattr(self.ui, "listing_log_upcoming_btn"):
            self.ui.listing_log_upcoming_btn.clicked.connect(
                lambda: self.set_listing_log_view_mode("upcoming")
            )
        if hasattr(self.ui, "listing_log_month_btn"):
            self.ui.listing_log_month_btn.clicked.connect(
                lambda: self.set_listing_log_view_mode("month")
            )
        self.ui.listing_log_list.itemClicked.connect(self.copy_listing_symbol)
        self.ui.listing_log_list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.ui.listing_log_list.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.ui.listing_log_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.NoContextMenu
        )

        # Session UI signals
        self.ui.session_enable_check.toggled.connect(self.on_session_enable_toggled)
        self.ui.session_volume_slider.valueChanged.connect(self.save_settings)

        if hasattr(self.ui, "tabs"):
            self.ui.tabs.currentChanged.connect(self._on_main_tab_changed)

        # Подключаем автосохранение для галочек таймфреймов
        self.reconnect_checkbox_signals()

        # Разрешаем сохранение
        self.loading_settings = False
        self._render_funding_exchange_status()
        self._render_session_status()
        self._apply_window_width_for_active_tab()

        # Запускаем таймеры часов и логики алертов
        self.logic.start()  # Основная логика (250мс, precise) для стабильных тиков
        self.logic.overlay_update_timer.start()  # Обновление часов каждые 100мс

        # Запускаем funding monitor только если фандинг включен
        if self.ui.funding_enable_check.isChecked():
            self.funding_monitor.start()

        # Таймер для обновления логов фандинга каждую секунду
        self.funding_log_timer = QTimer()
        self.funding_log_timer.timeout.connect(self._update_funding_log_realtime)
        self.funding_log_timer.start(1000)  # Каждую секунду

        # Запускаем listing monitor только если включен
        if self.ui.listing_enable_check.isChecked():
            self.listing_monitor.start()

        # Запускаем session monitor только если включен
        if self.ui.session_enable_check.isChecked():
            self.session_monitor.start()

        # Таймер для обновления логов листингов каждую секунду
        self.listing_log_timer = QTimer()
        self.listing_log_timer.timeout.connect(self._update_listing_log_realtime)
        self.listing_log_timer.start(1000)

        QTimer.singleShot(1200, self._warmup_donate_dialog)

        # Устанавливаем eventFilter для снятия выделения
        self.ui.funding_log_list.installEventFilter(self)
        self.ui.funding_minutes_edit.installEventFilter(self)
        self.ui.funding_threshold_pos_edit.installEventFilter(self)
        self.ui.funding_threshold_neg_edit.installEventFilter(self)
        self.ui.listing_log_list.installEventFilter(self)
        self.ui.listing_minutes_edit.installEventFilter(self)
        QApplication.instance().installEventFilter(self)

    def _tf_registry_key(self, tf):
        # Windows registry value names are case-insensitive, so 1m and 1M collide.
        return "tf_1mo" if tf == "1M" else f"tf_{tf}"

    def eventFilter(self, obj, event):
        """Перехватываем события для снятия выделения"""
        if event.type() == QEvent.Type.MouseButtonPress:
            funding_list = getattr(self.ui, "funding_log_list", None)
            listing_list = getattr(self.ui, "listing_log_list", None)

            clicked_funding = self._is_widget_in_list(obj, funding_list)
            clicked_listing = self._is_widget_in_list(obj, listing_list)

            if funding_list and not clicked_funding:
                funding_list.clearSelection()
            if listing_list and not clicked_listing:
                listing_list.clearSelection()

        # ESC и Enter снимают выделение
        if event.type() == QEvent.Type.KeyPress:
            if (
                event.key() == Qt.Key.Key_Escape
                or event.key() == Qt.Key.Key_Return
                or event.key() == Qt.Key.Key_Enter
            ):
                if obj == self.ui.funding_log_list:
                    self.ui.funding_log_list.clearSelection()
                    return True
                elif obj == self.ui.listing_log_list:
                    self.ui.listing_log_list.clearSelection()
                    return True
                elif obj in [
                    self.ui.funding_minutes_edit,
                    self.ui.funding_threshold_pos_edit,
                    self.ui.funding_threshold_neg_edit,
                    self.ui.listing_minutes_edit,
                ]:
                    obj.clearFocus()
                    obj.deselect()
                    return True

        # Клик вне элемента снимает выделение
        if event.type() == QEvent.Type.FocusOut:
            if obj in [
                self.ui.funding_minutes_edit,
                self.ui.funding_threshold_pos_edit,
                self.ui.funding_threshold_neg_edit,
                self.ui.listing_minutes_edit,
            ]:
                obj.deselect()

        return super().eventFilter(obj, event)

    def _is_widget_in_list(self, obj, list_widget):
        if obj is None or list_widget is None:
            return False
        current = obj
        while current is not None:
            if current is list_widget or current is list_widget.viewport():
                return True
            parent_ref = getattr(current, "parent", None)
            if callable(parent_ref):
                current = parent_ref()
                continue
            parent_widget_ref = getattr(current, "parentWidget", None)
            if callable(parent_widget_ref):
                current = parent_widget_ref()
                continue
            break
        return False

    def reconnect_checkbox_signals(self):
        """Переподключает все чекбоксы таймфреймов к save_settings"""
        log_write("[RECONNECT] Переподключение сигналов чекбоксов...")
        for tf, cb in self.ui.checkboxes.items():
            # Подключаем только один раз на экземпляр чекбокса
            if not getattr(cb, "_save_signal_connected", False):
                cb.stateChanged.connect(self.save_settings)
                cb._save_signal_connected = True
            log_write(f"[RECONNECT]   tf_{tf}: сигнал переподключен")

    def toggle_overlay(self, state):
        """Метод управления видимостью оверлея"""
        if state:
            self.logic.overlay.show()
        else:
            self.logic.overlay.hide()

    def update_overlay_mode(self, mode_index):
        """Обновляет режим отображения overlay"""
        if self.loading_settings:
            return
        # 0 = "Всегда показывать" / "Always Show" → "always"
        # 1 = "Только на определённых окнах" / "Only on Specific Windows" → "custom"
        overlay_mode = "always" if mode_index == 0 else "custom"
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("overlay_show_mode", overlay_mode)
        config.OVERLAY_SHOW_MODE = overlay_mode
        self.save_settings()

    def select_overlay_app(self):
        """Простой диалог для выбора приложений для Overlay"""
        from PyQt6.QtWidgets import (
            QDialog,
            QVBoxLayout,
            QHBoxLayout,
            QListWidget,
            QPushButton,
            QLabel,
            QLineEdit,
            QListWidgetItem,
            QCompleter,
            QWidget,
            QCheckBox,
        )
        from PyQt6.QtCore import Qt, QSize, QSettings
        from PyQt6.QtGui import QColor

        # Переводы
        translations = {
            "RU": {
                "title": "Добавить приложение для Overlay",
                "info": "Выберите приложения, на которых должен отображаться overlay:",
                "placeholder": "Название приложения точно как в панели задач",
                "add_btn": "+ Добавить",
                "select_all": "✓ Всё",
                "clear_all": "✗ Ничего",
                "cancel": "✗ Отмена",
                "save": "✓ Сохранить",
            },
            "EN": {
                "title": "Add Application for Overlay",
                "info": "Select applications where the overlay should be displayed:",
                "placeholder": "Application name exactly as in taskbar",
                "add_btn": "+ Add",
                "select_all": "✓ All",
                "clear_all": "✗ None",
                "cancel": "✗ Cancel",
                "save": "✓ Save",
            },
        }

        # Получаем текущий язык
        settings = QSettings("MyTradeTools", "TF-Alerter")
        current_lang = settings.value("language", "RU")
        t = translations[current_lang]

        # Получаем список открытых окон
        all_open_apps = list(self.get_open_windows())

        # Загружаем историю всех добавленных приложений
        settings = QSettings("MyTradeTools", "TF-Alerter")
        overlay_all = settings.value("overlay_windows_all", [])
        if not isinstance(overlay_all, list):
            overlay_all = []

        # Добавляем уже добавленные приложения если их нет в списке
        for app in config.OVERLAY_WINDOWS:
            if app not in all_open_apps:
                all_open_apps.insert(0, app)

        # Добавляем исторические приложения
        for app in overlay_all:
            if app not in all_open_apps:
                all_open_apps.append(app)

        dialog = QDialog(self)
        dialog.setWindowTitle(t["title"])
        dialog.resize(550, 400)

        # Строго центрируем диалог относительно главного окна
        parent_frame = self.frameGeometry()
        dialog_frame = dialog.frameGeometry()
        dialog_frame.moveCenter(parent_frame.center())
        dialog.move(dialog_frame.topLeft())
        self._apply_dark_title_bar(dialog)

        # Use a fixed dialog accent (blue) for this dialog's controls regardless of global clock color
        dialog_accent = "#1e90ff"
        # Стилизация диалога и явное переопределение highlight/selection цветов на dialog_accent
        dialog.setStyleSheet(
            f"QDialog {{ background-color: {config.COLORS['background']}; }} "
            f"QLabel {{ color: #aaa; }} "
            f"QLineEdit {{ background: #1a1a1a; color: #bbb; border: 1px solid #333; border-radius: 6px; padding: 5px; }}"
            f" QPushButton.add {{ color: {dialog_accent}; border: 1px solid {dialog_accent}; }}"
        )

        # Устанавливаем палитру highlight (выделение) в цвет accent, чтобы системные стилей не показывали зелёный
        from PyQt6.QtGui import QPalette

        pal = dialog.palette()
        pal.setColor(QPalette.ColorRole.Highlight, QColor(dialog_accent))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
        dialog.setPalette(pal)

        layout = QVBoxLayout()

        # Инструкция
        info_label = QLabel(t["info"])
        info_label.setStyleSheet("color: #aaa; margin-bottom: 10px;")
        layout.addWidget(info_label)

        # Поле для ввода приложения вручную
        search_layout = QHBoxLayout()
        search_input = QLineEdit()
        search_input.setPlaceholderText(t["placeholder"])

        # Добавляем автодополнение
        completer = QCompleter(sorted(set(all_open_apps)))
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        search_input.setCompleter(completer)

        search_layout.addWidget(search_input)

        # Кнопка добавить вручную
        add_custom_btn = QPushButton(t["add_btn"])
        add_custom_btn.setStyleSheet(
            f"QPushButton {{ color: {dialog_accent}; border: 1px solid {dialog_accent}; border-radius: 5px; background: transparent; padding: 5px; }} "
            f"QPushButton:hover {{ background: #333; }}"
        )
        add_custom_btn.setMaximumWidth(100)
        search_layout.addWidget(add_custom_btn)
        layout.addLayout(search_layout)

        # Список приложений с чекбоксами
        app_list = QListWidget()
        # Removed explicit border to avoid broken/discontinuous outline; rely on dialog/frame border
        app_list.setStyleSheet(
            f"QListWidget {{ background: #1a1a1a; color: #bbb; border: none; border-radius: 6px; }} "
            f"QListWidget::item {{ padding: 6px 5px; margin: 1px 0px; border-radius: 4px; }} "
            f"QListWidget::item:selected {{ background: transparent; color: #bbb; }} "
            f"QListWidget::item:focus {{ outline: none; border: none; }}"
        )
        app_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Устанавливаем максимальную высоту с возможностью прокрутки
        app_list.setMaximumHeight(240)
        app_list.setMinimumHeight(90)

        # Заполняем список с кастомными виджетами
        def create_app_item_widget(app_name, is_checked):
            """Создает кастомный виджет для элемента списка"""
            from PyQt6.QtGui import QPainter, QFont, QPen, QColor
            from PyQt6.QtCore import QRect

            container = QWidget()
            container_layout = QHBoxLayout()
            container_layout.setContentsMargins(5, 4, 4, 8)
            container_layout.setSpacing(8)

            # Создаём кастомный чекбокс с рисованием
            class CustomCheckBox(QCheckBox):
                # Кэш шрифтов для оптимизации памяти
                _font_cache = {}

                @classmethod
                def get_font(cls, family, size, weight=None):
                    """Возвращает закэшированный шрифт"""
                    key = (family, size, weight)
                    if key not in cls._font_cache:
                        font = QFont(family, size)
                        if weight:
                            font.setWeight(weight)
                        cls._font_cache[key] = font
                    return cls._font_cache[key]

                def paintEvent(self, event):
                    painter = QPainter(self)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

                    # Очищаем фон
                    painter.fillRect(self.rect(), QColor("#1e1e1e"))

                    # Рисуем квадрат для чекбокса (опущен чуть ниже, чтобы не обрезаться снизу)
                    checkbox_rect = QRect(2, 10, 16, 16)

                    if self.isChecked():
                        # Синий фон с полной заливкой
                        painter.fillRect(checkbox_rect, QColor("#1e90ff"))
                        painter.setPen(QPen(QColor("#1e90ff"), 1))
                        painter.drawRect(checkbox_rect)

                        # Чёрная галочка (используем закэшированный шрифт)
                        painter.setPen(QPen(QColor("#000000"), 2))
                        painter.setFont(self.get_font("Arial", 9, QFont.Weight.Bold))
                        painter.drawText(
                            checkbox_rect, Qt.AlignmentFlag.AlignCenter, "✓"
                        )
                    else:
                        # Синяя граница с прозрачным фоном
                        painter.fillRect(checkbox_rect, QColor("#1a1a1a"))
                        painter.setPen(QPen(QColor("#1e90ff"), 2))
                        painter.drawRect(checkbox_rect)

                    # Текст (используем закэшированный шрифт)
                    painter.setPen(QColor("#ffffff"))
                    painter.setFont(self.get_font("Arial", 10))
                    text_rect = QRect(25, 8, self.width() - 30, 24)
                    painter.drawText(
                        text_rect,
                        Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
                        self.text(),
                    )
                    painter.end()

            checkbox = CustomCheckBox(app_name)
            checkbox.setMaximumHeight(42)
            checkbox.setMinimumHeight(40)
            checkbox.setChecked(is_checked)
            container_layout.addWidget(checkbox)

            # Кнопка удаления
            delete_btn = QPushButton("✕")
            delete_btn.setMaximumWidth(30)
            delete_btn.setStyleSheet(
                f"QPushButton {{ color: {config.COLORS['danger']}; border: 1px solid {config.COLORS['danger']}; border-radius: 4px; background: transparent; padding: 2px; }} "
                f"QPushButton:hover {{ background: #333; }}"
            )

            def delete_item():
                # 找到这个widget在列表中的位置并删除
                for i in range(app_list.count()):
                    item = app_list.item(i)
                    if app_list.itemWidget(item) == container:
                        app_list.takeItem(i)
                        break

            delete_btn.clicked.connect(delete_item)
            container_layout.addWidget(delete_btn)

            container.setLayout(container_layout)
            return container, checkbox

        def add_app_item(app_name, is_checked):
            item = QListWidgetItem()
            item.setSizeHint(QSize(450, 46))
            app_list.addItem(item)
            widget, checkbox = create_app_item_widget(app_name, is_checked)
            widget.checkbox = checkbox
            item.data_checkbox = checkbox  # Store reference
            app_list.setItemWidget(item, widget)

        # Заполняем список
        for app in sorted(set(all_open_apps)):
            is_checked = app in config.OVERLAY_WINDOWS
            add_app_item(app, is_checked)

        layout.addWidget(app_list)

        def add_custom_app():
            text = search_input.text().strip()
            if text and len(text) > 0:
                # Проверяем что такого приложения еще нет
                found = False
                for i in range(app_list.count()):
                    item = app_list.item(i)
                    widget = app_list.itemWidget(item) if item else None
                    if widget and hasattr(widget, "checkbox"):
                        if widget.checkbox.text() == text:
                            # Уже есть, просто отмечаем галочкой
                            widget.checkbox.setChecked(True)
                            search_input.clear()
                            found = True
                            break

                if not found:
                    # Добавляем новый элемент с сохранением сортировки
                    insert_pos = app_list.count()
                    for i in range(app_list.count()):
                        item = app_list.item(i)
                        widget = app_list.itemWidget(item) if item else None
                        if widget and hasattr(widget, "checkbox"):
                            if widget.checkbox.text().lower() > text.lower():
                                insert_pos = i
                                break

                    item = QListWidgetItem()
                    item.setSizeHint(QSize(450, 46))
                    if insert_pos >= app_list.count():
                        app_list.addItem(item)
                    else:
                        app_list.insertItem(insert_pos, item)

                    item_widget, checkbox = create_app_item_widget(text, True)
                    item_widget.checkbox = checkbox
                    app_list.setItemWidget(item, item_widget)
                    search_input.clear()

        add_custom_btn.clicked.connect(add_custom_app)
        # Нажатие Enter в поле поиска тоже добавляет
        search_input.returnPressed.connect(add_custom_app)

        # Кнопки выбора
        btn_layout = QHBoxLayout()

        select_all_btn = QPushButton(t["select_all"])
        select_all_btn.setStyleSheet(
            f"QPushButton {{ color: {dialog_accent}; border: 1px solid {dialog_accent}; border-radius: 5px; background: transparent; padding: 5px; }} "
            f"QPushButton:hover {{ background: #333; }}"
        )
        select_all_btn.setMaximumWidth(60)

        def select_all():
            for i in range(app_list.count()):
                item = app_list.item(i)
                widget = app_list.itemWidget(item) if item else None
                if widget and hasattr(widget, "checkbox"):
                    widget.checkbox.setChecked(True)

        select_all_btn.clicked.connect(select_all)
        btn_layout.addWidget(select_all_btn)

        clear_all_btn = QPushButton(t["clear_all"])
        clear_all_btn.setStyleSheet(
            f"QPushButton {{ color: {config.COLORS['danger']}; border: 1px solid {config.COLORS['danger']}; border-radius: 5px; background: transparent; padding: 5px; }} "
            f"QPushButton:hover {{ background: #333; }}"
        )
        clear_all_btn.setMinimumWidth(100)

        def clear_all():
            for i in range(app_list.count()):
                item = app_list.item(i)
                widget = app_list.itemWidget(item) if item else None
                if widget and hasattr(widget, "checkbox"):
                    widget.checkbox.setChecked(False)

        clear_all_btn.clicked.connect(clear_all)
        btn_layout.addWidget(clear_all_btn)

        btn_layout.addStretch()

        # ОТМЕНА - идет ПЕРВОЙ (переставлена местами)
        cancel_btn = QPushButton(t["cancel"])
        cancel_btn.setStyleSheet(
            "QPushButton { color: #666; border: 1px solid #444; border-radius: 6px; padding: 6px 15px; } "
            "QPushButton:hover { background: #333; }"
        )
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        # СОХРАНИТЬ - идет ВТОРОЙ (переставлена местами)
        ok_btn = QPushButton(t["save"])
        ok_btn.setStyleSheet(
            f"QPushButton {{ color: {dialog_accent}; border: 2px solid {dialog_accent}; border-radius: 6px; font-weight: bold; padding: 6px 15px; }} "
            f"QPushButton:hover {{ background: {dialog_accent}; color: black; }}"
        )
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        def on_save():
            config.OVERLAY_WINDOWS.clear()
            overlay_all = []

            for i in range(app_list.count()):
                item = app_list.item(i)
                widget = app_list.itemWidget(item) if item else None
                if widget and hasattr(widget, "checkbox"):
                    app_name = widget.checkbox.text()
                    overlay_all.append(app_name)  # Сохраняем все
                    if widget.checkbox.isChecked():
                        config.OVERLAY_WINDOWS.append(
                            app_name
                        )  # Добавляем только отмеченные

            # Сохраняем историю всех приложений
            settings = QSettings("MyTradeTools", "TF-Alerter")
            settings.setValue("overlay_windows_all", overlay_all)

            self.update_config_overlay_windows()
            self.save_settings()
            dialog.accept()

        ok_btn.clicked.connect(on_save)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

        dialog.setLayout(layout)
        dialog.exec()

    def _apply_dark_title_bar(self, widget):
        if os.name != "nt" or widget is None:
            return
        try:
            hwnd = int(widget.winId())
            if hwnd <= 0:
                return
            use_dark = ctypes.c_int(1)
            cb_size = ctypes.sizeof(use_dark)
            dwm_set_attr = ctypes.windll.dwmapi.DwmSetWindowAttribute
            for attr in (20, 19):
                result = dwm_set_attr(hwnd, attr, ctypes.byref(use_dark), cb_size)
                if result == 0:
                    break
        except Exception:
            pass

    def get_open_windows(self):
        """Получает список открытых окон Windows"""
        try:
            import ctypes
            from ctypes import wintypes

            open_apps = []

            # Используем более безопасный способ перечисления окон
            EnumWindows = ctypes.windll.user32.EnumWindows
            GetWindowTextLength = ctypes.windll.user32.GetWindowTextLength
            GetWindowTextW = ctypes.windll.user32.GetWindowTextW
            IsWindowVisible = ctypes.windll.user32.IsWindowVisible

            # Определяем callback функцию
            WNDENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
            )

            def enum_callback(hwnd, lparam):
                try:
                    if IsWindowVisible(hwnd):
                        length = GetWindowTextLength(hwnd)
                        if length > 0:
                            buf = ctypes.create_unicode_buffer(length + 1)
                            GetWindowTextW(hwnd, buf, length + 1)
                            text = buf.value.strip()
                            if text and len(text) > 0:
                                # Не добавляем системные окна
                                if not text.startswith("Default IME"):
                                    open_apps.append(text)
                except Exception as e:
                    pass
                return True

            # Вызываем EnumWindows с callback
            callback = WNDENUMPROC(enum_callback)
            result = EnumWindows(callback, 0)

            # Удаляем дубликаты и сортируем
            unique_apps = sorted(list(set(open_apps)))
            return unique_apps

        except Exception as e:
            # Если что-то пошло не так, возвращаем пустой список
            return []

    def update_config_overlay_windows(self):
        """Обновляет конфиг с текущим списком приложений"""
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("overlay_windows", config.OVERLAY_WINDOWS)

    def open_about(self):
        """Открывает окно 'О программе'"""
        from about_dialog import AboutDialog

        dialog = AboutDialog(self)
        dialog.exec()

    def open_donate(self):
        """Открывает окно 'Поддержать проект'"""
        settings = QSettings("MyTradeTools", "TF-Alerter")
        cache_key = (
            settings.value("language", "RU"),
            settings.value("interface_scale_text", "100%"),
        )

        if self._donate_dialog is None or self._donate_dialog_cache_key != cache_key:
            self._donate_dialog = DonateDialog(self)
            self._donate_dialog_cache_key = cache_key

        self._donate_dialog.exec()

    def _warmup_donate_dialog(self):
        try:
            if self._donate_dialog is not None:
                return
            settings = QSettings("MyTradeTools", "TF-Alerter")
            cache_key = (
                settings.value("language", "RU"),
                settings.value("interface_scale_text", "100%"),
            )
            self._donate_dialog = DonateDialog(self)
            self._donate_dialog_cache_key = cache_key
        except Exception:
            self._donate_dialog = None
            self._donate_dialog_cache_key = None

    def open_settings(self):
        """Открывает окно настроек"""
        from settings_dialog import SettingsDialog

        dialog = SettingsDialog(self)
        dialog.exec()

        # Восстанавливаем hotkey после закрытия диалога
        settings = QSettings("MyTradeTools", "TF-Alerter")
        hotkey = settings.value("hotkey", "")
        hotkey_codes = settings.value("hotkey_codes", "")
        invalid_hotkeys = ["", "Нажмите клавишу...", "Не задана"]
        if hotkey and hotkey not in invalid_hotkeys:
            codes = None
            if hotkey_codes:
                try:
                    codes = [
                        int(x)
                        for x in str(hotkey_codes).split(",")
                        if x.strip().isdigit()
                    ]
                except Exception:
                    codes = None
            if codes:
                self.hotkey_manager.register_hotkey_codes(codes, hotkey)

    def toggle_minimize(self):
        """Сворачивает/разворачивает окно по горячей клавише"""
        if getattr(self, "_font_dialog_open", False):
            return
        if self.windowState() & Qt.WindowState.WindowMinimized:
            # Используем Windows API для надежного восстановления
            hwnd = int(self.winId())

            # Константы Windows API
            SW_RESTORE = 9
            SW_SHOW = 5
            SW_SHOWNORMAL = 1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            HWND_TOP = 0

            # Получаем foreground поток
            foreground_hwnd = ctypes.windll.user32.GetForegroundWindow()
            foreground_thread = ctypes.windll.user32.GetWindowThreadProcessId(
                foreground_hwnd, None
            )
            current_thread = ctypes.windll.kernel32.GetCurrentThreadId()

            # Присоединяем потоки для обхода ограничений SetForegroundWindow
            if foreground_thread != current_thread:
                ctypes.windll.user32.AttachThreadInput(
                    foreground_thread, current_thread, True
                )

            try:
                # Восстанавливаем окно (несколько вызовов для надежности)
                ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
                ctypes.windll.user32.ShowWindow(hwnd, SW_SHOWNORMAL)
                ctypes.windll.user32.SetWindowPos(
                    hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE
                )
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                ctypes.windll.user32.BringWindowToTop(hwnd)
                ctypes.windll.user32.SetActiveWindow(hwnd)
                ctypes.windll.user32.SetFocus(hwnd)
            finally:
                # Отсоединяем потоки
                if foreground_thread != current_thread:
                    ctypes.windll.user32.AttachThreadInput(
                        foreground_thread, current_thread, False
                    )

            # Дополнительно активируем через Qt
            self.setWindowState(Qt.WindowState.WindowNoState)
            self.activateWindow()
            self.raise_()
            self.show()
        else:
            self.request_minimize()

    def refresh_funding_data(self):
        """Принудительно обновляет данные фандинга"""
        if hasattr(self, "funding_monitor"):
            if hasattr(self.funding_monitor, "clear_cache"):
                self.funding_monitor.clear_cache()
            self._funding_paused = False
            if hasattr(self, "_funding_clear_resume_timer"):
                self._funding_clear_resume_timer.stop()
            self._pending_tts_entries = []
            self._funding_tts_sound_pending = False
            self._funding_tts_timer.stop()
            self._stop_funding_audio(tts_only=False)
            # Запускаем poll немедленно, не останавливая автообновление
            self.funding_monitor.poll()
            if self._funding_log_view_mode == "triggered":
                self._render_funding_log()

    def refresh_listing_data(self):
        """Принудительно обновляет данные листингов"""
        if hasattr(self, "listing_monitor"):
            if self.ui.listing_enable_check.isChecked() and not bool(
                getattr(self.listing_monitor, "is_monitoring", False)
            ):
                self.listing_monitor.start()
            if hasattr(self.listing_monitor, "clear_cache"):
                self.listing_monitor.clear_cache()
            # poll() сам запускает фоновый поток
            self.listing_monitor.poll()

    def refresh_session_data(self):
        """Принудительно обновляет статус крипто-сессий."""
        if hasattr(self, "session_monitor"):
            if self.ui.session_enable_check.isChecked() and not bool(
                getattr(self.session_monitor, "is_monitoring", False)
            ):
                self.session_monitor.start()
            self.session_monitor.poll()

    def on_session_enable_toggled(self, checked):
        self.ui.session_content_widget.setEnabled(checked)
        if checked:
            self.ui.session_opacity_effect.setOpacity(1.0)
        else:
            self.ui.session_opacity_effect.setOpacity(0.3)

        def _async_toggle():
            if checked:
                if hasattr(self, "session_monitor"):
                    self.session_monitor.start()
                    self.session_monitor.poll()
            else:
                if hasattr(self, "session_monitor"):
                    self.session_monitor.stop()
                self._session_status = {}
                self._render_session_status()
            self.save_settings()

        QTimer.singleShot(0, _async_toggle)

    def on_session_types_changed(self, *args):
        if self.loading_settings:
            return
        if self.ui.session_enable_check.isChecked() and hasattr(self, "session_monitor"):
            self.session_monitor.poll()
        self.save_settings()

    def on_session_status_update(self, payload):
        if not isinstance(payload, dict):
            return
        self._session_status = payload
        self._render_session_status()

    def _render_session_status(self):
        if not hasattr(self.ui, "session_status_label"):
            return

        if not self.ui.session_enable_check.isChecked():
            text = (
                "Session alerts: off"
                if self._is_ui_language_en()
                else "Алерты сессий: выкл"
            )
            self.ui.session_status_label.setText(text)
            if hasattr(self.ui, "set_session_visual_state"):
                countdown_text = (
                    "Until change: --:--"
                    if self._is_ui_language_en()
                    else "До смены: --:--"
                )
                next_text = (
                    "Next: -"
                    if self._is_ui_language_en()
                    else "Следующая: -"
                )
                self.ui.set_session_visual_state(
                    "",
                    "",
                    countdown_text,
                    next_text,
                )
            return

        payload = self._session_status if isinstance(self._session_status, dict) else {}
        current_name = (
            payload.get("current_session_name_en", "")
            if self._is_ui_language_en()
            else payload.get("current_session_name_ru", "")
        )
        next_name = (
            payload.get("next_session_name_en", "")
            if self._is_ui_language_en()
            else payload.get("next_session_name_ru", "")
        )
        next_local = str(payload.get("next_session_local", "--:--") or "--:--")
        next_utc = str(payload.get("next_session_utc", "--:--") or "--:--")
        tz_offset = str(payload.get("tz_offset", "+00:00") or "+00:00")
        seconds_to_next = payload.get("seconds_to_next", None)

        if self._is_ui_language_en():
            text = (
                f"Current: {current_name or '-'} | Next: {next_name or '-'} "
                f"at {next_local} (UTC {next_utc}, local UTC{tz_offset})"
            )
            big_title = current_name or "Unknown"
        else:
            text = (
                f"Сейчас: {current_name or '-'} | Далее: {next_name or '-'} "
                f"в {next_local} (UTC {next_utc}, локально UTC{tz_offset})"
            )
            big_title = current_name or "Неизвестно"
        self.ui.session_status_label.setText(text)

        if hasattr(self.ui, "set_session_visual_state"):
            countdown_text = self._format_session_countdown_text(seconds_to_next)
            next_text = (
                f"Next: {next_name or '-'}"
                if self._is_ui_language_en()
                else f"Следующая: {next_name or '-'}"
            )
            self.ui.set_session_visual_state(
                payload.get("current_session_key", ""),
                big_title,
                countdown_text,
                next_text,
            )

    def _format_session_countdown_text(self, seconds_to_next):
        try:
            seconds = int(seconds_to_next)
        except Exception:
            seconds = -1

        if seconds < 0:
            return "Until change: --:--" if self._is_ui_language_en() else "До смены: --:--"

        if seconds < 60:
            if self._is_ui_language_en():
                return f"Until change: {seconds:02d}s"
            return f"До смены: {seconds:02d}с"

        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if self._is_ui_language_en():
            return f"Until change: {hours:02d}h {minutes:02d}m"
        return f"До смены: {hours:02d}ч {minutes:02d}м"

    def on_session_alert(self, payload):
        if not isinstance(payload, dict):
            return
        if not self.ui.session_enable_check.isChecked():
            return

        alert_kind = str(payload.get("kind", "") or "").strip().lower()
        if alert_kind != "session_warning":
            return

        self._pending_session_warning = dict(payload)
        self._process_pending_session_warning()

    def _process_pending_session_warning(self):
        payload = (
            self._pending_session_warning
            if isinstance(self._pending_session_warning, dict)
            else None
        )
        if payload is None:
            return

        if not self.ui.session_enable_check.isChecked():
            self._pending_session_warning = None
            return

        next_start_ts = int(payload.get("next_session_start_ts", 0) or 0)
        if next_start_ts > 0:
            now_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
            seconds_left = next_start_ts - now_ts
            # Do not play delayed session warning in the 10-second TF alert window.
            if seconds_left <= 10:
                self._pending_session_warning = None
                return

        if self._is_alert_audio_busy():
            self._session_warning_retry_timer.start(700)
            return

        self._pending_session_warning = None
        self._trigger_session_warning_alert(payload)

    def _is_alert_audio_busy(self):
        if self._session_tts_busy:
            return True

        players = [
            getattr(self.logic, "voice_player", None),
            getattr(self.logic, "tick_player", None),
            getattr(self.logic, "transition_player", None),
            getattr(self, "_funding_player", None),
            getattr(self, "_listing_player", None),
            getattr(self, "_listing_edge_player", None),
            getattr(self, "_session_edge_player", None),
        ]
        for player in players:
            if self._player_is_playing(player):
                return True

        if self._edge_tts_busy or self._listing_edge_tts_busy:
            return True
        with self._system_tts_lock:
            if self._system_tts_busy or bool(self._system_tts_queue):
                return True
        if self._listing_tts_busy:
            return True

        return False

    def _player_is_playing(self, player):
        if player is None:
            return False
        try:
            from PyQt6.QtMultimedia import QMediaPlayer

            return player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        except Exception:
            return False

    def _trigger_session_warning_alert(self, payload):
        settings = QSettings("MyTradeTools", "TF-Alerter")
        tts_enabled = settings.value("session_tts_enabled", True, type=bool)

        if tts_enabled:
            tts_engine = settings.value("session_tts_engine", "system")
            tts_voice_id = settings.value("session_tts_voice_id", "")
            tts_language = settings.value("session_tts_language", "ru")
            tts_compensation_sec = self._estimate_session_tts_compensation_seconds(
                tts_engine,
            )
            message = self._format_session_tts_message(
                payload,
                tts_language,
                tts_compensation_sec,
            )
            self._speak_session_tts_async(
                message,
                tts_engine,
                tts_voice_id,
                language=tts_language,
            )

    def _estimate_session_tts_compensation_seconds(self, engine_type):
        # Edge TTS network generation adds noticeable delay.
        compensation = 2
        if str(engine_type or "").lower() == "edge":
            compensation += 2

        return max(1, min(12, compensation))

    def _format_session_tts_message(self, payload, language, compensation_sec=0):
        is_en = str(language or "ru").lower().startswith("en")
        next_name = (
            payload.get("next_session_name_en", "")
            if is_en
            else payload.get("next_session_name_ru", "")
        )
        if not next_name:
            next_name = "unknown" if is_en else "неизвестно"

        if is_en:
            return f"Trading session change. Next session: {next_name}."

        return f"Смена торговой сессии. Следующая сессия: {next_name}."

    def _speak_session_tts_async(
        self, message, engine_type, voice_id, language="ru"
    ):
        if (
            not self.ui.session_enable_check.isChecked()
            or not self._is_session_tts_enabled()
        ):
            return
        if self._session_tts_busy:
            return

        self._session_tts_busy = True
        effective_engine = str(engine_type or "system").lower()
        if effective_engine == "edge" and not self._edge_tts_service_blocked():
            self._speak_session_edge_tts(message, voice_id, language)
            return

        def _speak_thread():
            try:
                self._speak_session_system_tts(message, voice_id, language)
            finally:
                self._session_tts_busy = False

        thread = threading.Thread(target=_speak_thread, daemon=True)
        thread.start()

    def _speak_session_system_tts(self, text, voice_id, language="ru"):
        try:
            import pyttsx3

            engine = pyttsx3.init()
            resolved_voice = self._resolve_system_tts_voice(engine, voice_id, language)
            if resolved_voice:
                engine.setProperty("voice", resolved_voice)
            engine.setProperty("rate", 170)
            settings = QSettings("MyTradeTools", "TF-Alerter")
            session_volume = int(settings.value("session_volume", 80))
            system_tts_volume = self._safe_audio_volume_from_percent(session_volume)
            engine.setProperty("volume", system_tts_volume)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            print(f"⚠️ Ошибка Session System TTS: {e}")

    def _speak_session_edge_tts(self, text, voice_name, language="ru"):
        try:
            import asyncio
            import edge_tts
            import tempfile

            voice_name = self._resolve_edge_tts_voice(voice_name, language)

            async def _generate_audio():
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".mp3"
                ) as tmp_file:
                    tmp_path = tmp_file.name
                communicate = edge_tts.Communicate(
                    text,
                    voice_name,
                    rate="-8%",
                )
                await communicate.save(tmp_path)
                return tmp_path

            tmp_path = asyncio.run(_generate_audio())
            self._play_session_edge_file(tmp_path)
        except Exception as e:
            print(f"⚠️ Ошибка Session Edge TTS: {e}")
            self._fallback_edge_tts_to_system_tts(text, voice_name, language, kind="session")

    def _play_session_edge_file(self, path):
        from PyQt6.QtCore import QUrl
        from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

        if not path or not os.path.exists(path):
            self._session_tts_busy = False
            return

        if not hasattr(self, "_session_edge_player"):
            self._session_edge_player = QMediaPlayer()
            self._session_edge_output = QAudioOutput()
            self._session_edge_player.setAudioOutput(self._session_edge_output)
            self._session_edge_started = False
            self._session_edge_player.playbackStateChanged.connect(
                self._on_session_edge_playback_state
            )

        self._refresh_audio_output_device(getattr(self, "_session_edge_output", None))
        settings = QSettings("MyTradeTools", "TF-Alerter")
        session_volume = int(settings.value("session_volume", 80))
        volume = self._safe_audio_volume_from_percent(session_volume)

        self._session_edge_started = False
        self._session_edge_output.setVolume(0.0)
        self._session_edge_player.stop()
        self._session_edge_player.setSource(QUrl())
        self._session_edge_player.setSource(QUrl.fromLocalFile(path))
        self._session_edge_player.play()
        QTimer.singleShot(20, lambda out=self._session_edge_output, vol=volume: out.setVolume(vol))

    def _on_session_edge_playback_state(self, state):
        from PyQt6.QtMultimedia import QMediaPlayer

        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._session_edge_started = True
            return

        if (
            state == QMediaPlayer.PlaybackState.StoppedState
            and self._session_tts_busy
            and getattr(self, "_session_edge_started", False)
        ):
            self._session_tts_busy = False
            self._session_edge_started = False

    def _is_session_tts_enabled(self):
        settings = QSettings("MyTradeTools", "TF-Alerter")
        return settings.value("session_tts_enabled", True, type=bool)

    def _resume_funding_after_clear(self):
        self._funding_paused = False
        if hasattr(self, "funding_monitor"):
            self.funding_monitor.poll()

    def on_listing_enable_toggled(self, checked):
        """Обработка вкл/выкл листингов: затемняет/осветляет интерфейс"""
        self.ui.listing_content_widget.setEnabled(checked)
        if checked:
            self.ui.listing_opacity_effect.setOpacity(1.0)
        else:
            self.ui.listing_opacity_effect.setOpacity(0.3)

        self._render_listing_exchange_status()

        def _async_toggle():
            if checked:
                if hasattr(self, "listing_monitor"):
                    self.listing_monitor.start()
            else:
                if hasattr(self, "listing_monitor"):
                    self.listing_monitor.stop()
            self.save_settings()

        QTimer.singleShot(0, _async_toggle)

    def on_listing_exchanges_changed(self, *args):
        if self.loading_settings:
            return

        self.listing_alert_entries = []
        self._listing_seen_keys = set()
        self._listing_alerted_keys = set()
        self.ui.listing_log_list.clear()

        if self.ui.listing_enable_check.isChecked() and hasattr(
            self, "listing_monitor"
        ):
            if not bool(getattr(self.listing_monitor, "is_monitoring", False)):
                self.listing_monitor.start()
            if hasattr(self.listing_monitor, "clear_cache"):
                self.listing_monitor.clear_cache()
            self.listing_monitor.poll()

        self._render_listing_exchange_status()
        self.save_settings()

    def _on_main_tab_changed(self, _index):
        self._apply_window_width_for_active_tab()

    def _apply_window_width_for_active_tab(self):
        if not hasattr(self.ui, "tabs"):
            return
        if not self._compact_window_size:
            return

        target_width, target_height = self._compact_window_size

        if self.width() == target_width and self.height() == target_height:
            return
        self.setFixedSize(target_width, target_height)

    def append_listing_log_text(self, payload):
        if not isinstance(payload, dict):
            return
        if not self.ui.listing_enable_check.isChecked():
            return

        exchange_key = str(payload.get("exchange", "") or "").strip().lower()
        if not self._is_listing_exchange_enabled(exchange_key):
            return

        raw_symbol = self._normalize_symbol_text(payload.get("symbol", ""))
        if not self._is_valid_listing_symbol(raw_symbol):
            raw_symbol = self._extract_symbol_from_title(payload.get("title", ""))

        if not self._is_valid_listing_symbol(raw_symbol):
            return

        listing_time = int(payload.get("listing_time", 0) or 0)
        now_ms = int(time.time() * 1000)
        release_date = int(payload.get("release_date", 0) or 0)
        if release_date > 0 and release_date < 10**11:
            release_date *= 1000

        # Fallback for sudden listings: if explicit listing time is missing,
        # use a very recent release timestamp as the effective trigger time.
        if listing_time <= 0 and release_date > 0 and release_date >= now_ms - 30 * 60 * 1000:
            listing_time = release_date

        # Safety guard: ignore stale listing events that are too old.
        if listing_time > 0 and listing_time < now_ms - 30 * 60 * 1000:
            return
        # \u041b\u043e\u0433\u0438\u0440\u0443\u0435\u043c \u0442\u043e\u043b\u044c\u043a\u043e \u043d\u0430\u0439\u0434\u0435\u043d\u043d\u044b\u0435 \u043b\u0438\u0441\u0442\u0438\u043d\u0433\u0438 \u0441 \u0432\u0440\u0435\u043c\u0435\u043d\u0435\u043c

        article_code = str(payload.get("article_code", "") or "").strip()
        if not article_code:
            article_code = f"{payload.get('exchange','')}:{payload.get('title','')}:{payload.get('published_at',0)}"

        entry = {
            "exchange": exchange_key,
            "symbol": raw_symbol,
            "listing_time": listing_time,
            "release_date": release_date,
            "title": payload.get("title", ""),
            "article_code": article_code,
            "listing_type": self._resolve_listing_type(payload),
        }

        if not self._is_listing_type_enabled(entry):
            return

        # Dedup by (exchange, symbol, time rounded to minute, listing_type)
        # This prevents the same coin showing up from multiple sources
        time_minute = (listing_time // 60000) * 60000 if listing_time > 0 else 0
        key = (
            str(entry["exchange"]).strip().lower(),
            entry["symbol"],
            time_minute,
            entry.get("listing_type", ""),
        )
        if key in self._listing_seen_keys:
            return
        self._listing_seen_keys.add(key)
        self.listing_alert_entries.append(entry)

        self._render_listing_lists()
        self._render_listing_exchange_status()

    def on_listing_status_update(self, payload):
        if not isinstance(payload, dict):
            return
        status_map = payload.get("exchanges")
        if isinstance(status_map, dict):
            self._listing_exchange_status = status_map
            self._render_listing_exchange_status()
            self._warn_source_errors("listing", status_map)

    def _get_listing_passed_counts(self):
        counts = {}
        threshold_minutes = self._listing_minutes_threshold()
        now_local = datetime.datetime.now()

        for entry in list(self.listing_alert_entries):
            exchange_key = str(entry.get("exchange", "") or "").strip().lower()
            if not self._is_listing_exchange_enabled(exchange_key):
                continue
            if not self._is_listing_type_enabled(entry):
                continue
            listing_time_ms = int(entry.get("listing_time", 0) or 0)
            if listing_time_ms <= 0:
                continue
            listing_dt = datetime.datetime.fromtimestamp(listing_time_ms / 1000.0)
            diff_minutes = (listing_dt - now_local).total_seconds() / 60.0
            if diff_minutes < 0 or diff_minutes > threshold_minutes:
                continue
            key = str(entry.get("exchange", "")).strip().lower()
            counts[key] = counts.get(key, 0) + 1

        return counts

    def _render_listing_exchange_status(self):
        if not hasattr(self.ui, "listing_status_label"):
            return

        status_ok_color = "#1e90ff"

        status_map = (
            self._listing_exchange_status
            if isinstance(self._listing_exchange_status, dict)
            else {}
        )

        exchanges = [
            ("binance", "Binance", self.ui.listing_binance_check.isChecked()),
            ("bybit", "Bybit", self.ui.listing_bybit_check.isChecked()),
            ("okx", "OKX", self.ui.listing_okx_check.isChecked()),
            ("gate", "Gate", self.ui.listing_gate_check.isChecked()),
            ("bitget", "Bitget", self.ui.listing_bitget_check.isChecked()),
        ]

        if not self.ui.listing_enable_check.isChecked():
            chunks = [
                f"<span style='color:#666;'>● {name}: off</span>"
                for _, name, _ in exchanges
            ]
            self.ui.listing_status_label.setText("&nbsp;&nbsp;".join(chunks))
            return

        chunks = []
        passed_counts = self._get_listing_passed_counts()
        for key, name, is_enabled in exchanges:
            state = status_map.get(key, {}) if isinstance(status_map, dict) else {}
            fetched = int(state.get("fetched", 0) or 0)
            passed = int(passed_counts.get(key, 0) or 0)
            error = str(state.get("error", "") or "").strip()

            if not is_enabled:
                chunks.append(f"<span style='color:#666;'>● {name}: off</span>")
                continue

            if error:
                if error == "unsupported":
                    chunks.append(f"<span style='color:#888;'>● {name}: n/a</span>")
                else:
                    chunks.append(
                        f"<span style='color:{config.COLORS['danger']};'>● {name}: err</span>"
                    )
                continue

            chunks.append(
                f"<span style='color:{status_ok_color};'>● {name}: {fetched}/{passed}</span>"
            )

        self.ui.listing_status_label.setText("&nbsp;&nbsp;".join(chunks))

    def clear_listing_log(self):
        current_mode = str(
            getattr(self, "_listing_log_view_mode", "upcoming") or "upcoming"
        )

        if current_mode == "month":
            self.listing_alert_history = []
            self._listing_alert_history_keys = set()
            self._save_listing_alert_history()
        else:
            self.listing_alert_entries = []
            self._listing_seen_keys = set()
            self._listing_alerted_keys = set()
            self._listing_tts_queue.clear()
            if hasattr(self, "_listing_sound_delay_timer"):
                self._listing_sound_delay_timer.stop()
            self._listing_sound_pending = False
            self._listing_sound_pending_file = ""

            if hasattr(self, "_listing_player"):
                try:
                    self._listing_player.stop()
                except Exception:
                    pass

            if hasattr(self, "_listing_edge_player"):
                try:
                    self._listing_edge_player.stop()
                except Exception:
                    pass

        self.ui.listing_log_list.clear()
        self._render_listing_lists()

        self._render_listing_exchange_status()

    def _update_listing_log_realtime(self):
        if self._listing_log_view_mode == "upcoming":
            self._render_listing_lists()
        self._render_listing_exchange_status()
        self._trigger_listing_alerts()

    def _render_listing_lists(self):
        if not hasattr(self.ui, "listing_log_list"):
            return

        if self._listing_log_view_mode == "month":
            self._render_listing_month_alerts()
            return

        # Показываем предстоящие листинги
        now_local = datetime.datetime.now()
        entries = []
        threshold_minutes = self._listing_minutes_threshold()

        for entry in list(self.listing_alert_entries):
            exchange_key = str(entry.get("exchange", "") or "").strip().lower()
            if not self._is_listing_exchange_enabled(exchange_key):
                continue
            if not self._is_listing_type_enabled(entry):
                continue
            listing_time_ms = int(entry.get("listing_time", 0) or 0)
            if listing_time_ms <= 0:
                continue
            listing_dt = datetime.datetime.fromtimestamp(listing_time_ms / 1000.0)
            diff_minutes = (listing_dt - now_local).total_seconds() / 60.0
            if diff_minutes < 0:
                continue
            if diff_minutes > threshold_minutes:
                continue
            entries.append(entry)

        def _entry_sort_key(item):
            return int(item.get("listing_time", 0) or 0)

        entries.sort(key=_entry_sort_key)

        self.ui.listing_log_list.clear()
        for entry in entries:
            self._add_listing_log_item(self.ui.listing_log_list, entry, now_local)

        if not entries:
            empty_text = (
                "No listings for the selected window"
                if self._is_ui_language_en()
                else "Нет листингов за выбранный интервал"
            )
            item = QListWidgetItem(empty_text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor("#666"))
            self.ui.listing_log_list.addItem(item)

    def set_listing_log_view_mode(self, mode):
        if mode not in ("upcoming", "month"):
            mode = "upcoming"
        self._listing_log_view_mode = mode

        if hasattr(self.ui, "listing_log_upcoming_btn"):
            self.ui.listing_log_upcoming_btn.blockSignals(True)
            self.ui.listing_log_upcoming_btn.setChecked(mode == "upcoming")
            self.ui.listing_log_upcoming_btn.blockSignals(False)
        if hasattr(self.ui, "listing_log_month_btn"):
            self.ui.listing_log_month_btn.blockSignals(True)
            self.ui.listing_log_month_btn.setChecked(mode == "month")
            self.ui.listing_log_month_btn.blockSignals(False)

        self._render_listing_lists()

    def _record_listing_alert(self, entry):
        if not isinstance(entry, dict):
            return

        exchange_key = str(entry.get("exchange", "")).strip().lower()
        enabled_map = {
            "binance": self.ui.listing_binance_check.isChecked(),
            "bybit": self.ui.listing_bybit_check.isChecked(),
            "okx": self.ui.listing_okx_check.isChecked(),
            "gate": self.ui.listing_gate_check.isChecked(),
            "bitget": self.ui.listing_bitget_check.isChecked(),
        }
        if enabled_map.get(exchange_key) is False:
            return

        if not self._is_listing_type_enabled(entry):
            return

        now_ms = int(time.time() * 1000)
        keep_after = now_ms - 24 * 60 * 60 * 1000
        listing_time_ms = int(entry.get("listing_time", 0) or 0)
        if listing_time_ms <= 0:
            return
        if listing_time_ms < keep_after or listing_time_ms > now_ms:
            return

        # Round to minute for deduplication
        time_minute = (listing_time_ms // 60000) * 60000
        key = (
            exchange_key,
            self._normalize_symbol_text(entry.get("symbol", "")),
            time_minute,
            str(entry.get("listing_type", "") or "").strip().lower(),
        )
        if key in self._listing_alert_history_keys:
            return
        self._listing_alert_history_keys.add(key)
        snapshot = dict(entry)
        snapshot["detected_at"] = int(time.time() * 1000)
        self.listing_alert_history.append(snapshot)
        self._save_listing_alert_history()

    def _save_listing_alert_history(self):
        try:
            now_ms = int(time.time() * 1000)
            keep_after = now_ms - 24 * 60 * 60 * 1000
            trimmed = []
            for entry in list(self.listing_alert_history):
                listing_time_ms = int(entry.get("listing_time", 0) or 0)
                detected_at = int(
                    entry.get("detected_at", 0) or entry.get("alerted_at", 0) or 0
                )
                ref_ts = listing_time_ms if listing_time_ms > 0 else detected_at
                if ref_ts < keep_after or ref_ts > now_ms:
                    continue
                trimmed.append(entry)
            self.listing_alert_history = trimmed

            settings = QSettings("MyTradeTools", "TF-Alerter")
            settings.setValue(
                "listing_alert_history_json",
                json.dumps(self.listing_alert_history, ensure_ascii=True),
            )
        except Exception:
            pass

    def _load_listing_alert_history(self, settings):
        try:
            raw = settings.value("listing_alert_history_json", "")
            if not raw:
                return
            data = json.loads(raw)
            if not isinstance(data, list):
                return
            # Deduplicate existing history on load
            unique_entries = {}
            for item in data:
                if not isinstance(item, dict):
                    continue
                listing_time_ms = int(item.get("listing_time", 0) or 0)
                time_minute = (listing_time_ms // 60000) * 60000  # Round to minute
                key = (
                    str(item.get("exchange", "")).strip().lower(),
                    self._normalize_symbol_text(item.get("symbol", "")),
                    time_minute,
                    str(item.get("listing_type", "") or "").strip().lower(),
                )
                if key not in unique_entries:
                    unique_entries[key] = item
            self.listing_alert_history = list(unique_entries.values())
            self._listing_alert_history_keys = set(unique_entries.keys())
        except Exception:
            self.listing_alert_history = []
            self._listing_alert_history_keys = set()

    def _send_test_listing(self):
        """Отправить тестовый листинг для проверки работоспособности системы."""
        try:
            import datetime

            # Генерируем тестовый листинг через 5 минут от текущего времени
            test_time = datetime.datetime.now() + datetime.timedelta(minutes=5)
            test_time_ms = int(test_time.timestamp() * 1000)

            test_payload = {
                "exchange": "binance",
                "symbol": "PEPE",
                "title": "Binance Will List Pepe (PEPE) - PEPEUSDT Perpetual Contract",
                "listing_time": test_time_ms,
                "release_date": int(time.time() * 1000),
                "article_code": "test_listing_startup_check",
                "listing_type": "futures",
            }
            self.append_listing_log_text(test_payload)
        except Exception as e:
            print(f"⚠️ Ошибка отправки тестового листинга: {e}")

    def _render_listing_month_alerts(self):
        """Render history of listing alerts that occurred while the program was running."""
        now_ms = int(time.time() * 1000)
        keep_after = now_ms - 24 * 60 * 60 * 1000
        enabled_map = {
            "binance": self.ui.listing_binance_check.isChecked(),
            "bybit": self.ui.listing_bybit_check.isChecked(),
            "okx": self.ui.listing_okx_check.isChecked(),
            "gate": self.ui.listing_gate_check.isChecked(),
            "bitget": self.ui.listing_bitget_check.isChecked(),
        }

        entries = []
        for entry in list(self.listing_alert_history):
            exchange_key = str(entry.get("exchange", "")).strip().lower()
            if enabled_map.get(exchange_key) is False:
                continue
            if not self._is_listing_type_enabled(entry):
                continue
            listing_time_ms = int(entry.get("listing_time", 0) or 0)
            if listing_time_ms <= 0:
                continue
            if listing_time_ms < keep_after or listing_time_ms > now_ms:
                continue
            entries.append(entry)

        entries.sort(
            key=lambda item: int(item.get("detected_at", 0) or 0), reverse=True
        )

        self.ui.listing_log_list.clear()
        is_en = self._is_ui_language_en()
        for entry in entries:
            exchange = entry.get("exchange", "")
            symbol = entry.get("symbol", "")
            listing_time_ms = int(entry.get("listing_time", 0) or 0)
            listing_type = self._normalize_listing_type(entry.get("listing_type", ""))
            listing_dt = (
                datetime.datetime.fromtimestamp(listing_time_ms / 1000.0)
                if listing_time_ms
                else None
            )

            listing_text = listing_dt.strftime("%d.%m.%Y %H:%M") if listing_dt else "—"
            type_text = self._format_listing_type_label(listing_type)
            if is_en:
                text = (
                    f"{symbol} {type_text} — {exchange} — " f"listing: {listing_text}"
                )
            else:
                text = (
                    f"{symbol} {type_text} — {exchange} — " f"листинг: {listing_text}"
                )

            item = QListWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            font = item.font()
            font.setPointSize(9)
            item.setFont(font)
            item.setForeground(QColor(100, 100, 100))
            self.ui.listing_log_list.addItem(item)

        if not entries:
            empty_text = "No recorded alerts yet" if is_en else "Алертов пока не было"
            item = QListWidgetItem(empty_text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor("#666"))
            self.ui.listing_log_list.addItem(item)

    def _add_listing_log_item(self, list_widget, entry, now_local):
        exchange = entry.get("exchange", "")
        symbol = entry.get("symbol", "")
        listing_time_ms = int(entry.get("listing_time", 0) or 0)
        listing_type = self._normalize_listing_type(entry.get("listing_type", ""))

        if listing_time_ms:
            listing_dt = datetime.datetime.fromtimestamp(listing_time_ms / 1000.0)
            time_diff_ms = int((listing_dt - now_local).total_seconds() * 1000)
            if time_diff_ms >= 60000:
                minutes = max(0, int(time_diff_ms / 60000))
                time_str = f"{minutes} {'min' if self._is_ui_language_en() else 'мин'}"
            elif time_diff_ms > 0:
                seconds = max(0, int(time_diff_ms / 1000))
                time_str = f"{seconds} {'sec' if self._is_ui_language_en() else 'сек'}"
            else:
                time_str = "completed" if self._is_ui_language_en() else "завершен"

            time_label = listing_dt.strftime("%H:%M:%S")
        else:
            time_str = ""
            time_label = "—"

        text = (
            f"{symbol} {self._format_listing_type_label(listing_type)}  {exchange} — "
            f"{'listing at' if self._is_ui_language_en() else 'листинг в'} {time_label} — "
            f"{'in' if self._is_ui_language_en() else 'через'} {time_str}"
        )

        item = QListWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft)
        item.setData(Qt.ItemDataRole.UserRole, entry)

        font = item.font()
        font.setPointSize(9)
        item.setFont(font)

        if listing_time_ms:
            time_diff_ms = int((listing_dt - now_local).total_seconds() * 1000)
            minutes_to = max(0, int(time_diff_ms / 60000))
            if minutes_to <= 5 or (time_diff_ms > 0 and time_diff_ms <= 60000):
                item.setForeground(QColor(config.COLORS["danger"]))
            elif minutes_to <= 15:
                item.setForeground(QColor(config.COLORS["accent"]))
            else:
                item.setForeground(QColor(config.COLORS["text"]))
        else:
            item.setForeground(QColor(config.COLORS["text"]))

        list_widget.addItem(item)

    def copy_listing_symbol(self, item):
        if not item:
            return

        lst = self.ui.listing_log_list
        cursor_pos = lst.mapFromGlobal(QCursor.pos())
        item_rect = lst.visualItemRect(item)

        entry = item.data(Qt.ItemDataRole.UserRole) or {}
        symbol = entry.get("symbol", "")
        if not symbol:
            return

        relative_x = cursor_pos.x() - item_rect.x()
        if relative_x <= 100:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(symbol)
            QToolTip.showText(QCursor.pos(), f"Скопировано: {symbol}")
            QTimer.singleShot(2000, QToolTip.hideText)

    def _listing_minutes_threshold(self):
        raw = str(self.ui.listing_minutes_edit.text() or "").strip()
        raw = raw.replace(",", ".")
        if not raw:
            return 15.0
        try:
            return float(raw)
        except Exception:
            return 15.0

    def _trigger_listing_alerts(self):
        if not self.ui.listing_enable_check.isChecked():
            return

        threshold_minutes = self._listing_minutes_threshold()
        alert_window_minutes = max(1.0, threshold_minutes)
        recent_past_minutes = 20.0
        now_local = datetime.datetime.now()

        for entry in list(self.listing_alert_entries):
            exchange_key = str(entry.get("exchange", "") or "").strip().lower()
            if not self._is_listing_exchange_enabled(exchange_key):
                continue
            if not self._is_listing_type_enabled(entry):
                continue
            listing_time_ms = int(entry.get("listing_time", 0) or 0)
            if listing_time_ms <= 0:
                continue
            listing_dt = datetime.datetime.fromtimestamp(listing_time_ms / 1000.0)
            diff_minutes = (listing_dt - now_local).total_seconds() / 60.0

            symbol_key = self._normalize_symbol_text(entry.get("symbol", ""))
            listing_type_key = (
                str(self._normalize_listing_type(entry.get("listing_type", "")) or "")
                .strip()
                .lower()
            )
            time_minute = (listing_time_ms // 60000) * 60000
            alert_key = (
                exchange_key,
                symbol_key,
                time_minute,
                listing_type_key,
            )

            if diff_minutes < -recent_past_minutes:
                if alert_key in self._listing_alerted_keys:
                    self._record_listing_alert(entry)
                continue
            if diff_minutes > alert_window_minutes:
                continue

            if alert_key not in self._listing_alerted_keys:
                self._listing_alerted_keys.add(alert_key)
                self._trigger_listing_alert(entry, listing_live_now=(diff_minutes <= 0))

            if diff_minutes <= 0:
                self._record_listing_alert(entry)

    def _trigger_listing_alert(self, entry, listing_live_now=False):
        settings = QSettings("MyTradeTools", "TF-Alerter")
        sound_enabled = settings.value("listing_sound_enabled", True, type=bool)
        tts_enabled = settings.value("listing_tts_enabled", True, type=bool)
        sound_started = False

        if sound_enabled:
            try:
                sound_file = settings.value(
                    "listing_sound_file", config.SOUND_LISTING_ALERT
                )
                sound_file = (
                    str(sound_file or "").strip() or config.SOUND_LISTING_ALERT
                )
                if sound_file:
                    sound_started = self._play_listing_sound_throttled(sound_file)
                else:
                    sound_started = self._play_listing_sound_throttled(
                        config.SOUND_LISTING_ALERT
                    )
            except Exception:
                pass

        if tts_enabled:
            tts_engine = settings.value("listing_tts_engine", "system")
            tts_voice_id = settings.value("listing_tts_voice_id", "")
            tts_language = settings.value("listing_tts_language", "ru")
            message = self._format_listing_message(
                entry,
                tts_language,
                listing_live_now=listing_live_now,
            )
            self._speak_listing_tts_async(
                message,
                tts_engine,
                tts_voice_id,
                tts_language,
                wait_for_sound=sound_started,
            )

    def _format_listing_message(self, entry, language, listing_live_now=False):
        symbol = self._symbol_for_tts(entry.get("symbol", ""))
        exchange_key = str(entry.get("exchange", "")).strip().lower()
        exchange_name = self._exchange_name_for_tts(exchange_key, language)
        listing_type = self._normalize_listing_type(entry.get("listing_type", ""))
        if not listing_type:
            listing_type = self._classify_listing_type(entry.get("title", ""))
        market_label = self._listing_market_for_tts(listing_type, language)
        listing_time_ms = int(entry.get("listing_time", 0) or 0)
        listing_dt = (
            datetime.datetime.fromtimestamp(listing_time_ms / 1000.0)
            if listing_time_ms
            else None
        )
        if not listing_dt:
            if language == "ru":
                return f"{exchange_name}, {market_label}, {symbol}"
            return f"{exchange_name}, {market_label}, {symbol}"

        time_str = listing_dt.strftime("%H:%M")

        # Вычисляем сколько времени осталось
        now = datetime.datetime.now()
        time_diff = listing_dt - now
        total_seconds = int(time_diff.total_seconds())

        if total_seconds <= 0:
            if language == "ru":
                if listing_live_now:
                    return f"{exchange_name}, {market_label}, {symbol}, листинг уже открыт"
                return (
                    f"{exchange_name}, {market_label}, {symbol}, листинг в {time_str}"
                )
            if listing_live_now:
                return f"{exchange_name}, {market_label}, {symbol}, listing is now live"
            return f"{exchange_name}, {market_label}, {symbol}, listing at {time_str}"

        # Разбиваем на дни, часы, минуты
        days = total_seconds // 86400
        remaining = total_seconds % 86400
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        time_parts = []
        if language == "ru":
            if days > 0:
                day_word = self._get_day_word_ru(days)
                time_parts.append(f"{days} {day_word}")
            if hours > 0:
                hour_word = self._get_hour_word_ru(hours)
                time_parts.append(f"{hours} {hour_word}")
            if minutes > 0 or (days == 0 and hours == 0):
                minute_word = self._get_minute_word_ru(minutes)
                time_parts.append(f"{minutes} {minute_word}")

            time_remaining = " ".join(time_parts)
            return (
                f"{exchange_name}, {market_label}, {symbol}, листинг в {time_str}, "
                f"осталось {time_remaining}"
            )
        else:
            if days > 0:
                day_word = "day" if days == 1 else "days"
                time_parts.append(f"{days} {day_word}")
            if hours > 0:
                hour_word = "hour" if hours == 1 else "hours"
                time_parts.append(f"{hours} {hour_word}")
            if minutes > 0 or (days == 0 and hours == 0):
                minute_word = "minute" if minutes == 1 else "minutes"
                time_parts.append(f"{minutes} {minute_word}")

            time_remaining = " ".join(time_parts)
            return (
                f"{exchange_name}, {market_label}, {symbol}, listing at {time_str}, "
                f"{time_remaining} remaining"
            )

    def _listing_market_for_tts(self, listing_type, language="ru"):
        normalized = self._normalize_listing_type(listing_type)
        if language == "ru":
            if normalized == "spot":
                return "спот"
            if normalized == "futures":
                return "фьючерс"
            return "спот"
        if normalized == "spot":
            return "spot"
        if normalized == "futures":
            return "futures"
        return "spot"

    def _play_listing_sound_throttled(self, filename):
        now_ms = int(time.time() * 1000)
        cooldown_ms = int(getattr(self, "_listing_sound_cooldown_ms", 60000) or 60000)
        last_ms = int(getattr(self, "_last_listing_sound_played_ms", 0) or 0)

        if last_ms <= 0 or now_ms - last_ms >= cooldown_ms:
            if hasattr(self, "_listing_sound_delay_timer"):
                self._listing_sound_delay_timer.stop()
            self._listing_sound_pending = False
            self._listing_sound_pending_file = ""
            self._play_listing_sound(filename)
            self._last_listing_sound_played_ms = now_ms
            return True

        # Cooldown active: skip this beep (avoid misleading delayed beeps)
        self._listing_sound_pending = False
        self._listing_sound_pending_file = ""
        return False

    def _play_delayed_listing_sound(self):
        return

    def _get_day_word_ru(self, days):
        if days % 10 == 1 and days % 100 != 11:
            return "день"
        elif days % 10 in [2, 3, 4] and days % 100 not in [12, 13, 14]:
            return "дня"
        else:
            return "дней"

    def _get_hour_word_ru(self, hours):
        if hours % 10 == 1 and hours % 100 != 11:
            return "час"
        elif hours % 10 in [2, 3, 4] and hours % 100 not in [12, 13, 14]:
            return "часа"
        else:
            return "часов"

    def _get_minute_word_ru(self, minutes):
        if minutes % 10 == 1 and minutes % 100 != 11:
            return "минута"
        elif minutes % 10 in [2, 3, 4] and minutes % 100 not in [12, 13, 14]:
            return "минуты"
        else:
            return "минут"

    def _is_listing_tts_enabled(self):
        settings = QSettings("MyTradeTools", "TF-Alerter")
        return settings.value("listing_tts_enabled", True, type=bool)

    def _refresh_audio_output_device(self, output):
        if output is None:
            return
        try:
            from PyQt6.QtMultimedia import QMediaDevices

            default_device = QMediaDevices.defaultAudioOutput()
            output.setDevice(default_device)
        except Exception:
            pass

    def _safe_audio_volume_from_percent(self, volume_percent):
        return config.slider_to_audio_volume(volume_percent)

    def _safe_audio_volume_unit(self, volume_01):
        return config.clamp_audio_volume(volume_01)

    def _start_player_clean(self, player, output, path, target_volume):
        from PyQt6.QtCore import QUrl

        safe_volume = self._safe_audio_volume_unit(target_volume)
        output.setVolume(0.0)
        player.stop()
        player.setSource(QUrl())
        player.setSource(QUrl.fromLocalFile(path))
        player.play()
        QTimer.singleShot(20, lambda out=output, vol=safe_volume: out.setVolume(vol))

    def _play_listing_sound(self, filename):
        from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

        path = config.get_sound_path("listing", filename)
        if not path or not os.path.exists(path):
            return

        try:
            duration_ms = None
            if path.lower().endswith(".wav"):
                import wave

                with wave.open(path, "rb") as wav_file:
                    frame_rate = wav_file.getframerate()
                    frame_count = wav_file.getnframes()
                    if frame_rate > 0:
                        duration_ms = int((frame_count / frame_rate) * 1000)
            if duration_ms and duration_ms > 0:
                self._last_listing_sound_duration_ms = duration_ms
        except Exception:
            pass

        if not hasattr(self, "_listing_player"):
            self._listing_player = QMediaPlayer()
            self._listing_output = QAudioOutput()
            self._listing_player.setAudioOutput(self._listing_output)

        self._refresh_audio_output_device(getattr(self, "_listing_output", None))

        settings = QSettings("MyTradeTools", "TF-Alerter")
        volume = self._safe_audio_volume_from_percent(
            settings.value("listing_volume", 80, type=int)
        )
        self._start_player_clean(self._listing_player, self._listing_output, path, volume)

    def _speak_listing_tts_async(
        self, message, engine_type, voice_id, language="ru", wait_for_sound=False
    ):
        if (
            not self.ui.listing_enable_check.isChecked()
            or not self._is_listing_tts_enabled()
        ):
            return

        delay_ms = 0
        if wait_for_sound:
            sound_duration = int(
                getattr(self, "_last_listing_sound_duration_ms", 1700) or 1700
            )
            delay_ms = max(300, sound_duration + 80)

        self._listing_tts_queue.append(
            (message, engine_type, voice_id, str(language or "ru"), delay_ms)
        )
        self._start_next_listing_tts()

    def _start_next_listing_tts(self):
        if not self._listing_tts_queue:
            self._listing_tts_busy = False
            return
        if self._listing_tts_busy:
            return
        if (
            not self.ui.listing_enable_check.isChecked()
            or not self._is_listing_tts_enabled()
        ):
            self._listing_tts_queue.clear()
            self._listing_tts_busy = False
            return

        message, engine_type, voice_id, language, delay_ms = (
            self._listing_tts_queue.popleft()
        )
        self._listing_tts_busy = True

        if str(engine_type or "system").lower() == "edge" and not self._edge_tts_service_blocked():
            self._listing_edge_tts_busy = True
            self._listing_edge_tts_started = False
            QTimer.singleShot(
                max(0, int(delay_ms)),
                lambda msg=message, vid=voice_id, lang=language: self._speak_listing_edge_tts(
                    msg, vid, lang
                ),
            )
            return

        def _speak_thread():
            try:
                import time

                if delay_ms > 0:
                    time.sleep(delay_ms / 1000.0)
                self._speak_listing_system_tts(message, voice_id, language)
            finally:
                self._listing_tts_busy = False
                QTimer.singleShot(0, self._start_next_listing_tts)

        thread = threading.Thread(target=_speak_thread, daemon=True)
        thread.start()

    def _speak_listing_system_tts(self, text, voice_id, language="ru"):
        try:
            import pyttsx3

            engine = pyttsx3.init()
            resolved_voice = self._resolve_system_tts_voice(engine, voice_id, language)
            if resolved_voice:
                engine.setProperty("voice", resolved_voice)
            settings = QSettings("MyTradeTools", "TF-Alerter")
            listing_volume = int(settings.value("listing_volume", 80))
            system_tts_volume = self._safe_audio_volume_from_percent(listing_volume)
            engine.setProperty("volume", system_tts_volume)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            print(f"⚠️ Ошибка Listing System TTS: {e}")

    def _speak_listing_edge_tts(self, text, voice_name, language="ru"):
        try:
            if (
                not self.ui.listing_enable_check.isChecked()
                or not self._is_listing_tts_enabled()
            ):
                self._listing_edge_tts_busy = False
                self._listing_edge_tts_started = False
                return

            import edge_tts
            import asyncio
            import tempfile

            voice_name = self._resolve_edge_tts_voice(voice_name, language)

            def _generate_worker(message_text, current_voice):
                try:

                    async def generate_audio():
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=".mp3"
                        ) as tmp_file:
                            tmp_path = tmp_file.name
                        communicate = edge_tts.Communicate(message_text, current_voice)
                        await communicate.save(tmp_path)
                        return tmp_path

                    tmp_path = asyncio.run(generate_audio())
                    with self._listing_edge_ready_lock:
                        self._listing_edge_ready_paths.append(tmp_path)
                except Exception as e:
                    print(f"⚠️ Listing Edge TTS generation error: {e}")
                    self._fallback_edge_tts_to_system_tts(
                        text, voice_name, language, kind="listing"
                    )

            thread = threading.Thread(
                target=_generate_worker,
                args=(text, voice_name),
                daemon=True,
            )
            thread.start()

        except ImportError:
            print("⚠️ Edge TTS не установлен. Установите: pip install edge-tts")
            self._fallback_edge_tts_to_system_tts(
                text, voice_name, language, kind="listing"
            )
        except Exception as e:
            print(f"⚠️ Ошибка Listing Edge TTS: {e}")
            self._fallback_edge_tts_to_system_tts(
                text, voice_name, language, kind="listing"
            )

    def _drain_listing_edge_ready(self):
        if (
            not self.ui.listing_enable_check.isChecked()
            or not self._is_listing_tts_enabled()
        ):
            self._listing_edge_tts_busy = False
            self._listing_edge_tts_started = False
            return

        if not self._listing_edge_tts_busy:
            return

        _no_item = object()
        ready_item = _no_item
        with self._listing_edge_ready_lock:
            if self._listing_edge_ready_paths:
                ready_item = self._listing_edge_ready_paths.popleft()

        if ready_item is _no_item:
            return

        if ready_item is False:
            self._fallback_edge_tts_to_system_tts(
                self._listing_edge_last_text,
                self._listing_edge_last_voice,
                self._listing_edge_last_language,
                kind="listing",
            )
            return

        if isinstance(ready_item, str):
            self._play_listing_edge_tts_file(ready_item)

    def _play_listing_edge_tts_file(self, tmp_path):
        from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
        from PyQt6.QtCore import QUrl

        if (
            not self.ui.listing_enable_check.isChecked()
            or not self._is_listing_tts_enabled()
        ):
            self._listing_edge_tts_busy = False
            self._listing_edge_tts_started = False
            return

        if not os.path.exists(tmp_path):
            print(f"⚠️ Listing Edge TTS file not found: {tmp_path}")
            self._listing_edge_tts_busy = False
            self._listing_edge_tts_started = False
            QTimer.singleShot(50, self._start_next_listing_tts)
            return

        if not hasattr(self, "_listing_edge_player"):
            self._listing_edge_player = QMediaPlayer()
            self._listing_edge_output = QAudioOutput()
            self._listing_edge_player.setAudioOutput(self._listing_edge_output)
            self._listing_edge_player.playbackStateChanged.connect(
                self._on_listing_edge_tts_playback_state
            )
            self._listing_edge_player.mediaStatusChanged.connect(
                self._on_listing_edge_tts_media_status
            )

        self._refresh_audio_output_device(getattr(self, "_listing_edge_output", None))

        settings = QSettings("MyTradeTools", "TF-Alerter")
        volume = self._safe_audio_volume_from_percent(
            settings.value("listing_volume", 80, type=int)
        )
        self._start_player_clean(
            self._listing_edge_player,
            self._listing_edge_output,
            tmp_path,
            volume,
        )

    def _on_listing_edge_tts_playback_state(self, state):
        from PyQt6.QtMultimedia import QMediaPlayer

        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._listing_edge_tts_started = True
            return

        if (
            state == QMediaPlayer.PlaybackState.StoppedState
            and self._listing_edge_tts_busy
            and self._listing_edge_tts_started
        ):
            self._listing_edge_tts_busy = False
            self._listing_edge_tts_started = False
            self._listing_tts_busy = False
            QTimer.singleShot(50, self._start_next_listing_tts)

    def _on_listing_edge_tts_media_status(self, status):
        from PyQt6.QtMultimedia import QMediaPlayer

        if (
            status == QMediaPlayer.MediaStatus.InvalidMedia
            and self._listing_edge_tts_busy
        ):
            self._listing_edge_tts_busy = False
            self._listing_edge_tts_started = False
            self._listing_tts_busy = False
            QTimer.singleShot(50, self._start_next_listing_tts)

    def on_funding_enable_toggled(self, checked):
        """Обработка вкл/выкл фандинга: затемняет/осветляет интерфейс"""
        # Применяем визуальные изменения немедленно
        self.ui.funding_content_widget.setEnabled(checked)

        # Изменяем прозрачность контента для визуального эффекта
        if checked:
            self.ui.funding_opacity_effect.setOpacity(1.0)  # Полная яркость
        else:
            self.ui.funding_opacity_effect.setOpacity(0.3)  # Затемнение

        # Обновляем статус сразу
        self._render_funding_exchange_status()

        # Выполняем остальные операции асинхронно через QTimer
        def _async_toggle():
            if checked:
                if hasattr(self, "funding_monitor") and hasattr(
                    self.funding_monitor, "clear_cache"
                ):
                    self.funding_monitor.clear_cache()
                self.funding_monitor.start()
            else:
                self.funding_monitor.stop()
                self._stop_funding_audio(tts_only=False)
                self._funding_exchange_status = {}
                self._render_funding_exchange_status()
            self.save_settings()

        QTimer.singleShot(0, _async_toggle)

    def on_funding_exchanges_changed(self, *args):
        if self.loading_settings:
            return

        if hasattr(self, "funding_monitor") and hasattr(
            self.funding_monitor, "clear_cache"
        ):
            self.funding_monitor.clear_cache()

        self.funding_alert_entries = []
        self.triggered_alerts = []
        self._pending_tts_entries = []
        self.ui.funding_log_list.clear()
        self._funding_exchange_status = {}

        if self.ui.funding_enable_check.isChecked() and hasattr(
            self, "funding_monitor"
        ):
            self.funding_monitor.poll()

        self._render_funding_exchange_status()
        self.save_settings()

    def on_funding_thresholds_changed(self, *args):
        if self.loading_settings:
            return

        self.funding_alert_entries = [
            entry
            for entry in self.funding_alert_entries
            if self._passes_funding_thresholds(entry.get("signed_rate_pct", 0.0))
        ]
        self.triggered_alerts = [
            entry
            for entry in self.triggered_alerts
            if self._passes_funding_thresholds(entry.get("signed_rate_pct", 0.0))
        ]
        self._pending_tts_entries = [
            item
            for item in self._pending_tts_entries
            if self._passes_funding_thresholds(
                (item.get("entry") or {}).get("signed_rate_pct", 0.0)
            )
        ]
        self._render_funding_log()

    def request_minimize(self):
        """Сворачивает окно."""
        self._allow_minimize = True
        self.showMinimized()

    def apply_interface_scale(self, scale_text):
        """Метод масштабирования без дрожания"""
        self.setUpdatesEnabled(False)
        try:
            value = int(scale_text.replace("%", ""))
            factor = value / 100.0

            # 1. Глобальный шрифт
            font = QApplication.font()
            font.setPointSize(int(10 * factor))
            QApplication.setFont(font)

            # 2. Размер окна
            base_width = int(config.WINDOW_SIZE[0] * factor)
            base_height = int(config.WINDOW_SIZE[1] * factor)
            expanded_width = max(int(base_width * 1.45), int(760 * factor))
            self._compact_window_size = (base_width, base_height)
            self._apply_window_width_for_active_tab()

            # 3. Принудительно увеличиваем кнопки (чтобы текст не заходил под них)
            self.ui.color_btn.setFixedSize(int(125 * factor), int(38 * factor))
            self.ui.clock_font_btn.setMinimumWidth(int(155 * factor))
            self.ui.lang_sel.setFixedSize(int(65 * factor), int(28 * factor))

            # 4. Стили контейнера
            self.central_widget.setStyleSheet(
                f"#mainContainer {{ background-color: {config.COLORS['background']}; "
                f"border: 2px solid {config.COLORS['border']}; border-radius: {int(15 * factor)}px; }}"
            )

            # 5. Шапка
            if hasattr(self, "title_bar"):
                self.title_bar.setFixedHeight(int(40 * factor))
                for btn in self.title_bar.findChildren(QPushButton):
                    btn.setFixedSize(int(45 * factor), int(40 * factor))

            # 6. Масштабируем комбобокс режима оверлея
            if hasattr(self.ui, "overlay_mode_combo"):
                self.ui.overlay_mode_combo.setMinimumWidth(int(260 * factor))

            # 7. Funding: лог увеличивается плавнее, а индикаторы бирж масштабируются с интерфейсом
            if hasattr(self.ui, "funding_log_list"):
                log_min_height = max(80, int(100 * factor))
                self.ui.funding_log_list.setMinimumHeight(log_min_height)
                self.ui.funding_log_list.setMaximumHeight(
                    16777215
                )  # Remove any previous fixed height

            if hasattr(self.ui, "funding_status_label"):
                status_font_px = max(8, int(9 * factor))
                self.ui.funding_status_label.setStyleSheet(
                    f"color:#777; font-size: {status_font_px}px;"
                )

        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def save_settings(self, *args):
        """Сохраняет всё в память Windows (реестр)"""
        # Не сохраняем во время загрузки
        if hasattr(self, "loading_settings") and self.loading_settings:
            return

        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("volume", self.ui.volume_slider.value())
        settings.setValue("overlay_active", self.ui.cb_overlay.isChecked())
        settings.setValue("overlay_size", self.ui.ov_size_slider.value())
        settings.setValue("language", self.ui.lang_sel.currentText())
        settings.setValue("overlay_pos", self.logic.overlay.pos())
        settings.setValue("window_pos", self.pos())
        settings.setValue("accent_color", config.COLORS["accent"])
        settings.setValue("accent_alpha", config.COLORS.get("accent_alpha", 255))
        settings.setValue(
            "overlay_font_family",
            (self.current_overlay_font or "").strip() or "Arial",
        )
        settings.setValue("overlay_bg_enabled", bool(self.overlay_bg_enabled))
        settings.setValue("overlay_bg_color", self.overlay_bg_color or "#000000")
        settings.setValue(
            "overlay_move_locked", self.ui.cb_lock_overlay_move.isChecked()
        )
        settings.setValue(
            "funding_binance_enabled", self.ui.funding_binance_check.isChecked()
        )
        settings.setValue(
            "funding_bybit_enabled", self.ui.funding_bybit_check.isChecked()
        )
        settings.setValue("funding_okx_enabled", self.ui.funding_okx_check.isChecked())
        settings.setValue(
            "funding_gate_enabled", self.ui.funding_gate_check.isChecked()
        )
        settings.setValue(
            "funding_bitget_enabled", self.ui.funding_bitget_check.isChecked()
        )
        settings.setValue("funding_enabled", self.ui.funding_enable_check.isChecked())
        settings.setValue(
            "funding_minutes", self.ui.funding_minutes_edit.text().strip()
        )
        settings.setValue(
            "funding_threshold_pos",
            self.ui.funding_threshold_pos_edit.text().strip(),
        )
        settings.setValue(
            "funding_threshold_neg",
            self.ui.funding_threshold_neg_edit.text().strip(),
        )
        settings.setValue("funding_volume", self.ui.funding_volume_slider.value())

        settings.setValue(
            "listing_binance_enabled", self.ui.listing_binance_check.isChecked()
        )
        settings.setValue(
            "listing_bybit_enabled", self.ui.listing_bybit_check.isChecked()
        )
        settings.setValue("listing_okx_enabled", self.ui.listing_okx_check.isChecked())
        settings.setValue(
            "listing_gate_enabled", self.ui.listing_gate_check.isChecked()
        )
        settings.setValue(
            "listing_bitget_enabled", self.ui.listing_bitget_check.isChecked()
        )
        settings.setValue("listing_enabled", self.ui.listing_enable_check.isChecked())
        settings.setValue(
            "listing_minutes", self.ui.listing_minutes_edit.text().strip()
        )
        settings.setValue("listing_volume", self.ui.listing_volume_slider.value())
        settings.setValue(
            "listing_binance_spot_enabled",
            self.ui.listing_binance_spot_check.isChecked(),
        )
        settings.setValue(
            "listing_binance_futures_enabled",
            self.ui.listing_binance_futures_check.isChecked(),
        )
        settings.setValue(
            "listing_bybit_spot_enabled",
            self.ui.listing_bybit_spot_check.isChecked(),
        )
        settings.setValue(
            "listing_bybit_futures_enabled",
            self.ui.listing_bybit_futures_check.isChecked(),
        )
        settings.setValue(
            "listing_okx_spot_enabled",
            self.ui.listing_okx_spot_check.isChecked(),
        )
        settings.setValue(
            "listing_okx_futures_enabled",
            self.ui.listing_okx_futures_check.isChecked(),
        )
        settings.setValue(
            "listing_gate_spot_enabled",
            self.ui.listing_gate_spot_check.isChecked(),
        )
        settings.setValue(
            "listing_gate_futures_enabled",
            self.ui.listing_gate_futures_check.isChecked(),
        )
        settings.setValue(
            "listing_bitget_spot_enabled",
            self.ui.listing_bitget_spot_check.isChecked(),
        )
        settings.setValue(
            "listing_bitget_futures_enabled",
            self.ui.listing_bitget_futures_check.isChecked(),
        )
        settings.setValue("session_enabled", self.ui.session_enable_check.isChecked())
        settings.setValue("session_volume", self.ui.session_volume_slider.value())
        # Сохраняем режим и список приложений для overlay
        settings.setValue("overlay_show_mode", config.OVERLAY_SHOW_MODE)
        settings.setValue("overlay_windows", config.OVERLAY_WINDOWS)

        # Сохраняем состояния таймфреймов напрямую через winreg (без открытия консоли)
        import winreg

        try:
            hkey = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                r"Software\MyTradeTools\TF-Alerter",
                0,
                winreg.KEY_SET_VALUE,
            )
            for tf, cb in self.ui.checkboxes.items():
                val = "Y" if cb.isChecked() else "N"
                key_name = self._tf_registry_key(tf)
                winreg.SetValueEx(hkey, key_name, 0, winreg.REG_SZ, val)
                log_write(f"[SAVE] {key_name} = {val} (checked={cb.isChecked()})")
            winreg.CloseKey(hkey)
            log_write("[SAVE] Значения записаны через winreg")
        except Exception as e:
            log_write(f"[SAVE] Ошибка при записи через winreg: {e}")
            # Fallback на QSettings
            for tf, cb in self.ui.checkboxes.items():
                val = "Y" if cb.isChecked() else "N"
                settings.setValue(self._tf_registry_key(tf), val)

        settings.sync()
        log_write("[SAVE] settings.sync() called")

    def load_settings(self):
        """Загружает всё из памяти при запуске"""
        settings = QSettings("MyTradeTools", "TF-Alerter")

        # 1. Загружаем Язык первым!
        saved_lang = settings.value("language", "RU")
        self.ui.lang_sel.setCurrentText(saved_lang)
        self.ui.change_language(saved_lang)

        # 2. Загружаем Масштаб
        scale_txt = settings.value("interface_scale_text", "100%")
        self.apply_interface_scale(scale_txt)

        # 3. Остальные настройки
        vol = int(settings.value("volume", 80))
        self.ui.volume_slider.setValue(vol)

        is_ov_active = settings.value("overlay_active", False, type=bool)
        self.ui.cb_overlay.setChecked(is_ov_active)
        # Если чекбокс выключен — скрываем оверлей сразу
        if is_ov_active:
            self.logic.overlay.show()
        else:
            self.logic.overlay.hide()

        size = int(settings.value("overlay_size", 40))
        self.ui.ov_size_slider.setValue(size)

        saved_color = settings.value("accent_color", config.COLORS["accent"])
        saved_alpha = int(settings.value("accent_alpha", 255))
        saved_font = settings.value("overlay_font_family", "Arial")
        if not isinstance(saved_font, str) or not saved_font.strip():
            saved_font = "Arial"
        self.current_overlay_font = saved_font
        self.ui.clock_font_btn.setText(saved_font)

        self.overlay_bg_enabled = settings.value("overlay_bg_enabled", False, type=bool)
        saved_bg_color = settings.value("overlay_bg_color", "#000000")
        if not isinstance(saved_bg_color, str) or not saved_bg_color.strip():
            saved_bg_color = "#000000"
        self.overlay_bg_color = saved_bg_color

        self.overlay_move_locked = settings.value(
            "overlay_move_locked", False, type=bool
        )
        self.ui.cb_lock_overlay_move.setChecked(self.overlay_move_locked)
        self.logic.overlay.move_locked = self.overlay_move_locked

        self.ui.funding_binance_check.setChecked(
            settings.value("funding_binance_enabled", True, type=bool)
        )
        self.ui.funding_bybit_check.setChecked(
            settings.value("funding_bybit_enabled", True, type=bool)
        )
        self.ui.funding_okx_check.setChecked(
            settings.value("funding_okx_enabled", True, type=bool)
        )
        self.ui.funding_gate_check.setChecked(
            settings.value("funding_gate_enabled", True, type=bool)
        )
        self.ui.funding_bitget_check.setChecked(
            settings.value("funding_bitget_enabled", True, type=bool)
        )
        funding_enabled = settings.value("funding_enabled", True, type=bool)
        self.ui.funding_enable_check.setChecked(funding_enabled)
        self.ui.funding_content_widget.setEnabled(funding_enabled)

        # Устанавливаем прозрачность в зависимости от состояния
        if funding_enabled:
            self.ui.funding_opacity_effect.setOpacity(1.0)
        else:
            self.ui.funding_opacity_effect.setOpacity(0.3)

        self.ui.funding_minutes_edit.setText(settings.value("funding_minutes", "15,5"))

        threshold_legacy = settings.value("funding_threshold", "")
        self.ui.funding_threshold_pos_edit.setText(
            settings.value("funding_threshold_pos", threshold_legacy or "0")
        )
        self.ui.funding_threshold_neg_edit.setText(
            settings.value("funding_threshold_neg", threshold_legacy or "0")
        )
        funding_vol = int(settings.value("funding_volume", 80))
        self.ui.funding_volume_slider.setValue(funding_vol)

        self.ui.listing_binance_check.setChecked(
            settings.value("listing_binance_enabled", True, type=bool)
        )
        self.ui.listing_bybit_check.setChecked(
            settings.value("listing_bybit_enabled", True, type=bool)
        )
        self.ui.listing_okx_check.setChecked(
            settings.value("listing_okx_enabled", True, type=bool)
        )
        self.ui.listing_gate_check.setChecked(
            settings.value("listing_gate_enabled", True, type=bool)
        )
        self.ui.listing_bitget_check.setChecked(
            settings.value("listing_bitget_enabled", True, type=bool)
        )
        listing_enabled = settings.value("listing_enabled", True, type=bool)
        self.ui.listing_enable_check.setChecked(listing_enabled)
        self.ui.listing_content_widget.setEnabled(listing_enabled)

        if listing_enabled:
            self.ui.listing_opacity_effect.setOpacity(1.0)
        else:
            self.ui.listing_opacity_effect.setOpacity(0.3)

        self.ui.listing_minutes_edit.setText(settings.value("listing_minutes", "15"))
        listing_vol = int(settings.value("listing_volume", 80))
        self.ui.listing_volume_slider.setValue(listing_vol)
        self.ui.listing_binance_spot_check.setChecked(
            settings.value("listing_binance_spot_enabled", True, type=bool)
        )
        self.ui.listing_binance_futures_check.setChecked(
            settings.value("listing_binance_futures_enabled", True, type=bool)
        )
        self.ui.listing_bybit_spot_check.setChecked(
            settings.value("listing_bybit_spot_enabled", True, type=bool)
        )
        self.ui.listing_bybit_futures_check.setChecked(
            settings.value("listing_bybit_futures_enabled", True, type=bool)
        )
        self.ui.listing_okx_spot_check.setChecked(
            settings.value("listing_okx_spot_enabled", True, type=bool)
        )
        self.ui.listing_okx_futures_check.setChecked(
            settings.value("listing_okx_futures_enabled", True, type=bool)
        )
        self.ui.listing_gate_spot_check.setChecked(
            settings.value("listing_gate_spot_enabled", True, type=bool)
        )
        self.ui.listing_gate_futures_check.setChecked(
            settings.value("listing_gate_futures_enabled", True, type=bool)
        )
        self.ui.listing_bitget_spot_check.setChecked(
            settings.value("listing_bitget_spot_enabled", True, type=bool)
        )
        self.ui.listing_bitget_futures_check.setChecked(
            settings.value("listing_bitget_futures_enabled", True, type=bool)
        )

        session_enabled = settings.value("session_enabled", True, type=bool)
        self.ui.session_enable_check.setChecked(session_enabled)
        self.ui.session_content_widget.setEnabled(session_enabled)
        if session_enabled:
            self.ui.session_opacity_effect.setOpacity(1.0)
        else:
            self.ui.session_opacity_effect.setOpacity(0.3)
        self.ui.session_volume_slider.setValue(
            int(settings.value("session_volume", 80))
        )

        self._load_listing_alert_history(settings)
        self._load_funding_triggered_history(settings)

        config.COLORS["accent"] = saved_color
        config.COLORS["accent_alpha"] = saved_alpha
        self.logic.overlay.update_style(
            saved_color,
            size,
            saved_alpha,
            saved_font,
            self.overlay_bg_enabled,
            self.overlay_bg_color,
        )

        pos = settings.value("overlay_pos")
        if pos:
            self.logic.overlay.move(pos)

        # Загружаем режим отображения overlay и список приложений
        overlay_mode = settings.value("overlay_show_mode", "custom")
        config.OVERLAY_SHOW_MODE = overlay_mode
        # Используем индекс вместо текста: 0 = "always", 1 = "custom"
        mode_index = 0 if overlay_mode == "always" else 1
        self.ui.overlay_mode_combo.setCurrentIndex(mode_index)

        overlay_windows = settings.value("overlay_windows", config.OVERLAY_WINDOWS)
        if isinstance(overlay_windows, str):
            # Конвертируем строку в список если нужно
            overlay_windows = overlay_windows.split(", ") if overlay_windows else []
        elif not isinstance(overlay_windows, list):
            overlay_windows = []

        config.OVERLAY_WINDOWS = overlay_windows

        # Загружаем звуки для каждого таймфрейма
        # ВАЖНО: каждый таймфрейм загружается ОТДЕЛЬНО, без связи с другими
        for tf_key in config.TIMEFRAMES.keys():
            # Используем разные имена для 1M в QSettings (1Month вместо 1M)
            # чтобы избежать case-insensitive конфликтов в Windows реестре
            qsettings_key = tf_key.replace("1M", "1Month") if tf_key == "1M" else tf_key

            # Читаем ОТДЕЛЬНО для каждого tf_key
            main_sound = settings.value(f"sound_main_{qsettings_key}")
            tick_sound = settings.value(f"sound_tick_{qsettings_key}")
            transition_sound = settings.value(f"sound_transition_{qsettings_key}")

            # Если не найдено в QSettings, используем значение по умолчанию из config
            if not main_sound:
                main_sound = config.TIMEFRAMES[tf_key]["file"]
            if not tick_sound:
                tick_sound = config.SOUND_TICK_BY_TF.get(tf_key)
            if not transition_sound:
                transition_sound = config.SOUND_TRANSITION_BY_TF.get(tf_key)

            default_main = config.TIMEFRAMES[tf_key]["file"]
            default_tick = config.SOUND_TICK_BY_TF.get(tf_key, "")
            default_transition = config.SOUND_TRANSITION_BY_TF.get(tf_key, "")

            main_sound = config.sanitize_sound_filename(main_sound, default_main)
            tick_sound = config.sanitize_sound_filename(tick_sound, default_tick)
            transition_sound = config.sanitize_sound_filename(
                transition_sound, default_transition
            )

            # Обновляем config БЕЗ проверки существования
            # (проверка будет при попытке воспроизведения в logic.play_voice)
            if main_sound:
                config.TIMEFRAMES[tf_key]["file"] = main_sound

            if tick_sound:
                config.SOUND_TICK_BY_TF[tf_key] = tick_sound

            if transition_sound:
                config.SOUND_TRANSITION_BY_TF[tf_key] = transition_sound

        # Загружаем позицию главного окна
        window_pos = settings.value("window_pos")
        if window_pos:
            self.move(window_pos)

        # Загружаем и регистрируем горячую клавишу
        hotkey = settings.value("hotkey", "")
        hotkey_codes = settings.value("hotkey_codes", "")
        # Игнорируем placeholder текст и невалидные значения
        invalid_hotkeys = ["", "Нажмите клавишу...", "Не задана", "\\"]
        if hotkey and hotkey not in invalid_hotkeys:
            codes = None
            if hotkey_codes:
                try:
                    codes = [
                        int(x)
                        for x in str(hotkey_codes).split(",")
                        if x.strip().isdigit()
                    ]
                except Exception:
                    codes = None
            if codes:
                self.hotkey_manager.register_hotkey_codes(codes, hotkey)

        # Загружаем состояния таймфреймов из реестра
        # Значения хранятся как "Y"/"N" строки
        log_write("\n[LOAD] Загружаем состояния таймфреймов из реестра:")
        for tf in config.TIMEFRAMES.keys():
            val = settings.value(self._tf_registry_key(tf))
            # Конвертируем строку в boolean: "Y" -> True, всё остальное -> False
            is_checked = (str(val).upper() == "Y") if val is not None else False
            if tf in self.ui.checkboxes:
                self.ui.checkboxes[tf].setChecked(is_checked)
                log_write(
                    f"[LOAD]   {self._tf_registry_key(tf)}: val={val} -> is_checked={is_checked}"
                )

    def apply_overlay_visual(self):
        """Применяет текущий стиль overlay (цвет, размер, шрифт, фон)"""
        overlay_size = self.ui.ov_size_slider.value()
        accent_color = config.COLORS.get("accent", "#ffffff")
        accent_alpha = int(config.COLORS.get("accent_alpha", 255))
        self.logic.overlay.update_style(
            accent_color,
            overlay_size,
            accent_alpha,
            self.current_overlay_font,
            self.overlay_bg_enabled,
            self.overlay_bg_color,
        )

    def _parse_percent_threshold(self, value, default=0.0):
        try:
            normalized = str(value).strip().replace(",", ".")
            if not normalized:
                return float(default)
            return float(normalized)
        except Exception:
            return float(default)

    def _is_ui_language_en(self):
        try:
            current = self.ui.lang_sel.currentText()
        except Exception:
            current = ""

        if not current:
            settings = QSettings("MyTradeTools", "TF-Alerter")
            current = settings.value("language", "RU")

        return str(current).strip().upper().startswith("EN")

    def _warn_source_errors(self, kind, status_map):
        try:
            import time

            if not isinstance(status_map, dict):
                return

            now_ts = int(time.time())
            for exchange_key, state in status_map.items():
                error = str((state or {}).get("error", "") or "").strip()
                if not error:
                    continue

                key = (kind, exchange_key, error)
                last_ts = int(self._source_error_last.get(key, 0) or 0)
                if now_ts - last_ts < 1800:
                    continue

                self._source_error_last[key] = now_ts
                if self._is_ui_language_en():
                    log_write(
                        f"[SOURCE] Cannot update {kind}:{exchange_key.upper()} — {error}"
                    )
                else:
                    log_write(
                        f"[SOURCE] Не удалось обновить {kind}:{exchange_key.upper()} — {error}"
                    )
        except Exception:
            pass

    def _normalize_symbol_text(self, symbol):
        raw = str(symbol or "").strip().upper()
        if not raw:
            return ""
        cleaned = "".join(ch for ch in raw if ch.isalnum())
        return cleaned or raw.replace("_", "").replace("-", "")

    def _is_valid_listing_symbol(self, value):
        symbol = self._normalize_symbol_text(value)
        if not symbol:
            return False
        if len(symbol) < 2 or len(symbol) > 15:
            return False
        blocked = {
            "UTC",
            "USDT",
            "USDC",
            "USD",
            "SPOT",
            "FUTURES",
            "PERP",
            "PERPETUAL",
            "SWAP",
            "LISTING",
            "TRADING",
        }
        if symbol in blocked:
            return False
        if symbol.isdigit():
            return False
        return True

    def _extract_symbol_from_title(self, title):
        if not isinstance(title, str) or not title:
            return ""

        match = re.search(
            r"\b([A-Z0-9]{2,15})[-_/ ]?USDT(?:[-_/ ]?(SWAP|PERP|PERPETUAL))?\b",
            title,
            re.IGNORECASE,
        )
        if match:
            candidate = self._normalize_symbol_text(match.group(1))
            if self._is_valid_listing_symbol(candidate):
                return candidate

        match = re.search(r"\b([A-Z0-9]{2,10})USDT\b", title)
        if match:
            candidate = self._normalize_symbol_text(match.group(1))
            if self._is_valid_listing_symbol(candidate):
                return candidate

        all_parens = re.findall(r"\(([^)]+)\)", title)
        for chunk in all_parens:
            candidate = self._normalize_symbol_text(chunk)
            if self._is_valid_listing_symbol(candidate):
                return candidate

        return ""

    def _normalize_listing_type(self, value):
        raw = str(value or "").strip().lower()
        if raw in ("spot", "futures"):
            return raw
        if raw in ("future", "perp", "perpetual", "swap"):
            return "futures"
        return ""

    def _resolve_listing_type(self, payload):
        normalized = self._normalize_listing_type(payload.get("listing_type", ""))
        if normalized:
            return normalized

        title = str(payload.get("title", "") or "")
        classified = self._classify_listing_type(title)
        if classified:
            return classified

        article_code = str(payload.get("article_code", "") or "")
        lowered = f"{title} {article_code}".lower()
        if any(
            token in lowered
            for token in (
                "futures",
                "perpetual",
                "swap",
                "contract",
                "usdt-m",
                "newfutureslistings",
                "perp",
            )
        ):
            return "futures"
        if any(
            token in lowered
            for token in ("spot", "spot trading", "spot listing", "newspotlistings")
        ):
            return "spot"

        # Most generic "listing" announcements are spot listings unless explicitly futures.
        return "spot"

    def _classify_listing_type(self, title):
        text = str(title or "").lower()
        futures_words = (
            "futures",
            "perpetual",
            "swap",
            "perp",
            "usdt-m",
            "contract",
            "coin-m",
            "delivery",
        )
        spot_words = ("spot", "spot trading", "spot listing")
        if any(word in text for word in futures_words):
            return "futures"
        if any(word in text for word in spot_words):
            return "spot"
        return ""

    def _is_listing_exchange_enabled(self, exchange_key):
        key = str(exchange_key or "").strip().lower()
        mapping = {
            "binance": self.ui.listing_binance_check,
            "bybit": self.ui.listing_bybit_check,
            "okx": self.ui.listing_okx_check,
            "gate": self.ui.listing_gate_check,
            "bitget": self.ui.listing_bitget_check,
        }
        widget = mapping.get(key)
        return bool(widget and widget.isChecked())

    def _is_listing_type_enabled(self, entry):
        listing_type = self._normalize_listing_type(entry.get("listing_type", ""))
        exchange_key = str(entry.get("exchange", "")).strip().lower()
        spot_checks = {
            "binance": self.ui.listing_binance_spot_check,
            "bybit": self.ui.listing_bybit_spot_check,
            "okx": self.ui.listing_okx_spot_check,
            "gate": self.ui.listing_gate_spot_check,
            "bitget": self.ui.listing_bitget_spot_check,
        }
        futures_checks = {
            "binance": self.ui.listing_binance_futures_check,
            "bybit": self.ui.listing_bybit_futures_check,
            "okx": self.ui.listing_okx_futures_check,
            "gate": self.ui.listing_gate_futures_check,
            "bitget": self.ui.listing_bitget_futures_check,
        }
        spot_widget = spot_checks.get(exchange_key)
        futures_widget = futures_checks.get(exchange_key)
        spot_enabled = bool(spot_widget.isChecked()) if spot_widget else False
        futures_enabled = bool(futures_widget.isChecked()) if futures_widget else False

        if not spot_enabled and not futures_enabled:
            return False

        if listing_type == "spot":
            return spot_enabled
        if listing_type == "futures":
            return futures_enabled
        return spot_enabled or futures_enabled

    def _format_listing_type_label(self, listing_type):
        normalized = self._normalize_listing_type(listing_type) or "spot"
        if self._is_ui_language_en():
            return "(Spot)" if normalized == "spot" else "(Futures)"
        return "(спот)" if normalized == "spot" else "(фьюч)"

    def _format_month_day(self, dt):
        if not dt:
            return "—"
        if self._is_ui_language_en():
            return dt.strftime("%d %b")
        months = [
            "янв",
            "фев",
            "мар",
            "апр",
            "май",
            "июн",
            "июл",
            "авг",
            "сен",
            "окт",
            "ноя",
            "дек",
        ]
        return f"{dt.day:02d} {months[dt.month - 1]}"

    def _passes_funding_thresholds(self, signed_rate_pct):
        try:
            rate = float(signed_rate_pct or 0.0)
        except Exception:
            rate = 0.0

        pos_threshold = self._parse_percent_threshold(
            self.ui.funding_threshold_pos_edit.text(), 0.0
        )
        neg_threshold = self._parse_percent_threshold(
            self.ui.funding_threshold_neg_edit.text(), 0.0
        )

        pos_threshold = abs(pos_threshold)
        neg_threshold = -abs(neg_threshold)

        if rate >= 0:
            return rate >= pos_threshold
        return rate <= neg_threshold

    def _funding_minutes_threshold(self):
        raw = str(self.ui.funding_minutes_edit.text() or "").strip()
        raw = raw.replace(",", ".")
        if not raw:
            return 15.5
        try:
            value = float(raw)
            return max(0.0, min(1440.0, value))
        except Exception:
            return 15.5

    def _normalize_next_funding_time(self, entry):
        import time

        if not isinstance(entry, dict):
            return 0

        try:
            next_time = int(entry.get("next_funding_time", 0) or 0)
        except Exception:
            next_time = 0

        if next_time > 0:
            entry["next_funding_time"] = next_time
            return next_time

        try:
            minutes = float(str(entry.get("minutes_to", "0")).strip().replace(",", "."))
        except Exception:
            minutes = 0.0

        if minutes > 0:
            next_time = int(time.time() * 1000) + int(minutes * 60_000)
            entry["next_funding_time"] = next_time
            entry["minutes_to"] = int(round(minutes))
            return next_time

        return 0

    def _entry_identity_key(self, entry):
        next_time = self._normalize_next_funding_time(entry)
        time_bucket = int(next_time // (10 * 60 * 1000)) if next_time > 0 else -1
        return (
            str(entry.get("exchange", "")).strip().lower(),
            self._normalize_symbol_text(entry.get("symbol", "")),
            time_bucket,
        )

    def _entry_notification_key(self, entry):
        import time

        identity = self._entry_identity_key(entry)
        next_time = int(entry.get("next_funding_time", 0) or 0)
        now_ms = int(time.time() * 1000)
        diff_ms = max(0, next_time - now_ms) if next_time > 0 else 10**18
        is_urgent = diff_ms <= 5 * 60 * 1000
        return identity + (1 if is_urgent else 0,)

    def _mark_and_check_new_notification(self, entry):
        key = self._entry_notification_key(entry)
        if key in self._seen_funding_keys:
            return False
        self._seen_funding_keys.add(key)
        return True

    def _find_existing_entry_index(self, entry):
        key = self._entry_identity_key(entry)
        for idx, existing in enumerate(self.funding_alert_entries):
            if self._entry_identity_key(existing) == key:
                return idx
        return -1

    def append_funding_log(self, entry, trigger_alert=False):
        if not entry:
            return
        if not self.ui.funding_enable_check.isChecked():
            return
        if self._normalize_next_funding_time(entry) <= 0:
            return

        existing_idx = self._find_existing_entry_index(entry)
        if existing_idx >= 0:
            existing = self.funding_alert_entries[existing_idx]
            prev_triggered = bool(existing.get("triggered", False))
            prev_trigger_time = existing.get("trigger_time")
            existing.update(entry)
            if prev_triggered and not existing.get("triggered", False):
                existing["triggered"] = True
            if prev_trigger_time and not existing.get("trigger_time"):
                existing["trigger_time"] = prev_trigger_time
        else:
            self.funding_alert_entries.append(entry)

        # Сортируем: сначала по минимальному времени, потом по максимальному % (по модулю)
        self.funding_alert_entries = sorted(
            self.funding_alert_entries,
            key=lambda item: (
                (
                    int(item.get("next_funding_time", 0) or 0)
                    if int(item.get("next_funding_time", 0) or 0) > 0
                    else 10**18
                ),
                -abs(item.get("signed_rate_pct", 0)),
            ),
        )[:200]
        self._render_funding_log()

        # Если это новая запись из лога (не алерт), проигрываем алерт
        if trigger_alert:
            self._enqueue_pending_tts_entry(entry)
            self._funding_tts_timer.start(550)

    def append_funding_log_text(self, payload):
        if not isinstance(payload, dict):
            return
        if self._funding_paused:
            return
        if not self.ui.funding_enable_check.isChecked():
            return

        exchange_name = str(payload.get("exchange", "") or "").strip()
        symbol_name = self._normalize_symbol_text(payload.get("symbol", ""))
        if not exchange_name or not symbol_name:
            return

        signed_rate_pct = payload.get("signed_rate_pct", 0.0)
        if not self._passes_funding_thresholds(signed_rate_pct):
            return

        entry = {
            "index": 0,
            "exchange": exchange_name,
            "symbol": symbol_name,
            "minutes_to": payload.get("minutes_to", 0),
            "signed_rate_pct": signed_rate_pct,
            "next_funding_time": payload.get("next_funding_time", 0),
            "triggered": False,
            "trigger_time": None,
        }
        if self._normalize_next_funding_time(entry) <= 0:
            return
        entry["message"] = (
            f"{entry['exchange']} {entry['symbol']} — "
            f"funding {entry['signed_rate_pct']:.2f}% — "
            f"{'until funding' if self._is_ui_language_en() else 'до фандинга'} "
            f"{entry['minutes_to']} {'min' if self._is_ui_language_en() else 'мин'}"
        )
        is_new = self._find_existing_entry_index(entry) < 0
        should_notify = self._mark_and_check_new_notification(entry)
        if is_new:
            self.funding_alert_counter += 1
            entry["index"] = self.funding_alert_counter
        self.append_funding_log(entry, trigger_alert=should_notify)
        if not is_new:
            return

    def on_funding_status_update(self, payload):
        if not isinstance(payload, dict):
            return
        status_map = payload.get("exchanges")
        if isinstance(status_map, dict):
            self._funding_exchange_status = status_map
            self._render_funding_exchange_status()
            self._warn_source_errors("funding", status_map)

    def _get_funding_passed_counts(self):
        counts = {}
        now_ms = int(time.time() * 1000)
        threshold_minutes = self._funding_minutes_threshold()
        threshold_ms = int(max(0.0, threshold_minutes) * 60 * 1000)

        exchange_aliases = {
            "binance": "binance",
            "bybit": "bybit",
            "okx": "okx",
            "gate": "gate",
            "gate.io": "gate",
            "bitget": "bitget",
        }

        for entry in list(self.funding_alert_entries):
            if not self._passes_funding_thresholds(entry.get("signed_rate_pct", 0.0)):
                continue

            next_funding_time = int(entry.get("next_funding_time", 0) or 0)
            if next_funding_time <= 0:
                continue

            time_diff_ms = next_funding_time - now_ms
            if time_diff_ms < 0:
                continue
            if time_diff_ms > threshold_ms:
                continue

            exchange_raw = str(entry.get("exchange", "") or "").strip().lower()
            exchange_key = exchange_aliases.get(exchange_raw, exchange_raw)
            if not exchange_key:
                continue

            counts[exchange_key] = counts.get(exchange_key, 0) + 1

        return counts

    def _render_funding_exchange_status(self):
        if not hasattr(self.ui, "funding_status_label"):
            return

        status_ok_color = "#1e90ff"

        status_map = (
            self._funding_exchange_status
            if isinstance(self._funding_exchange_status, dict)
            else {}
        )

        exchanges = [
            ("binance", "Binance", self.ui.funding_binance_check.isChecked()),
            ("bybit", "Bybit", self.ui.funding_bybit_check.isChecked()),
            ("okx", "OKX", self.ui.funding_okx_check.isChecked()),
            ("gate", "Gate", self.ui.funding_gate_check.isChecked()),
            ("bitget", "Bitget", self.ui.funding_bitget_check.isChecked()),
        ]

        if not self.ui.funding_enable_check.isChecked():
            chunks = [
                f"<span style='color:#666;'>● {name}: off</span>"
                for _, name, _ in exchanges
            ]
            self.ui.funding_status_label.setText("&nbsp;&nbsp;".join(chunks))
            return

        chunks = []
        passed_counts = self._get_funding_passed_counts()
        for key, name, is_enabled in exchanges:
            state = status_map.get(key, {}) if isinstance(status_map, dict) else {}
            fetched = int(state.get("fetched", 0) or 0)
            passed = int(passed_counts.get(key, 0) or 0)
            error = str(state.get("error", "") or "").strip()

            if not is_enabled:
                chunks.append(f"<span style='color:#666;'>● {name}: off</span>")
                continue

            if error:
                chunks.append(
                    f"<span style='color:{config.COLORS['danger']};'>● {name}: err</span>"
                )
                continue

            if fetched > 0:
                chunks.append(
                    f"<span style='color:{status_ok_color};'>● {name}: {fetched}/{passed}</span>"
                )
            else:
                chunks.append(f"<span style='color:#888;'>● {name}: 0/0</span>")

        with self._system_tts_lock:
            system_busy = bool(self._system_tts_busy)
            system_queue_len = len(self._system_tts_queue)

        edge_queue_len = len(self._edge_tts_queue)
        pending_len = len(self._pending_tts_entries)
        tts_active = (
            bool(self._funding_tts_batch_active)
            or bool(self._funding_tts_sound_pending)
            or bool(self._edge_tts_busy)
            or system_busy
            or edge_queue_len > 0
            or system_queue_len > 0
            or pending_len > 0
        )
        total_tts_queue = pending_len + edge_queue_len + system_queue_len
        if tts_active:
            chunks.append(
                f"<span style='color:{status_ok_color};'>● TTS: active ({total_tts_queue})</span>"
            )
        else:
            chunks.append("<span style='color:#666;'>● TTS: idle</span>")

        self.ui.funding_status_label.setText("&nbsp;&nbsp;".join(chunks))

    def clear_funding_log(self):
        self._funding_paused = True
        self.ui.funding_log_list.clear()
        self.funding_alert_counter = 0
        self.funding_alert_entries = []
        self.triggered_alerts = []
        self.funding_triggered_history = []
        self._funding_triggered_history_keys = set()
        self._save_funding_triggered_history()
        self._pending_tts_entries = []
        self._seen_funding_keys = set()
        self._funding_tts_sound_pending = False
        self._funding_tts_batch_active = False
        self._funding_tts_timer.stop()
        self._stop_funding_audio(tts_only=False)
        if hasattr(self, "funding_monitor") and hasattr(
            self.funding_monitor, "clear_cache"
        ):
            self.funding_monitor.clear_cache()
        if hasattr(self, "_funding_clear_resume_timer"):
            self._funding_clear_resume_timer.start(60000)

    def _update_funding_log_realtime(self):
        """Обновляет логи в реальном времени: время, секунды, зачеркивание"""
        import time

        self._enforce_funding_audio_policy()

        now_ms = int(time.time() * 1000)

        # Проверяем каждый алерт
        to_move = []
        for entry in self.funding_alert_entries:
            next_funding_time = entry.get("next_funding_time", 0)
            if not next_funding_time:
                continue

            time_diff_ms = next_funding_time - now_ms

            # Если время прошло и алерт еще не triggered
            if time_diff_ms <= 0 and not entry.get("triggered", False):
                entry["triggered"] = True
                entry["trigger_time"] = now_ms
                self._record_funding_triggered_entry(entry)

            # Если алерт triggered и прошло 5 секунд после срабатывания
            trigger_time = entry.get("trigger_time")
            if entry.get("triggered", False) and trigger_time:
                elapsed_since_trigger = now_ms - trigger_time
                if elapsed_since_trigger >= 5000:  # 5 секунд
                    to_move.append(entry)

        # Перемещаем завершенные алерты в список triggered_alerts
        for entry in to_move:
            self.funding_alert_entries.remove(entry)
            self.triggered_alerts.append(entry)

        # Ограничиваем количество triggered_alerts до 10
        if len(self.triggered_alerts) > self.max_triggered_alerts:
            # Удаляем самые старые (первые в списке)
            self.triggered_alerts = self.triggered_alerts[-self.max_triggered_alerts :]

        # Перерисовываем лог
        if to_move or self.funding_alert_entries:
            self._render_funding_log()
        self._render_funding_exchange_status()

    def _get_today_start_ms(self):
        now = datetime.datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return int(today.timestamp() * 1000)

    def _record_funding_triggered_entry(self, entry):
        if not isinstance(entry, dict):
            return
        next_time = int(entry.get("next_funding_time", 0) or 0)
        key = (
            str(entry.get("exchange", "")).strip().lower(),
            self._normalize_symbol_text(entry.get("symbol", "")),
            int(next_time // (10 * 60 * 1000)) if next_time > 0 else -1,
        )
        if key in self._funding_triggered_history_keys:
            return
        snapshot = dict(entry)
        snapshot["triggered_at"] = int(time.time() * 1000)
        self._funding_triggered_history_keys.add(key)
        self.funding_triggered_history.append(snapshot)
        self._save_funding_triggered_history()

    def _save_funding_triggered_history(self):
        try:
            settings = QSettings("MyTradeTools", "TF-Alerter")
            settings.setValue(
                "funding_triggered_history_json",
                json.dumps(self.funding_triggered_history, ensure_ascii=True),
            )
        except Exception:
            pass

    def _load_funding_triggered_history(self, settings):
        try:
            raw = settings.value("funding_triggered_history_json", "")
            if not raw:
                return
            data = json.loads(raw)
            if not isinstance(data, list):
                return
            self.funding_triggered_history = [
                item for item in data if isinstance(item, dict)
            ]
            self._funding_triggered_history_keys = set()
            for entry in self.funding_triggered_history:
                next_time = int(entry.get("next_funding_time", 0) or 0)
                key = (
                    str(entry.get("exchange", "")).strip().lower(),
                    self._normalize_symbol_text(entry.get("symbol", "")),
                    int(next_time // (10 * 60 * 1000)) if next_time > 0 else -1,
                )
                self._funding_triggered_history_keys.add(key)
        except Exception:
            self.funding_triggered_history = []
            self._funding_triggered_history_keys = set()

    def on_funding_alert(self, payload):
        if not isinstance(payload, dict):
            return
        if self._funding_paused:
            return
        if not self.ui.funding_enable_check.isChecked():
            return

        signed_rate_pct = payload.get("signed_rate_pct", 0.0)
        if not self._passes_funding_thresholds(signed_rate_pct):
            return

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        entry = {
            "index": 0,
            "ts": ts,
            "exchange": payload.get("exchange", ""),
            "symbol": self._normalize_symbol_text(payload.get("symbol", "")),
            "minutes_to": payload.get("minutes_to", 0),
            "signed_rate_pct": signed_rate_pct,
            "next_funding_time": payload.get("next_funding_time", 0),
            "triggered": False,
            "trigger_time": None,
        }
        if self._normalize_next_funding_time(entry) <= 0:
            return
        entry["message"] = (
            f"{entry['exchange']} {entry['symbol']} — "
            f"funding {entry['signed_rate_pct']:.2f}% — "
            f"{'until funding' if self._is_ui_language_en() else 'до фандинга'} "
            f"{entry['minutes_to']} {'min' if self._is_ui_language_en() else 'мин'}"
        )

        # Определяем сколько бирж выбрано
        exchanges_count = 0
        if self.ui.funding_binance_check.isChecked():
            exchanges_count += 1
        if self.ui.funding_bybit_check.isChecked():
            exchanges_count += 1
        if self.ui.funding_okx_check.isChecked():
            exchanges_count += 1
        if self.ui.funding_gate_check.isChecked():
            exchanges_count += 1
        if self.ui.funding_bitget_check.isChecked():
            exchanges_count += 1
        is_multiple_exchanges = exchanges_count > 1

        # Генерируем голосовые сообщения
        entry["voice_message_ru"] = self._format_funding_message_ru(
            entry, is_multiple_exchanges
        )
        entry["voice_message_en"] = self._format_funding_message_en(
            entry, is_multiple_exchanges
        )

        is_new = self._find_existing_entry_index(entry) < 0
        should_notify = self._mark_and_check_new_notification(entry)
        if is_new:
            self.funding_alert_counter += 1
            entry["index"] = self.funding_alert_counter
        self.append_funding_log(
            entry, trigger_alert=False
        )  # Не триггерим алерт для истинных алертов
        if not is_new or not should_notify:
            return
        # Истинные алерты тоже отправляем в общую очередь, чтобы порядок озвучки
        # всегда был: меньшее время до фандинга -> больший модуль процента.
        self._enqueue_pending_tts_entry(entry)
        self._funding_tts_timer.start(550)

    def _trigger_funding_alert(self, entry):
        """Триггерит алерт для записи в логе"""
        if not self.ui.funding_enable_check.isChecked():
            return
        time_text_ru, time_text_en = self._format_tts_time_text(entry)

        # Определяем сколько бирж выбрано
        exchanges_count = 0
        if self.ui.funding_binance_check.isChecked():
            exchanges_count += 1
        if self.ui.funding_bybit_check.isChecked():
            exchanges_count += 1
        if self.ui.funding_okx_check.isChecked():
            exchanges_count += 1
        if self.ui.funding_gate_check.isChecked():
            exchanges_count += 1
        if self.ui.funding_bitget_check.isChecked():
            exchanges_count += 1
        is_multiple_exchanges = exchanges_count > 1

        # Генерируем голосовые сообщения
        entry["voice_message_ru"] = self._format_funding_message_ru(
            entry, is_multiple_exchanges, time_text_ru
        )
        entry["voice_message_en"] = self._format_funding_message_en(
            entry, is_multiple_exchanges, time_text_en
        )

        settings = QSettings("MyTradeTools", "TF-Alerter")
        sound_enabled = settings.value("funding_sound_enabled", True, type=bool)
        tts_enabled = settings.value("funding_tts_enabled", True, type=bool)
        funding_volume = int(settings.value("funding_volume", 80))

        if sound_enabled:
            try:
                sound_file = settings.value(
                    "funding_sound_file", config.SOUND_FUNDING_ALERT
                )
                sound_file = (
                    str(sound_file or "").strip() or config.SOUND_FUNDING_ALERT
                )
                if sound_file:
                    self._play_funding_sound(sound_file, funding_volume)
                else:
                    self._play_funding_sound(config.SOUND_FUNDING_ALERT, funding_volume)
            except Exception:
                pass

        if tts_enabled:
            tts_engine = settings.value("funding_tts_engine", "system")
            tts_voice_id = settings.value("funding_tts_voice_id", "")
            tts_language = settings.value("funding_tts_language", "ru")

            # Выбираем сообщение на нужном языке
            message = (
                entry["voice_message_ru"]
                if tts_language == "ru"
                else entry["voice_message_en"]
            )

            # TTS должен ждать окончания звука, если звук был включен
            self._speak_tts_async(
                message,
                tts_engine,
                tts_voice_id,
                wait_for_sound=sound_enabled,
                language=tts_language,
            )

    def _is_funding_tts_enabled(self):
        settings = QSettings("MyTradeTools", "TF-Alerter")
        return settings.value("funding_tts_enabled", True, type=bool)

    def _resolve_system_tts_voice(self, engine, requested_voice_id, language="ru"):
        try:
            lang_key = "ru" if str(language or "ru").lower().startswith("ru") else "en"
            voices = engine.getProperty("voices") or []

            if requested_voice_id:
                for voice in voices:
                    if getattr(voice, "id", "") != requested_voice_id:
                        continue
                    return getattr(voice, "id", "")

            for voice in voices:
                blob = (
                    f"{getattr(voice, 'id', '')} {getattr(voice, 'name', '')} "
                    f"{getattr(voice, 'languages', '')}"
                ).lower()
                if lang_key in blob:
                    return getattr(voice, "id", "")

            if requested_voice_id:
                return requested_voice_id
            if voices:
                return getattr(voices[0], "id", "")
        except Exception:
            pass
        return requested_voice_id

    def _resolve_edge_tts_voice(self, requested_voice_name, language="ru"):
        lang_is_ru = str(language or "ru").lower().startswith("ru")
        requested = str(requested_voice_name or "").strip()
        if requested:
            return requested
        if lang_is_ru:
            return "ru-RU-SvetlanaNeural"
        return "en-US-AriaNeural"

    def _edge_tts_service_blocked(self):
        settings = QSettings("MyTradeTools", "TF-Alerter")
        return bool(settings.value("edge_tts_service_blocked", False, type=bool))

    def _switch_tts_engine_to_system(self, kind="funding"):
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("edge_tts_service_blocked", True)
        mapping = {
            "funding": "funding_tts_engine",
            "listing": "listing_tts_engine",
            "session": "session_tts_engine",
            "tf": "tf_tts_engine",
        }
        key = mapping.get(str(kind or "funding").lower(), "funding_tts_engine")
        settings.setValue(key, "system")
        print(f"[Edge TTS] Service blocked; switching {key} to System TTS")

    def _fallback_edge_tts_to_system_tts(
        self, text, voice_id, language="ru", kind="funding"
    ):
        kind_name = str(kind or "funding").lower()
        self._switch_tts_engine_to_system(kind_name)
        print(f"[Edge TTS] Falling back to System TTS ({kind_name})")

        try:
            if kind_name == "session":
                self._session_tts_busy = False
                self._speak_session_system_tts(text, voice_id, language)
                return

            if kind_name == "listing":
                self._listing_edge_tts_busy = False
                self._listing_edge_tts_started = False
                self._listing_tts_busy = False
                self._speak_listing_system_tts(text, voice_id, language)
                return

            self._edge_tts_busy = False
            self._edge_tts_started = False
            self._speak_system_tts(text, voice_id, language)
        except Exception as exc:
            print(f"⚠️ [Edge TTS] Fallback to System TTS failed: {exc}")
            if kind_name == "session":
                self._session_tts_busy = False
            elif kind_name == "listing":
                self._listing_edge_tts_busy = False
                self._listing_edge_tts_started = False
                self._listing_tts_busy = False
            else:
                self._edge_tts_busy = False
                self._edge_tts_started = False

    def _stop_funding_audio(self, tts_only=False):
        self._edge_tts_queue = []
        self._edge_tts_busy = False
        self._edge_tts_started = False
        with self._system_tts_lock:
            self._system_tts_queue.clear()
            self._system_tts_busy = False
        with self._edge_ready_lock:
            self._edge_ready_paths.clear()

        if hasattr(self, "_edge_player"):
            try:
                self._edge_player.stop()
            except Exception:
                pass

        engine = getattr(self, "_active_system_tts_engine", None)
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass

        if not tts_only and hasattr(self, "_funding_player"):
            try:
                self._funding_player.stop()
            except Exception:
                pass

        self._funding_tts_sound_pending = False
        self._funding_tts_batch_active = False
        if hasattr(self, "ui"):
            self._render_funding_exchange_status()

    def _enforce_funding_audio_policy(self):
        if not self.ui.funding_enable_check.isChecked():
            self._stop_funding_audio(tts_only=False)
            self._pending_tts_entries = []
            self._funding_tts_sound_pending = False
            self._funding_tts_batch_active = False
            return

        if not self._is_funding_tts_enabled():
            self._stop_funding_audio(tts_only=True)

    def _entry_tts_key(self, entry):
        identity = self._entry_identity_key(entry)
        return identity + (round(float(entry.get("signed_rate_pct", 0.0) or 0.0), 6),)

    def _enqueue_pending_tts_entry(self, entry):
        if not isinstance(entry, dict):
            return

        snapshot = dict(entry)
        next_time = int(snapshot.get("next_funding_time", 0) or 0)
        rate_abs = abs(float(snapshot.get("signed_rate_pct", 0.0) or 0.0))

        self._pending_tts_seq += 1
        self._pending_tts_entries.append(
            {
                "entry": snapshot,
                "next_time": next_time if next_time > 0 else 10**18,
                "rate_abs": rate_abs,
                "seq": self._pending_tts_seq,
            }
        )

    def _flush_funding_tts_queue(self):
        if not self.ui.funding_enable_check.isChecked():
            self._pending_tts_entries = []
            self._stop_funding_audio(tts_only=False)
            return

        if not self._pending_tts_entries:
            return

        settings = QSettings("MyTradeTools", "TF-Alerter")
        sound_enabled = settings.value("funding_sound_enabled", True, type=bool)
        tts_enabled = settings.value("funding_tts_enabled", True, type=bool)

        if not tts_enabled:
            return

        if not self._funding_tts_batch_active:
            self._funding_tts_batch_active = True
            self._funding_tts_sound_pending = bool(sound_enabled)
        self._render_funding_exchange_status()
        self._start_next_pending_tts()

    def _pick_next_pending_entry(self):
        if not self._pending_tts_entries:
            return None

        best_index = min(
            range(len(self._pending_tts_entries)),
            key=lambda idx: (
                self._pending_tts_entries[idx].get("next_time", 10**18),
                -self._pending_tts_entries[idx].get("rate_abs", 0.0),
                self._pending_tts_entries[idx].get("seq", 0),
            ),
        )
        item = self._pending_tts_entries.pop(best_index)
        return item.get("entry") if isinstance(item, dict) else None

    def _start_next_pending_tts(self):
        if (
            self._funding_paused
            or not self.ui.funding_enable_check.isChecked()
            or not self._is_funding_tts_enabled()
        ):
            return

        if self._edge_tts_busy:
            return
        with self._system_tts_lock:
            system_busy = self._system_tts_busy
            system_queue_has_items = bool(self._system_tts_queue)
        if system_busy and system_queue_has_items:
            return

        entry = self._pick_next_pending_entry()
        if not entry:
            self._funding_tts_sound_pending = False
            self._funding_tts_batch_active = False
            self._render_funding_exchange_status()
            return

        settings = QSettings("MyTradeTools", "TF-Alerter")
        sound_enabled = settings.value("funding_sound_enabled", True, type=bool)
        tts_engine = settings.value("funding_tts_engine", "system")
        tts_voice_id = settings.value("funding_tts_voice_id", "")
        tts_language = settings.value("funding_tts_language", "ru")
        funding_volume = int(settings.value("funding_volume", 80))

        wait_for_sound = False
        if sound_enabled and self._funding_tts_sound_pending:
            try:
                sound_file = settings.value(
                    "funding_sound_file", config.SOUND_FUNDING_ALERT
                )
                sound_file = (
                    str(sound_file or "").strip() or config.SOUND_FUNDING_ALERT
                )
                if sound_file:
                    self._play_funding_sound(sound_file, funding_volume)
                else:
                    self._play_funding_sound(config.SOUND_FUNDING_ALERT, funding_volume)
            except Exception:
                pass
            wait_for_sound = True
            self._funding_tts_sound_pending = False
            self._render_funding_exchange_status()

        time_text_ru, time_text_en = self._format_tts_time_text(entry)

        exchanges_count = 0
        if self.ui.funding_binance_check.isChecked():
            exchanges_count += 1
        if self.ui.funding_bybit_check.isChecked():
            exchanges_count += 1
        if self.ui.funding_okx_check.isChecked():
            exchanges_count += 1
        if self.ui.funding_gate_check.isChecked():
            exchanges_count += 1
        if self.ui.funding_bitget_check.isChecked():
            exchanges_count += 1
        is_multiple_exchanges = exchanges_count > 1

        entry["voice_message_ru"] = self._format_funding_message_ru(
            entry, is_multiple_exchanges, time_text_ru
        )
        entry["voice_message_en"] = self._format_funding_message_en(
            entry, is_multiple_exchanges, time_text_en
        )

        message = (
            entry["voice_message_ru"]
            if tts_language == "ru"
            else entry["voice_message_en"]
        )
        self._speak_tts_async(
            message,
            tts_engine,
            tts_voice_id,
            wait_for_sound,
            language=tts_language,
        )
        self._render_funding_exchange_status()

    def _ru_plural_form(self, value, form_one, form_few, form_many):
        n = abs(int(value))
        if n % 10 == 1 and n % 100 != 11:
            return form_one
        if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return form_few
        return form_many

    def _ru_minutes_word(self, value):
        return self._ru_plural_form(value, "минуту", "минуты", "минут")

    def _ru_seconds_word(self, value):
        return self._ru_plural_form(value, "секунду", "секунды", "секунд")

    def _ru_rate_text(self, rate_value):
        try:
            value = abs(float(rate_value))
        except Exception:
            value = 0.0

        int_part = int(value)
        frac_part = int(round((value - int_part) * 100))
        if frac_part >= 100:
            int_part += 1
            frac_part = 0

        if frac_part == 0:
            return str(int_part)

        if int_part == 1:
            whole_number = "одна"
        elif int_part == 2:
            whole_number = "две"
        else:
            whole_number = str(int_part)

        whole_word = self._ru_plural_form(int_part, "целая", "целых", "целых")
        frac_text = f"{frac_part:02d}"
        return f"{whole_number} {whole_word} {frac_text}"

    def _format_tts_time_text(self, entry):
        import time

        next_time = int(entry.get("next_funding_time", 0) or 0)
        if next_time > 0:
            now_ms = int(time.time() * 1000)
            diff_ms = max(0, next_time - now_ms)

            if diff_ms <= 0:
                return "", ""

            total_seconds = max(1, int((diff_ms + 999) / 1000))

            if diff_ms >= 300000:
                minutes = max(1, int(diff_ms / 60000))
                minute_word_en = "minute" if minutes == 1 else "minutes"
                return (
                    f"{minutes} {self._ru_minutes_word(minutes)}",
                    f"{minutes} {minute_word_en}",
                )

            # Компенсируем сетевую/генерационную задержку TTS, чтобы фраза звучала ближе к реальному остатку.
            adjusted_total_seconds = max(1, total_seconds - 5)
            minutes = int(adjusted_total_seconds / 60)
            seconds = int(adjusted_total_seconds % 60)
            minute_word_en = "minute" if minutes == 1 else "minutes"
            second_word_en = "second" if seconds == 1 else "seconds"
            return (
                f"{minutes} {self._ru_minutes_word(minutes)} {seconds} {self._ru_seconds_word(seconds)}",
                f"{minutes} {minute_word_en} {seconds} {second_word_en}",
            )

        try:
            minutes = int(
                round(float(str(entry.get("minutes_to", "0")).replace(",", ".")))
            )
        except Exception:
            minutes = 0

        if minutes > 0:
            return f"{minutes} {self._ru_minutes_word(minutes)}", f"{minutes} minutes"

        return "", ""

    def _play_funding_sound(self, filename, volume_percent):
        """Plays funding sound with specified volume."""
        from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
        from PyQt6.QtCore import QUrl
        import config

        path = config.get_sound_path("funding", filename)
        if not path or not os.path.exists(path):
            return

        try:
            duration_ms = None
            if path.lower().endswith(".wav"):
                import wave

                with wave.open(path, "rb") as wav_file:
                    frame_rate = wav_file.getframerate()
                    frame_count = wav_file.getnframes()
                    if frame_rate > 0:
                        duration_ms = int((frame_count / frame_rate) * 1000)
            if duration_ms and duration_ms > 0:
                self._last_funding_sound_duration_ms = duration_ms
        except Exception:
            pass

        if not hasattr(self, "_funding_player"):
            self._funding_player = QMediaPlayer()
            self._funding_output = QAudioOutput()
            self._funding_player.setAudioOutput(self._funding_output)

        self._refresh_audio_output_device(getattr(self, "_funding_output", None))

        volume = self._safe_audio_volume_from_percent(volume_percent)
        self._start_player_clean(self._funding_player, self._funding_output, path, volume)

    def _format_funding_message_ru(
        self, entry, is_multiple_exchanges=True, time_text_ru=""
    ):
        """Формирует голосовое сообщение на русском"""
        exchange = str(entry.get("exchange", "")).lower()
        symbol = self._symbol_for_tts(entry["symbol"])
        rate = entry["signed_rate_pct"]

        exchange_ru = self._exchange_name_for_tts(exchange, "ru")
        coin_ru = self._coin_name_for_tts(symbol, "ru")

        # Определяем направление
        if rate > 0:
            direction = "плюс"
        elif rate < 0:
            direction = "минус"
        else:
            direction = "ноль"

        # Формируем сообщение
        rate_str = self._ru_rate_text(rate)

        # Включаем название биржи только если выбрано больше 1 биржи
        if is_multiple_exchanges:
            message = f"{exchange_ru}, {coin_ru}, {direction} {rate_str} процента"
        else:
            message = f"{coin_ru}, {direction} {rate_str} процента"

        if time_text_ru:
            message += f", через {time_text_ru}"

        return message

    def _format_funding_message_en(
        self, entry, is_multiple_exchanges=True, time_text_en=""
    ):
        """Формирует голосовое сообщение на английском"""
        exchange = str(entry.get("exchange", "")).lower()
        symbol = self._symbol_for_tts(entry["symbol"])
        rate = entry["signed_rate_pct"]

        exchange_en = self._exchange_name_for_tts(exchange, "en")
        coin_en = self._coin_name_for_tts(symbol, "en")

        # Определяем направление
        if rate > 0:
            direction = "positive"
        elif rate < 0:
            direction = "negative"
        else:
            direction = "zero"

        # Формируем сообщение
        rate_str = f"{abs(rate):.2f}".replace(".", " point ")

        # Включаем название биржи только если выбрано больше 1 биржи
        if is_multiple_exchanges:
            message = f"{exchange_en}, {coin_en}, {direction} {rate_str} percent"
        else:
            message = f"{coin_en}, {direction} {rate_str} percent"

        if time_text_en:
            message += f", in {time_text_en}"

        return message

    def _symbol_for_tts(self, symbol):
        if not isinstance(symbol, str):
            return ""
        cleaned = self._normalize_symbol_text(symbol)
        for suffix in ("USDT", "USDC", "BUSD", "USD"):
            if cleaned.endswith(suffix) and len(cleaned) > len(suffix):
                return cleaned[: -len(suffix)]
        return cleaned

    def _exchange_name_for_tts(self, exchange, language="ru"):
        key = str(exchange or "").strip().lower()
        if language == "ru":
            names = {
                "binance": "Бинанс",
                "bybit": "Байбит",
                "okx": "О-Кей-Икс",
                "gate": "Гейт",
                "gate.io": "Гейт",
                "bitget": "Битгет",
            }
            return names.get(key, str(exchange or ""))

        names = {
            "binance": "Binance",
            "bybit": "Bybit",
            "okx": "OKX",
            "gate": "Gate",
            "gate.io": "Gate",
            "bitget": "Bitget",
        }
        return names.get(key, str(exchange or ""))

    def _coin_name_for_tts(self, symbol, language="ru"):
        code = self._symbol_for_tts(symbol)
        if not code:
            return ""

        # Только 2-символьные ASCII-тикеры диктуем по буквам (BN -> "B N").
        # Все, что длиннее 2 символов, а также не-ASCII названия (в т.ч. китайские), проговариваем как есть.
        is_ascii_alnum = (
            code.isascii() and code.replace("-", "").replace("_", "").isalnum()
        )
        if is_ascii_alnum and len(code) == 2:
            return " ".join(list(code))
        return code

    def _start_next_edge_tts(self):
        if (
            not self.ui.funding_enable_check.isChecked()
            or not self._is_funding_tts_enabled()
        ):
            self._stop_funding_audio(tts_only=True)
            return

        if self._edge_tts_busy:
            return
        if not self._edge_tts_queue:
            return

        message, voice_id, delay_ms, language = self._edge_tts_queue.pop(0)
        self._edge_tts_busy = True
        self._edge_tts_started = False
        self._edge_tts_last_text = message
        self._edge_tts_last_voice = voice_id
        self._edge_tts_last_language = str(language or "ru")
        QTimer.singleShot(
            max(0, int(delay_ms)),
            lambda msg=message, vid=voice_id, lang=language: self._speak_edge_tts(
                msg, vid, lang
            ),
        )

    def _start_next_system_tts(self):
        if (
            not self.ui.funding_enable_check.isChecked()
            or not self._is_funding_tts_enabled()
        ):
            self._stop_funding_audio(tts_only=True)
            return

        with self._system_tts_lock:
            if self._system_tts_busy:
                return
            if not self._system_tts_queue:
                return
            self._system_tts_busy = True

        def _drain_system_queue():
            import time
            import pyttsx3

            engine = None
            active_voice_id = None

            try:
                engine = pyttsx3.init()
                self._active_system_tts_engine = engine

                while True:
                    with self._system_tts_lock:
                        if not self._system_tts_queue:
                            self._system_tts_busy = False
                            return
                        message, voice_id, delay_ms, language = (
                            self._system_tts_queue.popleft()
                        )

                    try:
                        if delay_ms > 0:
                            time.sleep(delay_ms / 1000.0)

                        resolved_voice = self._resolve_system_tts_voice(
                            engine, voice_id, language
                        )
                        if resolved_voice and resolved_voice != active_voice_id:
                            engine.setProperty("voice", resolved_voice)
                            active_voice_id = resolved_voice

                        settings = QSettings("MyTradeTools", "TF-Alerter")
                        funding_volume = int(settings.value("funding_volume", 80))
                        system_tts_volume = self._safe_audio_volume_from_percent(
                            funding_volume
                        )
                        engine.setProperty("volume", system_tts_volume)

                        engine.say(message)
                        engine.runAndWait()
                        QTimer.singleShot(0, self._start_next_pending_tts)
                    except Exception as e:
                        print(f"⚠️ Ошибка TTS: {e}")
            except Exception as e:
                print(f"⚠️ Ошибка System TTS init: {e}")
                with self._system_tts_lock:
                    self._system_tts_busy = False
            finally:
                try:
                    if engine is not None:
                        engine.stop()
                except Exception:
                    pass
                self._active_system_tts_engine = None

        thread = threading.Thread(
            target=_drain_system_queue,
            daemon=True,
        )
        thread.start()

    def _on_edge_tts_playback_state(self, state):
        from PyQt6.QtMultimedia import QMediaPlayer

        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._edge_tts_started = True
            return

        if (
            state == QMediaPlayer.PlaybackState.StoppedState
            and self._edge_tts_busy
            and self._edge_tts_started
        ):
            self._edge_tts_busy = False
            self._edge_tts_started = False
            QTimer.singleShot(50, self._start_next_pending_tts)

    def _on_edge_tts_media_status(self, status):
        from PyQt6.QtMultimedia import QMediaPlayer

        if status == QMediaPlayer.MediaStatus.InvalidMedia and self._edge_tts_busy:
            self._edge_tts_busy = False
            self._edge_tts_started = False
            QTimer.singleShot(50, self._start_next_pending_tts)

    def _speak_tts_async(
        self, message, engine_type, voice_id, wait_for_sound=False, language="ru"
    ):
        """Асинхронное проигрывание TTS с поддержкой разных движков"""
        import time

        if (
            not self.ui.funding_enable_check.isChecked()
            or not self._is_funding_tts_enabled()
        ):
            return

        delay_ms = 0
        if wait_for_sound:
            sound_duration = int(
                getattr(self, "_last_funding_sound_duration_ms", 1700) or 1700
            )
            delay_ms = max(300, sound_duration + 80)

        if str(engine_type or "system").lower() == "edge" and not self._edge_tts_service_blocked():
            if self._edge_tts_busy or self._edge_tts_queue:
                delay_ms = 0
            self._edge_tts_queue.append(
                (message, voice_id, delay_ms, str(language or "ru"))
            )
            self._start_next_edge_tts()
            return

        with self._system_tts_lock:
            self._system_tts_queue.append(
                (message, voice_id, delay_ms, str(language or "ru"))
            )
        self._start_next_system_tts()

    def _speak_system_tts(self, text, voice_id, language="ru"):
        """Проигрывание через системный TTS (pyttsx3)"""
        try:
            import pyttsx3

            engine = pyttsx3.init()
            self._active_system_tts_engine = engine
            resolved_voice = self._resolve_system_tts_voice(engine, voice_id, language)
            if resolved_voice:
                engine.setProperty("voice", resolved_voice)
            settings = QSettings("MyTradeTools", "TF-Alerter")
            funding_volume = int(settings.value("funding_volume", 80))
            system_tts_volume = self._safe_audio_volume_from_percent(funding_volume)
            engine.setProperty("volume", system_tts_volume)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            print(f"⚠️ Ошибка System TTS: {e}")
        finally:
            self._active_system_tts_engine = None

    def _speak_edge_tts(self, text, voice_name, language="ru"):
        """Проигрывание через Edge TTS (онлайн)"""
        try:
            if (
                not self.ui.funding_enable_check.isChecked()
                or not self._is_funding_tts_enabled()
            ):
                self._edge_tts_busy = False
                self._edge_tts_started = False
                return

            import edge_tts
            import asyncio
            import tempfile

            # Проверяем и устанавливаем voice_name с fallback
            voice_name = self._resolve_edge_tts_voice(voice_name, language)

            def _generate_worker(message_text, current_voice):
                try:

                    async def generate_audio():
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=".mp3"
                        ) as tmp_file:
                            tmp_path = tmp_file.name
                        communicate = edge_tts.Communicate(message_text, current_voice)
                        await communicate.save(tmp_path)
                        return tmp_path

                    tmp_path = asyncio.run(generate_audio())
                    with self._edge_ready_lock:
                        self._edge_ready_paths.append(tmp_path)
                except Exception as e:
                    print(f"⚠️ Edge TTS generation error: {e}")
                    self._fallback_edge_tts_to_system_tts(
                        getattr(self, "_edge_tts_last_text", ""),
                        getattr(self, "_edge_tts_last_voice", ""),
                        getattr(self, "_edge_tts_last_language", "ru"),
                        kind="funding",
                    )

            thread = threading.Thread(
                target=_generate_worker,
                args=(text, voice_name),
                daemon=True,
            )
            thread.start()

        except ImportError:
            print("⚠️ Edge TTS не установлен. Установите: pip install edge-tts")
            self._fallback_edge_tts_to_system_tts(
                text, voice_name, language, kind="funding"
            )
        except Exception as e:
            print(f"⚠️ Ошибка Edge TTS: {e}")
            self._fallback_edge_tts_to_system_tts(
                text, voice_name, language, kind="funding"
            )

    def _drain_edge_ready_paths(self):
        # Check if TTS is disabled
        if (
            not self.ui.funding_enable_check.isChecked()
            or not self._is_funding_tts_enabled()
        ):
            self._stop_funding_audio(tts_only=True)
            return

        # Only process if we're currently playing something
        if not self._edge_tts_busy:
            return

        # Check if any paths are ready
        _no_item = object()
        ready_item = _no_item
        with self._edge_ready_lock:
            if self._edge_ready_paths:
                ready_item = self._edge_ready_paths.popleft()

        if ready_item is _no_item:
            # No items ready yet, wait
            return

        if ready_item is False:
            # Generation failed, fallback to local System TTS instead of failing silently.
            self._fallback_edge_tts_to_system_tts(
                getattr(self, "_edge_tts_last_text", ""),
                getattr(self, "_edge_tts_last_voice", ""),
                getattr(self, "_edge_tts_last_language", "ru"),
                kind="funding",
            )
            return

        if isinstance(ready_item, str):
            # File is ready, play it
            self._play_edge_tts_file(ready_item)

    def _play_edge_tts_file(self, tmp_path):
        from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
        from PyQt6.QtCore import QUrl
        import os

        if (
            not self.ui.funding_enable_check.isChecked()
            or not self._is_funding_tts_enabled()
        ):
            self._edge_tts_busy = False
            self._edge_tts_started = False
            return

        # Verify file exists
        if not os.path.exists(tmp_path):
            print(f"⚠️ Edge TTS file not found: {tmp_path}")
            self._edge_tts_busy = False
            self._edge_tts_started = False
            QTimer.singleShot(50, self._start_next_edge_tts)
            return

        if not hasattr(self, "_edge_player"):
            self._edge_player = QMediaPlayer()
            self._edge_output = QAudioOutput()
            self._edge_player.setAudioOutput(self._edge_output)
            self._edge_player.playbackStateChanged.connect(
                self._on_edge_tts_playback_state
            )
            self._edge_player.mediaStatusChanged.connect(self._on_edge_tts_media_status)

        self._refresh_audio_output_device(getattr(self, "_edge_output", None))

        settings = QSettings("MyTradeTools", "TF-Alerter")
        volume = self._safe_audio_volume_from_percent(
            settings.value("funding_volume", 80, type=int)
        )
        self._start_player_clean(self._edge_player, self._edge_output, tmp_path, volume)

    def _render_funding_log(self):
        import time

        scrollbar = self.ui.funding_log_list.verticalScrollBar()
        prev_max = scrollbar.maximum()
        prev_value = scrollbar.value()
        prev_ratio = (prev_value / prev_max) if prev_max > 0 else 0.0

        self.ui.funding_log_list.clear()
        now_ms = int(time.time() * 1000)

        if self._funding_log_view_mode == "triggered":
            entries = self._get_today_triggered_entries()
            for entry in entries:
                self._add_funding_log_item(entry, now_ms, triggered=True)
            if not entries:
                empty_text = (
                    "No triggered alerts today"
                    if self._is_ui_language_en()
                    else "Сегодня сработавших алертов нет"
                )
                item = QListWidgetItem(empty_text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setForeground(QColor("#666"))
                self.ui.funding_log_list.addItem(item)
            return

        # По умолчанию показываем предстоящие
        ordered_entries = sorted(
            self.funding_alert_entries,
            key=lambda item: (
                (
                    int(item.get("next_funding_time", 0) or 0)
                    if int(item.get("next_funding_time", 0) or 0) > 0
                    else 10**18
                ),
                -abs(float(item.get("signed_rate_pct", 0.0) or 0.0)),
            ),
        )
        shown_count = 0
        for entry in ordered_entries:
            if entry.get("triggered", False):
                continue
            self._add_funding_log_item(entry, now_ms, triggered=False)
            shown_count += 1

        if shown_count == 0:
            empty_text = (
                "No upcoming funding events matching current filters"
                if self._is_ui_language_en()
                else "Пока нет предстоящих фандингов, прошедших текущие фильтры"
            )
            item = QListWidgetItem(empty_text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor("#666"))
            self.ui.funding_log_list.addItem(item)

        new_max = scrollbar.maximum()
        if new_max > 0:
            scrollbar.setValue(int(new_max * prev_ratio))
        else:
            scrollbar.setValue(0)

    def _get_today_triggered_entries(self):
        entries = []
        seen = set()
        enabled_exchanges = {
            "binance": self.ui.funding_binance_check.isChecked(),
            "bybit": self.ui.funding_bybit_check.isChecked(),
            "okx": self.ui.funding_okx_check.isChecked(),
            "gate": self.ui.funding_gate_check.isChecked(),
            "bitget": self.ui.funding_bitget_check.isChecked(),
        }

        def _key(entry):
            next_time = int(entry.get("next_funding_time", 0) or 0)
            return (
                str(entry.get("exchange", "")).strip().lower(),
                self._normalize_symbol_text(entry.get("symbol", "")),
                int(next_time // (10 * 60 * 1000)) if next_time > 0 else -1,
            )

        for entry in list(self.funding_triggered_history):
            exchange_key = str(entry.get("exchange", "")).strip().lower()
            if enabled_exchanges.get(exchange_key, False) is False:
                continue
            if not self._passes_funding_thresholds(entry.get("signed_rate_pct", 0.0)):
                continue
            key = _key(entry)
            if key in seen:
                continue
            seen.add(key)
            entries.append(entry)

        triggered_now = [
            entry
            for entry in self.funding_alert_entries
            if entry.get("triggered", False)
        ]
        for entry in self.triggered_alerts + triggered_now:
            exchange_key = str(entry.get("exchange", "")).strip().lower()
            if enabled_exchanges.get(exchange_key, False) is False:
                continue
            if not self._passes_funding_thresholds(entry.get("signed_rate_pct", 0.0)):
                continue
            key = _key(entry)
            if key in seen:
                continue
            seen.add(key)
            entries.append(entry)

        entries.sort(
            key=lambda item: int(
                item.get("triggered_at", 0)
                or item.get("trigger_time", 0)
                or item.get("next_funding_time", 0)
                or 0
            ),
            reverse=True,
        )
        return entries

    def set_funding_log_view_mode(self, mode):
        if mode not in ("upcoming", "triggered"):
            mode = "upcoming"
        self._funding_log_view_mode = mode

        self.ui.funding_log_upcoming_btn.blockSignals(True)
        self.ui.funding_log_triggered_btn.blockSignals(True)
        self.ui.funding_log_upcoming_btn.setChecked(mode == "upcoming")
        self.ui.funding_log_triggered_btn.setChecked(mode == "triggered")
        self.ui.funding_log_upcoming_btn.blockSignals(False)
        self.ui.funding_log_triggered_btn.blockSignals(False)

        self._render_funding_log()

    def _add_funding_log_item(self, entry, now_ms, triggered=False):
        """Добавляет элемент в лог фандинга"""
        exchange = entry.get("exchange", "")
        symbol = entry.get("symbol", "")
        rate = entry.get("signed_rate_pct", 0.0)
        next_funding_time = entry.get("next_funding_time", 0)
        is_en = self._is_ui_language_en()

        # Вычисляем время до фандинга
        if next_funding_time:
            time_diff_ms = next_funding_time - now_ms
            if time_diff_ms > 60000:  # > 1 минуты
                minutes = max(0, int(time_diff_ms / 60000))
                time_str = f"{minutes} {'min' if is_en else 'мин'}"
            elif time_diff_ms > 0:  # < 1 минуты, показываем секунды
                seconds = max(0, int(time_diff_ms / 1000))
                time_str = f"{seconds} {'sec' if is_en else 'сек'}"
            else:
                time_str = "completed" if is_en else "завершён"

            # Конвертируем next_funding_time в локальное время
            funding_dt = datetime.datetime.fromtimestamp(next_funding_time / 1000)
            funding_time_str = funding_dt.strftime("%H:%M:%S")
        else:
            try:
                fallback_minutes = int(
                    round(float(str(entry.get("minutes_to", "0")).replace(",", ".")))
                )
            except Exception:
                fallback_minutes = 0
            time_str = (
                f"{fallback_minutes} {'min' if is_en else 'мин'}"
                if fallback_minutes > 0
                else ("no data" if is_en else "нет данных")
            )
            funding_time_str = "—"

        # Текст: СИМВОЛ биржа — funding X% — до фандинга Y мин/сек — фандинг в HH:MM:SS
        text = (
            f"{symbol}  {exchange} — funding {rate:.2f}% — "
            f"{'until funding' if is_en else 'до фандинга'} {time_str} — "
            f"{'funding at' if is_en else 'фандинг в'} {funding_time_str}"
        )

        if triggered:
            triggered_ms = int(
                entry.get("triggered_at", 0)
                or entry.get("trigger_time", 0)
                or entry.get("next_funding_time", 0)
                or 0
            )
            if triggered_ms > 0:
                triggered_dt = datetime.datetime.fromtimestamp(triggered_ms / 1000.0)
                date_str = triggered_dt.strftime("%d.%m.%Y")
                text = f"{text} — {date_str}"

        item = QListWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft)
        item.setData(Qt.ItemDataRole.UserRole, entry)

        font = item.font()
        font.setPointSize(9)

        # Если алерт сработал - только делаем темнее (без зачёркивания)
        if triggered:
            item.setFont(font)
            item.setForeground(QColor(100, 100, 100))  # Темно-серый
        else:
            item.setFont(font)
            # Цвет по времени
            if next_funding_time:
                time_diff_ms = next_funding_time - now_ms
                minutes_to = max(0, int(time_diff_ms / 60000))
                if minutes_to <= 5 or (time_diff_ms > 0 and time_diff_ms <= 60000):
                    item.setForeground(QColor(config.COLORS["danger"]))
                elif minutes_to <= 15:
                    item.setForeground(QColor(config.COLORS["accent"]))
                else:
                    item.setForeground(QColor(config.COLORS["text"]))
            else:
                item.setForeground(QColor(config.COLORS["text"]))

        self.ui.funding_log_list.addItem(item)

    def copy_funding_symbol(self, item):
        if not item:
            return

        # Получаем позицию клика относительно элемента
        cursor_pos = self.ui.funding_log_list.mapFromGlobal(QCursor.pos())
        item_rect = self.ui.funding_log_list.visualItemRect(item)

        entry = item.data(Qt.ItemDataRole.UserRole) or {}
        symbol = entry.get("symbol", "")
        if not symbol:
            return

        # Копируем только если клик в первых ~100 пикселях (примерная ширина символа)
        relative_x = cursor_pos.x() - item_rect.x()
        if relative_x <= 100:  # Только если клик на начале строки (на символе)
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(symbol)
            QToolTip.showText(QCursor.pos(), f"Скопировано: {symbol}")
            QTimer.singleShot(2000, QToolTip.hideText)

    def toggle_overlay_move_lock(self, state):
        self.overlay_move_locked = bool(state)
        self.logic.overlay.move_locked = self.overlay_move_locked

    def on_overlay_font_changed(self, font_name, save=True):
        selected_family = (font_name or "").strip() or "Arial"
        self.current_overlay_font = selected_family
        if hasattr(self.ui, "clock_font_btn"):
            self.ui.clock_font_btn.setText(selected_family)
        self.apply_overlay_visual()
        if save:
            self.save_settings()

    def open_font_dialog(self):
        current_family = (self.current_overlay_font or "").strip() or "Arial"
        original_family = current_family
        self._font_dialog_open = True
        prev_selecting_color = bool(getattr(self.logic, "is_selecting_color", False))
        self.logic.is_selecting_color = True
        if self.ui.cb_overlay.isChecked() and not self.logic.overlay.isVisible():
            self.logic.overlay.show()
        dialog = FontPickerDialog(
            self,
            current_family,
            preview_callback=lambda family: self.on_overlay_font_changed(
                family, save=False
            ),
        )
        try:
            if dialog.exec():
                selected_family = dialog.get_selected_font_family()
                if selected_family:
                    self.on_overlay_font_changed(selected_family, save=True)
            else:
                self.on_overlay_font_changed(original_family, save=False)
        finally:
            self.logic.is_selecting_color = prev_selecting_color
            self._font_dialog_open = False

    def changeEvent(self, event):
        """Перехватываем изменения состояния окна"""
        if event.type() == QEvent.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized:
                if getattr(self, "_font_dialog_open", False):
                    self.setWindowState(Qt.WindowState.WindowNoState)
                    self.showNormal()
                    return
                if not self._allow_minimize and not self._is_closing:
                    QTimer.singleShot(0, self.toggle_minimize)
            else:
                self._allow_minimize = False
        super().changeEvent(event)

    def hideEvent(self, event):
        """Окно скрывается"""
        super().hideEvent(event)

    def closeEvent(self, event):
        log_write("\n[CLOSE] closeEvent вызван!")
        try:
            self._is_closing = True
            self.save_settings()

            # Дополнительно флешим все значения при закрытии
            settings = QSettings("MyTradeTools", "TF-Alerter")
            settings.sync()
            log_write("[CLOSE] Финальный sync() при закрытии приложения")

            # Останавливаем менеджер горячих клавиш
            if hasattr(self, "hotkey_manager"):
                self.hotkey_manager.stop()

            if hasattr(self, "logic"):
                self.logic.timer.stop()
                self.logic.overlay_update_timer.stop()  # Останавливаем таймер обновления часов
                self.logic.overlay.close()
            event.accept()
        except Exception as e:
            log_write(f"Ошибка при закрытии: {e}")
            event.accept()

    def change_color(self):
        self.logic.is_selecting_color = True
        current_hex = config.COLORS.get("accent", "#007acc")
        settings = QSettings("MyTradeTools", "TF-Alerter")
        current_alpha = int(settings.value("accent_alpha", 255))

        dialog = ColorPickerDialog(
            self,
            current_hex,
            current_alpha,
            self.overlay_bg_enabled,
            self.overlay_bg_color,
        )
        # При открытии диалога сразу применяются все изменения благодаря live preview
        if dialog.exec():
            # Пользователь нажал OK - сохраняем значения в конфиг и настройки
            new_hex = dialog.get_color()
            new_alpha = dialog.get_alpha()
            self.overlay_bg_enabled = dialog.get_bg_enabled()
            self.overlay_bg_color = dialog.get_bg_color()
            config.COLORS["accent"] = new_hex
            config.COLORS["accent_alpha"] = new_alpha
            self.save_settings()
        else:
            # Пользователь нажал Cancel или закрыл диалог
            # Значения уже восстановлены в dialog.reject()
            pass
        self.logic.is_selecting_color = False


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Установка иконки приложения для панели задач и Alt+Tab
    app.setWindowIcon(QIcon(config.LOGO_PATH))

    _APP_INSTANCE_LOCK = _acquire_instance_lock()
    if _APP_INSTANCE_LOCK is None:
        settings = QSettings("MyTradeTools", "TF-Alerter")
        lang = str(settings.value("language", "RU")).upper()
        title = "TF-Alerter"
        text = (
            "Программа уже запущена. Второй экземпляр заблокирован."
            if lang == "RU"
            else "Application is already running. Second instance is blocked."
        )
        QMessageBox.information(None, title, text)
        sys.exit(0)

    if not config.validate_crypto_addresses_integrity():
        settings = QSettings("MyTradeTools", "TF-Alerter")
        lang = str(settings.value("language", "RU")).upper()
        title = "TF-Alerter"
        text = (
            "Обнаружено изменение донат-адресов. Приложение будет закрыто."
            if lang == "RU"
            else "Donation address tampering detected. The app will close."
        )
        QMessageBox.critical(None, title, text)
        sys.exit(1)

    app._instance_lock = _APP_INSTANCE_LOCK

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
