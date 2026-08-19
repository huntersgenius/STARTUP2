"""Text normalisation shared by the retrieval arms.

The spelling folding itself lives with the terminology map, which is where the
clinical vocabulary is defined; this module just applies it to tokenisation.
"""

from __future__ import annotations

import re

from knowledge.terminology import fold_spelling

_TOKEN = re.compile(r"[\w']+", re.UNICODE)


def fold_medical_spelling(text: str) -> str:
    return fold_spelling(text.casefold())


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(fold_medical_spelling(text))
