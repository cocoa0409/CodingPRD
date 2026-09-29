"""
Type aliases for the payloads and response rows of the Design System Governance API.

These are documentation-grade aliases: they name the shapes that factories build
and that assertions read, so the rest of the suite can be read without guessing
whether a value is a header dict, a body dict or a decoded row.
"""

from typing import Any, Dict, List, Tuple

# A pair of identity headers plus Content-Type, as required by the API.
Headers = Dict[str, str]

# A JSON request body.
Payload = Dict[str, Any]

# One decoded resource row taken from the `data` member of the envelope.
Row = Dict[str, Any]

# A decoded list page: the rows plus the `meta` member carrying the
# pagination counters.
Page = Tuple[List[Row], Dict[str, Any]]

# Query parameters for a list or computed read.
Params = Dict[str, Any]
