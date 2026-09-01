"""
Level 4 building block: a deliberately simple RAG pipeline.

Documents -> chunks -> TF-IDF vectors ("embeddings") -> in-memory vector store.
A real embeddings API (Voyage, OpenAI, etc.) could be swapped in for the
vectorizer without changing anything else in this file.

The corpus is a PDF plus every markdown/text file in ../data, so retrieval has
to pick the right DOCUMENT as well as the right passage.
"""
import os
import pathlib
import re
import threading
from dataclasses import dataclass

import numpy as np
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

CHUNK_SIZE = 900
CHUNK_OVERLAP = 150
TOP_K = 8  # 6 documents in the corpus now; 4 was crowding out the short ones

# Cosine similarity below this is treated as "no match". Without it, a totally
# off-topic question still returns the four least-bad chunks in the book and
# the model dutifully cites them, which looks authoritative and is nonsense.
MIN_SCORE = 0.08


@dataclass
class Chunk:
    index: int
    page: int
    text: str        # what the user sees
    embed_text: str  # what gets vectorised: title + text
    document: str    # which file this passage came from


class VectorStore:
    def __init__(self, document_path: str, data_dir: str | None = None,
                 min_score: float = MIN_SCORE):
        self.document_path = document_path
        self.data_dir = data_dir
        self.min_score = min_score
        self.chunks: list[Chunk] = []
        self.documents: list[str] = []
        self.vectorizer: TfidfVectorizer | None = None
        self.matrix = None
        self._build()

    def _extract_pdf_pages(self, path: str) -> list[str]:
        reader = PdfReader(path)
        return [page.extract_text() or "" for page in reader.pages]

    def _chunk_pages(self, pages: list[str], document: str, start_index: int) -> list[Chunk]:
        """Split each page into overlapping windows, tagged with its document."""
        chunks: list[Chunk] = []
        idx = start_index
        for page_num, raw in enumerate(pages, start=1):
            text = re.sub(r"\s+", " ", raw).strip()
            if not text:
                continue
            start = 0
            while start < len(text):
                end = start + CHUNK_SIZE
                piece = text[start:end].strip()
                if len(piece) > 40:
                    # Prefix the title so a passage still matches its document's
                    # subject even when the passage itself never repeats it.
                    chunks.append(
                        Chunk(
                            index=idx,
                            page=page_num,
                            text=piece,
                            embed_text=f"{document}\n{piece}",
                            document=document,
                        )
                    )
                    idx += 1
                if end >= len(text):
                    break
                start = end - CHUNK_OVERLAP
        return chunks

    def _text_file_pages(self, path: str) -> list[str]:
        """Markdown has no pages, so split on headings to keep a useful locator."""
        raw = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
        # Drop the human-facing disclaimer blockquote: it is identical in every
        # sample document, so indexing it makes all their headers look alike.
        raw = "\n".join(
            line for line in raw.splitlines() if not line.lstrip().startswith(">")
        )
        sections = re.split(r"\n(?=##\s)", raw)
        return [sec for sec in sections if sec.strip()]

    def _title_for(self, path: str) -> str:
        """Prefer the document's own H1 over its filename."""
        try:
            for line in pathlib.Path(path).read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                if line.startswith("# "):
                    return line[2:].strip()
        except Exception:
            pass
        return pathlib.Path(path).stem.replace("-", " ").replace("_", " ").title()

    def _build(self):
        sources: list[tuple[str, str, list[str]]] = []  # (title, path, pages)

        if os.path.exists(self.document_path):
            sources.append((
                "Project Management (2nd Edition)",
                self.document_path,
                self._extract_pdf_pages(self.document_path),
            ))

        if self.data_dir and os.path.isdir(self.data_dir):
            for path in sorted(pathlib.Path(self.data_dir).glob("*")):
                if path.suffix.lower() not in {".md", ".txt", ".markdown"}:
                    continue
                sources.append((
                    self._title_for(str(path)),
                    str(path),
                    self._text_file_pages(str(path)),
                ))

        if not sources:
            raise FileNotFoundError(
                "No RAG source documents found. Looked for %s and any .md/.txt in %s"
                % (self.document_path, self.data_dir)
            )

        chunks: list[Chunk] = []
        for title, _path, pages in sources:
            chunks.extend(self._chunk_pages(pages, title, len(chunks)))

        self.chunks = chunks
        self.documents = [title for title, _p, _pg in sources]
        corpus = [c.embed_text for c in self.chunks]
        self.vectorizer = TfidfVectorizer(stop_words="english", max_features=20000)
        self.matrix = self.vectorizer.fit_transform(corpus)

    def search(self, query: str, top_k: int = TOP_K):
        query_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self.matrix)[0]
        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for i in top_indices:
            score = float(scores[i])
            if score < self.min_score:
                continue
            chunk = self.chunks[i]
            results.append(
                {
                    "chunk_index": chunk.index,
                    "document": chunk.document,
                    "page": chunk.page,
                    "text": chunk.text,
                    "score": round(score, 4),
                }
            )
        return results


