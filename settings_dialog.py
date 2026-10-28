from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QFrame,
    QLineEdit,
    QGridLayout,
    QFileDialog,
    QSizePolicy,
    QWidget,
    QScrollArea,
    QCheckBox,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QSettings, QEvent, QUrl, QRect, QTimer
from PyQt6.QtGui import QKeySequence, QKeyEvent, QColor, QPainter, QPen
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
import os
import shutil
import datetime
import config
import ctypes
from ctypes import wintypes


class NoWheelComboBox(QComboBox):
    """QComboBox, который игнорирует прокрутку мышью (wheel event)"""

    def wheelEvent(self, event):
        event.ignore()


class SoundColumnCheckBox(QCheckBox):
    """Кастомный чекбокс для управления колонками звуков - стиль как на главном окне"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)

    def paintEvent(self, event):
        """Рисуем галочку как на главном окне для таймфреймов"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        indicator_rect_x = 2
        indicator_rect_y = 2
        indicator_rect = QRect(indicator_rect_x, indicator_rect_y, 16, 16)

        if self.isChecked():
            # Синий квадрат с белой галочкой
            painter.fillRect(indicator_rect, QColor("#1e90ff"))
            painter.setPen(QPen(QColor("#1e90ff"), 2))
            painter.drawRect(indicator_rect)

            # Рисуем галочку
            pen = QPen(QColor("black"), 2, Qt.PenStyle.SolidLine)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)

            x = indicator_rect_x
            y = indicator_rect_y
            painter.drawLine(int(x + 3), int(y + 9), int(x + 7), int(y + 13))
            painter.drawLine(int(x + 7), int(y + 13), int(x + 13), int(y + 5))
        else:
            # Пустой квадрат
            painter.setPen(QPen(QColor("#555"), 2))
            painter.drawRect(indicator_rect)

        painter.end()


