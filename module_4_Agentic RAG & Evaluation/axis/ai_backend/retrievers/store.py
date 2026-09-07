"""Where chunks and their embeddings live.

Two implementations behind one Protocol, mirroring the
`InMemoryStepStore`/`SqliteStepStore` pattern already used for the trace:
`ChromaVectorStore` at runtime, `InMemoryVectorStore` for tests. The double is
what keeps the whole suite offline and fast.

**The Chroma pitfall worth knowing about.** Chroma ships a default embedding
function that downloads an ONNX model on first use. If a collection is created
without `embedding_function=None`, three things break at once: the offline
guarantee (the test suite's no-network fixture fails), the swappable-provider rule
(embeddings would come from Chroma, not from the configured `EmbeddingProvider`),
and cost accounting (those embeddings never appear in the trace). So Axis always
passes vectors in explicitly, computed by its own provider.

Sessions are separated by a metadata filter rather than a collection each. A
collection per session would mean creating and reaping hundreds of them across a
workshop, and `is_ready()` becomes a count either way.

**Embedding models get a collection each, though.** Vectors from two different
models are not comparable — cosine similarity between them is arithmetic without
meaning — so they must never share an index. Chroma enforces part of this by
accident (a collection is pinned to the dimension of its first insert, so
switching from a 4096-dim model to a 1536-dim one raises), but only the part that
happens to change dimension. Two different 1536-dim models would be accepted
silently and retrieval quality would quietly rot, which is the worse failure.
Naming the collection after the model covers both cases and makes switching
providers a non-event rather than a crash.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Protocol, runtime_checkable

from ai_backend.contracts.models import Chunk, Modality
from ai_backend.errors import IngestionError, RetrievalUnavailableError


@runtime_checkable
class VectorStore(Protocol):
    async def add(
        self, *, session_id: str, chunks: list[Chunk], vectors: list[list[float]]
    ) -> None: ...

    async def search(
        self, *, session_id: str, vector: list[float], top_k: int
    ) -> list[Chunk]:
        """Nearest chunks, each with `score` set to cosine similarity in 0..1.

        Normalised to a similarity rather than left as a distance so a relevance
        threshold means the same thing across both implementations — a threshold
        expressed in Chroma's distance units would be meaningless against the
        in-memory store, and the tests would be validating different behaviour
        from production.
        """
        ...

    async def count(self, *, session_id: str) -> int: ...

    async def all_chunks(self, *, session_id: str) -> list[Chunk]:
        """Every chunk for a session, for keyword scoring.

        BM25 needs the whole corpus, not a nearest-neighbour slice. Fine at
        classroom scale (five documents per session); a production system would
        push keyword search into the store instead.
        """
        ...

    async def delete_session(self, *, session_id: str) -> None: ...


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _to_metadata(chunk: Chunk) -> dict[str, str]:
    return {
        "document_id": chunk.document_id,
        "modality": str(chunk.modality),
        "source_location": chunk.source_location,
    }


_UNSAFE_IN_COLLECTION_NAME = re.compile(r"[^a-z0-9._-]+")


def _collection_name(base: str, embedding_model: str, provider: str = "") -> str:
    """One collection per embedding model **and provider**.

    Chroma restricts names to 3–63 characters of `[a-zA-Z0-9._-]`, so a model
    identifier carrying a slash or colon (`ollama/nomic-embed-text:v1.5`) has to
    be flattened before it can be used. Truncated from the *end* of the base, not
    the model, because the model is the part that distinguishes one from another.

    **The provider is in the key, and it was added after this went wrong.** The
    key used to be the model name alone, which is right for the case it was
    designed for — switching `text-embedding-3-small` for `nomic-embed-text` gets
    two collections and neither is corrupted.

    It is wrong for the case that actually happens during development: running with
    `AXIS_EMBEDDING__PROVIDER=fake` while `AXIS_EMBEDDING__MODEL` is still whatever
    `.env` says. The provider changes and the model name does not, so the fake's
    4096-dimensional vectors are written into the collection named for
    `text-embedding-3-small` — and the next real run finds a collection whose name
    promises 1536 and whose contents are 4096.

    That failure was *caught*, by the width check in `add` (which is why this is a
    narrow gap rather than silent corruption), but it should not have been
    reachable: what determines a vector space is the provider and the model
    together, so both belong in the key. The residual case the width check still
    exists for is a provider quietly changing a model's width under a stable name.
    """
    parts = [p for p in (provider.lower().strip(), embedding_model.lower().strip()) if p]
    if not parts:
        return base
    slug = _UNSAFE_IN_COLLECTION_NAME.sub("-", "-".join(parts)).strip("-._")
    if not slug:
        return base
    return f"{base}__{slug}"[:63].rstrip("-._")


def _from_metadata(chunk_id: str, content: str, meta: dict[str, str]) -> Chunk:
    return Chunk(
        id=chunk_id,
        document_id=meta.get("document_id", ""),
        content=content,
        modality=Modality(meta.get("modality", "text")),
        source_location=meta.get("source_location", ""),
    )


class InMemoryVectorStore:
    """Exhaustive cosine search over a dict. For tests and small demos.

    O(n) per query, which is irrelevant at five documents and is also, usefully,
    exactly what a vector database does conceptually — a student can read this and
    see there is no magic in the index, only an approximation of this loop.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, tuple[Chunk, list[float]]]] = {}

    async def add(
        self, *, session_id: str, chunks: list[Chunk], vectors: list[list[float]]
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError(
                f"{len(chunks)} chunks but {len(vectors)} vectors — every chunk "
                f"must be embedded exactly once."
            )
        bucket = self._sessions.setdefault(session_id, {})
        for chunk, vector in zip(chunks, vectors, strict=True):
            bucket[chunk.id] = (chunk, vector)

    async def search(
        self, *, session_id: str, vector: list[float], top_k: int
    ) -> list[Chunk]:
        bucket = self._sessions.get(session_id, {})
        scored = [
            chunk.model_copy(update={"score": cosine_similarity(vector, stored)})
            for chunk, stored in bucket.values()
        ]
        scored.sort(key=lambda c: c.score or 0.0, reverse=True)
        return scored[:top_k]

    async def count(self, *, session_id: str) -> int:
        return len(self._sessions.get(session_id, {}))

    async def all_chunks(self, *, session_id: str) -> list[Chunk]:
        return [chunk for chunk, _ in self._sessions.get(session_id, {}).values()]

    async def delete_session(self, *, session_id: str) -> None:
        self._sessions.pop(session_id, None)


class ChromaVectorStore:
    """Chroma, driven with externally-computed embeddings.

    See the module docstring for why `embedding_function=None` is not optional.
    """

    COLLECTION = "axis_chunks"

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        embedding_model: str = "",
        embedding_provider: str = "",
    ) -> None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        # Telemetry off: it phones home, which would violate the "no external
        # service beyond the configured providers" property in PRD Section 6 and
        # break the offline guarantee.
        config = ChromaSettings(anonymized_telemetry=False, allow_reset=True)

        if path is None:
            self._client = chromadb.EphemeralClient(settings=config)
            self._location = "the in-memory index"
        else:
            target = Path(path)
            target.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(target), settings=config)
            self._location = str(target)

        self._embedding_model = embedding_model
        self._embedding_provider = embedding_provider
        self._collection = self._client.get_or_create_collection(
            name=_collection_name(
                self.COLLECTION, embedding_model, embedding_provider
            ),
            metadata={
                # Cosine, so the distance Chroma returns can be converted to the
                # similarity the Retriever's threshold is expressed in.
                "hnsw:space": "cosine",
                # Recorded so anyone inspecting `var/chroma` can tell what built it.
                # Both halves, because both determine the vector space — see
                # `_collection_name`.
                "axis:embedding_model": embedding_model or "unspecified",
                "axis:embedding_provider": embedding_provider or "unspecified",
            },
            # THE important argument. See the module docstring.
            embedding_function=None,
        )
        self._dimension: int | None = None

    def _stored_dimension(self) -> int | None:
        """The vector width this collection is already pinned to, if anything.

        Read from the data rather than caught as a Chroma exception: the error type
        and message vary across Chroma releases, and turning a 500 into a clear
        refusal is not something to make dependent on a vendor's wording.
        """
        if self._dimension is None:
            peek = self._collection.get(limit=1, include=["embeddings"])
            vectors = peek.get("embeddings")
            if vectors is not None and len(vectors) > 0:
                self._dimension = len(vectors[0])
        return self._dimension

    def _mismatch(self, length: int) -> str | None:
        stored = self._stored_dimension()
        if stored is None or stored == length:
            return None
        return (
            f"This index holds {stored}-dimensional vectors, but the configured "
            f"embedding model ({self._embedding_model or 'unspecified'}) produces "
            f"{length}. It was built by a different model, and vectors from two "
            f"models cannot be compared."
        )

    @property
    def _remedy(self) -> str:
        return (
            f"Delete {self._location} to rebuild the index with the current model, "
            f"or restore the embedding model that built it."
        )

    async def add(
        self, *, session_id: str, chunks: list[Chunk], vectors: list[list[float]]
    ) -> None:
        if not chunks:
            return
        if len(chunks) != len(vectors):
            raise ValueError(
                f"{len(chunks)} chunks but {len(vectors)} vectors — every chunk "
                f"must be embedded exactly once."
            )
        # An `IngestionError` rather than a raw Chroma failure, so the upload
        # endpoint's per-file handler reports it to the student as a failed file
        # with a reason instead of returning a 500 and a stack trace.
        mismatch = self._mismatch(len(vectors[0]))
        if mismatch:
            raise IngestionError(mismatch, detail=self._remedy)

        self._collection.add(
            ids=[c.id for c in chunks],
            embeddings=vectors,
            documents=[c.content for c in chunks],
            metadatas=[{**_to_metadata(c), "session_id": session_id} for c in chunks],
        )
        self._dimension = len(vectors[0])

    async def search(
        self, *, session_id: str, vector: list[float], top_k: int
    ) -> list[Chunk]:
        # The same condition, but at query time the honest answer is that this
        # index is unusable for this configuration — not that a document failed.
        mismatch = self._mismatch(len(vector))
        if mismatch:
            raise RetrievalUnavailableError(mismatch, detail=self._remedy)

        result = self._collection.query(
            query_embeddings=[vector],
            n_results=max(1, top_k),
            where={"session_id": session_id},
            include=["documents", "metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        chunks: list[Chunk] = []
        for chunk_id, content, meta, distance in zip(
            ids, documents, metadatas, distances, strict=True
        ):
            chunk = _from_metadata(chunk_id, content or "", dict(meta or {}))
            # Chroma's cosine "distance" is 1 - similarity. Clamped because
            # floating-point can nudge it a hair outside [0, 1], and a similarity
            # of 1.0000001 would look like a bug to anyone reading the trace.
            similarity = max(0.0, min(1.0, 1.0 - float(distance)))
            chunks.append(chunk.model_copy(update={"score": similarity}))
        return chunks

    async def count(self, *, session_id: str) -> int:
        return len(self._collection.get(where={"session_id": session_id}).get("ids") or [])

    async def all_chunks(self, *, session_id: str) -> list[Chunk]:
        result = self._collection.get(
            where={"session_id": session_id}, include=["documents", "metadatas"]
        )
        return [
            _from_metadata(chunk_id, content or "", dict(meta or {}))
            for chunk_id, content, meta in zip(
                result.get("ids") or [],
                result.get("documents") or [],
                result.get("metadatas") or [],
                strict=True,
            )
        ]

    async def delete_session(self, *, session_id: str) -> None:
        self._collection.delete(where={"session_id": session_id})
