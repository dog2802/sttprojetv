"""Fuzzy-коррекция распознанного текста по пользовательскому словарю терминов.

Whisper часто слышит игровой жаргон "на слух" и искажает его (например "бикоридин"
вместо "Бикаридин"). Здесь каждое слово (или короткая последовательность слов, если
в словаре есть термины из нескольких слов) сравнивается с терминами из словаря по
похожести звучания/написания и при достаточном сходстве заменяется на точную форму
термина из словаря - пунктуация и позиция в тексте сохраняются.
"""
from __future__ import annotations

import string

from rapidfuzz import fuzz

_PUNCT = string.punctuation + "«»—…"
_MIN_CORE_LENGTH = 3
_MATCH_THRESHOLD = 84.0


def _split_punct(word: str) -> tuple[str, str, str]:
    """Возвращает (префикс-пунктуация, ядро-слово, суффикс-пунктуация)."""
    core = word.strip(_PUNCT)
    if not core:
        return word, "", ""
    prefix_len = word.index(core)
    suffix_start = prefix_len + len(core)
    return word[:prefix_len], core, word[suffix_start:]


def correct_terms(text: str, terms: list[str], threshold: float = _MATCH_THRESHOLD) -> str:
    """Заменяет в тексте слова/словосочетания, похожие на термины из словаря, на сам термин."""
    if not text or not terms:
        return text

    words = text.split(" ")
    max_span = max((len(term.split(" ")) for term in terms), default=1)

    result: list[str] = []
    i = 0
    n = len(words)
    while i < n:
        matched = False
        for span in range(min(max_span, n - i), 0, -1):
            window = words[i : i + span]
            parts = [_split_punct(w) for w in window]
            core = " ".join(p[1] for p in parts)
            if len(core) < _MIN_CORE_LENGTH:
                continue

            best_term, best_score = None, 0.0
            for term in terms:
                score = fuzz.ratio(core.lower(), term.lower())
                if score > best_score:
                    best_term, best_score = term, score

            if best_term is not None and best_score >= threshold:
                prefix = parts[0][0]
                suffix = parts[-1][2]
                result.append(f"{prefix}{best_term}{suffix}")
                i += span
                matched = True
                break

        if not matched:
            result.append(words[i])
            i += 1

    return " ".join(result)
