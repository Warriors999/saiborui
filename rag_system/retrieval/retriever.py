"""Semantic retrieval with metadata filtering and post-processing.

Post-processing steps:
  1. Same-source dedup: max 2 chunks per source file
  2. Final-version boost: 定稿 chunks get slight score boost
  3. Revision exclusion: optionally remove non-final revisions
"""

from dataclasses import dataclass, field

from rag_system.config import DEFAULT_TOP_K
from rag_system.embedding.embedder import Embedder
from rag_system.storage.vector_store import VectorStore


@dataclass
class RetrievedChunk:
    score: float
    document: str
    source_file: str
    persona: str
    product_name: str
    category: str
    is_final: bool
    chunk_index: str
    _revision_patterns: list = field(default_factory=lambda: ["修改", "v2", "v3", "v4", "(1)"], repr=False)

    def is_revision(self) -> bool:
        for p in self._revision_patterns:
            if p in self.source_file:
                return True
        return False


class Retriever:
    def __init__(self, embedder: Embedder, store: VectorStore):
        self.embedder = embedder
        self.store = store

    def retrieve(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        persona: str | None = None,
        category: str | None = None,
        is_final_only: bool = False,
        exclude_revisions: bool = False,
    ) -> list[RetrievedChunk]:
        query_embedding = self.embedder.embed_query(query)

        # Build ChromaDB 1.5.x where filter with $and for multi-condition
        conditions = []
        if persona:
            conditions.append({"persona": persona})
        if category:
            conditions.append({"category": category})
        if is_final_only:
            conditions.append({"is_final": "true"})
        where = {"$and": conditions} if len(conditions) > 1 else (conditions[0] if len(conditions) == 1 else None)

        fetch_k = top_k * 3 if (persona or category) else top_k * 2

        results = self.store.query(query_embedding, top_k=fetch_k, where=where)

        chunks = []
        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for i, _chunk_id in enumerate(ids):
            meta = metadatas[i]
            distance = distances[i]
            similarity = 1.0 - (distance / 2.0)

            chunks.append(RetrievedChunk(
                score=round(similarity, 4),
                document=documents[i],
                source_file=meta.get("source_file", ""),
                persona=meta.get("persona", ""),
                product_name=meta.get("product_name", ""),
                category=meta.get("category", ""),
                is_final=meta.get("is_final", "false") == "true",
                chunk_index=meta.get("chunk_index", "0"),
            ))

        chunks = _deduplicate_by_source(chunks)
        chunks = _boost_finals(chunks)
        if exclude_revisions:
            chunks = _exclude_revisions(chunks)

        return chunks[:top_k]


def _deduplicate_by_source(chunks: list[RetrievedChunk], max_per_source: int = 2) -> list[RetrievedChunk]:
    seen: dict[str, int] = {}
    result = []
    for c in chunks:
        count = seen.get(c.source_file, 0)
        if count < max_per_source:
            result.append(c)
            seen[c.source_file] = count + 1
    return result


def _boost_finals(chunks: list[RetrievedChunk], boost: float = 0.02) -> list[RetrievedChunk]:
    for c in chunks:
        if c.is_final:
            c.score = round(min(c.score + boost, 1.0), 4)
    chunks.sort(key=lambda c: c.score, reverse=True)
    return chunks


def _exclude_revisions(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    non_revision_products = {c.product_name for c in chunks if not c.is_revision()}
    if not non_revision_products:
        return chunks
    return [c for c in chunks if c.product_name not in non_revision_products or not c.is_revision()]
