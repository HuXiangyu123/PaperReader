"""Corpus Search 测试 fixtures。"""
from __future__ import annotations

import pytest
from dotenv import load_dotenv

load_dotenv()


def is_db_available() -> bool:
    """检查 DATABASE_URL 是否配置。"""
    import os
    return bool(os.getenv("DATABASE_URL"))


def is_milvus_available() -> bool:
    """检查 Milvus 是否可用。"""
    import os
    try:
        from pymilvus import connections

        host = os.getenv("MILVUS_HOST", "127.0.0.1")
        port = os.getenv("MILVUS_PORT", "19530")
        connections.connect("test_health", host=host, port=port, timeout=3)
        connections.disconnect("test_health")
        return True
    except Exception:
        return False


@pytest.fixture
def db_session():
    """PostgreSQL session（DATABASE_URL 必需）。"""
    if not is_db_available():
        pytest.skip("DATABASE_URL not configured")

    from src.db import get_db_session

    with get_db_session() as s:
        yield s


@pytest.fixture
def milvus_index():
    """Milvus 连接（需要 Milvus 服务运行）。"""
    if not is_milvus_available():
        pytest.skip("Milvus not available")

    import os
    from pymilvus import connections
    from src.corpus.store.vector_index import MilvusVectorIndex

    host = os.getenv("MILVUS_HOST", "127.0.0.1")
    port = int(os.getenv("MILVUS_PORT", "19530"))
    alias = "test_search"

    idx = MilvusVectorIndex(host=host, port=port, alias=alias)
    idx.connect()
    yield idx
    if connections.has_connection(alias):
        connections.disconnect(alias)


@pytest.fixture
def paper_retriever(db_session, milvus_index):
    """PaperRetriever 实例（需要 DB + Milvus）。"""
    from src.corpus.search.retrievers.paper_retriever import PaperRetriever

    return PaperRetriever(
        db_session=db_session,
        milvus_index=milvus_index,
        collection_coarse="test_coarse",
    )
