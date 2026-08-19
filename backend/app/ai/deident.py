"""De-identification.

Every payload leaving this process for a third-party model passes through
`deidentify`. The contract is narrow and absolute: **no direct identifier may
survive**. Where the choice is between over-redacting a clinical word and
letting a name through, we over-redact — a redacted symptom degrades one
suggestion, a leaked name is a reportable breach.

Two layers, because pattern matching alone cannot make an absolute guarantee:

1. **Known-value redaction (the guarantee).** The patient's own identifiers
   are already in our database, decrypted from `Patient.pii_blob`. They are
   redacted by exact match, with tolerance for Uzbek case suffixes
   ("Feruza" also matches "Feruzani"). This layer is complete by construction,
   and it is what `assert_no_pii` verifies before any outbound call.
2. **Pattern and gazetteer net (defence in depth).** Free text may mention
   people who are not the patient — a relative, a contact — whose values we do
   not hold. Regex rules plus a given-name gazetteer catch most of those. This
   layer is measured, not assumed: `tests/test_deident.py` reports its recall
   and holds it above a floor rather than claiming perfection.

Anything relying on layer 2 alone is best-effort. Anything the patient record
knows about is guaranteed.

Identifiers are replaced with stable tokens (`[NAME_1]`, `[PHONE_1]`) rather
than deleted, so the model still sees that a person was referred to, and so
the local re-identification step can put the real value back.

The red-team suite in `tests/test_deident.py` runs 100+ realistic Uzbek and
Russian texts through this module and asserts zero leakage. That test may
never be skipped — CI runs it as a separate, named job.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from knowledge.terminology import MAX_SUFFIX_CHARS

#: Keys whose values are identifiers by definition, whatever they contain.
PII_KEYS = {
    "full_name",
    "name",
    "first_name",
    "last_name",
    "patient_name",
    "father_name",
    "middle_name",
    "phone",
    "phone_number",
    "mobile",
    "tel",
    "passport",
    "passport_no",
    "pinfl",
    "jshshir",
    "address",
    "street",
    "mahalla",
    "email",
    "mrn",
    "national_id",
    "insurance_no",
    "card_no",
}


@dataclass
class _Rule:
    label: str
    pattern: re.Pattern[str]
    #: Which capture group holds the identifier itself (0 = whole match).
    group: int = 0


def _compile(pattern: str, flags: int = re.IGNORECASE | re.UNICODE) -> re.Pattern[str]:
    return re.compile(pattern, flags)


# Order matters: longer, more specific patterns run first so a passport number
# is not partially consumed by the generic long-digit rule.
RULES: tuple[_Rule, ...] = (
    # PINFL / JSHSHIR — the Uzbek national identifier, 14 digits.
    _Rule("ID", _compile(r"\b\d{14}\b")),
    # Passport: two Latin or Cyrillic letters then 7 digits (AA1234567).
    _Rule("PASSPORT", _compile(r"\b[A-ZА-Я]{2}\s?\d{7}\b")),
    # Phone: +998 XX XXX XX XX and the many ways people write it.
    _Rule(
        "PHONE", _compile(r"(?:\+?998|8)?[\s\-]*\(?\d{2}\)?[\s\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}\b")
    ),
    _Rule("PHONE", _compile(r"\(\d{2}\)[\s\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}\b")),
    _Rule("EMAIL", _compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")),
    # Card numbers (16 digits, spaced or not) before generic digit runs.
    _Rule("CARD", _compile(r"\b(?:\d{4}[\s\-]?){4}\b")),
    # Addresses: "... ko'chasi 12", "ул. Навои д. 5", mahalla names.
    _Rule(
        "ADDRESS",
        _compile(
            r"\b[\w'’ʻ\-]+\s*(?:ko'chasi|kochasi|ko‘chasi|kӯchasi|küchasi|mahallasi|mahalla|MFY|mfy|tumani|shahri|qishlog'i|qishlogi)"
            r"(?:\s*,?\s*(?:d\.|dom|uy|xonadon|kv\.?|kvartira)?\s*\d+[a-zа-я]?)?"
        ),
    ),
    _Rule(
        "ADDRESS",
        _compile(
            r"\b(?:ул\.|улица|мкр\.?|микрорайон|массив|проспект|пр-т)\s*[\w\-]+"
            r"(?:\s*,?\s*(?:д\.|дом|кв\.?|квартира)\s*\d+[а-я]?)*"
        ),
    ),
    # Dates of birth, which are identifiers in combination.
    _Rule("DOB", _compile(r"\b\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2}\b")),
    _Rule("DOB", _compile(r"\b(?:19|20)\d{2}[./-]\d{1,2}[./-]\d{1,2}\b")),
)

#: Titles that reliably precede a personal name in Uzbek or Russian clinical
#: notes. Matching on the title avoids guessing which capitalised word is a
#: name, which is unreliable in text where diseases are also capitalised.
NAME_TITLES = (
    r"bemor",
    r"bemorimiz",
    r"kasal",
    r"o'rtoq",
    r"janob",
    r"xonim",
    r"aka",
    r"opa",
    r"пациент(?:ка)?",
    r"больн(?:ой|ая)",
    r"гражданин",
    r"гражданка",
    r"тов\.",
    r"г-н",
    r"г-жа",
)

#: Uzbek and Russian family-name endings. Used only to confirm a token that is
#: already capitalised and adjacent to a name context.
_SURNAME_SUFFIX = re.compile(
    r"(ov|ova|yev|yeva|ev|eva|jon|xon|boy|zoda|zoda|ovich|ovna|evich|evna|ин|ина|ов|ова|ев|ева|ский|ская)$",
    re.IGNORECASE,
)

_CAPWORD = r"[A-ZА-ЯЎҚҒҲ][\w'’ʻ\-]{1,}"

NAME_RULES: tuple[re.Pattern[str], ...] = (
    # "bemor Aziza Yusupova", "пациентка Гулнора Ташева"
    _compile(rf"(?:{'|'.join(NAME_TITLES)})\s+((?:{_CAPWORD})(?:\s+{_CAPWORD}){{0,2}})"),
    # "Familiya: Yusupova", "Ф.И.О.: Ташева Гулнора"
    _compile(
        rf"(?:F\.?I\.?SH\.?|FISH|Familiya(?:si)?|Ismi|Ф\.?И\.?О\.?|Фамилия|Имя)\s*[:\-]?\s*"
        rf"((?:{_CAPWORD})(?:\s+{_CAPWORD}){{0,2}})"
    ),
)


@dataclass
class DeidentificationResult:
    text: str
    #: token → original value, kept in-process for local re-identification.
    mapping: dict[str, str] = field(default_factory=dict)
    #: Count of redactions per label, for the audit record.
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def redaction_count(self) -> int:
        return sum(self.counts.values())


class PiiLeakError(AssertionError):
    """Raised when a payload still contains a known identifier."""


class Deidentifier:
    def __init__(self) -> None:
        self._counter: dict[str, int] = {}
        self._seen: dict[str, str] = {}

    def _token(self, label: str, value: str) -> str:
        """Stable token per distinct value, so the same person reads the same."""
        key = f"{label}:{_normalize_for_compare(value)}"
        if key in self._seen:
            return self._seen[key]
        self._counter[label] = self._counter.get(label, 0) + 1
        token = f"[{label}_{self._counter[label]}]"
        self._seen[key] = token
        return token

    def _redact_known(
        self, text: str, known_values: list[str], mapping: dict[str, str], counts: dict[str, int]
    ) -> str:
        """Layer 1: redact values we already hold for this patient.

        Longest first, so "Aziza Yusupova" is one NAME token rather than two.
        Uzbek attaches case suffixes to names ("Feruzani", "Rahimovga"), so a
        known value may be followed by up to MAX_SUFFIX_CHARS word characters.
        """
        for value in sorted(
            {v for v in known_values if v and len(v.strip()) > 2}, key=len, reverse=True
        ):
            label = _label_for_value(value)
            pattern = re.compile(
                rf"(?<![\w']){re.escape(value.strip())}\w{{0,{MAX_SUFFIX_CHARS}}}",
                re.IGNORECASE | re.UNICODE,
            )

            def replace_known(match: re.Match[str], label: str = label, value: str = value) -> str:
                token = self._token(label, value)
                mapping[token] = match.group(0)
                counts[label] = counts.get(label, 0) + 1
                return token

            text = pattern.sub(replace_known, text)
        return text

    def scrub(self, text: str, known_values: list[str] | None = None) -> DeidentificationResult:
        if not text:
            return DeidentificationResult(text=text)

        mapping: dict[str, str] = {}
        counts: dict[str, int] = {}
        scrubbed = text

        if known_values:
            scrubbed = self._redact_known(scrubbed, known_values, mapping, counts)

        def replace(match: re.Match[str], label: str, group: int) -> str:
            value = match.group(group)
            if not value or not value.strip():
                return match.group(0)
            token = self._token(label, value)
            mapping[token] = value
            counts[label] = counts.get(label, 0) + 1
            whole = match.group(0)
            return whole.replace(value, token) if group else token

        # Names first: the name rules rely on surrounding words that later
        # rules might otherwise consume.
        def replace_name(match: re.Match[str]) -> str:
            return replace(match, "NAME", 1)

        for pattern in NAME_RULES:
            scrubbed = pattern.sub(replace_name, scrubbed)

        for rule in RULES:

            def replace_rule(match: re.Match[str], current: _Rule = rule) -> str:
                return replace(match, current.label, current.group)

            scrubbed = rule.pattern.sub(replace_rule, scrubbed)

        # Any remaining capitalised token that is either a known given name or
        # carries a family-name ending is treated as a personal name.
        def surname_sub(match: re.Match[str]) -> str:
            word = match.group(0)
            if _is_clinical_word(word):
                return word
            stem = _strip_suffix(word)
            looks_like_name = (
                bool(_SURNAME_SUFFIX.search(word))
                or stem in GIVEN_NAMES
                or word.casefold() in SHORT_SURNAMES
            )
            if not looks_like_name:
                return word
            token = self._token("NAME", word)
            mapping[token] = word
            counts["NAME"] = counts.get("NAME", 0) + 1
            return token

        scrubbed = re.sub(_CAPWORD, surname_sub, scrubbed)

        return DeidentificationResult(text=scrubbed, mapping=mapping, counts=counts)


#: Capitalised words that end in a surname-like suffix but are clinical terms.
#: Without this, "Gastritis" or "Пневмония" would be redacted as names.
_CLINICAL_ALLOWLIST = {
    "pnevmoniya",
    "gastrit",
    "gastritis",
    "bronxit",
    "diabet",
    "anemiya",
    "gipertoniya",
    "gipotoniya",
    "astma",
    "tuberkulyoz",
    "helikobakter",
    "xelikobakter",
    "koronavirus",
    "gripp",
    "otit",
    "sinusit",
    "artrit",
    "migren",
    "infarkt",
    "insult",
    "sepsis",
    "пневмония",
    "гастрит",
    "бронхит",
    "диабет",
    "анемия",
    "гипертония",
    "гипотония",
    "астма",
    "туберкулёз",
    "туберкулез",
    "хеликобактер",
    "грипп",
    "отит",
    "синусит",
    "артрит",
    "мигрень",
    "инфаркт",
    "инсульт",
    "сепсис",
    "температура",
    "давление",
    "лечение",
    "диарея",
    "паратсетамол",
    "парацетамол",
    "амоксициллин",
    "метформин",
}


#: Given names common in Uzbekistan. A given name carries no surname suffix,
#: so nothing else in the pattern layer can recognise it. This list is a net
#: for names in free text, not the guarantee — that is layer 1.
GIVEN_NAMES = {
    name.casefold()
    for name in (
        "Aziza",
        "Dilshod",
        "Nodira",
        "Bekzod",
        "Gulnora",
        "Sardor",
        "Zulfiya",
        "Jasur",
        "Malika",
        "Otabek",
        "Shahnoza",
        "Rustam",
        "Feruza",
        "Ulug'bek",
        "Kamola",
        "Nilufar",
        "Aziz",
        "Akmal",
        "Anvar",
        "Bahodir",
        "Botir",
        "Davron",
        "Doniyor",
        "Elyor",
        "Farrux",
        "Firuza",
        "Gulbahor",
        "Hasan",
        "Husan",
        "Iroda",
        "Islom",
        "Javohir",
        "Kamron",
        "Laziz",
        "Lola",
        "Madina",
        "Mehri",
        "Muhammad",
        "Mustafo",
        "Nargiza",
        "Nozima",
        "Odil",
        "Oybek",
        "Ozoda",
        "Qodir",
        "Ravshan",
        "Sabina",
        "Saida",
        "Sherzod",
        "Sitora",
        "Temur",
        "Timur",
        "Umid",
        "Xurshid",
        "Yulduz",
        "Zafar",
        "Zarina",
        "Zilola",
        "Aziznjon",
        "Абдулла",
        "Азиза",
        "Алексей",
        "Анна",
        "Виктор",
        "Гульнора",
        "Дилшод",
        "Дмитрий",
        "Елена",
        "Ирина",
        "Марина",
        "Мария",
        "Наталья",
        "Ольга",
        "Сергей",
        "Тимур",
        "Шахноза",
        "Юлия",
        "Александр",
        "Владимир",
        "Екатерина",
        "Светлана",
        "Татьяна",
        "Николай",
    )
}

#: Short surnames with no recognisable suffix. Korean-Uzbek families
#: (deported to Central Asia in 1937 and long settled) are a substantial part
#: of the population, and "Ким", "Цой", "Пак", "Ли" defeat every suffix rule.
SHORT_SURNAMES = {
    name.casefold()
    for name in ("Ким", "Цой", "Пак", "Ли", "Тен", "Хан", "Шин", "Юн", "Kim", "Tsoy", "Pak", "Li")
}

#: Uzbek case and possessive endings that attach directly to a name.
_NAME_SUFFIXES = (
    "ning",
    "ga",
    "ni",
    "da",
    "dan",
    "ku",
    "cha",
    "day",
    "dek",
    "lar",
    "lari",
    "im",
    "ing",
    "si",
    "i",
    "niki",
    "gacha",
)


def _strip_suffix(word: str) -> str:
    """Best-effort stem for an agglutinated Uzbek name."""
    folded = word.casefold()
    if folded in GIVEN_NAMES:
        return folded
    for suffix in sorted(_NAME_SUFFIXES, key=len, reverse=True):
        if folded.endswith(suffix) and len(folded) - len(suffix) >= 3:
            candidate = folded[: -len(suffix)]
            if candidate in GIVEN_NAMES:
                return candidate
    return folded


def _label_for_value(value: str) -> str:
    """Classify a known identifier so its token reads sensibly to the model."""
    stripped = value.strip()
    if re.fullmatch(r"[\d\s\-+()]{7,}", stripped):
        return "PHONE"
    if re.fullmatch(r"[A-ZА-Я]{2}\s?\d{7}", stripped, re.IGNORECASE):
        return "PASSPORT"
    if re.fullmatch(r"\d{14}", stripped):
        return "ID"
    if "@" in stripped:
        return "EMAIL"
    if re.search(r"\d", stripped) and len(stripped.split()) > 1:
        return "ADDRESS"
    if any(
        marker in stripped.casefold()
        for marker in (
            "tumani",
            "mahalla",
            "mfy",
            "ko'chasi",
            "kochasi",
            "shahri",
            "qishlog",
            "ул.",
            "мкр",
            "проспект",
            "массив",
        )
    ):
        return "ADDRESS"
    return "NAME"


def _is_clinical_word(word: str) -> bool:
    return word.casefold() in _CLINICAL_ALLOWLIST


def _normalize_for_compare(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def deidentify(text: str, known_values: list[str] | None = None) -> DeidentificationResult:
    """Scrub one free-text field.

    Pass `known_values` (the patient's own identifiers) whenever they are
    available — that is the layer that makes the guarantee.
    """
    return Deidentifier().scrub(text, known_values)


def deidentify_payload(
    payload: dict[str, Any], known_values: list[str] | None = None
) -> tuple[dict[str, Any], dict[str, str]]:
    """Scrub a whole structured payload before it leaves the process.

    Values under a key in `PII_KEYS` are dropped outright rather than scrubbed:
    the key already tells us the value is an identifier, so pattern matching
    adds nothing but risk.
    """
    deidentifier = Deidentifier()
    mapping: dict[str, str] = {}

    def walk(node: Any, key_hint: str | None = None) -> Any:
        if isinstance(node, dict):
            return {k: walk(v, key_hint=k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, key_hint=key_hint) for v in node]
        if isinstance(node, str):
            if key_hint and key_hint.casefold() in PII_KEYS:
                token = deidentifier._token(_label_for_key(key_hint), node)
                mapping[token] = node
                return token
            result = deidentifier.scrub(node, known_values)
            mapping.update(result.mapping)
            return result.text
        return node

    return walk(payload), mapping


def _label_for_key(key: str) -> str:
    key = key.casefold()
    if "phone" in key or key in ("mobile", "tel"):
        return "PHONE"
    if "passport" in key or key in ("pinfl", "jshshir", "national_id"):
        return "ID"
    if "address" in key or key in ("street", "mahalla"):
        return "ADDRESS"
    if "email" in key:
        return "EMAIL"
    if key in ("mrn", "insurance_no", "card_no"):
        return "RECORD"
    return "NAME"


def reidentify(text: str, mapping: dict[str, str]) -> str:
    """Put the real values back, locally, after the model has answered."""
    for token, value in mapping.items():
        text = text.replace(token, value)
    return text


def assert_no_pii(payload: Any, known_values: list[str]) -> None:
    """Fail loudly if any known identifier survived.

    Called on every outbound AI payload with the patient's actual identifier
    values. This is the last line of defence and is deliberately a hard error:
    a suggestion is worth less than a breach.
    """
    haystack = _normalize_for_compare(
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    )
    leaked = []
    for value in known_values:
        if not value:
            continue
        needle = _normalize_for_compare(str(value))
        # Two characters or fewer cannot be checked meaningfully.
        if len(needle) <= 2:
            continue
        if needle in haystack:
            leaked.append(value)
    if leaked:
        digests = [hashlib.sha256(v.encode()).hexdigest()[:12] for v in leaked]
        # The exception message must not itself contain the identifier.
        raise PiiLeakError(f"identifier(s) survived de-identification: {digests}")


def input_hash(payload: Any) -> str:
    """SHA-256 of the de-identified payload, recorded on every AiSuggestion."""
    serialised = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, sort_keys=True, ensure_ascii=False)
    )
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()
