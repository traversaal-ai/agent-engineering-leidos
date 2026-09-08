# The demo corpus

The five ACME Aerospace program documents a class loads with one click. Read by
`demo_documents()` in `ai_backend/evaluation/golden.py` (via `CORPUS_DIR`), served by
`POST /api/v1/sessions/{id}/documents/demo`, and reached from the sidebar's *Load the
demo set* button.

Every `*.md` file in this directory is loaded **except this one**, which is excluded by
name in `demo_documents()`. So any Markdown you add here becomes a sixth document in the
corpus — and since the demo endpoint is bound by the same five-file limit as an upload,
that turns *Load the demo set* into a `413`. Put notes in a comment inside a document
instead.

## Why these five

They were **copied from** `reference/module_3_Enterprise RAG/data/` — the material this
cohort was already taught on, so a question asked in Axis lands on documents a student
recognises rather than on a synthetic handbook nobody has read. That folder is the record
of the demo they were shown; it is never read at runtime, and this copy is the
authoritative one.

They also do something a synthetic corpus could not: **they interlock.** A slipped
deliverable appears as an action item in the kickoff notes, an escalation in the status
review, and risk R-02 in the register — so a question can genuinely require using what
one document says to know what to look for in another. That is the multi-hop pain point
on the *Why agentic* page, and without a real chain in the corpus there is nothing to
demonstrate.

## The one edit, and why re-copying the originals breaks things

Each file opens with a one-line provenance notice:

```markdown
*Fictional sample document, written for teaching. The company, program, people and figures are invented.*
```

The originals open with a three-line blockquote instead:

```markdown
> FICTIONAL SAMPLE DOCUMENT. Created for an AI demonstration. ACME Aerospace
> Systems is an invented company. Nothing here describes a real agreement,
> real terms, or real people.
```

It is **identical across all five files**, so it made every document's first chunk look
alike and outrank real content. Module 3 strips it entirely before indexing and records
the same reason; keeping one line keeps the provenance a fictional corpus needs without
five copies of it competing for the top of every search.

This is the failure mode to know about: syncing these files from `reference/` again looks
harmless, raises no error, and quietly makes retrieval worse on the corpus that every
measured claim on the *Why agentic* page rests on.
`test_the_provenance_notice_is_one_line` in `tests/evaluation/test_golden_set_m0.py` is
what catches it.

## Constraints on changing the corpus

- **Five files, exactly.** `AXIS_UPLOAD__MAX_FILES_PER_SESSION` defaults to 5 and bounds
  the demo endpoint too, so a sixth document here is a document that cannot be loaded —
  and the endpoint returns `413` rather than silently indexing four of five.
- **The ground truth lives elsewhere.**
  `ai_backend/evaluation/golden/questions.yaml` states the expected documents, expected
  substrings and sub-question splits for each golden question. Editing a document here can
  invalidate an expectation there, and the harness is what says so:

  ```bash
  python -m ai_backend.evaluation --strategy naive_rag      # recall floor, groundedness
  python -m ai_backend.evaluation --compare-strategies      # the four mechanism ceilings
  ```

  The second exits non-zero if a mechanism the *Why agentic* page claims stops earning its
  cost on this corpus — which is the point: a corpus change that invalidates a
  demonstration should fail a build rather than leave a teaching tool promising an outcome
  nothing measured.
- **The harness reads two more documents that are not here.** `rates.xlsx` and
  `headcount.png` are *generated* in `golden.py` rather than committed, so the tabular and
  visual questions stay measurable without a binary blob in the tree. They are deliberately
  outside the one-click set, which is bounded by the file limit above.
