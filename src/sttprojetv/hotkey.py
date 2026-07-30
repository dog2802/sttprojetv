"""Глобальный push-to-talk хоткей: клавиатура или боковая кнопка мыши (через pynput).

Имя клавиши хранится строкой в конфиге:
  - обычная клавиша: "ctrl_r", "f9", "caps_lock", "a" ...
  - кнопка мыши: "mouse_x1", "mouse_x2", "mouse_middle" (формат "mouse_<кнопка>")
"""
from __future__ import annotations

import logging
from typing import Callable

from pynput import keyboard, mouse
from pynput.keyboard import Key, KeyCode
from pynput.mouse import Button

logger = logging.getLogger(__name__)

MOUSE_PREFIX = "mouse_"

_MOUSE_BUTTONS: dict[str, Button] = {
    "left": Button.left,
    "right": Button.right,
    "middle": Button.middle,
    "x1": Button.x1,
    "x2": Button.x2,
}


def parse_key(name: str) -> Key | KeyCode:
    name = name.strip().lower()
    special = getattr(Key, name, None)
    if isinstance(special, Key):
        return special
    if len(name) == 1:
        return KeyCode.from_char(name)
    raise ValueError(f"Неизвестная клавиша в конфиге: {name!r}")


def is_mouse_trigger(name: str) -> bool:
    return name.strip().lower().startswith(MOUSE_PREFIX)


def parse_mouse_button(name: str) -> Button:
    key = name.strip().lower()[len(MOUSE_PREFIX):]
    if key not in _MOUSE_BUTTONS:
        raise ValueError(f"Неизвестная кнопка мыши в конфиге: {name!r}")
    return _MOUSE_BUTTONS[key]


class PushToTalkHotkey:
    """Слушает либо клавиатуру, либо мышь — в зависимости от формата key_name."""

    def __init__(
        self,
        key_name: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        self._on_press_cb = on_press
        self._on_release_cb = on_release
        self._pressed = False

        self._keyboard_listener: keyboard.Listener | None = None
        self._mouse_listener: mouse.Listener | None = None

        if is_mouse_trigger(key_name):
            self._button = parse_mouse_button(key_name)
            self._mouse_listener = mouse.Listener(on_click=self._handle_click)
        else:
            self._key = parse_key(key_name)
            self._keyboard_listener = keyboard.Listener(
                on_press=self._handle_press,
                on_release=self._handle_release,
            )

    def _safe_call(self, callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception:
            logger.exception("Ошибка в обработчике хоткея")

    def _handle_click(self, x: int, y: int, button: Button, pressed: bool) -> None:
        if button != self._button:
            return
        if pressed and not self._pressed:
            self._pressed = True
            self._safe_call(self._on_press_cb)
        elif not pressed and self._pressed:
            self._pressed = False
            self._safe_call(self._on_release_cb)

    def _handle_press(self, key: Key | KeyCode | None) -> None:
        if key == self._key and not self._pressed:
            self._pressed = True
            self._safe_call(self._on_press_cb)

    def _handle_release(self, key: Key | KeyCode | None) -> None:
        if key == self._key and self._pressed:
            self._pressed = False
            self._safe_call(self._on_release_cb)

    def _active_listener(self) -> keyboard.Listener | mouse.Listener:
        return self._mouse_listener or self._keyboard_listener  # type: ignore[return-value]

    def start(self) -> None:
        self._active_listener().start()

    def stop(self) -> None:
        self._active_listener().stop()

    def join(self) -> None:
        self._active_listener().join()
