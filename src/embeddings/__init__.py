"""Embeddings — 统一向量生成客户端。"""

from src.embeddings.client import (
    get_embedding_client,
    get_embedding_dimension,
    reset_embedding_client,
    _QwenEmbeddingClient,
    _LocalEmbeddingClient,
)

__all__ = [
    "get_embedding_client",
    "get_embedding_dimension",
    "reset_embedding_client",
]
