"""
AAGCP-Vector :: Embedding + Vector Store layer.

Self-contained by design (numpy only) so the governance demo runs anywhere
with zero API keys. Both layers are adapter interfaces:

  EmbedderAdapter   → swap in sentence-transformers / OpenAI / Endee-native
  VectorStoreAdapter → swap in Endee / Pinecone / Qdrant / pgvector

The governance control plane is deliberately agnostic to both — that is
the entire point: AAGCP wraps the store, it does not replace it.
"""

from __future__ import annotations
import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np


# ── Embedders ────────────────────────────────────────────────────────

class EmbedderAdapter(ABC):
    dim: int

    @abstractmethod
    def embed(self, text: str) -> np.ndarray: ...


class HashingEmbedder(EmbedderAdapter):
    """
    Deterministic feature-hashing embedder (word + char trigram features).
    No network, no model weights — good enough to demonstrate that
    nearest-neighbour semantics survive tokenization, which is the claim
    under test. Swap for a real model in production via the adapter.
    """

    def __init__(self, dim: int = 512):
        self.dim = dim

    def _features(self, text: str) -> List[str]:
        text = text.lower()
        words = re.findall(r"[a-z0-9_<>]+", text)
        feats = list(words)
        joined = " ".join(words)
        feats += [joined[i:i + 3] for i in range(len(joined) - 2)]
        return feats

    def embed(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for feat in self._features(text):
            h = int(hashlib.md5(feat.encode()).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 1) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec


# ── Vector stores ────────────────────────────────────────────────────

@dataclass
class StoredVector:
    vector_id: str
    vector: np.ndarray
    text: str                      # masked text only — raw never stored
    metadata: dict = field(default_factory=dict)


class VectorStoreAdapter(ABC):
    @abstractmethod
    def upsert(self, vector_id: str, vector: np.ndarray,
               text: str, metadata: dict): ...

    @abstractmethod
    def query(self, vector: np.ndarray, top_k: int) -> List[dict]: ...


class InMemoryVectorStore(VectorStoreAdapter):
    """Reference store: cosine similarity over numpy. Demo-grade."""

    def __init__(self):
        self._items: Dict[str, StoredVector] = {}

    def upsert(self, vector_id, vector, text, metadata):
        self._items[vector_id] = StoredVector(vector_id, vector, text, metadata)

    def query(self, vector, top_k=5):
        scored = []
        for item in self._items.values():
            sim = float(np.dot(vector, item.vector))
            scored.append({"id": item.vector_id, "score": round(sim, 4),
                           "text": item.text, "metadata": item.metadata})
        return sorted(scored, key=lambda x: -x["score"])[:top_k]


class EndeeAdapter(VectorStoreAdapter):
    """
    Integration stub for Endee. The governance plane needs exactly two
    operations from any store — upsert and similarity query — so wiring
    Endee in is a ~30-line exercise against its client SDK.

    def __init__(self, client, index): ...
    def upsert(...):  client.upsert(index, id, vector, payload={text, meta})
    def query(...):   client.search(index, vector, top_k)
    """

    def __init__(self, *_, **__):
        raise NotImplementedError(
            "Wire to the Endee SDK — see class docstring. "
            "The control plane requires no other changes."
        )

    def upsert(self, *a, **k): ...
    def query(self, *a, **k): ...
