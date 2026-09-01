# Search Lab

A frontend for [`basic_keyword_semantic_search.py`](../basic_keyword_semantic_search.py).
Both retrievers run over the same documents, for the same question, side by
side — so the difference between matching **words** and matching **meaning** is
something the room watches happen rather than something you assert.

## Run

```bash
cd ..                       # the module root
source venv/bin/activate
pip install -r requirements.txt
uvicorn --app-dir search-lab app:app --port 8010
```

Open http://localhost:8010. The embedding model loads on a background thread at
startup; the header says when it is ready.

## What each side does

| | Keyword | Semantic |
|---|---|---|
| Index | inverted index: word → document ids | one vector per document |
| Score | `tf × log(N / (df + 1))`, summed over query words | cosine similarity |
| Model | none | `nomic-ai/nomic-embed-text-v1.5`, 768 dims |
| Fails when | the question uses different words | rarely, on this scale |

The keyword side reproduces the notebook exactly, including its scoring
formula. The **"How that score was calculated"** panel shows the per-word
working: which query words were in the index, how many documents each appeared
in, and what each contributed. A word that is not in the index contributes
nothing at all, and that panel is where people see why.

Nomic is used with the task prefixes it was trained on — `search_document:` for
stored text, `search_query:` for questions. Skipping those quietly costs you
accuracy, which is a mistake worth naming out loud.

## The queries that make the point

| Query | What happens |
|---|---|
| `cat that chases mouse` | The notebook's own query, and keyword search **gets it wrong** — it ranks "The cat is playing in the garden" first, while the document actually about a cat chasing a mouse never surfaces. "mice" is not "mouse". |
| `feline hunting rodents` | Not one of these words appears anywhere. Keyword search returns **nothing**. Semantic search finds the right document immediately. |
| `pet animals` | Same failure in business language: "pets" is in a document, but "pet" is a different string. |
| `deep learning` | Subtler. Both match, but keyword ranks "Machine learning" first because "learning" is common; semantic puts "Deep learning uses neural networks" on top. |
| `how much does the shirt cost` | Keyword wins outright. Worth showing, so nobody concludes keyword search is simply broken. |

Try `how much does the shirt cost` and look at the keyword column's lower
ranks: "The cat is playing in the garden" scores above zero, because **"the"**
matched. That is the other half of the keyword problem — not just missing what
it should find, but matching on noise.

## Things to try live

- **Edit the documents.** The textarea is the corpus. Add a sentence in your own
  words, then search for it using completely different words.
- **Drag the threshold.** It sets how high a semantic score has to be to count
  as a match. Nomic's floor is high — unrelated text still scores 0.30–0.50 —
  so the default is 0.55, which is where relevant and irrelevant separate on
  these documents. Drag it to 0.3 and watch everything become a "match".
- **Ask something the library cannot answer at all.** Both sides should fail.
  Semantic search returning a confident-looking 0.5 for nonsense is exactly why
  thresholds exist.

## Why this is here

Module 3's main assistant uses TF-IDF for retrieval, which is honest about what
it is but is not how enterprise RAG is actually built. This lab is the argument
for the upgrade: same corpus, same questions, and a visible gap between the two.
