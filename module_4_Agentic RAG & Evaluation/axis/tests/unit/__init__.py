"""Unit tests for the Milestone -1 foundation.

Two of these are structural guardrails rather than ordinary tests, and they are
the ones most worth understanding:

- `test_layer_boundaries.py` turns CLAUDE.md's non-negotiable layer boundaries
  into a build failure. Prose rules erode one convenient import at a time.
- `test_docs_criteria_covered.py` checks the acceptance suite against the PRD, so
  a must-have story added without a test fails the build rather than quietly
  going untested.

Unit tests carry no milestone marker, so they run in every `--milestone=N` slice.
They are the foundation each milestone stands on.
"""
