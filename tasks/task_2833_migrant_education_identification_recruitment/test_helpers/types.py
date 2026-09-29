"""Lightweight aliases describing the shapes that flow between helpers and tests."""

from typing import Any, Dict, List, Optional, Tuple

# A JSON object as decoded from a response body or handed to a request body.
JsonObject = Dict[str, Any]
JsonList = List[Any]

# The two request headers every call must carry.
Headers = Dict[str, str]

# Query-string filters for a list endpoint.
Filters = Dict[str, Any]

# ``validate_paginated`` hands back the row list and the pagination block together.
PaginatedResult = Tuple[JsonList, JsonObject]

# Identifiers are server-minted UUID strings with no type prefix.
ResourceId = str

# Calendar dates are ISO 8601 ``YYYY-MM-DD``; instants carry three fractional digits.
CalendarDate = str
Instant = str

OptionalId = Optional[ResourceId]

__all__ = [
    "JsonObject",
    "JsonList",
    "Headers",
    "Filters",
    "PaginatedResult",
    "ResourceId",
    "CalendarDate",
    "Instant",
    "OptionalId",
]
