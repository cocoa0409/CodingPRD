"""Light-weight type aliases for payloads and captured world state.

These exist purely to make the helper signatures readable; the API contract is
JSON, so nothing here is enforced at runtime.
"""

from typing import Any, Dict, List, Optional, Tuple

# A JSON request body or a resource returned in the envelope's ``data`` field.
Payload = Dict[str, Any]
Resource = Dict[str, Any]

# A list response unwrapped by ``validate_paginated``: (rows, meta).
PagedResult = Tuple[List[Resource], Dict[str, Any]]

# Auth headers as produced by ``build_user_headers``.
Headers = Dict[str, str]

# The accumulated identifiers and versions a composite fixture hands back.
# Keys in use across the suite:
#   partner_id, partner_version, product_id, premises_id, premises_version,
#   campaign_id, enrollment_id, enrollment_version, contractor_id, claim_id,
#   claim_version, dispatch_id, complaint_id, complaint_version
World = Dict[str, Any]

OptionalStr = Optional[str]
OptionalInt = Optional[int]
