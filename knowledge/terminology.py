"""Uzbek/Russian clinical terminology map.

The hard part of this product is not the model — it is that a feldsher types
what the patient actually said. "shamollab qoldim", "boshim og'riyapti",
"qorin ogrigi" (no apostrophe, as typed on a real keyboard). This module maps
that text onto canonical concepts and ICD-10 codes *before* any LLM sees it,
so the model reasons over structure rather than guessing at dialect.

Matching is deliberately conservative: longest-match-first over normalized
text, no fuzzy scoring. A wrong concept is worse than a missing one — a missed
term degrades retrieval, an invented one can steer a differential.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DEFAULT_CSV = Path(__file__).parent / "terminology.csv"

#: Apostrophe variants that all mean the same letter in Uzbek Latin
#: (o', g', and the glottal stop). Keyboards, phones and OCR each produce a
#: different one; they must not produce different concepts.
_APOSTROPHES = "’‘ʻʼ`´'"

#: Cyrillic → Latin for Uzbek written in Cyrillic. Enough to normalise the
#: terms clinicians actually type; not a general transliterator.
_UZ_CYRILLIC = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "j",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "x",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sh",
    "ъ": "",
    "ы": "i",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
    "ў": "o",
    "қ": "q",
    "ғ": "g",
    "ҳ": "h",
}

#: British/American digraphs folded before lookup. WHO writes "anaemia",
#: "diarrhoea", "paediatric"; clinicians and MoH translations write the other
#: form. Without folding, a chunk and a query about the same thing never meet.
_SPELLING_DIGRAPHS = (
    ("aemia", "emia"),
    ("aemic", "emic"),
    ("hoea", "hea"),
    ("oede", "ede"),
    ("paed", "ped"),
    ("anae", "ane"),
    ("haem", "hem"),
    ("oesop", "esop"),
    ("gynae", "gyne"),
    ("orrhoe", "orrhe"),
)

RED_FLAG_CATEGORY = "red_flag"

#: Uzbek is agglutinative: "pnevmoniya" appears in real protocol text as
#: "pnevmoniyani", "pnevmoniyaning", "pnevmoniyadan". Requiring a whole-token
#: match therefore misses most real occurrences. We allow a match to be
#: followed by a short suffix inside the same token — long enough for the case
#: and possessive endings, short enough that "isitmasizlikxyz" is still not a
#: fever. The left boundary stays strict: a term must start a token.
MAX_SUFFIX_CHARS = 5


#: Numeric findings that carry clinical meaning on their own. A clinician
#: types "qon bosimi 160/95" and means hypertension; a pure word map cannot
#: see that. Thresholds follow the protocols in knowledge/corpus.
_BP_PATTERN = re.compile(r"\b(\d{2,3})\s*/\s*(\d{2,3})\b")
_TEMP_PATTERN = re.compile(r"\b(3[5-9][.,]\d|4[0-2][.,]?\d?)\s*(?:°|c\b|с\b)", re.IGNORECASE)
_SPO2_PATTERN = re.compile(r"\b(?:spo2|sat[a-z]*)\D{0,12}?(\d{2,3})\s*%?", re.IGNORECASE)
_GLUCOSE_PATTERN = re.compile(r"\b(\d{1,2}[.,]?\d?)\s*mmol", re.IGNORECASE)


def fold_spelling(text: str) -> str:
    folded = text
    for british, american in _SPELLING_DIGRAPHS:
        folded = folded.replace(british, american)
    return folded


@dataclass(frozen=True)
class Term:
    term_uz: str
    term_ru: str | None
    term_en: str
    icd10: str | None
    concept: str
    category: str
    synonyms: tuple[str, ...] = field(default=())

    @property
    def is_red_flag(self) -> bool:
        return self.category == RED_FLAG_CATEGORY


@dataclass(frozen=True)
class Match:
    """One recognised term, with where it was found."""

    term: Term
    surface: str
    start: int
    end: int
    language: str  # which side of the map matched: uz or ru


def normalize(text: str) -> str:
    """Fold case, apostrophe variants and Cyrillic so lookups are stable.

    Russian text is left in Cyrillic — only Uzbek-specific letters are
    transliterated, because Russian terms are matched against the Russian
    column directly.
    """
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(f"[{re.escape(_APOSTROPHES)}]", "'", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _latinize_uz(text: str) -> str:
    return "".join(_UZ_CYRILLIC.get(ch, ch) for ch in text)


def _key(text: str) -> str:
    """Lookup key: normalized, apostrophes dropped entirely.

    "yo'tal" and "yotal" are the same word typed by two different people.
    """
    return fold_spelling(normalize(text)).replace("'", "")


class TerminologyMap:
    def __init__(self, terms: list[Term]) -> None:
        self.terms = terms
        self._by_concept = {t.concept: t for t in terms}
        self._index: dict[str, tuple[Term, str]] = {}
        for term in terms:
            self._add(term.term_uz, term, "uz")
            for synonym in term.synonyms:
                self._add(synonym, term, "uz")
            if term.term_ru:
                self._add(term.term_ru, term, "ru")
            # English is indexed too: the corpus mixes WHO guidance in English
            # with MoH protocols in Uzbek, so concepts have to be reachable
            # from every side.
            self._add(term.term_en, term, "en")
        # Longest surface first, so "quruq yo'tal" wins over "yo'tal".
        self._surfaces = sorted(self._index, key=len, reverse=True)

    def _add(self, surface: str, term: Term, language: str) -> None:
        key = _key(surface)
        if key and key not in self._index:
            self._index[key] = (term, language)

    def __len__(self) -> int:
        return len(self.terms)

    @property
    def surface_count(self) -> int:
        """Total distinct strings a clinician can type and be understood."""
        return len(self._index)

    def all_surfaces(self) -> list[str]:
        """Every distinct string a clinician can type and be understood.

        Used by the evaluation overlap report to find vocabulary the test set
        never exercises — coverage we claim but do not measure.
        """
        return list(self._index)

    def lookup(self, surface: str) -> Term | None:
        entry = self._index.get(_key(surface))
        return entry[0] if entry else None

    def by_concept(self, concept: str) -> Term | None:
        return self._by_concept.get(concept)

    def _scan(self, haystack: str) -> list[Match]:
        claimed: list[tuple[int, int]] = []
        matches: list[Match] = []

        for surface in self._surfaces:
            start = 0
            while True:
                index = haystack.find(surface, start)
                if index == -1:
                    break
                end = index + len(surface)
                start = index + 1
                # Whole-token matches only: "isitma" must not match inside a
                # longer unrelated word.
                if index > 0 and haystack[index - 1].isalnum():
                    continue
                if end < len(haystack) and haystack[end].isalnum():
                    suffix_end = end
                    while suffix_end < len(haystack) and haystack[suffix_end].isalnum():
                        suffix_end += 1
                    if suffix_end - end > MAX_SUFFIX_CHARS:
                        continue
                    end = suffix_end
                if any(index < c_end and c_start < end for c_start, c_end in claimed):
                    continue
                term, language = self._index[surface]
                claimed.append((index, end))
                matches.append(
                    Match(term=term, surface=surface, start=index, end=end, language=language)
                )
        return matches

    def extract(self, text: str) -> list[Match]:
        """Find every known term in free text, longest match first.

        Two passes, because a clinic sees three scripts on one keyboard:
        Russian in Cyrillic, Uzbek in Latin, and Uzbek in Cyrillic. Pass one
        reads the text as written (catching Russian and Latin Uzbek); pass two
        transliterates Cyrillic to Latin (catching Uzbek written in Cyrillic).
        Results are merged and de-duplicated by concept, so a term found in
        both passes is reported once.

        Overlapping matches are dropped within a pass: once "quruq yo'tal" is
        claimed, the "yo'tal" inside it is not reported again. Offsets index
        the normalized text of the pass that produced the match, not the raw
        input — they are for highlighting, not for slicing the original.
        """
        normalized = normalize(text)
        found = self._scan(_key(normalized))
        latinized = _key(_latinize_uz(normalized))
        if latinized != _key(normalized):
            found.extend(self._scan(latinized))

        seen: set[str] = set()
        deduped: list[Match] = []
        for match in sorted(found, key=lambda m: (m.start, -(m.end - m.start))):
            if match.term.concept in seen:
                continue
            seen.add(match.term.concept)
            deduped.append(match)
        return deduped

    def concepts_in(self, text: str) -> list[str]:
        seen: list[str] = []
        for match in self.extract(text):
            if match.term.concept not in seen:
                seen.append(match.term.concept)
        return seen

    def numeric_concepts(self, text: str) -> list[str]:
        """Concepts implied by numbers in the text, not by its words.

        Deliberately conservative: only findings whose thresholds are stated in
        the committed protocols, and only in the abnormal direction. A normal
        reading adds no concept rather than adding a "normal" one.
        """
        concepts: list[str] = []

        for systolic, diastolic in _BP_PATTERN.findall(text):
            top, bottom = int(systolic), int(diastolic)
            if not (50 <= top <= 300 and 20 <= bottom <= 200):
                continue
            if top >= 140 or bottom >= 90:
                concepts.append("hypertension")
            elif top < 90:
                concepts.append("hypotension")

        for reading in _TEMP_PATTERN.findall(text):
            if float(reading.replace(",", ".")) >= 38.0:
                concepts.append("fever")

        for reading in _SPO2_PATTERN.findall(text):
            value = int(reading)
            if 40 <= value < 92:
                concepts.append("dyspnea")

        for reading in _GLUCOSE_PATTERN.findall(text):
            if float(reading.replace(",", ".")) >= 7.0:
                concepts.append("diabetes_t2")

        return list(dict.fromkeys(concepts))

    def clinical_concepts(self, text: str) -> list[str]:
        """Concepts from words and from numbers — what retrieval should use."""
        merged = self.concepts_in(text) + [
            c for c in self.numeric_concepts(text) if c not in self.concepts_in(text)
        ]
        return list(dict.fromkeys(merged))

    def concept_counts(self, text: str) -> dict[str, int]:
        """How often each concept occurs — the term-frequency side of ranking."""
        counts: dict[str, int] = {}
        haystack = _key(_latinize_uz(normalize(text)))
        for concept in self.clinical_concepts(text):
            if concept not in self._by_concept:
                counts[concept] = 1
                continue
            term = self._by_concept[concept]
            occurrences = 0
            for surface in (term.term_uz, term.term_ru, term.term_en, *term.synonyms):
                if surface:
                    occurrences += haystack.count(_key(surface))
            counts[concept] = max(occurrences, 1)
        return counts

    def icd10_candidates(self, text: str) -> list[str]:
        codes: list[str] = []
        for match in self.extract(text):
            if match.term.icd10 and match.term.icd10 not in codes:
                codes.append(match.term.icd10)
        return codes

    def red_flag_terms(self, text: str) -> list[Term]:
        return [m.term for m in self.extract(text) if m.term.is_red_flag]

    def expand(self, text: str) -> list[str]:
        """Every language's wording for the concepts found in `text`.

        This is what makes cross-lingual retrieval work: an Uzbek query is
        expanded with the Russian and English terms and the ICD-10 codes for
        the same concepts, so it can reach an English WHO protocol without a
        translation model in the request path.
        """
        expansions: list[str] = []
        for match in self.extract(text):
            term = match.term
            candidates = (term.term_uz, term.term_ru, term.term_en, term.icd10, *term.synonyms)
            for candidate in candidates:
                if candidate and candidate not in expansions:
                    expansions.append(candidate)
            readable = term.concept.replace("_", " ")
            if readable not in expansions:
                expansions.append(readable)
        return expansions

    def expand_query(self, text: str) -> str:
        """The original query plus its expansions, for lexical retrieval."""
        expansions = self.expand(text)
        return f"{text} {' '.join(expansions)}" if expansions else text

    def translate(self, surface: str, target: str) -> str | None:
        """Map a term into another language, for round-tripping output."""
        term = self.lookup(surface)
        if term is None:
            return None
        return {"uz": term.term_uz, "ru": term.term_ru, "en": term.term_en}.get(target)


def load_terms(path: Path | str = DEFAULT_CSV) -> list[Term]:
    rows: list[Term] = []
    with Path(path).open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            synonyms = tuple(s.strip() for s in (row.get("synonyms") or "").split("|") if s.strip())
            rows.append(
                Term(
                    term_uz=row["term_uz"].strip(),
                    term_ru=(row["term_ru"] or "").strip() or None,
                    term_en=row["term_en"].strip(),
                    icd10=(row["icd10"] or "").strip() or None,
                    concept=row["concept"].strip(),
                    category=(row["category"] or "symptom").strip(),
                    synonyms=synonyms,
                )
            )
    return rows


@lru_cache
def get_terminology(path: str | None = None) -> TerminologyMap:
    return TerminologyMap(load_terms(Path(path) if path else DEFAULT_CSV))


if __name__ == "__main__":  # pragma: no cover - manual inspection helper
    mapping = get_terminology()
    print(f"{len(mapping)} concepts, {mapping.surface_count} recognised surfaces")
    for sample in [
        "3 kundan beri yo'tal va isitma bor, kechasi terlayman",
        "у пациента сильная боль в груди и одышка",
        "boshim ogriyapti va kongim aynyapti",
    ]:
        print(f"\n{sample}\n  → {mapping.concepts_in(sample)}")
