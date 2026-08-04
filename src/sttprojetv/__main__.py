"""Точка входа: python -m sttprojetv"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from .app import Application
from .config import get_app_dir
from .errors import AppError
from .gui.settings_window import SettingsWindow
from .tray import TrayIcon

logger = logging.getLogger(__name__)

_SINGLE_INSTANCE_MUTEX_NAME = "Global\\STTProjetV_SingleInstance"


def _as_app_error(exc: Exception) -> AppError:
    """Любая ошибка, дошедшая досюда без кода - непредвиденная (E599). Все ожидаемые точки
    отказа (скачивание модели, микрофон, хоткей и т.п.) уже поднимают AppError сами."""
    return exc if isinstance(exc, AppError) else AppError("E599", str(exc))


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


def _setup_logging() -> Path:
    # В windowed-сборке (--windowed) у процесса нет консоли, а sys.stderr/stdout - None,
    # поэтому обычный StreamHandler уронит логирование. Всегда пишем лог в файл (обычно
    # рядом с программой, но get_app_dir() сама уходит в %LOCALAPPDATA%, если эта папка
    # недоступна для записи - см. config.py), а в консоль дублируем только если она реально
    # есть (запуск из терминала).
    log_path = get_app_dir() / "sttprojetv.log"
    handlers: list[logging.Handler] = [logging.FileHandler(log_path, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    return log_path


def _show_fatal_native_error(exc: BaseException) -> None:
    """Последний рубеж защиты - не зависит ни от logging (могло не настроиться), ни от
    tkinter (могло не создаться), ни от нашей обычной инфраструктуры диалогов (show_startup_error
    и т.п. - они сами часть того, что могло не заработать). Голый WinAPI MessageBox, чтобы
    пользователь увидел хоть что-то вместо тишины при полностью непредвиденном сбое."""
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            f"STTProjetV не смог запуститься из-за непредвиденной ошибки:\n\n{exc}",
            "STTProjetV - критическая ошибка",
            0x10,  # MB_ICONERROR
        )
    except Exception:
        pass


def main() -> None:
    try:
        _main_impl()
    except Exception as exc:
        logger.exception("Необработанная ошибка верхнего уровня")
        _show_fatal_native_error(exc)


def _main_impl() -> None:
    log_path = _setup_logging()

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
        # По отдельности и без пробрасывания исключений - клик "Выход" должен закрывать
        # программу гарантированно, даже если что-то внутри падает при остановке.
        try:
            tray_icon.stop()
        except Exception:
            logger.exception("Не удалось остановить иконку в трее")
        app = state["app"]
        if app is not None:
            try:
                app.shutdown()
            except Exception:
                logger.exception("Ошибка при завершении работы")
        root.quit()

    tray_icon = TrayIcon(
        on_open_settings=lambda: root.after(0, open_settings),
        on_quit=lambda: root.after(0, quit_app),
    )

    def run_tray() -> None:
        try:
            tray_icon.run()
        except Exception:
            logger.exception("Иконка в трее аварийно завершилась")

    threading.Thread(target=run_tray, daemon=True).start()

    def show_startup_error(message: str) -> None:
        tray_icon.set_status("error")
        messagebox.showerror(
            "STTProjetV - ошибка запуска",
            f"{message}\n\nПодробности - в файле {log_path}",
        )

    def show_runtime_error(err: AppError) -> None:
        # В отличие от show_startup_error - программа продолжает работать, это просто
        # сообщение "вот что не получилось", не фатальный сбой (иконка в трее не краснеет).
        messagebox.showerror(
            "STTProjetV - ошибка",
            f"{err}\n\nПодробности - в файле {log_path}",
        )

    def on_download_progress(done: int, total: int) -> None:
        if total:
            tray_icon.set_loading_progress(int(done / total * 100))

    def on_stage_change(message: str) -> None:
        tray_icon.set_loading_stage(message)

    def init_app() -> None:
        try:
            app = Application(
                on_download_progress=on_download_progress,
                on_stage_change=on_stage_change,
            )
        except Exception as exc:
            err = _as_app_error(exc)
            logger.exception("Не удалось запустить STTProjetV [%s]", err.code)
            root.after(0, lambda: show_startup_error(str(err)))
            return

        def finish_setup() -> None:
            settings_window = SettingsWindow(app.config, on_config_changed=app.apply_config_changes)
            app.set_reload_status_callback(settings_window.set_apply_status)
            app.set_error_callback(lambda err: root.after(0, lambda: show_runtime_error(err)))
            state["app"] = app
            state["settings_window"] = settings_window

            def on_status_change(status: str) -> None:
                tray_icon.set_status(status)
                settings_window.set_recording_status(status)

            app.set_status_callback(on_status_change)
            try:
                app.start()
            except Exception as exc:
                err = _as_app_error(exc)
                logger.exception("Не удалось запустить STTProjetV [%s]", err.code)
                show_startup_error(str(err))
                return
            tray_icon.set_status("idle")

        root.after(0, finish_setup)

    threading.Thread(target=init_app, daemon=True).start()

    try:
        root.mainloop()
    except Exception:
        logger.exception("Необработанная ошибка в главном цикле")


if __name__ == "__main__":
    main()
