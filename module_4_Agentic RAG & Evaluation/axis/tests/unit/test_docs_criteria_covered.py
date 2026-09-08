"""Keeps the test suite honest against the PRD.

The requirement this implements: *"Every must-have user story in PRD Section 5 has
a Given/When/Then acceptance criterion in Section 6. Write an automated test from
each one — a milestone isn't done until its criteria pass as tests."* (CLAUDE.md)

The failure mode without this test is quiet and likely: someone adds a must-have
story to the PRD, everyone agrees it is important, and no test is ever written for
it. Nothing breaks, nothing complains, and the gap is invisible because the suite
is green. Here, adding a must-have story to Section 5 turns the build red until a
corresponding acceptance module exists.

It parses the PRD rather than holding a hand-maintained list, because a
hand-maintained list is the same problem one level up.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PRD = REPO_ROOT / "docs" / "Axis_PRD.md"
ACCEPTANCE_DIR = REPO_ROOT / "tests" / "acceptance"

# Maps each must-have story to the acceptance module that proves it. Explicit
# because a story's prose and a filename cannot be mechanically derived from each
# other — but the *set* of stories is read from the PRD, so the mapping cannot
# silently fall out of date.
STORY_KEYWORDS_TO_MODULE = {
    ("upload", "5 documents"): "test_ac_upload_documents.py",
    ("choose a strategy",): "test_ac_choose_strategy.py",
    ("citations",): "test_ac_citations.py",
    ("live trace",): "test_ac_live_trace.py",
    ("example questions labelled",): "test_ac_predicted_outcomes.py",
    ("choose between my uploaded documents and a live web search",): "test_ac_source_routing.py",
    ("summarizer mode",): "test_ac_summarizer.py",
    ("watch each stage of indexing and answering",): "test_ac_pipeline_walkthrough.py",
    ("read any run this session has made",): "test_ac_trace_history.py",
    ("toggle the trace",): "test_ac_narration_toggle.py",
    ("Compare mode",): "test_ac_compare_mode.py",
    # Same story, two features: the endpoint that runs every strategy at once (above,
    # deferred) and the page that compares two runs already made (below).
    ("side by side", "same question"): "test_ac_compare_selection.py",
    ("cost and rate caps",): "test_ac_cost_rate_caps.py",
    ("run reliably on a single machine",): "test_ac_single_machine_health.py",
    ("four ways naive RAG fails",): "test_ac_pain_points.py",
    ("follow-up question",): "test_ac_conversation_memory.py",
    ("reworded repeat",): "test_ac_semantic_cache.py",
    ("hold the demo corpus",): "test_ac_corpus_switching.py",
    # Two stories, one module. They arrived together with the first hosted
    # deployment and are unrelated except in that: a shared door on the URL, and a
    # way to report what comes back through it.
    ("shared password",): "test_ac_feedback_and_gate.py",
    ("report an answer as wrong",): "test_ac_feedback_and_gate.py",
}


def _must_have_stories() -> list[str]:
    """The bullet list under "### Must-have" in PRD Section 5."""
    text = PRD.read_text(encoding="utf-8")

    match = re.search(
        r"^### Must-have\s*$(.*?)^### ", text, re.MULTILINE | re.DOTALL
    )
    assert match, "Could not locate the '### Must-have' block in PRD Section 5."

    stories: list[str] = []
    for raw in re.split(r"^- ", match.group(1), flags=re.MULTILINE)[1:]:
        # Bullets wrap across lines; collapse each to one string.
        stories.append(" ".join(raw.split()))
    return stories


def test_the_prd_still_has_a_parseable_must_have_list() -> None:
    """Guards the parser itself.

    If the PRD is restructured and this stops matching, the coverage check below
    would pass trivially over an empty list — a green suite that checks nothing.
    """
    stories = _must_have_stories()

    assert len(stories) >= 8, (
        f"Expected at least 8 must-have stories in PRD Section 5, parsed "
        f"{len(stories)}. If the PRD's structure changed, update the parser in "
        f"this test — do not let it silently match nothing."
    )


@pytest.mark.parametrize("story", _must_have_stories(), ids=lambda s: s[:48])
def test_every_must_have_story_has_an_acceptance_module(story: str) -> None:
    matched = [
        module
        for keywords, module in STORY_KEYWORDS_TO_MODULE.items()
        if all(keyword.lower() in story.lower() for keyword in keywords)
    ]

    assert matched, (
        f"No acceptance module is mapped to this must-have story:\n\n  {story}\n\n"
        f"Write its Given/When/Then from PRD Section 6 as a test under "
        f"tests/acceptance/, then add it to STORY_KEYWORDS_TO_MODULE in this file."
    )

    for module in matched:
        assert (ACCEPTANCE_DIR / module).is_file(), (
            f"{module} is mapped to a must-have story but does not exist."
        )


def test_every_acceptance_module_maps_to_a_story() -> None:
    """The reverse direction: no orphaned acceptance modules.

    An acceptance test not traceable to a story is either testing something the
    PRD does not ask for, or the story was removed and the test outlived it.
    Either way it needs a decision, not a quiet existence.
    """
    on_disk = {
        path.name
        for path in ACCEPTANCE_DIR.glob("test_ac_*.py")
    }
    mapped = set(STORY_KEYWORDS_TO_MODULE.values())

    orphans = on_disk - mapped
    assert not orphans, (
        f"These acceptance modules map to no PRD must-have story: {sorted(orphans)}. "
        f"Add the story to the PRD, or map the module in STORY_KEYWORDS_TO_MODULE."
    )


def test_acceptance_modules_declare_their_milestone() -> None:
    """Every acceptance test must say when it is expected to pass.

    Without a milestone marker `pytest --milestone=N` would silently omit it, and
    the per-milestone gate in CLAUDE.md ("do not start a milestone until the
    previous one's evaluation slice passes") would be checking an incomplete set.
    """
    missing: list[str] = []

    for path in sorted(ACCEPTANCE_DIR.glob("test_ac_*.py")):
        if "pytest.mark.milestone" not in path.read_text(encoding="utf-8"):
            missing.append(path.name)

    assert not missing, (
        f"These acceptance modules declare no milestone marker: {missing}. "
        f"Add @pytest.mark.milestone(n) so the per-milestone slice is complete."
    )
