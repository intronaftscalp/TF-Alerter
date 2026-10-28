from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt, QPoint


class OverlayClock(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel("00:00:00")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.label)
        self.font_family = "Arial"
        self.bg_enabled = False
        self.bg_color = "#000000"

        self._dragging = False
        self._drag_pos = QPoint()
        self.move_locked = False
        self.main_window = None  # Будет установлено из main.py

    def set_time(self, time_str):
        self.label.setText(time_str)

    def update_style(
        self,
        color,
        size,
        alpha=255,
        font_family=None,
        bg_enabled=None,
        bg_color=None,
    ):
        if isinstance(font_family, str) and font_family.strip():
            self.font_family = font_family.strip()

        if isinstance(bg_enabled, bool):
            self.bg_enabled = bg_enabled

        if isinstance(bg_color, str) and bg_color.strip():
            self.bg_color = bg_color.strip()

        safe_font_family = self.font_family.replace("'", "\\'")

        # Конвертируем цвет в RGBA с прозрачностью
        # Если цвет имеет формат #RRGGBBAA, используем его как есть
        if len(color) == 9:  # #RRGGBBAA формат
            rgba_color = f"rgba({int(color[1:3], 16)}, {int(color[3:5], 16)}, {int(color[5:7], 16)}, {alpha})"
        else:  # #RRGGBB формат
            rgba_color = f"rgba({int(color[1:3], 16)}, {int(color[3:5], 16)}, {int(color[5:7], 16)}, {alpha})"

        bg_style = "background: transparent;"
        if self.bg_enabled:
            if len(self.bg_color) == 9:
                bg_alpha = int(self.bg_color[7:9], 16)
                bg_rgba = f"rgba({int(self.bg_color[1:3], 16)}, {int(self.bg_color[3:5], 16)}, {int(self.bg_color[5:7], 16)}, {bg_alpha})"
            else:
                bg_rgba = f"rgba({int(self.bg_color[1:3], 16)}, {int(self.bg_color[3:5], 16)}, {int(self.bg_color[5:7], 16)}, 255)"
            bg_style = (
                f"background-color: {bg_rgba}; padding: 1px 4px; border-radius: 5px;"
            )

        # Чистый прозрачный фон. Тянуть можно только за прорисованные части цифр.
        self.label.setStyleSheet(
            f"""
            color: {rgba_color}; 
            font-size: {size}px; 
            font-family: '{safe_font_family}';
            font-weight: bold; 
            {bg_style}
        """
        )
        self.adjustSize()

    def mousePressEvent(self, event):
        if self.move_locked:
            event.ignore()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_pos = event.pos()
            self.grabMouse()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.releaseMouse()
            # Сохраняем позицию после перетаскивания
            if self.main_window:
                self.main_window.save_settings()
            event.accept()
