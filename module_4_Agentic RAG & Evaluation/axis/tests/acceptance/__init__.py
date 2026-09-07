"""One module per must-have user story in PRD Section 5.

Each test's docstring quotes its Given/When/Then from PRD Section 6 verbatim, and
carries `@pytest.mark.story` plus `@pytest.mark.milestone`. Criteria that cannot
pass yet are written as real executable code marked
`@pytest.mark.xfail(strict=True)`.

Strict xfail rather than skip, deliberately: when a milestone lands and the
feature starts working, a strict xfail that now passes turns the suite **red**
until its marker is deleted. A skip would stay silently green and the criterion
would never be promoted. That is the mechanism behind "a milestone isn't done
until its acceptance criteria pass as tests".

`tests/unit/test_docs_criteria_covered.py` checks this directory against the PRD,
so adding a must-have story without a test here fails the build.

Run one milestone's slice with `pytest --milestone=-1`.
"""
