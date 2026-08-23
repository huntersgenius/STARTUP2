"""Audit instrument: map free text to concepts and to firing red-flag rules.

Nothing here is part of the product. It exists so that when a case fails, the
audit can say *which* concept failed to resolve, rather than reporting an
opaque accuracy number.

Usage:
    PYTHONPATH=backend:. python audit/adversarial/probe.py "ko'kragim og'ir"
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from app.ai.red_flags import CaseFacts, evaluate
from knowledge.terminology import get_terminology


@dataclass
class Probe:
    text: str
    concepts: list[str]
    expanded: list[str]
    flags: list[str]


def probe(text: str, **facts: Any) -> Probe:
    mapping = get_terminology()
    concepts = mapping.clinical_concepts(text)
    case = CaseFacts(concepts=set(concepts), free_text=text, **facts)
    return Probe(
        text=text,
        concepts=sorted(concepts),
        expanded=sorted(case.concepts),
        flags=[f.code for f in evaluate(case)],
    )


def main() -> int:
    for text in sys.argv[1:]:
        p = probe(text)
        print(f"text     : {p.text}")
        print(f"concepts : {p.concepts}")
        print(f"expanded : {p.expanded}")
        print(f"red flags: {p.flags}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
