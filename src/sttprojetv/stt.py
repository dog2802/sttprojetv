"""Обёртка над RealtimeSTT.AudioToTextRecorder с ручным управлением записью.

Используется push-to-talk сценарий: start_recording() по нажатию хоткея,
stop_and_transcribe() по отпусканию — а не автоматический VAD-старт/стоп,
чтобы Whisper обрабатывал цельную фразу целиком (лучше пунктуация и меньше ошибок).
"""
from __future__ import annotations

import logging
import time

from RealtimeSTT import AudioToTextRecorder

from .hardware import HardwareProfile

logger = logging.getLogger(__name__)


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
