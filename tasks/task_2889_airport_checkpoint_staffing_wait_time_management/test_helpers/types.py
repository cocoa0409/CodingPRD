"""Type aliases shared by the test helpers."""

from typing import Any, Dict, List, Optional, Tuple

# A parsed JSON object (the ``data`` payload of the standard envelope).
JsonDict = Dict[str, Any]

# A parsed JSON array of objects (the ``data`` payload of a list response).
JsonList = List[JsonDict]

# Outgoing HTTP request headers, including the identity pair of PRD §2.1.
Headers = Dict[str, str]

# Query-string parameters for a collection read.
QueryParams = Dict[str, Any]

# The (rows, meta) pair returned by the paginated validator.
PaginatedResult = Tuple[JsonList, JsonDict]

# A request payload; ``None`` means "send no body at all".
Payload = Optional[JsonDict]

__all__ = [
    "JsonDict",
    "JsonList",
    "Headers",
    "QueryParams",
    "PaginatedResult",
    "Payload",
]
