from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QFrame,
)
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtCore import Qt, QSettings


class FontPickerDialog(QDialog):
    def __init__(self, parent=None, current_family="Arial", preview_callback=None):
        super().__init__(parent)
        self.parent = parent
        self.current_family = current_family
        self.selected_family = current_family
        self.preview_callback = preview_callback
        self.original_family = current_family

        # Словари переводов
        self.translations = {
            "RU": {
                "title": "Выбор шрифта",
                "font_list": "Доступные шрифты:",
                "cancel": "Отмена",
                "ok": "OK",
            },
            "EN": {
                "title": "Font Picker",
                "font_list": "Available fonts:",
                "cancel": "Cancel",
                "ok": "OK",
            },
        }

        # Получаем текущий язык
        settings = QSettings("MyTradeTools", "TF-Alerter")
        self.current_lang = settings.value("language", "RU")

        self.setWindowTitle(self.translations[self.current_lang]["title"])
        self.setFixedSize(400, 500)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Главный контейнер
        main_container = QFrame(self)
        main_container.setStyleSheet(
            """
            QFrame {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 10px;
            }
        """
        )
        main_container.setGeometry(0, 0, 400, 500)

        layout = QVBoxLayout(main_container)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(12)

        # Label
        label = QLabel(self.translations[self.current_lang]["font_list"])
        label.setStyleSheet("color: #fff;")
        layout.addWidget(label)

        # Font list
        self.font_list = QListWidget()
        self.font_list.setStyleSheet(
            """
            QListWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 5px;
                color: #fff;
            }
            QListWidget::item:selected {
                background-color: #1e90ff;
            }
        """
        )

        # Get available fonts (PyQt6: QFontDatabase is used via static methods)
        families = QFontDatabase.families()

        for family in families:
            item = QListWidgetItem(family)
            self.font_list.addItem(item)

            # Select current font
            if family == self.current_family:
                self.font_list.setCurrentItem(item)

        # Connect selection change to preview callback
        self.font_list.itemSelectionChanged.connect(self.on_font_selected)
        self.font_list.itemClicked.connect(self.on_font_clicked)
        layout.addWidget(self.font_list)

        # Buttons layout
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        cancel_btn = QPushButton(self.translations[self.current_lang]["cancel"])
        cancel_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #444;
                color: #fff;
                border: 1px solid #555;
                border-radius: 5px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """
        )
        cancel_btn.clicked.connect(self.reject)

        ok_btn = QPushButton(self.translations[self.current_lang]["ok"])
        ok_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #1e90ff;
                color: #fff;
                border: 1px solid #1a7cdb;
                border-radius: 5px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4da6ff;
            }
        """
        )
        ok_btn.clicked.connect(self.accept)

        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(ok_btn)
        layout.addLayout(button_layout)

        self.setLayout(QVBoxLayout(self))
        self.layout().addWidget(main_container)
        self.layout().setContentsMargins(0, 0, 0, 0)

    def on_font_selected(self):
        current_item = self.font_list.currentItem()
        if current_item:
            self.selected_family = current_item.text()
            if self.preview_callback:
                self.preview_callback(self.selected_family)

    def on_font_clicked(self, item):
        if not item:
            return
        self.selected_family = item.text()
        if self.preview_callback:
            self.preview_callback(self.selected_family)

    def get_selected_font_family(self):
        return self.selected_family
