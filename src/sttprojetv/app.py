"""Оркестратор: хоткей → STT → словарь → буфер обмена."""
from __future__ import annotations

import logging
import threading
from typing import Callable

from . import config as config_module
from .config import load_config
from .hardware import resolve_settings
from .hotkey import PushToTalkHotkey
from .output import deliver_text
from .pipeline import TextPipeline
from .stt import SpeechToText, ensure_model_downloaded

logger = logging.getLogger(__name__)


class Application:
    def __init__(self, on_download_progress: Callable[[int, int], None] | None = None) -> None:
        self.config = load_config()
        self.profile = resolve_settings(self.config)

        # initial_prompt - лишь мягкая подсказка модели при запуске (бакова в сессию STT,
        # берётся из словаря, активного на момент запуска). Основную работу по исправлению
        # искажённых терминов делает TextPipeline ниже - он каждый раз заново узнаёт, какой
        # словарь сейчас активен, и перечитывает его файл, поэтому и правки внутри словаря,
        # и переключение между словарями в настройках применяются сразу, без перезапуска.
        terms_at_startup = config_module.load_terms(config_module.get_active_dictionary(self.config))

        # Скачиваем модель заранее, в основном процессе, чтобы видеть реальный прогресс -
        # RealtimeSTT грузит её уже внутри отдельного процесса транскрипции, откуда прогресс
        # наружу не передать. on_download_progress передаётся конструктору, а не через
        # set_..._callback, потому что скачивание происходит прямо здесь, синхронно.
        ensure_model_downloaded(self.profile.model, on_progress=on_download_progress)

        self.stt = SpeechToText(
            profile=self.profile,
            language=self.config["language"],
            microphone_index=self.config["microphone_index"],
            initial_prompt=", ".join(terms_at_startup) or None,
        )
        self.pipeline = TextPipeline(get_terms=self._get_active_terms)

        self.hotkey = PushToTalkHotkey(
            key_name=self.config["hotkey"],
            on_press=self._on_hotkey_press,
            on_release=self._on_hotkey_release,
        )

        # Что сейчас реально загружено/активно - используется, чтобы после сохранения
        # настроек понять, что именно изменилось и что нужно пересобрать.
        self._active_model = self.config["model"]
        self._active_microphone_index = self.config["microphone_index"]
        self._active_hotkey_name = self.config["hotkey"]
        self._reload_lock = threading.Lock()

        self._status_callback: Callable[[str], None] | None = None
        self._reload_status_callback: Callable[[str], None] | None = None

    def set_status_callback(self, callback: Callable[[str], None]) -> None:
        """Вызывается при смене статуса (idle/listening/processing) - для иконки в трее."""
        self._status_callback = callback

    def set_reload_status_callback(self, callback: Callable[[str], None]) -> None:
        """Вызывается при применении настроек (ready/applying) - для индикатора в окне настроек."""
        self._reload_status_callback = callback

    def _set_status(self, status: str) -> None:
        if self._status_callback is not None:
            self._status_callback(status)

    def _set_reload_status(self, status: str) -> None:
        if self._reload_status_callback is not None:
            self._reload_status_callback(status)

    def _get_active_terms(self) -> list[str]:
        return config_module.load_terms(config_module.get_active_dictionary(self.config))

    def _on_hotkey_press(self) -> None:
        logger.info("[запись...]")
        self._set_status("listening")
        self.stt.start_recording()

    def _on_hotkey_release(self) -> None:
        # stop() быстрый — можно звать прямо из колбэка хоткея.
        self.stt.stop_recording()
        self._set_status("processing")
        # transcribe() медленный — уводим в отдельный поток, чтобы не блокировать
        # низкоуровневый хук клавиатуры (иначе Windows может его отключить).
        threading.Thread(target=self._transcribe_and_deliver, daemon=True).start()

    def _transcribe_and_deliver(self) -> None:
        logger.info("[распознаю...]")
        raw_text = self.stt.transcribe()
        if not raw_text:
            logger.info("[пусто] речь не распознана")
            self._set_status("idle")
            return

        text = self.pipeline.process(raw_text)
        if text != raw_text:
            logger.info("[словарь] %s -> %s", raw_text, text)
        deliver_text(text, mode=self.config["output_mode"])
        logger.info("[готово] %s", text)
        self._set_status("idle")

    def apply_config_changes(self) -> None:
        """Вызывается после сохранения настроек. Если поменялись модель/микрофон/хоткей -
        пересобирает STT-движок и/или хоткей-листенер прямо в работающем приложении,
        без перезапуска всей программы. Модель/микрофон всё равно требуют нескольких
        секунд на загрузку - это делается в фоновом потоке, статус в трее показывает это."""
        threading.Thread(target=self._reload_worker, daemon=True).start()

    def _reload_worker(self) -> None:
        if not self._reload_lock.acquire(blocking=False):
            logger.info("Применение настроек уже идёт, пропускаю повторный запрос")
            return
        try:
            new_model = self.config["model"]
            new_mic = self.config["microphone_index"]
            new_hotkey_name = self.config["hotkey"]

            stt_changed = (new_model, new_mic) != (self._active_model, self._active_microphone_index)
            hotkey_changed = new_hotkey_name != self._active_hotkey_name

            if not stt_changed and not hotkey_changed:
                return

            logger.info("Применяю новые настройки...")
            self._set_status("processing")
            self._set_reload_status("applying")

            # Останавливаем старый хоткей-листенер на время пересборки, чтобы не поймать
            # нажатие в процессе замены STT-движка. pynput.Listener нельзя перезапустить
            # повторным start() после stop() (это одноразовый поток) - поэтому ниже листенер
            # пересоздаётся заново в любом случае, а не только если поменялось имя хоткея.
            self.hotkey.stop()

            if stt_changed:
                self.profile = resolve_settings(self.config)
                ensure_model_downloaded(self.profile.model)
                new_stt = SpeechToText(
                    profile=self.profile,
                    language=self.config["language"],
                    microphone_index=new_mic,
                    initial_prompt=", ".join(self._get_active_terms()) or None,
                )
                old_stt = self.stt
                self.stt = new_stt
                old_stt.shutdown()
                self._active_model = new_model
                self._active_microphone_index = new_mic

            self.hotkey = PushToTalkHotkey(
                key_name=new_hotkey_name,
                on_press=self._on_hotkey_press,
                on_release=self._on_hotkey_release,
            )
            self._active_hotkey_name = new_hotkey_name
            self.hotkey.start()

            logger.info("Новые настройки применены")
            self._set_status("idle")
            self._set_reload_status("ready")
        except Exception:
            logger.exception("Не удалось применить новые настройки")
            self._set_status("idle")
            self._set_reload_status("ready")
        finally:
            self._reload_lock.release()

    def start(self) -> None:
        """Запускает хоткей-листенер (не блокирует поток)."""
        logger.info(
            "STTProjetV запущен. Зажмите '%s' и говорите.",
            self.config["hotkey"],
        )
        self.hotkey.start()

    def run(self) -> None:
        """CLI-режим без трея/GUI: блокирует поток до Ctrl+C."""
        self.start()
        try:
            self.hotkey.join()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        logger.info("Завершение работы...")
        self.hotkey.stop()
        self.stt.shutdown()
