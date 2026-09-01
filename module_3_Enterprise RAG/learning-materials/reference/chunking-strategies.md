# Reference: Chunking and Chunking Strategies

Deep dive on Concept 6 of the lesson. Chunking is step 3 of Ingestion (see `rag-pipeline.md`), and it is the single decision that most determines whether a RAG system's retrieval is any good.

## What is chunking, and why do we need it?

Chunking is breaking up your data into smaller pieces, or **chunks**, before embedding and storing it. It exists because large language models have a limited context window and cannot take in an entire dataset at once (see `rag-pipeline.md` for the context window limit itself). You cannot embed and search a whole 50-page contract as one unit and expect a meaningful match against a one-sentence question; you need pieces small enough to be individually relevant, and small enough to individually fit inside the prompt once retrieved.

**Why chunking quality matters, concretely:**

- **Improved retrieval efficiency.** Smaller, focused chunks are faster and cheaper to search and embed than a handful of enormous ones.
- **Enhanced accuracy and relevance.** A chunk that contains exactly one idea is much more likely to match a query about that idea than a chunk that blends five unrelated ideas together.
- **Scalability and manageability.** Uniform, well-bounded chunks are easier to index, update, and reason about as a corpus grows.
- **Balanced information distribution.** No single chunk ends up so large it dominates every search, or so small it carries no useful signal on its own.

**Chunk size matters** because it defines a direct trade-off: chunks too large dilute relevance (irrelevant material rides along with the useful sentence, and gets embedded into the same vector, blurring what the vector actually represents); chunks too small lose context (a sentence pulled with no surrounding paragraph can be ambiguous or misleading on its own).

## Chunking visualized

A tool called **ChunkViz** makes the effect of chunk size and overlap directly visible: paste in text, set a chunk size and overlap, and it highlights each resulting chunk in a different color over the original text. It's a fast way to build intuition before touching any code:

- Different colors show where each chunk starts and ends.
- **Overlapping text** between adjacent chunks is highlighted separately, this is the **chunk overlap** setting, a deliberate duplication of a few sentences or characters at chunk boundaries so context isn't lost right at the cut.
- The one pattern to watch for and avoid: a **chunk boundary landing in the middle of a sentence**. That is a sign the splitter is not respecting the structure of the text, and it is flagged explicitly as "not good," because it means a retrieved chunk can end mid-thought.

## The five chunking strategies

| # | Strategy | What it means | Best when |
|---|---|---|---|
| 1 | **Fixed-Size Chunking** | Split text into chunks of a specified number of characters, regardless of their content or structure. | You need something simple and fast, and the source text has little inherent structure to exploit. |
| 2 | **Recursive Chunking** | Recursively split text using a set of separators (e.g. paragraph breaks, then sentences, then words), in priority order, until each chunk is under the target size. | General-purpose default. Respects natural text boundaries far better than fixed-size, without needing document structure. |
| 3 | **Document-Based Chunking** | Split a document according to its own inherent structure: headings, sections, paragraphs. | The source has clear structure (Markdown, HTML, a templated report) and that structure maps onto meaningful units. |
| 4 | **Semantic Chunking** | Divide the text into chunks that are semantically complete, using an embedding model to detect where meaning actually shifts, rather than a fixed rule. | Precision matters more than speed or cost, and the text doesn't have reliable structural markers to lean on. |
| 5 | **Agentic Chunking** | Use an LLM to decide how much and what text to include in a chunk, based on context. | The highest-stakes or most irregular content, where even semantic chunking's heuristics aren't reliable enough, and the extra LLM cost is worth it. |

The five are roughly ordered from cheapest/simplest to most expensive/most context-aware. Fixed-size and recursive chunking need no model calls; semantic and agentic chunking spend inference budget at ingestion time to buy better retrieval quality later. There is no universally "correct" strategy, it is a cost/quality trade-off decided per corpus, and it is common to mix strategies (e.g. document-based chunking down to the section level, then recursive chunking within an oversized section).

## Worked example: Recursive Chunking

**Input:**
> "AI is amazing. It is used in medicine, finance, and art. However, it also raises ethical concerns."

**Chunking rules:**
- Max chunk size: 50 characters
- Separators, in priority order: `["." , "," , " "]`

**Step by step:**

1. Original text is 108 characters, too long. Try splitting on `". "` (sentence boundaries) first, since it's the highest-priority separator.
2. That produces three pieces:
   - `"AI is amazing."` (15 chars)
   - `"It is used in medicine, finance, and art."` (43 chars)
   - `"However, it also raises ethical concerns."` (49 chars)
3. All three are already under the 50-character limit, so no further splitting is needed.

**Final chunks:**
```
[
  "AI is amazing.",
  "It is used in medicine, finance, and art.",
  "However, it also raises ethical concerns."
]
```

**How it's recursive:** if either resulting chunk were still longer than 50 characters, the algorithm would recursively re-split *that specific chunk* using the next separator in the priority list (here, `","`, then `" "`), instead of re-splitting the whole document. This is what keeps sentence and clause boundaries intact wherever possible, unlike fixed-size chunking, which would have cut this same text at exactly character 50 regardless of what word it landed on.

## Worked example: Document-Based Chunking

**Original document** (Markdown, with `##` headers marking top-level sections):

```
## Introduction
Artificial Intelligence (AI) is rapidly changing the world.
It has the potential to improve many aspects of our lives.

## Applications
AI is used in healthcare, finance, transportation,
education, and more.

## Challenges
Ethical concerns and bias in data are major challenges.

## Conclusion
With proper regulation, AI can benefit society immensely.
```

**Resulting chunks**, split at each top-level header, one chunk per section:

```
Chunk 1 (Introduction): "Artificial Intelligence (AI) is rapidly changing the world..."
Chunk 2 (Applications):  "AI is used in healthcare, finance, transportation..."
Chunk 3 (Challenges):    "Ethical concerns and bias in data are major challenges..."
Chunk 4 (Conclusion):    "With proper regulation, AI can benefit society..."
```

No character-count rule is applied at all here, the document's own headings define the chunk boundaries. This is why document-based chunking works best only when the structure genuinely lines up with meaning; a document with headers that don't correspond to self-contained ideas gets no benefit from this approach over recursive chunking.

**Check:** For a 200-page internal policy manual with consistent `H1`/`H2` headings, and a folder of unstructured meeting transcripts, which chunking strategy would you reach for first for each, and what specifically about each source justifies the choice?
