"""Иконка в системном трее: статус (ожидание/запись/распознаю) + меню."""
from __future__ import annotations

from typing import Callable

import pystray
from PIL import Image, ImageDraw

_STATUS_COLORS = {
    "loading": (60, 140, 220, 255),     # синий - первый запуск, грузим/качаем модель
    "idle": (128, 128, 128, 255),       # серый - ожидание
    "listening": (220, 50, 50, 255),    # красный - идёт запись
    "processing": (230, 170, 40, 255),  # жёлтый - распознаю
    "error": (150, 0, 0, 255),          # тёмно-красный - ошибка при запуске
}
_STATUS_LABELS = {
    "loading": "STTProjetV - загрузка модели (может занять несколько минут при первом запуске)...",
    "idle": "STTProjetV - ожидание",
    "listening": "STTProjetV - запись...",
    "processing": "STTProjetV - распознаю...",
    "error": "STTProjetV - ошибка запуска, смотрите sttprojetv.log",
}


def _make_icon_image(color: tuple[int, int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=color)
    return img


class TrayIcon:
    def __init__(
        self,
        on_open_settings: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Открыть настройки", lambda icon, item: on_open_settings(), default=True),
            pystray.MenuItem("Выход", lambda icon, item: on_quit()),
        )
        self._icon = pystray.Icon(
            "sttprojetv",
            _make_icon_image(_STATUS_COLORS["loading"]),
            _STATUS_LABELS["loading"],
            menu=menu,
        )

    def set_status(self, status: str) -> None:
        if status not in _STATUS_COLORS:
            return
        self._icon.icon = _make_icon_image(_STATUS_COLORS[status])
        self._icon.title = _STATUS_LABELS[status]

    def set_loading_progress(self, percent: int) -> None:
        """Обновляет только подсказку (иконка остаётся синей "загрузка") - вызывается часто
        во время скачивания модели, поэтому не трогает картинку, только текст."""
        self._icon.title = f"STTProjetV - скачиваю модель... {percent}%"

    def run(self) -> None:
        """Блокирующий вызов - запускать в отдельном потоке."""
        self._icon.run()

    def stop(self) -> None:
        self._icon.stop()
