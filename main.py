import sys
import time
import threading
import math
import traceback

import numpy as np
import soundcard as sc
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QSlider, QCheckBox, QListWidget,
    QGroupBox, QMessageBox
)

APP_NAME = "ARGB Krutoy"
SDK_HOST = "127.0.0.1"
SDK_PORT = 6742


class AudioWorker(QObject):
    level_changed = Signal(float, float)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.running = False
        self.mic = None
        self.recorder = None

    def start(self, loopback_name=None):
        if self.running:
            return
        try:
            speakers = sc.all_speakers()
            if not speakers:
                raise RuntimeError("Windows не вернул аудиоустройства.")
            speaker = next((s for s in speakers if loopback_name and s.name == loopback_name), None)
            if speaker is None:
                speaker = sc.default_speaker()
            self.mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
            self.recorder = self.mic.recorder(samplerate=44100, channels=2, blocksize=2048)
            self.recorder.__enter__()
            self.running = True
            threading.Thread(target=self._loop, daemon=True).start()
        except Exception as exc:
            self.running = False
            self.error.emit(f"Не удалось включить захват системного звука:\n{exc}")

    def _loop(self):
        try:
            while self.running:
                data = self.recorder.record(numframes=2048)
                if data is None or len(data) == 0:
                    continue
                data = np.asarray(data, dtype=np.float32)
                rms = float(np.sqrt(np.mean(data * data)))
                # Approximate bass energy from low-passed adjacent samples.
                low = data[1:] - data[:-1]
                bass = float(np.sqrt(np.mean(low * low))) if low.size else 0.0
                level = min(1.0, rms * 7.0)
                bass_level = min(1.0, bass * 10.0)
                self.level_changed.emit(level, bass_level)
        except Exception as exc:
            if self.running:
                self.error.emit(f"Ошибка захвата звука:\n{exc}")
        finally:
            self.running = False
            try:
                if self.recorder:
                    self.recorder.__exit__(None, None, None)
            except Exception:
                pass

    def stop(self):
        self.running = False


