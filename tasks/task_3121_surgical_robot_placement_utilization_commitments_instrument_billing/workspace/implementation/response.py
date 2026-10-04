"""Response envelope helpers.

Envelope shape is taken verbatim from SCAFFOLD.yaml `response_envelope` and
PRD §2.2:

    { "meta": {"api_request_id": ..., "api_request_timestamp": ...},
      "response_type": "object" | "array" | "error",
      "data": ... }

List responses add `limit`, `offset`, `total_count`, `has_more` to `meta`
(field names and defaults from `response_envelope.pagination_fields` /
`pagination_defaults`).
"""

import random
import string
from datetime import datetime, timezone

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(18))


def now_iso():
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.2)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def meta_base():
    return {"api_request_id": request_id(), "api_request_timestamp": now_iso()}


def success(data, response_type="object", limit=None, offset=None,
            total_count=None, has_more=None):
    meta = meta_base()
    if limit is not None:
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total_count
        meta["has_more"] = has_more
    return {"meta": meta, "response_type": response_type, "data": data}


def list_success(payload, limit=None, offset=None, total_count=None):
    """A list response: `response_type` is "array" and the page is `data`."""
    return success(payload, response_type="array", limit=limit, offset=offset,
                   total_count=total_count,
                   has_more=(offset or 0) + len(payload) < (total_count or 0))


def error_body(error_id, message):
    return {"meta": meta_base(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}