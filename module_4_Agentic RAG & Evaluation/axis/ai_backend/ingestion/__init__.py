"""Document ingestion — one path, run once per document (System Design Section 8).

    upload (PDF / PPTX / DOCX / XLSX / PNG / JPG / MD)
              │
              ▼
      shared parser — text extraction + image captioning, owned by Axis
              │
              ▼
      recursive chunking (overlapping)
              │
              ▼
      embed → Chroma
              │
              ▼
      read by BOTH strategies, through one VectorRetriever

**Ingestion is not a comparison axis.** It happens before any question is asked, and
the index it produces is the same index both strategies query — which is what makes a
difference between their answers attributable to the orchestration rather than to how
the documents were prepared.

The four stages are traced separately (`parse`, `chunk`, `embed`, `store`) because the
canvas draws them individually, and because chunking is where retrieval quality is
actually decided: a student who never watches it happen has not seen the most
consequential parameter in the system.
"""
