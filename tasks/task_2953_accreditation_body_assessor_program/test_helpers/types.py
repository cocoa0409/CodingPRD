"""Light structural aliases for the JSON documents under test.

These are documentation-grade aliases, not runtime validators: the API
returns plain JSON, and the tests assert on plain dictionaries.
"""

from typing import Any, Dict, List, Tuple

# A single decoded resource object out of the envelope's ``data`` field.
Resource = Dict[str, Any]

# A decoded list-endpoint body, split into rows and the ``meta`` object.
ResourceList = List[Resource]
PaginatedResult = Tuple[ResourceList, Dict[str, Any]]

# A request body ready to be sent as JSON.
Payload = Dict[str, Any]

# An ``X-User-ID`` / ``X-User-Role`` header pair.
Headers = Dict[str, str]

# The accumulating context a composite fixture builds up: named ids, header
# pairs and the last-read copy of each resource it created.
Context = Dict[str, Any]
