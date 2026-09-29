"""Small structural aliases shared by the helper modules.

These are intentionally loose: the API returns plain JSON objects and the suite
asserts on individual keys rather than on whole schemas.
"""

from typing import Any, Dict, List, Tuple

# A decoded entity body (the inner ``data`` object of a success envelope).
Entity = Dict[str, Any]

# A decoded request body.
Payload = Dict[str, Any]

# Auth headers for one acting user.
Headers = Dict[str, str]

# The pair returned by the framework's paginated-response validator.
Page = Tuple[List[Entity], Dict[str, Any]]

__all__ = ["Entity", "Payload", "Headers", "Page"]
