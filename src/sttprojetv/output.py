"""Доставка распознанного текста: буфер обмена, вставка (Ctrl+V) или посимвольная печать.

Режим определяется config["output_mode"]: "clipboard" (только буфер, по умолчанию),
"paste" (Ctrl+V в активном окне) или "type" (эмуляция реальных нажатий клавиш - работает
и там, где программная вставка из буфера заблокирована, например в некоторых играх).
"""
from __future__ import annotations

import logging
import time

import pyperclip
from pynput.keyboard import Controller, Key

logger = logging.getLogger(__name__)

_controller = Controller()


def copy_to_clipboard(text: str) -> None:
    pyperclip.copy(text)


def paste_into_active_window() -> None:
    """Имитирует Ctrl+V в текущем активном окне (курсор должен уже стоять в поле ввода)."""
    time.sleep(0.05)  # даём системе зафиксировать содержимое буфера обмена
    with _controller.pressed(Key.ctrl):
        _controller.press("v")
        _controller.release("v")


def type_into_active_window(text: str) -> None:
    """Печатает текст в активном окне посимвольной эмуляцией нажатий клавиш."""
    _controller.type(text)


def deliver_text(text: str, mode: str) -> None:
    if not text:
        logger.info("Пустой результат распознавания — нечего доставлять")
        return

    copy_to_clipboard(text)
    logger.info("Текст скопирован в буфер обмена: %r", text)

    if mode == "paste":
        paste_into_active_window()
        logger.info("Текст вставлен в активное окно")
    elif mode == "type":
        type_into_active_window(text)
        logger.info("Текст напечатан в активном окне")
