"""Type aliases shared by the Executive Protection & Travel Risk Management test suite."""

from typing import Any, Dict, List, Optional, Tuple

# An auth header dict: X-User-ID / X-User-Role (plus Content-Type).
Headers = Dict[str, str]

# A decoded JSON object (an entity representation or an error payload).
JsonDict = Dict[str, Any]

# A decoded JSON list payload plus the list meta block.
PaginatedResult = Tuple[List[JsonDict], JsonDict]

# A request payload built by factories.py.
Payload = Dict[str, Any]

# Optional identifiers threaded through fixtures.
EntityId = str
OptionalEntityId = Optional[str]

__all__ = [
    "Headers",
    "JsonDict",
    "PaginatedResult",
    "Payload",
    "EntityId",
    "OptionalEntityId",
]
