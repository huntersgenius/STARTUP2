"""Sprint 2 acceptance: an Uzbek query returns correctly cited protocol chunks."""

from __future__ import annotations

from pathlib import Path

import pytest
from knowledge.ingest import DEFAULT_CORPUS, ingest_documents, load_documents

from app.ai.rag.chunking import chunk_markdown, estimate_tokens, parse_frontmatter
from app.ai.rag.retriever import HybridRetriever
from app.models.knowledge import ProtocolChunk

CORPUS = Path(DEFAULT_CORPUS)


@pytest.fixture()
def knowledge_base(db):
    documents = load_documents(CORPUS)
    assert documents, "committed corpus is missing"
    ingest_documents(db, documents, prefer_offline=True)
    return db


@pytest.fixture()
def retriever(knowledge_base):
    return HybridRetriever(knowledge_base)


def test_corpus_ingests_with_full_provenance(knowledge_base):
    chunks = knowledge_base.query(ProtocolChunk).all()
    assert len(chunks) >= 20
    for chunk in chunks:
        assert chunk.source_id and chunk.publisher and chunk.version
        assert chunk.language in ("uz", "ru", "en")
        assert chunk.embedding, "every chunk must be embedded"
        assert chunk.text.strip()
        # The citation is what a clinician checks the advice against.
        assert chunk.publisher in chunk.citation
        assert chunk.version in chunk.citation


def test_reingesting_replaces_rather_than_duplicates(db):
    documents = load_documents(CORPUS)
    ingest_documents(db, documents, prefer_offline=True)
    first = db.query(ProtocolChunk).count()
    ingest_documents(db, documents, prefer_offline=True)
    assert db.query(ProtocolChunk).count() == first


#: 20 seeded queries — 10 Uzbek, 10 Russian — each with the protocol that must
#: be retrieved. This is the Sprint 2 definition of done.
UZ_QUERIES = [
    ("bolada ich ketishi va suvsizlanish belgilari", "who-imci-diarrhoea"),
    ("qon bosimi 160/95, davolashni qachon boshlash kerak", "who-htn-2021"),
    ("isitma, balg'amli yo'tal, ko'krak og'rig'i - pnevmoniya", "uzmoh-pneumonia"),
    ("uch haftadan ortiq yo'tal, tunda terlash, ozish", "uzmoh-tb"),
    ("qandli diabet tashxis mezonlari glyukoza", "uzmoh-diabetes"),
    ("kamqonlik gemoglobin temir preparati", "who-anaemia"),
    ("jig'ildon qaynashi epigastral og'riq helikobakter", "uzmoh-gastritis"),
    ("bel og'rig'i, qanday davolash kerak", "who-lbp"),
    ("bo'qoq, yod yetishmovchiligi", "who-iodine"),
    ("yurak qon tomir xavfi, tuz va parhez", "who-cvd-risk"),
]

RU_QUERIES = [
    ("диарея у ребёнка и обезвоживание, план лечения", "who-imci-diarrhoea"),
    ("артериальное давление 160/95 когда начинать лечение", "who-htn-2021"),
    ("пневмония у взрослого амбулаторное лечение", "uzmoh-pneumonia"),
    ("кашель более трёх недель, ночная потливость, туберкулёз", "uzmoh-tb"),
    ("сахарный диабет диагностические критерии глюкоза", "uzmoh-diabetes"),
    ("анемия гемоглобин препараты железа", "who-anaemia"),
    ("изжога боль в эпигастрии хеликобактер", "uzmoh-gastritis"),
    ("боль в пояснице лечение", "who-lbp"),
    ("зоб дефицит йода", "who-iodine"),
    ("сердечно-сосудистый риск питание соль", "who-cvd-risk"),
]


@pytest.mark.parametrize(("query", "expected_source"), UZ_QUERIES)
def test_uzbek_query_retrieves_the_right_protocol(retriever, query, expected_source):
    hits = retriever.retrieve(query, limit=3, language="uz")
    assert hits, f"no hits for {query!r}"
    assert expected_source in {h.source_id for h in hits}, [h.source_id for h in hits]


