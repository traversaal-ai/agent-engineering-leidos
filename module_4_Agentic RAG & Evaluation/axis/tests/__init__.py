"""Axis test suite.

    tests/acceptance/  one module per PRD Section 5 must-have story, written from
                       the Given/When/Then in Section 6
    tests/unit/        the Milestone -1 foundation, plus two structural guardrails
    tests/contract/    one suite run against every implementation of an interface

Run everything:              pytest
Run one milestone's slice:   pytest --milestone=-1

The suite is offline by construction — an autouse fixture in `conftest.py` fails
any test that opens a real socket.
"""
