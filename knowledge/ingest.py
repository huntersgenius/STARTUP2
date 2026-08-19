"""Protocol ingestion: PDF/markdown → clean text → chunks → embeddings → store.

Run:
    python -m knowledge.ingest --corpus knowledge/corpus --reset

Every chunk keeps source, section, page, language and version, because a
recommendation a clinician cannot trace back to a named protocol version is
not usable evidence — for them or for the regulator.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.providers.embeddings import get_embeddings
from app.ai.rag.chunking import chunk_markdown, parse_frontmatter
from app.core.db import get_sessionmaker
from app.models.knowledge import FormularyItem, ProtocolChunk, TerminologyEntry
from knowledge.terminology import get_terminology

DEFAULT_CORPUS = Path(__file__).parent / "corpus"


@dataclass
class Document:
    source_id: str
    title: str
    publisher: str
    version: str
    language: str
    body: str
    filters: dict
    page: int | None = None


def read_markdown(path: Path) -> Document:
    raw = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw)
    missing = [
        k for k in ("source_id", "title", "publisher", "version", "language") if k not in meta
    ]
    if missing:
        raise ValueError(f"{path.name}: missing frontmatter keys {missing}")
    return Document(
        source_id=str(meta["source_id"]),
        title=str(meta["title"]),
        publisher=str(meta["publisher"]),
        version=str(meta["version"]),
        language=str(meta["language"]),
        body=body,
        filters={
            "age_bands": meta.get("age_bands", []),
            "icd10": meta.get("icd10", []),
            "sex": meta.get("sex", []),
            "regions": meta.get("regions", []),
        },
    )


def read_pdf(path: Path) -> list[Document]:
    """Extract a PDF page by page so citations keep real page numbers.

    pypdf is an optional dependency: the committed corpus is markdown so that
    tests and CI never need it. Install it to ingest MoH PDF protocols.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - optional path
        raise RuntimeError(
            "PDF ingestion needs pypdf: pip install pypdf. "
            "The committed corpus is markdown and does not require it."
        ) from exc

    reader = PdfReader(str(path))
    stem = path.stem
    docs: list[Document] = []
    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        docs.append(
            Document(
                source_id=stem,
                title=stem.replace("-", " ").title(),
                publisher="unknown",
                version="unversioned",
                language="uz",
                body=text,
                filters={},
                page=number,
            )
        )
    return docs


def load_documents(corpus: Path) -> list[Document]:
    docs: list[Document] = []
    for path in sorted(corpus.rglob("*")):
        if path.suffix.lower() in (".md", ".markdown"):
            docs.append(read_markdown(path))
        elif path.suffix.lower() == ".pdf":
            docs.extend(read_pdf(path))
    return docs


def ingest_documents(db: Session, docs: list[Document], *, prefer_offline: bool = False) -> int:
    embedder = get_embeddings(prefer_offline=prefer_offline)
    written = 0

    for doc in docs:
        # Re-ingesting a source replaces it wholesale: a protocol update must
        # never leave stale chunks of the old version retrievable.
        db.execute(delete(ProtocolChunk).where(ProtocolChunk.source_id == doc.source_id))

        chunks = chunk_markdown(doc.body) if doc.page is None else _plain_chunks(doc.body)
        if not chunks:
            continue
        vectors = embedder.embed([c.text for c in chunks])
        terminology = get_terminology()
        for chunk, vector in zip(chunks, vectors, strict=True):
            db.add(
                ProtocolChunk(
                    source_id=doc.source_id,
                    source_title=doc.title,
                    publisher=doc.publisher,
                    version=doc.version,
                    language=doc.language,
                    page=doc.page,
                    section=chunk.section or None,
                    chunk_index=chunk.index,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    # Concepts are the interlingua between an Uzbek query and
                    # an English protocol; they are indexed per chunk, not per
                    # document, so retrieval can pick the right section.
                    filters={
                        **doc.filters,
                        "concepts": terminology.clinical_concepts(chunk.text),
                        "concept_counts": terminology.concept_counts(chunk.text),
                    },
                    embedding=vector,
                )
            )
            written += 1
    db.flush()
    return written


def _plain_chunks(text: str):
    from app.ai.rag.chunking import Chunk, estimate_tokens

    return [Chunk(text=text, section="", index=0, token_count=estimate_tokens(text))]


def load_formulary(db: Session, csv_path: Path) -> int:
    import csv

    db.execute(delete(FormularyItem))
    count = 0
    with csv_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            db.add(
                FormularyItem(
                    generic_name=row["generic_name"].strip().lower(),
                    name_uz=(row.get("name_uz") or "").strip() or None,
                    name_ru=(row.get("name_ru") or "").strip() or None,
                    form=row["form"].strip().lower(),
                    strength=(row.get("strength") or "").strip() or None,
                    atc_code=(row.get("atc_code") or "").strip() or None,
                    availability_tier=int(row.get("availability_tier") or 2),
                    controlled=(row.get("controlled") or "false").strip().lower() == "true",
                    pediatric_ok=(row.get("pediatric_ok") or "true").strip().lower() == "true",
                    pregnancy_category=(row.get("pregnancy_category") or "").strip() or None,
                    typical_cost_uzs=float(row["typical_cost_uzs"])
                    if row.get("typical_cost_uzs")
                    else None,
                    notes=(row.get("notes") or "").strip() or None,
                )
            )
            count += 1
    db.flush()
    return count


def load_terminology_table(db: Session, csv_path: Path) -> int:
    from knowledge.terminology import load_terms

    db.execute(delete(TerminologyEntry))
    terms = load_terms(csv_path)
    for term in terms:
        db.add(
            TerminologyEntry(
                term_uz=term.term_uz,
                term_ru=term.term_ru,
                term_en=term.term_en,
                icd10=term.icd10,
                concept=term.concept,
                category=term.category,
                synonyms=list(term.synonyms),
            )
        )
    db.flush()
    return len(terms)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest clinical protocols into the RAG store")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--formulary", type=Path, default=Path(__file__).parent / "formulary.csv")
    parser.add_argument(
        "--terminology", type=Path, default=Path(__file__).parent / "terminology.csv"
    )
    parser.add_argument("--reset", action="store_true", help="drop existing chunks first")
    parser.add_argument("--offline", action="store_true", help="force the offline embedder")
    args = parser.parse_args(argv)

    if not args.corpus.exists():
        print(f"corpus not found: {args.corpus}", file=sys.stderr)
        return 1

    session = get_sessionmaker()()
    try:
        if args.reset:
            session.execute(delete(ProtocolChunk))
        docs = load_documents(args.corpus)
        chunks = ingest_documents(session, docs, prefer_offline=args.offline)
        drugs = load_formulary(session, args.formulary) if args.formulary.exists() else 0
        terms = (
            load_terminology_table(session, args.terminology) if args.terminology.exists() else 0
        )
        session.commit()
        total = session.execute(select(ProtocolChunk)).scalars().all()
        print(
            f"ingested {len(docs)} documents → {chunks} chunks "
            f"({len(total)} in store), {drugs} formulary items, {terms} terminology entries"
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
