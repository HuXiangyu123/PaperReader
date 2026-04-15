"""
统一 Embedding Client — 支持 Qwen text-embedding-v4 API 与本地 SentenceTransformer。

设计原则：
- 接口兼容 SentenceTransformer（.encode() 方法），可直接替换传入 retriever / indexer
- Qwen API 与 OpenAI Embeddings API 兼容，使用 openai 库调用
- 环境变量控制：
    QWEN_EMBEDDING_API_KEY / QWEN_EMBEDDING_BASE_URL / QWEN_EMBEDDING_MODEL / QWEN_EMBEDDING_DIM
  若 API key 为空，则 fallback 到 SentenceTransformer（本地模型）

用法：
    from src.embeddings.client import get_embedding_client

    # 自动选择（优先 Qwen，无 key 则本地）
    client = get_embedding_client()
    vectors = client.encode(["hello world", "foo bar"])

    # 强制指定后端
    client = get_embedding_client(backend="qwen")
    client = get_embedding_client(backend="local")
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 自动加载 .env（独立脚本场景，如 scripts/ 或直接 python -c 调用）
# ---------------------------------------------------------------------------

def _ensure_dotenv() -> None:
    """延迟加载 .env 文件（若未加载则自动加载）。"""
    if not os.getenv("_DOTENV_LOADED"):
        # 尝试从项目根目录加载
        for candidate in [
            Path(__file__).parent.parent.parent / ".env",  # src/embeddings/.env
            Path.cwd() / ".env",                           # cwd/.env
            Path(sys.argv[0] if sys.argv else ".").resolve().parent / ".env",  # script dir
        ]:
            if candidate.exists():
                from dotenv import load_dotenv
                load_dotenv(candidate, override=False)
                os.environ["_DOTENV_LOADED"] = "1"
                logger.debug(f"[Embedding] .env loaded from {candidate}")
                break


# ── 配置 ────────────────────────────────────────────────────────────────────────


@dataclass
class EmbeddingConfig:
    """Embedding 模型配置。"""
    api_key: str
    base_url: str
    model: str
    dimension: int
    backend: Literal["qwen", "local"]


def _load_config() -> EmbeddingConfig:
    """从环境变量加载配置（自动加载 .env）。"""
    _ensure_dotenv()
    api_key = os.getenv("QWEN_EMBEDDING_API_KEY", "").strip()
    base_url = os.getenv("QWEN_EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
    model = os.getenv("QWEN_EMBEDDING_MODEL", "text-embedding-v4").strip()
    dimension = int(os.getenv("QWEN_EMBEDDING_DIM", "1024"))

    backend: Literal["qwen", "local"] = "qwen" if api_key else "local"
    return EmbeddingConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        dimension=dimension,
        backend=backend,
    )


# ── Qwen API Client ────────────────────────────────────────────────────────────


class _QwenEmbeddingClient:
    """
    Qwen text-embedding-v4 API client。

    兼容 SentenceTransformer 接口：.encode(texts) -> np.ndarray
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "text-embedding-v4",
        dimension: int = 1024,
        batch_size: int = 50,
        normalize: bool = True,
    ):
        """
        初始化 Qwen embedding client。

        Args:
            api_key: DashScope API key
            base_url: DashScope OpenAI 兼容端点
            model: 模型名称
            dimension: 向量维度（默认 1024，支持 64-2048）
            batch_size: 每批请求的文本数量（API 限制 ≤ 25）
            normalize: 是否 L2 归一化（用于 cosine similarity）
        """
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dimension = dimension
        self._batch_size = min(batch_size, 10)  # DashScope 上限 10
        self._normalize = normalize
        self._client = None  # 延迟初始化

    def _get_openai_client(self):
        """延迟创建 OpenAI 兼容 client。"""
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError:
                raise RuntimeError(
                    "openai 库未安装。请运行：pip install openai"
                )
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
            )
        return self._client

    def encode(
        self,
        texts: str | list[str],
        normalize: bool | None = None,
        show_progress_bar: bool = False,
        convert_to_numpy: bool = True,
        batch_size: int | None = None,
    ) -> np.ndarray:
        """
        生成文本 embedding。

        Args:
            texts: 单条文本或文本列表
            normalize: 是否归一化（None=继承构造函数设置）
            show_progress_bar: 忽略（兼容接口）
            convert_to_numpy: 是否返回 numpy 数组（True=始终返回 np.ndarray）
            batch_size: 覆盖每批数量

        Returns:
            np.ndarray，shape (n, dimension) 或 (1, dimension)
        """
        if isinstance(texts, str):
            texts = [texts]

        norm = normalize if normalize is not None else self._normalize
        bs = batch_size or self._batch_size

        all_embeddings: list[list[float]] = []
        total = len(texts)

        for i in range(0, total, bs):
            batch = texts[i : i + bs]
            batch_embs = self._embed_batch(batch)
            all_embeddings.extend(batch_embs)

            if i + bs < total:
                logger.debug(
                    f"[QwenEmbedding] 进度：{min(i + bs, total)}/{total}"
                )

        result = np.array(all_embeddings, dtype=np.float32)

        if norm:
            norms = np.linalg.norm(result, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)
            result = result / norms

        return result

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """单批调用 Qwen embedding API。"""
        client = self._get_openai_client()

        try:
            response = client.embeddings.create(
                model=self._model,
                input=texts,
                # dimensions 参数需 API 支持（text-embedding-v4 支持）
                # dimensions=self._dimension,
            )
        except Exception as e:
            logger.error(f"[QwenEmbedding] API 调用失败：{e}")
            raise

        embeddings = []
        for item in response.data:
            vec = item.embedding
            if not isinstance(vec, list):
                vec = list(vec)
            embeddings.append(vec)

        return embeddings

    def __repr__(self) -> str:
        return (
            f"_QwenEmbeddingClient(model={self._model}, "
            f"dim={self._dimension}, batch={self._batch_size})"
        )