class Visualizer(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(110)
        self.level = 0.0
        self.bass = 0.0
        self.phase = 0.0

    def set_levels(self, level, bass):
        self.level = level
        self.bass = bass
        self.phase += 0.18
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#101018"))
        w, h = self.width(), self.height()
        bars = 36
        gap = 4
        bar_w = max(2, (w - gap * (bars - 1) - 20) / bars)
        for i in range(bars):
            wave = (math.sin(i * 0.48 + self.phase) + 1) * 0.22
            value = min(1.0, self.level * (0.35 + wave) + self.bass * 0.35)
            bh = max(3, value * (h - 20))
            hue = int((i / bars * 260 + self.phase * 25) % 360)
            color = QColor.fromHsv(hue, 230, 255)
            x = 10 + i * (bar_w + gap)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(int(x), int(h - bh - 8), int(bar_w), int(bh), 3, 3)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(780, 650)
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #17151f; color: #f5f3fa; font-size: 13px; }
            QGroupBox { border: 1px solid #393344; border-radius: 10px; margin-top: 10px; padding: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #e779d0; }
            QPushButton { background: #ce5aab; border: 0; border-radius: 8px; padding: 9px 14px; color: white; font-weight: 600; }
            QPushButton:hover { background: #df70bd; }
            QPushButton:disabled { background: #514354; color: #b7aebb; }
            QComboBox, QListWidget { background: #22202b; border: 1px solid #393344; border-radius: 6px; padding: 6px; }
            QSlider::groove:horizontal { height: 5px; background: #393344; border-radius: 2px; }
            QSlider::handle:horizontal { background: #ce5aab; width: 14px; margin: -5px 0; border-radius: 7px; }
        """)
        self.client = None
        self.devices = []
        self.worker = AudioWorker()
        self.worker.level_changed.connect(self.on_audio)
        self.worker.error.connect(self.on_error)
        self.level = 0.0
        self.bass = 0.0
        self.last_rgb = None
        self._build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.apply_lighting)
        self.timer.start(70)

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        title = QLabel("ARGB KRUTOY")
        title.setStyleSheet("font-size: 25px; font-weight: 800; color: #e779d0;")
        subtitle = QLabel("Музыкальная подсветка Windows")
        subtitle.setStyleSheet("color: #aaa4b7;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.visualizer = Visualizer()
        layout.addWidget(self.visualizer)

        audio_box = QGroupBox("Аудио")
        audio_layout = QHBoxLayout(audio_box)
        self.audio_status = QLabel("Захват звука выключен")
        self.start_btn = QPushButton("▶ Запустить")
        self.start_btn.clicked.connect(self.toggle_audio)
        audio_layout.addWidget(self.audio_status, 1)
        audio_layout.addWidget(self.start_btn)
        layout.addWidget(audio_box)

        effect_box = QGroupBox("Эффект")
        effect_layout = QHBoxLayout(effect_box)
        self.effect = QComboBox()
        self.effect.addItems(["Spectrum", "Bass Pulse", "Rainbow"])
        self.effect.currentTextChanged.connect(self.on_effect_changed)
        effect_layout.addWidget(QLabel("Режим:"))
        effect_layout.addWidget(self.effect, 1)
        effect_layout.addWidget(QLabel("Чувствительность:"))
        self.sensitivity = QSlider(Qt.Orientation.Horizontal)
        self.sensitivity.setRange(1, 200)
        self.sensitivity.setValue(100)
        self.sensitivity.setMaximumWidth(170)
        effect_layout.addWidget(self.sensitivity)
        layout.addWidget(effect_box)

        devices_box = QGroupBox("RGB-устройства")
        devices_layout = QVBoxLayout(devices_box)
        row = QHBoxLayout()
        self.connect_btn = QPushButton("Подключить RGB")
        self.connect_btn.clicked.connect(self.connect_rgb)
        self.refresh_btn = QPushButton("Обновить список")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        row.addWidget(self.connect_btn)
        row.addWidget(self.refresh_btn)
        devices_layout.addLayout(row)
        self.device_list = QListWidget()
        self.device_list.setMinimumHeight(140)
        devices_layout.addWidget(self.device_list)
        self.rgb_status = QLabel("RGB не подключён")
        self.rgb_status.setStyleSheet("color: #aaa4b7;")
        devices_layout.addWidget(self.rgb_status)
        layout.addWidget(devices_box)

        note = QLabel("Для первой версии нужен запущенный OpenRGB SDK Server на этом компьютере. Прямой драйвер устройств — следующий этап.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #c6a8c0; padding: 5px;")
        layout.addWidget(note)
        self.setCentralWidget(root)

    def toggle_audio(self):
        if self.worker.running:
            self.worker.stop()
            self.start_btn.setText("▶ Запустить")
            self.audio_status.setText("Захват звука выключен")
        else:
            self.worker.start()
            self.start_btn.setText("■ Остановить")
            self.audio_status.setText("Слушаю системный звук…")

    def on_audio(self, level, bass):
        scale = self.sensitivity.value() / 100.0
        self.level = min(1.0, level * scale)
        self.bass = min(1.0, bass * scale)
        self.visualizer.set_levels(self.level, self.bass)

    def on_error(self, message):
        self.audio_status.setText("Захват звука: ошибка")
        QMessageBox.warning(self, APP_NAME, message)

    def connect_rgb(self):
        try:
            self.client = OpenRGBClient(SDK_HOST, SDK_PORT, name=APP_NAME, timeout=2)
            self.devices = list(self.client.devices)
            self._show_devices()
            self.rgb_status.setText(f"Подключено устройств: {len(self.devices)}")
            if not self.devices:
                self.rgb_status.setText("SDK доступен, но устройств не найдено.")
        except Exception as exc:
            self.client = None
            self.devices = []
            self._show_devices()
            self.rgb_status.setText("Не удалось подключиться к SDK.")
            QMessageBox.warning(
                self, APP_NAME,
                "Не удалось подключиться к OpenRGB SDK Server.\n\n"
                "Проверь, что OpenRGB запущен и SDK Server включён на порту 6742.\n\n"
                f"Подробности: {exc}"
            )

    def refresh_devices(self):
        if self.client is None:
            self.connect_rgb()
            return
        try:
            self.client.update()
            self.devices = list(self.client.devices)
            self._show_devices()
            self.rgb_status.setText(f"Устройств: {len(self.devices)}")
        except Exception as exc:
            self.on_error(f"Не удалось обновить список RGB-устройств:\n{exc}")

    def _show_devices(self):
        self.device_list.clear()
        for device in self.devices:
            self.device_list.addItem(f"{device.name}  ·  {getattr(device, 'type', 'RGB')}")

    def on_effect_changed(self, _):
        self.last_rgb = None

    def apply_lighting(self):
        if self.client is None or not self.devices:
            return
        mode = self.effect.currentText()
        t = time.monotonic()
        if mode == "Bass Pulse":
            brightness = max(0.06, self.bass)
            hue = int((t * 50) % 360)
        elif mode == "Rainbow":
            brightness = max(0.12, self.level)
            hue = int((t * 90) % 360)
        else:
            brightness = max(0.05, self.level * 0.85 + self.bass * 0.4)
            hue = int((t * 45 + self.level * 180) % 360)
        color = QColor.fromHsv(hue, 240, int(max(0.04, min(1.0, brightness)) * 255))
        rgb = (color.red(), color.green(), color.blue())
        if rgb == self.last_rgb:
            return
        self.last_rgb = rgb
        try:
            rgb_color = RGBColor(*rgb)
            for device in self.devices:
                try:
                    device.set_color(rgb_color)
                except Exception:
                    # Some devices expose zones/LEDs differently; skip unsupported device.
                    continue
        except Exception as exc:
            self.rgb_status.setText(f"Ошибка управления RGB: {exc}")

    def closeEvent(self, event):
        self.worker.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
