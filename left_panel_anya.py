#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
left_panel_anya.py - Левая панель с картинкой Ани
Исправления:
- Убрано фиксированное setFixedSize() у QLabel (из-за него картинка обрезалась).
- Добавлено авто-масштабирование pixmap при resizeEvent (картинка всегда целиком).
- Использование Path для относительных путей (портабельность).
- Исправлена функция show_success_image для возврата к фону через таймер.
"""
import logging
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QVBoxLayout, QLabel, QWidget, QSizePolicy

logger = logging.getLogger("distributor")

class AnyaPanel(QWidget):
    """Контейнер с картинкой Ани, которая всегда масштабируется целиком по размеру панели."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_pixmap: QPixmap | None = None
        self._current_filename: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # ВАЖНО: не фиксированный размер — пусть растягивается/сжимается
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_label.setMinimumSize(200, 200)
        self.reset_timer = QTimer(self)
        self.reset_timer.timeout.connect(self._show_default_image)
        self.reset_timer.setSingleShot(True)
        # ПОРТАБЕЛЬНОСТЬ: ищем папку картинок относительно этого файла
        self.img_dir = Path(__file__).resolve().parent / "vnesh_ip"
        layout.addWidget(self.image_label, 1)
        self._show_default_image()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_scaled_pixmap()

    def _apply_scaled_pixmap(self):
        """Перемасштабировать текущую картинку под текущий размер label."""
        if self._current_pixmap is None or self._current_pixmap.isNull():
            return
        target_size = self.image_label.size()
        if target_size.width() <= 0 or target_size.height() <= 0:
            return
        scaled = self._current_pixmap.scaled(
            target_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def _load_image(self, filename: str) -> bool:
        """Загрузить картинку (в память) и отрисовать в label с масштабированием."""
        img_path = self.img_dir / filename
        if not img_path.exists():
            logger.error(f"[AnyaPanel] Файл не найден: {img_path}")
            self._current_pixmap = None
            self._current_filename = None
            return False
        try:
            pix = QPixmap(str(img_path))
            if pix.isNull():
                logger.error(f"[AnyaPanel] QPixmap.isNull() для {filename}")
                self._current_pixmap = None
            else:
                self._current_pixmap = pix
                self._current_filename = filename
                self._apply_scaled_pixmap()
            return not pix.isNull()
        except Exception as e:
            logger.error(f"[AnyaPanel] Ошибка при загрузке {filename}: {e}", exc_info=True)
            self._current_pixmap = None
            self._current_filename = None
            return False

    def _show_default_image(self):
        if not self._load_image("fon.png"):
            self.image_label.setStyleSheet("background-color: #444444; border: 1px solid #666;")
            self.image_label.setText("❌ fon.png не найдена")

    def show_check_image(self):
        self.reset_timer.stop()
        if not self._load_image("podklychenie.png"):
            self.image_label.setStyleSheet("background-color: #333333; border: 1px solid #555;")
            self.image_label.setText("⚠️ podklychenie.png не найдена")

    def show_error_image(self):
        self.reset_timer.stop()
        if not self._load_image("error.png"):
            self.image_label.setStyleSheet("background-color: #550000; border: 1px solid #800;")
            self.image_label.setText("❌ error.png не найдена")
        # Возврат к фону через 3 секунды
        self.reset_timer.start(3000)

    def show_success_image(self):
        self.reset_timer.stop()
        if not self._load_image("success.png"):
            self.image_label.setStyleSheet("background-color: #333333; border: 1px solid #555;")
            self.image_label.setText("⚠️ success.png не найдена")
        # Возврат к фону через 2 секунды
        self.reset_timer.start(2000)

    def show_image_1(self):
        self.reset_timer.stop()
        if not self._load_image("1.png"):
            self.image_label.setStyleSheet("background-color: #333333; border: 1px solid #555;")
            self.image_label.setText("⚠️ 1.png не найдена")
            return
        self.reset_timer.start(2000)

    def show_image_2(self):
        self.reset_timer.stop()
        if not self._load_image("2.png"):
            self.image_label.setStyleSheet("background-color: #333333; border: 1px solid #555;")
            self.image_label.setText("⚠️ 2.png не найдена")
            return
        self.reset_timer.start(2000)

    def back_to_default(self):
        self.reset_timer.stop()
        self._show_default_image()
