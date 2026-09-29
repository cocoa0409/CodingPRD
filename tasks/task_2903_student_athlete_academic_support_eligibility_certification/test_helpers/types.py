"""Lightweight typing aliases for the Athletics Academic Eligibility test suite.

These are documentation-grade aliases only; nothing here performs validation.
"""

from typing import Any, Dict, List, Optional, Tuple

# A JSON object as returned in the envelope's ``data`` field.
JsonObject = Dict[str, Any]

# A list-endpoint payload: the ``data`` array.
JsonArray = List[JsonObject]

# HTTP headers as accepted by ``requests``.
Headers = Dict[str, str]

# A request body.
Payload = Dict[str, Any]

# Query parameters.
Params = Dict[str, Any]

# Result of a paginated read: (rows, meta).
PageResult = Tuple[JsonArray, JsonObject]

# An entity identifier (server-minted UUID string, no prefix).
EntityId = str

# An opaque operator identifier carried in X-User-ID.
OperatorId = str

# An ISO-8601 UTC instant string.
Instant = str

OptionalId = Optional[EntityId]

__all__ = [
    "JsonObject",
    "JsonArray",
    "Headers",
    "Payload",
    "Params",
    "PageResult",
    "EntityId",
    "OperatorId",
    "Instant",
    "OptionalId",
]
