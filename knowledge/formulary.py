"""Formulary lookup.

The model may suggest any drug it has read about. This service is the gate
that decides whether a clinician in a Chinoz village can actually obtain it.
An unavailable drug is not silently dropped — it is flagged, with the nearest
available substitute, because the clinician needs to know what was intended.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge import FormularyItem

#: Therapeutic groups whose members treat the same primary-care indication.
#: A substitute is only ever *suggested for clinician review* — never swapped
#: into a prescription — because interchangeability depends on the patient, not
#: only on the class. Grouping is deliberately broader than pharmacological
#: class: when losartan is unavailable at a feldsher point, the clinically
#: useful answer is "enalapril or amlodipine is stocked", not "no substitute".
THERAPEUTIC_GROUPS: dict[str, tuple[str, ...]] = {
    "antihypertensive": (
        "enalapril",
        "lisinopril",
        "losartan",
        "amlodipine",
        "hydrochlorothiazide",
        "bisoprolol",
    ),
    "acid_suppression": ("omeprazole", "famotidine"),
    "analgesic_nsaid": ("ibuprofen", "diclofenac"),
    "analgesic_simple": ("paracetamol",),
    "antibiotic_respiratory": (
        "amoxicillin",
        "amoxicillin-clavulanate",
        "azithromycin",
        "clarithromycin",
        "co-trimoxazole",
        "doxycycline",
    ),
    "antihistamine": ("loratadine", "cetirizine"),
    "oral_hypoglycaemic": ("metformin", "gliclazide"),
    "iron_replacement": ("ferrous sulfate",),
    "anthelmintic": ("albendazole", "mebendazole"),
    "asthma_reliever": ("salbutamol",),
    "lipid_lowering": ("atorvastatin",),
}

_GROUP_OF_DRUG = {drug: group for group, drugs in THERAPEUTIC_GROUPS.items() for drug in drugs}


@dataclass(frozen=True)
class AvailabilityVerdict:
    """The answer to 'can this clinic actually give this drug?'"""

    requested: str
    available: bool
    item: FormularyItem | None
    #: 1 = feldsher point, 2 = rayon pharmacy, 3 = oblast/city only.
    tier: int | None
    controlled: bool
    substitute: FormularyItem | None
    reason: str

    @property
    def blocked(self) -> bool:
        """Controlled substances are never dispensable through this system."""
        return self.controlled


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


class FormularyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _all(self) -> list[FormularyItem]:
        return list(self.db.execute(select(FormularyItem)).scalars())

    def find(self, name: str, *, form: str | None = None) -> FormularyItem | None:
        """Match on generic name, local trade name, or a name embedded in text."""
        target = _normalize(name)
        items = self._all()

        exact = [
            i
            for i in items
            if target
            in {
                _normalize(i.generic_name),
                _normalize(i.name_uz or ""),
                _normalize(i.name_ru or ""),
            }
        ]
        if form:
            preferred = [i for i in exact if _normalize(i.form) == _normalize(form)]
            if preferred:
                return sorted(preferred, key=lambda i: i.availability_tier)[0]
        if exact:
            return sorted(exact, key=lambda i: i.availability_tier)[0]

        # "amoxicillin 500 mg three times daily" → amoxicillin
        for item in sorted(items, key=lambda i: -len(i.generic_name)):
            if re.search(rf"\b{re.escape(_normalize(item.generic_name))}\b", target):
                return item
        return None

    def substitute_for(self, item: FormularyItem, *, max_tier: int) -> FormularyItem | None:
        group = _GROUP_OF_DRUG.get(_normalize(item.generic_name))
        if not group:
            return None
        candidates = [
            i
            for i in self._all()
            if _normalize(i.generic_name) in THERAPEUTIC_GROUPS[group]
            and i.availability_tier <= max_tier
            and i.id != item.id
            and not i.controlled
        ]
        return sorted(candidates, key=lambda i: i.availability_tier)[0] if candidates else None

    def check(
        self,
        name: str,
        *,
        clinic_tier: int = 1,
        form: str | None = None,
        pediatric: bool = False,
        pregnant: bool = False,
    ) -> AvailabilityVerdict:
        item = self.find(name, form=form)
        if item is None:
            return AvailabilityVerdict(
                requested=name,
                available=False,
                item=None,
                tier=None,
                controlled=False,
                substitute=None,
                reason="not_in_national_formulary",
            )
        if item.controlled:
            return AvailabilityVerdict(
                requested=name,
                available=False,
                item=item,
                tier=item.availability_tier,
                controlled=True,
                substitute=None,
                reason="controlled_substance",
            )
        if pediatric and not item.pediatric_ok:
            return AvailabilityVerdict(
                requested=name,
                available=False,
                item=item,
                tier=item.availability_tier,
                controlled=False,
                substitute=self.substitute_for(item, max_tier=clinic_tier),
                reason="not_approved_for_children",
            )
        if pregnant and (item.pregnancy_category or "").upper() in ("D", "X"):
            return AvailabilityVerdict(
                requested=name,
                available=False,
                item=item,
                tier=item.availability_tier,
                controlled=False,
                substitute=self.substitute_for(item, max_tier=clinic_tier),
                reason=f"pregnancy_category_{(item.pregnancy_category or '').upper()}",
            )
        if item.availability_tier > clinic_tier:
            return AvailabilityVerdict(
                requested=name,
                available=False,
                item=item,
                tier=item.availability_tier,
                controlled=False,
                substitute=self.substitute_for(item, max_tier=clinic_tier),
                reason="not_stocked_at_this_tier",
            )
        return AvailabilityVerdict(
            requested=name,
            available=True,
            item=item,
            tier=item.availability_tier,
            controlled=False,
            substitute=None,
            reason="available",
        )
