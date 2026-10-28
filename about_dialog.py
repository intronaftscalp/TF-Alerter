from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
)
from PyQt6.QtCore import Qt, QUrl, QSettings, QTimer
from PyQt6.QtGui import QDesktopServices, QFont
import config


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Переводы
        self.translations = {
            "RU": {
                "title": "О программе",
                "version": f"Версия {config.APP_VERSION}",
                "description": "TF-Alerter — приложение для трейдеров, которое отслеживает переходы таймфреймов, фандинги, листинги и торговые сессии в реальном времени и озвучивает важные события.",
                "developer": "Разработчик:",
                "smart_link_btn": "🔗 Smart Link",
            },
            "EN": {
                "title": "Info",
                "version": f"Version {config.APP_VERSION}",
                "description": "TF-Alerter is a trader app that tracks timeframe transitions, funding, listings, and trading sessions in real time, and speaks important alerts.",
                "developer": "Developer:",
                "smart_link_btn": "🔗 Smart Link",
            },
        }

        settings = QSettings("MyTradeTools", "TF-Alerter")
        self.current_lang = settings.value("language", "RU")
        self.t = self.translations[self.current_lang]
        self.setWindowTitle(self.t["title"])
        scale_text = settings.value("interface_scale_text", "100%")
        try:
            value = int(str(scale_text).replace("%", ""))
            factor = value / 100.0
        except Exception:
            factor = 1.0

        def s(px):
            return max(1, int(px * factor))

        self.setFixedSize(s(420), s(390))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Главный контейнер
        main_container = QFrame(self)
        main_container.setStyleSheet(
            f"""
            QFrame {{
                background-color: {config.COLORS['background']};
                border: 2px solid {config.COLORS['border']};
                border-radius: 10px;
            }}
        """
        )
        main_container.setGeometry(0, 0, s(420), s(390))

        layout = QVBoxLayout(main_container)
        layout.setContentsMargins(s(25), s(14), s(25), s(16))
        layout.setSpacing(s(10))

        # Заголовок с кнопкой закрытия
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
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
                color: {config.COLORS['accent']};
            }}
        """
        )
        header_layout.addWidget(close_btn)
        layout.addLayout(header_layout)

        # Заголовок с логотипом
        title_layout = QHBoxLayout()
        title_layout.setSpacing(s(10))
        title_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        logo_label = QLabel()
        from PyQt6.QtGui import QPixmap

        logo_pix = QPixmap(config.LOGO_PATH).scaled(
            s(40),
            s(40),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        logo_label.setPixmap(logo_pix)
        logo_label.setStyleSheet("background: transparent; border: none;")
        title_layout.addWidget(logo_label)

        title = QLabel("TF-Alerter")
        title.setStyleSheet(
            f"""
            color: #1e90ff;
            font-size: {s(22)}px;
            font-weight: bold;
            border: none;
        """
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(title)

        layout.addLayout(title_layout)

        # Версия
        version = QLabel(self.t["version"])
        version.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: {s(11)}px; border: none;"
        )
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)

        layout.addSpacing(4)

        # Описание программы
        description = QLabel(self.t["description"])
        description.setStyleSheet(
            f"""
            color: {config.COLORS['text']};
            font-size: {s(12)}px;
            border: none;
            background: transparent;
        """
        )
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)
        layout.addWidget(description)

        layout.addSpacing(4)

        # Разработчик
        dev_row = QHBoxLayout()
        dev_row.setSpacing(s(6))
        dev_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        dev_label = QLabel(self.t["developer"])
        dev_label.setStyleSheet(
            f"color: #888; font-size: {s(11)}px; border: none; background: transparent;"
        )

        dev_name = QLabel(config.AUTHOR_NAME)
        dev_name.setStyleSheet(
            f"""
            color: {config.COLORS['text']};
            font-size: {s(14)}px;
            font-weight: bold;
            border: none;
            background: transparent;
        """
        )

        dev_row.addWidget(dev_label)
        dev_row.addWidget(dev_name)
        layout.addLayout(dev_row)

        layout.addSpacing(5)

        # Кнопка Smart Link
        smart_link_btn = QPushButton(self.t["smart_link_btn"])
        smart_link_btn.setFixedHeight(s(38))
        smart_link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        smart_link_btn.clicked.connect(self.open_smart_link)
        smart_link_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: #1e90ff;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px;
                font-size: {s(13)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #1874cc;
            }}
        """
        )
        layout.addWidget(smart_link_btn)

        # Для перетаскивания
        self.old_pos = None

    def open_smart_link(self):
        """Открывает Smart Link в браузере"""
        QDesktopServices.openUrl(QUrl(config.SMART_LINK_URL))
        self.close()

        parent_window = self.parent()
        if parent_window is None:
            return

        def _minimize_main_window():
            try:
                minimize_method = getattr(parent_window, "request_minimize", None)
                if callable(minimize_method):
                    minimize_method()
                    return
                show_minimized = getattr(parent_window, "showMinimized", None)
                if callable(show_minimized):
                    show_minimized()
            except Exception:
                pass

        QTimer.singleShot(0, _minimize_main_window)

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
