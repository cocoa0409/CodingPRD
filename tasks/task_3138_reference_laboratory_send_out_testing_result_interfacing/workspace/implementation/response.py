"""Response envelope helpers (PRD section 2.2, SCAFFOLD section 1.0)."""

import random
import string
from datetime import datetime, timezone


def request_id():
    """Server-generated unique request identifier starting with req_."""
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=18))
    return "req_" + suffix


def request_timestamp():
    """ISO 8601 UTC with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": request_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, response_type="object", pagination=None):
    """A 2xx envelope: meta, response_type ("object"/"array"), data."""
    if data is None:
        data = {}
    payload = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return payload


def error(error_id, message):
    """A 4xx envelope: meta carries only the request identifiers."""
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }