"""Точка входа для PyInstaller-сборки.

multiprocessing.freeze_support() обязателен первым делом: RealtimeSTT запускает
транскрипцию в отдельном процессе (multiprocessing, spawn), и без freeze_support()
это не работает из собранного .exe на Windows.
"""
from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path

if __name__ == "__main__":
    multiprocessing.freeze_support()

    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    from sttprojetv.__main__ import main

    main()
