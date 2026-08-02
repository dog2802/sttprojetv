"""Точка входа для PyInstaller-сборки.

multiprocessing.freeze_support() обязателен первым делом: RealtimeSTT запускает
транскрипцию в отдельном процессе (multiprocessing, spawn), и без freeze_support()
это не работает из собранного .exe на Windows.
"""
from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path

# Должно быть выставлено до первого импорта huggingface_hub (переменную окружения он читает
# один раз при импорте модуля с константами) - иначе выставлять её позже в коде уже бесполезно.
# Без xet прогресс скачивания модели (см. stt.ensure_model_downloaded) - один понятный
# байтовый прогресс-бар с заранее известным размером, вместо нескольких параллельных
# xet-стадий (download/reconstruct) с разной, плохо агрегируемой семантикой.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

if __name__ == "__main__":
    multiprocessing.freeze_support()

    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    from sttprojetv.__main__ import main

    main()
