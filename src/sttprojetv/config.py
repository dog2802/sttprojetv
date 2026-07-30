"""Загрузка и сохранение настроек STTProjetV в JSON-файле рядом с программой."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    # "auto" | "tiny" | "base" | "small" | "medium" | "large-v3" | "large-v3-turbo"
    "model": "auto",
    # "auto" | "cuda" | "cpu"
    "device": "auto",
    # "auto" | "int8" | "int8_float16" | "float16" | "float32"
    "compute_type": "auto",
    "language": "ru",
    # Имя клавиши для pynput (см. hotkey.py), например "ctrl_r", "f9".
    "hotkey": "ctrl_r",
    # Индекс микрофона (sounddevice/PyAudio). null = микрофон по умолчанию.
    "microphone_index": None,
    # "clipboard" (только буфер обмена) | "paste" (Ctrl+V в активном окне) |
    # "type" (эмуляция реальных нажатий клавиш - работает и там, где вставка заблокирована).
    "output_mode": "clipboard",
    # Имя файла (внутри dictionaries/) с активным сейчас словарём терминов. null - будет
    # выбран автоматически (первый найденный или создан "default.txt").
    "active_dictionary": None,
    # "light" | "dark" - тема окна настроек.
    "theme": "light",
}

DEFAULT_DICTIONARY_NAME = "default.txt"


def get_app_dir() -> Path:
    """Каталог, где живёт исполняемый .exe (или корень репозитория при запуске из исходников)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def get_config_path() -> Path:
    return get_app_dir() / "config.json"


def load_config() -> dict[str, Any]:
    path = get_config_path()
    if not path.exists():
        config = dict(DEFAULT_CONFIG)
        save_config(config)
        return config

    with path.open("r", encoding="utf-8") as f:
        loaded = json.load(f)

    # Разовая миграция: раньше был один флажок direct_paste (bool), теперь три
    # взаимоисключающих режима output_mode ("clipboard"/"paste"/"type").
    if "direct_paste" in loaded:
        loaded.setdefault("output_mode", "paste" if loaded["direct_paste"] else "clipboard")
        del loaded["direct_paste"]

    config = dict(DEFAULT_CONFIG)
    config.update(loaded)
    return config


def save_config(config: dict[str, Any]) -> None:
    path = get_config_path()
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_dictionaries_dir() -> Path:
    """Папка со словарями терминов - каждый .txt файл в ней это отдельный именованный
    список (например ss14.txt, my-other-game.txt). Можно просто скопировать туда свой
    .txt файл - он сразу появится в выпадающем списке в настройках."""
    path = get_app_dir() / "dictionaries"
    path.mkdir(exist_ok=True)
    return path


def list_dictionaries() -> list[str]:
    """Имена файлов словарей (с расширением) в dictionaries/, по алфавиту."""
    return sorted(p.name for p in get_dictionaries_dir().glob("*.txt"))


_TERMS_FILE_HEADER = (
    "# Пользовательский словарь STTProjetV.\n"
    "# По одному термину на строку. Строки, начинающиеся с '#', и пустые строки игнорируются.\n"
    "# Файл перечитывается перед каждой фразой - изменения применяются сразу, без перезапуска.\n"
    "# Пример: Бикаридин\n"
)


def _migrate_legacy_terms_file() -> None:
    """Разовая миграция: раньше словарь хранился в одном плоском terms.txt рядом с программой.
    Если он есть, а модульных словарей ещё нет - переносим его содержимое в dictionaries/,
    чтобы уже введённые пользователем термины не потерялись."""
    legacy_path = get_app_dir() / "terms.txt"
    directory = get_dictionaries_dir()
    if legacy_path.exists() and not any(directory.glob("*.txt")):
        (directory / DEFAULT_DICTIONARY_NAME).write_text(
            legacy_path.read_text(encoding="utf-8"), encoding="utf-8"
        )


def get_active_dictionary(config: dict[str, Any]) -> str:
    """Имя активного файла словаря: то, что выбрано в настройках, либо первый найденный,
    либо вновь создаваемый "default.txt", если словарей ещё вообще нет."""
    _migrate_legacy_terms_file()
    available = list_dictionaries()

    active = config.get("active_dictionary")
    if active in available:
        return active
    if available:
        return available[0]

    path = get_dictionaries_dir() / DEFAULT_DICTIONARY_NAME
    if not path.exists():
        path.write_text(_TERMS_FILE_HEADER, encoding="utf-8")
    return DEFAULT_DICTIONARY_NAME


def load_terms(dictionary_name: str) -> list[str]:
    """Читает конкретный словарь терминов с диска. Дешёвый вызов - можно звать перед каждой
    фразой, чтобы правки в файле подхватывались без перезапуска программы."""
    path = get_dictionaries_dir() / dictionary_name
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    return [
        stripped
        for line in lines
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]


def save_terms(dictionary_name: str, terms: list[str]) -> None:
    path = get_dictionaries_dir() / dictionary_name
    with path.open("w", encoding="utf-8") as f:
        f.write(_TERMS_FILE_HEADER)
        f.write("\n")
        for term in terms:
            f.write(term + "\n")
