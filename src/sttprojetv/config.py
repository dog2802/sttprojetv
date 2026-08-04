"""Загрузка и сохранение настроек STTProjetV в JSON-файле рядом с программой."""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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


_app_dir_cache: Path | None = None


def _is_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".write_test_{os.getpid()}"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def get_app_dir() -> Path:
    """Каталог для config.json/dictionaries/лога. Обычно рядом с .exe - удобно тестерам,
    всё в одном месте. Но если туда нельзя писать (например, программу распаковали в
    Program Files без прав администратора) - используем %LOCALAPPDATA%\\STTProjetV, куда
    любой процесс пользователя пишет без повышения прав. Решение принимается один раз за
    запуск и кешируется, чтобы данные не расползались между двумя местами посреди работы."""
    global _app_dir_cache
    if _app_dir_cache is not None:
        return _app_dir_cache

    if getattr(sys, "frozen", False):
        primary = Path(sys.executable).resolve().parent
    else:
        primary = Path(__file__).resolve().parent.parent.parent

    if _is_writable(primary):
        _app_dir_cache = primary
        return primary

    fallback = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "STTProjetV"
    fallback.mkdir(parents=True, exist_ok=True)
    logger.warning(
        "Папка программы %s недоступна для записи - использую %s вместо неё", primary, fallback
    )
    _app_dir_cache = fallback
    return fallback


def get_config_path() -> Path:
    return get_app_dir() / "config.json"


def load_config() -> dict[str, Any]:
    path = get_config_path()
    if not path.exists():
        config = dict(DEFAULT_CONFIG)
        save_config(config)
        return config

    try:
        with path.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError(f"config.json должен содержать объект, а не {type(loaded).__name__}")
    except (json.JSONDecodeError, ValueError, OSError):
        # Битый файл (ручное редактирование, обрыв записи при сбое питания и т.п.) не должен
        # ронять программу целиком - откатываемся на настройки по умолчанию, а повреждённый
        # файл сохраняем рядом на случай, если пользователь захочет восстановить свои правки.
        logger.exception("config.json повреждён - сбрасываю настройки на значения по умолчанию")
        try:
            backup_path = path.with_suffix(f".broken-{int(time.time())}.json")
            path.replace(backup_path)
        except OSError:
            logger.exception("Не удалось сохранить копию повреждённого config.json")
        config = dict(DEFAULT_CONFIG)
        save_config(config)
        return config

    # Разовая миграция: раньше был один флажок direct_paste (bool), теперь три
    # взаимоисключающих режима output_mode ("clipboard"/"paste"/"type").
    if "direct_paste" in loaded:
        loaded.setdefault("output_mode", "paste" if loaded["direct_paste"] else "clipboard")
        del loaded["direct_paste"]

    config = dict(DEFAULT_CONFIG)
    config.update(loaded)
    return config


def save_config(config: dict[str, Any]) -> None:
    _atomic_write_text(get_config_path(), json.dumps(config, ensure_ascii=False, indent=2))


def _atomic_write_text(path: Path, content: str) -> None:
    """Пишет во временный файл рядом и атомарно переименовывает поверх целевого - если
    процесс упадёт или получит сигнал завершения посреди записи (антивирус, отключение
    питания), целевой файл останется либо старым, либо новым, но никогда не обрежется
    наполовину (что превратило бы его в битый JSON при следующем запуске)."""
    tmp_path = path.with_suffix(f"{path.suffix}.tmp{os.getpid()}")
    with tmp_path.open("w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp_path, path)


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
        try:
            content = legacy_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Разовая миграция необязательна для работы программы - лучше молча её
            # пропустить (пользователь начнёт с пустого словаря), чем уронить запуск.
            logger.exception("Не удалось прочитать старый terms.txt для миграции - пропускаю")
            return
        try:
            (directory / DEFAULT_DICTIONARY_NAME).write_text(content, encoding="utf-8")
        except OSError:
            logger.exception("Не удалось записать смигрированный словарь")


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
    фразой, чтобы правки в файле подхватывались без перезапуска программы. Именно поэтому
    здесь нельзя просто дать исключению вылететь наружу при проблеме с файлом - иначе одна
    неудачная кодировка (пользователь накидывает свой .txt, часто сохранённый Блокнотом в
    ANSI/cp1251, а не UTF-8) превратила бы КАЖДУЮ произнесённую фразу в диалог с ошибкой."""
    path = get_dictionaries_dir() / dictionary_name
    if not path.exists():
        return []

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = path.read_text(encoding="cp1251")
        except (OSError, UnicodeDecodeError):
            logger.warning("Словарь %s в незнакомой кодировке - пропускаю", dictionary_name)
            return []
    except OSError:
        logger.warning("Не удалось прочитать словарь %s", dictionary_name)
        return []

    return [
        stripped
        for line in content.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]


def save_terms(dictionary_name: str, terms: list[str]) -> None:
    path = get_dictionaries_dir() / dictionary_name
    content = _TERMS_FILE_HEADER + "\n" + "".join(term + "\n" for term in terms)
    _atomic_write_text(path, content)
