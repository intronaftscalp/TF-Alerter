from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QFrame,
    QColorDialog,
    QCheckBox,
)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt, QSettings
import config
import os
import ctypes


class ColorPickerDialog(QDialog):
    def __init__(
        self,
        parent=None,
        current_color=None,
        current_alpha=255,
        bg_enabled=False,
        bg_color="#000000",
    ):
        super().__init__(parent)
        self.parent = parent
        # Use provided color or fallback to configured accent
        self.selected_color = QColor(
            current_color or config.COLORS.get("accent", "#1e90ff")
        )
        self.selected_alpha = current_alpha
        # Сохраняем исходные значения для восстановления при отмене
        self.original_color = current_color or config.COLORS.get("accent", "#1e90ff")
        self.original_alpha = current_alpha
        self.bg_enabled = bool(bg_enabled)
        bg_color_raw = str(bg_color if bg_color else "#000000")
        if len(bg_color_raw) == 9:
            self.bg_color = QColor(bg_color_raw[:7])
            self.bg_alpha = int(bg_color_raw[7:9], 16)
        else:
            self.bg_color = QColor(bg_color_raw)
            self.bg_alpha = 255
        self.original_bg_enabled = bool(bg_enabled)
        self.original_bg_color = self.bg_color.name()
        self.original_bg_alpha = self.bg_alpha

        # Словари переводов
        self.translations = {
            "RU": {
                "title": "Выбор цвета",
                "clock_color": "Цвет часов:",
                "clock_opacity": "Прозрачность часов:",
                "bg_enabled": "Фон под часами",
                "bg_color": "Цвет фона:",
                "bg_opacity": "Прозрачность фона:",
                "pick_color": "Выбрать цвет",
                "cancel": "Отмена",
                "ok": "OK",
            },
            "EN": {
                "title": "Color Picker",
                "clock_color": "Clock color:",
                "clock_opacity": "Clock opacity:",
                "bg_enabled": "Background under clock",
                "bg_color": "Background color:",
                "bg_opacity": "Background opacity:",
                "pick_color": "Pick Color",
                "cancel": "Cancel",
                "ok": "OK",
            },
        }

        # Получаем текущий язык
        settings = QSettings("MyTradeTools", "TF-Alerter")
        self.current_lang = settings.value("language", "RU")

        self.setWindowTitle(self.translations[self.current_lang]["title"])
        self.setFixedSize(420, 370)

        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

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
        main_container.setGeometry(0, 0, 420, 370)

        layout = QVBoxLayout(main_container)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(12)

        # Заголовок
        title = QLabel(self.translations[self.current_lang]["title"])
        title.setStyleSheet(
            f"""
            color: {config.COLORS['text']};
            font-size: 14px;
            font-weight: bold;
            border: none;
            background: transparent;
        """
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Цвет
        color_layout = QHBoxLayout()
        color_label = QLabel(self.translations[self.current_lang]["clock_color"])
        color_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: 12px; border: none; background: transparent;"
        )
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(50, 40)
        self.update_color_button()
        self.color_btn.clicked.connect(self.pick_color)
        color_layout.addWidget(color_label)
        color_layout.addStretch()
        color_layout.addWidget(self.color_btn)
        layout.addLayout(color_layout)

        # Прозрачность
        opacity_layout = QHBoxLayout()
        opacity_label = QLabel(self.translations[self.current_lang]["clock_opacity"])
        opacity_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: 12px; border: none; background: transparent;"
        )
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setMinimum(0)
        self.opacity_slider.setMaximum(255)
        self.opacity_slider.setValue(current_alpha)
        self.opacity_slider.setStyleSheet(self._slider_style())

        self.opacity_value = QLabel(f"{current_alpha}")
        self.opacity_value.setFixedWidth(40)
        self.opacity_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.opacity_value.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: 12px; border: none; background: transparent;"
        )

        # Подключаем live preview при изменении слайдера
        self.opacity_slider.valueChanged.connect(self.on_opacity_changed)
        self.opacity_slider.sliderMoved.connect(self.preview_changes)

        opacity_layout.addWidget(opacity_label)
        opacity_layout.addWidget(self.opacity_slider)
        opacity_layout.addWidget(self.opacity_value)
        layout.addLayout(opacity_layout)

        # Фон под часами: вкл/выкл
        bg_enable_layout = QHBoxLayout()
        self.bg_enabled_check = QCheckBox(
            self.translations[self.current_lang]["bg_enabled"]
        )
        self.bg_enabled_check.setChecked(self.bg_enabled)
        self.bg_enabled_check.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: 12px; border: none; background: transparent;"
        )
        self.bg_enabled_check.stateChanged.connect(self.on_bg_enabled_changed)
        bg_enable_layout.addWidget(self.bg_enabled_check)
        bg_enable_layout.addStretch()
        layout.addLayout(bg_enable_layout)

        # Цвет фона
        bg_color_layout = QHBoxLayout()
        bg_color_label = QLabel(self.translations[self.current_lang]["bg_color"])
        bg_color_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: 12px; border: none; background: transparent;"
        )
        self.bg_color_btn = QPushButton()
        self.bg_color_btn.setFixedSize(50, 40)
        self.update_bg_color_button()
        self.bg_color_btn.setEnabled(self.bg_enabled)
        self.bg_color_btn.clicked.connect(self.pick_bg_color)
        bg_color_layout.addWidget(bg_color_label)
        bg_color_layout.addStretch()
        bg_color_layout.addWidget(self.bg_color_btn)
        layout.addLayout(bg_color_layout)

        bg_opacity_layout = QHBoxLayout()
        bg_opacity_label = QLabel(self.translations[self.current_lang]["bg_opacity"])
        bg_opacity_label.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: 12px; border: none; background: transparent;"
        )
        self.bg_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.bg_opacity_slider.setMinimum(0)
        self.bg_opacity_slider.setMaximum(255)
        self.bg_opacity_slider.setValue(int(self.bg_alpha))
        self.bg_opacity_slider.setStyleSheet(self._slider_style())
        self.bg_opacity_slider.setEnabled(self.bg_enabled)
        self.bg_opacity_slider.valueChanged.connect(self.on_bg_opacity_changed)

        self.bg_opacity_value = QLabel(f"{int(self.bg_alpha)}")
        self.bg_opacity_value.setFixedWidth(40)
        self.bg_opacity_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bg_opacity_value.setStyleSheet(
            f"color: {config.COLORS['text']}; font-size: 12px; border: none; background: transparent;"
        )

        bg_opacity_layout.addWidget(bg_opacity_label)
        bg_opacity_layout.addWidget(self.bg_opacity_slider)
        bg_opacity_layout.addWidget(self.bg_opacity_value)
        layout.addLayout(bg_opacity_layout)

        layout.addSpacing(10)

        # Кнопки
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton(self.translations[self.current_lang]["cancel"])
        cancel_btn.setFixedHeight(32)
        cancel_btn.setFixedWidth(100)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet(self._button_style())

        ok_btn = QPushButton(self.translations[self.current_lang]["ok"])
        ok_btn.setFixedHeight(32)
        ok_btn.setFixedWidth(100)
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.clicked.connect(self.accept)
        ok_btn.setStyleSheet(self._button_style())

        btn_layout.addWidget(cancel_btn)
        btn_layout.addSpacing(5)
        btn_layout.addWidget(ok_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Для перетаскивания
        self.old_pos = None

    def _button_style(self):
        return f"""
            QPushButton {{
                background-color: {config.COLORS['panel']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: 5px;
                padding: 5px 20px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {config.COLORS['hover']};
                border: 1px solid {config.COLORS['text']};
            }}
        """

    def _slider_style(self):
        return f"""
            QSlider::groove:horizontal {{
                background-color: {config.COLORS['panel']};
                height: 8px;
                border-radius: 4px;
                border: 1px solid {config.COLORS['border']};
            }}
            QSlider::handle:horizontal {{
                background-color: {config.COLORS['accent']};
                width: 16px;
                margin: -4px 0;
                border-radius: 8px;
                border: 1px solid {config.COLORS['border']};
            }}
            QSlider::handle:horizontal:hover {{
                background-color: #1e90ff;
            }}
        """

    def update_color_button(self):
        """Обновляет кнопку с текущим цветом"""
        self.color_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {self.selected_color.name()};
                border: 2px solid {config.COLORS['border']};
                border-radius: 5px;
            }}
            QPushButton:hover {{
                border: 2px solid {config.COLORS['accent']};
            }}
        """
        )

    def update_bg_color_button(self):
        self.bg_color_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {self.bg_color.name()};
                border: 2px solid {config.COLORS['border']};
                border-radius: 5px;
            }}
            QPushButton:hover {{
                border: 2px solid {config.COLORS['accent']};
            }}
        """
        )

    def _create_dark_color_dialog(self, initial_color, show_alpha):
        dialog = QColorDialog(initial_color, self)
        dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        dialog.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, show_alpha)
        self._apply_dark_title_bar(dialog)
        dialog.setStyleSheet(
            f"""
            QColorDialog {{
                background-color: {config.COLORS['background']};
                color: {config.COLORS['text']};
            }}
            QWidget {{
                background-color: {config.COLORS['background']};
                color: {config.COLORS['text']};
            }}
            QLabel {{
                color: {config.COLORS['text']};
            }}
            QLineEdit, QSpinBox, QComboBox {{
                background-color: {config.COLORS['panel']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: 4px;
                padding: 2px 4px;
            }}
            QPushButton {{
                background-color: {config.COLORS['panel']};
                color: {config.COLORS['text']};
                border: 1px solid {config.COLORS['border']};
                border-radius: 4px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{
                border: 1px solid {config.COLORS['accent']};
            }}
        """
        )
        return dialog

    def _apply_dark_title_bar(self, widget):
        if os.name != "nt" or widget is None:
            return
        try:
            hwnd = int(widget.winId())
            if hwnd <= 0:
                return

            dwm_set_attr = ctypes.windll.dwmapi.DwmSetWindowAttribute

            use_dark = ctypes.c_int(1)
            dark_size = ctypes.sizeof(use_dark)
            for attr in (20, 19):
                result = dwm_set_attr(hwnd, attr, ctypes.byref(use_dark), dark_size)
                if result == 0:
                    break

            caption_color = ctypes.c_int(0x00141414)
            text_color = ctypes.c_int(0x00FFFFFF)
            color_size = ctypes.sizeof(caption_color)
            dwm_set_attr(hwnd, 35, ctypes.byref(caption_color), color_size)
            dwm_set_attr(hwnd, 36, ctypes.byref(text_color), color_size)
        except Exception:
            pass

    def pick_bg_color(self):
        if not hasattr(self, "bg_color_dialog"):
            self.bg_color_dialog = None

        if self.bg_color_dialog is None:
            self.bg_color_dialog = self._create_dark_color_dialog(
                self.bg_color, show_alpha=False
            )
            self.bg_color_dialog.currentColorChanged.connect(self.on_bg_color_selected)
            self.bg_color_dialog.finished.connect(self.on_bg_color_dialog_finished)
            self.bg_color_dialog.show()

    def on_bg_color_selected(self, color):
        if color.isValid():
            self.bg_color = color
            self.update_bg_color_button()
            self.preview_changes()

    def on_bg_color_dialog_finished(self, result):
        if result == 0:
            self.bg_color = QColor(self.original_bg_color)
            self.bg_alpha = int(self.original_bg_alpha)
            self.bg_opacity_slider.setValue(self.bg_alpha)
            self.bg_opacity_value.setText(str(self.bg_alpha))
            self.update_bg_color_button()
            self.preview_changes()
        self.bg_color_dialog = None

    def on_bg_enabled_changed(self, state):
        if isinstance(state, Qt.CheckState):
            self.bg_enabled = state == Qt.CheckState.Checked
        else:
            self.bg_enabled = int(state) == Qt.CheckState.Checked.value
        self.bg_color_btn.setEnabled(self.bg_enabled)
        self.bg_opacity_slider.setEnabled(self.bg_enabled)
        self.preview_changes()

    def on_bg_opacity_changed(self, value):
        self.bg_alpha = int(value)
        self.bg_opacity_value.setText(str(int(value)))
        self.preview_changes()

    def pick_color(self):
        """Открывает стандартный диалог выбора цвета с live preview"""
        # Используем non-modal диалог для live preview
        if not hasattr(self, "color_dialog"):
            self.color_dialog = None

        if self.color_dialog is None:
            self.color_dialog = self._create_dark_color_dialog(
                self.selected_color, show_alpha=True
            )
            # Подключаемся к сигналу currentColorChanged для live preview при каждом изменении
            self.color_dialog.currentColorChanged.connect(self.on_color_selected)
            self.color_dialog.finished.connect(self.on_color_dialog_finished)
            self.color_dialog.show()

    def on_color_selected(self, color):
        """Вызывается при каждом изменении цвета в диалоге"""
        if color.isValid():
            self.selected_color = color
            self.update_color_button()
            # Live preview: обновляем часы сразу при каждом движении/клике
            self.preview_changes()

    def on_color_dialog_finished(self, result):
        """Вызывается когда закрывается диалог выбора цвета"""
        # Если пользователь отменил (result == 0), восстанавливаем исходный цвет
        if result == 0:  # 0 = Rejected/Cancel
            self.selected_color = QColor(self.original_color)
            self.update_color_button()
            self.preview_changes()
        self.color_dialog = None

    def on_opacity_changed(self, value):
        """Обновляет значение прозрачности"""
        self.selected_alpha = value
        self.opacity_value.setText(str(value))
        # Live preview: обновляем часы сразу
        self.preview_changes()

    def preview_changes(self):
        """Применяет изменения цвета и прозрачности к часам в реальном времени"""
        if self.parent and hasattr(self.parent, "logic"):
            try:
                # Получаем текущий размер overlay из слайдера
                overlay_size = (
                    self.parent.ui.ov_size_slider.value()
                    if hasattr(self.parent, "ui")
                    else 40
                )
                selected_font = "Arial"
                if hasattr(self.parent, "current_overlay_font"):
                    selected_font = (
                        self.parent.current_overlay_font or ""
                    ).strip() or "Arial"
                # Обновляем стиль часов с новыми цветом и прозрачностью
                self.parent.logic.overlay.update_style(
                    self.selected_color.name(),
                    overlay_size,
                    self.selected_alpha,
                    selected_font,
                    self.bg_enabled,
                    self.get_bg_color(),
                )
            except Exception:
                pass

    def get_color_with_alpha(self):
        """Возвращает цвет с прозрачностью в формате #RRGGBBAA"""
        hex_color = self.selected_color.name()
        alpha_hex = f"{self.selected_alpha:02x}"
        return hex_color + alpha_hex

    def get_color(self):
        """Возвращает только цвет в формате #RRGGBB"""
        return self.selected_color.name()

    def get_alpha(self):
        """Возвращает прозрачность (0-255)"""
        return self.selected_alpha

    def get_bg_enabled(self):
        return bool(self.bg_enabled)

    def get_bg_color(self):
        return f"{self.bg_color.name()}{int(self.bg_alpha):02x}"

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

    def reject(self):
        """Отмена - восстанавливаем исходные значения часов"""
        # Восстанавливаем исходный цвет и прозрачность в overlay
        if self.parent and hasattr(self.parent, "logic"):
            try:
                overlay_size = (
                    self.parent.ui.ov_size_slider.value()
                    if hasattr(self.parent, "ui")
                    else 40
                )
                selected_font = "Arial"
                if hasattr(self.parent, "current_overlay_font"):
                    selected_font = (
                        self.parent.current_overlay_font or ""
                    ).strip() or "Arial"
                self.parent.logic.overlay.update_style(
                    self.original_color,
                    overlay_size,
                    self.original_alpha,
                    selected_font,
                    self.original_bg_enabled,
                    f"{self.original_bg_color}{int(self.original_bg_alpha):02x}",
                )
            except Exception:
                pass
        super().reject()
