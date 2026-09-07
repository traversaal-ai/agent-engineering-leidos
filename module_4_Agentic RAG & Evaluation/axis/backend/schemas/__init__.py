"""Request and response shapes — the contract the Frontend renders against.

Defined as explicit Pydantic models rather than returning dicts, so the contract
is checkable and shows up in the generated OpenAPI schema. Both sides of the
Frontend ↔ Backend boundary are in this repository, which makes it tempting to
skip; the boundary is real (a genuine HTTP hop, per System Design Section 6.2)
and a typo in a dict key would otherwise only surface in the browser.
"""

from backend.schemas.compare import CompareRequest, CompareResponse, StrategyResult
from backend.schemas.health import HealthResponse, LayerHealth
from backend.schemas.query import QueryRequest, QueryResponse
from backend.schemas.session import SessionCreateRequest, SessionCreateResponse, SessionInfo
from backend.schemas.trace import NarrateResponse, TraceStep

__all__ = [
    "CompareRequest",
    "CompareResponse",
    "HealthResponse",
    "LayerHealth",
    "NarrateResponse",
    "QueryRequest",
    "QueryResponse",
    "SessionCreateRequest",
    "SessionCreateResponse",
    "SessionInfo",
    "StrategyResult",
    "TraceStep",
]
