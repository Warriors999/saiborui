"""ChromaDB persistent vector store with upsert support for idempotent ingest."""

import hashlib

import chromadb

from rag_system.config import CHROMA_DIR

COLLECTION_NAME = "tech_reviews"


class VectorStore:
    def __init__(self, persist_dir: str = str(CHROMA_DIR)):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_chunks(self, chunks: list[dict]) -> int:
        """Insert or update chunks. Each chunk must have:
        id, embedding, document, metadata dict (all string values).
        Returns count of upserted chunks.
        """
        if not chunks:
            return 0

        ids = [c["id"] for c in chunks]
        embeddings = [c["embedding"] for c in chunks]
        documents = [c["document"] for c in chunks]
        metadatas = [c["metadata"] for c in chunks]

        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        return len(ids)

    def query(
        self,
        query_embedding: list[float],
        top_k: int = 8,
        where: dict | None = None,
    ) -> dict:
        """Retrieve top_k most similar chunks, with optional metadata filter."""
        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": top_k,
        }
        if where:
            kwargs["where"] = where

        return self.collection.query(**kwargs)

    def count(self) -> int:
        return self.collection.count()

    def get_all_metadata(self) -> list[dict]:
        """Fetch all metadata entries for stats. Returns in batches."""
        results = self.collection.get(include=["metadatas"])
        return results.get("metadatas", []) or []

    def reset(self) -> None:
        """Delete and recreate the collection."""
        self.client.delete_collection(COLLECTION_NAME)
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )


def make_chunk_id(source_file: str, chunk_index: int) -> str:
    """Deterministic chunk ID for idempotent upserts."""
    raw = f"{source_file}::{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]
