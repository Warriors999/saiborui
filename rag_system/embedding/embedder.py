"""Embedding model wrapper for BAAI/bge-large-zh-v1.5.

BGE models expect instruction prefixes for optimal query embeddings:
- Documents (during indexing): no prefix
- Queries (during retrieval): "为这个句子生成表示以用于检索相关文章："
"""

from sentence_transformers import SentenceTransformer

from rag_system.config import EMBEDDING_DEVICE, EMBEDDING_MODEL

QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class Embedder:
    def __init__(self, model_name: str = EMBEDDING_MODEL, device: str = EMBEDDING_DEVICE):
        self.model = SentenceTransformer(model_name, device=device)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed documents for storage (no instruction prefix)."""
        embeddings = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        """Embed a query for retrieval (with instruction prefix)."""
        embedding = self.model.encode(
            QUERY_INSTRUCTION + query,
            normalize_embeddings=True,
        )
        return embedding.tolist()