class FundingToggleCheckBox(QCheckBox):
    """Кастомный чекбокс с текстом в стиле главного окна."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        indicator_rect_x = 2
        indicator_rect_y = (self.height() - 16) // 2
        indicator_rect = QRect(indicator_rect_x, indicator_rect_y, 16, 16)

        if self.isChecked():
            painter.fillRect(indicator_rect, QColor("#1e90ff"))
            painter.setPen(QPen(QColor("#1e90ff"), 2))
            painter.drawRect(indicator_rect)

            pen = QPen(QColor("black"), 2, Qt.PenStyle.SolidLine)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)

            x = indicator_rect_x
            y = indicator_rect_y
            painter.drawLine(int(x + 3), int(y + 9), int(x + 7), int(y + 13))
            painter.drawLine(int(x + 7), int(y + 13), int(x + 13), int(y + 5))
        else:
            painter.setPen(QPen(QColor("#555"), 2))
            painter.drawRect(indicator_rect)

        text_color = QColor("#bbb") if self.isEnabled() else QColor("#666")
        painter.setPen(text_color)
        text_rect = QRect(25, 0, self.width() - 30, self.height())
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.text(),
        )
        painter.end()


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Настройки")

        # Нужно для надёжного получения keyPress/keyRelease во время захвата
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Устанавливаем ширину шире родительского окна для блока звуков
        parent_width = parent.width() if parent else 380
        scale_text = QSettings("MyTradeTools", "TF-Alerter").value(
            "interface_scale_text", "100%"
        )
        try:
            value = int(str(scale_text).replace("%", ""))
            factor = value / 100.0
        except Exception:
            factor = 1.0

        # Сохраняем масштаб как переменная класса для использования в других методах
        self.scale_factor = factor

        def s(px):
            return max(1, int(px * factor))

        dialog_width = max(parent_width + s(140), s(700))
        self.setFixedSize(dialog_width, s(560))

        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.capturing_hotkey = False
        self.captured_hotkey_codes = None
        self._pressed_vks = set()
        self._pressed_names = {}
        self._saw_non_modifier = False
        self._last_modifiers_vks = set()
        self.funding_sound_file = ""
        self.listing_sound_file = ""
        self._session_tts_preview_cache = {}
        self._session_tts_preview_cache_order = []

        self._user32 = ctypes.windll.user32
        self._MAPVK_VK_TO_VSC_EX = 4
        self._VK_MODIFIERS = {
            0x10,  # VK_SHIFT
            0x11,  # VK_CONTROL
            0x12,  # VK_MENU (Alt)
            0x5B,  # VK_LWIN
            0x5C,  # VK_RWIN
            0xA0,  # VK_LSHIFT
            0xA1,  # VK_RSHIFT
            0xA2,  # VK_LCONTROL
            0xA3,  # VK_RCONTROL
            0xA4,  # VK_LMENU
            0xA5,  # VK_RMENU
        }

        self._VK_DISPLAY = {
            0xA2: "Left Ctrl",
            0xA3: "Right Ctrl",
            0x11: "Ctrl",
            0xA4: "Left Alt",
            0xA5: "Right Alt",
            0x12: "Alt",
            0xA0: "Left Shift",
            0xA1: "Right Shift",
            0x10: "Shift",
            0x5B: "Left Windows",
            0x5C: "Right Windows",
        }

        # Словари переводов
        self.translations = {
            "RU": {
                "title": "Настройки",
                "language": "Язык:",
                "scale": "Масштаб:",
                "hotkey": "Горячая клавиша (свернуть/развернуть):",
                "clear": "Очистить",
                "cancel": "Отмена",
                "save": "Сохранить",
                "not_set": "Не задана",
                "capturing": "Нажмите клавишу...",
                "sounds_title": "Звуки таймфреймов",
                "tf_col": "ТФ",
                "voice_col": "Основной",
                "tick_col": "Тики 5с",
                "transition_col": "Переход",
                "enable_voice": "Включить",
                "enable_tick": "Включить",
                "enable_transition": "Включить",
                "about_btn": "ℹ️ О программе",
                "donate_btn": "♥️ Поддержать",
                "funding_title": "Фандинг: звук и голос",
                "funding_sound_enabled": "Включить звук фандинга",
                "funding_tts_enabled": "Включить TTS озвучку",
                "funding_sound_file": "Звук фандинга:",
                "funding_sound_pick": "Выбрать звук",
                "funding_tts_engine": "TTS движок:",
                "funding_tts_language": "Язык голоса:",
                "funding_tts_voice": "Голос:",
                "funding_tts_engine_system": "System TTS (Windows)",
                "funding_tts_engine_edge": "Edge TTS (онлайн, лучшее качество)",
                "funding_tts_lang_ru": "Русский",
                "funding_tts_lang_en": "English",
                "listing_title": "Листинг: звук и голос",
                "listing_sound_enabled": "Включить звук листинга",
                "listing_tts_enabled": "Включить TTS озвучку",
                "listing_sound_file": "Звук листинга:",
                "listing_sound_pick": "Выбрать звук",
                "listing_tts_engine": "TTS движок:",
                "listing_tts_language": "Язык голоса:",
                "listing_tts_voice": "Голос:",
                "listing_tts_engine_system": "System TTS (Windows)",
                "listing_tts_engine_edge": "Edge TTS (онлайн, лучшее качество)",
                "listing_tts_lang_ru": "Русский",
                "listing_tts_lang_en": "English",
                "session_title": "Сессии: голос",
                "session_tts_enabled": "Включить TTS озвучку",
                "session_tts_engine": "TTS движок:",
                "session_tts_language": "Язык голоса:",
                "session_tts_voice": "Голос:",
                "session_tts_engine_system": "System TTS (Windows)",
                "session_tts_engine_edge": "Edge TTS (онлайн, лучшее качество)",
                "session_tts_lang_ru": "Русский",
                "session_tts_lang_en": "English",
                "tf_tts_title": "TTS озвучка таймфреймов",
                "tf_tts_enabled": "Включить TTS для таймфреймов",
                "tf_tts_engine": "TTS движок:",
                "tf_tts_language": "Язык голоса:",
                "tf_tts_voice": "Голос:",
            },
            "EN": {
                "title": "Settings",
                "language": "Language:",
                "scale": "Scale:",
                "hotkey": "Hotkey (minimize/restore):",
                "clear": "Clear",
                "cancel": "Cancel",
                "save": "Save",
                "not_set": "Not set",
                "capturing": "Press a key...",
                "sounds_title": "Timeframe Sounds",
                "tf_col": "TF",
                "voice_col": "Voice",
                "tick_col": "Ticks 5s",
                "transition_col": "Transition",
                "enable_voice": "Enable",
                "enable_tick": "Enable",
                "enable_transition": "Enable",
                "about_btn": "ℹ️ Info",
                "donate_btn": "♥️ Support",
                "funding_title": "Funding: sound and voice",
                "funding_sound_enabled": "Enable funding sound",
                "funding_tts_enabled": "Enable TTS voice",
                "funding_sound_file": "Funding sound:",
                "funding_sound_pick": "Pick sound",
                "funding_tts_engine": "TTS Engine:",
                "funding_tts_language": "Voice Language:",
                "funding_tts_voice": "Voice:",
                "funding_tts_engine_system": "System TTS (Windows)",
                "funding_tts_engine_edge": "Edge TTS (online, better quality)",
                "funding_tts_lang_ru": "Russian",
                "funding_tts_lang_en": "English",
                "listing_title": "Listing: sound and voice",
                "listing_sound_enabled": "Enable listing sound",
                "listing_tts_enabled": "Enable TTS voice",
                "listing_sound_file": "Listing sound:",
                "listing_sound_pick": "Pick sound",
                "listing_tts_engine": "TTS Engine:",
                "listing_tts_language": "Voice Language:",
                "listing_tts_voice": "Voice:",
                "listing_tts_engine_system": "System TTS (Windows)",
                "listing_tts_engine_edge": "Edge TTS (online, better quality)",
                "listing_tts_lang_ru": "Russian",
                "listing_tts_lang_en": "English",
                "session_title": "Sessions: voice",
                "session_tts_enabled": "Enable TTS voice",
                "session_tts_engine": "TTS Engine:",
                "session_tts_language": "Voice Language:",
                "session_tts_voice": "Voice:",
                "session_tts_engine_system": "System TTS (Windows)",
                "session_tts_engine_edge": "Edge TTS (online, better quality)",
                "session_tts_lang_ru": "Russian",
                "session_tts_lang_en": "English",
                "tf_tts_title": "TTS voice for timeframes",
                "tf_tts_enabled": "Enable TTS for timeframes",
                "tf_tts_engine": "TTS Engine:",
                "tf_tts_language": "Voice Language:",
                "tf_tts_voice": "Voice:",
            },
        }

        # Главный контейнер
        main_container = QFrame(self)
        main_container.setStyleSheet(
            f"""
            QFrame {{
                background-color: {config.COLORS['background']};
                border: 1px solid {config.COLORS['border']};
                border-radius: 10px;
            }}
        """
        )
        main_container.setGeometry(0, 0, dialog_width, s(560))

        # Фиксированный header (не скроллится)
        header_frame = QWidget(main_container)
        header_frame.setGeometry(0, 0, dialog_width, s(50))
        header_frame.setStyleSheet("background: transparent;")

        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(s(20), s(12), s(20), s(8))
        header_layout.setSpacing(0)

        self.title = QLabel("Настройки")
        self.title.setStyleSheet(
            f"""
            color: {config.COLORS['text']};
            font-size: {s(14)}px;
            font-weight: bold;
            border: none;
            background: transparent;
        """
        )
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.title)
        header_layout.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(s(28), s(28))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                color: {config.COLORS['text']};
                border: none;
                font-size: {s(16)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: transparent;
                color: #1e90ff;
            }}
        """
        )
        header_layout.addWidget(close_btn)

        # Create a scroll area for the settings content (starts below header)
        main_scroll = QScrollArea(main_container)
        main_scroll.setWidgetResizable(True)
        main_scroll.setFrameShape(QFrame.Shape.NoFrame)
        main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        main_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: #111; width: 12px; margin: 2px; border: 1px solid #222; border-radius: 6px; }"
            "QScrollBar:vertical:hover { width: 16px; margin: 1px; border: 1px solid #2a2a2a; }"
            "QScrollBar::handle:vertical { background: #3a3a3a; min-height: 28px; border-radius: 5px; }"
            "QScrollBar::handle:vertical:hover { background: #4a4a4a; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { background: #1a1a1a; height: 12px; border: none; }"
            "QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical { background: transparent; border: none; width: 0px; height: 0px; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: #111; }"
        )
        main_scroll.viewport().setStyleSheet(
            f"background-color: {config.COLORS['background']}; border: none;"
        )
        footer_height = s(52)
        main_scroll.setGeometry(
            s(6),
            s(50),
            dialog_width - s(12),
            s(560) - s(50) - footer_height,
        )

        footer_frame = QWidget(main_container)
        footer_frame.setGeometry(0, s(560) - footer_height, dialog_width, footer_height)
        footer_frame.setStyleSheet("background: transparent;")
        self.footer_layout = QHBoxLayout(footer_frame)
        self.footer_layout.setContentsMargins(s(20), s(6), s(20), s(10))
        self.footer_layout.setSpacing(5)

        scroll_content = QWidget()
        scroll_content.setObjectName("settingsScrollContent")
        scroll_content.setStyleSheet(
            f"#settingsScrollContent {{ background-color: {config.COLORS['background']}; border: none; }}"
        )
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(s(20), s(4), s(20), s(15))
        layout.setSpacing(s(12))
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Кнопки для информации и донатов
        info_layout = QHBoxLayout()
        self.about_btn = QPushButton(self.translations["RU"]["about_btn"])
        self.about_btn.setMinimumWidth(s(170))
        self.about_btn.setMaximumWidth(s(190))
        self.about_btn.clicked.connect(self._open_about)
        self.about_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {config.COLORS['panel']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: {s(5)}px;
                padding: {s(8)}px {s(20)}px;
                font-size: {s(11)}px;
            }}
            QPushButton:hover {{
                background-color: {config.COLORS['hover']};
                border: 1px solid #1e90ff;
            }}
        """
        )

        self.donate_btn = QPushButton(self.translations["RU"]["donate_btn"])
        self.donate_btn.setMinimumWidth(s(170))
        self.donate_btn.setMaximumWidth(s(190))
        self.donate_btn.clicked.connect(self._open_donate)
        self.donate_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {config.COLORS['panel']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: {s(5)}px;
                padding: {s(8)}px {s(20)}px;
                font-size: {s(11)}px;
            }}
            QPushButton:hover {{
                background-color: {config.COLORS['hover']};
                border: 1px solid #1e90ff;
            }}
        """
        )

        info_layout.addStretch()
        info_layout.addWidget(self.about_btn)
        info_layout.addSpacing(5)
        info_layout.addWidget(self.donate_btn)
        info_layout.addStretch()
        layout.addLayout(info_layout)

        # Язык
        lang_layout = QHBoxLayout()
        lang_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lang_label = QLabel("Язык:")
        self.lang_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(12)}px; border: none; background: transparent;"
        )
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["RU", "EN"])
        self.lang_combo.setStyleSheet(self._combo_style())
        if self.lang_combo.lineEdit():
            self.lang_combo.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lang_combo.currentTextChanged.connect(self.change_dialog_language)
        lang_layout.addWidget(self.lang_label)
        lang_layout.addSpacing(10)
        lang_layout.addWidget(self.lang_combo)
        layout.addLayout(lang_layout)

        # Масштаб интерфейса
        scale_layout = QHBoxLayout()
        scale_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scale_label = QLabel("Масштаб:")
        self.scale_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(12)}px; border: none; background: transparent;"
        )
        self.scale_combo = QComboBox()
        self.scale_combo.addItems(
            ["90%", "100%", "110%", "120%", "130%", "140%", "150%"]
        )
        self.scale_combo.setStyleSheet(self._combo_style())
        if self.scale_combo.lineEdit():
            self.scale_combo.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)
        scale_layout.addWidget(self.scale_label)
        scale_layout.addSpacing(10)
        scale_layout.addWidget(self.scale_combo)
        layout.addLayout(scale_layout)

        # Горячая клавиша
        self.hotkey_label = QLabel("Горячая клавиша (свернуть/развернуть):")
        self.hotkey_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(12)}px; border: none; background: transparent;"
        )
        self.hotkey_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hotkey_label)

        hotkey_input_layout = QHBoxLayout()
        hotkey_input_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hotkey_input = QPushButton("Не задана")
        # Чтобы фокус не оставался на кнопке и не "съедал" события клавиатуры
        self.hotkey_input.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hotkey_input.setFixedHeight(s(32))
        self.hotkey_input.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hotkey_input.clicked.connect(self.start_capture)
        self.hotkey_input.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {config.COLORS['panel']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: {s(5)}px;
                padding: {s(8)}px;
                font-size: {s(11)}px;
                text-align: left;
            }}
            QPushButton:hover {{
                border: 1px solid #1e90ff;
            }}
        """
        )

        self.clear_hotkey_btn = QPushButton("Очистить")
        self.clear_hotkey_btn.setFixedHeight(s(32))
        self.clear_hotkey_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_hotkey_btn.clicked.connect(self.clear_hotkey)
        self.clear_hotkey_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {config.COLORS['panel']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: {s(5)}px;
                padding: {s(5)}px {s(12)}px;
                font-size: {s(11)}px;
            }}
            QPushButton:hover {{
                border: 1px solid #1e90ff;
            }}
        """
        )

        hotkey_input_layout.addWidget(self.hotkey_input)
        hotkey_input_layout.addWidget(self.clear_hotkey_btn)
        layout.addLayout(hotkey_input_layout)

        # Настройки фандинга (звук и голос)
        layout.addSpacing(s(8))

        self.funding_title = QLabel(self.translations["RU"]["funding_title"])
        self.funding_title.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(14)}px; font-weight: bold; border: none; background: transparent;"
        )
        self.funding_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.funding_title)

        funding_frame = QFrame()
        funding_frame.setStyleSheet(
            f"QFrame {{ background-color: {config.COLORS['panel']}; border: 1px solid {config.COLORS['border']}; border-radius: {s(6)}px; }}"
        )
        funding_layout = QVBoxLayout(funding_frame)
        funding_layout.setContentsMargins(s(10), s(8), s(10), s(8))
        funding_layout.setSpacing(s(6))

        funding_check_row = QHBoxLayout()
        self.funding_sound_check = FundingToggleCheckBox(
            self.translations["RU"]["funding_sound_enabled"]
        )
        self.funding_tts_check = FundingToggleCheckBox(
            self.translations["RU"]["funding_tts_enabled"]
        )
        self.funding_sound_check.setMinimumHeight(s(22))
        self.funding_tts_check.setMinimumHeight(s(22))
        # Set minimum width to prevent text truncation
        self.funding_tts_check.setMinimumWidth(s(180))
        for cb in (self.funding_sound_check, self.funding_tts_check):
            cb.setStyleSheet(
                f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
            )
        funding_check_row.addWidget(self.funding_sound_check, 1)
        funding_check_row.addStretch(1)
        funding_check_row.addWidget(
            self.funding_tts_check, 0, Qt.AlignmentFlag.AlignRight
        )
        funding_layout.addLayout(funding_check_row)

        sound_row = QHBoxLayout()
        self.funding_sound_label_static = QLabel(
            self.translations["RU"]["funding_sound_file"]
        )
        self.funding_sound_label_static.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        self.funding_sound_btn = QPushButton("funding_alert.wav")
        self.funding_sound_btn.setFixedHeight(s(30))
        self.funding_sound_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.funding_sound_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {config.COLORS['background']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: {s(5)}px;
                padding: {s(4)}px {s(10)}px;
                font-size: {s(10)}px;
            }}
            QPushButton:hover {{
                border: 1px solid #1e90ff;
            }}
            """
        )
        self.funding_sound_play_btn = QPushButton("▶")
        self.funding_sound_play_btn.setFixedSize(s(28), s(30))
        self.funding_sound_play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.funding_sound_play_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {config.COLORS['background']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: {s(5)}px;
                font-size: {s(11)}px;
            }}
            QPushButton:hover {{
                border: 1px solid #1e90ff;
            }}
            """
        )
        self.funding_sound_btn.setMaximumWidth(s(200))
        self.funding_sound_btn.clicked.connect(self._select_funding_sound)
        self.funding_sound_play_btn.clicked.connect(self._play_funding_sound)
        sound_row.addWidget(self.funding_sound_label_static)
        sound_row.addWidget(self.funding_sound_btn)
        sound_row.addWidget(self.funding_sound_play_btn)
        sound_row.addStretch()
        funding_layout.addLayout(sound_row)

        # TTS Движ Engine выбор
        engine_row = QHBoxLayout()
        self.funding_tts_engine_label = QLabel(
            self.translations["RU"]["funding_tts_engine"]
        )
        self.funding_tts_engine_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        self.funding_tts_engine_combo = NoWheelComboBox()
        self.funding_tts_engine_combo.addItem("System TTS (Windows)", "system")
        self.funding_tts_engine_combo.addItem(
            "Edge TTS (онлайн, лучшее качество)", "edge"
        )
        self.funding_tts_engine_combo.setStyleSheet(self._combo_style())
        self.funding_tts_engine_combo.currentIndexChanged.connect(
            self._on_tts_engine_changed
        )
        engine_row.addWidget(self.funding_tts_engine_label)
        engine_row.addWidget(self.funding_tts_engine_combo, 1)
        funding_layout.addLayout(engine_row)

        # TTS Язык выбор
        lang_row = QHBoxLayout()
        self.funding_tts_language_label = QLabel(
            self.translations["RU"]["funding_tts_language"]
        )
        self.funding_tts_language_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        self.funding_tts_language_combo = NoWheelComboBox()
        self.funding_tts_language_combo.addItem("Русский", "ru")
        self.funding_tts_language_combo.addItem("English", "en")
        self.funding_tts_language_combo.setStyleSheet(self._combo_style())
        self.funding_tts_language_combo.currentIndexChanged.connect(
            self._on_tts_language_changed
        )
        lang_row.addWidget(self.funding_tts_language_label)
        lang_row.addWidget(self.funding_tts_language_combo, 1)
        funding_layout.addLayout(lang_row)

        # TTS Голос выбор
        voice_row = QHBoxLayout()
        self.funding_tts_voice_label = QLabel(
            self.translations["RU"]["funding_tts_voice"]
        )
        self.funding_tts_voice_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        self.funding_tts_voice_combo = NoWheelComboBox()
        self.funding_tts_voice_combo.setStyleSheet(self._combo_style())
        self.funding_tts_voice_combo.currentIndexChanged.connect(
            self._on_tts_voice_changed
        )
        if self.funding_tts_voice_combo.lineEdit():
            self.funding_tts_voice_combo.lineEdit().setAlignment(
                Qt.AlignmentFlag.AlignCenter
            )
        self.funding_tts_play_btn = QPushButton("▶")
        self.funding_tts_play_btn.setFixedSize(s(28), s(30))
        self.funding_tts_play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.funding_tts_play_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {config.COLORS['background']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: {s(5)}px;
                font-size: {s(11)}px;
            }}
            QPushButton:hover {{
                border: 1px solid #1e90ff;
            }}
            """
        )
        self.funding_tts_play_btn.clicked.connect(self._play_funding_tts)
        voice_row.addWidget(self.funding_tts_voice_label)
        voice_row.addWidget(self.funding_tts_voice_combo, 1)
        voice_row.addWidget(self.funding_tts_play_btn)
        funding_layout.addLayout(voice_row)

        funding_container = QWidget()
        funding_container_layout = QVBoxLayout(funding_container)
        funding_container_layout.setContentsMargins(s(8), 0, s(8), 0)
        funding_container_layout.setSpacing(0)
        funding_container_layout.addWidget(funding_frame)
        layout.addWidget(funding_container)

        layout.addSpacing(s(15))

        # Separator line
        separator1 = QFrame()
        separator1.setFrameShape(QFrame.Shape.HLine)
        separator1.setFrameShadow(QFrame.Shadow.Sunken)
        separator1.setStyleSheet(f"color: {config.COLORS['border']};")
        layout.addWidget(separator1)

        layout.addSpacing(s(15))

        # Настройки листинга (звук и голос)
        self.listing_title = QLabel(self.translations["RU"]["listing_title"])
        self.listing_title.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(14)}px; font-weight: bold; border: none; background: transparent;"
        )
        self.listing_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.listing_title)

        listing_frame = QFrame()
        listing_frame.setStyleSheet(
            f"QFrame {{ background-color: {config.COLORS['panel']}; border: 1px solid {config.COLORS['border']}; border-radius: {s(6)}px; }}"
        )
        listing_layout = QVBoxLayout(listing_frame)
        listing_layout.setContentsMargins(s(10), s(8), s(10), s(8))
        listing_layout.setSpacing(s(6))

        listing_check_row = QHBoxLayout()
        self.listing_sound_check = FundingToggleCheckBox(
            self.translations["RU"]["listing_sound_enabled"]
        )
        self.listing_tts_check = FundingToggleCheckBox(
            self.translations["RU"]["listing_tts_enabled"]
        )
        self.listing_sound_check.setMinimumHeight(s(22))
        self.listing_tts_check.setMinimumHeight(s(22))
        # Set minimum width to prevent text truncation
        self.listing_tts_check.setMinimumWidth(s(180))
        for cb in (self.listing_sound_check, self.listing_tts_check):
            cb.setStyleSheet(
                f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
            )
        listing_check_row.addWidget(self.listing_sound_check, 1)
        listing_check_row.addStretch(1)
        listing_check_row.addWidget(
            self.listing_tts_check, 0, Qt.AlignmentFlag.AlignRight
        )
        listing_layout.addLayout(listing_check_row)

        listing_sound_row = QHBoxLayout()
        self.listing_sound_label_static = QLabel(
            self.translations["RU"]["listing_sound_file"]
        )
        self.listing_sound_label_static.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        self.listing_sound_btn = QPushButton("listing_alert.wav")
        self.listing_sound_btn.setFixedHeight(s(30))
        self.listing_sound_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.listing_sound_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {config.COLORS['background']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: {s(5)}px;
                padding: {s(4)}px {s(10)}px;
                font-size: {s(10)}px;
            }}
            QPushButton:hover {{
                border: 1px solid #1e90ff;
            }}
            """
        )
        self.listing_sound_play_btn = QPushButton("▶")
        self.listing_sound_play_btn.setFixedSize(s(28), s(30))
        self.listing_sound_play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.listing_sound_play_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {config.COLORS['background']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: {s(5)}px;
                font-size: {s(11)}px;
            }}
            QPushButton:hover {{
                border: 1px solid #1e90ff;
            }}
            """
        )
        self.listing_sound_btn.setMaximumWidth(s(200))
        self.listing_sound_btn.clicked.connect(self._select_listing_sound)
        self.listing_sound_play_btn.clicked.connect(self._play_listing_sound)
        listing_sound_row.addWidget(self.listing_sound_label_static)
        listing_sound_row.addWidget(self.listing_sound_btn)
        listing_sound_row.addWidget(self.listing_sound_play_btn)
        listing_sound_row.addStretch()
        listing_layout.addLayout(listing_sound_row)

        listing_engine_row = QHBoxLayout()
        self.listing_tts_engine_label = QLabel(
            self.translations["RU"]["listing_tts_engine"]
        )
        self.listing_tts_engine_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        self.listing_tts_engine_combo = NoWheelComboBox()
        self.listing_tts_engine_combo.addItem("System TTS (Windows)", "system")
        self.listing_tts_engine_combo.addItem(
            "Edge TTS (онлайн, лучшее качество)", "edge"
        )
        self.listing_tts_engine_combo.setStyleSheet(self._combo_style())
        self.listing_tts_engine_combo.currentIndexChanged.connect(
            self._on_listing_tts_engine_changed
        )
        listing_engine_row.addWidget(self.listing_tts_engine_label)
        listing_engine_row.addWidget(self.listing_tts_engine_combo, 1)
        listing_layout.addLayout(listing_engine_row)

        listing_lang_row = QHBoxLayout()
        self.listing_tts_language_label = QLabel(
            self.translations["RU"]["listing_tts_language"]
        )
        self.listing_tts_language_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        self.listing_tts_language_combo = NoWheelComboBox()
        self.listing_tts_language_combo.addItem("Русский", "ru")
        self.listing_tts_language_combo.addItem("English", "en")
        self.listing_tts_language_combo.setStyleSheet(self._combo_style())
        self.listing_tts_language_combo.currentIndexChanged.connect(
            self._on_listing_tts_language_changed
        )
        listing_lang_row.addWidget(self.listing_tts_language_label)
        listing_lang_row.addWidget(self.listing_tts_language_combo, 1)
        listing_layout.addLayout(listing_lang_row)

        listing_voice_row = QHBoxLayout()
        self.listing_tts_voice_label = QLabel(
            self.translations["RU"]["listing_tts_voice"]
        )
        self.listing_tts_voice_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        self.listing_tts_voice_combo = NoWheelComboBox()
        self.listing_tts_voice_combo.setStyleSheet(self._combo_style())
        self.listing_tts_voice_combo.currentIndexChanged.connect(
            self._on_listing_tts_voice_changed
        )
        if self.listing_tts_voice_combo.lineEdit():
            self.listing_tts_voice_combo.lineEdit().setAlignment(
                Qt.AlignmentFlag.AlignCenter
            )
        self.listing_tts_play_btn = QPushButton("▶")
        self.listing_tts_play_btn.setFixedSize(s(28), s(30))
        self.listing_tts_play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.listing_tts_play_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {config.COLORS['background']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: {s(5)}px;
                font-size: {s(11)}px;
            }}
            QPushButton:hover {{
                border: 1px solid #1e90ff;
            }}
            """
        )
        self.listing_tts_play_btn.clicked.connect(self._play_listing_tts)
        listing_voice_row.addWidget(self.listing_tts_voice_label)
        listing_voice_row.addWidget(self.listing_tts_voice_combo, 1)
        listing_voice_row.addWidget(self.listing_tts_play_btn)
        listing_layout.addLayout(listing_voice_row)

        listing_container = QWidget()
        listing_container_layout = QVBoxLayout(listing_container)
        listing_container_layout.setContentsMargins(s(8), 0, s(8), 0)
        listing_container_layout.setSpacing(0)
        listing_container_layout.addWidget(listing_frame)
        layout.addWidget(listing_container)

        layout.addSpacing(s(15))

        self.session_title = QLabel(self.translations["RU"]["session_title"])
        self.session_title.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(14)}px; font-weight: bold; border: none; background: transparent;"
        )
        self.session_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.session_title)

        session_frame = QFrame()
        session_frame.setStyleSheet(
            f"QFrame {{ background-color: {config.COLORS['panel']}; border: 1px solid {config.COLORS['border']}; border-radius: {s(6)}px; }}"
        )
        session_layout = QVBoxLayout(session_frame)
        session_layout.setContentsMargins(s(10), s(8), s(10), s(8))
        session_layout.setSpacing(s(6))

        session_check_row = QHBoxLayout()
        self.session_tts_check = FundingToggleCheckBox(
            self.translations["RU"]["session_tts_enabled"]
        )
        self.session_tts_check.setMinimumHeight(s(22))
        self.session_tts_check.setMinimumWidth(s(180))
        self.session_tts_check.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        session_check_row.addWidget(self.session_tts_check, 0, Qt.AlignmentFlag.AlignLeft)
        session_check_row.addStretch(1)
        session_layout.addLayout(session_check_row)

        session_engine_row = QHBoxLayout()
        self.session_tts_engine_label = QLabel(
            self.translations["RU"]["session_tts_engine"]
        )
        self.session_tts_engine_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        self.session_tts_engine_combo = NoWheelComboBox()
        self.session_tts_engine_combo.addItem("System TTS (Windows)", "system")
        self.session_tts_engine_combo.addItem(
            "Edge TTS (онлайн, лучшее качество)", "edge"
        )
        self.session_tts_engine_combo.setStyleSheet(self._combo_style())
        self.session_tts_engine_combo.currentIndexChanged.connect(
            self._on_session_tts_engine_changed
        )
        session_engine_row.addWidget(self.session_tts_engine_label)
        session_engine_row.addWidget(self.session_tts_engine_combo, 1)
        session_layout.addLayout(session_engine_row)

        session_lang_row = QHBoxLayout()
        self.session_tts_language_label = QLabel(
            self.translations["RU"]["session_tts_language"]
        )
        self.session_tts_language_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        self.session_tts_language_combo = NoWheelComboBox()
        self.session_tts_language_combo.addItem("Русский", "ru")
        self.session_tts_language_combo.addItem("English", "en")
        self.session_tts_language_combo.setStyleSheet(self._combo_style())
        self.session_tts_language_combo.currentIndexChanged.connect(
            self._on_session_tts_language_changed
        )
        session_lang_row.addWidget(self.session_tts_language_label)
        session_lang_row.addWidget(self.session_tts_language_combo, 1)
        session_layout.addLayout(session_lang_row)

        session_voice_row = QHBoxLayout()
        self.session_tts_voice_label = QLabel(
            self.translations["RU"]["session_tts_voice"]
        )
        self.session_tts_voice_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        self.session_tts_voice_combo = NoWheelComboBox()
        self.session_tts_voice_combo.setStyleSheet(self._combo_style())
        self.session_tts_voice_combo.currentIndexChanged.connect(
            self._on_session_tts_voice_changed
        )
        if self.session_tts_voice_combo.lineEdit():
            self.session_tts_voice_combo.lineEdit().setAlignment(
                Qt.AlignmentFlag.AlignCenter
            )
        self.session_tts_play_btn = QPushButton("▶")
        self.session_tts_play_btn.setFixedSize(s(28), s(30))
        self.session_tts_play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.session_tts_play_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {config.COLORS['background']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: {s(5)}px;
                font-size: {s(11)}px;
            }}
            QPushButton:hover {{
                border: 1px solid #1e90ff;
            }}
            """
        )
        self.session_tts_play_btn.clicked.connect(self._play_session_tts)
        session_voice_row.addWidget(self.session_tts_voice_label)
        session_voice_row.addWidget(self.session_tts_voice_combo, 1)
        session_voice_row.addWidget(self.session_tts_play_btn)
        session_layout.addLayout(session_voice_row)

        session_container = QWidget()
        session_container_layout = QVBoxLayout(session_container)
        session_container_layout.setContentsMargins(s(8), 0, s(8), 0)
        session_container_layout.setSpacing(0)
        session_container_layout.addWidget(session_frame)
        layout.addWidget(session_container)

        # Separator line
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.Shape.HLine)
        separator2.setFrameShadow(QFrame.Shadow.Sunken)
        separator2.setStyleSheet(f"color: {config.COLORS['border']};")
        layout.addWidget(separator2)

        layout.addSpacing(s(15))

        # Preview player for sounds
        self.preview_player = QMediaPlayer()
        self.preview_output = QAudioOutput()
        self.preview_player.setAudioOutput(self.preview_output)
        self._refresh_preview_audio_device()

        # Настройки звуков
        self.sounds_title = QLabel(self.translations["RU"]["sounds_title"])
        self.sounds_title.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(14)}px; font-weight: bold; border: none; background: transparent;"
        )
        self.sounds_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.sounds_title)

        sounds_container = QWidget()
        sounds_layout = QVBoxLayout(sounds_container)
        sounds_layout.setContentsMargins(s(8), 0, s(8), 0)
        sounds_layout.setSpacing(s(4))

        # --- TTS настройки для таймфреймов ---
        tf_tts_container = QFrame()
        tf_tts_container.setStyleSheet(
            f"QFrame {{ background-color: {config.COLORS['panel']}; border: 1px solid {config.COLORS['border']}; border-radius: {s(6)}px; }}"
        )
        tf_tts_layout = QVBoxLayout(tf_tts_container)
        tf_tts_layout.setContentsMargins(s(10), s(8), s(10), s(8))
        tf_tts_layout.setSpacing(s(6))

        # Заголовок TTS
        self.tf_tts_title = QLabel(self.translations["RU"]["tf_tts_title"])
        self.tf_tts_title.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(12)}px; font-weight: bold; border: none; background: transparent;"
        )
        tf_tts_layout.addWidget(self.tf_tts_title)

        # Чекбокс включения TTS
        self.tf_tts_check = FundingToggleCheckBox(
            self.translations["RU"]["tf_tts_enabled"]
        )
        self.tf_tts_check.setMinimumHeight(s(22))
        self.tf_tts_check.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        tf_tts_layout.addWidget(self.tf_tts_check)

        # TTS Движок выбор
        engine_row = QHBoxLayout()
        self.tf_tts_engine_label = QLabel(self.translations["RU"]["tf_tts_engine"])
        self.tf_tts_engine_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        self.tf_tts_engine_combo = NoWheelComboBox()
        self.tf_tts_engine_combo.addItem("System TTS (Windows)", "system")
        self.tf_tts_engine_combo.addItem("Edge TTS (онлайн, лучшее качество)", "edge")
        self.tf_tts_engine_combo.setStyleSheet(self._combo_style())
        self.tf_tts_engine_combo.currentIndexChanged.connect(
            self._on_tf_tts_engine_changed
        )
        engine_row.addWidget(self.tf_tts_engine_label)
        engine_row.addWidget(self.tf_tts_engine_combo, 1)
        tf_tts_layout.addLayout(engine_row)

        # TTS Язык выбор
        lang_row = QHBoxLayout()
        self.tf_tts_language_label = QLabel(self.translations["RU"]["tf_tts_language"])
        self.tf_tts_language_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        self.tf_tts_language_combo = NoWheelComboBox()
        self.tf_tts_language_combo.addItem("Русский", "ru")
        self.tf_tts_language_combo.addItem("English", "en")
        self.tf_tts_language_combo.setStyleSheet(self._combo_style())
        self.tf_tts_language_combo.currentIndexChanged.connect(
            self._on_tf_tts_language_changed
        )
        lang_row.addWidget(self.tf_tts_language_label)
        lang_row.addWidget(self.tf_tts_language_combo, 1)
        tf_tts_layout.addLayout(lang_row)

        # TTS Голос выбор
        voice_row = QHBoxLayout()
        self.tf_tts_voice_label = QLabel(self.translations["RU"]["tf_tts_voice"])
        self.tf_tts_voice_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none; background: transparent;"
        )
        self.tf_tts_voice_combo = NoWheelComboBox()
        self.tf_tts_voice_combo.setStyleSheet(self._combo_style())
        self.tf_tts_voice_combo.currentIndexChanged.connect(
            self._on_tf_tts_voice_changed
        )
        if self.tf_tts_voice_combo.lineEdit():
            self.tf_tts_voice_combo.lineEdit().setAlignment(
                Qt.AlignmentFlag.AlignCenter
            )
        self.tf_tts_play_btn = QPushButton("▶")
        self.tf_tts_play_btn.setFixedSize(s(28), s(30))
        self.tf_tts_play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tf_tts_play_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {config.COLORS['background']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: {s(5)}px;
                font-size: {s(11)}px;
            }}
            QPushButton:hover {{
                border: 1px solid #1e90ff;
            }}
            """
        )
        self.tf_tts_play_btn.clicked.connect(self._play_tf_tts_test)
        voice_row.addWidget(self.tf_tts_voice_label)
        voice_row.addWidget(self.tf_tts_voice_combo, 1)
        voice_row.addWidget(self.tf_tts_play_btn)
        tf_tts_layout.addLayout(voice_row)

        sounds_layout.addWidget(tf_tts_container)
        sounds_layout.addSpacing(s(6))
        # --- Конец TTS настроек для таймфреймов ---

        self.sound_buttons = {}
        # Списки всех кнопок (выбора и проигрывания) для каждого типа звука
        self.buttons_main = []  # Основной звук (выбор + проигрывание)
        self.buttons_tick = []  # Звуки тиков (выбор + проигрывание)
        self.buttons_transition = []  # Звуки переходов (выбор + проигрывание)
        self.tf_labels = {}
        self.tf_tts_toggles = {}  # Кнопки переключения TTS/Sound для каждого ТФ

        # Инициализируем settings для использования на всей этой странице
        settings = QSettings("MyTradeTools", "TF-Alerter")

        def make_btn(text):
            btn = QPushButton(text)
            btn.setFixedSize(s(130), s(32))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {config.COLORS['background']};
                    color: {config.COLORS['text']};
                    border: 1px solid {config.COLORS['border']};
                    border-radius: {s(5)}px;
                    padding: {s(4)}px {s(12)}px;
                    font-size: {s(10)}px;
                }}
                QPushButton:hover {{
                    border: 1px solid #1e90ff;
                }}
                """
            )
            return btn

        def make_play_btn():
            btn = QPushButton("▶")
            btn.setFixedSize(s(24), s(32))  # Уменьшенная ширина для экономии места
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {config.COLORS['background']};
                    color: {config.COLORS['text']};
                    border: 1px solid {config.COLORS['border']};
                    border-radius: {s(5)}px;
                    font-size: {s(11)}px;
                }}
                QPushButton:hover {{
                    border: 1px solid #1e90ff;
                }}
                """
            )
            return btn

        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(s(10), 0, s(20), 0)
        header_layout.setSpacing(s(2))

        self.header_tf = QLabel(self.translations["RU"]["tf_col"])
        self.header_tf.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(10)}px; font-weight: bold; border: none; background: transparent;"
        )
        self.header_tf.setFixedWidth(s(56))
        self.header_tf.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.header_tf)
        header_layout.addSpacing(s(4))

        def make_header(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {config.COLORS['text']}; font-size: {s(10)}px; font-weight: bold; border: none; background: transparent;"
            )
            lbl.setFixedWidth(s(130))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return lbl

        play_btn_width = s(24)
        tts_toggle_width = s(28)

        def build_header_container(label, checkbox, checkbox_offset=0):
            container = QWidget()
            grid = QGridLayout(container)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(0)
            grid.setVerticalSpacing(s(2))
            grid.setColumnStretch(0, 1)
            grid.setColumnMinimumWidth(1, play_btn_width)
            grid.addWidget(label, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter)
            if checkbox_offset:
                checkbox_row = QWidget()
                checkbox_row_layout = QHBoxLayout(checkbox_row)
                checkbox_row_layout.setContentsMargins(0, 0, 0, 0)
                checkbox_row_layout.setSpacing(0)
                checkbox_row_layout.addSpacing(checkbox_offset)
                checkbox_row_layout.addWidget(checkbox)
                checkbox_row_layout.addStretch()
                grid.addWidget(
                    checkbox_row, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter
                )
            else:
                grid.addWidget(checkbox, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter)
            container.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            return container

        # Создим контейнеры для каждой колонки с заголовком и чекбоксом
        self.check_voice_enabled = SoundColumnCheckBox()
        self.check_voice_enabled.setChecked(
            settings.value("sounds_voice_enabled", True, type=bool)
        )
        self.header_voice = make_header(self.translations["RU"]["voice_col"])
        voice_container = build_header_container(
            self.header_voice, self.check_voice_enabled, s(2)
        )

        self.check_tick_enabled = SoundColumnCheckBox()
        self.check_tick_enabled.setChecked(
            settings.value("sounds_tick_enabled", True, type=bool)
        )
        self.header_tick = make_header(self.translations["RU"]["tick_col"])
        tick_container = build_header_container(
            self.header_tick, self.check_tick_enabled
        )

        self.check_transition_enabled = SoundColumnCheckBox()
        self.check_transition_enabled.setChecked(
            settings.value("sounds_transition_enabled", True, type=bool)
        )
        self.header_transition = make_header(self.translations["RU"]["transition_col"])
        transition_container = build_header_container(
            self.header_transition, self.check_transition_enabled
        )

        tts_spacer = QWidget()
        tts_spacer.setFixedWidth(tts_toggle_width)
        header_layout.addWidget(tts_spacer)

        header_layout.addWidget(voice_container, 1)
        header_layout.addWidget(tick_container, 1)
        header_layout.addWidget(transition_container, 1)

        # Подключаем события для изменения стиля при отключении
        self.check_voice_enabled.stateChanged.connect(
            lambda: self._update_sound_column_style(
                "main", self.check_voice_enabled, self.header_voice
            )
        )
        self.check_tick_enabled.stateChanged.connect(
            lambda: self._update_sound_column_style(
                "tick", self.check_tick_enabled, self.header_tick
            )
        )
        self.check_transition_enabled.stateChanged.connect(
            lambda: self._update_sound_column_style(
                "transition", self.check_transition_enabled, self.header_transition
            )
        )

        # Инициальное обновление стилей
        self._update_sound_column_style(
            "main", self.check_voice_enabled, self.header_voice
        )
        self._update_sound_column_style(
            "tick", self.check_tick_enabled, self.header_tick
        )
        self._update_sound_column_style(
            "transition", self.check_transition_enabled, self.header_transition
        )

        sounds_layout.addWidget(header_row)

        for tf_key, data in config.TIMEFRAMES.items():
            # Создаем карточку для каждого таймфрейма
            tf_card = QFrame()
            tf_card.setStyleSheet(
                f"QFrame {{ background-color: {config.COLORS['panel']}; border: 1px solid {config.COLORS['border']}; border-radius: {s(6)}px; }}"
            )
            tf_card.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            tf_card.setFixedHeight(s(44))
            card_layout = QHBoxLayout(tf_card)
            card_layout.setContentsMargins(
                s(10), s(6), s(20), s(6)
            )  # Увеличенный правый margin для свободы
            card_layout.setSpacing(s(2))  # Уменьшенный spacing между элементами

            # Метка таймфрейма
            saved_lang = settings.value("language", "RU")
            tf_label = QLabel(config.get_timeframe_label(tf_key, saved_lang))
            tf_label.setStyleSheet(
                f"color: {config.COLORS['text']}; font-size: {s(11)}px; font-weight: bold; border: none; background: transparent;"
            )
            tf_label.setFixedWidth(s(56))
            tf_label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            card_layout.addWidget(tf_label)
            self.tf_labels[tf_key] = tf_label

            # Разделитель
            card_layout.addSpacing(s(4))  # Spacing перед первой group

            # Кнопка переключения TTS/Sound для основного звука
            tts_toggle_btn = QPushButton("🔊")
            tts_toggle_btn.setFixedSize(s(28), s(32))
            tts_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            tts_toggle_btn.setToolTip("Переключить TTS/Звук")
            tts_toggle_btn.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {config.COLORS['background']};
                    color: {config.COLORS['text']};
                    border: 1px solid {config.COLORS['border']};
                    border-radius: {s(5)}px;
                    font-size: {s(14)}px;
                }}
                QPushButton:hover {{
                    border: 1px solid #1e90ff;
                }}
                QToolTip {{
                    color: #ffffff;
                    background-color: {config.COLORS['panel']};
                    border: 1px solid {config.COLORS['border']};
                }}
                """
            )
            tts_toggle_btn.clicked.connect(
                lambda _=False, k=tf_key: self._toggle_tf_tts(k)
            )
            card_layout.addWidget(tts_toggle_btn)
            self.tf_tts_toggles[tf_key] = tts_toggle_btn

            # Основной звук
            main_name = os.path.basename(data["file"])
            main_btn = make_btn(main_name)
            main_btn.setMinimumWidth(s(130))
            card_layout.addWidget(main_btn, 1)

            play_main_btn = make_play_btn()
            card_layout.addWidget(play_main_btn)

            # Разделитель
            card_layout.addSpacing(s(2))  # Уменьшенный spacing между группами

            # Звук тиков
            tick_name = os.path.basename(config.SOUND_TICK_BY_TF.get(tf_key, ""))
            tick_btn = make_btn(tick_name)
            tick_btn.setMinimumWidth(s(130))
            card_layout.addWidget(tick_btn, 1)

            play_tick_btn = make_play_btn()
            card_layout.addWidget(play_tick_btn)

            # Разделитель
            card_layout.addSpacing(s(2))  # Уменьшенный spacing между группами

            # Звук перехода
            transition_name = os.path.basename(
                config.SOUND_TRANSITION_BY_TF.get(tf_key, "")
            )
            transition_btn = make_btn(transition_name)
            transition_btn.setMinimumWidth(s(130))
            card_layout.addWidget(transition_btn, 1)

            play_transition_btn = make_play_btn()
            card_layout.addWidget(play_transition_btn)

            # Подключаем события
            main_btn.clicked.connect(
                lambda _=False, k=tf_key: self._select_sound(k, "main")
            )
            tick_btn.clicked.connect(
                lambda _=False, k=tf_key: self._select_sound(k, "tick")
            )
            transition_btn.clicked.connect(
                lambda _=False, k=tf_key: self._select_sound(k, "transition")
            )
            play_main_btn.clicked.connect(
                lambda _=False, k=tf_key: self._play_sound(k, "main")
            )
            play_tick_btn.clicked.connect(
                lambda _=False, k=tf_key: self._play_sound(k, "tick")
            )
            play_transition_btn.clicked.connect(
                lambda _=False, k=tf_key: self._play_sound(k, "transition")
            )

            # Сохраняем кнопки
            self.sound_buttons[(tf_key, "main")] = main_btn
            self.sound_buttons[(tf_key, "tick")] = tick_btn
            self.sound_buttons[(tf_key, "transition")] = transition_btn

            # Сохраняем все кнопки по типам звука для управления стилями
            self.buttons_main.append((main_btn, play_main_btn))
            self.buttons_tick.append((tick_btn, play_tick_btn))
            self.buttons_transition.append((transition_btn, play_transition_btn))

            sounds_layout.addWidget(tf_card)

        layout.addWidget(sounds_container)

        layout.addSpacing(s(15))

        main_scroll.setWidget(scroll_content)

        # Кнопки (в фиксированном футере)
        self.footer_layout.addStretch()

        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.setFixedHeight(s(32))
        self.cancel_btn.setFixedWidth(s(100))
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setStyleSheet(
            """
            QPushButton {
                color: #ff3b30;
                border: 2px solid #ff3b30;
                border-radius: 10px;
                font-weight: bold;
                padding: 5px;
            }
            QPushButton:hover {
                background: #ff3b30;
                color: black;
            }
        """
        )

        self.save_btn = QPushButton("Сохранить")
        self.save_btn.setFixedHeight(s(32))
        self.save_btn.setFixedWidth(s(100))
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(self.save_and_close)
        self.save_btn.setStyleSheet(
            """
            QPushButton {
                color: #1e90ff;
                border: 2px solid #1e90ff;
                border-radius: 10px;
                font-weight: bold;
                padding: 5px;
            }
            QPushButton:hover {
                background: #1e90ff;
                color: black;
            }
        """
        )

        self.footer_layout.addWidget(self.cancel_btn)
        self.footer_layout.addSpacing(5)
        self.footer_layout.addWidget(self.save_btn)
        self.footer_layout.addStretch()

        # Загрузка текущих настроек
        self.load_current_settings()

        # Для перетаскивания
        self.old_pos = None

    def _combo_style(self):
        return f"""
            QComboBox {{
                background-color: {config.COLORS['panel']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: 5px;
                padding: 5px 10px;
                min-width: 80px;
            }}
            QComboBox:hover {{
                border: 1px solid #1e90ff;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {config.COLORS['panel']};
                color: {config.COLORS['text']};
                selection-background-color: #1e90ff;
                border: 1px solid {config.COLORS['border']};
            }}
        """

    def _refresh_preview_audio_device(self):
        output = getattr(self, "preview_output", None)
        if output is None:
            return
        try:
            from PyQt6.QtMultimedia import QMediaDevices

            default_device = QMediaDevices.defaultAudioOutput()
            output.setDevice(default_device)
        except Exception:
            pass

    def _update_sound_column_style(self, kind, checkbox, header_label):
        """Обновляет стиль всей колонки звуков (заголовок и все кнопки)"""
        scaled_px = max(1, int(10 * self.scale_factor))

        is_enabled = checkbox.isChecked()

        # Определяем цвет для заголовка
        if is_enabled:
            header_color = config.COLORS["text"]
            button_opacity = 1.0
            button_border_color = config.COLORS["border"]
        else:
            header_color = config.COLORS["border"]
            button_opacity = 0.5
            button_border_color = "#555555"  # Еще более темный бордер

        # Обновляем стиль заголовка
        header_label.setStyleSheet(
            f"color: {header_color}; font-size: {scaled_px}px; font-weight: bold; border: none; background: transparent;"
        )

        # Получаем список кнопок для этого типа звука
        if kind == "main":
            buttons = self.buttons_main
        elif kind == "tick":
            buttons = self.buttons_tick
        elif kind == "transition":
            buttons = self.buttons_transition
        else:
            buttons = []

        # Обновляем стиль и состояние всех кнопок в колонке
        for select_btn, play_btn in buttons:
            # Обновляем стиль кнопки выбора
            select_btn.setEnabled(is_enabled)
            if is_enabled:
                select_btn.setStyleSheet(
                    f"""
                    QPushButton {{
                        background-color: {config.COLORS['background']};
                        color: {config.COLORS['text']};
                        border: 1px solid {config.COLORS['border']};
                        border-radius: {max(1, int(5 * self.scale_factor))}px;
                        padding: {max(1, int(4 * self.scale_factor))}px {max(1, int(12 * self.scale_factor))}px;
                        font-size: {max(1, int(10 * self.scale_factor))}px;
                    }}
                    QPushButton:hover {{
                        border: 1px solid #1e90ff;
                    }}
                    """
                )
            else:
                select_btn.setStyleSheet(
                    f"""
                    QPushButton {{
                        background-color: #0a0a0a;
                        color: #555555;
                        border: 1px solid #555555;
                        border-radius: {max(1, int(5 * self.scale_factor))}px;
                        padding: {max(1, int(4 * self.scale_factor))}px {max(1, int(12 * self.scale_factor))}px;
                        font-size: {max(1, int(10 * self.scale_factor))}px;
                    }}
                    QPushButton:hover {{
                        border: 1px solid #555555;
                    }}
                    """
                )

            # Обновляем стиль кнопки проигрывания
            play_btn.setEnabled(is_enabled)
            if is_enabled:
                play_btn.setStyleSheet(
                    f"""
                    QPushButton {{
                        background-color: {config.COLORS['background']};
                        color: {config.COLORS['text']};
                        border: 1px solid {config.COLORS['border']};
                        border-radius: {max(1, int(5 * self.scale_factor))}px;
                        font-size: {max(1, int(11 * self.scale_factor))}px;
                    }}
                    QPushButton:hover {{
                        border: 1px solid #1e90ff;
                    }}
                    """
                )
            else:
                play_btn.setStyleSheet(
                    f"""
                    QPushButton {{
                        background-color: #0a0a0a;
                        color: #555555;
                        border: 1px solid #555555;
                        border-radius: {max(1, int(5 * self.scale_factor))}px;
                        font-size: {max(1, int(11 * self.scale_factor))}px;
                    }}
                    QPushButton:hover {{
                        border: 1px solid #555555;
                    }}
                    """
                )

    def _update_header_style(self, header_label, checkbox):
        """Обновляет стиль заголовка колонки (затемняет если отключена)"""
        scaled_px = max(1, int(10 * self.scale_factor))
        if checkbox.isChecked():
            # Включена - нормальный цвет
            color = config.COLORS["text"]
        else:
            # Отключена - затемненный цвет
            color = config.COLORS["border"]

        header_label.setStyleSheet(
            f"color: {color}; font-size: {scaled_px}px; font-weight: bold; border: none; background: transparent;"
        )

    def _select_sound(self, tf_key, kind):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выбрать звук",
            "",
            "Audio Files (*.wav *.mp3 *.ogg);;All Files (*.*)",
        )
        if not file_path:
            return

        ext = os.path.splitext(file_path)[1].lower() or ".wav"
        if ext not in config.ALLOWED_SOUND_EXTENSIONS:
            QMessageBox.warning(
                self,
                "TF-Alerter",
                "Неподдерживаемый формат аудио. Выберите WAV/MP3/OGG/M4A/AAC/FLAC/WMA/OPUS",
            )
            return

        # Формируем имя файла в зависимости от типа
        # Для 1M (месяца) используем префикс 1Mo
        file_prefix = "1Mo" if tf_key == "1M" else tf_key

        if kind == "main":
            target_name = f"{file_prefix}_voice{ext}"
        elif kind == "tick":
            target_name = f"{file_prefix}_tick{ext}"
        else:  # transition
            target_name = f"{file_prefix}_transition{ext}"

        target_dir = config.get_sound_dir(kind)
        target_path = os.path.join(target_dir, target_name)
        os.makedirs(target_dir, exist_ok=True)

        # Копируем новый звук, заменяя старый
        try:
            shutil.copy2(file_path, target_path)
        except Exception:
            return

        settings = QSettings("MyTradeTools", "TF-Alerter")

        # КРИТИЧНО: Используем разные имена для 1m и 1M в QSettings
        # Потому что Windows реестр case-insensitive и 1m/1M конфликтуют
        # Для 1M используем 1Month чтобы избежать конфликта
        qsettings_key = tf_key.replace("1M", "1Month") if tf_key == "1M" else tf_key

        if kind == "main":
            config.TIMEFRAMES[tf_key]["file"] = target_name
            key_name = f"sound_main_{qsettings_key}"
            settings.setValue(key_name, target_name)
        elif kind == "tick":
            config.SOUND_TICK_BY_TF[tf_key] = target_name
            key_name = f"sound_tick_{qsettings_key}"
            settings.setValue(key_name, target_name)
        elif kind == "transition":
            config.SOUND_TRANSITION_BY_TF[tf_key] = target_name
            key_name = f"sound_transition_{qsettings_key}"
            settings.setValue(key_name, target_name)

        settings.sync()

        # ВАЖНО: Обновляем кнопки ТОЛЬКО для текущего таймфрейма и вида
        btn = self.sound_buttons.get((tf_key, kind))
        if btn:
            btn.setText(os.path.basename(target_name))

    def _load_voice_files(self):
        """Загружает список голосов в зависимости от выбранного TTS движка"""
        engine = self.funding_tts_engine_combo.currentData()
        language = self.funding_tts_language_combo.currentData()

        self.funding_tts_voice_combo.blockSignals(True)
        try:
            self.funding_tts_voice_combo.clear()

            if engine == "system":
                self._load_system_voices(language)
            elif engine == "edge":
                self._load_edge_voices(language)

            # Восстанавливаем сохраненный голос (если он был установлен ранее)
            if hasattr(self, "_saved_voice_id") and self._saved_voice_id:
                voice_idx = self.funding_tts_voice_combo.findData(self._saved_voice_id)
                if voice_idx >= 0:
                    self.funding_tts_voice_combo.setCurrentIndex(voice_idx)
                    return

            # Если голос не найден или не был сохранен, выбираем первый
            if self.funding_tts_voice_combo.count() > 0:
                self.funding_tts_voice_combo.setCurrentIndex(0)
        finally:
            self.funding_tts_voice_combo.blockSignals(False)

    def _load_system_voices(self, language):
        """Загружает системные TTS голоса (pyttsx3)"""
        try:
            import pyttsx3

            engine = pyttsx3.init()
            voices = engine.getProperty("voices") or []

            def _voice_matches_language(voice, lang):
                name = str(getattr(voice, "name", "") or "").lower()
                vid = str(getattr(voice, "id", "") or "").lower()
                langs = []
                for item in getattr(voice, "languages", []) or []:
                    try:
                        if isinstance(item, bytes):
                            langs.append(item.decode(errors="ignore").lower())
                        else:
                            langs.append(str(item).lower())
                    except Exception:
                        continue
                lang_blob = " ".join(langs)

                if lang == "ru":
                    return (
                        "ru" in lang_blob
                        or "ru" in name
                        or "russian" in name
                        or "ru" in vid
                        or "pavel" in name
                        or "irina" in name
                        or "tatyana" in name
                        or "anna" in name
                        or "natalia" in name
                        or "yuri" in name
                        or "nikolai" in name
                        or "nicolai" in name
                    )

                if lang == "en":
                    return (
                        "en" in lang_blob
                        or "english" in name
                        or "en" in vid
                        or "zira" in name
                        or "david" in name
                        or "mark" in name
                        or "eva" in name
                    )

                return False

            for voice in voices:
                name = getattr(voice, "name", "Voice")
                vid = getattr(voice, "id", "")

                # Фильтруем по языку
                if _voice_matches_language(voice, language):
                    self.funding_tts_voice_combo.addItem(name, vid)

            if self.funding_tts_voice_combo.count() == 0:
                # Если голосов нет после фильтрации, добавляем все
                for voice in voices:
                    name = getattr(voice, "name", "Voice")
                    vid = getattr(voice, "id", "")
                    self.funding_tts_voice_combo.addItem(name, vid)

            engine.stop()
        except Exception as e:
            print(f"⚠️ Ошибка загрузки системных голосов: {e}")

    def _load_edge_voices(self, language):
        """Загружает Edge TTS голоса"""
        if language == "ru":
            # Русские голоса Edge TTS
            self.funding_tts_voice_combo.addItem(
                "[RU-M] Dmitry (мужской)", "ru-RU-DmitryNeural"
            )
            self.funding_tts_voice_combo.addItem(
                "[RU-F] Svetlana (женский)", "ru-RU-SvetlanaNeural"
            )
            self.funding_tts_voice_combo.addItem(
                "[RU-M] Andrew (accented)", "en-US-AndrewMultilingualNeural"
            )
            self.funding_tts_voice_combo.addItem(
                "[RU-F] Ava (accented)", "en-US-AvaMultilingualNeural"
            )
            self.funding_tts_voice_combo.addItem(
                "[RU-F] Emma (accented)", "en-US-EmmaMultilingualNeural"
            )
            self.funding_tts_voice_combo.addItem(
                "[RU-M] Brian (accented)", "en-US-BrianMultilingualNeural"
            )
            self.funding_tts_voice_combo.addItem(
                "[RU-M] William (accented)", "en-AU-WilliamMultilingualNeural"
            )
        elif language == "en":
            # Английские голоса Edge TTS
            self.funding_tts_voice_combo.addItem("[EN-M] Guy (male)", "en-US-GuyNeural")
            self.funding_tts_voice_combo.addItem(
                "[EN-F] Jenny (female)", "en-US-JennyNeural"
            )
            self.funding_tts_voice_combo.addItem(
                "[EN-F] Aria (female)", "en-US-AriaNeural"
            )
            self.funding_tts_voice_combo.addItem(
                "[EN-M] Brian (male)", "en-US-BrianNeural"
            )
            self.funding_tts_voice_combo.addItem(
                "[EN-M] Ryan (male, UK)", "en-GB-RyanNeural"
            )
            self.funding_tts_voice_combo.addItem(
                "[EN-F] Sonia (female, UK)", "en-GB-SoniaNeural"
            )

    def _on_tts_engine_changed(self, index):
        """Обработчик смены TTS движка"""
        # Сохраняем выбранный движок
        engine_id = self.funding_tts_engine_combo.currentData()
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("funding_tts_engine", engine_id)
        # Очищаем сохраненный голос при смене движка
        self._saved_voice_id = ""
        self._load_voice_files()

    def _on_tts_language_changed(self, index):
        """Обработчик смены языка"""
        # Сохраняем выбранный язык
        language = self.funding_tts_language_combo.currentData()
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("funding_tts_language", language)
        # Очищаем сохраненный голос при смене языка
        self._saved_voice_id = ""
        self._load_voice_files()

    def _on_tts_voice_changed(self, index):
        """Обработчик смены голоса TTS"""
        # Сохраняем выбранный голос
        voice_id = self.funding_tts_voice_combo.currentData()
        voice_id = str(voice_id) if voice_id is not None else ""
        self._saved_voice_id = voice_id
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("funding_tts_voice_id", voice_id)
        # Очищаем legacy-ключ, чтобы он не перетирал актуальный выбор
        settings.remove("funding_voice_file")
        settings.sync()

    def _select_funding_sound(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.translations[self.lang_combo.currentText()]["funding_sound_pick"],
            "",
            "Audio Files (*.wav *.mp3 *.ogg);;All Files (*.*)",
        )
        if not file_path:
            return
        ext = os.path.splitext(file_path)[1].lower() or ".wav"
        if ext not in config.ALLOWED_SOUND_EXTENSIONS:
            QMessageBox.warning(
                self,
                "TF-Alerter",
                "Неподдерживаемый формат аудио. Выберите WAV/MP3/OGG/M4A/AAC/FLAC/WMA/OPUS",
            )
            return
        target_name = f"funding_alert{ext}"
        target_dir = config.get_sound_dir("funding")
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, target_name)
        try:
            shutil.copy2(file_path, target_path)
        except Exception:
            return
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("funding_sound_file", target_name)
        settings.sync()
        self.funding_sound_file = target_name
        self.funding_sound_btn.setText(os.path.basename(target_name))

    def _play_funding_sound(self):
        settings = QSettings("MyTradeTools", "TF-Alerter")
        filename = config.sanitize_sound_filename(
            settings.value("funding_sound_file", config.SOUND_FUNDING_ALERT),
            config.SOUND_FUNDING_ALERT,
        )
        if not filename:
            return
        path = config.get_sound_path("funding", filename)
        if not path or not os.path.exists(path):
            path = config.get_sound_path("funding", config.SOUND_FUNDING_ALERT)
        if not path or not os.path.exists(path):
            return
        self._refresh_preview_audio_device()
        self.preview_player.stop()
        self.preview_player.setSource(QUrl())
        self.preview_output.setVolume(config.clamp_audio_volume(1.0))
        self.preview_player.setSource(QUrl.fromLocalFile(path))
        self.preview_player.play()

    def _play_funding_tts(self):
        """\u041fроигрывает тестовое TTS сообщение"""
        try:
            import threading

            engine_type = self.funding_tts_engine_combo.currentData()
            language = self.funding_tts_language_combo.currentData()
            voice_id = self.funding_tts_voice_combo.currentData()

            # Полные тестовые сообщения
            test_messages = {
                "ru": "Бинанс, биткоин, плюс ноль целых пять процента, через 15 минут",
                "en": "Binance, bitcoin, positive zero point five percent, in 15 minutes",
            }

            test_text = test_messages.get(language, test_messages["en"])

            if engine_type == "edge":
                # Для Edge запускаем из UI-потока, чтобы preview-плеер всегда
                # корректно получал команду воспроизведения.
                self._speak_edge_tts(test_text, voice_id, language)
                return

            def speak_thread():
                self._speak_system_tts(test_text, voice_id)

            thread = threading.Thread(target=speak_thread, daemon=True)
            thread.start()
        except Exception as e:
            print(f"⚠️ Ошибка проигрывания TTS: {e}")

    def _select_listing_sound(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.translations[self.lang_combo.currentText()]["listing_sound_pick"],
            "",
            "Audio Files (*.wav *.mp3 *.ogg);;All Files (*.*)",
        )
        if not file_path:
            return
        ext = os.path.splitext(file_path)[1].lower() or ".wav"
        if ext not in config.ALLOWED_SOUND_EXTENSIONS:
            QMessageBox.warning(
                self,
                "TF-Alerter",
                "Неподдерживаемый формат аудио. Выберите WAV/MP3/OGG/M4A/AAC/FLAC/WMA/OPUS",
            )
            return
        target_name = f"listing_alert{ext}"
        target_dir = config.get_sound_dir("listing")
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, target_name)
        try:
            shutil.copy2(file_path, target_path)
        except Exception:
            return
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("listing_sound_file", target_name)
        settings.sync()
        self.listing_sound_file = target_name
        self.listing_sound_btn.setText(os.path.basename(target_name))

    def _play_listing_sound(self):
        settings = QSettings("MyTradeTools", "TF-Alerter")
        filename = config.sanitize_sound_filename(
            settings.value("listing_sound_file", config.SOUND_LISTING_ALERT),
            config.SOUND_LISTING_ALERT,
        )
        if not filename:
            return
        path = config.get_sound_path("listing", filename)
        if not path or not os.path.exists(path):
            path = config.get_sound_path("listing", config.SOUND_LISTING_ALERT)
        if not path or not os.path.exists(path):
            return
        self._refresh_preview_audio_device()
        self.preview_player.stop()
        self.preview_player.setSource(QUrl())
        self.preview_output.setVolume(config.clamp_audio_volume(1.0))
        self.preview_player.setSource(QUrl.fromLocalFile(path))
        self.preview_player.play()

    def _play_listing_tts(self):
        """Проигрывает тестовое TTS сообщение для листинга"""
        try:
            import threading

            engine_type = self.listing_tts_engine_combo.currentData()
            language = self.listing_tts_language_combo.currentData()
            voice_id = self.listing_tts_voice_combo.currentData()

            test_messages = {
                "ru": "Бинанс, биткоин, листинг в 12:30",
                "en": "Binance, bitcoin, listing at 12:30",
            }

            test_text = test_messages.get(language, test_messages["en"])

            if engine_type == "edge":
                self._speak_edge_tts(test_text, voice_id, language)
                return

            def speak_thread():
                self._speak_system_tts(test_text, voice_id)

            thread = threading.Thread(target=speak_thread, daemon=True)
            thread.start()
        except Exception as e:
            print(f"⚠️ Ошибка проигрывания Listing TTS: {e}")

    def _load_listing_voice_files(self):
        """Загружает список голосов для листинга"""
        engine = self.listing_tts_engine_combo.currentData()
        language = self.listing_tts_language_combo.currentData()

        self.listing_tts_voice_combo.blockSignals(True)
        try:
            self.listing_tts_voice_combo.clear()

            if engine == "system":
                self._load_listing_system_voices(language)
            elif engine == "edge":
                self._load_listing_edge_voices(language)

            if (
                hasattr(self, "_saved_listing_voice_id")
                and self._saved_listing_voice_id
            ):
                voice_idx = self.listing_tts_voice_combo.findData(
                    self._saved_listing_voice_id
                )
                if voice_idx >= 0:
                    self.listing_tts_voice_combo.setCurrentIndex(voice_idx)
                    return

            if self.listing_tts_voice_combo.count() > 0:
                self.listing_tts_voice_combo.setCurrentIndex(0)
        finally:
            self.listing_tts_voice_combo.blockSignals(False)

    def _load_listing_system_voices(self, language):
        """Загружает системные TTS голоса (pyttsx3) для листинга"""
        try:
            import pyttsx3

            engine = pyttsx3.init()
            voices = engine.getProperty("voices") or []

            def _voice_matches_language(voice, lang):
                name = str(getattr(voice, "name", "") or "").lower()
                vid = str(getattr(voice, "id", "") or "").lower()
                langs = []
                for item in getattr(voice, "languages", []) or []:
                    try:
                        if isinstance(item, bytes):
                            langs.append(item.decode(errors="ignore").lower())
                        else:
                            langs.append(str(item).lower())
                    except Exception:
                        continue
                lang_blob = " ".join(langs)

                if lang == "ru":
                    return (
                        "ru" in lang_blob
                        or "ru" in name
                        or "russian" in name
                        or "ru" in vid
                        or "pavel" in name
                        or "irina" in name
                        or "tatyana" in name
                        or "anna" in name
                        or "natalia" in name
                        or "yuri" in name
                        or "nikolai" in name
                        or "nicolai" in name
                    )

                if lang == "en":
                    return (
                        "en" in lang_blob
                        or "english" in name
                        or "en" in vid
                        or "zira" in name
                        or "david" in name
                        or "mark" in name
                        or "eva" in name
                    )

                return False

            for voice in voices:
                name = getattr(voice, "name", "Voice")
                vid = getattr(voice, "id", "")
                if _voice_matches_language(voice, language):
                    self.listing_tts_voice_combo.addItem(name, vid)

            if self.listing_tts_voice_combo.count() == 0:
                for voice in voices:
                    name = getattr(voice, "name", "Voice")
                    vid = getattr(voice, "id", "")
                    self.listing_tts_voice_combo.addItem(name, vid)

            engine.stop()
        except Exception as e:
            print(f"⚠️ Ошибка загрузки системных голосов (listing): {e}")

    def _load_listing_edge_voices(self, language):
        """Загружает Edge TTS голоса для листинга"""
        if language == "ru":
            voices = [
                ("ru-RU-DmitryNeural", "[RU-M] Dmitry (male)"),
                ("ru-RU-SvetlanaNeural", "[RU-F] Svetlana (female)"),
                ("en-US-AndrewMultilingualNeural", "[RU-M] Andrew (accented)"),
                ("en-US-AvaMultilingualNeural", "[RU-F] Ava (accented)"),
                ("en-US-EmmaMultilingualNeural", "[RU-F] Emma (accented)"),
                ("en-US-BrianMultilingualNeural", "[RU-M] Brian (accented)"),
                ("en-AU-WilliamMultilingualNeural", "[RU-M] William (accented)"),
            ]
        else:
            voices = [
                ("en-US-GuyNeural", "[EN-M] Guy (male)"),
                ("en-US-JennyNeural", "[EN-F] Jenny (female)"),
                ("en-US-AriaNeural", "[EN-F] Aria (female)"),
                ("en-US-BrianNeural", "[EN-M] Brian (male)"),
                ("en-GB-RyanNeural", "[EN-M] Ryan (male, UK)"),
                ("en-GB-SoniaNeural", "[EN-F] Sonia (female, UK)"),
            ]

        for voice_id, display_name in voices:
            self.listing_tts_voice_combo.addItem(display_name, voice_id)

    def _on_listing_tts_engine_changed(self, index):
        engine_id = self.listing_tts_engine_combo.currentData()
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("listing_tts_engine", engine_id)
        self._saved_listing_voice_id = ""
        self._load_listing_voice_files()

    def _on_listing_tts_language_changed(self, index):
        language = self.listing_tts_language_combo.currentData()
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("listing_tts_language", language)
        self._saved_listing_voice_id = ""
        self._load_listing_voice_files()

    def _on_listing_tts_voice_changed(self, index):
        voice_id = self.listing_tts_voice_combo.currentData()
        voice_id = str(voice_id) if voice_id is not None else ""
        self._saved_listing_voice_id = voice_id
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("listing_tts_voice_id", voice_id)
        settings.sync()

    def _play_session_tts(self):
        try:
            import threading

            engine_type = self.session_tts_engine_combo.currentData()
            language = self.session_tts_language_combo.currentData()
            voice_id = self.session_tts_voice_combo.currentData()

            test_messages = {
                "ru": "Тест сессии. Следующая: Европа.",
                "en": "Session test. Next: Europe.",
            }
            test_text = test_messages.get(language, test_messages["en"])

            if engine_type == "edge":
                self._play_session_edge_tts_preview_async(test_text, voice_id, language)
                return

            def speak_thread():
                self._speak_system_tts(test_text, voice_id)

            thread = threading.Thread(target=speak_thread, daemon=True)
            thread.start()
        except Exception as e:
            print(f"⚠️ Ошибка проигрывания Session TTS: {e}")

    def _play_session_edge_tts_preview_async(self, text, voice_id, language):
        cache_key = (
            str(language or "ru"),
            str(voice_id or ""),
            str(text or ""),
        )
        cached_path = self._session_tts_preview_cache.get(cache_key)
        if cached_path and os.path.exists(cached_path):
            self._play_preview_file(cached_path)
            return
        try:
            import asyncio
            import edge_tts
            import tempfile

            resolved_voice = voice_id
            if not resolved_voice:
                resolved_voice = (
                    "ru-RU-DmitryNeural"
                    if str(language or "ru") == "ru"
                    else "en-US-GuyNeural"
                )

            async def _generate_audio():
                with tempfile.NamedTemporaryFile(
                    suffix=".mp3", delete=False
                ) as tmp_file:
                    tmp_path = tmp_file.name

                communicate = edge_tts.Communicate(
                    text,
                    resolved_voice,
                )
                await communicate.save(tmp_path)
                return tmp_path

            tmp_path = asyncio.run(_generate_audio())
            self._play_and_cache_session_tts_preview(cache_key, tmp_path)
        except Exception as e:
            print(f"⚠️ Session Edge TTS preview error: {e}")
            QMessageBox.warning(
                self,
                "Edge TTS",
                (
                    "Не удалось подключиться к онлайн TTS. "
                    "Проверьте интернет/DNS/фаервол и повторите.\n\n"
                    f"Ошибка: {str(e)}"
                ),
            )

    def _play_and_cache_session_tts_preview(self, cache_key, tmp_path):
        if not tmp_path or not os.path.exists(tmp_path):
            return
        self._session_tts_preview_cache[cache_key] = tmp_path
        if cache_key in self._session_tts_preview_cache_order:
            self._session_tts_preview_cache_order.remove(cache_key)
        self._session_tts_preview_cache_order.append(cache_key)

        while len(self._session_tts_preview_cache_order) > 4:
            old_key = self._session_tts_preview_cache_order.pop(0)
            old_path = self._session_tts_preview_cache.pop(old_key, None)
            if old_path and old_path != tmp_path:
                try:
                    if os.path.exists(old_path):
                        os.remove(old_path)
                except Exception:
                    pass

        self._play_preview_file(tmp_path)

    def _load_session_voice_files(self):
        engine = self.session_tts_engine_combo.currentData()
        language = self.session_tts_language_combo.currentData()

        self.session_tts_voice_combo.blockSignals(True)
        try:
            self.session_tts_voice_combo.clear()

            if engine == "system":
                self._load_session_system_voices(language)
            elif engine == "edge":
                self._load_session_edge_voices(language)

            if (
                hasattr(self, "_saved_session_voice_id")
                and self._saved_session_voice_id
            ):
                voice_idx = self.session_tts_voice_combo.findData(
                    self._saved_session_voice_id
                )
                if voice_idx >= 0:
                    self.session_tts_voice_combo.setCurrentIndex(voice_idx)
                    return

            if self.session_tts_voice_combo.count() > 0:
                self.session_tts_voice_combo.setCurrentIndex(0)
        finally:
            self.session_tts_voice_combo.blockSignals(False)

    def _load_session_system_voices(self, language):
        try:
            import pyttsx3

            engine = pyttsx3.init()
            voices = engine.getProperty("voices") or []

            def _voice_matches_language(voice, lang):
                name = str(getattr(voice, "name", "") or "").lower()
                vid = str(getattr(voice, "id", "") or "").lower()
                langs = []
                for item in getattr(voice, "languages", []) or []:
                    try:
                        if isinstance(item, bytes):
                            langs.append(item.decode(errors="ignore").lower())
                        else:
                            langs.append(str(item).lower())
                    except Exception:
                        continue
                lang_blob = " ".join(langs)

                if lang == "ru":
                    return (
                        "ru" in lang_blob
                        or "ru" in name
                        or "russian" in name
                        or "ru" in vid
                        or "pavel" in name
                        or "irina" in name
                        or "tatyana" in name
                        or "anna" in name
                        or "natalia" in name
                        or "yuri" in name
                        or "nikolai" in name
                        or "nicolai" in name
                    )

                if lang == "en":
                    return (
                        "en" in lang_blob
                        or "english" in name
                        or "en" in vid
                        or "zira" in name
                        or "david" in name
                        or "mark" in name
                        or "eva" in name
                    )

                return False

            for voice in voices:
                name = getattr(voice, "name", "Voice")
                vid = getattr(voice, "id", "")
                if _voice_matches_language(voice, language):
                    self.session_tts_voice_combo.addItem(name, vid)

            if self.session_tts_voice_combo.count() == 0:
                for voice in voices:
                    name = getattr(voice, "name", "Voice")
                    vid = getattr(voice, "id", "")
                    self.session_tts_voice_combo.addItem(name, vid)

            engine.stop()
        except Exception as e:
            print(f"⚠️ Ошибка загрузки системных голосов (session): {e}")

    def _load_session_edge_voices(self, language):
        if language == "ru":
            voices = [
                ("ru-RU-DmitryNeural", "[RU-M] Dmitry (male)"),
                ("ru-RU-SvetlanaNeural", "[RU-F] Svetlana (female)"),
                ("en-US-AndrewMultilingualNeural", "[RU-M] Andrew (accented)"),
                ("en-US-AvaMultilingualNeural", "[RU-F] Ava (accented)"),
                ("en-US-EmmaMultilingualNeural", "[RU-F] Emma (accented)"),
                ("en-US-BrianMultilingualNeural", "[RU-M] Brian (accented)"),
                ("en-AU-WilliamMultilingualNeural", "[RU-M] William (accented)"),
            ]
        else:
            voices = [
                ("en-US-GuyNeural", "[EN-M] Guy (male)"),
                ("en-US-JennyNeural", "[EN-F] Jenny (female)"),
                ("en-US-AriaNeural", "[EN-F] Aria (female)"),
                ("en-US-BrianNeural", "[EN-M] Brian (male)"),
                ("en-GB-RyanNeural", "[EN-M] Ryan (male, UK)"),
                ("en-GB-SoniaNeural", "[EN-F] Sonia (female, UK)"),
            ]

        for voice_id, display_name in voices:
            self.session_tts_voice_combo.addItem(display_name, voice_id)

    def _on_session_tts_engine_changed(self, index):
        engine_id = self.session_tts_engine_combo.currentData()
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("session_tts_engine", engine_id)
        self._saved_session_voice_id = ""
        self._load_session_voice_files()

    def _on_session_tts_language_changed(self, index):
        language = self.session_tts_language_combo.currentData()
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("session_tts_language", language)
        self._saved_session_voice_id = ""
        self._load_session_voice_files()

    def _on_session_tts_voice_changed(self, index):
        voice_id = self.session_tts_voice_combo.currentData()
        voice_id = str(voice_id) if voice_id is not None else ""
        self._saved_session_voice_id = voice_id
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("session_tts_voice_id", voice_id)
        settings.sync()

    def _speak_system_tts(self, text, voice_id):
        """Проигрывает TTS через System TTS (pyttsx3)"""
        try:
            import pyttsx3

            engine = pyttsx3.init()
            if voice_id:
                engine.setProperty("voice", voice_id)
            engine.setProperty("volume", config.clamp_audio_volume(1.0))
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            print(f"⚠️ System TTS error: {e}")

    def _speak_edge_tts(self, text, voice_id, language):
        """Проигрывает TTS через Edge TTS"""
        try:
            import asyncio
            import tempfile
            import edge_tts
            from PyQt6.QtCore import QUrl
            from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

            # Проверяем и устанавливаем voice_id с fallback
            if not voice_id:
                voice_id = (
                    "ru-RU-DmitryNeural" if language == "ru" else "en-US-GuyNeural"
                )

            async def generate_audio():
                with tempfile.NamedTemporaryFile(
                    suffix=".mp3", delete=False
                ) as tmp_file:
                    tmp_path = tmp_file.name

                communicate = edge_tts.Communicate(text, voice_id)
                await communicate.save(tmp_path)
                return tmp_path

            # Генерируем аудио синхронно
            tmp_path = asyncio.run(generate_audio())

            import os

            if os.path.exists(tmp_path):
                pass
            else:
                return

            # Проигрывание выполняем в UI-потоке
            QTimer.singleShot(0, lambda p=tmp_path: self._play_preview_file(p))

            # Временные файлы будут автоматически удалены системой

        except Exception as e:
            print(f"⚠️ Edge TTS error: {e}")
            QTimer.singleShot(
                0,
                lambda msg=str(e): QMessageBox.warning(
                    self,
                    "Edge TTS",
                    (
                        "Не удалось подключиться к онлайн TTS. "
                        "Проверьте интернет/DNS/фаервол и повторите.\n\n"
                        f"Ошибка: {msg}"
                    ),
                ),
            )

    def _play_preview_file(self, tmp_path):
        try:
            if not tmp_path or not os.path.exists(tmp_path):
                return
            self.preview_player.stop()
            self.preview_player.setSource(QUrl())
            self.preview_output.setVolume(config.clamp_audio_volume(1.0))
            self.preview_player.setSource(QUrl.fromLocalFile(tmp_path))
            self.preview_player.play()
        except Exception as e:
            print(f"⚠️ Preview playback error: {e}")

    # --- Методы для TTS таймфреймов ---

    def _on_tf_tts_engine_changed(self, index):
        """Обработчик смены TTS движка для таймфреймов"""
        engine_id = self.tf_tts_engine_combo.currentData()
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("tf_tts_engine", engine_id)
        self._saved_tf_voice_id = ""
        self._load_tf_voice_files()

    def _on_tf_tts_language_changed(self, index):
        """Обработчик смены языка для таймфреймов"""
        language = self.tf_tts_language_combo.currentData()
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("tf_tts_language", language)
        self._saved_tf_voice_id = ""
        self._load_tf_voice_files()

    def _on_tf_tts_voice_changed(self, index):
        """Обработчик смены голоса TTS для таймфреймов"""
        voice_id = self.tf_tts_voice_combo.currentData()
        voice_id = str(voice_id) if voice_id is not None else ""
        self._saved_tf_voice_id = voice_id
        settings = QSettings("MyTradeTools", "TF-Alerter")
        settings.setValue("tf_tts_voice_id", voice_id)
        settings.sync()

    def _play_tf_tts_test(self):
        """Проигрывает тестовое TTS сообщение для таймфреймов"""
        try:
            import threading

            engine_type = self.tf_tts_engine_combo.currentData()
            language = self.tf_tts_language_combo.currentData()
            voice_id = self.tf_tts_voice_combo.currentData()

            # Тестовые сообщения для таймфреймов
            test_messages = {
                "ru": "Пять минут",
                "en": "Five minutes",
            }

            test_text = test_messages.get(language, test_messages["en"])

            if engine_type == "edge":
                self._speak_edge_tts(test_text, voice_id, language)
                return

            def speak_thread():
                self._speak_system_tts(test_text, voice_id)

            thread = threading.Thread(target=speak_thread, daemon=True)
            thread.start()
        except Exception as e:
            print(f"⚠️ Ошибка проигрывания TTS таймфрейма: {e}")

    def _load_tf_voice_files(self):
        """Загружает список голосов для таймфреймов в зависимости от выбранного TTS движка"""
        engine = self.tf_tts_engine_combo.currentData()
        language = self.tf_tts_language_combo.currentData()

        self.tf_tts_voice_combo.blockSignals(True)
        try:
            self.tf_tts_voice_combo.clear()

            if engine == "system":
                self._load_tf_system_voices(language)
            elif engine == "edge":
                self._load_tf_edge_voices(language)

            # Восстанавливаем сохраненный голос
            if hasattr(self, "_saved_tf_voice_id") and self._saved_tf_voice_id:
                voice_idx = self.tf_tts_voice_combo.findData(self._saved_tf_voice_id)
                if voice_idx >= 0:
                    self.tf_tts_voice_combo.setCurrentIndex(voice_idx)
                    return

            # Если голос не найден, выбираем первый
            if self.tf_tts_voice_combo.count() > 0:
                self.tf_tts_voice_combo.setCurrentIndex(0)
        finally:
            self.tf_tts_voice_combo.blockSignals(False)

    def _load_tf_system_voices(self, language):
        """Загружает системные TTS голоса для таймфреймов"""
        try:
            import pyttsx3

            engine = pyttsx3.init()
            voices = engine.getProperty("voices") or []

            def _voice_matches_language(voice, lang):
                name = str(getattr(voice, "name", "") or "").lower()
                vid = str(getattr(voice, "id", "") or "").lower()
                langs = []
                for item in getattr(voice, "languages", []) or []:
                    try:
                        if isinstance(item, bytes):
                            langs.append(item.decode(errors="ignore").lower())
                        else:
                            langs.append(str(item).lower())
                    except Exception:
                        continue
                lang_blob = " ".join(langs)

                if lang == "ru":
                    return (
                        "ru" in lang_blob
                        or "ru" in name
                        or "russian" in name
                        or "ru" in vid
                        or "pavel" in name
                        or "irina" in name
                        or "tatyana" in name
                        or "anna" in name
                        or "natalia" in name
                        or "yuri" in name
                        or "nikolai" in name
                        or "nicolai" in name
                    )

                if lang == "en":
                    return (
                        "en" in lang_blob
                        or "english" in name
                        or "en" in vid
                        or "zira" in name
                        or "david" in name
                        or "mark" in name
                        or "eva" in name
                    )

                return False

            for voice in voices:
                name = getattr(voice, "name", "Voice")
                vid = getattr(voice, "id", "")

                if _voice_matches_language(voice, language):
                    self.tf_tts_voice_combo.addItem(name, vid)

            if self.tf_tts_voice_combo.count() == 0:
                for voice in voices:
                    name = getattr(voice, "name", "Voice")
                    vid = getattr(voice, "id", "")
                    self.tf_tts_voice_combo.addItem(name, vid)

            engine.stop()
        except Exception as e:
            print(f"⚠️ Ошибка загрузки системных голосов для таймфреймов: {e}")

    def _load_tf_edge_voices(self, language):
        """Загружает Edge TTS голоса для таймфреймов"""
        if language == "ru":
            # Русские голоса Edge TTS
            voices = [
                ("ru-RU-DmitryNeural", "[RU-M] Дмитрий (мужской)"),
                ("ru-RU-SvetlanaNeural", "[RU-F] Светлана (женский)"),
                ("en-US-AndrewMultilingualNeural", "[RU-M] Andrew (accented)"),
                ("en-US-AvaMultilingualNeural", "[RU-F] Ava (accented)"),
                ("en-US-EmmaMultilingualNeural", "[RU-F] Emma (accented)"),
                ("en-US-BrianMultilingualNeural", "[RU-M] Brian (accented)"),
                ("en-AU-WilliamMultilingualNeural", "[RU-M] William (accented)"),
            ]
        else:  # en
            # Английские голоса Edge TTS
            voices = [
                ("en-US-GuyNeural", "[EN-M] Guy (male)"),
                ("en-US-JennyNeural", "[EN-F] Jenny (female)"),
                ("en-US-AriaNeural", "[EN-F] Aria (female)"),
                ("en-US-BrianNeural", "[EN-M] Brian (male)"),
                ("en-GB-RyanNeural", "[EN-M] Ryan (male, UK)"),
                ("en-GB-SoniaNeural", "[EN-F] Sonia (female, UK)"),
            ]

        for voice_id, display_name in voices:
            self.tf_tts_voice_combo.addItem(display_name, voice_id)

    def _toggle_tf_tts(self, tf_key):
        """Переключает режим TTS/Sound для конкретного таймфрейма"""
        settings = QSettings("MyTradeTools", "TF-Alerter")
        tf_key_prefixed = f"{tf_key}_use_tts"
        current_state = settings.value(tf_key_prefixed, False, type=bool)
        new_state = not current_state
        settings.setValue(tf_key_prefixed, new_state)
        settings.sync()
        self._update_tf_tts_toggle_icon(tf_key, new_state)

    def _update_tf_tts_toggle_icon(self, tf_key, use_tts):
        """Обновляет иконку кнопки переключения TTS/Sound"""
        if tf_key not in self.tf_tts_toggles:
            return
        btn = self.tf_tts_toggles[tf_key]
        if use_tts:
            btn.setText("🗣️")  # Иконка TTS
            btn.setToolTip("Сейчас: TTS. Нажмите для переключения на звук")
        else:
            btn.setText("🔊")  # Иконка звука
            btn.setToolTip("Сейчас: Звук. Нажмите для переключения на TTS")

    def _load_tf_tts_toggle_states(self):
        """Загружает и применяет сохраненные состояния переключателей TTS"""
        settings = QSettings("MyTradeTools", "TF-Alerter")
        for tf_key in self.tf_tts_toggles.keys():
            tf_key_prefixed = f"{tf_key}_use_tts"
            use_tts = settings.value(tf_key_prefixed, False, type=bool)
            self._update_tf_tts_toggle_icon(tf_key, use_tts)

    # --- Конец методов для TTS таймфреймов ---

    def _play_sound(self, tf_key, kind):
        if kind == "main":
            filename = config.TIMEFRAMES.get(tf_key, {}).get("file", "")
        elif kind == "tick":
            filename = config.SOUND_TICK_BY_TF.get(tf_key, "")
        else:
            filename = config.SOUND_TRANSITION_BY_TF.get(tf_key, "")

        if not filename:
            print(f"⚠️ Нет названия файла для {kind}")
            return

        path = config.get_sound_path(kind, filename)
        if not path or not os.path.exists(path):
            print(f"⚠️ Файл не существует: {path}")
            return

        self._refresh_preview_audio_device()

        # Громкость предпрослушивания с headroom для предотвращения перегруза на пиках.
        target_volume = config.clamp_audio_volume(1.0)
        self.preview_output.setVolume(target_volume)
        print(f"🔊 Воспроизведение {kind}: {filename}")
        print(f"   Громкость установлена: {target_volume * 100:.0f}%")
        print(f"   Путь: {path}")

        # Полностью останавливаем и очищаем предыдущий звук
        self.preview_player.stop()
        self.preview_player.setSource(QUrl())  # Очищаем источник

        # Устанавливаем новый звук и проигрываем
        self.preview_player.setSource(QUrl.fromLocalFile(path))
        self.preview_player.play()

    def load_current_settings(self):
        """Загружает текущие настройки"""
        settings = QSettings("MyTradeTools", "TF-Alerter")

        # Язык
        saved_lang = settings.value("language", "RU")
        self.lang_combo.setCurrentText(saved_lang)

        # Масштаб
        saved_scale = settings.value("interface_scale_text", "100%")
        if saved_scale == "80%":
            saved_scale = "90%"
        self.scale_combo.setCurrentText(saved_scale)

        # Горячая клавиша
        saved_hotkey = settings.value("hotkey", "")
        saved_codes = settings.value("hotkey_codes", "")
        if saved_codes:
            try:
                self.captured_hotkey_codes = [
                    int(x) for x in str(saved_codes).split(",") if x.strip().isdigit()
                ]
            except Exception:
                self.captured_hotkey_codes = None
        else:
            self.captured_hotkey_codes = None
        # Игнорируем placeholder текст
        invalid_texts = [
            "Не задана",
            "Нажмите клавишу...",
            "Not set",
            "Press a key...",
            "",
        ]
        # Показываем сохранённый текст только если есть коды (иначе он неработоспособен)
        if (
            saved_hotkey
            and saved_hotkey not in invalid_texts
            and self.captured_hotkey_codes is not None
            and len(self.captured_hotkey_codes) > 0
        ):
            self.hotkey_input.setText(saved_hotkey)
        else:
            self.hotkey_input.setText(self.translations[saved_lang]["not_set"])

        # Обновляем текст на кнопках звуков (читаем из QSettings, а не из config)
        for tf_key in config.TIMEFRAMES.keys():
            # Используем разные имена для 1M в QSettings (1Month вместо 1M)
            # чтобы избежать case-insensitive конфликтов в Windows реестре
            qsettings_key = tf_key.replace("1M", "1Month") if tf_key == "1M" else tf_key

            main_name = settings.value(
                f"sound_main_{qsettings_key}", config.TIMEFRAMES[tf_key]["file"]
            )
            tick_name = settings.value(
                f"sound_tick_{qsettings_key}", config.SOUND_TICK_BY_TF.get(tf_key, "")
            )
            trans_name = settings.value(
                f"sound_transition_{qsettings_key}",
                config.SOUND_TRANSITION_BY_TF.get(tf_key, ""),
            )

            main_name = config.sanitize_sound_filename(
                main_name, config.TIMEFRAMES[tf_key]["file"]
            )
            tick_name = config.sanitize_sound_filename(
                tick_name, config.SOUND_TICK_BY_TF.get(tf_key, "")
            )
            trans_name = config.sanitize_sound_filename(
                trans_name, config.SOUND_TRANSITION_BY_TF.get(tf_key, "")
            )

            if (tf_key, "main") in self.sound_buttons:
                self.sound_buttons[(tf_key, "main")].setText(
                    os.path.basename(main_name) if main_name else ""
                )
            if (tf_key, "tick") in self.sound_buttons:
                self.sound_buttons[(tf_key, "tick")].setText(
                    os.path.basename(tick_name) if tick_name else ""
                )
            if (tf_key, "transition") in self.sound_buttons:
                self.sound_buttons[(tf_key, "transition")].setText(
                    os.path.basename(trans_name) if trans_name else ""
                )

        # Настройки фандинга (звук и TTS)
        self.funding_sound_check.setChecked(
            settings.value("funding_sound_enabled", True, type=bool)
        )
        self.funding_tts_check.setChecked(
            settings.value("funding_tts_enabled", True, type=bool)
        )
        self.funding_sound_file = settings.value(
            "funding_sound_file", config.SOUND_FUNDING_ALERT
        )
        self.funding_sound_file = config.sanitize_sound_filename(
            self.funding_sound_file,
            config.SOUND_FUNDING_ALERT,
        )
        self.funding_sound_btn.setText(
            os.path.basename(self.funding_sound_file)
            if self.funding_sound_file
            else config.SOUND_FUNDING_ALERT
        )

        # Если внешний Edge TTS сервис уже падал, принудительно возвращаемся на стабильную Windows TTS.
        if settings.value("edge_tts_service_blocked", False, type=bool):
            settings.setValue("funding_tts_engine", "system")
            settings.setValue("listing_tts_engine", "system")
            settings.setValue("session_tts_engine", "system")
            settings.setValue("tf_tts_engine", "system")

        # Загружаем сохраненные TTS настройки БЕЗ активации сигналов
        saved_engine = settings.value("funding_tts_engine", "system")
        engine_idx = self.funding_tts_engine_combo.findData(saved_engine)
        if engine_idx >= 0:
            self.funding_tts_engine_combo.blockSignals(True)
            self.funding_tts_engine_combo.setCurrentIndex(engine_idx)
            self.funding_tts_engine_combo.blockSignals(False)

        saved_language = settings.value("funding_tts_language", "ru")
        lang_idx = self.funding_tts_language_combo.findData(saved_language)
        if lang_idx >= 0:
            self.funding_tts_language_combo.blockSignals(True)
            self.funding_tts_language_combo.setCurrentIndex(lang_idx)
            self.funding_tts_language_combo.blockSignals(False)

        # Загружаем сохраненный ID голоса перед загрузкой списка
        # Fallback на старый/параллельный ключ для совместимости
        saved_voice_id = settings.value("funding_tts_voice_id", "")
        legacy_voice_id = settings.value("funding_voice_file", "")
        # Legacy используем только если новый ключ пустой
        if not saved_voice_id:
            saved_voice_id = legacy_voice_id
        self._saved_voice_id = str(saved_voice_id) if saved_voice_id is not None else ""
        if self._saved_voice_id:
            settings.setValue("funding_tts_voice_id", self._saved_voice_id)
        # Если выбран корректный новый ключ - очищаем legacy
        if self._saved_voice_id:
            settings.remove("funding_voice_file")

        # Теперь загружаем голоса с учетом выбранного движка и языка
        self._load_voice_files()

        # Настройки листинга (звук и TTS)
        self.listing_sound_check.setChecked(
            settings.value("listing_sound_enabled", True, type=bool)
        )
        self.listing_tts_check.setChecked(
            settings.value("listing_tts_enabled", True, type=bool)
        )
        self.listing_sound_file = settings.value(
            "listing_sound_file", config.SOUND_LISTING_ALERT
        )
        self.listing_sound_file = config.sanitize_sound_filename(
            self.listing_sound_file,
            config.SOUND_LISTING_ALERT,
        )
        self.listing_sound_btn.setText(
            os.path.basename(self.listing_sound_file)
            if self.listing_sound_file
            else config.SOUND_LISTING_ALERT
        )

        saved_listing_engine = settings.value("listing_tts_engine", "system")
        listing_engine_idx = self.listing_tts_engine_combo.findData(
            saved_listing_engine
        )
        if listing_engine_idx >= 0:
            self.listing_tts_engine_combo.blockSignals(True)
            self.listing_tts_engine_combo.setCurrentIndex(listing_engine_idx)
            self.listing_tts_engine_combo.blockSignals(False)

        saved_listing_language = settings.value("listing_tts_language", "ru")
        listing_lang_idx = self.listing_tts_language_combo.findData(
            saved_listing_language
        )
        if listing_lang_idx >= 0:
            self.listing_tts_language_combo.blockSignals(True)
            self.listing_tts_language_combo.setCurrentIndex(listing_lang_idx)
            self.listing_tts_language_combo.blockSignals(False)

        saved_listing_voice_id = settings.value("listing_tts_voice_id", "")
        self._saved_listing_voice_id = (
            str(saved_listing_voice_id) if saved_listing_voice_id is not None else ""
        )
        if self._saved_listing_voice_id:
            settings.setValue("listing_tts_voice_id", self._saved_listing_voice_id)

        self._load_listing_voice_files()

        # Настройки сессий (только TTS)
        self.session_tts_check.setChecked(
            settings.value("session_tts_enabled", True, type=bool)
        )

        saved_session_engine = settings.value("session_tts_engine", "system")
        session_engine_idx = self.session_tts_engine_combo.findData(saved_session_engine)
        if session_engine_idx >= 0:
            self.session_tts_engine_combo.blockSignals(True)
            self.session_tts_engine_combo.setCurrentIndex(session_engine_idx)
            self.session_tts_engine_combo.blockSignals(False)

        saved_session_language = settings.value("session_tts_language", "ru")
        session_lang_idx = self.session_tts_language_combo.findData(
            saved_session_language
        )
        if session_lang_idx >= 0:
            self.session_tts_language_combo.blockSignals(True)
            self.session_tts_language_combo.setCurrentIndex(session_lang_idx)
            self.session_tts_language_combo.blockSignals(False)

        saved_session_voice_id = settings.value("session_tts_voice_id", "")
        self._saved_session_voice_id = (
            str(saved_session_voice_id) if saved_session_voice_id is not None else ""
        )
        if self._saved_session_voice_id:
            settings.setValue("session_tts_voice_id", self._saved_session_voice_id)

        self._load_session_voice_files()

        # Загружаем TTS настройки для таймфреймов
        self.tf_tts_check.setChecked(settings.value("tf_tts_enabled", False, type=bool))

        saved_tf_engine = settings.value("tf_tts_engine", "system")
        tf_engine_idx = self.tf_tts_engine_combo.findData(saved_tf_engine)
        if tf_engine_idx >= 0:
            self.tf_tts_engine_combo.blockSignals(True)
            self.tf_tts_engine_combo.setCurrentIndex(tf_engine_idx)
            self.tf_tts_engine_combo.blockSignals(False)

        saved_tf_language = settings.value("tf_tts_language", "ru")
        tf_lang_idx = self.tf_tts_language_combo.findData(saved_tf_language)
        if tf_lang_idx >= 0:
            self.tf_tts_language_combo.blockSignals(True)
            self.tf_tts_language_combo.setCurrentIndex(tf_lang_idx)
            self.tf_tts_language_combo.blockSignals(False)

        saved_tf_voice_id = settings.value("tf_tts_voice_id", "")
        self._saved_tf_voice_id = (
            str(saved_tf_voice_id) if saved_tf_voice_id is not None else ""
        )
        if self._saved_tf_voice_id:
            settings.setValue("tf_tts_voice_id", self._saved_tf_voice_id)

        # Загружаем голоса для таймфреймов
        self._load_tf_voice_files()

        # Загружаем состояния переключателей TTS/Sound для таймфреймов
        self._load_tf_tts_toggle_states()

        # Сбрасываем режим захвата
        self.capturing_hotkey = False

    def change_dialog_language(self, lang):
        """Изменяет язык всех элементов диалога"""
        t = self.translations[lang]

        self.title.setText(t["title"])
        self.lang_label.setText(t["language"])
        self.scale_label.setText(t["scale"])
        self.hotkey_label.setText(t["hotkey"])
        self.clear_hotkey_btn.setText(t["clear"])
        self.cancel_btn.setText(t["cancel"])
        self.save_btn.setText(t["save"])
        self.sounds_title.setText(t["sounds_title"])
        self.header_tf.setText(t["tf_col"])
        self.header_voice.setText(t["voice_col"])
        self.header_tick.setText(t["tick_col"])
        self.header_transition.setText(t["transition_col"])
        self.about_btn.setText(t["about_btn"])
        self.donate_btn.setText(t["donate_btn"])
        self.funding_title.setText(t["funding_title"])
        self.funding_sound_check.setText(t["funding_sound_enabled"])
        self.funding_tts_check.setText(t["funding_tts_enabled"])
        self.funding_sound_label_static.setText(t["funding_sound_file"])
        self.funding_tts_engine_label.setText(t["funding_tts_engine"])
        self.funding_tts_language_label.setText(t["funding_tts_language"])
        self.funding_tts_voice_label.setText(t["funding_tts_voice"])
        self._refresh_funding_combo_texts(lang)

        self.listing_title.setText(t["listing_title"])
        self.listing_sound_check.setText(t["listing_sound_enabled"])
        self.listing_tts_check.setText(t["listing_tts_enabled"])
        self.listing_sound_label_static.setText(t["listing_sound_file"])
        self.listing_tts_engine_label.setText(t["listing_tts_engine"])
        self.listing_tts_language_label.setText(t["listing_tts_language"])
        self.listing_tts_voice_label.setText(t["listing_tts_voice"])
        self._refresh_listing_combo_texts(lang)

        self.session_title.setText(t["session_title"])
        self.session_tts_check.setText(t["session_tts_enabled"])
        self.session_tts_engine_label.setText(t["session_tts_engine"])
        self.session_tts_language_label.setText(t["session_tts_language"])
        self.session_tts_voice_label.setText(t["session_tts_voice"])
        self._refresh_session_combo_texts(lang)

        # Обновляем метки TTS для таймфреймов
        if hasattr(self, "tf_tts_check"):
            self.tf_tts_title.setText(t["tf_tts_title"])
            self.tf_tts_check.setText(t["tf_tts_enabled"])
            self.tf_tts_engine_label.setText(t["tf_tts_engine"])
            self.tf_tts_language_label.setText(t["tf_tts_language"])
            self.tf_tts_voice_label.setText(t["tf_tts_voice"])
            self._refresh_tf_combo_texts(lang)

        # Обновляем названия таймфреймов
        for tf_key, label in self.tf_labels.items():
            label.setText(config.get_timeframe_label(tf_key, lang))

        # Обновляем placeholder тексты не привращаю текст по-быстрому
        current_hotkey = self.hotkey_input.text()
        invalid_texts = ["Не задана", "Нажмите клавишу...", "Not set", "Press a key..."]
        if current_hotkey in invalid_texts:
            self.hotkey_input.setText(t["not_set"])

    def _refresh_funding_combo_texts(self, lang):
        """Обновляет отображаемые тексты в комбобоксах TTS без изменения data."""
        t = self.translations[lang]

        system_idx = self.funding_tts_engine_combo.findData("system")
        if system_idx >= 0:
            self.funding_tts_engine_combo.setItemText(
                system_idx, t["funding_tts_engine_system"]
            )
        edge_idx = self.funding_tts_engine_combo.findData("edge")
        if edge_idx >= 0:
            self.funding_tts_engine_combo.setItemText(
                edge_idx, t["funding_tts_engine_edge"]
            )

        ru_idx = self.funding_tts_language_combo.findData("ru")
        if ru_idx >= 0:
            self.funding_tts_language_combo.setItemText(
                ru_idx, t["funding_tts_lang_ru"]
            )
        en_idx = self.funding_tts_language_combo.findData("en")
        if en_idx >= 0:
            self.funding_tts_language_combo.setItemText(
                en_idx, t["funding_tts_lang_en"]
            )

    def _refresh_tf_combo_texts(self, lang):
        """Обновляет отображаемые тексты в комбобоксах TTS таймфреймов без изменения data."""
        t = self.translations[lang]

        # Обновляем тексты для движка
        system_idx = self.tf_tts_engine_combo.findData("system")
        if system_idx >= 0:
            self.tf_tts_engine_combo.setItemText(
                system_idx, t["funding_tts_engine_system"]
            )
        edge_idx = self.tf_tts_engine_combo.findData("edge")
        if edge_idx >= 0:
            self.tf_tts_engine_combo.setItemText(edge_idx, t["funding_tts_engine_edge"])

        # Обновляем тексты для языка
        ru_idx = self.tf_tts_language_combo.findData("ru")
        if ru_idx >= 0:
            self.tf_tts_language_combo.setItemText(ru_idx, t["funding_tts_lang_ru"])
        en_idx = self.tf_tts_language_combo.findData("en")
        if en_idx >= 0:
            self.tf_tts_language_combo.setItemText(en_idx, t["funding_tts_lang_en"])

    def _refresh_listing_combo_texts(self, lang):
        """Обновляет отображаемые тексты в комбобоксах TTS листинга без изменения data."""
        t = self.translations[lang]

        system_idx = self.listing_tts_engine_combo.findData("system")
        if system_idx >= 0:
            self.listing_tts_engine_combo.setItemText(
                system_idx, t["listing_tts_engine_system"]
            )
        edge_idx = self.listing_tts_engine_combo.findData("edge")
        if edge_idx >= 0:
            self.listing_tts_engine_combo.setItemText(
                edge_idx, t["listing_tts_engine_edge"]
            )

        ru_idx = self.listing_tts_language_combo.findData("ru")
        if ru_idx >= 0:
            self.listing_tts_language_combo.setItemText(
                ru_idx, t["listing_tts_lang_ru"]
            )
        en_idx = self.listing_tts_language_combo.findData("en")
        if en_idx >= 0:
            self.listing_tts_language_combo.setItemText(
                en_idx, t["listing_tts_lang_en"]
            )

    def _refresh_session_combo_texts(self, lang):
        """Обновляет отображаемые тексты в комбобоксах TTS сессий без изменения data."""
        t = self.translations[lang]

        system_idx = self.session_tts_engine_combo.findData("system")
        if system_idx >= 0:
            self.session_tts_engine_combo.setItemText(
                system_idx, t["session_tts_engine_system"]
            )
        edge_idx = self.session_tts_engine_combo.findData("edge")
        if edge_idx >= 0:
            self.session_tts_engine_combo.setItemText(
                edge_idx, t["session_tts_engine_edge"]
            )

        ru_idx = self.session_tts_language_combo.findData("ru")
        if ru_idx >= 0:
            self.session_tts_language_combo.setItemText(ru_idx, t["session_tts_lang_ru"])
        en_idx = self.session_tts_language_combo.findData("en")
        if en_idx >= 0:
            self.session_tts_language_combo.setItemText(en_idx, t["session_tts_lang_en"])

    def start_capture(self):
        """Начинает захват клавиши"""
        self._pressed_vks.clear()
        self._pressed_names.clear()
        self._saw_non_modifier = False
        self._last_modifiers_vks.clear()

        self.capturing_hotkey = True
        current_lang = self.lang_combo.currentText()
        self.hotkey_input.setText(self.translations[current_lang]["capturing"])
        # Устанавливаем фокус на диалог, а не на кнопку
        self.setFocus()
        # Гарантируем что все события клавиатуры придут сюда
        try:
            self.grabKeyboard()
        except Exception:
            pass

    def _vk_to_name(self, vk):
        try:
            scan = int(self._user32.MapVirtualKeyW(int(vk), self._MAPVK_VK_TO_VSC_EX))
            if scan == 0:
                return str(vk)
            lparam = (scan & 0xFF) << 16
            buf = ctypes.create_unicode_buffer(64)
            if self._user32.GetKeyNameTextW(lparam, buf, 64) > 0:
                return buf.value
        except Exception:
            pass
        return str(vk)

    def keyPressEvent(self, event: QKeyEvent):
        """Обработка нажатия клавиш"""
        if not self.capturing_hotkey:
            super().keyPressEvent(event)
            return

        if event.isAutoRepeat():
            return

        key = event.key()
        current_lang = self.lang_combo.currentText()

        # ESC отменяет ввод
        if key == Qt.Key.Key_Escape:
            self.hotkey_input.setText(self.translations[current_lang]["not_set"])
            self.capturing_hotkey = False
            return

        vk = int(event.nativeVirtualKey())
        if vk <= 0:
            return

        self._pressed_vks.add(vk)
        if vk not in self._pressed_names:
            self._pressed_names[vk] = self._vk_to_name(vk)

        if vk in self._VK_MODIFIERS:
            self._last_modifiers_vks = set(self._pressed_vks)
            return

        self._saw_non_modifier = True
        self._finalize_hotkey(list(self._pressed_vks))

    def keyReleaseEvent(self, event: QKeyEvent):
        if not self.capturing_hotkey:
            super().keyReleaseEvent(event)
            return

        if event.isAutoRepeat():
            return

        vk = int(event.nativeVirtualKey())
        if vk > 0:
            self._pressed_vks.discard(vk)

        if (
            not self._saw_non_modifier
            and not self._pressed_vks
            and self._last_modifiers_vks
        ):
            self._finalize_hotkey(list(self._last_modifiers_vks))

    def _is_modifier_name(self, name):
        if not name:
            return False
        return name in {
            "Left Ctrl",
            "Right Ctrl",
            "Ctrl",
            "Left Alt",
            "Right Alt",
            "Alt",
            "Alt Gr",
            "Left Shift",
            "Right Shift",
            "Shift",
            "Left Windows",
            "Right Windows",
            "Windows",
        }

    def _format_key_name(self, name):
        if not name:
            return ""
        return " ".join(part.capitalize() for part in name.split())

    def _vk_display_name(self, vk):
        if vk in self._VK_DISPLAY:
            return self._VK_DISPLAY[vk]
        name = self._pressed_names.get(vk)
        if name:
            return name
        return self._vk_to_name(vk)

    def _build_hotkey_display(self, scan_codes):
        vks = [int(x) for x in scan_codes if isinstance(x, int) or str(x).isdigit()]
        modifier_order_vks = [
            0xA2,  # LCtrl
            0xA3,  # RCtrl
            0x11,  # Ctrl
            0xA4,  # LAlt
            0xA5,  # RAlt
            0x12,  # Alt
            0xA0,  # LShift
            0xA1,  # RShift
            0x10,  # Shift
            0x5B,  # LWin
            0x5C,  # RWin
        ]
        mods = [vk for vk in vks if vk in self._VK_MODIFIERS]
        others = [vk for vk in vks if vk not in self._VK_MODIFIERS]

        ordered = [vk for vk in modifier_order_vks if vk in mods]
        ordered += others

        parts = [self._vk_display_name(vk) for vk in ordered]
        parts = [self._format_key_name(p) for p in parts if p]
        return "+".join(parts)

    def _finalize_hotkey(self, scan_codes):
        if not scan_codes:
            return
        display = self._build_hotkey_display(scan_codes)
        if display:
            self.hotkey_input.setText(display)
            self.captured_hotkey_codes = list(scan_codes)
            self.capturing_hotkey = False

        if not self.capturing_hotkey:
            try:
                self.releaseKeyboard()
            except Exception:
                pass

    def clear_hotkey(self):
        """Очищает горячую клавишу"""
        current_lang = self.lang_combo.currentText()
        self.hotkey_input.setText(self.translations[current_lang]["not_set"])
        self.capturing_hotkey = False
        self.captured_hotkey_codes = None
        try:
            self.releaseKeyboard()
        except Exception:
            pass

    def save_and_close(self):
        """Сохраняет настройки и закрывает окно"""
        settings = QSettings("MyTradeTools", "TF-Alerter")

        # Сохраняем язык
        settings.setValue("language", self.lang_combo.currentText())

        # Сохраняем масштаб
        settings.setValue("interface_scale_text", self.scale_combo.currentText())

        # Сохраняем горячую клавишу
        hotkey_text = self.hotkey_input.text()
        # Игнорируем placeholder текст
        invalid_texts = [
            "Не задана",
            "Нажмите клавишу...",
            "Not set",
            "Press a key...",
            "",
        ]
        hotkey = "" if hotkey_text in invalid_texts else hotkey_text
        settings.setValue("hotkey", hotkey)
        if hotkey and self.captured_hotkey_codes is not None:
            settings.setValue(
                "hotkey_codes",
                ",".join(str(sc) for sc in self.captured_hotkey_codes),
            )
        else:
            settings.remove("hotkey_codes")

        # Применяем язык в родительском окне (только если изменился)
        if self.parent:
            current_lang = self.parent.ui.lang_sel.currentText()
            new_lang = self.lang_combo.currentText()

            if current_lang != new_lang:
                self.parent.ui.lang_sel.setCurrentText(new_lang)
                self.parent.ui.change_language(new_lang)

            # Применяем масштаб интерфейса
            new_scale = self.scale_combo.currentText()
            self.parent.apply_interface_scale(new_scale)

        # Сохраняем состояние переключателей звуков по колонкам
        settings.setValue("sounds_voice_enabled", self.check_voice_enabled.isChecked())
        settings.setValue("sounds_tick_enabled", self.check_tick_enabled.isChecked())
        settings.setValue(
            "sounds_transition_enabled",
            self.check_transition_enabled.isChecked(),
        )

        # Сохраняем настройки фандинга
        settings.setValue("funding_sound_enabled", self.funding_sound_check.isChecked())
        settings.setValue("funding_tts_enabled", self.funding_tts_check.isChecked())
        settings.setValue(
            "funding_tts_engine",
            self.funding_tts_engine_combo.currentData() or "system",
        )
        settings.setValue(
            "funding_tts_language",
            self.funding_tts_language_combo.currentData() or "ru",
        )
        selected_voice_id = (
            self.funding_tts_voice_combo.currentData()
            if self.funding_tts_voice_combo.count() > 0
            else ""
        )
        selected_voice_id = (
            str(selected_voice_id) if selected_voice_id is not None else ""
        )
        self._saved_voice_id = selected_voice_id
        settings.setValue("funding_tts_voice_id", selected_voice_id)
        settings.remove("funding_voice_file")

        funding_sound_file = str(getattr(self, "funding_sound_file", "") or "").strip()
        if not funding_sound_file:
            funding_sound_file = config.SOUND_FUNDING_ALERT
        settings.setValue("funding_sound_file", funding_sound_file)

        # Сохраняем настройки листинга
        settings.setValue("listing_sound_enabled", self.listing_sound_check.isChecked())
        settings.setValue("listing_tts_enabled", self.listing_tts_check.isChecked())
        settings.setValue(
            "listing_tts_engine",
            self.listing_tts_engine_combo.currentData() or "system",
        )
        settings.setValue(
            "listing_tts_language",
            self.listing_tts_language_combo.currentData() or "ru",
        )
        selected_listing_voice_id = (
            self.listing_tts_voice_combo.currentData()
            if self.listing_tts_voice_combo.count() > 0
            else ""
        )
        selected_listing_voice_id = (
            str(selected_listing_voice_id)
            if selected_listing_voice_id is not None
            else ""
        )
        self._saved_listing_voice_id = selected_listing_voice_id
        settings.setValue("listing_tts_voice_id", selected_listing_voice_id)

        listing_sound_file = str(getattr(self, "listing_sound_file", "") or "").strip()
        if not listing_sound_file:
            listing_sound_file = config.SOUND_LISTING_ALERT
        settings.setValue("listing_sound_file", listing_sound_file)

        # Сохраняем настройки сессий
        settings.setValue("session_tts_enabled", self.session_tts_check.isChecked())
        settings.setValue(
            "session_tts_engine",
            self.session_tts_engine_combo.currentData() or "system",
        )
        settings.setValue(
            "session_tts_language",
            self.session_tts_language_combo.currentData() or "ru",
        )
        selected_session_voice_id = (
            self.session_tts_voice_combo.currentData()
            if self.session_tts_voice_combo.count() > 0
            else ""
        )
        selected_session_voice_id = (
            str(selected_session_voice_id)
            if selected_session_voice_id is not None
            else ""
        )
        self._saved_session_voice_id = selected_session_voice_id
        settings.setValue("session_tts_voice_id", selected_session_voice_id)

        # Сохраняем настройки TTS для таймфреймов
        settings.setValue("tf_tts_enabled", self.tf_tts_check.isChecked())
        settings.setValue(
            "tf_tts_engine", self.tf_tts_engine_combo.currentData() or "system"
        )
        settings.setValue(
            "tf_tts_language", self.tf_tts_language_combo.currentData() or "ru"
        )
        selected_tf_voice_id = (
            self.tf_tts_voice_combo.currentData()
            if self.tf_tts_voice_combo.count() > 0
            else ""
        )
        selected_tf_voice_id = (
            str(selected_tf_voice_id) if selected_tf_voice_id is not None else ""
        )
        self._saved_tf_voice_id = selected_tf_voice_id
        settings.setValue("tf_tts_voice_id", selected_tf_voice_id)

        settings.sync()

        self.accept()

    def mousePressEvent(self, event):
        """Начало перетаскивания окна"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        """Перетаскивание окна"""
        if self.old_pos:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        """Окончание перетаскивания"""
        self.old_pos = None

    def _open_about(self):
        """Открыть диалог О программе из главного окна"""
        if self.parent and hasattr(self.parent, "open_about"):
            self.parent.open_about()

    def _open_donate(self):
        """Открыть диалог Пожертвований из главного окна"""
        if self.parent and hasattr(self.parent, "open_donate"):
            self.parent.open_donate()

    def closeEvent(self, event):
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        super().closeEvent(event)
