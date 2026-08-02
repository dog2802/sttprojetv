"""Обёртка над RealtimeSTT.AudioToTextRecorder с ручным управлением записью.

Используется push-to-talk сценарий: start_recording() по нажатию хоткея,
stop_and_transcribe() по отпусканию — а не автоматический VAD-старт/стоп,
чтобы Whisper обрабатывал цельную фразу целиком (лучше пунктуация и меньше ошибок).
"""
from __future__ import annotations

import io
import logging
import re
import time
from typing import Callable

from RealtimeSTT import AudioToTextRecorder
from tqdm import tqdm as _tqdm

from .hardware import HardwareProfile

logger = logging.getLogger(__name__)

_MODEL_DOWNLOAD_PATTERNS = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]


def _resolve_model_repo_id(model_name: str) -> str:
    if re.match(r".*/.*", model_name):
        return model_name
    # Та же карта имя->репозиторий, что использует faster_whisper.utils.download_model
    # (не публичный API, но стабильный - используется только чтобы скачать модель заранее
    # в основном процессе и показать реальный прогресс, см. ensure_model_downloaded).
    from faster_whisper.utils import _MODELS

    repo_id = _MODELS.get(model_name)
    if repo_id is None:
        raise ValueError(f"Неизвестная модель Whisper: {model_name!r}")
    return repo_id


def ensure_model_downloaded(
    model_name: str, on_progress: Callable[[int, int], None] | None = None
) -> None:
    """Скачивает модель Whisper заранее, в основном процессе, с реальным прогрессом
    (в байтах). Нужно потому, что сам RealtimeSTT/faster-whisper грузит модель уже внутри
    отдельного процесса транскрипции - оттуда прогресс наружу никак не передать. Если модель
    уже полностью в кэше - сеть вообще не трогаем (работает офлайн)."""
    import huggingface_hub

    repo_id = _resolve_model_repo_id(model_name)

    try:
        huggingface_hub.snapshot_download(
            repo_id, allow_patterns=_MODEL_DOWNLOAD_PATTERNS, local_files_only=True
        )
        logger.info("Модель %s уже в кэше, скачивание не требуется", model_name)
        return
    except Exception:
        pass

    # snapshot_download создаёт сразу несколько tqdm-баров: "Downloading bytes" (сводный
    # прогресс по всем файлам сразу, total растёт по мере обнаружения новых файлов),
    # "Reconstructing..." (зеркально повторяет те же числа - если считать оба, байты
    # задвоятся) и "Fetching N files" (счётчик файлов, не байт - unit='it', а не 'B').
    # Нужен только "Downloading bytes". Раз total растёт по ходу дела (сперва известны только
    # мелкие файлы вроде config.json/tokenizer.json, model.bin добавляется в total чуть позже),
    # ранние отчёты могут показать ложные "100%" по одному крошечному файлу, пока model.bin ещё
    # не учтён. Поэтому игнорируем отчёты, пока total не станет заметно больше служебных файлов
    # (у всех наших моделей model.bin - от 75 МБ, а конфиги/токенайзер - единицы МБ максимум).
    _TRACKED_DESC = "Downloading bytes"
    _MIN_MEANINGFUL_TOTAL = 5_000_000  # 5 МБ - заведомо больше служебных файлов, меньше model.bin
    best_percent = -1

    class _ProgressTqdm(_tqdm):
        """Настоящий tqdm (а не самодельная заглушка) - huggingface_hub дёргает у
        прогресс-бара много разных методов помимо update() (set_postfix_str и т.п.), проще
        унаследоваться и переопределить только update(), чем угадывать весь интерфейс.
        file=StringIO(), чтобы не пытаться писать в консоль, которой нет в windowed-сборке
        (sys.stdout/stderr там None - иначе tqdm упал бы сам)."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs.setdefault("file", io.StringIO())
            super().__init__(*args, **kwargs)

        def update(self, n: float = 1) -> bool | None:
            nonlocal best_percent
            result = super().update(n)
            if (
                on_progress is not None
                and self.desc == _TRACKED_DESC
                and self.total >= _MIN_MEANINGFUL_TOTAL
            ):
                percent = min(100, int(self.n / self.total * 100))
                if percent > best_percent:
                    best_percent = percent
                    on_progress(int(self.n), int(self.total))
            return result

    logger.info("Скачиваю модель %s (%s)...", model_name, repo_id)
    huggingface_hub.snapshot_download(
        repo_id,
        allow_patterns=_MODEL_DOWNLOAD_PATTERNS,
        tqdm_class=_ProgressTqdm,
    )
    logger.info("Модель %s скачана", model_name)


class SpeechToText:
    def __init__(
        self,
        profile: HardwareProfile,
        language: str = "ru",
        microphone_index: int | None = None,
        initial_prompt: str | None = None,
    ) -> None:
        kwargs: dict = dict(
            model=profile.model,
            device=profile.device,
            compute_type=profile.compute_type,
            language=language,
            use_microphone=True,
            spinner=False,
            enable_realtime_transcription=False,
            level=logging.WARNING,
        )
        if microphone_index is not None:
            kwargs["input_device_index"] = microphone_index
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt

        logger.info(
            "Загружаю модель Whisper: model=%s device=%s compute_type=%s",
            profile.model,
            profile.device,
            profile.compute_type,
        )
        self._recorder = AudioToTextRecorder(**kwargs)
        logger.info("Модель загружена, готов к работе")

    def start_recording(self) -> None:
        self._recorder.start()

    def stop_recording(self) -> None:
        """Быстрый вызов: просто помечает конец записи. Безопасно вызывать из колбэка хоткея."""
        self._recorder.stop()

    def transcribe(self) -> str:
        """Блокирующая транскрипция — вызывать из отдельного потока, не из колбэка хоткея."""
        t0 = time.perf_counter()
        text = self._recorder.text()
        logger.info("recorder.text() заняло %.2f с", time.perf_counter() - t0)
        return (text or "").strip()

    def stop_and_transcribe(self) -> str:
        self.stop_recording()
        return self.transcribe()

    def shutdown(self) -> None:
        self._recorder.shutdown()