# ── 本地 SentenceTransformer Client（兼容性 Wrapper）─────────────────────────────


class _LocalEmbeddingClient:
    """
    SentenceTransformer 包装器。

    提供与 Qwen client 相同的接口，用于无 API key 时的 fallback。
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        normalize: bool = True,
    ):
        self._model_name = model_name
        self._normalize = normalize
        self._model = None

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise RuntimeError(
                    "sentence-transformers 未安装。"
                    "请运行：pip install sentence-transformers"
                )
            logger.info(f"Loading local embedding model: {self._model_name}")
            self._model = SentenceTransformer(self._model_name)
            logger.info(
                f"Local embedding model loaded, dim={self._model.get_sentence_embedding_dimension()}"
            )

    def encode(
        self,
        texts: str | list[str],
        normalize: bool | None = None,
        show_progress_bar: bool = False,
        convert_to_numpy: bool = True,
        batch_size: int | None = None,
    ) -> np.ndarray:
        self._load_model()
        norm = normalize if normalize is not None else self._normalize
        bs = batch_size or 32

        result = self._model.encode(
            texts,
            show_progress_bar=show_progress_bar,
            convert_to_numpy=True,
            batch_size=bs,
            normalize_embeddings=norm,
        )
        return result

    def __repr__(self) -> str:
        return f"_LocalEmbeddingClient(model={self._model_name})"


# ── 统一入口 ──────────────────────────────────────────────────────────────────


_embedding_client: _QwenEmbeddingClient | _LocalEmbeddingClient | None = None


def get_embedding_client(
    backend: Literal["auto", "qwen", "local"] = "auto",
    force_reload: bool = False,
) -> _QwenEmbeddingClient | _LocalEmbeddingClient:
    """
    获取全局 embedding client（单例）。

    Args:
        backend: "auto" — 有 QWEN_EMBEDDING_API_KEY 则用 Qwen，否则本地 SentenceTransformer
                 "qwen" — 强制使用 Qwen API
                 "local" — 强制使用本地 SentenceTransformer
        force_reload: 强制重新初始化

    Returns:
        实现 .encode() 接口的 client（兼容 SentenceTransformer）
    """
    global _embedding_client

    if _embedding_client is not None and not force_reload:
        return _embedding_client

    if backend == "auto":
        config = _load_config()
        chosen = config.backend
    else:
        chosen = backend

    if chosen == "qwen":
        config = _load_config()
        logger.info(
            f"[Embedding] 使用 Qwen API: model={config.model}, dim={config.dimension}, "
            f"url={config.base_url}"
        )
        _embedding_client = _QwenEmbeddingClient(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
            dimension=config.dimension,
        )
    else:
        local_model = os.getenv("LOCAL_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        logger.info(f"[Embedding] 使用本地模型: {local_model}")
        _embedding_client = _LocalEmbeddingClient(model_name=local_model)

    return _embedding_client


def get_embedding_dimension() -> int:
    """获取当前 embedding 向量维度。"""
    config = _load_config()
    if config.backend == "local":
        client = _LocalEmbeddingClient()
        client._load_model()
        return client._model.get_sentence_embedding_dimension()
    return config.dimension


def reset_embedding_client() -> None:
    """重置全局 client（用于测试或切换模型）。"""
    global _embedding_client
    _embedding_client = None
