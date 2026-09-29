"""Lightweight aliases for the JSON shapes the servicing API exchanges.

These are documentation-grade hints only; the tests assert on plain dicts so
that an unexpected extra key never masks a real contract violation.
"""

from typing import Any, Dict, List, Optional, Tuple

# A JSON request payload or a resource returned in the `data` envelope.
Payload = Dict[str, Any]
Resource = Dict[str, Any]
Headers = Dict[str, str]
ResourceList = List[Resource]
PaginatedResult = Tuple[ResourceList, Dict[str, Any]]

# Convenience alias for the optional identifiers threaded through factories.
OptionalId = Optional[str]

__all__ = [
    "Payload",
    "Resource",
    "Headers",
    "ResourceList",
    "PaginatedResult",
    "OptionalId",
]
