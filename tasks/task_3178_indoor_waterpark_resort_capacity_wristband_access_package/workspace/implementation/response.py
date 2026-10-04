"""Response envelope helpers.

Envelope shapes come from PRD section 2.2:

    { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
      "response_type": "object" | "array" | "error",
      "data": ... }

List responses additionally carry `limit`, `offset`, `total_count` and
`has_more` inside `meta`.  Error responses carry only the two meta fields.
"""

import random
import string
from datetime import datetime, timezone

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    tail = "".join(random.choice(_ALPHABET) for _ in range(15))
    return "req_" + tail


def timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(now.microsecond // 1000)


def meta_base():
    return {"api_request_id": request_id(), "api_request_timestamp": timestamp()}


def success(data, response_type="object"):
    return {"meta": meta_base(), "response_type": response_type, "data": data}


def array(data, limit=None, offset=None, total_count=None):
    meta = meta_base()
    if limit is not None:
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total_count
        meta["has_more"] = (offset + len(data)) < total_count
    return {"meta": meta, "response_type": "array", "data": data}


def error_body(error_id, message):
    return {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }