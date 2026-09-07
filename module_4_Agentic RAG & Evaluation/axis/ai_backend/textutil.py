"""Shared text tokenisation.

A leaf module with no Axis imports, so both `providers/fake.py` and
`retrievers/vector.py` can use it without either depending on the other — a
provider importing from the retrievers package would invert the dependency
direction for no good reason.

They must agree, and that is the whole point of putting it here. `FakeEmbedding
Provider` builds a hashed bag of words, and `_bm25_rank` scores lexical overlap;
if the two tokenised differently, similarity in tests would stop tracking the
lexical relevance the keyword arm measures, and the two halves of hybrid retrieval
would disagree about what a word is.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9]+")

# Deliberately short. Aggressive stopword removal loses real distinctions — "leave
# policy" versus "policy on leaving" — but these carry no retrieval signal and
# actively hurt: without removing them, "What is the position on X?" scores a
# spurious similarity against any passage containing "is" and "on", which is
# enough to defeat a relevance threshold.
STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
        "has", "have", "how", "i", "if", "in", "is", "it", "its", "of", "on",
        "or", "that", "the", "this", "to", "was", "were", "what", "when",
        "where", "which", "who", "why", "will", "with", "you", "your",
    }
)


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, stopwords removed.

    Numbers and identifier fragments are kept: a question about "form W-8BEN" or
    "16 weeks" is answered by a lexical match, and dropping the digits would throw
    away exactly the term that discriminates.
    """
    return [word for word in _WORD.findall(text.lower()) if word not in STOPWORDS]