_store: VectorStore | None = None
_store_lock = threading.Lock()
_store_error: str | None = None


def get_store() -> VectorStore:
    global _store, _store_error
    with _store_lock:
        if _store is None:
            doc_path = os.environ.get(
                "RAG_DOCUMENT_PATH",
                "../Project-Management-2nd-Edition-1729807212.pdf",
            )
            if not os.path.isabs(doc_path):
                doc_path = os.path.join(os.path.dirname(__file__), doc_path)
            data_dir = os.environ.get("RAG_DATA_DIR", "../data")
            if not os.path.isabs(data_dir):
                data_dir = os.path.join(os.path.dirname(__file__), data_dir)
            try:
                _store = VectorStore(doc_path, data_dir=data_dir)
            except Exception as exc:
                _store_error = str(exc)
                raise
    return _store


def warm_store() -> None:
    """Build the index ahead of the first question. Called at app startup on a
    background thread; failures surface via /api/health instead of crashing boot."""
    try:
        store = get_store()
        print(
            "[rag] index ready: %d chunks across %d documents (%s)"
            % (len(store.chunks), len(store.documents), ", ".join(store.documents))
        )
    except Exception as exc:
        print(f"[rag] index build FAILED: {exc}")


def chunk_breakdown(document: str, limit: int = 12) -> dict:
    """Show how one document was actually cut up: the chunks, how much text
    each one overlaps with the one before it, and the terms that carry the most
    TF-IDF weight in each. Used by the 'How RAG works' walkthrough."""
    store = get_store()
    picked = [c for c in store.chunks if c.document == document][:limit]
    if not picked:
        return {"document": document, "chunks": [], "total_chunks": 0}

    features = store.vectorizer.get_feature_names_out()
    rows = []
    prev = None
    for c in picked:
        # How many leading characters this chunk shares with the previous one.
        overlap = 0
        if prev is not None and prev.page == c.page:
            k = min(CHUNK_OVERLAP, len(prev.text), len(c.text))
            while k > 0 and prev.text[-k:] != c.text[:k]:
                k -= 1
            overlap = k

        vec = store.matrix[c.index]
        nonzero = int(vec.nnz)
        pairs = sorted(
            zip(vec.indices, vec.data), key=lambda kv: kv[1], reverse=True
        )[:6]
        rows.append({
            "chunk_index": c.index,
            "page": c.page,
            "text": c.text,
            "characters": len(c.text),
            "overlap_with_previous": overlap,
            "nonzero_terms": nonzero,
            "top_terms": [
                {"term": features[i], "weight": round(float(w), 3)} for i, w in pairs
            ],
        })
        prev = c

    total = sum(1 for c in store.chunks if c.document == document)
    return {
        "document": document,
        "chunks": rows,
        "total_chunks": total,
        "showing": len(rows),
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "vocabulary_size": len(features),
    }


def score_all(query: str, document: str | None = None, limit: int = 12) -> dict:
    """Score every chunk against a query so the walkthrough can show what
    retrieval is really doing: rank by cosine similarity, cut at top-k, drop
    anything under the threshold."""
    store = get_store()
    query_vec = store.vectorizer.transform([query])
    scores = cosine_similarity(query_vec, store.matrix)[0]

    features = store.vectorizer.get_feature_names_out()
    qpairs = sorted(
        zip(query_vec.indices, query_vec.data), key=lambda kv: kv[1], reverse=True
    )
    query_terms = [features[i] for i, _w in qpairs]

    idxs = [
        c.index for c in store.chunks
        if document is None or c.document == document
    ]
    ranked = sorted(idxs, key=lambda i: scores[i], reverse=True)

    # What the real search() would return, so the walkthrough matches reality.
    selected = {
        r["chunk_index"] for r in store.search(query)
    }

    rows = []
    for rank, i in enumerate(ranked[:limit], start=1):
        c = store.chunks[i]
        rows.append({
            "rank": rank,
            "chunk_index": c.index,
            "document": c.document,
            "page": c.page,
            "score": round(float(scores[i]), 4),
            "above_threshold": float(scores[i]) >= store.min_score,
            "selected": c.index in selected,
            "text": c.text[:260],
        })

    return {
        "query": query,
        "query_terms": query_terms,
        "scored": rows,
        "threshold": store.min_score,
        "top_k": TOP_K,
        "total_chunks": len(store.chunks),
        "selected_count": len(selected),
    }


def document_summary() -> list[dict]:
    """Per-document chunk counts, for the Level 4 knowledge-base list."""
    if _store is None:
        return []
    counts: dict[str, int] = {}
    for c in _store.chunks:
        counts[c.document] = counts.get(c.document, 0) + 1
    return [
        {"title": title, "chunks": counts.get(title, 0)}
        for title in _store.documents
    ]


def store_status() -> dict:
    if _store is not None:
        return {
            "ready": True,
            "chunks": len(_store.chunks),
            "documents": _store.documents,
        }
    return {"ready": False, "error": _store_error, "detail": "still building"}
