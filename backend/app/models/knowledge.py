from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import JSONBType, Vector


class ProtocolChunk(Base, UUIDMixin, TimestampMixin):
    """One retrievable slice of a clinical protocol, with its citation intact."""

    __tablename__ = "protocol_chunks"
    __table_args__ = (UniqueConstraint("source_id", "chunk_index", name="uq_source_chunk"),)

    source_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_title: Mapped[str] = mapped_column(String(300), nullable=False)
    publisher: Mapped[str] = mapped_column(String(120), nullable=False)  # WHO, UzMoH, ...
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    language: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String(300), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Retrieval filters: age bands, sex, icd10 codes, region tags.
    filters: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(get_settings().embedding_dim), nullable=True
    )

    @property
    def citation(self) -> str:
        bits = [self.publisher, self.source_title, f"v{self.version}"]
        if self.section:
            bits.append(self.section)
        if self.page:
            bits.append(f"p.{self.page}")
        return " · ".join(bits)


class FormularyItem(Base, UUIDMixin, TimestampMixin):
    """A medicine that is actually obtainable in Uzbek primary care."""

    __tablename__ = "formulary_items"
    # Strength is part of the identity: metformin 500 mg and metformin 1000 mg
    # are separate stock items with separate availability.
    __table_args__ = (
        UniqueConstraint("generic_name", "form", "strength", name="uq_generic_form_strength"),
    )

    generic_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    name_uz: Mapped[str | None] = mapped_column(String(160), nullable=True)
    name_ru: Mapped[str | None] = mapped_column(String(160), nullable=True)
    form: Mapped[str] = mapped_column(String(60), nullable=False)  # tablet, syrup, injection
    strength: Mapped[str | None] = mapped_column(String(60), nullable=True)
    atc_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: 1 = stocked at feldsher points, 2 = rayon pharmacy, 3 = oblast/city only.
    availability_tier: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    controlled: Mapped[bool] = mapped_column(default=False, nullable=False)
    pediatric_ok: Mapped[bool] = mapped_column(default=True, nullable=False)
    pregnancy_category: Mapped[str | None] = mapped_column(String(8), nullable=True)
    typical_cost_uzs: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class TerminologyEntry(Base, UUIDMixin, TimestampMixin):
    """Uzbek colloquial term → Russian → English → ICD-10 concept."""

    __tablename__ = "terminology_entries"

    term_uz: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    term_ru: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    term_en: Mapped[str] = mapped_column(String(160), nullable=False)
    icd10: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    concept: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(60), default="symptom", nullable=False)
    #: Colloquial/dialect spellings that map to the same concept.
    synonyms: Mapped[list[str]] = mapped_column(JSONBType, default=list, nullable=False)
