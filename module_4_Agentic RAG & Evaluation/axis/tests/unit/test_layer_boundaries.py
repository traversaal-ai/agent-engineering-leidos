"""The architecture guardrail.

CLAUDE.md lists layer boundaries as non-negotiable. Rules stated only in prose
erode one convenient import at a time — nobody sets out to violate them, someone
just needs a chunker in a route at 5pm. This test makes the boundary a build
failure instead of a code-review habit.

The rules, and the reason each exists:

1. **`frontend/` imports neither `backend` nor `ai_backend`.** The Frontend talks
   HTTP (System Design Section 6.2). With no import path, no secret, provider, or
   retriever is reachable from the layer that renders to a browser — a structural
   guarantee rather than a careful one.

2. **`backend/` imports AI Backend *behaviour* only through `dispatch.py`.**
   "Contains no retrieval or generation logic" (Section 6.1), enforced by
   funnelling the dependency through one auditable module.

3. **`ai_backend/` imports neither `backend` nor `frontend`, and never FastAPI.**
   The dependency direction is one-way, which is what lets the AI Backend be
   driven from a script or notebook — PRD Section 4's post-class reference use.

Three things are exempt from rule 2 as *shared vocabulary* rather than logic:
`ai_backend.contracts` (data shapes), `ai_backend.errors` (the exception
hierarchy the Backend maps to status codes), and `ai_backend.config` (settings —
the Backend legitimately needs cap and upload limits). The point of a shared
contract is that both sides may name the same things.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Importable from anywhere: data shapes, the exception hierarchy, and settings.
# None of these is retrieval or generation logic.
_SHARED_VOCABULARY = (
    "ai_backend.contracts",
    "ai_backend.errors",
    "ai_backend.config",
)

# The single sanctioned crossing point from Backend into AI Backend behaviour.
_DISPATCH_MODULE = "backend/dispatch.py"

# Backend modules that legitimately reach further, each with its reason. Keep
# this list short — every entry is a hole in rule 2, and the guardrail is only
# worth having while the list stays auditable at a glance.
_BACKEND_EXEMPTIONS = {
    # Composition root for this layer: wires the observability store and reads
    # the pipeline registry at startup. Wiring is precisely its job.
    "backend/app.py",
    # Serving the trace over SSE is a Backend responsibility, and the step store
    # is where the trace lives.
    "backend/api/v1/trace.py",
}


def _imported_modules(path: Path) -> set[str]:
    """Every module name a file imports, at any depth.

    Uses the AST rather than a text search so that a name inside a string or a
    comment cannot trip the check, and so `from x import y` and `import x.y` are
    both seen.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _python_files(package: str) -> list[Path]:
    return sorted((REPO_ROOT / package).rglob("*.py"))


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _crosses_into(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


def _is_shared_vocabulary(module: str) -> bool:
    return any(_crosses_into(module, allowed) for allowed in _SHARED_VOCABULARY)


# ---------------------------------------------------------------------------
# Rule 1 — the Frontend is sealed off.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _python_files("frontend"), ids=_relative)
def test_frontend_does_not_import_other_layers(path: Path) -> None:
    """The Frontend reaches the Backend over HTTP, never by import.

    `ai_backend.config` and `ai_backend.contracts` are permitted: the Frontend
    needs `FrontendSettings` (which structurally cannot hold a secret) and the
    `Strategy` enum to label a run.
    """
    allowed = (*_SHARED_VOCABULARY, "ai_backend.config")

    offenders = [
        module
        for module in _imported_modules(path)
        if (_crosses_into(module, "backend") or _crosses_into(module, "ai_backend"))
        and not any(_crosses_into(module, ok) for ok in allowed)
    ]

    assert not offenders, (
        f"{_relative(path)} imports {offenders}. The Frontend must reach the "
        f"Backend over HTTP (see frontend/api_client.py), so that no provider, "
        f"retriever, or secret is reachable from this layer."
    )


# ---------------------------------------------------------------------------
# Rule 2 — the Backend crosses into the AI Backend at exactly one place.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _python_files("backend"), ids=_relative)
def test_backend_reaches_ai_backend_only_through_dispatch(path: Path) -> None:
    relative = _relative(path)
    if relative == _DISPATCH_MODULE or relative in _BACKEND_EXEMPTIONS:
        return

    offenders = [
        module
        for module in _imported_modules(path)
        if _crosses_into(module, "ai_backend") and not _is_shared_vocabulary(module)
    ]

    assert not offenders, (
        f"{relative} imports {offenders} directly. The Backend contains no "
        f"retrieval or generation logic (System Design Section 6.1) — route it "
        f"through backend/dispatch.py, or add a justified exemption to "
        f"_BACKEND_EXEMPTIONS in this test."
    )


def test_no_backend_module_imports_a_pipeline_or_retriever() -> None:
    """The strongest form of rule 2, and immune to the exemption list.

    Even an exempted module must never import a pipeline, retriever, or provider
    implementation — those *are* the retrieval and generation logic. `dispatch.py`
    imports the pipeline registry, which is a lookup table, not an implementation.
    """
    forbidden = ("ai_backend.retrievers", "ai_backend.ingestion", "ai_backend.providers")
    violations: list[str] = []

    for path in _python_files("backend"):
        for module in _imported_modules(path):
            if any(_crosses_into(module, f) for f in forbidden):
                violations.append(f"{_relative(path)} → {module}")

    assert not violations, (
        "The Backend must not import retrieval, ingestion, or provider "
        f"implementations: {violations}"
    )


# ---------------------------------------------------------------------------
# Rule 3 — the AI Backend depends on nothing above it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _python_files("ai_backend"), ids=_relative)
def test_ai_backend_does_not_import_upper_layers(path: Path) -> None:
    offenders = [
        module
        for module in _imported_modules(path)
        if _crosses_into(module, "backend") or _crosses_into(module, "frontend")
    ]

    assert not offenders, (
        f"{_relative(path)} imports {offenders}. Dependencies point one way: "
        f"frontend → backend → ai_backend."
    )


@pytest.mark.parametrize("path", _python_files("ai_backend"), ids=_relative)
def test_ai_backend_does_not_import_a_web_framework(path: Path) -> None:
    """No FastAPI or Starlette below the Backend.

    Keeps the AI Backend drivable from a script, a notebook, or the evaluation
    harness with no HTTP involved — and it is why `ai_backend/errors.py` raises
    domain errors that `backend/core/errors.py` maps to status codes, rather than
    raising `HTTPException` directly.
    """
    web = ("fastapi", "starlette")

    offenders = [
        module
        for module in _imported_modules(path)
        if any(_crosses_into(module, w) for w in web)
    ]

    assert not offenders, (
        f"{_relative(path)} imports {offenders}. The AI Backend must be usable "
        f"without a web framework; raise an AxisError and let "
        f"backend/core/errors.py map it to a status code."
    )


# ---------------------------------------------------------------------------
# The observability rule from CLAUDE.md.
# ---------------------------------------------------------------------------


def test_no_external_tracing_framework_is_used() -> None:
    """Observability is custom-built. CLAUDE.md calls this a teaching choice.

    Worth a test rather than trusting review, because reaching for
    OpenTelemetry is the *reasonable* engineering instinct — and here it would
    quietly delete the thing the course is trying to teach.
    """
    banned = ("langfuse", "langsmith", "opentelemetry", "ddtrace", "sentry_sdk")
    violations: list[str] = []

    for package in ("ai_backend", "backend", "frontend", "axis"):
        for path in _python_files(package):
            for module in _imported_modules(path):
                root = module.split(".")[0]
                if root in banned:
                    violations.append(f"{_relative(path)} → {module}")

    assert not violations, (
        "Axis builds its own observability on purpose (System Design Section 10, "
        f"CLAUDE.md). Found: {violations}"
    )
