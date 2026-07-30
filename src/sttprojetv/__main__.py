"""Точка входа: python -m sttprojetv"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from .app import Application
from .config import get_app_dir
from .gui.settings_window import SettingsWindow
from .tray import TrayIcon

logger = logging.getLogger(__name__)

_SINGLE_INSTANCE_MUTEX_NAME = "Global\\STTProjetV_SingleInstance"


def _acquire_single_instance_lock() -> bool:
    """True, если это единственный запущенный экземпляр программы. Держит именованный
    Windows-мьютекс живым до конца процесса (закрывается автоматически при выходе)."""
    try:
        ctypes.windll.kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX_NAME)
        already_running = ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
        return not already_running
    except Exception:
        logger.debug("Не удалось проверить единственность запуска", exc_info=True)
        return True


def _setup_logging() -> None:
    # В windowed-сборке (--windowed) у процесса нет консоли, а sys.stderr/stdout - None,
    # поэтому обычный StreamHandler уронит логирование. Всегда пишем лог в файл рядом
    # с программой, а в консоль дублируем только если она реально есть (запуск из терминала).
    handlers: list[logging.Handler] = [
        logging.FileHandler(get_app_dir() / "sttprojetv.log", encoding="utf-8")
    ]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


def main() -> None:
    _setup_logging()

    if not _acquire_single_instance_lock():
        logger.warning("STTProjetV уже запущен - закрываю этот экземпляр")
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning("STTProjetV", "Программа уже запущена - смотрите иконку в трее.")
        root.destroy()
        return

    app = Application()

    root = tk.Tk()
    root.withdraw()  # видимого главного окна нет - только иконка в трее

    settings_window = SettingsWindow(app.config, on_config_changed=app.apply_config_changes)
    app.set_reload_status_callback(settings_window.set_apply_status)

    def open_settings() -> None:
        settings_window.show(root)

    def quit_app() -> None:
        tray_icon.stop()
        app.shutdown()
        root.quit()

    tray_icon = TrayIcon(
        on_open_settings=lambda: root.after(0, open_settings),
        on_quit=lambda: root.after(0, quit_app),
    )

    def on_status_change(status: str) -> None:
        tray_icon.set_status(status)
        settings_window.set_recording_status(status)

    app.set_status_callback(on_status_change)

    threading.Thread(target=tray_icon.run, daemon=True).start()
    app.start()

    root.mainloop()


if __name__ == "__main__":
    main()
