# Alex

Demonstrates how an AI assistant becomes progressively more capable:

`LLM -> Chatbot -> Tool-Using Agent -> RAG-Enabled Assistant`

- **Level 1: LLM Only** — only the current message is sent, no history, no tools.
- **Level 2: + Conversation History** — full session history is sent with each turn.
- **Level 3: + Web Search Tool** — the model can call a `web_search` tool when it needs current info (via [Tavily](https://tavily.com); falls back to mocked results if no key is set). The UI states explicitly whether results came back **live** or **mocked**.
- **Level 4: + RAG** — everything from Level 3 **plus** retrieval over a local knowledge base. Alex answers from the documents first (bracket citations `[1]`) and falls back to web search only when they do not cover the question (markdown-link citations).

The levels are strictly cumulative: Level 4 keeps the web_search tool Level 3 introduced.

All four levels share one backend/chatbot architecture (`backend/main.py`) — each level just turns on one more capability. Answers stream token-by-token over SSE, and markdown is rendered as markdown.

Alex has a persona system prompt on every level, so the debug panel can show the
difference between **prompt engineering** (hand-written instructions, identical
every call) and **context engineering** (excerpts looked up per question and
pasted into the same string).

## Knowledge base

Level 4 indexes two kinds of source:

- `Project-Management-2nd-Edition-1729807212.pdf` — a general project management reference.
- `data/*.md` — a fictional ACME Aerospace Systems program: master services agreement, statement of work, two sets of meeting notes, and a risk register.

**The ACME documents are invented sample data**, clearly labelled as such in each
file. They exist so the RAG demo answers questions an audience actually cares
about ("what are the payment terms?", "what is the highest risk right now?")
instead of textbook definitions. Drop more `.md` or `.txt` files into `data/`
and they are indexed at the next restart.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `ANTHROPIC_API_KEY` (required). `TAVILY_API_KEY` is optional — without it, Level 3 uses mocked search results so the flow still works.

## Run

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Open http://localhost:8000 in your browser.

The Level 4 PDF index is built on a background thread at startup, so the first
Level 4 question doesn't wait on it. `GET /api/health` reports whether the index
is ready and how many chunks it holds.

## Demo notes

- **Debug panel** (sidebar checkbox) shows exactly what was sent to the model,
  as a conversation: every turn of the session, each message tagged with whether
  it was appended this turn, re-sent from history, or produced by a tool. It can
  be opened after a reply has already streamed in.
- `rag.py` also loads `data/*.md`, so `RAG_DOCUMENT_PATH` covers only the PDF.
- Retrieval prefixes each chunk with its document title before vectorizing, so a passage still matches its document's subject when the passage itself never repeats it.
- Only excerpts the answer actually cites are shown as source cards; the debug panel shows everything retrieved.
- Level 4 only cites chunks scoring above `MIN_SCORE` in `backend/rag.py`
  (default `0.08`). Ask it something off-topic and it says it can't find the
  answer rather than citing four irrelevant pages.
- Level 4 follow-ups ("what about the third one?") prepend the last two user
  turns to the retrieval query, so the vector search still has terms to match on.

## Project structure

```
backend/
  main.py   # FastAPI app, SSE streaming chat endpoint, level-based logic
  rag.py    # PDF loading, chunking, TF-IDF vector store (Level 4)
  tools.py  # web_search tool + Tavily client (Level 3)
frontend/
  index.html / styles.css / app.js   # chat UI, level selector, debug panel
data/
  *.md                               # fictional ACME program documents (Level 4)
```
