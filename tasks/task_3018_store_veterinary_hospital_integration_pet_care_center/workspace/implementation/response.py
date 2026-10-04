"""Response envelope helpers (PRD §2.2)."""

import random
import string
from datetime import datetime, timezone

ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(18))


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (datetime.now(timezone.utc).microsecond // 1000)


def meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    return {"meta": meta(), "response_type": "object", "data": data}, status


def ok_array(items, limit, offset, total_count, status=200):
    payload = {"meta": meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }), "response_type": "array", "data": items}
    return payload, status


def error(error_id, message):
    return {"meta": meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}, 1