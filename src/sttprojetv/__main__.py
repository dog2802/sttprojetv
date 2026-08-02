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

    root = tk.Tk()
    root.withdraw()  # видимого главного окна нет - только иконка в трее

    # Иконка в трее и её меню должны появиться сразу, ещё до того, как загрузится модель
    # Whisper (при первом запуске это ещё и скачивание ~1-2 ГБ с Hugging Face - может занять
    # заметное время). Иначе пользователь смотрит на пустой трей и решает, что "ничего не
    # происходит". Поэтому Application() собирается в фоновом потоке, а до этого момента
    # иконка уже видна со статусом "загрузка".
    state: dict[str, object] = {"app": None, "settings_window": None}

    def open_settings() -> None:
        app = state["app"]
        settings_window = state["settings_window"]
        if app is None or settings_window is None:
            messagebox.showinfo(
                "STTProjetV",
                "Модель распознавания ещё загружается, подождите немного и попробуйте снова.",
            )
            return
        settings_window.show(root)

    def quit_app() -> None:
        tray_icon.stop()
        app = state["app"]
        if app is not None:
            app.shutdown()
        root.quit()

    tray_icon = TrayIcon(
        on_open_settings=lambda: root.after(0, open_settings),
        on_quit=lambda: root.after(0, quit_app),
    )
    threading.Thread(target=tray_icon.run, daemon=True).start()

    def show_startup_error(message: str) -> None:
        tray_icon.set_status("error")
        messagebox.showerror(
            "STTProjetV - ошибка запуска",
            f"{message}\n\nПодробности - в файле sttprojetv.log рядом с программой.",
        )

    def on_download_progress(done: int, total: int) -> None:
        if total:
            tray_icon.set_loading_progress(int(done / total * 100))

    def init_app() -> None:
        try:
            app = Application(on_download_progress=on_download_progress)
        except Exception as exc:
            logger.exception("Не удалось запустить STTProjetV")
            root.after(0, lambda: show_startup_error(str(exc)))
            return

        def finish_setup() -> None:
            settings_window = SettingsWindow(app.config, on_config_changed=app.apply_config_changes)
            app.set_reload_status_callback(settings_window.set_apply_status)
            state["app"] = app
            state["settings_window"] = settings_window

            def on_status_change(status: str) -> None:
                tray_icon.set_status(status)
                settings_window.set_recording_status(status)

            app.set_status_callback(on_status_change)
            app.start()
            tray_icon.set_status("idle")

        root.after(0, finish_setup)

    threading.Thread(target=init_app, daemon=True).start()

    try:
        root.mainloop()
    except Exception:
        logger.exception("Необработанная ошибка в главном цикле")


if __name__ == "__main__":
    main()
