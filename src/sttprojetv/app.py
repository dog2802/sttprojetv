"""Оркестратор: хоткей → STT → словарь → буфер обмена."""
from __future__ import annotations

import logging
import threading
from typing import Callable

from . import config as config_module
from .config import load_config
from .errors import AppError
from .hardware import resolve_settings
from .hotkey import PushToTalkHotkey
from .output import deliver_text
from .pipeline import TextPipeline
from .stt import SpeechToText, ensure_model_downloaded

logger = logging.getLogger(__name__)


class Application:
    def __init__(
        self,
        on_download_progress: Callable[[int, int], None] | None = None,
        on_stage_change: Callable[[str], None] | None = None,
    ) -> None:
        # Сохраняются как есть (не через set_..._callback) - оба нужны уже здесь, в __init__,
        # до того как объект Application вообще существует и его можно было бы передать
        # наружу для подписки (курица и яйцо, тот же приём, что и с on_download_progress).
        self._download_progress_callback = on_download_progress
        self._stage_callback = on_stage_change

        try:
            self.config = load_config()
        except Exception as exc:
            raise AppError("E103", str(exc)) from exc
        self.profile = resolve_settings(self.config)

        # initial_prompt - лишь мягкая подсказка модели при запуске (бакова в сессию STT,
        # берётся из словаря, активного на момент запуска). Основную работу по исправлению
        # искажённых терминов делает TextPipeline ниже - он каждый раз заново узнаёт, какой
        # словарь сейчас активен, и перечитывает его файл, поэтому и правки внутри словаря,
        # и переключение между словарями в настройках применяются сразу, без перезапуска.
        try:
            terms_at_startup = config_module.load_terms(config_module.get_active_dictionary(self.config))
        except Exception as exc:
            raise AppError("E103", str(exc)) from exc

        # Скачиваем модель заранее, в основном процессе, чтобы видеть реальный прогресс -
        # RealtimeSTT грузит её уже внутри отдельного процесса транскрипции, откуда прогресс
        # наружу не передать. on_download_progress передаётся конструктору, а не через
        # set_..._callback, потому что скачивание происходит прямо здесь, синхронно.
        ensure_model_downloaded(self.profile.model, on_progress=self._download_progress_callback)
        self._set_stage("загружаю модель в память...")

        self.stt = SpeechToText(
            profile=self.profile,
            language=self.config["language"],
            microphone_index=self.config["microphone_index"],
            initial_prompt=", ".join(terms_at_startup) or None,
        )
        self.pipeline = TextPipeline(get_terms=self._get_active_terms)

        try:
            self.hotkey = PushToTalkHotkey(
                key_name=self.config["hotkey"],
                on_press=self._on_hotkey_press,
                on_release=self._on_hotkey_release,
            )
        except Exception as exc:
            raise AppError("E301", str(exc)) from exc

        # Что сейчас реально загружено/активно - используется, чтобы после сохранения
        # настроек понять, что именно изменилось и что нужно пересобрать.
        self._active_model = self.config["model"]
        self._active_microphone_index = self.config["microphone_index"]
        self._active_hotkey_name = self.config["hotkey"]
        self._reload_lock = threading.Lock()
        # Захватывается на весь цикл запись->распознавание->доставка (с нажатия до конца
        # _transcribe_and_deliver), и на время подмены self.stt при смене модели/микрофона.
        # Не даёт двум циклам или циклу и подменой self.stt пересечься - RealtimeSTT не
        # рассчитан на одновременные start()/text()/shutdown() из разных потоков, а без этой
        # защиты быстрое повторное нажатие хоткея во время ещё не завершённого распознавания
        # предыдущей фразы могло бы испортить внутреннее состояние recorder'а.
        self._stt_lock = threading.Lock()
        self._recording_owned = False

        self._status_callback: Callable[[str], None] | None = None
        self._reload_status_callback: Callable[[str], None] | None = None
        self._error_callback: Callable[[AppError], None] | None = None

    def set_status_callback(self, callback: Callable[[str], None]) -> None:
        """Вызывается при смене статуса (idle/listening/processing) - для иконки в трее."""
        self._status_callback = callback

    def set_reload_status_callback(self, callback: Callable[[str], None]) -> None:
        """Вызывается при применении настроек (ready/applying) - для индикатора в окне настроек."""
        self._reload_status_callback = callback

    def set_error_callback(self, callback: Callable[[AppError], None]) -> None:
        """Вызывается при ошибках, произошедших уже после старта (смена настроек "на лету",
        доставка распознанного текста) - в отличие от ошибок запуска, они не роняют программу,
        поэтому их нужно явно показать пользователю отдельным путём."""
        self._error_callback = callback

    def _set_status(self, status: str) -> None:
        if self._status_callback is not None:
            self._status_callback(status)

    def _set_reload_status(self, status: str) -> None:
        if self._reload_status_callback is not None:
            self._reload_status_callback(status)

    def _set_stage(self, message: str) -> None:
        if self._stage_callback is not None:
            self._stage_callback(message)

    def _report_error(self, err: AppError) -> None:
        if self._error_callback is not None:
            self._error_callback(err)

    def _get_active_terms(self) -> list[str]:
        return config_module.load_terms(config_module.get_active_dictionary(self.config))

    def _on_hotkey_press(self) -> None:
        # Не блокирующий - если лок уже занят (предыдущая фраза ещё обрабатывается, или
        # прямо сейчас идёт подмена self.stt из _reload_worker), просто игнорируем нажатие,
        # а не пытаемся начать запись поверх незавершённого предыдущего цикла.
        if not self._stt_lock.acquire(blocking=False):
            logger.warning(
                "Хоткей нажат, пока обрабатывается предыдущая фраза (или применяются "
                "настройки) - игнорирую"
            )
            return
        self._recording_owned = True
        logger.info("[запись...]")
        self._set_status("listening")
        try:
            self.stt.start_recording()
        except Exception:
            logger.exception("Не удалось начать запись")
            self._recording_owned = False
            self._set_status("idle")
            self._stt_lock.release()

    def _on_hotkey_release(self) -> None:
        if not self._recording_owned:
            # Нажатие было проигнорировано в _on_hotkey_press (см. выше) - отпускание той же
            # кнопки не должно останавливать чужой, всё ещё идущий цикл записи.
            return
        self._recording_owned = False
        # stop() быстрый — можно звать прямо из колбэка хоткея.
        try:
            self.stt.stop_recording()
        except Exception:
            logger.exception("Не удалось остановить запись")
            self._set_status("idle")
            self._stt_lock.release()
            return
        self._set_status("processing")
        # transcribe() медленный — уводим в отдельный поток, чтобы не блокировать
        # низкоуровневый хук клавиатуры (иначе Windows может его отключить).
        threading.Thread(target=self._transcribe_and_deliver, daemon=True).start()

    def _transcribe_and_deliver(self) -> None:
        logger.info("[распознаю...]")
        try:
            raw_text = self.stt.transcribe()
            if not raw_text:
                logger.info("[пусто] речь не распознана")
                return

            text = self.pipeline.process(raw_text)
            if text != raw_text:
                logger.info("[словарь] %s -> %s", raw_text, text)
            deliver_text(text, mode=self.config["output_mode"])
            logger.info("[готово] %s", text)
        except Exception as exc:
            err = exc if isinstance(exc, AppError) else AppError("E401", str(exc))
            logger.exception("Не удалось обработать/доставить распознанный текст [%s]", err.code)
            self._report_error(err)
        finally:
            self._set_status("idle")
            self._stt_lock.release()

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
                # Модель и загрузка с диска/сети - долгие, лок на это время не держим (иначе
                # надолго заблокировали бы хоткей). Захватываем только на сам момент подмены
                # self.stt - если пользователь как раз в этот момент договаривает фразу на
                # старой модели, дожидаемся окончания цикла (с запасом на медленную
                # транскрипцию), а не обрываем его посреди работы.
                got_lock = False
                try:
                    self.profile = resolve_settings(self.config)
                    ensure_model_downloaded(
                        self.profile.model, on_progress=self._download_progress_callback
                    )
                    self._set_stage("загружаю модель в память...")
                    new_stt = SpeechToText(
                        profile=self.profile,
                        language=self.config["language"],
                        microphone_index=new_mic,
                        initial_prompt=", ".join(self._get_active_terms()) or None,
                    )
                    got_lock = self._stt_lock.acquire(timeout=15)
                    if not got_lock:
                        logger.warning(
                            "Не удалось дождаться окончания текущей записи/распознавания - "
                            "подменяю модель параллельно с ней (редкий случай)"
                        )
                    old_stt = self.stt
                    self.stt = new_stt
                    old_stt.shutdown()
                    self._active_model = new_model
                    self._active_microphone_index = new_mic
                except Exception as exc:
                    # Не оставляем в config.json нерабочий выбор (например, модель, которую
                    # не получилось скачать) - иначе при каждом следующем запуске программа
                    # заново и безуспешно повторяла бы ту же попытку. Откатываем на последнее
                    # реально рабочее состояние.
                    err = exc if isinstance(exc, AppError) else AppError("E201", str(exc))
                    logger.exception(
                        "Не удалось применить новую модель/микрофон - откатываю настройки [%s]",
                        err.code,
                    )
                    self.config["model"] = self._active_model
                    self.config["microphone_index"] = self._active_microphone_index
                    config_module.save_config(self.config)
                    self._report_error(err)
                finally:
                    if got_lock:
                        self._stt_lock.release()

            # Хоткей должен перезапуститься в любом случае, даже если смена модели выше
            # не удалась - иначе push-to-talk перестал бы работать до перезапуска программы.
            self.hotkey = PushToTalkHotkey(
                key_name=new_hotkey_name,
                on_press=self._on_hotkey_press,
                on_release=self._on_hotkey_release,
            )
            self._active_hotkey_name = new_hotkey_name
            self.hotkey.start()

            logger.info("Применение настроек завершено")
            self._set_status("idle")
            self._set_reload_status("ready")
        except Exception as exc:
            err = exc if isinstance(exc, AppError) else AppError("E202", str(exc))
            logger.exception("Не удалось применить новые настройки [%s]", err.code)
            # Даже при неожиданной ошибке (например, в самом PushToTalkHotkey) стараемся
            # оставить хоткей рабочим, а не немым до перезапуска программы.
            try:
                self.hotkey = PushToTalkHotkey(
                    key_name=self._active_hotkey_name,
                    on_press=self._on_hotkey_press,
                    on_release=self._on_hotkey_release,
                )
                self.hotkey.start()
            except Exception:
                logger.exception("Не удалось восстановить хоткей после ошибки")
            self._set_status("idle")
            self._set_reload_status("ready")
            self._report_error(err)
        finally:
            self._reload_lock.release()

    def start(self) -> None:
        """Запускает хоткей-листенер (не блокирует поток)."""
        logger.info(
            "STTProjetV запущен. Зажмите '%s' и говорите.",
            self.config["hotkey"],
        )
        try:
            self.hotkey.start()
        except Exception as exc:
            raise AppError("E301", str(exc)) from exc

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
        # По отдельности и без пробрасывания исключений - это финальный путь при закрытии
        # программы (в т.ч. по клику "Выход" в трее), сбой в одной части не должен мешать
        # попытаться прибрать вторую.
        try:
            self.hotkey.stop()
        except Exception:
            logger.exception("Не удалось остановить хоткей при завершении")
        try:
            self.stt.shutdown()
        except Exception:
            logger.exception("Не удалось корректно завершить STT-движок при завершении")
