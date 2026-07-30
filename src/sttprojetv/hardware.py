"""Автоопределение железа и подбор модели/устройства для faster-whisper.

Наличие GPU и объём VRAM определяем НЕ через torch (обычный `pip install torch` ставит
CPU-сборку без CUDA, и torch.cuda.is_available() в такой сборке всегда лжёт False, даже
на машине с настоящей видеокартой), а через ctranslate2.get_cuda_device_count() —
у ctranslate2 (внутри faster-whisper) собственная, независимая от torch поддержка CUDA,
встроенная прямо в PyPI-колесо. Объём VRAM читаем через NVML (nvidia-ml-py), которая идёт
в комплекте с любым драйвером NVIDIA и не требует установленного CUDA toolkit.

ВАЖНАЯ ОГОВОРКА: сам RealtimeSTT при инициализации внутренне перепроверяет устройство через
torch.cuda.is_available() и молча откатывает "cuda" на "cpu", если torch собран без CUDA —
даже если мы передали device="cuda" явно (см. README/requirements.txt: для реальной работы на
GPU нужно поставить CUDA-сборку torch, иначе распознавание всё равно уйдёт на CPU, просто
медленно, без ошибки). Поэтому здесь дополнительно проверяем torch.cuda.is_available() и,
если ctranslate2 видит GPU, а torch — нет, громко предупреждаем в логах, что будет использован
CPU несмотря на выбранную модель.

Логика (актуальна при config["model"] == "auto" и/или config["device"] == "auto"):
  - Есть CUDA-видеокарта:
      >=6 GB VRAM  -> large-v3-turbo (баланс качества и скорости на топовых картах)
      >=3 GB VRAM  -> medium
      меньше       -> small
    Во всех случаях compute_type=int8 (минимизирует VRAM, разница в качестве против
    float16 для этой задачи некритична).
  - CUDA нет -> device=cpu, model=small, compute_type=int8.

Пользователь может переопределить любое из полей вручную в настройках — тогда
detect_hardware() не переопределяет то, что задано явно (не "auto").
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HardwareProfile:
    device: str  # "cuda" | "cpu"
    model: str
    compute_type: str
    vram_gb: float | None = None


def _detect_cuda() -> tuple[bool, float | None]:
    try:
        import ctranslate2
    except ImportError:
        logger.warning("ctranslate2 недоступен — считаю, что CUDA нет")
        return False, None

    try:
        if ctranslate2.get_cuda_device_count() < 1:
            return False, None
    except Exception:
        logger.exception("Не удалось опросить CUDA через ctranslate2")
        return False, None

    vram_gb = _query_vram_gb()
    return True, vram_gb


def _query_vram_gb() -> float | None:
    try:
        import pynvml
    except ImportError:
        logger.warning("nvidia-ml-py недоступен — VRAM не определён, беру консервативный профиль")
        return None

    try:
        pynvml.nvmlInit()
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            return mem.total / (1024**3)
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        logger.exception("Не удалось прочитать объём VRAM через NVML")
        return None


def _torch_cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def detect_hardware() -> HardwareProfile:
    has_cuda, vram_gb = _detect_cuda()

    if not has_cuda:
        logger.info("CUDA не обнаружена, использую CPU-режим")
        return HardwareProfile(device="cpu", model="small", compute_type="int8")

    if not _torch_cuda_available():
        logger.warning(
            "Видеокарта обнаружена, но установлен torch без поддержки CUDA — "
            "RealtimeSTT всё равно будет распознавать речь на CPU (медленно, без ошибки). "
            "Установите CUDA-сборку torch: "
            "pip install torch --index-url https://download.pytorch.org/whl/cu126"
        )

    if vram_gb is not None and vram_gb >= 6:
        model = "large-v3-turbo"
    elif vram_gb is not None and vram_gb >= 3:
        model = "medium"
    else:
        model = "small"

    logger.info("Обнаружена CUDA-видеокарта, VRAM=%.1f ГБ, модель=%s", vram_gb or -1, model)
    return HardwareProfile(device="cuda", model=model, compute_type="int8", vram_gb=vram_gb)


def resolve_settings(config: dict[str, Any]) -> HardwareProfile:
    """Учитывает ручные настройки пользователя (не "auto"), остальное берёт из автоопределения."""
    auto = detect_hardware()

    device = config.get("device", "auto")
    model = config.get("model", "auto")
    compute_type = config.get("compute_type", "auto")

    return HardwareProfile(
        device=auto.device if device == "auto" else device,
        model=auto.model if model == "auto" else model,
        compute_type=auto.compute_type if compute_type == "auto" else compute_type,
        vram_gb=auto.vram_gb,
    )
