"""Обработка текста после распознавания: словарь терминов -> (позже) орфография."""
from __future__ import annotations

from typing import Callable

from .correction.dictionary import correct_terms


class TextPipeline:
    def __init__(self, get_terms: Callable[[], list[str]]) -> None:
        # get_terms читает terms.txt заново при каждом вызове, поэтому правки в файле
        # подхватываются сразу же, без перезапуска программы.
        self._get_terms = get_terms

    def process(self, raw_text: str) -> str:
        text = correct_terms(raw_text, self._get_terms())
        return text