@pytest.mark.parametrize(("query", "expected_source"), RU_QUERIES)
def test_russian_query_retrieves_the_right_protocol(retriever, query, expected_source):
    hits = retriever.retrieve(query, limit=3, language="ru")
    assert hits, f"no hits for {query!r}"
    assert expected_source in {h.source_id for h in hits}, [h.source_id for h in hits]


def test_every_hit_carries_a_verifiable_citation(retriever):
    for hit in retriever.retrieve("pnevmoniya davolash", limit=5):
        assert hit.citation
        assert hit.publisher in hit.citation
        assert hit.source_id
        assert hit.text.strip()


def test_age_band_filter_excludes_mismatched_protocols(retriever):
    # The IMCI diarrhoea protocol is labelled infant/under5 only.
    adult_hits = retriever.retrieve("diarrhoea treatment plan", limit=10, age_band="adult")
    assert "who-imci-diarrhoea" not in {h.source_id for h in adult_hits}
    child_hits = retriever.retrieve("diarrhoea treatment plan", limit=10, age_band="under5")
    assert "who-imci-diarrhoea" in {h.source_id for h in child_hits}


def test_unlabelled_protocols_are_not_silently_dropped(db):
    from app.ai.providers.embeddings import HashingEmbeddings

    chunk_text = "Generic advice with no age band metadata at all."
    db.add(
        ProtocolChunk(
            source_id="unlabelled",
            source_title="Unlabelled protocol",
            publisher="Test",
            version="1",
            language="en",
            chunk_index=0,
            text=chunk_text,
            token_count=10,
            filters={},
            embedding=HashingEmbeddings().embed([chunk_text])[0],
        )
    )
    db.flush()
    hits = HybridRetriever(db).retrieve("generic advice metadata", limit=5, age_band="elderly")
    assert "unlabelled" in {h.source_id for h in hits}


def test_hybrid_beats_a_single_arm_on_a_rare_token(retriever):
    # "GeneXpert" appears once in the whole corpus; BM25 must surface it.
    hits = retriever.retrieve("GeneXpert MTB RIF balg'am tekshiruvi", limit=3)
    assert "uzmoh-tb" in {h.source_id for h in hits}
    assert any("bm25" in h.arms for h in hits)


def test_language_preference_does_not_exclude_other_languages(retriever):
    hits = retriever.retrieve("bolada ich ketishi suvsizlanish", limit=5, language="uz")
    # The IMCI protocol is in English; an Uzbek query must still reach it.
    assert "who-imci-diarrhoea" in {h.source_id for h in hits}


def test_empty_store_returns_nothing_rather_than_raising(db):
    assert HybridRetriever(db).retrieve("anything at all", limit=3) == []


# --- chunking ------------------------------------------------------------


def test_chunks_respect_the_token_ceiling():
    for path in CORPUS.glob("*.md"):
        for chunk in chunk_markdown(path.read_text(encoding="utf-8")):
            assert chunk.token_count <= 900, f"{path.name}: {chunk.token_count} tokens"


def test_chunks_keep_their_heading_path():
    text = CORPUS.joinpath("who-imci-diarrhoea.md").read_text(encoding="utf-8")
    sections = [c.section for c in chunk_markdown(text)]
    assert any("Classify dehydration" in (s or "") for s in sections)
    assert all(s is not None for s in sections)


def test_frontmatter_is_parsed_and_stripped():
    text = CORPUS.joinpath("who-imci-diarrhoea.md").read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    assert meta["publisher"] == "WHO"
    assert meta["age_bands"] == ["infant", "under5"]
    assert not body.lstrip().startswith("---")


def test_token_estimate_is_monotonic():
    assert estimate_tokens("bir ikki uch") < estimate_tokens("bir ikki uch to'rt besh olti")
